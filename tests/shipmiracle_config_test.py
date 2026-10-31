#!/usr/bin/env python3
"""shipmiracle/config.py: schema validation, atomic write + lock, 0600/0700, no value in events, mtime cache, read-only sections, masking.
Run: python3 tests/shipmiracle_config_test.py"""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import shipmiracle_isolation; shipmiracle_isolation.apply_to_environ()   # test isolation: fresh HOME/SHIPMIRACLE_HOME/CONFIG/STATE unless already temp
import json, os, pathlib, pwd, stat, subprocess, sys, tempfile, time
os.environ.pop("CLAUDECODE", None)       # the owner check only runs in a fully temp sandbox or outside a chat (H1)

ROOT = pathlib.Path(__file__).resolve().parent.parent
TMP = pathlib.Path(tempfile.mkdtemp()).resolve()
os.environ.update(SHIPMIRACLE_TEST="1", SHIPMIRACLE_HOME=str(TMP / "home"), SHIPMIRACLE_STATE=str(TMP / "state"), SHIPMIRACLE_CONFIG=str(TMP / "config"),
                  SHIPMIRACLE_DEV=str(TMP / "dev"), SHIPMIRACLE_WS=str(TMP / "ws"))
sys.path.insert(0, str(ROOT))
from shipmiracle import SafetyError, SchemaError, UsageError, config, events, paths, state  # noqa: E402

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

CFG = TMP / "config" / "config.json"
if len(sys.argv) > 1 and sys.argv[1] == "worker":
    for i in range(20):
        config.set("logs.retention_days", str(1 + (int(sys.argv[2]) * 20 + i) % 300))
    sys.exit(0)

# defaults
me = pwd.getpwuid(os.getuid()).pw_name
check("defaults without a file", config.get("switches.state.v1") is True and config.get("logs.retention_days") == 30
      and config.get("release.author_name") is None and config.get("autopilot.mcp_allow") == [] and config.get("owner.user") == me, config.get("owner.user"))
check("get returns the caller default when given", config.get("release.author_name", "fallback") == "fallback" and config.get("nope.key", 5) == 5)
check("unknown key without a default raises UsageError", raises(UsageError, config.get, "nope.key") is True)
check("switch() default on", config.switch("state.v1") is True)
check("load() with no file is empty", config.load() == {})

# set + validation
config.set("switches.state.v1", "off")
check("set bool off", config.get("switches.state.v1") is False and config.switch("state.v1") is False)
config.set("switches.state.v1", "true")
check("set bool true", config.get("switches.state.v1") is True)
config.set("owner.user", "abdullah_1"); config.set("release.author_name", "My Phone"); config.set("logs.retention_days", "14")
config.set("autopilot.mcp_allow", "Home A, Home B")
check("set stores typed values", config.load() == {"switches.state.v1": True, "owner.user": "abdullah_1", "release.author_name": "My Phone",
      "logs.retention_days": 14, "autopilot.mcp_allow": ["Home A", "Home B"]}, config.load())
config.set("autopilot.mcp_allow", '["a,b", "c"]')
check("a list key accepts a JSON list (names with commas)", config.get("autopilot.mcp_allow") == ["a,b", "c"])
bad = [("switches.state.v1", "maybe"), ("switches.state.v1", ""), ("owner.user", "Root"), ("owner.user", "a b"), ("owner.user", "1abc"),
       ("owner.user", "x" * 33), ("owner.user", "a\n"), ("release.author_name", "x" * 65), ("release.author_name", ""), ("release.author_name", "a\nb"),
       ("autopilot.mcp_allow", ",".join("n%d" % i for i in range(11))), ("autopilot.mcp_allow", '["' + "x" * 65 + '"]'), ("autopilot.mcp_allow", "[1]"),
       ("autopilot.mcp_allow", "[oops"), ("logs.retention_days", "0"), ("logs.retention_days", "366"), ("logs.retention_days", "abc"),
       ("logs.retention_days", "-3"), ("logs.retention_days", "1.5"), ("logs.retention_days", ""),
       ("ask.daily_limit", "0"), ("ask.daily_limit", "201"), ("ask.daily_limit", "abc"), ("ask.daily_limit", "2.5"), ("ask.daily_limit", "-1"), ("ask.daily_limit", "")]
for k, v in bad:
    check("refused: %s = %r" % (k, v[:20]), raises(UsageError, config.set, k, v) is True)
for k, v in (("release.author_name", "a\u202eb"), ("release.author_name", "a\u200bb"), ("release.author_name", "a\u2066b"), ("release.author_name", "a\x1bb"), ("release.author_name", "a\x7fb"),
             ("release.author_name", "a\u2028b"), ("release.author_name", "a\ud800b"), ("release.author_name", "a\tb"), ("autopilot.mcp_allow", '["ok","a\\u202eb"]')):
    check("control/bidi/format character refused: %s %s" % (k, ascii(v)[:14]), raises(UsageError, config.set, k, v) is True)
check("ordinary text with spaces and non-ASCII letters is accepted", (config.set("release.author_name", "Caf\u00e9 Net 5G"), config.get("release.author_name"))[1] == "Caf\u00e9 Net 5G")
check("refused values left the file unchanged", config.get("logs.retention_days") == 14 and config.get("owner.user") == "abdullah_1")
check("ask.daily_limit: default 20, set 5 stored as int, bound 1 and 200 accepted",
      config.get("ask.daily_limit") == 20 and (config.set("ask.daily_limit", "5"), config.get("ask.daily_limit"))[1] == 5
      and (config.set("ask.daily_limit", "1"), config.set("ask.daily_limit", "200"), config.get("ask.daily_limit"))[2] == 200)
config.unset("ask.daily_limit")
(config.path().parent).mkdir(parents=True, exist_ok=True)
_old = config.path().read_text() if config.path().exists() else None
_d = json.loads(_old) if _old else {}; _d["ask.daily_limit"] = 7; config.path().write_text(json.dumps(_d))
check("config.json holding ask.daily_limit loads", config.load()["ask.daily_limit"] == 7 and config.get("ask.daily_limit") == 7)
_d["ask.daily_limit"] = 999; config.path().write_text(json.dumps(_d))
check("config.json with an out-of-range ask.daily_limit is a SchemaError", raises(config.SchemaError, config.load) is True)
config.path().write_text(_old if _old is not None else "{}")
check("unknown key refused", raises(UsageError, config.set, "color.theme", "red") is True)
for sec in ("watch.frozen_min", "ideas.idle_hours", "notifications.mac"):
    check("%s is read-only (set and unset refused)" % sec, raises(UsageError, config.set, sec, "1") is True and raises(UsageError, config.unset, sec) is True)

# unset
config.unset("logs.retention_days")
check("unset restores the default; unset of an absent key is fine", config.get("logs.retention_days") == 30 and config.unset("logs.retention_days") is None)

# perms, atomic, symlink
check("config.json 0600 and folder 0700", stat.S_IMODE(os.stat(CFG).st_mode) == 0o600 and stat.S_IMODE(os.stat(CFG.parent).st_mode) == 0o700)
check("valid JSON on disk, no temp left", isinstance(json.loads(CFG.read_text()), dict) and [p.name for p in CFG.parent.iterdir() if p.name.endswith(".tmp")] == [])
os.chmod(CFG.parent, 0o755)
config.set("logs.retention_days", "20")
check("a 0755 config folder is fixed to 0700 on set", stat.S_IMODE(os.stat(CFG.parent).st_mode) == 0o700)

# events never carry the value
ssid_value = "Secret-Name-42"
config.set("release.author_name", ssid_value)
alltxt = "\n".join(p.read_text() for p in (TMP / "state" / "v1").glob("events.jsonl*"))
evs = events.tail(100)
check("config.set emits an event with the key only", any(e["kind"] == "config.set" and e["data"] == {"key": "release.author_name"} for e in evs), evs[-2:])
check("the value never reaches the event log", ssid_value not in alltxt and "Home A" not in alltxt)
check("config.unset emits an event", (config.unset("release.author_name"), any(e["kind"] == "config.unset" for e in events.tail(100)))[1])
check("validation failure logs nothing with the value", (lambda n: (raises(UsageError, config.set, "owner.user", "BAD VALUE Z"), "BAD VALUE Z" not in "\n".join(p.read_text() for p in (TMP / "state" / "v1").glob("events.jsonl*")))[1])(0))

# corrupt / invalid stored data
CFG.write_text("{nope")
check("corrupt config: load/get raise SchemaError", raises(SchemaError, config.load) is True and raises(SchemaError, config.get, "owner.user") is True)
CFG.write_text("[1]")
check("non-object config: SchemaError", raises(SchemaError, config.load) is True)
CFG.write_text(json.dumps({"logs.retention_days": 9999}))
try:
    config.load(); msg = None
except SchemaError as e:
    msg = str(e)
check("invalid stored value: SchemaError names the key, not the value", msg is not None and "logs.retention_days" in msg and "9999" not in msg, msg)
CFG.write_text(json.dumps({"future.key": 1, "owner.user": "me"}))
check("unknown stored keys are kept out of the way (ignored by get, preserved by set)", config.get("owner.user") == "me" and (config.set("logs.retention_days", "5"), json.loads(CFG.read_text())["future.key"])[1] == 1)
CFG.unlink()
os.symlink(TMP / "elsewhere.json", CFG)
check("symlinked config.json refused for set", raises(SafetyError, config.set, "logs.retention_days", "5") is True and not (TMP / "elsewhere.json").exists())
os.unlink(CFG)

# mtime cache
config.set("logs.retention_days", "7")
calls = []
orig = state.read_bytes_nofollow
def counting(p):
    calls.append(str(p)); return orig(p)
state.read_bytes_nofollow = counting
try:
    config.load(); config.get("logs.retention_days"); config.get("owner.user"); config.switch("state.v1")
    n_cached = len(calls)
    cfg_before = config.get("logs.retention_days")
    # an external edit with different size/mtime must be noticed
    time.sleep(0.01)
    CFG.write_text(json.dumps({"logs.retention_days": 11}) + "\n")
    after = config.get("logs.retention_days")
finally:
    state.read_bytes_nofollow = orig
check("repeat reads of an unchanged file come from the cache (at most 1 read)", n_cached <= 1, calls)
check("an external change is noticed", cfg_before == 7 and after == 11, (cfg_before, after))
v = config.load(); v["logs.retention_days"] = 99
check("load() returns a copy", config.load()["logs.retention_days"] == 11)

# read-only sections come from <ws>/config/*.json
ws = TMP / "ws" / "config"; ws.mkdir(parents=True)
(ws / "watch.json").write_text('{"frozen_min": 20, "auto": true}')
check("watch.* reads the workspace file", config.get("watch.frozen_min") == 20 and config.get("watch.auto") is True and config.get("watch.nope", 3) == 3 and config.get("watch.nope") is None)
(ws / "watch.json").write_text("{bad")
check("a broken workspace section file raises SchemaError", raises(SchemaError, config.get, "watch.frozen_min") is True)
check("a missing section file reads as empty", config.get("ideas.idle_hours", 48) == 48)

# masking and list (no key is masked today; the mechanism still works for a prefix list)
CFG.write_text(json.dumps({"release.author_name": "Phone", "autopilot.mcp_allow": ["A"], "owner.user": "me"}))
li = config.list_items()
check("list masks nothing today", li["release.author_name"] == "Phone" and li["autopilot.mcp_allow"] == ["A"] and li["owner.user"] == "me" and li["logs.retention_days"] == 30, li)
config.MASKED_PREFIXES = ("release.", "autopilot.")
li = config.list_items()
check("list masks a configured prefix but not others", li["release.author_name"] == "***" and li["autopilot.mcp_allow"] == "***" and li["owner.user"] == "me", li)
check("unmasked list for the owner's own use", config.list_items(mask=False)["release.author_name"] == "Phone")
check("unset values are not masked", (CFG.write_text("{}"), config.list_items()["release.author_name"] is None)[1])
config.MASKED_PREFIXES = ()

# a config.json that still holds the removed wifi.* keys (owner decision 21 Oct) loads without error and is ignored
CFG.write_text(json.dumps({"wifi.hotspot": "Old", "wifi.home_networks": ["A"], "owner.user": "me"}))
check("removed keys in config.json are ignored silently (no error)", config.get("owner.user") == "me" and config.get("logs.retention_days") == 30
      and "wifi.hotspot" not in config.list_items() and raises(UsageError, config.get, "wifi.hotspot") is True)
config.set("logs.retention_days", "12")
check("a write keeps working next to removed keys", config.get("logs.retention_days") == 12)
CFG.write_text("{}")

# isolation
real_cfg = paths.real_home() / ".config" / "shipmiracle"
os.environ["SHIPMIRACLE_CONFIG"] = str(real_cfg)
opened = []
o_open, o_mk = os.open, os.mkdir
def trap(*a, **k):
    opened.append(a[:1]); raise AssertionError("touched the filesystem")
os.open, os.mkdir = trap, trap
try:
    r = raises(SafetyError, config.set, "logs.retention_days", "9")
finally:
    os.open, os.mkdir = o_open, o_mk
    os.environ["SHIPMIRACLE_CONFIG"] = str(TMP / "config")
check("set against the REAL config folder under SHIPMIRACLE_TEST=1 raises SafetyError before any I/O", r is True and not opened, (r, opened))

# concurrency: 6 processes x 20 sets
CFG.unlink()
procs = [subprocess.Popen([sys.executable, __file__, "worker", str(k)], stderr=subprocess.PIPE) for k in range(6)]
codes = [p.wait() for p in procs]
check("6 processes x 20 sets: no error, valid JSON, no temp left", codes == [0] * 6 and 1 <= config.get("logs.retention_days") <= 365
      and not [p for p in CFG.parent.iterdir() if p.name.endswith(".tmp")], codes)
# ---- P8 T1: engine.dir, paths.projects_dir, git.autopush, owner.github ----
CFG.write_text("{}")
check("P8 defaults: autopush off, others unset", config.get("git.autopush") is False and config.get("engine.dir") is None and config.get("paths.projects_dir") is None and config.get("owner.github") is None)
config.set("git.autopush", "on"); config.set("engine.dir", "/opt/shipmiracle"); config.set("paths.projects_dir", "~/Code"); config.set("owner.github", "octo-user")
check("P8 keys stored", config.get("git.autopush") is True and config.get("engine.dir") == "/opt/shipmiracle" and config.get("paths.projects_dir") == "~/Code" and config.get("owner.github") == "octo-user")
check("P8 paths.projects_dir feeds paths.dev_dir (tilde against home) when SHIPMIRACLE_DEV is unset", (os.environ.pop("SHIPMIRACLE_DEV"), paths.dev_dir() == paths.home() / "Code")[1])
config.set("paths.projects_dir", str(TMP / "proj")); check("P8 absolute projects_dir", paths.dev_dir() == TMP / "proj")      # a folder the user can create (QA D4: /srv/proj under a root-owned / is refused now)
CFG.write_text("{not json"); check("P8 damaged config: dev_dir falls back to ~/Developer", paths.dev_dir() == paths.home() / "Developer")
CFG.write_text("{}"); os.environ["SHIPMIRACLE_DEV"] = str(TMP / "dev")
for k, bad in (("engine.dir", "relative/x"), ("engine.dir", "/a/../b"), ("engine.dir", "/x\x00y"), ("paths.projects_dir", "Code"), ("owner.github", "-bad"), ("owner.github", "a b"),
               ("owner.github", "x" * 40), ("git.autopush", "maybe")):
    check("P8 %s rejects %r" % (k, bad[:12]), raises(UsageError, config.set, k, bad) is True)
CFG.write_text(json.dumps({"engine.dir": "rel"})); check("P8 a stored invalid value makes load() raise SchemaError", raises(SchemaError, config.load) is True)
CFG.write_text("{}")

# ---- review remediation A: switch keys, reporter.model, legacy hook scripts ----
CFG.write_text("{}")
check("A defaults: tokens.nudge off, agents.maxTurns on, prefix.trim on, guard.jobs off, reporter.model haiku (= the pin of agents/claude/reporter.md)",
      config.get("tokens.nudge") is False and config.get("agents.maxTurns") is True and config.get("prefix.trim") is True and config.get("guard.jobs") is False
      and config.get("reporter.model") == "haiku" and "model: haiku" in (ROOT / "agents" / "claude" / "reporter.md").read_text())
config.set("reporter.model", "Sonnet"); config.set("agents.maxTurns", "off"); config.set("prefix.trim", "off")
check("A set: reporter.model normalised, bools stored", config.get("reporter.model") == "sonnet" and config.get("agents.maxTurns") is False and config.get("prefix.trim") is False)
config.set("reporter.model", "off"); check("A reporter.model off is allowed", config.get("reporter.model") == "off")
for bad in ("gpt", "", "haiku,opus", "inherit"):
    check("A reporter.model rejects %r" % bad, raises(UsageError, config.set, "reporter.model", bad) is True)
check("A the new keys are in config list", all(k in config.list_items() for k in ("agents.maxTurns", "prefix.trim", "reporter.model")))
CFG.write_text("{}")
# the legacy-hook-scripts check (skipped in temp test workspaces unless SHIPMIRACLE_ENFORCE_LEGACY_HOOKS=1)
WSX = TMP / "ws"; (WSX / "hooks").mkdir(parents=True, exist_ok=True)
check("A scripts check is skipped under SHIPMIRACLE_TEST without the flag", config.set("hooks.dispatcher", "legacy") is None and config.get("hooks.dispatcher") == "legacy")
os.environ["SHIPMIRACLE_ENFORCE_LEGACY_HOOKS"] = "1"
miss = config.legacy_hook_scripts_missing()
check("A empty hooks folder: all legacy scripts missing (17 registrations use 8 distinct scripts + plan-capture)", "keep-awake.sh" in miss and "plan-capture.sh" in miss and len(miss) == 9, miss)
for v in ("legacy", "shadow"):
    r = raises(UsageError, config.set, "hooks.dispatcher", v)
    check("A hooks.dispatcher %s refused without the scripts" % v, r is True)
config.set("hooks.dispatcher", "v1"); check("A v1 needs no scripts", config.get("hooks.dispatcher") == "v1")
try:
    config.set("hooks.dispatcher", "legacy")
except UsageError as e:
    check("A the refusal names the remedy and does not print paths", "dispatcher" in str(e) and "v1" in str(e) and str(TMP) not in str(e), str(e))
check("A the refused value was not stored", config.get("hooks.dispatcher") == "v1")
for n in miss:
    (WSX / "hooks" / n).write_text("#!/bin/sh\n")
config.set("hooks.dispatcher", "shadow"); check("A with every script present shadow is accepted", config.get("hooks.dispatcher") == "shadow")
(WSX / "hooks" / "flow-gate.sh").unlink()
check("A one script missing is enough to refuse legacy", raises(UsageError, config.set, "hooks.dispatcher", "legacy") is True)
os.environ.pop("SHIPMIRACLE_ENFORCE_LEGACY_HOOKS"); CFG.write_text("{}")

print("\nFAILED: %d" % fails if fails else "\nALL PASS"); sys.exit(1 if fails else 0)
