"""The owner's personal-value denylist: <config dir>/release-denylist.txt (spec 2026-10-20-p8-spec.md section 3).

File format (text, 0600, in a 0700 folder, never inside a git work tree):
    # salt: <32 hex>
    <kind><TAB><value>      one entry per line (kind: name, email, handle, id, user, host, project, path, ...)
    !<value>                exclude a word (case/Unicode-insensitive); it is dropped from the entries
Values are NEVER printed, logged or put in an exception: callers get kind + h, where h = sha256(salt || kind || value)[:8]
(see entry_hash: the three parts are joined with one NUL byte, value after Unicode normalisation + casefold).
Matching uses `norm()` (NFKC, zero-width characters removed, curly quotes straightened, casefold) on both sides, with the variants
raw, separators (space - _ . and none), apostrophe removed, URL-encoded (%20 and +) and Claude's folder-name form (every non-alphanumeric -> '-').
"""
from __future__ import annotations

import hashlib
import os
import re
import secrets
import stat
import subprocess
import unicodedata
import urllib.parse
from pathlib import Path

from .. import SafetyError, UsageError

FILENAME = "release-denylist.txt"
MIN_LEN = 4
STOPLIST = frozenset(["ideas", "notes", "app", "web", "api", "home", "test", "main", "docs", "shipmiracle", "shipm", "ai-workspace"])
# Common English words / generic terms that a project can be named. `refresh` does not add a project entry that is one of these (it would
# match the plain word all over the tree: 446 false findings for a project called "sandbox", 30 Oct 2026); the owner can force one back with
# `--include-generic NAME`. Only kind "project" is affected; names the owner types as manual entries or that other kinds carry are untouched.
GENERIC_PROJECT_TERMS = frozenset([
    "sandbox", "ideas", "notes", "test", "tests", "demo", "demos", "app", "apps", "web", "site", "docs", "tmp", "temp", "example", "examples",
    "playground", "scratch", "template", "templates", "projects", "misc", "tools", "work", "blog", "data", "api", "home", "main", "inbox"])
KIND_RE = re.compile(r"[a-z][a-z0-9_-]{0,15}")
SALT_RE = re.compile(r"[0-9a-f]{32}")
MAX_VALUE = 200
_ZW = dict.fromkeys(map(ord, "​‌‍⁠﻿­"))
_QUOTES = {ord("’"): "'", ord("‘"): "'", ord("ʼ"): "'"}


def norm(s: str) -> str:
    """The matching form of a string: NFKC, no zero-width characters, straight apostrophes, casefolded."""
    if s.isascii():
        return s.lower()
    return unicodedata.normalize("NFKC", s).translate(_ZW).translate(_QUOTES).casefold()


def entry_hash(salt: str, kind: str, value: str) -> str:
    """h = sha256(salt NUL kind NUL norm(value))[:8] (the only form of a value that may appear in output)."""
    return hashlib.sha256(("%s\0%s\0%s" % (salt, kind, norm(value))).encode("utf-8", "replace")).hexdigest()[:8]


def variants(value: str) -> set:
    """Every matching form of `value` (all already norm()ed, each at least MIN_LEN long)."""
    base = norm(value).strip()
    out = {base}
    parts = [p for p in re.split(r"[\s_.-]+", base) if p]
    if len(parts) > 1:
        for sep in (" ", "-", "_", "", "."):
            out.add(sep.join(parts))
    for v in list(out):
        out.add(v.replace("'", ""))
        dn = re.sub(r"[^a-z0-9]", "-", v)                           # claude_dirname form (letters are lower-case after norm)
        if len(dn.replace("-", "")) >= MIN_LEN:                     # a name with no Latin letters would collapse to dashes
            out.add(dn)
        q = urllib.parse.quote(v, safe="").lower()
        out.add(q)
        out.add(urllib.parse.quote_plus(v, safe="").lower())
        out.add(urllib.parse.quote(v, safe="/@:").lower())
    return set(v for v in out if len(v) >= MIN_LEN)


def usable(value: str) -> bool:
    v = norm(value).strip()
    return bool(v) and len(v) >= MIN_LEN and v not in STOPLIST and len(value) <= MAX_VALUE and "\n" not in value and "\0" not in value


# ---------------------------------------------------------------- safety
def inside_git_tree(path) -> bool:
    """True when `path` or any parent folder holds a .git entry (file or folder): a git work tree (or the home folder used as one)."""
    d = Path(os.path.realpath(str(path)))
    if d.is_file() or not d.exists():
        d = d.parent
    while True:
        if os.path.lexists(str(d / ".git")):
            return True
        if d.parent == d:
            return False
        d = d.parent


def check_safe(path, need_file: bool = True) -> None:
    """SafetyError (exit 4) unless the denylist is a regular 0600 file of ours in a 0700 folder of ours outside every git work tree.
    Messages name the path and the rule, never a value."""
    p = Path(path)
    try:
        dst = os.lstat(str(p.parent))
    except FileNotFoundError:
        raise
    except OSError:
        raise SafetyError("denylist folder %s is not readable" % p.parent)
    if stat.S_ISLNK(dst.st_mode) or not stat.S_ISDIR(dst.st_mode) or dst.st_uid != os.getuid():
        raise SafetyError("denylist folder %s is a symlink, not a folder or not yours" % p.parent)
    if dst.st_mode & 0o077:
        raise SafetyError("denylist folder %s is group/world accessible (needs 0700)" % p.parent)
    if inside_git_tree(p.parent):
        raise SafetyError("denylist %s is inside a git work tree; move it outside every repository" % p)
    if need_file:
        try:
            st = os.lstat(str(p))
        except FileNotFoundError:
            raise
        except OSError:
            raise SafetyError("denylist %s is not readable" % p)
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid():
            raise SafetyError("denylist %s is a symlink, not a regular file or not yours" % p)
        if st.st_mode & 0o077:
            raise SafetyError("denylist %s is group/world accessible (needs 0600)" % p)


# ---------------------------------------------------------------- load
class Denylist(object):
    def __init__(self, salt, entries, malformed=0):
        self.salt = salt
        self.entries = entries              # [(kind, value)] after exclusions and stoplist
        self.malformed = malformed

    def hashes(self):
        return sorted((k, entry_hash(self.salt, k, v)) for k, v in self.entries)


def parse(text: str) -> Denylist:
    salt = None
    raw, excl, bad = [], set(), 0
    for line in text.splitlines():
        if not line.strip():
            continue
        if line.startswith("#"):
            m = re.match(r"#\s*salt:\s*([0-9a-f]{32})\s*$", line)
            if m and salt is None:
                salt = m.group(1)
            continue
        if line.startswith("!"):
            v = line[1:].strip()
            if v:
                excl.add(norm(v))
            else:
                bad += 1
            continue
        kind, tab, value = line.partition("\t")
        value = value.strip()
        if not tab or not KIND_RE.fullmatch(kind) or not value:
            bad += 1
            continue
        raw.append((kind, value))
    if salt is None:
        raise UsageError("denylist has no '# salt: <32 hex>' header (run: shipm release denylist --refresh)")
    seen, out = set(), []
    for kind, value in raw:
        key = (kind, norm(value))
        if norm(value) in excl or not usable(value) or key in seen:
            continue
        seen.add(key)
        out.append((kind, value))
    return Denylist(salt, out, bad)


def load(path):
    """The Denylist at `path`, or None when the file does not exist. SafetyError when it is unsafe (see check_safe)."""
    p = Path(path)
    try:
        check_safe(p)
    except FileNotFoundError:
        return None
    fd = os.open(str(p), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        with os.fdopen(fd, "rb") as f:
            data = f.read(1 << 20)
    except OSError:
        raise SafetyError("denylist %s is not readable" % p)
    return parse(data.decode("utf-8", "replace"))


# ---------------------------------------------------------------- matching
class Matcher(object):
    """One compiled alternation over every variant of every entry. find(text) -> [(kind, h, offset)] on norm(text)."""

    def __init__(self, dl: Denylist):
        self.salt = dl.salt
        self.by_variant = {}
        for kind, value in dl.entries:
            h = entry_hash(dl.salt, kind, value)
            for v in variants(value):
                self.by_variant.setdefault(v, set()).add((kind, h))
        # (kind, h) of the PUBLIC login: a `user` entry whose text equals a `handle` entry (and that `handle` entry) (the owner's account name is both the Mac user and the
        # GitHub login). Only these may be exempted at the reviewed files (check.LOGIN_EXEMPT); a user entry without a matching handle is private.
        handles = set(norm(v).strip() for k, v in dl.entries if k == "handle")
        users = set(norm(v).strip() for k, v in dl.entries if k == "user")
        both = handles & users
        self.login_hashes = set((k, entry_hash(dl.salt, k, v)) for k, v in dl.entries if k in ("user", "handle") and norm(v).strip() in both)
        self.login_used = set()
        self.rx = None
        if self.by_variant:
            self.rx = re.compile("|".join(re.escape(v) for v in sorted(self.by_variant, key=lambda x: (-len(x), x))))

    def __bool__(self):
        return self.rx is not None

    def search_norm(self, text_norm: str):
        """[(kind, h, offset in text_norm)] for every non-overlapping variant hit (all entries sharing the variant)."""
        if self.rx is None:
            return []
        out = []
        for m in self.rx.finditer(text_norm):
            for kind, h in sorted(self.by_variant[m.group(0)]):
                out.append((kind, h, m.start()))
        return out


# ---------------------------------------------------------------- refresh
class SystemProvider(object):
    """Gathers the values from this Mac (git config, gh, scutil, id, registry, config). Tests inject a fake with the same collect()."""

    def _run(self, argv, timeout=15):
        try:
            r = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=timeout, shell=False)
        except (OSError, subprocess.SubprocessError):
            return None
        return r.stdout.decode("utf-8", "replace").strip() if r.returncode == 0 else None

    def collect(self):
        from .. import config, paths, registry
        ent, notes, author = [], [], None

        def add(kind, v):
            if v and v != "null":
                ent.append((kind, v.strip()))
        add("name", self._run(["git", "config", "--global", "user.name"]))
        add("email", self._run(["git", "config", "--global", "user.email"]))
        try:
            reg = registry.load().get("projects", {})
        except Exception:
            reg, _ = {}, notes.append("registry unreadable")
        for pid in sorted(reg):
            e = reg[pid]
            nm = e.get("name")
            if isinstance(nm, str):
                add("project", nm)
                d = paths.dev_dir() / nm
                if d.is_dir():
                    add("email", self._run(["git", "-C", str(d), "config", "--local", "user.email"]))
            for k in ("display_name", "display"):
                if isinstance(e.get(k), str):
                    add("project", e[k])
            rem = e.get("remote")
            if isinstance(rem, str) and rem.count("/") == 1:
                add("handle", rem.split("/")[0])
                add("project", rem.split("/")[1])
        gh = self._run(["gh", "api", "user", "--jq", ".login,.name,.email,.id"], timeout=30)
        if gh is None:
            notes.append("gh unavailable: handle/name/email/id from GitHub not added")
        else:
            ls = (gh.split("\n") + ["", "", "", ""])[:4]
            add("handle", ls[0]); add("name", ls[1]); add("email", ls[2]); add("id", ls[3])
            if ls[0] and ls[3].isdigit() and re.fullmatch(r"[A-Za-z0-9-]+", ls[0]):
                author = (ls[0], "%s+%s@users.noreply.github.com" % (ls[3], ls[0]))
        add("user", paths.real_home().name)
        add("name", self._run(["id", "-F"]))
        add("host", self._run(["scutil", "--get", "ComputerName"]))
        add("host", self._run(["scutil", "--get", "LocalHostName"]))
        add("path", str(paths.dev_dir()))
        return {"entries": ent, "notes": notes, "author": author}


def _existing_keep(path):
    """Lines to preserve across a refresh: '!' excludes, manual entries, and the salt."""
    keep, salt = [], None
    try:
        txt = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return keep, salt
    for line in txt.splitlines():
        m = re.match(r"#\s*salt:\s*([0-9a-f]{32})\s*$", line)
        if m and salt is None:
            salt = m.group(1)
        elif line.startswith("!") or line.startswith("manual\t"):
            keep.append(line)
    return keep, salt


def refresh(path, provider=None, include_generic=()) -> dict:
    """Write the denylist from `provider.collect()`. Caller has required the owner. Raises SafetyError (inside a git work tree, bad owner,
    symlink) and UsageError (an include_generic name that is not a built-in common word). Returns {"counts": {kind: n}, "notes": [...],
    "author": ..., "skipped": [common word, ...]}; never returns private values (a skipped word is the built-in term itself)."""
    force = set()
    for name in include_generic:
        n = norm(name).strip()
        if n not in GENERIC_PROJECT_TERMS:
            raise UsageError("--include-generic: the given name is not a built-in common word (nothing to force-include; it is added already)")
        force.add(n)
    p = Path(path)
    d = p.parent
    if inside_git_tree(d if d.exists() else d.parent):
        raise SafetyError("denylist folder %s is inside a git work tree; refusing" % d)
    if not d.exists():
        d.mkdir(parents=True, mode=0o700)
    st = os.lstat(str(d))
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
        raise SafetyError("denylist folder %s is a symlink, not a folder or not yours" % d)
    if st.st_mode & 0o077:
        os.chmod(str(d), stat.S_IMODE(st.st_mode) & 0o700)          # harden our own folder; never widened
    if os.path.lexists(str(p)):
        s2 = os.lstat(str(p))
        if stat.S_ISLNK(s2.st_mode) or not stat.S_ISREG(s2.st_mode):
            raise SafetyError("denylist %s is a symlink or not a regular file" % p)
    keep, salt = _existing_keep(p)
    salt = salt or secrets.token_hex(16)
    got = (provider or SystemProvider()).collect()
    seen, lines, counts, skipped = set(), [], {}, set()
    for kind, value in got["entries"]:
        if not KIND_RE.fullmatch(kind) or not usable(value):
            continue
        nv = norm(value).strip()
        if kind == "project" and nv in GENERIC_PROJECT_TERMS and nv not in force:
            skipped.add(nv)
            continue
        key = (kind, norm(value))
        if key in seen:
            continue
        seen.add(key)
        lines.append("%s\t%s" % (kind, value.strip()))
        counts[kind] = counts.get(kind, 0) + 1
    body = "# salt: %s\n# generated by: shipm release denylist --refresh (do not commit, do not share)\n%s\n" % (
        salt, "\n".join(sorted(lines) + keep))
    tmp = d / (".%s.%s.tmp" % (p.name, secrets.token_hex(4)))
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(body.encode("utf-8"))
            f.flush()
            os.fsync(f.fileno())
        os.replace(str(tmp), str(p))
    except BaseException:
        try:
            os.unlink(str(tmp))
        except OSError:
            pass
        raise
    return {"counts": counts, "notes": list(got.get("notes", [])), "author": got.get("author"),
            "skipped": sorted(skipped)}
