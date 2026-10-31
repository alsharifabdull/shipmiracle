#!/usr/bin/env python3
"""Brand asset set (CHECKLIST L1/L2): every listed file exists, PNG sizes are exactly as named, the social preview is under 1 MB, SVGs parse,
the banner / social / lockup SVGs hold no text and no font reference (letters are outlined paths), the favicon.ico holds 16 and 32, the layer
files are the approved four, every brand file is on release/allowlist.txt and none is on hard-never.txt. Reads files only. Python 3.9, standard library.
Run: python3 tests/brand_assets_test.py"""
import pathlib, re, struct, sys, xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parent.parent
B = ROOT / "brand"
passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
    else:
        failed += 1
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(detail)[:400]))


PNG = {
    "icon/AppIcon-preview-1024.png": (1024, 1024), "icon/AppIcon-preview-dark-1024.png": (1024, 1024),
    "icon/AppIcon-preview-clear-1024.png": (1024, 1024), "icon/AppIcon-preview-tinted-1024.png": (1024, 1024),
    "favicon-16.png": (16, 16), "favicon-32.png": (32, 32), "apple-touch-icon-180.png": (180, 180),
    "menubar-template.png": (18, 18), "menubar-template@2x.png": (36, 36), "vscode-icon-128.png": (128, 128),
    "banner-1280x320.png": (1280, 320), "banner-dark-1280x320.png": (1280, 320), "social-preview-1280x640.png": (1280, 640),
}
SVG = ["icon/background.svg", "icon/foreground.svg", "icon/accent.svg", "icon/monochrome.svg", "favicon.svg", "menubar-template.svg",
       "banner-1280x320.svg", "banner-dark-1280x320.svg", "social-preview-1280x640.svg", "lockup-light.svg", "lockup-dark.svg",
       "mark-only.svg", "mark-only-dark.svg"]
OTHER = ["favicon.ico", "icon/README.md", "README.md", "colors.md"]
NO_TEXT = ["banner-1280x320.svg", "banner-dark-1280x320.svg", "social-preview-1280x640.svg", "lockup-light.svg", "lockup-dark.svg",
           "mark-only.svg", "mark-only-dark.svg", "favicon.svg", "menubar-template.svg"]
ALL = list(PNG) + SVG + OTHER

check("brand folder exists", B.is_dir(), B)
missing = [f for f in ALL if not (B / f).is_file()]
check("all %d listed files exist" % len(ALL), not missing, missing)

bad = []
for f, (w, h) in PNG.items():
    p = B / f
    if not p.is_file():
        continue
    d = p.read_bytes()
    if d[:8] != b"\x89PNG\r\n\x1a\n" or d[12:16] != b"IHDR" or struct.unpack(">II", d[16:24]) != (w, h):
        bad.append("%s %s" % (f, struct.unpack(">II", d[16:24]) if d[12:16] == b"IHDR" else "not a PNG"))
check("%d PNGs have exactly the pixel size in their name" % len(PNG), not bad, bad)
sp = B / "social-preview-1280x640.png"
check("social preview is under 1 MB", sp.is_file() and sp.stat().st_size < 1_000_000, sp.stat().st_size if sp.is_file() else "missing")

bad = []
for f in SVG:
    try:
        ET.parse(str(B / f))
    except Exception as e:  # noqa: BLE001
        bad.append("%s %s" % (f, e))
check("%d SVGs parse as XML" % len(SVG), not bad, bad)

bad = []
for f in NO_TEXT:
    t = (B / f).read_text(encoding="utf-8") if (B / f).is_file() else ""
    if re.search(r"<(text|tspan|textPath)\b|font-family|font-size|@font-face|<foreignObject", t, re.I):
        bad.append(f)
check("no <text> and no font reference in banner, social, lockup, mark and favicon SVGs (letters are outlined paths)", not bad, bad)
check("banner SVGs carry no external reference (href/url to a file or http)",
      not any(re.search(r'(?:href|src)="(?!#)|url\((?!#)', (B / f).read_text(encoding="utf-8")) for f in NO_TEXT if (B / f).is_file()))

ico = (B / "favicon.ico").read_bytes() if (B / "favicon.ico").is_file() else b""
ok = len(ico) > 22 and struct.unpack("<HHH", ico[:6]) == (0, 1, 2) and sorted([ico[6], ico[22]]) == [16, 32]
check("favicon.ico holds a 16 and a 32 px image", ok)

layer = {"background": "01-background", "foreground": "02-foreground", "accent": "03-accent"}
check("layer files carry numbered layer ids (Icon Composer order)", all(('id="%s"' % v) in (B / "icon" / (k + ".svg")).read_text() for k, v in layer.items()))


def glob_re(g):
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


def patterns(p):
    f = ROOT / "release" / p
    return [glob_re(l.strip()) for l in f.read_text(encoding="utf-8").splitlines() if l.strip() and not l.lstrip().startswith("#")] if f.is_file() else None


allow, never = patterns("allowlist.txt"), patterns("hard-never.txt")
if allow is None:       # exported tree: the release data files are not shipped
    print("SKIP allowlist checks (release/allowlist.txt is not in this tree)")
else:
    rel = ["brand/" + f for f in ALL]
    check("every brand file is on release/allowlist.txt", all(any(r.match(x) for r in allow) for x in rel), [x for x in rel if not any(r.match(x) for r in allow)])
    check("no brand file is on release/hard-never.txt", not never or not any(r.match(x) for r in never for x in rel))
    extra = sorted(str(p.relative_to(ROOT)) for p in B.rglob("*") if p.is_file() and str(p.relative_to(B)) not in ALL)
    check("no unlisted file in brand/ (every shipped file is covered by this test)", not extra, extra)

sys.path.insert(0, str(ROOT))
try:
    import struct, zlib
    from shipmiracle.release import check as RC
    bins = [p for p in B.rglob("*") if p.suffix in (".png", ".ico")]
    rx_ok = all(RC.BINARY_OK.match(str(p.relative_to(ROOT))) for p in bins) and not RC.BINARY_OK.match("docs/x.png") and not RC.BINARY_OK.match("brand/a.exe")
    check("release-check lets only brand/ PNG and ICO paths through as binary", rx_ok)
    check("every real brand PNG/ICO is clean picture data (allowed chunks, valid CRC, nothing after IEND; ICO directory consistent)",
          all(RC.brand_image_clean(str(p.relative_to(ROOT)), p.read_bytes()) for p in bins), [p.name for p in bins if not RC.brand_image_clean(str(p.relative_to(ROOT)), p.read_bytes())])

    def chunk(t, body):
        return struct.pack(">I", len(body)) + t + body + struct.pack(">I", zlib.crc32(t + body) & 0xFFFFFFFF)
    real = (B / "favicon-16.png").read_bytes()
    iend = real.rindex(b"IEND") - 4
    with_text = real[:iend] + chunk(b"tEXt", b"Comment\0" + b"/Users/x/secret") + real[iend:]
    with_exif = real[:iend] + chunk(b"eXIf", b"/Users/x") + real[iend:]
    trailing = real + b"/Users/x appended after IEND"
    bad_crc = bytearray(real); bad_crc[-20] ^= 1
    p = "brand/favicon-16.png"
    check("PNG with a tEXt chunk carrying '/Users/x' is a finding", not RC.brand_image_clean(p, with_text))
    check("PNG with an eXIf chunk is a finding", not RC.brand_image_clean(p, with_exif))
    check("PNG with bytes after IEND is a finding", not RC.brand_image_clean(p, trailing))
    check("PNG with a wrong CRC is a finding", not RC.brand_image_clean(p, bytes(bad_crc)))
    check("PNG cut before IEND is a finding", not RC.brand_image_clean(p, real[:-12]))
    ico = (B / "favicon.ico").read_bytes()
    check("ICO with trailing bytes is a finding", not RC.brand_image_clean("brand/favicon.ico", ico + b"/Users/x"))
    check("ICO whose entry points outside the file is a finding", not RC.brand_image_clean("brand/favicon.ico", ico[:-30]))
    ent = bytearray(ico); struct.pack_into("<I", ent, 6 + 8, 5)             # first image claims a 5-byte size
    check("ICO with a wrong entry size is a finding", not RC.brand_image_clean("brand/favicon.ico", bytes(ent)))
    def make_ico(png):
        return struct.pack("<HHH", 0, 1, 1) + struct.pack("<BBBBHHII", 16, 16, 0, 0, 1, 32, len(png), 22) + png
    check("a well-formed one-image ICO around a clean PNG passes", RC.brand_image_clean("brand/favicon.ico", make_ico(real)))
    check("ICO holding a PNG with a tEXt chunk is a finding", not RC.brand_image_clean("brand/favicon.ico", make_ico(with_text)))
except ImportError as e:
    print("SKIP release-check image rules (%s)" % e)
check("no brand file over 400 KB (working files stay out)", all(p.stat().st_size < 400_000 for p in B.rglob("*") if p.is_file()))
print("brand_assets_test: %d passed, %d failed" % (passed, failed))
sys.exit(1 if failed else 0)
