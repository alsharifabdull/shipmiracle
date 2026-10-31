"""Owner config <config>/config.json (0600, flat {"dotted.key": value}); atomic, flock-ed, validated against SCHEMA, mtime-cached.
Sections watch/ideas/notifications are read-only here: they come from <workspace>/config/<section>.json."""
from __future__ import annotations

import json
import os
import pwd
import re
import unicodedata
from pathlib import Path

from . import SchemaError, UsageError
from . import paths, state

_MISSING = object()
_BAD_CATS = ("Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp")    # control, format (bidi marks, zero-width), surrogate, private, unassigned, line/paragraph separators
USER_RE = re.compile(r"[a-z_][a-z0-9_-]{0,31}")
READONLY_SECTIONS = ("watch", "ideas", "notifications")
MASKED_PREFIXES = ()          # key prefixes shown as *** (none today)
GATE_ENGINES = ("legacy", "shadow", "playbook")


def _bool(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, str) and v.strip().lower() in ("on", "true", "1", "yes"):
        return True
    if isinstance(v, str) and v.strip().lower() in ("off", "false", "0", "no"):
        return False
    raise UsageError("expected on/off")


def _user(v):
    if isinstance(v, str) and USER_RE.fullmatch(v):
        return v
    raise UsageError("expected a user name like [a-z_][a-z0-9_-]{0,31}")


def _str64(v):
    if isinstance(v, str) and 0 < len(v) <= 64 and not any(unicodedata.category(c) in _BAD_CATS for c in v):
        return v
    raise UsageError("expected a text of 1-64 characters")


def _list(v):
    if isinstance(v, str):
        s = v.strip()
        if s.startswith("["):
            try:
                v = json.loads(s)
            except ValueError:
                raise UsageError("expected a JSON list or comma-separated texts")
        else:
            v = [x.strip() for x in s.split(",") if x.strip()]
    if not isinstance(v, list) or len(v) > 10:
        raise UsageError("expected a list of at most 10 texts")
    return [_str64(x) for x in v]


def _days(v):
    if isinstance(v, bool):
        raise UsageError("expected a number of days")
    if isinstance(v, str) and re.fullmatch(r"\d{1,4}", v.strip()):
        v = int(v)
    if isinstance(v, int) and 1 <= v <= 365:
        return v
    raise UsageError("expected 1-365")


def _presence(v):
    if isinstance(v, str) and v.strip().lower() in ("auto", "strong-only", "basic-ok"):
        return v.strip().lower()
    raise UsageError("expected auto, strong-only or basic-ok")


def _layout(v):
    if isinstance(v, str) and v.strip().lower() in ("legacy", "userlevel"):
        return v.strip().lower()
    raise UsageError("expected legacy or userlevel")


def _hooks_mode(v):
    if isinstance(v, str) and v.strip().lower() in ("legacy", "shadow", "v1"):
        return v.strip().lower()
    raise UsageError("expected legacy, shadow or v1")


def _gate_engine(v):
    if isinstance(v, str) and v.strip().lower() in GATE_ENGINES:
        return v.strip().lower()
    raise UsageError("expected legacy, shadow or playbook")


REPORTER_MODELS = ("haiku", "sonnet", "opus", "off")


def _reporter_model(v):
    if isinstance(v, str) and v.strip().lower() in REPORTER_MODELS:
        return v.strip().lower()
    raise UsageError("expected haiku, sonnet, opus or off")


def _ask_model(v):
    if isinstance(v, str) and v.strip().lower() in ("haiku", "sonnet", "opus"):
        return v.strip().lower()
    raise UsageError("expected haiku, sonnet or opus")


def _ask_limit(v):
    if isinstance(v, bool):
        raise UsageError("expected a number of questions, 1-200")
    if isinstance(v, str) and re.fullmatch(r"\d{1,4}", v.strip()):
        v = int(v)
    if isinstance(v, int) and 1 <= v <= 200:
        return v
    raise UsageError("expected 1-200")


def legacy_hook_scripts_missing(ws=None):
    """Names of the legacy hook scripts (shipmiracle.hooks.spec.LEGACY + the status line) that are not files under <workspace or main checkout>/hooks/.
    A public install ships only the dispatcher: hooks.dispatcher legacy|shadow would register scripts that do not exist."""
    from .hooks import spec
    ws = Path(ws) if ws is not None else paths.workspace_dir()
    roots = [ws / "hooks"]
    mc = paths.main_checkout(ws)
    if mc != ws:
        roots.append(Path(mc) / "hooks")
    need = sorted({r[2] for r in spec.LEGACY} | {spec.LEGACY_STATUSLINE})
    return [n for n in need if not any((r / n).is_file() for r in roots)]


def require_legacy_hooks(mode, ws=None):
    """UsageError when `mode` (legacy|shadow) needs the legacy hook scripts and they are not there. v1 and off need none."""
    if os.environ.get("SHIPMIRACLE_TEST") == "1" and os.environ.get("SHIPMIRACLE_ENFORCE_LEGACY_HOOKS") != "1":      # temp workspaces of the tests have no scripts; the check itself is tested with the flag
        return
    if mode in ("legacy", "shadow"):
        miss = legacy_hook_scripts_missing(ws)
        if miss:
            raise UsageError("hooks mode %s needs the legacy hook scripts, but %d of them are missing from the hooks folder (%s%s): this install ships "
                             "only the dispatcher; use hooks.dispatcher v1" % (mode, len(miss), ", ".join(miss[:3]), ", ..." if len(miss) > 3 else ""))


def _tail_bytes(v):
    if isinstance(v, str) and re.fullmatch(r"\d{1,9}", v.strip()):
        v = int(v)
    if isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 1 << 30:
        return v
    raise UsageError("expected a number of bytes, 0 = read the whole file")


_NOREPLY_RE = re.compile(r"\d+\+[A-Za-z0-9-]+@users\.noreply\.github\.com")


def _noreply(v):
    if isinstance(v, str) and _NOREPLY_RE.fullmatch(v):
        return v
    raise UsageError("expected a GitHub noreply address like 12345+login@users.noreply.github.com")


def _abs_path(v, allow_tilde=False):
    """An absolute folder path (or ~/... when allowed) of at most 512 characters without control characters, '..' parts or NUL."""
    if isinstance(v, str) and 0 < len(v) <= 512 and not any(unicodedata.category(c) in _BAD_CATS for c in v):
        ok = v.startswith("/") or (allow_tilde and v.startswith("~/"))
        if ok and ".." not in v.split("/"):
            return v.rstrip("/") or "/"
    raise UsageError("expected an absolute folder path%s" % (" (or ~/...)" if allow_tilde else ""))


def _choice(*opts):
    def check(v):
        if isinstance(v, str) and v.strip().lower() in opts:
            return v.strip().lower()
        raise UsageError("expected one of: " + ", ".join(opts))
    return check


def _engine_dir(v):
    return _abs_path(v)


def _projects_dir(v):
    from . import folder_check
    if isinstance(v, str) and len(v) > 512:
        raise UsageError("That folder path is too long (at most 512 characters)." + folder_check.NEXT)
    if isinstance(v, str) and any(unicodedata.category(c) in _BAD_CATS for c in v):
        raise UsageError("A folder path cannot contain line breaks or other control characters." + folder_check.NEXT)
    try:
        v = _abs_path(v, True)
    except UsageError:
        if isinstance(v, str) and (v.startswith("/") or v.startswith("~/")):
            raise UsageError("A folder path cannot contain '..' parts." + folder_check.NEXT)
        raise UsageError("That is not a full folder path (it must start with / or ~/)." + folder_check.NEXT)
    why = folder_check.syntactic_problem(v)       # a system folder is never a projects folder, also when it was stored by an older version
    if why:
        raise UsageError(why)
    return v


_LOGIN_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})")


def _github_login(v):
    if isinstance(v, str) and _LOGIN_RE.fullmatch(v):
        return v
    raise UsageError("expected a GitHub login (letters, digits, hyphens; at most 39 characters)")


def _default_user():
    try:
        n = pwd.getpwuid(os.getuid()).pw_name
    except KeyError:
        return None
    return n if USER_RE.fullmatch(n) else None


# key -> (validator, default factory)
SCHEMA = {
    "switches.state.v1": (_bool, lambda: True),
    "owner.user": (_user, _default_user),
    "logs.retention_days": (_days, lambda: 30),
    "hooks.dispatcher": (_hooks_mode, lambda: "legacy"),     # which hooks run: legacy = the old scripts, shadow = scripts + v1 compared, v1 = shipm-hook modules (shipm sync --hooks MODE registers it)
    "hooks.record": (_bool, lambda: False),                  # record hook inputs and legacy results for replay (off by default, redacted, capped)
    "hooks.stop_tests_block": (_bool, lambda: False),        # P4a T4: stop_tests blocks a stop on a failing .claude/test-command (off = like stop-gate.sh in practice: runs it, logs, never blocks)
    "tokens.nudge": (_bool, lambda: False),                  # P4a: the context module adds token-budget nudges (off by default)
    "hooks.awake_throttle": (_bool, lambda: False),          # P4a owner decision O2: keep_awake respawns caffeinate at most once per 60 s (off = on every call, as the old script)
    "hooks.keep_going_tail_bytes": (_tail_bytes, lambda: 0),  # P4a owner decision O6: keep_going reads only the last N bytes of the transcript (0 = whole file, as the old script)
    "gate.engine": (_gate_engine, lambda: "legacy"),         # P5: legacy = the 19 Oct gate only; shadow = the stage module logs what it would refuse; playbook = it enforces. shadow|playbook need hooks.dispatcher=v1
    "autopilot.full.enabled": (_bool, lambda: False),        # P6: the owner's switch for full autopilot (off = a playbook cannot be 'full', a running run pauses; fail closed)
    "owner.presence": (_presence, lambda: "auto"),           # owner proof: auto (best provider that works; default) | strong-only (Touch ID only) | basic-ok (typed code also when the OS prompt is unavailable now)
    "autopilot.standing.enabled": (_bool, lambda: False),   # owner proof (B2): the go-live switch of option C "Until I disable it"; turning it ON needs Touch ID and a recorded P6-1 pass (or a throwaway-account marker)
    "autopilot.mcp_allow": (_list, lambda: []),              # P6: MCP tool names (mcp__server__tool) a full run may call; everything else is hard stop H3
    "agents.layout": (_layout, lambda: "legacy"),      # where the team lives: legacy = copies in each project, userlevel = ~/.claude/agents (shipmiracle.agents)
    "release.author_name": (_str64, lambda: None),           # P8 T5: author and committer name of the public export commit (the GitHub login, never a real name)
    "release.author_email": (_noreply, lambda: None),        # P8 T5: must be the GitHub noreply address; `shipm release denylist --refresh` fills both
    "release.push_enabled": (_bool, lambda: False),          # P8 T5: `shipm release export --push` needs this on; the owner sets it only after P9
    "engine.dir": (_engine_dir, lambda: None),               # P8: this engine checkout (set by `shipm init`); for non-Python readers (panel, bin tools) and the doctor; Python derives it from its own location
    "paths.projects_dir": (_projects_dir, lambda: None),     # P8: the folder that holds the projects (unset = ~/Developer)
    "git.autopush": (_bool, lambda: False),                  # P8: the post-commit hook pushes after each commit (off for a fresh install; the owner's machine sets it on)
    "owner.github": (_github_login, lambda: None),           # P8: the owner's GitHub login (unset = none)
    "agents.maxTurns": (_bool, lambda: True),                # P1 lever (shipm switch agents.maxTurns): on = the maxTurns caps in the agent files apply (today's state); recorded for rollback and the scorecard, no code reads it yet
    "prefix.trim": (_bool, lambda: True),                    # P1 lever: on = the trimmed session prefix (docs/owner-steps/p1-prefix-trim.sh applied); recorded for rollback, no code reads it yet (the script and its backups are the real undo)
    "reporter.model": (_reporter_model, lambda: "haiku"),    # P5: the model of the summary reporter (default = the model agents/claude/reporter.md pins); off = no model line, reports stay script-only
    "ask.model": (_ask_model, lambda: "opus"),               # F4: the default model of `shipm ask --inbox` (tool-less side answers); default opus; `--model` overrides per question
    "ask.daily_limit": (_ask_limit, lambda: 20),             # the most questions `shipm ask --inbox` answers per day (1-200, default 20)
    "prefs.lang": (_choice("en", "ar"), lambda: None),                       # onboarding choice 1: language of reports (unset = English, as before)
    "prefs.autonomy": (_choice("normal", "step", "own"), lambda: None),      # choice 3: normal | step (step by step) | own (on its own: only prints the owner step, never switches full autopilot on)
    "prefs.keep_awake": (_bool, lambda: None),                               # choice 4: keep the computer awake while Claude works (unset = on, as before)
    "prefs.notify": (_choice("vscode", "system", "none"), lambda: None),     # choice 5: where notifications show (unset = the old config/notifications.json switch)
    "guard.jobs": (_bool, lambda: False),     # P4b: the guard runs its periodic jobs in-process (shipmiracle.guard.jobs); off = subprocess spawns exactly as before
}
_cache = {}      # path -> ((ino, mtime_ns, size), parsed)


def path() -> Path:
    return paths.config_dir() / "config.json"


def _cached_json(p: Path, required_dict=True):
    """Parsed JSON of `p`, re-read only when (inode, mtime, size) changed. {} when the file is absent."""
    try:
        st = os.lstat(p)
    except FileNotFoundError:
        _cache.pop(str(p), None)
        return {}
    key = (st.st_ino, st.st_mtime_ns, st.st_size)
    hit = _cache.get(str(p))
    if hit and hit[0] == key:
        return hit[1]
    try:
        val = json.loads(state.read_bytes_nofollow(p).decode("utf-8"))
    except ValueError:
        raise SchemaError("%s is not valid JSON" % p.name)
    except FileNotFoundError:
        return {}
    if required_dict and not isinstance(val, dict):
        raise SchemaError("%s is not a JSON object" % p.name)
    _cache[str(p)] = (key, val)
    return val


def load() -> dict:
    """The stored values (a copy). SchemaError when the file is damaged or holds an invalid value for a known key."""
    raw = _cached_json(path())
    out = {}
    for k, v in raw.items():
        if k in SCHEMA:
            try:
                v = SCHEMA[k][0](v)
            except UsageError as e:
                raise SchemaError("config key %s is invalid: %s" % (k, e))
        out[k] = v
    return json.loads(json.dumps(out))


def _section_key(key):
    sec, _, rest = key.partition(".")
    return (sec, rest) if sec in READONLY_SECTIONS and rest else None


def get(key: str, default=_MISSING):
    """Stored value, else `default` when given, else the SCHEMA default. Read-only sections read config/<section>.json."""
    sk = _section_key(key)
    if sk:
        data = _cached_json(paths.workspace_dir() / "config" / (sk[0] + ".json"))
        return data.get(sk[1], None if default is _MISSING else default)
    if key not in SCHEMA:
        if default is _MISSING:
            raise UsageError("unknown config key")
        return default
    if key == "gate.engine" and os.environ.get("SHIPMIRACLE_TEST") == "1" and os.environ.get("SHIPMIRACLE_GATE_ENGINE"):    # tests only; the hook logs gate_env_override otherwise
        try:
            return _gate_engine(os.environ["SHIPMIRACLE_GATE_ENGINE"])
        except UsageError:
            pass
    vals = load()
    if key in vals:
        return vals[key]
    return SCHEMA[key][1]() if default is _MISSING else default


def switch(name: str) -> bool:
    """Value of switches.<name> (bool; default on)."""
    return bool(get("switches." + name))


def _check_key(key: str) -> None:
    if _section_key(key):
        raise UsageError("%s is read-only here: edit config/%s.json in the workspace" % (key, key.split(".")[0]))
    if key not in SCHEMA:
        raise UsageError("unknown config key")


def _update(key: str, fn) -> None:
    paths.require_owner("shipm config set/unset")      # every key: agents.layout decides whether the trust model applies at all
    d = paths.config_dir()
    paths.assert_isolated(d)
    _check_key(key)
    state.ensure_dir(d)
    with state.lock_file(d / ".config.lock"):
        cur = dict(_cached_json(path()))
        fn(cur)
        state.atomic_write(path(), (json.dumps(cur, sort_keys=True, indent=1) + "\n").encode("utf-8"))
        _cache.pop(str(path()), None)


def set(key: str, value_str) -> None:  # noqa: A001  (name fixed by the spec)
    """Validate and store. Logs config.set with the key only; the value is never logged. Owner only (refuses inside a chat)."""
    paths.require_owner("shipm config set")
    paths.assert_isolated(paths.config_dir())
    _check_key(key)
    val = SCHEMA[key][0](value_str)
    if key == "paths.projects_dir" and val is not None:
        from . import folder_check
        why = folder_check.problem(val)           # set-time only: exists / owned / writable / not behind a link out of the home (reads never check the disk)
        if why:
            raise UsageError(why)
    if key.startswith("autopilot.") and val not in (False, [], None) and not (isinstance(val, str) and val.strip().lower() == "off"):
        from . import owner              # owner proof: turning an autopilot setting ON is an escalation (one touch); turning it off never asks for anything
        owner.escalate_switch(key, val)
    if key == "owner.presence":
        from . import owner               # weakening the owner check is itself confirmed by the best check that works now; strengthening needs nothing
        owner.escalate_presence_setting(get(key), val)
    if key == "gate.engine" and val != "legacy" and get("hooks.dispatcher") != "v1":
        raise UsageError("gate.engine %s needs hooks.dispatcher=v1 (it is %s); run `shipm switch hooks.dispatcher v1` first, or keep gate.engine legacy"
                         % (val, get("hooks.dispatcher")))
    if key == "hooks.dispatcher":
        require_legacy_hooks(val)
    _update(key, lambda cur: cur.__setitem__(key, val))
    _emit("config.set", key)


def unset(key: str) -> None:
    paths.require_owner("shipm config unset")
    if key == "owner.presence":
        from . import owner               # D14 m3: unsetting resets the check to its default (auto): weakening strong-only is confirmed exactly like `config set`
        owner.escalate_presence_setting(get(key), SCHEMA[key][1]())
    _update(key, lambda cur: cur.pop(key, None))
    _emit("config.unset", key)


def restore_many(values: dict) -> None:
    """Put several keys back in ONE atomic config write (value None = unset), so an interrupt leaves all of them old or all new. Used by `shipm uninstall`
    to restore the quick-setup answers; the values were valid when stored, so they are checked against the SCHEMA only."""
    paths.require_owner("shipm config set/unset")
    paths.assert_isolated(paths.config_dir())
    for k in values:
        _check_key(k)
    vals = {k: (None if v is None else SCHEMA[k][0](v)) for k, v in values.items()}
    _update(next(iter(values)), lambda cur: [cur.pop(k, None) if v is None else cur.__setitem__(k, v) for k, v in vals.items()])
    for k, v in vals.items():
        _emit("config.unset" if v is None else "config.set", k)


def _emit(kind, key):
    from . import events
    events.emit(kind, {"key": key}, src="shipmiracle-config")


def list_items(mask: bool = True) -> dict:
    """Effective value of every SCHEMA key; keys under MASKED_PREFIXES are shown as '***' when set and `mask` is true."""
    vals = load()
    out = {}
    for k in sorted(SCHEMA):
        v = vals[k] if k in vals else SCHEMA[k][1]()
        if mask and k.startswith(MASKED_PREFIXES) and v not in (None, []):
            v = "***"
        out[k] = v
    return out
