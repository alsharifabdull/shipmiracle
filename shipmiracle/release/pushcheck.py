"""`shipm push-check REMOTE URL` (spec 2026-10-20-p8-spec.md section 4, pre-push guard). Offline and read-only: it reads the registry, the config,
the release stamps and the local git objects; it never runs a network command and never writes. Keyed by the repo's top-level folder.

R1  a project or workspace repo may push only to its expected remote (expected_remote, else the remote found at sync) or a registered extra remote.
R2  a push to the public-engine remote is refused unless the repo is the export stage (<state>/v1/release/stage-*/repo).
R3  a push from the export stage needs: the registry's single public-engine entry as the destination; refs only main and v* tags, no deletes;
    for every pushed ref a PASS stamp check-<tree sha>.json younger than 1 h that was made WITH the denylist (a --no-denylist stamp is
    not accepted); every new commit with the GitHub noreply author and committer.
R4  an unregistered repo may push anywhere except to the public-engine remote (R2).
Exit: Result.refused. Messages never contain a URL as typed (it may carry credentials): only the normalised owner/name."""
from __future__ import annotations

import json
import os
import re
import subprocess
import time

from .. import ShipmiracleError, config, paths, projects, registry, state

GIT = "git"
STAMP_MAX_AGE = 3600
NOREPLY_RE = re.compile(r"\d+\+[A-Za-z0-9-]+@users\.noreply\.github\.com")
_ZERO = re.compile(r"^0+$")
_REF_OK = re.compile(r"^refs/(heads/main|tags/v\d[0-9A-Za-z.+-]*)$")
_STAGE_RE = re.compile(r"^stage-\d+(-\d+)?$")
MAX_NEW_COMMITS = 200


class Result(object):
    def __init__(self):
        self.refused = False
        self.rule = None
        self.lines = []

    def refuse(self, rule, why):
        self.refused, self.rule = True, rule
        self.lines.append("push blocked (%s): %s" % (rule, why))
        return self

    def note(self, text):
        self.lines.append("shipm push-check: " + text)
        return self


def _git(args, cwd):
    argv = [GIT] + projects.GIT_PREFIX[1:] + args
    try:
        r = subprocess.run(argv, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                           timeout=15, shell=False, env=projects.git_env())
    except (OSError, subprocess.SubprocessError):
        return 1, ""
    return r.returncode, r.stdout.decode("utf-8", "replace")


def parse_refs(text):
    out = []
    for line in (text or "").splitlines():
        p = line.split()
        if len(p) == 4:
            out.append(tuple(p))
    return out


def stage_repo_root():
    return os.path.realpath(str(state.root() / "release"))


def is_stage_repo(top) -> bool:
    """True for <state>/v1/release/stage-<ts>/repo (the one place the public release is committed and pushed from)."""
    t = os.path.realpath(top)
    root = stage_repo_root()
    if os.path.basename(t) != "repo":
        return False
    parent = os.path.dirname(t)
    return os.path.dirname(parent) == root and bool(_STAGE_RE.match(os.path.basename(parent)))


def stamp_problem(tree_sha, now=None):
    """None when check-<tree_sha>.json is a fresh PASS made with the denylist; else the reason (no values in it)."""
    now = time.time() if now is None else now
    p = state.root() / "release" / ("check-%s.json" % tree_sha)
    try:
        d = json.loads(state.read_bytes_nofollow(p).decode("utf-8"))
    except FileNotFoundError:
        return "no release-check stamp for tree %s (run shipm release export)" % tree_sha[:12]
    except (ValueError, OSError, ShipmiracleError):
        return "the release-check stamp for tree %s is unreadable" % tree_sha[:12]
    if not isinstance(d, dict) or d.get("v") != 1 or d.get("result") != "PASS" or d.get("tree_sha") != tree_sha:
        return "the release-check stamp for tree %s is not a PASS for that tree" % tree_sha[:12]
    ts = d.get("ts")
    if isinstance(ts, bool) or not isinstance(ts, (int, float)):
        return "the release-check stamp has no time"
    if now - ts > STAMP_MAX_AGE:
        return "the release-check stamp for tree %s is older than 1 hour (run shipm release export again)" % tree_sha[:12]
    if ts - now > 300:
        return "the release-check stamp is dated in the future"
    fl = d.get("flags")
    if not isinstance(fl, dict) or fl.get("no_denylist") is not False or fl.get("denylist_used") is not True \
            or "identifier" in (d.get("skipped") or []):
        return "the release-check stamp for tree %s was not made with the denylist (a --no-denylist stamp is not accepted for a push)" % tree_sha[:12]
    return None


def _r3(res, top, dest, pubs, refs, now):
    if len(pubs) != 1:
        return res.refuse("R3", "the export stage may push only when exactly one public-engine entry is registered (shipm registry add-remote)")
    pub = pubs[0]
    if dest is None or dest != pub["remote"]:
        return res.refuse("R3", "the export stage may push only to the registered public-engine remote")
    if pub["entry"].get("expected_visibility") not in ("private", "public"):
        return res.refuse("R3", "the public-engine entry does not have expected_visibility=private or public")
    if not refs:
        return res.refuse("R3", "no ref lines to check")
    want_email = config.get("release.author_email")
    for lref, lsha, rref, rsha in refs:
        if _ZERO.match(lsha):
            return res.refuse("R3", "deleting refs on the public remote is not allowed")
        if not _REF_OK.match(rref):
            return res.refuse("R3", "only refs/heads/main and v* tags may go to the public remote (not %s)" % re.sub(r"[^\x20-\x7e]", "?", rref)[:60])
        rc, tree = _git(["rev-parse", "--verify", "-q", lsha + "^{tree}"], top)
        tree = tree.strip()
        if rc != 0 or not re.fullmatch(r"[0-9a-f]{40,64}", tree):
            return res.refuse("R3", "cannot read the tree of %s" % lsha[:12])
        why = stamp_problem(tree, now)
        if why:
            return res.refuse("R3", why)
        args = ["rev-list", "--max-count=%d" % (MAX_NEW_COMMITS + 1), lsha]
        if not _ZERO.match(rsha) and _git(["cat-file", "-e", rsha + "^{commit}"], top)[0] == 0:
            args += ["--not", rsha]
        rc, out = _git(args, top)
        shas = out.split()
        if rc != 0 or not shas or len(shas) > MAX_NEW_COMMITS:
            return res.refuse("R3", "cannot list the new commits (or more than %d)" % MAX_NEW_COMMITS)
        rc, out = _git(["log", "--no-walk=unsorted", "--format=%an%x00%ae%x00%cn%x00%ce"] + shas, top)
        rows = [l.split("\x00") for l in out.splitlines() if l]
        if rc != 0 or len(rows) != len(shas):
            return res.refuse("R3", "cannot read commit authors")
        for an, ae, cn, ce in rows:
            if not (NOREPLY_RE.fullmatch(ae) and NOREPLY_RE.fullmatch(ce)) or (want_email and (ae != want_email or ce != want_email)) \
                    or an != cn:
                return res.refuse("R3", "a commit to be pushed does not have the configured GitHub noreply author and committer")
    return res


def check(remote_name, url, refs_text, cwd=None, now=None) -> Result:
    res = Result()
    top_rc, top = _git(["rev-parse", "--show-toplevel"], cwd or os.getcwd())
    top = top.strip()
    if top_rc != 0 or not top:
        return res.note("not inside a git work tree; push allowed")
    stage = is_stage_repo(top)
    try:
        reg = registry.load()
    except ShipmiracleError as e:
        if stage:
            return res.refuse("R3", "the registry is unreadable (%s)" % e)
        return res.note("registry unreadable (%s); push allowed" % e)
    dest = registry.normalise_remote(url) if url else None
    pubs = registry.public_engines(reg)
    pub_remotes = set(p["remote"] for p in pubs if p["remote"])
    refs = parse_refs(refs_text)
    if stage:
        return _r3(res, top, dest, pubs, refs, now)
    if dest is not None and dest in pub_remotes:
        return res.refuse("R2", "%s is the public-engine remote; only `shipm release export --push` may push there" % dest)
    entry = reg["projects"].get(projects.project_id(top))
    if entry is not None and registry.role_of(entry) in ("project", "workspace"):
        exp = registry.expected_remote_of(entry)
        extras = set(registry.normalise_remote(x.get("remote")) or x.get("remote") for x in (entry.get("extra_remotes") or []) if isinstance(x, dict))
        if exp is not None and dest != exp and dest not in extras:
            return res.refuse("R1", "this project may push only to %s or a registered extra remote (destination: %s)"
                              % (exp, dest or "not recognised"))
        return res
    return res          # R4: unregistered repo (or a public-engine entry's folder): allowed except to the public remote (R2 above)
