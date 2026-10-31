#!/usr/bin/env python3
"""gate_team_test: checklist G9, the team gate (plan docs/plans/2026-10-23-G6-G9-team-borrow-promotion-gate.md, Gate rule + UPDATE).
The flow gate (BOTH copies: the legacy shell script when present, and the v1 dispatcher flow slot) refuses a build step from an agent that is not in the project's Team table
(docs/SKILLS.md), ignores the review verdict of a non-member, refuses subagent writes to the table and the borrow record, follows the project's flow level, lets verifier and
reviewer through, is lifted by "just do it", and treats a damaged or vanished table as masters-only. Every rule has a mutant that must be noticed (legacy source only; the sync suite keeps the copies equal).
Run: python3 tests/gate_team_test.py"""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import shipmiracle_isolation; shipmiracle_isolation.apply_to_environ()   # test isolation
import copy, json, os, pathlib, shutil, subprocess, sys, tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import flow_fixture as F
from flow_fixture import deny, note, text, AGENT_TEXT

# read-only roles may write under the temp folders: the sandboxes must live elsewhere (as in flow_gate_roles_test)
tempfile.tempdir = next((d for d in ('/var/tmp', str(pathlib.Path.home() / '.cache')) if os.path.isdir(d) and os.access(d, os.W_OK)), None)
fails = []
n_checks = [0]
projects = []


def check(name, ok, info=""):
    n_checks[0] += 1
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(info)[:500]))
    if not ok:
        fails.append(name)


IMPLS = ([("legacy", str(F.LEGACY_HOOK))] if F.LEGACY_HOOK.exists() else []) + [("v1", str(F.V1_HOOK))]
BLOCK = "## Team\n<!-- team:begin -->\n| Role | Agent | Skills | Why |\n|---|---|---|---|\n{rows}<!-- team:end -->\n"
ROW = "| {role} | {agent} | - | because |\n"
AGENTS = {"builder-a": AGENT_TEXT.format(n="builder-a", m="sonnet", r="build"), "db-helper": AGENT_TEXT.format(n="db-helper", m="sonnet", r="build"),
          "rev-x": AGENT_TEXT.format(n="rev-x", m="opus", r="review"), "scout": AGENT_TEXT.format(n="scout", m="sonnet", r="scope")}
SRC = {"file_path": "src/app.py", "old_string": "x = 1", "new_string": "x = 2"}


class W:
    """One sandbox project with a symlinked Shipmiracle package as the workspace code (the gate loads shipmiracle.team from there)."""
    def __init__(self, impl_path, level="strict", rows=(("build", "builder-a"), ("test", "verifier")), table=True, userlevel=False):
        self.hook = impl_path
        self.p = p = F.make_project("proj", agents=dict(AGENTS)); projects.append(p)
        os.symlink(str(ROOT / "shipmiracle"), str(p.WSF / "shipmiracle"))
        self.cfg = p.T / "cfg"; self.cfg.mkdir(); self.home = p.T / "home"; (self.home / ".claude").mkdir(parents=True)
        (p.T / 'hooktmp').mkdir()
        p.ENV.update(SHIPMIRACLE_CONFIG=str(self.cfg), SHIPMIRACLE_HOME=str(self.home), HOME=str(self.home), TMPDIR=str(p.T / 'hooktmp'))
        if userlevel:
            (self.cfg / "config.json").write_text(json.dumps({"agents.layout": "userlevel"}))
        p.level(level)
        self.n = 0
        if table:
            self.table(rows)
        self.say("go")

    def table(self, rows):
        self.p.put("docs/SKILLS.md", "# Skills\n\n" + BLOCK.format(rows="".join(ROW.format(role=r, agent=a) for r, a in rows)))

    def level(self, lv):
        self.p.level(lv)

    def call(self, ev, sid="s1", agent=None, aid="ag1", env=None, cwd=None, **kw):
        d = {"hook_event_name": ev, "session_id": sid, "cwd": str(cwd or self.p.P), **kw}
        if agent:
            d.update(agent_id=aid, agent_type=agent)
        e = dict(env or self.p.ENV)
        if cwd:
            e["CLAUDE_PROJECT_DIR"] = str(cwd)
        r = subprocess.run(["bash", self.hook], input=json.dumps(d), capture_output=True, text=True, env=e, cwd=str(cwd or self.p.P))
        try:
            return json.loads(r.stdout) if r.stdout.strip() else {}
        except Exception:
            return {"raw": r.stdout, "err": r.stderr}

    def say(self, t, sid="s1"):
        return self.call("UserPromptSubmit", sid, prompt=t)

    def pre(self, tool, ti, agent=None, sid="s1", aid="ag1", **kw):
        return self.call("PreToolUse", sid, agent=agent, aid=aid, tool_name=tool, tool_input=ti, **kw)

    def edit(self, agent, path="src/app.py", sid="s1", aid="ag1", **kw):
        return self.pre("Edit", dict(SRC, file_path=str(self.p.P / path)), agent, sid, aid, **kw)

    def bash(self, cmd, agent, sid="s1"):
        return self.pre("Bash", {"command": cmd}, agent, sid)

    def review_stop(self, agent, sid="s1", aid="rv1"):
        return self.call("SubagentStop", sid, agent=agent, aid=aid, last_assistant_message="Verdict: ACCEPT\nLens: general\n")

    def events(self, kind=None):
        ev = self.p.events()
        return [e for e in ev if e["event"] == kind] if kind else ev

    def state(self, sid="s1"):
        return self.p.state(sid)


def reason(o):
    return (o.get("hookSpecificOutput") or {}).get("permissionDecisionReason") or o.get("reason") or ""


def _break_reader(w):
    link = w.p.WSF / "shipmiracle"; link.unlink(); os.symlink(str(w.p.T / "nowhere"), str(link))


def run_suite(impl, hook):
    T = lambda n: "[%s] %s" % (impl, n)

    # ---------------------------------------------------------------- build rule
    w = W(hook)
    o = w.edit("builder-a")
    check(T("member builder-a may build"), not deny(o), o)
    o = w.edit("db-helper", aid="ag2")
    check(T("non-member db-helper is refused at its first write"), deny(o), o)
    r = reason(o)
    check(T("message names the agent, the table, the fix and who to use"), "`db-helper` is not on this project's team" in r and "docs/SKILLS.md" in r and
          "shipm team add db-helper --role build" in r and "builder-a" in r, r)
    check(T("refusal is an event team_member_required"), len(w.events("team_member_required")) == 1, w.events())
    o = w.pre("Write", {"file_path": str(w.p.P / "src/n.py"), "content": "x"}, "db-helper", aid="ag2")
    check(T("Write by a non-member is refused too"), deny(o), o)
    o = w.pre("Bash", {"command": "echo hi > src/b.py"}, "db-helper", aid="ag2")
    check(T("strict has no cap: the third and fourth call of a non-member are refused too"), deny(o) and deny(w.edit("db-helper", aid="ag2")), o)
    w.say("again", "s2")
    check(T("Bash write by a non-member is refused in a fresh turn/session"), deny(w.bash("echo hi > src/b.py", "db-helper", "s2")))
    check(T("MultiEdit and NotebookEdit by a non-member are refused"),
          deny(w.pre("MultiEdit", {"file_path": str(w.p.P / "src/app.py"), "edits": [{"old_string": "x", "new_string": "y"}]}, "db-helper", "s3", aid="ag3")) and
          deny(w.pre("NotebookEdit", {"notebook_path": str(w.p.P / "src/n.ipynb"), "new_source": "x"}, "db-helper", "s4", aid="ag4")))
    check(T("even a read-only Bash command by a non-member is refused (Bash is a gated tool)"), deny(w.bash("ls src", "db-helper", "s5")))
    check(T("the main chat is not judged by the team rule"), not deny(w.pre("Edit", dict(SRC, file_path=str(w.p.P / "docs/STATUS.md")))))
    w.p.cleanup()

    # alias both ways
    w = W(hook, rows=(("build", "backend-engineer"),))
    check(T("table lists the old name backend-engineer: builder-backend is a member"), not deny(w.edit("builder-backend")))
    check(T("... and the old name itself"), not deny(w.edit("backend-engineer", sid="s2", aid="ag2")))
    w.p.cleanup()
    w = W(hook, rows=(("build", "builder-backend"),))
    check(T("table lists builder-backend: the old name backend-engineer is a member"), not deny(w.edit("backend-engineer")))
    check(T("... and builder-frontend is not"), deny(w.edit("builder-frontend", sid="s2", aid="ag2")))
    w.p.cleanup()

    # always allowed / exempt
    w = W(hook, rows=(("build", "builder-a"),))
    check(T("verifier (test role) may write a test file though not in the table"), not deny(w.pre("Write", {"file_path": str(w.p.P / "tests/t_test.py"), "content": "x"}, "verifier")))
    check(T("qa-engineer alias too"), not deny(w.pre("Write", {"file_path": str(w.p.P / "tests/t2_test.py"), "content": "x"}, "qa-engineer", "s2", aid="ag2")))
    check(T("general-purpose is not judged by the team rule (keeps its own refusal where it has one)"), not deny(w.edit("general-purpose", sid="s3", aid="ag3")))
    check(T("Explore and Plan are not judged"), not deny(w.bash("ls", "Explore", "s4")) and not deny(w.bash("ls", "Plan", "s5")))
    check(T("legacy layout: a scope-role non-member is judged like a builder (no read-only rule there)"), deny(w.bash("ls src", "scout")))
    w.p.cleanup()

    # no table
    w = W(hook, table=False)
    o = w.edit("db-helper")
    check(T("no table: no rule (today's behaviour)"), not deny(o), o)
    check(T("no table: one note per session at the first build write"), "No Team table yet" in note(o) and "shipm team add" in note(o), o)
    o = w.edit("db-helper", aid="ag9")
    check(T("no table: the note is not repeated in the same session"), "No Team table yet" not in note(o), o)
    check(T("no table: event team_table_missing logged once"), len(w.events("team_table_missing")) == 1, w.events())
    w.p.put("docs/SKILLS.md", "# Skills\n\nno team here\n")
    check(T("SKILLS.md without a block: no rule"), not deny(w.edit("db-helper", sid="s7", aid="ag7")))
    w.p.put("docs/SKILLS.md", "# Skills\n\n" + BLOCK.format(rows=""))
    check(T("a block with 0 valid rows = no table = no rule"), not deny(w.edit("db-helper", sid="s8", aid="ag8")))
    w.p.cleanup()

    # levels
    w = W(hook, level="warn")
    o = w.edit("db-helper")
    check(T("warn: let through with a note, event team_member_required_warned"), not deny(o) and "not on this project's team" in note(o) and len(w.events("team_member_required_warned")) == 1, o)
    w.p.cleanup()
    w = W(hook, level="off")
    check(T("off: nothing"), not deny(w.edit("db-helper")) and not w.events("team_member_required"))
    w.p.cleanup()

    # just do it
    w = W(hook)
    w.say("just do it, please")
    o = w.edit("db-helper")
    check(T("'just do it' lifts the team rule for the turn and logs team_bypass"), not deny(o) and len(w.events("team_bypass")) == 1, (o, w.events()))
    w.say("now carefully")
    check(T("the next ordinary turn judges again"), deny(w.edit("db-helper", aid="ag5")))
    w.p.cleanup()

    # cache per agent id (TOCTOU) and table edits
    w = W(hook)
    check(T("cache: member allowed"), not deny(w.edit("builder-a", aid="m1")))
    w.table((("build", "db-helper"),))
    check(T("cache: the same agent id is judged again by the changed table (builder-a is out)"), deny(w.edit("builder-a", aid="m1")))
    check(T("cache: a new agent id is judged by the new table (builder-a now out)"), deny(w.edit("builder-a", aid="m2")))
    check(T("cache: db-helper now in"), not deny(w.edit("db-helper", aid="m3", sid="s2")))
    w.p.cleanup()

    # damaged / vanished table
    w = W(hook)
    w.p.put("docs/SKILLS.md", "# S\n" + BLOCK.format(rows=ROW.format(role="build", agent="builder-a")) * 2)
    o = w.edit("builder-a")
    check(T("damaged markers (twice): a project agent cannot build, message says repair"), deny(o) and "Team table" in reason(o) and "damaged" in reason(o), o)
    check(T("damaged: a master (builder-backend) still works"), not deny(w.edit("builder-backend", sid="s2", aid="ag2")))
    check(T("damaged: event team_table_damaged logged once"), len(w.events("team_table_damaged")) == 1, w.events())
    w.p.cleanup()
    w = W(hook)
    check(T("vanish: table fine first"), not deny(w.edit("builder-a")))
    (w.p.P / "docs/SKILLS.md").unlink()
    o = w.edit("builder-a", aid="ag2")
    check(T("vanish: seen earlier this session, now missing: a project agent is refused (masters only)"), deny(o) and "missing" in reason(o), o)
    check(T("vanish: a master still works"), not deny(w.edit("builder-backend", aid="ag3")))
    check(T("vanish: another session never saw a table: no rule"), not deny(w.edit("builder-a", sid="fresh", aid="ag4")))
    w.say("next turn"); w.p.put("docs/SKILLS.md", "# S\nno block now\n")
    check(T("vanish: block removed (empty table) after being seen: masters only"), deny(w.edit("db-helper", aid="ag5")))
    w.say("next turn"); (w.p.P / "docs/SKILLS.md").unlink()
    os.symlink(str(w.p.P / "README-x"), str(w.p.P / "docs/SKILLS.md"))
    check(T("vanish: symlinked SKILLS.md after being seen: masters only"), deny(w.edit("db-helper", aid="ag6")))
    w.p.cleanup()
    w = W(hook, table=False)
    (w.p.P / "docs").mkdir(exist_ok=True)
    os.symlink(str(w.p.P / "src/app.py"), str(w.p.P / "docs/SKILLS.md"))
    check(T("a symlinked SKILLS.md (HEAD has no table): unreadable = masters only"), deny(w.edit("db-helper")) and not deny(w.edit("builder-backend", sid="s2", aid="b2")) and len(w.events("team_table_unreadable")) == 1)
    w.p.cleanup()
    w = W(hook, table=False)
    w.p.put("docs/SKILLS.md", "x" * 70000)
    check(T("an oversized SKILLS.md (HEAD has no table): unreadable = masters only"), deny(w.edit("db-helper")))
    w.p.cleanup()


    # ---------------------------------------------------------------- security round 1
    # (1) folder destinations and protected folders
    w = W(hook)
    n = 0
    for c in ("cp /tmp/SKILLS.md docs/", "mv /tmp/SKILLS.md docs/", "cp /tmp/SKILLS.md docs", "cp -t docs /tmp/SKILLS.md", "mv -t .agents /tmp/borrowed.json", "install -t docs /tmp/SKILLS.md",
              "rsync /tmp/SKILLS.md docs/", "cp /tmp/skills.md docs/", "cp /tmp/*.md docs/", "ln -s /tmp/x docs/SKILLS.md", "mv .agents /tmp/a", "rm -r .agents"):
        n += 1
        o = w.bash(c, "builder-a", "f%d" % n)
        check(T("folder: member refused: %s" % c), deny(o) and "may not change the project team" in reason(o), o)
    # (2) option-value and quoting spellings of the shipm commands
    for c in ("shipm team --role build add evil", "shipm team --role build --why x add evil", "shipm borrow --reason r record ID --as y", "shipm team $'add' evil", "shipm te\\\nam add evil",
              "bash -c 'shipm team add evil --role build --why x'", "SHIPM team add evil"):
        n += 1
        o = w.bash(c, "builder-a", "f%d" % n)
        check(T("command: member refused: %r" % c), deny(o) and "shipm team add" in reason(o), o)
        check(T("command: the lead is not refused by the team rule: %r" % c), "project team" not in reason(w.pre("Bash", {"command": c})), c)
    # (6) false-refusal corpus
    for c in ("rg -n 'shipm team add' docs", "git commit -m 'docs: explain shipm team add'", "grep -r \"team add\" docs", "echo shipm team add", "cat docs/SKILLS.md", "ls docs .agents",
              "cp README.md docs/guide.md", "cp a.md docs/", "mv docs/a.md docs/b.md", "rm docs/old.md", "shipm team show", "shipm team check"):
        n += 1
        o = w.bash(c, "builder-a", "f%d" % n)
        check(T("corpus: member allowed: %s" % c), not deny(o), o)
    w.p.cleanup()

    # (3) tamper ignores the cap; a new session still refuses
    w = W(hook)
    check(T("cap: non-member Edit refused twice"), deny(w.edit("db-helper", aid="k1")) and deny(w.edit("db-helper", aid="k1")))
    check(T("cap: then Bash cp into docs/ is refused (tamper has no cap)"), deny(w.bash("cp /tmp/SKILLS.md docs/", "db-helper")))
    check(T("cap: next session Edit is refused"), deny(w.edit("db-helper", sid="k-next", aid="k1")))
    # (7) one non-member's refusals do not use another's
    check(T("cap: another non-member (own agent id) is refused from its first call"), deny(w.edit("builder-zz", aid="k2")))
    w.p.cleanup()

    # (4) unreadable or vanished table in a fresh session while HEAD has a valid block
    for label, mk in (("symlink", lambda f: (f.unlink(), os.symlink(str(f.parent.parent / "src/app.py"), str(f)))), ("oversize", lambda f: f.write_text("x" * 70000)),
                      ("NUL byte", lambda f: f.write_bytes(b"a\0b")), ("mode 000", lambda f: os.chmod(f, 0)), ("deleted", lambda f: f.unlink()),
                      ("block removed", lambda f: f.write_text("# S\n")), ("damaged", lambda f: f.write_text(f.read_text() * 2))):
        w = W(hook)
        GITC = lambda *a: subprocess.run(["git", "-C", str(w.p.P), "-c", "user.email=t@t", "-c", "user.name=t"] + list(a), check=True, capture_output=True)
        GITC("add", "-A"); GITC("commit", "-qm", "team")
        mk(w.p.P / "docs/SKILLS.md")
        check(T("fresh session, HEAD has a table, SKILLS.md %s: a non-member is refused" % label), deny(w.edit("db-helper", sid="fresh-" + label.replace(" ", ""), aid="h1")))
        check(T("... and a master still works (%s)" % label), not deny(w.edit("builder-backend", sid="fresh2-" + label.replace(" ", ""), aid="h2")))
        try:
            os.chmod(w.p.P / "docs/SKILLS.md", 0o644)
        except OSError:
            pass
        w.p.cleanup()
    w = W(hook, table=False)
    check(T("fresh session, HEAD has no table, nothing on disk: no rule"), not deny(w.edit("db-helper", sid="n1", aid="n1")))
    w.p.cleanup()

    # (5) no stale allow-cache, reader unavailable then restored
    w = W(hook, table=False)
    check(T("no table: non-member c1 allowed"), not deny(w.edit("db-helper", aid="c1")))
    w.table((("build", "builder-a"),))
    check(T("lead adds a table: the same agent id is refused (no stale cache)"), deny(w.edit("db-helper", aid="c1")))
    w.p.cleanup()
    w = W(hook)
    link = w.p.WSF / "shipmiracle"
    link.unlink(); os.symlink(str(w.p.T / "nowhere"), str(link))
    check(T("reader unavailable: rule off, event team_reader_unavailable once"), not deny(w.edit("db-helper", aid="r1")) and not deny(w.edit("db-helper", aid="r2")) and len(w.events("team_reader_unavailable")) == 1, w.events())
    link.unlink(); os.symlink(str(ROOT / "shipmiracle"), str(link))
    check(T("reader restored: the same agent is refused"), deny(w.edit("db-helper", aid="r1")))
    w.p.cleanup()


    # ---------------------------------------------------------------- security/QA round 2
    w = W(hook)
    n = 100
    patch = w.p.T / "x.patch"; patch.write_text("diff --git a/docs/SKILLS.md b/docs/SKILLS.md\n--- a/docs/SKILLS.md\n+++ b/docs/SKILLS.md\n")
    for c in ("chmod 000 docs", "chmod -R 000 docs", "chmod 000 .agents", "ln -sfn /tmp/d docs", "chown root docs", "chattr +i docs", "unlink docs/SKILLS.md", "mv docs /tmp/dd",
              "git checkout stash@{0} -- docs/SKILLS.md", "git checkout .", "git restore .", "git stash", "git reset --hard", "git clean -fdx", "git apply %s" % patch,
              "git rm docs/SKILLS.md", "git mv docs/SKILLS.md docs/S.md", "git -C . checkout -- docs", "find docs -name SKILLS.md -delete", "echo x > docs/SKILL?.md",
              "f=docs/SKILLS.md; echo x > $f", "echo rm docs/SKILLS.md | sh", "eval 'rm docs/SKILLS.md'", "python3 -c \"import os; os.remove('docs/SKILLS.md')\"",
              "shipm team --why y add db-helper --role build", "shipm borrow --reason r record x --as n", "shipm team --role build add x"):
        n += 1
        check(T("round2: member refused: %s" % c.replace(str(patch), "p.patch")), deny(w.bash(c, "builder-a", "g%d" % n)))
    for c in ("git status", "git diff docs/SKILLS.md", "git log -p docs/SKILLS.md", "git add docs/SKILLS.md", "git commit -m 'update docs/SKILLS.md'", "grep -n team docs/SKILLS.md", "wc -l docs/SKILLS.md",
              "git checkout -b feature", "git stash list", "chmod +x docs/run.sh", "ln -s a.md docs/b.md", "cat docs/SKILLS.md > /tmp/out.txt", "python3 -c \"print(1)\""):
        n += 1
        o = w.bash(c, "builder-a", "g%d" % n)
        check(T("round2 corpus: member allowed: %s" % c), not deny(o) or "project team" not in reason(o), o)
    w.p.cleanup()
    # unknown role: an agent with no file and a name that gives no role is judged like a builder; a known scope role is not
    w = W(hook, rows=(("build", "builder-a"),))
    o = w.edit("mystery-agent")
    check(T("unknown role (no agent file): refused like a builder"), deny(o) and "not on this project's team" in reason(o), o)
    check(T("legacy layout: known scope role non-member is refused too"), deny(w.bash("ls src", "scout", "u2")))
    w.p.cleanup()
    # the parsed table is cached in the session: a new agent id does not need the reader; a broken reader gives a note and an event
    w = W(hook)
    check(T("cache: member allowed"), not deny(w.edit("builder-a", aid="a1")))
    _break_reader(w)
    o = w.edit("builder-a", aid="a2")
    check(T("parsed-table cache: a new member id is allowed without the reader, no reader event"), not deny(o) and not w.events("team_reader_unavailable"), (o, w.events()))
    w.table((("build", "builder-a"), ("test", "verifier")))
    o = w.edit("builder-a", aid="a3")
    check(T("changed table + broken reader: rule off, one visible note and one event"), not deny(o) and "OFF for this session" in note(o) and len(w.events("team_reader_unavailable")) == 1, (o, w.events()))
    w.p.cleanup()

    # ---------------------------------------------------------------- round 3: every non-member role, both layouts
    ROLES = {"scout": "scope", "rev-x": "review", "tester-x": "test", "planner-x": "plan", "mystery-agent": "unknown", "solution-architect": "plan (master)"}
    for layout in ("legacy", "userlevel"):
        w = W(hook, userlevel=(layout == "userlevel"), rows=(("build", "builder-a"),))
        w.p.put(".claude/agents/tester-x.md", AGENT_TEXT.format(n="tester-x", m="sonnet", r="test"))
        w.p.put(".claude/agents/planner-x.md", AGENT_TEXT.format(n="planner-x", m="opus", r="plan"))
        k = 0
        for who, role in ROLES.items():
            k += 1
            check(T("%s: non-member %s (%s) Edit in src is refused" % (layout, who, role)), deny(w.edit(who, sid="r%d" % k, aid="r%d" % k)))
            check(T("%s: non-member %s (%s) Bash write in src is refused" % (layout, who, role)), deny(w.bash("echo x > src/b.py", who, "rb%d" % k)))
        check(T("%s: master verifier may still write a test file" % layout), not deny(w.pre("Write", {"file_path": str(w.p.P / "tests/t_test.py"), "content": "x"}, "verifier", "v1", aid="v1")))
        if layout == "legacy":
          check(T("%s: a non-member planner may write a plan record" % layout), not deny(w.pre("Write", {"file_path": str(w.p.P / "docs/plans/x.md"), "content": "x"}, "solution-architect", "v2", aid="v2")))
        check(T("%s: a member builder still builds" % layout), not deny(w.edit("builder-a", sid="v3", aid="v3")))
        w.p.cleanup()
    # non-blocking list: folder-level overwrites, git whole-tree and plumbing forms, runtime-built shipm arguments
    w = W(hook)
    n = 300
    for c in ("cp -r /tmp/docs .", "cp -R /tmp/x/. docs", "rsync -a /tmp/x/ ./", "tar xf /tmp/t.tar", "tar -xf /tmp/t.tar -C docs", "tar -xzf /tmp/t.tgz --directory=.agents", "unzip -o /tmp/x.zip", "unzip -o /tmp/x.zip -d docs",
              "git checkout main", "git switch main", "git merge main", "git pull", "git rebase main", "git cherry-pick abc", "git update-index --cacheinfo 100644,abc,docs/SKILLS.md", "git checkout-index -f -a",
              "git read-tree -u --reset HEAD", "s=team; shipm $s add evil", "shipm $(echo team) add evil"):
        n += 1
        check(T("round3: member refused: %s" % c), deny(w.bash(c, "builder-a", "h%d" % n)))
    for c in ("cp -r src/lib /tmp/lib", "cp a.txt src/", "tar -xf /tmp/t.tar -C src", "unzip -o /tmp/x.zip -d src", "git checkout -b feature/x", "git checkout -- src/app.py", "git switch -c feature/y", "git diff", "git log --oneline", "git branch", "shipm team show", "shipm status"):
        n += 1
        o = w.bash(c, "builder-a", "h%d" % n)
        check(T("round3 corpus: member allowed: %s" % c), not deny(o) or "project team" not in reason(o), o)
    w.p.cleanup()

    # review verdicts
    w = W(hook, rows=(("build", "builder-a"), ("review", "rev-x")))
    w.review_stop("rev-x")
    check(T("review: a member's verdict is counted"), w.state().get("review_verdict") == "ACCEPT" and not w.events("team_review_ignored"), w.state())
    w.p.cleanup()
    w = W(hook, rows=(("build", "builder-a"),))
    o = w.review_stop("rev-x")
    check(T("review: a non-member's verdict is not counted"), not w.state().get("review_verdict") and not w.state().get("review_ts"), w.state())
    check(T("review: event team_review_ignored and a note naming the agent"), len(w.events("team_review_ignored")) == 1 and "rev-x" in note(o) and "not counted" in note(o), (o, w.events()))
    w.review_stop("reviewer", aid="rv2")
    check(T("review: master reviewer is always counted"), w.state().get("review_verdict") == "ACCEPT", w.state())
    w.p.cleanup()
    w = W(hook, rows=(("build", "builder-a"),))
    w.review_stop("security-reviewer")
    check(T("review: the old name security-reviewer is the reviewer (always allowed)"), w.state().get("review_verdict") == "ACCEPT", w.state())
    w.p.cleanup()
    w = W(hook, rows=(("build", "builder-a"),), level="warn")
    o = w.review_stop("rev-x")
    check(T("review at warn: counted, with a note"), w.state().get("review_verdict") == "ACCEPT" and "rev-x" in note(o), (o, w.state()))
    w.p.cleanup()
    w = W(hook, rows=(("build", "builder-a"),))
    w.say("just do it")
    w.review_stop("rev-x")
    check(T("review under 'just do it': counted, team_bypass logged"), w.state().get("review_verdict") == "ACCEPT" and len(w.events("team_bypass")) == 1, w.state())
    w.p.cleanup()
    w = W(hook, table=False)
    w.review_stop("rev-x")
    check(T("review with no table: counted (no rule)"), w.state().get("review_verdict") == "ACCEPT", w.state())
    w.p.cleanup()

    # tamper: subagents never write the table or the borrow record
    w = W(hook)
    for n, (tool, ti) in enumerate((("Edit", dict(SRC, file_path=str(w.p.P / "docs/SKILLS.md"))), ("Write", {"file_path": str(w.p.P / ".agents/borrowed.json"), "content": "{}"}),
                                    ("Edit", dict(SRC, file_path=str(w.p.P / "docs/skills.md"))), ("MultiEdit", {"file_path": "docs/SKILLS.md", "edits": []}),
                                    ("Write", {"file_path": str(w.p.P / "docs/../docs/SKILLS.md"), "content": "x"}))):
        o = w.pre(tool, ti, "builder-a", sid="t%d" % n, aid="t%d" % n)
        check(T("tamper: member builder-a may not %s %s" % (tool, os.path.basename(ti.get("file_path", "")))), deny(o) and "may not change the project team" in reason(o), o)
    check(T("tamper: event team_table_write"), len(w.events("team_table_write")) >= 5, w.events())
    for n, c in enumerate(("echo x >> docs/SKILLS.md", "sed -i s/a/b/ docs/SKILLS.md", "echo {} > .agents/borrowed.json", "tee docs/SKILLS.md", "cp /tmp/x docs/SKILLS.md", "rm docs/SKILLS.md",
                           "shipm team add db-helper --role build --why x", "./shipm team add db-helper --role build --why x", "python3 -m shipmiracle team add db-helper --role build --why x",
                           "shipm 'team' \"add\" db-helper", "shipm borrow record ecc:agent:x --reason y --as z")):
        check(T("tamper: Bash by a member refused: %s" % c[:40]), deny(w.bash(c, "builder-a", "b%d" % n)))
    check(T("tamper: reading and unrelated shipm commands pass"), not deny(w.bash("cat docs/SKILLS.md; shipm team show; shipm team check; shipm borrow show ecc:agent:x", "builder-a", "bz")))
    os.symlink(str(w.p.P / "docs/SKILLS.md"), str(w.p.P / "src/link.md"))
    check(T("tamper: a symlink to the table is judged by its target"), deny(w.pre("Write", {"file_path": str(w.p.P / "src/link.md"), "content": "x"}, "builder-a", "sl", aid="sl")))
    check(T("tamper: the main chat (the lead) may edit the table"), not deny(w.pre("Edit", dict(SRC, file_path=str(w.p.P / "docs/SKILLS.md")))))
    check(T("tamper: the lead may run shipm team add"), not deny(w.pre("Bash", {"command": "shipm team add db-helper --role build --why x"})))
    w.say("just do it", "tj")
    check(T("tamper: 'just do it' does not lift it"), deny(w.edit("builder-a", path="docs/SKILLS.md", sid="tj", aid="tj")))
    w.p.cleanup()
    w = W(hook, level="warn")
    o = w.edit("builder-a", path="docs/SKILLS.md")
    check(T("tamper at warn: let through with a note and an event"), not deny(o) and "may not change the project team" in note(o) and len(w.events("team_table_write_warned")) == 1, o)
    w.p.cleanup()
    w = W(hook, level="off")
    check(T("tamper at off: nothing"), not deny(w.edit("builder-a", path="docs/SKILLS.md")))
    w.p.cleanup()
    w = W(hook, table=False)
    check(T("tamper with no table: still refused (nobody but the lead writes it)"), deny(w.edit("builder-a", path="docs/SKILLS.md")))
    w.p.cleanup()

    # user-level layout
    w = W(hook, userlevel=True, rows=(("build", "builder-backend"),))
    check(T("userlevel layout: member builder-backend builds, builder-ops is refused"), not deny(w.edit("builder-backend")) and deny(w.edit("builder-ops", sid="s2", aid="ag2")))
    w.p.cleanup()

    # worktree: the table of the CURRENT checkout is read
    w = W(hook, rows=(("build", "builder-a"),))
    GIT = lambda *a: subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t"] + list(a), check=True, capture_output=True)
    wt = w.p.DEV / ".worktrees/proj/wt1"; wt.parent.mkdir(parents=True)
    GIT("-C", str(w.p.P), "worktree", "add", "-q", "-b", "feat/t", str(wt))
    wt = pathlib.Path(os.path.realpath(wt))
    (wt / "docs").mkdir(exist_ok=True); (wt / "docs/SKILLS.md").write_text("# S\n" + BLOCK.format(rows=ROW.format(role="build", agent="db-helper")))
    w.call("UserPromptSubmit", "wt", cwd=wt, prompt="go")
    check(T("worktree: db-helper is a member of the worktree's own table"), not deny(w.call("PreToolUse", "wt", agent="db-helper", cwd=wt, tool_name="Edit", tool_input=dict(SRC, file_path=str(wt / "src/app.py")))))
    check(T("worktree: builder-a is not (the main checkout's table is not used)"), deny(w.call("PreToolUse", "wt2", agent="builder-a", aid="x2", cwd=wt, tool_name="Edit", tool_input=dict(SRC, file_path=str(wt / "src/app.py")))))
    check(T("worktree: the main checkout still judges by its own table"), not deny(w.edit("builder-a", sid="m")) and deny(w.edit("db-helper", sid="m2", aid="x3")))
    w.p.cleanup()

    # the isolation block and the other agent rules are unchanged: a non-member's write to another project is still an isolation refusal
    w = W(hook)
    o = w.pre("Write", {"file_path": str(w.p.DEV / "other/x.txt"), "content": "x"}, "builder-a")
    (w.p.DEV / "other/.git").mkdir(parents=True) if not (w.p.DEV / "other/.git").exists() else None
    o = w.pre("Write", {"file_path": str(w.p.DEV / "other/x.txt"), "content": "x"}, "builder-a", sid="iso", aid="iso")
    check(T("isolation block untouched: a member writing into another project is still refused by it"), deny(o) and "Project isolation" in reason(o), o)
    w.p.cleanup()


for impl, hook in IMPLS:
    run_suite(impl, hook)

# ---------------------------------------------------------------- mutants (legacy source): each rule has a case that notices it
src = F.LEGACY_HOOK.read_text() if F.LEGACY_HOOK.exists() else None


def sc_nonmember_refused(h):
    w = W(h); r = deny(w.edit("db-helper")); w.p.cleanup(); return r


def sc_member_allowed_alias(h):
    w = W(h, rows=(("build", "builder-backend"),)); r = not deny(w.edit("backend-engineer")); w.p.cleanup(); return r


def sc_cache(h):
    w = W(h); w.edit("builder-a", aid="m1"); w.table((("build", "db-helper"),)); r = deny(w.edit("builder-a", aid="m1")); w.p.cleanup(); return r


def sc_tabcache(h):
    w = W(h); w.edit("builder-a", aid="a1"); _break_reader(w); w.edit("builder-a", aid="a2"); r = not w.events("team_reader_unavailable"); w.p.cleanup(); return r


def sc_unknown_role(h):
    w = W(h, rows=(("build", "builder-a"),)); r = deny(w.edit("mystery-agent")); w.p.cleanup(); return r


def sc_reader_note(h):
    w = W(h); _break_reader(w); r = "OFF for this session" in note(w.edit("db-helper", aid="r1")); w.p.cleanup(); return r


def sc_git(h):
    w = W(h); r = deny(w.bash("git restore .", "builder-a")); w.p.cleanup(); return r


def sc_textform(h):
    w = W(h); r = deny(w.bash("f=docs/SKILLS.md; echo x > $f", "builder-a")); w.p.cleanup(); return r


def sc_glob(h):
    w = W(h); r = deny(w.bash("echo x > docs/SKILL?.md", "builder-a")); w.p.cleanup(); return r


def sc_chmod(h):
    w = W(h); r = deny(w.bash("chattr +i docs", "builder-a")); w.p.cleanup(); return r


def sc_damaged(h):
    w = W(h); w.p.put("docs/SKILLS.md", "# S\n" + BLOCK.format(rows=ROW.format(role="build", agent="builder-a")) * 2); r = deny(w.edit("db-helper")); w.p.cleanup(); return r


def sc_vanish(h):
    w = W(h); w.edit("builder-a"); (w.p.P / "docs/SKILLS.md").unlink(); r = deny(w.edit("db-helper", aid="a2")); w.p.cleanup(); return r


def sc_master_in_damage(h):
    w = W(h); w.p.put("docs/SKILLS.md", "# S\n" + BLOCK.format(rows="") * 2); r = not deny(w.edit("builder-backend")); w.p.cleanup(); return r


def sc_review_ignored(h):
    w = W(h, rows=(("build", "builder-a"),)); w.review_stop("rev-x"); r = not w.state().get("review_verdict"); w.p.cleanup(); return r


def sc_reviewer_always(h):
    w = W(h, rows=(("build", "builder-a"),)); w.review_stop("reviewer"); r = w.state().get("review_verdict") == "ACCEPT"; w.p.cleanup(); return r


def sc_review_warn(h):
    w = W(h, rows=(("build", "builder-a"),), level="warn"); w.review_stop("rev-x"); r = w.state().get("review_verdict") == "ACCEPT"; w.p.cleanup(); return r


def sc_review_bypass(h):
    w = W(h, rows=(("build", "builder-a"),)); w.say("just do it"); w.review_stop("rev-x"); r = w.state().get("review_verdict") == "ACCEPT"; w.p.cleanup(); return r


def sc_bypass(h):
    w = W(h); w.say("just do it"); r = not deny(w.edit("db-helper")); w.p.cleanup(); return r


def sc_warn(h):
    w = W(h, level="warn"); r = not deny(w.edit("db-helper")); w.p.cleanup(); return r


def sc_general_purpose(h):
    w = W(h, rows=(("build", "builder-a"),)); r = not deny(w.edit("general-purpose")); w.p.cleanup(); return r


def sc_note_once(h):
    w = W(h, table=False); w.edit("db-helper"); r = "No Team table yet" not in note(w.edit("db-helper", aid="a2")); w.p.cleanup(); return r


def sc_note_first(h):
    w = W(h, table=False); r = "No Team table yet" in note(w.edit("db-helper")); w.p.cleanup(); return r


def sc_tamper_file(h):
    w = W(h); r = deny(w.edit("builder-a", path="docs/SKILLS.md")); w.p.cleanup(); return r


def sc_tamper_record(h):
    w = W(h); r = deny(w.pre("Write", {"file_path": str(w.p.P / ".agents/borrowed.json"), "content": "{}"}, "builder-a")); w.p.cleanup(); return r


def sc_tamper_bash(h):
    w = W(h); r = deny(w.bash("echo x >> docs/SKILLS.md", "builder-a")); w.p.cleanup(); return r


def sc_tamper_cmd(h):
    w = W(h); r = deny(w.bash("shipm team add db-helper --role build --why x", "builder-a")); w.p.cleanup(); return r


def sc_tamper_case(h):
    w = W(h); r = deny(w.edit("builder-a", path="docs/skills.md")); w.p.cleanup(); return r


def sc_tamper_bypass(h):
    w = W(h); w.say("just do it"); r = deny(w.edit("builder-a", path="docs/SKILLS.md")); w.p.cleanup(); return r


def sc_tamper_warn(h):
    w = W(h, level="warn"); r = not deny(w.edit("builder-a", path="docs/SKILLS.md")); w.p.cleanup(); return r


def sc_cap(h):
    w = W(h)
    for i in range(4):
        o = w.edit("db-helper", aid="c1")
    r = deny(o); w.p.cleanup(); return r


def sc_unreadable(h):
    w = W(h, table=False); w.p.put("docs/SKILLS.md", "x" * 70000); r = deny(w.edit("db-helper")); w.p.cleanup(); return r


def sc_head(h):
    w = W(h)
    subprocess.run(["git", "-C", str(w.p.P), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(w.p.P), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "t"], check=True, capture_output=True)
    (w.p.P / "docs/SKILLS.md").unlink(); r = deny(w.edit("db-helper", sid="fresh", aid="h1")); w.p.cleanup(); return r


def sc_stale(h):
    w = W(h, table=False); w.edit("db-helper", aid="c1"); w.table((("build", "builder-a"),)); r = deny(w.edit("db-helper", aid="c1")); w.p.cleanup(); return r


def sc_reader_event(h):
    w = W(h); link = w.p.WSF / "shipmiracle"; link.unlink(); os.symlink(str(w.p.T / "nowhere"), str(link))
    w.edit("db-helper", aid="r1"); r = len(w.events("team_reader_unavailable")) == 1; w.p.cleanup(); return r


def sc_folder(h):
    w = W(h); r = deny(w.bash("cp /tmp/*.md docs/", "builder-a")); w.p.cleanup(); return r


def sc_folder_rm(h):
    w = W(h); r = deny(w.bash("mv .agents /tmp/a", "builder-a")); w.p.cleanup(); return r


def _bash_denied(h, cmd, who="builder-a", **kw):
    w = W(h, **kw); r = deny(w.bash(cmd, who)); w.p.cleanup(); return r


def sc_cmdvar(h): return _bash_denied(h, "s=team; shipm $s add evil")


def sc_bulk(h): return _bash_denied(h, "cp -r /tmp/docs .")


def sc_checkout(h): return _bash_denied(h, "git checkout main")


def sc_merge(h): return _bash_denied(h, "git merge main")


def sc_plumb(h): return _bash_denied(h, "git checkout-index -f -a")


def sc_ul_skip(h):
    w = W(h, userlevel=True, rows=(("build", "builder-a"),)); o = w.bash("ls src", "scout"); r = "not on this project's team" not in reason(o); w.p.cleanup(); return r


def sc_record(h):
    w = W(h, rows=(("build", "builder-a"),)); r = not deny(w.pre("Write", {"file_path": str(w.p.P / "docs/plans/x.md"), "content": "x"}, "solution-architect")); w.p.cleanup(); return r


def sc_opt(h):
    w = W(h); r = deny(w.bash("shipm team --role build add evil", "builder-a")); w.p.cleanup(); return r


def sc_verifier_free(h):
    w = W(h, rows=(("build", "builder-a"),)); r = not deny(w.pre("Write", {"file_path": str(w.p.P / "tests/t_test.py"), "content": "x"}, "verifier")); w.p.cleanup(); return r


def sc_build_role_only(h):
    w = W(h, rows=(("build", "builder-a"),)); r = deny(w.bash("echo x > src/b.py", "scout")); w.p.cleanup(); return r


def sc_none_no_rule(h):
    w = W(h, table=False); r = not deny(w.edit("db-helper")); w.p.cleanup(); return r


MUT = [
    ("member test", 'if norm in {r_["agent"] for r_ in rows_}:', 'if True:', sc_nonmember_refused, True),
    ("alias normalisation", 'norm = ALIASES.get(atype, atype)\n        if not atype or atype in TEAM_FREE', 'norm = atype\n        if not atype or atype in TEAM_FREE', sc_member_allowed_alias, True),
    ("decision cache is tied to the file stamp", 'cache.get(key) == sig_', 'cache.get(key) is not None', sc_cache, True),
    ("parsed table cache", 'c_.get("sig") == sig_ and sig_ != [-1]', 'False and sig_ != [-1]', sc_tabcache, True),
    ("reader note visible", 'NOTES.append("TEAM FLOW: the Team table could not be read', 'NOTES.append("" and "TEAM FLOW: the Team table could not be read', sc_reader_note, True),
    ("git forms", 'elif any(team_git(w_) for _a, _u, w_ in segs_):', 'elif False:', sc_git, True),
    ("text forms", 'elif team_text(c, segs_):', 'elif False:', sc_textform, True),
    ("glob targets", 'if re.search(r"[*?\\[]", r_) and any(glob_re(r_)', 'if False and any(glob_re(r_)', sc_glob, True),
    ("dir permission verbs", 'if not w or _cmd_name(w[0]) not in TEAM_DIRCMDS:', 'if True:', sc_chmod, True),
    ("damaged table", 'state_ in ("damaged", "unreadable") or st.get("team_ok")', 'state_ in ("unreadable",) or st.get("team_ok")', sc_damaged, True),
    ("unreadable table", 'state_ in ("damaged", "unreadable") or st.get("team_ok")', 'state_ in ("damaged",) or st.get("team_ok")', sc_unreadable, True),
    ("seen-then-vanished table", 'or st.get("team_ok") or team_head()', 'or False or team_head()', sc_vanish, True),
    ("table existed in HEAD", 'or st.get("team_ok") or team_head()', 'or st.get("team_ok") or False', sc_head, True),
    ("reader unavailable is an event", 'log("team_reader_unavailable")', 'pass', sc_reader_event, True),
    ("masters stay allowed when damaged", 'if norm not in ALIASES and norm not in DEFAULT_ROLE:', 'if True:', sc_master_in_damage, True),
    ("team_ok remembered", 'if not st.get("team_ok"):\n                st["team_ok"] = True', 'if False:\n                st["team_ok"] = True', sc_vanish, True),
    ("review of a non-member ignored", 'log("team_review_ignored", agent=atype)', 'return False', sc_review_ignored, True),
    ("review verdict of reviewer always counted", 'norm in ("verifier", "reviewer")', 'norm in ("verifierx",)', sc_reviewer_always, True),
    ("review at warn is counted", 'if level == "warn":\n            log("team_review_warned"', 'if False:\n            log("team_review_warned"', sc_review_warn, True),
    ("review under bypass is counted", 'if st.get("bypass"):\n            log("team_bypass", agent=atype); return False', 'if False:\n            log("team_bypass", agent=atype); return False', sc_review_bypass, True),
    ("bypass lifts the build rule", 'if st.get("bypass"):\n            log("team_bypass", agent=atype); return\n        if level == "warn":', 'if False:\n            log("team_bypass", agent=atype); return\n        if level == "warn":', sc_bypass, True),
    ("strict has no cap", '        log("team_member_required", agent=atype)  ', '        st["tmr"] = st.get("tmr", 0) + 1\n        if st["tmr"] > 2: return\n        log("team_member_required", agent=atype)  ', sc_cap, True),
    ("warn level notes only", 'if level == "warn":\n            log("team_member_required_warned"', 'if False:\n            log("team_member_required_warned"', sc_warn, True),
    ("folder destinations", 'if r_ in TEAM_DIRS and cmd and (kind', 'if False and r_ in TEAM_DIRS and cmd and (kind', sc_folder, True),
    ("runtime-built shipm arguments", 'elif any(team_cmdvar(w_) for _a, _u, w_ in segs_):', 'elif False:', sc_cmdvar, True),
    ("folder-level overwrites", 'elif any(team_bulk(w_) for _a, _u, w_ in segs_):', 'elif False:', sc_bulk, True),
    ("git checkout of a branch", 'if sub_ in ("checkout", "switch") and "--" not in rest_', 'if False and "--" not in rest_', sc_checkout, True),
    ("git merge and friends", 'if sub_ in ("merge", "pull", "rebase", "cherry-pick", "revert", "am", "apply"):', 'if False:', sc_merge, True),
    ("git plumbing", 'return i_ < len(a_) and a_[i_] in TEAM_PLUMB', 'return False', sc_plumb, True),
    ("option values cannot hide the command", '(table or ADMIN_SUB).get(g_)', 'ADMIN_SUB.get(g_)', sc_opt, True),
    ("general-purpose is exempt", '"statusline-setup", "general-purpose")', '"statusline-setup",)', sc_general_purpose, True),
    ("legacy layout judges every role", 'if UL[0] and (r_ in READ_ONLY or r_ == "test"):', 'if True:', sc_build_role_only, True),
    ("user-level read-only roles are skipped", 'if UL[0] and (r_ in READ_ONLY or r_ == "test"):', 'if False:', sc_ul_skip, True),
    ("master verifier is free only in its own role", 'norm in ("verifier", "reviewer") and (kind == "review" or arole() in ("test", "review"))', 'norm in ("verifier", "reviewer") and kind == "review"', sc_verifier_free, True),
    ("record files are free for other roles", 'RECORD.match(rel(sp(ti.get("file_path")) or sp(ti.get("notebook_path"))))', 'False', sc_record, True),
    ("no table = no rule", 'TEAMC["t"] = ("none", [])\n            if sig_ is None:', 'TEAMC["t"] = ("damaged", [])\n            if sig_ is None:', sc_none_no_rule, True),
    ("missing-table note once", 'and not st.get("team_note")', 'and True', sc_note_once, True),
    ("missing-table note shown", 'NOTES.append("TEAM FLOW: No Team table yet', 'NOTES.append("" and "TEAM FLOW: No Team table yet', sc_note_first, True),
    ("tamper: file tools", 'if p_ and team_file(p_ if os.path.isabs(p_) else os.path.join(pd, p_)):', 'if False and team_file(p_ if os.path.isabs(p_) else os.path.join(pd, p_)):', sc_tamper_file, True),
    ("tamper: borrow record", 'fold(".agents/borrowed.json"))', 'fold(".agents/borrowedx.json"))', sc_tamper_record, True),
    ("tamper: bash targets", 'tam = lambda ap, kind="write": team_file(ap, kind, c)', 'tam = lambda ap, kind="write": False', sc_tamper_bash, True),
    ("tamper: shipm team add", 'if any(admin_seg(a_, u_, w_, TEAM_SUB) for', 'if False and any(admin_seg(a_, u_, w_, TEAM_SUB) for', sc_tamper_cmd, True),
    ("tamper: case folding", 'TEAM_NAMES = (fold("docs/SKILLS.md"),', 'TEAM_NAMES = ("docs/SKILLS.md",', sc_tamper_case, sys.platform == "darwin"),
    ("tamper: no bypass", 'hit = None; label = None\n', 'hit = None; label = None\n        if st.get("bypass"):\n            return\n', sc_tamper_bypass, True),
    ("tamper: warn level", 'if level == "warn":\n            log("team_table_write_warned"', 'if False:\n            log("team_table_write_warned"', sc_tamper_warn, True),
]
if src:
    tmp = pathlib.Path(tempfile.mkdtemp())
    for name, old, new, scen, active in MUT:
        if scen is None or not active:
            continue
        found = src.count(old) == 1
        mutated = tmp / "mut-gate.sh"
        mutated.write_text(src.replace(old, new, 1) if found else src)
        os.chmod(mutated, 0o755)
        orig_ok = scen(str(F.LEGACY_HOOK))
        mut_ok = scen(str(mutated)) if found else True
        check("mutant '%s' is noticed (original holds, mutant breaks it)" % name, found and orig_ok and not mut_ok, (found, orig_ok, mut_ok))
    shutil.rmtree(tmp, ignore_errors=True)
else:
    print("NOTE legacy shell gate not present: mutants skipped")

for p in projects:
    try:
        p.cleanup()
    except Exception:
        pass
print("\n%d checks, %d failed" % (n_checks[0], len(fails)))
sys.exit(1 if fails else 0)
