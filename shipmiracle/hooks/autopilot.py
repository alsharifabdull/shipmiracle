"""autopilot (Phase 6 T4, spec docs/plans/2026-10-20-p6-spec.md sections 1.3, 2, 4, 6): the hook module of the full autopilot. It runs AFTER `stage`
in UserPromptSubmit, PreToolUse (all tools), PostToolUse (Write|Edit|MultiEdit|NotebookEdit), SubagentStop and Stop and can only ADD refusals.
Rule of the phase: models may stop, only rules may go. This module never trusts a model's text; the only trusted text is the `prompt` field of a
UserPromptSubmit that is not a hand-back, whose first line is a charter:/allow: line, and whose process ancestry has exactly one `claude`.

What it does
  * Trusted prompt (any project): `charter: goal=...` stores a charter (charter.store_from_prompt), `charter: off|show`, `allow: H-xxxxxx` (state.allow,
    one shot, bound to the stopped command's sha, 10 min). Hand-back prompts (io.HANDBACK_HEADS), lines over 1024 bytes, a nested `claude` in the
    ancestry (ps -o ppid=,comm= up to 8 levels) or CLAUDE_CODE_ENTRYPOINT=sdk-* are ignored/refused and logged.
  * Bash `claude ... charter:/allow: ...` is refused in every project (the nested-claude trick).
  * Inside an AUTO worktree (cheap path test under <dev>/.worktrees/<project>/, then the HEAD file; no git subprocess otherwise) with a run state
    file: every call is checked against the charter. Active run -> shipmiracle.autopilot.hardstop.check (H1..H9); a stop pauses the run (state.pause with the
    stop id and cmd sha) and the call is denied with the exact text of the spec; H8 (budget/time at 100 %) ends the run (ended:budget|time) and never
    blocks the Stop event; at 90 % Agent calls are refused (limit_near). A paused/ended/set run allows only Read/Grep/Glob/LS and edits of the RECORD
    files; `allow: H-x` releases one exact action; any other trusted owner prompt resumes a paused run (when the prerequisites hold).
  * It ignores flow's bypass ("just do it") on purpose: it never reads it.
Fails closed inside an active run (an internal error denies mutating tools); everywhere else it fails open like every module (the dispatcher logs it).
Import budget at module level: os, re (plus core/io; hashlib and the regexes are loaded lazily); shipmiracle.autopilot.* and git only when an auto worktree has a run state or a
charter:/allow: line arrives."""
from __future__ import annotations

import os
import re

from . import core
from . import io as hio

READ_TOOLS = ("Read", "Grep", "Glob", "NotebookRead", "LS")
FILE_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
HARMLESS = READ_TOOLS + ("WebSearch", "WebFetch", "TodoWrite", "ExitPlanMode", "TaskCreate", "TaskUpdate", "TaskList", "TaskGet", "BashOutput")
RECORD = ("docs/status.md", "docs/decisions.md")
AGENT_TOOLS = ("Agent", "Task")
_RX = {}
_RX_SRC = {"CMD_LINE": (r"\s*(charter|allow)\s*:", re.I), "CMD_ANYWHERE": (r"(?im)^\s*(?:charter|allow)\s*:", 0), "NESTED_ARGS": (r"\b(?:charter|allow)\s*:", re.I),
           "NESTED_CLAUDE": (r"(?<![\w.-])(?:[^\s;|&()'\"`]*/)?claude(?![\w-])", 0), "BRANCH_RE": (r"auto/CR-\d+", 0),
           "CLAUDE_CMD": (r"""(?:^|[;&|(`\n]|\$\()\s*(?:\w+=\S*\s+)*(?:(?:exec|command|env|nohup|setsid|time|sudo|xargs|builtin|(?:ba|z|da)?sh\s+-\w*c)\s+['"]?)*(?:[^\s;|&()'"`]*/)?claude(?![\w.-])""", 0),
           "CLAUDE_ENV": (r"(?<!\w)(?:SHIPMIRACLE_\w*|CLAUDE\w*)\s*=|\b(?:export|env|declare|typeset|setenv)\b[^;|&\n]*(?:SHIPMIRACLE_|CLAUDE)\w*", 0)}


def _rx(name):
    """Regexes are compiled on first use: the common case (no charter line, no auto worktree) compiles none."""
    r = _RX.get(name)
    if r is None:
        src, fl = _RX_SRC[name]
        r = _RX[name] = re.compile(src, fl)
    return r


def _sha(b):
    import hashlib
    return hashlib.sha256(b).hexdigest()


MAX_PS_LEVELS = 256      # sanity bound of the walk to pid 1 (a loop or a longer chain is refused, never cut short)
_OWNER_HOST_OVERRIDE = None    # test-only: callable(comm) -> bool replacing is_owner_host
_PS_CHAIN_OVERRIDE = None      # test-only injection points: set by test code on the module object, never read from the environment
_TMP_ROOTS_OVERRIDE = None
ALLOW_MARK_S = 120
TEST_PATHS = ("tests/**", "test/**", "__tests__/**", "spec/**", "**/*_test.*", "**/test_*.*", "**/*.test.*", "**/*.spec.*", "**/*Tests/**", "**/*Tests.*")

PAUSED_TEXT = "Autopilot is paused (%s, id %s). Nothing is changed until the owner releases it. Do not retry or work around it. End your turn with one line for the owner."
ENDED_TEXT = "Autopilot has ended (%s). Do not change anything more on this branch. End your turn with one line for the owner."
NOT_RUNNING_TEXT = "Autopilot is %s, not running. Do not change anything. End your turn with one line for the owner."
PREREQ_TEXT = "Autopilot paused: %s. Do not retry or work around it. End your turn with one line for the owner."
CLOSED_TEXT = "Autopilot check failed (%s): nothing is changed until it works. End your turn with one line for the owner."
NESTED_TEXT = ("Refused: a tool call may not start `claude` (with a charter: or allow: argument, or at all while an autopilot run exists). Only the owner types those, in their own chat. "
               "Do not retry or work around it. End your turn with one line for the owner.")


# ---------------------------------------------------------------- small helpers (no Shipmiracle imports)
def _fold(p):
    return os.path.normcase(p).casefold()


def _handback(prompt) -> bool:
    """Trusted-prompt rule 1 (same test as flow's UserPromptSubmit): a subagent hand-back or system text is not the owner."""
    return hio.handback(prompt)


def _read_text(path, limit=4096):
    try:
        with open(path, "rb") as f:
            return f.read(limit).decode("utf-8", "replace")
    except OSError:
        return None


def _gitdirs(wt):
    """(gitdir, commondir) of a linked worktree from its .git file; (None, None) when it is not one."""
    g = os.path.join(wt, ".git")
    try:
        if os.path.islink(g) or not os.path.isfile(g):
            return None, None
    except OSError:
        return None, None
    t = _read_text(g)
    m = re.match(r"gitdir:\s*(.+?)\s*$", (t or "").splitlines()[0] if t and t.splitlines() else "")
    if not m:
        return None, None
    gd = m.group(1)
    if not os.path.isabs(gd):
        gd = os.path.normpath(os.path.join(wt, gd))
    cd = (_read_text(os.path.join(gd, "commondir")) or "").strip()
    if not cd:
        return gd, None
    return gd, os.path.normpath(cd if os.path.isabs(cd) else os.path.join(gd, cd))


def _branch(gd) -> str:
    t = _read_text(os.path.join(gd, "HEAD"), 512) if gd else None
    m = re.match(r"ref:\s*refs/heads/(\S+)", t or "")
    return m.group(1) if m else ""


def auto_worktree(ctx):
    """None, or {"wt", "proj", "main", "pid", "gd", "common", "branch"} when ctx.pd is inside <dev>/.worktrees/<project>/<x> whose .git file points
    into <dev>/<project>/.git and that is an auto worktree (folder auto-* or HEAD on auto/CR-n). Only file reads."""
    pd = ctx.pd
    if "/.worktrees/" not in pd and not pd.endswith("/.worktrees"):
        return None
    dev_parts = [p for p in ctx.dev.split("/") if p] + [".worktrees"]
    parts = [p for p in pd.split("/") if p]
    n = len(dev_parts)
    if len(parts) < n + 2 or [_fold(x) for x in parts[:n]] != [_fold(x) for x in dev_parts]:
        return None
    proj, name = parts[n], parts[n + 1]
    wt = "/" + "/".join(parts[:n + 2])
    gd, common = _gitdirs(wt)
    if gd is None or common is None:
        return None
    main = os.path.join(ctx.dev, proj)
    if _fold(os.path.realpath(os.path.dirname(common))) != _fold(os.path.realpath(main)):
        return None                                              # a worktree of some other repository
    branch = _branch(gd)
    if not (name.startswith("auto-") or branch.startswith("auto/")):
        return None
    pid = _sha(("shipmiracle-project:" + os.path.realpath(main)).encode("utf-8", "surrogateescape"))[:12]
    return {"wt": wt, "proj": proj, "main": os.path.realpath(main), "pid": pid, "gd": gd, "common": common, "branch": branch}


def _ev(kind, data, pid=None):
    hio.emit_event(kind, data, project=pid)


# ---------------------------------------------------------------- ancestry (trusted-prompt rule 3)
def _is_claude(comm: str) -> bool:
    from shipmiracle import owner
    return owner.is_claude(comm)


def __getattr__(name):
    if name == "OWNER_HOSTS":                                 # the list lives in shipmiracle/owner.py (the CLI shares the ancestry rule); loaded only when asked for
        from shipmiracle import owner
        return owner.OWNER_HOSTS
    raise AttributeError(name)


def is_owner_host(comm: str) -> bool:
    """Is this process name a place where the owner's own interactive chat is started from (see shipmiracle.owner.is_owner_host)? Injectable for tests (_OWNER_HOST_OVERRIDE)."""
    from shipmiracle import owner
    return owner.is_owner_host(comm, _OWNER_HOST_OVERRIDE)


def ancestry_ok(env):
    """(ok, why): the ancestry rule of shipmiracle.owner.ancestry (walk `ps` to pid 1: one `claude` at most, an owner host above it, no sdk entrypoint; a ps failure is refused).
    Tests replace ps by setting the module attribute _PS_CHAIN_OVERRIDE; NO environment variable can do that."""
    from shipmiracle import owner
    return owner.ancestry(env, _PS_CHAIN_OVERRIDE, _OWNER_HOST_OVERRIDE)


# ---------------------------------------------------------------- git facts for the hard-stop Ctx (only inside an active auto worktree)
def _git(wt, args, timeout=5):
    import subprocess
    env = {"PATH": "/usr/bin:/bin:/opt/homebrew/bin:/usr/local/bin", "HOME": os.path.expanduser("~"), "GIT_OPTIONAL_LOCKS": "0", "LC_ALL": "C"}
    try:
        r = subprocess.run(["git", "-C", wt, "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null"] + list(args), env=env, stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.decode("utf-8", "replace") if r.returncode == 0 else None


def _base_sha(info) -> str:
    """The commit the auto branch was created at: the first line of the branch reflog (`<zero> <sha> ... branch: Created from ...`). '' when unknown."""
    if not info["branch"] or not info["common"]:
        return ""
    t = _read_text(os.path.join(info["common"], "logs", "refs", "heads", *info["branch"].split("/")), 2048) or ""
    first = t.splitlines()[0] if t.splitlines() else ""
    parts = first.split(" ")
    return parts[1] if len(parts) > 2 and re.fullmatch(r"[0-9a-f]{40,64}", parts[1]) else ""


def _head_sha(info) -> str:
    t = _read_text(os.path.join(info["gd"], "HEAD"), 512) or ""
    m = re.match(r"ref:\s*(\S+)", t)
    if not m:
        return t.strip()[:64]
    ref = m.group(1)
    v = (_read_text(os.path.join(info["common"], *ref.split("/")), 256) or "").strip()
    if re.fullmatch(r"[0-9a-f]{40,64}", v):
        return v
    pk = _read_text(os.path.join(info["common"], "packed-refs"), 1 << 20) or ""
    for ln in pk.splitlines():
        if ln.endswith(" " + ref):
            return ln.split(" ")[0]
    return ""


def changed_files(ctx, info, base):
    """Paths changed since the CR base, including untracked and unstaged ones: `git status --porcelain -z -uall` (always fresh: unstaged edits do not touch
    the index) united with `git diff --name-only base HEAD`, which is cached on disk by (HEAD sha, base)."""
    out = set()
    st = _git(info["wt"], ["status", "--porcelain=v1", "-z", "-uall", "--no-renames"])
    if st is None:
        return None
    for ent in st.split("\0"):
        if len(ent) > 3:
            out.add(ent[3:])
    head = _head_sha(info)
    cache = os.path.join(ctx.state, "v1", "autopilot", "changed-%s.json" % info["pid"])
    c = ctx.memo_json(cache, {})
    names = c.get("names") if isinstance(c, dict) and c.get("head") == head and c.get("base") == base and head else None
    if not isinstance(names, list):
        d = _git(info["wt"], ["diff", "--name-only", "-z", "--no-renames", base or "HEAD", "HEAD"]) if base else ""
        if d is None:
            return None
        names = [x for x in d.split("\0") if x]
        if head:
            try:
                hio.atomic_json(cache, {"head": head, "base": base, "names": names})
            except OSError:
                pass
    out.update(x for x in names if isinstance(x, str))
    return out


# ---------------------------------------------------------------- the module
def autopilot(ctx):
    ev = ctx.event
    if ev == "UserPromptSubmit":
        return _on_prompt(ctx)
    if ev == "PreToolUse" and ctx.tool_name == "Bash":
        r = _nested_claude(ctx)
        if r is not None:
            return r
    info = auto_worktree(ctx)
    if info is None:
        return None
    return _in_auto(ctx, info)


def _bash_cmd(ctx):
    ti = ctx.data.get("tool_input")
    c = ti.get("command") if isinstance(ti, dict) else None
    return c if isinstance(c, str) else ""


def _live_run_anywhere(ctx):
    """True when an autopilot state file of ANY project says set / running / paused (an ended run does not count). Only reads files."""
    d = os.path.join(ctx.state, "v1", "autopilot")
    try:
        names = os.listdir(d)
    except OSError:
        return False
    for n in names:
        if not re.fullmatch(r"[0-9a-f]{12}\.json", n):
            continue
        t = _read_text(os.path.join(d, n), 8192)
        if t is None or not re.search(r'"state"\s*:\s*"ended"', t):
            return True                                                # live, or unreadable: counts
    return False


def _nested_claude(ctx):
    """Bash with a `claude` word: refused in every project (a) when it also carries a charter:/allow: argument or assigns/exports SHIPMIRACLE_* / CLAUDE*
    variables, at any nesting level (bash -c, eval, heredoc: the raw text is scanned), or (c) whenever `claude` is the command word of a simple command (every project, no run needed: a nested chat could
    otherwise speak as the owner to the stage module), or (b) whenever an autopilot state file of any project says
    set/running/paused (H4: `claude -p "..."` in a tool call is how a model would speak as the owner). Inside a running auto worktree the hard-stop path
    (H5 nested claude) also pauses the run, so (a) returns None there; (b) is refused there too."""
    cmd = _bash_cmd(ctx)
    if "claude" not in cmd.lower() or not _rx("NESTED_CLAUDE").search(cmd):
        return None
    args = bool(_rx("NESTED_ARGS").search(cmd) or _rx("CLAUDE_ENV").search(cmd))
    live = _live_run_anywhere(ctx)
    if re.fullmatch(r"\s*(?:\S*/)?claude\s+(?:--version|-v|--help|-h)\s*", cmd):
        return None                                        # the version / help text starts no chat
    cmdword = bool(_rx("CLAUDE_CMD").search(cmd))          # `claude` as a command word, whatever follows: a model starting another chat is never needed (every project)
    if not args and not live and not cmdword:
        return None
    info = auto_worktree(ctx)
    if args and info is not None:
        light = ctx.memo_json(os.path.join(ctx.state, "v1", "autopilot", info["pid"] + ".json"), None)
        if isinstance(light, dict) and light.get("state") in ("running", "paused"):
            return None
    _ev("autopilot.refused", {"why": "nested_claude", "tool": "Bash", "cmd_sha": _sha(cmd.encode("utf-8", "replace")), "live_run": live})
    return core.Result(block=True, reason=NESTED_TEXT)


# ---------------------------------------------------------------- UserPromptSubmit
def _on_prompt(ctx):
    prompt = ctx.data.get("prompt")
    if not isinstance(prompt, str) or not prompt:
        return None
    command = _rx("CMD_LINE").match(prompt[:200]) is not None
    if _handback(prompt):
        if _rx("CMD_ANYWHERE").search(prompt[:20000]):
            _ev("autopilot.ignored", {"why": "hand_back"})          # a charter:/allow: line inside a hand-back is data, never a command
        return None
    info = auto_worktree(ctx)
    if not command:
        if info is None:
            return None
        return _auto_prompt(ctx, info)
    return _command_prompt(ctx, prompt, info)


def _main_pid(ctx, info):
    """(pid, project name, project path) of the MAIN project this chat belongs to (the worktree's, or the folder's own)."""
    from shipmiracle import projects
    p = projects.resolve(ctx.pd, ctx.dev)
    if p is None:
        return None, "", ""
    return p.id, p.name, p.path


def _command_prompt(ctx, prompt, info):
    from shipmiracle.autopilot import charter as ch
    fields, err = ch.parse_line(prompt)
    if fields is None and err is None:
        return None
    ok, why = ancestry_ok(ctx.env)
    if not ok:
        _ev("autopilot.refused", {"why": "ancestry", "cmd": (fields or {}).get("cmd", "bad")})
        return _say("Charter NOT set: this prompt did not come from the owner's own top-level chat (%s)." % why)
    pid, name, _path = _main_pid(ctx, info)
    if pid is None:
        return _say("Charter NOT set: this folder is not a registered project.")
    if err:
        _ev("autopilot.refused", {"why": "parse"}, )
        return _say("Charter NOT set: %s" % err)
    cmd = fields["cmd"]
    try:
        if cmd == "set":
            r = ch.store_from_prompt(pid, prompt, ctx.session_id)
            return _say(r["echo"])
        if cmd == "off":
            r = ch.clear_from_prompt(pid, prompt)
            return _say("Charter cleared: %s is back to guided." % name if r["had_charter"] or r["was"] else "There was no charter to clear for %s." % name)
        if cmd == "show":
            return _say(_show(pid, name))
        if cmd == "allow":
            return _say(_allow(pid, fields["id"], name))
    except ch.CharterError as e:
        _ev("autopilot.refused", {"why": "charter", "cmd": cmd}, pid)
        return _say(("Allow NOT applied: %s" if cmd == "allow" else "Charter NOT set: %s") % e)
    return None


def _say(text):
    """The owner sees the text as systemMessage and the model gets it as additionalContext (spec section 1)."""
    return core.Result(system_message=text, additional_context=text)


def _show(pid, name):
    from shipmiracle import registry
    from shipmiracle.autopilot import charter as ch, state as S
    rec = registry.autopilot_of(registry.entry(pid))
    if rec is None:
        return "No charter is set for %s." % name
    c = rec["charter"]
    snap = S.snapshot(pid)
    return "Charter %s (sha %s, set by %s): %s. Run: %s." % (c["id"], rec["sha256"][:8], c["set_by"], ch.describe(c),
                                                            (snap["state"] + (" (%s)" % snap["ended_reason"] if snap and snap["ended_reason"] else "")) if snap else "no state")


def _allow(pid, hid, name=None):
    from shipmiracle import config
    from shipmiracle.autopilot import charter as ch, state as S
    from shipmiracle import UsageError
    if S.check(pid)[1] == "autopilot.full.enabled is off":
        raise ch.CharterError("autopilot.full.enabled is off: nothing can be allowed")
    from shipmiracle import owner
    if owner.proof_required():
        st0 = S.read(pid) if S.path(pid).exists() else None          # refuse an unknown stop BEFORE any Touch ID prompt
        stop0 = (st0 or {}).get("stop") or {}
        if not st0 or st0["state"] != "paused" or stop0.get("id") != hid:
            raise ch.CharterError("no paused run is stopped on %s" % hid)
        try:                                                           # Touch ID, with a hard cap: the owner's chat never hangs; on failure the line names the terminal command
            owner.touch("allow", "Shipmiracle: allow stop %s (one action, 10 minutes). Cancel if you did not just type this in your chat." % hid,
                        timeout=owner.HOOK_WAIT_S, hook_cmd="shipm autopilot allow %s --project %s" % (hid, name or "<project>"), min_tier="medium")
        except owner.OwnerRefused as e:
            raise ch.CharterError(str(e))
    try:
        cur = S.allow(pid, hid)
    except UsageError as e:
        raise ch.CharterError(str(e))
    al = cur["allow"][-1]
    _ev("autopilot.allowed", {"stop": al["id"], "cmd8": al["cmd_sha"][:8], "set_by": "chat"}, pid)
    return "Allowed %s once for that exact command, for 10 minutes; the autopilot is running again." % al["id"]


def _auto_prompt(ctx, info):
    """An owner prompt typed in an auto worktree chat: limits (H8). It never clears a pause (H4)."""
    pid = info["pid"]
    if not isinstance(ctx.memo_json(os.path.join(ctx.state, "v1", "autopilot", pid + ".json"), None), dict):
        return None
    from shipmiracle.autopilot import charter as ch, state as S
    st = S.settle(pid)
    if st is None or st["state"] in ("set", "ended"):
        return None
    msgs = []
    if st["state"] == "paused":
        # H4: an ordinary owner prompt does NOT resume a paused run (a prompt written by a nested claude looks the same). Only `allow: <id>` or the CLI.
        stop = st.get("stop") or {}
        if st.get("paused_reason") in ("checkpoint", "day_limit", "week_limit", "switch_off") and st.get("seg"):
            return _say("Autopilot is paused (%s). It goes on only after you type yes to `shipm autopilot checkpoint` in a terminal." % st["paused_reason"])
        return _say("Autopilot is paused%s. It resumes only with `allow: %s` typed in this chat, or `shipm autopilot resume` in a terminal." % (
            " (%s)" % (stop.get("rule") or st.get("paused_reason") or "stop"), stop.get("id") or "H-xxxxxx"))
    if st["state"] == "running":
        ok, _w, charter, st2 = S.check(pid)
        if ok:
            _session(S, pid, st2, ctx)
            lim = S.observe(pid, charter)
            r = _limit_end(ctx, S, pid, lim, None)
            if r:
                msgs.append(r)
    return _say(" ".join(msgs)) if msgs else None


def _record(pid):
    from shipmiracle import registry
    return registry.autopilot_of(registry.entry(pid))


def _session(S, pid, st, ctx):
    s8 = ctx.sid[:8]
    if s8 not in (st.get("sessions") or []):
        try:
            S.add_session(pid, s8)
        except Exception as e:
            hio.log_err("autopilot", e)


def _limit_name(lim):
    if not lim:
        return None
    if "week_cap_pct" in lim:                                # option C ("until I disable it"): the H8 labels are reused, _limit_end PAUSES instead of ending
        if lim["segment_due"]:
            return "time"
        if lim["budget_unknown"]:
            return "budget_unknown"
        if lim["budget_reached"]:
            return "budget"
        return "near" if lim["budget_near"] else None
    if lim["time_reached"]:
        return "time"
    if lim["budget_unknown"]:
        return "budget_unknown"
    if lim["budget_reached"]:
        return "budget"
    if lim["time_near"] or lim["budget_near"]:
        return "near"
    return None


def _limit_end(ctx, S, pid, lim, limit):
    """At 100 % (or an unreadable budget) end the run: ended:budget|time. Returns the owner text, or None."""
    limit = limit or _limit_name(lim)
    if limit not in ("time", "budget", "budget_unknown"):
        return None
    if lim and "week_cap_pct" in lim:                        # option C: a limit pauses the run, it never ends it; the owner's check-in clears it
        why = ("checkpoint" if lim["segment_due"] else "budget_unknown" if lim["budget_unknown"] else "week_limit" if lim["week_reached"] else "day_limit")
        if S.pause_for(pid, why):
            _ev("autopilot.paused", {"reason": why, "label": "H8-" + limit}, pid)
        return "Autopilot paused: %s." % {"checkpoint": "the daily check-in is due (shipm autopilot checkpoint)", "budget_unknown": "the weekly budget cannot be measured",
                                        "week_limit": "the weekly limit was reached", "day_limit": "today's limit was reached"}[why]
    reason = "time" if limit == "time" else "budget"
    cur = S.end(pid, reason)
    if cur is not None and cur.get("ended_reason") == reason:
        _ev("autopilot.ended", {"reason": reason, "label": "H8-" + limit}, pid)
    return "Autopilot ended: the %s limit was reached (%s)." % (reason, limit.replace("_", " "))


# ---------------------------------------------------------------- tool calls and stops inside an auto worktree
def _is_record_edit(ctx, info, tool):
    ti = ctx.data.get("tool_input")
    if tool not in FILE_TOOLS or not isinstance(ti, dict):
        return False
    p = ti.get("file_path") or ti.get("notebook_path") or ti.get("path")
    if not isinstance(p, str) or not p:
        return False
    full = p if os.path.isabs(p) else os.path.join(str(ctx.data.get("cwd") or info["wt"]), p)
    rp = _fold(os.path.realpath(full))
    root = _fold(os.path.realpath(info["wt"])).rstrip("/") + "/"
    return rp.startswith(root) and rp[len(root):] in RECORD


def _harmless_when_idle(ctx, info, tool):
    return tool in READ_TOOLS or _is_record_edit(ctx, info, tool)


def _in_auto(ctx, info):
    pid = info["pid"]
    sp = os.path.join(ctx.state, "v1", "autopilot", pid + ".json")
    light = ctx.memo_json(sp, None)
    if not isinstance(light, dict):
        if not os.path.lexists(sp):
            if not _charter_known(info):
                return None                                  # no run state and no charter in the registry: nothing to enforce (flow's own rules apply)
            return _no_state(ctx, info)                      # M4: a charter exists but the run state is missing: mutating tools are denied
        light = {}                                           # a state file that cannot be read: fail closed below
    if light.get("state") == "ended" and light.get("ended_reason") == "owner":
        return None                                          # the owner released the project: back to guided
    ev, tool = ctx.event, ctx.tool_name
    try:
        return _enforce(ctx, info)
    except Exception as e:
        hio.log_err("autopilot", e)
        hio.emit_event("autopilot.error", {"event": ev, "error": type(e).__name__}, project=pid)
        if ev == "PreToolUse" and tool not in HARMLESS:
            return core.Result(block=True, reason=CLOSED_TEXT % type(e).__name__)
        return None


def _charter_known(info) -> bool:
    """Does the registry hold a charter for this worktree's project? Unreadable registry = yes (fail closed): an auto worktree only exists for a run."""
    try:
        from shipmiracle import registry
        return registry.autopilot_of(registry.entry(info["pid"])) is not None
    except Exception as e:
        hio.log_err("autopilot", e)
        return True


def _no_state(ctx, info):
    if ctx.event != "PreToolUse" or ctx.tool_name in HARMLESS:
        return None
    _ev("autopilot.refused", {"why": "state_missing", "tool": ctx.tool_name[:40]}, info["pid"])
    return core.Result(block=True, reason=CLOSED_TEXT % "the run state file is missing")


def _enforce(ctx, info):
    from shipmiracle.autopilot import state as S
    pid, ev, tool = info["pid"], ctx.event, ctx.tool_name
    try:
        before = S.read(pid)
    except Exception:
        before = None
    if before is not None and before["state"] == "running" and S.now() >= before["expires"] and not S.is_standing(before):
        ok, why, charter, st = S.check(pid)                  # the time limit of a running run goes through H8 (event, deny text), not the silent settle below
        if charter is not None and why == "the run expired":
            return _running(ctx, info, S, charter, st)
    st = S.settle(pid)                                       # lapse / expiry / switch off are applied and persisted here
    if st is None:
        if ev == "PreToolUse" and tool not in HARMLESS:
            return core.Result(block=True, reason=CLOSED_TEXT % "the run state is damaged")
        return None
    if before is not None and before["state"] != st["state"]:
        if st["state"] == "ended":
            _ev("autopilot.ended", {"reason": st["ended_reason"], "label": "settle"}, pid)
        elif st["state"] == "paused":
            _ev("autopilot.paused", {"reason": st.get("paused_reason") or "settle"}, pid)
    state_name = st["state"]
    if state_name != "running":
        return _idle(ctx, info, st)
    if S.is_standing(st):                                    # D14 M2: only a standing run (option C) is checked; an A/B run never reaches this
        why = _sandbox_missing(ctx, info)
        if why:
            if S.pause_for(pid, "standing_off"):
                _ev("autopilot.paused", {"reason": "standing_off", "detail": "sandbox"}, pid)
            if ev == "PreToolUse" and tool not in HARMLESS:
                return core.Result(block=True, reason=PREREQ_TEXT % why)
            return None
        st = S.read(pid) or st
    ok, why, charter, st = S.check(pid)
    if not ok:
        S.pause(pid, None, "integrity")
        _ev("autopilot.paused", {"reason": "integrity"}, pid)
        if ev == "PreToolUse" and tool not in HARMLESS:
            return core.Result(block=True, reason=PREREQ_TEXT % why)
        return None
    return _running(ctx, info, S, charter, st)


SANDBOX_TEXT = ("the Claude sandbox is not switched on for this auto worktree (setting %s must be true in .claude/settings.local.json or .claude/settings.json of the worktree, or in your "
                "Claude settings): option C pauses until it is; your daily check-in continues it once it is on")


SANDBOX_CHANGED = ("the Claude sandbox settings of this auto worktree differ from the ones you tested in the sandbox test (P6-1; a wider allowance such as excluded commands, network or file access): "
                   "option C pauses; record the sandbox test again if the change is yours, then do the daily check-in")


def _json_file(path):
    """A settings file as a dict, or None (missing, unreadable, over 1 MB, not an object): never raises."""
    try:
        if os.path.getsize(path) > 1048576:
            return None
        import json
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def _sandbox_missing(ctx, info) -> str:
    """D14 M2 (design 2026-10-21 section 8): '' when the auto worktree's Claude sandbox setting named by the P6-1 record is ON, else the sentence for the pause. The nearest settings file that
    mentions the setting decides (worktree settings.local.json, then the worktree's settings.json, then the user's); only the literal true counts. Not checked on a separate account (the account
    itself is the boundary there). Read-only; a damaged file counts as missing (fail closed)."""
    from shipmiracle import owner
    if owner.separate_account():
        return ""
    name = owner.sandbox_setting()
    keys = name.split(".")
    cfg = ctx.env.get("CLAUDE_CONFIG_DIR") or os.path.join(ctx.home, ".claude")
    for p in (os.path.join(info["wt"], ".claude", "settings.local.json"), os.path.join(info["wt"], ".claude", "settings.json"), os.path.join(cfg, "settings.json")):
        if not os.path.lexists(p):
            continue
        d = _json_file(p)
        if d is None:
            return SANDBOX_TEXT % name                       # a settings file that exists but cannot be read (damaged, over 1 MB, not an object) is not "off": the run pauses
        v = d
        for k in keys:
            v = v.get(k) if isinstance(v, dict) else None
        if v is not None:
            if v is not True:
                return SANDBOX_TEXT % name
            want = owner.sandbox_hash_recorded()
            if want and owner.sandbox_digest(d.get(keys[0])) != want:
                return SANDBOX_CHANGED
            return ""
    return SANDBOX_TEXT % name


def _idle(ctx, info, st):
    """A run that is paused, ended (not by the owner) or only 'set': Read/Grep/Glob/LS and RECORD edits only; Stop and the other events pass."""
    ev, tool = ctx.event, ctx.tool_name
    if ev != "PreToolUse":
        return None
    if _harmless_when_idle(ctx, info, tool):
        return None
    name = st["state"]
    if name == "paused":
        s = st.get("stop") or {}
        text = PAUSED_TEXT % (s.get("rule") or st.get("paused_reason") or "stop", s.get("id") or "-")
    elif name == "ended":
        text = ENDED_TEXT % st["ended_reason"]
    else:
        text = NOT_RUNNING_TEXT % name
    _ev("autopilot.refused", {"why": "not_running", "state": name, "tool": tool[:40]}, info["pid"])
    return core.Result(block=True, reason=text)


def _cfg_values(text, section, key):
    """Values of `key` in `[section]` of a git config text, in order (cheap parser: section headers, key = value, quotes stripped)."""
    out = []; cur = ""
    for ln in (text or "").splitlines():
        t = ln.strip()
        if t.startswith("["):
            cur = t.split("]", 1)[0].lstrip("[").strip().lower()
            cur = cur.split(None, 1)[0] if cur and not cur.startswith('"') else cur
            continue
        m = re.match(r"([A-Za-z][\w-]*)\s*=\s*(.*?)\s*$", t)
        if m and cur == section and m.group(1).lower() == key:
            v = m.group(2)
            if len(v) >= 2 and v[0] == v[-1] == '"':
                v = v[1:-1]
            out.append(v)
    return out


def hooks_problem(state, info) -> str:
    """'' when the worktree runs git with the engine's empty hooks folder (`extensions.worktreeConfig=true` in the shared config and
    `core.hooksPath=<state>/v1/autopilot/nohooks` in this worktree's own config.worktree, the folder empty), else the reason (C1). Only file reads."""
    cfg = _read_text(os.path.join(info["common"], "config"), 1 << 20) or ""
    if not [v for v in _cfg_values(cfg, "extensions", "worktreeconfig") if v.lower() in ("true", "yes", "on", "1")]:
        return "extensions.worktreeConfig is not on"
    wc = _read_text(os.path.join(info["gd"], "config.worktree"), 1 << 16)
    if wc is None:
        return "this worktree has no config.worktree"
    if re.search(r"(?im)^\s*\[\s*include", wc):
        return "config.worktree includes another file"
    vals = _cfg_values(wc, "core", "hookspath")
    want = os.path.join(state, "v1", "autopilot", "nohooks")
    if not vals or os.path.realpath(vals[-1]) != os.path.realpath(want):
        return "core.hooksPath is not the engine's empty hooks folder"
    try:
        if os.path.islink(want) or not os.path.isdir(want) or os.listdir(want):
            return "the engine's hooks folder is not an empty folder"
    except OSError:
        return "the engine's hooks folder cannot be read"
    return ""


def _prereq_fast(ctx, info, charter):
    """The level prerequisites that cost nothing to check on every call (spec 1; the full list, with the network-free remote check, runs at set/start/
    resume). [] = fine."""
    bad = []
    if core.mode() != "v1":
        bad.append("autopilot_needs_gate: hooks.dispatcher is not v1")
    eng = core.config_get("gate.engine", "legacy")
    if eng != "playbook":
        bad.append("autopilot_needs_gate: gate.engine is not playbook")
    from shipmiracle.playbook import gate
    rules = gate.stage_rules(info["main"])
    if rules is None:
        bad.append("the project has no playbook")
    else:
        if rules.get("level") != "strict":
            bad.append("flow level is %s, not strict" % rules.get("level"))
        if not rules.get("trusted"):
            bad.append("the playbook is not trusted")
        if rules.get("type") != "software" or rules.get("autopilot") != "full":
            bad.append("the playbook is not a software playbook with autopilot full")
    hp = hooks_problem(ctx.state, info)
    if hp:
        bad.append("autopilot_needs_gate: git hooks are not isolated (%s)" % hp)
    if not _rx("BRANCH_RE").fullmatch(info["branch"] or ""):
        bad.append("the session is not on an auto/CR-n branch (HEAD is %s)" % (info["branch"] or "detached"))
    else:
        t = _read_text(os.path.join(info["common"], "config"), 1 << 20) or ""
        urls = []; insec = False
        for ln in t.splitlines():                              # every url and pushurl of every remote (M3), not only the first
            tl = ln.strip()
            if tl.startswith("["):
                insec = bool(re.match(r'\[remote\s+"', tl))
            elif insec:
                m = re.match(r"(?i)(?:push)?url\s*=\s*(\S+)", tl)
                if m:
                    urls.append(m.group(1))
        if urls:
            from shipmiracle.autopilot import visibility
            from shipmiracle.autopilot import state as S
            nz = [u for u in urls if not visibility.is_private(u, S.now())]
            if nz:
                bad.append("a git remote is not cached as private")
    return bad, rules


def _allowed_ids(info, charter):
    """H6: the requests the run may work on: ends, plus (standing charter) the owner's admissions that are still valid."""
    ids = list(charter["ends"])
    if charter.get("until") == "disabled":
        try:
            from shipmiracle.autopilot import standing
            ids = standing.allowed_ids(info["pid"], info["main"], charter)
        except Exception as e:
            hio.log_err("autopilot", e)
    return ids


def _hctx(ctx, info, charter, rules, limit, active_cr, engine_block):
    from shipmiracle.autopilot import hardstop as H
    from shipmiracle import config
    tool = ctx.tool_name
    ti = ctx.data.get("tool_input") if isinstance(ctx.data.get("tool_input"), dict) else {}
    cmd = ti.get("command") if tool == "Bash" and isinstance(ti.get("command"), str) else ""
    base = _base_sha(info)
    h = H.Ctx(root=info["wt"], base_sha=base, scope=list(charter["scope"]), deps_mode=charter["deps"]["mode"], deps_names=list(charter["deps"].get("names") or []),
              test_paths=list(TEST_PATHS), dep_files=list((rules or {}).get("deps") or []), active_cr=active_cr, ends=_allowed_ids(info, charter),
              auto_branch=info["branch"], limit=limit, engine_block=engine_block)
    if _TMP_ROOTS_OVERRIDE is not None:
        h.tmp_roots = list(_TMP_ROOTS_OVERRIDE)               # tests only (module attribute, never an env var): their world lives under the system tmp folder
    hp = []
    for v in _cfg_values(_read_text(os.path.join(info["common"], "config"), 1 << 20) or "", "core", "hookspath"):
        if v and not v.startswith(("/", "~")) and ".." not in v.split("/"):
            hp.append(v.strip("/"))
    h.hooks_rel = hp                                           # the main config's core.hooksPath folder inside the tree (C1: a hook-running git command is H5 when it changed)
    mcp = config.get("autopilot.mcp_allow")
    h.mcp_allow = [x for x in mcp if isinstance(x, str)] if isinstance(mcp, list) else []
    tc = _read_text(os.path.join(info["wt"], ".claude", "test-command"), 4096)
    h.test_command = tc.strip() if tc else ""
    if cmd:
        def _changed(_ctx=ctx, _info=info, _base=base):
            ch = changed_files(_ctx, _info, _base)
            if ch is None:
                raise RuntimeError("git status failed: the changed files are unknown")      # _in_auto turns this into a refusal of mutating tools
            return ch
        h.changed = _changed                                  # lazy: hardstop calls it only for rules that look at changed files (scripts, runners, npm run)
        if re.search(r"\bgit\b", cmd) and re.search(r"\b(commit|reset|rebase|checkout|switch|cherry-pick|revert|merge)\b", cmd):
            n = _git(info["wt"], ["rev-list", "--count", "%s..HEAD" % base]) if base else None
            h.ahead = int(n.strip()) if n and n.strip().isdigit() else None
            h.ref_ok = lambda ref, _b=base, _w=info["wt"], _br=info["branch"]: _ref_ok(_w, _b, _br, ref)
    return h


def _ref_ok(wt, base, branch, ref) -> bool:
    """Is this ref the auto branch or a commit after the CR base on it? (git reset/rebase targets.)"""
    if ref in ("HEAD", "@", branch, "refs/heads/" + branch):
        return True
    if not base or not re.fullmatch(r"[A-Za-z0-9_./~^@{}-]{1,200}", ref or "") or ref.startswith("-"):
        return False
    sha = _git(wt, ["rev-parse", "--verify", "-q", ref + "^{commit}"])
    if not sha:
        return False
    sha = sha.strip()
    return (_git(wt, ["merge-base", "--is-ancestor", base, sha]) is not None) and (_git(wt, ["merge-base", "--is-ancestor", sha, "HEAD"]) is not None)


def _active_cr(info, st):
    """(cr id, stage, blocked) of the worktree's active CR from the engine log (read-only), falling back to the state file's cr."""
    try:
        from shipmiracle.playbook import engine, store
        work = store.load(info["wt"])
        cr = engine.active_cr(work)
        if cr:
            return cr["id"], cr.get("stage"), cr.get("blocked")
    except Exception as e:
        hio.log_err("autopilot", e)
    return (st.get("cr") if isinstance(st.get("cr"), str) else None), None, None


def _allow_mark_path(ctx, pid):
    return os.path.join(ctx.state, "v1", "autopilot", "allowed-%s.json" % pid)


def _running(ctx, info, S, charter, st):
    ev, tool, pid = ctx.event, ctx.tool_name, info["pid"]
    ti = ctx.data.get("tool_input") if isinstance(ctx.data.get("tool_input"), dict) else {}
    _session(S, pid, st, ctx)
    lim = S.observe(pid, charter)
    limit = _limit_name(lim)
    msgs = []
    # prerequisites (paused, not ended: the owner can fix them and resume)
    bad, rules = _prereq_fast(ctx, info, charter)
    if bad and limit not in ("time", "budget", "budget_unknown"):
        S.pause(pid, None, "prereq")
        _ev("autopilot.paused", {"reason": "prereq", "detail": bad[0][:120]}, pid)
        if ev == "PreToolUse" and tool not in HARMLESS:
            return core.Result(block=True, reason=PREREQ_TEXT % bad[0])
        return None
    cr, stage, blocked = (None, None, None)
    if tool in AGENT_TOOLS or ev == "SubagentStop":
        cr, stage, blocked = _active_cr(info, st)
    else:
        cr = st.get("cr") if isinstance(st.get("cr"), str) else None
    from shipmiracle.autopilot import hardstop as H
    engine_block = "verify_twice" if ev == "SubagentStop" and blocked == "verify_twice" else None
    hc = _hctx(ctx, info, charter, rules, limit, cr, engine_block)
    cwd = ctx.data.get("cwd") if isinstance(ctx.data.get("cwd"), str) else info["wt"]
    stops = H.check(ev, tool, ti, cwd, hc)
    ended_text = None
    if limit in ("time", "budget", "budget_unknown"):
        ended_text = _limit_end(ctx, S, pid, lim, limit)
        stops = [s for s in stops if s.rule == "H8"] + [s for s in stops if s.rule != "H8"]
    stops = _filter_allowed(ctx, S, pid, st, stops, ev)
    if not stops:
        if ended_text and ev in ("Stop", "UserPromptSubmit", "SubagentStop"):
            return core.Result(system_message=ended_text)
        return None
    s = stops[0]
    near_only = s.rule == "H8" and limit == "near"
    if s.rule == "H8" and not near_only:
        cur_state = "paused" if S.is_standing(st) else "ended"
    elif near_only:
        cur_state = "running"
    else:
        cur_state = "paused"
    if cr is None or stage is None:
        cr2, stage2, _b = _active_cr(info, st)
        cr, stage = cr or cr2, stage or stage2
    _ev("autopilot.hard_stop", {"rule": s.rule, "label": s.label or s.rule, "id": s.id, "cr": cr, "stage": stage, "tool": tool[:40] or ev, "cmd_sha": s.cmd_sha,
                                "excerpt": s.excerpt[:200], "charter_sha": st["charter_sha"], "state": cur_state}, pid)
    if cur_state == "paused":
        S.pause(pid, {"id": s.id, "rule": s.label or s.rule, "ts": int(S.now()), "text": s.excerpt, "cmd_sha": s.cmd_sha}, "hard_stop" if s.rule != "H7" else "cr_blocked")
    if ev == "Stop":
        return core.Result(system_message=ended_text) if ended_text else None      # a Stop is never blocked; H8 ended the run above
    if ev == "SubagentStop":
        return core.Result(system_message="Autopilot paused: %s" % s.text)
    if ev == "UserPromptSubmit":
        return core.Result(system_message=ended_text or s.text)
    return core.Result(block=True, reason=s.text)


def _filter_allowed(ctx, S, pid, st, stops, ev):
    """Owner releases: a stop whose cmd sha has a live one-shot allow (state.allow, bound to that exact command) passes once. H8 and H7 are never
    allowed. The allow is consumed only when ALL non-H8 stops of the call are covered. PostToolUse honours the mark the PreToolUse left."""
    if not stops:
        return stops
    now = S.now()
    if ev == "PostToolUse":
        mk = ctx.memo_json(_allow_mark_path(ctx, pid), {})
        live = {k for k, v in (mk or {}).items() if isinstance(v, (int, float)) and v > now} if isinstance(mk, dict) else set()
        return [s for s in stops if s.cmd_sha not in live]
    hard = [s for s in stops if s.rule in ("H8", "H7")]
    soft = [s for s in stops if s.rule not in ("H8", "H7")]
    if hard or not soft:
        return stops
    avail = {}
    for a in st.get("allow") or []:
        if isinstance(a, dict) and isinstance(a.get("until"), (int, float)) and a["until"] > now:
            avail[a.get("cmd_sha")] = avail.get(a.get("cmd_sha"), 0) + 1
    need = {}
    for s in soft:
        need[s.cmd_sha] = need.get(s.cmd_sha, 0) + 1
    if any(avail.get(k, 0) < n for k, n in need.items()):
        return stops
    for s in soft:
        if S.consume_allow(pid, s.cmd_sha):
            _ev("autopilot.allow_used", {"stop": s.id, "rule": s.label or s.rule, "cmd8": s.cmd_sha[:8]}, pid)
    if ev == "PreToolUse" and ctx.tool_name in FILE_TOOLS:
        try:
            mk = ctx.memo_json(_allow_mark_path(ctx, pid), {})
            mk = dict(mk) if isinstance(mk, dict) else {}
            for s in soft:
                mk[s.cmd_sha] = now + ALLOW_MARK_S
            hio.atomic_json(_allow_mark_path(ctx, pid), {k: v for k, v in mk.items() if v > now})
        except OSError as e:
            hio.log_err("autopilot", e)
    return []


core.register("UserPromptSubmit", "autopilot", None, autopilot)
core.register("PreToolUse", "autopilot", None, autopilot)
core.register("PostToolUse", "autopilot", None, autopilot)
core.register("SubagentStop", "autopilot", None, autopilot)
core.register("Stop", "autopilot", None, autopilot)
