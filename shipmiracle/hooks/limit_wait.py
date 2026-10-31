"""limit_wait (spec 2.2, StopFailure): ported from legacy limit-wait.sh. When a turn ends because the plan's usage limit was reached, keep the Mac awake
until the reset time ("resets 4:20pm" in the message; 5 hours when it is not stated) plus 15 minutes, record it for the panel in
state/<project>.limit.json and in <workspace>/reports/limit-wait.log. Claude Code ignores the output of this event. Import budget: os, json, re, time only."""
from __future__ import annotations

import json
import os
import re
import time

from . import core
from . import io as hio

RESET = re.compile(r"resets\s+(\d{1,2})(?::(\d{2}))?\s*([ap]m)", re.I)


def seconds_to_wait(d) -> int:
    """Seconds to stay awake, 0 = not a limit message. Raises on a reset time that is not a real clock time (the old script printed nothing then)."""
    err = str(d.get("error", ""))
    msg = " ".join(str(d.get(k, "")) for k in ("last_assistant_message", "error_details"))
    if "rate_limit" not in err and not re.search(r"limit", msg, re.I):
        return 0
    m = RESET.search(msg)
    if not m:
        return 5 * 3600
    import datetime
    h, mi, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3).lower()
    h = (h % 12) + (12 if ap == "pm" else 0)
    now = datetime.datetime.now()
    t = now.replace(hour=h, minute=mi, second=0, microsecond=0)
    if t <= now:
        t += datetime.timedelta(days=1)
    return int((t - now).total_seconds()) + 900


def _shell_basename(p: str) -> str:
    s = p.rstrip("/")
    return s.rsplit("/", 1)[-1] if s else ("/" if p else "")


def limit_wait(ctx):
    if not ctx.raw.strip():
        return None
    try:
        if not isinstance(json.loads(ctx.raw.decode("utf-8", "replace")), dict):
            return None
        secs = seconds_to_wait(ctx.data)
    except ValueError:                                  # malformed JSON, or a reset time that is not a clock time: the old script did nothing
        return None
    if secs <= 0:
        return None
    from .activity import kill_old, pidfile_path, read_pid, spawn_caffeinate
    proj = _shell_basename(ctx.env.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    now = int(time.time())
    try:
        hio.atomic_json(os.path.join(ctx.state, proj + ".limit.json"), {"until": now + secs - 900, "ts": now})
    except OSError as e:
        hio.log_err("limit_wait", e)
    pidfile = os.path.join(ctx.env.get("TMPDIR") or "/tmp", "shipmiracle-limit-wait.pid")
    old = read_pid(pidfile)
    if old:
        kill_old(old)
    ok = False if ctx.config("prefs.keep_awake", True) is False else spawn_caffeinate(["-i", "-t", str(secs)], pidfile)     # prefs.keep_awake = No: the limit note is still written, nothing is kept awake
    logdir = os.path.join(ctx.ws, "reports")
    if os.path.isdir(logdir):                           # the old script never created the folder: a missing one just skips the log line
        try:
            hio.append_line(os.path.join(logdir, "limit-wait.log"),
                            "%s limit hit; Mac kept awake for %d min until the reset" % (time.strftime("%Y-%m-%d %H:%M"), secs // 60))
        except OSError:
            pass
    return core.Result(effects=["caffeinate -i -t %d" % secs] if ok else [])


core.register("StopFailure", "limit_wait", None, limit_wait)
