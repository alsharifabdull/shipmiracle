"""`shipm sync`: write the shipmiracle-owned part of ~/.claude/settings.json (hooks, statusLine, env) for one hook mode (shipmiracle.hooks.spec).
Only hook entries whose command IS an Shipmiracle registration (the dispatcher command or one known legacy script path, see is_owned) are replaced; foreign/plugin hooks, permissions, model, plugins and every
other key stay as they are. The old file is backed up first (<state>/v1/backups/settings-<ts>.json, 0600, newest 10 kept); the write is atomic and
re-checked against a concurrent change; the result is read back and verified. The file is re-serialised (not byte-exact): key order, the indent
(spaces/tab), ensure_ascii and the final newline of the original are kept, see style_of."""
from __future__ import annotations

import copy
import difflib
import hashlib
import json
import os
import re
import stat
import time
from pathlib import Path

from . import SafetyError, SchemaError
from . import paths, state
from .hooks import spec

KEEP_BACKUPS = 10
OFF = "off"            # not a hook mode: removes every shipmiracle-owned entry (hooks, statusLine) and adds nothing; `shipm sync --hooks off`, used by `shipm uninstall`
_TEST_HOOK = None      # tests: called between the read and the final change check


def settings_path() -> Path:
    return paths.home() / ".claude" / "settings.json"


def _roots(ws, home):
    """Folders whose hooks/ subfolder holds shipmiracle-owned scripts: this workspace, its main checkout (when run from a worktree) and the fixed fallback."""
    ws = Path(ws) if ws is not None else paths.workspace_dir()
    home = Path(home) if home is not None else paths.home()
    out = []
    for r in (ws, paths.main_checkout(ws), home / ".local" / "share" / "shipmiracle" / "engine"):      # the last one is spec.FIXED_PREFIX's folder
        for v in (os.path.normpath(str(r)), os.path.realpath(str(r))):
            if v not in out:
                out.append(v)
    return out


def _expand(tok, home):
    hv = [str(home), os.path.realpath(str(home))]
    for prefix in ("$HOME", "${HOME}", "~"):
        if tok == prefix or tok.startswith(prefix + "/"):
            return [h + tok[len(prefix):] for h in hv]
    return [tok]


OWNED_SCRIPTS = frozenset({r[2] for r in spec.LEGACY} | {spec.LEGACY_STATUSLINE, "context-nudge.sh"})    # every script an Shipmiracle registration ever pointed at
_PY_FLAGS = ("-I", "-S", "-E", "-s", "-B")
_EVENT = re.compile(r"[A-Za-z]{3,30}")


_WRAP_RE = re.compile(r"/bin/sh -c '" + re.escape(spec.WRAPPER_BODY).replace("PYCPFX", r"[A-Za-z0-9/._$-]+") + "' " + re.escape(spec.WRAPPER_NAME)
                      + r" (\S+) ([A-Za-z]{3,30})((?: --slow)?)")


def _is_hook_path(tok, name, roots, home, any_root=False):
    """True when `tok` is <root>/hooks/<name> for one of the workspace roots; with any_root, <any absolute folder>/hooks/<name> (repair only)."""
    for cand in _expand(tok.strip("\"'"), home):
        c = os.path.normpath(cand)
        if any(c == r.rstrip("/") + "/hooks/" + name for r in roots) or (any_root and os.path.isabs(c) and c.endswith("/hooks/" + name)):
            return True
    return False


def _expanded(tok, home):
    return os.path.normpath(_expand(tok.strip("\"'"), home)[0])


def owned_script(cmd, ws=None, home=None, any_root=False):
    """The (expanded) script path of a command Shipmiracle itself registered, else None: (1) exactly one word, <workspace>/hooks/<known legacy script> (the 17 script
    entries, plan-capture, context-nudge); (2) the dispatcher in its two forms: the fail-open wrapper (spec.dispatcher_command) and the plain
    [/usr/bin/python3 -I -S -X pycache_prefix=<dir>] <workspace>/hooks/shipm-hook <Event> [--slow] of before the wrapper. A foreign hook that merely
    mentions a path under <workspace>/hooks/ (an argument, another script, another wrapper) is NOT owned and stays through `shipm sync`.
    any_root=True accepts any folder in place of the workspace (the repair path: a registration whose workspace is gone or temporary)."""
    if not isinstance(cmd, str):
        return None
    home = Path(home) if home is not None else paths.home()
    roots = _roots(ws, home)
    m = _WRAP_RE.fullmatch(cmd)
    if m:
        return _expanded(m.group(1), home) if _is_hook_path(m.group(1), "shipm-hook", roots, home, any_root) else None
    w = cmd.split()
    if len(w) == 1:
        for n in OWNED_SCRIPTS:
            if _is_hook_path(w[0], n, roots, home, any_root):
                return _expanded(w[0], home)
        return None
    i = 0
    if w and os.path.basename(w[0].strip("\"'")) in ("python3", "python"):
        if w[0].strip("\"'") not in (spec.PYTHON, "python3"):
            return None
        i = 1
        while i < len(w) and w[i] in _PY_FLAGS:
            i += 1
        if i + 1 < len(w) and w[i] == "-X" and w[i + 1].startswith("pycache_prefix="):
            i += 2
    rest = w[i:]
    if (1 < len(rest) <= 3 and _is_hook_path(rest[0], "shipm-hook", roots, home, any_root) and _EVENT.fullmatch(rest[1]) is not None
            and (len(rest) == 2 or rest[2] == "--slow")):
        return _expanded(rest[0], home)
    return None


def is_owned(cmd, ws=None, home=None) -> bool:
    return owned_script(cmd, ws, home) is not None


def dispatcher_parts(cmd):
    """(event, slow) of an `shipm-hook <Event> [--slow]` command in either form, else None (no ownership check: use is_owned for that)."""
    m = _WRAP_RE.fullmatch(cmd) if isinstance(cmd, str) else None
    if m:
        return m.group(2), bool(m.group(3))
    w = cmd.split() if isinstance(cmd, str) else []
    for i, x in enumerate(w):
        if os.path.basename(x.strip("\"'")) == "shipm-hook" and i + 1 < len(w):
            return w[i + 1], "--slow" in w[i + 2:]
    return None


def is_temp_path(p) -> bool:
    return paths._under_temp(p)


def _split_group(g, ws, home):
    """(kept group or None, owned_count) for one registration group."""
    if not isinstance(g, dict) or not isinstance(g.get("hooks"), list):
        return g, 0
    keep = [h for h in g["hooks"] if not (isinstance(h, dict) and is_owned(h.get("command"), ws, home))]
    n = len(g["hooks"]) - len(keep)
    if n == 0:
        return g, 0
    if not keep:
        return None, n
    g2 = dict(g)
    g2["hooks"] = keep
    return g2, n


def _check_mode(mode):
    return mode if mode == OFF else spec.check_mode(mode)


def _built(mode, ws, home):
    if mode == OFF:
        return {"hooks": {}, "statusLine": None, "env": {}, "warning": None}
    return spec.build(mode, ws, home)


def plan(settings, mode, ws=None, home=None, style=None):
    """(new settings dict, unified diff text) for `mode`. `settings` is not modified. Adds the key 'warning' nowhere: see spec.build for the notice.
    Mode `off` removes the shipmiracle-owned hook entries and an Shipmiracle statusLine and nothing else (env, permissions, foreign hooks stay; a hooks object that
    this empties is dropped, one that was already absent is not added)."""
    _check_mode(mode)
    if not isinstance(settings, dict):
        raise SchemaError("settings.json is not a JSON object")
    new = copy.deepcopy(settings)
    built = _built(mode, ws, home)
    cur = new.get("hooks", {})
    if not isinstance(cur, dict):
        raise SchemaError("settings.json: hooks is not an object")
    out = {}
    for ev, groups in cur.items():
        if not isinstance(groups, list):
            raise SchemaError("settings.json: hooks.%s is not a list" % ev)
        add = built["hooks"].get(ev, [])
        res, placed, gone = [], False, []
        for g in groups:
            kept, n = _split_group(g, ws, home)
            if n and not placed:
                res.append(None); placed = True      # slot for the Shipmiracle groups: the first place an Shipmiracle group stood
            if n and kept is None:
                gone.append(g)
            if kept is not None:
                res.append(kept)
        mine = [next((x for x in gone if x == a), copy.deepcopy(a)) for a in add]    # an unchanged group keeps its original key order
        if placed:
            i = res.index(None); res[i:i + 1] = mine
        else:
            res.extend(mine)
        if res:
            out[ev] = res
    for ev, add in built["hooks"].items():
        if ev not in out and ev not in cur:
            out[ev] = copy.deepcopy(add)
    if mode == OFF:
        if out or "hooks" in settings and not settings["hooks"]:
            new["hooks"] = out
        else:
            new.pop("hooks", None)
        sl = new.get("statusLine")
        if isinstance(sl, dict) and is_owned(sl.get("command"), ws, home):
            del new["statusLine"]
        return new, diff_text(settings, new, style)
    new["hooks"] = out
    env = new.get("env", {})
    if not isinstance(env, dict):
        raise SchemaError("settings.json: env is not an object")
    env.update(built["env"])
    new["env"] = env
    sl = new.get("statusLine")
    if sl is None or (isinstance(sl, dict) and is_owned(sl.get("command"), ws, home)):
        new["statusLine"] = copy.deepcopy(built["statusLine"])
    return new, diff_text(settings, new, style)


def style_of(raw) -> dict:
    """How the original file was written: indent (spaces or a tab, default 2), ensure_ascii (False when it holds literal non-ASCII text and no \\u escapes),
    final newline. The rewrite is NOT byte-exact: the JSON is parsed and written again in this style (key order kept; blank lines, spacing inside a
    line, number spellings like 1.0e3 and duplicate keys are not preserved)."""
    t = raw.decode("utf-8", "replace") if isinstance(raw, (bytes, bytearray)) else (raw or "")
    indent = 2
    m = re.search(r"^(\t+|[ ]+)\S", t, re.M)
    if m:
        indent = "\t" if m.group(1).startswith("\t") else min(len(m.group(1)), 8)
    non_ascii = re.search(r"[^\x00-\x7f]", t) is not None
    return {"indent": indent, "ensure_ascii": not (non_ascii and "\\u" not in t), "newline": t.endswith("\n") or not t.strip()}


def dumps(d, style=None) -> str:
    st = style or {}
    return json.dumps(d, indent=st.get("indent", 2), ensure_ascii=st.get("ensure_ascii", True)) + ("\n" if st.get("newline", True) else "")


def diff_text(old, new, style=None) -> str:
    a, b = dumps(old, style).splitlines(keepends=True), dumps(new, style).splitlines(keepends=True)
    return "".join(difflib.unified_diff(a, b, "settings.json (current)", "settings.json (new)", n=2))


def _fingerprint(path):
    """(ino, mtime_ns, size, sha256) of the settings file, read without following a symlink; None when absent."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(st.st_mode):
        raise SafetyError("%s is a symlink: refusing to write through it" % path)
    data = state.read_bytes_nofollow(path)
    return (st.st_ino, st.st_mtime_ns, st.st_size, hashlib.sha256(data).hexdigest()), data


def _backup(data: bytes) -> Path:
    root = state.ensure_root()
    bdir = state.ensure_dir(root / "backups")
    t = time.time()
    name = "settings-%s-%03d.json" % (time.strftime("%Y%m%dT%H%M%S", time.gmtime(t)), int((t % 1) * 1000))
    dest = bdir / name
    n = 0
    while dest.exists():
        n += 1
        dest = bdir / ("settings-%s-%03d-%d.json" % (time.strftime("%Y%m%dT%H%M%S", time.gmtime(t)), int((t % 1) * 1000), n))
    state.atomic_write(dest, data, 0o600)
    olds = sorted(p for p in bdir.iterdir() if p.name.startswith("settings-") and p.name.endswith(".json"))
    for p in olds[:-KEEP_BACKUPS]:
        try:
            p.unlink()
        except OSError:
            pass
    return dest


REPAIR_CMD = "shipm sync --repair-hooks --apply"


def _guard_target(path, what, write=True):
    """Test-run safety: under SHIPMIRACLE_TEST=1 a write may not reach the real home's .claude (decoy under SHIPMIRACLE_REAL_HOME in tests)."""
    if write:
        paths.assert_home_writable(what)
    paths.assert_not_real_claude(path, what)


def _hook_commands(settings):
    hooks = settings.get("hooks") if isinstance(settings, dict) else None
    for groups in hooks.values() if isinstance(hooks, dict) else []:
        for g in groups if isinstance(groups, list) else []:
            for h in g.get("hooks") if isinstance(g, dict) and isinstance(g.get("hooks"), list) else []:
                if isinstance(h, dict) and isinstance(h.get("command"), str):
                    yield h["command"]
    sl = settings.get("statusLine") if isinstance(settings, dict) else None
    if isinstance(sl, dict) and isinstance(sl.get("command"), str):
        yield sl["command"]


def temp_hook_paths(settings, ws=None, home=None) -> list:
    """Script paths of shipmiracle-owned commands (any workspace folder) that sit under a temp root."""
    out = []
    for cmd in _hook_commands(settings):
        sp = owned_script(cmd, ws, home, any_root=True)
        if sp and is_temp_path(sp) and sp not in out:
            out.append(sp)
    return out


def _refuse_temp_hooks(new, path, ws, home):
    """Never install or keep an Shipmiracle hook whose script is in a temp folder in a settings file that is not itself in one (the 21 Oct incident)."""
    if is_temp_path(path):
        return
    bad = temp_hook_paths(new, ws, home)
    if bad:
        raise SafetyError("refusing to put an Shipmiracle hook with a script in a temp folder (%s) into %s, which is not in a temp folder. "
                          "Repair: %s (removes only the shipm hooks whose script is missing or in a temp folder), then run shipm sync from the real workspace" % (bad[0], path, REPAIR_CMD))


def apply(path=None, mode="legacy", dry_run=False, ws=None, home=None) -> dict:
    """Write `mode` into the settings file. Returns {changed, diff, backup, warning, path}. A dry run only reads and never needs the owner."""
    _check_mode(mode)
    if not dry_run:
        paths.require_owner("shipm sync")
    path = Path(path) if path is not None else settings_path()
    _guard_target(path, "shipm sync", write=not dry_run)
    if os.path.islink(str(path)):
        raise SafetyError("%s is a symlink: refusing to write through it" % path)
    fp = _fingerprint(path)
    if fp is None:
        old, raw = {}, None
    else:
        _, raw = fp
        try:
            old = json.loads(raw.decode("utf-8"))
        except ValueError:
            raise SchemaError("%s is not valid JSON: nothing changed" % path.name)
    style = style_of(raw) if raw is not None else None
    new, diff = plan(old, mode, ws, home, style)
    if mode != OFF:
        _refuse_temp_hooks(new, path, ws, home)
    warn = _built(mode, ws, home)["warning"]
    res = {"changed": new != old, "diff": diff, "backup": None, "warning": warn, "path": str(path)}
    if not res["changed"] or dry_run:
        return res
    if _TEST_HOOK:
        _TEST_HOOK()
    fp2 = _fingerprint(path)
    if (fp2[0] if fp2 else None) != (fp[0] if fp else None):
        raise SafetyError("%s changed while shipm sync was working: nothing written, run it again" % path.name)
    if raw is not None:
        res["backup"] = str(_backup(raw))
    mode_bits = stat.S_IMODE(os.lstat(path).st_mode) if fp else 0o600
    if not path.parent.is_dir():
        state.ensure_dir(path.parent)
    state.atomic_write(path, dumps(new, style).encode("utf-8"), mode_bits)
    back = json.loads(state.read_bytes_nofollow(path).decode("utf-8"))
    if back != new or plan(back, mode, ws, home)[0] != back:
        raise SchemaError("verification failed after writing %s%s" % (path.name, "; restore with: cp %s %s" % (res["backup"], path) if res["backup"] else ""))
    return res


def script_problems(path=None, ws=None, home=None) -> list:
    """[(kind, event, script)] for every shipmiracle-owned hook registration (any workspace folder) in the settings file whose script file does not exist
    (kind 'missing': the gate is OFF) or sits under a temp root (kind 'temp'). Read only; bin/doctor prints one red row per entry."""
    path = Path(path) if path is not None else settings_path()
    try:
        d = json.loads(state.read_bytes_nofollow(path).decode("utf-8"))
    except (OSError, ValueError, SafetyError):
        return []
    home = Path(home) if home is not None else paths.home()
    out = []
    hooks = d.get("hooks") if isinstance(d, dict) else None
    items = [(ev, c) for ev, groups in (hooks.items() if isinstance(hooks, dict) else []) if isinstance(groups, list)
             for g in groups if isinstance(g, dict) and isinstance(g.get("hooks"), list) for h in g["hooks"] if isinstance(h, dict) for c in [h.get("command")]]
    sl = d.get("statusLine") if isinstance(d, dict) else None
    if isinstance(sl, dict):
        items.append(("statusLine", sl.get("command")))
    for ev, cmd in items:
        sp = owned_script(cmd, ws, home, any_root=True)
        if sp is None:
            continue
        for kind, bad in (("missing", not os.path.exists(sp)), ("temp", is_temp_path(sp))):
            if bad and (kind, ev, sp) not in out:
                out.append((kind, ev, sp))
    return out


def plan_repair(settings, ws=None, home=None, emergency=False):
    """(new settings, removed [(event, command)], diff-less) : drops ONLY shipmiracle-owned entries (owned_script, any workspace folder) whose script file is
    missing or sits under a temp root; the statusLine too when it is such an entry. Everything else is left exactly as it is."""
    if not isinstance(settings, dict):
        raise SchemaError("settings.json is not a JSON object")
    home = Path(home) if home is not None else paths.home()

    def bad(cmd):
        sp = owned_script(cmd, ws, home, any_root=True)
        if sp is None:
            return False
        if emergency and len(cmd.split()) == 1:
            return is_temp_path(sp)      # L6: a single-word hook (<folder>/hooks/<legacy name>) can belong to someone else; the emergency cleanup removes it only when it sits in a temp folder
        return is_temp_path(sp) or not os.path.exists(sp)

    new = copy.deepcopy(settings)
    removed = []
    hooks = new.get("hooks")
    if isinstance(hooks, dict):
        for ev in list(hooks):
            groups = hooks[ev]
            if not isinstance(groups, list):
                continue
            out = []
            for g in groups:
                if isinstance(g, dict) and isinstance(g.get("hooks"), list):
                    keep = []
                    for h in g["hooks"]:
                        if isinstance(h, dict) and bad(h.get("command")):
                            removed.append((ev, h["command"]))
                        else:
                            keep.append(h)
                    if len(keep) == len(g["hooks"]):
                        out.append(g)
                    elif keep:
                        g2 = dict(g); g2["hooks"] = keep; out.append(g2)
                else:
                    out.append(g)
            if out or not groups:
                hooks[ev] = out
            else:
                del hooks[ev]
    sl = new.get("statusLine")
    if isinstance(sl, dict) and bad(sl.get("command")):
        removed.append(("statusLine", sl["command"]))
        del new["statusLine"]
    return new, removed


def repair(path=None, apply=False, ws=None, home=None, emergency=False) -> dict:
    if emergency:
        with paths.allow_real_writes():
            return _repair(path, apply, ws, home, True)
    return _repair(path, apply, ws, home, False)


def _emergency_backup(path: Path, data: bytes) -> Path:
    """L6: the emergency cleanup of a test run whose own state folder is a temp folder: the backup goes next to the settings file (0600, `.shipmiracle-repair-backup`, never
    overwriting an earlier one), not into a throw-away temp state folder where it would vanish and not into the real state folder from a test run."""
    base = Path(path).parent
    dest = base / ".shipmiracle-repair-backup"
    n = 0
    while os.path.lexists(str(dest)):
        n += 1
        dest = base / (".shipmiracle-repair-backup-%d" % n)
    fd = os.open(str(dest), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    return dest


def _repair(path, apply, ws, home, emergency) -> dict:
    """`shipm sync --repair-hooks [--apply]`: remove the shipmiracle-owned hook entries whose script is missing or in a temp folder. Dry run by default; --apply is
    owner only (emergency=True: bin/test-all's cleanup, no owner check and no test-run guard), backs up the old file (0600), writes atomically and reads back. Idempotent. -> {changed, diff, removed, backup, path}."""
    if apply and not emergency:
        paths.require_owner("shipm sync --repair-hooks --apply")
    path = Path(path) if path is not None else settings_path()
    if not emergency:       # emergency: bin/test-all cleaning the real file after a test run polluted it (the one deliberate write to the real home under SHIPMIRACLE_TEST)
        _guard_target(path, "shipm sync --repair-hooks", write=apply)
    if os.path.islink(str(path)):
        raise SafetyError("%s is a symlink: refusing to write through it" % path)
    fp = _fingerprint(path)
    if fp is None:
        return {"changed": False, "diff": "", "removed": [], "backup": None, "path": str(path)}
    _, raw = fp
    try:
        old = json.loads(raw.decode("utf-8"))
    except ValueError:
        raise SchemaError("%s is not valid JSON: nothing changed" % path.name)
    style = style_of(raw)
    new, removed = plan_repair(old, ws, home, emergency)
    res = {"changed": new != old, "diff": diff_text(old, new, style), "removed": removed, "backup": None, "path": str(path)}
    if not res["changed"] or not apply:
        return res
    fp2 = _fingerprint(path)
    if (fp2[0] if fp2 else None) != fp[0]:
        raise SafetyError("%s changed while shipm sync --repair-hooks was working: nothing written, run it again" % path.name)
    res["backup"] = str(_emergency_backup(path, raw) if emergency and paths._under_temp(paths.state_dir()) else _backup(raw))
    state.atomic_write(path, dumps(new, style).encode("utf-8"), stat.S_IMODE(os.lstat(path).st_mode))
    back = json.loads(state.read_bytes_nofollow(path).decode("utf-8"))
    if back != new:
        raise SchemaError("verification failed after writing %s; restore with: cp %s %s" % (path.name, res["backup"], path))
    return res


# ---- project hooks -> dispatcher (`shipm project hooks-global`, P4c) ----
# The template registrations of templates/base/.claude/settings.json: exact command -> the events it is registered for. Only these exact strings are ever removed.
_PH = "$CLAUDE_PROJECT_DIR/.claude/hooks/"
PROJECT_TEMPLATE = {
    _PH + "session-start.sh": ("session-start.sh", ("SessionStart",)),
    _PH + "block-secrets.sh": ("block-secrets.sh", ("PreToolUse",)),
    _PH + "shipm-state.sh working": ("shipm-state.sh", ("PreToolUse", "UserPromptSubmit")),
    _PH + "shipm-state.sh done": ("shipm-state.sh", ("Stop",)),
    _PH + "shipm-state.sh needs-input": ("shipm-state.sh", ("Notification",)),
    _PH + "stop-gate.sh": ("stop-gate.sh", ("Stop",)),
    _PH + "save-plan.sh": ("save-plan.sh", ("PostToolUse",)),
    _PH + "model-switch.sh": ("model-switch.sh", ("PreModelSwitch",)),
}                                    # format.sh is not here on purpose: it stays a per-project hook
# What the dispatcher needs to see registered globally before a script's project entries may go (every event the script serves; stop-gate also its --slow entry).
SCRIPT_NEEDS = {
    "session-start.sh": (("SessionStart", False),),
    "block-secrets.sh": (("PreToolUse", False),),
    "shipm-state.sh": (("UserPromptSubmit", False), ("PreToolUse", False), ("Stop", False), ("Notification", False)),
    "stop-gate.sh": (("Stop", False), ("Stop", True)),
    "save-plan.sh": (("PostToolUse", False),),
    "model-switch.sh": (("PreModelSwitch", False),),
}


def dispatcher_events(global_settings, ws=None, home=None) -> set:
    """{(event, slow)} registered in the global settings by the Shipmiracle dispatcher (owned `shipm-hook <Event> [--slow]` commands whose matcher is none or '*')."""
    out = set()
    hooks = global_settings.get("hooks") if isinstance(global_settings, dict) else None
    if not isinstance(hooks, dict):
        return out
    for ev, groups in hooks.items():
        for g in groups if isinstance(groups, list) else []:
            if not isinstance(g, dict) or g.get("matcher") not in (None, "", "*"):
                continue
            for h in g.get("hooks") if isinstance(g.get("hooks"), list) else []:
                cmd = h.get("command") if isinstance(h, dict) else None
                if isinstance(cmd, str) and is_owned(cmd, ws, home):
                    dp = dispatcher_parts(cmd)
                    if dp:
                        out.add(dp)
    return out


def plan_project_hooks_global(settings, covered, local_text="") -> tuple:
    """(new settings, removed [(event, command)], kept [(script, reason)]). `settings` is not modified. A script's entries go only when the dispatcher is
    registered globally for EVERY event it serves (`covered`, from dispatcher_events) and settings.local.json does not name it (the dispatcher module runs
    only when no settings file names the script, so a half-removal would silence the hook). Foreign entries and format.sh stay as they are."""
    if not isinstance(settings, dict):
        raise SchemaError("settings.json is not a JSON object")
    hooks = settings.get("hooks", {})
    if not isinstance(hooks, dict):
        raise SchemaError("settings.json: hooks is not an object")
    present = {PROJECT_TEMPLATE[h["command"]][0] for groups in hooks.values() if isinstance(groups, list) for g in groups if isinstance(g, dict)
               for h in (g.get("hooks") if isinstance(g.get("hooks"), list) else []) if isinstance(h, dict) and isinstance(h.get("command"), str) and h["command"] in PROJECT_TEMPLATE}
    ok, kept = set(), []
    for sh in sorted(present):
        miss = [e + (" --slow" if s else "") for e, s in SCRIPT_NEEDS[sh] if (e, s) not in covered]
        if miss:
            kept.append((sh, "the dispatcher is not registered globally for %s" % ", ".join(miss)))
        elif (".claude/hooks/" + sh) in (local_text or ""):
            kept.append((sh, ".claude/settings.local.json names it too"))
        else:
            ok.add(sh)
    new = copy.deepcopy(settings)
    removed, nh = [], {}
    for ev, groups in new.get("hooks", {}).items():
        if not isinstance(groups, list):
            nh[ev] = groups
            continue
        out = []
        for g in groups:
            if isinstance(g, dict) and isinstance(g.get("hooks"), list):
                keep = []
                for h in g["hooks"]:
                    t = PROJECT_TEMPLATE.get(h.get("command")) if isinstance(h, dict) and isinstance(h.get("command"), str) else None
                    if t and t[0] in ok and ev in t[1]:
                        removed.append((ev, h["command"]))
                    else:
                        keep.append(h)
                if len(keep) == len(g["hooks"]):
                    out.append(g)
                elif keep:
                    g2 = dict(g); g2["hooks"] = keep; out.append(g2)
            else:
                out.append(g)
        if out or not groups:
            nh[ev] = out
    if "hooks" in new:
        new["hooks"] = nh
    return new, removed, kept


def project_hooks_global(project_dir, pid, apply=False, undo=False, ws=None, home=None) -> dict:
    """Plan (dry run) or write the removal of the template hook entries now served by the dispatcher from <project>/.claude/settings.json; or undo it.
    -> {changed, diff, removed, kept, backup, path}. apply/undo are owner only; a symlinked settings file is refused; the file is re-checked right before the write
    and read back after it. The backup is <state>/v1/backups/project-settings-<pid>-<ts>.json (0600); undo restores the newest one."""
    path = Path(project_dir) / ".claude" / "settings.json"
    if apply or undo:
        paths.require_owner("shipm project hooks-global")
    if os.path.islink(str(path)):
        raise SafetyError("%s is a symlink: refusing to touch it" % path)
    bdir = Path(state.ensure_root()) / "backups"
    prefix = "project-settings-%s-" % pid
    if undo:
        olds = sorted(p for p in bdir.iterdir() if p.name.startswith(prefix) and p.name.endswith(".json")) if bdir.is_dir() else []
        if not olds:
            raise SafetyError("no backup of this project's settings.json to restore (looked in %s)" % bdir)
        data = state.read_bytes_nofollow(olds[-1])
        try:
            json.loads(data.decode("utf-8"))
        except ValueError:
            raise SchemaError("the backup %s is not valid JSON: nothing changed" % olds[-1].name)
        fp = _fingerprint(path)
        if fp is not None and fp[1] == data:
            return {"changed": False, "diff": "", "removed": [], "kept": [], "backup": str(olds[-1]), "path": str(path)}
        state.atomic_write(path, data, stat.S_IMODE(os.lstat(path).st_mode) if fp else 0o644)
        return {"changed": True, "diff": "", "removed": [], "kept": [], "backup": str(olds[-1]), "path": str(path)}
    gp = settings_path() if home is None else Path(home) / ".claude" / "settings.json"
    try:
        gset = json.loads(state.read_bytes_nofollow(gp).decode("utf-8"))
    except (OSError, ValueError, SafetyError):
        gset = {}
    if not is_temp_path(path) and temp_hook_paths(gset, ws, home):
        raise SafetyError("refusing to move %s to the global dispatcher: the global hooks point at a script in a temp folder (%s). Repair: %s" % (path, temp_hook_paths(gset, ws, home)[0], REPAIR_CMD))
    fp = _fingerprint(path)
    if fp is None:
        raise SchemaError("%s does not exist: nothing to move" % path)
    _, raw = fp
    try:
        old = json.loads(raw.decode("utf-8"))
    except ValueError:
        raise SchemaError("%s is not valid JSON: nothing changed" % path)
    try:
        local = state.read_bytes_nofollow(path.parent / "settings.local.json").decode("utf-8", "replace")
    except (OSError, SafetyError):
        local = ""
    style = style_of(raw)
    new, removed, kept = plan_project_hooks_global(old, dispatcher_events(gset, ws, home), local)
    res = {"changed": new != old, "diff": diff_text(old, new, style), "removed": removed, "kept": kept, "backup": None, "path": str(path)}
    if not res["changed"] or not apply:
        return res
    fp2 = _fingerprint(path)
    if (fp2[0] if fp2 else None) != fp[0]:
        raise SafetyError("%s changed while Shipmiracle was working: nothing written, run it again" % path)
    t = time.time()
    dest = state.ensure_dir(bdir) / ("%s%s-%03d.json" % (prefix, time.strftime("%Y%m%dT%H%M%S", time.gmtime(t)), int((t % 1) * 1000)))
    state.atomic_write(dest, raw, 0o600)
    olds = sorted(p for p in bdir.iterdir() if p.name.startswith(prefix) and p.name.endswith(".json"))
    for p in olds[:-KEEP_BACKUPS]:
        try:
            p.unlink()
        except OSError:
            pass
    res["backup"] = str(dest)
    state.atomic_write(path, dumps(new, style).encode("utf-8"), stat.S_IMODE(os.lstat(path).st_mode))
    back = json.loads(state.read_bytes_nofollow(path).decode("utf-8"))
    if back != new:
        raise SchemaError("verification failed after writing %s; restore with: cp %s %s" % (path, dest, path))
    return res


# ------------------------------------------------------------------ Remote Control opt-in (one boolean key of the USER-level settings file)
RC_KEY = "remoteControlAtStartup"       # Claude Code reads it from the user-level file only (it ignores true in project/local settings); `disableRemoteControl` is never touched here


def remote_control_state(path=None) -> str:
    """READ-ONLY. 'on' (the key is exactly true), 'off' (file or key absent, or any other value), 'unknown' (unreadable, not JSON, a symlink, not an object).
    Never returns or echoes any other key."""
    path = Path(path) if path is not None else settings_path()
    try:
        raw = state.read_bytes_nofollow(path)
    except FileNotFoundError:
        return "off"
    except (OSError, SafetyError):
        return "unknown"
    try:
        d = json.loads(raw.decode("utf-8"))
    except ValueError:
        return "unknown"
    if not isinstance(d, dict):
        return "unknown"
    return "on" if d.get(RC_KEY) is True else "off"


def remote_control_value(path=None):
    """READ-ONLY. The stored boolean of the key (True/False) or None when absent; SchemaError when the file cannot be read as an object."""
    path = Path(path) if path is not None else settings_path()
    try:
        d = json.loads(state.read_bytes_nofollow(path).decode("utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        raise SchemaError("%s cannot be read as JSON" % path.name)
    if not isinstance(d, dict):
        raise SchemaError("%s is not a JSON object" % path.name)
    v = d.get(RC_KEY)
    return v if isinstance(v, bool) else None


def _text_insert(raw, key, value, style):
    """Byte-faithful insertion of one new top-level member before the closing brace; None when the text does not have the plain multi-line shape."""
    t = raw.decode("utf-8", "replace")
    end = t.rstrip()
    if not end.endswith("}") or "\n" not in end:
        return None
    idx = len(end) - 1
    body = t[:idx].rstrip()
    if not body or body.endswith("{"):          # an empty object falls back to the full rewrite
        return None
    ws = t[len(body):idx]
    ind = "\t" if style["indent"] == "\t" else " " * int(style["indent"])
    member = json.dumps(key) + ": " + json.dumps(value)
    return body + ",\n" + ind + member + ws + t[idx:]


def set_remote_control(value, path=None, dry_run=False) -> dict:
    """Set ONLY the boolean key remoteControlAtStartup in the user-level settings file: value True/False, or None to remove the key.
    Every other key, the key order and the file style stay as they are (a new key is inserted into the text, so the other bytes are identical; an edit or
    removal of an existing key re-serialises in the original style, like `shipm sync`). Guards as `apply`: owner only (not a dry run), real-home refusal under
    SHIPMIRACLE_TEST=1, symlink refused, change re-check right before the write, 0600 backup, atomic write, read-back check. An unchanged value writes NOTHING
    (bytes, mtime and xattrs stay). Returns {changed, before, after, backup, path, file_before_sha256, file_after_sha256}; before/after are True/False/None (None = absent)."""
    if value not in (True, False, None) or (value is not None and not isinstance(value, bool)):
        raise SchemaError("remoteControlAtStartup must be true, false or removed")
    if not dry_run:
        paths.require_owner("Shipmiracle remote-control")
    path = Path(path) if path is not None else settings_path()
    _guard_target(path, "Shipmiracle remote-control", write=not dry_run)
    if os.path.islink(str(path)):
        raise SafetyError("%s is a symlink: refusing to write through it" % path)
    fp = _fingerprint(path)
    raw = fp[1] if fp else None
    if raw is None:
        old = {}
    else:
        try:
            old = json.loads(raw.decode("utf-8"))
        except ValueError:
            raise SchemaError("%s is not valid JSON: nothing changed" % path.name)
        if not isinstance(old, dict):
            raise SchemaError("%s is not a JSON object: nothing changed" % path.name)
    cur = old.get(RC_KEY, None)
    if cur is not None and not isinstance(cur, bool):
        raise SchemaError("%s holds a %s that is not true/false: left as it is" % (RC_KEY, type(cur).__name__))
    res = {"changed": cur != value, "before": cur, "after": value, "backup": None, "path": str(path),
           "file_before_sha256": hashlib.sha256(raw).hexdigest() if raw is not None else None, "file_after_sha256": None}
    if not res["changed"] or dry_run:
        res["file_after_sha256"] = res["file_before_sha256"]
        return res
    new = dict(old)
    if value is None:
        new.pop(RC_KEY, None)
    else:
        new[RC_KEY] = value
    style = style_of(raw) if raw is not None else None
    text = None
    if raw is not None and cur is None and value is not None:
        text = _text_insert(raw, RC_KEY, value, style)
        if text is not None:
            try:
                if json.loads(text) != new:
                    text = None
            except ValueError:
                text = None
    if text is None:
        text = dumps(new, style)
    if _TEST_HOOK:
        _TEST_HOOK()
    fp2 = _fingerprint(path)
    if (fp2[0] if fp2 else None) != (fp[0] if fp else None):
        raise SafetyError("%s changed while Shipmiracle was working: nothing written, run it again" % path.name)
    if raw is not None:
        res["backup"] = str(_backup(raw))
    mode_bits = stat.S_IMODE(os.lstat(path).st_mode) if fp else 0o600
    if not path.parent.is_dir():
        state.ensure_dir(path.parent)
    data = text.encode("utf-8")
    state.atomic_write(path, data, mode_bits)
    back = state.read_bytes_nofollow(path)
    if json.loads(back.decode("utf-8")) != new:
        raise SchemaError("verification failed after writing %s%s" % (path.name, "; restore with: cp %s %s" % (res["backup"], path) if res["backup"] else ""))
    res["file_after_sha256"] = hashlib.sha256(back).hexdigest()
    return res


def backup_in_manifest_dir(backup) -> bool:
    """True when `backup` is a path inside <state>/v1/install-backups/ (the only place `shipm init` keeps the files it may later restore from)."""
    try:
        d = os.path.realpath(str(state.root() / "install-backups"))
        r = os.path.realpath(str(backup))
    except (OSError, ValueError, TypeError):
        return False
    return r.startswith(d + "/")


def undo_remote_control(before, path=None, backup=None, file_before_sha256=None, file_after_sha256=None) -> str:
    """Put the key back to `before` (True/False, or None = absent). When the file is still exactly as the opt-in wrote it (sha equals file_after_sha256), the
    pre-opt-in bytes come back from the backup (or the file is removed when it did not exist), so nothing else differs; otherwise only the key is edited.
    Same guards as set_remote_control. Returns a one-line note."""
    paths.require_owner("Shipmiracle remote-control")
    path = Path(path) if path is not None else settings_path()
    if os.path.normpath(str(path)) != os.path.normpath(str(settings_path())):
        raise SafetyError("manifest entry refused: %s is not the settings file" % path)
    if backup and not backup_in_manifest_dir(backup):
        raise SafetyError("manifest entry refused: the backup %s is not in the install-backups folder" % backup)
    _guard_target(path, "Shipmiracle remote-control", write=True)
    if os.path.islink(str(path)):
        raise SafetyError("%s is a symlink: refusing to write through it" % path)
    fp = _fingerprint(path)
    if fp is not None and file_after_sha256 and hashlib.sha256(fp[1]).hexdigest() == file_after_sha256:
        if backup:
            data = state.read_bytes_nofollow(backup)
            if hashlib.sha256(data).hexdigest() == file_before_sha256:
                state.atomic_write(path, data, stat.S_IMODE(os.lstat(path).st_mode))
                return "restored the file as it was before the opt-in"
        elif file_before_sha256 is None:
            os.unlink(str(path))
            return "removed the settings file (it did not exist before the opt-in)"
    res = set_remote_control(before, path=path)
    return "set %s back to %s" % (RC_KEY, "absent" if before is None else str(before).lower()) if res["changed"] else "already as before"
