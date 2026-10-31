"""`shipm uninstall`: reverse what `shipm init` wrote, newest step first, and only where the target still looks exactly as init left it (current sha ==
after_sha256); anything else is SKIPPED and reported, never forced. Dry run unless apply. `purge` (typed confirmation) also removes the config and
state folders, but only when every step was reversed. Never deleted: project repos and the projects folder's contents, any other tool's config folder, anything in ~/.claude
that is not Shipmiracle's, gh and claude logins, brew packages, the engine clone (its rm line is printed)."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from .. import ShipmiracleError, NotFound, SafetyError, UsageError, agents, config, paths, registry, settings_sync, state
from . import call, guard_home, manifest
from .run import Paused

PURGE_WORD = "PURGE"


def rows_timer_dir():
    from .. import timer
    return timer.unit_dir()


def _short(s) -> str:
    t = s.get("path") or s.get("key") or ""
    h = str(paths.home())
    t = "~" + t[len(h):] if t.startswith(h + "/") else t
    return "%s %s" % (s.get("action"), t)


def validate(s):
    """(True, '') or (False, why): the manifest is a file an attacker may have forged, so every field that picks a file to read, write or delete is checked
    before the step is judged (L8). settings steps must name the real settings file; backups must live in <state>/v1/install-backups/; plain paths must be
    inside the home, config, state or projects folder (never one of those folders itself); the ask folder must sit directly inside the projects folder."""
    a = s.get("action")
    if a in ("settings_key", "settings_sync"):
        p = s.get("path")
        if not isinstance(p, str) or os.path.normpath(p) != os.path.normpath(str(settings_sync.settings_path())):
            return False, "its path is not the settings file (%s)" % settings_sync.settings_path()
    elif a in ("file_write", "symlink", "mkdir", "launchd", "systemd", "config_set", "vscode_ext", "agents_install"):
        from . import rows
        norm = os.path.normpath
        plists = {norm(str(rows._plist(lab))): lab for _short, lab in rows.LAUNCHD}
        units = {norm(str(u)) for u in rows._unit_paths()}
        timer_unit = norm(str(rows.timer.unit_path(".timer")))
        p = s.get("path")
        key = s.get("key")
        if a == "symlink" and (not isinstance(p, str) or norm(p) != norm(str(rows._bin_link()))):
            return False, "its path is not the Shipmiracle link init makes (%s)" % rows._bin_link()
        if a == "file_write" and (not isinstance(p, str) or (norm(p) not in plists and norm(p) not in units)):
            return False, "its path is not one of the launchd job files or systemd unit files init writes"
        if a == "systemd" and (not isinstance(p, str) or norm(p) != timer_unit or s.get("label") != rows.timer.LABEL):
            return False, "its path or label is not the daily timer init enables"
        if a == "launchd" and (not isinstance(p, str) or plists.get(norm(p)) != s.get("label")):
            return False, "its path or label is not one of the launchd jobs init loads"
        if a == "mkdir":
            home = norm(os.path.realpath(str(paths.home())))
            ok_dirs = set()
            for t in (agents.user_dir(), rows._bin_link().parent, rows._launch_dir(), rows.timer.unit_dir(), paths.dev_dir()):
                cur = Path(os.path.realpath(str(t)))
                while str(cur) != home and cur != cur.parent:
                    ok_dirs.add(str(cur))
                    cur = cur.parent
            if not isinstance(p, str) or norm(os.path.join(os.path.realpath(os.path.dirname(p)), os.path.basename(p))) not in ok_dirs:
                return False, "its folder is not one init creates"
        if a == "config_set" and key not in ("engine.dir", "hooks.dispatcher"):
            return False, "its config key is not one init sets"
        if a == "vscode_ext" and key not in (rows.SHIPMIRACLE_EXT, rows.CLAUDE_EXT):
            return False, "its extension id is not one init installs"
        if a == "agents_install" and key != "agents":
            return False, "unexpected agents step"
    if a == "prefs":
        from . import rows
        ks, bf = s.get("keys"), s.get("before")
        if not isinstance(ks, list) or not isinstance(bf, dict) or any(k not in rows.PREF_KEYS for k in ks) or set(bf) != set(ks):
            return False, "its keys are not the quick-setup choices init sets"
    if a == "ask_project":
        f = s.get("folder")
        dev = os.path.realpath(str(paths.dev_dir()))
        if not isinstance(f, str) or os.path.dirname(os.path.realpath(f)) != dev or os.path.basename(f.rstrip("/")) != "ask":
            return False, "its folder is not the ask folder directly inside the projects folder"
    b = s.get("backup")
    if b is not None and (not isinstance(b, str) or not settings_sync.backup_in_manifest_dir(b)):
        return False, "its backup is not in <state>/v1/install-backups/"
    return True, ""


class Interrupted(Exception):
    """Ctrl-C after removal began (some steps may already be undone). `.purge` = the run was a --purge run."""
    def __init__(self, purge=False):
        super().__init__("interrupted during removal")
        self.purge = purge


def decide(s):
    """('reverse'|'gone'|'skip', reason) for one step."""
    if s.get("preexisting"):
        return "skip", "was already there before shipm init; left alone"
    try:
        cur = manifest.current_sha(s)
    except ShipmiracleError as e:
        return "skip", "cannot look at it (%s)" % e
    after = s.get("after_sha256")
    bsha = s.get("before_sha256")
    if not s.get("pending") and bsha is not None and cur == bsha and cur != after:      # an interrupted earlier uninstall already put it back, only the record is left
        return "gone", "already restored"
    if s.get("action") == "prefs" and not s.get("pending") and isinstance(s.get("after"), dict):
        now = {k: config.get(k, None) for k in s["keys"]}
        at_before = [k for k in s["keys"] if now[k] == s["before"].get(k)]
        if at_before and all(now[k] == s["before"].get(k) or now[k] == s["after"].get(k) for k in s["keys"]):
            return "reverse", ""                      # a restore that was cut off part way: finishing it is idempotent
    if s.get("pending"):
        return ("gone", "interrupted step, nothing was written") if cur == s.get("before_sha256") else ("skip", "interrupted step: run `shipm init` once to settle it")
    if cur is None and after is not None:
        return "gone", "already removed"
    if cur == after or (s.get("action") == "agents_install" and cur is not None):      # agents.uninstall removes only unchanged files itself
        return "reverse", ""
    if s.get("action") == "settings_sync":          # edited since init: still fine when no Shipmiracle entry is left in it (e.g. after `shipm sync --hooks off`)
        try:
            if not settings_sync.apply(path=s["path"], mode=settings_sync.OFF, dry_run=True)["changed"]:
                return "gone", "no Shipmiracle entry is left in it"
        except ShipmiracleError:
            pass
    return "skip", "changed since init; left as it is"


def _reverse(s):
    """Undo one step; returns (True, note) or (False, why it was skipped)."""
    a = s["action"]
    if a == "prefs":
        config.restore_many({k: s["before"].get(k) for k in s["keys"]})          # one atomic write: never a half-restored set
        return True, "restored the previous choices (%s)" % ", ".join(s["keys"])
    if a == "config_set":
        if s.get("before") is None:
            config.unset(s["key"])
        else:
            config.set(s["key"], s["before"])
        return True, "restored %s" % s["key"]
    if a == "settings_sync":
        if s.get("backup"):
            state.atomic_write(s["path"], state.read_bytes_nofollow(s["backup"]), s.get("mode") or 0o600)
            return True, "restored the file from the backup taken before init"
        os.unlink(s["path"])
        return True, "removed (it did not exist before init)"
    if a in ("file_write", "symlink"):
        os.unlink(s["path"])
        if a == "file_write" and os.path.dirname(os.path.normpath(s["path"])) == os.path.normpath(str(rows_timer_dir())):
            call("systemctl", ["--user", "daemon-reload"])        # the unit is gone: tell the user manager (best effort)
        return True, "removed"
    if a == "systemd":
        rc, _, _ = call("systemctl", ["--user", "disable", "--now", s["label"] + ".timer"])
        return (True, "disabled") if rc == 0 else (False, "systemctl --user disable failed (exit %d); run it yourself" % rc)
    if a == "launchd":
        rc, _, _ = call("launchctl", ["bootout", "gui/%d/%s" % (os.getuid(), s["label"])])
        return (True, "unloaded") if rc == 0 else (False, "launchctl bootout failed (exit %d); run it yourself" % rc)
    if a == "agents_install":
        try:
            res = agents.uninstall()
        except NotFound:
            return True, "nothing installed"
        kept = [x["name"] for x in res["actions"] if x["action"] == "keep"]
        return True, "team removed" + ("; kept (changed by hand): %s" % ", ".join(kept) if kept else "")
    if a == "mkdir":
        try:
            os.rmdir(s["path"])
        except OSError:
            return False, "folder is not empty; left"
        return True, "removed"
    if a == "vscode_ext":
        rc, _, _ = call("code", ["--uninstall-extension", s["key"]], timeout=120)
        return (True, "uninstalled") if rc == 0 else (False, "code --uninstall-extension failed (exit %d)" % rc)
    if a == "registry_add":
        registry.forget(s["key"])
        return True, "forgot"
    if a == "settings_key":
        note = settings_sync.undo_remote_control(s.get("before"), s["path"], s.get("backup"), s.get("file_before_sha256"), s.get("file_after_sha256"))
        return True, note
    if a == "ask_project":
        registry.forget(s["key"])
        try:
            os.rmdir(s["folder"])
            return True, "forgot the registry entry and removed the empty folder"
        except OSError:
            return True, "forgot the registry entry; the project folder has files and is kept"
    return False, "unknown step"


def _purge_ok(d) -> bool:
    if os.path.islink(str(d)):
        return False
    if paths.sandboxed():
        return True
    return os.path.realpath(str(d)) in (os.path.realpath(str(paths.home() / ".config" / "shipmiracle")), os.path.realpath(str(paths.home() / ".local" / "state" / "shipmiracle")))


def run(apply=False, purge=False, confirm=None, say=None) -> int:
    say = say or (lambda s: sys.stdout.write(s + "\n"))
    if purge and not apply:
        raise UsageError("--purge needs --apply")
    if apply:
        paths.require_owner("shipm uninstall")
        guard_home()
        if purge:
            typed = confirm
            if typed is None and sys.stdin is not None and sys.stdin.isatty():
                try:
                    typed = input("  Type %s to also delete your shipm config and state folders: " % PURGE_WORD)
                except EOFError:
                    raise Paused("input ended at the purge question")
            if typed != PURGE_WORD:
                raise UsageError("--purge needs the typed confirmation: pass --confirm %s (or type it when asked)" % PURGE_WORD)
    st = {"started": False}
    try:
        return _go(apply, purge, say, st)
    except KeyboardInterrupt:
        if st["started"]:
            raise Interrupted(purge) from None
        raise


def _go(apply, purge, say, st):
    if apply:
        manifest.reconcile()
    steps = sorted(manifest.load()["steps"], key=lambda s: -s.get("id", 0))
    say("shipm uninstall: %s (%d recorded step(s), newest first)" % ("APPLY" if apply else "dry run, nothing changes", len(steps)))
    skipped = 0
    for s in steps:
        label = "step %-3s row %-2s %s" % (s.get("id"), s.get("row"), _short(s))
        okv, whyv = validate(s)
        if not okv:
            skipped += 1
            say("  SKIPPED   %s: manifest entry refused: %s" % (label, whyv))
            continue
        what, why = decide(s)
        if what == "skip":
            skipped += 1
            say("  SKIPPED   %s: %s" % (label, why))
            hint = " (to remove only the shipm hooks by hand: shipm sync --hooks off)" if s.get("action") == "settings_sync" else ""
            if hint:
                say("            %s" % hint.strip())
            continue
        if not apply:
            say("  would %-7s %s%s" % ("reverse" if what == "reverse" else "forget", label, "" if what == "reverse" else " (%s)" % why))
            continue
        st["started"] = True
        if what == "gone":
            manifest.drop(s["id"])
            say("  gone      %s: %s" % (label, why))
            continue
        try:
            ok, note = _reverse(s)
        except (ShipmiracleError, OSError) as e:
            ok, note = False, "%s" % (e if isinstance(e, ShipmiracleError) else type(e).__name__)
        if ok:
            manifest.drop(s["id"])
            say("  REVERSED  %s: %s" % (label, note))
        else:
            skipped += 1
            say("  SKIPPED   %s: %s" % (label, note))
    left = manifest.load()["steps"] if apply else steps
    if apply and not left:
        manifest.remove_file()
        try:
            os.unlink(str(state.root() / "init.json"))
        except FileNotFoundError:
            pass
    say("")
    say("Not touched on purpose: your project folders and repos, any other tool's config folder, everything in ~/.claude that is not Shipmiracle's, your GitHub and Claude logins, Homebrew packages.")
    say("The engine clone stays. To delete it yourself when you are done:  rm -rf %s" % paths.workspace_dir())
    if apply and purge:
        if left:
            say("PURGE not done: %d step(s) were skipped, so the record is kept. Fix them, run `shipm uninstall --apply` again, then --purge." % len(left))
            return 1
        st["started"] = True
        for d in (paths.config_dir(), paths.state_dir()):
            if not _purge_ok(d):
                raise SafetyError("refusing to delete %s" % d)
        for d in (paths.config_dir(), paths.state_dir()):
            shutil.rmtree(str(d), ignore_errors=False) if os.path.isdir(str(d)) else None
            say("purged %s" % d)
    elif apply and left:
        say("%d step(s) skipped; they stay in the manifest." % len(left))
    elif apply:
        say("All steps reversed. Your config and state folders were kept; `shipm uninstall --apply --purge` deletes them too.")
    return 1 if (apply and skipped) else 0
