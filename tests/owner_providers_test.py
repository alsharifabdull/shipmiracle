#!/usr/bin/env python3
"""shipmiracle/owner.py without the autopilot world: provider tiers and the no-downgrade rule (RT12, RT13, RT18, RT22), the typed code through a REAL pty (RT14-RT16), the hook route (RT17), the /proc
ancestry walk, WSL and VS Code-server chains (RT19, RT20), native Windows (RT21), the friction rules (one prompt per action, cool-down, plain refusals, a hard cap on the hook wait),
the build script and the doctor row. Needs only a temp HOME / config / state (tests/shipmiracle_isolation.py); runs on macOS and Linux (the Ubuntu CI job). A real Touch ID touch cannot be
automated: the helper is replaced by fake scripts through the test-only seam SHIPMIRACLE_PRESENCE_BIN. WSL, VS Code-server, Windows Hello, fprintd and polkit are tested with injected fakes only
(NOT verified on real systems). Run: python3 tests/owner_providers_test.py"""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import shipmiracle_isolation; shipmiracle_isolation.apply_to_environ()   # test isolation
import io, json, os, pathlib, pty, subprocess, sys, tempfile, time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
from shipmiracle import owner, paths, ShipmiracleError  # noqa: E402
import shipmiracle.config as acfg  # noqa: E402

fails = 0


def check(name, ok, info=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(info)[:600]))
    fails += 0 if ok else 1


os.environ["SHIPMIRACLE_ENFORCE_OWNER"] = "1"
os.environ.pop("CLAUDECODE", None)
CFG = pathlib.Path(os.environ["SHIPMIRACLE_CONFIG"])
STATE = pathlib.Path(os.environ["SHIPMIRACLE_STATE"])
TMP = pathlib.Path(tempfile.mkdtemp(prefix="ownprov-")).resolve()
CLEAN = ["python3", "zsh", "login", "Terminal"]
owner._CHAIN_OVERRIDE = CLEAN


class Fake(owner.Provider):
    def __init__(self, name, tier, probe="ready", ask="ok"):
        self.name, self.tier, self._probe, self._ask, self.calls = name, tier, probe, ask, []

    def probe(self):
        return self._probe

    def ask(self, reason, timeout):
        self.calls.append((reason, timeout))
        return self._ask


class Fake2(Fake):
    needs_tty = True


def reset():
    owner.reset_cache()
    try:
        os.unlink(str(owner._state_file()))
    except OSError:
        pass
    try:
        os.unlink(str(CFG / "config.json"))
    except OSError:
        pass


def sel_text(**kw):
    try:
        return owner.select(**kw), None
    except owner.OwnerRefused as e:
        return None, str(e)


def plain(t):
    return bool(t) and "Traceback" not in t and t.count(". ") <= 2 and len(t) < 420


# ================================================================ RT12: tier choice with fake providers
print("# RT12 tiers")
reset()
s_, m_, b_ = Fake("touch", "strong"), Fake("pw", "medium"), Fake2("code", "basic")
owner.PROVIDERS = [s_, m_, b_]
sel, err = sel_text()
check("RT12 strong ready -> strong is chosen first", sel and sel.tier == "strong" and sel.providers[0] is s_, err)
s_._probe = "absent"
sel, err = sel_text()
check("RT12 no strong, medium ready (auto) -> medium", sel and sel.tier == "medium", err)
m_._probe = "absent"
sel, err = sel_text()
check("F3 basic is OPT-IN: with no Touch ID / password prompt at all, `auto` refuses with the sentence that names `shipm switch owner.presence basic-ok`", sel is None and "owner.presence basic-ok" in err and "plausible terminal, not a person" in err and plain(err), err)
sel, err = sel_text(setting="basic-ok")
check("RT12 neither strong nor medium exists at all and the owner opted in (basic-ok) -> basic", sel and sel.tier == "basic" and sel.providers[0] is b_, err)
s_._probe, m_._probe = "setup", "setup"
sel, err = sel_text()
check("RT12 an installable helper that is not built is NOT 'absent': auto refuses with the fix instead of dropping to the typed code", sel is None and "bin/shipm-presence-build" in err and plain(err), err)
s_._probe, m_._probe = "ready", "ready"
acfg.set("owner.presence", "strong-only")
s_._probe = "absent"
sel, err = sel_text()
check("RT12 strong-only with only medium available is refused with one plain sentence", sel is None and "strong-only" in err and plain(err), err)
reset()
s_._probe, m_._probe = "ready", "ready"
s_._ask = "unavailable"
rr = owner.touch("checkpoint", "Shipmiracle: test", sel=owner.select())
check("RT12 strong ready but unavailable when asked (lid closed) + auto -> falls to medium, typed code never asked", len(s_.calls) == 1 and len(m_.calls) == 1 and not b_.calls, (s_.calls, m_.calls))
s_._ask = "ok"
# hook route never offers the typed code
s_._probe, m_._probe = "absent", "absent"
sel, err = sel_text(hook=True, min_tier="medium", setting="basic-ok")
check("RT17 the chat `allow:` route with only the typed code available is refused (no terminal in a hook)", sel is None and "system dialog" in err and plain(err), err)
sel, err = sel_text(min_tier="medium", setting="basic-ok")
check("RT17 a medium-tier action at the typed-code tier is refused with the 'stronger owner check' sentence and the separate-account hint", sel is None and "mark-separate-account" in err and plain(err), err)
(CFG / "throwaway-account").write_text("x\n")
owner._ACCOUNT_OVERRIDE = lambda: False
sel, err = sel_text(min_tier="medium", separate_ok=True, setting="basic-ok")
check("F1 a forged marker on an ADMIN account counts for nothing: option C at the typed-code tier is still refused", sel is None and "stronger owner check" in err, err)
owner._ACCOUNT_OVERRIDE = lambda: True
sel, err = sel_text(min_tier="medium", separate_ok=True, setting="basic-ok")
check("RT17/RT11 ... unless the account is marked separate (option C actions only: separate_ok)", sel is not None and sel.tier == "basic", err)
sel, err = sel_text(min_tier="medium", separate_ok=False, setting="basic-ok")
check("RT17 ... and the chat route never gets that exception", sel is None, err)
os.unlink(str(CFG / "throwaway-account"))
s_._probe, m_._probe = "ready", "ready"
reset()
acfg.set("owner.presence", "strong-only")
s_._probe = "ready"

# ================================================================ RT13 no downgrade with the REAL provider classes and a fake helper
print("# RT13 no downgrade")
reset()
fake_helper = TMP / "fake-helper"
log = TMP / "helper.log"
POL = TMP / "policies"
ANS = TMP / "answer"
POL.write_text("strong owner\n"); ANS.write_text("ok\n")
fake_helper.write_text('#!/bin/sh\necho "$@" >> %s\nif [ "$1" = "--probe" ]; then cat %s; exit 0; fi\ncase "$(cat %s)" in ok) echo ok; exit 0;; unavailable) echo unavailable; exit 2;; *) echo refused; exit 1;; esac\n' % (log, POL, ANS))
os.chmod(str(fake_helper), 0o700)
os.environ["SHIPMIRACLE_PRESENCE_BIN"] = str(fake_helper)
code_p = Fake2("code", "basic")
owner.PROVIDERS = [owner.HelperProvider("macos-touchid", "strong", "strong"), owner.HelperProvider("macos-password", "medium", "owner"), code_p]
sel, err = sel_text()
check("RT13 the helper (fake, via the sandbox seam) reports strong + owner -> strong chosen", sel and sel.tier == "strong", err)
owner.reset_cache(); POL.write_text("owner\n")
sel, err = sel_text()
check("RT13 policies 'owner' only (a Mac without Touch ID) -> medium", sel and sel.tier == "medium", err)
owner.reset_cache(); POL.write_text("none\n")
sel, err = sel_text(setting="basic-ok")
check("RT13 policies 'none' (helper works, no hardware) + basic-ok -> the typed code (basic)", sel and sel.tier == "basic", err)
owner.reset_cache(); POL.write_text("strong owner\n")
os.unlink(str(fake_helper))
sel, err = sel_text()
check("RT13 the helper file disappears while the seam points at it: missing -> not built, plain fix sentence; the typed code is not offered silently", sel is None and plain(err) and not code_p.calls, err)
del os.environ["SHIPMIRACLE_PRESENCE_BIN"]

# ================================================================ RT14-RT16 the typed code through a REAL pty
print("# RT14-RT16 typed code")
reset()
owner._TTY_OVERRIDE = None
CODE_SCRIPT = ("import sys,os\nsys.path.insert(0, %r)\nimport shipmiracle_isolation\nfrom shipmiracle import owner\nw = owner.TypedCode().ask('Confirm the thing', 4)\nopen(%r, 'w').write(w)\n" % (str(HERE), str(TMP / "res.txt")))


def run_code(mode):
    """mode: 'right' (read the printed code, type it), 'ahead' (type-ahead written before the code exists), 'silent' (nothing typed; stdin piped with a yes), 'wrong'."""
    res = TMP / "res.txt"
    if res.exists():
        res.unlink()
    env = dict(os.environ, SHIPMIRACLE_ENFORCE_OWNER="1")
    pid, fd = pty.fork()
    if pid == 0:
        os.execve(sys.executable, [sys.executable, "-c", CODE_SCRIPT], env)
    out = b""
    if mode == "ahead":
        os.write(fd, b"yes\nAAAAAA\n")                  # typed before the code is printed
    deadline = time.time() + 12
    typed = False
    while time.time() < deadline:
        import select
        r, _w, _x = select.select([fd], [], [], 0.2)
        if r:
            try:
                chunk = os.read(fd, 1024)
            except OSError:
                break
            if not chunk:
                break
            out += chunk
            if mode in ("right", "wrong") and not typed and b">" in out.split(b"code")[-1] and b"cancel" in out:
                import re as _re
                m = _re.search(rb":\s+([A-Z2-9]{6})\s+>", out)
                if m:
                    os.write(fd, (m.group(1) if mode == "right" else b"ZZZZZZ") + b"\n")
                    typed = True
        try:
            done, _st = os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            break
        if done:
            break
    try:
        os.waitpid(pid, 0)
    except ChildProcessError:
        pass
    os.close(fd)
    return (res.read_text() if res.exists() else "(no result)"), out


w, out = run_code("right")
check("RT16 (documented limit) a driver that READS the printed code on the terminal and types it passes: a typed code does not stop a program that controls the terminal window", w == "ok", (w, out[-200:]))
w, out = run_code("wrong")
check("RT14 a wrong code is refused (one try)", w == "refused", (w, out[-200:]))
w, out = run_code("ahead")
check("RT14 type-ahead written to the terminal BEFORE the code is printed is flushed: refused", w == "refused", (w, out[-200:]))
check("RT14 the code is 6 characters from an alphabet without 0 O 1 I", all(c not in owner.CODE_ALPHABET for c in "01OI") and len(owner.CODE_ALPHABET) == 32)
w, out = run_code("silent")
check("RT14 nothing typed (a pre-piped `yes` on stdin is never read: the code reads /dev/tty) -> refused", w == "refused", (w, out[-200:]))

# ================================================================ RT15: a pty driver under a claude chain is refused before any code is printed
print("# RT15")
reset()
tty_fake = Fake2("code", "basic")
owner.PROVIDERS = [tty_fake]
owner._CHAIN_OVERRIDE = ["python3", "claude", "zsh", "Terminal"]
try:
    owner.gate("checkpoint", "shipm autopilot checkpoint"); r15 = None
except owner.OwnerRefused as e:
    r15 = str(e)
owner._CHAIN_OVERRIDE = CLEAN
check("RT15 a chain with claude above is refused at lock 2; the code was never asked for (nothing printed on any terminal)", r15 and not tty_fake.calls and plain(r15), r15)

# ================================================================ RT18 + RT22
print("# RT18 / RT22")
reset()
st_, ty_ = Fake("touch", "strong"), Fake2("code", "basic")
owner.PROVIDERS = [st_, ty_]
owner._CHAIN_OVERRIDE = CLEAN
acfg.set("owner.presence", "strong-only")
check("RT18 STRENGTHENING the setting asks nothing", not st_.calls and acfg.get("owner.presence") == "strong-only")
acfg.set("owner.presence", "basic-ok")
check("RT18 weakening `owner.presence` (strong-only -> basic-ok) asks the BEST provider that works (strong), not the typed code", len(st_.calls) == 1 and not ty_.calls and acfg.get("owner.presence") == "basic-ok", (st_.calls, ty_.calls))
acfg.set("owner.presence", "auto")
check("RT18 basic-ok -> auto is a strengthening: no prompt", len(st_.calls) == 1)
reset()
ty_ = Fake2("code", "basic")
owner.PROVIDERS = [ty_]
buf = io.StringIO()
old_out = sys.stdout
sys.stdout = buf
try:
    sel = owner.select(setting="basic-ok")
    owner.touch("checkpoint", "x", sel=sel)
    first = buf.getvalue()
    buf.truncate(0); buf.seek(0)
    owner.touch("checkpoint", "x", sel=owner.select(setting="basic-ok"))
    second = buf.getvalue()
    owner.PROVIDERS = [Fake("pw", "medium")]
    owner.touch("checkpoint", "x", sel=owner.select())
    third = buf.getvalue()
finally:
    sys.stdout = old_out
check("RT22 the typed-code warning is printed once (first action), says plainly that a chat that can open a terminal window can still answer it, not on the second, and again when the tier changes", "typed code" in first and "open a terminal window" in first and second == "" and "Mac password" in third, (first[:80], second, third[:80]))

# ================================================================ friction: one prompt, cool-down, hard cap
print("# friction")
reset()
cancel = Fake("touch", "strong", ask="refused")
owner.PROVIDERS = [cancel]
try:
    owner.touch("checkpoint", "x", sel=owner.select()); f1 = None
except owner.OwnerRefused as e:
    f1 = str(e)
try:
    owner.touch("checkpoint", "x", sel=owner.select()); f2 = None
except owner.OwnerRefused as e:
    f2 = str(e)
check("friction 3: after a cancelled check there is NO re-prompt: the second try is refused for 30 s without asking the provider", f1 and f2 and len(cancel.calls) == 1 and "wait" in f2 and plain(f1) and plain(f2), (f1, f2, cancel.calls))
d = json.loads(owner._state_file().read_text())
d["fail_ts"] = time.time() - 31
owner._state_file().write_text(json.dumps(d))
cancel._ask = "ok"
owner.touch("checkpoint", "x", sel=owner.select())
check("friction 3: after the 30 s it asks again and a pass clears the cool-down", len(cancel.calls) == 2 and owner.cooldown_left() == 0)
reset()
dead = Fake("touch", "strong", ask="unavailable")
owner.PROVIDERS = [dead]
acfg.set("owner.presence", "strong-only")
try:
    owner.touch("checkpoint", "x", sel=owner.select()); f4 = None
except owner.OwnerRefused as e:
    f4 = str(e)
check("friction 4/5: a dead sensor under strong-only is refused with one sentence that says stop and switch-off still work (no cool-down: nothing was cancelled)", f4 and "stop and switch-off still work" in f4 and owner.cooldown_left() == 0 and plain(f4), f4)
reset()

# hard cap on the hook wait (friction 7), measured with a helper that never answers
sleeper = TMP / "sleeper"
sleeper.write_text('#!/bin/sh\nif [ "$1" = "--probe" ]; then echo strong; exit 0; fi\nsleep 60\necho ok\n')
os.chmod(str(sleeper), 0o700)
os.environ["SHIPMIRACLE_PRESENCE_BIN"] = str(sleeper)
owner.reset_cache()
owner.PROVIDERS = [owner.HelperProvider("macos-touchid", "strong", "strong")]
t0 = time.time()
try:
    owner.touch("allow", "x", timeout=2, hook_cmd="shipm autopilot allow H-aaaaaa --project p", min_tier="medium"); f7 = None
except owner.OwnerRefused as e:
    f7 = str(e)
took = time.time() - t0
check("friction 7: the chat `allow:` route gives up at its cap (2 s here, %d s in production) and never hangs; the refusal names the exact terminal command" % owner.HOOK_WAIT_S,
      took < 8 and f7 and "shipm autopilot allow H-aaaaaa --project p" in f7 and plain(f7.split(". To do it now")[0]), (took, f7))
check("friction 7: the production cap is small (<= 30 s)", owner.HOOK_WAIT_S <= 30)
del os.environ["SHIPMIRACLE_PRESENCE_BIN"]
owner.reset_cache()

# ================================================================ /proc ancestry (RT19), WSL (RT20), native Windows (RT21)
print("# RT19-RT21")
PROC = TMP / "proc"


def proc(pid, ppid, comm, cmdline=None):
    d = PROC / str(pid)
    d.mkdir(parents=True, exist_ok=True)
    (d / "stat").write_text("%d (%s) S %d 1 1 0 -1 0 0 0 0 0 0 0 0 0 20 0 1 0 1 0 0\n" % (pid, comm, ppid))
    (d / "cmdline").write_bytes((cmdline or comm).encode().replace(b" ", b"\0") + b"\0" if cmdline != "" else b"")


proc(100, 90, "python3", "/usr/bin/python3")
proc(90, 80, "zsh", "/bin/zsh")
proc(80, 70, "gnome-terminal-", "/usr/libexec/gnome-terminal-server")
proc(70, 1, "systemd", "/lib/systemd/systemd")
owner._PROC = str(PROC)
old_plat = sys.platform
sys.platform = "linux"
try:
    chain, err = owner.process_chain(100)
    check("RT19 /proc walk: the name is argv[0]'s basename (comm is cut at 15 characters)", chain == ["python3", "zsh", "gnome-terminal-server", "systemd"] and not err, (chain, err))
    ok, why = owner.ancestry({}, chain_override=chain[:3], claude_ok=False)
    check("RT19 a gnome-terminal-server chain is an owner host", ok, why)
    proc(95, 94, "node", "claude"); proc(94, 80, "zsh", "/bin/zsh")
    chain2, _e = owner.process_chain(95)
    ok, why = owner.ancestry({}, chain_override=chain2, claude_ok=False)
    check("RT19 a claude process above is refused for a CLI command", not ok and "claude" in why, why)
    proc(60, 1, "setsid-job", "/usr/bin/setsid-job")
    chain3, _e = owner.process_chain(60)
    ok, why = owner.ancestry({}, chain_override=chain3, claude_ok=False)
    check("RT19 an orphan that ends at pid 1 without an owner host is refused", not ok and "detached" in why, (chain3, why))
    proc(55, 54, "a) b (c", ""); proc(54, 80, "zsh", "/bin/zsh")
    chain4, _e = owner.process_chain(55)
    check("RT19 a process name containing ') ' and '(' does not shift the fields (parent = field after the LAST ')')", chain4[:2] == ["a) b (c", "zsh"], chain4)
    ok, why = owner.ancestry({}, chain_override=["a"], claude_ok=False) if False else (True, "")
    shutil_proc_missing, errm = owner.process_chain(12345)
    check("RT19 an unreadable process step fails closed", errm and not shutil_proc_missing, errm)
    # WSL
    owner._WSL_OVERRIDE = True
    proc(200, 190, "python3", "/usr/bin/python3"); proc(190, 180, "bash", "/bin/bash"); proc(180, 1, "Relay(185)", "")
    c5, _e = owner.process_chain(200)
    ok, why = owner.ancestry({}, chain_override=c5, claude_ok=False)
    check("RT20 WSL: an interactive shell under the per-terminal relay is an owner host", ok, (c5, why))
    proc(300, 290, "node", "/home/u/.vscode-server/bin/abc/node server.js"); proc(290, 280, "bash", "/bin/bash"); proc(280, 1, "node", "/home/u/.vscode-server/bin/abc/node")
    c6, _e = owner.process_chain(290)
    ok, why = owner.ancestry({}, chain_override=c6, claude_ok=False)
    check("RT20 VS Code server: a shell under the server's node (path under /.vscode-server/) is an owner host", ok, (c6, why))
    proc(400, 1, "python3", "/usr/bin/python3")
    c7, _e = owner.process_chain(400)
    ok, why = owner.ancestry({}, chain_override=c7, claude_ok=False)
    check("RT20 WSL: an orphan reparented to pid 1 is still refused", not ok, why)
    owner._WSL_OVERRIDE = False
    ok, why = owner.ancestry({}, chain_override=c5, claude_ok=False)
    check("RT20 the same relay chain WITHOUT WSL detected is refused (relay names count only in WSL)", not ok, why)
finally:
    sys.platform = old_plat
    owner._WSL_OVERRIDE = None
    owner._PROC = "/proc"
sys.platform = "win32"
owner._CHAIN_OVERRIDE = None
try:
    chain, err = owner.process_chain()
    ok, why = owner.ancestry({}, claude_ok=False)
    try:
        owner.gate("checkpoint", "shipm autopilot checkpoint"); gw = None
    except owner.OwnerRefused as e:
        gw = str(e)
    prov_state = [p.probe() for p in (owner.HelperProvider("a", "strong", "strong"), owner.TypedCode())]
finally:
    sys.platform = old_plat
    owner._CHAIN_OVERRIDE = CLEAN
check("RT21 native Windows: process_chain returns the error, ancestry refuses, gate says 'WSL 2', no provider claims to be ready", err and not ok and gw and "WSL 2" in gw and prov_state == ["absent", "absent"], (err, why, gw, prov_state))
r = subprocess.run([sys.executable, "-c", "import os, runpy, sys; os.name = 'nt'; runpy.run_path(%r, run_name='__main__')" % str(ROOT / "bin" / "shipm")], capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
check("RT21 `bin/shipm` on native Windows prints the WSL 2 sentence and exits 2 (no traceback)", r.returncode == 2 and "WSL 2" in r.stderr and "Traceback" not in r.stderr, (r.returncode, r.stderr[-200:]))

# ================================================================ host proof at the typed-code tier (security review: process NAMES are attacker-settable)
print("# host proof")
import types as _types
import stat as _stat
FS = {}


def fs(path, uid=0, mode=0o755, link=False):
    FS[path] = (uid, (_stat.S_IFLNK if link else _stat.S_IFDIR) | mode)


def fake_lstat(p):
    if p not in FS:
        raise OSError(2, "no such file", p)
    uid, mode = FS[p]
    return _types.SimpleNamespace(st_uid=uid, st_mode=mode)


for d in ("/", "/usr", "/usr/libexec", "/usr/bin", "/usr/local", "/usr/local/bin", "/opt", "/bin", "/init"):
    fs(d)
fs("/usr/libexec/gnome-terminal-server", mode=0o755)
fs("/usr/bin/xterm", mode=0o755)
fs("/usr/local/bin/xterm", uid=1000)
owner._lstat = fake_lstat
owner._realpath = lambda p: p
old_plat = sys.platform
sys.platform = "linux"
try:
    ok_ = owner._entry_proven({"name": "gnome-terminal-server", "path": "/usr/libexec/gnome-terminal-server"})
    check("RT23 a real root-owned terminal binary under a system root is a PROVEN host", ok_)
    check("RT23 the same NAME with a path in a user-writable folder (exec -a / a copied binary) is NOT proven", not owner._entry_proven({"name": "gnome-terminal-server", "path": "/home/u/bin/gnome-terminal-server"}))
    check("RT23 a binary under /usr/local that the user owns is NOT proven", not owner._entry_proven({"name": "xterm", "path": "/usr/local/bin/xterm"}))
    check("RT23 a process with only a name and no readable exe path is NOT proven", not owner._entry_proven({"name": "gnome-terminal-server", "path": None}))
    check("RT23 a deleted executable ('... (deleted)') is NOT proven", not owner._entry_proven({"name": "xterm", "path": "/usr/bin/xterm (deleted)"}))
    owner._realpath = lambda p: "/home/u/evil" if p == "/usr/bin/xterm" else p
    check("RT23 a symlinked executable (the real path differs) is NOT proven", not owner._entry_proven({"name": "xterm", "path": "/usr/bin/xterm"}))
    owner._realpath = lambda p: p
    fs("/usr/libexec", mode=0o775)
    check("RT23 a group-writable folder above the binary makes it NOT proven", not owner._entry_proven({"name": "gnome-terminal-server", "path": "/usr/libexec/gnome-terminal-server"}))
    fs("/usr/libexec", mode=0o755)
    fs("/usr/libexec", uid=1000)
    check("RT23 a folder above the binary owned by the user makes it NOT proven", not owner._entry_proven({"name": "gnome-terminal-server", "path": "/usr/libexec/gnome-terminal-server"}))
    fs("/usr/libexec", uid=0)
    check("RT23 a user-owned VS Code server (a node under ~/.vscode-server) is NOT proven; the name-level lock 2 still accepts it as plausible", not owner._entry_proven({"name": "node", "path": "/home/u/.vscode-server/bin/abc/node"})
          and owner.is_owner_host("/home/u/.vscode-server/bin/abc/node"))
    owner._WSL_OVERRIDE = True
    check("RT23 WSL: /init (root-owned) counts as the relay host; the same name elsewhere does not", owner._entry_proven({"name": "init", "path": "/init"}) and not owner._entry_proven({"name": "init", "path": "/tmp/init"}))
    owner._WSL_OVERRIDE = None
    # end to end through select(): only the typed code needs the proof
    reset()
    owner.PROVIDERS = [owner.TypedCode()]
    owner._TTY_OVERRIDE = "/dev/null"
    owner._DETAIL_OVERRIDE = [{"name": "python3", "path": "/usr/bin/python3"}, {"name": "bash", "path": "/usr/bin/bash"}, {"name": "gnome-terminal-server", "path": "/home/u/bin/gnome-terminal-server"}]
    sel, err = sel_text(setting="basic-ok")
    check("RT24 select() at the typed-code tier with a spoofed terminal is refused with the plain sentence and the next step", sel is None and "cannot prove this terminal is yours" in err and "owner.presence" in err
          and "installed system-wide" in err and plain(err), err)
    owner._DETAIL_OVERRIDE[2]["path"] = "/usr/libexec/gnome-terminal-server"
    sel, err = sel_text(setting="basic-ok")
    check("RT24 ... and with a proven terminal above it is accepted", sel is not None and sel.tier == "basic", err)
    owner._DETAIL_OVERRIDE = [{"name": "python3", "path": "/usr/bin/python3"}, {"name": "claude", "path": "/home/u/.local/bin/claude"}, {"name": "gnome-terminal-server", "path": "/usr/libexec/gnome-terminal-server"}]
    sel, err = sel_text(setting="basic-ok")
    check("RT24 ... but not when a claude process sits above this command", sel is None and "Claude chat" in err, err)
    owner._DETAIL_OVERRIDE = [{"name": "python3", "path": "/usr/bin/python3"}, {"name": "gnome-terminal-server", "path": "/home/u/bin/gnome-terminal-server"}]
    strong = Fake("touch", "strong")
    owner.PROVIDERS = [strong, owner.TypedCode()]
    sel, err = sel_text()
    check("RT24 at the strong tier the OS prompt is the proof: a spoofed terminal name does not matter there (lock 2 stays name-level)", sel is not None and sel.tier == "strong", err)
finally:
    sys.platform = old_plat
    owner._DETAIL_OVERRIDE = None
    owner._TTY_OVERRIDE = None
    owner._lstat, owner._realpath = os.lstat, os.path.realpath
    owner._WSL_OVERRIDE = None
# macOS bundles
sys.platform = "darwin"
VS = "/Applications/Visual Studio Code.app"
HELPER = VS + "/Contents/Frameworks/Code Helper (Plugin).app/Contents/MacOS/Code Helper (Plugin)"
good = {"valid": True, "identifier": "com.microsoft.VSCode", "team": "UBF8T346G9", "adhoc": False}
try:
    owner._CODESIGN = lambda b: good if b == VS else {"valid": False, "identifier": "", "team": None, "adhoc": True}
    check("RT25 macOS: a process inside the exact VS Code bundle with a valid, Microsoft-signed code signature is a proven host (the helper's path resolves to the outer bundle)",
          owner._entry_proven({"name": "Code Helper (Plugin)", "path": HELPER}))
    for label, sig in (("an ad-hoc signature", dict(good, adhoc=True)), ("an invalid signature (tampered bundle)", dict(good, valid=False)), ("another Team ID", dict(good, team="EVILTEAM00")),
                       ("another identifier", dict(good, identifier="com.evil.app")), ("no Team ID where one is expected", dict(good, team=None))):
        owner._CODESIGN = lambda b, sig=sig: sig
        check("RT25 macOS: %s makes the bundle NOT proven (fail closed)" % label, not owner._entry_proven({"name": "x", "path": HELPER}))
    owner._CODESIGN = lambda b: good
    check("RT25 macOS: the same app in ~/Applications (a user-writable folder) is NOT proven", not owner._entry_proven({"name": "x", "path": "/home/me/Applications/Visual Studio Code.app/Contents/MacOS/Electron"}))
    check("RT25 macOS: a process merely NAMED like a helper ('Code Helper evil') in /tmp is not proven and the prefix rule is gone from the name level too",
          not owner._entry_proven({"name": "Code Helper evil", "path": "/tmp/Code Helper evil"}) and not owner.is_owner_host("Code Helper evil") and not owner.is_owner_host("Claude Helper x"))
    check("RT25 macOS: the name-level lock 2 accepts a process inside an exact bundle path (plausible), and not a look-alike bundle name elsewhere",
          owner.is_owner_host(HELPER) and not owner.is_owner_host("/tmp/Visual Studio Code.app/Contents/MacOS/Electron"))
    check("RT25 macOS: a bundle that is not in the exact list (another .app in /Applications) is not a host", not owner._entry_proven({"name": "x", "path": "/Applications/Evil.app/Contents/MacOS/x"}))
    for d in ("/", "/usr", "/usr/bin"):
        fs(d)
    fs("/usr/bin/login")
    owner._lstat = fake_lstat
    term_ = {"name": "Terminal", "path": "/System/Applications/Utilities/Terminal.app/Contents/MacOS/Terminal"}
    owner._CODESIGN = lambda b: {"valid": True, "identifier": "com.apple.Terminal", "team": None, "adhoc": False} if b.endswith("Terminal.app") else {"valid": False, "identifier": "", "team": None, "adhoc": True}
    check("RT25 macOS: /usr/bin/login (root-owned, not writable) is a proven system host ONLY with a proven app above it (D14 m1); alone it is not",
          owner._entry_proven({"name": "login", "path": "/usr/bin/login"}, [term_]) and not owner._entry_proven({"name": "login", "path": "/usr/bin/login"}) and not owner._entry_proven({"name": "login", "path": "/usr/bin/login"}, []))
    fs("/usr/bin", uid=501)
    check("RT25 ... a user-owned /usr/bin makes it unproven", not owner._entry_proven({"name": "login", "path": "/usr/bin/login"}, [term_]))
finally:
    sys.platform = old_plat
    owner._CODESIGN = None
    owner._lstat = os.lstat
r = subprocess.run(["/bin/sh", "-c", "true"], capture_output=True)
check("RT25 doc: HOST_BUNDLES names exactly the five terminals / editors of the review (Terminal, iTerm2, VS Code, Ghostty, Warp)", {os.path.basename(k) for k in owner.HOST_BUNDLES} == {"Terminal.app", "iTerm.app", "Visual Studio Code.app", "Ghostty.app", "Warp.app"})

# ================================================================ the build script and the doctor row (friction 6)
print("# build script / doctor")
benv = {k: v for k, v in os.environ.items() if k != "SHIPMIRACLE_ENFORCE_OWNER"}
rf = subprocess.run([sys.executable, str(ROOT / "bin" / "shipm-presence-build")], env=dict(os.environ, SHIPMIRACLE_ENFORCE_OWNER="1"), capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
if sys.platform != "darwin":
    print("SKIP F2: the Touch ID helper build is macOS only; on this OS it answers 'not supported on this OS yet' before it reaches the engine-checkout rule")
else:
    check("F2 outside a sandbox the build refuses to run from a copy that is not the registered engine checkout (a rebuilt helper could say ok without Touch ID): one plain sentence, nothing built",
          rf.returncode == 2 and "not the engine checkout registered as engine.dir" in rf.stdout and len(rf.stdout.strip().splitlines()) == 1 and not (CFG / "bin" / "shipm-presence").exists(), (rf.returncode, rf.stdout))
r1 = subprocess.run([sys.executable, str(ROOT / "bin" / "shipm-presence-build"), "--check"], env=benv, capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
check("friction 6: `bin/shipm-presence-build --check` prints ONE line (not built, with the fix) and exits non-zero", r1.returncode in (1, 2) and len(r1.stdout.strip().splitlines()) == 1, (r1.returncode, r1.stdout))
if sys.platform == "darwin" and os.path.exists("/usr/bin/swiftc"):
    r2 = subprocess.run([sys.executable, str(ROOT / "bin" / "shipm-presence-build")], env=benv, capture_output=True, text=True, timeout=400, stdin=subprocess.DEVNULL)
    r3 = subprocess.run([sys.executable, str(ROOT / "bin" / "shipm-presence-build")], env=benv, capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    check("friction 6: the build works on this Mac (one line) and a second run is idempotent ('ready')", r2.returncode == 0 and "built" in r2.stdout and len(r2.stdout.strip().splitlines()) == 1
          and r3.returncode == 0 and "ready" in r3.stdout, (r2.stdout, r2.stderr[-200:], r3.stdout))
    pr = subprocess.run([str(CFG / "bin" / "shipm-presence"), "--probe"], capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL)
    check("OP1 the real helper's --probe (no dialog) answers with the policies this Mac can evaluate", pr.returncode == 0 and set(pr.stdout.split()) <= {"strong", "owner", "none"} and pr.stdout.strip(), pr.stdout)
    pu = subprocess.run([str(CFG / "bin" / "shipm-presence"), "--reason", "x", "--policy", "bogus"], capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL)
    check("OP1 the real helper refuses a bad policy with 'usage' and exit 3 (no dialog)", pu.returncode == 3 and pu.stdout.strip() == "usage", (pu.returncode, pu.stdout))
else:
    check("friction 6 (not on a Mac): the build script says 'not supported on this OS yet' and exits 2", r1.returncode == 2 and "not supported on this OS yet" in r1.stdout, r1.stdout)
doc = (ROOT / "bin" / "doctor").read_text()
row = [l for l in doc.splitlines() if "owner status --line" in l]
check("friction 6/OP8: bin/doctor has the 'Owner check' row, as ok or warn (never a FAIL), from `shipm owner status --line`", row and "bad " not in row[0] and "warn" in row[0], row)
from shipmiracle.autopilot import cli as _apcli  # noqa: E402
reset()
rows = {}
for label, provs, setting in (("strong", [Fake("t", "strong"), Fake("p", "medium")], "auto"), ("medium", [Fake("t", "strong", probe="absent"), Fake("p", "medium")], "auto"),
                              ("basic", [Fake("t", "strong", probe="absent"), Fake("p", "medium", probe="absent"), Fake2("c", "basic")], "auto"),
                              ("not built", [Fake("macos-touchid", "strong", probe="setup"), Fake("macos-password", "medium", probe="setup"), Fake2("c", "basic")], "auto"),
                              ("changed", [Fake("macos-touchid", "strong", probe="broken"), Fake("macos-password", "medium", probe="broken"), Fake2("c", "basic")], "auto"),
                              ("strong-only dead", [Fake("macos-touchid", "strong", probe="absent"), Fake("macos-password", "medium"), Fake2("c", "basic")], "strong-only"),
                              ("nothing", [Fake("t", "strong", probe="absent"), Fake("p", "medium", probe="absent")], "auto")):
    owner.PROVIDERS = provs
    reset()
    acfg.set("owner.presence", "auto") if False else None
    os.environ.pop("SHIPMIRACLE_ENFORCE_OWNER", None)
    acfg.set("owner.presence", setting)
    os.environ["SHIPMIRACLE_ENFORCE_OWNER"] = "1"
    rows[label] = _apcli.owner_row()
os.environ.pop("SHIPMIRACLE_ENFORCE_OWNER", None); acfg.set("owner.presence", "auto"); os.environ["SHIPMIRACLE_ENFORCE_OWNER"] = "1"
check("OP8 one doctor / Setup row per state, never a FAIL, with the wording of the design (and 'a plausible terminal, not a person' at the typed-code tier)",
      rows["strong"][0] == "ok" and rows["strong"][1].startswith("Owner check: Touch ID (or Apple Watch)") and rows["medium"][0] == "ok" and "Mac password dialog" in rows["medium"][1]
      and rows["basic"][0] == "warn" and "not a person" in rows["basic"][1] and "separate user account" in rows["basic"][1]
      and "bin/shipm-presence-build" in rows["not built"][1] and "bin/shipm-presence-build" in rows["changed"][1] and "stop and switch-off still work" in rows["strong-only dead"][1]
      and rows["nothing"][0] == "warn" and all(r[0] in ("ok", "warn") for r in rows.values()), rows)
# WSL mount row (fake /proc/mounts; the WSL marker file is a seam of the doctor block only)
lines_ = doc.splitlines()
blk = "\n".join(lines_[next(i for i, l in enumerate(lines_) if l.startswith("# wslmounts-begin")) + 1:next(i for i, l in enumerate(lines_) if l.startswith("# wslmounts-end"))])
hm = TMP / "wslhome"; (hm / ".config" / "shipmiracle").mkdir(parents=True)
(TMP / "mounts").write_text("rootfs / ext4 rw 0 0\n%s 9p rw 0 0\n" % "X")
def doctor_wsl(mounts_text, wsl=True):
    (TMP / "mounts").write_text(mounts_text)
    wf = TMP / "wslinterop"
    wf.write_text("1") if wsl else (wf.unlink() if wf.exists() else None)
    pre = 'bad() { printf "  FAIL %%s\\n" "$1"; }; HOME=%s; SHIPMIRACLE_DOCTOR_MOUNTS=%s; SHIPMIRACLE_DOCTOR_WSLFILE=%s\n' % (hm, TMP / "mounts", wf)
    return subprocess.run(["bash", "-c", pre + blk], capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL).stdout
rp = os.path.realpath(str(hm))
check("X8 doctor (WSL): Shipmiracle's config folder on a Windows disk (9p / drvfs mount) is a red row that says to move it into /home", "FAIL WSL:" in doctor_wsl("rootfs / ext4 rw 0 0\nC: %s 9p rw 0 0\n" % rp) and "Linux file system" in doctor_wsl("C: %s drvfs rw 0 0\n" % rp))
check("X8 doctor: the same folder on an ordinary Linux mount is fine, and nothing is checked outside WSL", doctor_wsl("rootfs / ext4 rw 0 0\n") == "" and doctor_wsl("C: %s 9p rw 0 0\n" % rp, wsl=False) == "")

# ================================================================ never lock out: no provider is consulted for stop / clear / off / show (friction 1, 5)
print("# fail-soft")
reset()
none_called = Fake("touch", "strong", ask="refused", probe="broken")
owner.PROVIDERS = [none_called]
import shipmiracle.autopilot.cli as apcli  # noqa: E402
src = (ROOT / "shipmiracle" / "autopilot" / "cli.py").read_text()
import re as _re
def body(fn):
    m = _re.search(r"^def %s\(.*?(?=^def )" % fn, src, _re.S | _re.M)
    return m.group(0) if m else ""
check("friction 1/5: cmd_stop, cmd_show and the charter clear path never call the owner check (source check)", all("owner." not in body(f) for f in ("cmd_stop", "cmd_show")) and "owner." not in body("cmd_charter").split('paths.require_owner("shipm autopilot charter clear")')[-1], "")
acfg.set("autopilot.full.enabled", "off")
check("friction 1/5: switching an autopilot setting OFF never asks (a broken provider changes nothing)", not none_called.calls)
print("\nALL PASS" if not fails else "\n%d FAILED" % fails)
sys.exit(1 if fails else 0)
