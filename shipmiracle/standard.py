"""The engineering standard in every project's CLAUDE.md.

docs/standards/base.md is rendered between two markers; plan_migration() builds the new CLAUDE.md of an old template project
(AGENTS.md + CLAUDE.md with `@AGENTS.md`) and checks that no project line is lost; apply() writes it (after a backup of the ORIGINAL
BYTES) and never commits. Exceptions (registry `standard: manual`, or the seeded table) get a proposal only: apply() refuses them.
`manual` means: never auto-migrate; an existing managed block is still refreshed by sync. Writes only inside the project folder and the
backup root; never through a symlink; every check runs before the first write. Kept project lines are copied byte for byte."""
from __future__ import annotations

import difflib
import os
import re
import stat
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import ShipmiracleError, SafetyError, SchemaError, UsageError
from . import paths, projects, registry, state

BEGIN = "<!-- SHIPMIRACLE-STANDARD BEGIN v2 (managed by shipm sync; edit AI-Workspace/docs/standards/base.md) -->"
END = "<!-- SHIPMIRACLE-STANDARD END -->"
_BEGIN_RE = re.compile(r"<!-- SHIPMIRACLE-STANDARD BEGIN v\d+[^\n]*?-->")
_OLD_BEGIN_RE = re.compile(r"<!-- SHARED-STANDARDS BEGIN[^\n]*-->")      # sync-tools and templates/base/AGENTS.md (v1)
_OLD_END = "<!-- SHARED-STANDARDS END -->"
MAX_BASE_BYTES = 4096
ON_DEMAND = ("team.md", "records.md", "skills.md", "ideas.md", "long-jobs.md")
MANAGED_HEADER = "<!-- managed by shipm sync from AI-Workspace/docs/standards/%s; edit it there, not here -->"
ENTRY_HEADING = "## Engineering entry"
CLAUDE_HEADING = "## Claude-specific"
RULES_HEADING = "## Project rules (from the old shared block)"
KNOWN_DIR = ("docs", "standards", "known")          # *.txt = the body of each known version of the old shared block

# One-line items and two-line items of the old template CLAUDE.md that are removed (EXACT match after stripping trailing blanks; a pair
# only as a unit, both lines in a row; nothing else is ever removed). The role-name and second-engine lines are rewritten by base.md / team.md.
# The removed second engine's name is built from pieces so this file (exported) does not carry the word.
_ENG = "co" + "dex"
_ENGC = "Co" + "dex"
SINGLE_LINES = frozenset([
    "- Plan mode = DISCUSS/PLAN. Do not implement from plan mode.",
    "- To hand a task to " + _ENGC + " from this chat, use the `" + _ENG + "` MCP server; write the brief into `docs/STATUS.md` first.",
])
PAIRS = (
    ("- Use the experts in `.claude/agents/` as subagents by role name; `independent-reviewer`,",
     "  `security-reviewer` and `qa-engineer` are read-only."),
    ("- Hooks in `.claude/settings.json` run the formatter after edits and the tests when you stop;",
     "  read their output and act on failures before reporting."),
    ("- To hand a task to " + _ENGC + " from this chat, use the `" + _ENG + "` MCP server; write the brief into",
     "  `docs/STATUS.md` first so " + _ENGC + " has it even without the MCP call."),
)
_PAIR_LINES = frozenset(x for p in PAIRS for x in p)
_FLAG_RE = re.compile(_ENG + r"|AGENTS\.md", re.I)


class ContainmentError(ShipmiracleError):
    """A line of the old project text would be lost; the migration is refused."""
    exit_code = 1


# ---- markers (whole line, outside code fences) ----

def _scan(lines: List[str], is_begin, is_end) -> Tuple[List[int], List[int]]:
    """Indexes of BEGIN and END marker lines: a marker is a whole line (after strip) outside ``` / ~~~ fences."""
    fence, begins, ends = None, [], []
    for i, l in enumerate(lines):
        s = l.strip()
        if s.startswith("```") or s.startswith("~~~"):
            f = s[:3]
            fence = None if fence == f else (fence or f)
            continue
        if fence:
            continue
        if is_begin(s):
            begins.append(i)
        elif is_end(s):
            ends.append(i)
    return begins, ends


def _one_block(lines: List[str], is_begin, is_end, what: str) -> Optional[Tuple[int, int]]:
    """(begin index, end index) of the single block, None when there is no marker at all; SchemaError otherwise."""
    b, e = _scan(lines, is_begin, is_end)
    if not b and not e:
        return None
    if len(b) != 1 or len(e) != 1 or e[0] < b[0]:
        raise SchemaError("%s needs exactly one BEGIN and one END marker line, in that order, outside code fences" % what)
    return b[0], e[0]


_new_begin = lambda s: _BEGIN_RE.fullmatch(s) is not None      # noqa: E731
_new_end = lambda s: s == END                                   # noqa: E731
_old_begin = lambda s: _OLD_BEGIN_RE.fullmatch(s) is not None  # noqa: E731
_old_end = lambda s: s == _OLD_END                              # noqa: E731


# ---- render / refresh ----

def base_text(ws=None) -> str:
    p = (Path(ws) if ws is not None else paths.workspace_dir()) / "docs" / "standards" / "base.md"
    return state.read_bytes_nofollow(p).decode("utf-8")


def render(base: str) -> str:
    """The managed block: BEGIN marker, base text, END marker, final newline."""
    if not isinstance(base, str) or not base.strip():
        raise UsageError("base text is empty")
    if "SHIPMIRACLE-STANDARD" in base:
        raise UsageError("base text must not contain the standard markers")
    return BEGIN + "\n" + base.strip("\n") + "\n" + END + "\n"


def has_block(text: str) -> bool:
    """A managed block marker line outside code fences (see _one_block for the exactly-one rule)."""
    return bool(_scan(text.split("\n"), _new_begin, _new_end)[0])


def refresh(text: str, base: str) -> str:
    """Replace the single managed block of `text` by render(base); text without a block is returned unchanged;
    SchemaError when the markers are not exactly one pair."""
    lines = text.split("\n")
    pos = _one_block(lines, _new_begin, _new_end, "CLAUDE.md")
    if pos is None:
        return text
    b, e = pos
    return "\n".join(lines[:b] + render(base).rstrip("\n").split("\n") + lines[e + 1:])


def on_demand_files(ws=None) -> Dict[str, str]:
    """{file name: text with the managed header as its first line} for docs/standards/ of a project."""
    root = (Path(ws) if ws is not None else paths.workspace_dir()) / "docs" / "standards"
    return {n: MANAGED_HEADER % n + "\n" + state.read_bytes_nofollow(root / n).decode("utf-8") for n in ON_DEMAND}


def _norm(l: str) -> str:
    return " ".join(l.split())


def known_lines(ws=None) -> Counter:
    """Normalised lines (multiset) of every known version of the old shared block (docs/standards/known/*.txt)."""
    d = (Path(ws) if ws is not None else paths.workspace_dir()).joinpath(*KNOWN_DIR)
    c: Counter = Counter()
    try:
        names = sorted(n for n in os.listdir(d) if n.endswith(".txt"))
    except OSError:
        return c                                 # optional folder: absent in a public checkout, no known old blocks then
    for n in names:
        for l in state.read_bytes_nofollow(d / n).decode("utf-8").split("\n"):     # a symlink or foreign file here is a SafetyError on purpose
            if l.strip():
                c[_norm(l)] += 1
    return c


# ---- the plan ----

@dataclass
class Plan:
    project: str
    name: str
    status: str                       # migrate | already | unfinished | skip
    new_claude_md: Optional[str] = None
    delete_agents_md: bool = False
    removed_lines: List[str] = field(default_factory=list)     # template lines removed from CLAUDE.md (and titles dropped)
    kept_lines: List[str] = field(default_factory=list)        # project lines carried over (non-blank)
    removed_block_lines: int = 0                               # non-blank lines of the old shared block that are known standard text
    exception: Optional[str] = None                            # None, or why apply() refuses
    manual: Optional[str] = None                               # registry `standard: manual` (never auto-migrate; block refresh allowed)
    note: str = ""
    shape: str = ""
    lost: List[str] = field(default_factory=list)              # containment failures (must be empty)
    flagged: List[str] = field(default_factory=list)           # kept lines that still mention the second engine / AGENTS.md (edit by hand)
    old_claude_md: Optional[str] = None
    old_agents_md: Optional[str] = None
    old_claude_bytes: Optional[bytes] = None
    old_agents_bytes: Optional[bytes] = None
    files: Dict[str, str] = field(default_factory=dict)        # docs/standards/* to write


def _read_bytes(path: Path) -> Optional[bytes]:
    """Bytes of a regular file (not a symlink), or None when absent."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(st.st_mode):
        raise SafetyError("%s is a symlink" % path)
    if not stat.S_ISREG(st.st_mode):
        raise SafetyError("%s is not a regular file" % path)
    return state.read_bytes_nofollow(path)


def _text(b: Optional[bytes], what: str) -> Optional[str]:
    if b is None:
        return None
    try:
        return b.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("%s is not UTF-8: left alone" % what)


def _manual(project_path: str, name: str) -> Optional[str]:
    """Why this project is a manual exception, or None. Only a stored registry entry with standard manual counts (the owner seeds those; none are built in)."""
    try:
        ent = registry.entry(projects.project_id(project_path))
    except (SchemaError, OSError):
        ent = None
    if ent is not None and "standard" in ent:
        return "registry: standard manual" if ent["standard"] == "manual" else None
    return None


def _squeeze(lines: List[str]) -> List[str]:
    """Strip leading/trailing blank lines and collapse blank runs to one; non-blank lines are never changed."""
    out: List[str] = []
    for l in lines:
        if not l.strip():
            if out and out[-1] != "":
                out.append("")
            continue
        out.append(l)
    while out and out[-1] == "":
        out.pop()
    return out


def _title(lines: List[str]):
    """(H1 line, rest) when the first non-blank line is an H1, else (None, lines)."""
    for i, l in enumerate(lines):
        if l.strip():
            if l.startswith("# "):
                return l, lines[:i] + lines[i + 1:]
            break
    return None, lines


def _filter_claude(lines: List[str], drop_import: bool):
    """(kept lines, removed lines, half-matched lines). Pairs are removed only as a unit; a lone half is kept and flagged."""
    out, removed, half = [], [], []
    i = 0
    while i < len(lines):
        l = lines[i]
        s = l.rstrip()
        if s in SINGLE_LINES or (drop_import and s.strip() == "@AGENTS.md"):
            removed.append(l); i += 1; continue
        pair = next((p for p in PAIRS if s == p[0]), None)
        if pair is not None and i + 1 < len(lines) and lines[i + 1].rstrip() == pair[1]:
            removed += [l, lines[i + 1]]; i += 2; continue
        if s in _PAIR_LINES:
            half.append(l)
        out.append(l); i += 1
    res, i = [], 0                       # the template heading goes only when its section is empty now
    while i < len(out):
        if out[i].strip() == CLAUDE_HEADING:
            j = i + 1
            while j < len(out) and not out[j].lstrip().startswith("#"):
                j += 1
            if all(not x.strip() for x in out[i + 1:j]):
                removed.append(out[i]); i = j; continue
        res.append(out[i]); i += 1
    return res, removed, half


def _nonblank(lines) -> List[str]:
    return [l for l in lines if l.strip()]


def _split_old(lines: List[str], known: Counter):
    """(head, project lines found in the block, tail, number of known standard lines) or None without markers."""
    pos = _one_block(lines, _old_begin, _old_end, "AGENTS.md")
    if pos is None:
        return None
    b, e = pos
    left = Counter(known)
    proj, std = [], 0
    for l in lines[b + 1:e]:
        n = _norm(l)
        if not n:
            continue
        if left[n] > 0:
            left[n] -= 1; std += 1
        else:
            proj.append(l)
    return lines[:b], proj, lines[e + 1:], std


def plan_migration(project_path, ws=None) -> Plan:
    """Build the migration of one project. Reads only; never raises for project content (the plan carries the reason)."""
    p = Path(project_path)
    plan = Plan(project=str(p), name=p.name, status="skip")
    try:
        _plan(p, plan, ws)
    except (ShipmiracleError, ValueError, OSError) as e:
        plan.exception = "refused: %s" % e
        plan.new_claude_md = None
        plan.delete_agents_md = False
    return plan


def _plan(p: Path, plan: Plan, ws) -> None:
    name = p.name
    if p.is_symlink() or not p.is_dir():
        plan.exception = "not a plain project folder (symlink or missing)"
        return
    plan.old_agents_bytes = _read_bytes(p / "AGENTS.md")
    plan.old_claude_bytes = _read_bytes(p / "CLAUDE.md")
    agents = plan.old_agents_md = _text(plan.old_agents_bytes, "AGENTS.md")
    claude = plan.old_claude_md = _text(plan.old_claude_bytes, "CLAUDE.md")
    plan.manual = _manual(str(p), name)
    if agents is None and claude is None:
        plan.shape = "none"
        return
    known = known_lines(ws)
    agent_lines = agents.split("\n") if agents is not None else []
    split = _split_old(agent_lines, known) if agents is not None else None
    if claude is not None and has_block(claude):
        cl = claude.split("\n")
        _one_block(cl, _new_begin, _new_end, "CLAUDE.md")
        if split is None:
            plan.status, plan.shape = "already", "already"
            plan.note = "already migrated" + ("; manual: block refresh only" if plan.manual else "")
            return
        # unfinished migration: CLAUDE.md has the block but AGENTS.md still holds the old block; apply may only delete AGENTS.md
        head, proj, tail, std = split
        plan.status, plan.shape, plan.delete_agents_md = "unfinished", "unfinished", True
        plan.removed_block_lines = std
        hl = _nonblank(head)
        if hl and hl[0].startswith("# "):
            hl = hl[1:]
        have = Counter(_nonblank(cl))
        plan.lost = sorted((Counter(hl + _nonblank(tail) + _nonblank(proj)) - have).elements())
        plan.exception = plan.manual
        plan.note = "unfinished migration: the block is in CLAUDE.md, AGENTS.md still has the old one"
        return
    try:
        base = base_text(ws)
        plan.files = on_demand_files(ws)
    except (OSError, SafetyError, UnicodeDecodeError) as e:
        plan.exception = "standards source unreadable: %s" % e
        return
    block = render(base)
    claude_lines = (claude or "").split("\n")
    delete = split is not None
    imports = any(l.strip() == "@AGENTS.md" for l in claude_lines)
    dangling = agents is None and imports
    ctitle, claude_rest = _title(claude_lines)
    filtered, removed, half = _filter_claude(claude_rest, drop_import=delete or dangling)
    if dangling:
        plan.flagged.append("@AGENTS.md import removed: AGENTS.md does not exist")

    pieces: List[List[str]] = []
    dropped_title = None
    proj_rules: List[str] = []
    head: List[str] = []
    tail: List[str] = []
    if delete:
        head, proj_rules, tail, plan.removed_block_lines = split
        htitle, head_rest = _title(head)
        entry = _squeeze(head_rest) + ([""] if _squeeze(head_rest) and _squeeze(tail) else []) + _squeeze(tail)
        title = ctitle or htitle
        if ctitle and htitle:
            dropped_title = htitle
        plan.shape = "template" if imports else "brief-without-import"
        pieces.append([title] if title else [])
        pieces.append(block.rstrip("\n").split("\n"))
        pieces.append(entry if imports else ([ENTRY_HEADING, ""] + entry if _nonblank(entry) else []))
        if proj_rules:
            pieces.append([RULES_HEADING, ""] + proj_rules)
        pieces.append(filtered)
    else:
        plan.shape = "record" if agents is not None else "claude-only"
        pieces.append([ctitle] if ctitle else [])
        pieces.append(block.rstrip("\n").split("\n"))
        pieces.append(filtered)
    body: List[str] = []
    for pc in pieces:
        pc = _squeeze(pc)
        if pc:
            if body:
                body.append("")
            body.extend(pc)
    new = "\n".join(body) + "\n"
    plan.new_claude_md = new
    plan.delete_agents_md = delete
    plan.removed_lines = [l.rstrip() for l in removed] + ([dropped_title.rstrip() + "   (duplicate title)"] if dropped_title else [])
    for l in half:
        plan.flagged.append("template line kept (its partner line is missing or changed): " + l.rstrip())

    # containment: every non-blank, non-template line of the old project text must be in the new file (outside the managed block)
    old: Counter = Counter(_nonblank(claude_lines))
    old -= Counter(l for l in removed)
    if delete:
        hl = _nonblank(head)
        if hl and hl[0].startswith("# ") and ctitle:
            hl = hl[1:]                 # the project's own CLAUDE.md title wins; the duplicate AGENTS.md title is dropped
        for l in hl + _nonblank(tail) + _nonblank(proj_rules):
            old[l] += 1
    nl = new.split("\n")
    bb, be = _scan(nl, _new_begin, _new_end)
    outside = nl[:bb[0]] + nl[be[0] + 1:]
    lost = old - Counter(_nonblank(outside))
    plan.lost = sorted(lost.elements())
    plan.kept_lines = list(old.elements())
    for l in outside:
        if (_FLAG_RE.search(l) or "AI-Workspace/AGENTS.md" in l) and l.strip() != "@AGENTS.md":
            if _ENG in l.lower() or delete or "AI-Workspace/AGENTS.md" in l:
                plan.flagged.append(l.rstrip())
    plan.status = "migrate"
    plan.exception = plan.manual


def diff(plan: Plan) -> str:
    """Unified diff of CLAUDE.md (old to new) plus the AGENTS.md decision. Read-only text."""
    if plan.new_claude_md is None:
        return ""
    a = (plan.old_claude_md or "").splitlines(keepends=True)
    b = plan.new_claude_md.splitlines(keepends=True)
    d = "".join(difflib.unified_diff(a, b, "a/CLAUDE.md", "b/CLAUDE.md"))
    d += "\n# AGENTS.md: %s\n" % ("deleted (a backup is made first)" if plan.delete_agents_md else "kept")
    return d


# ---- apply ----

def backup_name(plan: Plan) -> str:
    """<project_id>-<sanitised name>: two projects with the same folder name never share a backup folder."""
    return "%s-%s" % (projects.project_id(plan.project), re.sub(r"[^A-Za-z0-9._-]", "_", plan.name)[:60].lstrip("."))


def _inside(root_real: str, target: Path) -> bool:
    """True when the target's parent folder, resolved, is root_real or below it (the file itself is never followed)."""
    par = os.path.realpath(str(target.parent))
    return par == root_real or par.startswith(root_real.rstrip("/") + "/")


def _mkdir_inside(root_real: str, d: Path) -> None:
    if not _inside(root_real, d / "x"):
        raise SafetyError("%s is outside the project" % d)
    try:
        st = os.lstat(d)
    except FileNotFoundError:
        os.makedirs(str(d), exist_ok=True)
        return
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        raise SafetyError("%s is a symlink or not a folder" % d)


def apply(plan: Plan, backup_root, ws=None, now=None) -> dict:
    """Write the plan: backup (original bytes) of CLAUDE.md/AGENTS.md first, new CLAUDE.md, docs/standards/*, delete AGENTS.md when planned.
    Refuses: exceptions, a failed containment check, a changed file (stale plan), symlinks, paths outside the project.
    An already migrated project is a no-op (also a manual one). An unfinished migration only deletes AGENTS.md. Never runs git."""
    if plan.status == "already":
        return {"changed": False, "reason": "already migrated"}
    if plan.exception:
        raise SafetyError("%s is not migrated by apply: %s" % (plan.name, plan.exception))
    if plan.status not in ("migrate", "unfinished") or (plan.status == "migrate" and plan.new_claude_md is None):
        return {"changed": False, "reason": "nothing to do"}
    fresh = plan_migration(plan.project, ws)             # re-derive from the files now on disk
    if fresh.exception or fresh.status != plan.status:
        raise SafetyError("%s changed since the plan: %s" % (plan.name, fresh.exception or fresh.status))
    if fresh.lost or plan.lost:
        raise ContainmentError("containment check failed for %s; lines would be lost:\n%s" % (plan.name, "\n".join(fresh.lost or plan.lost)))
    if fresh.old_claude_bytes != plan.old_claude_bytes or fresh.old_agents_bytes != plan.old_agents_bytes or fresh.new_claude_md != plan.new_claude_md:
        raise SafetyError("%s changed since the plan was made; plan again" % plan.name)
    proj = Path(plan.project)
    root_real = os.path.realpath(str(proj))
    broot = Path(backup_root)
    paths.assert_isolated(broot)
    cpath, apath, sdir = proj / "CLAUDE.md", proj / "AGENTS.md", proj / "docs" / "standards"
    for f in (cpath, apath):
        if not _inside(root_real, f):
            raise SafetyError("%s is outside the project" % f.name)
    if plan.status == "migrate" and plan.files:          # check and make the target folders BEFORE the first write
        _mkdir_inside(root_real, proj / "docs")
        _mkdir_inside(root_real, sdir)
    ts = time.strftime("%Y%m%d-%H%M%S", time.localtime(now if now is not None else time.time()))
    state.ensure_dir(broot)
    pdir = state.ensure_dir(broot / backup_name(plan))
    bdir = pdir / ts
    n = 1
    while bdir.exists():
        bdir = pdir / ("%s-%d" % (ts, n)); n += 1
    state.ensure_dir(bdir)
    if plan.old_claude_bytes is not None:
        state.atomic_write(bdir / "CLAUDE.md", plan.old_claude_bytes, 0o600)
    if plan.old_agents_bytes is not None:
        state.atomic_write(bdir / "AGENTS.md", plan.old_agents_bytes, 0o600)
    written: List[str] = []
    if plan.status == "migrate":
        try:
            mode = stat.S_IMODE(os.lstat(cpath).st_mode)
        except FileNotFoundError:
            mode = 0o644
        state.atomic_write(cpath, plan.new_claude_md.encode("utf-8"), mode)
        written.append("CLAUDE.md")
        for fn, text in sorted(plan.files.items()):
            state.atomic_write(sdir / fn, text.encode("utf-8"), 0o644)
            written.append("docs/standards/" + fn)
    deleted = False
    if plan.delete_agents_md:
        if os.path.islink(apath):
            raise SafetyError("AGENTS.md is a symlink or outside the project")
        os.unlink(apath)
        deleted = True
    return {"changed": True, "backup": str(bdir), "written": written, "deleted_agents_md": deleted}


# ---- sync (already migrated projects): refresh the block and the on-demand files, no commit ----

def sync_project(project_path, ws=None) -> List[str]:
    """Refresh the managed block in CLAUDE.md and docs/standards/* of a migrated project. Returns what changed.
    A project without the block, a symlink or a different layout is left alone (returns []). The workspace itself (the SOURCE of
    docs/standards) is refused. Every check runs before the first write."""
    p = Path(project_path)
    if p.is_symlink() or not p.is_dir():
        return []
    w = Path(ws) if ws is not None else paths.workspace_dir()
    real = os.path.realpath(str(p))
    if real in (os.path.realpath(str(w)), os.path.realpath(str(paths.main_checkout(w)))):
        raise SafetyError("%s is the workspace: docs/standards there is the source and is never synced" % p.name)
    try:
        claude = _text(_read_bytes(p / "CLAUDE.md"), "CLAUDE.md")
        if claude is None or not has_block(claude):
            return []
        new = refresh(claude, base_text(w))
        todo = []
        for fn, text in sorted(on_demand_files(w).items()):
            if _text(_read_bytes(p / "docs" / "standards" / fn), fn) != text:
                todo.append((fn, text))
    except ValueError as e:
        raise SafetyError(str(e))
    if todo:
        _mkdir_inside(real, p / "docs")
        _mkdir_inside(real, p / "docs" / "standards")
    changed = []
    if new != claude:
        if not _inside(real, p / "CLAUDE.md"):
            raise SafetyError("CLAUDE.md is outside the project")
        state.atomic_write(p / "CLAUDE.md", new.encode("utf-8"), stat.S_IMODE(os.lstat(p / "CLAUDE.md").st_mode))
        changed.append("CLAUDE.md")
    for fn, text in todo:
        state.atomic_write(p / "docs" / "standards" / fn, text.encode("utf-8"), 0o644)
        changed.append("docs/standards/" + fn)
    return changed


def malformed_markers(dev=None) -> List[str]:
    """Names of projects whose AGENTS.md or CLAUDE.md has broken standard markers (for the doctor row). Reads only."""
    bad = []
    for pr in projects.list_projects(dev):
        if pr.symlink:
            continue
        for fn, b, e in (("AGENTS.md", _old_begin, _old_end), ("CLAUDE.md", _new_begin, _new_end)):
            try:
                raw = _read_bytes(Path(pr.path) / fn)
                if raw is not None:
                    _one_block(raw.decode("utf-8", "replace").split("\n"), b, e, fn)
            except (ShipmiracleError, OSError):
                bad.append(pr.name); break
    return bad


def summary(plan: Plan) -> dict:
    return {
        "project": plan.name, "status": plan.status, "shape": plan.shape, "exception": plan.exception, "manual": plan.manual,
        "note": plan.note, "delete_agents_md": plan.delete_agents_md,
        "removed_block_lines": plan.removed_block_lines, "removed_template_lines": len(plan.removed_lines),
        "kept_lines": len(plan.kept_lines), "lost": plan.lost, "flagged": plan.flagged,
        "containment": "ok" if not plan.lost else "FAIL",
    }
