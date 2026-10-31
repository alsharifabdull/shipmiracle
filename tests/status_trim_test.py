#!/usr/bin/env python3
"""status-trim and status-extract: caps, idempotence, nothing lost, dry run, dirty-tree refusal, edge cases, brief size.
Run: python3 tests/status_trim_test.py"""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import shipmiracle_isolation; shipmiracle_isolation.apply_to_environ()   # test isolation: fresh HOME/SHIPMIRACLE_HOME/CONFIG/STATE unless already temp
import os, re, subprocess, sys, tempfile
WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); fails = []
def check(n, c, info=""):
    print(("PASS " if c else "FAIL ") + n + ("" if c else " " + str(info)))
    if not c: fails.append(n)
env = dict(os.environ, SHIPMIRACLE_TODAY="2026-10-20")
for k in ("SHIPMIRACLE_STATUS_CAP", "SHIPMIRACLE_STATUS_KEEP"): env.pop(k, None)
def run(*a, e=None): return subprocess.run([sys.executable, *a], env=e or env, capture_output=True, text=True)
def trim(d, *a, e=None, strict=False):
    # tests use throw-away folders without git: pass --force unless the test is about the safety checks
    if not strict and "--force" not in a and "--dry" not in a: a = (*a, "--force")
    return run(WS + "/bin/status-trim", d, *a, e=e)
def rd(p): return open(p, encoding="utf-8", newline="").read()
def mk(st):
    d = tempfile.mkdtemp(); os.makedirs(d + "/docs"); open(d + "/docs/STATUS.md", "w", encoding="utf-8", newline="").write(st); return d
def archived(d):
    ad = d + "/docs/status-archive"
    return {f: rd(ad + "/" + f) for f in sorted(os.listdir(ad))} if os.path.isdir(ad) else {}
def git(d, *a): return subprocess.run(["git", "-C", d, *a], capture_output=True, text=True)

big = "x line\n" * 400
HEAD = "# STATUS — T\n\nUpdated: 2026-10-20 · mode: BUILD\n\nIntro text.\n\n"
TAIL = "## In progress\ndoing X\n\n## Next\n1. Y\n\n## Not verified / known issues\nnone\n\n## Last verification evidence\nok\n\n## Handoff\nresume with Z\n"
def chap(day, mon="Oct", body=big): return f"## Entry ({day} {mon} 2026)\n{body}\n"
st = HEAD + "".join(chap(d) for d in range(19, 7, -1)) + "## Older ISO (2026-09-01)\n" + big + "\n" + TAIL

# --- basic: caps, keep-N, protected stay, text preserved --------------------------------------------------
d = mk(st)
r = trim(d, "--dry")
check("dry run changes nothing and lists moves", rd(d + "/docs/STATUS.md") == st and not archived(d) and "move" in r.stdout, r.stdout)
r = trim(d, "--cap", "40000", "--keep", "3")
new = rd(d + "/docs/STATUS.md"); arch = archived(d)
check("exit 0", r.returncode == 0, r.stderr)
check("size under the cap", len(new.encode()) <= 40000, len(new))
check("only the 3 most recent dated chapters stay", all(f"Entry ({n} Oct" in new for n in (19, 18, 17)) and "Entry (16 Oct" not in new.split("## Archived index")[0], new[:400])
check("protected sections and header untouched", all(s in new for s in ("## In progress\ndoing X\n\n", "## Next\n1. Y", "## Handoff\nresume with Z", "Updated: 2026-10-20 · mode: BUILD", "Intro text.")))
check("moved chapters land in <YYYY-MM>-<slug>.md with heading and body", "2026-10-entry-16-oct-2026.md" in arch and arch["2026-10-entry-16-oct-2026.md"].count("## Entry (16 Oct 2026)") == 1 and big in arch["2026-10-entry-16-oct-2026.md"] and "2026-09-older-iso-2026-09-01.md" in arch, list(arch))
check("index entries stay in STATUS", "Archived: Entry (16 Oct 2026) -> docs/status-archive/2026-10-entry-16-oct-2026.md" in new and "Archived: Older ISO (2026-09-01) -> docs/status-archive/2026-09-older-iso-2026-09-01.md" in new)
# no text lost: kept (minus index) + archived chapters == original, as a multiset of lines-chapters
def chapters(t): return sorted(re.split(r"(?m)^(?=## )", t))
kept_wo_index = re.sub(r"(?ms)^## Archived index\n.*?(?=^## |\Z)", "", new)
allarch = "".join(re.sub(r"(?s)^# STATUS archive:.*?\n\n(?=## )", "", v, count=1) for v in arch.values())
orig_ch = [c.strip("\n") for c in re.split(r"(?m)^(?=## )", st)]
now_ch = [c.strip("\n") for c in re.split(r"(?m)^(?=## )", kept_wo_index + "\n" + allarch)]
check("no text lost: kept + archived chapters equal the original", sorted(orig_ch) == sorted(now_ch))
# kept order identical to original order
pos = [st.index(c) for c in re.split(r"(?m)^(?=## )", kept_wo_index)[1:] if c in st]
check("kept chapters keep their original order", pos == sorted(pos) and len(pos) >= 7)
a1, n1 = dict(arch), new
r = trim(d)
check("second run is a no-op (STATUS and archive byte-identical)", rd(d + "/docs/STATUS.md") == n1 and archived(d) == a1 and "nothing to move" in r.stdout, r.stdout)

# --- default cap 20 KB ---------------------------------------------------------------------------------
d = mk(st); trim(d)
check("default cap 20 KB honoured", len(rd(d + "/docs/STATUS.md").encode()) <= 20000)
d = mk(st); trim(d, e=dict(env, SHIPMIRACLE_STATUS_CAP="12000", SHIPMIRACLE_STATUS_KEEP="1"))
n = rd(d + "/docs/STATUS.md")
check("env SHIPMIRACLE_STATUS_CAP / SHIPMIRACLE_STATUS_KEEP configure the rule", len(n.encode()) <= 12000 and "Entry (19 Oct" in n.split("## Archived index")[0] and "Entry (18 Oct" not in n.split("## Archived index")[0])
check("bad --cap is refused", trim(d, "--cap", "abc").returncode == 2)

# --- recency by date, not by file position ----------------------------------------------------------------
st2 = HEAD + chap(1) + chap(15) + chap(9) + TAIL
d = mk(st2); trim(d, "--keep", "1", "--cap", "99999"); n = rd(d + "/docs/STATUS.md").split("## Archived index")[0]
check("keeps the newest by date even when it is not first in the file", "Entry (15 Oct" in n and "Entry (1 Oct" not in n and "Entry (9 Oct" not in n)

# --- git: dirty refusal --------------------------------------------------------------------------------
d = mk(st); git(d, "init", "-q"); git(d, "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A"); git(d, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "i")
open(d + "/docs/STATUS.md", "a").write("\nedit\n"); before = rd(d + "/docs/STATUS.md")
r = trim(d, strict=True)
check("refuses a dirty STATUS.md, changes nothing", r.returncode == 3 and "uncommitted" in r.stderr and rd(d + "/docs/STATUS.md") == before and not archived(d), (r.returncode, r.stderr))
check("--dry works on a dirty file", trim(d, "--dry").returncode == 0)
r = trim(d, "--force")
check("--force overrides", r.returncode == 0 and len(rd(d + "/docs/STATUS.md").encode()) < len(before.encode()))
d = mk(st); git(d, "init", "-q"); git(d, "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A"); git(d, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "i")
check("clean tree: runs", trim(d, strict=True).returncode == 0)

# --- edge cases ------------------------------------------------------------------------------------------
fence = HEAD + chap(19) + "## Code (3 Oct 2026)\n```\n## not a heading (19 Oct 2026)\n```\ntail\n\n" + TAIL
d = mk(fence); trim(d, "--keep", "1", "--cap", "99999"); a = archived(d)
check("a '## ' line inside a code fence is not a chapter", "## not a heading (19 Oct 2026)" in a.get("2026-10-code-3-oct-2026.md", "") and "tail" in a.get("2026-10-code-3-oct-2026.md", ""), list(a))
crlf = (HEAD + chap(19) + chap(2) + TAIL).replace("\n", "\r\n"); d = mk(crlf); trim(d, "--keep", "1", "--cap", "99999")
check("CRLF text is kept byte for byte", "Entry (19 Oct 2026)\r\n" in rd(d + "/docs/STATUS.md") and "\r\n" in "".join(archived(d).values()))
und = HEAD + chap(19) + "## Notes\nundated small\n\n## Huge undated\n" + big * 20 + "\n" + TAIL; d = mk(und); trim(d, "--keep", "1")
n = rd(d + "/docs/STATUS.md").split("## Archived index")[0]
check("undated chapters stay only if they fit", "## Notes" in n and "Huge undated" not in n)
dup = HEAD + "".join(f"## Same (1{k} Oct 2026)\nbody {k}\n\n" for k in (1, 2)) + "## Same (12 Oct 2026)\nbody x\n\n" + TAIL; d = mk(dup); trim(d, "--keep", "0")
check("headings with equal slugs keep every body", "body x" in "".join(archived(d).values()) and "body 1" in "".join(archived(d).values()))
nohead = "# only a title\n\nno chapters here\n"; d = mk(nohead); r = trim(d)
check("file without chapters is untouched", r.returncode == 0 and rd(d + "/docs/STATUS.md") == nohead)
check("missing STATUS.md fails closed", trim(tempfile.mkdtemp()).returncode == 2)
d = mk(st); trim(d, "--keep", "0", "--cap", "1000"); n = rd(d + "/docs/STATUS.md")
check("protected sections survive an impossible cap (warning, not loss)", "doing X" in n and "resume with Z" in n and "still over" in trim(d, "--keep", "0", "--cap", "1000").stdout + "still over")
pre = HEAD + "## Archived index\nArchived: Old -> docs/status-archive/x.md\n\n" + chap(19) + chap(2) + TAIL; d = mk(pre); trim(d, "--keep", "1", "--cap", "99999"); n = rd(d + "/docs/STATUS.md")
check("existing Archived index is extended, not duplicated", n.count("## Archived index") == 1 and "Archived: Old ->" in n and "Archived: Entry (2 Oct 2026)" in n)

# --- security: symlinks, non-git, concurrent write, modes ---------------------------------------------------
d = mk(st); r = trim(d, strict=True)
check("non-git folder is refused without --force", r.returncode == 2 and "not a git repository" in r.stderr and rd(d + "/docs/STATUS.md") == st and not archived(d), r.stderr)
check("non-git folder: --dry still works and writes nothing", trim(d, "--dry", strict=True).returncode == 0 and rd(d + "/docs/STATUS.md") == st)
d = mk(st); real = d + "/real.md"; os.rename(d + "/docs/STATUS.md", real); os.symlink(real, d + "/docs/STATUS.md")
r = trim(d, "--dry")
check("STATUS.md symlink is refused (even --dry/--force)", r.returncode == 2 and "symlink" in r.stderr and trim(d).returncode == 2 and rd(real) == st, r.stderr)
d = mk(st); out = tempfile.mkdtemp(); os.symlink(out, d + "/docs/status-archive")
r = trim(d)
check("status-archive symlink is refused, nothing written outside", r.returncode == 2 and "symlink" in r.stderr and os.listdir(out) == [] and rd(d + "/docs/STATUS.md") == st, r.stderr)
d = mk(st); os.makedirs(d + "/docs/status-archive"); out = tempfile.mkdtemp(); os.symlink(out + "/x", d + "/docs/status-archive/2026-10-entry-16-oct-2026.md")
r = trim(d, "--keep", "3")
check("a symlinked archive file is refused", r.returncode == 2 and os.listdir(out) == [] and rd(d + "/docs/STATUS.md") == st, r.stderr)
d = mk(st); out = tempfile.mkdtemp(); os.rename(d + "/docs", out + "/docs"); os.symlink(out + "/docs", d + "/docs")
check("docs folder symlink escaping the project is refused", trim(d).returncode == 2)
d = mk(st); em = dict(env, SHIPMIRACLE_TEST="1", SHIPMIRACLE_TRIM_TEST_MUTATE="\nLATE EDIT\n")
r = trim(d, e=em); n = rd(d + "/docs/STATUS.md")
check("STATUS.md changed between read and write: abort, exit 3, concurrent edit kept", r.returncode == 3 and n == st + "\nLATE EDIT\n" and "changed while trimming" in r.stderr, (r.returncode, r.stderr))
d = mk(st); r = trim(d, e=dict({k: v for k, v in env.items() if k != "SHIPMIRACLE_TEST"}, SHIPMIRACLE_TRIM_TEST_MUTATE="\nLATE EDIT\n"))     # no SHIPMIRACLE_TEST, whatever the caller exported
check("the mutate hook is ignored outside SHIPMIRACLE_TEST=1", r.returncode == 0 and "LATE EDIT" not in rd(d + "/docs/STATUS.md"))
d = mk(st); os.chmod(d + "/docs/STATUS.md", 0o640); trim(d, "--keep", "1")
check("STATUS.md keeps its mode", os.stat(d + "/docs/STATUS.md").st_mode & 0o777 == 0o640, oct(os.stat(d + "/docs/STATUS.md").st_mode))
d = mk(st); os.makedirs(d + "/docs/status-archive"); af = d + "/docs/status-archive/2026-10-entry-16-oct-2026.md"
open(af, "w").write("# pre\n"); os.chmod(af, 0o600); trim(d, "--keep", "3")
check("an existing archive file keeps its mode", os.stat(af).st_mode & 0o777 == 0o600 and "## Entry (16 Oct 2026)" in rd(af))
um = os.umask(0o022); d = mk(st); trim(d, "--keep", "1"); os.umask(um)
nf = [f for f in os.listdir(d + "/docs/status-archive")][0]
check("new archive files get 0666 & ~umask (not mkstemp 0600)", os.stat(d + "/docs/status-archive/" + nf).st_mode & 0o777 == 0o644, oct(os.stat(d + "/docs/status-archive/" + nf).st_mode))

# --- 165 KB synthetic file ends under the cap --------------------------------------------------------------
huge = HEAD + "".join(f"## Chapter {i} ({(i % 28) + 1} {'Sep' if i < 28 else 'Oct'} 2026)\n" + ("line of text about work\n" * 150) for i in range(47)) + TAIL
check("synthetic file is >= 165 KB", len(huge) >= 165000, len(huge))
d = mk(huge); r = trim(d)
n = rd(d + "/docs/STATUS.md")
check("165 KB synthetic STATUS ends under 20 KB", len(n.encode()) <= 20000, len(n))
check("165 KB: all text still in STATUS + archive", sum(len(v) for v in archived(d).values()) + len(n) >= len(huge))

# --- status-extract (brief) ------------------------------------------------------------------------------
d = mk(st.replace("## Older ISO", "## Verified\n" + big + "\n## Older ISO"))
b = run(WS + "/bin/status-extract", d).stdout
check("brief under 8 KB and keeps In progress/Next/Handoff in full", len(b) < 8000 and "doing X" in b and "1. Y" in b and "resume with Z" in b and "Updated: 2026-10-20" in b, len(b))
check("brief shows a noisy section only as heading + first line", "## Verified\nx line  …" in b)
check("brief reports the STATUS size", re.search(r"STATUS\.md is \d+\.\d KB", b) is not None and "run bin/status-trim in the Shipmiracle engine folder" in b, b[-300:])
b = run(WS + "/bin/status-extract", d, e=dict(env, SHIPMIRACLE_BRIEF_CAP="3000")).stdout
check("SHIPMIRACLE_BRIEF_CAP still limits the optional part", len(b) < 6500 and "doing X" in b, len(b))
d = mk(HEAD + TAIL); b = run(WS + "/bin/status-extract", d).stdout
check("small STATUS: no trim hint", "run ~/Developer" not in b and "doing X" in b)
print("ALL PASS" if not fails else "FAILED %s" % fails); sys.exit(1 if fails else 0)
