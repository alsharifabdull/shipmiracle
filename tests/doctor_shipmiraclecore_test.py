#!/usr/bin/env python3
"""bin/doctor: the 'Shipmiracle core' rows come from bin/shipm doctor --rows (fast, FAIL row fails doctor) and the daily-log row reads the new log folder
or the old reports/ one. Only the lines between the markers are run. Run: python3 tests/doctor_shipmiraclecore_test.py"""
import os, subprocess, sys, tempfile, time
from pathlib import Path
WS = Path(__file__).resolve().parent.parent
fails = 0
def check(n, c, info=""):
    global fails
    print(("PASS " if c else "FAIL ") + n + ("" if c else " :: " + str(info))); fails += 0 if c else 1
lines = (WS / "bin/doctor").read_text().splitlines()
def between(a, b):
    i = next(k for k, l in enumerate(lines) if l.startswith(a)); j = next(k for k, l in enumerate(lines) if l.startswith(b)); return "\n".join(lines[i + 1:j])
core, dlog = between("# shipmiracle-core-begin", "# shipmiracle-core-end"), between("# dlog-begin", "# dlog-end")
T = Path(tempfile.mkdtemp()).resolve()
pre = 'fail=0; ok() { printf "ok %s\\n" "$1"; }; bad() { printf "FAIL %s\\n" "$1"; fail=1; }; warn() { printf "warn %s\\n" "$1"; }\n'
env = dict(os.environ, SHIPMIRACLE_TEST="1", SHIPMIRACLE_HOME=str(T / "h"), SHIPMIRACLE_STATE=str(T / "state"), SHIPMIRACLE_CONFIG=str(T / "cfg"))
t0 = time.time()
r = subprocess.run(["bash", "-c", pre + 'WS="%s"\n' % WS + core + '\necho "fail=$fail"'], env=env, capture_output=True, text=True, timeout=30)
dt = time.time() - t0
check("Shipmiracle core rows are printed in doctor's format", "  ok   python" in r.stdout and "owner config valid" in r.stdout, r)
check("Shipmiracle core section adds well under 0.5 s (%.2fs)" % dt, dt < 0.5, dt)
check("no FAIL row on a clean temp home", "fail=0" in r.stdout, r.stdout)
(T / "cfg").mkdir(); (T / "cfg/config.json").write_text("{broken"); os.chmod(T / "cfg", 0o700)
r = subprocess.run(["bash", "-c", pre + 'WS="%s"\n' % WS + core + '\necho "fail=$fail"'], env=env, capture_output=True, text=True, timeout=30)
check("a FAIL row from shipmiracle (broken config) sets doctor's fail flag", "owner config invalid" in r.stdout and "fail=1" in r.stdout, r.stdout)
# daily log row source
fake = T / "ws"; (fake / "reports").mkdir(parents=True); (T / "state/v1/logs").mkdir(parents=True)
old, new = fake / "reports/daily-2026-01-01.log", T / "state/v1/logs/daily-2026-10-20.log"
old.write_text("o"); os.utime(old, (1000, 1000)); new.write_text("n")
def newest(e=None): return subprocess.run(["bash", "-c", 'WS="%s"\n' % fake + dlog + '\necho "$last"'], env=e or env, capture_output=True, text=True).stdout.strip()
check("newest log comes from the new location", newest() == str(new), newest())
new.unlink()
check("falls back to the old reports/ log", newest() == str(old), newest())
new.write_text("n")
noenv = {k: v for k, v in env.items() if k != "SHIPMIRACLE_TEST"}; noenv["HOME"] = str(T / "nohome")
check("SHIPMIRACLE_STATE is ignored without SHIPMIRACLE_TEST=1 (falls back to the old reports/ log)", newest(noenv) == str(old), newest(noenv))
new.unlink(); old.unlink()
check("no log anywhere -> empty (doctor says it has not run yet)", newest() == "")
print("\nFAILED:" if fails else "\nALL PASS", fails); sys.exit(1 if fails else 0)
