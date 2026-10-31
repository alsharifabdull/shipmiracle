#!/usr/bin/env python3
"""shipmiracle/playbook/diffstat.py on real temporary git repositories + the fast-lane promotion edge cases through the engine: 3/4 files, 50/51
lines, risk path, dep file, binary, untracked file, submodule, rename, exclusions, big untracked list, hardened git calls.
Temp dirs + SHIPMIRACLE_TEST=1 only. Run: python3 tests/fastlane_test.py"""
import os, pathlib, subprocess, sys, tempfile, time

ROOT = pathlib.Path(__file__).resolve().parent.parent
TMP = pathlib.Path(tempfile.mkdtemp()).resolve()
os.environ.update(SHIPMIRACLE_TEST="1", SHIPMIRACLE_HOME=str(TMP / "home"), SHIPMIRACLE_STATE=str(TMP / "state"), SHIPMIRACLE_CONFIG=str(TMP / "config"),
                  SHIPMIRACLE_DEV=str(TMP / "dev"), SHIPMIRACLE_WS=str(TMP / "ws"))
sys.path.insert(0, str(ROOT))
from shipmiracle import projects  # noqa: E402
from shipmiracle.playbook import config, diffstat, engine, gate  # noqa: E402

fails = 0
def check(name, ok, info=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(info)))
    fails += 0 if ok else 1

GENV = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(TMP / "home"), "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"}
def git(repo, *args):
    r = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", "-c", "protocol.file.allow=always", *args], cwd=str(repo), env=GENV,
                       stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if r.returncode != 0:
        raise RuntimeError("git %s: %s" % (args, r.stderr.decode()))
    return r.stdout.decode()

def write(repo, rel, text, binary=False):
    p = pathlib.Path(repo) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(text if binary else text.encode())

N = [0]
def mkrepo(commit=True):
    N[0] += 1
    r = TMP / ("repo%d" % N[0])
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    if commit:
        for i in range(1, 6):
            write(r, "f%d.py" % i, "".join("line %d\n" % k for k in range(100)))
        write(r, "src/auth/login.py", "".join("a%d\n" % k for k in range(20)))
        write(r, "docs/STATUS.md", "Updated: x\n")
        write(r, "package.json", "{}\n")
        write(r, "img.bin", b"\x00\x01\x02" * 100, binary=True)
        git(r, "add", "-A"); git(r, "commit", "-q", "-m", "init")
    return r

def edit(repo, rel, n_added):
    """Append n_added lines to a tracked file (added = n_added, deleted = 0)."""
    p = pathlib.Path(repo) / rel
    p.write_text(p.read_text() + "".join("new %d\n" % k for k in range(n_added)))

RULES = gate.build_rules("/x/P", config.validate({"v": 1, "type": "software"}), "trusted", "", "strict")
APP = gate.build_rules("/x/P", config.validate({"v": 1, "type": "app"}), "trusted", "", "strict")
ev = lambda r, snap, rules=RULES: diffstat.evaluate(r, snap, rules)

# ---- snapshot -----------------------------------------------------------------------------------
r = mkrepo()
head = git(r, "rev-parse", "HEAD").strip()
s0 = diffstat.snapshot(r)
check("snapshot of a clean repo: base is HEAD, no untracked", s0["base"] == head and s0["untracked"] == [] and s0["untracked_more"] == 0, s0)
check("clean repo: nothing changed", ev(r, s0)["files"] == 0 and ev(r, s0)["lines"] == 0)
edit(r, "f1.py", 7); write(r, "u1.txt", "x\n")
s1 = diffstat.snapshot(r)
check("snapshot of a dirty repo: base is a stash commit (not HEAD), pre-existing untracked listed", s1["base"] != head and len(s1["base"]) == 40 and s1["untracked"] == ["u1.txt"], s1)
check("pre-existing changes are not counted afterwards", ev(r, s1)["files"] == 0 and ev(r, s1)["lines"] == 0, ev(r, s1))
check("the stash commit is dangling: stash list and working tree are untouched", git(r, "stash", "list") == "" and "new 6" in (r / "f1.py").read_text())
edit(r, "f2.py", 4)
d = ev(r, s1)
check("a change after the snapshot is counted (files 1, lines 4)", d["files"] == 1 and d["lines"] == 4 and d["paths"] == ["f2.py"], d)
check("evaluate against the snapshot of a clean repo counts old dirt too", ev(r, s0)["files"] == 3, ev(r, s0))

# ---- boundaries: exactly at the limits are eligible --------------------------------------------------
r = mkrepo(); s = diffstat.snapshot(r)
edit(r, "f1.py", 20); edit(r, "f2.py", 20); edit(r, "f3.py", 10)
d = ev(r, s)
check("3 files / 50 lines (exactly the limits): measured exactly", d["files"] == 3 and d["lines"] == 50, d)
check("...and eligible", engine.evaluate_diff(d, RULES) == {"eligible": True, "why": []})
edit(r, "f3.py", 1)
d = ev(r, s)
check("51 lines: measured 51, not eligible (lines>50)", d["lines"] == 51 and engine.evaluate_diff(d, RULES)["why"] == ["lines>50"], d)
r = mkrepo(); s = diffstat.snapshot(r)
for i in range(1, 5):
    edit(r, "f%d.py" % i, 1)
d = ev(r, s)
check("4 files: not eligible (files>3)", d["files"] == 4 and engine.evaluate_diff(d, RULES)["why"] == ["files>3"], d)
r = mkrepo(); s = diffstat.snapshot(r); write(r, "f1.py", "only\n")
d = ev(r, s)
check("rewrite: 100 old lines replaced by 1 = 101 changed lines", d["files"] == 1 and d["lines"] == 101, d)

# ---- risk, deps, ui ------------------------------------------------------------------------------------
r = mkrepo(); s = diffstat.snapshot(r); edit(r, "src/auth/login.py", 1)
d = ev(r, s)
check("risk path hit (**/auth/**): risk listed, not eligible", d["risk"] == ["src/auth/login.py"] and engine.evaluate_diff(d, RULES)["why"] == ["risk_path"], d)
edit(r, "f1.py", 1)
rr = gate.build_rules("/x/P", config.validate({"v": 1, "type": "software", "overrides": {"risk_paths": ["f1.py"]}}), "trusted", "", "strict")
check("custom risk glob f1.py is hit", "f1.py" in diffstat.evaluate(r, s, rr)["risk"])
r = mkrepo(); s = diffstat.snapshot(r); edit(r, "package.json", 1)
d = ev(r, s)
check("dep file (package.json) promotes", d["deps"] and engine.evaluate_diff(d, RULES)["why"] == ["dep_file"], d)
r = mkrepo(); s = diffstat.snapshot(r); write(r, "web/yarn.lock", "x\n")
check("dep file glob *lock* matches an untracked yarn.lock", ev(r, s)["deps"])
r = mkrepo(); s = diffstat.snapshot(r); write(r, "requirements-dev.txt", "x\n"); write(r, "go.mod", "x\n")
check("requirements*.txt and go.mod are dep files", ev(r, s)["deps"])
r = mkrepo(); s = diffstat.snapshot(r); write(r, "src/ui/Button.tsx", "x\n"); write(r, "a.css", "x\n")
check("app: ui_paths hit flagged (tsx, css); software: ui stays False", ev(r, s, APP)["ui"] and not ev(r, s, RULES)["ui"])
r = mkrepo(); s = diffstat.snapshot(r); write(r, "z.py", "x\n")
check("ui_paths brace glob does not match .py", not ev(r, s, APP)["ui"])

# ---- binary ----------------------------------------------------------------------------------------------
r = mkrepo(); s = diffstat.snapshot(r); write(r, "img.bin", b"\x00\xff" * 500, binary=True)
d = ev(r, s)
check("changed tracked binary counts 51 lines", d["files"] == 1 and d["lines"] == 51 and d["binary"], d)
check("...and is not eligible (lines>50)", engine.evaluate_diff(d, RULES)["why"] == ["lines>50"])
r = mkrepo(); s = diffstat.snapshot(r); write(r, "new.png", b"\x89PNG\x00\x00" * 50, binary=True)
d = ev(r, s)
check("new untracked binary counts 51 lines", d["files"] == 1 and d["lines"] == 51 and d["binary"], d)

# ---- untracked files ---------------------------------------------------------------------------------------
r = mkrepo(); s = diffstat.snapshot(r)
write(r, "n1.txt", "a\nb\nc\n"); write(r, "n2.txt", "no newline at end"); write(r, "empty.txt", "")
d = ev(r, s)
check("new untracked files: lines counted (3 + 1 + 0), 3 files", d["files"] == 3 and d["lines"] == 4, d)
r = mkrepo(); s = diffstat.snapshot(r); write(r, "big.txt", "x\n" * (700 * 1024))
d = ev(r, s)
check("untracked file larger than 1 MB: read up to 1 MB only, still counted (>= 51 lines)", d["files"] == 1 and 51 <= d["lines"] <= 600000, d)
r = mkrepo(); s = diffstat.snapshot(r); os.symlink("/etc/passwd", r / "lnk")
check("untracked symlink counts as 1 line and is not followed", ev(r, s)["lines"] == 1)
r = mkrepo(); s = diffstat.snapshot(r)
t0 = time.time()
for i in range(305):
    write(r, "many/m%03d.txt" % i, "x\n")
d = ev(r, s)
check("305 new untracked files: all counted as files, not eligible; bounded work", d["files"] == 305 and engine.evaluate_diff(d, RULES)["why"][0] == "files>3", d["files"])
check("snapshot lists at most 300 untracked files and says how many more", (lambda s2: len(s2["untracked"]) == 300 and s2["untracked_more"] == 5)(diffstat.snapshot(r)))
check("a file untracked at open and edited later is not counted as new", (lambda r2: (write(r2, "pre.txt", "1\n"), (lambda s2: (write(r2, "pre.txt", "1\n2\n3\n"), ev(r2, s2)["files"] == 0)[1])(diffstat.snapshot(r2)))[1])(mkrepo()))
check("gitignored files are not counted", (lambda r2: (write(r2, ".gitignore", "*.log\n"), git(r2, "add", "-A"), git(r2, "commit", "-q", "-m", "ig"), (lambda s2: (write(r2, "a.log", "x\n"), ev(r2, s2)["files"] == 0)[1])(diffstat.snapshot(r2)))[3])(mkrepo()))

# ---- exclusions ---------------------------------------------------------------------------------------------------
r = mkrepo(); s = diffstat.snapshot(r)
edit(r, "docs/STATUS.md", 30); write(r, "docs/DECISIONS.md", "x\n" * 80); write(r, ".shipmiracle/work.json", "{}\n" * 60); write(r, "docs/reports/2026-CR-001.md", "r\n" * 99)
write(r, "docs/plans/p.md", "p\n" * 99); write(r, "docs/memory/m.md", "m\n" * 99); write(r, ".claude/plans/x.md", "x\n" * 99)
d = ev(r, s)
check("RECORD paths, .shipmiracle/ and docs/reports/ are not counted (STATUS edit, DECISIONS, plans, memory, reports, work.json)", d["files"] == 0 and d["lines"] == 0, d)
edit(r, "f1.py", 2)
check("...while a code file next to them is counted", ev(r, s)["files"] == 1 and ev(r, s)["lines"] == 2)
r = mkrepo(); s = diffstat.snapshot(r); write(r, "docs/guide.md", "g\n" * 5)
check("docs/ files that are not records ARE counted (docs/guide.md)", ev(r, s)["files"] == 1 and ev(r, s)["lines"] == 5)

# ---- rename ---------------------------------------------------------------------------------------------------------
r = mkrepo(); s = diffstat.snapshot(r); git(r, "mv", "f1.py", "renamed.py")
d = ev(r, s)
check("pure rename: one file, no lines, no risk", d["files"] == 1 and d["lines"] == 0 and d["paths"] == ["renamed.py"] and d["risk"] == [], d)
r = mkrepo(); s = diffstat.snapshot(r); git(r, "mv", "src/auth/login.py", "src/login.py")
d = ev(r, s)
check("rename OUT of a risk path still hits the risk glob (old path checked)", d["files"] == 1 and "src/auth/login.py" in d["risk"], d)
r = mkrepo(); s = diffstat.snapshot(r); (r / "src" / "auth").mkdir(exist_ok=True); git(r, "mv", "f1.py", "src/auth/f1.py")
check("rename INTO a risk path hits too", "src/auth/f1.py" in ev(r, s)["risk"])
r = mkrepo(); s = diffstat.snapshot(r); git(r, "mv", "package.json", "pkg/package.json") if (r / "pkg").mkdir() is None else None
check("rename of a dep file counts as a dep change", ev(r, s)["deps"])
r = mkrepo(); s = diffstat.snapshot(r); git(r, "mv", "f1.py", "g1.py"); edit(r, "g1.py", 3)
d = ev(r, s)
check("rename with edits: one file, 3 lines", d["files"] == 1 and d["lines"] == 3, d)
r = mkrepo(); s = diffstat.snapshot(r); (r / "f1.py").unlink()
d = ev(r, s)
check("deleted file: one file, 100 deleted lines", d["files"] == 1 and d["lines"] == 100, d)

# ---- submodule --------------------------------------------------------------------------------------------------------
r = mkrepo(); s = diffstat.snapshot(r)
sub = TMP / "subsrc"; sub.mkdir(); git(sub, "init", "-q", "-b", "main"); write(sub, "a.txt", "x\n"); git(sub, "add", "-A"); git(sub, "commit", "-q", "-m", "s")
git(r, "submodule", "add", "-q", str(sub), "vendor/sub")
d = ev(r, s)
check("added submodule: flagged, not eligible (submodule)", d["submodule"] and "submodule" in engine.evaluate_diff(d, RULES)["why"], d)
r = mkrepo(); s = diffstat.snapshot(r); nested = r / "nested"; nested.mkdir(); git(nested, "init", "-q", "-b", "main"); write(nested, "q.txt", "x\n")
d = ev(r, s)
check("nested untracked repository counts as a submodule", d["submodule"] and d["files"] == 1, d)

# ---- repo without commits, non-repo, bad input ------------------------------------------------------------------------------
r0 = mkrepo(commit=False); s = diffstat.snapshot(r0)
write(r0, "first.txt", "a\nb\n")
check("repository without commits: base is the empty tree, new files counted", s["base"] == diffstat.EMPTY_TREE and ev(r0, s)["files"] == 1 and ev(r0, s)["lines"] == 2, (s, ev(r0, s)))
plain = TMP / "plain"; plain.mkdir()
def gerr(fn, *a):
    try:
        fn(*a)
    except diffstat.GitError:
        return True
    except Exception as e:
        return repr(e)
    return False
check("not a repository: GitError (callers fail open)", gerr(diffstat.snapshot, plain) is True and gerr(diffstat.evaluate, plain, {"base": "a" * 40}) is True)
check("bad base id refused", gerr(diffstat.evaluate, r, {"base": "HEAD; rm -rf"}) is True and gerr(diffstat.evaluate, r, {"base": "--output=x"}) is True)
check("bad snapshot id for delta refused", gerr(diffstat.delta, r, "--help") is True and gerr(diffstat.delta, r, None) is True)

# ---- hardened git calls -------------------------------------------------------------------------------------------------------
calls = []
real_run = subprocess.run
def spy(argv, **kw):
    calls.append((argv, kw))
    return real_run(argv, **kw)
rh = mkrepo()
diffstat.subprocess.run = spy
os.environ.update(GIT_DIR="/nonexistent", GIT_WORK_TREE="/nonexistent", GIT_INDEX_FILE="/nonexistent", GIT_CONFIG_COUNT="1",
                  GIT_CONFIG_KEY_0="core.hooksPath", GIT_CONFIG_VALUE_0="/tmp")
try:
    sh = diffstat.snapshot(rh)
    edit(rh, "f1.py", 2)
    dh = ev(rh, sh)
finally:
    for k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_CONFIG_COUNT", "GIT_CONFIG_KEY_0", "GIT_CONFIG_VALUE_0"):
        os.environ.pop(k, None)
    diffstat.subprocess.run = real_run
check("GIT_DIR / GIT_WORK_TREE / GIT_INDEX_FILE in the caller's environment do not redirect git", dh["files"] == 1 and dh["lines"] == 2, dh)
check("every git call is list-form, no shell, with a timeout, starting with the hardened prefix",
      calls and all(isinstance(a, list) and a[:5] == projects.GIT_PREFIX and k.get("shell") is False and k.get("timeout") and k.get("stdin") == subprocess.DEVNULL for a, k in calls), calls[:1])
check("git env has only PATH/HOME/LANG/LC_*/TMPDIR and our GIT_ switches", all(set(k["env"]) <= set(projects._GIT_ENV_KEEP) | {"GIT_OPTIONAL_LOCKS", "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL"} for a, k in calls))
check("the prefix disables fsmonitor and hooks", "core.fsmonitor=false" in projects.GIT_PREFIX and "core.hooksPath=/dev/null" in projects.GIT_PREFIX)
def boom(argv, **kw):
    raise subprocess.TimeoutExpired(argv, 3)
diffstat.subprocess.run = boom
check("a git timeout becomes GitError", gerr(diffstat.snapshot, r) is True)
diffstat.subprocess.run = real_run

# ---- delta (post-review) ------------------------------------------------------------------------------------------------------------
r = mkrepo(); edit(r, "f1.py", 5)
snap = git(r, "stash", "create").strip()
edit(r, "f2.py", 2); write(r, "docs/STATUS.md", "changed\n" * 9)
d = diffstat.delta(r, snap)
check("delta since a review snapshot: only the new tracked change, records excluded", d == {"files": 1, "lines": 2}, d)
wd = engine.new_work(); cd_, _ = engine.open_cr(wd, "pr", "o", 1760000000, lane="full", rules=RULES)
check("delta result feeds engine.post_review_delta (nothing to reset before a review)", engine.post_review_delta(wd, cd_["id"], d, {"kind": "diff_eval", "data": {}}, RULES) == [])

# ---- end to end: snapshot at open, edits, evaluate, engine promotes ----------------------------------------------------------------------
r = mkrepo(); snap = diffstat.snapshot(r)
w = engine.new_work()
cr, trs = engine.open_cr(w, "e2e", "owner", 1760000000, base=snap["base"], rules=RULES)
edit(r, "f1.py", 2)
d = ev(r, snap)
t1 = engine.observe_diff(w, cr["id"], d, {"kind": "diff_eval", "data": {}, "ts": 1760000100}, RULES)
check("e2e: small edit keeps the CR in the fast lane (diff recorded)", cr["lane"] == "fast" and cr["diff"]["files"] == 1 and [t["op"] for t in t1] == ["diff"], (cr["lane"], t1))
edit(r, "src/auth/login.py", 1)
d = ev(r, snap)
t2 = engine.observe_diff(w, cr["id"], d, {"kind": "diff_eval", "data": {}, "ts": 1760000200}, RULES)
check("e2e: touching src/auth promotes to full (plan + approve next), risk path recorded", cr["lane"] == "full" and cr["stage"] == "plan" and cr["diff"]["risk"] == ["src/auth/login.py"] and [t["op"] for t in t2] == ["lane"], (cr["lane"], cr["stage"]))
check("e2e: the base in the CR is the snapshot commit", cr["base"] == snap["base"])
t0 = time.time(); [ev(r, snap) for _ in range(5)]
print("# diffstat.evaluate on a small repo: %.0f ms per call" % ((time.time() - t0) * 200))

print("\nFAILED: %d" % fails if fails else "\nALL PASS")
sys.exit(1 if fails else 0)
