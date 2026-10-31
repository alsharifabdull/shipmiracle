"""The Linux / WSL2 daily timer's unit files (plan docs/plans/2026-10-21-cross-platform-onboarding.md task 7): rendering, escaping and writing for `bin/shipm-timer` and for
`shipm init` row 9. Stdlib only. Units come from templates/systemd/*.in (placeholders @WS@ @STATE@). Values are checked and escaped for systemd (% and $ doubled; a newline,
quote, backslash or NUL in a path is refused). A unit file that exists and differs is never replaced. Nothing here runs systemctl."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

LABEL = "com.shipmiracle.daily"
SUFFIXES = (".service", ".timer")


def _check(value):
    v = str(value)
    if any(c in v for c in '\n\r"\\\0'):
        raise ValueError("path contains a character systemd units cannot hold safely: %r" % v)
    return v


def esc(value):
    """For Exec* lines: `%` (a specifier) and `$` (a variable marker) are doubled."""
    return _check(value).replace("%", "%%").replace("$", "$$")


def esc_plain(value):
    """For every other line (StandardOutput=, WorkingDirectory=): only the specifier `%` is doubled; systemd does not expand `$` there, so `$$` would be a different path."""
    return _check(value).replace("%", "%%")


def render(name, ws, state=None):
    """Bytes of unit `name` (e.g. com.shipmiracle.daily.timer) for the engine checkout `ws`."""
    from . import paths
    state = state or paths.state_dir()
    esc(ws), esc(state)                                    # refuse an unsafe path before anything is read
    txt = (Path(ws) / "templates" / "systemd" / (name + ".in")).read_text(encoding="utf-8")
    out = []
    for line in txt.splitlines(True):
        e = esc if line.lstrip().startswith("Exec") else esc_plain
        out.append(line.replace("@WS@", e(ws)).replace("@STATE@", e(state)))
    return "".join(out).encode("utf-8")


def unit_dir(arg=None):
    """~/.config/systemd/user. XDG_CONFIG_HOME is honoured outside tests only when it is an absolute path below the home folder (a relative or foreign value is ignored)."""
    if arg:
        return Path(arg)
    from . import paths
    home = Path(paths.home())
    base = home / ".config"
    xdg = os.environ.get("XDG_CONFIG_HOME") if os.environ.get("SHIPMIRACLE_TEST") != "1" else None
    if xdg and os.path.isabs(xdg):
        x = Path(os.path.normpath(xdg))
        try:
            Path(os.path.realpath(str(x))).relative_to(os.path.realpath(str(home)))      # real paths: a link below the home folder that points elsewhere is rejected
            base = x
        except ValueError:
            pass
    return base / "systemd" / "user"


def unit_path(suffix, d=None):
    return unit_dir(d) / (LABEL + suffix)


def write_unit(p, data):
    """Write one unit atomically (0644) beside its final name."""
    p = Path(p)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".shipmiracle-unit-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.chmod(tmp, 0o644)
        os.replace(tmp, str(p))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_units(d, ws):
    """Returns (written names, problem or None). Never replaces a file that differs."""
    d = Path(d)
    d.mkdir(parents=True, exist_ok=True)
    out = []
    for s in SUFFIXES:
        data, p = render(LABEL + s, ws), d / (LABEL + s)
        if p.exists() or p.is_symlink():
            if p.is_symlink() or p.read_bytes() != data:
                return out, "%s exists and differs from the template: not replaced" % p
            continue
        write_unit(p, data)
        out.append(p.name)
    return out, None
