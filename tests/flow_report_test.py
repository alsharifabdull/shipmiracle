#!/usr/bin/env python3
"""bin/flow-report: counts events per project from flow-events.jsonl and the Opus/Sonnet share from transcripts, in a temp state and a temp
transcript folder (SHIPMIRACLE_STATE and SHIPMIRACLE_CLAUDE_PROJECTS; HOME is a temp folder too). Run: python3 tests/flow_report_test.py"""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import shipmiracle_isolation; shipmiracle_isolation.apply_to_environ()   # test isolation: fresh HOME/SHIPMIRACLE_HOME/CONFIG/STATE unless already temp
import json, os, subprocess, sys, tempfile, time
from pathlib import Path
WS = Path(__file__).resolve().parent.parent
fails = 0
def check(n, c, info=""):
    global fails
    print(("PASS " if c else "FAIL ") + n + ("" if c else " :: " + str(info)[:500])); fails += 0 if c else 1
T = Path(tempfile.mkdtemp()).resolve()
S, P, H = T / "state", T / "claude-projects", T / "home"
for d in (S, P, H):
    d.mkdir()
now = time.time()
ev = lambda project, event, ago=60: json.dumps({"ts": now - ago, "project": project, "event": event})
(S / "flow-events.jsonl").write_text("\n".join([ev("a", "plan_ok"), ev("a", "plan_ok"), ev("a", "plan_without_architect"), ev("a", "small_fix"), ev("a", "bypass"),
                                                ev("a", "plan_ok", ago=20 * 86400), "{not json", ev("b", "done_without_qa"), ev("b", "qa_failed")]) + "\n")
pd = P / "-Users-x-Developer-a"; pd.mkdir()
(pd / "s1.jsonl").write_text('{"model":"claude-opus-4"}\n{"model":"claude-sonnet-5"}\n{"model":"claude-sonnet-5"}\n{"model":"claude-sonnet-5"}\n')
def run(*args, state=S):
    env = dict(os.environ, SHIPMIRACLE_TEST="1", SHIPMIRACLE_STATE=str(state), SHIPMIRACLE_CLAUDE_PROJECTS=str(P), HOME=str(H))
    r = subprocess.run([sys.executable, str(WS / "bin/flow-report"), *args], capture_output=True, text=True, env=env, timeout=60)
    return r.returncode, r.stdout + r.stderr
rc, o = run("7")
check("exit 0 and a header with the number of days", rc == 0 and o.startswith("Team flow, last 7 days"), o)
la = next((l for l in o.splitlines() if l.startswith("  a:")), "")
check("counts: 2 plans by the architect (the 20-day-old one and the broken line are ignored), 1 refused, 1 small fix, 1 escape hatch",
      "plans by the architect 2," in la and "plans refused 1," in la and "small fixes 1," in la and "escape hatches 1," in la, la)
check("model share from the transcripts: Sonnet 75 %, Opus 25 %", "Sonnet 75 %" in la and "Opus 25 %" in la, la)
lb = next((l for l in o.splitlines() if l.startswith("  b:")), "")
check("second project: stops refused for QA 1 and QA FAIL/BLOCKED 1, no replies part", "stops refused for QA 1 (QA FAIL/BLOCKED 1" in lb and "replies:" not in lb, lb)
rc, o = run("30")
check("a longer window counts the old event too (3 plans)", "plans by the architect 3," in next((l for l in o.splitlines() if l.startswith("  a:")), ""), o)
E2 = T / "empty"; E2.mkdir(); (T / "none").mkdir()
env = dict(os.environ, SHIPMIRACLE_TEST="1", SHIPMIRACLE_STATE=str(E2), SHIPMIRACLE_CLAUDE_PROJECTS=str(T / "none"), HOME=str(H))
r = subprocess.run([sys.executable, str(WS / "bin/flow-report")], capture_output=True, text=True, env=env, timeout=60)
check("no events and no transcripts: 'no activity', exit 0, default 7 days", r.returncode == 0 and "last 7 days" in r.stdout and "no activity" in r.stdout, r.stdout + r.stderr)
check("the report only reads: the state folder gained no file", sorted(x.name for x in S.iterdir()) == ["flow-events.jsonl"])
print("\nFAILED:" if fails else "\nALL PASS", fails); sys.exit(1 if fails else 0)
