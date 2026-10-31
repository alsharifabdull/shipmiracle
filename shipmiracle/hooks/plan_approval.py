"""plan_approval (spec 2.2): ported from legacy plan-approval.sh with identical decisions, texts and state files.
  PostToolUse ExitPlanMode  -> mark the session "plan pending" (state/plan-pending.<sid>) and tell Claude to show the plan and wait.
  UserPromptSubmit          -> owner words clear the mark; in plan mode on a non-Opus chat a warning is given once per 30 min.
  PreToolUse Edit|Write|NotebookEdit -> refused while the mark is fresh (6 h), except plan files (legacy exit 2 text).
SHIPMIRACLE_QUIET is handled by core. Import budget: os, json, re, time only."""
from __future__ import annotations

import json
import os
import re
import time

from . import core
from . import io as hio

FRESH_SECS = 6 * 3600
WARN_SECS = 1800
MODEL_AGE = 900
APPROVE = re.compile(r"\b(approved?|approve it|go ahead|go|yes|yep|proceed|start|build it|do it|implement|looks good|ok|okay)\b")
NEGATE = re.compile(r"\b(don'?t|do not|not approved|wait|stop|no)\b")

PENDING_TEXT = ("PLAN APPROVAL IS NOT CONFIRMED. The plan tool's 'approved' answer is not the owner's approval (auto mode and some chats answer it by themselves). "
                "Now print the full plan in this chat in plain language (what will be built, how it will look or work, what is NOT verified) and ask the owner to approve. "
                "Do not edit files, run builds or commit until the owner writes approval (approved / go / yes / proceed) in the chat. Edit and Write are blocked until then.")
BLOCK_TEXT = ("Blocked: a plan was just presented and the owner has not approved it in the chat. Show the plan in the chat and wait for 'approved' / 'go' / 'yes'. "
              "(The plan tool's own 'approved' does not count.) This unlocks as soon as the owner approves, or after 6 hours.")


def _write(path: str, text: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)


def _warn_text(model: str) -> str:
    return ("PLAN MODE ON %s: this chat's model picker is overriding opusplan, so planning would run on %s. Do the design with the Agent tool: " % (model.upper(), model)
            + "subagent_type Plan, model opus (put the full context in its prompt), then write the plan from its result and say the design was made by Opus. "
              "Start your reply with one line: 'Planning model: <your model> — design made by an Opus agent'. Tell the owner they can type /model opusplan in this chat to fix it for good.")


def _owner_words(d) -> bool:
    prompt = d.get("prompt") or ""
    if not isinstance(prompt, str):
        return False                                   # the old inline python crashed here: the mark stayed
    p = prompt.lower()
    h = p.lstrip()
    if h.startswith("/") or h.startswith(hio.PANEL_MARK):
        return False                                   # M3: a slash command (/rename go-api) or text the panel typed is never the owner's approval
    return bool(APPROVE.search(p)) and not NEGATE.search(p)


def _handback(prompt) -> bool:
    """Same test as flow's UserPromptSubmit (hio.HANDBACK_HEADS): the prompt starts with a hand-back head or carries an agent-message tag early."""
    if not isinstance(prompt, str):
        return False
    return hio.handback(prompt)


def _clear(mark: str) -> None:
    try:
        os.remove(mark)
    except OSError:
        pass


def plan_approval(ctx):
    hio.ensure_dir(ctx.state)                          # the old script made the folder before it looked at the input
    d = ctx.data
    if not ctx.raw.strip() or not d:
        return None
    sid_raw = d.get("session_id", "") or "x"
    if not isinstance(sid_raw, str):
        return None                                    # the old script crashed on a non-text session id: nothing happened
    sid = re.sub(r"[^A-Za-z0-9_-]", "", sid_raw)       # may be empty (unlike Ctx.sid), as before
    state = ctx.state
    mark = os.path.join(state, "plan-pending." + sid)
    try:
        fresh = time.time() - os.path.getmtime(mark) < FRESH_SECS
    except OSError:
        fresh = False
    ev, tool = d.get("hook_event_name", ""), d.get("tool_name")
    if ev == "UserPromptSubmit" and _handback(d.get("prompt")):
        return None                                    # P6 (red-team 1): a subagent hand-back / system text is not the owner and never approves a plan
    if ev == "PostToolUse" and tool == "ExitPlanMode":
        _write(mark, str(int(time.time())))
        return core.Result(additional_context=PENDING_TEXT, effects=["mark " + mark])
    if ev == "UserPromptSubmit" and d.get("permission_mode") == "plan":
        out = ""
        proj = os.path.basename((ctx.env.get("CLAUDE_PROJECT_DIR") or d.get("cwd") or "").rstrip("/"))
        try:
            with open(os.path.join(state, proj + ".model.json")) as f:
                m = json.load(f)
            model, age = str(m.get("model") or m.get("id") or ""), time.time() - m.get("ts", 0)
        except Exception:
            model, age = "", 1e9
        flag = os.path.join(state, "plan-model-told." + sid)
        try:
            told = time.time() - os.path.getmtime(flag) < WARN_SECS
        except OSError:
            told = False
        if model and age < MODEL_AGE and "opus" not in model.lower() and not told:
            _write(flag, model)
            out = _warn_text(model) + "\n"
        if fresh and _owner_words(d):
            _clear(mark)
        return core.Result(plain_stdout=out) if out else None
    if ev == "UserPromptSubmit" and fresh:
        if _owner_words(d):
            _clear(mark)
        return None
    if ev == "PreToolUse" and fresh and tool in ("Edit", "Write", "NotebookEdit"):
        ti = d.get("tool_input") or {}
        if not isinstance(ti, dict):
            return None                                # the old script crashed (exit 1 = no block)
        path = ti.get("file_path", "") or ""
        if not isinstance(path, str) or "/.claude/plans/" in path or "/docs/plans/" in path:
            return None
        return core.Result(block=True, reason=BLOCK_TEXT, exit_code=2)
    return None


core.register("PostToolUse", "plan_approval", None, plan_approval)
core.register("UserPromptSubmit", "plan_approval", None, plan_approval)
core.register("PreToolUse", "plan_approval", None, plan_approval)
