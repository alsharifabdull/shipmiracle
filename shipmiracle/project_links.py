"""Project links (G11): which project's chat may read (or write) another project's folder. The owner's list lives in <config>/project-links.json (0600, atomic, under
the config lock): {"v":1,"links":[{"from","to","mode","from_name","to_name","ts"}]}. `from` and `to` are projects.project_id of the REAL path, so a renamed or moved folder
drops its link (fail closed). One direction per link, mode read (default) or write (includes read). The workspace (hub) is never a target and a link never opens secrets
(the flow gate judges the secret table first). Owner only: paths.require_owner refuses inside a Claude Code chat; the flow gate's admin set refuses `shipm projects link|unlink`.
The flow gate reads the file itself (stdlib only, <= 64 KB, damaged = no links + event isolation_links_unreadable)."""
from __future__ import annotations

import json
import time
from typing import List

from . import NotFound, SchemaError, UsageError
from . import paths, projects, state

MAX_LINKS = 50
MODES = ("read", "write")


def path():
    return paths.config_dir() / "project-links.json"


def load() -> List[dict]:
    """The stored links (validated rows only). A missing file is []; a damaged one raises SchemaError."""
    p = path()
    if not p.exists():
        return []
    raw = p.read_bytes()
    if len(raw) > 65536:
        raise SchemaError("project-links.json is larger than 64 KB")
    try:
        j = json.loads(raw.decode("utf-8"))
    except ValueError:
        raise SchemaError("project-links.json is not valid JSON")
    if not isinstance(j, dict) or j.get("v") != 1 or not isinstance(j.get("links"), list):
        raise SchemaError("project-links.json has an unexpected shape")
    rows = []
    for r in j["links"]:
        if isinstance(r, dict) and isinstance(r.get("from"), str) and isinstance(r.get("to"), str) and r.get("mode") in MODES:
            rows.append(r)
    return rows


def _save(rows: List[dict]) -> None:
    state.atomic_write(path(), (json.dumps({"v": 1, "links": rows}, sort_keys=True, indent=1) + "\n").encode("utf-8"), 0o600)


def _mutate(what: str, fn):
    paths.require_owner(what)
    d = paths.config_dir()
    paths.assert_isolated(d)
    state.ensure_dir(d)
    with state.lock_file(d / ".project-links.lock"):
        try:
            cur = load()
        except SchemaError:
            cur = []                                  # a damaged list is replaced by the owner's new link (nothing in it can be trusted)
        res, changed = fn(cur)
        if changed:
            _save(cur)
        return res


def _project(name: str):
    p = projects.get(name)
    if p is None:
        raise NotFound("%s is not a listed project (see `shipm projects`)" % name)
    return p


def link(a: str, b: str, mode: str = "read") -> str:
    """Let project `a`'s chat reach project `b`. Returns a one-line description."""
    if mode not in MODES:
        raise UsageError("mode must be read or write")
    pa, pb = _project(a), _project(b)
    if pa.id == pb.id:
        raise UsageError("a project cannot be linked to itself")
    if pb.hub:
        raise UsageError("the workspace is never a link target: project chats read its tools and standards without a link and never write it")

    def fn(rows):
        for r in rows:
            if r["from"] == pa.id and r["to"] == pb.id:
                if r["mode"] == mode:
                    return "already linked: %s -> %s (%s)" % (pa.name, pb.name, mode), False
                r["mode"] = mode; r["ts"] = int(time.time())
                return "changed: %s -> %s now %s" % (pa.name, pb.name, mode), True
        if len(rows) >= MAX_LINKS:
            raise UsageError("at most %d links" % MAX_LINKS)
        rows.append({"from": pa.id, "to": pb.id, "mode": mode, "from_name": pa.name, "to_name": pb.name, "ts": int(time.time())})
        return "linked: %s -> %s (%s)" % (pa.name, pb.name, mode), True
    return _mutate("shipm projects link", fn)


def unlink(a: str, b: str) -> str:
    pa, pb = _project(a), _project(b)

    def fn(rows):
        keep = [r for r in rows if not (r["from"] == pa.id and r["to"] == pb.id)]
        if len(keep) == len(rows):
            return "no link: %s -> %s" % (pa.name, pb.name), False
        rows[:] = keep
        return "unlinked: %s -> %s" % (pa.name, pb.name), True
    return _mutate("shipm projects unlink", fn)


def rows() -> List[dict]:
    """Every stored link with `stale`: True when one of its two ids no longer names a listed project (renamed, moved or deleted folder: the link does nothing)."""
    ids = {p.id for p in projects.list_projects()}
    out = []
    for r in load():
        out.append({"from": r["from"], "to": r["to"], "mode": r["mode"], "from_name": r.get("from_name", ""), "to_name": r.get("to_name", ""), "ts": r.get("ts", 0),
                    "stale": r["from"] not in ids or r["to"] not in ids})
    return out
