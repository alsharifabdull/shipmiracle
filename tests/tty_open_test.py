#!/usr/bin/env python3
"""The controlling-terminal prompt (shipmiracle/terminal.py) and its four callers.
Bug (29 Oct 2026, macOS 27, system Python 3.9.6): open("/dev/tty", "r+") raises io.UnsupportedOperation ("File or stream is not seekable") because text mode
r+ wants a seekable stream, so bin/shipm-presence-build, the playbook interview (typed answers) and the playbook cli confirmation all said "needs you at a terminal"
inside a real terminal. The fix opens the device once with os.open(O_RDWR | O_NOCTTY) and wraps one write and one read file object around it.
Covers: the helper against a REAL pty slave (the answer is typed AFTER the prompt appears), type-ahead dropped (a pre-typed "yes" never answers), piped stdin ignored, Ctrl-D (also after
partial text) = cancel, missing device, the three playbook callers through the same pty, the Touch ID build script's gate (loaded as a module; a build is never executed) for typed yes / other
word / no terminal, `--check` exit codes unchanged, and a source scan that nothing under bin/ shipmiracle/ hooks/ tools/ templates/ .githooks/ opens the tty in a +-mode again.
Run: python3 tests/tty_open_test.py   (Python 3.9, macOS and Linux)"""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import shipmiracle_isolation; shipmiracle_isolation.apply_to_environ()   # test isolation
import hashlib, importlib.machinery, importlib.util, io, os, pathlib, pty, re, select, shutil, subprocess, sys, tempfile, threading, time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
fails = 0


def check(name, ok, info=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(info)[:600]))
    fails += 0 if ok else 1


from shipmiracle import terminal  # noqa: E402
from shipmiracle.playbook import cli as pcli, interview  # noqa: E402

os.environ.pop("CLAUDECODE", None)
os.environ.pop("SHIPMIRACLE_INTERVIEW_INPUT", None)


class Pty:
    """A real pseudo-terminal. .path is the slave device (what /dev/tty is for a person); .typed(text) types at once (type-ahead);
    .answers(text) types `text` only after the first output (the prompt) reached the screen; .shown() is everything the screen got."""
    def __init__(self):
        self.master, self.slave = pty.openpty()           # the slave fd stays open so the device lives for the whole test
        self.path = os.ttyname(self.slave)
        self.seen = ""

    def typed(self, text):
        os.write(self.master, text.encode())
        self.seen += self._drain(0.25)                   # the terminal echoes type-ahead at once; take that echo off the screen now so answers() waits for the PROMPT

    def _drain(self, wait):
        out, end = "", time.time() + wait
        while time.time() < end:
            r, _w, _x = select.select([self.master], [], [], 0.05)
            if not r:
                continue
            try:
                chunk = os.read(self.master, 4096)
            except OSError:
                break
            out += chunk.decode("utf-8", "replace")
        return out

    def answers(self, text, wait=10):
        def run():
            end = time.time() + wait
            while time.time() < end:
                r, _w, _x = select.select([self.master], [], [], 0.05)
                if not r:
                    continue
                try:
                    chunk = os.read(self.master, 4096)
                except OSError:
                    return
                self.seen += chunk.decode("utf-8", "replace")
                time.sleep(0.05)
                os.write(self.master, text.encode())
                return
        t = threading.Thread(target=run, daemon=True)
        t.start()
        return t

    def shown(self, wait=0.3):
        out, end = self.seen, time.time() + wait
        while time.time() < end:
            r, _w, _x = select.select([self.master], [], [], 0.05)
            if not r:
                continue
            try:
                chunk = os.read(self.master, 4096)
            except OSError:
                break
            if not chunk:
                break
            out += chunk.decode("utf-8", "replace")
        return out

    def close(self):
        for fd in (self.master, self.slave):
            try:
                os.close(fd)
            except OSError:
                pass


def with_answer(p, text, fn, *a, **k):
    """Run fn while a person types `text` after the prompt appears."""
    t = p.answers(text)
    try:
        return fn(*a, **k)
    finally:
        t.join(15)


MISSING = "/nonexistent-dir-for-tty-test/tty"

# ---------------------------------------------------------------- the bug itself, on a stream that cannot seek
print("# the old pattern")
tmp = pathlib.Path(tempfile.mkdtemp(prefix="ttyopen-")).resolve()
fifo = tmp / "fifo"
os.mkfifo(str(fifo))
try:
    open(str(fifo), "r+").close()
    old = None
except Exception as e:                                      # noqa: BLE001
    old = e
check("old pattern: open(<non-seekable>, 'r+') raises io.UnsupportedOperation (the macOS 27 failure, reproduced on a FIFO)", isinstance(old, io.UnsupportedOperation), repr(old))
check("old pattern: that error is an OSError, so the old callers printed 'needs you at a terminal' even in a real terminal", isinstance(old, OSError))

# ---------------------------------------------------------------- the helper against a real pty
print("# terminal.ask_line on a pty")
p = Pty()
got = with_answer(p, "yes\n", terminal.ask_line, 'Build it? Type "yes": ', path=p.path)
screen = p.shown()
check("ask_line returns the typed line (with its newline)", got == "yes\n", repr(got))
check("ask_line printed the prompt on the terminal, not on stdout", 'Build it? Type "yes": ' in screen, repr(screen))
p.close()

p = Pty()
check("ask_line reads a non-ASCII line", with_answer(p, "héllo wörld\n", terminal.ask_line, "> ", path=p.path).strip() == "héllo wörld")
p.close()

p = Pty()
check("ask_line on Ctrl-D returns '' (end of input)", with_answer(p, "\x04", terminal.ask_line, "> ", path=p.path) == "")
p.close()

p = Pty()
check("ask_line on partial text then Ctrl-D returns '' (a line without a newline is a cancel, never an answer)", with_answer(p, "yes\x04\x04", terminal.ask_line, "> ", path=p.path) == "")
p.close()

p = Pty()
a = with_answer(p, "one\n", terminal.ask_line, "> ", path=p.path)
b = with_answer(p, "two\n", terminal.ask_line, "> ", path=p.path)
check("two prompts in a row each get their own line (nothing is lost between opens)", (a, b) == ("one\n", "two\n"), (a, b))
p.close()

p = Pty()
p.typed("yes\n")                                             # type-ahead: typed BEFORE the question was shown
got = with_answer(p, "real\n", terminal.ask_line, "> ", path=p.path)
check("type-ahead is dropped: a 'yes' typed before the prompt is NOT the answer, the line typed after it is", got == "real\n", repr(got))
p.close()

p = Pty()
p.typed("yes\n")
got = with_answer(p, "\x04", terminal.ask_line, "> ", path=p.path)
check("type-ahead is dropped: a pre-typed 'yes' and then Ctrl-D is a cancel, not yes", got == "", repr(got))
p.close()

p = Pty()
code = "import sys; sys.path.insert(0, %r); from shipmiracle import terminal; sys.stdout.write(repr(terminal.ask_line('Q: ', path=%r)))" % (str(ROOT), p.path)
proc = subprocess.Popen([sys.executable, "-c", code], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
t_ = p.answers("from the terminal\n")
out_, err_ = proc.communicate(input=b"yes\n", timeout=30)
t_.join(15)
check("piped stdin is ignored: the answer comes from the terminal, never from stdin", out_.decode() == repr("from the terminal\n"), (out_, err_[-300:]))
p.close()

before = len(os.listdir("/dev/fd")) if os.path.isdir("/dev/fd") else None
p = Pty()
for _ in range(20):
    with_answer(p, "x\n", terminal.ask_line, "> ", path=p.path)
after_ = len(os.listdir("/dev/fd")) if os.path.isdir("/dev/fd") else None
p.close()
check("no descriptor leak over 20 prompts", before is None or after_ <= before + 3, (before, after_))

try:
    terminal.ask_line("> ", path=MISSING)
    exc = None
except OSError as e:
    exc = e
check("missing device: ask_line raises OSError (the 'no terminal' signal callers already handle)", isinstance(exc, OSError), repr(exc))
p = Pty()
check("can_open: true for a pty, false for a missing device", terminal.can_open(path=p.path) is True and terminal.can_open(path=MISSING) is False)
p.close()
check("the default device is /dev/tty", terminal.TTY_PATH == "/dev/tty")

# ---------------------------------------------------------------- the callers, each through the same pty (terminal.TTY_PATH is the seam)
print("# callers")
p = Pty()
terminal.TTY_PATH = p.path
try:
    r = with_answer(p, "  CR-17  \n", pcli._tty_ask, "type CR-17: ")
    check("playbook cli._tty_ask: stripped answer, prompt on the terminal", r == "CR-17" and "type CR-17: " in p.shown(), r)
    check("playbook cli._tty_ask: Ctrl-D with no text -> '' (not a confirmation)", with_answer(p, "\x04", pcli._tty_ask, "x: ") == "")
    check("playbook cli._tty_ask: partial text then Ctrl-D -> '' (not a confirmation)", with_answer(p, "CR-17\x04\x04", pcli._tty_ask, "x: ") == "")
    check("playbook interview._tty_line (stdin is not a terminal): the typed answer, no newline", with_answer(p, "Describe my work\n", interview._tty_line, "Q1? ") == "Describe my work")
    check("playbook interview._tty_line on Ctrl-D -> None (a closed terminal)", with_answer(p, "\x04", interview._tty_line, "Q2? ") is None)
    check("playbook interview._tty_line on partial text then Ctrl-D -> None", with_answer(p, "half\x04\x04", interview._tty_line, "Q3? ") is None)
    check("playbook interview._has_terminal: True when the device opens", interview._has_terminal() is True)
    terminal.TTY_PATH = MISSING
    check("playbook cli._tty_ask: no device -> None", pcli._tty_ask("x: ") is None)
    check("playbook interview._tty_line: no device -> None", interview._tty_line("Q? ") is None)
    check("playbook interview._has_terminal: no device -> False", interview._has_terminal() is False)
finally:
    terminal.TTY_PATH = "/dev/tty"
    p.close()

# ---------------------------------------------------------------- the Touch ID build script (loaded as a module; a build is never executed)
print("# Touch ID build script")
script = ROOT / "bin" / "shipm-presence-build"
loader = importlib.machinery.SourceFileLoader("shipm_presence_build_under_test", str(script))
spec = importlib.util.spec_from_loader(loader.name, loader)
pb = importlib.util.module_from_spec(spec)
loader.exec_module(pb)
from shipmiracle import config as _config, owner as _owner  # noqa: E402

saved = (_owner.proof_required, _owner.gate, _config.get)
_owner.proof_required = lambda: True
_owner.gate = lambda *a, **k: None
_config.get = lambda key, *a, **k: str(pb.HERE)
try:
    for label, typed, want in (("typed yes", "yes\n", ""), ("typed another word", "no\n", "you did not type yes"), ("closed terminal (Ctrl-D)", "\x04", "you did not type yes")):
        p = Pty()
        terminal.TTY_PATH = p.path
        r = with_answer(p, typed, pb._owner_gate)
        check("_owner_gate, %s -> %r" % (label, want or "(allowed)"), (r == "") if not want else (want in r and r.startswith("Touch ID helper NOT built")), r)
        p.close()
    p = Pty()
    terminal.TTY_PATH = p.path
    p.typed("yes\n")                                         # type-ahead before the question must not build
    r = with_answer(p, "\x04", pb._owner_gate)
    check("_owner_gate, a 'yes' typed before the question was shown does not allow the build", "you did not type yes" in r, r)
    p.close()
    terminal.TTY_PATH = MISSING
    r = pb._owner_gate()
    check("_owner_gate, no terminal -> the 'needs you at a terminal' message", "this needs you at a terminal" in r and r.startswith("Touch ID helper NOT built"), r)
finally:
    terminal.TTY_PATH = "/dev/tty"
    _owner.proof_required, _owner.gate, _config.get = saved


def run_check(cfg_dir):
    env = dict(os.environ)
    env.pop("CLAUDECODE", None)
    env["SHIPMIRACLE_CONFIG"] = str(cfg_dir)
    r = subprocess.run([sys.executable, str(script), "--check"], capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL, env=env)
    return r.returncode, r.stdout.strip()


if sys.platform == "darwin":
    cfg = tmp / "cfg"
    rc, out = run_check(cfg)
    has_swiftc = bool(shutil.which("swiftc") or os.path.exists("/usr/bin/swiftc"))
    check("--check, nothing built: exit %d (1 = not built, 2 = no Swift compiler) and says how to fix it" % (1 if has_swiftc else 2), rc == (1 if has_swiftc else 2) and "not built" in out, (rc, out))
    (cfg / "bin").mkdir(parents=True)
    (cfg / "bin" / "shipm-presence").write_bytes(b"#!/bin/sh\nexit 0\n")
    (cfg / "presence.sha256").write_text("%s %s\n" % (hashlib.sha256((cfg / "bin" / "shipm-presence").read_bytes()).hexdigest(), hashlib.sha256((ROOT / "tools/presence/shipm-presence.swift").read_bytes()).hexdigest()))
    rc, out = run_check(cfg)
    check("--check, built and unchanged: exit 0 'ready'", rc == 0 and out.startswith("Touch ID helper: ready"), (rc, out))
    (cfg / "bin" / "shipm-presence").write_bytes(b"#!/bin/sh\nexit 1\n")
    rc, out = run_check(cfg)
    check("--check, helper swapped after the pin: not ready (exit 1 or 2)", rc in (1, 2) and "ready" not in out, (rc, out))
else:
    rc, out = run_check(tmp / "cfg")
    check("--check off macOS: exit 2 'not supported'", rc == 2 and "not supported" in out, (rc, out))

# ---------------------------------------------------------------- nobody opens the tty in a +-mode again
print("# source scan")
OLD = re.compile(r"""open\(\s*[^,]*tty[^,]*,\s*(?:mode\s*=\s*)?["'][rwa]b?\+b?["']""", re.I)
check("scan self-test: matches the double-quote, single-quote, r+b / rb+ / w+ / a+ and mode= forms of the old call",
      all(OLD.search(s) for s in ('with open("/dev/tty", "r+") as t:', "with open('/dev/tty','r+') as t:", 'open("/dev/tty", "rb+")', 'open("/dev/tty", "r+b")', 'open(_TTY_PATH, "w+")',
                                 'open(TTY_PATH, "a+")', 'open("/dev/tty", mode="r+")', "io.open('/dev/tty', mode = 'r+')", 'open(path_to_tty, "r+")')))
check("scan self-test: does not match os.open with flags, a plain read open, or an unrelated r+ open",
      not any(OLD.search(s) for s in ("fd = os.open('/dev/tty', os.O_RDWR | os.O_NOCTTY)", 'open("/dev/tty", "r")', 'open("/dev/tty", "w")', 'open("data.txt", "r+")')))
files = [f for d in ("bin", "shipmiracle", "hooks", "tools", "templates", ".githooks") if (ROOT / d).is_dir() for f in sorted((ROOT / d).rglob("*")) if f.is_file() and f.suffix in ("", ".py", ".sh")]
hits = []
for f in files:
    try:
        text = f.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        continue
    for n, line in enumerate(text.splitlines(), 1):
        if OLD.search(line):
            hits.append("%s:%d" % (f.relative_to(ROOT), n))
check("no file under bin/ shipmiracle/ hooks/ tools/ templates/ .githooks/ opens the tty with open(..., 'r+') (%d files scanned)" % len(files), len(files) > 50 and not hits, hits)

shutil.rmtree(tmp, ignore_errors=True)
print("\nFAILED: %d" % fails if fails else "\nALL PASS")
sys.exit(1 if fails else 0)
