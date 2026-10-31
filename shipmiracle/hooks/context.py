"""context (spec 2.2, UserPromptSubmit; runs only when config tokens.nudge is on): ported from legacy context-nudge.sh with identical decisions, texts and state.
Reads the last 64 KB of the chat transcript, takes the last main-chain assistant usage (input + cache write + cache read = the context the model just saw),
keeps state/context.<session>.json (0600, same compact format as the shell script so both read each other's file), and gives a soft nudge at 200k tokens and a
strong one at 300k, once per session per level. Never blocks. Safety: the transcript must be a regular file (not a symlink) named *.jsonl inside the real
~/.claude/projects. Import budget: os, json, re, time only."""
from __future__ import annotations

import json
import os
import re
import time

from . import core

TAIL = 65536
SOFT, STRONG = 200000, 300000
RE_EV = re.compile(r'"hook_event_name"\s*:\s*"([A-Za-z]+)"')
RE_TP = re.compile(r'"transcript_path"\s*:\s*"([^"\\]+)"')
RE_SID = re.compile(r'"session_id"\s*:\s*"([A-Za-z0-9_-]{1,64})"')
RE_CWD = re.compile(r'"cwd"\s*:\s*"([^"\\]*)"')
RE_PROJECT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}\Z")
RE_USAGE = re.compile(rb'"usage" *: *\{')
RE_ROLE = re.compile(rb'"role" *: *"assistant"')
RE_SIDE = re.compile(rb'"isSidechain" *: *true')
RE_PREV_TOKENS = re.compile(r'"tokens":([0-9]+)')
RE_PREV_LEVEL = re.compile(r'"level":"([a-z]+)"')
SOFT_TEXT = ("Context is %dk tokens (long chats cost more per message). Finish this step, then suggest once, briefly, that the owner start a fresh chat with a handoff: "
             "update docs/STATUS.md first. Do not stop or refuse work; the owner decides.")
STRONG_TEXT = ("Context is %dk tokens (very long). After this step, strongly recommend a handoff and a fresh chat: update docs/STATUS.md (what changed, verified, next, handoff) "
               "and commit, then tell the owner to open a fresh chat. Never stop or refuse work because of this; the owner decides.")


def _num(u: bytes, key: bytes) -> int:
    m = re.search(b'"' + key + b'" *: *([0-9]+)', u)
    return int(m.group(1)) if m else 0


def last_usage(data: bytes, skip_first: bool):
    """(input, cache write, cache read) of the last main-chain assistant line in the tail, or None."""
    last = None
    for i, line in enumerate(data.split(b"\n")):
        if i == 0 and skip_first:
            continue
        if RE_USAGE.search(line) and RE_ROLE.search(line) and not RE_SIDE.search(line):
            last = line
    if last is None:
        return None
    u = last[RE_USAGE.search(last).start():]
    return _num(u, b"input_tokens"), _num(u, b"cache_creation_input_tokens"), _num(u, b"cache_read_input_tokens")


def _transcript(tp: str):
    """Real path of an allowed transcript, or None."""
    if not (tp.startswith("/") and tp.endswith(".jsonl") and "\n" not in tp) or os.path.islink(tp):
        return None
    dirpart = tp.rsplit("/", 1)[0]
    dir_ = os.path.realpath(dirpart or "/") if dirpart else os.path.realpath(".")
    root = os.path.realpath(os.path.join(os.path.expanduser("~"), ".claude/projects"))
    if not os.path.isdir(dir_) or not os.path.isdir(root) or not (dir_ + "/").startswith(root + "/"):
        return None
    f = dir_ + "/" + tp.rsplit("/", 1)[-1]
    return f if os.path.isfile(f) and not os.path.islink(f) else None


def _project(cwd: str, home: str) -> str:
    dev = home + "/Developer/"
    project = ""
    if cwd.startswith(dev):
        rest = cwd[len(dev):]
        project = rest.split("/", 1)[0]
        if project == ".worktrees":
            rest = rest[len(".worktrees/"):] if rest.startswith(".worktrees/") else ""
            project = rest.split("/", 1)[0]
    return project if RE_PROJECT.match(project) else ""


def _write_state(path: str, tmp: str, text: str) -> None:
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "w") as f:
            fd = -1
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def context(ctx):
    text = ctx.raw.decode("utf-8", "surrogateescape")
    if not text.strip():
        return None
    m = RE_EV.search(text)
    if m and m.group(1) != "UserPromptSubmit":
        return None
    m = RE_TP.search(text)
    sm = RE_SID.search(text)
    if not m or not sm:
        return None
    tp, sid = m.group(1), sm.group(1)
    cm = RE_CWD.search(text)
    cwd = cm.group(1) if cm else ""
    f = _transcript(tp)
    if f is None:
        return None
    size = os.path.getsize(f)
    skip = size > TAIL
    with open(f, "rb") as fh:
        if skip:
            fh.seek(size - TAIL)
        data = fh.read(TAIL)
    us = last_usage(data, skip)
    if us is None:
        return None
    tokens = sum(us)
    if tokens <= 0:
        return None
    level = "strong" if tokens >= STRONG else "soft" if tokens >= SOFT else "none"
    project = _project(cwd, ctx.home)
    state = ctx.state
    sf = "%s/context.%s.json" % (state, sid)
    ptok, plevel, n_soft, n_strong = -1, "", False, False
    if os.path.isfile(sf) and not os.path.islink(sf):
        try:
            with open(sf, errors="ignore") as fh:
                prev = fh.read()
            pm = RE_PREV_TOKENS.search(prev)
            ptok = int(pm.group(1)) if pm else -1
            lm = RE_PREV_LEVEL.search(prev)
            plevel = lm.group(1) if lm else ""
            n_soft, n_strong = '"soft":true' in prev, '"strong":true' in prev
        except OSError:
            pass
    say = ""
    if level == "soft" and not n_soft:
        say, n_soft = "soft", True
    elif level == "strong" and not n_strong:
        say, n_strong, n_soft = "strong", True, True
    if ptok < 0 or level != plevel or abs(tokens - ptok) > 5000 or say:
        if not os.path.isdir(state):
            from . import io as hio
            hio.ensure_dir(state)
        if os.path.isdir(state) and not os.path.islink(state):
            body = json.dumps({"project": project, "session": sid, "tokens": tokens, "level": level, "ts": int(time.time()),
                               "nudged": {"soft": n_soft, "strong": n_strong}}, separators=(",", ":")) + "\n"
            _write_state(sf, "%s/.context.%s.%d.tmp" % (state, sid, os.getpid()), body)
    if say:
        return core.Result(additional_context=(SOFT_TEXT if say == "soft" else STRONG_TEXT) % (tokens // 1000))
    return None


core.register("UserPromptSubmit", "context", None, context)
