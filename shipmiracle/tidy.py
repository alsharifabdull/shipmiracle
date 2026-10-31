"""`shipm tidy` (F10 phase 1): a READ-ONLY report of how a project folder compares with docs/standards/folders.md.

It never moves, deletes, creates or changes anything in the project, and writes nothing anywhere (no state file either): the result is printed.
How it stays read-only and safe on a hostile folder:
 - the tree is walked with directory file descriptors opened O_DIRECTORY|O_NOFOLLOW|O_NONBLOCK; a symbolic link is an item of its own and is never entered or counted through;
 - nothing but a few small markdown files is ever opened, and only after lstat says "regular file" (opened O_RDONLY|O_NONBLOCK|O_NOFOLLOW, then fstat again);
   a FIFO, socket or device is never opened or read;
 - another volume (st_dev differs) is not entered; a hard-linked file is counted once; sizes are allocated bytes (st_blocks * 512);
 - the walk has a budget (entries and seconds); when it runs out the report says "partial";
 - an unreadable folder is skipped with a line, not an error;
 - every name that is printed passes `clean()`: control, bidi, zero-width and markup characters are shown as \\uXXXX escapes.
Git is only asked read-only questions (ls-files, check-ignore) with a clean environment, no optional locks, no fsmonitor, no hooks.
Classes (first match wins): never, regenerable, disposable, review, plus "kept" (small/recent or work in progress; counted, not listed)."""
from __future__ import annotations

import fnmatch
import os
import urllib.parse
import re
import stat
import subprocess
import time
import unicodedata

from . import NotFound, UsageError

MAX_ENTRIES = 2_000_000
MAX_SECONDS = 20.0
MAX_DEPTH = 64
SCRATCH_DAYS = 14
BACKUP_KEEP = 3
BACKUP_DAYS = 30
REVIEW_BYTES = 50 * 1024 * 1024
REVIEW_DAYS = 90
WIP_DAYS = 30
IDLE_DAYS = 14
MD_MAX = 1024 * 1024
MD_FILES = 2000
GIT_TIMEOUT = 20
LISTING_CAP = 64_000_000         # bytes read from one git listing (a longer one counts as "git could not be read")
MAX_TOP = 20000                  # top-level entries and scratch/backup children looked at; more -> partial
LIST_CAP = 50                    # items / suggestions / skipped names per list in the output
MD_TOTAL = 32 * 1024 * 1024      # bytes of markdown read in all
LINKS_CAP = 200000

SECRET_GLOBS = (".env", ".env.*", "*.pem", "*.key", "*.p12", "secrets.*", "*.pfx", "id_rsa*", "id_ed25519*")
NEVER_NAMES = frozenset([".git", "docs", "design", "archive", "backups", "." + "ai" + "w", ".claude", ".githooks", ".github", ".vscode", ".shipmiracle",
                         "src", "apps", "packages", "tests", "agents", "bin", "hooks", "templates", "AGENTS.md", "CLAUDE.md", "README.md"])
ONLY_COPY = frozenset(["backups", "archive"])
REGEN_MARKER = {                       # name -> files that must exist (next to it, or inside it for the *_inside ones)
    "node_modules": ("package.json",),
    "Pods": ("Podfile.lock",),
    ".build": ("Package.swift",),
}
REGEN_INSIDE = {".venv": "pyvenv.cfg", "venv": "pyvenv.cfg"}
REGEN_STACK = frozenset(["dist", "build", ".next", ".turbo", "coverage", "test-results", "playwright-report", ".playwright-mcp", "__pycache__", ".pytest_cache", ".gradle", "DerivedData"])
STACK_FILES = ("package.json", "pyproject.toml", "setup.py", "Cargo.toml", "build.gradle", "Package.swift", "Makefile", "go.mod")
ARCHIVE_EXT = (".zip", ".tar", ".tar.gz", ".tgz", ".7z", ".rar", ".tar.bz2", ".tar.xz")
VERSION_RE = re.compile(r"^v\d{2,}[A-Za-z0-9._-]*$")
DATED_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-[A-Za-z0-9][A-Za-z0-9._-]*$")
SHOT_DIRS = frozenset(["screens", "screenshots", "shots", "screenshot"])
LINK_RES = (re.compile(r"\]\(\s*<([^>\n]+)>"), re.compile(r"\]\(\s*([^)\s<>]+)"), re.compile(r"(?m)^\s{0,3}\[[^\]\n]+\]:\s*<?([^\s<>]+)"),
            re.compile(r"""(?i)\b(?:src|href|poster|data)\s*=\s*["']([^"'<>\n]+)["']"""))
_ESC_CATS = ("Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp")
_ESC_CHARS = "<>&`\"'\\"


# ---------------------------------------------------------------- text
def clean(s, n=120) -> str:
    """Safe to print on one line: control/bidi/zero-width/markup characters become \\uXXXX, other whitespace a single space; cut at n characters."""
    out = []
    for c in str(s):
        if c == " ":
            out.append(" ")
        elif unicodedata.category(c) in _ESC_CATS or c in _ESC_CHARS or (c.isspace() and c != " "):
            out.append("\\u%04x" % ord(c) if ord(c) < 0x10000 else "\\U%08x" % ord(c))
        else:
            out.append(c)
    t = "".join(out)
    return t if len(t) <= n else t[: n - 1] + "..."


def human_bytes(n) -> str:
    n = float(n)
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or u == "TB":
            return "%d B" % n if u == "B" else "%.1f %s" % (n, u)
        n /= 1024.0
    return "%d B" % n


# ---------------------------------------------------------------- budgeted walk
class Budget:
    def __init__(self, max_entries=MAX_ENTRIES, max_seconds=MAX_SECONDS):
        self.max_entries, self.deadline = max_entries, time.monotonic() + max_seconds
        self.entries = 0
        self.partial = False
        self.seen = set()                # (dev, ino) of hard-linked files already counted
        self.secret = False              # a secret-looking name was met inside the item being measured
        self.unreadable = []             # relative paths (first LIST_CAP), cleaned later
        self.other_volume = []
        self.n_unreadable = self.n_other = 0
        self.incomplete = False          # the item being measured was NOT fully looked at (budget, depth, unreadable, other volume)

    def skip_unreadable(self, rel):
        self.incomplete = True
        self.n_unreadable += 1
        if len(self.unreadable) < LIST_CAP:
            self.unreadable.append(rel)

    def skip_volume(self, rel):
        self.incomplete = True
        self.n_other += 1
        if len(self.other_volume) < LIST_CAP:
            self.other_volume.append(rel)

    def tick(self) -> bool:
        self.entries += 1
        if self.entries > self.max_entries or (self.entries & 0xFF == 0 and time.monotonic() > self.deadline):
            self.partial = True
        return not self.partial

    def late(self) -> bool:
        """Deadline check, also done when a folder is entered."""
        if time.monotonic() > self.deadline:
            self.partial = True
        return self.partial


_DIR_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)


def _open_dir(name, dir_fd=None):
    return os.open(name, _DIR_FLAGS, dir_fd=dir_fd) if dir_fd is not None else os.open(name, _DIR_FLAGS)


def open_path(root, rel):
    """fd of the folder root/rel opened component by component with O_NOFOLLOW (a link anywhere on the way makes it fail)."""
    fd = _open_dir(root)
    try:
        for part in [x for x in rel.split("/") if x]:
            nfd = _open_dir(part, fd)
            os.close(fd)
            fd = nfd
        return fd
    except OSError:
        os.close(fd)
        raise


def measure(entry_st, name, parent_fd, rel, root_dev, b, depth=0):
    """(allocated bytes, newest mtime) of one item below parent_fd. A directory is walked (never through a link); anything else is lstat only."""
    if not b.tick():
        b.incomplete = True              # the budget ran out at this entry; the walk of every folder above it stops and is incomplete too
        return 0, entry_st.st_mtime
    if _secret(name):
        b.secret = True
    newest = entry_st.st_mtime
    if stat.S_ISDIR(entry_st.st_mode):
        if entry_st.st_dev != root_dev:
            b.skip_volume(rel)
            return 0, newest
        if depth >= MAX_DEPTH or b.late():
            b.incomplete = True              # only this item is unfinished; the rest of the scan goes on
            return 0, newest
        try:
            fd = _open_dir(name, parent_fd)
        except OSError:
            b.skip_unreadable(rel)
            return 0, newest
        total = 0
        try:
            try:
                with os.scandir(fd) as it:          # lazily: the entry budget bounds memory
                    for e in it:
                        if b.partial:
                            break
                        try:
                            st = e.stat(follow_symlinks=False)
                        except OSError:
                            continue
                        sz, nw = measure(st, e.name, fd, rel + "/" + e.name, root_dev, b, depth + 1)
                        total += sz
                        newest = max(newest, nw)
            except OSError:
                b.skip_unreadable(rel)
                return 0, newest
        finally:
            os.close(fd)
        return total + getattr(entry_st, "st_blocks", 0) * 512, newest
    if entry_st.st_nlink > 1 and stat.S_ISREG(entry_st.st_mode):
        key = (entry_st.st_dev, entry_st.st_ino)
        if key in b.seen:
            return 0, newest
        b.seen.add(key)
    return getattr(entry_st, "st_blocks", 0) * 512, newest


# ---------------------------------------------------------------- git (read-only questions)
def _git(root, args, stdin=b"", deadline=None):
    """Run one read-only git question. Output is read as it comes and git is killed once it passes LISTING_CAP (None = "could not be read"); the call is also
    killed after GIT_TIMEOUT seconds, or earlier when `deadline` (a time.monotonic() value, the project's own budget) comes sooner. Git never looks above the project's parent folder."""
    import threading
    argv = ["git", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null", "-c", "core.quotepath=false", "-C", root] + list(args)
    env = {k: os.environ[k] for k in ("PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR") if k in os.environ}
    env["GIT_OPTIONAL_LOCKS"] = "0"
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_CEILING_DIRECTORIES"] = os.path.dirname(os.path.abspath(root))
    limit = GIT_TIMEOUT if deadline is None else max(1.0, min(GIT_TIMEOUT, deadline - time.monotonic()))
    try:
        p = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, shell=False, env=env)
    except (OSError, subprocess.SubprocessError):
        return None
    chunks, flag = [], {"over": False}

    def reader():
        total = 0
        try:
            while True:
                c = os.read(p.stdout.fileno(), 65536)
                if not c:
                    return
                total += len(c)
                if total > LISTING_CAP:
                    flag["over"] = True
                    p.kill()
                    return
                chunks.append(c)
        except OSError:
            pass
    t = threading.Thread(target=reader, daemon=True)
    t.start()
    timer = threading.Timer(limit, p.kill)
    timer.daemon = True
    timer.start()
    try:
        try:
            if stdin:
                p.stdin.write(stdin)
        except OSError:
            pass
        finally:
            try:
                p.stdin.close()
            except OSError:
                pass
        t.join(limit + 2)
        try:
            rc = p.wait(timeout=2)
        except subprocess.TimeoutExpired:
            p.kill()
            return None
    finally:
        timer.cancel()
        if p.poll() is None:
            p.kill()
        t.join(2)
        try:
            p.stdout.close()
        except OSError:
            pass
    if flag["over"] or t.is_alive():
        return None
    return b"".join(chunks) if rc in (0, 1) else None


def _is_git(root) -> bool:
    return os.path.lexists(os.path.join(root, ".git"))


def nfc(s) -> str:
    return unicodedata.normalize("NFC", s)


def tracked_prefixes(root, deadline=None):
    """(set of tracked paths' first one and two components + the root-level files, ok). Tracked data decides "never"."""
    out = _git(root, ["ls-files", "-z"], deadline=deadline)
    if out is None:
        return set(), [], False
    pre, md = set(), []
    for p in out.split(b"\0"):
        if not p:
            continue
        full = nfc(p.decode("utf-8", "surrogateescape"))
        parts = full.split("/")
        pre.add(parts[0])
        if len(parts) > 2:
            pre.add(parts[0] + "/" + parts[1])
        elif len(parts) == 2:
            pre.add(full)
        if full.lower().endswith((".md", ".markdown")) and len(md) <= MD_FILES:
            md.append(full)
    return pre, md, True


def ignored_set(root, rels, deadline=None):
    """The subset of `rels` that .gitignore ignores (git check-ignore, read-only). None if git cannot answer."""
    if not rels:
        return set()
    out = _git(root, ["check-ignore", "-z", "--stdin"], stdin=("\0".join(rels) + "\0").encode("utf-8", "surrogateescape"), deadline=deadline)
    if out is None:
        return None
    return set(nfc(p.decode("utf-8", "surrogateescape")) for p in out.split(b"\0") if p)


# ---------------------------------------------------------------- doc links (items a tracked page points to are never swept)
def _read_small(root, rel):
    """(text, complete). complete is False when the file could not be read in full: not a regular file, bigger than MD_MAX, unreadable. A tracked file that is gone is complete (empty)."""
    path = os.path.join(root, rel)
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return "", True
    except OSError:
        return "", False
    if not stat.S_ISREG(st.st_mode):
        return "", False
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0))
    except OSError:
        return "", False
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return "", False
        data = os.read(fd, MD_MAX + 1)
        return data[:MD_MAX].decode("utf-8", "replace"), len(data) <= MD_MAX
    except OSError:
        return "", False
    finally:
        os.close(fd)


def link_targets(root, md_files):
    """(set of normalised relative paths named by links in the tracked markdown files, ok). Reads at most MD_FILES regular files of MD_MAX bytes and MD_TOTAL bytes in all.
    Understands [x](path), [x](<path with spaces>), reference lines `[x]: path`, HTML src/href, percent-encoding, a leading ./ and #fragment/?query."""
    out, total, ok = set(), 0, True
    if len(md_files) > MD_FILES:
        ok = False                       # more pages than the cap: the rest are not read
    for rel in md_files[:MD_FILES]:
        txt, full = _read_small(root, rel)
        ok = ok and full
        total += len(txt)
        base = os.path.dirname(rel)
        for rx in LINK_RES:
            for m in rx.finditer(txt):
                t = urllib.parse.unquote(m.group(1).strip()).split("#")[0].split("?")[0]
                if not t or "://" in t or t.startswith(("/", "mailto:", "data:", "tel:", "~")) or "\x00" in t:
                    continue
                norm = nfc(os.path.normpath(os.path.join(base, t)))
                if norm == "." or norm.startswith(".."):
                    continue
                out.add(norm)
                if len(out) >= LINKS_CAP:
                    return out, False
        if total > MD_TOTAL:
            return out, False
    return out, ok


def link_index(targets):
    """(targets, every ancestor folder of a target): an item is protected when a link names it, names something inside it, or names a folder above it."""
    anc = set()
    for t in targets:
        parts = t.split("/")
        for i in range(1, len(parts)):
            anc.add("/".join(parts[:i]))
    return targets, anc


def linked(rel, idx) -> bool:
    targets, anc = idx
    if rel in targets or rel in anc:
        return True
    parts = rel.split("/")
    return any("/".join(parts[:i]) in targets for i in range(1, len(parts)))


# ---------------------------------------------------------------- classification
def _secret(name) -> bool:
    return any(fnmatch.fnmatch(name.lower(), g) for g in SECRET_GLOBS)


def _kind(st) -> str:
    m = st.st_mode
    return "dir" if stat.S_ISDIR(m) else "file" if stat.S_ISREG(m) else "link" if stat.S_ISLNK(m) else "special"


def _reg(path) -> bool:
    try:
        return stat.S_ISREG(os.lstat(path).st_mode)
    except OSError:
        return False


def _has_stack(root) -> bool:
    return any(_reg(os.path.join(root, f)) for f in STACK_FILES)


def _regen_ok(root, name) -> bool:
    if name in REGEN_MARKER:
        return any(_reg(os.path.join(root, f)) for f in REGEN_MARKER[name])
    if name in REGEN_INSIDE:
        return _reg(os.path.join(root, name, REGEN_INSIDE[name]))
    if name in REGEN_STACK:
        return _has_stack(root)
    return False


def _age_days(newest, now) -> int:
    return max(0, int((now - newest) // 86400))


def _item(rel, cls, kind, nbytes, newest, why, now, extra=None):
    d = {"path_rel": clean(rel), "class": cls, "kind": kind, "bytes": int(nbytes), "newest_mtime": int(newest), "age_days": _age_days(newest, now),
         "why": clean(why, 200), "preselected": False}
    if extra:
        d.update(extra)
    return d


def project_idle_days(root, now) -> int:
    newest = 0
    for rel in (".git/logs/HEAD", ".git/HEAD", "docs/STATUS.md"):
        try:
            newest = max(newest, os.lstat(os.path.join(root, rel)).st_mtime)
        except OSError:
            pass
    return _age_days(newest, now) if newest else 9999


CLASS_ORDER = {"regenerable": 0, "disposable": 1, "review": 2, "never": 3}


class Sink:
    """Collects items with bounded memory: at most LIST_CAP kept per class (largest first); counts and bytes cover everything."""
    def __init__(self):
        self.items = {c: [] for c in CLASS_ORDER}
        self.counts = {c: 0 for c in CLASS_ORDER}
        self.bytes = {c: 0 for c in CLASS_ORDER}
        self.omitted = {c: 0 for c in CLASS_ORDER}

    def add(self, item):
        c = item["class"]
        self.counts[c] += 1
        self.bytes[c] += item["bytes"]
        lst = self.items[c]
        lst.append(item)
        if len(lst) >= 4 * LIST_CAP:
            self.trim(c)

    def trim(self, c):
        lst = self.items[c]
        lst.sort(key=lambda i: (-i["bytes"], i["path_rel"]))
        self.omitted[c] += max(0, len(lst) - LIST_CAP)
        del lst[LIST_CAP:]

    def finish(self):
        out = []
        for c in CLASS_ORDER:
            self.trim(c)
            out.extend(self.items[c])
        return out


def scan(root, max_entries=MAX_ENTRIES, max_seconds=MAX_SECONDS, now=None, max_top=MAX_TOP) -> dict:
    """Inspect the project folder `root` and return the report dict (see report_json). Reads only."""
    root = os.path.realpath(str(root))
    now = time.time() if now is None else now
    try:
        rst = os.lstat(root)
    except OSError:
        raise NotFound("cannot read %s" % clean(root))
    if not stat.S_ISDIR(rst.st_mode):
        raise UsageError("%s is not a folder" % clean(root))
    b = Budget(max_entries, max_seconds)
    git = _is_git(root)
    tracked, md_files, tracked_ok = tracked_prefixes(root, b.deadline) if git else (set(), [], False)
    lt, links_ok = link_targets(root, md_files) if tracked_ok else (set(), True)
    lidx = link_index(lt)
    idle = project_idle_days(root, now)
    notes, sugg = [], Sugg()
    if not git:
        notes.append("This folder is not a git repository, so nothing can be told apart as tracked or ignored. Nothing is offered for clean-up.")
    elif not tracked_ok:
        notes.append("Git could not be read, so tracked files are unknown. Nothing is offered for clean-up.")
    elif not links_ok:
        notes.append("Some documents were not read in full, so links from them may be missing: nothing is offered for clean-up.")

    cand = []                       # (name, lstat) of the top level, at most max_top
    try:
        it = os.scandir(root)
    except OSError:
        raise NotFound("cannot list %s" % clean(root))
    with it:
        for e in it:
            if len(cand) >= max_top or not b.tick():
                b.partial = True
                break
            try:
                cand.append((e.name, e.stat(follow_symlinks=False)))
            except OSError:
                continue
    cand.sort(key=lambda x: x[0])
    # children of the two folders with their own rules (opened without ever following a link)
    children = []
    for parent in (".scratch", ".claude/_backup"):
        try:
            pfd = open_path(root, parent)
        except OSError:
            continue
        try:
            with os.scandir(pfd) as it2:
                for e in it2:
                    if len(children) >= max_top or not b.tick():
                        b.partial = True
                        break
                    try:
                        children.append((parent + "/" + e.name, e.stat(follow_symlinks=False)))
                    except OSError:
                        continue
        except OSError:
            b.skip_unreadable(parent)
        finally:
            os.close(pfd)
    children.sort(key=lambda x: x[0])
    work = [(n, st) for n, st in cand if n != ".git"] + children
    ign = ignored_set(root, [r for r, _ in work], b.deadline) if git and tracked_ok else None
    can_judge = ign is not None and links_ok
    kept = {"small_or_recent": 0, "work_in_progress": 0, "tracked": 0}
    sink = Sink()
    backups = sorted([(r, st) for r, st in children if r.startswith(".claude/_backup/")], key=lambda x: -x[1].st_mtime)
    newest_backups = set(r for r, _ in backups[:BACKUP_KEEP])

    def _measure(rel, st):
        name = rel.rsplit("/", 1)[-1]
        b.secret = False
        b.incomplete = False
        if b.partial:
            b.incomplete = True
            return 0, st.st_mtime
        try:
            pfd = open_path(root, rel.rsplit("/", 1)[0] if "/" in rel else "")
        except OSError:
            b.skip_unreadable(rel)
            return 0, st.st_mtime
        try:
            return measure(st, name, pfd, rel, rst.st_dev, b)
        finally:
            os.close(pfd)

    for rel, st in work:
        name = rel.rsplit("/", 1)[-1]
        top_name = rel.split("/")[0]
        nrel = nfc(rel)
        kind = _kind(st)
        if rel == ".scratch" or rel == ".claude/_backup":
            continue                                   # containers: their children are judged one by one
        if nrel in tracked:
            kept["tracked"] += 1
            continue
        is_ignored = bool(ign and nrel in ign)
        protected = top_name in NEVER_NAMES and not rel.startswith(".claude/_backup/")
        listed = True
        if kind == "link":
            cls, why = "never", "a symbolic link: never followed"
        elif kind == "special":
            cls, why = "never", "not an ordinary file or folder (pipe, socket or device): never opened"
        elif _secret(name):
            cls, why = "never", "the name looks like a secret or key file"
        elif top_name in ONLY_COPY and "/" not in rel:
            cls, why = "never", "owner data kept on purpose; may be the only copy on this Mac"
        elif protected:
            cls, why, listed = "never", "a record or tool folder of the standard", False
        elif tracked_ok and linked(nrel, lidx):
            cls, why = "never", "a tracked page links to it"
        else:
            cls = None
        if cls == "never":
            nbytes, newest = (0, st.st_mtime)
            if listed:
                if kind == "dir" and (top_name in ONLY_COPY):
                    nbytes, newest = _measure(rel, st)
                sink.add(_item(rel, "never", kind, nbytes, newest, why, now))
            else:
                sink.counts["never"] += 1
            continue
        if not can_judge:
            continue
        nbytes, newest = _measure(rel, st)
        age = _age_days(newest, now)
        if b.secret:
            if is_ignored and _regen_ok(root, name):
                sink.add(_item(rel, "review", kind, nbytes, newest, "rebuildable, but it holds a secret-looking file (.env, key, certificate): check before removing", now))
            else:
                sink.add(_item(rel, "never", kind, nbytes, newest, "holds a secret-looking file (.env, key, certificate)", now))
            continue
        if b.incomplete:
            sink.add(_item(rel, "review", kind, nbytes, newest, "could not be checked completely (scan limit, unreadable or deep folder, or another disk): nothing is claimed about it", now, {"measured": False}))
            continue
        if rel.startswith(".scratch/"):
            if not DATED_RE.match(name):
                sugg.add("scratch_name", "%s is not named YYYY-MM-DD-<slug>; the sweep rule cannot date it by name." % clean(rel), "%d scratch items are not named YYYY-MM-DD-<slug>")
            if is_ignored and age > SCRATCH_DAYS:
                cls, why = "disposable", "scratch item untouched for %d days (standard: %d)" % (age, SCRATCH_DAYS)
            elif not is_ignored and age >= WIP_DAYS:
                cls, why = "review", "in .scratch, not ignored by git, %d days old" % age
            elif not is_ignored:
                kept["work_in_progress"] += 1
                continue
            else:
                kept["small_or_recent"] += 1
                continue
        elif rel.startswith(".claude/_backup/"):
            if rel not in newest_backups and age > BACKUP_DAYS and is_ignored:
                cls, why = "disposable", "template backup older than %d days, beyond the newest %d" % (BACKUP_DAYS, BACKUP_KEEP)
            elif rel not in newest_backups and age > BACKUP_DAYS:
                cls, why = "review", "template backup older than %d days, but not ignored by git" % BACKUP_DAYS
            else:
                kept["small_or_recent"] += 1
                continue
        elif is_ignored and _regen_ok(root, name):
            cls = "regenerable"
            why = "can be rebuilt; project idle %d days" % idle if idle >= IDLE_DAYS else "can be rebuilt, but the project is in use (active in the last %d days)" % IDLE_DAYS
        elif is_ignored or age >= WIP_DAYS:
            if nbytes > REVIEW_BYTES or age > REVIEW_DAYS:
                cls, why = "review", ("ignored" if is_ignored else "untracked") + ", %s, %d days old: only the owner can say" % (human_bytes(nbytes), age)
            else:
                kept["small_or_recent"] += 1
                continue
        else:
            kept["work_in_progress"] += 1
            continue
        extra = {"in_use": idle < IDLE_DAYS} if cls == "regenerable" else None
        sink.add(_item(rel, cls, kind, nbytes, newest, why, now, extra))

    standard_suggestions(root, cand, ign, git and can_judge, tracked, sugg)
    if b.partial:
        notes.append("The folder is very large: the scan stopped at its limit, so sizes are partial and unfinished items are marked 'needs your decision'.")
    if b.n_unreadable:
        notes.append("%d folder(s) could not be read and were skipped." % b.n_unreadable)
    items = sink.finish()
    sg, sg_omitted = sugg.result()
    return {"project": clean(os.path.basename(root)), "git": git, "partial": b.partial, "idle_days": idle if idle != 9999 else None,
            "entries_scanned": b.entries, "counts": sink.counts, "bytes": sink.bytes, "kept": kept, "items": items,
            "suggestions": sg, "unreadable": [clean(x) for x in b.unreadable], "other_volume": [clean(x) for x in b.other_volume], "notes": notes,
            "omitted": {"items": dict(sink.omitted), "suggestions": sg_omitted, "unreadable": max(0, b.n_unreadable - len(b.unreadable)), "other_volume": max(0, b.n_other - len(b.other_volume))}}


class Sugg:
    """Suggestions grouped by kind: the first few of each kind in full, the rest as one count line; at most LIST_CAP lines."""
    PER_KIND = 3

    def __init__(self):
        self.k = {}

    def add(self, kind, line, many):
        e = self.k.setdefault(kind, [[], 0, many])
        e[1] += 1
        if len(e[0]) < self.PER_KIND:
            e[0].append(line)

    def result(self):
        out, omitted = [], 0
        for kind, (lines, n, many) in self.k.items():
            out.extend(lines)
            if n > len(lines):
                out.append(many % n if "%d" in many else many + " (%d)" % n)
        omitted = max(0, len(out) - LIST_CAP)
        return out[:LIST_CAP], omitted


def standard_suggestions(root, cand, ign, judged, tracked, sg) -> None:
    """Plain-words suggestions against docs/standards/folders.md. Top level only; names only."""
    names = dict(cand)
    nv, vers = 0, []
    nz, zips = 0, []
    for n, s in cand:
        if n == ".git":
            continue
        if stat.S_ISDIR(s.st_mode) and VERSION_RE.match(n):
            nv += 1
            vers.append(n) if len(vers) < 3 else None
        if stat.S_ISREG(s.st_mode) and n.lower().endswith(ARCHIVE_EXT):
            nz += 1
            zips.append(n) if len(zips) < 3 else None
        if any(c.isspace() for c in n):
            sg.add("space", "%s has a space in its name: standard names use no spaces (use dashes)." % clean(n), "%d more top-level names have spaces")
        if stat.S_ISDIR(s.st_mode) and n.lower() in SHOT_DIRS:
            sg.add("shots", "%s at the top holds screenshots: the standard home is .scratch/<date>-<slug>/ (or tests/fixtures/ for golden shots)." % clean(n), "%d more screenshot folders at the top")
        if n.lower() == "reports" and stat.S_ISDIR(s.st_mode) and nfc(n) not in tracked:
            sg.add("reports", "reports/ is not tracked: QA output belongs in .scratch/<date>-<slug>/, written reports in docs/reports/.", "%d more")
        if "mock" in n.lower() and nfc(n) not in tracked:
            sg.add("mock", "%s looks like a mockup: approved ones go to design/, shown-to-owner ones to docs/summary/<date>-<slug>/." % clean(n), "%d more mockup-like names at the top")
    if nv >= 3:
        sg.add("versions", "%d version folders at the top (%s ...): move them into one ignored archive/ folder." % (nv, ", ".join(clean(v, 30) for v in vers)), "")
    if nz:
        sg.add("zips", "%d archive file(s) at the top (%s): keep them in archive/." % (nz, ", ".join(clean(z, 30) for z in zips)), "")
    if judged and ign is not None:
        for n in (".scratch", "archive", "backups"):
            if n in names and stat.S_ISDIR(names[n].st_mode) and n not in ign and n not in tracked:
                sg.add("ign_" + n, "%s/ is not ignored by git: add the line %s/ to .gitignore so it is never committed." % (n, n), "")


# ---------------------------------------------------------------- output
def report_json(rep: dict) -> dict:
    rep = dict(rep)
    # an item that was not fully measured has no real size or age: say null, never a real-looking number
    rep["items"] = [dict(i, bytes=None, age_days=None) if i.get("measured") is False else i for i in rep["items"]]
    return {k: rep[k] for k in ("project", "git", "partial", "idle_days", "entries_scanned", "counts", "bytes", "kept", "items", "suggestions", "unreadable", "other_volume", "notes", "omitted")}


_TITLES = (("regenerable", "Can be rebuilt (safe to remove when you do not need it now)"),
           ("disposable", "Throw-away by the standard (old scratch and backups)"),
           ("review", "Needs your decision (big or old, not clearly rebuildable)"),
           ("never", "Protected (never touched; listed so you know it exists)"))


def render(rep: dict, standard_only=False) -> str:
    L = ["Tidy report for %s (read-only: nothing was moved, deleted or written)." % rep["project"]]
    for n in rep["notes"]:
        L.append("Note: " + n)
    om = rep.get("omitted", {})
    if not standard_only:
        by = rep["bytes"]
        L.append("")
        L.append("Could be freed: %s rebuildable, %s throw-away. Needs your decision: %s. Protected: %s." % (
            human_bytes(by["regenerable"]), human_bytes(by["disposable"]), human_bytes(by["review"]), human_bytes(by["never"])))
        for cls, title in _TITLES:
            its = [i for i in rep["items"] if i["class"] == cls]
            if not its:
                continue
            L.append("")
            L.append("%s: %d in all" % (title, rep["counts"][cls]))
            for i in its[:15]:
                L.append("  - %s  %s: %s" % (i["path_rel"], "not fully measured" if i.get("measured") is False else "%s, %d days old" % (human_bytes(i["bytes"]), i["age_days"]), i["why"]))
            rest = rep["counts"][cls] - min(15, len(its))
            if rest > 0:
                L.append("  ... and %d more (use --json for the largest %d)" % (rest, LIST_CAP))
        k = rep["kept"]
        L.append("")
        L.append("Left alone and not listed: %d tracked, %d recent work-in-progress, %d small or recent." % (k["tracked"], k["work_in_progress"], k["small_or_recent"]))
    L.append("")
    if rep["suggestions"]:
        L.append("Against the folder standard (docs/standards/folders.md), suggestions only:")
        for x in rep["suggestions"]:
            L.append("  - " + x)
        if om.get("suggestions"):
            L.append("  ... and %d more" % om["suggestions"])
    else:
        L.append("Against the folder standard: nothing to suggest.")
    if rep["unreadable"]:
        L.append("Unreadable, skipped: " + ", ".join(rep["unreadable"][:10]) + (" ..." if len(rep["unreadable"]) > 10 or om.get("unreadable") else ""))
    if rep["other_volume"]:
        L.append("On another disk, not entered: " + ", ".join(rep["other_volume"][:10]) + (" ..." if len(rep["other_volume"]) > 10 or om.get("other_volume") else ""))
    if rep["partial"]:
        L.append("Partial: the scan hit its size/time limit.")
    return "\n".join(L)


def resolve_target(arg):
    """A project folder from a project name, a path, or (None) the folder the command runs in."""
    from . import projects
    if arg is None:
        p = projects.resolve(os.getcwd())
        if p is None:
            raise UsageError("not inside a project: give a project name or a folder path")
        return p.real
    if arg.startswith(("/", "~", ".")) or os.path.lexists(arg):      # a path that exists wins over a project name
        path = os.path.realpath(os.path.expanduser(arg))
        if not os.path.isdir(path):
            raise NotFound("no such folder: %s" % clean(arg))
        return path
    for p in projects.list_projects():
        if p.name == arg:
            return p.real
    raise NotFound("no project named %s" % clean(arg))


def run_cli(a) -> int:
    import sys
    from . import cli
    if getattr(a, "all", False) or getattr(a, "write", False) or getattr(a, "weekly", False):
        from . import tidyweekly
        return tidyweekly.run_cli(a)
    rep = scan(resolve_target(a.project))
    if a.json:
        cli._json({"tidy": report_json(rep)})
    else:
        sys.stdout.write(render(rep, standard_only=a.standard) + "\n")
    return 0
