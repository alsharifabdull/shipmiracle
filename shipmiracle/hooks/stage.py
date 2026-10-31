"""stage (P5b T5, spec docs/plans/2026-10-20-p5-spec.md sections 2.4, 4, 5): the playbook module of the dispatcher. It runs AFTER flow in
UserPromptSubmit, PreToolUse (Agent|Task), PostToolUse (ExitPlanMode|Agent|Task), SubagentStop and Stop, and can only ADD refusals and context:
flow's decisions are untouched (the dispatcher merge is a union). It tracks the active change request (CR) through shipmiracle.playbook.engine/store
(the log in the state dir is the authority; .shipmiracle/work.json is only a rendering) and, when config gate.engine is `playbook`, refuses with
cr_needs_plan, cr_review_missing, cr_continue (Stop), manual_hold, cr_blocked (PreToolUse Agent|Task). `shadow` tracks the same but only
logs `stage.shadow` events; `legacy` (default) returns at once. Level (flow.json) strict = refuse, warn = note, off = silent.
Inputs from flow are read-only: flow.<sid>.json (roles cache, bypass, arch_ts, qa_runs, team_seen) and its parse_verdict/qa_eval/constants.
Fails open: any error is raised to the dispatcher, which logs `hook_module_error` and treats it as no output.
Import budget at module level: os, json, re, time, hashlib (plus core/io); everything else is imported only when a CR needs it."""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import time

from . import core
from . import io as hio

ENGINES = ("shadow", "playbook")
# TODO(P6 T4): share hio.HANDBACK_HEADS once that constant carries the same envelope-like heads; until then the list lives here (superset of flow's).
HAND_BACK = ("<agent-message", "<task-notification", "<system-reminder", "<teammate-message", "[subagent hand-back]")
ENVELOPE_RE = re.compile(r"<\s*/?\s*[a-z][a-z-]*(?:message|notification|reminder)\b")     # any envelope-like tag early in a prompt
APPROVE_HEAD = re.compile(r"^[\W_]*(?:approved?|go|yes|yep|proceed|ok(?:ay)?|lgtm|looks good|build it|do it|start)\b")
HEDGE = re.compile(r"\b(but|however|except|unless|first|before|after|explain|why|how|what|which|when|where|who|whether|instead|rather|wait|stop)\b")
APPROVAL_MAX = 40
CAP = 2                                                  # refusals per kind per turn (cr_continue: once; cr_blocked: no cap)
NO_CAP = ("cr_blocked", "limit_near", "asset_changed")
LOOP_MAX = 8                                             # asset_changed has no per-turn cap but a Stop that is refused this often in one turn passes (no endless Stop loop)
NO_BYPASS = ("cr_blocked", "limit_near", "asset_changed")
HARD = ("asset_changed",)                                # blocks at level warn too (F5: a changed toolbox asset never reaches Deliver on a warn-only project)
CTX_MAX = 500
TOOLBOX_CTX_MAX = 1500
PLAN_STAGES = ("scope", "plan")


# ---------------------------------------------------------------- cheap gate (no Shipmiracle imports)
def _engine(ctx) -> str:
    """config gate.engine; the env var SHIPMIRACLE_GATE_ENGINE counts only under SHIPMIRACLE_TEST=1 (otherwise it is ignored and logged)."""
    env = ctx.env.get("SHIPMIRACLE_GATE_ENGINE")
    if env:
        if ctx.env.get("SHIPMIRACLE_TEST") == "1":
            v = env.strip().lower()
            return v if v in ENGINES else "legacy"
        if ctx.event == "UserPromptSubmit":
            hio.emit_event("gate_env_override", {"vars": ["SHIPMIRACLE_GATE_ENGINE"]})
    v = core.config_get("gate.engine", "legacy")
    v = v.strip().lower() if isinstance(v, str) else ""
    return v if v in ENGINES else "legacy"


def _read(path):
    try:
        with open(path, "rb") as f:
            return json.loads(f.read(core.MAX_JSON_BYTES).decode("utf-8", "replace"))
    except (OSError, ValueError):
        return None


def _fold(p):
    return os.path.normcase(p).casefold()


def _pid(pd) -> str:
    return hashlib.sha256(("shipmiracle-project:" + pd).encode("utf-8", "surrogateescape")).hexdigest()[:12]


def _has_playbook(ctx, pid, pd=None) -> bool:
    if os.path.exists(os.path.join(pd or ctx.pd, ".shipmiracle", "playbook.json")):
        return True
    reg = _read(os.path.join(os.path.dirname(core.config_path()), "registry.json"))
    projs = reg.get("projects") if isinstance(reg, dict) else None
    ent = projs.get(pid) if isinstance(projs, dict) else None
    return isinstance(ent, dict) and isinstance(ent.get("playbook"), dict)


def _log_path(ctx, pid):
    return os.path.join(ctx.state, "v1", "cr", pid + ".jsonl")


def _has_log(ctx, pid) -> bool:
    return os.path.exists(_log_path(ctx, pid)) or os.path.exists(os.path.join(ctx.pd, ".shipmiracle", "work.json"))


# ---------------------------------------------------------------- session state (v1/sessions/<sid>.stage.json, ours)
def _sess_path(ctx):
    return os.path.join(ctx.state, "v1", "sessions", ctx.sid + ".stage.json")


def _sess_load(ctx) -> dict:
    d = _read(_sess_path(ctx))
    return d if isinstance(d, dict) else {}


def _sess_save(ctx, sess) -> None:
    hio.atomic_json(_sess_path(ctx), sess)


# ---------------------------------------------------------------- the per-call bundle
class _C:
    """One call's facts. `render` is False in a replay/shadow child (no repository writes)."""
    def __init__(self, ctx, eng, pid, flow_st, sess):
        self.ctx, self.eng, self.pid, self.st, self.sess = ctx, eng, pid, flow_st, sess
        self.pd = ctx.pd
        self.now = int(ctx.now)
        self.render = ctx.env.get("SHIPMIRACLE_HOOK_NO_SPAWN") != "1"
        self.rules = None
        self.dirty = False
        self.auto = None                                     # {"main", "mpid", "branch"} inside a verified autopilot worktree (P6 T5)
        self.decisions = []                                  # auto_decision rows to emit once the transaction is closed
        self._run = None

    @property
    def level(self):
        return (self.rules or {}).get("level", "strict")

    def ev(self, kind, by, data=None, ts=None):
        return {"kind": kind, "by": by, "ts": ts if ts is not None else self.now, "sid8": self.ctx.sid[:8], "data": data or {}}


def _modules(git):
    """The playbook modules. diffstat (and with it subprocess) only for the events that look at the working tree."""
    from shipmiracle.playbook import engine, gate, store, types
    if git:
        from shipmiracle.playbook import diffstat
    else:
        diffstat = None
    return diffstat, engine, gate, store, types


def stage(ctx):
    if ctx.env.get("SHIPMIRACLE_HOOK_NO_SPAWN") == "1" and ctx.env.get("SHIPMIRACLE_STAGE_REPLAY") != "1":
        return None                                          # dispatcher shadow child: never write project files from a snapshot run
    eng = _engine(ctx)
    if eng == "legacy":
        return None
    auto = None
    if _fold(os.path.dirname(ctx.pd)) != _fold(ctx.dev):
        auto = _auto_info(ctx)                               # flow handles projects directly under ~/Developer; we add verified autopilot worktrees (P6 T5)
        if auto is None:
            return None
    st = _read(os.path.join(ctx.state, "flow.%s.json" % ctx.sid))
    if not isinstance(st, dict) or not st.get("team_seen"):
        return None
    pid = _pid(ctx.pd)                                       # a worktree has its OWN change-request log (keyed by its own path)
    if not (_has_playbook(ctx, pid) if auto is None else _has_playbook(ctx, auto["mpid"], auto["main"])):
        return None
    c = _C(ctx, eng, pid, st, _sess_load(ctx))
    c.auto = auto
    ev = ctx.event
    creates = (ev == "PostToolUse" and ctx.tool_name == "ExitPlanMode") or ev == "SubagentStop"
    if not creates and not _has_log(ctx, pid):
        return None                                          # no CR yet and this event cannot open one: nothing to import
    diffstat, engine, gate, store, types = _modules(ev in ("Stop", "SubagentStop") or (ev == "PostToolUse" and ctx.tool_name == "ExitPlanMode"))
    c.rules = gate.stage_rules(ctx.pd)
    if c.rules is None:
        return None
    if c.rules.get("trust") == "untrusted" and not c.sess.get("untrusted_told"):
        c.sess["untrusted_told"] = True
        c.dirty = True
        hio.emit_event("playbook.untrusted", {"reason": str(c.rules.get("reason"))[:120]}, project=pid)
    _sync_render(c, store)
    if ev == "UserPromptSubmit":
        r = _on_prompt(c, engine, store)
    elif ev == "PreToolUse":
        r = _on_agent_call(c, engine, store)
    elif ev == "PostToolUse":
        r = _on_post(c, engine, store, diffstat, types)
    elif ev == "SubagentStop":
        r = _on_subagent_stop(c, engine, store, diffstat, types)
    elif ev == "Stop":
        r = _on_stop(c, engine, store, diffstat)
    else:
        r = None
    if ev == "Stop" and c.auto is not None:
        r = _auto_stop(c, r, engine, store, diffstat)
    _emit_decisions(c)
    if c.dirty:
        try:
            _sess_save(ctx, c.sess)
        except Exception as e:
            hio.log_err("stage", e)
    return r


# ---------------------------------------------------------------- autopilot worktree (P6 T5)
def _auto_info(ctx):
    """{"main", "mpid", "branch"} when ctx.pd is a verified auto worktree (flow.worktree_of: <dev>/.worktrees/<p>/<x> whose .git points back into
    <dev>/<p>; folder auto-* or branch auto/*), else None. File reads only."""
    if "/.worktrees/" not in ctx.pd:
        return None
    from . import flow as F
    if _fold(F.DEV) != _fold(ctx.dev):
        return None
    w = F.worktree_of(ctx.pd)
    if not w or w[0] != "ok":
        return None
    if not (w[2].startswith("auto/") or os.path.basename(ctx.pd).startswith("auto-")):
        return None
    return {"main": w[1], "mpid": _pid(w[1]), "branch": w[2]}


def _run(c):
    """The run of this auto worktree: {"ok", "why", "charter", "st", "S"} (state.check recomputes the charter sha every time). Cached per call."""
    if c._run is None:
        from shipmiracle.autopilot import state as S
        ok, why, charter, st = S.check(c.auto["mpid"])
        c._run = {"ok": ok and c.rules is not None and c.rules.get("autopilot") == "full", "why": why, "charter": charter, "st": st, "S": S}
    return c._run


def _decide(c, cr, stage, rule, detail):
    run = _run(c)
    sha = (run["st"] or {}).get("charter_sha")
    if sha:
        c.decisions.append({"cr": cr, "stage": stage, "rule": rule, "charter_sha": sha, "detail": str(detail)[:200]})


def _emit_decisions(c):
    for d in c.decisions:
        hio.emit_event("auto_decision", d, project=c.auto["mpid"] if c.auto else c.pid)
        try:
            _run(c)["S"].bump_decisions(c.auto["mpid"])
        except Exception as e:
            hio.log_err("stage", e)
    c.decisions = []


def _auto_approve(c, engine, work, trs):
    """Inside `fn` of a transaction: an active run approves a presented plan of a CR in its charter (engine.charter_approve recomputes everything)."""
    if c.auto is None:
        return
    run = _run(c)
    if not run["ok"]:
        return
    cr = engine.active_cr(work)
    if cr is None or cr["stage"] != "approve":
        return
    extra = ()
    if run["charter"].get("until") == "disabled":                # option C: the owner's admissions count like the starting list
        try:
            from shipmiracle.autopilot import standing
            extra = standing.admitted_ids(c.auto["mpid"], c.auto["main"])
        except Exception as e:
            hio.log_err("stage", e)
    t = _try(engine, work, trs, engine.charter_approve, work, cr["id"], run["charter"], run["st"]["charter_sha"], c.ev("charter", "engine", {}), c.rules, extra)
    if t:
        _decide(c, cr["id"], "approve", "charter_approve", "plan %s approved by the charter" % (cr["plan_sha"] or "")[:8])


def _standing_pause(c, reason) -> bool:
    """Option C: pause the run for `reason` (qa_fail, review_reject, unknown_request). True when this call paused it. No effect on other runs."""
    if c.auto is None:
        return False
    run = _run(c)
    if not run["ok"] or not run["S"].is_standing(run["st"]):
        return False
    if run["S"].pause_for(c.auto["mpid"], reason):
        hio.emit_event("autopilot.paused", {"reason": reason}, project=c.auto["mpid"])
        return True
    return False


def _auto_stop(c, r0, engine, store, diffstat):
    """Stop in an auto worktree: a CR that is delivered in the worktree's log but not yet merged is fast-forward merged by the ENGINE (deliver.finish_cr);
    then the next CR of the charter starts (the Stop is blocked once so the chat goes on) or the run ends (done)."""
    run = _run(c)
    st = run["st"]
    if not run["ok"] or not st or not c.render:
        return r0
    cid = st.get("cr")
    if not cid or st.get("branch") != c.auto["branch"]:
        return r0
    work = store.load(c.pd)
    cr = engine.get_cr(work, cid)
    if cr is None or cr["status"] != "delivered":
        return r0
    from shipmiracle.autopilot import deliver
    try:
        res = deliver.finish_cr(c.pd, cid)
    except Exception as e:
        hio.log_err("stage", e)
        return r0
    run["S"].settle(c.auto["mpid"])
    if res["status"] == "merged" and res.get("next"):
        n = res["next"]
        txt = "AUTOPILOT: %s Continue now with %s on branch %s: start its Scope/Plan stage (run `shipm cr show --next`)." % (res["text"], n["cr"], n["branch"])
        if c.sess.get("auto_next") == n["cr"]:
            return r0
        c.sess["auto_next"], c.dirty = n["cr"], True
        return core.Result(block=True, reason=txt)
    if res["status"] in ("refused", "limit") and r0 is None:
        return core.Result(system_message="AUTOPILOT: " + res["text"])
    return core.Result(system_message="AUTOPILOT: " + res["text"]) if r0 is None else r0


# ---------------------------------------------------------------- helpers
def _sync_render(c, store) -> None:
    """A work.json that is not what the engine rendered last (forged, hand-edited, conflicted) is reported and rewritten. Decisions never read it."""
    if not c.render:
        return
    wp = os.path.join(c.pd, ".shipmiracle", "work.json")
    rp = os.path.join(c.ctx.state, "v1", "cr", c.pid + ".rendered")
    try:
        if os.path.islink(wp):
            bad = True
        else:
            fd = os.open(wp, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)       # a FIFO must not hang the hook
            try:
                if not stat.S_ISREG(os.fstat(fd).st_mode):
                    raise OSError("work.json is not a regular file")
                cur = os.read(fd, 1 << 20)
            finally:
                os.close(fd)
            if not os.path.exists(_log_path(c.ctx, c.pid)):
                bad = True                                   # no log yet: store imports it (fails closed) and persists
            else:
                try:
                    with open(rp, "rb") as f:
                        last = f.read(200).decode("ascii", "replace").strip()
                except OSError:
                    last = ""
                bad = hashlib.sha256(cur).hexdigest() != last
    except OSError:
        bad = False                                          # no work.json: nothing forged
    if bad:
        store.load_work(c.pd)


def _norm_head(prompt: str) -> str:
    """The prompt with leading invisible characters (zero-width, BOM, controls, spaces) removed, lower case, for the envelope tests."""
    import unicodedata
    i = 0
    while i < len(prompt) and i < 200 and (unicodedata.category(prompt[i]) in ("Cf", "Cc", "Zs", "Zl", "Zp") or prompt[i].isspace()):
        i += 1
    return prompt[i:i + 400].lower()


def _hand_back(prompt: str) -> bool:
    p = _norm_head(prompt).replace("_", "-")                 # `<task_notification` is `<task-notification` (P6 sec M1)
    return p.startswith(HAND_BACK) or "<agent-message from=" in p[:200] or bool(ENVELOPE_RE.search(p[:200])) or hio.handback(prompt)


def _owner_file(c) -> str:
    return os.path.join(c.ctx.state, "v1", "stage-owner", c.pid + ".json")


def _owner_note(c) -> None:
    """The session that presented the plan (ExitPlanMode in the main chat) is the owner's top-level session for this project's change requests (P6 sec B1)."""
    if c.ctx.data.get("agent_id"):
        return
    try:
        hio.atomic_json(_owner_file(c), {"sid": c.ctx.sid, "ts": c.now})
    except OSError as e:
        hio.log_err("stage", e)


def _owner_check(c, action: str):
    """(ok, why) for an owner-only effect of a prompt (approve a plan, unblock a CR, release a hold): the chat must be the owner's top-level interactive chat
    (ancestry: no nested `claude`, a recognised owner host above it) AND the session that presented the plan (approval always; unblock and release when a plan was presented
    at all, otherwise the ancestry alone). Anything else is refused with an event."""
    why = ""
    try:
        from .autopilot import ancestry_ok
        ok, why = ancestry_ok(c.ctx.env)
        if ok:
            try:
                with open(_owner_file(c), encoding="utf-8") as f:
                    rec = json.load(f)
            except (OSError, ValueError):
                rec = None
            if isinstance(rec, dict):
                if rec.get("sid") != c.ctx.sid:
                    ok, why = False, "this is not the session that presented the plan"
            elif action == "approve":
                ok, why = False, "no session has presented a plan"
    except Exception as e:
        hio.log_err("stage", e)
        ok, why = False, "the chat could not be verified"
    if not ok:
        hio.emit_event("stage.owner_refused", {"action": action, "why": why[:100]}, project=c.pid)
    return ok, why


def _approval(data) -> bool:
    """The owner approves a plan with a SHORT message: an approval word first, at most 40 characters, no question mark, no question or hedge word.
    A question about the plan ('how would you implement step 2?') is not approval. The word lists are plan_approval's (NEGATE); only tightened here."""
    prompt = data.get("prompt")
    if not isinstance(prompt, str) or hio.panel_or_slash(prompt):
        return False
    p = prompt.strip().lower()
    if not p or len(p) > APPROVAL_MAX or "?" in p or "\uff1f" in p or "\u061f" in p:
        return False
    if not APPROVE_HEAD.match(p) or HEDGE.search(p):
        return False
    from .plan_approval import NEGATE
    return not NEGATE.search(p)


def _clip(s, n=CTX_MAX):
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[:n - 1] + "..."


def _na_text(c, work, engine):
    """The next-action text (clipped like before) plus, when the playbook lists assets for the stage the model works on next, the toolbox line: pointers as untrusted data
    (F5 stage brief). Never raises; the text alone when anything is off."""
    na = engine.next_action(work, c.rules)
    txt = na["text"]
    try:
        cr = engine.active_cr(work)
        if cr is not None and cr["status"] == "open" and not cr["hold"] and (c.rules or {}).get("assets"):
            stg = "do" if cr["stage"] == "verify" and cr.get("need_build") else cr["stage"]
            from shipmiracle.playbook import toolbox
            extra = toolbox.brief_text(c.pd, c.rules, stg, (c.rules.get("labels") or {}).get(stg))
            if extra:
                return _clip(txt) + " " + extra[:TOOLBOX_CTX_MAX]
    except Exception as e:
        hio.log_err("stage", e)
    return txt


def _tx(c, store, fn):
    """store.transact; afterwards (outside the lock) the stage reports of every stage that just ended are written (private, state folder)."""
    box = []

    def g(work):
        r, trs = fn(work)
        box.extend(trs)
        return r, trs
    r = store.transact(c.pd, g, do_render=c.render)
    if box and c.render:
        _stage_reports(c, store, box)
    return r


def _stage_reports(c, store, trs):
    """write_stage for each stage exit among `trs` (a verify FAIL, a finished stage, the learn stage when the CR is delivered). Never raises."""
    try:
        from shipmiracle.playbook import engine
        from shipmiracle.report import write
        work = store.load(c.pd)
        seen = set()
        for tr in trs:
            op, st, cid = tr.get("op"), tr.get("stage"), tr.get("cr")
            if st not in ("scope", "plan", "approve", "do", "verify", "review", "deliver", "learn") or (cid, st, op) in seen:
                continue
            cr = engine.get_cr(work, cid)
            if cr is None:
                continue
            attempt = None
            if op == "fail":
                n = (tr.get("ev") or {}).get("data", {}).get("n")
                attempt = n if isinstance(n, int) and not isinstance(n, bool) else None
            elif op == "deliver":
                pass
            elif op == "block" and st == "verify" and ((tr.get("ev") or {}).get("data") or {}).get("reason") == "verify_twice":
                seen.add((cid, st, op))
                _fix_draft(c, cid, cr)
                continue
            elif op == "advance":
                if st == "learn" or not (cr["stages"].get(st) or "").startswith("done"):
                    continue                                 # a lens of a review that is not complete yet, half of the learn stage
            else:
                continue
            seen.add((cid, st, op))
            write.write_stage(c.pd, cid, st, attempt=attempt)
    except Exception as e:
        hio.log_err("stage", e)


def _fix_draft(c, cid, cr) -> None:
    """F6: a CR failed Verify twice -> write the proposed playbook fix as a draft for `shipm playbook set --from-draft` (owner only). The draft is untrusted text; the chat has no
    way to apply it. Not in an autopilot worktree (its main project owns the playbook). Never raises."""
    if c.auto is not None or not c.render:
        return
    try:
        from shipmiracle.playbook import fixplan
        names, _created = fixplan.changed(c.pd, cr.get("base"))
        prop = fixplan.for_cr(c.pd, names)
        res = fixplan.ensure_draft(c.pd, (c.rules or {}).get("project") or os.path.basename(c.pd), cid, prop, c.now)
        hio.emit_event("stage.fix_draft", {"cr": cid, "draft": res}, project=c.pid)
    except Exception as e:
        hio.log_err("stage", e)


def _clean(text, n):
    """A verifier/reviewer phrase as it may be stored in the log and the reports: the P4 record redaction (shipmiracle.hooks.shadow.red) is applied and a phrase that
    holds a secret shape is dropped altogether (not stored half-redacted). Returns '' to drop."""
    if not text:
        return ""
    try:
        from .shadow import red
        r = red(text)
    except Exception as e:                                   # no redactor: store nothing rather than a secret
        hio.log_err("stage", e)
        return ""
    return "" if r != text else text[:n]


def _evidence(msg):
    """What the verifier/reviewer said, for the reports: Evidence, Not verified, Failed and the backticked command (all clipped and redacted; facts.py reads them)."""
    from . import flow as F
    out = {}
    m = None
    for m in re.finditer(r"(?im)^[ \t*_#-]*Evidence[ \t*_]*:[ \t*_]*(.*)$", msg[-20000:]):      # the last Evidence line, backticks kept (the report needs the command)
        pass
    ev = _clean(" ".join(m.group(1).split()).strip("*_ ") if m else "", 150)
    if ev:
        out["evidence"] = ev
        m = re.search(r"`([^`]{2,80})`", ev)
        if m:
            out["cmd"] = m.group(1)
    nv = _clean(" ".join(F._field(msg, "Not verified").split()), 150)
    if nv:
        out["not_verified"] = nv
    fl = [_clean(x.strip(" `*_"), 60) for x in re.split(r"[,;]", F._field(msg, "Failed")) if x.strip(" `*_")]
    fl = [x for x in fl if x]
    if fl:
        out["failed"] = fl[:5]
    return out


def _baseline(c):
    """Paths that were already changed when the session began (flow's baseline): they are not part of a CR that is opened later."""
    b = c.st.get("baseline")
    return [p for p in b[:300] if isinstance(p, str)] if isinstance(b, list) else []


def _try(engine, work, trs, call, *a, **k):
    """Call an engine function; a refusal (wrong evidence/order) is normal flow and adds nothing."""
    try:
        r = call(*a, **k)
    except engine.EngineRefused:
        return None
    if isinstance(r, list):
        trs.extend(r)
    return r


def _roles(c):
    r = c.st.get("roles")
    return r if isinstance(r, dict) else {}


def _role_of_type(c, t):
    """The effective role of a subagent type: frontmatter `Flow role:`, flow's DEFAULT_ROLE/ALIASES, shipmiracle.agents in the user-level layout."""
    if not t or "/" in t or ".." in t:
        return ""
    from . import flow as F
    claimed = ""
    try:
        with open(os.path.join(c.pd, ".claude", "agents", t + ".md"), errors="ignore") as f:
            m = re.search(r"^Flow role:\s*(\w+)", f.read(20000), re.M)
        if m:
            claimed = m.group(1).lower()
    except OSError:
        pass
    if not claimed:
        claimed = F.DEFAULT_ROLE.get(F.ALIASES.get(t, t), "build" if re.search(r"engineer|sre|developer|implement|^builder", t) else "")
    eff = claimed
    try:
        if F.shipmiracle_layout() == "userlevel":
            from shipmiracle import agents
            r = agents.resolve(t, c.pd)
            if r is None:
                eff = "support" if claimed in F.PRIV else claimed
            else:
                eff = r.effective
    except Exception as e:
        hio.log_err("stage", e)
    return eff


def _stopped_role(c):
    atype = c.ctx.agent_type
    v = _roles(c).get("%s:%s" % (c.ctx.agent_id, atype)) if c.ctx.agent_id else None
    if isinstance(v, list) and len(v) == 2:
        return str(v[1])
    if isinstance(v, str) and v:
        return v
    return _role_of_type(c, atype)


def _snap_of(store, c, cr):
    s = store.load_snapshot(c.pd, cr["id"])
    return s if isinstance(s, dict) else {"base": cr.get("base"), "untracked": []}


def _measure(c, diffstat, store, cr):
    """The CR's current diff against its base, or None when git fails (fail open)."""
    try:
        return diffstat.evaluate(c.pd, _snap_of(store, c, cr), c.rules)
    except Exception as e:
        hio.log_err("stage", e)
        return None


def _diff_data(d):
    return {"files": d["files"], "lines": d["lines"], "risk": d["risk"][:3], "deps": d["deps"], "ui": d["ui"], "submodule": d.get("submodule", False)}


def _mark(c, happened):
    if happened:
        c.sess["stage_event"] = True
        c.dirty = True


def _shadow_or_playbook(c):
    return c.eng in ENGINES and c.level != "off"


def _context(c, text):
    """additionalContext only when the engine enforces (shadow emits nothing) and the level is not off."""
    return _clip(text, CTX_MAX + TOOLBOX_CTX_MAX) if (c.eng == "playbook" and c.level != "off") else ""


# ---------------------------------------------------------------- refusals (cap, bypass, level, shadow)
def _emit_refusals(c, refs, cr, stage_name):
    """-> (blocking reasons, note texts). Applies cap, bypass, level and the shadow engine, and logs the events."""
    block, notes = [], []
    turn = c.sess.setdefault("refusals", {})
    for kind, msg in refs:
        if kind not in NO_BYPASS and c.st.get("bypass"):
            if not c.sess.get("bypass_logged"):
                c.sess["bypass_logged"], c.dirty = True, True
                hio.emit_event("stage.bypass", {"kind": kind, "cr": cr}, project=c.pid)
            continue
        cap = 1 if kind == "cr_continue" else CAP
        if kind == "asset_changed" and turn.get(kind, 0) >= LOOP_MAX:
            if not c.sess.get("asset_loop_noted") and c.eng == "playbook" and c.level != "off":
                c.sess["asset_loop_noted"], c.dirty = True, True
                notes.append("A toolbox asset is STILL changed and the change request stays at Deliver (nothing is delivered); the stop is allowed after %d refusals. The owner re-signs or removes the asset at a terminal." % LOOP_MAX)
            continue
        if kind not in NO_CAP and turn.get(kind, 0) >= cap:
            continue
        if c.eng == "shadow":
            hio.emit_event("stage.shadow", {"kind": kind, "cr": cr, "stage": stage_name}, project=c.pid)
            continue
        if c.level == "off":
            continue
        turn[kind] = turn.get(kind, 0) + 1
        c.dirty = True
        if kind == "cr_continue":
            c.sess["continued"] = True
        if c.level == "warn" and kind not in HARD:
            hio.emit_event("stage.noted", {"kind": kind, "cr": cr, "stage": stage_name}, project=c.pid)
            notes.append(msg)
        else:
            hio.emit_event("stage.refused", {"kind": kind, "cr": cr, "stage": stage_name}, project=c.pid)
            block.append(msg)
    return block, notes


# ---------------------------------------------------------------- UserPromptSubmit
def _on_prompt(c, engine, store):
    prompt = c.ctx.data.get("prompt")
    if not isinstance(prompt, str) or _hand_back(prompt) or hio.panel_or_slash(prompt):
        return None                                          # a hand-back is not the owner: it neither approves nor unblocks nor starts a turn
    c.sess.update(refusals={}, stage_event=False, continued=False, bypass_logged=False, asset_loop_noted=False)
    c.sess.pop("pending_ctx", None)
    c.dirty = True
    words = _approval(c.ctx.data)

    def fn(work):
        cr = engine.active_cr(work)
        trs = []
        if cr is None:
            return None, trs
        owner = c.ev("owner_prompt", "owner", {"owner_words": words})
        trust = []

        def trusted(action):
            if not trust:
                trust.append(_owner_check(c, action)[0])
            return trust[0]
        if cr["status"] == "blocked" and trusted("unblock"):
            _try(engine, work, trs, engine.unblock, work, cr["id"], owner)
        if cr["hold"] and cr["status"] == "open" and trusted("release"):
            _try(engine, work, trs, engine.release, work, cr["id"], owner)
        if words and cr["status"] == "open" and cr["stage"] == "approve" and trusted("approve"):
            _try(engine, work, trs, engine.advance, work, cr["id"], "approve", c.ev("owner_prompt", "owner", {"owner_words": True, "plan_sha": cr["plan_sha"]}), c.rules)
        return (_na_text(c, work, engine) if trs else None), trs

    text = _tx(c, store, fn)
    _mark(c, text)
    return core.Result(additional_context=_context(c, text)) if text and _context(c, text) else None


# ---------------------------------------------------------------- PreToolUse Agent|Task
def _on_agent_call(c, engine, store):
    ti = c.ctx.data.get("tool_input")
    t = ti.get("subagent_type") if isinstance(ti, dict) else None
    if not isinstance(t, str) or not t:
        return None
    work = store.load(c.pd)
    cr = engine.active_cr(work)
    if cr is None:
        return None
    refs = engine.can_call_agent(work, c.rules, _role_of_type(c, t))
    if c.auto is not None and _run(c)["ok"] and c.render:
        from shipmiracle.autopilot import budget
        gate_txt = budget.agent_gate(c.auto["mpid"], _run(c)["charter"], starts_stage=True)
        if gate_txt:
            refs = [engine.Refusal("limit_near", gate_txt)] + list(refs)
    if not refs:
        return None
    block, notes = _emit_refusals(c, refs, cr["id"], cr["stage"])
    if block:
        return core.Result(block=True, reason="TEAM FLOW (change request): " + " ".join(block), exit_code=2)
    if notes:
        return core.Result(additional_context="TEAM FLOW (warn-only project): " + " ".join(notes))
    return None


# ---------------------------------------------------------------- PostToolUse
def _on_post(c, engine, store, diffstat, types):
    tool = c.ctx.tool_name
    if tool == "ExitPlanMode":
        return _on_plan(c, engine, store, diffstat)
    if tool in ("Agent", "Task"):
        text = c.sess.pop("pending_ctx", None)
        if text:
            c.dirty = True
            return core.Result(additional_context=text)
    return None


def _on_plan(c, engine, store, diffstat):
    _owner_note(c)
    ti = c.ctx.data.get("tool_input")
    plan = ti.get("plan") if isinstance(ti, dict) and isinstance(ti.get("plan"), str) else ""
    sha = hashlib.sha256(plan.encode("utf-8", "replace")).hexdigest()
    arch = c.st.get("arch_ts")
    arch = int(arch) if isinstance(arch, (int, float)) and not isinstance(arch, bool) else 0
    work0 = store.load(c.pd)
    snap = None
    if engine.active_cr(work0) is None:
        try:
            snap = diffstat.snapshot(c.pd)
        except Exception as e:
            hio.log_err("stage", e)
            snap = {"base": None, "untracked": []}
    first = next((ln.strip("#*- \t") for ln in plan.splitlines() if ln.strip("#*- \t")), "") or "Planned change"

    def fn(work):
        trs = []
        cr = engine.active_cr(work)
        if cr is None:
            if _standing_pause(c, "unknown_request"):            # option C: a request the chat opens inside the auto worktree is out of charter
                return None, []
            opened_at = arch if 0 < arch <= c.now and c.now - arch < 6 * 3600 else c.now
            cr, t0 = engine.open_cr(work, first, "lead", opened_at, lane="full", base=snap["base"], rules=c.rules, kind="auto_open", sid8=c.ctx.sid[:8])
            trs.extend(t0)
            store.save_snapshot(c.pd, cr["id"], snap)
        if cr["status"] == "open" and cr["stage"] in PLAN_STAGES and arch >= cr["opened"] > 0:
            _try(engine, work, trs, engine.advance, work, cr["id"], "plan",
                 c.ev("plan_presented", "planner", {"plan_sha": sha, "role_ts": arch, "role": "plan"}), c.rules)
        _auto_approve(c, engine, work, trs)
        return (_na_text(c, work, engine) if trs else None), trs

    text = _tx(c, store, fn)
    c.dirty = True
    _mark(c, text)
    return core.Result(additional_context=_context(c, text)) if text and _context(c, text) else None


# ---------------------------------------------------------------- SubagentStop
LENS_NAMES = {"independent-reviewer": "correctness", "security-reviewer": "risk"}      # same as shipmiracle.agents.ALIAS_LENS


def _declared_lens(c, atype):
    """The lens an agent TYPE is bound to (not what its message claims): `Lens:` in the agent file's front matter, the user-level resolver's lens,
    or the legacy names (security-reviewer = risk, independent-reviewer = correctness); None for a type that declares none."""
    if not atype or "/" in atype or ".." in atype:
        return None
    try:
        with open(os.path.join(c.pd, ".claude", "agents", atype + ".md"), errors="ignore") as f:
            m = re.search(r"^Lens:\s*(correctness|risk|design)\b", f.read(20000), re.M | re.I)
        if m:
            return m.group(1).lower()
    except OSError:
        pass
    if atype in LENS_NAMES:
        return LENS_NAMES[atype]
    try:
        from . import flow as F
        if F.shipmiracle_layout() == "userlevel":
            from shipmiracle import agents
            r = agents.resolve(atype, c.pd)
            if r is not None and r.lens:
                return r.lens
    except Exception as e:
        hio.log_err("stage", e)
    return "risk" if "secur" in atype.lower() else None


def _lens_of(c, lens_text, atype, default_role):
    """-> the lens this review verdict counts for, or None (refused). The agent type decides: a declared lens wins over the message; a type with none
    can claim correctness (or design for the design role) but never the risk lens (that needs a security-reviewer-class agent)."""
    if default_role == "design":
        return "design"
    d = _declared_lens(c, atype)
    if d:
        return d
    t = (lens_text or "").lower()
    if "design" in t:
        return "design"
    if "risk" in t or "secur" in t:
        return None
    return "correctness"


def _on_subagent_stop(c, engine, store, diffstat, types):
    from . import flow as F
    role = _stopped_role(c)
    if role not in ("scope", "build", "test", "review", "design"):
        return None
    atype = c.ctx.agent_type or role
    msg = c.ctx.data.get("last_assistant_message")
    msg = msg if isinstance(msg, str) else ""
    work0 = store.load(c.pd)
    cr0 = engine.active_cr(work0)
    diff = None
    if role == "build":
        if cr0 is not None:
            diff = _measure(c, diffstat, store, cr0)
            c.sess["diff_ts"], c.dirty = time.time(), True
        else:
            try:
                diff = diffstat.evaluate(c.pd, {"base": diffstat.head(c.pd), "untracked": [], "ignore": _baseline(c)}, c.rules)
            except Exception as e:
                hio.log_err("stage", e)
            if not diff or diff["files"] < 1:
                return None                                  # nothing built: no CR from this stop
    if cr0 is None and role != "build":
        return None
    verdict = counts = lens = ""
    qa_ok = False
    ed = {}
    if role == "test":
        verdict, counts, _l = F.parse_verdict(msg, F.TEST_VERDICTS)
        qa_ok = verdict == "PASS" and F.qa_eval(c.st, "strict")[0] == "passed"
        ed = _evidence(msg)
    elif role == "review":
        verdict, _c, lt = F.parse_verdict(msg, F.REVIEW_VERDICTS)
        lens = _lens_of(c, lt, atype, role)
        ed = _evidence(msg)
        if lens is None:
            hio.emit_event("stage.lens_refused", {"cr": cr0["id"] if cr0 else None, "reason": "risk lens needs a security-reviewer-class agent"}, project=c.pid)
            return None
        if cr0 is not None:
            by = c.sess.setdefault("lens_by", {}).setdefault(cr0["id"], {})
            if not any(cr0["lenses"].values()):
                by.clear()                                   # a new review attempt (after a build / reset): the same type may review again
            if by.get(atype) not in (None, lens):
                hio.emit_event("stage.lens_refused", {"cr": cr0["id"], "reason": "one agent type cannot satisfy two lenses in one attempt"}, project=c.pid)
                return None
            by[atype] = lens
            c.dirty = True
    elif role == "design":
        verdict, _c, _l = F.parse_verdict(msg, F.TEST_VERDICTS)
        lens = "design"
        ed = _evidence(msg)
    snap = None
    if cr0 is None and role == "build":
        try:
            snap = {"base": diffstat.head(c.pd), "untracked": [], "ignore": _baseline(c)}
        except Exception:
            snap = {"base": None, "untracked": [], "ignore": _baseline(c)}

    def fn(work):
        trs = []
        cr = engine.active_cr(work)
        if cr is None:
            if _standing_pause(c, "unknown_request"):
                return None, []
            title = "Change by %s" % atype
            lane = "fast" if (c.rules.get("lanes") or {}).get("fast_allowed") else "full"      # an ops project has no fast lane
            cr, t0 = engine.open_cr(work, title, "lead", c.now, lane=lane, base=snap["base"], rules=c.rules, kind="auto_open", sid8=c.ctx.sid[:8])
            trs.extend(t0)
            store.save_snapshot(c.pd, cr["id"], snap)
        cid = cr["id"]
        e = lambda kind, data: c.ev(kind, atype, dict(data, role=role))                # noqa: E731
        if role == "scope":
            _try(engine, work, trs, engine.advance, work, cid, "scope", e("role_stop", {}), c.rules)
        elif role == "build" and diff is not None:
            _try(engine, work, trs, engine.observe_diff, work, cid, diff, e("diff_eval", {}), c.rules)
            if diff["files"] >= 1:
                _try(engine, work, trs, engine.advance, work, cid, "do", e("role_stop", {"diff": _diff_data(diff)}), c.rules)
        elif role == "test":
            if qa_ok:
                _try(engine, work, trs, engine.advance, work, cid, "verify", e("qa_pass", dict(ed, counts=counts)), c.rules)
            elif verdict == "FAIL":
                _try(engine, work, trs, engine.fail, work, cid, "verify", e("qa_fail", dict(ed, counts=counts)), c.rules)
        elif role in ("review", "design") and verdict:
            _try(engine, work, trs, engine.advance, work, cid, "review", e("review_verdict", dict(ed, lens=lens, verdict=verdict)), c.rules)
        cr = engine.get_cr(work, cid)
        return {"text": _na_text(c, work, engine) if trs else None, "cr": cid,
                "reviewed": cr is not None and cr["stages"]["review"].startswith("done")}, trs

    res = _tx(c, store, fn)
    if role == "test" and verdict == "FAIL":
        _standing_pause(c, "qa_fail")                            # option C: a single Verify FAIL pauses (A/B allow one retry)
    elif role in ("review", "design") and verdict and verdict != "ACCEPT":
        _standing_pause(c, "review_reject")
    if not res or not res["text"]:
        return None
    _mark(c, True)
    if role in ("review", "design") and res["reviewed"]:
        try:
            rb = diffstat.snapshot(c.pd)["base"]
            c.sess.setdefault("review_snap", {})[res["cr"]] = rb
            diffstat.pin(c.pd, res["cr"] + "-review", rb)
        except Exception as e:
            hio.log_err("stage", e)
    ctx_text = _context(c, res["text"])
    if ctx_text:
        c.sess["pending_ctx"] = ctx_text                     # delivered by the PostToolUse of the Agent call (SubagentStop has no additionalContext)
    return None


# ---------------------------------------------------------------- Stop
def _delivered(c, diffstat, cr):
    """git_delivered: HEAD moved past the CR's base, nothing of the team's is dirty, nothing is unpushed (no upstream counts as pushed only when git.autopush is off)."""
    head = diffstat.head(c.pd)
    if not head or head == cr.get("base"):
        return None
    out = diffstat._git(c.pd, ["status", "--porcelain", "-z", "--untracked-files=normal"]).split(b"\0")
    for ent in out:
        p = ent[3:].decode("utf-8", "surrogateescape") if len(ent) > 3 else ""
        if p and not diffstat._excluded(p.rstrip("/")):
            return None
    try:
        n = diffstat._git(c.pd, ["rev-list", "--count", "@{u}..HEAD"]).decode("ascii", "replace").strip()
        if n != "0":
            return None
    except Exception:
        # m5: no upstream (or git failed) is NOT "pushed" unless git.autopush is off (then the report says "not pushed (autopush off)")
        if _autopush_on():
            return None
    return head


def _autopush_on() -> bool:
    try:
        from shipmiracle import config
        return config.get("git.autopush") is True
    except Exception:
        return True                                          # unknown: do not claim delivered


def _status_dated(c, diffstat):
    try:
        txt = diffstat._git(c.pd, ["show", "HEAD:docs/STATUS.md"]).decode("utf-8", "replace")
    except Exception:
        return False
    for ln in txt.splitlines():
        if ln.strip().startswith("Updated:"):
            return time.strftime("%Y-%m-%d", time.localtime(c.now)) in ln
    return False


def _report_written(c, cr_id, store=None):
    """True only for a report the ENGINE wrote: the log has an `op:report` line for the file with its content sha, and the file (a regular file inside
    docs/reports, not a symlink) still has exactly that sha. A file that merely has the CR id in its name is not accepted."""
    try:
        if store is None:
            from shipmiracle.playbook import store
        from shipmiracle.playbook import engine
        cr = engine.get_cr(store.load(c.pd), cr_id)
        rs = (cr or {}).get("report_sha") or {}
        root = os.path.realpath(os.path.join(c.pd, "docs", "reports"))
        for rel, sha in rs.items():
            fp = os.path.join(c.pd, rel)
            if os.path.islink(fp) or os.path.dirname(os.path.realpath(fp)) != root or not os.path.isfile(fp):
                continue
            with open(fp, "rb") as f:
                if hashlib.sha256(f.read(1 << 20)).hexdigest() == sha:
                    return True
    except Exception as e:
        hio.log_err("stage", e)
    return False


def _write_cr_report(c, cr_id):
    try:
        from shipmiracle.report import write
        write.write_cr(c.pd, cr_id)
    except Exception as e:
        hio.log_err("stage", e)


def _asset_block(c):
    """F5: the text that blocks Deliver when a toolbox asset of the playbook no longer matches its signed hash (changed, missing, a symlink now), else None. Fail-safe: an error
    while checking is a block too (an unreadable asset must not pass), with the error type only."""
    if not (c.rules or {}).get("assets"):
        return None
    try:
        from shipmiracle.playbook import toolbox
        bad = toolbox.deliver_problems(c.pd, c.rules)
        return toolbox.deliver_message(bad) if bad else None
    except Exception as e:
        hio.log_err("stage", e)
        return "Deliver is blocked: the toolbox assets could not be checked (%s). Ask the owner to run `shipm playbook asset list`." % type(e).__name__


def _on_stop(c, engine, store, diffstat):
    work0 = store.load(c.pd)
    cr0 = engine.active_cr(work0)
    if cr0 is None or cr0["status"] != "open":
        return None
    d = c.ctx.data
    msg = d.get("last_assistant_message")
    from .keep_going import ASKS
    asks = not isinstance(msg, str) or bool(ASKS.search(msg)) or d.get("stop_hook_active") is True
    stage0, lane0 = cr0["stage"], cr0["lane"]
    diff = delta = None
    deliver_head = None
    asset_msg = None
    learn_kinds = []
    try:
        if stage0 == "deliver":
            asset_msg = _asset_block(c)
            deliver_head = None if asset_msg else _delivered(c, diffstat, cr0)
        elif stage0 == "learn":
            if _status_dated(c, diffstat):
                learn_kinds.append("status_dated")
                if c.render and not _report_written(c, cr0["id"]):
                    _write_cr_report(c, cr0["id"])           # the engine delivers only after the report exists (write_cr accepts a CR at learn)
            if _report_written(c, cr0["id"]):
                learn_kinds.append("report_written")
        built = c.st.get("build_ts")
        stale = not isinstance(built, (int, float)) or built > c.sess.get("diff_ts", 0)       # an agent built since the diff was last measured
        if stale and (lane0 == "fast" or (lane0 == "full" and not cr0["stages"]["approve"].startswith("done"))):
            diff = _measure(c, diffstat, store, cr0)
            c.sess["diff_ts"], c.dirty = time.time(), True
        rs = (c.sess.get("review_snap") or {}).get(cr0["id"])
        if rs and any(cr0["lenses"].values()):
            delta = diffstat.delta(c.pd, rs)
    except Exception as e:
        hio.log_err("stage", e)

    def fn(work):
        trs = []
        cr = engine.active_cr(work)
        if cr is None:
            return None, trs
        cid = cr["id"]
        e = lambda kind, data: c.ev(kind, "engine", data)                               # noqa: E731
        if diff is not None:
            _try(engine, work, trs, engine.observe_diff, work, cid, diff, e("diff_eval", {}), c.rules)
        if delta is not None:
            _try(engine, work, trs, engine.post_review_delta, work, cid, delta, e("diff_eval", {}), c.rules)
        if deliver_head:
            _try(engine, work, trs, engine.advance, work, cid, "deliver", e("git_delivered", {"head": deliver_head[:12]}), c.rules)
        for k in learn_kinds:
            _try(engine, work, trs, engine.advance, work, cid, "learn", e(k, {}), c.rules)
        _auto_approve(c, engine, work, trs)
        sess = {"stage_event": c.sess.get("stage_event") or bool(trs), "continued": c.sess.get("continued"), "asks": asks,
                "auto_active": c.auto is not None and _run(c)["ok"]}
        cur = engine.active_cr(work)
        refs = engine.can_stop(work, c.rules, sess) if cur is not None else []
        if asset_msg and cur is not None and cur["stage"] == "deliver":
            refs = list(refs) + [engine.Refusal("asset_changed", asset_msg)]
        return {"refs": refs, "cr": cid, "stage": cur["stage"] if cur else "done", "trs": bool(trs), "reviewed": any(cur["lenses"].values()) if cur else False,
                "text": _na_text(c, work, engine) if trs else None}, trs

    res = _tx(c, store, fn)
    if not res:
        return None
    _mark(c, res["trs"])
    if not res["reviewed"] and (c.sess.get("review_snap") or {}).pop(res["cr"], None):
        c.dirty = True                                       # the review was reset by a big change: the next review takes a new snapshot
    block, notes = _emit_refusals(c, [(r.kind, r.msg) for r in res["refs"]], res["cr"], res["stage"])
    if block and c.auto is not None and any(r.kind == "cr_continue" for r in res["refs"]):
        _decide(c, res["cr"], res["stage"], "continue", "the run goes on with %s" % res["stage"])
    if block:
        return core.Result(block=True, reason="TEAM FLOW (change request): " + " ".join(block))
    if notes:
        return core.Result(system_message="TEAM FLOW (warn-only project): " + " ".join(notes))
    return None


core.register("UserPromptSubmit", "stage", None, stage)
core.register("PreToolUse", "stage", None, stage)
core.register("PostToolUse", "stage", None, stage)
core.register("SubagentStop", "stage", None, stage)
core.register("Stop", "stage", None, stage)
