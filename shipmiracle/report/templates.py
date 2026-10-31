"""Report templates: facts -> text. Fixed header, fixed field order (lint.py checks the same table), no model, no clock (the timestamps are
the facts'). Free text is already cleaned by facts; a field with no recorded value says so in words."""
from __future__ import annotations

import re
import time

from . import clean

WORDS = ("PASS", "FAIL", "BLOCKED", "NOT TESTED")
ORDINAL = {1: "1st", 2: "2nd", 3: "3rd"}
_EV_REF = re.compile(r"[0-9]|[\w/.-]+\.[A-Za-z0-9]{1,6}\b")


def _unpushed():
    """'committed', plus the reason when nothing can have been pushed: git.autopush is off (P6 sec m5)."""
    try:
        from .. import config
        return "committed (not pushed: autopush off)" if config.get("git.autopush") is not True else "committed"
    except Exception:
        return "committed"


def stamp(ts) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))


def hhmm(ts) -> str:
    return time.strftime("%H:%M", time.localtime(ts))


def _mins(secs):
    if secs is None:
        return "time not recorded"
    return "<1 min" if secs < 60 else "%d min" % round(secs / 60.0)


def _tokens(t):
    if not isinstance(t, int):
        return "tokens not measured"
    return "%dk tokens" % round(t / 1000.0) if t >= 1000 else "%d tokens" % t


def evidence_ok(text) -> bool:
    """The lint rule: a backticked command, `->`, then digits or a file/sha reference."""
    m = re.fullmatch(r"`[^`]+` -> (.+)", text or "")
    return bool(m and _EV_REF.search(m.group(1)))


def _safe(text) -> str:
    """Evidence text as it may be printed: the P4 record redaction; a phrase that holds a secret shape is dropped (the line falls back to the recorded counts)."""
    if not text or not isinstance(text, str):
        return ""
    try:
        from ..hooks.shadow import red
        return text if red(text) == text else ""
    except Exception:
        return ""


def evidence_line(facts, verdict=None) -> str:
    """The Evidence value. The agent's own words when they pass the rule (command, ->, number or file); otherwise its words under the
    recorded test command; otherwise what the engine itself recorded."""
    cr = facts["cr"]
    if verdict is not None:
        txt, cmd = _safe(verdict.get("evidence")), _safe(verdict.get("cmd")) or "tests"
        if txt:
            m = re.fullmatch(r"([^`]{1,80}?) -> (.+)", txt)
            if re.match(r"`[^`]+` ->", txt):
                cand = txt
            elif m:                                       # "npm test -> 212 passed": the agent's own command and counts, backticked
                cand = "`%s` -> %s" % (m.group(1).strip().replace("`", "'"), m.group(2))
            else:
                cand = "`%s` -> %s" % (cmd.replace("`", "'"), txt)
            if evidence_ok(cand):
                return cand
        c = verdict.get("counts")
        if isinstance(c, dict) and c:
            return "`%s` -> %s" % (cmd.replace("`", "'"), ", ".join("%d %s" % (v, k) for k, v in c.items()))
        if isinstance(c, str) and c:
            return "`%s` -> %s" % (cmd.replace("`", "'"), c) if evidence_ok("`x` -> " + c) else "`%s` -> %s (attempt %s)" % (cmd, c, verdict.get("attempt", 1))
        return "`shipm cr show %s` -> %s attempt %s recorded by the engine (test output not captured)" % (cr["id"], verdict["stage"], verdict.get("attempt", 1))
    done = sum(1 for s in facts["stages"] if str(s["status"]).startswith("done"))
    return "`shipm cr show %s` -> %d stages done, test output not captured" % (cr["id"], done)


def types_order(stage):
    from ..playbook import types
    return types.ORDER.index(stage) + 1


def _pad(left, right, width=46):
    return left + " " * max(2, width - len(left)) + right


# ------------------------------------------------------------------ stage report

def stage_verdict(facts, stage, attempt=None):
    """(word, verdict row or None, detail) for a stage exit: the newest verdict of the stage, or the one with that attempt number."""
    rows = [v for v in facts["verdicts"] if v["stage"] == stage and (attempt is None or v["attempt"] == attempt)]
    last = rows[-1] if rows else None
    if facts["cr"]["status"] == "blocked":
        return "BLOCKED", last, "blocked: %s" % (facts["cr"].get("blocked") or "see the CR")
    if stage == "verify" and last:
        return ("PASS" if last["verdict"] == "PASS" else "FAIL" if last["verdict"] == "FAIL" else "BLOCKED"), last, "attempt %d of 2" % last["attempt"]
    if stage == "review" and last:
        ok = last["verdict"] in ("ACCEPT", "ACCEPT WITH FIXES", "PASS")
        return ("PASS" if ok else "FAIL"), last, "%s, lens %s" % (last["verdict"], last.get("lens") or "-")
    return "NOT TESTED", last, "stage recorded, not a test"


def stage_report(facts, stage, attempt=None) -> str:
    cr, labels = facts["cr"], facts["labels"]
    row = next(s for s in facts["stages"] if s["id"] == stage)
    word, v, detail = stage_verdict(facts, stage, attempt)
    ts = row["ts"] or (v["ts"] if v else facts["generated"])
    head = _pad("# %s · %s · %s" % (cr["id"], labels.get(stage, stage.capitalize()), word),
                "%s · %s (%s)" % (stamp(ts), facts["project"], facts.get("type") or "no playbook"))
    prev = [s["ts"] for s in facts["stages"] if s["ts"] and s["ts"] < ts]
    secs = ts - max(prev) if prev else (ts - cr["opened"] if ts >= cr["opened"] else None)
    by = (v or {}).get("by") or row["by"] or "engine"
    model = row.get("model")
    out = [head, "Verdict: %s (%s)" % (word, detail), "Evidence: " + (evidence_line(facts, v) if v else
           "`shipm cr show %s` -> stage %d of %d is %s, recorded by the engine (no test output for this stage)" % (cr["id"], types_order(stage), len(facts["stages"]), row["status"]))]
    failed = (v or {}).get("failed") or []
    if failed:
        out.append("Failed: " + ", ".join(failed))
    out.append("By: %s%s · %s · %s" % (by, " (%s)" % model if model else "", _mins(secs), _tokens(row.get("tokens"))))
    nx = facts.get("next")
    if word == "BLOCKED":
        out.append("Next: owner decides: change the plan, fix again, or stop the CR")
    elif nx:
        who = " (%s)" % nx["agent"] if nx.get("agent") else ""
        out.append("Next: %s%s%s" % (nx["label"], who, " fixes the failures" if word == "FAIL" else ""))
    else:
        out.append("Next: none, the CR is %s" % cr["status"])
    out.append("Not verified: " + ((v or {}).get("not_verified") or "not reported for this stage"))
    return "\n".join(out) + "\n"


# ------------------------------------------------------------------ CR report

def learn_lines(facts) -> list:
    """The two Learn-step fields of a CR report: `Proposed assets` (F5; facts["proposed"] = list written only by the Learn step; absent = not computed, no line) and
    `Playbook fix` (F6; facts["fix"] after a double-failed Verify). Every value is engine text (paths are matched against a strict character set before they get here)."""
    out = []
    pa = facts.get("proposed")
    if pa is not None:
        labels = facts["labels"]
        if not pa:
            out.append("Proposed assets: none")
        else:
            from ..playbook import toolbox
            out.append("Proposed assets: %d from this CR; none is added unless the owner runs its command at a terminal" % len(pa))
            for r in pa:
                out.append("  %s — %s; suggested stage %s: `%s`" % (r["path"], toolbox.tidy(r["why"], 120), labels.get(r["stage"], r["stage"]), toolbox.add_command(r)))
    fx = facts.get("fix")
    if fx is not None:
        prop = fx.get("prop")
        if not prop:
            out.append("Playbook fix: none to propose (no changed folder to add as a risk path)")
        else:
            where = {"written": "the draft is .shipmiracle/playbook.draft.md", "kept": "an interview draft is already waiting, so no new draft was written"}.get(fx.get("draft"), "no draft was written")
            out.append("Playbook fix: proposed after tests failed twice; %s; the owner applies it with `shipm playbook set --from-draft` (typed confirmation)" % where)
            out += ["  " + d for d in prop["diff"]]
            if prop["diff_total"] > len(prop["diff"]):
                out.append("  (+%d more lines not shown)" % (prop["diff_total"] - len(prop["diff"])))
    return out


def cr_word(facts):
    cr = facts["cr"]
    if cr["status"] == "delivered":
        return "DELIVERED", "PASS" if cr["verified"] else "NOT TESTED"
    last = facts["verdicts"][-1]["verdict"] if facts["verdicts"] else None
    return "ABANDONED", "BLOCKED" if last == "FAIL" else "NOT TESTED"


def _stages_line(facts):
    labels, cr = facts["labels"], facts["cr"]
    verifies = [v for v in facts["verdicts"] if v["stage"] == "verify"]
    parts = []
    for s in facts["stages"]:
        if s["id"] == "learn":
            continue
        lab, st = s["label"], str(s["status"])
        if st == "skipped":
            parts.append("%s skipped" % lab)
        elif s["id"] == "verify" and verifies:
            n = len(verifies)
            parts.append("%s %s%s" % (lab, verifies[-1]["verdict"], " (%s)" % ORDINAL.get(n, "%dth" % n) if n > 1 else ""))
        elif s["id"] == "review" and st.startswith("done"):
            lens = [v for v in facts["verdicts"] if v["stage"] == "review"]
            parts.append("%s %s" % (lab, ", ".join("%s %s" % (v.get("lens"), v["verdict"]) for v in lens) or s["by"] or "done"))
        elif s["id"] == "deliver" and st.startswith("done"):
            g = facts["git"]
            parts.append("%s %s %s" % (lab, g["head"][:7] if g.get("head") else "-", "pushed" if g.get("pushed") else _unpushed()))
        elif s["id"] == "approve" and st.startswith("done"):
            parts.append("%s %s%s" % (lab, s["by"] or "owner", " " + hhmm(s["ts"]) if s["ts"] else ""))
        elif st.startswith("done"):
            parts.append("%s %s" % (lab, s["by"] or "done"))
        elif st.startswith("fail"):
            parts.append("%s FAIL" % lab)
        else:
            parts.append("%s not reached" % lab)
    return " · ".join(parts)


def cr_report(facts, summary="pending") -> str:
    cr, g = facts["cr"], facts["git"]
    status, word = cr_word(facts)
    out = ["# %s %s · %s · %s" % (cr["id"], cr["title"], status, word)]
    sl = [clean(x, 240) for x in str(summary).split("\n") if clean(x, 240)][:3] or ["pending"]
    out.append("Summary: " + sl[0])
    out += ["  " + x for x in sl[1:]]
    out.append("Stages: " + _stages_line(facts))
    tests = [v for v in facts["verdicts"] if v["stage"] == "verify"]
    passes = [v for v in tests if v["verdict"] == "PASS"]
    out.append("Evidence: " + evidence_line(facts, (passes or tests or [None])[-1]))
    n, files = g.get("files_total", 0), g.get("files") or []
    if files:
        from . import lint
        files = [x if not lint.LINK.search(x) else "(name withheld)" for x in files]       # a model-chosen file name shaped like a host or link would make the report fail its own lint
    out.append("Files: " + ((", ".join(files) + (" (+%d more)" % (n - len(files)) if n > len(files) else "")) if files else "none recorded"))
    cm = g.get("commits") or []
    out.append("Rollback: " + ("git revert %s" % cm[0]["sha"] if len(cm) == 1 else "git revert %s^..%s" % (cm[-1]["sha"], cm[0]["sha"]) if cm else "none, no commit recorded"))
    w, dec = facts["owner_waits"], facts["auto_decisions"]
    out.append("Owner waits: %d%s · Auto-decisions: %d" % (w["n"], " (%s)" % _mins(w["secs"]) if w["n"] else "", len(dec)))
    if dec:
        ch = facts.get("charter") or {}
        out.append("Charter: %s %s" % (ch.get("id") or "unknown", ch.get("goal") or "(goal not recorded)") if ch.get("id") else "Charter: unknown (no longer in the registry)")
        out.append("Decisions:")
        labels = facts["labels"]
        for d in dec[:10]:
            out.append("  %s %s %s — %s" % (hhmm(d["ts"]), labels.get(d["stage"], d["stage"]).replace(" ", "_"), d["rule"], d["detail"] or "no detail"))
        if len(dec) > 10:
            out[-1] = out[-1] + " (+%d more not shown)" % (len(dec) - 10)
    out += learn_lines(facts)
    out.append("Cost: %s · %s wall" % (_tokens(facts.get("tokens")), _mins(facts["wall_s"])))
    nv = []
    for v in facts["verdicts"]:
        if v.get("not_verified") and v["not_verified"] not in nv:
            nv.append(v["not_verified"])
    out.append("Not verified: " + ("; ".join(nv)[:200] if nv else "not reported by the verifier"))
    return "\n".join(out) + "\n"


# ------------------------------------------------------------------ digest

def digest(day, rows) -> str:
    out = ["# Digest · %s" % day]
    td = 0
    for r in rows[:30]:
        td += len(r["delivered"])
        bits = ["%s · %d delivered%s" % (r["project"], len(r["delivered"]), " (PASS)" if r["delivered"] and r["pass"] == len(r["delivered"]) else "")]
        bits.append("open %s at %s" % (r["open"]["id"], r["open"]["stage"]) if r["open"] else "no open CR")
        bits.append("waiting on you: %s" % r["waiting"] if r["waiting"] else "waiting on you: nothing")
        out.append(" · ".join(bits))
    if not rows:
        out.append("no projects with a playbook · 0 delivered · no open CR · waiting on you: nothing")
    out.append("Totals: %d delivered · %d projects · %d open" % (td, len(rows), sum(1 for r in rows if r["open"])))
    out.append("Not verified: reports are built from recorded facts only; live behaviour is not checked here")
    return "\n".join(out) + "\n"
