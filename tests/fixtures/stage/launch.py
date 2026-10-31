"""Launcher behind hook.sh. Runs ONLY the flow slot and the stage slot of the event's pipeline (flow first, like the dispatcher table), each through the
dispatcher's own steps (eligible / permitted / run_module). Output modes (env SHIPMIRACLE_STAGE_SHIM):
  flow    (default) what the suite sees is flow's result ALONE; the stage result is only recorded. A flow suite then proves two things: flow's decisions are
          byte-identical with the stage module running next to it (it cannot disturb flow's state or files), and the stage module never crashes on those inputs.
  merged  the real merged output of both (flow + stage), as the dispatcher prints it.
SHIPMIRACLE_STAGE_RECORD=<file>: one JSON line per call {event, tool, flow:{block,reason}, stage:{block,reason,ctx,sys}} (tests only, SHIPMIRACLE_TEST=1).
SHIPMIRACLE_STAGE_ENGINE=legacy|shadow|playbook (tests only) forces the stage engine (flow's gate.engine integrity item is not touched).
SHIPMIRACLE_STAGE_FORCE=1 (tests only): every project counts as having the software playbook (defaults, guided, trusted) so the engine runs under the flow suites."""
import json, os, sys

WS = os.path.realpath(os.path.join(os.path.dirname(os.path.realpath(__file__)), "../../.."))
sys.path.insert(0, WS)
raw = sys.stdin.buffer.read()
try:
    d = json.loads(raw.decode("utf-8", "replace")) if raw.strip() else {}
    event = d.get("hook_event_name") if isinstance(d, dict) and isinstance(d.get("hook_event_name"), str) else ""
except ValueError:
    d, event = {}, ""
if not event:
    event = "UserPromptSubmit"
from shipmiracle.hooks import core  # noqa: E402

test = os.environ.get("SHIPMIRACLE_TEST") == "1"
ctx = core.Ctx(raw, event)
results = {}
for slot in [s for s in core.PIPELINES.get(event, []) if s.name in ("flow", "stage")]:
    if not core.eligible(ctx, slot):
        continue
    if slot.fn is None:
        core._load(slot, event)
    if slot.fn is None:
        continue
    if slot.name == "stage" and test and os.environ.get("SHIPMIRACLE_STAGE_ENGINE"):      # the engine of this run, invisible to flow's integrity snapshot
        from shipmiracle.hooks import stage as S
        S._engine = lambda c, v=os.environ["SHIPMIRACLE_STAGE_ENGINE"]: v
    if slot.name == "stage" and test and os.environ.get("SHIPMIRACLE_STAGE_FORCE") == "1":
        from shipmiracle.hooks import stage as S
        from shipmiracle.playbook import config, gate
        S._has_playbook = lambda c, pid: True
        gate.stage_rules = lambda pd: gate.build_rules(pd, config.defaults(), config.TRUSTED, "forced", gate.flow_level(pd))
    if not core.permitted(ctx, slot):
        continue
    results[slot.name] = core.run_module(ctx, slot)
mode = os.environ.get("SHIPMIRACLE_STAGE_SHIM") or "flow"
visible = [results.get("flow")] + ([results.get("stage")] if mode == "merged" else [])
out, err, code = core.merge(event, visible)
rec = os.environ.get("SHIPMIRACLE_STAGE_RECORD")
if rec and test:
    def brief(r):
        return None if r is None else {"block": r.block, "reason": r.reason[:300], "ctx": r.additional_context[:300], "sys": r.system_message[:300]}
    try:
        fd = os.open(rec, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        os.write(fd, (json.dumps({"event": event, "tool": ctx.tool_name, "flow": brief(results.get("flow")), "stage": brief(results.get("stage"))}) + "\n").encode("utf-8"))
        os.close(fd)
    except OSError:
        pass
sys.stdout.buffer.write(out); sys.stdout.buffer.flush()
sys.stderr.buffer.write(err); sys.stderr.buffer.flush()
sys.exit(code)
