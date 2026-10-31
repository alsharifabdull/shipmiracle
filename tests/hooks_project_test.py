#!/usr/bin/env python3
"""Project hook modules (Phase 4a T4): shipmiracle/hooks/project.py against the legacy template hooks (templates/base/.claude/hooks/*.sh).
For EACH of the seven hooks every input runs twice on identical copies of a temp project (git repo made from templates/base, a temp HOME):
the legacy shell script (bash, stdin JSON, cwd and CLAUDE_PROJECT_DIR set) and the module through core.run. Compared: decision (block or
allow + the text; exit 2 + stderr text == JSON deny/block with that text), plain stdout, every file written (canonical content), git effects.
Also: ownership by detection (owned, not owned, symlinked project, no registry, unreadable registry, settings.json missing, local
settings), SHIPMIRACLE_QUIET ignored, performance numbers, import budget, no shell=True. Never touches the real HOME: everything is under a temp dir.
Run: python3 tests/hooks_project_test.py"""
import ast, hashlib, json, os, pathlib, re, shutil, signal, subprocess, sys, tempfile, time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
TMP = pathlib.Path(tempfile.mkdtemp(prefix="hooksproj")).resolve()
HOME = TMP / "home"
BASE = TMP / "base"
SNAP = TMP / "snap"
CFG = TMP / "config"
FIX = ROOT / "tests" / "fixtures" / "hooks" / "project"
TPL = ROOT / "templates" / "base" / ".claude" / "hooks"
PROJ = "p"
PD = HOME / "Developer" / PROJ
BASE_PATH = "/opt/homebrew/bin:/usr/local/bin:" + os.environ.get("PATH", "/usr/bin:/bin")
os.environ.update(SHIPMIRACLE_TEST="1", HOME=str(HOME), SHIPMIRACLE_HOME=str(HOME), SHIPMIRACLE_STATE=str(HOME / ".local/state/shipmiracle"), SHIPMIRACLE_CONFIG=str(CFG),
                  SHIPMIRACLE_DEV=str(HOME / "Developer"), SHIPMIRACLE_WS=str(HOME / "Developer/AI-Workspace"), SHIPMIRACLE_HOOK_NO_LOAD="1", PATH=BASE_PATH,
                  LC_ALL="en_US.UTF-8", LANG="en_US.UTF-8", GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0")
for k in ("SHIPMIRACLE_QUIET", "SHIPMIRACLE_HOOK_INJECT", "SHIPMIRACLE_HOOK_CAPTURE", "CLAUDE_PROJECT_DIR", "SHIPMIRACLE_STOP_TESTS_TIMEOUT", "GIT_DIR", "GIT_WORK_TREE"):
    os.environ.pop(k, None)
CFG.mkdir(); HOME.mkdir()
from shipmiracle.hooks import core  # noqa: E402
import shipmiracle.hooks.project as P  # noqa: E402
import shipmiracle_timing as T  # noqa: E402

fails = 0
FAILED = []
STAT = {}            # hook -> [cases, mismatches]


def check(name, ok, info=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(info)[:1500]))
    fails += 0 if ok else 1
    if not ok:
        FAILED.append(name)


def today():
    return time.strftime("%Y-%m-%d")


# ---------------------------------------------------------------- the temp project
def state_file(name=PROJ):
    return HOME / ".local/state/shipmiracle" / (name + ".json")


def sh(*cmd, cwd=None, inp=None):
    return subprocess.run(list(cmd), cwd=str(cwd or PD), input=inp, capture_output=True, timeout=60)


def write(rel, content, mtime=None, root=None):
    p = (root or PD) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
    if mtime is not None:
        os.utime(p, (mtime, mtime))
    return p


def pid_of(path):
    return hashlib.sha256(("shipmiracle-project:" + os.path.realpath(path)).encode()).hexdigest()[:12]


def make_registry(extra=()):
    ids = {pid_of(PD): {"name": PROJ}}
    for e in extra:
        ids[pid_of(e)] = {"name": os.path.basename(e)}
    (CFG / "registry.json").write_text(json.dumps({"v": 1, "projects": ids}))


def status_text(extra=""):
    return (FIX / "status_fresh.md.tmpl").read_text().replace("@TODAY@", today()) + extra


def make_base():
    shutil.rmtree(BASE, ignore_errors=True)
    BASE.mkdir()
    dev = BASE / "Developer"
    dev.mkdir()
    shutil.copytree(ROOT / "templates" / "base", dev / PROJ, symlinks=True)
    (dev / "AI-Workspace" / "bin").mkdir(parents=True)
    shutil.copy2(ROOT / "bin" / "status-extract", dev / "AI-Workspace" / "bin" / "status-extract")
    p = dev / PROJ
    shutil.copy2(FIX / "settings_migrated.json", p / ".claude" / "settings.json")
    (p / "docs" / "STATUS.md").write_text(status_text())
    (p / ".claude" / "test-command").unlink() if (p / ".claude" / "test-command").exists() else None
    for c in (["init", "-q", "-b", "main"], ["config", "user.name", "t"], ["config", "user.email", "t@t"], ["config", "commit.gpgsign", "false"],
              ["add", "-A"], ["commit", "-q", "-m", "init"]):
        r = subprocess.run(["git"] + c, cwd=str(p), env=dict(os.environ, HOME=str(BASE)), capture_output=True)
        assert r.returncode == 0, (c, r.stderr)
    (BASE / ".claude" / "plans").mkdir(parents=True)


def reset():
    shutil.rmtree(HOME, ignore_errors=True)
    shutil.copytree(BASE, HOME, symlinks=True)


def snapshot():
    shutil.rmtree(SNAP, ignore_errors=True)
    shutil.copytree(HOME, SNAP, symlinks=True)


def restore():
    shutil.rmtree(HOME, ignore_errors=True)
    shutil.copytree(SNAP, HOME, symlinks=True)


def tree():
    """Canonical content of everything under HOME (git internals except PUSH markers left out, timestamps and permissions normalised)."""
    out = {}
    for d, dirs, files in os.walk(str(HOME)):
        rel_d = os.path.relpath(d, str(HOME))
        if rel_d == "Library" or rel_d.startswith("Library" + os.sep):
            dirs[:] = []                    # python's bytecode cache of the legacy scripts' python3
            continue
        if rel_d == ".git" or rel_d.startswith(".git" + os.sep) or "/.git/" in "/" + rel_d + "/":
            for f in files:
                if f.startswith("PUSH-"):
                    out[os.path.join(rel_d, f)] = (pathlib.Path(d) / f).read_bytes()
            dirs[:] = []
            continue
        for f in files:
            p = pathlib.Path(d) / f
            rel = os.path.join(rel_d, f)
            if rel in (".local/state/shipmiracle/flow-errors.log", ".local/state/shipmiracle/stop-tests.log") or rel.startswith(".local/state/shipmiracle/v1/"):
                continue                    # the module's own error log and events (checked separately)
            if p.is_symlink():
                out[rel] = ("link", os.readlink(p))
                continue
            b = p.read_bytes()
            if rel.startswith(".local/state/shipmiracle/") and rel.endswith(".json"):
                try:
                    j = json.loads(b)
                    ts = j.pop("ts", None)
                    assert isinstance(ts, int) and abs(ts - time.time()) < 120, ts
                    b = json.dumps(j, sort_keys=True).encode()
                except Exception as e:
                    b = b"BAD STATE FILE %r" % (e,) + b
            if rel.endswith("model-log.md"):
                b = re.sub(rb"(?m)^- \d{4}-\d\d-\d\d \d\d:\d\d ", b"- TS ", b)
            out[rel] = b
    return out


def git_effects():
    r = []
    if (PD / ".git").exists():
        for a in (["status", "--porcelain=v1", "-z"], ["rev-parse", "HEAD"], ["diff", "--cached"], ["stash", "list"], ["branch", "-a"]):
            r.append(sh("git", *a).stdout)
    return r


# ---------------------------------------------------------------- running both implementations
def rendered(script):
    """The template hook with @SHIPMIRACLE_ENGINE@ replaced the way apply-template does (P8): the engine folder of the temp HOME."""
    out = TMP / "legacy-hooks" / script
    out.parent.mkdir(exist_ok=True)
    out.write_bytes((TPL / script).read_bytes().replace(b"@SHIPMIRACLE_ENGINE@", str(HOME / "Developer" / "AI-Workspace").encode()))
    return out


def run_legacy(script, stdin, proj, extra=None, args=(), timeout=60):
    env = {"PATH": BASE_PATH, "HOME": str(HOME), "LC_ALL": "en_US.UTF-8", "LANG": "en_US.UTF-8", "CLAUDE_PROJECT_DIR": str(proj), "GIT_CONFIG_NOSYSTEM": "1"}
    for k, v in (extra or {}).items():
        if v is None:
            env.pop(k, None)
        else:
            env[k] = v
    cwd = str(proj) if os.path.isdir(str(proj)) else str(HOME)
    try:
        p = subprocess.run(["bash", script if os.path.isabs(script) else str(rendered(script))] + list(args), input=stdin, cwd=cwd, env=env, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None
    return p.returncode, p.stdout, p.stderr


class Env:
    """Patch os.environ for one module run (the hook reads HOME, SHIPMIRACLE_STATE ... from the process)."""
    def __init__(self, **kw):
        self.kw = kw
    def __enter__(self):
        self.old = dict(os.environ)
        for k, v in self.kw.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = str(v)
        self.cwd = os.getcwd()
    def __exit__(self, *a):
        os.chdir(self.cwd)
        os.environ.clear(); os.environ.update(self.old)


class Only:
    """Keep only one project slot of a pipeline active (the others are other hooks' business in a per-hook comparison)."""
    def __init__(self, key, name):
        self.key, self.name = key, name
    def __enter__(self):
        self.saved = [(s, s.fn) for s in core.PIPELINES[self.key] if s.project]
        for s, fn in self.saved:
            if s.name != self.name:
                s.fn = None
        self.active = [s for s, _ in self.saved if s.name == self.name and s.fn is not None]
        assert self.active, (self.key, self.name)
    def __exit__(self, *a):
        for s, fn in self.saved:
            s.fn = fn


def run_mod(event, name, stdin, proj, extra=None, slow=False):
    if isinstance(stdin, (dict, list)):
        stdin = json.dumps(stdin).encode()
    key = event + "--slow" if slow else event
    changes = {"CLAUDE_PROJECT_DIR": str(proj)}
    changes.update(extra or {})
    core._FILES.clear()
    with Env(**changes):
        if os.path.isdir(str(proj)):
            os.chdir(str(proj))
        with Only(key, name):
            return core.run(event, stdin, slow)


LEGACY_TEXT = [
    (b'add: ~/Developer/AI-Workspace/bin/idea add "idea"; review method: ~/Developer/AI-Workspace/docs/idea-review-method.md)',
     b'add: shipm idea add "idea"; review method: docs/idea-review-method.md in the Shipmiracle engine folder)'),
    (b"(create it from ~/Developer/AI-Workspace/templates/base/docs/SKILLS.md if missing):",
     b"(create it from templates/base/docs/SKILLS.md in the Shipmiracle engine folder if missing):"),
]


def norm_legacy(r):
    if r is None:
        return ("allow", "", b"")           # killed by the harness: no block
    rc, out, err = r
    assert rc in (0, 2), r
    if rc == 2:
        return ("block", err.decode("utf-8", "replace").rstrip("\n"), b"")
    for a_, b_ in LEGACY_TEXT:        # the module words the owner-path hints without the owner's folder (P8 T1); the legacy script keeps its text until it is deleted
        out = out.replace(a_, b_)
    return ("allow", "", out)


def norm_mod(r):
    out, err, code = r
    if code == 2:
        return ("block", err.decode("utf-8", "replace").rstrip("\n"), b"")
    if out.startswith(b"{"):
        d = json.loads(out)
        hso = d.get("hookSpecificOutput") or {}
        if hso.get("permissionDecision") == "deny":
            return ("block", hso["permissionDecisionReason"].rstrip("\n"), b"")
        if d.get("decision") == "block":
            return ("block", d["reason"].rstrip("\n"), b"")
    assert code == 0 and not err, r
    return ("allow", "", out)


def diff_case(hook, label, event, script, name, stdin, setup=None, extra=None, args=(), slow=False, proj=None, expect=None, expect_in=None,
              ignore_stdout=False, legacy_timeout=60, after=None, known=None, log_ok=False, skip_files=(), skip_git=False):
    """One differential case. expect: "block"/"allow"; expect_in: text the block reason or stdout must contain (guards against vacuous cases)."""
    STAT.setdefault(hook, [0, 0])
    STAT[hook][0] += 1
    proj = proj or PD
    if isinstance(stdin, (dict, list)):
        stdin = json.dumps(stdin).encode()
    elif isinstance(stdin, str):
        stdin = stdin.encode("utf-8")
    try:
        reset()
        if setup:
            setup()
        snapshot()
        L = run_legacy(script, stdin, proj, extra, args, legacy_timeout)
        t1, g1 = tree(), git_effects()
        restore()
        M = run_mod(event, name, stdin, proj, extra, slow)
        t2, g2 = tree(), git_effects()
        nl, nm = norm_legacy(L), norm_mod(M)
        if ignore_stdout:
            nl, nm = nl[:2], nm[:2]
        problems = []
        if known:                               # a documented difference: (legacy kind, module kind)
            if (nl[0], nm[0]) != known:
                problems.append("known difference changed: legacy=%r module=%r" % (nl, nm))
        elif nl != nm:
            problems.append("decision/stdout legacy=%r module=%r" % (nl, nm))
        for k in skip_files:
            t1.pop(k, None); t2.pop(k, None)
        if t1 != t2:
            problems.append("files differ: " + ", ".join(sorted(k for k in set(t1) | set(t2) if t1.get(k) != t2.get(k)))[:400])
        if g1 != g2 and not skip_git:
            problems.append("git effects differ")
        if (HOME / ".local/state/shipmiracle/flow-errors.log").exists() and not log_ok:
            problems.append("the module logged an error: " + (HOME / ".local/state/shipmiracle/flow-errors.log").read_text()[-300:])
        if expect and nm[0] != expect:
            problems.append("scenario is vacuous: expected %s got %s" % (expect, nm[0]))
        if expect_in is not None and expect_in not in (nm[1] if nm[0] == "block" else nm[2].decode("utf-8", "replace")):
            problems.append("expected text %r missing in %r" % (expect_in, nm[1:] ))
        if after and not problems:
            msg = after(t2)
            if msg:
                problems.append(msg)
        ok = not problems
    except Exception as e:
        import traceback
        ok, problems = False, [traceback.format_exc()[-900:]]
    if not ok:
        STAT[hook][1] += 1
    check("%s: %s" % (hook, label), ok, "; ".join(problems))


def bashin(cmd, tool="Bash", **extra):
    d = {"tool_name": tool, "tool_input": {"command": cmd}, "session_id": "abcdef123456", "cwd": str(PD)}
    d.update(extra)
    return d


make_base()
make_registry()

# The legacy stop-gate.sh has a latent bug: `out=$(bash -lc "$cmd" 2>&1 | tail -30); status=${PIPESTATUS[0]}` reads the status of the assignment
# (= tail's, always 0), so a failing test-command NEVER blocks. stop_tests implements the documented behaviour (exit 2 + output on failure);
# the differential cases for it compare against the legacy script with exactly that one line corrected.
_orig = (TPL / "stop-gate.sh").read_text()
_needle = 'out=$(bash -lc "$cmd" 2>&1 | tail -30); status=${PIPESTATUS[0]}'
assert _needle in _orig, "the legacy stop-gate.sh changed: re-check the PIPESTATUS finding"
FIXED = TMP / "stop-gate-fixed.sh"
FIXED.write_text(_orig.replace(_needle, 'out=$(bash -lc "$cmd" 2>&1); status=$?; out=$(printf \'%s\\n\' "$out" | tail -30)'))

# ================================================================ 1 shipmiracle_state
EV = {"working": "PreToolUse", "done": "Stop", "needs-input": "Notification"}


def st_case(label, state, stdin, event=None, **kw):
    diff_case("shipmiracle_state", label, event or EV[state], "shipm-state.sh", "shipmiracle_state", stdin, args=(state,), **kw)


st_case("working PreToolUse, tool call", "working", {"tool_name": "Bash", "tool_input": {"command": "ls"}}, expect="allow")
st_case("working UserPromptSubmit with a message field", "working", {"prompt": "hi", "message": "hello"}, event="UserPromptSubmit")
st_case("working UserPromptSubmit, no message", "working", {"prompt": "hi"}, event="UserPromptSubmit")
st_case("done on Stop", "done", {"session_id": "s1", "stop_hook_active": False})
st_case("needs-input permission message", "needs-input", {"message": "Claude needs your permission to use Bash", "notification_type": "permission_prompt"})
st_case("needs-input idle_prompt is ignored", "needs-input", {"message": "Claude is waiting for your input", "notification_type": "idle_prompt"})
st_case("needs-input auth_success is ignored", "needs-input", {"message": "signed in", "notification_type": "auth_success"})
st_case("needs-input 'waiting for your input' text without a type is ignored", "needs-input", {"message": "Claude is waiting for your input"})
st_case("needs-input without any fields", "needs-input", {})
st_case("message longer than 140 characters is cut", "needs-input", {"message": "x" * 300})
st_case("message of exactly 140 and 141 characters", "needs-input", {"message": "y" * 141})
st_case("arabic and emoji message", "needs-input", {"message": "يحتاج Claude إلى إذنك 🔔 للمتابعة"})
st_case("message with quotes, backslash and newlines", "needs-input", {"message": "say \"hi\" \\ there\n\nnext line\n\n"})
st_case("message that is only newlines", "needs-input", {"message": "\n\n"})
st_case("message is a number", "needs-input", {"message": 42})
st_case("message is an object", "needs-input", {"message": {"a": [1, 2], "b": None}})
st_case("message is null and bool", "working", {"message": None})
st_case("invalid JSON on stdin", "needs-input", b"{not json")
st_case("empty stdin", "working", b"")
st_case("JSON list on stdin", "needs-input", [1, 2, 3])
st_case("invalid UTF-8 on stdin", "needs-input", b'{"message": "caf\xe9"}')
st_case("lone surrogate in the message", "needs-input", b'{"message": "a\\ud800b"}')
st_case("NUL in the message", "needs-input", b'{"message": "a\\u0000b"}')
st_case("project outside ~/Developer gets no state file", "working", {"tool_name": "Bash"}, proj=HOME / "other" / "p2",
        setup=lambda: (HOME / "other" / "p2").mkdir(parents=True), expect="allow")
st_case("CLAUDE_PROJECT_DIR with a trailing slash", "working", {"tool_name": "Bash"}, proj=str(PD) + "/")
st_case("an existing state file is replaced", "done", {"session_id": "s"},
        setup=lambda: write(".local/state/shipmiracle/p.json", '{"project":"p","state":"working"}', root=HOME))
st_case("state folder missing is created", "working", {"tool_name": "Read"}, setup=lambda: shutil.rmtree(HOME / ".local", ignore_errors=True))

# ---- state file mode and atomicity (documented difference: module writes 0600, no leftovers)
reset()
run_mod("Stop", "shipmiracle_state", b"{}", PD)
f = HOME / ".local/state/shipmiracle/p.json"
check("shipmiracle_state: file is 0600 and no pid temp file is left behind", f.exists() and (f.stat().st_mode & 0o777) == 0o600 and not list(f.parent.glob("*.tmp")))

# ================================================================ 2 block_secrets
SK = "s" + "k-" + "a1B2c3D4e5F6g7H8i9J0kLmN"
AKIA = "AK" + "IA" + "ABCDEFGHIJKLMNOP"
GHP = "gh" + "p_" + "A" * 36
XOX = "xo" + "xb-" + "1234567890abcdef"
PEM = "-----BEGIN " + "RSA PRIVATE KEY" + "-----"
PW = "pass" + "word"


def stage(rel, content):
    def f():
        write(rel, content)
        sh("git", "add", "-f", rel)
    return f


def stage_many(items):
    def f():
        for rel, content in items:
            write(rel, content)
            sh("git", "add", "-f", rel)
    return f


def bs(label, cmd, setup=None, expect=None, stdin=None, **kw):
    diff_case("block_secrets", label, "PreToolUse", "block-secrets.sh", "block_secrets", stdin if stdin is not None else bashin(cmd), setup=setup, expect=expect, **kw)


bs("commit with nothing staged", "git commit -m x", expect="allow")
bs("commit with an api key staged", "git commit -m x", stage("app.py", "key = '%s'\n" % SK), expect="block", expect_in="looks like a secret")
bs("push with a secret staged", "git push origin main", stage("app.py", "x = '%s'\n" % SK), expect="block")
bs("unrelated command with a secret staged", "ls -la", stage("app.py", "x = '%s'\n" % SK), expect="allow")
bs("git status with a secret staged", "git status", stage("app.py", "x = '%s'\n" % SK), expect="allow")
bs(".env staged, commit", "git commit -m x", stage(".env", "A=1\n"), expect="block", expect_in=".env file is staged")
bs(".env.local staged", "git commit -m x", stage(".env.local", "A=1\n"), expect="block")
bs("sub/.env staged", "git commit -m x", stage("sub/.env", "A=1\n"), expect="block")
bs(".env and .env.example staged together (the script's quirk: allowed)", "git commit -m x", stage_many([(".env", "A=1\n"), (".env.example", "A=\n")]), expect="allow")
bs("only .env.example staged", "git commit -m x", stage(".env.example", "A=\n"), expect="allow")
bs("name that merely contains env", "git commit -m x", stage("environment.txt", "hello\n"), expect="allow")
bs("AWS key id", "git commit -m x", stage("a.txt", "id %s\n" % AKIA), expect="block")
bs("github token", "git commit -m x", stage("a.txt", "t=%s\n" % GHP), expect="block")
bs("slack token", "git commit -m x", stage("a.txt", "t=%s\n" % XOX), expect="block")
bs("private key header", "git commit -m x", stage("k.pem", PEM + "\nabc\n"), expect="block")
bs("quoted assignment of 8+ chars", "git commit -m x", stage("c.py", '%s = "hunter2hunter2"\n' % PW), expect="block")
bs("quoted assignment shorter than 8", "git commit -m x", stage("c.py", '%s = "short"\n' % PW), expect="allow")
bs("api key in upper case with a colon", "git commit -m x", stage("c.yml", "API_KEY" ": 'abcdefghijkl'\n"), expect="block")
bs("mixed case Api-Key", "git commit -m x", stage("c.yml", 'Api-Key' ' = "xxxxxxxxxxx"\n'), expect="block")
bs("secret value on the next line only", "git commit -m x", stage("c.py", "token =\n'abcdefghijklmnop'\n"), expect="allow")
bs("secret only in a removed line", "git commit -m x", lambda: (write("old.py", "x = '%s'\n" % SK), sh("git", "add", "old.py"), sh("git", "commit", "-q", "-m", "o"), write("old.py", "x = 1\n"), sh("git", "add", "old.py")), expect="allow")
bs("added line starting with ++ is hidden by the script's grep -v '^+++'", "git commit -m x", stage("c.txt", "++ %s: 'longsecret1'\n" % PW), expect="allow")
bs("secret staged then changed in the work tree (index counts)", "git commit -m x",
   lambda: (stage("s.py", "x = '%s'\n" % SK)(), write("s.py", "x = 1\n")), expect="block")
bs("secret not staged", "git commit -m x", lambda: write("s.py", "x = '%s'\n" % SK), expect="allow")
bs("compound command with git commit", "cd . && git add -A && git commit -am y", stage("a.txt", "id %s\n" % AKIA), expect="block")
bs("git push inside a heredoc-like string", "echo 'run git push later'", stage("a.txt", "id %s\n" % AKIA), expect="block")
bs("two spaces in git  commit do not match", "git  commit -m x", stage("a.txt", "id %s\n" % AKIA), expect="allow")
bs("command is a list (python str() contains git commit)", None, stage("a.txt", "id %s\n" % AKIA), stdin={"tool_name": "Bash", "tool_input": {"command": ["git commit"]}}, expect="block")
bs("command is a number", None, stage("a.txt", "id %s\n" % AKIA), stdin={"tool_name": "Bash", "tool_input": {"command": 7}}, expect="allow")
bs("tool_input missing", None, stage("a.txt", "id %s\n" % AKIA), stdin={"tool_name": "Bash"}, expect="allow")
bs("tool_input is a string", None, None, stdin={"tool_name": "Bash", "tool_input": "git commit"}, expect="allow")
bs("invalid JSON", None, stage("a.txt", "id %s\n" % AKIA), stdin=b"{oops", expect="allow")
bs("empty stdin", None, None, stdin=b"", expect="allow")
bs("not a git repository", "git commit -m x", lambda: (shutil.rmtree(PD / ".git")), expect="allow")
bs("project folder missing", "git commit -m x", None, proj=HOME / "nowhere", expect="allow")
bs("non-ascii file name and ascii secret", "git commit -m x", stage("خطة.txt", "id %s\n" % AKIA), expect="block")
bs("binary-ish staged file with the key", "git commit -m x", stage("blob.bin", b"\xff\xfe\x00\x01" + SK.encode() + b"\n"), expect="allow")
bs("invalid UTF-8 text line with a key", "git commit -m x", stage("l1.txt", b"caf\xe9 " + SK.encode() + b"\n"), known=("allow", "block"))   # grep in a UTF-8 locale goes blind on invalid bytes; the module still sees the key
bs("very large staged diff, key on the last line", "git commit -m x",
   stage("big.txt", ("lorem ipsum dolor sit amet " * 40 + "\n") * 800 + "x = '%s'\n" % SK), expect="block")
bs("very large staged diff, no secret", "git commit -m x", stage("big2.txt", ("lorem ipsum dolor sit amet " * 40 + "\n") * 800), expect="allow")
bs("huge input JSON (2 MB command)", None, stage("a.txt", "id %s\n" % AKIA), stdin=bashin("echo " + "x" * (2 << 20) + "; git commit"), expect="block")

# ================================================================ 3 stop_fast / stop_tests
def set_status(text, mtime=None):
    return write("docs/STATUS.md", text, mtime)


def fresh_change(extra_status="", rel="src/app.py"):
    """An untracked source file older than a fresh STATUS."""
    t = int(time.time())
    def f():
        write(rel, "print(1)\n", t - 100)
        set_status(status_text(extra_status), t)
    return f


def sid_in(t):
    return t.get("Developer/p/docs/STATUS.md", b"")


def sf(label, stdin=None, setup=None, **kw):
    diff_case("stop_fast", label, "Stop", "stop-gate.sh", "stop_fast", stdin if stdin is not None else {"session_id": "sess-1234", "stop_hook_active": False}, setup=setup, **kw)


sf("clean tree", expect="allow")
sf("source changed, STATUS missing", setup=lambda: (fresh_change()(), (PD / "docs/STATUS.md").unlink()), expect="block", expect_in="STATUS.md is missing")
sf("source changed, STATUS stale", setup=lambda: (fresh_change()(), set_status(status_text().replace(today(), "2020-01-01"))), expect="block", expect_in="not updated for today")
sf("STATUS dated today but older than the source file", setup=lambda: (write("src/app.py", "x\n", int(time.time())), set_status(status_text(), int(time.time()) - 500)), expect="block", expect_in="older than the latest")
sf("fresh STATUS with a Handoff heading gets the session line", setup=fresh_change(), expect="allow", after=lambda t: None if b"- Last Claude session: sess-1234" in sid_in(t) else "no session line")
sf("existing session line is replaced", setup=fresh_change("\n- Last Claude session: old-1 (2020-01-01). Resume: x\n"), expect="allow",
   after=lambda t: None if b"old-1" not in sid_in(t) and b"sess-1234" in sid_in(t) else "not replaced")
sf("session id with a backslash group reference (re template quirk)", {"session_id": "a\\1b"}, setup=fresh_change("\n- Last Claude session: old-1 (x)\n"))
sf("session id with a harmless backslash", {"session_id": "a\\\\b"}, setup=fresh_change("\n- Last Claude session: old-1 (x)\n"))
sf("no session_id", {"stop_hook_active": False}, setup=fresh_change(), expect="allow")
sf("session_id is a number", {"session_id": 123}, setup=fresh_change(), expect="allow")
sf("session_id is null", {"session_id": None}, setup=fresh_change(), expect="allow")
sf("session_id empty string", {"session_id": ""}, setup=fresh_change(), expect="allow")
sf("stop_hook_active true with a space", b'{"session_id":"s","stop_hook_active": true}', setup=lambda: (fresh_change()(), set_status("stale\n")), expect="allow")
sf("stop_hook_active true without a space", b'{"session_id":"s","stop_hook_active":true}', setup=lambda: (fresh_change()(), set_status("stale\n")), expect="allow")
sf("stop_hook_active false still gates", {"session_id": "s", "stop_hook_active": False}, setup=lambda: (fresh_change()(), set_status("stale\n")), expect="block")
sf("no .git folder", setup=lambda: (fresh_change()(), shutil.rmtree(PD / ".git")), expect="allow")
sf(".git is a file (worktree style): the script's -d test fails", setup=lambda: (fresh_change()(), shutil.move(str(PD / ".git"), str(HOME / "gitdir")), write(".git", "gitdir: %s\n" % (HOME / "gitdir"))), expect="allow")
sf("only excluded paths changed", setup=lambda: (write(".claude/x.txt", "1"), write("docs/plans/p.md", "1"), write("docs/memory/m.md", "1"), write(".github/w.yml", "1"), set_status("stale\n")), expect="allow")
sf("G10: the removed second engine's dot-folder has no exemption any more (it is source)", setup=lambda: (write("." + "co" + "dex/c", "1"), set_status("stale\n")), expect="block")
_gate_line = lambda p: [l for l in p.read_text().splitlines() if l.startswith("changed=")]
_own_gate = ROOT / ".claude/hooks/stop-gate.sh"
if _own_gate.is_file():
    check("G10: the workspace's own .claude/hooks/stop-gate.sh has the same changed-files filter as the template (no exemption in either)",
          len(_gate_line(TPL / "stop-gate.sh")) == 1 and _gate_line(TPL / "stop-gate.sh") == _gate_line(_own_gate)
          and ("." + "co" + "dex/") not in _own_gate.read_text().replace("\\.", "."), _gate_line(_own_gate))
else:   # the exported tree does not carry the private .claude/ folder: only the template is checked
    print("SKIP G10: the workspace's own .claude/hooks/stop-gate.sh is not part of this tree")
    check("G10: the template stop-gate.sh has one changed-files filter and no second-engine exemption", len(_gate_line(TPL / "stop-gate.sh")) == 1
          and ("." + "co" + "dex/") not in (TPL / "stop-gate.sh").read_text().replace("\\.", "."), _gate_line(TPL / "stop-gate.sh"))
sf("docs/ files other than the record are source", setup=lambda: (write("docs/notes.md", "1"), set_status("stale\n")), expect="block")
sf("top-level .gitignore is excluded, nested one is not", setup=lambda: (write("sub/.gitignore", "x\n"), set_status("stale\n")), expect="block")
sf("tracked source file deleted: nothing to compare with", setup=lambda: (write("old.py", "1\n"), sh("git", "add", "old.py"), sh("git", "commit", "-q", "-m", "o"), (PD / "old.py").unlink()), expect="allow")
sf("tracked source file modified", setup=lambda: (write("README.txt", "v1\n"), sh("git", "add", "."), sh("git", "commit", "-q", "-m", "r"), write("README.txt", "v2\n", int(time.time()) - 10), set_status(status_text(), int(time.time()))), expect="allow")
sf("STATUS with CRLF line endings and a session line", setup=lambda: (fresh_change()(), set_status(status_text("\r\n- Last Claude session: old (x)\r\n").replace("\n", "\r\n") if False else status_text("\n- Last Claude session: old (x)\n").replace("\n", "\r\n"))), expect="allow")
sf("Updated line without a space after the colon", setup=lambda: (fresh_change()(), set_status(status_text().replace("Updated: ", "Updated:"))), expect="allow")
sf("Updated line with several spaces", setup=lambda: (fresh_change()(), set_status(status_text().replace("Updated: ", "Updated:     "))), expect="allow")
sf("Updated line not at the start of the line", setup=lambda: (fresh_change()(), set_status("# S\n\n  Updated: %s\n" % today())), expect="block")
sf("neither session line nor Handoff heading", setup=lambda: (fresh_change()(), set_status("# S\n\nUpdated: %s\n\n## Other\n- x\n" % today())), expect="allow")
sf("'## Handoff Notes' heading (no literal '## Handoff\\n')", setup=lambda: (fresh_change()(), set_status("# S\n\nUpdated: %s\r\n\n## Handoff Notes\n- x\n" % today())), expect="allow")
sf("non-UTF-8 STATUS with a session line (python fails in both)", setup=lambda: (fresh_change()(), set_status(("# S\n\nUpdated: %s\n- Last Claude session: o\n" % today()).encode() + b"\xff\xfe\n")), expect="allow")
sf("unicode STATUS", setup=lambda: (fresh_change()(), set_status(status_text("\n## ملاحظات\n- نص عربي\n- Last Claude session: قديم\n"))), expect="allow")
sf("invalid JSON on stdin", b"{oops", setup=fresh_change(), expect="allow")
sf("empty stdin", b"", setup=fresh_change(), expect="allow")
sf("JSON list on stdin", [1, 2], setup=fresh_change(), expect="allow")
sf("2 MB junk on stdin", b"x" * (2 << 20), setup=fresh_change(), expect="allow")
sf("file name with a space", setup=lambda: (write("my file.py", "1\n", int(time.time()) - 100), set_status(status_text(), int(time.time()))), expect="allow")
sf("file with a non-ascii name (git quotes it, so the mtime check skips it, in both)", setup=lambda: (set_status(status_text(), int(time.time()) - 100), write("ملف.py", "1\n", int(time.time()))), expect="allow")
sf("a passing test-command does not matter to the fast gate", setup=lambda: (fresh_change()(), write(".claude/test-command", "true\n")), expect="allow")
sf("project folder missing", setup=None, proj=HOME / "nowhere", expect="allow")
sf("STATUS.md is a directory", setup=lambda: (fresh_change()(), (PD / "docs/STATUS.md").unlink(), (PD / "docs/STATUS.md").mkdir()), expect="block")

# ---- stop_tests: STATUS is fresh in every case so the legacy script's only possible block is the test run
def tc(cmd):
    def f():
        fresh_change()()
        if cmd is not None:
            write(".claude/test-command", cmd)
    return f


def set_block(on):
    (CFG / "config.json").write_text(json.dumps({"hooks.stop_tests_block": bool(on)}) if on is not None else "{}")


def stt(label, cmd, stdin=None, setup=None, **kw):
    """Switch on: blocks like the documented intent (compared with the legacy script whose PIPESTATUS line is corrected).
    Switch off (the default): compared with the UNMODIFIED legacy script, which never blocks on a failing test-command."""
    common = dict(slow=True, skip_files=("Developer/p/docs/STATUS.md",), skip_git=True)   # the STATUS session line is stop_fast's job (pair cases)
    st = stdin if stdin is not None else {"session_id": "sess-1234"}
    set_block(True)
    diff_case("stop_tests", label + " [switch on]", "Stop", str(FIXED), "stop_tests", st, setup=setup or tc(cmd), **common, **kw)
    set_block(None)
    if "stale STATUS" in label:      # the unmodified script's stale-STATUS block is stop_fast's job
        return
    kw2 = {k: v for k, v in kw.items() if k not in ("expect", "expect_in", "after")}
    diff_case("stop_tests", label + " [switch off = default, unmodified legacy]", "Stop", "stop-gate.sh", "stop_tests", st, setup=setup or tc(cmd),
              expect="allow", **common, **kw2)


stt("no test-command", None, expect="allow")
stt("passing test-command", "true\n", expect="allow")
stt("failing test-command prints its output", "echo boom; exit 3\n", expect="block", expect_in="tests failed (`echo boom; exit 3`)")
stt("only the last 30 lines are shown", "seq 1 100; exit 1\n", expect="block", expect_in="100")
stt("stdout and stderr interleaved", "echo out1; echo err1 >&2; echo out2; exit 1\n", expect="block", expect_in="err1")
stt("trailing blank lines in the test-command file", "echo hi; exit 1\n\n\n", expect="block")
stt("output without a trailing newline", "printf abc; exit 1", expect="block", expect_in="abc")
stt("no output at all", "exit 1", expect="block")
stt("unicode output", "echo 'فشل الاختبار ✗'; exit 1", expect="block", expect_in="فشل")
stt("percent signs and backticks in the command", "echo '100%s done `x`'; exit 1", expect="block")
stt("multi-line script using the project folder variable", "cd \"$CLAUDE_PROJECT_DIR\" && test -f src/app.py && echo found-it\nexit 4\n", expect="block", expect_in="found-it")
stt("command not found (127)", "no_such_command_xyz\n", expect="block", expect_in="not found")
stt("exit 2 is a failure too", "exit 2", expect="block")
stt("empty test-command file", "", expect="allow")
stt("test-command whitespace only", "   \n", expect="allow")
stt("stop_hook_active skips the run", "touch ran-marker; exit 1", {"session_id": "s", "stop_hook_active": True}, expect="allow")
stt("nothing changed: the tests are not run", "touch ran-marker; exit 1", setup=lambda: write(".claude/test-command", "touch ran-marker; exit 1"), expect="allow")
stt("the tests do run when source changed (marker file written)", "touch ran-marker; exit 1", expect="block", after=lambda t: None if "Developer/p/ran-marker" in t else "marker missing")
stt("no .git folder", "exit 1", setup=lambda: (tc("exit 1")(), shutil.rmtree(PD / ".git")), expect="allow")
stt("test-command is a folder", None, setup=lambda: (fresh_change()(), (PD / ".claude/test-command").mkdir()), expect="allow")
stt("stale STATUS and failing tests: the run reports the tests (the script ran them first)", "echo red; exit 1", setup=lambda: (tc("echo red; exit 1")(), set_status("stale\n")), expect="block", expect_in="red")
stt("invalid UTF-8 in the test output", "printf 'bad \\377 byte\\n'; exit 1", expect="block")
stt("the test run changes files (written files compared)", "echo gen > generated.txt; exit 1", expect="block", after=lambda t: None if t.get("Developer/p/generated.txt") == b"gen\n" else "no generated file")
stt("very long output line", "head -c 200000 /dev/zero | tr '\\0' 'x'; echo; exit 1", expect="block")
stt("project folder missing", None, proj=HOME / "nowhere", expect="allow")

reset(); tc("echo red; exit 1")(); snapshot()
lg = norm_legacy(run_legacy("stop-gate.sh", b'{"session_id":"s"}', PD))
set_block(None)
check("FINDING: the unmodified legacy stop-gate.sh does not block on a failing test-command (PIPESTATUS bug); it passes the gate", lg[0] == "allow", lg)

set_block(None)
reset(); tc("echo red-output; exit 1")()
r = norm_mod(run_mod("Stop", "stop_tests", b'{"session_id":"s"}', PD, slow=True))
lgp = HOME / ".local/state/shipmiracle/stop-tests.log"
check("stop_tests switch off: a failing test run is logged (exit code and output tail) and does not block", r[0] == "allow" and lgp.exists() and "red-output" in lgp.read_text() and "exit=1" in lgp.read_text(), (r, lgp.exists()))
set_block(True)
check("config key hooks.stop_tests_block and tokens.nudge are in the config schema", all(k in __import__("shipmiracle.config", fromlist=["x"]).SCHEMA for k in ("hooks.stop_tests_block", "tokens.nudge")))

# timeout: the legacy script has no timeout of its own (Claude kills it); the module kills the group and does not block
STAT.setdefault("stop_tests", [0, 0])
set_block(True)
reset(); tc("echo $$ > pid-marker; exec sleep 4")()
t0 = time.time()
rr = run_mod("Stop", "stop_tests", b'{"session_id":"s"}', PD, {"SHIPMIRACLE_STOP_TESTS_TIMEOUT": "1"}, slow=True)
dt = time.time() - t0
nm = norm_mod(rr)
logtxt = (HOME / ".local/state/shipmiracle/flow-errors.log").read_text() if (HOME / ".local/state/shipmiracle/flow-errors.log").exists() else ""
time.sleep(0.3)
pidtxt = (PD / "pid-marker").read_text().strip() if (PD / "pid-marker").exists() else ""
alive = False
if pidtxt.isdigit():
    try:
        os.kill(int(pidtxt), 0); alive = True
    except OSError:
        alive = False
reset(); tc("echo $$ > pid-marker; exec sleep 4")()
lg = norm_legacy(run_legacy(str(FIXED), b'{"session_id":"s"}', PD, timeout=2))
time.sleep(2.5)         # the killed legacy run leaves its sleep child; it ends by itself (4 s), nothing is left running when the test ends
STAT["stop_tests"][0] += 1
check("stop_tests: timeout kills the whole group and does not block (legacy killed by the harness also does not block)",
      nm[0] == "allow" and lg[0] == "allow" and dt < 8 and not alive, (nm, lg, dt, alive))
check("stop_tests: the timeout is logged", "timed out" in logtxt, logtxt[-200:])
check("stop_tests: the timeout override works only under SHIPMIRACLE_TEST=1", True if P._timeout() == P.TEST_TIMEOUT else False, P._timeout())
with Env(SHIPMIRACLE_TEST=None, SHIPMIRACLE_STOP_TESTS_TIMEOUT="1"):
    check("stop_tests: SHIPMIRACLE_STOP_TESTS_TIMEOUT ignored outside SHIPMIRACLE_TEST", P._timeout() == P.TEST_TIMEOUT)

# stop_fast + stop_tests together equal the script (both blocks reported separately) when only one of the two has something to say
set_block(True)
STAT.setdefault("stop_pair", [0, 0])
for label, cmd, stale, want in (("tests fail, STATUS fresh", "exit 1", False, "tests"), ("tests pass, STATUS stale", "true", True, "status"), ("both fine", "true", False, None)):
    reset(); tc(cmd)()
    if stale:
        set_status("stale\n")
    snapshot()
    L = norm_legacy(run_legacy(str(FIXED), b'{"session_id":"s"}', PD))
    tl = tree()
    restore()
    fast = norm_mod(run_mod("Stop", "stop_fast", b'{"session_id":"s"}', PD))
    slow_r = norm_mod(run_mod("Stop", "stop_tests", b'{"session_id":"s"}', PD, slow=True))
    blocks = [x for x in (fast, slow_r) if x[0] == "block"]
    STAT["stop_pair"][0] += 1
    ok = (L[0] == "block") == bool(blocks) and (not blocks or L[1] == blocks[0][1] and len(blocks) == 1)
    if want != "tests" and tree() != tl:       # files written (the STATUS session line): equal, except where the tests failed (documented)
        ok = False
    if not ok: STAT["stop_pair"][1] += 1
    check("stop_fast + stop_tests together equal the script: " + label, ok, (L, fast, slow_r))
reset(); tc("exit 1")(); set_status("stale\n")
fast = norm_mod(run_mod("Stop", "stop_fast", b'{"session_id":"s"}', PD)); slow_r = norm_mod(run_mod("Stop", "stop_tests", b'{"session_id":"s"}', PD, slow=True))
check("stop_fast + stop_tests: stale STATUS AND failing tests -> two separate blocks (documented difference; the script reported only the tests)",
      fast[0] == "block" and "not updated" in fast[1] and slow_r[0] == "block" and "tests failed" in slow_r[1], (fast, slow_r))
reset(); tc("exit 1")(); snapshot()
run_mod("Stop", "stop_fast", b'{"session_id":"sess-xyz"}', PD)
check("stop_fast: rewrites the session line even when the tests fail (documented difference)", b"sess-xyz" in (PD / "docs/STATUS.md").read_bytes())

# ================================================================ 4 save_plan
def plan(name, content="# Plan\n", age=60):
    def f():
        write(".claude/plans/" + name, content, int(time.time()) - age, root=HOME)
    return f


def plans(*specs):
    def f():
        for s in specs:
            plan(*s)()
    return f


def sp(label, setup=None, stdin=None, **kw):
    diff_case("save_plan", label, "PostToolUse", "save-plan.sh", "save_plan", stdin or {"tool_name": "ExitPlanMode", "tool_input": {"plan": "x"}}, setup=setup, **kw)


sp("plans folder exists but empty", expect="allow")
sp("plans folder missing", setup=lambda: shutil.rmtree(HOME / ".claude"), expect="allow")
sp("one fresh plan with a generated 3-word name", plan("twinkly-snuggling-fox.md"), expect="allow", expect_in="docs/plans/%s-twinkly.md" % today())
sp("plan name without a trailing word pair", plan("myplan.md"), expect_in="-myplan.md")
sp("plan name with four words: only the last pair is cut", plan("a-b-c-d.md"), expect_in="-a-b.md")
sp("plan name with capitals is not cut", plan("Plan-Foo-Bar.md"), expect_in="Plan-Foo-Bar.md")
sp("plan name with digits is not cut", plan("plan-2-fox.md"), expect_in="plan-2-fox.md")
sp("plan name with a space", plan("my plan-foo-bar.md"), expect_in="my plan.md")
sp("plan name longer than 50 characters", plan("a" * 70 + "-big-cat.md"), expect_in="a" * 50 + ".md")
sp("non-ascii title", plan("خطة-الميزة-glowing-fox.md", "# خطة\n"), expect_in="خطة-الميزة")
sp("non-ascii title longer than 50 characters", plan("ع" * 60 + "-glowing-fox.md", "# خطة\n"), expect_in="ع" * 50)
sp("plan older than 2 hours", plan("old-plan-here.md", age=7300), expect="allow", expect_in="")
sp("plan 7100 seconds old counts", plan("edge-plan-here.md", age=7100), expect_in="-edge.md")
sp("newest of several plans wins", plans(("older-quick-fox.md", "old\n", 900), ("newer-quick-fox.md", "new\n", 30), ("oldest-quick-fox.md", "oldest\n", 3000)), expect_in="-newer.md")
sp("two plans with the same mtime (ls -t ties)", lambda: (write(".claude/plans/bbb-x-y.md", "b", 1_800_000_000 if False else int(time.time()) - 100, root=HOME), write(".claude/plans/aaa-x-y.md", "a", os.stat(HOME / ".claude/plans/bbb-x-y.md").st_mtime, root=HOME)))
sp("same content already saved: no message", lambda: (plan("same-plan-here.md", "same\n")(), write("docs/plans/%s-same.md" % today(), "same\n")), expect="allow")
sp("different content already saved: overwritten with a message", lambda: (plan("diff-plan-here.md", "new text\n")(), write("docs/plans/%s-diff.md" % today(), "old text\n")), expect_in="Plan saved")
sp("only non-md files", lambda: write(".claude/plans/note.txt", "x", root=HOME), expect="allow")
sp("hidden .md file is ignored", lambda: write(".claude/plans/.hidden-aa-bb.md", "x", root=HOME), expect="allow")
sp("project folder missing", plan("nowhere-plan-here.md"), proj=HOME / "nowhere", expect="allow")
sp("docs/plans is a file (cp fails, the message is still printed)", lambda: (plan("coll-plan-here.md")(), shutil.rmtree(PD / "docs/plans"), write("docs/plans", "i am a file")), expect_in="Plan saved", log_ok=True)
sp("plan file is a symlink to a fresh file", lambda: (write("real-plan.txt", "# linked\n", root=HOME), (HOME / ".claude/plans/link-plan-here.md").symlink_to(HOME / "real-plan.txt")), expect_in="-link.md")
sp("large plan (3 MB)", plan("big-plan-here.md", "# plan\n" + "line of text\n" * 250000), expect_in="-big.md")
sp("unexpected extra fields on stdin do not matter", plan("json-plan-here.md"), stdin={"tool_name": "ExitPlanMode", "x": [1, {"y": 2}]}, expect_in="-json.md")
sp("empty plans dir name collision: an md directory is skipped by the module only", lambda: (HOME / ".claude/plans/dir-aa-bb.md").mkdir())

# ================================================================ 5 model_switch
def ms(label, stdin, setup=None, **kw):
    diff_case("model_switch", label, "PreModelSwitch", "model-switch.sh", "model_switch", stdin, setup=setup, **kw)


ms("model fields and a session id", {"model": "opus", "previous_model": "sonnet", "session_id": "abcdef123456789"})
ms("no model fields", {"session_id": "abcdef123456", "x": 1})
ms("only a session id shorter than 8", {"model": "m", "session_id": "ab"})
ms("no session id", {"model": "haiku"})
ms("keys are matched case-insensitively", {"Model_Name": "x", "NEW_MODEL": "y", "other": 1})
ms("key order is kept", {"to_model": "b", "z": 1, "from_model": "a", "session_id": "12345678"})
ms("value is an object and a list", {"model": {"id": "x", "n": [1, 2]}, "models": ["a", "b"], "session_id": "s"})
ms("value is null, true and a number", {"model": None, "m_model": True, "n_model": 1.5, "session_id": 123456789012})
ms("value with a newline", {"model": "a\nb", "session_id": "s"})
ms("session id with a trailing newline", {"model": "a", "session_id": "ab\n"})
ms("unicode model name", {"model": "نموذج-✓", "session_id": "ٱلسلام عليكم"})
ms("existing log is appended to", {"model": "opus", "session_id": "s"}, setup=lambda: write("docs/memory/model-log.md", "# Model log (auto)\n\n- 2026-01-01 00:00 model=old session=x\n"))
ms("docs/memory missing is created with the header", {"model": "opus", "session_id": "s"}, setup=lambda: shutil.rmtree(PD / "docs/memory"))
ms("log without a trailing newline", {"model": "opus", "session_id": "s"}, setup=lambda: write("docs/memory/model-log.md", "# Model log (auto)\n\n- old"))
ms("invalid JSON", b"{oops")
ms("empty stdin", b"")
ms("JSON list", [1, 2])
ms("JSON string", b'"model"')
ms("invalid UTF-8", b'{"model": "caf\xe9"}')
ms("lone surrogate in a value", b'{"model": "a\\ud800", "session_id": "s"}')
ms("project folder missing", {"model": "x"}, proj=HOME / "nowhere")
ms("huge value (2 MB)", {"model": "x" * (2 << 20), "session_id": "s"})
ms("model-log.md is a directory (the script fails quietly; the module logs the error)", {"model": "x"}, setup=lambda: (PD / "docs/memory/model-log.md").mkdir(), log_ok=True)

# ================================================================ 6 session_start
IDEAS = (FIX / "ideas_open.md").read_text()


def ss(label, setup=None, stdin=None, **kw):
    diff_case("session_start", label, "SessionStart", "session-start.sh", "session_start", stdin if stdin is not None else {"session_id": "s", "source": "startup"},
              setup=setup, ignore_stdout=False, **kw)


def commits(n):
    for i in range(n):
        write("c%d.txt" % i, "x%d\n" % i)
        sh("git", "add", "-A"); sh("git", "commit", "-q", "-m", "commit number %d" % i)


ss("template project as created", expect="allow", expect_in="=== PROJECT BRIEF")
ss("no STATUS.md", lambda: (PD / "docs/STATUS.md").unlink(), expect_in="STATUS.md missing")
ss("status-extract not installed: sed fallback", lambda: (HOME / "Developer/AI-Workspace/bin/status-extract").unlink(), expect_in="docs/STATUS.md (brief")
ss("long STATUS (60 KB) is cut by status-extract", lambda: set_status(status_text("\n".join("## Section %d\nfirst line %d\n- more\n" % (i, i) for i in range(1500)))))
ss("long STATUS with the extract missing: first 120 lines", lambda: (set_status(status_text("\n".join("line %d" % i for i in range(300)) + "\n")), (HOME / "Developer/AI-Workspace/bin/status-extract").unlink()))
ss("STATUS with invalid UTF-8", lambda: set_status(status_text() + "\n").write_bytes(status_text().encode() + b"\xff\xfe\n"))
ss("feature ideas: 4 open, top 3 shown", lambda: write("docs/FEATURE-IDEAS.md", IDEAS), expect_in="4 open idea(s)")
ss("feature ideas: nothing open", lambda: write("docs/FEATURE-IDEAS.md", "# I\n\n## Open\n- [x] done\n\n## Later\n- [ ] x\n"))
ss("feature ideas: '## Opened' counts as the Open heading (awk prefix match)", lambda: write("docs/FEATURE-IDEAS.md", "## Opened ideas\n- [ ] A\n## Other\n- [ ] B\n"))
ss("feature ideas: two Open sections, CRLF file", lambda: write("docs/FEATURE-IDEAS.md", "## Open\r\n- [ ] A\r\n## Done\r\n## Open\r\n- [ ] B\r\n"))
ss("feature ideas: no trailing newline", lambda: write("docs/FEATURE-IDEAS.md", "## Open\n- [ ] A\n- [ ] B"))
ss("memory index of 100 lines (first 60 shown)", lambda: write("docs/memory/MEMORY.md", "".join("- memory line %d\n" % i for i in range(100))), expect_in="memory line 59")
ss("memory index without a trailing newline", lambda: write("docs/memory/MEMORY.md", "- one\n- two"))
ss("memory index exactly 60 lines", lambda: write("docs/memory/MEMORY.md", "".join("- m %d\n" % i for i in range(60))))
ss("memory index missing", lambda: (PD / "docs/memory/MEMORY.md").unlink())
ss("no git repository", lambda: shutil.rmtree(PD / ".git"))
ss("git repository without commits", lambda: (shutil.rmtree(PD / ".git"), sh("git", "init", "-q", "-b", "main")))
ss("12 commits: only the last 10", lambda: commits(12))
ss("dirty tree with 45 untracked files (30 shown)", lambda: [write("u/f%02d.txt" % i, "x") for i in range(45)])
ss("tracked change, staged change and untracked", lambda: (write("a.txt", "1"), sh("git", "add", "a.txt"), write("CLAUDE.md", "changed\n"), write("new.txt", "n")))
ss("PUSH-FAILED marker (one line)", lambda: write(".git/PUSH-FAILED", "To github.com: rejected\n"), expect_in="auto-push failed (To github.com: rejected)")
ss("PUSH-FAILED marker (several lines, no newline at the end)", lambda: write(".git/PUSH-FAILED", "line1\nline2\n\n\nlast"))
ss("PUSH-FAILED marker empty", lambda: write(".git/PUSH-FAILED", ""))
ss("branch ahead of its upstream by 2", lambda: (sh("git", "init", "-q", "--bare", str(HOME / "remote.git")), sh("git", "remote", "add", "origin", str(HOME / "remote.git")), sh("git", "push", "-q", "-u", "origin", "main"), commits(2)), expect_in="not on GitHub: 2")
ss("no upstream configured", expect_in="not on GitHub: 0")
ss("detached HEAD", lambda: sh("git", "checkout", "-q", "--detach"), expect_in="branch: ,")
ss("SKILLS.md missing", lambda: (PD / "docs/SKILLS.md").unlink(), expect_in="FIRST TASK THIS SESSION")
ss("SKILLS.md says review not done", lambda: write("docs/SKILLS.md", "# S\n\nSkills review: not done\n"), expect_in="FIRST TASK")
ss("SKILLS.md says review not done, different case and spacing", lambda: write("docs/SKILLS.md", "# S\n\nskills review:    NOT DONE\n"), expect_in="FIRST TASK")
ss("SKILLS.md reviewed long ago (100 days)", lambda: write("docs/SKILLS.md", (FIX / "skills_table.md").read_text(), time.time() - 100 * 86400), expect_in="over 90 days")
ss("SKILLS.md 91 days old counts as old", lambda: write("docs/SKILLS.md", (FIX / "skills_table.md").read_text(), time.time() - 91 * 86400 - 5), expect_in="over 90 days")
ss("SKILLS.md 89 days old is current", lambda: write("docs/SKILLS.md", (FIX / "skills_table.md").read_text(), time.time() - 89 * 86400), expect_in="project skills")
ss("SKILLS.md with a 30-row table (rows 3-20 shown)", lambda: write("docs/SKILLS.md", "# S\n\nSkills review: done\n\n" + "".join("| row %d | x |\n" % i for i in range(30))), expect_in="row 19")
ss("SKILLS.md with no table", lambda: write("docs/SKILLS.md", "# S\n\nSkills review: done\n\nplain text\n"))
ss("project folder missing", None, proj=HOME / "nowhere", expect="allow")
ss("stdin empty", None, stdin=b"")

# SHIPMIRACLE_QUIET is ignored by project modules (the script has no such switch either)
for name, ev in (("session_start", "SessionStart"), ("shipmiracle_state", "Stop"), ("model_switch", "PreModelSwitch")):
    reset()
    r = run_mod(ev, name, b'{"model":"x","session_id":"s"}', PD, {"SHIPMIRACLE_QUIET": "1"})
    if name == "session_start":
        wrote = r[0].startswith(b"=== PROJECT BRIEF")
    elif name == "shipmiracle_state":
        wrote = state_file().exists()
    else:
        wrote = (PD / "docs/memory/model-log.md").exists()
    check("SHIPMIRACLE_QUIET=1 is ignored by " + name, bool(wrote), r)

# PUSH-BLOCKED (new marker of the gitleaks git hook): additive, only when the marker exists
reset(); write(".git/PUSH-BLOCKED", "gitleaks: 1 finding\n")
o = run_mod("SessionStart", "session_start", b"{}", PD)[0].decode()
check("session_start: PUSH-BLOCKED marker adds one WARNING line", "WARNING: last auto-push was blocked by the secret scan (gitleaks: 1 finding); fix the finding, then run: git push\n" in o and "--- uncommitted changes" in o, o[-600:])
reset()
o2 = run_mod("SessionStart", "session_start", b"{}", PD)[0].decode()
check("session_start: without the marker the text is identical to the script (see the differential cases)", "PUSH-BLOCKED" not in o2 and "blocked by the secret scan" not in o2)

# ================================================================ 7 ownership, through the whole pipeline (no per-slot filtering)
def full(event, stdin, proj=PD, extra=None, slow=False):
    changes = {"CLAUDE_PROJECT_DIR": str(proj)}
    changes.update(extra or {})
    core._FILES.clear()
    with Env(**changes):
        os.chdir(str(proj)) if os.path.isdir(str(proj)) else None
        return core.run(event, stdin if isinstance(stdin, bytes) else json.dumps(stdin).encode(), slow)


reset(); make_registry()
full("UserPromptSubmit", {"prompt": "x"})
check("owned: registry has the project and settings.json registers no project hook -> shipmiracle_state runs", state_file().exists())
reset()
write(".claude/settings.json", (FIX / "settings_legacy.json").read_text())
full("UserPromptSubmit", {"prompt": "x"})
check("not owned: settings.json still registers .claude/hooks/shipm-state.sh -> shipmiracle_state does not run", not state_file().exists())
reset(); write(".claude/settings.json", (FIX / "settings_legacy.json").read_text()); write(".git/x", "")
stage("a.txt", "id %s\n" % AKIA)()
o = full("PreToolUse", bashin("git commit -m x"))
s = json.loads((FIX / "settings_legacy.json").read_text())
s["hooks"]["PreToolUse"] = [x for x in s["hooks"]["PreToolUse"] if "block-secrets" not in json.dumps(x)]
reset(); write(".claude/settings.json", json.dumps(s)); stage("a.txt", "id %s\n" % AKIA)()
o = full("PreToolUse", bashin("git commit -m x"))
check("ownership is per hook: block_secrets is owned (blocks), shipmiracle_state is not (no state file)", b"looks like a secret" in o[0] and not state_file().exists(), o)
reset(); write(".claude/settings.local.json", '{"hooks": {"Stop": [{"hooks": [{"command": "$CLAUDE_PROJECT_DIR/.claude/hooks/shipm-state.sh done"}]}]}}')
full("Stop", {"session_id": "s"})
check("not owned: settings.local.json registers shipm-state.sh", not state_file().exists())
reset(); (CFG / "registry.json").write_text(json.dumps({"v": 1, "projects": {}}))
full("UserPromptSubmit", {"prompt": "x"})
check("not owned: project not in the registry", not state_file().exists())
reset(); (CFG / "registry.json").unlink()
full("UserPromptSubmit", {"prompt": "x"})
check("not owned: no registry file", not state_file().exists())
reset(); (CFG / "registry.json").write_text("{damaged")
full("UserPromptSubmit", {"prompt": "x"})
check("not owned: registry unreadable (project_owned is False, no hook runs)", not state_file().exists() and core.project_owned(str(PD), "shipmiracle_state", str(HOME / "Developer")) is False)
reset(); (CFG / "registry.json").write_text(json.dumps({"v": 2, "projects": {pid_of(PD): {}}}))
full("UserPromptSubmit", {"prompt": "x"})
check("not owned: registry with another version", not state_file().exists())
make_registry()
reset(); (PD / ".claude/settings.json").unlink()
full("UserPromptSubmit", {"prompt": "x"})
check("owned: settings.json missing counts as no project hook registered", state_file().exists())
reset(); (PD / ".claude/settings.json").write_text("{not json but mentions nothing")
full("UserPromptSubmit", {"prompt": "x"})
check("owned: unparsable settings.json that does not name the script", state_file().exists())

# symlinked project (sample-app style: ~/sample-app -> ~/Developer/sample-app)
reset()
real = HOME / "Developer" / "sample-app"
shutil.move(str(PD), str(real))
link = HOME / "sample-app"
link.symlink_to(real)
make_registry([real])
(CFG / "registry.json").write_text(json.dumps({"v": 1, "projects": {pid_of(real): {"name": "sample-app"}}}))
full("PreModelSwitch", {"model": "opus", "session_id": "s"}, proj=link)
check("symlinked project: owned through realpath, model_switch writes into the real folder", (real / "docs/memory/model-log.md").exists())
full("UserPromptSubmit", {"prompt": "x"}, proj=link)
check("symlinked project: shipmiracle_state follows the script (folder not directly under Developer by its own path: no state file)", not state_file("sample-app").exists())
LS = run_legacy("shipm-state.sh", b"{}", link, args=("working",))
check("symlinked project: the script writes no state file either", not state_file("sample-app").exists() and LS[0] == 0)
full("UserPromptSubmit", {"prompt": "x"}, proj=real)
check("project addressed by its real path gets a state file", state_file("sample-app").exists())
make_registry()

# every project slot is registered where the table says
want = {("SessionStart", "session_start"), ("PreToolUse", "block_secrets"), ("PreToolUse", "shipmiracle_state"), ("UserPromptSubmit", "shipmiracle_state"), ("Stop", "shipmiracle_state"),
        ("Notification", "shipmiracle_state"), ("Stop", "stop_fast"), ("Stop--slow", "stop_tests"), ("PostToolUse", "save_plan"), ("PreModelSwitch", "model_switch")}
have = {(k, s.name) for k, v in core.PIPELINES.items() for s in v if s.fn is not None and s.project}
check("all seven modules are registered as project modules in the pipeline slots of the table", want <= have and {n for _, n in have} >= set(core.PROJECT_SH), sorted(want - have))
check("core.MODULE_FILE maps every project module to project.py", all(core.MODULE_FILE[n] == "project" for n in core.PROJECT_SH))
os.environ.pop("SHIPMIRACLE_HOOK_NO_LOAD", None)
core._FILES.clear()
sys.modules.pop("shipmiracle.hooks.project", None)
reset(); make_registry()
for s in core.PIPELINES["UserPromptSubmit"]:
    if s.name == "shipmiracle_state":
        s.fn = None
with Env(CLAUDE_PROJECT_DIR=str(PD)):
    os.chdir(str(PD))
    core.run("UserPromptSubmit", b"{}", False)
check("the dispatcher lazy-loads shipmiracle.hooks.project by itself (core._load)", state_file().exists())
os.environ["SHIPMIRACLE_HOOK_NO_LOAD"] = "1"
import shipmiracle.hooks.project as P  # noqa: E402  (the lazy load above re-imported it)

# ================================================================ 8 static checks, import budget, performance
src = (ROOT / "shipmiracle/hooks/project.py").read_text()
check("no shell=True anywhere in project.py", "shell=True" not in src)
check("bash -lc is the only shell run and uses an argv list", src.count('"bash", "-lc"') == 1 and "os.system" not in src and "os.popen" not in src)
tree_ = ast.parse(src)
top = sorted({str(n.names[0].name if isinstance(n, ast.Import) else n.module or "pkg:" + n.names[0].name) for n in tree_.body if isinstance(n, (ast.Import, ast.ImportFrom))})
check("module-level imports: os, json, re, time and the package only (lazy imports for the rest)", set(top) <= {"__future__", "json", "os", "re", "time", "pkg:core", "pkg:io", "core"}, top)
imp = subprocess.run(["/usr/bin/python3", "-I", "-S", "-c",
                      "import sys; sys.path.insert(0, %r); import shipmiracle.hooks.core; a=set(sys.modules); import shipmiracle.hooks.project; print(sorted(set(sys.modules)-a))" % str(ROOT)],
                     capture_output=True, text=True)
added = ast.literal_eval(imp.stdout.strip() or "None") if imp.returncode == 0 else None
check("import budget: importing project.py after core adds only itself", added == ["shipmiracle.hooks.project"], (added, imp.stderr[-300:]))
for name in ("subprocess", "shutil", "tempfile", "signal", "hashlib", "shipmiracle.projects"):
    check("import budget: %s is not imported at module level" % name, added is not None and name not in added)

K_LATENCY = 15


def BASE_REF():
    return T.p95_of(lambda: run_mod("Notification", "shipmiracle_state", {"notification_type": "idle_prompt"}, PD), 100)


# ---- performance: in-process core.run with only the module (registry file re-read every call), p50/p95 of 200 calls
def bench(label, event, name, stdin, setup=None, n=200, slow=False, limit=None):
    reset(); make_registry()
    if setup:
        setup()
    xs = []
    for _ in range(n):
        t0 = time.perf_counter()
        run_mod(event, name, stdin, PD, slow=slow)
        xs.append(time.perf_counter() - t0)
    xs.sort()
    p50, p95 = xs[len(xs) // 2] * 1000, xs[int(len(xs) * 0.95) - 1] * 1000
    print("BENCH %-44s p50 %6.2f ms  p95 %6.2f ms  (n=%d)" % (label, p50, p95, n))
    if limit:
        one = lambda: run_mod(event, name, stdin, PD, slow=slow)
        lim_s = limit / 1000.0
        # Load-tolerant (26 Oct 2026): p95 <= max(limit, K x baseline). Baseline = p95 of the lightest hook path (Notification idle_prompt, no write, ~1 ms on a quiet Mac) measured
        # right before and right after, same process, same load. K = 15 = limit 15 ms / that ~1 ms, so a quiet Mac behaves like the absolute limit and a loaded one gets proportional room.
        ok, rep, best = T.robust_around(lambda: T.p95_of(one, n), BASE_REF, lim_s, K_LATENCY)
        print("INFO %s: %s" % (label, rep))
        check("performance: %s p95 <= max(%d ms, %g x baseline) :: %s" % (label, limit, K_LATENCY, rep), ok, rep)
    return p50, p95


bench("shipmiracle_state (PreToolUse working, file write)", "PreToolUse", "shipmiracle_state", {"tool_name": "Read"}, limit=15)
bench("shipmiracle_state (Notification idle_prompt, no write)", "Notification", "shipmiracle_state", {"notification_type": "idle_prompt"}, limit=15)
bench("block_secrets (unrelated Bash command)", "PreToolUse", "block_secrets", bashin("ls -la"), limit=15)
bench("save_plan (no plan file)", "PostToolUse", "save_plan", {"tool_name": "ExitPlanMode"}, limit=15)
bench("save_plan (plan already saved)", "PostToolUse", "save_plan", {"tool_name": "ExitPlanMode"}, setup=lambda: (plan("perf-plan-here.md")(), write("docs/plans/%s-perf.md" % today(), "# Plan\n")), limit=15)
bench("model_switch (append)", "PreModelSwitch", "model_switch", {"model": "opus", "session_id": "abcdef123"}, limit=15)
bench("block_secrets (git commit, clean index: 2 git runs)", "PreToolUse", "block_secrets", bashin("git commit -m x"), n=40)
bench("stop_fast (nothing changed: 2 git runs)", "Stop", "stop_fast", {"session_id": "s"}, n=40)
bench("stop_fast (source changed, STATUS fresh)", "Stop", "stop_fast", {"session_id": "s"}, setup=fresh_change(), n=40)
bench("stop_tests (no test-command, nothing changed)", "Stop", "stop_tests", {"session_id": "s"}, n=40, slow=True)
bench("session_start (full brief)", "SessionStart", "session_start", {"session_id": "s"}, n=20)

# mutant: the same code made slower by a sleep must still FAIL the relative check (the check is not a rubber stamp)
reset(); make_registry()
check("performance mutant: shipmiracle_state slowed by a sleep (4 x the allowed p95) is noticed by the relative check",
      T.mutant_noticed(lambda: run_mod("PreToolUse", "shipmiracle_state", {"tool_name": "Read"}, PD), BASE_REF, 0.015, K_LATENCY))

print()
print("%-14s %6s %10s" % ("hook", "cases", "mismatches"))
for k, (n, m) in sorted(STAT.items()):
    print("%-14s %6d %10d" % (k, n, m))
for h in ("shipmiracle_state", "block_secrets", "stop_fast", "stop_tests", "save_plan", "model_switch", "session_start"):
    check("%s: at least 15 differential inputs" % h, STAT.get(h, [0])[0] >= 15, STAT.get(h))
shutil.rmtree(TMP, ignore_errors=True)
print("ALL PASS" if not fails else "%d FAILED: %s" % (fails, FAILED))
sys.exit(1 if fails else 0)
