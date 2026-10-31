#!/usr/bin/env python3
"""Stage parity (P5b T5, spec section 9 'Parity'): the stage module must not change what the gate (flow) decides.
A. Every flow suite that runs through the shared fixture (scenarios, verdict, roles, indexerror, p4, playbook) is run twice through the dispatcher
   shim tests/fixtures/stage/hook.sh (flow slot + stage slot, the playbook forced on for every project): once with the stage engine `legacy` (stage
   inert) and once with `playbook` (stage tracks CRs and may refuse). The suite sees flow's result alone, so identical PASS/FAIL lines in both runs
   (and no FAIL beyond the ones the suite already has) prove flow's decisions are byte-for-byte what they were; the recorded stage results show the
   engine really ran and that everything it said is on the allowlist (the five new refusal kinds and the CR context lines).
   (flow_gate_test.py drives the gate script directly and flow_gate_bash_test.py reads the gate source: neither goes through a dispatcher slot, and
   the stage slot never matches PreToolUse Bash/Edit/Write, which stage_hook_test 11a/11b assert.)
B. End to end through the real shim with the MERGED output (flow + stage): `python -c "open('.shipmiracle/playbook.json','w')"` (literal) is refused; a forged
   .shipmiracle/work.json is reported (cr.work_forged) and ignored; switching gate.engine in the middle of a turn trips flow's integrity check while the stage
   module follows the new value from the next call.
Run: python3 tests/stage_parity_test.py   (about 3 minutes: the roles suite alone takes 2.5)"""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import shipmiracle_isolation; shipmiracle_isolation.apply_to_environ()   # test isolation: fresh HOME/SHIPMIRACLE_HOME/CONFIG/STATE unless already temp
import concurrent.futures, json, os, pathlib, re, subprocess, sys, tempfile, time

ROOT = pathlib.Path(__file__).resolve().parent.parent
SHIM = ROOT / "tests/fixtures/stage/hook.sh"
os.environ["SHIPMIRACLE_TEST_HOOK"] = str(SHIM)
sys.path.insert(0, str(ROOT / "tests"))
fails = 0


def check(name, ok, info=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(info)[:900]))
    fails += 0 if ok else 1


SUITES = ["flow_gate_scenarios_test", "flow_gate_verdict_test", "flow_gate_roles_test", "flow_gate_indexerror_test", "flow_gate_p4_test", "flow_gate_playbook_test"]
# the stage module may say exactly these things (kind -> a phrase of its text); anything else recorded is a parity failure
BLOCK_PHRASES = ("plan is not approved", "needs review before it can finish", "Next:", "on hold", "is blocked")
CTX_RX = re.compile(r"^CR-\d{3,6}: ")
TMP = pathlib.Path(tempfile.mkdtemp(prefix="stage-parity-")).resolve()


def norm(ln):
    """A result line without the parts that differ between two runs: the temp paths, timings and counts."""
    ln = re.sub(r" ::.*$", "", ln)
    ln = re.sub(r"/(?:private/)?(?:var/folders|tmp)/\S*", "<path>", ln)
    return re.sub(r"\d+(?:\.\d+)?", "N", ln).strip()


def run_suite(name, engine):
    rec = TMP / ("%s.%s.jsonl" % (name, engine))
    env = dict(os.environ, SHIPMIRACLE_TEST_HOOK=str(SHIM), SHIPMIRACLE_STAGE_ENGINE=engine, SHIPMIRACLE_STAGE_FORCE="1", SHIPMIRACLE_STAGE_RECORD=str(rec), SHIPMIRACLE_TEST="1")
    env.pop("SHIPMIRACLE_GATE_ENGINE", None)
    r = subprocess.run([sys.executable, str(ROOT / "tests" / (name + ".py"))], env=env, capture_output=True, text=True, timeout=800)
    lines = sorted(norm(ln) for ln in r.stdout.splitlines() if ln.startswith(("PASS ", "FAIL ")))
    recs = []
    if rec.exists():
        for ln in rec.read_text().splitlines():
            try:
                recs.append(json.loads(ln))
            except ValueError:
                pass
    return name, engine, r.returncode, lines, recs


t0 = time.time()
jobs = [(s, e) for s in SUITES for e in ("legacy", "playbook")]
res = {}
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
    for name, engine, code, lines, recs in ex.map(lambda a: run_suite(*a), jobs):
        res[(name, engine)] = (code, lines, recs)
tot_stage = tot_block = tot_ctx = 0
for s in SUITES:
    (c1, l1, r1), (c2, l2, r2) = res[(s, "legacy")], res[(s, "playbook")]
    check("A %s: legacy and playbook engines give the same PASS/FAIL lines (%d checks)" % (s, len(l1)), l1 == l2 and len(l1) > 0, [x for x in l2 if x not in l1][:3] or [x for x in l1 if x not in l2][:3])
    check("A %s: same exit code in both" % s, c1 == c2, (c1, c2))
    check("A %s: stage inert under the legacy engine (no stage output recorded)" % s, all(r["stage"] is None for r in r1), [r for r in r1 if r["stage"]][:1])
    bad = []
    for r in r2:
        st = r["stage"]
        if not st:
            continue
        tot_stage += 1
        if st["block"]:
            tot_block += 1
            if not (st["reason"].startswith("TEAM FLOW (change request): ") and any(p in st["reason"] for p in BLOCK_PHRASES)):
                bad.append(st)
        if st["ctx"]:
            tot_ctx += 1
            if not (CTX_RX.match(st["ctx"]) or st["ctx"].startswith("TEAM FLOW (warn-only project)")):
                bad.append(st)
        if st["sys"] and not st["sys"].startswith("TEAM FLOW (warn-only project)"):
            bad.append(st)
    check("A %s: everything the stage module said is on the allowlist" % s, not bad, bad[:2])
print("INFO suites: %d stage results (%d blocks, %d contexts) over %d recorded calls, %.0f s" % (
    tot_stage, tot_block, tot_ctx, sum(len(res[(s, 'playbook')][2]) for s in SUITES), time.time() - t0))
check("A the engine really ran under the flow suites (at least one allowlisted stage refusal recorded)", tot_block >= 1, tot_block)

# ====================================================================== B. end to end, merged output
os.environ["SHIPMIRACLE_STAGE_SHIM"] = "merged"
import flow_fixture as F  # noqa: E402  (HOOK = the shim, because SHIPMIRACLE_TEST_HOOK is set)
from flow_fixture import deny, text  # noqa: E402

REFUSAL = "ask the owner to change them"


def mk(engine_file=None):
    p = F.make_project()
    p.ENV.update(SHIPMIRACLE_STAGE_SHIM="merged", SHIPMIRACLE_STAGE_FORCE="1")
    p.ENV.pop("SHIPMIRACLE_STAGE_ENGINE", None)
    cfg = p.T / "cfg"
    cfg.mkdir()
    p.ENV["SHIPMIRACLE_CONFIG"] = str(cfg)
    p.CFG = cfg
    (p.T / "sbx-home").mkdir(exist_ok=True)
    p.ENV["HOME"] = str(p.T / "sbx-home")          # a complete temp sandbox: the dispatcher honours SHIPMIRACLE_STATE only then (P6 sec M4)
    (cfg / "config.json").write_text(json.dumps({"gate.engine": engine_file or "playbook"}))
    return p


def vlog(p):
    out = []
    f = p.STATE / "v1" / "events.jsonl"
    if f.exists():
        out = [json.loads(x) for x in f.read_text().splitlines() if x.strip()]
    return out


p = mk()
(p.P / ".shipmiracle").mkdir()
(p.P / ".shipmiracle/playbook.json").write_text('{"v":1}')
p.prompt()
for cmd in ("python -c \"open('.shipmiracle/playbook.json','w').write('x')\"", "python3 -c \"open('.shipmiracle/playbook.json', 'w').write('x')\"",
            "python3 -c 'open(\".shipmiracle/work.json\",\"w\")'", "python3 -c \"open('%s/.shipmiracle/playbook.json','w').write('x')\"" % p.P):
    check("B tamper (engine=playbook, merged): %s refused" % cmd[:60], deny(p.bash(cmd)) and REFUSAL in text(p.bash(cmd)), p.bash(cmd))
    check("B tamper: the same for an agent: %s" % cmd[:40], deny(p.pre("Bash", {"command": cmd}, agent="backend-engineer")))
check("B tamper: the file is untouched", (p.P / ".shipmiracle/playbook.json").read_text() == '{"v":1}')
check("B tamper: a harmless python -c is not refused", not deny(p.bash("python3 -c \"print(1)\"")))

# forged work.json, end to end (the CR is opened by a build stop; the file is forged; the next Stop reports it)
q = mk()
q.prompt("go")
q.put("src/app.py", "x = 1\ny = 2\nz = 3\n")
q.sub_stop("backend-engineer")
w = q.P / ".shipmiracle" / "work.json"
check("B forged: a build stop opened CR-001 and rendered .shipmiracle/work.json", w.exists() and json.loads(w.read_text())["active"] == "CR-001", w.exists())
doc = json.loads(w.read_text())
doc["crs"][0]["stages"]["verify"] = "done:qa-engineer"
doc["crs"][0]["stages"]["review"] = "done:independent-reviewer"
w.write_text(json.dumps(doc))
q.stop()
check("B forged: cr.work_forged is logged on the next Stop", any(e.get("kind") == "cr.work_forged" for e in vlog(q)), vlog(q)[-3:])
re_ = json.loads(w.read_text())
check("B forged: work.json is rewritten from the log", re_["crs"][0]["stages"]["verify"] == "next", re_["crs"][0]["stages"])

# gate.engine switched in the middle of a turn
r = mk("legacy")
r.prompt("go")
small = dict(tool_name="Edit", tool_input={"file_path": str(r.P / "docs/STATUS.md"), "old_string": "a", "new_string": "b"})
check("B engine switch: baseline passes (engine legacy)", not deny(r.hook("PreToolUse", **small)))
r.put("src/one.py", "a = 1\n")
r.sub_stop("backend-engineer")
check("B engine switch: under legacy the stage module opened no CR", not any((r.STATE / "v1" / "cr").glob("*.jsonl")) if (r.STATE / "v1" / "cr").exists() else True)
(r.CFG / "config.json").write_text(json.dumps({"gate.engine": "playbook"}))
o = r.hook("PreToolUse", **small)
check("B engine switch: switching to playbook mid-turn is refused by flow's integrity check and names gate.engine", deny(o) and "gate.engine" in text(o), o)
r.prompt("ok, I switched it")
check("B engine switch: the owner's next message re-baselines", not deny(r.hook("PreToolUse", **small)))
r.put("src/two.py", "b = 2\n")
r.sub_stop("backend-engineer")
check("B engine switch: from the next call the stage module follows the new value (CR opened)", any((r.STATE / "v1" / "cr").glob("*.jsonl")), "")
(r.CFG / "config.json").write_text(json.dumps({"gate.engine": "legacy"}))
o = r.hook("PreToolUse", **small)
check("B engine switch: switching back is also refused mid-turn", deny(o) and "gate.engine" in text(o), o)

for pr in (p, q, r):
    pr.cleanup()
print("\n%s: %d failed (%.0f s)" % ("FAIL" if fails else "ALL PASS", fails, time.time() - t0))
sys.exit(1 if fails else 0)
