"""The one project resolver.

A project is a direct child of the Developer folder whose name does not start with "." and where `<child>/.git` exists
(file or folder). Everything else (symlink, hub, held, scope) is an attribute or a scope predicate. resolve() never guesses:
a path that is not provably inside one project is None. No subprocess runs in list_projects/names/get/resolve;
only scope() with STATUS checks runs `git ls-files` (seam: `_run_git`)."""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from . import ShipmiracleError, UsageError
from . import paths

SCOPES = ("all", "template", "standards", "ci")
_MAX_WALK = 40
_GITDIR_RE = re.compile(r"gitdir:\s*(.+)/\.git/worktrees/[^/]+/?")
_STACK_RE = re.compile(r"Stack rules — (iOS|Notes)")
_GIT_TIMEOUT = 10.0
# every git call of the package: no fsmonitor, no hooks, and an environment that cannot redirect git elsewhere
GIT_PREFIX = ["git", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null"]
_GIT_ENV_KEEP = ("PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR")


def git_env() -> dict:
    """A clean environment for git: only PATH, HOME, LANG, LC_*, TMPDIR (so GIT_DIR, GIT_WORK_TREE, GIT_INDEX_FILE, GIT_CONFIG*,
    GIT_CEILING_DIRECTORIES, GIT_EXEC_PATH and friends from the caller never change what git reads)."""
    return {k: os.environ[k] for k in _GIT_ENV_KEEP if k in os.environ}


def unsafe_name(n: str) -> bool:
    """A folder name with a control character (category C*: newline, NUL, escape, bidi marks...) could add lines to the
    line-oriented shell consumers; such folders are never listed."""
    return any(unicodedata.category(c).startswith("C") for c in n)


@dataclass(frozen=True)
class Project:
    id: str
    name: str
    path: str       # dev/<name> as listed (not resolved)
    real: str       # realpath of path
    symlink: bool
    git: str        # "dir" or "file"
    hub: bool
    held: bool


def _dev(dev) -> str:
    return str(dev if dev is not None else paths.dev_dir())


def _ws(ws) -> Path:
    return Path(ws) if ws is not None else paths.workspace_dir()


def project_id(path) -> str:
    """12 hex chars of sha256("shipmiracle-project:" + realpath(path)); the same for a path and its realpath."""
    real = os.path.realpath(os.path.expanduser(str(path)))
    return hashlib.sha256(("shipmiracle-project:" + real).encode("utf-8", "surrogateescape")).hexdigest()[:12]


def _listed(dev: str) -> List[str]:
    """The single rule: direct children of dev, not dot-named, with `.git` existing; sorted by codepoint."""
    try:
        entries = os.listdir(dev)
    except OSError:
        return []
    return sorted(n for n in entries if not n.startswith(".") and not unsafe_name(n) and os.path.exists(os.path.join(dev, n, ".git")))


def skipped_names(dev=None) -> List[str]:
    """Folders that would be projects but have a control character in the name (listed with the escapes visible, for warnings)."""
    d = _dev(dev)
    try:
        entries = os.listdir(d)
    except OSError:
        return []
    return sorted(n.encode("unicode_escape", "backslashreplace").decode("ascii") for n in entries
                  if not n.startswith(".") and unsafe_name(n) and os.path.exists(os.path.join(d, n, ".git")))


def held_names(ws=None) -> List[str]:
    """config/ci-hold.txt: lines trimmed, blank lines and lines starting with '#' (after trimming) ignored."""
    try:
        text = (_ws(ws) / "config" / "ci-hold.txt").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    out = []
    for line in text.split("\n"):
        s = line.strip()
        if s and not s.startswith("#"):
            out.append(s)
    return out


def _git_kind(gitpath: str) -> str:
    return "dir" if os.path.isdir(gitpath) else "file"


def _prefix_hit(keys, fp):
    """Longest key that equals fp or is a path-prefix of it; keys is [(key, Project)]. None when no key matches."""
    best = None
    for key, proj in keys:
        if fp == key or fp.startswith(key.rstrip("/") + "/"):
            if best is None or len(key) > len(best[0]):
                best = (key, proj)
    return best[1] if best else None


def _hub_name(base: List[Project], ws) -> Optional[str]:
    """Name of the project that is the main checkout of the workspace, or None when the workspace is not a project."""
    try:
        mc = paths.main_checkout(_ws(ws))
        hit = _match(base, os.path.realpath(str(mc)))
    except (OSError, ValueError):
        return None
    return hit.name if hit is not None else None


def _scan(d: str):
    """(projects without hub/held flags, [(alias name, kept name)]). Two names for the same folder (same id): the real folder is kept
    and the symlink alias dropped; two symlinks: the first by name is kept."""
    kept = {}
    dropped = []
    for n in _listed(d):
        p = os.path.join(d, n)
        pr = Project(project_id(p), n, p, os.path.realpath(p), os.path.islink(p), _git_kind(os.path.join(p, ".git")), False, False)
        old = kept.get(pr.id)
        if old is None:
            kept[pr.id] = pr
        elif old.symlink and not pr.symlink:
            dropped.append((old.name, pr.name)); kept[pr.id] = pr
        else:
            dropped.append((pr.name, old.name))
    return sorted(kept.values(), key=lambda x: x.name), sorted(dropped)


def collisions(dev=None) -> List[tuple]:
    """[(alias folder, folder kept)] for names that point at the same folder as another listed name; those aliases are not projects."""
    return _scan(_dev(dev))[1]


def list_projects(dev=None, ws=None, strict: bool = False) -> List[Project]:
    """All projects, sorted by name. An alias (second name for one folder) is dropped and reported by collisions();
    with strict=True it raises ShipmiracleError instead."""
    d = _dev(dev)
    base, dropped = _scan(d)
    if dropped and strict:
        raise ShipmiracleError("projects %s and %s are the same folder (id collision)" % dropped[0])
    hub = _hub_name(base, ws)
    held = set(held_names(ws))
    return [Project(p.id, p.name, p.path, p.real, p.symlink, p.git, p.name == hub, p.name in held) for p in base]


def names(dev=None) -> List[str]:
    """Project names only (the exact list the panel, bin/idea and bin/shipm-watch show), sorted."""
    return _listed(_dev(dev))


def get(name, dev=None) -> Optional[Project]:
    """The project with exactly this listed name, else None. '', '.', '..', dot-names and anything with a slash or NUL are None."""
    if not isinstance(name, str) or not name or name.startswith(".") or "/" in name or unsafe_name(name):
        return None
    for p in list_projects(dev):
        if p.name == name:
            return p
    return None


def _keys(projs: List[Project]):
    out = []
    for p in projs:
        out.append((paths.fold(p.real), p))
        out.append((paths.fold(p.path), p))
    return out


def _match(projs: List[Project], real_path: str) -> Optional[Project]:
    return _prefix_hit(_keys(projs), paths.fold(real_path))


def _worktree_segment(projs: List[Project], dev: str, p: str) -> Optional[Project]:
    root = paths.fold(os.path.realpath(dev)).rstrip("/") + "/.worktrees/"
    fp = paths.fold(p)
    if not fp.startswith(root):
        return None
    seg = fp[len(root):].split("/", 1)[0]
    if not seg:
        return None
    exact = [pr for pr in projs if paths.fold(pr.name) == seg]
    if len(exact) == 1:
        return exact[0]
    return None     # no project of that name, or case-variants that cannot be told apart: do not guess


def _gitfile_worktree(projs: List[Project], p: str) -> Optional[Project]:
    cur = p if os.path.isdir(p) else os.path.dirname(p)
    for _ in range(_MAX_WALK):
        g = os.path.join(cur, ".git")
        if os.path.lexists(g):
            if os.path.isdir(g):
                return None
            try:
                with open(g, "rb") as f:
                    first = f.read(4096).decode("utf-8", "replace").splitlines()[:1]
            except OSError:
                return None
            if not first:
                return None
            m = _GITDIR_RE.fullmatch(first[0].strip())
            if not m:
                return None
            x = m.group(1)
            if not os.path.isabs(x):
                x = os.path.join(cur, x)
            return _match(projs, os.path.realpath(x))
        parent = os.path.dirname(cur)
        if parent == cur:
            return None
        cur = parent
    return None


def resolve(path, dev=None) -> Optional[Project]:
    """The project that owns `path`, or None. Absolute paths only (relative, empty, NUL: None). First match wins:
    (1) realpath; (2) dev/.worktrees/<project>/...; (3) longest prefix of a project's real or listed path;
    (4) nearest .git file of a git worktree whose gitdir points into a project. Anything else: None."""
    if isinstance(path, os.PathLike):
        path = os.fspath(path)
    if not isinstance(path, str) or not path or "\x00" in path:
        return None
    path = os.path.expanduser(path)
    if not os.path.isabs(path):
        return None
    d = _dev(dev)
    projs = list_projects(d)
    if not projs:
        return None
    p = os.path.realpath(path)
    return _worktree_segment(projs, d, p) or _match(projs, p) or _gitfile_worktree(projs, p)


# ---- scopes (the conditions of the three loops in sync-tools) ----

def _run_git(argv, cwd):
    """Seam for tests. Returns (returncode, stdout text); timeout or missing git counts as a failure (1, "")."""
    try:
        r = subprocess.run(argv, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                           timeout=_GIT_TIMEOUT, shell=False, env=git_env())
    except (OSError, subprocess.SubprocessError):
        return 1, ""
    return r.returncode, r.stdout.decode("utf-8", "replace")


def status_tracked(p: Project) -> bool:
    """`git ls-files | grep -qix docs/STATUS.md`: some tracked path equals docs/STATUS.md ignoring case."""
    rc, out = _run_git(GIT_PREFIX + ["ls-files"], p.path)
    return rc == 0 and any(line.lower() == "docs/status.md" for line in out.split("\n"))


_STD_MARKER = "SHIPMIRACLE-STANDARD BEGIN"      # the managed block in CLAUDE.md (shipmiracle.standard); the old standard is the AGENTS.md block


def _read_small(path: str) -> Optional[str]:
    try:
        with open(path, "rb") as f:
            return f.read(2 * 1024 * 1024).decode("utf-8", "replace")
    except OSError:
        return None


def _agents_file(p: Project) -> bool:
    """A template-based project: CLAUDE.md with the managed standard block (new), else the old AGENTS.md (kept for one release)."""
    if os.path.isfile(os.path.join(p.path, "AGENTS.md")):
        return True
    c = os.path.join(p.path, "CLAUDE.md")
    if os.path.isfile(c):
        text = _read_small(c)
        return text is not None and _STD_MARKER in text
    return False


def _in_scope(p: Project, kind: str) -> bool:
    if kind == "template":     # loop 1: dir, not symlink, not the workspace, AGENTS.md + .claude/, not held
        return (not p.symlink and not p.hub and _agents_file(p) and os.path.isdir(os.path.join(p.path, ".claude"))
                and not p.held)
    if kind == "standards":    # loop 2: */AGENTS.md, not symlink, not held, STATUS tracked; NOT the hub (Phase 3a: the workspace's
        # docs/standards is the SOURCE of the standard, never a sync target; the old loop did refresh the hub's AGENTS.md)
        return not p.symlink and not p.hub and _agents_file(p) and not p.held and status_tracked(p)
    if kind == "ci":           # loop 3: .git dir, not symlink, AGENTS.md, not the workspace, not held, STATUS tracked, not iOS/Notes
        if p.symlink or p.git != "dir" or p.hub or not _agents_file(p) or p.held or not status_tracked(p):
            return False
        # Stack rules sit in CLAUDE.md (migrated) or AGENTS.md (old, kept for one release): either file excludes iOS/Notes
        texts = [_read_small(os.path.join(p.path, n)) for n in ("CLAUDE.md", "AGENTS.md") if os.path.isfile(os.path.join(p.path, n))]
        texts = [x for x in texts if x is not None]
        if not texts:
            return True     # `grep -qE` failing on an unreadable file does not skip the project in the old loop
        return not any(_STACK_RE.search(x) for x in texts)
    raise UsageError("unknown scope")


def scope(projects, kind: str) -> List[Project]:
    """Filter `projects` (as returned by list_projects) for a consumer: all | template | standards | ci. Order is kept."""
    if kind not in SCOPES:
        raise UsageError("unknown scope")
    return [p for p in projects if kind == "all" or _in_scope(p, kind)]
