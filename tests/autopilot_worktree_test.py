#!/usr/bin/env python3
"""Phase 6 T5 isolation (spec section 3) and the engine pieces it needs: worktree create / import / lease / switch_next / drop, the sandbox guard, gate.main_of (a worktree
is its main project), the stage module's worktree resolution (own log per worktree, main's playbook and level), engine.charter_approve (every negative: not in ends, forged
sha, no plan, not full, via advance), the lease rules of the main log, cr_continue only while the run is active, and red-team 18 (work.json forged to `approve: done`).
Temp sandbox, no network. Run: python3 tests/autopilot_worktree_test.py"""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import shipmiracle_isolation; shipmiracle_isolation.apply_to_environ()   # test isolation: fresh HOME/SHIPMIRACLE_HOME/CONFIG/STATE unless already temp
import json, os, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import autopilot_engine_fixture as X
from autopilot_engine_fixture import check, git, sh, S, PID, MAIN, engine, store, W, F, ch, DEV, STATE

X.build()


def raises(fn, *a, **k):
    try:
        fn(*a, **k)
    except Exception as e:
        return e
    return None


# ------------------------------------------------------------------ create
X.cleanup()
info = W.create(str(MAIN), "CR-002")
wt = info["wt"]
check("create: worktree at <dev>/.worktrees/sandbox/auto-CR-002 on branch auto/CR-002 at main's HEAD", wt == str((DEV / ".worktrees" / "sandbox" / "auto-CR-002").resolve())
      and W.current_branch(wt) == "auto/CR-002" and info["base"] == X.main_head() == W.rev(wt) and info["main_branch"] == "main", info)
check("create: its .git is a file pointing into the main repository (a linked worktree)", os.path.isfile(os.path.join(wt, ".git")) and W.inspect(wt)["main"] == str(MAIN.resolve()))
check("create again: refused (folder exists)", raises(W.create, str(MAIN), "CR-002") is not None)
check("create: bad CR ids are refused before anything is run", all(raises(W.create, str(MAIN), x) is not None for x in ("CR-1", "../x", "CR-002; rm", "auto/CR-002", "")))
git(MAIN, "worktree", "remove", "--force", wt)
check("create: the branch exists after removing only the worktree -> refused", "already exists" in str(raises(W.create, str(MAIN), "CR-002")))
git(MAIN, "branch", "-D", "auto/CR-002")
git(MAIN, "switch", "-q", "-c", "auto/CR-050")
check("create: refused when the main checkout is itself on an auto branch", "own branch" in str(raises(W.create, str(MAIN), "CR-002")))
git(MAIN, "switch", "-q", "main")
git(MAIN, "branch", "-D", "auto/CR-050")
X.cleanup()

# ------------------------------------------------------------------ import and lease
info = W.create(str(MAIN), "CR-002")
wt = info["wt"]
check("import_cr: first time True", W.import_cr(str(MAIN), wt, "CR-002", info["base"]) is True)
w = store.load(wt)
c = engine.get_cr(w, "CR-002")
check("import_cr: open, active, lane full, base and snapshot recorded, stages after scope are next", w["active"] == "CR-002" and c["status"] == "open" and c["lane"] == "full"
      and c["base"] == info["base"] and store.load_snapshot(wt, "CR-002")["base"] == info["base"] and c["stages"]["approve"] == c["stages"]["do"] == "next")
check("import_cr: the main CR is untouched (still queued, no lease yet)", engine.get_cr(store.load(str(MAIN)), "CR-002")["status"] == "queued")
check("import_cr again: False (idempotent)", W.import_cr(str(MAIN), wt, "CR-002", info["base"]) is False)
check("import_cr: a CR the main log does not have is refused", "not an open or queued" in str(raises(W.import_cr, str(MAIN), wt, "CR-777")))
W.lease(str(MAIN), "CR-002", True)
mc = engine.get_cr(store.load(str(MAIN)), "CR-002")
check("lease: main CR-002 is held with the lease name", mc["hold"] and mc["lease"] == "auto-CR-002")
def tx_start(work):
    return None, engine.start(work, "CR-002", {"kind": "cli_start", "by": "owner"})
e = raises(store.transact, str(MAIN), tx_start)
check("lease: `start` of a leased queued CR is refused", e is not None and "leased" in str(e), e)
W.lease(str(MAIN), "CR-001", True)                           # the ACTIVE CR of the main log: an owner prompt releases a manual hold, but not a lease
def tx_release(work):
    return None, engine.release(work, "CR-001", {"kind": "owner_prompt", "by": "owner", "data": {}})
store.transact(str(MAIN), tx_release)
check("lease: an owner prompt does not release a lease", engine.get_cr(store.load(str(MAIN)), "CR-001")["lease"] == "auto-CR-001" and engine.get_cr(store.load(str(MAIN)), "CR-001")["hold"])
W.lease(str(MAIN), "CR-001", False)
check("lease: the same lease twice is idempotent", raises(W.lease, str(MAIN), "CR-002", True) is None)
W.lease(str(MAIN), "CR-002", False)
mc = engine.get_cr(store.load(str(MAIN)), "CR-002")
check("unlease: hold and lease gone", not mc["hold"] and not mc["lease"])
check("lease survives a replay (apply_tr is the only writer)", engine.get_cr(store.replay(store._parse_lines(store._read_log_bytes(store.log_path(str(MAIN))))[0])[0], "CR-002")["lease"] is None)
X.cleanup()

# ------------------------------------------------------------------ next_cr_id and switch_next
cr, chat = X.new_run("nextcr")
c = S.check(PID)[2]
check("next_cr_id: skips leased and finished CRs; None when the charter has none left", W.next_cr_id(str(MAIN), c) is None, W.next_cr_id(str(MAIN), c))
cr2, chat2 = X.new_run("two")
code, out, err = X.shipm("cr", "open", "third", "--project", str(MAIN))
c3 = __import__("re").search(r"CR-\d+", out).group(0)
# a charter with two ends: build it directly on top of the existing run state
line = 'charter: goal="two"; scope="src/**"; budget=10%%; time=3h; deps=none; ends=%s,%s' % (cr2, c3)
X.shipm("autopilot", "stop", "--project", "sandbox")
X.cleanup()
X.write_plan(34)
r = ch.store_from_prompt(PID, line, X.SID)
code, out, err = X.shipm("autopilot", "start", "--project", "sandbox", "--yes", "--ack", r["charter"]["id"])
cc = r["charter"]
check("start with two ends: first CR = first end", S.read(PID)["cr"] == cr2, (code, out, err))
wt = S.read(PID)["worktree"]
check("next_cr_id after the first: the second end (queued, free)", W.next_cr_id(str(MAIN), cc, cr2) == c3)
check("switch_next: refused while the current CR is not finished in the worktree", "not finished" in str(raises(W.switch_next, PID, str(MAIN), wt, cc, r["sha256"], cr2)))
store.transact(wt, lambda w_: (None, engine.deliver_external(w_, cr2, {"kind": "engine", "by": "engine", "ts": int(time.time()), "data": {}})), do_render=False)
(__import__("pathlib").Path(wt) / "stray.txt").write_text("x")
check("switch_next: refused while the worktree is dirty", "not clean" in str(raises(W.switch_next, PID, str(MAIN), wt, cc, r["sha256"], cr2)))
os.unlink(os.path.join(wt, "stray.txt"))
n = W.switch_next(PID, str(MAIN), wt, cc, r["sha256"], cr2)
check("switch_next: new branch from main's HEAD in the same worktree, CR imported, leased, state moved", n["cr"] == c3 and W.current_branch(wt) == "auto/" + c3 and W.rev(wt) == X.main_head()
      and S.read(PID)["cr"] == c3 and S.read(PID)["branch"] == "auto/" + c3 and S.read(PID)["base"] == X.main_head()
      and engine.get_cr(store.load(str(MAIN)), c3)["lease"] == "auto-" + c3 and store.load(wt)["active"] == c3, n)
check("switch_next: the worktree log has the new CR", engine.get_cr(store.load(wt), c3) is not None)
check("switch_next: auto_decision charter_next_cr logged", any(e["data"]["rule"] == "charter_next_cr" and e["data"]["cr"] == c3 for e in X.events("auto_decision")))
check("switch_next: no CR left -> None", W.switch_next(PID, str(MAIN), wt, cc, r["sha256"], c3) is None)

# ------------------------------------------------------------------ gate.main_of and the stage resolution
from shipmiracle.playbook import gate
check("gate.main_of: a worktree is its main project; the main folder and strangers are themselves", gate.main_of(wt) == str(MAIN.resolve()) and gate.main_of(str(MAIN)) == str(MAIN.resolve())
      and gate.main_of("/tmp") == os.path.realpath("/tmp"))
rw, rm = gate.stage_rules(wt), gate.stage_rules(str(MAIN))
check("gate.stage_rules(worktree) = the main project's rules (trusted, strict, full, project name sandbox)", rw == rm and rw["trusted"] and rw["autopilot"] == "full" and rw["project"] == "sandbox", (rw or {}).get("trust"))
fake = DEV / ".worktrees" / "sandbox" / "auto-CR-888"
fake.mkdir(parents=True)
(fake / ".git").write_text("gitdir: /nonexistent/.git/worktrees/x\n")
check("gate.main_of: a forged .git file is not a worktree of main", gate.main_of(str(fake)) == os.path.realpath(str(fake)))
import shutil
shutil.rmtree(str(fake))

# ------------------------------------------------------------------ engine.charter_approve negatives (pure, on a work dict)
rules = gate.stage_rules(str(MAIN))
cs = S.read(PID)["charter_sha"]
LOG = []


def fresh_work(lane="full", plan=True, stage_approve=True):
    w = engine.new_work()
    cr, trs = engine.open_cr(w, "t", "x", 1000, lane=lane, rules=rules, kind="cli_open")
    LOG[:] = list(trs)
    if plan:
        LOG.extend(engine.advance(w, cr["id"], "plan", {"kind": "plan_presented", "by": "p", "ts": 1001, "data": {"plan_sha": "a" * 64, "role_ts": 1001, "role": "plan"}}, rules))
    return w, cr["id"]
w, cid = fresh_work()
open_lines = list(LOG)
ch_ok = dict(cc, ends=[cid])
ev = {"kind": "charter", "by": "engine", "ts": 1002, "data": {}}
check("charter_approve: refused for a charter whose sha differs from the run's", "charter_changed" in str(raises(engine.charter_approve, w, cid, ch_ok, cs, ev, rules)))
good_sha = ch.digest(ch_ok)
check("charter_approve: refused when the CR is not in the charter's ends", "not_in_charter" in str(raises(engine.charter_approve, w, cid, dict(ch_ok, ends=["CR-900"]), ch.digest(dict(ch_ok, ends=["CR-900"])), ev, rules)))
check("charter_approve: refused for a fast-lane CR", raises(engine.charter_approve, *((lambda w2, c2: (w2, c2, dict(ch_ok, ends=[c2]), ch.digest(dict(ch_ok, ends=[c2])), ev, rules))(*fresh_work(lane="fast", plan=False)))) is not None)
w2, c2 = fresh_work(plan=False)
check("charter_approve: refused when no plan was presented (no plan_sha)", raises(engine.charter_approve, w2, c2, dict(ch_ok, ends=[c2]), ch.digest(dict(ch_ok, ends=[c2])), ev, rules) is not None)
check("charter_approve: refused when the playbook is not full", "not_full" in str(raises(engine.charter_approve, w, cid, ch_ok, good_sha, ev, dict(rules, autopilot="guided"))))
check("charter_approve: refused when the playbook is untrusted", "not_full" in str(raises(engine.charter_approve, w, cid, ch_ok, good_sha, ev, dict(rules, trusted=False))))
check("charter_approve: refused for a non-hex state sha", "no_charter" in str(raises(engine.charter_approve, w, cid, ch_ok, "zz", ev, rules)))
e = raises(engine.advance, w, cid, "approve", {"kind": "charter", "by": "engine", "ts": 1002, "data": {}}, rules)
check("advance(kind charter) is refused: only charter_approve records it", e is not None and "charter_approve" in str(e), e)
check("advance(owner_prompt) from a hand-back is still refused", "owner_required" in str(raises(engine.advance, w, cid, "approve", {"kind": "owner_prompt", "by": "x", "ts": 1003, "data": {"hand_back": True, "owner_words": True}}, rules)))
trs = engine.charter_approve(w, cid, ch_ok, good_sha, ev, rules)
cr = engine.get_cr(w, cid)
check("charter_approve: a valid call approves (by engine), keeps the plan sha in the line, stage = do", cr["stage"] == "do" and cr["stages"]["approve"] == "done:engine"
      and trs[0]["ev"]["kind"] == "charter" and trs[0]["ev"]["data"]["plan_sha"] == "a" * 64 and len(engine.dumps_line(trs[0]).encode()) < 1024, trs)
w_re, _sk = store.replay(open_lines + trs)
check("charter_approve: the logged lines replay to the same state", engine.get_cr(w_re, cid)["stages"]["approve"] == "done:engine" and engine.get_cr(w_re, cid)["stage"] == "do" and _sk == 0)
check("charter_approve twice: refused (not at approve any more)", raises(engine.charter_approve, w, cid, ch_ok, good_sha, ev, rules) is not None)
check("block_reason: None for a healthy CR; merge_ready needs verify", engine.block_reason(w) is None and engine.merge_ready(cr, rules)[0] is False)

# ------------------------------------------------------------------ the CLI: start without launch, drop, resume
X.cleanup()
cr, chat = X.new_run("cli")
st = S.read(PID)
check("CLI start: running with a worktree, the chat NOT launched (no process, no --launch)", st["state"] == "running" and os.path.isdir(st["worktree"]))
code, out, err = X.shipm("autopilot", "start", "--project", "sandbox", "--yes", "--launch")
check("CLI start --launch is never run under SHIPMIRACLE_TEST=1 (and a second start is refused anyway)", code != 0, (code, out, err))
code, out, err = X.shipm("autopilot", "drop", "--project", "sandbox")
check("CLI drop without a CR id: exit 2", code == 2, (code, out, err))
code, out, err = X.shipm("autopilot", "drop", cr, "--project", "sandbox")
check("CLI drop of a RUNNING run: exit 1, worktree still there", code == 1 and "running" in (out + err) and os.path.isdir(st["worktree"]), (code, out, err))
S.pause(PID, None, "test")
shutil.rmtree(st["worktree"], ignore_errors=True)
code, out, err = X.shipm("autopilot", "resume", "--project", "sandbox")
check("CLI resume: refused while the worktree folder is gone", code == 1 and "worktree" in (out + err), (code, out, err))

# ------------------------------------------------------------------ red-team 18: work.json forged
X.cleanup()
cr, chat = X.new_run("forge")
chat.prompt("go")
wj = chat.wt / ".shipmiracle" / "work.json"
doc = json.loads(wj.read_text())
doc["crs"][0]["stages"]["approve"] = "done:owner"
doc["crs"][0]["stages"]["plan"] = "done:planner"
wj.write_text(json.dumps(doc))
n0 = len(X.events("cr.work_forged"))
chat.prompt("again")
c = chat.cr()
check("18: work.json edited to `approve: done` -> approve still next in the engine's state", c["stages"]["approve"] == "next" and c["stages"]["plan"] == "next" and c["stage"] == "plan", c["stages"])
check("18: cr.work_forged reported and the file re-rendered from the log", len(X.events("cr.work_forged")) > n0 and json.loads(wj.read_text())["crs"][0]["stages"]["approve"] == "next")
check("18: no charter approval was logged for the forged CR (no plan_sha, the engine never read the file)", c["plan_sha"] is None
      and not any(e["data"]["rule"] == "charter_approve" and e["data"]["cr"] == cr for e in X.events("auto_decision")))

# ------------------------------------------------------------------ cr_continue only while the run is active
X.cleanup()
cr, chat = X.new_run("continue")
chat.prompt("go")
chat.plan_stop()
chat.exit_plan()
chat.build()
r = chat.stop("Building done, continuing.")
check("running: a Stop after a stage event is pushed on (cr_continue)", r.get("decision") == "block" and "TEAM FLOW (change request)" in json.dumps(r), r)
check("running: the push is logged as auto_decision `continue`", any(e["data"]["rule"] == "continue" and e["data"]["cr"] == cr for e in X.events("auto_decision")))
chat2 = X.Chat(chat.wt, sid="other0001")
S.pause(PID, None, "test")
chat2.sub("backend-engineer", "Built again.")
r = chat2.stop("Paused, stopping.")
check("paused: the stage module does not push the Stop on (no cr_continue)", "TEAM FLOW (change request)" not in json.dumps(r), r)
S.resume(PID)
S.end(PID, "owner")
chat3 = X.Chat(chat.wt, sid="third0001")
chat3.sub("backend-engineer", "Built again.")
r = chat3.stop("Ended, stopping.")
check("ended: a Stop is not pushed either", "TEAM FLOW (change request)" not in json.dumps(r), r)

print("\nALL PASS" if not X.fails else "\nFAILED: %d" % X.fails)
sys.exit(1 if X.fails else 0)
