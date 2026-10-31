"""Report lint (`shipm report lint FILE|--all`). Pure text checks against the fixed formats of templates.py:
header per kind; fields in a fixed order; at most 40 lines; a verdict word from the closed set; every Evidence line has a backticked command,
`->` and a number or file/sha reference; `Not verified:` present and not empty; Summary at most 3 lines; no hedging words; Decisions lines
well formed and Charter present when there are auto-decisions. Splits on "\\n" only (U+2028 and friends are not line breaks here), reads
UTF-8, never treats Arabic or other scripts specially."""
from __future__ import annotations

import re
from pathlib import Path

from .. import SafetyError, SchemaError, paths, state
from . import BANNED
from .templates import WORDS, evidence_ok

MAX_LINES = 40
MAX_BYTES = 64 * 1024
HEAD_STAGE = re.compile(r"# (CR-[0-9]{3,6}) · (.+?) · (PASS|FAIL|BLOCKED|NOT TESTED) {2,}([0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}) · (.+) \(([^()]+)\)")
HEAD_CR = re.compile(r"# (CR-[0-9]{3,6}) (.+) · (DELIVERED|ABANDONED) · (PASS|FAIL|BLOCKED|NOT TESTED)")
HEAD_DIGEST = re.compile(r"# Digest · ([0-9]{4}-[0-9]{2}-[0-9]{2})")
FIELDS = {
    "stage": (["Verdict", "Evidence", "Failed", "By", "Next", "Not verified"], {"Verdict", "Evidence", "By", "Next", "Not verified"}),
    "cr": (["Summary", "Stages", "Evidence", "Files", "Rollback", "Owner waits", "Charter", "Decisions", "Proposed assets", "Playbook fix", "Cost", "Not verified"],
           {"Summary", "Stages", "Evidence", "Files", "Rollback", "Owner waits", "Cost", "Not verified"}),
    "digest": (["Totals", "Not verified"], {"Totals", "Not verified"}),
}
_FIELD = re.compile(r"([A-Z][A-Za-z -]{1,20}): ?(.*)")
_PROJECT_LINE = re.compile(r"\S.* · [0-9]+ delivered( \(PASS\))? · .+")
_DECISION = re.compile(r"  [0-9]{2}:[0-9]{2} \S+ \S+ — .+")
_LINK_STRONG = re.compile(r"(?i)[a-z][a-z0-9+.-]{1,12}://|\bwww\.|\]\(|!\[|<\s*(?:a|img)\b|\bdata:[a-z]+/|\b[a-z0-9-]+\.(?:com|org|net|io|dev|app|ai|co|ru|cn|xyz|info|me)(?:/|\b)|\b[\w-]+\.[a-z]{2,}/\S*")
# file extensions are not domains: a name like app.py, README.md or notes.txt is a file reference (documented trade-off: evil.md / evil.py are not caught here)
_EXT = ("py|pyc|js|mjs|cjs|ts|tsx|jsx|md|json|jsonl|sh|bash|zsh|txt|html|htm|css|scss|yml|yaml|toml|lock|cfg|ini|conf|log|csv|tsv|png|jpg|jpeg|gif|svg|webp|ico|pdf|c|h|cc|cpp|go|rs|rb|java|kt|swift|sql|xml|plist|env|bak|tmp|diff|patch|zip|tar|gz|tgz|map|vue|php|pl|lua|r|ex|exs|cs")
_EXTS = frozenset(_EXT.split("|"))
_GTLD = frozenset("com org net edu gov mil int info biz name pro mobi asia tel travel jobs museum aero coop xxx app dev ai io xyz top club online site shop store tech cloud live link click page email blog "
                  "art fun life world today news space website host icu vip win bid loan work cyou rest fit agency zip mov tube porn sex adult casino bet poker".split())
_DOTTED = re.compile(r"[\w-]+(?:\.[\w-]+)+")
_IPV4 = re.compile(r"\b[0-9]{1,3}(?:\.[0-9]{1,3}){3}\b")
_AT = re.compile(r"[\w.+-]+@[\w-]+")
_CODE = re.compile(r"`[^`\n]*`")
_DOTS = str.maketrans({"。": ".", "｡": ".", "․": ".", "‧": ".", "﹒": ".", "．": "."})


class _Link:
    """`LINK.search(text)`: a URL, link, image, host name (also bare domains, IPs, e-mail shapes, ideographic dots; NFKC-folded first). Text inside `code spans` is
    checked for URL schemes and links only, so `os.path` or `a@b` in a command is fine."""
    def search(self, text):
        import unicodedata
        t = unicodedata.normalize("NFKC", str(text)).translate(_DOTS)
        if _LINK_STRONG.search(t):
            return True
        plain = _CODE.sub(" ", t)
        for m in _DOTTED.finditer(plain):
            raw = m.group(0).rsplit(".", 1)[1]
            last = raw.lower()
            if raw[:1].isupper() and raw[1:].islower():
                continue                                                      # "ok.Next sentence": a sentence run together, not a host
            if last in _EXTS or not re.fullmatch(r"[a-z]{2,}", last):         # the last label decides: login.rtl.test.ts is a file, a.test:1 a test name
                continue
            if len(last) == 2 or last in _GTLD:                               # every two-letter label is a country code; longer ones only from the list of real top-level domains
                return True
        return bool(_IPV4.search(plain) or _AT.search(plain))


LINK = _Link()
_CHARTER = re.compile(r"(ch-[0-9a-f]{4,12} .+|unknown .+)")


def lint_text(text) -> list:
    """List of problems (empty = clean)."""
    bad = []
    if not isinstance(text, str):
        return ["not text"]
    if "\r" in text:
        bad.append("carriage return in the file")
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    if len(lines) > MAX_LINES:
        bad.append("%d lines (max %d)" % (len(lines), MAX_LINES))
    if not lines:
        return bad + ["empty report"]
    head = lines[0]
    kind, hword = None, None
    for k, rx in (("stage", HEAD_STAGE), ("cr", HEAD_CR), ("digest", HEAD_DIGEST)):
        m = rx.fullmatch(head)
        if m:
            kind = k
            hword = m.group(3) if k == "stage" else m.group(4) if k == "cr" else None
            break
    if kind is None:
        return bad + ["header is not a stage, CR or digest header"]
    if hword is not None and hword not in WORDS:
        bad.append("verdict word %r" % hword)
    order, required = FIELDS[kind]
    seen, last_i, cur, body = {}, -1, None, lines[1:]
    for ln in body:
        if not ln.strip():
            bad.append("blank line")
            continue
        if ln.startswith("  "):
            if cur is None:
                bad.append("indented line before any field")
            else:
                seen[cur].append(ln)
            continue
        m = _FIELD.fullmatch(ln)
        if m and m.group(1) in order:
            f = m.group(1)
            i = order.index(f)
            if f in seen:
                if f != "Evidence":
                    bad.append("field %s twice" % f)
            elif i < last_i:
                bad.append("field %s out of order" % f)
            if f not in seen:
                seen[f] = []
            last_i = max(last_i, i)
            cur = f
            seen[f].append(ln)
        elif kind == "digest" and "Totals" not in seen and _PROJECT_LINE.fullmatch(ln):
            cur = None
        else:
            bad.append("unexpected line: %s" % ln[:60])
            cur = None
    for f in sorted(required - set(seen)):
        bad.append("missing field %s" % f)
    for ln in lines:
        if LINK.search(ln):
            bad.append("a link, URL, host name or image in: %s" % ln[:40])
            break
    for ln in body:
        if BANNED.search(ln):
            bad.append("banned wording: %s" % BANNED.search(ln).group(1).lower())
    for ln in seen.get("Evidence", []):
        if ln.startswith("Evidence:") and not evidence_ok(ln[len("Evidence:"):].strip()):
            bad.append("Evidence needs a `command` -> number or file reference")
    nv = seen.get("Not verified")
    if nv and not nv[0][len("Not verified:"):].strip():
        bad.append("Not verified is empty (write none if none)")
    if kind == "digest" and not any(_PROJECT_LINE.fullmatch(ln) for ln in body):
        bad.append("digest has no project line")
    if kind == "stage" and "Verdict" in seen:
        v = seen["Verdict"][0][len("Verdict:"):].strip()
        if not (v == hword or v.startswith(hword + " ")):
            bad.append("Verdict line does not match the header word")
    if kind == "cr":
        if "Summary" in seen and len(seen["Summary"]) > 3:
            bad.append("Summary is %d lines (max 3)" % len(seen["Summary"]))
        if any(LINK.search(x) for x in seen.get("Summary", [])):
            bad.append("Summary has a link, URL or image")
        ow = seen.get("Owner waits", [""])[0]
        m = re.search(r"Auto-decisions: ([0-9]+)", ow)
        if "Owner waits" in seen and not m:
            bad.append("Owner waits needs 'Auto-decisions: N'")
        n = int(m.group(1)) if m else 0
        if n and ("Decisions" not in seen or "Charter" not in seen):
            bad.append("auto-decisions need Charter and Decisions lines")
        if "Decisions" in seen:
            rows = seen["Decisions"][1:]
            if len(rows) > 10 + 0 or not rows:
                bad.append("Decisions has %d lines (1-10)" % len(rows))
            for r in rows:
                if not _DECISION.fullmatch(r) and not re.search(r"\(\+[0-9]+ more not shown\)$", r):
                    bad.append("bad Decisions line: %s" % r[:50])
        if "Charter" in seen and not _CHARTER.fullmatch(seen["Charter"][0][len("Charter:"):].strip()):
            bad.append("Charter line needs an id (ch-...) and goal, or 'unknown ...'")
    return bad


def lint_file(path) -> list:
    p = Path(path)
    try:
        raw = state.read_bytes_nofollow(p)
    except FileNotFoundError:
        return ["file not found"]
    except (SafetyError, SchemaError, OSError) as e:
        return ["unreadable: %s" % type(e).__name__]
    if len(raw) > MAX_BYTES:
        return ["file larger than %d KB" % (MAX_BYTES // 1024)]
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return ["not valid UTF-8"]
    return lint_text(text)


def all_files(project_dir=None, base=None) -> list:
    """Every report file we write: <project>/docs/reports/*.md, <state>/v1/reports/*/*.md, <state>/v1/digest/*.md."""
    b = Path(base) if base is not None else paths.state_dir()
    out = []
    if project_dir:
        out += sorted((Path(project_dir) / "docs" / "reports").glob("*.md"))
    out += sorted((b / "v1" / "reports").glob("*/*.md")) + sorted((b / "v1" / "digest").glob("*.md"))
    return out
