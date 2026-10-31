#!/usr/bin/env python3
"""Dispatcher bench and concurrency (Phase 4a T5, spec section 8): the REAL entry `/usr/bin/python3 -I -S -X pycache_prefix=<tmp> hooks/shipm-hook <Event>`
in v1 mode over replayed fixture inputs (fake HOME, Shipmiracle shipmiracle/hooks/replay.py Home).
  B1  latency over >= 200 replayed fixture inputs: PreToolUse Bash/Edit p95 < 120 ms, every other event p95 < 70 ms (tests/shipmiracle_timing.robust: the limit
      or K x the spawn of `python -I -S -c pass` measured right before, in any of 3 attempts; a Mac under load does not fail the check, a regression does).
  B2  process count: ps-tree sampling of a run whose module sleeps (a stub hook): exactly 1 python process per event, no stray child after it ends.
  B3  concurrency: two PreToolUse events of ONE session started together: the flow lock serialises them, both decisions are right and no refusal count is lost.
  B4  8 parallel SubagentStart events keep 8 records in <project>.agents.json (the flock).
Numbers are printed as INFO lines. Run: python3 tests/hooks_bench_test.py"""
import collections, json, os, pathlib, shutil, subprocess, sys, tempfile, threading, time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
for k in ("SHIPMIRACLE_CONFIG", "SHIPMIRACLE_HOME", "SHIPMIRACLE_QUIET", "SHIPMIRACLE_HOOK_INJECT", "SHIPMIRACLE_HOOK_CAPTURE", "SHIPMIRACLE_HOOK_NO_LOAD", "CLAUDE_PROJECT_DIR", "SHIPMIRACLE_STATE", "SHIPMIRACLE_DEV", "SHIPMIRACLE_WS"):
    os.environ.pop(k, None)
BASE = pathlib.Path(os.path.realpath(tempfile.mkdtemp(prefix="hookbench-")))
os.environ.update(SHIPMIRACLE_TEST="1", SHIPMIRACLE_STATE=str(BASE / "inproc-state"))
import shipmiracle_timing as T  # noqa: E402
from shipmiracle.hooks import replay as R  # noqa: E402

SYSPY = R.SYSPY
fails = 0


def check(name, ok, info=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(info)[:1500]))
    fails += 0 if ok else 1


template = R.make_template(BASE)
home = R.Home(BASE, "bench", "v1", R.SYNTH_NAME, None, template, "/nonexistent", BASE / "pyc")
(home.ws / "config" / "flow.json").write_text('{"default": "strict"}')      # the suite measures the strict gate whatever level this checkout's own config/flow.json has (public checkouts ship warn)

# ----------------------------------------------------------------------------------------------- the 200 replayed inputs (whole sessions, in order)
fx = R.fixture_cases()
CORPUS = bool(list((pathlib.Path(R.__file__).resolve().parents[2] / "tests/fixtures/hooks/replay").glob("*.jsonl")))   # the recorded corpora (*.jsonl) are not part of the public export: then the suite needs only what the shipped fixtures give
sessions = collections.OrderedDict()
for c in fx:
    sessions.setdefault(c["session"], []).append(c)
picked, n = [], 0
for sid, cs in sessions.items():
    if n >= 220:
        break
    picked.append(cs)
    n += len(cs)
EVENTS = n
heavy_cls = lambda c: c["event"] == "PreToolUse" and (c.get("input") or {}).get("tool_name") in ("Bash", "Edit")


def run_all():
    """One pass over the picked sessions through the real entry; -> {"heavy": [secs], "other": [secs]} (state reset per session)."""
    out = {"heavy": [], "other": [], "by": collections.defaultdict(list)}
    for cs in picked:
        home.reset_state(cs[0].get("pre_state"))
        for c in cs:
            if c.get("transcript_text") is not None:
                tp = home.subst(str((c.get("input") or {}).get("transcript_path") or ""))
                if tp.startswith(str(home.tr) + "/"):
                    pathlib.Path(tp).write_text(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": c["transcript_text"]}]}}) + "\n")
            raw = (home.subst(c["raw"]) if "raw" in c else home.subst(json.dumps(c["input"]))).encode()
            t0 = time.perf_counter()
            home.call(c["event"], raw, c.get("env"))
            dt = time.perf_counter() - t0
            out["heavy" if heavy_cls(c) else "other"].append(dt)
            out["by"][c["event"] + ("/" + (c.get("input") or {}).get("tool_name", "") if c["event"] in ("PreToolUse", "PostToolUse") else "")].append(dt)
    return out


run_all()                                            # warm: bytecode cache, disk cache
best = {}
ref = lambda: T.spawn_ref(15, cmd=[SYSPY, "-I", "-S", "-c", "pass"])


def attempt_cls(cls):
    def m():
        r = run_all()
        best[cls] = r
        return T.p95(r[cls])
    return m


ok_h, rep_h, _ = T.robust(attempt_cls("heavy"), ref, 0.120, 5)
rh = best["heavy"]
print("INFO PreToolUse Bash/Edit: n=%d p50 %.0f ms p95 %.0f ms" % (len(rh["heavy"]), T.median(rh["heavy"]) * 1000, T.p95(rh["heavy"]) * 1000))
check("B1a >= 200 replayed fixture inputs through the real entry (v1): %d events, %d Bash/Edit PreToolUse" % (EVENTS, len(rh["heavy"])), (EVENTS >= 200 and len(rh["heavy"]) >= 20) if CORPUS else (EVENTS >= 1 and len(rh["heavy"]) >= 1), (EVENTS, len(rh["heavy"])))
check("B1b PreToolUse Bash/Edit p95 < 120 ms (or 5 x spawn of python -I -S -c pass): " + rep_h, ok_h, rep_h)
ok_o, rep_o, _ = T.robust(attempt_cls("other"), ref, 0.070, 5)
ro = best["other"]
print("INFO other events: n=%d p50 %.0f ms p95 %.0f ms" % (len(ro["other"]), T.median(ro["other"]) * 1000, T.p95(ro["other"]) * 1000))
for k, v in sorted(ro["by"].items()):
    print("INFO   %-28s n=%3d p50 %4.0f ms  p95 %4.0f ms  max %4.0f ms" % (k, len(v), T.median(v) * 1000, T.p95(v) * 1000, max(v) * 1000))
check("B1c every other event p95 < 70 ms (or 5 x spawn of python -I -S -c pass): " + rep_o, ok_o, rep_o)
home.kill_stubs()

# ----------------------------------------------------------------------------------------------- B2 process count
LAUNCH = BASE / "stub_hook.py"
LAUNCH.write_text('''import os, sys, time
sys.dont_write_bytecode = False
sys.path.insert(0, %r)
from shipmiracle.hooks import core
def slow(ctx):
    time.sleep(float(os.environ.get("STUB_SLEEP", "0.5")))
    return None
core.register("PreToolUse", "keep_awake", None, slow)       # a stub module: the real pipeline around it is unchanged
core.register("UserPromptSubmit", "keep_awake", None, slow)
core.register("Stop", "keep_going", None, slow)
core.register("SubagentStart", "agent_state", None, slow)
rc = core.main(sys.argv[1:])
sys.exit(rc if isinstance(rc, int) else 0)
''' % str(ROOT))


def ps_table():
    r = subprocess.run(["ps", "-A", "-o", "pid=,ppid=,command="], capture_output=True, text=True)
    rows = {}
    for l in r.stdout.splitlines():
        parts = l.split(None, 2)
        if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
            rows[int(parts[0])] = (int(parts[1]), parts[2])
    return rows


def tree(root, rows):
    kids = collections.defaultdict(list)
    for pid, (pp, _) in rows.items():
        kids[pp].append(pid)
    out, todo = [], [root]
    while todo:
        p = todo.pop()
        out.append(p)
        todo += kids.get(p, [])
    return out


def is_python(cmd):
    first = cmd.split()[0] if cmd.split() else ""
    return "python" in os.path.basename(first).lower()


counts = {}
raws = {"PreToolUse": {"hook_event_name": "PreToolUse", "session_id": "pc1", "cwd": "{P}", "tool_name": "Bash", "tool_input": {"command": "ls"}},
        "UserPromptSubmit": {"hook_event_name": "UserPromptSubmit", "session_id": "pc1", "cwd": "{P}", "prompt": "hi"},
        "Stop": {"hook_event_name": "Stop", "session_id": "pc1", "cwd": "{P}", "stop_hook_active": True},
        "SubagentStart": {"hook_event_name": "SubagentStart", "session_id": "pc1", "cwd": "{P}", "agent_id": "a1", "agent_type": "qa-engineer"}}
before_all = set(ps_table())
for ev, payload in raws.items():
    home.reset_state(None)
    p = subprocess.Popen([SYSPY, "-I", "-S", "-X", "pycache_prefix=" + str(home.pyc), str(LAUNCH), ev], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         env=home.env({"STUB_SLEEP": "0.6"}), cwd=str(home.proj))
    p.stdin.write(home.subst(json.dumps(payload)).encode()); p.stdin.close()
    mx, seen_cmds = 0, set()
    while p.poll() is None:
        rows = ps_table()
        if p.pid in rows:
            members = [x for x in tree(p.pid, rows) if x in rows]
            pys = [x for x in members if is_python(rows[x][1])]
            mx = max(mx, len(pys))
            seen_cmds |= {rows[x][1].split()[0].rsplit("/", 1)[-1] for x in members if x != p.pid}
        time.sleep(0.01)
    p.stdout.read(); p.stderr.read(); p.stdout.close(); p.stderr.close()
    counts[ev] = (mx, p.returncode, sorted(seen_cmds))
home.kill_stubs()
time.sleep(0.3)
after = ps_table()
strays = [pid for pid, (pp, cmd) in after.items() if pid not in before_all and str(BASE) in cmd]      # only processes of THIS sandbox: other suites run hooks at the same time under test-all
print("INFO process trees (max python processes, exit, other children seen):", json.dumps(counts))
check("B2a exactly 1 python process per event (the dispatcher), no module or helper starts another python: " + json.dumps({k: v[0] for k, v in counts.items()}),
      all(v[0] == 1 and v[1] == 0 for v in counts.values()), counts)
check("B2b no stray child process after the hook ended", strays == [], [(p, after[p]) for p in strays])

# ----------------------------------------------------------------------------------------------- B3 two PreToolUse for ONE session at once
big = {"file_path": "{P}/src/app.py", "old_string": "x = 1", "new_string": "x = 2\n" + "y = 3\n" * 40}
ok3, detail3 = True, []
for rnd in range(6):
    home.reset_state(None)
    sid = "cc%d" % rnd
    payload = home.subst(json.dumps({"hook_event_name": "PreToolUse", "session_id": sid, "cwd": "{P}", "tool_name": "Edit", "tool_input": big})).encode()
    gate = threading.Barrier(2)
    res = [None, None]

    def go(i):
        gate.wait()
        res[i] = home.call("PreToolUse", payload)
    ts = [threading.Thread(target=go, args=(i,)) for i in range(2)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    outs = [json.loads(r["out"] or b"{}") for r in res]
    denies = [((o.get("hookSpecificOutput") or {}).get("permissionDecision") == "deny") for o in outs]
    st = json.loads((home.state / ("flow.%s.json" % sid)).read_text()) if (home.state / ("flow.%s.json" % sid)).exists() else {}
    ref_total = sum((st.get("refusals") or {}).values())
    # strict: two refusals per kind, the third passes with a warning; two parallel calls must be counted as two
    good = all(denies) and ref_total == 2 and all(r["exit"] == 0 for r in res)
    ok3 = ok3 and good
    detail3.append((denies, ref_total))
check("B3 two parallel PreToolUse for the same session (6 rounds): both denied, the refusal counter says 2 (the flow lock serialised the read-modify-write), exit 0: " + str(detail3[:2]), ok3, detail3)

# ----------------------------------------------------------------------------------------------- B4 8 parallel SubagentStart
ok4, detail4 = True, []
for rnd in range(3):
    home.reset_state(None)
    gate = threading.Barrier(8)
    res = [None] * 8

    def go8(i):
        raw = home.subst(json.dumps({"hook_event_name": "SubagentStart", "session_id": "ag", "cwd": "{P}", "agent_id": "a%d-%d" % (rnd, i), "agent_type": "qa-engineer"})).encode()
        gate.wait()
        res[i] = home.call("SubagentStart", raw)
    ts = [threading.Thread(target=go8, args=(i,)) for i in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    f = home.state / (home.project + ".agents.json")
    recs = json.loads(f.read_text()) if f.exists() else {}
    ok4 = ok4 and len(recs) == 8 and all(r["exit"] == 0 for r in res) and not (home.state / (home.project + ".agents.json.tmp")).exists()
    detail4.append(len(recs))
check("B4 8 parallel SubagentStart (3 rounds) keep all 8 records in <project>.agents.json: " + str(detail4), ok4, detail4)

# ----------------------------------------------------------------------------------------------- B5 team gate cost (G9)
import flow_fixture as FF, resource  # noqa: E402
TEAM_BLOCK = "## Team\n<!-- team:begin -->\n| Role | Agent | Skills | Why |\n|---|---|---|---|\n| build | builder-a | - | because |\n<!-- team:end -->\n"


def b5_median_cpu(hook, table, n=12):
    """Median child CPU (user+sys, ms) of a PreToolUse Edit by a team member whose decision is already cached, in a project with or without a Team table."""
    p = FF.make_project("proj", agents={"builder-a": FF.AGENT_TEXT.format(n="builder-a", m="sonnet", r="build")})
    try:
        os.symlink(str(ROOT / "shipmiracle"), str(p.WSF / "shipmiracle"))
        if table:
            p.put("docs/SKILLS.md", "# Skills\n\n" + TEAM_BLOCK)
        d = {"hook_event_name": "PreToolUse", "session_id": "b5", "cwd": str(p.P), "tool_name": "Edit", "agent_id": "ag", "agent_type": "builder-a",
             "tool_input": {"file_path": str(p.P / "src/app.py"), "old_string": "x = 1", "new_string": "x = 2"}}
        run = lambda: subprocess.run(["bash", hook], input=json.dumps(d), capture_output=True, text=True, env=p.ENV, cwd=str(p.P))
        run()                                                    # the first call of the session parses the table (one reader load)
        out = []
        for _ in range(n):
            a = resource.getrusage(resource.RUSAGE_CHILDREN); run(); b = resource.getrusage(resource.RUSAGE_CHILDREN)
            out.append(((b.ru_utime - a.ru_utime) + (b.ru_stime - a.ru_stime)) * 1000)
        return sorted(out)[len(out) // 2]
    finally:
        p.cleanup()


for impl, hook in ([("legacy", str(FF.LEGACY_HOOK))] if FF.LEGACY_HOOK.exists() else []) + [("v1", str(FF.V1_HOOK))]:
    best = None
    for _attempt in range(6):                                    # a loaded Mac: the best of 6 attempts counts
        d_ = b5_median_cpu(hook, True) - b5_median_cpu(hook, False)
        best = d_ if best is None else min(best, d_)
        if best <= 5:
            break
    print("INFO B5 %s: cached team-member call costs %+.1f ms CPU more than the same call in a project without a table" % (impl, best))
    check("B5 team gate %s: a cached member call with a table adds <= 5 ms CPU (budget 3 ms + measurement slack): %+.1f ms" % (impl, best), best <= 5, best)

home.cleanup()
shutil.rmtree(BASE, ignore_errors=True)
print("ALL PASS" if not fails else "FAILED %d" % fails)
sys.exit(1 if fails else 0)
