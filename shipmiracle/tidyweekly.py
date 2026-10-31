"""`shipm tidy --all [--write] [--weekly]` (F10 phase 2, G2 step 1): the weekly size-and-count history behind the Tidy up card.

Read-only towards every project folder (it calls tidy.scan on each registered project and nothing else). The ONLY file it writes is <state>/v1/tidy.json
(sizes and counts, no file name, no path, no reason text), atomically, 0600, <= 64 KB, under its own lock. tidy.json is never the input to any action.
Shape of data: {"schema": 1, "scans": [...], "projects": [...], "condition": {...}}; a file with a missing or different schema counts as no history.
 scan   = {ts, iso_week, complete, projects_scanned, projects_skipped, duration_s, bytes: {disposable, regenerable_idle, regenerable_in_use, review}}
 project = {name, partial, git, idle_days, counts: {regenerable, disposable, review, never}, bytes: {disposable, regenerable, review, never}, freeable}
           (freeable = disposable + regenerable when the project is idle for 14 days or more, else disposable only)
 condition = {threshold_bytes, weeks_needed, weeks_over, met, met_since}
Budgets: tidy.scan's own 20 s / 2 M entries per project, plus 300 s for the whole run (projects not reached count as skipped and make the scan partial).
The owner's condition (4 complete weekly scans in a row with more than 2 GiB freeable) is computed here by `condition()`; each time it becomes true one
`tidy.condition_met` event is appended (best effort: retried on the next run when the append failed). The 300 s total can be overshot by at most one git call per project (git is bounded by the project's remaining budget)."""
from __future__ import annotations

import datetime
import json
import os
import re
import stat
import time

from . import NotFound, SafetyError, SchemaError, ShipmiracleError, UsageError
from . import state, tidy

WRITER = "shipmiracle-tidy"
NAME = "tidy.json"
SCHEMA = 1
THRESHOLD = 2 * 1024 ** 3
WEEKS_NEEDED = 4
KEEP = 8
MAX_PROJECTS = 100
MAX_BYTES = 64 * 1024
FRESH_DAYS = 6
TOTAL_SECONDS = 300.0
FUTURE_SLACK = 86400            # a scan dated more than a day ahead is not believed
MARGIN = 64                     # room kept below MAX_BYTES (the stored ts is longer than the 0 used to measure)
MAX_INT = 2 ** 53
WEEK_RE = re.compile(r"\d{4}-W\d{2}")
NAME_OK = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
CLASSES = ("regenerable", "disposable", "review", "never")
BYTE_KEYS = ("disposable", "regenerable_idle", "regenerable_in_use", "review")


# ---------------------------------------------------------------- small validators
def _int(v, hi=MAX_INT):
    return isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= hi


def iso_week(ts) -> str:
    y, w, _ = datetime.datetime.fromtimestamp(int(ts), datetime.timezone.utc).isocalendar()[:3]
    return "%04d-W%02d" % (y, w)


def freeable(bytes_) -> int:
    return bytes_["disposable"] + bytes_["regenerable_idle"]


def clean_scan(d, now=None):
    """A scan entry rebuilt from known keys only, or None when any field is not what the writer writes: the week must match the time, and with `now` a scan dated
    more than a day ahead is dropped."""
    if not isinstance(d, dict):
        return None
    if now is not None and _int(d.get("ts")) and d["ts"] > now + FUTURE_SLACK:
        return None
    b = d.get("bytes")
    if not (_int(d.get("ts")) and isinstance(d.get("iso_week"), str) and WEEK_RE.fullmatch(d["iso_week"]) and isinstance(d.get("complete"), bool)
            and _int(d.get("projects_scanned"), 100000) and _int(d.get("projects_skipped"), 100000) and isinstance(b, dict)
            and isinstance(d.get("duration_s"), (int, float)) and not isinstance(d.get("duration_s"), bool) and 0 <= d["duration_s"] <= 1e6
            and all(_int(b.get(k)) for k in BYTE_KEYS)):
        return None
    if d["iso_week"] != iso_week(d["ts"]):
        return None
    return {"ts": d["ts"], "iso_week": d["iso_week"], "complete": d["complete"], "projects_scanned": d["projects_scanned"], "projects_skipped": d["projects_skipped"],
            "duration_s": round(float(d["duration_s"]), 1), "bytes": {k: b[k] for k in BYTE_KEYS}}


def clean_project(d):
    if not isinstance(d, dict):
        return None
    c, b = d.get("counts"), d.get("bytes")
    idle = d.get("idle_days")
    if not (isinstance(d.get("name"), str) and NAME_OK.fullmatch(d["name"]) and isinstance(d.get("partial"), bool) and isinstance(d.get("git"), bool)
            and (idle is None or _int(idle, 100000)) and isinstance(c, dict) and isinstance(b, dict)
            and all(_int(c.get(k), 10 ** 9) and _int(b.get(k)) for k in CLASSES) and _int(d.get("freeable"))):
        return None
    return {"name": d["name"], "partial": d["partial"], "git": d["git"], "idle_days": idle, "counts": {k: c[k] for k in CLASSES},
            "bytes": {k: b[k] for k in CLASSES}, "freeable": d["freeable"]}


def clean_data(data, now=None):
    """(scans newest first, projects) from stored data; anything that does not fit is dropped, never repaired."""
    scans, projects = [], []
    if isinstance(data, dict):
        for s in (data.get("scans") if isinstance(data.get("scans"), list) else [])[:64]:
            c = clean_scan(s, now)
            if c:
                scans.append(c)
        for p in (data.get("projects") if isinstance(data.get("projects"), list) else [])[:MAX_PROJECTS * 2]:
            c = clean_project(p)
            if c:
                projects.append(c)
    scans.sort(key=lambda s: -s["ts"])
    return scans[:KEEP], projects[:MAX_PROJECTS]


# ---------------------------------------------------------------- the condition (pure)
def condition(scans) -> dict:
    """Count the newest run of complete weekly scans with freeable STRICTLY above the threshold. One entry per ISO week (the newest complete scan of that week);
    a complete week at or below the threshold ends the run (weeks_over then counts only what is newer); a week with no scan and a partial scan neither count nor reset."""
    weeks = {}
    for s in scans or []:
        c = clean_scan(s)
        if c and c["complete"]:
            cur = weeks.get(c["iso_week"])
            if cur is None or c["ts"] > cur["ts"]:
                weeks[c["iso_week"]] = c
    n = 0
    for wk in sorted(weeks, reverse=True):
        if freeable(weeks[wk]["bytes"]) > THRESHOLD:
            n += 1
        else:
            break
    return {"threshold_bytes": THRESHOLD, "weeks_needed": WEEKS_NEEDED, "weeks_over": n, "met": n >= WEEKS_NEEDED, "met_since": None}


def merge_scans(prev, entry):
    """New history: `entry` added to `prev`, newest first, max KEEP, one entry per ISO week (a complete one beats a partial one; between two of the same kind the newer ts wins)."""
    same = [x for x in prev if x["iso_week"] == entry["iso_week"]] + [entry]
    rest = [x for x in prev if x["iso_week"] != entry["iso_week"]]
    best = max(same, key=lambda x: (x["complete"], x["ts"]))
    out = rest + [best]
    out.sort(key=lambda x: -x["ts"])
    return out[:KEEP]


def apply(prev_data, entry, rows, now):
    """New data. Pure. `met_since` is kept only while the stored history itself still says met (the stored flag is never believed on its own)."""
    prev_scans, _ = clean_data(prev_data, now)
    prev_cond = prev_data.get("condition") if isinstance(prev_data, dict) and isinstance(prev_data.get("condition"), dict) else {}
    was_met = condition(prev_scans)["met"]
    since = prev_cond.get("met_since") if _int(prev_cond.get("met_since")) and prev_cond["met_since"] <= now else None
    scans = merge_scans(prev_scans, entry)
    cond = condition(scans)
    if cond["met"]:
        cond["met_since"] = since if (was_met and since is not None) else int(now)
    rows = sorted(rows, key=lambda r: (-r["freeable"], r["name"]))[:MAX_PROJECTS]
    return {"schema": SCHEMA, "scans": scans, "projects": rows, "condition": cond}


# ---------------------------------------------------------------- scanning
def _project_row(rep, name):
    idle = rep.get("idle_days")
    in_use = idle is not None and idle < tidy.IDLE_DAYS
    by = {k: int(rep["bytes"][k]) for k in CLASSES}
    cnt = {k: int(rep["counts"][k]) for k in CLASSES}
    idle_regen = 0 if in_use else by["regenerable"]
    row = {"name": name, "partial": bool(rep["partial"]), "git": bool(rep["git"]), "idle_days": idle, "counts": cnt, "bytes": by,
           "freeable": by["disposable"] + idle_regen}
    return row, in_use


def collect(now, total_seconds=TOTAL_SECONDS, scan_fn=None, projects_fn=None):
    """(scan entry, project rows). A project that cannot be scanned, or is not reached before the total deadline, counts as skipped and makes the scan incomplete."""
    scan_fn = scan_fn or tidy.scan
    projs = (projects_fn or __import__("shipmiracle.projects", fromlist=["x"]).list_projects)()
    t0 = time.monotonic()
    deadline = t0 + total_seconds
    tot = {k: 0 for k in BYTE_KEYS}
    rows, scanned, skipped, partial = [], 0, 0, False
    for p in projs:
        remaining = deadline - time.monotonic()
        if remaining <= 0.5:
            skipped += 1
            continue
        try:
            rep = scan_fn(p.real, max_seconds=min(tidy.MAX_SECONDS, remaining), now=now)
            row, in_use = _project_row(rep, p.name)
        except Exception:                      # any failure of one project (also a bug) only skips that project
            skipped += 1
            continue
        scanned += 1
        partial = partial or row["partial"]
        by = row["bytes"]
        tot["disposable"] += by["disposable"]
        tot["review"] += by["review"]
        tot["regenerable_in_use" if in_use else "regenerable_idle"] += by["regenerable"]
        clean = clean_project(row)
        if clean:
            rows.append(clean)
    entry = {"ts": int(now), "iso_week": iso_week(now), "complete": skipped == 0 and not partial, "projects_scanned": scanned, "projects_skipped": skipped,
             "duration_s": round(time.monotonic() - t0, 1), "bytes": tot}
    return entry, rows


# ---------------------------------------------------------------- storage
def _repair(base):
    """Remove a forged tidy.json by name relative to the opened state folder (never through a link): a link, pipe or file is unlinked; an EMPTY folder is removed;
    a folder with content is kept and refused with a fixed message (no path)."""
    try:
        fd = os.open(str(state.root(base)), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0))
    except OSError:
        raise SafetyError("the state folder cannot be opened safely")
    try:
        st = os.fstat(fd)
        if not stat.S_ISDIR(st.st_mode) or st.st_uid != state._uid():
            raise SafetyError("the state folder is not ours")
        try:
            e = os.lstat(NAME, dir_fd=fd)
        except FileNotFoundError:
            return
        if stat.S_ISDIR(e.st_mode):
            try:
                os.rmdir(NAME, dir_fd=fd)
            except OSError:
                raise SafetyError("tidy.json is not a regular file")
        else:
            os.unlink(NAME, dir_fd=fd)
    finally:
        os.close(fd)


def _read_prev(base, now=None, repair=True):
    """Stored data or None. A forged tidy.json (link, pipe, folder, foreign owner or writer, garbage, wrong shape, over the cap) counts as no history and, when
    `repair`, is removed so the next write works. A transient failure (no file handles, I/O error) raises: the file is kept and this run does not write."""
    path = state.root(base) / NAME
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return None
    except OSError:
        raise ShipmiracleError("tidy.json could not be checked now; try again later")
    forged = not stat.S_ISREG(st.st_mode) or st.st_size > MAX_BYTES
    data = None
    if not forged:
        try:
            env = state.read(NAME, base)
            if env.get("writer") != WRITER or not isinstance(env.get("data"), dict) or type(env["data"].get("schema")) is not int or env["data"]["schema"] != SCHEMA:
                forged = True
            else:
                data = env["data"]
        except (SafetyError, SchemaError):
            forged = True
        except NotFound:
            return None
        except OSError:
            raise ShipmiracleError("tidy.json could not be read now; try again later")
    if forged:
        if repair:
            _repair(base)
        return None
    return data


def last_complete(base, now=None):
    scans, _ = clean_data(_read_prev(base, repair=False), now)
    done = [s for s in scans if s["complete"]]
    return max(done, key=lambda s: s["ts"]) if done else None


def _event_recorded(since, base) -> bool:
    """True when a tidy.condition_met event for this met_since is in the recent events (best effort: older, rotated events are not looked at). An unreadable log counts as recorded, so a broken log is not spammed."""
    try:
        from . import events
        return any(e.get("kind") == "tidy.condition_met" and isinstance(e.get("data"), dict) and e["data"].get("met_since") == since for e in events.tail(500, base=base))
    except Exception:
        return True


def _encode(data) -> int:
    return len(json.dumps({"v": 1, "ts": 0, "writer": WRITER, "data": data}, sort_keys=True)) + 1


def _fit(data):
    """Drop the smallest project rows (one at a time) until the file fits in MAX_BYTES with a margin; refuse when even the history alone does not."""
    while _encode(data) + MARGIN > MAX_BYTES:
        if not data["projects"]:
            raise UsageError("tidy.json would exceed %d bytes" % MAX_BYTES)
        data["projects"].pop()
    return data


def run(write, weekly, now=None, base=None, scan_fn=None, projects_fn=None, total_seconds=TOTAL_SECONDS) -> dict:
    """Do one run. Returns a summary dict (numbers only): skipped (bool), wrote (bool), entry, condition."""
    now = time.time() if now is None else now
    if weekly:
        last = last_complete(base, now)
        if last is not None and 0 <= now - last["ts"] < FRESH_DAYS * 86400:
            return {"skipped": True, "wrote": False, "age_days": int((now - last["ts"]) // 86400)}
    entry, rows = collect(now, total_seconds, scan_fn, projects_fn)
    out = {"skipped": False, "wrote": False, "entry": entry, "rows": len(rows)}
    if not write:
        out["condition"] = apply(_read_prev(base, now, repair=False), entry, rows, now)["condition"]
        return out
    with state.locked("tidy-run", base, 30.0):
        data = _fit(apply(_read_prev(base, now), entry, rows, now))
        state.write(NAME, data, WRITER, base)
    out["wrote"], out["condition"] = True, data["condition"]
    c = data["condition"]
    if c["met"] and not _event_recorded(c["met_since"], base):
        from . import events
        events.emit("tidy.condition_met", {"weeks_over": c["weeks_over"], "threshold_bytes": THRESHOLD, "met_since": c["met_since"]}, base=base)
    return out


def summary_line(res) -> str:
    if res.get("skipped"):
        return "Tidy: skipped, the last complete weekly scan is %d day(s) old." % res["age_days"]
    e, c = res["entry"], res["condition"]
    b = e["bytes"]
    return ("Tidy: %d project(s) scanned, %d skipped%s; can be freed %s (throw-away %s, rebuildable and idle %s); needs your decision %s; "
            "over 2 GB: %d of %d week(s) in a row%s; %s." % (
                e["projects_scanned"], e["projects_skipped"], "" if e["complete"] else " (partial scan)", tidy.human_bytes(freeable(b)),
                tidy.human_bytes(b["disposable"]), tidy.human_bytes(b["regenerable_idle"]), tidy.human_bytes(b["review"]),
                c["weeks_over"], c["weeks_needed"], " (condition met)" if c["met"] else "", "history saved" if res["wrote"] else "not saved"))


def run_cli(a) -> int:
    import sys
    from . import cli
    if a.project:
        raise UsageError("--all, --write and --weekly scan every project: do not name one")
    try:
        os.nice(10)
    except OSError:
        pass
    res = run(bool(a.write), bool(a.weekly))
    if a.json:
        cli._json({"tidy_all": {k: v for k, v in res.items() if k != "rows"}})
    else:
        sys.stdout.write(summary_line(res) + "\n")
    return 0
