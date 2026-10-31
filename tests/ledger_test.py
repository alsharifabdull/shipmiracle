#!/usr/bin/env python3
"""ledger_test: bin/shipm-ledger on synthetic transcripts in a temp tree. Run: python3 tests/ledger_test.py"""
import importlib.machinery, importlib.util, json, os, stat, subprocess, sys, tempfile, time
WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(WS, "bin", "shipm-ledger")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import shipmiracle_timing as T
spec = importlib.util.spec_from_loader("ledger", importlib.machinery.SourceFileLoader("ledger", TOOL))
L = importlib.util.module_from_spec(spec); spec.loader.exec_module(L)
fails = []
def check(n, c, info=""):
    print(("PASS " if c else "FAIL ") + n + ("" if c else " " + str(info)))
    if not c: fails.append(n)

tmp = tempfile.mkdtemp()
proj, state = os.path.join(tmp, "projects"), os.path.join(tmp, "state")
NOW = time.time()
def iso(t): return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t)) + ".000Z"
def line(mid, t, fresh=10, cw=0, cr=0, out=5, model="claude-x", sid="s1", cwd=os.path.join(L.HOME, "Developer", "alpha")):
    return json.dumps({"type": "assistant", "timestamp": iso(t), "sessionId": sid, "cwd": cwd,
                       "message": {"id": mid, "role": "assistant", "model": model,
                                   "usage": {"input_tokens": fresh, "cache_creation_input_tokens": cw, "cache_read_input_tokens": cr, "output_tokens": out}}}) + "\n"
def put(rel, text, mode="a"):
    p = os.path.join(proj, rel); os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, mode) as f: f.write(text)
    return p
def rows():
    out = []
    try:
        for x in open(os.path.join(state, "ledger.jsonl")):
            try: out.append(json.loads(x))
            except ValueError: pass
    except OSError: pass
    return out
def summ(): return json.load(open(os.path.join(state, "ledger.summary.json")))
def upd(now=None): return L.update(state, proj, now or time.time())

# --- first run
put("-Users-x-Developer-alpha/s1.jsonl",
    line("m1", NOW - 100, fresh=5, cw=1000, cr=9000, out=50) +
    line("m2", NOW - 90, fresh=5, cw=10, cr=250000, out=20) +          # over 200k
    "this is not json\n" + '{"message": {"usage": 3}}\n' + '{"half": "usage"\n' +
    line("m3", NOW - 80, fresh=1, cw=0, cr=0, out=7) +                 # zero ctx: ignored? (fresh=1 -> ctx 1, kept)
    '{"type":"user","message":{"role":"user","content":"hi"}}\n')
put("-Users-x-Developer-alpha/s1/subagents/agent-a1.jsonl", line("sub1", NOW - 70, fresh=3, cw=0, cr=3000, out=11, sid="s1"))
put("-Users-x-Developer-alpha/s1/subagents/agent-a1.meta.json", json.dumps({"agentType": "backend-engineer"}), "w")
r = upd()
R = {x["id"]: x for x in rows()}
check("first run appends one row per valid call, skipping corrupt and non-usage lines", sorted(R) == ["m1", "m2", "m3", "sub1"] and r["rows"] == 4, sorted(R))
m1 = R["m1"]
check("row fields", all(k in m1 for k in ("ts", "project", "session", "agent_type", "model", "ctx_tokens", "cache_read", "cache_write", "fresh", "output", "kind")), m1)
check("ctx_tokens = fresh + cache_write + cache_read; parts kept", m1["ctx_tokens"] == 10005 and m1["cache_read"] == 9000 and m1["cache_write"] == 1000 and m1["fresh"] == 5 and m1["output"] == 50)
check("project from cwd, session from the line, main chat", m1["project"] == "alpha" and m1["session"] == "s1" and m1["kind"] == "main" and m1["agent_type"] == "main")
check("subagent row: sub kind and role from meta.json", R["sub1"]["kind"] == "sub" and R["sub1"]["agent_type"] == "backend-engineer")
check("worktree cwd maps to its project", L.project_of(L.HOME + "/Developer/.worktrees/Foo/branch-x", "d") == "Foo" and L.project_of(L.HOME + "/sample-app/a", "d") == "sample-app" and L.project_of(None, L.shipmiracle_paths.claude_dirname(L.HOME) + "-Developer-Bar") == "Bar")

_h = L.HOME
try:
    L.HOME = "/Users/some.other-user"           # another account: no literal user name in the tool
    check("other account: dirname fallback strips that account's home, not a fixed user", L.project_of(None, "-Users-some-other-user-Developer-Bar") == "Bar" and L.project_of(None, "-Users-some-other-user-sample-app") == "~sample-app" and L.project_of("/Users/some.other-user/Developer/.worktrees/Foo/x", "d") == "Foo")
    check("other account: the first account's folder name is not special", L.project_of(None, "-Users-octo-user-Developer-Bar") == "-Users-octo-user-Developer-Bar")
finally:
    L.HOME = _h
check("the tool has no literal user name", ("al" + "sharifabdull") not in open(TOOL).read())

# --- files: modes, atomic, nothing outside state
modes = {f: stat.S_IMODE(os.stat(os.path.join(state, f)).st_mode) for f in os.listdir(state)}
check("state files are 0600", all(m == 0o600 for m in modes.values()), modes)
check("state dir is 0700 and holds no temp files", stat.S_IMODE(os.stat(state).st_mode) == 0o700 and not [f for f in os.listdir(state) if ".tmp." in f], os.listdir(state))

# --- summary numbers
s = summ()
check("summary today: tokens include cache reads", s["today"]["calls"] == 4 and s["today"]["cache_read"] == 262000 and s["today"]["tokens"] == (10005 + 250015 + 1 + 3003) + (50 + 20 + 7 + 11), s["today"])
check("share of calls over 200k", s["today"]["calls_over_200k"] == 1 and s["today"]["share_calls_over_200k_pct"] == 25.0, s["today"])
check("share of tokens over 200k", abs(s["today"]["share_tokens_over_200k_pct"] - 100.0 * (250015 + 20) / s["today"]["tokens"]) < 0.1, s["today"])
check("per-role tokens and avg main context", s["by_role"]["backend-engineer"]["calls"] == 1 and s["by_role"]["main"]["calls"] == 3 and s["avg_main_context_by_project"]["alpha"] == round((10005 + 250015 + 1) / 3), s)
check("by_project tokens (today and week) for the card foot", s["by_project"]["alpha"]["today"] == s["today"]["tokens"] and "today" in s["by_project"]["alpha"], s.get("by_project"))
check("generated_at set and week >= today", abs(s["generated_at"] - time.time()) < 5 and s["week"]["calls"] >= s["today"]["calls"])

# --- incremental: a repeat run reads only new bytes
before = rows()
r = upd(); check("repeat run appends nothing", r["rows"] == 0 and len(rows()) == len(before))
p1 = os.path.join(proj, "-Users-x-Developer-alpha/s1.jsonl")
offs = json.load(open(os.path.join(state, "ledger.offsets.json")))["files"][p1][0]
check("offset cache points at the end of the file", offs == os.path.getsize(p1), offs)
put("-Users-x-Developer-alpha/s1.jsonl", line("m4", NOW - 10, fresh=1, cr=99, out=3))
r = upd(); check("appended call is the only new row", r["rows"] == 1 and rows()[-1]["id"] == "m4")
# partial last line is not consumed until complete
p = put("-Users-x-Developer-alpha/s1.jsonl", line("m5", NOW - 5, fresh=1, cr=1, out=3)[:-30])
r = upd(); check("an incomplete last line waits", r["rows"] == 0)
put("-Users-x-Developer-alpha/s1.jsonl", line("m5", NOW - 5, fresh=1, cr=1, out=3)[-30:])
r = upd(); check("...and is read once complete", r["rows"] == 1 and rows()[-1]["id"] == "m5", rows()[-1])

# --- de-dup: streaming copies keep the one with the most output
put("-Users-x-Developer-alpha/s2.jsonl", line("d1", NOW - 60, fresh=1, cr=500, out=2, sid="s2") + line("d1", NOW - 59, fresh=1, cr=500, out=40, sid="s2") + line("d1", NOW - 58, fresh=1, cr=500, out=10, sid="s2"))
put("-Users-x-Developer-beta/s3.jsonl", line("d1", NOW - 57, fresh=1, cr=500, out=40, sid="s3"))   # same id in another file (resumed session)
upd()
d1 = [x for x in rows() if x["id"] == "d1"]
check("ledger appends only a better copy (2 rows: out 2 then 40)", [x["output"] for x in d1] == [2, 40], d1)
s = summ()
check("summary counts the message once, with 40 output tokens", s["today"]["calls"] == 7, s["today"])  # m1 m2 m3 sub1 + m4 m5 + d1
check("summary de-duplicated d1 (keeps most output)", [x for x in L.read_rows(state, 0) if x["id"] == "d1"][0]["output"] == 40)
# lost offset cache: re-read everything, summary unchanged
n_before = s["today"]["calls"]
os.unlink(os.path.join(state, "ledger.offsets.json")); upd()
check("deleting the offset cache duplicates rows but not the numbers", summ()["today"]["calls"] == n_before and summ()["today"]["tokens"] == s["today"]["tokens"])
open(os.path.join(state, "ledger.offsets.json"), "w").write("{corrupt"); upd()
check("corrupt offset cache is tolerated", summ()["today"]["calls"] == n_before)

# --- corrupt ledger lines tolerated
with open(os.path.join(state, "ledger.jsonl"), "a") as f: f.write("garbage\n{\"ts\": 1}\n")
check("corrupt ledger lines skipped", L.compute(L.read_rows(state, NOW - 7 * 86400), NOW)["today"]["calls"] == n_before)

# --- context resets
put("-Users-x-Developer-alpha/s9.jsonl", line("r1", NOW - 50, fresh=1, cr=300000, sid="s9") + line("r2", NOW - 40, fresh=1, cr=310000, sid="s9") + line("r3", NOW - 30, fresh=1, cr=20000, sid="s9"))
put("-Users-x-Developer-alpha/s8.jsonl", line("q1", NOW - 50, fresh=1, cr=30000, sid="s8") + line("q2", NOW - 40, fresh=1, cr=28000, sid="s8") + line("q3", NOW - 30, fresh=1, cr=100, sid="s8") )
put("-Users-x-Developer-alpha/s7.jsonl", line("z1", NOW - 50, fresh=1, cr=100000, sid="s7") + line("z2", NOW - 40, fresh=1, cr=60000, sid="s7"))
upd(); check("context resets = sessions whose context fell by more than half (s9 yes, s8 yes, s7 no)", summ()["context_resets"]["today"] == 3, summ()["context_resets"])

# --- old transcripts are ignored
old = put("-Users-x-Developer-old/o.jsonl", line("o1", NOW - 20 * 86400, fresh=1, cr=1))
os.utime(old, (NOW - 20 * 86400, NOW - 20 * 86400)); upd()
check("transcripts older than 8 days are not read", "o1" not in {x.get("id") for x in rows()})
put("-Users-x-Developer-alpha/s1.jsonl", line("w1", NOW - 3 * 86400, fresh=1, cr=1000, out=1))
upd(); s = summ()
check("a call 3 days ago is in the week but not in today", s["week"]["calls"] == s["today"]["calls"] + 1, (s["week"]["calls"], s["today"]["calls"]))

# --- rotation
L.ROTATE_BYTES = 1000
upd(); put("-Users-x-Developer-alpha/s1.jsonl", line("rot1", NOW - 2, fresh=1, cr=7, out=1)); upd()
check("ledger rotates when over the cap (ledger.jsonl.1 exists, summary still counts both)", os.path.exists(os.path.join(state, "ledger.jsonl.1")) and "rot1" in {x.get("id") for x in L.read_rows(state, 0)})
check("rotated file is 0600 too", stat.S_IMODE(os.stat(os.path.join(state, "ledger.jsonl.1")).st_mode) == 0o600)
L.ROTATE_BYTES = 20 * 1024 * 1024

# --- lock: a second run while one is active does nothing
import fcntl
lk = open(os.path.join(state, "ledger.lock"), "w"); fcntl.flock(lk, fcntl.LOCK_EX)
check("a run while another is active returns busy and writes nothing", upd() == {"busy": True, "rows": 0})
lk.close()

# --- CLI + warm runtime on a larger tree
env = dict(os.environ, SHIPMIRACLE_STATE=state, SHIPMIRACLE_LEDGER_PROJECTS=proj)
r = subprocess.run([sys.executable, TOOL, "--json"], env=env, capture_output=True, text=True)
check("--json prints the summary", r.returncode == 0 and json.loads(r.stdout)["version"] == 1, r.stderr)
r = subprocess.run([sys.executable, TOOL, "--summary"], env=env, capture_output=True, text=True)
check("--summary says tokens incl. cache reads and share over 200k in words", "incl. cache reads" in r.stdout and "over 200k" in r.stdout, r.stdout)
big = "".join(line("b%d" % i, NOW - 1000 + i * 0.001, fresh=1, cr=1000 + i, out=1, sid="big") for i in range(30000))
for k in range(20): put("-Users-x-Developer-big/big%d.jsonl" % k, big if k == 0 else line("bb%d" % k, NOW - 5, cr=5))
subprocess.run([sys.executable, TOOL, "--update"], env=env, capture_output=True)
# limit 2 s, or 15 x the start-up time of python measured just before (a busy Mac slows both); a full re-read of the files would be about 3 s on a quiet machine
last = {}
def _upd():
    t0 = time.perf_counter(); last["r"] = subprocess.run([sys.executable, TOOL, "--update"], env=env, capture_output=True, text=True); return time.perf_counter() - t0
ok, rep, dt = T.robust(_upd, lambda: T.spawn_ref(10), 2.0, 15)
check("warm run (nothing new, 30k+ rows in the ledger) takes under 2 s: %s" % rep, last["r"].returncode == 0)
check("warm run time within max(2 s, 15 x python start)", ok, rep)
def _upd1():
    n = _upd1.n = getattr(_upd1, "n", 0) + 1
    put("-Users-x-Developer-big/big1.jsonl", line("fresh%d" % n, NOW - 1, cr=9)); return _upd()
ok, rep, dt = T.robust(_upd1, lambda: T.spawn_ref(10), 2.0, 15)
check("warm run with one new row (summary rebuilt) takes under 2 s: %s" % rep, "1 new rows" in last["r"].stdout)
check("one-new-row run time within max(2 s, 15 x python start)", ok, rep)
r = subprocess.run([sys.executable, TOOL, "--update", "--state", os.path.join(tmp, "nope", "deep")], env=dict(env, SHIPMIRACLE_LEDGER_PROJECTS=os.path.join(tmp, "missing")), capture_output=True, text=True)
check("missing projects folder: no crash, empty ledger", r.returncode == 0, r.stderr)

print("\nFAILED:" if fails else "\nALL PASS", fails)
sys.exit(1 if fails else 0)
