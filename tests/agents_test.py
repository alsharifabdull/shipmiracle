#!/usr/bin/env python3
"""agents_test: bin/agent-check (a shim over shipm agents check) rules (model rule, DoD section, maxTurns), the ten master agent files,
and the scripts that move agent files around: promote-agent (promote), apply-template (no_backup, legacy refresh, userlevel copies nothing).
Run with /usr/bin/python3 (3.9)."""
import glob, os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); WS = os.path.dirname(HERE)
CHK = os.path.join(WS, "bin", "agent-check")
fails = 0
def check(name, ok, detail=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else "  " + str(detail)))
    fails += 0 if ok else 1
GOOD = "---\nname: x\nmodel: sonnet\nmaxTurns: 20\n---\nModel reason: t\nFlow role: {role}\n\n## DoD\nResult: x\nVerdict: PASS | FAIL | BLOCKED | NOT TESTED\n"
def run(text):
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "a.md"); open(p, "w").write(text)
        r = subprocess.run([sys.executable, CHK, p], capture_output=True, text=True)
        return r.returncode, r.stdout
rc, out = run(GOOD.format(role="build")); check("model_rule: a conforming file passes", rc == 0 and out == "", out)
rc, out = run(GOOD.format(role="build").replace("sonnet", "inherit")); check("model_rule: inherit is refused", rc == 1 and "inherit" in out, out)
rc, out = run(GOOD.format(role="build").replace("Model reason: t\n", "")); check("model_rule: missing Model reason is refused", rc == 1 and "Model reason" in out, out)
rc, out = run(GOOD.format(role="bogus")); check("model_rule: invalid Flow role is refused", rc == 1 and "Flow role" in out, out)
rc, out = run(GOOD.format(role="build").replace("## DoD", "## Done")); check("dod: missing DoD heading is a warn-level [dod] problem (exit 3)", rc == 3 and "[dod]" in out and "DoD" in out, out)
rc, out = run(GOOD.format(role="build").replace("Verdict:", "Outcome:")); check("dod: missing Verdict line is a warn-level [dod] problem (exit 3)", rc == 3 and "[dod]" in out and "Verdict" in out, out)
rc, out = run(GOOD.format(role="build").replace("maxTurns: 20\n", "")); check("maxTurns: missing is a warn-level [dod] problem (exit 3)", rc == 3 and "[dod]" in out and "maxTurns is missing" in out, out)
rc, out = run(GOOD.format(role="build").replace("maxTurns: 20", "maxTurns: many")); check("maxTurns: non-integer is a warn-level [dod] problem (exit 3)", rc == 3 and "[dod]" in out and "maxTurns is many" in out, out)
rc, out = run(GOOD.format(role="build").replace("maxTurns: 20", "maxTurns: 0")); check("maxTurns: zero is a warn-level [dod] problem (exit 3)", rc == 3 and "[dod]" in out and "maxTurns" in out, out)
rc, out = run(GOOD.format(role="build").replace("sonnet", "inherit").replace("## DoD", "## Done")); lines = out.strip().splitlines()
check("split: a file with both problems prints a model line and a separate [dod] line, exit 1", rc == 1 and len(lines) == 2 and "[dod]" not in lines[0] and "[dod]" in lines[1], out)
rc, out = run(GOOD.format(role="route").replace("maxTurns: 20\n", "")); check("maxTurns: the lead (route) needs none", rc == 0, out)
rc, out = run(GOOD.format(role="route").replace("## DoD", "## Done")); check("dod: the lead still needs DoD", rc == 3 and "[dod]" in out and "DoD" in out, out)
rc, out = run(GOOD.format(role="report")); check("model_rule: Flow role report is accepted", rc == 0, out)
rc, out = run(GOOD.format(role="support")); check("model_rule: Flow role support is accepted", rc == 0, out)
files = sorted(glob.glob(os.path.join(WS, "agents", "claude", "*.md")))
check("master: 10 agent files", len(files) == 10, len(files))
r = subprocess.run([sys.executable, CHK] + files, capture_output=True, text=True); check("master: all 10 pass agent-check", r.returncode == 0, r.stdout)
EXP = {"builder": 80, "builder-frontend": 80, "builder-backend": 80, "builder-ops": 80, "verifier": 60, "planner": 40, "reviewer": 40,
       "designer": 40, "scoper": 20, "reporter": 5}
import re
check("master: the names are the ten function roles", sorted(os.path.basename(f)[:-3] for f in files) == sorted(EXP), sorted(os.path.basename(f)[:-3] for f in files))
for f in files:
    n = os.path.basename(f)[:-3]; s = open(f).read(); m = re.search(r"^maxTurns:\s*(\d+)", s, re.M)
    check(f"master: {n} maxTurns", (int(m.group(1)) if m else None) == EXP.get(n), m and m.group(1))
    rev, rep = n == "reviewer", n == "reporter"
    check(f"master: {n} DoD verdict set", (("ACCEPT | ACCEPT WITH FIXES | REMEDIATE" in s) == rev) and (("Verdict: PASS | BLOCKED" in s) == rep) and (("Lens:" in s) == rev))
    if n.startswith("builder"):
        check(f"master: {n} turn-70 line", "by turn 70" in s)
    check(f"master: {n} has no 'check docs/SKILLS.md' line and no AGENTS.md reference", "docs/SKILLS.md" not in s and "AGENTS.md" not in s)

# ---- promote-agent and apply-template run from a temp copy of the workspace (they write into their own workspace and commit there)
import json, shutil
TMP = tempfile.mkdtemp(prefix="agents-scripts-")
GENV = dict(os.environ, GIT_AUTHOR_NAME="T", GIT_AUTHOR_EMAIL="t@example.com", GIT_COMMITTER_NAME="T", GIT_COMMITTER_EMAIL="t@example.com", GIT_CONFIG_GLOBAL=os.devnull)
def git(cwd, *a):
    return subprocess.run(["git", "-C", str(cwd)] + list(a), env=GENV, capture_output=True, text=True).stdout.strip()
def make_ws(name):
    w = os.path.join(TMP, name)
    for d in ("bin", "shipmiracle", "agents", "templates", "config"):
        shutil.copytree(os.path.join(WS, d), os.path.join(w, d), ignore=shutil.ignore_patterns("__pycache__"))
    os.makedirs(os.path.join(w, "docs")); shutil.copytree(os.path.join(WS, "docs", "standards"), os.path.join(w, "docs", "standards"))
    subprocess.run(["git", "init", "-q", w], env=GENV); git(w, "add", "-A"); git(w, "commit", "-qm", "init", "--no-verify")
    return w
def make_proj(home, name, agents_files, status=True):
    d = os.path.join(home, "Developer", name); os.makedirs(os.path.join(d, ".claude", "agents"))
    subprocess.run(["git", "init", "-q", d], env=GENV)
    open(os.path.join(d, "CLAUDE.md"), "w").write("# %s\n<!-- SHIPMIRACLE-STANDARD BEGIN v2 (x) -->\nx\n<!-- SHIPMIRACLE-STANDARD END -->\n" % name)
    os.makedirs(os.path.join(d, "docs"))
    open(os.path.join(d, "docs", "STATUS.md"), "w").write("Updated: x\n")
    for fn, t in agents_files.items():
        open(os.path.join(d, ".claude", "agents", fn + ".md"), "wb").write(t if isinstance(t, bytes) else t.encode())
    git(d, "add", "-A"); git(d, "commit", "-qm", "init", "--no-verify")
    return d
def env_for(home, layout=None):
    cfg = os.path.join(home, "cfg"); e = dict(GENV, HOME=home, SHIPMIRACLE_TEST="1", SHIPMIRACLE_HOME=home, SHIPMIRACLE_DEV=os.path.join(home, "Developer"), SHIPMIRACLE_CONFIG=cfg, SHIPMIRACLE_STATE=os.path.join(home, "state"))
    e.pop("CLAUDECODE", None)
    e.pop("SHIPMIRACLE_WS", None)     # a caller's isolated SHIPMIRACLE_WS (empty temp dir) must not replace the workspace under test
    return e
def set_layout(w, home, v):
    return subprocess.run([sys.executable, os.path.join(w, "bin", "shipm"), "config", "set", "agents.layout", v], env=env_for(home), capture_output=True, text=True)
AG = lambda n, role="build", extra="": ("---\nname: %s\ndescription: Use when testing %s. Not for real work.\ntools: Read, Grep\nmodel: sonnet\nmaxTurns: 20\n%s---\nModel reason: test\nFlow role: %s\n\n## DoD\nResult: x\nVerdict: PASS | FAIL | BLOCKED | NOT TESTED\n" % (n, n, extra, role))

# promote: legacy layout
w = make_ws("ws-promote"); home = os.path.join(TMP, "h1"); os.makedirs(home)
pa = make_proj(home, "projA", {"my-helper": AG("my-helper")}); pb = make_proj(home, "projB", {"my-helper": AG("my-helper")})
PR = os.path.join(w, "bin", "promote-agent")
r = subprocess.run([PR, "--candidates"], env=env_for(home), capture_output=True, text=True)
check("promote: --candidates lists a project-only agent that exists in 2 projects", r.returncode == 0 and "my-helper" in r.stdout and "in 2 projects" in r.stdout, r.stdout)
open(os.path.join(pa, ".claude/agents/bad.md"), "w").write(AG("bad").replace("model: sonnet", "model: inherit"))
r = subprocess.run([PR, pa, "bad"], env=env_for(home), capture_output=True, text=True)
check("promote: a file that breaks the model rule is refused (exit 2), nothing copied", r.returncode == 2 and not os.path.exists(os.path.join(w, "agents/claude/bad.md")), r.stdout + r.stderr)
open(os.path.join(pa, ".claude/agents/wide.md"), "w").write(AG("wide").replace("Use when testing wide. Not for real work.", "Helps a lot."))
r = subprocess.run([PR, pa, "wide"], env=env_for(home), capture_output=True, text=True)
check("promote: a file that fails the master rules (description) is refused (exit 2)", r.returncode == 2 and not os.path.exists(os.path.join(w, "agents/claude/wide.md")), r.stdout + r.stderr)
plain2 = os.path.join(home, "Developer", "clonedrepo"); os.makedirs(plain2); subprocess.run(["git", "init", "-q", plain2], env=GENV); open(os.path.join(plain2, "CLAUDE.md"), "w").write("# not ours\n")
r = subprocess.run([PR, pa, "my-helper"], env=env_for(home), capture_output=True, text=True)
check("promote: the rollout leaves a folder with only a plain CLAUDE.md untouched", sorted(os.listdir(plain2)) == [".git", "CLAUDE.md"] and git(plain2, "config", "core.hooksPath") == "", os.listdir(plain2))
check("promote: check -> copy into agents/claude -> commit", r.returncode == 0 and os.path.isfile(os.path.join(w, "agents/claude/my-helper.md")) and git(w, "log", "-1", "--format=%s") == "Promote agent my-helper to the master team", r.stdout + r.stderr)
check("promote: prints `shipm agents install` as the owner step and never runs it", "OWNER STEP" in r.stdout and "shipm agents install" in r.stdout and not os.path.exists(os.path.join(home, ".claude", "agents")), r.stdout)
check("promote: legacy layout keeps the project's identical copy", os.path.isfile(os.path.join(pa, ".claude/agents/my-helper.md")) and "Layout is legacy" in r.stdout)
check("promote: only the new master file was committed", git(w, "show", "--stat", "--format=", "HEAD").count("|") == 1, git(w, "show", "--stat", "--format=", "HEAD"))
# promote: userlevel layout, identical copy deleted
w2 = make_ws("ws-promote2"); home2 = os.path.join(TMP, "h2"); os.makedirs(home2)
pc = make_proj(home2, "projC", {"my-helper": AG("my-helper"), "other-helper": AG("other-helper")})
set_layout(w2, home2, "userlevel")
r = subprocess.run([os.path.join(w2, "bin", "promote-agent"), pc, "my-helper"], env=env_for(home2), capture_output=True, text=True)
check("promote: userlevel layout deletes the project's copy when it equals the master", r.returncode == 0 and not os.path.exists(os.path.join(pc, ".claude/agents/my-helper.md")) and os.path.isfile(os.path.join(w2, "agents/claude/my-helper.md")), r.stdout + r.stderr)
check("promote: ...and does not roll out through apply-template", "Rolling it out" not in r.stdout)
# a master that already exists and differs: the project's copy gets overrides:
open(os.path.join(pc, ".claude/agents/builder.md"), "w").write(AG("builder", extra="").replace("Not for real work", "Not for things"))
r = subprocess.run([os.path.join(w2, "bin", "promote-agent"), pc, "builder"], env=env_for(home2), capture_output=True, text=True)
check("promote: an existing master that differs -> the project's copy gets an overrides: line", "already a master" in r.stdout and "overrides: builder" in open(os.path.join(pc, ".claude/agents/builder.md")).read(), r.stdout + r.stderr)

# apply-template
legacy_dir = os.path.join(HERE, "fixtures", "agents", "legacy")
OLDF = {os.path.basename(p)[:-3]: open(p, "rb").read() for p in glob.glob(os.path.join(legacy_dir, "*.md"))}
w3 = make_ws("ws-apply")
# history with the old masters so that install records the legacy hashes: old files committed in the workspace's own history
for n, b in OLDF.items(): open(os.path.join(w3, "agents/claude", n + ".md"), "wb").write(b)
git(w3, "add", "-A"); git(w3, "commit", "-qm", "old masters", "--no-verify")
for n in OLDF: os.unlink(os.path.join(w3, "agents/claude", n + ".md"))
git(w3, "add", "-A"); git(w3, "commit", "-qm", "old masters removed", "--no-verify")
home3 = os.path.join(TMP, "h3"); os.makedirs(home3)
ENV3 = env_for(home3)
r = subprocess.run([sys.executable, os.path.join(w3, "bin", "shipm"), "agents", "install"], env=ENV3, capture_output=True, text=True)
check("apply-template setup: install recorded the legacy hashes", r.returncode == 0 and "qa-engineer=5" in r.stdout, r.stdout + r.stderr)
mine = AG("shaj-qa", "test")
pd = make_proj(home3, "oldteam", dict({n: b for n, b in OLDF.items() if n in ("qa-engineer", "product-analyst", "devops-sre")}, **{"backend-engineer": OLDF["backend-engineer"] + b"\nproject edit\n", "shaj-qa": mine}))
AT = os.path.join(w3, "bin", "apply-template")
r = subprocess.run([AT, pd], env=ENV3, capture_output=True, text=True, cwd=pd)
after = sorted(os.listdir(os.path.join(pd, ".claude/agents")))
want = sorted(["backend-engineer.md", "shaj-qa.md"] + [os.path.basename(f) for f in glob.glob(os.path.join(w3, "agents/claude/*.md"))])
check("apply-template legacy: the ten new-name masters are refreshed in, old-name exact copies deleted, modified and project-only kept", after == want, (after, r.stdout[-300:], r.stderr[-200:]))
check("apply-template legacy: prints what it removed", "removed old-name agent copy .claude/agents/qa-engineer.md" in r.stdout and "removed old-name agent copy .claude/agents/product-analyst.md" in r.stdout, r.stdout)
check("apply-template legacy: the modified old-name file was kept untouched", open(os.path.join(pd, ".claude/agents/backend-engineer.md"), "rb").read().endswith(b"project edit\n"))
bk = os.path.join(pd, ".claude", "_backup")
check("apply-template no_backup: replacing agent files made no _backup copy of any agent", not glob.glob(os.path.join(bk, "*", ".claude", "agents", "*")), os.listdir(bk) if os.path.isdir(bk) else None)
r2 = subprocess.run([AT, pd], env=ENV3, capture_output=True, text=True, cwd=pd)
check("apply-template is idempotent (second run: nothing updated about agents)", ".claude/agents" not in r2.stdout and "removed old-name" not in r2.stdout, r2.stdout)
# userlevel copies nothing
home4 = os.path.join(TMP, "h4"); os.makedirs(home4); ENV4 = env_for(home4)
set_layout(w3, home4, "userlevel")
pd2 = make_proj(home4, "ulteam", {"qa-engineer": OLDF["qa-engineer"]})
r = subprocess.run([AT, pd2], env=ENV4, capture_output=True, text=True, cwd=pd2)
check("apply-template userlevel: no agent is copied in and the old copy is left for migrate-team", sorted(os.listdir(os.path.join(pd2, ".claude/agents"))) == ["qa-engineer.md"] and "agents/" not in r.stdout, (r.stdout, r.stderr[-200:]))
# apply-template guard: same test as has_std in sync-tools (AGENTS.md, or CLAUDE.md with the SHIPMIRACLE-STANDARD block)
home5 = os.path.join(TMP, "h5"); os.makedirs(os.path.join(home5, "Developer")); ENV5 = env_for(home5)
plain = os.path.join(home5, "Developer", "cloned"); os.makedirs(plain); subprocess.run(["git", "init", "-q", plain], env=GENV)
open(os.path.join(plain, "CLAUDE.md"), "w").write("# someone else's repo\n"); os.makedirs(os.path.join(plain, "docs")); open(os.path.join(plain, "docs", "STATUS.md"), "w").write("x\n")
git(plain, "add", "-A"); git(plain, "commit", "-qm", "i", "--no-verify")
snap = lambda d: sorted(os.path.relpath(os.path.join(a, f), d) for a, _, fs in os.walk(d) if ".git" + os.sep not in a + os.sep for f in fs)
before = (snap(plain), git(plain, "config", "core.hooksPath"))
r = subprocess.run([AT, plain], env=ENV5, capture_output=True, text=True, cwd=plain)
check("apply-template: a folder with only a plain CLAUDE.md is skipped untouched (no hooks, no core.hooksPath)", r.returncode == 0 and "skip" in r.stdout and (snap(plain), git(plain, "config", "core.hooksPath")) == before and git(plain, "config", "core.hooksPath") == "", r.stdout + r.stderr)
blk = make_proj(home5, "withblock", {})
r = subprocess.run([AT, blk], env=ENV5, capture_output=True, text=True, cwd=blk)
check("apply-template: a folder whose CLAUDE.md has the SHIPMIRACLE-STANDARD block is processed", os.path.isdir(os.path.join(blk, ".githooks")) and git(blk, "config", "core.hooksPath") == ".githooks", r.stdout + r.stderr)
# apply-template legacy: a project's own modified or overrides-marked copy of a new-name master
open(os.path.join(pd, ".claude/agents/builder.md"), "a").write("\nproject edit of builder\n")
ov = open(os.path.join(w3, "agents/claude/planner.md")).read().replace("\n---\n", "\noverrides: planner\n---\n", 1) + "\nmy planner\n"
open(os.path.join(pd, ".claude/agents/planner.md"), "w").write(ov)
r3 = subprocess.run([AT, pd], env=ENV3, capture_output=True, text=True, cwd=pd)
bks = glob.glob(os.path.join(pd, ".claude", "_backup", "*", ".claude", "agents", "builder.md"))
check("apply-template legacy: a project-modified copy of a master is backed up before it is replaced", len(bks) == 1 and open(bks[0]).read().endswith("project edit of builder\n") and open(os.path.join(pd, ".claude/agents/builder.md"), "rb").read() == open(os.path.join(w3, "agents/claude/builder.md"), "rb").read(), r3.stdout)
check("apply-template legacy: a copy carrying overrides: is kept untouched", open(os.path.join(pd, ".claude/agents/planner.md")).read() == ov and "kept project's own .claude/agents/planner.md" in r3.stdout, r3.stdout)

shutil.rmtree(TMP, ignore_errors=True)
sys.exit(1 if fails else 0)
