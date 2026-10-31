"""The authority of the change requests: `<state>/v1/cr/<pid>.jsonl`, an append-only log (one JSON line, <= 1 KB, written under the flock
`<pid>.lock`, files 0600 in 0700 folders). The state of a project is the replay of its log through engine.apply_tr. `.shipmiracle/work.json` in
the repository is only a rendering of that state: it is never read for a decision; a copy that does not match the sha of the last render
is reported (`cr.work_forged`) and overwritten.

pid = projects.project_id(checkout) = sha256("shipmiracle-project:" + realpath)[:12] (a worktree is its own checkout, so WIP = 1 is per worktree)."""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import time
from pathlib import Path

from .. import SafetyError, SchemaError, UsageError
from .. import events, paths, projects, state
from . import engine, types

MAX_LINE = engine.MAX_LINE
KEEP_DAYS = 14
COMPACT_LINES = 2000                                      # transact folds old finished CRs once the log is longer than this
IMPORT_MAX_BYTES = 64 * 1024
IMPORT_MAX_CRS = 20
_STAGE_RE = re.compile(r"next|skipped|done:[A-Za-z0-9_.-]{1,40}|fail:[0-9]")
_ID_RE = re.compile(r"CR-\d{3,6}")
_SHA_RE = re.compile(r"[0-9a-f]{40,64}")
_RESET_ON_IMPORT = ("approve", "verify", "review")


# ---------- paths ----------

def pid_of(project_dir) -> str:
    return projects.project_id(project_dir)


def _sbase(base):
    return Path(base) if base is not None else paths.state_dir()


def cr_dir(base=None) -> Path:
    b = _sbase(base)
    paths.assert_isolated(b)
    return state.ensure_dir(state.ensure_root(b) / "cr")


def log_path(project_dir, base=None) -> Path:
    return _sbase(base) / "v1" / "cr" / (pid_of(project_dir) + ".jsonl")


def _lock_path(pid, base) -> Path:
    return cr_dir(base) / (pid + ".lock")


def _rendered_path(pid, base) -> Path:
    return cr_dir(base) / (pid + ".rendered")


def history_path(project_dir, base=None) -> Path:
    """The append-only history of the CRs compaction folded away (one JSON line per CR); never rewritten, never deleted."""
    return _sbase(base) / "v1" / "cr" / (pid_of(project_dir) + ".history.jsonl")


def snapshot_path(project_dir, cr_id, base=None) -> Path:
    if not _ID_RE.fullmatch(cr_id or ""):
        raise UsageError("bad CR id")
    return _sbase(base) / "v1" / "cr" / ("%s.%s.snap.json" % (pid_of(project_dir), cr_id))


def work_path(project_dir) -> Path:
    return Path(project_dir) / ".shipmiracle" / "work.json"


# ---------- log io ----------

def _read_log_bytes(path):
    try:
        return state.read_bytes_nofollow(path)
    except FileNotFoundError:
        return None


def _parse_lines(raw):
    """([line dicts], corrupt count). A line that is not a JSON object with ts/op, or is over 1 KB, counts as corrupt and is skipped."""
    out, bad = [], 0
    if not raw:
        return out, bad
    for ln in raw.split(b"\n"):
        if not ln.strip():
            continue
        if len(ln) > MAX_LINE:
            bad += 1
            continue
        try:
            d = json.loads(ln.decode("utf-8"))
        except ValueError:
            bad += 1
            continue
        if not isinstance(d, dict) or not isinstance(d.get("op"), str) or not engine._int(d.get("ts")):
            bad += 1
            continue
        out.append(d)
    return out, bad


def replay(lines, project=None):
    """(work, skipped): the work dict built by applying `lines`; lines the engine cannot apply are skipped and counted."""
    work = engine.new_work()
    skipped = 0
    for ln in lines:
        try:
            engine.apply_tr(work, ln)
        except Exception:
            skipped += 1
    work["project"] = project
    return work, skipped


def _append_raw(path, data: bytes, sync: bool = False):
    """One write() of whole lines under the caller's lock. A torn last line (no newline) is terminated first so it cannot swallow ours.
    sync=True: fsync before the file is closed (the history file, which is the only copy of what compaction folds)."""
    fd = os.open(str(path), os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != state._uid():
            raise SafetyError("%s is not our regular file" % Path(path).name)
        if st.st_mode & 0o077:
            os.fchmod(fd, 0o600)
        if st.st_size > 0 and os.pread(fd, 1, st.st_size - 1) != b"\n":
            data = b"\n" + data
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view):]
        if sync:
            os.fsync(fd)
    finally:
        os.close(fd)


def _encode(trs):
    out = []
    for tr in trs:
        b = engine.dumps_line(tr).encode("utf-8")
        if len(b) > MAX_LINE:
            raise UsageError("log line is %d bytes (max %d)" % (len(b), MAX_LINE))
        out.append(b + b"\n")
    return b"".join(out)


def append(project_dir, trs, base=None, timeout: float = 5.0):
    """Append transitions to the project's log under its lock (no replay; engine users call transact instead)."""
    pid = pid_of(project_dir)
    data = _encode(trs)
    with state.lock_file(_lock_path(pid, base), timeout):
        _append_raw(log_path(project_dir, base), data)


# ---------- import of a committed work.json ----------

def _import_lines(raw: bytes, now):
    """Log lines for the CRs in a committed work.json, with approve/verify/review reset to `next` (fails closed). [] when unusable."""
    if len(raw) > IMPORT_MAX_BYTES:
        return []
    try:
        d = json.loads(raw.decode("utf-8"))
    except ValueError:
        return []
    if not isinstance(d, dict) or not isinstance(d.get("crs"), list):
        return []
    out = []
    for c in d["crs"][:IMPORT_MAX_CRS]:
        if not isinstance(c, dict) or not isinstance(c.get("id"), str) or not _ID_RE.fullmatch(c["id"]) or int(c["id"][3:]) > engine.ID_MAX:
            continue
        title = engine._clean_text(c.get("title") or "", 120)
        lane = c.get("lane") if c.get("lane") in types.LANES else "full"
        status = c.get("status") if c.get("status") in ("open", "queued", "blocked") + engine.TERMINAL else "queued"
        terminal = status in engine.TERMINAL
        stages = {}
        raw_st = c.get("stages") if isinstance(c.get("stages"), dict) else {}
        for s in types.ORDER:
            v = raw_st.get(s)
            v = v if isinstance(v, str) and _STAGE_RE.fullmatch(v) else "next"
            if not terminal and s in _RESET_ON_IMPORT:
                v = "next"
            stages[s] = v
        base = c.get("base") if isinstance(c.get("base"), str) and _SHA_RE.fullmatch(c["base"]) else None
        opened = c.get("opened") if engine._int(c.get("opened")) and c["opened"] >= 0 else now
        blocked = c.get("blocked") if isinstance(c.get("blocked"), str) and engine._REASON_RE.fullmatch(c["blocked"]) else None
        if status == "blocked" and blocked is None:
            blocked = "imported"
        if not title:
            continue
        out.append({"ts": now, "cr": c["id"], "op": "import", "stage": None, "by": "import", "sid8": None,
                    "ev": {"kind": "engine", "ref": None, "data": {"title": title, "lane": lane, "status": status, "base": base, "opened": opened,
                                                                 "skip": [], "stages": stages, "blocked": blocked}}})
    return out


# ---------- rendering ----------

def render_bytes(work) -> bytes:
    return (json.dumps(engine.render(work), sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def _ensure_shipmiracle_dir(project_dir) -> Path:
    d = Path(project_dir) / ".shipmiracle"
    try:
        st = os.lstat(d)
    except FileNotFoundError:
        os.mkdir(d, 0o755)
        return d
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        raise SafetyError(".shipmiracle is a symlink or not a folder")
    return d


def _sync_render(project_dir, work, pid, base, suppress_forged=False):
    """Write .shipmiracle/work.json (0644, atomic) and the render sha. Reports a copy that is not the one the engine wrote last."""
    expected = render_bytes(work)
    wp = work_path(project_dir)
    try:
        cur = state.read_bytes_nofollow(wp)
    except FileNotFoundError:
        cur = None
    except SafetyError:
        cur = b"\0symlink"
    rp = _rendered_path(pid, base)
    try:
        last = state.read_bytes_nofollow(rp).decode("ascii", "replace").strip() or None
    except (FileNotFoundError, SafetyError):
        last = None
    want = hashlib.sha256(expected).hexdigest()
    if cur is not None and not suppress_forged:
        cur_sha = hashlib.sha256(cur).hexdigest()
        if (last is not None and cur_sha != last) or (last is None and cur != expected):
            events.emit("cr.work_forged", {"file": ".shipmiracle/work.json"}, project=pid, src="playbook", base=base)
    if cur != expected:
        _ensure_shipmiracle_dir(project_dir)
        if cur == b"\0symlink":
            os.unlink(wp)
        state.atomic_write(wp, expected, 0o644)
    if last != want:
        state.atomic_write(rp, (want + "\n").encode("ascii"), 0o600)


def render(project_dir, base=None):
    """`shipm cr render`: rewrite .shipmiracle/work.json from the log. Returns the work."""
    return load_work(project_dir, base)


# ---------- load ----------

def load(project_dir, base=None) -> dict:
    """Read-only replay (no lock, no writes, no events): what Health and the brief use. With no log, a committed work.json is shown as it
    would be imported."""
    name = os.path.basename(os.path.realpath(str(project_dir)))
    raw = _read_log_bytes(log_path(project_dir, base))
    lines, _ = _parse_lines(raw)
    if not lines:
        try:
            lines = _import_lines(state.read_bytes_nofollow(work_path(project_dir)), int(time.time()))
        except (OSError, SafetyError, SchemaError):
            lines = []
    work, _ = replay(lines, name)
    return work


def _locked_load(project_dir, pid, base):
    """(work, imported, skipped) under the lock; persists the import of a committed work.json when there is no log yet."""
    name = os.path.basename(os.path.realpath(str(project_dir)))
    lp = log_path(project_dir, base)
    lines, bad = _parse_lines(_read_log_bytes(lp))
    imported = False
    if not lines:
        try:
            raw = state.read_bytes_nofollow(work_path(project_dir))
        except (FileNotFoundError, SafetyError):
            raw = None
        if raw is not None:
            imp = _import_lines(raw, int(time.time()))
            if imp:
                _append_raw(lp, _encode(imp))
                lines, imported = imp, True
                events.emit("cr.imported", {"n": len(imp)}, project=pid, src="playbook", base=base)
    work, skipped = replay(lines, name)
    return work, imported, bad + skipped, bool(lines)


def transact(project_dir, fn, base=None, do_render: bool = True, timeout: float = 5.0):
    """Under the project's lock: replay the log, call fn(work) -> (result, transitions) (the engine functions mutate `work` and return the
    transitions), append the transitions in one write, re-render work.json. Nothing is written when fn raises."""
    pid = pid_of(project_dir)
    with state.lock_file(_lock_path(pid, base), timeout):
        work, imported, bad, has_log = _locked_load(project_dir, pid, base)
        result, trs = fn(work)
        if trs:
            _append_raw(log_path(project_dir, base), _encode(trs))
            _maybe_compact(project_dir, pid, base)
        if do_render and (trs or has_log or imported):
            _sync_render(project_dir, work, pid, base, suppress_forged=imported)
    return result


def load_work(project_dir, base=None) -> dict:
    """The work dict with the writer duties done: import of a committed work.json, forged-file detection, re-render."""
    return transact(project_dir, lambda w: (w, []), base)


def save_snapshot(project_dir, cr_id, snap, base=None):
    """The diff base of a CR (commit id + untracked list at open) next to the log."""
    cr_dir(base)
    p = snapshot_path(project_dir, cr_id, base)
    state.atomic_write(p, (json.dumps(snap, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"), 0o600)
    try:
        from . import diffstat
        diffstat.pin(project_dir, cr_id, snap.get("base"))        # a dangling stash-create base must survive git gc
    except Exception:
        pass


def load_snapshot(project_dir, cr_id, base=None):
    try:
        d = json.loads(state.read_bytes_nofollow(snapshot_path(project_dir, cr_id, base)).decode("utf-8"))
    except (OSError, ValueError, SafetyError):
        return None
    return d if isinstance(d, dict) else None


# ---------- compaction ----------

def compact(project_dir, now=None, base=None) -> int:
    """Fold CRs finished more than 14 days ago into one `archived` line. Returns how many CRs were folded."""
    now = int(time.time()) if now is None else now
    pid = pid_of(project_dir)
    with state.lock_file(_lock_path(pid, base), 5.0):
        return _compact_locked(project_dir, now, base)


def _maybe_compact(project_dir, pid, base) -> None:
    """Called by transact (lock held) after an append: a log over COMPACT_LINES lines is compacted without anyone having to run `shipm cr render`."""
    try:
        lp = log_path(project_dir, base)
        if os.stat(str(lp)).st_size < COMPACT_LINES * 40:        # cheap size test first: a line is never shorter than ~40 bytes
            return
        raw = _read_log_bytes(lp)
        if raw.count(b"\n") > COMPACT_LINES:
            _compact_locked(project_dir, int(time.time()), base)
    except Exception:
        pass                                            # compaction is housekeeping; the transaction stands


_HEAD_RE = re.compile(r"[0-9a-f]{7,40}")


def deliver_heads(lines) -> dict:
    """{cr id: the commit (<= 12 hex) the Deliver stage recorded as git_delivered's head}; the last one wins."""
    out = {}
    for ln in lines:
        if ln.get("op") != "advance" or ln.get("stage") != "deliver":
            continue
        ev = ln.get("ev") if isinstance(ln.get("ev"), dict) else {}
        d = ev.get("data") if isinstance(ev.get("data"), dict) else {}
        h = d.get("head")
        if isinstance(h, str) and _HEAD_RE.fullmatch(h) and isinstance(ln.get("cr"), str):
            out[ln["cr"]] = h
    return out


def _history_records(crs, lines) -> list:
    heads = deliver_heads(lines)
    return [{"id": c["id"], "title": engine._clean_text(c["title"], 120), "status": c["status"], "opened": c["opened"], "closed": c["closed"], "commit": heads.get(c["id"])}
            for c in crs]


def read_history(project_dir, base=None) -> list:
    """The history records in file order (corrupt or foreign lines skipped; a missing file = [])."""
    out, seen = [], set()
    for d in _parse_history(_read_log_bytes(history_path(project_dir, base))):
        if d["id"] not in seen:
            seen.add(d["id"])
            out.append(d)
    return out


def _parse_history(raw) -> list:
    out = []
    for ln in (raw or b"").split(b"\n"):
        if not ln.strip() or len(ln) > MAX_LINE:
            continue
        try:
            d = json.loads(ln.decode("utf-8"))
        except ValueError:
            continue
        if not isinstance(d, dict) or not isinstance(d.get("id"), str) or not _ID_RE.fullmatch(d["id"]) or d.get("status") not in engine.TERMINAL:
            continue
        cm = d.get("commit")
        out.append({"id": d["id"], "title": engine._clean_text(d.get("title") or "", 120), "status": d["status"],
                    "opened": d.get("opened") if engine._int(d.get("opened")) else None, "closed": d.get("closed") if engine._int(d.get("closed")) else None,
                    "commit": cm if isinstance(cm, str) and _HEAD_RE.fullmatch(cm) else None})
    return out


def _history_append(project_dir, base, recs) -> int:
    """Append the records whose id is not in the history yet (lock held by the caller); one write, fsync. Returns how many were added."""
    if not recs:
        return 0
    hp = history_path(project_dir, base)
    have = {d["id"] for d in _parse_history(_read_log_bytes(hp))}
    new = []
    for r in recs:
        if r["id"] in have:
            continue
        have.add(r["id"])
        b = (json.dumps(r, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")
        if len(b) <= MAX_LINE:
            new.append(b)
    if new:
        _append_raw(hp, b"".join(new), sync=True)
    return len(new)


def _compact_locked(project_dir, now, base) -> int:
    lp = log_path(project_dir, base)
    raw = _read_log_bytes(lp)
    lines, _ = _parse_lines(raw)
    work, _ = replay(lines)
    old = {c["id"] for c in work["crs"] if c["status"] in engine.TERMINAL and c.get("closed") is not None and now - c["closed"] > KEEP_DAYS * 86400}
    if not old:
        return 0
    _history_append(project_dir, base, _history_records([c for c in work["crs"] if c["id"] in old], lines))     # first: the folded CRs survive a crash between the two writes
    prev, mx, n = [], work.get("_max_id", 0), 0
    keep = []
    for ln in lines:
        if ln["op"] == "archived":
            dd = (ln.get("ev") or {}).get("data") or {}
            prev += [e for e in dd.get("crs", []) if isinstance(e, list)]
            n += int(dd.get("n", 0))
        elif ln.get("cr") in old:
            continue
        else:
            keep.append(ln)
    for c in work["crs"]:
        if c["id"] in old:
            prev.append([c["id"], c["status"][0], c["closed"]])
    n += len(old)
    prev = prev[-30:]
    arch = {"ts": now, "cr": None, "op": "archived", "stage": None, "by": "engine", "sid8": None,
            "ev": {"kind": "engine", "ref": None, "data": {"max": mx, "n": n, "crs": prev}}}
    body = _encode([arch]) + b"".join((engine.dumps_line(k).encode("utf-8") + b"\n") for k in keep)
    state.atomic_write(lp, body, 0o600)
    for cid in old:
        try:
            os.unlink(snapshot_path(project_dir, cid, base))
        except OSError:
            pass
        try:
            from . import diffstat
            diffstat.unpin(project_dir, cid)
            diffstat.unpin(project_dir, cid + "-review")
        except Exception:
            pass
    return len(old)


# ---------- registry (the playbook sha snapshot) ----------

def registry_entry(project_dir):
    """The project's registry entry (read-only), or None when the registry is absent/unreadable/has no entry."""
    from .. import registry
    try:
        return registry.entry(pid_of(project_dir))
    except Exception:
        return None


def registry_snapshot_write(project_dir, snapshot) -> None:
    """Store {sha256, type, autopilot, overrides} in this project's registry entry. The one place that writes the registry for the
    playbook; the owner-only registry writer lives in shipmiracle.registry. Until T3 lets set_field take a `playbook` key this raises
    NotImplementedError (fail closed: no snapshot means the playbook stays untrusted)."""
    from .. import registry
    if "playbook" not in getattr(registry, "SETTABLE", ()):
        raise NotImplementedError("shipmiracle.registry.set_field does not accept the 'playbook' key yet (T3 wires the owner-only writer)")
    registry.set_field(pid_of(project_dir), "playbook", snapshot)
