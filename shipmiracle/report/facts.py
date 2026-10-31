"""facts.build(project_dir, cr_id=None, base=None) -> dict: everything a report may say, read from the engine log, the event log, the agents
file and git. Read-only, no clock except `now` for an open CR. Every free-text field is cleaned and clipped; nothing is invented: what is
not recorded is None / [] and the templates say "not recorded" / "not measured".

Evidence keys read from a log line's `ev.data` (written by the stage module at SubagentStop; any may be missing):
  evidence (<= 200 chars, the command and its counts as the agent reported them), not_verified (<= 200), failed (list of short names),
  counts (dict of ints {passed, failed, total} or short text), cmd (the test command)."""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

from .. import events, paths, projects, registry, state
from ..playbook import engine, gate, store, types
from . import clean, safe, secret_free

ORDER = types.ORDER
MAX_EVIDENCE = 200
_MODEL_RE = re.compile(r"(opus|sonnet|haiku)", re.I)


def _lines_of(pd, base):
    lines, _bad = store._parse_lines(store._read_log_bytes(store.log_path(pd, base)))
    return lines


def _counts(v):
    if isinstance(v, dict):
        out = {k: v[k] for k in ("passed", "failed", "total", "skipped") if isinstance(v.get(k), int) and not isinstance(v.get(k), bool)}
        return out or None
    t = clean(v, 60) if isinstance(v, str) else ""
    return t or None


def _git(pd, argv):
    try:
        rc, out = projects._run_git(projects.GIT_PREFIX + argv, pd)
    except Exception:
        return None
    return out.strip() if rc == 0 else None


def _git_facts(pd, cr):
    head = _git(pd, ["rev-parse", "HEAD"])
    base_sha = cr.get("base") if isinstance(cr.get("base"), str) and re.fullmatch(r"[0-9a-f]{7,64}", cr["base"]) else None
    out = {"base": base_sha, "head": head, "commits": [], "files": [], "files_total": 0, "pushed": False}
    if not head:
        return out
    if base_sha and base_sha != head:
        log = _git(pd, ["log", "-n", "10", "--format=%h%x09%s", "%s..%s" % (base_sha, head)])
        for ln in (log or "").splitlines():
            sha, _, subj = ln.partition("\t")
            if sha:
                out["commits"].append({"sha": sha, "subject": clean(subj, 80)})
        names = _git(pd, ["diff", "--name-only", base_sha, head])
        allf = [clean(x, 120) for x in (names or "").splitlines() if x.strip()]
        out["files_total"], out["files"] = len(allf), allf[:10]
    up = _git(pd, ["rev-parse", "--verify", "-q", "@{u}"])
    if up:
        rc = None
        try:
            rc, _o = projects._run_git(projects.GIT_PREFIX + ["merge-base", "--is-ancestor", head, up], pd)
        except Exception:
            pass
        out["pushed"] = rc == 0
    return out


def _agent_models(pd, base):
    """{agent type: model family} from <state>/<project>.agents.json (the SubagentStart records; newest record per type)."""
    b = Path(base) if base is not None else paths.state_dir()
    try:
        d = json.loads(state.read_bytes_nofollow(b / (os.path.basename(pd) + ".agents.json")).decode("utf-8"))
    except Exception:
        return {}
    best = {}
    if isinstance(d, dict):
        for rec in d.values():
            if isinstance(rec, dict) and isinstance(rec.get("type"), str) and isinstance(rec.get("model"), str):
                m = _MODEL_RE.search(rec["model"])
                st = rec.get("started") if isinstance(rec.get("started"), (int, float)) else 0
                if m and (rec["type"] not in best or st >= best[rec["type"]][0]):
                    best[rec["type"]] = (st, m.group(1).lower())
    return {k: v[1] for k, v in best.items()}


def _auto_decisions(pd, cr_id, base):
    """auto_decision events of this CR (P6), filtered by the charter sha when the registry still holds the charter."""
    pid = store.pid_of(pd)
    sha = None
    try:
        rec = registry.autopilot_of(registry.entry(pid))
    except Exception:
        rec = None
    if rec:
        sha = rec["sha256"]
    rows = []
    try:
        evs = events.tail(5000, base)
    except Exception:
        evs = []
    for e in evs:
        d = e.get("data") if isinstance(e, dict) else None
        if not isinstance(d, dict) or e.get("kind") != "auto_decision" or d.get("cr") != cr_id:
            continue
        if sha is not None and d.get("charter_sha") != sha:
            continue
        rows.append({"ts": int(e["ts"]) if isinstance(e.get("ts"), (int, float)) else 0, "stage": clean(d.get("stage"), 20) or "-",
                     "rule": clean(d.get("rule"), 30) or "-", "detail": clean(d.get("detail"), 200), "charter_sha": clean(d.get("charter_sha"), 64)})
    rows.sort(key=lambda r: r["ts"])
    charter = None
    if rec:
        charter = {"id": rec["charter"].get("id"), "goal": clean(rec["charter"].get("goal"), 200)}
    elif rows and rows[0]["charter_sha"]:
        charter = {"id": "ch-" + rows[0]["charter_sha"][:8], "goal": ""}
    return rows, charter


def _labels(rules):
    return dict((rules or {}).get("labels") or types.load("software")["labels"])


def _verdicts(cr_id, lines):
    out, fails = [], 0
    for ln in lines:
        if ln.get("cr") != cr_id:
            continue
        op, stage = ln.get("op"), ln.get("stage")
        ev = ln.get("ev") if isinstance(ln.get("ev"), dict) else {}
        d = ev.get("data") if isinstance(ev.get("data"), dict) else {}
        row = None
        if op == "fail":
            fails += 1
            row = {"stage": "verify", "verdict": "FAIL", "attempt": d.get("n") if isinstance(d.get("n"), int) else fails}
        elif op == "advance" and stage == "verify":
            row = {"stage": "verify", "verdict": "PASS", "attempt": fails + 1}
            fails = 0
        elif op == "advance" and stage == "review":
            row = {"stage": "review", "verdict": clean(d.get("verdict"), 20), "lens": clean(d.get("lens"), 20), "attempt": 1}
        elif op == "block":
            row = {"stage": stage or "verify", "verdict": "BLOCKED", "attempt": fails, "reason": clean(d.get("reason"), 40)}
        if row is None:
            continue
        row.update(ts=ln["ts"], by=clean(ln.get("by"), 40) or "engine", counts=_counts(d.get("counts")), evidence=safe(d.get("evidence"), MAX_EVIDENCE),
                   not_verified=safe(d.get("not_verified"), MAX_EVIDENCE), cmd=secret_free(clean(d.get("cmd"), 80)),
                   failed=[secret_free(clean(x, 80)) for x in (d.get("failed") if isinstance(d.get("failed"), list) else [])[:5] if isinstance(x, str) and secret_free(clean(x, 80))])
        out.append(row)
    return out


def _stage_rows(cr, lines, models, labels):
    last = {}
    for ln in lines:
        if ln.get("cr") == cr["id"] and ln.get("op") in ("advance", "override", "fail") and ln.get("stage") in ORDER:
            last[ln["stage"]] = ln
    rows = []
    for s in ORDER:
        ln = last.get(s)
        by = clean(ln.get("by"), 40) if ln else ""
        rows.append({"id": s, "label": labels.get(s, s.capitalize()), "status": cr["stages"].get(s, "next"), "by": by or None,
                     "ts": ln["ts"] if ln else None, "model": models.get(by) if by else None})
    return rows


def _owner_waits(cr_id, lines):
    plan_ts, waits = None, []
    for ln in lines:
        if ln.get("cr") != cr_id or ln.get("op") not in ("advance", "override"):
            continue
        if ln.get("stage") == "plan":
            plan_ts = ln["ts"]
        elif ln.get("stage") == "approve" and plan_ts is not None:
            waits.append(max(0, ln["ts"] - plan_ts))
            plan_ts = None
    return {"n": len(waits), "secs": sum(waits)}


def _next(cr, rules, labels):
    if cr["status"] in engine.TERMINAL:
        return None
    stage = "do" if cr.get("need_build") else cr["stage"]
    if stage not in ORDER:
        return None
    return {"stage": stage, "label": labels.get(stage, stage.capitalize()), "agent": ((rules or {}).get("agents") or {}).get(stage)}


def build(project_dir, cr_id=None, base=None, now=None, git=True) -> dict:
    """Facts of one change request (the active one, else the newest, when cr_id is None). {"cr": None, ...} when the project has none."""
    pd = os.path.realpath(str(project_dir))
    now = int(time.time()) if now is None else int(now)
    name = os.path.basename(pd)
    try:
        rules = gate.stage_rules(pd)
    except Exception:
        rules = None
    labels = _labels(rules)
    lines = _lines_of(pd, base)
    work = store.replay(lines, name)[0] if lines else store.load(pd, base)
    cr = engine.get_cr(work, cr_id) if cr_id else (engine.active_cr(work) or (work["crs"][-1] if work["crs"] else None))
    f = {"v": 1, "project": name, "type": (rules or {}).get("type"), "lang": (rules or {}).get("lang", "en"), "level": (rules or {}).get("level"),
         "labels": labels, "cr": None, "generated": now}
    if cr is None:
        return f
    models = _agent_models(pd, base)
    verdicts = _verdicts(cr["id"], lines)
    dec, charter = _auto_decisions(pd, cr["id"], base)
    end = cr.get("closed") or now
    first = min([ln["ts"] for ln in lines if ln.get("cr") == cr["id"]] or [cr["opened"]])
    f.update(
        cr={"id": cr["id"], "title": clean(cr["title"], 120), "lane": cr["lane"], "status": cr["status"], "stage": cr["stage"], "opened": cr["opened"],
            "closed": cr.get("closed"), "blocked": cr.get("blocked"), "verified": bool(cr.get("verified")), "verify_fails": cr["verify_fails"],
            "lenses": dict(cr["lenses"]), "diff": dict(cr["diff"]), "reports": list(cr.get("reports") or [])},
        stages=_stage_rows(cr, lines, models, labels), verdicts=verdicts, owner_waits=_owner_waits(cr["id"], lines),
        auto_decisions=dec, charter=charter, git=_git_facts(pd, cr) if git else {"base": None, "head": None, "commits": [], "files": [], "files_total": 0, "pushed": False}, next=_next(cr, rules, labels),
        tokens=None, wall_s=max(0, end - min(first, cr["opened"])))
    return f


def project_day(project_dir, day, base=None) -> dict:
    """One line of the daily digest: CRs delivered on local `day` (YYYY-MM-DD), the open CR and who it waits on."""
    pd = os.path.realpath(str(project_dir))
    lines = _lines_of(pd, base)
    work = store.replay(lines, os.path.basename(pd))[0] if lines else store.load(pd, base)
    delivered = [c for c in work["crs"] if c["status"] == "delivered" and c.get("closed") and time.strftime("%Y-%m-%d", time.localtime(c["closed"])) == day]
    act = engine.active_cr(work)
    rules = None
    try:
        rules = gate.stage_rules(pd)
    except Exception:
        pass
    wait, stage_label = None, None
    if act is not None:
        stage_label = _labels(rules).get(act["stage"], act["stage"])
        if rules:
            try:
                na = engine.next_action(work, rules)
                wait = clean(na.get("wait"), 80) if na.get("waiting_on") == "owner" else None
            except Exception:
                wait = None
    return {"project": os.path.basename(pd), "delivered": [c["id"] for c in delivered],
            "pass": sum(1 for c in delivered if c.get("verified")),
            "open": {"id": act["id"], "stage": stage_label} if act else None, "waiting": wait,
            "queue": len(work["queue"])}
