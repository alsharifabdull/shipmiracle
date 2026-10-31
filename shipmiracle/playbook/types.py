"""The six playbook types (shipmiracle/playbooks/<type>.json) as plain dicts with strict validation. No classes: dicts and helper functions."""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

from .. import SchemaError

TYPES = ("software", "app", "content", "research", "ops", "notes")
STAGES = ("intake", "scope", "plan", "approve", "do", "verify", "review", "deliver", "learn")
ORDER = STAGES[1:]                      # the stages a CR walks through (intake is the open event)
LANES = ("fast", "full")
LENSES = ("correctness", "risk", "design")
LENS_ROLE = {"correctness": "review", "risk": "review", "design": "design"}
ROLE_NAMES = ("scope", "plan", "owner", "build", "test", "review", "design", "lead")
_ROLE_KEYS = ("scope", "plan", "approve", "do", "verify", "review", "deliver", "learn")
_AGENT_KEYS = ("scope", "plan", "do", "verify", "review", "design")
_TOP = {"v", "type", "labels", "roles", "agents", "lane", "fast_limit", "review", "checks", "risk_paths_default", "dep_files", "ui_paths", "skips"}
_REVIEW_KEYS = ("full", "on_risk", "on_ui", "always")
_NAME_RE = re.compile(r"[a-z][a-z0-9-]{0,39}")
_DIR = Path(__file__).resolve().parent.parent / "playbooks"
_cache = {}


def _bad(msg: str):
    raise SchemaError("playbook type: " + msg)


def _strs(v, what, n_max, l_max=200):
    if not isinstance(v, list) or len(v) > n_max or any(not isinstance(x, str) or not 0 < len(x) <= l_max for x in v):
        _bad("%s must be a list of at most %d non-empty strings (<= %d chars)" % (what, n_max, l_max))
    return v


def _int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def validate_type(d, name=None) -> dict:
    """Return `d` when it is a valid type definition, else raise SchemaError. `name` (if given) must equal d["type"]."""
    if not isinstance(d, dict):
        _bad("not an object")
    extra = set(d) - _TOP
    if extra:
        _bad("unknown keys %s" % sorted(extra))
    if d.get("v") != 1 or not _int(d.get("v")):
        _bad("v must be 1")
    if d.get("type") not in TYPES or (name is not None and d.get("type") != name):
        _bad("type must be one of %s%s" % (", ".join(TYPES), "" if name is None else " and equal %s" % name))
    lab = d.get("labels")
    if not isinstance(lab, dict) or set(lab) != set(STAGES) or any(not isinstance(v, str) or not 0 < len(v) <= 20 for v in lab.values()):
        _bad("labels must name exactly the 9 stages with 1-20 char strings")
    roles = d.get("roles")
    if not isinstance(roles, dict) or not set(_ROLE_KEYS) <= set(roles) <= set(_ROLE_KEYS) | {"design"} \
            or any(v not in ROLE_NAMES for v in roles.values()):
        _bad("roles must map the 8 stages (and optionally design) to known roles")
    ag = d.get("agents")
    if not isinstance(ag, dict) or set(ag) != set(_AGENT_KEYS) or any(not isinstance(v, str) or not _NAME_RE.fullmatch(v) for v in ag.values()):
        _bad("agents must name scope, plan, do, verify, review, design")
    lane = d.get("lane")
    if not isinstance(lane, dict) or set(lane) != {"default", "fast_allowed"} or lane["default"] not in LANES \
            or not isinstance(lane["fast_allowed"], bool):
        _bad("lane must be {default: fast|full, fast_allowed: bool}")
    if not lane["fast_allowed"] and lane["default"] != "full":
        _bad("a type without a fast lane must default to full")
    fl = d.get("fast_limit")
    if fl is None:
        if lane["fast_allowed"]:
            _bad("fast_limit is required when the fast lane is allowed")
    else:
        if not isinstance(fl, dict) or set(fl) != {"max_files", "max_lines"} or not _int(fl["max_files"]) or not 1 <= fl["max_files"] <= 10 \
                or not (fl["max_lines"] is None or (_int(fl["max_lines"]) and 1 <= fl["max_lines"] <= 500)):
            _bad("fast_limit must be {max_files 1-10, max_lines 1-500 or null}")
    rv = d.get("review")
    if not isinstance(rv, dict) or set(rv) != set(_REVIEW_KEYS):
        _bad("review must have full, on_risk, on_ui, always")
    for k in _REVIEW_KEYS:
        if not isinstance(rv[k], list) or any(x not in LENSES for x in rv[k]) or len(set(rv[k])) != len(rv[k]):
            _bad("review.%s must be a list of distinct lenses %s" % (k, "/".join(LENSES)))
    if "design" in set(sum(rv.values(), [])) and "design" not in roles:
        _bad("a design lens needs the design role")
    _strs(d.get("checks"), "checks", 12, 60)
    _strs(d.get("risk_paths_default"), "risk_paths_default", 50)
    _strs(d.get("dep_files"), "dep_files", 50, 80)
    _strs(d.get("ui_paths"), "ui_paths", 20)
    sk = d.get("skips")
    if not isinstance(sk, dict) or set(sk) != {"fast"} or not isinstance(sk["fast"], list) or any(x not in ORDER for x in sk["fast"]):
        _bad("skips must be {fast: [stage ids]}")
    return d


def names():
    return list(TYPES)


def load(name: str) -> dict:
    """The validated definition of type `name` (a fresh copy). Raises SchemaError for an unknown name or a damaged file."""
    if name not in TYPES:
        raise SchemaError("playbook type: unknown type %r" % (name if isinstance(name, str) else type(name).__name__))
    d = _cache.get(name)
    if d is None:
        try:
            d = json.loads((_DIR / (name + ".json")).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise SchemaError("playbook type %s: cannot read (%s)" % (name, type(e).__name__))
        validate_type(d, name)
        _cache[name] = d
    return copy.deepcopy(d)


def load_all() -> dict:
    return {n: load(n) for n in TYPES}
