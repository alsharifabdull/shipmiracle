"""Launcher behind v1_hook.sh. Reads the hook input from stdin, takes the event from it (the production command passes it as an argument),
runs ONLY the flow slot of that event's pipeline through shipmiracle.hooks.core.run (the other modules have their own suites and side effects: caffeinate,
user-active files) and relays stdout, stderr and the exit code like the hook process does. Always the v1 path: the config switch hooks.dispatcher
is not consulted here (core.main would return "legacy" for a suite whose SHIPMIRACLE_CONFIG holds other settings); hooks_core_test covers the switch."""
import json, os, sys

WS = os.path.realpath(os.path.join(os.path.dirname(os.path.realpath(__file__)), "../../../.."))
sys.path.insert(0, WS)
raw = sys.stdin.buffer.read()
try:
    d = json.loads(raw.decode("utf-8", "replace")) if raw.strip() else {}
    event = d.get("hook_event_name") if isinstance(d, dict) and isinstance(d.get("hook_event_name"), str) else ""
except ValueError:
    event = ""
if not event:       # no event name in the input: the gate still handles it (and ignores it); route through a pipeline that has the flow slot for every tool
    event = "UserPromptSubmit"
rec = os.environ.get("SHIPMIRACLE_V1_RECORD")       # tests/hooks_parity_test.py: one JSON line per call (project dir + raw input) for the differential replay
if rec and os.environ.get("SHIPMIRACLE_TEST") == "1":
    try:
        fd = os.open(rec, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        os.write(fd, (json.dumps({"p": os.environ.get("CLAUDE_PROJECT_DIR", ""), "raw": raw.decode("utf-8", "replace")}) + "\n").encode("utf-8"))
        os.close(fd)
    except OSError:
        pass
from shipmiracle.hooks import core  # noqa: E402
core.PIPELINES[event] = [s for s in core.PIPELINES.get(event, []) if s.name == "flow"]
out, err, code = core.run(event, raw)
sys.stdout.buffer.write(out); sys.stdout.buffer.flush()
sys.stderr.buffer.write(err); sys.stderr.buffer.flush()
sys.exit(code)
