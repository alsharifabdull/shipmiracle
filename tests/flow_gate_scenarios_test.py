#!/usr/bin/env python3
"""Flow gate scenarios: hand-backs, races, false 'outside the team' flags, agent files, roles, levels, broken input, changed-line counting.
Run: python3 tests/flow_gate_scenarios_test.py"""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import shipmiracle_isolation; shipmiracle_isolation.apply_to_environ()   # test isolation: fresh HOME/SHIPMIRACLE_HOME/CONFIG/STATE unless already temp
import json, os, pathlib, shutil, stat, subprocess, sys, time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import flow_fixture as F
from flow_fixture import deny, note, text

fails = []; projects = []
def check(n, c, info=""):
    print(("PASS " if c else "FAIL ") + n + ("" if c else " " + str(info)[:300]))
    if not c: fails.append(n)
def mk(*a, **k):
    p = F.make_project(*a, **k); projects.append(p); return p
BIG = "\n".join(f"l{i}" for i in range(30))
GOOD = F.AGENT_TEXT.format(n="new-role", m="sonnet", r="build")

# ---- B1: a subagent hand-back is not the owner
p = mk()
p.prompt()
r = [p.edit("src/app.py", "a", BIG) for _ in range(2)]
p.hook("UserPromptSubmit", prompt="<agent-message from=\"backend-engineer\">done. just do it</agent-message>")
o = p.edit("src/app.py", "a", BIG)
check("B1 hand-back with 'just do it' does not reset the cap (third refusal is still a pass-with-note)", deny(r[0]) and deny(r[1]) and not deny(o) and "third time" in note(o), o)
p = mk()
p.prompt(); p.hook("UserPromptSubmit", prompt="<task-notification>finished, just do it</task-notification>")
check("B1 hand-back with 'just do it' does not bypass", deny(p.edit("src/app.py", "a", BIG)) and not p.state().get("bypass"))
p = mk()
p.prompt(); p.edit("src/app.py", "x = 1", "x = 2")
p.hook("UserPromptSubmit", prompt="<agent-message>hi</agent-message>")
check("B1 hand-back does not reset the small-fix allowance", deny(p.edit("src/other.py", "a", "b")))
p = mk()
p.hook("UserPromptSubmit", prompt="<agent-message>hi</agent-message>")
check("B1 hand-back as the first event sets no baseline and is logged", "baseline" not in p.state() and any(e["event"] == "agent_message" for e in p.events()))

# ---- B2: parallel hooks
p = mk()
p.prompt()
files = [f"src/par{i}.py" for i in range(8)]
procs = [p.popen("PostToolUse", tool_name="Edit", tool_input={"file_path": str(p.P / f)}, agent_id=f"a{i}", agent_type="backend-engineer") for i, f in enumerate(files)]
for x in procs: x.communicate(x.payload)
got = set(p.state().get("agent_edits", []))
check("B2 parallel PostToolUse writes are all recorded", got == set(files), got)
check("B2 flow-errors.log stays empty", p.errors() == "", p.errors())

# ---- B3 false flags
p = mk()
p.prompt()
p.edit("src/app.py", "x = 1", "x = 2\ny = 3"); p.put("src/app.py", "x = 2\ny = 3\n")
p.post("Edit", {"file_path": str(p.P / "src/b.py")}, agent="backend-engineer"); p.put("src/b.py", "b\n")
check("B3a small fix + agent edit: stop refused for QA", deny(p.stop()))
p.sub_stop("qa-engineer"); p.prompt("next")
o = p.stop()
check("B3a small fix then QA block then next turn: not flagged", not deny(o) and "app.py" not in text(o), o)

p = mk()
p.prompt()
check("B3b main chat writes a good agent file: allowed", not deny(p.write(".claude/agents/new-role.md", GOOD)))
p.put(".claude/agents/new-role.md", GOOD)
o = p.stop()
check("B3b agent file written by the main chat is not flagged", "new-role" not in text(o) and ".claude/agents/new-role.md" in p.state().get("agent_files", []), o)

p = mk()
p.prompt("typo, just do it")
p.edit("src/app.py", "a", BIG); p.put("src/app.py", BIG + "\n"); p.put("src/viaShell.py", "z\n")
check("B3c just-do-it turn: stop passes", not deny(p.stop()))
p.prompt("thanks"); o = p.stop()
check("B3c next turn: files of the just-do-it turn are not flagged", "app.py" not in text(o) and "viaShell" not in text(o), o)

p = mk()
p.put("src/pre.py", "p\n")
o = p.stop("fresh")
check("B3e no baseline: nothing flagged and the baseline is set", not deny(o) and "pre.py" not in text(o) and "src/pre.py" in p.state("fresh").get("baseline", []), o)
p.put("src/later.py", "l\n")
check("B3e afterwards new files are flagged", "later.py" in text(p.stop("fresh")))

p = mk()
p.prompt()
ar, sp = "src/ملف.py", "src/my file.py"
p.put(ar, "a\n"); p.put(sp, "b\n")
o = p.stop()
check("B3f Arabic and space paths are flagged with their real names", "ملف.py" in text(o) and "my file.py" in text(o), o)
ar2, sp2 = "src/ملف2.py", "src/my file2.py"
p.put(ar2, "a\n"); p.put(sp2, "b\n"); p.put("src/ok.py", "k\n"); p.sub_stop("backend-engineer"); p.sub_stop("qa-engineer"); p.prompt("x")
st = p.state()
check("B3f Arabic and space paths match the baseline/agent lists", ar2 in st.get("agent_edits", []) and sp2 in st.get("agent_edits", []), st)
check("B3f ... and are not flagged afterwards", "ملف2" not in text(p.stop()) and "my file2" not in text(p.stop()))
subprocess.run(["git", "-C", str(p.P), "add", "-A"]); subprocess.run(["git", "-C", str(p.P), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "c"], capture_output=True)
subprocess.run(["git", "-C", str(p.P), "mv", ar, "src/نقل.py"])
p.prompt("y", "ren"); p.put("src/ren-new.py", "n\n")
o = p.stop("ren")
check("B3f a rename is parsed as the new name (flagged once, old name absent)", "src/ملف.py" not in text(o) and "ren-new.py" in text(o), o)

# B3d: two sessions
p = mk()
p.prompt(sid="A"); p.prompt(sid="B")
p.post("Edit", {"file_path": str(p.P / "src/a.py")}, sid="A", agent="backend-engineer"); p.put("src/a.py", "a\n")
p.edit("src/app.py", "x = 1", "x = 9", sid="A"); p.put("src/small.py", "s\n")
o = p.stop("B")
check("B3d A's agent edit is not flagged when B stops", "a.py" not in text(o), o)
check("B3d A's agent edit is known to B (small.py is still flagged)", "small.py" in text(o), o)
p.sub_stop("qa-engineer", "A")
p.edit("src/other.py", "a", BIG, sid="A"); p.edit("src/other.py", "a", BIG, sid="A")
o = p.edit("src/other.py", "a", BIG, sid="B")
check("B3d A's refusals do not leak into B (B is refused, not capped)", deny(o) and "third time" not in text(o), o)
p.prompt("just do it", "A")
check("B3d A's bypass does not leak into B", deny(p.edit("src/other.py", "a", BIG, sid="B")))
stf = p.STATE / "flow.A.json"; sa = json.load(open(stf)); sa["ts"] = int(time.time()) - 90000; json.dump(sa, open(stf, "w"))
p.put("src/a2.py", "a\n"); p.put("src/a.py", "a\n")
check("B3d sessions older than 24 h are ignored", "a.py" in text(p.stop("B")))

# ---- B4
p = mk()
p.prompt()
p.post("Write", {"file_path": str(p.P / "docs/plans/x.md")}, agent="solution-architect")
check("B4 architect writing docs/plans/x.md sets no build and needs no QA", "build_ts" not in p.state() and not deny(p.stop()))
p.post("Write", {"file_path": str(p.P / "src/real.py")}, agent="solution-architect")
check("B4 ... a source file still counts", deny(p.stop()))

# ---- stale QA and reviewer
p = mk()
p.prompt()
p.post("Edit", {"file_path": str(p.P / "src/app.py")}, agent="backend-engineer"); p.sub_stop("qa-engineer")
check("stale QA: QA after the edit passes", not deny(p.stop()))
time.sleep(0.05)
p.post("Edit", {"file_path": str(p.P / "src/app.py")}, agent="backend-engineer")
check("stale QA: an agent edit after QA is refused again", deny(p.stop()))
p = mk()
p.prompt()
p.post("Edit", {"file_path": str(p.P / "src/app.py")}, agent="backend-engineer"); p.sub_stop("independent-reviewer")
check("reviewer run sets review_ts but does not satisfy QA", "review_ts" in p.state() and deny(p.stop()))
p.prompt("again")
check("reviewer run does not satisfy the plan", deny(p.pre("ExitPlanMode", {})))

# ---- project-only agents
ag = dict(F.DEFAULT_AGENTS)
ag["my-planner"] = F.AGENT_TEXT.format(n="my-planner", m="opus", r="plan")
ag["my-builder"] = F.AGENT_TEXT.format(n="my-builder", m="sonnet", r="build")
ag["qa-reviewer"] = F.AGENT_TEXT.format(n="qa-reviewer", m="sonnet", r="test")
ag["helper"] = "---\nname: helper\nmodel: sonnet\n---\nModel reason: x\nno role here\n"
p = mk(agents=ag)
p.prompt()
p.sub_stop("helper")
check("agent without a role counts as nothing", not any(k in p.state() for k in ("build_ts", "qa_ts", "arch_ts", "review_ts")), p.state())
check("plan role project agent counts as the architect", deny(p.pre("ExitPlanMode", {})) and (p.sub_stop("my-planner") or True) and not deny(p.pre("ExitPlanMode", {})))
p.prompt("n"); p.sub_stop("my-builder")
check("build role project agent is credited and needs QA", deny(p.stop()))
p.sub_stop("qa-reviewer")
check("qa-reviewer with test role satisfies QA", not deny(p.stop()))

# ---- agent files
p = mk()
p.prompt()
cases = {"missing model": "---\nname: x\n---\nModel reason: a\nFlow role: build\n",
         "inherit": "---\nmodel: inherit\n---\nModel reason: a\nFlow role: build\n",
         "missing reason": "---\nmodel: sonnet\n---\nFlow role: build\n",
         "missing role": "---\nmodel: sonnet\n---\nModel reason: a\n",
         "invalid role": "---\nmodel: sonnet\n---\nModel reason: a\nFlow role: banana\n"}
for n, t in cases.items():
    check(f"agent file ({n}): refused for main chat and for an agent", deny(p.write(".claude/agents/z.md", t)) and deny(p.write(".claude/agents/z.md", t, agent="backend-engineer")))
check("agent file with the rule: allowed for both", not deny(p.write(".claude/agents/new-role.md", GOOD)) and not deny(p.write(".claude/agents/new-role.md", GOOD, agent="backend-engineer")))
p.put(".claude/agents/z.md", GOOD)
rm = {"file_path": str(p.P / ".claude/agents/z.md"), "old_string": "Flow role: build\n", "new_string": ""}
check("Edit that removes the role: refused (main chat and agent)", deny(p.pre("Edit", rm)) and deny(p.pre("Edit", rm, agent="backend-engineer")))
mrm = {"file_path": rm["file_path"], "edits": [{"old_string": "Flow role: build\n", "new_string": ""}]}
check("MultiEdit that removes the role: refused (main chat and agent)", deny(p.pre("MultiEdit", mrm)) and deny(p.pre("MultiEdit", mrm, agent="backend-engineer")))
ok = {"file_path": rm["file_path"], "edits": [{"old_string": "test agent", "new_string": "other"}, {"old_string": "name: new-role", "new_string": "name: z"}]}
check("MultiEdit that keeps the rule: allowed", not deny(p.pre("MultiEdit", ok)) and not deny(p.pre("MultiEdit", ok, agent="backend-engineer")))
check("Edit that keeps the rule: allowed", not deny(p.pre("Edit", {**rm, "old_string": "name: new-role", "new_string": "name: z"})))

# ---- levels
def matrix(name, act):
    p = mk(); out = {}
    for lv in ("strict", "warn", "off"):
        p.level(lv); sid = "m" + lv; p.prompt(sid=sid); out[lv] = act(p, sid)
    check(f"level {name}: strict refuses", deny(out["strict"]), out["strict"])
    check(f"level {name}: warn only notes", not deny(out["warn"]) and "warn-only" in note(out["warn"]), out["warn"])
    check(f"level {name}: off is silent", out["off"] == {}, out["off"])
matrix("plan without architect", lambda p, s: p.pre("ExitPlanMode", {}, s))
matrix("edit outside team", lambda p, s: p.edit("src/app.py", "a", BIG, s))
matrix("bash write", lambda p, s: p.bash("sed -i '' 's/a/b/' src/app.py", s))
def qa_act(p, s):
    p.post("Edit", {"file_path": str(p.P / "src/app.py")}, s, agent="backend-engineer"); return p.stop(s)
p = mk(); outs = {}
for lv in ("strict", "warn", "off"):
    p.level(lv); p.prompt(sid="q" + lv); outs[lv] = qa_act(p, "q" + lv)
check("level done without QA: strict blocks, warn notes, off silent", deny(outs["strict"]) and not deny(outs["warn"]) and "warn-only" in note(outs["warn"]) and outs["off"] == {}, outs)

# ---- non-project, no agents, broken input
p = mk()
p.prompt()
E2 = dict(p.ENV, CLAUDE_PROJECT_DIR=str(p.T / "notaproject"))
check("non-project folder is ignored", p.hook("PreToolUse", env=E2, tool_name="ExitPlanMode", tool_input={}) == {})
E3 = {k: v for k, v in p.ENV.items() if k != "CLAUDE_PROJECT_DIR"}
check("non-project cwd is ignored", p.hook("PreToolUse", env=E3, cwd=str(p.T / "elsewhere"), tool_name="ExitPlanMode", tool_input={}) == {})
check("project folder resolved from cwd works", deny(p.hook("PreToolUse", env=E3, tool_name="ExitPlanMode", tool_input={})))
p = mk(agents={}); os.rmdir(p.P / ".claude/agents"); p.prompt()
check("project that never had a team is not enforced", p.edit("src/app.py", "a", BIG) == {})
p = mk(); p.prompt(); shutil.rmtree(p.P / ".claude/agents"); p.prompt("again")
check("F2 team committed in git, then deleted: still enforced", deny(p.edit("src/app.py", "a", BIG)))
check("F2 ... team_missing logged once per session", [e["event"] for e in p.events()].count("team_missing") == 1 and (p.edit("src/app.py", "a", BIG) or True) and [e["event"] for e in p.events()].count("team_missing") == 1)
p = mk(); p.prompt()
subprocess.run(["git", "-C", str(p.P), "rm", "-rq", "--cached", ".claude/agents"]); shutil.rmtree(p.P / ".claude/agents")
check("F2 team gone and not in git, but this session's state saw it: still enforced", deny(p.edit("src/app.py", "a", BIG)))

p = mk()
for n, raw in (("bad JSON", "{bad"), ("empty input", ""), ("null input", "null"), ("list input", "[]")):
    r = p.run_raw(raw); check(f"broken input ({n}): exit 0, silent", r.returncode == 0 and r.stdout == "", (r.returncode, r.stdout))
check("broken input (bad JSON, empty, null, list) writes nothing to flow-errors.log", p.errors() == "", p.errors())
r = p.run_raw(json.dumps({"hook_event_name": "PreToolUse", "session_id": "s", "cwd": str(p.P), "tool_name": "Edit", "tool_input": None}))
check("broken input: null tool_input: exit 0, silent", r.returncode == 0 and r.stdout == "", r.stdout)
r = p.run_raw(json.dumps({"hook_event_name": "PreToolUse", "session_id": "s", "cwd": str(p.P), "tool_name": "Edit", "tool_input": "str"}))
check("broken input: string tool_input: exit 0", r.returncode == 0, r.stdout)
p.prompt(sid="c"); (p.STATE / "flow.c.json").write_text("{corrupt")
o = p.edit("src/app.py", "a", BIG, "c")
check("corrupt state file: hook still works (state starts fresh)", deny(o), o)
(p.WSF / "config/flow.json").write_text("{corrupt")
r = p.run_raw(json.dumps({"hook_event_name": "PreToolUse", "session_id": "d", "cwd": str(p.P), "tool_name": "ExitPlanMode", "tool_input": {}}))
check("corrupt flow.json: exit 0 and a valid answer, no error logged", r.returncode == 0 and (r.stdout == "" or json.loads(r.stdout) is not None) and p.errors() == "", p.errors())
(p.WSF / "config/flow.json").write_text("[1]")
err0 = len(p.errors())
r = p.run_raw(json.dumps({"hook_event_name": "PreToolUse", "session_id": "d", "cwd": str(p.P), "tool_name": "ExitPlanMode", "tool_input": {}}))
check("flow.json that is not an object: exit 0, the errors file did not grow", r.returncode == 0 and len(p.errors()) == err0, p.errors())
p.level("strict")
os.chmod(p.STATE, stat.S_IRUSR | stat.S_IXUSR)
r = p.run_raw(json.dumps({"hook_event_name": "UserPromptSubmit", "session_id": "u", "cwd": str(p.P), "prompt": "hi"}))
check("unwritable state folder: exit 0, silent", r.returncode == 0 and r.stdout == "", (r.returncode, r.stdout))
os.chmod(p.STATE, 0o755)

# ---- sample-app-like layout
ag = dict(F.DEFAULT_AGENTS); ag["qa-reviewer"] = F.AGENT_TEXT.format(n="qa-reviewer", m="sonnet", r="test")
p = mk("sample-app-like", records_dir="Docs", agents=ag)
p.prompt()
check("sample-app layout: Docs/STATUS.md and Docs/DECISIONS.md allowed", not deny(p.edit("Docs/STATUS.md", "a", BIG)) and not deny(p.edit("Docs/DECISIONS.md", "a", BIG)))
check("sample-app layout: Docs/API.md refused", deny(p.edit("Docs/API.md", "a", BIG)))
check("sample-app layout: an Arabic source file name is refused", deny(p.edit("src/ملف.py", "a", BIG)))
p.put("src/ملف.py", "a\n"); p.post("Write", {"file_path": str(p.P / "src/ملف.py")}, agent="backend-engineer")
check("sample-app layout: agent edit needs QA; project-only qa-reviewer satisfies it", deny(p.stop()) and (p.sub_stop("qa-reviewer") or True) and not deny(p.stop()))
check("sample-app layout: the Arabic file is not flagged", "ملف" not in text(p.stop()))

# ---- engineer writes via Bash, then QA
p = mk()
p.prompt(); p.put("src/viaBash.py", "z\n"); p.sub_stop("backend-engineer")
a = deny(p.stop()); p.sub_stop("qa-engineer"); o = p.stop()
check("engineer writes via Bash: QA required, then clean", a and not deny(o) and "viaBash" not in text(o), o)

# ---- changed-line counting (step 3)
def fresh(p):
    p.n = getattr(p, "n", 0) + 1; sid = "t%d" % p.n; p.prompt(sid=sid); return sid
p = mk()
p.put("src/hundred.py", "".join(f"line {i}\n" for i in range(100)))
p.put("src/rep.py", "".join(f"foo = {i}\n" for i in range(20)))
s = fresh(p); check("count: Edit of 2 lines is a small fix", not deny(p.edit("src/app.py", "a\nb", "c\nd", s)))
s = fresh(p); check("count: Edit of 11 lines is refused", deny(p.edit("src/app.py", "a", "\n".join("x" * (i + 1) for i in range(11)), s)))
blk = "".join(f"line {i}\n" for i in range(100)); blk2 = blk.replace("line 50\n", "LINE 50\n")
s = fresh(p); check("count: Edit with a 100-line block where one line differs counts 1", not deny(p.edit("src/hundred.py", blk, blk2, s)))
p.put("src/rep.py", "".join("foo\n" for _ in range(5)) + "other\n")
s = fresh(p); check("count: replace_all with 5 occurrences (5 lines) is allowed", not deny(p.edit("src/rep.py", "foo", "bar", s, replace_all=True)))
p.put("src/rep.py", "".join("foo\n" for _ in range(12)))
s = fresh(p); check("count: replace_all with 12 occurrences (12 lines) is refused", deny(p.edit("src/rep.py", "foo", "bar", s, replace_all=True)))
s = fresh(p); check("count: the same without replace_all counts 1", not deny(p.edit("src/rep.py", "foo", "bar", s)))
s = fresh(p); check("count: Edit 6 lines then 6 lines in the same file: second refused", not deny(p.edit("src/app.py", "a", "1\n2\n3\n4\n5\n6", s)) and deny(p.edit("src/app.py", "b", "1\n2\n3\n4\n5\n6", s)))
s = fresh(p); check("count: Write over an existing file with one changed line is small", not deny(p.write("src/hundred.py", blk2, s)))
s = fresh(p); check("count: Write over an existing file with 30 new lines is refused", deny(p.write("src/hundred.py", BIG + "\n", s)))
s = fresh(p); check("count: Write of a new 3-line file is small", not deny(p.write("src/new3.py", "a\nb\nc\n", s)))
s = fresh(p); check("count: Write of a new 30-line file is refused", deny(p.write("src/new30.py", BIG, s)))
fp = str(p.P / "src/hundred.py")
s = fresh(p); check("count: MultiEdit of two 1-line edits is small", not deny(p.pre("MultiEdit", {"file_path": fp, "edits": [{"old_string": "line 1\n", "new_string": "L1\n"}, {"old_string": "line 2\n", "new_string": "L2\n"}]}, s)))
s = fresh(p); check("count: MultiEdit with 12 changed lines is refused", deny(p.pre("MultiEdit", {"file_path": fp, "edits": [{"old_string": "line 10\n", "new_string": "\n".join(f"n{i}" for i in range(12)) + "\n"}]}, s)))
s = fresh(p); check("count: MultiEdit applies edits in order (second edit builds on the first)", not deny(p.pre("MultiEdit", {"file_path": fp, "edits": [{"old_string": "line 3\n", "new_string": "tmp\n"}, {"old_string": "tmp\n", "new_string": "line 3\n"}]}, s)))
s = fresh(p); check("count: MultiEdit with an old_string not found sums the edits", deny(p.pre("MultiEdit", {"file_path": fp, "edits": [{"old_string": "nope1", "new_string": "\n".join("a" * (i + 1) for i in range(6))}, {"old_string": "nope2", "new_string": "\n".join("b" * (i + 1) for i in range(6))}]}, s)))
nb = {"cells": [{"id": "c1", "cell_type": "code", "source": ["a = 1\n", "b = 2\n", "c = 3\n"]}, {"id": "c2", "cell_type": "code", "source": "x\n"}]}
p.put("src/nb.ipynb", json.dumps(nb)); nbp = str(p.P / "src/nb.ipynb")
s = fresh(p); check("count: NotebookEdit replacing one line of a cell is small", not deny(p.pre("NotebookEdit", {"notebook_path": nbp, "cell_id": "c1", "new_source": "a = 1\nb = 9\nc = 3\n", "edit_mode": "replace"}, s)))
s = fresh(p); check("count: NotebookEdit insert of 30 lines is refused", deny(p.pre("NotebookEdit", {"notebook_path": nbp, "new_source": BIG, "edit_mode": "insert"}, s)))
s = fresh(p); check("count: NotebookEdit replacing a cell with 30 lines is refused", deny(p.pre("NotebookEdit", {"notebook_path": nbp, "cell_id": "c1", "new_source": BIG, "edit_mode": "replace"}, s)))
s = fresh(p); check("count: NotebookEdit deleting a 3-line cell is small", not deny(p.pre("NotebookEdit", {"notebook_path": nbp, "cell_id": "c1", "edit_mode": "delete"}, s)))
s = fresh(p); check("count: NotebookEdit with an unknown cell id is refused (unknown size)", deny(p.pre("NotebookEdit", {"notebook_path": nbp, "cell_id": "zzz", "new_source": "q", "edit_mode": "replace"}, s)))
p.put("src/huge.py", "x\n" * 5100)
s = fresh(p); check("count: file over 5000 lines counts as big even for a 1-line change", deny(p.write("src/huge.py", "x\n" * 5099 + "y\n", s)))
s = fresh(p); check("count: replace_all on a file over 5000 lines counts as big", deny(p.edit("src/huge.py", "x", "y", s, replace_all=True)))
(p.P / "src/bin.dat").write_bytes(b"\xff\xfe\x00\x80" * 10)
s = fresh(p); check("count: undecodable file counts as big", deny(p.write("src/bin.dat", "text\n", s)))

# ---- Stop: one block per new set of outside files (step 5)
def stopfile(p, sid="s1", path="src/gen.py"):
    p.put(path, "z\n")
p = mk()
p.prompt(); stopfile(p)
o = p.stop()
check("outside: strict blocks, names the file and an engineer, says what to do", deny(o) and "src/gen.py" in text(o) and "builder-backend" in text(o) and "tell the owner" in text(o), o)
check("outside: logged as outside_team", any(e["event"] == "outside_team" for e in p.events()))
check("outside: the next stop (stop_hook_active) passes", not deny(p.stop(active=True)))
check("outside: same file in a later turn is not blocked again", (p.prompt("more") or True) and not deny(p.stop()))
p.put("src/gen2.tsx", "q\n")
o = p.stop()
check("outside: a new file is blocked, the old one is not named", deny(o) and "gen2.tsx" in text(o) and "gen.py" not in text(o) and "builder-frontend" in text(o), o)

p = mk()
p.prompt(); stopfile(p)
p.post("Edit", {"file_path": str(p.P / "src/app.py")}, agent="backend-engineer")
o = p.stop()
check("outside + missing QA: ONE message with both", deny(o) and "verifier" in text(o) and "src/gen.py" in text(o) and "Agents changed files" in text(o), o)
check("outside + missing QA: counted per kind", p.state()["refusals"] == {"done_without_qa": 1, "outside_team": 1}, p.state().get("refusals"))
o = p.stop()
check("outside + QA: second stop blocks for QA only", deny(o) and "gen.py" not in text(o), o)
p.put("src/gen3.py", "q\n"); o = p.stop()
check("outside: a new file after the first block, QA still missing: blocked (2nd of each kind)", deny(o) and "gen3.py" in text(o), o)
p.put("src/gen4.py", "q\n"); o = p.stop()
check("outside: third block of a kind in one turn is a note only", not deny(o) and "third time" in note(o) and "gen4.py" in note(o), o)

p = mk()
p.prompt(); stopfile(p)
p.level("warn"); p.prompt("again"); o = p.stop()
check("outside: warn level is a note only", not deny(o) and "warn-only" in note(o) and "src/gen.py" in note(o), o)
p.level("off"); p.put("src/gen9.py", "q\n")
check("outside: off is silent", p.stop() == {})

p = mk()
p.prompt("just do it"); stopfile(p)
check("outside: just-do-it lifts the block", not deny(p.stop()))

p = mk()
p.put("src/owner.py", "o\n"); p.prompt()
check("outside: a file the owner edited before the session (baseline) is not blocked", not deny(p.stop()))

p = mk()
p.prompt(sid="A"); p.prompt(sid="B")
p.post("Edit", {"file_path": str(p.P / "src/a.py")}, sid="A", agent="backend-engineer"); p.put("src/a.py", "a\n")
p.sub_stop("qa-engineer", "A")
check("outside: A's engineer file does not block session B", not deny(p.stop("B")))

# ---- env overrides (step 6)
p = mk()
EO = dict(p.ENV, SHIPMIRACLE_FLOW_LEVEL="off"); p.level("strict")
check("SHIPMIRACLE_FLOW_LEVEL=off does not turn the gate off", deny(p.hook("PreToolUse", env=EO, tool_name="ExitPlanMode", tool_input={})))
EW = dict(p.ENV, SHIPMIRACLE_FLOW_LEVEL="warn")
o = p.hook("PreToolUse", env=EW, tool_name="ExitPlanMode", tool_input={})
check("SHIPMIRACLE_FLOW_LEVEL=warn turns a strict project into warn", not deny(o) and "warn-only" in note(o), o)
p.level("off")
check("SHIPMIRACLE_FLOW_LEVEL=strict overrides an off project", deny(p.hook("PreToolUse", env=dict(p.ENV, SHIPMIRACLE_FLOW_LEVEL="strict"), tool_name="ExitPlanMode", tool_input={})))
check("SHIPMIRACLE_FLOW_LEVEL=bogus is ignored", p.hook("PreToolUse", env=dict(p.ENV, SHIPMIRACLE_FLOW_LEVEL="bogus"), tool_name="ExitPlanMode", tool_input={}) == {})
p.level("strict")
capd = p.T / "cap"; EC = dict(p.ENV, SHIPMIRACLE_FLOW_CAPTURE=str(capd))
p.hook("PreToolUse", env=EC, sid="real-sid", transcript_path="/secret/t.jsonl", tool_name="Write", tool_input={"file_path": str(p.P / "src/x.py"), "content": "c"}, agent_id="a1", agent_type="backend-engineer")
p.hook("PreToolUse", env=EC, sid="real-sid", transcript_path="/secret/t.jsonl", tool_name="Write", tool_input={"file_path": str(p.P / "src/x.py"), "content": "c"})
p.hook("PostToolUse", env=EC, tool_name="Write", tool_input={"file_path": str(p.P / "src/x.py")}, agent_id="a1", agent_type="backend-engineer")
names = sorted(x.name for x in capd.iterdir()) if capd.exists() else []
check("capture writes <event>-<main|agent>.json", names == ["posttooluse-agent.json", "pretooluse-agent.json", "pretooluse-main.json"], names)
cj = json.load(open(capd / "pretooluse-agent.json"))
check("capture: no transcript_path, session and cwd redacted, project paths relative", "transcript_path" not in cj and cj["session_id"] == "SESSION" and cj["cwd"] == "PROJECT"
      and cj["tool_input"]["file_path"] == "PROJECT/src/x.py" and cj["agent_type"] == "backend-engineer" and str(p.P) not in json.dumps(cj), cj)
cm = json.load(open(capd / "pretooluse-main.json"))
check("capture: content replaced by its length, keys kept, file_path kept", cm["tool_input"]["content"] == "<1 chars>" and "file_path" in cm["tool_input"], cm)
p.hook("UserPromptSubmit", env=EC, prompt="my secret prompt " + str(pathlib.Path.home()))
p.hook("PreToolUse", env=EC, tool_name="Bash", tool_input={"command": "echo " + str(pathlib.Path.home()) + "/x", "file_path": str(pathlib.Path.home()) + "/note.txt", "edits": [{"old_string": "aaa", "new_string": "bbbb"}], "long": "y" * 300})
cb = json.load(open(capd / "pretooluse-main.json")); cu = json.load(open(capd / "userpromptsubmit-main.json"))
check("capture: prompt is never captured", cu["prompt"].startswith("<") and "secret" not in json.dumps(cu), cu)
check("capture: command, edits[*] and long strings become '<N chars>'; HOME becomes ~", cb["tool_input"]["command"].startswith("<") and cb["tool_input"]["edits"][0] == {"old_string": "<3 chars>", "new_string": "<4 chars>"}
      and cb["tool_input"]["long"] == "<300 chars>" and cb["tool_input"]["file_path"] == "~/note.txt" and str(pathlib.Path.home()) not in json.dumps(cb), cb)
check("capture: overwrites, never appends", json.load(open(capd / "pretooluse-agent.json")) == cj)
r = p.run_raw(json.dumps({"hook_event_name": "PreToolUse", "session_id": "s", "cwd": str(p.P), "tool_name": "ExitPlanMode", "tool_input": {}}), dict(p.ENV, SHIPMIRACLE_FLOW_CAPTURE="/dev/null/nope"))
check("capture to an unwritable place never raises", r.returncode == 0 and p.errors() == "", p.errors())


# ---- gate tamper (fix 1)
p = mk()
HOMEC = os.path.expanduser("~/.claude")
targets = {"state dir": p.STATE / "flow.x.json", "config/flow.json": p.WSF / "config/flow.json", "hooks/": p.WSF / F.HK / "new.sh",
           "~/.claude/settings.json": pathlib.Path(HOMEC) / "settings.json", "~/.claude/settings.local.json": pathlib.Path(HOMEC) / "settings.local.json",
           "project settings.json": p.P / ".claude/settings.json", "project settings.local.json": p.P / ".claude/settings.local.json"}
p.prompt()
for n, t in targets.items():
    ok = all(deny(x) for x in (p.pre("Edit", {"file_path": str(t), "old_string": "a", "new_string": "b"}), p.pre("Write", {"file_path": str(t), "content": "x"}),
                               p.pre("MultiEdit", {"file_path": str(t), "edits": [{"old_string": "a", "new_string": "b"}]}),
                               p.pre("NotebookEdit", {"notebook_path": str(t), "new_source": "x", "edit_mode": "insert"})))
    check(f"tamper: main chat Edit/Write/MultiEdit/NotebookEdit of {n} refused", ok)
    check(f"tamper: Bash write to {n} refused", deny(p.bash(f"echo x > '{t}'")))
check("tamper: reason is plain", "ask the owner to change them" in text(p.pre("Write", {"file_path": str(p.WSF / "hooks/x"), "content": "x"})))
check("tamper: logged as gate_tamper", any(e["event"] == "gate_tamper" for e in p.events()))
for cmd in (f"cp /tmp/x {p.WSF}/hooks/flow-gate.sh", f"rm {p.WSF}/hooks/flow-gate.sh", f"sed -i '' s/a/b/ {p.WSF}/config/flow.json", f"mv /tmp/x {p.STATE}/flow-events.jsonl",
            'echo x > "$HOME/.claude/settings.json"', 'echo x > ~/.claude/settings.local.json', f"echo x | tee {p.P}/.claude/settings.json", f"cd {p.WSF}/hooks && echo x > a.sh"):
    check("tamper: Bash " + cmd[:60] + " refused", deny(p.bash(cmd)), cmd)
check("tamper: reading the gate files from Bash is allowed", not deny(p.bash(f"cat {p.WSF}/config/flow.json ~/.claude/settings.json; ls {p.WSF}/hooks")))
res = [p.pre("Write", {"file_path": str(p.WSF / "hooks/x"), "content": "x"}) for _ in range(5)]
check("tamper: no refusal cap (5 in a row all refused)", all(deny(x) for x in res))
p.edit("src/app.py", "a", BIG); p.edit("src/app.py", "a", BIG)
p.prompt("just do it")
check("tamper: 'just do it' does not lift it", deny(p.pre("Write", {"file_path": str(p.WSF / "hooks/x"), "content": "x"})) and deny(p.bash(f"echo x > {p.WSF}/config/flow.json")))
check("tamper: small fix allowance does not apply", (p.prompt("n") or True) and deny(p.pre("Edit", {"file_path": str(p.WSF / "config/flow.json"), "old_string": "a", "new_string": "b"})))
check("F3 tamper: an agent may NOT edit hooks, config or settings (event carries the agent type)", deny(p.pre("Write", {"file_path": str(p.WSF / "hooks/x"), "content": "x"}, agent="backend-engineer"))
      and deny(p.pre("Edit", {"file_path": str(p.WSF / "config/flow.json"), "old_string": "a", "new_string": "b"}, agent="qa-engineer"))
      and deny(p.pre("Bash", {"command": f"echo x > {p.WSF}/hooks/a.sh"}, agent="backend-engineer"))
      and any(e["event"] == "gate_tamper" and e.get("agent") == "backend-engineer" for e in p.events()))
ET = dict(p.ENV, SHIPMIRACLE_FLOW_TAMPER_OK="1")
check("F3 tamper: SHIPMIRACLE_FLOW_TAMPER_OK=1 in the hook environment lets an agent edit hooks, but not the main chat",
      not deny(p.hook("PreToolUse", env=ET, tool_name="Write", tool_input={"file_path": str(p.WSF / "hooks/x"), "content": "x"}, agent_id="a", agent_type="backend-engineer"))
      and deny(p.hook("PreToolUse", env=ET, tool_name="Write", tool_input={"file_path": str(p.WSF / "hooks/x"), "content": "x"})))
check("F3 tamper: an agent may still write a good agent file", not deny(p.write(".claude/agents/new-role.md", GOOD, agent="backend-engineer")))
p.level("warn"); p.prompt("n")
check("tamper: warn level still refuses", deny(p.pre("Write", {"file_path": str(p.WSF / "hooks/x"), "content": "x"})))
p.level("off"); p.prompt("n")
check("tamper: off level is silent", p.pre("Write", {"file_path": str(p.WSF / "hooks/x"), "content": "x"}) == {})
p.level("strict")

# ---- large input (fix 2)
p = mk()
p.prompt()
bigsrc = "x = 1\n" * 270000
raw = json.dumps({"hook_event_name": "PreToolUse", "session_id": "s1", "cwd": str(p.P), "tool_name": "Write", "tool_input": {"file_path": str(p.P / "src/huge_new.py"), "content": bigsrc}})
t0 = time.time(); r = p.run_raw(raw)
check(f"large input: a 1.6 MB main-chat Write of source is REFUSED, not silently allowed ({len(raw)} bytes, {time.time() - t0:.1f}s)", len(raw) > 1600000 and r.returncode == 0 and r.stdout.strip() and deny(json.loads(r.stdout)), (r.returncode, r.stdout[:200], r.stderr[:200]))
e0 = len(p.errors())
raw = json.dumps({"hook_event_name": "UserPromptSubmit", "session_id": "s1", "cwd": str(p.P), "prompt": "word " * 600000})
r = p.run_raw(raw)
check("large input: a 3 MB prompt does not crash (exit 0, no error logged, turn reset)", len(raw) > 3000000 and r.returncode == 0 and len(p.errors()) == e0 and p.state().get("refusals") == {}, (r.returncode, p.errors()))
if F.IMPL == "legacy":          # the shell wrapper only: the dispatcher shim starts /usr/bin/python3 by absolute path
    tb = p.T / "nopy"; tb.mkdir()
    for n in ("cat", "mkdir", "date", "bash"):
        os.symlink(shutil.which(n), tb / n)
    r = subprocess.run(["/bin/bash", str(F.HOOK)], input="{}", capture_output=True, text=True, env=dict(p.ENV, PATH=str(tb)))
    check("python3 cannot start: exit 0 and a line in flow-errors.log", r.returncode == 0 and "python3 failed to start (exit 127)" in p.errors(), (r.returncode, p.errors()))

# ---- held lock (fix 14)
import fcntl
p = mk()
p.prompt(sid="lk")
lf = open(p.STATE / "flow.lk.json.lock", "w"); fcntl.flock(lf, fcntl.LOCK_EX)
t0 = time.time(); o = p.hook("PreToolUse", "lk", tool_name="ExitPlanMode", tool_input={}); dt = time.time() - t0
lf.close()
check(f"held lock: hook waits about 3 s, then fails open WITHOUT the lock and still answers correctly (took {dt:.1f}s)", 2.8 < dt < 4.5 and deny(o), (dt, o))
check("held lock: nothing in the error log", p.errors() == "", p.errors())

# ---- dirty() failing in UserPromptSubmit (fix 5)
p = mk()
tb = p.T / "nogit"; tb.mkdir()
for n in ("cat", "mkdir", "date", "bash"):
    os.symlink(shutil.which(n), tb / n)
os.symlink(os.path.realpath(sys.executable), tb / "python3")
Eng = dict(p.ENV, PATH=str(tb))
r = p.run_raw(json.dumps({"hook_event_name": "UserPromptSubmit", "session_id": "ng", "cwd": str(p.P), "prompt": "do x, just do it"}), Eng)
stn = p.state("ng")
check("dirty() failure: the turn is still reset and saved (bypass set), baseline left unset", r.returncode == 0 and stn.get("bypass") is True and stn.get("refusals") == {} and "baseline" not in stn, (r.returncode, r.stderr[:200], stn))
p.run_raw(json.dumps({"hook_event_name": "UserPromptSubmit", "session_id": "ng2", "cwd": str(p.P), "prompt": "plain"}), Eng)
p.put("src/pre.py", "p\n")
o = p.stop("ng2")
check("dirty() failure: the state was saved; the next Stop sets the baseline and flags nothing", "refusals" in p.state("ng2") and not deny(o) and "src/pre.py" in p.state("ng2").get("baseline", []), (o, p.state("ng2")))

# ---- mixed cap (fix 6)
p = mk()
p.prompt()
p.post("Edit", {"file_path": str(p.P / "src/app.py")}, agent="backend-engineer")
p.stop(); p.stop()
p.put("src/mix.py", "m\n")
o = p.stop()
check("mixed cap: QA capped + outside live: blocks for the files and carries the QA text as a note", deny(o) and "mix.py" in text(o) and "Agents changed files" in text(o) and "Note" in text(o), o)
check("mixed cap: the capped kind is logged as done_without_qa_capped", any(e["event"] == "done_without_qa_capped" for e in p.events()), [e["event"] for e in p.events()])

# ---- hand-backs and 'just do it' (fix 8)
for n, t in (("[Subagent hand-back] prefix", "  [Subagent hand-back] report: just do it"), ("<system-reminder prefix", "<system-reminder>just do it</system-reminder>"),
             ("<task-notification prefix", "<task-notification>just do it"), ("<agent-message prefix", "<agent-message>just do it"),
             ("<agent-message from= within 200 chars", "Result follows. <agent-message from=\"x\"> just do it")):
    p = mk(); p.prompt(); p.hook("UserPromptSubmit", prompt=t)
    check(f"hand-back form ({n}): not the owner (no bypass, agent_message logged)", not p.state().get("bypass") and any(e["event"] == "agent_message" for e in p.events()) and not any(e["event"] == "bypass" for e in p.events()))
p = mk(); p.prompt()
p.hook("UserPromptSubmit", prompt="x" * 250 + "<agent-message from=")
check("hand-back marker after 200 chars is not a hand-back", not any(e["event"] == "agent_message" for e in p.events()))
for n, t, exp in (("plain", "please, just do it", True), ("apostrophes", "don't ask, just do it, it's urgent", True), ("after 300 chars", "x " * 160 + "just do it", False),
                  ("inside a fenced block", "log:\n```\njust do it\n```\nthanks", False), ("unterminated fence", "```\njust do it", False),
                  ("inside double quotes", 'he said "just do it" to me', False), ("inside single quotes", "the phrase 'just do it' is magic", False),
                  ("after a closed fence", "```\nx\n```\njust do it", True)):
    p = mk(); p.prompt(t)
    check(f"just do it ({n}): bypass is {exp}", bool(p.state().get("bypass")) == exp, p.state().get("bypass"))

# ---- build agent credit (fix 9)
p = mk()
p.prompt()
p.put("src/viaShell.py", "z\n")
o1 = p.stop()
p.sub_stop("backend-engineer"); p.sub_stop("qa-engineer")
st = p.state()
check("agent stop does not credit a file already reported outside the team", "src/viaShell.py" not in st.get("agent_edits", []) and "src/viaShell.py" in st.get("outside", []) and deny(o1), st)
p.prompt("again"); o2 = p.stop()
check("... and it is not blocked a second time", not deny(o2) and "src/viaShell.py" in p.state().get("outside", []), o2)

# ---- paths (fix 10)
if sys.platform == "darwin" and os.path.exists(str(p.P).swapcase()):
    p = mk(); p.prompt()
    o = p.pre("Edit", {"file_path": str(p.P).swapcase() + "/src/app.py", "old_string": "a", "new_string": BIG})
    check("darwin: a path with different letter case is still inside the project (refused)", deny(o), o)
    check("darwin: ... and a record file in other case is still allowed", not deny(p.pre("Edit", {"file_path": str(p.P).swapcase() + "/DOCS/status.md", "old_string": "a", "new_string": BIG})))
    check("darwin: project folder given in other case is still enforced", deny(p.hook("PreToolUse", env=dict(p.ENV, CLAUDE_PROJECT_DIR=str(p.P).swapcase()), tool_name="ExitPlanMode", tool_input={})))
else:
    print("SKIP darwin case-insensitive path tests (not macOS or case-sensitive file system)")
p = mk(); p.prompt()
check("count: a new file of one 3500-char line (500 statements) is not one line", deny(p.write("src/oneline.py", "a = 1; " * 500)))
check("count: a short one-line new file is still small", not deny(p.write("src/short.py", "a = 1\n")))
p.prompt("n")
check("count: an Edit adding one 3500-char line is refused", deny(p.edit("src/app.py", "x = 1", "a = 1; " * 500)))

# ---- F1: python runs isolated (-I)
import re as _re
p = mk(); p.prompt()
for n in ("glob", "shlex", "json"):
    p.put(f"{n}.py", 'open("PWNED-%s", "w").write("x")\nraise SystemExit(3)\n' % n)
p.run_cwd = str(p.P)                                             # Claude Code starts hooks in the project folder
o = p.pre("Write", {"file_path": str(p.WSF / "hooks/x"), "content": "x"})
check("F1 project with glob.py/shlex.py/json.py: the gate still refuses a tamper attempt", deny(o), o)
check("F1 ... and no marker file was created by the planted modules", not any(x.name.startswith("PWNED") for x in p.P.iterdir()), os.listdir(p.P))
p.run_cwd = None
pp = p.T / "pypath"; pp.mkdir(); (pp / "json.py").write_text('open(%r, "w").write("x")\nraise SystemExit(3)\n' % str(pp / "PWNED"))
o = p.hook("PreToolUse", env=dict(p.ENV, PYTHONPATH=str(pp)), tool_name="Write", tool_input={"file_path": str(p.WSF / "hooks/x"), "content": "x"})
check("F1 PYTHONPATH with a json.py does not matter", deny(o) and not (pp / "PWNED").exists(), o)
if (F.WS / F.HK / "plan-capture.sh").exists():          # the legacy shell hooks exist only in the owner's checkout
    bad = []
    for hf in sorted((F.WS / F.HK).glob("*.sh")):
        for ln, line in enumerate(hf.read_text().splitlines(), 1):
            if _re.search(r"(?<![\w\"'-])python3 (?!-I)", _re.sub(r"\s#.*$", "", line)) and not line.lstrip().startswith("#") and "failed to start" not in line:
                bad.append(f"{hf.name}:{ln}")
    check("F1 every hook starts python with -I", not bad, bad)
    hm = p.T / "hhome"; (hm / ".local/state/shipmiracle").mkdir(parents=True); (hm / "Developer/pj").mkdir(parents=True)
    (hm / "Developer/pj/json.py").write_text('open("PWNED", "w").write("x")\nraise SystemExit(3)\n')
    r = subprocess.run(["bash", str(F.WS / F.HK / "plan-capture.sh")], input=json.dumps({"cwd": str(hm / "Developer/pj"), "rate_limits": {"a": 1}}), capture_output=True, text=True,
                       env=dict(os.environ, HOME=str(hm), PYTHONPATH=str(pp)), cwd=str(hm / "Developer/pj"))
    check("F1 plan-capture.sh works from a project with a planted json.py (plan.json written, no marker)", r.returncode == 0 and (hm / ".local/state/shipmiracle/plan.json").exists() and not (hm / "Developer/pj/PWNED").exists(), r.stderr)
    r = subprocess.run(["bash", str(F.WS / F.HK / "guard-hook.sh")], input=json.dumps({"hook_event_name": "UserPromptSubmit", "cwd": str(hm / "Developer/pj")}), capture_output=True, text=True,
                       env=dict(os.environ, HOME=str(hm)), cwd=str(hm / "Developer/pj"))
    check("F1 guard-hook.sh works from a project with a planted json.py (user-active touched, no marker)", r.returncode == 0 and (hm / ".local/state/shipmiracle/user-active").exists() and not (hm / "Developer/pj/PWNED").exists(), r.stderr)

# ---- F2: .claude and .claude/agents are protected
p = mk(); p.prompt()
cmds = ["rm -rf .claude/agents", "rm .claude/agents/qa-engineer.md", "mv .claude/agents /tmp/a", "mv .claude/agents/qa-engineer.md /tmp/", "rmdir .claude/agents", "rm -rf .claude",
        "mv .claude .claude.bak", "echo x > .claude/agents/qa-engineer.md", f"rm -rf {p.P}/.claude/agents", "cd .claude && rm -rf agents", "unlink .claude/agents/qa-engineer.md"]
for c in cmds:
    p.prompt("n"); o = p.bash(c)
    check("F2 main chat Bash refused: " + c, deny(o) and "control the team-flow" in text(o), o)
p.prompt("n")
check("F2 Edit/Write of a non-agent file inside .claude/agents refused", deny(p.write(".claude/agents/notes.txt", "x")) and deny(p.write(".claude/agents/sub/a.md", GOOD)))
check("F2 Write of a good agent .md is still allowed (model rule)", not deny(p.write(".claude/agents/new-role.md", GOOD)))
p.level("warn"); p.prompt("n")
check("F2 warn level still refuses", deny(p.bash("rm -rf .claude/agents")))
p.level("off"); p.prompt("n")
check("F2 off level is silent", p.bash("rm -rf .claude/agents") == {})
p.level("strict"); p.prompt("just do it")
check("F2 just do it does not lift it, and there is no cap", all(deny(p.bash("rm -rf .claude/agents")) for _ in range(4)))
check("F2 agents may not remove it either", deny(p.pre("Bash", {"command": "rm -rf .claude/agents"}, agent="backend-engineer")))

# ---- F3 is covered in the tamper block; F4a zsh redirects, F4b integrity
HM = None
p = mk(); HM = p.T / "home"; (HM / ".claude").mkdir(parents=True); (HM / ".claude/settings.json").write_text("{}")
(p.WSF / "hooks").mkdir(); (p.WSF / F.GATE_REL).write_text("#!/bin/bash\n")
EH = dict(p.ENV, HOME=str(HM))
def hk(ev_, sid="s1", **kw): return p.hook(ev_, sid, env=EH, **kw)
hk("UserPromptSubmit", prompt="go")
small = dict(tool_name="Edit", tool_input={"file_path": str(p.P / "docs/STATUS.md"), "old_string": "a", "new_string": "b"})
check("F4b nothing changed: tool call passes", not deny(hk("PreToolUse", **small)))
(p.WSF / F.GATE_REL).touch()
check("F4b only the mtime changed: passes", not deny(hk("PreToolUse", **small)))
(p.WSF / F.GATE_REL).write_text("#!/bin/bash\nexit 1\n")
res = [hk("PreToolUse", **small) for _ in range(5)]
check("F4b a gate file changed: every main-chat tool call is blocked (no cap), plain message names the file", all(deny(x) for x in res) and "flow-gate.sh" in text(res[0]) and "Tell the owner or revert it" in text(res[0]), res[0])
check("F4b ... logged once", [e["event"] for e in p.events()].count("gate_tamper_detected") == 1)
check("F4b ... a subagent is not blocked by it", not deny(hk("PreToolUse", tool_name="Bash", tool_input={"command": "ls"}, agent_id="a", agent_type="backend-engineer")))
o1 = hk("Stop", stop_hook_active=False); o2 = hk("Stop", stop_hook_active=False); o3 = hk("Stop", stop_hook_active=True)
check("F4b ... Stop is blocked once per change (the retry passes, never loops)", deny(o1) and not deny(o2) and not deny(o3), (o1, o2, o3))
hk("UserPromptSubmit", prompt="x"); (p.WSF / F.GATE_REL).write_text("#!/bin/bash\nexit 2\n")
hk("UserPromptSubmit", prompt="just do it")
hk("UserPromptSubmit", prompt="ok, continue")
check("F4b the owner's next message re-baselines", not deny(hk("PreToolUse", **small)))
(p.WSF / F.HK / "new.sh").write_text("x")
check("F4b a new file under hooks/ is a change", deny(hk("PreToolUse", **small)))
hk("UserPromptSubmit", prompt="ok")
os.remove(p.WSF / F.HK / "new.sh")
check("F4b a deleted gate file is a change", deny(hk("PreToolUse", **small)))
hk("UserPromptSubmit", prompt="ok"); (HM / ".claude/settings.json").write_text('{"model":"opus","x":1}')
check("M1 ~/.claude/settings.json: a model change does not block", not deny(hk("PreToolUse", **small)))
(HM / ".claude/settings.json").write_text('{"model":"opus","permissions":{"allow":["Bash(ls)"]}}')
(p.P / ".claude/settings.local.json").write_text('{"permissions":{"allow":["Bash(ls:*)"]}}')
(p.WSF / "hooks/.DS_Store").write_text("junk"); (p.WSF / "hooks/notes.txt").write_text("n"); (p.WSF / "hooks/.hidden.sh").write_text("h")
check("M1 permissions in settings(.local).json, .DS_Store / notes / dotfiles in hooks/ do not block", not deny(hk("PreToolUse", **small)))
hk("UserPromptSubmit", prompt="ok"); (HM / ".claude/settings.json").write_text('{"model":"opus","hooks":{"PreToolUse":[{"hooks":[{"command":"x"}]}]}}')
check("M1 ~/.claude/settings.json: a new hook entry blocks", deny(hk("PreToolUse", **small)))
hk("UserPromptSubmit", prompt="ok"); (HM / ".claude/settings.json").write_text('{"hooks":{"PreToolUse":[{"hooks":[{"command":"x"}]}]},"disableAllHooks":true}')
check("M1 disableAllHooks:true blocks", deny(hk("PreToolUse", **small)))
hk("UserPromptSubmit", prompt="ok"); (HM / ".claude/settings.json").write_text('{"hooks":{"PreToolUse":[{"hooks":[{"command":"x"}]}]},"disableAllHooks":true,"env":{"SHIPMIRACLE_QUIET":"1"}}')
check("M1 an env change blocks", deny(hk("PreToolUse", **small)))
hk("UserPromptSubmit", prompt="ok"); (HM / ".claude/settings.json").write_text("{not json")
check("M1 a file that parsed before and no longer parses blocks", deny(hk("PreToolUse", **small)))
hk("UserPromptSubmit", prompt="ok"); (HM / ".claude/settings.json").write_text("{still not json")
check("M1 a file that was already unparseable does not block", not deny(hk("PreToolUse", **small)))
hk("UserPromptSubmit", prompt="ok"); (p.P / ".claude/settings.local.json").write_text('{"hooks":{"Stop":[]}}')
check("M1 <project>/.claude/settings.local.json with hooks blocks", deny(hk("PreToolUse", **small)))
hk("UserPromptSubmit", prompt="ok"); os.remove(p.P / ".claude/settings.local.json"); (p.P / ".claude/settings.local.json").write_text('{"permissions":{}}')
hk("UserPromptSubmit", prompt="ok"); (p.P / ".claude/settings.json").write_text('{"model":"x"}')
check("M1 creating a project settings.json without hooks/env does not block", not deny(hk("PreToolUse", **small)))
(p.P / ".claude/hooks").mkdir(); (p.P / ".claude/hooks/a.sh").write_text("#!/bin/bash\n"); hk("UserPromptSubmit", prompt="ok")
(p.P / ".claude/hooks/a.sh").write_text("#!/bin/bash\nexit 1\n")
check("M1/M2b a changed <project>/.claude/hooks/*.sh blocks", deny(hk("PreToolUse", **small)))
hk("UserPromptSubmit", prompt="ok"); (p.P / ".claude/hooks/b.sh").write_text("x")
check("M1/M2b a new <project>/.claude/hooks/*.sh blocks", deny(hk("PreToolUse", **small)))
hk("UserPromptSubmit", prompt="ok"); (p.P / ".claude/hooks/.DS_Store").write_text("x"); (p.P / ".claude/hooks/README.md").write_text("x")
check("M1 non-.sh files in <project>/.claude/hooks do not block", not deny(hk("PreToolUse", **small)))
hk("UserPromptSubmit", prompt="ok"); shutil.rmtree(p.P / ".claude/agents")
check("F4b/M1 .claude/agents vanished", deny(hk("PreToolUse", **small)))
hk("UserPromptSubmit", prompt="ok"); (p.WSF / "config/flow.json").write_text(json.dumps({"default": "strict", "n": 1}))
o = hk("Stop", stop_hook_active=False)
check("F4b Stop is blocked once with the message", deny(o) and "changed since your last message" in text(o), o)
check("F4b ... the second Stop (stop_hook_active) passes", not deny(hk("Stop", stop_hook_active=True)))
p.level("off"); p.prompt("n"); (p.WSF / F.GATE_REL).write_text("zzz")
check("F4b off level is silent", p.pre("Edit", small["tool_input"]) == {} and hk("PreToolUse", **small) == {})
p.level("warn"); hk("UserPromptSubmit", prompt="ok"); (p.WSF / F.GATE_REL).write_text("zzzz")
ow_ = hk("PreToolUse", **small)
check("M1 warn level: a note (once per change), not a block", not deny(ow_) and "changed since your last message" in note(ow_) and "warn-only" in note(ow_), ow_)
check("M1 warn level: the note is not repeated for the same change", "changed since" not in note(hk("PreToolUse", **small)))
ow2_ = hk("Stop", stop_hook_active=False)
check("M1 warn level: Stop is not blocked", not deny(ow2_), ow2_)
hk("UserPromptSubmit", prompt="ok"); (p.WSF / "config/flow.json").write_text(json.dumps({"default": "warn", "n": 2}))
ow3_ = hk("Stop", stop_hook_active=False)
check("M1 warn level: a Stop-only change gives a systemMessage note", not deny(ow3_) and "changed since your last message" in note(ow3_), ow3_)

# ---- F5 env override events, F7, F8
p = mk()
E5 = {k: v for k, v in p.ENV.items() if k != "SHIPMIRACLE_TEST"}
p.hook("UserPromptSubmit", env=E5, prompt="hi"); p.hook("PreToolUse", env=E5, tool_name="Bash", tool_input={"command": "ls"})
ev5 = [e for e in p.events() if e["event"] == "gate_env_override"]
check("F5 env overrides outside tests: one gate_env_override event per session, with the variable names", len(ev5) == 1 and "SHIPMIRACLE_STATE" in ev5[0]["vars"], p.events())
p = mk(); p.prompt(); p.pre("Bash", {"command": "ls"})
check("F5 SHIPMIRACLE_TEST=1 silences it", not any(e["event"] == "gate_env_override" for e in p.events()))
hq = p.T / "qhome"; (hq / "Developer/pj/.claude/agents").mkdir(parents=True); (hq / ".local/state/shipmiracle").mkdir(parents=True)
EQ = dict(os.environ, HOME=str(hq), SHIPMIRACLE_QUIET="1", CLAUDE_PROJECT_DIR=str(hq / "Developer/pj")); EQ.pop("SHIPMIRACLE_TEST", None)
r = subprocess.run(["bash", str(F.HOOK)], input=json.dumps({"hook_event_name": "PreToolUse", "session_id": "q1", "tool_name": "Bash", "tool_input": {}}), capture_output=True, text=True, env=EQ)
r2 = subprocess.run(["bash", str(F.HOOK)], input=json.dumps({"hook_event_name": "PreToolUse", "session_id": "q1", "tool_name": "Bash", "tool_input": {}}), capture_output=True, text=True, env=EQ)
evq = (hq / ".local/state/shipmiracle/flow-events.jsonl").read_text() if (hq / ".local/state/shipmiracle/flow-events.jsonl").exists() else ""
check("F5 SHIPMIRACLE_QUIET: still silent, exit 0, but a tool call from a real project is noted once", r.returncode == 0 and r.stdout == "" and r2.stdout == "" and evq.count("gate_env_override") == 1, evq)
p = mk(); p.prompt("please SECRET-PROMPT-TEXT just do it")
check("F7 bypass is logged without the prompt text", any(e["event"] == "bypass" for e in p.events()) and "SECRET-PROMPT" not in (p.STATE / "flow-events.jsonl").read_text())
p = mk(); p.prompt()
for at in ("../agents/qa-engineer", "x/../qa-engineer", "agents/../agents/qa-engineer", "a/b"):
    p.sub_stop(at)
check("F8 an agent_type with / or .. has no role", "qa_ts" not in p.state(), p.state())
p.sub_stop("qa-engineer")
check("F8 ... a plain name still works", "qa_ts" in p.state())

# ---- F6 / D-2 capture allow-list
p = mk()
capd = p.T / "cap2"; EC = dict(p.ENV, SHIPMIRACLE_FLOW_CAPTURE=str(capd))
SEC = "sk-SECRET-TOKEN-123"
payload = dict(tool_name="Bash", tool_input={"command": SEC, "file_path": str(p.P / "src/a.py"), "description": SEC, "old_string": SEC, "weird": [SEC, {"deep": SEC}], "replace_all": True},
               tool_response={"stdout": SEC}, last_assistant_message=SEC, description=SEC, structuredPatch=[SEC], originalFile=SEC, lines=[SEC], oldString=SEC, newString=SEC,
               agent_transcript_path="/Users/x/" + SEC, transcript_path="/t/" + SEC, extra_key=SEC, prompt=SEC, permission_mode="acceptEdits", prompt_id="pid", tool_use_id="tid", agent_id="ag", agent_type="qa-engineer")
p.hook("PreToolUse", env=EC, **payload)
cj = json.load(open(capd / "pretooluse-agent.json")); cs = json.dumps(cj)
check("F6 no secret-looking string survives anywhere in the capture", SEC not in cs and "/Users/x" not in cs and "SECRET" not in cs, cs)
check("F6 dropped keys are gone", not any(k in cj for k in ("tool_response", "last_assistant_message", "description", "structuredPatch", "originalFile", "lines", "oldString", "newString", "agent_transcript_path", "transcript_path")), cs)
check("F6 allow-listed keys kept, other strings become '<N chars>'", cj["tool_name"] == "Bash" and cj["agent_type"] == "qa-engineer" and cj["permission_mode"] == "acceptEdits" and cj["prompt_id"] == "pid" and cj["tool_use_id"] == "tid"
      and cj["tool_input"]["file_path"] == "PROJECT/src/a.py" and cj["tool_input"]["replace_all"] is True and cj["extra_key"].startswith("<") and cj["tool_input"]["command"] == "<%d chars>" % len(SEC)
      and "description" not in cj["tool_input"] and cj["tool_input"]["weird"][1]["deep"].startswith("<") and cj["session_id"] == "SESSION" and cj["cwd"] == "PROJECT", cs)

# ---- D-5 non-string paths
p = mk(); p.prompt()
BADV = [["a"], {"a": 1}, 5, None, True, 1.5]
for tool_ in ("Edit", "Write", "MultiEdit", "NotebookEdit", "Bash", "ExitPlanMode"):
    for key in ("file_path", "notebook_path", "command", "content", "old_string", "new_string", "edits", "new_source", "cell_id"):
        for v in BADV:
            for ag_ in (None, "backend-engineer"):
                p.pre(tool_, {key: v, "file_path": str(p.P / "src/app.py")} if key != "file_path" else {key: v}, agent=ag_)
p.pre("MultiEdit", {"file_path": str(p.P / "src/app.py"), "edits": [{"old_string": ["x"], "new_string": 5}, "str", None]})
p.pre("Write", {"file_path": str(p.P / ".claude/agents/z.md"), "content": ["x"]}); p.pre("Write", {"file_path": str(p.P / ".claude/agents/z.md"), "content": ["x"]}, agent="backend-engineer")
p.pre("Edit", {"file_path": str(p.P / ".claude/agents/z.md"), "old_string": ["x"], "new_string": {"a": 1}}, agent="backend-engineer")
for v in BADV:
    p.hook("PostToolUse", tool_name="Write", tool_input={"file_path": v}, agent_id="a", agent_type="backend-engineer")
    p.hook("PreToolUse", tool_name="Bash", tool_input={"command": "ls"}, cwd=v)
    p.hook("PreToolUse", tool_name=v, tool_input={}, agent_type=v, agent_id="a")
check("D-5 file_path/notebook_path/command/... as list, dict, number, None: nothing in flow-errors.log", p.errors() == "", p.errors())

# ---- fixture replay
fx = pathlib.Path(__file__).resolve().parent / "fixtures/flow"
fa, fm = fx / "pretooluse-agent.json", fx / "pretooluse-main.json"
if fa.exists() and fm.exists():
    p = mk(); p.prompt("go", "fx")
    def replay(f, as_edit=False, drop_agent=False):
        dd = json.loads(f.read_text().replace("PROJECT", str(p.P)).replace("SESSION", "fx"))
        ti_ = dd.setdefault("tool_input", {})                    # captured payloads keep no content: the content is added here
        if as_edit or not dd.get("agent_id"):                    # an Edit of src/app.py with 30 changed lines (the real main payload edits docs/STATUS.md, a record file)
            dd["tool_name"] = "Edit"; ti_["file_path"] = str(p.P / "src/app.py")
        ti_["content"] = BIG; ti_["new_string"] = BIG; ti_["old_string"] = "x = 1"
        if drop_agent:
            dd.pop("agent_id", None); dd.pop("agent_type", None)
        r = p.run_raw(json.dumps(dd)); return json.loads(r.stdout) if r.stdout.strip() else {}
    check("fixture replay: the agent payload is allowed", not deny(replay(fa)))
    check("fixture replay: the agent payload as a 30-line source Edit is allowed (agent_id present)", not deny(replay(fa, as_edit=True)))
    p.prompt("go", "fx")
    check("fixture replay: the same payload WITHOUT agent_id is refused (the agent/main difference is agent_id)", deny(replay(fa, as_edit=True, drop_agent=True)))
    p.prompt("go", "fx")
    check("fixture replay: the main-chat payload is refused in strict", deny(replay(fm)))
else:
    print("SKIP fixture replay (fixtures not captured yet: run tests/private/flow_live_test.sh --capture)")

# ---- M2 / M2b gate paths by path component
p = mk(); p.prompt("n")
HC = os.path.expanduser("~/.claude")
for n_, t_ in (("<project>/.claude/hooks/x.sh (new)", p.P / ".claude/hooks/x.sh"), ("~/.claude/hooks/x.sh", pathlib.Path(HC) / "hooks" "/x.sh"), ("<WS>/hooks/x", p.WSF / "hooks/x"),
               ("<WS>/config/flow.json", p.WSF / "config/flow.json"), ("state dir", p.STATE / "x.json"), ("<project>/.claude/settings.local.json", p.P / ".claude/settings.local.json"),
               ("~/.claude/settings.json", pathlib.Path(HC) / "settings.json")):
    for ag_ in (None, "backend-engineer"):
        check(f"M2 Write to {n_} refused ({ag_ or 'main chat'})", deny(p.pre("Write", {"file_path": str(t_), "content": "x"}, agent=ag_)))
    check(f"M2 python -c to {n_} refused", deny(p.bash(f"""python3 -c "open('{t_}','w').write('x')" """)))
    check(f"M2 zsh >! to {n_} refused", deny(p.bash(f"echo x >! '{t_}'")))
for ag_ in (None, "backend-engineer"):
    for pth_ in ("src/hooks/useX.ts", ".claude-backup/x.json", ".vscode/settings.json"):
        o_ = p.pre("Write", {"file_path": str(p.P / pth_), "content": "x"}, agent=ag_)
        check(f"M2 Write to {pth_} is not a gate path ({ag_ or 'main chat'})", "control the team-flow" not in text(o_), o_)
    check(f"M2 /tmp/settings.json via python is allowed ({ag_ or 'main chat'})", "control the team-flow" not in text(p.pre("Bash", {"command": """python3 -c "open('/tmp/settings.json','w')" """}, agent=ag_)))
check("M2b removing .claude/agents through rm is still refused", deny(p.bash("rm -rf .claude/agents")))

# ---- minor 5: SHIPMIRACLE_QUIET compares the project parent folder case-insensitively
if sys.platform == "darwin" and os.path.exists(str(hq / "DEVELOPER/pj")):
    (hq / ".local/state/shipmiracle/flow-events.jsonl").unlink()
    EQ2 = dict(EQ, CLAUDE_PROJECT_DIR=str(hq / "DEVELOPER/pj"))
    subprocess.run(["bash", str(F.HOOK)], input=json.dumps({"hook_event_name": "PreToolUse", "session_id": "q2", "tool_name": "Bash", "tool_input": {}}), capture_output=True, text=True, env=EQ2)
    evq2 = (hq / ".local/state/shipmiracle/flow-events.jsonl").read_text() if (hq / ".local/state/shipmiracle/flow-events.jsonl").exists() else ""
    check("minor5 SHIPMIRACLE_QUIET with ~/DEVELOPER/pj (other case) is noted like ~/Developer/pj", evq2.count("gate_env_override") == 1, evq2)
else:
    print("SKIP SHIPMIRACLE_QUIET case test (not macOS or case-sensitive file system)")

for q in projects: q.cleanup()
print("ALL PASS" if not fails else "FAILED %s" % fails); sys.exit(1 if fails else 0)
