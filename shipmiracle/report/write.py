"""Where reports go (spec section 1.4) and the panel index.
CR report  -> <project>/docs/reports/YYYY-MM-DD-CR-012.md   (repo, kept)
Stage      -> <state>/v1/reports/<pid>/YYYY-MM-DD-CR-012-<stage>[-n].md   (private, 30 days)
Digest     -> <state>/v1/digest/YYYY-MM-DD.md   (private, 30 days)
Index      -> <state>/v1/reports/index.json  {"v":1,"items":[...]} newest first, 500 items, written under a lock.
Every write refuses a symlink and is atomic; a report is linted before it is written (a template bug must not reach disk)."""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import time
from pathlib import Path

from .. import SafetyError, UsageError, paths, state
from ..playbook import engine, store
from . import facts as F
from . import lint, templates

KEEP_S = 30 * 86400
MAX_INDEX = 500
_PID_DIRS = re.compile(r"[0-9a-f]{12}")


def _sbase(base):
    return Path(base) if base is not None else paths.state_dir()


def _day(ts):
    return time.strftime("%Y-%m-%d", time.localtime(ts))


def _ensure(base, *parts) -> Path:
    b = _sbase(base)
    paths.assert_isolated(b)
    d = state.ensure_root(b)
    for p in parts:
        d = state.ensure_dir(d / p)
    return d


def _check(text, what):
    problems = lint.lint_text(text)
    if problems:
        raise UsageError("%s failed its own lint: %s" % (what, "; ".join(problems[:3])))


def _rid(project, stem) -> str:
    """The index id: unique across projects (every project has its own CR-001 on the same day), made of the characters the panel accepts for an id."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", "%s-%s" % (project, stem))[:120]


def index_add(item, base=None) -> None:
    d = _ensure(base, "reports")
    ip = d / "index.json"
    with state.lock_file(d / "index.lock", 5.0):
        try:
            cur = json.loads(state.read_bytes_nofollow(ip).decode("utf-8"))
            items = cur["items"] if isinstance(cur, dict) and isinstance(cur.get("items"), list) else []
        except Exception:
            items = []
        items = [item] + [x for x in items if isinstance(x, dict) and x.get("path") != item["path"]]
        state.atomic_write(ip, (json.dumps({"v": 1, "items": items[:MAX_INDEX]}, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8"), 0o600)


def write_stage(project_dir, cr_id, stage, base=None, now=None, attempt=None) -> Path:
    """The stage report of `stage` for a CR, from the facts as they are now. Returns the file."""
    if stage not in F.ORDER:
        raise UsageError("unknown stage")
    f = F.build(project_dir, cr_id, base, now, git=False)       # a stage report never shows git facts: no git processes in the hook
    if f["cr"] is None:
        raise UsageError("no such change request")
    text = templates.stage_report(f, stage, attempt)
    _check(text, "stage report")
    pid = store.pid_of(project_dir)
    d = _ensure(base, "reports", pid)
    ts = next(s["ts"] for s in f["stages"] if s["id"] == stage) or f["generated"]
    stem = "%s-%s-%s" % (_day(ts), cr_id, stage)
    p, n = d / (stem + ".md"), 1
    while p.exists():
        n += 1
        p = d / ("%s-%d.md" % (stem, n))
    state.atomic_write(p, text.encode("utf-8"), 0o600)
    word, v, _detail = templates.stage_verdict(f, stage, attempt)
    index_add({"id": _rid(f["project"], p.stem), "project": f["project"], "kind": "stage", "cr": cr_id, "stage": stage, "verdict": word, "ts": ts,
               "title": "%s %s" % (cr_id, f["labels"].get(stage, stage)), "sub": f["cr"]["title"], "path": str(p), "private": True}, base)
    return p


def write_cr(project_dir, cr_id, summary="pending", base=None, now=None) -> Path:
    """docs/reports/YYYY-MM-DD-CR-012.md in the repo for a delivered or abandoned CR; records the path in the log (op report) and
    enqueues the summary. Rewriting the same CR/day replaces the file."""
    f = F.build(project_dir, cr_id, base, now)
    if f["cr"] is None:
        raise UsageError("no such change request")
    if f["cr"]["status"] == "open" and f["cr"]["stage"] == "learn":
        # the engine delivers a CR only once its report exists, so the report is written while the CR is at learn (everything before it is done)
        f["cr"] = dict(f["cr"], status="delivered", closed=f["cr"]["closed"] or f["generated"])
    if f["cr"]["status"] not in ("delivered", "abandoned"):
        raise UsageError("%s is %s: a CR report is written when it is delivered or abandoned" % (cr_id, f["cr"]["status"]))
    from .. import config
    queued = summary == "pending" and config.get("guard.jobs") is True      # no guard job = nobody would ever fill the line: say so now
    pd = os.path.realpath(str(project_dir))
    learn = _learn(pd, f, cr_id, base, now)
    summ = summary if summary != "pending" or queued else "not generated"
    text = None
    for drop in ((), ("fix",), ("fix", "proposed")):             # a report that would break its own lint (40 lines) loses the Learn extras first, never fails
        g = {k: v for k, v in dict(f, **learn).items() if k not in drop}
        text = templates.cr_report(g, summ)
        if not lint.lint_text(text):
            break
    _check(text, "CR report")
    d = Path(pd) / "docs" / "reports"
    if os.path.lexists(str(Path(pd) / "docs")) and (os.path.islink(str(Path(pd) / "docs")) or os.path.islink(str(d))):
        raise SafetyError("docs or docs/reports is a symlink")
    os.makedirs(str(d), exist_ok=True)
    p = d / ("%s-%s.md" % (_day(f["cr"]["closed"] or f["generated"]), cr_id))
    rel = os.path.relpath(str(p), pd)
    body = text.encode("utf-8")
    sha = hashlib.sha256(body).hexdigest()
    _quarantine_forged(pd, p, rel, cr_id, base, now)
    state.atomic_write(p, body, 0o644)
    try:
        store.transact(pd, lambda w: (None, engine.record_report(w, cr_id, rel[:80], {"kind": "report_written", "by": "engine", "ts": int(time.time()) if now is None else int(now)}, sha=sha)), base)
    except Exception:
        pass                     # the report exists; without the log note the stage module does not accept it and writes it again
    if queued:
        try:
            from . import queue
            queue.enqueue(pd, p, f, base, now)
        except Exception:
            pass
    word, w = templates.cr_word(f)
    index_add({"id": _rid(f["project"], p.stem), "project": f["project"], "kind": "cr", "cr": cr_id, "stage": None, "verdict": w, "ts": f["cr"]["closed"] or f["generated"],
               "title": "%s %s" % (cr_id, f["cr"]["title"]), "sub": word.capitalize(), "path": str(p), "private": False}, base)
    return p


def _learn(pd, f, cr_id, base, now) -> dict:
    """The Learn step (the ONLY writer of proposals): F5 proposed assets (a delivered CR; at most 3, saved next to the log for the panel), the F6 playbook fix after a double-failed
    Verify (diff in the report, draft for `shipm playbook set --from-draft`) and the Short/Long measurement row. Every part is best effort and never raises."""
    out = {}
    try:
        from ..playbook import fixplan, gate, measure, toolbox
        cr = engine.get_cr(store.load(pd, base), cr_id) or {}
        names, created = fixplan.changed(pd, cr.get("base"))
        if f["cr"]["status"] == "delivered":
            rules = gate.stage_rules(pd) or {}
            rows = toolbox.candidates(pd, names, created, [a["path"] for a in rules.get("assets") or []], cr.get("opened") or 0, now)
            out["proposed"] = rows
            toolbox.proposals_save(pd, cr_id, rows, base, now)
        if fixplan.double_failed(pd, cr_id, base):
            prop = fixplan.for_cr(pd, names)
            out["fix"] = {"prop": prop, "draft": fixplan.ensure_draft(pd, f["project"], cr_id, prop, now) if prop else "none"}
        measure.record(pd, cr_id, base, now)
    except Exception:
        pass
    return out


def _regular_sha(p):
    """sha256 of a regular file read through a non-blocking handle; None for a FIFO, socket, directory or unreadable path (never read)."""
    try:
        fd = os.open(str(p), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except OSError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None
        h = hashlib.sha256()
        while True:
            c = os.read(fd, 1 << 16)
            if not c:
                return h.hexdigest()
            h.update(c)
    except OSError:
        return None
    finally:
        os.close(fd)


def _quarantine_forged(pd, p, rel, cr_id, base, now) -> None:
    """A file already at the report path that the engine did not write (no matching op:report line with its content sha) is renamed to
    <name>.forged-<ts> before the real report is written: the engine's own earlier report (same sha) is simply replaced."""
    if not os.path.lexists(str(p)):
        return
    try:
        known = (engine.get_cr(store.load(pd, base), cr_id) or {}).get("report_sha", {}).get(rel[:80])
    except Exception:
        known = None
    try:
        if not os.path.islink(str(p)) and known and _regular_sha(p) == known:
            return
    except OSError:
        pass
    ts = int(time.time()) if now is None else int(now)
    q, n = Path(str(p) + ".forged-%d" % ts), 1
    while os.path.lexists(str(q)):
        n += 1
        q = Path(str(p) + ".forged-%d-%d" % (ts, n))
    os.rename(str(p), str(q))


def write_digest(day, project_dirs, base=None) -> Path:
    rows = [F.project_day(pd, day, base) for pd in project_dirs]
    rows = [r for r in rows if r["delivered"] or r["open"] or r["queue"]]
    text = templates.digest(day, rows)
    _check(text, "digest")
    d = _ensure(base, "digest")
    p = d / (day + ".md")
    state.atomic_write(p, text.encode("utf-8"), 0o600)
    ts = int(time.mktime(time.strptime(day, "%Y-%m-%d"))) + 86399
    index_add({"id": "digest-" + day, "project": "", "kind": "digest", "cr": None, "stage": None, "verdict": "NOT TESTED", "ts": ts,
               "title": "Digest " + day, "sub": "%d projects" % len(rows), "path": str(p), "private": True}, base)
    return p


def prune(base=None, now=None) -> int:
    """Delete stage reports and digests older than 30 days (the CR reports in repos are never touched). Returns the number deleted."""
    now = time.time() if now is None else now
    b = _sbase(base) / "v1"
    n = 0
    for pat in ("reports/*/*.md", "digest/*.md"):
        for p in b.glob(pat):
            try:
                if now - p.lstat().st_mtime > KEEP_S:
                    os.unlink(str(p))
                    n += 1
            except OSError:
                pass
    return n
