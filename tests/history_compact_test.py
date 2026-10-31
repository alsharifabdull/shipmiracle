#!/usr/bin/env python3
"""history_compact_test: shipmiracle/playbook/store.py compact() keeps an append-only history of the CRs it folds away.
One JSON line per CR (id, title, status, opened, closed, commit) in <state>/v1/cr/<pid>.history.jsonl, written (fsync, same lock) BEFORE the fold, ids already
present skipped, never deleted; the panel's history reads it back.
Run: python3 tests/history_compact_test.py"""
import json, os, pathlib, stat, sys, time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import release_fixture as X
from release_fixture import check, git, mkrepo, commit

from shipmiracle import LockTimeout, state  # noqa: E402
from shipmiracle.playbook import engine, store  # noqa: E402
from shipmiracle.report import panel  # noqa: E402

d = mkrepo("hist", "2026-01-10")
h1 = git(d, "rev-parse", "HEAD")
git(d, "tag", "-a", "v1.0", "-m", "r", date="2026-01-10")
h2 = commit(d, "two", "2026-02-01")
X.set_software(d)
OLD = 1760000000                                    # 9 Oct 2025: far older than 14 days
sim = X.Sim(d, t=OLD)
sim.deliver("First finished", head=h1)
sim.deliver("Second finished", head=h2)
sim.abandon("Dropped")
sim.append()
sim2 = X.Sim(d, t=int(time.time()) - 3600)          # an hour ago: stays in the log
sim2.w = sim.w
sim2.deliver("Recent finished")
sim2.append()

hp = store.history_path(d, X.STATE)
lp = store.log_path(d, X.STATE)
check("history path sits next to the CR log", hp.parent == lp.parent and hp.name == lp.name.replace(".jsonl", ".history.jsonl"), hp)
check("no history before the first fold", not hp.exists())
log_before = lp.read_bytes()

# 1. a crash between the history write and the fold: history is already complete, the log is untouched
real_aw = state.atomic_write
def boom(*a, **k):
    raise OSError("disk full")
state.atomic_write = boom
try:
    try:
        store.compact(d, base=X.STATE)
        crashed = False
    except OSError:
        crashed = True
finally:
    state.atomic_write = real_aw
check("history is written before the fold: a failing fold leaves the history on disk and the log unchanged", crashed and hp.exists() and lp.read_bytes() == log_before)
recs = [json.loads(l) for l in hp.read_text().splitlines()]
check("one line per folded CR (3), none for the recent one", [r["id"] for r in recs] == ["CR-001", "CR-002", "CR-003"], recs)
check("line fields: id, title, status, opened, closed, commit", all(set(r) == {"id", "title", "status", "opened", "closed", "commit"} for r in recs), recs[0])
check("title, status and the Deliver commit (12 hex) are kept; abandoned has no commit", recs[0]["title"] == "First finished" and recs[0]["status"] == "delivered" and recs[0]["commit"] == h1[:12]
      and recs[1]["commit"] == h2[:12] and recs[2]["status"] == "abandoned" and recs[2]["commit"] is None, recs)
check("closed and opened are the engine's epoch seconds", all(isinstance(r["closed"], int) and isinstance(r["opened"], int) and r["opened"] <= r["closed"] for r in recs), recs)
check("history file is 0600", stat.S_IMODE(hp.stat().st_mode) == 0o600, oct(hp.stat().st_mode))

# 2. the rerun after the crash folds and adds no duplicate
n = store.compact(d, base=X.STATE)
recs2 = [json.loads(l) for l in hp.read_text().splitlines()]
check("rerun folds the 3 CRs and the history still has exactly 3 lines (no duplicates)", n == 3 and len(recs2) == 3 and recs2 == recs, (n, len(recs2)))
check("the log no longer holds the folded CRs but still the recent one", [c["id"] for c in store.load(d, X.STATE)["crs"]] == ["CR-004"], [c["id"] for c in store.load(d, X.STATE)["crs"]])

# 3. replay: the old log comes back (restore from a backup) and is compacted again: still no duplicates
lp.write_bytes(log_before)
n = store.compact(d, base=X.STATE)
check("replaying the old log folds again and the history is unchanged (ids already present are skipped)", n == 3 and hp.read_text().count("\n") == 3 and [json.loads(l) for l in hp.read_text().splitlines()] == recs)
check("a compaction with nothing to fold does not touch the history", store.compact(d, base=X.STATE) == 0 and hp.read_text().count("\n") == 3)

# 4. append-only: a later fold adds new lines after the old ones, nothing is rewritten; a corrupt line does not stop it
with open(str(hp), "ab") as fh:
    fh.write(b"{not json\n")
sim3 = X.Sim(d, t=OLD + 86400)
sim3.w = store.load(d, X.STATE)
cr = sim3.deliver("Later old one", head=h2)
sim3.append()
size_before = hp.stat().st_size
head_bytes = hp.read_bytes()
n = store.compact(d, now=int(time.time()) + 30 * 86400, base=X.STATE)
after = hp.read_bytes()
check("a later fold appends to the end: the earlier bytes (also the corrupt line) are untouched", n >= 1 and after.startswith(head_bytes) and len(after) > size_before, (n, size_before, len(after)))
hist = store.read_history(d, X.STATE)
check("read_history: all folded CRs once, the corrupt line skipped", [h["id"] for h in hist][:3] == ["CR-001", "CR-002", "CR-003"] and len({h["id"] for h in hist}) == len(hist) >= 4, [h["id"] for h in hist])

# 5. fsync and the lock
syncs = []
real_fsync = os.fsync
os.fsync = lambda fd: (syncs.append(fd), real_fsync(fd))[1]
try:
    added = store._history_append(d, X.STATE, [{"id": "CR-777", "title": "x", "status": "delivered", "opened": 1, "closed": 2, "commit": None}])
finally:
    os.fsync = real_fsync
check("the history append is fsynced", added == 1 and len(syncs) >= 1, (added, syncs))
with state.lock_file(store._lock_path(store.pid_of(d), X.STATE), 2.0):
    t0 = time.time()
    try:
        store.compact(d, now=int(time.time()) + 90 * 86400, base=X.STATE)
        waited = False
    except LockTimeout:
        waited = True
check("compaction (and so the history write) happens under the CR log lock: with the lock held it times out and writes nothing", waited and "CR-777" in hp.read_text() and hp.read_text().count("CR-777") == 1)

# 6. the history is never deleted by later compactions, and the panel shows folded CRs
before = hp.read_bytes()
store.compact(d, now=int(time.time()) + 365 * 86400, base=X.STATE)
check("history is never deleted or shortened by a later compaction", hp.exists() and hp.read_bytes().startswith(before))
out = panel.data(d, X.STATE)["history"]
ids = [h["id"] for h in out]
check("panel history includes CRs that were folded out of the log (newest first, max 10)", len(out) <= 10 and "CR-001" in [h["id"] for h in store.read_history(d, X.STATE)] and ids == sorted(ids, key=lambda i: -next(h["closed"] for h in out if h["id"] == i)), ids)
by = {h["id"]: h for h in panel.data(d, X.STATE)["history"]}
check("... with the release the folded CR shipped in (CR-001 -> 1.0) from the stored commit", by.get("CR-001", {}).get("release") == "1.0" and by.get("CR-003", {}).get("status") == "abandoned", by)

X.finish()
