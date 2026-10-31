#!/usr/bin/env python3
"""P4 security remediation (review of snapshot fae0a56), the non-gate findings. Temp folders only; the real state, HOME and workspace are never touched.
  L2  the shadow child writes nothing outside its throw-away folder (the limit_wait <ws>/reports log), checked with a fingerprint of a scratch workspace.
  L3  state-folder and project-folder writes never follow a symlink and never leave the state/project folder (append_line, lock files, record, user-active,
      model_switch, save_plan, stop_fast).
  L4  `shipm hooks replay --report` writes only a .md inside the repo / state / temp folder, never over a file that is not an earlier report (exit 2).
  L5  every docs/owner-steps/*.sh refuses under CLAUDECODE=1 (and writes nothing).
  L8  at most 4 shadow children run at once; the rest are skipped and counted in a hook_shadow_skipped event.
Run: python3 tests/hooks_p4sec_test.py"""
import hashlib, json, os, pathlib, shutil, stat, subprocess, sys, tempfile, threading, time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
T = pathlib.Path(os.path.realpath(tempfile.mkdtemp(prefix="p4sec-")))
HOME = T / "home"; STATE = T / "state"; CFG = T / "cfg"
for d in (HOME / ".claude" / "plans", STATE, CFG, HOME / "Developer"):
    d.mkdir(parents=True, exist_ok=True)
for k in ("SHIPMIRACLE_CONFIG", "SHIPMIRACLE_HOME", "SHIPMIRACLE_QUIET", "SHIPMIRACLE_HOOK_INJECT", "SHIPMIRACLE_HOOK_CAPTURE", "SHIPMIRACLE_HOOK_NO_LOAD", "CLAUDE_PROJECT_DIR", "SHIPMIRACLE_STATE", "SHIPMIRACLE_DEV", "SHIPMIRACLE_WS",
          "SHIPMIRACLE_SHADOW_PIDFILE", "SHIPMIRACLE_SHADOW_TEST_RUNNER", "SHIPMIRACLE_SHADOW_LIMIT", "SHIPMIRACLE_SHADOW_MAX"):
    os.environ.pop(k, None)
os.environ.update(SHIPMIRACLE_TEST="1", HOME=str(HOME), SHIPMIRACLE_HOME=str(HOME), SHIPMIRACLE_STATE=str(STATE), SHIPMIRACLE_CONFIG=str(CFG), SHIPMIRACLE_DEV=str(HOME / "Developer"), SHIPMIRACLE_WS=str(T / "ws"))
from shipmiracle.hooks import core, io as hio, shadow as S, replay as R  # noqa: E402
import shipmiracle.hooks.project as P  # noqa: E402
import shipmiracle.hooks.agents as A  # noqa: E402
import shipmiracle.hooks.activity as ACT  # noqa: E402

SYSPY = "/usr/bin/python3" if os.path.exists("/usr/bin/python3") else sys.executable
fails = 0


def check(name, ok, info=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(info)[:1200]))
    fails += 0 if ok else 1


def fp(root):
    h = hashlib.sha256()
    for dp, dns, fns in os.walk(str(root)):
        dns.sort()
        h.update(("D" + os.path.relpath(dp, str(root)) + "\n").encode())
        for f in sorted(fns):
            p = os.path.join(dp, f)
            st = os.lstat(p)
            h.update(("F%s %o %d\n" % (f, st.st_mode, st.st_mtime_ns)).encode())
            if stat.S_ISREG(st.st_mode):
                h.update(open(p, "rb").read())
    return h.hexdigest()


def victim(name, text="KEEP-ME\n", mode=0o644, age=1_500_000_000):
    p = T / "outside" / name
    p.parent.mkdir(exist_ok=True)
    p.write_text(text); os.chmod(p, mode); os.utime(p, (age, age))
    return p


def untouched(p, text="KEEP-ME\n", mode=0o644, age=1_500_000_000):
    st = os.stat(p)
    return p.read_text() == text and stat.S_IMODE(st.st_mode) == mode and int(st.st_mtime) == age


# ================================================================================ L2 shadow child: no real file written
ws = T / "ws"
(ws / "reports").mkdir(parents=True); (ws / "config").mkdir(); (ws / "reports" / "limit-wait.log").write_text("old line\n"); (ws / "config" / "flow.json").write_text('{"default": "off"}')
before = fp(ws)
tmp_run = T / "run-l2"; (tmp_run / "state").mkdir(parents=True)
code = ("import sys, json\nsys.path.insert(0, %r)\nfrom shipmiracle.hooks import shadow as S\n"
        "raw = json.dumps({'hook_event_name': 'StopFailure', 'session_id': 'sl2', 'error': 'rate_limit', 'last_assistant_message': 'You hit your limit, resets 4:20pm', 'cwd': %r}).encode()\n"
        "out = S.run_v1('StopFailure', raw, %r, %r)\nprint(json.dumps(out[3]))\n") % (str(ROOT), str(HOME / "Developer" / "projx"), str(tmp_run / "state"), str(tmp_run))
e = dict(os.environ, SHIPMIRACLE_WS=str(ws), CLAUDE_PROJECT_DIR=str(HOME / "Developer" / "projx"))
r = subprocess.run([SYSPY, "-c", code], capture_output=True, text=True, env=e, timeout=60)
effects = json.loads(r.stdout.strip().splitlines()[-1]) if r.returncode == 0 and r.stdout.strip() else None
check("L2 the v1 run of a limit-hit event ran limit_wait (caffeinate recorded as an intended effect, limit.json in the TEMP state)",
      effects is not None and any(x.startswith("caffeinate") for x in effects) and (tmp_run / "state" / "projx.limit.json").exists(), (r.stdout, r.stderr[-400:]))
check("L2 nothing in the real <WS>/reports or <WS>/config changed (fingerprint before == after; the log line went nowhere)", fp(ws) == before and (ws / "reports" / "limit-wait.log").read_text() == "old line\n")

# ================================================================================ L3 symlinks and escapes
v = victim("log")
(T / "st1").mkdir(); os.symlink(v, T / "st1" / "x.log")
try:
    hio.append_line(str(T / "st1" / "x.log"), "pwned"); ok = False
except OSError:
    ok = True
check("L3 append_line refuses a symlink at the target (O_NOFOLLOW) and the victim is untouched", ok and untouched(v))
out_dir = T / "outside" / "dir"; out_dir.mkdir()
(T / "st2").mkdir(); os.symlink(out_dir, T / "st2" / "v1")
try:
    hio.append_line(str(T / "st2" / "v1" / "rec.jsonl"), "x", inside_root=str(T / "st2")); ok = False
except PermissionError:
    ok = True
check("L3 append_line with inside_root refuses a path whose folder is a symlink to elsewhere; nothing created outside", ok and list(out_dir.iterdir()) == [])
hio.append_line(str(T / "st2" / "fine.log"), "a", inside_root=str(T / "st2"))
check("L3 append_line inside the root still works (0600)", (T / "st2" / "fine.log").read_text() == "a\n" and stat.S_IMODE(os.stat(T / "st2" / "fine.log").st_mode) == 0o600)
check("L3 inside(): existing, new, dotdot and symlinked paths", hio.inside(str(T / "st2" / "n" / "e" / "w"), str(T / "st2")) and not hio.inside(str(T / "st2" / ".." / "x"), str(T / "st2"))
      and not hio.inside(str(T / "st2" / "v1" / "a"), str(T / "st2")) and hio.inside(str(T / "st2"), str(T / "st2")))

# record file: symlink at hooks-record.jsonl
rs = T / "rec-state"; (rs / "v1").mkdir(parents=True)
v = victim("rec", mode=0o644)
os.symlink(v, rs / "v1" / "hooks-record.jsonl")
ok = S.append_record(str(rs), {"ts": int(time.time()), "event": "Stop", "input": {}, "pre_state": {}, "legacy_result": {}})
check("L3 append_record: a symlink at the record path is refused (returns False), the victim keeps content and mode (no chmod through the link)", ok is False and untouched(v))
rs2 = T / "rec-state2"; (rs2 / "v1").mkdir(parents=True); os.symlink(out_dir, rs2 / "v1x")
ok = S.append_record(str(rs2), {"ts": int(time.time()), "event": "Stop"})
check("L3 append_record: a normal record is written 0600", ok and stat.S_IMODE(os.stat(S.record_path(str(rs2))).st_mode) == 0o600)

# lock file of agent_state
proj = HOME / "Developer" / "projx"; proj.mkdir(parents=True, exist_ok=True)
v = victim("lock")
os.symlink(v, STATE / "projx.agents.json.lock")
raw = json.dumps({"hook_event_name": "SubagentStart", "agent_id": "a1", "agent_type": "x", "session_id": "s1"}).encode()
env = dict(os.environ, CLAUDE_PROJECT_DIR=str(proj))
res = A.agent_state(core.Ctx(raw, "SubagentStart", env))
check("L3 agent_state: a symlinked .lock file is refused (not truncated), no registration written, no exception", res is None and untouched(v) and not (STATE / "projx.agents.json").exists(), res)
os.unlink(STATE / "projx.agents.json.lock")
res = A.agent_state(core.Ctx(raw, "SubagentStart", env))
check("L3 agent_state: normal case still registers the agent", (STATE / "projx.agents.json").exists() and "a1" in (STATE / "projx.agents.json").read_text())

# user-active (UserPromptSubmit) must not touch a symlink target
v = victim("active")
os.symlink(v, STATE / "user-active")
ACT.guard_hook(core.Ctx(json.dumps({"hook_event_name": "UserPromptSubmit", "session_id": "s1", "cwd": str(proj)}).encode(), "UserPromptSubmit", env))
check("L3 guard_hook: user-active as a symlink is not opened or touched (victim mtime unchanged)", untouched(v))
os.unlink(STATE / "user-active")

# project-folder modules
GENV = dict(os.environ, HOME=str(HOME), GIT_CONFIG_NOSYSTEM="1")


def git(*a, cwd):
    return subprocess.run(["git"] + list(a), cwd=str(cwd), capture_output=True, env=GENV, timeout=60)


def mkproj(name):
    p = HOME / "Developer" / name; p.mkdir(parents=True)
    git("init", "-q", "-b", "main", cwd=p); git("config", "user.name", "t", cwd=p); git("config", "user.email", "t@t", cwd=p)
    return p


def ctx_for(p, event, payload):
    return core.Ctx(json.dumps(payload).encode(), event, dict(os.environ, CLAUDE_PROJECT_DIR=str(p)))


# model_switch
p = mkproj("ms1"); (p / "docs" / "memory").mkdir(parents=True); v = victim("mlog")
os.symlink(v, p / "docs" / "memory" / "model-log.md")
P.model_switch(ctx_for(p, "PreModelSwitch", {"model": "opus", "session_id": "abcdef123"}))
check("L3 model_switch: model-log.md as a symlink is not written through", untouched(v))
p = mkproj("ms2"); (p / "docs").mkdir(); od = T / "outside" / "mem"; od.mkdir(); os.symlink(od, p / "docs" / "memory")
P.model_switch(ctx_for(p, "PreModelSwitch", {"model": "opus", "session_id": "abcdef123"}))
check("L3 model_switch: docs/memory as a symlink to a folder outside the project writes nothing there", list(od.iterdir()) == [])
p = mkproj("ms3")
P.model_switch(ctx_for(p, "PreModelSwitch", {"model": "opus", "session_id": "abcdef123"}))
check("L3 model_switch: a normal project still gets docs/memory/model-log.md", "model=opus" in (p / "docs/memory/model-log.md").read_text())

# save_plan
plan = HOME / ".claude" / "plans" / "my-big-plan-here.md"; plan.write_text("# Plan\nbody\n")
p = mkproj("sp1"); (p / "docs").mkdir(); od = T / "outside" / "plans"; od.mkdir(); os.symlink(od, p / "docs" / "plans")
P.save_plan(ctx_for(p, "PostToolUse", {"tool_name": "ExitPlanMode"}))
check("L3 save_plan: docs/plans as a symlink to a folder outside the project receives no plan", list(od.iterdir()) == [])
p = mkproj("sp2"); (p / "docs" / "plans").mkdir(parents=True); v = victim("plandst")
slug = "my-big-plan-here"
os.symlink(v, p / "docs" / "plans" / ("%s-%s.md" % (time.strftime("%Y-%m-%d"), slug)))
P.save_plan(ctx_for(p, "PostToolUse", {"tool_name": "ExitPlanMode"}))
check("L3 save_plan: the target plan file as a symlink is not written through", untouched(v))
p = mkproj("sp3")
res = P.save_plan(ctx_for(p, "PostToolUse", {"tool_name": "ExitPlanMode"}))
check("L3 save_plan: a normal project still gets the plan", res is not None and any((p / "docs" / "plans").glob("*.md")))

# stop_fast: STATUS.md is a symlink to a file outside the project
p = mkproj("sf1"); (p / "docs").mkdir(); (p / "src.py").write_text("a=1\n"); git("add", "-A", cwd=p); git("commit", "-q", "-m", "i", cwd=p)
(p / "src.py").write_text("a=2\n"); time.sleep(1.1)
v = victim("status", text="Updated: %s test\n## Handoff\nnothing\n" % time.strftime("%Y-%m-%d"))
os.symlink(v, p / "docs" / "STATUS.md")
P.stop_fast(ctx_for(p, "Stop", {"session_id": "sess-123456"}))
check("L3 stop_fast: a STATUS.md symlinked outside the project is never rewritten (no 'Last Claude session' line in the victim)", "Last Claude session" not in v.read_text(), v.read_text())
p = mkproj("sf2"); (p / "docs").mkdir(); (p / "src.py").write_text("a=1\n"); git("add", "-A", cwd=p); git("commit", "-q", "-m", "i", cwd=p)
(p / "src.py").write_text("a=2\n"); time.sleep(1.1)
(p / "docs" / "STATUS.md").write_text("Updated: %s test\n## Handoff\nnothing\n" % time.strftime("%Y-%m-%d"))
P.stop_fast(ctx_for(p, "Stop", {"session_id": "sess-123456"}))
check("L3 stop_fast: a normal STATUS.md still gets the session line", "Last Claude session: sess-123456" in (p / "docs/STATUS.md").read_text())

# ================================================================================ L4 --report path
BIN = str(ROOT / "bin/shipm")
cenv = dict(os.environ, SHIPMIRACLE_STATE=str(T / "cli-state"), SHIPMIRACLE_CONFIG=str(T / "cli-cfg"), SHIPMIRACLE_HOME=str(T / "cli-home"), HOME=str(T / "cli-home"))
for d in ("cli-state", "cli-cfg", "cli-home"):
    (T / d).mkdir(exist_ok=True)


def cli_report(path):
    r = subprocess.run([BIN, "hooks", "replay", "--corpus", "fixtures", "--limit", "1", "--report", path], capture_output=True, text=True, env=cenv, timeout=300, stdin=subprocess.DEVNULL)
    return r.returncode, r.stdout, r.stderr


gate_cfg = ROOT / "config" / "flow.json"
gate_before = gate_cfg.read_bytes() if gate_cfg.exists() else None
os.symlink(T / "ok-target.md", T / "link.md")
other_md = T / "notes.md"; other_md.write_text("# my notes\n")
for label, path in (("outside every allowed folder", "/etc/shipmiracle-report-test.md"), ("the gate config in the repo (not .md)", str(gate_cfg)), ("an existing .md that is not a replay report", str(other_md)),
                    ("a symlink in the temp folder", str(T / "link.md")), ("dotdot out of the temp folder", str(T / ".." / ".." / ".." / "etc" / "shipmiracle-x.md")) ):
    rc, out, err = cli_report(path)
    check("L4 --report %s: exit 2, nothing written" % label, rc == 2 and not os.path.exists("/etc/shipmiracle-report-test.md") and other_md.read_text() == "# my notes\n"
          and not (T / "ok-target.md").exists() and (gate_cfg.read_bytes() if gate_cfg.exists() else None) == gate_before, (rc, out[-200:], err[-200:]))
good = T / "good-report.md"
rc, out, err = cli_report(str(good))
check("L4 --report inside the temp folder works (exit 0 or 1 by the replay result, never 2) and writes the report", rc in (0, 1) and good.read_text().startswith("# Hook replay report"), (rc, err[-200:]))
rc, out, err = cli_report(str(good))
check("L4 --report over an earlier replay report is allowed", rc in (0, 1), (rc, err[-200:]))
try:
    R.check_report_path(str(ROOT / "docs" / "replay-report-test.md")); ok = True
except R.ReplayError:
    ok = False
try:
    R.check_report_path(str(STATE / "v1" / "replay.md"), str(STATE)); ok2 = True
except R.ReplayError:
    ok2 = False
check("L4 check_report_path accepts a new .md inside the repo and inside the state folder", ok and ok2)

# ================================================================================ L5 owner scripts refuse in a Claude chat
scripts = sorted(p_ for p_ in (ROOT / "docs" / "owner-steps").glob("*.sh") if p_.name != "cutover.sh")      # cutover.sh refuses inside a chat by its own preconditions and has no --apply; it has its own private test
if scripts:          # the owner-step scripts exist only in the owner's checkout
    check("L5 there are owner-step scripts to check", len(scripts) >= 9, len(scripts))
    for sc in scripts:
        h = T / ("l5-" + sc.stem); h.mkdir()
        e = {k: v for k, v in os.environ.items() if not k.startswith("SHIPMIRACLE_")}
        e.update(CLAUDECODE="1", HOME=str(h)); e.pop("SHIPMIRACLE_TEST", None)
        outs = []
        for args in ([], ["--apply"]):
            r = subprocess.run(["bash", str(sc)] + args, capture_output=True, text=True, env=e, timeout=30, stdin=subprocess.DEVNULL)
            outs.append((r.returncode, (r.stdout + r.stderr)))
        check("L5 %s refuses under CLAUDECODE=1 (dry run and --apply: non-zero, says why) and wrote nothing" % sc.name,
              all(rc != 0 and "CLAUDECODE" in o for rc, o in outs) and list(h.iterdir()) == [], outs)

# ================================================================================ L8 at most 4 shadow children
procs = [subprocess.Popen(["sleep", "30"]) for _ in range(8)]
try:
    st8 = T / "slots"; st8.mkdir()
    got = [S.acquire_slot(str(st8), 4, pid=p_.pid) for p_ in procs[:5]]
    check("L8 acquire_slot: the first 4 get a slot, the 5th is refused (returns the running count)", got == [0, 0, 0, 0, 4], got)
    S.release_slot(str(st8), procs[0].pid)
    check("L8 release_slot frees a slot", S.acquire_slot(str(st8), 4, pid=procs[5].pid) == 0)
    procs[1].kill(); procs[1].wait()
    check("L8 a dead child's slot is reclaimed", S.acquire_slot(str(st8), 4, pid=procs[6].pid) == 0)
    old = T / "slots-old"; old.mkdir(); (old / "v1").mkdir()
    (old / "v1" / "shadow-children").write_text("".join("%d %d\n" % (p_.pid, int(time.time()) - 600) for p_ in procs[:4]))
    check("L8 slots older than the child limit + 30 s are reclaimed even if the pid is alive (pid reuse)", S.acquire_slot(str(old), 4, pid=procs[7].pid) == 0)
    # concurrency: 8 racers, exactly 4 win
    st9 = T / "slots-race"; st9.mkdir(); res = []
    racers = [subprocess.Popen(["sleep", "30"]) for _ in range(8)]
    procs.extend(racers)
    ths = [threading.Thread(target=lambda p_=p_: res.append(S.acquire_slot(str(st9), 4, pid=p_.pid))) for p_ in racers]
    [t.start() for t in ths]; [t.join() for t in ths]
    check("L8 eight concurrent children: exactly 4 registered, 4 refused (flock)", sorted(res).count(0) == 4 and len(res) == 8, res)
    lnk = T / "slots-link"; (lnk / "v1").mkdir(parents=True); os.symlink(victim("slotvictim"), lnk / "v1" / "shadow-children")
    try:
        S.acquire_slot(str(lnk), 4, pid=procs[0].pid); ok = False
    except OSError:
        ok = True
    check("L8 a symlinked counter file is refused", ok and untouched(T / "outside" / "slotvictim"))
finally:
    for p_ in procs:
        p_.kill(); p_.wait()


# end to end: the counter is full, the shadow child skips and counts
def new_world(name):
    base = T / name
    st, cfg, dev, stubs, tmpd = base / ".local/state/shipmiracle", base / "cfg", base / "Developer", base / "stubs", base / "tmp"
    for d in (st, cfg, dev / "projx", stubs, tmpd, base / "ws/config"):
        d.mkdir(parents=True, exist_ok=True)
    for n in ("caffeinate", "osascript", "gh", "pmset"):
        (stubs / n).write_text("#!/bin/sh\nexit 0\n"); os.chmod(stubs / n, 0o755)
    (cfg / "config.json").write_text(json.dumps({"hooks.dispatcher": "shadow"}))
    (base / "ws/config/flow.json").write_text('{"default": "off"}')
    env = dict(os.environ, SHIPMIRACLE_TEST="1", SHIPMIRACLE_STATE=str(st), SHIPMIRACLE_CONFIG=str(cfg), SHIPMIRACLE_HOME=str(base), HOME=str(base), SHIPMIRACLE_DEV=str(dev), TMPDIR=str(tmpd),
               CLAUDE_PROJECT_DIR=str(dev / "projx"), PATH="%s:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin" % stubs, SHIPMIRACLE_WS=str(base / "ws"))
    return env, {"base": base, "state": st, "dev": dev}


def wait_pid(pidfile, tmo=40):
    end = time.time() + tmo
    while time.time() < end and not os.path.exists(pidfile):
        time.sleep(0.05)
    if not os.path.exists(pidfile):
        return False
    time.sleep(0.05)
    pid = int(open(pidfile).read().strip() or 0)
    while time.time() < end:
        try:
            os.kill(pid, 0)
        except OSError:
            return True
        time.sleep(0.1)
    return False


def evs(state, kind):
    p = pathlib.Path(state) / "v1/events.jsonl"
    return [d for d in (json.loads(l) for l in p.read_text().splitlines() if l.strip()) if d.get("kind") == kind] if p.exists() else []


if (ROOT / "hooks" / "agent-cap.sh").exists():          # the shadow mode answers with the legacy shell scripts, which exist only in the owner's checkout
    payload = {"hook_event_name": "PreToolUse", "session_id": "sl8", "tool_name": "Agent", "tool_input": {"prompt": "x"}}
    entry = str(ROOT / "hooks/shipm-hook")
    busy = [subprocess.Popen(["sleep", "30"]) for _ in range(4)]
    try:
        env8, W8 = new_world("l8-full")
        (W8["state"] / "agents.paused").write_text("")
        (W8["state"] / "v1").mkdir(parents=True)
        (W8["state"] / "v1" / "shadow-children").write_text("".join("%d %d\n" % (p_.pid, int(time.time())) for p_ in busy))
        pf = str(W8["base"] / "child.pid")
        r = subprocess.run([SYSPY, "-I", "-S", entry, "PreToolUse"], input=json.dumps(dict(payload, cwd=str(W8["dev"] / "projx"))).encode(), capture_output=True,
                           env=dict(env8, SHIPMIRACLE_SHADOW_PIDFILE=pf), timeout=60)
        done = wait_pid(pf)
        sk, sh_ = evs(W8["state"], "hook_shadow_skipped"), evs(W8["state"], "hook_shadow")
        check("L8 end to end with 4 children already running: the hook answers as legacy, the child logs hook_shadow_skipped and runs no comparison",
              r.returncode == 0 and b"permissionDecision" in r.stdout and done and len(sk) == 1 and sk[0]["data"]["max"] == 4 and sk[0]["data"]["event"] == "PreToolUse" and sh_ == [], (r, sk, sh_))
        env8b, W8b = new_world("l8-free")
        (W8b["state"] / "agents.paused").write_text("")
        pf2 = str(W8b["base"] / "child.pid")
        r = subprocess.run([SYSPY, "-I", "-S", entry, "PreToolUse"], input=json.dumps(dict(payload, cwd=str(W8b["dev"] / "projx"))).encode(), capture_output=True,
                           env=dict(env8b, SHIPMIRACLE_SHADOW_PIDFILE=pf2), timeout=60)
        done = wait_pid(pf2)
        sk, sh_ = evs(W8b["state"], "hook_shadow_skipped"), evs(W8b["state"], "hook_shadow")
        slots = (W8b["state"] / "v1" / "shadow-children").read_text().split() if (W8b["state"] / "v1" / "shadow-children").exists() else []
        check("L8 end to end with a free slot: the comparison runs (hook_shadow event), no skip event, the slot is released afterwards", done and len(sh_) == 1 and sk == [] and slots == [], (sk, sh_, slots))
    finally:
        for p_ in busy:
            p_.kill(); p_.wait()
agg = S.aggregate([{"kind": "hook_shadow_skipped", "ts": time.time(), "data": {}}, {"kind": "hook_shadow_skipped", "ts": 1, "data": {}}], time.time() - 60)
check("L8 shadow-report aggregate counts skipped events in the window", agg["skipped"] == 1, agg)

shutil.rmtree(T, ignore_errors=True)
print("ALL PASS" if not fails else "FAILED %d" % fails)
sys.exit(1 if fails else 0)
