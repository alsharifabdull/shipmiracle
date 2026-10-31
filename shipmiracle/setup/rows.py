"""The checklist as data: one dict per row (n, id, title, need, connect, fix, undo, writes) plus a probe (read-only, returns (state, detail)) and an
optional apply (does the Fix; every write goes through manifest.recorded). `ready` = rows 0-5 and 7 green. Nothing here asks for or stores a secret;
external tools are only called through shipmiracle.setup.call (the SHIPMIRACLE_SETUP_BIN seam). Row 9 covers both launchd jobs (guard and daily).
Each row is also one entry of the connected-apps registry (plan 2026-10-21): `stage` (connect | prefs | advanced), `class` (required | recommended | optional |
advisory | never), `order` (connect order), `osx` (per-OS connect text; a dict there may also carry fix, undo and writes, see field()), `unsupported` (kinds where the row is "not on this system"), `docs` (one link)."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from .. import ShipmiracleError, UsageError, agents, ask, config, folder_check, paths, platform as aplat, projects, registry, settings_sync, state, timer
from . import call, manifest, _env, tool

READY_ROWS = (0, 1, 2, 3, 4, 5, 7)
SHIPMIRACLE_EXT = "shipmiracle.shipmiracle-panel"
CLAUDE_EXT = "anthropic.claude-code"
LAUNCHD = (("guard", "com.shipmiracle.guard"), ("daily", "com.shipmiracle.daily"))


def _cfg(key):
    """Stored config value (None when unset or unreadable)."""
    try:
        return config.get(key, None)
    except ShipmiracleError:
        return None


def engine_dir_value(ctx):
    if "engine.dir" in config.SCHEMA:
        return _cfg("engine.dir")
    return ctx.init_state.get("engine_dir")          # config key not defined yet (P8 T1): kept in <state>/v1/init.json


def _set_cfg(ctx, row, key, value):
    """Set a config key as a recorded step; returns False when the value is already in place."""
    if config.get(key, None) == value:
        return False
    before = config.get(key, None)
    with manifest.recorded(row, "config_set", key, before=before, before_sha256=manifest.sha_json(before)):
        config.set(key, value)
    return True


def _tilde(p) -> str:
    h = str(paths.home())
    s = str(p)
    return "~" + s[len(h):] if s.startswith(h + "/") else s


def _bin_link() -> Path:
    return paths.home() / ".local" / "bin" / "shipm"


def _launch_dir() -> Path:
    return paths.home() / "Library" / "LaunchAgents"


def _plist(label) -> Path:
    return _launch_dir() / (label + ".plist")


# ------------------------------------------------------------------ probes
HOOK_SELFTEST_S = 2
HOOK_OK = "shipm-hook selftest ok"


def _registered_hook_argv():
    """argv of the dispatcher command registered for UserPromptSubmit in the user-level settings, cut right after the `shipm-hook` path; None when there is none."""
    import shlex
    try:
        d = json.loads(state.read_bytes_nofollow(settings_sync.settings_path()).decode("utf-8"))
    except (OSError, ValueError, ShipmiracleError):
        return None
    ents = ((d.get("hooks") or {}).get("UserPromptSubmit") or []) if isinstance(d, dict) and isinstance(d.get("hooks"), dict) else []
    for e in ents:
        for h in (e.get("hooks") or []) if isinstance(e, dict) else []:
            c = h.get("command") if isinstance(h, dict) else None
            if isinstance(c, str) and "shipm-hook" in c:
                try:
                    argv = shlex.split(c)
                except ValueError:
                    return None
                idx = [i for i, a in enumerate(argv) if os.path.basename(a) == "shipm-hook"]
                return argv[:idx[-1] + 1] if idx else None
    return None


def hook_selftest(ctx):
    """(ok, detail): the REGISTERED hook command, started with the event SelfTest and --selftest, answers within 2 s with exit 0. It runs the same
    wrapper, python and dispatcher Claude Code will run, so a registration that exists but cannot start is caught here. Only the engine's own hooks/shipm-hook is run."""
    import subprocess
    argv = _registered_hook_argv()
    if argv is None:
        return False, "no shipm-hook command is registered in ~/.claude/settings.json"
    # the registered command is run by a shell, which expands $HOME / ~ in the words after the -c script; do the same here
    argv = [os.path.expanduser(os.path.expandvars(a)) if a.startswith(("$HOME", "${HOME}", "~")) else a for a in argv]
    want = os.path.realpath(str(ctx.engine / "hooks" / "shipm-hook"))
    if os.path.realpath(argv[-1]) != want:
        return False, "the registered hook runs a different checkout (%s)" % _tilde(argv[-1])
    try:
        r = subprocess.run(argv + ["SelfTest", "--selftest"], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=HOOK_SELFTEST_S)
    except subprocess.TimeoutExpired:
        return False, "the registered hook did not answer within %d s" % HOOK_SELFTEST_S
    except OSError as e:
        return False, "the registered hook cannot start (%s)" % type(e).__name__
    if r.returncode != 0 or HOOK_OK not in r.stdout.decode("utf-8", "replace"):
        return False, "the registered hook started but did not answer correctly (exit %d)" % r.returncode
    return True, ""


def probe_engine(ctx):
    eng = os.path.realpath(str(ctx.engine))
    miss = []
    cur = engine_dir_value(ctx)
    if cur is None:
        miss.append("engine.dir not set")
    elif os.path.realpath(str(cur)) != eng:
        return "red", "engine.dir points to another checkout (%s); run `shipm init` from that checkout, or unset it" % cur
    if _cfg("hooks.dispatcher") != "v1":
        miss.append("hooks.dispatcher is %s, not v1" % (_cfg("hooks.dispatcher") or "legacy"))
    try:
        if settings_sync.apply(mode="v1", dry_run=True)["changed"]:
            miss.append("hooks not registered in ~/.claude/settings.json")
    except ShipmiracleError as e:
        return "red", "settings.json problem: %s" % e
    try:
        pl = agents.install(dry_run=True)
        if agents.manifest() is None or any(a["action"] in ("install", "update", "remove") for a in pl["actions"]):
            miss.append("the agent team is not (fully) installed in ~/.claude/agents")
    except ShipmiracleError as e:
        miss.append("agent team cannot be checked (%s)" % e)
    link = _bin_link()
    if not os.path.lexists(str(link)):
        miss.append("~/.local/bin/shipm missing")
    elif os.path.realpath(str(link)) != os.path.realpath(str(ctx.engine / "bin" / "shipm")):
        return "red", "~/.local/bin/shipm exists and points elsewhere: not replaced (remove it yourself, then Fix)"
    if miss:
        return "red", "; ".join(miss)
    ok, why = hook_selftest(ctx)
    if not ok:
        return "red", "hooks are registered but do not work: %s. Next step: shipm init (it re-registers them), then check python3 and the engine folder" % why
    note = "" if str(_bin_link().parent) in os.environ.get("PATH", "").split(os.pathsep) else " (note: ~/.local/bin is not on your PATH)"
    return "green", "engine %s registered, hooks answer%s" % (_tilde(eng), note)


def probe_base(ctx):
    miss = []
    mac = aplat.kind() == "macos"
    if mac:
        rc, out, _ = call("xcode-select", ["-p"])
        if rc != 0:
            miss.append("Xcode command line tools missing")
    if call("git", ["--version"])[0] != 0:
        miss.append("git missing")
    if sys.version_info < (3, 9):
        miss.append("python3 older than 3.9")
    return ("red", "; ".join(miss)) if miss else ("green", ("command line tools, git and python3 %d.%d found" if mac else "git and python3 %d.%d found") % sys.version_info[:2])


def probe_node(ctx):
    rc, out, _ = call("node", ["-v"])
    if rc != 0:
        return "red", "node not found"
    m = re.match(r"v?(\d+)\.", out.strip())
    if not m or int(m.group(1)) < 18:
        return "red", "node %s is older than 18" % (out.strip()[:20] or "?")
    return "green", "node %s" % out.strip()[:20]


def probe_claude(ctx):
    rc, out, _ = call("claude", ["--version"])
    if rc != 0:
        return "red", "Claude Code not found"
    # NOT VERIFIED live: the non-interactive login check. `claude auth status` first; if that subcommand does not exist,
    # the presence of the oauthAccount key in ~/.claude.json (the key name only; no value is read or shown).
    rc2, _, _ = call("claude", ["auth", "status"])
    if rc2 == 0:
        return "green", "Claude Code %s, logged in" % out.strip()[:30]
    try:
        d = json.loads(state.read_bytes_nofollow(paths.home() / ".claude.json").decode("utf-8"))
        if isinstance(d, dict) and d.get("oauthAccount"):
            return "green", "Claude Code %s, login found" % out.strip()[:30]
    except (OSError, ValueError, ShipmiracleError):
        pass
    return "red", "Claude Code is installed but not logged in"


def _exts():
    rc, out, _ = call("code", ["--list-extensions"])
    return None if rc != 0 else [x.strip().lower() for x in out.splitlines() if x.strip()]


def probe_vscode(ctx):
    ex = _exts()
    if ex is None:
        return "red", "VS Code `code` command not found (in VS Code: Shell Command: Install 'code' command in PATH)"
    miss = [n for n, i in (("the Shipmiracle panel", SHIPMIRACLE_EXT), ("the Claude Code extension", CLAUDE_EXT)) if i not in ex]
    return ("red", "missing: " + ", ".join(miss)) if miss else ("green", "VS Code with the panel and Claude Code extension")


def _gitid():
    out = {}
    for k in ("user.name", "user.email"):
        rc, v, _ = call("git", ["config", "--global", k])
        out[k] = v.strip() if rc == 0 else ""
    return out


def probe_gitid(ctx):
    g = _gitid()
    miss = [k for k, v in g.items() if not v]
    return ("red", "git %s not set" % " and ".join(miss)) if miss else ("green", "git name and email set")


def probe_github(ctx):
    if tool("gh") is None:
        return "red", "gh not found (%s); without it projects stay local" % aplat.install_hint("gh")
    return ("green", "GitHub login found") if call("gh", ["auth", "status"])[0] == 0 else ("red", "not logged in to GitHub")


def probe_projects(ctx):
    try:
        config.get("paths.projects_dir", None)          # paths.py ignores an invalid saved value silently; the Check must not
    except ShipmiracleError as e:
        return "red", "Your saved projects folder cannot be used (%s). Fix it with: shipm init --prefs --folder ~/Developer" % str(e)[:160]
    d = paths.dev_dir()
    why = folder_check.problem(str(d))
    if why:
        return "red", why
    return ("green", "%s exists" % _tilde(d)) if d.is_dir() else ("red", "%s does not exist" % _tilde(d))


def _missing_ids():
    prop = registry.propose()
    have = registry.load()["projects"]
    return [i for i in sorted(prop["projects"]) if i not in have], prop


def probe_registry(ctx):
    if not paths.dev_dir().is_dir():
        return "red", "needs the projects folder first (row 7)"
    try:
        miss, prop = _missing_ids()
    except ShipmiracleError as e:
        return "red", "registry problem: %s" % e
    return ("red", "%d project(s) not in the registry" % len(miss)) if miss else ("green", "%d project(s) registered" % len(prop["projects"]))


def _loaded(label) -> bool:
    return call("launchctl", ["print", "gui/%d/%s" % (os.getuid(), label)])[0] == 0


def _timer_os() -> bool:
    return aplat.kind() in ("linux", "wsl")


def _unit_paths():
    return [timer.unit_path(s) for s in timer.SUFFIXES]


def probe_timer(ctx):
    svc = aplat.service()
    if svc.name != "systemd":
        return "red", "no systemd user manager here (WSL 2: turn on systemd in /etc/wsl.conf, then restart WSL); the daily job can still be run by hand: shipm daily"
    if not all(p.is_file() for p in _unit_paths()):
        return "red", "the daily timer is not installed"
    return ("green", "daily timer installed and enabled (systemd user timer)") if svc.is_loaded(timer.LABEL) else ("red", "the daily timer is written but not enabled")


def probe_guard(ctx):
    if _timer_os():
        return probe_timer(ctx)
    if not _plist(LAUNCHD[0][1]).is_file():
        return "red", "the awake guard is not installed"
    return ("green", "awake guard installed and loaded") if _loaded(LAUNCHD[0][1]) else ("red", "the guard job is written but not loaded")


def probe_notify(ctx):
    what = "macOS itself" if aplat.kind() == "macos" else "notify-send"
    if probe_github(ctx)[0] != "green":
        return "red", "the CI chip needs the GitHub login (row 6); notifications use %s" % what
    return "green", "CI chip available; notifications use %s" % what


def apply_notify(ctx):
    """`shipm init --step notify`: send one test notification. Not part of a plain init (a pop-up is never a surprise)."""
    if not getattr(ctx, "explicit", False):
        return "run `shipm init --step notify` to send a test notification"
    if aplat.kind() == "wsl":
        return "no system pop-ups on WSL 2: the VS Code panel is the notification"
    if aplat.notify_argv("Shipmiracle", "x") is None:
        return "no notification program found here (%s); the VS Code panel still works" % ("notify-send" if aplat.kind() == "linux" else "osascript")
    ok = aplat.notify("Shipmiracle", "Test notification from shipmiracle init", force=True)
    return "test notification sent" if ok else "the notification program ran but reported an error"


def _tool_row(name, args, ok, bad):
    def probe(ctx):
        return ("green", ok) if call(name, args)[0] == 0 else ("red", bad)
    return probe


def _docker_probe(ctx):
    mac = aplat.kind() == "macos"
    args = ["--context", "colima", "ps"] if mac else ["ps"]
    return ("green", "Docker (Colima) answers" if mac else "Docker answers") if call("docker", args)[0] == 0 else ("red", "Docker (Colima) is not running or not installed" if mac else "Docker is not running or not installed")


def probe_advisory(text):
    return lambda ctx: ("advisory", text)


def probe_backup(ctx):
    if aplat.kind() != "macos":
        return "advisory", "no backup check on this system; GitHub is the only offsite copy"
    rc, out, _ = call("tmutil", ["latestbackup"])
    if rc == 0 and out.strip():
        return "advisory", "a Time Machine backup exists; GitHub is the only offsite copy"
    return "advisory", "no Time Machine backup found; GitHub is the only offsite copy"


def probe_remote(ctx):
    """Optional row: green when remoteControlAtStartup is true in the USER-level settings, skipped when off (never red). Read-only."""
    st = settings_sync.remote_control_state()
    if st == "on":
        return "green", "on: your Claude Code sessions can be reached from the Claude phone app (set in ~/.claude/settings.json)"
    if st == "unknown":
        return "skipped", "off, or ~/.claude/settings.json could not be read (optional; nothing is changed)"
    return "skipped", "off (default); opt in with: shipm init --step remote-control"


def apply_remote(ctx):
    sp = settings_sync.settings_path()
    if settings_sync.remote_control_state(sp) == "on":
        return "already on"
    ctx.say("               Remote Control lets you reach your OWN Claude Code sessions from the Claude phone app or claude.ai/code.")
    ctx.say("               It needs a claude.ai Pro, Max, Team or Enterprise plan. It is a user-level setting (%s): Claude Code ignores true in project or local settings." % _tilde(sp))
    ctx.say("               Shipmiracle sets only the key %s to true; no other key is touched, and a backup is kept. Undo: shipm init --undo remote-control." % settings_sync.RC_KEY)
    if not ctx.confirm_word("Turn Remote Control on at startup?", "yes"):
        return "not confirmed: nothing changed (re-run with --yes, or type yes when asked)"
    plan = settings_sync.set_remote_control(True, dry_run=True)
    manifest.ensure_dirs(14, sp.parent)
    bak = manifest.backup_file(sp, "settings.json")
    before = plan["before"]
    with manifest.recorded(14, "settings_key", sp, before=before, before_sha256=None if before is None else manifest.sha_json(before), backup=bak,
                           key_name=settings_sync.RC_KEY, file_before_sha256=plan["file_before_sha256"], mode=(os.lstat(str(sp)).st_mode & 0o777) if bak else None) as sid:
        res = settings_sync.set_remote_control(True)
        manifest.annotate(sid, file_after_sha256=res["file_after_sha256"])
    return "turned on (%s = true in %s); backup kept" % (settings_sync.RC_KEY, _tilde(sp))


def probe_ask(ctx):
    try:
        ask.locate()
    except ShipmiracleError:
        return "skipped", "not set up (optional): a notes project for random questions; shipm init --step ask-inbox"
    return "green", "ask inbox project ready at %s" % _tilde(ask.project_path())


def probe_describe(ctx):
    """Row 19 (F6): never red, not counted in ready. green = some project's interview was applied; a draft waiting is said; otherwise the optional text."""
    st = set()
    try:
        from ..playbook import interview
        for pr in projects.list_projects():
            d = interview.load(pr.real)
            if d:
                st.add(d["status"])
    except Exception:
        st = set()
    if "draft" in st:
        return "skipped", "a draft playbook is ready to read (shipm playbook set --from-draft after you read it)"
    if "done" in st:
        return "green", "playbook set from your answers"
    return "skipped", "optional: answer a few questions and get a draft playbook; shipm playbook interview --short --project NAME"


def apply_ask(ctx):
    try:
        if ask.locate() is not None:
            return "already in place"
    except ShipmiracleError:
        pass
    dev = paths.dev_dir()
    if not dev.is_dir():
        return "needs the projects folder first (row 7)"
    folder = ask.project_path()
    pid = projects.project_id(folder)
    adopt = False
    if ask.folder_needs_adopt():
        if not ctx.confirm_adopt("%s already exists, is not empty and is not a registered project." % _tilde(folder)):
            return "refused: %s already exists and is not empty (re-run with --adopt if it is yours)" % _tilde(folder)
        adopt = True
    elif not ctx.confirm("Create the ask inbox project %s (a notes project for random questions)?" % _tilde(folder)):
        return "not confirmed (re-run with --yes)"
    created = not os.path.lexists(str(folder))
    with manifest.recorded(18, "ask_project", pid, before=created, before_sha256=None, folder=str(folder)):
        res = ask.create_project(say=ctx.say, adopt=adopt)
    return "%s %s and registered it" % ("created" if res["created"] else "found", _tilde(res["folder"]))


def _mcp_names():
    """Names of the MCP servers in Claude's own settings (names only; no command, URL or key is read out). None when nothing could be read."""
    names = set()
    for p in (paths.home() / ".claude.json", settings_sync.settings_path()):
        try:
            d = json.loads(state.read_bytes_nofollow(p).decode("utf-8"))
        except (OSError, ValueError, ShipmiracleError):
            continue
        m = d.get("mcpServers") if isinstance(d, dict) else None
        if isinstance(m, dict):
            names.update(k for k in m if isinstance(k, str) and re.fullmatch(r"[\w.@-]{1,40}", k))
    return sorted(names)


def probe_connectors(ctx):
    n = _mcp_names()
    base = "set in Claude's own settings; Shipmiracle only reports"
    return "advisory", base + (("; MCP servers: " + ", ".join(n[:10]) + ("..." if len(n) > 10 else "")) if n else "; no MCP servers found")


PREF_KEYS = ("prefs.lang", "paths.projects_dir", "prefs.autonomy", "prefs.keep_awake", "prefs.notify")


def probe_prefs(ctx):
    """Row 20: green once the quick-setup answers are stored (or the owner confirmed them); until then the defaults are used and nothing is red."""
    if ctx.init_state.get("prefs_done") or all(_cfg(k) is not None for k in PREF_KEYS if not (k == "prefs.keep_awake" and aplat.kind() in ("wsl", "windows"))):
        return "green", "your choices are saved (shipm init --prefs to change them)"
    return "skipped", "not answered yet: defaults are used (shipm init --prefs asks 5 short questions)"


def apply_prefs(ctx):
    from . import onboard
    return onboard.run_prefs(ctx, interactive=ctx.interactive())


def probe_gitleaks(ctx):
    if call("gitleaks", ["version"])[0] == 0:
        return "green", "gitleaks found (release export and autopilot deliver scan secrets with it)"
    return "red", "gitleaks not found (%s); the release check then skips its secret scan" % aplat.install_hint("gitleaks")


def probe_never(ctx):
    return "never", "not set up here on purpose: publishing always asks you"


# ------------------------------------------------------------------ applies (each returns a one-line result)
def apply_engine(ctx):
    eng = ctx.engine
    done = []
    if "engine.dir" in config.SCHEMA:
        if _set_cfg(ctx, 0, "engine.dir", str(eng)):
            done.append("engine.dir")
    elif ctx.init_state.get("engine_dir") != str(eng):
        ctx.init_state["engine_dir"] = str(eng); ctx.save_init(); done.append("engine.dir (kept in init.json)")
    if _set_cfg(ctx, 0, "hooks.dispatcher", "v1"):
        done.append("hooks.dispatcher=v1")
    sp = settings_sync.settings_path()
    if settings_sync.apply(mode="v1", dry_run=True)["changed"]:
        manifest.ensure_dirs(0, sp.parent)
        before = manifest.sha_file(sp)
        bak = manifest.backup_file(sp, "settings.json")
        mode = (os.lstat(str(sp)).st_mode & 0o777) if before else None
        with manifest.recorded(0, "settings_sync", sp, before=before, before_sha256=before, backup=bak, mode=mode):
            settings_sync.apply(mode="v1")
        done.append("hooks registered")
    ud = agents.user_dir()
    pl = agents.install(dry_run=True)
    if agents.manifest() is None or any(a["action"] in ("install", "update", "remove") for a in pl["actions"]):
        pre = agents.manifest() is not None
        manifest.ensure_dirs(0, ud)
        with manifest.recorded(0, "agents_install", "agents", before=pre, before_sha256=manifest.current_sha({"action": "agents_install"}), preexisting=pre):
            agents.install(ws=eng)
        done.append("team installed")
    link = _bin_link()
    if not os.path.lexists(str(link)):
        manifest.ensure_dirs(0, link.parent)
        with manifest.recorded(0, "symlink", link, before=None, before_sha256=None):
            os.symlink(str(eng / "bin" / "shipm"), str(link))
        done.append("~/.local/bin/shipm")
    return ("set up: " + ", ".join(done)) if done else "already in place"


def apply_vscode(ctx):
    ex = _exts()
    if ex is None:
        return "VS Code `code` command not found: nothing done"
    done = []
    if SHIPMIRACLE_EXT not in ex:
        if not ctx.confirm("Install the Shipmiracle panel into VS Code?"):
            return "not confirmed (re-run with --yes)"
        script = ctx.engine / "bin" / "install-shipm-ext"
        with manifest.recorded(4, "vscode_ext", SHIPMIRACLE_EXT, before=False, before_sha256=None):
            r = subprocess.run([sys.executable, str(script)], env=_env(), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300)
            if r.returncode != 0:
                raise UsageError("installing the panel failed (exit %d); run %s yourself to see why" % (r.returncode, _tilde(script)))
        done.append("panel")
    if CLAUDE_EXT not in ex:
        if not ctx.confirm("Install the Claude Code extension into VS Code?"):
            return ("panel installed; " if done else "") + "Claude Code extension not confirmed (re-run with --yes)"
        with manifest.recorded(4, "vscode_ext", CLAUDE_EXT, before=False, before_sha256=None):
            rc, _, err = call("code", ["--install-extension", CLAUDE_EXT], timeout=300)
            if rc != 0:
                raise UsageError("`code --install-extension %s` failed (exit %d)" % (CLAUDE_EXT, rc))
        done.append("Claude Code extension")
    return "installed: " + ", ".join(done) if done else "already in place"


def apply_github(ctx):
    if tool("gh") is None:
        return "gh not found: install it first (brew install gh); Shipmiracle never runs brew"
    if not ctx.confirm("Open the GitHub sign-in in your browser now?"):
        return "not confirmed (re-run with --yes)"
    rc, _, _ = call("gh", ["auth", "login", "--web", "-s", "repo"], interactive=True)
    return "GitHub sign-in finished" if rc == 0 else "GitHub sign-in did not finish (exit %d). Try again" % rc


def apply_projects(ctx):
    d = paths.dev_dir()
    why = folder_check.problem(str(d))
    if why:
        return "refused: " + why
    if d.is_dir():
        return "already in place"
    if not ctx.confirm("Create the projects folder %s?" % _tilde(d)):
        return "not confirmed (re-run with --yes)"
    manifest.ensure_dirs(7, d)
    return "created %s" % _tilde(d)


def apply_registry(ctx):
    if not paths.dev_dir().is_dir():
        return "needs the projects folder first (row 7)"
    miss, prop = _missing_ids()
    if not miss:
        return "already in place"
    sids = {i: manifest.begin(8, "registry_add", i, before=None, before_sha256=None) for i in miss}
    if manifest.FAULT:
        manifest.FAULT("begin:registry_add:*")
    added = registry.write_missing({"v": 1, "projects": {i: prop["projects"][i] for i in miss}})
    if manifest.FAULT:
        manifest.FAULT("done:registry_add:*")
    cur = {s["id"]: s for s in manifest.load()["steps"]}
    for i, sid in sids.items():
        manifest.commit(sid, manifest.current_sha(cur[sid]))
    return "registered %d project(s)" % len(added)


def render_plist(label, engine) -> bytes:
    tpl = Path(engine) / "templates" / "launchd" / (label + ".plist.in")
    try:
        txt = tpl.read_text(encoding="utf-8")
    except OSError:
        raise UsageError("launchd template %s not found in the engine" % tpl.name)
    return txt.replace("@WS@", str(engine)).replace("@STATE@", str(paths.state_dir())).encode("utf-8")


def apply_timer(ctx):
    """Linux / WSL 2: the daily job as a systemd USER timer (no root, your account only). The awake guard is macOS only. Every file and the enable are recorded in the
    install manifest, so `shipm uninstall` removes exactly what was written here (a unit file that was changed since is left alone)."""
    svc = aplat.service()
    if svc.name != "systemd":
        return "no systemd user manager here: nothing done (WSL 2: turn on systemd in /etc/wsl.conf). Run `shipm daily` by hand or from the panel."
    if not ctx.confirm("Install the daily job (a systemd user timer, your account only, no root)?"):
        return "not confirmed (re-run with --yes)"
    try:
        wanted = [(p, timer.render(p.name, ctx.engine)) for p in _unit_paths()]
    except (ValueError, OSError) as e:
        raise UsageError("the daily timer units cannot be rendered: %s" % e)
    done = []
    for p, data in wanted:
        if manifest.sha_file(p) == manifest.sha_bytes(data):
            continue
        if p.exists() or p.is_symlink():
            return "%s exists and differs from the template: not replaced" % _tilde(p)
        manifest.ensure_dirs(9, p.parent)
        state.ensure_dir(state.ensure_root() / "logs")           # systemd opens the log file before bin/daily runs
        with manifest.recorded(9, "file_write", p, before=None, before_sha256=None):
            timer.write_unit(p, data)
        done.append(p.name + " written")
    call("systemctl", ["--user", "daemon-reload"])
    tpath = timer.unit_path(".timer")
    if not svc.is_loaded(timer.LABEL):
        with manifest.recorded(9, "systemd", tpath, before=False, before_sha256=None, label=timer.LABEL):
            rc, err = svc.load(timer.LABEL, tpath)
            if rc != 0:
                raise UsageError("systemctl --user enable --now %s.timer failed (exit %d)" % (timer.LABEL, rc))
        done.append(timer.LABEL + ".timer enabled")
    return ("; ".join(done)) if done else "already in place"


def apply_guard(ctx):
    if _timer_os():
        return apply_timer(ctx)
    if tool("launchctl") is None:
        return "launchctl not found: nothing done"
    if not ctx.confirm("Install the awake guard and the daily job (launchd, your account only)?"):
        return "not confirmed (re-run with --yes)"
    done = []
    for short, label in LAUNCHD:
        plist = _plist(label)
        data = render_plist(label, ctx.engine)
        if manifest.sha_file(plist) != manifest.sha_bytes(data):
            if plist.exists():
                if _loaded(label):
                    return "%s differs from the template and is loaded: remove it yourself first (Shipmiracle never overwrites a changed job)" % _tilde(plist)
                return "%s exists and differs from the template: not replaced" % _tilde(plist)
            manifest.ensure_dirs(9, plist.parent)
            state.ensure_dir(state.ensure_root() / "logs")
            state.ensure_dir(paths.state_dir() / "logs")
            with manifest.recorded(9, "file_write", plist, before=None, before_sha256=None):
                state.atomic_write(plist, data, 0o644)
            done.append(label + " written")
        if not _loaded(label):
            with manifest.recorded(9, "launchd", plist, before=False, before_sha256=None, label=label):
                rc, _, err = call("launchctl", ["bootstrap", "gui/%d" % os.getuid(), str(plist)])
                if rc != 0:
                    raise UsageError("launchctl bootstrap %s failed (exit %d)" % (label, rc))
            done.append(label + " loaded")
    ctx.say("  lid-closed keep-awake (optional, only you can run it):  sudo %s --print   shows the line; run  sudo %s  once to allow it"
            % (_tilde(ctx.engine / "bin" / "shipm-guard-admin"), _tilde(ctx.engine / "bin" / "shipm-guard-admin")))
    return ("; ".join(done)) if done else "already in place"


def _hint(kind, text):
    return {"kind": kind, "text": text}


def _row(n, rid, title, need, connect, fix, undo, writes, probe, apply=None, stage="advanced", cls=None, order=99, osx=None, unsupported=(), docs=""):
    return {"n": n, "id": rid, "title": title, "need": need, "connect": connect, "fix": fix, "undo": undo, "writes": writes, "probe": probe, "apply": apply,
            "stage": stage, "class": cls or need, "order": order, "osx": dict(osx or {}), "unsupported": tuple(unsupported), "docs": docs}


def supported(r, kind=None) -> bool:
    return (kind or aplat.kind()) not in r["unsupported"]


def connect_text(r, kind=None) -> str:
    """The connect text for this OS: the per-OS override (WSL falls back to the Linux text), else the generic one."""
    k = kind or aplat.kind()
    o = r["osx"]
    ov = o.get(k) or (o.get("linux") if k == "wsl" else None)
    if isinstance(ov, dict):
        ov = ov.get("connect")
    return ov or r["connect"]["text"]


def field(r, name, kind=None):
    """`fix`, `undo` or `writes` for this OS: the per-OS override (a dict in `osx`; WSL falls back to the Linux one), else the generic text, which is the macOS text."""
    k = kind or aplat.kind()
    o = r["osx"]
    ov = o.get(k) or (o.get("linux") if k == "wsl" else None)
    if isinstance(ov, dict) and name in ov:
        return ov[name]
    return r[name]


ROWS = [
    _row(0, "engine", "Engine", "required", _hint("write", "Register this checkout: config, hooks, agent team, Shipmiracle command."),
         "Sets engine.dir and hooks.dispatcher=v1, runs `shipm sync --hooks v1`, installs the agent team, links ~/.local/bin/shipm.",
         "Restores the config keys, `shipm sync --hooks off`, removes the team files it installed, removes the link if it still points here.",
         ["~/.config/shipmiracle/config.json", "~/.claude/settings.json", "~/.claude/agents", "~/.local/bin/shipm"], probe_engine, apply_engine),
    _row(1, "base", "Base tools", "required", _hint("hint", "Run: xcode-select --install   (a macOS window opens; python3 3.9+ comes with it)"),
         "Shows the command; Shipmiracle does not run it.", "Nothing to undo.", [], probe_base),
    _row(2, "node", "Node", "required", _hint("hint", "Install Node 18 or newer (for example: brew install node). Shipmiracle never runs brew."),
         "Shows the hint; Shipmiracle does not install it.", "Nothing to undo.", [], probe_node),
    _row(3, "claude", "Claude Code login", "required", _hint("browser", "Run `claude` in a terminal and sign in with your Claude account (opens your browser)."),
         "Shows the steps; the sign-in is yours.", "Nothing to undo; Shipmiracle never removes a login.", [], probe_claude),
    _row(4, "vscode", "VS Code + panel", "required", _hint("write", "Installs the Shipmiracle panel and the Claude Code extension with `code --install-extension`."),
         "Runs bin/install-shipm-ext and `code --install-extension anthropic.claude-code` (asks first).",
         "Uninstalls only the extensions this init installed.", ["~/.vscode/extensions"], probe_vscode, apply_vscode),
    _row(5, "git-id", "Git name and email", "required", _hint("prompt", 'git config --global user.name "Your Name"   and   git config --global user.email "you@example.com"'),
         "Shows the two commands; Shipmiracle never writes ~/.gitconfig.", "Nothing to undo.", [], probe_gitid),
    _row(6, "github", "GitHub login", "recommended", _hint("browser", "gh auth login --web -s repo   (opens your browser; Shipmiracle never sees the token)"),
         "Runs the GitHub sign-in (asks first).", "Nothing to undo; Shipmiracle never removes a login.", [], probe_github, apply_github),
    _row(7, "projects", "Projects folder", "required", _hint("prompt", "Confirm the folder for your projects (default ~/Developer)."),
         "Creates the folder if it is missing (asks first).", "Removes the folder only if init created it and it is still empty.", ["~/Developer"], probe_projects, apply_projects),
    _row(8, "registry", "Project registry", "required", _hint("write", "Adds your existing projects to the registry from their git remotes."),
         "Adds the missing projects to ~/.config/shipmiracle/registry.json.", "Forgets the ids init added (if unchanged).", ["~/.config/shipmiracle/registry.json"], probe_registry, apply_registry),
    _row(9, "guard", "Awake guard", "optional", _hint("write", "Installs two launchd jobs for your account: the awake guard and the daily report."),
         "Renders templates/launchd/*.in, writes ~/Library/LaunchAgents/com.shipmiracle.*.plist, `launchctl bootstrap` (asks first). Prints the sudo line; never runs it.",
         "launchctl bootout, then deletes the plist if unchanged.", ["~/Library/LaunchAgents/com.shipmiracle.guard.plist", "~/Library/LaunchAgents/com.shipmiracle.daily.plist"], probe_guard, apply_guard,
         osx={k: {"connect": c, "fix": "Renders templates/systemd/*.in into ~/.config/systemd/user and runs `systemctl --user enable --now` for the daily timer (asks first; no root; no awake guard).",
                  "undo": "`systemctl --user disable --now`, then deletes the two unit files if unchanged.",
                  "writes": ["~/.config/systemd/user/com.shipmiracle.daily.service", "~/.config/systemd/user/com.shipmiracle.daily.timer"]}
              for k, c in (("linux", "Installs the daily report as a systemd user timer for your account (no root). The awake guard is macOS only."),
                           ("wsl", "Installs the daily report as a systemd user timer for your account (no root; needs systemd turned on in /etc/wsl.conf). The awake guard is macOS only."))}),
    _row(10, "notify", "Notifications and CI", "optional", _hint("hint", "The CI chip needs the GitHub login; notifications use macOS and need nothing."),
         "Nothing to write.", "Nothing to undo.", [], probe_notify),
    _row(11, "docker", "Docker", "optional", _hint("hint", "Only for container projects: install Colima and Docker (brew install colima docker)."),
         "Shows the hint.", "Nothing to undo.", [], _docker_probe),
    _row(12, "web-verify", "Web checks", "optional", _hint("hint", "Only for web projects: install agent-browser (see the stack pack)."),
         "Shows the hint.", "Nothing to undo.", [], _tool_row("agent-browser", ["--version"], "agent-browser found", "agent-browser not found")),
    _row(13, "connectors", "Claude connectors and MCP servers", "advisory", _hint("hint", "Gmail, Drive, Calendar, MCP servers and other connectors are added in Claude's own settings, never by Shipmiracle."),
         "Open Claude settings.", "Nothing to undo.", [], probe_connectors),
    _row(14, "remote-control", "Remote Control", "optional", _hint("hint", "Optional: reach your own Claude Code sessions from your phone. Off by default; opt in with `shipm init --step remote-control`."),
         "Explains it, asks you to type yes, then sets only remoteControlAtStartup=true in ~/.claude/settings.json (user-level; backup kept; needs a claude.ai Pro/Max/Team/Enterprise plan).",
         "`shipm init --undo remote-control` (or shipm uninstall) puts the key back to what it was (absent = removed). disableRemoteControl is never touched.",
         ["~/.claude/settings.json"], probe_remote, apply_remote),
    _row(15, "backup", "Backups", "advisory", _hint("hint", "Turn on Time Machine or another backup; GitHub is the only offsite copy."),
         "Shows the status.", "Nothing to undo.", [], probe_backup),
    _row(16, "ios", "iOS tools", "optional", _hint("hint", "Only for iOS projects: install Xcode from the App Store."),
         "Shows the hint.", "Nothing to undo.", [], _tool_row("xcodebuild", ["-version"], "Xcode found", "Xcode not found")),
    _row(17, "publishing", "Publishing", "never", _hint("hint", "Publishing tools are never preconfigured: publishing always asks you."),
         "Nothing to do.", "Nothing to undo.", [], probe_never),
    _row(18, "ask-inbox", "Ask inbox", "optional", _hint("write", "Optional: a notes project `ask` for random questions; `shipm ask --inbox \"question\"` writes the answers there."),
         "Creates ~/Developer/ask (git, docs/notes, notes playbook) and registers it (asks first). Only when you run `shipm init --step ask-inbox`.",
         "`shipm init --undo ask-inbox` (or shipm uninstall) forgets the registry entry; the folder is removed only if empty, never when it has notes.",
         ["~/Developer/ask", "~/.config/shipmiracle/registry.json"], probe_ask, apply_ask),
    _row(19, "describe-work", "Describe your work", "optional", _hint("hint", "Optional: answer a few questions and get a draft playbook. In a terminal: `shipm playbook interview --short --project NAME` (or --long)."),
         "Nothing to write here; the interview runs in your terminal and writes only a draft inside the project (.shipmiracle/playbook.draft.md).",
         "Nothing to undo; delete the draft files or run the interview with --restart.", [], probe_describe),
]
ROWS += [
    _row(20, "prefs", "Quick setup choices", "optional", _hint("prompt", "Five short choices: language, projects folder, how much the team does by itself, keep awake, notifications. Enter keeps the recommended answer."),
         "Asks the five questions (shipm init --prefs) and saves the answers in ~/.config/shipmiracle/config.json, user-level only.",
         "`shipm init --undo prefs` puts the previous values back (a key that was absent is removed).", ["~/.config/shipmiracle/config.json"], probe_prefs, apply_prefs),
    _row(21, "gitleaks", "gitleaks", "optional", _hint("hint", "Recommended for release export and autopilot deliver: install gitleaks (brew install gitleaks)."),
         "Shows the hint.", "Nothing to undo.", [], probe_gitleaks),
]
_LIN = ("linux", "wsl")
# registry metadata (plan section 4.3): connect order, class, per-OS connect text, rows that do not exist on an OS, one docs link
META = {
    "base": dict(stage="connect", order=1, docs="https://git-scm.com/downloads", osx={k: "Run: " + aplat._HINTS["base"][k] for k in _LIN}),
    "node": dict(stage="connect", order=2, docs="https://nodejs.org/en/download", osx={k: aplat._HINTS["node"][k] for k in _LIN}),
    "git-id": dict(stage="connect", order=3, docs="https://git-scm.com/book/en/v2/Getting-Started-First-Time-Git-Setup"),
    "claude": dict(stage="connect", order=4, docs="https://docs.claude.com/en/docs/claude-code/overview"),
    "projects": dict(stage="connect", order=5),
    "engine": dict(stage="connect", order=6),
    "registry": dict(stage="connect", order=7),
    "vscode": dict(stage="connect", order=8, docs="https://code.visualstudio.com/download", osx={"linux": "Install the Shipmiracle panel and the Claude Code extension with `code --install-extension` (needs the `code` command on your PATH).",
                                                                                          "wsl": aplat._HINTS["code"]["wsl"]}),
    "github": dict(stage="connect", cls="recommended", order=9, docs="https://cli.github.com"),
    "prefs": dict(stage="prefs", cls="required", order=0),
    "guard": dict(unsupported=("windows",)),                  # Linux / WSL 2: the row installs the daily systemd user timer only (the awake guard is macOS only)
    "notify": dict(osx={"linux": "The CI chip needs the GitHub login; notifications use notify-send when it is installed.", "wsl": "System pop-ups are not available on WSL 2: the VS Code panel is the notification."},
                   unsupported=("wsl", "windows")),
    "docker": dict(osx={k: "Only for container projects: " + aplat._HINTS["docker"][k] for k in _LIN}, docs="https://docs.docker.com/engine/install/"),
    "gitleaks": dict(cls="recommended", docs="https://github.com/gitleaks/gitleaks", osx={k: "Recommended for release export and autopilot deliver: " + aplat._HINTS["gitleaks"][k] for k in _LIN}),
    "backup": dict(unsupported=("linux", "wsl", "windows")),
    "ios": dict(unsupported=("linux", "wsl", "windows"), docs="https://developer.apple.com/xcode/"),
}
for _r in ROWS:
    _r.update(META.get(_r["id"], {}))
BY_ID = {r["id"]: r for r in ROWS}
CONNECT_ROWS = sorted((r for r in ROWS if r["class"] == "required" and r["stage"] == "connect"), key=lambda r: r["order"])
