"""`shipm report ACTION ...` (the one subparser lives in shipmiracle/cli.py and delegates here).
  report lint FILE | --all [--project DIR]     check report files; exit 1 when any fails
  report facts [CR] [--project DIR]            the facts as JSON
  report stage CR STAGE [--write]              the stage report (text; --write puts it in the state folder and the index)
  report cr CR [--write]                       the CR report of a delivered/abandoned CR (--write: docs/reports/ + summary queue)
  report digest [--day YYYY-MM-DD] [--write]   one line per project with a playbook
  report panel [--project DIR]                 the panel data contract as JSON
  report queue                                 run one pending summary now (what the guard job does)"""
from __future__ import annotations

import json
import re
import sys
import time

from .. import NotFound, UsageError, projects
from . import facts as F
from . import lint, panel, queue, templates, write


def _out(t=""):
    sys.stdout.write(t + "\n")


def _pd(a):
    from ..playbook import cli as pcli
    return pcli._project_arg(a.project)


def _cr_id(ra, n=0):
    if len(ra) <= n or not re.fullmatch(r"CR-[0-9]{3,6}", ra[n]):
        raise UsageError("expected a change request id like CR-012")
    return ra[n]


def run(a) -> int:
    act, ra = a.action, list(a.rargs or [])
    if act == "lint":
        files = []
        if a.all:
            pd = None
            try:
                pd = _pd(a)
            except NotFound:
                pass
            files = lint.all_files(pd)
        elif ra:
            files = ra
        else:
            raise UsageError("report lint needs FILE or --all")
        bad = 0
        for f in files:
            probs = lint.lint_file(f)
            _out(("PASS %s" % f) if not probs else "FAIL %s: %s" % (f, "; ".join(probs)))
            bad += bool(probs)
        if not files:
            _out("no report files")
        return 1 if bad else 0
    if act == "panel":
        _out(json.dumps(panel.data(_pd(a)), ensure_ascii=False))
        return 0
    if act == "queue":
        r = queue.run_one()
        _out("%s%s" % (r["outcome"], (": " + r["why"]) if r["why"] else ""))
        return 0
    if act == "digest":
        day = a.day or time.strftime("%Y-%m-%d")
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", day):
            raise UsageError("--day is YYYY-MM-DD")
        dirs = [p.path for p in projects.list_projects()]
        if a.write:
            _out(str(write.write_digest(day, dirs)))
        else:
            rows = [F.project_day(d, day) for d in dirs]
            _out(templates.digest(day, [r for r in rows if r["delivered"] or r["open"] or r["queue"]]).rstrip("\n"))
        return 0
    pd = _pd(a)
    if act == "facts":
        f = F.build(pd, _cr_id(ra) if ra else None)
        _out(json.dumps(f, ensure_ascii=False, sort_keys=True))
        return 0
    if act == "stage":
        cr, stage = _cr_id(ra), (ra[1] if len(ra) > 1 else "")
        if a.write:
            _out(str(write.write_stage(pd, cr, stage)))
        else:
            f = F.build(pd, cr)
            if f["cr"] is None or stage not in F.ORDER:
                raise UsageError("unknown change request or stage")
            _out(templates.stage_report(f, stage).rstrip("\n"))
        return 0
    if act == "cr":
        cr = _cr_id(ra)
        if a.write:
            _out(str(write.write_cr(pd, cr)))
        else:
            f = F.build(pd, cr)
            if f["cr"] is None:
                raise NotFound("no such change request")
            _out(templates.cr_report(f).rstrip("\n"))
        return 0
    raise UsageError("unknown report action")
