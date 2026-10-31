#!/usr/bin/env python3
"""Phase 6 T3: the gate in BOTH copies (SHIPMIRACLE_GATE_IMPL picks one like every flow suite) covers git worktrees under <DEV>/.worktrees/<p>/<x>
(F1), refuses `shipm autopilot ...` and `claude` with `charter:`/`allow:` to the model (C7), refuses every write on an auto/CR-N branch unless
hooks.dispatcher is v1 and gate.engine is playbook (C6), and checks integrity (layout, registry entry, gate.engine) for subagents too.
Run: python3 tests/flow_gate_worktree_test.py"""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import shipmiracle_isolation; shipmiracle_isolation.apply_to_environ()   # test isolation: fresh HOME/SHIPMIRACLE_HOME/CONFIG/STATE unless already temp
import copy, hashlib, json, os, pathlib, subprocess, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import flow_fixture as F
from flow_fixture import deny, text

ROOT = pathlib.Path(__file__).resolve().parent.parent
fails = []; projects = []
def check(n, c, info=""):
    print(("PASS " if c else "FAIL ") + n + ("" if c else " " + str(info)[:300]))
    if not c: fails.append(n)
FX = json.loads((ROOT / "tests/fixtures/flow/p6-gate.json").read_text())
BIG = "x = 1\n" * 40
GIT = lambda *a, cwd=None: subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t"] + list(a), cwd=cwd, check=True, capture_output=True)

def mk(agents=None):
    p = F.make_project("proj", agents=agents); projects.append(p)
    p.CFG = p.T / "cfg"; p.CFG.mkdir(); p.HM = p.T / "home"; (p.HM / ".claude").mkdir(parents=True)
    p.ENV.update(SHIPMIRACLE_CONFIG=str(p.CFG), SHIPMIRACLE_HOME=str(p.HM), HOME=str(p.HM))
    (p.DEV / ".worktrees/proj").mkdir(parents=True)
    return p

def worktree(p, name="wt1", branch="feat/x", under="proj"):
    path = p.DEV / ".worktrees" / under / name
    path.parent.mkdir(parents=True, exist_ok=True)
    GIT("-C", str(p.P), "worktree", "add", "-q", "-b", branch, str(path))
    return on(p, path)

def on(p, path):
    q = copy.copy(p); q.P = pathlib.Path(os.path.realpath(path)); q.ENV = dict(p.ENV, CLAUDE_PROJECT_DIR=str(q.P)); return q

def levels(p, default="strict", **projs):
    (p.WSF / "config/flow.json").write_text(json.dumps({"default": default, "projects": projs}))

def cfg(p, **kv):
    (p.CFG / "config.json").write_text(json.dumps(kv))

def register(p, team="on"):
    key = hashlib.sha256(("shipmiracle-project:" + os.path.realpath(p.P)).encode()).hexdigest()[:12]
    (p.CFG / "registry.json").write_text(json.dumps({"v": 1, "projects": {key: {"team": team, "name": "proj"}}}))

# ---- F1: a verified worktree is gated like its project, at the project's level
p = mk(); w = worktree(p); w.prompt()
check("f1: main project: a 40-line edit by the main chat is refused (control)", deny(p.write("src/new.py", BIG)))
check("f1: worktree: a 40-line edit by the main chat is refused (gated, not ungated)", deny(w.write("src/new.py", BIG)), w.write("src/new.py", BIG))
check("f1: worktree: a bash write is refused", deny(w.bash("echo x > src/b.py")))
check("f1: worktree: a record edit passes", not deny(w.edit("docs/STATUS.md", "a", "b")))
check("f1: worktree: events and state carry the project name", any(e.get("project") == "proj" for e in w.events()), w.events())
levels(p, "strict", proj="warn"); w.prompt()
check("f1: level comes from flow.json[proj] (warn: let through)", not deny(w.write("src/new.py", BIG)), w.write("src/new.py", BIG))
levels(p, "strict", proj="off"); w.prompt()
check("f1: level off for the project = off in its worktree", not deny(w.write("src/new.py", BIG)))
levels(p, "strict"); w.prompt()
# registry trust: a project without a team folder in git (so the worktree has none either)
p = mk({}); w = worktree(p); w.prompt()
check("f1: no team folder and no registry entry: not a team project, not gated", not deny(w.write("src/new.py", BIG)))
register(p); w.prompt("again")
check("f1: no team folder in the worktree but the MAIN project is registered with a team: gated", deny(w.write("src/new2.py", BIG)), w.write("src/new2.py", BIG))
register(p, "off")
check("f1: registry team off: not gated (trust resolved from the main project's entry)", not deny(w.write("src/new3.py", BIG)))

# ---- unknown worktrees: gated at the default level, never trusted, never free
p = mk(); levels(p, "strict", proj="off")
fo = p.T / "other"; fo.mkdir(); GIT("init", "-q", str(fo)); (fo / "a").write_text("a"); GIT("-C", str(fo), "add", "-A"); GIT("-C", str(fo), "commit", "-qm", "i")
cases = {}
d = p.DEV / ".worktrees/proj/plain"; d.mkdir(parents=True); cases["plain folder (no .git)"] = d
d = p.DEV / ".worktrees/proj/forged"; d.mkdir(); (d / ".git").write_text("gitdir: %s/.git/worktrees/nope\n" % p.P); cases["forged .git file (no admin folder)"] = d
d = p.DEV / ".worktrees/proj/dotdot"; d.mkdir(); (d / ".git").write_text("gitdir: %s/other/../proj/.git/worktrees/dotdot\n" % p.DEV); cases["gitdir with .."] = d
d = p.DEV / ".worktrees/proj/rel"; d.mkdir(); (d / ".git").write_text("gitdir: ../../../proj/.git/worktrees/rel\n"); cases["relative gitdir"] = d
d = p.DEV / ".worktrees/proj/unrel"; GIT("-C", str(fo), "worktree", "add", "-q", "-b", "u", str(d)); (d / ".claude/agents").mkdir(parents=True); cases["worktree of an unrelated repo"] = d
GIT("-C", str(p.P), "worktree", "add", "-q", "-b", "o", str(p.DEV / ".worktrees/other/x")) if (p.DEV / ".worktrees/other").mkdir(parents=True) is None else None
cases["worktree of proj placed under .worktrees/other"] = p.DEV / ".worktrees/other/x"
d = p.DEV / ".worktrees/proj/real"; GIT("-C", str(p.P), "worktree", "add", "-q", "-b", "r", str(d)); (d / ".git").rename(d / ".git.bak"); (d / ".git").symlink_to(d / ".git.bak"); cases["symlinked .git file"] = d
d = p.DEV / ".worktrees/proj/deep/er"; d.mkdir(parents=True); cases["two levels below the project folder"] = d
d = p.DEV / ".worktrees/proj/stolen"; GIT("-C", str(p.P), "worktree", "add", "-q", "-b", "s", str(d))
d2 = p.DEV / ".worktrees/proj/copy"; d2.mkdir(); (d2 / ".git").write_text((d / ".git").read_text()); cases["copy of a real worktree's .git file (admin folder points elsewhere)"] = d2
for label, path in cases.items():
    q = on(p, path); q.prompt()
    o = q.write("src/new.py", BIG)
    check("unknown worktree [%s]: gated at the default level (strict) although flow.json says proj=off" % label, deny(o), o)
    check("unknown worktree [%s]: a record edit passes" % label, not deny(q.edit("docs/STATUS.md", "a", "b")))
    check("unknown worktree [%s]: not logged under the project name" % label, not any(e.get("project") == "proj" and e.get("session") == "s1" and e["event"] == "edit_outside_team" for e in q.events()))
levels(p, "strict", proj="warn"); q = on(p, cases["plain folder (no .git)"]); q.prompt()
check("unknown worktree: warn for proj is NOT inherited", deny(q.write("src/new.py", BIG)))
levels(p, "warn"); q.prompt()
check("unknown worktree: the default level applies (warn: let through)", not deny(q.write("src/new.py", BIG)))
levels(p, "off"); q.prompt()
check("unknown worktree: default level off is the owner's own choice (not gated)", not deny(q.write("src/new.py", BIG)))
levels(p, "strict")
real = on(p, p.DEV / ".worktrees/proj/real")
# a verified worktree beside them stays trusted
p2 = mk(); w2 = worktree(p2); w2.prompt()
levels(p2, "strict", proj="warn"); w2.prompt()
check("verified worktree: proj=warn applies (unlike the unknown ones)", not deny(w2.write("src/new.py", BIG)))

# ---- tamper: the worktree's own gate files and the main project's
p = mk(); w = worktree(p); w.prompt()
for label, path in (("worktree .claude/settings.json", w.P / ".claude/settings.json"), ("worktree .shipmiracle/playbook.json", w.P / ".shipmiracle/playbook.json"),
                    ("main .claude/settings.json", p.P / ".claude/settings.json"), ("main .claude/settings.local.json", p.P / ".claude/settings.local.json"),
                    ("main .shipmiracle/playbook.json", p.P / ".shipmiracle/playbook.json"), ("main .claude/test-command", p.P / ".claude/test-command"),
                    ("main .claude/hooks/x.sh", p.P / ".claude/hooks/x.sh")):
    o = w.pre("Write", {"file_path": str(path), "content": "x"}); a = w.pre("Write", {"file_path": str(path), "content": "x"}, agent="backend-engineer")
    check("tamper: %s refused for the main chat and an agent" % label, deny(o) and deny(a) and "ask the owner to change them" in text(o), o)
    check("tamper: Bash write to %s refused" % label, deny(w.bash("echo x > '%s'" % path)))
check("tamper: ordinary worktree file edit is not a tamper", "ask the owner" not in text(w.write("src/new.py", BIG)))

# ---- autopilot admin subcommands and the nested claude
a = mk(); a.prompt()
for cmd in FX["autopilot_denied"]:
    check("c2 autopilot refused: " + cmd[:70], deny(a.bash(cmd)) and deny(a.pre("Bash", {"command": cmd}, agent="backend-engineer")), a.bash(cmd))
for cmd in ("shipm autopilot checkpoint --project sandbox", "shipm autopilot admit CR-015 --project sandbox", "shipm autopilot drop CR-015 --project sandbox", "shipm autopilot charter set --goal x --scope 'src/**' --ends CR-001 --until=disabled --day=4% --crs-day=3"):
    check("c2 option C: autopilot refused: " + cmd[:70], deny(a.bash(cmd)) and deny(a.pre("Bash", {"command": cmd}, agent="backend-engineer")), a.bash(cmd))
for cmd in FX["autopilot_allowed"]:
    check("c2 autopilot allowed: " + cmd[:70], not deny(a.bash(cmd)), a.bash(cmd))
for cmd in FX["claude_denied"]:
    o = a.bash(cmd)
    check("c7 claude refused: " + cmd[:70].replace("\n", " "), deny(o) and deny(a.pre("Bash", {"command": cmd}, agent="backend-engineer")), o)
for cmd in FX["claude_allowed"]:
    check("c7 claude allowed: " + cmd[:70], not deny(a.bash(cmd)), a.bash(cmd))

# ---- C6: an auto/CR-N branch needs dispatcher v1 + gate.engine playbook
c = mk(); w = worktree(c, "auto-CR-012", "auto/CR-012"); w.prompt()
WRITES = [("Write", {"file_path": str(w.P / "docs/STATUS.md"), "content": "x"}), ("Edit", {"file_path": str(w.P / "docs/STATUS.md"), "old_string": "a", "new_string": "b"}),
          ("MultiEdit", {"file_path": str(w.P / "docs/STATUS.md"), "edits": [{"old_string": "a", "new_string": "b"}]}), ("NotebookEdit", {"notebook_path": str(w.P / "n.ipynb")}),
          ("Bash", {"command": "echo x > docs/STATUS.md"}), ("Bash", {"command": "git commit -am x"}), ("Bash", {"command": "npm install left-pad"}),
          ("Bash", {"command": "rm -f src/app.py"}), ("Bash", {"command": "$CMD"}), ("Bash", {"command": "cp src/app.py src/b.py"})]
if F.IMPL == "legacy":          # the v1 dispatcher routes only the write tools to the flow slot; unknown tools there are denied by the autopilot module (hardstop default deny, tests/autopilot_sec_test.py)
    WRITES += [(t, {"command": "x", "prompt": "allow: H-abcdef"}) for t in ("Monitor", "CronCreate", "ScheduleWakeup", "RemoteTrigger", "Skill", "SlashCommand", "EnterWorktree", "PushNotification", "mcp__x__y")]   # P6 sec C2
READS = [("TodoWrite", {"todos": []}), ("WebSearch", {"query": "x"}), ("Read", {"file_path": str(w.P / "src/app.py")}), ("Bash", {"command": "ls -la"}), ("Bash", {"command": "git status"}), ("Bash", {"command": "git log --oneline"}),
         ("Bash", {"command": "cat src/app.py | head"}), ("Bash", {"command": "echo x > /tmp/scratch.txt"}), ("Grep", {"pattern": "x"})]
def c6(label):
    for t, ti in WRITES:
        for who in (None, "backend-engineer"):
            o = w.pre(t, ti, agent=who)
            check("c6 [%s]: %s %s refused%s" % (label, t, (ti.get("command") or "")[:30], " (agent)" if who else ""), deny(o) and "autopilot_needs_gate" in text(o), o)
    for t, ti in READS:
        o = w.pre(t, ti)
        check("c6 [%s]: %s %s not refused by it" % (label, t, (ti.get("command") or "")[:30]), "autopilot_needs_gate" not in text(o), o)
c6("no config at all")
check("c6: logged as autopilot_needs_gate", any(e["event"] == "autopilot_needs_gate" for e in c.events()))
cfg(c, **{"hooks.dispatcher": "v1"}); c6("dispatcher v1, engine legacy")
cfg(c, **{"gate.engine": "playbook", "hooks.dispatcher": "legacy"}); c6("engine playbook, dispatcher legacy")
cfg(c, **{"gate.engine": "playbook", "hooks.dispatcher": "shadow"}); c6("dispatcher shadow")
(c.CFG / "config.json").write_text("{not json"); c6("unreadable config")
cfg(c, **{"gate.engine": "playbook", "hooks.dispatcher": "v1"})
check("c6: both right: a record edit is no longer refused by it", "autopilot_needs_gate" not in text(w.edit("docs/STATUS.md", "a", "b")), w.edit("docs/STATUS.md", "a", "b"))
check("c6: both right: writes are not refused by it", all("autopilot_needs_gate" not in text(w.pre(t, ti)) for t, ti in WRITES))
env_fb = dict(w.ENV, SHIPMIRACLE_HOOK_FALLBACK="1"); (c.CFG / "config.json").write_text(json.dumps({"gate.engine": "playbook", "hooks.dispatcher": "v1"}))
check("c6 M1: both config values right but the shim fell back to the legacy scripts (SHIPMIRACLE_HOOK_FALLBACK=1): writes refused", all("autopilot_needs_gate" in text(w.hook("PreToolUse", env=env_fb, tool_name=t, tool_input=ti)) for t, ti in WRITES[:2]))
# the real shim with a core.py that cannot be imported: the legacy children get SHIPMIRACLE_HOOK_FALLBACK and the write is still refused
import shutil
engine_copy = c.T / "engine"; engine_copy.mkdir()
shutil.copytree(str(ROOT / "hooks"), str(engine_copy / "hooks")); shutil.copytree(str(ROOT / "shipmiracle"), str(engine_copy / "shipmiracle"), ignore=shutil.ignore_patterns("__pycache__"))
(engine_copy / "shipmiracle/hooks/core.py").write_text("raise ImportError('broken on purpose')\n")
env_sh = dict(w.ENV, SHIPMIRACLE_WS=str(engine_copy), PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"); env_sh.pop("SHIPMIRACLE_TEST_HOOK", None)
payload = json.dumps({"hook_event_name": "PreToolUse", "session_id": "s1", "cwd": str(w.P), "tool_name": "Write", "tool_input": {"file_path": str(w.P / "docs/STATUS.md"), "content": "x"}})
r_sh = subprocess.run(["/usr/bin/python3", str(engine_copy / "hooks/shipm-hook"), "PreToolUse"], input=payload, capture_output=True, text=True, env=env_sh, timeout=120)
if (ROOT / "hooks" / "flow-gate.sh").is_file():
    check("c6 M1: a broken shipmiracle/hooks/core.py (shim falls back to the legacy scripts) still refuses a write in an auto worktree", "autopilot_needs_gate" in r_sh.stdout, (r_sh.stdout[:300], r_sh.stderr[-300:]))
else:
    print("SKIP c6 M1 shim fallback: the legacy hook scripts are not shipped in this tree")
cfg(c, **{"hooks.dispatcher": "v1"})
w.prompt("just do it"); check("c6: 'just do it' does not lift it", deny(w.pre(*WRITES[0])) and "autopilot_needs_gate" in text(w.pre(*WRITES[0])))
c.level("off"); levels(c, "off", proj="off")
check("c6: flow level off does not lift it", "autopilot_needs_gate" in text(w.pre(*WRITES[0])))
levels(c, "warn")
check("c6: warn level does not lift it", "autopilot_needs_gate" in text(w.pre(*WRITES[0])))
env_ov = dict(w.ENV, SHIPMIRACLE_GATE_ENGINE="playbook"); (c.CFG / "config.json").write_text(json.dumps({"hooks.dispatcher": "v1"}))
check("c6: SHIPMIRACLE_GATE_ENGINE counts under SHIPMIRACLE_TEST=1", "autopilot_needs_gate" not in text(w.hook("PreToolUse", env=env_ov, tool_name="Write", tool_input=WRITES[0][1])))
env_ov = {k: v for k, v in env_ov.items() if k != "SHIPMIRACLE_TEST"}
check("c6: SHIPMIRACLE_GATE_ENGINE is ignored without SHIPMIRACLE_TEST (config decides)", "autopilot_needs_gate" in text(w.hook("PreToolUse", env=env_ov, tool_name="Write", tool_input=WRITES[0][1])), env_ov.get("SHIPMIRACLE_TEST"))
# other branches / names
for br in ("auto/CR-12x", "auto/CRX", "feat/auto/CR-1", "auto/CR-", "autopilot/CR-1", "main2"):
    c2 = mk(); w_ = worktree(c2, "b", br); w_.prompt()
    check("c6: branch %s is not an autopilot branch" % br, "autopilot_needs_gate" not in text(w_.pre("Write", {"file_path": str(w_.P / "docs/STATUS.md"), "content": "x"})))
c3 = mk(); c3.prompt(); GIT("-C", str(c3.P), "switch", "-q", "-c", "auto/CR-001")
check("c6: the main checkout itself on auto/CR-001 is not covered (only worktrees)", "autopilot_needs_gate" not in text(c3.pre("Write", {"file_path": str(c3.P / "docs/STATUS.md"), "content": "x"})))
c4 = mk(); w4 = worktree(c4, "auto-CR-3", "auto/CR-3"); w4.prompt(); (w4.P / ".git").unlink(); (w4.P / ".git").write_text("gitdir: %s/.git/worktrees/missing\n" % c4.P)
check("c6: a forged .git file is an unknown worktree (gated, no C6 branch)", "autopilot_needs_gate" not in text(w4.pre("Write", {"file_path": str(w4.P / "docs/STATUS.md"), "content": "x"})) and deny(w4.write("src/new.py", BIG)))

# ---- integrity for subagents
def agent_case(label, mutate, expect_name, setup=None):
    q = mk(); cfg(q, **{"gate.engine": "legacy"})
    if setup: setup(q)
    small = dict(tool_name="Bash", tool_input={"command": "ls"}, agent_id="a1", agent_type="backend-engineer")
    q.prompt("go")
    check("agent integrity [%s]: baseline, nothing changed -> passes" % label, not deny(q.hook("PreToolUse", **small)))
    mutate(q)
    o = q.hook("PreToolUse", **small)
    check("agent integrity [%s]: change mid-turn -> refused, names %s" % (label, expect_name), deny(o) and expect_name in text(o) and "Tell the owner or revert it" in text(o), o)
    check("agent integrity [%s]: still refused on the next call" % label, deny(q.hook("PreToolUse", **small)))
    check("agent integrity [%s]: a PostToolUse is not refused" % label, not deny(q.hook("PostToolUse", **dict(small, tool_name="Bash"))))
    q.prompt("ok")
    check("agent integrity [%s]: the owner's next message re-baselines" % label, not deny(q.hook("PreToolUse", **small)))
    return q
agent_case("gate.engine", lambda q: cfg(q, **{"gate.engine": "playbook"}), "gate.engine")
agent_case("layout", lambda q: cfg(q, **{"gate.engine": "legacy", "agents.layout": "userlevel"}), "agents.layout")
def reg_change(q):
    p_ = q.CFG / "registry.json"; j = json.loads(p_.read_text()); e = next(iter(j["projects"].values())); e["team"] = "off"; p_.write_text(json.dumps(j))
q = agent_case("registry entry", reg_change, "registry entry", setup=lambda q: (cfg(q, **{"gate.engine": "legacy", "agents.layout": "userlevel"}), register(q)))
q = mk(); cfg(q, **{"gate.engine": "legacy"})
small = dict(tool_name="Bash", tool_input={"command": "ls"}, agent_id="a1", agent_type="backend-engineer")
check("agent integrity: no baseline yet (agent first) -> passes", not deny(q.hook("PreToolUse", **small)))
check("agent integrity: ... and the agent call did not create the baseline", "integrity" not in q.state(), q.state())
cfg(q, **{"gate.engine": "playbook"}); q.prompt("go")
check("agent integrity: baseline made by the owner's prompt holds the new value", not deny(q.hook("PreToolUse", **small)))
check("agent integrity: file churn (a new hooks" "/x.sh in the workspace) is NOT watched for agents", (q.WSF / "hooks").mkdir() is None and (q.WSF / "hooks" "/x.sh").write_text("#!/bin/sh\n") and not deny(q.hook("PreToolUse", **small)))
check("agent integrity: ... but the main chat still sees it", deny(q.hook("PreToolUse", tool_name="Bash", tool_input={"command": "ls"})))
q = mk(); cfg(q, **{"gate.engine": "legacy"}); levels(q, "warn"); q.prompt("go"); cfg(q, **{"gate.engine": "playbook"})
o = q.hook("PreToolUse", **small)
check("agent integrity: warn level only notes it", not deny(o) and "gate.engine" in text(o), o)
q = mk(); q.prompt("go"); (q.CFG / "config.json").write_text("{bad")
check("agent integrity: a broken config.json is a change for the agent too", deny(q.hook("PreToolUse", **small)))

# ---- P5 security review: H1 option values, env redirection, M3 reports, L1 git routes
h = mk(); (h.P / ".shipmiracle").mkdir(); (h.P / ".shipmiracle/playbook.json").write_text('{"v":1}'); h.prompt()
for cmd in FX["opt_value_denied"]:
    check("h1 refused: " + cmd[:70], deny(h.bash(cmd)) and deny(h.pre("Bash", {"command": cmd}, agent="backend-engineer")), h.bash(cmd))
for cmd in FX["opt_value_allowed"]:
    check("h1 allowed: " + cmd[:70], not deny(h.bash(cmd)), h.bash(cmd))
for rel_ in FX["reports_denied_paths"]:
    ap = str(h.P / rel_)
    for who in (None, "backend-engineer"):
        check("m3 %s Write refused%s" % (rel_, " (agent)" if who else ""), deny(h.pre("Write", {"file_path": ap, "content": "x"}, agent=who)))
    check("m3 %s Edit refused" % rel_, deny(h.pre("Edit", {"file_path": ap, "old_string": "a", "new_string": "b"})))
    check("m3 %s Bash redirect refused" % rel_, deny(h.bash("echo x > " + rel_)))
check("m3 Bash rm -rf docs/reports refused", deny(h.bash("rm -rf docs/reports")))
check("m3 sibling docs/reports-old.md and docs/STATUS.md are not refused", not deny(h.write("docs/reports-old.md", "x")) and not deny(h.edit("docs/STATUS.md", "a", "b")))
pt = h.T / "p.diff"; pt.write_text("diff --git a/.shipmiracle/playbook.json b/.shipmiracle/playbook.json\n--- a/.shipmiracle/playbook.json\n+++ b/.shipmiracle/playbook.json\n@@ -1 +1 @@\n-a\n+b\n")
ok = h.T / "ok.diff"; ok.write_text("diff --git a/src/app.py b/src/app.py\n--- a/src/app.py\n+++ b/src/app.py\n@@ -1 +1 @@\n-a\n+b\n")
sub = lambda c: c.replace("{PATCH}", str(pt)).replace("{OKPATCH}", str(ok)).replace("{P}", str(h.P))
for cmd in FX["git_denied"]:
    cmd = sub(cmd)
    check("l1 refused: " + cmd[:70].replace(str(h.T), "T"), deny(h.bash(cmd)) and deny(h.pre("Bash", {"command": cmd}, agent="backend-engineer")), h.bash(cmd))
for cmd in FX["git_allowed"]:
    cmd = sub(cmd)
    check("l1 allowed: " + cmd[:70].replace(str(h.T), "T"), not deny(h.bash(cmd)), h.bash(cmd))
n = mk(); n.prompt()                                             # no .shipmiracle/playbook.json: only the forms that name .shipmiracle are refused
check("l1: worktree-wide forms are allowed in a project without .shipmiracle/playbook.json", all(not deny(n.bash(c)) for c in ("git checkout -- .", "git restore .", "git reset --hard", "git stash", "git clean -fd")))
check("l1: ... but naming .shipmiracle is refused anyway", deny(n.bash("git checkout HEAD~1 -- .shipmiracle/playbook.json")))

print("\n%d failed" % len(fails) if fails else "\nALL PASS")
for pr in projects: pr.cleanup()
sys.exit(1 if fails else 0)
