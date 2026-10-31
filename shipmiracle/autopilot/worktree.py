"""The isolation of a full-autopilot run (Phase 6 spec section 3): one git worktree per run, one branch per change request.

  create        `git -C <main> worktree add -b auto/CR-n <dev>/.worktrees/<project>/auto-CR-n <main HEAD>`
  import_cr     the CR of the main log is copied into the worktree's OWN log (op import, status open, lane full; every stage after scope goes back to
                `next`: nothing the owner or a model did elsewhere counts here) and the main log gets a lease on it (owner prompts cannot release it)
  switch_next   after a delivery: `git -C <wt> switch -c auto/CR-m <main HEAD>`, import of CR-m, auto_decision charter_next_cr
  drop          rollback before the merge: worktree remove + branch -D + lease released (owner only, never while the run is running)

Every git command is a FIXED argv list run with an explicit environment (PATH, HOME, LC_ALL...; nothing else is inherited) and hooks switched off;
no text from a model ever reaches an argv. Under SHIPMIRACLE_TEST=1 every mutating function refuses a folder outside the temp sandbox (guard): a test
can never touch a real project."""
from __future__ import annotations

import hashlib
import os
import re
import subprocess

from .. import NotFound, SafetyError, UsageError
from .. import events, paths
from . import state as S

CR_RE = re.compile(r"CR-\d{3,6}")
SHA_RE = re.compile(r"[0-9a-f]{40,64}")
PATH_FIXED = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
GATE_PATHS = (".githooks", ".claude", ".shipmiracle", ".mcp.json", ".github", ".co" "dex", ".husky", ".envrc")
GATE_FILES = (".vscode/tasks.json", ".vscode/settings.json")
GATE_NAMES = ("claude.md", "agents.md")          # at any depth (compared folded): instructions the next chat obeys; a change needs the owner's `allow`


def is_gate_path(rel: str) -> bool:
    """A path of a branch diff that controls hooks, settings, tools or instructions (deliver: H5 unless the owner allows)."""
    r = rel.strip("/")
    low = r.casefold()
    return r.split("/", 1)[0] in GATE_PATHS or low in GATE_FILES or low.rsplit("/", 1)[-1] in GATE_NAMES or r == ".mcp.json"

GIT_TIMEOUT = 60


# ---------------------------------------------------------------- guard and git
def guard(*dirs) -> None:
    """SHIPMIRACLE_TEST=1 means 'a test': it must be a COMPLETE temp sandbox and every folder touched must be inside the temp folder (the 2026-10-20
    incident: SHIPMIRACLE_TEST alone is not a sandbox). Outside tests nothing is checked here."""
    if os.environ.get("SHIPMIRACLE_TEST") != "1":
        return
    if not paths.sandboxed():
        raise SafetyError("SHIPMIRACLE_TEST=1 without a complete temp sandbox (SHIPMIRACLE_CONFIG, SHIPMIRACLE_STATE, SHIPMIRACLE_WS, SHIPMIRACLE_DEV and HOME under the temp folder): refusing to touch git")
    for d in dirs:
        if d and not paths._under_temp(d):
            raise SafetyError("test run refused to touch %s (outside the temp folder)" % d)


def genv(ident=False, isolate=False) -> dict:
    e = {"PATH": PATH_FIXED, "HOME": os.environ.get("HOME") or os.path.expanduser("~"), "LC_ALL": "C", "LANG": "C", "GIT_TERMINAL_PROMPT": "0",
         "GIT_OPTIONAL_LOCKS": "0", "GIT_CONFIG_NOSYSTEM": "1"}
    if os.environ.get("SSH_AUTH_SOCK"):
        e["SSH_AUTH_SOCK"] = os.environ["SSH_AUTH_SOCK"]
    if isolate:                                     # M3: no global / system config (url.<x>.insteadOf, credential helpers) between the check and the push
        e.update(GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null")
    if ident:
        e.update(GIT_AUTHOR_NAME="shipm autopilot", GIT_AUTHOR_EMAIL="shipmiracle@localhost", GIT_COMMITTER_NAME="shipm autopilot", GIT_COMMITTER_EMAIL="shipmiracle@localhost")
    return e


def git(wd, args, timeout=GIT_TIMEOUT, ident=False, isolate=False):
    """(returncode, stdout text). Fixed argv, explicit environment, hooks off, no prompt. 127 when git is missing, 124 on timeout."""
    argv = ["git", "-C", str(wd), "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", "-c", "commit.gpgsign=false"] + [str(a) for a in args]
    try:
        r = subprocess.run(argv, env=genv(ident, isolate), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=timeout, shell=False)
    except subprocess.TimeoutExpired:
        return 124, ""
    except OSError:
        return 127, ""
    return r.returncode, r.stdout.decode("utf-8", "replace")


def rev(wd, ref="HEAD"):
    rc, out = git(wd, ["rev-parse", "--verify", "-q", ref + "^{commit}"])
    out = out.strip()
    return out if rc == 0 and SHA_RE.fullmatch(out) else None


def current_branch(wd) -> str:
    rc, out = git(wd, ["symbolic-ref", "-q", "--short", "HEAD"])
    return out.strip() if rc == 0 else ""


def names(cr):
    """(branch, folder name) for a CR id."""
    if not isinstance(cr, str) or not CR_RE.fullmatch(cr):
        raise UsageError("not a change request id")
    return "auto/" + cr, "auto-" + cr


def hooks_dir(state_dir=None) -> str:
    """The engine-owned EMPTY folder every auto worktree uses as core.hooksPath (C1)."""
    return os.path.join(str(state_dir if state_dir is not None else paths.state_dir()), "v1", "autopilot", "nohooks")


def isolate_hooks(main, wt) -> None:
    """Per-worktree core.hooksPath = the engine's empty folder (extensions.worktreeConfig + `git config --worktree`), so no hook of the repository (the
    model may write .githooks/** or anything a hooksPath names) ever runs in this worktree. The hook module re-checks it on every call. Raises UsageError."""
    d = hooks_dir()
    os.makedirs(d, 0o700, exist_ok=True)
    rc, _o = git(main, ["config", "extensions.worktreeConfig", "true"])
    if rc != 0:
        raise UsageError("git config extensions.worktreeConfig failed")
    rc, _o = git(wt, ["config", "--worktree", "core.hooksPath", d])
    if rc != 0:
        raise UsageError("git config --worktree core.hooksPath failed")


def worktree_path(main, cr) -> str:
    main = os.path.realpath(str(main))
    return os.path.join(os.path.dirname(main), ".worktrees", os.path.basename(main), names(cr)[1])


def push_targets(main):
    """[(name, url)] of the URLs a `git push <name>` would go to (`get-url --push --all`, insteadOf/pushurl applied, no global/system config)."""
    rc, out = git(main, ["remote"], isolate=True)
    res = []
    if rc != 0:
        return res
    for name in out.split():
        rc2, o2 = git(main, ["remote", "get-url", "--push", "--all", name], isolate=True)
        if rc2 != 0:
            res.append((name, ""))
            continue
        for u in dict.fromkeys(x.strip() for x in o2.splitlines() if x.strip()):
            res.append((name, u))
    return res


def remotes(main):
    """[(name, url)] of every URL a remote can be fetched from or pushed to: `git remote get-url --all <name>` and `get-url --push --all <name>` (insteadOf and
    pushurl applied, no global/system config), one row per distinct URL. A remote whose URLs cannot be read is returned with url '' (never private)."""
    rc, out = git(main, ["remote"], isolate=True)
    res = []
    if rc != 0:
        return res
    for name in out.split():
        urls = []
        for extra in ([], ["--push"]):
            rc2, o2 = git(main, ["remote", "get-url"] + extra + ["--all", name], isolate=True)
            if rc2 != 0:
                urls.append("")
            else:
                urls += [u.strip() for u in o2.splitlines() if u.strip()]
        seen = set()
        for u in urls:
            if u not in seen:
                seen.add(u)
                res.append((name, u))
    return res


def dirty_files(wd, ignore=(".shipmiracle/",)):
    """Paths with changes (tracked or untracked, not ignored) except under the engine's own folders."""
    rc, out = git(wd, ["status", "--porcelain=v1", "-z", "--untracked-files=all", "--no-renames"])
    if rc != 0:
        raise UsageError("git status failed in the worktree")
    res = []
    for ent in out.split("\0"):
        if len(ent) > 3 and not ent[3:].startswith(tuple(ignore)):
            res.append(ent[3:])
    return res


def inspect(wd):
    """{"wt", "main", "name", "pid", "branch"} for an autopilot worktree (the .git file points into <dev>/<project>/.git), else NotFound."""
    wd = os.path.realpath(str(wd))
    main = os.path.realpath(str(paths.main_checkout(wd)))
    if main == wd:
        raise NotFound("%s is not a git worktree" % wd)
    from .. import projects
    return {"wt": wd, "main": main, "name": os.path.basename(main), "pid": projects.project_id(main), "branch": current_branch(wd)}


# ---------------------------------------------------------------- decisions and events
def log_decision(pid, charter_sha, cr, stage, rule, detail="") -> None:
    """Event auto_decision {cr, stage, rule, charter_sha, detail<=200}; the run's counter goes up. Never raises."""
    try:
        events.emit("auto_decision", {"cr": cr, "stage": stage or "-", "rule": rule, "charter_sha": charter_sha, "detail": str(detail)[:200]},
                    project=pid, src="autopilot")
        S.bump_decisions(pid)
    except Exception:
        pass


def stop_id(rule, cr, key="") -> tuple:
    """(H-xxxxxx, cmd_sha) for a stop the engine itself raises (deliver): derived, so the owner's `allow H-...` binds to exactly this situation."""
    sha = hashlib.sha256(("deliver|%s|%s|%s" % (rule, cr, key)).encode("utf-8", "replace")).hexdigest()
    return "H-" + sha[:6], sha


def pause_stop(pid, rule, cr, text, key="", charter_sha=None, stage="deliver") -> dict:
    """Pause the run with an engine stop; event autopilot.hard_stop like the hook's. Returns the stop dict."""
    _derived, sha = stop_id(rule, cr, key)           # cmd_sha stays derived (the owner's allow binds to it); the id the owner types is random (H4)
    from . import rules as R
    hid = R.new_stop_id()
    stop = {"id": hid, "rule": rule, "ts": int(S.now()), "text": text[:200], "cmd_sha": sha}
    S.pause(pid, stop, "hard_stop")
    try:
        events.emit("autopilot.hard_stop", {"rule": rule.split("-")[0], "label": rule, "id": hid, "cr": cr, "stage": stage, "tool": "engine", "cmd_sha": sha,
                                            "excerpt": text[:200], "charter_sha": charter_sha, "state": "paused"}, project=pid, src="autopilot")
    except Exception:
        pass
    return stop


# ---------------------------------------------------------------- logs
def _main_transact(main, fn):
    from ..playbook import store
    return store.transact(main, fn, do_render=False)


def _ev(by="engine", data=None):
    return {"kind": "engine", "by": by, "ts": int(S.now()), "data": data or {}}


def lease(main, cr, on=True) -> None:
    """Lease (or release) CR `cr` of the main log for the autopilot worktree."""
    from ..playbook import engine

    def fn(work):
        return None, (engine.lease(work, cr, names(cr)[1], _ev()) if on else engine.unlease(work, cr, _ev()))
    _main_transact(main, fn)


def import_cr(main, wt, cr_id, base=None) -> bool:
    """Copy CR `cr_id` of the main log into the worktree's own log as the open CR (idempotent: False when it is already there). The stages after scope
    are reset to `next`, the lane is full. Raises UsageError when the main log has no open/queued CR with that id."""
    guard(main, wt)
    from ..playbook import engine, store, types
    from .. import projects
    mw = store.load(main)
    c = engine.get_cr(mw, cr_id)
    if c is None or c["status"] not in ("open", "queued"):
        raise UsageError("%s is not an open or queued change request in the main log" % cr_id)
    ww = store.load(wt)
    if engine.get_cr(ww, cr_id) is not None:
        return False
    if ww.get("active") is not None:
        raise UsageError("the worktree already works on %s" % ww["active"])
    stages = {s: ("next") for s in types.ORDER}
    for s in ("intake", "scope"):
        stages[s] = c["stages"].get(s, "next") if re.fullmatch(r"next|skipped|done:[A-Za-z0-9_.-]{1,40}", c["stages"].get(s, "next")) else "next"
    line = {"ts": int(S.now()), "cr": cr_id, "op": "import", "stage": None, "by": "import", "sid8": None,
            "ev": {"kind": "engine", "ref": None, "data": {"title": c["title"], "lane": "full", "status": "open", "base": base, "opened": int(S.now()),
                                                         "skip": [], "stages": stages, "blocked": None}}}
    store.append(wt, [line])
    if base:
        store.save_snapshot(wt, cr_id, {"base": base, "untracked": []})       # the CR's diff is measured against the commit the branch started at
    events.emit("cr.imported", {"n": 1, "cr": cr_id, "from": "main"}, project=projects.project_id(wt), src="playbook")
    return True


# ---------------------------------------------------------------- create / next / drop
def create(main, cr) -> dict:
    """Make the worktree and branch for `cr` at the main checkout's HEAD. UsageError when the branch or folder exists or main is on an auto branch /
    detached HEAD. Returns {"wt", "branch", "base", "main_branch"}."""
    main = os.path.realpath(str(main))
    branch, _folder = names(cr)
    wt = worktree_path(main, cr)
    guard(main, wt)
    if os.path.lexists(wt):
        raise UsageError("%s already exists" % wt)
    mb = current_branch(main)
    if not mb or mb.startswith("auto/"):
        raise UsageError("the main checkout must be on its own branch (not detached, not an auto branch)")
    if rev(main, "refs/heads/" + branch):
        raise UsageError("branch %s already exists (shipm autopilot drop %s removes it)" % (branch, cr))
    base = rev(main, "HEAD")
    if not base:
        raise UsageError("the main checkout has no commits")
    os.makedirs(os.path.dirname(wt), 0o700, exist_ok=True)
    rc, _o = git(main, ["worktree", "add", "-b", branch, wt, base])
    if rc != 0 or current_branch(wt) != branch:
        raise UsageError("git worktree add failed")
    try:
        isolate_hooks(main, wt)
    except UsageError:
        git(main, ["worktree", "remove", "--force", wt])
        git(main, ["branch", "-D", branch])
        raise
    return {"wt": os.path.realpath(wt), "branch": branch, "base": base, "main_branch": mb}


def start_run(pid, main, charter, cr) -> dict:
    """create + import + lease + the run state's cr/branch/worktree/base. Everything is undone when a step fails."""
    info = create(main, cr)
    try:
        import_cr(main, info["wt"], cr, info["base"])
        lease(main, cr, True)
        S.set_progress(pid, cr=cr, branch=info["branch"], worktree=info["wt"], base=info["base"])
        S.bump_crs(pid)                                          # option C: counts against crs_day (no-op for other runs)
    except BaseException:
        try:
            drop(pid, main, cr, force=True)
        except Exception:
            pass
        raise
    return info


def _pid_of(main):
    from .. import projects
    return projects.project_id(os.path.realpath(str(main)))


def next_cr_id(main, charter, after=None):
    """The next CR of the charter's `ends` (in order) that is open or queued in the main log and not leased; None when none is left."""
    from ..playbook import engine, store
    work = store.load(main)
    ends = list(charter["ends"])
    if charter.get("until") == "disabled":                      # option C: the starting list, then the owner's admissions, in that order; nothing else is ever picked
        from . import standing
        pid = _pid_of(main)
        ends += [i for i in standing.admitted_ids(pid, main) if i not in ends]
    dropped = []
    try:
        dropped = list((S.read(_pid_of(main)) or {}).get("dropped") or [])
    except Exception:
        pass
    start = ends.index(after) + 1 if after in ends else 0
    for c in ends[start:]:
        if c in dropped:
            continue
        cr = engine.get_cr(work, c)
        if cr is not None and cr["status"] in ("open", "queued") and not cr.get("lease"):
            return c
    return None


def switch_next(pid, main, wt, charter, charter_sha, cur_cr) -> dict:
    """After a delivery: new branch auto/<next CR> from the main HEAD in the same worktree (clean), import, lease, state, auto_decision.
    Returns {"cr", "branch", "base"} or None when no CR is left (the caller ends the run with `done`)."""
    main, wt = os.path.realpath(str(main)), os.path.realpath(str(wt))
    guard(main, wt)
    nxt = next_cr_id(main, charter, cur_cr)
    if nxt is None:
        return None
    from ..playbook import engine, store
    prev = engine.get_cr(store.load(wt), cur_cr)
    if prev is not None and prev["status"] not in engine.TERMINAL:
        raise UsageError("%s is not finished in the worktree" % cur_cr)
    if dirty_files(wt):
        raise UsageError("the worktree is not clean: the next branch needs a clean tree")
    branch, _f = names(nxt)
    if rev(main, "refs/heads/" + branch):
        raise UsageError("branch %s already exists" % branch)
    base = rev(main, "HEAD")
    if not base:
        raise UsageError("main has no commits")
    rc, _o = git(wt, ["switch", "-c", branch, base])
    if rc != 0 or current_branch(wt) != branch:
        raise UsageError("git switch failed")
    import_cr(main, wt, nxt, base)
    lease(main, nxt, True)
    S.set_progress(pid, cr=nxt, branch=branch, base=base)
    S.bump_crs(pid)
    log_decision(pid, charter_sha, nxt, "intake", "charter_next_cr", "%s delivered; next %s on %s" % (cur_cr, nxt, branch))
    return {"cr": nxt, "branch": branch, "base": base}


def drop(pid, main, cr, force=False) -> dict:
    """Rollback before the merge: remove the worktree and delete the branch, release the lease. Refused while the run is running, and when the branch is
    already merged into main (then `git revert` is the way; the report prints it)."""
    main = os.path.realpath(str(main))
    branch, _f = names(cr)
    wt = worktree_path(main, cr)
    guard(main, wt)
    cur = S.read(pid) if os.path.exists(str(S.path(pid))) else None
    if cur is not None and cur["state"] == "running" and not force:
        raise UsageError("the run is running: stop it first (shipm autopilot stop), then drop")
    out = {"removed_worktree": False, "deleted_branch": False, "unleased": False}
    head = rev(main, "HEAD")
    tip = rev(main, "refs/heads/" + branch)
    if tip and head:
        rc, _o = git(main, ["merge-base", "--is-ancestor", tip, head])
        base = cur.get("base") if cur else None
        if rc == 0 and base and tip != base:
            raise UsageError("%s is already merged into main: undo it with `git revert` (see the CR report)" % branch)
    if os.path.lexists(wt):
        rc, _o = git(main, ["worktree", "remove", "--force", wt])
        out["removed_worktree"] = rc == 0
        if rc != 0:
            raise UsageError("git worktree remove failed")
    if tip:
        rc, _o = git(main, ["branch", "-D", branch])
        out["deleted_branch"] = rc == 0
    try:
        lease(main, cr, False)
        out["unleased"] = True
    except Exception:
        pass
    events.emit("autopilot.dropped", {"cr": cr, "branch": branch}, project=pid, src="shipmiracle")
    return out


def commit_reports(wt, cr) -> bool:
    """The engine commits the CR report it wrote (docs/reports/ only) on the auto branch so that it travels with the merge. True when a commit was made."""
    guard(wt)
    rc, _o = git(wt, ["add", "--", "docs/reports"])
    if rc != 0:
        return False
    rc, _o = git(wt, ["diff", "--cached", "--quiet", "--", "docs/reports"])
    if rc == 0:
        return False
    rc, _o = git(wt, ["commit", "-q", "-m", "Report for %s (autopilot)" % cr, "--", "docs/reports"], ident=True)
    return rc == 0
