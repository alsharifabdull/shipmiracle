#!/usr/bin/env python3
"""Owner-step scripts (docs/owner-steps/*.sh, except p5-playbook.sh which has its own typed confirmation): the refusal inside a Claude chat
(CLAUDECODE set, even empty) is lifted only by a full temp sandbox (SHIPMIRACLE_TEST=1 + HOME, SHIPMIRACLE_STATE, SHIPMIRACLE_CONFIG and SHIPMIRACLE_LAUNCHCTL when set, all under the
system temp folder; the same rule as shipmiracle.paths.sandboxed()). SHIPMIRACLE_TEST=1 alone, a real HOME or a real state folder never lifts it.
Every script runs without --apply; the 'real' paths used here do not exist (nothing real is read or written). Run: python3 tests/owner_scripts_refusal_test.py"""
import glob, os, pwd, subprocess, sys, tempfile
from pathlib import Path
WS = Path(__file__).resolve().parent.parent
fails = 0
def check(n, c, info=""):
    global fails
    print(("PASS " if c else "FAIL ") + n + ("" if c else " :: " + str(info)[:500])); fails += 0 if c else 1
REAL = pwd.getpwuid(os.getuid()).pw_dir
T = Path(tempfile.mkdtemp()).resolve()
for d in ("home", "state", "cfg", "ws", "dev"):
    (T / d).mkdir()
FAKE_REAL = REAL + "/.shipmiracle-refusal-test-does-not-exist"      # under the real home, absent
scripts = sorted(p for p in glob.glob(str(WS / "docs/owner-steps/*.sh")) if not p.endswith(("p5-playbook.sh", "cutover.sh")))      # cutover.sh refuses inside a chat by its own preconditions and has its own private test
if not scripts:
    print("SKIP-ALL the owner-step scripts (docs/owner-steps) are not shipped in the public tree"); sys.exit(0)
check("found the owner-step scripts", len(scripts) >= 8, scripts)
def run(script, **env):
    e = {k: v for k, v in os.environ.items() if not k.startswith("SHIPMIRACLE_") and k not in ("CLAUDECODE", "HOME")}
    e.update(env)
    r = subprocess.run(["bash", script], env=e, capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL, cwd=str(T))
    return r.returncode, r.stdout + r.stderr
SANDBOX = dict(SHIPMIRACLE_TEST="1", HOME=str(T / "home"), SHIPMIRACLE_STATE=str(T / "state"), SHIPMIRACLE_CONFIG=str(T / "cfg"), SHIPMIRACLE_WS=str(T / "ws"), SHIPMIRACLE_DEV=str(T / "dev"), SHIPMIRACLE_HOME=str(T / "home"))
blocked = lambda o: "BLOCKED" in o and "CLAUDECODE is set" in o
for s in scripts:
    n = os.path.basename(s)
    rc, o = run(s, CLAUDECODE="1", SHIPMIRACLE_TEST="1", HOME=REAL, SHIPMIRACLE_STATE=str(T / "state"), SHIPMIRACLE_CONFIG=str(T / "cfg"))
    check(n + ": CLAUDECODE=1 SHIPMIRACLE_TEST=1 with the real HOME is refused", rc != 0 and blocked(o), (rc, o))
    rc, o = run(s, CLAUDECODE="", SHIPMIRACLE_TEST="1", HOME=REAL, SHIPMIRACLE_STATE=FAKE_REAL + "/s", SHIPMIRACLE_CONFIG=FAKE_REAL + "/c")
    check(n + ": an EMPTY CLAUDECODE counts as inside a chat (real HOME, real state)", rc != 0 and blocked(o), (rc, o))
    rc, o = run(s, CLAUDECODE="1", **dict(SANDBOX, SHIPMIRACLE_STATE=FAKE_REAL + "/s"))
    check(n + ": temp HOME but a real SHIPMIRACLE_STATE is refused", rc != 0 and blocked(o), (rc, o))
    rc, o = run(s, CLAUDECODE="1", **{k: v for k, v in SANDBOX.items() if k != "SHIPMIRACLE_CONFIG"})
    check(n + ": SHIPMIRACLE_CONFIG missing is refused", rc != 0 and blocked(o), (rc, o))
    rc, o = run(s, CLAUDECODE="1", **dict(SANDBOX, SHIPMIRACLE_LAUNCHCTL=FAKE_REAL + "/launchctl"))
    check(n + ": a real SHIPMIRACLE_LAUNCHCTL is refused", rc != 0 and blocked(o), (rc, o))
    rc, o = run(s, CLAUDECODE="1", **dict(SANDBOX, SHIPMIRACLE_STATE=str(T / "state") + "/../../" + FAKE_REAL[1:]))
    check(n + ": a path that climbs out of the temp folder with .. is refused", rc != 0 and blocked(o), (rc, o))
    rc, o = run(s, CLAUDECODE="1", **{k: v for k, v in SANDBOX.items() if k != "SHIPMIRACLE_TEST"})
    check(n + ": without SHIPMIRACLE_TEST=1 even a temp sandbox is refused", rc != 0 and blocked(o), (rc, o))
    rc, o = run(s, CLAUDECODE="1", **SANDBOX)
    check(n + ": the full temp sandbox is NOT refused by the chat check", not blocked(o), (rc, o))
    rc, o = run(s, **dict(SANDBOX, SHIPMIRACLE_TEST="1"))
    check(n + ": no CLAUDECODE: the chat check does not fire", not blocked(o), (rc, o))
print("\nFAILED:" if fails else "\nALL PASS", fails); sys.exit(1 if fails else 0)
