#!/usr/bin/env python3
"""Stage module cost (P5b T5, spec section 4 'Performance'): the time the stage slot adds to a hook call, measured as real processes
(/usr/bin/python3 -I -S, the interpreter flags of the production hook command) through the dispatcher shim tests/fixtures/stage/hook.sh in merged mode:
the SAME input once with the stage engine `legacy` (the slot returns at once) and once with `playbook` and an active CR; the difference is the added
cost. Targets: PreToolUse not Agent|Task: 0 ms (the slot does not match: checked by the matcher, then timed); Agent|Task and ExitPlanMode:
<= +10 ms p95; Stop and SubagentStop with an active CR: <= +60 ms p95 (git with 3 s timeouts, fail-open). A busy Mac must not fail the check
(tests/shipmiracle_timing.robust: pass when within the limit OR within K x a same-moment reference, any of 3 attempts).
Run: python3 tests/stage_bench_test.py"""
import json, os, pathlib, shutil, subprocess, sys, tempfile, time

ROOT = pathlib.Path(__file__).resolve().parent.parent
SHIM = ROOT / "tests/fixtures/stage/hook.sh"
os.environ["SHIPMIRACLE_TEST_HOOK"] = str(SHIM)
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT))
import shipmiracle_timing as T  # noqa: E402
import flow_fixture as F  # noqa: E402

fails = 0
N = int(os.environ.get("SHIPMIRACLE_BENCH_N") or 30)


def check(name, ok, info=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(info)[:700]))
    fails += 0 if ok else 1


p = F.make_project()
env0 = dict(p.ENV, SHIPMIRACLE_STAGE_SHIM="merged", SHIPMIRACLE_STAGE_FORCE="1")
env0.pop("SHIPMIRACLE_STAGE_ENGINE", None)
p.ENV.update(env0)
sid = "bench"


def call(event, engine, **kw):
    env = dict(env0, SHIPMIRACLE_STAGE_ENGINE=engine)
    d = {"hook_event_name": event, "session_id": sid, "cwd": str(p.P), **kw}
    t0 = time.perf_counter()
    r = subprocess.run(["bash", str(SHIM)], input=json.dumps(d), capture_output=True, text=True, env=env, cwd=str(p.P))
    return time.perf_counter() - t0, r


# a session with the team seen and one active CR (built, waiting for the test)
p.hook("UserPromptSubmit", sid, prompt="go")
p.put("src/app.py", "x = 1\ny = 2\nz = 3\n")
call("SubagentStop", "playbook", agent_id="b1", agent_type="backend-engineer", last_assistant_message="Built.")
call("UserPromptSubmit", "playbook", prompt="next")
log = list((p.STATE / "v1" / "cr").glob("*.jsonl"))
check("setup: an active CR exists (the log was written by the stage module)", len(log) == 1, log)

CASES = [
    ("PreToolUse Agent (qa-engineer)", "PreToolUse", dict(tool_name="Agent", tool_input={"subagent_type": "qa-engineer", "prompt": "x"}), 10),
    ("PostToolUse ExitPlanMode", "PostToolUse", dict(tool_name="ExitPlanMode", tool_input={"plan": "# P\nx"}, tool_response={}), 10),
    ("PostToolUse Agent", "PostToolUse", dict(tool_name="Agent", tool_input={"subagent_type": "x"}, tool_response={}), 10),
    ("UserPromptSubmit", "UserPromptSubmit", dict(prompt="status?"), 60),
    ("Stop", "Stop", dict(last_assistant_message="Done for now."), 60),
    ("SubagentStop (build)", "SubagentStop", dict(agent_id="b2", agent_type="backend-engineer", last_assistant_message="Built."), 60),
]
for label, ev, kw, limit in CASES:
    def measure(ev=ev, kw=kw):
        legacy, play = [], []
        for _ in range(N):                                   # interleaved: both see the same machine load
            legacy.append(call(ev, "legacy", **kw)[0])
            play.append(call(ev, "playbook", **kw)[0])
        d = sorted(b - a for a, b in zip(sorted(legacy), sorted(play)))
        return max(0.0, T.p95(play) - T.p95(legacy)), T.median(legacy), T.median(play)
    best = []

    def m():
        v, ml, mp = measure()
        best.append((v, ml, mp))
        return v
    ok, rep, val = T.robust_around(m, lambda: T.spawn_ref(7), limit / 1000.0, 0.75 if limit <= 10 else 2.0, attempts=5)      # baseline before AND after, best of 5 (26 Oct 2026)
    v, ml, mp = min(best)
    print("INFO %-32s legacy p50 %.0f ms, playbook p50 %.0f ms, added p95 %.0f ms (limit %d ms)" % (label, ml * 1000, mp * 1000, v * 1000, limit))
    check("%s: stage adds <= %d ms p95 (or <= K x a bare python start while the Mac is busy)" % (label, limit), ok, rep)

# PreToolUse that the slot does not match: no stage import at all
t_bash = []
for _ in range(N):
    t_bash.append(call("PreToolUse", "legacy", tool_name="Bash", tool_input={"command": "ls"})[0])
    t_bash.append(call("PreToolUse", "playbook", tool_name="Bash", tool_input={"command": "ls"})[0])
code = ("import sys, json; sys.path.insert(0, %r); from shipmiracle.hooks import core; "
        "ctx = core.Ctx(b'{\"hook_event_name\":\"PreToolUse\",\"tool_name\":\"Bash\"}', 'PreToolUse'); "
        "s = [x for x in core.PIPELINES['PreToolUse'] if x.name == 'stage'][0]; "
        "print(core.eligible(ctx, s), 'shipmiracle.hooks.stage' in sys.modules)" % str(ROOT))
out = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, env=dict(os.environ, SHIPMIRACLE_TEST="1")).stdout.strip()
check("PreToolUse Bash: the stage slot is not eligible and its file is not imported (0 ms)", out == "False False", out)
legacy_b = [t_bash[i] for i in range(0, len(t_bash), 2)]
play_b = [t_bash[i] for i in range(1, len(t_bash), 2)]
d = abs(T.median(play_b) - T.median(legacy_b)) * 1000
print("INFO PreToolUse Bash: median legacy %.0f ms, playbook %.0f ms (difference %.1f ms)" % (T.median(legacy_b) * 1000, T.median(play_b) * 1000, d))
# noise between two engines that run the same code here: <= max(3 ms, 0.25 x a bare python start measured right now, same load). (The old comparison mixed ms with seconds.) 0.25 = 3 ms / ~12-20 ms quiet.
_sp = max(T.spawn_ref(7), T.spawn_ref(7)) * 1000
check("PreToolUse Bash: median difference between the engines <= max(3 ms, 0.25 x bare python start %.0f ms) (noise)" % _sp, d <= max(3.0, 0.25 * _sp), d)

p.cleanup()
print("\n%s: %d failed" % ("FAIL" if fails else "ALL PASS", fails))
sys.exit(1 if fails else 0)
