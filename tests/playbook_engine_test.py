#!/usr/bin/env python3
"""shipmiracle/playbook/engine.py (pure) and store.py (the authority log): every exit rule positive and refused, lanes, promotion, delta resets, queue
and WIP, verify FAIL/FAIL, owner-only unblock, hand-backs, REMEDIATE, review lenses, can_stop, next_action, brief, render; then the log:
concurrent appends, replay == engine state, forged work.json, import, compaction, corrupt lines, permissions, isolation, timing.
Temp dirs + SHIPMIRACLE_TEST=1 only. Run: python3 tests/playbook_engine_test.py"""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import shipmiracle_isolation; shipmiracle_isolation.apply_to_environ()   # test isolation: fresh HOME/SHIPMIRACLE_HOME/CONFIG/STATE unless already temp
import copy, json, os, pathlib, stat, subprocess, sys, tempfile, time

ROOT = pathlib.Path(__file__).resolve().parent.parent
TMP = pathlib.Path(os.environ.get("SHIPMIRACLE_PB_TMP") or tempfile.mkdtemp()).resolve()      # workers inherit the parent's temp dir
os.environ.update(SHIPMIRACLE_PB_TMP=str(TMP), SHIPMIRACLE_TEST="1", SHIPMIRACLE_HOME=str(TMP / "home"), SHIPMIRACLE_STATE=str(TMP / "state"), SHIPMIRACLE_CONFIG=str(TMP / "config"),
                  SHIPMIRACLE_DEV=str(TMP / "dev"), SHIPMIRACLE_WS=str(TMP / "ws"), TZ="UTC")
time.tzset()
sys.path.insert(0, str(ROOT))
from shipmiracle import SafetyError, UsageError, events, paths, state  # noqa: E402
from shipmiracle.playbook import config, engine, gate, store, types  # noqa: E402
from shipmiracle.playbook.engine import EngineRefused  # noqa: E402

fails = 0
def check(name, ok, info=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(info)))
    fails += 0 if ok else 1

def code(fn, *a, **k):
    """The EngineRefused code of fn(...) or None when it did not refuse."""
    try:
        fn(*a, **k)
    except EngineRefused as e:
        return e.code
    return None

def raises(exc, fn, *a, **k):
    try:
        fn(*a, **k)
    except exc:
        return True
    except Exception as e:
        return "wrong exception %r" % e
    return False

def mode(p):
    return stat.S_IMODE(os.lstat(p).st_mode)

SHA = "ab" * 32
BASE = "c" * 40
def mk_rules(t="software", autopilot="guided", level="strict", **ov):
    cfg = config.validate({"v": 1, "type": t, "autopilot": autopilot, "level": level, "overrides": ov})
    return gate.build_rules("/x/Proj", cfg, "trusted", "", level)
RULES_S = mk_rules()

if len(sys.argv) > 1 and sys.argv[1] == "worker":           # child: appends or opens CRs through the store
    kind, project, n, wid = sys.argv[2], sys.argv[3], int(sys.argv[4]), sys.argv[5]
    bad = 0
    for i in range(n):
        try:
            if kind == "append":
                store.append(project, [{"ts": 1760000000 + i, "cr": "CR-001", "op": "report", "stage": None, "by": wid, "sid8": None,
                                        "ev": {"kind": "engine", "ref": None, "data": {"path": "r-%s-%d" % (wid, i), "pad": "x" * 300}}}])
            else:
                store.transact(project, lambda w: (lambda cr_trs: (cr_trs[0]["id"], cr_trs[1]))(
                    engine.open_cr(w, "w%s-%d" % (wid, i), "t", int(time.time()), rules=RULES_S)))
        except Exception as e:
            bad += 1; print("worker error", repr(e), file=sys.stderr)
    sys.exit(1 if bad else 0)


class Sim:
    """Drives the engine like the stage module would and keeps every transition for the replay check."""
    def __init__(self, rules, ts=1760000000):
        self.w = engine.new_work(); self.w["project"] = "Proj"; self.r = rules; self.t = ts; self.trs = []
    def tick(self, n=60):
        self.t += n; return self.t
    def ev(self, kind, by=None, **data):
        return {"kind": kind, "data": data, "by": by or data.get("role") or "x", "ts": self.tick()}
    def rec(self, trs):
        self.trs += trs; return trs
    def open(self, title="RTL fix on login", lane=None, **k):
        cr, trs = engine.open_cr(self.w, title, "owner", self.tick(), lane=lane, base=BASE, rules=self.r, **k)
        self.rec(trs); return cr
    def adv(self, cr, stage, kind, by=None, **data):
        return self.rec(engine.advance(self.w, cr["id"], stage, self.ev(kind, by, **data), self.r))
    def scope(self, cr): return self.adv(cr, "scope", "role_stop", "scoper", role="scope")
    def plan(self, cr): return self.adv(cr, "plan", "plan_presented", "planner", plan_sha=SHA, role_ts=self.t)
    def approve(self, cr): return self.adv(cr, "approve", "owner_prompt", "owner", owner_words=True)
    def build(self, cr, files=2, lines=20, **d): return self.adv(cr, "do", "role_stop", "builder", role="build", diff=dict({"files": files, "lines": lines, "risk": [], "deps": False}, **d))
    def passed(self, cr): return self.adv(cr, "verify", "qa_pass", "verifier", counts="214/214")
    def failed(self, cr): return self.rec(engine.fail(self.w, cr["id"], "verify", self.ev("qa_fail", "verifier", counts="212/214"), self.r))
    def review(self, cr, lens="correctness", verdict="ACCEPT"): return self.adv(cr, "review", "review_verdict", "reviewer", lens=lens, verdict=verdict)
    def deliver(self, cr): return self.adv(cr, "deliver", "git_delivered", "lead")
    def learn(self, cr):
        self.adv(cr, "learn", "status_dated", "lead"); return self.adv(cr, "learn", "report_written", "lead")
    def to_plan_done(self, cr): self.scope(cr); self.plan(cr)
    def to_build_done(self, cr, **k): self.plan(cr); self.approve(cr); self.build(cr, **k)
    def replay_equal(self):
        w2, skipped = store.replay([json.loads(engine.dumps_line(t)) for t in self.trs], "Proj")
        a, b = copy.deepcopy(self.w), copy.deepcopy(w2)
        return a == b and skipped == 0

def stg(cr): return dict(cr["stages"])

# ===== open, lanes, queue =====================================================================================
s = Sim(mk_rules())
c1 = s.open("  RTL fix\x00 on\x1b login\n  ")
check("open: first CR is active, id CR-001, title cleaned", c1["id"] == "CR-001" and s.w["active"] == "CR-001" and c1["status"] == "open" and c1["title"] == "RTL fix on login", c1)
check("open: default lane fast (software); scope plan approve review skipped; stage do", c1["lane"] == "fast" and stg(c1)["scope"] == "skipped" and stg(c1)["plan"] == "skipped"
      and stg(c1)["approve"] == "skipped" and stg(c1)["review"] == "skipped" and c1["stage"] == "do", stg(c1))
c2 = s.open("second")
check("open: second CR queued (WIP = 1) with its own id", c2["id"] == "CR-002" and c2["status"] == "queued" and s.w["queue"] == ["CR-002"] and s.w["active"] == "CR-001")
c3 = s.open("full please", lane="full")
check("open: explicit full lane has every stage next, stage scope", c3["lane"] == "full" and set(stg(c3).values()) == {"next"} and c3["stage"] == "scope")
check("open refused: empty / control-only title", code(engine.open_cr, s.w, " \x00 ", "o", 1, rules=s.r) == "bad_title" and code(engine.open_cr, s.w, 5, "o", 1, rules=s.r) == "bad_title")
check("open: title cut at 120 characters", len(engine.open_cr(copy.deepcopy(s.w), "x" * 300, "o", 1, rules=s.r)[0]["title"]) == 120)
check("open refused: bad lane / bad base", code(engine.open_cr, s.w, "t", "o", 1, lane="slow", rules=s.r) == "bad_lane" and code(engine.open_cr, s.w, "t", "o", 1, base="zz", rules=s.r) == "bad_base")
check("open refused: evidence kind must be cli_open/auto_open", code(engine.open_cr, s.w, "t", "o", 1, rules=s.r, kind="qa_pass") == "bad_evidence")
sq = Sim(mk_rules()); sq.open("a")
for i in range(12):
    sq.open("q%d" % i)
check("queue holds 12, the 13th is refused", len(sq.w["queue"]) == 12 and code(engine.open_cr, sq.w, "x", "o", 1, rules=sq.r) == "queue_full")
check("auto_open is accepted", engine.open_cr(engine.new_work(), "t", "hook", 5, rules=s.r, kind="auto_open")[1][0]["ev"]["kind"] == "auto_open")
so = Sim(mk_rules("ops")); co = so.open("rotate keys")
check("ops: default lane full", co["lane"] == "full" and co["stage"] == "scope")
check("ops: explicit fast refused", code(engine.open_cr, so.w, "t", "o", 1, lane="fast", rules=so.r) == "fast_not_allowed")
check("ops: evaluate_diff never eligible (type_no_fast)", engine.evaluate_diff({"files": 1, "lines": 1}, so.r) == {"eligible": False, "why": ["type_no_fast"]})
check("ops: a tiny diff can not stay fast (observe_diff on a full CR is a plain record)", so.rec(engine.observe_diff(so.w, co["id"], {"files": 1, "lines": 1}, so.ev("diff_eval"), so.r))[0]["op"] == "diff" and co["lane"] == "full")
check("replay of the open sequences equals the engine state", s.replay_equal() and so.replay_equal())

# ===== full lane, every exit rule =============================================================================
s = Sim(mk_rules()); cr = s.open("feature", lane="full")
check("exit scope: wrong evidence kind", code(engine.advance, s.w, cr["id"], "scope", s.ev("qa_pass"), s.r) == "wrong_evidence")
check("exit scope: wrong role in role_stop", code(engine.advance, s.w, cr["id"], "scope", s.ev("role_stop", role="build"), s.r) == "wrong_evidence")
check("exit scope: ts before the CR opened", code(engine.advance, s.w, cr["id"], "scope", {"kind": "role_stop", "data": {"role": "scope"}, "ts": cr["opened"] - 1}, s.r) == "wrong_evidence")
check("order: approve before plan refused", code(engine.advance, s.w, cr["id"], "approve", s.ev("owner_prompt", owner_words=True), s.r) == "order")
check("order: build before plan refused", code(engine.advance, s.w, cr["id"], "do", s.ev("role_stop", role="build", diff={"files": 1}), s.r) == "order")
check("order: verify / review / deliver / learn before their turn refused", all(code(engine.advance, s.w, cr["id"], st, s.ev(k, lens="correctness", verdict="ACCEPT"), s.r) == "order"
      for st, k in (("verify", "qa_pass"), ("review", "review_verdict"), ("deliver", "git_delivered"), ("learn", "status_dated"))))
check("unknown stage / intake refused", code(engine.advance, s.w, cr["id"], "nope", s.ev("role_stop"), s.r) == "bad_stage" and code(engine.advance, s.w, cr["id"], "intake", s.ev("cli_open"), s.r) == "bad_stage")
check("unknown evidence kind refused", code(engine.advance, s.w, cr["id"], "scope", {"kind": "magic", "data": {}}, s.r) == "bad_evidence" and code(engine.advance, s.w, cr["id"], "scope", "x", s.r) == "bad_evidence")
trs = s.scope(cr)
check("exit scope: done by scoper, stage plan", stg(cr)["scope"] == "done:scoper" and cr["stage"] == "plan" and trs[0]["op"] == "advance", stg(cr))
check("exit plan: bad sha / missing role_ts / role stop before the CR refused", code(engine.advance, s.w, cr["id"], "plan", s.ev("plan_presented", plan_sha="xyz", role_ts=s.t), s.r) == "wrong_evidence"
      and code(engine.advance, s.w, cr["id"], "plan", s.ev("plan_presented", plan_sha=SHA), s.r) == "wrong_evidence"
      and code(engine.advance, s.w, cr["id"], "plan", s.ev("plan_presented", plan_sha=SHA, role_ts=cr["opened"] - 5), s.r) == "wrong_evidence")
check("exit plan: owner words are not a plan", code(engine.advance, s.w, cr["id"], "plan", s.ev("owner_prompt", owner_words=True), s.r) == "wrong_evidence")
s.plan(cr)
check("exit plan: done by planner, plan_sha stored, stage approve", stg(cr)["plan"] == "done:planner" and cr["plan_sha"] == SHA and cr["stage"] == "approve")
check("approve: hand-back evidence kind refused", code(engine.advance, s.w, cr["id"], "approve", s.ev("hand_back", owner_words=True), s.r) == "wrong_evidence")
check("approve: owner_prompt flagged hand_back refused", code(engine.advance, s.w, cr["id"], "approve", s.ev("owner_prompt", owner_words=True, hand_back=True), s.r) == "owner_required")
check("approve: owner_prompt without owner_words (not an approval) refused", code(engine.advance, s.w, cr["id"], "approve", s.ev("owner_prompt"), s.r) == "owner_required"
      and code(engine.advance, s.w, cr["id"], "approve", s.ev("owner_prompt", owner_words=False), s.r) == "owner_required")
check("approve: a different plan sha refused", code(engine.advance, s.w, cr["id"], "approve", s.ev("owner_prompt", owner_words=True, plan_sha="cd" * 32), s.r) == "plan_changed")
check("approve: wrong evidence (qa_pass) refused", code(engine.advance, s.w, cr["id"], "approve", s.ev("qa_pass"), s.r) == "wrong_evidence")
check("nothing was recorded by the refused approvals", stg(cr)["approve"] == "next" and cr["stage"] == "approve")
trs = s.rec(engine.advance(s.w, cr["id"], "approve", s.ev("owner_prompt", "owner", owner_words=True, plan_sha=SHA), s.r))
check("approve: owner words + same plan sha -> done by owner; the line carries plan_sha (cr.approved)", stg(cr)["approve"] == "done:owner" and trs[0]["ev"]["data"]["plan_sha"] == SHA and cr["stage"] == "do")
check("do: non-build role refused / no changed file refused", code(engine.advance, s.w, cr["id"], "do", s.ev("role_stop", role="test", diff={"files": 1}), s.r) == "wrong_evidence"
      and code(engine.advance, s.w, cr["id"], "do", s.ev("role_stop", role="build", diff={"files": 0, "lines": 0}), s.r) == "no_changes"
      and code(engine.advance, s.w, cr["id"], "do", s.ev("role_stop", role="build"), s.r) == "no_changes")
s.build(cr, files=2, lines=20, risk=["src/auth/x.py"])
check("do: done, diff recorded (risk hit), stage verify, verified False", stg(cr)["do"] == "done:builder" and cr["diff"]["files"] == 2 and cr["diff"]["risk"] == ["src/auth/x.py"]
      and cr["stage"] == "verify" and cr["verified"] is False)
check("verify: review before verify refused", code(engine.advance, s.w, cr["id"], "review", s.ev("review_verdict", lens="correctness", verdict="ACCEPT"), s.r) == "order")
check("verify: wrong evidence (qa_fail via advance / role_stop) refused", code(engine.advance, s.w, cr["id"], "verify", s.ev("qa_fail"), s.r) == "wrong_evidence"
      and code(engine.advance, s.w, cr["id"], "verify", s.ev("role_stop", role="test"), s.r) == "wrong_evidence")
check("fail(): stage must be verify and evidence qa_fail", code(engine.fail, s.w, cr["id"], "do", s.ev("qa_fail"), s.r) == "wrong_evidence" and code(engine.fail, s.w, cr["id"], "verify", s.ev("qa_pass"), s.r) == "wrong_evidence")
s.passed(cr)
check("verify PASS: done, verified, stage review, last verdict kept", stg(cr)["verify"] == "done:verifier" and cr["verified"] and cr["stage"] == "review" and cr["verdict"]["word"] == "PASS")
check("required lenses: correctness + risk (risk path hit)", engine.required_lenses(cr, s.r) == ["correctness", "risk"])
check("review: unknown lens / bad verdicts / BLOCKED refused", code(engine.advance, s.w, cr["id"], "review", s.ev("review_verdict", lens="style", verdict="ACCEPT"), s.r) == "bad_lens"
      and code(engine.advance, s.w, cr["id"], "review", s.ev("review_verdict", lens="correctness", verdict="MAYBE"), s.r) == "bad_verdict"
      and code(engine.advance, s.w, cr["id"], "review", s.ev("review_verdict", lens="correctness", verdict="BLOCKED"), s.r) == "bad_verdict"
      and code(engine.advance, s.w, cr["id"], "review", s.ev("review_verdict", lens="correctness", verdict="PASS"), s.r) == "bad_verdict")
check("review: wrong evidence kind refused", code(engine.advance, s.w, cr["id"], "review", s.ev("qa_pass"), s.r) == "wrong_evidence")
s.review(cr, "correctness", "ACCEPT")
check("review: one lens of two recorded, review not complete", cr["lenses"]["correctness"] == "ACCEPT" and cr["stage"] == "review" and stg(cr)["review"] == "next")
check("can_stop: cr_review_missing while a required lens is missing", [r.kind for r in engine.can_stop(s.w, s.r)] == ["cr_review_missing"] and "risk" in engine.can_stop(s.w, s.r)[0].msg)
s.review(cr, "risk", "ACCEPT WITH FIXES")
check("review: both lenses accepted (ACCEPT WITH FIXES counts) -> done, stage deliver", stg(cr)["review"] == "done:reviewer" and cr["stage"] == "deliver")
check("deliver: wrong evidence refused; learn before deliver refused", code(engine.advance, s.w, cr["id"], "deliver", s.ev("status_dated"), s.r) == "wrong_evidence"
      and code(engine.advance, s.w, cr["id"], "learn", s.ev("status_dated"), s.r) == "order")
s.deliver(cr)
check("deliver: git_delivered -> stage learn", stg(cr)["deliver"] == "done:lead" and cr["stage"] == "learn")
check("learn: wrong evidence refused", code(engine.advance, s.w, cr["id"], "learn", s.ev("git_delivered"), s.r) == "wrong_evidence")
s.adv(cr, "learn", "status_dated", "lead")
check("learn: status_dated alone does not finish the CR", cr["status"] == "open" and cr["stage"] == "learn" and s.w["active"] == cr["id"])
trs = s.adv(cr, "learn", "report_written", "lead")
check("learn: report_written completes it -> delivered, no active CR", cr["status"] == "delivered" and s.w["active"] is None and cr["stage"] == "done" and [t["op"] for t in trs] == ["advance", "deliver"])
check("closed CR refuses everything", code(engine.advance, s.w, cr["id"], "learn", s.ev("report_written"), s.r) == "closed" and code(engine.block, s.w, cr["id"], "x", s.ev("engine")) == "closed")
check("full lane replay == engine state", s.replay_equal())
check("every log line <= 1 KB", all(len(engine.dumps_line(t).encode()) <= 1024 for t in s.trs), max(len(engine.dumps_line(t)) for t in s.trs))
sl2 = Sim(mk_rules()); cl2 = sl2.open("x"); sl2.build(cl2); sl2.passed(cl2); sl2.deliver(cl2); sl2.adv(cl2, "learn", "report_written", "lead"); sl2.adv(cl2, "learn", "status_dated", "lead")
check("learn works in the other order too (report first)", cl2["status"] == "delivered")
check("learn: the same evidence twice does not complete it", (lambda s3, c3x: (s3.build(c3x), s3.passed(c3x), s3.deliver(c3x), s3.adv(c3x, "learn", "status_dated"), s3.adv(c3x, "learn", "status_dated"), c3x["status"])[-1])(
      *(lambda s3: (s3, s3.open("y")))(Sim(mk_rules()))) == "open")

# ===== scope optional =====================================================================================
s = Sim(mk_rules()); cr = s.open("x", lane="full")
s.plan(cr)
check("scope is optional: plan while scope is next marks scope skipped", stg(cr)["scope"] == "skipped" and stg(cr)["plan"] == "done:planner" and cr["stage"] == "approve")
check("scope after plan refused (order)", code(engine.advance, s.w, cr["id"], "scope", s.ev("role_stop", role="scope"), s.r) == "order")

# ===== fast lane ===================================================================================================
s = Sim(mk_rules()); cr = s.open("tiny")
check("fast lane: approve/plan evidence refused (they are skipped)", code(engine.advance, s.w, cr["id"], "approve", s.ev("owner_prompt", owner_words=True), s.r) == "order")
s.build(cr, files=3, lines=50)
check("fast lane: build at exactly 3 files / 50 lines stays fast", cr["lane"] == "fast" and cr["stage"] == "verify")
check("fast lane: observe_diff at the limits does not promote", s.rec(engine.observe_diff(s.w, cr["id"], {"files": 3, "lines": 50, "risk": [], "deps": False}, s.ev("diff_eval"), s.r)) == [] and cr["lane"] == "fast")
s.passed(cr)
check("fast lane: verify PASS skips review, stage deliver", stg(cr)["review"] == "skipped" and cr["stage"] == "deliver")
check("fast lane: can_stop has nothing to say", engine.can_stop(s.w, s.r) == [])
s.deliver(cr); s.learn(cr)
check("fast lane: delivered after build, test, release, learn", cr["status"] == "delivered" and s.replay_equal())

# ===== promotion edge cases =======================================================================================
def promo(diff, rules=None, t="software"):
    sp = Sim(rules or mk_rules(t)); c = sp.open("p")
    trs = sp.rec(engine.observe_diff(sp.w, c["id"], diff, sp.ev("diff_eval"), sp.r))
    return sp, c, trs
base_d = {"files": 1, "lines": 1, "risk": [], "deps": False}
for name, d, why in (("4 files", dict(base_d, files=4), "files>3"), ("51 lines", dict(base_d, lines=51), "lines>50"), ("risk path hit", dict(base_d, risk=["a/auth/x.py"]), "risk_path"),
                     ("dep file", dict(base_d, deps=True), "dep_file"), ("submodule", dict(base_d, submodule=True), "submodule")):
    sp, c, trs = promo(d)
    check("promotion: %s -> full, plan+approve next, stage plan, why=%s" % (name, why), c["lane"] == "full" and stg(c)["plan"] == "next" and stg(c)["approve"] == "next"
          and c["stage"] == "plan" and stg(c)["review"] == "next" and why in engine.evaluate_diff(d, sp.r)["why"] and [t["op"] for t in trs] == ["lane"], (stg(c), trs))
    check("promotion: %s replay equal" % name, sp.replay_equal())
for name, d in (("1 file 1 line", base_d), ("3 files 50 lines (limits)", dict(base_d, files=3, lines=50)), ("0 files", dict(base_d, files=0, lines=0))):
    sp, c, trs = promo(d)
    check("no promotion: %s" % name, c["lane"] == "fast" and engine.evaluate_diff(d, sp.r)["eligible"])
sp, c, trs = promo(dict(base_d, files=4))
check("promotion is one way: a second promote is a no-op and a small diff never demotes", engine.promote(sp.w, c["id"], base_d, sp.ev("diff_eval")) == [] and
      sp.rec(engine.observe_diff(sp.w, c["id"], base_d, sp.ev("diff_eval"), sp.r))[0]["op"] == "diff" and c["lane"] == "full")
check("promoted CR: plan is required before building (order refused)", code(engine.advance, sp.w, c["id"], "do", sp.ev("role_stop", role="build", diff={"files": 1}), sp.r) == "order")
check("evaluate_diff reports every reason", engine.evaluate_diff({"files": 9, "lines": 999, "risk": ["x"], "deps": True, "submodule": True}, RULES_S)["why"] ==
      ["files>3", "lines>50", "risk_path", "dep_file", "submodule"])
# content / research / notes limits
rc = mk_rules("content")
check("content limit 3 files / 150 lines: 150 eligible, 151 not", engine.evaluate_diff({"files": 3, "lines": 150}, rc)["eligible"] and not engine.evaluate_diff({"files": 3, "lines": 151}, rc)["eligible"])
rr = mk_rules("research")
check("research limit 200 lines: 200 eligible, 201 not", engine.evaluate_diff({"files": 1, "lines": 200}, rr)["eligible"] and not engine.evaluate_diff({"files": 1, "lines": 201}, rr)["eligible"])
rn = mk_rules("notes")
check("notes: 5 files with any number of lines eligible, 6 files not", engine.evaluate_diff({"files": 5, "lines": 100000}, rn)["eligible"] and engine.evaluate_diff({"files": 5, "lines": 100000}, rn)["why"] == []
      and engine.evaluate_diff({"files": 6, "lines": 1}, rn)["why"] == ["files>5"])
check("notes: no review lens even in the full lane (verify PASS skips review)", (lambda sn: (sn.passed(sn.w["crs"][0]) or True) and stg(sn.w["crs"][0])["review"] == "skipped")(
      (lambda sn: (sn.open("n", lane="full"), sn.scope(sn.w["crs"][0]), sn.to_build_done(sn.w["crs"][0]), sn)[-1])(Sim(rn))))
ro = mk_rules("app")
c_app = Sim(ro).open("ui", lane="full")
sa = Sim(ro); ca = sa.open("ui", lane="full"); sa.plan(ca); sa.approve(ca); sa.build(ca, ui=True); sa.passed(ca)
check("app: ui_paths hit in a full lane requires the design lens", engine.required_lenses(ca, ro) == ["correctness", "design"])
sa.review(ca, "correctness"); check("app: design lens missing keeps review open", ca["stage"] == "review")
check("design lens: only PASS finishes; ACCEPT is refused", code(engine.advance, sa.w, ca["id"], "review", sa.ev("review_verdict", lens="design", verdict="ACCEPT"), sa.r) == "bad_verdict")
sa.review(ca, "design", "PASS"); check("app: designer PASS completes review", ca["stage"] == "deliver")
check("software: ui flag does not add a design lens", engine.required_lenses(dict(ca, diff=dict(ca["diff"], ui=True)), RULES_S) == ["correctness"])

# ===== REMEDIATE, rebuild, ACCEPT WITH FIXES ===================================================================
s = Sim(mk_rules()); cr = s.open("r", lane="full"); s.to_build_done(cr); s.passed(cr)
trs = s.review(cr, "correctness", "REMEDIATE")
check("REMEDIATE resets build, test and review; stage do; lenses cleared; fails 0", stg(cr)["do"] == "next" and stg(cr)["verify"] == "next" and stg(cr)["review"] == "next" and cr["stage"] == "do"
      and cr["verify_fails"] == 0 and not any(cr["lenses"].values()) and cr["verified"] is False and stg(cr)["approve"].startswith("done") and stg(cr)["plan"].startswith("done"), stg(cr))
check("REMEDIATE: plan and approval are kept (no new OK needed)", cr["plan_sha"] == SHA)
s.build(cr); check("after REMEDIATE a build moves to verify", cr["stage"] == "verify")
s.passed(cr); s.review(cr, "correctness", "ACCEPT WITH FIXES")
check("ACCEPT WITH FIXES completes review (correctness only, no risk hit)", cr["stage"] == "deliver" and stg(cr)["review"].startswith("done"))
s.build(cr, files=1, lines=3)
check("ACCEPT WITH FIXES: the fixing build reopens verify (re-verify), review stays done", cr["stage"] == "verify" and stg(cr)["verify"] == "next" and stg(cr)["review"].startswith("done") and not cr["verified"])
check("re-verify required: deliver refused until PASS", code(engine.advance, s.w, cr["id"], "deliver", s.ev("git_delivered"), s.r) == "order")
s.passed(cr)
check("re-verify PASS goes straight to deliver", cr["stage"] == "deliver" and cr["verified"] and s.replay_equal())
s2 = Sim(ro); c2_ = s2.open("d", lane="full"); s2.plan(c2_); s2.approve(c2_); s2.build(c2_, ui=True); s2.passed(c2_); s2.review(c2_, "correctness")
s2.review(c2_, "design", "FAIL")
check("designer FAIL resets like REMEDIATE", c2_["stage"] == "do" and stg(c2_)["verify"] == "next")
sr = Sim(mk_rules()); cr_ = sr.open("rv", lane="full"); sr.to_build_done(cr_)
check("review before a passing test refused (verify_missing)", code(engine.advance, sr.w, cr_["id"], "review", sr.ev("review_verdict", lens="correctness", verdict="ACCEPT"), sr.r) == "order")

# ===== post-review delta ==========================================================================================
s = Sim(mk_rules()); cr = s.open("pr", lane="full"); s.to_build_done(cr); s.passed(cr); s.review(cr)
check("post-review delta within the limits: nothing", engine.post_review_delta(s.w, cr["id"], {"files": 3, "lines": 50}, s.ev("diff_eval"), s.r) == [])
trs = s.rec(engine.post_review_delta(s.w, cr["id"], {"files": 1, "lines": 51}, s.ev("diff_eval"), s.r))
check("post-review delta over the limit resets review (lenses cleared, stage review)", [t["op"] for t in trs] == ["reset"] and stg(cr)["review"] == "next" and cr["stage"] == "review"
      and not any(cr["lenses"].values()) and cr["verified"] and s.replay_equal(), stg(cr))
s.review(cr); check("review can be redone after the reset", cr["stage"] == "deliver")
sn_ = Sim(mk_rules()); cn = sn_.open("nr", lane="full"); sn_.to_build_done(cn); sn_.passed(cn)
check("post-review delta with no review yet is a no-op", engine.post_review_delta(sn_.w, cn["id"], {"files": 9, "lines": 999}, sn_.ev("diff_eval"), sn_.r) == [])

# ===== delta reset, queue, WIP =======================================================================================
s = Sim(mk_rules()); a = s.open("first", lane="full"); b = s.open("second"); s.to_build_done(a)
check("queued CR can not advance (not_active)", code(engine.advance, s.w, b["id"], "do", s.ev("role_stop", role="build", diff={"files": 1}), s.r) == "not_active")
check("start refused while another CR is active (WIP)", code(engine.start, s.w, b["id"], s.ev("cli_start"), s.r) == "wip")
check("delta: source must be queued and different", code(engine.reset_after_delta, s.w, a["id"], "plan", a["id"], s.ev("cli_delta")) == "unknown_cr"
      and code(engine.reset_after_delta, s.w, a["id"], "plan", "CR-099", s.ev("cli_delta")) == "unknown_cr" and code(engine.reset_after_delta, s.w, a["id"], "build", b["id"], s.ev("cli_delta")) == "bad_reset")
trs = s.rec(engine.reset_after_delta(s.w, a["id"], "plan", b["id"], s.ev("cli_delta")))
check("delta reset_to plan: second merged, first back to plan, approval removed, fails 0", b["status"] == "merged" and b["merged_into"] == a["id"] and s.w["queue"] == [] and a["deltas"] == [b["id"]]
      and a["stage"] == "plan" and stg(a)["plan"] == "next" and stg(a)["approve"] == "next" and stg(a)["do"] == "next" and a["plan_sha"] is None and a["verify_fails"] == 0
      and stg(a)["scope"] == "skipped", (stg(a), b["status"]))
check("delta reset_to plan keeps scope; a merged CR can not be advanced or merged again", code(engine.advance, s.w, b["id"], "do", s.ev("role_stop"), s.r) == "closed" and code(engine.reset_after_delta, s.w, a["id"], "plan", b["id"], s.ev("cli_delta")) == "not_queued")
s.plan(a); s.approve(a)
c3_ = s.open("third")
trs = s.rec(engine.reset_after_delta(s.w, a["id"], "scope", c3_["id"], s.ev("cli_delta")))
check("delta reset_to scope: scope next again, stage scope", a["stage"] == "scope" and stg(a)["scope"] == "next" and stg(a)["approve"] == "next")
check("delta replay == engine state", s.replay_equal())
sf = Sim(mk_rules()); f1 = sf.open("fast one"); f2 = sf.open("queued")
sf.rec(engine.reset_after_delta(sf.w, f1["id"], "plan", f2["id"], sf.ev("cli_delta")))
check("delta on a fast-lane CR promotes it to full (a delta needs a plan)", f1["lane"] == "full" and f1["stage"] == "plan" and stg(f1)["approve"] == "next" and stg(f1)["review"] == "next" and sf.replay_equal())
# queue: guided autostart, manual waits
sg = Sim(mk_rules(autopilot="guided")); g1 = sg.open("g1"); g2 = sg.open("g2")
sg.build(g1); sg.passed(g1); sg.deliver(g1); trs = sg.learn(g1)
check("guided: next queued CR starts after the delivery (start line)", g1["status"] == "delivered" and sg.w["active"] == g2["id"] and g2["status"] == "open" and trs[-1]["op"] == "start" and sg.replay_equal())
sm = Sim(mk_rules(autopilot="manual")); m1 = sm.open("m1"); m2 = sm.open("m2")
sm.build(m1); sm.passed(m1)
sm.rec(engine.release(sm.w, m1["id"], sm.ev("owner_prompt", "owner"))); sm.deliver(m1); sm.rec(engine.release(sm.w, m1["id"], sm.ev("owner_prompt", "owner"))); trs = sm.learn(m1)
check("manual: the queue does not start by itself", m1["status"] == "delivered" and sm.w["active"] is None and m2["status"] == "queued" and not any(t["op"] == "start" for t in trs))
check("manual: no active CR -> next_action asks the owner to start the queued one", engine.next_action(sm.w, sm.r)["waiting_on"] == "owner" and "shipm cr start CR-002" in engine.next_action(sm.w, sm.r)["text"])
sm.rec(engine.start(sm.w, m2["id"], sm.ev("cli_start"), sm.r))
check("manual: shipm cr start activates it", sm.w["active"] == m2["id"] and m2["status"] == "open" and sm.replay_equal())
sab = Sim(mk_rules(autopilot="guided")); ab1 = sab.open("a"); ab2 = sab.open("b")
check("abandon needs owner_override", code(engine.abandon, sab.w, ab1["id"], sab.ev("owner_prompt", "owner")) == "owner_required")
sab.rec(engine.abandon(sab.w, ab1["id"], sab.ev("owner_override", "owner", reason="no"), sab.r))
check("abandon: status abandoned, guided starts the queue", ab1["status"] == "abandoned" and sab.w["active"] == ab2["id"] and sab.replay_equal())
sab.rec(engine.abandon(sab.w, ab2["id"], sab.ev("owner_override", "owner")))
check("abandoning a queued/active CR with an empty queue leaves no active CR", sab.w["active"] is None)

# ===== verify FAIL / block / unblock =================================================================================
s = Sim(mk_rules()); cr = s.open("v"); s.build(cr)
trs = s.failed(cr)
check("verify FAIL #1: fail:1, need a build, still verify, not blocked", stg(cr)["verify"] == "fail:1" and cr["verify_fails"] == 1 and cr["need_build"] and cr["stage"] == "verify" and cr["status"] == "open" and [t["op"] for t in trs] == ["fail"])
check("after FAIL a re-test without a build is refused", code(engine.advance, s.w, cr["id"], "verify", s.ev("qa_pass"), s.r) == "order")
na = engine.next_action(s.w, s.r)
check("next_action after FAIL: build fixes, then test again", na["agent"] == "builder" and na["role"] == "build" and "fixes" in na["text"] and "Test FAIL (attempt 1 of 2)" in na["text"], na["text"])
s.build(cr)
check("fix build keeps verify at fail:1 and clears need_build", stg(cr)["verify"] == "fail:1" and not cr["need_build"] and cr["stage"] == "verify")
s.passed(cr)
check("verify FAIL then PASS: fails reset, verified, stage deliver (fast)", cr["verify_fails"] == 0 and cr["verified"] and cr["stage"] == "deliver" and s.replay_equal())
s = Sim(mk_rules()); cr = s.open("v2"); s.build(cr); s.failed(cr); s.build(cr)
trs = s.failed(cr)
check("verify FAIL x2: blocked with reason verify_twice (fail then block lines)", [t["op"] for t in trs] == ["fail", "block"] and cr["status"] == "blocked" and cr["blocked"] == "verify_twice" and cr["verify_fails"] == 2)
check("blocked: advance / fail / open-other refused, CR stays active", code(engine.advance, s.w, cr["id"], "verify", s.ev("qa_pass"), s.r) == "blocked" and code(engine.fail, s.w, cr["id"], "verify", s.ev("qa_fail"), s.r) == "blocked"
      and s.w["active"] == cr["id"])
for name, e in (("a role stop", s.ev("role_stop", "builder", role="build")), ("qa_pass", s.ev("qa_pass")), ("a hand-back", s.ev("hand_back", owner_words=True)), ("owner_prompt flagged hand_back", s.ev("owner_prompt", hand_back=True))):
    check("unblock refused with %s" % name, code(engine.unblock, s.w, cr["id"], e) in ("owner_required", "bad_evidence") and cr["status"] == "blocked")
check("the engine's next_action while blocked waits on the owner", engine.next_action(s.w, s.r)["waiting_on"] == "owner" and "tests failed twice" in engine.next_action(s.w, s.r)["text"])
check("can_stop on a blocked CR is empty (stopping to ask is right); can_call_agent refuses build/test only", engine.can_stop(s.w, s.r) == []
      and [r.kind for r in engine.can_call_agent(s.w, s.r, "build")] == ["cr_blocked"] and [r.kind for r in engine.can_call_agent(s.w, s.r, "test")] == ["cr_blocked"]
      and engine.can_call_agent(s.w, s.r, "plan") == [] and engine.can_call_agent(s.w, s.r, "review") == [])
trs = s.rec(engine.unblock(s.w, cr["id"], s.ev("owner_prompt", "owner")))
check("owner prompt unblocks: open, fails 0, verify next, a build is needed first", cr["status"] == "open" and cr["blocked"] is None and cr["verify_fails"] == 0 and stg(cr)["verify"] == "next" and cr["need_build"] and s.replay_equal())
check("unblock a CR that is not blocked refused", code(engine.unblock, s.w, cr["id"], s.ev("owner_prompt")) == "not_blocked")
s = Sim(mk_rules()); cr = s.open("v3"); s.build(cr); s.failed(cr); s.build(cr); s.failed(cr)
s.rec(engine.unblock(s.w, cr["id"], s.ev("owner_override", "owner", reason="retry")))
check("owner_override also unblocks", cr["status"] == "open")
s.build(cr); s.passed(cr)
check("after unblock: build, then PASS works", cr["verified"])
s = Sim(mk_rules()); cr = s.open("v4"); s.build(cr)
check("block() by the engine/anyone is allowed; reason must be a short word", code(engine.block, s.w, cr["id"], "Bad Reason!", s.ev("engine")) == "bad_reason" and engine.block(s.w, cr["id"], "stuck", s.ev("stuck"))[0]["op"] == "block"
      and cr["status"] == "blocked" and engine.block(s.w, cr["id"], "stuck", s.ev("stuck")) == [])
check("a PASS not preceded by FAIL does not touch fail counters (fails stay consecutive only)", (lambda s5: (s5.build(s5.w["crs"][0]), s5.failed(s5.w["crs"][0]), s5.build(s5.w["crs"][0]), s5.passed(s5.w["crs"][0]),
      s5.w["crs"][0]["verify_fails"])[-1] == 0)((lambda x: (x.open("z"), x)[1])(Sim(mk_rules()))))

# ===== owner override =================================================================================================
s = Sim(mk_rules()); cr = s.open("ov", lane="full")
check("override needs a reason and the current stage", code(engine.advance, s.w, cr["id"], "scope", s.ev("owner_override"), s.r) == "reason_required"
      and code(engine.advance, s.w, cr["id"], "plan", s.ev("owner_override", reason="x"), s.r) == "order")
trs = s.rec(engine.advance(s.w, cr["id"], "scope", s.ev("owner_override", "owner", reason="not needed"), s.r))
check("owner_override moves the current stage (logged as override)", trs[0]["op"] == "override" and stg(cr)["scope"] == "done:owner" and cr["stage"] == "plan" and s.replay_equal())

# ===== hand-backs ====================================================================================================
s = Sim(mk_rules()); cr = s.open("hb", lane="full"); s.scope(cr); s.plan(cr)
for e in (s.ev("hand_back", owner_words=True), s.ev("owner_prompt", owner_words=True, hand_back=True)):
    check("hand-back text does not approve (%s)" % e["kind"], code(engine.advance, s.w, cr["id"], "approve", e, s.r) in ("wrong_evidence", "owner_required") and stg(cr)["approve"] == "next")
check("owner prompt with the caller's filter flag approves", s.approve(cr) and cr["stage"] == "do")

# ===== hold / release (manual autopilot) =============================================================================
s = Sim(mk_rules(autopilot="manual")); cr = s.open("mh", lane="full")
trs = s.scope(cr)
check("manual: every completed stage sets hold (hold line after the advance)", [t["op"] for t in trs] == ["advance", "hold"] and cr["hold"])
check("manual: can_call_agent refuses with manual_hold; can_stop has no cr_continue", [r.kind for r in engine.can_call_agent(s.w, s.r, "plan")] == ["manual_hold"] and
      "cr_continue" not in [r.kind for r in engine.can_stop(s.w, s.r, {"stage_event": True})])
na = engine.next_action(s.w, s.r)
check("manual: next_action says report and wait for next", na["waiting_on"] == "owner" and "wait for 'next'" in na["text"] and na["text"].startswith("CR-001: Scope done."), na["text"])
check("release by a hand-back / non-owner evidence refused", code(engine.release, s.w, cr["id"], s.ev("hand_back")) == "owner_required" and code(engine.release, s.w, cr["id"], s.ev("owner_prompt", hand_back=True)) == "owner_required"
      and code(engine.release, s.w, cr["id"], s.ev("qa_pass")) == "owner_required" and cr["hold"])
s.rec(engine.release(s.w, cr["id"], s.ev("owner_prompt", "owner")))
check("any owner prompt releases the hold", not cr["hold"] and engine.can_call_agent(s.w, s.r, "plan") == [] and s.replay_equal())
check("release when not held is a no-op", engine.release(s.w, cr["id"], s.ev("owner_prompt")) == [])
trs = s.plan(cr)
check("manual: the plan stage also holds; hold() is idempotent", cr["hold"] and engine.hold(s.w, cr["id"], s.ev("hold")) == [])
sg = Sim(mk_rules(autopilot="guided")); gc = sg.open("g", lane="full"); trs = sg.scope(gc)
check("guided: no hold lines", [t["op"] for t in trs] == ["advance"] and not gc["hold"])
sl = Sim(mk_rules(level="off", autopilot="guided"))
check("level off forces manual (gate.build_rules)", sl.r["autopilot"] == "manual")

# ===== can_stop =====================================================================================================
s = Sim(mk_rules()); cr = s.open("cs", lane="full")
check("can_stop: nothing before any change", engine.can_stop(s.w, s.r) == [])
engine.observe_diff(s.w, cr["id"], {"files": 1, "lines": 5, "risk": [], "deps": False}, s.ev("diff_eval"), s.r)
rs = engine.can_stop(s.w, s.r)
check("cr_needs_plan: full lane, changes seen, approve not done", [r.kind for r in rs] == ["cr_needs_plan"] and "CR-001" in rs[0].msg, rs)
s.plan(cr)
check("cr_needs_plan persists while the plan is not approved", [r.kind for r in engine.can_stop(s.w, s.r)] == ["cr_needs_plan"])
s.approve(cr)
check("cr_needs_plan gone after approval", engine.can_stop(s.w, s.r, {}) == [])
s.build(cr); s.passed(cr)
rs = engine.can_stop(s.w, s.r)
check("cr_review_missing after verify PASS with no review", [r.kind for r in rs] == ["cr_review_missing"] and "correctness" in rs[0].msg, rs)
s.review(cr); check("cr_review_missing gone after the review", engine.can_stop(s.w, s.r) == [])
# cr_continue conditions
cont = lambda w, r, **sess: [x.kind for x in engine.can_stop(w, r, sess)]
check("cr_continue: guided + stage event this turn + next stage lead-runnable", cont(s.w, s.r, stage_event=True) == ["cr_continue"], cont(s.w, s.r, stage_event=True))
check("cr_continue text is the guided hint", engine.can_stop(s.w, s.r, {"stage_event": True})[0].msg.endswith("Continue.") and "Review correctness ACCEPT" in engine.can_stop(s.w, s.r, {"stage_event": True})[0].msg)
check("cr_continue: not without a stage event this turn", cont(s.w, s.r) == [] and cont(s.w, s.r, stage_event=False) == [])
check("cr_continue: only once per turn", cont(s.w, s.r, stage_event=True, continued=True) == [] and cont(s.w, s.r, stage_event=True, continued=1) == [])
check("cr_continue: not when the assistant asked a question (ASKS match)", cont(s.w, s.r, stage_event=True, asks=True) == [])
check("cr_continue: not under manual autopilot", cont(s.w, mk_rules(autopilot="manual"), stage_event=True) == [])
sa_ = Sim(mk_rules()); ca_ = sa_.open("w", lane="full"); sa_.scope(ca_); sa_.plan(ca_)
check("cr_continue: not when waiting on the owner (approve)", cont(sa_.w, sa_.r, stage_event=True) == [] and engine.next_action(sa_.w, sa_.r)["waiting_on"] == "owner")
sb_ = Sim(mk_rules()); cb_ = sb_.open("b"); sb_.build(cb_); sb_.failed(cb_); sb_.build(cb_); sb_.failed(cb_)
check("cr_continue: not on a blocked CR", cont(sb_.w, sb_.r, stage_event=True) == [])
se_ = Sim(mk_rules())
check("cr_continue / refusals: nothing with no active CR", cont(se_.w, se_.r, stage_event=True) == [])
check("cr_continue after delivery with an empty queue: nothing", (lambda sd: (sd.build(sd.w["crs"][0]), sd.passed(sd.w["crs"][0]), sd.deliver(sd.w["crs"][0]), sd.learn(sd.w["crs"][0]), cont(sd.w, sd.r, stage_event=True))[-1] == [])(
      (lambda x: (x.open("d"), x)[1])(Sim(mk_rules()))))

# ===== next_action texts per state ===================================================================================
s = Sim(mk_rules("app")); na = engine.next_action(s.w, s.r)
check("next_action: no CR", na == {"cr": None, "stage": None, "role": None, "agent": None, "waiting_on": "none", "wait": "", "text": "No active CR."})
cr = s.open("RTL fix on login", lane="full")
T = lambda: engine.next_action(s.w, s.r)
check("next_action scope", T()["agent"] == "scoper" and T()["text"] == "CR-001: Next: Scope (optional) — scoper. Continue.", T()["text"])
s.scope(cr)
check("next_action plan", T()["agent"] == "planner" and T()["role"] == "plan" and T()["text"] == "CR-001: Scope done. Next: Plan — planner; present the plan, then wait for the owner's OK. Continue.", T()["text"])
s.plan(cr)
check("next_action approve: waiting on the owner", T()["waiting_on"] == "owner" and T()["agent"] is None and T()["text"] == "CR-001: Plan presented. Waiting on owner: approve the plan (write your OK in the chat).", T()["text"])
s.approve(cr)
check("next_action build", T()["agent"] == "builder" and T()["text"] == "CR-001: Plan approved. Next: Build — builder. Continue.", T()["text"])
s.build(cr, ui=True)
t_ = T()
check("next_action verify lists the checks and the attempt", t_["agent"] == "verifier" and "attempt 1 of 2" in t_["text"] and "contrast 4.5" in t_["text"] and "screens 375/768/1280" in t_["text"], t_["text"])
s.passed(cr)
check("next_action review names the lens", T()["agent"] == "reviewer" and T()["text"] == "CR-001: Test PASS. Next: Review — reviewer, lens correctness. Continue.", T()["text"])
s.review(cr, "correctness")
check("next_action review: design lens goes to the designer", T()["agent"] == "designer" and T()["role"] == "design" and "lens design" in T()["text"], T())
s.review(cr, "design", "PASS")
check("next_action deliver", T()["role"] == "lead" and "Release — commit and push" in T()["text"], T()["text"])
s.deliver(cr)
check("next_action learn", "docs/STATUS.md" in T()["text"] and "CR report" in T()["text"], T()["text"])
check("labels follow the type (ops: Dry-run)", "Dry-run" in (lambda so2: (so2.open("x", lane="full"), so2.scope(so2.w["crs"][0]), so2.plan(so2.w["crs"][0]), so2.approve(so2.w["crs"][0]), so2.build(so2.w["crs"][0]), engine.next_action(so2.w, so2.r)["text"])[-1])(Sim(mk_rules("ops"))))

# ===== brief and render ================================================================================================
sb = Sim(mk_rules("app", **{"risk_paths": ["src/auth/**"]})); sb.w["project"] = "sample-app"
b0 = engine.brief(sb.w, sb.r)
check("brief with no CR", b0.split("\n")[0] == "Playbook: app · strict · guided (sample-app)" and "Active: none" in b0 and "Queue: none" in b0 and "Last verdict: none" in b0, b0)
cr = sb.open("RTL fix on login", lane="full"); q = sb.open("Arabic numerals")
sb.scope(cr); sb.plan(cr); sb.approve(cr); sb.build(cr, ui=True)
sb.failed(cr); sb.build(cr)
b1 = engine.brief(sb.w, sb.r)
exp = ['Playbook: app · strict · guided (sample-app)',
       'Active: CR-001 "RTL fix on login" · full lane · at Test (attempt 2 of 2) · next: verifier',
       'Waiting on owner: none',
       'Queue: CR-002 "Arabic numerals"',
       'Last verdict: Test FAIL 212/214 (%s)' % engine._fmt_ts(sb.w["crs"][0]["verdict"]["ts"]),
       'Rules: plan by planner · your OK in chat · Test needs PASS · review correctness (+risk on src/auth/**)']
check("brief: exact six-line format (section 1.5)", b1.split("\n") == exp, "\n".join(b1.split("\n")))
sb.failed(cr)
b2 = engine.brief(sb.w, sb.r)
check("brief: blocked CR shows the owner wait", "Waiting on owner: tests failed twice" in b2, b2)
sb.rec(engine.unblock(sb.w, cr["id"], sb.ev("owner_prompt", "owner")))
check("brief size <= 1 KB, also with long titles and many words", len(engine.brief(sb.w, sb.r).encode()) <= 1024 and len(engine.brief(Sim(mk_rules()).w, mk_rules()).encode()) <= 1024)
sbig = Sim(mk_rules()); sbig.w["project"] = "P" * 60; cb = sbig.open("t" * 200, lane="full")
for i in range(6):
    sbig.open("q" * 200)
check("brief size cap with maximal titles", len(engine.brief(sbig.w, sbig.r).encode("utf-8")) <= 1000 and len(engine.brief(sbig.w, sbig.r)) > 100)
sf = Sim(mk_rules()); cf = sf.open("fast one")
check("brief rules line for the fast lane", "Rules: fast lane (up to 3 files, 50 lines) · Test needs PASS" == engine.brief(sf.w, sf.r).split("\n")[-1], engine.brief(sf.w, sf.r).split("\n")[-1])
sv = Sim(mk_rules()); cv = sv.open("v"); sv.build(cv); sv.passed(cv)
check("brief last verdict shows PASS with counts", "Last verdict: Test PASS 214/214 (" in engine.brief(sv.w, sv.r))
r = engine.render(sb.w)
check("render: public keys only, spec fields present", set(r) == {"v", "render", "project", "active", "queue", "crs", "updated"} and r["render"] == "shipmiracle-engine" and r["active"] == "CR-001"
      and r["queue"] == ["CR-002"] and set(r["crs"][0]) >= {"id", "title", "lane", "status", "stage", "opened", "by", "base", "stages", "verify_fails", "lenses", "plan_sha", "hold", "diff", "deltas", "reports"}
      and "need_build" not in r["crs"][0] and "learn" not in r["crs"][0], sorted(r["crs"][0]))
sm = Sim(mk_rules())
for i in range(40):
    c_ = sm.open("many %d " % i + "x" * 100)
    if sm.w["active"] == c_["id"]:
        sm.build(c_); sm.passed(c_); sm.deliver(c_); sm.learn(c_)
check("render stays < 4 KB with a long history (12 queued, many finished)", len(json.dumps(engine.render(sm.w), separators=(",", ":"), ensure_ascii=False).encode()) < 4000, len(json.dumps(engine.render(sm.w))))
check("render keeps at most the last 3 finished CRs", sum(1 for c_ in engine.render(sm.w)["crs"] if c_["status"] == "delivered") <= 3)
check("render is deterministic", engine.render(sm.w) == engine.render(copy.deepcopy(sm.w)))

# ===== evidence hygiene ====================================================================================================
s = Sim(mk_rules()); cr = s.open("e", lane="full"); s.scope(cr)
huge = s.ev("plan_presented", "planner", plan_sha=SHA, role_ts=s.t)
check("long strings are clipped (log line stays <= 1 KB)", all(len(v) <= 160 for v in engine._ev({"kind": "engine", "data": {"a": "x" * 5000}})["data"].values()))
check("evidence that cannot fit in a line is refused", code(engine.advance, s.w, cr["id"], "plan", dict(huge, data=dict(huge["data"], **{"k%d" % i: "y" * 150 for i in range(14)})), s.r) == "evidence_too_big")
check("control characters are removed from evidence", engine._ev({"kind": "engine", "ref": "a\x00b\x1b", "data": {"k": "x\x07y"}})["ref"] == "ab" and engine._ev({"kind": "engine", "data": {"k": "x\x07y"}})["data"]["k"] == "xy")
check("unknown CR refused", code(engine.advance, s.w, "CR-099", "plan", s.ev("plan_presented"), s.r) == "unknown_cr" and code(engine.unblock, s.w, "CR-099", s.ev("owner_prompt")) == "unknown_cr")
check("record_report keeps the last 5 and refuses a long path", (lambda: (all(s.rec(engine.record_report(s.w, cr["id"], "docs/reports/r%d.md" % i, s.ev("engine"))) for i in range(7)), cr["reports"])[1])() ==
      ["docs/reports/r%d.md" % i for i in range(2, 7)] and code(engine.record_report, s.w, cr["id"], "x" * 81, s.ev("engine")) == "bad_path")
check("refused calls never change the work (state is replayed from lines only)", s.replay_equal())

# ===== perf: engine operations < 5 ms each =====================================================================================
import statistics
def timeit(fn, n=300):
    ts = []
    for _ in range(n):
        t0 = time.perf_counter(); fn(); ts.append((time.perf_counter() - t0) * 1000)
    return statistics.mean(ts), max(ts)
sp = Sim(mk_rules()); cp = sp.open("perf", lane="full"); sp.scope(cp); sp.plan(cp)
evx = sp.ev("owner_prompt", owner_words=True)
wcopy = copy.deepcopy(sp.w)
mean_a, max_a = timeit(lambda: engine.advance(copy.deepcopy(wcopy), cp["id"], "approve", evx, sp.r))
mean_n, _ = timeit(lambda: engine.next_action(sp.w, sp.r))
mean_b, _ = timeit(lambda: engine.brief(sp.w, sp.r))
mean_c, _ = timeit(lambda: engine.can_stop(sp.w, sp.r, {"stage_event": True}))
mean_r, _ = timeit(lambda: engine.render(sp.w))
mean_e, _ = timeit(lambda: engine.evaluate_diff({"files": 2, "lines": 10, "risk": [], "deps": False}, sp.r))
print("# engine ms: advance(incl. deepcopy) %.3f (max %.2f) · next_action %.3f · brief %.3f · can_stop %.3f · render %.3f · evaluate_diff %.4f" % (mean_a, max_a, mean_n, mean_b, mean_c, mean_r, mean_e))
check("perf: every engine operation < 5 ms (mean)", max(mean_a, mean_n, mean_b, mean_c, mean_r, mean_e) < 5.0)

# ===== STORE ==============================================================================================================
def newproj(name):
    p = TMP / "dev" / name
    (p / ".git").mkdir(parents=True, exist_ok=True)
    return p
SB = TMP / "state"
P = newproj("Store1")
pid = store.pid_of(P)
import shipmiracle.projects as projects
check("pid is the registry formula (12 hex of sha256 shipmiracle-project:realpath)", pid == projects.project_id(P) and len(pid) == 12 and
      pid == __import__("hashlib").sha256(("shipmiracle-project:" + os.path.realpath(P)).encode()).hexdigest()[:12])
check("log path is v1/cr/<pid>.jsonl under the state dir", store.log_path(P) == SB / "v1" / "cr" / (pid + ".jsonl"))

# concurrent appends: 12 processes x 50
t0 = time.time()
procs = [subprocess.Popen([sys.executable, __file__, "worker", "append", str(P), "50", str(k)], stderr=subprocess.PIPE) for k in range(12)]
codes = [p_.wait() for p_ in procs]
for p_ in procs:
    err = p_.stderr.read().decode()
    if err:
        print(err[:300])
print("# 12x50 appends took %.2fs" % (time.time() - t0))
raw = open(store.log_path(P), "rb").read()
lines, bad = store._parse_lines(raw)
check("12 processes x 50 appends: no worker error", codes == [0] * 12, codes)
check("600 whole lines, none torn, none corrupt", len(lines) == 600 and bad == 0 and raw.count(b"\n") == 600, (len(lines), bad))
check("every worker's lines are all there (50 each)", all(sum(1 for l in lines if l["by"] == str(k)) == 50 for k in range(12)))
# concurrent transact: 4 processes x 3 opens -> 12 unique CR ids
P2 = newproj("Store2")
procs = [subprocess.Popen([sys.executable, __file__, "worker", "open", str(P2), "3", str(k)], stderr=subprocess.PIPE) for k in range(4)]
codes = [p_.wait() for p_ in procs]
w2 = store.load(P2)
ids = [c_["id"] for c_ in w2["crs"]]
check("4 processes x 3 opens through transact: no error, 12 distinct sequential ids", codes == [0] * 4 and sorted(ids) == ["CR-%03d" % i for i in range(1, 13)], (codes, ids))
check("WIP = 1 holds under concurrency (one active, 11 queued)", w2["active"] is not None and len(w2["queue"]) == 11)

# permissions
check("cr dir 0700, log 0600, lock 0600", mode(SB / "v1" / "cr") == 0o700 and mode(store.log_path(P)) == 0o600 and mode(SB / "v1" / "cr" / (pid + ".lock")) == 0o600)
old = os.umask(0); P3 = newproj("Store3")
try:
    w = store.load_work(P3)
    store.transact(P3, lambda w: (None, engine.open_cr(w, "perm", "t", 1760000000, rules=RULES_S)[1]))
finally:
    os.umask(old)
check("umask 0 does not widen: log 0600, cr dir 0700", mode(store.log_path(P3)) == 0o600 and mode(SB / "v1" / "cr") == 0o700)
check("work.json is 0644 in the repo, .rendered 0600, .shipmiracle 0755", mode(P3 / ".shipmiracle" / "work.json") == 0o644 and mode(SB / "v1" / "cr" / (store.pid_of(P3) + ".rendered")) == 0o600 and mode(P3 / ".shipmiracle") == 0o755)
check("state.check finds no permission problem", state.check(SB) == [], state.check(SB))

# replay == engine state, through the store
P4 = newproj("Store4")
sim_w = engine.new_work()
r_ = mk_rules()
def step(project, f):
    def fn(w):
        trs = f(w)
        return None, trs
    store.transact(project, fn)
    f(sim_w)       # the same step on an in-memory copy
cr_id = "CR-001"
step(P4, lambda w: engine.open_cr(w, "via store", "o", 1760000100, lane="full", base=BASE, rules=r_)[1])
step(P4, lambda w: engine.advance(w, cr_id, "scope", {"kind": "role_stop", "data": {"role": "scope"}, "by": "scoper", "ts": 1760000200}, r_))
step(P4, lambda w: engine.advance(w, cr_id, "plan", {"kind": "plan_presented", "data": {"plan_sha": SHA, "role_ts": 1760000300}, "by": "planner", "ts": 1760000300}, r_))
step(P4, lambda w: engine.advance(w, cr_id, "approve", {"kind": "owner_prompt", "data": {"owner_words": True}, "by": "owner", "ts": 1760000400}, r_))
step(P4, lambda w: engine.advance(w, cr_id, "do", {"kind": "role_stop", "data": {"role": "build", "diff": {"files": 2, "lines": 9}}, "by": "builder", "ts": 1760000500}, r_))
step(P4, lambda w: engine.fail(w, cr_id, "verify", {"kind": "qa_fail", "data": {"counts": "1/2"}, "by": "verifier", "ts": 1760000600}, r_))
loaded = store.load(P4)
sim_w["project"] = "Store4"
check("store.load(replay of the log) == the engine state step by step", loaded == sim_w, (loaded["crs"][0]["stages"], sim_w["crs"][0]["stages"]))
check("refused transact writes nothing", (lambda n0: (code(lambda: store.transact(P4, lambda w: (None, engine.advance(w, cr_id, "learn", {"kind": "status_dated", "data": {}}, r_)))), len(open(store.log_path(P4), "rb").read().split(b"\n")) == n0)[1])(
      len(open(store.log_path(P4), "rb").read().split(b"\n"))))
wk = json.loads((P4 / ".shipmiracle" / "work.json").read_text())
check("work.json is rendered from the log (< 4 KB, shipmiracle-engine)", wk["render"] == "shipmiracle-engine" and wk["active"] == "CR-001" and wk["crs"][0]["stages"]["verify"] == "fail:1" and len((P4 / ".shipmiracle" / "work.json").read_bytes()) < 4096)
check("load() (read-only) writes nothing and emits nothing", (lambda m, n: (store.load(P4), (P4 / ".shipmiracle" / "work.json").stat().st_mtime_ns == m, len(events.tail(500)) == n)[1:])(
      (P4 / ".shipmiracle" / "work.json").stat().st_mtime_ns, len(events.tail(500))) == (True, True))

# forged work.json
ev0 = len(events.tail(500))
forged = json.loads((P4 / ".shipmiracle" / "work.json").read_text())
forged["crs"][0]["stages"]["approve"] = "done:owner"; forged["crs"][0]["stages"]["verify"] = "done:verifier"; forged["crs"][0]["stages"]["review"] = "done:reviewer"
(P4 / ".shipmiracle" / "work.json").write_text(json.dumps(forged))
w = store.load_work(P4)
now_wk = json.loads((P4 / ".shipmiracle" / "work.json").read_text())
kinds = [e["kind"] for e in events.tail(500)[ev0:]]
check("forged work.json is ignored (decisions come from the log)", w["crs"][0]["stages"]["verify"] == "fail:1" and w["crs"][0]["stages"]["review"] == "next")
check("forged work.json is re-rendered from the log", now_wk["crs"][0]["stages"]["verify"] == "fail:1" and now_wk["crs"][0]["stages"]["review"] == "next")
check("cr.work_forged event logged once, with the project id and no file content", kinds.count("cr.work_forged") == 1 and events.tail(500)[-1]["project"] == store.pid_of(P4), kinds)
ev1 = len(events.tail(500))
store.load_work(P4)
check("no new forged event when the file is the engine's own", [e["kind"] for e in events.tail(500)[ev1:]] == [])
os.unlink(P4 / ".shipmiracle" / "work.json"); store.load_work(P4)
check("deleted work.json is re-rendered without a forged event", (P4 / ".shipmiracle" / "work.json").exists() and [e["kind"] for e in events.tail(500)[ev1:]] == [])
(P4 / ".shipmiracle" / "work.json").write_text("{}")
os.unlink(SB / "v1" / "cr" / (store.pid_of(P4) + ".rendered"))
store.load_work(P4)
check("changed file with no render sha (lost state) is also reported", [e["kind"] for e in events.tail(500)[ev1:]].count("cr.work_forged") == 1)
(P4 / ".shipmiracle" / "work.json").write_text("garbage"); store.render(P4)
check("shipm cr render (store.render) rewrites the file", json.loads((P4 / ".shipmiracle" / "work.json").read_text())["active"] == "CR-001")
# engine-written then crash before render: stale but untouched file is not forged
ev2 = len(events.tail(500))
store.append(P4, [engine.open_cr(copy.deepcopy(store.load(P4)), "late", "o", 1760000900, rules=r_)[1][0]])
store.load_work(P4)
check("stale (untampered) render after a crash is repaired quietly", [e["kind"] for e in events.tail(500)[ev2:]] == [] and len(json.loads((P4 / ".shipmiracle" / "work.json").read_text())["crs"]) == 2)
# symlinked .shipmiracle
P5 = newproj("Store5"); os.symlink(str(TMP), str(P5 / ".shipmiracle"))
check("a symlinked .shipmiracle is refused", raises(SafetyError, store.transact, P5, lambda w: (None, engine.open_cr(w, "x", "o", 1, rules=r_)[1])) is True)
check("...and the log did not get the line committed before the refusal being relevant (log exists, work.json not written outside)", not (TMP / "work.json").exists())

# import fallback
P6 = newproj("Store6"); (P6 / ".shipmiracle").mkdir()
evil = {"v": 1, "render": "x", "active": "CR-004", "queue": ["CR-005"], "crs": [
    {"id": "CR-004", "title": "imported \x00job", "lane": "full", "status": "open", "stage": "review", "opened": 1760000000, "by": "owner", "base": BASE,
     "stages": {"scope": "skipped", "plan": "done:planner", "approve": "done:owner", "do": "done:builder", "verify": "done:verifier", "review": "done:reviewer", "deliver": "next", "learn": "next"},
     "lenses": {"correctness": "ACCEPT"}, "plan_sha": SHA, "verify_fails": 0},
    {"id": "CR-005", "title": "queued one", "lane": "fast", "status": "queued", "stages": {"approve": "skipped", "review": "skipped", "plan": "skipped", "scope": "skipped"}},
    {"id": "../../etc", "title": "bad id", "lane": "full", "status": "open"}, {"id": "CR-006", "title": "", "status": "open"}, "junk",
    {"id": "CR-007", "title": "old", "lane": "full", "status": "delivered", "stages": {"approve": "done:owner", "verify": "done:verifier"}}]}
(P6 / ".shipmiracle" / "work.json").write_text(json.dumps(evil))
e0 = len(events.tail(500))
w = store.load_work(P6)
cr4 = engine.get_cr(w, "CR-004")
check("import (no log): approve/verify/review reset to next, others kept", cr4 is not None and cr4["stages"]["approve"] == "next" and cr4["stages"]["verify"] == "next" and cr4["stages"]["review"] == "next"
      and cr4["stages"]["plan"] == "done:planner" and cr4["stages"]["do"] == "done:builder" and cr4["stage"] == "approve", cr4 and cr4["stages"])
check("import: lenses and plan_sha are not trusted; title cleaned", not any(cr4["lenses"].values()) and cr4["plan_sha"] is None and cr4["title"] == "imported job")
check("import: bad ids / empty titles / junk skipped; active and queue kept; fast CR's approve/review also reset", [c_["id"] for c_ in w["crs"]] == ["CR-004", "CR-005", "CR-007"] and w["active"] == "CR-004"
      and w["queue"] == ["CR-005"] and engine.get_cr(w, "CR-005")["stages"]["approve"] == "next")
check("import: a finished CR stays finished; next id continues after the highest", engine.get_cr(w, "CR-007")["status"] == "delivered" and engine.open_cr(copy.deepcopy(w), "n", "o", 1, rules=r_)[0]["id"] == "CR-008")
check("import event cr.imported logged, log file created, work.json re-rendered without a forged event", [e["kind"] for e in events.tail(500)[e0:]] == ["cr.imported"] and store.log_path(P6).exists()
      and json.loads((P6 / ".shipmiracle" / "work.json").read_text())["crs"][0]["stages"]["approve"] == "next")
check("an imported CR needs approval, evidence and review again (approve refused before plan evidence is irrelevant: stage is approve)", code(engine.advance, w, "CR-004", "verify", {"kind": "qa_pass", "data": {}}, r_) == "order")
check("import happens once: a second load_work keeps the log as the authority", (lambda: (store.load_work(P6), len(store._parse_lines(open(store.log_path(P6), "rb").read())[0]))[1])() == 3)
P7 = newproj("Store7"); (P7 / ".shipmiracle").mkdir(); (P7 / ".shipmiracle" / "work.json").write_bytes(b"x" * 70000)
check("oversize / invalid committed work.json is not imported", store.load_work(P7)["crs"] == [] and not store.log_path(P7).exists())
P8 = newproj("Store8")
check("no log and no work.json: empty work, nothing written", store.load_work(P8)["crs"] == [] and not (P8 / ".shipmiracle").exists() and not store.log_path(P8).exists())
check("load() of a project with only a committed work.json shows the preview (reset) without writing", (lambda P9: (os.makedirs(P9 / ".shipmiracle"), (P9 / ".shipmiracle" / "work.json").write_text(json.dumps(evil)), store.load(P9)["crs"][0]["stages"]["approve"] == "next" and not store.log_path(P9).exists())[-1])(newproj("Store9")))

# corrupt lines
P10 = newproj("Store10")
store.transact(P10, lambda w: (None, engine.open_cr(w, "good one", "o", 1760000000, rules=r_)[1]))
with open(store.log_path(P10), "ab") as f:
    f.write(b"not json at all\n{\"op\":\"advance\"}\n[1,2]\n" + b"{\"ts\":1,\"op\":\"zzz\",\"cr\":\"CR-001\"}\n" + b"\xff\xfe\n" + b"{\"ts\":5,\"cr\":\"CR-001\",\"op\":\"advance\",\"stage\":\"plan\",\"by\":\"p\"")   # torn, no newline
w = store.load(P10)
check("corrupt lines are skipped, the good CR survives", len(w["crs"]) == 1 and w["crs"][0]["title"] == "good one")
store.transact(P10, lambda w: (None, engine.open_cr(w, "after torn", "o", 1760000001, rules=r_)[1]))
w = store.load(P10)
check("a torn last line does not swallow the next append", [c_["title"] for c_ in w["crs"]] == ["good one", "after torn"], [c_["title"] for c_ in w["crs"]])
check("oversize lines are skipped as corrupt", store._parse_lines(b"{\"ts\":1,\"op\":\"x\",\"pad\":\"" + b"a" * 1100 + b"\"}\n")[1] == 1)
check("append refuses a line > 1 KB", raises(UsageError, store.append, P10, [{"ts": 1, "cr": "CR-001", "op": "report", "stage": None, "by": "x", "sid8": None, "ev": {"kind": "engine", "ref": None, "data": {"pad": "z" * 1100}}}]) is True)
check("store.replay skips lines the engine cannot apply and counts them", store.replay([{"ts": 1, "op": "advance", "cr": "CR-009", "stage": "scope", "ev": {}}])[1] == 1)

# compaction
P11 = newproj("Store11")
NOW = 1760000000 + 40 * 86400
def lifecycle(project, title, t0):
    def fn(w):
        trs = []
        c_, t_ = engine.open_cr(w, title, "o", t0, base=BASE, rules=r_); trs += t_
        ev_ = lambda k, **d: {"kind": k, "data": d, "by": "x", "ts": t0 + 10}
        trs += engine.advance(w, c_["id"], "do", ev_("role_stop", role="build", diff={"files": 1, "lines": 1}), r_)
        trs += engine.advance(w, c_["id"], "verify", ev_("qa_pass"), r_)
        trs += engine.advance(w, c_["id"], "deliver", ev_("git_delivered"), r_)
        trs += engine.advance(w, c_["id"], "learn", ev_("status_dated"), r_)
        trs += engine.advance(w, c_["id"], "learn", ev_("report_written"), r_)
        return c_["id"], trs
    return store.transact(project, fn)
old1 = lifecycle(P11, "old one", NOW - 30 * 86400)
old2 = lifecycle(P11, "old two", NOW - 20 * 86400)
rec_ = lifecycle(P11, "recent", NOW - 3 * 86400)
store.transact(P11, lambda w: (None, engine.open_cr(w, "still open", "o", NOW - 1000, rules=r_)[1]))
store.save_snapshot(P11, old1, {"base": BASE, "untracked": ["a"]})
size0 = len(open(store.log_path(P11), "rb").read())
n_ = store.compact(P11, NOW)
w = store.load(P11)
lines, _ = store._parse_lines(open(store.log_path(P11), "rb").read())
check("compaction folds the two CRs finished > 14 days ago", n_ == 2 and [c_["id"] for c_ in w["crs"]] == ["CR-003", "CR-004"], [c_["id"] for c_ in w["crs"]])
check("...into exactly one archived line, first in the log; log got smaller", [l["op"] for l in lines].count("archived") == 1 and lines[0]["op"] == "archived" and len(open(store.log_path(P11), "rb").read()) < size0)
check("...recent and open CRs replay identically (state preserved)", engine.get_cr(w, "CR-003")["status"] == "delivered" and w["active"] == "CR-004" and engine.get_cr(w, "CR-004")["status"] == "open")
check("ids never repeat after compaction (max id kept in the archive)", engine.open_cr(copy.deepcopy(w), "n", "o", NOW, rules=r_)[0]["id"] == "CR-005")
check("snapshot file of an archived CR is removed; mode stays 0600", not store.snapshot_path(P11, old1).exists() and mode(store.log_path(P11)) == 0o600)
check("compaction twice does nothing more", store.compact(P11, NOW) == 0)
n2 = store.compact(P11, NOW + 20 * 86400)
w = store.load(P11); lines, _ = store._parse_lines(open(store.log_path(P11), "rb").read())
arch = [l for l in lines if l["op"] == "archived"]
check("a later compaction merges into the same single archived line", n2 == 1 and len(arch) == 1 and arch[0]["ev"]["data"]["n"] == 3 and arch[0]["ev"]["data"]["max"] == 4, arch[0]["ev"]["data"] if arch else None)
check("archived line <= 1 KB even with many entries", (lambda P12: (lambda ids: len(engine.dumps_line(store._parse_lines(open(store.log_path(P12), "rb").read())[0][0]).encode()) <= 1024)(
      [lifecycle(P12, "t%d" % i, NOW - 60 * 86400 + i) for i in range(40)] and store.compact(P12, NOW)))(newproj("Store12")))
check("replay of a compacted log still opens new CRs and keeps guided queue order", store.load(P11)["active"] == "CR-004")
check("snapshots: save/load roundtrip, bad id refused", store.load_snapshot(P11, "CR-004") is None and (store.save_snapshot(P11, "CR-004", {"base": BASE, "untracked": ["x"]}), store.load_snapshot(P11, "CR-004"))[1]["untracked"] == ["x"]
      and raises(UsageError, store.snapshot_path, P11, "../x") is True)

# isolation
real = paths.real_home() / ".local" / "state" / "shipmiracle"
check("isolation: the real state folder is refused (cr_dir, append, transact via base)", raises(SafetyError, store.cr_dir, real) is True
      and raises(SafetyError, store.append, P, [], real) is True and raises(SafetyError, store.transact, P, lambda w: (None, []), real) is True)
mine = {store.pid_of(newproj(n_)) for n_ in ("Store1", "Store2", "Store3", "Store4", "Store6", "Store10", "Store11")}
check("isolation: nothing of this run exists under the real state folder", not any(f.split(".")[0] in mine for f in (os.listdir(real / "v1" / "cr") if (real / "v1" / "cr").is_dir() else [])))
check("isolation: all log files live in the temp state dir", all(str(p_).startswith(str(SB)) for p_ in (SB / "v1" / "cr").iterdir()))

# registry snapshot writer
import shipmiracle.registry as registry
# T3 (wired): registry.SETTABLE now has 'playbook'; the stub's NotImplementedError only remains for a registry without the key
_st = registry.SETTABLE
registry.SETTABLE = tuple(k for k in _st if k != "playbook")
check("registry_snapshot_write: NotImplementedError when the registry has no 'playbook' key (fail closed)", raises(NotImplementedError, store.registry_snapshot_write, P, {"sha256": "0" * 64}) is True)
registry.SETTABLE = _st
check("registry_snapshot_write: a damaged snapshot is refused by the wired registry (UsageError)", raises(UsageError, store.registry_snapshot_write, P, {"sha256": "0" * 64}) is True)
calls = []
orig = (registry.SETTABLE, registry.set_field)
registry.SETTABLE = registry.SETTABLE + ("playbook",); registry.set_field = lambda pid_, k, v: calls.append((pid_, k, v))
store.registry_snapshot_write(P, config.snapshot_of({"v": 1, "type": "app"}))
registry.SETTABLE, registry.set_field = orig
check("registry_snapshot_write: delegates to registry.set_field(pid, 'playbook', snapshot) when allowed", calls and calls[0][0] == pid and calls[0][1] == "playbook" and calls[0][2]["type"] == "app")
check("registry_entry: None for a missing registry / entry (read-only)", store.registry_entry(P) is None)

# store timing
Pt = newproj("StoreT")
store.transact(Pt, lambda w: (None, engine.open_cr(w, "t", "o", 1, rules=r_)[1]))
tr_ = {"ts": 5, "cr": "CR-001", "op": "report", "stage": None, "by": "x", "sid8": None, "ev": {"kind": "engine", "ref": None, "data": {"path": "r"}}}
m_app, mx_app = timeit(lambda: store.append(Pt, [tr_]), 300)
m_load, _ = timeit(lambda: store.load(Pt), 100)
m_tx, _ = timeit(lambda: store.transact(Pt, lambda w: (None, []), do_render=False), 100)
print("# store ms: append %.3f (max %.2f) · load(300 lines) %.3f · transact(no-op, no render) %.3f" % (m_app, mx_app, m_load, m_tx))
check("perf: store append < 5 ms (mean)", m_app < 5.0, m_app)

print("\nFAILED: %d" % fails if fails else "\nALL PASS")
sys.exit(1 if fails else 0)
