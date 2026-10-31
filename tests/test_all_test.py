#!/usr/bin/env python3
"""bin/test-all: exit codes, per-suite counts and TOTAL line, on a temp tests folder (never the real one)."""
import json, os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TA = os.path.join(HERE, "..", "bin", "test-all")
fails = 0
# every nested test-all run guards nothing real unless a case says so (the real home/state are rewritten by live hooks)
os.environ.update(SHIPMIRACLE_TEST="1", SHIPMIRACLE_GUARD_FILES="[]", SHIPMIRACLE_GUARD_EVENTS="[]", SHIPMIRACLE_GUARD_AGENTS="", SHIPMIRACLE_GUARD_STATEJSON="",
                  SHIPMIRACLE_GUARD_CLAUDE_JSON=os.path.join(tempfile.mkdtemp(), "none.json"))


def check(name, ok, extra=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(extra)))
    fails += 0 if ok else 1


def run(d, *args):
    env = dict(os.environ, SHIPMIRACLE_TESTS_DIR=d)
    r = subprocess.run([TA] + list(args), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60)
    return r.returncode, r.stdout.decode()


d = tempfile.mkdtemp()
open(os.path.join(d, "a_test.py"), "w").write("print('PASS one')\nprint('PASS two')\n")
open(os.path.join(d, "b_test.py"), "w").write("print('PASS x')\nprint('FAIL y')\nprint('boom')\nraise SystemExit(1)\n")
open(os.path.join(d, "helper.py"), "w").write("raise SystemExit(9)\n")
code, out = run(d)
check("failing suite gives exit 1", code == 1, out)
check("passing suite counts", "a_test.py: 2 passed, 0 failed" in out, out)
check("failing suite counts", "b_test.py: 1 passed, 1 failed" in out, out)
check("failed suite tail printed", "boom" in out.split("last 5 lines")[-1], out)
check("TOTAL line", "TOTAL: suites 2, passed 3, failed 1" in out, out)
check("non-matching file ignored", "helper.py" not in out, out)
code, out = run(d, "--list")
check("--list prints suites, exit 0", code == 0 and out.split() == ["a_test.py", "b_test.py"], out)

d2 = tempfile.mkdtemp()
open(os.path.join(d2, "a_test.py"), "w").write("print('PASS one')\n")
code, out = run(d2)
check("only passing suite exits 0", code == 0 and "TOTAL: suites 1, passed 1, failed 0" in out, out)

d3 = tempfile.mkdtemp()
open(os.path.join(d3, "c_test.py"), "w").write("raise SystemExit(3)\n")
code, out = run(d3)
check("non-zero exit with no FAIL line counts as 1 failure", code == 1 and "c_test.py: 0 passed, 1 failed (exit 3" in out, out)

# a suite that cannot start because TMPDIR is outside the fixed temp roots is a loud failure with a reason, never a silent "passed 0, failed 0"
import shutil
vt = tempfile.mkdtemp(dir="/var/tmp")        # /var/tmp is not one of the fixed roots (/tmp, /var/folders)
try:
    r = subprocess.run([TA], env=dict(os.environ, SHIPMIRACLE_TESTS_DIR=d2, TMPDIR=vt), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60)
    out = r.stdout.decode()
    check("TMPDIR outside the fixed temp roots: exit 1, 'refusing to run' shown, one failed suite", r.returncode == 1 and "refusing to run" in out and "TOTAL: suites 1, passed 0, failed 1" in out, out)
finally:
    shutil.rmtree(vt, ignore_errors=True)

d4 = tempfile.mkdtemp()
open(os.path.join(d4, "z_test.py"), "w").write("print('PASS one')\nprint('FAILED: 0')\n")
open(os.path.join(d4, "y_test.py"), "w").write("print('PASS one')\nprint('FAILED: []')\n")
code, out = run(d4)
check("summary FAILED: 0 / FAILED: [] is not a failure", code == 0 and "TOTAL: suites 2, passed 2, failed 0" in out, out)
d5 = tempfile.mkdtemp()
open(os.path.join(d5, "w_test.py"), "w").write("print('PASS one')\nprint(\"FAILED: ['x']\")\n")
code, out = run(d5)
check("non-empty FAILED summary is a failure", code == 1 and "w_test.py: 1 passed, 1 failed" in out, out)
d6 = tempfile.mkdtemp()
open(os.path.join(d6, "s_test.py"), "w").write("import time\nprint('PASS one', flush=True)\ntime.sleep(30)\n")
env6 = dict(os.environ, SHIPMIRACLE_TESTS_DIR=d6, SHIPMIRACLE_TEST_TIMEOUT="2")
r6 = subprocess.run([TA], env=env6, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60)
o6 = r6.stdout.decode()
check("per-suite timeout (SHIPMIRACLE_TEST_TIMEOUT) counts as failure", r6.returncode == 1 and "s_test.py: 1 passed, 1 failed (exit timeout" in o6, o6)

# SKIP accounting and NOT TESTED (review m8)
d8 = tempfile.mkdtemp()
open(os.path.join(d8, "a_test.py"), "w").write("print('PASS one')\nprint('SKIP the live tree is not here')\nprint('SKIP second reason')\n")
open(os.path.join(d8, "n_test.py"), "w").write("print('SKIP-ALL nothing to run on this machine')\n")
code, out = run(d8)
check("SKIP lines are printed under the suite and counted", "a_test.py: 1 passed, 0 failed, 2 skipped" in out and "    SKIP the live tree is not here" in out and "skipped 3" in out, out)
check("0 checks with a SKIP line: NOT TESTED (not PASS), explained, not a failure", "n_test.py: NOT TESTED, 0 checks ran (1 skipped)" in out and code == 0 and "NOT TESTED 1 (n_test.py)" in out and "n_test.py: 0 passed" not in out, out)
d9 = tempfile.mkdtemp()
open(os.path.join(d9, "a_test.py"), "w").write("print('PASS one')\n")
open(os.path.join(d9, "z_test.py"), "w").write("print('all fine, no check lines')\n")
code, out = run(d9)
check("0 checks and no word why: NOT TESTED and a failure (a silent zero is never green)", code == 1 and "z_test.py: NOT TESTED, 0 checks ran and nothing said why" in out and "failed 1" in out and "NOT TESTED 1 (z_test.py)" in out, out)

# guard: a suite that changes a guarded real file
gd = tempfile.mkdtemp(); guarded = os.path.join(gd, "flow.json"); open(guarded, "w").write("{}")
ev = os.path.join(gd, "flow-events.jsonl"); open(ev, "w").write('{"event": "x"}\n')
dev = os.path.join(gd, "dev"); os.makedirs(os.path.join(dev, "realproj"))
d7 = tempfile.mkdtemp()
open(os.path.join(d7, "a_test.py"), "w").write("print('PASS one')\n")
open(os.path.join(d7, "b_test.py"), "w").write("open(%r, 'w').write('{\"b\": 1}')\nprint('PASS two')\n" % guarded)
open(os.path.join(d7, "c_test.py"), "w").write("print('PASS three')\n")
genv = dict(os.environ, SHIPMIRACLE_TESTS_DIR=d7, SHIPMIRACLE_TEST="1", SHIPMIRACLE_GUARD_FILES=json.dumps([guarded]), SHIPMIRACLE_GUARD_EVENTS=json.dumps([ev]), SHIPMIRACLE_GUARD_DEVDIR=dev, SHIPMIRACLE_GUARD_AGENTS="", SHIPMIRACLE_GUARD_STATEJSON="")
r7 = subprocess.run([TA, "--jobs", "1"], env=genv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60)
o7 = r7.stdout.decode()
check("guard (serial): changed real file fails test-all and names the suite", r7.returncode == 1 and "FAIL test-all: a test changed a real file" in o7 and "after suite: b_test.py" in o7, o7)
open(guarded, "w").write("{}")
genv["SHIPMIRACLE_TESTS_DIR"] = d2
r8 = subprocess.run([TA], env=genv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60)
check("guard: clean run unchanged", r8.returncode == 0 and "FAIL test-all" not in r8.stdout.decode() and "TOTAL: suites 1, passed 1, failed 0" in r8.stdout.decode(), r8.stdout.decode())
# a live-style write to an agents file (rewritten by live hooks) must NOT fail the run
agf = os.path.join(gd, "x.agents.json"); open(agf, "w").write("{}")
dd = tempfile.mkdtemp()
open(os.path.join(dd, "g_test.py"), "w").write("open(%r, 'w').write('{\"a\": 1}')\nprint('PASS g')\n" % agf)
rg = subprocess.run([TA], env=dict(genv, SHIPMIRACLE_TESTS_DIR=dd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60)
check("guard: write to an agents file is not guarded", rg.returncode == 0, rg.stdout.decode())
# event files: ordinary growth ignored, test-style level_changed for an unknown project flagged, real project ignored
def run_ev(line):
    dd = tempfile.mkdtemp()
    open(os.path.join(dd, "e_test.py"), "w").write("open(%r, 'a').write(%r + '\\n')\nprint('PASS e')\n" % (ev, line))
    e = dict(genv, SHIPMIRACLE_TESTS_DIR=dd)
    r = subprocess.run([TA], env=e, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60)
    return r.returncode, r.stdout.decode()
c1, o1 = run_ev('{"event": "bypass", "session": "s"}')
check("guard: ordinary new event lines are ignored", c1 == 0, o1)
c2, o2 = run_ev('{"event": "level_changed", "by": "owner-panel", "project": "b"}')
check("guard: level_changed for a test-only project is flagged", c2 == 1 and "e_test.py" in o2 and "real file" in o2, o2)
c3, o3 = run_ev('{"event": "level_changed", "by": "owner-panel", "project": "realproj"}')
check("guard: level_changed for a real project folder is ignored", c3 == 0, o3)
# ---- parallel runner, --only / --list / --fast
import re as _re
def total(out):
    m = _re.findall(r"^TOTAL: .*$", out, _re.M)
    return m[-1] if len(m) == 1 else None
def blocks(out):
    return sorted(_re.sub(r", [0-9.]+s\)", ")", l) for l in out.splitlines() if _re.match(r"\S+_test\.(py|js): ", l))

pd = tempfile.mkdtemp()
for i in range(8):
    open(os.path.join(pd, "s%d_test.py" % i), "w").write("import time\ntime.sleep(0.2)\nprint('PASS a%d')\nprint('PASS b%d')\n" % (i, i))
open(os.path.join(pd, "bad_test.py"), "w").write("print('PASS x')\nprint('FAIL y')\nraise SystemExit(1)\n")
cs, os_ = run(pd, "--jobs", "1")
cp, op = run(pd, "--jobs", "4")
check("parallel result equals serial result (exit, per-suite lines, TOTAL)", cs == cp == 1 and blocks(os_) == blocks(op) and total(os_) == total(op) == "TOTAL: suites 9, passed 17, failed 1", (os_, op))
check("parallel: exactly one TOTAL line, last of the counted output", total(op) is not None and "last 5 lines" in op, op)
check("parallel: failing suite tail printed", "--- bad_test.py: last 5 lines ---" in op, op)
envj = dict(os.environ, SHIPMIRACLE_TESTS_DIR=pd, SHIPMIRACLE_TEST_JOBS="3")
rj = subprocess.run([TA], env=envj, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60)
check("SHIPMIRACLE_TEST_JOBS env is honoured and gives the same TOTAL", total(rj.stdout.decode()) == total(os_), rj.stdout.decode())
cb, ob = run(pd, "--jobs", "0")
check("--jobs 0 is refused (exit 2)", cb == 2 and "usage:" in ob, ob)
cb, ob = run(pd, "--bogus")
check("unknown option is refused (exit 2)", cb == 2 and "unknown option" in ob, ob)

# real parallelism: 4 suites of 1.5 s finish well under 4 x 1.5 s with --jobs 4
sd = tempfile.mkdtemp()
for i in range(4):
    open(os.path.join(sd, "p%d_test.py" % i), "w").write("import time\ntime.sleep(1.5)\nprint('PASS p')\n")
t0 = __import__("time").time(); run(sd, "--jobs", "4"); tp_ = __import__("time").time() - t0
t0 = __import__("time").time(); run(sd, "--jobs", "1"); ts_ = __import__("time").time() - t0
check("--jobs 4 is faster than --jobs 1 (%.1fs vs %.1fs)" % (tp_, ts_), tp_ < ts_ - 2.0, (tp_, ts_))

# a hung suite times out in parallel mode and the others still report
hd = tempfile.mkdtemp()
open(os.path.join(hd, "h_test.py"), "w").write("import time\nprint('PASS one', flush=True)\ntime.sleep(60)\n")
open(os.path.join(hd, "k_test.py"), "w").write("print('PASS k')\n")
rh = subprocess.run([TA, "--jobs", "2"], env=dict(os.environ, SHIPMIRACLE_TESTS_DIR=hd, SHIPMIRACLE_TEST_TIMEOUT="2"), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30)
oh = rh.stdout.decode()
check("parallel: hung suite times out (failure), other suite passes", rh.returncode == 1 and "h_test.py: 1 passed, 1 failed (exit timeout" in oh and "k_test.py: 1 passed, 0 failed" in oh and "TOTAL: suites 2, passed 2, failed 1" in oh, oh)

# a failing suite fails a parallel run even when all others pass
fd = tempfile.mkdtemp()
for i in range(5):
    open(os.path.join(fd, "ok%d_test.py" % i), "w").write("print('PASS ok')\n")
open(os.path.join(fd, "zz_test.py"), "w").write("raise SystemExit(4)\n")
cf, of_ = run(fd, "--jobs", "4")
check("parallel: one failing suite -> exit 1 and failed 1", cf == 1 and "TOTAL: suites 6, passed 5, failed 1" in of_, of_)

# guard still fires in parallel mode (attribution is best effort, the failure is not)
open(guarded, "w").write("{}")
for j in ("2", "4"):
    open(guarded, "w").write("{}")
    rp = subprocess.run([TA, "--jobs", j], env=dict(genv, SHIPMIRACLE_TESTS_DIR=d7), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60)
    op_ = rp.stdout.decode()
    check("guard (--jobs %s): changed real file still fails test-all" % j, rp.returncode == 1 and "FAIL test-all: a test changed a real file" in op_ and "TOTAL: suites 3, passed 3, failed 1" in op_, op_)
open(guarded, "w").write("{}")

# --only / --list / --fast
co, oo = run(d, "--list", "--only", "b_")
check("--list --only filters the suites", co == 0 and oo.split() == ["b_test.py"], oo)
co, oo = run(pd, "--only", "s1")
check("--only runs just the matching suites and is labelled partial", co == 0 and "TOTAL: suites 1, passed 2, failed 0" in oo and "PARTIAL RUN" in oo, oo)
co, oo = run(pd)
check("a full run is not labelled partial", "PARTIAL RUN" not in oo, oo)
ld = tempfile.mkdtemp()
for n in ("flow_gate_scenarios_test.py", "flow_gate_indexerror_test.py", "quick_test.py"):
    open(os.path.join(ld, n), "w").write("print('PASS %s')\n" % n[:4])
co, oo = run(ld, "--fast")
check("--fast skips the two slowest suites and says so", co == 0 and "PARTIAL RUN (--fast skips " in oo and "flow_gate_scenarios_test.py" in oo.split("\n")[0] and "TOTAL: suites 1, passed 1, failed 0" in oo and "\nquick_test.py: 1 passed" in oo and "\nflow_gate_scenarios_test.py: " not in oo, oo)
co, oo = run(ld, "--fast", "--list")
check("--fast --list shows only the suites that would run", oo.split() == ["quick_test.py"], oo)
co, oo = run(ld)
check("without --fast all three suites run", "TOTAL: suites 3, passed 3, failed 0" in oo and "PARTIAL RUN" not in oo, oo)

# --python-only (bin/test-linux container has no node): node suites are left out and the run is labelled partial
pj = tempfile.mkdtemp()
open(os.path.join(pj, "p_test.py"), "w").write("print('PASS p')\n")
open(os.path.join(pj, "j_test.js"), "w").write("console.log('PASS j')\n")
co, oo = run(pj, "--python-only", "--list")
check("--python-only --list shows only the python suites", oo.split() == ["p_test.py"], oo)
co, oo = run(pj, "--python-only")
check("--python-only runs only python suites and says how many node suites it skipped", co == 0 and "PARTIAL RUN (--python-only skips 1 node suite(s))" in oo and "TOTAL: suites 1, passed 1, failed 0" in oo, oo)

# chrome-style suites never overlap (shared lock group)
kd = tempfile.mkdtemp(); lockf = os.path.join(kd, "busy")
body = "# remote-debugging-port\nimport os, time, sys\nif os.path.exists(%r): print('FAIL overlap'); sys.exit(1)\nopen(%r, 'w').close(); time.sleep(0.6); os.remove(%r)\nprint('PASS alone')\n" % (lockf, lockf, lockf)
for n in ("c1", "c2", "c3"):
    open(os.path.join(kd, n + "_test.py"), "w").write(body)
ck, ok_ = run(kd, "--jobs", "3")
check("suites using headless Chrome never run at the same time", ck == 0 and "TOTAL: suites 3, passed 3, failed 0" in ok_, ok_)
# ---- SIGTERM / SIGINT: running suites are killed, guard still reported
import signal as _sig, time as _time
for sgn, code_ in ((_sig.SIGTERM, 143), (_sig.SIGINT, 130)):
    sd_ = tempfile.mkdtemp(); pidf = os.path.join(sd_, "pid"); gf = os.path.join(sd_, "flow.json"); open(gf, "w").write("{}")
    td = tempfile.mkdtemp()
    open(os.path.join(td, "a_test.py"), "w").write("open(%r, 'w').write('{\"x\": 1}')\nprint('PASS a')\n" % gf)
    open(os.path.join(td, "z_test.py"), "w").write("import os, time\nopen(%r, 'w').write(str(os.getpid()))\nprint('PASS z', flush=True)\ntime.sleep(120)\n" % pidf)
    sev = dict(os.environ, SHIPMIRACLE_TESTS_DIR=td, SHIPMIRACLE_TEST="1", SHIPMIRACLE_GUARD_FILES=json.dumps([gf]), SHIPMIRACLE_GUARD_EVENTS=json.dumps([]), SHIPMIRACLE_GUARD_AGENTS="", SHIPMIRACLE_GUARD_STATEJSON="")
    pr_ = subprocess.Popen([TA, "--jobs", "2"], env=sev, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    for _ in range(100):
        if os.path.exists(pidf) and open(pidf).read().strip(): break
        _time.sleep(0.1)
    _time.sleep(0.5)
    spid = int(open(pidf).read())
    pr_.send_signal(sgn)
    try:
        out_, _ = pr_.communicate(timeout=20)
    except subprocess.TimeoutExpired:
        pr_.kill(); out_, _ = pr_.communicate()
    out_ = out_.decode()
    gone = False
    for _ in range(30):
        try: os.kill(spid, 0)
        except OSError: gone = True; break
        _time.sleep(0.1)
    check("signal %d: test-all exits %d and the running suite process is gone" % (sgn, code_), pr_.returncode == code_ and gone, (pr_.returncode, gone, out_))
    check("signal %d: INTERRUPTED shown, guard result and TOTAL still reported" % sgn, "INTERRUPTED by signal" in out_ and "a test changed a real file" in out_ and "TOTAL: suites 2" in out_, out_)
    if not gone:
        try: os.kill(spid, 9)
        except OSError: pass

# ---- guard coverage: every guarded thing, one fake suite each
gdir = tempfile.mkdtemp()
G = {n: os.path.join(gdir, n) for n in ("flow.json", "watch.json", "gate-deny.off", "claude.json")}
for n, pth in G.items(): open(pth, "w").write('{"mcpServers": {}, "projects": {}}' if n == "claude.json" else "{}")
agd = os.path.join(gdir, "agents"); os.makedirs(agd); open(os.path.join(agd, "a.md"), "w").write("a")
std = os.path.join(gdir, "state"); os.makedirs(std); open(os.path.join(std, "proj.json"), "w").write("{}")
for n in ("x.agents.json", "ledger-1.json", "ledger.json.1", "health.json", "scorecard.json", "snapshot-3.json", "flow.abc.json", "x.mode.json", "x.limit.json", "context.k.json", "s.lock", "model-reset.json"):
    open(os.path.join(std, n), "w").write("{}")
gev = dict(os.environ, SHIPMIRACLE_TEST="1", SHIPMIRACLE_GUARD_FILES=json.dumps([G[n] for n in ("flow.json", "watch.json", "gate-deny.off")]), SHIPMIRACLE_GUARD_CLAUDE_JSON=G["claude.json"],
           SHIPMIRACLE_GUARD_AGENTS=agd, SHIPMIRACLE_GUARD_STATEJSON=std, SHIPMIRACLE_GUARD_EVENTS=json.dumps([]), SHIPMIRACLE_GUARD_SHIPMIRACLECONFIG=os.path.join(gdir, "shipmiraclecfg"))
os.makedirs(os.path.join(gdir, "shipmiraclecfg")); os.makedirs(os.path.join(std, "v1", "logs"))
def guard_case(label, code, expect_fail=True):
    dd = tempfile.mkdtemp()
    open(os.path.join(dd, "t_test.py"), "w").write(code + "\nprint('PASS t')\n")
    r = subprocess.run([TA, "--jobs", "2"], env=dict(gev, SHIPMIRACLE_TESTS_DIR=dd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60)
    o = r.stdout.decode()
    ok = (r.returncode == 1 and "a test changed a real file" in o) if expect_fail else (r.returncode == 0 and "FAIL test-all" not in o)
    check("guard: " + label, ok, o)
for n in ("flow.json", "watch.json", "gate-deny.off"):
    guard_case("a suite changing the real workspace %s is caught" % n, "open(%r, 'a').write(' ')" % G[n])
guard_case("a suite adding an MCP server to ~/.claude.json is caught", "open(%r, 'w').write('{\"mcpServers\": {\"x\": {}}, \"projects\": {}}')" % G["claude.json"])
guard_case("a suite granting project trust in ~/.claude.json is caught", "open(%r, 'w').write('{\"mcpServers\": {}, \"projects\": {\"/p\": {\"hasTrustDialogAccepted\": true}}}')" % G["claude.json"])
guard_case("a suite adding a file to ~/.claude/agents is caught", "open(%r, 'w').write('x')" % os.path.join(agd, "new.md"))
guard_case("a suite editing a file in ~/.claude/agents is caught", "open(%r, 'a').write('x')" % os.path.join(agd, "a.md"))
guard_case("a suite deleting a file in ~/.claude/agents is caught", "import os; os.rename(%r, %r)" % (os.path.join(agd, "a.md"), os.path.join(gdir, "a.md.moved")))
os.rename(os.path.join(gdir, "a.md.moved"), os.path.join(agd, "a.md")); os.remove(os.path.join(agd, "new.md"))
guard_case("a suite changing a state *.json (size) is caught", "open(%r, 'a').write(' ')" % os.path.join(std, "proj.json"))
guard_case("a suite creating a new state *.json is caught", "open(%r, 'w').write('{}')" % os.path.join(std, "new.json"))
guard_case("a suite touching a state *.json (mtime only) is caught", "import os; os.utime(%r, (1, 1))" % os.path.join(std, "new.json"))
vol = "; ".join("open(%r, 'a').write(' ')" % os.path.join(std, n) for n in ("x.agents.json", "ledger-1.json", "ledger.json.1", "health.json", "scorecard.json", "snapshot-3.json", "flow.abc.json", "x.mode.json", "x.limit.json", "context.k.json", "s.lock", "model-reset.json"))
guard_case("rewrites of live-rewritten state files (agents/ledger/health/scorecard/snapshot/context/flow.*/mode/limit/lock/model-reset: the live guard daemon writes it when a /model choice is put back, 30 Oct 2026) are NOT guarded", vol, expect_fail=False)
AC = os.path.join(gdir, "shipmiraclecfg")
guard_case("a suite creating the real shipm config.json is caught (absent is a stable value)", "open(%r, 'w').write('{}')" % os.path.join(AC, "config.json"))
os.remove(os.path.join(AC, "config.json"))
guard_case("a suite creating the real shipm registry.json is caught", "open(%r, 'w').write('{}')" % os.path.join(AC, "registry.json"))
open(os.path.join(AC, "config.json"), "w").write("{}")
guard_case("a suite editing an existing shipm config.json is caught", "open(%r, 'a').write(' ')" % os.path.join(AC, "config.json"))
guard_case("churn under <state>/v1 (guard mirrors) is NOT guarded", "open(%r, 'w').write('{}'); open(%r, 'a').write('x')" % (os.path.join(std, "v1", "guard.json"), os.path.join(std, "v1", "logs", "daily-x.log")), expect_fail=False)
open(G["claude.json"], "w").write('{"mcpServers": {}, "projects": {}}')
guard_case("unrelated churn in ~/.claude.json (counters) is NOT guarded", "open(%r, 'w').write('{\"mcpServers\": {}, \"projects\": {}, \"numStartups\": 99}')" % G["claude.json"], expect_fail=False)

# ---- from a git worktree the guard fingerprints the MAIN checkout's config, not only the worktree's
import shutil as _sh
rr = os.path.realpath(tempfile.mkdtemp()); os.makedirs(os.path.join(rr, "bin")); os.makedirs(os.path.join(rr, "tests"))
_sh.copy(TA, os.path.join(rr, "bin", "test-all")); open(os.path.join(rr, "x"), "w").write("x")
gi = ["git", "-C", rr, "-c", "user.email=t@t", "-c", "user.name=t"]
subprocess.run(["git", "init", "-q", "-b", "main", rr], check=True); subprocess.run(gi + ["add", "-A"], check=True); subprocess.run(gi + ["commit", "-qm", "i"], check=True, capture_output=True)
wt = os.path.join(os.path.realpath(tempfile.mkdtemp()), "wt")
subprocess.run(gi + ["worktree", "add", "-q", wt], check=True, capture_output=True)
renv = {k: v for k, v in os.environ.items() if not k.startswith("SHIPMIRACLE_")}
rw = subprocess.run([os.path.join(wt, "bin", "test-all"), "--guard-paths"], env=renv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60).stdout.decode().split("\n")
for n in ("flow.json", "watch.json", "gate-deny.off"):
    check("worktree: guard includes the main checkout's config/%s" % n, os.path.join(rr, "config", n) in rw and os.path.join(wt, "config", n) in rw, rw)
check("worktree: guard includes the real ~/.config/shipmiracle config.json and registry.json", all(any(l.endswith(".config/shipmiracle/" + x) for l in rw) for x in ("config.json", "registry.json")), rw)
check("worktree: guard includes ~/.claude.json, ~/.claude/agents and the settings files", all(any(l.endswith(x) for l in rw) for x in (".claude.json", ".claude/agents/ (listing)", ".claude/settings.json", ".claude/settings.local.json")), rw)
# ---- 21 Oct 2026: per-suite isolation and the real-settings guard (a DECOY stands in for the real home: SHIPMIRACLE_REAL_HOME) ----
import hashlib, json as _j, signal as _sig, time as _t
def iso_run(suites, decoy, sig_after=None):
    td = tempfile.mkdtemp()
    for n, body in suites.items():
        open(os.path.join(td, n), "w").write(body)
    env = {k: v for k, v in os.environ.items() if not k.startswith("SHIPMIRACLE_") and k not in ("CLAUDECODE", "HOME")}
    env.update(SHIPMIRACLE_TEST="1", SHIPMIRACLE_REAL_HOME=decoy, SHIPMIRACLE_HOME=decoy, DECOY_HOME=decoy, SHIPMIRACLE_TESTS_DIR=td, HOME=decoy, SHIPMIRACLE_STATE=tempfile.mkdtemp(), SHIPMIRACLE_CONFIG=tempfile.mkdtemp(), SHIPMIRACLE_TEST_JOBS="1")
    pr = subprocess.Popen([TA, "--jobs", "1"], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    if sig_after:
        _t.sleep(sig_after)
        pr.send_signal(_sig.SIGTERM)
    out, _ = pr.communicate(timeout=120)
    return pr.returncode, out.decode()
def mkdecoy():
    d = os.path.realpath(tempfile.mkdtemp()); os.makedirs(os.path.join(d, ".claude"))
    st = {"model": "x", "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "/opt/foreign/keep.sh"}]}],
          "PreToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": "/opt/other/guard.sh"}]}]}}
    open(os.path.join(d, ".claude", "settings.json"), "w").write(_j.dumps(st, indent=2) + "\n")
    return d, st
POLLUTE = ("import json, os\np = os.path.join(os.environ['DECOY_HOME'], '.claude', 'settings.json')\nd = json.load(open(p))\n"
           "d['hooks'].setdefault('Stop', []).append({'hooks': [{'type': 'command', 'command': '/usr/bin/python3 -I -S -X pycache_prefix=/tmp/zz/pyc /tmp/zzpollute/hooks/shipm-hook Stop'}]})\n"
           "json.dump(d, open(p, 'w'), indent=2)\nprint('PASS polluted')\n")
d, st = mkdecoy()
code, out = iso_run({"a_test.py": "print('PASS fine')\n"}, d)
check("isolation: the real settings file unchanged -> pass, exit 0", code == 0 and "FAIL test-all" not in out and "TOTAL: suites 1, passed 1, failed 0" in out, out)
ENVSUITE = ("import os, tempfile\nh = os.environ['HOME']; print('H=' + h)\nok = (os.environ['SHIPMIRACLE_TEST'] == '1' and os.environ['SHIPMIRACLE_HOME'] == h and os.environ['CLAUDE_CONFIG_DIR'] == h + '/.claude'"
            " and all(os.environ[k].startswith(os.path.dirname(h)) for k in ('SHIPMIRACLE_CONFIG', 'SHIPMIRACLE_STATE', 'SHIPMIRACLE_WS', 'SHIPMIRACLE_DEV'))"
            " and os.environ['AGENT_BROWSER_ARGS'] == '--use-mock-keychain,--password-store=basic' and 'CLAUDECODE' not in os.environ and os.environ.get('SHIPMIRACLE_GUARD_FILES') is None"
            " and 'SHIPMIRACLE_REAL_HOME' not in os.environ and os.path.isdir(h + '/.claude') and os.environ['SHIPMIRACLE_STATE'] != %r)\nprint(('PASS' if ok else 'FAIL') + ' env isolated')\n")
d, st = mkdecoy()
callerstate = tempfile.mkdtemp()
code, out = iso_run({"a_test.py": ENVSUITE % "x", "b_test.py": ENVSUITE % "x"}, d)
homes = [l[2:] for l in out.splitlines() if False]
check("isolation: every suite gets the full fresh set (HOME=SHIPMIRACLE_HOME, CLAUDE_CONFIG_DIR, config/state/ws/dev, browser args), no CLAUDECODE, no caller SHIPMIRACLE_*", code == 0 and "a_test.py: 1 passed, 0 failed" in out and "b_test.py: 1 passed, 0 failed" in out, out)
# L6: foreign single-word hooks named like an Shipmiracle script are kept; the backup sits next to the settings file (0600), never in the real state folder
d, st = mkdecoy()
fg = {"type": "command", "command": "/opt/foreign/hooks/keep-awake.sh"}                                  # missing file, shipmiracle-looking name, not in a temp folder: someone else's
st["hooks"]["Stop"].append({"hooks": [fg]}); open(os.path.join(d, ".claude", "settings.json"), "w").write(_j.dumps(st, indent=2) + "\n")
code, out = iso_run({"z_test.py": POLLUTE}, d)
after = _j.load(open(os.path.join(d, ".claude", "settings.json")))
bk = os.path.join(d, ".claude", ".shipmiracle-repair-backup")
check("L6 guard: the foreign single-word hook /opt/foreign/hooks/keep-awake.sh is NOT removed; the temp Shipmiracle entry is", fg in [h for g in after["hooks"]["Stop"] for h in g["hooks"]] and "zzpollute" not in _j.dumps(after), (out[-500:], after))
check("L6 guard: the backup is .shipmiracle-repair-backup next to the settings file, mode 0600, and holds the polluted file; nothing under the real state folder",
      os.path.isfile(bk) and (os.stat(bk).st_mode & 0o777) == 0o600 and "zzpollute" in open(bk).read() and not os.path.exists(os.path.join(d, ".local")), (os.listdir(os.path.join(d, ".claude")), out[-300:]))
d, st = mkdecoy()
code, out = iso_run({"a_test.py": "import os\nprint('PASS ' + os.environ['HOME'])\nopen(os.environ['HOME'] + '/mark', 'w').write('x')\n", "b_test.py": "import os\nprint('PASS ' + os.environ['HOME'])\nassert not os.path.exists(os.environ['HOME'] + '/mark')\n"}, d)
check("isolation: two suites never share a HOME (a file one writes is not there for the next)", code == 0, out)
d, st = mkdecoy(); before = open(os.path.join(d, ".claude", "settings.json"), "rb").read()
code, out = iso_run({"a_test.py": "print('PASS ok')\n", "z_test.py": POLLUTE}, d)
after = _j.load(open(os.path.join(d, ".claude", "settings.json")))
check("guard: a suite that pollutes the real settings -> loud FAIL naming the file, exit non-zero", code != 0 and "FAIL test-all: a test changed a real file" in out and os.path.join(d, ".claude", "settings.json") in out, out)
check("guard: ...only the Shipmiracle entry with the temp script was removed (a repair, not a restore)", "removed 1 Shipmiracle hook entry" in out and "zzpollute" not in _j.dumps(after), out)
check("guard: ...the foreign hooks and every other key are intact, as before the run", after == st, after)
d, st = mkdecoy()
code, out = iso_run({"z_test.py": POLLUTE.replace("print('PASS polluted')", "import time; print('PASS polluted', flush=True); time.sleep(60)")}, d, sig_after=4)
after = _j.load(open(os.path.join(d, ".claude", "settings.json")))
check("guard: SIGTERM to test-all while a suite pollutes -> suites killed, file cleaned, exit non-zero", code != 0 and "INTERRUPTED" in out and "zzpollute" not in _j.dumps(after) and after == st, (code, out[-400:]))

# ---- 26 Oct 2026: --retry-failed (load flakes) and the settings.json WARN rule ----
fd = tempfile.mkdtemp(); mark = os.path.join(fd, "seen-once")
open(os.path.join(fd, "flaky_test.py"), "w").write("import os\nm = %r\nif not os.path.exists(m):\n    open(m, 'w').write('x')\n    print('PASS a')\n    print('FAIL timing check took 2 s')\n    raise SystemExit(1)\nprint('PASS a')\nprint('PASS b')\n" % mark)
open(os.path.join(fd, "ok_test.py"), "w").write("print('PASS fine')\n")
code, out = run(fd)
check("retry off by default: the flaky suite fails the run", code == 1 and "TOTAL: suites 2, passed 2, failed 1" in out and "FLAKY" not in out, out)
os.remove(mark)
code, out = run(fd, "--retry-failed")
check("--retry-failed: a suite that fails once and passes alone is FLAKY, counted as passed, exit 0, first failure line shown, 'flaky 1' in TOTAL",
      code == 0 and "flaky_test.py: FLAKY (passed alone on retry)" in out and "first failure: FAIL timing check took 2 s" in out and "TOTAL: suites 2, passed 3, failed 0, flaky 1" in out, out)
check("--retry-failed: the FLAKY summary lists the suite", "FLAKY suites (failed once" in out and "flaky_test.py: FAIL timing check" in out, out)
ad = tempfile.mkdtemp()
open(os.path.join(ad, "bad_test.py"), "w").write("print('PASS a')\nprint('FAIL always')\nraise SystemExit(1)\n")
code, out = run(ad, "--retry-failed")
check("--retry-failed: a suite that fails again stays failed (exit 1, no flaky)", code == 1 and "bad_test.py: failed again on retry" in out and "TOTAL: suites 1, passed 1, failed 1" in out and "flaky" not in out.split("TOTAL")[-1], out)
zd = tempfile.mkdtemp()
open(os.path.join(zd, "zero_test.py"), "w").write("raise SystemExit(0)\n")
code, out = run(zd, "--retry-failed")
check("--retry-failed: a suite with zero checks still fails (never a flaky pass)", code == 1 and "FLAKY" not in out, out)
cd_ = tempfile.mkdtemp()
open(os.path.join(cd_, "boot_test.py"), "w").write("print('PASS a')\n")
env_bad = dict(os.environ, SHIPMIRACLE_TESTS_DIR=cd_, TMPDIR="/var/tmp")
r_ = subprocess.run([TA, "--retry-failed", "--jobs", "1"], env=env_bad, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60)
o_ = r_.stdout.decode()
check("--retry-failed: a suite that cannot start is not retried and stays failed", r_.returncode == 1 and "cannot run, not retried" in o_ and "FLAKY" not in o_ and "failed 1" in o_, o_)
# settings.json: another session's unrelated edit is a WARN, a temp path or a Shipmiracle hook entry is a FAIL
UNREL = ("import json, os\np = os.path.join(os.environ['DECOY_HOME'], '.claude', 'settings.json')\nd = json.load(open(p))\nd['model'] = 'changed-by-another-session'\n"
         "json.dump(d, open(p, 'w'), indent=2)\nprint('PASS wrote unrelated key')\n")
d, st = mkdecoy()
code, out = iso_run({"a_test.py": UNREL}, d)
check("settings guard: an unrelated edit of ~/.claude/settings.json is a WARN only (exit 0, no FAIL, file untouched by test-all)", code == 0 and "WARN test-all" in out and "FAIL test-all" not in out and _j.load(open(os.path.join(d, ".claude", "settings.json")))["model"] == "changed-by-another-session", (code, out[-500:]))
TEMPKEY = UNREL.replace("d['model'] = 'changed-by-another-session'", "d['note'] = '/private/tmp/zzsandbox/x'")
d, st = mkdecoy()
code, out = iso_run({"a_test.py": TEMPKEY}, d)
check("settings guard: a change holding a temp-folder path is a FAIL", code != 0 and "FAIL test-all: a test changed a real file" in out, (code, out[-400:]))
SHIPMHOOK = UNREL.replace("d['model'] = 'changed-by-another-session'", "d['hooks'].setdefault('Stop', []).append({'hooks': [{'type': 'command', 'command': '/opt/x/shipm-hook Stop'}]})")
d, st = mkdecoy()
code, out = iso_run({"a_test.py": SHIPMHOOK}, d)
check("settings guard: adding a Shipmiracle hook entry is a FAIL (the polluting-suite case above also still fails)", code != 0 and "FAIL test-all: a test changed a real file" in out, (code, out[-400:]))
REMOVE = UNREL.replace("d['model'] = 'changed-by-another-session'", "d['hooks'].pop('PreToolUse')")
d, st = mkdecoy()
code, out = iso_run({"a_test.py": REMOVE}, d)
check("settings guard: removing a foreign (non-Shipmiracle) hook is a WARN only", code == 0 and "WARN test-all" in out, (code, out[-300:]))

sys.exit(1 if fails else 0)
