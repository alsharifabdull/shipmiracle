"""The project team table (CHECKLIST G6): which agent does which job in THIS project, written down on purpose.

The table is a marked block inside <project>/docs/SKILLS.md:

    ## Team
    <!-- team:begin -->
    | Role | Agent | Skills | Why |
    |---|---|---|---|
    | build | builder-backend | - | API and data work |
    <!-- team:end -->

`shipm skills view --write` regenerates the rest of that file and copies this block forward byte for byte. Only the lead (or the owner)
writes it; `shipm team add` is the checked way. This module reads and renders the block and answers `team_rows(project_dir)`, the one function
a later gate reads. It never follows a symbolic link and never opens a FIFO. Limits: the file is read up to 64 KB, the block is at most 16 KB
and 40 rows. A row that cannot be parsed is ignored and reported; a block with no valid row is "no table".
A block whose markers are damaged (nested, twice, unmatched) is reported as damaged and never guessed at."""
from __future__ import annotations

import errno
import hashlib
import os
import re
import stat
import tempfile
import unicodedata
from pathlib import Path
from typing import List, NamedTuple, Optional, Tuple

from . import LockTimeout, ShipmiracleError, SafetyError, UsageError
from . import agents, state

BEGIN = "<!-- team:begin -->"
END = "<!-- team:end -->"
HEADING = "## Team"
HEADER_LINE = "| Role | Agent | Skills | Why |"
SEP_LINE = "|---|---|---|---|"
MAX_FILE = 64 * 1024        # bytes read from docs/SKILLS.md
MAX_BLOCK = 16 * 1024       # bytes of one Team block (render and add refuse more)
MAX_ROWS = 40
MAX_WHY = 200
MAX_SKILLS = 16

_ROLE_RE = re.compile(r"[a-z]{2,16}")
_SKILL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}")
_SEPCELL_RE = re.compile(r":?-{1,}:?")
_LINE_RE = re.compile(r"[^\n]*\n|[^\n]+")


class Table(NamedTuple):
    state: str            # "ok" | "none" (no block or no valid row) | "damaged" | "unreadable"
    rows: list            # [{"role","agent","agent_raw","skills":[...],"why"}]
    ignored: list         # [(line number within the file, reason)]
    detail: str           # why damaged / unreadable ("" otherwise)


# ------------------------------------------------------------------ safe file read
def _component_problem(root, path) -> str:
    """lstat every folder between the project root and the file: a symbolic link (or a non-folder) anywhere on the way is a refusal."""
    try:
        rel = Path(path).relative_to(root).parts[:-1]
    except ValueError:
        return "is outside the project"
    cur = Path(root)
    for part in rel:
        cur = cur / part
        try:
            st = os.lstat(str(cur))
        except FileNotFoundError:
            return ""
        except OSError:
            return "has an unreadable folder on its path"
        if stat.S_ISLNK(st.st_mode):
            return "has a symbolic link on its path (%s)" % part
        if not stat.S_ISDIR(st.st_mode):
            return "has a non-folder on its path (%s)" % part
    return ""


def read_text(path, root=None) -> Tuple[Optional[str], str]:
    """-> (text, "") ; (None, "") when the file does not exist ; (None, reason) when it exists but may not be read:
    a symbolic link, anything that is not a regular file (FIFO, socket, device, folder), more than 64 KB, not UTF-8, or a NUL byte.
    Newlines are NOT translated (CRLF stays CRLF)."""
    if root is not None:
        bad = _component_problem(root, path)
        if bad:
            return None, bad
    try:
        st = os.lstat(str(path))
    except FileNotFoundError:
        return None, ""
    except OSError as e:
        return None, "cannot be read (%s)" % errno.errorcode.get(e.errno, "error")
    if stat.S_ISLNK(st.st_mode):
        return None, "is a symbolic link"
    if not stat.S_ISREG(st.st_mode):
        return None, "is not a regular file"
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(str(path), flags)
    except OSError as e:
        return None, "cannot be opened (%s)" % errno.errorcode.get(e.errno, "error")
    try:
        st2 = os.fstat(fd)
        if not stat.S_ISREG(st2.st_mode):
            return None, "is not a regular file"
        chunks, total = [], 0
        while total <= MAX_FILE:
            b = os.read(fd, MAX_FILE + 1 - total)
            if not b:
                break
            chunks.append(b)
            total += len(b)
    finally:
        os.close(fd)
    data = b"".join(chunks)
    if len(data) > MAX_FILE:
        return None, "is larger than %d KB" % (MAX_FILE // 1024)
    if b"\x00" in data:
        return None, "contains a NUL byte"
    try:
        return data.decode("utf-8"), ""
    except UnicodeDecodeError:
        return None, "is not UTF-8 text"


# ------------------------------------------------------------------ cells
def _bad_char(s: str) -> Optional[str]:
    for ch in s:
        cat = unicodedata.category(ch)
        if cat in ("Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"):
            return "control, bidi or zero-width character U+%04X" % ord(ch)
        if ch in "|`":
            return "the character %s" % ch
    return None


def norm_agent(name: str) -> str:
    """Old role names become their new agent (qa-engineer -> verifier); kebab names and plugin:name stay as they are."""
    return agents.ALIASES.get(name, name)


def check_agent_name(name) -> str:
    if not isinstance(name, str) or not (agents._NAME_RE.fullmatch(name) or agents._PLUGIN_RE.fullmatch(name)):
        raise UsageError("not an agent name (use the agent_type: kebab-case or plugin:name)")
    return norm_agent(name)


def _cell_problem(role, agent, skills, why) -> Optional[str]:
    for label, v in (("role", role), ("agent", agent), ("skills", skills), ("why", why)):
        bad = _bad_char(v)
        if bad:
            return "%s has %s" % (label, bad)
    if not _ROLE_RE.fullmatch(role):
        return "role is not a lower-case word"
    try:
        check_agent_name(agent)
    except UsageError:
        return "agent is not an agent name"
    if len(why) > MAX_WHY:
        return "why is longer than %d characters" % MAX_WHY
    if not why:
        return "why is empty"
    if skills not in ("", "-"):
        parts = [x.strip() for x in skills.split(",")]
        if len(parts) > MAX_SKILLS or not all(_SKILL_RE.fullmatch(p) for p in parts):
            return "skills is not a comma list of skill names"
    return None


def _skill_list(cell: str) -> List[str]:
    if cell in ("", "-"):
        return []
    return [x.strip() for x in cell.split(",")]


# ------------------------------------------------------------------ the block
def find_block(text: str) -> Tuple[str, Optional[Tuple[int, int, int, int]], str]:
    """-> ("none"|"ok"|"damaged", (begin_line_start, begin_line_end, end_line_start, end_line_end) offsets, detail).
    A marker counts only when it is alone on its line. Exactly one begin and one end, begin first, otherwise damaged."""
    begins, ends = [], []
    fence = None                          # a marker inside a fenced code block (an example of the format) is not the table
    for m in _LINE_RE.finditer(text):
        s = m.group(0).strip()
        if fence is not None:
            if s.startswith(fence) and not s.strip(fence[0]):
                fence = None
            continue
        if s.startswith("```") or s.startswith("~~~"):
            fence = s[:3]
            continue
        if s == BEGIN:
            begins.append(m)
        elif s == END:
            ends.append(m)
        elif BEGIN in s or END in s:
            pass                          # a marker inside other text is plain text
    if fence is not None and (BEGIN in text or END in text):
        return "damaged", None, "a code fence is never closed"
    if not begins and not ends:
        return "none", None, ""
    if len(begins) != 1 or len(ends) != 1:
        return "damaged", None, "expected one %s and one %s, found %d and %d" % (BEGIN, END, len(begins), len(ends))
    b, e = begins[0], ends[0]
    if e.start() < b.start():
        return "damaged", None, "%s comes before %s" % (END, BEGIN)
    return "ok", (b.start(), b.end(), e.start(), e.end()), ""


def block_text(text: str) -> Optional[str]:
    """The block exactly as written, from the start of the begin line to the end of the end line (None when there is none)."""
    st, off, _d = find_block(text)
    return text[off[0]:off[3]] if st == "ok" else None


def _split_cells(line: str) -> Optional[List[str]]:
    s = line.strip()
    if not s.startswith("|"):
        return None
    s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def parse_text(text: Optional[str], reason: str = "") -> Table:
    """The Team table of a docs/SKILLS.md text (text None + reason = unreadable file)."""
    if text is None:
        return Table("unreadable", [], [], reason) if reason else Table("none", [], [], "")
    st, off, detail = find_block(text)
    if st == "none":
        return Table("none", [], [], "")
    if st == "damaged":
        return Table("damaged", [], [], detail)
    inner = text[off[1]:off[2]]
    if len(text[off[0]:off[3]].encode("utf-8")) > MAX_BLOCK:
        return Table("damaged", [], [], "the Team block is larger than %d KB" % (MAX_BLOCK // 1024))
    base_line = text.count("\n", 0, off[1]) + 1
    rows, ignored, seen = [], [], {}
    for i, raw in enumerate(inner.split("\n")):
        lineno = base_line + i
        line = raw.rstrip("\r")
        if not line.strip():
            continue
        cells = _split_cells(line)
        if cells is None:
            ignored.append((lineno, "not a table row"))
            continue
        if all(_SEPCELL_RE.fullmatch(c) for c in cells if c) and any(cells):
            continue
        if [c.lower() for c in cells] == ["role", "agent", "skills", "why"]:
            continue
        if len(cells) != 4:
            ignored.append((lineno, "expected 4 columns, found %d" % len(cells)))
            continue
        role, agent, skills, why = cells
        prob = _cell_problem(role, agent, skills, why)
        if prob:
            ignored.append((lineno, prob))
            continue
        norm = norm_agent(agent)
        if norm in seen:
            ignored.append((lineno, "duplicate of line %d (agent %s)" % (seen[norm], norm)))
            continue
        if len(rows) >= MAX_ROWS:
            ignored.append((lineno, "more than %d rows" % MAX_ROWS))
            continue
        seen[norm] = lineno
        rows.append({"role": role, "agent": norm, "agent_raw": agent, "skills": _skill_list(skills), "why": why})
    if not rows:
        return Table("none", [], ignored, "")
    return Table("ok", rows, ignored, "")


def load(project_dir) -> Table:
    text, reason = read_text(Path(project_dir) / "docs" / "SKILLS.md", root=project_dir)
    return parse_text(text, reason)


def team_rows(project_dir) -> list:
    """The valid rows of the project's Team table ([] = no table, damaged or unreadable). The gate calls this; it never raises on a hostile file."""
    try:
        return list(load(project_dir).rows)
    except Exception:
        return []


def render_row(role, agent, skills, why) -> str:
    prob = _cell_problem(role, agent, ",".join(skills) if skills else "-", why)
    if prob:
        raise UsageError("not written: " + prob)
    return "| %s | %s | %s | %s |" % (role, norm_agent(agent), ", ".join(skills) if skills else "-", why)


def render_block(rows, eol="\n") -> str:
    lines = [BEGIN, HEADER_LINE, SEP_LINE] + [render_row(r["role"], r["agent"], r.get("skills") or [], r["why"]) for r in rows] + [END]
    out = eol.join(lines) + eol
    if len(out.encode("utf-8")) > MAX_BLOCK:
        raise UsageError("the Team block would be larger than %d KB" % (MAX_BLOCK // 1024))
    return out


# ------------------------------------------------------------------ write
def _atomic_write(path: Path, text: str) -> None:
    """Temp file in the same folder, fsync, os.replace: an interruption leaves the old file. Newlines are written as they are."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix="." + path.name + ".")
    except OSError as e:
        raise ShipmiracleError("cannot write docs/SKILLS.md (%s): nothing was changed" % (os.strerror(e.errno) if e.errno else "error"))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(text.encode("utf-8"))
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o644)
        os.replace(tmp, str(path))
    except BaseException as e:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        if isinstance(e, OSError):
            raise ShipmiracleError("cannot write docs/SKILLS.md (%s): nothing was changed" % (os.strerror(e.errno) if e.errno else "error"))
        raise


LOCK_WAIT = 10.0


def _lock(project_dir):
    """One lock per project, in the owner-side state folder (outside the project): two `team add` at once take turns instead of losing a row."""
    key = hashlib.sha1(os.path.realpath(str(project_dir)).encode("utf-8", "surrogateescape")).hexdigest()[:20]
    return state.locked("team-" + key, timeout=LOCK_WAIT)


def add_row(project_dir, agent, role, why, skills=None, home=None) -> dict:
    """Add one row to the project's Team table (creating the block, and the file, when missing). The agent must resolve for this project;
    a duplicate (after alias normalisation) is refused; a damaged block, an unreadable file, a full table (40 rows) or a block that would pass
    16 KB is refused. Existing rows and any other text in the block stay exactly as they were. The read, the check and the replace happen
    under one per-project lock, so parallel adds all land."""
    if not isinstance(agent, str):
        raise UsageError("an agent name is needed")
    agent, role, why = agent.strip(), (role or "").strip(), (why or "").strip()
    if not role or not why:
        raise UsageError("not written: role and why must not be empty")
    norm = check_agent_name(agent)
    skills = [s.strip() for s in (skills or [])]
    if any(not s for s in skills):
        raise UsageError("not written: an empty skill name")
    r = agents.resolve(norm, str(project_dir), home)
    if r is None:
        raise UsageError("not written: '%s' does not resolve to an agent for this project (see `shipm agents list --project <dir>`)" % agent[:64])
    row = render_row(role, norm, skills, why)         # validates every cell
    target = Path(project_dir) / "docs" / "SKILLS.md"
    try:
        lock = _lock(project_dir)
        with lock:
            return _add_locked(project_dir, target, row, norm, role, skills, r, home)
    except LockTimeout:
        raise ShipmiracleError("another `shipm team add` is still running for this project (waited %d s): try again" % int(LOCK_WAIT))


def _add_locked(project_dir, target, row, norm, role, skills, r, home) -> dict:
    text, reason = read_text(target, root=project_dir)
    if text is None and reason:
        raise SafetyError("docs/SKILLS.md %s: not changed" % reason)
    if text is None:
        new = HEADING + "\n" + render_block([]).replace(END, row + "\n" + END)
        created = True
    else:
        t = parse_text(text)
        if t.state == "damaged":
            raise UsageError("not written: the Team block is damaged (%s); fix docs/SKILLS.md by hand first" % t.detail)
        if any(x["agent"] == norm for x in t.rows):
            raise UsageError("not written: %s is already on the team" % norm)
        if len(t.rows) >= MAX_ROWS:
            raise UsageError("not written: the team is full: %d rows" % MAX_ROWS)
        st, off, _d = find_block(text)
        if st == "ok":
            eol = "\r\n" if text[off[0]:off[1]].endswith("\r\n") else "\n"
            new = text[:off[2]] + row + eol + text[off[2]:]
            blk = new[off[0]:off[3] + len(row) + len(eol)]
            if len(blk.encode("utf-8")) > MAX_BLOCK:
                raise UsageError("not written: the Team block would be larger than %d KB" % (MAX_BLOCK // 1024))
        else:
            sep = "" if text.endswith("\n") or not text else "\n"
            new = text + sep + ("\n" if text else "") + HEADING + "\n" + render_block([]).replace(END, row + "\n" + END)
        created = False
    if len(new.encode("utf-8")) > MAX_FILE:
        raise UsageError("not written: docs/SKILLS.md would be larger than %d KB" % (MAX_FILE // 1024))
    _atomic_write(target, new)
    missing = [s for s in skills if not agents.skill_exists(s, str(project_dir), home)]
    return {"agent": norm, "role": role, "path": str(target), "created_file": created, "effective": r.effective, "missing_skills": missing}


# ------------------------------------------------------------------ check
def _record_checks(project_dir, rows) -> List[Tuple[str, str]]:
    """Cross-checks against other records: the borrow record (.agents/borrowed.json) and the owner-side borrow log. Returns (level, message) pairs."""
    from . import borrow
    return borrow.check_records(project_dir, rows)


def check(project_dir, home=None) -> List[Tuple[str, str]]:
    """-> [(level, message)] with level "problem" or "warn". Empty = clean."""
    out: List[Tuple[str, str]] = []
    t = load(project_dir)
    if t.state == "unreadable":
        return [("problem", "docs/SKILLS.md %s" % t.detail)]
    if t.state == "damaged":
        return [("problem", "the Team block is damaged: %s" % t.detail)]
    if t.state == "none":
        out.append(("problem", "no Team table: record the team with `shipm team add AGENT --role R --why \"...\"`"))
        out += [("warn", "line %d ignored: %s" % (ln, why)) for ln, why in t.ignored]
        return out
    for ln, why in t.ignored:
        out.append(("warn", "line %d ignored: %s" % (ln, why)))
    roles = set()
    for r in t.rows:
        res = agents.resolve(r["agent"], str(project_dir), home)
        if res is None:
            out.append(("problem", "%s does not resolve to an agent for this project" % r["agent"]))
            continue
        roles.add(res.effective)
        if r["role"] != res.effective:
            out.append(("warn", "%s: Role cell says %s but its effective role is %s" % (r["agent"], r["role"], res.effective)))
        for s in r["skills"]:
            if not agents.skill_exists(s, str(project_dir), home):
                out.append(("problem", "%s: skill %s is not installed here" % (r["agent"], s)))
    for need in ("test", "review"):
        if need not in roles:
            out.append(("problem", "no team member has the %s role" % need))
    out += _record_checks(project_dir, t.rows)
    return out


def exit_code(findings) -> int:
    if any(lv == "problem" for lv, _m in findings):
        return 1
    return 3 if findings else 0
