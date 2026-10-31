"""The charter of a full-autopilot run (Phase 6 spec section 1): schema, caps, canonical sha256, the first-line parser, the prerequisites
and the one writer `store()` that the owner CLI and (later) the UserPromptSubmit hook share.

A charter lives in the MAIN project's registry entry (`projects.<pid>.autopilot = {"charter": {...}, "sha256": ...}`), written only by
registry.set_autopilot (not in registry.SETTABLE, so `shipm registry set` cannot touch it). The sha256 is over the canonical JSON (sorted
keys, no spaces) of the charter WITHOUT its id; id = "ch-" + sha[:8]. Every decision recomputes it (state.check). Rule of the phase:
models may stop, only rules may go: nothing in this module trusts text that did not come through the owner's CLI or the hook's
verified first prompt line.

Parser: `parse_line(text)` is linear (hand-written scanner, no backtracking regex on user text), looks at the first line only, and every
refusal says why."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import unicodedata

from .. import NotFound, SchemaError, UsageError
from .. import config, events, paths, projects, registry
from . import state as ap_state
from . import visibility

SET_BY = ("panel", "chat", "cli")
GOAL_MAX = 200
SCOPE_MAX_GLOBS, SCOPE_MAX_LEN = 20, 200
BUDGET_MIN, BUDGET_MAX, BUDGET_DEFAULT = 1, 25, 10
TIME_MIN, TIME_MAX, TIME_DEFAULT = 0.25, 8, 3
DEPS_MAX = 10
ENDS_MAX = 5
DAY_MIN, DAY_MAX, DAY_DEFAULT = 1, 10, 4              # option C "Until I disable it": the share of the week one 24 h segment may use
CRS_MIN, CRS_MAX, CRS_DEFAULT = 1, 5, 3               # option C: requests started per segment
CHECKPOINT_H = 24                                     # option C: a segment lasts 24 h, then the owner's typed yes (shipm autopilot checkpoint) opens the next
UNTIL_DISABLED = "disabled"
ADMITTED_MAX = 5
LINE_MAX = 1024                    # bytes, the first prompt line
QUOTED_MAX, BARE_MAX = 400, 100
ALWAYS_EXCLUDED = (".shipmiracle/**", ".claude/**", ".githooks/**", ".git/**", ".github/workflows/**", "**/.env*", ".mcp.json",
                   ".co" "dex/**", ".vscode/tasks.json", ".vscode/settings.json", ".envrc", ".husky/**", "CLAUDE.md", "AGENTS.md")
_KEYS = ("goal", "scope", "budget", "time", "deps", "ends")
_REQUIRED = ("goal", "scope", "ends")
_DEP_RE = re.compile(r"[a-z0-9@/._-]{1,100}")
_CR_RE = re.compile(r"CR-(\d{3,6})")
_SID_RE = re.compile(r"[A-Za-z0-9_-]{1,8}")
_SHA_RE = re.compile(r"[0-9a-f]{64}")
_STORED = {"v", "id", "project", "pid", "goal", "scope", "budget_pct_week", "time_h", "deps", "ends", "set_by", "set_ts", "session8", "prompt_sha",
           "until", "checkpoint_h", "day_pct", "crs_day"}      # the last four exist for option C only (older code refuses them: unknown keys = invalid = not active)
_C_KEYS = ("until", "checkpoint_h", "day_pct", "crs_day")
_CMD_HEAD = re.compile(r"\s*(charter|allow)\s*:\s*", re.I)


class CharterError(UsageError):
    """A refusal whose message says why (the hook prints it as `Charter NOT set: <message>`)."""


# ---------------------------------------------------------------- value normalisers (shared by the CLI, the line parser and validation)

def _isint(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _ctrl(s: str) -> bool:
    return any(unicodedata.category(c).startswith("C") for c in s)


def clean_goal(v) -> str:
    if not isinstance(v, str):
        raise CharterError("goal: expected text")
    g = "".join(c for c in v if not unicodedata.category(c).startswith("C")).strip()
    if not 1 <= len(g) <= GOAL_MAX:
        raise CharterError("goal: 1-%d characters after removing control characters (got %d)" % (GOAL_MAX, len(g)))
    return g


def clean_scope(v) -> list:
    if isinstance(v, str):
        v = [x.strip() for x in v.split(",") if x.strip()]
    if not isinstance(v, list) or not 1 <= len(v) <= SCOPE_MAX_GLOBS:
        raise CharterError("scope: 1-%d globs, comma separated" % SCOPE_MAX_GLOBS)
    out = []
    for g in v:
        if not isinstance(g, str) or not 1 <= len(g) <= SCOPE_MAX_LEN:
            raise CharterError("scope: each glob is 1-%d characters" % SCOPE_MAX_LEN)
        if _ctrl(g) or "\\" in g:
            raise CharterError("scope: no control characters or backslashes in %r" % g[:40])
        if g.startswith(("/", "~")):
            raise CharterError("scope: %r must be relative (no leading '/' or '~')" % g[:40])
        if ".." in g.split("/"):
            raise CharterError("scope: %r must not contain '..'" % g[:40])
        if g not in out:
            out.append(g)
    return out


def clean_budget(v) -> int:
    if isinstance(v, str):
        m = re.fullmatch(r"(\d{1,3})\s*%?", v.strip())
        if not m:
            raise CharterError("budget: expected a whole number of percent, like 10%%, got %r" % v[:20])
        v = int(m.group(1))
    if not _isint(v):
        raise CharterError("budget: expected a whole number of percent")
    if not BUDGET_MIN <= v <= BUDGET_MAX:
        raise CharterError("budget: %d%% is outside %d-%d%% of the week (the cap is %d%%)" % (v, BUDGET_MIN, BUDGET_MAX, BUDGET_MAX))
    return v


def clean_time(v):
    if isinstance(v, str):
        s = v.strip().lower()
        m = re.fullmatch(r"(\d{1,3}(?:\.\d{1,3})?)\s*h?", s)
        m2 = re.fullmatch(r"(\d{1,3})\s*m", s)
        if m2:
            v = int(m2.group(1)) / 60.0
        elif m:
            v = float(m.group(1))
        else:
            raise CharterError("time: expected hours like 3h or 1.5h, or minutes like 90m, got %r" % v[:20])
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise CharterError("time: expected hours")
    q = round(v * 4)
    if abs(v * 4 - q) > 1e-6:
        raise CharterError("time: %g h is not a multiple of 15 minutes" % v)
    if not TIME_MIN <= q / 4 <= TIME_MAX:
        raise CharterError("time: %g h is outside %g-%g h" % (q / 4, TIME_MIN, TIME_MAX))
    return q // 4 if q % 4 == 0 else q / 4


def clean_day(v) -> int:
    if isinstance(v, str):
        m = re.fullmatch(r"(\d{1,3})\s*%?", v.strip())
        if not m:
            raise CharterError("day: expected a whole number of percent of the week, like 4%%, got %r" % v[:20])
        v = int(m.group(1))
    if not _isint(v) or not DAY_MIN <= v <= DAY_MAX:
        raise CharterError("day: %s%% is outside %d-%d%% of the week a day" % (v, DAY_MIN, DAY_MAX))
    return v


def clean_crs(v) -> int:
    if isinstance(v, str):
        if not re.fullmatch(r"\d{1,2}", v.strip()):
            raise CharterError("crs-day: expected a whole number of requests, got %r" % v[:20])
        v = int(v.strip())
    if not _isint(v) or not CRS_MIN <= v <= CRS_MAX:
        raise CharterError("crs-day: %s is outside %d-%d requests a day" % (v, CRS_MIN, CRS_MAX))
    return v


def is_standing(ch) -> bool:
    """True for an option C charter ("Until I disable it")."""
    return isinstance(ch, dict) and ch.get("until") == UNTIL_DISABLED


def clean_deps(v) -> dict:
    if isinstance(v, str):
        s = v.strip()
        v = {"mode": "none"} if s.lower() == "none" else {"mode": "listed", "names": [x.strip() for x in s.split(",") if x.strip()]}
    if not isinstance(v, dict) or v.get("mode") not in ("none", "listed"):
        raise CharterError("deps: expected none or a list of package names")
    if v["mode"] == "none":
        if set(v) != {"mode"}:
            raise CharterError("deps: mode none takes no names")
        return {"mode": "none"}
    names = v.get("names")
    if set(v) != {"mode", "names"} or not isinstance(names, list) or not 1 <= len(names) <= DEPS_MAX:
        raise CharterError("deps: listed needs 1-%d package names" % DEPS_MAX)
    out = []
    for n in names:
        if not isinstance(n, str) or not _DEP_RE.fullmatch(n):
            raise CharterError("deps: %r is not a package name ([a-z0-9@/._-], 1-100 characters)" % str(n)[:40])
        if n not in out:
            out.append(n)
    return {"mode": "listed", "names": out}


def clean_ends(v) -> list:
    if isinstance(v, str):
        v = expand_ends(v)
    if not isinstance(v, list) or not 1 <= len(v) <= ENDS_MAX:
        raise CharterError("ends: 1-%d change request ids" % ENDS_MAX)
    out = []
    for c in v:
        if not isinstance(c, str) or not re.fullmatch(r"CR-\d{3,6}", c):
            raise CharterError("ends: %r is not a change request id like CR-012" % str(c)[:20])
        if c not in out:
            out.append(c)
    return out


def expand_ends(s: str) -> list:
    """'CR-012..CR-014' -> three ids; 'CR-012,CR-020' -> two; at most 5 either way."""
    s = s.strip()
    if ".." in s:
        a, _, b = s.partition("..")
        ma, mb = _CR_RE.fullmatch(a.strip()), _CR_RE.fullmatch(b.strip())
        if not ma or not mb or "," in s:
            raise CharterError("ends: a range looks like CR-012..CR-014")
        lo, hi = int(ma.group(1)), int(mb.group(1))
        if hi < lo:
            raise CharterError("ends: the range runs backwards (%s..%s)" % (a.strip(), b.strip()))
        if hi - lo + 1 > ENDS_MAX:
            raise CharterError("ends: a range covers at most %d change requests (got %d)" % (ENDS_MAX, hi - lo + 1))
        w = len(ma.group(1))
        return ["CR-%0*d" % (w, n) for n in range(lo, hi + 1)]
    parts = [x.strip() for x in s.split(",")]
    if not parts or any(not _CR_RE.fullmatch(x) for x in parts):
        raise CharterError("ends: expected CR-012..CR-014 or CR-012,CR-015")
    if len(parts) > ENDS_MAX:
        raise CharterError("ends: at most %d change requests (got %d)" % (ENDS_MAX, len(parts)))
    return parts


# ---------------------------------------------------------------- schema, canonical form, sha

def canonical(d) -> bytes:
    return json.dumps(d, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def _body(ch) -> dict:
    return {k: v for k, v in ch.items() if k != "id"}


def digest(ch) -> str:
    """sha256 of the canonical JSON of the charter without its id."""
    return hashlib.sha256(canonical(_body(ch))).hexdigest()


def normalize(d) -> dict:
    """The normalised charter body (no id) or CharterError. Keys: v, project, pid, goal, scope, budget_pct_week, time_h, deps, ends,
    set_by, set_ts and, for set_by chat only, session8 and prompt_sha."""
    if not isinstance(d, dict):
        raise CharterError("charter: expected an object")
    extra = set(d) - _STORED
    if extra:
        raise CharterError("charter: unknown keys %s" % ", ".join(sorted(map(str, extra))))
    if d.get("v") != 1 or not _isint(d.get("v")):
        raise CharterError("charter: v must be 1")
    pid = d.get("pid")
    if not isinstance(pid, str) or not re.fullmatch(r"[0-9a-f]{12}", pid):
        raise CharterError("charter: pid must be a project id")
    name = d.get("project")
    if not isinstance(name, str) or not 1 <= len(name) <= 100 or _ctrl(name):
        raise CharterError("charter: project must be a name")
    if d.get("set_by") not in SET_BY:
        raise CharterError("charter: set_by must be panel, chat or cli")
    ts = d.get("set_ts")
    if not _isint(ts) or ts < 0:
        raise CharterError("charter: set_ts must be a non-negative integer")
    standing = "until" in d
    if standing:
        if d["until"] != UNTIL_DISABLED:
            raise CharterError("charter: until can only be 'disabled'")
        if d["set_by"] == "chat":
            raise CharterError("a charter that runs until you disable it is set in the panel or a terminal only")
        if d.get("time_h") is not None:
            raise CharterError("charter: a charter that runs until you disable it has no time limit (time_h is null)")
        if d.get("checkpoint_h", CHECKPOINT_H) != CHECKPOINT_H:
            raise CharterError("charter: checkpoint_h is fixed at %d" % CHECKPOINT_H)
    elif any(k in d for k in _C_KEYS):
        raise CharterError("charter: day_pct, crs_day and checkpoint_h belong to 'until disabled' charters only")
    out = {"v": 1, "project": name, "pid": pid, "goal": clean_goal(d.get("goal")), "scope": clean_scope(d.get("scope")),
           "budget_pct_week": clean_budget(d.get("budget_pct_week", BUDGET_DEFAULT)),
           "time_h": None if standing else clean_time(d.get("time_h", TIME_DEFAULT)),
           "deps": clean_deps(d.get("deps", {"mode": "none"})), "ends": clean_ends(d.get("ends")), "set_by": d["set_by"], "set_ts": ts}
    if standing:
        day = clean_day(d.get("day_pct", DAY_DEFAULT))
        if day > out["budget_pct_week"]:
            raise CharterError("day: %d%% a day is more than the %d%% a week cap" % (day, out["budget_pct_week"]))
        out.update(until=UNTIL_DISABLED, checkpoint_h=CHECKPOINT_H, day_pct=day, crs_day=clean_crs(d.get("crs_day", CRS_DEFAULT)))
    if d["set_by"] == "chat":
        s8, psha = d.get("session8"), d.get("prompt_sha")
        if not isinstance(s8, str) or not _SID_RE.fullmatch(s8) or not isinstance(psha, str) or not _SHA_RE.fullmatch(psha):
            raise CharterError("charter: a chat charter records session8 and prompt_sha")
        out.update(session8=s8, prompt_sha=psha)
    elif "session8" in d or "prompt_sha" in d:
        raise CharterError("charter: session8 and prompt_sha belong to chat charters only")
    return out


def build(fields, project, pid, set_by, set_ts, session8=None, prompt_sha=None) -> dict:
    """fields = {goal, scope, budget?, time?, deps?, ends} (the parse_line / CLI output) -> the full charter with its id."""
    d = {"v": 1, "project": project, "pid": pid, "goal": fields.get("goal"), "scope": fields.get("scope"),
         "budget_pct_week": fields.get("budget", BUDGET_DEFAULT), "time_h": fields.get("time", TIME_DEFAULT),
         "deps": fields.get("deps", {"mode": "none"}), "ends": fields.get("ends"), "set_by": set_by, "set_ts": int(set_ts)}
    if fields.get("until"):
        d.update(until=fields["until"], time_h=None, day_pct=fields.get("day", DAY_DEFAULT), crs_day=fields.get("crs_day", CRS_DEFAULT))
    if set_by == "chat":
        d.update(session8=session8, prompt_sha=prompt_sha)
    body = normalize(d)
    return dict(body, id="ch-" + digest(body)[:8])


def record_of(charter) -> dict:
    return {"charter": charter, "sha256": digest(charter)}


def validate_record(rec) -> dict:
    """Check a stored {"charter", "sha256"}: well formed, already in normal form, sha256 equals the recomputed one, id equals ch-sha[:8].
    Returns the charter; raises CharterError (a tampered or hand-edited registry entry fails here)."""
    if (not isinstance(rec, dict) or not {"charter", "sha256"} <= set(rec) or set(rec) - {"charter", "sha256", "admitted"}
            or not isinstance(rec["charter"], dict) or not isinstance(rec["sha256"], str)):
        raise CharterError("autopilot record: expected {charter, sha256}")
    if "admitted" in rec:
        clean_admitted(rec["admitted"])
    ch = rec["charter"]
    body = normalize(_body(ch))
    if body != _body(ch):
        raise CharterError("autopilot record: charter is not in normal form")
    sha = digest(body)
    if rec["sha256"] != sha:
        raise CharterError("autopilot record: sha256 does not match the charter")
    if ch.get("id") != "ch-" + sha[:8]:
        raise CharterError("autopilot record: id does not match the sha256")
    return ch


def clean_admitted(v) -> list:
    """The owner's admissions beside a standing charter (outside its sha): at most ADMITTED_MAX entries {id, title_sha (full sha256 of the title), ts}."""
    if not isinstance(v, list) or len(v) > ADMITTED_MAX:
        raise CharterError("admitted: at most %d entries" % ADMITTED_MAX)
    out = []
    for e in v:
        if (not isinstance(e, dict) or set(e) != {"id", "title_sha", "ts"} or not isinstance(e["id"], str) or not re.fullmatch(r"CR-\d{3,6}", e["id"])
                or not isinstance(e["title_sha"], str) or not _SHA_RE.fullmatch(e["title_sha"]) or not _isint(e["ts"]) or e["ts"] < 0):
            raise CharterError("admitted: each entry is {id, title_sha (full sha256), ts}")
        out.append({"id": e["id"], "title_sha": e["title_sha"], "ts": e["ts"]})
    return out


# ---------------------------------------------------------------- the first-line parser

def _scan(line: str, i: int):
    """Scanner for `key=value; key="quoted value" ...` from index i. Linear: every loop advances i. Returns {key: raw value}."""
    n, out = len(line), {}
    while True:
        while i < n and (line[i] == ";" or line[i] in " \t"):
            i += 1
        if i >= n:
            return out
        j = i
        while j < n and "a" <= line[j] <= "z" and j - i <= 8:
            j += 1
        key = line[i:j]
        if not 1 <= len(key) <= 8:
            raise CharterError("expected a key like goal= at position %d (keys are 1-8 lowercase letters)" % i)
        if j >= n or line[j] != "=":
            raise CharterError("key %r needs '=' right after it" % key)
        if key not in _KEYS:
            raise CharterError("unknown key %r (keys: %s)" % (key, ", ".join(_KEYS)))
        if key in out:
            raise CharterError("key %r appears twice" % key)
        j += 1
        if j < n and line[j] == '"':
            k = line.find('"', j + 1)
            if k < 0:
                raise CharterError("%s: the quote is never closed" % key)
            if k - j - 1 > QUOTED_MAX:
                raise CharterError("%s: a quoted value is at most %d characters" % (key, QUOTED_MAX))
            out[key] = line[j + 1:k]
            i = k + 1
            if i < n and line[i] not in " \t;":
                raise CharterError("%s: unexpected text right after the closing quote" % key)
        else:
            k = j
            while k < n and line[k] != ";" and line[k] not in " \t" and k - j <= BARE_MAX:
                k += 1
            if k - j > BARE_MAX:
                raise CharterError("%s: an unquoted value is at most %d characters (use quotes)" % (key, BARE_MAX))
            if k == j:
                raise CharterError("%s: no value after '='" % key)
            out[key] = line[j:k]
            i = k


def parse_line(text):
    """Parse the FIRST line of a prompt. Returns (fields, error):
      (None, None)   not a charter:/allow: line at all (nothing to say)
      (None, "why")  a charter:/allow: line that is refused; nothing is stored
      ({"cmd": "off"|"show"}, None)
      ({"cmd": "allow", "id": "H-1a2b3c"}, None)
      ({"cmd": "set", goal, scope, budget, time, deps, ends}, None)   normalised values, defaults filled
    Linear in the first KB: a 200 KB input costs one slice."""
    if not isinstance(text, str):
        return None, None
    first = re.split(r"[\r\n]", text[:LINE_MAX * 2 + 64], 1)[0]
    m = _CMD_HEAD.match(first[:64]) if first else None
    if not m:
        return None, None
    if len(first.encode("utf-8", "replace")) > LINE_MAX:
        return None, "the line is longer than %d bytes" % LINE_MAX
    head, rest = m.group(1).lower(), first[m.end():].strip()
    try:
        if head == "allow":
            if not re.fullmatch(r"H-[0-9a-f]{6}", rest):
                raise CharterError("allow: expected a stop id like H-1a2b3c")
            return {"cmd": "allow", "id": rest}, None
        low = rest.lower()
        if low in ("off", "show"):
            return {"cmd": low}, None
        if not rest:
            raise CharterError("charter: expected goal=..., off or show")
        if re.search(r"(?:^|[;\s])(until|day|crs-?day|checkpoint)\s*=", first[m.end():], re.I):
            raise CharterError("a charter that runs until you disable it is set in the panel or a terminal only, never from the chat line")
        raw = _scan(first, m.end())
        missing = [k for k in _REQUIRED if k not in raw]
        if missing:
            raise CharterError("missing %s (a charter needs goal, scope and ends)" % ", ".join(missing))
        out = {"cmd": "set", "goal": clean_goal(raw["goal"]), "scope": clean_scope(raw["scope"]), "ends": clean_ends(raw["ends"])}
        b = raw.get("budget", "%d%%" % BUDGET_DEFAULT)
        if not re.fullmatch(r"\d{1,2}%", b):
            raise CharterError("budget: expected 1-2 digits and %%, like 10%%, got %r" % b[:20])
        out["budget"] = clean_budget(b)
        t = raw.get("time", "%gh" % TIME_DEFAULT)
        if not re.fullmatch(r"\d+(\.\d+)?h|\d{1,3}m", t):
            raise CharterError("time: expected hours like 3h or 1.5h, or minutes like 90m, got %r" % t[:20])
        out["time"] = clean_time(t)
        out["deps"] = clean_deps(raw.get("deps", "none"))
        return out, None
    except CharterError as e:
        return None, str(e)


# ---------------------------------------------------------------- text for the owner

def _ends_text(ends) -> str:
    nums = [int(c[3:]) for c in ends]
    if len(ends) > 1 and nums == list(range(nums[0], nums[0] + len(nums))):
        return "%s..%s" % (ends[0], ends[-1])
    return ",".join(ends)


def describe(ch) -> str:
    deps = "none" if ch["deps"]["mode"] == "none" else "listed: " + ", ".join(ch["deps"]["names"])
    if is_standing(ch):
        return 'goal "%s" · scope %s · UNTIL YOU DISABLE IT: %d%% of the week a day, %d%% a week, up to %d requests a day, a yes from you every %d h · deps %s · ends %s' % (
            ch["goal"], ", ".join(ch["scope"]), ch["day_pct"], ch["budget_pct_week"], ch["crs_day"], ch["checkpoint_h"], deps, _ends_text(ch["ends"]))
    return 'goal "%s" · scope %s · budget %d%% of the week · time %g h after start · deps %s · ends %s' % (
        ch["goal"], ", ".join(ch["scope"]), ch["budget_pct_week"], ch["time_h"], deps, _ends_text(ch["ends"]))


def echo(ch, week_pct=None) -> str:
    """The line the owner sees after a set (spec section 1): the charter, the week now and where it stops."""
    now_txt = ""
    if week_pct is not None:
        now_txt = " (now %g%%, stops at %g%%)" % (round(week_pct, 1), round(week_pct + ch["budget_pct_week"], 1))
    deps = "none" if ch["deps"]["mode"] == "none" else "listed: " + ", ".join(ch["deps"]["names"])
    if is_standing(ch):
        return 'Charter %s set (UNTIL YOU DISABLE IT): goal "%s" · scope %s · %d%% of the week a day, %d%% a week%s, up to %d requests a day · deps %s · ends %s. ' \
               'Start it with "Start autopilot" (panel) or: shipm autopilot start --project %s' % (
                   ch["id"], ch["goal"], ", ".join(ch["scope"]), ch["day_pct"], ch["budget_pct_week"], now_txt, ch["crs_day"], deps, _ends_text(ch["ends"]), ch["project"])
    return 'Charter %s set: goal "%s" · scope %s · budget %d%% of the week%s · time %g h after start · deps %s · ends %s. ' \
           'Start it with "Start autopilot" (panel) or: shipm autopilot start --project %s' % (
               ch["id"], ch["goal"], ", ".join(ch["scope"]), ch["budget_pct_week"], now_txt, ch["time_h"], deps, _ends_text(ch["ends"]), ch["project"])


# ---------------------------------------------------------------- prerequisites

def _remotes(pd):
    try:
        from . import worktree as W
        return W.remotes(pd)                                   # every fetch and push URL of every remote (M3), not only remote.<n>.url
    except Exception:
        return []


def prereqs(project_dir, at=None, base=None, standing=False):
    """[(ok, text)] for the level prerequisites of a full run (spec section 1). Pure reads, no network: the switch, strict level,
    hooks.dispatcher=v1, gate.engine=playbook, a trusted software playbook with autopilot=full, every git remote cached as private
    (or no remote), plan.json fresh with rate_limits.seven_day. The checks of the session itself (branch auto/CR-n, active CR in ends)
    are the hook's."""
    from ..playbook import config as pbconfig, gate, store
    at = ap_state.now() if at is None else at
    pd = os.path.realpath(str(project_dir))
    rows = []

    def row(ok, good, bad):
        rows.append((bool(ok), good if ok else bad))
    row(config.get("autopilot.full.enabled") is True, "switch autopilot.full.enabled is on",
        "switch autopilot.full.enabled is off: run `shipm switch autopilot.full.enabled on`")
    if standing:
        row(config.get("autopilot.standing.enabled") is True, "switch autopilot.standing.enabled is on",
            "switch autopilot.standing.enabled is off: run `shipm switch autopilot.standing.enabled on` (it needs the sandbox test record, see docs/owner-steps/p6-autopilot.sh)")
    lv = gate.flow_level(pd)
    row(lv == "strict", "flow level is strict", "flow level is %s: full autopilot needs strict" % lv)
    disp = config.get("hooks.dispatcher")
    row(disp == "v1", "hooks.dispatcher is v1", "hooks.dispatcher is %s: run `shipm switch hooks.dispatcher v1`" % disp)
    eng = config.get("gate.engine")
    row(eng == "playbook", "gate.engine is playbook", "gate.engine is %s: run `shipm switch gate.engine playbook`" % eng)
    entry = store.registry_entry(pd) or {}
    cfg, trust, _why = pbconfig.load_trusted(pd, entry)
    if cfg is None:
        row(False, "", "the project has no playbook (shipm playbook set type software)")
    elif trust != pbconfig.TRUSTED:
        row(False, "", "the playbook is %s, not trusted: run `shipm playbook set autopilot full`" % trust)
    elif cfg["type"] != "software":
        row(False, "", "the playbook type is %s: full autopilot is for software projects only" % cfg["type"])
    else:
        row(cfg["autopilot"] == "full", "playbook is trusted, software, autopilot full",
            "playbook autopilot is %s: run `shipm playbook set autopilot full`" % cfg["autopilot"])
    remotes = _remotes(pd)
    if not remotes:
        row(True, "no git remote", "")
    else:
        bad = [n for n, u in remotes if not visibility.is_private(u, at, base)]
        row(not bad, "every remote is cached private", "remote %s is not cached as private (the owner's `shipm autopilot start` asks GitHub)" % ", ".join(bad))
    plan = ap_state.plan_reading(at, base)
    row(plan is not None and plan["fresh"], "plan.json is fresh with the weekly percentage",
        "plan.json is missing, stale (over 15 minutes) or lacks rate_limits.seven_day: the budget cannot be measured")
    return rows


def prereq_failures(rows):
    return [t for ok, t in rows if not ok]


def refresh_visibility(project_dir, runner=None) -> None:
    """Owner `start` only: ask GitHub (gh api, 5 s) about each remote. Never in tests (no network); a failure leaves the cache as it was."""
    if os.environ.get("SHIPMIRACLE_TEST") == "1" and runner is None:
        return
    for _n, url in _remotes(os.path.realpath(str(project_dir))):
        visibility.refresh(url, runner)


# ---------------------------------------------------------------- store / clear (the writers)

def _project(pid):
    for p in projects.list_projects():
        if p.id == pid:
            return p
    raise NotFound("no project with id %s" % pid)


def check_ends(project_dir, ends) -> None:
    """Every id in `ends` must already be an open or queued change request in the main log."""
    from ..playbook import store
    work = store.load(project_dir)
    status = {c["id"]: c.get("status") for c in work.get("crs", [])}
    bad = [c for c in ends if status.get(c) not in ("open", "queued")]
    if bad:
        raise CharterError("ends: %s %s not an open or queued change request in this project (shipm cr open ...)" % (
            ", ".join(bad), "is" if len(bad) == 1 else "are"))


def other_standing(pid):
    """The id of ANOTHER project whose registry entry holds an "until disabled" charter, else None. One standing run per machine: the weekly
    budget is account-wide, two standing runs would each count the other's spend."""
    try:
        reg = registry.load()
    except Exception:
        return None
    for q, e in (reg.get("projects") or {}).items():
        if q == pid:
            continue
        rec = registry.autopilot_of(e)
        if rec is not None and is_standing(rec.get("charter")):
            return q
    return None


def store_charter(pid, fields, origin, at=None, base=None, prereq_check=True) -> dict:
    """The owner's writer (CLI and panel; origin cli|panel): ALWAYS require_owner, refused inside a chat. origin "chat" is rejected here:
    only store_from_prompt may produce a chat charter. Steps: build + validate (caps), ends exist, prerequisites, no run in progress,
    state file `set`, registry entry, event autopilot.charter_set. Nothing is stored when any step refuses.
    Returns {"charter", "sha256", "echo"}."""
    if origin == "chat":
        raise CharterError("a chat charter is stored only from the owner's prompt (store_from_prompt)")
    if origin not in ("cli", "panel"):
        raise UsageError("origin must be cli or panel")
    paths.require_owner("shipm autopilot charter set")
    return _store(pid, fields, origin, None, None, at, base, prereq_check, True)


store = store_charter           # the name used in the spec: store(pid, charter, origin)


def store_from_prompt(pid, raw_prompt, session_id, at=None, base=None) -> dict:
    """The hook's only entry (UserPromptSubmit, after it verified the prompt is the owner's own). It re-parses the raw prompt itself,
    recomputes prompt_sha (sha256 of the prompt text) and session8 (first 8 safe characters of the session id): nothing the caller
    passes can set these. Raises CharterError (message = reason) when the first line is not a valid `charter: goal=...` line."""
    fields, err = parse_line(raw_prompt)
    if err:
        raise CharterError(err)
    if not fields or fields.get("cmd") != "set":
        raise CharterError("the prompt is not a charter set line")
    sid = re.sub(r"[^A-Za-z0-9_-]", "", str(session_id or ""))[:8]
    if not sid:
        raise CharterError("no session id: a chat charter records its session")
    psha = hashlib.sha256(raw_prompt.encode("utf-8", "replace")).hexdigest()
    return _store(pid, {k: v for k, v in fields.items() if k != "cmd"}, "chat", sid, psha, at, base, True, False)


def _store(pid, fields, origin, session8, prompt_sha, at, base, prereq_check, owner) -> dict:
    at = ap_state.now() if at is None else at
    p = _project(pid)
    ch = build(fields, p.name, pid, origin, int(at), session8, prompt_sha)
    if is_standing(ch) and other_standing(pid) is not None:
        raise CharterError("only one project can run until you disable it: another project already has such a charter (stop it first)")
    check_ends(p.path, ch["ends"])
    plan = ap_state.plan_reading(at, base)
    if prereq_check:
        bad = prereq_failures(prereqs(p.path, at, base, standing=is_standing(ch)))
        if bad:
            raise CharterError("prerequisites not met: " + "; ".join(bad))
    rec = record_of(ch)
    try:
        ap_state.create(pid, rec["sha256"], int(at), base)       # refuses a running/paused run before anything else is written
    except CharterError:
        raise
    except UsageError as e:
        raise CharterError(str(e))
    try:
        registry.set_autopilot(pid, rec, owner=owner)
    except BaseException:
        ap_state.delete(pid, base)
        raise
    events.emit("autopilot.charter_set", {"sha8": rec["sha256"][:8], "set_by": origin}, project=pid, src="shipmiracle")
    return {"charter": ch, "sha256": rec["sha256"], "echo": echo(ch, plan["pct"] if plan and plan["fresh"] else None)}


def clear(pid, at=None, base=None, _owner=True) -> dict:
    """Back to guided (owner only, always require_owner): ends a set/running/paused run as ended:owner and removes the charter."""
    if _owner:
        paths.require_owner("shipm autopilot charter clear")
    at = ap_state.now() if at is None else at
    try:
        st = ap_state.read(pid, base) if ap_state.path(pid, base).exists() else None
    except SchemaError:                           # a damaged or edited state file never blocks the kill switch: it is removed
        ap_state.delete(pid, base)
        st = {"state": "damaged"}
    had_charter = registry.autopilot_of(registry.entry(pid)) is not None
    if st is not None and st["state"] not in ("ended", "damaged"):
        ap_state.end(pid, "owner", at, base)
    registry.set_autopilot(pid, None, owner=_owner)
    if st is not None or had_charter:
        events.emit("autopilot.charter_cleared", {"set_by": "cli" if _owner else "chat", "was": st["state"] if st else "none"}, project=pid, src="shipmiracle")
    return {"was": st["state"] if st else None, "had_charter": had_charter}


def clear_from_prompt(pid, raw_prompt, at=None, base=None) -> dict:
    """The hook's `charter: off`: re-parses the raw prompt; only a valid off line clears."""
    fields, err = parse_line(raw_prompt)
    if err or not fields or fields.get("cmd") != "off":
        raise CharterError(err or "the prompt is not `charter: off`")
    return clear(pid, at, base, _owner=False)
