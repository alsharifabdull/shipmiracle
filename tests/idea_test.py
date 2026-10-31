"""bin/idea in a sandbox: temp git projects, temp state. Nothing real is touched. Run: python3 tests/idea_test.py"""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import shipmiracle_isolation; shipmiracle_isolation.apply_to_environ(); shipmiracle_isolation.mac_platform_off_mac()   # test isolation: fresh HOME/SHIPMIRACLE_HOME/CONFIG/STATE unless already temp
import json, os, pathlib, subprocess, sys, tempfile, time
ws = pathlib.Path(__file__).resolve().parent.parent
T = pathlib.Path(tempfile.mkdtemp()); HOME = T / "home"; DEV = HOME / "Developer"; STATE = HOME / ".local/state/shipmiracle"; WS = T / "ws"
for d in (DEV, STATE, WS / "config"): d.mkdir(parents=True)
GENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
ENV = dict(GENV, SHIPMIRACLE_HOME=str(HOME), SHIPMIRACLE_DEV=str(DEV), SHIPMIRACLE_STATE=str(STATE), SHIPMIRACLE_WS=str(WS), SHIPMIRACLE_TEST="1")
def git(d, *a): return subprocess.run(["git", "-C", str(d), *a], capture_output=True, text=True, env=GENV).stdout
def mk(name):
    d = DEV / name; subprocess.run(["git", "init", "-q", "-b", "main", str(d)], env=GENV); (d / "a.txt").write_text("x\n")
    git(d, "add", "-A"); git(d, "commit", "-q", "-m", "init"); return d
def bl(*a, cwd=None):
    r = subprocess.run([str(ws / "bin/idea"), *a], capture_output=True, text=True, env=ENV, cwd=cwd); return (r.stdout + r.stderr), r.returncode
fails = []
def check(n, c, info=""):
    print(("PASS " if c else "FAIL ") + n, "" if c else info)
    if not c: fails.append(n)

p1, ideas = mk("p1"), mk("ideas"); mk("held")
(WS / "config/ci-hold.txt").write_text("# x\nheld\n")
# add / list / commit scope
(p1 / "half-done.txt").write_text("work in progress\n")
o, rc = bl("-p", "p1", "add", "Export report as PDF", "#export", "#report"); check("add works", rc == 0 and "F1" in o, o)
o, _ = bl("-p", "p1", "add", "Dark mode"); check("second id is F2", "F2" in o, o)
check("commit contains only docs/FEATURE-IDEAS.md", git(p1, "show", "--stat", "--format=%s", "HEAD").strip().splitlines()[0] == "ideas: add F2" and "half-done" not in git(p1, "show", "--name-only", "--format=", "HEAD"), git(p1, "show", "--stat", "HEAD"))
check("the chat's half-done file stays uncommitted", "half-done.txt" in git(p1, "status", "--porcelain"))
o, _ = bl("-p", "p1", "list"); check("list shows both open items", "F1" in o and "F2" in o and "PDF" in o, o)
# hand / phone edits: id-less line, duplicate id
f = p1 / "docs/FEATURE-IDEAS.md"; t = f.read_text()
f.write_text(t.replace("## Evaluated", "- [ ] Offline mode #offline\n- [ ] F2 · 2026-10-19 · duplicate id from another session\n\n## Evaluated", 1))
o, _ = bl("-p", "p1", "add", "Search box"); txt = f.read_text()
ids = [l.split(" · ")[0].split("] ")[1] for l in txt.splitlines() if l.startswith("- [")]
check("id-less and duplicate lines get unique ids on the next write", len(ids) == len(set(ids)) == 5 and "Offline mode" in txt and "duplicate id" in txt, txt)
# verdict / done / drop
o, _ = bl("-p", "p1", "verdict", "F1", "BUILD LATER", "·", "score", "2.4", "·", "needs F2"); txt = f.read_text()
check("verdict moves the item to Evaluated with a ↳ line", "## Evaluated\n\n- [ ] F1" in txt and "↳ verdict: BUILD LATER · score 2.4 · needs F2" in txt, txt)
o, _ = bl("-p", "p1", "done", "F2"); o2, _ = bl("-p", "p1", "drop", "F3")
txt = f.read_text(); check("done and drop go to Done / Dropped with dates", "- [x] F2" in txt and "- [-] F3" in txt and txt.count(" · done 20") == 1 and txt.count(" · dropped 20") == 1, txt)
o, _ = bl("-p", "p1", "list"); check("list (open) no longer shows done/dropped", "F2" not in o and "F3" not in o, o)
o, _ = bl("-p", "p1", "list", "--evaluated"); check("list --evaluated shows the verdict", "BUILD LATER" in o, o)
o, _ = bl("-p", "p1", "eval-prompt", "f1", "f4"); check("eval-prompt is one line naming the method doc", o.count("\n") == 1 and "F1,F4" in o and "idea-review-method.md" in o and "plan mode" in o, o)
o, rc = bl("-p", "p1", "done", "F99"); check("unknown id fails clearly", rc != 0 and "no item F99" in o, o)
# move: re-home an idea (the Inbox is the `ideas` project)
o, rc = bl("-p", "p1", "move", "F5", "--to", "ideas"); ptxt = (p1 / "docs/FEATURE-IDEAS.md").read_text(); itxt = (ideas / "docs/FEATURE-IDEAS.md").read_text()
check("move takes the idea out of one project and into the other", rc == 0 and "F5" not in ptxt.split("## Evaluated")[0] and "Search box (moved from p1 F5)" in itxt, o + itxt)
check("move commits in both projects", git(p1, "log", "-1", "--format=%s").strip().startswith("ideas: move F5") and git(ideas, "log", "-1", "--format=%s").strip().startswith("ideas: F"))
o, rc = bl("-p", "p1", "copy", "F4", "--to", "ideas"); ptxt = (p1 / "docs/FEATURE-IDEAS.md").read_text(); itxt = (ideas / "docs/FEATURE-IDEAS.md").read_text()
check("copy keeps the original and adds a fresh Open item with a note", rc == 0 and "F4" in ptxt and "(copied from p1 F4)" in itxt and "verdict" not in itxt.split("(copied from p1 F4)")[1].split("\n")[0], o + itxt)
o, rc = bl("-p", "p1", "copy", "F4", "--to", "p1"); check("copy into the same project is refused", rc != 0 and "already in" in o, o)
o, rc = bl("-p", "p1", "copy", "F4", "--to", "held"); check("copy into a held project is refused", rc != 0 and "on hold" in o, o)
o, rc = bl("-p", "p1", "eval-prompt", "f1"); check("eval-prompt asks for a recommendation (home, worth, next step)", "RECOMMENDATION" in o and "another existing project" in o and "next step" in o and o.count("\n") == 1, o)
o, rc = bl("-p", "p1", "move", "F6", "--to", "held"); check("move into a held project is refused", rc != 0 and "on hold" in o, o)
o, rc = bl("-p", "p1", "move", "F6", "--to", "nowhere"); check("move to an unknown project fails clearly", rc != 0 and "no project" in o, o)
# project from the folder you are in
o, rc = bl("add", "From the folder", cwd=str(p1)); check("project defaults to the git folder you are in", rc == 0 and "p1: added" in o, o)
# held project refused
o, rc = bl("-p", "held", "add", "x"); check("project on config/ci-hold.txt is refused", rc != 0 and "on hold" in o and not (DEV / "held/docs/FEATURE-IDEAS.md").exists(), o)
# index: overlaps across projects and ideas
(ideas / "ideas").mkdir(); (ideas / "ideas/report-builder.md").write_text("status: idea\nExport report as PDF with charts for managers #export #report\n")
bl("-p", "p1", "add", "Export report as PDF", "#export", "#report")
o, _ = bl("index"); check("index lists projects and ideas and flags the overlap", "p1" in o and "report-builder" in o and "Likely overlaps" in o and "p1/F" in o, o)

# ---- nudge ----
now = time.time()
def old(path, hours):
    t = now - hours * 3600; os.utime(path, (t, t))
def setup(idle_h=60, guard=None, away=False):
    for n in ("p1", "ideas", "held"):
        (STATE / f"{n}.json").write_text(json.dumps({"state": "done", "ts": int(now - idle_h * 3600)}))
    (STATE / "guard.json").write_text(json.dumps(guard or {"lid_closed": False, "idle_s": 5, "ts": int(now)}))
    (STATE / "away.json").write_text(json.dumps({"away": away, "ts": int(now)}))
    for f in ("idea-prefs.json", "idea-ask.json"): (STATE / f).unlink(missing_ok=True)
    enc = HOME / ".claude/projects/-x-Developer-p1"; enc.mkdir(parents=True, exist_ok=True); tr = enc / "s.jsonl"; tr.write_text("{}\n"); old(tr, idle_h)
    d = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now - idle_h * 3600))
    for n in ("p1", "ideas"):                                   # the project's last real commit (not a ideas one) is idle_h old
        with open(DEV / n / "a.txt", "a") as fh: fh.write("change\n")
        git(DEV / n, "add", "a.txt")
        subprocess.run(["git", "-C", str(DEV / n), "commit", "-q", "-m", "work", "--date", d, "--", "a.txt"], env=dict(GENV, GIT_COMMITTER_DATE=d), capture_output=True)
def nudge(): o, _ = bl("nudge"); return o
setup(); o = nudge()
check("idle 60 h, owner present, open items -> one batched ask (the Inbox counts too)", "ask: " in o and "p1 " in o and (STATE / "idea-ask.json").exists(), o)
# macOS notification for the ask: silent unless config/notifications.json says mac:true (the panel banner is the ask)
_rec = T / "osascript"; _rec.write_text("#!/bin/sh\necho \"$@\" >> " + str(T / "osa.log") + "\n"); _rec.chmod(0o755)
ENV3 = dict(ENV); ENV3["SHIPMIRACLE_OSASCRIPT"] = str(_rec)      # the recorder counts only under SHIPMIRACLE_TEST=1
def nudge3(cfg):
    setup(); (WS / "config").mkdir(exist_ok=True); (WS / "config/notifications.json").write_text(cfg); (T / "osa.log").unlink(missing_ok=True)
    r = subprocess.run([str(ws / "bin/idea"), "nudge"], capture_output=True, text=True, env=ENV3); return r.stdout, (T / "osa.log").exists()
o3, sent = nudge3('{"mac": false}'); check("idle ask: no macOS notification by default (the banner is the ask)", "ask: " in o3 and not sent, o3)
o3, sent = nudge3('{"mac": true}'); check("idle ask: a notification only when the switch is on", "ask: " in o3 and sent, o3)
setup(); o = nudge()
check("held project is never asked about", "held" not in json.dumps(json.loads((STATE / "idea-ask.json").read_text())))
check("second run within a day: no new ask", "already asked" in nudge())
setup(idle_h=5); check("project active 5 h ago -> no ask (needs 48 h)", "nothing to ask" in nudge())
setup(guard={"lid_closed": True, "idle_s": 5}); check("lid closed -> no ask", "owner not at the Mac" in nudge())
setup(guard={"lid_closed": False, "idle_s": 900}); check("owner idle 15 min -> no ask", "owner not at the Mac" in nudge())
setup(away=True); check("away mode -> no ask", "owner not at the Mac" in nudge())
setup(); (STATE / "ideas.json").write_text(json.dumps({"state": "working", "ts": int(now)})); check("another project working -> not a good moment", "not a good moment" in nudge())
setup(); (STATE / "p1.agents.json").write_text(json.dumps({"a": {"started": now - 60}})); o = nudge(); check("agents running -> that project is not asked about", "p1" not in o, o)
(STATE / "p1.agents.json").unlink(); setup(); nudge(); bl("snooze", "p1")
prefs = json.loads((STATE / "idea-prefs.json").read_text()); prefs["last_ask"] = 0; (STATE / "idea-prefs.json").write_text(json.dumps(prefs))
check("Later (snooze) silences the project", "nothing to ask" in nudge())
setup(); nudge(); bl("never", "p1"); prefs = json.loads((STATE / "idea-prefs.json").read_text()); prefs["last_ask"] = 0; prefs["snooze"] = {}; (STATE / "idea-prefs.json").write_text(json.dumps(prefs))
check("Never silences the project for good", "nothing to ask" in nudge())
setup(); nudge(); bl("dismiss"); check("dismiss clears the ask and snoozes", not (STATE / "idea-ask.json").exists() and "p1" in json.loads((STATE / "idea-prefs.json").read_text()).get("snooze", {}))
setup(); nudge(); prefs = json.loads((STATE / "idea-prefs.json").read_text()); prefs["last_ask"] = 0; (STATE / "idea-prefs.json").write_text(json.dumps(prefs))
bl("-p", "p1", "add", "A brand new idea"); check("a new idea re-opens the question (before the 7 days)", "ask: p1" in nudge())
# T4: project discovery through shipmiracle.projects (traversal closed; symlinked project still works)
import shutil
mk("evil"); (T / "outside").mkdir(); subprocess.run(["git", "init", "-q", str(T / "outside")], env=GENV)
hid = DEV / ".hidden"; shutil.copytree(DEV / "evil", hid)
for bad in ("../evil", "../../outside", ".hidden", "", ".", "..", "a/b"):
    for cmd in (("add", "x"), ("list",), ("eval-prompt", "f1")):
        o, rc = bl("-p", bad, *cmd); check(f"-p {bad!r} {cmd[0]} refused", rc != 0 and f"no project {bad} in {DEV}" in o, o)
check("traversal wrote nothing outside", not (T / "outside" / "docs").exists() and not (DEV / "evil" / "docs").exists() and not (hid / "docs").exists())
o, rc = bl("-p", "p1", "copy", "F4", "--to", "../evil"); check("copy --to ../evil refused", rc != 0 and "no project ../evil" in o, o)
o, rc = bl("-p", "p1", "copy", "F4", "--to", ".hidden"); check("copy --to .hidden refused", rc != 0 and "no project .hidden" in o, o)
os.symlink(T / "outside", DEV / "linked")
o, rc = bl("-p", "linked", "add", "via symlink"); check("symlinked project still works", rc == 0 and "linked: added F1" in o, o)
o, rc = bl("-p", "nothing-here", "add", "x"); check("unknown project text unchanged", rc != 0 and f"no project nothing-here in {DEV}" in o, o)
print("\nFAILED:" if fails else "\nALL PASS", fails)
sys.exit(1 if fails else 0)
