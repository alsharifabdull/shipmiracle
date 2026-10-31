"""Shared isolation for test runs (not a test; test-all only runs *_test.py). A test, and every process it starts, must never reach the user's real
~/.claude, ~/.config/shipmiracle or ~/.local/state/shipmiracle: Shipmiracle's home() ignores $HOME on purpose, so HOME alone is NOT isolation. This helper builds the FULL set,
in fresh folders under the system temp folder:
    SHIPMIRACLE_TEST=1  HOME  SHIPMIRACLE_HOME  CLAUDE_CONFIG_DIR  SHIPMIRACLE_CONFIG  SHIPMIRACLE_STATE  SHIPMIRACLE_WS  SHIPMIRACLE_DEV   (+ AGENT_BROWSER_ARGS, a minimal git identity in the fake HOME)
Use:  env, root = isolated_env(); subprocess.run([...], env=env); cleanup(root)
      or  with isolated() as env: subprocess.run([...], env=env)
release-check's isolation lint accepts a tests file that imports this module (or tests/shipmiracle_timing.py, tests/chrome_helper.js, tests/setup_fixture.py)."""
import contextlib, json, os, re, shutil, tempfile

BROWSER_ARGS = "--use-mock-keychain,--password-store=basic"
KEEP = {"SHIPMIRACLE_ENFORCE_LEGACY_HOOKS", "SHIPMIRACLE_TEST_TIMEOUT", "SHIPMIRACLE_TEST_JOBS", "SHIPMIRACLE_CHROME"}     # the only SHIPMIRACLE_* variables a caller may pass through
DROP = {"CLAUDECODE", "CLAUDE_CONFIG_DIR", "HOME"}


def isolated_env(base=None, ws=None, root=None):
    """(env, root): a copy of `base` (default os.environ) with every shipmiracle/Claude location pointed into a fresh temp folder `root`. `ws`: a read-only
    workspace for the suite (default: an empty fresh folder). The caller removes `root` with cleanup()."""
    require_fixed_tmpdir()
    base = dict(os.environ if base is None else base)
    env = {k: v for k, v in base.items() if k not in DROP and not (k.startswith("SHIPMIRACLE_") and k not in KEEP)}
    root = root or tempfile.mkdtemp(prefix="shipmiracle-iso-")
    d = os.path.realpath(root)
    for sub in ("h/.claude", "c", "s", "w", "dev"):
        os.makedirs(os.path.join(d, sub), exist_ok=True)
    gc = os.path.join(d, "h", ".gitconfig")
    if not os.path.exists(gc):
        with open(gc, "w") as f:
            f.write("[user]\n\tname = Shipmiracle test\n\temail = test@example.com\n[init]\n\tdefaultBranch = main\n[commit]\n\tgpgsign = false\n")
    env.update(SHIPMIRACLE_TEST="1", HOME=d + "/h", SHIPMIRACLE_HOME=d + "/h", CLAUDE_CONFIG_DIR=d + "/h/.claude", SHIPMIRACLE_CONFIG=d + "/c", SHIPMIRACLE_STATE=d + "/s",
               SHIPMIRACLE_WS=str(ws) if ws else d + "/w", SHIPMIRACLE_DEV=d + "/dev", AGENT_BROWSER_ARGS=BROWSER_ARGS, GIT_CONFIG_NOSYSTEM="1")
    return env, root


def settings_change_is_ours(old_text, new_text):
    """Same rule as bin/test-all: True (a real failure) when the change to the REAL ~/.claude/settings.json holds a temp-folder path or adds/removes a Shipmiracle hook entry (or a
    version cannot be read); False for any other edit, which is what ANOTHER live Claude session rewriting the file looks like (it cannot be told apart by a hash)."""
    def leaves(o, under=False, out=None, hooks=None):
        out = set() if out is None else out
        hooks = set() if hooks is None else hooks
        if isinstance(o, dict):
            for k, v in o.items():
                leaves(v, under or k == "hooks", out, hooks)
        elif isinstance(o, list):
            for v in o:
                leaves(v, under, out, hooks)
        elif isinstance(o, str):
            out.add(o)
            if under:
                hooks.add(o)
        return out, hooks
    try:
        old, new = json.loads(old_text), json.loads(new_text)
    except (TypeError, ValueError):
        return True
    ao, ho = leaves(old)
    an, hn = leaves(new)
    temps = ("/tmp/", "/private/tmp/", "/var/folders/", "/private/var/folders/")
    if any(any(t in x for t in temps) for x in ao ^ an):
        return True
    return any(re.search(r"shipm", x, re.I) for x in ho ^ hn)


def cleanup(root):
    shutil.rmtree(root, ignore_errors=True)


@contextlib.contextmanager
def isolated(base=None, ws=None):
    env, root = isolated_env(base, ws)
    try:
        yield env
    finally:
        cleanup(root)


def _under_temp(p):
    r = os.path.realpath(str(p))
    roots = {os.path.realpath(x) for x in ("/tmp", "/private/tmp", "/var/folders", "/private/var/folders")}
    return any(r == t or r.startswith(t.rstrip("/") + "/") for t in roots)


def require_fixed_tmpdir():
    """Abort when $TMPDIR (where mkdtemp puts the sandbox) is not under a FIXED temp root: the product no longer trusts $TMPDIR, so such a sandbox would not count as one."""
    if not _under_temp(tempfile.gettempdir()):
        raise SystemExit("shipmiracle_isolation: TMPDIR/gettempdir %r is not under /tmp or /var/folders; refusing to run (set TMPDIR to a folder there)" % tempfile.gettempdir())


def apply_to_environ():
    """Called at the top of a test file: fill in the isolation a test run lacks, in THIS process, so every child it starts inherits it. Each of SHIPMIRACLE_TEST, HOME,
    SHIPMIRACLE_HOME, CLAUDE_CONFIG_DIR, SHIPMIRACLE_CONFIG, SHIPMIRACLE_STATE that is unset or points outside the system temp folder gets a fresh temp folder (removed at exit); values that are
    already temp folders (set by test-all or by the test) are kept. SHIPMIRACLE_WS and SHIPMIRACLE_DEV are left alone (an unset SHIPMIRACLE_WS means the repo, which shipm treats as read-only
    under SHIPMIRACLE_TEST=1). Returns the fresh root or None."""
    require_fixed_tmpdir()
    e = os.environ
    state = {"root": None}

    def fresh(sub):
        if state["root"] is None:
            state["root"] = os.path.realpath(tempfile.mkdtemp(prefix="shipmiracle-iso-"))
            import atexit
            atexit.register(cleanup, state["root"])
            os.makedirs(state["root"] + "/h/.claude", exist_ok=True)
            with open(state["root"] + "/h/.gitconfig", "w") as f:
                f.write("[user]\n\tname = Shipmiracle test\n\temail = test@example.com\n[init]\n\tdefaultBranch = main\n[commit]\n\tgpgsign = false\n")
        return state["root"] + "/" + sub
    e["SHIPMIRACLE_TEST"] = "1"
    for var, sub in (("HOME", "h"), ("SHIPMIRACLE_HOME", "h"), ("CLAUDE_CONFIG_DIR", "h/.claude"), ("SHIPMIRACLE_CONFIG", "c"), ("SHIPMIRACLE_STATE", "s")):
        v = e.get(var)
        if not v or not _under_temp(v):
            e[var] = fresh(sub)
    e.setdefault("AGENT_BROWSER_ARGS", BROWSER_ARGS)
    return state["root"]


def mac_platform_off_mac(reason="this suite checks the macOS branch (launchd, osascript, caffeinate, pbcopy stubs)"):
    """For a suite that tests the macOS branch of the platform layer: on any other OS tell the layer (SHIPMIRACLE_FAKE_OS=macos, honoured only under SHIPMIRACLE_TEST=1) to take
    its macOS branch, and print why. Call it at the top, BEFORE any environment copy is made. The Linux branches have their own suites (platform_test, linux_gate_test, ...)."""
    import sys
    if sys.platform != "darwin":
        os.environ["SHIPMIRACLE_FAKE_OS"] = "macos"
        print("NOTE: not a Mac (%s): SHIPMIRACLE_FAKE_OS=macos; %s" % (sys.platform, reason))


def set_xattr(path, name="com.shipmiracle.test", value="1"):
    """Put one extended attribute on `path`: macOS `xattr -w`; Linux os.setxattr (user.<name>). False when this file system cannot hold one (printed once)."""
    import subprocess, sys
    if sys.platform == "darwin":
        return subprocess.run(["xattr", "-w", name, value, str(path)], capture_output=True).returncode == 0
    try:
        os.setxattr(str(path), "user." + name, value.encode())
        return True
    except (AttributeError, OSError) as e:
        print("NOTE: extended attributes are not available on this file system (%s); the xattr part of the check is skipped" % type(e).__name__)
        return False


def list_xattrs(path):
    """Sorted names of the extended attributes of `path` (macOS `xattr`, Linux os.listxattr); [] when there are none or they cannot be read."""
    import subprocess, sys
    if sys.platform == "darwin":
        try:
            return sorted(subprocess.run(["xattr", str(path)], capture_output=True, text=True).stdout.split())
        except OSError:
            return []
    try:
        return sorted(os.listxattr(str(path)))
    except (AttributeError, OSError):
        return []
