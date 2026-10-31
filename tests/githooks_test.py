#!/usr/bin/env python3
"""Git hooks (.githooks/ of the workspace and templates/base/.githooks/): pre-commit (STATUS date check + gitleaks scan), post-commit (gitleaks scan, then
the background auto-push, PUSH-FAILED / PUSH-BLOCKED markers). Temp repos with a LOCAL bare remote and a STUB gitleaks; nothing touches a real project and
nothing is pushed anywhere else. Every background push is waited for (polling the bare remote with a timeout) before the temp folder is removed.
Run: python3 tests/githooks_test.py"""
import os, pathlib, re, shutil, subprocess, sys, tempfile, time

WS = pathlib.Path(__file__).resolve().parent.parent
TPL = WS / "templates/base/.githooks"
WSH = WS / ".githooks"
HAVE_WSH = (WSH / "post-commit").exists()          # the workspace's own hooks exist only in the owner's checkout; the template copies are what ships
fails = []; T = pathlib.Path(tempfile.mkdtemp()).resolve()
TODAY = time.strftime("%Y-%m-%d")


def check(n, c, info=""):
    print(("PASS " if c else "FAIL ") + n + ("" if c else " " + str(info)[:400]))
    if not c: fails.append(n)


# stub gitleaks: logs its arguments, behaves per GL_MODE (finding = exit 1 with a line on stdout, clean = exit 0)
STUB = T / "stubbin"; STUB.mkdir()
(STUB / "gitleaks").write_text('#!/bin/bash\necho "$*" >> "$GL_LOG"\n[[ "${GL_MODE:-clean}" == finding ]] && { echo "stub: leaks found"; exit 1; }\n[[ "${GL_MODE:-clean}" == error ]] && { echo "stub: scanner crashed" >&2; exit 126; }\nif [[ "${GL_MODE:-clean}" == content ]]; then opts=""; for a in "$@"; do [[ "$a" == --log-opts=* ]] && opts="${a#--log-opts=}"; done; if git log -p $opts 2>/dev/null | grep -q "SECRET-TOKEN"; then echo "stub: leaks found"; exit 1; fi; fi\nexit 0\n')
os.chmod(STUB / "gitleaks", 0o755)
BASE_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"
if shutil.which("gitleaks", path=BASE_PATH):
    print("SKIP-ALL a real gitleaks is in " + BASE_PATH); sys.exit(0)


AUTOPUSH = "true"          # the git.autopush value the hooks under test read


def env_for(mode, log):
    e = {k: v for k, v in os.environ.items() if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")}
    e.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t", GL_LOG=str(log), HOME=str(T / "home"))
    # P8: the post-commit hook pushes only when config git.autopush is on; a temp config folder (SHIPMIRACLE_TEST=1) says so, the engine is this checkout
    cfg = T / ("cfg-" + AUTOPUSH); cfg.mkdir(exist_ok=True); (cfg / "config.json").write_text('{"git.autopush": %s}\n' % AUTOPUSH)
    e.update(SHIPMIRACLE_TEST="1", SHIPMIRACLE_CONFIG=str(cfg), SHIPMIRACLE_ENGINE=str(WS), SHIPMIRACLE_STATE=str(T / "state"), SHIPMIRACLE_HOME=str(T / "home"))
    if mode == "missing":
        e["PATH"] = BASE_PATH
    else:
        e["PATH"] = str(STUB) + ":" + BASE_PATH; e["GL_MODE"] = mode
    return e


class Repo:
    def __init__(self, name, hooks, mode="clean", remote=True, bad_remote=False):
        self.d = T / name; self.d.mkdir(); self.log = T / (name + ".gl.log"); self.mode = mode
        self.env = env_for(mode, self.log)
        self.bare = T / (name + ".git")
        self.g("init", "-q", "-b", "main")
        self.g("config", "core.hooksPath", str(hooks))
        if remote:
            subprocess.run(["git", "init", "-q", "--bare", str(self.bare)], check=True, env=self.env)
            self.g("remote", "add", "origin", str(T / "nonexistent.git") if bad_remote else str(self.bare))

    def g(self, *a, check_=True):
        return subprocess.run(["git", "-C", str(self.d)] + list(a), capture_output=True, text=True, env=self.env, check=False, timeout=60)

    def put(self, rel, text):
        f = self.d / rel; f.parent.mkdir(parents=True, exist_ok=True); f.write_text(text); return f

    def commit(self, msg="c", *extra):
        self.g("add", "-A")
        return self.g("commit", "-q", "-m", msg, *extra)

    def remote_head(self):
        r = subprocess.run(["git", "--git-dir", str(self.bare), "rev-parse", "-q", "--verify", "refs/heads/main"], capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else ""

    def wait_pushed(self, timeout=20):
        """Poll the local bare remote until main matches HEAD (the push is a background job), then give the subshell a moment to finish."""
        end = time.time() + timeout
        head = self.g("rev-parse", "HEAD").stdout.strip()
        while time.time() < end:
            if self.remote_head() == head:
                time.sleep(0.4); return True
            time.sleep(0.2)
        return False

    def wait_marker(self, name, timeout=30):
        end = time.time() + timeout; f = self.d / ".git" / name
        while time.time() < end:
            if f.exists(): time.sleep(0.2); return True
            time.sleep(0.3)
        return False

    def gl_calls(self):
        try: return self.log.read_text().splitlines()
        except OSError: return []


# ---------------- post-commit (workspace copy and template copy are tested the same way)
for label, hooks_src in ((("workspace", WSH),) if HAVE_WSH else ()) + (("template", TPL),):
    hooks = T / ("post-only-" + label); hooks.mkdir()          # only the post-commit hook, so the pre-commit scan does not interfere
    shutil.copy2(hooks_src / "post-commit", hooks / "post-commit")
    r = Repo("post-clean-" + label, hooks, "clean"); r.put("a.txt", "1\n"); c = r.commit("one")
    check(f"{label} post-commit: clean scan -> pushed", c.returncode == 0 and r.wait_pushed(), c.stderr)
    check(f"{label} post-commit: clean scan -> no PUSH-BLOCKED, no PUSH-FAILED", not (r.d / ".git/PUSH-BLOCKED").exists() and not (r.d / ".git/PUSH-FAILED").exists())
    check(f"{label} post-commit: gitleaks called with detect --log-opts --redact --no-banner (root commit: all of HEAD, nothing on the remote yet)",
          r.gl_calls() == ["detect --log-opts=HEAD --not --remotes=origin --redact --no-banner"], r.gl_calls())
    r.put("a.txt", "2\n"); r.commit("two"); ok2 = r.wait_pushed()
    check(f"{label} post-commit: second commit scans every commit not on the remote (HEAD --not --remotes=origin) and pushes", ok2 and r.gl_calls()[-1] == "detect --log-opts=HEAD --not --remotes=origin --redact --no-banner", r.gl_calls())

    r = Repo("post-find-" + label, hooks, "finding"); r.put("a.txt", "secret\n"); c = r.commit("leak")
    check(f"{label} post-commit: finding -> commit itself succeeds", c.returncode == 0, c.stderr)
    pb = r.d / ".git/PUSH-BLOCKED"
    check(f"{label} post-commit: finding -> NO push", r.remote_head() == "" and not (time.sleep(1.0) or r.remote_head()))
    txt = pb.read_text() if pb.exists() else ""
    check(f"{label} post-commit: finding -> PUSH-BLOCKED with date + message", re.fullmatch(r"\d{4}-\d\d-\d\d \d\d:\d\d gitleaks finding in HEAD; see git log -1; branch=main sha=[0-9a-f]{40}\n", txt) is not None, txt)
    check(f"{label} post-commit: finding -> prints a line (stderr) and the redacted scan output", "auto-push blocked" in c.stderr and "stub: leaks found" in c.stderr and "PUSH-BLOCKED" in c.stderr, c.stderr)
    check(f"{label} post-commit: finding -> no PUSH-FAILED", not (r.d / ".git/PUSH-FAILED").exists())
    # the block stays open for the next commit while the leaking commit is unpushed (scan covers everything not pushed)
    r.env = env_for("clean", r.log); r.put("b.txt", "fixed\n"); r.commit("next")
    check(f"{label} post-commit: marker open + clean next commit -> scans all unpushed history (HEAD), clears marker, pushes",
          r.wait_pushed() and not pb.exists() and r.gl_calls()[-1] == "detect --log-opts=HEAD --not --remotes=origin --redact --no-banner", r.gl_calls())
    r.put("c.txt", "x\n"); r.env = env_for("finding", r.log); r.commit("again")
    check(f"{label} post-commit: new finding after a pushed history -> blocked again, remote not moved",
          pb.exists() and r.remote_head() != r.g("rev-parse", "HEAD").stdout.strip())

    r = Repo("post-miss-" + label, hooks, "missing"); r.put("a.txt", "1\n"); c = r.commit("one")
    check(f"{label} post-commit: gitleaks missing -> warns on stderr and still pushes",
          "gitleaks not installed: secret scan skipped" in c.stderr and r.wait_pushed() and not (r.d / ".git/PUSH-BLOCKED").exists(), c.stderr)

    r = Repo("post-fail-" + label, hooks, "clean", bad_remote=True); r.put("a.txt", "1\n"); c = r.commit("one")
    check(f"{label} post-commit: push failure -> PUSH-FAILED (unchanged logic, after one retry)", c.returncode == 0 and r.wait_marker("PUSH-FAILED"), c.stderr)
    time.sleep(0.5)

    r = Repo("post-nor-" + label, hooks, "finding", remote=False); r.put("a.txt", "1\n"); c = r.commit("one")
    check(f"{label} post-commit: no remote -> exits quietly, no scan, no markers", c.returncode == 0 and r.gl_calls() == [] and not (r.d / ".git/PUSH-BLOCKED").exists(), c.stderr)

# git.autopush off (the default of a fresh install): the commit succeeds, nothing is scanned, nothing is pushed
AUTOPUSH = "false"
for label, hooks_src in ((("workspace", WSH),) if HAVE_WSH else ()) + (("template", TPL),):
    hooks = T / ("post-off-" + label); hooks.mkdir(); shutil.copy2(hooks_src / "post-commit", hooks / "post-commit")
    r = Repo("off-" + label, hooks, "clean"); r.put("a.txt", "1\n"); c = r.commit("one")
    check(f"{label} post-commit: git.autopush off -> commit ok, no scan, no push, no markers",
          c.returncode == 0 and r.gl_calls() == [] and not (time.sleep(1.5) or r.remote_head()) and not (r.d / ".git/PUSH-FAILED").exists() and not (r.d / ".git/PUSH-BLOCKED").exists(), c.stderr)
AUTOPUSH = "true"

# ---------------- pre-commit: template (STATUS rules + scan) and workspace (scan only)
STATUS_OK = f"# Status\nUpdated: {TODAY} test\n"
STATUS_OLD = "# Status\nUpdated: 2020-01-01 test\n"


def pre(mode, files, status=None, name="pre", hooks=TPL, extra_staged_first=None):
    r = Repo(f"{name}-{mode}-{len(list(T.iterdir()))}", hooks, mode, remote=False)
    for k, v in files.items(): r.put(k, v)
    if status is not None: r.put("docs/STATUS.md", status)
    return r, r.commit("m")


r, c = pre("clean", {"src/app.py": "x=1\n"})
check("template pre-commit: source without STATUS -> blocked (STATUS rule unchanged)", c.returncode != 0 and "docs/STATUS.md is not staged" in c.stderr, c.stderr)
r, c = pre("clean", {"src/app.py": "x=1\n"}, STATUS_OLD)
check("template pre-commit: stale Updated: date -> blocked (unchanged)", c.returncode != 0 and f"'Updated:' line is not {TODAY}" in c.stderr, c.stderr)
r, c = pre("clean", {"src/app.py": "x=1\n"}, STATUS_OK)
check("template pre-commit: source + STATUS with today's date -> allowed", c.returncode == 0, c.stderr)
r, c = pre("clean", {"docs/notes.md": "n\n", "README.md": "r\n", ".claude/x.json": "{}\n", ".github/w.yml": "a: 1\n", ".githooks/h": "h\n"})
check("template pre-commit: docs/.claude/.github/.githooks/*.md only -> allowed without STATUS", c.returncode == 0, c.stderr)
r, c = pre("clean", {".co" + "dex/agents/a.toml": "x\n"})
check("template pre-commit: G10 the removed second engine's folder has no exemption any more (it is source) -> blocked without STATUS", c.returncode != 0 and "docs/STATUS.md is not staged" in c.stderr, c.stderr)
r, c = pre("clean", {".co" + "dex/a.toml": "x\n", "src/app.py": "x=1\n"})
check("template pre-commit: the second tool's folder + real source still needs STATUS", c.returncode != 0 and "docs/STATUS.md is not staged" in c.stderr, c.stderr)
r, c = pre("clean", {"src/app.py": "x=1\n"}, STATUS_OK)
check("template pre-commit: clean scan calls gitleaks protect --staged --redact --no-banner", r.gl_calls() == ["protect --staged --redact --no-banner"], r.gl_calls())
r, c = pre("finding", {"src/app.py": "key\n"}, STATUS_OK)
check("template pre-commit: finding -> commit blocked with a plain message, scan output shown", c.returncode != 0 and "possible secret" in c.stderr and "stub: leaks found" in c.stderr, c.stderr)
check("template pre-commit: finding -> nothing committed", r.g("rev-parse", "-q", "--verify", "HEAD").returncode != 0)
r, c = pre("finding", {"docs/notes.md": "key\n"})
check("template pre-commit: finding in a docs-only commit is still blocked (scan runs before the STATUS exemptions)", c.returncode != 0, c.stderr)
c2 = r.commit("override", "--no-verify")
check("template pre-commit: --no-verify overrides", c2.returncode == 0, c2.stderr)
r, c = pre("missing", {"src/app.py": "x=1\n"}, STATUS_OK)
check("template pre-commit: gitleaks missing -> warns on stderr, never blocks", c.returncode == 0 and "gitleaks not installed: secret scan skipped" in c.stderr, c.stderr)
r, c = pre("missing", {"src/app.py": "x=1\n"})
check("template pre-commit: gitleaks missing does not hide the STATUS rule", c.returncode != 0 and "docs/STATUS.md is not staged" in c.stderr and "gitleaks not installed" in c.stderr, c.stderr)

if HAVE_WSH:
    r, c = pre("clean", {"src/app.py": "x=1\n"}, hooks=WSH, name="wspre")
    check("workspace pre-commit: clean scan -> allowed (no STATUS rule here)", c.returncode == 0 and r.gl_calls() == ["protect --staged --redact --no-banner"], (c.stderr, r.gl_calls()))
    r, c = pre("finding", {"src/app.py": "key\n"}, hooks=WSH, name="wspre")
    check("workspace pre-commit: finding -> blocked", c.returncode != 0 and "possible secret" in c.stderr, c.stderr)
    r, c = pre("missing", {"src/app.py": "x=1\n"}, hooks=WSH, name="wspre")
    check("workspace pre-commit: missing -> warns, allowed", c.returncode == 0 and "gitleaks not installed: secret scan skipped" in c.stderr, c.stderr)


# ---------------- H2: the scan covers everything not on the remote, in worktrees, per branch, and the pre-push hook enforces it
ALL = T / "all-hooks"; ALL.mkdir()
for n in ("post-commit", "pre-push"):
    shutil.copy2(TPL / n, ALL / n)


def heads(r):
    out = subprocess.run(["git", "--git-dir", str(r.bare), "for-each-ref", "--format=%(refname:short)", "refs/heads"], capture_output=True, text=True).stdout.split()
    return set(out)


def bare_has(r, branch):
    return subprocess.run(["git", "--git-dir", str(r.bare), "rev-parse", "-q", "--verify", "refs/heads/" + branch], capture_output=True).returncode == 0


# case a: linked worktree (.git is a file): marker lands in the worktree's git dir, nothing is pushed, a clean next commit still scans the leak
r = Repo("h2-wt", ALL, "content"); r.put("a.txt", "1\n"); r.commit("base"); r.wait_pushed()
wt = T / "h2-wt-tree"; r.g("worktree", "add", "-q", "-b", "wtbranch", str(wt))
def wg(*a): return subprocess.run(["git", "-C", str(wt)] + list(a), capture_output=True, text=True, env=r.env, timeout=60)
(wt / "s.txt").write_text("SECRET-TOKEN=abc\n"); wg("add", "-A"); c = wg("commit", "-q", "-m", "leak")
gd = pathlib.Path(wg("rev-parse", "--git-path", "PUSH-BLOCKED").stdout.strip()); gd = gd if gd.is_absolute() else wt / gd
time.sleep(1.0)
check("H2a worktree: finding writes the marker in the worktree git dir (no .git/ file path error)", c.returncode == 0 and gd.is_file() and "branch=wtbranch" in gd.read_text() and (wt / ".git").is_file(), (c.stderr, str(gd)))
check("H2a worktree: nothing pushed", not bare_has(r, "wtbranch"))
(wt / "t.txt").write_text("clean\n"); wg("add", "-A"); c = wg("commit", "-q", "-m", "clean after leak"); time.sleep(1.0)
check("H2a worktree: a clean commit after the leaking one is STILL blocked (range covers the unpushed leak), marker stays", gd.is_file() and not bare_has(r, "wtbranch"), c.stderr)
p = wg("push", "origin", "wtbranch")
check("H2a worktree: manual git push is refused by pre-push", p.returncode != 0 and "push blocked" in p.stderr and not bare_has(r, "wtbranch"), p.stderr)

# case b: branch A leaks, clean commit on main, clean commit on A
r = Repo("h2-br", ALL, "content"); r.put("a.txt", "1\n"); r.commit("base"); r.wait_pushed()
r.g("checkout", "-q", "-b", "A"); r.put("s.txt", "SECRET-TOKEN=abc\n"); r.commit("leak on A"); time.sleep(1.0)
pbm = r.d / ".git/PUSH-BLOCKED"
check("H2b: leak on branch A -> blocked, marker names branch A", pbm.is_file() and "branch=A " in pbm.read_text() and not bare_has(r, "A"), pbm.read_text() if pbm.exists() else "")
r.g("checkout", "-q", "main"); r.put("m.txt", "clean main\n"); r.commit("clean on main"); ok = r.wait_pushed()
check("H2b: clean commit on main is pushed (main holds no leak)", ok and not bare_has(r, "A"))
check("H2b: marker for branch A survives a clean commit on main", pbm.is_file() and "branch=A " in pbm.read_text(), pbm.read_text() if pbm.exists() else "")
r.g("checkout", "-q", "A"); r.put("n.txt", "clean on A\n"); r.commit("clean on A"); time.sleep(1.0)
check("H2b: clean commit on A is still NOT pushed (the leak is in its unpushed range), marker stays", not bare_has(r, "A") and pbm.is_file())
p = r.g("push", "origin", "A")
check("H2b: manual git push of A refused by pre-push; remote has no A", p.returncode != 0 and "push blocked" in p.stderr and not bare_has(r, "A"), p.stderr)
p = r.g("push", "origin", "main")
check("H2b: pushing the clean branch main manually is allowed", p.returncode == 0, p.stderr)
# rewrite A without the leak: next commit scans clean, clears the marker, pushes
r.g("reset", "-q", "--hard", "main"); r.put("n.txt", "clean again\n"); r.commit("rewritten A")
end = time.time() + 20
while time.time() < end and not bare_has(r, "A"): time.sleep(0.3)
check("H2b: after the history is rewritten clean, marker cleared and A pushed", bare_has(r, "A") and not pbm.exists(), pbm.exists())

# case c: block, then plain git push (no new commit) is refused; scanner error counts as a finding; deletes and a clean push pass
r = Repo("h2-man", ALL, "content"); r.put("a.txt", "1\n"); r.commit("base"); r.wait_pushed()
r.put("s.txt", "SECRET-TOKEN=abc\n"); r.commit("leak"); time.sleep(1.0)
p = r.g("push", "origin", "main")
check("H2c: manual git push after the block is refused; remote unchanged", p.returncode != 0 and "push blocked" in p.stderr and r.remote_head() != r.g("rev-parse", "HEAD").stdout.strip(), p.stderr)
p = r.g("push", "--no-verify", "origin", "main")
check("H2c: --no-verify is the documented override", p.returncode == 0)
r = Repo("h2-err", ALL, "error"); r.put("a.txt", "1\n"); c = r.commit("one"); time.sleep(1.0)
check("H2c: scanner error (exit 126) in post-commit = finding (blocked, no push)", (r.d / ".git/PUSH-BLOCKED").is_file() and r.remote_head() == "", c.stderr)
p = r.g("push", "origin", "main")
check("H2c: scanner error in pre-push refuses the push", p.returncode != 0 and r.remote_head() == "", p.stderr)
r = Repo("h2-miss", ALL, "missing"); r.put("a.txt", "1\n"); r.commit("one"); r.wait_pushed(); r.put("a.txt", "2\n"); r.commit("two"); r.wait_pushed()
p = r.g("push", "origin", "main:other")
check("H2c: pre-push with gitleaks missing warns and allows", p.returncode == 0 and "pre-push secret scan skipped" in p.stderr, p.stderr)
r = Repo("h2-del", ALL, "finding"); r.put("a.txt", "1\n"); r.commit("one"); r.g("push", "--no-verify", "origin", "main"); r.g("push", "--no-verify", "origin", "main:tmp")
p = r.g("push", "origin", ":tmp")
check("H2c: deleting a remote branch is not scanned (allowed)", p.returncode == 0 and not bare_has(r, "tmp"), p.stderr)
# pre-push alone, composable: a second block appended after the marker still runs and can refuse
comp = T / "comp-hooks"; comp.mkdir(); txt = (TPL / "pre-push").read_text().replace("exit 0\n", "") + 'echo "second guard ran; refs=$(printf %s \"$refs\" | wc -l | tr -d \" \")" >&2\nexit 1\n'
(comp / "pre-push").write_text(txt); os.chmod(comp / "pre-push", 0o755)
r = Repo("h2-comp", comp, "clean"); r.put("a.txt", "1\n"); r.commit("one"); p = r.g("push", "origin", "main")
check("H2: pre-push is composable (a later block sees $refs and can refuse)", p.returncode != 0 and "second guard ran" in p.stderr, p.stderr)
check("pre-push (template): executable, bash -n clean", os.access(TPL / "pre-push", os.X_OK) and subprocess.run(["bash", "-n", str(TPL / "pre-push")]).returncode == 0)
if HAVE_WSH:
    check("pre-push copies byte-identical, executable, bash -n clean", (WSH / "pre-push").read_bytes() == (TPL / "pre-push").read_bytes() and os.access(WSH / "pre-push", os.X_OK) and subprocess.run(["bash", "-n", str(WSH / "pre-push")]).returncode == 0)

# ---------------- the two copies agree
def between(p, a, b):
    s = pathlib.Path(p).read_text(); i = s.index(a); return s[i:s.index(b) + len(b)]

if HAVE_WSH:
    check("template and workspace post-commit are byte-identical", (WSH / "post-commit").read_bytes() == (TPL / "post-commit").read_bytes())
    check("gitleaks block of pre-commit is identical in both copies",
          between(WSH / "pre-commit", "#--GITLEAKS-PRE-BEGIN--", "#--GITLEAKS-PRE-END--") == between(TPL / "pre-commit", "#--GITLEAKS-PRE-BEGIN--", "#--GITLEAKS-PRE-END--"))
    check("expected difference: only the template pre-commit has the STATUS rule", "docs/STATUS.md" in (TPL / "pre-commit").read_text() and "docs/STATUS.md" not in (WSH / "pre-commit").read_text())
_pcs = ((WSH / "post-commit",) if HAVE_WSH else ()) + (TPL / "post-commit",)
check("hooks are executable, bash -n clean, no push other than 'git push -q -u origin \"$branch\"'",
      all(os.access(p, os.X_OK) and subprocess.run(["bash", "-n", str(p)]).returncode == 0 for p in ((WSH / "pre-commit", WSH / "post-commit") if HAVE_WSH else ()) + (TPL / "pre-commit", TPL / "post-commit"))
      and all((lambda f: len(f) == 2 and all(x.startswith('git push -q -u origin "$branch" ') for x in f))(re.findall(r"git push -q[^>]*", pc.read_text())) for pc in _pcs))

shutil.rmtree(T, ignore_errors=True)
print("\nFAILED: " + ", ".join(fails) if fails else "\nALL PASS")
sys.exit(1 if fails else 0)
