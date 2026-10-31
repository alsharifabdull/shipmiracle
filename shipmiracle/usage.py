"""Promotion counter (CHECKLIST G8): how often project-only agents and skills are used, and which borrowed items appear in several projects.
Feeds `bin/promote-agent --candidates` and the `bin/daily` line. Read-only: it never edits a project; the OWNER decides every promotion.

Counts come from the Claude transcripts (<home>/.claude/projects/*/*.jsonl): Agent/Task tool calls carry input.subagent_type, Skill tool calls
carry input.skill. Scanning is incremental (per-file counts cached by mtime+size in <state>/usage-counts.json, version USAGE_CACHE_V), time-budgeted
(an unfinished scan returns what it has with partial=True) and safe against hostile files: regular files only, opened O_NOFOLLOW|O_NONBLOCK, lines
capped, nothing is parsed as JSON (a regex over bytes), names capped.
Borrowed items are read from <project>/.agents/borrowed.json (entries {id, kind, dest, source{..., sha256}, ...}); a damaged, huge, symlinked or FIFO
record is ignored. Only the owner's own projects folder is read.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import sys
import time
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional

from . import paths

# The promotion thresholds live HERE and nowhere else (bin/promote-agent and bin/daily read them from this module).
PROMOTE_CALLS = 10      # called this many times ...
PROMOTE_PROJECTS = 2    # ... or present in this many projects
USAGE_CACHE_V = 2       # bump when the counted patterns change (old per-file counts are then ignored)
DEFAULT_BUDGET_S = 20.0
MAX_LINE = 16 << 20     # a longer transcript line is skipped (its tail up to the next newline is dropped)
MAX_NAMES_PER_FILE = 200
MAX_NAME = 80
MAX_RECORD = 256 * 1024
MAX_ENTRIES = 500
BUILTIN_AGENTS = {"general-purpose", "Explore", "Plan", "claude-code-guide", "statusline-setup"}

_AGENT_RE = re.compile(rb'"subagent_type"\s*:\s*"([^"\\]{1,%d})"' % MAX_NAME)
_SKILL_HEAD_RE = re.compile(rb'"name"\s*:\s*"Skill"\s*,\s*"input"\s*:\s*\{')
_SKILL_NAME_RE = re.compile(rb'"skill"\s*:\s*"([^"\\]{1,%d})"' % MAX_NAME)
_NAME_OK = re.compile(r"[A-Za-z0-9][\w.:-]*\Z")


_KEYWORDS = re.compile(r"(?i)(f)(ail)|(w)(arn)")


def esc(s, limit: int = 80) -> str:
    """Printable, single-line text: control, format (bidi, zero-width) and separator characters become \\uXXXX; long text is cut. The words fail/warn are
    broken ("F*AIL") so a data string can never look like a status row to the log greps in bin/daily (Health counts ' FAIL ' and ' warn ')."""
    out = []
    for ch in str(s)[:limit]:
        cat = unicodedata.category(ch)
        if cat[0] == "C" or cat in ("Zl", "Zp") or (cat == "Zs" and ch != " ") or not ch.isprintable():
            out.append("\\u%04x" % ord(ch) if ord(ch) <= 0xFFFF else "\\U%08x" % ord(ch))
        else:
            out.append(ch)
    text = _KEYWORDS.sub(lambda m: (m.group(1) or m.group(3)) + "*" + (m.group(2) or m.group(4)), "".join(out))
    return text + ("..." if len(str(s)) > limit else "")


# ------------------------------------------------------------------ safe file access
def _open_regular(path, nonblock_flags=0):
    """fd of a regular file opened without following a symlink and without blocking on a FIFO; None for anything else."""
    try:
        fd = os.open(str(path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0))
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            os.close(fd)
            return None
    except OSError:
        os.close(fd)
        return None
    return fd


def _read_small(path, cap: int = MAX_RECORD) -> Optional[bytes]:
    fd = _open_regular(path)
    if fd is None:
        return None
    try:
        if os.fstat(fd).st_size > cap:
            return None
        data = b""
        while len(data) <= cap:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            data += chunk
        return data if len(data) <= cap else None
    except OSError:
        return None
    finally:
        os.close(fd)


# ------------------------------------------------------------------ transcript scan
def _scan_line(line: bytes, agents: Counter, skills: Counter) -> None:
    if b'"subagent_type"' in line:
        for m in _AGENT_RE.finditer(line):
            agents[m.group(1).decode("utf-8", "replace")] += 1
    if b'"Skill"' in line:
        for h in _SKILL_HEAD_RE.finditer(line):
            m = _SKILL_NAME_RE.match(line, h.end()) or _SKILL_NAME_RE.search(line, h.end(), h.end() + 400)
            if m:
                skills[m.group(1).decode("utf-8", "replace")] += 1


def _scan_file(full: str, deadline: float, resume=None):
    """Scan one transcript. Returns ("done", agents, skills), ("part", offset, sha256-hex of bytes [0:offset], agents, skills) when the time ran out
    at a line boundary (the next run resumes there), or None (not a plain readable file / unusable). `resume` = (offset, hex, agents, skills) from a
    previous partial run; it is used only when the first `offset` bytes still hash to the same value."""
    fd = _open_regular(full)
    if fd is None:
        return None
    agents, skills = Counter(), Counter()
    h = hashlib.sha256()
    off = 0
    try:
        if resume:
            roff, rhex, ra, rs = resume
            if os.fstat(fd).st_size >= roff:
                left = roff
                while left > 0:
                    if time.time() > deadline:
                        return None
                    c = os.read(fd, min(1 << 20, left))
                    if not c:
                        break
                    h.update(c)
                    left -= len(c)
                if left == 0 and h.hexdigest() == rhex:
                    off = roff
                    agents.update(ra)
                    skills.update(rs)
                else:
                    h = hashlib.sha256()
                    os.lseek(fd, 0, os.SEEK_SET)
            else:
                os.lseek(fd, 0, os.SEEK_SET)
        buf = b""
        skipping = False
        resumable = True
        while True:
            if time.time() > deadline:
                return ("part", off, h.hexdigest(), agents, skills) if resumable and not skipping else None
            try:
                chunk = os.read(fd, 1 << 20)
            except OSError:
                return None
            if not chunk:
                break
            data = buf + chunk
            parts = data.split(b"\n")      # one split per chunk: linear however short the lines are
            buf = parts.pop()
            if skipping:
                if not parts:
                    buf = b""
                    continue
                parts.pop(0)                 # the tail of a line that was too long
                skipping = False
            for ln in parts:
                _scan_line(ln, agents, skills)
            if len(buf) > MAX_LINE:
                buf, skipping, resumable = b"", True, False
            if resumable and not skipping:
                done = data[:len(data) - len(buf)]
                h.update(done)
                off += len(done)
        if buf and not skipping:
            _scan_line(buf, agents, skills)
    finally:
        os.close(fd)
    return ("done", agents, skills)


def _cap(c: Counter) -> dict:
    return dict(c.most_common(MAX_NAMES_PER_FILE))


def scan_transcripts(projects_dir=None, budget_s: float = DEFAULT_BUDGET_S, cache_path=None, nested: bool = False) -> dict:
    """{"agents": Counter, "skills": Counter, "partial": bool, "read": files read this run, "files": files seen, "cached": files served from the cache}.
    Files that changed (mtime or size) are re-read; the rest comes from the cache. When the budget runs out the result is partial (counts may be low);
    the files finished so far are cached, and a file interrupted inside is cached as (byte offset, hash of the bytes before it, counts so far), so the next
    run resumes there. Only <projects>/<project>/*.jsonl are read, as the old counter did; nested.. subagent transcripts (<session>/subagents/) are read only
    with nested=True (they are separate sessions, but a double count with the parent is not ruled out)."""
    root = Path(projects_dir) if projects_dir else paths.home() / ".claude" / "projects"
    res = {"agents": Counter(), "skills": Counter(), "partial": False, "read": 0, "files": 0, "cached": 0}
    if root.is_symlink() or not root.is_dir():
        return res
    cache_path = Path(cache_path) if cache_path else paths.state_dir() / "usage-counts.json"
    cache: dict = {}
    pcache: dict = {}
    raw = _read_small(cache_path, 8 << 20)
    if raw:
        try:
            d = json.loads(raw.decode("utf-8", "replace"))
            if isinstance(d, dict) and d.get("v") == USAGE_CACHE_V and isinstance(d.get("files"), dict):
                cache = d["files"]
                if isinstance(d.get("part"), dict):
                    pcache = d["part"]
        except (ValueError, RecursionError):
            cache = {}
    t0 = time.time()
    deadline = t0 + max(0.0, budget_s)
    seen, pseen, dirty = {}, {}, False
    for dp, dns, fns in os.walk(str(root), followlinks=False):
        dns.sort()
        if not nested and dp != str(root):
            dns[:] = []
        if not nested and dp == str(root):
            continue
        for fn in sorted(fns):
            if not fn.endswith(".jsonl"):
                continue
            full = os.path.join(dp, fn)
            try:
                st = os.lstat(full)
            except OSError:
                continue
            if not stat.S_ISREG(st.st_mode):
                continue
            res["files"] += 1
            key = os.path.relpath(full, str(root))
            c = cache.get(key)
            if (isinstance(c, list) and len(c) == 4 and c[0] == int(st.st_mtime) and c[1] == st.st_size
                    and isinstance(c[2], dict) and isinstance(c[3], dict)):
                a, s = c[2], c[3]
                seen[key] = c
                res["cached"] += 1
            else:
                if time.time() > deadline:
                    res["partial"] = True
                    continue
                pr = pcache.get(key)
                resume = None
                if isinstance(pr, list) and len(pr) == 4 and isinstance(pr[0], int) and isinstance(pr[1], str) and isinstance(pr[2], dict) and isinstance(pr[3], dict):
                    resume = tuple(pr)
                got = _scan_file(full, deadline, resume)
                if got is None:
                    res["partial"] = res["partial"] or time.time() > deadline
                    continue
                if got[0] == "part":
                    pseen[key] = [got[1], got[2], _cap(got[3]), _cap(got[4])]
                    res["partial"] = True
                    dirty = True
                    continue
                a, s = _cap(got[1]), _cap(got[2])
                seen[key] = [int(st.st_mtime), st.st_size, a, s]
                res["read"] += 1
                dirty = True
            for k, v in a.items():
                if isinstance(v, int):
                    res["agents"][k] += v
            for k, v in s.items():
                if isinstance(v, int):
                    res["skills"][k] += v
    if dirty or set(seen) != set(cache) or set(pseen) != set(pcache):
        try:
            _write_cache(cache_path, {"v": USAGE_CACHE_V, "files": seen, "part": pseen})
        except OSError:
            pass
    return res


def _write_cache(path: Path, obj: dict) -> None:
    import tempfile
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix="." + path.name + ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(obj) + "\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, str(path))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ------------------------------------------------------------------ borrowed records
def _entry_name(dest: str, kind: str) -> Optional[str]:
    parts = [p for p in re.split(r"[\\/]+", dest) if p]
    if not parts or ".." in parts or dest.startswith(("/", "\\")):
        return None     # a record may only name a place inside its own project
    last = parts[-1]
    if last.lower() == "skill.md" and len(parts) > 1:
        name = parts[-2]
    else:
        name = last[:-3] if last.lower().endswith(".md") else last
    return name if _NAME_OK.match(name) and len(name) <= MAX_NAME else None


def read_borrowed(project_dir) -> List[dict]:
    """Normalised entries [{"id", "kind", "name", "sha"}] of <project>/.agents/borrowed.json; [] when absent or damaged. Never raises."""
    p = Path(project_dir) / ".agents" / "borrowed.json"
    raw = _read_small(p)
    if raw is None:
        return []
    try:
        d = json.loads(raw.decode("utf-8", "replace"))
    except (ValueError, RecursionError):
        return []
    items = None
    if isinstance(d, list):
        items = d
    elif isinstance(d, dict):
        for k in ("entries", "items", "borrowed"):
            if isinstance(d.get(k), list):
                items = d[k]
                break
        if items is None and all(isinstance(v, dict) for v in d.values()):
            items = [dict(v, id=v.get("id", k)) for k, v in d.items()]
    out = []
    for e in (items or [])[:MAX_ENTRIES]:
        if not isinstance(e, dict):
            continue
        eid = e.get("id") if isinstance(e.get("id"), str) else ""
        src = e.get("source") if isinstance(e.get("source"), dict) else {}
        sha = src.get("sha256") if isinstance(src.get("sha256"), str) else ""
        kind = e.get("kind") if e.get("kind") in ("agent", "skill") else None
        if kind is None:
            m = re.match(r"[\w.-]+:(agent|skill):", eid)
            kind = m.group(1) if m else None
        dest = e.get("dest") if isinstance(e.get("dest"), str) else ""
        name = _entry_name(dest[:300], kind or "") if dest else None
        if not kind or not name or not (eid or sha):
            continue
        out.append({"id": eid[:200] or "sha256:" + sha[:64], "kind": kind, "name": name, "sha": sha[:64], "dest": dest[:300]})
    return out


# ------------------------------------------------------------------ candidates
def _projects(dev: Path, ws: Path) -> List[Path]:
    """The owner's own projects: real folders directly inside the projects folder (no symlinks), except the workspace."""
    out = []
    try:
        names = sorted(os.listdir(str(dev)))
    except OSError:
        return out
    try:
        ws_real = os.path.realpath(str(ws))
    except OSError:
        ws_real = ""
    for n in names:
        p = dev / n
        try:
            if p.is_symlink() or not p.is_dir():
                continue
        except OSError:
            continue
        if n == "AI-Workspace" or os.path.realpath(str(p)) == ws_real:
            continue
        out.append(p)
    return out


def _md_names(d: Path) -> List[str]:
    try:
        if d.is_symlink() or not d.is_dir():
            return []
        return sorted(f[:-3] for f in os.listdir(str(d)) if f.endswith(".md") and _NAME_OK.match(f[:-3]) and (d / f).is_file() and not (d / f).is_symlink())
    except OSError:
        return []


def _skill_dirs(d: Path) -> List[str]:
    try:
        if d.is_symlink() or not d.is_dir():
            return []
        return sorted(f for f in os.listdir(str(d)) if _NAME_OK.match(f) and (d / f).is_dir() and not (d / f).is_symlink())
    except OSError:
        return []


def candidates(ws=None, dev=None, projects_dir=None, budget_s: float = DEFAULT_BUDGET_S, cache_path=None) -> dict:
    """{"rows": [...], "partial": bool, "borrowed": int}. A row: {"name", "kind", "projects": [..], "calls": int, "borrowed_from": id|None, "also": [names],
    "qualifies": bool, "why": str}. Project-only agents (.claude/agents) and skills (.agents/skills, real folders) plus every borrowed item; borrowed items are
    grouped by source id (or source sha), so one source renamed in several projects is one row."""
    ws = Path(ws) if ws else paths.workspace_dir()
    dev = Path(dev) if dev else paths.dev_dir()
    masters = {p.stem for p in (ws / "agents" / "claude").glob("*.md")} if (ws / "agents" / "claude").is_dir() else set()
    scan = scan_transcripts(projects_dir, budget_s, cache_path)
    groups: Dict[tuple, dict] = {}
    borrowed_total = recorded = 0

    def grp(key, name, kind):
        g = groups.setdefault(key, {"kind": kind, "names": Counter(), "projects": set(), "from": None})
        g["names"][name] += 0
        return g
    for proj in _projects(dev, ws):
        allent = read_borrowed(proj)
        recorded += len(allent)
        entries = [e for e in allent if os.path.lexists(str(proj / e["dest"]))]    # a record whose file is gone is history, not a borrowed item in use
        borrowed_total += len(entries)
        bmap = {(e["kind"], e["name"]): e for e in entries}
        for e in entries:
            g = grp(("src", e["kind"], e["sha"] or e["id"]), e["name"], e["kind"])
            g["from"] = g["from"] or e["id"]
            g["projects"].add(proj.name)
            g["names"][e["name"]] += 0
        for kind, names in (("agent", [n for n in _md_names(proj / ".claude" / "agents") if n not in masters]),
                            ("skill", _skill_dirs(proj / ".agents" / "skills"))):
            for n in names:
                e = bmap.get((kind, n))
                if e is not None:
                    continue    # already grouped by its source above
                g = grp(("name", kind, n), n, kind)
                g["projects"].add(proj.name)
    rows = []
    for key, g in groups.items():
        src = scan["agents"] if g["kind"] == "agent" else scan["skills"]
        names = sorted(g["names"])
        calls = sum(src[n] for n in names if not (g["kind"] == "agent" and n in BUILTIN_AGENTS))
        why = []
        if len(g["projects"]) >= PROMOTE_PROJECTS:
            why.append("in %d projects" % len(g["projects"]))
        if calls >= PROMOTE_CALLS:
            why.append("called %dx" % calls)
        rows.append({"name": names[0], "kind": g["kind"], "projects": sorted(g["projects"]), "calls": calls, "borrowed_from": g["from"],
                     "also": names[1:], "qualifies": bool(why), "why": " + ".join(why) or "-"})
    rows.sort(key=lambda r: (r["kind"], r["name"]))
    return {"rows": rows, "partial": scan["partial"], "borrowed": borrowed_total, "recorded": recorded, "scan": {k: scan[k] for k in ("read", "files", "cached")}}


def render_table(res: dict) -> str:
    rows = res["rows"]
    if not rows:
        return "No project-only agents or skills." + (_partial_note(res))
    lines = ["%-28s %-6s %-34s %5s  %s" % ("name", "kind", "projects", "calls", "promotion candidate?")]
    for r in rows:
        why = r["why"]
        if r["borrowed_from"]:
            why += "  [borrowed (inspired by %s)%s]" % (esc(r["borrowed_from"]), (", also named " + ", ".join(esc(a) for a in r["also"])) if r["also"] else "")
        lines.append("%-28s %-6s %-34s %5d  %s" % (esc(r["name"], 28), r["kind"], esc(",".join(r["projects"]), 34), r["calls"], why))
    return "\n".join(lines) + _partial_note(res)


def _partial_note(res: dict) -> str:
    return "\n(partial: the transcript scan stopped at its time budget; counts may be low, run again to continue)" if res.get("partial") else ""


def daily_line(res: dict) -> str:
    """One plain line for bin/daily, or "" when there is nothing to say."""
    cands = [r for r in res["rows"] if r["qualifies"]]
    if not res["borrowed"] and not cands and not res.get("recorded"):
        return ""
    gone = res.get("recorded", res["borrowed"]) - res["borrowed"]
    parts = ["Borrowed items: %d%s." % (res["borrowed"], " (%d more recorded, file gone)" % gone if gone > 0 else "")]
    if cands:
        shown = []
        for r in cands[:5]:
            t = "%s (%d projects, called %d times%s)" % (esc(r["name"], 40), len(r["projects"]), r["calls"], (", borrowed from " + esc(r["borrowed_from"], 80)) if r["borrowed_from"] else "")
            shown.append(t)
        more = " and %d more" % (len(cands) - 5) if len(cands) > 5 else ""
        parts.append("Promotion candidates: " + "; ".join(shown) + more + ", owner decides: bin/promote-agent <dir> <name>")
    else:
        parts.append("No promotion candidates yet.")
    if res.get("partial"):
        parts.append("(counts partial)")
    return " ".join(parts)


def _budget() -> float:
    v = os.environ.get("SHIPMIRACLE_USAGE_BUDGET") if os.environ.get("SHIPMIRACLE_TEST") == "1" else None
    try:
        return float(v) if v is not None else DEFAULT_BUDGET_S
    except ValueError:
        return DEFAULT_BUDGET_S


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    mode = argv[0] if argv else "table"
    if mode not in ("table", "daily-line", "report"):
        sys.stderr.write("usage: python3 -m shipmiracle.usage table|daily-line|report\n")
        return 2
    res = candidates(budget_s=_budget())
    if mode == "report":     # the table, then the one-line summary: one scan for bin/daily
        out = render_table(res)
        dl = daily_line(res)
        out = out + ("\n" + dl if dl else "")
    else:
        out = render_table(res) if mode == "table" else daily_line(res)
    if out:
        sys.stdout.write(out + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
