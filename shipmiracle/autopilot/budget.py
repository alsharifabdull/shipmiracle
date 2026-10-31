"""Budget and time of a full-autopilot run (Phase 6 spec section 4). The arithmetic lives in state.py (used_pct / limits / observe: week reset,
stale plan.json, caps); this module is what the engine and the stage module ask:

  evaluate(pid, charter)   -> {"level": ok | near | reached, "kind": None | budget | time | budget_unknown, "lim": limits dict}; folds plan.json into the state
  close_if_reached(...)    -> ends the run at 100 % (ended:budget|time), event autopilot.ended (+ autopilot.budget_reached for Health); returns the reason or None
  agent_gate(pid, charter) -> refusal text for an Agent call that would start a new stage (>= 90 %), or for any Agent call at 100 %, else None
  per_cr(...)              -> tokens of one CR from the token ledger rows of the run's own sessions; None = "not measured"

plan.json older than 15 minutes counts as reached while the run is running (H8-budget_unknown): the budget cannot be measured. Account-wide percent:
conservative on purpose."""
from __future__ import annotations

import json
import os

from .. import events, paths
from . import state as S

STANDING_KINDS = {"day": "day_limit", "week": "week_limit", "budget_unknown": "budget_unknown", "checkpoint": "checkpoint"}   # option C: kind -> pause reason
TEXT_NEAR = "limit_near: the autopilot is at %s of its %s limit. No new stage is started; finish nothing new and end your turn with one line for the owner."
TEXT_REACHED = "H8-%s: the autopilot reached its %s limit and ended. Nothing more is changed. End your turn with one line for the owner."


def evaluate(pid, charter, plan=None, at=None, base=None) -> dict:
    lim = S.observe(pid, charter, plan, at, base)
    if lim is None:
        return {"level": "ok", "kind": None, "lim": None}
    if charter.get("until") == "disabled":                       # option C: every limit PAUSES (day_limit | week_limit | budget_unknown | checkpoint), none ends the run
        if lim.get("segment_due"):
            return {"level": "reached", "kind": "checkpoint", "lim": lim}
        if lim["budget_unknown"]:
            return {"level": "reached", "kind": "budget_unknown", "lim": lim}
        if lim["week_reached"]:
            return {"level": "reached", "kind": "week", "lim": lim}
        if lim["day_reached"]:
            return {"level": "reached", "kind": "day", "lim": lim}
        if lim["budget_near"]:
            return {"level": "near", "kind": "budget", "lim": lim}
        return {"level": "ok", "kind": None, "lim": lim}
    if lim["time_reached"]:
        return {"level": "reached", "kind": "time", "lim": lim}
    if lim["budget_unknown"]:
        return {"level": "reached", "kind": "budget_unknown", "lim": lim}
    if lim["budget_reached"]:
        return {"level": "reached", "kind": "budget", "lim": lim}
    if lim["time_near"] or lim["budget_near"]:
        return {"level": "near", "kind": "time" if lim["time_near"] else "budget", "lim": lim}
    return {"level": "ok", "kind": None, "lim": lim}


def close_if_reached(pid, ev, base=None):
    """Ends the run when `ev` (an evaluate() result) says reached. Returns the ending reason (time|budget; the run's own when it had already ended) or None. Events only on the transition."""
    if ev["level"] != "reached":
        return None
    if ev["kind"] in STANDING_KINDS:
        reason = STANDING_KINDS[ev["kind"]]
        if S.pause_for(pid, reason, None, base):
            try:
                events.emit("autopilot.paused", {"reason": reason, "label": "H8-" + ev["kind"]}, project=pid, src="autopilot")
            except Exception:
                pass
        return reason
    reason = "time" if ev["kind"] == "time" else "budget"
    try:
        was_ended = (S.read(pid, base) or {}).get("state") == "ended"
    except Exception:
        was_ended = False
    cur = S.end(pid, reason, None, base)
    if cur is not None and cur.get("ended_reason") == reason and not was_ended:
        try:
            events.emit("autopilot.ended", {"reason": reason, "label": "H8-" + ev["kind"]}, project=pid, src="autopilot")
            if reason == "budget":
                events.emit("autopilot.budget_reached", {"kind": ev["kind"]}, project=pid, src="autopilot")
        except Exception:
            pass
    return reason


def agent_gate(pid, charter, starts_stage=True, base=None):
    """Text refusing an Agent call, or None. At 100 % every Agent call is refused; at 90 % only one that starts a new stage."""
    ev = evaluate(pid, charter, base=base)
    if ev["level"] == "reached" and ev["kind"] in STANDING_KINDS:
        close_if_reached(pid, ev, base)
        return "H8-%s: the autopilot paused (%s). Nothing more is changed until the owner looks. End your turn with one line for the owner." % (ev["kind"], STANDING_KINDS[ev["kind"]])
    if ev["level"] == "reached":
        return TEXT_REACHED % (ev["kind"], "time" if ev["kind"] == "time" else "budget")
    if ev["level"] == "near" and starts_stage:
        lim = ev["lim"]
        if "week_cap_pct" in lim:
            return TEXT_NEAR % ("%g%%" % (lim["week_used_pct"] if lim["week_used_pct"] is not None else lim["used_pct"]), "budget (day cap %g%%, week cap %g%%)" % (lim["cap_pct"], lim["week_cap_pct"]))
        if ev["kind"] == "time":
            return TEXT_NEAR % ("%d%%" % round(100 * (1 - lim["left_s"] / lim["cap_s"])), "time")
        return TEXT_NEAR % ("%g%%" % lim["used_pct"], "budget (cap %g%%)" % lim["cap_pct"])
    return None


def per_cr(sessions, t0, t1, state_dir=None):
    """{"tokens", "calls"} summed from ledger.jsonl rows whose session starts with one of the run's session prefixes and whose ts lies in [t0, t1]
    (one row per message id, the copy with the most output). None when the ledger is absent or no row matches: "not measured"."""
    if not sessions:
        return None
    sd = str(state_dir if state_dir is not None else paths.state_dir())
    seen = {}
    try:
        with open(os.path.join(sd, "ledger.jsonl"), encoding="utf-8", errors="replace") as f:
            for ln in f:
                try:
                    r = json.loads(ln)
                except ValueError:
                    continue
                if not isinstance(r, dict) or not isinstance(r.get("session"), str) or r["session"][:8] not in sessions:
                    continue
                ts = r.get("ts")
                if isinstance(ts, bool) or not isinstance(ts, (int, float)) or not (t0 <= ts <= t1):
                    continue
                key = r.get("id") or (r["session"], ts)
                out = r.get("output") if isinstance(r.get("output"), (int, float)) else 0
                if key not in seen or out > seen[key][0]:
                    seen[key] = (out, r)
    except OSError:
        return None
    if not seen:
        return None
    tokens = 0
    for _o, r in seen.values():
        for k in ("fresh", "output", "cache_write", "cache_read"):
            v = r.get(k)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                tokens += int(v)
    return {"tokens": tokens, "calls": len(seen)}
