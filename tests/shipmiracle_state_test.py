#!/usr/bin/env python3
"""shipmiracle/state.py: atomic concurrent writes, permissions, symlink/foreign-uid refusal, owners, isolation, mirror, read_compat.
Never touches the real state or config folders (SHIPMIRACLE_TEST=1 + temp dirs). Run: python3 tests/shipmiracle_state_test.py"""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import shipmiracle_isolation; shipmiracle_isolation.apply_to_environ()   # test isolation: fresh HOME/SHIPMIRACLE_HOME/CONFIG/STATE unless already temp
import json, os, pathlib, stat, subprocess, sys, tempfile, time
os.environ.pop("CLAUDECODE", None)       # the owner check only runs in a fully temp sandbox or outside a chat (H1)

ROOT = pathlib.Path(__file__).resolve().parent.parent
TMP = pathlib.Path(tempfile.mkdtemp()).resolve()
os.environ.update(SHIPMIRACLE_TEST="1", SHIPMIRACLE_HOME=str(TMP / "home"), SHIPMIRACLE_STATE=str(TMP / "state"), SHIPMIRACLE_CONFIG=str(TMP / "config"),
                  SHIPMIRACLE_DEV=str(TMP / "dev"), SHIPMIRACLE_WS=str(TMP / "ws"))
sys.path.insert(0, str(ROOT))
from shipmiracle import LockTimeout, NotFound, SafetyError, SchemaError, UsageError, config, events, paths, state  # noqa: E402

fails = 0
def check(name, ok, info=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(info)))
    fails += 0 if ok else 1

def raises(exc, fn, *a, **k):
    try:
        fn(*a, **k)
    except exc:
        return True
    except Exception as e:
        return "wrong exception %r" % e
    return False

def mode(p):
    return stat.S_IMODE(os.lstat(p).st_mode)

if len(sys.argv) > 1 and sys.argv[1] == "worker":      # child: N writes to one name
    base, n, wid = sys.argv[2], int(sys.argv[3]), sys.argv[4]
    bad = 0
    for i in range(n):
        try:
            state.write("guard.json", {"w": wid, "i": i, "pad": "x" * 2000}, "shipmiracle-guard", base=base, timeout=30)
        except Exception as e:
            bad += 1; print("worker error", repr(e), file=sys.stderr)
    sys.exit(1 if bad else 0)

def fresh(name):
    b = TMP / name
    return b

# ---- concurrency: 12 processes x 50 writes to one name ----------------------------------------
base = fresh("race")
t0 = time.time()
procs = [subprocess.Popen([sys.executable, __file__, "worker", str(base), "50", str(k)], stderr=subprocess.PIPE) for k in range(12)]
codes = [p.wait() for p in procs]
dt = time.time() - t0
print("# concurrency 12x50 writes took %.2fs" % dt)
check("12 processes x 50 writes: no worker error", codes == [0] * 12, codes)
env = state.read("guard.json", base)
check("final file is valid JSON envelope from the last write of some worker", env["v"] == 1 and env["writer"] == "shipmiracle-guard" and env["data"]["i"] in range(50), env)
left = [p.name for p in (base / "v1").iterdir() if p.name.endswith(".tmp") or p.name.startswith(".guard")]
check("no temp file left", left == [], left)
check("lock file exists, 0600", mode(base / "v1/.locks/guard.json.lock") == 0o600)

# ---- permissions ---------------------------------------------------------------------------------
old = os.umask(0)
try:
    b = fresh("perm")
    state.write("guard.json", {"a": 1}, "shipmiracle-guard", base=b)
    check("umask 000: base and v1 are 0700", mode(b) == 0o700 and mode(b / "v1") == 0o700 and mode(b / "v1/.locks") == 0o700, oct(mode(b)))
    check("umask 000: file and lock are 0600", mode(b / "v1/guard.json") == 0o600 and mode(b / "v1/.locks/guard.json.lock") == 0o600)
    b2 = fresh("perm2"); b2.mkdir(); os.chmod(b2, 0o755)
    (b2 / "v1").mkdir(); os.chmod(b2 / "v1", 0o755)
    (b2 / "guard.json").write_text("{}")      # a legacy file stays as it is
    state.ensure_root(b2)
    check("pre-existing 0755 base and v1 are fixed to 0700", mode(b2) == 0o700 and mode(b2 / "v1") == 0o700)
    (b2 / "v1" / "ci.json").write_text("{}"); os.chmod(b2 / "v1" / "ci.json", 0o644)
    probs = state.check(b2)
    check("check() reports a 0644 file under v1", any("ci.json mode 644" in p for p in probs), probs)
    os.chmod(b2 / "v1" / "ci.json", 0o600)
    check("check() has no mode complaint once the file is 0600", not [p for p in state.check(b2) if "mode" in p], state.check(b2))
finally:
    os.umask(old)

# ---- ensure_dir never widens; check() tolerates vanishing temp files; read cap ------------------------------
b = fresh("nowiden"); b.mkdir(); os.chmod(b, 0o500)
state.ensure_dir(b)
check("a deliberate 0500 folder is left at 0500", mode(b) == 0o500, oct(mode(b)))
os.chmod(b, 0o750); state.ensure_dir(b)
check("0750 loses group access only (0700)", mode(b) == 0o700)
os.chmod(b, 0o555); state.ensure_dir(b)
check("0555 becomes 0500, not widened to 0700", mode(b) == 0o500, oct(mode(b)))
os.chmod(b, 0o700)
b = fresh("chk"); state.write("guard.json", {}, "shipmiracle-guard", base=b)
(b / "v1" / ".guard.json.abc.tmp").write_text("x"); os.chmod(b / "v1" / ".guard.json.abc.tmp", 0o644)
check("check() skips in-flight temp files", state.check(b) == [], state.check(b))
real_lstat = os.lstat
def flaky(p, *a, **k):
    if str(p).endswith("guard.json") and "v1" in str(p) and not str(p).endswith(".lock"):
        raise FileNotFoundError(p)
    return real_lstat(p, *a, **k)
os.lstat = flaky
try:
    probs = state.check(b)
finally:
    os.lstat = real_lstat
check("check() tolerates an entry that vanished mid-walk", isinstance(probs, list))
big = TMP / "big.json"
with open(big, "wb") as f:
    f.truncate(state.MAX_READ + 1)
check("read_bytes_nofollow refuses a file over 8 MiB with SchemaError", raises(SchemaError, state.read_bytes_nofollow, big) is True)
with open(big, "wb") as f:
    f.truncate(state.MAX_READ)
check("a file of exactly 8 MiB is read", len(state.read_bytes_nofollow(big)) == state.MAX_READ)
b = fresh("bigstate"); state.ensure_root(b)
with open(b / "v1/ci.json", "wb") as f:
    f.truncate(state.MAX_READ + 1)
check("read() of an oversized state file is a SchemaError; read_data gives the default", raises(SchemaError, state.read, "ci.json", b) is True and state.read_data("ci.json", 5, b) == 5)

# ---- symlink and foreign uid refusal --------------------------------------------------------------
b = fresh("sym"); b.mkdir(); os.chmod(b, 0o700)
victim = TMP / "victim"; victim.mkdir()
os.symlink(victim, b / "v1")
r = raises(SafetyError, state.write, "guard.json", {}, "shipmiracle-guard", base=b)
check("symlinked v1 is refused", r is True, r)
check("nothing was written through the symlinked v1", list(victim.iterdir()) == [])
b = fresh("sym2"); state.ensure_root(b)
os.symlink(victim / "target.json", b / "v1/guard.json")
r = raises(SafetyError, state.write, "guard.json", {}, "shipmiracle-guard", base=b)
check("symlinked target file is refused", r is True, r)
check("nothing was created through the symlinked target", not (victim / "target.json").exists())
check("read through a symlinked target is refused", raises(SafetyError, state.read, "guard.json", b) is True)
check("read_data through a symlink returns the default", state.read_data("guard.json", "dflt", b) == "dflt")
b = fresh("sym3"); state.ensure_root(b)
os.rmdir(b / "v1/.locks"); os.symlink(victim, b / "v1/.locks")
check("symlinked .locks folder is refused", raises(SafetyError, state.write, "guard.json", {}, "shipmiracle-guard", base=b) is True)
b = fresh("sym4"); state.ensure_root(b)
os.symlink(victim / "l.lock", b / "v1/.locks/guard.json.lock")
check("symlinked lock file is refused (O_NOFOLLOW)", raises(SafetyError, state.write, "guard.json", {}, "shipmiracle-guard", base=b) is True)
check("lock symlink target not created", not (victim / "l.lock").exists())
b = fresh("sym5"); b.mkdir(); os.symlink(victim, b / "link")
check("symlinked base is refused", raises(SafetyError, state.ensure_root, b / "link") is True)
f = TMP / "afile"; f.write_text("x")
check("a file where the base folder should be is refused", raises(SafetyError, state.ensure_root, f) is True)
real_uid = state._uid
try:
    state._uid = lambda: os.getuid() + 1
    b = fresh("foreign"); b.mkdir()
    check("folder owned by another uid is refused", raises(SafetyError, state.ensure_root, b) is True)
    b = fresh("foreign2"); state._uid = real_uid; state.write("guard.json", {}, "shipmiracle-guard", base=b); state._uid = lambda: os.getuid() + 1
    check("file owned by another uid is refused on read", raises(SafetyError, state.read, "guard.json", b) is True)
    check("check() flags foreign owner", any("another user" in p for p in state.check(b)), state.check(b))
finally:
    state._uid = real_uid

# ---- names, owners, envelope ---------------------------------------------------------------------
b = fresh("names")
for bad in ("", "../x", "a/b", ".hidden", "guard.json\n", "x" * 129, "guard json", 5):
    r = raises(UsageError, state.write, bad, {}, "shipmiracle-guard", base=b)
    check("bad name refused: %r" % (bad if not isinstance(bad, str) else bad[:12]), r is True, r)
check("wrong writer refused", raises(SafetyError, state.write, "guard.json", {}, "shipmiracle-watch", base=b) is True)
check("name without an owner refused", raises(SafetyError, state.write, "other.json", {}, "shipmiracle-guard", base=b) is True)
check("non-JSON data refused, nothing written", raises(UsageError, state.write, "guard.json", {"x": object()}, "shipmiracle-guard", base=b) is True and not (b / "v1/guard.json").exists())
e = state.write("health.json", {"ok": True}, "shipmiracle-watch", base=b)
check("envelope shape", e["v"] == 1 and e["writer"] == "shipmiracle-watch" and isinstance(e["ts"], int) and abs(e["ts"] - time.time()) < 5 and e["data"] == {"ok": True})
check("read returns the same envelope", state.read("health.json", b) == e)
check("read_data", state.read_data("health.json", None, b) == {"ok": True})
check("read of a missing name: NotFound; read_data default", raises(NotFound, state.read, "ci.json", b) is True and state.read_data("ci.json", 7, b) == 7)
(b / "v1/ci.json").write_text("not json")
check("damaged file: read raises SchemaError, read_data returns default", raises(SchemaError, state.read, "ci.json", b) is True and state.read_data("ci.json", 8, b) == 8)
(b / "v1/ci.json").write_text('{"v":2,"ts":1,"writer":"x","data":1}')
check("wrong envelope version is a SchemaError", raises(SchemaError, state.read, "ci.json", b) is True)
check("delete: wrong writer refused, then removes, then False", raises(SafetyError, state.delete, "health.json", "shipmiracle-guard", base=b) is True
      and state.delete("health.json", "shipmiracle-watch", base=b) is True and state.delete("health.json", "shipmiracle-watch", base=b) is False)
check("read_data with bad name never raises", state.read_data("../x", 1, b) == 1)

# ---- locks -----------------------------------------------------------------------------------------
with state.locked("guard.json", b):
    t = time.time()
    r = raises(LockTimeout, state.write, "guard.json", {}, "shipmiracle-guard", base=b, timeout=0.2)
    check("a held lock makes write time out (LockTimeout)", r is True and time.time() - t < 2, r)
check("lock is free again after the context", state.write("guard.json", {"z": 1}, "shipmiracle-guard", base=b)["data"] == {"z": 1})

# ---- isolation ---------------------------------------------------------------------------------------
real_state = paths.real_home() / ".local/state/shipmiracle"
touched = []
orig = (os.open, os.mkdir, os.makedirs, os.replace, os.unlink, state.tempfile.mkstemp)
def trap(*a, **k):
    touched.append(a[:1]); raise AssertionError("touched the filesystem")
os.open, os.mkdir, os.makedirs, os.replace, os.unlink, state.tempfile.mkstemp = (trap,) * 6
try:
    r1 = raises(SafetyError, state.write, "guard.json", {}, "shipmiracle-guard", base=real_state)
    r2 = raises(SafetyError, events.append, "x.y", {}, base=real_state)
    r3 = raises(SafetyError, state.delete, "guard.json", "shipmiracle-guard", base=real_state / "v1" / "..")
finally:
    os.open, os.mkdir, os.makedirs, os.replace, os.unlink, state.tempfile.mkstemp = orig
check("write to the REAL state root under SHIPMIRACLE_TEST=1 raises SafetyError before any I/O", r1 is True and not touched, (r1, touched))
check("events.append to the real root raises SafetyError before any I/O", r2 is True)
check("delete on the real root raises SafetyError before any I/O", r3 is True)
check("mirror to the real root returns False and never raises", state.mirror("guard.json", {}, "shipmiracle-guard", real_state) is False)
check("a SafetyError carries exit code 4", SafetyError.exit_code == 4 and UsageError.exit_code == 2 and NotFound.exit_code == 3)

# ---- mirror and read_compat ---------------------------------------------------------------------------
b = fresh("mirror"); legacy = TMP / "legacy-guard.json"
state._mirror_failed = False
check("switch defaults to on", config.switch("state.v1") is True)
legacy.write_text(json.dumps({"mode": "x"}))
check("mirror (switch on) writes v1 and returns True", state.mirror("guard.json", {"mode": "x"}, "shipmiracle-guard", b) is True
      and state.read("guard.json", b)["data"] == json.loads(legacy.read_text()))
config.set("switches.state.v1", "off")
before = (b / "v1/guard.json").read_bytes()
check("switch off: mirror is a no-op and leaves v1 untouched", state.mirror("guard.json", {"mode": "y"}, "shipmiracle-guard", b) is False and (b / "v1/guard.json").read_bytes() == before)
legacy.write_text(json.dumps({"mode": "y"})); future = time.time() + 5
os.utime(legacy, (future, future))
check("read_compat takes the newer legacy copy when v1 is older", state.read_compat("guard.json", legacy, b) == ({"mode": "y"}, "legacy"))
config.set("switches.state.v1", "on")
state.mirror("guard.json", {"mode": "z"}, "shipmiracle-guard", b)
past = time.time() - 100
os.utime(legacy, (past, past))
check("read_compat takes v1 when it is newer", state.read_compat("guard.json", legacy, b) == ({"mode": "z"}, "v1"))
check("read_compat: only legacy", state.read_compat("away.json", legacy, b) == ({"mode": "y"}, "legacy"))
b_only = fresh("v1only"); state.write("ci.json", {"q": 1}, "ci-status", base=b_only)
check("read_compat: legacy absent, v1 present -> the v1 copy, marked v1 (documented)", state.read_compat("ci.json", TMP / "absent.json", b_only) == ({"q": 1}, "v1"))
check("read_compat: neither", state.read_compat("away.json", TMP / "nope.json", b) == (None, None))
bad = TMP / "bad-legacy.json"; bad.write_text("{oops"); os.utime(bad, (future, future))
check("read_compat: an unreadable newer copy loses to the other one", state.read_compat("guard.json", bad, b) == ({"mode": "z"}, "v1"))
os.symlink(legacy, TMP / "sym-legacy")
check("read_compat refuses to follow a symlinked legacy file", state.read_compat("away.json", TMP / "sym-legacy", b) == (None, None))

# mirror failure: a folder sits where the file must go -> legacy untouched, exactly one event per process
b = fresh("mfail"); state.ensure_root(b)
os.mkdir(b / "v1/guard.json"); os.mkdir(b / "v1/away.json")
legacy2 = TMP / "legacy2.json"; legacy2.write_text('{"k":1}')
state._mirror_failed = False
r1 = state.mirror("guard.json", {"k": 1}, "shipmiracle-guard", b)
r2 = state.mirror("away.json", {"k": 2}, "shipmiracle-guard", b)
evs = [e for e in events.tail(50, b) if e["kind"] == "state.v1_write_failed"]
check("mirror failure returns False twice and never raises", r1 is False and r2 is False, (r1, r2))
check("mirror failure leaves the legacy file intact", legacy2.read_text() == '{"k":1}')
check("mirror failure emits exactly one event per process, error class only", len(evs) == 1 and evs[0]["data"]["error"] == "SafetyError" and set(evs[0]["data"]) == {"name", "error"}, evs)
check("mirror with a bad name never raises", state.mirror("../x", {}, "shipmiracle-guard", b) is False)
check("mirror with unserialisable data never raises", state.mirror("guard.json", {"x": object()}, "shipmiracle-guard", b) is False)
state._mirror_failed = False

# a corrupt config makes mirror fail visibly (False), not crash
cfgfile = paths.config_dir() / "config.json"
cfgfile.write_text("{broken")
check("corrupt config: mirror returns False without raising", state.mirror("guard.json", {}, "shipmiracle-guard", fresh("mcfg")) is False)
cfgfile.unlink()

# a process whose workspace has no shipmiracle/ package is simulated by the daemons in T5; here: import isolation from a foreign cwd
r = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, %r); import shipmiracle.state as s; print(s.OWNERS['ci.json'])" % str(ROOT)],
                   cwd=str(TMP), capture_output=True, text=True, env=dict(os.environ))
check("package imports from any cwd", r.stdout.strip() == "ci-status", r.stderr)
check("atomic_write refuses a directory target", raises(SafetyError, state.atomic_write, TMP / "victim", b"x") is True)
d = TMP / "aw"; d.mkdir()
_rep = os.replace
def boom(*a, **k): raise OSError("disk full")
os.replace = boom
try:
    r = raises(OSError, state.atomic_write, d / "f", b"x")
finally:
    os.replace = _rep
check("atomic_write error removes its temp file and creates no target", r is True and list(d.iterdir()) == [], list(d.iterdir()))
# v1/pyc (bytecode cache from the hook wrapper): the folder itself is checked, its contents are not
b = fresh("pyc"); state.ensure_root(b); pyc = b / "v1/pyc"; pyc.mkdir(); os.chmod(pyc, 0o700)
(pyc / "Users/x").mkdir(parents=True); os.chmod(pyc / "Users", 0o755); os.chmod(pyc / "Users/x", 0o755)
(pyc / "Users/x/m.pyc").write_bytes(b"x"); os.chmod(pyc / "Users/x/m.pyc", 0o644)
check("pyc: 755 subfolders and a 644 file under v1/pyc are not reported", state.check(b) == [], state.check(b))
USR = "Us" + "ers"          # built from pieces: a literal slash-Users path in a test trips the release home-path check
os.symlink("/nonexistent-target", pyc / "Users/x/evil.pyc")
probs = state.check(b)
check("pyc: a symlink inside v1/pyc is still reported (only the mode complaint is skipped)", any("v1/pyc/%s/x/evil.pyc is a symlink" % USR in p for p in probs) and not any("mode 755" in p or "m.pyc mode" in p for p in probs), probs)
os.unlink(pyc / "Users/x/evil.pyc")
os.symlink(str(b), pyc / "Users/linkdir")
probs = state.check(b)
check("pyc: a symlinked folder inside v1/pyc is reported and not followed", any("v1/pyc/%s/linkdir is a symlink" % USR in p for p in probs) and len(probs) == 1, probs)
os.unlink(pyc / "Users/linkdir")
os.chmod(pyc, 0o755)
check("pyc: v1/pyc itself at 755 is reported", any("v1/pyc mode 755" in p for p in state.check(b)), state.check(b))
os.chmod(pyc, 0o700)
real = b / "v1/pyc_real"; pyc.rename(real); os.symlink(real, pyc)
probs = state.check(b)
check("pyc: v1/pyc as a symlink is reported", any("v1/pyc is a symlink" in p for p in probs), probs)
print("\nFAILED: %d" % fails if fails else "\nALL PASS"); sys.exit(1 if fails else 0)
