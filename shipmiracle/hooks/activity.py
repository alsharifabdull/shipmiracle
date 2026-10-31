"""Global activity hooks (spec docs/plans/2026-10-20-p4-spec.md 2.2): keep_awake and guard_hook, ported from legacy keep-awake.sh and legacy guard-hook.sh
with identical decisions, texts and state effects. Registered for UserPromptSubmit and every PreToolUse call. SHIPMIRACLE_QUIET is handled by core.
Import budget: os, json, re, time only; subprocess is imported where it is used."""
from __future__ import annotations

import json
import os
import re
import time

from . import core
from . import io as hio

PID_NAME = "shipmiracle-keep-awake.pid"
THROTTLE_SECS = 60
BATTERY_MSG = ("BATTERY LOW (unplugged, 25% or less). The Mac will be put to sleep at 15%. Finish the current step only, then: update docs/STATUS.md "
               "(what changed, verification, what is next, how to resume), commit and push, and stop. Do not start new work.")


def shell_basename(p: str) -> str:
    """`basename` of the shell: trailing slashes dropped, "/" stays "/"."""
    s = p.rstrip("/")
    if not s:
        return "/" if p else ""
    return s.rsplit("/", 1)[-1]


def project_dir(env) -> str:
    """${CLAUDE_PROJECT_DIR:-$PWD}"""
    return env.get("CLAUDE_PROJECT_DIR") or os.getcwd()


def pidfile_path(env) -> str:
    return os.path.join(env.get("TMPDIR") or "/tmp", PID_NAME)       # ${TMPDIR:-/tmp}


def read_pid(path: str) -> str:
    try:
        with open(path, "r", errors="ignore") as f:
            return f.read().rstrip("\n")
    except OSError:
        return ""


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


def kill_old(old: str) -> None:
    """`kill "$old"`: a positive pid only (the shell would also signal a process group for 0 or a negative number: never wanted)."""
    try:
        pid = int(old.strip())
    except ValueError:
        return
    if pid > 1:
        try:
            os.kill(pid, 15)
        except OSError:
            pass


def spawn_caffeinate(args, pidfile: str) -> bool:
    """caffeinate detached (own session, no stdio), pid recorded in `pidfile`. False when the program is missing or this system has none
    (macOS: exactly `caffeinate <args>`; Linux: systemd-inhibit, see shipmiracle.platform)."""
    import subprocess
    from .. import platform as aplat
    argv = aplat.keep_awake_argv_from_caffeinate(args)
    if argv is None:
        return False
    try:
        p = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True, close_fds=True)
    except OSError:
        return False
    try:
        fd = os.open(pidfile, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write("%d\n" % p.pid)
    except OSError:
        pass
    return True


def keep_awake(ctx):
    if ctx.config("prefs.keep_awake", True) is False:               # the owner answered No in `shipm init` (unset = on, as before)
        return None
    pidfile = pidfile_path(ctx.env)
    old = read_pid(pidfile)
    if core.on(ctx.config("hooks.awake_throttle", False)):          # owner decision O2 (default off = respawn on every call, as the old script)
        try:
            if time.time() - os.path.getmtime(pidfile) < THROTTLE_SECS and old.strip().isdigit() and pid_alive(int(old.strip())):
                return None
        except OSError:
            pass
    if old:
        kill_old(old)
    ok = spawn_caffeinate(["-i", "-t", "600"], pidfile)
    return core.Result(effects=["caffeinate -i -t 600"] if ok else [])


def _mode_file(ctx, d, ev) -> None:
    """The panel's <project>.mode.json (only real projects directly under ~/Developer)."""
    pd = os.path.realpath(ctx.env.get("CLAUDE_PROJECT_DIR") or d.get("cwd") or "/")
    proj = os.path.basename(pd) if os.path.dirname(pd) == ctx.dev else ""
    if proj and d.get("permission_mode"):
        hio.atomic_json(os.path.join(ctx.state, proj + ".mode.json"),
                        {"mode": d.get("permission_mode"), "tool": d.get("tool_name", ""), "event": ev, "ts": int(time.time())})


def guard_hook(ctx):
    state = ctx.state
    hio.ensure_dir(state)
    d = ctx.data
    ev = d.get("hook_event_name", "")                      # the JSON field, like the old script (a missing name = no owner-active touch)
    try:
        _mode_file(ctx, d, ev)
    except Exception:                                      # the old inline python died here and printed nothing: the event is unknown
        ev = ""
    if ev == "UserPromptSubmit":
        try:
            fd = os.open(os.path.join(state, "user-active"), os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            try:
                os.utime(fd, None)                             # the opened file, never a path; a symlink at the path is refused
            finally:
                os.close(fd)
        except OSError:
            pass
    flag = os.path.join(state, "handoff-now")
    if not os.path.isfile(flag):
        return None
    proj = shell_basename(project_dir(ctx.env))
    mark = "%s/handoff-told.%s" % (state, proj)
    if os.path.isfile(mark) and not (os.path.getmtime(flag) > os.path.getmtime(mark)):
        return None
    try:
        fd = os.open(mark, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            os.utime(fd, None)
        finally:
            os.close(fd)
    except OSError:
        pass
    if ev == "PreToolUse":
        return core.Result(additional_context=BATTERY_MSG)
    return core.Result(plain_stdout=BATTERY_MSG + "\n")


core.register("UserPromptSubmit", "keep_awake", None, keep_awake)
core.register("PreToolUse", "keep_awake", None, keep_awake)
core.register("UserPromptSubmit", "guard_hook", None, guard_hook)
core.register("PreToolUse", "guard_hook", None, guard_hook)
