"""Delivery of a full-autopilot change request (Phase 6 spec section 3, "Merge back"). The ENGINE alone merges and pushes; a model never does.

ff_merge(wt, cr) -> {"status", "text", ...} where status is one of
  merged         the branch was fast-forward merged into the main checkout (and pushed when every remote is cached private); main log: CR delivered
  merge_waiting  a live session in the main checkout, or uncommitted changes there on files the branch touches (Health: info; retried at the next Stop)
  stopped        the run is paused with an engine stop: H5 (gate/hook/settings files in the branch), H2-publish_unknown (a remote that is not
                 cached private and cannot be confirmed), diverged (main moved), push failed
  limit          budget/time reached: no merge
  refused        the preconditions do not hold (run not active, CR not ready, nothing to merge, dirty tree): nothing changed
Preflight, in this order: run active and inside its limits; the CR in the worktree's own log is merge-ready (verify PASS after the last build, every
required lens ACCEPT); the engine commits the CR report; tree clean; commits ahead of the run's base; `git diff base..tip` has no gate/hook/settings/instruction path (W.is_gate_path; else H5; also when the branch is already inside main); main on its own branch with HEAD == merge-base; main has no live session and is clean on the touched files;
every remote cached private (refresh through the injectable runner; unknown = H2-publish_unknown, nothing pushed, nothing merged).
An owner `allow H-...` for an engine stop lets that one stop pass (a publish_unknown allow merges but never pushes). All git calls: fixed argv,
explicit environment, hooks off (worktree.git); refused outside the temp sandbox under SHIPMIRACLE_TEST=1 (worktree.guard)."""
from __future__ import annotations

import os
import re

from .. import ShipmiracleError, events
from . import state as S
from . import visibility
from . import worktree as W

GATE = W.GATE_PATHS


def _res(status, text, **kw):
    d = {"status": status, "text": text}
    d.update(kw)
    return d


def _touched(wt, base, tip):
    rc, out = W.git(wt, ["diff", "--name-only", "-z", "--no-renames", "%s..%s" % (base, tip), "--"])
    if rc != 0:
        return None
    return [x for x in out.split("\0") if x]


def _chats(name):
    from .. import agents
    return agents.chats_open(name)


def _gitleaks(main, base, tip):
    """('clean'|'finding'|'error'|'skipped', text). Default scanner of the delivered range: `gitleaks detect --log-opts=<base>..<tip> --redact --no-banner`."""
    import shutil
    import subprocess
    exe = shutil.which("gitleaks", path=W.PATH_FIXED)
    if not exe:
        return "skipped", "gitleaks is not installed"
    try:
        r = subprocess.run([exe, "detect", "--log-opts=%s..%s" % (base, tip), "--redact", "--no-banner"], cwd=main, env=W.genv(), stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300)
    except (OSError, subprocess.SubprocessError) as e:
        return "error", type(e).__name__
    return ("clean", "") if r.returncode == 0 else ("finding", r.stderr.decode("utf-8", "replace")[-200:])


def _push_blocked(main, wt, branch, mb):
    """The P4 PUSH-BLOCKED marker (a gitleaks finding in commits not pushed yet) in the main checkout's or the worktree's git dir, for this branch or any."""
    for d in (main, wt):
        rc, out = W.git(d, ["rev-parse", "--git-path", "PUSH-BLOCKED"])
        if rc != 0 or not out.strip():
            continue
        p = out.strip() if os.path.isabs(out.strip()) else os.path.join(d, out.strip())
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                line = f.readline()
        except OSError:
            continue
        m = re.search(r"branch=(\S+)", line)
        if not m or m.group(1) in (branch, mb):
            return True
    return False


def ff_merge(wt, cr, runner=None, now=None, chats=None, state_dir=None, scan=None) -> dict:
    wt = os.path.realpath(str(wt))
    info = W.inspect(wt)
    main, pid, name = info["main"], info["pid"], info["name"]
    W.guard(wt, main)
    branch, _folder = W.names(cr)
    if info["branch"] != branch:
        return _res("refused", "the worktree is on %s, not %s" % (info["branch"] or "a detached HEAD", branch))
    ok, why, charter, st = S.check(pid)
    if not ok:
        return _res("refused", "the autopilot run is not active (%s)" % why)
    sha = st["charter_sha"]
    from . import budget
    ev = budget.evaluate(pid, charter)
    if ev["level"] == "reached":
        budget.close_if_reached(pid, ev)
        return _res("limit", "the %s limit was reached: nothing is merged" % ("time" if ev["kind"] == "time" else "budget"))
    # the CR, recomputed from the worktree's own log (never from work.json)
    from ..playbook import engine, gate, store
    rules = gate.stage_rules(wt)
    if rules is None:
        return _res("refused", "no playbook")
    work = store.load(wt)
    c = engine.get_cr(work, cr)
    ready, rwhy = engine.merge_ready(c, rules)
    if not ready:
        return _res("refused", "%s is not ready to merge: %s" % (cr, rwhy))
    base = st.get("base")
    head_main = W.rev(main, "HEAD")
    tip = W.rev(main, "refs/heads/" + branch)
    if not tip or not head_main:
        return _res("refused", "git cannot read the branch")
    if not base:
        rc, out = W.git(main, ["merge-base", head_main, tip])
        base = out.strip() if rc == 0 else None
    if not base:
        return _res("refused", "the run has no base commit")
    rc, _o = W.git(main, ["merge-base", "--is-ancestor", tip, head_main])
    already = rc == 0 and tip != base
    # H2: a branch that is already inside main counts as 'merged by a crashed retry' ONLY when the engine recorded its own merge of exactly this tip
    # (state field `merged`, written before the push). Anything else (a model moved main to the branch with `git fetch . HEAD:main`) is refused.
    recorded = st.get("merged") or ""
    if already and recorded.split(" ")[:2] != [cr, tip]:
        return _res("refused", "%s is already inside the main checkout, but the engine did not merge it: nothing is pushed. The owner checks main and the branch." % branch)
    if not already:
        W.commit_reports(wt, cr)
        tip = W.rev(main, "refs/heads/" + branch)               # H3: resolved ONCE more (the engine's own report commit); every check below is on base..tip
        if not tip:
            return _res("refused", "git cannot read the branch")
        if W.dirty_files(wt):
            return _res("refused", "the worktree is not clean: commit or remove the changes first")
        rc, out = W.git(wt, ["rev-list", "--count", "%s..%s" % (base, tip)])
        if rc != 0 or not out.strip().isdigit() or int(out.strip()) < 1:
            return _res("refused", "nothing to merge: the branch has no commits after the base")
    touched = _touched(wt, base, tip)
    if touched is None:
        return _res("refused", "git diff failed")
    bad = [t for t in touched if W.is_gate_path(t)]
    if bad:
        sid, csha = W.stop_id("H5-deliver_gate_files", cr, ",".join(sorted(bad)))
        if not S.consume_allow(pid, csha):
            stop = W.pause_stop(pid, "H5-deliver_gate_files", cr, "H5-gate_files: the branch changes %s" % ", ".join(sorted(bad)[:3]),
                                ",".join(sorted(bad)), sha)
            return _res("stopped", "Hard stop %s: the branch %s changes gate/hook/settings/instruction files (%s). The autopilot paused; nothing was merged." % (
                stop["id"], branch, ", ".join(sorted(bad)[:3])), stop=stop, rule="H5")
    mb = W.current_branch(main)
    if not mb or mb.startswith("auto/"):
        return _res("refused", "the main checkout is not on its own branch")
    if not already:
        rc, out = W.git(main, ["merge-base", head_main, tip])
        if rc != 0 or out.strip() != head_main:
            stop = W.pause_stop(pid, "deliver-diverged", cr, "main moved since the branch was created: no fast-forward", head_main[:12], sha)
            return _res("stopped", "Stop %s: main moved on after %s was created, so a fast-forward is impossible. The autopilot paused; nothing was merged." % (
                stop["id"], branch), stop=stop, rule="diverged")
        live = (chats or _chats)(name)
        if live is None or live > 0:
            _waiting(pid, cr, "a live chat in the main checkout" if live else "the main checkout's chats cannot be confirmed")
            return _res("merge_waiting", "merge_waiting: %s. %s stays on its branch until the main checkout is idle." % (
                "a chat is open in the main checkout" if live else "the open chats of the main checkout cannot be confirmed", cr))
        tset = set(touched)
        rc, out = W.git(main, ["status", "--porcelain=v1", "-z", "--untracked-files=all", "--no-renames"])
        if rc != 0:
            return _res("refused", "git status failed in the main checkout")
        dirty = sorted(e[3:] for e in out.split("\0") if len(e) > 3 and e[3:] in tset)
        if dirty:
            _waiting(pid, cr, "uncommitted changes in main on " + ", ".join(dirty[:3]))
            return _res("merge_waiting", "merge_waiting: the main checkout has uncommitted changes on files the branch touches (%s)." % ", ".join(dirty[:3]))
    # M2: the engine's merge and push skip the hooks (core.hooksPath=/dev/null), so the checks the P4/P8 hooks make are made here
    if _push_blocked(main, wt, branch, mb):
        sid, csha = W.stop_id("H2-push_blocked", cr, tip)
        if not S.consume_allow(pid, csha):
            stop = W.pause_stop(pid, "H2-push_blocked", cr, "H2-push_blocked: the PUSH-BLOCKED marker (a secret scan finding) is open for %s" % branch, tip[:12], sha)
            return _res("stopped", "Hard stop %s (H2-push_blocked): a secret-scan block (.git/PUSH-BLOCKED) is open. Nothing is merged or pushed. The autopilot paused." % stop["id"],
                        stop=stop, rule="H2")
    scan_note = ""
    if not already:
        kind, why2 = (scan or _gitleaks)(main, base, tip)
        if kind in ("finding", "error"):
            sid, csha = W.stop_id("H2-secret_scan", cr, tip)
            if not S.consume_allow(pid, csha):
                stop = W.pause_stop(pid, "H2-secret_scan", cr, "H2-secret_scan: gitleaks %s in %s..%s" % ("found a possible secret" if kind == "finding" else "failed", base[:8], tip[:8]), tip[:12], sha)
                return _res("stopped", "Hard stop %s (H2-secret_scan): the secret scan of the delivered commits %s. Nothing is merged or pushed. The autopilot paused." % (
                    stop["id"], "reported a finding" if kind == "finding" else "failed"), stop=stop, rule="H2")
        elif kind == "skipped":
            scan_note = " (secret scan skipped: %s)" % why2
            events.emit("autopilot.secret_scan_skipped", {"cr": cr, "why": why2[:80]}, project=pid, src="autopilot")
            W.log_decision(pid, sha, cr, "deliver", "secret_scan_skipped", "%s: no secret scan of %s..%s" % (why2, base[:8], tip[:8]))
    # remotes: visibility (before anything is merged or pushed), every fetch and push URL of every remote (M3)
    now_ts = S.now() if now is None else now
    pushable, unknown = [], []
    for rname, url in W.remotes(main):
        if url and not visibility.is_private(url, now_ts, state_dir) and (runner is not None or os.environ.get("SHIPMIRACLE_TEST") != "1"):
            visibility.refresh(url, runner, now_ts, state_dir)          # the only network call; a test must inject its runner
        (pushable if url and visibility.is_private(url, now_ts, state_dir) else unknown).append((rname, url))
    allow_unknown = False
    if unknown:
        sid, csha = W.stop_id("H2-publish_unknown", cr, ",".join(sorted(n for n, _u in unknown)))
        if S.consume_allow(pid, csha):
            allow_unknown = True
        else:
            stop = W.pause_stop(pid, "H2-publish_unknown", cr, "H2-publish_unknown: remote %s is not cached as private and could not be confirmed" % unknown[0][0],
                                ",".join(sorted(n for n, _u in unknown)), sha)
            return _res("stopped", "Hard stop %s (H2-publish_unknown): remote %s is not confirmed private, so nothing is pushed and nothing is merged. "
                        "The autopilot paused." % (stop["id"], unknown[0][0]), stop=stop, rule="H2")
    targets = []
    if pushable and not allow_unknown:
        from ..release import pushcheck
        for rname, url in W.push_targets(main):
            if not url or not visibility.is_private(url, now_ts, state_dir):
                sid, csha = W.stop_id("H2-publish_unknown", cr, rname)
                stop = W.pause_stop(pid, "H2-publish_unknown", cr, "H2-publish_unknown: the push URL of %s is not cached as private" % rname, rname, sha)
                return _res("stopped", "Hard stop %s (H2-publish_unknown): the push URL of remote %s is not confirmed private. Nothing is merged. The autopilot paused." % (stop["id"], rname),
                            stop=stop, rule="H2")
            res = pushcheck.check(rname, url, "refs/heads/%s %s refs/heads/%s %s" % (mb, tip, mb, "0" * 40), cwd=main, now=None)
            if res.refused:
                stop = W.pause_stop(pid, "H2-push_guard", cr, "H2-push_guard: %s" % (res.lines[0] if res.lines else "push-check refused")[:160], rname, sha)
                return _res("stopped", "Hard stop %s (H2-push_guard): the registry's push guard refuses the push to %s (%s). Nothing is merged. The autopilot paused." % (
                    stop["id"], rname, res.rule), stop=stop, rule="H2")
            targets.append((rname, url))
    if not already:
        # H3: re-verify immediately before the merge, then merge the SHA that every check above looked at
        if W.rev(main, "refs/heads/" + branch) != tip or W.rev(main, "HEAD") != head_main:
            stop = W.pause_stop(pid, "deliver-diverged", cr, "the branch or main moved during the delivery checks", tip[:12], sha)
            return _res("stopped", "Stop %s: %s or main moved while the delivery was checked. Nothing was merged. The autopilot paused." % (stop["id"], branch), stop=stop, rule="diverged")
        rc, _o = W.git(main, ["merge", "--ff-only", tip])
        if rc != 0:
            return _res("refused", "git merge --ff-only failed")
        if W.rev(main, "HEAD") != tip:
            stop = W.pause_stop(pid, "deliver-diverged", cr, "main is not at the checked commit after the merge", tip[:12], sha)
            return _res("stopped", "Stop %s: main is not at the checked commit after the merge. Nothing is pushed. The autopilot paused." % stop["id"], stop=stop, rule="diverged")
        try:
            S.set_progress(pid, merged="%s %s %s" % (cr, tip, tip))         # the engine's own record, BEFORE any push (a retry after a crash needs it)
        except Exception as e:
            events.emit("autopilot.error", {"where": "merged_record", "error": type(e).__name__}, project=pid, src="autopilot")
    elif W.rev(main, "HEAD") != head_main:
        return _res("refused", "main moved during the delivery checks")
    head = W.rev(main, "HEAD")
    pushed, perr = False, None
    if targets:
        pushed = True
        for rname, url in targets:
            rc, _o = W.git(main, ["push", "--", url, "%s:refs/heads/%s" % (tip, mb)], timeout=120, isolate=True)       # the checked URL, the checked commit, no global config
            if rc != 0:
                pushed, perr = False, rname
                break
    # the main log: the CR is delivered, the lease ends
    try:
        def fn(w):
            return None, engine.deliver_external(w, cr, {"kind": "engine", "by": "engine", "ts": int(S.now()), "data": {"merged": branch, "head": (head or "")[:12], "secret_scan": "skipped" if scan_note else "done"}})
        store.transact(main, fn, do_render=False)
    except Exception as e:
        events.emit("autopilot.error", {"where": "deliver_log", "error": type(e).__name__}, project=pid, src="autopilot")
    events.emit("autopilot.merged", {"cr": cr, "branch": branch, "head": (head or "")[:12], "pushed": pushed}, project=pid, src="autopilot")
    W.log_decision(pid, sha, cr, "deliver", "deliver_ff", "%s fast-forwarded into %s at %s%s" % (branch, mb, (head or "")[:12], ", pushed" if pushed else ", not pushed"))
    if perr:
        stop = W.pause_stop(pid, "H2-publish_failed", cr, "push to %s failed after the merge" % perr, perr, sha)
        return _res("stopped", "Stop %s: %s is merged into %s but the push to %s failed. The autopilot paused." % (stop["id"], cr, mb, perr),
                    stop=stop, rule="H2", head=head, merged=True)
    return _res("merged", "%s merged into %s (fast-forward) at %s%s%s." % (cr, mb, (head or "")[:12], ", pushed" if pushed else ", not pushed", scan_note), head=head, pushed=pushed, merged=True)


def _waiting(pid, cr, why):
    try:
        events.emit("autopilot.merge_waiting", {"cr": cr, "why": why[:120]}, project=pid, src="autopilot")
    except ShipmiracleError:
        pass


def finish_cr(wt, cr, **kw) -> dict:
    """ff_merge, then the next step of the run: the next CR of the charter (branch switch + import + lease) or the end (ended:done).
    Adds "next": {"cr","branch","base"} | None and "ended": bool to a merged result."""
    r = ff_merge(wt, cr, **kw)
    if r["status"] != "merged":
        return r
    info = W.inspect(wt)
    pid = info["pid"]
    ok, _why, charter, st = S.check(pid)
    if not ok:
        r["next"], r["ended"] = None, False
        return r
    standing = S.is_standing(st)
    if standing and int(st["seg"]["crs_started"]) >= int(charter["crs_day"]):
        if S.pause_for(pid, "day_limit"):                        # option C: the request that was running may finish; the next one waits for the next check-in
            events.emit("autopilot.paused", {"reason": "day_limit", "label": "crs_day"}, project=pid, src="autopilot")
        S.set_progress(pid, cr=None)                             # the delivered request is done; the next check-in starts the next admitted one
        r.update(next=None, ended=False, text=r["text"] + " The day's limit of %d requests is reached: autopilot paused until the next check-in." % int(charter["crs_day"]))
        return r
    try:
        nxt = W.switch_next(pid, info["main"], info["wt"], charter, st["charter_sha"], cr)
    except ShipmiracleError as e:
        stop = W.pause_stop(pid, "deliver-next_cr", cr, "cannot start the next change request: %s" % str(e)[:100], str(e)[:60], st["charter_sha"])
        r.update(status="stopped", text=r["text"] + " Stop %s: the next change request could not be started (%s)." % (stop["id"], e), stop=stop, next=None, ended=False)
        return r
    if nxt is None and standing:                                 # option C: no admitted work left is not the end; the run waits for the owner's next admit
        S.set_progress(pid, cr=None)
        r.update(next=None, ended=False, text=r["text"] + " Autopilot is waiting for requests: you admit one with `shipm autopilot admit CR-x`.")
        return r
    if nxt is None:
        S.end(pid, "done")
        events.emit("autopilot.ended", {"reason": "done", "label": "charter_complete"}, project=pid, src="autopilot")
        r.update(next=None, ended=True, text=r["text"] + " The charter is complete: autopilot ended (done).")
    else:
        r.update(next=nxt, ended=False, text=r["text"] + " Next change request: %s on branch %s." % (nxt["cr"], nxt["branch"]))
    return r
