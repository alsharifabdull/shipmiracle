"""Is the project's remote private? (Phase 6 spec section 2, "Visibility".)

Cache `<state>/v1/autopilot/visibility.json` = {sha256(remote_url): {"private": bool, "ts": int}}, valid for 24 h, written atomically with mode 0600.
`is_private()` NEVER touches the network: it only reads the cache. Missing, expired, unreadable or future-dated entries mean NOT private.
`refresh()` is the only function that asks GitHub (`gh api repos/{o}/{r} --jq .private`, 5 s timeout) through an injectable runner; it is called by the
owner's start command and by the engine at deliver, never by a hook. Any error leaves the cache untouched, so the answer stays 'not private'."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import subprocess
import time
from typing import Callable, Optional, Tuple

from shipmiracle import paths

VALID_SECONDS = 24 * 3600
FUTURE_SLACK = 300                      # a cache entry stamped more than 5 minutes ahead of 'now' is not trusted
TIMEOUT = 5

_NAME = r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}"
_URL_RES = (
    re.compile(r"^(?:https?|ssh|git)://(?:[^@/]+@)?github\.com(?::\d+)?/(%s)/(%s)/?$" % (_NAME, _NAME)),
    re.compile(r"^(?:[A-Za-z0-9_.-]+@)?github\.com:(%s)/(%s)/?$" % (_NAME, _NAME)),
)


def cache_path(state_dir=None) -> str:
    return os.path.join(str(state_dir if state_dir is not None else paths.state_dir()), "v1", "autopilot", "visibility.json")


def key(remote_url: str) -> str:
    return hashlib.sha256(remote_url.encode("utf-8", "surrogateescape")).hexdigest()


def parse_remote(remote_url) -> Optional[Tuple[str, str]]:
    """(owner, repo) of a github.com remote URL, else None (other hosts cannot be checked)."""
    if not isinstance(remote_url, str) or not remote_url or len(remote_url) > 500:
        return None
    u = remote_url.strip()
    for rx in _URL_RES:
        m = rx.match(u)
        if m:
            repo = m.group(2)
            repo = repo[:-4] if repo.endswith(".git") else repo
            if repo and repo not in (".", "..") and not m.group(1).startswith("-"):
                return m.group(1), repo
    return None


def read_cache(state_dir=None) -> dict:
    try:
        with open(cache_path(state_dir), encoding="utf-8") as f:
            raw = f.read(2 * 1024 * 1024)
        j = json.loads(raw)
    except (OSError, ValueError):
        return {}
    return j if isinstance(j, dict) else {}


def is_private(remote_url, now=None, state_dir=None) -> bool:
    """True only for a fresh cached 'private: true'. No network, no side effect."""
    if not isinstance(remote_url, str) or not remote_url:
        return False
    now = time.time() if now is None else now
    e = read_cache(state_dir).get(key(remote_url))
    if not isinstance(e, dict) or e.get("private") is not True:
        return False
    ts = e.get("ts")
    if isinstance(ts, bool) or not isinstance(ts, (int, float)):
        return False
    return ts - FUTURE_SLACK <= now <= ts + VALID_SECONDS


def _ensure_dir(d: str) -> None:
    missing = []
    p = os.path.abspath(d)
    while p and not os.path.isdir(p):
        missing.append(p)
        parent = os.path.dirname(p)
        if parent == p:
            break
        p = parent
    for x in reversed(missing):
        try:
            os.mkdir(x, 0o700)
        except FileExistsError:
            pass


def write_entry(remote_url: str, private: bool, now=None, state_dir=None) -> None:
    """Merge one entry into the cache: flock on a sidecar file, temp file in the same folder, fsync, replace, 0600."""
    now = int(time.time() if now is None else now)
    path = cache_path(state_dir)
    d = os.path.dirname(path)
    _ensure_dir(d)
    lock = os.open(path + ".lock", os.O_WRONLY | os.O_CREAT, 0o600)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        cur = read_cache(state_dir)
        cur = {k: v for k, v in cur.items() if isinstance(v, dict) and isinstance(v.get("ts"), (int, float)) and now - v["ts"] <= 7 * VALID_SECONDS}
        cur[key(remote_url)] = {"private": bool(private), "ts": now}
        tmp = "%s.%d.tmp" % (path, os.getpid())
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                fd = -1
                json.dump(cur, f, sort_keys=True)
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
    finally:
        os.close(lock)


def default_runner(argv, timeout=TIMEOUT):
    """Run argv with a minimal environment; returns (returncode, stdout). Never raises for a missing binary or a timeout (returns (127, '') / (124, ''))."""
    env = {"PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin", "HOME": os.path.expanduser("~"), "GH_PROMPT_DISABLED": "1", "NO_COLOR": "1"}
    for k in ("GH_TOKEN", "GITHUB_TOKEN", "GH_CONFIG_DIR"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    try:
        r = subprocess.run(argv, env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, ""
    except OSError:
        return 127, ""
    return r.returncode, r.stdout.decode("utf-8", "replace")


def refresh(remote_url, runner: Optional[Callable] = None, now=None, state_dir=None) -> Optional[bool]:
    """Ask GitHub whether the remote is private and cache the answer. Returns True / False, or None when unknown (not github.com, offline, error,
    unexpected output): nothing is written then, so is_private() keeps answering from whatever the cache held. The runner takes (argv, timeout)."""
    nr = parse_remote(remote_url)
    if nr is None:
        return None
    runner = runner or default_runner
    try:
        rc, out = runner(["gh", "api", "repos/%s/%s" % nr, "--jq", ".private"], TIMEOUT)
    except Exception:
        return None
    if rc != 0 or not isinstance(out, str):
        return None
    v = out.strip().lower()
    if v not in ("true", "false"):
        return None
    write_entry(remote_url, v == "true", now=now, state_dir=state_dir)
    return v == "true"
