"""`.shipmiracle/playbook.json` (owner-written, committed, <= 4 KB, or <= 16 KB with a toolbox): validation, canonical form, sha256 and the trust rule.

The file only counts when its sha256 equals the one the owner stored in the registry (`shipm playbook set`); otherwise the registry
snapshot is used, and without a snapshot the software defaults. A chat that edits the file can therefore never loosen anything."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import unicodedata

from .. import UsageError
from .. import state
from . import types

MAX_BYTES = 4096
MAX_BYTES_ASSETS = 16384       # a playbook that carries the toolbox (F5) may be larger; without assets the 4 KB cap stands
MAX_ASSETS = 40
ASSET_STAGES = ("scope", "plan", "approve", "do", "verify", "review", "deliver")
ASSET_PURPOSE_MAX = 120
ASSET_PATH_MAX = 120
LEVELS = ("strict", "warn", "off")
AUTOPILOTS = ("manual", "guided")
LANGS = ("en", "ar")
_TOP = {"v", "type", "level", "autopilot", "overrides", "charter", "report", "set_by", "ts", "assets"}
_OVR = {"risk_paths", "test_cmd", "fast_lane"}
_SHA_RE = re.compile(r"[0-9a-f]{64}")
FULL_REFUSED = "full autopilot arrives in P6"       # kept word for word for the types other than software (full arrives for them after P9)
FULL_NEEDS_SWITCH = "autopilot full (P6) needs the owner switch: run `shipm switch autopilot.full.enabled on` first"
DEFAULTS = {"v": 1, "type": "software", "level": "strict", "autopilot": "guided", "overrides": {}, "charter": None, "report": {"lang": "en"}}
TRUSTED, SNAPSHOT, UNTRUSTED, NONE = "trusted", "snapshot", "untrusted", "none"


def _int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _ctrl(s: str) -> bool:
    return any(unicodedata.category(c).startswith("C") for c in s)


def _rel_path(s, what):
    if not isinstance(s, str) or not s or _ctrl(s):
        raise UsageError("%s: expected a non-empty path without control characters" % what)
    if s.startswith("/") or s.startswith("~") or "\\" in s or ".." in s.split("/"):
        raise UsageError("%s: must be relative, without '..', '~' or a leading '/'" % what)


def _risk_paths(v):
    if not isinstance(v, list) or len(v) > 50:
        raise UsageError("risk_paths: expected a list of at most 50 globs")
    for g in v:
        if not isinstance(g, str) or not 0 < len(g) <= 200:
            raise UsageError("risk_paths: each glob is 1-200 characters")
        _rel_path(g, "risk_paths")
    return list(v)


def _test_cmd(v, project_dir):
    if not isinstance(v, str) or len(v) > 200:
        raise UsageError("test_cmd: expected a relative file path of at most 200 characters")
    _rel_path(v, "test_cmd")
    if project_dir is not None:
        root = os.path.realpath(str(project_dir))
        full = os.path.realpath(os.path.join(root, v))
        if not (full == root or full.startswith(root.rstrip("/") + "/")):
            raise UsageError("test_cmd: resolves outside the project")
        if not os.path.isfile(full):
            raise UsageError("test_cmd: no such file in the project")
    return v


def _fast_lane(v):
    if not isinstance(v, dict) or not v or set(v) - {"max_files", "max_lines"}:
        raise UsageError("fast_lane: expected {max_files, max_lines}")
    out = {}
    if "max_files" in v:
        if not _int(v["max_files"]) or not 1 <= v["max_files"] <= 10:
            raise UsageError("fast_lane.max_files: integer 1-10")
        out["max_files"] = v["max_files"]
    if "max_lines" in v:
        if not _int(v["max_lines"]) or not 1 <= v["max_lines"] <= 500:
            raise UsageError("fast_lane.max_lines: integer 1-500")
        out["max_lines"] = v["max_lines"]
    return out


def _full_enabled() -> bool:
    """The owner switch autopilot.full.enabled (default off). Anything unreadable counts as off (fail closed)."""
    try:
        from .. import config as owner_config
        return owner_config.get("autopilot.full.enabled") is True
    except Exception:
        return False


def _assets(v):
    """F5 toolbox: [{path, sha256, purpose, stage}], at most MAX_ASSETS, unique relative paths, sorted by path (so the sha does not depend on the order)."""
    if not isinstance(v, list) or len(v) > MAX_ASSETS:
        raise UsageError("assets: expected a list of at most %d" % MAX_ASSETS)
    out, seen = [], set()
    for a in v:
        if not isinstance(a, dict) or set(a) != {"path", "sha256", "purpose", "stage"}:
            raise UsageError("assets: each asset is {path, sha256, purpose, stage}")
        p, h, pu, st = a["path"], a["sha256"], a["purpose"], a["stage"]
        _rel_path(p, "assets.path")
        if len(p) > ASSET_PATH_MAX or p.endswith("/") or p in seen:
            raise UsageError("assets.path: at most %d characters, a file, no duplicates" % ASSET_PATH_MAX)
        seen.add(p)
        if not isinstance(h, str) or not _SHA_RE.fullmatch(h):
            raise UsageError("assets.sha256: 64 lowercase hex characters")
        if not isinstance(pu, str) or not 0 < len(pu.strip()) <= ASSET_PURPOSE_MAX or _ctrl(pu):
            raise UsageError("assets.purpose: 1-%d characters, no control characters" % ASSET_PURPOSE_MAX)
        if st not in ASSET_STAGES:
            raise UsageError("assets.stage: one of %s" % ", ".join(ASSET_STAGES))
        out.append({"path": p, "sha256": h, "purpose": pu.strip(), "stage": st})
    return sorted(out, key=lambda x: x["path"])


def validate(d, project_dir=None) -> dict:
    """The normalised playbook (defaults filled) or UsageError. With `project_dir`, test_cmd must be an existing file inside it."""
    if not isinstance(d, dict):
        raise UsageError("playbook: expected a JSON object")
    extra = set(d) - _TOP
    if extra:
        raise UsageError("playbook: unknown keys %s" % ", ".join(sorted(map(str, extra))))
    if d.get("v") != 1 or not _int(d.get("v")):
        raise UsageError("playbook: v must be 1")
    if d.get("type") not in types.TYPES:
        raise UsageError("type: expected one of %s" % ", ".join(types.TYPES))
    level = d.get("level", "strict")
    if level not in LEVELS:
        raise UsageError("level: expected strict, warn or off")
    ap = d.get("autopilot", "guided")
    if ap == "full":
        if d["type"] != "software":
            raise UsageError(FULL_REFUSED)
        if not _full_enabled():
            raise UsageError(FULL_NEEDS_SWITCH)
    if ap not in AUTOPILOTS and ap not in ("off", "full"):
        raise UsageError("autopilot: expected manual, guided or full")
    if ap == "off" or level == "off":
        ap = "manual"
    ov = d.get("overrides", {})
    if not isinstance(ov, dict) or set(ov) - _OVR:
        raise UsageError("overrides: allowed keys are risk_paths, test_cmd, fast_lane")
    out_ov = {}
    if "risk_paths" in ov:
        out_ov["risk_paths"] = _risk_paths(ov["risk_paths"])
    if "test_cmd" in ov:
        out_ov["test_cmd"] = _test_cmd(ov["test_cmd"], project_dir)
    if "fast_lane" in ov:
        out_ov["fast_lane"] = _fast_lane(ov["fast_lane"])
    if d.get("charter") is not None:
        raise UsageError("charter: must be null in this version")
    rep = d.get("report", {"lang": "en"})
    if not isinstance(rep, dict) or set(rep) - {"lang"} or rep.get("lang", "en") not in LANGS:
        raise UsageError("report: expected {lang: en|ar}")
    out = {"v": 1, "type": d["type"], "level": level, "autopilot": ap, "overrides": out_ov, "charter": None,
           "report": {"lang": rep.get("lang", "en")}}
    if d.get("assets"):
        out["assets"] = _assets(d["assets"])                  # only when there are some: a playbook without a toolbox keeps its old canonical form and sha
    elif "assets" in d and d["assets"] != []:
        raise UsageError("assets: expected a list")
    if "set_by" in d:
        if not isinstance(d["set_by"], str) or len(d["set_by"]) > 40 or _ctrl(d["set_by"]):
            raise UsageError("set_by: a short text")
        out["set_by"] = d["set_by"]
    if "ts" in d:
        if not _int(d["ts"]) or d["ts"] < 0:
            raise UsageError("ts: a non-negative integer")
        out["ts"] = d["ts"]
    return out


def parse(raw: bytes, project_dir=None) -> dict:
    """Bytes of a playbook.json -> normalised dict. UsageError for size, JSON or content problems."""
    if len(raw) > MAX_BYTES_ASSETS:
        raise UsageError("playbook: larger than %d bytes" % MAX_BYTES)

    def refuse(x):
        raise ValueError("constant")
    try:
        d = json.loads(raw.decode("utf-8"), parse_constant=refuse)
    except (ValueError, RecursionError):
        raise UsageError("playbook: not valid JSON")
    out = validate(d, project_dir)
    if len(raw) > (MAX_BYTES_ASSETS if out.get("assets") else MAX_BYTES):
        raise UsageError("playbook: larger than %d bytes" % MAX_BYTES)
    return out


def canonical(d) -> bytes:
    """Stable serialisation: sorted keys, no spaces, ASCII."""
    return json.dumps(d, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def digest(d) -> str:
    """sha256 of the canonical form of the NORMALISED playbook (so formatting and omitted defaults do not matter)."""
    return hashlib.sha256(canonical(validate(d))).hexdigest()


def snapshot_of(d) -> dict:
    """What `shipm playbook set` stores in the registry entry: {sha256, type, autopilot, overrides}."""
    n = validate(d)
    return {"sha256": digest(n), "type": n["type"], "autopilot": n["autopilot"], "overrides": copy.deepcopy(n["overrides"])}


def _valid_snapshot(s):
    """The normalised playbook a registry snapshot stands for, or None when the snapshot is damaged."""
    if not isinstance(s, dict) or set(s) != {"sha256", "type", "autopilot", "overrides"} or not isinstance(s["sha256"], str) \
            or not _SHA_RE.fullmatch(s["sha256"]):
        return None
    try:
        return validate({"v": 1, "type": s["type"], "autopilot": s["autopilot"], "overrides": s["overrides"]})
    except UsageError:
        return None


def defaults() -> dict:
    return copy.deepcopy(DEFAULTS)


def load_trusted(project_dir, registry_entry):
    """(effective_config, trust_state, reason). trust_state: "trusted" (file sha == registry sha), "snapshot" (no file, registry
    snapshot used), "untrusted" (file present but sha mismatch / invalid / unreadable / no registry sha: snapshot, else software
    defaults, guided; the caller logs `playbook.untrusted`), "none" (no file, no snapshot: config None, no playbook for this project)."""
    snap = registry_entry.get("playbook") if isinstance(registry_entry, dict) else None
    snap_cfg = _valid_snapshot(snap)
    path = os.path.join(str(project_dir), ".shipmiracle", "playbook.json")
    problem = None
    try:
        raw = state.read_bytes_nofollow(path)
    except FileNotFoundError:
        raw = None
    except Exception as e:
        raw = None
        problem = "unreadable (%s)" % type(e).__name__
    if raw is None and problem is None:
        if snap_cfg is not None:
            return snap_cfg, SNAPSHOT, "no playbook.json; using the registry snapshot"
        return None, NONE, "no playbook"
    cfg = None
    if raw is not None:
        try:
            cfg = parse(raw)
        except UsageError as e:
            problem = "invalid (%s)" % str(e)[:80]
        else:
            problem = None
    if cfg is not None:
        if snap_cfg is not None and isinstance(snap, dict) and digest(cfg) == snap["sha256"]:
            return cfg, TRUSTED, "playbook.json matches the registry sha"
        problem = "sha256 does not match the registry" if snap_cfg is not None else "no registry sha to check it against"
    if snap_cfg is not None:
        return snap_cfg, UNTRUSTED, "playbook.json %s; using the registry snapshot" % problem
    return defaults(), UNTRUSTED, "playbook.json %s; using the software defaults (guided)" % problem
