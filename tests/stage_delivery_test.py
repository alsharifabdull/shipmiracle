#!/usr/bin/env python3
"""Stage delivery (P5b T6): the stage module writes the reports and can deliver. End to end in a temp repo through the real dispatcher steps:
open CR (Arabic title) -> plan -> approve -> build -> test PASS -> review ACCEPT -> learn -> deliver, with the stage reports (private, state folder),
the CR report (repo, docs/reports) written by the hook itself (write_cr accepts a CR at learn), evidence kept for facts.py; auto-open does not count
files that were already dirty (flow's baseline); a CR report for an abandoned CR; `shipm hooks replay --engine` env; report_written matches the exact CR id.
Run: python3 tests/stage_delivery_test.py"""
import json, os, pathlib, re, shutil, subprocess, sys, tempfile, time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = pathlib.Path(tempfile.mkdtemp(prefix="stage-hook-")).resolve()
HOME, DEV, STATE, CONF, WS = (TMP / n for n in ("home", "dev", "state", "config", "ws"))
ENV = dict(os.environ, SHIPMIRACLE_TEST="1", SHIPMIRACLE_HOME=str(HOME), SHIPMIRACLE_DEV=str(DEV), SHIPMIRACLE_STATE=str(STATE), SHIPMIRACLE_CONFIG=str(CONF), SHIPMIRACLE_WS=str(WS), HOME=str(HOME))
for k in ("SHIPMIRACLE_DEBUG", "CLAUDECODE", "SHIPMIRACLE_ENFORCE_OWNER", "SHIPMIRACLE_QUIET", "SHIPMIRACLE_GATE_ENGINE", "SHIPMIRACLE_HOOK_INJECT", "SHIPMIRACLE_HOOK_NO_SPAWN", "SHIPMIRACLE_STAGE_REPLAY", "CLAUDE_PROJECT_DIR",
          "SHIPMIRACLE_FLOW_LEVEL", "SHIPMIRACLE_FLOW_VERDICT", "SHIPMIRACLE_HOOK_NO_LOAD"):
    ENV.pop(k, None)
os.environ.clear()
os.environ.update(ENV)
REAL = pathlib.Path("/Users/%s" % os.environ.get("USER", "x"))
for d in (HOME, DEV, STATE, CONF, WS / "config"):
    d.mkdir(parents=True, exist_ok=True)
(HOME / ".gitconfig").write_text("[user]\n name = t\n email = t@example.com\n[init]\n defaultBranch = main\n[commit]\n gpgsign = false\n")
(WS / "config" / "flow.json").write_text('{"default": "strict", "projects": {}}')
(CONF / "config.json").write_text(json.dumps({"gate.engine": "playbook"}))
(STATE / "health.json").write_text(json.dumps({"ts": time.time(), "chats": {}}))

from shipmiracle.hooks import core  # noqa: E402
from shipmiracle.hooks import autopilot as _AP  # noqa: E402
_AP._PS_CHAIN_OVERRIDE = ["claude", "zsh", "Terminal"]      # the owner's own top-level chat (P6 sec B1: approvals check the ancestry; tests never walk the real process tree)
from shipmiracle.playbook import engine, store, diffstat  # noqa: E402

for _ev, _slots in core.PIPELINES.items():                 # only the gate and the module under test (the others have their own suites and side effects)
    core.PIPELINES[_ev] = [s for s in _slots if s.name in ("flow", "stage")]

fails = 0
def check(name, ok, info=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(info)[:900]))
    fails += 0 if ok else 1

AGENT = "---\nname: {n}\nmodel: {m}\n---\nModel reason: test agent.\nFlow role: {r}\n"
AGENTS = {"solution-architect": ("opus", "plan"), "qa-engineer": ("sonnet", "test"), "backend-engineer": ("sonnet", "build"),
          "independent-reviewer": ("opus", "review"), "product-analyst": ("sonnet", "scope"), "ux-designer": ("sonnet", "design")}
SID = [0]


def shipm(*args, cwd=None):
    r = subprocess.run([sys.executable, str(ROOT / "bin" / "shipm")] + list(args), env=ENV, capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL, cwd=cwd)
    return r.returncode, r.stdout, r.stderr


class P:
    """A temp project under DEV with a team, a trusted playbook and a git history."""
    def __init__(self, name, ptype="software", autopilot="guided", sets=()):
        self.name = name
        self.P = DEV / name
        (self.P / ".claude/agents").mkdir(parents=True)
        (self.P / "src").mkdir()
        for n, (m, r) in AGENTS.items():
            (self.P / ".claude/agents" / (n + ".md")).write_text(AGENT.format(n=n, m=m, r=r))
        (self.P / "src/app.py").write_text("x = 1\n")
        (self.P / "docs").mkdir()
        (self.P / "docs/STATUS.md").write_text("Updated: 2020-01-01\n")
        subprocess.run(["git", "init", "-q", str(self.P)], env=ENV, check=True)
        self.git("add", "-A")
        self.git("commit", "-qm", "init")
        hp = STATE / "health.json"
        h = json.loads(hp.read_text())
        h["ts"] = time.time()
        h["chats"][name] = {"chats": 0}
        hp.write_text(json.dumps(h))
        for k, v in (("type", ptype), ("autopilot", autopilot)) + tuple(sets):
            code, out, err = shipm("playbook", "set", k, v, "--project", name)
            if code != 0:
                raise SystemExit("playbook set %s %s failed: %s %s" % (k, v, out, err))
        self.sid = "s%d" % (SID.__setitem__(0, SID[0] + 1) or SID[0])
        self.n = 0

    def git(self, *a):
        return subprocess.run(["git", "-C", str(self.P)] + list(a), env=ENV, capture_output=True, text=True).stdout

    def hk(self, event, **kw):
        core._FILES.clear()
        os.environ["CLAUDE_PROJECT_DIR"] = str(self.P)
        d = {"hook_event_name": event, "session_id": self.sid, "cwd": str(self.P)}
        d.update(kw)
        ctx = core.Ctx(json.dumps(d).encode(), event)
        res = core.run_pipeline(ctx, event)
        out, err, code = core.merge(event, res)
        o = json.loads(out) if out.strip() else {}
        return o

    # --- hook calls
    def prompt(self, text="go"):
        return self.hk("UserPromptSubmit", prompt=text)

    def agent_call(self, t):
        return self.hk("PreToolUse", tool_name="Agent", tool_input={"subagent_type": t, "prompt": "x"})

    def post_agent(self):
        return self.hk("PostToolUse", tool_name="Agent", tool_input={"subagent_type": "x"}, tool_response={"ok": True})

    def sub(self, atype, msg, name=None):
        self.n += 1
        return self.hk("SubagentStop", agent_id="a%d" % self.n, agent_type=atype, last_assistant_message=msg)

    def plan_stop(self):
        return self.sub("solution-architect", "Plan: do the thing.")

    def exit_plan(self, plan="# Add a feature\nsteps"):
        return self.hk("PostToolUse", tool_name="ExitPlanMode", tool_input={"plan": plan}, tool_response={})

    def build(self, rel="src/app.py", lines=2):
        p = self.P / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("".join("y%d = %d\n" % (i, i) for i in range(lines)) if rel.endswith(".py") else "z\n" * lines)
        return self.sub("backend-engineer", "Built.")

    def test(self, verdict="PASS", ev="`pytest` -> 214 passed, 0 failed"):
        return self.sub("qa-engineer", "Verdict: %s\nEvidence: %s\nNot verified: none" % (verdict, ev))

    def review(self, verdict="ACCEPT", lens="correctness", atype="independent-reviewer"):
        return self.sub(atype, "Verdict: %s\nLens: %s\nEvidence: read the diff" % (verdict, lens))

    def stop(self, msg="Done for now.", **kw):
        return self.hk("Stop", last_assistant_message=msg, **kw)

    # --- state
    def work(self):
        return store.load(str(self.P))

    def cr(self):
        return engine.active_cr(self.work())

    def stage(self):
        c = self.cr()
        return c["stage"] if c else None

    def events(self):
        p = STATE / "v1" / "events.jsonl"
        out = []
        if p.exists():
            for ln in p.read_text().splitlines():
                try:
                    out.append(json.loads(ln))
                except ValueError:
                    pass
        return out

    def ev(self, kind):
        pid = store.pid_of(str(self.P))
        return [e for e in self.events() if e.get("kind") == kind and e.get("project") == pid]

    def open(self, title="Add a feature", lane="full"):
        pd = str(self.P)
        snap = diffstat.snapshot(pd)
        from shipmiracle.playbook import gate
        rules = gate.stage_rules(pd)

        def fn(work):
            cr, trs = engine.open_cr(work, title, "owner", int(time.time()), lane=lane, base=snap["base"], rules=rules, kind="cli_open")
            store.save_snapshot(pd, cr["id"], snap)
            return cr, trs
        return store.transact(pd, fn)

    def commit(self, msg="CR work"):
        self.git("add", "-A")
        self.git("commit", "-qm", msg)


def mine(o):
    """A block that comes from the stage module (flow's own blocks have other texts)."""
    return blocked(o) and "TEAM FLOW (change request)" in text(o)


def blocked(o):
    return o.get("decision") == "block" or (o.get("hookSpecificOutput") or {}).get("permissionDecision") == "deny"


def text(o):
    return json.dumps(o, ensure_ascii=False)


def ctx_of(o):
    return ((o.get("hookSpecificOutput") or {}).get("additionalContext") or "") + (o.get("systemMessage") or "")


def kinds_in(o):
    return [k for k in ("cr_needs_plan", "cr_review_missing", "cr_continue", "manual_hold", "cr_blocked") if k in text(o)] if blocked(o) else []


def set_engine(v):
    (CONF / "config.json").write_text(json.dumps({"gate.engine": v}) if v else "{}")


def set_level(lv):
    (WS / "config" / "flow.json").write_text(json.dumps({"default": lv, "projects": {}}))




def mine(o):
    """A block that comes from the stage module (flow's own blocks have other texts)."""
    return blocked(o) and "TEAM FLOW (change request)" in text(o)


def blocked(o):
    return o.get("decision") == "block" or (o.get("hookSpecificOutput") or {}).get("permissionDecision") == "deny"


def text(o):
    return json.dumps(o, ensure_ascii=False)


def ctx_of(o):
    return ((o.get("hookSpecificOutput") or {}).get("additionalContext") or "") + (o.get("systemMessage") or "")


def kinds_in(o):
    return [k for k in ("cr_needs_plan", "cr_review_missing", "cr_continue", "manual_hold", "cr_blocked") if k in text(o)] if blocked(o) else []


def set_engine(v):
    (CONF / "config.json").write_text(json.dumps({"gate.engine": v}) if v else "{}")


def set_level(lv):
    (WS / "config" / "flow.json").write_text(json.dumps({"default": lv, "projects": {}}))



AR = "إصلاح اتجاه الكتابة في صفحة الدخول"
today = time.strftime("%Y-%m-%d")
set_engine = lambda v: (CONF / "config.json").write_text(json.dumps({"gate.engine": v}))
set_engine("playbook")
from shipmiracle.report import lint, write, facts  # noqa: E402
from shipmiracle.hooks import stage as STG  # noqa: E402
from shipmiracle import state as ST  # noqa: E402

# ====================================================================== 1. end to end, Arabic title
e = P("deliv")
e.prompt("fix the login direction")
code, out, err = shipm("cr", "open", AR, "--lane", "full", "--project", "deliv")
check("1a shipm cr open with an Arabic title", code == 0 and "CR-001" in out, (code, out, err))
e.plan_stop()
e.exit_plan("# " + AR + "\nstep 1")
check("1b plan presented: approve", e.stage() == "approve", e.cr())
e.prompt("approved, go")
check("1c approved: do", e.stage() == "do", e.cr())
e.build(lines=3)
check("1d build: verify", e.stage() == "verify", e.cr())
e.test("PASS", "`pytest tests` -> 214 passed, 0 failed")
check("1e test PASS: review", e.stage() == "review", e.cr())
e.review("ACCEPT", "correctness")
check("1f review ACCEPT: deliver", e.stage() == "deliver", e.cr())
e.commit("CR-001: fix direction")
e.stop("All committed.")
check("1g committed: learn", e.stage() == "learn", e.cr())
(e.P / "docs/STATUS.md").write_text("Updated: %s\n" % today)
e.commit("status")
reports = e.P / "docs" / "reports"
check("1h no CR report yet", not reports.exists() or not list(reports.glob("*.md")))
o = e.stop("Status updated.")
cr = [c for c in e.work()["crs"] if c["id"] == "CR-001"][0]
check("1i Stop at learn: the hook wrote the CR report and the CR is delivered", cr["status"] == "delivered" and e.cr() is None, cr)
rp = list(reports.glob("*CR-001.md"))
check("1j docs/reports/<day>-CR-001.md exists", len(rp) == 1 and rp[0].name == today + "-CR-001.md", rp)
txt = rp[0].read_text(encoding="utf-8") if rp else ""
check("1k the report has the Arabic title, DELIVERED, PASS and the test evidence", AR in txt and "DELIVERED" in txt.splitlines()[0] and "PASS" in txt.splitlines()[0] and "214" in txt, txt)
check("1l the report passes the lint", lint.lint_text(txt) == [], lint.lint_text(txt))
check("1m the log records the report path (op report)", any(r.endswith("-CR-001.md") for r in cr["reports"]), cr["reports"])
pid = store.pid_of(str(e.P))
sd = STATE / "v1" / "reports" / pid
names = sorted(p.name for p in sd.glob("*.md")) if sd.exists() else []
stages = {n.split("CR-001-")[1].split(".md")[0].split("-")[0] for n in names}
check("1n stage reports for plan, approve, do, verify, review, deliver, learn", {"plan", "approve", "do", "verify", "review", "deliver", "learn"} <= stages, names)
vt = next((p.read_text(encoding="utf-8") for p in sd.glob("*-verify*.md")), "") if sd.exists() else ""
check("1n2 one learn report only (written when the CR is delivered)", len([n for n in names if "-learn" in n]) == 1, names)
check("1o the verify stage report carries the verifier's evidence and command", "214 passed" in vt and "pytest tests" in vt and "Not verified: none" in vt, vt)
check("1p every stage report passes the lint", sd.exists() and all(lint.lint_text(p.read_text(encoding="utf-8")) == [] for p in sd.glob("*.md")), [(p.name, lint.lint_text(p.read_text(encoding="utf-8"))) for p in sd.glob("*.md")])
idx = json.loads((STATE / "v1" / "reports" / "index.json").read_text())["items"]
check("1q the panel index lists the CR report (public) and stage reports (private)", any(i["kind"] == "cr" and i["cr"] == "CR-001" and not i["private"] for i in idx) and any(i["kind"] == "stage" and i["private"] for i in idx), idx[:3])
fct = facts.build(str(e.P), "CR-001")
vv = [v for v in fct["verdicts"] if v["stage"] == "verify"]
check("1r facts read the evidence the hook captured", vv and "214 passed" in vv[-1]["evidence"] and vv[-1]["cmd"] == "pytest tests", vv)
o = e.stop("again")
check("1s a further Stop after delivery changes nothing", not mine(o) and len(list(reports.glob("*CR-001*.md"))) == 1)
shown = shipm("cr", "show", "CR-001", "--project", "deliv")[1]
check("1t shipm cr show shows it delivered", "delivered" in shown.lower() or "Delivered" in shown, shown)

# ====================================================================== 2. write_cr direct: refuses before learn, accepts at learn
g = P("gamma")
g.prompt("x")
g.open("Plain title")
try:
    write.write_cr(str(g.P), "CR-001")
    ok = False
except Exception as ex:
    ok = "report is written when it is delivered or abandoned" in str(ex)
check("2a write_cr on a CR at scope is refused", ok)
check("2b nothing was written", not (g.P / "docs" / "reports").exists() or not list((g.P / "docs" / "reports").glob("*.md")))

# ====================================================================== 3. report_written: only a report the engine logged (op:report + content sha) counts
import hashlib as _h
class FC:
    pass
fc = FC()
fc.pd = str(g.P)
(g.P / "docs" / "reports").mkdir(parents=True, exist_ok=True)
rp12 = g.P / "docs" / "reports" / "2026-10-20-CR-012.md"
rp12.write_text("x")
REL = "docs/reports/2026-10-20-CR-012.md"
class FS:
    sha = None
    @staticmethod
    def load(pd):
        w = engine.new_work()
        w["crs"] = [{"id": "CR-012", "report_sha": ({REL: FS.sha} if FS.sha else {})}, {"id": "CR-1", "report_sha": {}}]
        return w
check("3a (P5 sec M3) a file named CR-012.md with NO op:report line is not accepted", not STG._report_written(fc, "CR-012", FS))
FS.sha = _h.sha256(b"x").hexdigest()
check("3b a logged report with the same content sha is accepted", STG._report_written(fc, "CR-012", FS))
rp12.write_text("x edited by the model")
check("3c ... a changed file is no longer the report the engine wrote", not STG._report_written(fc, "CR-012", FS))
rp12.write_text("x")
rp12.unlink(); os.symlink(str(g.P / "docs" / "STATUS.md"), str(rp12))
FS.sha = _h.sha256((g.P / "docs" / "STATUS.md").read_bytes()).hexdigest()
check("3d ... a symlink with the right sha is refused", not STG._report_written(fc, "CR-012", FS))
rp12.unlink(); rp12.write_text("x")
FS.sha = _h.sha256(b"x").hexdigest()
check("3e another CR id (CR-1 / CR-0123) is not satisfied by CR-012's report", not STG._report_written(fc, "CR-1", FS) and not STG._report_written(fc, "CR-0123", FS))

# ====================================================================== 4. auto-open ignores what was dirty before the session
h = P("hotel")
(h.P / "src" / "old1.py").write_text("old\n" * 40)
(h.P / "src" / "old2.py").write_text("old\n" * 40)
h.git("add", "-A"); h.git("commit", "-qm", "more")
for n in ("old1.py", "old2.py"):
    (h.P / "src" / n).write_text("dirty before the session\n" * 30)
(h.P / "src" / "scratch.txt").write_text("untracked before\n" * 30)
h.prompt("work")                                 # flow takes its baseline here
base = json.loads((STATE / ("flow.%s.json" % h.sid)).read_text()).get("baseline")
check("4a flow's baseline lists the three dirty files", sorted(base or []) == ["src/old1.py", "src/old2.py", "src/scratch.txt"], base)
h.plan_stop() if False else None
h.build("src/new.py", lines=3)                   # a build stop with no CR: auto-open
c = h.cr()
check("4b auto-open: the diff counts only the new file (fast lane kept)", c is not None and c["diff"]["files"] == 1 and c["lane"] == "fast", c)
c2 = h.work()
check("4c the saved snapshot carries the ignore list", store.load_snapshot(str(h.P), c["id"]).get("ignore") == sorted(base) or set(store.load_snapshot(str(h.P), c["id"]).get("ignore") or []) == set(base))
h.test("PASS")
check("4d the fast lane goes on to verify/deliver, not promoted", h.cr()["lane"] == "fast" and h.cr()["stage"] in ("deliver", "review"), h.cr())

# ====================================================================== 5. abandon writes the CR report
k = P("kilo")
k.prompt("x")
shipm("cr", "open", "Something we drop", "--project", "kilo")
code, out, err = shipm("cr", "abandon", "CR-001", "--project", "kilo")
rk = list((k.P / "docs" / "reports").glob("*CR-001.md")) if (k.P / "docs" / "reports").exists() else []
check("5a shipm cr abandon: exit 0 and a report is written", code == 0 and len(rk) == 1 and "Report: docs/reports/" in out, (code, out, err, rk))
t5 = rk[0].read_text(encoding="utf-8") if rk else ""
check("5b the report says ABANDONED and passes the lint", "ABANDONED" in t5.splitlines()[0] and lint.lint_text(t5) == [], (t5, lint.lint_text(t5)))

# ====================================================================== 6. replay --engine
from shipmiracle.hooks import replay  # noqa: E402
hm = replay.Home.__new__(replay.Home)
for a, v in (("proj", TMP / "p"), ("home", HOME), ("cfg", CONF), ("state", STATE), ("dev", DEV), ("ws", WS), ("stublog", TMP / "stub"), ("bin", TMP / "bin"), ("tmp", TMP / "t")):
    setattr(hm, a, v)
replay.ENGINE = None
e0 = hm.env()
replay.ENGINE = "shadow"
e1 = hm.env()
replay.ENGINE = None
check("6a without --engine the stage module stays inert in a replay", "SHIPMIRACLE_STAGE_REPLAY" not in e0 and e0.get("SHIPMIRACLE_HOOK_NO_SPAWN") == "1")
check("6b --engine sets SHIPMIRACLE_STAGE_REPLAY=1 and the engine", e1.get("SHIPMIRACLE_STAGE_REPLAY") == "1" and e1.get("SHIPMIRACLE_GATE_ENGINE") == "shadow" and e1.get("SHIPMIRACLE_HOOK_NO_SPAWN") == "1", e1)
r = subprocess.run([sys.executable, str(ROOT / "bin" / "shipm"), "hooks", "replay", "--engine", "bogus"], env=ENV, capture_output=True, text=True, stdin=subprocess.DEVNULL)
check("6c a wrong --engine value is a usage error", r.returncode == 2, (r.returncode, r.stderr[-200:]))

# ====================================================================== 7. a report failure never breaks the hook
m = P("mike")
m.prompt("x")
m.open()
m.plan_stop()
(STATE / "v1" / "reports").mkdir(parents=True, exist_ok=True)
shutil.rmtree(STATE / "v1" / "reports" / store.pid_of(str(m.P)), ignore_errors=True)
os.symlink(str(TMP / "elsewhere"), str(STATE / "v1" / "reports" / store.pid_of(str(m.P))))
o = m.exit_plan()
check("7a a refused report location (symlink) does not stop the stage", m.stage() == "approve" and not blocked(o), (m.cr(), o))

shutil.rmtree(TMP, ignore_errors=True)
print("ALL PASS" if not fails else "%d FAILED" % fails)
sys.exit(1 if fails else 0)
