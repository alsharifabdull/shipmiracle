"""`shipm hooks apply NAME` (checklist D17): the owner installs a git hook that a chat PROPOSED.

A chat cannot write a project's git hooks (gate rule D14) but may write the proposal text to docs/proposed-hooks/NAME.txt. This command is the owner's one step from proposal to hook:
  1  locks 1 and 2 of the owner proof (owner.gate: no CLAUDECODE, the process ancestry has no claude and has a terminal host) BEFORE anything is read or shown
  2  NAME must be one of the client-side git hook names (a fixed list, lower case, nothing else: no path, no dot, no unicode)
  3  the proposal is read ONCE through a chain of folders opened without following links (root/docs/proposed-hooks/NAME.txt): a regular file of ours, one link, at most MAX_BYTES, UTF-8 text without
     control characters, a first line that is a `#!` of sh, bash or python3 only, and none of the DENY patterns (network tools, decoders, eval, secret and start-up files, persistence)
  4  the hooks folder is core.hooksPath of the project (relative, inside the project, never .git) or, when that is unset, an existing .githooks; opened the same way; never group/other-writable
  5  a readable diff against the current hook (or "NEW") plus the sha256 of the proposal and the WARN lines are printed on the terminal /dev/tty
  6  the owner types the word `apply` on /dev/tty (stdin must be a terminal, the type-ahead is flushed, an argument or an environment variable can never answer it); then ONE presence check per `owner.presence`
  7  the proposal is read again: its hash must still be the one shown, and the current hook must still be the one diffed (otherwise nothing is written)
  8  backup of the current hook (state folder, 0600, O_EXCL), a log line (state folder), then temp file + rename in the hooks folder (mode 0755): an interrupted write leaves the old hook intact.
Never touched: any other path. The bytes written are the bytes shown (held in memory from step 3 to step 8).
Test seams (module attributes only): _TTY_PATH, _stdin_is_tty, _now, _chain_hook (called at named points)."""
from __future__ import annotations

import difflib
import errno
import hashlib
import os
import re
import select
import shutil
import stat
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

from . import ShipmiracleError, SafetyError, UsageError, NotFound, owner, paths, state, events

MAX_BYTES = 32768
MAX_OLD = 1 << 20
TYPED_WORD = "apply"
TYPE_WAIT_S = 120
HOOK_NAMES = ("applypatch-msg", "pre-applypatch", "post-applypatch", "pre-commit", "pre-merge-commit", "prepare-commit-msg", "commit-msg", "post-commit", "pre-rebase",
              "post-checkout", "post-merge", "pre-push", "post-rewrite", "pre-auto-gc", "push-to-checkout", "reference-transaction", "sendemail-validate")
NAME_RE = re.compile(r"[a-z][a-z-]{2,30}")
SHEBANG_RE = re.compile(r"#!(?:/usr/bin/env |/usr/bin/|/bin/)(?:sh|bash|python3)(?: -[eu]{1,2})?")
PROPOSAL_DIR = ("docs", "proposed-hooks")

# Hard refusals: clear patterns a proposal must not contain. This filter is a SPEED BUMP, not a boundary: it cannot constrain python hooks or hooks that run project scripts; the control is the owner reading the diff.
# The owner can still put such a hook in place by hand (docs/owner-steps/edit-githooks.md). Lines that only print a message (echo / printf without a pipe, redirect or substitution) and whole-line comments are not scanned.
_TOOLS = r"(?:curl|wget|nc|ncat|netcat|socat|telnet|ssh|scp|sftp|ftp|rsync|tftp|nslookup|dig)"
_PRIV = r"(?:launchctl|crontab|osascript|systemctl|sudo|doas|chown)"
_CMDPOS = (r"(?:^|[;&|({`]|\$\(|(?<![\w-])(?:then|do|else|elif|if|while|until)(?![\w-])|!)[ \t]*"
           r"(?:(?:command[ \t]+(?!-[vV])|(?:builtin|env|time|nohup|xargs|exec|nice|setsid|sudo|doas|stdbuf|timeout|watch|ionice|caffeinate)[ \t]+)(?:-\S+[ \t]+|\d+[ \t]+)*)*"
           r"(?:[A-Za-z_]\w*=\S*[ \t]+)*(?:/\S*/)?")
_BROAD = re.compile(r"\$\(|`|(?<![\w-])-[A-Za-z]*[ce](?![\w-])|(?<![\w-])(?:xargs|eval|exec|source)(?![\w-])|-exec")
DENY_CMD = [(re.compile(_CMDPOS + _TOOLS + r"(?![\w-])", re.I), "a network tool"), (re.compile(_CMDPOS + _PRIV + r"(?![\w-])", re.I), "persistence or privilege")]
DENY_BROAD = [(re.compile(r"(?<![\w-])" + _TOOLS + r"(?![\w-])", re.I), "a network tool"), (re.compile(r"(?<![\w-])" + _PRIV + r"(?![\w-])", re.I), "persistence or privilege")]
DENY = [(re.compile(p, re.I), why) for p, why in (
    (r"/dev/(?:tcp|udp)/", "a raw network socket"),
    (r"(?:^|[;\s'\"(])(?:import|from)\s+(?:socket|urllib|requests|ftplib|smtplib|telnetlib|ctypes|marshal|pickle|http\.client|http\.server|xmlrpc)(?![\w])|(?<![\w.-])(?:socket|urllib|requests|ftplib|smtplib|telnetlib|ctypes|marshal|pickle)\.\w+|__import__", "network or code-loading python modules"),
    (r"(?<![\w-])(?:base64|b64decode|xxd\s+-r|openssl\s+enc)(?![\w-])", "a decoder (hidden code)"),
    (r"(?<![\w.-])eval(?![\w-])|(?<![\w.-])exec\s*\(", "eval / exec"),
    (r"\|\s*(?:sudo\s+)?(?:/\S*/)?(?:sh|bash|zsh|dash|python3?(?!\s+-m\s+(?:json\.tool|calendar|tokenize)(?![\w.-]))|perl|ruby|node)(?![\w-])", "a pipe into an interpreter"),
    (r"(?<![\w])\.(?:env(?:rc)?(?!\.(?:example|sample|template|dist)(?![\w-]))|ssh|aws|gnupg|netrc|npmrc|pypirc|git-credentials|kube|docker)(?![\w-])", "a secret or credential file"),
    (r"(?<![\w-])(?:security\s+(?:find|dump|add|delete)-|keychain|\.pem|id_rsa|id_ed25519)", "the keychain or a private key"),
    (r"LaunchAgents|LaunchDaemons|(?<![\w-])at\s+now|setuid", "persistence or privilege"),
    (r"(?:\.zshrc|\.zprofile|\.zshenv|\.bashrc|\.bash_profile|\.profile|\.gitconfig)(?![\w-])", "a shell start-up file"),
    (r"git\s+config\s+(?!--get|--list|-l(?![\w-]))(?:--\S+\s+)*(?:core\.hookspath|core\.fsmonitor|core\.sshcommand|alias\.)", "a git setting that runs code later"),
    (r"\.git/config", "the git config"),
    (r"(?<![\w-])chmod\s+(?:-\w+\s+)*(?:[0-7]?[2467][0-7]{3}|[ugoa]*[+=][rwxXt]*s)", "a setuid / setgid permission change"),
    (r"(?<![\w-])rm\s+-[a-z]*r[a-z]*f?\s+(?:/|~|\$HOME|\.\.)", "a recursive delete outside the project"),
    (r"(?<![\w-])install\s+(?:-\w+\s+)*-m\s*=?[0-7]*[2467][0-7]{3}(?![\w-])", "a setuid / setgid install"),
    (r"[A-Za-z]['\"]{2}[A-Za-z]|[A-Za-z]['\"]\$[A-Za-z]", "a word split by quotes (a way to hide a command name)"),
    (r"(?<![\w$\"'])[A-Za-z]+['\"][A-Za-z]{1,4}['\"][A-Za-z]+(?![\w])", "a word split by quotes (a way to hide a command name)"),
    (r"(?m)(?:^|[;&|(]|\b(?:then|do|else)\b)[ \t]*\$\{?[A-Za-z_]\w*\}?(?:[ \t]|$)", "a command name built from a variable"),
)]
# Shown to the owner, not refused: these are normal in this workspace's hooks but deserve a second look.
WARN = [(re.compile(p, re.I), why) for p, why in (
    (r"git\s+push", "pushes to a remote (the commits leave this Mac)"),
    (r"git\s+(?:-\S+\s+)*push\s+(?:-\S+\s+)*\S*(?:://|@|:)\S*", "pushes to an address written in the hook"),
    (r"(?<![\w-])chmod(?![\w-])", "changes file permissions"),
    (r"(?<![\w.-])exec[ \t]+\S", "replaces the hook by another program (exec)"),
    (r"\.git/hooks|\.githooks|\.husky", "mentions another hooks location"),
    (r"(?<![&|])&\s*(?:$|[);])|(?<![\w-])(?:nohup|disown|setsid)(?![\w-])", "starts a background job"),
    (r"(?<![\w-])rm\s+-", "deletes files"),
    (r"\$HOME|~/", "reads or writes under your home folder"),
    (r"(?<![\w-])(?:bash|sh|zsh|dash|python3?|perl|ruby|node)\s+(?:-\w+\s+)*-\w*[ce]\b", "runs a command given as text (interpreter -c / -e)"),
    (r"(?m)(?:^|[;&|(]|\b(?:then|do|else)\b)[ \t]*(?:source|\.)[ \t]+\S", "loads another file into itself (source)"),
    (r"\$\(|`", "runs a command inside a command ($( ) or backticks)"),
    (r"(?<![\w-])(?:pip3?|pipx|npm|npx|yarn|pnpm|bun|brew|gem|cargo|apt|apt-get|uv)[ \t]+\w", "runs a package manager (it can download and run code)"),
    (r"(?<![\w-])git\b[^\n]*?(?<![\w-])(?:ls-remote|fetch|clone|pull|difftool|submodule|remote[ \t]+update)(?![\w-])|(?<![\w-])git\b[^\n]*--exec\b|(?<![\w-])rebase[ \t]+-x", "uses a git command that can contact a remote or run a program"),
    (r"(?<![\w-])(?:open|ping|host|whois|traceroute|dns-sd|xargs)[ \t]+\S|\bfind\b[^\n]*-exec", "starts another program or contacts a host"),
    (r"GIT_CONFIG_(?:COUNT|KEY|VALUE|GLOBAL|SYSTEM|PARAMETERS)|GIT_(?:SSH|ASKPASS|EXTERNAL_DIFF|EDITOR|PAGER)", "sets a git environment variable that runs a program"),
    (r"(?<![\w-])install[ \t]+-", "installs a file with chosen permissions"),
    (r"(?<=[A-Za-z])\\(?=[A-Za-z])", "has a backslash inside a word (can hide a command name)"),
)]

_TTY_PATH = "/dev/tty"
_chain_hook = None                      # tests: callable(point) run at "after_typed", "before_rename"


def _stdin_is_tty() -> bool:
    try:
        return os.isatty(0)
    except OSError:
        return False


def _now() -> float:
    return time.time()


def _point(name, *a) -> None:
    if _chain_hook is not None:
        _chain_hook(name, *a)


class Refused(SafetyError):
    """A refusal with one plain sentence (exit 4)."""


# ---------------------------------------------------------------- validation
def validate_name(name) -> str:
    if not isinstance(name, str) or not name or len(name) > 40 or "\0" in name or not name.isascii() or not NAME_RE.fullmatch(name):
        raise UsageError("hook name must be one of: %s" % ", ".join(HOOK_NAMES))
    if name not in HOOK_NAMES:
        raise UsageError("hook name must be one of: %s" % ", ".join(HOOK_NAMES))
    return name


_HEREDOC = re.compile(r"<<(-?)[ \t]*(['\"]?)([A-Za-z_]\w*)\2")


def _quote_state(line: str, inq):
    """The open quote (' or " or None) at the end of one shell line; an unquoted # after a space starts a comment."""
    i, n = 0, len(line)
    while i < n:
        c = line[i]
        if inq is None:
            if c == "\\":
                i += 1
            elif c in "'\"":
                inq = c
            elif c == "#" and (i == 0 or line[i - 1] in " \t;"):
                break
        elif inq == "'":
            if c == "'":
                inq = None
        else:
            if c == "\\":
                i += 1
            elif c == '"':
                inq = None
        i += 1
    return inq


def _code_lines(text: str, mark: bool = False) -> str:
    """The text with whole-line comments blanked. NOT blanked: lines inside a here-document (data that may be written out and run), a line that follows a backslash continuation or sits inside an open quote
    (there a # is not a comment)."""
    out, tag, dash, cont, inq = [], None, False, False, None
    for i, l in enumerate(text.split("\n")):
        if tag is not None:
            out.append(("\x01" + l) if mark else l)
            if (l.strip() if dash else l) == tag or l.strip() == tag:
                tag = None
            continue
        comment = i > 0 and not cont and inq is None and l.lstrip().startswith("#")
        in_string = i > 0 and not cont and inq is not None and l.lstrip().startswith("#")          # text inside an open quote: data, scanned like a here-document
        out.append("" if comment else (("\x01" + l) if (mark and in_string) else l))
        if comment:
            cont = False
            continue
        if i:
            m = _HEREDOC.search(l.replace("<<<", "   "))
            if m:
                tag, dash = m.group(3), bool(m.group(1))
        inq = _quote_state(l, inq)
        cont = (len(l) - len(l.rstrip("\\"))) % 2 == 1
    return "\n".join(out)


_IND_START = r"(?:^|[;&|(]|\b(?:then|do|else)\b)[ \t]*"
_IND = [
    re.compile(_IND_START + r"((?:\.{1,2}/|[\w.-]+/)[^\s;&|)\"']+)"),
    re.compile(r"(?<![\w-])(?:bash|sh|zsh|dash|python3?|node|ruby|perl)[ \t]+(?:-[\w-]+[ \t]+)*(?![-$\"'/])([\w.][^\s;&|)\"']*)"),
    re.compile(_IND_START + r"(?:source|\.)[ \t]+([^\s;&|)\"']+)"),
    re.compile(r"(?<![\w-])((?:npm|npx|yarn|pnpm|bun)[ \t]+(?:run|exec|test|x|start)\b)"),
    re.compile(r"(?<![\w-])(make|pytest|tox|nox|gradle|mvn|rake|just|cargo[ \t]+(?:test|run)|go[ \t]+(?:test|run)|python3?[ \t]+-m[ \t]+\S+)(?![\w-])"),
]


def indirections(body: str):
    """[(sentence, token)]: places where an approved hook runs something that lives in the project and that a chat may rewrite later."""
    found = []
    for l in body.split("\n")[1:]:
        for rx in _IND:
            for m in rx.finditer(l):
                tok = m.group(1)[:80]
                msg = "runs a project file that a chat can change later: %s" % tok
                if (msg, tok) not in found:
                    found.append((msg, tok))
    return found


def pin_samples(root: str, body: str, limit=3):
    """Sample lines the owner may add to the hook to pin the project files it runs (sha256 of what is there now)."""
    out = []
    for _msg, tok in indirections(body):
        if len(out) >= limit or tok.startswith(("/", "$", "~")):
            continue
        try:
            p = os.path.realpath(os.path.join(root, tok))
            if not (p.startswith(root.rstrip("/") + "/") and os.path.isfile(p) and os.path.getsize(p) <= MAX_OLD):
                continue
            with open(p, "rb") as f:
                out.append("echo '%s  %s' | shasum -a 256 -c - >/dev/null || exit 1" % (_sha(f.read()), tok))
        except (OSError, ValueError):
            continue
    return out


def _clean(s, n=60) -> str:
    """One printable line: control, invisible and newline characters become ?, so a folder name cannot forge a log line or a prompt."""
    return "".join(c if (c.isprintable() and c not in "\n\r\t") else "?" for c in str(s))[:n]


def change_summary(old, new_text: str):
    """(added, removed, first new command) from the real bytes: the OS dialog shows this, the terminal text cannot fake it."""
    old_lines = old.decode("utf-8", "replace").splitlines() if old is not None else []
    add = rem = 0
    first = ""
    for l in difflib.unified_diff(old_lines, new_text.splitlines(), lineterm="", n=0):
        if l.startswith(("+++", "---", "@@")):
            continue
        if l.startswith("+"):
            add += 1
            t = l[1:].strip()
            if not first and t and not t.startswith("#"):
                first = _clean(t, 40)
        elif l.startswith("-"):
            rem += 1
    return add, rem, first


def _message_line(line: str) -> bool:
    """A line that only prints text: echo / printf with no pipe, redirect to a file, substitution or second command."""
    if not re.match(r"[ \t]*(?:echo|printf)(?![\w-])", line):
        return False
    l = re.sub(r"[12]?>&[12]", "", line)
    return not re.search(r"[|;&<>`]|\$\(", l)


def check_content(data: bytes):
    """(text, warnings). Raises Refused with the reason for text that is not an acceptable proposal."""
    if not data:
        raise Refused("the proposal is empty")
    if len(data) > MAX_BYTES:
        raise Refused("the proposal is larger than %d KB" % (MAX_BYTES // 1024))
    if b"\0" in data:
        raise Refused("the proposal is not plain text (it holds a NUL byte)")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise Refused("the proposal is not valid UTF-8 text")
    for ch in text:
        o = ord(ch)
        if (o < 32 and ch not in "\n\t") or o == 127 or 0x80 <= o < 0xA0 or ch in "‪‫‬‭‮⁦⁧⁨⁩​‌‍﻿":
            raise Refused("the proposal holds a control or invisible character (U+%04X)" % o)
    first = text.split("\n", 1)[0]
    if not SHEBANG_RE.fullmatch(first):
        raise Refused("the first line must be a shebang for sh, bash or python3 (like #!/usr/bin/env bash); found %r" % first[:60])
    body = _code_lines(text)
    for line in _code_lines(text, True).replace("\\\n", "").split("\n"):             # a backslash-newline joins the words, exactly as the shell does
        hd = line.startswith("\x01")                  # a here-document line is data that may be written out and run: scanned with the broad word match
        line = line.lstrip("\x01")
        if _message_line(line) and not hd:
            continue
        rxs = DENY + DENY_CMD + (DENY_BROAD if (hd or _BROAD.search(line)) else [])
        for rx, why in rxs:
            m = rx.search(line)
            if m:
                raise Refused("the proposal contains %s (%r): put it in place by hand if you really want it (docs/owner-steps/edit-githooks.md)" % (why, m.group(0).strip()[:30]))
    warns = []
    for rx, why in WARN:
        if rx.search(body):
            warns.append(why)
    if any(ord(c) > 127 and c.isalpha() for c in text):
        warns.append("contains non-ASCII letters (they can look like ASCII ones and hide a command)")
    for msg, _tok in indirections(body):
        if msg not in warns:
            warns.append(msg)
    return text, warns


# ---------------------------------------------------------------- safe file access
def _open_dir(dirfd, part):
    try:
        fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=dirfd)
    except OSError as e:
        if e.errno in (errno.ELOOP, errno.ENOTDIR):
            raise Refused("%s is a link or not a folder: the command does not follow links" % part)
        if e.errno == errno.ENOENT:
            raise NotFound("no folder %s" % part)
        raise Refused("cannot open folder %s (%s)" % (part, e.strerror))
    st = os.fstat(fd)
    if st.st_uid != os.geteuid():
        os.close(fd)
        raise Refused("folder %s is owned by another user" % part)
    return fd


def _open_chain(root_fd, parts, must_exist=True):
    fd = os.dup(root_fd)
    try:
        for p in parts:
            nfd = _open_dir(fd, p)
            os.close(fd)
            fd = nfd
        return fd
    except BaseException:
        os.close(fd)
        raise


def _read_regular(dirfd, fname, limit, what, single_link=False):
    """(bytes, st) of a regular file of ours opened without following a link, or (None, None) when absent."""
    try:
        fd = os.open(fname, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=dirfd)
    except FileNotFoundError:
        return None, None
    except OSError as e:
        if e.errno == errno.ELOOP:
            raise Refused("%s is a symbolic link: the command does not follow links" % what)
        raise Refused("cannot open %s (%s)" % (what, e.strerror))
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise Refused("%s is not a regular file" % what)
        if st.st_uid != os.geteuid():
            raise Refused("%s belongs to another user" % what)
        if single_link and st.st_nlink != 1:
            raise Refused("%s has more than one hard link (it may be the same file as something else)" % what)
        if st.st_size > limit:
            raise Refused("%s is larger than %d KB" % (what, limit // 1024))
        chunks, total = [], 0
        while True:
            c = os.read(fd, 1 << 16)
            if not c:
                break
            total += len(c)
            if total > limit:
                raise Refused("%s is larger than %d KB" % (what, limit // 1024))
            chunks.append(c)
        return b"".join(chunks), st
    finally:
        os.close(fd)


def project_root(cwd=None) -> str:
    cur = os.path.realpath(str(cwd or os.getcwd()))
    while True:
        if os.path.lexists(os.path.join(cur, ".git")):
            return cur
        par = os.path.dirname(cur)
        if par == cur:
            raise NotFound("this folder is not inside a git project (no .git found)")
        cur = par


def _git_path(root: str) -> str:
    """The git program: a fixed system location, else PATH with relative entries and entries inside the project removed (a project file named git cannot run)."""
    for c in ("/usr/bin/git", "/opt/homebrew/bin/git", "/usr/local/bin/git"):
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    rr = os.path.realpath(root)
    keep = [d for d in os.environ.get("PATH", "").split(os.pathsep) if d and os.path.isabs(d) and not (os.path.realpath(d) + "/").startswith(rr.rstrip("/") + "/")]
    g = shutil.which("git", path=os.pathsep.join(keep))
    if not g:
        raise Refused("cannot find git outside the project")
    return g


def hooks_folder(root: str):
    """The relative path parts of the hooks folder: core.hooksPath (read from the project's own git config) or an existing .githooks. Never .git."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0")
    try:
        r = subprocess.run([_git_path(root), "-C", root, "config", "--local", "--get", "core.hooksPath"], capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL, timeout=15)
    except (OSError, subprocess.SubprocessError):
        raise Refused("cannot read the project's git settings (is git installed?)")
    if r.returncode == 0:
        val = r.stdout.strip()
    elif r.returncode == 1:
        val = ""
    else:
        raise Refused("cannot read core.hooksPath of this project (git said exit %d)" % r.returncode)
    if not val:
        val = ".githooks"
        if not os.path.isdir(os.path.join(root, val)):
            raise NotFound("this project has no hooks folder: run `git config core.hooksPath .githooks` and create .githooks yourself, then run this again")
    if val.startswith(("/", "~")) or "\0" in val or "\\" in val:
        raise Refused("core.hooksPath (%s) must be a folder inside the project, written relative" % val[:60])
    parts = [p for p in val.split("/") if p not in ("", ".")]
    if not parts or any(unicodedata.normalize("NFKC", p).casefold().rstrip(". ") in ("..", ".git", "") for p in parts):
        raise Refused("core.hooksPath (%s) must stay inside the project and is never .git" % val[:60])
    return parts


# ---------------------------------------------------------------- terminal
def _tty_open():
    if not _stdin_is_tty():
        raise Refused("This needs you at a terminal: run `shipm hooks apply NAME` in Terminal or VS Code (standard input is not a terminal).")
    try:
        return os.open(_TTY_PATH, os.O_RDWR | os.O_NOCTTY | os.O_CLOEXEC)
    except OSError:
        raise Refused("This needs you at a terminal: there is no terminal (/dev/tty) to ask you on; run `shipm hooks apply NAME` in Terminal or VS Code.")


def _say(fd, text):
    b = text.encode("utf-8", "replace")
    while b:
        b = b[os.write(fd, b):]


def _ask_word(fd, prompt, timeout=TYPE_WAIT_S) -> str:
    """One typed line on the terminal. Type-ahead is dropped first. '' on EOF or timeout."""
    import termios
    try:
        termios.tcflush(fd, termios.TCIFLUSH)
    except termios.error:
        raise Refused("this terminal cannot be read safely; use Terminal or VS Code")
    _say(fd, prompt)
    buf = b""
    end = time.time() + timeout
    try:
        while b"\n" not in buf and time.time() < end:
            r, _w, _x = select.select([fd], [], [], max(0.1, min(1.0, end - time.time())))
            if r:
                chunk = os.read(fd, 256)
                if not chunk:
                    break
                buf += chunk
                if b"\n" not in buf:                 # a terminal hands over a line without its newline only when the owner pressed Ctrl-D: that is a cancel, at once
                    buf = b""
                    break
            if len(buf) > 4096:
                break
    except KeyboardInterrupt:
        _say(fd, "\n")
        raise Refused("Cancelled: nothing was installed.")
    _say(fd, "\n")
    if b"\n" not in buf:
        return ""
    return buf.split(b"\n", 1)[0].decode("utf-8", "replace").strip("\r ")


# ---------------------------------------------------------------- the diff
def render_diff(old: "bytes | None", new_text: str, name: str) -> str:
    if old is None:
        lines = new_text.splitlines()
        return "NEW hook %s (no current file). Full text:\n%s" % (name, "\n".join("+ " + l for l in lines))
    old_text = old.decode("utf-8", "replace")
    d = list(difflib.unified_diff(old_text.splitlines(), new_text.splitlines(), "current " + name, "proposed " + name, lineterm="", n=3))
    return "\n".join(d)


# ---------------------------------------------------------------- writing
def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _backup(old: bytes, name: str, root: str) -> str:
    d = state.ensure_dir(state.ensure_root() / "hook-backups")
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(_now()))
    base = "%s-%s-%s" % (stamp, name, _sha(old)[:8])
    for i in range(100):
        p = d / (base + ("" if i == 0 else "-%d" % i) + ".bak")
        try:
            fd = os.open(str(p), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        except FileExistsError:
            continue
        try:
            b = old
            while b:
                b = b[os.write(fd, b):]
            os.fsync(fd)
        finally:
            os.close(fd)
        return str(p)
    raise Refused("cannot find a free backup name")


def _restore(hfd, name, old):
    """Put the previous hook back (or remove a hook that did not exist before)."""
    if old is None:
        try:
            os.unlink(name, dir_fd=hfd)
        except OSError:
            pass
    else:
        write_hook(hfd, name, old, point=False)


def _log(line: str) -> None:
    d = state.ensure_dir(state.ensure_root())
    fd = os.open(str(d / "hooks-apply.log"), os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        os.write(fd, (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(_now())) + " " + line + "\n").encode("utf-8", "replace"))
        os.fsync(fd)
    finally:
        os.close(fd)


def write_hook(hooks_fd, name: str, data: bytes, point=True) -> None:
    """Temp file in the hooks folder (mode 0755, fsync) then rename over the hook. On any failure the temp file is removed and the old hook is untouched."""
    tmp = ".%s.%s.tmp" % (name, os.urandom(6).hex())
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o700, dir_fd=hooks_fd)
    except OSError as e:
        raise Refused("cannot write in the hooks folder (%s): nothing was changed" % e.strerror)
    try:
        try:
            os.fchmod(fd, 0o755)
            b = data
            while b:
                b = b[os.write(fd, b):]
            os.fsync(fd)
        finally:
            os.close(fd)
        if point:
            _point("before_rename", tmp)
        os.rename(tmp, name, src_dir_fd=hooks_fd, dst_dir_fd=hooks_fd)
    except BaseException:
        try:
            os.unlink(tmp, dir_fd=hooks_fd)
        except OSError:
            pass
        raise
    try:
        os.fsync(hooks_fd)
    except OSError:
        pass


# ---------------------------------------------------------------- the command
def run(name, cwd=None, out=None) -> int:
    say = out or (lambda s: sys.stdout.write(s + "\n"))
    # lock 1 and 2 first: before the name is even looked at, so a chat learns nothing
    hint = "shipm hooks apply %s" % (name if isinstance(name, str) and NAME_RE.fullmatch(name or "") else "NAME")
    owner.gate("hooks-apply", hint)
    name = validate_name(name)
    root = project_root(cwd)
    if (not owner.proof_required() and not paths._under_temp(root)) or (os.environ.get("SHIPMIRACLE_TEST") == "1" and not paths.sandboxed()):
        raise Refused("a test run may only install into a temp project: this one is outside the test sandbox, nothing was changed")
    try:
        setting = owner.presence_setting()
    except Exception:
        setting = "auto"
    sel = owner.select(min_tier="basic" if setting == "basic-ok" else "medium")      # None in a sandbox; OwnerRefused when no provider is allowed; basic only when the owner set basic-ok
    basic = sel is not None and getattr(sel, "tier", "") == "basic"
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    pname = _clean(os.path.basename(root))
    try:
        pdir = _open_chain(root_fd, PROPOSAL_DIR)
        try:
            raw, _pst = _read_regular(pdir, name + ".txt", MAX_BYTES, "docs/proposed-hooks/%s.txt" % name, single_link=True)
        finally:
            os.close(pdir)
        if raw is None:
            raise NotFound("no proposal docs/proposed-hooks/%s.txt in this project" % name)
        text, warns = check_content(raw)
        digest = _sha(raw)
        parts = hooks_folder(root)
        hfd = _open_chain(root_fd, parts)
        try:
            hst = os.fstat(hfd)
            if hst.st_mode & 0o022:
                raise Refused("the hooks folder %s is writable by group or others: fix that first (chmod go-w)" % "/".join(parts))
            old, _ost = _read_regular(hfd, name, MAX_OLD, "the current hook %s" % name)
            if old is not None and _sha(old) == digest:
                say("%s is already exactly this proposal: nothing to do." % name)
                return 0
            add, rem, first = change_summary(old, text)
            summary = "+%d -%d lines%s" % (add, rem, "; first new command: " + first if first else "")
            tfd = _tty_open()
            try:
                shown = "\n  Hook %s for %s\n  Folder: %s\n  Proposal sha256: %s (%d bytes)\n" % (name, pname, "/".join(parts), digest, len(raw))
                for w in warns:
                    shown += "  ATTENTION: this hook %s\n" % w
                pins = pin_samples(root, _code_lines(text))
                if pins:
                    shown += "  To pin the project files it runs (the hook then stops if a chat changed them), add lines like:\n" + "".join("    %s\n" % x for x in pins)
                shown += "\n" + render_diff(old, text, name) + "\n\n  Summary (from the real file): %s\n  The filter only warns about patterns; you must read the diff above.\n\n" % summary
                _say(tfd, shown)
                if not basic:
                    word = _ask_word(tfd, "  Read it all. Type the word %s to install it (anything else cancels): " % TYPED_WORD)
                    if word != TYPED_WORD:
                        raise Refused("Nothing was changed (you did not type %s)." % TYPED_WORD)
            finally:
                os.close(tfd)
            _point("after_typed")
            reason = "install git hook %s in %s: %s." % (name, pname, summary)
            try:
                owner.touch("hooks-apply", ("Read it all, then type this code to install " + reason) if basic else ("Shipmiracle: " + reason + " Cancel if you did not just type this yourself."), sel=sel)
            except KeyboardInterrupt:
                raise Refused("Cancelled: nothing was installed.")
            # the same bytes as shown, or nothing: both files are read again
            pdir = _open_chain(root_fd, PROPOSAL_DIR)
            try:
                raw2, _ = _read_regular(pdir, name + ".txt", MAX_BYTES, "docs/proposed-hooks/%s.txt" % name, single_link=True)
            finally:
                os.close(pdir)
            if raw2 is None or _sha(raw2) != digest:
                raise Refused("The proposal changed after it was shown. Nothing was changed; run the command again and read it again.")
            old2, _ = _read_regular(hfd, name, MAX_OLD, "the current hook %s" % name)
            if (old2 is None) != (old is None) or (old2 is not None and _sha(old2) != _sha(old)):
                raise Refused("The current hook changed after it was shown. Nothing was changed; run the command again.")
            bpath = _backup(old, name, root) if old is not None else ""
            _log("begin hook=%s project=%s old=%s new=%s backup=%s" % (name, pname, _sha(old)[:16] if old is not None else "none", digest[:16], bpath or "none"))
            try:
                write_hook(hfd, name, raw)
                got, _ = _read_regular(hfd, name, MAX_OLD, "the installed hook %s" % name)
            except BaseException:
                try:
                    _log("failed hook=%s new=%s" % (name, digest[:16]))
                except Exception:
                    pass
                raise
            if got is None or _sha(got) != digest:
                try:
                    _restore(hfd, name, old)
                finally:
                    try:
                        _log("MISMATCH hook=%s new=%s restored=%s" % (name, digest[:16], "yes" if old is not None else "removed"))
                    except Exception:
                        pass
                raise Refused("WRONG FILE: the hook on disk is not the text you read (it was swapped while being written). The previous hook was put back%s. Nothing from the proposal is installed." % (" (backup: %s)" % bpath if bpath else "; the new file was removed"))
            _point("after_write")
            try:
                lfd = _open_chain(root_fd, parts)
                try:
                    live, _ = _read_regular(lfd, name, MAX_OLD, "the installed hook %s" % name)
                    a_, b_ = os.fstat(lfd), os.fstat(hfd)
                    same = (a_.st_ino, a_.st_dev) == (b_.st_ino, b_.st_dev)
                finally:
                    os.close(lfd)
            except ShipmiracleError:
                live, same = None, False
            if not same or live is None or _sha(live) != digest:
                try:
                    _log("WRONGPLACE hook=%s new=%s" % (name, digest[:16]))
                except Exception:
                    pass
                raise Refused("WRONG PLACE: the hooks folder %s was replaced or moved while the hook was written, so the live path does NOT hold the hook you read. Nothing is installed there%s. Check the folder by hand." % ("/".join(parts), " (the previous hook is saved at %s)" % bpath if bpath else ""))
            try:
                _log("done hook=%s new=%s" % (name, digest[:16]))
            except Exception:
                pass
            try:
                events.emit("hooks.apply", {"hook": name, "new": digest[:16], "old": _sha(old)[:16] if old is not None else "none"}, src="shipmiracle")
            except Exception:
                pass
        finally:
            os.close(hfd)
    finally:
        os.close(root_fd)
    say("installed %s (%s, mode 0755, sha256 %s)" % (name, "/".join(parts) + "/" + name, digest[:16]))
    if bpath:
        say("the old hook is saved at %s" % bpath)
    else:
        say("it was a new hook (nothing to back up)")
    say("You can delete docs/proposed-hooks/%s.txt now. Git runs hooks only when core.hooksPath points at that folder: `git config core.hooksPath` should print %s." % (name, "/".join(parts)))
    return 0
