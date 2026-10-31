#!/usr/bin/env python3
"""The reporter (shipmiracle/report/*): facts from a real CR log + git + events, templates (golden snapshots from tests/fixtures/report), lint (positive and
one negative per rule, Arabic/RTL survives), writers (CR report in the repo, stage report + digest + index in the state folder), the summary queue
with a fake claude (accept, reject a new number, hedging, too long, timeout, 3 tries, 24 h expiry, daily cap, path escape), the panel data contract,
the guard job registration and the `shipm report` CLI. Temp dirs + SHIPMIRACLE_TEST=1 only; no network, no model.
Run: python3 tests/report_facts_test.py   (UPDATE_GOLDEN=1 rewrites the expected *.md fixtures)"""
import json, os, pathlib, re, shutil, stat, subprocess, sys, tempfile, time

ROOT = pathlib.Path(__file__).resolve().parent.parent
FX = ROOT / "tests" / "fixtures" / "report"
TMP = pathlib.Path(tempfile.mkdtemp(prefix="shipmiracle-report-")).resolve()
HOME, DEV, STATE, CONF, WS = (TMP / n for n in ("home", "dev", "state", "config", "ws"))
ENV = dict(os.environ, SHIPMIRACLE_TEST="1", SHIPMIRACLE_HOME=str(HOME), SHIPMIRACLE_DEV=str(DEV), SHIPMIRACLE_STATE=str(STATE), SHIPMIRACLE_CONFIG=str(CONF), SHIPMIRACLE_WS=str(WS), HOME=str(HOME), TZ="UTC")
for k in ("SHIPMIRACLE_DEBUG", "CLAUDECODE", "SHIPMIRACLE_ENFORCE_OWNER", "SHIPMIRACLE_GOLDEN_CLAUDE"):
    ENV.pop(k, None)
os.environ.update({k: v for k, v in ENV.items() if k.startswith("SHIPMIRACLE_") or k in ("HOME", "TZ")})
time.tzset()
sys.path.insert(0, str(ROOT))
from shipmiracle import config, events, projects  # noqa: E402
from shipmiracle.autopilot import state as ap  # noqa: E402
from shipmiracle.playbook import config as pbcfg, engine, gate, store  # noqa: E402
from shipmiracle.report import clean, facts as F, lint, panel, queue, safe, templates, write  # noqa: E402

REAL = pathlib.Path(os.path.expanduser("~"))
CANARY = [REAL / ".config" / "shipmiracle" / "registry.json", REAL / ".config" / "shipmiracle" / "config.json", REAL / ".claude" / "settings.json", REAL / ".local" / "state" / "shipmiracle" / "v1" / "events.jsonl"]
BEFORE = [(p.stat().st_mtime_ns if p.exists() else None) for p in CANARY]
fails = 0
def check(name, ok, info=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(info)[:900]))
    fails += 0 if ok else 1

def shipm(*args, env=None, cwd=None):
    r = subprocess.run([sys.executable, str(ROOT / "bin" / "shipm")] + list(args), env=env or ENV, capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL, cwd=cwd)
    return r.returncode, r.stdout, r.stderr

def git(d, *a):
    return subprocess.run(["git", "-C", str(d)] + list(a), env=ENV, capture_output=True, text=True, check=True).stdout.strip()

HOME.mkdir(parents=True)
(HOME / ".gitconfig").write_text("[user]\n name = t\n email = t@example.com\n[init]\n defaultBranch = main\n[commit]\n gpgsign = false\n")
(WS / "config").mkdir(parents=True)
(WS / "config" / "flow.json").write_text('{\n  "default": "strict",\n  "projects": {}\n}\n')
STATE.mkdir(parents=True)

def mkproj(name):
    d = DEV / name
    d.mkdir(parents=True)
    subprocess.run(["git", "-C", str(d), "init", "-q"], env=ENV, check=True)
    (d / "a.txt").write_text("1\n")
    git(d, "add", "-A"); git(d, "commit", "-q", "-m", "init")
    return d

A, B, C = mkproj("alpha"), mkproj("beta"), mkproj("gamma")
(STATE / "health.json").write_text(json.dumps({"ts": time.time(), "chats": {"alpha": {"chats": 0}, "beta": {"chats": 0}, "gamma": {"chats": 0}}}))
check("playbook set software (alpha)", shipm("playbook", "set", "type", "software", "--project", "alpha")[0] == 0)
check("playbook set app (beta)", shipm("playbook", "set", "type", "app", "--project", "beta")[0] == 0)
PID = projects.project_id(A)

# ---------------------------------------------------------------- 1. a real CR: log lines, one real commit, events
T0 = 1760000000
SHA = "ab" * 32
base_sha = git(A, "rev-parse", "HEAD")
(A / "src.txt").write_text("x\n"); (A / "b.txt").write_text("y\n")
git(A, "add", "-A"); git(A, "commit", "-q", "-m", "RTL fix on login: mirror the form")
head_sha = git(A, "rev-parse", "HEAD")

TITLE = "إصلاح RTL fix on login"
class Sim:
    def __init__(self, rules, base):
        self.w = engine.new_work(); self.w["project"] = "alpha"; self.r = rules; self.t = T0; self.trs = []; self.base = base
    def tick(self, n=60):
        self.t += n; return self.t
    def ev(self, kind, by=None, **data):
        return {"kind": kind, "data": data, "by": by or data.get("role") or "x", "ts": self.tick()}
    def adv(self, cr, stage, kind, by=None, **data):
        self.trs += engine.advance(self.w, cr["id"], stage, self.ev(kind, by, **data), self.r)
    def fail(self, cr, **data):
        self.trs += engine.fail(self.w, cr["id"], "verify", self.ev("qa_fail", "verifier", **data), self.r)

rules = gate.stage_rules(str(A))
check("alpha has trusted rules (software)", rules is not None and rules["type"] == "software" and rules["trusted"], rules and rules.get("reason"))
s = Sim(rules, base_sha)
cr, trs = engine.open_cr(s.w, TITLE, "owner", s.tick(), lane="full", base=base_sha, rules=rules, kind="cli_open"); s.trs += trs
s.adv(cr, "scope", "role_stop", "scoper", role="scope")
s.adv(cr, "plan", "plan_presented", "planner", plan_sha=SHA, role_ts=s.t)
s.t += 480
s.adv(cr, "approve", "owner_prompt", "owner", owner_words=True)
s.adv(cr, "do", "role_stop", "builder-frontend", role="build", diff={"files": 2, "lines": 20, "risk": [], "deps": False})
s.fail(cr, counts={"passed": 212, "failed": 2, "total": 214}, evidence="npm test -> 212 passed, 2 failed", cmd="npm test", failed=["tests/login.rtl.test.ts:41", "tests/login.rtl.test.ts:77 ‮"],
       not_verified="screenshots at 375 px")
s.adv(cr, "do", "role_stop", "builder-frontend", role="build", diff={"files": 2, "lines": 22, "risk": [], "deps": False})
s.adv(cr, "verify", "qa_pass", "verifier", counts={"passed": 214, "failed": 0, "total": 214}, evidence="`npm test` -> 214 passed, 0 failed", cmd="npm test",
      not_verified="real device RTL rendering")
s.adv(cr, "review", "review_verdict", "reviewer", lens="correctness", verdict="ACCEPT")
s.adv(cr, "deliver", "git_delivered", "lead")
s.adv(cr, "learn", "status_dated", "lead"); s.adv(cr, "learn", "report_written", "lead")
store.append(A, s.trs, base=STATE)
(STATE / "alpha.agents.json").write_text(json.dumps({"x1": {"type": "verifier", "model": "claude-sonnet-4-5", "started": T0}, "x2": {"type": "planner", "model": "claude-opus-4-1", "started": T0}}))
CHARTER_SHA = "c1" * 32
for i, (st, rule, det) in enumerate((("do", "continue", "build next"), ("approve", "charter_approve", "plan matches charter ch-c1c1c1c1"))):
    events.append("auto_decision", {"cr": "CR-001", "stage": st, "rule": rule, "charter_sha": CHARTER_SHA, "detail": det}, project=PID, src="autopilot", base=STATE)
events.append("auto_decision", {"cr": "CR-009", "stage": "do", "rule": "continue", "charter_sha": CHARTER_SHA, "detail": "other CR"}, project=PID, src="autopilot", base=STATE)

f = F.build(A, "CR-001", STATE, now=T0 + 99999)
cr_ = f["cr"]
check("facts: project, type, lang, cr id/title/lane/status", f["project"] == "alpha" and f["type"] == "software" and f["lang"] == "en" and cr_["id"] == "CR-001" and cr_["title"] == TITLE
      and cr_["lane"] == "full" and cr_["status"] == "delivered" and cr_["verified"] is True, cr_)
check("facts: stages with status, by, ts and model family from agents.json", [x["id"] for x in f["stages"]] == list(F.ORDER)
      and next(x for x in f["stages"] if x["id"] == "plan")["by"] == "planner" and next(x for x in f["stages"] if x["id"] == "plan")["model"] == "opus"
      and next(x for x in f["stages"] if x["id"] == "verify")["model"] == "sonnet" and next(x for x in f["stages"] if x["id"] == "do")["model"] is None, f["stages"])
vs = f["verdicts"]
check("facts: verdicts FAIL(1) then PASS(2) then review ACCEPT, with counts, evidence, failed, not_verified",
      [(v["stage"], v["verdict"], v["attempt"]) for v in vs] == [("verify", "FAIL", 1), ("verify", "PASS", 2), ("review", "ACCEPT", 1)]
      and vs[0]["counts"] == {"passed": 212, "failed": 2, "total": 214} and vs[0]["evidence"].startswith("npm test ->") and vs[0]["not_verified"] == "screenshots at 375 px"
      and vs[2]["lens"] == "correctness", vs)
check("facts: failed names are cleaned (bidi override removed) and limited", vs[0]["failed"] == ["tests/login.rtl.test.ts:41", "tests/login.rtl.test.ts:77"], vs[0]["failed"])
check("facts: owner wait = plan -> approve (8 min + the 60 s tick)", f["owner_waits"]["n"] == 1 and 480 <= f["owner_waits"]["secs"] <= 600, f["owner_waits"])
check("facts: git base/head/commits/files from the real repository, pushed false (no upstream)", f["git"]["base"] == base_sha and f["git"]["head"] == head_sha
      and [c["subject"] for c in f["git"]["commits"]] == ["RTL fix on login: mirror the form"] and f["git"]["files"] == ["b.txt", "src.txt"] and f["git"]["files_total"] == 2
      and f["git"]["pushed"] is False, f["git"])
check("facts: auto_decisions filtered by CR (CR-009 left out), charter id from the sha when the registry holds none",
      [d["rule"] for d in f["auto_decisions"]] == ["continue", "charter_approve"] and f["charter"] and f["charter"]["id"] == "ch-c1c1c1c1", (f["auto_decisions"], f["charter"]))
check("facts: tokens null (not measured), wall time from the first line to the close", f["tokens"] is None and f["wall_s"] > 0, f["wall_s"])
check("facts: JSON-serialisable", json.loads(json.dumps(f)) == f)
f2 = F.build(A, None, STATE)
check("facts: no cr id -> the newest CR; project without any CR -> cr None", f2["cr"]["id"] == "CR-001" and F.build(B, None, STATE)["cr"] is None and F.build(C, None, STATE)["cr"] is None)
check("facts: unknown CR id -> cr None (no crash)", F.build(A, "CR-099", STATE)["cr"] is None)

# ---------------------------------------------------------------- 2. templates: golden snapshots from fixed facts
def golden(name, text):
    p = FX / name
    if os.environ.get("UPDATE_GOLDEN") == "1":
        p.write_text(text, encoding="utf-8")
    return p.exists() and p.read_text(encoding="utf-8") == text

def fixed_facts():
    g = json.loads((FX / "facts_cr012.json").read_text(encoding="utf-8"))
    return g
if os.environ.get("UPDATE_GOLDEN") == "1":
    g = json.loads(json.dumps(f))
    g["git"].update(base="1111111111111111111111111111111111111111", head="a1b2c3d4e5f60718293a4b5c6d7e8f9012345678", commits=[{"sha": "a1b2c3d", "subject": "RTL fix on login: mirror the form"}],
                    files=["b.txt", "src.txt"], files_total=2, pushed=True)
    g["generated"] = T0 + 5000; g["cr"]["closed"] = T0 + 3000; g["wall_s"] = 2820; g["owner_waits"] = {"n": 1, "secs": 480}; g["tokens"] = 412000; g["project"] = "sample-app"; g["type"] = "app"
    for d in g["auto_decisions"]:
        d["charter_sha"] = CHARTER_SHA
    (FX / "facts_cr012.json").write_text(json.dumps(g, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
G = fixed_facts()
GF = json.loads(json.dumps(G))                     # the facts as they were at the first FAIL: CR open, test failed once, Build is next
GF["cr"].update(status="open", stage="verify", closed=None, verified=False, verify_fails=1); GF["verdicts"] = GF["verdicts"][:1]
for st_ in GF["stages"]:
    if st_["id"] == "verify":
        st_.update(status="fail:1", ts=GF["verdicts"][0]["ts"])
GF["next"] = {"stage": "do", "label": "Build", "agent": "builder-frontend"}
check("golden: stage report FAIL (verify, attempt 1)", golden("stage_verify_fail.md", templates.stage_report(GF, "verify")), templates.stage_report(GF, "verify"))
check("golden: stage report PASS (verify, attempt 2)", golden("stage_verify_pass.md", templates.stage_report(G, "verify", 2)), templates.stage_report(G, "verify", 2))
check("golden: stage report PASS (review)", golden("stage_review_pass.md", templates.stage_report(G, "review")), templates.stage_report(G, "review"))
check("golden: stage report NOT TESTED (plan)", golden("stage_plan.md", templates.stage_report(G, "plan")), templates.stage_report(G, "plan"))
check("golden: CR report with Charter and Decisions", golden("cr_delivered.md", templates.cr_report(G)), templates.cr_report(G))
G0 = json.loads(json.dumps(G)); G0["auto_decisions"] = []; G0["charter"] = None; G0["tokens"] = None
check("golden: CR report with 0 auto-decisions, tokens not measured, Summary text", golden("cr_plain.md", templates.cr_report(G0, "Login form now mirrors in RTL.\nTests pass: 214.")), templates.cr_report(G0, "x"))
GA = json.loads(json.dumps(G0)); GA["cr"].update(status="abandoned", verified=False); GA["verdicts"] = GA["verdicts"][:1]
for st_ in GA["stages"]:
    if st_["id"] == "verify":
        st_["status"] = "fail:1"
    elif st_["id"] in ("review", "deliver", "learn"):
        st_.update(status="next", by=None, ts=None)
GA["git"].update(commits=[], files=[], files_total=0, pushed=False)
check("golden: abandoned CR report (BLOCKED after a FAIL)", golden("cr_abandoned.md", templates.cr_report(GA)), templates.cr_report(GA))
rows = [{"project": "sample-app", "delivered": ["CR-012"], "pass": 1, "open": {"id": "CR-013", "stage": "Plan"}, "waiting": "approve the plan", "queue": 0},
        {"project": "alpha", "delivered": [], "pass": 0, "open": None, "waiting": None, "queue": 1}]
check("golden: digest", golden("digest.md", templates.digest("2025-10-09", rows)), templates.digest("2025-10-09", rows))
txt = templates.cr_report(G)
check("template: header carries the (Arabic) title and survives a UTF-8 round trip", txt.splitlines()[0] == "# CR-001 %s · DELIVERED · PASS" % TITLE and txt.encode("utf-8").decode("utf-8") == txt)
fs_ = {n: (FX / n).read_text(encoding="utf-8") for n in ("stage_verify_fail.md", "stage_verify_pass.md", "stage_review_pass.md", "stage_plan.md", "cr_delivered.md", "cr_plain.md", "cr_abandoned.md", "digest.md")}
for n, t in fs_.items():
    check("lint: golden %s is clean" % n, lint.lint_text(t) == [], lint.lint_text(t))
check("template: stage FAIL names the failures and the next step", "Failed: tests/login.rtl.test.ts:41, tests/login.rtl.test.ts:77" in fs_["stage_verify_fail.md"] and "Next: " in fs_["stage_verify_fail.md"], fs_["stage_verify_fail.md"])
check("template: evidence from facts with no captured text falls back to an engine line that still passes lint",
      lint.lint_text(templates.cr_report({**G0, "verdicts": []})) == [] and "test output not captured" in templates.cr_report({**G0, "verdicts": []}))

# ---------------------------------------------------------------- 3. lint: one negative per rule
CRT = fs_["cr_delivered.md"]; ST = fs_["stage_verify_fail.md"]; DG = fs_["digest.md"]
def bad(text, needle):
    p = lint.lint_text(text)
    return any(needle in x for x in p), p
def neg(name, text, needle):
    ok, p = bad(text, needle)
    check("lint negative: " + name, ok, p)
neg("unknown header", "# Hello\nVerdict: PASS\n", "header")
neg("wrong verdict word", ST.replace("· FAIL", "· MAYBE", 1), "header")
neg("verdict line differs from the header word", ST.replace("Verdict: FAIL", "Verdict: PASS", 1), "Verdict line")
neg("field order", CRT.replace("Rollback:", "Zzz:").replace("Files:", "Rollback: git revert x1\nFiles:", 1), "")
lines_ = CRT.rstrip("\n").split("\n")
swapped = "\n".join([lines_[0], lines_[2], lines_[1]] + lines_[3:]) + "\n"
neg("Summary after Stages is out of order", swapped, "out of order")
neg("more than 40 lines", CRT.rstrip("\n") + "\n" + "\n".join("  x" for _ in range(40)) + "\n", "lines (max 40)")
neg("Evidence without backticks", CRT.replace("`npm test` ->", "npm test ->"), "Evidence")
neg("Evidence without a number or file", re.sub(r"Evidence: .*", "Evidence: `npm test` -> all good", CRT, 1), "Evidence")
neg("Evidence without ->", re.sub(r"Evidence: .*", "Evidence: `npm test` 214 passed", CRT, 1), "Evidence")
neg("Not verified missing", "\n".join(l for l in CRT.split("\n") if not l.startswith("Not verified")), "Not verified")
neg("Not verified empty", re.sub(r"Not verified: .*", "Not verified:", CRT), "Not verified")
neg("Summary of 4 lines", CRT.replace("Summary: pending", "Summary: a1\n  b2\n  c3\n  d4"), "Summary is 4")
for w_ in ("should work", "probably", "seems", "your call", "I think"):
    neg("banned wording %r" % w_, CRT.replace("Summary: pending", "Summary: it %s fine" % w_), "banned")
neg("banned wording in a stage report", ST.replace("Next:", "Next: your call -", 1), "banned")
neg("Decisions line malformed", CRT.replace("  09:", "  9:", 1) if "  09:" in CRT else CRT.replace("Decisions:\n", "Decisions:\n  bad line\n", 1), "Decisions")
neg("auto-decisions without Charter", re.sub(r"Charter: .*\n", "", CRT), "Charter")
neg("Owner waits without Auto-decisions", re.sub(r" · Auto-decisions: [0-9]+", "", CRT), "Auto-decisions")
neg("blank line", CRT.replace("Stages:", "\nStages:", 1), "blank")
neg("indented line before any field", "# Digest · 2025-10-09\n  x\n", "indented")
neg("missing required field (Rollback)", "\n".join(l for l in CRT.split("\n") if not l.startswith("Rollback")), "Rollback")
neg("digest without project line", "# Digest · 2025-10-09\nTotals: 0 delivered\nNot verified: none\n", "digest has no project line")
neg("carriage return", ST.replace("\n", "\r\n"), "carriage")
check("lint: Arabic everywhere (title, failed names, evidence) passes", lint.lint_text(templates.cr_report({**G0, "cr": {**G0["cr"], "title": "إصلاح الواجهة من اليمين إلى اليسار"}})) == [])
check("clean(): U+2028, bidi overrides and control characters removed, Arabic and ZWNJ kept", clean("a b‮c\x07مرحبا‌") == "abcمرحبا‌", repr(clean("a b‮c\x07مرحبا‌")))
check("safe(): withholds a field with a hedging phrase", safe("it should work") == "" and safe("214 passed") == "214 passed")
big = TMP / "big.md"; big.write_bytes(b"x" * 70000)
check("lint_file: too large / missing / not UTF-8 / symlink are reported, not raised", lint.lint_file(big) and lint.lint_file(TMP / "none.md") == ["file not found"]
      and lint.lint_file((lambda p: (p.write_bytes(b"\xff\xfe"), p)[1])(TMP / "bin.md")) == ["not valid UTF-8"]
      and (lambda p: (p.symlink_to(big), lint.lint_file(p))[1])(TMP / "ln.md")[0].startswith("unreadable"))

# ---------------------------------------------------------------- 4. writers + index
rc, out, err = shipm("config", "set", "guard.jobs", "true")
check("config guard.jobs true (temp config)", rc == 0 and config.get("guard.jobs") is True, (rc, out, err))
p_cr = write.write_cr(A, "CR-001", base=STATE, now=T0 + 5000)
check("write_cr: docs/reports/YYYY-MM-DD-CR-001.md in the repo, 0644, lint clean, Summary pending", p_cr.parent == A / "docs" / "reports" and re.fullmatch(r"20\d\d-\d\d-\d\d-CR-001\.md", p_cr.name)
      and stat.S_IMODE(p_cr.stat().st_mode) == 0o644 and lint.lint_file(p_cr) == [] and "\nSummary: pending\n" in p_cr.read_text(encoding="utf-8"), p_cr)
check("write_cr: the report path is recorded in the CR log (op report) and work.json", any(l["op"] == "report" and l["ev"]["data"].get("path", "").endswith("CR-001.md") for l in store._parse_lines(store._read_log_bytes(store.log_path(A, STATE)))[0]))
try:
    write.write_cr(B, "CR-001", base=STATE); r_ = "no error"
except Exception as e:
    r_ = type(e).__name__
check("write_cr: a project without that CR is refused (UsageError)", r_ == "UsageError", r_)
p_st = write.write_stage(A, "CR-001", "verify", base=STATE, now=T0 + 5000)
check("write_stage: private file in <state>/v1/reports/<pid>/, 0600, lint clean", p_st.parent == STATE / "v1" / "reports" / PID and stat.S_IMODE(p_st.stat().st_mode) == 0o600 and lint.lint_file(p_st) == [], p_st)
p_st2 = write.write_stage(A, "CR-001", "verify", base=STATE, now=T0 + 5000)
check("write_stage twice: second file gets -2 (no overwrite)", p_st2.name == p_st.stem + "-2.md" and p_st.exists())
p_dg = write.write_digest("2025-10-09", [A, B, C], base=STATE)
check("write_digest: <state>/v1/digest/DAY.md lint clean, mentions alpha", p_dg.parent == STATE / "v1" / "digest" and lint.lint_file(p_dg) == [] and "alpha" in p_dg.read_text(encoding="utf-8"), p_dg.read_text())
idx = json.loads((STATE / "v1" / "reports" / "index.json").read_text(encoding="utf-8"))
check("index: v=1, newest first, kinds stage/cr/digest, private flags, title and path", idx["v"] == 1 and {i["kind"] for i in idx["items"]} == {"stage", "cr", "digest"}
      and all(set(i) == {"id", "project", "kind", "cr", "stage", "verdict", "ts", "title", "sub", "path", "private"} for i in idx["items"])
      and [i["private"] for i in idx["items"] if i["kind"] == "cr"] == [False] and all(i["private"] for i in idx["items"] if i["kind"] != "cr"), idx)
write.index_add({"id": "dup", "project": "alpha", "kind": "stage", "cr": "CR-001", "stage": "verify", "verdict": "FAIL", "ts": 1, "title": "t", "sub": "s", "path": str(p_st), "private": True}, STATE)
idx = json.loads((STATE / "v1" / "reports" / "index.json").read_text(encoding="utf-8"))
check("index: the same path is replaced, not duplicated", sum(1 for i in idx["items"] if i["path"] == str(p_st)) == 1 and idx["items"][0]["id"] == "dup")
for i in range(520):
    write.index_add({"id": "x%d" % i, "project": "p", "kind": "stage", "cr": None, "stage": None, "verdict": "PASS", "ts": i, "title": "t", "sub": "", "path": "/x/%d" % i, "private": True}, STATE)
check("index: capped at 500 items", len(json.loads((STATE / "v1" / "reports" / "index.json").read_text())["items"]) == 500)
old = STATE / "v1" / "digest" / "1999-01-01.md"; old.write_text("x"); os.utime(old, (1, 1))
check("prune: removes private reports older than 30 days, keeps the repo report", write.prune(STATE) == 1 and not old.exists() and p_cr.exists())
os.makedirs(B / "docs", exist_ok=True)
rc, out, err = shipm("report", "lint", "--all", "--project", str(A))
check("CLI: report lint --all lints the repo report, stage reports and digests: exit 0", rc == 0 and out.count("PASS ") >= 3 and "FAIL" not in out, (rc, out, err))
bad_file = A / "docs" / "reports" / "bad.md"; bad_file.write_text("# nope\n")
rc, out, err = shipm("report", "lint", str(bad_file))
check("CLI: report lint of a bad file: exit 1 and a reason", rc == 1 and out.startswith("FAIL ") and "header" in out, (rc, out))
bad_file.unlink()

# ---------------------------------------------------------------- 5. the summary queue with a fake claude
FAKE = TMP / "fakebin"; FAKE.mkdir()
def fake(name, body):
    p = FAKE / name
    p.write_text("#!/usr/bin/env python3\nimport json, sys\n" + body)
    p.chmod(0o755)
    return str(p)
DOD = "\\nResult: ok\\nEvidence: `cat facts.json` -> 1\\nFiles: facts.json\\nNot verified: none\\nVerdict: PASS"
claudes = {
    "ok": fake("c_ok", 'print(json.dumps({"is_error": False, "result": "CR-001 delivered after 2 attempts.\\nTests: 214 passed.' + DOD + '"}))'),
    "newnum": fake("c_new", 'print(json.dumps({"is_error": False, "result": "999 tests passed.' + DOD + '"}))'),
    "long": fake("c_long", 'print(json.dumps({"is_error": False, "result": "a\\nb\\nc\\nd' + DOD + '"}))'),
    "hedge": fake("c_hedge", 'print(json.dumps({"is_error": False, "result": "It probably works.' + DOD + '"}))'),
    "err": fake("c_err", 'print(json.dumps({"is_error": True, "result": ""}))'),
    "junk": fake("c_junk", 'print("not json")'),
    "sleep": fake("c_sleep", 'import time\ntime.sleep(30)'),
}
def new_job(now=None):
    return write.write_cr(A, "CR-001", base=STATE, now=int(time.time()))
shutil.rmtree(STATE / "v1" / "report-queue", ignore_errors=True)
def jobs():
    return queue._jobs(STATE)
rp = new_job()
js = jobs()
check("queue: write_cr (guard.jobs on) enqueued one pending job with facts.json (0600)", len(js) == 1 and js[0][2]["status"] == "pending" and stat.S_IMODE((js[0][1] / "facts.json").stat().st_mode) == 0o600
      and queue.has_pending(STATE), js)
qfacts = json.loads((js[0][1] / "facts.json").read_text(encoding="utf-8"))
check("queue: facts.json is the slim, flat summary (title, stages, verdicts, counts)", qfacts["cr"] == "CR-001" and qfacts["title"] == TITLE and qfacts["owner_waits"] == 1 and qfacts["auto_decisions"] == 2 and "git" not in qfacts, qfacts)
NOW = int(time.time())
def run(kind, now=None):
    os.environ["SHIPMIRACLE_GOLDEN_CLAUDE"] = claudes[kind]
    return queue.run_one(STATE, now or NOW)
r = run("newnum")
check("queue: a summary with a new number (999) is rejected, job stays pending, report untouched", r["outcome"] == "retry" and "999" in r["why"] and "Summary: pending" in rp.read_text(encoding="utf-8"), r)
r = run("long")
check("queue: 4 summary lines rejected", r["outcome"] == "retry" and "4 summary lines" in r["why"], r)
r = run("hedge")
check("queue: hedging wording rejected (3rd try -> Summary: not generated)", r["outcome"] == "not_generated" and "Summary: not generated" in rp.read_text(encoding="utf-8") and lint.lint_file(rp) == [], r)
check("queue: after giving up the job is failed and no longer pending", jobs()[0][2]["status"] == "failed" and not queue.has_pending(STATE))
rp = new_job()
r = run("ok")
txt = rp.read_text(encoding="utf-8")
check("queue: accepted summary replaces 'Summary: pending' (2 lines, indented continuation), report still lints", r["outcome"] == "done" and "Summary: CR-001 delivered after 2 attempts.\n  Tests: 214 passed.\n" in txt and lint.lint_file(rp) == [], (r, txt[:300]))
check("queue: job done with done_ts; report mode stays 0644", [j for _c, _d, j in jobs() if j["status"] == "done"] and stat.S_IMODE(rp.stat().st_mode) == 0o644)
rp = new_job(); queue.run_one  # fresh pending job
os.environ["SHIPMIRACLE_GOLDEN_CLAUDE"] = claudes["err"]
r = queue.run_one(STATE, NOW)
check("queue: model error -> retry", r["outcome"] == "retry", r)
os.environ["SHIPMIRACLE_GOLDEN_CLAUDE"] = claudes["junk"]
r = queue.run_one(STATE, NOW)
check("queue: unparseable output -> retry", r["outcome"] == "retry" and "unparseable" in r["why"], r)
queue.TIMEOUT_S = 1
os.environ["SHIPMIRACLE_GOLDEN_CLAUDE"] = claudes["sleep"]
t0 = time.time(); r = queue.run_one(STATE, NOW)
check("queue: timeout -> 'Summary: not generated' on the 3rd failure, within the budget", r["outcome"] == "not_generated" and r["why"] == "timeout" and time.time() - t0 < 20 and "Summary: not generated" in rp.read_text(encoding="utf-8"), (r, time.time() - t0))
queue.TIMEOUT_S = 100
rp = new_job()
r = queue.run_one(STATE, NOW + 25 * 3600, ask=lambda d: (_ for _ in ()).throw(AssertionError("no model call after 24 h")))
check("queue: a job older than 24 h is not asked, its line becomes 'not generated'", r["outcome"] == "not_generated" and "Summary: not generated" in rp.read_text(encoding="utf-8"), r)
rp = new_job()
os.environ["SHIPMIRACLE_GOLDEN_CLAUDE"] = claudes["ok"]
done_before = sum(1 for _c, _d, j in jobs() if j.get("done_ts"))
for _c, d, j in jobs():                                   # simulate 20 summaries done today
    pass
for i in range(20):
    d = STATE / "v1" / "report-queue" / ("fake%d" % i); d.mkdir(parents=True)
    (d / "job.json").write_text(json.dumps({"v": 1, "id": "fake%d" % i, "created": NOW - 100, "report": "/x", "status": "done", "done_ts": NOW - 10, "tries": 0}))
r = queue.run_one(STATE, NOW)
check("queue: at most 20 summaries a day", r["outcome"] == "capped" and "Summary: pending" in rp.read_text(encoding="utf-8"), r)
for i in range(20):
    shutil.rmtree(STATE / "v1" / "report-queue" / ("fake%d" % i))
# a job whose report path points outside docs/reports
evil = TMP / "evil.md"; evil.write_text("# x\nSummary: pending\n")
for _c, d, j in jobs():
    if j["status"] == "pending":
        j["report"] = str(evil); (d / "job.json").write_text(json.dumps(j))
r = queue.run_one(STATE, NOW)
check("queue: a report path outside docs/reports is refused and the file untouched", r["outcome"] == "retry" and evil.read_text() == "# x\nSummary: pending\n", r)
for _c, d, j in jobs():
    (d / "job.json").write_text(json.dumps(dict(j, created=NOW - 8 * 86400)))
check("queue: prune deletes jobs older than 7 days", queue.prune(STATE, NOW) >= 1 and not any(True for _c, _d, j in jobs() if j.get("created", 0) < NOW - 7 * 86400))
os.environ.pop("SHIPMIRACLE_GOLDEN_CLAUDE", None)
check("queue.job(): never raises, returns a word", isinstance(queue.job(), str))
rc, out, err = shipm("config", "set", "guard.jobs", "false")
rp_off = write.write_cr(A, "CR-001", base=STATE, now=T0 + 5000)
check("write_cr with guard.jobs off: the line says 'not generated' at once and nothing is queued", "Summary: not generated" in rp_off.read_text(encoding="utf-8") and not queue.has_pending(STATE))

# ---------------------------------------------------------------- 6. guard job registration
sys.path.insert(0, str(ROOT))
from shipmiracle.guard import jobs as J  # noqa: E402
tbl = {j.name: j for j in J.default_jobs(ROOT)}
check("guard: job report_summaries (interval 300 s, budget 120 s, nothing on low battery, gated on a pending job)", "report_summaries" in tbl and tbl["report_summaries"].interval == 300
      and tbl["report_summaries"].budget == 120 and tbl["report_summaries"].low_interval >= 86400 and tbl["report_summaries"].gate is not None and tbl["report_summaries"].gate() is False)
check("guard: low battery means the job is never due", J.due([tbl["report_summaries"]], 1e9, {"on_ac": False, "battery_pct": 5}) == [])

# ---------------------------------------------------------------- 7. panel data contract
pd_ = panel.data(A, STATE)
check("panel: playbook {type, level, autopilot, trusted, valid}", pd_["playbook"] == {"type": "software", "level": "strict", "autopilot": "guided", "trusted": True, "valid": True}, pd_["playbook"])
check("panel: stageLabels for the 7 stages (approve = OK)", pd_["stageLabels"] and set(pd_["stageLabels"]) == {"scope", "plan", "approve", "do", "verify", "review", "deliver"} and pd_["stageLabels"]["approve"] == "OK", pd_["stageLabels"])
check("panel: cr list, newest finished, last verdict word and label", pd_["cr"][0]["id"] == "CR-001" and pd_["cr"][0]["status"] == "delivered" and pd_["cr"][0]["verdict"] == "ACCEPT" and pd_["cr"][0]["title"] == TITLE
      and set(pd_["cr"][0]) == {"id", "title", "status", "stage", "lane", "label", "verdict", "waiting_on", "in_chat"}, pd_["cr"])
check("panel: lastVerdict {stage, word, counts, report}", pd_["lastVerdict"] and set(pd_["lastVerdict"]) == {"stage", "word", "counts", "report"} and pd_["lastVerdict"]["word"] == "ACCEPT"
      and pd_["lastVerdict"]["report"].endswith("CR-001.md"), pd_["lastVerdict"])
check("panel: nextAction null when no CR is active; autopilot null with no state file", pd_["nextAction"] is None and pd_["autopilot"] is None)
rc, out, err = shipm("cr", "open", "second request", "--lane", "full", "--project", "alpha")
rc, out, err = shipm("cr", "open", "third request", "--project", "alpha")
rc, out, err = shipm("report", "panel", "--project", str(A))
pj = json.loads(out)
check("panel CLI: active CR first with waiting_on and the engine's next text, queued second", rc == 0 and pj["cr"][0]["status"] == "open" and pj["cr"][0]["waiting_on"] in ("lead", "owner", "none") and pj["cr"][1]["status"] == "queued"
      and pj["nextAction"].startswith("CR-002:") and len(pj["cr"]) <= 5, pj)
ap.update(PID, lambda cur: ap.blank("a" * 64, int(time.time()) - 60), base=STATE)
pj = panel.data(A, STATE)
check("panel: autopilot = shipmiracle.autopilot.state.snapshot when the state file exists", pj["autopilot"] and pj["autopilot"]["state"] == "set" and pj["autopilot"]["charter"] is None and set(pj["autopilot"]) >= {"state", "level", "enabled", "charter", "decisions", "budget", "time", "stop", "cr", "branch", "worktree", "ended_reason"}, pj["autopilot"])
pn = panel.data(C, STATE)
check("panel: a project with no playbook -> playbook/cr/stageLabels/nextAction/lastVerdict null or empty", pn["playbook"] is None and pn["cr"] == [] and pn["stageLabels"] is None and pn["nextAction"] is None and pn["lastVerdict"] is None and pn["autopilot"] is None, pn)
def tree(root):
    return sorted((str(q), q.stat().st_mtime_ns) for q in pathlib.Path(root).rglob("*") if q.is_file())
snap_ = (tree(STATE), tree(A))
panel.data(A, STATE); panel.data(C, STATE)
check("panel: remote = {state} read-only from the user-level settings, and no ask field for an ordinary project (F4 data contract)", pd_["remote"]["state"] in ("on", "off", "unknown") and set(pd_["remote"]) == {"state"} and "ask" not in pd_ and "ask" not in pn, (pd_.get("remote"), list(pd_)))
check("panel: read-only (no file in the state folder or the project changed or appeared)", (tree(STATE), tree(A)) == snap_)

# panel: an open CR whose test failed once is shown at the build stage (build is next again, the rule of facts._next); the second failure blocks it and keeps the verify stage
rules_b = gate.stage_rules(str(B)); sb = Sim(rules_b, git(B, "rev-parse", "HEAD")); sb.w["project"] = "beta"
cr_b = engine.open_cr(sb.w, "Fail once", "owner", sb.tick(), lane="full", base=sb.base, rules=rules_b, kind="cli_open")
sb.trs += cr_b[1]; cr_b = cr_b[0]
sb.adv(cr_b, "scope", "role_stop", "scoper", role="scope"); sb.adv(cr_b, "plan", "plan_presented", "planner", plan_sha=SHA, role_ts=sb.t); sb.adv(cr_b, "approve", "owner_prompt", "owner", owner_words=True)
sb.adv(cr_b, "do", "role_stop", "builder", role="build", diff={"files": 1, "lines": 5, "risk": [], "deps": False})
sb.fail(cr_b, counts={"passed": 1, "failed": 1, "total": 2}, evidence="t -> 1 failed", cmd="t")
store.append(B, sb.trs, base=STATE); sb.trs = []
pb1 = panel.data(B, STATE)["cr"][0]
check("panel: a CR whose test failed once is at the build stage (stage do, label of do, verdict FAIL, still open)", pb1["status"] == "open" and pb1["stage"] == "do" and pb1["label"] == rules_b["labels"]["do"] and pb1["verdict"] == "FAIL", pb1)
sb.adv(cr_b, "do", "role_stop", "builder", role="build", diff={"files": 1, "lines": 6, "risk": [], "deps": False})
store.append(B, sb.trs, base=STATE); sb.trs = []
check("panel: after the rebuild the test is next again (stage verify, verdict still FAIL until it passes)", panel.data(B, STATE)["cr"][0]["stage"] == "verify", panel.data(B, STATE)["cr"][0])
sb.fail(cr_b, counts={"passed": 1, "failed": 1, "total": 2}, evidence="t -> 1 failed", cmd="t")
store.append(B, sb.trs, base=STATE)
pb2 = panel.data(B, STATE)["cr"][0]
check("panel: failed twice = blocked, the verify stage is kept, verdict BLOCKED", pb2["status"] == "blocked" and pb2["stage"] == "verify" and pb2["verdict"] == "BLOCKED", pb2)

# the index id is unique across projects (two projects both have a CR-001 verify report on the same day) and made of panel-safe characters
ids_ = [i["id"] for i in json.loads((STATE / "v1" / "reports" / "index.json").read_text(encoding="utf-8"))["items"]]
check("index: ids are unique and start with the project name; only [A-Za-z0-9._-]", len(ids_) == len(set(ids_)) and all(re.fullmatch(r"[A-Za-z0-9._-]{1,120}", i) for i in ids_) and any(i.startswith("alpha-") for i in ids_ if not i.startswith("digest-")), ids_[:5])
check("index: _rid keeps ids of different projects apart and cleans odd characters", write._rid("a", "2026-10-21-CR-001-verify") != write._rid("b", "2026-10-21-CR-001-verify") and write._rid("my proj/é", "x") == "my_proj__-x" and len(write._rid("p" * 300, "x")) == 120)

# ---------------------------------------------------------------- 8. CLI
rc, out, err = shipm("report", "facts", "CR-001", "--project", str(A))
check("CLI report facts: JSON of the facts", rc == 0 and json.loads(out)["cr"]["id"] == "CR-001", (rc, err))
rc, out, err = shipm("report", "stage", "CR-001", "verify", "--project", str(A))
check("CLI report stage: prints the template (header + Verdict)", rc == 0 and out.startswith("# CR-001 · ") and "\nVerdict: " in out and lint.lint_text(out) == [], out)
rc, out, err = shipm("report", "cr", "CR-001", "--project", str(A))
check("CLI report cr: prints the CR report", rc == 0 and out.splitlines()[0].startswith("# CR-001 ") and lint.lint_text(out) == [], out)
rc, out, err = shipm("report", "cr", "CR-002", "--project", str(A), "--write")
check("CLI report cr --write of an unfinished CR: exit 2", rc == 2, (rc, err))
rc, out, err = shipm("report", "stage", "CR-001", "bogus", "--project", str(A))
check("CLI report stage with a bad stage: exit 2", rc == 2, (rc, err))
rc, out, err = shipm("report", "facts", "nope", "--project", str(A))
check("CLI report facts with a bad id: exit 2", rc == 2, (rc, err))
rc, out, err = shipm("report", "lint")
check("CLI report lint without a file: exit 2", rc == 2, (rc, err))
rc, out, err = shipm("report", "digest", "--day", "2025-10-09")
check("CLI report digest: prints, lint clean", rc == 0 and out.startswith("# Digest · 2025-10-09") and lint.lint_text(out) == [], out)
rc, out, err = shipm("report", "digest", "--day", "9/10")
check("CLI report digest with a bad day: exit 2", rc == 2, (rc, err))
rc, out, err = shipm("report", "stage", "CR-001", "verify", "--write", "--project", str(A))
check("CLI report stage --write prints the stored path", rc == 0 and out.strip().endswith(".md") and pathlib.Path(out.strip()).exists(), (rc, out, err))
check("isolation: the real registry/config/settings files were not touched", [(p.stat().st_mtime_ns if p.exists() else None) for p in CANARY] == BEFORE)

print("\nFAILED %d" % fails if fails else "\nALL PASS")
sys.exit(1 if fails else 0)
