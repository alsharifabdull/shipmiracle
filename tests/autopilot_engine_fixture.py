"""World for the P6 T5 suites (worktree / deliver / budget / e2e). Not a test. It builds on tests/autopilot_hook_fixture.py (a fully temp HOME / DEV / STATE /
config / workspace, SHIPMIRACLE_TEST=1, project `sandbox` with a trusted software playbook with autopilot full, CRs 001-003, fresh plan.json) and adds: a team
(.claude/agents committed in main), a .githooks/post-commit file, a LOCAL bare temp origin that the visibility cache says is private, a fresh health.json
(no open chat in main), and a driver `Chat` that sends hook events (flow + stage + autopilot slots) from inside the auto worktree. No network: the only
push goes to the bare temp origin."""
import json, os, pathlib, subprocess, sys, time

import autopilot_hook_fixture as F

TMP, DEV, STATE, MAIN, PID, ROOT = F.TMP, F.DEV, F.STATE, F.MAIN, F.PID, F.ROOT
ORIGIN = TMP / "origin.git"
git, sh, shipm, write_plan = F.git, F.sh, F.shipm, F.write_plan

from shipmiracle import config, registry, projects  # noqa: E402
from shipmiracle.autopilot import charter as ch, state as S, visibility, worktree as W, deliver, budget  # noqa: E402
from shipmiracle.playbook import engine, store  # noqa: E402
from shipmiracle.hooks import core  # noqa: E402

AGENT = "---\nname: {n}\nmodel: {m}\n---\nModel reason: test agent.\nFlow role: {r}\n"
AGENTS = {"solution-architect": ("opus", "plan"), "qa-engineer": ("sonnet", "test"), "backend-engineer": ("sonnet", "build"),
          "independent-reviewer": ("opus", "review"), "product-analyst": ("sonnet", "scope"), "security-reviewer": ("opus", "review")}
LINE = 'charter: goal="ship login"; scope="src/**,tests/**,docs/**,package.json"; budget=10%; time=3h; deps=none; ends=CR-001..CR-003'
SID = "sess0001abc"
fails = 0


def check(name, ok, info=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(info)[:900]))
    fails += 0 if ok else 1


def build():
    """The world (once per process)."""
    F.build_world()
    (MAIN / ".claude" / "agents").mkdir(parents=True)
    for n, (m, r) in AGENTS.items():
        (MAIN / ".claude" / "agents" / (n + ".md")).write_text(AGENT.format(n=n, m=m, r=r))
    (MAIN / ".githooks").mkdir()
    (MAIN / ".githooks" / "post-commit").write_text("#!/bin/sh\nexit 0\n")
    (MAIN / ".gitignore").write_text("*.log\nnode_modules/\n.shipmiracle/\n")
    git(MAIN, "add", ".claude", ".githooks", ".gitignore")
    git(MAIN, "commit", "-qm", "team and hooks")
    git(TMP, "init", "-q", "--bare", str(ORIGIN))
    git(MAIN, "remote", "add", "origin", str(ORIGIN))
    git(MAIN, "push", "-q", "origin", "main")
    visibility.write_entry(str(ORIGIN), True)
    fresh_health()


def fresh_health(chats=0):
    (STATE / "health.json").write_text(json.dumps({"ts": time.time(), "chats": {"sandbox": {"chats": chats}}}))


def set_charter(line=LINE):
    """Charter through store_from_prompt (the hook's writer) and the owner CLI start (--yes --ack): worktree auto-CR-001 is created."""
    shipm("autopilot", "stop", "--project", "sandbox")
    S.delete(PID)
    write_plan(34)
    r = ch.store_from_prompt(PID, line, SID)
    c = r["charter"]
    code, out, err = shipm("autopilot", "start", "--project", "sandbox", "--yes", "--ack", c["id"])
    return code, out, err


def cleanup():
    """Between scenarios: end any run, remove every auto worktree and auto branch (merged or not), forget stale worktree entries."""
    import re
    shipm("autopilot", "stop", "--project", "sandbox")
    S.delete(PID)
    root = DEV / ".worktrees" / "sandbox"
    if root.exists():
        for d in sorted(root.iterdir()):
            sh(["git", "-C", str(MAIN), "worktree", "remove", "--force", str(d)])
    sh(["git", "-C", str(MAIN), "worktree", "prune"])
    code, out, err = sh(["git", "-C", str(MAIN), "for-each-ref", "--format=%(refname:short)", "refs/heads/auto/"])
    for b in out.split():
        sh(["git", "-C", str(MAIN), "branch", "-D", b])


_SID = [0]


def new_run(tag, budget=10, time_h="3h", extra=""):
    """A fresh CR in the main log, a charter whose ends is just that CR, `shipm autopilot start`: returns (cr id, Chat in its worktree)."""
    import re
    cleanup()
    code, out, err = shipm("cr", "open", "change " + tag, "--project", str(MAIN))
    cr = re.search(r"CR-\d+", out).group(0)
    write_plan(34)
    fresh_health()
    line = 'charter: goal="%s"; scope="src/**,tests/**,docs/**,package.json"; budget=%d%%; time=%s; deps=none; ends=%s%s' % (tag, budget, time_h, cr, extra)
    r = ch.store_from_prompt(PID, line, SID)
    code, out, err = shipm("autopilot", "start", "--project", "sandbox", "--yes", "--ack", r["charter"]["id"])
    if code != 0:
        raise SystemExit("new_run: start failed: %s %s" % (out, err))
    _SID[0] += 1
    return cr, Chat(wt_path(cr), sid="run%05d" % _SID[0])


def wt_path(cr="CR-001"):
    return DEV / ".worktrees" / "sandbox" / ("auto-" + cr)


def events(kind=None):
    return F.events(kind)


class Chat:
    """A chat inside the auto worktree: hook events through the real dispatcher (flow + stage + autopilot slots)."""
    def __init__(self, wt=None, sid=SID):
        self.wt = pathlib.Path(wt or wt_path())
        self.sid = sid
        self.n = 0
        F.reset_core(only=["flow", "stage", "autopilot"])

    def hk(self, event, **kw):
        o, e, _c = F.hook(event, cwd=self.wt, project_dir=self.wt, sid=self.sid, **kw)
        self.err = e
        return o

    def prompt(self, text="go"):
        return self.hk("UserPromptSubmit", prompt=text)

    def sub(self, atype, msg):
        self.n += 1
        return self.hk("SubagentStop", agent_id="a%d" % self.n, agent_type=atype, last_assistant_message=msg)

    def agent_call(self, t):
        return self.hk("PreToolUse", tool_name="Agent", tool_input={"subagent_type": t, "prompt": "x"})

    def plan_stop(self):
        return self.sub("solution-architect", "Plan: do the thing.")

    def exit_plan(self, plan="# Login form\nsteps"):
        return self.hk("PostToolUse", tool_name="ExitPlanMode", tool_input={"plan": plan}, tool_response={})

    def build(self, rel="src/login/form.py", text="def form():\n    return 1\n"):
        p = self.wt / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return self.sub("backend-engineer", "Built.")

    def test(self, verdict="PASS", ev="`pytest` -> 12 passed, 0 failed"):
        return self.sub("qa-engineer", "Verdict: %s\nEvidence: %s\nNot verified: none" % (verdict, ev))

    def review(self, verdict="ACCEPT", lens="correctness", atype="independent-reviewer"):
        return self.sub(atype, "Verdict: %s\nLens: %s\nEvidence: read the diff" % (verdict, lens))

    def stop(self, msg="Done for now.", **kw):
        return self.hk("Stop", last_assistant_message=msg, **kw)

    def commit(self, msg="work"):
        git(self.wt, "add", "-A")
        git(self.wt, "commit", "-qm", msg)

    def work(self):
        return store.load(str(self.wt))

    def cr(self):
        return engine.active_cr(self.work())

    def stage(self):
        c = self.cr()
        return c["stage"] if c else None

    def through_review(self):
        """prompt -> plan -> (charter approves) -> build -> test PASS -> review ACCEPT."""
        self.prompt("go")
        self.plan_stop()
        self.exit_plan()
        self.build()
        self.test()
        return self.review()

    def deliver_and_learn(self):
        """commit the build, then the Learn stage (STATUS dated today, committed); the Stop that follows writes the report and delivers."""
        self.commit("Add login form")
        self.stop("ok")                                       # deliver stage: git_delivered
        (self.wt / "docs" / "STATUS.md").write_text("Updated: %s\nrun %s\n" % (time.strftime("%Y-%m-%d"), time.time()))
        self.commit("STATUS")
        return self.stop("ok")


def merged(branch="auto/CR-001"):
    rc, _o, _e = sh(["git", "-C", str(MAIN), "merge-base", "--is-ancestor", branch, "HEAD"])
    return rc == 0


def origin_head():
    code, out, err = sh(["git", "-C", str(ORIGIN), "rev-parse", "refs/heads/main"])
    return out.strip() if code == 0 else None


def main_head():
    return git(MAIN, "rev-parse", "HEAD").strip()
