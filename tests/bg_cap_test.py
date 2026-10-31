#!/usr/bin/env python3
"""shipm-bg deadline and agent-cap hook. Run: python3 tests/bg_cap_test.py"""
import json, os, subprocess, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import shipmiracle_timing as T
WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); fails = []
def check(n, c, info=""):
    print(("PASS " if c else "FAIL ") + n + ("" if c else " " + str(info)))
    if not c: fails.append(n)
t = tempfile.mkdtemp(); env = dict(os.environ, SHIPMIRACLE_BG_LOG=t + "/bg.log")
r = subprocess.run([sys.executable, WS + "/bin/shipm-bg", "1", "--", "sh", "-c", "exit 3"], env=env); check("exit code of the command is passed through", r.returncode == 3, r.returncode)
MARK = "30.%d" % os.getpid()   # unique: other processes may also run sleep 30
_res = {}
def _bg():
    t0 = time.perf_counter(); _res["r"] = subprocess.run([sys.executable, WS + "/bin/shipm-bg", "0.02", "--", "sh", "-c", "sleep %s & sleep %s" % (MARK, MARK)], env=env); return time.perf_counter() - t0
_ok, _rep, _ = T.robust(_bg, lambda: T.spawn_ref(10), 8.0, 60)   # nominal 1.2 s; limit 8 s or 60 x python start
check("deadline ends the job and its children (124, in about a second)", _res["r"].returncode == 124, _res["r"].returncode)
check("deadline run time within max(8 s, 60 x python start)", _ok, _rep)
check("no leftover sleep from the job", subprocess.run("pgrep -f 'sleep %s'" % MARK.replace('.', '[.]'), shell=True, capture_output=True).stdout == b"")
log = open(t + "/bg.log").read(); check("start, deadline and end are logged", "start deadline" in log and "deadline reached" in log and "end rc=124" in log)
if os.path.exists(WS + "/hooks/agent-cap.sh"):          # the legacy shell hook exists only in the owner's checkout
    st = tempfile.mkdtemp(); proj = tempfile.mkdtemp(); name = os.path.basename(os.path.realpath(proj))
    def hook(): return subprocess.run(["bash", WS + "/hooks/agent-cap.sh"], input="{}", capture_output=True, text=True, env=dict(os.environ, SHIPMIRACLE_STATE=st, CLAUDE_PROJECT_DIR=proj)).stdout
    def agents(n, who=name): json.dump({str(i): {"started": time.time()} for i in range(n)}, open(f"{st}/{who}.agents.json", "w"))
    check("no agents: allowed", hook() == "")
    agents(3); check("3 agents in the project: allowed", hook() == "")
    agents(4); check("4 agents in the project: denied with a reason", "deny" in hook() and "limit 4" in hook())
    agents(2); agents(6, "other"); check("8 agents in total: denied", "deny" in hook() and "limit 8" in hook())
    agents(1, "other"); agents(0); open(st + "/agents.paused", "w").close(); check("paused: denied", "paused" in hook())
    os.remove(st + "/agents.paused"); json.dump({"x": {"started": time.time() - 5 * 3600}}, open(f"{st}/other.agents.json", "w")); agents(1)
    check("agents older than 3 h are not counted", hook() == "")
print("ALL PASS" if not fails else "FAILED %s" % fails); sys.exit(1 if fails else 0)
