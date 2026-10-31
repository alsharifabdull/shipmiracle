"""F5 Toolbox: signed-off reusable assets (scripts, templates, docs) of a project's playbook. Pure helpers; the owner commands are in shipmiracle/playbook/cli.py.

`assets: [{path, sha256, purpose, stage}]` lives in the owner-written `.shipmiracle/playbook.json`, so it is trusted through the registry sha like the rest of the playbook
(`shipm playbook asset add|remove` rewrite the file and the registry snapshot together; a chat that edits the file only makes it untrusted and the snapshot, without
assets, applies). A file is hashed through an O_NOFOLLOW handle, at most MAX_FILE bytes, only inside the project and never under .git/.shipmiracle/node_modules or a secret-looking
name. A path that is gone or changed after sign-off is reported as `missing` / `changed`, never silently dropped."""
from __future__ import annotations

import hashlib
import os
import re
import stat

from .. import SafetyError, UsageError
from . import config as pbconfig

MAX_FILE = 1024 * 1024
STAGE_ORDER = pbconfig.ASSET_STAGES
_BLOCKED_DIRS = {".git", ".shipmiracle", "node_modules", ".claude"}
_BLOCKED_NAME = re.compile(r"(^\.env($|\.)|\.pem$|\.key$|\.p12$|id_rsa|id_ed25519|secret|credential|\.keystore$)", re.I)


def check_path(pd, rel) -> str:
    """The normalised relative path of an asset to sign, or UsageError / SafetyError. Must be a regular file inside `pd`, no symlink anywhere on the way."""
    if not isinstance(rel, str):
        raise UsageError("asset path: expected text")
    rel = rel.strip()
    pbconfig._rel_path(rel, "asset path")
    rel = os.path.normpath(rel).replace(os.sep, "/")
    parts = rel.split("/")
    if rel in (".", "") or len(rel) > pbconfig.ASSET_PATH_MAX:
        raise UsageError("asset path: a file of at most %d characters" % pbconfig.ASSET_PATH_MAX)
    if any(p in _BLOCKED_DIRS for p in parts) or _BLOCKED_NAME.search(parts[-1]):
        raise UsageError("asset path: %s is not a file that can be a shared asset (git, Shipmiracle, node_modules, keys and secrets)" % rel[:60])
    root = os.path.realpath(str(pd))
    cur = root
    for p in parts:
        cur = os.path.join(cur, p)
        try:
            if stat.S_ISLNK(os.lstat(cur).st_mode):
                raise SafetyError("asset path: %s goes through a symlink" % rel[:60])
        except FileNotFoundError:
            raise UsageError("asset path: no such file in the project: %s" % rel[:60])
    if not os.path.isfile(cur):
        raise UsageError("asset path: not a regular file: %s" % rel[:60])
    return rel


def sha_of(pd, rel):
    """sha256 hex of the file, or None when it is gone, a symlink, not a regular file, unreadable or larger than MAX_FILE."""
    root = os.path.realpath(str(pd))
    cur = root
    try:
        for part in rel.split("/")[:-1]:                 # D5: a symlink in any parent directory counts as missing (same rule as check_path)
            cur = os.path.join(cur, part)
            if stat.S_ISLNK(os.lstat(cur).st_mode):
                return None
        fd = os.open(os.path.join(root, rel), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)    # D1: O_NONBLOCK so a FIFO never hangs; fstat below rejects it
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_FILE:
            return None
        h = hashlib.sha256()
        left = st.st_size
        while left > 0:
            chunk = os.read(fd, min(left, 1 << 16))
            if not chunk:
                break
            h.update(chunk)
            left -= len(chunk)
        return h.hexdigest()
    except OSError:
        return None
    finally:
        os.close(fd)


def status_of(pd, a) -> str:
    """"ok" (hash unchanged) | "changed" (content differs) | "missing" (gone, a symlink now, or unreadable)."""
    cur = sha_of(pd, a["path"])
    if cur is None:
        return "missing"
    return "ok" if cur == a["sha256"] else "changed"


def listing(pd, cfg, labels=None) -> dict:
    """{"total", "changed", "assets": [{path, stage, stageLabel, purpose, sha256, status}]} in the panel order: changed (and missing) first, then stage order, then path."""
    rows = []
    for a in (cfg or {}).get("assets") or []:
        stt = status_of(pd, a)
        rows.append({"path": a["path"], "stage": a["stage"], "stageLabel": (labels or {}).get(a["stage"], a["stage"].capitalize()), "purpose": a["purpose"],
                     "sha256": a["sha256"], "status": stt})
    rows.sort(key=lambda r: (r["status"] == "ok", STAGE_ORDER.index(r["stage"]), r["path"]))
    return {"total": len(rows), "changed": sum(1 for r in rows if r["status"] != "ok"), "assets": rows}


def with_asset(cfg, entry) -> dict:
    """A copy of the config with `entry` added or replaced (same path)."""
    a = [x for x in (cfg.get("assets") or []) if x["path"] != entry["path"]] + [entry]
    return dict(cfg, assets=a)


def without_asset(cfg, rel):
    """(copy of the config without the path, True when it was there)."""
    old = cfg.get("assets") or []
    new = [x for x in old if x["path"] != rel]
    return dict(cfg, assets=new), len(new) != len(old)
