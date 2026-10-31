"""plan_capture (spec 2.2, StatusLine): ported from legacy plan-capture.sh. Claude Code hands the status-line command, after each reply, the live plan usage
(rate_limits.five_hour / seven_day) -> state/plan.json, and the model of this session -> state/<project>.model.json (real projects only), for the panel
and for plan_approval's non-Opus warning. Prints nothing (so no status line is shown). Reads no credentials. Import budget: os, json, re, time only."""
from __future__ import annotations

import json
import os
import time

from . import core
from . import io as hio


def plan_capture(ctx):
    d = ctx.data
    if not ctx.raw.strip():
        return None
    try:
        parsed = json.loads(ctx.raw.decode("utf-8", "replace"))
    except ValueError:
        return None
    hio.ensure_dir(ctx.state)                         # the old script created the folder as soon as the input parsed (any JSON)
    if not isinstance(parsed, dict) or not d:
        return None
    try:
        m = d.get("model") or {}
        ws = d.get("workspace") or {}
        pd = os.path.realpath(ws.get("project_dir") or ws.get("current_dir") or d.get("cwd") or "/")
        proj = os.path.basename(pd) if os.path.dirname(pd) == ctx.dev else ""        # real projects only
        if proj and (m.get("id") or m.get("display_name")):
            hio.atomic_json(os.path.join(ctx.state, proj + ".model.json"),
                            {"model": m.get("display_name") or m.get("id"), "id": m.get("id", ""), "session": d.get("session_id", ""), "ts": int(time.time())})
        rl = d.get("rate_limits")
        if rl:
            hio.atomic_json(os.path.join(ctx.state, "plan.json"), {"at": int(time.time()), "rate_limits": rl, "model": m.get("display_name", "")})
    except (AttributeError, TypeError, ValueError):    # a model/workspace field of an unexpected shape: the old inline python died silently
        return None
    return core.Result(effects=["write plan.json / model.json"])


core.register("StatusLine", "plan_capture", None, plan_capture)
