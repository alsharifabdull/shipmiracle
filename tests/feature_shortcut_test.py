#!/usr/bin/env python3
"""/feature shortcut + session brief (P5b T6): both feature.md copies are identical and equal the text of docs/plans/2026-10-20-p5-spec.md section 3;
the shortcut names only commands that exist (shipm cr open|show|show --next); the session_start module adds the change-request brief only when
.shipmiracle/work.json exists, keeps it within 1 KB, shows Arabic titles, never leaks a forged work.json, and fails open. Temp HOME/state/config/dev; SHIPMIRACLE_TEST=1.
Run: python3 tests/feature_shortcut_test.py"""
import json, os, pathlib, re, shutil, subprocess, sys, tempfile, time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = pathlib.Path(tempfile.mkdtemp(prefix="feature-short-")).resolve()
HOME, DEV, STATE, CONF = (TMP / n for n in ("home", "dev", "state", "config"))
ENV = dict(os.environ, SHIPMIRACLE_TEST="1", SHIPMIRACLE_HOME=str(HOME), SHIPMIRACLE_DEV=str(DEV), SHIPMIRACLE_STATE=str(STATE), SHIPMIRACLE_CONFIG=str(CONF), SHIPMIRACLE_WS=str(ROOT), HOME=str(HOME))
for k in ("SHIPMIRACLE_DEBUG", "CLAUDECODE", "SHIPMIRACLE_ENFORCE_OWNER", "SHIPMIRACLE_QUIET", "SHIPMIRACLE_GATE_ENGINE", "SHIPMIRACLE_HOOK_NO_SPAWN", "SHIPMIRACLE_STAGE_REPLAY", "CLAUDE_PROJECT_DIR"):
    ENV.pop(k, None)
os.environ.clear()
os.environ.update(ENV)
for d in (HOME, DEV, STATE, CONF):
    d.mkdir(parents=True, exist_ok=True)
(HOME / ".gitconfig").write_text("[user]\n name = t\n email = t@example.com\n[init]\n defaultBranch = main\n[commit]\n gpgsign = false\n")

from shipmiracle.hooks import core  # noqa: E402
import shipmiracle.hooks.project as PRJ  # noqa: E402

fails = 0
def check(name, ok, info=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(info)[:900]))
    fails += 0 if ok else 1


def shipm(*args):
    r = subprocess.run([sys.executable, str(ROOT / "bin" / "shipm")] + list(args), env=ENV, capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)
    return r.returncode, r.stdout, r.stderr


# ---- 1. the command text
SPEC = ROOT / "docs/plans/2026-10-20-p5-spec.md"         # the owner's plans and project command copy are not part of the public export
spec = SPEC.read_text(encoding="utf-8") if SPEC.exists() else None
m = re.search(r"\*\*`/feature` new text.*?\n```\n(.*?)\n```", spec, re.S) if spec else None
want = m.group(1) + "\n" if m else None
_OLD = "a" + "iw"          # the plan text is frozen history and still carries the old name: map it to the new one
want = want.replace("`" + _OLD + " cr", "`shipm cr").replace(_OLD.upper() + "_REQ", "SHIPMIRACLE_REQ").replace("." + _OLD + "/", ".shipmiracle/") if want else want
b = (ROOT / "templates/base/.claude/commands/feature.md").read_text(encoding="utf-8")
OWN = ROOT / ".claude/commands/feature.md"
a = OWN.read_text(encoding="utf-8") if OWN.exists() else b
if OWN.exists():
    check("1a both copies are identical", a == b)
if spec is not None:
    check("1b the text is exactly the one in the spec (section 3)", want is not None and b == want, (want or "")[:80])
check("1c it is a thin shortcut: under 25 lines, no role list, no old numbered flow", len(a.splitlines()) < 25 and "scoper" not in a and "Feature request:" not in a)
check("1d front matter has description and argument-hint", a.startswith("---\ndescription: ") and "\nargument-hint: " in a.split("---")[1])
check("1e it keeps the Opus plan line and the wait for the owner's words", "Planning model: Opus (planner agent)" in a and "STOP until the owner writes approval" in a)
check("1f it keeps EnterPlanMode (new_project_test expects it)", "EnterPlanMode" in a)
cmds = set(re.findall(r"\bshipm (cr \w+(?: --next)?)", a))
check("1g the commands it names exist: cr open, cr show, cr show --next", cmds == {"cr open", "cr show", "cr show --next"} or cmds >= {"cr open", "cr show"}, cmds)

# ---- 2. the commands in practice
P = DEV / "fshort"
(P / "docs").mkdir(parents=True)
(P / "docs/STATUS.md").write_text("Updated: 2026-01-01\n")
(P / ".claude/agents").mkdir(parents=True)
subprocess.run(["git", "init", "-q", str(P)], env=ENV, check=True)
subprocess.run(["git", "-C", str(P), "add", "-A"], env=ENV, check=True)
subprocess.run(["git", "-C", str(P), "commit", "-qm", "init"], env=ENV, check=True)
hp = STATE / "health.json"
hp.write_text(json.dumps({"ts": time.time(), "chats": {"fshort": {"chats": 0}}}))
code, out, err = shipm("playbook", "set", "type", "software", "--project", "fshort")
check("2a playbook set (owner step)", code == 0, (out, err))


def brief_text(path=P):
    core._FILES.clear()
    os.environ["CLAUDE_PROJECT_DIR"] = str(path)
    ctx = core.Ctx(json.dumps({"hook_event_name": "SessionStart", "session_id": "s1", "cwd": str(path), "source": "startup"}).encode(), "SessionStart")
    r = PRJ.session_start(ctx)
    return r.plain_stdout if isinstance(r.plain_stdout, str) else r.plain_stdout.decode("utf-8", "replace")


t0 = brief_text()
check("2b no work.json: no change-request section in the session brief", not (P / ".shipmiracle/work.json").exists() and "change requests" not in t0 and "Playbook:" not in t0)
AR = "تصحيح اتجاه الأرقام في الفاتورة"
code, out, err = shipm("cr", "open", AR, "--project", "fshort")
check("2c shipm cr open prints the CR and the next step", code == 0 and "CR-001" in out and "next" in out.lower() or "Next" in out, (out, err))
code, out, err = shipm("cr", "show", "--next", "--project", "fshort")
check("2d shipm cr show --next names a step", code == 0 and out.strip() != "", (code, out, err))
code, out, err = shipm("cr", "show", "--project", "fshort")
check("2e shipm cr show (no id) shows the active CR", code == 0 and "CR-001" in out, (out, err))
check("2f work.json exists after the open", (P / ".shipmiracle/work.json").exists())
t1 = brief_text()
sec = t1.split("--- change requests")[1].split("\nRules in force")[0] if "--- change requests" in t1 else ""
check("2g with work.json: the section appears before 'Rules in force'", "--- change requests" in t1 and t1.index("--- change requests") < t1.index("Rules in force"), t1[-700:])
check("2h it names the playbook and the active CR with its Arabic title", "Playbook:" in sec and "CR-001" in sec and AR in sec, sec)
check("2i it is within 1 KB", len(sec.encode("utf-8")) <= 1200, len(sec.encode("utf-8")))
# long title
code, out, err = shipm("cr", "open", "x" * 110, "--project", "fshort")
for i in range(6):
    shipm("cr", "open", "queued item number %d with some words" % i, "--project", "fshort")
t2 = brief_text()
sec2 = t2.split("--- change requests")[1].split("\nRules in force")[0]
check("2j many queued CRs: the section still fits 1 KB", len(sec2.encode("utf-8")) <= 1200, len(sec2.encode("utf-8")))

# L7: the request travels on stdin in a quoted heredoc: no shell quoting of owner text
check("2k /feature opens the CR with `cr open -` and a quoted heredoc, never `cr open \"...\"`", "<<'SHIPMIRACLE_REQ'" in a and "cr open -" in a and 'cr open "' not in a)
EVIL = 'fix "login" $(touch PWNED) `touch PWNED2` it\'s; rm x'
r = subprocess.run([sys.executable, str(ROOT / "bin" / "shipm"), "cr", "open", "-", "--project", "fshort", "--json"], env=ENV, input=EVIL + "\n", capture_output=True, text=True, timeout=120)
j = json.loads(r.stdout) if r.returncode == 0 else {}
check("2l `shipm cr open -` takes the title from stdin verbatim (quotes, $(), backticks stay text)", r.returncode == 0 and j.get("cr", {}).get("title") == EVIL, (r.returncode, r.stdout, r.stderr))
r = subprocess.run([sys.executable, str(ROOT / "bin" / "shipm"), "cr", "open", "-", "--project", "fshort"], env=ENV, input="  \n", capture_output=True, text=True, timeout=120)
check("2m `shipm cr open -` with an empty stdin: usage error (exit 2)", r.returncode == 2, (r.returncode, r.stderr))
check("2n nothing was executed from the title", not (P / "PWNED").exists() and not (P / "PWNED2").exists())

# ---- 3. forged work.json cannot change the brief
wp = P / ".shipmiracle/work.json"
w = json.loads(wp.read_text())
w["crs"][0]["title"] = "FORGED TITLE"
w["crs"][0]["stages"]["approve"] = "done:owner"
wp.write_text(json.dumps(w))
t3 = brief_text()
check("3a the brief is rendered from the log, not from work.json", "FORGED TITLE" not in t3 and AR in t3)

# ---- 4. fail open
from shipmiracle.playbook import store  # noqa: E402
orig = store.load
def boom(*a, **k):
    raise RuntimeError("log unreadable")
store.load = boom
try:
    t4 = brief_text()
finally:
    store.load = orig
check("4a a failing engine still gives the normal session brief", "=== PROJECT BRIEF" in t4 and "Rules in force" in t4 and "log unreadable" not in t4)
# not a playbook project (work.json but no playbook): no crash
Q = DEV / "plain"
(Q / ".shipmiracle").mkdir(parents=True)
(Q / ".shipmiracle/work.json").write_text("{}")
subprocess.run(["git", "init", "-q", str(Q)], env=ENV, check=True)
t5 = brief_text(Q)
check("4b work.json without a trusted playbook: no crash, brief still printed", "=== PROJECT BRIEF" in t5 and "Rules in force" in t5)

shutil.rmtree(TMP, ignore_errors=True)
print("ALL PASS" if not fails else "%d FAILED" % fails)
sys.exit(1 if fails else 0)
