"""`shipm autopilot ...` (shipmiracle/cli.py only parses and delegates here). Phase 6 spec section 1, entry points.

  charter set --goal G --scope S [--budget 10] [--time 3h] [--deps none|a,b] --ends CR-012..CR-014 | charter show | charter clear
  start | stop | allow H-xxxxxx | resume | show

Every action changes things only for the owner: paths.require_owner (refused inside a Claude Code chat) except `show`. `start` also needs a
terminal and a typed `yes` after the charter is printed (`--yes` only when paths.sandboxed(), i.e. tests). In T1 `start` validates the
prerequisites, moves the state set -> running (started, expires, budget_start) and creates the auto worktree + branch for the first CR of the charter
(worktree.start_run: import into the worktree's own log, lease in the main log, base in the state); the chat is launched only with --launch (a terminal).
`drop CR-x` = rollback before the merge (worktree remove, branch -D, lease released; never while running). Exit codes as the rest of shipm: 0 ok, 1 refused/failed check, 2 usage, 3 not found, 4 safety."""
from __future__ import annotations

import json
import os
import re
import sys

from .. import ShipmiracleError, NotFound, SafetyError, UsageError
from .. import config, events, owner, paths, registry
from ..playbook import cli as pbcli
from . import charter as ch
from . import standing as sg
from . import state as st
from . import worktree as wtm

ACTIONS = ("charter", "start", "stop", "allow", "resume", "drop", "show", "checkpoint", "admit", "probe")
RISK_LINE = "until i disable it"
CHARTER_ACTIONS = ("set", "show", "clear")


class Refused(ShipmiracleError):
    exit_code = 1


def _out(text="") -> None:
    sys.stdout.write(text + "\n")


def _is_tty() -> bool:
    """Seam for tests."""
    return sys.stdin.isatty() and sys.stdout.isatty()


def _ask(prompt) -> str:
    """Seam for tests."""
    sys.stdout.write(prompt)
    sys.stdout.flush()
    return sys.stdin.readline().strip()


def _project(a):
    """(Project, folder) of the MAIN project: a run belongs to the main checkout, never to a worktree."""
    pd = pbcli._project_arg(getattr(a, "project", None))
    p = pbcli._resolved(pd)
    if os.path.realpath(pd) != os.path.realpath(p.path):
        raise UsageError("autopilot belongs to the main project %s: run it there (--project %s)" % (p.name, p.name))
    return p


def _stand(p) -> bool:
    rec = _record(p.id)
    return bool(rec and ch.is_standing(rec["charter"]))


def _gate(p, verb, extra=""):
    """Locks 1 and 2 of the owner proof, before anything is printed (shipmiracle/owner.py)."""
    owner.gate(verb, "shipm autopilot %s%s --project %s" % (verb, extra, p.name))


def _select(p, rec=None, setting=None):
    """The owner check for this action (no UI): option C needs medium (or basic on a marked separate account), A/B need basic. None in a sandbox without SHIPMIRACLE_ENFORCE_OWNER."""
    standing = ch.is_standing(rec["charter"]) if rec else _stand(p)
    return owner.select(min_tier="medium" if standing else "basic", separate_ok=standing, setting=setting)


def _owner_check(a, sel, action, what, hint, reason, legacy_yes=False):
    """The typed yes (basic tier: the typed code REPLACES it) and then ONE presence check. Outside proof mode only the old typed yes, where the command always had one."""
    if sel is None:
        if legacy_yes:
            _typed_yes(a, what, hint)
        return
    if sel.tier != "basic":
        _typed_yes(a, what, hint)
    owner.touch(action, reason, sel=sel)


def _record(pid):
    rec = registry.autopilot_of(registry.entry(pid))
    if rec is None:
        return None
    ch.validate_record(rec)
    return rec


def _fields(a) -> dict:
    if not a.goal or not a.scope or not a.ends:
        raise UsageError("charter set needs --goal, --scope and --ends (optional: --budget 10, --time 3h, --deps none; or --until=disabled --day=4% --crs-day=3)")
    until, day, crs = getattr(a, "until", None), getattr(a, "day", None), getattr(a, "crs_day", None)
    out = {"goal": ch.clean_goal(a.goal), "scope": ch.clean_scope(a.scope), "ends": ch.clean_ends(a.ends),
           "budget": ch.clean_budget(a.budget if a.budget is not None else ch.BUDGET_DEFAULT),
           "deps": ch.clean_deps(a.deps if a.deps is not None else "none")}
    if until is not None:
        if until != ch.UNTIL_DISABLED:
            raise UsageError("--until takes only the word: disabled")
        if a.time is not None:
            raise UsageError("a charter that runs until you disable it has no --time (it pauses every 24 hours for your yes)")
        out.update(until=ch.UNTIL_DISABLED, day=ch.clean_day(day if day is not None else ch.DAY_DEFAULT), crs_day=ch.clean_crs(crs if crs is not None else ch.CRS_DEFAULT))
        return out
    if day is not None or crs is not None:
        raise UsageError("--day and --crs-day belong to --until=disabled")
    out["time"] = ch.clean_time(a.time if a.time is not None else "%gh" % ch.TIME_DEFAULT)
    return out


def cmd_charter(a) -> int:
    ra = list(a.rargs or [])
    sub = ra[0] if ra else None
    if sub not in CHARTER_ACTIONS or len(ra) != 1:
        raise UsageError("charter needs one of: %s" % ", ".join(CHARTER_ACTIONS))
    p = _project(a)
    if sub == "set":
        paths.require_owner("shipm autopilot charter set")
        try:
            fields = _fields(a)                          # a malformed charter is refused before anything else (same refusal text as when it is stored)
        except ch.CharterError as e:
            raise Refused("Charter NOT set: %s" % e)
        if getattr(a, "until", None) is not None:        # a standing charter: setting it is an escalation (one touch, no typed line)
            hint = "shipm autopilot charter set --until=disabled --project %s ..." % p.name
            owner.gate("charter", hint)                  # locks 1 and 2 first
            if owner.proof_required():                   # D14 m4: everything the owner could be refused for is checked BEFORE the touch, so a touch is never spent on a charter that cannot be set
                ok, why = owner.standing_allowed()
                if not ok:
                    raise Refused("Charter NOT set: option C stays off: %s. Run the sandbox test and record it (docs/owner-steps/p6-autopilot.sh --record-p6-1 pass), or run `shipm owner mark-separate-account` on a separate user account." % why)
            bad = ch.prereq_failures(ch.prereqs(p.path, standing=True))
            if bad:
                raise Refused("Charter NOT set: prerequisites not met: " + "; ".join(bad))
            owner.touch("charter", "Shipmiracle: set an autopilot that keeps going until you disable it, on %s. Cancel if you did not just type this yourself." % p.name,
                        min_tier="medium", separate_ok=True)
        try:
            r = ch.store_charter(p.id, fields, "cli")
        except ch.CharterError as e:
            raise Refused("Charter NOT set: %s" % e)
        if a.json:
            _out(json.dumps({"v": 1, "id": r["charter"]["id"], "sha256": r["sha256"], "echo": r["echo"]}, ensure_ascii=False))
        else:
            _out(r["echo"])
        return 0
    if sub == "show":
        rec = _record(p.id)
        if rec is None:
            raise NotFound("no charter is set for %s" % p.name)
        if a.json:
            _out(json.dumps(dict(rec, v=1), sort_keys=True, ensure_ascii=False))
        else:
            c = rec["charter"]
            _out("charter %s (sha256 %s) set by %s" % (c["id"], rec["sha256"][:12], c["set_by"]))
            _out(ch.describe(c))
            _out("always excluded: " + ", ".join(ch.ALWAYS_EXCLUDED))
        return 0
    paths.require_owner("shipm autopilot charter clear")      # clear = Back to guided
    r = ch.clear(p.id)
    _out("charter cleared; the project is back to guided" if r["had_charter"] or r["was"] else "nothing to clear")
    return 0


RISKS = ("It works unattended, also at night, for up to 24 hours per yes.",
         "It merges finished work into main by itself after tests and review pass.",
         "It spends up to %(day)d%% of your weekly Claude limit a day, %(week)d%% a week; your own chats share that limit.",
         "Code its tests run can do anything your user account can (residual risk K11-K14 in the P6 spec).",
         "Only requests listed above, or that you admit later with `shipm autopilot admit`, are worked on.")


def _confirm(a, rec, main=None, skip_yes=False) -> None:
    c = rec["charter"]
    standing = ch.is_standing(c)
    _out("About to START autopilot on %s with this charter (sha256 %s):" % (c["project"], rec["sha256"][:12]))
    _out(ch.describe(c))
    _out("Always excluded: " + ", ".join(ch.ALWAYS_EXCLUDED))
    _out("Set by: %s%s" % (c["set_by"], " (chat session %s, prompt sha %s)" % (c["session8"], c["prompt_sha"][:12]) if c["set_by"] == "chat" else ""))
    if main is not None:                                  # every request the run is allowed to work on: id · title · who opened it (titles are data, control characters stripped)
        _out("Requests it may work on:")
        for ln in sg.requests_listing(main, c["ends"]):
            _out(ln)
    if standing:
        _out("")
        _out("This charter runs UNTIL YOU DISABLE IT. Risks:")
        for n, t in enumerate(RISKS, 1):
            _out("  %d. %s" % (n, t % {"day": c["day_pct"], "week": c["budget_pct_week"]}))
        _out("Stop it any time: Stop autopilot in the panel, `shipm autopilot stop`, or `charter: off` in a chat.")
    chat = c["set_by"] == "chat"
    if a.yes and chat and not getattr(a, "ack", None) == c["id"]:
        raise SafetyError("this charter was set from a chat: pass --ack %s (or type the id in a terminal) to start it" % c["id"])
    if a.yes:
        if not paths.sandboxed():
            raise SafetyError("--yes works only in tests (SHIPMIRACLE_TEST=1 with temp folders); start asks for a typed yes in a terminal")
        if standing and (getattr(a, "ack_risk", None) or "").strip().lower() != RISK_LINE:
            raise Refused("not started (the line 'until I disable it' was not given: --ack-risk in tests, typed in a terminal)")
        return
    if not _is_tty():
        raise SafetyError("start needs a terminal: run `shipm autopilot start` yourself and type yes (it is never started from a script or a chat)")
    if not skip_yes and _ask('Type "yes" to start: ') != "yes":          # at the typed-code tier the code (asked next) replaces this yes
        raise Refused("not started (you did not type yes)")
    if standing and _ask('Type "until I disable it" to confirm: ').strip().lower() != RISK_LINE:
        raise Refused("not started (the line 'until I disable it' did not match)")
    if chat and _ask("This charter was set from a chat, not by you in a terminal. Type its id (%s) to start: " % c["id"]) != c["id"]:
        raise Refused("not started (the charter id was not typed)")


def cmd_start(a) -> int:
    paths.require_owner("shipm autopilot start")
    p = _project(a)
    if a.yes and not paths.sandboxed():
        raise SafetyError("--yes is for tests only: run `shipm autopilot start --project %s` in Terminal or VS Code and type yes there." % p.name)
    _gate(p, "start")
    rec = _record(p.id)
    if rec is None:
        raise NotFound("no charter is set for %s: shipm autopilot charter set ..." % p.name)
    sel = _select(p, rec)
    cur = st.settle(p.id)
    if cur is None or cur["state"] != "set" or cur["charter_sha"] != rec["sha256"]:
        now_is = "absent" if cur is None else cur["state"] + (" (%s)" % cur["ended_reason"] if cur["ended_reason"] else "")
        raise Refused("the run is %s, not 'set' with this charter: set the charter again" % now_is)
    if ch.is_standing(rec["charter"]) and ch.other_standing(p.id) is not None:
        raise Refused("autopilot NOT started: another project already has a charter that runs until you disable it (one at a time)")
    bad = [t for t in ch.prereq_failures(ch.prereqs(p.path, standing=_stand(p))) if not t.startswith("remote ")]      # the remote-is-private answer is renewed AFTER the owner has confirmed (m8)
    if bad:
        raise Refused("autopilot NOT started: " + "; ".join(bad))
    _confirm(a, rec, p.path, skip_yes=sel is not None and sel.tier == "basic")
    owner.touch("start", "Shipmiracle: start autopilot on %s%s. Cancel if you did not just type this yourself." % (p.name, " (keeps going until you disable it)" if ch.is_standing(rec["charter"]) else ""), sel=sel)
    ch.refresh_visibility(p.path)         # owner only; no network in tests
    bad = ch.prereq_failures(ch.prereqs(p.path, standing=_stand(p)))
    if bad:
        raise Refused("autopilot NOT started: " + "; ".join(bad))
    cur = st.start(p.id, rec["charter"], st.plan_reading())
    events.emit("autopilot.started", {"sha8": rec["sha256"][:8], "set_by": "cli"}, project=p.id, src="shipmiracle")
    cr = wtm.next_cr_id(p.path, rec["charter"])
    if cr is None:
        st.end(p.id, "owner")
        raise Refused("autopilot NOT started: none of the charter's change requests is open or queued and free (ends: %s)" % ", ".join(rec["charter"]["ends"]))
    try:
        info = wtm.start_run(p.id, p.path, rec["charter"], cr)
    except ShipmiracleError as e:
        st.end(p.id, "owner")
        raise Refused("autopilot NOT started: the worktree could not be created (%s)" % e)
    events.emit("autopilot.worktree_created", {"cr": cr, "branch": info["branch"]}, project=p.id, src="shipmiracle")
    if ch.is_standing(rec["charter"]):
        _out("autopilot state: running until you disable it (first check-in in 24 h, budget measured from %g%% of the week)" % cur["budget_start"]["pct"])
    else:
        _out("autopilot state: running (started, expires in %g h, budget measured from %g%% of the week)" % (rec["charter"]["time_h"], cur["budget_start"]["pct"]))
    _out("worktree %s on branch %s (change request %s); nothing is launched%s" % (info["wt"], info["branch"], cr, "" if getattr(a, "launch", False) else " (add --launch to open the auto chat)"))
    if getattr(a, "launch", False):
        return _launch(info["wt"])
    return 0


def _launch(wt) -> int:
    """Open the auto chat in the worktree with `/feature` as the first message. Terminal only; never in tests; the live run is the owner's step."""
    if os.environ.get("SHIPMIRACLE_TEST") == "1":
        raise SafetyError("--launch is never run under SHIPMIRACLE_TEST=1")
    if not _is_tty():
        raise SafetyError("--launch needs a terminal")
    import shutil
    import subprocess
    exe = os.path.join(os.path.expanduser("~"), ".local", "bin", "claude")
    exe = exe if os.path.exists(exe) else shutil.which("claude")
    if not exe:
        raise NotFound("claude is not installed")
    return subprocess.call([exe, "/feature"], cwd=wt)


def cmd_drop(a) -> int:
    paths.require_owner("shipm autopilot drop")
    ra = list(a.rargs or [])
    if len(ra) != 1:
        raise UsageError("drop needs the change request, like CR-012")
    p = _project(a)
    _gate(p, "drop", " " + ra[0])
    sel = _select(p)
    if sel is not None:
        _out("This removes the autopilot's work on %s (its worktree and branch)." % ra[0])
        _owner_check(a, sel, "drop", "dropping a request", "shipm autopilot drop %s --project %s" % (ra[0], p.name),
                     "Shipmiracle: drop %s from autopilot on %s. Cancel if you did not just type this yourself." % (ra[0], p.name))
    try:
        r = wtm.drop(p.id, p.path, ra[0])
    except UsageError as e:
        raise Refused(str(e))
    cur = st.read(p.id) if st.path(p.id).exists() else None
    if st.is_standing(cur) and cur["state"] != "ended":
        # option C: dropping one request does not end the standing run; it is remembered as dropped, its admission goes, the run goes on with the next admitted one
        def fn(c):
            c["dropped"] = (list(c.get("dropped") or []) + [ra[0]])[-50:]
            c.update(cr=None, worktree=None, branch=None, base=None)
            if c["state"] == "paused" and c.get("paused_reason") in st.RESUME_REASONS:
                c.update(state="running", paused_reason=None, stop=None)
            return c
        st.update(p.id, fn)
        sg.drop_admission(p.id, ra[0])
        rec = _record(p.id)
        if st.read(p.id)["state"] == "running" and rec:
            sg.start_idle(p.id, p.path, rec["charter"], rec["sha256"])
    elif cur is not None and cur["state"] != "ended":
        st.end(p.id, "owner")
    _out("dropped %s: worktree %s, branch %s, lease %s" % (ra[0], "removed" if r["removed_worktree"] else "was not there",
                                                         "deleted" if r["deleted_branch"] else "was not there", "released" if r["unleased"] else "kept"))
    return 0


def cmd_stop(a) -> int:
    paths.require_owner("shipm autopilot stop")
    p = _project(a)
    try:                                  # the lease on the run's CR ends with the run; the worktree and branch stay for the owner (drop removes them)
        cur = st.read(p.id) if st.path(p.id).exists() else None
        if cur is not None and cur.get("cr"):
            wtm.lease(p.path, cur["cr"], False)
    except ShipmiracleError:
        pass
    r = ch.clear(p.id)
    _out("autopilot stopped (ended: owner); charter cleared" if r["was"] else "nothing to stop")
    return 0


def cmd_allow(a) -> int:
    paths.require_owner("shipm autopilot allow")
    ra = list(a.rargs or [])
    if len(ra) != 1:
        raise UsageError("allow needs the stop id, like H-1a2b3c")
    p = _project(a)
    _gate(p, "allow", " " + ra[0])
    if st.check(p.id)[1] == "autopilot.full.enabled is off":
        raise Refused("autopilot.full.enabled is off: nothing can be allowed")
    sel = _select(p)
    if sel is not None:
        cur0 = st.read(p.id) if st.path(p.id).exists() else None
        stop0 = (cur0 or {}).get("stop") or {}
        _out("Stopped on %s (%s): %s" % (ra[0], sg.clean_text(stop0.get("rule") or "", 40), sg.clean_text(stop0.get("text") or "(no text)", 160)))
        _owner_check(a, sel, "allow", "allowing a stopped action", "shipm autopilot allow %s --project %s" % (ra[0], p.name),
                     "Shipmiracle: allow stop %s on %s (one action, 10 minutes). Cancel if you did not just type this yourself." % (ra[0], p.name))
    try:
        cur = st.allow(p.id, ra[0])
    except UsageError as e:
        raise Refused(str(e))
    al = cur["allow"][-1]
    events.emit("autopilot.allowed", {"stop": al["id"], "cmd8": al["cmd_sha"][:8]}, project=p.id, src="shipmiracle")
    _out("allowed %s once for that exact command, for 10 minutes; the run is running again" % al["id"])
    return 0


def cmd_resume(a) -> int:
    paths.require_owner("shipm autopilot resume")
    p = _project(a)
    _gate(p, "resume")
    cur = st.settle(p.id)
    if cur is None or cur["state"] != "paused":
        raise Refused("nothing to resume: the run is %s" % (cur["state"] if cur else "absent"))
    if _record(p.id) is None or _record(p.id)["sha256"] != cur["charter_sha"]:
        raise Refused("the charter does not match the run any more: stop it and set it again")
    if st.is_standing(cur) and cur.get("paused_reason") in st.CP_REASONS:
        raise Refused("this pause (%s) is cleared by the daily check-in only: shipm autopilot checkpoint" % cur["paused_reason"])
    bad = [t for ok, t in ch.prereqs(p.path, standing=_stand(p)) if not ok]
    if bad:
        raise Refused("not resumed: " + "; ".join(bad))
    if st.is_standing(cur) and cur.get("paused_reason") == "budget_unknown":
        plan = st.plan_reading()
        if plan is None or not plan["fresh"]:
            raise Refused("not resumed: the weekly budget still cannot be measured (plan.json is stale; open a chat so it refreshes)")
    if cur.get("worktree") and not os.path.isdir(cur["worktree"]):
        raise Refused("not resumed: the worktree %s is gone (shipm autopilot stop)" % cur["worktree"])
    sel = _select(p)
    if sel is not None:
        _out("Paused because: %s. Resuming lets the autopilot work again." % (cur.get("paused_reason") or (cur.get("stop") or {}).get("rule") or "a stop"))
        _owner_check(a, sel, "resume", "resuming", "shipm autopilot resume --project %s" % p.name,
                     "Shipmiracle: resume autopilot on %s. Cancel if you did not just type this yourself." % p.name)
    try:
        st.resume(p.id)
        if st.is_standing(cur) and cur.get("paused_reason") == "budget_unknown":
            st.rebase_week(p.id, st.plan_reading())           # M2: the owner's resume re-reads the weekly window
    except UsageError as e:
        raise Refused(str(e))
    events.emit("autopilot.resumed", {"set_by": "cli"}, project=p.id, src="shipmiracle")
    _out("autopilot state: running")
    return 0


def _typed_yes(a, what, hint=None) -> None:
    """The owner's typed yes in a terminal; --yes only when sandboxed (tests). Never from a script or a chat. ONE line, the same everywhere."""
    if a.yes:
        if not paths.sandboxed():
            raise SafetyError("--yes is for tests only: run `%s` in Terminal or VS Code and type yes there." % (hint or "the command"))
        return
    if not _is_tty():
        raise SafetyError("This needs you at a terminal (%s): run `%s` in Terminal or VS Code and type yes." % (what, hint or "the command"))
    if _ask('Type "yes" to continue: ') != "yes":
        raise Refused("Nothing was changed (you did not type yes).")


def cmd_checkpoint(a) -> int:
    paths.require_owner("shipm autopilot checkpoint")
    p = _project(a)
    _gate(p, "checkpoint")
    rec = _record(p.id)
    sel = _select(p, rec)
    cur = st.settle(p.id)
    if rec is None or not ch.is_standing(rec["charter"]) or cur is None or not st.is_standing(cur):
        raise Refused("there is no run that lasts until you disable it for %s" % p.name)
    if cur["state"] != "paused" or cur.get("paused_reason") not in st.CP_REASONS:
        raise Refused("no daily check-in is waiting: the run is %s%s" % (cur["state"], " (%s)" % cur["paused_reason"] if cur.get("paused_reason") else ""))
    if cur["charter_sha"] != rec["sha256"]:
        raise Refused("the charter does not match the run any more: stop it and set it again")
    # refuse early (before asking for a yes) when the check-in is not allowed yet
    plan = st.plan_reading()
    try:
        if cur["paused_reason"] not in ("switch_off", "standing_off"):
            if plan is None or not plan["fresh"]:
                raise UsageError("plan.json is missing or older than 15 minutes: the weekly budget cannot be measured (open a chat so the status line refreshes it)")
            if st.now() < cur["seg"]["expires"]:
                raise UsageError("the next check-in is not due for %.1f h: the day slice is per 24 hours, a yes does not refill it" % ((cur["seg"]["expires"] - st.now()) / 3600.0))
            if cur["paused_reason"] == "week_limit" and plan["resets_at"] - cur["week"]["resets_at"] <= st.WINDOW_SLACK:
                raise UsageError("the weekly limit is reached and the week has not reset yet")
    except UsageError as e:
        raise Refused(str(e))
    bad = [t for t in ch.prereq_failures(ch.prereqs(p.path, standing=_stand(p))) if not t.startswith("remote ")]      # the remote answer is renewed after the yes and the touch (m8)
    if bad:
        raise Refused("not continued: " + "; ".join(bad))
    for ln in sg.last_segment_summary(p.id, p.path):
        _out(ln)
    line = owner.summary_line()
    if line:
        _out(line)
    _owner_check(a, sel, "checkpoint", "the daily check-in", "shipm autopilot checkpoint --project %s" % p.name,
                 "Shipmiracle: daily check-in for autopilot on %s (day %d). Cancel if you did not just type this yourself." % (p.name, int(cur["seg"]["n"])), legacy_yes=True)
    sg.prune_admissions(p.id, p.path)       # D14 m5: after the owner check, never before (a refused proof changes nothing)
    ch.refresh_visibility(p.path)         # owner only (like start): a check-in renews the 24 h "this remote is private" answer; no network in tests
    bad = ch.prereq_failures(ch.prereqs(p.path, standing=_stand(p)))
    if bad:
        raise Refused("not continued: " + "; ".join(bad))
    try:
        new = st.checkpoint(p.id, rec["charter"], plan)
    except UsageError as e:
        raise Refused(str(e))
    events.emit("autopilot.checkpoint", {"seg": int(new["seg"]["n"]), "sha8": rec["sha256"][:8]}, project=p.id, src="shipmiracle")
    started = sg.start_idle(p.id, p.path, rec["charter"], rec["sha256"])
    _out("autopilot keeps going for another 24 hours (check-in %d)%s" % (int(new["seg"]["n"]), "; started %s on %s" % (started["cr"], started["branch"]) if started else ""))
    return 0


def cmd_admit(a) -> int:
    """Admit one or several requests with ONE typed yes and ONE touch."""
    paths.require_owner("shipm autopilot admit")
    ra = list(dict.fromkeys(a.rargs or []))
    if not ra:
        raise UsageError("admit needs the request, like CR-015 (several are fine: CR-015 CR-016)")
    p = _project(a)
    _gate(p, "admit", " " + " ".join(ra))
    rec = _record(p.id)
    sel = _select(p, rec)
    if rec is None or not ch.is_standing(rec["charter"]):
        raise Refused("admit belongs to a run that lasts until you disable it")
    from ..playbook import engine, store
    work = store.load(p.path)
    found = []
    for cr in ra:
        if not re.fullmatch(r"CR-\d{3,6}", cr):
            raise UsageError("admit needs requests like CR-015, got %r" % cr[:20])
        c = engine.get_cr(work, cr)
        if c is None or c.get("status") not in ("open", "queued"):
            raise Refused("%s is not an open or queued request in %s" % (cr, p.name))
        found.append((cr, c))
    for cr, c in found:
        _out("%s · %s · opened in %s" % (cr, sg.clean_title(c["title"]), sg.opener_word(c)))
    _out("charter scope: " + ", ".join(rec["charter"]["scope"]))
    first = sg.clean_title(found[0][1]["title"], 50)
    _owner_check(a, sel, "admit", "admitting a request", "shipm autopilot admit %s --project %s" % (" ".join(ra), p.name),
                 "Shipmiracle: let autopilot work on %s %s%s on %s. Cancel if you did not just type this yourself." % (
                     found[0][0], first, " and %d more" % (len(found) - 1) if len(found) > 1 else "", p.name), legacy_yes=True)
    sg.prune_admissions(p.id, p.path)                       # m4: admissions of closed requests go away; D14 m5: only AFTER the owner check passed (a refused proof changes nothing)
    done = []
    for cr, _c in found:
        try:
            sg.admit(p.id, p.path, cr)
            done.append(cr)
        except ch.CharterError as e:
            raise Refused("%s%s" % ("admitted %s, then: " % ", ".join(done) if done else "", e))
    cur = st.settle(p.id)
    started = None
    if cur is not None and cur["state"] == "running" and not [t for t in ch.prereq_failures(ch.prereqs(p.path, standing=_stand(p)))]:        # m6: only from a running run whose prerequisites hold
        started = sg.start_idle(p.id, p.path, rec["charter"], rec["sha256"])
    _out("admitted %s%s" % (", ".join(done), "; autopilot started %s on %s" % (started["cr"], started["branch"]) if started else "; they are worked on after the current request"))
    return 0


def cmd_probe(a) -> int:
    """`shipm autopilot probe pass|fail [--lines 1,2,..,7]`: record the owner's P6-1 sandbox test (docs/owner-steps/p6-autopilot.sh --record-p6-1). One typed yes, one touch."""
    paths.require_owner("shipm autopilot probe")
    ra = list(a.rargs or [])
    if len(ra) != 1 or ra[0] not in ("pass", "fail"):
        raise UsageError("probe needs pass or fail, like: shipm autopilot probe pass --lines 1,2,3,4,5,6,7")
    lines = [x.strip() for x in (getattr(a, "lines", None) or "").split(",") if x.strip()]
    owner.gate("probe", "shipm autopilot probe %s --lines %s" % (ra[0], ",".join(lines) or "1,2,3,4,5,6,7"))
    if ra[0] == "pass" and sorted(lines) != list(owner.P61_LINES):
        raise Refused("A pass needs all seven lines of the sandbox test: --lines 1,2,3,4,5,6,7 (or use a throwaway account instead).")
    _out("Record the sandbox test (P6-1) as %s%s. Option C can be switched on for 30 days after a full pass." % (ra[0], " (lines " + ",".join(lines) + ")" if lines else ""))
    sel = owner.select(setting="basic-ok")          # the best check that works now: a dead sensor never locks the owner out, a working one cannot be skipped
    _owner_check(a, sel, "probe", "recording the sandbox test", "shipm autopilot probe %s --lines %s" % (ra[0], ",".join(lines)),
                 "Shipmiracle: record the autopilot sandbox test as %s. Cancel if you did not just type this yourself." % ra[0], legacy_yes=True)
    try:
        owner.record_probe(ra[0], lines)
    except owner.OwnerRefused as e:
        raise Refused(str(e))
    _out("recorded")
    return 0


def cmd_show(a) -> int:
    p = _project(a)
    snap = st.snapshot(p.id)
    if a.json:
        _out(json.dumps({"v": 1, "autopilot": snap}, sort_keys=True, ensure_ascii=False))
        return 0
    if snap is None:
        _out("no autopilot run for %s (switch autopilot.full.enabled is %s)" % (p.name, "on" if config.get("autopilot.full.enabled") is True else "off"))
        return 0
    _out("autopilot %s: %s%s" % (p.name, snap["state"], " (%s)" % snap["ended_reason"] if snap["ended_reason"] else ""))
    c = snap["charter"]
    if c:
        _out("charter %s (%s): %s" % (c["id"], c["sha8"], c["goal"]))
    b, t = snap["budget"], snap["time"]
    _out("budget: %s of %s%% (%s) · time left: %s of %s s · decisions: %d" % (b["used_pct"], b["cap_pct"], b["source"], t["left_s"], t["cap_s"], snap["decisions"]))
    if snap["stop"]:
        _out("stopped on %(id)s (%(rule)s): %(text)s" % snap["stop"])
    return 0


def run(a) -> int:
    act = a.action
    if act == "charter":
        return cmd_charter(a)
    if act not in ACTIONS:
        raise UsageError("unknown autopilot action")
    return {"start": cmd_start, "stop": cmd_stop, "allow": cmd_allow, "resume": cmd_resume, "drop": cmd_drop, "show": cmd_show,
            "checkpoint": cmd_checkpoint, "admit": cmd_admit, "probe": cmd_probe}[act](a)


def owner_row():
    """(level, text) for bin/doctor and the Setup data (see shipmiracle.owner.row)."""
    return owner.row()


def run_owner(a) -> int:
    """`shipm owner status` (read-only: which owner check this computer can give) and `shipm owner mark-separate-account` (confirmed)."""
    if a.action == "status":
        name, tier = owner.best()
        setting = owner.presence_setting()
        states = {p.name: p.probe() for p in owner.PROVIDERS}
        lvl, txt = owner_row()
        if getattr(a, "line", False):
            _out("%s\t%s" % (lvl, txt))
            return 0
        if a.json:
            _out(json.dumps({"v": 1, "best": name, "tier": tier, "setting": setting, "providers": states, "separate_account": owner.separate_account(),
                             "platform": sys.platform, "row": {"level": lvl, "text": txt}}, sort_keys=True))
            return 0
        _out(txt)
        _out("Setting owner.presence = %s; separate account marker: %s" % (setting, "yes" if owner.separate_account() else "no"))
        if tier == "none" and sys.platform == "win32":
            _out("Windows: run Shipmiracle inside WSL 2.")
        return 0
    path = owner.mark_separate_account()
    _out("marked: %s (option C may now use the typed code on this account)" % path)
    return 0
