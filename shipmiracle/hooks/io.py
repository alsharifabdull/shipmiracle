"""Hook file helpers (stdlib only, imports kept minimal: this runs on every hook call).
State resolution is the one flow-gate uses: SHIPMIRACLE_STATE when set (the gate logs that override itself), else ~/.local/state/shipmiracle."""
from __future__ import annotations

import json
import os
import time


# Prompt prefixes that mark a subagent hand-back or system text, never the owner (flow keeps its own literal copy, kept equal by flow_source_sync_test).
HANDBACK_HEADS = ("<agent-message", "<task-notification", "<teammate-message", "<system-reminder", "[subagent hand-back]")
# Prefix the panel puts on text it types for the owner (commands, buttons): such a prompt is never the owner's approval of a plan (M3).
PANEL_MARK = "[panel] "
_ENVELOPE = None


def panel_or_slash(prompt) -> bool:
    """True for text the panel typed (PANEL_MARK) and for slash commands: never the owner's own words for approvals, holds, bypass or baselines (M3, re-review)."""
    return isinstance(prompt, str) and prompt.lstrip().lower().startswith(("/", PANEL_MARK))


def handback(prompt) -> bool:
    """True when a prompt is a subagent hand-back or system envelope, never the owner. Leading invisible characters (zero-width, BOM, controls, spaces)
    are skipped and '_' counts as '-' (`<task_notification>` is `<task-notification>`); any envelope-like tag early in the prompt counts too (M1)."""
    global _ENVELOPE
    if not isinstance(prompt, str):
        return True
    import unicodedata
    i = 0
    while i < len(prompt) and i < 200 and (prompt[i].isspace() or unicodedata.category(prompt[i]) in ("Cf", "Cc", "Zs", "Zl", "Zp")):
        i += 1
    p = prompt[i:i + 400].lower().replace("_", "-")
    if p.startswith(HANDBACK_HEADS) or "<agent-message from=" in p[:200]:
        return True
    if _ENVELOPE is None:
        import re
        _ENVELOPE = re.compile(r"<\s*/?\s*[a-z][a-z-]*(?:message|notification|reminder)\b")
    return bool(_ENVELOPE.search(p[:200]))


_STATE_OVERRIDE = None          # in-process only (the shadow child); never read from the environment


def _temp_ok(v) -> bool:
    try:
        r = os.path.realpath(v)
        roots = {os.path.realpath(x) for x in ("/tmp", "/private/tmp", "/var/folders", "/private/var/folders")}
        return any(r == t or r.startswith(t.rstrip("/") + "/") for t in roots)
    except Exception:
        return False


def sandboxed() -> bool:
    """SHIPMIRACLE_TEST=1 AND config, state, workspace, dev folders and HOME all set inside the system temp folder (same rule as shipmiracle.paths.sandboxed, no import)."""
    if os.environ.get("SHIPMIRACLE_TEST") != "1":
        return False
    for var in ("SHIPMIRACLE_CONFIG", "SHIPMIRACLE_STATE", "SHIPMIRACLE_WS", "SHIPMIRACLE_DEV", "HOME"):
        v = os.environ.get(var)
        if not v or not _temp_ok(v):
            return False
    return True


def state_dir() -> str:
    """The state folder. SHIPMIRACLE_STATE is honoured only in a complete temp sandbox under SHIPMIRACLE_TEST=1 (M4: a nested claude inherits the environment and could
    point the hooks at an empty folder, where no run exists); otherwise ~/.local/state/shipmiracle."""
    if _STATE_OVERRIDE:
        return _STATE_OVERRIDE
    v = os.environ.get("SHIPMIRACLE_STATE")
    if v and sandboxed():
        return v
    return os.path.join(os.path.expanduser("~"), ".local/state/shipmiracle")


def ensure_dir(path: str) -> None:
    """mkdir -p with mode 0700 for every folder it creates (os.makedirs applies the mode to the leaf only)."""
    missing = []
    p = os.path.abspath(path)
    while p and not os.path.isdir(p):
        missing.append(p)
        parent = os.path.dirname(p)
        if parent == p:
            break
        p = parent
    for d in reversed(missing):
        try:
            os.mkdir(d, 0o700)
        except FileExistsError:
            pass


def atomic_json(path: str, obj, mode: int = 0o600) -> None:
    """Write JSON to path: pid-suffixed temp file in the same folder, fsync, replace. Raises on failure (callers decide)."""
    ensure_dir(os.path.dirname(os.path.abspath(path)))
    tmp = "%s.%d.tmp" % (path, os.getpid())
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, mode)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            fd = -1
            json.dump(obj, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def inside(path: str, root: str) -> bool:
    """True when `path` (which may not exist yet) resolves to `root` or below it, symlinks resolved (a symlinked folder in the middle of the path, or a link at the end, that points
    elsewhere is refused). `root` may not exist yet."""
    try:
        r = os.path.realpath(root)
        p = os.path.realpath(path)         # resolves every existing symlink (also a dangling one at the end); the part that does not exist yet is appended as is
        return p == r or p.startswith(r.rstrip("/") + "/")
    except (OSError, ValueError):
        return False


def append_line(path: str, line: str, mode: int = 0o600, inside_root: str = None, fix_mode: bool = False) -> None:
    """One O_APPEND write of line + newline (atomic for short lines). The last path component is never followed (O_NOFOLLOW: a symlink planted at the
    log path is refused with OSError, not written through). `inside_root`: the folder the file must resolve into (state or project folder); a path that
    resolves outside raises PermissionError and nothing is created. `fix_mode`: fchmod the opened file to `mode` (the file, never a path)."""
    if inside_root is not None and not inside(path, inside_root):
        raise PermissionError("refusing to write outside %s: %s" % (inside_root, path))
    ensure_dir(os.path.dirname(os.path.abspath(path)))
    if inside_root is not None and not inside(path, inside_root):
        raise PermissionError("refusing to write outside %s: %s" % (inside_root, path))
    data = (line.rstrip("\n") + "\n").encode("utf-8", "replace")
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, mode)
    try:
        if fix_mode:
            os.fchmod(fd, mode)
        os.write(fd, data)
    finally:
        os.close(fd)


def open_lock(path: str, inside_root: str = None):
    """The lock file for an flock, opened for writing without following a symlink at `path` (OSError when it is one) and, with `inside_root`, only
    when it resolves inside that folder (PermissionError otherwise). Returns a file object (the caller closes it)."""
    if inside_root is not None and not inside(path, inside_root):
        raise PermissionError("refusing to lock outside %s: %s" % (inside_root, path))
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    return os.fdopen(fd, "w")


def log_err(module: str = "", exc: BaseException = None) -> None:
    """Append a line to flow-errors.log in the gate's format (`%F %T ` + traceback with ' | ' for newlines, last 800 chars) plus module=NAME. Never raises."""
    try:
        import traceback
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)) if exc is not None else traceback.format_exc()
        append_line(os.path.join(state_dir(), "flow-errors.log"),
                    time.strftime("%F %T ") + "module=%s " % (module or "-") + tb.replace("\n", " | ")[-800:], inside_root=state_dir())
    except Exception:
        pass


def emit_event(kind: str, data: dict = None, project: str = None) -> bool:
    """events.jsonl entry through shipmiracle.events (imported only now); never raises."""
    try:
        from shipmiracle import events
        return events.emit(kind, data or {}, project=project, src="hooks")
    except Exception:
        return False
