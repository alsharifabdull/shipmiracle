"""Runs the checklist: evaluate (read-only), render (text / JSON), and the idempotent apply loop of `shipm init`. State that is not a write to the
machine lives in <state>/v1/init.json ({"v":1,"skipped":{id: ts},"engine_dir": ...}); every write to the machine is a manifest step."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from .. import ShipmiracleError, UsageError, paths, platform as aplat, state
from . import guard_home, manifest, rows

SCHEMA_V = 1
STATES = ("green", "red", "skipped", "advisory", "never")


def fake_tty() -> bool:
    """Test seam: SHIPMIRACLE_FAKE_TTY=1 lets a sandboxed run read its answers from a piped stdin as if it were a terminal."""
    return os.environ.get("SHIPMIRACLE_FAKE_TTY") == "1" and paths.sandboxed()


class Paused(Exception):
    """The input ended (Ctrl-D, closed stdin) while `shipm init` was asking: stop at once and apply nothing more; the next `shipm init` resumes."""


class Ctx:
    def __init__(self, yes=False, say=None, engine=None, adopt=False, ask=None, ascii_mode=None):
        self._ask = ask                   # tests: fn(prompt) -> answer text, used instead of input()
        self.ascii = ascii_mode           # None = decide from the output encoding
        self.pause_on_eof = False         # True during the three-stage `shipm init`: the end of the input at ANY question stops the run (Paused)
        self.eof = False                  # the input has ended
        self.explicit = False             # True while `shipm init --step ROW` runs that one row
        self.yes = yes
        self.adopt = adopt                # --adopt: take over a pre-existing non-empty folder (--yes alone never does)
        self.say = say or (lambda s: sys.stdout.write(s + "\n"))
        self.engine = Path(engine) if engine is not None else paths.workspace_dir()
        self.init_state = load_init()

    def save_init(self):
        save_init(self.init_state)

    def interactive(self) -> bool:
        """True when questions may be asked: not with --yes, and only with a terminal (or a test answer source)."""
        if self.yes:
            return False
        return self._ask is not None or (sys.stdin is not None and sys.stdin.isatty()) or fake_tty()

    def input(self, prompt) -> str:
        try:
            if self._ask is not None:
                return self._ask(prompt)
            return input(prompt)
        except EOFError:
            self.eof = True
            self.say("")                  # the cursor sits after the prompt: finish the line
            raise

    def _eof(self):
        """Called where a question was cut off by the end of the input: pause the three-stage run, otherwise the answer is simply no."""
        if self.pause_on_eof:
            raise Paused()
        return False

    def _tty(self) -> bool:
        return self._ask is not None or (sys.stdin is not None and sys.stdin.isatty()) or fake_tty()

    def confirm(self, question) -> bool:
        if self.yes:
            return True
        if self._tty():
            try:
                return self.input("  %s [y/N] " % question).strip().lower() in ("y", "yes")
            except EOFError:
                return self._eof()
        self.say("  %s  (no terminal: re-run with --yes to say yes)" % question)
        return False

    def confirm_adopt(self, question) -> bool:
        """A pre-existing non-empty folder is taken over only with --adopt, or when the word `adopt` is typed at a terminal. --yes alone is NOT enough (L9)."""
        if self.adopt:
            return True
        if not self.yes and self._tty():
            try:
                return self.input("  %s Type adopt to take it over: " % question).strip().lower() == "adopt"
            except EOFError:
                return self._eof()
        self.say("  %s  (refused: re-run with --adopt if this folder is yours)" % question)
        return False

    def confirm_word(self, question, word="yes") -> bool:
        """A typed answer: the whole word must be typed (a bare Enter or `y` is no). --yes counts as the typed word (an explicit flag on a named step)."""
        if self.yes:
            return True
        if self._tty():
            try:
                return self.input("  %s Type %s to confirm: " % (question, word)).strip().lower() == word
            except EOFError:
                return self._eof()
        self.say("  %s  (no terminal: re-run with --yes to say yes)" % question)
        return False


def init_path() -> Path:
    return state.root() / "init.json"


def load_init() -> dict:
    """<state>/v1/init.json, read-only. A damaged file is treated as empty (it only holds skips)."""
    try:
        d = json.loads(state.read_bytes_nofollow(init_path()).decode("utf-8"))
    except (FileNotFoundError, ValueError, OSError):
        return {"v": 1, "skipped": {}}
    if not isinstance(d, dict) or not isinstance(d.get("skipped", {}), dict):
        return {"v": 1, "skipped": {}}
    d.setdefault("skipped", {})
    d["skipped"] = {k: v for k, v in d["skipped"].items() if k in rows.BY_ID}   # a row that no longer exists (an old optional one) is dropped on the next save
    d["v"] = 1
    return d


def save_init(d) -> None:
    state.ensure_root()
    state.atomic_write(init_path(), (json.dumps(d, sort_keys=True, indent=1) + "\n").encode("utf-8"), 0o600)


def find(ref):
    """The row for an id or a number."""
    ref = str(ref).strip()
    if ref.isdigit():
        for r in rows.ROWS:
            if r["n"] == int(ref):
                return r
    if ref in rows.BY_ID:
        return rows.BY_ID[ref]
    raise UsageError("unknown row %r (ids: %s)" % (ref[:30], ", ".join(r["id"] for r in rows.ROWS)))


DETAIL_MAX = 400
_TAILS = ("Fix it with:", "Next step:", " Choose a folder", "Run: ", " Run:", "\u2192 run:")
_CTRL = __import__("re").compile("\x1b\\[[0-9;?]*[ -/]*[@-~]|\x1b\\][^\x07\x1b]*(?:\x07|\x1b\\\\)|\x1b[@-Z\\\\-_]|[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def clean_text(text) -> str:
    """Escape sequences and control characters removed (a detail may quote what a tool printed); newlines and tabs become spaces."""
    return _CTRL.sub("", str(text).replace("\n", " ").replace("\t", " ").replace("\r", " "))


def cut_detail(text, limit=DETAIL_MAX):
    """Clean text, never longer than min(limit, len); cut at a word boundary with '...'; the fix / next-step sentence at the end is kept whole when it fits."""
    text = clean_text(text)
    if len(text) <= limit:
        return text
    head, tail = text, ""
    for m in _TAILS:
        i = text.rfind(m)
        if i > 0 and len(text) - i <= limit - 8:
            head, tail = text[:i].rstrip(), text[i:].lstrip()
            break
    room = limit - len(tail) - (1 if tail else 0) - 3          # 3 = the dots, 1 = the space before the tail
    if len(head) <= room:                                       # only the tail was the problem: nothing to shorten
        return head + (" " if head and tail else "") + tail
    cut = head[:max(room, 0)]
    sp = cut.rfind(" ")
    if sp > len(cut) // 2:
        cut = cut[:sp]
    cut = cut.rstrip(" ,;:.") + "..."
    return cut + (" " + tail if tail else "")


def probe_row(r, ctx):
    """(state, detail) of one row; a probe that raises is a red row, never a crash. A row that does not exist on this OS is `skipped`, never red."""
    if not rows.supported(r):
        return "skipped", "not on this system"
    try:
        st, detail = r["probe"](ctx)
    except ShipmiracleError as e:
        st, detail = "red", "check failed: %s" % e
    except Exception as e:
        st, detail = "red", "check failed (%s)" % type(e).__name__
    if st == "red" and r["id"] in ctx.init_state.get("skipped", {}) and r["need"] in ("recommended", "optional"):
        st = "skipped"
    return st, cut_detail(str(detail))


def evaluate(ctx) -> dict:
    out = []
    for r in rows.ROWS:
        st, detail = probe_row(r, ctx)
        out.append({"n": r["n"], "id": r["id"], "title": r["title"], "need": r["need"], "state": st, "detail": detail,
                    "connect": {"kind": r["connect"]["kind"], "text": rows.connect_text(r)}, "fix": rows.field(r, "fix"), "undo": rows.field(r, "undo"), "writes": list(rows.field(r, "writes")),
                    "stage": r["stage"], "class": r["class"], "os_supported": rows.supported(r), "docs": r["docs"]})
    ready = all(x["state"] == "green" for x in out if x["n"] in rows.READY_ROWS)
    return {"v": SCHEMA_V, "ready": ready, "os": {"kind": aplat.kind(), "line": aplat.describe()}, "rows": out}


MARK = {"green": "ok       ", "red": "NEEDS FIX", "skipped": "skipped  ", "advisory": "info     ", "never": "n/a      "}


def render_text(res) -> str:
    n_green = sum(1 for x in res["rows"] if x["state"] == "green")
    lines = ["shipm init: %s (%d of %d rows ready)" % ("READY" if res["ready"] else "NOT READY", n_green, len(res["rows"]))]
    for x in res["rows"]:
        lines.append("  %2d %s %-22s %s" % (x["n"], MARK[x["state"]], x["title"], x["detail"]))
        if x["state"] == "red":
            lines.append("       connect: %s" % x["connect"]["text"])
    return "\n".join(lines)


def check(as_json=False, ctx=None) -> str:
    """Read-only. Writes nothing and needs no owner."""
    ctx = ctx or Ctx()
    res = evaluate(ctx)
    if as_json:
        return json.dumps(res, indent=1)
    from . import onboard
    left = [x for x in res["rows"] if x["n"] in rows.READY_ROWS and x["state"] != "green"]
    tail = "Ready: yes." if res["ready"] else "Ready: no (%d required item%s left: %s)." % (len(left), "" if len(left) == 1 else "s", ", ".join(x["title"] for x in left))
    return "\n".join([res["os"]["line"], ""] + onboard.render_check(res, ctx) + ["", tail])


def skip(ref, ctx):
    paths.require_owner("shipm init --skip")
    guard_home()
    r = find(ref)
    if r["need"] not in ("recommended", "optional"):
        raise UsageError("row %d (%s) cannot be skipped: it is %s" % (r["n"], r["id"], r["need"]))
    ctx.init_state.setdefault("skipped", {})[r["id"]] = int(time.time())
    ctx.save_init()
    ctx.say("row %d (%s) skipped; it stays grey and nothing nags. Turn it on later with: shipm init --step %s" % (r["n"], r["id"], r["id"]))


def undo(ref, ctx) -> dict:
    """`shipm init --undo ROW`: reverse the recorded steps of one optional/recommended row (newest first, only where the target is still as init left it),
    using the same rules as `shipm uninstall`. Owner only. A row Shipmiracle never changed has nothing recorded: nothing is touched."""
    from . import uninstall
    paths.require_owner("shipm init --undo")
    guard_home()
    r = find(ref)
    if r["need"] not in ("recommended", "optional"):
        raise UsageError("row %d (%s) cannot be undone on its own: use `shipm uninstall`" % (r["n"], r["id"]))
    manifest.reconcile()
    steps = sorted((s for s in manifest.load()["steps"] if s.get("row") == r["n"]), key=lambda s: -s.get("id", 0))
    if r["id"] == "prefs":
        steps = steps[:1]                       # `--undo prefs` goes back one answer set (the previous values), not to before the first run
    if not steps:
        ctx.say("row %d (%s): nothing recorded to undo (shipm init did not change it)" % (r["n"], r["id"]))
        return {"reversed": 0, "skipped": 0}
    done = skipped = 0
    for s in steps:
        what, why = uninstall.decide(s)
        if what == "skip":
            skipped += 1
            ctx.say("  SKIPPED   %s: %s" % (uninstall._short(s), why))
            continue
        if what == "gone":
            manifest.drop(s["id"])
            ctx.say("  gone      %s: %s" % (uninstall._short(s), why))
            continue
        try:
            ok, note = uninstall._reverse(s)
        except (ShipmiracleError, OSError) as e:
            ok, note = False, str(e) if isinstance(e, ShipmiracleError) else type(e).__name__
        if ok:
            manifest.drop(s["id"])
            done += 1
            ctx.say("  REVERSED  %s: %s" % (uninstall._short(s), note))
        else:
            skipped += 1
            ctx.say("  SKIPPED   %s: %s" % (uninstall._short(s), note))
    if r["id"] == "prefs" and done:
        ctx.init_state.pop("prefs_done", None)
        ctx.save_init()
    return {"reversed": done, "skipped": skipped}


def apply_rows(ctx, only=None) -> dict:
    """The idempotent loop: green rows are left alone, skipped rows too (unless named with --step), red rows with a Fix are applied and re-checked.
    Recommended rows (GitHub sign-in) are applied with --yes or --step; OPTIONAL rows (the awake guard with its two launchd jobs, notifications, ...) only with
    --step NAME, never with --yes alone: the README says the guard is off by default. Returns the final evaluation."""
    paths.require_owner("shipm init")
    guard_home()
    manifest.reconcile()
    targets = [find(only)] if only else rows.ROWS
    ctx.explicit = bool(only)
    step_ok = True          # with `only`: did the requested row end ok (or has nothing to do)? Drives `shipm init --step`'s exit code
    for r in targets:
        st, detail = probe_row(r, ctx)
        if st == "green":
            ctx.say("  %2d ok         %s" % (r["n"], r["title"]))
            continue
        if st == "skipped" and not only:
            ctx.say("  %2d skipped    %s" % (r["n"], r["title"]))
            continue
        if st in ("advisory", "never"):
            ctx.say("  %2d info       %s: %s" % (r["n"], r["title"], detail))
            continue
        if only and r["id"] in ctx.init_state.get("skipped", {}):
            ctx.init_state["skipped"].pop(r["id"], None)
            ctx.save_init()
        if r["apply"] is None:
            ctx.say("  %2d NEEDS FIX  %s: %s\n               %s" % (r["n"], r["title"], detail, r["connect"]["text"]))
            step_ok = False
            continue
        if not only and (r["need"] == "optional" or (r["need"] == "recommended" and not ctx.yes)):
            ctx.say("  %2d optional   %s: %s  (run: shipm init --step %s)" % (r["n"], r["title"], detail, r["id"]))
            continue
        ctx.say("  %2d fixing     %s: %s" % (r["n"], r["title"], detail))
        try:
            ctx.say("               " + r["apply"](ctx))
        except (ShipmiracleError, OSError) as e:
            ctx.say("               FAILED: %s" % (e if isinstance(e, ShipmiracleError) else type(e).__name__))
        st2, d2 = probe_row(r, ctx)
        ctx.say("  %2d %s %s: %s" % (r["n"], "ok       " if st2 == "green" else "NEEDS FIX", r["title"], d2))
        step_ok = st2 == "green"
    res = evaluate(ctx)
    res["step_ok"] = step_ok if only else None
    ctx.say("")
    ctx.say(render_text(res))
    return res
