"""Declarative hook registration for ~/.claude/settings.json (P4 spec section 6). Pure data and string building: no file is read or written here
except bin/gate-deny (imported for its deny-rule list).
Modes: legacy = the 17 script entries sync-tools wrote until P4, in the same order; shadow and v1 = one shipm-hook dispatcher entry per event."""
from __future__ import annotations

import importlib.machinery
import importlib.util
import os
import re
from pathlib import Path

from .. import UsageError, paths

MODES = ("legacy", "shadow", "v1")
DEFAULT_MODE = "legacy"
FIXED_PREFIX = "$HOME/.local/share/shipmiracle/engine/hooks/"      # fallback when the engine path is unsafe in a hook command: the owner links this to the engine folder
SAFE_RE = re.compile(r"(\$HOME)?/[A-Za-z0-9/._-]+")      # a space, quote or $ in the path would break the hook command line in settings.json
BROWSER_ARGS = "--use-mock-keychain,--password-store=basic"     # automation browsers must never touch the login keychain (agent-browser reads AGENT_BROWSER_ARGS)
ENV_KEYS = {"BASH_DEFAULT_TIMEOUT_MS": "600000", "BASH_MAX_TIMEOUT_MS": "3600000", "AGENT_BROWSER_ARGS": BROWSER_ARGS}     # a Bash call cannot hang for ever; long jobs go through bin/shipm-bg
PYTHON = "/usr/bin/python3"

# Today's registrations, in the order sync-tools' ensure() calls made them (so the dict order of a fresh file is the old one):
# (event, matcher or None, script). Matchers are Claude Code regexes over the tool name.
LEGACY = (
    ("UserPromptSubmit", None, "keep-awake.sh"), ("PreToolUse", "*", "keep-awake.sh"),
    ("UserPromptSubmit", None, "guard-hook.sh"), ("PreToolUse", "*", "guard-hook.sh"),
    ("UserPromptSubmit", None, "plan-approval.sh"), ("PreToolUse", "Edit|Write|NotebookEdit", "plan-approval.sh"),
    ("PostToolUse", "ExitPlanMode", "plan-approval.sh"),
    ("Stop", None, "keep-going.sh"), ("StopFailure", None, "limit-wait.sh"),
    ("SubagentStart", None, "agent-state.sh"), ("SubagentStop", None, "agent-state.sh"),
    ("PreToolUse", "Agent|Task", "agent-cap.sh"),
    ("UserPromptSubmit", None, "flow-gate.sh"),
    ("PreToolUse", "ExitPlanMode|Edit|Write|NotebookEdit|MultiEdit|Bash", "flow-gate.sh"),
    ("PostToolUse", "Edit|Write|NotebookEdit|MultiEdit", "flow-gate.sh"),
    ("SubagentStop", None, "flow-gate.sh"), ("Stop", None, "flow-gate.sh"),
)
LEGACY_STATUSLINE = "plan-capture.sh"

# The dispatcher registrations: (event, matcher or None, argument words after the event name)
V1 = (
    ("UserPromptSubmit", None, ()), ("PreToolUse", "*", ()), ("PostToolUse", "*", ()),
    ("Stop", None, ()), ("Stop", None, ("--slow",)),     # the slow test run is its own entry: a timeout there cannot kill the gate
    ("StopFailure", None, ()), ("SubagentStart", None, ()), ("SubagentStop", None, ()),
    ("SessionStart", None, ()), ("Notification", None, ()), ("PreModelSwitch", None, ()),     # served by shipmiracle.hooks.project (session_start, shipmiracle_state, model_switch)
)


def check_mode(mode):
    if mode not in MODES:
        raise UsageError("hooks mode must be one of %s" % ", ".join(MODES))
    return mode


def _home_rel(target: str, home: str):
    """`$HOME/<rel>` when `target` is under the (realpath) home, else None."""
    return "$HOME/" + os.path.relpath(target, home) if target.startswith(home + "/") else None


def hooks_prefix(ws=None, home=None):
    """(prefix, warning): '<$HOME/rel|abs>/hooks/' of the MAIN checkout (also when run from a worktree); the fixed
    FIXED_PREFIX (a link to the engine folder) with a warning text when the derived path is not shell-safe. Same rule as the old sync-tools `H=`."""
    ws = Path(ws) if ws is not None else paths.workspace_dir()
    home = Path(home) if home is not None else paths.home()
    mc = os.path.realpath(str(paths.main_checkout(ws)))
    hm = os.path.realpath(str(home))
    h = (_home_rel(mc, hm) or mc) + "/hooks/"
    if not SAFE_RE.fullmatch(h):
        return FIXED_PREFIX, "the workspace path has characters that are unsafe in a hook command; using the fixed %s (make it a link to the engine folder)" % FIXED_PREFIX
    return h, None


def _pyc_dir(home=None):
    home = Path(home) if home is not None else paths.home()
    sd = os.path.realpath(str(paths.state_dir()))
    hm = os.path.realpath(str(home))
    p = (_home_rel(sd, hm) or sd) + "/v1/pyc"
    return p if SAFE_RE.fullmatch(p) else "$HOME/.local/state/shipmiracle/v1/pyc"


# The dispatcher command is a fail-open wrapper: when the hook script exists it is `exec /usr/bin/python3 <flags> <script> <Event> [--slow]` (same
# argv, stdin, stdout and exit code as the plain command); when it is missing (a deleted checkout or temp folder) it exits 0 and prints a visible
# warning (JSON systemMessage, plain text for the status line) and logs a line, so a vanished script can never make every event fail.
WRAPPER_NAME = "shipm-gate"      # $0 of the wrapper shell; the marker that settings_sync.is_owned recognises
WRAPPER_BODY = (
    '[ -f "$1" ] || { m="Shipmiracle gate OFF: hook script missing at $1 (repair: shipm sync --repair-hooks)"; '
    'case "$2" in StatusLine) printf "%s\\n" "$m";; *) printf "%s\\n" "{\\"systemMessage\\":\\"$m\\"}";; esac; '
    'd="${SHIPMIRACLE_STATE:-$HOME/.local/state/shipmiracle}"; { mkdir -p "$d" && printf "%s module=shipmiracle-hook-wrapper %s: %s\\n" "$(date "+%F %T")" "$2" "$m" >> "$d/flow-errors.log"; } 2>/dev/null; exit 0; }; '
    'exec ' + PYTHON + ' -I -S -X pycache_prefix=PYCPFX "$@"'
)


def wrapper_body(pyc):
    return WRAPPER_BODY.replace("PYCPFX", pyc)


def dispatcher_command(prefix, event, words=(), home=None):
    """`/bin/sh -c '<fail-open wrapper>' shipm-gate <hooks>/shipm-hook <Event> [--slow]`; the wrapper runs `/usr/bin/python3 -I -S -X pycache_prefix=<state>/v1/pyc
    <hooks>/shipm-hook <Event> [--slow]` (the pyc cache sits under the protected v1 folder) when the script exists. `plain_dispatcher_command` is the pre-wrapper form."""
    return "/bin/sh -c '%s' %s %s" % (wrapper_body(_pyc_dir(home)), WRAPPER_NAME, " ".join([prefix + "shipm-hook", event] + list(words)))


def plain_dispatcher_command(prefix, event, words=(), home=None):
    """The command Shipmiracle registered before the wrapper: python straight at the dispatcher script (still recognised as shipmiracle-owned and migrated on the next sync)."""
    return " ".join([PYTHON, "-I", "-S", "-X", "pycache_prefix=" + _pyc_dir(home), prefix + "shipm-hook", event] + list(words))


def _group(cmd, matcher):
    g = {"hooks": [{"type": "command", "command": cmd}]}
    if matcher:
        g["matcher"] = matcher
    return g


def build(mode, ws=None, home=None):
    """{"hooks": {event: [group, ...]}, "statusLine": {...}, "env": {...}, "warning": str|None} for `mode`. Event order = first use in the table."""
    check_mode(mode)
    prefix, warn = hooks_prefix(ws, home)
    hooks = {}
    if mode == "legacy":
        for ev, matcher, script in LEGACY:
            hooks.setdefault(ev, []).append(_group(prefix + script, matcher))
        status = {"type": "command", "command": prefix + LEGACY_STATUSLINE, "padding": 0}
    else:
        for ev, matcher, words in V1:
            hooks.setdefault(ev, []).append(_group(dispatcher_command(prefix, ev, words, home), matcher))
        status = {"type": "command", "command": dispatcher_command(prefix, "StatusLine", (), home), "padding": 0}
    return {"hooks": hooks, "statusLine": status, "env": dict(ENV_KEYS), "warning": warn}


def entries(spec):
    """Flat rows (event, matcher or '-', command) of a built spec, in order."""
    return [(ev, g.get("matcher", "-"), h["command"]) for ev, groups in spec["hooks"].items() for g in groups for h in g["hooks"]]


def deny_rules(ws=None):
    """The native deny rules bin/gate-deny installs (its RULES list, imported from the file, never copied)."""
    ws = Path(ws) if ws is not None else paths.workspace_dir()
    for root in (ws, paths.main_checkout(ws)):
        f = Path(root) / "bin" / "gate-deny"
        if f.is_file():
            loader = importlib.machinery.SourceFileLoader("shipmiracle_gate_deny_rules", str(f))
            mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
            loader.exec_module(mod)
            return list(mod.RULES)
    return []
