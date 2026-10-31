"""stage_rules(project_dir): the one adapter between the playbook files and the engine/hooks. It merges the type definition with the
trusted playbook config (config.load_trusted), the project's level from config/flow.json (P5: the level is read only there) and the
fast-lane/risk overrides. Cached by the mtimes of playbook.json, the registry and flow.json. Read-only: it logs nothing; the caller
reports `playbook.untrusted` when rules["trust"] == "untrusted"."""
from __future__ import annotations

import copy
import json
import os

from .. import paths, projects, registry, state
from . import config, types

_cache = {}


def _mtime(p):
    try:
        st = os.stat(p)
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def flow_level(project_dir, ws=None) -> str:
    """The gate level for this project from config/flow.json (default strict; anything unreadable or unknown = strict)."""
    ws = ws if ws is not None else paths.workspace_dir()
    try:
        d = json.loads(state.read_bytes_nofollow(os.path.join(str(ws), "config", "flow.json")).decode("utf-8"))
        proj = d.get("projects") if isinstance(d.get("projects"), dict) else {}
        lv = proj.get(os.path.basename(os.path.realpath(str(project_dir))), d.get("default", "strict"))
    except Exception:
        return "strict"
    return lv if lv in config.LEVELS else "strict"


def _registry_entry(pid):
    try:
        return registry.entry(pid)
    except Exception:
        return None


def build_rules(project_dir, cfg, trust, reason, level) -> dict:
    """Rules dict from an effective config (see config.load_trusted) and a level. cfg None -> None."""
    if cfg is None:
        return None
    t = types.load(cfg["type"])
    ov = cfg.get("overrides") or {}
    fl = t["fast_limit"]
    if fl is not None:
        fl = dict(fl, **(ov.get("fast_lane") or {}))
    risk = list(ov.get("risk_paths") or []) + [g for g in t["risk_paths_default"] if g not in (ov.get("risk_paths") or [])]
    ap = "manual" if level == "off" else cfg["autopilot"]
    return {"type": cfg["type"], "project": os.path.basename(os.path.realpath(str(project_dir))), "level": level, "autopilot": ap,
            "trusted": trust == config.TRUSTED, "trust": trust, "reason": reason,
            "labels": t["labels"], "roles": t["roles"], "agents": t["agents"], "lanes": t["lane"], "limits": fl,
            "risk": risk, "ui": t["ui_paths"], "deps": t["dep_files"], "review": t["review"], "lenses": t["review"], "checks": t["checks"],
            "skips": t["skips"], "assets": list(cfg.get("assets") or []), "test_cmd": ov.get("test_cmd"), "lang": (cfg.get("report") or {}).get("lang", "en")}


def main_of(project_dir) -> str:
    """P6: the MAIN project folder for an autopilot worktree <dev>/.worktrees/<p>/<x> (its .git file points into <dev>/<p>/.git and <p> is the
    folder name), else the folder itself. The playbook trust, the registry entry and the flow level of a worktree are those of its main project."""
    pd = os.path.realpath(str(project_dir))
    dev = os.path.realpath(str(paths.dev_dir()))
    root = os.path.join(dev, ".worktrees") + os.sep
    if not pd.startswith(root):
        return pd
    rel = pd[len(root):].split(os.sep)
    if len(rel) != 2:
        return pd
    m = os.path.realpath(str(paths.main_checkout(pd)))
    if m == pd or os.path.dirname(m) != dev or os.path.basename(m) != rel[0]:
        return pd
    return m


def stage_rules(project_dir):
    """The rules for this project, or None when it has no playbook (no file and no registry snapshot). For an autopilot worktree: those of its main
    project (see main_of)."""
    pd = main_of(project_dir)
    pid = projects.project_id(pd)
    ws = paths.workspace_dir()
    key = (pd, _mtime(os.path.join(pd, ".shipmiracle", "playbook.json")), _mtime(registry.path()), _mtime(os.path.join(str(ws), "config", "flow.json")))
    hit = _cache.get(pd)
    if hit is not None and hit[0] == key:
        return copy.deepcopy(hit[1])
    cfg, trust, reason = config.load_trusted(pd, _registry_entry(pid))
    rules = build_rules(pd, cfg, trust, reason, flow_level(pd, ws))
    _cache[pd] = (key, rules)
    return copy.deepcopy(rules)
