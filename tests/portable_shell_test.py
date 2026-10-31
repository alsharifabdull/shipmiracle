#!/usr/bin/env python3
"""Portable shell (cross-platform task 2, 21 Oct 2026): the project template hooks, bin/apply-template, bin/doctor and bin/shipm-chat must not use
BSD-only forms (`stat -f %m`, `sed -i ''`, a bare /usr/bin/shasum). Proof: (a) a static scan; (b) the Stop gate and save-plan decide exactly as before
with a PATH where `stat` and a BSD-style `sed -i ''` FAIL like on GNU (a use of either breaks the run); (c) `date -r FILE +%s` equals the real mtime;
(d) apply-template fills docs/SKILLS.md without sed -i. Runs on macOS and Linux. Run: python3 tests/portable_shell_test.py"""
import os, pathlib, re, shutil, subprocess, sys, tempfile, time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
import shipmiracle_isolation as iso  # noqa: E402

fails = 0


def check(name, ok, info=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(info)[:1200]))
    fails += 0 if ok else 1


def run(cmd, env, cwd=None, inp=""):
    return subprocess.run(cmd, env=env, cwd=cwd, input=inp, capture_output=True, text=True, timeout=60)


# ---- (a) static scan ------------------------------------------------------------------------------------------------
files = [ROOT / "templates/base/.claude/hooks/stop-gate.sh", ROOT / "templates/base/.claude/hooks/save-plan.sh", ROOT / "bin/apply-template",
         ROOT / "bin/doctor", ROOT / "bin/shipm-chat"]
for f in sorted((ROOT / "templates/base/.claude/hooks").glob("*.sh")) + sorted((ROOT / "templates/base/.githooks").glob("*")):
    if f not in files and f.is_file():
        files.append(f)
for f in files:
    code = [l for l in f.read_text(errors="replace").splitlines() if not l.lstrip().startswith("#")]
    bad = [l for l in code if re.search(r"\bstat\s+-f\b|sed\s+-i\s+''|sed\s+-i\s+\"\"", l)]
    check("no BSD-only stat/sed in " + str(f.relative_to(ROOT)), not bad, bad)
chat = (ROOT / "bin/shipm-chat").read_text()
check("shipm-chat hashes through $SHA256 (shasum or sha256sum), not a bare /usr/bin/shasum call", "| /usr/bin/shasum" not in chat and "$SHA256 |" in chat)

# ---- shim PATH: stat and BSD-style sed -i '' fail, as on GNU ---------------------------------------------------------
tmp = pathlib.Path(tempfile.mkdtemp(prefix="portsh-")).resolve()
shim = tmp / "shim"
shim.mkdir()
(shim / "stat").write_text('#!/bin/sh\necho "stat shim: GNU stat -f is file-system status; use date -r" >&2\nexit 64\n')
(shim / "sed").write_text('#!/bin/sh\nprev=""\nfor a in "$@"; do\n  if [ "$prev" = "-i" ] && [ -z "$a" ]; then echo "sed shim: GNU sed -i takes no empty suffix argument" >&2; exit 65; fi\n  prev="$a"\ndone\nexec /usr/bin/sed "$@"\n')
for n in ("stat", "sed"):
    os.chmod(shim / n, 0o755)
if not os.path.exists("/usr/bin/sed"):
    (shim / "sed").write_text((shim / "sed").read_text().replace("/usr/bin/sed", "/bin/sed"))
check("shim self-check: stat and sed -i '' fail", subprocess.run([str(shim / "stat"), "-f", "%m", "/"], capture_output=True).returncode == 64
      and subprocess.run([str(shim / "sed"), "-i", "", "s/a/b/", "/dev/null"], capture_output=True).returncode == 65)

env0, root = iso.isolated_env(root=str(tmp / "iso"))
home = pathlib.Path(env0["HOME"])
env_shim = dict(env0, PATH=str(shim) + os.pathsep + env0.get("PATH", "/usr/bin:/bin"))
env_plain = dict(env0)

# ---- (c) mtime helper -------------------------------------------------------------------------------------------------
f = tmp / "m.txt"
f.write_text("x")
os.utime(f, (1700000000, 1700000123))
r = run(["bash", "-c", 'mtime() { date -r "$1" +%s 2>/dev/null; }; mtime "$1"', "_", str(f)], env_plain)
check("date -r FILE +%s equals the file's mtime", r.stdout.strip() == "1700000123", (r.stdout, r.stderr))

# ---- (b) Stop gate ----------------------------------------------------------------------------------------------------
def make_project(name):
    p = tmp / name
    (p / "docs").mkdir(parents=True)
    g = lambda *a: subprocess.run(["git", *a], cwd=p, env=env_plain, capture_output=True, text=True)
    g("init", "-q")
    (p / "docs/STATUS.md").write_text("Updated: %s · by: test · mode: BUILD\n" % time.strftime("%Y-%m-%d"))
    (p / "src.txt").write_text("a\n")
    g("add", "-A"); g("commit", "-qm", "init")
    (p / "src.txt").write_text("b\n")                      # a changed source file
    return p


gate = ROOT / "templates/base/.claude/hooks/stop-gate.sh"
outcome = {}
for label, env in (("plain PATH", env_plain), ("GNU-like PATH (stat, sed -i '' fail)", env_shim)):
    for fresh in (True, False):
        p = make_project("p-%s-%s" % ("shim" if env is env_shim else "plain", "new" if fresh else "old"))
        now = time.time()
        os.utime(p / "src.txt", (now - 100, now - 100))
        os.utime(p / "docs/STATUS.md", (now, now) if fresh else (now - 500, now - 500))
        r = run(["bash", str(gate)], dict(env, CLAUDE_PROJECT_DIR=str(p)), cwd=p, inp="{}")
        outcome[(label, fresh)] = (r.returncode, "older than the latest" in r.stderr)
        check("stop-gate [%s] STATUS %s than the source -> %s" % (label, "newer" if fresh else "older", "allowed" if fresh else "blocked (exit 2)"),
              (r.returncode == 0 and not r.stderr) if fresh else (r.returncode == 2 and "older than the latest" in r.stderr), (r.returncode, r.stderr))
check("stop-gate decides the same on both PATHs", all(outcome[(a, x)] == outcome[(b, x)] for x in (True, False)
      for a, b in [("plain PATH", "GNU-like PATH (stat, sed -i '' fail)")]), outcome)

# ---- save-plan ----------------------------------------------------------------------------------------------------------
sp = ROOT / "templates/base/.claude/hooks/save-plan.sh"
for age, want in ((60, True), (3 * 3600, False)):
    p = tmp / ("sp-%d" % age)
    p.mkdir()
    (home / ".claude/plans").mkdir(parents=True, exist_ok=True)
    for old in (home / ".claude/plans").glob("*.md"):
        old.unlink()
    pl = home / ".claude/plans/plan-a-b.md"
    pl.write_text("# plan\n")
    t = time.time() - age
    os.utime(pl, (t, t))
    r = run(["bash", str(sp)], dict(env_shim, CLAUDE_PROJECT_DIR=str(p)), cwd=p)
    saved = list((p / "docs/plans").glob("*.md")) if (p / "docs/plans").exists() else []
    check("save-plan with a %d s old plan on the GNU-like PATH: %s" % (age, "saved" if want else "ignored"), r.returncode == 0 and bool(saved) == want, (r.returncode, r.stderr, saved))

# ---- (d) apply-template: SKILLS.md placeholder without sed -i --------------------------------------------------------------
proj = tmp / "my-proj"
(proj / "docs").mkdir(parents=True)
subprocess.run(["git", "init", "-q"], cwd=proj, env=env_plain)
(proj / "AGENTS.md").write_text("# a\n")
(proj / "docs/STATUS.md").write_text("Updated: x\n")
subprocess.run(["git", "add", "-A"], cwd=proj, env=env_plain)
subprocess.run(["git", "commit", "-qm", "i"], cwd=proj, env=env_plain, capture_output=True)
r = run(["bash", str(ROOT / "bin/apply-template"), str(proj)], env_shim)
sk = proj / "docs/SKILLS.md"
txt = sk.read_text() if sk.exists() else ""
check("apply-template on the GNU-like PATH writes docs/SKILLS.md with the project name", sk.exists() and "my-proj" in txt and "{{PROJECT_NAME}}" not in txt and not (proj / "docs/SKILLS.md.tmp").exists(), (r.returncode, r.stdout[-300:], r.stderr[-300:]))

# ---- shipm-chat hash step on a PATH-less sha256sum-only machine is covered by the static check; run its syntax check ----------
check("bash -n on the changed scripts", all(subprocess.run(["bash", "-n", str(x)], capture_output=True).returncode == 0 for x in files if x.suffix in ("", ".sh") and x.name not in ("pre-commit", "post-commit", "pre-push") or x.suffix == ".sh"))

shutil.rmtree(tmp, ignore_errors=True)
print("FAILED %d" % fails if fails else "ALL PASS")
sys.exit(1 if fails else 0)
