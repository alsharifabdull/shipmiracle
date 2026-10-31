"""The install manifest <state>/v1/install-manifest.json (0600, atomic, flock-ed): one step per write `shipm init` made, so `shipm uninstall` can reverse it.
Step: {id, row, action: prefs (the 5 quick-setup answers as one step)|config_set|file_write|settings_sync|agents_install|launchd|systemd|symlink|mkdir|vscode_ext|registry_add, path|key, before, before_sha256,
after_sha256, backup, mode, ts, pending}. A step is written as `pending` BEFORE the action and completed AFTER it (`recorded`), so a kill between the two
is repaired by `reconcile()` on the next run: the step is dropped when the target still has its old value, else completed with what is there now.
`current_sha(step)` is how the target looks now (None = absent); uninstall reverses a step only while current_sha equals after_sha256."""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import stat
import time
from pathlib import Path
from typing import Optional

from .. import ShipmiracleError, SchemaError, paths, state

ACTIONS = ("config_set", "file_write", "settings_sync", "agents_install", "launchd", "systemd", "symlink", "mkdir", "vscode_ext", "registry_add", "settings_key", "ask_project", "prefs")
FAULT = None          # tests: fn(point) called between an action and its commit ("done:<action>:<key>") and before it ("begin:<action>:<key>")


def path() -> Path:
    return state.root() / "install-manifest.json"


def backups_dir() -> Path:
    return state.root() / "install-backups"


def sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha_text(s: str) -> str:
    return sha_bytes(s.encode("utf-8"))


def sha_json(v) -> str:
    return sha_text(json.dumps(v, sort_keys=True))


def sha_file(p) -> Optional[str]:
    """sha256 of a regular file, 'link:<target>' for a symlink, None when absent."""
    p = str(p)
    if os.path.islink(p):
        return "link:" + os.readlink(p)
    try:
        return sha_bytes(state.read_bytes_nofollow(p))
    except FileNotFoundError:
        return None
    except IsADirectoryError:
        return "dir"


def load() -> dict:
    """The manifest (read-only; absent = empty). SchemaError when damaged."""
    try:
        raw = state.read_bytes_nofollow(path())
    except FileNotFoundError:
        return {"v": 1, "steps": []}
    try:
        m = json.loads(raw.decode("utf-8"))
    except ValueError:
        raise SchemaError("install-manifest.json is not valid JSON")
    if not isinstance(m, dict) or m.get("v") != 1 or not isinstance(m.get("steps"), list) or any(not isinstance(s, dict) for s in m["steps"]):
        raise SchemaError("install-manifest.json has an unexpected shape")
    return m


def _mutate(fn):
    state.ensure_root()
    with state.locked("install-manifest"):
        m = load()
        out = fn(m)
        state.atomic_write(path(), (json.dumps(m, sort_keys=True, indent=1) + "\n").encode("utf-8"), 0o600)
        return out


def save_steps(steps) -> None:
    _mutate(lambda m: m.__setitem__("steps", list(steps)))


def remove_file() -> None:
    with contextlib.suppress(FileNotFoundError):
        os.unlink(str(path()))


def backup_file(src, name: str) -> Optional[str]:
    """Copy `src` into <state>/v1/install-backups (0600) and return the copy's path; None when `src` does not exist."""
    try:
        data = state.read_bytes_nofollow(src)
    except FileNotFoundError:
        return None
    d = state.ensure_dir(backups_dir())
    dest = d / ("%d-%s" % (int(time.time() * 1000), name))
    n = 0
    while dest.exists():
        n += 1
        dest = d / ("%d-%d-%s" % (int(time.time() * 1000), n, name))
    state.atomic_write(dest, data, 0o600)
    _prune_backups(d, keep=dest)
    return str(dest)


KEEP_BACKUPS = 20


def _prune_backups(d, keep=None) -> None:
    """Keep the newest KEEP_BACKUPS files in install-backups; a file a recorded step still names is never removed (L8)."""
    try:
        used = {os.path.realpath(str(s.get("backup"))) for s in load()["steps"] if s.get("backup")}
    except (ShipmiracleError, OSError):
        return                                  # unreadable manifest: delete nothing
    files = sorted((f for f in Path(d).iterdir() if f.is_file() and not f.is_symlink()), key=lambda f: (f.stat().st_mtime, f.name))
    for f in files[:-KEEP_BACKUPS]:
        if os.path.realpath(str(f)) in used or (keep is not None and f == keep):
            continue
        try:
            f.unlink()
        except OSError:
            pass


def begin(row, action, key=None, before=None, before_sha256=None, backup=None, mode=None, **extra) -> int:
    if action not in ACTIONS:
        raise SchemaError("unknown manifest action")
    step = {"row": row, "action": action, "before": before, "before_sha256": before_sha256, "after_sha256": None, "backup": backup, "mode": mode,
            "ts": int(time.time()), "pending": True}
    step["path" if action in ("file_write", "settings_sync", "symlink", "mkdir", "launchd", "systemd", "settings_key") else "key"] = str(key)
    step.update(extra)

    def fn(m):
        step["id"] = 1 + max([s.get("id", 0) for s in m["steps"]] or [0])
        m["steps"].append(step)
        return step["id"]
    return _mutate(fn)


def commit(step_id: int, after_sha256) -> None:
    def fn(m):
        for s in m["steps"]:
            if s.get("id") == step_id:
                s["after_sha256"] = after_sha256
                s["pending"] = False
    _mutate(fn)


def annotate(step_id: int, **fields) -> None:
    """Add fields to a recorded step (for values only known after the action, e.g. the file sha after the write)."""
    def fn(m):
        for s in m["steps"]:
            if s.get("id") == step_id:
                s.update(fields)
    _mutate(fn)


def drop(step_id: int) -> None:
    _mutate(lambda m: m.__setitem__("steps", [s for s in m["steps"] if s.get("id") != step_id]))


@contextlib.contextmanager
def recorded(row, action, key=None, **kw):
    """Record one write: pending step, then the body (the action), then the step's after_sha256. An exception in the body leaves the pending step
    for reconcile() (the next run decides whether the action happened)."""
    sid = begin(row, action, key, **kw)
    if FAULT:
        FAULT("begin:%s:%s" % (action, key))
    yield sid
    if FAULT:
        FAULT("done:%s:%s" % (action, key))
    s = next(s for s in load()["steps"] if s["id"] == sid)
    commit(sid, current_sha(s))


def current_sha(s):
    """How the target of step `s` looks now: a sha string, or None when it is absent / not in place."""
    a = s.get("action")
    if a in ("file_write", "settings_sync", "symlink"):
        return sha_file(s["path"])
    if a == "settings_key":                  # the boolean remoteControlAtStartup: sha of its value, None when the key (or the file) is absent
        from .. import settings_sync
        try:
            v = settings_sync.remote_control_value(s["path"])
        except Exception:
            return "unreadable"
        return None if v is None else sha_json(v)
    if a == "ask_project":                   # the `ask` inbox project: the registry entry plus the folder
        from .. import registry
        try:
            e = registry.entry(s["key"])
        except Exception:
            return None
        return sha_json("registered") if e is not None else None
    if a == "mkdir":
        return "dir" if os.path.isdir(s["path"]) and not os.path.islink(s["path"]) else None
    if a == "prefs":                         # the quick-setup answers: sha of {key: value or None} over the keys the step names
        from .. import config
        try:
            return sha_json({k: config.get(k, None) for k in s.get("keys", [])})
        except Exception:
            return "unreadable"
    if a == "config_set":
        from .. import config
        try:
            return sha_json(config.get(s["key"], None))      # None (not the default) when unset: before_sha256 is taken the same way
        except Exception:
            return None
    if a == "agents_install":
        from .. import agents
        try:
            mf = agents.manifest()
        except Exception:
            mf = None
        if not mf:
            return None
        return sha_json({n: (m or {}).get("sha256") for n, m in sorted((mf.get("agents") or {}).items())})
    if a == "launchd":
        from . import call
        rc, _, _ = call("launchctl", ["print", "gui/%d/%s" % (os.getuid(), s["label"])])
        return sha_text(s["label"]) if rc == 0 else None
    if a == "systemd":                       # Linux / WSL 2: the daily timer is enabled for the user manager
        from . import call
        rc, _, _ = call("systemctl", ["--user", "is-enabled", "--quiet", s["label"] + ".timer"])
        return sha_text(s["label"]) if rc == 0 else None
    if a == "vscode_ext":
        from . import call
        rc, out, _ = call("code", ["--list-extensions"])
        return sha_text(s["key"]) if rc == 0 and s["key"].lower() in [x.strip().lower() for x in out.splitlines()] else None
    if a == "registry_add":
        from .. import registry
        try:
            e = registry.entry(s["key"])
        except Exception:
            return None
        return sha_json(e) if e is not None else None
    return None


def clean_stale_tmp() -> int:
    """Remove `.install-manifest.json.*.tmp` files an interrupted manifest write left behind (regular files we own, not links). Done under the manifest
    lock, where no writer can be mid-write. Returns how many were removed."""
    n = 0
    try:
        with state.locked("install-manifest"):
            for name in os.listdir(str(path().parent)):
                if not (name.startswith(".install-manifest.json.") and name.endswith(".tmp")):
                    continue
                f = os.path.join(str(path().parent), name)
                try:
                    st = os.lstat(f)
                    if stat.S_ISREG(st.st_mode) and st.st_uid == os.getuid():
                        os.unlink(f); n += 1
                except OSError:
                    pass
    except (OSError, ShipmiracleError):
        pass
    return n


def reconcile() -> list:
    """Settle steps a killed run left pending. Returns the ids dropped. Needs no owner."""
    clean_stale_tmp()
    dropped = []
    for s in list(load()["steps"]):
        if not s.get("pending"):
            continue
        now = current_sha(s)
        if now == s.get("before_sha256"):
            drop(s["id"]); dropped.append(s["id"])
        else:
            commit(s["id"], now)
    return dropped


def ensure_dirs(row, target) -> None:
    """mkdir -p `target` below the home folder, one recorded `mkdir` step per folder that did not exist (so uninstall can remove exactly those)."""
    home = Path(os.path.realpath(str(paths.home())))
    t = Path(target)
    chain = []
    cur = t
    while cur != home and cur != cur.parent and not cur.exists():
        chain.append(cur)
        cur = cur.parent
    for d in reversed(chain):
        with recorded(row, "mkdir", d):
            os.mkdir(str(d), 0o755)
