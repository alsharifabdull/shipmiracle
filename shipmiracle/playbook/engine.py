"""The change-request engine: pure functions over a `work` dict plus `rules` (gate.stage_rules). No I/O, no clock unless an event has no ts.

Every change to `work` goes through apply_tr(work, line): each API function validates, builds log lines ("transitions"), applies them
and returns them; the store appends exactly those lines, and replaying the log with apply_tr rebuilds the same work. Models may only
add work; only evidence and the owner's words move a CR forward or remove work.

Evidence `ev` = {"kind", "ref", "data", "by", "ts", "sid8"} (all but kind optional). `rules` = {type, project, labels, agents, lanes,
limits, risk, ui, deps, review, checks, autopilot, level, ...}."""
from __future__ import annotations

import json
import re
import time
import unicodedata
from collections import namedtuple

from .. import ShipmiracleError
from . import types

ORDER = types.ORDER
EXIT = {
    "intake": ("cli_open", "auto_open"),
    "scope": ("role_stop",),
    "plan": ("plan_presented",),
    "approve": ("owner_prompt", "charter"),
    "do": ("role_stop",),
    "verify": ("qa_pass",),
    "review": ("review_verdict",),
    "deliver": ("git_delivered",),
    "learn": ("status_dated", "report_written"),
}
FAIL_EXIT = {"verify": ("qa_fail",)}
OWNER_KINDS = ("owner_prompt", "owner_override")
KINDS = frozenset(k for v in EXIT.values() for k in v) | {"qa_fail", "owner_override", "cli_delta", "diff_eval", "engine", "cli_abandon", "cli_start",
                                                          "cli_render", "hold", "stuck", "hand_back"}
TERMINAL = ("delivered", "abandoned", "merged")
ACCEPT = ("ACCEPT", "ACCEPT WITH FIXES")
MAX_LINE = 1024
MAX_QUEUE = 12
_ID_RE = re.compile(r"CR-\d{3,6}")
ID_MAX = 99999                                            # imported or counted ids above this are refused (the next id must still fit CR-\d{3,6})
_SHA_RE = re.compile(r"[0-9a-f]{64}")
_REASON_RE = re.compile(r"[a-z][a-z0-9_]{0,39}")
_LEASE_RE = re.compile(r"auto-CR-\d{3,6}")
Refusal = namedtuple("Refusal", "kind msg")


class EngineRefused(ShipmiracleError):
    """The evidence or the order does not allow this move. `code` is a short machine word, str() is "code: message"."""
    def __init__(self, code: str, message: str = ""):
        super().__init__("%s: %s" % (code, message) if message else code)
        self.code = code
        self.message = message


def _int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _now() -> int:
    return int(time.time())


# ---------- work ----------

def new_work() -> dict:
    return {"v": 1, "render": "shipmiracle-engine", "project": None, "active": None, "queue": [], "crs": [], "updated": 0, "_max_id": 0}


def get_cr(work, cr_id):
    for c in work["crs"]:
        if c["id"] == cr_id:
            return c
    return None


def active_cr(work):
    return get_cr(work, work["active"]) if work.get("active") else None


def _clean_text(s, n):
    s = "".join(" " if c in "\t\n\r" else c for c in str(s) if not unicodedata.category(c).startswith("C") or c in "\t\n\r")
    return " ".join(s.split())[:n]


def _clip(v, depth=0):
    if isinstance(v, str):
        return _clean_text(v, 160)
    if isinstance(v, bool) or v is None or _int(v):
        return v
    if isinstance(v, float):
        return int(v)
    if depth < 3 and isinstance(v, (list, tuple)):
        return [_clip(x, depth + 1) for x in list(v)[:8]]
    if depth < 3 and isinstance(v, dict):
        return {str(k)[:32]: _clip(x, depth + 1) for k, x in list(v.items())[:14]}
    return None


def _ev(ev, now=None) -> dict:
    if not isinstance(ev, dict) or ev.get("kind") not in KINDS:
        raise EngineRefused("bad_evidence", "unknown evidence kind")
    ref = ev.get("ref")
    data = ev.get("data") if ev.get("data") is not None else {}
    if not isinstance(data, dict) or (ref is not None and not isinstance(ref, str)):
        raise EngineRefused("bad_evidence", "ref must be text and data an object")
    ts = ev.get("ts")
    out = {"kind": ev["kind"], "ref": _clean_text(ref, 80) if ref else None, "data": _clip(data),
           "by": _clean_text(ev.get("by") or data.get("role") or "engine", 40) or "engine",
           "ts": ts if _int(ts) and ts >= 0 else (now if now is not None else _now()), "sid8": _clean_text(ev.get("sid8") or "", 8) or None}
    return out


def dumps_line(tr: dict) -> str:
    return json.dumps(tr, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _tr(cr_id, op, stage, ev, **extra) -> dict:
    data = dict(ev["data"])
    data.update(extra)
    line = {"ts": ev["ts"], "cr": cr_id, "op": op, "stage": stage, "by": ev["by"],
            "ev": {"kind": ev["kind"], "ref": ev["ref"], "data": data}, "sid8": ev["sid8"]}
    if len(dumps_line(line).encode("utf-8")) > MAX_LINE:
        raise EngineRefused("evidence_too_big", "log line would exceed %d bytes" % MAX_LINE)
    return line


# ---------- applying a line (the only place that changes work) ----------

def _blank_cr(cr_id, title, lane, by, ts, base, skip, in_chat=False):
    stages = {s: ("skipped" if (lane == "fast" and s in skip) else "next") for s in ORDER}
    cr = {"id": cr_id, "title": title, "lane": lane, "status": "queued", "stage": "scope", "opened": ts, "by": by, "base": base,
          "stages": stages, "verify_fails": 0, "lenses": {l: None for l in types.LENSES}, "plan_sha": None, "hold": False,
          "diff": {"files": 0, "lines": 0, "risk": [], "deps": False, "ui": False}, "deltas": [], "reports": [],
          "blocked": None, "lease": None, "verified": False, "need_build": False, "learn": [], "last": None, "verdict": None, "closed": None, "report_sha": {}}
    if in_chat:
        cr["in_chat"] = True                   # display only (set at open time: opened from a chat); absent = not from a chat. Never an authority.
    _settle(cr)
    return cr


def _settle(cr):
    for s in ORDER:
        v = cr["stages"][s]
        if not (v.startswith("done") or v == "skipped"):
            cr["stage"] = s
            return
    cr["stage"] = "done"


def _done(cr, stage, by):
    cr["stages"][stage] = "done:" + by


def _reset_from(cr, first):
    """Stages first..learn go back to `next` (a skipped fast-lane review stays skipped only if the lane is still fast)."""
    i = ORDER.index(first)
    for s in ORDER[i:]:
        cr["stages"][s] = "next"
    cr["verify_fails"] = 0
    cr["lenses"] = {l: None for l in types.LENSES}
    cr["verified"] = False
    cr["learn"] = []
    cr["need_build"] = False
    if first in ("scope", "plan"):
        cr["plan_sha"] = None


def _verdict(cr, stage, word, counts, ts):
    cr["verdict"] = {"stage": stage, "word": word, "counts": counts, "ts": ts}


def _set_diff(cr, d):
    if isinstance(d, dict):
        cr["diff"] = {"files": d.get("files", 0) if _int(d.get("files")) else 0, "lines": d.get("lines", 0) if _int(d.get("lines")) else 0,
                      "risk": [_clean_text(x, 60) for x in (d.get("risk") or [])[:3] if isinstance(x, str)], "deps": bool(d.get("deps")),
                      "ui": bool(d.get("ui"))}


def _finish(work, cr, status, ts):
    cr["status"] = status
    cr["closed"] = ts
    cr["hold"] = False
    cr["lease"] = None
    if work.get("active") == cr["id"]:
        work["active"] = None
    if cr["id"] in work["queue"]:
        work["queue"].remove(cr["id"])


def _label(rules, stage):
    return (rules.get("labels") or {}).get(stage, stage.capitalize())


def apply_tr(work, tr):
    """Apply one log line to `work`. Raises (KeyError/ValueError/EngineRefused) on a line that makes no sense; the store skips those."""
    op = tr["op"]
    cr_id = tr.get("cr")
    ev = tr.get("ev") or {}
    data = ev.get("data") or {}
    ts = tr["ts"]
    by = tr.get("by") or "engine"
    stage = tr.get("stage")
    work["updated"] = max(work.get("updated", 0), ts)
    if op == "archived":
        work["_max_id"] = max(work.get("_max_id", 0), min(int(data.get("max", 0)), ID_MAX))
        return
    if op in ("open", "import"):
        if not isinstance(cr_id, str) or not _ID_RE.fullmatch(cr_id) or int(cr_id[3:]) > ID_MAX or get_cr(work, cr_id):
            raise ValueError("bad or duplicate CR id")
        cr = _blank_cr(cr_id, data["title"], data["lane"], by, data.get("opened", ts), data.get("base"), data.get("skip") or [], data.get("in_chat") is True)
        if op == "import":
            for s, v in (data.get("stages") or {}).items():
                if s in cr["stages"]:
                    cr["stages"][s] = v
            _settle(cr)
        work["crs"].append(cr)
        work["_max_id"] = max(work.get("_max_id", 0), int(cr_id[3:]))
        st = data.get("status", "open")
        if st in TERMINAL:
            cr["status"], cr["closed"] = st, ts
        elif work["active"] is None and st in ("open", "blocked"):
            work["active"] = cr_id
            cr["status"] = st
            cr["blocked"] = data.get("blocked")
        else:
            cr["status"] = "queued"
            work["queue"].append(cr_id)
        return
    cr = get_cr(work, cr_id)
    if cr is None:
        if op == "merge":                      # the merged CR was compacted away; nothing to mark
            return
        raise ValueError("unknown CR")
    if op == "start":
        if work["active"] is not None or cr["status"] != "queued":
            raise ValueError("cannot start")
        work["queue"].remove(cr_id)
        work["active"] = cr_id
        cr["status"] = "open"
    elif op == "advance":
        _apply_advance(cr, stage, ev.get("kind"), data, by, ts)
    elif op == "override":
        _done(cr, stage, "owner")
        if stage == "verify":
            cr["verified"], cr["verify_fails"], cr["need_build"] = True, 0, False
            if data.get("skip_review"):
                cr["stages"]["review"] = "skipped"
        if stage == "do":
            cr["verified"], cr["need_build"] = False, False
        cr["last"] = "%s skipped by the owner" % stage
        _settle(cr)
        if stage == "learn":
            _finish(work, cr, "delivered", ts)
    elif op == "fail":
        n = int(data["n"])
        cr["verify_fails"] = n
        cr["stages"]["verify"] = "fail:%d" % n
        cr["need_build"], cr["verified"] = True, False
        cr["last"] = "Test FAIL (attempt %d of 2)" % n
        _verdict(cr, "verify", "FAIL", data.get("counts"), ts)
        _settle(cr)
    elif op == "block":
        cr["status"], cr["blocked"], cr["hold"] = "blocked", data["reason"], False
    elif op == "unblock":
        cr["status"], cr["blocked"] = "open", None
        cr["hold"] = False
        if cr["stages"]["verify"].startswith("fail"):
            cr["stages"]["verify"] = "next"
            cr["verify_fails"], cr["need_build"] = 0, True
        _settle(cr)
    elif op == "lane":
        cr["lane"] = "full"
        cr["stages"]["plan"] = cr["stages"]["approve"] = "next"
        if cr["stages"]["review"] == "skipped":
            cr["stages"]["review"] = "next"
        cr["plan_sha"] = None
        cr["verified"] = False
        _set_diff(cr, data.get("diff"))
        _settle(cr)
        cr["stage"] = "plan"
    elif op == "diff":
        _set_diff(cr, data.get("diff"))
        if cr["lane"] == "full" and cr["stages"]["review"] == "skipped" and cr["diff"]["risk"]:
            cr["stages"]["review"] = "next"
            _settle(cr)
    elif op == "reset":
        to = data["to"]
        if to == "review":
            cr["stages"]["review"] = "next"
            cr["lenses"] = {l: None for l in types.LENSES}
        else:
            _reset_from(cr, to)
        cr["last"] = {"delta": "Reset to %s by a new request" % to,
                      "post_review_delta": "Review reset: changes after the review"}.get(data.get("why"), "Reset to %s" % to)
        _settle(cr)
    elif op == "hold":
        cr["hold"] = True
        if isinstance(data.get("lease"), str) and _LEASE_RE.fullmatch(data["lease"]):
            cr["lease"] = data["lease"]                   # P6: the CR is leased to an autopilot worktree (auto-CR-012)
    elif op == "release":
        cr["hold"] = False
        if data.get("unlease"):
            cr["lease"] = None
    elif op == "merge":
        other = get_cr(work, data["from"])
        if other is not None:
            if other["status"] in ("queued", "open"):
                _finish(work, other, "merged", ts)
            other["merged_into"] = cr_id
        cr["deltas"] = (cr["deltas"] + [data["from"]])[-5:]
    elif op == "deliver":
        _done(cr, "learn", by)
        _settle(cr)
        cr["last"] = "Delivered"
        _finish(work, cr, "delivered", ts)
    elif op == "abandon":
        cr["last"] = "Abandoned"
        _finish(work, cr, "abandoned", ts)
    elif op == "report":
        cr["reports"] = (cr["reports"] + [data["path"]])[-5:]
        sha = data.get("sha")
        if isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{64}", sha):
            rs = cr.setdefault("report_sha", {})
            rs[data["path"]] = sha                            # content sha of the report the ENGINE wrote: stage.py accepts only a file that still has it
            for k in [k for k in rs if k not in cr["reports"]]:
                del rs[k]
    else:
        raise ValueError("unknown op")


def _apply_advance(cr, stage, kind, data, by, ts):
    st = cr["stages"]
    if stage == "scope":
        _done(cr, "scope", by)
        cr["last"] = "Scope done"
    elif stage == "plan":
        if st["scope"] == "next":
            st["scope"] = "skipped"
        _done(cr, "plan", by)
        cr["plan_sha"] = data.get("plan_sha")
        cr["last"] = "Plan presented"
    elif stage == "approve":
        _done(cr, "approve", by)
        cr["last"] = "Plan approved"
    elif stage == "do":
        _set_diff(cr, data.get("diff"))
        _done(cr, "do", by)
        cr["verified"], cr["need_build"] = False, False
        if st["verify"].startswith("done"):
            st["verify"] = "next"
        cr["last"] = "Build done"
    elif stage == "verify":
        _done(cr, "verify", by)
        cr["verified"], cr["verify_fails"], cr["need_build"] = True, 0, False
        if data.get("skip_review"):
            st["review"] = "skipped"
        cr["last"] = "Test PASS"
        _verdict(cr, "verify", "PASS", data.get("counts"), ts)
    elif stage == "review":
        lens, verdict = data["lens"], data["verdict"]
        _verdict(cr, "review", verdict, lens, ts)
        if data.get("reset"):
            _reset_from(cr, "do")
            cr["need_build"] = True
            cr["last"] = "Review %s %s: back to Build" % (lens, verdict)
        else:
            cr["lenses"][lens] = verdict
            cr["last"] = "Review %s %s" % (lens, verdict)
            if data.get("complete"):
                _done(cr, "review", by)
    elif stage == "deliver":
        _done(cr, "deliver", by)
        cr["last"] = "Delivered to git"
    elif stage == "learn":
        if kind not in cr["learn"]:
            cr["learn"].append(kind)
        cr["last"] = "Learn: %s" % kind
    else:
        raise ValueError("bad stage")
    _settle(cr)


# ---------- helpers for the API ----------

def _need(work, cr_id, allow_blocked=False, allow_queued=False):
    cr = get_cr(work, cr_id)
    if cr is None:
        raise EngineRefused("unknown_cr", "no such change request")
    if cr["status"] in TERMINAL:
        raise EngineRefused("closed", "%s is %s" % (cr_id, cr["status"]))
    if cr["status"] == "queued" and not allow_queued:
        raise EngineRefused("not_active", "%s is queued behind %s" % (cr_id, work.get("active")))
    if cr["status"] == "blocked" and not allow_blocked:
        raise EngineRefused("blocked", "%s is blocked (%s)" % (cr_id, cr["blocked"]))
    return cr


def _emit(work, trs, tr):
    apply_tr(work, tr)
    trs.append(tr)


def _hand_back(ev):
    return ev["kind"] == "hand_back" or ev["data"].get("hand_back") is True


def _need_owner(ev, words=False):
    if ev["kind"] == "owner_override":
        return
    if ev["kind"] != "owner_prompt" or _hand_back(ev):
        raise EngineRefused("owner_required", "only the owner's own message or `shipmiracle` in a terminal can do this (hand-backs do not count)")
    if words and ev["data"].get("owner_words") is not True:
        raise EngineRefused("owner_required", "the message is not an approval")


def limits_of(rules):
    lim = rules.get("limits")
    return lim if isinstance(lim, dict) else None


def evaluate_diff(diff, rules) -> dict:
    """{"eligible": bool, "why": [reasons]}. Boundaries equal to the limit are eligible."""
    why = []
    if not (rules.get("lanes") or {}).get("fast_allowed", True):
        why.append("type_no_fast")
    lim = limits_of(rules) or {}
    mf, ml = lim.get("max_files"), lim.get("max_lines")
    files, lines = diff.get("files", 0), diff.get("lines", 0)
    if mf is not None and files > mf:
        why.append("files>%d" % mf)
    if ml is not None and lines > ml:
        why.append("lines>%d" % ml)
    if diff.get("risk"):
        why.append("risk_path")
    if diff.get("deps"):
        why.append("dep_file")
    if diff.get("submodule"):
        why.append("submodule")
    return {"eligible": not why, "why": why}


def required_lenses(cr, rules) -> list:
    """Lenses the review of this CR needs, in the fixed order correctness, risk, design. The fast lane has no review."""
    if cr["lane"] != "full":
        return []
    rv = rules.get("review") or {}
    need = set(rv.get("full", [])) | set(rv.get("always", []))
    if cr["diff"].get("risk"):
        need |= set(rv.get("on_risk", []))
    if cr["diff"].get("ui"):
        need |= set(rv.get("on_ui", []))
    return [l for l in types.LENSES if l in need]


def _missing_lenses(cr, rules):
    return [l for l in required_lenses(cr, rules) if cr["lenses"].get(l) not in ACCEPT + ("PASS",)]


def _after_stage(work, cr, rules, trs, ev, completed=True):
    """Manual autopilot holds after each completed stage; guided starts the next queued CR after a delivery or abandon."""
    if cr["status"] == "open" and completed and rules.get("autopilot") == "manual" and not cr["hold"] and cr["stage"] != "done":
        _emit(work, trs, _tr(cr["id"], "hold", cr["stage"], dict(ev, kind="hold", data={}, ref=None)))
    if cr["status"] in TERMINAL:
        _autostart(work, rules, trs, ev)


def _autostart(work, rules, trs, ev):
    if work["active"] is None and work["queue"] and rules.get("autopilot") == "guided":
        nxt = work["queue"][0]
        _emit(work, trs, _tr(nxt, "start", None, dict(ev, kind="engine", data={}, ref=None)))


# ---------- API ----------

def open_cr(work, title, by, now, lane=None, base=None, rules=None, kind="cli_open", sid8=None, in_chat=False):
    """(cr, [tr]). The CR is active when none is, else queued (WIP = 1). EngineRefused: bad title, queue full, fast lane not allowed."""
    rules = rules or {}
    t = _clean_text(title, 120) if isinstance(title, str) else ""
    if not t:
        raise EngineRefused("bad_title", "a change request needs a title")
    if kind not in EXIT["intake"]:
        raise EngineRefused("bad_evidence", "open needs cli_open or auto_open")
    fast_ok = (rules.get("lanes") or {}).get("fast_allowed", False)
    if lane is None:
        lane = (rules.get("lanes") or {}).get("default", "full")
    if lane not in types.LANES:
        raise EngineRefused("bad_lane", "lane is fast or full")
    if lane == "fast" and not fast_ok:
        raise EngineRefused("fast_not_allowed", "this project type always uses the full lane")
    if work["active"] is not None and len(work["queue"]) >= MAX_QUEUE:
        raise EngineRefused("queue_full", "%d requests are already queued" % MAX_QUEUE)
    if base is not None and not (isinstance(base, str) and re.fullmatch(r"[0-9a-f]{40,64}", base)):
        raise EngineRefused("bad_base", "base must be a commit id")
    nxt = max([int(c["id"][3:]) for c in work["crs"]] + [work.get("_max_id", 0)]) + 1
    if nxt > ID_MAX:
        raise EngineRefused("id_overflow", "no change request ids left (the log counts past %d)" % ID_MAX)
    cr_id = "CR-%03d" % nxt
    ev = _ev({"kind": kind, "by": by, "ts": now, "sid8": sid8}, now)
    skip = list(((rules.get("skips") or {}).get("fast")) or []) if lane == "fast" else []
    trs = []
    extra = {"in_chat": True} if (in_chat or kind == "auto_open") else {}
    tr = _tr(cr_id, "open", "intake", ev, title=t, lane=lane, base=base, skip=skip, opened=ev["ts"],
             status="open" if work["active"] is None else "queued", **extra)
    _emit(work, trs, tr)
    return get_cr(work, cr_id), trs


def start(work, cr_id, ev, rules=None):
    ev = _ev(ev)
    cr = _need(work, cr_id, allow_queued=True)
    if cr["status"] != "queued":
        raise EngineRefused("not_queued", "%s is not queued" % cr_id)
    if cr.get("lease"):
        raise EngineRefused("leased", "%s is leased to %s (an autopilot worktree is working on it)" % (cr_id, cr["lease"]))
    if work["active"] is not None:
        raise EngineRefused("wip", "%s is still active (one change request at a time)" % work["active"])
    trs = []
    _emit(work, trs, _tr(cr_id, "start", None, ev))
    return trs


def _stage_check(work, cr, stage, ev, rules, extra):
    """Validate evidence for `stage`; fills `extra` (data stored in the line). Raises EngineRefused."""
    d = ev["data"]
    k = ev["kind"]
    if stage == "scope":
        if d.get("role") != "scope" or ev["ts"] < cr["opened"]:
            raise EngineRefused("wrong_evidence", "scope needs a stop of the scope role during this CR")
    elif stage == "plan":
        sha = d.get("plan_sha")
        rt = d.get("role_ts")
        if not (isinstance(sha, str) and _SHA_RE.fullmatch(sha)) or not _int(rt) or rt < cr["opened"]:
            raise EngineRefused("wrong_evidence", "plan needs the presented plan (sha) and a plan-role stop during this CR")
    elif stage == "approve":
        _need_owner(ev, words=True)
        if k != "owner_prompt":
            raise EngineRefused("wrong_evidence", "approval is the owner's message")
        sha = d.get("plan_sha")
        if sha is not None and cr["plan_sha"] is not None and sha != cr["plan_sha"]:
            raise EngineRefused("plan_changed", "the plan changed after it was presented")
        extra["plan_sha"] = cr["plan_sha"]
    elif stage == "do":
        if d.get("role") != "build":
            raise EngineRefused("wrong_evidence", "build needs a stop of a build role")
        diff = d.get("diff") if isinstance(d.get("diff"), dict) else cr["diff"]
        if not _int(diff.get("files")) or diff["files"] < 1:
            raise EngineRefused("no_changes", "the build stop shows no changed file")
        if cr["lane"] == "full" and cr["stages"]["approve"] != "skipped" and not cr["stages"]["approve"].startswith("done"):
            raise EngineRefused("order", "build before the plan is approved")
    elif stage == "verify":
        if not cr["stages"]["do"].startswith("done"):
            raise EngineRefused("order", "test before build")
        if cr["need_build"]:
            raise EngineRefused("order", "the failed test needs a build first")
        if cr["lane"] == "fast" or not required_lenses(cr, rules):
            extra["skip_review"] = True
    elif stage == "review":
        lens, verdict = d.get("lens"), d.get("verdict")
        if lens not in types.LENSES:
            raise EngineRefused("bad_lens", "lens is correctness, risk or design")
        if not cr["verified"]:
            raise EngineRefused("verify_missing", "review needs a passing test after the last build")
        if lens == "design":
            ok, bad = ("PASS",), ("FAIL",)
        else:
            ok, bad = ACCEPT, ("REMEDIATE",)
        if verdict in bad:
            extra["reset"] = True
        elif verdict in ok:
            lenses = dict(cr["lenses"], **{lens: verdict})
            have = [l for l in required_lenses(cr, rules) if lenses.get(l) in ACCEPT + ("PASS",)]
            extra["complete"] = len(have) == len(required_lenses(cr, rules))
        else:
            raise EngineRefused("bad_verdict", "%s is not a finished %s verdict" % (verdict, lens))
    elif stage == "deliver":
        if not cr["verified"]:
            raise EngineRefused("verify_missing", "deliver needs a passing test after the last build")
    return None


def advance(work, cr_id, stage, ev, rules):
    """Record the exit evidence of `stage`. Returns the transitions. EngineRefused for a wrong kind, a broken order, a blocked/closed CR."""
    ev = _ev(ev)
    cr = _need(work, cr_id)
    if stage not in EXIT or stage == "intake":
        raise EngineRefused("bad_stage", "unknown stage")
    cur = cr["stage"]
    if ev["kind"] == "owner_override":
        return _override(work, cr, stage, ev, rules)
    if ev["kind"] == "charter":
        raise EngineRefused("wrong_evidence", "a charter approval is recorded only by charter_approve (the engine recomputes it)")
    if ev["kind"] not in EXIT[stage]:
        raise EngineRefused("wrong_evidence", "%s does not end with %s" % (stage, ev["kind"]))
    ci, si = (ORDER.index(cur) if cur in ORDER else len(ORDER)), ORDER.index(stage)
    rebuild = stage == "do" and ci > si and cur != "done"
    if not (stage == cur or (stage == "plan" and cur == "scope") or rebuild):
        raise EngineRefused("order", "%s is at %s, not %s" % (cr_id, cur, stage))
    extra = {}
    _stage_check(work, cr, stage, ev, rules, extra)
    trs = []
    completed = True
    if stage == "learn":
        kinds = set(cr["learn"]) | {ev["kind"]}
        completed = False
        _emit(work, trs, _tr(cr_id, "advance", stage, ev, **extra))
        if kinds >= set(EXIT["learn"]):
            _emit(work, trs, _tr(cr_id, "deliver", "learn", ev))
            completed = True
    else:
        _emit(work, trs, _tr(cr_id, "advance", stage, ev, **extra))
        if stage == "review":
            completed = bool(extra.get("complete") or extra.get("reset"))
    _after_stage(work, cr, rules, trs, ev, completed)
    return trs


def _override(work, cr, stage, ev, rules):
    reason = ev["data"].get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise EngineRefused("reason_required", "an owner override needs a reason")
    if stage not in EXIT or stage == "intake" or stage != cr["stage"]:
        raise EngineRefused("order", "%s is at %s, not %s" % (cr["id"], cr["stage"], stage))
    extra = {}
    if stage == "verify" and (cr["lane"] == "fast" or not required_lenses(cr, rules)):
        extra["skip_review"] = True
    trs = []
    _emit(work, trs, _tr(cr["id"], "override", stage, ev, **extra))
    _after_stage(work, cr, rules, trs, ev, True)
    return trs


def fail(work, cr_id, stage, ev, rules):
    """A failed verify. Two FAILs in a row (no PASS between) block the CR with reason verify_twice."""
    ev = _ev(ev)
    cr = _need(work, cr_id)
    if stage != "verify" or ev["kind"] not in FAIL_EXIT["verify"]:
        raise EngineRefused("wrong_evidence", "only a verify can fail, with qa_fail evidence")
    if cr["stage"] != "verify":
        raise EngineRefused("order", "%s is at %s, not verify" % (cr_id, cr["stage"]))
    n = cr["verify_fails"] + 1
    trs = []
    _emit(work, trs, _tr(cr_id, "fail", "verify", ev, n=n))
    if n >= 2:
        _emit(work, trs, _tr(cr_id, "block", "verify", ev, reason="verify_twice"))
    else:
        _after_stage(work, cr, rules, trs, ev, True)
    return trs


def block(work, cr_id, reason, ev):
    ev = _ev(ev)
    cr = _need(work, cr_id, allow_blocked=True)
    if not isinstance(reason, str) or not _REASON_RE.fullmatch(reason):
        raise EngineRefused("bad_reason", "reason is a short word like verify_twice")
    if cr["status"] == "blocked":
        return []
    trs = []
    _emit(work, trs, _tr(cr_id, "block", cr["stage"], ev, reason=reason))
    return trs


def unblock(work, cr_id, ev):
    """Only the owner (a real chat message or `shipm`) unblocks."""
    ev = _ev(ev)
    cr = _need(work, cr_id, allow_blocked=True)
    _need_owner(ev)
    if cr["status"] != "blocked":
        raise EngineRefused("not_blocked", "%s is not blocked" % cr_id)
    trs = []
    _emit(work, trs, _tr(cr_id, "unblock", cr["stage"], ev))
    return trs


def hold(work, cr_id, ev):
    ev = _ev(ev)
    cr = _need(work, cr_id)
    if cr["hold"]:
        return []
    trs = []
    _emit(work, trs, _tr(cr_id, "hold", cr["stage"], ev))
    return trs


def release(work, cr_id, ev):
    """Any owner message releases a manual hold; a hand-back does not."""
    ev = _ev(ev)
    cr = _need(work, cr_id, allow_blocked=True)
    _need_owner(ev)
    if not cr["hold"] or cr.get("lease"):
        return []                                         # a lease is dropped only by unlease() (shipm autopilot drop / the merge)
    trs = []
    _emit(work, trs, _tr(cr_id, "release", cr["stage"], ev))
    return trs


def lease(work, cr_id, name, ev):
    """P6: hold CR `cr_id` of the MAIN log for the autopilot worktree `name` (auto-CR-012). Works on open and queued CRs. Owner prompts do not release it."""
    ev = _ev(ev)
    cr = get_cr(work, cr_id)
    if cr is None:
        raise EngineRefused("unknown_cr", "no such change request")
    if cr["status"] in TERMINAL:
        raise EngineRefused("closed", "%s is %s" % (cr_id, cr["status"]))
    if not isinstance(name, str) or not _LEASE_RE.fullmatch(name):
        raise EngineRefused("bad_lease", "a lease is named auto-CR-n")
    if cr.get("lease") == name:
        return []
    if cr.get("lease"):
        raise EngineRefused("leased", "%s is already leased to %s" % (cr_id, cr["lease"]))
    trs = []
    _emit(work, trs, _tr(cr_id, "hold", cr["stage"], ev, lease=name))
    return trs


def unlease(work, cr_id, ev):
    ev = _ev(ev)
    cr = get_cr(work, cr_id)
    if cr is None or not cr.get("lease"):
        return []
    trs = []
    _emit(work, trs, _tr(cr_id, "release", cr["stage"], ev, unlease=True))
    return trs


def deliver_external(work, cr_id, ev):
    """P6: the autopilot worktree's branch was fast-forward merged into main: the CR of the MAIN log is delivered (op deliver; the lease ends with it)."""
    ev = _ev(ev)
    cr = get_cr(work, cr_id)
    if cr is None or cr["status"] in TERMINAL:
        return []
    trs = []
    _emit(work, trs, _tr(cr_id, "deliver", "learn", ev))
    return trs


def merge_ready(cr, rules):
    """(ok, why): verify passed after the last build, every required lens accepted (a skipped review needs none), not blocked/closed."""
    if cr is None:
        return False, "no such change request"
    if cr["status"] == "blocked":
        return False, "blocked (%s)" % cr["blocked"]
    if cr["status"] in ("abandoned", "merged"):
        return False, "the change request is %s" % cr["status"]
    if not cr["verified"] or not cr["stages"]["verify"].startswith("done"):
        return False, "no passing test after the last build"
    if cr["lane"] == "full" and cr["stages"]["review"] != "skipped":
        miss = _missing_lenses(cr, rules)
        if miss:
            return False, "review missing: " + ", ".join(miss)
    return True, ""


def charter_approve(work, cr_id, charter, state_sha, ev, rules, extra_ids=()):
    """The charter approves the plan (spec section 5, rule charter_approve; exit kind `charter`). Nothing the caller says is trusted: the engine
    recomputes from the LOG (the CR is active, open, full lane, at approve, with a presented plan_sha) and from the charter itself (its sha256 must equal
    the run state's sha, the CR must be in its `ends`, the project's rules must say autopilot full and trusted). Never read from work.json.
    Returns the transitions, or raises EngineRefused."""
    from ..autopilot import charter as ch
    ev = _ev(dict(ev, kind="charter"))
    if rules.get("autopilot") != "full" or not rules.get("trusted") or rules.get("level") != "strict":
        raise EngineRefused("not_full", "charter approval needs a trusted strict playbook with autopilot full")
    if not isinstance(charter, dict) or not isinstance(state_sha, str) or not _SHA_RE.fullmatch(state_sha):
        raise EngineRefused("no_charter", "no charter")
    try:
        sha = ch.digest(charter)
    except Exception:
        raise EngineRefused("no_charter", "the charter does not validate")
    if sha != state_sha:
        raise EngineRefused("charter_changed", "the charter sha differs from the run's")
    cr = _need(work, cr_id)
    if work.get("active") != cr_id or cr["status"] != "open" or cr["hold"]:
        raise EngineRefused("not_active", "%s is not the open active change request" % cr_id)
    if cr_id not in (charter.get("ends") or []) and cr_id not in (extra_ids or ()):          # extra_ids: the owner's admissions of a standing charter
        raise EngineRefused("not_in_charter", "%s is not one of the charter's change requests" % cr_id)
    if cr["lane"] != "full" or cr["stage"] != "approve" or cr["stages"]["plan"] == "next":
        raise EngineRefused("order", "%s is not waiting for approval of a presented plan" % cr_id)
    if not (isinstance(cr["plan_sha"], str) and _SHA_RE.fullmatch(cr["plan_sha"])):
        raise EngineRefused("no_plan", "no presented plan to approve")
    trs = []
    _emit(work, trs, _tr(cr_id, "advance", "approve", ev, plan_sha=cr["plan_sha"], charter=sha[:16]))
    return trs


def block_reason(work):
    """The blocked reason (verify_twice...) of the active change request, or None. The H7 hard stop reads it."""
    cr = active_cr(work)
    return cr["blocked"] if cr is not None and cr["status"] == "blocked" else None


def observe_diff(work, cr_id, diff, ev, rules):
    """Record the current diff and, in the fast lane, promote when it is no longer eligible. Returns the transitions."""
    ev = _ev(ev)
    cr = _need(work, cr_id, allow_blocked=True)
    d = {"files": diff.get("files", 0), "lines": diff.get("lines", 0), "risk": list(diff.get("risk") or [])[:3], "deps": bool(diff.get("deps")),
         "ui": bool(diff.get("ui"))}
    trs = []
    if cr["lane"] == "fast" and not evaluate_diff(diff, rules)["eligible"]:
        trs += promote(work, cr_id, diff, dict(ev, data=dict(ev["data"], why=evaluate_diff(diff, rules)["why"])))
    elif dict(cr["diff"]) != d:
        _emit(work, trs, _tr(cr_id, "diff", cr["stage"], ev, diff=d))
    return trs


def promote(work, cr_id, diff, ev):
    """Fast -> full. One way. Plan and approve become `next`, stage = plan."""
    ev = _ev(ev)
    cr = _need(work, cr_id, allow_blocked=True)
    if cr["lane"] == "full":
        return []
    d = {"files": diff.get("files", 0), "lines": diff.get("lines", 0), "risk": list(diff.get("risk") or [])[:3], "deps": bool(diff.get("deps")),
         "ui": bool(diff.get("ui"))}
    trs = []
    _emit(work, trs, _tr(cr_id, "lane", "plan", ev, diff=d))
    return trs


def reset_after_delta(work, cr_id, reset_to, from_cr, ev):
    """A new request changes this CR: `from_cr` (queued) merges into it and stages from `reset_to` (scope|plan) go back to `next`."""
    ev = _ev(ev)
    cr = _need(work, cr_id, allow_blocked=True)
    if reset_to not in ("scope", "plan"):
        raise EngineRefused("bad_reset", "reset_to is scope or plan")
    other = get_cr(work, from_cr)
    if other is None or from_cr == cr_id:
        raise EngineRefused("unknown_cr", "the delta source must be another change request")
    if other["status"] != "queued":
        raise EngineRefused("not_queued", "%s is not queued" % from_cr)
    trs = []
    _emit(work, trs, _tr(cr_id, "merge", cr["stage"], ev, **{"from": from_cr}))
    if cr["lane"] == "fast":
        _emit(work, trs, _tr(cr_id, "lane", "plan", ev, diff=dict(cr["diff"])))
    _emit(work, trs, _tr(cr_id, "reset", reset_to, ev, to=reset_to, why="delta"))
    return trs


def post_review_delta(work, cr_id, delta, ev, rules):
    """Changes after the review: when `delta` ({files, lines}) is over the fast-lane limits the review starts again."""
    ev = _ev(ev)
    cr = _need(work, cr_id)
    lim = limits_of(rules) or {"max_files": 3, "max_lines": 50}
    over = (lim.get("max_files") is not None and delta.get("files", 0) > lim["max_files"]) or \
           (lim.get("max_lines") is not None and delta.get("lines", 0) > lim["max_lines"])
    reviewed = cr["stages"]["review"].startswith("done") or any(cr["lenses"].values())
    if not over or not reviewed:
        return []
    trs = []
    _emit(work, trs, _tr(cr_id, "reset", "review", ev, to="review", why="post_review_delta"))
    return trs


def abandon(work, cr_id, ev, rules=None):
    ev = _ev(ev)
    cr = _need(work, cr_id, allow_blocked=True, allow_queued=True)
    if ev["kind"] != "owner_override":
        raise EngineRefused("owner_required", "only the owner abandons a change request")
    trs = []
    _emit(work, trs, _tr(cr_id, "abandon", cr["stage"], ev))
    _autostart(work, rules or {}, trs, ev)
    return trs


def record_report(work, cr_id, path, ev, sha=None):
    """Log that the engine wrote the report `path` (docs/reports/...); `sha` is the sha256 (hex) of its content."""
    ev = _ev(ev)
    if sha is not None and not (isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{64}", sha)):
        raise EngineRefused("bad_sha", "report sha is 64 hex characters")
    if get_cr(work, cr_id) is None:
        raise EngineRefused("unknown_cr", "no such change request")
    if not isinstance(path, str) or not path or len(path) > 80:
        raise EngineRefused("bad_path", "report path is 1-80 characters")
    trs = []
    _emit(work, trs, _tr(cr_id, "report", None, ev, path=path, **({"sha": sha} if sha else {})))
    return trs


# ---------- questions the hooks ask ----------

def _agent(rules, stage):
    return (rules.get("agents") or {}).get(stage)


def next_action(work, rules) -> dict:
    """{"cr","stage","role","agent","waiting_on": owner|lead|none, "wait", "text"} for the active CR."""
    cr = active_cr(work)
    if cr is None:
        if work["queue"]:
            q = get_cr(work, work["queue"][0])
            t = "No active CR. Start %s \"%s\" with `shipm cr start %s`." % (q["id"], q["title"], q["id"])
            return {"cr": None, "stage": None, "role": None, "agent": None, "waiting_on": "owner", "wait": "start the queued CR", "text": t}
        return {"cr": None, "stage": None, "role": None, "agent": None, "waiting_on": "none", "wait": "", "text": "No active CR."}
    stage, lab = cr["stage"], _label(rules, cr["stage"])
    roles = rules.get("roles") or {}
    role, agent, waiting, wait = roles.get(stage), _agent(rules, stage), "lead", ""
    short = ""
    n = cr["verify_fails"] + 1
    if stage == "scope":
        short = "%s (optional) — %s" % (lab, agent)
    elif stage == "plan":
        short = "%s — %s; present the plan, then wait for the owner's OK" % (lab, agent)
    elif stage == "approve":
        waiting, wait, role, agent = "owner", "approve the plan (write your OK in the chat)", "owner", None
    elif stage == "do":
        short = "%s — %s" % (lab, agent)
    elif stage == "verify":
        if cr["need_build"]:
            role, agent = roles.get("do"), _agent(rules, "do")
            short = "%s — %s fixes the %s failure, then %s again" % (_label(rules, "do"), agent, lab, lab)
        else:
            short = "%s — %s, attempt %d of 2" % (lab, agent, n)
            if rules.get("checks"):
                short += "; checks: " + ", ".join(rules["checks"])
    elif stage == "review":
        miss = _missing_lenses(cr, rules) or ["correctness"]
        lens = miss[0]
        role = "design" if lens == "design" else roles.get("review")
        agent = _agent(rules, "design" if lens == "design" else "review")
        short = "%s — %s, lens %s" % (lab, agent, lens)
    elif stage == "deliver":
        short = "%s — commit and push" % lab
    elif stage == "learn":
        short = "%s — update docs/STATUS.md (dated today) and write the CR report" % lab
    last = (cr["last"] + ". ") if cr["last"] else ""
    if cr["status"] == "blocked":
        waiting, wait = "owner", "tests failed twice; choose: change the plan, fix again, or stop the CR" if cr["blocked"] == "verify_twice" \
            else "blocked (%s)" % cr["blocked"]
        text = "%s: %sBlocked: %s. Waiting on owner." % (cr["id"], last, wait)
    elif cr["hold"]:
        waiting, wait = "owner", "type next"
        text = "%s: %sReport this stage to the owner and stop; wait for 'next'." % (cr["id"], last)
    elif waiting == "owner":
        text = "%s: %sWaiting on owner: %s." % (cr["id"], last, wait)
    else:
        text = "%s: %sNext: %s. Continue." % (cr["id"], last, short)
    return {"cr": cr["id"], "stage": stage, "role": role, "agent": agent, "waiting_on": waiting, "wait": wait, "text": text}


def can_stop(work, rules, sess=None) -> list:
    """Refusals at Stop for the active CR (list of Refusal). sess: {stage_event, continued, asks}. A blocked or held CR may stop:
    that is the correct way to wait for the owner."""
    sess = sess or {}
    cr = active_cr(work)
    if cr is None or cr["status"] != "open":
        return []
    out = []
    if cr["lane"] == "full" and not cr["stages"]["approve"].startswith("done") and (cr["diff"]["files"] >= 1 or cr["stages"]["do"].startswith("done")):
        out.append(Refusal("cr_needs_plan", "%s changes files in the full lane but the plan is not approved. Have the planner write the plan, "
                           "present it, and wait for the owner's OK before building." % cr["id"]))
    missing = _missing_lenses(cr, rules)
    if cr["stages"]["verify"].startswith("done") and cr["verified"] and not (cr["stages"]["review"].startswith("done") or cr["stages"]["review"] == "skipped") \
            and missing and cr["lane"] == "full":
        out.append(Refusal("cr_review_missing", "%s needs review before it can finish: missing %s. Run the %s." % (
            cr["id"], ", ".join(missing), "reviewer (lens %s)" % missing[0] if missing[0] != "design" else "designer")))
    if not out and (rules.get("autopilot") == "guided" or (rules.get("autopilot") == "full" and sess.get("auto_active") is True)) and not cr["hold"] and sess.get("stage_event") and not sess.get("continued") \
            and not sess.get("asks"):
        na = next_action(work, rules)
        if na["waiting_on"] == "lead":
            out.append(Refusal("cr_continue", na["text"]))
    return out


def can_call_agent(work, rules, role) -> list:
    """Refusals at PreToolUse Agent|Task for a subagent of `role` (build, test, scope, plan, review, design...)."""
    cr = active_cr(work)
    if cr is None:
        return []
    if cr["status"] == "blocked" and role in ("build", "test"):
        return [Refusal("cr_blocked", "%s is blocked (%s). Stop and ask the owner: change the plan, fix it again, or stop the CR." % (
            cr["id"], "tests failed twice" if cr["blocked"] == "verify_twice" else cr["blocked"]))]
    if cr["hold"] and cr["status"] == "open":
        return [Refusal("manual_hold", "Manual autopilot: %s is on hold. Report this stage to the owner and wait for 'next'." % cr["id"])]
    return []


# ---------- render and brief ----------

_PUBLIC = ("id", "title", "lane", "status", "stage", "opened", "by", "base", "stages", "verify_fails", "lenses", "plan_sha", "hold", "diff", "deltas",
           "reports", "blocked", "in_chat")
_COMPACT = ("id", "title", "lane", "status", "stage", "opened", "by")


def render(work) -> dict:
    """The public record for .shipmiracle/work.json (< 4 KB): the active CR in full, queued ones compact, the last 3 finished ones."""
    crs = []
    fin = [c for c in work["crs"] if c["status"] in TERMINAL][-3:]
    for c in work["crs"]:
        if c["status"] in TERMINAL and c not in fin:
            continue
        if c["status"] in ("queued",) or c in fin:
            row = {k: c[k] for k in _COMPACT} if c["status"] == "queued" else {k: c[k] for k in _COMPACT + ("verify_fails", "reports")}
            if c.get("in_chat"):
                row["in_chat"] = True
            crs.append(row)
        else:
            crs.append({k: c[k] for k in _PUBLIC if k in c})
    out = {"v": 1, "render": "shipmiracle-engine", "project": work.get("project"), "active": work["active"], "queue": list(work["queue"]), "crs": crs,
           "updated": work.get("updated", 0)}
    while len(json.dumps(out, separators=(",", ":"), ensure_ascii=False).encode("utf-8")) > 3900 and len(out["crs"]) > 1:
        for i, c in enumerate(out["crs"]):
            if c["status"] in TERMINAL:
                del out["crs"][i]
                break
        else:
            out["crs"].pop()
    return out


def _fmt_ts(ts):
    t = time.localtime(ts)
    return "%d %s" % (t.tm_mday, time.strftime("%b %H:%M", t))


def _short(t, n):
    return t if len(t) <= n else t[:n - 1] + "…"


def brief(work, rules) -> str:
    """The session brief (<= 1 KB): Playbook / Active / Waiting on owner / Queue / Last verdict / Rules. Long titles shrink to fit."""
    txt = ""
    for ta, tq, qmax in ((120, 120, 12), (80, 50, 5), (50, 30, 3), (30, 20, 2)):
        txt = _brief(work, rules, ta, tq, qmax)
        if len(txt.encode("utf-8")) <= 1000:
            return txt
    return txt.encode("utf-8")[:1000].decode("utf-8", "ignore")


def _brief(work, rules, ta, tq, qmax):
    cr = active_cr(work)
    na = next_action(work, rules)
    proj = _short(work.get("project") or rules.get("project") or "?", 40)
    lines = ["Playbook: %s · %s · %s (%s)" % (rules.get("type"), rules.get("level"), rules.get("autopilot"), proj)]
    if cr is None:
        lines.append("Active: none")
    else:
        at = _label(rules, cr["stage"]) if cr["stage"] != "done" else "done"
        if cr["stage"] == "verify":
            at += " (attempt %d of 2)" % (cr["verify_fails"] + 1)
        nxt = na["agent"] or na["role"] or "owner"
        lines.append("Active: %s \"%s\" · %s lane · at %s · next: %s" % (cr["id"], _short(cr["title"], ta), cr["lane"], at, nxt))
    wait = na["wait"] if na["waiting_on"] == "owner" and cr is not None else "none"
    lines.append("Waiting on owner: %s" % wait)
    q = [c for c in (get_cr(work, i) for i in work["queue"]) if c]
    qs = ", ".join("%s \"%s\"" % (c["id"], _short(c["title"], tq)) for c in q[:qmax])
    if len(q) > qmax:
        qs += " (+%d more)" % (len(q) - qmax)
    lines.append("Queue: " + (qs if q else "none"))
    vs = [c["verdict"] for c in work["crs"] if c.get("verdict")]
    if vs:
        v = max(vs, key=lambda x: x["ts"])
        word = " ".join(x for x in (_label(rules, v["stage"]) if v["stage"] != "review" else "Review", v["word"], v.get("counts") or "") if x)
        lines.append("Last verdict: %s (%s)" % (word, _fmt_ts(v["ts"])))
    else:
        lines.append("Last verdict: none")
    lines.append("Rules: " + _rules_line(cr, rules))
    return "\n".join(lines)


def _rules_line(cr, rules):
    lim = limits_of(rules)
    lab = lambda s: _label(rules, s)
    parts = []
    if cr is not None and cr["lane"] == "fast" and lim:
        parts.append("fast lane (up to %s files%s)" % (lim.get("max_files"), ", %s lines" % lim["max_lines"] if lim.get("max_lines") else ""))
    else:
        ag = (rules.get("agents") or {})
        parts += ["plan by %s" % ag.get("plan", "planner"), "your OK in chat"]
    parts.append("%s needs PASS" % lab("verify"))
    rv = rules.get("review") or {}
    lenses = list(rv.get("full", [])) + list(rv.get("always", []))
    if (cr is None or cr["lane"] == "full") and (lenses or rv.get("on_risk")):
        s = "review " + (", ".join(lenses) if lenses else "none")
        if rv.get("on_risk") and rules.get("risk"):
            s += " (+%s on %s)" % ("/".join(rv["on_risk"]), rules["risk"][0])
        parts.append(s)
    return " · ".join(parts)
