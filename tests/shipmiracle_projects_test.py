#!/usr/bin/env python3
"""shipmiracle/projects.py: the single project rule, identity, resolve() (property test over 300 seeded random trees against an
independent oracle and the generator's ground truth), held rule, hub, scopes. Run: python3 tests/shipmiracle_projects_test.py"""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import shipmiracle_isolation; shipmiracle_isolation.apply_to_environ()   # test isolation: fresh HOME/SHIPMIRACLE_HOME/CONFIG/STATE unless already temp
import os, pathlib, random, shutil, subprocess, sys, tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["SHIPMIRACLE_TEST"] = "1"
from shipmiracle import ShipmiracleError, UsageError, paths, projects  # noqa: E402

fails = 0
def check(name, ok, info=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(info)))
    fails += 0 if ok else 1

TMP = pathlib.Path(tempfile.mkdtemp(prefix="shipmiracle-proj-"))     # deliberately not realpath'ed (macOS /var -> /private/var)
def write(p, text=""):
    p = pathlib.Path(p); p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text)

def ci_fs():
    d = TMP / "casecheck"; d.mkdir(); (d / "aB").write_text("x")
    return (d / "Ab").exists()
CASE_INSENSITIVE = sys.platform == "darwin" and ci_fs()

# ---------- independent oracle: plain loops, no shared code with projects.py ----------
def oracle(dev, path):
    if not path or not os.path.isabs(path):
        return None
    cf = (lambda s: s.lower()) if CASE_INSENSITIVE else (lambda s: s)
    rp = os.path.realpath(path)
    listed = [n for n in sorted(os.listdir(dev)) if n[0] != "." and os.path.exists(dev + "/" + n + "/.git")]
    def inside(child, parent):
        return cf(child) == cf(parent) or cf(child).startswith(cf(parent) + "/")
    def owner_of(real):
        best, blen = None, -1
        for n in listed:
            for base in (os.path.realpath(dev + "/" + n), dev + "/" + n):
                if inside(real, base) and len(base) > blen:
                    best, blen = n, len(base)
        return best
    wt = os.path.realpath(dev) + "/.worktrees/"
    if cf(rp).startswith(cf(wt)):
        seg = rp[len(wt):].split("/")[0]
        hits = [n for n in listed if cf(n) == cf(seg)]
        if len(hits) == 1:
            return hits[0]
    o = owner_of(rp)
    if o:
        return o
    cur = rp if os.path.isdir(rp) else os.path.dirname(rp)
    for _ in range(40):
        g = cur + "/.git"
        if os.path.lexists(g):
            if os.path.isfile(g):
                first = open(g).read().split("\n")[0].strip()
                if first.startswith("gitdir:") and "/.git/worktrees/" in first:
                    x = first[len("gitdir:"):].strip().split("/.git/worktrees/")[0]
                    if not os.path.isabs(x):
                        x = os.path.join(cur, x)
                    return owner_of(os.path.realpath(x))
            return None
        if cur == "/":
            return None
        cur = os.path.dirname(cur)
    return None

# ---------- random tree ----------
NAMES = ["alpha", "Beta", "gamma-2", "delta.v2", "Eps Lon", "zeta_é", "Omega"]
def build(seed):
    rnd = random.Random(seed)
    R = TMP / ("t%d" % seed); dev = R / "dev"; out = R / "out"; home = R / "home"
    dev.mkdir(parents=True); out.mkdir(); home.mkdir()
    projs = rnd.sample(NAMES, rnd.randint(1, 4))
    queries = []      # (path, intended name or None)
    for n in projs:
        (dev / n / ".git").mkdir(parents=True)
        sub = "/".join(rnd.choice("abc") for _ in range(rnd.randint(0, 4)))
        write(dev / n / sub / "f.txt", "x")
        queries += [(str(dev / n), n), (str(dev / n / sub / "f.txt"), n), (str(dev / n / "nope" / "x"), n),
                    (str(dev / n) + "/", n), (str(dev / n / "a" / ".." / "b"), n)]
        if CASE_INSENSITIVE:
            queries.append((str(dev / n.swapcase() / "q"), n))
        # worktree under .worktrees
        deep = "/".join(rnd.choice("xyz") for _ in range(rnd.randint(1, 3)))
        (dev / ".worktrees" / n / deep).mkdir(parents=True)
        queries += [(str(dev / ".worktrees" / n / deep), n), (str(dev / ".worktrees" / n), n)]
        # gitdir-linked worktree outside dev
        wt = out / ("wt-" + str(rnd.randint(0, 999)) + "-" + str(len(queries)))
        (wt / "src").mkdir(parents=True)
        write(wt / ".git", "gitdir: %s/.git/worktrees/w1\n" % (dev / n))
        queries.append((str(wt / "src"), n))
        # claude worktree inside the project
        (dev / n / ".claude" / "worktrees" / "w").mkdir(parents=True)
        queries.append((str(dev / n / ".claude" / "worktrees" / "w"), n))
    # home symlink to a project (like ~/sample-app)
    p0 = projs[0]
    os.symlink(dev / p0, home / "Link")
    queries += [(str(home / "Link"), p0), (str(home / "Link" / "a" / "b"), p0)]
    # symlinks inside projects
    if len(projs) > 1:
        p1 = projs[1]
        write(dev / p1 / "real" / "f", "x")
        os.symlink(dev / p1 / "real", dev / p0 / "toother")
        queries.append((str(dev / p0 / "toother" / "f"), p1))        # realpath decides
    os.symlink(out, dev / projs[-1] / "toout")
    queries.append((str(dev / projs[-1] / "toout"), None))           # leads outside
    # a symlinked project in dev pointing at an outside repo
    if rnd.random() < 0.5 and "ext" not in projs:
        (out / "ext" / ".git").mkdir(parents=True); write(out / "ext" / "s" / "f", "x")
        os.symlink(out / "ext", dev / "linkproj")
        queries += [(str(dev / "linkproj" / "s"), "linkproj"), (str(out / "ext" / "s" / "f"), "linkproj")]
    # things that are not projects
    (dev / ".hidden" / ".git").mkdir(parents=True); write(dev / ".hidden" / "f", "x")
    write(dev / "plain" / "AGENTS.md", "x"); write(dev / "plain" / ".claude" / "x", "x")
    write(dev / "afile.txt", "x")
    (dev / ".worktrees" / "ghost" / "deep").mkdir(parents=True)
    write(out / "wtbad" / ".git", "gitdir: %s/.git/worktrees/w9\n" % (out / "ext-other"))
    write(out / "sub" / "f", "x")
    (out / "sub" / ".git").mkdir()
    write(out / "wtnone" / ".git", "gitdir: /nonexistent/x/.git/worktrees/w\n")
    queries += [(str(dev / ".hidden" / "f"), None), (str(dev / "plain" / "AGENTS.md"), None), (str(dev), None),
                (str(dev / "afile.txt"), None), (str(dev / ".worktrees" / "ghost" / "deep"), None),
                (str(out / "wtbad"), None), (str(out / "sub" / "f"), None), (str(out / "wtnone"), None),
                (str(out), None), ("/", None), ("/tmp", None),
                ("relative/path", None), ("", None), ("./x", None), (str(dev / ".worktrees"), None)]
    return R, dev, queries

ids_by_seed = {}
bad_oracle, bad_truth, bad_outside, bad_id, bad_calls = [], [], [], [], []
real_run, real_popen = subprocess.run, subprocess.Popen
def boom(*a, **k):
    raise AssertionError("subprocess used by resolve")
nq = 0
for seed in range(300):
    R, dev, queries = build(seed)
    lst = projects.list_projects(dev)
    ids = [p.id for p in lst]
    if len(set(ids)) != len(ids):
        bad_id.append((seed, "dup"))
    ids_by_seed[seed] = {p.name: p.id for p in lst}
    for p in lst:
        if projects.project_id(p.path) != projects.project_id(os.path.realpath(p.path)) or p.id != projects.project_id(p.real):
            bad_id.append((seed, p.name))
    subprocess.run = subprocess.Popen = boom
    try:
        for q, intended in queries:
            nq += 1
            try:
                r = projects.resolve(q, dev)
            except Exception as e:
                bad_calls.append((seed, q, repr(e))); continue
            got = r.name if r else None
            o = oracle(str(dev), q)
            if got != o:
                bad_oracle.append((seed, q, got, o))
            if got != intended:
                bad_truth.append((seed, q, got, intended))
            if intended is None and got is not None:
                bad_outside.append((seed, q, got))
    finally:
        subprocess.run, subprocess.Popen = real_run, real_popen
    if seed % 30 == 0:           # ids stable across processes
        code = "import sys; sys.path.insert(0, %r); from shipmiracle import projects; print(','.join(p.name+'='+p.id for p in projects.list_projects(%r)))" % (str(ROOT), str(dev))
        o = subprocess.run([sys.executable, "-c", code], stdout=subprocess.PIPE, universal_newlines=True).stdout.strip()
        if o != ",".join("%s=%s" % (p.name, p.id) for p in lst):
            bad_id.append((seed, "unstable across runs"))
check("property: %d queries over 300 trees: resolve name == oracle" % nq, not bad_oracle, bad_oracle[:3])
check("property: resolve name == the generator's ground truth", not bad_truth, bad_truth[:3])
check("property: paths outside every project resolve to None", not bad_outside, bad_outside[:3])
check("property: ids unique, id(path) == id(realpath), stable across runs", not bad_id, bad_id[:3])
check("property: resolve never raises and never starts a subprocess", not bad_calls, bad_calls[:3])
a = ids_by_seed[0]
check("ids are 12 hex chars", all(len(v) == 12 and all(c in "0123456789abcdef" for c in v) for v in a.values()), a)
check("case-insensitive filesystem detection ran (%s)" % ("insensitive" if CASE_INSENSITIVE else "sensitive or not darwin"), True)

# ---------- get / names edge cases ----------
R, dev, _ = build(1000)
lst = projects.list_projects(dev)
nm = lst[0].name
check("names == list_projects names, sorted by codepoint", projects.names(dev) == [p.name for p in lst] == sorted(p.name for p in lst))
check("get(exact name) returns it", projects.get(nm, dev) is not None and projects.get(nm, dev).name == nm)
for bad in ("../x", "../" + nm, ".x", ".hidden", "", ".", "..", nm + "/", "/" + nm, nm + "/..", "plain", "afile.txt", "a\x00b", None, 5):
    check("get(%r) is None" % (bad,), projects.get(bad, dev) is None)
check("get is exact (a case variant is not a listed name)", projects.get(nm.swapcase(), dev) is None or nm.swapcase() == nm)
check("relative path resolves to None", projects.resolve("dev/" + nm, dev) is None and projects.resolve("", dev) is None)
check("resolve accepts a pathlib.Path", projects.resolve(dev / nm / "x", dev).name == nm)
check("missing dev folder gives an empty list", projects.names(R / "nope") == [] and projects.resolve("/x", R / "nope") is None)

# ---------- narrowings ----------
D = TMP / "narrow" / "dev"
(D / ".dotproj" / ".git").mkdir(parents=True)
write(D / "nogit" / "AGENTS.md", "x"); (D / "nogit" / ".claude").mkdir()
(D / "gitfile").mkdir(); write(D / "gitfile" / ".git", "gitdir: /x/.git/worktrees/y\n")
check("narrowing: a dot-named folder with .git is not a project", projects.names(D) == ["gitfile"])
check("narrowing: a non-git folder with AGENTS.md/.claude is not a project", "nogit" not in projects.names(D))
check("a .git file counts (git == 'file')", projects.get("gitfile", D).git == "file")
# collision
C = TMP / "collide" / "dev"; (C / "p" / ".git").mkdir(parents=True); os.symlink(C / "p", C / "q")
try:
    projects.list_projects(C, strict=True); raised = False
except ShipmiracleError:
    raised = True
check("strict=True: two names for the same folder raise (id collision)", raised)
check("default: the alias is dropped, the real folder kept", [x.name for x in projects.list_projects(C)] == ["p"], projects.list_projects(C))
check("collisions() reports the alias and what it points to", projects.collisions(C) == [("q", "p")], projects.collisions(C))
check("get(alias) is None; the real folder resolves from either spelling", projects.get("q", C) is None and projects.get("p", C).name == "p"
      and projects.resolve(str(C / "q" / "sub"), C).name == "p")
check("names() (panel list) still shows both", projects.names(C) == ["p", "q"])
C2 = TMP / "collide2" / "dev"; (C2 / "z" / ".git").mkdir(parents=True); os.symlink(C2 / "z", C2 / "a")
check("a symlink alias sorting first loses to the real folder", [x.name for x in projects.list_projects(C2)] == ["z"] and projects.collisions(C2) == [("a", "z")])
C3 = TMP / "collide3" / "dev"; (C3 / "real" / ".git").mkdir(parents=True); os.symlink(C3 / "real", C3 / "l1"); os.symlink(C3 / "real", C3 / "l2")
check("with three names the real folder is kept, both aliases reported", [x.name for x in projects.list_projects(C3)] == ["real"] and len(projects.collisions(C3)) == 2)
C4 = TMP / "collide4" / "dev"; (C4 / "x" / ".git").mkdir(parents=True); (C4 / "y").mkdir(); os.symlink(C4 / "x" / ".git", C4 / "y" / ".git")
check("a folder whose .git is a symlink to another project's .git is not a collision (different realpath)", len(projects.list_projects(C4)) == 2)

# ---------- control characters in names ----------
CC = TMP / "ctl" / "dev"
for n in ("good", "Held\nx", "esc\x1b[0m", "zero\u200bwidth", "tab\tname", "nul-free"):
    (CC / n / ".git").mkdir(parents=True)
check("names with newline, escape, zero-width or tab are not listed", projects.names(CC) == ["good", "nul-free"], projects.names(CC))
check("list_projects skips them as well", [x.name for x in projects.list_projects(CC)] == ["good", "nul-free"])
check("get refuses them", all(projects.get(n, CC) is None for n in ("Held\nx", "esc\x1b[0m", "zero\u200bwidth", "tab\tname", "a\x00b")))
sk = projects.skipped_names(CC)
check("skipped_names lists them with visible escapes (no raw newline)", len(sk) == 4 and all("\n" not in s and "\x1b" not in s for s in sk) and "Held\\nx" in sk, sk)

# ---------- git subprocess hardening ----------
check("GIT_PREFIX disables fsmonitor and hooks", projects.GIT_PREFIX == ["git", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null"])
saved = dict(os.environ)
os.environ.update(GIT_DIR="/nonexistent", GIT_WORK_TREE="/x", GIT_INDEX_FILE="/x/i", GIT_CONFIG_GLOBAL="/x/c", GIT_CONFIG_COUNT="1",
                  GIT_CEILING_DIRECTORIES="/", GIT_EXEC_PATH="/x", LANG="C", LC_ALL="C")
ge = projects.git_env()
check("git_env keeps PATH/HOME/LANG and drops every GIT_*", "PATH" in ge and "HOME" in ge and ge.get("LANG") == "C" and not [k for k in ge if k.startswith("GIT_")], sorted(ge))
GR = TMP / "gitenv" / "dev"; gp = GR / "repo"; gp.mkdir(parents=True)
subprocess.run(["git", "init", "-q", str(gp)], check=True, env=ge)
write(gp / "docs" / "STATUS.md", "s")
subprocess.run(["git", "-C", str(gp), "add", "-A"], check=True, env=ge)
pr = projects.list_projects(GR)[0]
check("a GIT_DIR/GIT_WORK_TREE in the caller's environment does not change status_tracked", projects.status_tracked(pr) is True)
seen = []
real_run = projects._run_git
projects._run_git = lambda argv, cwd: (seen.append(argv), (0, ""))[1]
try:
    projects.status_tracked(pr)
finally:
    projects._run_git = real_run
check("status_tracked runs the hardened argv", seen and seen[0][:5] == projects.GIT_PREFIX and seen[0][5:] == ["ls-files"], seen)
os.environ.clear(); os.environ.update(saved)

# ---------- held rule, hub, scopes ----------
S = TMP / "scope"; sdev = S / "dev"; ws = sdev / "AI-Workspace"; mainws = ws
def repo(name, agents=True, claude=True, status=True, stack=None, track_case="docs/STATUS.md"):
    d = sdev / name
    subprocess.run(["git", "init", "-q", str(d)], check=True)
    if agents: write(d / "AGENTS.md", "# x\n" + (stack or ""))
    if claude: (d / ".claude").mkdir()
    if status:
        write(d / track_case, "s")
        subprocess.run(["git", "-C", str(d), "add", "-A"], check=True)
repo("AI-Workspace"); repo("full"); repo("held"); repo("heldspace"); repo("ios", stack="Stack rules — iOS\n"); repo("notes", stack="Stack rules — Notes\n")
repo("nostatus", status=False); repo("noclaude", claude=False); repo("noagents", agents=False); repo("lowcase", track_case="docs/status.md")
(sdev / "plain").mkdir(); write(sdev / "plain" / "AGENTS.md", "x")           # not git: not a project
(S / "ext").mkdir(); subprocess.run(["git", "init", "-q", str(S / "ext" / "r")], check=True)
write(S / "ext" / "r" / "AGENTS.md", "x"); (S / "ext" / "r" / ".claude").mkdir()
write(S / "ext" / "r" / "docs" / "STATUS.md", "s"); subprocess.run(["git", "-C", str(S / "ext" / "r"), "add", "-A"], check=True)
os.symlink(S / "ext" / "r", sdev / "symproj")
write(ws / "config" / "ci-hold.txt", "# comment\n\n  held  \nheldspace \n#heldcomment\r\nnot-a-project\n")
write(ws / "config" / "extra", "")
lst = projects.list_projects(sdev, ws)
by = {p.name: p for p in lst}
check("held rule: trimmed lines, comments and blanks ignored", projects.held_names(ws) == ["held", "heldspace", "not-a-project"], projects.held_names(ws))
check("held attribute (trailing space holds)", by["held"].held and by["heldspace"].held and not by["full"].held)
check("hub: the workspace project is the hub", [p.name for p in lst if p.hub] == ["AI-Workspace"])
check("symlink attribute", by["symproj"].symlink and not by["full"].symlink)
nm_ = lambda k: [p.name for p in projects.scope(lst, k)]
check("scope all == every project", nm_("all") == [p.name for p in lst])
check("scope template", nm_("template") == ["full", "ios", "lowcase", "nostatus", "notes"], nm_("template"))
check("scope standards (the hub is excluded since Phase 3a: its docs/standards is the source)", nm_("standards") == ["full", "ios", "lowcase", "noclaude", "notes"], nm_("standards"))
check("scope ci", nm_("ci") == ["full", "lowcase", "noclaude"], nm_("ci"))
# migrated projects (Phase 3a): the managed block in CLAUDE.md replaces the AGENTS.md test; Stack rules are read from either file
def crepo(name, claude_text, agents_text=None):
    d = sdev / name
    subprocess.run(["git", "init", "-q", str(d)], check=True)
    write(d / "CLAUDE.md", claude_text)
    if agents_text is not None: write(d / "AGENTS.md", agents_text)
    (d / ".claude").mkdir(); write(d / "docs" / "STATUS.md", "s")
    subprocess.run(["git", "-C", str(d), "add", "-A"], check=True)
MARK = "<!-- SHIPMIRACLE-STANDARD BEGIN v2 (managed by shipm sync; edit AI-Workspace/docs/standards/base.md) -->\nx\n<!-- SHIPMIRACLE-STANDARD END -->\n"
crepo("migr", "# m\n" + MARK); crepo("migr-ios", "# m\n" + MARK + "\n## Stack rules \u2014 iOS (Swift / SwiftUI)\n")
crepo("claude-only", "# no marker, no AGENTS.md\n"); crepo("old-ios-agents", "@AGENTS.md\n", "# x\nStack rules \u2014 iOS\n")
crepo("migr-notes-agents", "# m\n" + MARK, "# x\nStack rules \u2014 Notes\n")
lst2 = projects.list_projects(sdev, ws)
nm2 = lambda k: [p.name for p in projects.scope(lst2, k)]
check("migrated: template scope takes a CLAUDE.md with the managed block and no AGENTS.md", "migr" in nm2("template") and "migr-ios" in nm2("template"), nm2("template"))
check("migrated: a CLAUDE.md without the block and without AGENTS.md is in no scope", all("claude-only" not in nm2(k) for k in ("template", "standards", "ci")))
check("migrated: standards scope", "migr" in nm2("standards") and "migr-ios" in nm2("standards") and "claude-only" not in nm2("standards"))
check("migrated: ci scope takes migr, drops iOS/Notes stack rules found in CLAUDE.md or in AGENTS.md",
      "migr" in nm2("ci") and "migr-ios" not in nm2("ci") and "old-ios-agents" not in nm2("ci") and "migr-notes-agents" not in nm2("ci"), nm2("ci"))
check("old projects keep their scope (nothing dropped by the new rule)", all(n in nm2("standards") for n in nm_("standards")) and all(n in nm2("ci") for n in nm_("ci")))
for n in ("migr", "migr-ios", "claude-only", "old-ios-agents", "migr-notes-agents"):
    shutil.rmtree(sdev / n, ignore_errors=True)
try:
    projects.scope(lst, "bogus"); raised = False
except UsageError:
    raised = True
check("unknown scope raises UsageError", raised)
# git seam: a failing git means STATUS is not tracked
orig = projects._run_git
projects._run_git = lambda argv, cwd: (128, "")
check("git failure -> not tracked -> excluded from standards and ci", nm_("standards") == [] and nm_("ci") == [])
projects._run_git = orig
# hub from a worktree-style workspace: .git file pointing to a main checkout in dev
W = TMP / "hub"; hdev = W / "dev"; (hdev / "Main" / ".git" / "worktrees" / "w").mkdir(parents=True)
hws = W / "elsewhere" / "wt"; hws.mkdir(parents=True); write(hws / ".git", "gitdir: %s/.git/worktrees/w\n" % (hdev / "Main"))
check("hub: a worktree workspace marks its main checkout", [p.name for p in projects.list_projects(hdev, hws) if p.hub] == ["Main"])
check("hub: a workspace outside dev marks nothing", [p.name for p in projects.list_projects(hdev, W / "elsewhere") if p.hub] == [])
check("held file absent -> nobody held", not any(p.held for p in projects.list_projects(hdev, W)))

# defaults read SHIPMIRACLE_DEV / SHIPMIRACLE_WS under SHIPMIRACLE_TEST=1
os.environ["SHIPMIRACLE_DEV"] = str(sdev); os.environ["SHIPMIRACLE_WS"] = str(ws)
check("default dev comes from SHIPMIRACLE_DEV under SHIPMIRACLE_TEST", projects.names() == projects.names(sdev) and any(p.hub for p in projects.list_projects()))

shutil.rmtree(TMP, ignore_errors=True)
print("\nFAILED: %d" % fails if fails else "\nALL PASS"); sys.exit(1 if fails else 0)
