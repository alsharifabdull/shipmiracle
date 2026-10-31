"""F6 "fix the playbook, not the chat" (release scope C3). When a change request fails Verify twice, the engine proposes ONE concrete playbook edit as a unified diff of the
playbook text (current vs proposed). Nothing is applied here:
  - the proposal is deterministic (no model): the folders the failing CR touched are added to `risk_paths`, so the risk review lens fires there next time;
  - the diff is untrusted text, cleaned and size-capped, shown in the CR report;
  - the same proposal is written as `.shipmiracle/playbook.draft.md` (+ the interview progress file, status draft, `fix_cr`) so the ONLY way to apply it is the owner running
    `shipm playbook set --from-draft` at a terminal and typing `set` (shipmiracle/playbook/cli.py); the draft's sha must match, so a chat that edits the draft cannot apply it.
  A paused or unapplied interview draft of the owner is never overwritten. This module never writes playbook.json, work.json or the registry."""
from __future__ import annotations

import difflib
import hashlib
import json
import re
import time

from .. import projects, state
from . import config as pbconfig
from . import interview, store
from .toolbox import tidy

MAX_ADD = 3
DIFF_LINES = 14
DIFF_LINE_MAX = 100
_GLOB_OK = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,80}/\*\*")
_SKIP_TOP = {"tests", "test", "docs", ".shipmiracle", "node_modules", ".git", ".github"}


def changed(pd, base_sha):
    """(names, created): repo-relative paths added or changed since `base_sha` in the working tree (tracked changes plus untracked files), and the new ones."""
    if not isinstance(base_sha, str) or not re.fullmatch(r"[0-9a-f]{7,64}", base_sha):
        return [], []
    names, created = [], []

    def run(argv):
        try:
            rc, out = projects._run_git(projects.GIT_PREFIX + argv, pd)
        except Exception:
            return []
        return [x for x in out.split("\0") if x] if rc == 0 else []
    for n in run(["diff", "--name-only", "-z", "--no-renames", "--diff-filter=AM", base_sha, "--"]):
        names.append(n)
    for n in run(["diff", "--name-only", "-z", "--no-renames", "--diff-filter=A", base_sha, "--"]) + run(["ls-files", "--others", "--exclude-standard", "-z"]):
        created.append(n)
        names.append(n)
    return sorted(set(names))[:400], sorted(set(created))[:400]


def double_failed(pd, cr_id, base=None) -> bool:
    """True when the CR was blocked with reason verify_twice (two Verify failures in a row) at any time."""
    from ..report import facts as F
    for ln in F._lines_of(pd, base):
        if ln.get("cr") == cr_id and ln.get("op") == "block":
            d = (ln.get("ev") or {}).get("data") if isinstance(ln.get("ev"), dict) else None
            if isinstance(d, dict) and d.get("reason") == "verify_twice":
                return True
    return False


def current_text(cfg) -> list:
    """The playbook as plain lines (what the diff compares): type, level, autopilot, test command, the owner's risk paths."""
    c = cfg or pbconfig.defaults()
    ov = c.get("overrides") or {}
    risk = list(ov.get("risk_paths") or [])
    return render(c, risk)


def render(cfg, risk) -> list:
    ov = cfg.get("overrides") or {}
    out = ["Type: %s" % cfg.get("type"), "Level: %s" % cfg.get("level"), "Autopilot: %s" % cfg.get("autopilot"), "Test command: %s" % (ov.get("test_cmd") or "playbook default"),
           "Risk paths added by the owner:"]
    return out + (["* %s" % g for g in risk] or ["* none"])


def _globs(names, have, link_check):
    """The folders (two levels deep at most) that held the most changed files, as `a/b/**` globs the playbook does not list yet."""
    count = {}
    for n in names:
        parts = n.split("/")
        if len(parts) < 2 or parts[0] in _SKIP_TOP:
            continue
        g = "/".join(parts[:2] if len(parts) >= 3 else parts[:1]) + "/**"
        if _GLOB_OK.fullmatch(g) and ".." not in g.split("/") and g not in have and not link_check(g):
            count[g] = count.get(g, 0) + 1
    return [g for g, _n in sorted(count.items(), key=lambda kv: (-kv[1], kv[0]))][:MAX_ADD]


def _dl(d) -> str:
    """One diff line as text: the +/-/space marker kept, the rest cleaned (no control characters, markup brackets or backticks) and clipped."""
    if d.startswith(("---", "+++", "@@")):
        return tidy(d, DIFF_LINE_MAX)
    return (d[:1] if d[:1] in "+- " else " ") + tidy(d[1:], DIFF_LINE_MAX - 1)


def propose(cfg, names, link_check=None):
    """None when there is nothing to propose, else {"add": [globs], "risk_paths": [...], "diff": [lines shown], "diff_total": n}. `cfg` is the trusted playbook config (or None)."""
    if link_check is None:
        from ..report import lint
        link_check = lint.LINK.search
    c = json.loads(json.dumps(cfg)) if cfg else pbconfig.defaults()
    have = list((c.get("overrides") or {}).get("risk_paths") or [])
    add = _globs(names or [], set(have), link_check)
    if not add:
        return None
    new_risk = have + add
    try:
        pbconfig._risk_paths(new_risk)
    except Exception:
        return None
    cur_lines, new_lines = render(c, have), render(c, new_risk)
    diff = [d for d in difflib.unified_diff(cur_lines, new_lines, "playbook (current)", "playbook (proposed)", lineterm="", n=1)]
    diff = [_dl(d) for d in diff]
    return {"add": add, "risk_paths": new_risk, "diff": diff[:DIFF_LINES], "diff_total": len(diff)}


def draft_text(name, cr_id, prop, now=None) -> str:
    lines = ["# Draft playbook fix (not trusted)", "", "Project: %s · From: %s failed its tests twice · Written: %s" % (name, cr_id, time.strftime("%Y-%m-%d", time.localtime(now))), "",
             "Nothing here is trusted yet. It only counts after the owner reads it and runs `shipm playbook set --from-draft` and confirms.", "", "## Proposed change", ""]
    lines += ["    " + d for d in prop["diff"]]
    if prop["diff_total"] > len(prop["diff"]):
        lines.append("    (+%d more lines not shown)" % (prop["diff_total"] - len(prop["diff"])))
    lines += ["", "<!-- shipmiracle-proposal %s -->" % json.dumps({"risk_paths": prop["risk_paths"]}, sort_keys=True, ensure_ascii=True, separators=(",", ":"))]
    return "\n".join(lines) + "\n"


def ensure_draft(pd, name, cr_id, prop, now=None) -> str:
    """Write the fix draft + the interview progress file (status draft, fix_cr). -> "written" | "kept" (an interview of the owner is paused or its draft waits) | "none".
    Never touches playbook.json, work.json or the registry; a draft of the owner's own interview that is not applied yet is never overwritten."""
    if not prop:
        return "none"
    st = interview.load(pd)
    if st is not None and not (st["status"] == "done" or (st["status"] == "draft" and st.get("fix_cr"))):
        return "kept"
    data = draft_text(name, cr_id, prop, now).encode("utf-8")
    if len(data) > interview.DRAFT_MAX:
        return "none"
    st = st or interview.blank(name, "short")
    interview._shipmiracle_dir(pd)
    state.atomic_write(interview.draft_path(pd), data, 0o644)
    st.update(status="draft", draft_sha=hashlib.sha256(data).hexdigest(), fix_cr=cr_id, proposal=None, queue=[], question=None)
    interview._save(pd, st)
    return "written"


def for_cr(pd, names):
    """(prop or None) for the project's CURRENT trusted playbook and the changed `names`."""
    try:
        cfg, _trust, _why = pbconfig.load_trusted(pd, store.registry_entry(pd) or {})
    except Exception:
        cfg = None
    return propose(cfg, names)
