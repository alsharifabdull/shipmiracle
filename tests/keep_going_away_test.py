#!/usr/bin/env python3
"""Phase 6 T4: the keep_going AWAY branch (shipmiracle/hooks/keep_going.py) and `bin/away-decisions list --cr`. Same temp world as autopilot_hook_test (sandbox project, auto
worktree, started run). Differential: with no trusted playbook (gate.engine legacy / shadow / playbook but no playbook / untrusted playbook) the module is byte-identical to the
committed legacy module (tests/fixtures/autopilot/hook/keep_going_legacy.py = shipmiracle/hooks/keep_going.py before P6): same Result, same away-decisions.jsonl line, no event.
New behaviour only with a trusted playbook and gate.engine=playbook: guided -> no AWAY_TEXT, return None, away.wait; full active -> FULL_AWAY_TEXT + auto_decision away_choice;
both write a compatible away-decisions line {ts, project, question, cr, rule, src}. Run: python3 tests/keep_going_away_test.py"""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import shipmiracle_isolation; shipmiracle_isolation.apply_to_environ()   # test isolation: fresh HOME/SHIPMIRACLE_HOME/CONFIG/STATE unless already temp
import json, os, pathlib, subprocess, sys, time, types

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import autopilot_hook_fixture as F  # noqa: E402
from shipmiracle.hooks import core, keep_going as KG  # noqa: E402
from shipmiracle import config  # noqa: E402
from shipmiracle.autopilot import state as S  # noqa: E402

fails = 0
def check(name, ok, info=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(info)[:900]))
    fails += 0 if ok else 1

REAL = pathlib.Path(os.path.expanduser("~"))
CANARY = [REAL / ".config" / "shipmiracle" / "config.json", REAL / ".local/state/shipmiracle/away-decisions.jsonl", REAL / ".local/state/shipmiracle/events.jsonl"]
before = [(p.stat().st_mtime_ns if p.exists() else None) for p in CANARY]
F.build_world()
F.reset_core(only=["keep_going"])
MAIN, PID, STATE = F.MAIN, F.PID, F.STATE
TR = F.TMP / "transcripts"
TR.mkdir()

# the legacy module, loaded under another name so that it does not take the Stop slot
src = (HERE / "fixtures/autopilot/hook/keep_going_legacy.py").read_text()
legacy = types.ModuleType("shipmiracle.hooks.keep_going_legacy")
legacy.__package__ = "shipmiracle.hooks"
_reg = core.register
core.register = lambda *a, **k: None
try:
    exec(compile(src, "keep_going_legacy.py", "exec"), legacy.__dict__)
finally:
    core.register = _reg

SAFE = "Option A keeps the old layout; option B rewrites it. Which one do you want?"
RISKY = "I will delete the old branches and force push. Do you want that?"
PROMISE = "I read the files. Next I will run the tests."
MSGS = {"safe question": SAFE, "risky question": RISKY, "promise": PROMISE, "done": "All tests pass. Done.", "plain": "Here is the summary.", "empty": ""}


def transcript(msg):
    p = TR / ("t%d.jsonl" % (len(list(TR.iterdir()))))
    p.write_text((json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": msg}]}}) + "\n") if msg else "")
    return str(p)


def away(on=True, state=STATE):
    pathlib.Path(state, "away.json").write_text(json.dumps({"away": on, "ts": int(time.time())}))


def call(fn, msg, project_dir, state=None, **env):
    """Run one Stop through keep_going function `fn` with the given project dir; (Result, away-decisions lines)."""
    st_dir = pathlib.Path(state or STATE)
    log = st_dir / "away-decisions.jsonl"
    if log.exists():
        log.unlink()
    raw = json.dumps({"hook_event_name": "Stop", "session_id": "sess0001abc", "cwd": str(project_dir), "transcript_path": transcript(msg)}).encode()
    core._FILES.clear()
    with F.env_set(CLAUDE_PROJECT_DIR=str(project_dir), SHIPMIRACLE_STATE=str(st_dir), **env):
        ctx = core.Ctx(raw, "Stop")
        res = fn(ctx)
    lines = [json.loads(ln) for ln in log.read_text().splitlines()] if log.exists() else []
    return res, lines


def norm(lines):
    return [{k: v for k, v in ln.items() if k != "ts"} for ln in lines]


def n_events(kind):
    return len(F.events(kind))


# a second project without any playbook
PLAIN = F.DEV / "plain"
PLAIN.mkdir()
F.git(PLAIN, "init", "-q")
(PLAIN / "a.txt").write_text("1\n")
F.git(PLAIN, "add", "-A"); F.git(PLAIN, "commit", "-qm", "init")

# ================================================================== differential: no trusted playbook -> byte-identical
away(True)
ev0 = len(F.events())
cases = 0
def diff(label, project, engine, **kw):
    global cases
    config.set("gate.engine", engine)
    for name, msg in MSGS.items():
        for aw in (True, False):
            away(aw)
            a, la = call(legacy.keep_going, msg, project)
            b, lb = call(KG.keep_going, msg, project)
            cases += 1
            check("differential [%s] %s, away=%s: same Result and same log line" % (label, name, aw), a == b and norm(la) == norm(lb) and all(set(x) == {"ts", "project", "question"} for x in lb), (a, b, la, lb))
diff("engine legacy, playbook project", MAIN, "legacy")
diff("engine shadow, playbook project", MAIN, "shadow")
diff("engine playbook, project without a playbook", PLAIN, "playbook")
diff("engine legacy, project without a playbook", PLAIN, "legacy")
# an untrusted playbook (file edited after the registry sha)
config.set("gate.engine", "playbook")
pj = MAIN / ".shipmiracle" / "playbook.json"
orig = pj.read_text()
pj.write_text(orig.replace('"strict"', '"warn"') if '"strict"' in orig else orig + " ")
away(True)
for name, msg in MSGS.items():
    a, la = call(legacy.keep_going, msg, MAIN)
    b, lb = call(KG.keep_going, msg, MAIN)
    check("differential [playbook.json edited = untrusted] %s: same Result and log line" % name, a == b and norm(la) == norm(lb), (a, b, la, lb))
pj.write_text(orig)
check("the differential made no autopilot event", len(F.events()) == ev0 or all(not e["kind"].startswith(("away.", "auto_decision")) for e in F.events()[ev0:]), F.events()[ev0:])

# ================================================================== guided + trusted playbook + engine playbook
config.set("gate.engine", "playbook")
away(True)
res, lines = call(KG.keep_going, SAFE, MAIN)
check("guided + away + safe question: no AWAY_TEXT, no block (the stop stands)", res is None, res)
check("   one away-decisions line: compatible fields + rule away_wait, src autopilot, cr", len(lines) == 1 and set(lines[0]) == {"ts", "project", "question", "cr", "rule", "src"}
      and lines[0]["rule"] == "away_wait" and lines[0]["src"] == "autopilot" and lines[0]["project"] == "sandbox" and lines[0]["question"] == SAFE and isinstance(lines[0]["ts"], int), lines)
check("   event away.wait logged", n_events("away.wait") == 1, F.events("away.wait"))
check("   no auto_decision event for a wait", n_events("auto_decision") == 0)
res, lines = call(KG.keep_going, RISKY, MAIN)
check("guided + away + risky question: not decided, no log line", res is None and lines == [], (res, lines))
res, lines = call(KG.keep_going, PROMISE, MAIN)
check("guided + a promise: the push-on text is unchanged", res is not None and res.block and res.reason == KG.PUSH_TEXT and res.exit_code == 2, res)
away(False)
res, lines = call(KG.keep_going, SAFE, MAIN)
check("guided + not away + question: legacy (a real stop, no line)", res is None and lines == [], (res, lines))

# ================================================================== full autopilot, active
wt = F.start()
WTS = str(wt)
away(True)
n_ad0 = n_events("auto_decision")
res, lines = call(KG.keep_going, SAFE, wt)
check("full active + away + safe question: block with FULL_AWAY_TEXT (exit code 2 like the legacy hook)", res is not None and res.block and res.reason == KG.FULL_AWAY_TEXT and res.exit_code == 2, res)
check("   FULL_AWAY_TEXT is the spec text", KG.FULL_AWAY_TEXT == "Charter active: choose the recommended reversible option inside the charter scope; the gate enforces hard stops.")
check("   away-decisions line: rule away_choice, cr CR-001, src autopilot, project = worktree folder", len(lines) == 1 and lines[0]["rule"] == "away_choice" and lines[0]["cr"] == "CR-001" and lines[0]["src"] == "autopilot"
      and lines[0]["question"] == SAFE, lines)
ads = F.events("auto_decision")
check("   auto_decision event {cr, stage, rule, charter_sha, detail<=200}", len(ads) == n_ad0 + 1 and ads[-1]["data"]["rule"] == "away_choice" and ads[-1]["data"]["cr"] == "CR-001"
      and ads[-1]["data"]["charter_sha"] == S.read(PID)["charter_sha"] and len(ads[-1]["data"]["detail"]) <= 200 and ads[-1]["data"]["stage"], ads[-1:])
check("   state.decisions bumped", S.read(PID)["decisions"] == 1, S.read(PID))
res, lines = call(KG.keep_going, RISKY, wt)
check("full active + away + risky question: not decided", res is None and lines == [], (res, lines))
res, lines = call(KG.keep_going, PROMISE, wt)
check("full active + a promise: pushes on as before", res is not None and res.reason == KG.PUSH_TEXT, res)
away(False)
res, lines = call(KG.keep_going, SAFE, wt)
check("full active + not away: a real stop, no line", res is None and lines == [], (res, lines))

# ================================================================== full but paused / ended: keep_going stops pushing
away(True)
S.pause(PID, {"id": "H-111111", "rule": "H1-delete", "ts": int(time.time()), "text": "x", "cmd_sha": "a" * 64}, "hard_stop")
res, lines = call(KG.keep_going, SAFE, wt)
check("full + paused + away + safe question: waits (no choice), line away_wait", res is None and len(lines) == 1 and lines[0]["rule"] == "away_wait", (res, lines))
res, lines = call(KG.keep_going, PROMISE, wt)
check("full + paused + a promise: keep_going does not push (the run is over)", res is None, res)
S.resume(PID)
res, lines = call(KG.keep_going, PROMISE, wt)
check("full + running again: pushes on", res is not None and res.reason == KG.PUSH_TEXT, res)
S.end(PID, "budget")
res, lines = call(KG.keep_going, PROMISE, wt)
check("full + ended:budget + a promise: does not push", res is None, res)
res, lines = call(KG.keep_going, SAFE, wt)
check("full + ended + away + safe question: waits", res is None and len(lines) == 1 and lines[0]["rule"] == "away_wait", (res, lines))
res, lines = call(KG.keep_going, PROMISE, MAIN)
check("the main checkout (guided) is unaffected by the run's ending", res is not None and res.reason == KG.PUSH_TEXT, res)

# ================================================================== through the dispatcher (core.run), merge shape
away(True)
config.set("gate.engine", "playbook")
wt = F.start()
raw_msg = SAFE
out, err, code = (lambda: None, None, None)
core._FILES.clear()
with F.env_set(CLAUDE_PROJECT_DIR=str(wt)):
    out, err, code = core.run("Stop", json.dumps({"hook_event_name": "Stop", "session_id": "sess0001abc", "cwd": str(wt), "transcript_path": transcript(SAFE)}).encode())
o = json.loads(out.decode()) if out.strip() else {}
check("dispatcher: the full AWAY choice is a Stop block with the charter text", o.get("decision") == "block" and o.get("reason") == KG.FULL_AWAY_TEXT, (o, err))

# ================================================================== bin/away-decisions list --cr
AD = str(F.ROOT / "bin" / "away-decisions")
sd = F.TMP / "ad-state"
sd.mkdir()
now = int(time.time())
(sd / "away-decisions.jsonl").write_text("\n".join(json.dumps(x) for x in (
    {"ts": now - 50, "project": "old", "question": "legacy line without cr"},
    {"ts": now - 40, "project": "sandbox", "question": "chose A", "cr": "CR-001", "rule": "away_choice", "src": "autopilot"},
    {"ts": now - 30, "project": "sandbox", "question": "waited on B", "cr": "CR-001", "rule": "away_wait", "src": "autopilot"},
    {"ts": now - 20, "project": "sandbox", "question": "chose C", "cr": "CR-002", "rule": "away_choice", "src": "autopilot"},
    {"ts": now - 10, "project": "sandbox", "question": "no cr yet", "cr": None, "rule": "away_wait", "src": "autopilot"})) + "\n")
def ad(*a):
    r = subprocess.run([sys.executable, AD] + list(a), env=dict(F.ENV, SHIPMIRACLE_STATE=str(sd)), capture_output=True, text=True, stdin=subprocess.DEVNULL)
    return r.returncode, r.stdout, r.stderr
code, out, err = ad("list")
check("away-decisions list: all 5 lines, legacy format kept, newest first", code == 0 and len(out.strip().splitlines()) == 5 and out.strip().splitlines()[-1].endswith("legacy line without cr")
      and "old: legacy line without cr" in out, (code, out))
check("away-decisions list: a waiting line is marked", "(waiting, nothing chosen) waited on B" in out, out)
code, out, err = ad("list", "--cr", "CR-001")
check("away-decisions list --cr CR-001: only its 2 lines", code == 0 and "chose A" in out and "waited on B" in out and "chose C" not in out and "legacy" not in out and len(out.strip().splitlines()) == 2, (code, out))
code, out, err = ad("--cr", "CR-002", "list")
check("away-decisions --cr CR-002 list (flag first): only its line", code == 0 and out.strip().endswith("chose C") and len(out.strip().splitlines()) == 1, (code, out))
code, out, err = ad("list", "--cr", "CR-099")
check("away-decisions list --cr CR-099: nothing", code == 0 and "no unreviewed decisions" in out, (code, out))
code, out, err = ad("list", "--cr")
check("away-decisions list --cr without a value: exit 2", code == 2, (code, out, err))
code, out, err = ad("render")
check("away-decisions render still works", code == 0 and (sd / "away-decisions.md").exists(), (code, out, err))
code, out, err = ad("review")
code, out, err = ad("list", "--cr", "CR-001")
check("away-decisions review then list --cr: nothing new", "no unreviewed decisions" in out, out)

# ================================================================== housekeeping
import ast
for f in ("shipmiracle/hooks/keep_going.py",):
    s_ = (F.ROOT / f).read_text()
    ast.parse(s_, feature_version=(3, 9))
    check("py39 syntax + future annotations: " + f, "from __future__ import annotations" in s_)
check("keep_going module level imports are unchanged: os, json, re, time (+ core, io)", sorted({n.names[0].name for n in ast.parse((F.ROOT / "shipmiracle/hooks/keep_going.py").read_text()).body if isinstance(n, ast.Import)}) == ["json", "os", "re", "time"])
after = [(p.stat().st_mtime_ns if p.exists() else None) for p in CANARY]
check("the owner's real config / away-decisions / events were not touched", before == after, (before, after))
print("\n%s (%d failed, %d differential cases)" % ("ALL PASS" if not fails else "FAILURES", fails, cases))
import shutil
shutil.rmtree(F.TMP, ignore_errors=True)
sys.exit(1 if fails else 0)
