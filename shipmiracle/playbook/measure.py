"""F6 Short/Long measurement (release scope C3): is a Long interview really better than a Short one? Per finished change request we record which interview mode the project had
(`short`, `long`, or `none` for no finished interview) and the rework rounds (fail -> fix loops of Verify). `shipm playbook interview --report` prints counts per mode, the median
rework and N. Local only: files in `<state>/v1/measure/<pid>.json` (0600), no network, no model; the report is read-only."""
from __future__ import annotations

import json
import statistics
import time

from .. import paths, state
from . import store

MODES = ("short", "long", "none")
KEEP = 300
EVIDENCE_N = 10


def _dir(base=None):
    b = store._sbase(base)
    paths.assert_isolated(b)
    return state.ensure_dir(state.ensure_root(b) / "measure")


def mode_of(pd) -> str:
    """The interview mode in effect: `short` / `long` when a finished interview (draft or done, with answers) exists, else `none`."""
    try:
        from . import interview
        st = interview.load(pd)
        if st and st["answered"] and st["status"] in ("draft", "done"):
            return st["mode"]
    except Exception:
        pass
    return "none"


def rework_of(pd, cr_id, base=None) -> int:
    """Verify fail -> fix loops of the CR: the number of `fail` lines in its log."""
    from ..report import facts as F
    return sum(1 for ln in F._lines_of(pd, base) if ln.get("cr") == cr_id and ln.get("op") == "fail")


def record(pd, cr_id, base=None, now=None) -> dict:
    """Store {mode, rework, ts} for the CR (replaces an earlier row of the same CR). Returns the row."""
    row = {"mode": mode_of(pd), "rework": rework_of(pd, cr_id, base), "ts": int(time.time()) if now is None else int(now)}
    d = _dir(base)
    p = d / (store.pid_of(pd) + ".json")
    try:
        cur = json.loads(state.read_bytes_nofollow(p).decode("utf-8"))
        rows = cur["rows"] if isinstance(cur, dict) and isinstance(cur.get("rows"), dict) else {}
    except Exception:
        rows = {}
    rows[cr_id] = row
    if len(rows) > KEEP:
        for k in sorted(rows, key=lambda k: rows[k].get("ts", 0))[:len(rows) - KEEP]:
            rows.pop(k, None)
    state.atomic_write(p, (json.dumps({"v": 1, "rows": rows}, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"), 0o600)
    return row


def _valid(r) -> bool:
    return isinstance(r, dict) and r.get("mode") in MODES and isinstance(r.get("rework"), int) and not isinstance(r.get("rework"), bool) and 0 <= r["rework"] <= 1000


def summary(base=None) -> dict:
    """{"modes": {mode: {"n", "median"}}, "n": total}. Reads every project's file; a damaged file or row is ignored. Read-only (nothing is created)."""
    b = store._sbase(base) / "v1" / "measure"
    by = {m: [] for m in MODES}
    try:
        files = sorted(b.glob("*.json"))
    except OSError:
        files = []
    for f in files[:500]:
        try:
            d = json.loads(state.read_bytes_nofollow(f).decode("utf-8"))
        except Exception:
            continue
        for r in (d.get("rows") if isinstance(d, dict) and isinstance(d.get("rows"), dict) else {}).values():
            if _valid(r):
                by[r["mode"]].append(r["rework"])
    modes = {m: {"n": len(v), "median": (statistics.median(v) if v else None)} for m, v in by.items()}
    return {"modes": modes, "n": sum(len(v) for v in by.values())}


def render(s) -> str:
    lines = ["Interview mode and rework rounds (local data only, nothing is sent anywhere)"]
    for m in MODES:
        r = s["modes"][m]
        lines.append("  %-5s N=%d  median rework rounds: %s" % (m, r["n"], "%g" % r["median"] if r["n"] else "no data"))
    small = s["modes"]["short"]["n"] < EVIDENCE_N or s["modes"]["long"]["n"] < EVIDENCE_N
    lines.append("Rework rounds are Verify fail -> fix loops per finished change request.")
    lines.append("N is below %d for Short or Long, so this is not evidence that Long is better than Short; it only shows what was recorded." % EVIDENCE_N if small
                 else "Both modes have at least %d change requests; read the medians as a hint, not a proof." % EVIDENCE_N)
    return "\n".join(lines)
