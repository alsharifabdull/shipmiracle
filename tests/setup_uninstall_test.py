#!/usr/bin/env python3
"""`shipm uninstall` (dry run, --apply, --purge), the install manifest, and `shipm sync --hooks off` (settings_sync mode off). Same sandbox as
setup_init_test.py: temp HOME / state / config / engine, fake tools in SHIPMIRACLE_SETUP_BIN, nothing real touched. Run: python3 tests/setup_uninstall_test.py"""
import copy, json, os, pathlib, shutil, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import setup_fixture as F  # noqa: E402
from shipmiracle import ShipmiracleError, SchemaError, UsageError, agents, config, paths, registry, settings_sync, state  # noqa: E402
from shipmiracle.setup import manifest, run, uninstall  # noqa: E402

fails = 0
n_checks = 0


def check(name, ok, info=""):
    global fails, n_checks
    n_checks += 1
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(info)[:600]))
    fails += 0 if ok else 1


def init(yes=True):
    ctx = run.Ctx(yes=yes, say=lambda s: None)
    res = run.apply_rows(ctx)
    if yes:                                                  # --yes alone no longer applies the OPTIONAL awake guard: opt in by name, as a person would
        res = run.apply_rows(run.Ctx(yes=yes, say=lambda s: None), only="guard")
    return res


def uni(apply=False, purge=False, confirm=None):
    lines = []
    rc = uninstall.run(apply=apply, purge=purge, confirm=confirm, say=lines.append)
    return rc, "\n".join(lines)


SETTINGS = F.HOME / ".claude" / "settings.json"
UD = F.HOME / ".claude" / "agents"
LINK = F.HOME / ".local" / "bin" / "shipm"
PLIST = F.HOME / "Library" / "LaunchAgents" / "com.shipmiracle.guard.plist"
ALL = (F.HOME, F.STATE, F.CFG, F.WS)
FOREIGN = {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "/opt/tools/my-lint.sh --strict"}]}],
                     "Notification": [{"hooks": [{"type": "command", "command": "/opt/tools/notify.sh"}]}]},
           "permissions": {"allow": ["Bash(ls:*)"]}, "model": "opus", "enabledPlugins": {"x@y": True}}

# =============================================================== 1. round trip: init then uninstall --apply --purge leaves the tree as it was
F.reset()
before = F.snapshot(*ALL)
init()
check("after init the tree differs (sanity)", F.diff(before, F.snapshot(*ALL)) != [])
snap_inited = F.snapshot(*ALL)
rc, out = uni(apply=False)
check("dry run (the default): exit 0, lists 'would reverse', changes nothing", rc == 0 and "would reverse" in out and "REVERSED" not in out and F.diff(snap_inited, F.snapshot(*ALL)) == [], out[-400:])
rc, out = uni(apply=True, purge=True, confirm="PURGE")
after = F.snapshot(*ALL)
check("uninstall --apply --purge: exit 0", rc == 0, out)
check("temp-HOME tree diff is empty (home, state, config, engine as before init)", F.diff(before, after) == [], F.diff(before, after))
check("the engine clone is not deleted; its rm line is printed", F.WS.is_dir() and "rm -rf %s" % F.WS in out)
check("fake calls: the guard jobs were booted out and the extensions uninstalled", sum(c.startswith("launchctl bootout") for c in F.fake_calls()) == 2
      and any(c.startswith("code --uninstall-extension shipmiracle.shipmiracle-panel") for c in F.fake_calls()))
check("gh / claude logins and brew were never touched", not any(c.startswith(("brew", "gh auth logout", "claude logout")) for c in F.fake_calls()))

# with a project present: the project survives, the registry entry init added is forgotten, the folder stays
F.reset()
F.make_project("alpha")
before = F.snapshot(*ALL)
init()
check("project registered by init", len(registry.load()["projects"]) == 1)
rc, out = uni(apply=True, purge=True, confirm="PURGE")
after = F.snapshot(*ALL)
check("with a project: round trip leaves the tree equal, the project repo untouched", F.diff(before, after) == [] and (F.DEV / "alpha" / ".git").is_dir(), F.diff(before, after))

# =============================================================== 2. no purge: manifest and init.json go, config/state folders stay
F.reset()
init()
rc, out = uni(apply=True)
check("apply without purge: exit 0, manifest and init.json removed, state/config folders kept",
      rc == 0 and not (F.STATE / "v1" / "install-manifest.json").exists() and not (F.STATE / "v1" / "init.json").exists() and F.STATE.is_dir(), out[-300:])
check("settings.json (created by init) is gone, ~/.claude gone, link gone, agents gone",
      not SETTINGS.exists() and not (F.HOME / ".claude").exists() and not os.path.lexists(str(LINK)) and not (F.HOME / ".local").exists())
check("config keys restored: hooks.dispatcher is back to legacy", config.get("hooks.dispatcher") == "legacy")
rc2, out2 = uni(apply=True)
check("a second uninstall --apply has nothing to do and exits 0", rc2 == 0 and "0 recorded step(s)" in out2)

# =============================================================== 3. purge guards
F.reset()
init()
snap = F.snapshot(*ALL)
e = None
try:
    uni(apply=True, purge=True)
except UsageError as ex:
    e = ex
check("--purge without the typed confirmation is refused (usage error) before anything is reversed", e is not None and F.diff(snap, F.snapshot(*ALL)) == [])
e = None
try:
    uni(apply=True, purge=True, confirm="purge")
except UsageError as ex:
    e = ex
check("a wrong confirmation (lower case) is refused", e is not None and F.diff(snap, F.snapshot(*ALL)) == [])
e = None
try:
    uni(apply=False, purge=True, confirm="PURGE")
except UsageError as ex:
    e = ex
check("--purge without --apply is a usage error", e is not None)
rc, out, err = F.cli("uninstall", "--apply", "--purge")
check("CLI: --apply --purge without --confirm and without a terminal -> exit 2", rc == 2 and F.diff(snap, F.snapshot(*ALL)) == [], (rc, err))
rc, out, err = F.cli("uninstall", "--apply", env={"CLAUDECODE": "1", "SHIPMIRACLE_ENFORCE_OWNER": "1"})
check("CLI: uninstall --apply inside a chat is refused with exit 4, nothing changes", rc == 4 and F.diff(snap, F.snapshot(*ALL)) == [], (rc, err))
rc, out, err = F.cli("uninstall", env={"CLAUDECODE": "1", "SHIPMIRACLE_ENFORCE_OWNER": "1"})
check("CLI: the dry run works inside a chat (read-only) and exits 0", rc == 0 and "dry run" in out and F.diff(snap, F.snapshot(*ALL)) == [], (rc, err))

# purge refuses to run while a step was skipped (the record must survive)
F.reset()
init()
config.set("hooks.dispatcher", "shadow")          # the owner changed it after init
rc, out = uni(apply=True, purge=True, confirm="PURGE")
check("purge is not done while a step was skipped; the manifest and state survive", rc == 1 and "PURGE not done" in out and (F.STATE / "v1" / "install-manifest.json").is_file() and F.CFG.is_dir(), out[-400:])
check("the config key the owner changed afterwards is left as the owner set it", config.get("hooks.dispatcher") == "shadow" and "SKIPPED" in out)

# =============================================================== 4. foreign hooks: byte-exact round trip
F.reset()
(F.HOME / ".claude").mkdir(parents=True)
orig = ("{\n\t\"model\": \"opus\",\n\t\"hooks\": " + json.dumps(FOREIGN["hooks"], indent="\t").replace("\n", "\n\t") + ",\n\t\"permissions\": {\"allow\": [\"Bash(ls:*)\"]}\n}\n").encode()
SETTINGS.write_bytes(orig)
init()
cur = json.loads(SETTINGS.read_text())
check("init kept the foreign hooks, permissions and model while adding the shipm hooks",
      cur["model"] == "opus" and cur["permissions"] == {"allow": ["Bash(ls:*)"]}
      and cur["hooks"]["PreToolUse"][0]["hooks"][0]["command"] == "/opt/tools/my-lint.sh --strict" and cur["hooks"]["Notification"][0]["hooks"][0]["command"] == "/opt/tools/notify.sh"
      and any("shipm-hook" in h["command"] for g in cur["hooks"]["PreToolUse"] for h in g["hooks"]))
check("init kept the file's tab indent", SETTINGS.read_text().startswith("{\n\t\""))
m = manifest.load()
sst = next(s for s in m["steps"] if s["action"] == "settings_sync")
check("settings step records the backup of the original and its sha", sst["backup"] and pathlib.Path(sst["backup"]).read_bytes() == orig and sst["before_sha256"] == manifest.sha_bytes(orig))
check("the backup is private (0600)", (pathlib.Path(sst["backup"]).stat().st_mode & 0o777) == 0o600)
uni(apply=True)
check("uninstall restores settings.json byte-for-byte", SETTINGS.read_bytes() == orig)
check("the ~/.claude folder (not created by init) stays", (F.HOME / ".claude").is_dir())

# settings edited by the owner after init -> SKIPPED with the exact remedy; then `off` clears only Shipmiracle entries
F.reset()
(F.HOME / ".claude").mkdir(parents=True)
SETTINGS.write_bytes(orig)
init()
d = json.loads(SETTINGS.read_text()); d["model"] = "sonnet"
SETTINGS.write_text(json.dumps(d, indent="\t") + "\n")
edited = SETTINGS.read_bytes()
rc, out = uni(apply=True)
check("settings edited after init: SKIPPED, file untouched, the 'shipm sync --hooks off' remedy is printed, exit 1",
      rc == 1 and "SKIPPED" in out and "shipm sync --hooks off" in out and SETTINGS.read_bytes() == edited, out[-500:])
r = settings_sync.apply(mode="off")
back = json.loads(SETTINGS.read_text())
check("sync --hooks off removed every Shipmiracle entry and kept the owner's edit and the foreign hooks",
      r["changed"] and back["model"] == "sonnet" and back["hooks"] == FOREIGN["hooks"] and "shipm-hook" not in SETTINGS.read_text() and back["permissions"] == FOREIGN["permissions"])
rc, out = uni(apply=True)
check("after 'off' the settings step is settled (no Shipmiracle entry left) and uninstall finishes with exit 0", rc == 0 and not (F.STATE / "v1" / "install-manifest.json").exists(), out[-500:])

# =============================================================== 5. a user-edited agent file is skipped
F.reset()
init()
names = sorted(p.name for p in UD.glob("*.md"))
mine = UD / names[0]
mine.write_text(mine.read_text() + "\nmy own line\n")
rc, out = uni(apply=True)
check("user-edited agent file is kept, the others are removed", mine.exists() and sorted(p.name for p in UD.glob("*.md")) == [names[0]], sorted(p.name for p in UD.glob("*.md")))
check("the kept file is reported (changed by hand)", "kept (changed by hand)" in out and names[0][:-3] in out, out[-500:])
check("~/.claude/agents is not removed while it holds a file", UD.is_dir() and "folder is not empty" in out)

# =============================================================== 6. other steps: owner changes are never overwritten
F.reset()
init()
os.unlink(str(LINK)); os.symlink("/usr/bin/true", str(LINK))
PLIST.write_text(PLIST.read_text() + "<!-- edited -->\n")
rc, out = uni(apply=True)
check("a link the owner re-pointed is left alone (SKIPPED)", os.readlink(str(LINK)) == "/usr/bin/true" and "SKIPPED" in out)
check("an edited plist is left (SKIPPED) but its job is still booted out", PLIST.exists() and "<!-- edited -->" in PLIST.read_text()
      and any(c.startswith("launchctl bootout gui/") and "com.shipmiracle.guard" in c for c in F.fake_calls()))
check("exit code 1 when something was skipped", rc == 1)

F.reset()
F.make_project("alpha")
init()
pid = next(iter(registry.load()["projects"]))
d = registry.load(); d["projects"][pid]["type"] = "software"
state.atomic_write(registry.path(), (json.dumps(d, sort_keys=True, indent=1) + "\n").encode())
rc, out = uni(apply=True)
check("a registry entry the owner edited is not forgotten", pid in registry.load()["projects"] and "SKIPPED" in out)

F.reset()
(F.FAKE / "code-extensions").write_text("anthropic.claude-code\n")
init()
uni(apply=True)
calls = F.fake_calls()
check("an extension that was there before init is not uninstalled; the one init installed is",
      not any("--uninstall-extension anthropic.claude-code" in c for c in calls) and any("--uninstall-extension shipmiracle.shipmiracle-panel" in c for c in calls), calls[-6:])

F.reset()
agents.install(ws=F.WS)                                  # the owner installed the team earlier, by hand
settings_sync.apply(mode="v1")
init()
steps = manifest.load()["steps"]
check("a team and hooks that were fully installed before init get no step of their own", not any(s["action"] in ("settings_sync", "agents_install") for s in steps), steps)
rc, out = uni(apply=True)
check("uninstall leaves the earlier team install and the hooks alone", len(list(UD.glob("*.md"))) >= 10 and "shipm-hook" in SETTINGS.read_text(), out[-400:])

F.reset()
agents.install(ws=F.WS)
master = sorted((F.WS / "agents" / "claude").glob("*.md"))[0]
master.write_text(master.read_text() + "\n<!-- newer master -->\n")
init()
st_ = [s for s in manifest.load()["steps"] if s["action"] == "agents_install"]
check("a team installed earlier and updated by init is recorded as pre-existing", len(st_) == 1 and st_[0]["preexisting"] is True, st_)
rc, out = uni(apply=True)
check("uninstall leaves a pre-existing team alone and says why", len(list(UD.glob("*.md"))) >= 10 and "was already there" in out, out[-500:])

# =============================================================== 7. the manifest itself
F.reset()
snap = F.snapshot(*ALL)
check("load() on a fresh account is empty and creates nothing", manifest.load() == {"v": 1, "steps": []} and F.diff(snap, F.snapshot(*ALL)) == [])
sid = manifest.begin(3, "config_set", "hooks.dispatcher", before="legacy", before_sha256="x")
mp = manifest.path()
check("manifest file is 0600 and the state folders 0700", (mp.stat().st_mode & 0o777) == 0o600 and (F.STATE.stat().st_mode & 0o777) == 0o700 and ((F.STATE / "v1").stat().st_mode & 0o777) == 0o700)
s = manifest.load()["steps"][0]
check("a begun step is pending with the documented fields", s["pending"] is True and {"id", "row", "action", "key", "before", "before_sha256", "after_sha256", "backup", "ts"} <= set(s), s)
e = None
try:
    manifest.begin(1, "rm_rf", "x")
except SchemaError as ex:
    e = ex
check("an unknown action is refused", e is not None)
mp.write_text("{broken")
e = None
try:
    manifest.load()
except SchemaError as ex:
    e = ex
check("a damaged manifest raises SchemaError (exit 1), it is not guessed at", e is not None)
rc, out, err = F.cli("uninstall")
check("CLI uninstall with a damaged manifest fails cleanly (exit 1, no traceback)", rc == 1 and "Traceback" not in err, (rc, err))
mp.unlink()
pa = manifest.backup_file(F.WS / "bin" / "shipm", "shipm")
check("backup_file copies with 0600 and returns None for an absent file", pa and (pathlib.Path(pa).stat().st_mode & 0o777) == 0o600 and manifest.backup_file(F.TMP / "nope", "x") is None)

# =============================================================== 8. settings_sync mode off (unit)
HOME_ = F.HOME
hook = settings_sync.spec.build("v1")["hooks"]
v1_cmd = hook["PreToolUse"][0]["hooks"][0]["command"]
legacy_cmd = settings_sync.spec.build("legacy")["hooks"]["Stop"][0]["hooks"][0]["command"] if "Stop" in settings_sync.spec.build("legacy")["hooks"] else None
base = {"model": "opus", "env": {"MY": "1"}, "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "/x/y.sh"}]}]}}
new, _ = settings_sync.plan(base, "off")
check("off on a file with no Shipmiracle entry changes nothing", new == base)
w, _ = settings_sync.plan(base, "v1")
off, _ = settings_sync.plan(w, "off")
check("v1 then off restores the foreign hooks exactly; the env keys v1 added are left (not provably Shipmiracle's)", off["hooks"] == base["hooks"] and off["model"] == "opus" and off["env"]["MY"] == "1")
check("off drops a statusLine that is Shipmiracle's", "statusLine" not in off and "statusLine" in w)
w2 = copy.deepcopy(w); w2["statusLine"] = {"type": "command", "command": "/opt/mine/status.sh"}
check("off keeps a foreign statusLine", settings_sync.plan(w2, "off")[0]["statusLine"]["command"] == "/opt/mine/status.sh")
only, _ = settings_sync.plan({}, "v1")
off2, _ = settings_sync.plan(only, "off")
check("off on an shipmiracle-only file drops the emptied hooks key", "hooks" not in off2, off2)
check("off on {} stays {}", settings_sync.plan({}, "off")[0] == {})
leg, _ = settings_sync.plan({}, "legacy")
check("off also removes legacy-script registrations", "hooks" not in settings_sync.plan(leg, "off")[0])
fm = {"hooks": {"PreToolUse": [{"hooks": [{"type": "command", "command": "/opt/mine/wrap.sh %s/hooks/keep-awake.sh" % F.WS}]}]}}
check("a foreign hook that merely mentions an Shipmiracle script path stays (P4 L7)", settings_sync.plan(fm, "off")[0] == fm)
grp = {"hooks": {"PreToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": "/opt/mine/a.sh"}, copy.deepcopy(hook["PreToolUse"][0]["hooks"][0])]}]}}
res_g = settings_sync.plan(grp, "off")[0]
check("in a mixed group only the Shipmiracle hook is removed", res_g["hooks"]["PreToolUse"][0]["hooks"] == [{"type": "command", "command": "/opt/mine/a.sh"}])
e = None
try:
    settings_sync.plan({"hooks": []}, "off")
except SchemaError:
    e = 1
except Exception:
    e = None
check("off on a malformed hooks value fails closed (SchemaError)", e is not None)
e = None
try:
    settings_sync.plan({}, "bogus")
except UsageError as ex:
    e = ex
check("an unknown mode is still refused", e is not None)
F.reset()
(F.HOME / ".claude").mkdir(parents=True)
orig = json.dumps(base, indent=4).encode() + b"\n"
SETTINGS.write_bytes(orig)
r1 = settings_sync.apply(mode="off")
check("apply(off) on a file without Shipmiracle entries writes nothing (no backup, bytes identical)", not r1["changed"] and r1["backup"] is None and SETTINGS.read_bytes() == orig)
settings_sync.apply(mode="v1")
r2 = settings_sync.apply(mode="off")
check("apply(off) after v1: changed, a backup is made, the file parses and keeps the 4-space indent", r2["changed"] and r2["backup"] and SETTINGS.read_text().startswith("{\n    \""))
r3 = settings_sync.apply(mode="off")
check("apply(off) twice is a no-op", not r3["changed"])
rc, out, err = F.cli("sync", "--hooks", "off")
check("CLI shipm sync --hooks off: exit 0, no change", rc == 0 and "no change" in out, (rc, out, err))
rc, out, err = F.cli("sync", "--hooks", "v1")
rc2, out2, err2 = F.cli("sync", "--hooks", "off")
check("CLI shipm sync --hooks v1 then off: removes the registration", rc == 0 and rc2 == 0 and "shipm-hook" not in SETTINGS.read_text(), (out2, err2))

# =============================================================== 8b. L8: a forged install manifest is refused step by step
def forge(mutate):
    mp = manifest.path()
    m = json.loads(mp.read_text())
    mutate(m)
    mp.write_text(json.dumps(m))
F.reset()
init()
victim = F.HOME / "victim.txt"; victim.write_text("precious\n")
outside = F.HOME / "outside-backup.json"; outside.write_text(json.dumps({"hooks": {}}))
def f1(m):
    for st in m["steps"]:
        if st["action"] == "settings_sync":
            st["path"] = str(victim); st["backup"] = None; st["after_sha256"] = manifest.sha_file(victim); break
forge(f1)
rc, out = uni(apply=True)
check("L8 a settings_sync step whose path is not the settings file: 'manifest entry refused', the file is untouched, the run goes on", "manifest entry refused" in out and victim.read_text() == "precious\n" and "REVERSED" in out, out[-700:])
F.reset(); init()
SETTINGS.write_text(json.dumps({"remote": 1})); before_set = SETTINGS.read_bytes()
def f2(m):
    for st in m["steps"]:
        if st["action"] == "settings_sync":
            st["backup"] = str(outside)
forge(f2)
rc, out = uni(apply=False)
check("L8 a backup outside <state>/v1/install-backups is refused (also in the dry run)", "manifest entry refused" in out and "install-backups" in out, out[-600:])
F.reset(); init()
dev = paths.dev_dir(); dev.mkdir(parents=True, exist_ok=True)
step = manifest.begin(18, "ask_project", "forged", folder=str(F.HOME))
forge(lambda m: [st.update(pending=False, after_sha256=None) for st in m["steps"] if st["id"] == step])
rc, out = uni(apply=True)
check("L8 an ask_project step whose folder is the parent of the projects folder is refused; the folder stays", "manifest entry refused" in out and F.HOME.is_dir(), out[-500:])
for kind, bad in (("file_write", "/etc/hosts"), ("symlink", "/usr/local/bin/shipm")):
    F.reset(); init()
    sid = manifest.begin(0, kind, bad)
    forge(lambda m: [st.update(pending=False, after_sha256="deadbeef") for st in m["steps"] if st["id"] == sid])
    rc, out = uni(apply=True)
    check("L8 a %s step outside home/config/state/projects (%s) is refused" % (kind, bad), "manifest entry refused" in out and ("REVERSED  step %d " % sid) not in out and ("step %-3s row 0  %s %s: manifest entry refused" % (sid, kind, bad)) in out, out[-500:])
for kind, extra, nm in (("file_write", {}, ".zshrc"), ("symlink", {}, ".zshrc"), ("launchd", {"label": "com.evil.job"}, "Library/LaunchAgents/com.evil.job.plist"),
                        ("mkdir", {}, ".ssh"),
                        ("file_write", {}, ".config/systemd/user/evil.service"), ("file_write", {}, ".config/autostart/evil.desktop"),
                        ("systemd", {"label": "com.evil.timer"}, ".config/systemd/user/com.evil.timer"), ("systemd", {"label": "com.shipmiracle.daily"}, ".config/systemd/user/evil.timer"),      # D9: the systemd validate in this suite
                        ("config_set", {}, None), ("vscode_ext", {}, None)):
    F.reset(); init()
    victim = F.HOME / (nm or "x"); (victim.parent).mkdir(parents=True, exist_ok=True); victim.write_text("mine\n") if kind != "mkdir" else victim.mkdir(exist_ok=True)
    if kind == "config_set":
        sid = manifest.begin(0, kind, "gate.level", before="block", before_sha256=manifest.sha_json("block"))
    elif kind == "vscode_ext":
        sid = manifest.begin(4, kind, "evil.ext", before=False, before_sha256=None)
    else:
        sid = manifest.begin(0, kind, victim, **extra)
    forge(lambda m: [st.update(pending=False, after_sha256=manifest.sha_file(victim) if (nm and kind != "mkdir") else "x") for st in m["steps"] if st["id"] == sid])
    rc, out = uni(apply=True)
    check("L8b forged %s step (%s) is refused by the exact-allowlist and nothing is touched" % (kind, nm or "key"), ("manifest entry refused" in out) and ("REVERSED  step %d " % sid) not in out
          and (nm is None or victim.exists()), out[-400:])
F.reset(); (F.HOME / ".claude").mkdir(parents=True); SETTINGS.write_text("{}")
victim.write_text("precious\n"); outside.write_text("{}")
e = None
try:
    settings_sync.undo_remote_control(None, str(victim), None, None, None)
except ShipmiracleError as ex:
    e = ex
check("L8 undo_remote_control refuses a path that is not the settings file", e is not None and "manifest entry refused" in str(e) and victim.read_text() == "precious\n", e)
e = None
try:
    settings_sync.undo_remote_control(None, str(SETTINGS), str(outside), "x", "y")
except ShipmiracleError as ex:
    e = ex
check("L8 undo_remote_control refuses a backup outside install-backups", e is not None and "manifest entry refused" in str(e), e)
F.reset()
(F.HOME / "src.json").write_text("{}")
made = [manifest.backup_file(F.HOME / "src.json", "settings.json") for _ in range(26)]
left = sorted(os.listdir(manifest.backups_dir()))
check("L8 install-backups is pruned to the newest 20", len(left) == 20 and os.path.basename(made[-1]) in left, len(left))

# =============================================================== 8b. the PURGE question: Ctrl-D, Ctrl-C, wrong word, right word, piped stdin (real ptys)
import pty, select, signal, subprocess, time  # noqa: E402


def pty_uni(chunks, timeout=60):
    """Run `bin/shipm uninstall --apply --purge` on a real pty; chunks are sent when the output goes quiet (b'\\x04' = Ctrl-D, b'SIGINT' = the signal). -> (exit code, output)."""
    env = dict(os.environ); env.pop("CLAUDECODE", None); env["SHIPMIRACLE_FAKE_OS"] = "macos"
    m, sl = pty.openpty()
    p = subprocess.Popen([sys.executable, str(F.ROOT / "bin" / "shipm"), "uninstall", "--apply", "--purge"], stdin=sl, stdout=sl, stderr=sl, env=env, close_fds=True)
    os.close(sl)
    out, chunks, t0 = b"", list(chunks), time.time()
    while p.poll() is None and time.time() - t0 < timeout:
        r, _, _ = select.select([m], [], [], 1.0)
        if r:
            try:
                out += os.read(m, 4096)
            except OSError:
                break
        elif chunks and b"PURGE" in out:
            c = chunks.pop(0)
            if c == b"SIGINT":
                p.send_signal(signal.SIGINT)
            else:
                os.write(m, c)
    try:
        while True:
            r, _, _ = select.select([m], [], [], 0.3)
            if not r:
                break
            x = os.read(m, 4096)
            if not x:
                break
            out += x
    except OSError:
        pass
    rc = p.wait(timeout=10) if p.poll() is not None else None
    if rc is None:
        p.kill(); p.wait()
    os.close(m)
    return rc, out.decode("utf-8", "replace").replace("\r", "")


PAUSE = "Uninstall paused. Nothing was deleted. Run shipm uninstall --apply --purge again."
for label, chunks in (("Ctrl-D", [b"\x04"]), ("Ctrl-C (SIGINT)", [b"SIGINT"]), ("wrong word", [b"purge\n"])):
    F.reset(); init()
    snap = F.snapshot(*ALL)
    rc, out = pty_uni(chunks)
    if label == "wrong word":
        check("PURGE prompt, wrong word: refused (exit 2), no traceback, tree identical", rc == 2 and "--confirm PURGE" in out and "Traceback" not in out and "unexpected error" not in out and F.diff(snap, F.snapshot(*ALL)) == [], (rc, out[-400:]))
    else:
        check("PURGE prompt, %s: exit 130, the one sentence, no traceback, tree identical" % label,
              rc == 130 and PAUSE in out and out.count("paused") == 1 and "Traceback" not in out and "unexpected error" not in out and F.diff(snap, F.snapshot(*ALL)) == [], (rc, out[-400:]))
F.reset(); init()
rc, out = pty_uni([b"PURGE\n"])
check("PURGE prompt, the right word: accepted, uninstall runs (exit 0), config and state folders purged", rc == 0 and "Traceback" not in out and not (F.CFG / "config.json").exists() and "REVERSED" in out, (rc, out[-400:]))
F.reset(); init()
snap = F.snapshot(*ALL)
for label, kw in (("piped stdin with data", dict(input="PURGE\n")), ("stdin closed (/dev/null)", dict(stdin=subprocess.DEVNULL))):
    e = dict(os.environ); e.pop("CLAUDECODE", None)
    r = subprocess.run([sys.executable, str(F.ROOT / "bin" / "shipm"), "uninstall", "--apply", "--purge"], env=e, capture_output=True, text=True, **kw)
    check("no terminal + no --confirm (%s): the usage error (exit 2), nothing removed" % label, r.returncode == 2 and "--confirm PURGE" in r.stderr and "Traceback" not in r.stderr and F.diff(snap, F.snapshot(*ALL)) == [], (r.returncode, r.stderr[-300:]))

# =============================================================== 8c. an interrupt DURING removal: honest message, rerun finishes, nothing stuck in the manifest
import contextlib, io, types  # noqa: E402
from shipmiracle.setup import cli as setup_cli  # noqa: E402

STOPPED = "Uninstall stopped partway. Some steps were already undone. Run shipm uninstall --apply again to finish."


def noise(d):
    return {k: v for k, v in d.items() if "__pycache__" not in k and not k.endswith("events.jsonl")}


def init_p():
    init()
    b = {k: None for k in ("prefs.lang", "prefs.notify")}
    with manifest.recorded(20, "prefs", "prefs", before=b, before_sha256=manifest.sha_json(b), keys=sorted(b), after={"prefs.lang": "ar", "prefs.notify": "vscode"}):
        config.set("prefs.lang", "ar"); config.set("prefs.notify", "vscode")


def final_tree():
    F.reset(); init_p()
    uni(apply=True)
    return F.snapshot(*ALL)


def cli_uni(purge=False, confirm=None):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = setup_cli.run_uninstall(types.SimpleNamespace(apply=True, purge=purge, confirm=confirm))
    return rc, buf.getvalue()


REF = final_tree()
n_steps = 0
bad = []
for where in ("after_reverse", "after_drop"):
    for N in range(1, 40):
        F.reset(); init_p()
        real_rev, real_drop, cnt = uninstall._reverse, manifest.drop, [0]
        if where == "after_reverse":
            def rev(s, real_rev=real_rev, cnt=cnt, N=N):
                r = real_rev(s); cnt[0] += 1
                if cnt[0] == N:
                    raise KeyboardInterrupt()
                return r
            uninstall._reverse = rev
        else:
            def drp(i, real_drop=real_drop, cnt=cnt, N=N):
                real_drop(i); cnt[0] += 1
                if cnt[0] == N:
                    raise KeyboardInterrupt()
            manifest.drop = drp
        try:
            rc, out = cli_uni()
        finally:
            uninstall._reverse, manifest.drop = real_rev, real_drop
        if cnt[0] < N:
            break                                   # fewer than N steps: the sweep is complete
        n_steps = N
        rc2, out2 = cli_uni()
        ok = rc == 130 and STOPPED in out and "Nothing was deleted" not in out and rc2 == 0 and F.diff(noise(REF), noise(F.snapshot(*ALL))) == [] and not manifest.load()["steps"]
        if not ok:
            bad.append((where, N, rc, out[-200:], rc2, out2[-100:], F.diff(noise(REF), noise(F.snapshot(*ALL))), manifest.load()['steps'][:1]))
check("interrupt after every reversal and after every manifest drop (%d steps): 130 + the 'stopped partway' sentence, rerun exits 0, tree equals the uninterrupted result, manifest empty" % n_steps, n_steps >= 5 and not bad, bad[:2])

F.reset(); init_p()
real = uninstall._reverse
def rev_first(s):
    raise KeyboardInterrupt()
uninstall._reverse = rev_first
try:
    rc, out = cli_uni(purge=True, confirm="PURGE")
finally:
    uninstall._reverse = real
check("interrupt during a --purge run: the sentence tells to rerun with --purge", rc == 130 and "uninstall --apply --purge again to finish" in out, (rc, out))

F.reset(); init_p()
init_p()
st = [x for x in manifest.load()["steps"] if x["action"] == "prefs"]
k = st[0]["keys"][0] if st else None
if k:
    config.set("prefs.lang", "en")
    rc, out = uni(apply=True)
    check("a prefs step edited by hand after init is still left alone (SKIPPED, exit 1, value kept)", rc == 1 and "changed since init" in out and config.get("prefs.lang", None) == "en", (rc, out[-500:]))
else:
    check("prefs step present after init (sanity)", False, st)

# --- the prefs restore is ONE atomic write, and a restore cut off part way is finished on the rerun (deterministic, no timing)
F.reset(); init_p()
writes, real_aw = [], state.atomic_write
def counting(path_, data, mode=0o600):
    writes.append(str(path_)); return real_aw(path_, data, mode)
state.atomic_write = counting
try:
    s_prefs = [x for x in manifest.load()["steps"] if x["action"] == "prefs"][0]
    writes.clear(); uninstall._reverse(s_prefs)
finally:
    state.atomic_write = real_aw
check("prefs reversal writes the config file exactly once", len([w for w in writes if w.endswith("config.json")]) == 1 and config.get("prefs.lang", None) is None and config.get("prefs.notify", None) is None, writes)

F.reset(); init_p()
def boom(path_, data, mode=0o600):
    if str(path_).endswith("config.json"):
        raise KeyboardInterrupt()
    return real_aw(path_, data, mode)
state.atomic_write = boom
try:
    rc, out = cli_uni()
finally:
    state.atomic_write = real_aw
config._cache.clear()
check("interrupt inside the prefs config write: no half state (both keys still at their init values), honest sentence", rc == 130 and STOPPED in out and config.get("prefs.lang", None) == "ar" and config.get("prefs.notify", None) == "vscode", (rc, out[-200:]))
rc2, _ = cli_uni()
check("... and the rerun exits 0 with the tree of an uninterrupted uninstall and an empty manifest", rc2 == 0 and F.diff(noise(REF), noise(F.snapshot(*ALL))) == [] and not manifest.load()["steps"])

for sub in ((), ("prefs.lang",), ("prefs.notify",)):          # keys already restored by a cut-off older run
    F.reset(); init_p()
    for k in sub:
        config.unset(k)
    rc, out = cli_uni()
    check("partly restored prefs (already back: %s): the rerun finishes it, exit 0, tree equals an uninterrupted uninstall, manifest empty" % (", ".join(sub) or "none"),
          rc == 0 and F.diff(noise(REF), noise(F.snapshot(*ALL))) == [] and not manifest.load()["steps"], (rc, out[-300:]))
F.reset(); init_p()
config.set("prefs.lang", "en"); config.unset("prefs.notify")          # one key hand-edited (neither old nor new) plus one already restored
rc, out = cli_uni()
check("partly restored prefs with a hand-edited key: left alone (SKIPPED, exit 1, the edited value kept)", rc == 1 and "changed since init" in out and config.get("prefs.lang", None) == "en", (rc, out[-300:]))

# --- a stale temp file from an interrupted manifest write is cleaned by the next run
F.reset(); init_p()
v1 = manifest.path().parent
(v1 / ".install-manifest.json.abc123.tmp").write_text("{")
(v1 / ".other.tmp").write_text("keep")
rc, out = cli_uni()
check("stale .install-manifest.json.*.tmp is removed by the next uninstall (an unrelated .tmp stays); the rerun tree equals an uninterrupted uninstall", rc == 0 and not (v1 / ".install-manifest.json.abc123.tmp").exists() and (v1 / ".other.tmp").exists() and F.diff(noise(REF), noise({k: v for k, v in F.snapshot(*ALL).items() if not k.endswith(".other.tmp")})) == [], (rc, out[-200:]))

# real pty: SIGINT at a sweep of delays 0.03 .. 0.12 s after the start of `shipm uninstall --apply`
def pty_sigint(delay):
    env = dict(os.environ); env.pop("CLAUDECODE", None); env["SHIPMIRACLE_FAKE_OS"] = "macos"
    m, sl = pty.openpty()
    p = subprocess.Popen([sys.executable, str(F.ROOT / "bin" / "shipm"), "uninstall", "--apply"], stdin=sl, stdout=sl, stderr=sl, env=env, close_fds=True)
    os.close(sl)
    out = b""
    t0 = time.time()
    while b"APPLY" not in out and time.time() - t0 < 30:        # the program is running (imports done): the delay counts from its first line
        if select.select([m], [], [], 1.0)[0]:
            out += os.read(m, 4096)
    time.sleep(delay - 0.03)
    if p.poll() is None:
        p.send_signal(signal.SIGINT)
    try:
        while True:
            r, _, _ = select.select([m], [], [], 2.0)
            if not r:
                break
            x = os.read(m, 4096)
            if not x:
                break
            out += x
    except OSError:
        pass
    try:
        rc = p.wait(timeout=15)
    except subprocess.TimeoutExpired:
        p.kill(); rc = p.wait()
    os.close(m)
    return rc, out.decode("utf-8", "replace").replace("\r", "")


bad, outcomes = [], set()
for i in range(19):
    delay = 0.03 + 0.005 * i
    F.reset(); init_p()
    inited = F.snapshot(*ALL)
    rc, out = pty_sigint(delay)
    outcomes.add(rc)
    honest = ("Traceback" not in out) and ((rc == 0) or (rc == 130 and ((STOPPED in out) or ("Nothing was deleted. Run shipm uninstall --apply again." in out and F.diff(noise(inited), noise(F.snapshot(*ALL))) == []))))
    rc2, out2 = cli_uni()
    if not (honest and rc2 == 0 and F.diff(noise(REF), noise(F.snapshot(*ALL))) == [] and not manifest.load()["steps"]):
        bad.append((delay, rc, out[-200:], rc2, out2[-200:]))
check("real pty SIGINT sweep 0-0.09 s after the first output line: no traceback, honest sentence, rerun exits 0, tree equals the uninterrupted result, manifest empty (exit codes seen: %s)" % sorted(outcomes), not bad, bad[:2])

# =============================================================== 9. nothing real was touched
check("real ~/.claude/settings.json, ~/.claude/agents, LaunchAgents, ~/.local/bin/shipm, ~/.config/shipmiracle and the install state are unchanged", F.real_unchanged(), F._real_fp())

# =============================================================== 8c. G10: a machine that recorded a removed optional row (init.json skip + a manifest step for row 21 of the old numbering) keeps working
F.reset(); init()
OLDID = "co" + "dex"                            # the removed row's id, built so this file does not carry the word
ip = run.init_path(); d0 = run.load_init(); d0.setdefault("skipped", {})[OLDID] = 1700000000; d0["skipped"]["backup"] = 1700000001
run.save_init(d0)
old_dir = F.HOME / "old-optional-row.txt"; old_dir.write_text("x\n")
sid = manifest.begin(21, "file_write", str(old_dir))
forge(lambda m: [st.update(pending=False, after_sha256=manifest.sha_file(old_dir)) for st in m["steps"] if st["id"] == sid])
rc, out, err = F.cli("init", "--check", "--json")
res = json.loads(out)
check("G10 init --check ignores a recorded skip of the removed row: exit 0, 22 rows, no such row, valid JSON", rc == 0 and len(res["rows"]) == 22 and OLDID not in [r["id"] for r in res["rows"]] and "Traceback" not in err, (rc, err[-300:]))
ctx = run.Ctx(say=lambda s: None); ctx.save_init()  # load_init() ran in Ctx()
d1 = json.loads(ip.read_text())
check("G10 the next init.json save drops the removed row's skip and keeps the others", OLDID not in d1["skipped"] and "backup" in d1["skipped"], d1)
rc, out, err = F.cli("init", "--undo", OLDID)
check("G10 init --undo of the removed row id is a plain usage error (exit 2), no traceback", rc == 2 and "unknown row" in err + out and "Traceback" not in err, (rc, out[-200:], err[-300:]))
rc, out = uni(apply=False)
check("G10 uninstall dry run lists the stale row-21 step and does not crash", "row 21" in out and "Traceback" not in out, out[-500:])
rc, out = uni(apply=True)
check("G10 uninstall --apply handles the stale step by its action (reversed or skipped with a line), exit 0 or 1, run completes", rc in (0, 1) and "step %d " % sid in out, (rc, out[-500:]))

shutil.rmtree(F.TMP, ignore_errors=True)
print("\n%d checks" % n_checks)
print("\nFAILED: %d" % fails if fails else "\nALL PASS")
sys.exit(1 if fails else 0)
