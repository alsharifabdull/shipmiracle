"""Option C of full autopilot, "Until I disable it" (design docs/plans/2026-10-21-autopilot-scope-design.md section 8): the helpers around a STANDING charter
(`until: "disabled"`): the owner's admissions of extra requests, the requests that wait for the owner, the summary printed at a check-in, the refusal of a
request opened inside the auto worktree, and the panel data.

Nothing here trusts the opener of a request: `shipm cr open` is open to chats, so every request beyond the charter's starting list needs a separate admission
typed by the owner in a terminal (`shipm autopilot admit`). Admissions live in the registry record NEXT TO the charter, outside its sha, and are only ever
written by the owner CLI (registry.set_admitted); the state file is never read as a source of admissions."""
from __future__ import annotations

import hashlib
import os
import re
import unicodedata

from .. import ShipmiracleError, events, paths, registry
from . import charter as ch
from . import state as S

TITLE_SHOW = 80


def title_sha(title) -> str:
    """m1: the FULL sha256 of the title (an 8-character prefix could be ground against)."""
    return hashlib.sha256(str(title).encode("utf-8", "replace")).hexdigest()


_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)?|\x1b[@-_]|\x9b[0-9;?]*[ -/]*[@-~]")


def clean_text(text, n=TITLE_SHOW) -> str:
    """Like clean_title but unquoted (for rule names and stop texts)."""
    return clean_title(text, n)[1:-1]


def clean_title(title, n=TITLE_SHOW) -> str:
    """A request title for the owner's terminal and the system dialog (m2): ANSI / OSC escape sequences removed WITH their parameters, C0 and C1 controls, bidi marks
    (U+202A-202E, U+2066-2069), zero-width and other format characters removed, whitespace collapsed, cut at n, shown inside quotes so a title cannot pass for the prompt
    line. A title is model text and is printed right before a typed yes."""
    t = re.sub(r"[\t\r\n\v\f\x85\u2028\u2029]", " ", _ANSI.sub("", str(title)))             # line breaks become spaces (a title cannot start a new prompt line)
    t = "".join(c for c in t if not unicodedata.category(c).startswith("C"))
    t = re.sub(r"\s+", " ", t).strip().replace('"', "'")
    t = t if len(t) <= n else t[:n - 1] + "…"
    return '"%s"' % t


def standing_record(pid):
    """The registry record when the project has a STANDING charter, else None."""
    try:
        rec = registry.autopilot_of(registry.entry(pid))
    except Exception:
        return None
    if rec is None or not ch.is_standing(rec.get("charter")):
        return None
    return rec


def _main_cr(main, cr_id):
    from ..playbook import engine, store
    return engine.get_cr(store.load(main), cr_id)


def _admission_event(pid, cr_id, ts) -> bool:
    """True when the engine's own ledger (not the shared events tail, m5) has an `admit` record with this exact admit_ts for this request (a registry entry written by a script has none)."""
    try:
        return any(r.get("kind") == "admit" and r.get("cr") == cr_id and r.get("admit_ts") == ts for r in S.ledger_read(pid))
    except Exception:
        return False


def admitted(pid, main) -> list:
    """The admissions that count right now: [{id, title, in_chat, verified}] for registry entries whose request is still open or queued in the MAIN log and
    whose current title still hashes to the admitted title_sha (a retitled request needs a new admission). Never read from the state file."""
    rec = standing_record(pid)
    if rec is None:
        return []
    try:
        entries = ch.clean_admitted(rec.get("admitted") or [])          # D2: a malformed record is ONE kind of problem (nothing is honoured), never a KeyError
    except ch.CharterError:
        return []
    out = []
    for a in entries:
        try:
            cr = _main_cr(main, a["id"])
        except Exception:
            cr = None
        if cr is None or cr.get("status") not in ("open", "queued") or title_sha(cr["title"]) != a["title_sha"]:
            continue
        out.append({"id": a["id"], "title": cr["title"], "in_chat": bool(cr.get("in_chat")), "verified": _admission_event(pid, a["id"], a["ts"])})
    return out


def admitted_ids(pid, main, verified_only=True) -> list:
    """Ids the run may work on beyond its starting list. Q7: only VERIFIED admissions count (the engine's ledger has the exact admit record); an entry a script wrote
    into the registry is ignored and shown as 'admitted outside the terminal: ignored'."""
    return [a["id"] for a in admitted(pid, main) if a["verified"] or not verified_only]


def allowed_ids(pid, main, charter) -> list:
    """The ids a run may work on: the charter's starting list plus the valid admissions (standing charters only)."""
    ids = list(charter.get("ends") or [])
    if ch.is_standing(charter):
        ids += [i for i in admitted_ids(pid, main) if i not in ids]
    return ids


def waiting(pid, main, charter) -> list:
    """Open or queued requests of the main log that the run may NOT work on: [{id, title, in_chat}] ("Waiting for your OK"). The run is not paused by them."""
    from ..playbook import store
    ok = set(allowed_ids(pid, main, charter))
    out = []
    try:
        for c in store.load(main).get("crs", []):
            if c.get("status") in ("open", "queued") and c["id"] not in ok:
                out.append({"id": c["id"], "title": c["title"], "in_chat": bool(c.get("in_chat"))})
    except Exception:
        return out
    return out


def opener_word(cr) -> str:
    return "a chat" if cr.get("in_chat") else "a terminal"


def requests_listing(main, ids) -> list:
    """Printable lines `CR-012 · title · opened in a chat|terminal` for the start confirmation (titles cleaned)."""
    lines = []
    for i in ids:
        try:
            cr = _main_cr(main, i)
        except Exception:
            cr = None
        lines.append("  %s · %s · opened in %s" % (i, clean_title(cr["title"]) if cr else "(not found)", opener_word(cr) if cr else "unknown"))
    return lines


def admit(pid, main, cr_id, at=None) -> dict:
    """Store the owner's admission of one request (the CLI has already confirmed it with the owner in a terminal): require_owner, standing charter, the
    request open or queued in the main log, not already in ends, at most ADMITTED_MAX waiting. Event autopilot.admitted (the cross-check)."""
    paths.require_owner("shipm autopilot admit")
    rec = standing_record(pid)
    if rec is None:
        raise ch.CharterError("admit belongs to a run that lasts until you disable it")
    charter = rec["charter"]
    if not re.fullmatch(r"CR-\d{3,6}", str(cr_id)):
        raise ch.CharterError("expected a request id like CR-015")
    cr = _main_cr(main, cr_id)
    if cr is None or cr.get("status") not in ("open", "queued"):
        raise ch.CharterError("%s is not an open or queued request in this project" % cr_id)
    if cr_id in charter["ends"]:
        raise ch.CharterError("%s is already in the charter's starting list" % cr_id)
    cur = [a for a in (rec.get("admitted") or []) if a["id"] != cr_id]
    if len(cur) >= ch.ADMITTED_MAX:
        raise ch.CharterError("at most %d admitted requests wait at a time" % ch.ADMITTED_MAX)
    ts = int(S.now() if at is None else at)
    cur.append({"id": cr_id, "title_sha": title_sha(cr["title"]), "ts": ts})
    S.ledger_append(pid, "admit", cr=cr_id, admit_ts=ts, ts=ts)                # m5: the engine's own record, written BEFORE the registry entry it vouches for
    registry.set_admitted(pid, cur)
    events.emit("autopilot.admitted", {"cr": cr_id, "title8": title_sha(cr["title"])[:8], "admit_ts": ts}, project=pid, src="shipmiracle")
    try:                                                                       # m4: re-admitting a dropped request removes it from the dropped list
        S.update(pid, lambda c: (dict(c, dropped=[x for x in (c.get("dropped") or []) if x != cr_id]) if c and cr_id in (c.get("dropped") or []) else None))
    except Exception:
        pass
    return {"cr": cr_id, "title": cr["title"], "in_chat": bool(cr.get("in_chat"))}


def prune_admissions(pid, main) -> int:
    """m4: remove the admissions whose request is closed, delivered or abandoned (or gone). Owner paths call it (admit, checkpoint); returns how many were removed."""
    rec = standing_record(pid)
    if rec is None or not rec.get("admitted"):
        return 0
    try:
        keep = []
        for a in ch.clean_admitted(rec["admitted"]):
            cr = _main_cr(main, a["id"])
            if cr is not None and cr.get("status") in ("open", "queued"):
                keep.append(a)
    except Exception:
        return 0
    n = len(rec["admitted"]) - len(keep)
    if n:
        registry.set_admitted(pid, keep)
    return n


def drop_admission(pid, cr_id) -> bool:
    """Remove one admission (or none). True when something was removed."""
    rec = standing_record(pid)
    if rec is None:
        return False
    cur = [a for a in (rec.get("admitted") or []) if a["id"] != cr_id]
    if len(cur) == len(rec.get("admitted") or []):
        return False
    registry.set_admitted(pid, cur)
    return True


# ---------------------------------------------------------------- opening a request inside the auto worktree

def refuse_open_in_worktree(pd):
    """Text refusing `shipm cr open` (or an engine open) when `pd` is the auto worktree of a RUNNING standing run; the run pauses with unknown_request.
    None when the call is fine (not a worktree, not a standing run, not running)."""
    from . import worktree as W
    try:
        info = W.inspect(pd)
    except ShipmiracleError:
        return None
    if not (info["branch"] or "").startswith("auto/"):
        return None
    try:
        st = S.read(info["pid"])
    except Exception:
        return None
    if not S.is_standing(st) or st.get("state") != "running":
        return None
    if S.pause_for(info["pid"], "unknown_request"):
        S._emit_paused(info["pid"], "unknown_request")
    return "a request cannot be opened inside the autopilot's worktree: the run is paused (unknown_request); the owner decides (shipm autopilot resume | drop)"


# ---------------------------------------------------------------- the check-in summary and the panel data

def last_segment_summary(pid, main) -> list:
    """Lines for `shipm autopilot checkpoint`: what the last 24 h did (from the state file and the main log). Plain facts, no model text."""
    st = S.read(pid) if S.path(pid).exists() else None
    rec = standing_record(pid)
    if st is None or rec is None or not S.is_standing(st):
        return []
    sg, wk = st["seg"], st.get("week") or {}
    plan = S.plan_reading()
    lim = S.standing_limits(st, rec["charter"], plan) if plan else None
    from ..playbook import store
    done, blocked = [], []
    try:
        for c in store.load(main).get("crs", []):
            if c.get("status") == "delivered" and c.get("closed") and c["closed"] >= sg["start"]:
                done.append("%s · %s" % (c["id"], clean_title(c["title"], 60)))
            elif c.get("status") == "blocked":
                blocked.append("%s · %s" % (c["id"], clean_title(c["title"], 60)))
    except Exception:
        pass
    lines = ["Check-in %d: the last 24 hours" % int(sg["n"]),
             "  requests merged: %s" % (", ".join(done) if done else "none"),
             "  requests blocked: %s" % (", ".join(blocked) if blocked else "none"),
             "  requests started this segment: %d of %d" % (int(sg["crs_started"]), rec["charter"]["crs_day"]),
             "  auto-decisions: %d" % int(st.get("decisions") or 0)]
    if st.get("paused_reason"):
        lines.append("  paused because: %s" % st["paused_reason"])
    if st.get("stop"):
        lines.append("  last hard stop: %s (%s)" % (st["stop"].get("id"), clean_text(st["stop"].get("rule") or "", 40)))
    if lim and lim["used_pct"] is not None and lim["week_used_pct"] is not None:
        lines.append("  your week: %g%% of %g%% a day used, %g%% of %g%% a week" % (lim["used_pct"], lim["cap_pct"], lim["week_used_pct"], lim["week_cap_pct"]))
    w = waiting(pid, main, rec["charter"])
    lines.append("  requests waiting for your OK: %s" % (", ".join("%s%s" % (x["id"], " (opened in a chat)" if x["in_chat"] else "") for x in w) if w else "none"))
    return lines


def panel_fields(pid, main, at=None) -> dict:
    """Extra fields of `p.autopilot` for a standing run: until, seg_left_s, day, week, waiting[], reason, admitted_unverified, next_check_in_s."""
    rec = standing_record(pid)
    if rec is None:
        return {}
    c = rec["charter"]
    out = {"until": "disabled", "crs_day": c["crs_day"], "waiting": [], "reason": None, "seg_left_s": None, "day": None, "week": None, "admitted_unverified": []}
    try:
        st = S.read(pid)
    except Exception:
        st = None
    if S.is_standing(st):
        at = S.now() if at is None else at
        out["reason"] = st.get("paused_reason")
        out["seg_left_s"] = max(0, int(st["seg"]["expires"] - at)) if st["state"] != "ended" else None
        lim = S.standing_limits(st, c, S.plan_reading(at), at) if st["state"] in ("running", "paused") else None
        if lim:
            out["day"] = {"used_pct": lim["used_pct"], "cap_pct": lim["cap_pct"]}
            out["week"] = {"used_pct": lim["week_used_pct"], "cap_pct": lim["week_cap_pct"]}
        out["crs_started"] = int(st["seg"]["crs_started"])
    out["waiting"] = waiting(pid, main, c)
    out["admitted"] = [{"id": a["id"], "title": a["title"], "in_chat": a["in_chat"]} for a in admitted(pid, main) if a["verified"]]
    out["admitted_unverified"] = [a["id"] for a in admitted(pid, main) if not a["verified"]]        # "admitted outside the terminal: ignored"
    return out


# ---------------------------------------------------------------- starting work in a run that is waiting for requests

def start_idle(pid, main, charter, charter_sha):
    """A running standing run with no request (waiting for requests): start the next admitted one in the same segment (counted against crs_day). Returns
    {"cr", "branch", "wt"} or None (nothing to start, day's limit reached, not idle, or the worktree could not be made: the owner sees why in `show`)."""
    from . import worktree as W
    try:
        st = S.read(pid)
    except Exception:
        return None
    if not S.is_standing(st) or st["state"] != "running" or st.get("cr"):
        return None
    if int(st["seg"]["crs_started"]) >= int(charter["crs_day"]):
        return None
    nxt = W.next_cr_id(main, charter, None)
    if nxt is None:
        return None
    try:
        if st.get("worktree") and os.path.isdir(st["worktree"]):
            r = W.switch_next(pid, main, st["worktree"], charter, charter_sha, None)
            return {"cr": r["cr"], "branch": r["branch"], "wt": st["worktree"]} if r else None
        info = W.start_run(pid, main, charter, nxt)
        return {"cr": nxt, "branch": info["branch"], "wt": info["wt"]}
    except ShipmiracleError:
        return None
