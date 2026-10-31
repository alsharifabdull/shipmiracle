#!/usr/bin/env python3
"""F6 engine pieces (release scope C3): (5) "fix the playbook" after a double-failed Verify: a proposed playbook edit (unified diff of the playbook text, current vs proposed) in the CR
report and as `.shipmiracle/playbook.draft.md`, untrusted, size-capped, applied only by the owner with `shipm playbook set --from-draft` (typed confirmation), the chat has no patching
path; (6) the Short/Long measurement: per finished CR the interview mode and the rework rounds, and `shipm playbook interview --report` (counts per mode, median rework, N, a plain
sentence that N<10 is not evidence; read-only, local). Real hook calls in a temp project; no model, no network.
Run: python3 tests/engine_fixplan_test.py"""
import json, os, pathlib, subprocess, sys, time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import shipmiracle_isolation as ISO  # noqa: E402

ENV, TMPS = ISO.isolated_env()
TMP = pathlib.Path(TMPS)
HOME, DEV, STATE, CONF, WS = pathlib.Path(ENV["HOME"]), pathlib.Path(ENV["SHIPMIRACLE_DEV"]), pathlib.Path(ENV["SHIPMIRACLE_STATE"]), pathlib.Path(ENV["SHIPMIRACLE_CONFIG"]), pathlib.Path(ENV["SHIPMIRACLE_WS"])
for k in ("SHIPMIRACLE_DEBUG", "CLAUDECODE", "SHIPMIRACLE_ENFORCE_OWNER", "SHIPMIRACLE_QUIET", "SHIPMIRACLE_GATE_ENGINE", "SHIPMIRACLE_HOOK_NO_SPAWN", "SHIPMIRACLE_STAGE_REPLAY", "CLAUDE_PROJECT_DIR"):
    ENV.pop(k, None)
os.environ.update(ENV)
(WS / "config").mkdir(parents=True, exist_ok=True)
(WS / "config" / "flow.json").write_text('{"default": "strict", "projects": {}}')
(CONF / "config.json").write_text(json.dumps({"gate.engine": "playbook"}))
(STATE / "health.json").write_text(json.dumps({"ts": time.time(), "chats": {}}))

from shipmiracle.hooks import core  # noqa: E402
from shipmiracle.hooks import autopilot as _AP  # noqa: E402
_AP._PS_CHAIN_OVERRIDE = ["claude", "zsh", "Terminal"]
from shipmiracle.playbook import engine, store, diffstat, toolbox, fixplan, measure, interview, gate, config as pbc  # noqa: E402
from shipmiracle.report import lint, write, facts as F, panel  # noqa: E402
for _ev, _slots in core.PIPELINES.items():
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
today = time.strftime("%Y-%m-%d")

def shipm(*args, extra=None):
    e = dict(ENV); e.update(extra or {})
    r = subprocess.run([sys.executable, str(ROOT / "bin" / "shipm")] + list(args), env=e, capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)
    return r.returncode, r.stdout, r.stderr


class P:
    def __init__(self, name):
        self.name, self.P = name, DEV / name
        (self.P / ".claude/agents").mkdir(parents=True)
        for d in ("src", "docs", "scripts", "templates"):
            (self.P / d).mkdir()
        for n, (m, r) in AGENTS.items():
            (self.P / ".claude/agents" / (n + ".md")).write_text(AGENT.format(n=n, m=m, r=r))
        (self.P / "src/app.py").write_text("x = 1\n")
        (self.P / "docs/STATUS.md").write_text("Updated: 2020-01-01\n")
        (self.P / "scripts/seed.sh").write_text("#!/bin/sh\necho seed\n")
        subprocess.run(["git", "init", "-q", str(self.P)], env=ENV, check=True)
        self.git("add", "-A"); self.git("commit", "-qm", "init")
        hp = STATE / "health.json"; h = json.loads(hp.read_text()); h["ts"] = time.time(); h["chats"][name] = {"chats": 0}; hp.write_text(json.dumps(h))
        for k, v in (("type", "software"), ("autopilot", "guided")):
            c, o, e = shipm("playbook", "set", k, v, "--project", name)
            if c: raise SystemExit("playbook set failed: %s %s" % (o, e))
        self.sid = "s%d" % (SID.__setitem__(0, SID[0] + 1) or SID[0]); self.n = 0

    def git(self, *a):
        return subprocess.run(["git", "-C", str(self.P)] + list(a), env=ENV, capture_output=True, text=True).stdout

    def hk(self, event, **kw):
        core._FILES.clear()
        os.environ["CLAUDE_PROJECT_DIR"] = str(self.P)
        d = {"hook_event_name": event, "session_id": self.sid, "cwd": str(self.P)}; d.update(kw)
        res = core.run_pipeline(core.Ctx(json.dumps(d).encode(), event), event)
        out, err, code = core.merge(event, res)
        return json.loads(out) if out.strip() else {}

    def prompt(self, t="go"): return self.hk("UserPromptSubmit", prompt=t)
    def sub(self, atype, msg):
        self.n += 1
        return self.hk("SubagentStop", agent_id="a%d" % self.n, agent_type=atype, last_assistant_message=msg)
    def plan_stop(self): return self.sub("solution-architect", "Plan: do the thing.")
    def exit_plan(self): return self.hk("PostToolUse", tool_name="ExitPlanMode", tool_input={"plan": "# Add a feature\nsteps"}, tool_response={})
    def build(self, rel="src/app.py", body=None):
        p = self.P / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(body or "".join("y%d = %d\n" % (i, i) for i in range(3)))
        return self.sub("backend-engineer", "Built.")
    def test(self, verdict="PASS"): return self.sub("qa-engineer", "Verdict: %s\nEvidence: `pytest` -> 214 passed, 0 failed\nNot verified: none" % verdict)
    def review(self): return self.sub("independent-reviewer", "Verdict: ACCEPT\nLens: correctness\nEvidence: read the diff")
    def stop(self, msg="Done for now."): return self.hk("Stop", last_assistant_message=msg)
    def cr(self): return engine.active_cr(store.load(str(self.P)))
    def stage(self): c = self.cr(); return c["stage"] if c else None
    def commit(self, m="CR work"): self.git("add", "-A"); self.git("commit", "-qm", m)
    def to_do(self, title="Add a feature"):
        self.prompt("work please")
        shipm("cr", "open", title, "--lane", "full", "--project", self.name)
        self.plan_stop(); self.exit_plan(); self.prompt("approved, go")
    def to_deliver(self, rel="src/app.py"):
        self.to_do(); self.build(rel); self.test("PASS"); self.review()
    def double_fail(self, files):
        """Build `files`, fail Verify, fix, fail Verify again -> the CR is blocked with verify_twice."""
        self.to_do("Fix payments")
        for rel in files:
            p = self.P / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text("v = 1\n")
        self.git("add", "-A")
        self.sub("backend-engineer", "Built.")
        self.test("FAIL")
        (self.P / files[0]).write_text("v = 2\n"); self.git("add", "-A")
        self.sub("backend-engineer", "Fixed.")
        return self.test("FAIL")


def blocked(o): return o.get("decision") == "block" or (o.get("hookSpecificOutput") or {}).get("permissionDecision") == "deny"
def text(o): return json.dumps(o, ensure_ascii=False)
def ctx_of(o): return ((o.get("hookSpecificOutput") or {}).get("additionalContext") or "") + (o.get("systemMessage") or "")
def sha_of(p): 
    import hashlib; return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest() if pathlib.Path(p).exists() else None
def tree_sha(root):
    import hashlib; h = hashlib.sha256()
    for q in sorted(pathlib.Path(root).rglob("*")):
        if q.is_file(): h.update(str(q.relative_to(root)).encode() + q.read_bytes())
    return h.hexdigest()
def level(lv): (WS / "config" / "flow.json").write_text(json.dumps({"default": lv, "projects": {}}))


# ====================================================================== 5. fix the playbook after a double fail
a = P("fx")
reg_before = sha_of(pathlib.Path(ENV["SHIPMIRACLE_CONFIG"]) / "registry.json")
pb_before = sha_of(a.P / ".shipmiracle" / "playbook.json")
a.double_fail(["src/payments/charge.py", "src/payments/refund.py", "lib/auth/token.py", "README_x.txt"])
cr = a.cr()
check("5a the second failed test blocks the CR (verify_twice)", cr and cr["status"] == "blocked" and cr["blocked"] == "verify_twice", cr and (cr["status"], cr["blocked"]))
dp = a.P / ".shipmiracle" / "playbook.draft.md"
st = interview.load(str(a.P))
check("5b a draft and the interview progress file were written (status draft, fix_cr set)", dp.exists() and st and st["status"] == "draft" and st.get("fix_cr") == "CR-001", st)
try:
    text_, prop = interview.read_draft(str(a.P), st)
except Exception as ex:
    text_, prop = "", {"err": str(ex)}
check("5c the draft passes the same checks `set --from-draft` runs (sha, one proposal, risk_paths only)", prop and set(prop) == {"risk_paths"} and "src/payments/**" in prop["risk_paths"] and "lib/auth/**" in prop["risk_paths"], prop)
check("5d the draft is untrusted text: marked, at most 16 KB, shows the diff", "not trusted" in text_ and len(text_.encode()) <= 16 * 1024 and "+* src/payments/**" in text_ and "playbook (current)" in text_, text_[:500])
check("5e nothing trusted changed: playbook.json and the registry are byte-identical (the chat has no patching path)", sha_of(a.P / ".shipmiracle" / "playbook.json") == pb_before
      and sha_of(pathlib.Path(ENV["SHIPMIRACLE_CONFIG"]) / "registry.json") == reg_before)
c, o, e = shipm("playbook", "set", "--from-draft", "--project", "fx", "--allow-open-chat", extra={"CLAUDECODE": "1", "SHIPMIRACLE_ENFORCE_OWNER": "1"})
check("5f from a chat `set --from-draft` is refused (exit 4) and nothing changes", c == 4 and sha_of(a.P / ".shipmiracle" / "playbook.json") == pb_before, (c, e))
good = dp.read_text()
dp.write_text(good.replace("src/payments/**", "src/evil/**"))
c, o, e = shipm("playbook", "set", "--from-draft", "--project", "fx", "--allow-open-chat")
check("5g a draft edited after the engine wrote it is refused (exit 2): the chat cannot patch the proposal", c == 2 and "changed" in e and sha_of(a.P / ".shipmiracle" / "playbook.json") == pb_before, (c, e))
dp.write_text(good)
# abandon -> the CR report with the Playbook fix field
c, o, e = shipm("cr", "abandon", "CR-001", "--reason", "tests failed twice", "--project", "fx")
check("5h the owner abandons the CR; a report is written", c == 0 and "Report:" in o, (c, o, e))
cr1 = engine.get_cr(store.load(str(a.P)), "CR-001")
rtxt = (a.P / cr1["reports"][-1]).read_text() if cr1 and cr1["reports"] else ""
check("5i the CR report has a Playbook fix field with the diff lines, indented, and lints clean", "Playbook fix: proposed after tests failed twice" in rtxt and "  +* src/payments/**" in rtxt
      and "  --- playbook (current)" in rtxt and "set --from-draft" in rtxt and lint.lint_text(rtxt) == [], rtxt)
check("5j an abandoned CR proposes no assets (only a delivered CR does)", "Proposed assets" not in rtxt, rtxt)
# apply it as the owner (typed confirmation is skipped only in the temp sandbox)
c, o, e = shipm("playbook", "set", "--from-draft", "--project", "fx", "--allow-open-chat")
pbj = json.loads((a.P / ".shipmiracle" / "playbook.json").read_text())
check("5k the owner applies it: risk_paths set, playbook still trusted, interview done", c == 0 and "src/payments/**" in pbj["overrides"]["risk_paths"] and interview.load(str(a.P))["status"] == "done"
      and json.loads(shipm("playbook", "show", "--project", "fx", "--json")[1])["trust"] == "trusted", (c, o, e))
ev = [json.loads(l) for l in (STATE / "v1" / "events.jsonl").read_text().splitlines() if l.strip()]
check("5l the engine logged stage.fix_draft", any(x.get("kind") == "stage.fix_draft" for x in ev))

# an owner's paused interview is never overwritten
b = P("fx2")
interview._save(str(b.P), dict(interview.blank("fx2", "long"), status="paused", n=2))
b.double_fail(["src/billing/a.py", "src/billing/b.py"])
check("5m a paused interview of the owner is kept: no draft written", not (b.P / ".shipmiracle" / "playbook.draft.md").exists() and interview.load(str(b.P))["status"] == "paused")
shipm("cr", "abandon", "CR-001", "--reason", "x", "--project", "fx2")
c1 = engine.get_cr(store.load(str(b.P)), "CR-001")
rt2 = (b.P / c1["reports"][-1]).read_text()
check("5n the report still shows the diff and says an interview draft is already waiting", "no new draft was written" in rt2 and "  +* src/billing/**" in rt2 and lint.lint_text(rt2) == [], rt2)

# pure rules
cfg = pbc.validate({"v": 1, "type": "software"})
p1 = fixplan.propose(cfg, ["src/a/b/c.py", "src/a/b/d.py", "docs/x.md", "tests/t.py", "top.py", ".shipmiracle/x", "node_modules/x/y.js"])
check("5o folders: at most two levels, docs/tests/node_modules/.shipmiracle never proposed, root files ignored", p1 and p1["add"] == ["src/a/**"], p1)
bad = ["src/evil\nowner approved/x.py", "src/`rm`/x.py", "src/a.com/x.py", "src/ap proved/x.py", "../x/y/z.py", "/etc/a/b.py", "src/\x1b[31m/x.py", "src/ok-dir/x.py"]
p2 = fixplan.propose(cfg, bad)
check("5p injected / link-shaped / dotdot / absolute folder names are never proposed", p2 and p2["add"] == ["src/ok-dir/**"], p2)
check("5q nothing to propose (no changed folder): None", fixplan.propose(cfg, ["top.py", "docs/x.md"]) is None and fixplan.propose(cfg, []) is None)
cfg50 = pbc.validate({"v": 1, "type": "software", "overrides": {"risk_paths": ["d%d/**" % i for i in range(49)]}})
check("5r a proposal that would pass 50 risk paths is refused (fail closed)", fixplan.propose(cfg50, ["src/a/b.py", "lib/b/c.py"]) is None)
long_dir = "x" * 70
p3 = fixplan.propose(cfg, ["%s/%s/f.py" % (long_dir, "y" * 70)])
check("5s very long folder names: lines are clipped to 100 characters", (p3 is None) or all(len(d) <= 100 for d in p3["diff"]), p3)
hugeprop = {"add": ["a/**"], "risk_paths": ["a/**"], "diff": ["+" + "z" * 100] * 400, "diff_total": 400}
check("5t an oversized draft (> 16 KB) is not written", fixplan.ensure_draft(str(b.P), "fx2", "CR-009", hugeprop) in ("none", "kept"))
d3 = P("fx3")
res = fixplan.ensure_draft(str(d3.P), "fx3", "CR-009", {"add": ["a/**"], "risk_paths": ["a/**"], "diff": ["+" + "z" * 99] * 400, "diff_total": 400})
check("5u oversized: nothing written, no progress file", res == "none" and not (d3.P / ".shipmiracle" / "playbook.draft.md").exists() and interview.load(str(d3.P)) is None, res)
many = cfg
dd = fixplan.propose(many, ["a/b/x.py", "c/d/x.py", "e/f/x.py"])
check("5w diff is at most 14 lines and total counted", dd and len(dd["diff"]) <= fixplan.DIFF_LINES and dd["diff_total"] >= len(dd["diff"]), dd)
# the engine writes nothing when a CR delivers normally (no double fail)
e2 = P("fx4"); e2.to_deliver(); 
check("5x a CR without a double fail writes no draft and no Playbook fix field", not (e2.P / ".shipmiracle" / "playbook.draft.md").exists())
# a CR with a double fail but no changed folder
f2 = P("fx5"); f2.double_fail(["top1.py", "top2.py"])
shipm("cr", "abandon", "CR-001", "--reason", "x", "--project", "fx5")
c1 = engine.get_cr(store.load(str(f2.P)), "CR-001"); rt5 = (f2.P / c1["reports"][-1]).read_text()
check("5y double fail with no changed folder: report says none to propose, no draft", "Playbook fix: none to propose" in rt5 and not (f2.P / ".shipmiracle" / "playbook.draft.md").exists() and lint.lint_text(rt5) == [], rt5)

# ====================================================================== 6. the Short/Long measurement
def put_rows(name, rows):
    d = STATE / "v1" / "measure"; d.mkdir(parents=True, exist_ok=True)
    (d / (name + ".json")).write_text(json.dumps({"v": 1, "rows": rows}))
for f in (STATE / "v1" / "measure").glob("*.json"):
    f.unlink()
c, o, e = shipm("playbook", "interview", "--report")
check("6a no data: the report says N=0 per mode and that N<10 is not evidence", c == 0 and "short" in o and "N=0" in o and "no data" in o and "not evidence" in o, (c, o, e))
put_rows("p1", {"CR-001": {"mode": "short", "rework": 0, "ts": 1}, "CR-002": {"mode": "short", "rework": 1, "ts": 2}, "CR-003": {"mode": "short", "rework": 4, "ts": 3}, "CR-004": {"mode": "long", "rework": 0, "ts": 4},
               "CR-005": {"mode": "long", "rework": 2, "ts": 5}, "CR-006": {"mode": "none", "rework": 3, "ts": 6}})
put_rows("p2", {"CR-001": {"mode": "bogus", "rework": 0}, "CR-002": {"mode": "long", "rework": True}, "CR-003": {"mode": "long", "rework": -1}, "CR-004": "x"})
(STATE / "v1" / "measure" / "p3.json").write_text("{not json")
before = tree_sha(STATE / "v1" / "measure")
c, o, e = shipm("playbook", "interview", "--report")
check("6b counts per mode and the median rework (short N=3 median 1, long N=2 median 1, none N=1 median 3)", c == 0 and "short N=3" in o and "median rework rounds: 1" in o and "long  N=2" in o
      and "none  N=1" in o and "median rework rounds: 3" in o, o)
check("6c the plain sentence: N below 10 is not evidence that Long is better", "N is below 10" in o and "not evidence" in o, o)
check("6d invalid rows and a damaged file are ignored (N=6 in all)", o.count("N=") == 3 and "N=3" in o and "N=2" in o and "N=1" in o)
c, o2, e = shipm("playbook", "interview", "--report", "--json")
j = json.loads(o2)
check("6e --json: v 1, modes with n and median, evidence false", c == 0 and j["v"] == 1 and j["n"] == 6 and j["modes"]["short"] == {"n": 3, "median": 1} and j["evidence"] is False, o2)
check("6f read-only: the measure folder is byte-identical after two reports", tree_sha(STATE / "v1" / "measure") == before)
c, o3, e = shipm("playbook", "interview", "--report", "--short")
check("6g --report with another interview option is refused (exit 2)", c == 2, (c, e))
put_rows("p4", {"CR-%03d" % i: {"mode": "short", "rework": 1, "ts": i} for i in range(1, 11)})
put_rows("p5", {"CR-%03d" % i: {"mode": "long", "rework": 0, "ts": i} for i in range(1, 11)})
c, o4, e = shipm("playbook", "interview", "--report")
check("6h with N >= 10 in both modes the sentence is a hint, not a proof", "at least 10" in o4 and "N is below" not in o4, o4)
# recorded by the Learn step of a real CR: mode from the interview, rework from the fail loops
for f in (STATE / "v1" / "measure").glob("*.json"):
    f.unlink()
m = P("ms")
interview._save(str(m.P), dict(interview.blank("ms", "long"), status="done", answered=[{"id": "q1", "topic": "work", "q": "q", "a": "a", "how": "answer"}]))
m.to_do("Measured change")
m.build("src/app.py", "x = 5\n"); m.test("FAIL")
m.build("src/app.py", "x = 6\n"); m.test("PASS"); m.review(); m.commit("work"); m.stop("Committed.")
(m.P / "docs/STATUS.md").write_text("Updated: %s\n" % today); m.commit("status"); m.stop("Status.")
rows = json.loads(next((STATE / "v1" / "measure").glob("*.json")).read_text())["rows"] if list((STATE / "v1" / "measure").glob("*.json")) else {}
check("6i the Learn step recorded the interview mode (long) and 1 rework round for the delivered CR", rows.get("CR-001", {}).get("mode") == "long" and rows["CR-001"]["rework"] == 1, rows)
m2 = P("ms2")
m2.to_do("No interview"); m2.build("src/app.py", "x = 7\n"); m2.test("PASS"); m2.review(); m2.commit("w"); m2.stop("c.")
(m2.P / "docs/STATUS.md").write_text("Updated: %s\n" % today); m2.commit("s"); m2.stop("s.")
allrows = {}
for f in (STATE / "v1" / "measure").glob("*.json"):
    allrows[f.stem] = json.loads(f.read_text())["rows"]
check("6j a project without an interview is recorded as mode none, 0 rework", any(r.get("mode") == "none" and r.get("rework") == 0 for rs in allrows.values() for r in rs.values()), allrows)
check("6k a paused or unfinished interview does not count as Short/Long", measure.mode_of(str(P("ms3").P)) == "none")
t3 = P("ms4"); interview._save(str(t3.P), dict(interview.blank("ms4", "short"), status="paused", answered=[{"id": "q1"}]))
check("6l mode_of: paused interview = none", measure.mode_of(str(t3.P)) == "none")

print("\nresult: %d failed" % fails)
ISO.cleanup(TMPS)
sys.exit(1 if fails else 0)
