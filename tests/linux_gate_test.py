#!/usr/bin/env python3
"""linux_gate_test: the Linux additions to the gate deny lists (plan docs/plans/2026-10-21-cross-platform-onboarding.md task 3, checklist E6).
Both gate copies (the legacy shell gate where it exists, and shipmiracle/hooks/flow.py through the v1 shim) and the autopilot hard stop must refuse the Linux launchers
(systemd-run, xdg-open of an executable, secret-tool, dbus-send, gdbus/busctl call, zenity --entry, kdialog --inputbox, terminal emulators with -e), refuse clipboard / pop-up
tools only when the text names shipm or claude (the osascript style), and keep ordinary uses allowed. Write of the Linux user site-packages, the macOS user site-packages
spelled on Linux, and ~/.local/share/shipmiracle is refused. fold() is case-insensitive on a WSL Windows drive (/mnt/c) and case-sensitive on plain Linux paths.
Run: python3 tests/linux_gate_test.py"""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import shipmiracle_isolation; shipmiracle_isolation.apply_to_environ()   # test isolation
import json, os, pathlib, re, subprocess, sys, tempfile
from concurrent.futures import ThreadPoolExecutor

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import flow_fixture as F
from flow_fixture import deny, text
from shipmiracle.autopilot import hardstop as H

fails = []


def check(name, ok, info=""):
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(info)[:500]))
    if not ok:
        fails.append(name)


DENIED = [
    # code that runs outside this chat's process tree
    "systemd-run --user sleep 100", "systemd-run --user --on-calendar=daily ./job.sh", "env systemd-run --user true",
    "xdg-open run.sh", "xdg-open app.desktop", "xdg-open Tool.AppImage", "gio open install.sh",
    "gnome-terminal -- ls", "xterm -e ls", "konsole -e ls", "x-terminal-emulator -e ls", "xfce4-terminal --command=ls", "tilix -e ls",
    # keyring, session bus, fake prompts
    "secret-tool lookup service github", "secret-tool store --label=x a b", "dbus-send --session --dest=org.x /org/x org.x.Run",
    "gdbus call --session --dest org.x --object-path /org/x --method org.x.Run", "busctl --user call org.x /org/x org.x Run",
    "zenity --entry --text 'password?'", "zenity --password", "kdialog --inputbox 'password?'", "kdialog --password x",
    # clipboard, pop-ups and openers that name the command shipm (the osascript rule)
    "xclip -selection clipboard <<< 'shipm autopilot start'", "xsel -b <<< 'shipm sync'", "wl-copy 'shipm autopilot start'", "notify-send 'run shipm autopilot start'",
    "kdialog --msgbox 'shipm sync'", "zenity --info --text 'shipm sync'", "xdg-open 'shipm sync'", "loginctl enable-linger; shipm sync",
]
ALLOWED = [
    "notify-send done", "xdg-open https://example.com", "xclip -o", "wl-paste", "gdbus introspect --session --dest org.x --object-path /org/x", "zenity --info --text hi",
    "kdialog --msgbox hi", "gnome-terminal --version", "systemd-analyze verify x.service", "xdg-open README", "gio trash old.txt", "ls ~/.config/systemd/user",
    "xclip -selection clipboard < notes.txt", "wl-copy < notes.txt",
]
# the hard stop refuses every launcher in any form (by design): only the names the gate lets through conditionally differ
HS_ONLY_DENIED = ["notify-send done", "xclip -o", "wl-paste", "gdbus introspect --session --dest org.x --object-path /org/x", "zenity --info --text hi", "kdialog --msgbox hi",
                  "xclip -selection clipboard < notes.txt", "wl-copy < notes.txt"]

p = F.make_project()
p.put("src/a.py", "x\n")
p.prompt()
IMPLS = []
if F.LEGACY_HOOK.exists():
    IMPLS.append(("legacy shell gate", str(F.LEGACY_HOOK)))
IMPLS.append(("v1 gate (shipmiracle/hooks/flow.py)", str(F.V1_HOOK)))
cnt = [0]


def run_cmd(hook, cmd):
    cnt[0] += 1
    d = {"hook_event_name": "PreToolUse", "session_id": "l%d" % cnt[0], "cwd": str(p.P), "tool_name": "Bash", "tool_input": {"command": cmd}}
    r = subprocess.run(["bash", hook], input=json.dumps(d), capture_output=True, text=True, env=p.ENV, cwd=str(p.P))
    try:
        return json.loads(r.stdout) if r.stdout.strip() else {}
    except Exception:
        return {"raw": r.stdout, "err": r.stderr}


for label, hook in IMPLS:
    with ThreadPoolExecutor(6) as ex:
        den = list(ex.map(lambda c: run_cmd(hook, c), DENIED))
        alw = list(ex.map(lambda c: run_cmd(hook, c), ALLOWED))
    for c, o in zip(DENIED, den):
        check("%s DENIED: %r" % (label, c[:60]), deny(o) and "Traceback" not in text(o), o)
    for c, o in zip(ALLOWED, alw):
        check("%s ALLOWED: %r" % (label, c[:60]), not deny(o), o)
check("hook errors log stays empty", p.errors() == "", p.errors())

# ------------------------------------------------------------------ the autopilot hard stop
WT = pathlib.Path(tempfile.mkdtemp()).resolve() / "dev" / ".worktrees" / "sandbox" / "auto-CR-012"
WT.mkdir(parents=True)
(WT / "src").mkdir(); (WT / "src/a.py").write_text("x\n")
HOME = os.path.realpath(os.environ["HOME"])


def hs(cmd):
    c = H.Ctx(root=str(WT), base_sha="abc123", scope=["src/**"], tracked=lambda rel: ["src/a.py"], changed=set(), read_text=lambda r: None, added_text=lambda r: None,
              home=HOME, tmp_roots=["/tmp", "/private/tmp"], active_cr="CR-012", ends=["CR-012"], auto_branch="auto/CR-012", ahead=1)
    return H.check("PreToolUse", "Bash", {"command": cmd}, str(WT), c)


H.RAISE = True
for c in DENIED + HS_ONLY_DENIED:
    got = hs(c)
    check("hard stop DENIED: %r" % c[:60], bool(got) and any(s.rule == "H5" for s in got), [s.rule for s in got])
from shipmiracle.autopilot import rules as R
flag = lambda line: [name for name, rx, rule in R.FORBIDDEN if rx.search(line)]
for line, want in (("subprocess.run(['systemd-run', '--user', 'x'])", "systemd-run"), ("os.system('secret-tool lookup a b')", "secret-tool")):
    check("diff scanner flags %r" % line[:50], want in flag(line), flag(line))
check("diff scanner does not flag a plain sentence", flag("systemd runs the timer; the secret tools stay out") == [], flag("systemd runs the timer; the secret tools stay out"))
for c in ("xclip -o", "wl-paste", "xsel -b", "wl-copy < notes.txt", "systemd-run --user true", "secret-tool lookup a b"):
    check("persist table (rules.PERSIST_CMDS) names %s" % c.split()[0], c.split()[0] in R.PERSIST_CMDS)
for c in ("ls src", "cat src/a.py", "git status"):
    check("hard stop ALLOWED: %r" % c, not hs(c), [(s.rule, s.text[:60]) for s in hs(c)])
for c in ("echo x > %s/.config/systemd/user/x.service" % HOME, "cp x %s/.config/autostart/x.desktop" % HOME, "echo x > %s/.local/lib/python3.9/site-packages/z.pth" % HOME,
          "echo x > %s/.local/share/shipmiracle/x" % HOME):
    got = hs(c)
    check("hard stop refuses a write to a Linux persistence folder: %r" % c[:70].replace(HOME, "~"), bool(got), [s.rule for s in got])

# ------------------------------------------------------------------ protected paths (Write)
home = os.environ["HOME"]
PATHS_DENIED = ["~/.local/lib/python3.9/site-packages/zz.pth", "~/.local/lib/python3.12/site-packages/sub/x.py", "~/Library/Python/3.9/lib/python/site-packages/zz.pth",
                "~/library/python/3.9/lib/python/site-packages/zz.pth", "~/.local/share/shipmiracle/x", "~/.config/shipmiracle/x",
                "~/.CONFIG/SHIPMIRACLE/x", "~/.config/\u017fhipmiracle/x", "~/.Local/Share/Shipmiracle/x", "~/.local/lib/PYTHON3.12/site-packages/x.pth",       # pfold: folded on every OS (long s, case)
                "~/.config/systemd/user/x.service", "~/.CONFIG/Autostart/x.desktop", "~/.config/environment.d/10-x.conf"]                                       # D9 M1: user units, autostart, session environment
for label, hook in IMPLS:
    F.HOOK = type("H", (), {"__str__": lambda s, h=hook: h, "__fspath__": lambda s, h=hook: h})()
    for tmpl in PATHS_DENIED:
        for agent in (False, True):
            o = p.pre("Write", {"file_path": tmpl.replace("~", home), "content": "x"}, sid="lw%d" % cnt[0], agent="backend-engineer" if agent else None)
            cnt[0] += 1
            check("%s Write %s%s is refused" % (label, tmpl, " (agent)" if agent else ""), deny(o), o)

# ------------------------------------------------------------------ fold(): WSL drive letters ignore case, plain Linux paths do not (both copies)
src = F.gate_source()
m = re.search(r"^def _ci_drive\(p\):.*?^def relto", src, re.M | re.S)
check("the gate source defines _ci_drive and fold", m is not None)
for label, gsrc in [("gate source", src)] + ([("legacy shell gate", F.LEGACY_HOOK.read_text())] if F.LEGACY_HOOK.exists() else []):
    mm = re.search(r"^def _ci_drive\(p\):.*?^def relto", gsrc, re.M | re.S)
    if not mm:
        check(label + ": fold block found", False)
        continue
    for fake, path, want in [("wsl", "/mnt/C/Users/Someone/Proj", "/mnt/c/users/someone/proj"), ("wsl", "/mnt/c", "/mnt/c"), ("wsl", "/home/Me/Proj", "/home/Me/Proj"),
                             ("wsl", "/mnt/cc/Proj", "/mnt/cc/Proj"), ("wsl", "/mnt/wsl/Proj", "/mnt/wsl/Proj"),
                             ("linux", "/mnt/C/Users/Someone", "/mnt/C/Users/Someone"), ("linux", "/home/Me/Proj", "/home/Me/Proj")]:
        ns = {"os": os, "re": re, "sys": sys}
        old = os.environ.get("SHIPMIRACLE_FAKE_OS")
        os.environ["SHIPMIRACLE_FAKE_OS"] = fake
        try:
            exec(mm.group(0).rsplit("def relto", 1)[0], ns)
            got = ns["fold"](path)
        finally:
            if old is None:
                os.environ.pop("SHIPMIRACLE_FAKE_OS", None)
            else:
                os.environ["SHIPMIRACLE_FAKE_OS"] = old
        exp = want if sys.platform != "darwin" else path.casefold()
        check("%s: fold(%r) on %s" % (label, path, fake), got == exp, got)
from shipmiracle import paths as _paths
for fake, path, want in (("wsl", "/mnt/C/Users/Someone/X", "/mnt/c/users/someone/x"), ("wsl", "/home/Me/X", "/home/Me/X"), ("linux", "/mnt/C/Users/Someone/X", "/mnt/C/Users/Someone/X")):
    old = os.environ.get("SHIPMIRACLE_FAKE_OS"); os.environ["SHIPMIRACLE_FAKE_OS"] = fake
    try:
        got = _paths.fold(path)
    finally:
        os.environ.pop("SHIPMIRACLE_FAKE_OS", None) if old is None else os.environ.__setitem__("SHIPMIRACLE_FAKE_OS", old)
    check("paths.fold(%r) on %s" % (path, fake), got == (want if sys.platform != "darwin" else path.casefold()), got)
check("the fake OS variable is ignored outside SHIPMIRACLE_TEST=1", 'os.environ.get("SHIPMIRACLE_TEST") == "1" and os.environ.get("SHIPMIRACLE_FAKE_OS")' in src)

# ------------------------------------------------------------------ hard stop on a case-sensitive file system (sys.platform=linux): the name tables are folded (_cf), protected paths are folded (_pf)
def hs_write(path, scope=("**",)):
    """The Write tool through the hard stop with a charter scope that covers everything, so only the always-excluded name tables and the protected paths can stop it."""
    c = H.Ctx(root=str(WT), base_sha="abc123", scope=list(scope), tracked=lambda rel: ["src/a.py"], changed=set(), read_text=lambda r: None, added_text=lambda r: None,
              home=HOME, tmp_roots=["/tmp", "/private/tmp"], active_cr="CR-012", ends=["CR-012"], auto_branch="auto/CR-012", ahead=1)
    return H.check("PreToolUse", "Write", {"file_path": path, "content": "x"}, str(WT), c)


real_platform = sys.platform
try:
    sys.platform = "linux"
    for rel in ("CLAUDE.md", "claude.MD", "sub/Agents.md", "sub/AGENTS.MD", ".ENV", ".Claude/x"):
        got = hs_write(str(WT / rel))
        check("hard stop on Linux: Write %s is refused (name tables are folded on every OS)" % rel, bool(got), [s.rule for s in got])
    for rel in ("src/a.py",):
        got = hs_write(str(WT / rel))
        check("hard stop on Linux: Write %s (in scope) is allowed" % rel, not got, [(s.rule, s.text[:60]) for s in got])
    for pth in (HOME + "/.CONFIG/SYSTEMD/user/x.service", HOME + "/.Local/Share/KEYRINGS/x", HOME + "/.config/Autostart/x.desktop", HOME + "/.SSH/authorized_keys"):
        got = hs_write(pth)
        check("hard stop on Linux: Write %s is refused (protected paths are folded)" % pth.replace(HOME, "~"), bool(got), [s.rule for s in got])
    got = hs_write(HOME + "/.config/other/x")
    check("hard stop on Linux: a file outside the worktree is still H6 (not silently allowed)", bool(got), [])
finally:
    sys.platform = real_platform

p.cleanup()
print("\nFAILED: %d" % len(fails) if fails else "\nALL PASS")
sys.exit(1 if fails else 0)
