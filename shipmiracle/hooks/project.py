"""Project hook modules (Phase 4a T4): the seven template hooks of templates/base/.claude/hooks/ as dispatcher modules.
  session_start (SessionStart), block_secrets (PreToolUse Bash), shipmiracle_state (UserPromptSubmit + PreToolUse -> working, Stop -> done,
  Notification -> needs-input), stop_fast (Stop), stop_tests (the separate `Stop --slow` entry), save_plan (PostToolUse ExitPlanMode),
  model_switch (PreModelSwitch).
Each one is a line-by-line port of its .sh file (the legacy script is the reference; tests/hooks_project_test.py runs both and compares).
They run only when core.project_owned() says so (project in the registry AND its .claude/settings.json no longer registers the matching
.claude/hooks/<x>.sh), so a hook never runs twice. SHIPMIRACLE_QUIET is ignored here (spec 2.4 rule 2). Every function takes a Ctx and returns a
Result or None; an exception propagates to core.run_module (logged, counts as no output: fail-open as the scripts were).

NOT ported: format.sh (PostToolUse Edit|Write formatter). It stays a per-project hook because it runs whatever formatter the project has
(swiftformat, node_modules prettier, ruff), is project-specific by design, never blocks and writes only the edited file; the dispatcher
gains nothing from it. `shipm project hooks-global` keeps its settings entry.

stop_tests and the legacy bug: stop-gate.sh reads `${PIPESTATUS[0]}` after `out=$(bash -lc ... | tail -30)`, which is tail's status, so it has NEVER
blocked on a failing test-command (the documented intent is to block). Strict parity is the default: with config `hooks.stop_tests_block` off
(default) stop_tests runs the command, appends the output tail to <state>/stop-tests.log and never blocks; with it on it blocks (exit 2 + last
30 lines). The owner turns it on per decision (docs/DECISIONS.md).

Known, deliberate differences from the scripts (all listed in docs/STATUS.md):
 - stop_fast does NOT run the test command; stop_tests (Stop --slow) does. The script ran tests first and returned only the test failure;
   now a stale STATUS and a failing test are reported by two separate Stop entries, and the "Last Claude session" line is rewritten even
   when the tests fail (the script rewrote it only after they passed).
 - state files and the model log are written by python (shipmiracle_state.json: atomic, 0600; model log: same bytes); session_start's stderr noise
   (the shell complaint about `<topic>` inside backticks) is gone; the stdout is identical.
 - the script that is run with `bash -lc <test-command>` has no hook timeout of its own (Claude's default applied); stop_tests uses TEST_TIMEOUT
   and kills the whole process group; a timeout is "no block" (what Claude does with a hook it has killed).
Import budget: os, json, re, time at module level; subprocess, shutil, tempfile, signal are imported where used."""
from __future__ import annotations

import json
import os
import re
import time

from . import core
from . import io as hio
from .core import Result

TEST_TIMEOUT = 600          # seconds for `bash -lc <test-command>` (assumed Claude's own hook default; override only under SHIPMIRACLE_TEST=1)
GIT_TIMEOUT = 20
MAX_OUT_KEEP = 1 << 18      # bytes of test output kept (the hook shows the last 30 lines)

# block-secrets.sh, verbatim (grep -Eiq per line)
SECRET_RE = re.compile(r"""(sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{36}|xox[baprs]-[A-Za-z0-9-]{10,}|-----BEGIN [A-Z ]*PRIVATE KEY-----|(api[_-]?key|secret|token|password)\s*[:=]\s*["'][^"']{8,})""", re.I)
ENV_RE = re.compile(r"(^|/)\.env($|\.)")
ENV_EXAMPLE_RE = re.compile(r"\.env\.example$")
MSG_CRED = "Blocked: staged changes contain something that looks like a secret. Move it to .env and retry."
MSG_ENV = "Blocked: a .env file is staged. Unstage it (git restore --staged .env)."

# stop-gate.sh
STOP_ACTIVE_RE = re.compile(rb'"stop_hook_active": *true')
EXCL_DOCS_RE = re.compile(r"^docs/(STATUS\.md|DECISIONS\.md|FEATURE-IDEAS\.md|memory/|plans/)", re.I)
EXCL_DOT_RE = re.compile(r"^(\.claude/|\.agents/|\.vscode/|\.github/|\.githooks/|\.editorconfig$|\.gitignore$)")

STATES = {"UserPromptSubmit": "working", "PreToolUse": "working", "Stop": "done", "Notification": "needs-input"}


# ---------------------------------------------------------------- helpers
def _dir(ctx):
    """`cd "${CLAUDE_PROJECT_DIR:-.}"`: the folder, or None when the cd would fail."""
    d = ctx.env.get("CLAUDE_PROJECT_DIR") or ctx._s("cwd") or "."
    return d if os.path.isdir(d) else None


def _git(args, cwd, timeout=GIT_TIMEOUT):
    """stdout bytes of `git <args>` in cwd (stderr dropped, as 2>/dev/null); b"" on any failure."""
    import subprocess
    try:
        p = subprocess.run(["git"] + list(args), cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=timeout)
        return p.stdout
    except (OSError, subprocess.SubprocessError, ValueError):
        return b""


def _lines(data: bytes):
    parts = data.split(b"\n")
    if parts and parts[-1] == b"":
        parts.pop()
    return parts


def _dec(b: bytes) -> str:
    return b.decode("utf-8", "surrogateescape")


def _sub(s):
    """What bash's $(...) does to a printed value: NULs dropped, trailing newlines stripped. None when python's print() would fail
    (a lone surrogate cannot be encoded: the script's python then printed nothing)."""
    try:
        s.encode("utf-8")
    except UnicodeEncodeError:
        return None
    return s.replace("\x00", "").rstrip("\n")


def _data(ctx):
    """The stdin JSON as the scripts' `json.load(sys.stdin)` saw it: a dict, else None (invalid UTF-8, invalid JSON, not an object)."""
    if not hasattr(ctx, "_pj"):
        try:
            d = json.loads(ctx.raw.decode("utf-8"))
        except ValueError:                  # includes UnicodeDecodeError
            d = None
        ctx._pj = d if isinstance(d, dict) else None
    return ctx._pj


def _printed(d, key):
    """`print(d.get(key, ""))` captured by $(...): str(value) cleaned, or None when the script's python failed."""
    if d is None:
        return None
    v = d.get(key, "")
    return _sub(v if isinstance(v, str) else str(v))


def _basename(p):
    p = p.rstrip("/") or "/"
    return os.path.basename(p) or p


def _dirname(p):
    p = p.rstrip("/") or "/"
    return os.path.dirname(p) or "."


def _changed(pd):
    """Source files changed since HEAD, excluding the record itself (stop-gate.sh `changed`): a list of lines."""
    out = _git(["diff", "--name-only", "HEAD"], pd) + _git(["ls-files", "--others", "--exclude-standard"], pd)
    res = []
    for b in _lines(out):
        l = _dec(b)
        if EXCL_DOCS_RE.search(l) or EXCL_DOT_RE.search(l):
            continue
        res.append(l)
    return res


def _stop_precheck(ctx):
    """(project dir, changed list) when the stop gate has work to do, else None (stop_hook_active, no .git dir, nothing changed)."""
    pd = _dir(ctx)
    if pd is None or STOP_ACTIVE_RE.search(ctx.raw) or not os.path.isdir(os.path.join(pd, ".git")):
        return None
    changed = _changed(pd)
    return (pd, changed) if changed else None


# ---------------------------------------------------------------- shipmiracle_state (shipm-state.sh)
def shipmiracle_state(ctx):
    state = STATES.get(ctx.event)
    if state is None:
        return None
    d = ctx.env.get("CLAUDE_PROJECT_DIR") or ctx._s("cwd") or os.getcwd()
    name = _basename(d)
    parent = _dirname(d)
    lhs = os.path.realpath(parent) if os.path.isdir(parent) else ""
    rhs = ctx.dev if os.path.isdir(ctx.dev) else ""
    if lhs != rhs:
        return None             # only a folder directly under ~/Developer gets a state file
    data = _data(ctx)
    msg = ""
    if data is not None:
        v = data.get("message", "")
        m = _sub((v if isinstance(v, str) else str(v))[:140])
        msg = m if m is not None else ""
    if state == "needs-input":
        nt = _printed(data, "notification_type") or ""
        if nt in ("idle_prompt", "auth_success") or "waiting for your input" in msg:
            return None         # Claude's "waiting for your input" notice is not a question: keep the state (done)
    _write_state(os.path.join(ctx.state, name + ".json"), {"project": name, "path": d, "state": state, "message": msg, "ts": int(ctx.now)})
    return None


def _write_state(path, obj):
    """Atomic like hio.atomic_json (pid temp file in the same folder, 0600, replace) but without fsync: the state file is a status flag that is
    rewritten on every tool call (the script never synced it either), and an fsync costs 5-10 ms of the module's 15 ms budget."""
    hio.ensure_dir(os.path.dirname(path))
    tmp = "%s.%d.tmp" % (path, os.getpid())
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------- block_secrets (block-secrets.sh)
def block_secrets(ctx):
    data = _data(ctx)
    d = data.get("tool_input") if data is not None else None
    if not isinstance(d, dict):
        return None
    v = d.get("command", "")
    cmd = _sub(v if isinstance(v, str) else str(v))
    if cmd is None or ("git commit" not in cmd and "git push" not in cmd):
        return None
    pd = _dir(ctx)
    if pd is None:
        return None
    staged = _dec(_git(["diff", "--cached", "-U0"], pd))
    for l in staged.split("\n"):
        if l.startswith("+") and not l.startswith("+++") and SECRET_RE.search(l):
            return Result(block=True, reason=MSG_CRED, exit_code=2)
    names = [_dec(b) for b in _lines(_git(["diff", "--cached", "--name-only"], pd))]
    if any(ENV_RE.search(n) for n in names) and not any(ENV_EXAMPLE_RE.search(n) for n in names):
        return Result(block=True, reason=MSG_ENV, exit_code=2)
    return None


# ---------------------------------------------------------------- stop_fast (stop-gate.sh without the tests)
def stop_fast(ctx):
    pre = _stop_precheck(ctx)
    if pre is None:
        return None
    pd, changed = pre
    today = time.strftime("%Y-%m-%d", time.localtime(ctx.now))
    st = os.path.join(pd, "docs", "STATUS.md")
    if not os.path.isfile(st):
        return Result(block=True, reason="Stop blocked: docs/STATUS.md is missing. Create it (what changed, how verified, next, handoff).", exit_code=2)
    try:
        with open(st, "rb") as f:
            raw = f.read()
    except OSError:
        raw = b""
    if not re.search(rb"(?m)^Updated: *" + today.encode(), raw):
        return Result(block=True, exit_code=2, reason="Stop blocked: source files changed but docs/STATUS.md is not updated for today. Set its first 'Updated:' line to '%s · by: <engine/model> · mode: <mode>', record what changed, the exact verification, what is next and the handoff. Then stop again." % today)
    newest = None
    for l in changed:
        f = l.strip(" \t")                      # `read -r f` trims the IFS whitespace
        p = os.path.join(pd, f)
        if os.path.isfile(p):
            try:
                m = int(os.lstat(p).st_mtime)   # stat -f %m shows the link itself
            except OSError:
                continue
            newest = m if newest is None or m > newest else newest
    try:
        stm = int(os.lstat(st).st_mtime)
    except OSError:
        stm = 0
    if newest is not None and stm < newest:
        return Result(block=True, exit_code=2, reason="Stop blocked: docs/STATUS.md is older than the latest source change. Re-read it, update what changed/verified/next/handoff, save it, then stop again.")
    sid = _printed(_data(ctx), "session_id")
    if sid and hio.inside(st, pd):               # STATUS.md that is a symlink to a file outside the project is never rewritten
        line = "- Last Claude session: %s (%s). Resume: /resume in VS Code, or claude --resume %s" % (sid, today, sid)
        try:
            if re.search(rb"(?m)^- Last Claude session:", raw):
                with open(st, encoding="utf-8") as f:
                    t = f.read()
                t = re.sub(r"^- Last Claude session:.*$", line, t, count=1, flags=re.M)     # the script used the line as the template too
                with open(st, "w", encoding="utf-8") as f:
                    f.write(t)
            elif re.search(rb"(?m)^## Handoff", raw):
                with open(st, encoding="utf-8") as f:
                    t = f.read()
                t = t.replace("## Handoff\n", "## Handoff\n" + line + "\n", 1)
                with open(st, "w", encoding="utf-8") as f:
                    f.write(t)
        except (OSError, ValueError, re.error):
            pass                                 # the script's python failed silently as well
    return None


# ---------------------------------------------------------------- stop_tests (stop-gate.sh, the test run)
def _timeout() -> float:
    if os.environ.get("SHIPMIRACLE_TEST") == "1" and os.environ.get("SHIPMIRACLE_STOP_TESTS_TIMEOUT"):
        try:
            return float(os.environ["SHIPMIRACLE_STOP_TESTS_TIMEOUT"])
        except ValueError:
            pass
    return TEST_TIMEOUT


def stop_tests(ctx):
    pre = _stop_precheck(ctx)
    if pre is None:
        return None
    pd = pre[0]
    tc = os.path.join(pd, ".claude", "test-command")
    if not os.path.isfile(tc):
        return None
    try:
        with open(tc, "rb") as f:
            cmd = f.read().replace(b"\x00", b"").rstrip(b"\n")
    except OSError:
        cmd = b""
    import signal
    import subprocess
    import tempfile
    with tempfile.TemporaryFile() as out:
        try:
            p = subprocess.Popen(["bash", "-lc", cmd], cwd=pd, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, start_new_session=True)
        except (OSError, ValueError) as e:
            hio.log_err("stop_tests", e)
            return None
        try:
            rc = p.wait(timeout=_timeout())
        except subprocess.TimeoutExpired:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except OSError:
                pass
            p.wait()
            hio.log_err("stop_tests", RuntimeError("test command timed out after %ss" % _timeout()))
            return None
        if rc == 0:
            return None
        size = out.seek(0, 2)
        out.seek(max(0, size - MAX_OUT_KEEP))
        data = out.read()
    tail = b"\n".join(_lines(data)[-30:]).replace(b"\x00", b"").rstrip(b"\n")
    if not core.on(ctx.config("hooks.stop_tests_block", False)):
        # default: strict parity with stop-gate.sh, which in practice never blocks on a failing test-command (see the docstring)
        try:
            hio.append_line(os.path.join(ctx.state, "stop-tests.log"), "%s %s exit=%s `%s` | %s" % (
                time.strftime("%F %T", time.localtime(ctx.now)), os.path.basename(pd), rc, cmd.decode("utf-8", "replace")[:200],
                tail.decode("utf-8", "replace").replace("\n", " | ")[-800:]), inside_root=ctx.state)
        except OSError:
            pass
        return None
    msg = "Stop blocked: tests failed (`%s`). Fix them, then update docs/STATUS.md.\n%s" % (cmd.decode("utf-8", "replace"), tail.decode("utf-8", "replace"))
    return Result(block=True, reason=msg, exit_code=2)


# ---------------------------------------------------------------- save_plan (save-plan.sh)
def save_plan(ctx):
    pd = _dir(ctx)
    if pd is None:
        return None
    plans = os.path.join(ctx.home, ".claude", "plans")
    try:
        names = [n for n in os.listdir(plans) if n.endswith(".md") and not n.startswith(".")]
    except OSError:
        return None
    best = None
    for n in names:                              # ls -t: newest first, ties by name
        try:
            k = (-os.lstat(os.path.join(plans, n)).st_mtime_ns, n)
        except OSError:
            continue
        if best is None or k < best:
            best = k
    if best is None:
        return None
    src = os.path.join(plans, best[1])
    if not os.path.isfile(src):
        return None
    if int(ctx.now) - int(os.lstat(src).st_mtime) >= 7200:
        return None                              # only plans touched in the last 2 hours belong to this session
    base = best[1][:-3]
    slug = re.sub(r"-[a-z]+-[a-z]+\Z", "", base)[:50]
    rel = "docs/plans/%s-%s.md" % (time.strftime("%Y-%m-%d", time.localtime(ctx.now)), slug)
    dst = os.path.join(pd, rel)
    if not hio.inside(dst, pd) or os.path.islink(dst):      # docs/plans (or the plan file) that leads outside the project is never written
        hio.log_err("save_plan", PermissionError("refusing to write outside the project: " + dst))
        return None
    try:
        os.makedirs(os.path.join(pd, "docs", "plans"), exist_ok=True)
    except OSError:
        pass
    try:
        with open(src, "rb") as a, open(dst, "rb") as b:
            if a.read() == b.read():
                return None
    except OSError:
        pass
    import shutil
    try:
        shutil.copyfile(src, dst)
    except OSError as e:
        hio.log_err("save_plan", e)              # the script's cp complained on stderr and still echoed
    return Result(plain_stdout="Plan saved to %s (commit it with the work).\n" % rel)


# ---------------------------------------------------------------- model_switch (model-switch.sh)
def model_switch(ctx):
    pd = _dir(ctx)
    if pd is None:
        return None
    d = _data(ctx)
    if d is None:
        return None
    parts = ["%s=%s" % (k, d[k]) for k in d if "model" in k.lower()] or ["(no model fields)"]
    sid = d.get("session_id", "")
    line = _sub(" ".join(parts) + " " + "session=" + str(sid)[:8])
    if not line:
        return None
    mdir = os.path.join(pd, "docs", "memory")
    path = os.path.join(mdir, "model-log.md")
    if not hio.inside(path, pd) or os.path.islink(path):    # docs/memory (or the log) that leads outside the project is never written
        hio.log_err("model_switch", PermissionError("refusing to write outside the project: " + path))
        return None
    os.makedirs(mdir, exist_ok=True)
    data = ""
    if not os.path.isfile(path):
        data = "# Model log (auto)\n\nEvery model switch in this project, newest last.\n\n"
    data += "- %s %s\n" % (time.strftime("%Y-%m-%d %H:%M", time.localtime(ctx.now)), line)
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o666)
    try:
        os.write(fd, data.encode("utf-8"))
    finally:
        os.close(fd)
    return None


# ---------------------------------------------------------------- session_start (session-start.sh)
def session_start(ctx):
    """SessionStart: the project brief of session-start.sh, byte for byte on stdout. Sections in order: the header with today's date; docs/STATUS.md through
    bin/status-extract (first 120 lines when that fails; a "missing" line without the file); up to 3 open ideas of docs/FEATURE-IDEAS.md; the first 60 lines
    of docs/memory/MEMORY.md; for a git folder the last 10 commits, up to 30 uncommitted lines, the PUSH-FAILED / PUSH-BLOCKED markers and
    "branch: B, commits not on GitHub: N"; the skills line (first task when docs/SKILLS.md says "Skills review: not done" or is missing, a re-check note after
    90 days, else its table rows); the change-request brief when .shipmiracle/work.json exists; the closing rules. Returns None when the folder is not there.
    Fails open: a git, status-extract or playbook error only drops that section. It runs for a project only when core.project_owned("session_start") says so
    (the project is registered and its settings no longer name session-start.sh), and the global dispatcher must register SessionStart for it to be called
    at all (`shipm project hooks-global` keeps the template entry until it does). The skills-review line keeps the script's quirk: its backticked command ran
    as an empty command in bash, so "the lead runs  and proposes" has two spaces; tests/hooks_project_test.py compares it with the script."""
    pd = _dir(ctx)
    if pd is None:
        return None
    today = time.strftime("%Y-%m-%d", time.localtime(ctx.now))
    o = []                                       # output chunks (bytes)

    def say(s=""):
        o.append(s.encode("utf-8") + b"\n")

    def path(*p):
        return os.path.join(pd, *p)

    say("=== PROJECT BRIEF (auto, %s) — read before anything else ===" % today)
    status = path("docs", "STATUS.md")
    if os.path.isfile(status):
        say("--- docs/STATUS.md (brief; full file: docs/STATUS.md)")
        import subprocess
        ok = False
        try:
            p = subprocess.run(["python3", os.path.join(ctx.ws, "bin", "status-extract"), os.path.abspath(pd)], cwd=pd, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=GIT_TIMEOUT)
            o.append(p.stdout)
            ok = p.returncode == 0
        except (OSError, subprocess.SubprocessError):
            pass
        if not ok:                               # `|| sed -n 1,120p docs/STATUS.md`
            o.append(_head(status, 120))
    else:
        say("docs/STATUS.md missing: create it from the template before working.")
    ideas = path("docs", "FEATURE-IDEAS.md")
    if os.path.isfile(ideas):
        try:
            with open(ideas, "rb") as f:
                lines = _lines(f.read())
        except OSError:
            lines = []
        flag, op = False, []
        for l in lines:                          # awk '/^## Open/{f=1;next} /^## /{f=0} f && /^- \[ \]/'
            if l.startswith(b"## Open"):
                flag = True
                continue
            if l.startswith(b"## "):
                flag = False
            if flag and l.startswith(b"- [ ]"):
                op.append(l)
        if op:
            say()
            say('--- feature ideas: %d open idea(s) in docs/FEATURE-IDEAS.md (top 3; add: shipm idea add "idea"; review method: docs/idea-review-method.md in the Shipmiracle engine folder)' % len(op))
            o.append(b"".join(l + b"\n" for l in op[:3]))
    mem = path("docs", "memory", "MEMORY.md")
    if os.path.isfile(mem):
        say()
        say("--- docs/memory/MEMORY.md (project memory index)")
        o.append(_head(mem, 60))
    if os.path.isdir(path(".git")):
        say()
        say("--- last 10 commits")
        o.append(_git(["log", "--oneline", "-10"], pd))
        say()
        say("--- uncommitted changes")
        o.append(b"".join(l + b"\n" for l in _lines(_git(["status", "--short"], pd))[:30]))
        for marker, pre, post in (("PUSH-FAILED", b"WARNING: last auto-push failed (", b"); run: git push\n"),
                                  ("PUSH-BLOCKED", b"WARNING: last auto-push was blocked by the secret scan (", b"); fix the finding, then run: git push\n")):
            mp = path(".git", marker)
            if os.path.isfile(mp):
                try:
                    with open(mp, "rb") as f:
                        c = f.read().replace(b"\x00", b"").rstrip(b"\n")
                except OSError:
                    c = b""
                o.append(pre + c + post)
        b = _git(["branch", "--show-current"], pd).replace(b"\x00", b"").rstrip(b"\n")
        ahead = _git(["rev-list", "--count", "@{u}..HEAD"], pd).replace(b"\x00", b"").rstrip(b"\n") or b"0"
        o.append(b"branch: " + b + b", commits not on GitHub: " + ahead + b"\n")
    sk = path("docs", "SKILLS.md")
    skraw = None
    if os.path.isfile(sk):
        try:
            with open(sk, "rb") as f:
                skraw = f.read()
        except OSError:
            skraw = b""
    if skraw is None or re.search(rb"(?mi)^Skills review: *not done", skraw):
        say()
        say(">>> FIRST TASK THIS SESSION: the project skills review has not been done. Before other work, follow")
        say("    docs/SKILLS.md 'How the review works' (create it from templates/base/docs/SKILLS.md in the Shipmiracle engine folder if missing):")
        say("    the lead runs  and proposes the skills each role needs, asks the owner once, installs only what is approved.")   # the script's backticks ran an empty command
    elif int(ctx.now) - int(os.lstat(sk).st_mtime) >= 91 * 86400:                                                              # find -mtime +90
        say()
        say("Note: docs/SKILLS.md was last reviewed over 90 days ago; offer the owner a skills re-check.")
    else:
        say()
        say("--- project skills (docs/SKILLS.md)")
        rows = [l for l in _lines(skraw) if l.startswith(b"|")]
        o.append(b"".join(l + b"\n" for l in rows[2:20]))
    if os.path.isfile(path(".shipmiracle", "work.json")):    # change-request brief (P5b T6): only projects that have a playbook render work.json
        try:
            from shipmiracle.playbook import engine, gate, store
            rules = gate.stage_rules(pd)
            if rules:
                say()
                say("--- change requests (shipm cr show; the log in the state folder is the authority)")
                say(engine.brief(store.load(pd), rules))
        except Exception as e:                       # fail open: the brief never blocks a session start
            hio.log_err("session_start", e)
    say()
    say("Rules in force: update docs/STATUS.md (Updated: line with today's date) before stopping when source changed; one engine edits at a time; commit = push (auto).")
    say("To continue an earlier conversation: /resume (VS Code) or claude --continue (terminal).")
    return Result(plain_stdout=_dec(b"".join(o)))


def _head(path, n):
    """`sed -n 1,<n>p file` (stdout bytes; every line ends with a newline except possibly the last, as BSD sed prints it)."""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return b""
    parts = data.split(b"\n")
    if len(parts) > n:
        return b"\n".join(parts[:n]) + b"\n"
    return data


# ---------------------------------------------------------------- registration
def _register():
    for ev in ("UserPromptSubmit", "PreToolUse", "Stop", "Notification"):
        core.register(ev, "shipmiracle_state", None, shipmiracle_state, True)
    core.register("PreToolUse", "block_secrets", None, block_secrets, True)
    core.register("Stop", "stop_fast", None, stop_fast, True)
    core.register("Stop--slow", "stop_tests", None, stop_tests, True)
    core.register("PostToolUse", "save_plan", None, save_plan, True)
    core.register("PreModelSwitch", "model_switch", None, model_switch, True)
    core.register("SessionStart", "session_start", None, session_start, True)


_register()
