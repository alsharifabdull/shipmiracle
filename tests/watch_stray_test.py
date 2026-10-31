#!/usr/bin/env python3
"""bin/shipm-watch stray_browser and stray_testrun against REAL dummy processes (real ps, real lsof, real signals; no real Chrome, no real test-all):
  - a dummy 'Google Chrome' with a temp profile is ended by its Fix; one whose profile is NOT in a temp folder survives every scan and every act;
  - an orphaned dummy test-all (parent pid 1) is stopped by SIGTERM only; one with a live parent survives.
Run: python3 tests/watch_stray_test.py"""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import shipmiracle_isolation; shipmiracle_isolation.apply_to_environ()   # test isolation: fresh HOME/SHIPMIRACLE_HOME/CONFIG/STATE unless already temp
import json, os, pathlib, signal, subprocess, sys, tempfile, time
ws = pathlib.Path(__file__).resolve().parent.parent
T = pathlib.Path(tempfile.mkdtemp(prefix="strayt-")).resolve()
HOME, STATE, W = T / "home", T / "state", T / "ws"
DEV = HOME / "Developer"
(DEV / "p1" / "bin").mkdir(parents=True); (W / "bin").mkdir(parents=True); (W / "config").mkdir(parents=True); STATE.mkdir()
(W / "config" / "watch.json").write_text(json.dumps({"stray_browser_min": 0, "stray_testrun_min": 0}))
ENV = dict(os.environ, SHIPMIRACLE_TEST="1", SHIPMIRACLE_HOME=str(HOME), SHIPMIRACLE_DEV=str(DEV), SHIPMIRACLE_STATE=str(STATE), SHIPMIRACLE_WS=str(W), HOME=str(HOME))
for k in ("SHIPMIRACLE_PS", "SHIPMIRACLE_LSOF", "SHIPMIRACLE_KILL_LOG", "SHIPMIRACLE_NOW", "CLAUDECODE"):
    ENV.pop(k, None)
fails = 0
def check(n, c, info=""):
    global fails
    print(("PASS " if c else "FAIL ") + n + ("" if c else " :: " + str(info)[:500])); fails += 0 if c else 1
def alive(pid):
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    r = subprocess.run(["/bin/ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    return bool(r) and not r.startswith("Z")
def watch(*a):
    r = subprocess.run([str(ws / "bin" / "shipm-watch"), *a], capture_output=True, text=True, env=ENV, timeout=90, stdin=subprocess.DEVNULL, cwd=str(T))
    try:
        return json.loads(r.stdout)
    except Exception:
        return {"_raw": r.stdout + r.stderr}
def items(kind):
    return [i for i in json.loads((STATE / "health.json").read_text())["items"] if i["kind"] == kind]
PY = "#!/usr/bin/env python3\nimport time\ntime.sleep(300)\n"
pids = []
def start(script, args, cwd, orphan):
    cwd = str(cwd)
    if orphan:                       # double fork through sh: the child's parent becomes launchd (pid 1)
        pf = T / ("pid-%d" % len(pids))
        subprocess.run(["/bin/sh", "-c", '( cd "$1" && shift && exec "$@" ) </dev/null >/dev/null 2>&1 & echo $! > "$0"', str(pf), cwd, str(script), *args], check=True, env=ENV)
        for _ in range(50):
            if pf.exists() and pf.read_text().strip():
                break
            time.sleep(0.1)
        pid = int(pf.read_text().strip())
    else:
        pid = subprocess.Popen([str(script), *args], cwd=cwd, env=ENV, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).pid
    pids.append(pid)
    time.sleep(0.8)
    return pid
try:
    chrome = T / "Google Chrome.app" / "Contents" / "MacOS" / "Google Chrome"
    chrome.parent.mkdir(parents=True); chrome.write_text(PY); chrome.chmod(0o755)
    prof = T / "profile-temp"; prof.mkdir()
    b_temp = start(chrome, ["--headless=new", "--remote-debugging-port=1", "--user-data-dir=" + str(prof)], T, True)
    b_other = start(chrome, ["--headless=new", "--remote-debugging-port=2", "--user-data-dir=/Users/someone/own-debug-profile"], T, True)
    ta = W / "bin" / "test-all"; ta.write_text(PY); ta.chmod(0o755)          # the workspace's own bin/test-all (L5: only this one counts)
    t_orphan = start(ta, [], DEV / "p1", True)
    t_live = start(ta, [], DEV / "p1", False)
    pta = DEV / "p1" / "bin" / "test-all"; pta.write_text(PY); pta.chmod(0o755)   # a PROJECT's own test-all script, orphaned too: never listed, never ended
    t_proj = start(pta, [], DEV / "p1", True)
    b_two = start(chrome, ["--headless=new", "--remote-debugging-port=3", "--user-data-dir=" + str(prof), "--user-data-dir=/Users/someone/real-profile"], T, True)     # decoy temp first, real profile last
    b_one_dash = start(chrome, ["--headless=new", "--remote-debugging-port=5", "--user-data-dir=" + str(prof), "-user-data-dir=/Users/someone/real-profile"], T, True)      # single-dash spelling counts as a second occurrence
    b_two_b = start(chrome, ["--headless=new", "--remote-debugging-port=4", "--user-data-dir=/Users/someone/real-profile", "--user-data-dir=" + str(prof)], T, True)   # two occurrences: never temp, even when the last is a temp folder
    for _ in range(2):
        subprocess.run([str(ws / "bin" / "shipm-watch"), "scan"], env=ENV, capture_output=True, timeout=90, stdin=subprocess.DEVNULL, cwd=str(T))
    sb = {i["pid"]: i for i in items("stray_browser")}
    st = {i["pid"]: i for i in items("stray_testrun")}
    check("real ps: both automation browsers are listed", b_temp in sb and b_other in sb, sorted(sb))
    check("real ps: the temp-profile browser is fixable, the other-profile browser is only listed", sb[b_temp]["fixable_now"] and not sb[b_other]["fixable_now"] and sb[b_other]["mode"] == "info", (sb[b_temp]["mode"], sb[b_other]["mode"]))
    check("real ps: only the orphaned test-all is listed (the one with a live parent is not)", t_orphan in st and t_live not in st, sorted(st))
    check("L5 a project's own orphaned test-all is not listed as a test run", t_proj not in st, sorted(st))
    check("L5 two --user-data-dir occurrences: listed but only listed (never fixable), in either order", all(b in sb and not sb[b]["fixable_now"] and sb[b]["mode"] == "info" for b in (b_two, b_two_b, b_one_dash)), {b: sb.get(b) for b in (b_two, b_two_b, b_one_dash)})
    r = watch("act", "end-browser", sb[b_two]["id"])
    check("L5 act end-browser on the two-profile browser is refused and it survives", r.get("ok") is False and alive(b_two) and alive(b_two_b), r)
    r = watch("act", "end-browser", sb[b_other]["id"])
    check("act end-browser on the other-profile browser is refused and it survives", r.get("ok") is False and alive(b_other), r)
    r = watch("act", "end-browser", sb[b_temp]["id"])
    time.sleep(1)
    check("act end-browser ends the temp-profile browser", r.get("ok") is True and not alive(b_temp), r)
    check("...and the other-profile browser still survives", alive(b_other))
    r = watch("act", "end-testrun", st[t_orphan]["id"])
    time.sleep(1)
    check("act end-testrun stops the orphaned test-all with SIGTERM and reports the leftovers", r.get("ok") is True and not alive(t_orphan) and "child" in r.get("did", ""), r)
    check("the test-all with a live parent survives", alive(t_live))
    check("L5 the project's own test-all survives", alive(t_proj))
    for _ in range(2):
        subprocess.run([str(ws / "bin" / "shipm-watch"), "scan"], env=ENV, capture_output=True, timeout=90, stdin=subprocess.DEVNULL, cwd=str(T))
    check("after the rescan neither ended process is listed any more", b_temp not in {i["pid"] for i in items("stray_browser")} and t_orphan not in {i["pid"] for i in items("stray_testrun")})
finally:
    for p in pids:
        try:
            os.kill(p, signal.SIGKILL)
        except OSError:
            pass
    import shutil; shutil.rmtree(T, ignore_errors=True)
print("\nALL PASS" if not fails else "\n%d FAILED" % fails); sys.exit(1 if fails else 0)
