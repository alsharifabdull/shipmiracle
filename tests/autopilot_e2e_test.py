#!/usr/bin/env python3
"""Phase 6 T5 end to end (spec sections 3, 5): charter via store_from_prompt -> `shipm autopilot start` (worktree auto-CR-001, CR imported, lease) -> a chat in the
worktree (flow + stage + autopilot slots): plan, charter approval by the ENGINE, build, test PASS, review ACCEPT, commit, Learn -> the engine fast-forward merges into
main and pushes to a LOCAL bare temp origin -> the next CR (branch auto/CR-002) starts -> second CR delivered -> last CR ends the run (done). Plus the auto_decision
events, cr_continue off while paused/ended, and the guided path left alone. Fully temp sandbox, no network. Run: python3 tests/autopilot_e2e_test.py"""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import autopilot_engine_fixture as X
from autopilot_engine_fixture import check, git, S, PID, MAIN, engine, store, W, F

X.build()
code, out, err = X.set_charter()
check("start: exit 0, worktree auto-CR-001 on branch auto/CR-001, nothing launched", code == 0 and "auto-CR-001" in out and "nothing is launched" in out, (code, out, err))
wt = X.wt_path()
st = S.read(PID)
check("state: running, cr CR-001, branch, worktree and base recorded", st["state"] == "running" and st["cr"] == "CR-001" and st["branch"] == "auto/CR-001"
      and st["worktree"] == str(wt.resolve()) and st["base"] == X.main_head(), st)
check("worktree is on branch auto/CR-001 at main's HEAD", W.current_branch(wt) == "auto/CR-001" and W.rev(wt) == X.main_head())
wk = store.load(str(wt))
c1 = engine.get_cr(wk, "CR-001")
check("CR-001 is imported into the worktree's OWN log: open, active, lane full, stages after scope reset", c1 and wk["active"] == "CR-001" and c1["status"] == "open"
      and all(c1["stages"][s] == "next" for s in ("plan", "approve", "do", "verify", "review", "deliver", "learn")) and c1["base"] == st["base"], c1)
mw = store.load(str(MAIN))
check("main log: CR-001 is leased to auto-CR-001 (hold)", engine.get_cr(mw, "CR-001")["lease"] == "auto-CR-001" and engine.get_cr(mw, "CR-001")["hold"], engine.get_cr(mw, "CR-001"))
check("event cr.imported written", any(e["data"].get("cr") == "CR-001" for e in X.events("cr.imported")))

# ------------------------------------------------------------------ CR-001 through the chat
chat = X.Chat()
chat.prompt("go")
chat.plan_stop()
chat.exit_plan()
c = chat.cr()
check("plan presented -> the charter approved it (engine, no owner words): approve done by engine, stage = do", c["stages"]["approve"].startswith("done:") and c["stage"] == "do" and c["plan_sha"], c)
ad = X.events("auto_decision")
check("auto_decision charter_approve logged with full charter sha, cr and stage", any(e["data"]["rule"] == "charter_approve" and e["data"]["cr"] == "CR-001" and e["data"]["stage"] == "approve"
      and e["data"]["charter_sha"] == st["charter_sha"] for e in ad), ad)
chat.build()
chat.test()
chat.review()
c = chat.cr()
check("build, test PASS, review ACCEPT -> stage deliver", c["verified"] and c["stage"] == "deliver", c)
head0 = X.main_head()
r = chat.deliver_and_learn()
check("Learn done -> the engine merged and started the next CR (the Stop is blocked once: go on with CR-002)", "CR-002" in json.dumps(r), r)
check("main moved: auto/CR-001 is merged (fast-forward) and main HEAD differs", X.merged("auto/CR-001") and X.main_head() != head0 and X.main_head() == W.rev(MAIN, "refs/heads/auto/CR-001"))
check("the file and the report are in main", (MAIN / "src" / "login" / "form.py").exists() and any((MAIN / "docs" / "reports").glob("*CR-001*.md")))
check("pushed to the local bare origin", X.origin_head() == X.main_head(), (X.origin_head(), X.main_head()))
mw = store.load(str(MAIN))
check("main log: CR-001 delivered, lease gone", engine.get_cr(mw, "CR-001")["status"] == "delivered" and not engine.get_cr(mw, "CR-001")["lease"])
st = S.read(PID)
check("state: now CR-002 on auto/CR-002, base = new main HEAD, still running", st["state"] == "running" and st["cr"] == "CR-002" and st["branch"] == "auto/CR-002" and st["base"] == X.main_head(), st)
check("worktree switched to auto/CR-002 at main HEAD", W.current_branch(wt) == "auto/CR-002" and W.rev(wt) == X.main_head())
wk = store.load(str(wt))
check("CR-002 imported into the worktree log and active; main CR-002 leased", wk["active"] == "CR-002" and engine.get_cr(store.load(str(MAIN)), "CR-002")["lease"] == "auto-CR-002")
rules = {d["data"]["rule"] for d in X.events("auto_decision")}
check("auto_decision rules logged: charter_approve, deliver_ff, charter_next_cr", {"charter_approve", "deliver_ff", "charter_next_cr"} <= rules, rules)
check("autopilot.merged event carries cr, branch, pushed", any(e["data"].get("cr") == "CR-001" and e["data"].get("pushed") is True for e in X.events("autopilot.merged")))
check("state.decisions counts them", S.read(PID)["decisions"] >= 3, S.read(PID)["decisions"])

# ------------------------------------------------------------------ CR-002 (the same way), then CR-003 is the last
for n in (2, 3):
    cr = "CR-00%d" % n
    chat = X.Chat()
    chat.prompt("go")
    chat.plan_stop()
    chat.exit_plan()
    chat.build(rel="src/login/f%d.py" % n, text="v = %d\n" % n)
    chat.test()
    chat.review()
    r = chat.deliver_and_learn()
    if n == 2:
        check("CR-002 delivered and merged; CR-003 started", X.merged("auto/CR-002") and S.read(PID)["cr"] == "CR-003" and "CR-003" in json.dumps(r), (S.read(PID), r))
check("CR-003 (last in ends) delivered: run ended:done, no further block", S.read(PID)["state"] == "ended" and S.read(PID)["ended_reason"] == "done", S.read(PID))
check("autopilot.ended event: done", any(e["data"].get("reason") == "done" for e in X.events("autopilot.ended")))
check("origin has all three", X.origin_head() == X.main_head() and X.merged("auto/CR-003"))
mw = store.load(str(MAIN))
check("main log: three CRs delivered", [engine.get_cr(mw, "CR-00%d" % i)["status"] for i in (1, 2, 3)] == ["delivered"] * 3)
r = chat.stop("again")
check("after the end a Stop pushes nothing (no cr_continue, no block)", r.get("decision") != "block", r)

# ------------------------------------------------------------------ red-team 13: two verifier FAIL hand-backs -> engine block verify_twice -> H7 pause
cr, chat = X.new_run("rt13")
chat.prompt("go"); chat.plan_stop(); chat.exit_plan()
chat.build(rel="src/rt13.py")
chat.test("FAIL", "`pytest` -> 3 failed, 9 passed")
c = chat.cr()
check("13: first FAIL: verify fail:1, run still running", c["stages"]["verify"] == "fail:1" and c["status"] == "open" and S.read(PID)["state"] == "running", c)
chat.build(rel="src/rt13b.py")
chat.test("FAIL", "`pytest` -> 2 failed, 10 passed")
c = chat.cr()
st = S.read(PID)
check("13: second FAIL: the ENGINE blocked the CR with verify_twice", c["status"] == "blocked" and c["blocked"] == "verify_twice" and engine.block_reason(chat.work()) == "verify_twice", c)
check("13: the H7 hard stop paused the run (cr_blocked), stop rule H7", st["state"] == "paused" and st["paused_reason"] == "cr_blocked" and st["stop"]["rule"].startswith("H7"), st)
check("13: hard_stop event H7 carries the CR", any(e["data"]["rule"] == "H7" and e["data"]["cr"] == cr for e in X.events("autopilot.hard_stop")))
r = chat.agent_call("backend-engineer")
check("13: a builder Agent call on the blocked CR is refused (cr_blocked)", F.denied((r, "", 0))[0], r)

print("\nALL PASS" if not X.fails else "\nFAILED: %d" % X.fails)
sys.exit(1 if X.fails else 0)
