#!/usr/bin/env python3
"""Public website (website/): static checks, no browser. The page follows the 2026-11-01 positioning ("All your AI projects, organized."), the old
"Claude Code, now with a team" framing is gone, the social image is a clean 2400x1260 PNG, every local reference resolves, nothing loads from
another origin, the owner's GitHub login lives in index.html only, the theme default is light (no system dark switching) and the toggle exists.
The browser check (computed colours with an emulated dark system) is tests/website_ui_test.js.
Reads files only. Python 3.9, standard library. Run: python3 tests/website_test.py"""
import pathlib, re, struct, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from shipmiracle.release.check import png_clean  # noqa: E402  the same strict rule release-check applies

W = ROOT / "website"
passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
    else:
        failed += 1
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(detail)[:400]))


def read(rel):
    return (W / rel).read_text(encoding="utf-8")


check("website folder and its core files exist", all((W / f).is_file() for f in ("index.html", "404.html", "styles.css", "theme.js", "site.js")), W)
html, css, theme_js, site_js, nf = read("index.html"), read("styles.css"), read("theme.js"), read("site.js"), read("404.html")


def meta(attr, key):
    m = re.search(r'<meta\s+%s="%s"\s+content="([^"]*)"' % (attr, re.escape(key)), html)
    return m.group(1) if m else None


def text_of(fragment):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", fragment)).strip()


# ---------------------------------------------------------------- positioning
low = html.lower()
check("no 'now with a team' anywhere in index.html", "now with a team" not in low)
check("no 'team manager' anywhere in index.html", "team manager" not in low)
check("no 'ship it with miracles' left over", "ship it with miracles" not in low)
check("no 'Runs on your Mac'", not re.search(r"runs on your mac\b", low))
h1 = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
check("h1 is 'All your AI projects, organized.'", bool(h1) and text_of(h1.group(1)) == "All your AI projects, organized.", h1 and text_of(h1.group(1)))
lead = re.search(r'<p class="lead">(.*?)</p>', html, re.S)
check("hero subline is the approved sentence", bool(lead) and text_of(lead.group(1)) == "One place to start, track and finish every project you build with AI agents.")
title = re.search(r"<title>(.*?)</title>", html, re.S)
check("title carries the positioning", bool(title) and "All your AI projects, organized" in title.group(1), title and title.group(1))
for attr, key in (("name", "description"), ("property", "og:title"), ("property", "og:description"), ("name", "twitter:title"), ("name", "twitter:description")):
    v = meta(attr, key)
    ok = bool(v) and ("AI projects" in v or "AI agents" in v) and "team" not in v.lower() and "!" not in v
    check("%s carries the new positioning and no team framing" % key, ok, v)
check("hero has one primary and at most one secondary call to action",
      len(re.findall(r'<a class="btn btn-lg', re.search(r'<p class="cta">(.*?)</p>', html, re.S).group(1))) in (1, 2))
check("FAQ asks 'Do I still use Claude Code?' and the old question is gone", "Do I still use Claude Code?" in html and "Does it replace Claude Code?" not in html)
check("platform wording matches the README", "Runs locally on macOS, Linux and Windows (through WSL 2); Linux and WSL 2 are experimental." in html)
rest = html
for allowed in ("Claude Code, Pro or Max login", "Claude Code login", "Claude and Claude Code are Anthropic&rsquo;s products", "Do I still use Claude Code?",
                "works with the Claude Code you already use", "It drives Claude Code with the login you already have"):
    rest = rest.replace(allowed, "")
check("'Claude Code' appears only as a requirement or fact", "Claude Code" not in rest, [m.start() for m in re.finditer("Claude Code", rest)][:5])
visible = re.sub(r"(?s)<!--.*?-->|<(script|style|svg)\b.*?</\1>", " ", html)
visible = re.sub(r"<[^>]+>", " ", visible)
check("no exclamation mark in visible text", "!" not in visible.replace("<!doctype html>", ""), [m.start() for m in re.finditer("!", visible)][:3])
check("section order: how, team, control, memory, panel, features, install, faq",
      re.findall(r'<section id="([a-z]+)"', html) == ["how", "team", "control", "memory", "panel", "features", "install", "faq"], re.findall(r'<section id="([a-z]+)"', html))
fc = re.findall(r'<section class="fcard".*?</section>', html, re.S)
check("44 features in 7 groups", len(fc) == 7 and sum(len(re.findall(r"<li><b>", s)) for s in fc) == 44, (len(fc), sum(len(re.findall(r"<li><b>", s)) for s in fc)))
check("ten roles", len(re.findall(r'<li class="role">', html)) == 10)
check("the three step illustrations are labelled 'Sample'", html.count('<p class="ill-cap">Sample</p>') == 3 and html.count('class="ill-w"') == 3)

# ---------------------------------------------------------------- social image
og = meta("property", "og:image")
check("og:image is on the site's own domain under /assets/", bool(og) and og.startswith("https://shipmiracle.com/assets/"), og)
png = W / "assets" / pathlib.PurePosixPath(og or "x").name
check("og:image file exists", png.is_file(), png)
d = png.read_bytes() if png.is_file() else b""
size = struct.unpack(">II", d[16:24]) if d[12:16] == b"IHDR" else None
check("og:image is a PNG of 2400x1260 (1200x630 at 2x)", size == (2400, 1260), size)
check("og:image width/height meta match the file", (meta("property", "og:image:width"), meta("property", "og:image:height")) == ("2400", "1260"), (meta("property", "og:image:width"), meta("property", "og:image:height")))
check("og:image passes the strict release PNG rule (only IHDR, PLTE, tRNS, IDAT, IEND; valid CRCs; nothing after IEND)", png_clean(d))
check("og:image is under 150 KB", 0 < len(d) < 150 * 1024, len(d))

# ---------------------------------------------------------------- references
m = re.search(r'href="(https://github\.com/([^/"]+)/shipmiracle)"', html)
repo, login = (m.group(1), m.group(2)) if m else ("", "")
check("the GitHub repo link exists in index.html", bool(repo))


def local_target(ref):
    ref = ref.split("#")[0].split("?")[0]
    if ref.startswith("https://shipmiracle.com"):
        ref = ref[len("https://shipmiracle.com"):] or "/"
    if ref in ("", "/"):
        return W / "index.html"
    return W / ref.lstrip("/")


bad, ext = [], []
for src_name, src in (("index.html", html), ("404.html", nf), ("styles.css", css)):
    if src_name.endswith(".css"):
        refs = re.findall(r'url\(\s*["\']?([^)"\']+)', src)
    else:
        refs = re.findall(r'\b(?:href|src)="([^"]*)"', src)
    for r in refs:
        if r.startswith(("#", "mailto:", "data:")):
            continue
        if r.startswith(("http://", "https://")) and not r.startswith("https://shipmiracle.com"):
            ext.append((src_name, r))
            continue
        if not local_target(r).is_file():
            bad.append((src_name, r))
check("every local href/src/url() resolves to a file in website/", not bad, bad)
check("the only external URL referenced is the GitHub repo", all(r.startswith(repo) for _, r in ext) and bool(repo), ext)
check("external URLs appear only in anchors, never in src, link, url() or @import",
      not re.search(r'<(?:script|img|link|iframe|source)\b[^>]*\b(?:src|href)="https?://(?!shipmiracle\.com)', html) and not re.search(r"url\(\s*[\"']?https?:|@import", css))
check("every script is local and none is inline", re.findall(r"<script\b[^>]*>", html) == ['<script src="/theme.js">', '<script src="/site.js" defer>'] and "<script>" not in html)
csp = re.search(r'Content-Security-Policy" content="([^"]*)"', html)
check("the CSP names no origin other than 'self'", bool(csp) and not re.search(r"https?:|\*", csp.group(1)), csp and csp.group(1))
if login:
    others = [str(p.relative_to(W)) for p in W.rglob("*") if p.is_file() and p.name != "index.html" and login.encode() in p.read_bytes()]
    check("the owner's GitHub login appears in index.html only", not others, others)

# ---------------------------------------------------------------- theme: light by default
check("theme.js never reads the system setting (no matchMedia, no prefers-color-scheme)", "matchMedia" not in theme_js and "prefers-color-scheme" not in theme_js)
check("site.js never reads the system colour scheme", "prefers-color-scheme" not in site_js)
check("styles.css has no prefers-color-scheme rule", "prefers-color-scheme" not in css)
root = re.search(r"(?s):root\{(.*?)\n\}", css)
dark = re.search(r'(?s):root\[data-theme="dark"\]\{(.*?)\n\}', css)
check(":root defaults are the light values", bool(root) and "color-scheme:light" in root.group(1) and "--bg:#F4EFE6" in root.group(1) and "--accent:#B05100" in root.group(1) and "--accent-t:#9C4300" in root.group(1))
check('only [data-theme="dark"] carries the dark values', bool(dark) and "--bg:#17191C" in dark.group(1) and "--accent:#FFD04A" in dark.group(1) and "#17191C" not in (root.group(1) if root else ""))
check("theme.js switches to dark only for a saved 'dark' and sets data-theme", "=== 'dark'" in theme_js and "data-theme" in theme_js and "'shipm-theme'" in theme_js)
check("meta color-scheme is 'light' and theme-color is the light colour, with no media query",
      meta("name", "color-scheme") == "light" and meta("name", "theme-color") == "#F4EFE6" and not re.search(r'theme-color"[^>]*media=', html), (meta("name", "color-scheme"), meta("name", "theme-color")))
check("theme.js (and the 404 page) load in the head before the stylesheet", html.index('src="/theme.js"') < html.index('href="/styles.css"') and nf.index('src="/theme.js"') < nf.index('href="/styles.css"') and 'name="color-scheme" content="light"' in nf)
tog = re.search(r'<button[^>]*class="ib theme"[^>]*>', html)
check("the theme toggle exists, is a button with an accessible name", bool(tog) and 'aria-label="Switch to dark theme"' in tog.group(0) and 'type="button"' in tog.group(0), tog and tog.group(0))
check("site.js flips the toggle's label and saves the choice", "Switch to light theme" in site_js and "Switch to dark theme" in site_js and "localStorage.setItem" in site_js)

# ---- export rules (2026-11-01): every shipped website file is named exactly by release/allowlist.txt (no website/**) and by the check-side name rule
from shipmiracle.release.check import WEBSITE_OK  # noqa: E402


def _glob_re(g):
    out, i = "", 0
    while i < len(g):
        if g.startswith("**/", i):
            out += "(?:.*/)?"; i += 3
        elif g.startswith("**", i):
            out += ".*"; i += 2
        elif g[i] == "*":
            out += "[^/]*"; i += 1
        elif g[i] == "?":
            out += "[^/]"; i += 1
        else:
            out += re.escape(g[i]); i += 1
    return re.compile("^" + out + "$")


shipped = sorted(str(f.relative_to(ROOT)) for f in W.rglob("*") if f.is_file())     # every file on disk (the committed ones in a clean checkout; also catches an untracked stray)
check("the website folder has files to check", len(shipped) >= 10, shipped)
check("every file under website/ matches the check-side name rule (release-check: website_unknown otherwise)", all(WEBSITE_OK.match(f) for f in shipped), [f for f in shipped if not WEBSITE_OK.match(f)])
_al = ROOT / "release" / "allowlist.txt"
if _al.is_file():
    pats = [l.strip() for l in _al.read_text(encoding="utf-8").splitlines() if l.strip() and not l.lstrip().startswith("#")]
    web = [p for p in pats if p.startswith("website/")]
    rx = [_glob_re(p) for p in web]
    check("release/allowlist.txt has no broad website glob (no website/** and no website/*)", web and "website/**" not in pats and "website/*" not in pats and not any(p.endswith("**") for p in web), web)
    check("every file under website/ matches a website pattern of release/allowlist.txt", all(any(r.match(f) for r in rx) for f in shipped), [f for f in shipped if not any(r.match(f) for r in rx)])
    check("every website pattern of the allowlist matches at least one tracked file (no stale pattern)", all(any(r.match(f) for f in shipped) for r in rx), [p for p, r in zip(web, rx) if not any(r.match(f) for f in shipped)])
    unwanted = ["website/" + "." + "ht" + "access", "website/" + "." + "ht" + "passwd", "website/" + "." + "np" + "mrc", "website/site.js.map", "website/deploy.sh", "website/data.dat", "website/notes.txt",
                "website/.DS_Store", "website/assets/x.gif", "website/assets/fonts/x.woff", "website/assets/fonts/x.txt", "website/assets/sub/x.png", "website/sub/index.html", "website/index.html.bak", "website/INDEX.HTML"]
    check("hidden, map, script, data and unknown names under website/ are not on the allowlist", not [u for u in unwanted if any(r.match(u) for r in rx)], [u for u in unwanted if any(r.match(u) for r in rx)])
else:
    print("SKIP allowlist checks (release/allowlist.txt is not in this tree)")

print("\n%d passed, %d failed" % (passed, failed))
sys.exit(1 if failed else 0)
