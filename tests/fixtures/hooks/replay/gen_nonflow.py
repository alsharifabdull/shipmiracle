#!/usr/bin/env python3
"""Writes nonflow.jsonl next to this file: replay cases (shipmiracle/hooks/replay.py case format) for the global hooks other than the flow gate:
keep-awake, guard-hook, plan-approval, agent-cap, agent-state, keep-going, limit-wait. Run: python3 tests/fixtures/hooks/replay/gen_nonflow.py
{P} = project dir, {NOW} = epoch seconds at replay time, {T} = transcripts folder (replaced by the replay harness)."""
import json, pathlib

OUT = []


def case(session, event, pre=None, env=None, tr=None, raw=None, **inp):
    c = {"session": session, "event": event}
    if raw is not None:
        c["raw"] = raw
    else:
        c["input"] = dict({"hook_event_name": event, "session_id": session, "cwd": "{P}"}, **inp)
    for k, v in (("pre_state", pre), ("env", env), ("transcript_text", tr)):
        if v is not None:
            c[k] = v
    OUT.append(c)


def edit(s, path="src/app.py", **kw):
    return dict(tool_name="Edit", tool_input={"file_path": "{P}/" + path, "old_string": "x = 1", "new_string": "x = 2"}, **kw)


# --- keep-awake + guard-hook
case("ups", "UserPromptSubmit", prompt="hello there", permission_mode="default")
case("ups", "PreToolUse", tool_name="Read", tool_input={"file_path": "{P}/src/app.py"}, permission_mode="acceptEdits")
case("ups", "UserPromptSubmit", prompt="next", permission_mode="plan")
case("battery", "UserPromptSubmit", pre={"handoff-now": ""}, prompt="go on")
case("battery", "UserPromptSubmit", prompt="again")
case("battery-pre", "PreToolUse", pre={"handoff-now": ""}, tool_name="Read", tool_input={"file_path": "{P}/src/app.py"})
case("battery-pre", "PreToolUse", tool_name="Read", tool_input={"file_path": "{P}/src/app.py"})
case("quiet", "UserPromptSubmit", env={"SHIPMIRACLE_QUIET": "1"}, prompt="probe")
case("quiet", "PreToolUse", env={"SHIPMIRACLE_QUIET": "1"}, tool_name="Bash", tool_input={"command": "ls"})
# --- plan-approval
case("plan", "PostToolUse", tool_name="ExitPlanMode", tool_input={"plan": "p"})
case("plan", "PreToolUse", **edit("plan"))
case("plan", "PreToolUse", tool_name="Write", tool_input={"file_path": "{P}/docs/plans/x.md", "content": "plan"})
case("plan", "UserPromptSubmit", prompt="hmm, wait, not yet")
case("plan", "PreToolUse", **edit("plan"))
case("plan", "UserPromptSubmit", prompt="approved, go")
case("plan", "PreToolUse", **edit("plan"))
case("plan-old", "PreToolUse", pre={"plan-pending.plan-old": {"text": "1", "age_s": 25000}}, **edit("plan-old"))
case("plan-model", "UserPromptSubmit", pre={"proj.model.json": '{"model": "claude-sonnet-5", "ts": {NOW}}'}, prompt="plan this", permission_mode="plan")
case("plan-model", "UserPromptSubmit", prompt="and again", permission_mode="plan")
case("plan-model-opus", "UserPromptSubmit", pre={"proj.model.json": '{"model": "claude-opus-5", "ts": {NOW}}'}, prompt="plan this", permission_mode="plan")
# --- agent-cap + agent-state
case("cap-paused", "PreToolUse", pre={"agents.paused": ""}, tool_name="Agent", tool_input={"subagent_type": "qa-engineer", "prompt": "x"})
FOUR = json.dumps({"a%d" % i: {"type": "qa-engineer", "model": "sonnet", "started": 0} for i in range(4)}).replace(": 0", ": {NOW}")
case("cap-proj", "PreToolUse", pre={"proj.agents.json": FOUR}, tool_name="Agent", tool_input={"subagent_type": "qa-engineer", "prompt": "x"})
case("cap-proj-env", "PreToolUse", pre={"proj.agents.json": FOUR}, env={"SHIPMIRACLE_AGENT_CAP": "9", "SHIPMIRACLE_AGENT_CAP_TOTAL": "3"}, tool_name="Task", tool_input={"prompt": "x"})
case("cap-stale", "PreToolUse", pre={"proj.agents.json": json.dumps({"a%d" % i: {"type": "t", "model": "", "started": 1000} for i in range(6)})}, tool_name="Agent", tool_input={"prompt": "x"})
case("cap-badjson", "PreToolUse", pre={"proj.agents.json": "{broken"}, tool_name="Agent", tool_input={"prompt": "x"})
case("cap-badenv", "PreToolUse", env={"SHIPMIRACLE_AGENT_CAP": "many"}, tool_name="Agent", tool_input={"prompt": "x"})
case("cap-other", "PreToolUse", pre={"other.agents.json": json.dumps({"o%d" % i: {"type": "t", "model": "", "started": "{NOW}"} for i in range(8)}).replace('"{NOW}"', "{NOW}")}, tool_name="Agent", tool_input={"prompt": "x"})
for i in range(3):
    case("agents", "SubagentStart", agent_id="ag%d" % i, agent_type="qa-engineer")
case("agents", "SubagentStart", agent_id="ag9", agent_type="no-such-agent")
case("agents", "PreToolUse", tool_name="Agent", tool_input={"prompt": "x"})
case("agents", "SubagentStop", agent_id="ag1", agent_type="qa-engineer")
case("agents", "SubagentStop", agent_type="qa-engineer")
case("agents", "SubagentStop", agent_id="nope", agent_type="x")
case("agents-bad", "SubagentStart", raw="not json")
case("agents-empty", "SubagentStart", raw="{}")
# --- keep-going
for name, text in (("promise", "I fixed the config. Next I will run the tests."), ("done", "Everything is finished. All tests pass."), ("ask", "Which option do you prefer?"),
                   ("letme", "The build passed. Let me commit this now."), ("empty", "")):
    case("stop-" + name, "Stop", tr=text, transcript_path="{T}/stop-%s.jsonl" % name, stop_hook_active=False)
case("stop-active", "Stop", tr="Next I will run the tests.", transcript_path="{T}/stop-active.jsonl", stop_hook_active=True)
case("stop-notr", "Stop", stop_hook_active=False)
AWAY = {"away.json": json.dumps({"away": True, "ts": 0}).replace(": 0", ": {NOW}")}
case("away-ask", "Stop", pre=AWAY, tr="Should I use option A or option B? Your call.", transcript_path="{T}/away-ask.jsonl", stop_hook_active=False)
case("away-risky", "Stop", pre=AWAY, tr="Should I delete the old branch? Your call.", transcript_path="{T}/away-risky.jsonl", stop_hook_active=False)
case("away-stale", "Stop", pre={"away.json": json.dumps({"away": True, "ts": 1000})}, tr="Which one do you want?", transcript_path="{T}/away-stale.jsonl", stop_hook_active=False)
# --- limit-wait
case("limit", "StopFailure", error="rate_limit", last_assistant_message="You've hit your limit · resets 4:20pm")
case("limit", "StopFailure", error="rate_limit", last_assistant_message="limit reached")
case("limit-other", "StopFailure", error="server_error", last_assistant_message="boom")
case("limit-bad", "StopFailure", error="rate_limit", last_assistant_message="limit, resets 99:99pm")
# --- malformed input everywhere
for ev in ("UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop", "SubagentStop", "StopFailure"):
    case("bad-" + ev, ev, raw="not json at all")
    case("bad-" + ev, ev, raw="")
    case("bad-" + ev, ev, raw="[1, 2]")

for c in OUT:
    if "pre_state" in c:
        c["pre_state"] = {k: v for k, v in c["pre_state"].items()}
here = pathlib.Path(__file__).resolve().parent
(here / "nonflow.jsonl").write_text("".join(json.dumps(c, sort_keys=True) + "\n" for c in OUT))
print(len(OUT), "cases")
