#!/usr/bin/env python3
"""Settings isolation (public): no test-style invocation of Shipmiracle may ever write the user's real ~/.claude/settings.json.
The 'real' home is a DECOY folder (SHIPMIRACLE_REAL_HOME, honoured only under SHIPMIRACLE_TEST=1). Each case runs Shipmiracle the way a QA run once did (HOME only; SHIPMIRACLE_HOME only;
the full set; `shipm sync --hooks v1` without SHIPMIRACLE_HOME) and asserts the decoy settings.json is byte-for-byte unchanged and that bad targets are refused.
Run: python3 tests/settings_isolation_test.py"""
import hashlib, json, os, pathlib, shutil, subprocess, sys, tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
TMP = pathlib.Path(tempfile.mkdtemp(prefix="shipmiracle-iso-")).resolve()
fails = 0
def check(name, ok, info=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(info)[:600]))
    fails += 0 if ok else 1

DECOY = TMP / "decoy-home"
(DECOY / ".claude").mkdir(parents=True)
DSET = DECOY / ".claude" / "settings.json"
DSET.write_text(json.dumps({"model": "opusplan", "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "/opt/keep/me.sh"}]}]}}, indent=2) + "\n")
DSET.chmod(0o600)
def fp():
    return hashlib.sha256(DSET.read_bytes()).hexdigest(), DSET.stat().st_mtime_ns
BEFORE = fp()

def fresh(name):
    d = TMP / name
    for sub in ("h/.claude", "c", "s", "dev"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    return d

def run(env_extra, *args, drop=()):
    env = {k: v for k, v in os.environ.items() if not k.startswith("SHIPMIRACLE_") and k not in ("CLAUDECODE", "CLAUDE_CONFIG_DIR", "HOME") and k not in drop}
    env.update({"SHIPMIRACLE_TEST": "1", "SHIPMIRACLE_REAL_HOME": str(DECOY), "SHIPMIRACLE_WS": str(ROOT)})
    env.update(env_extra)
    r = subprocess.run([sys.executable, str(ROOT / "bin" / "shipm")] + list(args), env=env, capture_output=True, text=True, timeout=90, stdin=subprocess.DEVNULL)
    return r.returncode, r.stdout, r.stderr

def isolated_dirs(d):
    return {"SHIPMIRACLE_CONFIG": str(d / "c"), "SHIPMIRACLE_STATE": str(d / "s"), "SHIPMIRACLE_DEV": str(d / "dev")}

# 1. HOME only (the QA mistake): HOME is a temp folder, SHIPMIRACLE_HOME is NOT set -> Shipmiracle uses HOME, never the real home
d = fresh("homeonly")
rc, out, err = run(dict(isolated_dirs(d), HOME=str(d / "h")), "sync", "--hooks", "v1")
check("HOME-only sandbox: sync succeeds in the temp HOME and the decoy real settings.json is byte-identical", rc == 0 and fp() == BEFORE and (d / "h/.claude/settings.json").is_file(), (rc, out[-200:], err[-300:]))
# 2. SHIPMIRACLE_HOME only
d = fresh("shipmiraclehome")
rc, out, err = run(dict(isolated_dirs(d), SHIPMIRACLE_HOME=str(d / "h")), "sync", "--hooks", "v1")
check("SHIPMIRACLE_HOME-only sandbox: decoy unchanged, settings written under SHIPMIRACLE_HOME", rc == 0 and fp() == BEFORE and (d / "h/.claude/settings.json").is_file(), (rc, err[-300:]))
# 3. the full set
d = fresh("full")
rc, out, err = run(dict(isolated_dirs(d), SHIPMIRACLE_HOME=str(d / "h"), HOME=str(d / "h"), CLAUDE_CONFIG_DIR=str(d / "h/.claude")), "sync", "--hooks", "v1")
check("full isolation set: decoy unchanged", rc == 0 and fp() == BEFORE, (rc, err[-300:]))
# 4. shipm sync --hooks v1 WITHOUT SHIPMIRACLE_HOME where HOME is the (decoy) real home: refused
d = fresh("nohome")
for mode in ("v1", "shadow", "legacy", "off"):
    rc, out, err = run(dict(isolated_dirs(d), HOME=str(DECOY)), "sync", "--hooks", mode)
    check("shipm sync --hooks %s without SHIPMIRACLE_HOME while HOME is the real home: refused, decoy unchanged" % mode, rc != 0 and fp() == BEFORE and ("real home" in err + out or "refused" in err + out), (rc, out[-200:], err[-300:]))
# 5. repair against the real home is refused too
rc, out, err = run(dict(isolated_dirs(d), HOME=str(DECOY)), "sync", "--repair-hooks", "--apply")
check("shipm sync --repair-hooks --apply on the real home under SHIPMIRACLE_TEST=1: refused", rc != 0 and fp() == BEFORE, (rc, out, err[-300:]))
# 6. CLAUDE_CONFIG_DIR pointing at the real .claude
d = fresh("ccd")
rc, out, err = run(dict(isolated_dirs(d), SHIPMIRACLE_HOME=str(d / "h"), CLAUDE_CONFIG_DIR=str(DECOY / ".claude")), "sync", "--hooks", "v1")
check("CLAUDE_CONFIG_DIR resolving into the real .claude: refused, decoy unchanged", rc != 0 and fp() == BEFORE, (rc, err[-300:]))
# 7. HOME outside every temp folder and no SHIPMIRACLE_HOME: writers refuse
def under_temp(p):
    import tempfile as t
    return any(os.path.realpath(str(p)).startswith(os.path.realpath(r)) for r in {t.gettempdir(), "/tmp", "/private/tmp", "/var/folders", "/private/var/folders"})
if not under_temp(ROOT):
    d = fresh("nontemp")
    nt = ROOT / "tests" / "_never_written_home"
    rc, out, err = run(dict(isolated_dirs(d), HOME=str(nt)), "sync", "--hooks", "v1")
    check("no SHIPMIRACLE_HOME and a HOME outside every temp folder: writers refuse, no .claude or state created", rc != 0 and not (nt / ".claude").exists() and not (nt / ".local").exists() and fp() == BEFORE, (rc, err[-300:]))
    shutil.rmtree(nt, ignore_errors=True)
# 8. in-process: a direct write into the decoy .claude is refused
os.environ.update({"SHIPMIRACLE_TEST": "1", "SHIPMIRACLE_REAL_HOME": str(DECOY), "SHIPMIRACLE_HOME": str(TMP / "inproc-h"), "SHIPMIRACLE_STATE": str(TMP / "inproc-s")})
os.environ.pop("CLAUDECODE", None)
sys.path.insert(0, str(ROOT))
from shipmiracle import SafetyError, paths, settings_sync as ss  # noqa: E402
check("paths.real_home() honours SHIPMIRACLE_REAL_HOME only under SHIPMIRACLE_TEST=1", paths.real_home() == DECOY)
try:
    ss.apply(path=DSET, mode="v1", ws=ROOT); r = None
except SafetyError as x:
    r = str(x)
check("settings_sync.apply(path=<real home>/.claude/settings.json) raises SafetyError", r is not None and fp() == BEFORE, r)
try:
    ss.repair(path=DSET, apply=True); r = None
except SafetyError as x:
    r = str(x)
check("settings_sync.repair(apply=True) on the real home raises SafetyError", r is not None and fp() == BEFORE, r)
# 9. sandbox markers without SHIPMIRACLE_TEST: a subprocess that lost SHIPMIRACLE_TEST but kept a temp HOME / CLAUDE_CONFIG_DIR still may not write the real folders
#    (pure path checks only: nothing is written; the real home here is the password-database home, no decoy needed because no write happens)
import pwd
from shipmiracle import state  # noqa: E402
REALH = pathlib.Path(pwd.getpwuid(os.getuid()).pw_dir)
def guard_raises(path):
    try:
        paths.guard_real_write(path); return False
    except SafetyError:
        return True
os.environ.pop("SHIPMIRACLE_REAL_HOME", None); os.environ.pop("SHIPMIRACLE_TEST", None)
os.environ["HOME"] = str(TMP / "tmphome"); os.environ.pop("CLAUDE_CONFIG_DIR", None)
check("no SHIPMIRACLE_TEST, HOME in a temp folder: a write into the real ~/.claude, ~/.config/shipmiracle or ~/.local/state/shipmiracle is refused", all(guard_raises(REALH / x) for x in (".claude/settings.json", ".config/shipmiracle/config.json", ".local/state/shipmiracle/v1/events.jsonl")))
check("no SHIPMIRACLE_TEST, HOME in a temp folder: other places are fine", not guard_raises(TMP / "x" / "y.json"))
os.environ["HOME"] = str(REALH); os.environ["CLAUDE_CONFIG_DIR"] = str(TMP / "ccd")
check("no SHIPMIRACLE_TEST, real HOME but CLAUDE_CONFIG_DIR in a temp folder: still refused", guard_raises(REALH / ".claude/settings.json"))
os.environ.pop("CLAUDE_CONFIG_DIR")
check("a normal owner run (real HOME, no marker): the guard does not interfere", not guard_raises(REALH / ".claude/settings.json"))
# the central writer (state.atomic_write) refuses the decoy's folders in a sandbox run and nothing is written
os.environ.update({"SHIPMIRACLE_TEST": "1", "SHIPMIRACLE_REAL_HOME": str(DECOY), "HOME": str(TMP / "tmphome")})
refused = []
for rel in (".claude/settings.json", ".claude/agents/x.md", ".config/shipmiracle/config.json", ".local/state/shipmiracle/v1/x.json"):
    try:
        (DECOY / rel).parent.mkdir(parents=True, exist_ok=True)
        state.atomic_write(DECOY / rel, b"{}", 0o600); refused.append(False)
    except SafetyError:
        refused.append(True)
check("state.atomic_write refuses every real-home folder (settings, agents, config, state) in a sandbox run", all(refused) and fp() == BEFORE and not (DECOY / ".config/shipmiracle/config.json").exists(), refused)
with paths.allow_real_writes():
    state.atomic_write(DECOY / ".config/shipmiracle/emergency.json", b"{}", 0o600)
check("the emergency context (test-all cleanup) is the only way through", (DECOY / ".config/shipmiracle/emergency.json").exists())
(DECOY / ".config/shipmiracle/emergency.json").unlink()

os.environ.pop("SHIPMIRACLE_TEST")
check("without SHIPMIRACLE_TEST=1 the seam is ignored (real_home() is the password-database home)", paths.real_home() != DECOY)
check("the decoy real settings.json is still byte-identical at the end", fp() == BEFORE)

shutil.rmtree(TMP, ignore_errors=True)
print("\nALL PASS" if not fails else "\n%d FAILED" % fails); sys.exit(1 if fails else 0)
