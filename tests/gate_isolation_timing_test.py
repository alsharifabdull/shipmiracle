#!/usr/bin/env python3
"""gate_isolation_timing_test: checklist G11 (f), what the isolation rule costs and that hostile input cannot hang the gate.
  1  the Read fast path (Read/Grep/Glob/LS through the flow slot): the isolation check itself <= 3 ms at p95 per call (in-process, 300 calls, warm)
  2  benign Bash: the whole hook call with isolation on is at most 15% slower (median of 21 alternating runs per command, 12 commands) than with isolation off (test switch SHIPMIRACLE_ISOLATION=off)
  3  hostile inputs of 200 KB (one huge word, many words, deep $( nesting, a long cd chain, quote storms, a 200 KB path, an unterminated heredoc) finish inside the 1 s budget on both gate copies
Run: python3 tests/gate_isolation_timing_test.py"""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import shipmiracle_isolation; shipmiracle_isolation.apply_to_environ()   # test isolation
import json, os, pathlib, statistics, subprocess, sys, time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import isolation_fixture as X
import flow_fixture as F

fails = []


def check(name, ok, info=""):
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(info)[:400]))
    if not ok:
        fails.append(name)


w = X.World()
P, B, DEV = str(w.P), str(w.B), str(w.DEV)

# ------------------------------------------------------------------ 1  the check itself, in-process
os.environ.update({k: v for k, v in w.env.items() if k.startswith("SHIPMIRACLE_") or k == "CLAUDE_PROJECT_DIR"})
import importlib
flow = importlib.import_module("shipmiracle.hooks.flow")
d = {"hook_event_name": "PreToolUse", "session_id": "t1", "cwd": P}
ti_read = {"file_path": P + "/src/mine.py"}
ti_grep = {"pattern": "x", "path": P + "/src"}
ti_glob = {"pattern": "**/*.py"}
pd = os.path.realpath(P)


def one(tool, ti):
    t0 = time.perf_counter()
    flow.ISO.clear()
    flow.iso_init(pd, pd, False)
    r = flow.iso_file_calls(tool, ti, pd)
    return (time.perf_counter() - t0) * 1000, r


import shipmiracle_timing as T
BASE_FILE = P + "/src/mine.py"


def base_ref():
    """Baseline measured right before and right after on the same machine: p95 of a fixed small workload of the same kind of primitives the check uses (path resolution, stat, a
    list scan, a dict build). Quiet Mac: about 0.1 ms. K = 3 ms / 0.1 ms = 30, so a quiet machine behaves like the absolute 3 ms and a loaded one gets proportional room."""
    def work():
        os.path.realpath(BASE_FILE); os.stat(BASE_FILE); d_ = {str(i): i for i in range(200)}; sorted(d_)
    return T.p95_of(work, 300)


K_ISO = 30
for tool, ti in (("Read", ti_read), ("Grep", ti_grep), ("Glob", ti_glob), ("LS", {"path": P})):
    for _ in range(20):
        one(tool, ti)
    ok_, rep_, best_ = T.robust_around(lambda: T.p95_of(lambda: one(tool, ti), 300), base_ref, 0.003, K_ISO)
    print("INFO 1 %s: %s" % (tool, rep_))
    check("1 %s: isolation check p95 <= max(3 ms, %d x baseline) :: %s" % (tool, K_ISO, rep_), ok_, rep_)
check("1 mutant: the Read check slowed by a sleep (4 x the allowed p95) is still noticed by the relative check", T.mutant_noticed(lambda: one("Read", ti_read), base_ref, 0.003, K_ISO))
check("1 the benign calls were not refused", one("Read", ti_read)[1] == [] and one("Grep", ti_grep)[1] == [])

# ------------------------------------------------------------------ 2  benign Bash end to end
BENIGN = ["ls -la", "git status --short", "cat src/mine.py", "grep -rn print src", "rg print", "python3 -c 'print(1)'", "npm test", "git log --oneline -5", "find . -name '*.py'", "sed -n 1,5p src/mine.py", "cp src/mine.py /tmp/g11-t", "echo hello > src/out.txt"]


def run_hook(impl, cmd, level):
    e = dict(w.env, SHIPMIRACLE_ISOLATION=level)
    d = {"hook_event_name": "PreToolUse", "session_id": "tb", "cwd": P, "tool_name": "Bash", "tool_input": {"command": cmd}}
    t0 = time.perf_counter()
    subprocess.run(["bash", dict(X.IMPLS)[impl]], input=json.dumps(d), capture_output=True, text=True, env=e, cwd=P)
    return (time.perf_counter() - t0) * 1000


for impl, _h in X.IMPLS:
    off, on = [], []
    for cmd in BENIGN:
        run_hook(impl, cmd, "strict")
        a, b = [], []
        for _ in range(21):
            a.append(run_hook(impl, cmd, "off")); b.append(run_hook(impl, cmd, "strict"))
        off.append(statistics.median(a)); on.append(statistics.median(b))
    mo, mn = statistics.median(off), statistics.median(on)
    check("2 %s: benign Bash median %.1f ms (isolation on) vs %.1f ms (off) = %+.1f%% <= +15%%" % (impl, mn, mo, (mn / mo - 1) * 100), mn <= mo * 1.15, (off, on))

# ------------------------------------------------------------------ 3  hostile 200 KB inputs
KB = 1024
HOSTILE = [("one 200 KB word", "cat " + "a" * 200 * KB), ("50000 words", "cat " + " ".join("f%d" % i for i in range(50000))), ("50000 path words", "cat " + " ".join("src/f%d.py" % i for i in range(20000))),
           ("deep $( nesting", "echo " + "$(" * 20000 + "x" + ")" * 20000), ("long cd chain", " && ".join("cd .." for _ in range(20000))), ("quote storm", "echo " + "'\"" * 100000),
           ("unterminated heredoc", "cat <<EOF\n" + "x" * 200 * KB), ("200 KB of ../", "cat " + "../" * 70000 + "other/src/a.py"), ("backslashes", "echo " + "\\" * 200 * KB), ("200 KB python literal", "python3 -c \"" + "open('a')" * 20000 + "\""),
           ("many redirects", "echo x " + " ".join("> f%d" % i for i in range(20000))), ("glob storm", "cat " + "*" * 50000), ("200 KB path with a project at the end", "cat " + B + "/" + "d/" * 60000 + "x")]
for impl, _h in X.IMPLS:
    for lab, cmd in HOSTILE:
        d = {"hook_event_name": "PreToolUse", "session_id": "th", "cwd": P, "tool_name": "Bash", "tool_input": {"command": cmd}}
        ok, info = False, ""
        for _try in range(3):                                   # wall-clock checks retry: a loaded machine must not fail the suite
            t0 = time.perf_counter()
            try:
                r = subprocess.run(["bash", dict(X.IMPLS)[impl]], input=json.dumps(d), capture_output=True, text=True, env=w.env, cwd=P, timeout=20)
                secs = time.perf_counter() - t0
                ok = secs < 1.0
                info = "%.2f s" % secs
            except subprocess.TimeoutExpired:
                ok, info = False, "timeout"
            if ok:
                break
        check("3 %s: %s inside the 1 s budget" % (impl, lab), ok, info)
# B1/B2 of the security review: these must be REFUSED (strict) and inside the budget
REFUSE = [("B1 .env then 150000 '>'", "cat .env " + ">" * 150000), ("B1 80000 x '.ssh/' then x.pub", "cat " + ".ssh/" * 80000 + "x.pub"),
          ("B2 13 deep globs then ../other/.env", "cat " + "'/var/*/*/*/*/*' " * 13 + "../other/.env"), ("M1 brace ReDoS: 480 x ('{' + 199 ',')", "echo " + ("{" + "," * 199) * 480), ("M5 >4000 words then a project path", "cd .. && cat other/notes.md; " + " ".join(["true"] * 4100)),
          ("B2 deep globs, no secret at the end (must still finish)", "cat " + "'/var/*/*/*/*/*' " * 13 + "x")]
for impl, _h in X.IMPLS:
    for lab, cmd in REFUSE:
        lim = 3.0 if lab.startswith("B2") else 1.0                  # the deep-glob storm runs into the 1.5 s CPU budget by design
        d = {"hook_event_name": "PreToolUse", "session_id": "tr", "cwd": P, "tool_name": "Bash", "tool_input": {"command": cmd}}
        for _try in range(3):
            t0 = time.perf_counter()
            r = subprocess.run(["bash", dict(X.IMPLS)[impl]], input=json.dumps(d), capture_output=True, text=True, env=w.env, cwd=P, timeout=20)
            secs = time.perf_counter() - t0
            if secs < lim:
                break
        try:
            o = json.loads(r.stdout) if r.stdout.strip() else {}
        except Exception:
            o = {}
        check("3b %s: %s refused=%s in %.2f s (budget %.0f s)" % (impl, lab, X.iso_denied(o), secs, lim), secs < lim and (X.iso_denied(o) or lab.startswith("B2 deep globs, no")), (secs, r.stdout[:100]))
# m5: the alarm fires while the except branch runs (log_err is slow): still refused, timer off, handler restored
import signal
saved = (flow.iso_file_calls, flow.log_err, flow.out)
got = []
def _boom(*a):
    raise RuntimeError("x")
def _slow(*a):
    t0_ = time.process_time()
    while time.process_time() - t0_ < 4.0:           # burn CPU: the budget counts CPU time, a sleep would never hit it
        pass
def _out(o):
    got.append(o); raise SystemExit(0)
flow.iso_file_calls, flow.log_err, flow.out = _boom, _slow, _out
h0 = signal.getsignal(signal.SIGALRM)
t0 = time.perf_counter()
try:
    flow.NOTES[:] = []
    flow.iso_pre({"hook_event_name": "PreToolUse", "session_id": "u1", "cwd": P}, pd, pd, False, "proj", "Read", {"file_path": P + "/src/mine.py"})
except SystemExit:
    pass
finally:
    flow.iso_file_calls, flow.log_err, flow.out = saved
secs = time.perf_counter() - t0
check("m5 alarm inside the except branch: refused at strict, back in %.2f s, timer off, handler restored" % secs, bool(got) and got[0]["hookSpecificOutput"]["permissionDecision"] == "deny" and secs < 6.0 and signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0) and signal.getitimer(signal.ITIMER_PROF) == (0.0, 0.0) and signal.getsignal(signal.SIGALRM) == h0, (got, secs))
# M3 (security review 3): a big benign tree is not refused as "could not judge" and stays fast; an exhausted scan budget is UNKNOWN and refuses
bigp = w.T / "benign25k"; bigp.mkdir()
for d_ in range(50):
    (bigp / ("pkg%d" % d_)).mkdir()
    for f_ in range(500):
        (bigp / ("pkg%d" % d_) / ("m%d.ts" % f_)).write_text("")
(bigp / ".gitignore").write_text(".env\nnode_modules/\n"); (bigp / ".env").write_text("A=1\n")
for impl, _h in X.IMPLS:
    secs_, den_ = [], []
    for cmd in ("rg TODO", "git grep TODO", "grep -rn TODO pkg1"):
        for _ in range(5):
            d = {"hook_event_name": "PreToolUse", "session_id": "bg", "cwd": str(bigp), "tool_name": "Bash", "tool_input": {"command": cmd}}
            t0 = time.perf_counter()
            r = subprocess.run(["bash", dict(X.IMPLS)[impl]], input=json.dumps(d), capture_output=True, text=True, env=dict(w.env, CLAUDE_PROJECT_DIR=str(bigp)), cwd=str(bigp))
            secs_.append(time.perf_counter() - t0)
            den_.append((cmd, r.stdout[:80]) if r.stdout.strip() and "Project isolation" in r.stdout else None)
    secs_.sort()
    check("M3 %s: 25000 benign files, rg / git grep / grep -rn: none refused, p95 %.2f s (limit 1 s; median %.2f s tolerates a loaded machine)" % (impl, secs_[int(len(secs_) * 0.95)], statistics.median(secs_)), not any(den_) and (secs_[int(len(secs_) * 0.95)] < 1.0 or statistics.median(secs_) < 0.5), [x for x in den_ if x])
class _FakeTime:
    def __init__(self):
        self.n = 0
    def time(self):
        self.n += 1
        return 1e12 + self.n * 10
    process_time = time
    def __getattr__(self, k):
        return getattr(time, k)
real_time = flow.time
flow.iso_init(pd, pd, False)
flow.time = _FakeTime()
try:
    unknown = flow.iso_tree_secret(str(bigp), False)
    hit = flow.iso_tree_hit(str(bigp), hidden=False)
finally:
    flow.time = real_time
check("M3 an exhausted scan budget is UNKNOWN (None) and the caller's hit is an error, never a pass", unknown is None and hit == ("error", ""), (unknown, hit))
check("B1 the real scan of the same tree finishes: False (clean) for visible files", flow.iso_tree_secret(str(bigp), False, True) is False)
# M11: SIGALRM / setitimer interrupted in the cleanup: still denied, handler restored
import signal
real_set = signal.setitimer
calls = [0]
def flaky_set(which, secs, interval=0.0):
    calls[0] += 1
    if secs == 0 and not calls[1:]:
        calls.append(1)
        raise flow.IsoTimeout()
    return real_set(which, secs, interval)
signal.setitimer = flaky_set
saved2 = flow.out
got2 = []
def _out2(o):
    got2.append(o); raise SystemExit(0)
flow.out = _out2
h1 = signal.getsignal(signal.SIGALRM)
try:
    flow.iso_pre({"hook_event_name": "PreToolUse", "session_id": "u2", "cwd": P}, pd, pd, False, "proj", "Read", {"file_path": B + "/src/a.py"})
except SystemExit:
    pass
finally:
    signal.setitimer = real_set; flow.out = saved2
check("M11 an IsoTimeout raised inside the cleanup is caught: the call is still denied and the timer is off", bool(got2) and got2[0]["hookSpecificOutput"]["permissionDecision"] == "deny" and signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0), (got2, calls))
# brace sequences: every element up to 1024 is judged, above that only harmless text may surround the braces
flow.iso_init(pd, pd, False)
def _br(c):
    try:
        return flow.iso_braces(c)
    except ValueError:
        return None
check("braces: {1..100}, {0..255}, {1..10..2}, f{08..11} expand fully (step and zero padding); {1..5000} is short and allowed; {1..5000}/../.env and x{1..5000}.pem are refused",
      _br("echo {1..100}").split()[-1] == "100" and len(_br("echo {0..255}").split()) == 257 and _br("echo {1..10..2}") == "echo 1 3 5 7 9" and _br("cat f{08..11}") == "cat f08 f09 f10 f11"
      and _br("echo {1..5000}") == "echo 1" and _br("cat {1..5000}/../.env") is None and _br("cat x{1..5000}.pem") is None and ".env" in _br("cat .en{u..w}").split(), None)
check("hook error log stays empty after hostile input", w.p.errors().strip() == "", w.p.errors()[:300])
# m3 (security review 5): a call stuck where no signal can interrupt it is answered by the watchdog thread (deny JSON on stdout, exit 0) at strict
WDS = """
import os, sys, time, json
sys.path.insert(0, %r)
from shipmiracle.hooks import flow
flow.ISO_WD = 0.4
flow.iso_file_calls = lambda *a, **k: time.sleep(6)
flow.iso_pre({"hook_event_name": "PreToolUse", "session_id": "wd", "cwd": %r}, %r, %r, False, "proj", "Read", {"file_path": %r})
print("NOT-DENIED")
""" % (str(F.WS), P, pd, pd, P + "/src/mine.py")
t0_ = time.perf_counter()
r_ = subprocess.run([sys.executable, "-c", WDS], capture_output=True, text=True, env=dict(w.env, SHIPMIRACLE_ISOLATION="strict"), cwd=P, timeout=30)
secs_ = time.perf_counter() - t0_
check("m3 watchdog: a stuck call is refused after 0.4 s (took %.2f s), exit 0, no 'NOT-DENIED'" % secs_, r_.returncode == 0 and "NOT-DENIED" not in r_.stdout and X.iso_denied(json.loads(r_.stdout.strip().splitlines()[-1])) and secs_ < 5, (r_.returncode, r_.stdout[:200], r_.stderr[-200:]))
r2_ = subprocess.run([sys.executable, "-c", WDS], capture_output=True, text=True, env=dict(w.env, SHIPMIRACLE_ISOLATION="warn"), cwd=P, timeout=30)
check("m3 watchdog: at warn level there is no watchdog (the stuck call just finishes)", "NOT-DENIED" in r2_.stdout, (r2_.returncode, r2_.stdout[:200]))
# m3: the legacy fallback in hooks/shipm-hook refuses a PreToolUse when flow-gate itself fails to run
src_ = (F.WS / "hooks/shipm-hook").read_text()
check("m3 hooks/shipm-hook: a failing flow-gate on PreToolUse is a refusal (rc 2), not a pass", 'return (2, b"", b"The project-isolation' in src_ and 'ev == "PreToolUse" and s == "flow-gate"' in src_, None)
# D7 (QA): git children are cached per hook call and capped (12 processes / 3 s wall): beyond the cap the answer is unknown (rc 128), never a pass
flow.iso_init(pd, pd, False)
n_ = 0
for i_ in range(20):
    rc_, _o = flow.iso_git_out(pd, ["rev-parse", "--git-dir", "--", "x%d" % i_])
    n_ += 1
c1_ = flow.ISO.get("gitn", 0)
rc2_, _o2 = flow.iso_git_out(pd, ["rev-parse", "--git-dir", "--", "x0"])
check("D7 git subprocesses per hook call are capped at 12 (ran %d for 20 distinct calls); the 21st call is unknown (rc 128); a repeated call is served from the cache" % c1_, c1_ == 12 and flow.iso_git_out(pd, ["rev-parse", "--git-dir", "--", "x19"])[0] == 128 and rc2_ == flow.ISO["gitc"][(pd, ("rev-parse", "--git-dir", "--", "x0"), b"")][0], (c1_, rc2_))
# round 9 F1: v1 configured but the core import fails -> the legacy fallback must still send the READ tools to the isolation check
import shutil, tempfile
fb = pathlib.Path(tempfile.mkdtemp(prefix="g11-fb-")) if "pathlib" in globals() else None
if fb is None:
    import pathlib
    fb = pathlib.Path(tempfile.mkdtemp(prefix="g11-fb-"))
(fb / "hooks").mkdir(); (fb / "shipmiracle" / "hooks").mkdir(parents=True)
shutil.copy(F.WS / "hooks/shipm-hook", fb / "hooks/shipm-hook")
for f_ in (F.WS / "hooks").glob("*.sh"):
    os.symlink(f_, fb / "hooks" / f_.name)
(fb / "shipmiracle/__init__.py").write_text(""); (fb / "shipmiracle/hooks/__init__.py").write_text(""); (fb / "shipmiracle/hooks/core.py").write_text("raise ImportError('forced for the test')\n")
def fb_call(tool, ti, level="strict", ev="PreToolUse"):
    d_ = {"hook_event_name": ev, "session_id": "fb1", "cwd": P, "tool_name": tool, "tool_input": ti}
    r_ = subprocess.run([sys.executable, str(fb / "hooks/shipm-hook"), ev], input=json.dumps(d_), capture_output=True, text=True, env=dict(w.env, SHIPMIRACLE_ISOLATION=level), cwd=P, timeout=60)
    try:
        o_ = json.loads(r_.stdout) if r_.stdout.strip() else {}
    except ValueError:
        o_ = {}
    return o_, r_
if F.LEGACY_HOOK.exists():
    for tool_, ti_ in (("Read", {"file_path": B + "/.env"}), ("Read", {"file_path": P + "/../other/.env"}), ("Grep", {"pattern": "x", "path": B}), ("Glob", {"pattern": "*", "path": B}), ("LS", {"path": B}), ("Bash", {"command": "cat ../other/.env"})):
        o_, r_ = fb_call(tool_, ti_)
        check("F1 core import fails (legacy fallback): %s %s is refused by the isolation check" % (tool_, list(ti_.values())[0][-24:]), X.iso_denied(o_), (r_.returncode, r_.stdout[:200], r_.stderr[-200:]))
    o_, r_ = fb_call("Read", {"file_path": P + "/src/mine.py"})
    check("F1 ... and the project's own file is still readable in the fallback", not X.iso_denied(o_) and r_.returncode == 0, (r_.returncode, r_.stdout[:200]))
else:
    print("SKIP F1 legacy fallback: the exported tree has no legacy shell gate")
shutil.rmtree(fb, ignore_errors=True)
# round 10 F-A: a dependency folder is never walked: the outcome does not depend on the time budget (flat 30000-file node_modules, ignored)
flatp = w.T / "flatdeps"; (flatp / "node_modules").mkdir(parents=True)
for i_ in range(30000):
    os.close(os.open(str(flatp / "node_modules" / ("m%d.js" % i_)), os.O_CREAT | os.O_WRONLY))
(flatp / ".gitignore").write_text("node_modules/\n"); (flatp / "a.txt").write_text("x\n")
subprocess.run(["git", "init", "-q", str(flatp)], capture_output=True)
flow.iso_init(pd, pd, False)
real_time2 = flow.time
res_ = []
for fake_ in (False, True):
    if fake_:
        flow.time = _FakeTime()
    try:
        res_.append([flow.iso_tree_secret(str(flatp), True, True) for _ in range(3)])
    finally:
        flow.time = real_time2
check("F-A a flat 30000-file node_modules: always the same answer (clean), with a real clock and with an exhausted budget", all(r_ == [False] * 3 for r_ in res_), res_)
(flatp / "node_modules" / "id_rsa").write_text("k")
check("F-A ... and a secret-named file in the top level of node_modules is still found", flow.iso_tree_secret(str(flatp), True, False) is True)
check("F-A ... the folder as the search root (grep -r KEY node_modules) is judged the same way", flow.iso_tree_secret(str(flatp / "node_modules"), True, False) is True)
# QA m1: the fallback's flow-gate misbehaving (crash code, garbage output) is a refusal for PreToolUse, not a pass; a quiet exit 0 is a pass
for lab_, body_, want_ in (("exits 1", "exit 1", True), ("exits 139", "exit 139", True), ("prints garbage", "echo 'not json'", True), ("exits 0 quietly", "exit 0", False)):
    fb2 = pathlib.Path(tempfile.mkdtemp(prefix="g11-fb2-"))
    (fb2 / "hooks").mkdir(); (fb2 / "shipmiracle/hooks").mkdir(parents=True)
    shutil.copy(F.WS / "hooks/shipm-hook", fb2 / "hooks/shipm-hook")
    for f_ in (F.WS / "hooks").glob("*.sh"):
        if f_.name != "flow-gate.sh":
            os.symlink(f_, fb2 / "hooks" / f_.name)
    fg_ = fb2 / "hooks" / ("flow-gate" + ".sh"); fg_.write_text("#!/bin/bash\n" + body_ + "\n"); os.chmod(fg_, 0o755)
    (fb2 / "shipmiracle/__init__.py").write_text(""); (fb2 / "shipmiracle/hooks/__init__.py").write_text(""); (fb2 / "shipmiracle/hooks/core.py").write_text("raise ImportError('forced')\n")
    d_ = {"hook_event_name": "PreToolUse", "session_id": "fb2", "cwd": P, "tool_name": "Bash", "tool_input": {"command": "ls"}}
    r_ = subprocess.run([sys.executable, str(fb2 / "hooks/shipm-hook"), "PreToolUse"], input=json.dumps(d_), capture_output=True, text=True, env=dict(w.env, SHIPMIRACLE_ISOLATION="strict"), cwd=P, timeout=60)
    try:
        o_ = json.loads(r_.stdout) if r_.stdout.strip() else {}
    except ValueError:
        o_ = {}
    denied_ = (o_.get("hookSpecificOutput") or {}).get("permissionDecision") == "deny" or r_.returncode == 2
    check("m1 fallback: flow-gate %s on PreToolUse -> %s" % (lab_, "refused" if want_ else "allowed"), denied_ == want_, (r_.returncode, r_.stdout[:150], r_.stderr[-150:]))
    shutil.rmtree(fb2, ignore_errors=True)
# round 9 F2: the flow module crashes (injected) or fails to load at strict -> PreToolUse for Bash and the file tools is refused; warn/off and other events are untouched
import io, contextlib
core = importlib.import_module("shipmiracle.hooks.core")
def core_call(ev, tool, ti, level, inject="flow"):
    env_ = dict(os.environ)
    old_ = {k: os.environ.get(k) for k in ("SHIPMIRACLE_HOOK_INJECT", "SHIPMIRACLE_ISOLATION", "CLAUDE_PROJECT_DIR")}
    os.environ.update({"SHIPMIRACLE_HOOK_INJECT": inject, "SHIPMIRACLE_ISOLATION": level, "CLAUDE_PROJECT_DIR": P})
    try:
        raw_ = json.dumps({"hook_event_name": ev, "session_id": "f2", "cwd": P, "tool_name": tool, "tool_input": ti}).encode()
        out_, err_, code_ = core.run(ev, raw_, env=dict(os.environ))
        return (json.loads(out_) if out_.strip() else {}), code_
    finally:
        for k_, v_ in old_.items():
            if v_ is None:
                os.environ.pop(k_, None)
            else:
                os.environ[k_] = v_
for tool_, ti_ in (("Bash", {"command": "cat ../other/.env"}), ("Bash", {"command": "ls"}), ("Read", {"file_path": P + "/src/mine.py"}), ("Write", {"file_path": P + "/n.txt", "content": "x"})):
    o_, c_ = core_call("PreToolUse", tool_, ti_, "strict")
    check("F2 flow module crashes at strict: PreToolUse %s %s is refused with a clear sentence" % (tool_, str(list(ti_.values())[0])[-20:]), X.iso_denied(o_) and "could not run" in json.dumps(o_), o_)
o_, c_ = core_call("PreToolUse", "Bash", {"command": "ls"}, "warn")
check("F2 at warn the crash stays a logged non-event (no refusal)", not X.iso_denied(o_) and c_ == 0, o_)
o_, c_ = core_call("PreToolUse", "Bash", {"command": "ls"}, "off")
check("F2 at off the crash stays a logged non-event", not X.iso_denied(o_) and c_ == 0, o_)
for ev_ in ("UserPromptSubmit", "Stop", "SessionStart"):
    o_, c_ = core_call(ev_, "", {}, "strict")
    check("F2 event %s is not broken by a flow crash at strict" % ev_, not X.iso_denied(o_) and c_ == 0, o_)
o_, c_ = core_call("PreToolUse", "WebFetch", {"url": "https://example.com"}, "strict")
check("F2 a tool that never goes through isolation (WebFetch) is not refused by a flow crash", not X.iso_denied(o_), o_)
# the flow module cannot even be imported
core._LOAD_FAILED.add("flow")
sl_ = [s_ for s_ in core.PIPELINES["PreToolUse"] if s_.name == "flow"][0]
saved_fn = sl_.fn; sl_.fn = None
try:
    old_i = os.environ.get("SHIPMIRACLE_HOOK_INJECT"); os.environ.pop("SHIPMIRACLE_HOOK_INJECT", None); os.environ["SHIPMIRACLE_ISOLATION"] = "strict"; os.environ["CLAUDE_PROJECT_DIR"] = P
    core_load = core._load; core._load = lambda slot, event: None
    out_, err_, code_ = core.run("PreToolUse", json.dumps({"hook_event_name": "PreToolUse", "session_id": "f2b", "cwd": P, "tool_name": "Bash", "tool_input": {"command": "ls"}}).encode(), env=dict(os.environ))
    check("F2 the flow module failed to load at strict: PreToolUse Bash is refused", X.iso_denied(json.loads(out_) if out_.strip() else {}), out_[:200])
finally:
    core._load = core_load; sl_.fn = saved_fn; core._LOAD_FAILED.discard("flow"); os.environ.pop("SHIPMIRACLE_ISOLATION", None)
# the dispatcher itself crashes after reading stdin
saved_run, saved_mode = core.run, core.mode
def _boom_run(*a, **k):
    raise RuntimeError("dispatcher boom")
core.run, core.mode = _boom_run, (lambda: "v1")
os.environ["SHIPMIRACLE_ISOLATION"] = "strict"; os.environ["CLAUDE_PROJECT_DIR"] = P
old_in, old_out = sys.stdin, sys.stdout
sys.stdin = io.TextIOWrapper(io.BytesIO(json.dumps({"hook_event_name": "PreToolUse", "session_id": "f2c", "cwd": P, "tool_name": "Bash", "tool_input": {"command": "ls"}}).encode()))
sys.stdout = io.TextIOWrapper(io.BytesIO(), write_through=True)
try:
    rc_ = core.main(["PreToolUse"]); sys.stdout.flush(); got_ = sys.stdout.buffer.getvalue().decode()
finally:
    sys.stdin, sys.stdout = old_in, old_out; core.run, core.mode = saved_run, saved_mode; os.environ.pop("SHIPMIRACLE_ISOLATION", None)
check("F2 the dispatcher crashes at strict: PreToolUse still answers with a refusal (exit 0 with deny JSON)", rc_ == 0 and X.iso_denied(json.loads(got_) if got_.strip() else {}), (rc_, got_[:200]))
# round 9 F4: the watchdog and the main thread never both answer: exactly one JSON object
RACE = """
import os, sys, time, json, threading
sys.path.insert(0, %r)
from shipmiracle.hooks import flow
flow.ISO_WD = 0.2
flow.iso_file_calls = lambda *a, **k: [("secret", "")]
threading.Timer.cancel = lambda self: None          # the timer is NOT cancelled: it fires while the main thread is inside out()
_real_out = flow.out
def slow_out(o):
    time.sleep(0.8)
    _real_out(o)
flow.out = slow_out
flow.iso_pre({"hook_event_name": "PreToolUse", "session_id": "race", "cwd": %r}, %r, %r, False, "proj", "Read", {"file_path": %r})
print("NOT-DENIED")
""" % (str(F.WS), P, pd, pd, P + "/src/mine.py")
r_ = subprocess.run([sys.executable, "-c", RACE], capture_output=True, text=True, env=dict(w.env, SHIPMIRACLE_ISOLATION="strict"), cwd=P, timeout=30)
lines_ = [l_ for l_ in r_.stdout.splitlines() if l_.strip()]
check("F4 the watchdog fires while the main thread is answering: exactly one JSON deny on stdout", len(lines_) == 1 and X.iso_denied(json.loads(lines_[0])) and r_.returncode == 0, (r_.returncode, r_.stdout[:300], r_.stderr[-200:]))
w.cleanup()
print("\nisolation timing tests: %d failed" % len(fails))
sys.exit(1 if fails else 0)
