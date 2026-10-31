"""The `shipm` command line. Read-only except: config set/unset, switch, registry write (and the tools idea/bg that it hands over to).
Exit codes: 0 ok; 1 check failed or runtime error; 2 usage or validation; 3 not found; 4 safety refusal (ShipmiracleError.exit_code).
Errors go to stderr as `shipm: <message>`. Every --json output has a top-level "v": 1."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import traceback
from pathlib import Path

from . import ShipmiracleError, NotFound, SafetyError, SchemaError, UsageError
from . import agents, borrow, config, events, paths, project_links, projects, registry, skills, standard, state, team

DRIFT_GRACE = 60          # seconds: a legacy file younger than this is not compared with its v1 copy (the mirror follows the write)
SWITCH_RE = re.compile(r"[a-z][a-z0-9_.-]{0,63}")
EXEC_TOOLS = ("idea", "bg")
_EXEC_TARGET = {"idea": "idea", "bg": "shipm-bg"}
# `shipm migrate` exists only in the owner's private checkout: the tool sits in tools/private/ (never exported) and the subcommand is registered only while that file is there.
PRIVATE_TARGET = Path(__file__).resolve().parent.parent / "tools" / "private" / "shipm-migrate"


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise UsageError(message)


def _out(text="") -> None:
    sys.stdout.write(text + "\n")


def _json(obj) -> None:
    _out(json.dumps(dict([("v", 1)] + list(obj.items()))))


def _scalar(v) -> str:
    return v if isinstance(v, str) else json.dumps(v, sort_keys=True)


# ---- projects ----
def cmd_projects_links(a) -> int:
    """`shipm projects link A B [--read|--write]`, `unlink A B`, `links [--json]` (G11: which project chat may reach another project's folder; owner terminal only)."""
    act, rest = a.action, list(a.names or [])
    if act == "links":
        if rest:
            raise UsageError("links takes no names")
        rows = project_links.rows()
        if a.json:
            _json({"links": rows})
        else:
            for r in rows:
                _out("%s -> %s\t%s%s" % (r["from_name"] or r["from"], r["to_name"] or r["to"], r["mode"], "\tSTALE (a folder was renamed or moved; the link does nothing)" if r["stale"] else ""))
        return 0
    if len(rest) != 2:
        raise UsageError("usage: shipm projects %s FROM TO%s" % (act, " [--read|--write]" if act == "link" else ""))
    if act == "link":
        _out(project_links.link(rest[0], rest[1], "write" if a.write else "read"))
    else:
        _out(project_links.unlink(rest[0], rest[1]))
    return 0


def cmd_projects(a) -> int:
    if a.action:
        return cmd_projects_links(a)
    if a.resolve is not None:
        p = projects.resolve(a.resolve)
        if p is None:
            raise NotFound("no project contains %s" % a.resolve)
        _out("%s\t%s" % (p.id, p.name))
        return 0
    for n in projects.skipped_names():
        sys.stderr.write("shipm: warning: folder %s has a control character in its name and is ignored\n" % n)
    plist = projects.scope(projects.list_projects(), a.scope)
    if a.held:
        plist = [p for p in plist if p.held]
    if a.json:
        rows = []
        for p in plist:
            try:
                reg = registry.entry(p.id)
            except SchemaError:
                reg = None
            rows.append({"id": p.id, "name": p.name, "path": p.path, "real": p.real, "symlink": p.symlink,
                         "git": p.git, "hub": p.hub, "held": p.held, "registry": reg})
        _json({"projects": rows})
    else:
        for p in plist:
            _out(p.path if a.paths else "%s\t%s" % (p.id, p.name) if a.ids else p.name)
    return 0


# ---- state ----
def _legacy_json(path):
    return json.loads(state.read_bytes_nofollow(path).decode("utf-8"))


def _drift_view(name, data):
    """What is compared for a mirrored name. guard.json: its `actions` texts are left out
    (free text, so a stopped guard cannot show false drift)."""
    if name == "guard.json" and isinstance(data, dict):
        return {k: v for k, v in data.items() if k != "actions"}
    return data


def drift_problems(base=None) -> list:
    """Problems between mirrored v1 copies and their legacy files (only when switch state.v1 is on and both files exist):
    (a) frozen mirror: the legacy file was written more than DRIFT_GRACE s after the v1 envelope ts (a live writer rewrites both
        within seconds, so v1 stuck behind a moving legacy file shows at once, however young the legacy file is);
    (b) data drift: legacy quiet for at least DRIFT_GRACE s and v1 data differs (see _drift_view)."""
    b = Path(base) if base is not None else paths.state_dir()
    out = []
    if not config.switch("state.v1"):
        return out
    now = time.time()
    for name in sorted(state.OWNERS):
        v1p, lg = state.root(b) / name, b / name
        if not (os.path.lexists(v1p) and os.path.lexists(lg)):
            continue
        try:
            lmt = os.lstat(lg).st_mtime
            env = state.read(name, b)
        except Exception as e:
            out.append("v1/%s or its legacy file unreadable: %s" % (name, type(e).__name__))
            continue
        if lmt - env["ts"] > DRIFT_GRACE:
            out.append("%s: v1 copy is %d s behind the legacy file (mirror stuck?)" % (name, int(lmt - env["ts"])))
            continue
        if now - lmt < DRIFT_GRACE:
            continue
        try:
            legacy = _legacy_json(lg)
        except Exception as e:
            out.append("%s legacy file unreadable: %s" % (name, type(e).__name__))
            continue
        if _drift_view(name, env["data"]) != _drift_view(name, legacy):
            out.append("%s: v1 copy differs from the legacy file" % name)
    return out


def cmd_state(a) -> int:
    b = paths.state_dir()
    if a.action == "ls":
        rows = [{"name": n, "v1": os.path.lexists(state.root(b) / n), "legacy": os.path.lexists(b / n)} for n in sorted(state.OWNERS)]
        if a.json:
            _json({"state": rows})
        else:
            for r in rows:
                where = "both" if r["v1"] and r["legacy"] else "v1" if r["v1"] else "legacy" if r["legacy"] else "none"
                _out("%s\t%s" % (r["name"], where))
        return 0
    if a.action == "get":
        if not a.name:
            raise UsageError("state get needs a NAME")
        data, src = state.read_compat(a.name, b / a.name, b)
        if src is None:
            raise NotFound("no state %s" % a.name)
        _out(json.dumps(data, sort_keys=True))
        return 0
    problems = state.check(b) + drift_problems(b)
    if a.json:
        _json({"ok": not problems, "problems": problems})
    elif problems:
        for p in problems:
            _out(p)
    else:
        _out("ok")
    return 1 if problems else 0


# ---- config / switch ----
def cmd_config(a) -> int:
    if a.action == "path":
        _out(str(config.path()))
    elif a.action == "list":
        items = config.list_items(mask=True)
        if a.json:
            _json({"config": items})
        else:
            for k, v in items.items():
                _out("%s = %s" % (k, json.dumps(v, sort_keys=True)))
    elif a.action == "get":
        key = _need(a.key, "KEY")
        v = config.get(key)
        if key.startswith(config.MASKED_PREFIXES) and not a.reveal and v not in (None, []):
            v = "***"
        _out(_scalar(v))
    elif a.action == "set":
        config.set(_need(a.key, "KEY"), _need(a.value, "VALUE"))
        _out("ok")
    else:
        config.unset(_need(a.key, "KEY"))
        _out("ok")
    return 0


def _need(v, label):
    if v is None:
        raise UsageError("missing %s" % label)
    return v


VALUE_SWITCHES = ("hooks.dispatcher", "hooks.record", "gate.engine", "autopilot.full.enabled", "autopilot.standing.enabled", "owner.presence", "tokens.nudge", "guard.jobs", "agents.maxTurns", "prefix.trim", "reporter.model")    # config keys that `shipm switch` sets with an explicit value (validated by the config schema)


def _switch_text(v) -> str:
    return ("on" if v else "off") if isinstance(v, bool) else _scalar(v)


def cmd_switch(a) -> int:
    if a.name in VALUE_SWITCHES:
        if a.value is None:
            _out(_switch_text(config.get(a.name)))
        else:
            config.set(a.name, a.value)
            _out("%s %s" % (a.name, a.value))
        return 0
    if not SWITCH_RE.fullmatch(a.name) or ("switches." + a.name) not in config.SCHEMA:
        raise UsageError("unknown switch %r" % a.name[:64])
    if a.value is not None and a.value not in ("on", "off"):
        raise UsageError("switch value must be on or off")
    if a.value is None:
        _out("on" if config.switch(a.name) else "off")
    else:
        config.set("switches." + a.name, a.value)
        _out("%s %s" % (a.name, a.value))
    return 0


# ---- rollback (the switch table of docs/baseline/switches.json) ----
def _switch_table():
    f = paths.workspace_dir() / "docs" / "baseline" / "switches.json"
    try:
        t = json.loads(state.read_bytes_nofollow(f).decode("utf-8"))
    except (OSError, ValueError, SchemaError):
        raise NotFound("the switch table docs/baseline/switches.json is missing or damaged")
    if not isinstance(t, dict) or not isinstance(t.get("phases"), dict) or not isinstance(t.get("legacy", {}), dict):
        raise SchemaError("switches.json has an unexpected shape")
    return t


def _switch_now(name):
    """Current value text of a switch, or None when `name` is not a config key (yet)."""
    if name in VALUE_SWITCHES:
        return _switch_text(config.get(name))
    if ("switches." + name) in config.SCHEMA:
        return "on" if config.switch(name) else "off"
    return None


def cmd_rollback(a) -> int:
    t = _switch_table()
    phase = (a.phase or "").strip().upper()
    if phase not in t["phases"]:
        raise UsageError("unknown phase %r (known: %s)" % ((a.phase or "")[:20], ", ".join(sorted(t["phases"]))))
    rows = []
    for name in reversed(t["phases"][phase]):             # newest first: the reverse of the order they were switched on
        back = t.get("legacy", {}).get(name)
        now = _switch_now(name) if isinstance(name, str) and (name in VALUE_SWITCHES or SWITCH_RE.fullmatch(name)) else None
        if back is None or now is None:
            rows.append({"switch": name, "now": None, "back": back, "action": "unavailable"})
        else:
            rows.append({"switch": name, "now": now, "back": back, "action": "keep" if now == back else "change"})
    todo = [r for r in rows if r["action"] == "change"]
    manual = [m for m in (t.get("manual") or {}).get(phase, []) if isinstance(m, str)]
    done, failed = [], None
    if a.apply:
        paths.require_owner("shipm rollback")
    if a.apply and todo:
        sys.stderr.write("shipm rollback %s would set: %s\ntype yes to apply: " % (phase, ", ".join("%s %s" % (r["switch"], r["back"]) for r in todo)))
        sys.stderr.flush()
        if sys.stdin.readline().strip() != "yes":
            raise UsageError("not confirmed: nothing changed")
        for r in todo:
            try:
                config.set(r["switch"] if r["switch"] in VALUE_SWITCHES else "switches." + r["switch"], r["back"])
            except ShipmiracleError as e:
                failed = (r["switch"], str(e))
                break
            done.append(r["switch"])
    if a.json:
        _json({"phase": phase, "apply": bool(a.apply), "switches": rows, "applied": done, "failed": failed, "manual": manual})
    else:
        _out("rollback %s (%s)" % (phase, "APPLY" if a.apply else "dry run: add --apply to change anything"))
        for r in rows:
            if r["action"] == "unavailable":
                _out("  %-24s not available (%s)" % (r["switch"], "no config key yet" if r["now"] is None and r["back"] is not None else "no legacy value in the table"))
            else:
                _out("  %-24s %s -> %s%s" % (r["switch"], r["now"], r["back"], "" if r["action"] == "change" else " (already)"))
        for n in done:
            _out("  set %s (undo: shipm switch %s %s)" % (n, n, next(r["now"] for r in rows if r["switch"] == n)))
        for m in manual:
            _out("  then: " + m)
        if phase == "P4" and any(r["switch"] == "hooks.dispatcher" and r["action"] == "change" for r in rows) and config.get("gate.engine") != "legacy":
            _out("  note: gate.engine is %s; roll back P5 as well (shipm rollback P5)" % config.get("gate.engine"))
    if failed:
        raise SafetyError("%s was not changed: %s (done before it: %s)" % (failed[0], failed[1], ", ".join(done) or "nothing"))
    return 0


# ---- sync / hooks (settings writer) ----
def cmd_sync(a) -> int:
    from . import settings_sync
    from .hooks import spec
    if a.legacy_hooks and a.hooks not in (None, "legacy"):
        raise UsageError("--legacy-hooks means --hooks legacy")
    if a.repair_hooks:
        return _sync_repair(a)
    if a.apply:
        raise UsageError("--apply belongs to --repair-hooks")
    mode = "legacy" if a.legacy_hooks else a.hooks or config.get("hooks.dispatcher")
    if mode != settings_sync.OFF:
        config.require_legacy_hooks(mode)           # legacy|shadow register scripts: refused when this install does not ship them
    r = settings_sync.apply(mode=mode if mode == settings_sync.OFF else spec.check_mode(mode), dry_run=a.dry_run)
    if r["warning"]:
        _out("  WARNING: " + r["warning"])
    if r["diff"]:
        sys.stdout.write(r["diff"])
    if a.dry_run:
        _out("dry run: %s (mode %s, nothing written)" % ("would change %s" % r["path"] if r["changed"] else "no change", mode))
    elif r["changed"]:
        _out("hooks mode %s written to %s%s" % (mode, r["path"], "; backup %s" % r["backup"] if r["backup"] else ""))
        if r["backup"]:
            _out("  undo: cp %s %s   or   shipm sync --legacy-hooks" % (r["backup"], r["path"]))
    else:
        _out("hooks mode %s already in place: no change" % mode)
    missing = [x for x in spec.deny_rules() if x not in (_deny_have(r["path"]))]
    if missing:
        _out("  note: %d deny rule(s) missing in permissions.deny: run bin/gate-deny install" % len(missing))
    return 0


def _sync_repair(a) -> int:
    from . import settings_sync
    if a.hooks or a.legacy_hooks or a.dry_run:
        raise UsageError("--repair-hooks stands alone (dry run by default; add --apply to write)")
    r = settings_sync.repair(apply=a.apply)
    for ev, cmd in r["removed"]:
        _out("  remove %s: %s" % (ev, cmd if len(cmd) < 160 else cmd[:80] + " ... " + cmd[-70:]))
    if r["diff"]:
        sys.stdout.write(r["diff"])
    if not r["changed"]:
        _out("repair-hooks: nothing to repair in %s (no Shipmiracle hook with a missing or temp-folder script)" % r["path"])
    elif a.apply:
        _out("repair-hooks: %d Shipmiracle entr%s removed from %s; backup %s" % (len(r["removed"]), "y" if len(r["removed"]) == 1 else "ies", r["path"], r["backup"]))
        _out("  then run: shipm sync   (registers the hooks again from the real workspace)")
    else:
        _out("dry run: would remove %d Shipmiracle entr%s from %s; add --apply to write (owner only, in a terminal)" % (len(r["removed"]), "y" if len(r["removed"]) == 1 else "ies", r["path"]))
    return 0


def _deny_have(p):
    try:
        d = json.loads(state.read_bytes_nofollow(p).decode("utf-8"))
        return list((d.get("permissions") or {}).get("deny") or [])
    except Exception:
        return []


def _hooks_shadow_report(a) -> int:
    from .hooks import shadow
    try:
        secs = shadow.parse_since(a.since or "24h")
    except ValueError as e:
        raise UsageError(str(e))
    if getattr(a, "stage", False):
        rep = shadow.aggregate_stage(events.tail(100000), time.time() - secs)
        if a.json:
            _json(rep)
        else:
            _out("stage.shadow events (would-refusals of gate.engine=shadow): %d" % rep["events"])
            for k in ("by_kind", "by_project", "by_stage"):
                for n, v in sorted(rep[k].items()):
                    _out("  %s %s: %d" % (k, n, v))
            for d in rep["details"]:
                _out("  - " + json.dumps(d, sort_keys=True))
        return 0
    rep = shadow.aggregate(events.tail(100000), time.time() - secs)
    if a.json:
        _json(rep)
    else:
        _out("hook_shadow events: %d; agree %d, disagree %d, child errors %d; agree rate %s" % (rep["events"], rep["agree"], rep["disagree"], rep["child_errors"], rep["agree_rate"]))
        for k in ("by_event", "by_module"):
            for n, v in sorted(rep[k].items()):
                _out("  %s %s: %d" % (k, n, v))
        for d in rep["details"]:
            _out("  - " + json.dumps(d, sort_keys=True))
    return 1 if rep["disagree"] or rep["child_errors"] else 0


def _hooks_replay(a) -> int:
    from .hooks import replay
    corpus = a.corpus or "fixtures"
    replay.ENGINE = getattr(a, "engine", None)
    if a.limit is not None and a.limit < 0:
        raise UsageError("--limit must be 0 or more")
    if a.report:                                   # before the long run: a report path outside the repo/state/temp folders is refused (exit 2)
        try:
            replay.check_report_path(a.report, str(paths.state_dir()))
        except replay.ReplayError as e:
            raise UsageError(str(e))
    try:
        cases, info = replay.load_corpus(corpus, a.project, a.limit or 0, str(paths.state_dir()), str(paths.home()))
    except replay.ReplayError as e:
        raise UsageError(str(e))
    if not cases:
        raise NotFound("no replay cases in corpus %s%s" % (corpus, " for project " + a.project if a.project else ""))
    rep = replay.replay_cases(cases, corpus, src_home=str(paths.home()), full=a.full_local)
    where = replay.write_full_local(rep, str(paths.state_dir())) if a.full_local else ""
    for d in rep["disagreements"]:
        d.pop("full", None)
    if a.report:
        replay.write_report(rep, a.report, info)
    if a.json:
        _json(dict(rep, info=info, full_local=where))
    else:
        _out("replay %s: %d events, %d projects, %d disagreements (%d explained, %d unexplained), %.0f s" % (corpus, rep["events"], len(rep["by_project"]), len(rep["disagreements"]), rep["explained"], rep["unexplained"], rep["secs"]))
        if a.report:
            _out("report: " + a.report)
        if where:
            _out("full texts (local only): " + where)
    return 1 if rep["unexplained"] else 0


def cmd_hooks(a) -> int:
    if a.action == "apply":
        from . import githook_apply
        return githook_apply.run(a.value)
    from .hooks import spec
    if a.action == "shadow-report":
        return _hooks_shadow_report(a)
    if a.action == "replay":
        return _hooks_replay(a)
    if a.action == "record":
        if a.value not in ("on", "off"):
            raise UsageError("hooks record needs on or off (same as: shipm switch hooks.record on|off)")
        a.name = "hooks.record"
        return cmd_switch(a)
    if a.action == "mode":
        _out(config.get("hooks.dispatcher"))
        return 0
    if a.action == "spec":
        mode = spec.check_mode(a.mode or config.get("hooks.dispatcher"))
        built = spec.build(mode)
        if a.json:
            _json({"mode": mode, "hooks": built["hooks"], "statusLine": built["statusLine"], "env": built["env"],
                   "deny_rules": spec.deny_rules(), "warning": built["warning"]})
        else:
            for ev, m, cmd in spec.entries(built):
                _out("%s\t%s\t%s" % (ev, m, cmd))
            _out("statusLine\t-\t%s" % built["statusLine"]["command"])
            for k, v in built["env"].items():
                _out("env\t%s\t%s" % (k, v))
        return 0
    raise UsageError("unknown hooks action")


# ---- standard (CLAUDE.md managed block) ----
def _std_target(arg, outside=False) -> str:
    """A project given by folder path or by name under the Developer folder; must exist and (without --outside) be a direct child of it."""
    if not arg:
        raise UsageError("a project name or folder is needed")
    cand = Path(arg).expanduser()
    if not (os.sep in arg or arg.startswith(".")):
        cand = paths.dev_dir() / arg
    if not cand.is_dir():
        raise NotFound("no project folder %s" % arg)
    if not outside:
        dev = os.path.realpath(str(paths.dev_dir()))
        parent = os.path.realpath(str(cand.parent)) if cand.name not in ("", ".", "..") else ""
        if parent != dev or cand.name.startswith("."):
            raise UsageError("%s is not a direct child of the Developer folder (use --outside to allow it)" % arg)
    return str(cand if cand.name not in ("", ".", "..") else cand.resolve())


def cmd_standard(a) -> int:
    act = a.action
    if act == "render":
        sys.stdout.write(standard.render(standard.base_text()))
        return 0
    if act == "plan" and a.all:
        rows = []
        for p in projects.list_projects():
            if p.symlink:
                continue
            pl = standard.plan_migration(p.path)
            if pl.status == "skip" and not pl.exception:
                continue
            rows.append(standard.summary(pl))
        if a.json:
            _json({"plans": rows})
        else:
            for r in rows:
                _out("%s\t%s\t%s\tblock-removed=%d template-removed=%d kept=%d containment=%s%s%s" % (
                    r["project"], r["status"], r["shape"] or "-", r["removed_block_lines"], r["removed_template_lines"],
                    r["kept_lines"], r["containment"], "\tEXCEPTION(%s)" % r["exception"] if r["exception"] else "",
                    "\tflagged=%d" % len(r["flagged"]) if r["flagged"] else ""))
        return 1 if any(r["lost"] for r in rows) else 0
    if a.all:
        raise UsageError("--all is only for plan")
    pl = standard.plan_migration(_std_target(a.project, a.outside))
    if act == "plan":
        if a.json:
            _json({"plan": standard.summary(pl)})
        else:
            _out(json.dumps(standard.summary(pl), indent=1, sort_keys=True, ensure_ascii=False))
            if a.diff:
                sys.stdout.write(standard.diff(pl))
        return 1 if pl.lost else 0
    if act == "sync":
        if pl.status != "already":
            _out("  %s: not migrated yet%s (shipm standard plan %s)" % (pl.name, "; standard manual, never auto-migrated" if pl.manual else "", pl.name))
            return 0
        ch = standard.sync_project(pl.project)
        if ch:
            _out("  updated %s: %s" % (pl.name, ", ".join(ch)))
        return 0
    if act == "apply":
        if not a.yes:
            raise UsageError("apply changes files in the project: add --yes (read the plan first)")
        res = standard.apply(pl, state.root() / "backups")
        _out("%s: %s" % (pl.name, json.dumps(res, sort_keys=True)))
        return 0
    raise UsageError("unknown standard action")


# ---- registry / events ----
def _project_id_arg(arg) -> str:
    """A project id from an id, a name or a folder; an id of a project whose folder is gone is accepted as it is (forget)."""
    if isinstance(arg, str) and re.fullmatch(r"[0-9a-f]{12}", arg):
        return arg
    return agents.project_for(arg).id


def cmd_registry(a) -> int:
    act, ra = a.action, list(a.rargs or [])
    if act in ("propose", "write"):
        proposal = registry.propose()
        if act == "write":
            added = registry.write_missing(proposal)
            _out("added %d" % len(added))
            for i in added:
                _out(i)
        elif a.json:
            _json({"projects": proposal["projects"]})
        else:
            for i, e in proposal["projects"].items():
                _out("%s\t%s\t%s" % (i, e["name"], e.get("remote") or "-"))
        return 0
    if act == "sync":
        r = registry.sync()
        _out("added %d, filled %d" % (len(r["added"]), len(r["filled"])))
        return 0
    if act == "set":
        if len(ra) != 3:
            raise UsageError("registry set needs PROJECT KEY VALUE")
        registry.set_field(_project_id_arg(ra[0]), ra[1], ra[2])
        _out("ok")
        return 0
    if act == "forget":
        if len(ra) != 1:
            raise UsageError("registry forget needs PROJECT")
        _out("forgotten" if registry.forget(_project_id_arg(ra[0])) else "was not registered")
        return 0
    if act == "add-remote":
        if len(ra) != 1:
            raise UsageError("registry add-remote needs ROLE (public-engine) --remote OWNER/NAME --visibility private|public")
        _out("public-engine entry %s" % registry.add_remote_only(ra[0], a.remote, a.visibility))
        return 0
    if act == "activate":
        if len(ra) != 2:
            raise UsageError("registry activate needs PROJECT AGENT")
        r = agents.activate(ra[0], ra[1], a.confirm_role)
        _out("activated %s in %s (%s, %s)" % (r["name"], r["project"], r["role"], r["sha256"][:12]))
        return 0
    raise UsageError("unknown registry action")


def cmd_events(a) -> int:
    if a.n < 0:
        raise UsageError("-n must be 0 or more")
    evs = events.tail(a.n)
    if a.json:
        _json({"events": evs})
    else:
        for e in evs:
            ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(e.get("ts", 0))) if isinstance(e.get("ts"), int) else "?"
            _out("%s %s %s %s %s" % (ts, e.get("kind", "?"), e.get("project") or "-", e.get("src", "?"),
                                     json.dumps(e.get("data", {}), sort_keys=True)))
    return 0


# ---- agents (the team: masters, user-level install, resolver, check) ----
def _resolved_line(r) -> str:
    return "%s\t%s\tclaimed=%s\teffective=%s\ttrusted=%s%s%s" % (
        r.name, r.layer, r.claimed, r.effective, "yes" if r.trusted else "no",
        "\talias_of=%s" % r.alias_of if r.alias_of else "", "\tlens=%s" % r.lens if r.lens else "")


def _plain_actions(res):
    for x in res["actions"]:
        _out("  %-8s %-18s %s" % (x["action"], x["name"], x["why"]))


def cmd_agents(a) -> int:
    act, ra = a.action, list(a.rargs or [])
    if act == "install":
        if not a.dry_run:                                  # show the diff of every changed master BEFORE anything is written
            pre = agents.install(dry_run=True, allow_dirty=a.allow_dirty)
            if pre["diff"]:
                _out("changes to install:"); _out(pre["diff"]); _out("")
        res = agents.install(dry_run=a.dry_run, allow_dirty=a.allow_dirty)
        for w in res["warnings"]:
            _out("warning: " + w)
        if a.dry_run and res["diff"]:
            _out("changes that would be installed:"); _out(res["diff"]); _out("")
        _out("%s: %d masters from %s%s" % ("dry run (nothing written)" if a.dry_run else "installed", len(res["actions"]), res["ws"],
                                         "" if not res.get("ws_sha") else " @ " + res["ws_sha"][:12]))
        _plain_actions(res)
        _out("  legacy trust (old role files accepted until %s): %s" % (agents.LEGACY_EXPIRES, ", ".join("%s=%d" % kv for kv in res["legacy"].items()) or "none (frozen set missing)"))
        if a.dry_run:
            _out("  legacy set (frozen at the P3b cutoff) vs the installed one: " + ("; ".join(res.get("legacy_diff") or []) or "no difference"))
        return 0
    if act == "uninstall":
        _plain_actions(agents.uninstall())
        return 0
    if act == "check":
        probs = []
        mode = "draft" if a.draft else "master" if a.master else None
        if a.project:
            pd = str(agents.project_for(a.project).path) if not os.path.isdir(a.project) else a.project
            probs = agents.check(None, project_dir=pd)
            listing = [r.as_dict() for r in agents.list_agents(pd)]
        else:
            if not ra:
                raise UsageError("check needs FILE... or --project DIR")
            for f in ra:
                probs += agents.check(f, mode, project_dir=a.in_project)
            listing = []
        if a.json:
            _json({"ok": not probs, "problems": [dict(p._asdict()) for p in probs], "agents": listing, "count": len(listing)})
        else:
            for line in agents.format_problems(probs):
                _out(line)
        return agents.exit_code(probs)
    if act == "vendor":
        if not a.all and len(ra) != 1:
            raise UsageError("vendor needs PROJECT or --all")
        for r in agents.vendor(ra[0] if ra else None, all_projects=a.all):
            _out("%s: wrote %d, kept %d%s%s" % (r["project"], len(r["written"]), len(r["kept"]),
                                                 ", committed" if r["committed"] else "", ", SKIPPED: " + r["skipped"] if r["skipped"] else ""))
            for n, why in r["kept"]:
                _out("  kept %s: %s" % (n, why))
        return 0
    if act == "activate":
        if len(ra) != 2:
            raise UsageError("activate needs PROJECT AGENT")
        r = agents.activate(ra[0], ra[1], a.confirm_role)
        _out("activated %s in %s (%s, %s)%s" % (r["name"], r["project"], r["role"], r["sha256"][:12], ", moved from agents-drafts" if r["moved"] else ""))
        return 0
    if act == "migrate-team":
        return _migrate_team(a, ra)
    if act == "list":
        pd = str(agents.project_for(a.project).path) if a.project else None
        rs = agents.list_agents(pd)
        if a.json:
            _json({"agents": [r.as_dict() for r in rs]})
        else:
            for r in rs:
                _out(_resolved_line(r))
        return 0
    if act == "resolve":
        if len(ra) != 1:
            raise UsageError("resolve needs NAME")
        pd = str(agents.project_for(a.project).path) if a.project else None
        r = agents.resolve(ra[0], pd)
        if r is None:
            raise NotFound("%s does not resolve" % ra[0][:64])
        _json({"resolved": r.as_dict()}) if a.json else _out(_resolved_line(r))
        return 0
    raise UsageError("unknown agents action")


def _project_aside(a) -> int:
    """F7/F8: `shipm project aside NAME [--note T]`, `aside --list [--json]`, `unaside NAME`, `seen NAME` (owner at a terminal; they only write <state>/v1/aside.json or seen.json)."""
    from . import aside
    ra = list(a.rargs or [])
    if a.action == "aside" and a.list_:
        m, sil = aside.aside_map(), aside.silenced_list()
        out = {"aside": [dict(project=k, since=v["since"], note=v["note"]) for k, v in sorted(m.items())], "silenced": sil, "returned": aside.returned(),
               "silencedKinds": list(aside.SILENCED_KINDS)}
        if a.json:
            _json(out)
        else:
            for r in out["aside"]:
                _out("%s\tsince %s%s" % (r["project"], r["since"], ("\t" + r["note"]) if r["note"] else ""))
        return 0
    if len(ra) != 1:
        raise UsageError("%s needs NAME" % a.action)
    if a.action == "aside":
        r = aside.set_aside(ra[0], a.note)
        _json(r) if a.json else _out("set aside: %s" % r["project"])
    elif a.action == "unaside":
        was = aside.unaside(ra[0])
        _json({"project": ra[0], "was_aside": was}) if a.json else _out("brought back: %s" % ra[0] if was else "not set aside: %s" % ra[0])
    else:
        ts = aside.mark_seen(ra[0])
        _json({"project": ra[0], "seen": ts}) if a.json else _out("seen: %s" % ra[0])
    return 0


def _project(a) -> int:
    ra = list(a.rargs or [])
    if a.action in ("aside", "unaside", "seen"):
        return _project_aside(a)
    if a.note or a.list_:
        raise UsageError("--note and --list belong to aside")
    if a.action == "hooks-global":
        return _hooks_global(a, ra)
    if a.undo:
        raise UsageError("--undo belongs to hooks-global")
    return _migrate_team(a, ra)


def _hooks_global(a, ra) -> int:
    from . import settings_sync
    if len(ra) != 1:
        raise UsageError("hooks-global needs PROJECT")
    if a.apply and a.undo:
        raise UsageError("--apply and --undo are separate")
    p = agents.project_for(ra[0])
    if not a.undo:
        if config.get("hooks.dispatcher") != "v1":
            raise SafetyError("hooks.dispatcher is %s, not v1: the dispatcher would not serve this project's hooks; nothing changed" % config.get("hooks.dispatcher"))
        if registry.entry(p.id) is None:
            raise SafetyError("%s is not in the registry: its project hooks run only for registered projects (shipm registry write)" % p.name)
    r = settings_sync.project_hooks_global(p.real, p.id, apply=a.apply, undo=a.undo)
    if a.undo:
        _out("%s: %s" % (p.name, "restored %s from %s" % (r["path"], r["backup"]) if r["changed"] else "already identical to the backup: no change"))
        return 0
    _out("%s: %s" % (p.name, "APPLY" if a.apply else "dry run (add --apply to change anything)"))
    for ev, cmd in r["removed"]:
        _out("  %s %s: %s" % ("removed" if a.apply else "would remove", ev, cmd.replace("$CLAUDE_PROJECT_DIR/", "")))
    for sh, why in r["kept"]:
        _out("  kept %s: %s" % (sh, why))
    if r["diff"]:
        sys.stdout.write(r["diff"])
    if not r["changed"]:
        _out("  no change")
    elif a.apply:
        _out("  backup %s" % r["backup"])
        _out("  undo: shipm project hooks-global %s --undo   (or cp %s %s)" % (ra[0], r["backup"], r["path"]))
        _out("  the file is part of the project: commit it there when the next session works")
    return 0


def _migrate_team(a, ra) -> int:
    if len(ra) != 1:
        raise UsageError("migrate-team needs PROJECT")
    if a.apply and not os.environ.get("SHIPMIRACLE_TEST"):
        watch = Path(__file__).resolve().parent.parent / "bin" / "shipm-watch"
        if watch.is_file():
            import subprocess
            try:
                subprocess.run([str(watch), "scan", "--dry"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
            except (OSError, subprocess.SubprocessError):
                pass
    r = agents.migrate_team(ra[0], apply=a.apply, drop_backups=a.drop_backups)
    _out("%s: %s" % (r["project"], "APPLY" if a.apply else "dry run (add --apply to change anything)"))
    for n in r["removed"]:
        _out("  %s %s (exact master copy)" % ("removed" if a.apply and not r["skipped"] else "would remove", n))
    for n, why in r["kept"]:
        _out("  kept %s: %s" % (n, why))
    if r.get("has_backups"):
        _out("  .claude/_backup exists: %s" % ("dropped" if r["backups_dropped"] else "kept (add --drop-backups to remove it)"))
    if r["skipped"]:
        _out("  SKIPPED: %s" % r["skipped"])
        return 1
    if a.apply:
        _out("  committed: Team moved to user level" if r["committed"] else "  nothing to commit")
    return 0


# ---- doctor rows ----
def doctor_rows() -> list:
    rows = []
    add = lambda level, text: rows.append("  %-4s %s" % (level, text))   # noqa: E731  ("  ok   x", "  warn x", "  FAIL x", "  info x")
    v = sys.version_info
    add("ok" if v >= (3, 9) else "FAIL", "python %d.%d.%d" % v[:3] + ("" if v >= (3, 9) else " (Shipmiracle needs 3.9 or newer)"))
    b = paths.state_dir()
    try:
        probs = state.check(b)
    except Exception as e:
        probs = ["state check failed: %s" % type(e).__name__]
    if not probs:
        add("ok", "state folder permissions and v1 files")
    else:
        serious = any("symlink" in p or "another user" in p or "unreadable" in p for p in probs)
        add("FAIL" if serious else "warn", "state folder: %d problem(s), first: %s → shipm state check" % (len(probs), probs[0]))
    try:
        dp = drift_problems(b)
    except Exception as e:
        dp = ["drift check failed: %s" % type(e).__name__]
    add("ok" if not dp else "FAIL", "state v1 matches the legacy files" if not dp else "state drift: %s → shipm state check" % dp[0])
    try:
        for alias, kept in projects.collisions():
            add("warn", "alias folder %s -> %s ignored (same folder listed twice)" % (alias, kept))
        for n in projects.skipped_names():
            add("warn", "folder %s ignored (control character in the name)" % n)
    except Exception as e:
        add("warn", "project folder check failed: %s" % type(e).__name__)
    try:
        config.load()
        add("ok", "owner config valid (%s)" % ("present" if os.path.lexists(config.path()) else "absent, defaults"))
    except ShipmiracleError as e:
        add("FAIL", "owner config invalid: %s → shipm config path" % e)
    try:
        n = len(registry.load()["projects"])
        add("info", "project registry present (%d entries)" % n if n or os.path.lexists(registry.path())
            else "project registry not created yet → shipm registry write")
    except ShipmiracleError as e:
        add("FAIL", "project registry invalid: %s" % e)
    try:
        bad = standard.malformed_markers()
        add("ok" if not bad else "warn", "standard markers well-formed" if not bad else "broken standard markers in %s → shipm standard plan <project>" % ", ".join(bad))
    except Exception as e:
        add("warn", "standard marker check failed: %s" % type(e).__name__)
    try:
        for lv, text in agents.doctor_rows():
            add(lv, text)
    except Exception as e:
        add("warn", "agents check failed: %s" % type(e).__name__)
    try:
        for lv, text in skills.doctor_rows():
            add(lv, text)
    except Exception as e:
        add("warn", "skills check failed: %s" % type(e).__name__)
    return rows


def cmd_skills(a) -> int:
    if a.action == "found":
        fnd = skills.found_scan()
        for ln in skills.found_lines(fnd, short=a.short):
            _out(ln)
        return 1 if any(f["level"] == "FAIL" for f in fnd) else 0
    if a.action in ("approve", "remove", "ignore"):
        paths.require_owner("shipm skills %s" % a.action)
        if not a.project:
            raise UsageError("usage: shipm skills %s NAME%s" % (a.action, {"approve": ' --why "..." [--pack a,b]', "ignore": ' --reason "..."', "remove": ""}[a.action]))
        if a.action == "approve":
            _out(skills.approve(a.project, a.why, a.pack))
        elif a.action == "ignore":
            _out(skills.ignore(a.project, a.reason))
        else:
            return skills.remove(a.project)
        return 0
    if a.action != "view" or not a.project:
        raise UsageError("usage: shipm skills view PROJECT [--write] [--mark-reviewed]")
    text, wrote = skills.view(a.project, write=a.write, mark_reviewed=a.mark_reviewed)
    if a.write:
        _out("wrote %s" % wrote)
    else:
        _out(text.rstrip("\n"))
        _out("(dry run: add --write to replace docs/SKILLS.md)")
    return 0


def _team_project(arg, write):
    """The checkout a `shipm team` command works on: the folder given (name, id or path), else the current one. A chat (CLAUDECODE set) may
    read another project's table but may not write one: its own checkout is the only one it can add to."""
    from .playbook import cli as pbcli
    pd = pbcli._project_arg(arg)
    if write and "CLAUDECODE" in os.environ and arg:
        here = pbcli.checkout(None)
        if os.path.realpath(pd) != os.path.realpath(here):
            raise SafetyError("a chat can change only its own project's team: this chat is in %s, not %s" % (os.path.basename(here), os.path.basename(pd)))
    return pd


def cmd_team(a) -> int:
    ra = list(a.rargs or [])
    if a.action == "add":
        if not ra or len(ra) > 2:
            raise UsageError("usage: shipm team add AGENT --role R --why \"...\" [--skills a,b] [PROJECT]")
        if not a.role or not a.why:
            raise UsageError("team add needs --role and --why")
        pd = _team_project(ra[1] if len(ra) > 1 else None, True)
        skl = [x.strip() for x in a.skills.split(",")] if a.skills is not None else []
        if a.skills is not None and (not a.skills.strip() or any(not x for x in skl)):
            raise UsageError("--skills is a comma list of skill names (no empty names)")
        r = team.add_row(pd, ra[0], a.role, a.why, skl)
        for sk in r.get("missing_skills", []):
            sys.stderr.write("shipm: warning: skill %s is not installed here (the row was written)\n" % sk[:64])
        _json(r) if a.json else _out("added %s (%s) to the team of %s" % (r["agent"], r["role"], os.path.basename(pd)))
        return 0
    if a.role or a.why or a.skills:
        raise UsageError("--role, --why and --skills belong to `team add`")
    if len(ra) > 1:
        raise UsageError("usage: shipm team %s [PROJECT]" % a.action)
    pd = _team_project(ra[0] if ra else None, False)
    if a.action == "show":
        t = team.load(pd)
        if a.json:
            _json({"state": t.state, "rows": t.rows, "ignored": [{"line": ln, "why": w} for ln, w in t.ignored], "detail": t.detail})
            return 1 if t.state in ("damaged", "unreadable") else 0
        if t.state in ("damaged", "unreadable"):
            _out("the Team table is %s: %s" % (t.state if t.state == "damaged" else "unreadable (docs/SKILLS.md)", t.detail))
            return 1
        if t.state != "ok":
            _out("no team table (none recorded yet; the lead adds it with `shipm team add`)")
        for r in t.rows:
            _out("%-8s %-24s %-24s %s" % (r["role"], r["agent"], ",".join(r["skills"]) or "-", r["why"]))
        for ln, why in t.ignored:
            _out("ignored line %d: %s" % (ln, why))
        return 0
    found = team.check(pd)
    code = team.exit_code(found)
    if a.json:
        _json({"ok": code == 0, "findings": [{"level": lv, "message": m} for lv, m in found]})
    else:
        for lv, m in found:
            _out("%s: %s" % (lv, m))
        if not found:
            _out("team ok")
    return code


def cmd_borrow(a) -> int:
    ra = list(a.rargs or [])
    extra = [n for n, v in (("--reason", a.reason), ("--as", a.as_name), ("--dest", a.dest)) if v is not None]
    if a.action == "list":
        if extra:
            raise UsageError("%s belong to `borrow record`" % ", ".join(extra))
        if len(ra) > 1 or (ra and a.project):
            raise UsageError("usage: shipm borrow list [PROJECT]")
        pd = _team_project(ra[0] if ra else a.project, False)
        rows, prob = borrow.list_entries(pd)
        if a.json:
            _json({"items": rows, "problem": prob})
            return 1 if prob else 0
        if prob:
            _out("problem: " + prob)
            return 1
        if not rows:
            _out("nothing borrowed in %s" % os.path.basename(pd))
        for r in rows:
            _out("%-34s %-22s %s  %s  [%s]" % (r["id"], r["name"], r["dest"], r["borrowed"], r["status"]))
        return 0
    if len(ra) != 1:
        raise UsageError("usage: shipm borrow show ID | shipm borrow record ID --reason TEXT --as NAME [--dest PATH] [--project P]")
    if a.action == "show":
        if extra or a.project:
            raise UsageError("`borrow show` takes only the item id")
        try:
            info = borrow.load_item(ra[0])
        except NotFound as e:
            if str(e) == borrow.NO_CATALOG:
                _out(borrow.NO_CATALOG)
                return 3
            raise
        if a.json:
            _json(borrow.public_info(info))
        else:
            _out(borrow.render_reference(info))
        return 4 if info["refused"] else 0
    if not a.reason or not a.as_name:
        raise UsageError("borrow record needs --reason and --as (the name of YOUR version)")
    pd = _team_project(a.project, True)
    try:
        e = borrow.record(pd, ra[0], a.reason, a.as_name, a.dest, by="lead" if "CLAUDECODE" in os.environ else "owner")
    except NotFound as ex:
        if str(ex) == borrow.NO_CATALOG:
            _out(borrow.NO_CATALOG)
            return 3
        raise
    _json({"recorded": e}) if a.json else _out("recorded %s as %s (%s) in %s/.agents/borrowed.json" % (e["id"], e["name"], e["dest"], os.path.basename(pd)))
    return 0


def cmd_doctor(a) -> int:
    if not a.rows:
        raise UsageError("doctor needs --rows")
    rows = doctor_rows()
    for r in rows:
        _out(r)
    return 1 if any(r.startswith("  FAIL") for r in rows) else 0


# ---- hand-over to the existing tools ----
def _exec(tool: str, args: list) -> int:
    name = _EXEC_TARGET.get(tool, "")
    seam = os.environ.get("SHIPMIRACLE_EXEC_" + tool.upper()) if os.environ.get("SHIPMIRACLE_TEST") == "1" else None
    target = Path(seam) if seam else (PRIVATE_TARGET if tool == "migrate" else Path(__file__).resolve().parent.parent / "bin" / name)
    if not target.is_file() or not os.access(str(target), os.X_OK):
        raise NotFound("%s is missing or not executable" % target)
    sys.stdout.flush()
    os.execv(str(target), [str(target)] + list(args))
    return 1   # not reached


# ---- parser ----
def build_parser() -> argparse.ArgumentParser:
    P = _Parser(prog="shipm", description="Shipmiracle command line. Exit codes: 0 ok, 1 check failed, 2 usage, 3 not found, 4 safety refusal.")
    sub = P.add_subparsers(dest="cmd", parser_class=_Parser, metavar="COMMAND")
    sub.required = True

    p = sub.add_parser("projects", help="list projects (one per line)")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--names", action="store_true", help="names (default)")
    g.add_argument("--paths", action="store_true", help="folder paths")
    g.add_argument("--ids", action="store_true", help="id<TAB>name")
    g.add_argument("--json", action="store_true", help='{"v":1,"projects":[...]}')
    g.add_argument("--resolve", metavar="PATH", help="the project containing PATH: id<TAB>name, exit 3 if none")
    p.add_argument("--scope", choices=projects.SCOPES, default="all")
    p.add_argument("--held", action="store_true", help="only projects held back by config/ci-hold.txt")
    p.add_argument("action", nargs="?", choices=("link", "unlink", "links"), help="link FROM TO [--read|--write] | unlink FROM TO | links: which project chat may reach another project's folder (owner terminal only)")
    p.add_argument("names", nargs="*", help="FROM TO (project names) for link and unlink")
    p.add_argument("--read", action="store_true", help="link: read access (default)")
    p.add_argument("--write", action="store_true", help="link: write access (includes read)")
    p.set_defaults(fn=cmd_projects)

    p = sub.add_parser("state", help="read-only view of the state folder")
    p.add_argument("action", choices=("ls", "get", "check"))
    p.add_argument("name", nargs="?", help="state file name (get)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_state)

    p = sub.add_parser("config", help="owner config (~/.config/shipmiracle/config.json)")
    p.add_argument("action", choices=("get", "set", "unset", "list", "path"))
    p.add_argument("key", nargs="?")
    p.add_argument("value", nargs="?")
    p.add_argument("--json", action="store_true", help="list as JSON")
    p.add_argument("--reveal", action="store_true", help="get: show a masked value instead of ***")
    p.set_defaults(fn=cmd_config)

    p = sub.add_parser("switch", help="show or set a switch (rollback levers)")
    p.add_argument("name")
    p.add_argument("value", nargs="?", help="on|off; for hooks.dispatcher legacy|shadow|v1; for gate.engine legacy|shadow|playbook (needs hooks.dispatcher=v1); for hooks.record on|off")
    p.set_defaults(fn=cmd_switch)

    p = sub.add_parser("rollback", help="go back one phase: PHASE (P1..P7) prints its switches and their legacy values; --apply (owner only, typed yes) sets them, newest first")
    p.add_argument("phase", help="P1, P2, P4, P5, P6 or P7 (the table is docs/baseline/switches.json)")
    p.add_argument("--apply", action="store_true", help="change the switches (default: dry run)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_rollback)

    p = sub.add_parser("sync", help="write the Shipmiracle hook registration into ~/.claude/settings.json (owner only; --dry-run shows the diff)")
    p.add_argument("--hooks", choices=("legacy", "shadow", "v1", "off"), help="mode (default: config hooks.dispatcher); off removes only the Shipmiracle entries")
    p.add_argument("--legacy-hooks", action="store_true", help="same as --hooks legacy (rollback)")
    p.add_argument("--dry-run", action="store_true", help="print the diff, write nothing")
    p.add_argument("--repair-hooks", action="store_true", help="remove only the Shipmiracle hook entries whose script is missing or in a temp folder (dry run; add --apply)")
    p.add_argument("--apply", action="store_true", help="with --repair-hooks: write the repair (owner only)")
    p.set_defaults(fn=cmd_sync)

    p = sub.add_parser("hooks", help="hook registration: mode, spec --mode M [--json]; replay [--corpus fixtures|record|transcripts]; shadow-report [--since 24h]; record on|off; apply NAME (owner only, in a terminal: install the git hook a chat proposed in docs/proposed-hooks/NAME.txt after you read the diff and type the word apply)")
    p.add_argument("action", choices=("mode", "spec", "replay", "shadow-report", "record", "apply"))
    p.add_argument("value", nargs="?", help="record: on|off; apply: the git hook name (pre-commit, post-commit, pre-push ...)")
    p.add_argument("--mode", choices=("legacy", "shadow", "v1"))
    p.add_argument("--json", action="store_true")
    p.add_argument("--corpus", choices=("fixtures", "record", "transcripts"), help="replay: where the hook inputs come from (default fixtures)")
    p.add_argument("--project", help="replay: only this project")
    p.add_argument("--engine", choices=("shadow", "playbook"), help="replay: run the stage module (change requests) on the replayed events")
    p.add_argument("--limit", type=int, help="replay: at most N events")
    p.add_argument("--report", help="replay: write the report (counts and sha prefixes only) to this file")
    p.add_argument("--full-local", action="store_true", help="replay: also write the full texts of every disagreement to a local file in the state folder")
    p.add_argument("--since", help="shadow-report: window like 24h, 90m, 7d (default 24h)")
    p.add_argument("--stage", action="store_true", help="shadow-report: the stage.shadow events (what gate.engine=shadow would have refused) instead of the hook_shadow ones")
    p.set_defaults(fn=cmd_hooks)

    p = sub.add_parser("registry", help="project registry (~/.config/shipmiracle/registry.json): propose, write, sync, set, activate, forget")
    p.add_argument("action", choices=("propose", "write", "sync", "set", "activate", "forget", "add-remote"))
    p.add_argument("rargs", nargs="*", help="set PROJECT KEY VALUE | activate PROJECT AGENT | forget PROJECT | add-remote public-engine")
    p.add_argument("--remote", help="add-remote: owner/name on GitHub")
    p.add_argument("--visibility", choices=("private", "public"), help="add-remote: the visibility the repo must have")
    p.add_argument("--confirm-role", dest="confirm_role", help="activate: the privileged role the file claims (plan, test, review, report), after you read it")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_registry)

    p = sub.add_parser("agents", help="the team: install/uninstall (owner), check, vendor, activate, migrate-team, list, resolve")
    p.add_argument("action", choices=("install", "uninstall", "check", "vendor", "activate", "migrate-team", "list", "resolve"))
    p.add_argument("rargs", nargs="*", help="check FILE... | vendor PROJECT | activate PROJECT AGENT | migrate-team PROJECT | resolve NAME")
    p.add_argument("--dry-run", action="store_true", help="install: show what would change")
    p.add_argument("--allow-dirty", action="store_true", help="install: use the working tree of agents/claude even with uncommitted changes")
    p.add_argument("--apply", action="store_true", help="migrate-team: do it (default is a dry run)")
    p.add_argument("--drop-backups", action="store_true", help="migrate-team: also remove .claude/_backup")
    p.add_argument("--all", action="store_true", help="vendor: every project")
    p.add_argument("--confirm-role", dest="confirm_role", help="activate: the privileged role the file claims (plan, test, review, report), after you read it")
    p.add_argument("--project", help="check/list/resolve: a project name or folder")
    p.add_argument("--in-project", dest="in_project", help="check FILE: the project the file belongs to (skills, active count)")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--draft", action="store_true", help="check: an invited agent in .claude/agents-drafts/")
    g.add_argument("--master", action="store_true", help="check: a master in agents/claude/")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_agents)

    p = sub.add_parser("project", help="project moves: migrate-team PROJECT [--apply] [--drop-backups]; hooks-global PROJECT [--apply|--undo]; aside NAME [--note T] | aside --list | unaside NAME | seen NAME")
    p.add_argument("action", choices=("migrate-team", "hooks-global", "aside", "unaside", "seen"))
    p.add_argument("--note", help="aside: why (optional, 120 characters)")
    p.add_argument("--list", dest="list_", action="store_true", help="aside: list the set-aside projects, the silenced Health items and the auto un-aside notices")
    p.add_argument("--json", action="store_true")
    p.add_argument("rargs", nargs="*")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--drop-backups", action="store_true")
    p.add_argument("--undo", action="store_true", help="hooks-global: restore the settings.json from the newest backup")
    p.set_defaults(fn=_project)

    p = sub.add_parser("standard", help="the CLAUDE.md engineering standard: render, plan/apply a migration, sync")
    p.add_argument("action", choices=("render", "plan", "apply", "sync"))
    p.add_argument("project", nargs="?", help="project name (under the Developer folder) or folder")
    p.add_argument("--all", action="store_true", help="plan: every project (read-only)")
    p.add_argument("--diff", action="store_true", help="plan: also print the CLAUDE.md diff")
    p.add_argument("--yes", action="store_true", help="apply: confirm")
    p.add_argument("--outside", action="store_true", help="allow a project folder that is not a direct child of the Developer folder")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_standard)

    p = sub.add_parser("events", help="the event log")
    p.add_argument("action", choices=("tail",))
    p.add_argument("-n", type=int, default=20)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_events)

    p = sub.add_parser("skills", help="skills: view PROJECT [--write] regenerates docs/SKILLS.md (dry run by default)")
    p.add_argument("action", choices=("view", "found", "approve", "remove", "ignore"),
                   help="view PROJECT; found [--short] (read only); approve NAME --why TEXT [--pack a,b]; ignore NAME --reason TEXT; remove NAME (asks y/N on a terminal). Owner commands only")
    p.add_argument("project", nargs="?", help="view: the project; approve/remove/ignore: the skill or NAME@MARKETPLACE plugin")
    p.add_argument("--short", action="store_true", help="found: one summary line")
    p.add_argument("--why", help="approve: why the owner approves it")
    p.add_argument("--pack", help="approve: comma list of packs (default global)")
    p.add_argument("--reason", help="ignore: why it stays unapproved (required)")
    p.add_argument("--write", action="store_true", help="replace the project's docs/SKILLS.md")
    p.add_argument("--mark-reviewed", action="store_true", help="set 'Skills review:' to today and record the stack (after the owner approved the review)")
    p.set_defaults(fn=cmd_skills)

    p = sub.add_parser("team", help="the project team table in docs/SKILLS.md: show [PROJECT]; check [PROJECT] (exit 0 clean, 1 problems, 3 warnings only; an unknown project is also exit 3 but prints a shipm: no project line on stderr); add AGENT --role R --why TEXT [--skills a,b] [PROJECT]")
    p.add_argument("action", choices=("show", "check", "add"))
    p.add_argument("rargs", nargs="*", help="add: AGENT then optional PROJECT; show/check: optional PROJECT (default: the project you are in)")
    p.add_argument("--role")
    p.add_argument("--why")
    p.add_argument("--skills", help="comma list of skill names")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_team)

    _bh = ("reference catalog (when the machine has one): show ID (read the item and its safety scan; writes nothing; nothing is copied); record ID --reason TEXT --as NAME [--dest PATH] [--project P] "
           "(after you wrote your OWN version, log it; a copy is refused); list [PROJECT]. Item id = <catalog>:<kind>:<name>; agents and skills only. Without a catalog the commands say so and exit 3")
    p = sub.add_parser("borrow", help=_bh, description=_bh)
    p.add_argument("action", choices=("show", "record", "list"))
    p.add_argument("rargs", nargs="*", help="show/record: the item id; list: optional PROJECT")
    p.add_argument("--reason", help="record: why this item was used (one line)")
    p.add_argument("--as", dest="as_name", help="record: the name of our own version")
    p.add_argument("--dest", help="record: where our version is, inside the project (default .claude/agents/NAME.md or .agents/skills/NAME)")
    p.add_argument("--project", help="record/list: the project (a chat can record only in its own)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_borrow)

    p = sub.add_parser("doctor", help="health rows in bin/doctor's format")
    p.add_argument("--rows", action="store_true")
    p.set_defaults(fn=cmd_doctor)

    p = sub.add_parser("tidy", help="read-only report: how a project folder compares with docs/standards/folders.md (rebuildable, throw-away, needs-a-decision, protected); nothing is moved or deleted")
    p.add_argument("project", nargs="?", help="folder path, or project name (a name that is also a path in the current folder is read as the path; default: the project you are in)")
    p.add_argument("--json", action="store_true", help="machine-readable")
    p.add_argument("--standard", action="store_true", help="only the suggestions against the folder standard")
    p.add_argument("--all", action="store_true", help="scan every project and print one summary line (sizes and counts only, no paths); writes nothing")
    p.add_argument("--write", action="store_true", help="like --all, and save the weekly history to <state>/v1/tidy.json (sizes and counts only)")
    p.add_argument("--weekly", action="store_true", help="like --all; do nothing when the newest complete scan is less than 6 days old")
    p.set_defaults(fn=lambda a: __import__("shipmiracle.tidy", fromlist=["x"]).run_cli(a))

    p = sub.add_parser("playbook", help="the project playbook (.shipmiracle/playbook.json): set KEY VALUE | set --from-draft, show, init --legacy [--apply], asset add|remove|list, interview [--short|--long] [--resume|--restart] (set/init/asset add|remove/interview are owner only)")
    p.add_argument("action", choices=("set", "show", "init", "asset", "interview"))
    p.add_argument("rargs", nargs="*", help="set KEY VALUE (keys: type, level, autopilot, lang, risk_paths, test_cmd, fast_lane) | asset add PATH --stage S --purpose T | asset remove PATH | asset list")
    p.add_argument("--stage", help="asset add: scope|plan|approve|do|verify|review|deliver")
    p.add_argument("--purpose", help="asset add: what the asset is for (1-120 characters)")
    p.add_argument("--short", action="store_true", help="interview: about 3 questions, 1-2 minutes (default)")
    p.add_argument("--long", dest="long_", action="store_true", help="interview: about 10 questions in up to 3 rounds; continues from the Short answers")
    p.add_argument("--resume", action="store_true", help="interview: continue a paused interview")
    p.add_argument("--restart", action="store_true", help="interview: throw away the saved answers and the draft, start over")
    p.add_argument("--report", action="store_true", help="interview: print how many finished change requests had a Short or a Long interview and their median rework rounds (read-only, local)")
    p.add_argument("--from-draft", dest="from_draft", action="store_true", help="set: apply the one change the interview's draft proposes (type / risk_paths), after you read it")
    p.add_argument("--project", help="a project name or folder (default: the current folder)")
    p.add_argument("--legacy", action="store_true", help="init: the migration of the existing projects")
    p.add_argument("--all", action="store_true", help="init --legacy: all 7 projects, in the migration order")
    p.add_argument("--apply", action="store_true", help="init: do it (default is a dry run)")
    p.add_argument("--force", action="store_true", help="init: overwrite a playbook.json that differs from the legacy values")
    p.add_argument("--allow-open-chat", dest="allow_open_chat", action="store_true", help="set: do not refuse because a chat is open in the project")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=lambda a: __import__("shipmiracle.playbook.cli", fromlist=["x"]).run_playbook(a))

    p = sub.add_parser("owner", help="owner check for the autopilot commands: status, mark-separate-account")
    p.add_argument("action", choices=("status", "mark-separate-account"))
    p.add_argument("--json", action="store_true")
    p.add_argument("--line", action="store_true", help="status: one doctor line, LEVEL and text")
    p.set_defaults(fn=lambda a: __import__("shipmiracle.autopilot.cli", fromlist=["x"]).run_owner(a))

    p = sub.add_parser("autopilot", help="full autopilot (owner only, software projects): charter set|show|clear, start, stop, allow H-xxxxxx, resume, drop CR-012, checkpoint, admit CR-015, show")
    p.add_argument("action", choices=("charter", "start", "stop", "allow", "resume", "drop", "show", "checkpoint", "admit", "probe"))
    p.add_argument("rargs", nargs="*", help="charter set|show|clear | allow H-xxxxxx | drop CR-012 | admit CR-015")
    p.add_argument("--project", help="a project name or folder (default: the current folder; the main checkout)")
    p.add_argument("--goal", help="charter set: what the run is for (1-200 characters)")
    p.add_argument("--scope", help="charter set: comma separated relative globs the run may change")
    p.add_argument("--budget", help="charter set: percent of the weekly budget, 1-25 (default 10)")
    p.add_argument("--time", help="charter set: 3h, 1.5h or 90m (multiples of 15 minutes, 0.25-8 h; default 3h)")
    p.add_argument("--deps", help="charter set: none (default) or comma separated package names")
    p.add_argument("--until", help="charter set: the word disabled = keep going until you disable it (24 h check-ins; no --time)")
    p.add_argument("--day", help="charter set --until disabled: percent of the week one 24 h segment may use, 1-10 (default 4)")
    p.add_argument("--crs-day", dest="crs_day", help="charter set --until disabled: requests started per 24 h, 1-5 (default 3)")
    p.add_argument("--lines", help="probe: the P6-1 sandbox lines that passed, like 1,2,3,4,5,6,7")
    p.add_argument("--ack-risk", dest="ack_risk", help="start: the line 'until I disable it' for a standing charter (tests only; in a terminal you type it)")
    p.add_argument("--ends", help="charter set: CR-012..CR-014 or CR-012,CR-015 (1-5 open or queued change requests)")
    p.add_argument("--yes", action="store_true", help="start: skip the typed yes (tests only)")
    p.add_argument("--ack", help="start: the charter id, for a chat-set charter (tests only; in a terminal you type it)")
    p.add_argument("--launch", action="store_true", help="start: also open the auto chat in the worktree (terminal only; without it the worktree is created and nothing is launched)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=lambda a: __import__("shipmiracle.autopilot.cli", fromlist=["x"]).run(a))

    p = sub.add_parser("cr", help="change requests: open TITLE | list | show [CR] [--next] | start CR | delta CR --from CR2 --reset-to scope|plan | render | abandon CR | advance CR --stage S --reason T")
    p.add_argument("action", choices=("open", "list", "show", "start", "delta", "render", "abandon", "advance"))
    p.add_argument("rargs", nargs="*", help="open TITLE | show [CR] | start|delta|abandon|advance CR")
    p.add_argument("--project", help="a project folder (default: the current folder)")
    p.add_argument("--lane", choices=("fast", "full"), help="open: the lane (default: the type's default)")
    p.add_argument("--next", action="store_true", help="show: print the next step of the active change request")
    p.add_argument("--from", dest="from_cr", metavar="CR", help="delta: the queued change request that changes CR")
    p.add_argument("--reset-to", dest="reset_to", choices=("scope", "plan"), help="delta: the stage CR goes back to")
    p.add_argument("--stage", help="advance: the stage the owner passes")
    p.add_argument("--reason", help="advance: why (required); abandon: why (optional)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=lambda a: __import__("shipmiracle.playbook.cli", fromlist=["x"]).cmd_cr(a))

    p = sub.add_parser("brief", help="the session brief of the active playbook/CR (prints nothing when the project has no .shipmiracle/work.json)")
    p.add_argument("--project", help="a project folder (default: the current folder)")
    p.set_defaults(fn=lambda a: __import__("shipmiracle.playbook.cli", fromlist=["x"]).cmd_brief(a))

    p = sub.add_parser("report", help="reports: lint FILE|--all, facts [CR], stage CR STAGE, cr CR, digest, panel, queue (--write stores the file)")
    p.add_argument("action", choices=("lint", "facts", "stage", "cr", "digest", "panel", "queue"))
    p.add_argument("rargs", nargs="*", help="lint FILE | facts [CR] | stage CR STAGE | cr CR")
    p.add_argument("--project", help="a project folder (default: the current folder)")
    p.add_argument("--all", action="store_true", help="lint: every report file we write")
    p.add_argument("--write", action="store_true", help="stage|cr|digest: write the file (default: print it)")
    p.add_argument("--day", help="digest: YYYY-MM-DD (default: today)")
    p.set_defaults(fn=lambda a: __import__("shipmiracle.report.cli", fromlist=["x"]).run(a))

    p = sub.add_parser("release-check", help="scan an export tree for secrets, personal values, private files; read-only (exit 0 pass, 1 findings, 3 no tree, 4 unsafe denylist)")
    p.add_argument("--tree", help="the folder to check")
    p.add_argument("--json", action="store_true", help="machine-readable result")
    p.add_argument("--require-denylist", action="store_true", help="FAIL when this machine has no denylist")
    p.add_argument("--no-denylist", action="store_true", help="skip the identifier check (CI)")
    p.add_argument("--require-gitleaks", action="store_true", help="FAIL when gitleaks is not installed")
    p.add_argument("--require-login", action="store_true", help="FAIL when the literal login placeholder (the word login in angle brackets) is still in a file (replace it with the GitHub login before the first export)")
    p.set_defaults(fn=lambda a: __import__("shipmiracle.release.cli", fromlist=["x"]).run_check(a))

    p = sub.add_parser("release", help="public export tooling: denylist [--refresh] [--show-hashes] (refresh is owner only) | export [--version X] [--dry-run] [--skip-tests] [--push --yes-publish] | project releases: status [--project P] [--json] (read-only) | mark X.Y [--date YYYY-MM-DD] [--push] [--project P] (owner only: tags vX.Y)")
    p.add_argument("action", choices=("denylist", "export", "status", "mark"))
    p.add_argument("rversion", nargs="?", metavar="X.Y", help="mark: the release version (digits and dots, at most four parts)")
    p.add_argument("--project", help="status|mark: a project name or folder (default: the current folder)")
    p.add_argument("--date", help="mark: tag the newest commit on or before this day, YYYY-MM-DD (default: HEAD)")
    p.add_argument("--json", action="store_true", help="status: machine-readable")
    p.add_argument("--version", help="export: the version to release (default release/VERSION; must equal it)")
    p.add_argument("--dry-run", action="store_true", dest="dry_run", help="export: build and check the stage, run no remote command (the default)")
    p.add_argument("--skip-tests", action="store_true", dest="skip_tests", help="export: do not run test-all in the stage (recorded; such a stage can never be pushed)")
    p.add_argument("--push", action="store_true", help="export: push the stage to the registered public-engine remote (owner terminal only; many gates); mark: push the tag (it stays local without this)")
    p.add_argument("--yes-publish", action="store_true", dest="yes_publish", help="export --push: explicit consent to publish")
    p.add_argument("--refresh", action="store_true", help="denylist: rebuild ~/.config/shipmiracle/release-denylist.txt from this Mac (values never printed)")
    p.add_argument("--show-hashes", action="store_true", help="denylist: print kind and salted hash only")
    p.add_argument("--include-generic", action="append", metavar="NAME", dest="include_generic", help="denylist --refresh: force-include a project name that refresh skipped as a common word (repeatable; owner decision)")
    p.set_defaults(fn=lambda a: (__import__("shipmiracle.report.release", fromlist=["x"]).run(a) if a.action in ("status", "mark")
                                 else __import__("shipmiracle.release.cli", fromlist=["x"]).run_release(a)))

    p = sub.add_parser("init", help="standard onboarding: Check, Quick setup (5 choices), Connect (what is missing); --check [--json] and --more are read-only; owner only, idempotent, resumable; --step/--skip/--undo ROW")
    p.add_argument("--check", action="store_true", help="read-only: show every row, write nothing, no owner check")
    p.add_argument("--json", action="store_true", help="--check: machine-readable {v:1, ready, rows:[...]}")
    p.add_argument("--step", help="run one row (id or number); the exit code then reflects only that row (0 ok, 1 failed)")
    p.add_argument("--skip", help="mark an optional row as skipped (id or number)")
    p.add_argument("--undo", help="reverse what init recorded for one optional row (id or number), e.g. remote-control or ask-inbox")
    p.add_argument("--yes", action="store_true", help="answer yes to the questions (folder create, extensions, GitHub login)")
    p.add_argument("--adopt", action="store_true", help="ask-inbox: take over an existing non-empty ~/Developer/ask folder (--yes alone refuses it)")
    p.add_argument("--prefs", action="store_true", help="ask the five quick-setup choices again (current answers in brackets); undo with --undo prefs")
    p.add_argument("--more", action="store_true", help="read-only: every row (the Advanced list), not just what needs you")
    p.add_argument("--lang", choices=("en", "ar"), help="--prefs: language for reports (no question is asked for a choice given here)")
    p.add_argument("--folder", help="--prefs: the projects folder (absolute or ~/...)")
    p.add_argument("--autonomy", choices=("normal", "step", "own"), help="--prefs: how much the team does by itself (own never turns full autopilot on)")
    p.add_argument("--awake", choices=("yes", "no"), help="--prefs: keep the computer awake while Claude works")
    p.add_argument("--notify", choices=("vscode", "system", "none"), help="--prefs: where notifications show")
    p.set_defaults(fn=lambda a: __import__("shipmiracle.setup.cli", fromlist=["x"]).run_init(a))

    p = sub.add_parser("uninstall", help="reverse what `shipm init` wrote, from the install manifest (dry run unless --apply; --purge also removes config and state)")
    p.add_argument("--apply", action="store_true", help="do it (default: show what would be reversed)")
    p.add_argument("--purge", action="store_true", help="with --apply: also remove ~/.config/shipmiracle and ~/.local/state/shipmiracle (typed confirmation)")
    p.add_argument("--confirm", help="the typed confirmation for --purge (the word PURGE) when there is no terminal")
    p.set_defaults(fn=lambda a: __import__("shipmiracle.setup.cli", fromlist=["x"]).run_uninstall(a))

    p = sub.add_parser("push-check", help="git pre-push guard: registry rules R1-R4 for a push (offline, read-only; ref lines on stdin; exit 1 refuses)")
    p.add_argument("remote", nargs="?", default="")
    p.add_argument("url", nargs="?", default="")
    p.set_defaults(fn=lambda a: __import__("shipmiracle.release.cli", fromlist=["x"]).run_push_check(a))

    p = sub.add_parser("ask", help='ask --inbox "question" (a tool-less answer as a note in the ask project), ask --list, ask promote NOTE (copy the question to the Inbox as an idea)')
    p.add_argument("rargs", nargs="*", help="the question, or: promote NOTE")
    p.add_argument("--inbox", action="store_true", help="write the answer as a note in the ask inbox project (needs `shipm init --step ask-inbox`)")
    p.add_argument("--model", help="--inbox: opus, sonnet or haiku for this question (default: config ask.model, opus)")
    p.add_argument("--project", help="only the value `ask` is accepted; per-project questions use /btw in the chat")
    p.add_argument("--list", action="store_true", dest="list_", help="list the notes (read-only, no owner needed)")
    p.add_argument("--json", action="store_true", help="--list: machine-readable")
    p.set_defaults(fn=lambda a: __import__("shipmiracle.ask", fromlist=["x"]).run_cli(a))

    sub.add_parser("idea", help="feature ideas (runs bin/idea with the same arguments)", add_help=False)
    sub.add_parser("bg", help="long job with a deadline (runs bin/shipm-bg with the same arguments)", add_help=False)
    if PRIVATE_TARGET.is_file():       # owner checkout only: the public export has no tools/private, so it has no `migrate`
        sub.add_parser("migrate", help="(owner machine, private) move this machine from the retired name: dry run unless --apply (runs tools/private/shipm-migrate)", add_help=False)
    return P


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        if argv and (argv[0] in EXEC_TOOLS or (argv[0] == "migrate" and (PRIVATE_TARGET.is_file() or os.environ.get("SHIPMIRACLE_TEST") == "1" and os.environ.get("SHIPMIRACLE_EXEC_MIGRATE")))):
            return _exec(argv[0], argv[1:])
        a, extra = build_parser().parse_known_args(argv)
        if extra:               # argparse cannot interleave optionals with a trailing positional list: leftover words join `rargs`
            if hasattr(a, "rargs") and not any(x.startswith("-") for x in extra):
                a.rargs = list(a.rargs or []) + extra
            else:
                raise UsageError("unrecognized arguments: %s" % " ".join(extra)[:200])
        return a.fn(a)
    except SystemExit as e:                      # --help (0); a non-int, non-None code is a failure
        return 0 if e.code is None else e.code if isinstance(e.code, int) and not isinstance(e.code, bool) else 1
    except ShipmiracleError as e:
        sys.stderr.write("shipm: %s\n" % e)
        return e.exit_code
    except BrokenPipeError:
        return 0
    except Exception as e:
        if os.environ.get("SHIPMIRACLE_TEST") == "1" and os.environ.get("SHIPMIRACLE_DEBUG") == "1":
            traceback.print_exc()
        sys.stderr.write("shipm: unexpected error (%s)\n" % type(e).__name__)
        return 1
