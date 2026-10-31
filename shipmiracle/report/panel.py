"""The panel's data contract (`shipm report panel [--project DIR] --json`, read by vscode-ext/shipmiracle-panel/data.js; the UI is P7).
Read-only: it replays the log, reads the rules and the autopilot state file; it writes nothing and logs nothing.

{"v":1,"playbook":{type,level,autopilot,trusted,valid}|null,
 "cr":[{id,title,status,stage,lane,label,verdict,waiting_on}],            active first, then queued, then the newest finished; at most 5; stage = "do" for an open CR whose test failed (build next)
 "stageLabels":{scope,plan,approve,do,verify,review,deliver}|null, "nextAction": text|null,
 "lastVerdict":{stage,word,counts,report}|null, "autopilot": shipmiracle.autopilot.state.snapshot(...)|null,
 "remote":{"state":"on"|"off"|"unknown"},                      Remote Control at startup, read from the user-level settings file (read-only; no other key is read out)
 "aside":{on,since,note,canAside,reason,backOnList}                         F7: set aside (reason = the panel's "Not now: ..." text; backOnList = "{project} started work."/"... hit a hard stop." for an aside project that must show as a normal card)
 "toolbox":{count,changed,assets:[{path,stage,stageLabel,purpose,status:"ok"|"changed"|"missing"}]}   F5: the signed-off assets, changed/missing first, then stage order, then path (the panel shows 20, "+N more")
 "interview":{status:"asking"|"paused"|"draft"|"done"|"error",mode:"short"|"long",n,total,draft}|null   F6: the progress of `shipm playbook interview` (the mirror itself reads .shipmiracle/playbook.interview.json)
 "proposed_assets":[{path,why,stage,cr}]                                  F5: at most 3 files the Learn step of the newest finished CR proposed (additive; [] when none)
 "caps":{toolbox,interview,aside,unread,release}                            capability flags of this CLI (a UI part is shown only when its flag is true)
 "release":{"last":{version,date,tag}|null,"working":{version,source}|null,"since":{changes,commits}}    timeline level 1 (shipmiracle.report.release; read-only, git calls time out after 2 s -> null)
 "history":[{id,title,status,closed,release}]                              timeline level 2: the last 10 finished CRs, newest first (closed = epoch seconds; release = version that shipped it or null)
 "unread":{new,why:"turn"|"wait"|null,since}                                F8: new since the owner last looked (seen.json is written only by `shipm project seen NAME`)
 "ask":{"inbox":true,"questions_today":N,"limit":N,"notes":N,"last":{title,path,ts}|null}}   present ONLY for the registered `ask` inbox project (F4); absent for every other project
No playbook (rules None) -> playbook, cr, stageLabels, nextAction, lastVerdict are null / []; autopilot is independent."""
from __future__ import annotations

import os

from ..playbook import engine, gate, store
from . import clean
from . import facts as F
from . import release as R

MAX_CR = 5
_STAGES = ("scope", "plan", "approve", "do", "verify", "review", "deliver")


def _autopilot(pd, base):
    try:
        from ..autopilot import state as ap
        return ap.snapshot(store.pid_of(pd), base=base)
    except Exception:
        return None


def _remote():
    try:
        from .. import settings_sync
        return {"state": settings_sync.remote_control_state()}
    except Exception:
        return {"state": "unknown"}


def _owner_check():
    """Setup data for the optional 'Owner check' row (the panel adds the row later): {level ok|warn, text, tier, setting}; never raises."""
    try:
        from .. import owner
        lvl, txt = owner.row()
        return {"level": lvl, "text": txt, "tier": owner.best()[1], "setting": owner.presence_setting()}
    except Exception:
        return {"level": "warn", "text": "Owner check: unknown", "tier": "none", "setting": "auto"}


def _ask(pd):
    """The ask inbox data, only when `pd` IS the registered ask project; never raises."""
    try:
        from .. import ask
        if os.path.realpath(str(pd)) != os.path.realpath(str(ask.project_path())):
            return None
        return ask.panel_info()
    except Exception:
        return None


def data(project_dir, base=None) -> dict:
    out = _data(project_dir, base)
    pd = os.path.realpath(str(project_dir))
    name = os.path.basename(pd)
    try:
        from .. import aside
        pid = store.pid_of(pd)
        waiting = any(c.get("waiting_on") == "owner" for c in out["cr"])
        out["aside"] = aside.panel_field(name, pid, base, waiting_owner=waiting)
        out["unread"] = aside.unread(name, base)
    except Exception:
        out["aside"] = {"on": False, "since": None, "note": None, "canAside": False, "reason": None, "backOnList": None}
        out["unread"] = {"new": False, "why": None, "since": None}
    out["toolbox"] = _toolbox(pd, out.get("stageLabels"))
    out["proposed_assets"] = _proposed(pd, base)
    out["caps"] = dict(CAPS)
    out["interview"] = _interview(pd)
    out["release"], out["history"] = _release(pd, base)
    return out


def _release(pd, base):
    """(release facts, history list) of the timeline; never raises (no git, no log, a timeout -> nulls, zeros and [])."""
    try:
        lines = F._lines_of(pd, base)
        work = store.replay(lines, os.path.basename(pd))[0] if lines else store.load(pd, base)
        recs = R.cr_records(pd, lines, work, base)
        return R.facts(pd, recs=recs, base=base), R.history(pd, recs)
    except Exception:
        return {"last": None, "working": None, "since": {"changes": 0, "commits": 0}}, []


def _proposed(pd, base):
    """F5: [{path, why, stage, cr}] (at most 3) the Learn step of the newest finished CR proposed and the owner has not signed yet; each row is re-checked now (safe regular file inside
    the project, no symlink). The owner adds one with `shipm playbook asset add`; nothing here adds anything. Never raises."""
    try:
        from ..playbook import toolbox
        listed = [a["path"] for a in (gate.stage_rules(pd) or {}).get("assets") or []]
        cid, rows = toolbox.proposals_load(pd, base, listed)
        return [dict(r, cr=cid) for r in rows]
    except Exception:
        return []


def _interview(pd):
    """F6: {status, mode, n, total, draft:bool} of the project's interview progress file (untrusted data, only these fields), or None."""
    try:
        from ..playbook import interview
        d = interview.load(pd)
        if not d:
            return None
        return {"status": d["status"], "mode": d["mode"], "n": int(d.get("n") or 0), "total": int(d.get("total") or 0), "draft": os.path.isfile(str(interview.draft_path(pd)))}
    except Exception:
        return None


CAPS = {"toolbox": True, "interview": True, "aside": True, "unread": True, "release": True}     # what this CLI can do; a panel UI part appears only when its flag is true


def _toolbox(pd, labels):
    """F5: {count, changed, assets:[{path,stage,stageLabel,purpose,status:ok|changed|missing}]} in the panel order (changed first, stage order, path); never raises."""
    try:
        from ..playbook import assets, config as pbc
        cfg, _trust, _why = pbc.load_trusted(pd, store.registry_entry(pd) or {})
        lst = assets.listing(pd, cfg, labels)
        return {"count": lst["total"], "changed": lst["changed"],
                "assets": [{k: r[k] for k in ("path", "stage", "stageLabel", "purpose", "status")} for r in lst["assets"]]}
    except Exception:
        return {"count": 0, "changed": 0, "assets": []}


def _data(project_dir, base=None) -> dict:
    pd = os.path.realpath(str(project_dir))
    out = {"v": 1, "playbook": None, "cr": [], "stageLabels": None, "nextAction": None, "lastVerdict": None, "autopilot": _autopilot(pd, base), "remote": _remote(), "owner_check": _owner_check()}
    info = _ask(pd)
    if info is not None:
        out["ask"] = info
    try:
        rules = gate.stage_rules(pd)
    except Exception:
        rules = None
    if rules is None:
        return out
    reason = str(rules.get("reason") or "")
    out["playbook"] = {"type": rules["type"], "level": rules["level"], "autopilot": rules["autopilot"], "trusted": rules["trust"] in ("trusted", "snapshot"),
                       "valid": "invalid" not in reason and "unreadable" not in reason}
    labels = rules["labels"]
    out["stageLabels"] = {s: labels.get(s, s.capitalize()) for s in _STAGES}
    lines = F._lines_of(pd, base)
    work = store.replay(lines, os.path.basename(pd))[0] if lines else store.load(pd, base)
    verdict_of = {}
    for ln in lines:
        ev = ln.get("ev") if isinstance(ln.get("ev"), dict) else {}
        d = ev.get("data") if isinstance(ev.get("data"), dict) else {}
        if ln.get("op") == "fail":
            verdict_of[ln.get("cr")] = "FAIL"
        elif ln.get("op") == "advance" and ln.get("stage") == "verify":
            verdict_of[ln.get("cr")] = "PASS"
        elif ln.get("op") == "advance" and ln.get("stage") == "review":
            verdict_of[ln.get("cr")] = clean(d.get("verdict"), 20) or None
        elif ln.get("op") == "block":
            verdict_of[ln.get("cr")] = "BLOCKED"
    act = engine.active_cr(work)
    na = None
    try:
        na = engine.next_action(work, rules)
    except Exception:
        na = None
    queued = [engine.get_cr(work, i) for i in work["queue"]]
    fin = [c for c in reversed(work["crs"]) if c["status"] in engine.TERMINAL]
    order = ([act] if act else []) + [c for c in queued if c] + fin
    for c in order[:MAX_CR]:
        stage = "do" if c["status"] == "open" and c.get("need_build") else c["stage"]      # after a failed test the build is next again (same rule as facts._next); a blocked CR keeps its stage
        out["cr"].append({"id": c["id"], "title": clean(c["title"], 120), "status": c["status"], "stage": stage, "lane": c["lane"],
                          "label": labels.get(stage, stage), "verdict": verdict_of.get(c["id"]), "in_chat": bool(c.get("in_chat")),
                          "waiting_on": (na or {}).get("waiting_on") if act is not None and c["id"] == act["id"] else None})
    if na and act is not None:
        out["nextAction"] = clean(na.get("text"), 300)
    cr_for_verdict = act or (fin[0] if fin else None)
    if cr_for_verdict is not None:
        f = F.build(pd, cr_for_verdict["id"], base)
        if f["verdicts"]:
            v = f["verdicts"][-1]
            rep = (f["cr"]["reports"] or [None])[-1]
            out["lastVerdict"] = {"stage": v["stage"], "word": v["verdict"], "counts": v["counts"], "report": rep}
    return out
