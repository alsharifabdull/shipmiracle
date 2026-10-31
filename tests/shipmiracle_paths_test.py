#!/usr/bin/env python3
"""shipmiracle/paths.py: overrides only under SHIPMIRACLE_TEST=1, fold, claude_dirname, main_checkout, assert_isolated. Run: python3 tests/shipmiracle_paths_test.py"""
import os, pathlib, pwd, sys, tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from shipmiracle import SafetyError, paths  # noqa: E402

fails = 0
def check(name, ok, info=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(info)))
    fails += 0 if ok else 1

tmp = pathlib.Path(tempfile.mkdtemp()).resolve()
real = pathlib.Path(pwd.getpwuid(os.getuid()).pw_dir)

# without SHIPMIRACLE_TEST the overrides are ignored
for v in ("SHIPMIRACLE_TEST", "SHIPMIRACLE_HOME", "SHIPMIRACLE_DEV", "SHIPMIRACLE_STATE", "SHIPMIRACLE_WS", "SHIPMIRACLE_CONFIG"):
    os.environ.pop(v, None)
os.environ.update(SHIPMIRACLE_HOME=str(tmp / "h"), SHIPMIRACLE_DEV=str(tmp / "d"), SHIPMIRACLE_STATE=str(tmp / "s"), SHIPMIRACLE_CONFIG=str(tmp / "c"), SHIPMIRACLE_WS=str(tmp / "w"))
os.environ["HOME"] = str(tmp / "fakehome")
check("real_home ignores $HOME", paths.real_home() == real, paths.real_home())
check("overrides ignored without SHIPMIRACLE_TEST", paths.home() == real and paths.dev_dir() == real / "Developer"
      and paths.state_dir() == real / ".local/state/shipmiracle" and paths.config_dir() == real / ".config/shipmiracle"
      and paths.workspace_dir() == ROOT)
os.environ["SHIPMIRACLE_TEST"] = "0"
check("SHIPMIRACLE_TEST=0 is not test mode", paths.home() == real)
os.environ["SHIPMIRACLE_TEST"] = "1"
check("overrides honoured under SHIPMIRACLE_TEST=1", paths.home() == tmp / "h" and paths.dev_dir() == tmp / "d" and paths.state_dir() == tmp / "s"
      and paths.config_dir() == tmp / "c" and paths.workspace_dir() == tmp / "w")
check("test_override default is returned as Path", paths.test_override("SHIPMIRACLE_NOPE", "/x") == pathlib.Path("/x"))
del os.environ["SHIPMIRACLE_HOME"]
check("home() derives dev/state/config from SHIPMIRACLE_HOME only", paths.dev_dir() == tmp / "d")
os.environ.pop("SHIPMIRACLE_DEV")
check("SHIPMIRACLE_TEST=1 without SHIPMIRACLE_HOME and a HOME under a temp folder: home() is that HOME (a HOME-only sandbox never reaches the real home)", paths.home() == tmp / "fakehome")
os.environ["HOME"] = str(real)
check("dev defaults to ~/Developer", paths.dev_dir() == real / "Developer")
decoy = tmp / "decoy"; os.environ["SHIPMIRACLE_REAL_HOME"] = str(decoy); os.environ["HOME"] = str(decoy)
check("SHIPMIRACLE_REAL_HOME is the test seam for real_home() (SHIPMIRACLE_TEST=1 only)", paths.real_home() == decoy and paths.home() == decoy)
try:
    paths.assert_not_real_claude(decoy / ".claude" / "settings.json"); r = None
except SafetyError as e:
    r = e
check("assert_not_real_claude raises SafetyError for <real home>/.claude/settings.json", r is not None, r)
paths.assert_not_real_claude(tmp / "elsewhere" / "settings.json")
os.environ["SHIPMIRACLE_TEST"] = "0"
check("SHIPMIRACLE_REAL_HOME is ignored without SHIPMIRACLE_TEST=1", paths.real_home() == real)
os.environ["SHIPMIRACLE_TEST"] = "1"
# L3: SHIPMIRACLE_REAL_HOME counts only when it is under a temp root AND differs from the passwd home
for bad, why in (("/srv/shipmiracle-nonexistent-decoy", "outside a temp root"), (str(real), "the passwd home itself"), ("/opt/shipmiracle-decoy", "outside a temp root (/opt)")):
    os.environ["SHIPMIRACLE_REAL_HOME"] = bad
    check("L3 SHIPMIRACLE_REAL_HOME ignored: %s" % why, paths.real_home() == real, paths.real_home())
os.environ["SHIPMIRACLE_REAL_HOME"] = str(decoy)
check("L3 SHIPMIRACLE_REAL_HOME under a temp root and not the passwd home is honoured", paths.real_home() == decoy)
os.environ.pop("SHIPMIRACLE_REAL_HOME"); os.environ["HOME"] = str(real)

check("claude_dirname", paths.claude_dirname("/Users/a.b/Developer/X y") == "-Users-a-b-Developer-X-y")
check("fold is case-insensitive on macOS only", (paths.fold("/A/b") == paths.fold("/a/B")) == (sys.platform == "darwin"))

# main_checkout: plain dir, worktree .git file, junk
plain = tmp / "plain"; plain.mkdir()
check("main_checkout of a plain folder is itself", paths.main_checkout(plain) == plain)
wt = tmp / "wt"; wt.mkdir()
(wt / ".git").write_text("gitdir: /x/main/.git/worktrees/wt\n")
check("main_checkout follows the .git file", paths.main_checkout(wt) == pathlib.Path("/x/main"), paths.main_checkout(wt))
(wt / ".git").write_text("garbage\n")
check("main_checkout ignores a junk .git file", paths.main_checkout(wt) == wt)
(wt / ".git").write_text("")
check("main_checkout ignores an empty .git file", paths.main_checkout(wt) == wt)

# relative gitdir (git worktree --relative-paths) resolves against the .git file's folder, not the cwd
rel = tmp / "relwt"; rel.mkdir()
(rel / ".git").write_text("gitdir: ../main/.git/worktrees/relwt\n")
here = os.getcwd()
os.chdir("/")
try:
    check("main_checkout resolves a relative gitdir against the worktree folder", paths.main_checkout(rel) == tmp / "main", paths.main_checkout(rel))
finally:
    os.chdir(here)
import shutil, subprocess
if shutil.which("git"):
    mr = tmp / "gitmain"; subprocess.run(["git", "init", "-q", str(mr)], check=True)
    subprocess.run(["git", "-C", str(mr), "-c", "user.email=a@b.c", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "i"], check=True)
    wtp = tmp / "gitwt"
    r = subprocess.run(["git", "-C", str(mr), "worktree", "add", "-q", "--relative-paths", str(wtp)], capture_output=True, text=True)
    if r.returncode == 0:
        gl = (wtp / ".git").read_text()
        check("fixture: git wrote a relative gitdir", not gl.split(":", 1)[1].strip().startswith("/"), gl)
        os.chdir("/")
        try:
            check("main_checkout of a real --relative-paths worktree is the main repo", paths.main_checkout(wtp).resolve() == mr.resolve(), paths.main_checkout(wtp))
        finally:
            os.chdir(here)
    else:
        print("# git has no worktree --relative-paths here; hand-made fixture only")

# fold: NFC on macOS
nfd, nfc = "/Dev/Cafe\u0301", "/dev/caf\u00e9"
check("fold treats NFD and NFC spellings alike on macOS (and keeps them apart elsewhere)", (paths.fold(nfd) == paths.fold(nfc)) == (sys.platform == "darwin"))

# assert_isolated: resolves only, never touches
real_state, real_cfg = real / ".local/state/shipmiracle", real / ".config/shipmiracle"
def raises(p):
    try:
        paths.assert_isolated(p)
    except SafetyError:
        return True
    return False
check("assert_isolated refuses the real state folder and below", raises(real_state) and raises(real_state / "v1" / "x") and raises(str(real_state) + "/a/../b"))
check("assert_isolated refuses the real config folder", raises(real_cfg / "config.json"))
check("assert_isolated allows temp paths and look-alikes", not raises(tmp / "s") and not raises(str(real_state) + "-other"))
link = tmp / "link"; os.symlink(real_state, link)
check("assert_isolated sees through a symlink into the real folder", raises(link / "v1"))
os.environ["SHIPMIRACLE_TEST"] = "0"
check("assert_isolated is a no-op outside tests", not raises(real_state))

# ---- P5 security H1: the owner check is skipped only in a FULLY temp sandbox ----
def owner_refused(extra, drop=()):
    # location-independent: the only "temp" root is this test's own folder, so a checkout under /tmp or ~ is a real (non-temp) workspace either way
    _roots0 = paths._temp_roots
    paths._temp_roots = lambda: [os.path.realpath(str(tmp))]
    env_keys = ("SHIPMIRACLE_TEST", "SHIPMIRACLE_HOME", "SHIPMIRACLE_DEV", "SHIPMIRACLE_STATE", "SHIPMIRACLE_WS", "SHIPMIRACLE_CONFIG", "SHIPMIRACLE_ENFORCE_OWNER", "CLAUDECODE")
    saved = {k: os.environ.get(k) for k in env_keys + ("HOME",)}
    try:
        for k in env_keys + ("HOME",):
            os.environ.pop(k, None)
        full = dict(SHIPMIRACLE_TEST="1", SHIPMIRACLE_CONFIG=str(tmp / "c"), SHIPMIRACLE_STATE=str(tmp / "s"), SHIPMIRACLE_WS=str(tmp / "w"), SHIPMIRACLE_DEV=str(tmp / "d"), HOME=str(tmp / "h"), CLAUDECODE="1")
        for k in drop:
            full.pop(k, None)
        full.update(extra)
        os.environ.update(full)
        try:
            paths.require_owner("x")
            return False
        except SafetyError:
            return True
    finally:
        paths._temp_roots = _roots0
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
check("H1: fully temp sandbox + CLAUDECODE: owner check skipped (tests run inside chats)", not owner_refused({}))
check("H1: only SHIPMIRACLE_CONFIG and SHIPMIRACLE_STATE in temp (SHIPMIRACLE_WS, SHIPMIRACLE_DEV, HOME unset): refused", owner_refused({}, drop=("SHIPMIRACLE_WS", "SHIPMIRACLE_DEV", "HOME")))
check("H1: SHIPMIRACLE_WS unset: refused", owner_refused({}, drop=("SHIPMIRACLE_WS",)))
check("H1: SHIPMIRACLE_DEV unset: refused", owner_refused({}, drop=("SHIPMIRACLE_DEV",)))
check("H1: HOME unset: refused", owner_refused({}, drop=("HOME",)))
check("H1: SHIPMIRACLE_WS is the real workspace: refused", owner_refused({"SHIPMIRACLE_WS": str(ROOT)}))
check("H1: HOME is the real home: refused", owner_refused({"HOME": str(real)}))
check("H1: SHIPMIRACLE_ENFORCE_OWNER=1 still refuses in a full sandbox", owner_refused({"SHIPMIRACLE_ENFORCE_OWNER": "1"}))
check("H1: no SHIPMIRACLE_TEST: refused", owner_refused({"SHIPMIRACLE_TEST": "0"}))

print("\nFAILED: %d" % fails if fails else "\nALL PASS"); sys.exit(1 if fails else 0)
