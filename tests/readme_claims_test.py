#!/usr/bin/env python3
"""The public README and tester docs (release/overlay in the private repository, the root of an exported tree) must not promise what the tool does not have:
 - every `shipm <command>` in a code span or code block names a command that `shipm --help` lists, and every --flag in that span is shown by
   `shipm <command> --help` (or by the top-level help);
 - every relative link and image points to a file that is in the overlay (a short list of FUTURE pictures, captured at release time, is allowed and must
   still be referenced); every #anchor names a heading of the same file;
 - the OWNER-CONFIRM markers are counted and printed, so nobody forgets to resolve them.
`shipm` runs only with the full isolation environment of tests/shipmiracle_isolation.py (fresh HOME, config, state, workspace). Python 3.9, standard library.
Run: python3 tests/readme_claims_test.py"""
import os, pathlib, re, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import shipmiracle_isolation as ISO  # noqa: E402

OVERLAY = ROOT / "release" / "overlay"
BASE = OVERLAY if (OVERLAY / "README.md").is_file() else ROOT          # an exported tree has the overlay files at its root
DOCS = ["README.md", "SUPPORT.md", "CONTRIBUTING.md", "SECURITY.md", "CODE_OF_CONDUCT.md"] + sorted(
    str(p.relative_to(BASE)) for p in (BASE / "docs").glob("*.md"))
# Pictures that do not exist yet: none since 31 Oct 2026 (the README pictures are real renders in docs/images/); every missing picture is a failure.
FUTURE = set()

passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print("PASS", name)
    else:
        failed += 1
        print("FAIL", name, str(detail)[:600])


ENV, TMP = ISO.isolated_env(ws=ROOT)
ENV.pop("CLAUDECODE", None)
_help_cache = {}


def shipm_help(*args):
    key = tuple(args)
    if key not in _help_cache:
        r = subprocess.run([sys.executable, str(ROOT / "bin" / "shipm")] + list(args) + ["--help"], env=ENV, cwd=str(ROOT), stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, timeout=120)
        _help_cache[key] = (r.returncode, r.stdout)
    return _help_cache[key]


def commands_of(top):
    """Command names listed in `shipm --help` (the lines indented by four spaces under COMMAND)."""
    return set(m.group(1) for m in re.finditer(r"^ {4}([a-z][a-z-]*)\b", top, re.M))


def code_lines(text):
    """Text of inline code spans and of fenced code block lines."""
    out, fenced = [], False
    for ln in text.splitlines():
        if ln.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            out.append(ln.split("  #")[0].strip())
        else:
            out.extend(re.findall(r"`([^`\n]+)`", ln))
    return out


SHIPM_RE = re.compile(r"(?<![\w/.-])(?:\./)?(?:bin/)?shipm(?:\s+([a-z][a-z-]*))?((?:\s+\S+)*)$")


def shipm_uses(text):
    for span in code_lines(text):
        for part in re.split(r"\s*(?:&&|\|\||;|\|)\s*", span):
            m = SHIPM_RE.match(part.strip())
            if m and m.group(1):
                yield m.group(1), re.findall(r"(?<![\w-])(--[a-z][a-z-]*)", m.group(2) or ""), part.strip()


def slug(h):
    s = re.sub(r"[^\w\s-]", "", h.strip().lower())
    return re.sub(r"\s", "-", s)


texts = {}
for d in DOCS:
    p = BASE / d
    check("file exists: " + d, p.is_file())
    if p.is_file():
        texts[d] = p.read_text(encoding="utf-8")

rc, top = shipm_help()
CMDS = commands_of(top)
check("shipm --help works and lists commands", rc == 0 and len(CMDS) > 20, (rc, top[:200]))

bad_cmd, bad_flag, n_uses = [], [], 0
for d, t in texts.items():
    for cmd, flags, span in shipm_uses(t):
        n_uses += 1
        if cmd not in CMDS:
            bad_cmd.append("%s: %s" % (d, span))
            continue
        if flags:
            _, h = shipm_help(cmd)
            for f in flags:
                if f not in h and f not in top:
                    bad_flag.append("%s: %s (%s)" % (d, span, f))
check("docs name %d shipm commands; every command exists" % n_uses, not bad_cmd and n_uses > 10, bad_cmd[:5])
check("every flag used with a shipm command is in that command's --help", not bad_flag, bad_flag[:5])

LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)\)|(?:src|srcset|href)=\"([^\"]+)\"")
bad_link, future_seen, n_links = [], set(), 0
for d, t in texts.items():
    here = (BASE / d).parent
    body = re.sub(r"<!--.*?-->", "", t, flags=re.S)             # links inside comments are not shown
    heads = set(slug(h) for h in re.findall(r"^#{1,6}\s+(.+)$", body, re.M))
    for m in LINK_RE.finditer(body):
        tgt = m.group(1) or m.group(2)
        if re.match(r"[a-z][a-z0-9+.-]*:", tgt) or "<" in tgt:
            continue
        n_links += 1
        path, _, frag = tgt.partition("#")
        if not path:
            if frag and frag not in heads:
                bad_link.append("%s: #%s" % (d, frag))
            continue
        full = (here / path).resolve()
        if not full.is_file() and BASE == OVERLAY and (ROOT / path).is_file() and path.startswith("brand/"):
            full = (ROOT / path).resolve()               # the brand folder sits at the root of the exported tree, not in the overlay
        rel = os.path.relpath(str(full), str(BASE)) if str(full).startswith(str(BASE)) else path
        if rel in FUTURE:
            future_seen.add(rel)
            continue
        if not full.is_file():
            bad_link.append("%s: %s" % (d, tgt))
        elif frag and full.suffix == ".md":
            fh = set(slug(h) for h in re.findall(r"^#{1,6}\s+(.+)$", full.read_text(encoding="utf-8"), re.M))
            if frag not in fh:
                bad_link.append("%s: %s#%s" % (d, path, frag))
check("%d relative links and images resolve to files in the overlay (or a listed future picture)" % n_links, not bad_link and n_links > 15, bad_link[:8])
check("no placeholder picture is allowed any more: every picture the README shows exists", future_seen == FUTURE == set())
_readme_body = re.sub(r"<!--.*?-->", "", texts.get("README.md", ""), flags=re.S)
_shipped = sorted(p.name for p in (BASE / "docs" / "images").glob("*") if p.is_file())
_unused = [n for n in _shipped if "docs/images/" + n not in _readme_body]
check("docs/images holds %d pictures and the README uses every one (no orphan picture ships)" % len(_shipped), len(_shipped) >= 9 and not _unused, _unused)
_big = [n for n in _shipped if (BASE / "docs" / "images" / n).stat().st_size > 320 * 1024]
check("every README picture is a PNG under release-check's 320 KB file limit, except the one strict-clean animated header.gif", all(n.endswith(".png") or n == "header.gif" for n in _shipped) and not [n for n in _big if n != "header.gif"], _big)
check("the how-it-works diagram files exist", all((BASE / "docs" / "assets" / f).is_file() for f in ("how-it-works-light.svg", "how-it-works-dark.svg")))

markers = sum(t.count("OWNER-CONFIRM") for t in texts.values())      # the README's first comment is a maintainer note and does not use the marker word
print("INFO OWNER-CONFIRM markers (owner decisions) open in the public docs:", markers)
check("the maintainer comment at the top of the README does not count as a decision marker", "OWNER-CONFIRM" not in texts.get("README.md", "").split("-->", 1)[0])

# Linux / WSL 2 must never be called "supported" anywhere in the public files while the label is experimental (a line pair is judged together, wrapping).
TEXT_EXT = (".md", ".yml", ".yaml", ".txt", ".json", ".sh")
if OVERLAY.is_dir() and (OVERLAY / "README.md").is_file():
    scan = [p for p in OVERLAY.rglob("*") if p.is_file() and p.suffix in TEXT_EXT]
else:
    scan = [p for p in list(BASE.glob("*.md")) + list((BASE / "docs").glob("*.md")) + list((BASE / ".github").rglob("*")) if p.is_file() and p.suffix in TEXT_EXT]
PLAT = re.compile(r"\b(?:linux|wsl ?2)\b", re.I)
SUP = re.compile(r"(?<!not )(?<!un)\bsupported\b", re.I)


def linux_supported_lines(text):
    ls = text.splitlines()
    for i, ln in enumerate(ls):
        win = ln + " " + (ls[i + 1] if i + 1 < len(ls) else "")
        win = re.sub(r"supported systems", "", win, flags=re.I)             # the section name is not a claim
        if PLAT.search(ln) and SUP.search(win) and "experimental" not in win.lower() and "not supported" not in win.lower():
            yield i + 1, ln.strip()[:120]


bad_sup = ["%s:%d %s" % (os.path.relpath(str(p), str(BASE)), n, s) for p in scan for n, s in linux_supported_lines(p.read_text(encoding="utf-8", errors="replace"))]
check("no public file (%d scanned) calls Linux or WSL 2 supported without 'experimental'" % len(scan), not bad_sup and len(scan) > 15, bad_sup[:5])
check("self-test: the Linux rule catches a bad line and passes a good one", bool(list(linux_supported_lines("| Linux (Ubuntu) | Supported | x |")))
      and not list(linux_supported_lines("Linux is experimental; Windows native is not supported."))
      and not list(linux_supported_lines("Linux and WSL 2: experimental")))
_heads = set(re.findall(r"^#{2,3}\s+(.+?)\s*$", _readme_body, re.M))
_need = ("Supported systems", "Requirements", "What it changes (exact list)", "Uninstall", "Safety model", "Limitations", "Install", "How it works", "Features", "FAQ")
check("README still has the sections the tests and docs rely on (as headings)", all(h in _heads for h in _need), [h for h in _need if h not in _heads])
# Owner wording rules (31 Oct 2026): production for everyone, no verified / not-verified points, no tester or invite wording, no "runs on your Mac", no old slogan sentence.
_BANNED = [r"not verified", r"\bverified\b", r"\bunverified\b", r"\btesters?\b", r"\bbeta\b", r"\binvite", r"\bprivate (?:repo|beta|preview|release)", r"nothing ships without your word",
           r"runs on your mac", r"not yet been installed", r"until a stranger"]
_hits = [b for b in _BANNED if re.search(b, _readme_body, re.I)]
check("README has no tester / invite / verified wording, no 'runs on your Mac' and no old slogan sentence", not _hits, _hits)
# Positioning (owner decision 31 Oct 2026): the product manages and organizes ALL your AI projects; the old headline "Claude Code, now with a team." is retired.
# The headline is set inside the light-only header picture, so it is the first words of that picture's alt text; there is no second h1 and no dark header.
_hdr = re.findall(r"<img\b[^>]*docs/images/header\.gif[^>]*>", _readme_body)
import html as _html  # noqa: E402
_hdr_alt = _html.unescape(re.search(r'alt="([^"]*)"', _hdr[0]).group(1)) if len(_hdr) == 1 else ""
_hdr_gif = BASE / "docs" / "images" / "header.gif"
_hdr_bytes = _hdr_gif.read_bytes() if _hdr_gif.is_file() else b""
check("README header: exactly one reference to docs/images/header.gif, a single <img> (no <picture>/dark source), width 100%, alt (one paragraph) names the headline and the subline",
      len(_hdr) == 1 and 'width="100%"' in _hdr[0] and _hdr_gif.is_file() and "All your AI projects, organized." in _hdr_alt
      and "One place to start, track and finish every project you build with AI agents." in _hdr_alt and "\n" not in _hdr_alt
      and "<picture>" not in _readme_body.split("</p>", 1)[0] and "srcset" not in _readme_body.split("</p>", 1)[0], (len(_hdr), _hdr_alt[:80]))
sys.path.insert(0, str(ROOT))
from shipmiracle.release import check as _chk  # noqa: E402
check("the animated header passes the strict gif_clean rule and is at most 4.5 MB", _chk.gif_clean(_hdr_bytes) and 0 < len(_hdr_bytes) <= 4.5 * 1024 * 1024, len(_hdr_bytes))
check("the old still header.png is gone (the GIF is the only header picture)", not (BASE / "docs" / "images" / "header.png").exists() and "header.png" not in _readme_body)
check("old banners are gone: no banner-*.png in docs/images or in the README, and the old headline is retired",
      not list((BASE / "docs" / "images").glob("banner*")) and "banner" not in _readme_body and "now with a team" not in _readme_body.lower() and "<h1" not in _readme_body, "banner or old headline left")
check("README intro says it manages and organizes all your AI projects (plans, approvals, memory, status)",
      "Shipmiracle keeps every project you build with AI agents in one VS Code panel, with plans, approvals, memory and status for each project." in _readme_body
      and "One place for every project." in _readme_body)
check("README names the ten roles and the 44 features in 7 groups", _readme_body.count("<details>") == 7 + 5
      and sum(1 for ln in _readme_body.splitlines() if re.match(r"\| \*\*.+\*\* \|", ln)) == 44, (_readme_body.count("<details>"),))
check("README says it runs locally on macOS, Linux and WSL 2 with Linux and WSL 2 experimental", "Runs locally on macOS, Linux and Windows (through WSL 2); Linux and WSL 2 are experimental." in _readme_body)
check("README's three shipm install commands are the documented ones", re.search(r"git clone https://github\.com/[A-Za-z0-9-]+/shipmiracle ~/Developer/shipmiracle\ncd ~/Developer/shipmiracle\n\./bin/shipm init\n", _readme_body) is not None)   # no literal login here: the login is allowed only in README/LICENSE/.github, not in tests
check("README states the Linux label (owner confirmed Experimental, 24 Oct)", "Linux and WSL 2: experimental" in texts.get("README.md", ""))

ISO.cleanup(TMP)
print("readme_claims_test: %d passed, %d failed" % (passed, failed))
sys.exit(1 if failed else 0)
