#!/usr/bin/env python3
"""`shipm tidy` (F10 phase 1): the read-only folder-standard report. The tree is fingerprinted before and after every run (every entry's type, mode, size, mtime, link target,
and the bytes of regular files; symlinks, FIFOs and unreadable folders included); a write guard proves no write call is made; hostile names are escaped; budgets and volumes are respected.
Full isolation through tests/shipmiracle_isolation.py. Run: python3 tests/tidy_test.py"""
import builtins, hashlib, json, os, pathlib, shutil, stat, subprocess, sys, time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import shipmiracle_isolation as ISO  # noqa: E402

ENV, TMP = ISO.isolated_env(ws=ROOT)
TMP = pathlib.Path(TMP)
os.environ.update(ENV)
ENV.pop("CLAUDECODE", None)
from shipmiracle import tidy  # noqa: E402

passed = failed = 0
def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1; print("PASS", name)
    else:
        failed += 1; print("FAIL", name, detail)

SHIPM = str(ROOT / "bin" / "shipm")
def shipm(*args, cwd=None, timeout=60):
    r = subprocess.run([sys.executable, SHIPM] + list(args), env=ENV, cwd=cwd or str(TMP), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    return r.returncode, r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace")

def git(p, *a):
    subprocess.run(["git", "-C", str(p)] + list(a), env=ENV, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

def fingerprint(root):
    """sha256 over every entry below root (not following links): path, type/mode, size, mtime_ns, link target, content of regular files (never FIFOs)."""
    h = hashlib.sha256(); n = 0
    for dp, dns, fns in os.walk(str(root), followlinks=False):
        dns.sort()
        for name in sorted(dns + fns):
            p = os.path.join(dp, name)
            st = os.lstat(p); n += 1
            h.update(("%s|%o|%d|%d|" % (os.path.relpath(p, str(root)), st.st_mode, st.st_size, st.st_mtime_ns)).encode("utf-8", "surrogateescape"))
            if stat.S_ISLNK(st.st_mode):
                h.update(os.readlink(p).encode("utf-8", "surrogateescape"))
            elif stat.S_ISREG(st.st_mode) and os.access(p, os.R_OK):
                h.update(hashlib.sha256(open(p, "rb").read()).digest())
    return h.hexdigest(), n

OLD = time.time() - 400 * 86400
def age(p, t=OLD):
    for dp, dns, fns in os.walk(str(p), topdown=False):
        for x in fns + dns:
            os.utime(os.path.join(dp, x), (t, t), follow_symlinks=False)
    os.utime(str(p), (t, t))

def build():
    """A project with a bit of everything."""
    p = TMP / "proj"; shutil.rmtree(p, ignore_errors=True); p.mkdir()
    outside = TMP / "outside"; shutil.rmtree(outside, ignore_errors=True); outside.mkdir(); (outside / "big.bin").write_bytes(b"x" * 100000)
    git(p, "init", "-q")
    (p / ".gitignore").write_text("node_modules\nnm2\n.scratch/\narchive/\nbackups/\ncache/\nreports/\ndist\n.claude/_backup/\nkept-shots\nv100\nv101\nv102\n")
    (p / "package.json").write_text("{}")
    (p / "README.md").write_text("see [shots](kept-shots/a.png) and [d](docs/x.md)\n")
    (p / "docs").mkdir(); (p / "docs" / "x.md").write_text("x\n")
    (p / "node_modules" / "pkg").mkdir(parents=True); (p / "node_modules" / "pkg" / "i.js").write_text("a" * 5000)
    (p / "nm2").mkdir(); (p / "nm2" / "f").write_text("b")                         # nm2 is not a known name: never regenerable
    (p / "dist").mkdir(); (p / "dist" / "o.js").write_text("c" * 100)
    (p / "kept-shots").mkdir(); (p / "kept-shots" / "a.png").write_text("png")      # linked from README: never
    (p / ".scratch" / "2024-01-01-old-shots").mkdir(parents=True); (p / ".scratch" / "2024-01-01-old-shots" / "a.png").write_text("p" * 3000)
    (p / ".scratch" / "2099-01-01-new").mkdir(); (p / ".scratch" / "2099-01-01-new" / "b").write_text("n")
    (p / ".scratch" / "secrets-run").mkdir(); (p / ".scratch" / "secrets-run" / ".env").write_text("TOKEN=1")
    (p / ".scratch" / "2024-02-02-with-env.pem").write_text("k")
    (p / "backups").mkdir(); (p / "backups" / "ha.tar").write_text("b" * 2000)
    (p / "archive").mkdir(); (p / "archive" / "old.zip").write_text("z")
    (p / "cache").mkdir(); (p / "cache" / "tracked.txt").write_text("t"); (p / "cache" / "loose.txt").write_text("l")
    (p / "reports").mkdir(); (p / "reports" / "s.png").write_text("s")
    for v in ("v100", "v101", "v102"):
        (p / v).mkdir(); (p / v / "f").write_text("v")
    (p / "release.zip").write_text("zip")
    (p / "Claude outputs").mkdir(); (p / "Claude outputs" / "f").write_text("o")
    (p / "wip.txt").write_text("fresh untracked")
    (p / "old-untracked").mkdir(); (p / "old-untracked" / "f").write_text("u")
    git(p, "add", "-A"); git(p, "add", "-f", "cache/tracked.txt")
    git(p, "commit", "-qm", "init")
    (p / "wip.txt").write_text("fresh untracked 2"); (p / "old-untracked").mkdir(exist_ok=True); (p / "old-untracked" / "g").write_text("u")
    (p / "old-untracked").exists()
    # commit made these tracked; make a truly untracked one
    (p / "untracked-old").mkdir(); (p / "untracked-old" / "f").write_text("u"); age(p / "untracked-old")
    # hostile things
    os.symlink(str(outside), str(p / "evil-link")); os.symlink("loop-b", str(p / "loop-a")); os.symlink("loop-a", str(p / "loop-b"))
    os.mkfifo(str(p / "pipe"))
    os.link(str(p / ".scratch" / "2024-01-01-old-shots" / "a.png"), str(p / ".scratch" / "2024-01-01-old-shots" / "a-hard.png"))
    with open(p / ".scratch" / "2024-03-03-sparse", "wb") as f:
        f.truncate(2 * 1024 ** 3)
    (p / ".scratch" / "2024-04-04-unreadable" / "inner").mkdir(parents=True); (p / ".scratch" / "2024-04-04-unreadable" / "inner" / "f").write_text("x")
    os.chmod(str(p / ".scratch" / "2024-04-04-unreadable" / "inner"), 0)
    for n in (".scratch/2024-01-01-old-shots", ".scratch/2024-03-03-sparse", ".scratch/secrets-run", ".scratch/2024-02-02-with-env.pem", "node_modules", "dist", "reports"):
        try:
            age(p / n) if os.path.isdir(p / n) else os.utime(p / n, (OLD, OLD))
        except OSError:
            pass
    os.utime(str(p / ".scratch" / "2024-04-04-unreadable"), (OLD, OLD))
    # names with newline / bidi / markup
    for nm in ("evil\nname", "rtl‮txt", "<script>alert(1)", "esc\x1b[31mred"):
        try:
            (p / ".scratch" / nm).mkdir(); os.utime(str(p / ".scratch" / nm), (OLD, OLD))
        except OSError:
            pass
    return p, outside

def unlock(p):
    for dp, dns, fns in os.walk(str(p)):
        for d in dns:
            try: os.chmod(os.path.join(dp, d), 0o755)
            except OSError: pass

proj, outside = build()
fp0 = fingerprint(proj); fo0 = fingerprint(outside)

# ---- CLI, text and JSON, tree unchanged ----
rc, out, err = shipm("tidy", str(proj))
check("text report exits 0", rc == 0, err)
check("text says read-only", "read-only" in out and "nothing was moved" in out)
rc, jout, err = shipm("tidy", str(proj), "--json")
j = json.loads(jout)
check("json has v:1 and tidy object", rc == 0 and j.get("v") == 1 and "tidy" in j)
t = j["tidy"]
check("json keys stable", set(t) == {"project", "git", "partial", "idle_days", "entries_scanned", "counts", "bytes", "kept", "items", "suggestions", "unreadable", "other_volume", "notes", "omitted"}, sorted(t))
check("item keys stable", all(set(i) >= {"path_rel", "class", "kind", "bytes", "newest_mtime", "age_days", "why", "preselected"} for i in t["items"]))
check("nothing is preselected (report only)", not any(i["preselected"] for i in t["items"]))
by = {i["path_rel"]: i for i in t["items"]}
cls = lambda n: by.get(n, {}).get("class")
check("tree identical after CLI runs (hash of every entry incl. links, FIFO)", fingerprint(proj) == fp0)
check("target of the evil symlink untouched", fingerprint(outside) == fo0)
check("old scratch folder is throw-away", cls(".scratch/2024-01-01-old-shots") == "disposable", by.keys())
check("new scratch folder is not offered", ".scratch/2099-01-01-new" not in by)
check("node_modules with package.json is rebuildable", cls("node_modules") == "regenerable")
check("dist with a stack file is rebuildable", cls("dist") == "regenerable")
check("unknown ignored folder nm2 is not rebuildable", cls("nm2") != "regenerable")
check("backups/ is protected and called only copy", cls("backups") == "never" and "only copy" in by["backups"]["why"])
check("archive/ is protected", cls("archive") == "never")
check("symlink to outside is protected, not followed", cls("evil-link") == "never" and by["evil-link"]["bytes"] == 0)
check("symlink loop is protected", cls("loop-a") == "never")
check("FIFO is protected and was not opened", cls("pipe") == "never" and "never opened" in by["pipe"]["why"])
check("folder linked from README is protected", cls("kept-shots") == "never")
check("folder holding a tracked file in an ignored dir is never offered", "cache" not in by or by["cache"]["class"] == "never")
check(".env inside .scratch: folder not offered as disposable", cls(".scratch/secrets-run") != "disposable")
check("secret-named file in .scratch is protected", cls(".scratch/2024-02-02-with-env.pem") == "never")
check("fresh untracked file is not offered", "wip.txt" not in by)
check("tracked items are never listed", "README.md" not in by and "docs" not in by and "package.json" not in by)
check("untracked old folder is not rebuildable (review at most)", cls("untracked-old") in (None, "review"))
check("sparse 2 GB file counted by blocks, not length", by[".scratch/2024-03-03-sparse"]["bytes"] < 50 * 1024 * 1024)
old = by[".scratch/2024-01-01-old-shots"]
check("hard link counted once", old["bytes"] < 2 * 4096 * 3 and old["bytes"] >= 4096, old["bytes"])
check("unreadable folder skipped with a line", any("unreadable" in x for x in t["unreadable"]), t["unreadable"])
check("suggestion: version folders to archive/", any("version folders" in s and "archive/" in s for s in t["suggestions"]))
check("suggestion: zip at top", any("archive file" in s for s in t["suggestions"]))
check("suggestion: space in name", any("space in its name" in s for s in t["suggestions"]))
check("suggestion: reports/ not tracked", any(s.startswith("reports/") for s in t["suggestions"]))
check("suggestion: scratch name not dated", any("YYYY-MM-DD" in s for s in t["suggestions"]))
check("v100.. ignored folders small: not offered", "v100" not in by)
# hostile names
alltext = out + jout
check("no raw newline from a name splits a line", "evil\nname" not in alltext and "evil\\u000aname" in out)
check("no raw bidi override in text or json", "‮" not in alltext and "\\u202e" in out)
check("no raw markup or escape char from names", "<script>" not in alltext and "\x1b" not in alltext and "\\u003cscript" in out)
# --standard
rc, sout, _ = shipm("tidy", str(proj), "--standard")
check("--standard prints suggestions only", rc == 0 and "Against the folder standard" in sout and "Could be freed" not in sout)
# by name through the projects folder and by cwd
dev = pathlib.Path(ENV["SHIPMIRACLE_DEV"]); os.symlink(str(proj), str(dev / "proj"))
rc, nout, _ = shipm("tidy", "proj")
check("project by name", rc == 0 and "Tidy report for proj" in nout)
rc, cout, _ = shipm("tidy", cwd=str(dev / "proj"))
check("project from the current folder", rc == 0 and "Tidy report for proj" in cout, cout[:100])
rc, _, e = shipm("tidy", "nope-no-such")
check("unknown project exits 3", rc == 3 and "no project named" in e, e)
rc, _, e = shipm("tidy", cwd=str(TMP))
check("outside a project, no name: exit 2", rc == 2, e)
rc, _, e = shipm("tidy", str(proj / "README.md"))
check("a file path is refused", rc == 3, e)
rc, hout, _ = shipm("--help")
check("tidy is listed by --help", "tidy" in hout)

# ---- read-only folder: scan works with every directory made unwritable ----
unlock(proj)
ro = TMP / "ro"; shutil.rmtree(ro, ignore_errors=True); shutil.copytree(str(proj), str(ro), symlinks=True, ignore=lambda d, names: [n for n in names if n in ("pipe", ".scratch")] if d == str(proj) else [])
for dp, dns, fns in os.walk(str(ro)):
    for d in dns + [""]:
        os.chmod(os.path.join(dp, d) if d else dp, 0o555)
fr0 = fingerprint(ro)
rc, rout, err = shipm("tidy", str(ro))
check("works on a read-only tree and changes nothing", rc == 0 and fingerprint(ro) == fr0, err)
unlock(ro); os.chmod(str(ro), 0o755)

# ---- write guard: no write-type call at all during an in-process scan ----
proj, outside = build()
calls = []
real_open, real_bopen = os.open, builtins.open
WRITE = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
def g_open(path, flags, *a, **k):
    if str(path) == "/dev/null": return real_open(path, flags, *a, **k)      # subprocess plumbing
    if flags & WRITE: calls.append(("os.open", path, flags))
    if not stat.S_ISDIR(0) and not (flags & getattr(os, "O_DIRECTORY", 0)) and not (flags & os.O_NONBLOCK): calls.append(("blocking-open", path, flags))
    return real_open(path, flags, *a, **k)
def g_bopen(f, mode="r", *a, **k):
    if any(c in mode for c in "wax+"): calls.append(("open", f, mode))
    return real_bopen(f, mode, *a, **k)
saved = {n: getattr(os, n) for n in ("unlink", "remove", "rename", "replace", "mkdir", "makedirs", "rmdir", "symlink", "link", "chmod", "utime", "truncate", "mkfifo")}
def blocker(n):
    def f(*a, **k): calls.append((n, a[:1]))
    return f
os.open, builtins.open = g_open, g_bopen
for n in saved: setattr(os, n, blocker(n))
try:
    rep = tidy.scan(proj)
finally:
    os.open, builtins.open = real_open, real_bopen
    for n, f in saved.items(): setattr(os, n, f)
check("scan made no write call and no blocking open", calls == [], calls[:3])
check("scan returned items in-process", len(rep["items"]) > 5)

# ---- FIFO is never read: a hang would time out here ----
t0 = time.time()
rc, _, _ = shipm("tidy", str(proj), timeout=30)
check("FIFO in tree does not hang the scan", rc == 0 and time.time() - t0 < 30)
# a FIFO named like a doc and a FIFO inside .scratch
os.mkfifo(str(proj / "docs" / "pipe.md")); os.mkfifo(str(proj / ".scratch" / "2024-05-05-fifo"))
t0 = time.time()
rc, o2, _ = shipm("tidy", str(proj), timeout=30)
check("FIFO named *.md and FIFO child of .scratch: no hang", rc == 0 and time.time() - t0 < 30)

# ---- budgets and volumes ----
big = TMP / "big"; shutil.rmtree(big, ignore_errors=True); (big / ".scratch" / "2024-01-01-many").mkdir(parents=True); git(big, "init", "-q")
(big / ".gitignore").write_text(".scratch/\n")
for i in range(1500): (big / ".scratch" / "2024-01-01-many" / ("f%d" % i)).write_text("x")
age(big / ".scratch")
r = tidy.scan(big, max_entries=300)
check("entry budget stops the walk and says partial", r["partial"] and r["entries_scanned"] <= 305 and any("partial" in n or "limit" in n for n in r["notes"]))
r = tidy.scan(big, max_seconds=0.0)
check("time budget zero: partial, no crash", isinstance(r["partial"], bool))
r = tidy.scan(big)
check("big folder complete when within budget", not r["partial"] and r["entries_scanned"] >= 1500)
b = tidy.Budget(); st = os.lstat(str(big / ".scratch"))
fd = os.open(str(big), os.O_RDONLY)
sz, _ = tidy.measure(st, ".scratch", fd, ".scratch", st.st_dev + 1, b)     # root on another device: seam for a mount point
os.close(fd)
check("other volume is not entered", sz == 0 and b.other_volume == [".scratch"] and b.entries == 1)
text = tidy.render(tidy.scan(big))
check("plain-words text names the owner decision limits", "Could be freed" in text and "Left alone" in text)

# ---- not a git folder, empty folder ----
ng = TMP / "nogit"; shutil.rmtree(ng, ignore_errors=True); (ng / ".scratch" / "2020-01-01-x").mkdir(parents=True); age(ng / ".scratch")
r = tidy.scan(ng)
check("not a git repo: note and nothing offered", r["git"] is False and not [i for i in r["items"] if i["class"] != "never"] and any("not a git" in n for n in r["notes"]))
em = TMP / "empty"; shutil.rmtree(em, ignore_errors=True); em.mkdir()
check("empty folder: no crash, no suggestions", tidy.scan(em)["items"] == [])
# a .scratch that is a symlink to elsewhere is not walked
fo1 = fingerprint(outside)
sl = TMP / "slink"; shutil.rmtree(sl, ignore_errors=True); sl.mkdir(); git(sl, "init", "-q"); os.symlink(str(outside), str(sl / ".scratch"))
r = tidy.scan(sl)
check("a .scratch symlink is not walked", not [i for i in r["items"] if i["path_rel"].startswith(".scratch/")] and fingerprint(outside) == fo1)
check("clean() escapes control, bidi, markup", tidy.clean("a\nb‮c<d>") == "a\\u000ab\\u202ec\\u003cd\\u003e")

# ---- QA round 1 (D1..D8) ----
def mk(name):
    p = TMP / name; shutil.rmtree(p, ignore_errors=True); p.mkdir(); git(p, "init", "-q"); return p
def commit(p):
    git(p, "add", "-A"); git(p, "commit", "-qm", "c")
def itemmap(r): return {i["path_rel"]: i for i in r["items"]}

src = (ROOT / "shipmiracle" / "tidy.py").read_text()
check("D1 tidy.py does not carry the retired name", "a" + "iw" not in src.lower())
check("D1 the old tool folder name stays protected", ("." + "ai" + "w") in tidy.NEVER_NAMES)

# D2: a folder that was not fully looked at is never throw-away / rebuildable
p2 = mk("d2"); (p2 / ".gitignore").write_text(".scratch/\ndist\n"); (p2 / "package.json").write_text("{}")
for k in range(6):
    d = p2 / ".scratch" / ("2020-01-0%d-a" % (k + 1)); d.mkdir(parents=True)
    for j in range(8): (d / ("f%d" % j)).write_text("x")
    (d / "zz.env").write_text("x"); (d / ".env").write_text("TOKEN=1")
deep = p2 / ".scratch" / "2020-02-02-deep"; q = deep
for k in range(70): q = q / "d"
q.mkdir(parents=True); (q / ".env").write_text("K=1")
(p2 / "dist").mkdir(); [ (p2 / "dist" / ("o%d" % j)).write_text("x") for j in range(40) ]
commit(p2)
age(p2 / ".scratch")
r = tidy.scan(p2, max_entries=20)
bad = [i for i in r["items"] if i["class"] in ("disposable", "regenerable")]
check("D2 budget spent: nothing offered as throw-away or rebuildable", r["partial"] and not bad, bad[:2])
r = tidy.scan(p2)
m = itemmap(r)
check("D2 70-deep folder with .env is not throw-away", m.get(".scratch/2020-02-02-deep", {}).get("class") in ("review", "never"), m.get(".scratch/2020-02-02-deep"))
check("D2 shallow folders with .env are protected", all(m[".scratch/2020-01-0%d-a" % k]["class"] == "never" for k in range(1, 7)))

# D3: links from tracked pages protect by prefix, in any folder, in every link style
p3 = mk("d3"); (p3 / ".gitignore").write_text(".scratch/\n")
names = ["2020-01-01-ev", "2020-01-02-pct x", "2020-01-03-dot", "2020-01-04-ref", "2020-01-05-html", "2020-01-06-angle y", "2020-01-07-up", "2020-01-08-free"]
for n in names:
    (p3 / ".scratch" / n).mkdir(parents=True); (p3 / ".scratch" / n / "shot.png").write_text("png")
(p3 / "docs" / "deep" / "x").mkdir(parents=True); (p3 / "a" / "b").mkdir(parents=True)
(p3 / "docs" / "deep" / "x" / "page.md").write_text("![s](../../../.scratch/2020-01-01-ev/shot.png)\n![t](../../../.scratch/2020-01-02-pct%20x/shot.png)\n![u](<../../../.scratch/2020-01-06-angle y/shot.png>)\n")
(p3 / "a" / "b" / "n.md").write_text("[d](./../../.scratch/2020-01-03-dot/shot.png#frag)\n\n[r]: ../../.scratch/2020-01-04-ref/shot.png\n<img src=\"../../.scratch/2020-01-05-html/shot.png\">\n[up](../../.scratch/2020-01-07-up)\n")
commit(p3); age(p3 / ".scratch")
m = itemmap(tidy.scan(p3))
for n in names[:-1]:
    check("D3 linked folder protected: " + n, m.get(".scratch/" + n, {}).get("class") == "never", m.get(".scratch/" + n))
check("D3 unlinked old folder stays throw-away", m.get(".scratch/2020-01-08-free", {}).get("class") == "disposable")

# D4: bounded work and output
p4 = mk("d4"); (p4 / ".gitignore").write_text(".scratch/\n")
for k in range(22000):
    os.symlink("/nonexistent", str(p4 / ("l%d" % k)))
    open(str(p4 / ("n %d x" % k)), "w").close()
t0 = time.time(); r = tidy.scan(p4); el = time.time() - t0
j4 = json.dumps(report_json := tidy.report_json(r)); tx = tidy.render(r)
check("D4 44k top-level names: partial, fast", r["partial"] and el < 30, el)
check("D4 json under 200 KB", len(j4) < 200000, len(j4))
check("D4 text under 200 KB", len(tx) < 200000, len(tx))
check("D4 lists are capped", len(r["items"]) <= 4 * tidy.LIST_CAP and len(r["suggestions"]) <= tidy.LIST_CAP and r["counts"]["never"] > 100)
check("D4 text says there is more", "more" in tx)

# D5: recent untracked, not ignored scratch work is never listed
p5 = mk("d5"); (p5 / "keep").write_text("k"); commit(p5)
(p5 / ".scratch" / (time.strftime("%Y-%m-%d") + "-work")).mkdir(parents=True); (p5 / ".scratch" / (time.strftime("%Y-%m-%d") + "-work") / "f").write_text("w")
r = tidy.scan(p5)
check("D5 fresh untracked scratch is not listed", not [i for i in r["items"] if i["path_rel"].startswith(".scratch/")] and r["kept"]["work_in_progress"] >= 1)

# D6: normalisation (NFD on disk, NFC in git or the other way round)
import unicodedata
p6 = mk("d6"); (p6 / ".gitignore").write_text("zzz\n")
for nm in ("caf\u00e9", "\u0623hlan", "\u0627\u0654b"):
    for form in ("NFD", "NFC"):
        d = p6 / unicodedata.normalize(form, nm + "-" + form)
        d.mkdir(); (d / "f").write_text("t")
commit(p6)
for dd in list(p6.iterdir()):
    if dd.name != ".git" and dd.is_dir(): age(dd)
m = itemmap(tidy.scan(p6))
check("D6 tracked folders in any Unicode form are never listed", not [k for k in m if "-NF" in unicodedata.normalize("NFC", k)], list(m)[:3])

# D7: secret inside rebuildable, marker must be a regular file, path wins over a name
p7 = mk("d7"); (p7 / ".gitignore").write_text("node_modules\ndist\nbuild\n"); (p7 / "package.json").write_text("{}")
(p7 / "node_modules" / "x" / "test").mkdir(parents=True); (p7 / "node_modules" / "x" / "test" / "server.key").write_text("k")
(p7 / "dist").mkdir(); (p7 / "dist" / ".env.production").write_text("k")
commit(p7); age(p7 / "node_modules"); age(p7 / "dist")
m = itemmap(tidy.scan(p7))
check("D7 secret inside node_modules demotes it", m["node_modules"]["class"] == "review" and "secret" in m["node_modules"]["why"], m.get("node_modules"))
check("D7 secret inside dist demotes it", m["dist"]["class"] == "review")
p7b = mk("d7b"); (p7b / ".gitignore").write_text("node_modules\n"); (p7b / "package.json").mkdir(); (p7b / "package.json" / "f").write_text("x")
(p7b / "node_modules").mkdir(); (p7b / "node_modules" / "f").write_text("x"); commit(p7b); age(p7b / "node_modules")
check("D7 package.json as a folder is not a marker", itemmap(tidy.scan(p7b)).get("node_modules", {}).get("class") != "regenerable")
os.makedirs(str(TMP / "cwd" / "samename"), exist_ok=True); os.symlink(str(p7), str(dev / "samename"))
old_cwd = os.getcwd(); os.chdir(str(TMP / "cwd"))
try:
    check("D7 an existing relative path wins over a project name", tidy.resolve_target("samename") == os.path.realpath(str(TMP / "cwd" / "samename")))
finally:
    os.chdir(old_cwd)
check("D7 the name still works when no such path exists", tidy.resolve_target("samename") == os.path.realpath(str(p7)))
fm = (ROOT / "docs" / "standards" / "folders.md").read_text()
check("D8 public page has no private references", "DECISIONS 2026" not in fm and "Approved" not in fm and "owner on 21" not in fm)
check("D8 page states what the code does for ignored data and secrets", "may be the only copy" in fm and "secret-looking" in fm and "Needs a decision" in fm)

# ---- QA round 2 (A, B, M1-M5) ----
def link_proj(name, md_files, ignore=".scratch/\n"):
    """A project with one old ignored scratch folder `.scratch/2020-01-01-a` and tracked pages `md_files` {relpath: text}."""
    p = mk(name); (p / ".gitignore").write_text(ignore)
    for rel, txt in md_files.items():
        (p / rel).parent.mkdir(parents=True, exist_ok=True); (p / rel).write_text(txt)
    commit(p)
    (p / ".scratch" / "2020-01-01-a").mkdir(parents=True); (p / ".scratch" / "2020-01-01-a" / "f").write_text("x"); age(p / ".scratch")
    return p
def offered(r): return [i for i in r["items"] if i["class"] in ("disposable", "regenerable")]
LINK = "[s](%s.scratch/2020-01-01-a/f)\n"

# A1: more pages than the cap
old_files = tidy.MD_FILES; tidy.MD_FILES = 5
pa = link_proj("a1", dict([("d%d/p.md" % k, "x\n") for k in range(5)] + [("zz/last.md", LINK % "../")]))
r = tidy.scan(pa); tidy.MD_FILES = old_files
check("A1 pages over the cap: nothing offered, note says so", not offered(r) and any("not read in full" in n for n in r["notes"]), r["items"])
# A2: huge page with the link before 2 MB of text
old_md = tidy.MD_MAX; tidy.MD_MAX = 2000
pa = link_proj("a2", {"docs/huge.md": LINK % "../" + "y" * 5000})
r = tidy.scan(pa); tidy.MD_MAX = old_md
check("A2 page over 1 MB (cap lowered for the test): nothing offered", not offered(r) and any("not read in full" in n for n in r["notes"]))
# A3: tracked page turned into a FIFO / a symlink
pa = link_proj("a3", {"docs/p.md": LINK % "../", "docs/q.md": "q\n"})
os.remove(str(pa / "docs" / "p.md")); os.mkfifo(str(pa / "docs" / "p.md"))
check("A3 tracked page that is now a FIFO: nothing offered", not offered(tidy.scan(pa)))
pa = link_proj("a3b", {"docs/p.md": LINK % "../", "docs/q.md": "q\n"})
os.remove(str(pa / "docs" / "p.md")); os.symlink("q.md", str(pa / "docs" / "p.md"))
check("A3 tracked page that is now a symlink: nothing offered", not offered(tidy.scan(pa)))
# M1d: total markdown cap
old_tot = tidy.MD_TOTAL; tidy.MD_TOTAL = 100
pa = link_proj("m1d", {"a.md": "z" * 300 + "\n", "b.md": LINK % ""})
r = tidy.scan(pa); tidy.MD_TOTAL = old_tot
check("M1 total markdown cap: later pages unread, nothing offered", not offered(r))
pa = link_proj("m1ok", {"a.md": "z\n"})
check("A control: a normal project still offers the old scratch folder", [i["path_rel"] for i in offered(tidy.scan(pa))] == [".scratch/2020-01-01-a"])
# M1c: a link to the folder ABOVE the item
pa = link_proj("m1c", {"docs/p.md": "[all](../.scratch)\n"})
check("M1 link to the parent folder protects the children", itemmap(tidy.scan(pa)).get(".scratch/2020-01-01-a", {}).get("class") == "never")
# M1a: unreadable folder inside an item
pa = link_proj("m1a", {"a.md": "z\n"}); u = pa / ".scratch" / "2020-01-01-a" / "locked"; u.mkdir(); age(pa / ".scratch"); os.chmod(str(u), 0)
r = tidy.scan(pa); os.chmod(str(u), 0o755)
check("M1 item with an unreadable folder inside is not throw-away", not offered(r) and itemmap(r)[".scratch/2020-01-01-a"]["class"] == "review", r["items"])
# M1b: budget exhausted at the end of an item
pa = link_proj("m1b", {"a.md": "z\n"})
for j in range(30): (pa / ".scratch" / "2020-01-01-a" / ("g%d" % j)).write_text("x")
age(pa / ".scratch")
check("M1 budget cut inside an item: not throw-away", not offered(tidy.scan(pa, max_entries=15)))
# B: unignored old backups are not throw-away
pb = mk("b"); (pb / "k").write_text("k"); commit(pb)
for k in range(6):
    d = pb / ".claude" / "_backup" / ("20200%d" % (k + 1)); d.mkdir(parents=True); (d / "f").write_text("x"); age(d, OLD - k * 86400)
r = tidy.scan(pb)
check("B unignored old backups are not offered as throw-away", not offered(r) and any(i["class"] == "review" for i in r["items"]), r["items"][:2])
(pb / ".gitignore").write_text(".claude/_backup/\n")
r = tidy.scan(pb)
check("B ignored old backups beyond the newest 3 are throw-away", len(offered(r)) == 3, [i["path_rel"] for i in r["items"]])
# M3: one deep folder is incomplete alone, the scan stays complete
pm = mk("m3"); (pm / ".gitignore").write_text(".scratch/\n"); (pm / "k").write_text("k"); commit(pm)
q = pm / ".scratch" / "2020-01-01-deep"
for k in range(70): q = q / "d"
q.mkdir(parents=True)
(pm / ".scratch" / "2020-01-02-fine").mkdir(); (pm / ".scratch" / "2020-01-02-fine" / "f").write_text("x"); age(pm / ".scratch" / "2020-01-02-fine")
r = tidy.scan(pm); m = itemmap(r)
check("M3 deep folder alone does not make the whole scan partial", r["partial"] is False and m[".scratch/2020-01-02-fine"]["class"] == "disposable", r["partial"])
check("M3 deep folder is review and says not fully measured", m[".scratch/2020-01-01-deep"]["class"] == "review" and m[".scratch/2020-01-01-deep"].get("measured") is False and "not fully measured" in tidy.render(r))
# M2: lazy listing, M5: deadline per folder
import inspect
check("M2 no whole-directory list() in the walk", "list(os.scandir" not in inspect.getsource(tidy.measure))
b5 = tidy.Budget(max_seconds=0.0); time.sleep(0.01)
check("M5 deadline is checked on entering a folder", b5.late() is True)
b6 = tidy.Budget(max_seconds=0.0); time.sleep(0.01); ok = True
for _ in range(300): ok = b6.tick()
check("M5 deadline is checked within 256 entries", ok is False)

# F10 nits: rule 4 for small unignored items, null numbers for unmeasured items in --json
pn = mk("n1"); (pn / "k").write_text("k"); commit(pn)
for nm, days in (("2020-01-01-s30", 30), ("2020-01-02-s29", 29)):
    d = pn / ".scratch" / nm; d.mkdir(parents=True); (d / "f").write_text("x"); age(d, time.time() - days * 86400 - 3600)
d = pn / ".claude" / "_backup" / "b31"; d.mkdir(parents=True); (d / "f").write_text("x"); age(d, time.time() - 31 * 86400 - 3600)
for k in range(3):
    d = pn / ".claude" / "_backup" / ("new%d" % k); d.mkdir(parents=True); (d / "f").write_text("x")
r = tidy.scan(pn); m = itemmap(r)
check("N1 tiny unignored .scratch item of 30 days is needs-a-decision", m.get(".scratch/2020-01-01-s30", {}).get("class") == "review" and m[".scratch/2020-01-01-s30"]["bytes"] < 1024 * 1024, m.get(".scratch/2020-01-01-s30"))
check("N1 unignored .scratch item of 29 days is work in progress, not offered", ".scratch/2020-01-02-s29" not in m)
check("N1 tiny unignored backup over 30 days is needs-a-decision", m.get(".claude/_backup/b31", {}).get("class") == "review", m.get(".claude/_backup/b31"))
check("N1 folders.md rule 4 names both cases", "unignored `.scratch` item of 30 days or more" in open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "standards", "folders.md")).read() and "unignored `.claude/_backup` item older than 30 days" in open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "standards", "folders.md")).read())
jn = tidy.report_json(tidy.scan(pm))
dm = [i for i in jn["items"] if i.get("measured") is False]
check("N2 json: unmeasured item has null bytes and null age_days", dm and all(i["bytes"] is None and i["age_days"] is None for i in dm), dm)
check("N2 json: measured items keep real numbers", all(isinstance(i["bytes"], int) and isinstance(i["age_days"], int) for i in jn["items"] if i.get("measured") is not False))
rc, jo, _e = shipm("tidy", str(pm), "--json")
jj = [i for i in json.loads(jo)["tidy"]["items"] if i.get("measured") is False]
check("N2 shipm tidy --json: same through the CLI", rc == 0 and jj and jj[0]["bytes"] is None and jj[0]["age_days"] is None, jo[:300])

unlock(TMP)
ISO.cleanup(str(TMP))
print("tidy_test: %d passed, %d failed" % (passed, failed))
sys.exit(1 if failed else 0)
