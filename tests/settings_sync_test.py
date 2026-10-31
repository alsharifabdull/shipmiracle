#!/usr/bin/env python3
"""shipmiracle/settings_sync.py + shipmiracle/hooks/spec.py + `shipm sync` / `shipm hooks` / `shipm switch hooks.*` (the installer hook step and the owner script are in tests/private/settings_sync_owner_test.py).
Everything runs in a temp HOME with a sanitized copy of the real settings shape (tests/fixtures/settings/real-shape.json); the real
~/.claude/settings.json is never read or written. Run: python3 tests/settings_sync_test.py"""
import copy, json, os, pathlib, re, shutil, stat, subprocess, sys, tempfile, time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
import shipmiracle_isolation  # noqa: E402  (xattr helpers)
TMP = pathlib.Path(tempfile.mkdtemp(prefix="shipmiracle-sset-")).resolve()
HOME = TMP / "home"
WSD = HOME / "Developer" / "AI-Workspace"           # the fake main checkout: $HOME-relative prefix
STATE, CONF = TMP / "state", TMP / "cfg"
for d in (HOME / ".claude", WSD / "bin", WSD / "hooks", WSD / "shipmiracle"):
    d.mkdir(parents=True)
shutil.copy(ROOT / "bin" / "gate-deny", WSD / "bin" / "gate-deny")
for f in (ROOT / "shipmiracle").glob("*.py"):
    shutil.copy(f, WSD / "shipmiracle" / f.name)          # the old sync-tools block imports shipmiracle.paths from the workspace it is given
ENV = dict(os.environ, SHIPMIRACLE_TEST="1", SHIPMIRACLE_HOME=str(HOME), SHIPMIRACLE_STATE=str(STATE), SHIPMIRACLE_CONFIG=str(CONF), SHIPMIRACLE_WS=str(WSD), HOME=str(HOME))
ENV.pop("SHIPMIRACLE_DEBUG", None); ENV.pop("CLAUDECODE", None); ENV.pop("SHIPMIRACLE_ENFORCE_OWNER", None)
os.environ.update({k: v for k, v in ENV.items() if k.startswith("SHIPMIRACLE_") or k == "HOME"})
os.environ.pop("CLAUDECODE", None); os.environ.pop("SHIPMIRACLE_ENFORCE_OWNER", None)
sys.path.insert(0, str(ROOT))
from shipmiracle import SafetyError, SchemaError, UsageError, config, paths  # noqa: E402
from shipmiracle import settings_sync as ss  # noqa: E402
from shipmiracle.hooks import spec  # noqa: E402

fails = 0
def check(name, ok, info=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(info)[:600]))
    fails += 0 if ok else 1

FIX = json.loads((ROOT / "tests/fixtures/settings/real-shape.json").read_text())
SET = HOME / ".claude" / "settings.json"
BACKUPS = STATE / "v1" / "backups"

def put(d, mode=0o600):
    SET.parent.mkdir(parents=True, exist_ok=True)
    if SET.is_symlink() or SET.exists():
        SET.unlink()
    SET.write_text(d if isinstance(d, str) else json.dumps(d, indent=2) + "\n"); os.chmod(SET, mode)

def cur():
    return json.loads(SET.read_text())

def dumps(x):
    return json.dumps(x, indent=2)

def shipm(*args, env=None):
    r = subprocess.run([sys.executable, str(ROOT / "bin" / "shipm")] + list(args), env=env or ENV, capture_output=True, text=True, timeout=60)
    return r.returncode, r.stdout, r.stderr

def bks():
    return sorted(BACKUPS.glob("settings-*.json")) if BACKUPS.is_dir() else []

# ---- legacy block (the comparison with the OLD inline code lives in tests/private/settings_sync_owner_test.py) ----
new_empty, _ = ss.plan({}, "legacy", ws=WSD)
check("legacy: 17 entries, top-level key order hooks, env, statusLine as before", sum(len(g["hooks"]) for gs in new_empty["hooks"].values() for g in gs) == 17 and list(new_empty) == ["hooks", "env", "statusLine"], list(new_empty))
new_real, diff = ss.plan(copy.deepcopy(FIX), "legacy", ws=WSD)
check("legacy on the real-shape file changes nothing (same dict, same key order, empty diff)", dumps(new_real) == dumps(FIX) and diff == "", diff[:300])
check("the real-shape fixture holds the 17 entries the spec lists", len([h for gs in FIX["hooks"].values() for g in gs for h in g["hooks"]]) == 17)
check("legacy block equals the fixture's registrations (dict equality)", new_empty["hooks"] == FIX["hooks"])
check("fixture is sanitized: no user name or absolute home path", ("al" + "sharif") not in (ROOT / "tests/fixtures/settings/real-shape.json").read_text().lower() and "/Users/" not in (ROOT / "tests/fixtures/settings/real-shape.json").read_text())

# ---- shadow / v1 entries ----
sh = spec.build("shadow", ws=WSD)
ents = spec.entries(sh)
check("shadow: one entry per event, Stop twice (--slow), Pre/PostToolUse matcher *", [e[0] for e in ents] == ["UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop", "Stop", "StopFailure", "SubagentStart", "SubagentStop", "SessionStart", "Notification", "PreModelSwitch"]
      and [e[1] for e in ents if e[0] in ("PreToolUse", "PostToolUse")] == ["*", "*"], ents)
check("shadow: v1 builds the same entries as shadow", spec.build("v1", ws=WSD)["hooks"] == sh["hooks"] and sh["statusLine"]["padding"] == 0)
pyc = str(STATE) + "/v1/pyc"          # the test state folder is outside HOME, so the path stays absolute
check("dispatcher command is the fail-open wrapper around the documented argv, $HOME-relative script path",
      ents[3][2] == spec.dispatcher_command("$HOME/Developer/AI-Workspace/hooks/", "Stop", (), HOME) and ents[3][2].startswith("/bin/sh -c '")
      and ("exec /usr/bin/python3 -I -S -X pycache_prefix=%s \"$@\"'" % pyc) in ents[3][2] and ents[3][2].endswith("' shipm-gate $HOME/Developer/AI-Workspace/hooks/shipm-hook Stop")
      and ents[4][2].endswith("shipm-hook Stop --slow") and sh["statusLine"]["command"].endswith("shipm-hook StatusLine"), ents[3][2])
check("env keys (incl. the browser keychain flags)", sh["env"] == {"BASH_DEFAULT_TIMEOUT_MS": "600000", "BASH_MAX_TIMEOUT_MS": "3600000", "AGENT_BROWSER_ARGS": "--use-mock-keychain,--password-store=basic"})
check("legacy command strings: no whitespace, no quotes", all(not any(c in cmd for c in " \t'\"") for _, _, cmd in spec.entries(spec.build("legacy", ws=WSD))))
check("plain (pre-wrapper) dispatcher command splits into 7 plain words", all(len(c.split()) == 7 + (1 if "--slow" in c else 0) and not any(q in c for q in "'\"") for c in [spec.plain_dispatcher_command("$HOME/x/hooks/", e[0], ("--slow",) if i == 4 else (), HOME) for i, e in enumerate(ents)]))
check("the wrapper command is one shell word group: /bin/sh -c '<body>' shipm-gate <script> <Event>", all(c.startswith("/bin/sh -c '") and c.count("'") == 2 for _, _, c in ents))
check("deny rules are bin/gate-deny's RULES list", spec.deny_rules(ws=WSD) == json.loads(subprocess.run([sys.executable, "-c", "import importlib.machinery as m,importlib.util as u,json,sys;l=m.SourceFileLoader('g',sys.argv[1]);x=u.module_from_spec(u.spec_from_loader('g',l));l.exec_module(x);print(json.dumps(x.RULES))", str(WSD / "bin/gate-deny")], capture_output=True, text=True).stdout))

# unsafe workspace path: fixed fallback + warning
bad = HOME / "Developer" / "my main"; bad.mkdir(parents=True, exist_ok=True)
b = spec.build("legacy", ws=bad)
check("workspace path with a space falls back to the fixed prefix and warns", b["hooks"]["Stop"][0]["hooks"][0]["command"] == spec.FIXED_PREFIX + "keep-going.sh" and b["warning"], b["warning"])
check("workspace path outside HOME stays absolute when shell-safe", spec.hooks_prefix(ws=TMP / "outside", home=HOME)[0] == str(TMP / "outside") + "/hooks/")

# ---- round trip, foreign keys and hooks ----
FOREIGN_A = {"matcher": "Bash", "hooks": [{"type": "command", "command": "/opt/tools/rtk-hook.sh pre"}]}
FOREIGN_B = {"hooks": [{"type": "command", "command": "/usr/local/bin/notify-me"}]}
base = copy.deepcopy(FIX); base["hooks"] = copy.deepcopy(new_empty["hooks"])      # canonical key order (hooks, matcher) as the writer produces it
base["hooks"]["PreToolUse"].insert(0, copy.deepcopy(FOREIGN_A))
base["hooks"]["UserPromptSubmit"].append(copy.deepcopy(FOREIGN_B))
base["hooks"]["SessionStart"] = [{"hooks": [{"type": "command", "command": "/opt/plugin/session.sh"}]}]
base["hooks"]["Stop"].append({"hooks": [{"type": "command", "command": "$HOME/Developer/AI-Workspace/hooks/keep-going.sh"}, {"type": "command", "command": "/opt/mixed/foreign.sh"}]})
base["extra"] = {"keep": ["me", 1, None]}
x, _ = ss.plan(base, "legacy", ws=WSD)
y, _ = ss.plan(x, "v1", ws=WSD)
z, _ = ss.plan(y, "legacy", ws=WSD)
check("round trip legacy -> v1 -> legacy: hook blocks byte-identical", dumps(z["hooks"]) == dumps(x["hooks"]) and dumps(z) == dumps(x), "")
check("v1 step holds the dispatcher and none of the old scripts", all("shipm-hook" in c or not ss.is_owned(c, WSD, HOME) for gs in y["hooks"].values() for g in gs for c in [h["command"] for h in g["hooks"]])
      and not any(c.endswith(".sh") and "AI-Workspace" in c for gs in y["hooks"].values() for g in gs for c in [h["command"] for h in g["hooks"]]))
def foreign(d):
    return [(ev, g) for ev, gs in d["hooks"].items() for g in gs if any(not ss.is_owned(h["command"], WSD, HOME) for h in g["hooks"])]
check("foreign hooks are kept, in the same order, in every mode", [g for _, g in foreign(y)] == [g for _, g in foreign(base)] or
      [json.dumps(g["hooks"]) for _, g in foreign(y)] == [json.dumps(g["hooks"]) for _, g in foreign(x)], foreign(y))
check("the mixed group keeps only its foreign hook after a mode change", {"hooks": [{"type": "command", "command": "/opt/mixed/foreign.sh"}]} in y["hooks"]["Stop"], y["hooks"]["Stop"])
check("foreign PreToolUse hook stays first, foreign UserPromptSubmit stays last, SessionStart untouched", y["hooks"]["PreToolUse"][0] == FOREIGN_A and y["hooks"]["UserPromptSubmit"][-1] == FOREIGN_B and y["hooks"]["SessionStart"][0] == base["hooks"]["SessionStart"][0] and len(y["hooks"]["SessionStart"]) == 2)
others = [k for k in base if k not in ("hooks", "env", "statusLine")]
check("every other top-level key is untouched and in the same order (model, permissions, plugins, autoMode, extra...)",
      [k for k in y if k in others] == others and all(dumps(y[k]) == dumps(base[k]) for k in others) and "permissions" in y and y["permissions"] == base["permissions"], list(y))
snap = dumps(base); ss.plan(base, "shadow", ws=WSD)
check("plan does not modify its input", dumps(base) == snap)
base_env = copy.deepcopy(FIX); base_env["env"] = {"MY_VAR": "1", "BASH_MAX_TIMEOUT_MS": "1"}
e, _ = ss.plan(base_env, "legacy", ws=WSD)
check("env: our two keys set, foreign env keys kept", e["env"] == {"MY_VAR": "1", "BASH_MAX_TIMEOUT_MS": "3600000", "BASH_DEFAULT_TIMEOUT_MS": "600000", "AGENT_BROWSER_ARGS": "--use-mock-keychain,--password-store=basic"}, e["env"])

# statusLine
fs = copy.deepcopy(FIX); fs["statusLine"] = {"type": "command", "command": "/opt/mine/statusline.sh", "padding": 2}
check("foreign statusLine is kept", ss.plan(fs, "shadow", ws=WSD)[0]["statusLine"] == fs["statusLine"])
ns = copy.deepcopy(FIX); ns.pop("statusLine")
check("absent statusLine is added", ss.plan(ns, "shadow", ws=WSD)[0]["statusLine"]["command"].endswith("shipm-hook StatusLine"))
check("our statusLine is replaced and back", ss.plan(ss.plan(FIX, "v1", ws=WSD)[0], "legacy", ws=WSD)[0]["statusLine"] == FIX["statusLine"])

# worktree: the main checkout's hooks are ours too
MAINW = HOME / "Developer" / "AI-Workspace"; WT = HOME / "Developer" / ".worktrees" / "AI-Workspace" / "wt"
WT.mkdir(parents=True); (MAINW / ".git" / "worktrees" / "wt").mkdir(parents=True)
(WT / ".git").write_text("gitdir: %s/.git/worktrees/wt\n" % MAINW)
wp, _ = ss.plan(FIX, "v1", ws=WT)
check("run from a worktree: prefix comes from the main checkout and the main checkout's entries are replaced",
      all("$HOME/Developer/AI-Workspace/hooks/shipm-hook" in h["command"] for gs in wp["hooks"].values() for g in gs for h in g["hooks"]), json.dumps(wp["hooks"])[:300])
check("is_owned: known script, dispatcher, tilde and absolute spellings; foreign and non-strings are not", ss.is_owned("$HOME/Developer/AI-Workspace/hooks/keep-awake.sh", WSD, HOME) and ss.is_owned(str(WSD) + "/hooks/shipm-hook Stop", WSD, HOME)
      and ss.is_owned("~/Developer/AI-Workspace/hooks/flow-gate.sh", WSD, HOME) and not ss.is_owned("/opt/AI-Workspace/hooks/flow-gate.sh", WSD, HOME) and not ss.is_owned(None, WSD, HOME)
      and not ss.is_owned("$HOME/Developer/AI-Workspace-evil/hooks/keep-awake.sh", WSD, HOME))
DISP = spec.dispatcher_command("$HOME/Developer/AI-Workspace/hooks/", "PreToolUse", (), HOME)
check("L7 is_owned: the exact dispatcher command (with --slow too) and the five legacy spellings are owned",
      ss.is_owned(DISP, WSD, HOME) and ss.is_owned(spec.dispatcher_command("$HOME/Developer/AI-Workspace/hooks/", "Stop", ("--slow",), HOME), WSD, HOME)
      and all(ss.is_owned("$HOME/Developer/AI-Workspace/hooks/" + n, WSD, HOME) for n in ("keep-awake.sh", "limit-wait.sh", "agent-cap.sh", "plan-capture.sh", "context-nudge.sh")))
FOREIGN = ["$HOME/Developer/AI-Workspace/hooks/my-own-hook.sh",                                 # an unknown script that lives in the folder
           "/usr/local/bin/audit-log --watch $HOME/Developer/AI-Workspace/hooks/keep-awake.sh", "echo $HOME/Developer/AI-Workspace/hooks/shipm-hook",
           "bash -c 'rm -rf /; $HOME/Developer/AI-Workspace/hooks/keep-awake.sh'", "/usr/bin/python3 /tmp/wrap.py $HOME/Developer/AI-Workspace/hooks/shipm-hook Stop",
           "$HOME/Developer/AI-Workspace/hooks/keep-awake.sh --extra", "/usr/bin/python3 -I -S $HOME/Developer/AI-Workspace/hooks/shipm-hook Stop; curl evil",
           "$HOME/Developer/AI-Workspace/hooks/sub/keep-awake.sh", "cat $HOME/Developer/AI-Workspace/hooks/shipm-hook"]
check("L7 is_owned: a foreign hook that only mentions a path under <WS>/hooks/ is NOT owned", not any(ss.is_owned(c, WSD, HOME) for c in FOREIGN), [c for c in FOREIGN if ss.is_owned(c, WSD, HOME)])
fx = copy.deepcopy(FIX)
fx.setdefault("hooks", {}).setdefault("PreToolUse", []).append({"matcher": "Bash", "hooks": [{"type": "command", "command": FOREIGN[1]}, {"type": "command", "command": FOREIGN[0]}]})
fx["hooks"].setdefault("Stop", []).append({"hooks": [{"type": "command", "command": FOREIGN[4]}]})
for md in ("legacy", "shadow", "v1"):
    pn, _ = ss.plan(fx, md, ws=WSD)
    kept = [h["command"] for gs in pn["hooks"].values() for g in gs for h in g["hooks"]]
    check("L7 plan(%s): the foreign hooks that mention <WS>/hooks/ survive a sync" % md, FOREIGN[0] in kept and FOREIGN[1] in kept and FOREIGN[4] in kept, kept[-6:])
for bad_set in ([], {"hooks": []}, {"hooks": {"Stop": {}}}, {"env": 3}):
    try:
        ss.plan(bad_set, "legacy", ws=WSD); ok = False
    except SchemaError:
        ok = True
    check("plan refuses a settings file of the wrong shape: %s" % json.dumps(bad_set), ok)
for m in ("", "LEGACY2", None, "v2"):
    try:
        ss.plan({}, m, ws=WSD); ok = False
    except UsageError:
        ok = True
    check("mode %r is rejected" % (m,), ok)

# ---- apply: backups, atomic write, verification ----
CANON = {ev: new_empty["hooks"][ev] for ev in FIX["hooks"]}      # the writer's group key order, the fixture's event order
put(copy.deepcopy(FIX), 0o640)
before = SET.read_bytes()
r = ss.apply(mode="shadow", ws=WSD)
check("apply shadow: changed, backup holds the exact old bytes, backup is 0600, result verified", r["changed"] and pathlib.Path(r["backup"]).read_bytes() == before
      and stat.S_IMODE(os.stat(r["backup"]).st_mode) == 0o600 and cur() == ss.plan(FIX, "shadow", ws=WSD)[0], r)
check("apply keeps the file mode (0640)", stat.S_IMODE(os.stat(SET).st_mode) == 0o640)
check("backup folder is private (0700)", stat.S_IMODE(os.stat(BACKUPS).st_mode) == 0o700 and stat.S_IMODE(os.stat(STATE / "v1").st_mode) == 0o700)
r2 = ss.apply(mode="shadow", ws=WSD)
check("second apply of the same mode: no change, no new backup", not r2["changed"] and r2["backup"] is None and len(bks()) == 1)
check("no temp files left next to settings.json", sorted(p.name for p in SET.parent.iterdir()) == ["settings.json"], list(SET.parent.iterdir()))
for i in range(13):
    ss.apply(mode=("legacy", "shadow")[i % 2], ws=WSD)
check("backups are pruned to the newest 10, all 0600", len(bks()) == 10 and all(stat.S_IMODE(os.stat(p).st_mode) == 0o600 for p in bks()), len(bks()))
ss.apply(mode="legacy", ws=WSD)
check("legacy restores today's block exactly (same content as the fixture; key order as the writer makes it)", cur() == FIX and dumps(cur()["hooks"]) == dumps(CANON))

# a file that does not exist yet
SET.unlink()
r = ss.apply(mode="legacy", ws=WSD)
check("absent settings.json: created from the spec (0600), no backup", r["changed"] and r["backup"] is None and SET.exists() and stat.S_IMODE(os.stat(SET).st_mode) == 0o600 and cur()["hooks"] == FIX["hooks"])

# malformed
put("{ not json")
n0 = len(bks()); raw = SET.read_bytes()
try:
    ss.apply(mode="shadow", ws=WSD); ok = False
except SchemaError:
    ok = True
check("malformed settings.json: abort, file untouched, no backup", ok and SET.read_bytes() == raw and len(bks()) == n0)
put("[1, 2]"); raw = SET.read_bytes()
try:
    ss.apply(mode="shadow", ws=WSD); ok = False
except SchemaError:
    ok = True
check("settings.json that is not an object: abort, untouched", ok and SET.read_bytes() == raw)

# dry run
put(copy.deepcopy(FIX)); mt, raw, n0 = os.stat(SET).st_mtime_ns, SET.read_bytes(), len(bks())
r = ss.apply(mode="v1", dry_run=True, ws=WSD)
check("dry run: diff returned, nothing written, mtime and backups unchanged", r["changed"] and r["diff"].startswith("--- ") and SET.read_bytes() == raw and os.stat(SET).st_mtime_ns == mt and len(bks()) == n0)

# owner refusal
os.environ["CLAUDECODE"] = "1"; os.environ["SHIPMIRACLE_ENFORCE_OWNER"] = "1"
try:
    ss.apply(mode="shadow", ws=WSD); ok = False
except SafetyError:
    ok = True
check("refused under CLAUDECODE with SHIPMIRACLE_ENFORCE_OWNER=1; file untouched", ok and SET.read_bytes() == raw and len(bks()) == n0)
check("a dry run is allowed inside a chat (it writes nothing)", ss.apply(mode="shadow", dry_run=True, ws=WSD)["changed"])
env2 = dict(ENV, CLAUDECODE="1", SHIPMIRACLE_ENFORCE_OWNER="1")
code, out, err = shipm("sync", "--hooks", "shadow", env=env2)
check("shipm sync under CLAUDECODE: exit 4 and one shipm: line", code == 4 and err.startswith("shipm: ") and SET.read_bytes() == raw, (code, err))
del os.environ["CLAUDECODE"]; del os.environ["SHIPMIRACLE_ENFORCE_OWNER"]

# symlink
real = TMP / "elsewhere.json"; real.write_text(json.dumps(FIX)); SET.unlink(); SET.symlink_to(real)
for dry in (False, True):
    try:
        ss.apply(mode="shadow", dry_run=dry, ws=WSD); ok = False
    except SafetyError:
        ok = True
    check("symlinked settings.json refused (dry_run=%s), target untouched" % dry, ok and json.loads(real.read_text()) == FIX and SET.is_symlink())
SET.unlink()

# concurrent change between read and replace
put(copy.deepcopy(FIX))
def tamper():
    d = cur(); d["model"] = "changed-by-someone-else"; SET.write_text(json.dumps(d, indent=2) + "\n")
ss._TEST_HOOK = tamper; n0 = len(bks())
try:
    ss.apply(mode="shadow", ws=WSD); ok = False
except SafetyError:
    ok = True
ss._TEST_HOOK = None
check("a change between read and replace is detected: nothing written over it, no backup", ok and cur()["model"] == "changed-by-someone-else" and cur()["hooks"] == FIX["hooks"] and len(bks()) == n0)
def tamper_same_size():
    raw = SET.read_bytes(); SET.write_bytes(raw.replace(b"opusplan", b"opusplaN"))
put(copy.deepcopy(FIX)); ss._TEST_HOOK = tamper_same_size
try:
    ss.apply(mode="shadow", ws=WSD); ok = False
except SafetyError:
    ok = True
ss._TEST_HOOK = None
check("a same-size change (content hash differs) is detected too", ok and cur()["model"] == "opusplaN")

# ---- config keys and CLI ----
check("hooks.dispatcher defaults to legacy, hooks.record to false", config.get("hooks.dispatcher") == "legacy" and config.get("hooks.record") is False)
for bad_v in ("bogus", "", "V2", "on"):
    try:
        config.set("hooks.dispatcher", bad_v); ok = False
    except UsageError:
        ok = True
    check("config set hooks.dispatcher %r is rejected" % bad_v, ok)
try:
    config.set("hooks.record", "maybe"); ok = False
except UsageError:
    ok = True
check("config set hooks.record maybe is rejected", ok)
code, out, err = shipm("switch", "hooks.dispatcher", "bogus")
check("shipm switch hooks.dispatcher bogus: exit 2, one shipm: line", code == 2 and err.startswith("shipm: ") and "Traceback" not in err, (code, err))
code, out, err = shipm("switch", "hooks.dispatcher", "shadow")
code2, out2, _ = shipm("switch", "hooks.dispatcher")
code3, out3, _ = shipm("hooks", "mode")
check("shipm switch hooks.dispatcher shadow is stored; switch NAME and hooks mode print it", code == 0 and out2.strip() == "shadow" and out3.strip() == "shadow" and code2 == code3 == 0, (out, out2, out3))
code, out, _ = shipm("switch", "hooks.record", "on")
check("shipm switch hooks.record on / off", code == 0 and config.get("hooks.record") is True and shipm("switch", "hooks.record", "off")[0] == 0 and config.get("hooks.record") is False)
code, out, err = shipm("switch", "hooks.record", "legacy")
check("shipm switch hooks.record legacy: exit 2", code == 2, err)
code, out, err = shipm("switch", "state.v1", "maybe")
check("existing switches still accept only on/off", code == 2 and err.startswith("shipm: "), err)
check("shipm switch state.v1 off/on still works", shipm("switch", "state.v1", "off")[0] == 0 and shipm("switch", "state.v1")[1].strip() == "off" and shipm("switch", "state.v1", "on")[0] == 0)

code, out, _ = shipm("hooks", "spec", "--mode", "legacy")
lines = [l for l in out.splitlines() if l.split("\t")[0] not in ("statusLine", "env")]
check("shipm hooks spec --mode legacy lists 17 entries and the statusLine", code == 0 and len(lines) == 17 and "statusLine\t-\t$HOME/Developer/AI-Workspace/hooks/plan-capture.sh" in out, out[:300])
code, out, _ = shipm("hooks", "spec", "--mode", "v1", "--json")
j = json.loads(out)
check("shipm hooks spec --json: v=1, mode, hooks, statusLine, env, deny_rules from gate-deny", code == 0 and j["v"] == 1 and j["mode"] == "v1" and j["hooks"] == spec.build("v1", ws=WSD)["hooks"] and j["deny_rules"] == spec.deny_rules(ws=WSD) and len(j["deny_rules"]) >= 15, list(j))
code, out, _ = shipm("hooks", "spec")
check("shipm hooks spec without --mode uses the configured mode (shadow)", code == 0 and "shipm-hook Stop --slow" in out)
code, out, err = shipm("hooks", "spec", "--mode", "nope")
check("shipm hooks spec --mode nope: exit 2", code == 2, err)

put(copy.deepcopy(FIX)); raw = SET.read_bytes()
code, out, err = shipm("sync", "--hooks", "shadow", "--dry-run")
check("shipm sync --hooks shadow --dry-run: prints the diff and 'nothing written', settings.json byte-identical", code == 0 and "--- settings.json (current)" in out and "nothing written" in out and SET.read_bytes() == raw, (code, out[-200:], err))
code, out, err = shipm("sync")
check("shipm sync (no --hooks) uses the configured mode (shadow)", code == 0 and cur()["hooks"] == ss.plan(FIX, "shadow", ws=WSD)[0]["hooks"] and "backup" in out and "undo:" in out, (out[-300:], err))
code, out, err = shipm("sync", "--legacy-hooks")
check("shipm sync --legacy-hooks restores today's block byte-for-byte", code == 0 and dumps(cur()["hooks"]) == dumps(CANON) and cur() == FIX, (out[-200:], err))
code, out, err = shipm("sync", "--hooks", "legacy")
check("shipm sync --hooks legacy when already in place: no change, no new backup", code == 0 and "no change" in out and "already in place" in out)
code, out, err = shipm("sync", "--hooks", "shadow", "--legacy-hooks")
check("--legacy-hooks conflicts with --hooks shadow: exit 2", code == 2, err)
code, out, err = shipm("sync", "--hooks", "bogus")
check("shipm sync --hooks bogus: exit 2", code == 2, err)
put("{oops"); code, out, err = shipm("sync", "--hooks", "shadow")
check("shipm sync on malformed settings: exit nonzero, one shipm: line, file untouched", code != 0 and err.startswith("shipm: ") and SET.read_text() == "{oops", (code, err))

# ---- L7: the rewrite keeps the file's style (not byte-exact, by design); a realistic settings.json round-trips
REAL = r"""{
  "model": "opusplan",
  "permissions": {
    "allow": ["Bash(git status:*)"],
    "deny": ["Read(./.env)"]
  },
  "hooks": {
    "SessionStart": [{"hooks": [{"type": "command", "command": "/usr/local/bin/notify \u2014 start"}]}],
    "Stop": [{"hooks": [{"type": "command", "command": "$HOME/Developer/AI-Workspace/hooks/keep-going.sh"}]}]
  },
  "statusLine": {"type": "command", "command": "$HOME/Developer/AI-Workspace/hooks/plan-capture.sh", "padding": 0},
  "note": "caf\u00e9 \u2014 owner text",
  "env": {"FOO": "bar"}
}
"""
REAL_UTF = REAL.replace("\\u2014", "\u2014").replace("\\u00e9", "\u00e9")
st = ss.style_of(REAL.encode()); st2 = ss.style_of(REAL_UTF.encode())
check("L7 style_of: indent 2, ensure_ascii kept per file, final newline", st == {"indent": 2, "ensure_ascii": True, "newline": True} and st2["ensure_ascii"] is False
      and ss.style_of(b'{\n\t"a": 1\n}')["indent"] == "\t" and ss.style_of(b'{\n    "a": 1\n}')["indent"] == 4 and ss.style_of(b'{"a": 1}')["newline"] is False, (st, st2))
for label, text in (("escaped unicode", REAL), ("literal unicode", REAL_UTF), ("4 spaces", json.dumps(json.loads(REAL), indent=4) + "\n"), ("tabs", json.dumps(json.loads(REAL), indent="\t", ensure_ascii=False) + "\n")):
    put(text)
    r = ss.apply(mode="legacy", ws=WSD)
    ss.apply(mode="shadow", ws=WSD); ss.apply(mode="legacy", ws=WSD)
    new_text = SET.read_text(); d = json.loads(new_text)
    style = ss.style_of(text.encode())
    check("L7 round trip (%s): result is written in the original style" % label, new_text == ss.dumps(d, style) and (("\\u" in new_text) == style["ensure_ascii"] or not re.search(r"[^\x00-\x7f]", json.dumps(d, ensure_ascii=False))), new_text[:200])
    check("L7 round trip (%s): key order and foreign keys unchanged, the foreign hook and unicode text intact" % label,
          list(d)[:3] == ["model", "permissions", "hooks"] and d["note"] == json.loads(text)["note"] and d["permissions"] == json.loads(text)["permissions"]
          and d["hooks"]["SessionStart"] == json.loads(text)["hooks"]["SessionStart"] and d["env"]["FOO"] == "bar", d)
    pick = lambda t: [l.strip() for l in t.splitlines() if l.strip().startswith(('"model"', '"note"'))]
    check("L7 round trip (%s): the untouched scalar lines (model, note with its unicode spelling) are byte-identical" % label, pick(text) == pick(new_text) and len(pick(text)) == 2, (pick(text), pick(new_text)))
put(REAL); b0 = len(bks()); ss.apply(mode="legacy", ws=WSD)
check("L7 backups stay 0600 and hold the exact old bytes", all(stat.S_IMODE(os.stat(p).st_mode) == 0o600 for p in bks()) and bks() and bks()[-1].read_text() == REAL, [oct(stat.S_IMODE(os.stat(p).st_mode)) for p in bks()])

# ---- 21 Oct 2026 regression: a no-op sync / repair leaves bytes, mtime, inode and xattrs untouched (the owner's real file was rewritten once with nothing to change) ----
def snap(p):
    st = os.stat(p)
    xa = shipmiracle_isolation.list_xattrs(p)
    return (st.st_ino, st.st_mtime_ns, st.st_size, SET.read_bytes(), sorted(xa))
put(FIX)
ss.apply(mode="legacy", ws=WSD, home=HOME)
HAVE_XA = shipmiracle_isolation.set_xattr(SET)
check("xattr part is only relaxed off a Mac: on macOS the attribute is really set and listed (HAVE_XA)", HAVE_XA is True and shipmiracle_isolation.list_xattrs(SET) != [] if sys.platform == "darwin" else True,
      (HAVE_XA, shipmiracle_isolation.list_xattrs(SET)))
time.sleep(0.05)
a0 = snap(SET); nb = len(bks())
r1 = ss.apply(mode="legacy", ws=WSD, home=HOME)
r2 = ss.apply(mode="legacy", ws=WSD, home=HOME, dry_run=True)
code, out, err = shipm("sync", "--hooks", "legacy")
check("no-op: apply, dry run and the CLI report no change", r1["changed"] is False and r2["changed"] is False and code == 0 and "already in place" in out, (r1["changed"], out, err))
check("no-op sync: bytes, mtime (ns), inode, size and extended attributes are exactly as before, and no backup was made", snap(SET) == a0 and len(bks()) == nb, (a0[:3], snap(SET)[:3], a0[4], snap(SET)[4]))
put({"model": "x", "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "/opt/foreign/keep.sh"}]}]}})
HAVE_XA = shipmiracle_isolation.set_xattr(SET)
check("xattr set on the second file (macOS must succeed)", HAVE_XA is True if sys.platform == "darwin" else True, HAVE_XA)
time.sleep(0.05)
a1 = snap(SET); nb = len(bks())
r3 = ss.repair(apply=True, ws=WSD, home=HOME)
code2, out2, err2 = shipm("sync", "--repair-hooks", "--apply")
code3, out3, err3 = shipm("sync", "--hooks", "off")
check("no-op repair and `--hooks off` (nothing shipmiracle-owned in the file) report no change", r3["changed"] is False and code2 == 0 and "nothing to repair" in out2 and code3 == 0 and "no change" in out3 + "already in place", (out2, out3, err2, err3))
check("no-op repair / off: bytes, mtime (ns), inode, size and extended attributes are exactly as before, and no backup was made", snap(SET) == a1 and len(bks()) == nb, (a1[:3], snap(SET)[:3], a1[4], snap(SET)[4]))
import time as _t

# ---- 21 Oct: fail-open wrapper, temp-path refusal, --repair-hooks ----
import json as _j
def _sh(cmd, stdin=b"", env=None):
    r = subprocess.run(["/bin/sh", "-c", cmd], input=stdin, capture_output=True, env=env or dict(ENV), timeout=30)
    return r.returncode, r.stdout, r.stderr
GOOD = ROOT / "hooks"               # the repo's own hooks folder: never under a temp root unless the checkout itself is (then the real-folder cases are skipped)
REAL_OUTSIDE_TEMP = not ss.is_temp_path(ROOT)
# differential: script exists -> the wrapper behaves byte-identically to the plain command
stubws = TMP / "stubws"; (stubws / "hooks").mkdir(parents=True)
(stubws / "hooks" / "shipm-hook").write_text("import sys,os\nsys.stdout.write(repr(sys.argv[1:]) + sys.stdin.read() + os.environ.get('HOME', ''))\nsys.stderr.write('err')\nsys.exit(3)\n")
for ev, words in (("Stop", ()), ("Stop", ("--slow",)), ("PreToolUse", ()), ("StatusLine", ()), ("SessionStart", ())):
    pre = str(stubws) + "/hooks/"
    a = _sh(spec.plain_dispatcher_command(pre, ev, words, HOME), b'{"x": 1}\n')
    b = _sh(spec.dispatcher_command(pre, ev, words, HOME), b'{"x": 1}\n')
    check("wrapper == plain command when the script exists (%s %s): stdout, stderr and exit code identical" % (ev, " ".join(words)), a == b and a[0] == 3 and b"err" in a[2], (a, b))
# missing script: exit 0 + visible warning on stdout for EVERY event, logged
LOG = STATE / "flow-errors.log"
if LOG.exists(): LOG.unlink()
allev = sorted({e[0] for e in spec.V1} | {"StatusLine"})
ok = True; info = ""
for ev in allev:
    rc, out, err = _sh(spec.dispatcher_command(str(TMP / "gone") + "/hooks/", ev, (), HOME), b"{}")
    txt = out.decode()
    try:
        good = rc == 0 and (txt.strip().startswith("Shipmiracle gate OFF") if ev == "StatusLine" else (_j.loads(txt)["systemMessage"].startswith("Shipmiracle gate OFF: hook script missing at " + str(TMP / "gone")) and list(_j.loads(txt)) == ["systemMessage"]))
    except Exception as x:
        good = False
    if not good:
        ok = False; info = (ev, rc, out, err)
check("wrapper: missing script -> exit 0 and the JSON systemMessage (plain text for StatusLine) on stdout for every event, no hookSpecificOutput", ok, info)
check("wrapper: missing script is logged to <state>/flow-errors.log", LOG.is_file() and "module=shipmiracle-hook-wrapper" in LOG.read_text() and "hook script missing" in LOG.read_text())
sp_cmd = spec.dispatcher_command("/x/", "Stop", (), HOME)
body = sp_cmd[len("/bin/sh -c '"):sp_cmd.index("' shipm-gate")]
rc, out, _ = _sh("/bin/sh -c '%s' shipm-gate '%s' Stop" % (body, str(TMP / "no such dir" / "shipm-hook")), b"")
check("wrapper: a script path with a space is handled (quoted word)", rc == 0 and "no such dir" in out.decode(), out)
# unwritable state folder: still exit 0 with the warning
rc, out, _ = _sh(spec.dispatcher_command(str(TMP / "gone") + "/hooks/", "Stop", (), HOME), b"{}", env=dict(ENV, SHIPMIRACLE_STATE="/proc/nope/none"))
check("wrapper: a log failure never changes the outcome (exit 0, warning printed)", rc == 0 and "systemMessage" in out.decode(), (rc, out))
# ownership: both forms; tampering is not owned
PRE = "$HOME/Developer/AI-Workspace/hooks/"
check("is_owned: the wrapper form and the old plain form are both owned; a tampered wrapper body is not", ss.is_owned(spec.dispatcher_command(PRE, "Stop", (), HOME), WSD, HOME)
      and ss.is_owned(spec.plain_dispatcher_command(PRE, "Stop", ("--slow",), HOME), WSD, HOME)
      and not ss.is_owned(spec.dispatcher_command(PRE, "Stop", (), HOME).replace("exit 0", "exit 0; curl evil"), WSD, HOME)
      and not ss.is_owned(spec.dispatcher_command("/opt/other/hooks/", "Stop", (), HOME), WSD, HOME)
      and ss.dispatcher_parts(spec.dispatcher_command(PRE, "Stop", ("--slow",), HOME)) == ("Stop", True) and ss.dispatcher_parts(spec.dispatcher_command(PRE, "Stop", (), HOME)) == ("Stop", False))
# migration old -> new, idempotent, foreign entries byte-faithful
old_form = copy.deepcopy(FIX); old_form["hooks"] = {"PreToolUse": [copy.deepcopy(FOREIGN_A)], "Stop": [{"hooks": [{"type": "command", "command": spec.plain_dispatcher_command(PRE, "Stop", (), HOME)}]}, copy.deepcopy(FOREIGN_B)]}
old_form["statusLine"] = {"type": "command", "command": spec.plain_dispatcher_command(PRE, "StatusLine", (), HOME), "padding": 0}
m1, _ = ss.plan(old_form, "v1", ws=WSD, home=HOME)
m2, d2 = ss.plan(m1, "v1", ws=WSD, home=HOME)
check("migration: old plain dispatcher entries become the wrapper on the next sync; foreign hooks untouched; a second run has no diff",
      m1["hooks"]["PreToolUse"][0] == FOREIGN_A and FOREIGN_B in m1["hooks"]["Stop"] and all(h["command"].startswith("/bin/sh -c '") for gs in m1["hooks"].values() for g in gs for h in g["hooks"] if h["command"] != FOREIGN_A["hooks"][0]["command"] and h["command"] != FOREIGN_B["hooks"][0]["command"])
      and m1["statusLine"]["command"].startswith("/bin/sh -c '") and m2 == m1 and d2 == "", json.dumps(m1)[:300])
# V1 now registers all nine events + StatusLine
check("spec.V1 registers SessionStart, Notification and PreModelSwitch too", {"SessionStart", "Notification", "PreModelSwitch"} <= {e[0] for e in spec.V1})
# temp-path refusal (needs a settings file outside every temp root: a folder in the checkout that is only read, never written, because the refusal comes first)
if REAL_OUTSIDE_TEMP:
    outside = ROOT / "tests" / "_never_written" / ".claude" / "settings.json"
    for mode in ("v1", "shadow", "legacy"):
        try:
            ss.apply(path=outside, mode=mode, dry_run=True, ws=WSD, home=HOME); r = None
        except SafetyError as x:
            r = str(x)
        check("temp-path refusal (%s): a hook script in a temp folder into a settings file outside temp -> SafetyError naming the path and the repair command" % mode,
              r is not None and str(WSD) in r and "--repair-hooks" in r, r)
    r2 = ss.apply(path=outside, mode="off", dry_run=True, ws=WSD, home=HOME)
    check("temp-path refusal: --hooks off stays possible", r2["changed"] is False and not outside.exists())
    # a real workspace is fine
    r3 = ss.apply(path=outside, mode="v1", dry_run=True, ws=ROOT, home=HOME)
    check("temp-path refusal: the real (non-temp) workspace is accepted", r3["changed"] is True)
    # hooks-global: the global dispatcher points into temp, the project file is outside temp -> refused
    # (the project move itself is covered in rollback_hooksglobal_test; here only the guard)
    sp = ss.temp_hook_paths(ss.plan({}, "v1", ws=WSD, home=HOME)[0], WSD, HOME)
    check("temp_hook_paths lists the temp scripts of the registered hooks", sp == [str(WSD) + "/hooks/shipm-hook"], sp)
    put(ss.plan({}, "v1", ws=WSD, home=HOME)[0])
    try:
        ss.project_hooks_global(ROOT / "tests" / "_never_written_proj", "x", ws=WSD, home=HOME); r = None
    except SafetyError as x:
        r = str(x)
    check("hooks-global: global hooks in a temp folder + a project outside temp -> refused, naming the repair command", r is not None and "--repair-hooks" in r, r)
    # repair
    other = TMP / "otherws"
    badset = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": spec.dispatcher_command(str(ROOT) + "/hooks/", "Stop", (), HOME)}]}],
                        "PreToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": spec.dispatcher_command(str(ROOT) + "/hooks/", "PreToolUse", (), HOME)}]}]}}   # good entries (script exists, not temp)
    badset["hooks"]["Stop"].append({"hooks": [{"type": "command", "command": spec.dispatcher_command(str(other) + "/hooks/", "Stop", (), HOME)}]})
    badset["hooks"]["PreToolUse"].append({"matcher": "Bash", "hooks": [{"type": "command", "command": "$HOME/Developer/gone-forever/hooks/keep-awake.sh"}]})
    badset["hooks"]["Stop"].append({"hooks": [{"type": "command", "command": "/tmp/foreign/hook.sh"}, {"type": "command", "command": spec.plain_dispatcher_command(str(other) + "/hooks/", "Stop", ("--slow",), HOME)}]})
    badset["hooks"]["Notification"] = badset["hooks"].get("Notification", []) + [{"hooks": [{"type": "command", "command": spec.dispatcher_command(str(other) + "/hooks/", "Notification", (), HOME)}]}]
    badset["permissions"] = {"deny": ["Bash(rm -rf /)"]}
    put(badset); raw0 = SET.read_bytes(); nb = len(bks())
    code, out, err = shipm("sync", "--repair-hooks")
    check("repair-hooks: dry run by default (prints the diff, writes nothing)", code == 0 and "dry run" in out and "--- settings.json" in out and SET.read_bytes() == raw0 and len(bks()) == nb, (code, out[-300:], err))
    code, out, err = shipm("sync", "--repair-hooks", "--apply")
    d = cur()
    cmds = [h["command"] for gs in d["hooks"].values() for g in gs for h in g["hooks"]]
    check("repair-hooks --apply: removes ONLY the Shipmiracle entries with a temp or missing script, keeps good Shipmiracle entries, the foreign /tmp hook and every other key",
          code == 0 and not any(str(other) in c or "gone-forever" in c for c in cmds) and "/tmp/foreign/hook.sh" in cmds and sum(1 for c in cmds if str(ROOT) in c) == 2
          and d["permissions"] == badset["permissions"] and "Notification" not in d["hooks"], (code, out[-400:], err, cmds))
    check("repair-hooks --apply: a 0600 backup holds the old bytes", bks()[-1].read_bytes() == raw0 and stat.S_IMODE(os.stat(bks()[-1]).st_mode) == 0o600)
    raw1 = SET.read_bytes(); newest = bks()[-1].name
    code, out, err = shipm("sync", "--repair-hooks", "--apply")
    check("repair-hooks is idempotent (second run: nothing to repair, file and backups unchanged)", code == 0 and "nothing to repair" in out and SET.read_bytes() == raw1 and bks()[-1].name == newest, (out, err))
    put({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": spec.dispatcher_command(str(other) + "/hooks/", "Stop", (), HOME)}]}]}, "statusLine": {"type": "command", "command": spec.dispatcher_command(str(other) + "/hooks/", "StatusLine", (), HOME), "padding": 0}, "model": "x"})
    ss.repair(apply=True)
    check("repair-hooks: an emptied event and an Shipmiracle statusLine are dropped, other keys stay", cur() == {"hooks": {}, "model": "x"}, cur())
else:
    print("SKIP temp-path refusal and repair cases: the checkout is itself under a temp folder")

shutil.rmtree(TMP, ignore_errors=True)
print("\nALL PASS" if not fails else "\n%d FAILED" % fails); sys.exit(1 if fails else 0)
