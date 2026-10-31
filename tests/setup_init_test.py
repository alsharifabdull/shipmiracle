#!/usr/bin/env python3
"""`shipm init`: the rows (read-only --check, JSON schema, ready), the idempotent apply loop, resume after a kill, skips, the owner/chat refusal,
the tool seam. Everything runs under SHIPMIRACLE_TEST=1 with a temp HOME / state / config / Developer / engine and FAKE tools in SHIPMIRACLE_SETUP_BIN
(tests/fakes/bin); nothing real is touched (a real-file fingerprint at the end proves it). Run: python3 tests/setup_init_test.py"""
import json, os, pathlib, shutil, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import setup_fixture as F  # noqa: E402
from shipmiracle import ShipmiracleError, SafetyError, UsageError, agents, config, paths, registry, settings_sync, state  # noqa: E402
from shipmiracle.setup import manifest, rows, run, call, tool  # noqa: E402
import shipmiracle.setup as setup_pkg  # noqa: E402

fails = 0
n_checks = 0


def check(name, ok, info=""):
    global fails, n_checks
    n_checks += 1
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(info)[:500]))
    fails += 0 if ok else 1


def init(yes=True, step=None, say=None):
    lines = []
    ctx = run.Ctx(yes=yes, say=(say or lines.append))
    res = run.apply_rows(ctx, only=step)
    return res, lines


def states(res):
    return {r["id"]: r["state"] for r in res["rows"]}


def check_json():
    return json.loads(run.check(as_json=True))


SETTINGS = F.HOME / ".claude" / "settings.json"
UD = F.HOME / ".claude" / "agents"
LINK = F.HOME / ".local" / "bin" / "shipm"
ALL = (F.HOME, F.STATE, F.CFG, F.WS)

# =============================================================== 1. fresh account, nothing installed
F.reset(with_fakes=False, logins=False, git_id=False)
before = F.snapshot(*ALL)
res = check_json()
check("--check on a fresh account writes nothing (home, state, config, engine, HOME snapshot equal)", F.diff(before, F.snapshot(*ALL)) == [], F.diff(before, F.snapshot(*ALL)))
check("fresh account: ready is false", res["ready"] is False)
check("schema: v=1, 22 rows numbered 0..21 (20 prefs, 21 gitleaks)", res["v"] == 1 and [r["n"] for r in res["rows"]] == list(range(22)))
check("no Wi-Fi row (removed by owner decision 21 Oct)", all("wifi" not in r["id"] for r in res["rows"]))
KEYS = {"n", "id", "title", "need", "state", "detail", "connect", "fix", "undo", "writes", "stage", "class", "os_supported", "docs"}      # v:1 only gained fields (plan 21 Oct)
check("schema: every row has exactly the documented keys", all(set(r) == KEYS for r in res["rows"]))
check("schema: states and needs are from the closed sets", all(r["state"] in ("green", "red", "skipped", "advisory", "never") and r["need"] in ("required", "recommended", "optional", "advisory", "never") for r in res["rows"]))
check("schema: connect is {kind,text} with a known kind", all(set(r["connect"]) == {"kind", "text"} and r["connect"]["kind"] in ("browser", "hint", "prompt", "write") and r["connect"]["text"] for r in res["rows"]))
check("schema: writes is a list of strings, fix and undo are texts", all(isinstance(r["writes"], list) and all(isinstance(w, str) for w in r["writes"]) and r["fix"] and r["undo"] for r in res["rows"]))
# D9 (Linux QA minor): row 9 on macOS is word for word what it was before the Linux merge (tag pre-linux-merge); the Linux / WSL text and the systemd unit paths live in the per-OS overrides
ROW9_MAC = {"connect": "Installs two launchd jobs for your account: the awake guard and the daily report.",
            "fix": "Renders templates/launchd/*.in, writes ~/Library/LaunchAgents/com.shipmiracle.*.plist, `launchctl bootstrap` (asks first). Prints the sudo line; never runs it.",
            "undo": "launchctl bootout, then deletes the plist if unchanged.",
            "writes": ["~/Library/LaunchAgents/com.shipmiracle.guard.plist", "~/Library/LaunchAgents/com.shipmiracle.daily.plist"]}
_old_fake = os.environ.get("SHIPMIRACLE_FAKE_OS")
try:
    os.environ["SHIPMIRACLE_FAKE_OS"] = "macos"
    r9 = [r for r in check_json()["rows"] if r["id"] == "guard"][0]
    check("row 9 on macOS: connect text, fix, undo and writes are the pre-linux-merge text", (r9["connect"]["text"], r9["fix"], r9["undo"], r9["writes"]) == (ROW9_MAC["connect"], ROW9_MAC["fix"], ROW9_MAC["undo"], ROW9_MAC["writes"]), r9)
    check("row 9 on macOS: no systemd path anywhere in the row", "systemd" not in json.dumps(r9) and r9["os_supported"] is True, r9)
    for kind in ("linux", "wsl"):
        os.environ["SHIPMIRACLE_FAKE_OS"] = kind
        rl = [r for r in check_json()["rows"] if r["id"] == "guard"][0]
        check("row 9 on %s: the systemd timer text and the two unit paths (no launchd path)" % kind, "systemd" in rl["fix"] and "systemctl" in rl["undo"] and any("systemd/user" in w for w in rl["writes"])
              and not any("LaunchAgents" in w for w in rl["writes"]) and rl["os_supported"] is True, rl)
    os.environ["SHIPMIRACLE_FAKE_OS"] = "windows"
    rw = [r for r in check_json()["rows"] if r["id"] == "guard"][0]
    check("row 9 on Windows: not supported, text is the macOS text", rw["os_supported"] is False and rw["fix"] == ROW9_MAC["fix"], rw)
finally:
    os.environ.pop("SHIPMIRACLE_FAKE_OS", None) if _old_fake is None else os.environ.__setitem__("SHIPMIRACLE_FAKE_OS", _old_fake)
st = states(res)
check("fresh: every required row is red", all(st[i] == "red" for i in ("engine", "base", "node", "claude", "vscode", "git-id", "projects", "registry")), st)
check("fresh: rows 13 and 15 are advisory, row 17 is never; the optional rows 14 (Remote Control) and 18 (ask inbox) are skipped, never red", st["connectors"] == st["backup"] == "advisory" and st["publishing"] == "never" and st["remote-control"] == st["ask-inbox"] == "skipped")
check("seam: with no fakes no external tool is found (PATH is not searched under SHIPMIRACLE_TEST)", tool("git") is None and call("git", ["--version"])[0] == 127)
check("text output renders the same rows", "Ready: no" in run.check(as_json=False) and "Engine" in run.check(as_json=False))

# =============================================================== 2. fakes installed: the apply loop
F.reset()
F.make_project("alpha")
(F.FAKE / "gh-logged-in").unlink()
before_real = F.REAL_BEFORE
res0 = check_json()
st0 = states(res0)
check("fakes installed: rows 1,2,3,5 green, engine/vscode/projects red", st0["base"] == st0["node"] == st0["claude"] == st0["git-id"] == "green" and st0["engine"] == st0["vscode"] == "red", st0)
check("fakes installed: before init not ready (engine, vscode, projects)", res0["ready"] is False)
res, lines = init(yes=True)
st1 = states(res)
check("init --yes: ready is true", res["ready"] is True, st1)
check("rows 0-5 and 7 are green after init", all(st1[i] == "green" for i in ("engine", "base", "node", "claude", "vscode", "git-id", "projects")), st1)
check("row 6 and 8 green after init --yes; the OPTIONAL awake guard (row 9) is not applied by --yes alone", st1["github"] == st1["registry"] == "green" and st1["guard"] == "red", st1)
c_yes = F.fake_calls()
check("init --yes alone: no launchctl call and no plist written (the README says the guard is off by default)", not any(c.startswith("launchctl") for c in c_yes) and not (F.HOME / "Library" / "LaunchAgents" / "com.shipmiracle.guard.plist").exists(), [c for c in c_yes if c.startswith("launchctl")])
check("init --yes alone: the guard row says how to opt in", any("optional" in l and "--step guard" in l for l in lines), [l for l in lines if "guard" in l.lower()][:3])
res_g, lines_g = init(yes=True, step="guard")          # the explicit opt-in the rest of this suite builds on
check("init --step guard applies the guard row", states(res_g)["guard"] == "green", states(res_g))
check("settings.json has the v1 dispatcher registration", SETTINGS.is_file() and "shipm-hook" in SETTINGS.read_text())
check("agent team installed in ~/.claude/agents", len(list(UD.glob("*.md"))) >= 10)
check("~/.local/bin/shipm links to the engine's bin/shipm", os.path.islink(LINK) and os.path.realpath(LINK) == os.path.realpath(F.WS / "bin" / "shipm"))
check("config: hooks.dispatcher is v1", config.get("hooks.dispatcher") == "v1")
check("the project was added to the registry", len(registry.load()["projects"]) == 1)
for lab in ("guard", "daily"):
    p = F.HOME / "Library" / "LaunchAgents" / ("com.shipmiracle.%s.plist" % lab)
    txt = p.read_text() if p.is_file() else ""
    check("plist %s rendered from the template (no placeholders, engine path in)" % lab, "@WS@" not in txt and "@STATE@" not in txt and str(F.WS) in txt, txt[:200])
calls = F.fake_calls()
check("fakes saw: gh login, extension installs, launchctl bootstrap", any(c.startswith("gh auth login") for c in calls) and any("--install-extension anthropic.claude-code" in c for c in calls)
      and any(c.startswith("code --install-extension shipmiracle.shipmiracle-panel") for c in calls) and sum(c.startswith("launchctl bootstrap") for c in calls) == 2, calls)
check("brew was never called (Shipmiracle never installs software)", not any(c.startswith("brew") for c in calls))
m = manifest.load()
mp = F.STATE / "v1" / "install-manifest.json"
check("manifest exists, mode 0600, no pending steps", mp.is_file() and (mp.stat().st_mode & 0o777) == 0o600 and not any(s["pending"] for s in m["steps"]))
acts = [s["action"] for s in m["steps"]]
check("manifest actions are from the closed set and cover config/settings/agents/symlink/mkdir/launchd/vscode/registry",
      set(acts) <= set(manifest.ACTIONS) and {"config_set", "settings_sync", "agents_install", "symlink", "mkdir", "file_write", "launchd", "vscode_ext", "registry_add"} <= set(acts), acts)
check("every committed step has an after_sha256 and a row", all(s.get("after_sha256") and isinstance(s.get("row"), int) for s in m["steps"]), [s for s in m["steps"] if not s.get("after_sha256")][:2])
ids = [s["id"] for s in m["steps"]]
check("step ids are unique and increasing", ids == sorted(set(ids)))
sst = next(s for s in m["steps"] if s["action"] == "settings_sync")
check("settings step: no previous file -> before null, no backup; check shows it", sst["before_sha256"] is None and sst["backup"] is None)

# ---- 3. re-run: no new steps, no new backup, no new mutating fake call
snap_state = F.snapshot(F.STATE)
steps_before = json.dumps(manifest.load(), sort_keys=True)
n_calls = len(F.fake_calls())
res2, lines2 = init(yes=True)
mut = [c for c in F.fake_calls()[n_calls:] if any(w in c for w in ("install", "bootstrap", "auth login", "uninstall", "bootout"))]
check("re-run: ready stays true", res2["ready"] is True)
check("re-run: manifest unchanged (no new steps)", json.dumps(manifest.load(), sort_keys=True) == steps_before)
check("re-run: no new backup files, state tree unchanged", F.diff(snap_state, F.snapshot(F.STATE)) == [], F.diff(snap_state, F.snapshot(F.STATE)))
check("re-run: no mutating fake tool call", mut == [], mut)
check("re-run: green rows print 'ok'", any(l.strip().startswith("0 ok") for l in lines2))
# --check after init: still read-only
snap_all = F.snapshot(*ALL)
rc_ = check_json()
check("--check after init changes nothing and says ready", rc_["ready"] and F.diff(snap_all, F.snapshot(*ALL)) == [])

# =============================================================== 4. skips and --step
F.reset()
(F.FAKE / "gh-logged-in").unlink()
res, _ = init(yes=False)
check("no --yes: required rows with a Fix still run (projects folder asks and is declined -> red)", states(res)["projects"] == "red" and states(res)["engine"] == "green")
check("no --yes: optional rows are not applied", states(res)["github"] == "red" and states(res)["guard"] == "red")
ctx = run.Ctx(yes=False, say=lambda s: None)
run.skip("guard", ctx)
st = states(check_json())
check("--skip guard: row shows skipped", st["guard"] == "skipped")
e = None
try:
    run.skip("engine", run.Ctx(yes=False, say=lambda s: None))
except UsageError as ex:
    e = ex
check("--skip on a required row is a usage error", e is not None)
e = None
try:
    run.skip("backup", run.Ctx(yes=False, say=lambda s: None))
except UsageError as ex:
    e = ex
check("--skip on an advisory row is a usage error", e is not None)
check("skips live in init.json (0600)", (F.STATE / "v1" / "init.json").is_file() and "guard" in json.loads((F.STATE / "v1" / "init.json").read_text())["skipped"]
      and ((F.STATE / "v1" / "init.json").stat().st_mode & 0o777) == 0o600)
res, _ = init(yes=True)
check("init --yes leaves a skipped row skipped (and applies the other optional row)", states(res)["guard"] == "skipped" and states(res)["github"] == "green", states(res))
res, _ = init(yes=True, step="guard")
check("--step guard un-skips and runs the row", states(res)["guard"] == "green")
check("ready is true", res["ready"])
e = None
try:
    init(step="nonsense")
except UsageError as ex:
    e = ex
check("--step with an unknown row is a usage error", e is not None)

# =============================================================== 5. kill between steps -> resume consistent
def killed_run(point_prefix, label):
    F.reset()
    class Kill(Exception):
        pass

    def fault(point):
        if point.startswith(point_prefix):
            raise Kill(point)
    manifest.FAULT = fault
    raised = False
    try:
        init(yes=True)
    except Kill:
        raised = True
    manifest.FAULT = None
    check("%s: the injected kill stopped the run" % label, raised)
    pend = [s for s in manifest.load()["steps"] if s["pending"]]
    check("%s: exactly one pending step is left behind" % label, len(pend) == 1, pend)
    n1 = len(manifest.load()["steps"])
    res, _ = init(yes=True)
    steps = manifest.load()["steps"]
    check("%s: the next run finishes ready" % label, res["ready"])
    check("%s: no pending step remains" % label, not any(s["pending"] for s in steps), steps)
    keys = [(s["action"], s.get("path") or s.get("key")) for s in steps]
    check("%s: no duplicated step" % label, len(keys) == len(set(keys)), keys)
    check("%s: every step is committed with an after_sha256" % label, all(s["after_sha256"] for s in steps))
    return pend[0]


p = killed_run("done:settings_sync", "kill after the settings write")
check("kill after the write: the step was completed from what is on disk (not dropped)", any(s["action"] == "settings_sync" for s in manifest.load()["steps"]))
p = killed_run("begin:agents_install", "kill before the team install")
check("kill before the action: the step was kept once and the team is installed", sum(s["action"] == "agents_install" for s in manifest.load()["steps"]) == 1 and len(list(UD.glob("*.md"))) >= 10)
p = killed_run("done:symlink", "kill after the link")
check("kill after the link: the link step exists", any(s["action"] == "symlink" for s in manifest.load()["steps"]))
# a pending step whose action never happened is dropped by reconcile
F.reset()
sid = manifest.begin(0, "symlink", LINK, before=None, before_sha256=None)
check("reconcile drops a pending step whose target never changed", manifest.reconcile() == [sid] and manifest.load()["steps"] == [])

# =============================================================== 6. row semantics
F.reset()
(F.FAKE / "no-clt").write_text("")
check("row 1 red without the command line tools", states(check_json())["base"] == "red")
F.reset()
os.environ["SHIPMIRACLE_FAKE_NODE_VERSION"] = "v16.20.0"
check("row 2 red for node 16", states(check_json())["node"] == "red")
os.environ["SHIPMIRACLE_FAKE_NODE_VERSION"] = "v18.0.0"
check("row 2 green for node 18", states(check_json())["node"] == "green")
del os.environ["SHIPMIRACLE_FAKE_NODE_VERSION"]
F.reset(logins=False)
check("row 3 red when Claude Code is not logged in", states(check_json())["claude"] == "red")
(F.HOME / ".claude.json").write_text(json.dumps({"oauthAccount": {"emailAddress": "x@example.com"}}))
j = check_json()
check("row 3 green via the login marker in ~/.claude.json (the value is never shown)", states(j)["claude"] == "green" and "x@example.com" not in json.dumps(j))
F.reset(git_id=False)
check("row 5 red without git name/email", states(check_json())["git-id"] == "red")
before = F.snapshot(F.HOME)
res, _ = init(yes=True)
check("row 5 stays red after init: Shipmiracle never writes the git identity", states(res)["git-id"] == "red" and not any("config --global user" in c and "--get" not in c and c.count(" ") > 3 for c in F.fake_calls())
      and not (F.TMP / "gh" / ".gitconfig").exists() and not (F.HOME / ".gitconfig").exists())
check("not ready while row 5 is red, even with all else green", res["ready"] is False)
F.reset()
(F.HOME / ".local" / "bin").mkdir(parents=True)
os.symlink("/usr/bin/true", str(LINK))
res, _ = init(yes=True)
check("a foreign ~/.local/bin/shipm is not replaced; row 0 stays red with the reason", os.readlink(str(LINK)) == "/usr/bin/true" and states(res)["engine"] == "red"
      and "points elsewhere" in next(r["detail"] for r in res["rows"] if r["id"] == "engine"))
F.reset()
config_dir_note = None
(F.HOME / ".claude").mkdir(parents=True)
SETTINGS.write_text("{not json")
res, _ = init(yes=True)
check("damaged settings.json: row 0 red with a reason, file untouched, no crash", states(res)["engine"] == "red" and SETTINGS.read_text() == "{not json")
F.reset()
res, _ = init(yes=True)
engine_row = next(r for r in res["rows"] if r["id"] == "engine")
check("engine.dir is remembered (init.json while the config key is not defined yet, or config)", run.load_init().get("engine_dir") == str(F.WS) or config.get("engine.dir", None) == str(F.WS))
cfg = run.load_init()
cfg["engine_dir"] = "/somewhere/else"
run.save_init(cfg)
if "engine.dir" not in config.SCHEMA:
    check("engine.dir pointing at another checkout -> row 0 red", states(check_json())["engine"] == "red")
else:
    check("engine.dir key defined in config (T1 landed): fallback unused", True)
F.reset()
make = F.make_project("beta")
check("row 8 red while a project is not registered", states(check_json())["registry"] == "red")
init(yes=True)
check("row 8 green after init; project registered", states(check_json())["registry"] == "green")
(F.DEV / "gamma").mkdir()
F.make_project("gamma")
check("a new project makes row 8 red again", states(check_json())["registry"] == "red")

# =============================================================== 7. CLI: exit codes, owner refusal inside a chat, JSON
F.reset()
snap = F.snapshot(*ALL)
rc, out, err = F.cli("init", "--check", "--json", env={"CLAUDECODE": "1", "SHIPMIRACLE_ENFORCE_OWNER": "1"})
j = json.loads(out) if rc == 0 else {}
check("init --check works inside a chat (no owner check), exit 0, JSON on stdout", rc == 0 and j.get("v") == 1 and len(j.get("rows", [])) == 22, (rc, err))
check("CLI --check wrote nothing", F.diff(snap, F.snapshot(*ALL)) == [], F.diff(snap, F.snapshot(*ALL)))
rc, out, err = F.cli("init", env={"CLAUDECODE": "1", "SHIPMIRACLE_ENFORCE_OWNER": "1"})
check("init inside a chat is refused with exit 4", rc == 4 and "not inside a Claude Code chat" in err, (rc, err))
check("the refusal changed nothing", F.diff(snap, F.snapshot(*ALL)) == [])
rc, out, err = F.cli("init", "--skip", "guard", env={"CLAUDECODE": "1", "SHIPMIRACLE_ENFORCE_OWNER": "1"})
check("init --skip inside a chat is refused (exit 4)", rc == 4)
rc, out, err = F.cli("init", "--check", "--yes")
check("--check with --yes is a usage error (exit 2)", rc == 2)
rc, out, err = F.cli("init", "--json")
check("--json without --check is a usage error (exit 2)", rc == 2)
rc, out, err = F.cli("init", "--yes")
check("CLI init --yes: exit 0 when ready", rc == 0 and "Ready: yes" in out, (rc, out[-300:], err))
rc, out, err = F.cli("init", "--step", "no-such-row", "--yes")
check("init --step with an unknown row is not a success (exit != 0)", rc != 0, (rc, out[-200:], err))
rc, out, err = F.cli("init", "--step", "engine", "--yes")
check("init --step on a green row exits 0 (only that row counts)", rc == 0, (rc, out[-200:], err))
rc, out, err = F.cli("init", "--check")
check("CLI text check lists rows and says READY", rc == 0 and "Ready: yes" in out and "Engine" in out)
rc, out, err = F.cli("sync", "--hooks", "off", "--dry-run")
check("shipm sync --hooks off is accepted by the CLI", rc == 0, (rc, err))

# =============================================================== 8. never asks for a secret / no terminal
F.reset()
res, lines = init(yes=False)
txt = "\n".join(lines).lower() + json.dumps(check_json()).lower()
check("no output asks for a password, token or key", not any(w in txt for w in ("password", "paste your", "enter your token", "api key")))
check("without a terminal and without --yes the questions are answered no, nothing hangs", states(res)["vscode"] == "red")

# =============================================================== 9. the seam is the only lookup path under SHIPMIRACLE_TEST
F.reset()
saved = os.environ.pop("SHIPMIRACLE_SETUP_BIN")
check("SHIPMIRACLE_TEST=1 without SHIPMIRACLE_SETUP_BIN: no tool at all (not even /usr/bin/git)", tool("git") is None and tool("ls") is None)
os.environ["SHIPMIRACLE_SETUP_BIN"] = saved
check("with the seam folder: the fake is found, real /usr/bin tools are not", tool("git") == str(F.SEAM / "git") and tool("ls") is None)
os.environ["SHIPMIRACLE_HOME"] = str(paths.real_home())
e = None
try:
    setup_pkg.guard_home()
except SafetyError as ex:
    e = ex
os.environ["SHIPMIRACLE_HOME"] = str(F.HOME)
check("guard_home refuses the account's real home under SHIPMIRACLE_TEST", e is not None)

# =============================================================== 10. nothing real was touched
check("real ~/.claude/settings.json, ~/.claude/agents, LaunchAgents, ~/.local/bin/shipm, ~/.config/shipmiracle and the install state are unchanged", F.real_unchanged(), F._real_fp())

shutil.rmtree(F.TMP, ignore_errors=True)
print("\n%d checks" % n_checks)
print("\nFAILED: %d" % fails if fails else "\nALL PASS")
sys.exit(1 if fails else 0)
