"""The one seam for operating-system differences (plan docs/plans/2026-10-21-cross-platform-onboarding.md, section 3.2). Stdlib only; nothing from the rest of
Shipmiracle is imported at the top, no subprocess runs at import, and `kind()` on the hook path is `sys.platform` only. macOS branches run exactly the commands the
code ran before this module existed; Linux/WSL2 branches only add. Shipmiracle never runs a package manager or sudo: `install_hint` only returns text.

Supported: macOS (first-class), Linux and Windows through WSL2 (best effort). Native Windows is refused (`windows`), see `refusal_text()`.

Test seams (honoured only when SHIPMIRACLE_TEST=1, so a stray variable can never change what a real run does):
  SHIPMIRACLE_FAKE_OS    macos | linux | wsl | windows         which OS kind() reports
  SHIPMIRACLE_FAKE_PROC  a folder that stands in for /proc (loadavg, meminfo, osrelease, <pid>/cwd, <pid>/stat) and holds `os-release` for /etc/os-release
  SHIPMIRACLE_NOTIFY     the program used instead of notify-send
SHIPMIRACLE_OSASCRIPT (a recorder standing in for osascript) is honoured under SHIPMIRACLE_TEST=1 only. Notification text is cut to 200 characters and the title to 60 (the daily health line is about 130)."""
from __future__ import annotations

import os
import shutil
import sys

KINDS = ("macos", "linux", "wsl", "windows")
_cache = {}


def _testing() -> bool:
    return os.environ.get("SHIPMIRACLE_TEST") == "1"


def _fake(var):
    return os.environ.get(var) if _testing() and os.environ.get(var) else None


def _proc_root() -> str:
    return _fake("SHIPMIRACLE_FAKE_PROC") or "/proc"


def _read(path, limit=65536) -> str:
    try:
        with open(path, "r", errors="replace") as f:
            return f.read(limit)
    except OSError:
        return ""


def _is_wsl() -> bool:
    if "wsl" in _cache and not _fake("SHIPMIRACLE_FAKE_PROC"):
        return _cache["wsl"]
    rel = _read(os.path.join(_proc_root(), "sys", "kernel", "osrelease") if _fake("SHIPMIRACLE_FAKE_PROC") else "/proc/sys/kernel/osrelease")
    if not rel and _fake("SHIPMIRACLE_FAKE_PROC"):
        rel = _read(os.path.join(_proc_root(), "osrelease"))
    # WSL is decided from the kernel release; the WSL_DISTRO_NAME variable is a test seam only (a variable inherited from another environment must not turn a Linux run into WSL)
    val = "microsoft" in rel.lower() or (_testing() and bool(os.environ.get("WSL_DISTRO_NAME")) and not _fake("SHIPMIRACLE_FAKE_PROC"))
    if not _fake("SHIPMIRACLE_FAKE_PROC"):
        _cache["wsl"] = val
    return val


def kind() -> str:
    """macos | linux | wsl | windows. The hook path never gets further than the `sys.platform` test on a Mac."""
    f = _fake("SHIPMIRACLE_FAKE_OS")
    if f in KINDS:
        return f
    if sys.platform == "darwin":
        return "macos"
    if os.name == "nt" or sys.platform.startswith(("win", "cygwin")):
        return "windows"
    return "wsl" if _is_wsl() else "linux"


def is_posix_supported() -> bool:
    return kind() != "windows"


# ------------------------------------------------------------------ describe
_SUPPORT = {
    "macos": ("CLI, hooks, panel, autopilot, awake guard", "nothing"),
    "linux": ("CLI, hooks, panel, autopilot, keep awake", "awake guard, iOS tools"),
    "wsl": ("CLI, hooks, panel, autopilot", "awake guard, iOS tools, keep awake (Windows controls sleep), system pop-ups"),
    "windows": ("nothing yet", "everything: run Shipmiracle inside WSL 2"),
}


def _release_line() -> str:
    """A short OS name and version for the one-line description (read once per process)."""
    if "release" in _cache and not _testing():
        return _cache["release"]
    k = kind()
    txt = ""
    if k == "macos":
        if sys.platform == "darwin" and not _fake("SHIPMIRACLE_FAKE_OS"):
            import subprocess
            try:
                r = subprocess.run(["/usr/bin/sw_vers", "-productVersion"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, timeout=3)
                v = r.stdout.decode("utf-8", "replace").strip()
                txt = "macOS %s" % v if v else "macOS"
            except (OSError, ValueError, subprocess.SubprocessError):
                txt = "macOS"
        else:
            txt = "macOS"
    elif k == "windows":
        txt = "Windows (native)"
    else:
        osr = os.path.join(_fake("SHIPMIRACLE_FAKE_PROC"), "os-release") if _fake("SHIPMIRACLE_FAKE_PROC") else "/etc/os-release"
        d = {}
        for line in _read(osr).splitlines():
            if "=" in line and not line.startswith("#"):
                a, _, b = line.partition("=")
                d[a.strip()] = b.strip().strip('"')
        txt = d.get("NAME") or "Linux"
        if d.get("VERSION_ID"):
            txt += " " + d["VERSION_ID"]
        if k == "wsl":
            txt += " on Windows (WSL 2)"
    _cache["release"] = txt
    return txt


def _arch() -> str:
    try:
        return os.uname().machine
    except AttributeError:
        return "unknown"


def _presence_text() -> str:
    """What confirms the owner's identity here, read from shipmiracle.owner.provider() (owned by the owner-proof work); text only, never raises."""
    try:
        from . import owner
        p = owner.provider()
        tier = getattr(p, "tier", "none")
        name = getattr(p, "name", "none")
    except Exception:
        return "not checked"
    if tier == "none":
        return "not available yet"
    return "%s (%s)" % ("Touch ID" if "touchid" in str(name) else str(name), tier)


def describe() -> str:
    """One line: 'This computer: Ubuntu 24.04 (x86_64). Supported: .... Not here: .... Confirmations: password (basic).'"""
    k = kind()
    if k == "windows":
        return refusal_text()
    sup, no = _SUPPORT[k]
    return "This computer: %s (%s). Supported: %s. Not here: %s. Confirmations: %s." % (_release_line(), _arch(), sup, no, _presence_text())


def refusal_text() -> str:
    return ('This computer: Windows 11 (native). Shipmiracle runs inside WSL2 here: run "wsl --install", open Ubuntu, then install Shipmiracle there. '
            "Nothing was changed.")


# ------------------------------------------------------------------ file system
def case_insensitive(path) -> bool:
    """True when `path` lives on a file system that ignores case. macOS: True (the default volume format). Linux: False. WSL: True under /mnt/<letter>/
    (NTFS through drvfs). Windows: True."""
    k = kind()
    if k in ("macos", "windows"):
        return True
    if k == "wsl":
        p = os.path.normpath(str(path))
        parts = p.split("/")
        return len(parts) > 2 and parts[0] == "" and parts[1] == "mnt" and len(parts[2]) == 1 and parts[2].isalpha()
    return False


def under_windows_mount(path) -> bool:
    """WSL only: the path is on a Windows drive (/mnt/c/...), which shipm refuses as a projects folder."""
    return kind() == "wsl" and case_insensitive(path)


# ------------------------------------------------------------------ keep awake
def systemd_running() -> bool:
    if _fake("SHIPMIRACLE_FAKE_OS"):
        return True if _fake("SHIPMIRACLE_FAKE_PROC") is None else os.path.isdir(os.path.join(_fake("SHIPMIRACLE_FAKE_PROC"), "systemd"))
    return os.path.isdir("/run/systemd/system")


def _which(name):
    if _testing():
        return shutil.which(name, path=os.environ.get("PATH", ""))
    return shutil.which(name)


def keep_awake_argv(secs):
    """The argv that keeps the computer awake for `secs` seconds, or None when this system cannot do it. macOS: the same caffeinate call as before."""
    secs = max(1, int(secs))
    k = kind()
    if k == "macos":
        return ["caffeinate", "-i", "-t", str(secs)]
    if k == "linux" and systemd_running():
        exe = _which("systemd-inhibit")
        if exe:
            return [exe, "--what=idle:sleep", "--who=shipmiracle", "--why=Claude is working", "sleep", str(secs)]
    return None


def keep_awake_available() -> bool:
    return keep_awake_argv(1) is not None


def keep_awake_argv_from_caffeinate(args):
    """Hook helper: `args` are the old caffeinate arguments (['-i', '-t', '600']). macOS: ['caffeinate'] + args, unchanged. Elsewhere the seconds are
    read from `-t N` and the platform's own command is used (None when there is none)."""
    if kind() == "macos":
        return ["caffeinate"] + list(args)
    a = list(args)
    secs = 600
    if "-t" in a and a.index("-t") + 1 < len(a) and str(a[a.index("-t") + 1]).isdigit():
        secs = int(a[a.index("-t") + 1])
    return keep_awake_argv(secs)


# ------------------------------------------------------------------ notifications
def clean_text(text, limit=200) -> str:
    """Printable characters only (newlines become spaces), at most `limit` characters; used for notification text."""
    s = "".join(c if c.isprintable() else " " for c in str(text))
    return " ".join(s.split())[:limit]


def notify_argv(title, text):
    """argv of the system notification program, or None. macOS: the osascript call (the text goes in as an argument, never into the script). Linux:
    notify-send. WSL and Windows: None (the VS Code panel is the notification there)."""
    t, m = clean_text(title, 60), clean_text(text, 200)
    k = kind()
    if k == "macos":
        if _testing():          # a test run never reaches the real osascript (a real pop-up); SHIPMIRACLE_OSASCRIPT names a recorder and counts ONLY under SHIPMIRACLE_TEST=1
            exe = os.environ.get("SHIPMIRACLE_OSASCRIPT")
            if not exe:
                return None
        else:
            exe = "/usr/bin/osascript"
        return [exe, "-e", "on run argv", "-e", "display notification (item 1 of argv) with title (item 2 of argv)", "-e", "end run", m, t]
    if k == "linux":
        exe = _fake("SHIPMIRACLE_NOTIFY") or _which("notify-send")
        if exe:
            return [exe, "--app-name=Shipmiracle", "--", t, m]
    return None


def notify_wanted(ws=None) -> bool:
    """prefs.notify = system turns system pop-ups on; vscode or none turn them off. Unset: the old switch config/notifications.json {"mac": true}."""
    try:
        from . import config
        pref = config.get("prefs.notify", None)
    except Exception:
        pref = None
    if pref is not None:
        return pref == "system"
    try:
        import json
        if ws is None:
            from . import paths
            ws = paths.workspace_dir()
        with open(os.path.join(str(ws), "config", "notifications.json"), "r") as f:
            d = json.load(f)
        return bool(isinstance(d, dict) and d.get("mac"))
    except Exception:
        return False


def notify(title, text, ws=None, force=False) -> bool:
    """Send one system notification when wanted (or `force`, for the setup test). Never raises, never blocks more than 10 s. True when a program ran."""
    if not force and not notify_wanted(ws):
        return False
    argv = notify_argv(title, text)
    if argv is None:
        return False
    import subprocess
    try:
        r = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0


# ------------------------------------------------------------------ host load and process readers
def _run(argv, timeout=4) -> str:
    import subprocess
    try:
        r = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
        return r.stdout.decode("utf-8", "replace") if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def host_load() -> dict:
    """{'load': float|None, 'cores': int|None, 'swap_pct': float|None, 'free_pct': float|None, 'unknown': [names]}. A value that could not be read is None
    and listed under 'unknown': it is never reported as 0 (so 'quiet' is never said about a machine nobody could read)."""
    import re
    h = {"load": None, "cores": None, "swap_pct": None, "free_pct": None}
    k = kind()
    if k == "macos":
        o = _run(["/usr/sbin/sysctl", "-n", "vm.swapusage"]); m = re.search(r"total = ([\d.]+)M\s+used = ([\d.]+)M", o)
        if m:
            h["swap_pct"] = round(100 * float(m.group(2)) / float(m.group(1)), 1) if float(m.group(1)) > 0 else 0.0
        o = _run(["/usr/sbin/sysctl", "-n", "vm.loadavg"]); m = re.search(r"([\d.]+)", o)
        if m:
            h["load"] = float(m.group(1))
        o = _run(["/usr/sbin/sysctl", "-n", "hw.ncpu"])
        if o.strip().isdigit():
            h["cores"] = int(o.strip())
        o = _run(["/usr/sbin/sysctl", "-n", "hw.memsize"]); mem = int(o.strip()) if o.strip().isdigit() else 0
        o = _run(["/usr/bin/vm_stat"])
        pg = re.search(r"page size of (\d+)", o); free = sum(int(x) for x in re.findall(r"Pages (?:free|inactive|speculative):\s+(\d+)", o))
        if mem and pg:
            h["free_pct"] = round(100 * free * int(pg.group(1)) / mem, 1)
    elif k in ("linux", "wsl"):
        root = _proc_root()
        m = re.match(r"\s*([\d.]+)", _read(os.path.join(root, "loadavg")))
        if m:
            h["load"] = float(m.group(1))
        mi = {}
        for line in _read(os.path.join(root, "meminfo")).splitlines():
            mm = re.match(r"(\w+):\s+(\d+)", line)
            if mm:
                mi[mm.group(1)] = int(mm.group(2))
        if mi.get("MemTotal"):
            avail = mi.get("MemAvailable")
            if avail is not None:
                h["free_pct"] = round(100 * avail / mi["MemTotal"], 1)
        if "SwapTotal" in mi:
            h["swap_pct"] = round(100 * (mi["SwapTotal"] - mi.get("SwapFree", mi["SwapTotal"])) / mi["SwapTotal"], 1) if mi["SwapTotal"] > 0 else 0.0
        n = os.cpu_count()
        if _fake("SHIPMIRACLE_FAKE_PROC"):
            n = None
            c = _read(os.path.join(root, "cpuinfo"))
            if c:
                n = len([1 for ln in c.splitlines() if ln.startswith("processor")]) or None
        h["cores"] = n
    h["unknown"] = [x for x in ("load", "cores", "swap_pct", "free_pct") if h[x] is None]
    return h


def claude_tmp_dir() -> str:
    """Where Claude Code keeps its per-user temp folder: /private/tmp/claude-UID on macOS, /tmp/claude-UID elsewhere."""
    uid = os.getuid() if hasattr(os, "getuid") else 0
    return ("/private/tmp/claude-%d" if kind() == "macos" else "/tmp/claude-%d") % uid


def pid_cwd(pid) -> str:
    """Working folder of process `pid`, or '' when unknown. Reader only; whether to trust it is the caller's policy. macOS: lsof (as before). Linux: /proc/PID/cwd."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return ""
    if pid <= 0:
        return ""
    if kind() == "macos":
        import re
        o = _run(["/usr/sbin/lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"])
        m = re.search(r"\nn(.+)", o)
        return m.group(1) if m else ""
    p = os.path.join(_proc_root(), str(pid), "cwd")
    try:
        if os.path.islink(p):
            return os.readlink(p)
        return _read(p, 4096).strip()
    except OSError:
        return ""


def parent_of(pid):
    """Parent pid of `pid`, or None when unknown. macOS: ps (as before). Linux: field 4 of /proc/PID/stat (the name in parentheses may hold spaces)."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return None
    if pid <= 0:
        return None
    if kind() == "macos":
        o = _run(["/bin/ps", "-o", "ppid=", "-p", str(pid)]).strip()
        return int(o) if o.isdigit() else None
    s = _read(os.path.join(_proc_root(), str(pid), "stat"), 4096)
    i = s.rfind(")")
    if i < 0:
        return None
    f = s[i + 1:].split()
    return int(f[1]) if len(f) > 1 and f[1].isdigit() else None


# ------------------------------------------------------------------ background services
class Service:
    """The interface of a user-level background job manager. `name` is launchd or systemd; calls go through shipmiracle.setup.call (the SHIPMIRACLE_SETUP_BIN test seam)."""
    name = "none"

    def available(self) -> bool:
        return False

    def is_loaded(self, label) -> bool:
        return False

    def load(self, label, unit_path):
        """(returncode, stderr)"""
        return 127, "no service manager"

    def unload(self, label):
        return 127, "no service manager"


class Launchd(Service):
    name = "launchd"

    def available(self) -> bool:
        from . import setup
        return setup.tool("launchctl") is not None

    def is_loaded(self, label) -> bool:
        from . import setup
        return setup.call("launchctl", ["print", "gui/%d/%s" % (os.getuid(), label)])[0] == 0

    def load(self, label, unit_path):
        from . import setup
        rc, _, err = setup.call("launchctl", ["bootstrap", "gui/%d" % os.getuid(), str(unit_path)])
        return rc, err

    def unload(self, label):
        from . import setup
        rc, _, err = setup.call("launchctl", ["bootout", "gui/%d/%s" % (os.getuid(), label)])
        return rc, err


class SystemdUser(Service):
    """Interface only in this round: the unit files and the daily timer are plan task 7."""
    name = "systemd"

    def available(self) -> bool:
        from . import setup
        return systemd_running() and setup.tool("systemctl") is not None

    def is_loaded(self, label) -> bool:
        from . import setup
        return setup.call("systemctl", ["--user", "is-active", "--quiet", label + ".timer"])[0] == 0

    def load(self, label, unit_path):
        from . import setup
        rc, _, err = setup.call("systemctl", ["--user", "enable", "--now", label + ".timer"])
        return rc, err

    def unload(self, label):
        from . import setup
        rc, _, err = setup.call("systemctl", ["--user", "disable", "--now", label + ".timer"])
        return rc, err


def service() -> Service:
    k = kind()
    if k == "macos":
        return Launchd()
    if k in ("linux", "wsl"):
        s = SystemdUser()
        return s if s.available() else Service()
    return Service()


# ------------------------------------------------------------------ install hints (text only; Shipmiracle never runs a package manager or sudo)
_HINTS = {
    "base": {"macos": "xcode-select --install   (a macOS window opens; python3 3.9+ comes with it)",
             "linux": "sudo apt install git python3   (Fedora: sudo dnf install git python3)",
             "wsl": "sudo apt install git python3   (Fedora: sudo dnf install git python3)"},
    "node": {"macos": "brew install node   (Node 18 or newer; Shipmiracle never runs brew)",
             "linux": "Node 18 or newer: sudo apt install nodejs npm, or nvm (https://github.com/nvm-sh/nvm)",
             "wsl": "Node 18 or newer: sudo apt install nodejs npm, or nvm (https://github.com/nvm-sh/nvm)"},
    "gh": {"macos": "brew install gh", "linux": "sudo apt install gh   (or https://cli.github.com)", "wsl": "sudo apt install gh   (or https://cli.github.com)"},
    "gitleaks": {"macos": "brew install gitleaks", "linux": "download a release from https://github.com/gitleaks/gitleaks/releases (or your package manager)",
                 "wsl": "download a release from https://github.com/gitleaks/gitleaks/releases (or your package manager)"},
    "docker": {"macos": "install Colima and Docker (brew install colima docker)", "linux": "install Docker Engine (https://docs.docker.com/engine/install/)",
               "wsl": "turn on Docker Desktop's WSL integration"},
    "code": {"macos": "in VS Code: Shell Command: Install 'code' command in PATH", "linux": "install VS Code (https://code.visualstudio.com), then check that `code` is on your PATH",
             "wsl": "install VS Code on Windows plus its WSL extension, then run `code .` once from this Ubuntu terminal (not verified by shipm)"},
}


def install_hint(tool_id) -> str:
    h = _HINTS.get(tool_id, {})
    return h.get(kind()) or h.get("linux") or ""


def main(argv=None) -> int:
    """`python3 -m shipmiracle.platform notify TITLE TEXT [WORKSPACE]`: used by bin/daily on every system. Honours prefs.notify; always exits 0."""
    a = list(sys.argv[1:] if argv is None else argv)
    if len(a) >= 3 and a[0] == "notify":
        notify(a[1], a[2], ws=a[3] if len(a) > 3 else None)
        return 0
    if a[:1] == ["describe"]:
        sys.stdout.write(describe() + "\n")
        return 0
    sys.stderr.write("usage: python3 -m shipmiracle.platform notify TITLE TEXT | describe\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
