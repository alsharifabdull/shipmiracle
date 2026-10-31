"""The standard onboarding (plan docs/plans/2026-10-21-cross-platform-onboarding.md, section 4): `shipm init` in three stages.
  1. Check    read-only, one screen: the OS line and the rows that matter (required, recommended) with a symbol each.
  2. Quick setup  at most five choices, Enter keeps the recommended answer; stored user-level in the config (never in a project) as ONE recorded manifest step.
  3. Connect  only the missing required items, in dependency order, each verified by its probe, resumable (init.json `connect_next`), undoable per item.
Nothing here asks for or stores a credential: sign-ins happen in the tool's own login (claude, gh auth login --web). `--yes` never prompts, never
opens a browser and never uses sudo. The text of every screen is built here; the rows themselves (probe, apply, per-OS text) live in rows.py."""
from __future__ import annotations

import sys

from .. import ShipmiracleError, UsageError, config, folder_check, paths, platform as aplat
from . import guard_home, manifest, rows, run

UTF = {"ok": "✓", "need": "!", "opt": "–", "no": "✕"}
ASCII = {"ok": "ok", "need": "!!", "opt": "--", "no": "no"}
MAX_TRIES = 3


Paused = run.Paused         # the input ended at a question: stop cleanly, `shipm init` resumes


def use_ascii(ctx) -> bool:
    if ctx.ascii is not None:
        return bool(ctx.ascii)
    return "utf" not in (getattr(sys.stdout, "encoding", "") or "").lower()


def symbols(ctx):
    return ASCII if use_ascii(ctx) else UTF


def symbol(x, sy) -> str:
    """ok = ready, need = a required item that is not ready, opt = optional or recommended and not set / skipped / advisory, no = not on this system."""
    if not x["os_supported"]:
        return sy["no"]
    if x["state"] == "green":
        return sy["ok"]
    if x["state"] == "red" and x["class"] == "required":
        return sy["need"]
    return sy["opt"]


def _tilde(p) -> str:
    h = str(paths.home())
    s = str(p)
    return "~" + s[len(h):] if s.startswith(h + "/") else s


# ------------------------------------------------------------------ stage 1: Check
def counts(res):
    """(required total, required ready, optional ready, optional not set, optional not on this system) over the rows that are not the prefs row."""
    req = [x for x in res["rows"] if x["class"] == "required" and x["stage"] == "connect"]
    opt = [x for x in res["rows"] if not (x["class"] == "required") and x["id"] != "prefs"]
    return (len(req), sum(1 for x in req if x["state"] == "green"), sum(1 for x in opt if x["os_supported"] and x["state"] == "green"),
            sum(1 for x in opt if x["os_supported"] and x["state"] != "green"), sum(1 for x in opt if not x["os_supported"]))


def render_check(res, ctx, full=True):
    """Lines of the Check screen. full=False is the short form for a machine with nothing to do."""
    sy = symbols(ctx)
    tot, ok, o_ok, o_off, o_no = counts(res)
    if not full:
        return ["Check: all %d required ready, %d optional ready (shipm init --more)" % (tot, o_ok)]
    lines = ["Check"]
    order = {r["id"]: r["order"] for r in rows.ROWS}
    shown = [x for x in res["rows"] if x["id"] != "prefs" and x["class"] in ("required", "recommended") and x["stage"] == "connect"]
    for x in sorted(shown, key=lambda x: (x["class"] != "required", order[x["id"]])):      # the order Connect follows (dependencies first)
        d = x["detail"]
        if x["state"] == "red" and x["class"] != "required":
            d = "recommended, " + d
        lines.append("  %-2s %-20s %s" % (symbol(x, sy), x["title"], d))
    lines.append("  Optional: %d ready, %d not set, %d not on this system   (shipm init --more)" % (o_ok, o_off, o_no))
    return lines


def render_more(res, ctx):
    """`shipm init --more`: every row (the Advanced list)."""
    sy = symbols(ctx)
    lines = [res["os"]["line"], "", "All rows (%s ready, ! needs you, %s optional or not set, %s not on this system)" % (sy["ok"], sy["opt"], sy["no"])]
    for x in res["rows"]:
        lines.append("  %-2s %2d %-30s %s" % (symbol(x, sy), x["n"], x["title"], x["detail"]))
        if x["state"] == "red" and x["os_supported"]:
            lines.append("        connect: %s" % x["connect"]["text"])
        if x["docs"] and x["state"] != "green" and x["os_supported"]:
            lines.append("        more: %s" % x["docs"])
    return lines


# ------------------------------------------------------------------ stage 2: Quick setup
def _stored(key):
    try:
        return config.get(key, None)
    except ShipmiracleError:
        return None


def questions():
    """The up to five choices for this OS. Each: key, text, opts [(value, label)] or free=True, default value. Defaults are the current stored value, else the recommended one."""
    k = aplat.kind()
    dev = paths.dev_dir()
    qs = [
        dict(key="prefs.lang", text="Language for reports?", opts=[("en", "English"), ("ar", "Arabic")], default="en"),
        dict(key="paths.projects_dir", text="Projects folder?", free=True, default=_stored("paths.projects_dir") or (_tilde(dev) if dev.is_dir() else "~/Developer")),
        dict(key="prefs.autonomy", text="How much should the team do by itself?", opts=[("normal", "Normal"), ("step", "Step by step"), ("own", "On its own")], default="normal"),
    ]
    if k == "macos" or (k == "linux" and aplat.keep_awake_available()):
        qs.append(dict(key="prefs.keep_awake", text="Keep the computer awake while Claude works?", opts=[(True, "Yes"), (False, "No")], default=True))
    notify = [("vscode", "In VS Code only")] + ([("system", "Also system pop-ups")] if k in ("macos", "linux") else []) + [("none", "None")]
    qs.append(dict(key="prefs.notify", text="Notifications?", opts=notify, default="vscode"))
    for q in qs:
        cur = _stored(q["key"])
        if cur is not None and not q.get("free"):
            q["default"] = cur
    return qs


def _label(q, value) -> str:
    if q.get("free"):
        return str(value)
    return next((lab for v, lab in q["opts"] if v == value), str(value))


def _parse(q, text):
    """The value for an answer, or None when it is not one of the choices. Empty = the default."""
    t = text.strip()
    if not t:
        return q["default"]
    if q.get("free"):
        return t
    low = t.lower()
    for v, lab in q["opts"]:
        if low in (lab.lower(), str(v).lower()):
            return v
    if q["opts"][0][0] is True:
        if low in ("y", "yes", "true", "on"):
            return True
        if low in ("n", "no", "false", "off"):
            return False
    hits = [v for v, lab in q["opts"] if lab.lower().startswith(low)]
    return hits[0] if len(hits) == 1 else None


def _prompt(q, i, n) -> str:
    if q.get("free"):
        return "  %d/%d %s [%s]: " % (i, n, q["text"], q["default"])
    others = " / ".join(lab for v, lab in q["opts"] if v != q["default"])
    return "  %d/%d %s [%s]%s: " % (i, n, q["text"], _label(q, q["default"]), (" / " + others) if others else "")


def _check_value(q, value):
    """Validate a chosen value with the config schema; the projects folder is also refused under a Windows drive on WSL. Returns the stored value or raises UsageError."""
    if q["key"] == "paths.projects_dir":
        v = config.SCHEMA[q["key"]][0](value)
        why = folder_check.problem(v)
        if why:
            raise UsageError(why)
        return v
    return config.SCHEMA[q["key"]][0](value)


def run_prefs(ctx, interactive=None, given=None) -> str:
    """Ask (or take from `given`/defaults) the choices and save what changed as ONE recorded step. `given` maps key -> value from flags. Returns a one-line result."""
    paths.require_owner("shipm init")
    guard_home()
    given = dict(given or {})
    interactive = ctx.interactive() if interactive is None else interactive
    qs = questions()
    answers = {}
    for i, q in enumerate(qs, 1):
        if q["key"] in given:
            val = given[q["key"]]
        elif interactive:
            val = None
            for _ in range(MAX_TRIES):
                try:
                    reply = ctx.input(_prompt(q, i, len(qs)))
                except EOFError:
                    if ctx.pause_on_eof:                    # inside the three-stage run the end of the input stops everything; nothing is saved, shipm init asks again
                        raise Paused()
                    if interactive:                         # alone (--prefs, --step prefs): the recommended answer for this and every later question
                        ctx.say("      No more input: using the recommended answers for the rest.")
                    interactive = False
                    break
                got = _parse(q, reply)
                if got is None:
                    ctx.say("      Please answer with one of: " + ", ".join(lab for _v, lab in q["opts"]))
                    continue
                try:
                    val = _check_value(q, got)
                except UsageError as e:
                    ctx.say("      %s" % e)
                    continue
                break
            if val is None:
                val = q["default"]
                if interactive:
                    ctx.say("      Using %s." % _label(q, val))
        else:
            val = q["default"]
        try:
            answers[q["key"]] = _check_value(q, val)
        except UsageError as e:
            raise UsageError("%s: %s" % (q["text"].rstrip("?"), e))
    changed = {k: v for k, v in answers.items() if _stored(k) != v}
    if changed:
        before = {k: _stored(k) for k in changed}
        with manifest.recorded(20, "prefs", "prefs", before=before, before_sha256=manifest.sha_json(before), keys=sorted(changed), after={k: changed[k] for k in changed}):
            for k in sorted(changed):
                config.set(k, changed[k])
    ctx.init_state["prefs_done"] = True
    ctx.save_init()
    if answers.get("prefs.autonomy") == "own":
        ctx.say("  \"On its own\" never switches full autopilot on here. If you want it, you do that step yourself in a terminal: shipm switch autopilot.full.enabled on")
    where = _tilde(config.path())
    ctx.say("  Saved in %s. Change later: shipm init --prefs. Undo: shipm init --undo prefs." % where)
    return "saved %d choice(s)" % len(changed) if changed else "choices unchanged"


# ------------------------------------------------------------------ stage 3: Connect
def _later(answer) -> bool:
    return answer.strip().lower() in ("later", "l", "skip", "s", "q", "quit")


def connect(ctx, res) -> None:
    """Walk the missing required rows in dependency order. A row with an apply is applied (it asks its own questions) and verified; any other row prints its exact
    command or link, waits for Enter at a terminal, then verifies. A row that is still not ready stays for the next `shipm init`."""
    states = {x["id"]: x["state"] for x in res["rows"]}
    todo = [r for r in rows.CONNECT_ROWS if states.get(r["id"]) == "red"]
    if not todo:
        ctx.init_state.pop("connect_next", None)
        ctx.save_init()
        return
    nxt = ctx.init_state.get("connect_next")
    k = next((i for i, r in enumerate(todo) if r["id"] == nxt), None)
    resuming = k is not None
    k = k or 0
    todo = todo[k:] + todo[:k]                  # resume where the last run stopped (when that row is still red), then the rest in order
    if resuming:
        ctx.say("")
        ctx.say("Continuing at: %s" % todo[0]["title"])
    left = []
    ctx.say("")
    ctx.say("Connect (%d left; Ctrl-C stops, shipm init resumes here)" % len(todo))
    sy = symbols(ctx)
    no_terminal = not ctx.yes and not ctx._tty()          # nobody can answer: nothing that changes settings or config is applied without --yes
    not_applied = []
    try:
        for i, r in enumerate(todo, 1):
            ctx.init_state["connect_next"] = r["id"]       # the row being worked on: where a pause resumes
            ctx.save_init()
            if ctx.eof:
                raise Paused()                              # the input has ended: apply nothing more
            ctx.say("  %d/%d %s" % (i, len(todo), r["title"]))
            text = rows.connect_text(r)
            if r["apply"] is not None and no_terminal:
                ctx.say("      %s" % rows.field(r, "fix"))
                ctx.say("      not applied: there is no terminal to ask you")
                not_applied.append(r["title"])
                left.append(r)
                continue
            if r["apply"] is not None:
                ctx.say("      %s" % rows.field(r, "fix"))
                try:
                    ctx.say("      " + r["apply"](ctx))
                except (ShipmiracleError, OSError) as e:
                    ctx.say("      FAILED: %s" % (e if isinstance(e, ShipmiracleError) else type(e).__name__))
            else:
                ctx.say("      %s" % text)
                if r["docs"]:
                    ctx.say("      More: %s" % r["docs"])
                if ctx.interactive():
                    try:
                        ans = ctx.input("      Press Enter when done, or type later: ")
                    except EOFError:
                        raise Paused()
                    if _later(ans):
                        ctx.say("      %s left for later." % r["title"])
                        left.append(r)
                        continue
                else:
                    ctx.say("      (not checked now: no terminal)")
                    left.append(r)
                    continue
            st, detail = run.probe_row(r, ctx)
            if st == "green":
                ctx.say("      %s verified" % sy["ok"])
            else:
                left.append(r)
                ctx.say("      %s still not ready: %s" % (sy["need"], detail))
                if r["apply"] is None:
                    ctx.say("      Next step: %s, then run shipm init again." % text)
    except (Paused, KeyboardInterrupt):
        ctx.save_init()                                     # connect_next stays at the row that was not finished; run_all prints the one pause sentence
        raise
    if left:
        ctx.init_state["connect_next"] = left[0]["id"]      # rows remain red: the next run starts at the first of them
    else:
        ctx.init_state.pop("connect_next", None)
    ctx.save_init()
    if not_applied:
        ctx.say("")
        ctx.say("Not applied (no terminal to ask you): %s. Run this in a terminal: shipm init   (or shipm init --yes to allow these writes without questions)" % ", ".join(not_applied))


# ------------------------------------------------------------------ the whole thing
def run_all(ctx, given=None, prefs_only=False) -> int:
    """The three-stage `shipm init` (or `--prefs` alone). Ctrl-C or the end of the input anywhere (also during the Check) pauses it: one sentence, exit 130."""
    try:
        return _run_all(ctx, given, prefs_only)
    except (Paused, KeyboardInterrupt):
        try:
            ctx.save_init()
        except Exception:
            pass
        ctx.say("")
        ctx.say("Setup paused. Run shipm init to continue.")
        return 130


def _run_all(ctx, given=None, prefs_only=False) -> int:
    """`shipm init` (no row flags) and `shipm init --prefs`. Exit: 0 when ready, 1 when something required is left, 130 after Ctrl-C."""
    paths.require_owner("shipm init")
    guard_home()
    manifest.reconcile()
    say = ctx.say
    ctx.pause_on_eof = not ctx.yes and not prefs_only      # `--prefs` alone: the end of the input means "the recommended answers for the rest", saved
    if prefs_only:
        try:
            run_prefs(ctx, given=given)
        except (Paused, KeyboardInterrupt):
            say("Setup paused. Run shipm init to continue.")
            return 130
        return 0
    res = run.evaluate(ctx)
    say(res["os"]["line"])
    states = {x["id"]: x["state"] for x in res["rows"]}
    missing = [r for r in rows.CONNECT_ROWS if states[r["id"]] == "red"]
    need_prefs = states["prefs"] != "green"
    if not missing and not need_prefs:
        for ln in render_check(res, ctx, full=False):
            say(ln)
        if ctx.init_state.pop("connect_next", None) is not None:
            ctx.save_init()                                 # everything is green: the resume mark is no longer needed
        say("Nothing to do.")
        return 0
    say("")
    for ln in render_check(res, ctx):
        say(ln)
    try:
        if need_prefs:
            say("")
            if ctx.yes or given:
                say("Quick setup: using the recommended answers (change later: shipm init --prefs)")
                run_prefs(ctx, interactive=False, given=given)
            elif ctx.interactive():
                say("Quick setup (Enter keeps the answer in brackets)")
                run_prefs(ctx, interactive=True)
            else:
                say("Quick setup needs a terminal: run shipm init in one, or shipm init --yes to take the recommended answers.")
        res = run.evaluate(ctx)
        connect(ctx, res)
    except Paused:
        say("Setup paused. Run shipm init to continue.")
        return 130
    except KeyboardInterrupt:
        say("")
        say("Setup paused. Run shipm init to continue.")
        return 130
    final = run.evaluate(ctx)
    say("")
    left = [x for x in final["rows"] if x["n"] in rows.READY_ROWS and x["state"] != "green"]
    if final["ready"]:
        say("Ready: yes.")
    else:
        say("Ready: no (%d required item%s left: %s). Run shipm init again when done." % (len(left), "" if len(left) == 1 else "s", ", ".join(x["title"] for x in left)))
    rec = [x for x in final["rows"] if x["class"] == "recommended" and x["state"] != "green" and x["os_supported"]]
    if rec:
        say("Also recommended: " + "; ".join("%s (shipm init --step %s)" % (x["title"], x["id"]) for x in rec) + ". All rows: shipm init --more")
    return 0 if final["ready"] else 1
