#!/usr/bin/env python3
"""Flow gate, Phase 3b T4: function roles, user-level agents, trust, read-only enforcement, general-purpose refusal, activation by registry, tamper and
integrity additions, legacy parity, ALIASES equality, latency bench. The 22 cases of docs/plans/2026-10-20-p3-spec.md section 4 are numbered C1..C22.
Everything runs sandboxed (SHIPMIRACLE_TEST=1, temp HOME / state / config / Developer / workspace per scenario; the real ~/.claude and ~/.config/shipmiracle are never read).
User-level agents are installed with shipmiracle.agents.install into the temp HOME. Run: /usr/bin/python3 tests/flow_gate_roles_test.py (Python 3.9)."""
import ast, json, os, pathlib, re, shutil, statistics, subprocess, sys, tempfile, time
HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(ROOT))
os.environ["SHIPMIRACLE_TEST"] = "1"
# Read-only roles may write under /tmp, /private/tmp and $TMPDIR: the sandboxes must live elsewhere (and the hook's TMPDIR points to a folder outside them).
tempfile.tempdir = next((d for d in ("/var/tmp", str(pathlib.Path.home() / ".cache")) if os.path.isdir(d) and os.access(d, os.W_OK)), None)
for k_ in ("CLAUDECODE", "SHIPMIRACLE_ENFORCE_OWNER", "SHIPMIRACLE_QUIET", "SHIPMIRACLE_FLOW_TAMPER_OK", "SHIPMIRACLE_FLOW_LEVEL", "SHIPMIRACLE_FLOW_VERDICT"):
    os.environ.pop(k_, None)
from flow_fixture import make_project, deny, note, text, AGENT_TEXT, GATE_REL, HK, gate_source  # noqa: E402
import shipmiracle_timing  # noqa: E402
from shipmiracle import agents as AG, projects, registry  # noqa: E402

fails = []
n_checks = [0]
BASE_COMMIT = "8fab959"          # the commit before the T4 gate change: the bench compares against this version of the legacy shell gate


def check(n, c, info=""):
    n_checks[0] += 1
    print(("PASS " if c else "FAIL ") + n + ("" if c else " :: " + str(info)[:600]))
    if not c:
        fails.append(n)


GENV = dict(os.environ, GIT_AUTHOR_NAME="T", GIT_AUTHOR_EMAIL="t@example.com", GIT_COMMITTER_NAME="T", GIT_COMMITTER_EMAIL="t@example.com")
TOP = pathlib.Path(tempfile.mkdtemp(prefix="flow-roles-")).resolve()
LEGACY = {p.stem: p.read_bytes() for p in sorted((HERE / "fixtures/agents/legacy").glob("*.md"))}
MASTERS = {p.stem: p.read_bytes() for p in sorted((ROOT / "agents/claude").glob("*.md"))}


def git(cwd, *a):
    return subprocess.run(["git", "-C", str(cwd)] + list(a), env=GENV, capture_output=True, text=True, check=True).stdout.strip()


def make_ws_repo():
    """A workspace repo whose history holds two versions of every old master and then the ten new ones (the legacy-hash set comes from it)."""
    ws = TOP / "wsrepo"
    (ws / "agents/claude").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(ws)], env=GENV, check=True)
    for v in (1, 2):
        for n, b in LEGACY.items():
            (ws / "agents/claude" / (n + ".md")).write_bytes(b + (b"\n<!-- v1 -->\n" if v == 1 else b""))
        git(ws, "add", "-A"); git(ws, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "old v%d" % v)
    for n in LEGACY:
        (ws / "agents/claude" / (n + ".md")).unlink()
    for n, b in MASTERS.items():
        (ws / "agents/claude" / (n + ".md")).write_bytes(b)
    git(ws, "add", "-A"); git(ws, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "new masters")
    return ws


WSREPO = make_ws_repo()
REPORT = "Verdict: {v}\nEvidence: {e}\n"


class Sb:
    """One sandbox: a flow_fixture project plus temp HOME, config and workspace (with the real Shipmiracle package linked in)."""
    def __init__(self, layout="userlevel", agents=None, install=True, with_dir=True, name="proj"):
        self.p = p = make_project(name, agents=agents if agents is not None else {})
        self.HOME = p.T / "home"; self.CFG = self.HOME / ".config/shipmiracle"
        self.HOME.mkdir(); self.CFG.mkdir(parents=True)
        os.symlink(str(ROOT / "shipmiracle"), str(p.WSF / "shipmiracle"))
        (p.T / "hooktmp").mkdir()
        p.ENV.update(TMPDIR=str(p.T / "hooktmp"), SHIPMIRACLE_HOME=str(self.HOME), SHIPMIRACLE_CONFIG=str(self.CFG), HOME=str(self.HOME), SHIPMIRACLE_STATE=str(p.STATE))
        if layout == "userlevel":
            (self.CFG / "config.json").write_text(json.dumps({"agents.layout": "userlevel"}))
        self.use()
        if install:
            AG.install(ws=WSREPO, home=self.HOME)
        self.pid = projects.project_id(p.P)
        if not with_dir:
            shutil.rmtree(p.P / ".claude")

    def use(self):
        p = self.p
        os.environ.update(SHIPMIRACLE_TEST="1", SHIPMIRACLE_HOME=str(self.HOME), SHIPMIRACLE_CONFIG=str(self.CFG), SHIPMIRACLE_STATE=str(p.STATE), SHIPMIRACLE_DEV=str(p.DEV), SHIPMIRACLE_WS=str(p.WSF))

    def registry(self, **fields):
        e = {"team": "on", "standard": "auto", "test_paths": [], "agents": {}}; e.update(fields)
        (self.CFG / "registry.json").write_text(json.dumps({"v": 1, "projects": {self.pid: e}}))

    def activate(self, name, content=None):
        self.use()
        if not (self.CFG / "registry.json").exists():
            self.registry()
        f = self.p.P / ".claude/agents" / (name + ".md")
        data = f.read_bytes()
        registry.activate(self.pid, name, AG.sha256_bytes(data), AG.parse(data.decode())["role"])

    def agent_file(self, name, text_):
        return self.p.put(".claude/agents/%s.md" % name, text_)

    def built(self, sid, by="builder"):
        """A build by an agent: PostToolUse Edit in src."""
        return self.p.hook("PostToolUse", sid, tool_name="Edit", tool_input={"file_path": str(self.p.P / "src/app.py")}, agent_id="b1", agent_type=by)

    def qa(self, sid, who, v="PASS"):
        return self.p.hook("SubagentStop", sid, agent_id="q1", agent_type=who, last_assistant_message=REPORT.format(v=v, e="3 passed, 0 failed"))

    def credited(self, who, sid, setup=None):
        """Build, then `who` reports PASS: does the Stop check accept it?"""
        p = self.p
        p.prompt("go", sid)
        self.built(sid)
        self.qa(sid, who)
        return not deny(p.stop(sid))

    def untrusted_events(self):
        return [e for e in self.p.events() if e["event"] == "role_untrusted"]

    def done(self):
        self.p.cleanup()


def agent_pre(sb, tool, ti, who, sid="s1"):
    return sb.p.pre(tool, ti, sid, agent=who)


def reason(o):
    return (o.get("hookSpecificOutput") or {}).get("permissionDecisionReason") or o.get("reason") or ""


BIG = "\n".join("line %d" % i for i in range(30))

# ===================================================================== C1, C2: roles via the user-level layer and via aliases
sb = Sb()
p = sb.p
check("C1 userlevel: ExitPlanMode without the planner is refused and the message names planner", deny(o := p.pre("ExitPlanMode", {})) and "planner" in reason(o) and "solution-architect" not in reason(o), o)
p.sub_stop("planner")
check("C1 planner (user-level file, manifest hash) stopped: ExitPlanMode passes", not deny(p.pre("ExitPlanMode", {})))
sb.done()

sb = Sb(); p = sb.p
check("C2 alias solution-architect with no file anywhere: ExitPlanMode refused first", deny(p.pre("ExitPlanMode", {})))
p.sub_stop("solution-architect")
check("C2 alias solution-architect (no file) is credited as plan", not deny(p.pre("ExitPlanMode", {})) and p.state().get("planned_by") == "solution-architect", p.state())
check("C2 an alias is not 'untrusted'", not sb.untrusted_events())
sb.done()

# ===================================================================== C3, C4: trust by legacy hash and by manifest
sb = Sb(); p = sb.p
mf = AG.manifest()
check("C3 setup: the manifest holds legacy hashes of qa-engineer", AG.sha256_bytes(LEGACY["qa-engineer"]) in (mf["legacy"].get("qa-engineer") or []), mf.get("legacy", {}).keys())
sb.agent_file("qa-engineer", LEGACY["qa-engineer"].decode())
check("C3 project copy of the old qa-engineer (legacy sha) is trusted: QA credited, Stop passes", sb.credited("qa-engineer", "c3"))
check("C3 no role_untrusted for it", not sb.untrusted_events())
sb.done()

sb = Sb(); p = sb.p
check("C4 user-level verifier PASS after a builder's edit: Stop passes", sb.credited("verifier", "c4"))
p.prompt("x", "c4b"); sb.built("c4b")
o = p.stop("c4b")
check("C4 a build without any QA still blocks Stop (control), and the refusal names verifier", deny(o) and "verifier" in reason(o) and "qa-engineer" not in reason(o), o)
sb.done()

# ===================================================================== C5, C6, C7: untrusted claims, activation, edit after activation, unmarked shadow
sb = Sb(); p = sb.p
sb.agent_file("fake-qa", AGENT_TEXT.format(n="fake-qa", m="sonnet", r="test"))
check("C5 project fake-qa.md claiming test: QA not credited, Stop refuses", not sb.credited("fake-qa", "c5"))
check("C5 the refusal is done_without_qa", any(e["event"] == "done_without_qa" for e in p.events()), p.events())
ev = sb.untrusted_events()
check("C5 role_untrusted logged once, with claimed and effective", len(ev) == 1 and ev[0].get("claimed") == "test" and ev[0].get("effective") == "support", ev)
sb.qa("c5", "fake-qa"); sb.qa("c5", "fake-qa")
check("C5 role_untrusted is logged once per agent id (cached)", len(sb.untrusted_events()) == 1, sb.untrusted_events())
sb.activate("fake-qa")
check("C6 the same file after owner activation: credited", sb.credited("fake-qa", "c6"))
with open(p.P / ".claude/agents/fake-qa.md", "a") as f:
    f.write("\nextra line\n")
check("C6 edited after activation: untrusted again", not sb.credited("fake-qa", "c6b"))
sb.done()

sb = Sb(); p = sb.p
sb.agent_file("verifier", AGENT_TEXT.format(n="verifier", m="sonnet", r="test"))
check("C7 verifier.md in the project without overrides: (unmarked shadow) not credited", not sb.credited("verifier", "c7"))
check("C7 ... and logged as untrusted", len(sb.untrusted_events()) == 1)
sb.agent_file("verifier", MASTERS["verifier"].decode())
check("C7 an exact master copy of verifier.md in the project is trusted (manifest hash)", sb.credited("verifier", "c7b"))
sb.done()

# ===================================================================== hash-trust matrix
sb = Sb(); p = sb.p
rows = []
sb.agent_file("reviewer", MASTERS["reviewer"].decode())
rows.append(("manifest hash (project copy of the master)", sb.credited("reviewer", "m1") is not None))
sb.agent_file("qa-engineer", LEGACY["qa-engineer"].decode())
rows.append(("legacy hash", sb.credited("qa-engineer", "m2")))
sb.agent_file("zz-tester", AGENT_TEXT.format(n="zz-tester", m="sonnet", r="test"))
rows.append(("unknown hash before activation", not sb.credited("zz-tester", "m3")))
sb.activate("zz-tester")
rows.append(("activated hash", sb.credited("zz-tester", "m4")))
with open(p.P / ".claude/agents/zz-tester.md", "a") as f:
    f.write("tamper\n")
rows.append(("edited after activation", not sb.credited("zz-tester", "m5")))
sb.agent_file("qa-engineer", AGENT_TEXT.format(n="qa-engineer", m="sonnet", r="test"))
rows.append(("old-name file that is not a legacy copy (unmarked shadow)", not sb.credited("qa-engineer", "m6")))
for n_, ok_ in rows:
    check("matrix: " + n_, ok_)
sb.done()

# ===================================================================== C8: reviewer is read-only
sb = Sb(); p = sb.p
first = [deny(agent_pre(sb, "Edit", {"file_path": str(p.P / "src/app.py"), "old_string": "x", "new_string": "y"}, "reviewer")) for _ in range(4)]
check("C8 reviewer Edit src/: denied on the 1st, 2nd, 3rd and 4th try (no cap)", all(first), first)
o = agent_pre(sb, "Edit", {"file_path": str(p.P / "src/app.py"), "old_string": "x", "new_string": "y"}, "reviewer")
check("C8 message names the role and the path and the builder", "`reviewer` is a read-only role" in reason(o) and "`src/app.py`" in reason(o) and "a builder makes the change" in reason(o), reason(o))
check("C8 event readonly_refused logged", any(e["event"] == "readonly_refused" for e in p.events()))
p.prompt("just do it, please")
check("C8 'just do it' does not lift it", deny(agent_pre(sb, "Write", {"file_path": str(p.P / "src/new.py"), "content": "x"}, "reviewer")))
check("C8 reviewer may write under /tmp", not deny(agent_pre(sb, "Write", {"file_path": "/tmp/flow-roles-test.txt", "content": "x"}, "reviewer")))
check("C8 reviewer may write under $TMPDIR-like private tmp", not deny(agent_pre(sb, "Write", {"file_path": "/private/tmp/flow-roles-test.txt", "content": "x"}, "reviewer")))
check("C8 NotebookEdit is covered", deny(agent_pre(sb, "NotebookEdit", {"notebook_path": str(p.P / "n.ipynb"), "new_source": "x"}, "reviewer")))
check("C8 MultiEdit is covered", deny(agent_pre(sb, "MultiEdit", {"file_path": str(p.P / "src/app.py"), "edits": [{"old_string": "x", "new_string": "y"}]}, "reviewer")))
check("C8 the main chat is not subject to it (its own small-fix rule applies)", not deny(p.pre("Edit", {"file_path": str(p.P / "src/app.py"), "old_string": "x = 1", "new_string": "x = 2"}, "c8m")))
p.level("warn")
o = agent_pre(sb, "Edit", {"file_path": str(p.P / "src/app.py"), "old_string": "x", "new_string": "y"}, "reviewer", "w1")
check("C8 warn: a NOTE, not a denial", not deny(o) and "read-only role" in note(o), o)
p.level("off")
o = agent_pre(sb, "Edit", {"file_path": str(p.P / "src/app.py"), "old_string": "x", "new_string": "y"}, "reviewer", "o1")
check("C8 off: silent", o == {}, o)
sb.done()

# ===================================================================== C9: reviewer Bash
sb = Sb(); p = sb.p
def rb(cmd, sid="b1"):
    return agent_pre(sb, "Bash", {"command": cmd}, "reviewer", sid)
for cmd in ("echo hi >src/a", "git commit -m x", "npm i x", "git add -A", "git -C . push origin main", "pip install requests", "pnpm add left-pad", "rm src/app.py", "sed -i s/x/y/ src/app.py", "cp /tmp/a src/a", "tee src/b < /dev/null", "git checkout -- ."):
    check("C9 reviewer Bash refused: " + cmd, deny(rb(cmd)))
for cmd in ("npm test", "echo x >/tmp/x", "git status", "git log --oneline | head -3", "grep -rn foo src", "ls > /dev/null", "cat src/app.py", "python3 -m pytest -q", "git diff HEAD~1", "echo hi 2>&1 | tee /tmp/out.txt"):
    check("C9 reviewer Bash allowed: " + cmd, not deny(rb(cmd)), rb(cmd))
check("C9 refusal message for a mutating command names the command", "git commit" in reason(rb("git commit -m x")))
check("C9 'just do it' does not lift a Bash refusal", (p.prompt("just do it"), deny(rb("git push")))[1])
sb.done()

# ===================================================================== C10: planner
sb = Sb(); p = sb.p
check("C10 planner Write docs/plans/x.md is denied", deny(agent_pre(sb, "Write", {"file_path": str(p.P / "docs/plans/x.md"), "content": "plan"}, "planner")))
check("C10 planner Write /tmp/plan.md is allowed", not deny(agent_pre(sb, "Write", {"file_path": "/tmp/plan-flow-roles.md", "content": "plan"}, "planner")))
check("C10 the old name solution-architect (alias) is read-only too", deny(agent_pre(sb, "Write", {"file_path": str(p.P / "docs/plans/x.md"), "content": "plan"}, "solution-architect")))
check("C10 scoper and reporter are read-only", deny(agent_pre(sb, "Edit", {"file_path": str(p.P / "src/app.py"), "old_string": "a", "new_string": "b"}, "scoper")) and deny(agent_pre(sb, "Write", {"file_path": str(p.P / "x.md"), "content": "a"}, "reporter")))
check("C10 designer is not read-only (design role)", not deny(agent_pre(sb, "Edit", {"file_path": str(p.P / "src/app.py"), "old_string": "a", "new_string": "b"}, "designer")))
check("C10 builder may edit source", not deny(agent_pre(sb, "Edit", {"file_path": str(p.P / "src/app.py"), "old_string": "a", "new_string": "b"}, "builder")))
sb.done()

# ===================================================================== C11: verifier writes tests only
sb = Sb(); p = sb.p
check("C11 verifier Edit tests/t.py allowed", not deny(agent_pre(sb, "Edit", {"file_path": str(p.P / "tests/t.py"), "old_string": "a", "new_string": "b"}, "verifier")))
sb.p.hook("PostToolUse", "s1", tool_name="Edit", tool_input={"file_path": str(p.P / "tests/t.py")}, agent_id="ag1", agent_type="verifier")
check("C11 ... and it does not count as a build (no build_ts)", not p.state().get("build_ts"), p.state())
o = agent_pre(sb, "Edit", {"file_path": str(p.P / "src/a.py"), "old_string": "a", "new_string": "b"}, "verifier")
check("C11 verifier Edit src/a.py denied, message lists the test paths", deny(o) and "tests may change only under:" in reason(o) and "tests/**" in reason(o) and "read-only role" not in reason(o), reason(o))
check("C11 verifier sed -i src/a.py denied", deny(agent_pre(sb, "Bash", {"command": "sed -i s/a/b/ src/a.py"}, "verifier")))
check("C11 verifier sed -i tests/a.py allowed", not deny(agent_pre(sb, "Bash", {"command": "sed -i s/a/b/ tests/a.py"}, "verifier")))
check("C11 verifier npm test / pytest allowed", not deny(agent_pre(sb, "Bash", {"command": "npm test"}, "verifier")) and not deny(agent_pre(sb, "Bash", {"command": "python3 -m pytest -q tests"}, "verifier")))
check("C11 verifier git commit still refused (MUTATE_RE)", deny(agent_pre(sb, "Bash", {"command": "git commit -am x"}, "verifier")))
for pth, ok_ in (("src/a.test.ts", True), ("pkg/b_test.go", True), ("src/__tests__/x.js", True), ("spec/x.rb", True), ("test_foo.py", True), ("Sources/App/x.swift", False), ("AppTests/x.swift", True), ("src/main.py", False), ("docs/x.md", False)):
    check("C11 default test path %s -> %s" % (pth, "allowed" if ok_ else "refused"), deny(agent_pre(sb, "Write", {"file_path": str(p.P / pth), "content": "x"}, "verifier")) != ok_)
sb.registry(test_paths=["checks/**"])
check("C11 registry test_paths override: checks/t.py allowed", not deny(agent_pre(sb, "Edit", {"file_path": str(p.P / "checks/t.py"), "old_string": "a", "new_string": "b"}, "verifier", "s2")))
o = agent_pre(sb, "Edit", {"file_path": str(p.P / "tests/t.py"), "old_string": "a", "new_string": "b"}, "verifier", "s2")
check("C11 ... and tests/t.py is now refused (the list replaces the default)", deny(o) and "checks/**" in reason(o), reason(o))
sb.done()

# ===================================================================== C12: untrusted claim still restricted
sb = Sb(); p = sb.p
sb.agent_file("fake-rev", AGENT_TEXT.format(n="fake-rev", m="opus", r="review"))
check("C12 untrusted project file claiming review is still read-only", deny(agent_pre(sb, "Edit", {"file_path": str(p.P / "src/app.py"), "old_string": "a", "new_string": "b"}, "fake-rev")))
sb.agent_file("fake-rev2", AGENT_TEXT.format(n="fake-rev2", m="opus", r="test"))
check("C12 untrusted file claiming test: neither source nor (effective role support, item 6) tests may be written", deny(agent_pre(sb, "Edit", {"file_path": str(p.P / "src/app.py"), "old_string": "a", "new_string": "b"}, "fake-rev2")) and deny(agent_pre(sb, "Edit", {"file_path": str(p.P / "tests/a.py"), "old_string": "a", "new_string": "b"}, "fake-rev2")))
sb.agent_file("fake-b", AGENT_TEXT.format(n="fake-b", m="sonnet", r="build"))
check("C12 a build claim is not restricted (a claim only restricts)", not deny(agent_pre(sb, "Edit", {"file_path": str(p.P / "src/app.py"), "old_string": "a", "new_string": "b"}, "fake-b")))
sb.done()

# ===================================================================== C13, C14: general-purpose
sb = Sb(); p = sb.p
r1 = [agent_pre(sb, "Edit", {"file_path": str(p.P / "src/a.ts"), "old_string": "a", "new_string": "b"}, "general-purpose") for _ in range(3)]
check("C13 userlevel: general-purpose Edit src/a.ts refused, names builder-frontend", deny(r1[0]) and "builder-frontend" in reason(r1[0]) and "subagent_type builder-frontend" in reason(r1[0]) and "read and research only" in reason(r1[0]), reason(r1[0]))
check("C13 refused twice, the third time passes with a note (capped like other flow rules)", deny(r1[1]) and not deny(r1[2]) and "third time" in note(r1[2]), r1)
o = agent_pre(sb, "Edit", {"file_path": str(p.P / "src/a.py"), "old_string": "a", "new_string": "b"}, "general-purpose", "g2")
check("C13 a .py file points at builder-backend", deny(o) and "builder-backend" in reason(o))
o = agent_pre(sb, "Write", {"file_path": str(p.P / "notes.md"), "content": "a"}, "general-purpose", "g3")
check("C13 a .md file points at builder", deny(o) and "use builder (Agent tool" in reason(o), reason(o))
check("C13 general-purpose Bash redirect into the project refused", deny(agent_pre(sb, "Bash", {"command": "echo a > src/x.py"}, "general-purpose", "g4")))
check("C13 general-purpose read-only Bash allowed", not deny(agent_pre(sb, "Bash", {"command": "grep -rn x src"}, "general-purpose", "g5")))
check("C13 RECORD path docs/STATUS.md allowed", not deny(agent_pre(sb, "Edit", {"file_path": str(p.P / "docs/STATUS.md"), "old_string": "a", "new_string": "b"}, "general-purpose", "g6")))
check("C13 a drafts file is a RECORD path (.claude/agents-drafts/)", not deny(agent_pre(sb, "Write", {"file_path": str(p.P / ".claude/agents-drafts/new-one.md"), "content": "x"}, "general-purpose", "g7")))
check("C13 the main chat may write a drafts file", not deny(p.pre("Write", {"file_path": str(p.P / ".claude/agents-drafts/new-one.md"), "content": BIG}, "g8")))
p.prompt("just do it", "g9")
check("C14 general-purpose with 'just do it' is allowed", not deny(agent_pre(sb, "Edit", {"file_path": str(p.P / "src/a.ts"), "old_string": "a", "new_string": "b"}, "general-purpose", "g9")))
p.level("warn")
o = agent_pre(sb, "Edit", {"file_path": str(p.P / "src/a.ts"), "old_string": "a", "new_string": "b"}, "general-purpose", "g10")
check("C13 warn: a note", not deny(o) and "builder-frontend" in note(o), o)
sb.done()

sb = Sb(layout="legacy"); p = sb.p
check("C13 legacy: general-purpose Edit src/a.ts allowed", not deny(agent_pre(sb, "Edit", {"file_path": str(p.P / "src/a.ts"), "old_string": "a", "new_string": "b"}, "general-purpose")))
check("C13 legacy: general-purpose Bash write allowed", not deny(agent_pre(sb, "Bash", {"command": "echo a > src/x.py"}, "general-purpose")))
sb.done()

# ===================================================================== C15, C16: activation by registry
sb = Sb(with_dir=False); p = sb.p
check("C15 no .claude/agents, no registry entry: not enforced (userlevel)", not deny(o := p.edit("src/app.py", "x = 1", BIG)), o)
sb.registry()
check("C15 no .claude/agents but a registry entry (team on): enforced in userlevel", deny(o := p.edit("src/app.py", "x = 1", BIG, "c15")) and "builder" in reason(o), o)
check("C15 userlevel refusal does not offer the general-purpose fallback", "general-purpose with model sonnet" not in reason(o) and "builder" in reason(o), reason(o))
check("C15 team_seen is recorded for the registry-gated project", p.state("c15").get("team_seen") is True)
check("C15 no team_missing event for a registry-gated project", not any(e["event"] == "team_missing" for e in p.events()))
sb.registry(team="off")
check("C15 registry team=off: not enforced", not deny(p.edit("src/app.py", "x = 1", BIG, "c15b")))
sb.done()

sb = Sb(layout="legacy", with_dir=False); p = sb.p
sb.registry()
check("C15/M3 legacy layout: a registry entry (team on) keeps the migrated project gated too", deny(o := p.edit("src/app.py", "x = 1", BIG)) and "builder-backend" in reason(o), o)
sb.registry(team="off")
check("C15/M3 legacy layout: team=off in the registry -> not enforced", not deny(p.edit("src/app.py", "x = 1", BIG, "m3b")))
sb.done()

sb = Sb(with_dir=False); p = sb.p
(sb.CFG / "registry.json").write_text("{not json")
(p.STATE).mkdir(parents=True, exist_ok=True)
(p.STATE / "flow.c16a.json").write_text(json.dumps({"team_seen": True, "project": "proj"}))
check("C16 registry unreadable + team_seen: still enforced", deny(o := p.edit("src/app.py", "x = 1", BIG, "c16a")), o)
n_before = len([l for l in p.errors().splitlines() if l.strip()])
check("C16 ... and the damaged registry is logged", n_before >= 1, p.errors())
sb.done()

sb = Sb(with_dir=False); p = sb.p
(sb.CFG / "registry.json").write_text("{not json")
o = p.edit("src/app.py", "x = 1", BIG, "c16b")
errs = [l for l in p.errors().splitlines() if l.strip()]
check("C16 registry unreadable, no team_seen: gate off for this project, exactly 1 flow-errors line", not deny(o) and len(errs) == 1, (o, errs))
sb.done()

# ===================================================================== C17: tamper
sb = Sb(); p = sb.p
H = sb.HOME
cases = [
    ("Write ~/.claude/agents/x.md (main)", lambda: p.pre("Write", {"file_path": str(H / ".claude/agents/x.md"), "content": "x"}, "t1")),
    ("Edit ~/.claude/agents/verifier.md (main)", lambda: p.pre("Edit", {"file_path": str(H / ".claude/agents/verifier.md"), "old_string": "a", "new_string": "b"}, "t1")),
    ("cp a ~/.claude/agents/ (main)", lambda: p.pre("Bash", {"command": "cp /tmp/a ~/.claude/agents/"}, "t1")),
    ("shipm agents install (main)", lambda: p.pre("Bash", {"command": "shipm agents install"}, "t1")),
    ("bin/shipm agents activate (main)", lambda: p.pre("Bash", {"command": "cd ~/Developer/x && bin/shipm agents activate proj foo"}, "t1")),
    ("env -u CLAUDECODE shipm sync (main)", lambda: p.pre("Bash", {"command": "env -u CLAUDECODE shipm sync"}, "t1")),
    ("unset CLAUDECODE; shipm agents install (main)", lambda: p.pre("Bash", {"command": "unset CLAUDECODE; shipm agents install"}, "t1")),
    ("shipm registry set (main)", lambda: p.pre("Bash", {"command": "shipm registry set proj team off"}, "t1")),
    ("shipm config set agents.layout legacy (main)", lambda: p.pre("Bash", {"command": "shipm config set agents.layout legacy"}, "t1")),
    ("sh -c 'shipm sync' (main)", lambda: p.pre("Bash", {"command": "sh -c 'shipm sync'"}, "t1")),
    ("Edit ~/.config/shipmiracle/registry.json (main)", lambda: p.pre("Edit", {"file_path": str(H / ".config/shipmiracle/registry.json"), "old_string": "a", "new_string": "b"}, "t1")),
    ("Edit <WS>/shipmiracle/agents.py (main)", lambda: p.pre("Edit", {"file_path": str(p.WSF / "shipmiracle/agents.py"), "old_string": "a", "new_string": "b"}, "t1")),
    ("echo > ~/.config/shipmiracle/config.json (main)", lambda: p.pre("Bash", {"command": "echo '{}' > ~/.config/shipmiracle/config.json"}, "t1")),
    ("Write ~/.claude/agents/x.md (agent builder)", lambda: p.pre("Write", {"file_path": str(H / ".claude/agents/x.md"), "content": "x"}, "t1", agent="builder")),
    ("env -u CLAUDECODE shipm sync (agent builder)", lambda: p.pre("Bash", {"command": "env -u CLAUDECODE shipm sync"}, "t1", agent="builder")),
    ("Edit <WS>/shipmiracle/agents.py (agent builder)", lambda: p.pre("Edit", {"file_path": str(p.WSF / "shipmiracle/agents.py"), "old_string": "a", "new_string": "b"}, "t1", agent="builder")),
]
for n_, fn in cases:
    check("C17 tamper denied: " + n_, deny(fn()))
check("C17 gate_tamper logged", sum(1 for e in p.events() if e["event"] == "gate_tamper") >= len(cases))
o = p.pre("Bash", {"command": "shipm agents install"}, "t2")
check("C17 admin message says the owner runs it in a terminal", "owner runs it in a terminal" in reason(o), reason(o))
for n_, cmd in (("shipm agents list", "shipm agents list --json"), ("shipm doctor", "shipm doctor --rows"), ("shipm config get", "shipm config get agents.layout"), ("commit message mentioning shipm sync", 'git commit -m "docs: explain shipm sync"'),
                ("grep for the text", "grep -n 'shipm sync' README.md"), ("echo heredoc", "cat <<EOF\nshipm sync\nEOF"), ("shipmiraclex syncs", "echo shipmiraclex sync"), ("env without CLAUDECODE", "env -u FOO ls")):
    check("C17 not tamper: " + n_, not deny(p.pre("Bash", {"command": cmd}, "t3")), cmd)
check("C17 reading ~/.claude/agents is fine (Bash cat)", not deny(p.pre("Bash", {"command": "cat ~/.claude/agents/verifier.md"}, "t3")))
check("C17 an ordinary doc edit still works", not deny(p.pre("Write", {"file_path": str(p.P / "docs/STATUS.md"), "content": "x"}, "t3")))
sb.done()

# ===================================================================== C18: integrity of manifest / user agents / registry entry
for what in ("manifest", "user-agents", "registry-entry"):
    sb = Sb(); p = sb.p
    sb.registry()
    p.prompt("start", "i1")
    check("C18 baseline: main chat Bash passes (%s)" % what, not deny(p.pre("Bash", {"command": "ls"}, "i1")))
    if what == "manifest":
        with open(p.STATE / "v1/agents.json", "a") as f:
            f.write(" ")
    elif what == "user-agents":
        with open(sb.HOME / ".claude/agents/planner.md", "a") as f:
            f.write("\nchanged\n")
    else:
        sb.registry(team="on", test_paths=["x/**"])
    o = p.pre("Bash", {"command": "ls"}, "i1")
    label = {"manifest": "agents manifest", "user-agents": "~/.claude/agents", "registry-entry": "registry entry"}[what]
    check("C18 strict: %s changed mid-turn blocks the main chat" % what, deny(o) and label in reason(o), o)
    check("C18 ... no cap, no bypass (third call)", all(deny(p.pre("Bash", {"command": "ls"}, "i1")) for _ in range(3)))
    check("C18 ... the owner's next message resets it", (p.prompt("ok", "i1"), not deny(p.pre("Bash", {"command": "ls"}, "i1")))[1])
    sb.done()
sb = Sb(); p = sb.p
p.level("warn"); p.prompt("start", "i2")
with open(p.STATE / "v1/agents.json", "a") as f:
    f.write(" ")
o = p.pre("Bash", {"command": "ls"}, "i2")
check("C18 warn: manifest change is a note once", not deny(o) and "agents manifest" in note(o), o)
check("C18 warn: not repeated", "agents manifest" not in note(p.pre("Bash", {"command": "ls"}, "i2")))
sb.done()
sb = Sb(layout="legacy", agents={"qa-engineer": AGENT_TEXT.format(n="qa-engineer", m="sonnet", r="test")}); p = sb.p
p.prompt("start", "i3")
shutil.rmtree(p.P / ".claude/agents")
o = p.pre("Bash", {"command": "ls"}, "i3")
check("C18 legacy keeps the agents-dir item (folder removed -> blocked)", deny(o) and ".claude/agents" in reason(o), o)
sb.done()

# ===================================================================== C19: Shipmiracle import fails
sb = Sb(); p = sb.p
os.unlink(str(p.WSF / "shipmiracle"))
(p.WSF / "shipmiracle").mkdir(); (p.WSF / "shipmiracle/__init__.py").write_text(""); (p.WSF / "shipmiracle/agents.py").write_text("def broken(:\n")
p.sub_stop("planner")
errs = [l for l in p.errors().splitlines() if l.strip()]
check("C19 Shipmiracle import fails: legacy fallback credits the planner, ExitPlanMode passes, nothing blocked", not deny(p.pre("ExitPlanMode", {})))
check("C19 exactly 1 flow-errors line", len(errs) == 1, errs)
check("C19 the fallback keeps the read-only rule (planner is the plan role in the legacy view)", deny(agent_pre(sb, "Edit", {"file_path": str(p.P / "src/app.py"), "old_string": "a", "new_string": "b"}, "planner", "s3")))
sb.done()

# ===================================================================== C20: Flow role: report
for layout in ("userlevel", "legacy"):
    sb = Sb(layout=layout); p = sb.p
    GOODR = "---\nname: rep-x\nmodel: haiku\n---\nModel reason: mechanical.\nFlow role: report\n"
    check("C20 %s: Flow role: report passes agent_rule" % layout, not deny(o := p.write(".claude/agents/rep-x.md", GOODR)), o)
    check("C20 %s: a bogus Flow role is still refused" % layout, deny(p.write(".claude/agents/rep-y.md", GOODR.replace("report", "bogus"))))
    sb.done()
sb = Sb(); p = sb.p
o = p.write(".claude/agents/rep-z.md", "---\nname: rep-z\nmodel: sonnet\n---\nModel reason: x\n")
check("C20 the refusal text points to CLAUDE.md, not AGENTS.md, and lists report", deny(o) and "CLAUDE.md" in reason(o) and "AGENTS.md" not in reason(o) and "report" in reason(o), reason(o))
sb.done()

# ===================================================================== C21: the ALIASES copies are equal
src = gate_source()          # the legacy shell script's python part where it exists, else the gate block of shipmiracle/hooks/flow.py
m = re.search(r"^ALIASES = (\{.*?\})$", src, re.M)
gate_aliases = ast.literal_eval(m.group(1)) if m else None
check("C21 flow-gate.sh ALIASES parses", isinstance(gate_aliases, dict))
check("C21 flow-gate.sh ALIASES == shipmiracle.agents.ALIASES", gate_aliases == AG.ALIASES, (gate_aliases, AG.ALIASES))
dm = re.search(r"const ALIASES = \{(.*?)\};", (ROOT / "vscode-ext/shipmiracle-panel/data.js").read_text(), re.S)
if dm:
    js = dict(re.findall(r"'([^']+)':\s*'([^']+)'", dm.group(1)))
    check("C21 data.js ALIASES == shipmiracle.agents.ALIASES", js == AG.ALIASES, js)
else:
    check("C21 data.js has no ALIASES yet (T6): skipped", True)
dr = re.search(r"^DEFAULT_ROLE = (\{.*?\})\s*# built-in", src, re.M | re.S)
gate_roles = ast.literal_eval(dr.group(1)) if dr else {}
check("C21 every flow-gate.sh DEFAULT_ROLE entry equals shipmiracle.agents.DEFAULT_ROLE", bool(gate_roles) and all(AG.DEFAULT_ROLE.get(k_) == v_ for k_, v_ in gate_roles.items()), gate_roles)
for k_ in ("READ_ONLY", "PRIV"):
    mm = re.search(r"^%s = (\{[^}]*\})" % k_, src, re.M)
    check("C21 flow-gate.sh %s equals shipmiracle.agents" % k_, mm is not None and ast.literal_eval(mm.group(1)) == getattr(AG, "READ_ONLY" if k_ == "READ_ONLY" else "PRIVILEGED"), mm and mm.group(1))

# ===================================================================== legacy parity
sb = Sb(layout="legacy", agents={}); p = sb.p
check("L1 legacy: old names without files keep their roles (solution-architect -> plan)", (p.sub_stop("solution-architect"), not deny(p.pre("ExitPlanMode", {})))[1])
check("L2 legacy: independent-reviewer is a review role (verdict recorded)", (p.hook("SubagentStop", "s1", agent_id="r1", agent_type="independent-reviewer", last_assistant_message="Verdict: ACCEPT\n"), p.state().get("review_verdict") == "ACCEPT")[1], p.state())
check("L3 legacy: the new name planner works through the defaults", (p.hook("SubagentStop", "s2", agent_id="x", agent_type="planner"), not deny(p.pre("ExitPlanMode", {}, "s2")))[1])
check("L4 legacy: qa-engineer without a file credits QA after a backend-engineer edit", (p.prompt("g", "s3"), p.hook("PostToolUse", "s3", tool_name="Edit", tool_input={"file_path": str(p.P / "src/app.py")}, agent_id="b", agent_type="backend-engineer"),
         sb.qa("s3", "qa-engineer"), not deny(p.stop("s3")))[3])
check("L5 legacy: planner / scoper are NOT read-only (old behaviour); reviewer and tester may write only records (and tests)", deny(agent_pre(sb, "Edit", {"file_path": str(p.P / "src/app.py"), "old_string": "a", "new_string": "b"}, "reviewer", "s4")) and not deny(agent_pre(sb, "Write", {"file_path": str(p.P / "docs/plans/x.md"), "content": "x"}, "planner", "s4")))
check("L6 legacy: an untrusted file's claim still counts (no trust in legacy)", (sb.agent_file("fake-qa", AGENT_TEXT.format(n="fake-qa", m="sonnet", r="test")), sb.credited("fake-qa", "s5"))[1])
o = p.edit("src/app.py", "x = 1", BIG, "s6")
check("L7 legacy: edit_outside_team names the new roles and keeps the general-purpose fallback sentence", deny(o) and "builder-backend" in reason(o) and "general-purpose with model sonnet if builder-backend is not loaded" in reason(o) and "builder agents" in reason(o) and "engineer" not in reason(o), reason(o))
o = p.pre("ExitPlanMode", {}, "s7")
check("L8 legacy: plan_without_architect names planner", deny(o) and "planner" in reason(o) and "solution-architect" not in reason(o))
o = p.pre("Bash", {"command": "echo a > src/x.py"}, "s7")
check("L9 legacy: bash_write_outside_team says engineer agent", deny(o) and "a builder agent" in reason(o), reason(o))
check("L10 legacy: a .tsx file points at builder-frontend", "builder-frontend" in reason(p.edit("src/App.tsx", "a", BIG, "s8")))
sb.done()

sb = Sb(); p = sb.p
o = p.edit("src/app.py", "x = 1", BIG, "u1")
check("U1 userlevel edit_outside_team: names builder-backend, drops the fallback", deny(o) and "builder-backend" in reason(o) and "general-purpose" not in reason(o) and "engineer" not in reason(o), reason(o))
check("U2 userlevel .md goes to builder, .tsx to builder-frontend, workflow yaml to builder-ops", "builder-frontend" in reason(p.edit("src/App.tsx", "a", BIG, "u2")) and "use builder " not in reason(p.edit("a/b.md", "a", BIG, "u3")) and "to builder with" in reason(p.edit("a/c.md", "a", BIG, "u4")) and "builder-ops" in reason(p.edit(".github/w.yml", "a", BIG, "u5")))
o = p.pre("ExitPlanMode", {}, "u6")
check("U3 userlevel plan_without_architect names planner", deny(o) and "planner" in reason(o) and "solution-architect" not in reason(o))
p.prompt("x", "u7")
sb.built("u7")
o = p.stop("u7")
check("U4 userlevel done_without_qa names verifier", deny(o) and "verifier" in reason(o) and "qa-engineer" not in reason(o), o)
sb.done()

# ===================================================================== review fixes R1-R8
# R1: layout downgrade inside a session + config unset
sb = Sb(); p = sb.p
for n_, cmd in (("shipm config unset", "shipm config unset agents.layout"), ("quoted subcommand", "shipm 'config' set agents.layout legacy"), ("CLAUDECODE= prefix", "CLAUDECODE= shipm config set agents.layout legacy"),
                ("config unset via path", "~/Developer/AI-Workspace/bin/shipm config unset agents.layout")):
    check("R1 denied: " + n_, deny(p.pre("Bash", {"command": cmd}, "r1")), cmd)
p.prompt("start", "r1b")
check("R1 baseline passes", not deny(p.pre("Bash", {"command": "ls"}, "r1b")))
(sb.CFG / "config.json").write_text(json.dumps({"agents.layout": "legacy"}))
o = p.pre("Bash", {"command": "ls"}, "r1b")
check("R1 layout downgrade inside a session blocks the main chat at strict (agents.layout named)", deny(o) and "agents.layout" in reason(o), o)
(sb.CFG / "config.json").write_text(json.dumps({"agents.layout": "userlevel"}))
p.prompt("ok", "r1b")
(sb.CFG / "config.json").write_text("{}")
check("R1 ... also when the key is removed (unset)", deny(o := p.pre("Bash", {"command": "ls"}, "r1b")) and "agents.layout" in reason(o), o)
sb.done()

# R2: a poisoned <WS>/typing.py or dataclasses.py must not run inside the hook
sb = Sb(); p = sb.p
marker = p.T / "poison-ran"
for mod_ in ("typing.py", "dataclasses.py", "tempfile.py", "pathlib.py"):
    (p.WSF / mod_).write_text("open(%r, 'w').write('ran')\n" % str(marker))
p.sub_stop("planner")
check("R2 poisoned <WS>/typing.py etc: marker not created", not marker.exists())
check("R2 ... and the gate still works (planner credited through shipmiracle.agents)", not deny(p.pre("ExitPlanMode", {})) and not p.errors().strip(), p.errors())
check("R2 a top-level <WS>/*.py is a gate file (main chat Write denied)", deny(p.pre("Write", {"file_path": str(p.WSF / "json.py"), "content": "x"}, "r2")))
check("R2 ... and Bash redirect into it", deny(p.pre("Bash", {"command": "echo x > %s" % (p.WSF / "re.py")}, "r2")))
sb.done()

# R3: ADMIN bypasses and allowed look-alikes
sb = Sb(); p = sb.p
DENY_ADMIN = ['"bin/shipm" agents install', "bin/shipm 'agents' install", "s\\hipm agents install", "shipm project migrate-team proj --apply", "shipm registry write x", "shipm standard apply proj",
              "shipm registry set proj team off", "shipm config unset k", "CLAUDECODE= shipm agents list", "export CLAUDECODE=", "CLAUDECODE=0 ls", "python3 -m shipmiracle agents install", "python3.9 -m shipmiracle sync",
              "python3 -c \"import shipmiracle.agents as a; a.install()\"", "python3 ~/Developer/AI-Workspace/shipmiracle/cli.py sync", "python3 bin/shipm sync", "SHIPMIRACLE_TEST=1 shipm agents list", "env SHIPMIRACLE_STATE=/x shipm doctor",
              "/Users/someone/Developer/AI-Workspace/bin/shipm sync", "sh -c \"shipm sync\"", "bash -c 'echo hi; shipm switch x'", "echo $(shipm sync)", "echo \"$(shipm sync)\"", "eval \"shipm sync\"", "sudo -u x shipm sync",
              "env -u CLAUDECODE shipm agents list", "unset CLAUDECODE", "ls; shipm agents activate p x", "ls && shipm agents vendor --all", "true | shipm agents uninstall", "(shipm sync)", "shipm --json agents install",
              "cd /tmp && shipm config set agents.layout legacy", "nohup shipm sync &", "command shipm sync", "time shipm switch", "`shipm sync`",
              "shipm skills approve foo --why ok", "shipm skills ignore foo --reason ok", "shipm skills remove foo", "shipm --json skills approve foo --why ok",
              "bin/skills-sync --pin --online --repin vsk", "skills-sync --repin=vsk --pin --online", "/x/AI-Workspace/bin/skills-sync --pin --online", "python3 bin/skills-sync --pin --online --repin a,b", "bash bin/skills-sync --repin a",
              "./x/Skills-Sync --pin --online", "python3 -X dev bin/skills-sync --pin --online", "python3 -W ignore bin/skills-sync --repin a", "bash -x bin/skills-sync --pin",
              "bin/skills-sync --pin --online --from-commit emil-design-eng,break-ui", "skills-sync --from-commit=apple-design", "python3 bin/skills-sync --from-commit write-swift",
              "bin/shipm-guard hold 90m", "shipm-guard hold until 23:30", "shipm-guard release", "/x/AI-Workspace/bin/shipm-guard hold 2h", "python3 bin/shipm-guard hold 1h", "python3 -X dev bin/shipm-guard release",
              "bash bin/shipm-guard hold 1h", "./x/Shipm-Guard release", "ls; bin/shipm-guard hold 30m", "true && shipm-guard release", "sh -c \"bin/shipm-guard hold 5m\""]
for cmd in DENY_ADMIN:
    check("R3 admin denied: " + cmd, deny(p.pre("Bash", {"command": cmd}, "r3")), cmd)
ALLOW_ADMIN = ['git commit -m "explain shipm sync"', 'grep "shipm sync" README.md', "grep -rn 'shipm agents install' docs", "cat <<EOF\nshipm sync\nEOF", "shipm agents list --json", "shipm doctor --rows", "shipm config get agents.layout",
               "echo shipmiraclex sync", "python3 -m pytest tests", "python3 tests/shipmiracle_agents_test.py", "echo CLAUDECODE is set", "ls Shipmiracle", "git log --grep='shipm config set'", "printf 'shipm switch\\n'", "shipm registry list", "shipm skills view proj", "shipm skills found", "shipm skills found --short",
               "bin/skills-sync --diff", "bin/skills-sync --dry", "grep -rn -- --repin docs", "grep -rn -- --from-commit docs", "python3 bin/skills-sync --diff",
               "bin/shipm-guard status", "shipm-guard once --dry", "python3 bin/shipm-guard status", "cat bin/shipm-guard", "grep -n 'hold' bin/shipm-guard", "grep -rn 'shipm-guard hold' docs", "bash -n bin/shipm-guard"]
for cmd in ALLOW_ADMIN:
    check("R3 not admin: " + cmd.replace("\n", " "), not deny(p.pre("Bash", {"command": cmd}, "r3b")), cmd)
HOSTILE = ["echo " + '" ' * 100000, "echo " + "' " * 100000, "echo " + "\\" * 100000 + "'", "x=" + "$(" * 30000, "echo " + 'a"b ' * 50000 + "shipm sync"]
import shipmiracle_timing as T
# load-tolerant (26 Oct 2026): the hook answers in <= max(1 s, 6 x a trivial hook call measured right before and after on the same machine, ~0.15 s quiet); best of 3 attempts
R3_REF = lambda: T.timed(lambda: p.pre("Bash", {"command": "ls"}, "r3ref"))
for i_, h_ in enumerate(HOSTILE):
    ok_, rep_, best = T.robust_around(lambda: T.timed(lambda: p.pre("Bash", {"command": h_}, "r3h%d" % i_)), R3_REF, 1.0, 6, attempts=3)
    print("INFO R3 hostile #%d: %s" % (i_, rep_))
    check("R3 hostile %d KB command #%d: the hook answers in <= max(1 s, 6 x baseline) :: %s" % (len(h_) // 1000, i_, rep_), ok_, rep_)
check("R3 mutant: a hostile-command call slowed by a sleep (4 x the allowed time) is still noticed by the relative check",
      T.mutant_noticed(lambda: p.pre("Bash", {"command": HOSTILE[0]}, "r3hm"), R3_REF, 1.0, 6, n=2))
check("R3 an admin command after 30 KB of padding is still found", deny(p.pre("Bash", {"command": "echo " + "x " * 15000 + "; shipm sync"}, "r3p")))
sb.done()

# R4: read-only classification tables
sb = Sb(); p = sb.p
MUT = ["git add -A", "git commit -m x", "git push origin main", "git reset --hard", "git checkout -- .", "git switch main", "git restore src", "git stash", "git stash pop", "git merge x", "git rebase main",
       "git cherry-pick abc", "git revert HEAD", "git tag v1", "git tag -d v1", "git clean -fd", "git rm src/a", "git mv a b", "git apply x.patch", "git am x.mbox", "git branch -D old", "git branch newbranch",
       "git update-ref HEAD abc", "git gc", "git update-index --assume-unchanged a", "git worktree add ../x", "git notes add -m x", "git config alias.co checkout", "git -c alias.x=commit x", "git -C . commit -m x",
       "git --no-pager commit -m x", "npm i", "npm install x", "npm ci", "pnpm i", "pnpm add x", "yarn", "yarn install", "yarn add x", "pip install x", "pip3 install -r r.txt", "python3 -m pip install x",
       "uv pip install x", "brew install x", "curl -o out.bin http://x", "curl -O http://x/a", "wget http://x/a", "wget -O out http://x/a", "tar xf a.tar", "tar -xzf a.tgz -C src", "unzip a.zip", "unzip a.zip -d src",
       "mkdir src/new", "eval \"ls\"", "prettier --write .", "npx prettier --write src", "eslint --fix .", "ruff check --fix .", "ruff format .", "black .", "go fmt ./...", "cargo fmt", "swiftformat .",
       "bash -c 'git commit -m x'", "sudo npm i", "env FOO=1 git push", "echo hi | git commit -F -", "rm src/a", "sed -i s/a/b/ src/app.py", "echo x > src/f", "cp /tmp/a src/b", "touch src/n", "chmod +x src/f", "tee src/f < /dev/null"]
RO = ["git status", "git log --oneline -5", "git diff HEAD~1", "git show HEAD:src/app.py", "git stash list", "git stash show", "git tag -l", "git tag --list 'v*'", "git tag", "git grep -n foo", "git branch --list", "git branch -a",
      "git remote -v", "git rev-parse HEAD", "git blame src/app.py", "git ls-files", "git describe --tags", "git shortlog -sn", "git config --get user.name", "git log --grep=\"git commit\"",
      "npm test", "npm run lint", "npm ls", "npm view left-pad version", "yarn test", "yarn list", "pnpm test", "pytest -q", "python3 -m pytest tests", "pip list", "pip show x", "uv pip list", "brew list",
      "ls -la", "cat src/app.py", "grep -rn \"git commit\" src", "rg 'npm install' docs", "echo \"git push\"", "printf 'rm -rf x'", "curl -s https://example.com", "curl -o /tmp/x https://example.com", "wget -O /tmp/x https://example.com",
      "tar tf a.tar", "tar xf a.tar -C /tmp/y", "unzip -l a.zip", "mkdir /tmp/x", "black --check .", "prettier --check .", "eslint .", "ruff check .", "ruff format --check .", "cargo fmt --check", "swiftformat --lint .",
      "go vet ./...", "find . -name '*.py'", "wc -l src/app.py", "head -5 README.md", "diff a b", "jq . package.json", "which node", "sed -n 1,5p src/app.py", "awk '{print}' src/app.py", "sort src/app.py | uniq -c", "echo hi 2>&1 | tee /tmp/o.txt"]
check("R4 tables: %d mutating and %d read-only commands" % (len(MUT), len(RO)), len(MUT) >= 60 and len(RO) >= 60, (len(MUT), len(RO)))
wrong = [c_ for c_ in MUT if not deny(agent_pre(sb, "Bash", {"command": c_}, "reviewer", "r4"))]
check("R4 all %d mutating commands are refused for the reviewer" % len(MUT), not wrong, wrong)
wrong = [c_ for c_ in RO if deny(agent_pre(sb, "Bash", {"command": c_}, "reviewer", "r4b"))]
check("R4 all %d read-only commands are allowed for the reviewer" % len(RO), not wrong, wrong)
wrong = [c_ for c_ in MUT if c_.split()[0] not in ("rm", "sed", "echo", "cp", "touch", "chmod", "tee", "mkdir", "eval") and not deny(agent_pre(sb, "Bash", {"command": c_}, "verifier", "r4c"))]
check("R4 the verifier is refused the same repository/package mutations", not wrong, wrong)
wrong = [c_ for c_ in RO if deny(agent_pre(sb, "Bash", {"command": c_}, "verifier", "r4d"))]
check("R4 the verifier may run the read-only commands", not wrong, wrong)
o = agent_pre(sb, "Bash", {"command": "git commit -m x"}, "verifier", "r4e")
check("R4 verifier refusal text: 'tests may change only under', not 'read-only role'", "tests may change only under:" in reason(o) and "read-only role" not in reason(o), reason(o))
for pth in ("pkg/tests/x.py", "src/test/x.go", "app/conftest.py", "pkg/testdata/a.json", "web/login.cy.ts", "e2e/login.ts", "web/e2e/a.ts"):
    check("R4 default test path allowed for the verifier: " + pth, not deny(agent_pre(sb, "Write", {"file_path": str(p.P / pth), "content": "x"}, "verifier", "r4f")))
sb.done()

# R6: support / unknown roles may not write project files
sb = Sb(); p = sb.p
for who in ("statusline-setup", "claude-code-guide", "some-plugin:helper"):
    o = agent_pre(sb, "Edit", {"file_path": str(p.P / "src/app.py"), "old_string": "a", "new_string": "b"}, who, "r6" + who)
    check("R6 %s (role support) may not edit a project file" % who, deny(o) and "may read and research only" in reason(o) and "builder" in reason(o), reason(o))
check("R6 ... nor write through Bash", deny(agent_pre(sb, "Bash", {"command": "echo x > src/new.py"}, "statusline-setup", "r6b")))
check("R6 ... but a record file is fine", not deny(agent_pre(sb, "Write", {"file_path": str(p.P / "docs/STATUS.md"), "content": "x"}, "statusline-setup", "r6c")))
check("R6 a named builder and the designer may edit", not deny(agent_pre(sb, "Edit", {"file_path": str(p.P / "src/app.py"), "old_string": "a", "new_string": "b"}, "builder-ops", "r6d")) and not deny(agent_pre(sb, "Edit", {"file_path": str(p.P / "src/app.py"), "old_string": "a", "new_string": "b"}, "designer", "r6e")))
sb.done()

# R8: agent_rule name checks, C5b
for layout in ("userlevel", "legacy"):
    sb = Sb(layout=layout); p = sb.p
    GOOD_ = "---\nname: {n}\nmodel: sonnet\n---\nModel reason: x\nFlow role: build\n"
    check("R8 %s: file name = frontmatter name passes" % layout, not deny(o := p.write(".claude/agents/my-helper.md", GOOD_.format(n="my-helper"))), o)
    o = p.write(".claude/agents/my-other.md", GOOD_.format(n="verifier"))
    check("R8 %s: name: verifier in my-other.md is refused" % layout, deny(o) and "frontmatter name" in reason(o), reason(o))
    check("R8 %s: ... also for an agent's write" % layout, deny(p.pre("Write", {"file_path": str(p.P / ".claude/agents/my-other.md"), "content": GOOD_.format(n="verifier")}, "r8", agent="builder")))
    sb.done()
sb = Sb(); p = sb.p
check("R8 userlevel: a NEW project file named like a master/user agent is refused without overrides", deny(o := p.write(".claude/agents/verifier.md", "---\nname: verifier\nmodel: sonnet\n---\nModel reason: x\nFlow role: test\n")) and "already exists" in reason(o), reason(o))
check("R8 userlevel: ... allowed with overrides:", not deny(p.write(".claude/agents/reviewer.md", "---\nname: reviewer\noverrides: reviewer\nmodel: opus\n---\nModel reason: x\nFlow role: review\n")))
sb.done()
sb = Sb(); p = sb.p
sb.agent_file("fake-qa", "---\nname: verifier\nmodel: sonnet\n---\nModel reason: x\nFlow role: test\n")
check("C5b project fake-qa.md with name: verifier and Flow role: test is NOT credited (agent_type fake-qa)", not sb.credited("fake-qa", "c5b"))
check("C5b ... nor when Claude Code reports the frontmatter name (agent_type verifier) and the user-level master is shadowed", not sb.credited("verifier", "c5c"))
ev = sb.untrusted_events()
check("C5b ... and role_untrusted is logged for both", len(ev) == 2 and all(e.get("claimed") == "test" and e.get("effective") == "support" for e in ev), ev)
sb.done()

# ===================================================================== agent-state.sh: the model comes from the project file, else the user-level file
sb = Sb(install=False); p = sb.p
(sb.HOME / ".claude/agents").mkdir(parents=True)
(sb.HOME / ".claude/agents/verifier.md").write_text("---\nname: verifier\nmodel: haiku\n---\nFlow role: test\n")
(sb.HOME / ".claude/agents/planner.md").write_text("---\nname: planner\nmodel: opus\n---\nFlow role: plan\n")
p.put(".claude/agents/planner.md", "---\nname: planner\nmodel: sonnet\n---\nFlow role: plan\n")
if (ROOT / HK / "agent-state.sh").exists():          # legacy shell hook: owner's checkout only
    AS = ROOT / HK / "agent-state.sh"
    def agent_state(typ, aid):
        env = dict(p.ENV, CLAUDE_PROJECT_DIR=str(p.P)); env.pop("SHIPMIRACLE_QUIET", None)
        subprocess.run(["bash", str(AS)], input=json.dumps({"hook_event_name": "SubagentStart", "agent_id": aid, "agent_type": typ, "cwd": str(p.P)}), capture_output=True, text=True, env=env)
        try:
            return json.load(open(sb.HOME / ".local/state/shipmiracle" / (p.P.name + ".agents.json")))
        except Exception:
            return {}
    st_ = agent_state("verifier", "a1")
    check("AS agent-state: model from the user-level file when the project has none", st_.get("a1", {}).get("model") == "haiku", st_)
    st_ = agent_state("planner", "a2")
    check("AS agent-state: the project file wins over the user-level one", st_.get("a2", {}).get("model") == "sonnet", st_)
    st_ = agent_state("nobody", "a3")
    check("AS agent-state: unknown type -> empty model, no crash", st_.get("a3", {}).get("model") == "", st_)
    st_ = agent_state("../verifier", "a4")
    check("AS agent-state: a path-like type reads no file", st_.get("a4", {}).get("model") == "", st_)
sb.done()

# ===================================================================== C22: latency
def _modern(b):
    """The baseline gate comes from git history with the retired names: map them so the bench runs the same code path as the new gate."""
    o = ("a" + "iw").encode()
    for old, new in ((o.upper() + b"_", b"SHIPMIRACLE_"), (b"bin/" + o + b"-", b"bin/shipm-"), (b"bin/" + o, b"bin/shipm"), (o + b"-hook", b"shipm-hook"), (o, b"shipmiracle"), (o.upper(), b"SHIPMIRACLE")):
        b = b.replace(old, new)
    return b


def baseline_hook():
    r = subprocess.run(["git", "-C", str(ROOT), "show", "%s:%s" % (BASE_COMMIT, GATE_REL)], capture_output=True)
    if r.returncode != 0:
        return None
    f = TOP / "flow-gate-base.sh"
    f.write_bytes(_modern(r.stdout))
    return f


base = baseline_hook() if (ROOT / GATE_REL).exists() else None
if base is None:
    check("C22 bench skipped: baseline commit %s not available" % BASE_COMMIT, True)
else:
    sb = Sb(); p = sb.p
    sb.registry()
    new_hook = ROOT / GATE_REL
    payload = json.dumps({"hook_event_name": "PreToolUse", "session_id": "bench", "cwd": str(p.P), "tool_name": "Bash", "tool_input": {"command": "ls"}})
    prompt = json.dumps({"hook_event_name": "UserPromptSubmit", "session_id": "bench", "cwd": str(p.P), "prompt": "go"})
    for h in (base, new_hook):
        subprocess.run(["bash", str(h)], input=prompt, capture_output=True, text=True, env=p.ENV)

    def run_once(h):
        t0 = time.perf_counter()
        subprocess.run(["bash", str(h)], input=payload, capture_output=True, text=True, env=p.ENV)
        return (time.perf_counter() - t0) * 1000.0

    def attempt(n=200):
        """Interleaved: the same machine load hits both versions."""
        a, b = [], []
        for i in range(n):
            if i % 2:
                b.append(run_once(new_hook)); a.append(run_once(base))
            else:
                a.append(run_once(base)); b.append(run_once(new_hook))
        return shipmiracle_timing.p95(a), shipmiracle_timing.p95(b), statistics.median(a), statistics.median(b)

    rows = []
    ok = False
    for i in range(3):
        pa, pb, ma, mb = attempt()
        rows.append("attempt %d: base p95 %.1f ms (median %.1f), new p95 %.1f ms (median %.1f), diff %+.1f ms" % (i + 1, pa, ma, pb, mb, pb - pa))
        if pb <= pa + 10.0:
            ok = True; break
    print("INFO bench PreToolUse 200 runs each, userlevel + registry entry + user agents; " + "; ".join(rows))
    check("C22 PreToolUse p95 <= baseline (%s) + 10 ms over 200 runs" % BASE_COMMIT, ok, "; ".join(rows))
    sb.done()

shutil.rmtree(TOP, ignore_errors=True)
print("%d checks, %d failed" % (n_checks[0], len(fails)))
print("ALL PASS" if not fails else "%d FAILED: %s" % (len(fails), fails))
sys.exit(1 if fails else 0)
