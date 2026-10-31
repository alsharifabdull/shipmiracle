#!/usr/bin/env python3
"""bin/daily: log location/modes/retention (logdir markers) and the injection-proof notification (notify markers, stub osascript recording argv).
Run: python3 tests/daily_test.py"""
import json, os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import shipmiracle_isolation; shipmiracle_isolation.apply_to_environ(); shipmiracle_isolation.mac_platform_off_mac()   # test isolation: fresh HOME/SHIPMIRACLE_HOME/CONFIG/STATE unless already temp
import os, stat, subprocess, sys, tempfile, time
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
fails = 0
def check(n, c, info=""):
    global fails
    print(("PASS " if c else "FAIL ") + n + ("" if c else " :: " + str(info))); fails += 0 if c else 1
src = (WS / "bin/daily").read_text()
def between(a, b):
    lines = src.splitlines(); i = next(k for k, l in enumerate(lines) if l.startswith(a)); j = next(k for k, l in enumerate(lines) if l.startswith(b))
    return "\n".join(lines[i + 1:j])
T = Path(tempfile.mkdtemp()).resolve()

# ---- log location, modes, retention, fallback
logdir_body = between("# logdir-begin", "# logdir-end"); prune_body = between("# prune-begin", "# prune-end")
def run_logdir(state, ws, env_extra=None, test=True, home=None):
    env = dict(os.environ, HOME=str(home or (T / "nohome")))
    env.pop("SHIPMIRACLE_TEST", None); env.pop("SHIPMIRACLE_STATE", None)
    if test: env.update(SHIPMIRACLE_TEST="1", SHIPMIRACLE_STATE=str(state))
    env.update(env_extra or {})
    script = 'set -uo pipefail\nWS="%s"\n%s\n[[ $LOGFAIL -eq 1 ]] || chmod 600 "$log" 2>/dev/null\n%s\necho "$log|$LOGFAIL|$LOGDIR"\n' % (ws, logdir_body, prune_body)
    r = subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True)
    last = r.stdout.strip().split("\n")[-1] if r.stdout.strip() else "||"
    return r, last.split("|")
WSX = T / "wsx"; (WSX / "reports").mkdir(parents=True)
S = T / "state"; S.mkdir(); logs = S / "v1/logs"; logs.mkdir(parents=True)
for i in range(20):
    f = logs / ("daily-2026-09-%02d.log" % (i + 1)); f.write_text("x"); os.utime(f, (1000 + i, 1000 + i))
    g = WSX / "reports" / ("daily-2026-08-%02d.log" % (i + 1)); g.write_text("x"); os.utime(g, (1000 + i, 1000 + i))
r, (log, fail, ld) = run_logdir(S, WSX)
log = Path(log)
check("log goes to <state>/v1/logs/daily-<date>.log", log.parent == S / "v1/logs" and log.exists() and fail == "0", r)
check("log folder mode 700 and file mode 600", stat.S_IMODE(os.stat(log.parent).st_mode) == 0o700 and stat.S_IMODE(os.stat(log).st_mode) == 0o600)
check("keeps 14 files in the log folder (oldest removed)", len(list(log.parent.glob("daily-*.log"))) == 14 and not (log.parent / "daily-2026-09-01.log").exists() and (log.parent / "daily-2026-09-20.log").exists())
check("old reports/daily-*.log files are pruned with the same 14-file retention", len(list((WSX / "reports").glob("daily-*.log"))) == 14 and not (WSX / "reports/daily-2026-08-01.log").exists() and (WSX / "reports/daily-2026-08-20.log").exists())
check("nothing is written to reports/ in the repo while the state folder works", not any(p.name == log.name for p in (WSX / "reports").iterdir()))
# launchd creates launchd-daily.log itself (mode 644, its own umask): the run tightens it to 600 and never follows a symlink
lf = S / "v1/logs/launchd-daily.log"; lf.write_text("from launchd\n"); os.chmod(lf, 0o644)
r, _x = run_logdir(S, WSX)
check("launchd-daily.log created 0644 by launchd is chmod-ed to 0600 by the run (content kept)", stat.S_IMODE(os.stat(lf).st_mode) == 0o600 and lf.read_text() == "from launchd\n", r)
SL = T / "s-lnk"; (SL / "v1/logs").mkdir(parents=True); linked = T / "linked-target.txt"; linked.write_text("x"); os.chmod(linked, 0o644)
os.symlink(linked, SL / "v1/logs/launchd-daily.log")
r, _x = run_logdir(SL, WSX)
check("a symlinked launchd-daily.log is not followed (target mode untouched)", stat.S_IMODE(os.stat(linked).st_mode) == 0o644, r)
S2 = T / "fresh" / "deeper"
r, (log2, fail2, _) = run_logdir(S2, WSX)
check("fresh state folder: every created level (state, v1, logs) is 0700", all(stat.S_IMODE(os.stat(x).st_mode) == 0o700 for x in (S2, S2 / "v1", S2 / "v1/logs")) and fail2 == "0", r)
# SHIPMIRACLE_STATE is ignored unless SHIPMIRACLE_TEST=1
H3 = T / "h3"; H3.mkdir(); S3 = T / "ignored"
r, (log3, fail3, _) = run_logdir(S3, WSX, test=False, env_extra={"SHIPMIRACLE_STATE": str(S3)}, home=H3)
check("SHIPMIRACLE_STATE without SHIPMIRACLE_TEST=1 is ignored (log goes under $HOME/.local/state/shipmiracle)", not S3.exists() and log3.startswith(str(H3 / ".local/state/shipmiracle/v1/logs")), (r, log3))
# symlinked log folder -> fallback to reports/
S4 = T / "s4"; (S4 / "v1").mkdir(parents=True); target = T / "elsewhere"; target.mkdir(); os.symlink(target, S4 / "v1/logs")
WS4 = T / "ws4"; (WS4 / "reports").mkdir(parents=True)
r, (log4, fail4, ld4) = run_logdir(S4, WS4)
check("symlinked logs folder is refused: falls back to <workspace>/reports and nothing is written through the link", log4.startswith(str(WS4 / "reports")) and fail4 == "0" and not list(target.iterdir()), (r, log4))
# symlinked v1 folder
S5 = T / "s5"; S5.mkdir(); os.symlink(target, S5 / "v1")
r, (log5, fail5, _) = run_logdir(S5, WS4)
check("symlinked v1 folder is refused too", log5.startswith(str(WS4 / "reports")) and not list(target.iterdir()), (r, log5))
# unwritable folder
S6 = T / "s6"; (S6 / "v1/logs").mkdir(parents=True); os.chmod(S6 / "v1/logs", 0o500)
r, (log6, fail6, _) = run_logdir(S6, WS4)
check("unwritable logs folder falls back to reports/", log6.startswith(str(WS4 / "reports")) and fail6 == "0", (r, log6)); os.chmod(S6 / "v1/logs", 0o700)
# nowhere to write: the run goes on, flagged
S7 = T / "s7"; (S7 / "v1/logs").mkdir(parents=True); os.chmod(S7 / "v1/logs", 0o500)
WS7 = T / "ws7"; WS7.mkdir(); (WS7 / "reports").write_text("a file, not a folder")
r, (log7, fail7, _) = run_logdir(S7, WS7)
check("no writable location at all: LOGFAIL=1 and the log is /dev/null (the run is not skipped)", log7 == "/dev/null" and fail7 == "1", (r, log7, fail7)); os.chmod(S7 / "v1/logs", 0o700)
tail = src[src.index("# prune-end"):]
check("a failed log write never prints 'Health: 0 problems': the message says unknown", 'LOGFAIL -eq 1 ]]; then msg="Health: unknown' in tail and tail.index("Health: unknown") < tail.index("Health: $fails"), tail[:300])
check("the maintenance block is not conditional on the log", src.index("# logdir-end") < src.index("== Claude plugins") < src.index("} > \"$log\" 2>&1"))

# ---- notification
notify = between("# notify-begin", "# notify-end")
rec = T / "osascript"; calls = T / "argv.bin"
rec.write_text('#!/bin/sh\nfor a in "$@"; do printf "%s\\0" "$a"; done >> ' + str(calls) + '\nprintf "\\0\\0END\\0" >> ' + str(calls) + '\n'); rec.chmod(0o755)
W2 = T / "ws"; (W2 / "config").mkdir(parents=True)
os.symlink(str(WS / "shipmiracle"), str(W2 / "shipmiracle"))             # the block runs `python3 -m shipmiracle.platform` from the workspace
CFGD = Path(os.environ["SHIPMIRACLE_CONFIG"]); CFGD.mkdir(parents=True, exist_ok=True)
def fire(msg, mac, pref=None, osa=True):
    (W2 / "config/notifications.json").write_text('{"mac": %s}' % ("true" if mac else "false"))
    (CFGD / "config.json").write_text(json.dumps({"prefs.notify": pref} if pref else {}))
    if calls.exists(): calls.unlink()
    env = dict(os.environ, SHIPMIRACLE_TEST="1")
    env.pop("SHIPMIRACLE_OSASCRIPT", None)
    if osa: env["SHIPMIRACLE_OSASCRIPT"] = str(rec)
    subprocess.run(["bash", "-c", 'set -uo pipefail\nWS="$1"; msg="$2"\n' + notify, "x", str(W2), msg], env=env, timeout=30)
    return calls.read_bytes().split(b"\0") if calls.exists() else None
nasty = 'He said "hi" \\ back\\slash $(touch pwned) `id` \'q\'\nline two; end run'     # short and relative: the message is cut at 200 characters, so it must not depend on how long the temp path is
a = fire(nasty, True)
check("switch on: osascript called once with the 4 script parts, then the message, then the title as ARGUMENTS (newlines become spaces)",
      a is not None and a[0] == b"-e" and a[1] == b"on run argv" and a[3] == b"display notification (item 1 of argv) with title (item 2 of argv)" and a[5] == b"end run" and a[6].decode() == " ".join(nasty.split()) and a[7] == b"Shipmiracle daily", a)
check("the message is not spliced into any script part", all(b"touch" not in x for x in a[:6]) and not (T / "pwned").exists() and not (W2 / "pwned").exists() and not Path("pwned").exists(), a)
check("switch off: osascript is not called", fire("hello", False) is None)
check("prefs.notify=none wins over the old switch mac:true: no notification", fire("hello", True, pref="none") is None)
check("prefs.notify=vscode wins over the old switch mac:true: no notification", fire("hello", True, pref="vscode") is None)
check("prefs.notify=system turns it on with the old switch off", fire("hello", False, pref="system") is not None)
check("under SHIPMIRACLE_TEST=1 without the recorder the real /usr/bin/osascript is never reached", fire("hello", True, osa=False) is None)
(W2 / "config/notifications.json").unlink()
(CFGD / "config.json").write_text("{}")
if calls.exists(): calls.unlink()
subprocess.run(["bash", "-c", 'set -uo pipefail\nWS="$1"; msg="m"\n' + notify, "x", str(W2)], env=dict(os.environ, SHIPMIRACLE_TEST="1", SHIPMIRACLE_OSASCRIPT=str(rec)))
check("no config file: osascript is not called", not calls.exists())
# the real osascript accepts the argument form (macOS only, a real dialog is never shown: compile only)
if sys.platform == "darwin" and Path("/usr/bin/osacompile").exists():
    out = T / "x.scpt"
    r = subprocess.run(["/usr/bin/osacompile", "-o", str(out), "-e", "on run argv", "-e", 'display notification (item 1 of argv) with title (item 2 of argv)', "-e", "end run"], capture_output=True, text=True)
    check("the script parts compile with the real AppleScript compiler", r.returncode == 0, r.stderr)
# review m3: the digest step runs `shipm report digest --write` and is fail-soft (a failing digest never stops the later steps)
dline = next((l.strip() for l in src.splitlines() if "== Report digest" in l), "")
check("bin/daily has the Report digest step calling shipm report digest --write", '"$WS/bin/shipm" report digest --write' in dline and "||" in dline, dline)
FW = T / "fakews"; (FW / "bin").mkdir(parents=True)
(FW / "bin/shipm").write_text('#!/bin/bash\necho "ARGS: $*" >> "$0.calls"\nexit ${FAKE_RC:-0}\n'); os.chmod(FW / "bin/shipm", 0o755)
for rc in ("0", "3"):
    r = subprocess.run(["bash", "-c", 'set -uo pipefail\nWS="$1"\n{\n' + dline + '\necho NEXT-STEP-RAN\n}', "x", str(FW)], env=dict(os.environ, FAKE_RC=rc), capture_output=True, text=True)
    check("digest step with Shipmiracle exit %s: later steps still run%s" % (rc, " and the failure is named" if rc != "0" else ""), "NEXT-STEP-RAN" in r.stdout and (rc == "0" or "report digest failed (exit 3)" in r.stdout), r.stdout + r.stderr)
check("Shipmiracle was called with: report digest --write", "ARGS: report digest --write" in (FW / "bin" / "shipm.calls").read_text())
# G2: the weekly Tidy step: host-busy check, fail-soft, never changes the exit code or the Health line (the real bin/daily, every helper replaced by a stub)
tline = [l for l in src.splitlines() if "tidy --all --write --weekly" in l]
check("bin/daily has the Tidy step: host check (shipm-watch host --heavy-ok), then shipm tidy --all --write --weekly with a fail-soft message", len(tline) == 1 and 'shipm-watch" host --heavy-ok' in src and "||" in tline[0] and "== Tidy (weekly, read-only" in src, tline)
check("the Tidy step runs before Health, inside the logged block", src.index("== Tidy (weekly") < src.index('echo; echo "== Health"') < src.index('} > "$log" 2>&1'))
def fake_daily(tidy_rc, host_rc, tag, sleep=0, limit=None, promote=None, climit=None):
    ws = T / ("fd-" + tag); (ws / "bin").mkdir(parents=True); (ws / "bin/daily").write_text(src); os.chmod(ws / "bin/daily", 0o755)
    calls = ws / "calls.txt"
    for n in ("plugins-update", "skills-sync", "promote-agent", "flow-report", "gate-deny"):
        (ws / "bin" / n).write_text("#!/bin/bash\necho stub-%s\n" % n); os.chmod(ws / "bin" / n, 0o755)
    if promote: (ws / "bin/promote-agent").write_text(promote); os.chmod(ws / "bin/promote-agent", 0o755)
    (ws / "bin/shipm").write_text('#!/bin/bash\necho "shipm $*" >> %s\nif [[ "$1 $2" == "skills found" ]]; then echo "found-stub"; exit ${FAKE_SKILLS_RC:-0}; fi\nif [[ "$1" == tidy ]]; then sleep %s; echo "tidy boom"; exit %s; fi\nexit 0\n' % (calls, sleep, tidy_rc)); os.chmod(ws / "bin/shipm", 0o755)
    (ws / "bin/shipm-watch").write_text('#!/bin/bash\necho "watch $*" >> %s\nexit %s\n' % (calls, host_rc)); os.chmod(ws / "bin/shipm-watch", 0o755)
    (ws / "bin/doctor").write_text("#!/bin/bash\necho 'doctor ran'\nexit 0\n"); os.chmod(ws / "bin/doctor", 0o755)
    st = T / ("fds-" + tag); st.mkdir()
    cbin = ws / "cbin"; cbin.mkdir(); (cbin / "code").write_text("#!/bin/bash\nexit 0\n"); os.chmod(cbin / "code", 0o755)
    env = dict(os.environ, SHIPMIRACLE_TEST="1", SHIPMIRACLE_STATE=str(st), HOME=str(T / "nohome"), PATH=str(cbin) + ":" + os.environ["PATH"], **({"SHIPMIRACLE_TIDY_LIMIT": str(limit)} if limit else {}), **({"SHIPMIRACLE_COUNTER_LIMIT": str(climit)} if climit else {}))
    r = subprocess.run(["bash", str(ws / "bin/daily")], env=env, capture_output=True, text=True, timeout=120)
    return r, (st / "v1/logs" / next(iter(os.listdir(st / "v1/logs")))).read_text(), (calls.read_text() if calls.exists() else "")
r0, log0, c0 = fake_daily(0, 0, "ok")
r3, log3, c3 = fake_daily(3, 0, "bad")
check("daily has the section 'Skills and plugins found, not approved' running shipm skills found --short, after plugins", "shipm skills found --short" in c0 and "== Skills and plugins found, not approved\nfound-stub" in log0 and log0.index("== Claude plugins") < log0.index("== Skills and plugins found"), (c0, log0))
os.environ["FAKE_SKILLS_RC"] = "2"; rs, logs_, cs = fake_daily(0, 0, "nofound"); del os.environ["FAKE_SKILLS_RC"]
check("missing/failing 'skills found': one note line, daily does not abort (exit 0, later steps ran)", rs.returncode == 0 and "note: 'shipm skills found --short' not available (exit 2); skipped" in logs_ and "doctor ran" in logs_ and "found-stub" not in logs_, (rs, logs_))
check("tidy ok: the step ran with the right arguments after the host check", "watch host --heavy-ok" in c0 and "shipm tidy --all --write --weekly" in c0 and "doctor ran" in log0, (c0, log0))
check("tidy exit 3: daily exit code 0, the failure is named, Health step still ran", r3.returncode == 0 and "tidy skipped or failed (exit 3): the other steps still ran" in log3 and "doctor ran" in log3, (r3, log3))
check("a failing tidy does not change the 'Health: N problems' line", r0.stdout.strip().split("Report:")[0] == r3.stdout.strip().split("Report:")[0] and "Health: 0 problems, 0 warnings" in r3.stdout, (r0.stdout, r3.stdout))
rb, logb, cb = fake_daily(0, 1, "busy")
rh, logh, ch = fake_daily(0, 2, "hostfail")
check("host check exit 2 (not 1): tidy not run, the log says 'host check failed (exit 2)', Health still ran", rh.returncode == 0 and "shipm tidy" not in ch and "host check failed (exit 2)" in logh and "tidy skipped: the Mac is busy" not in logh and "doctor ran" in logh, (ch, logh))
rt, logt, ct = fake_daily(0, 0, "hang", sleep=30, limit=1)
check("a hung tidy is killed at the wall-clock limit: 'tidy timed out', daily exit 0, Health still ran, within seconds", rt.returncode == 0 and "tidy timed out after 1 s" in logt and "doctor ran" in logt and "tidy boom" not in logt, (rt, logt))
rl, logl, cl = fake_daily(0, 0, "limit-ignored", sleep=0, limit=None)
check("the limit seam is honoured only with SHIPMIRACLE_TEST=1 (default 420 s in the script)", "tlimit=420" in src and 'SHIPMIRACLE_TEST:-}" == 1' in src and "tidy boom" in logl)
check("busy host: tidy is not run, one line says so, daily exit 0, Health still ran", rb.returncode == 0 and "shipm tidy" not in cb and "tidy skipped: the Mac is busy" in logb and "doctor ran" in logb, (cb, logb))
# G8: the promotion counter is fail-soft, bounded, and its data can never change the Health counts
healthy = r0.stdout.strip().split("Report:")[0]
crash = '#!/bin/bash\necho "Traceback: boom FAIL x warn y" >&2\necho " FAIL partial output" >&2\nexit 1\n'
rg, logg, cg = fake_daily(0, 0, "counter-crash", promote=crash)
check("a crashing promotion counter: daily exit 0, one plain 'unavailable' line, Health line identical to the healthy run", rg.returncode == 0 and "candidate list unavailable" in logg and rg.stdout.strip().split("Report:")[0] == healthy and "Health: 0 problems, 0 warnings" in rg.stdout, (rg, logg))
check("a crashing counter still lets the later steps run (Team flow, Health)", "stub-flow-report" in logg and "doctor ran" in logg, logg)
loud = '#!/bin/bash\necho "x FAIL y"\necho "a warn b"\nexit 3\n'
rl2, logl2, _ = fake_daily(0, 0, "counter-loud-exit3", promote=loud)
check("a failing counter's STDOUT does not reach the log (exit 3 with 'x FAIL y'): Health unchanged", rl2.returncode == 0 and "x FAIL y" not in logl2 and "a warn b" not in logl2 and "candidate list unavailable" in logl2 and rl2.stdout.strip().split("Report:")[0] == healthy, (rl2, logl2))
okline = '#!/bin/bash\n[[ "$1" == --report ]] || exit 2\necho "stub table"\necho "Borrowed items: 1. No promotion candidates yet."\n'
ro, logo, co = fake_daily(0, 0, "counter-ok", promote=okline)
check("a counter that works is printed (table, then the summary line) in the report", "stub table\nBorrowed items: 1. No promotion candidates yet." in logo and ro.stdout.strip().split("Report:")[0] == healthy, logo)
fakedata = '#!/bin/bash\necho "name q FAIL x warn y FAIL"\necho " FAIL second"\n'
rd2, logd2, _ = fake_daily(0, 0, "counter-data", promote=fakedata)
check("data strings with ' FAIL ' / ' warn ' in a SUCCESSFUL counter run are broken (F*AIL, w*arn): Health still 0 problems, 0 warnings", rd2.stdout.strip().split("Report:")[0] == healthy and "F*AIL" in logd2 and "w*arn" in logd2 and "Health: 0 problems, 0 warnings" in rd2.stdout, (rd2.stdout, logd2))
rempty, logempty, _ = fake_daily(0, 0, "counter-empty", promote='#!/bin/bash\n')
check("an empty counter output is harmless", rempty.returncode == 0 and "doctor ran" in logempty)
hang = '#!/bin/bash\nsleep 30\necho late\n'
t0 = time.time(); rh2, logh2, _ = fake_daily(0, 0, "counter-hang", promote=hang, climit=1)
check("a hung counter is killed at its limit: 'timed out' line, daily exit 0, Health unchanged, within seconds", rh2.returncode == 0 and "candidate list timed out after 1 s" in logh2 and "late" not in logh2 and rh2.stdout.strip().split("Report:")[0] == healthy and time.time() - t0 < 25, (rh2, logh2, time.time() - t0))
check("the counter limit seam is honoured only with SHIPMIRACLE_TEST=1 (default 60 s)", "climit=60" in src and 'SHIPMIRACLE_TEST:-}" == 1 && "${SHIPMIRACLE_COUNTER_LIMIT' in src)
check("the counter runs once per daily (one --report call, no separate --candidates / --daily-line calls)", src.count("--report") >= 1 and '"$WS/bin/promote-agent" --candidates' not in src and "--daily-line" not in src.replace("# ", ""), src)
check("bash syntax of bin/daily", subprocess.run(["bash", "-n", str(WS / "bin/daily")]).returncode == 0)
print("\nFAILED:" if fails else "\nALL PASS", fails); sys.exit(1 if fails else 0)
