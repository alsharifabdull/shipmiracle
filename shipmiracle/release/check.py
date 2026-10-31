"""`shipm release-check`: read-only scan of an export tree (spec 2026-10-20-p8-spec.md section 3). Never prints, logs or stores matched text.

Checks (in output order): secrets/builtin, secrets/gitleaks, identifier, home-path, filetype, fixtures, closure, version.
A finding is (check, kind, file, line, col, h). `file` is the path inside the tree (replaced by <redacted:xxxxxxxx> when the path itself
matches the denylist); line/col are 1-based on the normalised text (col is approximate for non-ASCII lines), 0:0 for whole-file findings.
tree_sha: the git tree-object id of the tree contents, computed here in pure python (blobs/trees like `git write-tree`; mode 100755 when the
owner exec bit is set, 120000 for symlinks, `.git` at the root, nested repos and special files left out). It equals `git write-tree` of the
same files, so a tree identical to a commit's tree gets that commit's tree sha (one algorithm for work trees, archives and plain folders).
Hostile input: symlinks are never followed, FIFOs/devices are never opened, depth is capped (MAX_DEPTH), files above MAX_FILE and binary
files are not text-scanned (they are findings), the total scanned bytes are capped (BUDGET)."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import time
from pathlib import Path

from .. import NotFound, SafetyError, UsageError
from ..hooks.project import SECRET_RE
from . import denylist as dl

MAX_FILE = 320 * 1024                     # raised from 200 KB on 24 Oct 2026 (DECISIONS): the flow gate source (shipmiracle/hooks/flow.py) carries the isolation rules
NUL_WINDOW = 8192
# Brand pictures and the README pictures are the only binary files that may ship: PNG / ICO under brand/ (CHECKLIST L2), PNG in docs/images/, and only when the whole file is plain picture data:
# a PNG may hold only IHDR, PLTE, tRNS, IDAT and IEND chunks (CRC valid, IHDR first, IEND last, NOTHING after it), so no text/EXIF chunk or appended bytes can carry a
# value past the scan; an ICO must have its directory and every image inside the file, each image a strict PNG or a BMP whose size matches its header, and no trailing bytes.
BINARY_OK = re.compile(r"^(?:brand/(?:[^/]+/)?[^/]+\.(?:png|ico)|docs/images/[^/]+\.png)\Z")   # \Z, not $ ($ also matches before a trailing newline in the name); + the README pictures (docs/images/*.png, DECISIONS 2026-10-31): same strict PNG rule
_MAGIC = {"png": b"\x89PNG\r\n\x1a\n", "ico": b"\x00\x00\x01\x00"}
_PNG_CHUNKS = (b"IHDR", b"PLTE", b"tRNS", b"IDAT", b"IEND")


def png_clean(d):
    """True only for a PNG made of the allowed chunks with valid CRCs and no byte after IEND."""
    import struct
    import zlib
    if not d.startswith(_MAGIC["png"]):
        return False
    p, n, first, seen_idat = 8, len(d), True, False
    while p + 12 <= n:
        (ln,) = struct.unpack(">I", d[p:p + 4])
        t = d[p + 4:p + 8]
        end = p + 12 + ln
        if t not in _PNG_CHUNKS or end > n or (first and t != b"IHDR") or (t == b"IHDR" and (not first or ln != 13)):
            return False
        if struct.unpack(">I", d[end - 4:end])[0] != (zlib.crc32(d[p + 4:end - 4]) & 0xFFFFFFFF):
            return False
        first = False
        seen_idat = seen_idat or t == b"IDAT"
        p = end
        if t == b"IEND":
            return ln == 0 and p == n and seen_idat
    return False


def ico_clean(d):
    """True only for an ICO whose directory and images lie inside the file, each image a strict PNG or a size-consistent BMP, with no trailing bytes."""
    import struct
    if len(d) < 22 or not d.startswith(_MAGIC["ico"]):
        return False
    (cnt,) = struct.unpack("<H", d[4:6])
    if not 1 <= cnt <= 16 or 6 + 16 * cnt > len(d):
        return False
    top = 6 + 16 * cnt
    spans = []
    for i in range(cnt):
        w, h, _c, res, _pl, _bp, size, off = struct.unpack("<BBBBHHII", d[6 + 16 * i:22 + 16 * i])
        if res != 0 or size < 8 or off < top or off + size > len(d):
            return False
        img = d[off:off + size]
        if img.startswith(_MAGIC["png"]):
            if not png_clean(img):
                return False
        else:
            if size < 40:
                return False
            bsz, bw, bh, planes, bpp, comp, _isz, _x, _y, used, _imp = struct.unpack("<IiiHHIIiiII", img[:40])
            if bsz != 40 or planes != 1 or comp != 0 or bpp not in (1, 4, 8, 24, 32) or bw < 1 or bw > 256 or bh != 2 * (h or 256) or bw != (w or 256):
                return False
            pal = 4 * ((used or (1 << bpp)) if bpp <= 8 else used)
            if 40 + pal + ((bw * bpp + 31) // 32) * 4 * (bh // 2) + ((bw + 31) // 32) * 4 * (bh // 2) != size:
                return False
        spans.append((off, off + size))
    spans.sort()
    return all(spans[k][1] <= spans[k + 1][0] for k in range(len(spans) - 1)) and spans[-1][1] == len(d)


def brand_image_clean(rel, d):
    return bool(BINARY_OK.match(rel)) and (png_clean(d) if rel.endswith(".png") else ico_clean(d))
MAX_DEPTH = 64
BUDGET = 1 << 30
CHECKS = ("secrets/builtin", "secrets/gitleaks", "identifier", "home-path", "filetype", "fixtures", "closure", "isolation", "legacy_name", "version")
HANDLE_FILES = ("LICENSE", "README", "SECURITY", "CONTRIBUTING")
# The owner's PUBLIC GitHub login (the denylist's `user` entry that equals a `handle` entry) is allowed ONLY at these exact files, each with the
# owner decision that put it there. This table lives in the engine on purpose: nothing in the exported tree can add a path to it.
LOGIN_EXEMPT = {
    "LICENSE": "DECISIONS 2026-10-21, D1 (license holder is the public login)",
    "README.md": "DECISIONS 2026-10-27, owner (D1 login in the overlay files)",
    ".github/CODEOWNERS": "DECISIONS 2026-10-27, owner (D1 login in the overlay files)",
    ".github/ISSUE_TEMPLATE/config.yml": "DECISIONS 2026-10-27, owner (D1 login in the overlay files)",
}
DEFAULT_PLACEHOLDERS = ("x", "example", "someone", "you", "a.b", "some.other-user", "<owner>", "$USER")
STATE_NAMES = frozenset(["registry.json", "release-denylist.txt", "install-manifest.json", "shipmiracle_state.json"])
EXEC_OK = re.compile(r"^(bin/|hooks/|\.githooks/|templates/(.+/)?(\.githooks|hooks)/|tests/[^/]+\.sh\Z|tests/fakes/)")   # \Z: no match before a trailing newline in the name
# legacy_name (rename 2026-10-21): the old working name must not be in a public export: not as text (any case, also its env and label forms), not in a path.
# Spelled in two pieces so that this file does not carry the word either.
LEGACY_RE = re.compile("a" "iw", re.I)
VERSION_RE = re.compile(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.+-]+)?")
LINE_CAP = 200          # FAIL lines printed per check (the JSON keeps JSON_CAP in total)
JSON_CAP = 2000

_SPECIFIC = re.compile("|".join([
    r"(?P<github_pat>github_pat_[A-Za-z0-9_]{20,})",
    r"(?P<github_token>\bgh[ousr]_[A-Za-z0-9]{20,})",
    r"(?P<anthropic_key>sk-ant-[A-Za-z0-9_-]{10,})",
    r"(?P<openai_project_key>sk-proj-[A-Za-z0-9_-]{10,})",
    r"(?P<google_api_key>AIza[0-9A-Za-z_-]{35})",
]))
_HOME_RE = re.compile(r"/users/(<[A-Za-z_-]+>|\$\{?[A-Za-z_]+\}?|[A-Za-z0-9._@+~-]+)", re.I)
_ANCHOR = r"(?:@SHIPMIRACLE_ENGINE@|\$\{?(?:SHIPMIRACLE_ENGINE|ENGINE|WS|SHIPMIRACLE_WS|ENGINE_DIR)\}?)/"
_BIN_RE = re.compile(r"(?:(?<![\w.~/$@-])(?:\./)?|" + _ANCHOR + r")bin/([A-Za-z0-9][\w.+-]*)")
_SH_RE = re.compile(r"(?:(?<![\w.~/$@-])(?:\./)?|" + _ANCHOR + r")hooks/([A-Za-z0-9][\w.-]*\.sh)\b")
_DOCS_RE = re.compile(_ANCHOR + r"(docs/(?:STATUS\.md|DECISIONS\.md|ACCEPTANCE\.md|FEATURE-IDEAS\.md|parity\.md|"
                      r"(?:plans|baseline|golden|memory|owner-steps|status-archive)(?=[/\s\"'`)]|$)|standards/known))")


class Finding(object):
    __slots__ = ("check", "kind", "file", "line", "col", "h", "note")

    def __init__(self, check, kind, file=None, line=0, col=0, h=None, note=None):
        self.check, self.kind, self.file, self.line, self.col, self.h, self.note = check, kind, file, line, col, h, note

    def key(self):
        return (CHECKS.index(self.check), self.file or "", self.line, self.col, self.kind, self.h or "")

    def as_dict(self):
        return {"check": self.check, "kind": self.kind, "file": self.file, "line": self.line, "col": self.col, "h": self.h}

    def text(self):
        s = "FAIL %s kind=%s" % (self.check, self.kind)
        if self.h:
            s += " h=%s" % self.h
        if self.file is not None:
            s += " %s:%d:%d" % (_clean(self.file), self.line, self.col)
        if self.note:
            s += " (%s)" % self.note
        return s


def _clean(s):
    return re.sub(r"[^\x20-\x7e¡-\U0010ffff]", "?", s).encode("utf-8", "replace").decode("utf-8", "replace")


class Inputs(object):
    """Everything release-check reads besides the tree. None = not available yet (that check prints a SKIP line)."""

    def __init__(self, placeholders=None, fixtures=None, version=None, changelog=None, notes=None, closure_exempt=None):
        self.placeholders = placeholders        # set of strings, or None (built-in list used)
        self.fixtures = fixtures                # {path: sha256}, or None
        self.version = version                  # text of release/VERSION, or None
        self.changelog = changelog              # text of the overlay CHANGELOG, or None
        self.notes = notes or {}                # check -> why an input is missing
        self.closure_exempt = closure_exempt or []   # [(path, target, line fragment)] reviewed closure exemptions (release/closure-exempt.txt)


def _read_text(p):
    try:
        return Path(p).read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return None


def load_inputs(release_dir) -> Inputs:
    """Read the documented defaults from <release_dir> (release/placeholders.txt, fixtures-reviewed.txt, VERSION, overlay/CHANGELOG.md)."""
    rd = Path(release_dir) if release_dir is not None else None
    inp = Inputs()
    t = _read_text(rd / "placeholders.txt") if rd else None
    if t is None:
        inp.notes["home-path"] = "release/placeholders.txt not found; built-in placeholder list used"
    else:
        inp.placeholders = set(l.strip() for l in t.splitlines() if l.strip() and not l.lstrip().startswith("#"))
    t = _read_text(rd / "fixtures-reviewed.txt") if rd else None
    if t is None:
        inp.notes["fixtures"] = "release/fixtures-reviewed.txt not found"
    else:
        inp.fixtures = parse_fixtures(t)
    t = _read_text(rd / "VERSION") if rd else None
    if t is None:
        inp.notes["version"] = "release/VERSION not found"
    else:
        inp.version = t.strip()
    inp.changelog = _read_text(rd / "overlay" / "CHANGELOG.md") if rd else None
    t = _read_text(rd / "closure-exempt.txt") if rd else None
    if t is not None:
        inp.closure_exempt = parse_closure_exempt(t)
    return inp


def load_inputs_for_tree(tree, release_dir) -> Inputs:
    """Inputs for checking `tree`: the files of <tree>/release/ (closure-exempt.txt, fixtures-reviewed.txt, VERSION, placeholders.txt) win when present, the
    workspace's release/ folder fills what the tree does not carry. This makes release-check self-sufficient on an exported tree (the public CI runs it
    with --tree . where release/ holds only the shipped copies) and in an empty workspace."""
    base = load_inputs(release_dir)
    tr = Path(tree) / "release"
    if not tr.is_dir() or tr.is_symlink():
        return base
    mine = load_inputs(tr)
    mine.changelog = None
    out = Inputs(placeholders=mine.placeholders if mine.placeholders is not None else base.placeholders,
                 fixtures=mine.fixtures if mine.fixtures is not None else base.fixtures,
                 version=mine.version if mine.version is not None else base.version,
                 changelog=base.changelog,
                 closure_exempt=mine.closure_exempt if (tr / "closure-exempt.txt").is_file() else base.closure_exempt)
    for k, v in base.notes.items():
        if (k == "home-path" and out.placeholders is not None) or (k == "fixtures" and out.fixtures is not None) or (k == "version" and out.version is not None):
            continue
        out.notes[k] = v
    return out


def parse_closure_exempt(text):
    """release/closure-exempt.txt: '<file path> | <referenced target> | <text the referencing line must contain>' per line (# comments).
    Line numbers are never part of an entry, so the entry survives edits elsewhere in the file. Every entry is a reviewed exception to the
    closure rule (a prose reference to a file the export does not carry)."""
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) != 3 or not all(parts) or parts[0].startswith("/") or ".." in parts[0].split("/"):
            raise UsageError("closure-exempt.txt line %d is not '<path> | <target> | <line text>'" % n)
        out.append((parts[0], parts[1], parts[2]))
    return out


def parse_fixtures(text):
    out = {}
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = line.strip().split(None, 1)
        if len(parts) != 2 or not re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
            raise UsageError("fixtures-reviewed.txt line %d is not '<sha256> <path>'" % n)
        out[parts[1].strip()] = parts[0].lower()
    return out


# ---------------------------------------------------------------- gitleaks seam
def gitleaks_binary():
    """Path of the gitleaks executable or None. Under SHIPMIRACLE_TEST=1 the env SHIPMIRACLE_GITLEAKS_BIN replaces the PATH lookup (a missing file = not installed)."""
    if os.environ.get("SHIPMIRACLE_TEST") == "1" and "SHIPMIRACLE_GITLEAKS_BIN" in os.environ:
        p = os.environ["SHIPMIRACLE_GITLEAKS_BIN"]
        return p if p and os.access(p, os.X_OK) else None
    return shutil.which("gitleaks")


def run_gitleaks(tree, binary, timeout=300):
    """('missing'|'ok'|'error', [(rule, file, line, col)], note). Only RuleID/File/StartLine/StartColumn are kept; the report file is
    in a private 0700 folder and deleted; gitleaks' own output is discarded."""
    if not binary:
        return "missing", [], "gitleaks not installed"
    tmp = tempfile.mkdtemp(prefix="shipmiracle-gl-")
    try:
        os.chmod(tmp, 0o700)
        rep = os.path.join(tmp, "r.json")
        common = ["--redact", "--no-banner", "--report-format", "json", "--report-path", rep]
        rc = None
        for argv in ([binary, "dir", str(tree)] + common, [binary, "detect", "--no-git", "--source", str(tree)] + common):
            try:
                r = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout, shell=False)
            except (OSError, subprocess.SubprocessError):
                return "error", [], "gitleaks could not run"
            rc = r.returncode
            if rc in (0, 1):
                break
        if rc not in (0, 1):
            return "error", [], "gitleaks failed (exit %s)" % rc
        items = []
        if os.path.exists(rep):
            try:
                data = json.loads(open(rep, "rb").read().decode("utf-8", "replace") or "null")
            except ValueError:
                return "error", [], "gitleaks report unreadable"
            for it in data or []:
                if not isinstance(it, dict):
                    continue
                rule = re.sub(r"[^A-Za-z0-9_.-]", "_", str(it.get("RuleID", "rule")))[:40] or "rule"
                f = str(it.get("File", ""))
                try:
                    rel = os.path.relpath(f, os.path.realpath(str(tree))) if os.path.isabs(f) else f
                except ValueError:
                    rel = f
                line = it.get("StartLine") if isinstance(it.get("StartLine"), int) else 0
                col = it.get("StartColumn") if isinstance(it.get("StartColumn"), int) else 0
                items.append((rule, rel, line, col))
        elif rc == 1:
            return "error", [], "gitleaks reported leaks but wrote no report"
        return "ok", items, ""
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- the scan
class Report(object):
    def __init__(self):
        self.findings, self.passes, self.skipped = [], {}, []
        self.files = 0
        self.tree_sha = None
        self.result = "PASS"
        self.truncated = False

    def counts(self):
        by = {}
        for f in self.findings:
            by[f.check] = by.get(f.check, 0) + 1
        return {"findings": len(self.findings), "files": self.files, "by_check": by}

    def lines(self):
        out = []
        for c in CHECKS:
            fs = [f for f in self.findings if f.check == c]
            if fs:
                for f in fs[:LINE_CAP]:
                    out.append(f.text())
                if len(fs) > LINE_CAP:
                    out.append("FAIL %s ... %d more findings not shown (use --json)" % (c, len(fs) - LINE_CAP))
            elif c in self.passes:
                out.append(("PASS %s %s" % (c, self.passes[c])).rstrip())
            for sc, why in self.skipped:
                if sc == c:
                    out.append("SKIP %s (%s)" % (c, why))
        out.append("RESULT %s findings=%d files=%d tree=%s" % (self.result, len(self.findings), self.files, self.tree_sha))
        return out

    def as_dict(self):
        return {"result": self.result, "tree_sha": self.tree_sha, "counts": self.counts(),
                "findings": [f.as_dict() for f in self.findings[:JSON_CAP]], "truncated": len(self.findings) > JSON_CAP,
                "skipped": [{"check": c, "reason": w} for c, w in self.skipped]}


def _classify_generic(s):
    t = s.lower()
    if t.startswith("sk-"):
        return "api_key_sk"
    if t.startswith("akia"):
        return "aws_access_key"
    if t.startswith("ghp_"):
        return "github_token"
    if t.startswith("xox"):
        return "slack_token"
    if t.startswith("-----begin"):
        return "private_key"
    return "assignment"


def _lc(text, off):
    return text.count("\n", 0, off) + 1, off - (text.rfind("\n", 0, off) + 1) + 1


def handle_allowed(rel):
    parts = rel.split("/")
    if parts[0] == ".github":
        return True
    if len(parts) == 1:
        u = parts[0].upper()
        return any(u in (b, b + ".MD", b + ".TXT") for b in HANDLE_FILES)
    return False


def _filetype_kind(rel, name):
    b = name.lower()
    if b.endswith(".jsonl"):
        return "jsonl"
    if b.endswith(".log"):
        return "log"
    if b.endswith((".db", ".sqlite", ".sqlite3")):
        return "database"
    if b.endswith(".plist"):
        return "plist"
    if re.match(r"^\.env($|\.)", b) and b != ".env.example":
        return "env_file"
    if b.endswith((".pem", ".key", ".p12")):
        return "key_file"
    if b == ".ds_store":
        return "ds_store"
    if b.endswith(".pyc"):
        return "pyc"
    if rel.endswith(".shipmiracle/work.json") or rel == ".shipmiracle/work.json" or name in STATE_NAMES:
        return "state_file"
    return None


def _tree_obj(entries):
    entries = sorted(entries, key=lambda e: e[0] + (b"/" if e[1] == b"40000" else b""))
    body = b"".join(m + b" " + n + b"\0" + s for n, m, s in entries)
    return hashlib.sha1(b"tree %d\0" % len(body) + body).digest()


def scan(tree, inputs=None, deny=None, deny_required=False, require_gitleaks=False, gitleaks=None, deny_skip_reason=None, require_login=False):
    """Scan `tree` (a folder). deny: dl.Denylist or None. gitleaks: callable(tree) -> (status, items, note) or None (= missing)."""
    root = os.path.realpath(str(tree))
    if not os.path.isdir(root):
        raise NotFound("tree %s is not a folder" % tree)
    inputs = inputs or Inputs()
    rep = Report()
    F = rep.findings
    matcher = dl.Matcher(deny) if deny is not None else None
    placeholders = set(p.lower() for p in (inputs.placeholders if inputs.placeholders is not None else DEFAULT_PLACEHOLDERS))
    disp_cache = {}

    def disp(rel):
        if matcher:
            d = disp_cache.get(rel)
            if d is None:
                hit = matcher.search_norm(dl.norm(rel))
                d = "<redacted:%s>" % hashlib.sha256(rel.encode("utf-8", "replace")).hexdigest()[:8] if hit else rel
                disp_cache[rel] = d
            return d
        return rel

    files = set()
    fixtures_seen = {}
    refs = []                                   # closure candidates: (rel, line, col, kind, target)
    dir_entries = {"": []}
    dir_children = {"": []}
    order = [""]
    stack = [("", 0)]
    spent = 0
    while stack:
        drel, depth = stack.pop()
        dpath = os.path.join(root, drel) if drel else root
        try:
            it = sorted(os.scandir(dpath), key=lambda e: e.name)
        except OSError:
            F.append(Finding("filetype", "unreadable", disp(drel or "."), 0, 0))
            continue
        for e in it:
            name = e.name
            rel = drel + "/" + name if drel else name
            if drel == "" and name == ".git":
                continue
            try:
                st = e.stat(follow_symlinks=False)
            except OSError:
                F.append(Finding("filetype", "unreadable", disp(rel), 0, 0))
                continue
            mode = st.st_mode
            fname = os.fsencode(name)
            if stat.S_ISLNK(mode):
                files.add(rel)
                rep.files += 1
                F.append(Finding("filetype", "symlink", disp(rel), 0, 0))
                try:
                    dir_entries[drel].append((fname, b"120000", _blob_sha(os.fsencode(os.readlink(e.path)))))
                except OSError:
                    pass
                _path_hits(rel, disp, matcher, F)
                continue
            if stat.S_ISDIR(mode):
                if name == ".git" or os.path.lexists(os.path.join(e.path, ".git")):
                    F.append(Finding("filetype", "submodule", disp(rel), 0, 0))
                    continue
                if depth + 1 > MAX_DEPTH:
                    F.append(Finding("filetype", "depth", disp(rel), 0, 0))
                    continue
                dir_entries[rel] = []
                dir_children[drel].append((fname, rel))
                dir_children[rel] = []
                order.append(rel)
                stack.append((rel, depth + 1))
                _path_hits(rel, disp, matcher, F)
                continue
            rep.files += 1
            files.add(rel)
            _path_hits(rel, disp, matcher, F)
            if not stat.S_ISREG(mode):
                F.append(Finding("filetype", "special_file", disp(rel), 0, 0))
                continue
            _file(rel, name, e.path, st, root, dir_entries[drel], F, disp, matcher, placeholders, inputs, refs, fixtures_seen,
                  budget=BUDGET - spent)
            spent += min(st.st_size, MAX_FILE)
            if name == ".gitmodules":
                F.append(Finding("filetype", "submodule", disp(rel), 0, 0))
    # tree sha, children before parents
    shas = {}
    for drel in reversed(order):
        ents = list(dir_entries[drel])
        for fname, crel in dir_children[drel]:
            if crel in shas and shas[crel] is not None:
                ents.append((fname, b"40000", shas[crel]))
        shas[drel] = _tree_obj(ents) if (ents or drel == "") else None
    rep.tree_sha = shas[""].hex()

    # closure
    exempt = inputs.closure_exempt
    used = set()
    for rel, line, col, kind, target, ltext in refs:
        if ltext is not None:
            hit = [i for i, (ep, et, ef) in enumerate(exempt) if ep == rel and et == target and ef in ltext]
            if hit:
                used.update(hit)
                continue
        if kind == "docs":
            ok = any(f == target or f.startswith(target.rstrip("/") + "/") for f in files)
        else:
            ok = target in files
        if not ok:
            F.append(Finding("closure", {"bin": "missing_bin", "hook": "missing_hook", "docs": "private_doc"}[kind], disp(rel), line, col))
    rep.passes["secrets/builtin"] = "%d files scanned" % rep.files
    rep.passes["home-path"] = "(%s)" % inputs.notes["home-path"] if inputs.notes.get("home-path") else ""
    rep.passes["filetype"] = ""
    rep.passes["isolation"] = ""
    rep.passes["legacy_name"] = ""
    stale = len(exempt) - len(used)
    rep.passes["closure"] = ("(%d reviewed exemption%s used%s)" % (len(used), "" if len(used) == 1 else "s", ", %d unused" % stale if stale else "")) if exempt else ""

    # identifier
    if matcher:
        rep.passes["identifier"] = "%d denylist entries" % len(deny.entries) + (
            " (%d reviewed login exemption%s used)" % (len(matcher.login_used), "" if len(matcher.login_used) == 1 else "s") if matcher.login_used else "")
    elif deny_required:
        F.append(Finding("identifier", "denylist_missing", None, note="--require-denylist: " + (deny_skip_reason or "no denylist on this machine")))
    else:
        rep.skipped.append(("identifier", deny_skip_reason or "no denylist on this machine"))

    # --require-login: the literal login placeholder (the word login in angle brackets) must be replaced (owner step, docs/standards/repo-settings.md section 7) before the first public export
    if require_login:
        for dp, dn, fn in os.walk(root):
            dn[:] = [x for x in dn if x != ".git"]
            for n_ in fn:
                fp = os.path.join(dp, n_)
                try:
                    if os.path.islink(fp) or os.path.getsize(fp) > MAX_FILE:
                        continue
                    with open(fp, "rb") as fh:
                        raw_ = fh.read()
                except OSError:
                    continue
                at = raw_.find(b"<" + b"login" + b">")
                if at >= 0 and b"\0" not in raw_[:NUL_WINDOW]:
                    ln_, col_ = _lc(raw_.decode("utf-8", "replace"), at)
                    F.append(Finding("identifier", "login_placeholder", disp(os.path.relpath(fp, root).replace(os.sep, "/")), ln_, col_))
        rep.passes.setdefault("identifier", "")

    # gitleaks
    status, items, note = gitleaks(root) if gitleaks else ("missing", [], "gitleaks not installed")
    if status == "ok":
        for rule, f, line, col in items:
            F.append(Finding("secrets/gitleaks", rule, disp(f), line, col))
        rep.passes["secrets/gitleaks"] = ""
    elif require_gitleaks:
        F.append(Finding("secrets/gitleaks", "unavailable" if status == "error" else "missing", None, note="--require-gitleaks: " + note))
    else:
        rep.skipped.append(("secrets/gitleaks", note))

    # fixtures
    fx = inputs.fixtures
    if fx is None:
        if fixtures_seen:
            rep.skipped.append(("fixtures", inputs.notes.get("fixtures", "no reviewed-fixtures list")))
        else:
            rep.passes["fixtures"] = "0/0 reviewed"
    else:
        good = 0
        for rel, sha in sorted(fixtures_seen.items()):
            want = fx.get(rel)
            if want is None:
                F.append(Finding("fixtures", "unreviewed", disp(rel), 0, 0))
            elif want != sha:
                F.append(Finding("fixtures", "changed", disp(rel), 0, 0))
            else:
                good += 1
        stale = len([p for p in fx if p not in fixtures_seen])
        rep.passes["fixtures"] = "%d/%d reviewed%s" % (good, len(fixtures_seen), " (%d stale entries in the list)" % stale if stale else "")

    _version(root, files, inputs, rep)
    F.sort(key=Finding.key)
    seen, uniq = set(), []
    for f in F:
        k = (f.check, f.kind, f.file, f.line, f.col, f.h)
        if k not in seen:
            seen.add(k)
            uniq.append(f)
    rep.findings[:] = uniq
    rep.result = "FAIL" if rep.findings else "PASS"
    return rep


def _blob_sha(data):
    return hashlib.sha1(b"blob %d\0" % len(data) + data).digest()


def _path_hits(rel, disp, matcher, F):
    if not matcher:
        return
    nrel = dl.norm(rel)
    for kind, h, off in matcher.search_norm(nrel):
        if kind == "handle" and handle_allowed(rel):
            continue
        F.append(Finding("identifier", kind, disp(rel), 0, 0, h))


def _line_text(text, off):
    a = text.rfind("\n", 0, off) + 1
    b = text.find("\n", off)
    return text[a:b if b >= 0 else len(text)]


def _file(rel, name, path, st, root, ents, F, disp, matcher, placeholders, inputs, refs, fixtures_seen, budget):
    d = disp(rel)
    if LEGACY_RE.search(rel):
        F.append(Finding("legacy_name", "old_name_in_path", d, 0, 0))
    fk = _filetype_kind(rel, name)
    if fk:
        F.append(Finding("filetype", fk, d, 0, 0))
    if st.st_mode & 0o111 and not EXEC_OK.match(rel):
        F.append(Finding("filetype", "exec_bit", d, 0, 0))
    want_sha256 = rel.startswith("tests/fixtures/")
    size = st.st_size
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    except OSError:
        F.append(Finding("filetype", "unreadable", d, 0, 0))
        return
    data = b""
    try:
        h1 = hashlib.sha1(b"blob %d\0" % size)
        h256 = hashlib.sha256() if want_sha256 else None
        total = 0
        with os.fdopen(fd, "rb") as f:
            while True:
                chunk = f.read(1 << 20)
                if not chunk:
                    break
                total += len(chunk)
                h1.update(chunk)
                if h256:
                    h256.update(chunk)
                if len(data) < MAX_FILE + 1:
                    data += chunk[:MAX_FILE + 1 - len(data)]
    except OSError:
        F.append(Finding("filetype", "unreadable", d, 0, 0))
        return
    if total == size:                           # a file that changed while we read it keeps no tree entry
        ents.append((os.fsencode(name), b"100755" if st.st_mode & 0o100 else b"100644", h1.digest()))
    if h256:
        fixtures_seen[rel] = h256.hexdigest()
    if size > MAX_FILE:
        F.append(Finding("filetype", "too_large", d, 0, 0))
        return
    if budget <= 0:
        F.append(Finding("filetype", "scan_budget_exceeded", d, 0, 0))
        return
    if b"\0" in data[:NUL_WINDOW]:
        if size <= MAX_FILE and brand_image_clean(rel, data):
            return                              # a brand picture that is nothing but picture data (strict chunk / directory check above): no text to scan
        F.append(Finding("filetype", "binary", d, 0, 0))
        return
    text = data.decode("utf-8", "replace")
    for m in LEGACY_RE.finditer(text):
        line, col = _lc(text, m.start())
        F.append(Finding("legacy_name", "old_name", d, line, col))
    # secrets/builtin
    for m in _SPECIFIC.finditer(text):
        line, col = _lc(text, m.start())
        F.append(Finding("secrets/builtin", m.lastgroup, d, line, col))
    for m in SECRET_RE.finditer(text):
        line, col = _lc(text, m.start())
        F.append(Finding("secrets/builtin", _classify_generic(m.group(0)), d, line, col))
    # home-path
    low = text.lower()
    if "/users/" in low:
        for m in _HOME_RE.finditer(text):
            who = m.group(1).lower()
            if who not in placeholders:
                line, col = _lc(text, m.start())
                F.append(Finding("home-path", "home_path", d, line, col))
    for kind, line, col in isolation_issues(rel, text):
        F.append(Finding("isolation", kind, d, line, col))
    # closure candidates
    if ("bin/" in text or "hooks/" in text or "docs/" in text) and rel not in ("release/closure-exempt.txt", "release/fixtures-reviewed.txt", "release/placeholders.txt"):
        ex_here = any(e[0] == rel for e in inputs.closure_exempt)
        lt = (lambda m: _line_text(text, m.start())) if ex_here else (lambda m: None)
        for m in _BIN_RE.finditer(text):
            nm = m.group(1).rstrip(".-+")
            nxt = text[m.end():m.end() + 1]
            if nm and nxt not in ("*", "<", "{", "[", "?", "$"):
                refs.append((rel,) + _lc(text, m.start()) + ("bin", "bin/" + nm, lt(m)))
        for m in _SH_RE.finditer(text):
            refs.append((rel,) + _lc(text, m.start()) + ("hook", "hooks/" + m.group(1), lt(m)))
        for m in _DOCS_RE.finditer(text):
            refs.append((rel,) + _lc(text, m.start()) + ("docs", m.group(1), lt(m)))
    # identifier
    if matcher:
        nt = dl.norm(text)
        for kind, h, off in matcher.search_norm(nt):
            if kind == "handle" and handle_allowed(rel):
                continue
            if rel in LOGIN_EXEMPT and (kind, h) in matcher.login_hashes:
                matcher.login_used.add(rel)
                continue
            line, col = _lc(nt, off)
            F.append(Finding("identifier", kind, d, line, col, h))


# ---------------------------------------------------------------- isolation lint (21 Oct 2026)
# A test that can reach the user's real files must not ship. DETECTION (exact, on the text of every tests/** file except tests/fixtures/, tests/fakes/, tests/private/):
#   LAUNCH  = the file starts processes: subprocess / Popen / os.system / os.exec* / os.spawn* / child_process / execFileSync / execSync / spawnSync / spawn( / execFile(
#   TARGET  = the file names an Shipmiracle tool or hook as a path: bin/<name> or hooks/<name> (also "bin", "<name>" and / "bin" / "<name>" spellings), or runs `-m shipmiracle`
#   A file with LAUNCH and TARGET is "executing Shipmiracle" and must be ISOLATED, which means ONE of:
#     (a) it uses a shared helper: its text mentions shipmiracle_isolation, shipmiracle_timing, chrome_helper, setup_fixture or one of the *_fixture helpers that wrap them; or
#     (b) it sets the whole sandbox itself: SHIPMIRACLE_TEST, SHIPMIRACLE_HOME, SHIPMIRACLE_STATE, SHIPMIRACLE_CONFIG and HOME all appear in its text.
#   BROWSER = the file spawns a browser: spawn/execFile/Popen of CHROME / chrome... / a path naming Google Chrome, Chromium or chrome-headless. It must use tests/chrome_helper.js
#   (the helper adds the safe flags, kills the whole process group and removes the profile); no inline alternative.
# The helpers themselves are exempt. Findings: isolation / unisolated_exec, unisolated_browser (file:line of the first launch).
ISO_HELPERS = ("shipmiracle_isolation", "shipmiracle_timing", "chrome_helper", "setup_fixture")
ISO_HELPER_FILES = frozenset(["tests/shipmiracle_isolation.py", "tests/shipmiracle_isolation.js", "tests/shipmiracle_timing.py", "tests/chrome_helper.js", "tests/setup_fixture.py",
                              "tests/flow_fixture.py", "tests/autopilot_engine_fixture.py", "tests/autopilot_hook_fixture.py"])     # fixtures imported by tests, which pass them their own env
_LAUNCH = re.compile(r"subprocess\b|create_subprocess_\w+|\bPopen\b|os\.system\b|os\.popen\b|os\.exec\w*|os\.spawn\w*|child_process|\bchildProcess\b|execFileSync|execSync|spawnSync|\bspawn\(|\bexecFile\(|\b(?:cp|child_process|childProcess)\.exec\(")
_TARGET = re.compile(r"""(?:\b(?:bin|hooks)\b["']?\s*(?:/|,)\s*["']?[A-Za-z][\w.-]*|["']\s*/\s*["'](?:bin|hooks)["']\s*/\s*["'][A-Za-z]|-m\s+shipmiracle\b|["']-m["']\s*,\s*["']shipmiracle\b)""")
_BROWSER = re.compile(r"""(?:\bspawn|spawnSync|execFile|execFileSync|\bPopen)\(\s*(?:CHROME\b|chrome\w*\b|[\"'`][^\"'`]*(?:Google Chrome|[Cc]hromium|chrome-headless)[^\"'`]*[\"'`])""")
_SANDBOX = ("SHIPMIRACLE_TEST", "SHIPMIRACLE_HOME", "SHIPMIRACLE_STATE", "SHIPMIRACLE_CONFIG")


def _strip_comments(text, rel):
    """`text` without comments and (python) triple-quoted blocks, so a helper or sandbox variable that is only MENTIONED there never counts as isolation (L10).
    Crude on purpose: a scan per line that tracks quotes; it only ever removes text, so it can make a file look LESS isolated, never more."""
    py, js = rel.endswith(".py"), rel.endswith((".js", ".mjs", ".cjs"))
    if py:
        text = re.sub(r'(?s)("""|\'\'\').*?\1', " ", text)
    elif js:
        text = re.sub(r"(?s)/\*.*?\*/", " ", text)
    out = []
    for line in text.split("\n"):
        q = None
        i = 0
        cut = len(line)
        while i < len(line):
            c = line[i]
            if q:
                if c == "\\":
                    i += 1
                elif c == q:
                    q = None
            elif c in "\"'" or (js and c == "`"):
                q = c
            elif (py or not js) and c == "#" and (py or i == 0 or line[i - 1] in " \t"):
                cut = i
                break
            elif js and c == "/" and line[i:i + 2] == "//":
                cut = i
                break
            i += 1
        out.append(line[:cut])
    return "\n".join(out)


def _uses_helper(code, names, rel):
    """The (comment-free) code imports / requires / sources one of the helper modules `names`."""
    alt = "|".join(re.escape(n) for n in names)
    if rel.endswith(".py"):
        return re.search(r"(?m)(?:^|[;\s])(?:import|from)\s+[^\n;]*?\b(?:%s)\b" % alt, code) is not None
    if rel.endswith(".sh"):
        return re.search(r"(?m)^\s*(?:source|\.)\s+\S*(?:%s)" % alt, code) is not None
    return re.search(r"require\(\s*[\"'`][^\"'`]*(?:%s)[^\"'`]*[\"'`]\s*\)|\bfrom\s+[\"'][^\"']*(?:%s)|\bimport\s*\(?\s*[\"'][^\"']*(?:%s)" % (alt, alt, alt), code) is not None


def _sets_var(code, name):
    """The code ASSIGNS `name`: NAME=..., NAME: ..., ["NAME"] = ..., .NAME = ... (a bare mention in a string or message does not)."""
    return re.search(r"(?<![A-Za-z0-9_])%s[\"'`]?\s*\]?\s*(?:=(?!=)|:)" % re.escape(name), code) is not None


def _code_mask(text, js):
    """list of bool, one per character: True where the character is code (not inside a comment or the body of a string literal; an opening quote counts as code).
    Crude scanner for python (# comments, ' " and triple quotes) and js (// and /* */ comments, ' " and `)."""
    n = len(text)
    mask = [True] * n
    i = 0
    while i < n:
        c = text[i]
        if js and text.startswith("//", i) or (not js and c == "#"):
            j = text.find("\n", i)
            j = n if j < 0 else j
            for k in range(i, j):
                mask[k] = False
            i = j
        elif js and text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            for k in range(i, j):
                mask[k] = False
            i = j
        elif c in "\"'" or (js and c == "`"):
            q = text[i:i + 3] if (not js and text[i:i + 3] in ('"""', "'''")) else c
            j = i + len(q)
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text.startswith(q, j) or (len(q) == 1 and q != "`" and text[j] == "\n"):
                    break
                j += 1
            end = min(n, j + len(q))
            for k in range(i + 1, end):
                mask[k] = False
            i = end
        else:
            i += 1
    return mask


def _py_env_names(tree):
    """(imported module names, environment-variable names the code SETS) from a python AST: keyword arguments (dict(os.environ, SHIPMIRACLE_TEST=..), env.update(SHIPMIRACLE_TEST=..)),
    dict keys ({"SHIPMIRACLE_TEST": ..}) and subscript assignments (env["SHIPMIRACLE_TEST"] = ..)."""
    import ast
    mods, names = set(), set()
    for nd in ast.walk(tree):
        if isinstance(nd, ast.Import):
            mods.update(a.name.split(".")[0] for a in nd.names)
        elif isinstance(nd, ast.ImportFrom) and nd.module:
            mods.add(nd.module.split(".")[0])
            mods.update(a.name for a in nd.names)
        elif isinstance(nd, ast.keyword) and nd.arg:
            names.add(nd.arg)
        elif isinstance(nd, ast.Dict):
            names.update(k.value for k in nd.keys if isinstance(k, ast.Constant) and isinstance(k.value, str))
        elif isinstance(nd, (ast.Assign, ast.AugAssign)):
            for t in (nd.targets if isinstance(nd, ast.Assign) else [nd.target]):
                if isinstance(t, ast.Subscript):
                    sl = t.slice.value if isinstance(t.slice, getattr(ast, "Index", ())) else t.slice
                    if isinstance(sl, ast.Constant) and isinstance(sl.value, str):
                        names.add(sl.value)
    return mods, names


def _isolated(rel, text):
    """(helper_used, whole_sandbox_set) judged on CODE only: python through ast, js through a quote/comment-aware scan, shell on comment-free text."""
    if rel.endswith(".py"):
        import ast
        try:
            mods, names = _py_env_names(ast.parse(text))
        except (SyntaxError, ValueError):
            code = _strip_comments(text, rel)        # unparsable (a newer syntax): the crude text rules, never more lenient than before
            return _uses_helper(code, ISO_HELPERS, rel), all(_sets_var(code, t) for t in _SANDBOX) and _sets_var(code, "HOME")
        return bool(mods & set(ISO_HELPERS)), all(t in names for t in _SANDBOX) and "HOME" in names
    if rel.endswith((".js", ".mjs", ".cjs")):
        mask = _code_mask(text, True)
        alt = "|".join(re.escape(h) for h in ISO_HELPERS)
        helper = any(mask[m.start()] for m in re.finditer(r"require\(\s*[\"'`][^\"'`]*(?:%s)[^\"'`]*[\"'`]\s*\)|\bfrom\s+[\"'][^\"']*(?:%s)|\bimport\s*\(?\s*[\"'][^\"']*(?:%s)" % (alt, alt, alt), text))

        def sets(name):
            for m in re.finditer(r"(?<![A-Za-z0-9_])%s(?![A-Za-z0-9_])\s*(?:\]\s*)?(?::|=(?!=))|([\"'`])%s\1\s*(?:\]\s*)?(?::|=(?!=))" % (name, name), text):
                if mask[m.start()]:
                    return True
            return False
        return helper, all(sets(t) for t in _SANDBOX) and sets("HOME")
    code = _strip_comments(text, rel)
    return _uses_helper(code, ISO_HELPERS, rel), all(_sets_var(code, t) for t in _SANDBOX) and _sets_var(code, "HOME")


def _chrome_helper(rel, text, code):
    if rel.endswith(".py"):
        import ast
        try:
            return "chrome_helper" in _py_env_names(ast.parse(text))[0]
        except (SyntaxError, ValueError):
            pass
    elif rel.endswith((".js", ".mjs", ".cjs")):
        mask = _code_mask(text, True)
        return any(mask[m.start()] for m in re.finditer(r"require\(\s*[\"'`][^\"'`]*chrome_helper[^\"'`]*[\"'`]\s*\)|\bfrom\s+[\"'][^\"']*chrome_helper|\bimport\s*\(?\s*[\"'][^\"']*chrome_helper", text))
    return _uses_helper(code, ("chrome_helper",), rel)


def isolation_issues(rel, text):
    """[(kind, line, col)] for one tests/** file (see the detection rules above); [] when it is fine or not a test."""
    if (not rel.startswith("tests/") or rel in ISO_HELPER_FILES or rel.startswith(("tests/fixtures/", "tests/fakes/", "tests/private/"))
            or not rel.endswith((".py", ".js", ".mjs", ".cjs", ".sh"))):
        return []
    out = []
    lm = _LAUNCH.search(text)
    bm = _BROWSER.search(text)
    code = _strip_comments(text, rel)
    if bm and not _chrome_helper(rel, text, code):
        out.append(("unisolated_browser",) + _lc(text, bm.start()))
    if lm and _TARGET.search(text):
        helper, full = _isolated(rel, text)
        if not (helper or full):
            out.append(("unisolated_exec",) + _lc(text, lm.start()))
    return out


def _version(root, files, inputs, rep):
    src = None
    if "shipmiracle/__init__.py" in files:
        t = _read_text(os.path.join(root, "shipmiracle", "__init__.py")) or ""
        m = re.search(r"^__version__\s*=\s*['\"]([^'\"]+)['\"]", t, re.M)
        src = m.group(1) if m else None
    clog = None
    if "CHANGELOG.md" in files:
        t = _read_text(os.path.join(root, "CHANGELOG.md"))
    else:
        t = inputs.changelog
    if t is not None:
        for m in re.finditer(r"^##\s+\[?([^\]\s]+)\]?", t, re.M):
            if m.group(1).lower() != "unreleased":
                clog = m.group(1)
                break
    ver = inputs.version.strip() if inputs.version else None
    have = [("shipmiracle/__init__.py", src), ("CHANGELOG", clog), ("release/VERSION", ver)]
    miss = [n for n, v in have if v is None]
    got = [(n, v) for n, v in have if v is not None]
    if len(got) < 2:
        rep.skipped.append(("version", "need two of shipmiracle/__init__.py __version__, overlay CHANGELOG, release/VERSION; missing: " + ", ".join(miss)))
        return
    bad = [n for n, v in got if not VERSION_RE.fullmatch(v)]
    if bad:
        rep.findings.append(Finding("version", "bad_format", None, note="not x.y.z: " + ", ".join(bad)))
        return
    if len(set(v for _, v in got)) > 1:
        rep.findings.append(Finding("version", "mismatch", None, note="versions differ: " + ", ".join("%s=%s" % g for g in got)))
        return
    rep.passes["version"] = got[0][1] + (" (missing: %s)" % ", ".join(miss) if miss else "")


def write_stamp(rep, flags, state_base=None):
    """<state>/v1/release/check-<tree_sha>.json for a PASS (read by the pre-push guard). Atomic, 0600, folder 0700. Returns the path."""
    from .. import paths, state
    if rep.result != "PASS":
        raise UsageError("stamps are written for a PASS only")
    paths.assert_isolated(state_base or paths.state_dir())
    r = state.ensure_root(state_base)
    d = state.ensure_dir(r / "release")
    p = d / ("check-%s.json" % rep.tree_sha)
    body = {"v": 1, "result": "PASS", "tree_sha": rep.tree_sha, "ts": int(time.time()), "files": rep.files,
            "skipped": [c for c, _ in rep.skipped], "flags": flags}
    state.atomic_write(p, (json.dumps(body, sort_keys=True, indent=1) + "\n").encode("utf-8"))
    return p
