#!/usr/bin/env python3
"""owner_d14_test: checklist D14, the owner-proof recheck fixes that need no autopilot world.
  M4  `is_claude` also recognises Claude Code run through node (args hold @anthropic-ai/claude-code, or a claude launcher / claude-code cli.js behind node), on the ps path (macOS) and the /proc path
      (Linux / WSL), for the CLI ancestry (lock 2) and for the typed-code host proof; benign node programs are not taken for Claude;
  m1  /usr/bin/login and sshd count as a proven host only when a proven HOST_BUNDLES app sits above them;
  m2  the presence helper: opened O_NOFOLLOW, a regular file owned by the uid and not group / other-writable, hashed, and a PRIVATE COPY of the hashed bytes is run (a swap after the hash changes nothing);
  m3  `config unset owner.presence` goes through escalate_presence_setting like `config set`;
  m7  bin/shipm re-executes python with -I -S: a hostile PYTHONPATH, user site or working folder is ignored.
Run: python3 tests/owner_d14_test.py"""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import shipmiracle_isolation; shipmiracle_isolation.apply_to_environ()   # test isolation
import hashlib, os, pathlib, shutil, stat, subprocess, sys, tempfile, time

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
TMP = pathlib.Path(tempfile.mkdtemp(prefix="ownd14-")).resolve()
CLAUDE_JS = "/usr/lib/node_modules/@anthropic-ai/claude-code/cli.js"

# ================================================================ M4 is_claude: node-run Claude Code
print("# M4")
YES = [("node", "node " + CLAUDE_JS), ("node", "/usr/local/bin/node " + CLAUDE_JS + " --resume abc"), ("node", "node /home/u/.npm/_npx/1/node_modules/@anthropic-ai/claude-code/cli.js -p hi"),
       ("node", "node /home/u/.nvm/versions/node/v22/bin/claude"), ("node", "node --no-warnings /home/u/bin/claude.js"), ("bun", "bun /home/u/.bun/install/global/node_modules/@anthropic-ai/claude-code/cli.js"),
       ("npm exec", "npm exec @anthropic-ai/claude-code"), ("node", "/usr/bin/node /opt/claude-code/cli.js"), ("claude", ""), ("/home/u/.local/bin/claude", ""),
       ("node", "node   " + CLAUDE_JS.upper()), ("MainThread", "node /home/u/.config/yarn/global/node_modules/@anthropic-ai/claude-code/cli.js")]
NO = [("node", "node /home/u/app/server.js"), ("node", "node /opt/tool/cli.js"), ("node", "node /home/u/proj/node_modules/.bin/eslint ."), ("zsh", "-zsh"), ("vim", "vim claude-notes.md"),
      ("python3", "python3 /home/u/claude/script.py"), ("Terminal", "/System/Applications/Utilities/Terminal.app/Contents/MacOS/Terminal"), ("node", ""), ("node", "node ./build.js --name=claude-ish"),
      ("less", "less /home/u/docs/claude.md"), ("login", "login -pf u")]
for comm, args in YES:
    check("M4 is_claude(%r, %r) is True" % (comm, args[:50]), owner.is_claude(comm, args), (comm, args))
for comm, args in NO:
    check("M4 is_claude(%r, %r) is False" % (comm, args[:50]), not owner.is_claude(comm, args), (comm, args))
check("M4 the one-argument form of is_claude is unchanged", owner.is_claude("claude") and not owner.is_claude("node") and owner.is_claude("/x/claude/versions/1.2.3"))

# --- /proc path: fake /proc tree
PROC = TMP / "proc"


def proc(pid, ppid, comm, cmdline):
    d = PROC / str(pid)
    d.mkdir(parents=True, exist_ok=True)
    (d / "stat").write_text("%d (%s) S %d 1 1 0 -1 0 0 0 0 0 0 0 0 0 20 0 1 0 1 0 0\n" % (pid, comm, ppid))
    (d / "cmdline").write_bytes(b"\0".join(x.encode() for x in cmdline.split(" ")) + b"\0")


proc(100, 90, "python3", "/usr/bin/python3")
proc(90, 80, "zsh", "/bin/zsh")
proc(80, 70, "node", "node " + CLAUDE_JS + " --resume")         # Claude Code run through node
proc(70, 60, "zsh", "/bin/zsh")
proc(60, 50, "gnome-terminal-", "/usr/libexec/gnome-terminal-server")
proc(50, 1, "systemd", "/lib/systemd/systemd")
proc(200, 190, "python3", "/usr/bin/python3")
proc(190, 180, "node", "node /home/u/app/server.js")             # an ordinary node program
proc(180, 60, "zsh", "/bin/zsh")
owner._PROC = str(PROC)
old_plat = sys.platform
sys.platform = "linux"
try:
    chain, err = owner.process_chain(100)
    check("M4 /proc: a node process running claude-code/cli.js is reported as claude", chain[:3] == ["python3", "zsh", "claude"] and not err, (chain, err))
    ok, why = owner.ancestry({}, chain_override=chain, claude_ok=False)
    check("M4 /proc: lock 2 refuses a CLI command with node-run Claude Code above it", not ok and "claude" in why, (ok, why))
    owner._WSL_OVERRIDE = False
    detail, err = owner.process_detail(100)
    owner._DETAIL_OVERRIDE = detail
    ok, why = owner.host_proof(claude_ok=False)
    check("M4 /proc: the typed-code host proof refuses with node-run Claude Code above it", not ok and "Claude" in why, (ok, why))
    owner._DETAIL_OVERRIDE = None
    chain2, err = owner.process_chain(200)
    check("M4 /proc: an ordinary node program keeps its name", chain2[:2] == ["python3", "node"] and not err, (chain2, err))
    ok, why = owner.ancestry({}, chain_override=chain2, claude_ok=False)
    check("M4 /proc: ... and does not refuse the command", ok, why)
    ok, why = owner.ancestry({}, chain_override=chain, claude_ok=True)
    check("M4 /proc: for the hook route (claude_ok) one node-run claude with an owner host above is fine", ok, why)
    proc(300, 290, "node", "node " + CLAUDE_JS); proc(290, 280, "node", "node " + CLAUDE_JS); proc(280, 60, "zsh", "/bin/zsh")
    chain3, _e = owner.process_chain(300)
    ok, why = owner.ancestry({}, chain_override=chain3, claude_ok=True)
    check("M4 /proc: two node-run claude processes (a nested claude -p) are refused", not ok and "second claude" in why, (chain3, why))
finally:
    sys.platform = old_plat
    owner._PROC = "/proc"
    owner._DETAIL_OVERRIDE = None
    owner._WSL_OVERRIDE = None

# --- ps path (macOS): fake `ps`
PS = {  # pid -> (ppid, comm, args)
    500: (490, "/usr/local/bin/python3", "python3 /x/bin/shipm autopilot checkpoint"),
    490: (480, "/bin/zsh", "-zsh"),
    480: (470, "/usr/local/bin/node", "node " + CLAUDE_JS),
    470: (460, "/bin/zsh", "-zsh"),
    460: (1, "/System/Applications/Utilities/Terminal.app/Contents/MacOS/Terminal", "/System/Applications/Utilities/Terminal.app/Contents/MacOS/Terminal"),
    600: (590, "/usr/local/bin/node", "node /home/u/app/server.js"),
    590: (460, "/bin/zsh", "-zsh"),
    700: (690, "/opt/homebrew/bin/node", "claude"),                # the npm install sets process.title: ps shows just `claude` for a node program
    690: (460, "/bin/zsh", "-zsh"),
    710: (690, "/opt/homebrew/bin/node", "claude-code --resume"),
    800: (690, "/opt/homebrew/bin/node", "node something"),         # its args call fails (see BADARGS)
    900: (690, "/usr/bin/vim", "claude"),                           # not a node program: the title alone proves nothing
}
BADARGS = {800}
real_run = subprocess.run
calls = []


class _R:
    def __init__(self, out, rc=0):
        self.stdout, self.stderr, self.returncode = out.encode(), b"", rc


def fake_run(argv, *a, **k):
    if isinstance(argv, list) and argv and argv[0] == "/bin/ps":
        calls.append(list(argv))
        pid = int(argv[-1])
        if pid not in PS:
            return _R("", 1)
        ppid, comm, args = PS[pid]
        if "args=" in argv:
            return _R("", 1) if pid in BADARGS else _R(args + "\n")
        return _R("%d %s\n" % (ppid, comm))
    return real_run(argv, *a, **k)


sys.platform = "darwin"
subprocess.run = fake_run
try:
    chain, err = owner.process_chain(500)
    check("M4 ps: node running claude-code/cli.js is reported as claude (macOS path)", len(chain) >= 3 and chain[2] == "claude" and not err, (chain, err))
    owner._CHAIN_OVERRIDE = None
    _gp = os.getppid
    os.getppid = lambda: 500
    try:
        ok, why = owner.ancestry({}, claude_ok=False)
    finally:
        os.getppid = _gp
    check("M4 ps: ancestry() from a fake ps chain with node-run claude is refused for a CLI command", not ok and "claude" in why, (ok, why))
    chain2, err = owner.process_chain(600)
    check("M4 ps: an ordinary node program stays node", chain2[:2] == ["/usr/local/bin/node", "/bin/zsh"] or chain2[0].endswith("node"), chain2)
    chain3, err = owner.process_chain(700)
    check("M4 ps: comm /opt/homebrew/bin/node with args `claude` (process.title) is reported as claude", chain3[0] == "claude" and not err, (chain3, err))
    _gp = os.getppid
    os.getppid = lambda: 700
    try:
        ok, why = owner.ancestry({}, claude_ok=False)
    finally:
        os.getppid = _gp
    check("M4 ps: ... and lock 2 refuses a CLI command under it", not ok and "claude" in why, (ok, why))
    chain4, err = owner.process_chain(710)
    check("M4 ps: a rewritten title starting with claude (claude-code ...) counts too", chain4[0] == "claude", chain4)
    chain5, err = owner.process_chain(900)
    check("M4 ps: a program that is not a node runner with args `claude` is NOT taken for claude", chain5[0] == "/usr/bin/vim" and not err, (chain5, err))
    chain6, err = owner.process_chain(800)
    check("M4 ps: a failing args call is 'process tree could not be read' (fail closed), not empty args", err and "could not be read" in err, (chain6, err))
    _gp = os.getppid
    os.getppid = lambda: 800
    try:
        ok, why = owner.ancestry({}, claude_ok=False)
    finally:
        os.getppid = _gp
    check("M4 ps: ... and lock 2 then refuses", not ok, (ok, why))
    check("M4 args_are_claude('claude') alone is False without a node runner (unit), True via_runner", not owner.args_are_claude("claude") and owner.args_are_claude("claude", True) and not owner.args_are_claude("vim claude", True))
    check("M4 ps: the args are asked only for node-like programs (no extra ps call per shell, terminal or vim)", {int(c[-1]) for c in calls if "args=" in c} <= {480, 600, 700, 710, 800}, [c for c in calls if "args=" in c])
finally:
    subprocess.run = real_run
    sys.platform = old_plat

# ================================================================ m1 login / sshd only with a proven bundle app above
print("# m1")
good = {"valid": True, "identifier": "com.apple.Terminal", "team": None, "adhoc": False}
TERM = "/System/Applications/Utilities/Terminal.app/Contents/MacOS/Terminal"
fsmap = {}


def fake_lstat(p):
    if p in fsmap:
        return fsmap[p]
    raise OSError(2, "x")


class _St:
    def __init__(self, mode=0o755, uid=0):
        self.st_mode, self.st_uid = stat.S_IFDIR | mode, uid


for d in ("/", "/usr", "/usr/bin", "/usr/sbin", "/usr/libexec"):
    fsmap[d] = _St()
for f in ("/usr/bin/login", "/usr/sbin/sshd", "/usr/libexec/sshd-session"):
    fsmap[f] = _St()
sys.platform = "darwin"
owner._lstat = fake_lstat
owner._CODESIGN = lambda b: good if b.endswith("Terminal.app") else {"valid": False, "identifier": "", "team": None, "adhoc": True}
try:
    login = {"name": "login", "path": "/usr/bin/login"}
    term = {"name": "Terminal", "path": TERM}
    sshd = {"name": "sshd", "path": "/usr/sbin/sshd"}
    owner._DETAIL_OVERRIDE = [{"name": "python3", "path": "/usr/bin/python3"}, {"name": "zsh", "path": "/bin/zsh"}, login, term]
    ok, why = owner.host_proof()
    check("m1 login with the Terminal app above it is a proven host", ok, why)
    owner._DETAIL_OVERRIDE = [{"name": "python3", "path": "/usr/bin/python3"}, {"name": "zsh", "path": "/bin/zsh"}, login]
    ok, why = owner.host_proof()
    check("m1 login alone (nothing above it) is NOT a proven host", not ok, why)
    owner._DETAIL_OVERRIDE = [{"name": "python3", "path": "/usr/bin/python3"}, login, {"name": "evil", "path": "/tmp/evil"}]
    ok, why = owner.host_proof()
    check("m1 login with an unknown program above it is NOT a proven host", not ok, why)
    owner._DETAIL_OVERRIDE = [{"name": "python3", "path": "/usr/bin/python3"}, sshd]
    ok, why = owner.host_proof()
    check("m1 sshd alone is NOT a proven host", not ok, why)
    owner._DETAIL_OVERRIDE = [{"name": "python3", "path": "/usr/bin/python3"}, {"name": "sshd-session", "path": "/usr/libexec/sshd-session"}, sshd]
    ok, why = owner.host_proof()
    check("m1 sshd-session under sshd with no app above is NOT a proven host", not ok, why)
    owner._DETAIL_OVERRIDE = [{"name": "python3", "path": "/usr/bin/python3"}, sshd, term]
    ok, why = owner.host_proof()
    check("m1 sshd with a proven bundle app above it is a proven host", ok, why)
    owner._CODESIGN = lambda b: dict(good, adhoc=True)
    owner._DETAIL_OVERRIDE = [{"name": "python3", "path": "/usr/bin/python3"}, login, term]
    ok, why = owner.host_proof()
    check("m1 login under an app whose signature is ad hoc is NOT a proven host", not ok, why)
    owner._CODESIGN = lambda b: good
    fsmap["/usr/bin"] = _St(uid=501)
    check("m1 a proven app above does not make a user-owned login proven (the login itself is still checked)", not owner._entry_proven(login, [term]))
    fsmap["/usr/bin"] = _St()
    check("m1 _entry_proven: login with a proven app above is proven; with nothing, an empty list or only sshd above it is not",
          owner._entry_proven(login, [term]) and not owner._entry_proven(login) and not owner._entry_proven(login, []) and not owner._entry_proven(login, [sshd]) and not owner._entry_proven(sshd, [login]))
    check("m1 the bundle app alone is still proven", owner._entry_proven(term))
finally:
    sys.platform = old_plat
    owner._lstat = os.lstat
    owner._CODESIGN = None
    owner._DETAIL_OVERRIDE = None

# ================================================================ m2 the helper: file checks and the private copy
print("# m2")
HLOG = TMP / "helper.log"
helper = TMP / "helper"


def put_helper(body=None, mode=0o700):
    if helper.is_symlink() or helper.exists():
        helper.unlink()
    helper.write_text(body or '#!/bin/sh\necho "$0 $@" >> %s\nif [ "$1" = "--probe" ]; then echo "strong owner"; exit 0; fi\necho ok\n' % HLOG)
    os.chmod(str(helper), mode)


os.environ["SHIPMIRACLE_PRESENCE_BIN"] = str(helper)
owner.reset_cache()
put_helper()
check("m2 a regular, owner-only helper is ready", owner.helper_state() == "ready", owner.helper_state())
rc, word = owner._run_helper(["--reason", "x", "--policy", "strong"], 5)
lines = HLOG.read_text().splitlines()
check("m2 ... and it runs", rc == 0 and word == "ok", (rc, word))
check("m2 ... from a PRIVATE COPY, not from the helper's own path", lines and lines[-1].split()[0] != str(helper), lines)
check("m2/#9 ... the private copy lives under the 0700 state folder, not the shared temp folder", lines and os.path.realpath(lines[-1].split()[0]).startswith(os.path.realpath(os.environ["SHIPMIRACLE_STATE"])), lines)
check("m2 ... the private copy is gone afterwards", lines and not os.path.exists(lines[-1].split()[0]) and not os.path.exists(os.path.dirname(lines[-1].split()[0])), lines)
put_helper(mode=0o770)
check("m2 a group-writable helper is refused (changed)", owner.helper_state() == "changed", owner.helper_state())
put_helper(mode=0o707)
check("m2 an other-writable helper is refused (changed)", owner.helper_state() == "changed", owner.helper_state())
rc, word = owner._run_helper(["--probe"], 5)
check("m2 ... and it is not run", rc is None, (rc, word))
real_target = TMP / "real-helper"
real_target.write_text('#!/bin/sh\necho "$0" >> %s\necho ok\n' % HLOG)
os.chmod(str(real_target), 0o700)
if helper.exists():
    helper.unlink()
os.symlink(str(real_target), str(helper))
check("m2 a symlinked helper is refused (changed)", owner.helper_state() == "changed", owner.helper_state())
n0 = len(HLOG.read_text().splitlines())
rc, word = owner._run_helper(["--probe"], 5)
check("m2 ... and it is not run (O_NOFOLLOW)", rc is None and len(HLOG.read_text().splitlines()) == n0, (rc, word))
helper.unlink()
os.mkdir(str(helper))
check("m2 a directory in place of the helper is refused", owner.helper_state() in ("changed", "missing"), owner.helper_state())
os.rmdir(str(helper))
put_helper()
_fst = owner._fstat
owner._fstat = lambda fd: type("S", (), {"st_mode": stat.S_IFREG | 0o700, "st_uid": os.geteuid() + 1, "st_size": 10})()
check("m2 a helper owned by another user is refused (changed)", owner.helper_state() == "changed", owner.helper_state())
owner._fstat = _fst
check("m2 ... back to normal it is ready again", owner.helper_state() == "ready", owner.helper_state())

# swapped after the hash: the bytes that were hashed are the bytes that run (macOS record path, fake platform)
CBIN = CFG / "bin"
CBIN.mkdir(parents=True, exist_ok=True)
real_helper = CBIN / "shipm-presence"
orig = '#!/bin/sh\necho "orig $0" >> %s\nif [ "$1" = "--probe" ]; then echo "strong owner"; exit 0; fi\necho ok\n' % HLOG
real_helper.write_text(orig)
os.chmod(str(real_helper), 0o700)
(CFG / "presence.sha256").write_text(hashlib.sha256(orig.encode()).hexdigest() + "  shipm-presence\n")
del os.environ["SHIPMIRACLE_PRESENCE_BIN"]
sys.platform = "darwin"
owner.reset_cache()
try:
    check("m2 (record) the helper matching its pin is ready", owner.helper_state() == "ready", owner.helper_state())
    swapped = {"n": 0}

    def swap():
        swapped["n"] += 1
        real_helper.write_text('#!/bin/sh\necho "EVIL $0" >> %s\necho ok\n' % HLOG)
        os.chmod(str(real_helper), 0o700)
    owner._AFTER_HASH = swap
    HLOG.write_text("")
    rc, word = owner._run_helper(["--reason", "x", "--policy", "strong"], 5)
    out = HLOG.read_text()
    check("m2 (record) a swap between the hash and the run does not change what runs: the hashed bytes ran", swapped["n"] == 1 and "orig" in out and "EVIL" not in out and rc == 0, (swapped, out, rc))
    owner._AFTER_HASH = None
    check("m2 (record) after the swap the file no longer matches the pin: changed", owner.helper_state() == "changed", owner.helper_state())
    HLOG.write_text("")
    rc, word = owner._run_helper(["--probe"], 5)
    check("m2 (record) a helper that does not match its pin is not run at all", rc is None and HLOG.read_text() == "", (rc, HLOG.read_text()))
finally:
    sys.platform = old_plat
    owner._AFTER_HASH = None
    owner.reset_cache()

# ================================================================ m3 config unset owner.presence
print("# m3")


class Fake(owner.Provider):
    def __init__(self, name, tier):
        self.name, self.tier, self.calls = name, tier, []

    def probe(self):
        return "ready"

    def ask(self, reason, timeout):
        self.calls.append(reason)
        return "ok"


owner._CHAIN_OVERRIDE = ["python3", "zsh", "login", "Terminal"]
touch = Fake("touch", "strong")
owner.PROVIDERS = [touch]
try:
    acfg.set("owner.presence", "strong-only")
    check("m3 setting strong-only (a strengthening) asks nothing", not touch.calls, touch.calls)
    seen = []
    real_esc = owner.escalate_presence_setting
    owner.escalate_presence_setting = lambda old, new: (seen.append((old, new)), real_esc(old, new))[1]
    acfg.unset("owner.presence")
    check("m3 `config unset owner.presence` goes through escalate_presence_setting (old strong-only, new auto)", seen == [("strong-only", "auto")], seen)
    check("m3 ... and weakening strong-only to the default is confirmed by the best check (one touch)", len(touch.calls) == 1, touch.calls)
    check("m3 ... the key is gone afterwards", acfg.get("owner.presence") == "auto", acfg.get("owner.presence"))
    touch.calls.clear(); seen.clear()
    acfg.unset("owner.presence")
    check("m3 unsetting a key that is already at the default (auto) asks nothing", seen == [("auto", "auto")] and not touch.calls, (seen, touch.calls))
    acfg.set("owner.presence", "basic-ok")
    touch.calls.clear()
    acfg.unset("owner.presence")
    check("m3 unsetting basic-ok (a strengthening back to auto) asks nothing", not touch.calls, touch.calls)
    acfg.set("owner.presence", "strong-only")
    owner.PROVIDERS = [Fake("pw", "medium")]
    owner.PROVIDERS[0].ask = lambda reason, timeout: "refused"
    try:
        acfg.unset("owner.presence"); r = None
    except ShipmiracleError as e:
        r = str(e)
    check("m3 a refused check keeps strong-only in place (nothing is weakened)", r is not None and acfg.get("owner.presence") == "strong-only", (r, acfg.get("owner.presence")))
finally:
    owner.escalate_presence_setting = real_esc
    owner._CHAIN_OVERRIDE = None

# ================================================================ m7 bin/shipm re-executes isolated
print("# m7")
EVIL = TMP / "evil"
(EVIL / "shipmiracle").mkdir(parents=True)
MARK = TMP / "evil-ran"
for mod in ("json.py", "shipmiracle/__init__.py", "shlex.py", "re.py", "argparse.py"):
    (EVIL / mod).write_text("open(%r, 'a').write(%r)\n" % (str(MARK), mod))
env = dict(os.environ, PYTHONPATH=str(EVIL))
r = subprocess.run([sys.executable, str(ROOT / "bin" / "shipm"), "--help"], env=env, cwd=str(EVIL), capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
check("m7 bin/shipm ignores a hostile PYTHONPATH and a hostile working folder (no planted module ran)", not MARK.exists() and r.returncode == 0, (MARK.read_text() if MARK.exists() else "", r.returncode, r.stderr[-200:]))
check("m7 ... and it still works (help text printed, package importable from the checkout)", "shipm" in (r.stdout + r.stderr).lower(), (r.stdout[-200:], r.stderr[-200:]))
r2 = subprocess.run([sys.executable, str(ROOT / "bin" / "shipm"), "--help"], env=dict(os.environ), cwd=str(TMP), capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
check("m7 a normal run (no PYTHONPATH) works the same", r2.returncode == 0 and r2.stdout == r.stdout, (r2.returncode, r2.stderr[-200:]))
src = (ROOT / "bin" / "shipm").read_text()
check("m7 the launcher re-executes with -I -S before importing anything of Shipmiracle", '"-I", "-S"' in src and src.index('"-I", "-S"') < src.index("from shipmiracle.cli import main"), src[:600])
# the isolated flags are really on after the re-exec (a probe launcher that reuses the launcher's first lines)
probe = TMP / "probe-launcher"
head = src.split("sys.path.append", 1)[0]
probe.write_text(head + "\nsys.stdout.write('iso=%s site=%s' % (sys.flags.isolated, sys.flags.no_site))\n")
r3 = subprocess.run([sys.executable, str(probe)], env=env, cwd=str(TMP), capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
check("m7 after the re-exec python runs isolated (-I) without site (-S)", "iso=1 site=1" in r3.stdout, (r3.stdout, r3.stderr[-300:]))

# D14 #8: started directly (the shebang is `env -S python3 -IS`) python never reads PYTHONPATH / sitecustomize at all
SC = TMP / "evilsc"
SC.mkdir()
SMARK = TMP / "sitecustomize-ran"
(SC / "sitecustomize.py").write_text("open(%r, 'a').write('sc')\n" % str(SMARK))
(SC / "usercustomize.py").write_text("open(%r, 'a').write('uc')\n" % str(SMARK))
check("#8 the shebang is `env -S python3 -IS`", src.splitlines()[0] == "#!/usr/bin/env -S python3 -IS", src.splitlines()[0])
r4 = subprocess.run([str(ROOT / "bin" / "shipm"), "--help"], env=dict(os.environ, PYTHONPATH=str(SC)), cwd=str(SC), capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
check("#8 direct exec ignores a sitecustomize / usercustomize reachable through PYTHONPATH entirely (nothing ran, help printed)", r4.returncode == 0 and not SMARK.exists() and "shipm" in (r4.stdout + r4.stderr).lower(), (r4.returncode, SMARK.exists(), r4.stderr[-300:]))
r5 = subprocess.run([sys.executable, str(ROOT / "bin" / "shipm"), "--help"], env=dict(os.environ, PYTHONPATH=str(SC)), cwd=str(SC), capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
print("INFO known limit: `python3 bin/shipm` with a sitecustomize on PYTHONPATH -> it ran %s time(s) before the re-exec (rc %d); direct exec avoids it" % (len(SMARK.read_text()) // 2 if SMARK.exists() else 0, r5.returncode))
env_nopath = {k: v for k, v in os.environ.items() if k != "PATH"}
r6 = subprocess.run([sys.executable, "-c", "import os, runpy, sys; sys.executable = ''; runpy.run_path(%r, run_name='__main__')" % str(ROOT / "bin" / "shipm")], capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
check("#8 an empty sys.executable is refused in one line (exit 2), nothing runs", r6.returncode == 2 and "cannot find the python" in r6.stderr, (r6.returncode, r6.stderr[-200:]))
check("#8 the unicode-safe stdout: bin/shipm reconfigures stdout/stderr (errors=backslashreplace)", "backslashreplace" in src)

print("owner_d14: %d failed" % fails)
sys.exit(1 if fails else 0)
