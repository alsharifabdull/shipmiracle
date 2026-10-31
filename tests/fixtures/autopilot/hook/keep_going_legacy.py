"""keep_going (spec 2.2, Stop): ported from the legacy shell hook with identical decisions and texts. When the last assistant message announces the
next step and asks nothing, Claude is sent back to do it (block). Away mode (state/away.json fresh, no risky words) takes the safe option instead of
waiting and logs it to away-decisions.jsonl. Fires at most once per stop (stop_hook_active). The transcript is read whole (as before) unless
config hooks.keep_going_tail_bytes (owner decision O6) bounds it. Import budget: os, json, re, time only."""
from __future__ import annotations

import json
import os
import re
import time

from . import core
from . import io as hio

ACTIVE = re.compile(r'"stop_hook_active": *true')
ASKS = re.compile(r"\?|\b(tell me|let me know|describe|send me|send a|your call|would you like|do you want|"
                  r"which (one|do you)|approve|confirm|say \"|reply|waiting (for|on) you|"
                  r"if you (don'?t|do|want|need|prefer|would|like)|I'?ll leave (it|them|that|this)|nothing (else|more) (to do|needed))\b", re.I)
RISKY = re.compile(r"\b(delet\w+|remov\w+|force|push\w*|publish\w*|deploy\w*|releas\w+|pay\w*|purchas\w+|buy|spend|billing|credential\w*|password\w*|secret\w*|token\w*|permission\w*|security|drop|wipe|erase|overwrit\w+|reset --hard|production|irreversib\w+)\b", re.I)
PROMISE = re.compile(r"\b(I'?ll|I will|I'm going to|Next,? I|Then I|Now I'?ll|Let me|Going to|about to)\b[^.\n]{0,160}\.?\s*$", re.I)
DONE = re.compile(r"\b(done|finished|complete[d]?|all (tests )?pass(ed)?|nothing (else|left)|ready for (your )?review)\b", re.I)
AWAY_TEXT = ("The owner is away (lid closed or idle). Do not wait: choose the option you recommended (the safest, reversible one), "
             "continue, and record the decision in docs/STATUS.md under 'Decisions taken while away'.")
PUSH_TEXT = ("You ended your turn right after saying what you will do next. Do it now in this turn; "
             "stop only when the work is finished, you are blocked, or you need a decision from the owner.")


def read_tail(path: str, max_bytes: int = 0):
    """Lines of the transcript as text. max_bytes <= 0: the whole file (parity with the old script). Otherwise only the last max_bytes bytes, and the
    first line of a cut-off tail (it is partial) is dropped."""
    if max_bytes <= 0:
        with open(path, errors="ignore", encoding="utf-8") as f:
            for line in f:
                yield line
        return
    with open(path, "rb") as f:
        size = os.fstat(f.fileno()).st_size
        cut = size > max_bytes
        if cut:
            f.seek(size - max_bytes)
        data = f.read(max_bytes)
    lines = data.decode("utf-8", "ignore").split("\n")
    for line in (lines[1:] if cut else lines):
        yield line


def last_message(path: str, max_bytes: int = 0) -> str:
    last = ""
    for line in read_tail(path, max_bytes):
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("type") == "assistant":
            c = (r.get("message") or {}).get("content") or []
            t = " ".join(x.get("text", "") for x in c if isinstance(x, dict) and x.get("type") == "text").strip()
            if t:
                last = t
    return last


def _tail_bytes(ctx) -> int:
    v = ctx.config("hooks.keep_going_tail_bytes", 0)
    return v if isinstance(v, int) and not isinstance(v, bool) and v > 0 else 0


def _away(ctx) -> bool:
    try:
        with open(os.path.join(ctx.state, "away.json")) as f:
            aw = json.load(f)
        return bool(aw.get("away") and time.time() - aw.get("ts", 0) < 120)
    except Exception:
        return False


def keep_going(ctx):
    if ACTIVE.search(ctx.raw.decode("utf-8", "replace")):
        return None
    tp = ctx.data.get("transcript_path", "")
    tp = tp if isinstance(tp, str) else str(tp)
    tp = tp.rstrip("\n")
    if not (tp and os.path.isfile(tp)):
        return None
    try:
        last = last_message(tp, _tail_bytes(ctx))
    except (AttributeError, TypeError):                 # an odd transcript line shape: the old inline python died without a decision
        return None
    tail = last[-400:]
    asks_owner = ASKS.search(last[-900:])
    if asks_owner and last:
        if _away(ctx) and not RISKY.search(last[-900:]):
            try:                                        # one line per decision for bin/away-decisions; a failed write never blocks the hook
                proj = os.path.basename((ctx.env.get("CLAUDE_PROJECT_DIR") or os.getcwd()).rstrip("/"))
                hio.append_line(os.path.join(ctx.state, "away-decisions.jsonl"),
                                json.dumps({"ts": int(time.time()), "project": proj, "question": re.sub(r"\s+", " ", last)[-300:].strip()}), inside_root=ctx.state)
            except OSError as e:
                hio.log_err("keep_going", e)
            return core.Result(block=True, reason=AWAY_TEXT, exit_code=2)
    if not tail or asks_owner:
        return None                                     # waiting on the owner: a real stop
    if PROMISE.search(tail) and not DONE.search(tail[-200:]):
        return core.Result(block=True, reason=PUSH_TEXT, exit_code=2)
    return None


core.register("Stop", "keep_going", None, keep_going)
