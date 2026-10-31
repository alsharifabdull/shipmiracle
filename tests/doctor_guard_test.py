#!/usr/bin/env python3
"""bin/doctor Awake-guard rows read from guard.json / events.log (30 Oct 2026): older guard code, sleep disabled while not holding,
manual hold, last network outage. Runs the marker-delimited lines of bin/doctor against a fixture state folder, a fixture guard file
and a fake `pmset` on PATH (the real pmset, HOME and state are never touched). Run: python3 tests/doctor_guard_test.py"""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import shipmiracle_isolation; shipmiracle_isolation.apply_to_environ()   # test isolation: fresh HOME/SHIPMIRACLE_HOME/CONFIG/STATE unless already temp
import hashlib, json, os, subprocess, tempfile, time
from pathlib import Path
WS = Path(__file__).resolve().parent.parent
fails = 0
def check(n, c, info=""):
    global fails
    print(("PASS " if c else "FAIL ") + n + ("" if c else " :: " + str(info)[:800])); fails += 0 if c else 1
lines = (WS / "bin/doctor").read_text().splitlines()
i = next(k for k, l in enumerate(lines) if l.startswith("# guardrows-begin")); j = next(k for k, l in enumerate(lines) if l.startswith("# guardrows-end"))
BLOCK = "\n".join(lines[i + 1:j])
T = Path(tempfile.mkdtemp()).resolve()
PRE = 'fail=0; ok() { printf "  ok   %s\\n" "$1"; }; bad() { printf "  FAIL %s\\n" "$1"; fail=1; }; warn() { printf "  warn %s\\n" "$1"; }\n'
H = T / "home"; S = H / ".local/state/shipmiracle"; S.mkdir(parents=True)
FW = T / "ws"; (FW / "bin").mkdir(parents=True); GF = FW / "bin/shipm-guard"; GF.write_text("#!/usr/bin/env python3\nprint('guard v2')\n")
GSHA = hashlib.sha256(GF.read_bytes()).hexdigest()
FB = T / "fakebin"; FB.mkdir()
PM = FB / "pmset"; PM.write_text('#!/bin/sh\n[ "$1" = "-g" ] || { echo "fake pmset: unexpected args $*" >&2; exit 9; }\ncat "$FAKE_PMSET"\n'); PM.chmod(0o755)
PMF = T / "pmset.txt"
PM_ON = "System-wide power settings:\n SleepDisabled\t\t1\nCurrently in use:\n sleep 0\n"
PM_OFF = "System-wide power settings:\n SleepDisabled\t\t0\nCurrently in use:\n sleep 1\n"
def run(guard=None, events=None, pm=PM_OFF, guard_file=GF, path=True):
    for f in ("guard.json", "events.log"): (S / f).unlink(missing_ok=True)
    if guard is not None: (S / "guard.json").write_text(guard if isinstance(guard, str) else json.dumps(guard))
    if events is not None: (S / "events.log").write_text("\n".join(events) + "\n")
    PMF.write_text(pm)
    e = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    e.update(SHIPMIRACLE_TEST="1", SHIPMIRACLE_STATE=str(S), HOME=str(H), FAKE_PMSET=str(PMF), GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1")
    if path: e["PATH"] = str(FB) + os.pathsep + e["PATH"]
    r = subprocess.run(["bash", "-c", PRE + 'WS="%s"\n' % FW + BLOCK + '\necho "fail=$fail"'], env=e, capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    return r.stdout + r.stderr
now = time.time()
ts = lambda off: time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now - off))
evl = lambda off, extra: ts(off) + " lid_closed=False ac=True batt=100% " + extra + " reason=x"

# nothing at all: no rows, no FAIL
o = run()
check("no guard.json, no events.log: no row at all, fail=0", "warn" not in o and "info" not in o and "  ok" not in o and "fail=0" in o, o)
o = run(guard="{broken")
check("broken guard.json: no row, no crash", "warn" not in o and "info" not in o and "fail=0" in o and "Traceback" not in o, o)
o = run(guard=[1, 2])
check("guard.json is not an object: no row", "warn" not in o and "info" not in o and "fail=0" in o, o)

# 1) older code
o = run(guard={"hold": True, "ts": int(now), "pid": 1, "code_started": {"sha": GSHA[:12], "ts": int(now)}})
check("code_started.sha equals sha256 of bin/shipm-guard: ok row, no warn", "  ok   guard is running the current bin/shipm-guard" in o and "warn" not in o, o)
o = run(guard={"hold": True, "code_started": {"sha": GSHA[:12], "ts": int(now)}})
check("the 12-hex prefix the guard writes matches", "  ok   guard is running the current" in o, o)
o = run(guard={"hold": True, "code_started": {"sha": "0" * 12, "ts": int(now)}})
check("different sha: warn row with the restart hint, fail=0", "  warn guard is running older code than bin/shipm-guard → it reloads itself within a few seconds; if it stays: launchctl kickstart -k gui/$(id -u)/com.shipmiracle.guard" in o and "fail=0" in o, o)
for bad_cs in (None, "x", {"time": 1}, {"sha": 5}, {"sha": ""}, {"sha": "abc"}):
    o = run(guard={"hold": True, "code_started": bad_cs} if bad_cs is not None else {"hold": True})
    check("code_started %r: no row (fail-soft)" % (bad_cs,), "older code" not in o and "current bin/shipm-guard" not in o and "fail=0" in o, o)
GF2 = GF.with_name("x"); GF.rename(GF2)
o = run(guard={"code_started": {"sha": "0" * 64}})
check("bin/shipm-guard unreadable: no row, no crash", "older code" not in o and "fail=0" in o and "Traceback" not in o, o)
GF2.rename(GF)

# 2) sleep disabled but not holding
o = run(guard={"hold": False}, events=[evl(1200, "hold=False lpm=False off=False")], pm=PM_ON)
check("SleepDisabled 1, hold false for 20 min: warn row", "  warn sleep is disabled but the guard is not holding → shipm-guard off then on" in o and "fail=0" in o, o)
o = run(guard={"hold": False}, events=[evl(120, "hold=False lpm=False off=False")], pm=PM_ON)
check("hold false for only 2 min: no warn", "sleep is disabled" not in o, o)
o = run(guard={"hold": False}, events=[evl(1200, "hold=False lpm=False off=False")], pm=PM_OFF)
check("SleepDisabled 0: no warn", "sleep is disabled" not in o, o)
o = run(guard={"hold": True}, events=[evl(1200, "hold=True lpm=False off=False")], pm=PM_ON)
check("guard is holding: no warn", "sleep is disabled" not in o, o)
o = run(guard={"hold": False}, events=[evl(3000, "hold=True lpm=False off=False"), evl(1200, "hold=False lpm=False off=False")], pm=PM_ON)
check("last hold change is False 20 min ago: warn", "sleep is disabled but the guard is not holding" in o, o)
o = run(guard={"hold": False}, events=[evl(1200, "hold=False lpm=False off=False"), evl(60, "hold=True lpm=False off=False")], pm=PM_ON)
check("the latest events.log line says hold=True (guard.json is older): no warn", "sleep is disabled" not in o, o)
o = run(guard={"hold": False}, pm=PM_ON)
check("no events.log: duration unknown, no warn (fail-soft)", "sleep is disabled" not in o and "fail=0" in o, o)
o = run(guard={}, events=[evl(1200, "hold=False")], pm=PM_ON)
check("guard.json without hold: no warn", "sleep is disabled" not in o, o)
o = run(guard={"hold": False}, events=["garbage line", evl(1200, "hold=False")], pm=PM_ON)
check("a garbage events.log line is skipped", "sleep is disabled but the guard is not holding" in o and "Traceback" not in o, o)
o = run(guard={"hold": False}, events=[evl(1200, "hold=False")], pm="")
check("pmset output empty: no warn, no crash", "sleep is disabled" not in o and "fail=0" in o, o)

# 3) manual hold
fut = now + 3600
o = run(guard={"manual_until": fut})
check("manual_until in the future (epoch s): info 'manual hold until HH:MM'", "  info manual hold until " + time.strftime("%H:%M", time.localtime(fut)) in o and "fail=0" in o, o)
o = run(guard={"manual_until": int(fut * 1000)})
check("manual_until in ms is read too", "manual hold until " + time.strftime("%H:%M", time.localtime(fut)) in o, o)
o = run(guard={"manual_until": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(fut))})
check("manual_until as a local ISO string is read too", "manual hold until " + time.strftime("%H:%M", time.localtime(fut)) in o, o)
(S / "guard.hold").write_text(json.dumps({"until": fut, "set": int(now)}))
o = run(guard={"manual_until": None})
check("manual_until null falls back to the state file guard.hold (run() clears only guard.json and events.log)", "manual hold until " + time.strftime("%H:%M", time.localtime(fut)) in o, o)
(S / "guard.hold").unlink()
for v in (now - 60, 0, None, True, "soon", [1]):
    o = run(guard={"manual_until": v})
    check("manual_until %r: no row" % (v,), "manual hold" not in o and "fail=0" in o, o)

# 4) network outage (guard line written when an outage ends: net_outage start=<%FT%T> end=<%FT%T> gap_s=N)
iso = lambda off: time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now - off))
nol = lambda off, dur: ts(off - dur) + " net_outage start=" + iso(off) + " end=" + iso(off - dur) + " gap_s=%d" % dur
o = run(guard={}, events=[nol(7200, 600)])
check("outage line: info 'last network outage <start> for 10 min'", "  info last network outage " + time.strftime("%Y-%m-%d %H:%M", time.localtime(now - 7200)) + " for 10 min" in o and "fail=0" in o, o)
o = run(guard={}, events=[nol(7200, 600), nol(300, 45)])
check("the LAST outage is shown (45 s)", "last network outage " + time.strftime("%Y-%m-%d %H:%M", time.localtime(now - 300)) + " for 45 s" in o and o.count("network outage") == 1, o)
o = run(guard={}, events=[nol(20000, 7200)])
check("a 2 h outage is shown in hours", " for 2.0 h" in o, o)
o = run(guard={}, events=[evl(300, "hold=True")])
check("no net_outage line: no outage row", "network outage" not in o, o)
o = run(guard={})
check("no events.log: no outage row", "network outage" not in o, o)
o = run(guard={}, events=[ts(100) + " net_outage start=garbage gap_s=x", ts(100) + " net_outage start=2026-10-30T09:00:00 end=2026-10-30T09:05:00"])
check("malformed net_outage lines: no row, no crash", "network outage" not in o and "Traceback" not in o and "fail=0" in o, o)
o = run(guard={}, events=[nol(7200, 600) + " ssid=HomeWifi-123"])
check("a network name in the line is never printed", "HomeWifi" not in o and "ssid" not in o and "network outage" in o, o)

# read-only: the guard files are unchanged by the run
g = {"hold": False, "manual_until": fut, "code_started": {"sha": "0" * 64}}
run(guard=g, events=[evl(1200, "hold=False"), nol(900, 60)], pm=PM_ON)
(S / "guard.json").write_text(json.dumps(g)); before = ((S / "guard.json").read_bytes(), (S / "events.log").read_bytes())
e = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}; e.update(SHIPMIRACLE_STATE=str(S), HOME=str(H), FAKE_PMSET=str(PMF), PATH=str(FB) + os.pathsep + e["PATH"])
subprocess.run(["bash", "-c", PRE + 'WS="%s"\n' % FW + BLOCK], env=e, capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
check("the rows only read: guard.json and events.log are byte-identical after a run", before == ((S / "guard.json").read_bytes(), (S / "events.log").read_bytes()) and sorted(p.name for p in S.iterdir()) == ["events.log", "guard.json"])

# source checks: wired in the Awake guard section, no pmset write, no secrets
src = (WS / "bin/doctor").read_text()
a = src.index('echo "Awake guard"'); b = src.index("# guardrows-begin"); nxt = src.index('echo "', a + 10)
check("rows sit in the Awake guard section (after its heading, before the next section heading)", a < b < nxt, (a, b, nxt))
check("block calls only 'pmset -g' (no disablesleep, no sudo)", "pmset -g " in BLOCK and "disablesleep" not in BLOCK and "sudo" not in BLOCK)
check("fixture HOME is under the temp folder", str(H).startswith(str(T)))
print("\nFAILED:" if fails else "\nALL PASS", fails); _s.exit(1 if fails else 0)
