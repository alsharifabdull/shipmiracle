#!/usr/bin/env python3
"""shipmiracle/platform.py (the one OS seam) and its callers: kind/describe/case-sensitivity, keep-awake, notifications, host load, pid readers, install hints, the service
interface, the hook callers (activity, limit_wait), shipm-watch `host` with unreadable load, bin/idea and bin/daily on a system without osascript.
Fakes: SHIPMIRACLE_FAKE_OS, SHIPMIRACLE_FAKE_PROC (a folder standing in for /proc), SHIPMIRACLE_NOTIFY; all honoured only under SHIPMIRACLE_TEST=1. Run: python3 tests/platform_test.py"""
import os, pathlib, stat, subprocess, sys, tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import shipmiracle_isolation as ISO  # noqa: E402
ISO.apply_to_environ()
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from shipmiracle import platform as P  # noqa: E402

fails = 0
n = 0


def check(name, ok, info=""):
    global fails, n
    n += 1
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(info)[:500]))
    fails += 0 if ok else 1


T = pathlib.Path(tempfile.mkdtemp(prefix="shipmiracle-plat-")).resolve()
BIN = T / "bin"; BIN.mkdir()
os.environ["PATH"] = str(BIN) + os.pathsep + "/usr/bin:/bin"


def stub(name, body="exit 0"):
    f = BIN / name
    f.write_text("#!/bin/sh\n" + body + "\n"); f.chmod(0o755)
    return str(f)


def fos(k):
    os.environ["SHIPMIRACLE_FAKE_OS"] = k


# ---- kind
for k in ("macos", "linux", "wsl", "windows"):
    fos(k)
    check("kind: SHIPMIRACLE_FAKE_OS=%s is honoured under SHIPMIRACLE_TEST=1" % k, P.kind() == k)
fos("bogus")
check("kind: an unknown fake value is ignored (real OS)", P.kind() in ("macos", "linux", "wsl"))
del os.environ["SHIPMIRACLE_FAKE_OS"]
real = P.kind()
check("kind: real OS is one of the supported kinds here", real in ("macos", "linux", "wsl"), real)
env = {k: v for k, v in os.environ.items() if k != "SHIPMIRACLE_TEST"}; env["SHIPMIRACLE_FAKE_OS"] = "windows"
r = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, %r); from shipmiracle import platform as p; print(p.kind())" % str(ROOT)], env=env, capture_output=True, text=True)
check("kind: without SHIPMIRACLE_TEST=1 the fake is ignored (a stray variable cannot change a real run)", r.stdout.strip() == real, r.stdout + r.stderr)
# WSL detection by osrelease through the fake proc folder
PROC = T / "proc"; (PROC / "sys/kernel").mkdir(parents=True)
(PROC / "sys/kernel/osrelease").write_text("5.15.153.1-microsoft-standard-WSL2\n")
os.environ["SHIPMIRACLE_FAKE_PROC"] = str(PROC)
if sys.platform != "darwin":
    check("kind: osrelease with 'microsoft' means wsl", P.kind() == "wsl", P.kind())
    (PROC / "sys/kernel/osrelease").write_text("6.8.0-31-generic\n")
    check("kind: a normal kernel means linux", P.kind() == "linux", P.kind())
else:
    check("kind: real macOS stays macos even with a fake proc folder", P.kind() == "macos")

# D9 m7: WSL is decided from /proc/sys/kernel/osrelease; the WSL_DISTRO_NAME variable counts only under SHIPMIRACLE_TEST=1 (a stray variable cannot turn a Linux run into WSL)
_old_fp = os.environ.pop("SHIPMIRACLE_FAKE_PROC", None); P._cache.clear()
os.environ["WSL_DISTRO_NAME"] = "Ubuntu"
try:
    seam_on = P._is_wsl()
    P._cache.clear()
    env_ = {k: v for k, v in os.environ.items() if k not in ("SHIPMIRACLE_TEST", "SHIPMIRACLE_FAKE_PROC", "SHIPMIRACLE_FAKE_OS")}
    code = "import sys; sys.path.insert(0, %r); from shipmiracle import platform as p; print(p._is_wsl())" % str(ROOT)
    with_var = subprocess.run([sys.executable, "-c", code], env=env_, capture_output=True, text=True).stdout.strip()
    env_.pop("WSL_DISTRO_NAME")
    without_var = subprocess.run([sys.executable, "-c", code], env=env_, capture_output=True, text=True).stdout.strip()
    check("wsl: the test seam WSL_DISTRO_NAME counts under SHIPMIRACLE_TEST=1", seam_on is True, seam_on)
    check("wsl: outside tests the variable changes nothing (same answer with and without it: %s)" % without_var, with_var == without_var != "", (with_var, without_var))
finally:
    os.environ.pop("WSL_DISTRO_NAME", None); P._cache.clear()
    if _old_fp is not None:
        os.environ["SHIPMIRACLE_FAKE_PROC"] = _old_fp

# ---- describe
(PROC / "os-release").write_text('NAME="Ubuntu"\nVERSION_ID="24.04"\n')
fos("linux")
d = P.describe()
check("describe: one line with OS, version, arch, supported, not here, confirmations", d.startswith("This computer: Ubuntu 24.04 (") and "Supported:" in d and "Not here:" in d and "Confirmations:" in d and "\n" not in d, d)
fos("wsl")
check("describe: WSL names Windows (WSL 2)", "WSL 2" in P.describe(), P.describe())
fos("macos")
check("describe: macOS line", P.describe().startswith("This computer: macOS") and "awake guard" in P.describe(), P.describe())
fos("windows")
check("describe: native Windows is the refusal text (WSL2, nothing changed)", "wsl --install" in P.describe() and "Nothing was changed" in P.describe())

# ---- case sensitivity
fos("macos"); check("case: macOS volumes ignore case", P.case_insensitive("/Users/x/p") is True)
fos("linux"); check("case: Linux is case-sensitive, also under /mnt/c", P.case_insensitive("/home/x/p") is False and P.case_insensitive("/mnt/c/p") is False)
fos("wsl")
check("case: WSL home is case-sensitive, /mnt/<letter>/ is not", P.case_insensitive("/home/x/p") is False and P.case_insensitive("/mnt/c/Users/x") is True and P.case_insensitive("/mnt/d") is True and P.case_insensitive("/mnt/wsl/x") is False and P.case_insensitive("/mnt/cc/x") is False)
check("case: under_windows_mount only on WSL", P.under_windows_mount("/mnt/c/x") is True)
fos("linux"); check("case: under_windows_mount is False on Linux", P.under_windows_mount("/mnt/c/x") is False)

# ---- keep awake
fos("macos")
check("keep-awake: macOS runs exactly caffeinate -i -t N", P.keep_awake_argv(600) == ["caffeinate", "-i", "-t", "600"] and P.keep_awake_argv_from_caffeinate(["-i", "-t", "600"]) == ["caffeinate", "-i", "-t", "600"])
fos("linux")
(PROC / "systemd").mkdir(exist_ok=True)
a = P.keep_awake_argv(90)
check("keep-awake: Linux without systemd-inhibit on PATH is None", a is None, a)
stub("systemd-inhibit")
a = P.keep_awake_argv(90)
check("keep-awake: Linux with systemd-inhibit: argv only, ends with sleep 90", a and a[0].endswith("systemd-inhibit") and a[-2:] == ["sleep", "90"] and "--what=idle:sleep" in a, a)
check("keep-awake: the old caffeinate arguments are translated (-t 600 -> sleep 600)", P.keep_awake_argv_from_caffeinate(["-i", "-t", "600"])[-2:] == ["sleep", "600"])
(PROC / "systemd").rmdir()
check("keep-awake: Linux without a running systemd is None", P.keep_awake_argv(5) is None)
fos("wsl"); check("keep-awake: WSL is None (Windows controls sleep)", P.keep_awake_argv(5) is None and not P.keep_awake_available())
fos("windows"); check("keep-awake: native Windows is None", P.keep_awake_argv(5) is None)

# ---- notifications
bad = 'Hi\nthere\x1b[31m $(rm -rf x) `id` "q" ' + "x" * 400
fos("macos")
os.environ.pop("SHIPMIRACLE_OSASCRIPT", None)
check("notify: in a test run macOS never reaches the real osascript (no recorder = None)", P.notify_argv("t", "m") is None)
rec = stub("osa", 'for a in "$@"; do printf "%s\\n" "$a"; done > ' + str(T / "osa.out"))
os.environ["SHIPMIRACLE_OSASCRIPT"] = rec
av = P.notify_argv("Shipmiracle", bad)
check("notify: macOS argv = osascript with the 4 script parts, then text, then title as ARGUMENTS", av[0] == rec and av[1:7] == ["-e", "on run argv", "-e", "display notification (item 1 of argv) with title (item 2 of argv)", "-e", "end run"] and av[7].startswith("Hi there") and av[8] == "Shipmiracle", av)
check("notify: text cleaned: printable only, at most 200 characters, no newline or escape", len(av[7]) <= 200 and "\n" not in av[7] and "\x1b" not in av[7])
check("notify: nothing from the text is spliced into the script parts", all("rm -rf" not in x for x in av[:7]))
env = {k: v for k, v in os.environ.items() if k != "SHIPMIRACLE_TEST"}; env["SHIPMIRACLE_OSASCRIPT"] = rec; env["SHIPMIRACLE_FAKE_OS"] = "macos"
r = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, %r); from shipmiracle import platform as p; a = p.notify_argv('t', 'm'); print(a[0] if a else None)" % str(ROOT)], env=env, capture_output=True, text=True)
check("notify: SHIPMIRACLE_OSASCRIPT is ignored outside SHIPMIRACLE_TEST=1 (the real program or none, never the variable)", r.stdout.strip() != rec, r.stdout + r.stderr)
fos("linux")
check("notify: Linux without notify-send is None", P.notify_argv("t", "m") is None)
ns = stub("notify-send")
av = P.notify_argv("T", "-rf not an option")
check("notify: Linux notify-send argv has -- before the title so text can never be an option", av[0] == ns and av[-3:] == ["--", "T", "-rf not an option"], av)
fos("wsl"); check("notify: WSL has no system notification (panel only)", P.notify_argv("t", "m") is None)
fos("windows"); check("notify: native Windows has none", P.notify_argv("t", "m") is None)
# wanted: prefs.notify wins, else the old json switch
from shipmiracle import config  # noqa: E402
W = T / "ws"; (W / "config").mkdir(parents=True)
(W / "config/notifications.json").write_text('{"mac": true}')
config._cache.clear()
check("notify wanted: unset preference falls back to config/notifications.json mac:true", P.notify_wanted(W) is True)
(W / "config/notifications.json").write_text('{"mac": false}')
check("notify wanted: mac:false and no preference is off", P.notify_wanted(W) is False)
config.set("prefs.notify", "system")
check("notify wanted: prefs.notify=system turns it on even with the old switch off", P.notify_wanted(W) is True)
config.set("prefs.notify", "vscode")
(W / "config/notifications.json").write_text('{"mac": true}')
check("notify wanted: prefs.notify=vscode wins over the old switch", P.notify_wanted(W) is False)
config.unset("prefs.notify")
fos("macos"); os.environ["SHIPMIRACLE_OSASCRIPT"] = rec
(W / "config/notifications.json").write_text('{"mac": false}')
(T / "osa.out").unlink(missing_ok=True)
check("notify: not wanted means no program runs", P.notify("t", "m", ws=W) is False and not (T / "osa.out").exists())
check("notify: force (the setup test) runs the recorder with the text as an argument", P.notify("Shipmiracle", "hello", ws=W, force=True) is True and "hello" in (T / "osa.out").read_text())
fos("linux"); stub("notify-send", "exit 1")
check("notify: a failing program returns False and never raises", P.notify("t", "m", ws=W, force=True) is False)
os.environ.pop("SHIPMIRACLE_OSASCRIPT", None)

# ---- host load
fos("linux")
(PROC / "loadavg").write_text("3.50 2.00 1.00 1/200 123\n")
(PROC / "meminfo").write_text("MemTotal: 16000000 kB\nMemAvailable: 4000000 kB\nSwapTotal: 2000000 kB\nSwapFree: 500000 kB\n")
(PROC / "cpuinfo").write_text("processor : 0\nprocessor : 1\nprocessor : 2\nprocessor : 3\n")
h = P.host_load()
check("host_load: Linux reads /proc (load, cores, free %, swap %)", h["load"] == 3.5 and h["cores"] == 4 and h["free_pct"] == 25.0 and h["swap_pct"] == 75.0 and h["unknown"] == [], h)
(PROC / "loadavg").unlink()
h = P.host_load()
check("host_load: an unreadable load is None and listed as unknown, never 0", h["load"] is None and "load" in h["unknown"], h)
(PROC / "meminfo").write_text("MemTotal: 100 kB\n")
h = P.host_load()
check("host_load: no MemAvailable / swap lines: unknown, not 0 and not 100", h["free_pct"] is None and h["swap_pct"] is None, h)
(PROC / "meminfo").write_text("MemTotal: 100 kB\nMemAvailable: 50 kB\nSwapTotal: 0 kB\nSwapFree: 0 kB\n")
(PROC / "loadavg").write_text("0.10 0 0 1/1 1\n")
check("host_load: a machine without swap has swap 0 %", P.host_load()["swap_pct"] == 0.0)
if sys.platform == "darwin":
    fos("macos")
    h = P.host_load()
    check("host_load: macOS reads sysctl (real numbers on this Mac)", h["load"] is not None and h["cores"] and h["unknown"] == [], h)
check("claude_tmp_dir: /private/tmp/claude-UID on macOS, /tmp/claude-UID elsewhere", (fos("macos") or P.claude_tmp_dir()).startswith("/private/tmp/claude-") and (fos("linux") or P.claude_tmp_dir()).startswith("/tmp/claude-"))

# ---- pid readers
fos("linux")
(PROC / "4242").mkdir(exist_ok=True)
(PROC / "4242/cwd").write_text("/home/x/Developer/proj\n")
(PROC / "4242/stat").write_text("4242 (my (weird) name) S 100 4242 4242 0 -1\n")
check("pid_cwd: Linux reads the cwd link or file of /proc/PID", P.pid_cwd(4242) == "/home/x/Developer/proj", P.pid_cwd(4242))
os.symlink("/home/x/other", str(PROC / "4242/cwd2"))
(PROC / "4242/cwd").unlink(); os.rename(str(PROC / "4242/cwd2"), str(PROC / "4242/cwd"))
check("pid_cwd: a symlink is read as a link", P.pid_cwd(4242) == "/home/x/other")
check("parent_of: Linux parses /proc/PID/stat even when the name has spaces and parentheses", P.parent_of(4242) == 100, P.parent_of(4242))
check("pid readers: unknown pid, zero, negative and junk give '' / None", P.pid_cwd(99999) == "" and P.pid_cwd(0) == "" and P.pid_cwd(-1) == "" and P.pid_cwd("x") == "" and P.parent_of(99999) is None and P.parent_of("x") is None)
if sys.platform == "darwin":
    fos("macos")
    check("pid readers: macOS (lsof / ps) answer for this very process", P.pid_cwd(os.getpid()) == os.path.realpath(os.getcwd()) and P.parent_of(os.getpid()) == os.getppid(), (P.pid_cwd(os.getpid()), os.getcwd()))

# ---- hints
fos("macos"); check("hint: macOS base is xcode-select, node is brew", "xcode-select --install" in P.install_hint("base") and "brew install node" in P.install_hint("node"))
fos("linux"); check("hint: Linux base is apt (text only)", "sudo apt install git python3" in P.install_hint("base") and "brew" not in P.install_hint("base"))
fos("wsl"); check("hint: WSL code hint names the WSL extension", "WSL" in P.install_hint("code"))
check("hint: unknown tool is empty", P.install_hint("nope") == "")

# ---- service interface
fos("macos"); check("service: macOS backend is launchd", P.service().name == "launchd")
fos("linux"); (PROC / "systemd").mkdir(exist_ok=True)
check("service: Linux without systemctl has no backend", P.service().name == "none")
fos("windows"); check("service: native Windows has none", P.service().name == "none" and P.service().is_loaded("x") is False)

# ---- hook callers
from shipmiracle.hooks import activity, limit_wait  # noqa: E402
fos("macos")
(BIN / "caffeinate").write_text("#!/bin/sh\nsleep 1\n"); (BIN / "caffeinate").chmod(0o755)
pf = str(T / "pid")
check("hooks: spawn_caffeinate on macOS starts caffeinate (same argv) and records the pid", activity.spawn_caffeinate(["-i", "-t", "600"], pf) is True and pathlib.Path(pf).read_text().strip().isdigit())
fos("wsl")
check("hooks: spawn_caffeinate on WSL returns False and starts nothing", activity.spawn_caffeinate(["-i", "-t", "600"], str(T / "pid2")) is False and not (T / "pid2").exists())


class Ctx:
    def __init__(self, cfg): self.cfg = cfg; self.env = {"TMPDIR": str(T)}
    def config(self, k, d=None): return self.cfg.get(k, d)


fos("macos")
(T / "shipmiracle-keep-awake.pid").unlink(missing_ok=True)
check("hooks: keep_awake with prefs.keep_awake=false does nothing (no process, no pid file)", activity.keep_awake(Ctx({"prefs.keep_awake": False})) is None and not (T / "shipmiracle-keep-awake.pid").exists())
res = activity.keep_awake(Ctx({}))
check("hooks: keep_awake with the preference unset still keeps the Mac awake (today's behaviour)", res is not None and res.effects == ["caffeinate -i -t 600"], res)
check("hooks: keep_awake with prefs.keep_awake=true too", activity.keep_awake(Ctx({"prefs.keep_awake": True})) is not None)

# ---- shipm-watch host with an unreadable machine
E1, root = ISO.isolated_env()
E1.update(SHIPMIRACLE_FAKE_OS="linux", SHIPMIRACLE_FAKE_PROC=str(T / "emptyproc"))
(T / "emptyproc").mkdir()
r = subprocess.run([str(ROOT / "bin/shipm-watch"), "host", "--heavy-ok"], env=E1, capture_output=True, text=True, stdin=subprocess.DEVNULL)
check("shipm-watch host --heavy-ok: unreadable load is 'unknown', exit 1 (never 'ok' or exit 0)", r.returncode == 1 and r.stdout.startswith("unknown:") and "load" in r.stdout, (r.returncode, r.stdout, r.stderr[-200:]))
(T / "emptyproc/loadavg").write_text("0.20 0 0 1/1 1\n"); (T / "emptyproc/meminfo").write_text("MemTotal: 100 kB\nMemAvailable: 80 kB\nSwapTotal: 0 kB\nSwapFree: 0 kB\n")
(T / "emptyproc/cpuinfo").write_text("processor : 0\nprocessor : 1\n")
r = subprocess.run([str(ROOT / "bin/shipm-watch"), "host", "--heavy-ok"], env=E1, capture_output=True, text=True, stdin=subprocess.DEVNULL)
check("shipm-watch host --heavy-ok: readable and quiet Linux box: ok, exit 0", r.returncode == 0 and r.stdout.strip() == "ok", (r.returncode, r.stdout, r.stderr[-200:]))
(T / "emptyproc/loadavg").write_text("9.00 0 0 1/1 1\n")
r = subprocess.run([str(ROOT / "bin/shipm-watch"), "host", "--heavy-ok"], env=E1, capture_output=True, text=True, stdin=subprocess.DEVNULL)
check("shipm-watch host --heavy-ok: load 9 on 2 cores: busy, exit 1 with the reason", r.returncode == 1 and "load 9.0 on 2 cores" in r.stdout, (r.returncode, r.stdout))
ISO.cleanup(root)

# ---- bin/daily and bin/idea on a system without osascript
E2, root2 = ISO.isolated_env()
E2["SHIPMIRACLE_FAKE_OS"] = "linux"; E2["SHIPMIRACLE_NOTIFY"] = stub("notify-rec", 'for a in "$@"; do printf "%s\\n" "$a"; done > ' + str(T / "ns.out")); E2["PATH"] = str(BIN) + os.pathsep + "/usr/bin:/bin"
code = ("import sys; sys.path.insert(0, %r); from shipmiracle import platform as p; p.main(['notify', 'Shipmiracle daily', 'Health: 0 problems'])" % str(ROOT))
subprocess.run([sys.executable, "-c", code], env=E2, cwd=str(ROOT))
check("daily/idea path: python3 -m shipmiracle.platform notify does nothing when notifications are not wanted", not (T / "ns.out").exists())
import json  # noqa: E402
cfgdir = pathlib.Path(E2["SHIPMIRACLE_CONFIG"]); (cfgdir / "config.json").write_text(json.dumps({"prefs.notify": "system"}))
subprocess.run([sys.executable, "-c", code], env=E2, cwd=str(ROOT))
out = (T / "ns.out").read_text() if (T / "ns.out").exists() else ""
check("daily/idea path: with prefs.notify=system the Linux notifier gets title and text as arguments", "Health: 0 problems" in out and "Shipmiracle daily" in out, out)
r = subprocess.run([sys.executable, "-m", "shipmiracle.platform", "nonsense"], env=E2, cwd=str(ROOT), capture_output=True, text=True)
check("python3 -m shipmiracle.platform with bad arguments: usage, exit 2", r.returncode == 2 and "usage" in r.stderr)
ISO.cleanup(root2)
check("no module-level subprocess or Shipmiracle import in platform.py (hook path stays light)", "import subprocess" not in open(ROOT / "shipmiracle/platform.py").read().split("def ")[0] and "from . import" not in open(ROOT / "shipmiracle/platform.py").read().split("def ")[0])

print("\n%d checks" % n)
print("\nFAILED: %d" % fails if fails else "\nALL PASS")
sys.exit(1 if fails else 0)
