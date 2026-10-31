#!/usr/bin/env python3
"""gate_failclosed_test: checklist G11 (round 10), the gate fails CLOSED. At strict, a PreToolUse for Bash and the file tools gets exactly ONE valid JSON deny
when the gate crashes, exits oddly, prints garbage, is interrupted or hangs, in the legacy script and in the v1 dispatcher. warn / off and every other event stay silent.
Drills are injected by SHIPMIRACLE_GATE_DRILL (honoured only under SHIPMIRACLE_TEST=1).
Run: python3 tests/gate_failclosed_test.py"""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import shipmiracle_isolation; shipmiracle_isolation.apply_to_environ()   # test isolation
import json, os, pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import isolation_fixture as X

fails = []


def check(name, ok, info=""):
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(info)[:500]))
    if not ok:
        fails.append(name)


w = X.World()
IMPL_NAMES = [n for n, _h in X.IMPLS]
P = str(w.P)
TOOLS = {"Bash": {"command": "ls"}, "Read": {"file_path": P + "/src/mine.py"}, "Grep": {"pattern": "x", "path": P + "/src"}, "Glob": {"pattern": "*.py"}, "LS": {"path": P},
         "Edit": {"file_path": P + "/src/mine.py", "old_string": "a", "new_string": "b"}, "Write": {"file_path": P + "/n.txt", "content": "x"}}


V1_MAIN = """
import sys
sys.path.insert(0, %r)
from shipmiracle.hooks import core
core.mode = lambda: "v1"
core.PIPELINES[%r] = [s for s in core.PIPELINES.get(%r, []) if s.name == "flow"]
sys.exit(core.main([%r]) or 0)
"""


def call(impl, ev, tool, ti, level, drill, wd="1"):
    d = {"hook_event_name": ev, "session_id": "fc", "cwd": P}
    if tool:
        d.update({"tool_name": tool, "tool_input": ti})
    e = dict(w.env, SHIPMIRACLE_ISOLATION=level, SHIPMIRACLE_GATE_OUTER_WD=wd)
    if drill:
        e["SHIPMIRACLE_GATE_DRILL"] = drill
    if impl == "v1":                                                  # the real dispatcher entry (core.main with the v1 switch), flow slot only
        cmd = [sys.executable, "-I", "-c", V1_MAIN % (str(ROOT), ev, ev, ev)]
    else:
        cmd = ["bash", dict(X.IMPLS)[impl]]
    return subprocess.run(cmd, input=json.dumps(d), capture_output=True, text=True, env=e, cwd=P, timeout=60)


def one_deny(r):
    """stdout is exactly one JSON object and it is a PreToolUse deny"""
    try:
        o = json.loads(r.stdout)
    except ValueError:
        return False
    return isinstance(o, dict) and (o.get("hookSpecificOutput") or {}).get("permissionDecision") == "deny"


def silent(r):
    return r.returncode == 0 and (not r.stdout.strip() or '"deny"' not in r.stdout)


KINDS = ("raise", "exit1", "exit2", "interrupt", "garbage", "garbage2", "twojson", "hang")
for impl in IMPL_NAMES:
    for kind in KINDS:
        bad = []
        for tool, ti in TOOLS.items():
            r = call(impl, "PreToolUse", tool, ti, "strict", kind)
            if not one_deny(r):
                bad.append((tool, r.returncode, r.stdout[:120], r.stderr[-120:]))
        check("%s strict, drill %s: Bash, Read, Grep, Glob, LS, Edit, Write each get exactly one valid JSON deny" % (impl, kind), not bad, bad)
        for level in (("warn", "off") if kind != "hang" and not (kind == "exit2" and impl == "v1") else ()):   # v1 has always read exit 2 as a block (stderr = reason)      # a hang at warn / off has no watchdog by design (the owner chose not to enforce)
            bad = []
            for tool, ti in TOOLS.items():
                r = call(impl, "PreToolUse", tool, ti, level, kind)
                if not silent(r):
                    bad.append((tool, r.returncode, r.stdout[:120]))
            check("%s %s, drill %s: no refusal (a crash stays a logged non-event)" % (impl, level, kind), not bad, bad)
    for kind in ("raise", "exit1", "interrupt", "garbage"):
        bad = []
        for ev in ("UserPromptSubmit", "Stop", "PostToolUse"):
            tool = "Bash" if ev == "PostToolUse" else ""
            r = call(impl, ev, tool, TOOLS["Bash"], "strict", kind)
            if '"deny"' in r.stdout or '"block"' in r.stdout:
                bad.append((ev, r.stdout[:120]))
        check("%s strict, drill %s: UserPromptSubmit / Stop / PostToolUse are not refused" % (impl, kind), not bad, bad)
    r = call(impl, "PreToolUse", "Bash", TOOLS["Bash"], "strict", "")
    check("%s control: no drill, a plain `ls` is allowed with no output" % impl, r.returncode == 0 and not one_deny(r), (r.returncode, r.stdout[:150]))
    r = call(impl, "PreToolUse", "WebFetch", {"url": "https://example.invalid"}, "strict", "raise")
    check("%s a tool that never goes through isolation (WebFetch) is not refused by a crash" % impl, not one_deny(r), r.stdout[:150])

# "killed by a signal" and "exit 139": simulated with SIGKILL and os._exit(139). NEVER a real SIGSEGV/SIGABRT in a test: the macOS crash reporter shows a dialog each time.
# A real segfault of the v1 dispatcher cannot be answered from inside the dying process: ACCEPTED LIMIT, documented, deliberately not executed here.
for impl in IMPL_NAMES:
    for kind in ("kill", "exit139"):
        r = call(impl, "PreToolUse", "Bash", TOOLS["Bash"], "strict", kind)
        if impl == "legacy":
            check("legacy strict, gate %s: the wrapper answers with exactly one deny" % kind, one_deny(r), (r.returncode, r.stdout[:150]))
        elif kind == "exit139":
            check("v1 strict, exit 139 of the dispatcher process: ACCEPTED LIMIT (an exiting process cannot be judged from outside here; Claude Code sees a non-zero exit) - pinned", not one_deny(r), (r.returncode, r.stdout[:150]))
        else:
            check("v1 strict, dispatcher killed by SIGKILL: ACCEPTED LIMIT - pinned", not one_deny(r) and r.returncode != 0, (r.returncode, r.stdout[:150]))

# in-process: SystemExit / KeyboardInterrupt from a slot or from the load path are crashes (refused at strict for the flow module)
os.environ.update({k: v for k, v in w.env.items() if k.startswith("SHIPMIRACLE_") or k == "CLAUDE_PROJECT_DIR"})
import importlib
core = importlib.import_module("shipmiracle.hooks.core")
core_flow = importlib.import_module("shipmiracle.hooks.flow")
RAW = json.dumps({"hook_event_name": "PreToolUse", "session_id": "ip", "cwd": P, "tool_name": "Bash", "tool_input": {"command": "ls"}}).encode()
slot = [s for s in core.PIPELINES["PreToolUse"] if s.name == "flow"][0]
saved = slot.fn
os.environ["SHIPMIRACLE_ISOLATION"] = "strict"
for exc in (SystemExit(0), SystemExit(3), KeyboardInterrupt()):
    def boom(ctx, exc=exc):
        raise exc
    slot.fn = boom
    try:
        out_, err_, code_ = core.run("PreToolUse", RAW, env=dict(os.environ))
    finally:
        slot.fn = saved
    check("in-process: %r raised by the flow slot is a crash: one deny at strict" % (exc,), out_.count(b'"permissionDecision"') == 1 and b'"deny"' in out_, out_[:150])
os.environ["SHIPMIRACLE_ISOLATION"] = "warn"
slot.fn = lambda ctx: (_ for _ in ()).throw(SystemExit(0))
try:
    out_, err_, code_ = core.run("PreToolUse", RAW, env=dict(os.environ))
finally:
    slot.fn = saved
check("in-process: the same at warn is silent", b'"deny"' not in out_, out_[:150])
core._LOAD_FAILED.discard("flow")
os.environ["SHIPMIRACLE_ISOLATION"] = "strict"
real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__
slot.fn = None
def bad_import(name, *a, **k):
    if name == "shipmiracle.hooks.flow":
        raise SystemExit(0)
    return real_import(name, *a, **k)
import builtins
builtins.__import__ = bad_import
try:
    core._LOAD_FAILED.discard("flow")
    out_, err_, code_ = core.run("PreToolUse", RAW, env=dict(os.environ))
finally:
    builtins.__import__ = real_import; slot.fn = saved; core._LOAD_FAILED.discard("flow")
check("in-process: SystemExit while loading the flow module is a crash: one deny at strict", b'"deny"' in out_, out_[:150])
os.environ.pop("SHIPMIRACLE_ISOLATION", None)

w.cleanup()
print("\ngate fail-closed tests: %d failed" % len(fails))
sys.exit(1 if fails else 0)
