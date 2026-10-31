"""Fast-lane diff measurement. Base = `git stash create` (or HEAD) taken when the CR opens, plus the untracked files of that moment.
count = numstat added+deleted + new untracked files read up to 1 MB; a binary file counts 51 lines; RECORD paths, `.shipmiracle/` and
`docs/reports/` are not counted. Every git call is list-form, has a timeout and uses the hardened environment of shipmiracle.projects."""
from __future__ import annotations

import fnmatch
import os
import re
import subprocess
import time

from .. import ShipmiracleError
from .. import projects

TIMEOUT = 3.0
MAX_UNTRACKED = 300
READ_MAX = 1024 * 1024
BINARY_LINES = 51
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
# same set as the RECORD pattern of the flow gate, plus the engine's own files
RECORD = re.compile(r"^(docs/(STATUS\.md|DECISIONS\.md|FEATURE-IDEAS\.md|ACCEPTANCE\.md|SKILLS\.md|plans/|memory/|status-archive/|reports/)"
                    r"|\.claude/plans/|\.claude/agents-drafts/|\.shipmiracle/)", re.I)
_SHA_RE = re.compile(r"[0-9a-f]{40,64}")


class GitError(ShipmiracleError):
    """git failed, timed out or is missing; callers fail open."""


def _env(identity=False):
    e = projects.git_env()
    e["GIT_OPTIONAL_LOCKS"] = "0"
    if identity:     # `git stash create` makes a commit object and needs an identity even when none is configured
        e.update(GIT_AUTHOR_NAME="shipmiracle", GIT_AUTHOR_EMAIL="shipmiracle@localhost", GIT_COMMITTER_NAME="shipmiracle", GIT_COMMITTER_EMAIL="shipmiracle@localhost")
    return e


def _git(project_dir, args, identity=False, ok=(0,)):
    try:
        r = subprocess.run(projects.GIT_PREFIX + list(args), cwd=str(project_dir), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL, timeout=TIMEOUT, shell=False, env=_env(identity))
    except (OSError, subprocess.SubprocessError) as e:
        raise GitError("git %s failed (%s)" % (args[0], type(e).__name__))
    if r.returncode not in ok:
        raise GitError("git %s exited %d" % (args[0], r.returncode))
    return r.stdout


def _git_par(project_dir, arglists):
    """Run several read-only git commands AT ONCE (latency: one hook call pays the slowest git, not the sum). Returns [(returncode, stdout)] in order;
    a command that cannot start or does not finish within TIMEOUT gives (None, b"") and is killed. Never raises."""
    procs = []
    for args in arglists:
        try:
            procs.append(subprocess.Popen(projects.GIT_PREFIX + list(args), cwd=str(project_dir), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                          stderr=subprocess.DEVNULL, shell=False, env=_env(False)))
        except (OSError, subprocess.SubprocessError):
            procs.append(None)
    out = []
    t0 = time.monotonic()
    for pr in procs:
        if pr is None:
            out.append((None, b""))
            continue
        try:
            o, _e = pr.communicate(timeout=max(0.05, TIMEOUT - (time.monotonic() - t0)))
            out.append((pr.returncode, o))
        except (subprocess.SubprocessError, OSError):
            try:
                pr.kill()
                pr.communicate()
            except Exception:
                pass
            out.append((None, b""))
    return out


def _excluded(path: str) -> bool:
    return bool(RECORD.match(path))


def _untracked(project_dir):
    out = _git(project_dir, ["ls-files", "--others", "--exclude-standard", "-z"])
    return [p.decode("utf-8", "surrogateescape") for p in out.split(b"\0") if p]


def head(project_dir):
    """HEAD commit id, or None in a repository without commits."""
    try:
        s = _git(project_dir, ["rev-parse", "--verify", "-q", "HEAD"]).decode("ascii", "replace").strip()
    except GitError:
        return None
    return s if _SHA_RE.fullmatch(s) else None


def snapshot(project_dir) -> dict:
    """{"base": commit id, "untracked": [paths <= 300], "untracked_more": int}. base is a dangling stash commit holding the current
    tracked changes, or HEAD when the tree is clean (or the empty tree in a repository without commits)."""
    base = None
    if head(project_dir) is not None:
        try:
            s = _git(project_dir, ["stash", "create"], identity=True).decode("ascii", "replace").strip()
        except GitError:
            s = ""
        base = s if _SHA_RE.fullmatch(s) else head(project_dir)
    if base is None:      # no commits yet: the empty tree has to exist as an object for `git diff <tree>`
        try:
            t = _git(project_dir, ["hash-object", "-t", "tree", "-w", "--stdin"]).decode("ascii", "replace").strip()
        except GitError:
            t = ""
        base = t if _SHA_RE.fullmatch(t) else EMPTY_TREE
    un = _untracked(project_dir)
    return {"base": base, "untracked": un[:MAX_UNTRACKED], "untracked_more": max(0, len(un) - MAX_UNTRACKED)}


_PIN_RE = re.compile(r"CR-[0-9]{3,6}(-review)?")


def pin(project_dir, name, sha) -> bool:
    """Keep the commit `sha` (a `git stash create` base is a dangling commit that gc may prune) reachable from refs/shipmiracle/base/<name>. Best effort: False on failure."""
    if not _PIN_RE.fullmatch(name or "") or not _SHA_RE.fullmatch(sha or ""):
        return False
    try:
        _git(project_dir, ["update-ref", "refs/shipmiracle/base/" + name, sha])
        return True
    except GitError:
        return False


def unpin(project_dir, name) -> bool:
    if not _PIN_RE.fullmatch(name or ""):
        return False
    try:
        _git(project_dir, ["update-ref", "-d", "refs/shipmiracle/base/" + name])
        return True
    except GitError:
        return False


def _is_tree(project_dir, sha) -> bool:
    try:
        _git(project_dir, ["cat-file", "-e", sha + "^{tree}"])
        return True
    except GitError:
        return False


def _has_object(project_dir, sha) -> bool:
    try:
        _git(project_dir, ["cat-file", "-e", sha + "^{commit}"])
        return True
    except GitError:
        return False


# ---- globs: ** crosses folders, * does not, {a,b} alternatives ----

def _expand(g):
    m = re.search(r"\{([^{}]*)\}", g)
    if not m:
        return [g]
    out = []
    for alt in m.group(1).split(","):
        out += _expand(g[:m.start()] + alt + g[m.end():])
    return out


def glob_re(g):
    out = []
    i = 0
    while i < len(g):
        if g.startswith("**/", i):
            out.append("(?:.*/)?"); i += 3
        elif g.startswith("**", i):
            out.append(".*"); i += 2
        elif g[i] == "*":
            out.append("[^/]*"); i += 1
        elif g[i] == "?":
            out.append("[^/]"); i += 1
        else:
            out.append(re.escape(g[i])); i += 1
    return re.compile("".join(out) + r"\Z")


def compile_globs(globs):
    res = []
    for g in globs or []:
        for x in _expand(g):
            res.append(glob_re(x))
    return res


def _hit(res, path):
    return any(r.match(path) for r in res)


def _dep(patterns, path):
    base = os.path.basename(path)
    return any(fnmatch.fnmatchcase(base, p) for p in patterns or [])


def _count_file(project_dir, rel):
    """Lines of an untracked file (up to 1 MB read; binary = 51; a symlink counts 1)."""
    p = os.path.join(str(project_dir), rel)
    try:
        st = os.lstat(p)
        if not os.path.isfile(p) or os.path.islink(p):
            return 1
        fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError:
        return 0
    try:
        data = os.read(fd, READ_MAX)
    finally:
        os.close(fd)
    if b"\0" in data[:8000]:
        return BINARY_LINES
    n = data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)
    return max(n, BINARY_LINES) if st.st_size > READ_MAX else n


def _parse_numstat(raw: bytes):
    """[(added, deleted, path, oldpath|None)] from `git diff --numstat -z -M`; binary files have added None."""
    parts = raw.split(b"\0")
    out = []
    i = 0
    while i < len(parts):
        rec = parts[i]
        i += 1
        if not rec:
            continue
        fields = rec.decode("utf-8", "surrogateescape").split("\t", 2)
        if len(fields) < 3:
            continue
        a, d, path = fields
        old = None
        if path == "":                       # rename: the next two NUL fields are old and new
            old = parts[i].decode("utf-8", "surrogateescape") if i < len(parts) else None
            path = parts[i + 1].decode("utf-8", "surrogateescape") if i + 1 < len(parts) else ""
            i += 2
        out.append((None if a == "-" else int(a), None if d == "-" else int(d), path, old))
    return out


def _submodule_paths(raw: bytes):
    """Paths whose mode is 160000 (a submodule pointer) on either side, from `git diff --raw -z`."""
    parts = raw.split(b"\0")
    out = set()
    i = 0
    while i < len(parts):
        h = parts[i]
        i += 1
        if not h.startswith(b":"):
            continue
        f = h[1:].split(b" ")
        status = f[4][:1] if len(f) > 4 else b""
        n = 2 if status in (b"R", b"C") else 1
        paths = [x.decode("utf-8", "surrogateescape") for x in parts[i:i + n]]
        i += n
        if len(f) >= 2 and (f[0] == b"160000" or f[1] == b"160000"):
            out.update(paths)
    return out


def evaluate(project_dir, snap, rules=None) -> dict:
    """Measure the working tree against `snap` (from snapshot()). Returns {"files","lines","risk":[<=5 paths],"deps","ui","submodule",
    "binary","paths":[<=10]}. Raises GitError when git fails."""
    rules = rules or {}
    base = snap.get("base") or EMPTY_TREE
    if not _SHA_RE.fullmatch(base) and base != EMPTY_TREE:
        raise GitError("bad base")
    # the reads run at once; when the base commit proves missing the diffs are discarded and redone below (rare)
    par = _git_par(project_dir, ([] if base == EMPTY_TREE else [["cat-file", "-e", base + "^{commit}"]]) + [
        ["diff", "--numstat", "-z", "-M", "--no-color", base, "--"], ["diff", "--raw", "-z", "-M", "--no-abbrev", "--no-color", base, "--"],
        ["ls-files", "--others", "--exclude-standard", "-z"]])
    pre = None
    if base != EMPTY_TREE:
        if par[0][0] == 0:
            pre = par[1:]
        elif not _is_tree(project_dir, base):
            base = EMPTY_TREE            # the base object is gone (gc): measure against nothing, so the whole tree counts and the change is promoted (fail closed)
    else:
        pre = par
    if pre is not None and any(rc != 0 for rc, _o in pre):
        pre = None                       # any failure: redo sequentially so the error is raised exactly as before
    risk_re = compile_globs(rules.get("risk"))
    ui_re = compile_globs(rules.get("ui"))
    deps = rules.get("deps") or []
    if pre is not None:
        num, sub, untracked_out = _parse_numstat(pre[0][1]), _submodule_paths(pre[1][1]), pre[2][1]
    else:
        num = _parse_numstat(_git(project_dir, ["diff", "--numstat", "-z", "-M", "--no-color", base, "--"]))
        sub = _submodule_paths(_git(project_dir, ["diff", "--raw", "-z", "-M", "--no-abbrev", "--no-color", base, "--"]))
        untracked_out = None
    seen = {p for p in snap.get("untracked", [])}
    ignore = {p for p in (snap.get("ignore") or []) if isinstance(p, str)}      # paths that were already changed before the CR (flow's baseline): never counted
    res = {"files": 0, "lines": 0, "risk": [], "deps": False, "ui": False, "submodule": False, "binary": False, "paths": []}

    def add(path, lines, old=None, is_sub=False, binary=False):
        if _excluded(path) and (old is None or _excluded(old)):
            return
        if path in ignore:
            return
        res["files"] += 1
        res["lines"] += lines
        res["binary"] = res["binary"] or binary
        res["submodule"] = res["submodule"] or is_sub
        for q in (path, old):
            if q is None:
                continue
            if _hit(risk_re, q) and q not in res["risk"] and len(res["risk"]) < 5:
                res["risk"].append(q)
            res["deps"] = res["deps"] or _dep(deps, q)
        res["ui"] = res["ui"] or _hit(ui_re, path)
        if len(res["paths"]) < 10:
            res["paths"].append(path)

    for a, d, path, old in num:
        binary = a is None
        add(path, BINARY_LINES if binary else a + d, old, path in sub or (old in sub if old else False), binary)
    all_untracked = _untracked(project_dir) if untracked_out is None else [p.decode("utf-8", "surrogateescape") for p in untracked_out.split(b"\0") if p]
    new = [p for p in all_untracked if p not in seen]
    for p in new[:MAX_UNTRACKED]:
        if p.endswith("/"):                       # a nested repository
            add(p.rstrip("/"), 0, is_sub=True)
            continue
        if _excluded(p):
            continue
        n = _count_file(project_dir, p)
        add(p, n, binary=(n == BINARY_LINES))
    for p in new[MAX_UNTRACKED:]:
        if not _excluded(p):
            res["files"] += 1
    return res


def delta(project_dir, since_commit) -> dict:
    """{"files","lines"} of the tracked changes between `since_commit` (a review snapshot) and the working tree, same exclusions."""
    if not _SHA_RE.fullmatch(since_commit or ""):
        raise GitError("bad snapshot id")
    files = lines = 0
    for a, d, path, old in _parse_numstat(_git(project_dir, ["diff", "--numstat", "-z", "-M", "--no-color", since_commit, "--"])):
        if _excluded(path):
            continue
        files += 1
        lines += BINARY_LINES if a is None else a + d
    return {"files": files, "lines": lines}
