"""Project registry: ~/.config/shipmiracle/registry.json (0600). Data about each project that git and the folder cannot tell
(GitHub owner/name, extra remotes, protected, known exceptions). propose() only reads; write_missing() only adds ids that are
not yet present and never overwrites an entry. No consumer in P2. A raw remote URL is never stored (it may carry a token)."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional

from . import NotFound, SchemaError, UsageError
from . import paths, projects, state

GIT = "git"             # seams for tests (never a fake on PATH): the executable and the timeout
TIMEOUT = 5.0
_SCP_RE = re.compile(r"^(?:[^@/\s]+@)?([^:/\s]+):(?!//)(.+)$")

# Per-project exceptions (protected, standard manual, special, exceptions text) are registry DATA: a fresh install has none. The owner's
# set is applied by `apply_seed` from a private file (docs/owner-steps/p8-private-defaults.sh); nothing about specific projects is in this code.
SEED_FIELDS = {"protected": False, "standard": "auto", "special": None, "exceptions": [], "legacy": None}      # an entry field is overwritten by a seed only while it still holds this default


def path() -> Path:
    return paths.config_dir() / "registry.json"


# ---- team fields (Phase 3b): team on|off, standard auto|manual, test_paths, agents {name: {sha256, role, ts}} ----
TEAM_VALUES = ("on", "off")
STANDARD_VALUES = ("auto", "manual")
ROLES = ("project", "workspace", "public-engine")     # P8: who may push where (shipm push-check); absent = project
VISIBILITIES = ("private", "public")
SETTABLE = ("team", "standard", "test_paths", "playbook", "role", "expected_remote", "expected_visibility")
_AGENT_NAME_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
_SHA_RE = re.compile(r"[0-9a-f]{64}")
_ID_RE = re.compile(r"[0-9a-f]{12}")


def default_team_fields() -> dict:
    return {"team": "on", "standard": "auto", "test_paths": [], "agents": {}}


def team_state(entry) -> str:
    """'on' or 'off' for a stored entry (absent or odd value: on, the safe side for the gate)."""
    return "off" if isinstance(entry, dict) and entry.get("team") == "off" else "on"


def activated_sha(entry, name) -> Optional[str]:
    """The sha256 the owner activated for agent `name` in this project entry, or None."""
    a = entry.get("agents") if isinstance(entry, dict) else None
    v = a.get(name) if isinstance(a, dict) else None
    s = v.get("sha256") if isinstance(v, dict) else None
    return s if isinstance(s, str) and _SHA_RE.fullmatch(s) else None


def _test_paths(v) -> List[str]:
    if isinstance(v, str):
        t = v.strip()
        if t.startswith("["):
            try:
                v = json.loads(t)
            except ValueError:
                raise UsageError("test_paths: expected a JSON list or comma-separated globs")
        else:
            v = [x.strip() for x in t.split(",") if x.strip()]
    if not isinstance(v, list) or len(v) > 30:
        raise UsageError("test_paths: expected a list of at most 30 globs")
    out = []
    for g in v:
        if (not isinstance(g, str) or not 0 < len(g) <= 120 or g.startswith("/") or ".." in g.split("/")
                or any(ord(c) < 32 or ord(c) == 127 for c in g)):
            raise UsageError("test_paths: each glob is 1-120 characters, relative, without '..' or control characters")
        out.append(g)
    return out


def _validate(key, value):
    if key == "team":
        if value in TEAM_VALUES:
            return value
        raise UsageError("team: expected on or off")
    if key == "standard":
        if value in STANDARD_VALUES:
            return value
        raise UsageError("standard: expected auto or manual")
    if key == "test_paths":
        return _test_paths(value)
    if key == "playbook":      # P5: {sha256, type, autopilot, overrides} written by `shipm playbook set|init` only (a text value, e.g. from `registry set`, is refused)
        from .playbook import config as pbconfig
        if not isinstance(value, dict) or pbconfig._valid_snapshot(value) is None:
            raise UsageError("playbook: expected a snapshot {sha256, type, autopilot, overrides}; use `shipm playbook set`")
        return json.loads(json.dumps(value))
    if key == "role":
        if value in ("project", "workspace"):
            return value
        raise UsageError("role: expected project or workspace (the public-engine entry is made by `shipm registry add-remote`)")
    if key == "expected_remote":
        r = remote_arg(value)
        if r is None:
            raise UsageError("expected_remote: expected owner/name (GitHub)")
        return r
    if key == "expected_visibility":
        if value in VISIBILITIES:
            return value
        raise UsageError("expected_visibility: expected private or public")
    raise UsageError("only %s can be set (agents are changed with `shipm registry activate`)" % ", ".join(SETTABLE))


def _mutate(what: str, fn, owner: bool = True):
    """Owner-only read-modify-write of registry.json under the lock. fn(registry dict) returns the result; the file is written
    only when fn changed something (it returns (result, changed)). owner=False only for set_autopilot(origin chat), see there."""
    if owner:
        paths.require_owner(what)
    d = paths.config_dir()
    paths.assert_isolated(d)
    state.ensure_dir(d)
    with state.lock_file(d / ".registry.lock"):
        cur = load()
        res, changed = fn(cur)
        if changed:
            state.atomic_write(path(), (json.dumps(cur, sort_keys=True, indent=1) + "\n").encode("utf-8"), 0o600)
        return res


def _entry_of(cur, project_id):
    if not isinstance(project_id, str) or not _ID_RE.fullmatch(project_id):
        raise UsageError("not a project id")
    e = cur["projects"].get(project_id)
    if e is None:
        raise NotFound("project %s is not in the registry (shipm registry sync)" % project_id)
    return e


def set_field(project_id: str, key: str, value) -> None:
    """Owner-only: team | standard | test_paths | playbook (snapshot) for one project."""
    val = _validate(key, value)

    def fn(cur):
        e = _entry_of(cur, project_id)
        changed = e.get(key) != val
        e[key] = val
        return None, changed
    _mutate("registry set", fn)


def autopilot_of(entry):
    """The stored charter record {"charter": {...}, "sha256": ...} of an entry, or None."""
    a = entry.get("autopilot") if isinstance(entry, dict) else None
    return a if isinstance(a, dict) and isinstance(a.get("charter"), dict) and isinstance(a.get("sha256"), str) else None


# ---- P8 T5: role / expected remote (read by `shipm push-check` and `shipm release export --push`) ----
def role_of(entry) -> str:
    """'project' (default), 'workspace' or 'public-engine'. An absent or odd value is 'project'."""
    r = entry.get("role") if isinstance(entry, dict) else None
    return r if r in ROLES else "project"


def expected_remote_of(entry) -> Optional[str]:
    """The normalised remote this entry may push to: expected_remote, else the remote found at sync time; None = unknown."""
    if not isinstance(entry, dict):
        return None
    for k in ("expected_remote", "remote"):
        v = entry.get(k)
        if isinstance(v, str) and v:
            n = normalise_remote(v) or v
            return n
    return None


def remote_arg(value) -> Optional[str]:
    """A remote typed by the owner -> normalised owner/name (GitHub) or file://... (SHIPMIRACLE_TEST=1 only); None when it is neither.
    A bare owner/name is read as GitHub."""
    if not isinstance(value, str):
        return None
    v = value.strip()
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9._-]+", v):
        v = "https://github.com/" + v
    n = normalise_remote(v)
    if n is None:
        return None
    if n.startswith("file://"):
        return n
    return n if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9._-]+", n) else None      # github.com only (host/owner/name is refused)


def public_engine_id(remote: str) -> str:
    return hashlib.sha256(("shipmiracle-public-engine:" + remote).encode("utf-8")).hexdigest()[:12]


def public_engines(reg=None) -> List[dict]:
    """Entries whose role is public-engine, each as {"id", "entry", "remote"} (remote = normalised expected remote)."""
    reg = load() if reg is None else reg
    out = []
    for i, e in sorted(reg["projects"].items()):
        if role_of(e) == "public-engine":
            out.append({"id": i, "entry": e, "remote": expected_remote_of(e)})
    return out


def add_remote_only(role: str, remote, visibility) -> str:
    """Owner-only: register the remote-only public-engine entry (no path, no folder). Exactly one may exist: the same remote again is a
    no-op, another remote is refused. Returns the entry id."""
    if role != "public-engine":
        raise UsageError("add-remote: the only role is public-engine")
    r = remote_arg(remote)
    if r is None:
        raise UsageError("add-remote: --remote must be owner/name on GitHub")
    if visibility not in VISIBILITIES:
        raise UsageError("add-remote: --visibility must be private or public")
    i = public_engine_id(r)

    def fn(cur):
        for pid, e in cur["projects"].items():
            if role_of(e) == "public-engine":
                if pid == i and e.get("expected_visibility") == visibility:
                    return i, False
                if pid != i:
                    raise UsageError("a public-engine entry already exists; run `shipm registry forget <id>` first")
        cur["projects"][i] = {"name": "public-engine", "remote": r, "extra_remotes": [], "visibility": None, "type": None,
                              "protected": True, "special": None, "exceptions": [], "role": "public-engine",
                              "expected_remote": r, "expected_visibility": visibility}
        return i, True
    return _mutate("registry add-remote", fn)


def set_autopilot(project_id: str, value, owner: bool = True) -> None:
    """The one writer of the `autopilot` (charter) field; it is NOT in SETTABLE, so `shipm registry set` can never write it. Only
    shipmiracle.autopilot.charter calls this (CLI: owner=True, refused inside a chat; the UserPromptSubmit hook passes owner=False after it
    verified the trusted prompt: the hook runs inside the chat's environment, where require_owner would refuse). value = {"charter",
    "sha256"} validated by the charter module (sha recomputed), or None to clear."""
    if value is not None:
        from .autopilot import charter as _charter
        _charter.validate_record(value)
        value = json.loads(json.dumps(value))

    def fn(cur):
        e = _entry_of(cur, project_id)
        if value is None:
            had = "autopilot" in e
            e.pop("autopilot", None)
            return None, had
        if isinstance(value.get("charter"), dict) and value["charter"].get("until") == "disabled":          # m3: one standing charter per machine, checked inside the same lock as the write
            for q, other in (cur.get("projects") or {}).items():
                o = autopilot_of(other)
                if q != project_id and o is not None and o["charter"].get("until") == "disabled":
                    raise UsageError("only one project can run until you disable it: another project already has such a charter (stop it first)")
        changed = e.get("autopilot") != value
        e["autopilot"] = value
        return None, changed
    _mutate("autopilot charter", fn, owner=owner)


def set_admitted(project_id: str, admitted, owner: bool = True) -> None:
    """Owner-only writer of the admissions beside a standing charter: record["admitted"] (outside the charter sha). Only `shipm autopilot admit` /
    drop / the engine's pruning call it; the charter record must exist."""
    from .autopilot import charter as _charter
    val = _charter.clean_admitted(admitted)

    def fn(cur):
        e = _entry_of(cur, project_id)
        rec = e.get("autopilot")
        if not isinstance(rec, dict) or not isinstance(rec.get("charter"), dict):
            raise UsageError("no charter to attach admissions to")
        if rec.get("admitted", []) == val:
            return None, False
        if val:
            rec["admitted"] = val
        else:
            rec.pop("admitted", None)
        return None, True
    _mutate("autopilot admit", fn, owner=owner)


def activate(project_id: str, name: str, sha256: str, role: str, ts: Optional[int] = None) -> None:
    """Owner-only: record that the owner trusts the agent file `name` with this exact content hash in this project."""
    if not isinstance(name, str) or not _AGENT_NAME_RE.fullmatch(name):
        raise UsageError("not an agent name")
    if not isinstance(sha256, str) or not _SHA_RE.fullmatch(sha256):
        raise UsageError("not a sha256")
    if not isinstance(role, str) or not re.fullmatch(r"[a-z]{1,16}", role):
        raise UsageError("not a role")
    t = int(time.time()) if ts is None else int(ts)

    def fn(cur):
        e = _entry_of(cur, project_id)
        a = e.get("agents")
        if not isinstance(a, dict):
            a = e["agents"] = {}
        new = {"sha256": sha256, "role": role, "ts": t}
        old = a.get(name)
        if isinstance(old, dict) and old.get("sha256") == sha256 and old.get("role") == role:
            return None, False
        a[name] = new
        return None, True
    _mutate("registry activate", fn)


def forget(project_id: str) -> bool:
    """Owner-only: remove a project's entry (delete-project). False when it was not there."""
    if not isinstance(project_id, str) or not _ID_RE.fullmatch(project_id):
        raise UsageError("not a project id")

    def fn(cur):
        had = project_id in cur["projects"]
        cur["projects"].pop(project_id, None)
        return had, had
    return _mutate("registry forget", fn)


def sync(project_list=None, dev=None) -> dict:
    """Owner-only: add the projects that are not in the registry and fill the team fields that are missing in existing entries
    (a stored value is never changed). Returns {"added": [ids], "filled": [ids]}."""
    prop = propose(project_list, dev)

    def fn(cur):
        added, filled = [], []
        for i in sorted(prop["projects"]):
            if i not in cur["projects"]:
                cur["projects"][i] = prop["projects"][i]; added.append(i)
                continue
            e = cur["projects"][i]
            miss = [k for k in default_team_fields() if k not in e]
            if miss:
                for k in miss:
                    e[k] = prop["projects"][i].get(k, default_team_fields()[k])
                filled.append(i)
        return {"added": added, "filled": filled}, bool(added or filled)
    return _mutate("registry sync", fn)


def _empty() -> dict:
    return {"v": 1, "projects": {}}


def load() -> dict:
    """The stored registry {"v":1,"projects":{id: entry}}; an absent file is empty. SchemaError when damaged."""
    p = path()
    try:
        raw = state.read_bytes_nofollow(p)
    except FileNotFoundError:
        return _empty()
    try:
        d = json.loads(raw.decode("utf-8"))
    except ValueError:
        raise SchemaError("registry.json is not valid JSON")
    if not isinstance(d, dict) or d.get("v") != 1 or not isinstance(d.get("projects"), dict) \
            or any(not isinstance(e, dict) for e in d["projects"].values()):
        raise SchemaError("registry.json has an unexpected shape")
    return d


def entry(project_id: str) -> Optional[dict]:
    """The stored entry for an id, or None."""
    e = load()["projects"].get(project_id)
    return json.loads(json.dumps(e)) if e is not None else None


def normalise_remote(url) -> Optional[str]:
    """owner/name for github.com (https, ssh://, scp-style, with or without .git or credentials); other hosts: host/owner/name;
    anything that is not a remote URL (a local path, junk): None."""
    if not isinstance(url, str):
        return None
    u = url.strip()
    if not u or "\x00" in u or "\n" in u:
        return None
    if u.lower().startswith("file:///"):               # tests only (SHIPMIRACLE_TEST=1): a local bare repo stands in for the remote; the realpath is the identity
        if os.environ.get("SHIPMIRACLE_TEST") != "1" or "?" in u or "#" in u or "%" in u:
            return None
        return "file://" + os.path.realpath("/" + u[8:].lstrip("/")).rstrip("/")
    host = rest = None
    m = re.match(r"^[a-z][a-z0-9+.-]*://([^/]+)/(.+)$", u, re.I)
    if m:
        # the authority ends at the first '/'; credentials end at its LAST '@' ('user:p@ss@host' has the password 'p@ss')
        auth = m.group(1).rsplit("@", 1)[-1]
        hm = re.fullmatch(r"([^:@\s]+)(?::\d+)?", auth)
        if not hm:
            return None
        host, rest = hm.group(1), m.group(2)
    else:
        m = _SCP_RE.match(u)
        if m and not u.startswith(("/", ".", "~")):
            host, rest = m.group(1), m.group(2)
    if host and "@" in host:
        return None
    if not host or not rest:
        return None
    rest = rest.strip("/")
    if rest.endswith(".git"):
        rest = rest[:-4]
    parts = [s for s in rest.split("/") if s]
    if len(parts) < 2 or any(not re.fullmatch(r"[A-Za-z0-9._-]+", s) or s in (".", "..") for s in parts):
        return None
    on = "/".join(parts)                        # GitLab-style subgroups (g/s/r) stay intact
    return on if host.lower() in ("github.com", "www.github.com") and len(parts) == 2 else "%s/%s" % (host.lower(), on)


def _git_remotes(project_path: str) -> List[tuple]:
    """[(remote name, url)] from `git -C <path> config --get-regexp ^remote\\..*\\.url$`; argv list, no shell, TIMEOUT seconds.
    A timeout, a missing git or a failure gives []."""
    argv = [GIT] + projects.GIT_PREFIX[1:] + ["-C", project_path, "config", "--get-regexp", r"^remote\..*\.url$"]
    try:
        r = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                           timeout=TIMEOUT, shell=False, env=projects.git_env())
    except (OSError, subprocess.SubprocessError):
        return []
    if r.returncode != 0:
        return []
    out = []
    for line in r.stdout.decode("utf-8", "replace").split("\n"):
        key, _, url = line.partition(" ")
        m = re.fullmatch(r"remote\.(.+)\.url", key)
        if m and url.strip():
            out.append((m.group(1), url.strip()))
    return out


def _entry_for(p) -> dict:
    remotes = _git_remotes(p.path)
    origin = next((u for n, u in remotes if n == "origin"), None)
    e = {
        "name": p.name,
        "remote": normalise_remote(origin) if origin else None,
        "extra_remotes": sorted(
            ({"name": n, "remote": normalise_remote(u)} for n, u in remotes if n != "origin"), key=lambda x: x["name"]),
        "visibility": None,
        "type": None,
        "protected": False,
        "special": None,
        "exceptions": [],
    }
    e.update(default_team_fields())
    return e


def _seed_value(key, v):
    if key == "protected" and isinstance(v, bool):
        return v
    if key == "standard" and v in STANDARD_VALUES:
        return v
    if key == "special" and (v is None or (isinstance(v, str) and 0 < len(v) <= 40)):
        return v
    if key == "exceptions" and isinstance(v, list) and len(v) <= 20 and all(isinstance(x, str) and 0 < len(x) <= 300 for x in v):
        return list(v)
    if key == "legacy" and (v is None or _legacy_ok(v)):
        return v if v is None else {k: (list(x) if isinstance(x, list) else x) for k, x in v.items()}
    raise UsageError("seed: invalid value for %s" % key)


def _legacy_ok(v) -> bool:
    """The playbook migration row of a project (data from the private seed): {type, level, risk_paths, order, keep_level?}."""
    return (isinstance(v, dict) and set(v) <= {"type", "level", "risk_paths", "order", "keep_level"}
            and isinstance(v.get("type"), str) and 0 < len(v["type"]) <= 40 and v.get("level") in ("strict", "warn", "off")
            and isinstance(v.get("risk_paths"), list) and len(v["risk_paths"]) <= 30
            and all(isinstance(x, str) and 0 < len(x) <= 200 for x in v["risk_paths"])
            and isinstance(v.get("order"), int) and not isinstance(v.get("order"), bool) and 0 <= v["order"] < 1000
            and isinstance(v.get("keep_level", False), bool))


def legacy_table(reg=None) -> list:
    """[(name, type, level, risk_paths, keep_level)] of the registry entries that carry a `legacy` row, in their order. Empty by default."""
    reg = load() if reg is None else reg
    rows = [(e["legacy"]["order"], str(e.get("name")), e["legacy"]) for e in reg["projects"].values()
            if isinstance(e.get("legacy"), dict) and _legacy_ok(e["legacy"]) and isinstance(e.get("name"), str)]
    return [(n, l["type"], l["level"], list(l["risk_paths"]), bool(l.get("keep_level", False))) for _, n, l in sorted(rows, key=lambda r: (r[0], r[1]))]


def seed_plan(seed: dict, reg=None, dev=None) -> List[dict]:
    """What `apply_seed` would do, as [{"name", "id", "new": bool, "set": {field: value}}] (read-only). A seed is
    {project name: {protected, standard, special, exceptions}}; only projects that exist under the projects folder count."""
    if not isinstance(seed, dict):
        raise UsageError("seed must be an object {project name: {field: value}}")
    for name, fields in seed.items():
        if not isinstance(fields, dict):
            raise UsageError("seed: %s must be an object" % name)
        for k, v in fields.items():
            if k in SEED_FIELDS:
                _seed_value(k, v)
    reg = load() if reg is None else reg
    out = []
    for p in projects.list_projects(dev):
        if p.name not in seed:
            continue
        ent = reg["projects"].get(p.id)
        base = ent if ent is not None else _entry_for(p)
        sets = {k: _seed_value(k, v) for k, v in seed[p.name].items()
                if k in SEED_FIELDS and base.get(k, SEED_FIELDS[k]) == SEED_FIELDS[k] and _seed_value(k, v) != base.get(k)}
        if ent is None or sets:
            out.append({"name": p.name, "id": p.id, "new": ent is None, "set": sets})
    return out


def apply_seed(seed: dict, dev=None) -> List[str]:
    """Owner-only: for each project NAME in `seed` that exists under the projects folder, add its registry entry when missing and set each
    seeded field that still holds its default (SEED_FIELDS); a field the owner changed is never overwritten. Unknown fields and names not
    found are ignored. Returns the ids changed. Idempotent."""
    seed_plan(seed, _empty(), dev)                       # validates the seed (UsageError) before the lock is taken
    plist = {p.id: p for p in projects.list_projects(dev)}

    def fn(cur):
        plan = seed_plan(seed, cur, dev)
        for it in plan:
            ent = cur["projects"].get(it["id"])
            if ent is None:
                ent = cur["projects"][it["id"]] = _entry_for(plist[it["id"]])
            ent.update(it["set"])
        return [it["id"] for it in plan], bool(plan)
    return _mutate("registry apply-seed", fn)


def propose(project_list=None, dev=None) -> dict:
    """{"v":1,"projects":{id: entry}} for the given projects (default: all). Reads git; writes nothing."""
    plist = projects.list_projects(dev) if project_list is None else list(project_list)
    return {"v": 1, "projects": {p.id: _entry_for(p) for p in plist}}


def write_missing(proposal: dict) -> List[str]:
    """Add the proposal's ids that are not in the stored registry; existing entries are never touched. Returns the added ids.
    A damaged stored file raises SchemaError and is left as it is."""
    if not isinstance(proposal, dict) or not isinstance(proposal.get("projects"), dict):
        raise UsageError("proposal must be {'v':1,'projects':{...}}")
    paths.require_owner("shipm registry write")
    d = paths.config_dir()
    paths.assert_isolated(d)
    state.ensure_dir(d)
    with state.lock_file(d / ".registry.lock"):
        cur = load()
        added = [i for i in sorted(proposal["projects"]) if i not in cur["projects"]]
        if not added:
            return []
        for i in added:
            cur["projects"][i] = proposal["projects"][i]
        state.atomic_write(path(), (json.dumps(cur, sort_keys=True, indent=1) + "\n").encode("utf-8"), 0o600)
        return added
