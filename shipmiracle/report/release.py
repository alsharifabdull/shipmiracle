"""Release facts of a project for the two-level timeline (spec: owner decisions D1-D6, 30 Oct 2026).

A release is a pushed git tag `vX.Y` (D2). Everything here is read-only and fails soft: a git call has a 2 second timeout, and a missing
git, a repository without commits or a timeout turns the fact into None (never an exception, never a write). Only `mark` writes: it creates
one annotated tag (kept local; pushed only with --push); it is owner-only (paths.require_owner here, the flow gate in front of it).

facts(pd, ...) -> {"last": {version, date, tag} | None,                    newest version tag on the first-parent line of HEAD, date = its commit's date (YYYY-MM-DD)
                   "working": {version, source} | None,                    version in the project's version file when higher than `last`
                   "since": {changes, commits}}                            delivered CRs / commits after `last` (no tag: all of them)
history(pd, ...) -> [{id, title, status, closed, release}]                 at most 10, newest first; closed = epoch seconds; release = the earliest version tag containing the CR's commit, else None
"""
from __future__ import annotations

import datetime
import os
import re
import subprocess
from pathlib import Path
from typing import Optional

from .. import NotFound, ShipmiracleError, UsageError
from .. import paths, projects
from ..playbook import engine, store
from . import clean

GIT_TIMEOUT = 2.0                      # seconds, every read-only git call
WRITE_TIMEOUT = 30.0                   # tag creation and push
HISTORY_MAX = 10
VERSION_RE = re.compile(r"[0-9]+(?:\.[0-9]+){0,3}")
TAG_RE = re.compile(r"v?([0-9]+(?:\.[0-9]+){0,3})")
_MAX_FILE = 5 * 1024 * 1024
_SKIP_DIRS = {"node_modules", "Pods", "build", "DerivedData", "Carthage", ".build", ".git", "vendor", "venv", ".venv"}


# ---------- git (the seam: tests replace subprocess.run through RUN) ----------

RUN = subprocess.run


class Git:
    """Read-only git calls of one project. After a timeout every further call returns None at once (a slow repository costs 2 s once, not per call)."""

    def __init__(self, pd, timeout: float = None):
        self.pd = str(pd)
        self.timeout = GIT_TIMEOUT if timeout is None else timeout
        self.dead = False

    def run(self, argv, timeout: float = None) -> Optional[str]:
        """stdout (stripped) when git exits 0, else None."""
        r = self.run_rc(argv, timeout)
        return None if r is None or r[0] != 0 else r[1].strip()

    def run_rc(self, argv, timeout: float = None):
        """(returncode, stdout, stderr) or None (timeout, no git, dead)."""
        if self.dead:
            return None
        try:
            r = RUN(projects.GIT_PREFIX + list(argv), cwd=self.pd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    timeout=self.timeout if timeout is None else timeout, shell=False, env=projects.git_env())
        except subprocess.TimeoutExpired:
            self.dead = True
            return None
        except (OSError, subprocess.SubprocessError):
            return None
        return r.returncode, r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace")


# ---------- versions ----------

def version_key(v: str) -> tuple:
    """(1, 2, 0, 0) for 1.2: trailing zeros do not matter, so 1.2 == 1.2.0."""
    parts = [int(x) for x in v.split(".")]
    return tuple(parts + [0] * (4 - len(parts)))


def tag_version(name: str) -> Optional[str]:
    m = TAG_RE.fullmatch(name or "")
    return m.group(1) if m else None


# ---------- last release ----------

def last_release(g: Git):
    """The newest version tag on the first-parent line of HEAD: {version, date, tag, commit, ts} (commit and ts for the callers; the panel drops them) or None.
    A tag on a side branch is not on that line, so it is never found."""
    out = g.run(["log", "--first-parent", "--simplify-by-decoration", "--max-count=1000", "--format=%H%x09%ct%x09%cs%x09%D", "HEAD"])
    for ln in (out or "").splitlines():
        parts = ln.split("\t", 3)
        if len(parts) < 4:
            continue
        found = []
        for d in parts[3].split(", "):
            if d.startswith("tag: ") and tag_version(d[5:]):
                found.append((version_key(tag_version(d[5:])), d[5:]))
        if not found:
            continue
        _k, name = max(found)
        try:
            ts = int(parts[1])
        except ValueError:
            ts = 0
        return {"version": tag_version(name), "date": parts[2], "tag": name, "commit": parts[0], "ts": ts}
    return None


# ---------- working version ----------

def _read(p: Path) -> Optional[str]:
    try:
        if p.is_symlink() or not p.is_file() or p.stat().st_size > _MAX_FILE:
            return None
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _xcode(pd: Path):
    """The most common MARKETING_VERSION of the first project.pbxproj (root, then one folder down)."""
    cands = sorted(pd.glob("*.xcodeproj/project.pbxproj"))
    if not cands:
        for d in sorted(x for x in pd.iterdir() if x.is_dir() and not x.is_symlink() and not x.name.startswith(".") and x.name not in _SKIP_DIRS):
            cands += sorted(d.glob("*.xcodeproj/project.pbxproj"))
    for c in cands:
        txt = _read(c)
        if txt is None:
            continue
        counts = {}
        for m in re.finditer(r"MARKETING_VERSION\s*=\s*([^;]+);", txt):
            v = m.group(1).strip().strip('"').strip()
            if VERSION_RE.fullmatch(v):
                counts[v] = counts.get(v, 0) + 1
        if counts:
            return max(counts.items(), key=lambda kv: (kv[1], version_key(kv[0])))[0]
    return None


def _package_json(pd: Path):
    import json
    txt = _read(pd / "package.json")
    if txt is None:
        return None
    try:
        v = json.loads(txt).get("version")
    except (ValueError, AttributeError):
        return None
    return v if isinstance(v, str) and VERSION_RE.fullmatch(v) else None


def _pyproject(pd: Path):
    txt = _read(pd / "pyproject.toml")
    if txt is None:
        return None
    sect = None
    for ln in txt.splitlines():
        s = ln.strip()
        if s.startswith("["):
            sect = s
            continue
        if sect == "[project]":
            m = re.fullmatch(r"version\s*=\s*([\"'])([^\"']+)\1\s*(?:#.*)?", s)
            if m:
                return m.group(2) if VERSION_RE.fullmatch(m.group(2)) else None
    return None


def _version_file(pd: Path):
    txt = _read(pd / "VERSION")
    if txt is None:
        return None
    v = txt.strip().splitlines()[0].strip() if txt.strip() else ""
    return v if VERSION_RE.fullmatch(v) else None


SOURCES = (("Xcode project", _xcode), ("package.json", _package_json), ("pyproject.toml", _pyproject), ("VERSION", _version_file))


def version_file(project_dir):
    """{version, source} of the first version file that gives a valid version, or None."""
    pd = Path(os.path.realpath(str(project_dir)))
    for name, fn in SOURCES:
        try:
            v = fn(pd)
        except OSError:
            v = None
        if v:
            return {"version": v, "source": name}
    return None


def working_version(project_dir, last):
    """The version file's version when it is higher than the last release's (any version when there is no release yet), else None."""
    w = version_file(project_dir)
    if w is None:
        return None
    if last is not None and version_key(w["version"]) <= version_key(last["version"]):
        return None
    return w


# ---------- the CRs ----------

def cr_records(project_dir, lines, work, base=None) -> list:
    """Finished CRs, newest first: the live ones (work) and the ones compaction folded into the history file. [{id,title,status,opened,closed,commit}]"""
    heads = store.deliver_heads(lines)
    recs, seen = [], set()
    for c in work["crs"]:
        if c["status"] in engine.TERMINAL:
            seen.add(c["id"])
            recs.append({"id": c["id"], "title": clean(c["title"], 120), "status": c["status"], "opened": c.get("opened"), "closed": c.get("closed"), "commit": heads.get(c["id"])})
    try:
        old = store.read_history(project_dir, base)
    except Exception:
        old = []
    for d in old:
        if d["id"] not in seen:
            seen.add(d["id"])
            recs.append(dict(d, title=clean(d["title"], 120)))
    recs.sort(key=lambda r: (r["closed"] if isinstance(r["closed"], int) else -1, r["id"]), reverse=True)
    return recs


def _since(g: Git, last, recs) -> dict:
    """{changes, commits}: commits after the last release (all commits without one) and delivered CRs among them. A CR counts when its recorded commit is
    among those commits, or, with no recorded commit, when it was closed after the release commit."""
    rng = "HEAD" if last is None else "%s..HEAD" % last["commit"]
    n = g.run(["rev-list", "--count", rng])
    commits = int(n) if n and n.isdigit() else 0
    shas = set()
    if commits:
        lst = g.run(["rev-list", "--max-count=5000", rng])
        shas = {x[:12] for x in (lst or "").split()}
    changes = 0
    for r in recs:
        if r["status"] != "delivered":
            continue
        if r.get("commit"):
            changes += r["commit"][:12] in shas
        elif last is None:
            changes += 1
        else:
            changes += isinstance(r.get("closed"), int) and r["closed"] > last["ts"]
    return {"changes": changes, "commits": commits}


def facts(project_dir, recs=None, base=None, lines=None, work=None) -> dict:
    """{last, working, since}; never raises. `recs` = cr_records(...) when the caller has them."""
    pd = os.path.realpath(str(project_dir))
    g = Git(pd)
    try:
        last = last_release(g)
    except Exception:
        last = None
    try:
        working = working_version(pd, last)
    except Exception:
        working = None
    if recs is None:
        try:
            lines = lines if lines is not None else store._parse_lines(store._read_log_bytes(store.log_path(pd, base)))[0]
            recs = cr_records(pd, lines, work if work is not None else store.replay(lines)[0], base)
        except Exception:
            recs = []
    try:
        since = _since(g, last, recs)
    except Exception:
        since = {"changes": 0, "commits": 0}
    return {"last": {k: last[k] for k in ("version", "date", "tag")} if last else None, "working": working, "since": since}


def release_of(g: Git, commit) -> Optional[str]:
    """The lowest version tag that contains `commit` (the release that shipped it), else None."""
    if not commit or not re.fullmatch(r"[0-9a-f]{7,40}", commit):
        return None
    out = g.run(["tag", "--contains", commit])
    vs = [tag_version(t) for t in (out or "").splitlines()]
    vs = [v for v in vs if v]
    return min(vs, key=version_key) if vs else None


def history(project_dir, recs, n: int = HISTORY_MAX) -> list:
    """The last `n` finished CRs, newest first: [{id,title,status,closed,release}]."""
    g = Git(os.path.realpath(str(project_dir)))
    out = []
    for r in recs[:n]:
        try:
            rel = release_of(g, r.get("commit")) if r["status"] == "delivered" else None
        except Exception:
            rel = None
        out.append({"id": r["id"], "title": r["title"], "status": r["status"], "closed": r["closed"] if isinstance(r["closed"], int) else None, "release": rel})
    return out


# ---------- text for `shipm release status` ----------

def status_lines(f: dict) -> list:
    last, w, s = f["last"], f["working"], f["since"]
    out = ["last release: " + ("%s (%s, tag %s)" % (last["version"], last["date"], last["tag"]) if last else "none (no version tag on this branch)")]
    out.append("working version: " + ("%s (from %s)" % (w["version"], w["source"]) if w else "none"))
    out.append("since the last release: %d change%s, %d commit%s" % (s["changes"], "" if s["changes"] == 1 else "s", s["commits"], "" if s["commits"] == 1 else "s"))
    return out


# ---------- mark (the one writer) ----------

def _starts_on_tag(txt: str) -> bool:
    """True when a workflow file may start from a pushed tag: a `tags:` / `tags-ignore:` key, `on: push` or `on: [push, ...]`, `on: create` (also as a key), or a
    `push:` key with no `branches:` filter under it. A line scan, not a YAML parse; it errs towards warning. Comment text is ignored."""
    lines = [re.sub(r"(^|[ \t])#.*$", "", ln).rstrip() for ln in txt.splitlines()]
    if re.search(r"^[ \t]*-?[ \t]*['\"]?tags(?:-ignore)?['\"]?[ \t]*:", "\n".join(lines), re.M):
        return True
    for i, ln in enumerate(lines):
        if re.match(r"^['\"]?on['\"]?[ \t]*:[ \t]*(\[[^\]]*\b(push|create)\b[^\]]*\]|push|create)[ \t]*$", ln):
            return True
        m = re.match(r"^([ \t]*)-?[ \t]*(push|create)[ \t]*:[ \t]*(\{[ \t]*\})?$", ln)
        if not m:
            continue
        if m.group(2) == "create":
            return True
        ind, body = len(m.group(1)), []
        for nx in lines[i + 1:]:
            if not nx.strip():
                continue
            if len(nx) - len(nx.lstrip()) <= ind:
                break
            body.append(nx)
        if not any(re.match(r"^[ \t]*['\"]?branches['\"]?[ \t]*:", x) for x in body):
            return True
    return False


def tags_workflow(project_dir) -> Optional[str]:
    """The name of the first CI workflow file that may start on a pushed tag (see _starts_on_tag), else None. Only used for the warning with `mark --push`."""
    d = Path(project_dir) / ".github" / "workflows"
    try:
        names = sorted(p for p in os.listdir(str(d)) if p.endswith((".yml", ".yaml")))
    except OSError:
        return None
    for n in names:
        txt = _read(d / n)
        if txt and _starts_on_tag(txt):
            return n
    return None


def _check_date(date: Optional[str]) -> Optional[str]:
    if date is None:
        return None
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", date):
        raise UsageError("--date is YYYY-MM-DD")
    try:
        datetime.date.fromisoformat(date)
    except ValueError:
        raise UsageError("--date is not a real date")
    return date


def mark(project_dir, version: str, date: Optional[str] = None, push: bool = False) -> dict:
    """Create the annotated tag vX.Y on the newest first-parent commit on or before `date` (default HEAD). Owner only. Refuses a bad version or an existing
    release of the same version. The tag stays LOCAL unless `push` (the owner decides when a tag reaches GitHub: many CI setups deploy on a tag push); with `push`,
    a workflow that may start on a tag adds a warning. Returns {tag, commit, date, pushed, remote, note, warn}. The tag is created before the push; a failed push
    raises after the tag exists (the message says so)."""
    paths.require_owner("shipm release mark")
    if not isinstance(version, str) or not VERSION_RE.fullmatch(version):
        raise UsageError("version must look like 1.2 or 1.2.3 (digits and dots, at most four parts)")
    date = _check_date(date)
    pd = os.path.realpath(str(project_dir))
    g = Git(pd, timeout=WRITE_TIMEOUT)
    if g.run(["rev-parse", "--git-dir"]) is None:
        raise NotFound("%s is not a git repository" % os.path.basename(pd))
    key = version_key(version)
    existing = g.run(["tag", "--list"])
    if existing is None:
        raise ShipmiracleError("could not list the tags")
    for t in existing.splitlines():
        v = tag_version(t)
        if v and version_key(v) == key:
            raise UsageError("release %s already exists (tag %s); a release is never moved" % (version, t))
    if date is None:
        sha = g.run(["rev-parse", "--verify", "-q", "HEAD^{commit}"])
    else:
        sha = g.run(["rev-list", "-n", "1", "--first-parent", "--before=%s 23:59:59" % date, "HEAD"])
    if not sha or not re.fullmatch(r"[0-9a-f]{40,64}", sha):
        raise NotFound("no commit%s to tag" % ("" if date is None else " on or before " + date))
    tag = "v" + version
    r = g.run_rc(["tag", "-a", tag, "-m", "Release " + version, sha])
    if r is None or r[0] != 0:
        raise ShipmiracleError("could not create tag %s: %s" % (tag, clean(r[2] if r else "git did not answer", 200)))
    cdate = g.run(["show", "-s", "--format=%cs", sha]) or ""
    res = {"tag": tag, "commit": sha, "date": cdate, "pushed": False, "remote": None, "note": None, "warn": None}
    remote = g.run(["config", "--get", "branch.%s.remote" % (g.run(["symbolic-ref", "--short", "-q", "HEAD"]) or "-")]) or ("origin" if g.run(["remote", "get-url", "origin"]) else None)
    if not push:
        res["note"] = ("kept local: nothing was pushed. To push it when you want: git push %s %s" % (remote, tag)) if remote else "kept local: this project has no git remote"
        return res
    if not remote:
        raise ShipmiracleError("tag %s was created locally, but there is no git remote to push it to" % tag)
    wf = tags_workflow(pd)
    if wf:
        res["warn"] = "this push may start a deploy: " + wf
    p = g.run_rc(["push", remote, "refs/tags/" + tag])
    if p is None or p[0] != 0:
        raise ShipmiracleError("tag %s was created locally, but the push to %s failed: %s; push it with: git push %s %s"
                               % (tag, remote, clean(p[2] if p else "no answer", 200), remote, tag))
    res["pushed"], res["remote"] = True, remote
    return res


# ---------- CLI glue (arguments are parsed in shipmiracle/cli.py) ----------

def run(a) -> int:
    """`shipm release status|mark`. status writes nothing; mark is owner only."""
    import json
    import sys
    from ..playbook import cli as pcli
    pd = pcli._project_arg(a.project)
    if a.action == "status":
        f = facts(pd)
        sys.stdout.write((json.dumps(f, sort_keys=True, ensure_ascii=False) if getattr(a, "json", False) else "\n".join(status_lines(f))) + "\n")
        return 0
    if not a.rversion:
        raise UsageError("release mark needs a version, for example: shipm release mark 1.2")
    res = mark(pd, a.rversion, getattr(a, "date", None), bool(getattr(a, "push", False)))
    sys.stdout.write("tagged %s at %s (%s)\n" % (res["tag"], res["commit"][:7], res["date"]))
    sys.stdout.write((("pushed to " + res["remote"]) if res["pushed"] else res["note"]) + "\n")
    if res.get("warn"):
        sys.stdout.write("warning: " + res["warn"] + "\n")
    return 0
