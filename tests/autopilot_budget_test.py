#!/usr/bin/env python3
"""Phase 6 T5 budget and time (spec section 4; red-team 11 and 12): the math (same window, week reset, second reset, stale and odd plan.json, 90 % / 100 %, time),
budget.evaluate / close_if_reached / agent_gate, per-CR token measurement from ledger rows of the run's own sessions ("not measured" otherwise), and the hook path:
plan.json 34 -> 45 with a cap of 10 ends the run (H8, ended:budget), a clock past started + time ends it (ended:time), a stale plan.json counts as reached, a stage
Agent call is refused at 90 % (`limit_near`) by the stage module. Temp sandbox, no network. Run: python3 tests/autopilot_budget_test.py"""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import autopilot_engine_fixture as X
from autopilot_engine_fixture import check, S, PID, MAIN, budget, F, STATE, DEV

X.build()
R0 = float(F.RESETS)
DAY = 86400.0


def plan(pct, resets=R0, fresh=True):
    return {"pct": float(pct), "resets_at": float(resets), "age": 0 if fresh else 2000, "fresh": fresh}


cr, chat = X.new_run("budget")
c = S.check(PID)[2]
st = S.read(PID)
check("start recorded budget_start 34 %", st["budget_start"]["pct"] == 34.0)
for pct, level in ((34, "ok"), (38.9, "ok"), (43, "near"), (43.9, "near"), (44, "reached"), (60, "reached")):
    ev = budget.evaluate(PID, c, plan(pct))
    check("evaluate: weekly %s %% (start 34, cap 10) -> %s" % (pct, level), ev["level"] == level, ev)
ev = budget.evaluate(PID, c, plan(40, fresh=False))
check("stale plan.json counts as reached: budget_unknown", ev["level"] == "reached" and ev["kind"] == "budget_unknown", ev)
check("plan_reading: a plan.json without rate_limits.seven_day is None -> unknown", (STATE / "plan.json").write_text(json.dumps({"at": int(time.time()), "rate_limits": {}})) is not None
      and S.plan_reading() is None)
X.write_plan(34)
# week reset: 34 -> 39 in window one, then the window resets and the status line shows 3
S.observe(PID, c, plan(39))
ev = budget.evaluate(PID, c, plan(3, R0 + 7 * DAY))
check("week reset: used = (39 - 34) + 3 = 8 -> ok", ev["lim"]["used_pct"] == 8.0 and ev["level"] == "ok", ev["lim"])
ev = budget.evaluate(PID, c, plan(4.5, R0 + 7 * DAY))
check("week reset: used 9.5 -> near", ev["level"] == "near" and ev["lim"]["used_pct"] == 9.5, ev["lim"])
ev = budget.evaluate(PID, c, plan(0.2, R0 + 14 * DAY))
check("second reset: used = 9.5 (spent so far) + 0.2 = 9.7 -> near", ev["lim"]["used_pct"] == 9.7 and ev["level"] == "near", ev["lim"])
ev = budget.evaluate(PID, c, plan(5, R0 + 14 * DAY))
check("second reset: used 14.5 -> reached", ev["level"] == "reached" and ev["kind"] == "budget", ev["lim"])
ev = budget.evaluate(PID, c, plan(5, R0 - 7 * DAY))
check("a plan.json from an OLDER window than the start is unknown (reached)", ev["kind"] == "budget_unknown", ev)

# time
cr, chat = X.new_run("time")
c = S.check(PID)[2]; st = S.read(PID); t0 = st["started"]
for dt, level in ((0, "ok"), (2.6 * 3600, "ok"), (2.7 * 3600, "near"), (3 * 3600 - 1, "near"), (3 * 3600, "reached")):
    ev = budget.evaluate(PID, c, plan(34), at=t0 + dt)
    check("evaluate: %.2f h after start (time 3h) -> %s" % (dt / 3600, level), ev["level"] == level, ev)

# agent_gate and close_if_reached
cr, chat = X.new_run("gate")
c = S.check(PID)[2]
check("agent_gate: ok -> None", budget.agent_gate(PID, c) is None)
X.write_plan(43)
g = budget.agent_gate(PID, c)
check("agent_gate: 90 % refuses a call that starts a stage (limit_near)", g and "limit_near" in g, g)
check("agent_gate: 90 % lets a call through that starts no new stage", budget.agent_gate(PID, c, starts_stage=False) is None)
X.write_plan(44)
g = budget.agent_gate(PID, c, starts_stage=False)
check("agent_gate: 100 % refuses every call (H8-budget)", g and "H8-budget" in g, g)
ev = budget.evaluate(PID, c)
r = budget.close_if_reached(PID, ev)
check("close_if_reached: ended:budget, events autopilot.ended + autopilot.budget_reached", r == "budget" and S.read(PID)["ended_reason"] == "budget"
      and X.events("autopilot.budget_reached") and any(e["data"]["reason"] == "budget" for e in X.events("autopilot.ended")))
check("close_if_reached again: idempotent (keeps the first reason, no second event)", budget.close_if_reached(PID, ev) == "budget" and len([e for e in X.events("autopilot.ended") if e["data"]["reason"] == "budget"]) == 1)

# ------------------------------------------------------------------ per CR measurement from the ledger
lg = STATE / "ledger.jsonl"
if lg.exists():
    lg.unlink()
check("per_cr: no ledger -> not measured (None)", budget.per_cr(["abcd1234"], 0, 10 ** 10) is None)
rows = [{"id": "m1", "ts": 100, "session": "abcd1234-xxxx", "fresh": 10, "output": 5, "cache_read": 100, "cache_write": 0},
        {"id": "m1", "ts": 100, "session": "abcd1234-xxxx", "fresh": 10, "output": 9, "cache_read": 100, "cache_write": 0},          # same id, more output: this copy counts
        {"id": "m2", "ts": 150, "session": "abcd1234-yyyy", "fresh": 20, "output": 1, "cache_read": 0, "cache_write": 3},
        {"id": "m3", "ts": 150, "session": "zzzz9999-yyyy", "fresh": 1000, "output": 1000},                                         # not this run's session
        {"id": "m4", "ts": 900, "session": "abcd1234-xxxx", "fresh": 1000, "output": 1000}]                                       # outside the CR's time window
lg.write_text("\n".join(json.dumps(r) for r in rows) + "\nnot json\n")
m = budget.per_cr(["abcd1234"], 50, 200)
check("per_cr: only the run's sessions, in the window, one row per id (most output)", m == {"tokens": 10 + 9 + 100 + 20 + 1 + 3, "calls": 2}, m)
check("per_cr: no matching session -> not measured", budget.per_cr(["nosuch00"], 50, 200) is None and budget.per_cr([], 0, 10 ** 9) is None)

# ------------------------------------------------------------------ hook path: red-team 11 and 12
def write_call(chat, rel="src/x.py"):
    return chat.hk("PreToolUse", tool_name="Write", tool_input={"file_path": str(chat.wt / rel), "content": "x = 1\n"})


cr, chat = X.new_run("rt11", budget=10)
r = write_call(chat)
check("11 (before the limit): a Write inside the scope is allowed", not F.denied((r, "", 0))[0], r)
X.write_plan(45)                                             # 34 -> 45, cap 10
r = write_call(chat)
st = S.read(PID)
check("11: plan.json 34 -> 45 (cap 10) -> Write denied by H8, run ended:budget", F.denied((r, "", 0))[0] and st["state"] == "ended" and st["ended_reason"] == "budget", (r, st["state"], st["ended_reason"]))
check("11: events hard_stop H8 + autopilot.ended budget", any(e["data"]["rule"] == "H8" for e in X.events("autopilot.hard_stop")) and any(e["data"]["reason"] == "budget" for e in X.events("autopilot.ended")))
check("11: the Stop is not blocked after the end", chat.stop("done").get("decision") != "block")
r = chat.agent_call("backend-engineer")
check("11: an Agent call after the end is refused too", F.denied((r, "", 0))[0], r)

cr, chat = X.new_run("rt12", time_h="1h")
st = S.read(PID)
with F.env_set(SHIPMIRACLE_TEST_NOW=str(int(st["started"]) + 3600 + 5)):
    X.write_plan(34)
    r = write_call(chat)
    st2 = S.read(PID)
check("12: clock past started + time -> Write denied (H8), run ended:time", F.denied((r, "", 0))[0] and st2["state"] == "ended" and st2["ended_reason"] == "time", (r, st2["state"], st2["ended_reason"]))
check("12: events hard_stop H8 + autopilot.ended time", any(e["data"]["rule"] == "H8" for e in X.events("autopilot.hard_stop")) and any(e["data"]["reason"] == "time" for e in X.events("autopilot.ended")))

cr, chat = X.new_run("rtstale")
X.write_plan(34, age=1000)                                   # older than 15 minutes
r = write_call(chat)
check("stale plan.json while running counts as reached: Write denied, ended:budget (H8-budget_unknown)", F.denied((r, "", 0))[0] and S.read(PID)["ended_reason"] == "budget"
      and any(e["data"].get("label") == "H8-budget_unknown" for e in X.events("autopilot.ended")), (r, S.read(PID)))

# ------------------------------------------------------------------ the stage module at 90 %: limit_near on an Agent call
cr, chat = X.new_run("near", budget=10)
chat.prompt("go")
X.write_plan(43)
r = chat.agent_call("solution-architect")
txt = json.dumps(r)
check("stage: at 90 % an Agent call that starts a stage is refused (limit_near), the run keeps running", F.denied((r, "", 0))[0] and "limit_near" in txt and S.read(PID)["state"] == "running", r)
X.write_plan(34)
r = chat.agent_call("solution-architect")
check("stage: below 90 % the same call is allowed", not F.denied((r, "", 0))[0], r)

print("\nALL PASS" if not X.fails else "\nFAILED: %d" % X.fails)
sys.exit(1 if X.fails else 0)
