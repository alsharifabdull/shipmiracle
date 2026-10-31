"""Runtime state of a full-autopilot run: `<state>/v1/autopilot/<pid>.json` (0600, written atomically under the flock `<pid>.lock`).

pid = the id of the MAIN project (the charter lives in its registry entry, see charter.py). This file is engine-only: the owner CLI
(shipm autopilot ...) and, later, the hooks and the engine write it; nothing a model can write is ever read as state.

States: set (charter stored, not started; lapses 24 h after set) -> running (started; ends at started + time_h) <-> paused (a hard stop
or the switch went off) -> ended (ended_reason: done | time | budget | owner | lapsed). `active()` is the only yes/no the hooks use:
registry sha == recomputed sha == state.charter_sha, state running, not expired, ended_reason null, switch on.

Budget math (spec section 4): used = current weekly % - start; after a window reset (resets_at moved on) used = (last % seen in the old
window - start) + current. plan.json older than 15 minutes (or missing/odd) means "unknown" and counts as reached (H8-budget_unknown).
Clock: `now()`; SHIPMIRACLE_TEST_NOW (epoch seconds) is honoured only under SHIPMIRACLE_TEST=1 with CLAUDECODE unset and every state/config/workspace/dev/HOME path in the temp folder (paths.sandboxed())."""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

from .. import NotFound, SafetyError, SchemaError, UsageError
from .. import config, events, paths, registry
from .. import state as core

STATES = ("set", "running", "paused", "ended")
END_REASONS = ("done", "time", "budget", "owner", "lapsed")
LAPSE_S = 24 * 3600
PLAN_FRESH_S = 15 * 60
ALLOW_S = 10 * 60
SEG_S = 24 * 3600                      # option C: one segment (the owner's yes covers this long)
CP_LAPSE_S = 7 * 24 * 3600             # option C: paused at a check-in this long without the owner's yes = ended:lapsed
CP_REASONS = ("checkpoint", "day_limit", "week_limit", "switch_off", "standing_off")      # option C pauses that only `shipm autopilot checkpoint` clears
RESUME_REASONS = ("qa_fail", "review_reject", "unknown_request", "budget_unknown")   # option C pauses that `shipm autopilot resume` (or drop) clears
C_PAUSES = CP_REASONS + RESUME_REASONS
NEAR = 0.9
MAX_SESSIONS = 50
MAX_ALLOW = 5
WINDOW_SLACK = 60                      # resets_at values closer than this are the same weekly window
HID_RE = re.compile(r"H-[0-9a-f]{6}")
PID_RE = re.compile(r"[0-9a-f]{12}")
SHA_RE = re.compile(r"[0-9a-f]{64}")
_PROGRESS = ("cr", "branch", "worktree", "base", "merged")        # merged: "<cr> <tip sha> <main head sha>" written by deliver BEFORE the push
_BASE_RE = re.compile(r"[0-9a-f]{40,64}")


def now() -> float:
    """Wall clock; the test clock only under SHIPMIRACLE_TEST=1."""
    if os.environ.get("SHIPMIRACLE_TEST") == "1" and os.environ.get("SHIPMIRACLE_TEST_NOW") and "CLAUDECODE" not in os.environ and paths.sandboxed():
        try:
            return float(os.environ["SHIPMIRACLE_TEST_NOW"])
        except ValueError:
            pass
    return time.time()


# ---------------------------------------------------------------- files

def _check_pid(pid) -> str:
    if not isinstance(pid, str) or not PID_RE.fullmatch(pid):
        raise UsageError("not a project id")
    return pid


def folder(base=None) -> Path:
    """<state>/v1/autopilot (created 0700)."""
    b = Path(base) if base is not None else paths.state_dir()
    paths.assert_isolated(b)
    return core.ensure_dir(core.ensure_root(b) / "autopilot")


def path(pid, base=None) -> Path:
    b = Path(base) if base is not None else paths.state_dir()
    return b / "v1" / "autopilot" / (_check_pid(pid) + ".json")


def blank(charter_sha, set_ts) -> dict:
    return {"v": 1, "charter_sha": charter_sha, "state": "set", "set_ts": int(set_ts), "started": None, "expires": int(set_ts) + LAPSE_S,
            "budget_start": None, "last_pct": None, "used_pct": None, "worktree": None, "branch": None, "base": None, "cr": None, "decisions": 0,
            "stop": None, "paused_reason": None, "allow": [], "sessions": [], "ended_reason": None, "ended_ts": None}


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _seg_ok(sg) -> bool:
    return sg is None or (isinstance(sg, dict) and _num(sg.get("n")) and _num(sg.get("start")) and _num(sg.get("expires")) and _num(sg.get("crs_started"))
                          and isinstance(sg.get("budget_start"), dict) and _num(sg["budget_start"].get("pct")) and _num(sg["budget_start"].get("resets_at")))


# ---- the run's own ledger (M1/m5): <state>/v1/autopilot-ledger.jsonl, appended by the engine's CLI paths only (start, checkpoint, admit). It is what `seg.n` and the
# admissions are checked against, so editing the state file alone (or the registry alone) is noticed. Same-uid code can still write both files (documented residual R1).
def ledger_path(base=None) -> Path:
    b = Path(base) if base is not None else paths.state_dir()
    return b / "v1" / "autopilot-ledger.jsonl"


def ledger_append(pid, kind, **data) -> None:
    folder()
    line = (json.dumps(dict(data, pid=pid, kind=kind, ts=int(data.get("ts") or now())), sort_keys=True) + "\n").encode("utf-8")
    p = ledger_path()
    with core.lock_file(p.parent / "autopilot-ledger.lock"):
        fd = os.open(str(p), os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
        try:
            os.write(fd, line)
        finally:
            os.close(fd)


def ledger_read(pid, base=None) -> list:
    try:
        raw = core.read_bytes_nofollow(ledger_path(base)).decode("utf-8", "replace")
    except (FileNotFoundError, SchemaError, SafetyError, OSError):
        return []
    out = []
    for ln in raw.splitlines():
        try:
            d = json.loads(ln)
        except ValueError:
            continue
        if isinstance(d, dict) and d.get("pid") == pid:
            out.append(d)
    return out


def sanity(pid, st, at=None, base=None):
    """M1: '' or the reason a STANDING state file looks edited: the segment must be 24 h long, may not start in the future, its number must be 1 + the check-ins in the
    ledger since the run started, `started` and the week window may not lie in the future beyond a little slack."""
    if not is_standing(st):
        return ""
    at = now() if at is None else at
    sg = st["seg"]
    if sg["n"] < 1 or int(sg["n"]) != sg["n"]:
        return "the segment number is not valid"
    if abs(sg["expires"] - (sg["start"] + SEG_S)) > 1:
        return "the segment is not 24 hours long"
    if sg["start"] > at + 300 or (isinstance(st.get("started"), (int, float)) and st["started"] > at + 300):
        return "the run starts in the future"
    wk = st.get("week")
    if isinstance(wk, dict) and wk["resets_at"] > at + 8 * 86400:
        return "the weekly window ends too far ahead"
    rows = ledger_read(pid, base)
    starts = [i for i, r in enumerate(rows) if r.get("kind") == "start"]
    if not starts:
        return "the ledger has no record of this run's start"
    cps = sum(1 for r in rows[starts[-1] + 1:] if r.get("kind") == "checkpoint")
    if int(sg["n"]) != 1 + cps:
        return "the segment number does not match the check-ins on record"
    marks = [r for r in rows[starts[-1]:] if r.get("kind") in ("start", "checkpoint")]
    last = marks[-1].get("ts")
    if not isinstance(last, (int, float)) or abs(sg["start"] - last) > 120:
        return "the segment does not start when the ledger says its check-in happened"          # a segment slid forward by editing start and expires together
    return ""


def is_standing(st) -> bool:
    """A state file of an option C run (it carries its segment)."""
    return isinstance(st, dict) and isinstance(st.get("seg"), dict)


def _check_shape(d) -> dict:
    """SchemaError unless d looks like a state file this module wrote (types of the fields every decision reads)."""
    ok = (isinstance(d, dict) and d.get("v") == 1 and isinstance(d.get("charter_sha"), str) and SHA_RE.fullmatch(d["charter_sha"])
          and d.get("state") in STATES and _num(d.get("expires")) and (d.get("started") is None or _num(d["started"]))
          and (d.get("ended_reason") is None or d["ended_reason"] in END_REASONS)
          and isinstance(d.get("allow"), list) and isinstance(d.get("sessions"), list)
          and (d.get("stop") is None or isinstance(d["stop"], dict)) and (d.get("budget_start") is None or isinstance(d["budget_start"], dict))
          and _seg_ok(d.get("seg")) and (d.get("week") is None or (isinstance(d["week"], dict) and _num(d["week"].get("resets_at")) and _num(d["week"].get("start_pct")))))
    if not ok:
        raise SchemaError("autopilot state file has an unexpected shape")
    return d


def read(pid, base=None):
    """The state dict, or None when there is no file. SchemaError when the file is damaged (callers treat that as 'not active')."""
    p = path(pid, base)
    try:
        raw = core.read_bytes_nofollow(p)
    except FileNotFoundError:
        return None
    try:
        d = json.loads(raw.decode("utf-8"))
    except ValueError:
        raise SchemaError("autopilot state file is not valid JSON")
    _check_shape(d)
    why = sanity(pid, d, None, base)
    if why:
        raise SchemaError("state file looks edited: %s" % why)
    return d


def update(pid, fn, base=None):
    """Read-modify-write under the lock. fn(state or None) returns the new dict (or None = leave as it is). Returns what is stored."""
    folder(base)
    p = path(pid, base)
    with core.lock_file(p.parent / (pid + ".lock")):
        cur = read(pid, base)
        new = fn(json.loads(json.dumps(cur)) if cur is not None else None)
        if new is None or new == cur:
            return cur
        _check_shape(new)
        core.atomic_write(p, (json.dumps(new, sort_keys=True, indent=1) + "\n").encode("utf-8"), 0o600)
        return new


def delete(pid, base=None) -> None:
    folder(base)
    p = path(pid, base)
    with core.lock_file(p.parent / (pid + ".lock")):
        try:
            os.unlink(p)
        except FileNotFoundError:
            pass


# ---------------------------------------------------------------- plan.json and budget

def plan_reading(at=None, base=None):
    """{"pct", "resets_at", "age", "fresh"} from <state>/plan.json (written by the status line), or None when absent or odd.
    fresh = written at most 15 minutes ago (a stamp more than 60 s in the future is not fresh) and carries rate_limits.seven_day."""
    at = now() if at is None else at
    b = Path(base) if base is not None else paths.state_dir()
    try:
        d = json.loads(core.read_bytes_nofollow(b / "plan.json").decode("utf-8"))
        sd = d["rate_limits"]["seven_day"]
        pct, resets, written = sd["used_percentage"], sd["resets_at"], d["at"]
    except (OSError, ValueError, KeyError, TypeError, AttributeError, SafetyError, SchemaError):
        return None
    if not (_num(pct) and _num(resets) and _num(written)) or not 0 <= pct <= 100:
        return None
    age = at - written
    return {"pct": float(pct), "resets_at": float(resets), "age": age, "fresh": -60 <= age <= PLAN_FRESH_S}


def used_pct(st, plan):
    """(used percent of the week since the start, source). Source "unknown" (used None) when the start was not recorded, plan.json is
    missing/stale, or its window is older than the start's. Never negative."""
    bs = st.get("budget_start") if isinstance(st, dict) else None
    if not isinstance(bs, dict) or not _num(bs.get("pct")) or not _num(bs.get("resets_at")) or plan is None or not plan["fresh"]:
        return None, "unknown"
    cur, r = plan["pct"], plan["resets_at"]
    if abs(r - bs["resets_at"]) <= WINDOW_SLACK:
        used = cur - bs["pct"]
    elif r > bs["resets_at"]:
        last = st.get("last_pct") if _num(st.get("last_pct")) else bs["pct"]
        used = (last - bs["pct"]) + cur
    else:
        return None, "unknown"
    return round(max(0.0, used), 2), "plan.json"


def limits(st, charter, plan, at=None) -> dict:
    """Budget and time against the charter caps. *_reached: stop everything (H8); *_near: >= 90 %, no new stage. A budget that cannot be
    measured counts as reached."""
    at = now() if at is None else at
    if charter.get("until") == "disabled":
        return standing_limits(st, charter, plan, at)
    cap = float(charter["budget_pct_week"])
    used, src = used_pct(st, plan)
    tcap = float(charter["time_h"]) * 3600.0
    started = st.get("started")
    elapsed = (at - started) if _num(started) else 0.0
    return {"used_pct": used, "cap_pct": cap, "source": src,
            "budget_unknown": used is None, "budget_reached": used is None or used >= cap,
            "budget_near": used is not None and used >= NEAR * cap,
            "cap_s": tcap, "left_s": max(0.0, tcap - elapsed) if _num(started) else tcap,
            "time_reached": _num(started) and elapsed >= tcap, "time_near": _num(started) and elapsed >= NEAR * tcap}


# ---------------------------------------------------------------- option C: segments, day slice, week window, check-ins

def _seg_view(st):
    """The segment as a budget_start/last_pct pair, so the A/B used_pct() maths serves the day slice too."""
    sg = st.get("seg") or {}
    return {"budget_start": sg.get("budget_start"), "last_pct": sg.get("last_pct")}


WEEK_S = 7 * 86400
WEEK_TOL = 3600


def week_roll(wk, plan, at=None) -> str:
    """M2: 'same' (the stored window), 'rolled' (a new window: the stored end plus k whole weeks, within an hour, and not further than a week and an hour ahead of now) or 'bad'
    (anything else: a stale, forged or jumpy resets_at). 'bad' pauses the run (budget_unknown); the owner's resume re-reads the week."""
    at = now() if at is None else at
    d = plan["resets_at"] - wk["resets_at"]
    if abs(d) <= WINDOW_SLACK:
        return "same"
    if d < 0:
        return "bad"
    k = round(d / WEEK_S)
    if k >= 1 and abs(d - k * WEEK_S) <= WEEK_TOL and plan["resets_at"] <= at + WEEK_S + WEEK_TOL:
        return "rolled"
    return "bad"


def week_used(st, plan, at=None):
    """Percent of the week spent in the CURRENT weekly window since the run first saw it (restarts at 0 when the window rolls over), or None when unknown or the window moved
    in a way week_roll() does not accept."""
    wk = st.get("week")
    if not isinstance(wk, dict) or plan is None or not plan["fresh"]:
        return None
    roll = week_roll(wk, plan, at)
    if roll == "same":
        return round(max(0.0, plan["pct"] - wk["start_pct"]), 2)
    if roll == "rolled":
        return 0.0                                  # a new window: observe() re-bases the week at the first reading
    return None


def rebase_week(pid, plan, at=None, base=None):
    """The owner's resume after a week window that could not be verified: the week is re-read from the current reading (usage restarts at 0)."""
    at = now() if at is None else at

    def fn(cur):
        if not is_standing(cur) or plan is None or not plan["fresh"]:
            return None
        cur["week"] = {"resets_at": plan["resets_at"], "start_pct": plan["pct"], "last_pct": plan["pct"]}
        return cur
    return update(pid, fn, base)


def standing_limits(st, charter, plan, at=None) -> dict:
    """Day slice, week cap and the segment clock of an option C run. Unknown budget counts as reached (the run pauses; it never ends)."""
    at = now() if at is None else at
    day_cap, wk_cap = float(charter["day_pct"]), float(charter["budget_pct_week"])
    day, src = used_pct(_seg_view(st), plan)
    wk = week_used(st, plan, at)
    unknown = day is None or wk is None
    sg = st.get("seg") or {}
    left = max(0.0, sg["expires"] - at) if _num(sg.get("expires")) else 0.0
    return {"used_pct": day, "cap_pct": day_cap, "source": src, "week_used_pct": wk, "week_cap_pct": wk_cap,
            "budget_unknown": unknown, "day_reached": day is not None and day >= day_cap, "week_reached": wk is not None and wk >= wk_cap,
            "budget_reached": unknown or (day >= day_cap) or (wk >= wk_cap),
            "budget_near": (day is not None and day >= NEAR * day_cap) or (wk is not None and wk >= NEAR * wk_cap),
            "cap_s": float(SEG_S), "left_s": left, "time_reached": False, "time_near": False,
            "segment_due": _num(sg.get("expires")) and at >= sg["expires"]}


def _fold_standing(cur, plan):
    """Fold a fresh plan.json into the segment and the week of an option C state (in place)."""
    if plan is None or not plan["fresh"]:
        return
    sg, wk = cur.get("seg"), cur.get("week")
    if isinstance(sg, dict):
        bs = sg["budget_start"]
        if plan["resets_at"] - bs["resets_at"] > WINDOW_SLACK:
            last = sg["last_pct"] if _num(sg.get("last_pct")) else bs["pct"]
            sg["budget_start"] = {"pct": round(-(last - bs["pct"]), 4), "resets_at": plan["resets_at"]}
        if abs(plan["resets_at"] - sg["budget_start"]["resets_at"]) <= WINDOW_SLACK:
            sg["last_pct"] = plan["pct"]
    if isinstance(wk, dict):
        roll = week_roll(wk, plan)
        if roll == "rolled":
            cur["week"] = {"resets_at": plan["resets_at"], "start_pct": plan["pct"], "last_pct": plan["pct"]}      # the week usage restarts at 0
        elif roll == "same":
            wk["last_pct"] = plan["pct"]
        # "bad": left as it is; week_used() then says unknown and the run pauses (budget_unknown)


def bump_crs(pid, base=None) -> dict:
    """One more request started in the current segment."""
    def fn(cur):
        if not is_standing(cur):
            return None
        cur["seg"]["crs_started"] = int(cur["seg"]["crs_started"]) + 1
        return cur
    return update(pid, fn, base)


def pause_for(pid, reason, at=None, base=None):
    """Option C pause with a named reason (checkpoint, day_limit, week_limit, budget_unknown, qa_fail, review_reject, unknown_request, switch_off).
    Returns True when this call made the transition (the caller emits the event once)."""
    if reason not in C_PAUSES:
        raise UsageError("unknown pause reason")
    hit = []

    def fn(cur):
        if cur is None or cur["state"] != "running":
            return None
        cur.update(state="paused", stop=None, paused_reason=reason, paused_ts=int(now() if at is None else at))
        hit.append(1)
        return cur
    update(pid, fn, base)
    return bool(hit)


def checkpoint(pid, charter, plan, at=None, base=None) -> dict:
    """The owner's daily yes (CLI, typed): paused on a check-in reason -> running in a NEW 24 h segment with a fresh day slice. Refused: before the
    segment is over (also after day_limit: the slice is per 24 h, not per yes), after week_limit while the weekly window has not reset, with a stale plan.json.
    switch_off continues the SAME segment (toggling the switch must not refill the day)."""
    at = now() if at is None else at
    if plan is None or not plan["fresh"]:
        raise UsageError("plan.json is missing or older than 15 minutes: the weekly budget cannot be measured (open a chat so the status line refreshes it)")

    def fn(cur):
        if not is_standing(cur):
            raise UsageError("a check-in belongs to a run that lasts until you disable it")
        if cur["state"] != "paused" or cur.get("paused_reason") not in CP_REASONS:
            raise UsageError("no daily check-in is waiting: the run is %s%s" % (cur["state"], " (%s)" % cur["paused_reason"] if cur.get("paused_reason") else ""))
        reason = cur["paused_reason"]
        wk = cur["week"]
        if reason in ("switch_off", "standing_off"):
            cur.update(state="running", paused_reason=None, stop=None, confirmed_ts=int(at))
            return cur
        if at < cur["seg"]["expires"]:
            raise UsageError("the next check-in is not due for %.1f h: the day slice is per 24 hours, a yes does not refill it" % ((cur["seg"]["expires"] - at) / 3600.0))
        if reason == "week_limit" and week_roll(wk, plan, at) != "rolled":
            raise UsageError("the weekly limit is reached and the week has not reset yet (it resets at %s)" % time.strftime("%a %H:%M", time.localtime(wk["resets_at"])))
        n = int(cur["seg"]["n"]) + 1
        roll = week_roll(wk, plan, at)
        if roll == "bad":
            raise UsageError("the weekly window could not be verified (its end moved by an unexpected amount): run `shipm autopilot resume` first, it re-reads the week")
        ledger_append(pid, "checkpoint", ts=int(at), seg=n)
        cur["seg"] = {"n": n, "start": int(at), "expires": int(at + SEG_S), "budget_start": {"pct": plan["pct"], "resets_at": plan["resets_at"]},
                      "last_pct": plan["pct"], "crs_started": 0}
        if roll == "rolled":
            cur["week"] = {"resets_at": plan["resets_at"], "start_pct": plan["pct"], "last_pct": plan["pct"]}
        cur.update(state="running", paused_reason=None, stop=None, paused_ts=None, expires=int(at + SEG_S), confirmed_ts=int(at), used_pct=0.0,
                   budget_start={"pct": plan["pct"], "resets_at": plan["resets_at"]}, last_pct=plan["pct"])
        return cur
    return update(pid, fn, base)


# ---------------------------------------------------------------- transitions

def create(pid, charter_sha, set_ts, base=None) -> dict:
    """New state `set` for a stored charter. A running or paused run is never replaced (stop it first); a set or ended file is."""
    def fn(cur):
        if cur is not None and cur["state"] in ("running", "paused"):
            raise UsageError("an autopilot run is %s: stop it first (shipm autopilot stop)" % cur["state"])
        return blank(charter_sha, set_ts)
    return update(pid, fn, base)


def start(pid, charter, plan, at=None, base=None) -> dict:
    """set -> running. Records started, expires (= started + time_h), budget_start from plan.json (must be fresh)."""
    at = now() if at is None else at
    if plan is None or not plan["fresh"]:
        raise UsageError("plan.json is missing or older than 15 minutes: the weekly budget cannot be measured (open a chat so the status line refreshes it)")

    def fn(cur):
        if cur is None or cur["state"] != "set":
            raise UsageError("nothing to start: the state is %s (set a charter first)" % ("absent" if cur is None else cur["state"]))
        if at >= cur["expires"]:
            raise UsageError("the charter lapsed (24 h without a start): set it again")
        if charter.get("until") == "disabled":
            cur.update(state="running", started=int(at), expires=int(at + SEG_S), budget_start={"pct": plan["pct"], "resets_at": plan["resets_at"]},
                       last_pct=plan["pct"], used_pct=0.0, confirmed_ts=int(at),
                       seg={"n": 1, "start": int(at), "expires": int(at + SEG_S), "budget_start": {"pct": plan["pct"], "resets_at": plan["resets_at"]},
                            "last_pct": plan["pct"], "crs_started": 0},
                       week={"resets_at": plan["resets_at"], "start_pct": plan["pct"], "last_pct": plan["pct"]})
            ledger_append(pid, "start", ts=int(at), seg=1)
            cur["paused_ts"] = None
            return cur
        cur.update(state="running", started=int(at), expires=int(at + float(charter["time_h"]) * 3600),
                   budget_start={"pct": plan["pct"], "resets_at": plan["resets_at"]}, last_pct=plan["pct"], used_pct=0.0)
        return cur
    return update(pid, fn, base)


def observe(pid, charter, plan=None, at=None, base=None):
    """Fold the current plan.json into the state of a running/paused run and return limits(). A window reset is folded into
    budget_start (pct = -(spent in the old window)) so that used = current + spent also after a second reset. None when no such run."""
    at = now() if at is None else at
    plan = plan_reading(at, base) if plan is None else plan
    out = {}

    def fn(cur):
        if cur is None or cur["state"] not in ("running", "paused"):
            return None
        if is_standing(cur):
            _fold_standing(cur, plan)
            u, _src = used_pct(_seg_view(cur), plan)
            if u is not None:
                cur["used_pct"] = u
            out["st"] = cur
            return cur
        if plan is not None and plan["fresh"] and isinstance(cur.get("budget_start"), dict):
            bs = cur["budget_start"]
            if plan["resets_at"] - bs["resets_at"] > WINDOW_SLACK:
                last = cur["last_pct"] if _num(cur.get("last_pct")) else bs["pct"]
                cur["budget_start"] = {"pct": round(-(last - bs["pct"]), 4), "resets_at": plan["resets_at"]}
            if abs(plan["resets_at"] - cur["budget_start"]["resets_at"]) <= WINDOW_SLACK:
                cur["last_pct"] = plan["pct"]
        u, _src = used_pct(cur, plan)
        if u is not None:
            cur["used_pct"] = u
        out["st"] = cur
        return cur
    update(pid, fn, base)
    return limits(out["st"], charter, plan, at) if "st" in out else None


def end(pid, reason, at=None, base=None) -> dict:
    """-> ended with a reason (done|time|budget|owner|lapsed). An already ended run keeps its first reason."""
    if reason not in END_REASONS:
        raise UsageError("unknown ending reason")
    at = now() if at is None else at

    def fn(cur):
        if cur is None or cur["state"] == "ended":
            return None
        cur.update(state="ended", ended_reason=reason, ended_ts=int(at))
        return cur
    return update(pid, fn, base)


def pause(pid, stop=None, reason="hard_stop", base=None) -> dict:
    """running -> paused. stop = {"id": "H-xxxxxx", "rule", "ts", "text", "cmd_sha"?} for a hard stop; reason is any short word otherwise."""
    if stop is not None:
        if not isinstance(stop, dict) or not HID_RE.fullmatch(str(stop.get("id", ""))):
            raise UsageError("a stop needs an id like H-1a2b3c")
        stop = {k: stop[k] for k in ("id", "rule", "ts", "text", "cmd_sha") if k in stop}
        if isinstance(stop.get("text"), str):
            stop["text"] = stop["text"][:200]

    def fn(cur):
        if cur is None or cur["state"] != "running":
            return None
        cur.update(state="paused", stop=stop, paused_reason=str(reason)[:40], paused_ts=int(now()))
        return cur
    return update(pid, fn, base)


def resume(pid, base=None) -> dict:
    """paused -> running (the caller checked the prerequisites). The stop is dropped; the same action would stop again."""
    def fn(cur):
        if cur is None or cur["state"] != "paused":
            raise UsageError("nothing to resume: the state is %s" % ("absent" if cur is None else cur["state"]))
        if is_standing(cur) and cur.get("paused_reason") in CP_REASONS:
            raise UsageError("this pause (%s) is cleared by the daily check-in only: shipm autopilot checkpoint" % cur["paused_reason"])
        cur.update(state="running", stop=None, paused_reason=None, paused_ts=None)
        return cur
    return update(pid, fn, base)


def allow(pid, hid, at=None, base=None) -> dict:
    """The owner's exact-id release: paused on stop `hid` -> running with ONE allow {id, cmd_sha, until = at + 10 min}. The stop must
    carry the command's cmd_sha (the hook records it); otherwise there is nothing to bind the allow to."""
    at = now() if at is None else at
    if not isinstance(hid, str) or not HID_RE.fullmatch(hid):
        raise UsageError("expected a stop id like H-1a2b3c")

    def fn(cur):
        stop = cur.get("stop") if cur else None
        if cur is None or cur["state"] != "paused" or not stop or stop.get("id") != hid:
            raise UsageError("no paused run is stopped on %s" % hid)
        sha = stop.get("cmd_sha")
        if not isinstance(sha, str) or not SHA_RE.fullmatch(sha):
            raise UsageError("stop %s recorded no command hash: nothing to allow (resume it, or end the run)" % hid)
        live = [a for a in cur["allow"] if isinstance(a, dict) and _num(a.get("until")) and a["until"] > at]
        live.append({"id": hid, "cmd_sha": sha, "until": int(at) + ALLOW_S})
        cur.update(state="running", stop=None, paused_reason=None, allow=live[-MAX_ALLOW:])
        return cur
    return update(pid, fn, base)


def consume_allow(pid, cmd_sha, at=None, base=None) -> bool:
    """True once for an allow whose cmd_sha matches and has not expired; the entry is removed (one-shot)."""
    at = now() if at is None else at
    hit = []

    def fn(cur):
        if cur is None:
            return None
        keep = []
        for a in cur["allow"]:
            if not hit and isinstance(a, dict) and a.get("cmd_sha") == cmd_sha and _num(a.get("until")) and a["until"] > at:
                hit.append(a)
            elif isinstance(a, dict) and _num(a.get("until")) and a["until"] > at:
                keep.append(a)
        if not hit:
            return None
        cur["allow"] = keep
        return cur
    update(pid, fn, base)
    return bool(hit)


def add_session(pid, sid8, base=None) -> None:
    if not isinstance(sid8, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,8}", sid8):
        raise UsageError("not a session prefix")

    def fn(cur):
        if cur is None or sid8 in cur["sessions"]:
            return None
        cur["sessions"] = (cur["sessions"] + [sid8])[-MAX_SESSIONS:]
        return cur
    update(pid, fn, base)


def bump_decisions(pid, base=None) -> None:
    def fn(cur):
        if cur is None:
            return None
        cur["decisions"] = int(cur.get("decisions") or 0) + 1
        return cur
    update(pid, fn, base)


def set_progress(pid, state_base=None, **kw) -> None:
    """cr / branch / worktree / base (commit the auto branch was created at) of the run; worktree.py sets them."""
    bad = set(kw) - set(_PROGRESS)
    if bad:
        raise UsageError("unknown progress field")
    if kw.get("base") is not None and not (isinstance(kw["base"], str) and _BASE_RE.fullmatch(kw["base"])):
        raise UsageError("base: a commit id")
    for k, v in kw.items():
        if v is not None and (not isinstance(v, str) or len(v) > 300 or any(ord(c) < 32 for c in v)):
            raise UsageError("%s: a short text without control characters" % k)

    def fn(cur):
        if cur is None:
            return None
        cur.update(kw)
        return cur
    update(pid, fn, state_base)


def _emit_paused(pid, reason) -> None:
    try:
        events.emit("autopilot.paused", {"reason": reason}, project=pid, src="autopilot")
    except Exception:
        pass


def settle(pid, charter=None, at=None, base=None):
    """Apply the time rules and persist them: set past its 24 h -> ended:lapsed; running/paused past `expires` -> ended:time; running with
    the switch off -> paused (fail closed). Returns the state (None when there is none). Never raises for a damaged file (returns None)."""
    at = now() if at is None else at
    try:
        cur = read(pid, base)
    except SchemaError:
        return None
    if cur is None or cur["state"] == "ended":
        return cur
    if is_standing(cur):
        if cur["state"] == "set":
            return end(pid, "lapsed", at, base) if at >= cur["expires"] else cur
        if cur["state"] == "paused" and ((cur.get("paused_reason") in CP_REASONS and at >= cur["seg"]["expires"] + CP_LAPSE_S)
                                         or (isinstance(cur.get("paused_ts"), (int, float)) and at >= cur["paused_ts"] + CP_LAPSE_S)):       # m7: any standing pause older than 7 days
            out = end(pid, "lapsed", at, base)                        # 7 days without the owner's yes: the standing charter goes with it
            try:
                registry.set_autopilot(pid, None, owner=False)
                events.emit("autopilot.charter_cleared", {"set_by": "cli", "was": "lapsed"}, project=pid, src="autopilot")
            except Exception:
                pass
            return out
        if cur["state"] == "running" and at >= cur["seg"]["expires"]:
            if pause_for(pid, "checkpoint", at, base):
                _emit_paused(pid, "checkpoint")
            return read(pid, base)
        if cur["state"] == "running" and config.get("autopilot.full.enabled") is not True:
            if pause_for(pid, "switch_off", at, base):
                _emit_paused(pid, "switch_off")
            return read(pid, base)
        if cur["state"] == "running" and config.get("autopilot.standing.enabled") is not True:      # option C needs its own switch (owner proof B2)
            if pause_for(pid, "standing_off", at, base):
                _emit_paused(pid, "standing_off")
            return read(pid, base)
        return cur
    if at >= cur["expires"]:
        return end(pid, "lapsed" if cur["state"] == "set" else "time", at, base)
    if cur["state"] == "running" and config.get("autopilot.full.enabled") is not True:
        return pause(pid, None, "switch_off", base)
    return cur


# ---------------------------------------------------------------- the one yes/no

def check(pid, at=None, base=None):
    """(ok, reason, charter, state). ok only when: a stored charter whose sha256 equals the recomputed sha and the state's charter_sha;
    the state is running, ended_reason null, now < expires; and autopilot.full.enabled is on. Pure read: nothing is written."""
    from . import charter as ch
    at = now() if at is None else at
    try:
        st = read(pid, base)
    except (SchemaError, SafetyError, OSError):
        return False, "the run state file is damaged", None, None
    if st is None:
        return False, "no autopilot run state", None, None
    try:
        rec = registry.autopilot_of(registry.entry(pid))
    except Exception:
        rec = None
    if rec is None:
        return False, "no charter in the registry", None, st
    try:
        ch.validate_record(rec)
    except UsageError as e:
        return False, "charter does not match its sha (%s)" % e, None, st
    if rec["sha256"] != st["charter_sha"]:
        return False, "charter sha differs from the run state", rec["charter"], st
    if st["ended_reason"] is not None or st["state"] == "ended":
        return False, "the run ended (%s)" % st["ended_reason"], rec["charter"], st
    if st["state"] != "running":
        return False, "the run is %s" % st["state"], rec["charter"], st
    if at >= st["expires"]:
        return False, "the run expired", rec["charter"], st
    if config.get("autopilot.full.enabled") is not True:
        return False, "autopilot.full.enabled is off", rec["charter"], st
    return True, "active", rec["charter"], st


def active(pid, at=None, base=None):
    """{"charter", "state"} when the run is active (see check), else None."""
    ok, _why, charter, st = check(pid, at, base)
    return {"charter": charter, "state": st} if ok else None


# ---------------------------------------------------------------- panel data (spec section 7)

def snapshot(pid, at=None, base=None):
    """The data contract of the panel (`p.autopilot`): {state, level, enabled, charter:{id,goal,scope,ends,set_by,sha8}|None, decisions,
    budget:{used_pct,cap_pct,source}, time:{left_s,cap_s}, stop:{id,rule,text,ts}|None, cr, branch, worktree, ended_reason}.
    None when there is no state file (or it is damaged). Read-only: the numbers come from plan.json now."""
    at = now() if at is None else at
    try:
        st = read(pid, base)
    except SchemaError as e:
        if str(e).startswith("state file looks edited"):
            return {"state": "invalid", "level": None, "enabled": config.get("autopilot.full.enabled") is True, "charter": None, "decisions": 0,
                    "budget": {"used_pct": None, "cap_pct": None, "source": "unknown"}, "time": {"left_s": None, "cap_s": None}, "stop": None, "cr": None, "branch": None,
                    "worktree": None, "ended_reason": None, "reason": "state_edited", "invalid": str(e)[:120]}
        return None
    except (SafetyError, OSError):
        return None
    if st is None:
        return None
    try:
        entry = registry.entry(pid)
    except Exception:
        entry = None
    rec = registry.autopilot_of(entry)
    c = rec["charter"] if rec else None
    level = (entry.get("playbook") or {}).get("autopilot") if isinstance(entry, dict) and isinstance(entry.get("playbook"), dict) else None
    out = {"state": st["state"], "level": level, "enabled": config.get("autopilot.full.enabled") is True,
           "charter": None, "decisions": int(st.get("decisions") or 0), "budget": {"used_pct": st.get("used_pct"), "cap_pct": None, "source": "unknown"},
           "time": {"left_s": None, "cap_s": None}, "stop": None, "cr": st.get("cr"), "branch": st.get("branch"),
           "worktree": st.get("worktree"), "ended_reason": st.get("ended_reason")}
    if c:
        out["charter"] = {"id": c["id"], "goal": c["goal"], "scope": list(c["scope"]), "ends": list(c["ends"]), "set_by": c["set_by"],
                          "sha8": rec["sha256"][:8]}
        out["budget"]["cap_pct"] = c["budget_pct_week"]
        out["time"]["cap_s"] = float(c["time_h"]) * 3600.0 if c.get("time_h") is not None else None
        if st["state"] in ("running", "paused"):
            lim = limits(st, c, plan_reading(at, base), at)
            out["budget"].update(used_pct=lim["used_pct"] if lim["used_pct"] is not None else st.get("used_pct"), source=lim["source"])
            out["time"]["left_s"] = lim["left_s"]
        elif st["state"] == "set" and c.get("time_h") is not None:
            out["time"]["left_s"] = float(c["time_h"]) * 3600.0
    elif st["state"] in ("running", "paused"):
        out["budget"]["source"] = "unknown"
    if st.get("stop"):
        s = st["stop"]
        out["stop"] = {"id": s.get("id"), "rule": s.get("rule"), "text": s.get("text"), "ts": s.get("ts")}
    if c and c.get("until") == "disabled":                      # option C: the fields the panel reads (until, reason, seg_left_s, day, week, waiting[])
        try:
            from .. import projects
            from . import standing
            main = next((p.path for p in projects.list_projects() if p.id == pid), None)
            out.update(standing.panel_fields(pid, main, at) if main else {"until": "disabled"})
            out["time"] = {"left_s": out.get("seg_left_s"), "cap_s": float(SEG_S)}
        except Exception:
            out["until"] = "disabled"
        out["until"] = "disabled"
    return out
