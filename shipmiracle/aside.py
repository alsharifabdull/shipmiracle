"""F7 Set aside and F8 Unread marker: the state files and the pure rules behind them (panel v3 UX addendum sections 3 and 4).

Both files are small v1 envelopes in `<state>/v1/` written through shipmiracle.state (atomic, flock, 0600, never through a symlink). They are NOT trusted or gate
files: no rule of the gate reads them, a chat that edited them could only hide a card or a marker, never loosen a check.

aside.json  data {"projects": {name: {"since": ts, "note": str}}, "returned": [{"project","why": "work"|"hard_stop","ts"}]}
            written by `shipm project aside|unaside` (owner at a terminal) and by the watcher's reconcile() when an aside project starts work or hits a hard stop.
seen.json   data {"seen": {name: ts}}   written ONLY by `shipm project seen NAME` (the owner's own "I looked" action: Open chat / focusing the chat).

"New since you last looked" (F8): the chat's own state file `<state>/<name>.json` says `idle` (a turn finished) or `needs-input` (it waits for you) with a ts; the
project is New when that ts is later than the seen ts. A project with no seen record has no marker (nothing was ever looked at, nothing to compare with); `working`
never shows a marker. Read-only everywhere except the two writers above."""
from __future__ import annotations

import time
from pathlib import Path

from . import NotFound, UsageError
from . import paths, projects, state

WRITER = "shipmiracle-project"
ASIDE, SEEN = "aside.json", "seen.json"
MAX_PROJECTS = 200
NOTE_MAX = 120
RETURNED_TTL = 24 * 3600
# Health kinds a set-aside project silences (addendum 3). Everything else (hard stops, integrity blocks, secret-scan blocks, limit warnings) is never in this set, so it
# is never silenced by construction.
SILENCED_KINDS = ("stage_stuck", "cr_orphan", "frozen_chat", "merge_waiting")
BLOCK_AUTOPILOT = "Not now: autopilot is running."
BLOCK_WAITING = "Not now: %s is waiting for you."


def _clean(s, n):
    from .report import clean
    return clean(s, n)


# ------------------------------------------------------------------ reading (never raises)

def _read(name, base=None):
    d = state.read_data(name, None, base)
    return d if isinstance(d, dict) else {}


def aside_map(base=None) -> dict:
    """{project: {"since": int, "note": str}} (damaged entries dropped)."""
    out = {}
    pj = _read(ASIDE, base).get("projects")
    if isinstance(pj, dict):
        for k, v in pj.items():
            if isinstance(k, str) and isinstance(v, dict) and isinstance(v.get("since"), int) and not isinstance(v.get("since"), bool):
                out[k] = {"since": v["since"], "note": _clean(v.get("note"), NOTE_MAX) or None}
    return out


def returned(base=None, now=None) -> list:
    """Auto un-aside notices of the last 24 hours, newest last: [{project, why, ts}]."""
    now = int(time.time()) if now is None else int(now)
    rows = _read(ASIDE, base).get("returned")
    out = []
    if isinstance(rows, list):
        for r in rows:
            if isinstance(r, dict) and r.get("why") in ("work", "hard_stop") and isinstance(r.get("project"), str) and isinstance(r.get("ts"), int) \
                    and now - r["ts"] < RETURNED_TTL:
                out.append({"project": r["project"], "why": r["why"], "ts": r["ts"]})
    return out


def seen_map(base=None) -> dict:
    out = {}
    s = _read(SEEN, base).get("seen")
    if isinstance(s, dict):
        for k, v in s.items():
            if isinstance(k, str) and isinstance(v, int) and not isinstance(v, bool):
                out[k] = v
    return out


# ------------------------------------------------------------------ writing

def _write_aside(proj, ret, base):
    state.write(ASIDE, {"projects": proj, "returned": ret}, WRITER, base)


def _sbase(base):
    return Path(base) if base is not None else paths.state_dir()


def _health(base):
    d, _src = state.read_compat("health.json", _sbase(base) / "health.json", base)
    return d if isinstance(d, dict) else {}


def _autopilot(pid, base):
    try:
        from .autopilot import state as ap
        return ap.snapshot(pid, base=base)
    except Exception:
        return None


def block_reason(name, pid, base=None, waiting_owner=False):
    """Why `name` cannot be set aside right now (the exact panel text), or None."""
    ap = _autopilot(pid, base)
    if ap and ap.get("state") in ("running", "paused"):
        return BLOCK_AUTOPILOT
    chat = (_health(base).get("chats") or {}).get(name)
    if waiting_owner or (isinstance(chat, dict) and chat.get("state") in ("waiting_you", "plan_approval")):
        return BLOCK_WAITING % name
    return None


def set_aside(name, note=None, base=None, now=None, waiting_owner=False) -> dict:
    """Park `name`. Owner only (refused inside a chat). Raises UsageError with the panel's reason when autopilot runs or the project waits for the owner."""
    paths.require_owner("shipm project aside")
    p = projects.get(name)
    if p is None:
        raise NotFound("no project named %s" % _clean(name, 60))
    why = block_reason(p.name, p.id, base, waiting_owner)
    if why:
        raise UsageError(why)
    note = _clean(note, NOTE_MAX) if note else ""
    now = int(time.time()) if now is None else int(now)
    with state.locked("aside", base):
        cur = aside_map(base)
        if p.name not in cur and len(cur) >= MAX_PROJECTS:
            raise UsageError("too many set-aside projects")
        cur[p.name] = {"since": now, "note": note or None}
        _write_aside(cur, returned(base, now), base)
    return {"project": p.name, "since": now, "note": note or None}


def unaside(name, base=None) -> bool:
    """Bring `name` back. True when it was set aside."""
    paths.require_owner("shipm project unaside")
    with state.locked("aside", base):
        cur = aside_map(base)
        if name not in cur:
            return False
        del cur[name]
        _write_aside(cur, returned(base), base)
    return True


def mark_seen(name, base=None, now=None) -> int:
    """The owner looked at the chat of `name` now. Owner only: a chat cannot clear a marker for the owner."""
    paths.require_owner("shipm project seen")
    p = projects.get(name)
    if p is None:
        raise NotFound("no project named %s" % _clean(name, 60))
    now = int(time.time()) if now is None else int(now)
    with state.locked("seen", base):
        cur = seen_map(base)
        cur[p.name] = now
        if len(cur) > MAX_PROJECTS:
            for k in sorted(cur, key=cur.get)[:len(cur) - MAX_PROJECTS]:
                del cur[k]
        state.write(SEEN, {"seen": cur}, WRITER, base)
    return now


# ------------------------------------------------------------------ F8: what is new

def unread(name, base=None) -> dict:
    """{"new": bool, "why": "turn"|"wait"|None, "since": ts|None} for the chat of project `name` (read-only; a failed read means no marker)."""
    none = {"new": False, "why": None, "since": None}
    try:
        d = state._load_json_file(_sbase(base) / ("%s.json" % name))
        seen = seen_map(base).get(name)
        if not isinstance(d, dict) or seen is None:
            return none
        ts, st = d.get("ts"), d.get("state")
        if not isinstance(ts, (int, float)) or isinstance(ts, bool):
            return none
        chat = (_health(base).get("chats") or {}).get(name)
        why = "wait" if st == "needs-input" or (isinstance(chat, dict) and chat.get("state") in ("waiting_you", "plan_approval")) \
            else "turn" if st == "idle" else None
        if why is None or int(ts) <= seen:
            return none
        return {"new": True, "why": why, "since": int(ts)}
    except Exception:
        return none


# ------------------------------------------------------------------ F7: panel fields, health split, auto un-aside

def back_reason(name, pid, base=None):
    """Why an aside project must show as a normal card ("work" | "hard_stop" | None), read-only."""
    chat = (_health(base).get("chats") or {}).get(name)
    if isinstance(chat, dict) and chat.get("working") is True:
        return "work"
    ap = _autopilot(pid, base)
    if ap and ap.get("stop"):
        return "hard_stop"
    return None


def panel_field(name, pid, base=None, waiting_owner=False) -> dict:
    """The `aside` field of `shipm report panel`: {on, since, note, canAside, reason, backOnList}."""
    m = aside_map(base).get(name)
    reason = block_reason(name, pid, base, waiting_owner) if m is None else None
    back = back_reason(name, pid, base) if m is not None else None
    return {"on": m is not None, "since": m["since"] if m else None, "note": m["note"] if m else None,
            "canAside": m is None and reason is None, "reason": reason,
            "backOnList": {"work": "%s started work." % name, "hard_stop": "%s hit a hard stop." % name}.get(back) if back else None}


def silenced_list(base=None) -> list:
    """The Health items the watcher set aside (health.json `aside_items`), cut to what the panel shows: [{project, kind, title, id}]."""
    rows = _health(base).get("aside_items")
    out = []
    if isinstance(rows, list):
        for i in rows[:100]:
            if isinstance(i, dict) and isinstance(i.get("project"), str) and isinstance(i.get("kind"), str):
                out.append({"project": i["project"], "kind": i["kind"], "title": _clean(i.get("title"), 120), "id": _clean(i.get("id"), 80) or None})
    return out


def split_items(items, base=None):
    """(kept, silenced): health items of set-aside projects whose kind is in SILENCED_KINDS go to `silenced` (listed, never dropped)."""
    a = aside_map(base)
    if not a:
        return list(items), []
    kept, quiet = [], []
    for i in items:
        (quiet if isinstance(i, dict) and i.get("project") in a and i.get("kind") in SILENCED_KINDS else kept).append(i)
    return kept, quiet


def reconcile(chats, base=None, now=None) -> list:
    """Auto un-aside (watcher): an aside project that is working (chats[name]["working"]) or has an autopilot hard stop leaves the aside list and a
    notice is kept 24 h. Returns the names brought back. Never raises."""
    try:
        now = int(time.time()) if now is None else int(now)
        if not aside_map(base):
            return []                      # nothing is aside: touch nothing (no folder, no lock file)
        with state.locked("aside", base):
            cur = aside_map(base)
            back = []
            for n in list(cur):
                c = (chats or {}).get(n)
                if isinstance(c, dict) and c.get("working") is True:
                    back.append((n, "work"))
                else:
                    pr = projects.get(n)
                    ap = _autopilot(pr.id, base) if pr else None
                    if ap and ap.get("stop"):
                        back.append((n, "hard_stop"))
            ret = returned(base, now)
            if not back and len(ret) == len(_read(ASIDE, base).get("returned") or []):
                return []
            for n, why in back:
                del cur[n]
                ret.append({"project": n, "why": why, "ts": now})
            _write_aside(cur, ret[-20:], base)
            return [n for n, _w in back]
    except Exception:
        return []
