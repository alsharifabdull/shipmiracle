#!/usr/bin/env python3
"""bin/doctor event rows (review of P4-P6, M10 + m2): the red row for hook_module_error events, the red row for playbook.untrusted events
and the PUSH-BLOCKED row, each run from the marker-delimited lines of bin/doctor against a fixture state folder and a fixture HOME
(no real HOME, state or project is read). Run: python3 tests/doctor_rows_test.py"""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import shipmiracle_isolation; shipmiracle_isolation.apply_to_environ()   # test isolation: fresh HOME/SHIPMIRACLE_HOME/CONFIG/STATE unless already temp
import json, os, subprocess, sys, tempfile, time
from pathlib import Path
WS = Path(__file__).resolve().parent.parent
fails = 0
def check(n, c, info=""):
    global fails
    print(("PASS " if c else "FAIL ") + n + ("" if c else " :: " + str(info)[:600])); fails += 0 if c else 1
lines = (WS / "bin/doctor").read_text().splitlines()
def between(a, b):
    i = next(k for k, l in enumerate(lines) if l.startswith(a)); j = next(k for k, l in enumerate(lines) if l.startswith(b)); return "\n".join(lines[i + 1:j])
HOOKEV, PUSHB = between("# hookev-begin", "# hookev-end"), between("# pushblock-begin", "# pushblock-end")
T = Path(tempfile.mkdtemp()).resolve()
PRE = 'fail=0; ok() { printf "  ok   %s\\n" "$1"; }; bad() { printf "  FAIL %s\\n" "$1"; fail=1; }; warn() { printf "  warn %s\\n" "$1"; }\n'
def env(home, state):
    e = {k: v for k, v in os.environ.items() if k not in ("CLAUDECODE",)}
    e.update(SHIPMIRACLE_TEST="1", SHIPMIRACLE_STATE=str(state), HOME=str(home), GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1")
    return e
def run(block, home, state, ws):
    r = subprocess.run(["bash", "-c", PRE + 'WS="%s"\n' % ws + block + '\necho "fail=$fail"'], env=env(home, state), capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    return r.stdout + r.stderr
def events(state, evs):
    d = Path(state) / "v1"; d.mkdir(parents=True, exist_ok=True)
    (d / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in evs) + "{broken line\n")
now = int(time.time())
ev = lambda kind, ts=None, project=None: {"v": 1, "ts": now if ts is None else ts, "kind": kind, "project": project, "src": "hooks", "data": {}}

H = T / "home"; H.mkdir(); S = H / ".local/state/shipmiracle"; S.mkdir(parents=True)
FW = T / "ws"; FW.mkdir(); subprocess.run(["git", "init", "-q", str(FW)], check=True)

# no events file at all
o = run(HOOKEV, H, S, FW)
check("no events file: both rows ok, no FAIL", "  ok   hook dispatcher: no module errors" in o and "  ok   playbooks: no untrusted playbook" in o and "fail=0" in o, o)
# hook_module_error
events(S, [ev("hook_module_error"), ev("hook_module_error"), ev("hook_module_error", ts=now - 3 * 86400)])
o = run(HOOKEV, H, S, FW)
check("2 recent hook_module_error events (a 3-day-old one and a broken line ignored): red row names 2, fail=1", "  FAIL hook dispatcher: 2 module error(s) in the last 24 h" in o and "fail=1" in o and "playbooks: no untrusted" in o, o)
events(S, [ev("hook_module_error", ts=now - 3 * 86400)])
o = run(HOOKEV, H, S, FW)
check("only an old hook_module_error: row is ok", "  ok   hook dispatcher: no module errors" in o and "fail=0" in o, o)
# playbook.untrusted
events(S, [ev("playbook.untrusted", project="sample-app"), ev("playbook.untrusted", project="sample-app"), ev("playbook.untrusted", project="other"), ev("playbook.untrusted", project="old", ts=now - 5 * 86400)])
o = run(HOOKEV, H, S, FW)
check("3 recent playbook.untrusted events: red row with the count and project names, fail=1",
      "  FAIL playbook untrusted: 3 event(s) in the last 24 h (project: sample-app,other)" in o and "fail=1" in o and "  ok   hook dispatcher" in o, o)
check("the untrusted row tells the next step", "shipm playbook show --project" in o, o)
events(S, [ev("playbook.untrusted", project="x y; rm -rf")])
o = run(HOOKEV, H, S, FW)
check("a hostile project value is never echoed (name list stays '-')", "(project: -)" in o and "rm -rf" not in o, o)
events(S, [dict(ev("playbook.untrusted"), ts="bad")])
o = run(HOOKEV, H, S, FW)
check("a non-numeric ts is skipped (no crash, row ok)", "  ok   playbooks: no untrusted playbook" in o and "fail=0" in o, o)

# PUSH-BLOCKED
(H / "Developer").mkdir()
P = H / "Developer" / "proj"; subprocess.run(["git", "init", "-q", str(P)], check=True)
o = run(PUSHB, H, S, FW)
check("no PUSH-BLOCKED marker: no row, fail=0", "PUSH" not in o and "fail=0" in o, o)
(P / ".git/PUSH-BLOCKED").write_text("2026-10-20 gitleaks: 1 finding in HEAD\n")
o = run(PUSHB, H, S, FW)
check("PUSH-BLOCKED in a project under HOME/Developer: red row naming it, fail=1", "  FAIL push blocked by gitleaks in proj: 2026-10-20 gitleaks: 1 finding" in o and "fail=1" in o, o)
(P / ".git/PUSH-BLOCKED").unlink()
(FW / ".git/PUSH-BLOCKED").write_text("ws finding\n")
o = run(PUSHB, H, S, FW)
check("PUSH-BLOCKED in the workspace itself: red row too", "  FAIL push blocked by gitleaks in ws: ws finding" in o and "fail=1" in o, o)
# review: the admin-step row must not execute pmset (owner-approved 21 Oct): sudo -n -l only asks whether the rule is allowed
src = (WS / "bin/doctor").read_text()
check("doctor never runs pmset through sudo: only the read-only 'sudo -n -l' probe", "sudo -n -l /usr/bin/pmset" in src and "sudo -n /usr/bin/pmset" not in src)
# 21 Oct 2026: registered hook scripts that are gone (gate OFF) or sit in a temp folder
sys.path.insert(0, str(WS))
from shipmiracle.hooks import spec  # noqa: E402
HS = between("# hookscripts-begin", "# hookscripts-end")
(H / ".claude").mkdir(exist_ok=True)
exist = T / "tmpws" / "hooks"; exist.mkdir(parents=True); (exist / "shipm-hook").write_text("x")
reg = lambda pre, ev: {"hooks": [{"type": "command", "command": spec.dispatcher_command(pre, ev, (), H)}]}
(H / ".claude" / "settings.json").write_text(json.dumps({"hooks": {"Stop": [reg("$HOME/Developer/gone/hooks/", "Stop"), reg(str(exist) + "/", "Stop"), {"hooks": [{"type": "command", "command": "/opt/foreign.sh"}]}]}}))
o = run(HS, H, S, WS)
check("doctor: a registered Shipmiracle hook whose script file is missing -> FAIL row 'hook script missing: gate OFF', names repair command", "  FAIL hook script missing: gate OFF (Stop" in o and "gone/hooks/shipm-hook" in o and "shipm sync --repair-hooks" in o and "fail=1" in o, o)
check("doctor: a registered Shipmiracle hook script in a temp folder -> FAIL row 'hook script in a temp folder'", "  FAIL hook script in a temp folder (Stop" in o and "tmpws/hooks/shipm-hook" in o, o)
check("doctor: the foreign hook is not mentioned", "foreign.sh" not in o)
(H / ".claude" / "settings.json").write_text(json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "/opt/foreign.sh"}]}]}}))
o = run(HS, H, S, WS)
check("doctor: no Shipmiracle hook problem -> one ok row, fail=0", "  ok   registered Shipmiracle hook scripts exist" in o and "fail=0" in o, o)
(H / ".claude" / "settings.json").unlink()
o = run(HS, H, S, WS)
check("doctor: no settings file -> ok row (nothing registered)", "  ok   registered Shipmiracle hook scripts exist" in o and "fail=0" in o, o)
# stray processes row
SR = between("# strays-begin", "# strays-end")
o = run(SR, H, S, FW)
check("strays: no health.json -> ok row", "  ok   no stray automation browser" in o, o)
(S / "health.json").write_text(json.dumps({"items": [{"kind": "stray_browser"}, {"kind": "stray_browser"}, {"kind": "stray_testrun"}, {"kind": "idle_session"}]}))
o = run(SR, H, S, FW)
check("strays: items in health.json -> warn row with both counts", "  warn stray processes: 2 automation browser(s) and 1 orphaned test run(s)" in o, o)
# stale worktree records
WT = between("# worktrees-begin", "# worktrees-end")
GENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t", GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1")
WR = T / "wtrepo"; WR.mkdir(); subprocess.run(["git", "init", "-q", "-b", "main", str(WR)], check=True, env=GENV)
(WR / "a").write_text("x"); subprocess.run(["git", "-C", str(WR), "add", "-A"], check=True, env=GENV); subprocess.run(["git", "-C", str(WR), "commit", "-q", "-m", "i"], check=True, env=GENV)
o = run(WT, H, S, WR)
check("worktrees: none -> ok row", "  ok   stale worktree records: none" in o and "fail=0" in o, o)
subprocess.run(["git", "-C", str(WR), "worktree", "add", "-q", "--detach", str(T / "snapwt")], check=True, env=GENV)
o = run(WT, H, S, WR)
check("worktrees: a worktree under a temp folder -> warn row naming the path and 'git worktree prune'", "  warn stale worktree records:" in o and "worktree under a temp folder" in o and "snapwt" in o and "git worktree prune" in o, o)
import shutil; shutil.rmtree(T / "snapwt")
o = run(WT, H, S, WR)
check("worktrees: a dangling record (folder gone) -> warn row 'dangling record'", "dangling record" in o and "snapwt" in o, o)
subprocess.run(["git", "-C", str(WR), "worktree", "prune"], check=True, env=GENV)
o = run(WT, H, S, WR)
check("worktrees: after git worktree prune the row is ok again", "  ok   stale worktree records: none" in o, o)
# Remote Control row (27 Oct): on = ok, off = ok with the opt-in hint; no dotfiles lookup, never a warn or FAIL
RC = between("# remote-begin", "# remote-end")
RW = T / "rcws"; (RW / "dotfiles").mkdir(parents=True)
RH = T / "rchome"; (RH / ".claude").mkdir(parents=True)
rc_run = lambda: run('s="%s/.claude/settings.json"\n' % RH + RC, RH, S, RW)
o = rc_run()
check("remote: no settings file and no dotfiles: ok 'off (default)', no warn, fail=0", "  ok   Remote Control off (default" in o and "warn" not in o and "fail=0" in o, o)
(RH / ".claude" / "settings.json").write_text('{\n  "remoteControlAtStartup": true\n}\n')
o = rc_run()
check("remote: on in the settings file: ok", "  ok   Remote Control on at startup" in o and "fail=0" in o, o)
(RH / ".claude" / "settings.json").write_text('{"model": "x"}\n')
(RW / "dotfiles" / "claude-settings.json").write_text('{\n  "remoteControlAtStartup": true\n}\n')
o = rc_run()
check("remote: off even if a dotfiles snapshot says true: ok with the opt-in hint, no warn, fail=0 (no dotfiles lookup)", "  ok   Remote Control off (default; opt in with: shipm init --step remote-control)" in o and "warn" not in o and "fail=0" in o, o)
SRC = "\n".join(lines)
check("doctor: no 'drifted from dotfiles' row and no reference to dotfiles/claude-settings.json left", "drifted from dotfiles" not in SRC and "dotfiles/claude-settings.json" not in SRC)
check("dotfiles/claude-settings.json is gone from the repo", not (WS / "dotfiles/claude-settings.json").exists())
if (WS / "dotfiles/vscode-keybindings.json").is_file():
    kb = json.loads((WS / "dotfiles/vscode-keybindings.json").read_text())
    check("keybindings parse as JSON: ctrl+alt+d -> shipmiracle.check, ctrl+alt+n -> shipmiracle.newProject", {k["key"]: k["command"] for k in kb if k["key"] in ("ctrl+alt+d", "ctrl+alt+n")} == {"ctrl+alt+d": "shipmiracle.check", "ctrl+alt+n": "shipmiracle.newProject"}, kb)
else:       # exported tree: dotfiles/ is private and not shipped
    print("SKIP keybindings check (dotfiles/vscode-keybindings.json is not in this tree)")
# hook rows (27 Oct): dispatcher v1 checks every event of table T (+ StatusLine) for `hooks/shipm-hook <Event>`; legacy keeps the old script loop
HK = between("# hooks-begin", "# hooks-end")
import ast, re as _re
TEV = sorted(set(ast.literal_eval(_re.search(r"^T = (\{.*\})\s*$", (WS / "hooks/shipm-hook").read_text(), _re.M).group(1))) | {"StatusLine"})
HH = T / "hkhome"; (HH / ".claude").mkdir(parents=True)
def hk_run(mode, settings):
    cfg = T / ("hkcfg-" + mode); cfg.mkdir(exist_ok=True)
    e = env(HH, S); e.update(SHIPMIRACLE_CONFIG=str(cfg), SHIPMIRACLE_HOME=str(HH), CLAUDE_CONFIG_DIR=str(HH / ".claude"), SHIPMIRACLE_WS=str(WS))
    if mode == "v1":
        r = subprocess.run([sys.executable, str(WS / "bin/shipm"), "config", "set", "hooks.dispatcher", "v1"], env=e, capture_output=True, text=True, stdin=subprocess.DEVNULL)
        assert r.returncode == 0, r.stdout + r.stderr
    (HH / ".claude" / "settings.json").write_text(json.dumps(settings))
    r = subprocess.run(["bash", "-c", PRE + 'WS="%s"\n' % WS + HK + '\necho "fail=$fail"'], env=e, capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    return r.stdout + r.stderr
full = {"hooks": {ev: [{"hooks": [{"type": "command", "command": "/bin/sh -c 'wrap' shipm-gate %s/hooks/shipm-hook %s" % (WS, ev)}]}] for ev in TEV if ev != "StatusLine"}, "statusLine": {"type": "command", "command": "%s/hooks/shipm-hook StatusLine" % WS}}
o = hk_run("v1", full)
check("hooks v1: all events registered (incl. StatusLine) -> 0 FAIL, fail=0", "FAIL" not in o and "fail=0" in o and o.count("  ok   hook ") == len(TEV), o)
part = json.loads(json.dumps(full)); del part["hooks"]["Stop"]; part["statusLine"]["command"] = "x"
o = hk_run("v1", part)
check("hooks v1: Stop (not confused with StopFailure) and StatusLine missing -> exactly those two FAIL rows with the repair hint", o.count("  FAIL ") == 2 and "hook Stop not registered" in o and "hook StatusLine not registered" in o and "shipm sync --repair-hooks" in o and "fail=1" in o, o)
o = hk_run("v1", {})
check("hooks v1: no settings -> one FAIL row per event", o.count("  FAIL ") == len(TEV), o)
o = hk_run("legacy", {})
check("hooks legacy: a missing legacy hook still FAILs", "  FAIL global hook keep-awake missing" in o and "fail=1" in o, o)
check("plan-capture row is skipped under v1 and kept for legacy", 'if [[ "$HOOKMODE" == v1 ]]; then :' in SRC and "plan-capture status line missing" in SRC)
# the fixture never touched the real home
check("fixture HOME is under the temp folder", str(H).startswith(str(T)))
print("\nFAILED:" if fails else "\nALL PASS", fails); sys.exit(1 if fails else 0)
