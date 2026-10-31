#!/usr/bin/env python3
"""Phase 6 T5 deliver.ff_merge (spec section 3, red-team 37 and 38): temp repo + LOCAL bare origin (the visibility cache says private), no network. Covers: the happy path
(fast-forward, push to the bare origin, main log delivered, auto_decision deliver_ff), every refusal/stop (CR not ready, dirty tree, no commits, run not active, wrong branch),
H5 gate-file stop with the owner's exact allow (case 37), live chat / dirty main = merge_waiting, diverged main, limit reached = no merge, unknown visibility =
H2-publish_unknown with nothing pushed and nothing merged (case 38; a github URL remote that can only resolve to a nonexistent local path), push failure, retry after a crash
(already merged), the sandbox guard (the 2026-10-20 incident), and rollback with `drop`. Run: python3 tests/autopilot_deliver_test.py"""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import autopilot_engine_fixture as X
from autopilot_engine_fixture import check, git, sh, S, PID, MAIN, engine, store, W, F, deliver, visibility, ORIGIN

X.build()
GH = "https://github.com/owner/sandbox.git"


def ready(tag, rel=None, text="v = 1\n"):
    """A run whose CR has passed review and whose work is committed on the auto branch (not yet delivered)."""
    cr, chat = X.new_run(tag)
    chat.prompt("go"); chat.plan_stop(); chat.exit_plan()
    chat.build(rel=rel or "src/%s.py" % tag, text=text)
    chat.test(); chat.review()
    chat.commit("work " + tag)
    return cr, chat


def kinds(k):
    return X.events(k)


# ------------------------------------------------------------------ sandbox guard (incident rule)
real_dev = os.environ["SHIPMIRACLE_DEV"]
os.environ["SHIPMIRACLE_DEV"] = "/Users/someone/Developer"
try:
    r = None
    try:
        W.create(str(MAIN), "CR-777")
    except Exception as e:
        r = e
finally:
    os.environ["SHIPMIRACLE_DEV"] = real_dev
check("guard: a partial sandbox (SHIPMIRACLE_DEV outside the temp folder) refuses to touch git", r is not None and type(r).__name__ == "SafetyError", r)
try:
    W.guard("/Users/someone/Developer/real-project")
    g = None
except Exception as e:
    g = e
check("guard: a project folder outside the temp folder is refused even in a full sandbox", type(g).__name__ == "SafetyError", g)

# ------------------------------------------------------------------ happy path
cr, chat = ready("happy", "src/happy.py")
head0, o0 = X.main_head(), X.origin_head()
res = deliver.ff_merge(chat.wt, cr)
check("happy: merged, pushed", res["status"] == "merged" and res["pushed"] is True, res)
check("happy: main fast-forwarded to the branch tip, origin equals main", X.main_head() == W.rev(MAIN, "refs/heads/auto/" + cr) != head0 and X.origin_head() == X.main_head())
check("happy: file is in main", (MAIN / "src" / "happy.py").exists())
check("happy: main log CR delivered, lease gone", engine.get_cr(store.load(str(MAIN)), cr)["status"] == "delivered" and not engine.get_cr(store.load(str(MAIN)), cr)["lease"])
check("happy: auto_decision deliver_ff + autopilot.merged logged", any(e["data"]["rule"] == "deliver_ff" and e["data"]["cr"] == cr for e in kinds("auto_decision"))
      and any(e["data"]["cr"] == cr and e["data"]["pushed"] for e in kinds("autopilot.merged")))
res2 = deliver.ff_merge(chat.wt, cr)
check("retry after a crash (already merged): merged again without a new merge, nothing breaks", res2["status"] == "merged" and X.main_head() == W.rev(MAIN, "refs/heads/auto/" + cr), res2)

# ------------------------------------------------------------------ refusals
cr, chat = X.new_run("notready")
res = deliver.ff_merge(chat.wt, cr)
check("refused: a CR that has not passed verify/review is not merged", res["status"] == "refused" and "not ready" in res["text"], res)
cr, chat = ready("dirty", "src/dirty.py")
(chat.wt / "src" / "stray.py").write_text("x\n")
h = X.main_head()
res = deliver.ff_merge(chat.wt, cr)
check("refused: untracked file in the worktree -> not clean, nothing merged", res["status"] == "refused" and "not clean" in res["text"] and X.main_head() == h, res)
os.unlink(str(chat.wt / "src" / "stray.py"))
res = deliver.ff_merge(chat.wt, "CR-999")
check("refused: the worktree is not on the asked branch", res["status"] == "refused", res)
cr, chat = X.new_run("nocommit")
chat.prompt("go"); chat.plan_stop(); chat.exit_plan(); chat.build(rel="src/nc.py"); chat.test(); chat.review()          # built but never committed
res = deliver.ff_merge(chat.wt, cr)
check("refused: built files uncommitted (dirty) -> nothing merged", res["status"] == "refused", res)
S.pause(PID, None, "test")
res = deliver.ff_merge(chat.wt, cr)
check("refused: a paused run does not merge", res["status"] == "refused" and "not active" in res["text"], res)

# ------------------------------------------------------------------ case 37: the branch changes .githooks
cr, chat = ready("hooks", "src/hooks.py")
(chat.wt / ".githooks" / "post-commit").write_text("#!/bin/sh\ngit push --force origin HEAD\n")
chat.commit("tweak hook")
h, o = X.main_head(), X.origin_head()
res = deliver.ff_merge(chat.wt, cr)
st = S.read(PID)
check("37: gate/hook file changed on the branch -> stopped H5, not merged, not pushed", res["status"] == "stopped" and res["rule"] == "H5" and X.main_head() == h and X.origin_head() == o and not X.merged("auto/" + cr), res)
check("37: run paused with the stop id, event autopilot.hard_stop rule H5", st["state"] == "paused" and st["stop"]["id"] == res["stop"]["id"] and any(e["data"]["rule"] == "H5" and e["data"]["cr"] == cr for e in kinds("autopilot.hard_stop")), st)
check("37: the stop text names the file, not model text", ".githooks/post-commit" in res["text"])
S.allow(PID, st["stop"]["id"])
res = deliver.ff_merge(chat.wt, cr)
check("37: the owner's exact allow lets that one merge pass (no second allow left)", res["status"] == "merged" and not S.read(PID)["allow"], res)

# ------------------------------------------------------------------ merge_waiting
cr, chat = ready("waiting", "src/waiting.py")
h = X.main_head()
res = deliver.ff_merge(chat.wt, cr, chats=lambda name: 1)
check("merge_waiting: a live chat in the main checkout", res["status"] == "merge_waiting" and X.main_head() == h and S.read(PID)["state"] == "running", res)
check("merge_waiting: Health event autopilot.merge_waiting", any(e["data"]["cr"] == cr for e in kinds("autopilot.merge_waiting")))
res = deliver.ff_merge(chat.wt, cr, chats=lambda name: None)
check("merge_waiting: open chats that cannot be confirmed count as live", res["status"] == "merge_waiting", res)
(MAIN / "src" / "waiting.py").write_text("local edit\n")
res = deliver.ff_merge(chat.wt, cr, chats=lambda name: 0)
check("merge_waiting: uncommitted change in main on a file the branch touches", res["status"] == "merge_waiting" and "waiting.py" in res["text"] and X.main_head() == h, res)
os.unlink(str(MAIN / "src" / "waiting.py"))
(MAIN / "elsewhere.txt").write_text("unrelated\n")
res = deliver.ff_merge(chat.wt, cr, chats=lambda name: 0)
check("an unrelated untracked file in main does not block the merge", res["status"] == "merged", res)
os.unlink(str(MAIN / "elsewhere.txt"))

# ------------------------------------------------------------------ diverged main
cr, chat = ready("diverged", "src/diverged.py")
(MAIN / "moved.txt").write_text("m\n")
git(MAIN, "add", "moved.txt"); git(MAIN, "commit", "-qm", "owner moved main")
h = X.main_head()
res = deliver.ff_merge(chat.wt, cr)
check("diverged: main moved after the branch was created -> stopped, not merged", res["status"] == "stopped" and res["rule"] == "diverged" and X.main_head() == h and S.read(PID)["state"] == "paused", res)

# ------------------------------------------------------------------ limit: no merge
cr, chat = ready("limit", "src/limit.py")
X.write_plan(34 + 11)                                         # cap 10 -> used 11
h = X.main_head()
res = deliver.ff_merge(chat.wt, cr)
check("limit: budget reached -> no merge, run ended:budget", res["status"] == "limit" and X.main_head() == h and S.read(PID)["ended_reason"] == "budget", res)

# ------------------------------------------------------------------ case 38: visibility unknown
cr, chat = ready("unknown", "src/unknown.py")
git(MAIN, "remote", "add", "gh", GH)
git(MAIN, "config", "remote.gh.pushurl", "file:///nonexistent-sandbox-remote")        # an accidental push could only reach a nonexistent local path (get-url --push --all sees it, M3)
calls = []
def failing(argv, timeout=5):
    calls.append(argv)
    return 1, ""
h, o = X.main_head(), X.origin_head()
res = deliver.ff_merge(chat.wt, cr, runner=failing)
check("38: remote not cached private and gh fails -> stopped H2-publish_unknown", res["status"] == "stopped" and res["rule"] == "H2" and "publish_unknown" in res["text"], res)
check("38: nothing pushed (origin unchanged), nothing merged (main unchanged), run paused", X.origin_head() == o and X.main_head() == h and S.read(PID)["state"] == "paused", (X.origin_head(), o))
check("38: gh was asked through the injected runner only (argv fixed)", calls and calls[0][:3] == ["gh", "api", "repos/owner/sandbox"], calls)
check("38: stop recorded as H2-publish_unknown with an id", S.read(PID)["stop"]["rule"] == "H2-publish_unknown" and S.read(PID)["stop"]["id"].startswith("H-"))
# owner allow: merge locally, never push
S.allow(PID, S.read(PID)["stop"]["id"])
res = deliver.ff_merge(chat.wt, cr, runner=failing)
check("38: after the owner's exact allow the branch is merged locally and still NOT pushed", res["status"] == "merged" and res["pushed"] is False and X.origin_head() == o, res)
git(MAIN, "config", "--unset", "remote.gh.pushurl")
git(MAIN, "remote", "remove", "gh")

# ------------------------------------------------------------------ push failure
cr, chat = ready("pushfail", "src/pushfail.py")
git(MAIN, "remote", "add", "broken", "/nonexistent/bare/repo.git")
visibility.write_entry("/nonexistent/bare/repo.git", True)
res = deliver.ff_merge(chat.wt, cr)
check("push failure: merged locally, run paused with H2-publish_failed", res["status"] == "stopped" and res.get("merged") is True and S.read(PID)["stop"]["rule"] == "H2-publish_failed", res)
git(MAIN, "remote", "remove", "broken")

# ------------------------------------------------------------------ rollback: drop
cr, chat = ready("dropme", "src/dropme.py")
S.pause(PID, None, "test")
wt = chat.wt
leased = engine.get_cr(store.load(str(MAIN)), cr)["lease"]
r = W.drop(PID, str(MAIN), cr)
check("drop: worktree removed, branch deleted, lease released", leased == "auto-" + cr and not os.path.exists(str(wt)) and W.rev(MAIN, "refs/heads/auto/" + cr) is None
      and not engine.get_cr(store.load(str(MAIN)), cr)["lease"] and r["removed_worktree"] and r["deleted_branch"] and r["unleased"], r)
check("drop: main untouched (the work never reached it)", not (MAIN / "src" / "dropme.py").exists())
cr, chat = ready("dropped2", "src/dropped2.py")
try:
    W.drop(PID, str(MAIN), cr); e = None
except Exception as ex:
    e = ex
check("drop: refused while the run is running", e is not None and "running" in str(e) and os.path.exists(str(chat.wt)), e)
deliver.ff_merge(chat.wt, cr)
S.pause(PID, None, "test")
try:
    W.drop(PID, str(MAIN), cr); e = None
except Exception as ex:
    e = ex
check("drop: refused after the merge (git revert is the way)", e is not None and "revert" in str(e), e)
code, out, err = X.shipm("autopilot", "drop", cr, "--project", "sandbox")
check("CLI drop of a merged branch: exit 1 with the revert hint", code == 1 and "revert" in (out + err), (code, out, err))
cr, chat = ready("dropcli", "src/dropcli.py")
S.pause(PID, None, "test")
code, out, err = X.shipm("autopilot", "drop", cr, "--project", "sandbox")
check("CLI drop of an unmerged branch: exit 0, run ended:owner", code == 0 and S.read(PID)["ended_reason"] == "owner" and not os.path.exists(str(chat.wt)), (code, out, err))

print("\nALL PASS" if not X.fails else "\nFAILED: %d" % X.fails)
sys.exit(1 if X.fails else 0)
