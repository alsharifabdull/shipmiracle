#!/usr/bin/env python3
"""Hook dispatcher core (Phase 4a T1): hooks/shipm-hook shim + shipmiracle/hooks/{core,io}.py.
Merge rules, matchers, no short-circuit, crash injection, malformed/empty/huge input, the legacy fallback runner (broken core, mode legacy),
import budget, empty-pipeline latency, state resolution parity with flow-gate, file permissions, capture/inject only under SHIPMIRACLE_TEST.
Run: python3 tests/hooks_core_test.py   (needs /usr/bin/python3 for the timing and import-budget checks, as the hook command uses it)"""
import ast, json, os, pathlib, re, shutil, stat, subprocess, sys, tempfile, time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
TMP = pathlib.Path(tempfile.mkdtemp()).resolve()
os.environ.update(SHIPMIRACLE_TEST="1", SHIPMIRACLE_HOME=str(TMP / "home"), SHIPMIRACLE_STATE=str(TMP / "state"), SHIPMIRACLE_CONFIG=str(TMP / "config"),
                  SHIPMIRACLE_DEV=str(TMP / "dev"), SHIPMIRACLE_WS=str(TMP / "ws"), HOME=str(TMP / "home"))      # HOME too: io.state_dir() honours SHIPMIRACLE_STATE only in a complete temp sandbox (P6 sec M4)
for k in ("SHIPMIRACLE_QUIET", "SHIPMIRACLE_HOOK_INJECT", "SHIPMIRACLE_HOOK_CAPTURE", "SHIPMIRACLE_HOOK_NO_LOAD", "CLAUDE_PROJECT_DIR"):
    os.environ.pop(k, None)
(TMP / "config").mkdir(); (TMP / "state").mkdir(); (TMP / "dev").mkdir(); (TMP / "home").mkdir()
from shipmiracle.hooks import core, io as hio  # noqa: E402
import shipmiracle_timing as T  # noqa: E402

PY = "/usr/bin/python3" if os.path.exists("/usr/bin/python3") else sys.executable
HOOK = ROOT / "hooks" / "shipm-hook"
fails = 0


def check(name, ok, info=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(info)))
    fails += 0 if ok else 1


def cfg(mode_value=None, raw=None):
    p = TMP / "config" / "config.json"
    if raw is not None:
        p.write_text(raw)
    elif mode_value is None:
        p.exists() and p.unlink()
    else:
        p.write_text(json.dumps({"hooks.dispatcher": mode_value}))
    core._FILES.clear()


def log_text():
    p = TMP / "state" / "flow-errors.log"
    return p.read_text() if p.exists() else ""


R = core.Result
EV = "TestEvt"


def regs(*mods, event=EV):
    """Register test modules (name, matcher, fn[, project]) on a private event, clear it first."""
    core.PIPELINES[event] = []
    for m in mods:
        core.register(event, m[0], m[1], m[2], len(m) > 3 and m[3])


def go(event, payload=None, raw=None, slow=False, env=None):
    raw = raw if raw is not None else json.dumps(payload or {}).encode()
    return core.run(event, raw, slow, env)


# ---------------------------------------------------------------- 1 shim shape
lines = HOOK.read_text().splitlines()
check("shim is at most 30 lines", len(lines) <= 30, len(lines))
check("shim is executable with a python shebang", os.access(HOOK, os.X_OK) and lines[0].startswith("#!") and "python3" in lines[0])
src = HOOK.read_text()
check("shim: no shell=True, no Shipmiracle import except core, bytecode writing on", "shell=True" not in src and "dont_write_bytecode = False" in src and src.count("import shipmiracle") == 0)
for f in sorted((ROOT / "shipmiracle" / "hooks").glob("*.py")):
    if f.name != "spec.py":
        check("no shell=True in shipmiracle/hooks/" + f.name, "shell=True" not in f.read_text())
legacy_table = {"UserPromptSubmit": ["keep-awake", "guard-hook", "plan-approval", "flow-gate"],
                "PreToolUse": ["keep-awake", "guard-hook", "plan-approval", "agent-cap", "flow-gate"],
                "PostToolUse": ["plan-approval", "flow-gate"], "Stop": ["keep-going", "flow-gate"], "StopFailure": ["limit-wait"],
                "SubagentStart": ["agent-state"], "SubagentStop": ["agent-state", "flow-gate"], "StatusLine": ["plan-capture"]}
m = re.search(r"^T = (\{.*\})$", src, re.M)
tbl = ast.literal_eval(m.group(1)) if m else {}
check("shim legacy table lists exactly today's registered scripts per event (docs/baseline hook_registrations)",
      {e: [t.split(":")[0] for t in v.split()] for e, v in tbl.items()} == legacy_table, tbl)
check("shim legacy table matchers equal the registration matchers",
      tbl.get("PreToolUse", "").split()[2:] == ["plan-approval:Edit|Write|NotebookEdit", "agent-cap:Agent|Task", "flow-gate:ExitPlanMode|Edit|Write|NotebookEdit|MultiEdit|Bash|Read|Grep|Glob|LS|NotebookRead"]   # G11: the fallback also sends the read tools to the isolation check
      and tbl.get("PostToolUse", "").split() == ["plan-approval:ExitPlanMode", "flow-gate:Edit|Write|NotebookEdit|MultiEdit"])
if (ROOT / "hooks" / "flow-gate.sh").exists():          # the legacy shell scripts exist only in the owner's checkout
    check("every legacy script of the table exists in hooks/", all((ROOT / "hooks" / (s + ".sh")).exists() for v in legacy_table.values() for s in v))

# ---------------------------------------------------------------- 2 merge rules
def mg(event, *rs):
    return core.merge(event, list(rs))

_fl = [sl for sl in core.PIPELINES["PreToolUse"] if sl.name == "flow"]
check("P-1602: the PreToolUse flow slot matches Read, Grep, Glob, LS and NotebookRead (project isolation) as well as the file modifiers and Bash",
      len(_fl) == 1 and all(__import__("re").fullmatch(_fl[0].matcher, t) for t in ("Read", "Grep", "Glob", "LS", "NotebookRead", "Edit", "Write", "MultiEdit", "NotebookEdit", "Bash", "ExitPlanMode")) and not __import__("re").fullmatch(_fl[0].matcher, "WebFetch"), _fl and _fl[0].matcher)
o, e, c = mg("PreToolUse", R(block=True, reason="A"), R(block=True, reason="B"))
d = json.loads(o)
check("PreToolUse: two denies join with a newline in pipeline order, exit 0",
      d["hookSpecificOutput"] == {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "A\nB"} and c == 0 and e == b"")
o, e, c = mg("PreToolUse", R(block=True, reason="A"), R(additional_context="ctx1"), R(additional_context="ctx2"), R(system_message="s1"), R(system_message="s2"))
d = json.loads(o)
check("PreToolUse: contexts join with a space and stay next to the deny; system messages join",
      d["hookSpecificOutput"]["additionalContext"] == "ctx1 ctx2" and d["hookSpecificOutput"]["permissionDecision"] == "deny" and d["systemMessage"] == "s1 s2" and c == 0, d)
o, e, c = mg("Stop", R(block=True, reason="keep going"), R(block=True, reason="QA missing"))
check("Stop: blocks join into one decision block", json.loads(o) == {"decision": "block", "reason": "keep going\nQA missing"} and c == 0)
o, e, c = mg("SubagentStop", R(block=True, reason="x"))
check("SubagentStop: decision block", json.loads(o) == {"decision": "block", "reason": "x"})
o, e, c = mg("UserPromptSubmit", R(block=True, reason="no prompt"))
check("an event without a structured block form: legacy exit 2 with the reasons on stderr", c == 2 and e == b"no prompt\n" and o == b"")
o, e, c = mg("PostToolUse", R(block=True, reason="r1\n"), R(block=True, reason="r2"))
check("exit-2 style blocks on PostToolUse join with newline, one trailing newline", c == 2 and e == b"r1\nr2\n")
o, e, c = mg("UserPromptSubmit", R(plain_stdout="battery low, wrap up\n"))
check("plain stdout alone is byte-identical (trailing newline kept)", o == b"battery low, wrap up\n" and c == 0 and e == b"")
o, e, c = mg("SessionStart", R(plain_stdout="no newline"))
check("plain stdout without newline stays without newline", o == b"no newline")
o, e, c = mg("SessionStart", R(plain_stdout="line one\n"), R(plain_stdout="line two"))
check("two plain outputs: concatenated after a newline, space otherwise", o == b"line one\nline two")
o, e, c = mg("SessionStart", R(plain_stdout="a"), R(plain_stdout="b"))
check("two plain outputs without newline are joined by a space", o == b"a b")
o, e, c = mg("UserPromptSubmit", R(plain_stdout="plain text\n"), R(additional_context="ctx"))
d = json.loads(o)
check("plain stdout next to structured output travels as additionalContext", d["hookSpecificOutput"] == {"hookEventName": "UserPromptSubmit", "additionalContext": "ctx plain text"}, d)
o, e, c = mg("Stop", R(additional_context="note"))
check("an event without additionalContext shows context as systemMessage", json.loads(o) == {"systemMessage": "note"})
o, e, c = mg("UserPromptSubmit", R(), R(exit_code=1))
check("modules with nothing to say produce empty output and exit 0 (their own exit codes do not leak)", (o, e, c) == (b"", b"", 0))
check("no results: empty output", mg("Stop") == (b"", b"", 0))
o, e, c = mg("PreToolUse", R(block=True))
check("a block without text still carries a reason", json.loads(o)["hookSpecificOutput"]["permissionDecisionReason"] == "blocked")
o, e, c = mg("UserPromptSubmit", R(plain_stdout="caf\u00e9 \u2713\n"))
check("non-ASCII plain stdout is UTF-8 identical", o == "caf\u00e9 \u2713\n".encode("utf-8"))
r = R(block=True, reason="x", effects=["e"])
check("Result carries block/reason/additional_context/system_message/plain_stdout/exit_code/effects", (r.block, r.reason, r.additional_context, r.system_message, r.plain_stdout, r.exit_code, r.effects) == (True, "x", "", "", "", 0, ["e"]) and R().effects == [] and R() == R() and R() != r)

# ---------------------------------------------------------------- 3 matchers, order, no short-circuit
seen = []
def mod(name, res=None, boom=False):
    def fn(ctx):
        seen.append(name)
        if boom:
            raise ZeroDivisionError("boom " + name)
        return res
    return fn

regs(("a", "Edit|Write", mod("a", R(block=True, reason="A"))), ("b", "*", mod("b", R(block=True, reason="B"))), ("c", "Bash", mod("c", R(additional_context="C"))))
o, e, c = go(EV, {"tool_name": "Edit"})
check("matcher Edit|Write matches Edit; * always; Bash does not match Edit", seen == ["a", "b"], seen)
check("no short-circuit: the module after a blocking one still ran and its reason is joined", EV != "PreToolUse" and c == 2 and e == b"A\nB\n", (c, e))
seen.clear(); go(EV, {"tool_name": "MultiEdit"})
check("matchers are full matches (Edit|Write does not match MultiEdit)", seen == ["b"], seen)
seen.clear(); go(EV, {"tool_name": "Bash"})
check("tool Bash runs b then c in registration order", seen == ["b", "c"], seen)
seen.clear(); go(EV, {})
check("no tool name: only * matchers run", seen == ["b"], seen)
regs(("a", "*", mod("a", R(block=True, reason="A"))), ("b", "*", mod("b", R(plain_stdout="B\n"))), event="PreToolUse")
seen.clear(); o, e, c = go("PreToolUse", {"tool_name": "Bash"})
d = json.loads(o)
check("PreToolUse: first denies, second still ran, its text sits beside the deny", seen == ["a", "b"] and d["hookSpecificOutput"]["permissionDecision"] == "deny" and "B" in d["hookSpecificOutput"]["additionalContext"] and c == 0, (seen, o))
core.PIPELINES["PreToolUse"] = core._p([("keep_awake", "*"), ("guard_hook", "*"), ("plan_approval", "Edit|Write|NotebookEdit"), ("agent_cap", "Agent|Task"), ("flow", core.FILE_MODS), ("stage", "Agent|Task"), ("autopilot", "*"), ("block_secrets", "Bash", True), ("shipmiracle_state", "*", True)])
tbl2 = {e: [(s.name, s.matcher, s.project) for s in v] for e, v in core.PIPELINES.items()}
check("PIPELINES table matches spec 2.4 (order and matchers)",
      [n for n, _, _ in tbl2["UserPromptSubmit"]] == ["keep_awake", "guard_hook", "plan_approval", "flow", "stage", "autopilot", "context", "shipmiracle_state"]
      and [n for n, _, _ in tbl2["PreToolUse"]] == ["keep_awake", "guard_hook", "plan_approval", "agent_cap", "flow", "stage", "autopilot", "block_secrets", "shipmiracle_state"]
      and [n for n, _, _ in tbl2["PostToolUse"]] == ["plan_approval", "flow", "stage", "autopilot", "save_plan"]
      and [n for n, _, _ in tbl2["Stop"]] == ["keep_going", "flow", "stage", "autopilot", "stop_fast", "shipmiracle_state"] and [n for n, _, _ in tbl2["Stop--slow"]] == ["stop_tests"]
      and [n for n, _, _ in tbl2["SubagentStop"]] == ["agent_state", "flow", "stage", "autopilot"] and [n for n, _, _ in tbl2["StopFailure"]] == ["limit_wait"]
      and [n for n, _, _ in tbl2["StatusLine"]] == ["plan_capture"] and tbl2["PostToolUse"][4] == ("save_plan", "ExitPlanMode", True)
      and tbl2["PreToolUse"][7] == ("block_secrets", "Bash", True) and tbl2["PreToolUse"][5] == ("stage", "Agent|Task", False) and tbl2["PreToolUse"][6] == ("autopilot", "*", False)
      and tbl2["PostToolUse"][2] == ("stage", "ExitPlanMode|Agent|Task", False) and tbl2["PostToolUse"][3] == ("autopilot", "Write|Edit|MultiEdit|NotebookEdit", False), tbl2)

# register API
regs(("x", "*", mod("x1", R(plain_stdout="one"))))
core.register(EV, "x", None, mod("x2", R(plain_stdout="two")))
seen.clear(); o, _, _ = go(EV, {})
check("register replaces the function of an existing slot; a new name is appended", len(core.PIPELINES[EV]) == 1 and seen == ["x2"] and o == b"two", (seen, o))
core.register(EV, "y", "Read", mod("y", R(plain_stdout="y")))
seen.clear(); go(EV, {"tool_name": "Read"})
check("register(event, name, matcher, fn): appended slot with its own matcher", seen == ["x2", "y"], seen)
s = core.register("PostToolUse", "save_plan", None, mod("sp"), False)
check("register never downgrades a project slot to a global one", s.project is True and s.matcher == "ExitPlanMode")
core.unregister("PostToolUse", "save_plan")

# ---------------------------------------------------------------- 4 crash isolation (in-process)
cfg("v1")
regs(("good1", "*", mod("good1", R(additional_context="G1"))), ("bad", "*", mod("bad", boom=True)), ("good2", "*", mod("good2", R(additional_context="G2"))), event="UserPromptSubmit")
(TMP / "state" / "flow-errors.log").exists() and (TMP / "state" / "flow-errors.log").unlink()
o, e, c = go("UserPromptSubmit", {"hook_event_name": "UserPromptSubmit"})
check("a module that raises: the others' output is unchanged, exit 0", json.loads(o)["hookSpecificOutput"]["additionalContext"] == "G1 G2" and c == 0 and e == b"", o)
lg = log_text()
check("the crash is logged in flow-errors.log with the gate's format plus module=", re.match(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d module=bad .*ZeroDivisionError.*boom bad", lg) is not None and lg.count("\n") == 1, lg[:200])
evs = (TMP / "state" / "v1" / "events.jsonl")
check("the crash is also an event hook_module_error", evs.exists() and any(json.loads(l)["kind"] == "hook_module_error" and json.loads(l)["data"]["module"] == "bad" for l in evs.read_text().splitlines()))
regs(("good1", "*", mod("good1", R(additional_context="G1"))), ("good2", "*", mod("good2", R(additional_context="G2"))), event="UserPromptSubmit")
o2, _, _ = go("UserPromptSubmit", {})
check("with the crashing module absent the output is the same (crash counts as no output)", o2 == o)
regs(("m", "*", mod("m", R(plain_stdout="m-out\n"))), event="UserPromptSubmit")
os.environ["SHIPMIRACLE_HOOK_INJECT"] = "m"
log0 = len(log_text())
o, e, c = go("UserPromptSubmit", {})
check("SHIPMIRACLE_HOOK_INJECT=<module> (SHIPMIRACLE_TEST=1) raises inside that module: no output, exit 0, logged", o == b"" and c == 0 and "injected crash in m" in log_text()[log0:])
os.environ["SHIPMIRACLE_TEST"] = "0"
o, e, c = go("UserPromptSubmit", {})
check("SHIPMIRACLE_HOOK_INJECT is ignored without SHIPMIRACLE_TEST=1", o == b"m-out\n")
os.environ["SHIPMIRACLE_TEST"] = "1"; del os.environ["SHIPMIRACLE_HOOK_INJECT"]
regs(("noop", "*", lambda ctx: None), event="UserPromptSubmit")
check("a module returning None is no output", go("UserPromptSubmit", {}) == (b"", b"", 0))
regs(("w", "*", lambda ctx: "not a Result"), event="UserPromptSubmit")
check("a module returning a non-Result is no output", go("UserPromptSubmit", {}) == (b"", b"", 0))
os.environ["SHIPMIRACLE_HOOK_INJECT"] = "a, b ,c"
regs(("b", "*", mod("b", R(plain_stdout="b"))), event="UserPromptSubmit")
check("SHIPMIRACLE_HOOK_INJECT accepts a comma list", go("UserPromptSubmit", {})[0] == b"")
del os.environ["SHIPMIRACLE_HOOK_INJECT"]

# ---------------------------------------------------------------- 5 Ctx
seen_ctx = []
regs(("p", "*", lambda ctx: seen_ctx.append(ctx)), event="UserPromptSubmit")
proj = TMP / "dev" / "Proj"; (proj / "sub").mkdir(parents=True)
payload = {"hook_event_name": "UserPromptSubmit", "session_id": "ab/../c d", "agent_id": "ag1", "agent_type": "qa", "cwd": str(proj / "sub"), "tool_name": "Read", "prompt": "x"}
go("UserPromptSubmit", payload)
cx = seen_ctx[-1]
check("Ctx: event, tool, session (raw and sanitized), agent fields, pd", (cx.event, cx.tool_name, cx.session_id, cx.sid, cx.agent_id, cx.agent_type, cx.pd, cx.is_agent) == ("UserPromptSubmit", "Read", "ab/../c d", "abcd", "ag1", "qa", str(proj / "sub"), True), vars(cx))
check("Ctx: project falls back to the folder basename; raw bytes kept", cx.project == "sub" and json.loads(cx.raw)["prompt"] == "x")
os.environ["CLAUDE_PROJECT_DIR"] = str(proj)
go("UserPromptSubmit", payload); cx = seen_ctx[-1]
check("Ctx: CLAUDE_PROJECT_DIR wins over cwd", cx.pd == str(proj) and cx.project == "Proj")
del os.environ["CLAUDE_PROJECT_DIR"]
for label, raw in (("malformed JSON", b"{not json"), ("empty stdin", b""), ("whitespace", b"  \n"), ("JSON list", b"[1,2]"), ("JSON string", b'"x"'), ("invalid UTF-8", b'{"a":"\xff\xfe"}')):
    seen_ctx.clear(); out = go("UserPromptSubmit", raw=raw)
    check("Ctx tolerates " + label + " (empty dict, module still runs, exit 0)", len(seen_ctx) == 1 and (seen_ctx[0].data == {} or label == "invalid UTF-8") and out == (b"", b"", 0), out)
seen_ctx.clear(); go("UserPromptSubmit", raw=b'{"tool_name": 5, "session_id": null, "agent_id": ["x"]}')
check("Ctx ignores non-string fields", (seen_ctx[0].tool_name, seen_ctx[0].session_id, seen_ctx[0].agent_id, seen_ctx[0].sid) == ("", "", "", "x"))
big = json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": "x" * (1 << 20), "tool_name": "Read"}).encode()
seen_ctx.clear(); t0 = time.time(); out = go("UserPromptSubmit", raw=big)
check("1 MB input is parsed and passed on (exit 0)", len(seen_ctx) == 1 and len(seen_ctx[0].raw) == len(big) and seen_ctx[0].tool_name == "Read" and out == (b"", b"", 0), time.time() - t0)
mj = TMP / "memo.json"; mj.write_text('{"a": 1}')
cx = core.Ctx(b"{}", "X"); first = cx.memo_json(mj)
mj.write_text('{"a": 2}')
check("memo_json is cached per process; missing and bad files give the default", first == {"a": 1} and cx.memo_json(mj) == {"a": 1} and cx.memo_json(TMP / "nope.json", {}) == {} and cx.memo_json(TMP / "nope.json") is None)
(TMP / "bad.json").write_text("{x"); check("memo_json: unparseable file gives the default", cx.memo_json(TMP / "bad.json", "dflt") == "dflt")
check("Ctx state resolution", core.Ctx(b"{}", "X").state == str(TMP / "state"))

# ---------------------------------------------------------------- 6 modes
HAVE_LEGACY = core._legacy_scripts_present()      # the public export has no legacy shell scripts: every mode then resolves to v1 (core.mode)
LEGACY, SHADOW = ("legacy", "shadow") if HAVE_LEGACY else ("v1", "v1")
cfg(None); check("mode: no config file is legacy", core.mode() == LEGACY)
cfg("v1"); check("mode: v1", core.mode() == "v1")
cfg("shadow"); check("mode: shadow", core.mode() == SHADOW)
cfg("legacy"); check("mode: legacy", core.mode() == LEGACY)
cfg("V2"); check("mode: unknown value is legacy", core.mode() == LEGACY)
cfg(raw="{broken"); check("mode: damaged config is legacy", core.mode() == LEGACY)
cfg(raw="[1]"); check("mode: non-object config is legacy", core.mode() == LEGACY)
cfg(raw=json.dumps({"hooks.dispatcher": "v1", "pad": "x" * (2 << 20)})); check("mode: config over 1 MB is not read (legacy)", core.mode() == LEGACY)
cfg("v1"); core.mode(); (TMP / "config" / "config.json").write_text(json.dumps({"hooks.dispatcher": "legacy"}))
check("mode: the read is cached in the process", core.mode() == "v1")
core._FILES.clear()
if HAVE_LEGACY:
    cfg("shadow"); check("main returns 'legacy' for shadow without reading stdin", core.main(["Stop"]) == "legacy")
    cfg("legacy"); check("main returns 'legacy' for legacy", core.main(["Stop"]) == "legacy")
else:
    print("SKIP main returns 'legacy' for shadow / legacy: the exported tree has no legacy shell scripts (mode() is v1 there)")

# ---------------------------------------------------------------- 7 quiet, switch, ownership, slow
cfg("v1")
regs(("g", "*", mod("g", R(plain_stdout="G"))), ("flow", "*", mod("flow", R(plain_stdout="F"))), ("pm", "*", mod("pm", R(plain_stdout="P")), True), event="UserPromptSubmit")
orig_owned = core.project_owned
core.project_owned = lambda pd, name, dev=None: True
seen.clear(); out = go("UserPromptSubmit", {}, env=dict(os.environ, SHIPMIRACLE_QUIET="1"))
check("SHIPMIRACLE_QUIET: global modules skip, flow still runs (its own quiet note), project modules ignore SHIPMIRACLE_QUIET", seen == ["flow", "pm"], seen)
core.project_owned = lambda pd, name, dev=None: False
seen.clear(); go("UserPromptSubmit", {})
check("a project module does not run when the project is not owned by the dispatcher", seen == ["g", "flow"], seen)
core.project_owned = orig_owned
seen.clear(); go("UserPromptSubmit", {})
check("project_owned defaults to False on any error (no registry)", seen == ["g", "flow"], seen)
regs(("context", "*", mod("context", R(plain_stdout="N"))), event="UserPromptSubmit")
seen.clear(); go("UserPromptSubmit", {})
check("switch tokens.nudge: off by default", seen == [])
cfg(raw=json.dumps({"hooks.dispatcher": "v1", "tokens.nudge": True})); seen.clear(); go("UserPromptSubmit", {})
check("switch tokens.nudge: on runs context", seen == ["context"])
cfg(raw=json.dumps({"hooks.dispatcher": "v1", "tokens.nudge": "off"})); seen.clear(); go("UserPromptSubmit", {})
check("switch tokens.nudge: 'off' stays off", seen == [])
cfg("v1")
regs(("t", "*", mod("t", R(plain_stdout="T"))), event="Stop--slow")
regs(("n", "*", mod("n", R(plain_stdout="N"))), event="Stop")
seen.clear(); o1 = go("Stop", {}, slow=True); o2 = go("Stop", {})
check("--slow runs only the Stop--slow pipeline; plain Stop never runs it", seen == ["t", "n"] and o1[0] == b"T" and o2[0] == b"N", seen)
core.PIPELINES.pop("Stop--slow"); core.PIPELINES["Stop--slow"] = core._p([("stop_tests", "*", True)]); core.PIPELINES["Stop"] = core._p(["keep_going", "flow", ("stop_fast", "*", True), ("shipmiracle_state", "*", True)])

# project_owned with a real registry and project settings
from shipmiracle import projects as aprojects  # noqa: E402
subprocess.run(["git", "init", "-q", str(proj)], check=True)
pid = aprojects.project_id(proj)
(TMP / "config" / "registry.json").write_text(json.dumps({"v": 1, "projects": {}}))
check("project_owned: project not in the registry is False", core.project_owned(str(proj), "shipmiracle_state", str(TMP / "dev")) is False)
(TMP / "config" / "registry.json").write_text(json.dumps({"v": 1, "projects": {pid: {}}})); core._FILES.clear()
check("project_owned: in the registry and no project hook registration is True", core.project_owned(str(proj), "shipmiracle_state", str(TMP / "dev")) is True)
(proj / ".claude").mkdir(exist_ok=True)
(proj / ".claude" / "settings.json").write_text(json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/shipm-state.sh done"}]}]}}))
check("project_owned: the project still registers .claude/hooks/shipm-state.sh -> False", core.project_owned(str(proj), "shipmiracle_state", str(TMP / "dev")) is False)
check("project_owned: another hook of that project is still owned", core.project_owned(str(proj), "block_secrets", str(TMP / "dev")) is True)
check("project_owned: unknown hook name and global names are False", core.project_owned(str(proj), "flow", str(TMP / "dev")) is False and core.project_owned(str(proj), "nonsense") is False)
(TMP / "config" / "registry.json").write_text("{damaged"); core._FILES.clear()
check("project_owned: damaged registry is False", core.project_owned(str(proj), "block_secrets", str(TMP / "dev")) is False)

# ---------------------------------------------------------------- 8 main never raises
cfg("v1")
real_run = core.run
def bad_run(*a, **k):
    raise RuntimeError("dispatcher bug")
core.run = bad_run
import io as _io
sys.stdin = _io.TextIOWrapper(_io.BytesIO(b"{}"))
log0 = len(log_text())
check("main: an internal error gives exit 0 (fail open)", core.main(["PreToolUse"]) == 0)
check("main: the internal error is logged with module=dispatcher", "module=dispatcher" in log_text()[log0:] and "dispatcher bug" in log_text()[log0:])
core.run = real_run
sys.stdin = sys.__stdin__

# ---------------------------------------------------------------- 9 capture
cap = TMP / "cap"
os.environ["SHIPMIRACLE_HOOK_CAPTURE"] = str(cap)
raw = b'{"tool_name": "Bash", "tool_input": {"command": "echo sk-ant-123"}, "session_id": "s"}'
go("PreToolUse", raw=raw)
f = cap / "PreToolUse-Bash-main.json"
check("SHIPMIRACLE_HOOK_CAPTURE (SHIPMIRACLE_TEST=1) writes the raw input, unredacted, mode 0600, folder 0700",
      f.exists() and f.read_bytes() == raw and stat.S_IMODE(f.stat().st_mode) == 0o600 and stat.S_IMODE(cap.stat().st_mode) == 0o700)
go("PreToolUse", raw=raw.replace(b'"session_id"', b'"agent_id": "a1", "session_id"'))
check("capture names agent calls -agent", (cap / "PreToolUse-Bash-agent.json").exists())
shutil.rmtree(cap); os.environ["SHIPMIRACLE_TEST"] = "0"
go("PreToolUse", raw=raw)
check("SHIPMIRACLE_HOOK_CAPTURE is ignored without SHIPMIRACLE_TEST=1", not cap.exists())
os.environ["SHIPMIRACLE_TEST"] = "1"; del os.environ["SHIPMIRACLE_HOOK_CAPTURE"]

# ---------------------------------------------------------------- 10 io
d = TMP / "io" / "a" / "b"
hio.atomic_json(str(d / "x.json"), {"k": [1, "\u00e9"]})
check("atomic_json: content, file 0600, every created folder 0700", json.loads((d / "x.json").read_text(encoding="utf-8")) == {"k": [1, "\u00e9"]}
      and stat.S_IMODE((d / "x.json").stat().st_mode) == 0o600 and all(stat.S_IMODE(p.stat().st_mode) == 0o700 for p in (d, d.parent, d.parent.parent)))
hio.atomic_json(str(d / "x.json"), {"k": 2})
check("atomic_json: replaces, leaves no temp file", json.loads((d / "x.json").read_text()) == {"k": 2} and [p.name for p in d.iterdir()] == ["x.json"])
try:
    hio.atomic_json(str(d / "y.json"), {"bad": object()})
    raised = False
except TypeError:
    raised = True
check("atomic_json: unserialisable data raises and leaves nothing behind", raised and [p.name for p in d.iterdir()] == ["x.json"])
(d / "link.json").symlink_to(TMP / "victim")
(TMP / "victim").write_text("keep")
hio.atomic_json(str(d / "link.json"), {"z": 1})
check("atomic_json: a symlink target is replaced, not written through", (TMP / "victim").read_text() == "keep" and json.loads((d / "link.json").read_text()) == {"z": 1})
hio.append_line(str(d / "log.txt"), "one"); hio.append_line(str(d / "log.txt"), "two\n")
check("append_line: lines, mode 0600", (d / "log.txt").read_text() == "one\ntwo\n" and stat.S_IMODE((d / "log.txt").stat().st_mode) == 0o600)
check("emit_event never raises (bad kind)", hio.emit_event("BAD KIND", {}) is False and hio.emit_event("hook_test", {"a": 1}) is True)
check("log_err never raises without an exception in flight", hio.log_err("m") is None)
sp = TMP / "state" / "flow-errors.log"
check("flow-errors.log written by io is mode 0600", stat.S_IMODE(sp.stat().st_mode) == 0o600)

# ---------------------------------------------------------------- 11 state resolution parity with flow-gate
if (ROOT / "hooks" / "flow-gate.sh").exists():          # the legacy shell gate exists only in the owner's checkout
    gate = (ROOT / "hooks" / "flow-gate.sh").read_text()
    lines_ = [l for l in gate.splitlines() if re.match(r"^(HOME|STATE|DEV|WS) = ", l)]
    check("flow-gate has the four resolution lines (HOME, STATE, DEV, WS)", [l.split(" =")[0] for l in lines_] == ["HOME", "STATE", "WS", "DEV"], lines_)
    def gate_def(name):    # a top-level function of the gate's python part, source text
        m_ = re.search(r"^def %s\(.*?(?=^\S)" % name, gate.split("#--PYTHON-BEGIN--", 1)[1], re.S | re.M)
        return m_.group(0) if m_ else ""
    defs_ = "\n".join(gate_def(n_) for n_ in ("shipmiracle_home", "shipmiracle_cfg_dir", "cfg_value", "_engine_dir", "_projects_dir"))
    probe = "import os, sys, json, pwd\nsys.argv = ['x', %r]\n" % str(ROOT / "hooks" / "flow-gate.sh") + defs_ + "\n" + "\n".join(lines_) + "\nfrom shipmiracle.hooks import core\nc = core.Ctx(b'{}', 'X')\nprint(json.dumps([[STATE, DEV, WS], [c.state, c.dev, c.ws]]))\n"
    base_env = {k: v for k, v in os.environ.items() if not k.startswith("SHIPMIRACLE_")}
    cases = {"SHIPMIRACLE_STATE set, SHIPMIRACLE_TEST unset": {"SHIPMIRACLE_STATE": str(TMP / "s1")}, "SHIPMIRACLE_STATE + SHIPMIRACLE_TEST=1": {"SHIPMIRACLE_STATE": str(TMP / "s2"), "SHIPMIRACLE_TEST": "1"},
             "nothing set": {}, "SHIPMIRACLE_STATE empty": {"SHIPMIRACLE_STATE": ""}, "SHIPMIRACLE_DEV and SHIPMIRACLE_WS set": {"SHIPMIRACLE_DEV": str(TMP / "dv"), "SHIPMIRACLE_WS": str(TMP / "wsx")}}
    (TMP / "cfgpd").mkdir(exist_ok=True); (TMP / "cfgpd" / "config.json").write_text(json.dumps({"paths.projects_dir": str(TMP / "pdir")}))
    cases["config paths.projects_dir (SHIPMIRACLE_TEST=1)"] = {"SHIPMIRACLE_TEST": "1", "SHIPMIRACLE_CONFIG": str(TMP / "cfgpd"), "SHIPMIRACLE_STATE": str(TMP / "s3")}
    for label, extra in cases.items():
        env = dict(base_env, HOME=str(TMP / "home"), PYTHONPATH=str(ROOT)); env.update(extra)
        if env.get("SHIPMIRACLE_TEST") == "1" and not env.get("SHIPMIRACLE_CONFIG"):
            # In test mode without SHIPMIRACLE_HOME the gate reads no config, while the hook core falls back to the account's real ~/.config (it can hold
            # paths.projects_dir on the runner's machine). Give both an empty config folder so the comparison does not depend on the runner's own config.
            (TMP / "cfgempty").mkdir(exist_ok=True); env["SHIPMIRACLE_CONFIG"] = str(TMP / "cfgempty")
        p = subprocess.run([PY, "-c", probe], env=env, capture_output=True, text=True, cwd=str(TMP))
        try:
            g, c_ = json.loads(p.stdout)
            check("state/dev/ws resolution equals flow-gate: " + label, g == c_, (g, c_))
        except ValueError:
            check("state/dev/ws resolution equals flow-gate: " + label, False, p.stderr[-300:])

# ---------------------------------------------------------------- 12 subprocess: shim + real core, crash injection through the process boundary
def run_shim(hook, args, raw, env_extra=None, cwd=None, timeout=90):
    env = dict(os.environ); env.update(env_extra or {})
    t0 = time.time()
    p = subprocess.run([PY, "-I", "-S", "-X", "pycache_prefix=" + str(TMP / "pyc"), str(hook)] + args, input=raw, capture_output=True, env=env, cwd=cwd, timeout=timeout)
    return p, time.time() - t0

cfg("v1")
drv = TMP / "driver.py"
drv.write_text("import sys\nsys.path.insert(0, %r)\nfrom shipmiracle.hooks import core\nR = core.Result\n"
               "core.register('PreToolUse', 'g1', '*', lambda c: R(block=True, reason='deny one'))\n"
               "core.register('PreToolUse', 'bad', '*', lambda c: 1 / 0)\n"
               "core.register('PreToolUse', 'g2', 'Bash', lambda c: R(block=True, reason='deny two', additional_context='ctx'))\n"
               "sys.exit(core.main(sys.argv[1:]))\n" % str(ROOT))
p, _ = run_shim(drv, ["PreToolUse"], b'{"tool_name":"Bash","session_id":"s"}')
d = json.loads(p.stdout)
check("process: crash in the middle module, both denies joined, exit 0, nothing on stderr",
      p.returncode == 0 and d["hookSpecificOutput"]["permissionDecisionReason"] == "deny one\ndeny two" and d["hookSpecificOutput"]["additionalContext"] == "ctx" and p.stderr == b"", (p.returncode, p.stdout, p.stderr))
check("process: the crash line is in flow-errors.log with module=bad", "module=bad" in log_text() and "ZeroDivisionError" in log_text())
p, _ = run_shim(HOOK, ["PreToolUse"], b'{"tool_name":"Bash"}', {"SHIPMIRACLE_HOOK_NO_LOAD": "1"})
check("process: the real shim with an empty pipeline prints nothing and exits 0", (p.returncode, p.stdout, p.stderr) == (0, b"", b""), p)
for label, raw in (("malformed JSON", b"{oops"), ("empty stdin", b""), ("1 MB", b'{"x":"' + b"y" * (1 << 20) + b'"}')):
    p, _ = run_shim(HOOK, ["PreToolUse"], raw, {"SHIPMIRACLE_HOOK_NO_LOAD": "1"})
    check("process: shim with " + label + ": exit 0, empty output", (p.returncode, p.stdout, p.stderr) == (0, b"", b""), p.stderr[-200:])
p, _ = run_shim(HOOK, [], b"{}", {"SHIPMIRACLE_HOOK_NO_LOAD": "1"})
check("process: no event argument is a harmless no-op", p.returncode == 0 and p.stdout == b"")
p, _ = run_shim(HOOK, ["NoSuchEvent"], b"{}", {"SHIPMIRACLE_HOOK_NO_LOAD": "1"})
check("process: unknown event is a harmless no-op", p.returncode == 0 and p.stdout == b"")
p, _ = run_shim(HOOK, ["PreToolUse"], b'{"tool_name":"Bash"}', {"SHIPMIRACLE_HOOK_NO_LOAD": "1", "SHIPMIRACLE_STATE": str(TMP / "state-ro" / "x" / "y")})
check("process: stdout closed early is not fatal (no output to write)", p.returncode == 0)

# ---------------------------------------------------------------- 13 legacy fallback (broken core, mode legacy/shadow)
wsn = [0]
def mkws(real_core, scripts, core_src="def main(argv:\n"):
    wsn[0] += 1
    ws = TMP / ("ws%d" % wsn[0]); (ws / "hooks").mkdir(parents=True)
    shutil.copy(HOOK, ws / "hooks" / "shipm-hook"); os.chmod(ws / "hooks" / "shipm-hook", 0o755)
    if real_core:
        shutil.copytree(ROOT / "shipmiracle", ws / "shipmiracle", ignore=shutil.ignore_patterns("__pycache__"))
    else:
        (ws / "shipmiracle" / "hooks").mkdir(parents=True)
        (ws / "shipmiracle" / "__init__.py").write_text(""); (ws / "shipmiracle" / "hooks" / "__init__.py").write_text(""); (ws / "shipmiracle" / "hooks" / "core.py").write_text(core_src)
    for n, body in scripts.items():
        f = ws / "hooks" / (n + ".sh"); f.write_text("#!/bin/sh\n" + body + "\n"); os.chmod(f, 0o755)
    return ws

MARK = TMP / "marks"; MARK.mkdir()
def silent(name):
    return 'echo ran >> "%s/%s"; cat >/dev/null' % (MARK, name)
def scripts(**over):
    s = {n: silent(n) for n in ("keep-awake", "guard-hook", "plan-approval", "agent-cap", "agent-state", "keep-going", "limit-wait", "plan-capture", "flow-gate")}
    s.update(over); return s
def marks():
    return sorted(p.name for p in MARK.iterdir())
def clear_marks():
    for p in MARK.iterdir(): p.unlink()
def fb(ws, event, payload, args=(), env_extra=None, raw=None):
    clear_marks()
    return run_shim(ws / "hooks" / "shipm-hook", [event] + list(args), raw if raw is not None else json.dumps(payload).encode(), env_extra)

cfg("v1")
ws = mkws(False, scripts(**{"plan-approval": 'cat >/dev/null; echo "edits blocked: plan pending" >&2; exit 2',
                            "flow-gate": 'cat >/dev/null; echo \'{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"R2 flow"}}\'', "keep-awake": silent("keep-awake")}))
(TMP / "state" / "flow-errors.log").write_text("")
p, _ = fb(ws, "PreToolUse", {"tool_name": "Edit", "session_id": "s"})
d = json.loads(p.stdout) if p.stdout else {}
check("fallback (syntax error in core): exit-2 stderr and a JSON deny are joined into one PreToolUse deny, exit 0",
      p.returncode == 0 and d.get("hookSpecificOutput", {}).get("permissionDecisionReason") == "edits blocked: plan pending\nR2 flow" and d["hookSpecificOutput"]["permissionDecision"] == "deny", (p.returncode, p.stdout, p.stderr))
check("fallback: matchers decide which scripts run (Edit: keep-awake, guard-hook, plan-approval, flow-gate; agent-cap did not run)", marks() == ["guard-hook", "keep-awake"], marks())
check("fallback: the failure is logged in flow-errors.log (module=shipmiracle-hook-fallback, core import failed)", "module=shipmiracle-hook-fallback" in log_text() and "core import failed" in log_text() and "SyntaxError" in log_text(), log_text()[-300:])
p, _ = fb(ws, "PreToolUse", {"tool_name": "WebFetch"})
check("fallback: a tool no matcher selects only runs the '*' scripts", marks() == ["guard-hook", "keep-awake"] and p.stdout == b"" and p.returncode == 0, (marks(), p.stdout))
p, _ = fb(ws, "PreToolUse", {"tool_name": "Task"})
check("fallback: Task selects agent-cap but not flow-gate or plan-approval", "agent-cap" in marks() and "flow-gate" not in marks() and "plan-approval" not in marks(), marks())
ws = mkws(False, scripts(**{"guard-hook": "cat >/dev/null; printf 'battery low, wrap up\\n'"}))
p, _ = fb(ws, "UserPromptSubmit", {"prompt": "hi"})
check("fallback: a single plain stdout is relayed byte-identical", p.stdout == b"battery low, wrap up\n" and p.returncode == 0, p.stdout)
one = '{"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "keep   spacing"}}'
ws = mkws(False, scripts(**{"flow-gate": "cat >/dev/null; printf '%s\\n' '" + one + "'"}))
p, _ = fb(ws, "UserPromptSubmit", {"prompt": "hi"})
check("fallback: a single JSON output is relayed byte-identical", p.stdout == (one + "\n").encode(), p.stdout)
ws = mkws(False, scripts(**{"guard-hook": "cat >/dev/null; printf 'plain note\\n'", "flow-gate": "cat >/dev/null; printf '%s\\n' '" + one + "'"}))
p, _ = fb(ws, "UserPromptSubmit", {"prompt": "hi"})
d = json.loads(p.stdout)
check("fallback: plain text next to JSON context is merged into one additionalContext", d["hookSpecificOutput"]["additionalContext"] == "keep   spacing plain note", p.stdout)
ws = mkws(False, scripts(**{"keep-going": "cat >/dev/null; echo 'go on' >&2; exit 2", "flow-gate": 'cat >/dev/null; echo \'{"decision":"block","reason":"QA missing"}\''}))
p, _ = fb(ws, "Stop", {"stop_hook_active": False})
check("fallback: Stop blocks (exit 2 and JSON) become one decision block", json.loads(p.stdout) == {"decision": "block", "reason": "go on\nQA missing"} and p.returncode == 0, p.stdout)
ws = mkws(False, scripts(**{"plan-approval": "cat >/dev/null; echo 'no prompt' >&2; exit 2"}))
p, _ = fb(ws, "UserPromptSubmit", {})
check("fallback: exit 2 on an event without a structured block form stays exit 2 with the stderr text", p.returncode == 2 and p.stderr == b"no prompt\n" and p.stdout == b"", (p.returncode, p.stderr))
p, _ = fb(ws, "Stop", {}, args=["--slow"])
check("fallback: Stop --slow has no legacy script (nothing runs)", marks() == [] and p.stdout == b"" and p.returncode == 0, marks())
p, _ = fb(ws, "SessionStart", {})
check("fallback: events without a registered legacy script run nothing", marks() == [] and p.returncode == 0)
payload_bytes = json.dumps({"tool_name": "Bash", "tool_input": {"command": "echo \u00e9\u2713" + "z" * 200000}, "session_id": "s"}).encode()
ws = mkws(False, scripts(**{"flow-gate": 'cat > "%s/stdin.copy"; echo "$SHIPMIRACLE_MARK" > "%s/env.copy"' % (MARK, MARK)}))
p, _ = fb(ws, "PreToolUse", None, env_extra={"SHIPMIRACLE_MARK": "marker-value"}, raw=payload_bytes)
check("fallback: the script gets the same stdin bytes (200 KB, non-ASCII) and the same env",
      (MARK / "stdin.copy").read_bytes() == payload_bytes and (MARK / "env.copy").read_text().strip() == "marker-value", p.stderr[-200:])
ws = mkws(False, scripts(**{"keep-awake": "cat >/dev/null; sleep 0.6", "guard-hook": "cat >/dev/null; sleep 0.6", "agent-cap": "sleep 0.6"}))
p, dt = fb(ws, "PreToolUse", {"tool_name": "Task"})
check("fallback: scripts run in parallel (3 x 0.6 s sleeps finish in under 1.5 s)", dt < 1.5 and p.returncode == 0, dt)
ws = mkws(False, scripts()); os.unlink(ws / "hooks" / "guard-hook.sh")
p, _ = fb(ws, "UserPromptSubmit", {})
check("fallback: a missing script is logged and the others still run", p.returncode == 0 and "keep-awake" in marks() and "guard-hook failed" in log_text(), (marks(), log_text()[-200:]))
ws = mkws(False, scripts(**{"flow-gate": "cat >/dev/null; echo oops >&2; exit 1"}))
p, _ = fb(ws, "UserPromptSubmit", {})
check("fallback: a script that exits 1 (non-blocking in Claude Code) adds nothing", (p.returncode, p.stdout) == (0, b""))
ws = mkws(False, scripts(), core_src="raise RuntimeError('core boom')\n")
p, _ = fb(ws, "UserPromptSubmit", {})
check("fallback: a core that raises at import also falls back", p.returncode == 0 and "RuntimeError('core boom')" in log_text(), log_text()[-200:])
ws = mkws(False, scripts(), core_src="import sys\nsys.exit(7)\n")
p, _ = fb(ws, "UserPromptSubmit", {})
check("a SystemExit from the core import falls back to the legacy scripts too (G11 round 10: it must not end the hook with the exit code of the import)", p.returncode == 0 and "SystemExit" in log_text(), (p.returncode, log_text()[-200:]))
ws = mkws(False, scripts(), core_src="def main(argv):\n    raise KeyError('in main')\n")
p, _ = fb(ws, "UserPromptSubmit", {})
check("a core main that raises is fail-open (exit 0, scripts not double-run)", p.returncode == 0 and marks() == [], marks())

# mode switch end to end with the real core
live = {"guard-hook": "cat >/dev/null; printf 'from legacy\\n'"}
for mode_value, expect_legacy in (("legacy", True), ("shadow", True), ("v1", False), (None, True)):
    cfg(mode_value)
    ws = mkws(True, scripts(**live))
    (TMP / "state" / "flow-errors.log").write_text("")
    p, _ = fb(ws, "UserPromptSubmit", {"prompt": "x"}, env_extra={"SHIPMIRACLE_HOOK_NO_LOAD": "1"})
    check("mode %s: %s" % (mode_value or "unset", "legacy scripts run through the dispatcher" if expect_legacy else "v1 does not run the legacy scripts"),
          (p.stdout == b"from legacy\n" and "keep-awake" in marks()) if expect_legacy else (p.stdout == b"" and marks() == []), (p.stdout, marks()))
    check("mode %s: no fallback error is logged (it is a mode, not a failure)" % (mode_value or "unset"), "core import failed" not in log_text())
cfg("v1")

# ---------------------------------------------------------------- 14 import budget and latency
budget = ("import sys, os\nsys.path.insert(0, %r)\nfrom shipmiracle.hooks import core\ncore.run('PreToolUse', b'{\"tool_name\": \"Bash\"}')\n"
          "heavy = [m for m in ('tempfile', 'subprocess', 'shlex', 'difflib', 'typing', 'dataclasses', 'inspect', 'hashlib', 'unicodedata', 'pathlib', 'shipmiracle.state', 'shipmiracle.events', 'shipmiracle.config', 'traceback') if m in sys.modules]\n"
          "print(','.join(heavy))\n" % str(ROOT))
p = subprocess.run([PY, "-I", "-S", "-c", budget], env=dict(os.environ, SHIPMIRACLE_HOOK_NO_LOAD="1"), capture_output=True, text=True)
check("import budget: an empty pipeline run imports none of tempfile/subprocess/shlex/difflib/typing/dataclasses/inspect/pathlib/shipmiracle.state/events/config",
      p.returncode == 0 and p.stdout.strip() == "", (p.stdout, p.stderr[-300:]))
imp = subprocess.run([PY, "-I", "-S", "-X", "importtime", "-c", "import sys; sys.path.insert(0, %r); from shipmiracle.hooks import core" % str(ROOT)], capture_output=True, text=True).stderr
rows = []
for l in imp.splitlines():
    mm = re.match(r"import time:\s+(\d+) \|\s+(\d+) \| (\s*)(\S+)", l)
    if mm:
        rows.append((int(mm.group(2)), mm.group(4)))
print("INFO importtime (cumulative us), top 6:", sorted(rows, reverse=True)[:6])
check("importtime: core's imports are only os/json/re/time-level modules plus shipmiracle.hooks", not any(n in ("tempfile", "subprocess", "typing", "dataclasses", "inspect") for _, n in rows), [n for _, n in rows][-20:])

pyc = TMP / "pyc2"; pyc.mkdir()
cmd_env = dict(os.environ, SHIPMIRACLE_HOOK_NO_LOAD="1")
payload_pre = b'{"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"ls"},"session_id":"s","cwd":"/tmp"}'
def one():
    subprocess.run([PY, "-I", "-S", "-X", "pycache_prefix=" + str(pyc), str(HOOK), "PreToolUse"], input=payload_pre, env=cmd_env, capture_output=True)
one()                                                                       # warm the bytecode cache (the first call compiles)
samples = []
def measure():
    xs = [T.timed(one) for _ in range(30)]; samples.append(xs); return T.p95(xs)
ok, rep, best = T.robust(measure, lambda: T.spawn_ref(15, T.p95, [PY, "-I", "-S", "-c", "pass"]), 0.045, 2.0)
xs = sorted(samples[-1])
print("INFO empty-pipeline PreToolUse via the shim: p50 %.1f ms, p95 %.1f ms, best p95 %.1f ms (%s)" % (xs[len(xs) // 2] * 1000, T.p95(xs) * 1000, best * 1000, rep))
check("empty-pipeline run p95 < 45 ms (or 2 x the bare python start on a busy Mac)", ok, rep)

# ---------------------------------------------------------------- done
print("\nFAILED: %d" % fails if fails else "\nALL PASS")
shutil.rmtree(TMP, ignore_errors=True)
sys.exit(1 if fails else 0)
