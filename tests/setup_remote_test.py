#!/usr/bin/env python3
"""Remote Control opt-in (init row 14, optional): settings_sync.set_remote_control / remote_control_state / undo_remote_control, the row's probe (green on, skipped off,
never red), the typed-yes apply, the manifest step with before/after, `shipm init --undo remote-control`, `shipm uninstall`, the decoy-real-home refusals, and the panel's
read-only `remote` field. Everything runs in fresh isolated folders (tests/shipmiracle_isolation.py); a fingerprint of the real ~/.claude/settings.json is compared at the end.
Run: python3 tests/setup_remote_test.py"""
import hashlib, json, os, pathlib, stat, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import shipmiracle_isolation as ISO  # noqa: E402

ENV, TMP = ISO.isolated_env(ws=ROOT)
TMP = pathlib.Path(TMP)
REAL_SETTINGS = pathlib.Path(__import__("pwd").getpwuid(os.getuid()).pw_dir) / ".claude" / "settings.json"
def real_sha():
    try:
        return hashlib.sha256(REAL_SETTINGS.read_bytes()).hexdigest()
    except OSError:
        return "absent"
REAL_BEFORE = real_sha()
os.environ.update(ENV)
ENV.pop("CLAUDECODE", None)
HOME = pathlib.Path(ENV["SHIPMIRACLE_HOME"]); S = HOME / ".claude" / "settings.json"
STATE = pathlib.Path(ENV["SHIPMIRACLE_STATE"]); CFG = pathlib.Path(ENV["SHIPMIRACLE_CONFIG"])

from shipmiracle import SafetyError, SchemaError, settings_sync as SS  # noqa: E402

fails = 0
def check(name, ok, info=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(info)[:700]))
    fails += 0 if ok else 1

def shipm(*args, extra=None):
    e = dict(ENV); e.update(extra or {})
    r = subprocess.run([sys.executable, str(ROOT / "bin" / "shipm")] + list(args), env=e, capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)
    return r.returncode, r.stdout, r.stderr

def rows():
    rc, out, err = shipm("init", "--check", "--json")
    return {r["id"]: r for r in json.loads(out)["rows"]}

def xattrs(p):
    return " ".join(ISO.list_xattrs(p))

def put(text, mode=0o600):
    S.parent.mkdir(parents=True, exist_ok=True)
    if S.is_symlink() or S.exists():
        S.unlink()
    S.write_text(text); S.chmod(mode)

def raises(fn, exc):
    try:
        fn()
    except exc:
        return True
    except Exception as e:
        return "other:" + type(e).__name__
    return False

ORIG = '{\n  "model": "opusplan",\n  "disableRemoteControl": false,\n  "permissions": {"allow": ["Bash(ls:*)"]},\n  "env": {"A": "\\u00e9"}\n}\n'

# ---------------------------------------------------------------- 1. the writer: byte-faithful insertion
put(ORIG, 0o640)
check("1 state off when the key is absent", SS.remote_control_state() == "off")
res = SS.set_remote_control(True)
new = S.read_bytes()
check("1 changed, key true, backup 0600 with the old bytes", res["changed"] and res["before"] is None and res["after"] is True and SS.remote_control_state() == "on"
      and pathlib.Path(res["backup"]).read_bytes() == ORIG.encode() and stat.S_IMODE(os.stat(res["backup"]).st_mode) == 0o600, res)
check("1 byte-faithful: the old text is a prefix up to the last member, the tail is only the new member and the closing brace",
      new.decode().startswith(ORIG[:ORIG.rindex("}")].rstrip()) and new.decode().endswith(',\n  "remoteControlAtStartup": true\n}\n'), new)
d = json.loads(new)
check("1 every other key is unchanged, disableRemoteControl untouched (false), mode kept 0640", {k: v for k, v in d.items() if k != "remoteControlAtStartup"} == json.loads(ORIG)
      and d["disableRemoteControl"] is False and stat.S_IMODE(os.stat(S).st_mode) == 0o640, d)
# idempotent no-op: bytes, mtime, inode, xattrs unchanged
HAVE_XA = ISO.set_xattr(S)
st0 = os.stat(S); x0 = xattrs(S); b0 = S.read_bytes()
import time; time.sleep(0.02)
res2 = SS.set_remote_control(True)
st1 = os.stat(S)
check("1 no-op when already true: changed False, bytes / mtime_ns / inode / xattrs identical, no new backup", not res2["changed"] and res2["backup"] is None and S.read_bytes() == b0
      and st1.st_mtime_ns == st0.st_mtime_ns and st1.st_ino == st0.st_ino and xattrs(S) == x0 and (not HAVE_XA or "com.shipmiracle.test" in x0), (res2, x0))
# dry run writes nothing
put(ORIG)
b0 = S.read_bytes(); m0 = os.stat(S).st_mtime_ns
r = SS.set_remote_control(True, dry_run=True)
check("1 dry run reports the change and writes nothing", r["changed"] and S.read_bytes() == b0 and os.stat(S).st_mtime_ns == m0)
# tab-indented file
put('{\n\t"model": "x"\n}\n')
SS.set_remote_control(True)
check("1 a tab-indented file keeps its tab style", S.read_text() == '{\n\t"model": "x",\n\t"remoteControlAtStartup": true\n}\n', S.read_text())
# no trailing newline, CRLF-free single member
put('{"model": "x"}')
SS.set_remote_control(True)
check("1 a one-line file falls back to the style-keeping rewrite and stays valid", json.loads(S.read_text()) == {"model": "x", "remoteControlAtStartup": True}, S.read_text())
# false -> true edit; remove
put('{\n  "remoteControlAtStartup": false,\n  "model": "m"\n}\n')
check("1 state off when false", SS.remote_control_state() == "off")
SS.set_remote_control(True)
check("1 false -> true keeps the key order and other keys", S.read_text() == '{\n  "remoteControlAtStartup": true,\n  "model": "m"\n}\n', S.read_text())
SS.set_remote_control(None)
check("1 removal deletes only the key", json.loads(S.read_text()) == {"model": "m"} and "remoteControlAtStartup" not in S.read_text())
# absent file
S.unlink()
check("1 state off when the file is absent", SS.remote_control_state() == "off")
r = SS.set_remote_control(True)
check("1 absent file: created 0600 with just the key, no backup", json.loads(S.read_text()) == {"remoteControlAtStartup": True} and stat.S_IMODE(os.stat(S).st_mode) == 0o600 and r["backup"] is None)
S.unlink()
check("1 removing a key from an absent file is a no-op (no file created)", not SS.set_remote_control(None)["changed"] and not S.exists())

# ---------------------------------------------------------------- 2. refusals
put('{ not json')
b0 = S.read_bytes()
check("2 invalid JSON: SchemaError, file unchanged, state unknown", raises(lambda: SS.set_remote_control(True), SchemaError) is True and S.read_bytes() == b0 and SS.remote_control_state() == "unknown")
put('[1,2]')
check("2 a JSON array: SchemaError", raises(lambda: SS.set_remote_control(True), SchemaError) is True)
put('{"remoteControlAtStartup": "yes"}')
b0 = S.read_bytes()
check("2 a non-boolean value is left alone (SchemaError)", raises(lambda: SS.set_remote_control(True), SchemaError) is True and S.read_bytes() == b0 and SS.remote_control_state() == "off")
check("2 only true, false or None are accepted", raises(lambda: SS.set_remote_control("true"), SchemaError) is True and raises(lambda: SS.set_remote_control(1), SchemaError) is True)
S.unlink(); other = TMP / "other.json"; other.write_text("{}")
os.symlink(str(other), str(S))
check("2 a symlinked settings file is refused, target untouched, state unknown", raises(lambda: SS.set_remote_control(True), SafetyError) is True and other.read_text() == "{}" and SS.remote_control_state() == "unknown")
S.unlink()
os.environ["CLAUDECODE"] = "1"
os.environ["SHIPMIRACLE_ENFORCE_OWNER"] = "1"
put(ORIG); b0 = S.read_bytes()
check("2 inside a Claude chat the writer refuses (owner only), a dry run does not", raises(lambda: SS.set_remote_control(True), SafetyError) is True and S.read_bytes() == b0 and SS.set_remote_control(True, dry_run=True)["changed"])
del os.environ["CLAUDECODE"]; del os.environ["SHIPMIRACLE_ENFORCE_OWNER"]
# decoy real home: SHIPMIRACLE_REAL_HOME is the decoy; a sandboxed run may not write it
DECOY = TMP / "decoy"; (DECOY / ".claude").mkdir(parents=True); DS = DECOY / ".claude" / "settings.json"; DS.write_text('{"model": "keep"}\n')
os.environ["SHIPMIRACLE_REAL_HOME"] = str(DECOY)
db = DS.read_bytes(); dm = os.stat(DS).st_mtime_ns
check("2 a target inside the (decoy) real home is refused under SHIPMIRACLE_TEST=1; bytes and mtime unchanged", raises(lambda: SS.set_remote_control(True, path=DS), SafetyError) is True
      and raises(lambda: SS.undo_remote_control(None, path=DS), SafetyError) is True and DS.read_bytes() == db and os.stat(DS).st_mtime_ns == dm)
del os.environ["SHIPMIRACLE_REAL_HOME"]
rc, out, err = shipm("init", "--step", "remote-control", "--yes", extra={"SHIPMIRACLE_HOME": str(DECOY), "HOME": str(DECOY), "SHIPMIRACLE_REAL_HOME": str(DECOY)})
check("2 init --step remote-control against the real home under SHIPMIRACLE_TEST=1: refused, decoy unchanged", rc != 0 and DS.read_bytes() == db and os.stat(DS).st_mtime_ns == dm, (rc, out[-300:], err))

# ---------------------------------------------------------------- 3. the row: probe states
put(ORIG)
r = rows()["remote-control"]
check("3 row 14: id remote-control, optional, state skipped when off (never red)", r["n"] == 14 and r["need"] == "optional" and r["state"] == "skipped" and "off" in r["detail"], r)
check("3 the row describes the plain-text facts in fix/undo (user-level, backup, undo command)", "remoteControlAtStartup" in r["fix"] and "--undo remote-control" in r["undo"] and r["writes"] == ["~/.claude/settings.json"], r)
put('{ broken')
check("3 unreadable settings: still skipped, never red", rows()["remote-control"]["state"] == "skipped")
put('{"remoteControlAtStartup": true}\n')
check("3 green when true", rows()["remote-control"]["state"] == "green")
put(ORIG)

# ---------------------------------------------------------------- 4. apply: explanation, typed yes, manifest, undo
b_orig = S.read_bytes()
rc, out, err = shipm("init", "--step", "remote-control")           # no terminal, no --yes: not confirmed
check("4 --step not confirmed (no typed yes) is not done: exit 1", rc == 1, (rc, out[-200:]))
check("4 without a terminal and without --yes nothing changes (needs the typed yes)", S.read_bytes() == b_orig and "not confirmed" in out and "Pro, Max, Team or Enterprise" in out, (rc, out[-600:]))
check("4 the explanation names the phone app, the plan, user-level only and the ignore-in-project rule", all(x in out for x in ("phone app", "Pro, Max, Team or Enterprise", "user-level", "ignores true in project or local settings")), out[:900])
rc, out, err = shipm("init", "--yes")                                # a plain init --yes must never turn it on
check("4 `shipm init --yes` alone never enables the optional row (it registers hooks, not the key)", "remoteControlAtStartup" not in S.read_text() and rows()["remote-control"]["state"] == "skipped", (rc, out[-300:]))
b_orig = S.read_bytes()
rc, out, err = shipm("init", "--step", "remote-control", "--yes")
after = S.read_bytes()
check("4 --step remote-control --yes exits 0 although other rows are red (only the requested row counts)", rc == 0 and "NOT READY" in out, (rc, out[-400:]))
check("4 --step remote-control --yes sets only the key", json.loads(after) == dict(json.loads(b_orig), remoteControlAtStartup=True) and rows()["remote-control"]["state"] == "green", (rc, out[-300:], err))
man = json.loads((STATE / "v1" / "install-manifest.json").read_text())
st = [s for s in man["steps"] if s["action"] == "settings_key"]
check("4 manifest: one settings_key step for row 14 with before=null (absent), backup, file sha before/after", len(st) == 1 and st[0]["row"] == 14 and st[0]["before"] is None and st[0]["backup"]
      and st[0]["file_before_sha256"] == hashlib.sha256(b_orig).hexdigest() and st[0]["file_after_sha256"] == hashlib.sha256(after).hexdigest() and not st[0]["pending"], st)
check("4 the backup in the manifest is a 0600 copy of the old file", pathlib.Path(st[0]["backup"]).read_bytes() == b_orig and stat.S_IMODE(os.stat(st[0]["backup"]).st_mode) == 0o600)
rc, out, err = shipm("init", "--step", "remote-control", "--yes")
check("4 --step on an already-ok row exits 0", rc == 0, (rc, out[-200:]))
check("4 idempotent: a second run says already on, no new step, bytes identical", "ok" in out and S.read_bytes() == after and len([s for s in json.loads((STATE / "v1" / "install-manifest.json").read_text())["steps"] if s["action"] == "settings_key"]) == 1, out[-300:])
rc, out, err = shipm("init", "--undo", "remote-control")
check("4 --undo restores the old bytes exactly (absent key)", rc == 0 and S.read_bytes() == b_orig and "REVERSED" in out, (rc, out, err))
check("4 the manifest step is gone and a second undo says nothing recorded", not [s for s in json.loads((STATE / "v1" / "install-manifest.json").read_text())["steps"] if s["action"] == "settings_key"]
      and "nothing recorded" in shipm("init", "--undo", "remote-control")[1])
check("4 disableRemoteControl never touched through the whole cycle", json.loads(S.read_bytes())["disableRemoteControl"] is False)
# previous value false is restored as false
put('{\n  "remoteControlAtStartup": false,\n  "model": "m"\n}\n'); b1 = S.read_bytes()
shipm("init", "--step", "remote-control", "--yes")
check("4 from false: turned on", SS.remote_control_state() == "on")
shipm("init", "--undo", "remote-control")
check("4 undo from false restores false (bytes identical)", S.read_bytes() == b1, S.read_text())
# the owner edited the file after the opt-in: undo edits only the key
put(ORIG); shipm("init", "--step", "remote-control", "--yes")
S.write_text(S.read_text().replace('"model": "opusplan"', '"model": "sonnet"'))
rc, out, err = shipm("init", "--undo", "remote-control")
d = json.loads(S.read_text())
check("4 file edited after the opt-in: undo removes only the key and keeps the owner's edit", rc == 0 and "remoteControlAtStartup" not in d and d["model"] == "sonnet", (rc, out, S.read_text()))
# --skip is allowed for the optional row
rc, out, err = shipm("init", "--skip", "remote-control")
check("4 --skip remote-control is accepted (optional) and the row stays skipped", rc == 0 and rows()["remote-control"]["state"] == "skipped", (rc, out, err))
# undo on a row Shipmiracle never changed (owner turned it on by hand): nothing touched
put('{"remoteControlAtStartup": true}\n'); b2 = S.read_bytes()
rc, out, err = shipm("init", "--undo", "remote-control")
check("4 a key the owner set by hand is not ours: undo touches nothing", S.read_bytes() == b2 and "nothing recorded" in out, (rc, out))

# ---------------------------------------------------------------- 5. uninstall reverses it
put(ORIG); b3 = S.read_bytes()
shipm("init", "--step", "remote-control", "--yes")
rc, out, err = shipm("uninstall")
check("5 uninstall dry run lists the step and changes nothing", "settings_key" in out and "would reverse" in out and SS.remote_control_state() == "on", out)
rc, out, err = shipm("uninstall", "--apply")
check("5 uninstall --apply restores the settings file byte for byte", S.read_bytes() == b3 and "REVERSED" in out, (rc, out, err))

# ---------------------------------------------------------------- 6. panel: read-only `remote`
put('{"remoteControlAtStartup": true, "secretish": "do-not-echo"}\n'); b4 = S.read_bytes(); m4 = os.stat(S).st_mtime_ns
proj = pathlib.Path(ENV["SHIPMIRACLE_DEV"]) / "demo"; proj.mkdir(); subprocess.run(["git", "init", "-q", "-b", "main", str(proj)], check=True, env=dict(ENV))
rc, out, err = shipm("report", "panel", "--project", str(proj))
pj = json.loads(out)
check("6 panel data: remote.state on, no other key echoed, no ask field on a normal project, file untouched", rc == 0 and pj["remote"] == {"state": "on"} and "ask" not in pj and "do-not-echo" not in out
      and S.read_bytes() == b4 and os.stat(S).st_mtime_ns == m4, (rc, out[:300], err))
put('{"model": "x"}\n')
check("6 panel remote off / unknown", json.loads(shipm("report", "panel", "--project", str(proj))[1])["remote"] == {"state": "off"}, "")
put('{ nope')
check("6 panel remote unknown for broken settings", json.loads(shipm("report", "panel", "--project", str(proj))[1])["remote"] == {"state": "unknown"}, "")
S.unlink()
check("6 panel remote off when the file is absent", json.loads(shipm("report", "panel", "--project", str(proj))[1])["remote"] == {"state": "off"})
# the ask project gets the ask field, the others do not
rc, out, err = shipm("init", "--step", "ask-inbox", "--yes")
rc, out, err = shipm("report", "panel", "--project", str(pathlib.Path(ENV["SHIPMIRACLE_DEV"]) / "ask"))
a = json.loads(out).get("ask")
check("6 panel data for the registered ask project: ask = {inbox, questions_today, limit, notes, last, model_supported, model}", a == {"inbox": True, "questions_today": 0, "limit": 20, "notes": 0, "last": None, "model_supported": True, "model": "opus"}, (a, err))
(pathlib.Path(ENV["SHIPMIRACLE_DEV"]) / "ask" / "docs" / "notes" / "2026-10-21-hello-world.md").write_text("# Ask · 2026-10-21 · Hello world?\n\nQuestion: Hello world?\n")
a = json.loads(shipm("report", "panel", "--project", str(pathlib.Path(ENV["SHIPMIRACLE_DEV"]) / "ask"))[1])["ask"]
check("6 ask.last carries title, relative path and ts; notes counts the files", a["notes"] == 1 and a["last"]["title"] == "Hello world?" and a["last"]["path"] == "docs/notes/2026-10-21-hello-world.md" and isinstance(a["last"]["ts"], int), a)
check("6 other projects still have no ask field", "ask" not in json.loads(shipm("report", "panel", "--project", str(proj))[1]))

check("7 the real ~/.claude/settings.json is unchanged", real_sha() == REAL_BEFORE)
ISO.cleanup(str(TMP))
print("\n%s" % ("ALL PASSED" if fails == 0 else "%d FAILED" % fails))
sys.exit(1 if fails else 0)
