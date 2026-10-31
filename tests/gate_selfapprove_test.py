#!/usr/bin/env python3
"""gate_selfapprove_test: a QA or review agent must not fix the source and then approve its own fix (G9 round 3 blocker re-check).
Both layouts (legacy, user-level), both gate copies, levels strict / warn / off. Rules:
  A) test roles (verifier, qa-engineer) write only test paths and records; review roles (reviewer, independent-reviewer, security-reviewer) only records; refused at strict.
  B) a test or review edit outside test paths and records counts as a build (build_ts, built_by), and the verdict of an agent that edited source in its own run is ignored.
Mutants (legacy source): each rule is noticed. Run: python3 tests/gate_selfapprove_test.py"""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import shipmiracle_isolation; shipmiracle_isolation.apply_to_environ()   # test isolation
import json, os, pathlib, shutil, subprocess, sys, tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import flow_fixture as F
from flow_fixture import deny, note, AGENT_TEXT
from shipmiracle import agents as AG

# read-only roles may write under the temp folders: the sandboxes must live elsewhere
tempfile.tempdir = next((d for d in ('/var/tmp', str(pathlib.Path.home() / '.cache')) if os.path.isdir(d) and os.access(d, os.W_OK)), None)
fails = []; n_checks = [0]; projects = []


def check(name, ok, info=""):
    n_checks[0] += 1
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(info)[:500]))
    if not ok:
        fails.append(name)


IMPLS = ([("legacy", str(F.LEGACY_HOOK))] if F.LEGACY_HOOK.exists() else []) + [("v1", str(F.V1_HOOK))]
MASTERS_WS = pathlib.Path(tempfile.mkdtemp(prefix="sa-ws-"))
shutil.copytree(ROOT / "agents/claude", MASTERS_WS / "agents/claude")
TESTERS = ("qa-engineer", "verifier")
REVIEWERS = ("reviewer", "independent-reviewer", "security-reviewer")
REPORT = "Verdict: {v}\nEvidence: 3 passed, 0 failed\n"


class W:
    def __init__(self, hook, level="strict", ul=False):
        self.hook = hook
        self.p = p = F.make_project("proj", agents={"builder-a": AGENT_TEXT.format(n="builder-a", m="sonnet", r="build")}); projects.append(p)
        os.symlink(str(ROOT / "shipmiracle"), str(p.WSF / "shipmiracle"))
        self.cfg = p.T / "cfg"; self.cfg.mkdir(); self.home = p.T / "home"; (self.home / ".claude").mkdir(parents=True); (p.T / "hooktmp").mkdir()
        p.ENV.update(SHIPMIRACLE_CONFIG=str(self.cfg), SHIPMIRACLE_HOME=str(self.home), HOME=str(self.home), TMPDIR=str(p.T / "hooktmp"))
        if ul:
            (self.cfg / "config.json").write_text(json.dumps({"agents.layout": "userlevel"}))
            for k, v in (("SHIPMIRACLE_CONFIG", self.cfg), ("SHIPMIRACLE_HOME", self.home), ("SHIPMIRACLE_STATE", p.STATE), ("SHIPMIRACLE_DEV", p.DEV), ("SHIPMIRACLE_WS", p.WSF)):
                os.environ[k] = str(v)
            AG.install(ws=MASTERS_WS, home=self.home)
        p.level(level)
        (p.P / "tests").mkdir(exist_ok=True); (p.P / "docs/plans").mkdir(parents=True, exist_ok=True)
        self.call("UserPromptSubmit", "s0", prompt="go")

    def call(self, ev, sid, agent=None, aid="ag1", **kw):
        d = {"hook_event_name": ev, "session_id": sid, "cwd": str(self.p.P), **kw}
        if agent:
            d.update(agent_id=aid, agent_type=agent)
        r = subprocess.run(["bash", self.hook], input=json.dumps(d), capture_output=True, text=True, env=dict(self.p.ENV), cwd=str(self.p.P))
        try:
            return json.loads(r.stdout) if r.stdout.strip() else {}
        except Exception:
            return {"raw": r.stdout, "err": r.stderr}

    def write(self, agent, rel, sid="w1", tool="Write"):
        self.call("UserPromptSubmit", sid, prompt="go")
        return self.call("PreToolUse", sid, agent=agent, aid="a-" + agent, tool_name=tool, tool_input={"file_path": str(self.p.P / rel), "content": "x"})

    def bash(self, agent, cmd, sid="w1"):
        self.call("UserPromptSubmit", sid, prompt="go")
        return self.call("PreToolUse", sid, agent=agent, aid="a-" + agent, tool_name="Bash", tool_input={"command": cmd})

    def seq(self, who, sid="z", verdict="PASS"):
        """builder edits src; `who` edits src (Pre output ignored, as a hole would be exploited), then stops with a verdict; returns (state, Stop output)."""
        c = self.call; P = str(self.p.P / "src/app.py")
        c("UserPromptSubmit", sid, prompt="go")
        e1 = {"file_path": P, "old_string": "x = 1", "new_string": "x = 2"}
        c("PreToolUse", sid, agent="builder-a", aid="b1", tool_name="Edit", tool_input=e1)
        c("PostToolUse", sid, agent="builder-a", aid="b1", tool_name="Edit", tool_input=e1)
        c("SubagentStop", sid, agent="builder-a", aid="b1", last_assistant_message="done")
        self.bt1 = self.p.state(sid).get("build_ts")
        e2 = {"file_path": P, "old_string": "x = 2", "new_string": "x = 3"}
        self.pre2 = c("PreToolUse", sid, agent=who, aid="q1", tool_name="Edit", tool_input=e2)
        c("PostToolUse", sid, agent=who, aid="q1", tool_name="Edit", tool_input=e2)
        self.st_mid = self.p.state(sid)
        v = "ACCEPT" if who in REVIEWERS else verdict
        c("SubagentStop", sid, agent=who, aid="q1", last_assistant_message=REPORT.format(v=v))
        return self.p.state(sid), c("Stop", sid, stop_hook_active=False)

    def indep(self, sid="y"):
        """Control: builder edits src, an independent QA agent writes only a test and reports PASS."""
        c = self.call
        c("UserPromptSubmit", sid, prompt="go")
        e1 = {"file_path": str(self.p.P / "src/app.py"), "old_string": "x = 1", "new_string": "x = 2"}
        c("PreToolUse", sid, agent="builder-a", aid="b1", tool_name="Edit", tool_input=e1)
        c("PostToolUse", sid, agent="builder-a", aid="b1", tool_name="Edit", tool_input=e1)
        c("SubagentStop", sid, agent="builder-a", aid="b1", last_assistant_message="done")
        e2 = {"file_path": str(self.p.P / "tests/t_test.py"), "content": "x"}
        o = c("PreToolUse", sid, agent="qa-engineer", aid="q1", tool_name="Write", tool_input=e2)
        c("PostToolUse", sid, agent="qa-engineer", aid="q1", tool_name="Write", tool_input=e2)
        c("SubagentStop", sid, agent="qa-engineer", aid="q1", last_assistant_message=REPORT.format(v="PASS"))
        return deny(o), self.p.state(sid), c("Stop", sid, stop_hook_active=False)


def sc_write_denied(hook, ul=False):
    """strict: a master tester writing src / a reviewer writing tests are refused; tests and records allowed per role."""
    w = W(hook, "strict", ul)
    ok = all(deny(w.write(a, "src/n.py")) for a in TESTERS + REVIEWERS)
    ok = ok and all(deny(w.bash(a, "echo x > src/b.py")) for a in TESTERS + REVIEWERS)
    ok = ok and all(not deny(w.write(a, "tests/t_test.py")) for a in TESTERS)
    ok = ok and all(deny(w.write(a, "tests/t_test.py")) for a in REVIEWERS)
    ok = ok and all(not deny(w.write(a, "docs/plans/p.md")) and not deny(w.write(a, "docs/STATUS.md")) for a in TESTERS + REVIEWERS)
    return ok


def sc_levels(hook, ul=False):
    w = W(hook, "warn", ul); ok = not any(deny(w.write(a, "src/n.py")) for a in TESTERS + REVIEWERS)
    ok = ok and "TEAM FLOW" in note(w.write("qa-engineer", "src/n.py")) + note(w.write("reviewer", "src/n.py", sid="w2"))
    w = W(hook, "off", ul)
    return ok and not any(deny(w.write(a, "src/n.py")) for a in TESTERS + REVIEWERS)


def sc_selfapprove_blocks(hook, ul=False, level="strict"):
    """The 4-step sequence does not pass clean (Stop blocks) at strict; at warn the verdict is still ignored (state)."""
    w = W(hook, level, ul)
    for who in TESTERS:
        st, stop = w.seq(who, "z-" + who)
        if st.get("qa_verdict") == "PASS" or (level == "strict" and not deny(stop)):
            return False
    return True


def sc_build_ts(hook, ul=False):
    w = W(hook, "warn", ul)                      # warn lets the edit happen, so only the PostToolUse rule is under test
    st, _s = w.seq("qa-engineer", "b-q")
    ok = w.st_mid.get("build_ts", 0) > w.bt1 and w.st_mid.get("built_by") == "qa-engineer"
    st, _s = w.seq("reviewer", "b-r")
    return ok and w.st_mid.get("built_by") == "reviewer"


def sc_verdict_ignored(hook, ul=False):
    w = W(hook, "warn", ul)
    st, stop = w.seq("qa-engineer", "v-q")
    ok = st.get("qa_verdict") in (None, "") and not st.get("qa_runs")
    st, stop = w.seq("reviewer", "v-r")
    return ok and not st.get("review_verdict")


def sc_indep_passes(hook, ul=False):
    w = W(hook, "strict", ul)
    d, st, stop = w.indep()
    return (not d) and st.get("qa_verdict") == "PASS" and not deny(stop) and w.p.state("y").get("built_by") == "builder-a"


for impl, hook in IMPLS:
    for ul in (False, True):
        tag = "[%s/%s]" % (impl, "userlevel" if ul else "legacy")
        check(tag + " strict: testers/reviewers writing src refused, tests/records allowed per role", sc_write_denied(hook, ul))
        check(tag + " warn notes only, off silent", sc_levels(hook, ul))
        check(tag + " self-approval sequence (builder edit, QA edit, QA PASS) does not pass clean at strict", sc_selfapprove_blocks(hook, ul))
        check(tag + " warn: QA edit still counts as a build and its own verdict is ignored", sc_build_ts(hook, ul) and sc_verdict_ignored(hook, ul))
        check(tag + " member builder + independent QA (tests only) still passes clean", sc_indep_passes(hook, ul))

from shipmiracle.hooks import io as HIO
check("hooks/io._temp_ok agrees with paths.sandboxed: /var/tmp is not a temp root, /tmp is", not HIO._temp_ok("/var/tmp/x") and HIO._temp_ok("/tmp/x"))

# before/after evidence line for the report
if IMPLS:
    w = W(IMPLS[0][1], "strict", False); st, stop = w.seq("qa-engineer", "ev")
    print("INFO self-approval via %s: pre2 denied=%s qa_verdict=%s stop_blocks=%s" % (IMPLS[0][0], deny(w.pre2), st.get("qa_verdict"), deny(stop)))

MUT = [
    ("legacy layout tester/reviewer check", 'ro = e_ == "review"  ', 'ro = False  ', lambda h: sc_write_denied(h, False) and sc_selfapprove_blocks(h, False)),
    ("legacy: tester role skipped", "tst = not ro and \"test\" in (c_, e_)", "tst = not ro and \"test\" in (c_, e_) and UL[0]", lambda h: sc_write_denied(h, False)),
    ("records allowed for restricted roles", "if inside(r_) and RECORD.match(r_) and (not UL[0]", "if False and (not UL[0]", lambda h: sc_write_denied(h, False)),
    ("test paths allowed for testers", "return inside(r_) and any(g_.match(r_) for g_ in gre)", "return False", lambda h: sc_write_denied(h, False)),
    ("QA edit outside tests is a build", 'if arole() != "test" or not is_test_path(r):', 'if arole() != "test":', lambda h: sc_build_ts(h, False)),
    ("test-path edit by QA is not a build", 'if arole() != "test" or not is_test_path(r):', 'if True:', lambda h: sc_indep_passes(h, False)),
    ("source editors recorded", 'se_[sp(agent)] = now; st["src_editors"]', 'se_[sp(agent)] = now; st["src_editorsx"]', lambda h: sc_verdict_ignored(h, False)),
    ("own verdict ignored", "elif r in (\"test\", \"review\") and agent and sp(agent) in", "elif False and agent and sp(agent) in", lambda h: sc_verdict_ignored(h, False) and sc_selfapprove_blocks(h, False)),
    ("warn level notes only", 'if level == "warn":\n                log("readonly_refused_warned"', 'if False:\n                log("readonly_refused_warned"', lambda h: sc_levels(h, False)),
]
if IMPLS and IMPLS[0][0] == "legacy":
    src = F.LEGACY_HOOK.read_text(); tmp = pathlib.Path(tempfile.mkdtemp())
    for name, old, new, scen in MUT:
        found = src.count(old) == 1
        m = tmp / "mut-gate.sh"; m.write_text(src.replace(old, new, 1) if found else src); os.chmod(m, 0o755)
        orig_ok = scen(str(F.LEGACY_HOOK)); mut_ok = scen(str(m)) if found else True
        check("mutant '%s' is noticed (original holds, mutant breaks it)" % name, found and orig_ok and not mut_ok, (found, orig_ok, mut_ok))
    shutil.rmtree(tmp, ignore_errors=True)
else:
    print("NOTE legacy shell gate not present: mutants skipped")

for p in projects:
    try:
        p.cleanup()
    except Exception:
        pass
shutil.rmtree(MASTERS_WS, ignore_errors=True)
print("\n%d checks, %d failed" % (n_checks[0], len(fails)))
sys.exit(1 if fails else 0)
