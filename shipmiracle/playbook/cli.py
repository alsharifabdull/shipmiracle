"""Command implementations of `shipm playbook`, `shipm cr` and `shipm brief` (shipmiracle/cli.py only parses and dispatches).

Owner-only (paths.require_owner): playbook set|init, cr abandon|advance. Anyone: playbook show, cr open|list|show|start|delta|render, brief.
Exit codes as the rest of shipm: 0 ok, 1 refused/failed check, 2 usage, 3 not found, 4 safety."""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from .. import ShipmiracleError, NotFound, SafetyError, UsageError
from .. import agents, events, paths, projects, registry, state, terminal
from . import config as pbconfig
from . import diffstat, engine, gate, store

# The migration table (project -> type, level, risk_paths, in the order they are migrated) is registry DATA from the private seed
# ("legacy_projects", applied by docs/owner-steps/p8-private-defaults.sh). A fresh install has none: `playbook init --legacy` then names nothing.
def legacy_table() -> dict:
    """{name: (type, level, risk_paths, keep_level)} in migration order; empty when the registry carries no legacy rows."""
    try:
        return {n: (t, lv, r, k) for n, t, lv, r, k in registry.legacy_table()}
    except Exception:
        return {}


SET_BY_SET, SET_BY_INIT = "shipm playbook set", "shipm playbook init"
KEYS = ("type", "level", "autopilot", "lang", "risk_paths", "test_cmd", "fast_lane")
_KEY_ALIASES = {"report.lang": "lang", "overrides.risk_paths": "risk_paths", "overrides.test_cmd": "test_cmd", "overrides.fast_lane": "fast_lane"}
NO_PLAYBOOK = "this project has no playbook yet: run `shipm playbook init --legacy --project <name> --apply` (owner, in a terminal) or `shipm playbook set type <type>`"


class PlaybookMissing(ShipmiracleError):
    exit_code = 1


def _out(text="") -> None:
    sys.stdout.write(text + "\n")


def _json(obj) -> None:
    _out(json.dumps(dict([("v", 1)] + list(obj.items())), ensure_ascii=False))


def _err(text) -> None:
    sys.stderr.write("shipm: %s\n" % text)


# ------------------------------------------------------------------ project resolution

def checkout(arg=None) -> str:
    """The git checkout (realpath) that `arg` (a folder, default the current one) belongs to; it must be one of the workspace projects
    (shipmiracle.projects decides). A worktree is its own checkout (its own log, WIP = 1)."""
    raw = arg if arg else os.getcwd()
    base = os.path.realpath(os.path.expanduser(raw))
    if not os.path.isdir(base):
        raise NotFound("%s is not a folder" % raw)
    rc, out = projects._run_git(projects.GIT_PREFIX + ["rev-parse", "--show-toplevel"], base)
    top = os.path.realpath(out.strip()) if rc == 0 and out.strip() else None
    if not top:
        raise NotFound("%s is not inside a git project" % raw)
    if projects.resolve(top) is None:
        raise NotFound("%s is not one of the workspace projects" % top)
    return top


def _project_arg(arg) -> str:
    """A project given as a name, id or folder (--project); no value = the current folder."""
    if arg and os.sep not in arg and not arg.startswith((".", "~")):
        try:
            return os.path.realpath(agents.project_for(arg).path)
        except NotFound:
            pass          # not a project name: maybe a folder relative to here
    return checkout(arg)


def _resolved(pd):
    p = projects.resolve(pd)
    if p is None:
        raise NotFound("%s is not one of the workspace projects" % pd)
    return p


def _refresh_health() -> None:
    """Like migrate-team: ask the watcher for a fresh health read before a write (never in tests)."""
    if os.environ.get("SHIPMIRACLE_TEST"):
        return
    watch = Path(__file__).resolve().parent.parent.parent / "bin" / "shipm-watch"
    if watch.is_file():
        try:
            subprocess.run([str(watch), "scan", "--dry"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
        except (OSError, subprocess.SubprocessError):
            pass


def _session_reason(name):
    """Why a write must wait (a chat is open or cannot be confirmed), or None. The same health read as `shipm project migrate-team`."""
    n = agents.chats_open(name)
    if n is None:
        return "the watcher gives no fresh chat state (run bin/shipm-watch scan), run again"
    if n > 0:
        return "%d chat(s) open (close them, then run again)" % n
    return None


# ------------------------------------------------------------------ typed owner confirmation (P5 security M5)

def _tty_ask(prompt):
    """Seam for tests. Reads one line from the controlling terminal (/dev/tty), never from stdin; None when there is no terminal."""
    try:
        return terminal.ask_line(prompt).strip()          # a text-mode r+ open of the tty raises "not seekable" on macOS 27
    except OSError:
        return None


def _origin() -> dict:
    """Where a state-changing owner command came from, recorded in the override line: tty yes/no, CLAUDECODE set."""
    tty = False
    try:
        tty = bool(sys.stdin is not None and sys.stdin.isatty())
    except (OSError, ValueError):
        pass
    return {"tty": tty, "chat": "CLAUDECODE" in os.environ}


def confirm_owner(what, expected) -> None:
    """A gate-changing action needs the owner at a terminal who types `expected` (the CR id, or the new value). Skipped non-interactively only in
    a fully temp sandbox (paths.sandboxed(), H1) unless SHIPMIRACLE_ENFORCE_OWNER=1 (the tests of this guard itself)."""
    if paths.sandboxed() and os.environ.get("SHIPMIRACLE_ENFORCE_OWNER") != "1":
        return
    typed = _tty_ask("%s: type %s to confirm: " % (what, expected))
    if typed is None:
        raise SafetyError("%s needs the owner at a terminal (it is never done from a script or a chat)" % what)
    if typed != str(expected):
        raise SafetyError("%s not done: what you typed is not %s" % (what, expected))


# ------------------------------------------------------------------ config/flow.json (the level, dual-written in P5)

def flow_path() -> Path:
    return paths.workspace_dir() / "config" / "flow.json"


def _ser(v) -> str:
    if isinstance(v, dict):
        return "{" + ", ".join("%s: %s" % (json.dumps(k, ensure_ascii=False), _ser(x)) for k, x in v.items()) + "}"
    return json.dumps(v, ensure_ascii=False)


def flow_set_level(name, to):
    """Write the level of `name` into config/flow.json with the rules of the panel's level action: only strict|warn (never off), a project
    that has the gate off is left to a hand edit, the default level is stored as 'no entry', atomic, same file mode, event level_changed.
    Returns (old_bytes_or_None, new_level_changed: bool). The workspace commit stays an owner action (this never commits)."""
    if to not in ("strict", "warn"):
        raise UsageError("the level can be set to strict or warn here, never off (edit config/flow.json by hand for that)")
    if not paths.ws_writable_for_tests():
        raise SafetyError("test run refused to write config/flow.json of the real workspace (SHIPMIRACLE_WS must be a temp folder)")
    fp = flow_path()
    try:
        raw = state.read_bytes_nofollow(fp)
        cfg = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError, ShipmiracleError):
        raise UsageError("config/flow.json is missing or malformed. Fix it by hand.")
    lv = ("strict", "warn", "off")
    if not isinstance(cfg, dict) or cfg.get("default") not in lv or ("projects" in cfg and not isinstance(cfg["projects"], dict)):
        raise UsageError("config/flow.json is missing or malformed. Fix it by hand.")
    projs = dict(cfg.get("projects") or {})
    frm = projs.get(name) if projs.get(name) in lv else cfg["default"]
    if frm == "off":
        raise UsageError("%s has the gate off: set its level by hand in config/flow.json" % name)
    if frm == to:
        return raw, False
    if to == cfg["default"]:
        projs.pop(name, None)
    else:
        projs[name] = to
    out = dict(cfg)
    out["projects"] = projs
    body = "{\n" + ",\n".join("  %s: %s" % (json.dumps(k, ensure_ascii=False), _ser(v)) for k, v in out.items()) + "\n}\n"
    try:
        mode = os.stat(fp).st_mode & 0o777
    except OSError:
        mode = 0o644
    state.atomic_write(fp, body.encode("utf-8"), mode)
    try:
        sd = paths.state_dir()
        sd.mkdir(parents=True, exist_ok=True)
        with open(str(sd / "flow-events.jsonl"), "a") as f:
            f.write(json.dumps({"ts": int(time.time()), "project": name, "event": "level_changed", "by": "owner-cli", "from": frm, "to": to}) + "\n")
    except OSError:
        pass          # the file change stands
    return raw, True


def _flow_restore(raw):
    if raw is not None:
        try:
            state.atomic_write(flow_path(), raw, 0o644)
        except Exception:
            pass


# ------------------------------------------------------------------ playbook.json writer (shared by set and init)

def _ensure_shipmiracle(pd) -> Path:
    d = Path(pd) / ".shipmiracle"
    try:
        st = os.lstat(d)
    except FileNotFoundError:
        os.mkdir(d, 0o755)
        return d
    if os.path.islink(d) or not os.path.isdir(d):
        raise SafetyError(".shipmiracle is a symlink or not a folder")
    return d


def _pb_path(pd) -> Path:
    return Path(pd) / ".shipmiracle" / "playbook.json"


def _pb_bytes(norm) -> bytes:
    b = (json.dumps(norm, indent=1, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    cap = pbconfig.MAX_BYTES_ASSETS if norm.get("assets") else pbconfig.MAX_BYTES
    if len(b) > cap:
        raise UsageError("playbook.json would be larger than %d bytes" % cap)
    return b


def _read_pb(pd):
    try:
        return state.read_bytes_nofollow(_pb_path(pd))
    except FileNotFoundError:
        return None


def _core(norm) -> dict:
    return {k: v for k, v in norm.items() if k not in ("ts", "set_by")}


def _write_registry(p, norm):
    """Registry snapshot (the trust anchor). An entry that does not exist yet is created first (like migrate-team)."""
    paths.require_owner("shipm playbook")
    if registry.entry(p.id) is None:
        registry.sync([p])
    store.registry_snapshot_write(p.path, pbconfig.snapshot_of(norm))


def _commit(pd, rels, message) -> bool:
    return agents._commit(pd, rels, message)


# ------------------------------------------------------------------ shipm playbook

def _parse_value(key, value):
    if key in ("type", "autopilot", "lang", "level"):
        return value
    if key == "risk_paths":
        s = value.strip()
        if s in ("-", "none", ""):
            return None
        if s.startswith("["):
            try:
                return json.loads(s)
            except ValueError:
                raise UsageError("risk_paths: expected a JSON list or comma-separated globs")
        return [x.strip() for x in s.split(",") if x.strip()]
    if key == "fast_lane":
        s = value.strip()
        if s in ("-", "none"):
            return None
        try:
            return json.loads(s)
        except ValueError:
            raise UsageError('fast_lane: expected JSON like {"max_files":3,"max_lines":50}')
    if key == "test_cmd":
        return None if value.strip() in ("-", "none") else value
    raise UsageError("unknown key")


def _apply_key(base, key, val):
    d = json.loads(json.dumps(base))
    d.pop("ts", None)
    d.pop("set_by", None)
    ov = d.setdefault("overrides", {})
    if key in ("type", "autopilot", "level"):
        d[key] = val
    elif key == "lang":
        d["report"] = {"lang": val}
    else:
        if val is None:
            ov.pop(key, None)
        else:
            ov[key] = val
    return d


def _show_cfg_line(norm) -> str:
    return "%s · %s · %s" % (norm["type"], norm["level"], norm["autopilot"])


def cmd_set_from_draft(a) -> int:
    """`shipm playbook set --from-draft`: apply the ONE change the interview's draft proposes (type and/or risk_paths), after the owner read it. Owner at a terminal, typed `set`."""
    from . import interview
    paths.require_owner("shipm playbook set --from-draft")
    pd = _project_arg(a.project)
    p = _resolved(pd)
    st = interview.load(pd)
    _text, prop = interview.read_draft(pd, st)
    if not prop:
        raise UsageError("the draft proposes no change to the playbook (it stays a description to read)")
    entry = store.registry_entry(pd)
    cfg, trust, _reason = pbconfig.load_trusted(pd, entry or {})
    base = cfg if cfg is not None else dict(pbconfig.defaults(), level=gate.flow_level(pd))
    d = json.loads(json.dumps(base))
    d.pop("ts", None)
    d.pop("set_by", None)
    if "type" in prop:
        d["type"] = prop["type"]
    if "risk_paths" in prop:
        d.setdefault("overrides", {})["risk_paths"] = prop["risk_paths"]
    new = pbconfig.validate(d, pd)
    if cfg is not None and _core(new) == _core(cfg) and trust == pbconfig.TRUSTED:
        _out("unchanged: the playbook already has what the draft proposes")
        interview.mark_done(pd)
        return 0
    _out("The draft proposes:")
    if "type" in prop:
        _out("  type: %s -> %s" % ((cfg or {}).get("type", "(none)"), new["type"]))
    if "risk_paths" in prop:
        _out("  risk_paths: %s -> %s" % (json.dumps(((cfg or {}).get("overrides") or {}).get("risk_paths")), json.dumps(new["overrides"]["risk_paths"])))
    confirm_owner("shipm playbook set --from-draft", "set")
    if not a.allow_open_chat:
        _refresh_health()
        why = _session_reason(p.name)
        if why:
            raise SafetyError("%s: %s (or --allow-open-chat)" % (p.name, why))
    new = pbconfig.validate(dict(new, set_by="shipm playbook set --from-draft", ts=int(time.time())), pd)
    rc = _asset_save(pd, p, new, _read_pb(pd), "shipm: playbook (from interview draft)")
    interview.mark_done(pd)
    return rc


def cmd_interview(a) -> int:
    if getattr(a, "report", False):
        from . import measure
        if a.short or a.long_ or a.resume or a.restart:
            raise UsageError("interview --report only prints the numbers; it takes no other interview option")
        summ = measure.summary()
        if a.json:
            _json(dict(summ, evidence=summ["modes"]["short"]["n"] >= measure.EVIDENCE_N and summ["modes"]["long"]["n"] >= measure.EVIDENCE_N))
        else:
            _out(measure.render(summ))
        return 0
    from . import interview
    if a.short and a.long_:
        raise UsageError("choose --short or --long, not both")
    pd = _project_arg(a.project)
    _resolved(pd)
    name = os.path.basename(pd)
    mode = "long" if a.long_ else "short"
    r = interview.run(pd, name, mode, resume=a.resume, restart=a.restart)
    return 0 if r["status"] == "draft" else 1


def cmd_set(a) -> int:
    if getattr(a, "from_draft", False):
        return cmd_set_from_draft(a)
    paths.require_owner("shipm playbook set")
    ra = list(a.rargs or [])
    if len(ra) != 2:
        raise UsageError("playbook set needs KEY VALUE (keys: %s)" % ", ".join(KEYS))
    key = _KEY_ALIASES.get(ra[0], ra[0])
    if key not in KEYS:
        raise UsageError("unknown key %r (keys: %s)" % (ra[0][:40], ", ".join(KEYS)))
    pd = _project_arg(a.project)
    p = _resolved(pd)
    name = os.path.basename(pd)
    val = _parse_value(key, ra[1])
    if key == "level" and val not in ("strict", "warn"):
        raise UsageError("level: strict or warn (off is never set from here: edit config/flow.json by hand)")
    entry = store.registry_entry(pd)
    cfg, trust, _reason = pbconfig.load_trusted(pd, entry or {})
    if cfg is None:
        if key != "type":
            raise PlaybookMissing("the project has no playbook: set the type first (`shipm playbook set type software`) or run `shipm playbook init --legacy`")
        base = dict(pbconfig.defaults(), level=gate.flow_level(pd))
    else:
        base = cfg
    new = pbconfig.validate(_apply_key(base, key, val), pd)
    cur_flow = gate.flow_level(pd)
    changed = (cfg is None) or _core(new) != _core(cfg) or trust != pbconfig.TRUSTED or (key == "level" and cur_flow != new["level"])
    if not changed:
        _out("unchanged: %s = %s (%s)" % (key, ra[1], _show_cfg_line(new)))
        return 0
    if key in ("level", "autopilot"):
        confirm_owner("shipm playbook set %s" % key, val)
    if not a.allow_open_chat:
        _refresh_health()
        why = _session_reason(p.name)
        if why:
            raise SafetyError("%s: %s (or --allow-open-chat)" % (p.name, why))
    now = int(time.time())
    new = pbconfig.validate(dict(new, set_by=SET_BY_SET, ts=now), pd)
    if key in ("level", "autopilot"):
        events.emit("playbook.set", dict(_origin(), key=key, value=str(val)[:20]), project=name, src="shipmiracle")
    data = _pb_bytes(new)
    old_pb, old_flow, flow_changed = _read_pb(pd), None, False
    created_dir, wrote = not (Path(pd) / ".shipmiracle").exists(), False
    try:
        if key == "level":
            old_flow, flow_changed = flow_set_level(name, new["level"])
        _ensure_shipmiracle(pd)
        state.atomic_write(_pb_path(pd), data, 0o644)
        wrote = True
        _write_registry(p, new)
    except BaseException:
        if flow_changed:
            _flow_restore(old_flow)
        try:
            if wrote and old_pb is None:
                os.unlink(_pb_path(pd))
                if created_dir:
                    os.rmdir(Path(pd) / ".shipmiracle")
            elif wrote:
                state.atomic_write(_pb_path(pd), old_pb, 0o644)
        except OSError:
            pass
        raise
    _out("playbook %s = %s (%s)" % (key, ra[1], _show_cfg_line(new)))
    if flow_changed:
        _out("config/flow.json updated (level %s); not committed: commit it in the workspace repo" % new["level"])
    try:
        done = _commit(pd, [".shipmiracle/playbook.json"], "shipm: playbook (%s)" % key)
    except ShipmiracleError as e:
        _err("saved, not committed: %s" % e)
        return 1
    _out("committed .shipmiracle/playbook.json" if done else "nothing to commit")
    return 0


def cmd_show(a) -> int:
    pd = _project_arg(a.project)
    entry = store.registry_entry(pd)
    cfg, trust, reason = pbconfig.load_trusted(pd, entry or {})
    raw = _read_pb(pd)
    level = gate.flow_level(pd)
    sha = None
    if cfg is not None:
        try:
            sha = pbconfig.digest(cfg)
        except Exception:
            sha = None
    if a.json:
        _json({"project": os.path.basename(pd), "trust": trust, "reason": reason, "config": cfg, "file": raw is not None, "sha256": sha,
               "flow_level": level})
        return 0
    _out("Project: %s" % os.path.basename(pd))
    if cfg is None:
        _out("Playbook: none (%s)" % reason)
        _out("Trust: none")
        _out("Level (config/flow.json): %s" % level)
        return 0
    _out("Playbook: %s" % _show_cfg_line(cfg))
    _out("Trust: %s (%s)" % (trust, reason))
    _out("Level (config/flow.json): %s" % level)
    ov = cfg.get("overrides") or {}
    _out("Overrides: %s" % (", ".join("%s=%s" % (k, json.dumps(v, ensure_ascii=False)) for k, v in sorted(ov.items())) or "none"))
    _out("Report language: %s" % cfg["report"]["lang"])
    _out("File: .shipmiracle/playbook.json %s" % ("present" if raw is not None else "absent (registry snapshot in use)"))
    return 0


def _legacy_names(a):
    table = legacy_table()
    if a.all:
        have = {pr.name: pr for pr in projects.list_projects()}
        return [(n, have.get(n), table) for n in table]
    if not a.project:
        raise UsageError("playbook init --legacy needs --project NAME or --all")
    p = agents.project_for(a.project)
    if p.name not in table:
        raise UsageError("no legacy mapping for %s (known: %s); use `shipm playbook set type ...`" % (p.name, ", ".join(table) or "none: the private seed has no legacy_projects"))
    return [(p.name, p, table)]


def _desired(name, p, now, table):
    typ, level, risk, keep = table[name]
    note = ""
    flow = gate.flow_level(p.real)
    if (not keep or flow == "off") and flow != level:
        level, note = flow, "level follows config/flow.json (%s)" % flow
    ov = {"risk_paths": list(risk)} if risk else {}
    norm = pbconfig.validate({"v": 1, "type": typ, "level": level, "autopilot": "guided", "overrides": ov, "set_by": SET_BY_INIT, "ts": now}, p.real)
    return norm, note


def _text_diff(old: bytes, new: bytes, name):
    return "".join(difflib.unified_diff(old.decode("utf-8", "replace").splitlines(True), new.decode("utf-8", "replace").splitlines(True),
                                        "%s/.shipmiracle/playbook.json (existing)" % name, "%s/.shipmiracle/playbook.json (legacy)" % name))


def cmd_init(a) -> int:
    paths.require_owner("shipm playbook init")
    if not a.legacy:
        raise UsageError("playbook init needs --legacy (the migration of the existing projects)")
    todo = _legacy_names(a)
    now = int(time.time())
    if a.apply:
        _refresh_health()
    _out("%s" % ("APPLY" if a.apply else "dry run (add --apply to change anything)"))
    _out("%-24s %-9s %-7s %-8s %s" % ("project", "type", "level", "autopilot", "risk_paths / action"))
    rc = 0
    for name, p, table in todo:
        typ, lvl0, risk, _keep = table[name]
        if p is None:
            _out("%-24s %-9s %-7s %-8s not found: skipped" % (name, typ, lvl0, "guided"))
            continue
        norm, note = _desired(name, p, now, table)
        data = _pb_bytes(norm)
        old = _read_pb(p.real)
        entry = store.registry_entry(p.real) or {}
        equal, cur = False, None
        if old is not None:
            try:
                cur = pbconfig.parse(old, p.real)
                equal = _core(cur) == _core(norm)
            except UsageError:
                equal = False
        eff = cur if equal else norm                       # what the registry must hold: the file as it is (its ts is part of the sha)
        reg_ok = isinstance(entry.get("playbook"), dict) and entry["playbook"].get("sha256") == pbconfig.digest(eff)
        flow_cur = gate.flow_level(p.real)
        need_flow = norm["level"] != flow_cur and norm["level"] in ("strict", "warn")
        wj = Path(p.real) / ".shipmiracle" / "work.json"
        rk = ",".join(norm["overrides"].get("risk_paths", [])) or "-"
        if old is not None and not equal:
            action = "differs from the legacy values: skipped" + ("" if a.force else " (--force overwrites)")
            if a.force:
                action = "would overwrite" if not a.apply else "overwritten"
        elif old is None:
            action = "would write" if not a.apply else "written"
        else:
            action = "ok" if reg_ok and wj.exists() else "would repair registry/work.json" if not a.apply else "repaired"
        if note:
            action += " · " + note
        if need_flow:
            action += " · flow.json %s -> %s" % (flow_cur, norm["level"])
        row = "%-24s %-9s %-7s %-8s %s · %s" % (name, norm["type"], norm["level"], norm["autopilot"], rk, action)
        will_write = a.apply and not (old is not None and not equal and not a.force) and not (old is not None and equal and reg_ok and wj.exists())
        if not will_write:
            _out(row)                                      # nothing is written for this project: the row is the whole answer
        if old is not None and not equal:
            _out(_text_diff(_pb_bytes(_core(cur)) if cur is not None else old, _pb_bytes(_core(norm)), name).rstrip("\n"))
            if not a.force:
                rc = 1 if a.apply else rc
                continue
        if not a.apply:
            continue
        if old is not None and equal and reg_ok and wj.exists():
            continue
        why = _session_reason(p.name)
        if why:
            _out("  SKIPPED %s: %s" % (name, why))
            rc = 1
            continue
        why = agents._git_guard(p.real)
        if why:
            _out("  SKIPPED %s: %s" % (name, why))
            rc = 1
            continue
        old_flow, flow_changed, made_work, wrote = None, False, False, False
        created_dir = not (Path(p.real) / ".shipmiracle").exists()
        try:
            if need_flow:
                old_flow, flow_changed = flow_set_level(name, norm["level"])
            _ensure_shipmiracle(p.real)
            if old is None or not equal:
                state.atomic_write(_pb_path(p.real), data, 0o644)
                wrote = True
            if not wj.exists():
                w = engine.new_work()
                w["project"] = name
                body = store.render_bytes(w)
                state.atomic_write(wj, body, 0o644)
                made_work = True                         # TOUCH-T2: also the render sha, so the engine's first render is not reported as forged
                store.cr_dir()
                state.atomic_write(store._rendered_path(store.pid_of(p.real), None), (hashlib.sha256(body).hexdigest() + "\n").encode("ascii"), 0o600)
            _write_registry(p, eff)
        except BaseException:
            if flow_changed:
                _flow_restore(old_flow)
            try:
                if wrote and old is None:
                    os.unlink(_pb_path(p.real))
                elif wrote:
                    state.atomic_write(_pb_path(p.real), old, 0o644)
                if made_work:
                    os.unlink(wj)
                if created_dir:
                    os.rmdir(Path(p.real) / ".shipmiracle")
            except OSError:
                pass
            raise
        _out(row)                                          # only now: a skipped project prints its SKIPPED line instead of a "written" row
        if flow_changed:
            _out("  config/flow.json updated (%s %s); not committed: commit it in the workspace repo" % (name, norm["level"]))
        try:
            done = _commit(p.real, [".shipmiracle"], "shipm: playbook (legacy migration)")
        except ShipmiracleError as e:
            _out("  saved, not committed: %s" % e)
            rc = 1
            continue
        _out("  committed .shipmiracle/" if done else "  nothing to commit")
    return rc


# ------------------------------------------------------------------ shipm playbook asset (F5 toolbox)

def _asset_base(pd):
    """The effective, trusted config to extend. A playbook that is missing, or whose file does not match the registry sha, is refused (the owner re-trusts it
    with `shipm playbook set` first), so an asset is never signed into a file the registry does not vouch for."""
    entry = store.registry_entry(pd)
    cfg, trust, reason = pbconfig.load_trusted(pd, entry or {})
    if cfg is None:
        raise PlaybookMissing("the project has no playbook: set the type first (`shipm playbook set type software`)")
    if trust not in (pbconfig.TRUSTED, pbconfig.SNAPSHOT):
        raise SafetyError("the playbook is not trusted (%s): run `shipm playbook show`, then `shipm playbook set ...` to trust it again before signing assets" % reason)
    return cfg, trust


def _asset_save(pd, p, new, old_pb, message):
    """Write playbook.json and the registry snapshot together (the guarded writer: state.atomic_write refuses symlinks and non-files); undo the file when the registry write fails."""
    created_dir, wrote = not (Path(pd) / ".shipmiracle").exists(), False
    data = _pb_bytes(new)
    try:
        _ensure_shipmiracle(pd)
        state.atomic_write(_pb_path(pd), data, 0o644)
        wrote = True
        _write_registry(p, new)
    except BaseException:
        try:
            if wrote and old_pb is None:
                os.unlink(_pb_path(pd))
                if created_dir:
                    os.rmdir(Path(pd) / ".shipmiracle")
            elif wrote:
                state.atomic_write(_pb_path(pd), old_pb, 0o644)
        except OSError:
            pass
        raise
    try:
        done = _commit(pd, [".shipmiracle/playbook.json"], message)
    except ShipmiracleError as e:
        _err("saved, not committed: %s" % e)
        return 1
    _out("committed .shipmiracle/playbook.json" if done else "nothing to commit")
    return 0


def cmd_asset(a) -> int:
    from . import assets as pbassets
    ra = list(a.rargs or [])
    sub = ra[0] if ra else None
    if sub not in ("add", "remove", "list"):
        raise UsageError("playbook asset needs add PATH --stage S --purpose TEXT | remove PATH | list [--json]")
    pd = _project_arg(a.project)
    p = _resolved(pd)
    if sub == "list":
        entry = store.registry_entry(pd)
        cfg, trust, reason = pbconfig.load_trusted(pd, entry or {})
        labels = None
        try:
            labels = (gate.stage_rules(pd) or {}).get("labels")
        except Exception:
            labels = None
        lst = pbassets.listing(pd, cfg, labels)
        if a.json:
            _json(dict(project=os.path.basename(pd), trust=trust, **lst))
        else:
            if not lst["assets"]:
                _out("no assets yet")
            for r in lst["assets"]:
                _out("%-8s %-9s %s\t%s" % (r["status"], r["stage"], r["path"], r["purpose"]))
        return 0
    paths.require_owner("shipm playbook asset %s" % sub)
    if len(ra) != 2:
        raise UsageError("playbook asset %s needs one PATH" % sub)
    cfg, _trust = _asset_base(pd)
    if not a.allow_open_chat:
        _refresh_health()
        why = _session_reason(p.name)
        if why:
            raise SafetyError("%s: %s (or --allow-open-chat)" % (p.name, why))
    old_pb = _read_pb(pd)
    now = int(time.time())
    if sub == "add":
        if not a.stage or a.purpose is None:
            raise UsageError("playbook asset add needs --stage S (%s) and --purpose TEXT" % ", ".join(pbconfig.ASSET_STAGES))
        rel = pbassets.check_path(pd, ra[1])
        purpose = " ".join(a.purpose.split())
        sha = pbassets.sha_of(pd, rel)
        if sha is None:
            raise UsageError("asset path: cannot read %s (a file of at most %d KB)" % (rel[:60], pbassets.MAX_FILE // 1024))
        entry = {"path": rel, "sha256": sha, "purpose": purpose, "stage": a.stage}
        new = pbconfig.validate(dict(pbassets.with_asset(_core(cfg), entry), set_by="shipm playbook asset", ts=now), pd)
        old = next((x for x in (cfg.get("assets") or []) if x["path"] == rel), None)
        if old is not None and old == entry:
            _out("unchanged: %s is already signed off (%s)" % (rel, sha[:12]))
            return 0
        _out("%s %s\n  stage: %s\n  purpose: %s\n  sha256: %s" % ("re-sign" if old else "add", rel, a.stage, purpose, sha))
        confirm_owner("shipm playbook asset add", rel)
        events.emit("playbook.asset", dict(_origin(), op="resign" if old else "add", path=rel[:80], stage=a.stage), project=os.path.basename(pd), src="shipmiracle")
        _out("asset %s: %s" % ("re-signed" if old else "added", rel))
        return _asset_save(pd, p, new, old_pb, "shipm: playbook asset %s" % ("re-sign" if old else "add"))
    rel = os.path.normpath(ra[1].strip()).replace(os.sep, "/")
    newc, had = pbassets.without_asset(cfg, rel)
    if not had:
        raise NotFound("%s is not in the toolbox" % rel[:60])
    new = pbconfig.validate(dict(_core(newc), set_by="shipm playbook asset", ts=now), pd)
    _out("remove %s" % rel)
    confirm_owner("shipm playbook asset remove", rel)
    events.emit("playbook.asset", dict(_origin(), op="remove", path=rel[:80]), project=os.path.basename(pd), src="shipmiracle")
    _out("asset removed: %s" % rel)
    return _asset_save(pd, p, new, old_pb, "shipm: playbook asset remove")


def run_playbook(a) -> int:
    if a.action == "interview":
        return cmd_interview(a)
    if a.action == "asset":
        return cmd_asset(a)
    if a.action == "set":
        return cmd_set(a)
    if a.action == "show":
        return cmd_show(a)
    if a.action == "init":
        return cmd_init(a)
    raise UsageError("unknown playbook action")


# ------------------------------------------------------------------ shipm cr

def _rules_for_write(pd):
    rules = gate.stage_rules(pd)
    if rules is None:
        raise PlaybookMissing(NO_PLAYBOOK)
    if rules["trust"] == pbconfig.UNTRUSTED:
        raise SafetyError("the playbook is not trusted (%s); the owner must run `shipm playbook set` to accept it" % rules["reason"])
    return rules


def _pub(cr) -> dict:
    return {k: cr[k] for k in engine._PUBLIC if k in cr}


def _label(rules, stage):
    if stage in (None, "done"):
        return stage or "-"
    return engine._label(rules, stage) if rules else stage.capitalize()


def _impact(work, cr, rules) -> str:
    act = engine.get_cr(work, work["active"])
    planner = ((rules.get("agents") or {}).get("plan")) or "planner"
    return ("%s queued behind %s (at %s). Impact check: ask %s whether %s changes %s's scope or plan (brief: both titles, %s's plan, "
            "`git diff --stat`). If it does, run `shipm cr delta %s --from %s --reset-to plan` (the owner approves the new plan). "
            "If not, leave it queued." % (cr["id"], act["id"], _label(rules, act["stage"]), planner, cr["id"], act["id"], act["id"], act["id"], cr["id"]))


def _title(raw):
    t = engine._clean_text(raw, 120) if isinstance(raw, str) else ""
    if not t:
        raise UsageError('cr open needs a title: shipm cr open "what to change"')
    return t


def _ev(kind, now, **data):
    return {"kind": kind, "by": "cli", "ts": now, "data": data}


def _stdin_title() -> str:
    try:
        if sys.stdin is None or sys.stdin.isatty():
            raise UsageError("cr open - reads the title from standard input (pipe it in or use a heredoc)")
        return " ".join(sys.stdin.read(4096).split())
    except (OSError, ValueError):
        raise UsageError("cannot read the title from standard input")


def _cr_id(ra, what):
    if len(ra) != 1 or not re.fullmatch(r"CR-\d{3,6}", ra[0]):
        raise UsageError("%s needs a change request id like CR-012" % what)
    return ra[0]


def _show_text(cr, rules, na):
    L = lambda s: _label(rules, s)      # noqa: E731
    at = L(cr["stage"])
    if cr["stage"] == "verify":
        at += " (attempt %d of 2)" % (cr["verify_fails"] + 1)
    lines = ['%s  "%s"' % (cr["id"], cr["title"]),
             "Status: %s · %s lane · at %s%s" % (cr["status"], cr["lane"], at, " · blocked: %s" % cr["blocked"] if cr.get("blocked") else ""),
             "Stages: " + " · ".join("%s %s" % (L(s), v) for s, v in cr["stages"].items())]
    d = cr.get("diff") or {}
    lines.append("Diff: %s files, %s lines%s%s" % (d.get("files", 0), d.get("lines", 0), " · risk path" if d.get("risk") else "", " · dependency file" if d.get("deps") else ""))
    if cr.get("deltas"):
        lines.append("Deltas: " + ", ".join(str(x) for x in cr["deltas"]))
    if na and na["cr"] == cr["id"]:
        lines.append("Next: " + na["text"])
    return "\n".join(lines)


def _refuse_in_auto_worktree(pd) -> None:
    """`shipm cr open` inside the auto worktree of a standing ("until I disable it") run: refused, and the run pauses with unknown_request. Other
    runs and ordinary projects are unaffected."""
    try:
        from ..autopilot import standing
        r = standing.refuse_open_in_worktree(pd)
    except UsageError:
        raise
    except Exception:
        return
    if r:
        raise UsageError(r)


def cmd_cr(a) -> int:
    act, ra = a.action, list(a.rargs or [])
    pd = _project_arg(a.project)
    now = int(time.time())
    if act == "open":
        if ra == ["-"]:
            title = _title(_stdin_title())                 # /feature passes the request on stdin in a quoted heredoc: no shell quoting of owner text
        else:
            title = _title(" ".join(ra) if ra else "")
        _refuse_in_auto_worktree(pd)                       # option C: a request opened INSIDE the auto worktree is refused and pauses the run (unknown_request)
        rules = _rules_for_write(pd)
        snap = diffstat.snapshot(pd)                       # the diff base is taken first and saved with the CR

        def fn(work):
            cr, trs = engine.open_cr(work, title, "owner" if "CLAUDECODE" not in os.environ else "chat", now, lane=a.lane, base=snap["base"],
                                     rules=rules, kind="cli_open", in_chat="CLAUDECODE" in os.environ)
            store.save_snapshot(pd, cr["id"], snap)
            queued = cr["status"] == "queued"
            return {"cr": _pub(cr), "queued": queued, "impact": _impact(work, cr, rules) if queued else None,
                    "next": engine.next_action(work, rules)}, trs
        r = store.transact(pd, fn)
        if a.json:
            _json(r)
        elif r["queued"]:
            _out(r["impact"])
        else:
            c = r["cr"]
            _out('%s opened: "%s" · %s lane · active' % (c["id"], c["title"], c["lane"]))
            _out(r["next"]["text"])
        return 0
    if act in ("list", "show"):
        work = store.load(pd)
        rules = gate.stage_rules(pd)
        if act == "list":
            rd = engine.render(work)
            if a.json:
                _json({"project": rd["project"], "active": rd["active"], "queue": rd["queue"], "crs": rd["crs"], "updated": rd["updated"]})
                return 0
            if not rd["crs"]:
                _out("No change requests.")
                return 0
            for c in rd["crs"]:
                _out("%-8s %-10s %-10s %-5s %s" % (c["id"], c["status"], _label(rules, c["stage"]) if c["status"] in ("open", "blocked") else "-", c["lane"], c["title"]))
            return 0
        na = engine.next_action(work, rules) if rules else None
        if a.next:
            if rules is None:
                raise PlaybookMissing(NO_PLAYBOOK)
            if ra and ra[0] != work.get("active"):
                raise UsageError("--next describes the active change request (%s)" % (work.get("active") or "none"))
            tb_stage, tb_items, tb_line = None, [], ""
            try:
                from . import toolbox
                act_cr = engine.active_cr(work)
                if act_cr is not None and act_cr["status"] == "open" and rules.get("assets"):
                    tb_stage = "do" if act_cr["stage"] == "verify" and act_cr.get("need_build") else act_cr["stage"]
                    tb_items = toolbox.brief_items(pd, rules, tb_stage)
                    tb_line = toolbox.brief_text(pd, rules, tb_stage, _label(rules, tb_stage))
            except Exception:
                tb_items, tb_line = [], ""
            if a.json:
                _json({"next": dict(na, toolbox=tb_items) if tb_items else na})
            else:
                _out(na["text"])
                if tb_line:
                    _out(tb_line)
            return 0
        if ra:
            cid = _cr_id(ra, "cr show")
            cr = engine.get_cr(work, cid)
        else:
            cr = engine.active_cr(work) or (engine.get_cr(work, work["queue"][0]) if work["queue"] else None) or (work["crs"][-1] if work["crs"] else None)
            if cr is None:
                raise NotFound("no change requests yet (shipm cr open \"...\")")
        if cr is None:
            raise NotFound("no such change request")
        if a.json:
            _json({"cr": _pub(cr), "next": na})
        else:
            _out(_show_text(cr, rules, na))
        return 0
    if act == "render":
        store.render(pd)
        n = store.compact(pd, now)
        w = store.load(pd)
        if a.json:
            _json({"rendered": True, "crs": len(w["crs"]), "compacted": n})
        else:
            _out("rendered .shipmiracle/work.json (%d change request(s)); compacted %d" % (len(w["crs"]), n))
        return 0
    if act == "start":
        cid = _cr_id(ra, "cr start")
        rules = _rules_for_write(pd)

        def fn(work):
            trs = engine.start(work, cid, _ev("cli_start", now), rules)
            return engine.next_action(work, rules), trs
        na = store.transact(pd, fn)
        if a.json:
            _json({"cr": cid, "next": na})
        else:
            _out("%s started." % cid)
            _out(na["text"])
        return 0
    if act == "delta":
        cid = _cr_id(ra, "cr delta")
        if not a.from_cr or not re.fullmatch(r"CR-\d{3,6}", a.from_cr) or a.reset_to not in ("scope", "plan"):
            raise UsageError("cr delta needs CR --from CR2 --reset-to scope|plan")
        rules = _rules_for_write(pd)

        def fn(work):
            trs = engine.reset_after_delta(work, cid, a.reset_to, a.from_cr, _ev("cli_delta", now, **{"from": a.from_cr}))
            return engine.next_action(work, rules), trs
        na = store.transact(pd, fn)
        if a.json:
            _json({"cr": cid, "merged": a.from_cr, "reset_to": a.reset_to, "next": na})
        else:
            _out("%s merged into %s; %s goes back to %s." % (a.from_cr, cid, cid, _label(rules, a.reset_to)))
            _out(na["text"])
        return 0
    if act == "abandon":
        paths.require_owner("shipm cr abandon")
        cid = _cr_id(ra, "cr abandon")
        confirm_owner("shipm cr abandon", cid)
        rules = _rules_for_write(pd)

        def fn(work):
            trs = engine.abandon(work, cid, _ev("owner_override", now, reason=engine._clean_text(a.reason or "abandoned by the owner", 80), **_origin()), rules)
            return engine.next_action(work, rules), trs
        na = store.transact(pd, fn)
        rpt = None
        try:
            from shipmiracle.report import write as _write
            rpt = os.path.relpath(str(_write.write_cr(pd, cid)), pd)          # the CR report of an abandoned CR (best effort)
        except Exception:
            pass
        if a.json:
            _json({"cr": cid, "abandoned": True, "report": rpt, "next": na})
        else:
            _out("%s abandoned." % cid)
            if rpt:
                _out("Report: " + rpt)
            _out(na["text"])
        return 0
    if act == "advance":
        paths.require_owner("shipm cr advance")
        cid = _cr_id(ra, "cr advance")
        if not a.stage or not a.reason or not a.reason.strip():
            raise UsageError("cr advance needs CR --stage STAGE --reason TEXT")
        confirm_owner("shipm cr advance", cid)
        rules = _rules_for_write(pd)
        reason = engine._clean_text(a.reason, 80)

        def fn(work):
            trs = engine.advance(work, cid, a.stage, _ev("owner_override", now, reason=reason, **_origin()), rules)
            return engine.next_action(work, rules), trs
        na = store.transact(pd, fn)
        if a.json:
            _json({"cr": cid, "advanced": a.stage, "next": na})
        else:
            _out("%s: %s passed by the owner (%s)." % (cid, _label(rules, a.stage), reason))
            _out(na["text"])
        return 0
    raise UsageError("unknown cr action")


# ------------------------------------------------------------------ shipm brief

def cmd_brief(a) -> int:
    """The session brief (<= 1 KB). Prints only when the project has .shipmiracle/work.json and a playbook; otherwise nothing and exit 0."""
    try:
        pd = _project_arg(a.project)
    except NotFound:
        return 0
    if not os.path.isfile(store.work_path(pd)):
        return 0
    rules = gate.stage_rules(pd)
    if rules is None:
        return 0
    _out(engine.brief(store.load(pd), rules))
    return 0
