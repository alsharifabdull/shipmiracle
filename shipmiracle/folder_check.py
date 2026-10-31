"""Is this a sane projects folder? One place for the rules (QA finding D4): absolute, resolved with realpath, an existing directory (or one that can be created under an
existing parent), owned by and writable for the current user, never a system folder, not the home folder itself, not reached through a link that leaves the home,
and on WSL not on a Windows drive. `problem()` returns None when fine, else ONE plain sentence with the exact next step. Pure reads: it never creates anything.
In a test run (SHIPMIRACLE_TEST=1) a folder under the system temp folder skips the system-folder and link rules (the temp folders of the tests live under /var and /private)."""
from __future__ import annotations

import os

ALWAYS = ("/etc", "/usr", "/bin", "/sbin", "/System", "/Library", "/dev", "/proc", "/sys", "/boot", "/lib", "/lib32", "/lib64", "/root", "/Applications", "/cores", "/run", "/private/etc")
OUTSIDE_HOME = ("/var", "/private", "/opt", "/tmp")       # system areas too, but a temp folder of a test run lives there; refused only outside the home and outside a test's temp folder
NEXT = " Choose a folder in your home, for example ~/Developer, with: shipm init --prefs"


def _under(p, root) -> bool:
    return p == root or p.startswith(root.rstrip("/") + "/")


def _home():
    from . import paths
    return os.path.realpath(str(paths.home()))


def _in_test_temp(real) -> bool:
    if os.environ.get("SHIPMIRACLE_TEST") != "1":
        return False
    from . import paths
    return paths._under_temp(real)


def syntactic_problem(v) -> str:
    """No file system access: a path that is the root or inside a system folder is never a projects folder. Used by the config validator, which also runs when the config is read."""
    if not isinstance(v, str) or not v.startswith("/"):
        return ""
    p = os.path.normpath(v)
    if p == "/" or any(_under(p, s) for s in ALWAYS):
        return "%s is a system folder." % v + NEXT
    return ""


def problem(value, home=None):
    from . import platform as aplat
    v = str(value)
    if v.startswith("~/"):
        v = os.path.join(home or str(__import__("shipmiracle.paths", fromlist=["x"]).home()), v[2:])
    if not v.startswith("/"):
        return "%s is not a full folder path (it must start with / or ~/)." % value + NEXT
    lexical = os.path.normpath(v)
    real = os.path.realpath(lexical)
    hm = os.path.realpath(home) if home else _home()
    test_tmp = _in_test_temp(real)
    if not test_tmp:
        if real == hm:
            return "%s is your whole home folder, not a projects folder." % value + NEXT
        if syntactic_problem(lexical):
            return "%s is a system folder." % value + NEXT
        if not _under(real, hm) and lexical != real:
            return "%s is a link to %s, outside your home." % (value, real) + NEXT
        if syntactic_problem(real):
            return "%s is a system folder." % value + NEXT
        if not _under(real, hm) and (any(_under(real, s) for s in OUTSIDE_HOME) or any(_under(lexical, s) for s in OUTSIDE_HOME)):
            return "%s is a system folder." % value + NEXT
    if aplat.under_windows_mount(real) or aplat.under_windows_mount(lexical):
        return "%s is on a Windows drive: file names there ignore case. Move the folder into the Linux home (for example ~/Developer)." % value + " Then run: shipm init --prefs"
    target = real
    while not os.path.lexists(target):
        parent = os.path.dirname(target)
        if parent == target:
            break
        target = parent
    if not os.path.isdir(target):
        return "%s exists but is not a folder." % (value if target == real else target) + NEXT
    try:
        st = os.stat(target)
    except OSError:
        return "%s cannot be read." % value + NEXT
    if hasattr(os, "getuid") and st.st_uid != os.getuid():
        return "%s belongs to another user." % (value if target == real else target) + NEXT
    if not os.access(target, os.W_OK | os.X_OK):
        return "You cannot write in %s." % (value if target == real else target) + NEXT
    return None
