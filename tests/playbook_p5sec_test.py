#!/usr/bin/env python3
"""P5 security remediation, engine/store/diffstat side: CR id overflow (L2), the report content sha in the log (M3), automatic log compaction (L6),
the diff base kept alive by a git ref and the gone-base fallback (L8). Temp git repos, SHIPMIRACLE_TEST=1; nothing of the owner's is touched.
Run: python3 tests/playbook_p5sec_test.py"""
import hashlib, json, os, pathlib, subprocess, sys, tempfile, time

ROOT = pathlib.Path(__file__).resolve().parent.parent
TMP = pathlib.Path(tempfile.mkdtemp(prefix="shipmiracle-p5sec-")).resolve()
HOME, DEV, STATE, CONF, WS = (TMP / n for n in ("home", "dev", "state", "config", "ws"))
ENV = dict(os.environ, SHIPMIRACLE_TEST="1", SHIPMIRACLE_HOME=str(HOME), SHIPMIRACLE_DEV=str(DEV), SHIPMIRACLE_STATE=str(STATE), SHIPMIRACLE_CONFIG=str(CONF), SHIPMIRACLE_WS=str(WS), HOME=str(HOME))
for k in ("SHIPMIRACLE_DEBUG", "CLAUDECODE", "SHIPMIRACLE_ENFORCE_OWNER"):
    ENV.pop(k, None)
os.environ.clear()
os.environ.update(ENV)
for d in (HOME, DEV, STATE, CONF, WS):
    d.mkdir(parents=True, exist_ok=True)
(HOME / ".gitconfig").write_text("[user]\n name = t\n email = t@example.com\n[init]\n defaultBranch = main\n[commit]\n gpgsign = false\n")
sys.path.insert(0, str(ROOT))
from shipmiracle.playbook import diffstat, engine, store  # noqa: E402

fails = 0
def check(name, ok, info=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(info)[:700]))
    fails += 0 if ok else 1

def git(d, *a):
    return subprocess.run(["git", "-C", str(d)] + list(a), env=ENV, capture_output=True, text=True).stdout.strip()

def mkproj(name):
    d = DEV / name
    d.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(d)], env=ENV, check=True)
    (d / "a.txt").write_text("1\n")
    git(d, "add", "-A"); git(d, "commit", "-qm", "init")
    return d

RULES = {"type": "software", "lanes": {"default": "full", "fast_allowed": True, "fast_max_files": 3, "fast_max_lines": 50}, "stages": [], "agents": {}, "skips": {}, "review": {"full": ["correctness"], "always": [], "on_risk": []},
         "level": "strict", "autopilot": "guided", "roles": {}, "risk": [], "deps": [], "ui": [], "trusted": True}

# ---------------------------------------------------------------- L2 id overflow
w = engine.new_work()
w["_max_id"] = engine.ID_MAX
try:
    engine.open_cr(w, "x", "owner", 1000, lane="full", rules=RULES, kind="cli_open")
    r = "opened"
except engine.EngineRefused as e:
    r = e.code if hasattr(e, "code") else str(e)
check("L2 opening a CR past the id cap is an EngineRefused (id_overflow), not a crash or a 7-digit id", "id_overflow" in str(r) or r == "id_overflow", r)
w2 = engine.new_work()
tr = {"ts": 5, "cr": "CR-100000", "op": "import", "stage": None, "by": "import", "sid8": None, "ev": {"kind": "engine", "ref": None, "data": {"title": "t", "lane": "full", "status": "open", "stages": {}}}}
try:
    engine.apply_tr(w2, tr)
    r = "applied"
except ValueError:
    r = "refused"
check("L2 an imported/logged id above the cap is refused by the engine (skipped by replay)", r == "refused" and not w2["crs"], (r, w2["crs"]))
w3 = engine.new_work()
engine.apply_tr(w3, {"ts": 5, "cr": None, "op": "archived", "stage": None, "by": "engine", "sid8": None, "ev": {"kind": "engine", "ref": None, "data": {"max": 10 ** 9, "n": 1, "crs": []}}})
check("L2 an archived line cannot push the counter past the cap", w3["_max_id"] <= engine.ID_MAX, w3["_max_id"])
lines = store._import_lines(json.dumps({"crs": [{"id": "CR-100000", "title": "big", "status": "open"}, {"id": "CR-000123", "title": "ok", "status": "queued"}]}).encode(), 5)
check("L2 store import skips an over-cap id and keeps a normal one", [x["cr"] for x in lines] == ["CR-000123"], lines)

# ---------------------------------------------------------------- M3 report sha in the log
P = mkproj("m3")
sha = hashlib.sha256(b"report body").hexdigest()
def rec(w, **kw):
    cr, t = engine.open_cr(w, "t", "owner", 100, lane="full", rules=RULES, kind="cli_open")
    return cr, t
def tx(fn):
    return store.transact(str(P), fn, base=STATE)
cr = tx(lambda w: ((lambda r: (r[0]["id"], r[1]))(rec(w))))
cid = cr
tx(lambda w: (None, engine.record_report(w, cid, "docs/reports/2026-10-20-%s.md" % cid, {"kind": "report_written", "by": "engine", "ts": 200}, sha=sha)))
c = engine.get_cr(store.load(str(P), STATE), cid)
check("M3 the op:report line carries the content sha and replay restores it", c["report_sha"] == {"docs/reports/2026-10-20-%s.md" % cid: sha}, c.get("report_sha"))
check("M3 the log line is op report with a sha", '"op":"report"' in open(store.log_path(str(P), STATE)).read() and sha in open(store.log_path(str(P), STATE)).read())
try:
    tx(lambda w: (None, engine.record_report(w, cid, "docs/reports/x.md", {"kind": "report_written", "by": "engine", "ts": 201}, sha="nothex")))
    r = "accepted"
except engine.EngineRefused:
    r = "refused"
check("M3 a malformed sha is refused", r == "refused")
check("M3 report_sha is not part of the rendered/public CR", "report_sha" not in json.dumps(engine.render(store.load(str(P), STATE))))

# ---------------------------------------------------------------- L6 automatic compaction
Q = mkproj("l6")
old = 1_000_000_000
wk = engine.new_work()
alltrs = []
for i in range(1100):
    cr, t = engine.open_cr(wk, "old %d" % i, "owner", old + i, lane="full", rules=RULES, kind="cli_open")
    alltrs += t
    alltrs += engine.abandon(wk, cr["id"], {"kind": "owner_override", "by": "owner", "ts": old + i, "data": {"reason": "x"}}, RULES)
store.append(str(Q), alltrs, base=STATE)
lp = store.log_path(str(Q), STATE)
n0 = lp.read_text().count("\n")
check("L6 setup: the log has more than %d lines and nothing compacted it yet" % store.COMPACT_LINES, n0 > store.COMPACT_LINES, n0)
store.transact(str(Q), lambda w: (None, engine.open_cr(w, "fresh", "owner", int(time.time()), lane="full", rules=RULES, kind="cli_open")[1]), base=STATE)
n1 = lp.read_text().count("\n")
wk2 = store.load(str(Q), STATE)
check("L6 the first transaction over the threshold compacts the log by itself (old finished CRs folded, new CR kept)", n1 < 50 and len(wk2["crs"]) == 1 and wk2["crs"][0]["title"] == "fresh", (n1, len(wk2["crs"])))
check("L6 the id counter survives compaction (next id follows the folded ones)", wk2["crs"][0]["id"] == "CR-1101", wk2["crs"][0]["id"])

# ---------------------------------------------------------------- L8 diff base pinned by a ref
R = mkproj("l8")
(R / "a.txt").write_text("2\n")                      # a tracked change: `git stash create` makes a dangling commit
snap = diffstat.snapshot(str(R))
base = snap["base"]
head = git(R, "rev-parse", "HEAD")
check("L8 setup: the base is a dangling stash-create commit (not HEAD)", base != head, (base, head))
store.save_snapshot(str(R), "CR-001", snap, STATE)
check("L8 save_snapshot pins the base under refs/shipmiracle/base/CR-001", git(R, "rev-parse", "refs/shipmiracle/base/CR-001") == base)
git(R, "reflog", "expire", "--expire=now", "--all"); git(R, "gc", "--prune=now", "-q")
check("L8 the base survives git gc --prune=now", subprocess.run(["git", "-C", str(R), "cat-file", "-e", base + "^{commit}"], env=ENV).returncode == 0)
S = mkproj("l8b")
(S / "a.txt").write_text("2\n")
snap2 = diffstat.snapshot(str(S))
git(S, "reflog", "expire", "--expire=now", "--all"); git(S, "gc", "--prune=now", "-q")
gone = subprocess.run(["git", "-C", str(S), "cat-file", "-e", snap2["base"] + "^{commit}"], env=ENV, capture_output=True).returncode != 0
check("L8 control: an unpinned base is pruned by gc", gone)
(S / "b.txt").write_text("x\n" * 5)
d = diffstat.evaluate(str(S), snap2, {})
check("L8 evaluate with a gone base falls back to the empty tree (everything counts, fail closed) instead of raising", d["files"] >= 2, d)
check("L8 pin refuses a bad name or sha", not diffstat.pin(str(R), "../x", base) and not diffstat.pin(str(R), "CR-001", "zz"))
check("L8 unpin removes the ref", diffstat.unpin(str(R), "CR-001") and subprocess.run(["git", "-C", str(R), "rev-parse", "-q", "--verify", "refs/shipmiracle/base/CR-001"], env=ENV, capture_output=True).returncode != 0)

print("\nFAILED: %d" % fails if fails else "\nALL PASS"); sys.exit(1 if fails else 0)
