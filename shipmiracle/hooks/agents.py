"""agent_cap and agent_state (spec 2.2): ported from legacy agent-cap.sh and legacy agent-state.sh with identical decisions, texts and state files.
agent_cap (PreToolUse Agent|Task): deny when agents.paused exists, or when the project (default 4, SHIPMIRACLE_AGENT_CAP) or all projects (default 8, SHIPMIRACLE_AGENT_CAP_TOTAL)
already run that many agents; counts come from <state>/<project>.agents.json (entries older than 3 h ignored). Any problem while counting = allow, as before.
agent_state (SubagentStart / SubagentStop): maintains <state>/<project>.agents.json {agent_id: {type, model, started}} under an flock.
Import budget: os, json, re, time only; glob and fcntl are imported where used."""
from __future__ import annotations

import json
import os
import re
import time

from . import core
from . import io as hio

STALE = 3 * 3600
SHAPE = (AttributeError, TypeError, KeyError, ValueError)     # a state file or input of an unexpected shape (OS errors propagate to core's wrapper)


def _project_dir(env) -> str:
    return env.get("CLAUDE_PROJECT_DIR") or os.getcwd()          # ${CLAUDE_PROJECT_DIR:-$PWD}


def agent_cap(ctx):
    state = ctx.state
    try:
        cap_project, cap_total = int(ctx.env.get("SHIPMIRACLE_AGENT_CAP", "4")), int(ctx.env.get("SHIPMIRACLE_AGENT_CAP_TOTAL", "8"))
    except ValueError:
        return None                                               # the old inline python died here (errors hidden): allow
    if os.path.exists(os.path.join(state, "agents.paused")):
        return core.Result(block=True, reason="New agents are paused (Health tab -> Resume new agents) because the Mac is busy. Do the work yourself or wait.")
    import glob
    try:
        now = time.time()
        mine = os.path.basename(os.path.realpath(_project_dir(ctx.env)))
        per = total = 0
        for f in glob.glob(os.path.join(state, "*.agents.json")):
            try:
                with open(f) as fh:
                    cur = json.load(fh)
            except Exception:
                continue
            n = sum(1 for v in cur.values() if now - v.get("started", now) < STALE)
            total += n
            if os.path.basename(f) == mine + ".agents.json":
                per = n
    except SHAPE:
        return None
    if per >= cap_project:
        return core.Result(block=True, reason="%d agents are already running in this project (limit %d). Wait for some to finish before starting more." % (per, cap_project))
    if total >= cap_total:
        return core.Result(block=True, reason="%d agents are running across all projects (limit %d). Wait for some to finish before starting more." % (total, cap_total))
    return None


def _path_name(d: str) -> str:
    """pathlib.Path(d).name without importing pathlib."""
    parts = [p for p in d.split("/") if p not in ("", ".")]
    return parts[-1] if parts else ""


def _model_of(path: str) -> str:
    with open(path, errors="ignore") as f:
        m = re.search(r"^model:\s*(\S+)", f.read(), re.M)
    return m.group(1) if m else ""


def agent_state(ctx):
    state = ctx.state
    try:
        hio.ensure_dir(state)                                      # the old script made the folder before it looked at the input
    except OSError:
        return None
    ev = ctx.data
    if not ev:                                                     # {} is valid input (the old script still rewrote the file); other empties are not
        try:
            if not isinstance(json.loads(ctx.raw.decode("utf-8", "replace")), dict):
                return None
        except ValueError:
            return None
    d = _project_dir(ctx.env)
    f = os.path.join(state, _path_name(d) + ".agents.json")
    import fcntl
    try:
        lk = hio.open_lock(f + ".lock", state)          # several agents can start in the same second; a symlinked lock file is refused
    except OSError as e:
        hio.log_err("agent_state", e)
        return None
    try:
        fcntl.flock(lk, fcntl.LOCK_EX)
        try:
            with open(f) as fh:
                cur = json.loads(fh.read())
        except Exception:
            cur = {}
        now = int(time.time())
        cur = {k: v for k, v in cur.items() if now - v.get("started", now) < STALE}      # drop anything stuck > 3 h
        aid = str(ev.get("agent_id") or ev.get("subagent_id") or ev.get("tool_use_id") or "")
        typ = ev.get("agent_type") or ev.get("subagent_type") or "agent"
        kind = ev.get("hook_event_name", "")
        if kind == "SubagentStart" and aid:
            model = ""
            home = os.path.expanduser("~")
            for af in (os.path.join(d, ".claude/agents", "%s.md" % (typ,)), os.path.join(home, ".claude/agents", "%s.md" % (typ,))):
                if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", str(typ)) and os.path.isfile(af):      # project file first, then the user-level one
                    model = _model_of(af)
                    break
            cur[aid] = {"type": typ, "model": model, "started": now}
        elif kind == "SubagentStop":
            cur.pop(aid, None)
            if not aid:                                            # no id given: drop the oldest of that type
                for k in sorted(cur, key=lambda k: cur[k]["started"]):
                    if cur[k]["type"] == typ:
                        cur.pop(k)
                        break
        hio.atomic_json(f, cur)
    except SHAPE:
        return None                                                # unexpected JSON shapes: the old inline python died silently, nothing written
    finally:
        lk.close()
    return core.Result(effects=["write " + f])


core.register("PreToolUse", "agent_cap", None, agent_cap)
core.register("SubagentStart", "agent_state", None, agent_state)
core.register("SubagentStop", "agent_state", None, agent_state)
