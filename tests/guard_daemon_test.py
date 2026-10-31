#!/usr/bin/env python3
"""Guard jobs in process (Platform v2 P4b): scheduler table, battery intervals, stuck job, failure backoff, a broken shipm-watch copy,
switch-off parity, scan equivalence, no leaks, grep for shell=True, the bench with a fake ps, the plist template (the owner script is tested in tests/private/guard_daemon_owner_test.py).
Fake clocks and fake probes only; nothing real is started, stopped or changed. Run: python3 tests/guard_daemon_test.py"""
import contextlib, importlib.machinery, importlib.util, io, json, os, pathlib, re, shutil, stat, subprocess, sys, tempfile, threading, time, tracemalloc
os.environ.pop("CLAUDECODE", None)       # the owner check only runs in a fully temp sandbox or outside a chat (H1)

WS = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WS))
T = pathlib.Path(tempfile.mkdtemp()).resolve()
STATE = T / "state"; STATE.mkdir()
CFG = T / "cfg"; CFG.mkdir()
os.environ.update(SHIPMIRACLE_TEST="1", SHIPMIRACLE_STATE=str(STATE), SHIPMIRACLE_CONFIG=str(CFG), SHIPMIRACLE_HOME=str(T / "home"), HOME=str(T / "home"), SHIPMIRACLE_DEV=str(T / "home/Developer"))
os.environ.pop("SHIPMIRACLE_GUARD_FAKE", None)
fails = []
def check(n, c, info=""):
    print(("PASS " if c else "FAIL ") + n, "" if c else info)
    if not c: fails.append(n)

from shipmiracle.guard import jobs as J
from shipmiracle import config as shipmiracle_config

def load_guard():
    spec = importlib.util.spec_from_loader("g_daemon", importlib.machinery.SourceFileLoader("g_daemon", str(WS / "bin/shipm-guard")))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

def settle(r, timeout=10):
    ok = r.join_all(timeout); r.tick(r.clock()); return ok

class Clock:
    def __init__(self, t=1_000_000.0): self.t = t
    def __call__(self): return self.t

def mk(name, fn=None, interval=60, low=300, **kw):
    return J.Job(name, fn or (lambda: None), interval, low, **kw)

# ---------- 1. schedule table (spec section 5) ----------
tbl = {j.name: j for j in J.default_jobs(WS)}
check("table: scan 60/300, nudge 600/600, ci 600/1200 (VS Code only), ledger 600/1200, report_summaries 300/never on low battery (P5c)",
      [(n, j.interval, j.low_interval, j.needs_vscode) for n, j in tbl.items()] ==
      [("scan", 60, 300, False), ("nudge", 600, 600, False), ("ci", 600, 1200, True), ("ledger", 600, 1200, False), ("report_summaries", 300, 10 ** 12, False)], str([(n, j.interval, j.low_interval) for n, j in tbl.items()]))
check("tier cache is 60 s", J.TIER_TTL == 60)

# ---------- 2. due() is pure, battery aware ----------
a, b, c = mk("a", interval=60, low=300), mk("b", interval=600, low=1200, needs_vscode=True), mk("c", interval=600, low=600)
jl = [a, b, c]; ac = {"on_ac": True, "battery_pct": 100, "vscode": True}
snap = [(j.last_run, j.failures, j.backoff_until, j.thread) for j in jl]
check("due: all three at time 1000 (never ran)", [j.name for j in J.due(jl, 1000.0, ac)] == ["a", "b", "c"])
check("due: pure (job fields unchanged)", snap == [(j.last_run, j.failures, j.backoff_until, j.thread) for j in jl])
a.last_run = b.last_run = c.last_run = 1000.0
check("due: nothing at +59 s", J.due(jl, 1059.0, ac) == [])
check("due: scan at +60 s on power", [j.name for j in J.due(jl, 1060.0, ac)] == ["a"])
bat = {"on_ac": False, "battery_pct": 19, "vscode": True}
check("battery <20% unplugged: scan not due at +60 s, due at +300 s", J.due(jl, 1060.0, bat) == [] and [j.name for j in J.due(jl, 1300.0, bat)] == ["a"])
check("battery 20% (not below) or plugged in: normal interval", [j.name for j in J.due(jl, 1060.0, {"on_ac": False, "battery_pct": 20})] == ["a"]
      and [j.name for j in J.due(jl, 1060.0, {"on_ac": True, "battery_pct": 5})] == ["a"])
check("battery: ci/ledger style jobs wait 1200 s, nudge stays 600 s", J.due([b], 1600.0, bat) == [] and J.due([b], 2200.0, bat) == [b] and J.due([c], 1600.0, bat) == [c])
check("needs_vscode: ci job not due without VS Code", J.due([b], 5000.0, {"vscode": False}) == [] and J.due([b], 5000.0, {"vscode": True}) == [b])
a.backoff_until = 9999.0
check("backoff: not due until it ends", J.due([a], 2000.0, ac) == [] and J.due([a], 9999.0, ac) == [a])
a.backoff_until = 0.0; a.stuck = True
check("stuck: never due", J.due([a], 2000.0, ac) == []); a.stuck = False
a.gate = lambda: False
check("gate False: not due", J.due([a], 2000.0, ac) == []); a.gate = None

# ---------- 3. runner: one worker, never waits, stuck, backoff ----------
clk = Clock(); st = T / "rstate"
r = J.Runner([mk("a"), mk("b")], clock=clk, state=st, emit=lambda k, d: None)
j1 = r.tick(clk(), ac)
check("runner: one tick starts exactly one job (a)", j1 is not None and j1.name == "a")
r.join_all(); n2 = r.tick(clk(), ac)
check("runner: next tick reaps a, starts b", n2 is not None and n2.name == "b")
r.join_all(); clk.t += 1; r.tick(clk(), ac)
check("runner: finished jobs reaped, no thread left", not any(j.thread for j in r.jobs) and not any(t.name.startswith("shipmiracle-job-") for t in threading.enumerate()))

release = threading.Event(); started = threading.Event()
def blocker():
    started.set(); release.wait(30)
evs = []
clk = Clock()
slow = mk("slow", blocker, interval=60, budget=45); fast = mk("fast", interval=60)
r = J.Runner([slow, fast], clock=clk, state=T / "rstate2", emit=lambda k, d: evs.append((k, d)))
r.tick(clk(), ac); started.wait(5)
t0 = time.time(); clk.t += 10; r.tick(clk(), ac); dt = time.time() - t0
check("runner: tick returns at once while a job runs (never waits)", dt < 0.2 and slow.alive() and not fast.thread, dt)
check("runner: one at a time: the other job does not start while the first runs inside its budget", fast.last_run == 0.0)
clk.t += 50; r.tick(clk(), ac)
check("stuck: past the budget -> event guard_job_stuck, marked, never raises", slow.stuck and [k for k, _ in evs] == ["guard_job_stuck"] and evs[0][1]["job"] == "slow" and evs[0][1]["budget_s"] == 45, str(evs))
r.join_all(0.2); clk.t += 1; r.tick(clk(), ac)
check("stuck: a stuck job does not stop the others (fast started)", fast.last_run > 0 and slow.alive())
clk.t += 600; r.tick(clk(), ac)
check("stuck: not rescheduled while alive; only one guard_job_stuck event", slow.alive() and len([1 for k, _ in evs if k == "guard_job_stuck"]) == 1)
release.set(); r.join_all(); r.tick(clk(), ac)
check("stuck: once it ends the stuck flag is cleared and the job is scheduled normally again", not slow.stuck)
r.join_all()
# the step is not delayed by a stuck job: a guard step with a hung scan thread returns in well under a second (section 5 below)

# failures -> backoff
clk = Clock(); evs = []; st = T / "rstate3"
boom = [0]
def bad():
    boom[0] += 1; raise ImportError("no module named x")
fj = mk("flaky", bad, interval=60)
r = J.Runner([fj], clock=clk, state=st, emit=lambda k, d: evs.append((k, d)))
for i in range(5):
    r.tick(clk(), ac); r.join_all(); clk.t += 61
r.tick(clk(), ac)   # reap #5
check("5 consecutive failures -> backoff 30 min, one event, a line in guard.err", fj.backoff_until == clk.t + 1800 and [k for k, _ in evs] == ["guard_job_backoff"]
      and "flaky failed 5 times" in (st / "guard.err").read_text(), (fj.backoff_until, clk.t, evs))
n = boom[0]; clk.t += 600; r.tick(clk(), ac)
check("backoff: not run during the 30 minutes", boom[0] == n)
clk.t += 1300; r.tick(clk(), ac); r.join_all()
check("backoff over: runs again", boom[0] == n + 1)
for exc in (SyntaxError("bad"), SystemExit(3), KeyboardInterrupt()):
    def raiser(e=exc): raise e
    rr = J.Runner([mk("x", raiser)], clock=Clock(), state=T / "rs4", emit=lambda k, d: None)
    rr.tick(rr.clock(), ac); rr.join_all(); rr.tick(rr.clock())
    check("isolation: %s in a job is a failure, not an exit of the guard" % type(exc).__name__, rr.jobs[0].failures == 1)
ok_j = mk("okj", interval=60); rr = J.Runner([ok_j], clock=Clock(), state=T / "rs5", emit=lambda k, d: None); ok_j.failures = 3
rr.tick(rr.clock(), ac); rr.join_all(); rr.tick(rr.clock())
check("a success resets the failure count", ok_j.failures == 0)

# ---------- tier cache ----------
clk = Clock(); tc = J.TierCache(clock=clk); calls = []
f = lambda: (calls.append(1), len(calls))[1]
v1 = tc.get("therm", f); clk.t += 59; v2 = tc.get("therm", f); clk.t += 2; v3 = tc.get("therm", f)
check("tier cache: reused for 60 s, then asked again", (v1, v2, v3) == (1, 1, 2) and len(calls) == 2)
check("tier cache: names are independent", tc.get("notify", lambda: "x") == "x")

# ---------- 4. library functions, CLI unchanged ----------
def load(path, name):
    return J.load_script(path, name)

# fixture workspace and project for scan equivalence
FW = T / "ws"; (FW / "bin").mkdir(parents=True); (FW / "config").mkdir()
for n in ("shipm-watch", "idea", "ci-status", "shipm-ledger", "shipm-guard"):
    shutil.copy(WS / "bin" / n, FW / "bin" / n)
T0 = 1_800_000_000
HOME = T / "home"; DEV = HOME / "Developer"; DEV.mkdir(parents=True)
GE = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
pd = DEV / "p1"; subprocess.run(["git", "init", "-q", "-b", "main", str(pd)], env=GE); (pd / "a.txt").write_text("x\n")
subprocess.run(["git", "-C", str(pd), "add", "-A"], env=GE); subprocess.run(["git", "-C", str(pd), "commit", "-q", "-m", "i"], env=GE)
# the assistant maps EVERY non-alphanumeric character of the path to "-" (a "_" in macOS /var/folders too), as the watcher does
tdir = HOME / ".claude/projects" / ("-" + re.sub(r"[^A-Za-z0-9]", "-", str(pd)).lstrip("-")); tdir.mkdir(parents=True)
tf = tdir / "s1.jsonl"; tf.write_text("{}\n"); os.utime(tf, (T0 - 1500, T0 - 1500))
(T / "ps.txt").write_text("100 1 05:00:00 0.1 300000 /Users/x/.local/bin/claude --continue --name p1 --remote-control p1\n")
(T / "lsof.json").write_text("{}"); (T / "host.json").write_text(json.dumps({"swap_pct": 10, "free_pct": 60, "load": 1.0, "cores": 8}))
(FW / "config/watch.json").write_text("{}")
shutil.copytree(WS / "shipmiracle", FW / "shipmiracle", ignore=shutil.ignore_patterns("__pycache__"))
WENV = {"SHIPMIRACLE_TEST": "1", "SHIPMIRACLE_HOME": str(HOME), "HOME": str(HOME), "SHIPMIRACLE_DEV": str(DEV), "SHIPMIRACLE_WS": str(FW), "SHIPMIRACLE_NOW": str(T0), "SHIPMIRACLE_PS": str(T / "ps.txt"), "SHIPMIRACLE_LSOF": str(T / "lsof.json"),
        "SHIPMIRACLE_HOST": str(T / "host.json"), "SHIPMIRACLE_KILL_LOG": str(T / "kills.log"), "SHIPMIRACLE_TMP": str(T / "tasks")}
(T / "tasks").mkdir()
S_SUB, S_IN = T / "s_sub", T / "s_in"
for s in (S_SUB, S_IN):
    s.mkdir(); (s / "p1.json").write_text(json.dumps({"project": "p1", "state": "working", "ts": T0 - 60}))
subout = []
for _ in range(2):
    rr_ = subprocess.run([sys.executable, str(FW / "bin/shipm-watch"), "scan"], capture_output=True, text=True, env=dict(os.environ, **WENV, SHIPMIRACLE_STATE=str(S_SUB)))
    subout.append(rr_.stdout.strip())
saved = dict(os.environ)
os.environ.update(WENV); os.environ["SHIPMIRACLE_STATE"] = str(S_IN)
inproc = []
for _ in range(2):
    inproc.append(J.run_script(FW / "bin/shipm-watch", "shipmiracle_watch_job", lambda m: m.scan()))
os.environ.clear(); os.environ.update(saved)
def norm(o, root):
    if isinstance(o, dict): return {k: norm(v, root) for k, v in o.items() if k != "ts"}
    if isinstance(o, list): return [norm(v, root) for v in o]
    if isinstance(o, str): return o.replace(str(root), "<S>")
    return o
hs = json.loads((S_SUB / "health.json").read_text()); hi = json.loads((S_IN / "health.json").read_text())
check("equivalence: fixture has a frozen chat item (so the compare is not empty)", any(i["kind"] == "frozen_chat" for i in hs["items"]), str(hs["items"])[:300])
check("equivalence: in-process scan health.json == subprocess scan health.json (ignoring ts)", norm(hs, S_SUB) == norm(hi, S_IN), (json.dumps(norm(hs, S_SUB))[:300], json.dumps(norm(hi, S_IN))[:300]))
check("equivalence: scan() returns what the CLI printed", subout[1] == json.dumps(inproc[1]) and "red" in inproc[1], (subout, inproc))

buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    J.run_script(FW / "bin/idea", "shipmiracle_idea_job", lambda m: m.nudge([]))
    J.run_script(FW / "bin/ci-status", "shipmiracle_ci_job", lambda m: m.main([]))
check("library: nudge() and ci-status main([]) print nothing", buf.getvalue() == "", buf.getvalue())
check("library: ci-status main([]) still wrote ci.json", (S_IN.parent / "state/ci.json").exists() or (STATE / "ci.json").exists())
cli = subprocess.run([sys.executable, str(FW / "bin/idea"), "nudge"], capture_output=True, text=True, env=dict(os.environ, **WENV, SHIPMIRACLE_STATE=str(S_SUB)))
check("CLI unchanged: `idea nudge` still prints its line", cli.returncode == 0 and cli.stdout.strip() != "", cli.stdout + cli.stderr)
cli = subprocess.run([sys.executable, str(FW / "bin/ci-status"), "--print"], capture_output=True, text=True, env=dict(os.environ, **WENV, SHIPMIRACLE_STATE=str(S_SUB)))
check("CLI unchanged: `ci-status --print` still prints the JSON", cli.returncode == 0 and cli.stdout.strip().startswith("{"), cli.stdout + cli.stderr)

# ---------- 5. guard integration ----------
g = load_guard()
check("Shipmiracle imported in the guard", g.shipmiracle_config is not None)
g.WS = FW; g.STATE = STATE
calls = {"run": [], "popen": []}
class _P:
    def poll(self): return None
real_run, real_popen = g.subprocess.run, g.subprocess.Popen
g.subprocess.run = lambda cmd, **kw: (calls["run"].append(cmd), subprocess.CompletedProcess(cmd, 0, "", ""))[1]
g.subprocess.Popen = lambda cmd, **kw: (calls["popen"].append(cmd), _P())[1]
J.subprocess.Popen = g.subprocess.Popen
base_threads = {t.name for t in threading.enumerate()}
try:
    # switch OFF (default): exactly the old subprocess spawns, no runner, no thread
    g.DAEMON = True
    G = g.Guard(); t0 = 1_000_000.0
    G.held_projects(t0); G.ci_check(t0, True); G.ledger_check(t0)
    check("switch off: subprocess scan + nudge + ci + ledger as before", [c[1:] for c in calls["run"]] == [[str(FW / "bin/shipm-watch"), "scan"], [str(FW / "bin/idea"), "nudge"]]
          and [c[1:] for c in calls["popen"]] == [[str(FW / "bin/ci-status")], [str(FW / "bin/shipm-ledger"), "--update"]], str(calls))
    check("switch off: no runner, no job thread", g._JOBS["runner"] is None and {t.name for t in threading.enumerate()} == base_threads)
    tcalls = []
    check("switch off: _tier asks every time", [g._tier("x", lambda: tcalls.append(1) or "v") for _ in range(3)] == ["v"] * 3 and len(tcalls) == 3)
    # switch ON but not the daemon (shipm-guard once): still subprocesses
    shipmiracle_config.set("guard.jobs", "true")
    check("config key guard.jobs reads true after set", shipmiracle_config.get("guard.jobs") is True)
    g.DAEMON = False; calls["run"].clear(); calls["popen"].clear()
    G = g.Guard(); G.held_projects(t0)
    check("switch on, but `once` (not the daemon): still the subprocess", len(calls["run"]) == 2 and g._JOBS["runner"] is None)
    # switch ON in the daemon: in-process
    g.DAEMON = True; calls["run"].clear(); calls["popen"].clear(); g._JOBS["tiers"] = None
    tcalls.clear()
    vals = [g._tier("x", lambda: tcalls.append(1) or "v") for _ in range(3)]
    check("switch on: _tier answered from the 60 s cache (probe asked once)", vals == ["v"] * 3 and len(tcalls) == 1)
    G = g.Guard(); G.held_projects(t0)
    r = g._JOBS["runner"]; r.join_all(15)
    check("switch on: held_projects starts the scan in process (no shipm-watch / idea subprocess)", not any("shipm-watch" in " ".join(c) or "/bin/idea" in " ".join(c) for c in calls["run"]) and r is not None and r.jobs[0].last_run == t0, str(calls))
    r.tick(t0 + 1, {}); r.join_all(15)
    G.ledger_check(t0 + 2); G.ci_check(t0 + 3, False)
    check("switch on: ledger is still a subprocess (Popen), ci needs VS Code", [c[1:] for c in calls["popen"]] == [[str(FW / "bin/shipm-ledger"), "--update"]], str(calls["popen"]))
    # --- a SyntaxError in a copy of bin/shipm-watch: the awake decisions stay intact and the loop stays alive ---
    (FW / "bin/shipm-watch").write_text((WS / "bin/shipm-watch").read_text() + "\ndef (:\n")
    stubs = (g.read_system, g.keep_default_model, g.Guard.awake, g.Guard.lowpower, g.FAKE)
    awake_calls = []
    g.keep_default_model = lambda: None
    g.Guard.awake = lambda self, on, actual=None: awake_calls.append(on)
    g.Guard.lowpower = lambda self, *a: None
    g.read_system = lambda: g._JOBS.__setitem__("sys", {"vscode": True, "claude_working": True, "agents": 0, "vscode_busy": False, "lid_closed": False, "idle_s": 0, "poke_age": 999,
                  "on_ac": True, "battery_pct": 100, "thermal_limit": 100, "sleep_disabled": False, "lpm": False, "frozen_since": None}) or g._JOBS["sys"]
    g.FAKE = None
    G = g.Guard()
    outs = []
    t_start = time.time()
    for i in range(6):
        outs.append(G.step())
        sc = g._JOBS["runner"].jobs[0]
        g._JOBS["runner"].join_all(15)
        sc.last_run = 0.0                      # skip the 60 s wait (fake clock substitute)
    dt = time.time() - t_start
    sc = g._JOBS["runner"].jobs[0]
    check("broken shipm-watch copy: every step still decided hold=True and called awake(True)", all(o["hold"] for o in outs) and awake_calls == [True] * 6, (outs[-1], awake_calls))
    check("broken shipm-watch copy: 5 failures -> backoff + guard.err line + event kept, loop alive", sc.backoff_until > 0 and "scan failed 5 times" in (STATE / "guard.err").read_text(), (sc.failures, sc.backoff_until))
    check("broken shipm-watch copy: the steps were not slowed (6 steps incl. 5 loader failures < 5 s)", dt < 5, dt)
    # a hung scan never delays the step
    gate = threading.Event()
    sc.backoff_until = 0.0; sc.last_run = 0.0; sc.fn = lambda: gate.wait(30)
    G.step(); time.sleep(0.05)
    t0 = time.time(); o = G.step(); dt = time.time() - t0
    check("hung scan thread: step() returns promptly and still holds", dt < 1.0 and o["hold"] and sc.alive(), dt)
    gate.set(); g._JOBS["runner"].join_all(15)
    g.read_system, g.keep_default_model, g.Guard.awake, g.Guard.lowpower, g.FAKE = stubs
    # the jobs module missing -> the guard stays on the old path
    g._JOBS.update(mod=None, bad=False, runner=None)
    real_imp = __import__
    def fake_import(name, *a, **k):
        if name == "shipmiracle.guard": raise SyntaxError("broken jobs module")
        return real_imp(name, *a, **k)
    import builtins; builtins.__import__ = fake_import
    try:
        check("a broken shipmiracle.guard.jobs: guard falls back (jobs_enabled False), no exception", g.jobs_enabled() is False and g._JOBS["bad"] is True)
    finally:
        builtins.__import__ = real_imp
finally:
    g.subprocess.run, g.subprocess.Popen = real_run, real_popen
    J.subprocess.Popen = real_popen
    shipmiracle_config.unset("guard.jobs")

# ---------- 6. no leaks ----------
for _ in range(2):
    J.run_script(FW / "bin/idea", "shipmiracle_idea_job", lambda m: None)        # warm up caches / bytecode
(FW / "bin/shipm-watch").write_text((WS / "bin/shipm-watch").read_text())
os.environ.update(WENV); os.environ["SHIPMIRACLE_STATE"] = str(S_IN)
for _ in range(2):
    J.run_script(FW / "bin/shipm-watch", "shipmiracle_watch_job", lambda m: m.scan())
import gc; gc.collect()
mods, plen = len(sys.modules), len(sys.path)
tracemalloc.start(); gc.collect(); m0 = tracemalloc.get_traced_memory()[0]
for _ in range(50):
    J.run_script(FW / "bin/shipm-watch", "shipmiracle_watch_job", lambda m: m.scan())
    J.run_script(FW / "bin/idea", "shipmiracle_idea_job", lambda m: m.nudge([]))
gc.collect(); m1 = tracemalloc.get_traced_memory()[0]; tracemalloc.stop()
os.environ.clear(); os.environ.update(saved)
check("50 reload-and-run cycles: sys.modules and sys.path stable", len(sys.modules) == mods and len(sys.path) == plen, (mods, len(sys.modules), plen, len(sys.path)))
check("50 reload-and-run cycles: traced memory growth < 1 MiB (%d bytes)" % (m1 - m0), m1 - m0 < 1 << 20, m1 - m0)
check("no job thread left", not [t for t in threading.enumerate() if t.name.startswith("shipmiracle-job-")], threading.enumerate())
kids = subprocess.run(["ps", "-axo", "pid=,ppid="], capture_output=True, text=True).stdout.split("\n")
mine = [l for l in kids if l.split()[1:2] == [str(os.getpid())]]
check("no child process left (only the ps itself may exist)", len(mine) <= 1, mine)

# ---------- 7. grep: no shell=True ----------
bad = [str(p.relative_to(WS)) for p in list((WS / "shipmiracle/guard").glob("*.py")) if re.search(r"shell\s*=\s*True|os\.system\(|os\.popen\(", p.read_text())]
check("no shell=True / os.system in shipmiracle/guard", not bad, bad)
check("bin/shipm-guard has no shell=True either", "shell=True" not in (WS / "bin/shipm-guard").read_text())

# ---------- 9. plist template and the owner script ----------
tpl = (WS / "templates/launchd/com.shipmiracle.guard.plist.in").read_text()
check("plist template: KeepAlive, ThrottleInterval 10, RunAtLoad, logs under @STATE@/logs/", "<key>KeepAlive</key><true/>" in tpl and "<key>ThrottleInterval</key><integer>10</integer>" in tpl
      and "<key>RunAtLoad</key><true/>" in tpl and tpl.count("@STATE@/logs/guard.log") == 2 and "@WS@/bin/shipm-guard</string><string>run" in tpl)
lint = subprocess.run(["plutil", "-lint", str(WS / "templates/launchd/com.shipmiracle.guard.plist.in")], capture_output=True, text=True) if shutil.which("plutil") else None
check("plist template is valid XML plist (plutil)", lint is None or lint.returncode == 0, lint and lint.stdout)

# ---------- 10. config default ----------
check("config guard.jobs defaults to false and is a bool switch", shipmiracle_config.get("guard.jobs") is False and "guard.jobs" in shipmiracle_config.SCHEMA)

print("\nFAILED:" if fails else "\nALL PASS", fails)
shutil.rmtree(T, ignore_errors=True)
sys.exit(1 if fails else 0)
