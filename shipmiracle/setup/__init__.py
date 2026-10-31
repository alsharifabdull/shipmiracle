"""`shipm init` / `shipm uninstall`: the first-run checklist (rows.py), its install manifest (manifest.py), the runner (run.py), the reversal (uninstall.py)
and the CLI glue (cli.py). This file holds the one seam to external tools: every probe and every action calls a tool through `tool()` / `call()`.
Under SHIPMIRACLE_TEST=1 the folder in SHIPMIRACLE_SETUP_BIN is the ONLY place a tool is looked up (no PATH), so a test can never reach a real brew, gh, code,
launchctl, xcode-select or claude. Outside tests SHIPMIRACLE_SETUP_BIN is ignored and the usual folders are searched (Homebrew first)."""
from __future__ import annotations

import os
import shutil
import subprocess
from typing import List, Optional, Tuple

from .. import SafetyError, paths

TOOL_TIMEOUT = 25
_REAL_PATH = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"


def testing() -> bool:
    return os.environ.get("SHIPMIRACLE_TEST") == "1"


def seam_dir() -> Optional[str]:
    return os.environ.get("SHIPMIRACLE_SETUP_BIN") if testing() and os.environ.get("SHIPMIRACLE_SETUP_BIN") else None


def tool(name: str) -> Optional[str]:
    """Absolute path of external tool `name`, or None. Under SHIPMIRACLE_TEST=1 only the seam folder is searched."""
    if testing():
        d = seam_dir()
        if not d:
            return None
        p = os.path.join(d, name)
        return p if os.path.isfile(p) and os.access(p, os.X_OK) else None
    return shutil.which(name, path=_REAL_PATH + os.pathsep + os.environ.get("PATH", ""))


def _env() -> dict:
    if testing():
        env = {"PATH": seam_dir() or "/nonexistent", "HOME": str(paths.home()), "PYTHONDONTWRITEBYTECODE": "1"}
        env.update({k: v for k, v in os.environ.items() if k.startswith("SHIPMIRACLE_FAKE_")})
        return env
    env = dict(os.environ)
    env["PATH"] = _REAL_PATH + os.pathsep + env.get("PATH", "")
    return env


def call(name: str, args: List[str], timeout: int = TOOL_TIMEOUT, interactive: bool = False) -> Tuple[int, str, str]:
    """(returncode, stdout, stderr) of `name args`; 127 when the tool is missing, 124 on a timeout. No shell, stdin closed
    (`interactive` keeps the terminal for browser login flows and returns empty output)."""
    exe = tool(name)
    if exe is None:
        return 127, "", "%s not found" % name
    try:
        if interactive:
            r = subprocess.run([exe] + list(args), env=_env(), timeout=None)
            return r.returncode, "", ""
        r = subprocess.run([exe] + list(args), env=_env(), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, "", "%s timed out" % name
    except OSError as e:
        return 126, "", "%s could not run (%s)" % (name, type(e).__name__)
    return r.returncode, r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace")


def guard_home() -> None:
    """Under SHIPMIRACLE_TEST=1 refuse to run against the account's real home (init writes ~/.claude, ~/Library/LaunchAgents, ~/.local/bin)."""
    if testing() and os.path.realpath(str(paths.home())) == os.path.realpath(str(paths.real_home())):
        raise SafetyError("test run refused to use the real home folder %s" % paths.real_home())
    paths.assert_isolated(paths.state_dir())
    paths.assert_isolated(paths.config_dir())
