"""CLI glue for `shipm init` and `shipm uninstall` (arguments are parsed in shipmiracle/cli.py). Exit codes: init --check 0 always (the JSON says `ready`);
init without --step: 0 when ready after the run, else 1; with --step ROW, --skip or --undo ROW: only that row counts (0 done or already ok,
1 failed or could not be fully undone), the closing table and readiness line are informational; uninstall 0 or 1 (a step was skipped); 2 usage; 4 refusal (inside a Claude chat, real home in tests)."""
from __future__ import annotations

import sys

from .. import UsageError, platform as aplat
from . import onboard, run, uninstall


def _out(text=""):
    sys.stdout.write(text + "\n")


PREF_FLAGS = {"lang": "prefs.lang", "folder": "paths.projects_dir", "autonomy": "prefs.autonomy", "awake": "prefs.keep_awake", "notify": "prefs.notify"}


def _given(a) -> dict:
    """The choices typed as flags (the panel's prefilled command); validated by the config schema."""
    from .. import config
    out = {}
    for flag, key in PREF_FLAGS.items():
        v = getattr(a, flag, None)
        if v is not None:
            if not getattr(a, "prefs", False):
                raise UsageError("--%s goes with --prefs" % flag)
            out[key] = config.SCHEMA[key][0](v)
            if key == "paths.projects_dir":
                from .. import folder_check
                why = folder_check.problem(out[key])
                if why:
                    raise UsageError(why)
    return out


def run_init(a) -> int:
    """Ctrl-C (or the end of the input where it must stop the run) anywhere in `shipm init`, also with --step / --skip / --undo: one sentence, exit 130, no traceback.
    A write that was cut off is settled by the manifest on the next run."""
    try:
        return _run_init(a)
    except (KeyboardInterrupt, run.Paused):
        _out("")
        _out("Setup paused. Run shipm init to continue.")
        return 130


def _run_init(a) -> int:
    if aplat.kind() == "windows":          # native Windows: refuse before anything is read or written (exit 3 = not supported yet)
        _out(aplat.refusal_text())
        return 3
    if a.json and not a.check:
        raise UsageError("--json goes with --check")
    more, prefs = getattr(a, "more", False), getattr(a, "prefs", False)
    given = _given(a)
    if a.check:
        if a.step or a.skip or a.yes or getattr(a, "undo", None) or more or prefs:
            raise UsageError("--check is read-only: it takes only --json")
        _out(run.check(as_json=a.json))
        return 0
    if more:
        if a.step or a.skip or a.yes or getattr(a, "undo", None) or prefs:
            raise UsageError("--more is read-only: it takes no other option")
        _out("\n".join(onboard.render_more(run.evaluate(run.Ctx()), run.Ctx())))
        return 0
    if prefs and (a.step or a.skip or getattr(a, "undo", None)):
        raise UsageError("--prefs cannot be combined with --step, --skip or --undo")
    undo = getattr(a, "undo", None)
    if undo and (a.step or a.skip):
        raise UsageError("--undo cannot be combined with --step or --skip")
    if a.step and a.skip:
        raise UsageError("--step and --skip cannot be combined")
    ctx = run.Ctx(yes=a.yes, say=_out, adopt=bool(getattr(a, "adopt", False)))
    if prefs:
        return onboard.run_all(ctx, given=given, prefs_only=True)
    if undo:
        res = run.undo(undo, ctx)
        return 1 if res["skipped"] else 0
    if a.skip:
        run.skip(a.skip, ctx)
        return 0
    if not a.step:
        return onboard.run_all(ctx)          # the standard onboarding: Check, Quick setup, Connect
    res = run.apply_rows(ctx, only=a.step)
    if a.step:
        return 0 if res.get("step_ok") else 1       # only the requested row decides; the readiness line above is informational
    return 0 if res["ready"] else 1


def run_uninstall(a) -> int:
    """Ctrl-C or Ctrl-D at the purge question: one sentence, exit 130, no traceback. The question comes before any removal, so nothing was changed."""
    try:
        return uninstall.run(apply=a.apply, purge=a.purge, confirm=a.confirm, say=_out)
    except uninstall.Interrupted as e:
        _out("")
        _out("Uninstall stopped partway. Some steps were already undone. Run shipm uninstall --apply%s again to finish." % (" --purge" if e.purge else ""))
        return 130
    except (KeyboardInterrupt, run.Paused):
        _out("")
        _out("Uninstall paused. Nothing was deleted. Run shipm uninstall --apply%s again." % (" --purge" if a.purge else ""))
        return 130
