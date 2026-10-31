"""Owner proof for the escalating autopilot commands (design docs/plans/2026-10-21-owner-proof-design.md incl. section 15, security blockers B1/B2).

A command that lets an autopilot run do MORE (start, daily check-in, admit, allow, resume, drop, a standing charter, switching autopilot on) passes three locks:
  lock 1  CLAUDECODE is not set                       (paths.require_owner: the cheap filter that exists today)
  lock 2  the process ancestry has no `claude` and has an owner host (a terminal app, VS Code, ...)   -> defeats `script`, `expect`, a python pty, a daemonised child
  lock 3  a presence check from a PROVIDER of a given tier (below): a live Touch ID touch, the Mac password in the system dialog, or a code typed in the terminal
`gate(action, hint)` runs locks 1 and 2 BEFORE anything is shown (a chat can never make the owner's computer pop a dialog at will); `select(...)` picks the provider (no UI);
`touch(...)` asks it AFTER the owner has read the printout. Exactly one check per user action.

Tiers (what a pass proves):  strong = a body or device-bound secret (Touch ID / Apple Watch)   medium = the account password typed into an OS-owned dialog
                              basic  = a person read this terminal just now (lock 2 + a random code typed in /dev/tty, type-ahead flushed; no OS help)
Setting `owner.presence`: auto (default: the best provider that works; basic only when the machine has NO strong or medium provider at all) | strong-only | basic-ok.
No silent downgrade: a provider that was installed and is now missing or changed ("broken") makes the action REFUSE; it never falls through to a lower tier.

What never goes through here (so it can never lock the owner out): stop, charter clear, switching off, show, every read-only command and all non-autopilot work.

Friction rules: one plain sentence per refusal with the exact next step, never a stack trace; after a cancelled or failed check a 30 s cool-down (no prompt loop); one prompt at a
time; the chat `allow:` route waits at most HOOK_WAIT_S and needs a provider that works without a terminal (medium or better).

Tests: in a sandbox (paths.sandboxed() and no SHIPMIRACLE_ENFORCE_OWNER=1) locks 2 and 3 are skipped exactly like lock 1 is today. Test seams are module attributes only (_CHAIN_OVERRIDE,
_HOST_OVERRIDE, PROVIDERS, _PROC, _WSL_OVERRIDE, _TTY_OVERRIDE); the single env seam SHIPMIRACLE_PRESENCE_BIN (a fake helper) is honoured only when paths.sandboxed().
Honest limits: nothing here stops same-uid code that writes Shipmiracle's files directly (contained only by the P6-1 sandbox or a separate account); a typed code does not stop a program that
controls a terminal window outside the chat's process tree and can read it; a same-user program can also WRITE to the owner's terminal device and draw a fake diff or prompt (the OS dialog reason of `hooks apply` therefore carries a summary built from the real bytes); a real Touch ID touch cannot be automated in tests (docs/owner-steps/p6-autopilot.sh has the 30-second
manual step). OS seam: no pwd/fcntl at import time here; macOS-only parts are behind providers and print 'macOS only for now' elsewhere."""
from __future__ import annotations

import hashlib
import os
import re
import sys
import time
from pathlib import Path

from . import SafetyError, paths

COOLDOWN_S = 30                 # after a cancelled / failed check: no new prompt for this long
TOUCH_WAIT_S = 60               # the provider's own limit for a command typed in a terminal
HOOK_WAIT_S = 20                # the chat `allow:` route: a hard cap, so the owner's chat never hangs
CODE_WAIT_S = 120               # the typed code: time to read and type it
MAX_PS_LEVELS = 256             # sanity bound of the ancestry walk (a loop or a longer chain is refused)
OWNER_HOSTS = ("Terminal", "iTerm", "iTerm2", "Ghostty", "WezTerm", "wezterm-gui", "kitty", "Alacritty", "Warp", "Hyper", "Visual Studio Code", "Cursor",
               "Code - Insiders", "Claude", "Claude Desktop", "VSCodium", "Zed", "Xcode", "login", "sshd", "sshd-session",
               "gnome-terminal-server", "gnome-terminal-", "konsole", "xfce4-terminal", "tilix", "terminator", "xterm", "urxvt", "foot", "code", "codium", "alacritty", "wezterm",
               "mate-terminal", "lxterminal", "tmux: client")
TIER_RANK = {"none": 0, "basic": 1, "medium": 2, "strong": 3}
SETTINGS = ("auto", "strong-only", "basic-ok")
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"     # no 0 O 1 I
_CHAIN_OVERRIDE = None          # tests: list of process names, nearest first, replacing the process walk
_HOST_OVERRIDE = None           # tests: callable(comm) -> bool replacing is_owner_host
_PROC = "/proc"                 # tests: a fake /proc tree
_WSL_OVERRIDE = None            # tests: True / False replacing the WSL detection
_TTY_OVERRIDE = None            # tests: path of the terminal device the typed code uses (default /dev/tty)


class OwnerRefused(SafetyError):
    """A refusal whose message is ONE plain sentence plus the exact next step (exit code 4 like every SafetyError)."""


def proof_required() -> bool:
    """Locks 2 and 3 (and the typed yes of allow / resume / drop) apply outside a sandbox, and inside one when SHIPMIRACLE_ENFORCE_OWNER=1."""
    return (not paths.sandboxed()) or os.environ.get("SHIPMIRACLE_ENFORCE_OWNER") == "1"


# ---------------------------------------------------------------- ancestry (lock 2)
def is_wsl() -> bool:
    if _WSL_OVERRIDE is not None:
        return bool(_WSL_OVERRIDE)
    return sys.platform.startswith("linux") and os.path.exists("/proc/sys/fs/binfmt_misc/WSLInterop")


NODE_RUNNERS = ("node", "nodejs", "bun", "deno", "npx", "npm", "pnpm", "yarn", "tsx", "ts-node")       # programs Claude Code can run through (D14 M4)
CLAUDE_PKG = "@anthropic-ai/claude-code"
CLAUDE_SCRIPTS = ("claude", "claude-code", "claude.js", "claude.mjs", "claude.cjs", "claude-code.js")


def args_are_claude(args, via_runner=False) -> bool:
    """D14 M4: Claude Code run through node (the npm install, `npx`, a launcher script): the command line holds the package name, or a node-like program runs a script named like the Claude Code
    launcher (claude, claude-code, claude.js, or a cli.js whose path says claude). An ordinary node program (server.js, a project's cli.js) is not taken for Claude."""
    a = (args or "").strip()
    if not a:
        return False
    toks = a.split()
    if via_runner and os.path.basename(toks[0]).lower().startswith("claude"):
        return True                      # the process is a node program (asked by its name) whose title was rewritten to `claude`: the npm install of Claude Code sets process.title, so `ps -o args=` shows just that
    runner = os.path.basename(toks[0]).lower() in NODE_RUNNERS
    if (runner and CLAUDE_PKG in a.lower()) or "claude-code/cli.js" in a.lower():
        return True
    if not runner:
        return False
    for t in toks[1:8]:
        if t.startswith("-"):
            continue
        b = os.path.basename(t).lower()
        if b in CLAUDE_SCRIPTS or (b == "cli.js" and "claude" in t.lower()):
            return True
    return False


def is_claude(comm: str, args=None) -> bool:
    c = (comm or "").strip()
    if not c:
        return bool(args) and args_are_claude(args)
    b = os.path.basename(c)
    if b == "claude" or b.startswith("claude-") or "/claude/versions/" in c or "/.claude/local/" in c or bool(re.fullmatch(r"\d+\.\d+\.\d+\S*", b) and "claude" in c.lower()):
        return True
    return bool(args) and args_are_claude(args)


def _entry_claude(e) -> bool:
    return bool(e.get("claude")) or is_claude(e.get("name"), e.get("args"))


# Exact application bundles (macOS) whose processes count as an owner host, with the code-signing identity `codesign` must report (Team ID None = an Apple-signed system app).
# Prefix rules on process names are gone: a process NAME is attacker-settable (exec -a, a copied or renamed binary), the bundle path and its signature are not.
HOST_BUNDLES = {
    "/System/Applications/Utilities/Terminal.app": ("com.apple.Terminal", None),
    "/Applications/Utilities/Terminal.app": ("com.apple.Terminal", None),
    "/Applications/iTerm.app": ("com.googlecode.iterm2", "H7V7XYVQ7D"),
    "/Applications/Visual Studio Code.app": ("com.microsoft.VSCode", "UBF8T346G9"),
    "/Applications/Ghostty.app": ("com.mitchellh.ghostty", "24VZSL4C39"),
    "/Applications/Warp.app": ("dev.warp.Warp-Stable", "2BBY89MBSN"),
}
MAC_SYSTEM_HOSTS = ("/usr/bin/login", "/usr/sbin/sshd", "/usr/libexec/sshd-session")           # root-owned system programs (SIP-protected)
LINUX_HOST_EXES = ("gnome-terminal-server", "konsole", "xfce4-terminal", "tilix", "xterm", "urxvt", "foot", "kitty", "alacritty", "wezterm-gui", "code", "codium", "login",
                   "sshd", "sshd-session", "mate-terminal", "lxterminal")                          # basenames of the RESOLVED executable under a root-owned, non user-writable path
LINUX_HOST_ROOTS = ("/usr", "/opt", "/bin", "/sbin", "/lib", "/lib64", "/snap")


def _bundle_root(path):
    i = path.find(".app/")
    return path[:i + 4] if i > 0 and not path.startswith(("~", ".")) else ""


def is_owner_host(comm: str, override=None) -> bool:
    """NAME-based host test used by lock 2 (plausible ancestry): exact names, or a process whose full path lies inside one of the exact HOST_BUNDLES. NOT proof: at the typed-code tier
    host_proof() additionally checks the resolved executable path, ownership and (macOS) the code signature. A chain that ends at launchd / init (pid 1) without a host is a detached process."""
    if override is not None:
        return bool(override(comm))
    c = (comm or "").strip()
    if not c:
        return False
    b = os.path.basename(c)
    if b in OWNER_HOSTS:
        return True
    if is_wsl() and (b.startswith("Relay(") or b == "SessionLeader" or b == "init"):
        return True
    if "/.vscode-server/" in c or "/.cursor-server/" in c:
        return True
    return _bundle_root(c) in HOST_BUNDLES


def _read(path, limit=4096):
    try:
        with open(path, "rb") as f:
            return f.read(limit)
    except OSError:
        return None


_lstat = os.lstat               # tests: a fake file-system table
_readlink = os.readlink
_realpath = os.path.realpath
_CODESIGN = None                # tests: callable(bundle) -> {"valid": bool, "identifier": str, "team": str|None, "adhoc": bool}
_DETAIL_OVERRIDE = None         # tests: list of {"name", "path"} replacing the process walk of host_proof()


def _proc_walk(start_pid):
    """Linux / WSL: walk /proc/<pid>/stat (the parent is the 2nd field after the LAST ')', so a name containing ') ' cannot shift fields); the name is argv[0] of cmdline
    (comm is cut at 15 characters), with comm as the fallback; `path` is where /proc/<pid>/exe points (None when unreadable). No subprocess. -> (entries nearest first, error)."""
    out, pid, seen = [], start_pid, set()
    while pid > 1:
        if pid in seen or len(out) >= MAX_PS_LEVELS:
            return out, "the process tree could not be read to its end"
        seen.add(pid)
        st = _read(os.path.join(_PROC, str(pid), "stat"))
        if not st:
            return out, "the process tree could not be read"
        txt = st.decode("utf-8", "replace")
        rp = txt.rfind(")")
        lp = txt.find("(")
        rest = txt[rp + 1:].split() if rp > lp >= 0 else []
        if len(rest) < 2 or not rest[1].isdigit():
            return out, "the process tree could not be read"
        comm = txt[lp + 1:rp]
        cl = _read(os.path.join(_PROC, str(pid), "cmdline"))
        name = ""
        args = ""
        if cl:
            args = " ".join(x for x in cl.decode("utf-8", "replace").split("\0") if x)
            argv0 = cl.split(b"\0", 1)[0].decode("utf-8", "replace")
            if "/.vscode-server/" in argv0 or "/.cursor-server/" in argv0:
                name = argv0                                    # keep the path: the server's node is an owner host by its folder (NAME level only)
            else:
                name = os.path.basename(argv0)
        try:
            path = _readlink(os.path.join(_PROC, str(pid), "exe"))
        except OSError:
            path = None
        out.append({"name": (name or comm).strip(), "path": path, "args": args[:2000], "claude": args_are_claude(args)})
        pid = int(rest[1])
    return out, ""


def process_detail(start_pid=None):
    """([{'name', 'path'}] nearest first, error text or ''). darwin: `ps -o ppid=,comm=` (comm is the full executable path); linux / WSL: /proc; native Windows: not supported."""
    start = os.getppid() if start_pid is None else start_pid
    if sys.platform == "win32":
        return [], "not supported on this OS yet (run Shipmiracle inside WSL 2)"
    if sys.platform.startswith("linux"):
        return _proc_walk(start)
    import subprocess
    out, pid, seen = [], start, set()
    while pid > 1:
        if pid in seen or len(out) >= MAX_PS_LEVELS:
            return out, "the process tree could not be read to its end"
        seen.add(pid)
        try:
            r = subprocess.run(["/bin/ps", "-o", "ppid=,comm=", "-p", str(pid)], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=3, stdin=subprocess.DEVNULL,
                               env={"PATH": "/bin:/usr/bin", "LC_ALL": "C"})
        except (OSError, subprocess.SubprocessError):
            return out, "the process tree could not be read"
        m = re.match(r"(\d+)\s+(.*)$", r.stdout.decode("utf-8", "replace").strip())
        if r.returncode != 0 or not m:
            return out, "the process tree could not be read"
        nm = m.group(2).strip()
        args = ""
        if os.path.basename(nm).lower() in NODE_RUNNERS:                  # only node-like programs: one more `ps` call asks how it was started (D14 M4)
            try:
                ra = subprocess.run(["/bin/ps", "-o", "args=", "-p", str(pid)], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=3, stdin=subprocess.DEVNULL,
                                    env={"PATH": "/bin:/usr/bin", "LC_ALL": "C"})
                if ra.returncode != 0:
                    return out, "the process tree could not be read"            # fail closed: an unreadable command line is not an empty one
                args = ra.stdout.decode("utf-8", "replace").strip()[:2000]
            except (OSError, subprocess.SubprocessError):
                return out, "the process tree could not be read"
        out.append({"name": nm, "path": nm if nm.startswith("/") else None, "args": args, "claude": args_are_claude(args, True)})
        pid = int(m.group(1))
    return out, ""


def process_chain(start_pid=None):
    """(chain of process names nearest first, error text or '') - the NAME view of process_detail(). A node process that runs Claude Code is reported under the name `claude` (D14 M4)."""
    d, err = process_detail(start_pid)
    return ["claude" if e.get("claude") else e["name"] for e in d], err


def ancestry(env, chain_override=None, host_override=None, max_levels=None, claude_ok=True):
    """(ok, why). More than one `claude` above = refused (a nested claude -p); a chain without a recognised owner host above the claude (or anywhere, when there is no
    claude) = refused; CLAUDE_CODE_ENTRYPOINT=sdk-* = refused; a ps / proc failure and native Windows = refused (fail closed)."""
    ep = (env.get("CLAUDE_CODE_ENTRYPOINT") or "").strip().lower()
    if ep.startswith("sdk-") or ep.startswith("sdk_"):
        return False, "the chat was started through the SDK (CLAUDE_CODE_ENTRYPOINT=%s)" % ep[:30]
    if chain_override is not None:
        chain = list(chain_override)
    else:
        chain, err = process_chain()
        if err:
            return False, err
    n = sum(1 for c in chain if is_claude(c))
    if n and not claude_ok:
        return False, "this command was started from inside a Claude chat (a claude process sits above it)"
    if n > 1:
        return False, "a second claude process sits above this chat (a nested claude -p)"
    first = next((i for i, c in enumerate(chain) if is_claude(c)), None)
    above = chain[first + 1:] if first is not None else chain
    if not any(is_owner_host(c, host_override) for c in above):
        return False, "this chat does not descend from a terminal, VS Code or the Claude app (a detached process)"
    return True, ""


# ---------------------------------------------------------------- host proof (the typed-code tier only)
HOST_UNPROVEN = ("Shipmiracle cannot prove this terminal is yours (it runs from a place you or a program of yours can change): use an OS prompt (set owner.presence and build the Touch ID helper), "
                 "or run the command from Terminal or VS Code installed system-wide.")


def _locked_down(path) -> bool:
    """True when `path` and every folder above it are real (no symlink), owned by root and not writable by group or others. (macOS /Applications is root:admin 775 and fails here on
    purpose: bundles are proved by their code signature instead.)"""
    p = path
    while True:
        try:
            st = _lstat(p)
        except OSError:
            return False
        import stat as _st
        if _st.S_ISLNK(st.st_mode) or st.st_uid != 0 or (st.st_mode & 0o022):
            return False
        if p == "/":
            return True
        p = os.path.dirname(p) or "/"


def _codesign(bundle) -> dict:
    """Read-only: {'valid', 'identifier', 'team', 'adhoc'} for an app bundle (`codesign --verify --deep --strict` and `codesign -dv`); nothing is cached."""
    if _CODESIGN is not None:
        return _CODESIGN(bundle)
    import subprocess
    out = {"valid": False, "identifier": "", "team": None, "adhoc": True}
    try:
        v = subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", bundle], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20, stdin=subprocess.DEVNULL)
        d = subprocess.run(["/usr/bin/codesign", "-dv", "--verbose=2", bundle], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return out
    txt = (d.stderr + d.stdout).decode("utf-8", "replace")
    m = re.search(r"^Identifier=(\S+)", txt, re.M)
    t = re.search(r"^TeamIdentifier=(\S+)", txt, re.M)
    out.update(valid=v.returncode == 0, identifier=m.group(1) if m else "", team=(t.group(1) if t and t.group(1) != "not" else None), adhoc="Signature=adhoc" in txt or "(adhoc)" in txt)
    return out


def _entry_proven(e, above=()) -> bool:
    """One process of the chain is a PROVEN owner host: macOS - its executable lies inside an exact HOST_BUNDLES app (under /Applications or /System, never ~/Applications) whose code
    signature is valid, not ad hoc, and has the expected identifier and Team ID; or it is one of the SIP-protected system programs. Linux / WSL - the resolved executable (never
    the process name) is a known terminal / editor binary under a system root, with no symlink, not deleted, and root-owned with no group / other write on the file and every folder above."""
    path = e.get("path")
    if not path or not path.startswith("/") or path.endswith(" (deleted)"):
        return False
    if sys.platform == "darwin":
        if path in MAC_SYSTEM_HOSTS:
            # m1: /usr/bin/login and sshd are root-owned, but any program of the owner can start a process under them (`login -pf`, `ssh localhost`): they prove the terminal only
            # when a proven application bundle (Terminal, iTerm2, VS Code ...) sits above them
            return _locked_down(path) and any(_entry_proven(x) for x in (above or ()))
        root = _bundle_root(path)
        want = HOST_BUNDLES.get(root)
        if not want:
            return False
        c = _codesign(root)
        return bool(c.get("valid")) and not c.get("adhoc") and c.get("identifier") == want[0] and c.get("team") == want[1]
    if _realpath(path) != path:
        return False                                            # a symlink somewhere in the path
    if not any(path == r or path.startswith(r + "/") for r in LINUX_HOST_ROOTS) and not (is_wsl() and path == "/init"):
        return False
    if os.path.basename(path) not in LINUX_HOST_EXES and not (is_wsl() and path == "/init"):
        return False
    return _locked_down(path)


def host_proof(claude_ok=False):
    """(ok, why): at the typed-code tier lock 2 must rest on a PROVEN host above this process, not on a process name. Every other tier relies on the OS prompt instead."""
    if _DETAIL_OVERRIDE is not None:
        detail = list(_DETAIL_OVERRIDE)
    else:
        detail, err = process_detail()
        if err:
            return False, err
    n = sum(1 for e in detail if _entry_claude(e))
    if n and not claude_ok:
        return False, "this command was started from inside a Claude chat (a claude process sits above it)"
    first = next((i for i, e in enumerate(detail) if _entry_claude(e)), None)
    above = detail[first + 1:] if first is not None else detail
    for i, e in enumerate(above):
        if _entry_proven(e, above[i + 1:]):
            return True, ""
    return False, HOST_UNPROVEN


# ---------------------------------------------------------------- events, refusals
def _event(action, ok, why, **more) -> None:
    try:
        from . import events
        events.emit("owner.presence", dict({"action": action, "ok": bool(ok), "why": why[:60]}, **more), src="shipmiracle")
    except Exception:
        pass


def _refuse(action, why, text, **more) -> "OwnerRefused":
    _event(action, False, why, **more)
    return OwnerRefused(text)


def gate(action, hint) -> None:
    """Locks 1 and 2, before anything is printed. `hint` is the exact command the owner should run in a terminal."""
    try:
        paths.require_owner("shipm autopilot " + action)
    except SafetyError:
        raise _refuse(action, "chat", "This needs you at a terminal: run `%s` in Terminal or VS Code, not inside a Claude chat." % hint)
    if not proof_required():
        return
    ok, why = ancestry(os.environ, _CHAIN_OVERRIDE, _HOST_OVERRIDE, claude_ok=False)       # a CLI command typed by the owner has NO claude above it (the hook route is the one that sits under a chat)
    if not ok:
        if "not supported on this OS" in why:
            raise _refuse(action, "os", "Shipmiracle runs inside WSL 2 on Windows (native Windows is not supported yet): open your Linux terminal and run `%s`." % hint)
        raise _refuse(action, "ancestry", "Run this yourself in Terminal or VS Code (it was started from a script, a background job or another program): `%s`." % hint)


# ---------------------------------------------------------------- state file: cool-down and the one-time warning
def _state_file() -> Path:
    from . import state as core
    return core.ensure_dir(core.ensure_root()) / "presence.json"


def _load_state() -> dict:
    import json
    try:
        d = json.loads(_state_file().read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_file(path, text) -> None:
    """The hardened atomic writer (shipmiracle.state.atomic_write: temp file in the same folder, fsync, replace; refuses a symlink or a non-regular target; guard_real_write)."""
    from . import state as core
    core.atomic_write(path, text.encode("utf-8"), 0o600)


def _save_state(d) -> None:
    import json
    try:
        _write_file(_state_file(), json.dumps(d))
    except (OSError, SafetyError):
        pass


def cooldown_left(now=None) -> int:
    """Seconds left of the pause after a cancelled / failed check (0 = none)."""
    try:
        left = COOLDOWN_S - ((time.time() if now is None else now) - float(_load_state().get("fail_ts", 0)))
    except (TypeError, ValueError):
        return 0
    return max(0, int(left + 0.999)) if left > 0 else 0


def _mark_failed(now=None) -> None:
    d = _load_state()
    d["fail_ts"] = time.time() if now is None else now
    _save_state(d)


def _clear_failed() -> None:
    d = _load_state()
    if "fail_ts" in d:
        d.pop("fail_ts")
        _save_state(d)


# ---------------------------------------------------------------- providers
def helper_path():
    """(path, sandbox seam used). The fixed place is <config>/bin/shipm-presence; SHIPMIRACLE_PRESENCE_BIN counts only when paths.sandboxed()."""
    seam = os.environ.get("SHIPMIRACLE_PRESENCE_BIN")
    if seam and paths.sandboxed():
        return seam, True
    return str(Path(paths.config_dir()) / "bin" / "shipm-presence"), False


def _record_path() -> Path:
    return Path(paths.config_dir()) / "presence.sha256"


_fstat = os.fstat               # tests: a fake file status
_AFTER_HASH = None              # tests: callable run between the hash and the start of the helper (a swap there must change nothing)
HELPER_MAX = 64 * 1024 * 1024   # a larger file is not our helper


def _helper_bytes():
    """-> (state, bytes). State: 'ready' | 'missing' | 'changed'. The helper is opened WITHOUT following a link (O_NOFOLLOW), must be a regular file owned by this user and not writable by group
    or others (D14 m2), and its bytes are read from that one open file; outside the test seam they must hash to the pin <config>/presence.sha256. The bytes returned are the bytes that were
    checked: callers run THEM (a private copy), never the path again."""
    p, seam = helper_path()
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(p, flags)
    except (FileNotFoundError, NotADirectoryError):
        return "missing", None
    except OSError:
        return "changed", None                                  # a symlink (ELOOP), no permission, ...: not our helper
    try:
        st = _fstat(fd)
        import stat as _st
        if not _st.S_ISREG(st.st_mode) or st.st_uid != os.geteuid() or (st.st_mode & 0o022) or st.st_size > HELPER_MAX:
            return "changed", None
        if not st.st_mode & 0o100:
            return "missing", None                              # not executable: not built (as before)
        chunks, n = [], 0
        while True:
            c = os.read(fd, 1 << 20)
            if not c:
                break
            chunks.append(c)
            n += len(c)
            if n > HELPER_MAX:
                return "changed", None
        data = b"".join(chunks)
    except OSError:
        return "changed", None
    finally:
        os.close(fd)
    if seam:
        return "ready", data
    try:
        want = _record_path().read_text().split()[0]
    except (OSError, IndexError):
        return "changed", None
    return ("ready", data) if want == hashlib.sha256(data).hexdigest() else ("changed", None)


def helper_state() -> str:
    """'ready' | 'missing' | 'changed' | 'unsupported' (a read-only look at the macOS helper; no process is started)."""
    seam = bool(os.environ.get("SHIPMIRACLE_PRESENCE_BIN")) and paths.sandboxed()
    if sys.platform != "darwin" and not seam:
        return "unsupported"
    return _helper_bytes()[0]


_HELPER_CACHE = {}              # per process only: a cached "strong absent" in a file would be a downgrade switch


def _run_helper(args, timeout):
    """-> (returncode, first output line) or (None, '') when it could not run. The helper is re-checked here (D14 m2) and a PRIVATE COPY of the checked bytes is run from a fresh 0700
    folder, so nothing can be swapped between the check and the run. Own process group, killed when the cap passes."""
    import shutil
    import signal
    import subprocess
    import tempfile
    state, data = _helper_bytes()
    if state != "ready" or data is None:
        return None, ""
    if _AFTER_HASH is not None:
        _AFTER_HASH()
    try:
        from . import state as core
        base = str(core.ensure_dir(core.ensure_root() / "presence-run"))          # D14 #9: under the 0700 state folder (a hardened, user-only place), not the shared temp folder
    except Exception:
        base = None
    d = tempfile.mkdtemp(prefix="shipm-presence-", dir=base)
    try:
        os.chmod(d, 0o700)
        cp = os.path.join(d, "shipm-presence")
        fd = os.open(cp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o700)
        try:
            _write_all(fd, data)
        finally:
            os.close(fd)
        try:
            proc = subprocess.Popen([cp] + list(args), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env={"PATH": "/usr/bin:/bin"}, start_new_session=True)
        except OSError:
            return None, ""
        try:
            out, _e = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                pass
            proc.communicate()
            return 1, "refused"
        return proc.returncode, out.decode("utf-8", "replace").strip().splitlines()[0] if out.strip() else ""
    except OSError:
        return None, ""
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _write_all(fd, data):
    mv = memoryview(data)
    while mv:
        mv = mv[os.write(fd, mv):]


def helper_policies():
    """The set of policies the helper says this Mac can evaluate now ({'strong', 'owner'}), or None when it could not be asked."""
    if "policies" not in _HELPER_CACHE:
        rc, word = _run_helper(["--probe"], 5)
        _HELPER_CACHE["policies"] = set(word.split()) - {"none"} if rc == 0 else None
    return _HELPER_CACHE["policies"]


def reset_cache() -> None:
    _HELPER_CACHE.clear()


def _have_swiftc() -> bool:
    import shutil
    return bool(shutil.which("swiftc") or os.path.exists("/usr/bin/swiftc"))


class Provider:
    name = "none"
    tier = "none"

    def probe(self) -> str:
        """'ready' | 'setup' (installable: e.g. the helper is not built) | 'absent' | 'broken' (was installed, now missing or changed). No UI."""
        return "absent"

    def ask(self, reason, timeout) -> str:
        """-> 'ok' | 'refused' | 'unavailable'"""
        return "unavailable"


class HelperProvider(Provider):
    """macOS: the local Swift helper (LocalAuthentication). Two policies: strong (Touch ID / Apple Watch only) and owner (those, else the Mac password)."""
    def __init__(self, name, tier, policy):
        self.name, self.tier, self.policy = name, tier, policy

    def probe(self) -> str:
        st = helper_state()
        if st == "unsupported":
            return "absent"
        if st == "changed":
            return "broken"
        if st == "missing":
            if _record_path().exists():
                return "broken"
            return "setup" if _have_swiftc() else "absent"
        pol = helper_policies()
        if pol is None:
            return "broken"
        return "ready" if self.policy in pol else "absent"

    def ask(self, reason, timeout) -> str:
        rc, word = _run_helper(["--reason", reason, "--policy", self.policy, "--timeout", str(int(timeout))], timeout + 3)
        if rc == 0 and word == "ok":
            return "ok"
        if rc == 2 or word == "unavailable":
            return "unavailable"
        return "refused"


class TypedCode(Provider):
    """Every Unix: lock 2 has passed; a random code is printed on /dev/tty (never stdin) after the type-ahead is flushed, and ONE typed line must match. It replaces the typed yes."""
    name = "typed-code"
    tier = "basic"
    needs_tty = True
    needs_host_proof = True

    def probe(self) -> str:
        if sys.platform == "win32":
            return "absent"
        return "ready" if (_TTY_OVERRIDE or os.path.exists("/dev/tty")) else "absent"

    def ask(self, reason, timeout) -> str:
        import secrets
        try:
            import select
            import termios
        except ImportError:
            return "unavailable"
        try:
            fd = os.open(_TTY_OVERRIDE or "/dev/tty", os.O_RDWR | os.O_NOCTTY)
        except OSError:
            return "unavailable"
        try:
            try:
                termios.tcflush(fd, termios.TCIFLUSH)          # drops type-ahead: a pre-typed or pre-piped line can never answer the code that is not printed yet
            except termios.error:
                return "unavailable"
            code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(6))
            os.write(fd, ("\n  %s\n  Type this code to confirm (or press Enter to cancel): %s  >  " % (reason[:160], code)).encode("utf-8", "replace"))
            buf = b""
            end = time.time() + timeout
            while b"\n" not in buf and time.time() < end:
                r, _w, _x = select.select([fd], [], [], max(0.1, min(1.0, end - time.time())))
                if r:
                    chunk = os.read(fd, 256)
                    if not chunk:
                        break
                    buf += chunk
            line = buf.split(b"\n", 1)[0].decode("utf-8", "replace").strip().upper()
            os.write(fd, b"\n")
            return "ok" if line == code else "refused"
        finally:
            os.close(fd)


PROVIDERS = [HelperProvider("macos-touchid", "strong", "strong"), HelperProvider("macos-password", "medium", "owner"), TypedCode()]


def presence_setting() -> str:
    try:
        from . import config
        v = config.get("owner.presence")
    except Exception:
        v = None
    return v if v in SETTINGS else "auto"


class Selection:
    """The result of select(): the providers to try in order and the tier of the first. `tier` is what the owner will be asked with."""
    def __init__(self, providers, tier, setting, note=""):
        self.providers, self.tier, self.setting, self.note = providers, tier, setting, note


def best():
    """(provider name, tier) of the best provider that works now, or ('none', 'none'). Read-only; used by doctor and `shipm owner status`."""
    for p in PROVIDERS:
        try:
            if p.probe() == "ready":
                return p.name, p.tier
        except Exception:
            continue
    return "none", "none"


_ACCOUNT_OVERRIDE = None        # tests: callable() -> True when the current account is a standard (non-admin) user


def account_is_standard() -> bool:
    """True only when this account is COMPUTED to be a standard user: not root, not in an administrator group (admin / sudo / wheel). If it cannot be computed (native Windows,
    no group database, any error) the answer is False: not separate."""
    if _ACCOUNT_OVERRIDE is not None:
        return bool(_ACCOUNT_OVERRIDE())
    try:
        import grp
        if os.geteuid() == 0:
            return False
        names = set()
        for g in set(os.getgroups()) | {os.getegid()}:
            try:
                names.add(grp.getgrgid(g).gr_name)
            except KeyError:
                pass
        return not (names & {"admin", "sudo", "wheel", "root"})
    except Exception:
        return False


def separate_marker() -> bool:
    return (Path(paths.config_dir()) / "throwaway-account").is_file()


def separate_account() -> bool:
    """A separate account is COMPUTED, not trusted from a file: the marker (made by `shipm owner mark-separate-account`) AND an account that is a standard user. On an administrator
    account a forged marker counts for nothing."""
    return separate_marker() and account_is_standard()


TEXTS = {
    "unsupported": "Owner confirmation for autopilot is not available on this computer: the autopilot commands that need it stay off here (stop, switch-off and show still work).",
    "missing": "The Touch ID helper is not built yet: run `bin/shipm-presence-build` once (a few seconds), then run this again.",
    "broken": "The Touch ID helper is missing or changed since it was built, so Shipmiracle will not fall back to a weaker check: run `bin/shipm-presence-build` to rebuild it, then run this again.",
    "unavailable": "Touch ID is not available on this Mac right now (sensor off, lid closed or no Touch ID): this works again when the sensor is available; stop and switch-off still work.",
    "strong-only": "Your setting (owner.presence = strong-only) needs Touch ID, which is not available right now (lid closed?): stop and switch-off still work.",
    "refused": "The check was cancelled or did not match, so nothing was changed. Run the command again when you are ready (wait %d s first).",
    "tier": "This action needs a stronger owner check than this computer can give (%s): use a Mac password dialog or Touch ID, or mark a separate user account with `shipm owner mark-separate-account`.",
    "hook": "The chat line cannot show a system dialog on this computer.",
    "basic_opt_in": "This computer has no Touch ID or password prompt that Shipmiracle can use. A typed code is possible only if you allow it: run `shipm switch owner.presence basic-ok` once (it proves a plausible terminal, not a person; a program that can open a terminal window can answer it).",
    "not_standard": "This account has administrator rights, so it cannot count as a separate account: use a standard user account made for autopilot, then run `shipm owner mark-separate-account` there.",
    "tty": "No terminal is available for the code: run the command in Terminal or VS Code.",
}
WARN_BASIC = ("You allowed a typed code (owner.presence basic-ok) because this computer has no Touch ID, Windows Hello or fingerprint that Shipmiracle can use. That proves a plausible terminal, not a person: "
              "it stops a chat from approving autopilot by typing 'yes' itself, but NOT a chat that can open a terminal window and read or type into it. Autopilot options A and B work this way; option C (keeps going until you disable it) needs your system password "
              "prompt, a fingerprint, or a separate user account.")
WARN_MEDIUM = "This Mac has no Touch ID, so Shipmiracle asks for your Mac password in the system dialog. A chat cannot answer it. All autopilot options work."


def select(min_tier="basic", hook=False, separate_ok=False, setting=None) -> Selection:
    """Pick the provider(s) for one action (no UI). Raises OwnerRefused with one plain sentence when none is allowed. Returns None when proof is not required."""
    if not proof_required():
        return None
    setting = setting or presence_setting()
    states = []
    for p in PROVIDERS:
        if hook and getattr(p, "needs_tty", False):
            continue
        try:
            states.append((p, p.probe()))
        except Exception:
            states.append((p, "broken"))
    os_states = [(p, s) for p, s in states if p.tier != "basic"]
    if any(s == "broken" for _p, s in os_states):
        raise _refuse("select", "broken", TEXTS["broken"])
    ready = [p for p, s in states if s == "ready"]
    os_ready = [p for p in ready if p.tier != "basic"]
    if setting == "strong-only":
        cand = [p for p in os_ready if p.tier == "strong"]
        if not cand:
            if any(s == "setup" for _p, s in os_states):
                raise _refuse("select", "setup", TEXTS["missing"])
            raise _refuse("select", "strong-only", TEXTS["strong-only"])
    else:
        cand = sorted(os_ready, key=lambda p: -TIER_RANK[p.tier])
        if not cand:
            if any(s == "setup" for _p, s in os_states):
                raise _refuse("select", "setup", TEXTS["missing"])
            cand = [p for p in ready if p.tier == "basic"]
            if cand and setting != "basic-ok":
                raise _refuse("select", "basic_opt_in", TEXTS["basic_opt_in"])
            if not cand:
                if hook:
                    raise _refuse("select", "hook", TEXTS["hook"])
                raise _refuse("select", "unsupported", TEXTS["unsupported"] if sys.platform == "win32" else TEXTS["tty"])
        elif setting == "basic-ok":
            cand = cand + [p for p in ready if p.tier == "basic"]
    first = cand[0]
    if getattr(first, "needs_host_proof", False):
        ok_, why_ = host_proof()
        if not ok_:
            raise _refuse("select", "host", why_ if why_ == HOST_UNPROVEN else "Shipmiracle cannot check where this command runs from (%s): use an OS prompt (owner.presence) or run it from Terminal or VS Code." % why_)
    need = TIER_RANK[min_tier]
    if TIER_RANK[first.tier] < need and not (separate_ok and first.tier == "basic" and not os_ready and separate_account()):          # a separate account never lowers the tier on a machine that HAS an OS prompt
        raise _refuse("select", "tier", TEXTS["tier"] % first.tier, tier=first.tier, provider=first.name)
    return Selection(cand, first.tier, setting)


def _warn_once(sel) -> None:
    """The one-time (per machine and per best tier) sentence about what a weaker check does and does not prove."""
    if sel.tier == "strong":
        return
    d = _load_state()
    if d.get("warned_tier") == sel.tier:
        return
    sys.stdout.write((WARN_BASIC if sel.tier == "basic" else WARN_MEDIUM) + "\n")
    d["warned_tier"] = sel.tier
    _save_state(d)


def touch(action, reason, sel=None, timeout=None, hook_cmd=None, **kw) -> None:
    """Lock 3: ONE presence check whose reason text is `reason`. Returns when the owner passed; raises OwnerRefused (one plain sentence + the next step) otherwise.
    sel: the Selection from select() (computed here when not given; kw goes to select). hook_cmd: the terminal command to name when the chat route cannot get a check."""
    if not proof_required():
        return
    if sel is None:
        try:
            sel = select(hook=bool(hook_cmd), **kw)
        except OwnerRefused as e:
            if hook_cmd:
                raise OwnerRefused(str(e).rstrip(".") + ". To do it now, run in Terminal: `%s`." % hook_cmd)
            raise
    wait = int(timeout if timeout is not None else TOUCH_WAIT_S)
    left = cooldown_left()
    if left > 0:
        raise _refuse(action, "cooldown", "The last check was not completed a moment ago; wait %d s, then run it again (no prompt is shown until then)." % left)
    from . import state as core
    lock = core.ensure_dir(core.ensure_root()) / "presence.lock"
    try:
        cm = core.lock_file(lock, timeout=0.05)
        cm.__enter__()
    except Exception:
        raise _refuse(action, "busy", "Another owner check is already open: finish or cancel it first, then run this again.")
    word, used = "unavailable", sel.providers[0]
    try:
        if not hook_cmd:                       # a hook prints JSON on stdout: never a warning there
            _warn_once(sel)
        for i, p in enumerate(sel.providers):
            used = p
            word = p.ask(reason, CODE_WAIT_S if getattr(p, "needs_tty", False) else wait)
            if word != "unavailable" or i == len(sel.providers) - 1:
                break
    finally:
        try:
            cm.__exit__(None, None, None)
        except Exception:
            pass
    if word == "ok":
        _clear_failed()
        _event(action, True, "passed", tier=used.tier, provider=used.name)
        return
    if word == "refused":
        _mark_failed()
        text = TEXTS["refused"] % COOLDOWN_S
    elif sel.setting == "strong-only":
        text = TEXTS["strong-only"]
    elif used.tier == "basic":
        text = TEXTS["tty"]
    else:
        text = TEXTS["unavailable"]
    if hook_cmd:
        text = text.rstrip(".") + ". To do it now, run in Terminal: `%s`." % hook_cmd
    raise _refuse(action, word, text, tier=used.tier, provider=used.name)


def confirm(action, hint, reason, timeout=None, **kw) -> None:
    """For actions with no printout of their own (switches, a standing `charter set`): locks 1-3 in one call, one check."""
    gate(action, hint)
    touch(action, reason, timeout=timeout, **kw)


def summary_line(hours=24) -> str:
    """'Owner checks in the last 24 h: N approved (Touch ID 3, typed code 1), M refused' from the owner.presence events; '' when there are none."""
    try:
        from . import events
        cutoff = time.time() - hours * 3600
        ok, bad, by = 0, 0, {}
        for e in events.tail(4000):
            if e.get("kind") != "owner.presence" or float(e.get("ts") or 0) < cutoff:
                continue
            d = e.get("data") or {}
            if d.get("action") in ("select",):
                continue
            if d.get("ok"):
                ok += 1
                nm = {"macos-touchid": "Touch ID", "macos-password": "Mac password", "typed-code": "typed code"}.get(d.get("provider"), d.get("provider") or "?")
                by[nm] = by.get(nm, 0) + 1
            else:
                bad += 1
        if not ok and not bad:
            return ""
        return "Owner checks in the last %d h: %d approved%s, %d refused" % (hours, ok, " (" + ", ".join("%s %d" % kv for kv in sorted(by.items())) + ")" if by else "", bad)
    except Exception:
        return ""


# ---------------------------------------------------------------- the option C go-live switch (B2), the separate-account marker, the presence setting
P61_LINES = ("1", "2", "3", "4", "5", "6", "7")       # the written pass list of probe P6-1 (design section 8); ALL seven are required (owner answer Q8: no partial pass)
P61_VALID_S = 30 * 86400
P61_FUTURE_S = 300                  # a record dated later than now + 5 minutes is refused (clock slack only): a forged long-lived record
SANDBOX_SETTINGS = ("sandbox.enabled",)       # the Claude Code setting the P6-1 probe tests (dotted path in settings.json); the only names the standing-run hook check accepts
STANDING_KEY = "autopilot.standing.enabled"


def probes_path() -> Path:
    return Path(paths.config_dir()) / "probes.json"


def standing_allowed(now=None):
    """(ok, why): option C may be switched on only after a recorded P6-1 pass of all seven lines within 30 days, or on a separate account (marker file
    <config>/throwaway-account, created by `shipm owner mark-separate-account`). Read-only."""
    import json
    if separate_account():
        return True, "separate account"
    try:
        d = json.loads(probes_path().read_text()).get("P6-1") or {}
    except (OSError, ValueError, AttributeError):
        d = {}
    checks = d.get("checks") if isinstance(d.get("checks"), dict) else {}
    ts = d.get("ts")
    if d.get("result") != "pass" or not isinstance(ts, (int, float)) or isinstance(ts, bool):
        return False, "no recorded sandbox test (P6-1)"
    if any(checks.get(k) != "pass" for k in P61_LINES):
        return False, "the sandbox test (P6-1) did not pass all seven lines"
    now_ = time.time() if now is None else now
    if ts - now_ > P61_FUTURE_S:
        return False, "the sandbox test (P6-1) is dated in the future (a record written by hand can not be trusted): record it again"        # D14 m6
    if now_ - ts > P61_VALID_S:
        return False, "the sandbox test (P6-1) is older than 30 days"
    return True, "P6-1 pass"


def _user_settings_sandbox():
    """The `sandbox` object of the user's Claude settings (CLAUDE_CONFIG_DIR or ~/.claude), or None."""
    import json
    try:
        with open(os.path.join(os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude"), "settings.json"), encoding="utf-8") as f:
            v = json.load(f).get("sandbox")
        return v if isinstance(v, dict) else None
    except (OSError, ValueError, AttributeError):
        return None


def sandbox_digest(obj) -> str:
    import json
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode("utf-8")).hexdigest()


def sandbox_hash_recorded():
    """The sha256 of the `sandbox` settings the P6-1 test ran with (stored by record_probe), or None (no record, or an older record without it). A widening of that object (excluded commands,
    network or file-system allowances) is a different hash (D14 #7)."""
    import json
    try:
        v = (json.loads(probes_path().read_text()).get("P6-1") or {}).get("sandbox_hash")
    except (OSError, ValueError, AttributeError):
        v = None
    return v if isinstance(v, str) and len(v) == 64 else None


def sandbox_setting() -> str:
    """The Claude Code setting (dotted path) the recorded P6-1 test used (D14 M2): the name written in the record, but only a name in SANDBOX_SETTINGS counts (a forged record cannot point the
    hook check at a key it controls); a record without a name, or no record, gives the default. Read-only."""
    import json
    try:
        v = (json.loads(probes_path().read_text()).get("P6-1") or {}).get("sandbox_setting")
    except (OSError, ValueError, AttributeError):
        v = None
    return v if v in SANDBOX_SETTINGS else SANDBOX_SETTINGS[0]


def record_probe(result, lines, now=None) -> None:
    """Writes <config>/probes.json {P6-1: {result, ts, checks}} (0600, atomic). The caller has confirmed with the owner (gate, typed yes or code, check)."""
    import json
    if result not in ("pass", "fail"):
        raise OwnerRefused("The result must be pass or fail.")
    checks = {k: ("pass" if k in lines else "fail") for k in P61_LINES}
    if result == "pass" and any(v != "pass" for v in checks.values()):
        raise OwnerRefused("A pass needs all seven lines (--lines 1,2,3,4,5,6,7); record fail with the lines that worked, or use a separate user account.")
    p = probes_path()
    cur = {}
    try:
        cur = json.loads(p.read_text())
    except (OSError, ValueError):
        cur = {}
    cur["P6-1"] = {"result": result, "ts": int(time.time() if now is None else now), "checks": checks, "sandbox_setting": SANDBOX_SETTINGS[0]}
    sb = _user_settings_sandbox()
    if sb is not None:
        cur["P6-1"]["sandbox_hash"] = sandbox_digest(sb)
    from . import state as core
    core.ensure_dir(p.parent)
    _write_file(p, json.dumps(cur, sort_keys=True, indent=1) + "\n")


def mark_separate_account() -> str:
    """`shipm owner mark-separate-account`: this user account is a separate one made for autopilot (the owner's own words). Confirmed with the best check that works now (a typed code
    is fine: it lowers nothing on the owner's main account). Creates <config>/throwaway-account."""
    gate("mark-separate-account", "shipm owner mark-separate-account")
    if not account_is_standard():
        raise _refuse("mark-separate-account", "admin_account", TEXTS["not_standard"])
    touch("mark-separate-account", "Shipmiracle: mark this user account as a separate account for autopilot. Cancel if you did not just type this yourself.", setting="basic-ok")
    p = Path(paths.config_dir()) / "throwaway-account"
    from . import state as core
    core.ensure_dir(p.parent)
    _write_file(p, "separate account for autopilot, marked %s\n" % time.strftime("%Y-%m-%d"))
    _event("mark-separate-account", True, "marked")
    return str(p)


def escalate_switch(key, val) -> None:
    """`shipm switch|config set autopilot.<key> <on>`: option C's switch first needs the P6-1 record or the separate-account marker (refused before any prompt); then ONE check:
    basic is enough for the A/B switch, option C needs medium (or basic on a marked separate account)."""
    if key == STANDING_KEY:
        ok, why = standing_allowed()
        if not ok:
            raise OwnerRefused("Option C stays off: %s. Run the sandbox test and record it (docs/owner-steps/p6-autopilot.sh --record-p6-1 pass), or run `shipm owner mark-separate-account` "
                               "on a separate user account." % why)
        confirm("switch", "shipm switch %s on" % key, "Shipmiracle: switch %s on. Cancel if you did not just type this yourself." % key, min_tier="medium", separate_ok=True)
        return
    confirm("switch", "shipm switch %s on" % key, "Shipmiracle: switch %s on. Cancel if you did not just type this yourself." % key)


def escalate_presence_setting(old, new) -> None:
    """Weakening `owner.presence` (strong-only > auto > basic-ok) is confirmed by the best check that works NOW (a dead sensor never locks the owner out; a working sensor cannot be
    skipped). Strengthening needs nothing."""
    order = {"strong-only": 2, "auto": 1, "basic-ok": 0}
    if order.get(new, 1) >= order.get(old, 1):
        return
    confirm("setting", "shipm switch owner.presence %s" % new, "Shipmiracle: weaken the owner check setting to %s. Cancel if you did not just type this yourself." % new, setting="basic-ok")


OWNER_ROW = {
    "strong": ("ok", "Owner check: Touch ID (or Apple Watch)"),
    "medium": ("ok", "Owner check: Mac password dialog (no Touch ID found): all autopilot options work"),
    "basic": ("warn", "Owner check: typed code (no fingerprint or system prompt found). It proves a plausible terminal, not a person: options A and B work; option C needs a separate user account"),
    "none": ("warn", "Owner check: not available on this computer: the autopilot commands that need it stay off (stop, switch-off and show still work)"),
}


def pin_changed():
    """Epoch seconds of the last `owner.helper_built` event (the helper and its pin were rebuilt), or None."""
    try:
        from . import events
        ts = [e.get("ts") for e in events.tail(4000) if e.get("kind") == "owner.helper_built"]
        return int(ts[-1]) if ts else None
    except Exception:
        return None


def row():
    """(level, text) for bin/doctor and the Setup data: what the owner check can do here and the one fix. Never a FAIL (autopilot is off by default)."""
    states = {p.name: p.probe() for p in PROVIDERS}
    name, tier = best()
    mac = [v for k, v in states.items() if k.startswith("macos")]
    if "broken" in mac:
        return "warn", "Owner check: the Touch ID helper changed since it was built: run bin/shipm-presence-build to rebuild it"
    if tier != "strong" and "setup" in mac:
        return "warn", "Owner check: the Touch ID helper is not built: run bin/shipm-presence-build (a few seconds)"
    if presence_setting() == "strong-only" and tier != "strong":
        return "warn", "Owner check: your setting needs Touch ID, which is not available now (lid closed?): stop and switch-off still work"
    lvl, txt = OWNER_ROW[tier]
    pc = pin_changed() if tier in ("strong", "medium") else None
    return lvl, txt + (" (helper last rebuilt %s)" % time.strftime("%Y-%m-%d", time.localtime(pc)) if pc else "")
