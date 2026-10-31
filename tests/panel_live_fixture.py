#!/usr/bin/env python3
"""Builds a LIVE-shaped project set with the real engine APIs (no hand-written contract JSON) for the panel golden / performance tests.
Not a test (test-all runs *_test.py only). Needs the full isolation env (SHIPMIRACLE_TEST=1, SHIPMIRACLE_DEV, SHIPMIRACLE_STATE, SHIPMIRACLE_CONFIG, SHIPMIRACLE_HOME, HOME all in fresh temp folders):
the script refuses to write anywhere else.

  python3 tests/panel_live_fixture.py golden   ->  JSON on stdout: {"projects":[{name,dir,type,expect}], ...}
  python3 tests/panel_live_fixture.py perf     ->  12 projects, 50 CRs, 500 reports

golden: open CRs in several stages (scope, plan, approve, do, verify FAIL, verify BLOCKED, review, deliver), a delivered CR, queued-only, a project with
no playbook, a full-autopilot project that is running and one that is paused on a hard stop, stage reports in the reports index (FAIL / PASS / BLOCKED),
a CR report, and the registered `ask` inbox project with notes."""
import json, os, pathlib, subprocess, sys, tempfile, time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))


def _guard():
    need = ("SHIPMIRACLE_TEST", "SHIPMIRACLE_DEV", "SHIPMIRACLE_STATE", "SHIPMIRACLE_CONFIG", "SHIPMIRACLE_HOME", "HOME", "SHIPMIRACLE_WS", "CLAUDE_CONFIG_DIR")
    if os.environ.get("SHIPMIRACLE_TEST") != "1" or any(not os.environ.get(k) for k in need):
        sys.exit("panel_live_fixture: refusing to run without the full isolation env")
    from shipmiracle_isolation import _under_temp
    for k in need[1:]:
        if not _under_temp(os.environ[k]):
            sys.exit("panel_live_fixture: %s is not under a temp folder: refusing" % k)


_guard()
from shipmiracle import events, projects  # noqa: E402
from shipmiracle.autopilot import charter as chm, state as ap  # noqa: E402
from shipmiracle.playbook import engine, gate, store  # noqa: E402
from shipmiracle.report import write  # noqa: E402

ENV = dict(os.environ)
DEV, STATE = pathlib.Path(os.environ["SHIPMIRACLE_DEV"]), pathlib.Path(os.environ["SHIPMIRACLE_STATE"])
T0 = int(time.time()) - 6 * 3600
SHA = "ab" * 32


def git(d, *a):
    return subprocess.run(["git", "-C", str(d)] + list(a), env=ENV, capture_output=True, text=True, check=True, stdin=subprocess.DEVNULL).stdout.strip()


def shipm(*args):
    r = subprocess.run([sys.executable, str(ROOT / "bin" / "shipm")] + list(args), env=ENV, capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        sys.exit("Shipmiracle %s failed: %s" % (" ".join(args), r.stderr[:300]))
    return r.stdout


def mkproj(name, typ=None, autopilot=None):
    d = DEV / name
    d.mkdir(parents=True)
    git(d, "init", "-q", "-b", "main")
    (d / "a.txt").write_text("1\n")
    git(d, "add", "-A"); git(d, "commit", "-q", "-m", "init")
    if typ:
        shipm("playbook", "set", "type", typ, "--project", name, "--allow-open-chat")
        if autopilot:
            shipm("playbook", "set", "autopilot", autopilot, "--project", name, "--allow-open-chat")
    return d


class Sim:
    def __init__(self, d):
        self.d, self.t = d, T0
        self.r = gate.stage_rules(str(d))
        self.w = store.load(str(d), STATE)
        self.trs = []
        self.base = git(d, "rev-parse", "HEAD")

    def tick(self, n=60):
        self.t += n
        return self.t

    def ev(self, kind, by=None, **data):
        return {"kind": kind, "data": data, "by": by or data.get("role") or "x", "ts": self.tick()}

    def open(self, title, lane="full"):
        cr, trs = engine.open_cr(self.w, title, "owner", self.tick(), lane=lane, base=self.base, rules=self.r, kind="cli_open")
        self.trs += trs
        return cr

    def adv(self, cr, stage, kind, by=None, **data):
        self.trs += engine.advance(self.w, cr["id"], stage, self.ev(kind, by, **data), self.r)

    def fail(self, cr, **data):
        self.trs += engine.fail(self.w, cr["id"], "verify", self.ev("qa_fail", "verifier", **data), self.r)

    def block(self, cr, reason):
        self.trs += engine.block(self.w, cr["id"], reason, self.ev("stuck", "engine"))

    def upto(self, cr, stage):
        """Advance through the stages before `stage` (scope, plan, approve, do, verify, review, deliver, learn)."""
        steps = [("scope", "role_stop", "scoper", dict(role="scope")), ("plan", "plan_presented", "planner", dict(plan_sha=SHA, role_ts=self.t)),
                 ("approve", "owner_prompt", "owner", dict(owner_words=True)), ("do", "role_stop", "builder", dict(role="build", diff={"files": 2, "lines": 20, "risk": [], "deps": False})),
                 ("verify", "qa_pass", "verifier", dict(counts={"passed": 214, "failed": 0, "total": 214}, evidence="`npm test` -> 214 passed", cmd="npm test", not_verified="real device")),
                 ("review", "review_verdict", "reviewer", dict(lens="correctness", verdict="ACCEPT")), ("deliver", "git_delivered", "lead", {})]
        for st, kind, by, data in steps:
            if st == stage:
                return
            if engine.get_cr(self.w, cr["id"])["stage"] != st:      # a stage this type does not have (or already passed)
                continue
            self.adv(cr, st, kind, by, **data)

    def deliver_all(self, cr):
        self.upto(cr, "none")
        self.adv(cr, "learn", "status_dated", "lead"); self.adv(cr, "learn", "report_written", "lead")

    def save(self):
        store.append(self.d, self.trs, base=STATE)


def golden():
    out = []
    fail_counts = dict(counts={"passed": 212, "failed": 2, "total": 214}, evidence="npm test -> 212 passed, 2 failed", cmd="npm test", failed=["a.test:1", "b.test:2"], not_verified="screenshots")
    # name, type, stage to stop at, extra
    specs = [("alpha-scope", "software"), ("beta-plan", "app"), ("gamma-approve", "software"), ("delta-build", "content"), ("eps-fail", "software"), ("zeta-twice", "ops"),
             ("eta-review", "research"), ("theta-deliver", "software"), ("iota-done", "notes"), ("kappa-queued", "software"), ("lambda-idle", "app")]
    for name, typ in specs:
        d = mkproj(name, typ)
        if name == "lambda-idle":
            out.append(d); continue
        s = Sim(d)
        if name == "kappa-queued":
            s.open("Export report"); s.open("Dark mode")        # first one becomes active in the engine; the second is queued
            s.save(); out.append(d); continue
        cr = s.open("RTL fix on login" if name != "gamma-approve" else "Export report")
        stage = {"alpha-scope": "scope", "beta-plan": "plan", "gamma-approve": "approve", "delta-build": "do", "eps-fail": "do", "zeta-twice": "do", "eta-review": "review", "theta-deliver": "deliver"}.get(name)
        if name == "iota-done":
            s.deliver_all(cr)
        elif name == "eps-fail":
            s.upto(cr, "verify"); s.fail(cr, **fail_counts)
        elif name == "zeta-twice":
            s.upto(cr, "verify"); s.fail(cr, **fail_counts); s.adv(cr, "do", "role_stop", "builder", role="build", diff={"files": 1, "lines": 3, "risk": [], "deps": False}); s.fail(cr, **fail_counts)
        else:
            s.upto(cr, stage)
        if name in ("alpha-scope", "gamma-approve"):
            s.open("Second request"); s.open("Third request")
        s.save(); out.append(d)
    # an autopilot project RUNNING, one PAUSED on a hard stop (state files written through the engine's own state module)
    shipm("switch", "autopilot.full.enabled", "on")                  # the owner switch, in the throw-away config folder
    for name, mode in (("mu-auto-run", "run"), ("nu-auto-stop", "stop")):
        d = mkproj(name, "software", autopilot="full")
        s = Sim(d); cr = s.open("Ship the login"); s.upto(cr, "do"); s.save()
        pid = projects.project_id(d)
        fields = chm.parse_line('charter: goal="ship login"; scope="src/**,tests/**"; budget=10%; time=3h; deps=none; ends=CR-001')[0]     # a real stored charter (registry record + state `set`)
        chm.store_charter(pid, fields, "cli", base=STATE, prereq_check=False)

        def run(cur, mode=mode):
            cur.update(state="running", started=int(time.time()) - 1800, expires=int(time.time()) + 4320, budget_start={"pct": 10.0, "resets_at": int(time.time()) + 86400}, last_pct=14.1, used_pct=4.1, decisions=1)
            return cur
        ap.update(pid, run, base=STATE)
        if mode == "stop":
            ap.pause(pid, stop={"id": "H-1a2b3c", "rule": "push_public", "text": "autopilot wants to push publicly", "ts": int(time.time())}, base=STATE)
        events.append("auto_decision", {"cr": cr["id"], "stage": "do", "rule": "continue", "charter_sha": "c1" * 32, "detail": "build next"}, project=pid, src="autopilot", base=STATE)
        out.append(d)
    out.append(mkproj("omicron-legacy"))                                         # no playbook at all
    # reports: stage reports FAIL / PASS / BLOCKED and a CR report, through the real writers
    write.write_stage(DEV / "eps-fail", "CR-001", "verify", base=STATE)
    write.write_stage(DEV / "eta-review", "CR-001", "scope", base=STATE)
    write.write_stage(DEV / "zeta-twice", "CR-001", "verify", base=STATE)
    write.write_cr(DEV / "iota-done", "CR-001", base=STATE)
    # the registered ask inbox project with notes
    from shipmiracle import ask
    ask.create_project()
    nd = ask.notes_dir(create=True)
    for i, (slug, q) in enumerate((("what-is-a-monad", "What is a monad?"), ("rtl-in-css", "ما هو RTL في CSS؟"))):
        (nd / ("2026-10-2%d-%s.md" % (i, slug))).write_text("# Ask · 2026-10-2%d · %s\n\nQuestion: %s\n\nAnswer: short.\n\nNot verified: the answer comes from the model alone.\n" % (i, q, q), encoding="utf-8")
    out.append(DEV / "ask")
    return out


def perf():
    out = []
    types = ["software", "app", "notes"]            # types whose review needs the one lens the helper gives
    n_cr = 0
    for i in range(12):
        name = "perf-%02d" % i
        d = mkproj(name, types[i % 3])
        s = Sim(d)
        k = 5 if i < 2 else 4                                   # 2*5 + 10*4 = 50 CRs
        for j in range(k):
            cr = s.open("Request %d of %s" % (j, name))
            n_cr += 1
            if j < k - 1:
                s.deliver_all(cr)                                  # earlier CRs are finished; the last one stays active at the plan stage
            else:
                s.upto(cr, "plan")
        s.save(); out.append(d)
    # 500 report index items through the real index writer (newest first, capped at 500 by the writer)
    for i in range(500):
        write.index_add({"id": "perf-%02d-2026-10-20-CR-%03d-verify-%03d" % (i % 12, i % 90 + 1, i), "project": "perf-%02d" % (i % 12), "kind": "stage" if i % 7 else "cr", "cr": "CR-%03d" % (i % 90 + 1), "stage": "verify" if i % 7 else None,
                         "verdict": ("FAIL", "PASS", "BLOCKED", "NOT TESTED", "PASS")[i % 5], "ts": T0 + i * 60, "title": "CR-%03d Test" % (i % 90 + 1), "sub": "%d of 214 tests failed" % (i % 9),
                         "path": str(STATE / "v1" / "reports" / ("r%04d.md" % i)), "private": True}, base=STATE)
    return out, n_cr


if __name__ == "__main__":
    prof = sys.argv[1] if len(sys.argv) > 1 else "golden"
    extra = {}
    if prof == "golden":
        dirs = golden()
    elif prof == "perf":
        dirs, n = perf(); extra["crs"] = n
    else:
        sys.exit("profile: golden | perf")
    print(json.dumps({"profile": prof, "projects": [str(d) for d in dirs], **extra}))
