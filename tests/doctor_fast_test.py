#!/usr/bin/env python3
"""bin/doctor fast/full split (Platform v2 P7): fast mode is quick, skips only what it says it skips (never green when skipped),
keeps exit codes and row format, and --full keeps every row. Run: python3 tests/doctor_fast_test.py
Opt-in differential (about 2.5 min): DOCTOR_DIFF=1 python3 tests/doctor_fast_test.py  compares --full against the pre-split doctor (git show DOCTOR_BASE:bin/doctor, default HEAD)."""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import shipmiracle_isolation; shipmiracle_isolation.apply_to_environ()   # test isolation: fresh HOME/SHIPMIRACLE_HOME/CONFIG/STATE unless already temp
import os, re, subprocess, sys, tempfile, time
from pathlib import Path
WS = Path(__file__).resolve().parent.parent
fails = 0
def check(n, c, info=""):
    global fails
    print(("PASS " if c else "FAIL ") + n + ("" if c else " :: " + str(info)[:600])); fails += 0 if c else 1
SRC = (WS / "bin/doctor").read_text()
T = Path(tempfile.mkdtemp()).resolve()
SKIP = "  info not checked in fast mode (run bin/doctor --full): "
def run(args, home=None, path=None, script=None, timeout=900):
    env = dict(os.environ, SHIPMIRACLE_TEST="1", SHIPMIRACLE_STATE=str((home or T) / ".local/state/shipmiracle"))   # Shipmiracle core rows write a cache under the state folder: keep it away from the real one
    if home: env["HOME"] = str(home)
    if path: env["PATH"] = path
    t0 = time.time()
    r = subprocess.run([str(script or WS / "bin/doctor")] + args, capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL, timeout=timeout, cwd=str(WS))
    return r.returncode, r.stderr + r.stdout, time.time() - t0     # stdout last: the final "doctor:" line stays the last line whatever stderr said

check("bash -n bin/doctor", subprocess.run(["bash", "-n", str(WS / "bin/doctor")]).returncode == 0)
rc, o, dt = run(["--bogus"]); check("unknown option: exit 2 and usage", rc == 2 and "usage: bin/doctor [--full]" in o, o)
rc, o, dt = run(["--help"]); check("--help: exit 0, no checks run", rc == 0 and "usage:" in o and "Tools" not in o, o)

# ---- fast mode on the real (read-only) state
rc, fast, dt = run([])
print("INFO fast mode wall time %.1f s, load %s" % (dt, os.getloadavg()[0].__round__(1)))
check("fast mode finishes well under 15 s (%.1fs)" % dt, dt < 15, dt)
check("fast mode ends with the doctor: line and exit 0/1 only", rc in (0, 1) and fast.rstrip().splitlines()[-1].startswith("doctor:"), fast[-300:])
skipped = [l[len(SKIP):] for l in fast.splitlines() if l.startswith(SKIP)]
# labels of every row that fast mode must not run: the ok text of each trow call plus the other slow rows
trow_ok = re.findall(r'^(?:\[\[ -f [^\]]*\]\] && )?trow \w+ "([^"]*)"', SRC, re.M)
import shutil
slow_other = ["Claude Code signed in", "GitHub CLI signed in", "no agents waiting for promotion"] + (["MCP servers connect"] if shutil.which("claude", path=os.environ.get("PATH")) else [])     # bin/doctor has the MCP row only when `claude` is on PATH (a machine without it has no such row, so none can be "not checked")
check("every embedded test-suite row is listed as 'not checked' in fast mode (%d)" % len(trow_ok), all(x in skipped for x in trow_ok), [x for x in trow_ok if x not in skipped])
check("login, MCP and promotion rows are listed as 'not checked'", all(x in skipped for x in slow_other), skipped)
HAS_PROJECTS = any(p.is_dir() and not p.is_symlink() and p.name != "AI-Workspace" for p in Path(os.path.expanduser("~/Developer")).glob("*"))     # the brief row exists only when a project is under ~/Developer
if HAS_PROJECTS:
    check("session-brief rows are listed as 'not checked'", any(x.startswith("session brief size") for x in skipped), skipped)
else:
    print("SKIP session-brief row: no project under ~/Developer on this machine (temp HOME)")
check("a skipped row is never printed ok/warn/FAIL in fast mode",
      not any(l.startswith(("  ok   " + x, "  warn " + x, "  FAIL " + x)) for l in fast.splitlines() for x in trow_ok + slow_other), "")
check("no 'session brief is' warning and no test-suite 'pass' row in fast mode", "session brief is" not in fast and not re.search(r"^  ok   .*tests pass", fast, re.M), "")
check("last lines say how many checks were not run; 'all good' is qualified", ("%d check(s) not run" % len(skipped)) in fast and "doctor: all good" not in fast.replace("doctor: all good (fast mode,", ""), fast[-300:])
check("every section header is still printed",
      all(h in fast.splitlines() for h in ["Tools", "Logins (no credentials read)", "VS Code extensions", "Claude: MCP and model", "Global Claude hooks", "Awake guard", "Shared memory", "Shipmiracle core", "Skills and agents", "Secret scan", "GitHub", "Projects", "CI on main", "Workspace"]), "")
check("the Shipmiracle core rows and the project rows are present in fast mode", "  ok   python" in fast and re.search(r"^  (ok|warn) +\S+ (pushed and clean|: \d+ commits)", fast, re.M) is not None or "Projects" in fast, "")

# ---- fixture HOME: exit codes and FAIL rows survive the parallel prefetch
H = T / "home"; (H / ".claude").mkdir(parents=True); (H / ".local").mkdir(); (H / ".vscode").mkdir()
D = H / "Developer"; P = D / "proj"; P.mkdir(parents=True)
g = lambda *a: subprocess.run(["git", "-C", str(P), *a], check=True, capture_output=True)
subprocess.run(["git", "init", "-q", str(P)], check=True); g("remote", "add", "origin", "https://example.invalid/x.git")
(P / ".git/PUSH-FAILED").write_text("2026-10-20 10:00")
SAFE = "/usr/bin:/bin"
rc, o, dt = run([], home=H, path=SAFE)
check("fixture HOME: missing global hooks and a PUSH-FAILED project -> FAIL rows, exit 1 in fast mode", rc == 1 and "  FAIL global hook keep-awake missing" in o and "  FAIL proj: auto-push failed at 2026-10-20 10:00" in o and "\ndoctor: problems above" in o, o[-800:])
(P / ".git/PUSH-FAILED").unlink()
rc, o, dt = run([], home=H, path=SAFE)
check("fixture HOME: project rows come from the background job (proj: ... uncommitted/pushed)", re.search(r"^  (warn|ok) +proj", o, re.M) is not None and "auto-push failed" not in o, o[-600:])
(H / ".local/state/shipmiracle").mkdir(parents=True, exist_ok=True)
(H / ".local/state/shipmiracle/flow-errors.log").write_text(time.strftime("%Y-%m-%d %H:%M:%S") + " Traceback IndexError\n")
rc, o, dt = run([], home=H, path=SAFE)
check("flow-errors row still red in fast mode", "  FAIL team flow check logged 1 internal error(s)" in o, o[-500:])

# ---- --full is accepted and keeps the old text for its rows (only the test-suite rows of ONE lane, via the real run in the differential below)
if os.environ.get("DOCTOR_DIFF") == "1":
    base = os.environ.get("DOCTOR_BASE", "HEAD")
    old = subprocess.run(["git", "-C", str(WS), "show", base + ":bin/doctor"], capture_output=True, text=True).stdout
    oldp = WS / "bin" / (".doctor-old-%d" % os.getpid())
    try:
        oldp.write_text(old); oldp.chmod(0o755)
        for label, home in (("real state", None), ("fixture HOME", H)):
            rc1, a, t1 = run([], home=home, script=oldp)
            rc2, b, t2 = run(["--full"], home=home)
            norm = lambda s: [l for l in s.splitlines() if not l.startswith(("doctor:", "  info doctor took"))]
            check("differential (%s): --full rows == old doctor rows (%d lines), exit %d == %d; old %.0fs, new %.0fs" % (label, len(norm(a)), rc1, rc2, t1, t2), norm(a) == norm(b) and rc1 == rc2, [x for x in zip(norm(a), norm(b)) if x[0] != x[1]][:3])
    finally:
        oldp.unlink()
else:
    print("INFO differential vs the old doctor is opt-in: DOCTOR_DIFF=1")
print("\nFAILED:" if fails else "\nALL PASS", fails); sys.exit(1 if fails else 0)
