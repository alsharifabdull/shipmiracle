"""The agents layer (Platform v2 P3b): ten function roles kept in agents/claude/ (the masters), installed by `shipm agents install` as real
copies in ~/.claude/agents with a sha manifest in <state>/v1/agents.json; a resolver (project > user > plugin > builtin/alias) with a
trust rule for privileged role claims; the agent-file lint (`check`); team moves (`migrate_team`, `vendor`, `activate`); doctor rows.

Trust: a file's claim of a privileged role (plan, test, review, report) counts only when its sha256 is the one Shipmiracle installed for that
name (manifest), one of the last five committed versions of the OLD master of that name (manifest "legacy", until P5), or the one the
owner activated for this project (registry). Otherwise the effective role is `support`. A claim can only RESTRICT: a file that claims a
read-only role is treated as read-only even when untrusted.
Owner-only writers (install, uninstall, vendor, activate, migrate_team) refuse inside a Claude Code chat (paths.require_owner)."""
from __future__ import annotations

import collections
import hashlib
import json
import os
import re
import stat
import subprocess
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional

from . import ShipmiracleError, NotFound, SafetyError, SchemaError, UsageError
from . import config, paths, projects, registry, state

MANIFEST = "agents.json"
WRITER = "shipmiracle-agents"
LEGACY_EXPIRES = "P5"
MAX_FILE = 256 * 1024
GIT_TIMEOUT = 15.0

ROLES = {"plan", "build", "test", "review", "scope", "design", "route", "support", "report"}
PRIVILEGED = {"plan", "test", "review", "report"}
READ_ONLY = {"scope", "plan", "review", "report"}
DRAFT_ROLES = {"build", "design", "scope", "support"}
MAX_ACTIVE = 12

# Old master name -> new role (resolution only; no alias agent files are installed). Copies live in legacy flow-gate.sh and
# vscode-ext/shipmiracle-panel/data.js (a test keeps the three equal).
ALIASES = {
    "product-analyst": "scoper",
    "solution-architect": "planner",
    "frontend-engineer": "builder-frontend",
    "backend-engineer": "builder-backend",
    "data-integration-engineer": "builder-backend",
    "devops-sre": "builder-ops",
    "qa-engineer": "verifier",
    "independent-reviewer": "reviewer",
    "security-reviewer": "reviewer",
    "ux-designer": "designer",
}
ALIAS_LENS = {"independent-reviewer": "correctness", "security-reviewer": "risk"}
LEGACY_NAMES = sorted(list(ALIASES) + ["engineering-lead"])
DEFAULT_ROLE = {
    "scoper": "scope", "planner": "plan", "builder": "build", "builder-frontend": "build", "builder-backend": "build",
    "builder-ops": "build", "verifier": "test", "reviewer": "review", "designer": "design", "reporter": "report",
    "general-purpose": "build", "Plan": "plan", "Explore": "scope", "claude-code-guide": "support", "statusline-setup": "support",
    "engineering-lead": "route",
}
BUILTINS = {"general-purpose", "Plan", "Explore", "claude-code-guide", "statusline-setup", "engineering-lead"}
LAYERS = ("project", "user", "plugin", "builtin", "alias")

_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_PLUGIN_RE = re.compile(r"([A-Za-z0-9][A-Za-z0-9._-]{0,63}):([A-Za-z0-9][A-Za-z0-9._-]{0,127})")
_KEBAB_RE = re.compile(r"[a-z][a-z0-9]*(-[a-z0-9]+)*")
_SHA_RE = re.compile(r"[0-9a-f]{64}")


# ------------------------------------------------------------------ small helpers
def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _read_file(path) -> Optional[bytes]:
    """Content of a regular file (symlinks followed, as Claude Code does), at most MAX_FILE bytes; None when absent/unreadable/too big."""
    try:
        with open(str(path), "rb") as f:
            b = f.read(MAX_FILE + 1)
    except OSError:
        return None
    return b if len(b) <= MAX_FILE else None


_NAME_LIKE = re.compile(r"^[ \t]*(?:\?[ \t]*)?['\"]?name['\"]?[ \t]*:", re.M)    # anything that could be read as a `name` key
_NAME_STRICT = re.compile(r"name: (['\"]?)([a-z][a-z0-9]*(?:-[a-z0-9]+)*)\1")
_LINE_BREAKS = "\r\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029"            # YAML or Python may split a line here; a name line must not hide behind one


def name_scan(text: str) -> dict:
    """Fail-closed reading of the frontmatter name (P3 remediation B1). {"ok": bool, "name": str|None, "cands": set, "unknown": bool}.
    ok: no name-like line at all (name None) or EXACTLY ONE line `name: <kebab>` (value optionally single/double-quoted, one space, nothing else).
    Any other form (quoted key, `name :`, comment, block scalar, duplicate key, tab, CR, BOM, flow mapping, line-break tricks) is not ok:
    `cands` then holds the names Claude Code could read from it (loose reading) and `unknown` says a value could not be read at all."""
    bom = text.startswith("\ufeff")
    t = text.lstrip("\ufeff")
    m = re.match(r"---\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|$)", t, re.S)
    region = m.group(1) if m else t
    lines = region.split("\n")
    idx = [i for i, ln in enumerate(lines) if _NAME_LIKE.match(ln)]
    bad = bom or (m is None and bool(idx))
    unknown = False
    if m is not None and (any(c in region.replace("\r\n", "\n") for c in _LINE_BREAKS) or re.match(r"\s*\{", region)
                          or re.search(r"^<<[ \t]*:", region, re.M)):
        bad = unknown = True
    cands = set()
    strict = None
    for i in idx:
        ln = lines[i]
        sm = _NAME_STRICT.fullmatch(ln)
        if sm and len(idx) == 1 and not bad:
            strict = sm.group(2)
        else:
            bad = True
        km = _NAME_LIKE.match(ln)
        v = ln[km.end():].strip(" \t\r")
        if v[:1] in (">", "|"):
            v = next((x.strip() for x in lines[i + 1:] if x.strip()), "")
        elif v[:1] in ("'", '"'):
            e = v.find(v[0], 1)
            v = v[1:e] if e > 0 else v[1:]
        else:
            v = re.split(r"[ \t]#", v, 1)[0].strip()
        v = v.strip().strip("'\"").strip()
        if v and _NAME_RE.fullmatch(v) and "\\" not in v:
            cands.add(v)
        else:
            unknown = True
    if bad and idx and not cands:
        unknown = True
    return {"ok": not bad, "name": strict if not bad else None, "cands": cands, "unknown": unknown}


def _norm_name(v) -> Optional[str]:
    """Kept for callers: the strict kebab name of a bare value, else None (no quote stripping tricks)."""
    if not isinstance(v, str):
        return None
    m = re.fullmatch(r"(['\"]?)([a-z][a-z0-9]*(?:-[a-z0-9]+)*)\1", v.strip())
    return m.group(2) if m else None


def parse(text: str) -> dict:
    """Frontmatter keys (top-level `key: value`, inline or block lists for skills/tools) plus the lines the flow rules use.
    {"fm": {key: str}, "skills": [...], "tools": [...], "model", "reason", "role", "max_turns", "overrides", "vendored", "body"}."""
    ns = name_scan(text)                              # on the raw text: a BOM is itself a reason not to trust the name
    text = text.lstrip("\ufeff")                      # a byte-order mark must not hide the frontmatter
    m = re.match(r"---\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|$)", text, re.S)
    fm_text, body = (m.group(1), text[m.end():]) if m else ("", text)
    fm: Dict[str, str] = {}
    lists: Dict[str, List[str]] = {}
    cur = None
    for ln in fm_text.splitlines():
        km = re.match(r"([A-Za-z][\w-]*):[ \t]*(.*)$", ln)
        if km:
            cur = km.group(1)
            fm[cur] = km.group(2).strip()
            if fm[cur] == "":
                lists[cur] = []
            continue
        lm = re.match(r"\s+-\s+(.+)$", ln)
        if lm and cur in lists:
            lists[cur].append(lm.group(1).strip().strip("'\""))

    def as_list(key):
        if key in lists and lists[key]:
            return lists[key]
        v = fm.get(key, "")
        if v.startswith("[") and v.endswith("]"):
            v = v[1:-1]
        return [x.strip().strip("'\"") for x in v.split(",") if x.strip()]
    mm = re.search(r"^model:[ \t]*(\S+)", text, re.M)
    rr = re.search(r"^Flow role:[ \t]*(\w+)", text, re.M)
    tt = re.search(r"^maxTurns:[ \t]*(\S+)", text, re.M)
    return {"fm": fm, "skills": as_list("skills"), "tools": as_list("tools"), "model": mm.group(1) if mm else None,
            "reason": bool(re.search(r"^Model reason:[ \t]*\S", text, re.M)), "role": rr.group(1).lower() if rr else None,
            "max_turns": tt.group(1) if tt else None, "overrides": fm.get("overrides") or None,
            "vendored": fm.get("vendored") or None, "name": ns["name"], "name_ok": ns["ok"], "name_cands": ns["cands"],
            "name_unknown": ns["unknown"], "body": body}


def user_dir(home=None) -> Path:
    return Path(home if home is not None else paths.home()) / ".claude" / "agents"


def masters_dir(ws=None) -> Path:
    return Path(ws if ws is not None else paths.workspace_dir()) / "agents" / "claude"


def _names_in(d) -> List[str]:
    try:
        return sorted(f[:-3] for f in os.listdir(str(d)) if f.endswith(".md") and not f.startswith(".") and _NAME_RE.fullmatch(f[:-3]))
    except OSError:
        return []


# ------------------------------------------------------------------ config / registry views
def layout() -> str:
    """config agents.layout: 'legacy' (default; copies in each project) or 'userlevel'."""
    return config.get("agents.layout")


def project_gated(pd) -> bool:
    """True when the project has a registry entry whose team is not off (the userlevel gate activation). Raises SchemaError when
    the registry is damaged (the caller decides)."""
    p = projects.resolve(str(pd)) if pd else None
    if p is None:
        return False
    e = registry.entry(p.id)
    return e is not None and registry.team_state(e) == "on"


def _project_entry(pd) -> Optional[dict]:
    if not pd:
        return None
    try:
        return registry.entry(projects.project_id(pd))
    except ShipmiracleError:
        return None


def manifest() -> Optional[dict]:
    """The install manifest (data part) or None when shipm agents install never ran. Damaged files raise SchemaError/SafetyError."""
    try:
        d = state.read(MANIFEST)["data"]
    except NotFound:
        return None
    if not isinstance(d, dict) or not isinstance(d.get("agents"), dict):
        raise SchemaError("agents.json has an unexpected shape")
    return d


def _manifest_soft() -> dict:
    """The manifest for trust decisions: any problem means 'nothing is trusted' (fail closed)."""
    try:
        return manifest() or {}
    except (ShipmiracleError, OSError):
        return {}


# ------------------------------------------------------------------ plugin agents / skills (read-only views of the plugin cache)
def _plugin_cache(home=None) -> Path:
    return Path(home if home is not None else paths.home()) / ".claude" / "plugins" / "cache"


_PA_MEMO: dict = {}


def plugin_agents(home=None) -> Dict[str, List[str]]:
    """{bare agent name: [plugin, ...]} from ~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/agents/*.md (memoised by the
    cache folder's mtime)."""
    root = _plugin_cache(home)
    try:
        key = (str(root), os.stat(str(root)).st_mtime_ns)
    except OSError:
        return {}
    if key in _PA_MEMO:
        return _PA_MEMO[key]
    out: Dict[str, List[str]] = collections.defaultdict(list)
    try:
        for mk in sorted(os.listdir(str(root))):
            for pl in sorted(os.listdir(str(root / mk))):
                seen = set()
                for ver in sorted(os.listdir(str(root / mk / pl))):
                    for n in _names_in(root / mk / pl / ver / "agents"):
                        if n not in seen:
                            seen.add(n)
                            out[n].append(pl)
    except OSError:
        pass
    _PA_MEMO.clear()
    _PA_MEMO[key] = dict(out)
    return _PA_MEMO[key]


def _plugin_skill_exists(plugin, skill, home=None) -> bool:
    root = _plugin_cache(home)
    try:
        for mk in os.listdir(str(root)):
            pd = root / mk / plugin
            for ver in (os.listdir(str(pd)) if pd.is_dir() else []):
                if (pd / ver / "skills" / skill).is_dir():
                    return True
    except OSError:
        pass
    return False


def skill_exists(name, project_dir=None, home=None) -> bool:
    """A `skills:` name exists as a folder under the project's or the user's .claude/skills, or is a plugin skill (plugin:skill).
    Claude Code itself ignores an absent skill silently (probe P3-4), so this is the only place it is noticed."""
    if not isinstance(name, str) or not name:
        return False
    pm = _PLUGIN_RE.fullmatch(name)
    if pm:
        return _plugin_skill_exists(pm.group(1), pm.group(2), home)
    if not _NAME_RE.fullmatch(name):
        return False
    roots = [Path(home if home is not None else paths.home()) / ".claude" / "skills"]
    if project_dir:
        roots.insert(0, Path(project_dir) / ".claude" / "skills")
    return any((r / name).is_dir() for r in roots)


# ------------------------------------------------------------------ resolver
def _scan(d) -> List[dict]:
    """Every agent file of a folder: [{"stem", "name" (frontmatter name or None), "key" (name or stem), "data"}], sorted by file name.
    Claude Code identifies an agent by its frontmatter `name:`, not by the file name, so the resolver works on `key`."""
    out = []
    try:
        fns = sorted(f for f in os.listdir(str(d)) if f.endswith(".md") and not f.startswith("."))
    except OSError:
        return out
    for fn in fns:
        data = _read_file(Path(d) / fn)
        if data is None:
            continue
        info = parse(data.decode("utf-8", "replace"))
        nm = info["name"]
        names = {nm or fn[:-3]} if info["name_ok"] else (set(info["name_cands"]) | {fn[:-3]})
        out.append({"stem": fn[:-3], "name": nm, "key": nm or fn[:-3], "data": data, "path": str(Path(d) / fn),
                    "ok": info["name_ok"], "names": names, "unknown": info["name_unknown"]})
    return out


@dataclass
class Resolved:
    name: str
    path: Optional[str]
    layer: str                  # project | user | plugin | builtin | alias
    sha256: Optional[str]
    claimed: str
    effective: str
    trusted: bool
    overrides: Optional[str] = None
    model: Optional[str] = None
    alias_of: Optional[str] = None
    lens: Optional[str] = None
    readonly: bool = False      # claimed or effective role is read-only (a claim can only restrict)
    shadow: bool = False        # a master-named project file without `overrides:` that is not an exact master copy
    mismatch: bool = False      # the frontmatter name differs from the file name (or is missing)
    duplicate: bool = False     # another file of the same layer carries the same frontmatter name

    def as_dict(self) -> dict:
        return asdict(self)


def _trusted_shas(name, mf, entry) -> set:
    out = set()
    a = (mf.get("agents") or {}).get(name)
    if isinstance(a, dict) and isinstance(a.get("sha256"), str):
        out.add(a["sha256"])
    lg = (mf.get("legacy") or {}).get(name)
    if isinstance(lg, list):
        out.update(x for x in lg if isinstance(x, str))
    s = registry.activated_sha(entry, name)
    if s:
        out.add(s)
    return out


def _all_master_names(mf) -> set:
    return set(mf.get("agents") or {}) | (set(DEFAULT_ROLE) - BUILTINS) | set(ALIASES) | {"engineering-lead"}


def _from_file(name, layer, stem, path, data, mf, entry, duplicate=False, collides=False, name_ok=True) -> Resolved:
    text = data.decode("utf-8", "replace")
    info = parse(text)
    sha = sha256_bytes(data)
    claimed = info["role"] if info["role"] in ROLES else DEFAULT_ROLE.get(name, "support")
    mismatch = (not name_ok) or info["name"] != stem     # a non-strict name line (B1) counts as a mismatch; # a file `fake-qa.md` that says `name: verifier` is identified as `verifier` by Claude Code
    trusted = (not mismatch) and (not duplicate) and sha in _trusted_shas(name, mf, entry)
    effective = claimed if (claimed not in PRIVILEGED or trusted) else "support"
    shadow = False
    if layer == "project" and not info["overrides"]:
        exact = sha in _trusted_shas(name, mf, None)
        shadow = mismatch or duplicate or ((name in _all_master_names(mf) or collides) and not exact)
    return Resolved(name=name, path=str(path), layer=layer, sha256=sha, claimed=claimed, effective=effective, trusted=trusted,
                    overrides=info["overrides"], model=info["model"], readonly=(claimed in READ_ONLY or effective in READ_ONLY),
                    shadow=shadow, mismatch=mismatch, duplicate=duplicate)


def _pick(entries, name):
    """(entry, duplicate) for the files of one layer whose frontmatter name is `name`; the one named like its file is preferred."""
    c = [e for e in entries if name in e["names"]]
    if not c:
        return None, False
    c.sort(key=lambda e: (e["stem"] != name, e["stem"]))
    return c[0], len(c) > 1


def _tainted(entries, name, layer, mf, entry):
    """B1 fail-closed: a file whose name line cannot be read (`unknown`) might be ANY agent. For a name that could carry a privileged role
    the answer is that file, untrusted, so the role falls to support."""
    t = next((e for e in entries if e["unknown"]), None)
    if t is None:
        return None
    if not (name in _all_master_names(mf) or DEFAULT_ROLE.get(ALIASES.get(name, name)) in PRIVILEGED):
        return None
    claimed = DEFAULT_ROLE.get(ALIASES.get(name, name), "support")
    return Resolved(name=name, path=t["path"], layer=layer, sha256=sha256_bytes(t["data"]), claimed=claimed, effective="support" if claimed in PRIVILEGED else claimed,
                    trusted=False, readonly=claimed in READ_ONLY, shadow=layer == "project", mismatch=True)


def resolve(name, project_dir=None, home=None) -> Optional[Resolved]:
    """Where an agent type comes from. Order: project file > user file > plugin (`plugin:name` only; bare names are ambiguous, probe P3-5)
    > builtin / alias. The same name is never merged across layers. None when nothing matches."""
    if not isinstance(name, str) or len(name) > 192 or "\x00" in name:
        return None
    mf = _manifest_soft()
    entry = _project_entry(project_dir)
    if _NAME_RE.fullmatch(name):
        user = _scan(user_dir(home))
        if project_dir:
            pe = _scan(Path(project_dir) / ".claude" / "agents")
            e, dup = _pick(pe, name)
            if e is not None:
                return _from_file(name, "project", e["stem"], e["path"], e["data"], mf, entry, dup, any(name in u["names"] for u in user), e["ok"])
            tr = _tainted(pe, name, "project", mf, entry)
            if tr is not None:
                return tr
        e, dup = _pick(user, name)
        if e is not None:
            return _from_file(name, "user", e["stem"], e["path"], e["data"], mf, entry, dup, False, e["ok"])
        tr = _tainted(user, name, "user", mf, entry)
        if tr is not None:
            return tr
    pm = _PLUGIN_RE.fullmatch(name)
    if pm:
        if pm.group(1) in plugin_agents(home).get(pm.group(2), []):
            return Resolved(name=name, path=None, layer="plugin", sha256=None, claimed="support", effective="support", trusted=False)
        return None
    if name in ALIASES:
        target = ALIASES[name]
        r = DEFAULT_ROLE[target]
        return Resolved(name=name, path=None, layer="alias", sha256=None, claimed=r, effective=r, trusted=True, alias_of=target,
                        lens=ALIAS_LENS.get(name), readonly=r in READ_ONLY)
    if name in BUILTINS or name in DEFAULT_ROLE:
        r = DEFAULT_ROLE.get(name, "support")
        return Resolved(name=name, path=None, layer="builtin", sha256=None, claimed=r, effective=r, trusted=True, readonly=r in READ_ONLY)
    return None


def list_agents(project_dir=None, home=None) -> List[Resolved]:
    """Every agent file visible to a project (its own files and the user-level ones), resolved; sorted by name."""
    names = {e["key"] for e in _scan(user_dir(home))}
    if project_dir:
        names |= {e["key"] for e in _scan(Path(project_dir) / ".claude" / "agents")}
    names = {n for n in names if _NAME_RE.fullmatch(n)}
    out = [resolve(n, project_dir, home) for n in sorted(names)]
    return [r for r in out if r is not None]


# ------------------------------------------------------------------ check (the lint)
Problem = collections.namedtuple("Problem", "file kind text")
# kinds: model (model rule, exit 1) | lint (draft/master rules, exit 1) | dod (DoD block / maxTurns, exit 3) | warn (skills, shadow, count, ambiguity: exit 3)
_TAG = {"model": "", "lint": "[lint] ", "dod": "[dod] ", "warn": "[warn] "}


def _file_problems(f, text, mode) -> List[Problem]:
    """The rules every agent file follows (the same as bin/agent-check had): model rule, Flow role vocabulary, DoD block, maxTurns."""
    out: List[Problem] = []
    info = parse(text)
    why = []
    if info["model"] not in ("opus", "sonnet", "haiku"):
        why.append("model is %s (use opus, sonnet or haiku)" % (info["model"] or "missing"))
    if not info["reason"]:
        why.append("no 'Model reason:' line")
    if info["role"] not in ROLES:
        why.append("no valid 'Flow role:' line (" + " | ".join(sorted(ROLES)) + ")")
    if why:
        out.append(Problem(f, "model", "; ".join(why)))
    dod = []
    if not re.search(r"^##\s+DoD\b", text, re.M) or not re.search(r"^Verdict:\s*\S", text, re.M):
        dod.append("no '## DoD' section with a 'Verdict:' line")
    if info["role"] != "route":
        if info["max_turns"] is None or not re.fullmatch(r"[1-9]\d*", info["max_turns"]):
            dod.append("maxTurns is %s (use a whole number)" % (info["max_turns"] or "missing"))
    if dod:
        out.append(Problem(f, "dod", "; ".join(dod)))
    return out


def _common_lints(f, stem, text, mode, mf, count_other) -> List[Problem]:
    """draft / master rules (spec section 3.4)."""
    info = parse(text)
    lint = []
    name = info["name"]
    if not info["name_ok"]:
        lint.append("the name line must be exactly one 'name: <kebab-name>' line (no quotes around the key, no comment, no block scalar, no duplicate)")
    elif not name or not _KEBAB_RE.fullmatch(name):
        lint.append("name must be kebab-case (lowercase words joined by '-')")
    elif name != stem:
        lint.append("name '%s' differs from the file name '%s.md'" % (name, stem))
    desc = info["fm"].get("description", "")
    if not desc:
        lint.append("no description")
    else:
        if len(desc) > 400:
            lint.append("description is %d characters (at most 400)" % len(desc))
        if "Use when" not in desc or "Not for" not in desc:
            lint.append("description needs 'Use when ...' and 'Not for ...'")
        if re.search(r":\s", desc) or re.search(r"\s#", desc):
            lint.append("description contains ': ' or ' #' (breaks the frontmatter)")
    if "Agent" in info["tools"] or "Task" in info["tools"]:
        lint.append("tools must not include Agent (agents do not start agents)")
    for k in ("hooks", "mcpServers", "permissionMode"):
        if k in info["fm"]:
            lint.append("'%s' is not allowed in an agent file" % k)
    if mode == "draft":
        if info["role"] not in DRAFT_ROLES:
            lint.append("Flow role must be one of: %s (invited agents never plan, test, review or report)" % ", ".join(sorted(DRAFT_ROLES)))
        if info["max_turns"] is None:
            lint.append("maxTurns is required")
        if name and name in _all_master_names(mf) and not info["overrides"]:
            lint.append("'%s' is a master name: add an 'overrides: %s' line or pick another name" % (name, name))
        if count_other + 1 > MAX_ACTIVE:
            lint.append("more than %d active agents (%d with this one)" % (MAX_ACTIVE, count_other + 1))
    if mode == "master" and info["overrides"]:
        lint.append("a master must not carry 'overrides:'")
    return [Problem(f, "lint", t) for t in lint]


def check_file(path, mode="file", project_dir=None, home=None) -> List[Problem]:
    """Problems of one agent file. mode: file (model rule + DoD/maxTurns, what bin/agent-check always did), draft (an invited agent in
    .claude/agents-drafts/), master (a file in agents/claude/), project (a file in a project's .claude/agents, with the extra project
    rules: skills exist, no unmarked master-name shadow, no plugin-name collision)."""
    f = str(path)
    data = _read_file(path)
    if data is None:
        return []                       # the old tool skipped unreadable files silently (OSError)
    text = data.decode("utf-8", "ignore")
    out = _file_problems(f, text, mode)
    stem = os.path.basename(f)[:-3] if f.endswith(".md") else os.path.basename(f)
    info = parse(text)
    mf = _manifest_soft() if mode in ("draft", "project") else {}
    if mode in ("draft", "master"):
        other = 0
        if mode == "draft":
            others = [e for e in _scan(user_dir(home)) + (_scan(Path(project_dir) / ".claude" / "agents") if project_dir else [])
                      if os.path.realpath(e["path"]) != os.path.realpath(f)]
            names = {e["key"] for e in others}
            other = len(names)
            if info["name"] and info["name"] in names and not info["overrides"]:
                out.append(Problem(f, "lint", "another agent already uses the name '%s' (add 'overrides: %s' to replace it on purpose)" % (info["name"], info["name"])))
        out += _common_lints(f, stem, text, mode, mf, other)
    if mode in ("master", "draft", "project"):
        for s in info["skills"]:
            if not skill_exists(s, project_dir, home):
                out.append(Problem(f, "warn", "skill '%s' is named in skills: but is not installed (Claude Code ignores it silently)" % s))
        pa = plugin_agents(home)
        nm = info["name"] or stem
        if nm in pa and mode in ("draft", "project"):
            out.append(Problem(f, "warn", "'%s' is also a bare plugin agent name (%s); plugin agents resolve only as <plugin>:%s" % (nm, ", ".join(pa[nm]), nm)))
    if mode == "project":
        nm = info["name"]
        key = nm or stem
        if not info["name_ok"]:
            out.append(Problem(f, "warn", "the name line is not exactly 'name: <kebab-name>' (quoted key, comment, block scalar, duplicate, tab, CR or BOM): this agent file is untrusted and so is every privileged role claim for its name in this project"))
        elif nm != stem:
            out.append(Problem(f, "warn", "frontmatter name %s differs from the file name '%s.md': Claude Code identifies this agent as '%s'; it is untrusted and a privileged role claim is ignored" % (
                "'%s'" % nm if nm else "is missing", stem, key)))
        sibs = [e for e in _scan(Path(f).parent) if e["key"] == key and os.path.realpath(e["path"]) != os.path.realpath(f)]
        if sibs:
            out.append(Problem(f, "warn", "another file in this folder also has the name '%s' (%s); both are untrusted" % (key, ", ".join(e["stem"] + ".md" for e in sibs))))
        r = resolve(key, project_dir, home)
        if r is not None and r.layer == "project" and r.shadow and r.path and os.path.realpath(r.path) == os.path.realpath(f) and not (nm != stem or sibs):
            out.append(Problem(f, "warn", "unmarked shadow of '%s': add 'overrides: %s' (until then its privileged role claim is not trusted)" % (key, key)))
    return out


def check(target, mode=None, project_dir=None, home=None) -> List[Problem]:
    """Problems for a file, a folder of agent files, or (project_dir=...) a whole project team.
    check(path) -> file mode for a file; folders and projects are checked file by file; a project also gets the whole-team rules
    (more than 12 active agents)."""
    out: List[Problem] = []
    if project_dir is not None and target is None:
        ad = Path(project_dir) / ".claude" / "agents"
        ents = _scan(ad)
        for e in ents:
            out += check_file(e["path"], "project", project_dir, home)
        total = {e["key"] for e in ents} | {e["key"] for e in _scan(user_dir(home))}
        if len(total) > MAX_ACTIVE:
            out.append(Problem(str(ad), "warn", "%d active agents (at most %d)" % (len(total), MAX_ACTIVE)))
        return out
    t = Path(target)
    if t.is_dir():
        for e in _scan(t):
            out += check_file(e["path"], mode or "file", project_dir, home)
        return out
    return check_file(t, mode or "file", project_dir, home)


def exit_code(problems) -> int:
    kinds = {p.kind for p in problems}
    return 1 if kinds & {"model", "lint"} else 3 if kinds & {"dod", "warn"} else 0


def format_problems(problems) -> List[str]:
    """Lines in bin/agent-check's format: `file: problem; problem` for the model rule, `file: [dod] ...` for DoD/maxTurns, and
    `[lint]` / `[warn]` for the stricter modes."""
    return ["%s: %s%s" % (p.file, _TAG[p.kind], p.text) for p in problems]


# ------------------------------------------------------------------ git helpers
def _git(argv, cwd, text=True, timeout=GIT_TIMEOUT):
    try:
        r = subprocess.run(projects.GIT_PREFIX + argv, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           timeout=timeout, shell=False, env=projects.git_env())
    except (OSError, subprocess.SubprocessError):
        return 1, b"" if not text else ""
    return r.returncode, (r.stdout.decode("utf-8", "replace") if text else r.stdout)


def masters_head(ws) -> str:
    """Last commit that touched agents/claude (the 'masters HEAD'), '' when unknown."""
    rc, out = _git(["log", "-1", "--format=%H", "--", "agents/claude"], str(ws))
    return out.strip() if rc == 0 else ""


LEGACY_CUTOFF = "2630f3292cacd038edd5cbfd7e6cca52589ffb50"     # parent of the P3b commit (8fab959) that replaced the old masters; the frozen set was read at this commit
LEGACY_FILE = Path(__file__).resolve().parent / "legacy_hashes.json"


def legacy_hashes(ws=None, keep=5, skip=()) -> Dict[str, List[str]]:
    """{old master name: [sha256 of its last 5 committed versions as of LEGACY_CUTOFF]}. P3 remediation: a FROZEN set shipped in
    shipmiracle/legacy_hashes.json (generated once with `git log LEGACY_CUTOFF -- agents/claude/<old>.md`); never read from the live history, so a
    later commit to agents/claude cannot poison trust. `ws` and `keep` are kept for callers and ignored. Names in `skip` are left out."""
    try:
        raw = json.loads(LEGACY_FILE.read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    out: Dict[str, List[str]] = {}
    for old in LEGACY_NAMES:
        v = raw.get(old) if isinstance(raw, dict) else None
        if old in skip or not isinstance(v, list):
            continue
        shas = [h for h in v if isinstance(h, str) and _SHA_RE.fullmatch(h)]
        if shas:
            out[old] = shas
    return out


# ------------------------------------------------------------------ install / uninstall
def _guard_real_claude_dir(home) -> None:
    """Under SHIPMIRACLE_TEST=1 refuse to touch the real ~/.claude (tests use a temp HOME)."""
    if os.environ.get("SHIPMIRACLE_TEST") != "1":
        return
    real = os.path.realpath(str(paths.real_home() / ".claude"))
    cand = os.path.realpath(str(Path(home) / ".claude"))
    if paths.fold(cand) == paths.fold(real) or paths.fold(cand).startswith(paths.fold(real).rstrip("/") + "/"):
        raise SafetyError("test run refused to touch the real folder %s" % real)


def _require_main_checkout(ws) -> None:
    mc = paths.main_checkout(ws)
    if os.path.realpath(str(mc)) != os.path.realpath(str(ws)):
        raise SafetyError("run this from the main checkout %s, not from a worktree" % mc)


def _read_masters(ws) -> Dict[str, bytes]:
    """The masters as files of the working tree."""
    md = masters_dir(ws)
    out = {}
    for n in _names_in(md):
        b = _read_file(md / (n + ".md"))
        if b is not None:
            out[n] = b
    return out


def _is_git_repo(ws) -> bool:
    rc, top = _git(["rev-parse", "--show-toplevel"], str(ws))
    return rc == 0 and os.path.realpath(top.strip()) == os.path.realpath(str(ws))


def _masters_committed(ws) -> Optional[Dict[str, bytes]]:
    """The masters as committed in HEAD (git show HEAD:agents/claude/<f>), or None when that cannot be read."""
    rc, names = _git(["ls-tree", "--name-only", "HEAD", "agents/claude/"], str(ws))
    if rc != 0:
        return None
    out = {}
    for rel in [x for x in names.split("\n") if x.endswith(".md")]:
        rc2, blob = _git(["show", "HEAD:" + rel], str(ws), text=False)
        if rc2 != 0:
            return None
        n = os.path.basename(rel)[:-3]
        if _NAME_RE.fullmatch(n) and len(blob) <= MAX_FILE:
            out[n] = blob
    return out


def _masters_dirty(ws) -> List[str]:
    rc, out = _git(["status", "--porcelain", "--", "agents/claude"], str(ws))
    return [x[3:] for x in out.split("\n") if x.strip()] if rc == 0 else []


def _masters_ok(masters, home) -> None:
    import tempfile
    with tempfile.TemporaryDirectory(prefix="shipmiracle-masters-") as td:
        for n, b in masters.items():
            Path(td, n + ".md").write_bytes(b)
        probs = [p for p in check(td, "master", None, home) if p.kind in ("model", "lint", "dod")]
    if probs:
        raise UsageError("the masters do not pass `shipm agents check --master` (%d problem(s)); first: %s" % (len(probs), format_problems(probs[:1])[0].replace(td, "agents/claude")))


def _agent_meta(data: bytes) -> dict:
    info = parse(data.decode("utf-8", "replace"))
    return {"sha256": sha256_bytes(data), "role": info["role"], "model": info["model"]}


def _diff(old: Optional[bytes], new: bytes, name: str, limit=40) -> str:
    import difflib
    a = (old or b"").decode("utf-8", "replace").splitlines()
    b = new.decode("utf-8", "replace").splitlines()
    lines = list(difflib.unified_diff(a, b, "installed/" + name + ".md" if old is not None else "/dev/null", "master/" + name + ".md", lineterm="", n=1))
    return "\n".join(lines[:limit] + (["... (%d more lines)" % (len(lines) - limit)] if len(lines) > limit else []))


def _plan_install(masters, home) -> dict:
    ud = user_dir(home)
    old = _manifest_soft()
    oldagents = old.get("agents") or {}
    actions = []
    new_agents = {}
    for n, data in sorted(masters.items()):
        sha = sha256_bytes(data)
        dst = ud / (n + ".md")
        try:
            lst = os.lstat(str(dst))
        except FileNotFoundError:
            actions.append({"name": n, "action": "install", "why": "new"}); new_agents[n] = _agent_meta(data); continue
        cur = _read_file(dst) if stat.S_ISREG(lst.st_mode) else None
        if cur is not None and sha256_bytes(cur) == sha:
            actions.append({"name": n, "action": "same", "why": "already current"}); new_agents[n] = _agent_meta(data); continue
        mine = oldagents.get(n, {}).get("sha256") if isinstance(oldagents.get(n), dict) else None
        if stat.S_ISLNK(lst.st_mode) or cur is None:
            actions.append({"name": n, "action": "keep", "why": "not a regular file, not touched"})
        elif mine and sha256_bytes(cur) == mine:
            actions.append({"name": n, "action": "update", "why": "installed by Shipmiracle, unchanged by hand"}); new_agents[n] = _agent_meta(data)
        elif mine:
            actions.append({"name": n, "action": "keep", "why": "changed by hand, kept"})
            new_agents[n] = oldagents[n]
        else:
            actions.append({"name": n, "action": "keep", "why": "a file of that name exists that Shipmiracle did not install, not touched"})
    for n, meta in sorted(oldagents.items()):
        if n in masters or not isinstance(meta, dict):
            continue
        dst = ud / (n + ".md")
        cur = _read_file(dst)
        if cur is None:
            actions.append({"name": n, "action": "forget", "why": "no longer a master and already gone"})
        elif sha256_bytes(cur) == meta.get("sha256"):
            actions.append({"name": n, "action": "remove", "why": "no longer a master, unchanged by hand"})
        else:
            actions.append({"name": n, "action": "keep", "why": "no longer a master but changed by hand, kept"})
            new_agents[n] = meta
    return {"actions": actions, "agents": new_agents, "masters": masters}


def install(dry_run=False, ws=None, home=None, allow_dirty=False) -> dict:
    """Copy the masters to ~/.claude/agents as real files (0644, atomic) and write the manifest. Never touches a file Shipmiracle did not
    install; removes a managed file only while it is unchanged; idempotent. Owner only; main checkout only (dry runs are free).
    The masters are read from the COMMITTED blobs (HEAD) when the workspace is a git repo; uncommitted changes in agents/claude refuse the
    install unless allow_dirty (then the working tree is used). The result carries a `diff` of every changed master and `warnings`."""
    ws = Path(ws if ws is not None else paths.workspace_dir())
    home = Path(home if home is not None else paths.home())
    if not dry_run:
        paths.require_owner("shipm agents install")
        _require_main_checkout(ws)
        _guard_real_claude_dir(home)
        paths.assert_isolated(paths.state_dir())
    warnings = []
    if _is_git_repo(ws):
        dirty = _masters_dirty(ws)
        if dirty and not allow_dirty:
            raise UsageError("agents/claude has uncommitted changes (%s): commit them, or pass --allow-dirty to install the working tree" % ", ".join(dirty[:4]))
        masters = _read_masters(ws) if dirty else _masters_committed(ws)
        if masters is None:
            raise UsageError("cannot read the masters from git (HEAD:agents/claude)")
        if dirty:
            warnings.append("installing the UNCOMMITTED working tree (--allow-dirty)")
        rc, sh = _git(["rev-parse", "--is-shallow-repository"], str(ws))
        if rc == 0 and sh.strip() == "true":
            warnings.append("shallow clone: the history is incomplete, the legacy hash set may be missing versions")
    else:
        masters = _read_masters(ws)
        warnings.append("not a git repository: no legacy hash set can be read (old-name project copies will not be trusted)")
    if not masters:
        raise NotFound("no masters in %s" % masters_dir(ws))
    readded = [o for o in LEGACY_NAMES if o in masters or (masters_dir(ws) / (o + ".md")).exists()]
    for o in readded:
        warnings.append("old-name file agents/claude/%s.md is present: it is treated as a master and its history is NOT trusted as legacy" % o)
    _masters_ok(masters, home)
    plan = _plan_install(masters, home)
    plan["masters"] = masters
    legacy = legacy_hashes(ws, skip=readded)
    diff = []
    for a in plan["actions"]:
        if a["action"] in ("install", "update"):
            cur = _read_file(user_dir(home) / (a["name"] + ".md")) if a["action"] == "update" else None
            diff.append(_diff(cur, masters[a["name"]], a["name"]))
    prev_lg = _manifest_soft().get("legacy") or {}
    ldiff = ["%s: %s %s" % (k, sign, h[:12]) for k in sorted(set(prev_lg) | set(legacy))
             for sign, hs in (("+", [h for h in legacy.get(k, []) if h not in (prev_lg.get(k) or [])]), ("-", [h for h in (prev_lg.get(k) or []) if h not in legacy.get(k, [])]))
             for h in hs if isinstance(h, str)]
    res = {"dry_run": bool(dry_run), "actions": plan["actions"], "legacy_diff": ldiff, "ws": os.path.realpath(str(ws)), "ws_sha": masters_head(ws),
           "legacy": {k: len(v) for k, v in sorted(legacy.items())}, "warnings": warnings, "diff": "\n".join(d for d in diff if d)}
    if dry_run:
        return res
    ud = user_dir(home)
    if ud.is_symlink():
        raise SafetyError("%s is a symlink" % ud)
    os.makedirs(str(ud), 0o755, exist_ok=True)
    with state.locked("agents-install"):
        for a in plan["actions"]:
            n, act = a["name"], a["action"]
            dst = ud / (n + ".md")
            try:
                if act in ("install", "update"):
                    state.atomic_write(dst, plan["masters"][n], 0o644)
                elif act == "remove":
                    os.unlink(str(dst))
            except (OSError, SafetyError) as e:
                a["action"], a["why"] = "keep", "could not write (%s), kept" % type(e).__name__
                plan["agents"].pop(n, None)
        merged = {k: list(v) for k, v in sorted(legacy.items())}     # exactly the frozen set: nothing from an earlier manifest or the live history is merged in
        data = {"v": 1, "installed": int(time.time()), "ws": res["ws"], "ws_sha": res["ws_sha"], "agents": plan["agents"],
                "legacy": merged, "legacy_expires": LEGACY_EXPIRES}
        state.write(MANIFEST, data, WRITER)
    return res


def uninstall(home=None) -> dict:
    """Remove the files Shipmiracle installed (only while unchanged) and the manifest. Owner only."""
    home = Path(home if home is not None else paths.home())
    paths.require_owner("shipm agents uninstall")
    _guard_real_claude_dir(home)
    paths.assert_isolated(paths.state_dir())
    mf = manifest()
    if mf is None:
        raise NotFound("nothing installed (no agents manifest)")
    actions = []
    with state.locked("agents-install"):
        for n, meta in sorted(mf["agents"].items()):
            dst = user_dir(home) / (n + ".md")
            cur = _read_file(dst)
            if cur is None:
                actions.append({"name": n, "action": "gone", "why": "already absent"})
            elif isinstance(meta, dict) and sha256_bytes(cur) == meta.get("sha256"):
                try:
                    os.unlink(str(dst)); actions.append({"name": n, "action": "remove", "why": "unchanged"})
                except OSError as e:
                    actions.append({"name": n, "action": "keep", "why": "could not remove (%s)" % type(e).__name__})
            else:
                actions.append({"name": n, "action": "keep", "why": "changed by hand, kept"})
        state.delete(MANIFEST, WRITER)
    return {"actions": actions}


# ------------------------------------------------------------------ projects: lookup, activate, vendor, migrate
def project_for(arg):
    """A registered project from a name (under the Developer folder), a folder path, or an id. NotFound otherwise."""
    if not arg or not isinstance(arg, str):
        raise UsageError("a project name or folder is needed")
    cand = None
    if os.sep in arg or arg.startswith((".", "~")):
        cand = projects.resolve(os.path.abspath(os.path.expanduser(arg)))
    else:
        cand = projects.get(arg)
        if cand is None:
            for p in projects.list_projects():
                if p.id == arg:
                    cand = p
    if cand is None:
        raise NotFound("no project %s" % arg)
    return cand


def activate(project, name, confirm_role=None) -> dict:
    """Owner only: trust the agent file `name` of this project as it is now (its sha256 goes to the registry). A file waiting in
    .claude/agents-drafts/ must pass the draft check and is moved into .claude/agents/ afterwards. A file that claims a PRIVILEGED role
    (plan, test, review, report) is activated only with confirm_role equal to that claim; without it the refusal shows the role, the path,
    the sha256 and the first 20 lines, so one short command is never enough to give an unreviewed file the test or review role."""
    paths.require_owner("shipm agents activate")
    p = project_for(project)
    if not isinstance(name, str) or not _KEBAB_RE.fullmatch(name):
        raise UsageError("not an agent name")
    live = Path(p.path) / ".claude" / "agents" / (name + ".md")
    draft = Path(p.path) / ".claude" / "agents-drafts" / (name + ".md")
    src, from_draft = (live, False) if live.is_file() else (draft, True) if draft.is_file() else (None, False)
    if src is None:
        raise NotFound("no agent file %s (nor a draft)" % live)
    data = _read_file(src)
    if data is None:
        raise NotFound("cannot read %s" % src)
    info = parse(data.decode("utf-8", "replace"))
    if info["name"] != name:
        raise UsageError("not activated: the frontmatter name is %s, not '%s' (Claude Code identifies the agent by that name)" % (
            "'%s'" % info["name"] if info["name"] else "missing", name))
    if not from_draft and sum(1 for e in _scan(live.parent) if e["key"] == name) > 1:
        raise UsageError("not activated: more than one file in %s has the name '%s'" % (live.parent, name))
    probs = [x for x in check_file(src, "draft" if from_draft else "file", p.path) if x.kind in ("model", "lint", "dod") or (not from_draft and x.kind == "model")]
    if from_draft and probs:
        raise UsageError("the draft does not pass the check: " + format_problems(probs[0:1])[0])
    if not from_draft:
        probs = [x for x in probs if x.kind == "model"]
        if probs:
            raise UsageError("not activated, the file breaks the model rule: " + format_problems(probs[0:1])[0])
    meta = _agent_meta(data)
    if meta["role"] not in ROLES:
        raise UsageError("not activated: no valid 'Flow role:' line")
    if meta["role"] in PRIVILEGED and confirm_role != meta["role"]:
        head = "\n".join(data.decode("utf-8", "replace").splitlines()[:20])
        raise UsageError("this file claims the privileged role '%s'. Read it, then repeat the command with --confirm-role %s\n"
                         "  file:   %s\n  sha256: %s\n  first 20 lines:\n%s" % (meta["role"], meta["role"], src, meta["sha256"], head))
    moved = False
    if from_draft:
        os.makedirs(str(live.parent), exist_ok=True)
        if live.exists():
            raise SafetyError("%s already exists" % live)
        os.replace(str(draft), str(live)); moved = True
    registry.activate(p.id, name, meta["sha256"], meta["role"])
    return {"project": p.name, "name": name, "sha256": meta["sha256"], "role": meta["role"], "moved": moved}


def _stamp(data: bytes, name, ws_sha) -> bytes:
    """A master's bytes with `overrides: <name>` and `vendored: <ws_sha>` added to the frontmatter (before the closing line)."""
    text = data.decode("utf-8")
    m = re.match(r"(---\r?\n.*?)(\r?\n---[ \t]*(?:\r?\n|$))", text, re.S)
    if not m:
        raise UsageError("master %s has no frontmatter" % name)
    return (m.group(1) + "\noverrides: %s\nvendored: %s" % (name, ws_sha or "unknown") + text[m.end(1):]).encode("utf-8")


def _git_clean(path, rel) -> bool:
    rc, out = _git(["status", "--porcelain", "--", rel], str(path))
    return rc == 0 and out.strip() == ""


def _git_guard(path) -> Optional[str]:
    """Why a commit into this project must not happen now, or None: detached HEAD, a branch other than main / master / the remote's
    default, or a merge / rebase / cherry-pick / revert in progress."""
    rc, br = _git(["symbolic-ref", "-q", "--short", "HEAD"], str(path))
    br = br.strip()
    if rc != 0 or not br:
        return "HEAD is detached (check out the main branch, then run again)"
    rc, dflt = _git(["symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD"], str(path))
    allowed = {"main", "master"} | ({dflt.strip().split("/", 1)[-1]} if rc == 0 and dflt.strip() else set())
    if br not in allowed:
        return "branch '%s' is not the main branch (%s); switch to it, then run again" % (br, "/".join(sorted(allowed)))
    for x in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply"):
        rc, gp = _git(["rev-parse", "--git-path", x], str(path))
        if rc == 0 and gp.strip() and os.path.exists(os.path.join(str(path), gp.strip())):
            return "a merge / rebase / cherry-pick / revert is in progress (%s); finish or abort it first" % x
    return None


def _commit(path, rels, message) -> bool:
    """Commit exactly `rels` (explicit pathspecs that have changes); the project's pre-commit hook is skipped (a .claude-only change, no
    records), its post-commit hook (auto-push) still runs. True when a commit was made."""
    env = projects.git_env()
    run = lambda argv: subprocess.run(["git", "-C", str(path)] + argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,   # noqa: E731
                                      stderr=subprocess.PIPE, env=env, timeout=GIT_TIMEOUT)
    for r in rels:
        run(["add", "-A", "--", r])                          # a pathspec that matches nothing (an untracked, removed folder) is fine
    names = [x for x in run(["diff", "--cached", "--name-only", "--"] + rels).stdout.decode("utf-8", "replace").split("\n") if x]
    if not names:
        return False
    r = run(["commit", "-q", "--no-verify", "-m", message, "--"] + names)
    if r.returncode != 0:
        raise SafetyError("git commit failed: " + r.stderr.decode("utf-8", "replace").strip()[:200])
    return True


def vendor(project=None, all_projects=False, ws=None) -> List[dict]:
    """Rollback: copy the current masters into the project's .claude/agents with `overrides:` and `vendored:` markers, record their
    hashes in the registry (so their role claims stay trusted) and commit. Never overwrites an unmarked modified file or a marked
    override. Owner only."""
    paths.require_owner("shipm agents vendor")
    ws = Path(ws if ws is not None else paths.workspace_dir())
    masters = _read_masters(ws)
    if not masters:
        raise NotFound("no masters in %s" % masters_dir(ws))
    ws_sha = masters_head(ws)
    if all_projects:
        plist = [p for p in projects.list_projects() if not p.symlink]
    else:
        plist = [project_for(project)]
    mf = _manifest_soft()
    reports = []
    for p in plist:
        rep = {"project": p.name, "written": [], "kept": [], "skipped": None, "committed": False}
        ad = Path(p.path) / ".claude" / "agents"
        if not _git_clean(p.path, ".claude/agents"):
            rep["skipped"] = ".claude/agents has uncommitted changes"; reports.append(rep); continue
        why = _git_guard(p.path)
        if why:
            rep["skipped"] = why; reports.append(rep); continue
        os.makedirs(str(ad), exist_ok=True)
        before = {}
        for n, data in sorted(masters.items()):
            dst = ad / (n + ".md")
            before[dst] = _read_file(dst)
            new = _stamp(data, n, ws_sha)
            cur = _read_file(dst)
            if cur is not None and cur == new:
                rep["written"].append(n); continue
            if cur is not None:
                info = parse(cur.decode("utf-8", "replace"))
                ok_to_replace = info["vendored"] or sha256_bytes(cur) in _trusted_shas(n, mf, None)
                if not ok_to_replace:
                    rep["kept"].append((n, "a modified file of that name, kept")); continue
            state.atomic_write(dst, new, 0o644)
            rep["written"].append(n)
        if rep["written"] and registry.entry(p.id) is None:
            registry.sync([p])
        for n in rep["written"]:
            d = _read_file(ad / (n + ".md"))
            meta = _agent_meta(d)
            registry.activate(p.id, n, meta["sha256"], meta["role"])
        try:
            rep["committed"] = _commit(p.path, [".claude/agents"], "Team vendored from AI-Workspace (rollback copy of the user-level team)")
        except (SafetyError, OSError, subprocess.SubprocessError) as e:
            for f, b in before.items():                     # the commit failed: restore what was there
                if b is None:
                    f.unlink() if f.exists() else None
                else:
                    state.atomic_write(f, b, 0o644)
            rep["skipped"] = "commit failed, files restored: %s" % e
        reports.append(rep)
    return reports


def copy_state(name, path) -> str:
    """How a project's file `path` for master `name` relates to the masters: absent | override (carries `overrides:`: the project's own,
    never replaced) | exact (a trusted older copy of the master: manifest or legacy hash) | modified (anything else)."""
    data = _read_file(path)
    if data is None:
        return "absent"
    if parse(data.decode("utf-8", "replace"))["overrides"]:
        return "override"
    return "exact" if sha256_bytes(data) in _trusted_shas(name, _manifest_soft(), None) else "modified"


def remove_legacy_copies(project_dir, dry_run=False) -> List[str]:
    """Delete the old-name agent files of a project whose sha256 is one of the last committed versions of that old master (manifest
    legacy set). Exact copies only; a modified file is never touched. Used by apply-template in the legacy layout. Returns the names."""
    legacy = _manifest_soft().get("legacy") or {}
    ad = Path(project_dir) / ".claude" / "agents"
    gone = []
    for n in LEGACY_NAMES:
        f = ad / (n + ".md")
        data = _read_file(f) if f.is_file() and not f.is_symlink() else None
        if data is not None and sha256_bytes(data) in set(legacy.get(n) or []):
            if not dry_run:
                os.unlink(str(f))
            gone.append(n)
    return gone


def chats_open(name) -> Optional[int]:
    """Open chats of a project from the watcher's health.json (legacy authority); None when the state is missing, old (> 15 min) or
    unreadable. The caller treats None as 'cannot confirm' and skips (fail closed)."""
    try:
        h = json.loads(state.read_bytes_nofollow(paths.state_dir() / "health.json").decode("utf-8"))
        c = (h.get("chats") or {}).get(name)
        if not isinstance(c, dict) or time.time() - float(h.get("ts") or 0) > 900:
            return None
        return int(c.get("chats") or 0)
    except (OSError, ValueError, TypeError, ShipmiracleError, AttributeError):
        return None


def migrate_team(project, apply=False, drop_backups=False, home=None) -> dict:
    """Move a project from its own team copies to the user-level team. Dry run unless apply. Deletes only project files whose sha256 is
    an exact master copy (manifest) or an old master version (legacy); keeps modified and project-only agents. Skips (reports) when a
    chat is open or cannot be confirmed, when .claude has uncommitted changes, or when the user-level team is not installed intact.
    Commit message: 'Team moved to user level'. Owner only (also the dry run: it reads the watcher)."""
    paths.require_owner("shipm project migrate-team")
    home = Path(home if home is not None else paths.home())
    p = project_for(project)
    rep = {"project": p.name, "apply": bool(apply), "removed": [], "kept": [], "skipped": None, "committed": False, "backups_dropped": False}
    mf = manifest()
    if mf is None:
        raise SafetyError("the user-level team is not installed (shipm agents install first)")
    bad = []
    for n, meta in mf["agents"].items():
        cur = _read_file(user_dir(home) / (n + ".md"))
        if cur is None or not isinstance(meta, dict) or sha256_bytes(cur) != meta.get("sha256"):
            bad.append(n)
    if bad:
        raise SafetyError("the user-level team is not intact (%s); run shipm agents install" % ", ".join(sorted(bad)[:5]))
    ad = Path(p.path) / ".claude" / "agents"
    for n in _names_in(ad):
        data = _read_file(ad / (n + ".md"))
        if data is None:
            rep["kept"].append((n, "unreadable")); continue
        sha = sha256_bytes(data)
        master_shas = {(mf["agents"].get(n) or {}).get("sha256")} | set((mf.get("legacy") or {}).get(n) or [])
        if sha in master_shas:
            rep["removed"].append(n)
        elif n in _all_master_names(mf):
            rep["kept"].append((n, "a master name but modified: kept as the project's own file"))
        else:
            rep["kept"].append((n, "project-only agent"))
    bk = Path(p.path) / ".claude" / "_backup"
    rep["has_backups"] = bk.is_dir()
    if not apply:
        return rep
    if not (Path(p.path) / ".git").exists():
        rep["skipped"] = "not a git project"; return rep
    c = chats_open(p.name)
    if c is None:
        rep["skipped"] = "the watcher gives no fresh chat state (run bin/shipm-watch scan), run again"; return rep
    if c > 0:
        rep["skipped"] = "%d chat(s) open (close them, then run again)" % c; return rep
    if not _git_clean(p.path, ".claude"):
        rep["skipped"] = ".claude has uncommitted changes (commit or discard them, then run again)"; return rep
    why = _git_guard(p.path)
    if why:
        rep["skipped"] = why; return rep
    e = registry.entry(p.id)
    if e is None:
        registry.sync([p])                                  # the gate activates by registry: the entry must exist before any copy goes
    rels, saved = [], {}
    try:
        for n in rep["removed"]:
            f = ad / (n + ".md")
            saved[f] = f.read_bytes()
            os.unlink(str(f)); rels.append(".claude/agents/%s.md" % n)
        if drop_backups and bk.is_dir() and not bk.is_symlink():
            import shutil
            shutil.rmtree(str(bk)); rels.append(".claude/_backup"); rep["backups_dropped"] = True
        if rels:
            rep["committed"] = _commit(p.path, rels, "Team moved to user level")
    except BaseException:
        for f, b in saved.items():                          # the commit failed: put the files back (never leave a deleted, uncommitted team)
            if not f.exists():
                state.atomic_write(f, b, 0o644)
        raise
    return rep


# ------------------------------------------------------------------ doctor rows
def doctor_rows(ws=None, home=None) -> List[tuple]:
    """[(level, text)] with level ok | info | warn | FAIL. Never raises."""
    rows = []
    add = lambda lv, t: rows.append((lv, t))               # noqa: E731
    ws = Path(ws if ws is not None else paths.workspace_dir())
    home = Path(home if home is not None else paths.home())
    try:
        lay = layout()
    except ShipmiracleError as e:
        add("FAIL", "agents.layout unreadable: %s" % e); lay = "legacy"
    try:
        mf = manifest()
    except ShipmiracleError as e:
        add("FAIL", "agents manifest damaged: %s → shipm agents install" % e); mf = None
    if mf is None:
        add("FAIL" if lay == "userlevel" else "info",
            "user-level agents not installed (layout %s)%s" % (lay, " → shipm agents install" if lay == "userlevel" else ""))
    else:
        miss, chg = [], []
        for n, meta in sorted(mf["agents"].items()):
            cur = _read_file(user_dir(home) / (n + ".md"))
            if cur is None:
                miss.append(n)
            elif not isinstance(meta, dict) or sha256_bytes(cur) != meta.get("sha256"):
                chg.append(n)
        if miss or chg:
            add("FAIL", "user agents differ from the manifest (missing: %s; changed: %s) → shipm agents install" % (", ".join(miss) or "-", ", ".join(chg) or "-"))
        else:
            add("ok", "%d user-level agents match the manifest" % len(mf["agents"]))
        masters = _read_masters(ws)
        stale = [n for n, d in masters.items() if (mf["agents"].get(n) or {}).get("sha256") != sha256_bytes(d)]
        head = masters_head(ws)
        if stale or (head and mf.get("ws_sha") and head != mf.get("ws_sha")):
            add("warn", "the installed team is older than the masters (%s) → shipm agents install" % (", ".join(sorted(stale)[:4]) or "commit differs"))
        else:
            add("ok", "installed team is current with the masters")
    try:
        plist = [p for p in projects.list_projects() if not p.symlink]
    except ShipmiracleError:
        plist = []
    legacy_all = (mf or {}).get("legacy") or {}
    gated = 0
    try:
        reg = registry.load()["projects"]
    except ShipmiracleError as e:
        reg = None
        add("FAIL" if lay == "userlevel" else "warn", "registry unreadable: %s" % e)
    for p in plist:
        ents = list_agents(p.path, home)
        proj = [r for r in ents if r.layer == "project"]
        shadows = [r.name for r in proj if r.shadow]
        untrusted = [r.name for r in proj if r.claimed in PRIVILEGED and not r.trusted]
        old = [r.name for r in proj if r.name in LEGACY_NAMES and r.trusted]
        vend = [r.name for r in proj if r.overrides and parse((_read_file(r.path) or b"").decode("utf-8", "replace"))["vendored"]]
        if shadows:
            add("warn", "%s: unmarked master-name file(s) %s → add 'overrides:' or remove" % (p.name, ", ".join(shadows)))
        if untrusted:
            add("warn", "%s: privileged role claim not trusted (%s) → shipm agents activate %s <name>" % (p.name, ", ".join(untrusted), p.name))
        if old and lay == "userlevel":
            add("warn", "%s: %d old-name agent file(s) left → shipm project migrate-team %s" % (p.name, len(old), p.name))
        if vend:
            add("info", "%s: %d vendored agent copies (rollback)" % (p.name, len(vend)))
        if reg is not None and p.id in reg and registry.team_state(reg[p.id]) == "on":
            gated += 1
    if reg is not None and plist:
        missing = [p.name for p in plist if p.id not in reg]
        if missing:
            add("FAIL" if lay == "userlevel" else "warn", "registry lacks %d project(s): %s → shipm registry sync" % (len(missing), ", ".join(missing[:6])))
        else:
            add("ok", "registry covers all %d projects (gated %d, layout %s)" % (len(plist), gated, lay))
    return rows
