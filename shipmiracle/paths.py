"""Where things live. Test overrides (SHIPMIRACLE_HOME, SHIPMIRACLE_DEV, SHIPMIRACLE_STATE, SHIPMIRACLE_WS, SHIPMIRACLE_CONFIG) are honoured only when SHIPMIRACLE_TEST=1."""
from __future__ import annotations

import os
import pwd
import re
import sys
import unicodedata
from pathlib import Path

from . import SafetyError


def real_home() -> Path:
    """The account's home from the password database; $HOME is ignored on purpose. Test seam: under SHIPMIRACLE_TEST=1, SHIPMIRACLE_REAL_HOME names a decoy
    folder that stands in for the real home (tests prove that nothing reaches it); outside SHIPMIRACLE_TEST=1 it is ignored, and so it is when the folder is not
    under a temp root or is the passwd home itself (L3: a leaked variable can never move the guarded 'real home' onto a folder that matters)."""
    pw = Path(pwd.getpwuid(os.getuid()).pw_dir)
    rh = os.environ.get("SHIPMIRACLE_REAL_HOME")
    if os.environ.get("SHIPMIRACLE_TEST") == "1" and rh and _under_temp(rh) and not _same(rh, pw):
        return Path(rh)
    return pw


def test_override(var: str, default):
    """The value of env var `var` when SHIPMIRACLE_TEST=1 and it is set, else `default`; always a Path."""
    if os.environ.get("SHIPMIRACLE_TEST") == "1" and os.environ.get(var):
        return Path(os.environ[var])
    return Path(default)


def home() -> Path:
    """SHIPMIRACLE_HOME under SHIPMIRACLE_TEST=1. Under SHIPMIRACLE_TEST=1 without SHIPMIRACLE_HOME a $HOME that differs from the real home and sits under a temp root is used
    (a HOME-only sandbox can never reach the real home); any other case is the real home, and `assert_home_writable` then refuses the writers."""
    if os.environ.get("SHIPMIRACLE_TEST") == "1":
        if os.environ.get("SHIPMIRACLE_HOME"):
            return Path(os.environ["SHIPMIRACLE_HOME"])
        hv = os.environ.get("HOME")
        if hv and _same(hv, real_home()) is False and _under_temp(hv):
            return Path(hv)
    return real_home()


def _same(a, b) -> bool:
    return fold(os.path.realpath(str(a))) == fold(os.path.realpath(str(b)))


def assert_home_writable(what: str = "this write") -> None:
    """Under SHIPMIRACLE_TEST=1 refuse (SafetyError) when the effective home is the real home or when SHIPMIRACLE_HOME is unset and $HOME is neither the real home
    nor under a temp root: a test run must never write where the owner's real files are."""
    if os.environ.get("SHIPMIRACLE_TEST") != "1":
        return
    if os.environ.get("SHIPMIRACLE_HOME"):
        return
    hv = os.environ.get("HOME")
    if hv and not _same(hv, real_home()) and not _under_temp(hv):
        raise SafetyError("%s refused: SHIPMIRACLE_TEST=1 without SHIPMIRACLE_HOME and HOME=%s is not under a temp folder; set SHIPMIRACLE_HOME to a temp folder" % (what, hv))


def _sandbox_marker() -> bool:
    """True when this process shows it is a test or sandbox run: SHIPMIRACLE_TEST=1, or a HOME / CLAUDE_CONFIG_DIR inside a temp root that is not the real home. Such a run
    must never write the account's real Shipmiracle / Claude folders, also when a subprocess lost SHIPMIRACLE_TEST (a cleared env drops everything, but a leftover HOME or
    CLAUDE_CONFIG_DIR in a temp folder still says 'sandbox')."""
    if os.environ.get("SHIPMIRACLE_TEST") == "1":
        return True
    hv, cd = os.environ.get("HOME"), os.environ.get("CLAUDE_CONFIG_DIR")
    return bool((hv and _under_temp(hv) and not _same(hv, real_home())) or (cd and _under_temp(cd)))


def _inside_real(path) -> str:
    """The real folder (<real home>/.claude, .config/shipmiracle, .local/state/shipmiracle) that contains `path`, else ''."""
    rh = real_home()
    p = fold(os.path.realpath(str(path)))
    for sub in (".claude", ".config/shipmiracle", ".local/state/shipmiracle"):
        root = rh / sub
        r = fold(os.path.realpath(str(root)))
        if p == r or p.startswith(r.rstrip("/") + "/"):
            return str(root)
    return ""


_ALLOW_REAL = [False]


class allow_real_writes(object):
    """Context manager: lifts guard_real_write inside it. Used only by bin/test-all's cleanup of a polluted real settings file (settings_sync.repair emergency=True)."""
    def __enter__(self):
        _ALLOW_REAL[0] = True

    def __exit__(self, *a):
        _ALLOW_REAL[0] = False


def guard_real_write(path, what: str = "this write") -> None:
    """SafetyError for a write into the real home's .claude / .config/shipmiracle / .local/state/shipmiracle from a sandboxed run (see _sandbox_marker). Only resolves paths."""
    if _ALLOW_REAL[0] or not _sandbox_marker():
        return
    root = _inside_real(path)
    if root:
        raise SafetyError("%s refused: %s is inside the real folder %s and this is a test or sandbox run (SHIPMIRACLE_TEST=1, or HOME / CLAUDE_CONFIG_DIR in a temp folder). "
                          "Set SHIPMIRACLE_HOME, HOME, CLAUDE_CONFIG_DIR, SHIPMIRACLE_CONFIG and SHIPMIRACLE_STATE to a temp folder" % (what, path, root))


def assert_not_real_claude(path, what: str = "this write") -> None:
    """Refuse (SafetyError) any target inside <real home>/.claude in a sandboxed run, and any CLAUDE_CONFIG_DIR that resolves there. Only resolves paths."""
    if not _sandbox_marker():
        return
    root = os.path.realpath(str(real_home() / ".claude"))
    for cand in (str(path), os.environ.get("CLAUDE_CONFIG_DIR") or ""):
        if not cand:
            continue
        p = fold(os.path.realpath(cand))
        r = fold(root)
        if p == r or p.startswith(r.rstrip("/") + "/"):
            raise SafetyError("%s refused: %s is inside the real home's .claude (%s) and this is a test or sandbox run. Set SHIPMIRACLE_HOME, HOME and CLAUDE_CONFIG_DIR to a temp folder" % (what, cand, root))


def workspace_dir() -> Path:
    return test_override("SHIPMIRACLE_WS", Path(__file__).resolve().parent.parent)


def main_checkout(ws) -> Path:
    """The main checkout of workspace `ws`: ws itself, or, when ws is a git worktree (.git is a file), the repository that owns it."""
    ws = Path(ws)
    g = ws / ".git"
    try:
        if g.is_symlink() or not g.is_file():
            return ws
        first = g.read_text(encoding="utf-8", errors="replace").splitlines()[0]
    except (OSError, IndexError):
        return ws
    m = re.fullmatch(r"gitdir:\s*(.+)/\.git/worktrees/[^/]+/?", first.strip())
    if not m:
        return ws
    x = m.group(1)
    if not os.path.isabs(x):               # git --relative-paths: relative to the folder holding the .git file, not the cwd
        x = os.path.normpath(os.path.join(str(ws), x))
    return Path(x)


def _configured_projects_dir():
    """config paths.projects_dir as a Path (absolute, or ~/... against home()), or None when unset or unreadable."""
    try:
        from . import config
        v = config.get("paths.projects_dir")
    except Exception:
        return None
    if not isinstance(v, str) or not v:
        return None
    return home() / v[2:] if v.startswith("~/") else Path(v)


def dev_dir() -> Path:
    """The projects folder: SHIPMIRACLE_DEV (tests), else config paths.projects_dir, else <home>/Developer."""
    return test_override("SHIPMIRACLE_DEV", _configured_projects_dir() or home() / "Developer")


def state_dir() -> Path:
    return test_override("SHIPMIRACLE_STATE", home() / ".local" / "state" / "shipmiracle")


def config_dir() -> Path:
    return test_override("SHIPMIRACLE_CONFIG", home() / ".config" / "shipmiracle")


def fold(p) -> str:
    """Path comparison key: case-insensitive and NFC-normalised on macOS (APFS accepts NFD spellings of the same name) and on a WSL 2 Windows drive (/mnt/c, NTFS: the
    platform layer decides). Every other Linux path keeps its case."""
    p = os.path.normcase(str(p))
    if sys.platform == "darwin":
        return unicodedata.normalize("NFC", p).casefold()
    if p.startswith("/mnt/"):
        from . import platform as _plat
        if _plat.case_insensitive(p):
            return unicodedata.normalize("NFC", p).casefold()
    return p


def claude_dirname(path) -> str:
    """Claude Code's folder name for a path: every character outside [A-Za-z0-9] becomes '-'."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(path))


def _real_roots():
    h = real_home()
    return [h / ".local" / "state" / "shipmiracle", h / ".config" / "shipmiracle"]


def assert_isolated(path) -> None:
    """Under SHIPMIRACLE_TEST=1 refuse (SafetyError) any path inside the real state or config folder. Only resolves paths, never touches them."""
    if os.environ.get("SHIPMIRACLE_TEST") != "1":
        return
    p = fold(os.path.realpath(str(path)))
    for root in _real_roots():
        r = fold(os.path.realpath(str(root)))
        if p == r or p.startswith(r.rstrip("/") + "/"):
            raise SafetyError("test run refused to touch the real folder %s" % root)


def _temp_roots():
    """FIXED temp roots only. Never $TMPDIR or tempfile.gettempdir(): a chat controls the environment, and a TMPDIR pointing at a real project folder would make that folder count as
    a sandbox (owner locks 2 and 3 skipped). The per-user macOS temp folder (confstr) lies under /var/folders and is listed only for clarity."""
    roots = ["/tmp", "/private/tmp", "/var/folders", "/private/var/folders"]
    try:
        u = os.confstr("CS_DARWIN_USER_TEMP_DIR")
        if u:
            roots.append(u)
    except (AttributeError, ValueError, OSError):
        pass
    return sorted({os.path.realpath(r) for r in roots})


def _under_temp(d) -> bool:
    r = os.path.realpath(str(d))
    return any(r == t or r.startswith(t.rstrip("/") + "/") for t in _temp_roots())


def sandboxed() -> bool:
    """True only under SHIPMIRACLE_TEST=1 when the config, state, workspace and dev folders AND $HOME are all set explicitly and all inside the system
    temp folder. A chat can set any env var, so a partial sandbox (say only SHIPMIRACLE_CONFIG and SHIPMIRACLE_STATE in /tmp while the workspace is real)
    is NOT a sandbox: the owner check must still run."""
    if os.environ.get("SHIPMIRACLE_TEST") != "1":
        return False
    for var in ("SHIPMIRACLE_CONFIG", "SHIPMIRACLE_STATE", "SHIPMIRACLE_WS", "SHIPMIRACLE_DEV", "HOME"):
        v = os.environ.get(var)
        if not v or not _under_temp(v):
            return False
    if os.environ.get("SHIPMIRACLE_HOME") and not _under_temp(os.environ["SHIPMIRACLE_HOME"]):
        return False
    return True


def ws_writable_for_tests() -> bool:
    """False when SHIPMIRACLE_TEST=1 points the workspace at a real (non-temp) folder: writers of <workspace>/config files refuse then."""
    return os.environ.get("SHIPMIRACLE_TEST") != "1" or _under_temp(workspace_dir())


def require_owner(what: str) -> None:
    """Owner-only actions (agents install/uninstall/vendor/activate/migrate, registry and config writes) refuse inside a Claude Code chat:
    Claude Code sets CLAUDECODE in the Bash tool's environment (probe P3-3); any value, also an empty one, counts as 'inside a chat'.
    A convenience guard (`env -u CLAUDECODE` defeats it; the flow gate's ADMIN_RE and its guards are the second layer; a chat can still run
    python directly as the same user: the boundary is the gate plus the owner's terminal). SHIPMIRACLE_TEST=1 skips it only when the whole sandbox
    (config, state, workspace, dev, HOME) is under the temp folder (`sandboxed()`), and SHIPMIRACLE_ENFORCE_OWNER=1 re-enables it for the tests of the guard itself."""
    if "CLAUDECODE" not in os.environ:
        return
    if sandboxed() and os.environ.get("SHIPMIRACLE_ENFORCE_OWNER") != "1":
        return
    raise SafetyError("%s is for the owner in a terminal, not inside a Claude Code chat (CLAUDECODE is set)" % what)
