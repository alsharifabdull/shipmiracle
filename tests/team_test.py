#!/usr/bin/env python3
"""shipmiracle/team.py and `shipm team show|add|check` (CHECKLIST G6): the project Team table in docs/SKILLS.md.
Covers parse/render, hostile blocks, alias and plugin names, add/show/check on fixtures, `shipm skills view --write` keeping a hand-edited block
byte for byte, the cross-project refusal from a chat, symlink/FIFO files (no hang), atomic write and exit codes.
Everything runs under SHIPMIRACLE_TEST=1 in temp folders. Run: python3 tests/team_test.py (Python 3.9 ok)"""
import json, os, pathlib, shutil, signal, subprocess, sys, tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = pathlib.Path(tempfile.mkdtemp(prefix="shipmiracle-team-")).resolve()
ENV = dict(os.environ, SHIPMIRACLE_TEST="1", SHIPMIRACLE_HOME=str(TMP / "home"), SHIPMIRACLE_STATE=str(TMP / "state"), SHIPMIRACLE_CONFIG=str(TMP / "cfg"),
           SHIPMIRACLE_DEV=str(TMP / "dev"), SHIPMIRACLE_WS=str(ROOT), HOME=str(TMP / "home"), CLAUDE_CONFIG_DIR=str(TMP / "home" / ".claude"),
           GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null")
for k in ("CLAUDECODE", "SHIPMIRACLE_ENFORCE_OWNER", "CLAUDE_PROJECT_DIR"):
    ENV.pop(k, None)
os.environ.update(ENV)
from shipmiracle import team as T, skills as S, UsageError, SafetyError  # noqa: E402

fails = 0
n = 0


def check(name, ok, info=""):
    global fails, n
    n += 1
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(info)[:600]))
    fails += 0 if ok else 1


def shipm(*args, cwd=None, chat=False, timeout=30):
    env = dict(ENV)
    if chat:
        env["CLAUDECODE"] = "1"
    r = subprocess.run([sys.executable, str(ROOT / "bin" / "shipm")] + list(args), cwd=str(cwd or TMP), env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=timeout)
    return r.returncode, r.stdout, r.stderr


def mkproj(name, skills_md=None):
    d = TMP / "dev" / name
    (d / "docs").mkdir(parents=True)
    subprocess.run(["git", "-C", str(d), "init", "-q"], env=ENV, check=True)
    (d / "CLAUDE.md").write_text("# %s\n- Stack: Web app (React)\n" % name)
    if skills_md is not None:
        (d / "docs" / "SKILLS.md").write_bytes(skills_md if isinstance(skills_md, bytes) else skills_md.encode())
    return d


def block(*rows, eol="\n"):
    return eol.join([T.BEGIN, T.HEADER_LINE, T.SEP_LINE] + list(rows) + [T.END]) + eol


R_BUILD = "| build | builder-backend | - | API and data work |"
R_TEST = "| test | verifier | - | runs the tests |"
R_REV = "| review | reviewer | - | reads the diff |"

# ------------------------------------------------------------------ parse / render
t = T.parse_text("x\n## Team\n" + block(R_BUILD, R_TEST) + "tail\n")
check("parse: two valid rows", t.state == "ok" and [r["agent"] for r in t.rows] == ["builder-backend", "verifier"] and not t.ignored, t)
rt = T.render_block(t.rows)
t2 = T.parse_text(rt)
check("render -> parse round trip gives the same rows", t2.rows == t.rows and rt == block(R_BUILD, R_TEST), rt)
check("no markers -> none", T.parse_text("# nothing\n").state == "none")
check("missing file -> none", T.parse_text(None, "").state == "none")
check("unreadable reason -> unreadable", T.parse_text(None, "is a symbolic link").state == "unreadable")
check("block with only the header row -> none (0 valid rows = no table)", T.parse_text(block()).state == "none")
check("rows with skills split", T.parse_text(block("| build | builder | a, b | w |")).rows[0]["skills"] == ["a", "b"])
check("CRLF block parses", T.parse_text(block(R_BUILD, R_TEST, eol="\r\n")).state == "ok" and len(T.parse_text(block(R_BUILD, R_TEST, eol="\r\n")).rows) == 2)
check("tab inside a cell -> row ignored, reported", T.parse_text(block("| build | builder\tx | - | w |", R_TEST)).ignored[0][1].startswith("agent has control"), T.parse_text(block("| build | builder\tx | - | w |", R_TEST)))
for label, bad in (("backtick", "| build | `builder` | - | w |"), ("bidi", "| build | builder | - | a‮b |"), ("zero-width", "| build | build​er | - | w |"),
                   ("extra pipe", "| build | builder | - | a | b |"), ("too few cells", "| build | builder | w |"), ("bad role", "| Build! | builder | - | w |"),
                   ("empty why", "| build | builder | - |  |"), ("not a row", "build builder - w"), ("bad agent", "| build | ../etc | - | w |")):
    tt = T.parse_text(block(bad, R_TEST))
    check("hostile row (%s) ignored and reported, valid row kept" % label, tt.state == "ok" and len(tt.rows) == 1 and len(tt.ignored) == 1, tt)
tt = T.parse_text(block(R_BUILD, "| build | builder-backend | - | again |"))
check("duplicate row ignored and reported", len(tt.rows) == 1 and "duplicate" in tt.ignored[0][1], tt)
tt = T.parse_text(block("| test | qa-engineer | - | w |", "| test | verifier | - | w |"))
check("alias and its target are the same agent (duplicate)", len(tt.rows) == 1 and tt.rows[0]["agent"] == "verifier" and tt.rows[0]["agent_raw"] == "qa-engineer", tt)
tt = T.parse_text(block("| review | security-reviewer | - | w |", "| build | myplug:helper | - | w |"))
check("alias is normalised, plugin:name kept", [r["agent"] for r in tt.rows] == ["reviewer", "myplug:helper"], tt)
many = block(*["| build | agent-%d | - | w |" % i for i in range(T.MAX_ROWS + 10)])
tt = T.parse_text(many)
check("many rows: capped at %d, the rest reported" % T.MAX_ROWS, len(tt.rows) == T.MAX_ROWS and len(tt.ignored) == 10, (len(tt.rows), len(tt.ignored)))
huge = block(*["| build | agent-%d | - | %s |" % (i, "x" * 190) for i in range(100)])
check("block over 16 KB -> damaged (not parsed)", len(huge.encode()) > T.MAX_BLOCK and T.parse_text(huge).state == "damaged", T.parse_text(huge).detail)
check("two blocks -> damaged", T.parse_text(block(R_BUILD) + block(R_TEST)).state == "damaged")
check("nested markers -> damaged", T.parse_text(T.BEGIN + "\n" + block(R_BUILD)).state == "damaged")
check("end before begin -> damaged", T.parse_text(T.END + "\n" + T.BEGIN + "\n").state == "damaged")
check("begin without end -> damaged", T.parse_text(T.BEGIN + "\n" + R_BUILD + "\n").state == "damaged")
check("a marker inside other text is not a marker", T.parse_text("see %s in the docs\n" % T.BEGIN).state == "none")
try:
    T.render_block([{"role": "build", "agent": "a%d" % i, "skills": [], "why": "x" * 190} for i in range(100)]); ok = False
except UsageError:
    ok = True
check("render refuses a block over 16 KB", ok)
try:
    T.render_row("build", "builder", [], "a|b"); ok = False
except UsageError:
    ok = True
check("render refuses a pipe in a cell", ok)
check("team_rows on a missing project is [] (never raises)", T.team_rows(TMP / "nope") == [])

# ------------------------------------------------------------------ files: symlink, FIFO, size, NUL
P = mkproj("files")
(P / "docs" / "SKILLS.md").write_text(block(R_BUILD))
check("team_rows reads a regular file", len(T.team_rows(P)) == 1)
os.remove(str(P / "docs" / "SKILLS.md"))
(TMP / "real.md").write_text(block(R_BUILD))
os.symlink(str(TMP / "real.md"), str(P / "docs" / "SKILLS.md"))
check("symlinked SKILLS.md is not followed", T.team_rows(P) == [] and T.load(P).state == "unreadable", T.load(P))
os.remove(str(P / "docs" / "SKILLS.md"))
os.mkfifo(str(P / "docs" / "SKILLS.md"))


def alarm(sec):
    signal.alarm(sec)


signal.signal(signal.SIGALRM, lambda *_a: (_ for _ in ()).throw(TimeoutError("hang")))
alarm(5)
try:
    st = T.load(P).state
except TimeoutError:
    st = "HANG"
alarm(0)
check("FIFO SKILLS.md: no hang, unreadable", st == "unreadable", st)
rc, out, err = shipm("team", "check", str(P), timeout=15)
check("shipm team check on a FIFO: exit 1, no hang", rc == 1 and "not a regular file" in out, (rc, out, err))
rc, out, err = shipm("team", "add", "verifier", "--role", "test", "--why", "w", str(P), timeout=15)
check("shipm team add on a FIFO is refused, FIFO untouched", rc == 4 and os.path.exists(str(P / "docs/SKILLS.md")) and not (P / "docs/SKILLS.md").is_file(), (rc, out, err))
os.remove(str(P / "docs" / "SKILLS.md"))
(P / "docs" / "SKILLS.md").write_text("x" * (T.MAX_FILE + 1))
check("file over 64 KB: unreadable", T.load(P).state == "unreadable" and "64 KB" in T.load(P).detail)
(P / "docs" / "SKILLS.md").write_bytes(b"a\x00b")
check("NUL byte: unreadable", T.load(P).state == "unreadable")
(P / "docs" / "SKILLS.md").write_bytes(b"\xff\xfe")
check("not UTF-8: unreadable", T.load(P).state == "unreadable")
check("exactly 64 KB is accepted", (lambda: ((P / "docs" / "SKILLS.md").write_text(block(R_BUILD) + "y" * (T.MAX_FILE - len(block(R_BUILD)))), T.load(P).state)[1])() == "ok")

# ------------------------------------------------------------------ add / show / check on fixtures
HOME = TMP / "home"
plug = HOME / ".claude" / "plugins" / "cache" / "mk" / "myplug" / "1.0" / "agents"
plug.mkdir(parents=True)
(plug / "helper.md").write_text("---\nname: helper\n---\nx\n")
A = mkproj("alpha")
rc, out, err = shipm("team", "show", cwd=A)
check("show with no table: exit 0, says so", rc == 0 and "no team table" in out, (rc, out, err))
rc, out, err = shipm("team", "check", cwd=A)
check("check with no table: exit 1", rc == 1 and "no Team table" in out, (rc, out))
rc, out, err = shipm("team", "add", "builder-backend", "--role", "build", "--why", "API and data work", cwd=A)
check("add creates the file and the block", rc == 0 and (A / "docs/SKILLS.md").read_text() == "## Team\n" + block(R_BUILD), (rc, out, err, (A / "docs/SKILLS.md").read_text()))
rc, out, err = shipm("team", "add", "builder-backend", "--role", "build", "--why", "again", cwd=A)
check("add of the same agent is refused (exit 2)", rc == 2 and "already on the team" in err, (rc, err))
rc, out, err = shipm("team", "add", "backend-engineer", "--role", "build", "--why", "alias of builder-backend", cwd=A)
check("add of an alias of a member is refused", rc == 2 and "already on the team" in err, (rc, err))
rc, out, err = shipm("team", "add", "no-such-agent", "--role", "build", "--why", "w", cwd=A)
check("add of an unknown agent is refused, file unchanged", rc == 2 and "does not resolve" in err and (A / "docs/SKILLS.md").read_text() == "## Team\n" + block(R_BUILD), (rc, err))
rc, out, err = shipm("team", "add", "qa-engineer", "--role", "test", "--why", "runs the tests", cwd=A)
txt = (A / "docs/SKILLS.md").read_text()
check("add of an old name stores the new agent name", rc == 0 and "| test | verifier | - | runs the tests |" in txt and "qa-engineer" not in txt, (rc, err, txt))
rc, out, err = shipm("team", "add", "myplug:helper", "--role", "support", "--why", "helps", cwd=A)
check("add of a plugin agent works", rc == 0 and "| support | myplug:helper | - | helps |" in (A / "docs/SKILLS.md").read_text(), (rc, err))
rc, out, err = shipm("team", "add", "nope:helper", "--role", "support", "--why", "w", cwd=A)
check("add of a plugin agent that is not installed is refused", rc == 2, (rc, err))
for label, role, why in (("pipe in why", "design", "a|b"), ("backtick in why", "design", "a`b"), ("bidi in why", "design", "a\u202eb"), ("empty why", "design", ""), ("bad role", "Bad Role", "w")):
    rc, out, err = shipm("team", "add", "designer", "--role", role, "--why", why, cwd=A)
    check("add refuses %s" % label, rc == 2 and "designer" not in (A / "docs/SKILLS.md").read_text(), (rc, err))
rc, out, err = shipm("team", "add", "designer", "--role", "design", "--why", "w", "--skills", "ghost-skill,other", cwd=A)
check("add with skills writes them (existence is a check matter)", rc == 0 and "| design | designer | ghost-skill, other | w |" in (A / "docs/SKILLS.md").read_text(), (rc, err))
rc, out, err = shipm("team", "show", cwd=A)
check("show lists the rows", rc == 0 and "builder-backend" in out and "verifier" in out and "myplug:helper" in out, out)
rc, out, err = shipm("team", "show", "--json", cwd=A)
j = json.loads(out)
check("show --json", j["v"] == 1 and j["state"] == "ok" and len(j["rows"]) == 4, out)
rc, out, err = shipm("team", "check", cwd=A)
check("check: no reviewer, a missing skill and a role mismatch -> exit 1 with each finding", rc == 1 and "no team member has the review role" in out and "ghost-skill is not installed" in out and "Role cell says support but its effective role is support" not in out, out)
rc, out, err = shipm("team", "add", "reviewer", "--role", "review", "--why", "reads the diff", cwd=A)
# clean fixture
B = mkproj("beta")
for ag, role in (("builder-backend", "build"), ("verifier", "test"), ("reviewer", "review")):
    shipm("team", "add", ag, "--role", role, "--why", "w", cwd=B)
rc, out, err = shipm("team", "check", cwd=B)
check("check: clean team -> exit 0", rc == 0 and "team ok" in out, (rc, out, err))
rc, out, err = shipm("team", "check", "--json", cwd=B)
check("check --json clean", rc == 0 and json.loads(out)["ok"] is True, out)
txt = (B / "docs/SKILLS.md").read_text().replace("| build | builder-backend", "| test | builder-backend")
(B / "docs/SKILLS.md").write_text(txt)
rc, out, err = shipm("team", "check", cwd=B)
check("check: Role cell differs from the effective role -> warning only, exit 3", rc == 3 and out.startswith("warn:") and "effective role is build" in out, (rc, out))
(B / "docs/SKILLS.md").write_text(txt.replace("| test | builder-backend", "| build | builder-backend"))
(B / "docs/SKILLS.md").write_text((B / "docs/SKILLS.md").read_text().replace(T.END, "garbage line\n" + T.END))
rc, out, err = shipm("team", "check", cwd=B)
check("check: a broken row is reported as a warning (exit 3)", rc == 3 and "not a table row" in out, (rc, out))
(B / "docs/SKILLS.md").write_text((B / "docs/SKILLS.md").read_text().replace("garbage line\n", "| build | ghost-agent | - | w |\n"))
rc, out, err = shipm("team", "check", cwd=B)
check("check: an unknown agent in the file -> exit 1", rc == 1 and "ghost-agent does not resolve" in out, (rc, out))
(B / "docs/SKILLS.md").write_text((B / "docs/SKILLS.md").read_text().replace("| build | ghost-agent | - | w |\n", ""))
S_ = "## Team\n" + block(R_BUILD, R_TEST, R_REV)
(B / "docs/SKILLS.md").write_text(S_)
(B / ".claude" / "skills" / "present").mkdir(parents=True)
shipm("team", "add", "designer", "--role", "design", "--why", "w", "--skills", "present", cwd=B)
rc, out, err = shipm("team", "check", cwd=B)
check("check: an installed skill is fine", rc == 0, (rc, out))
rc, out, err = shipm("team", "check", str(B), cwd=TMP)
check("check accepts a project argument", rc == 0, (rc, out, err))
rc, out, err = shipm("team", "show", "beta", cwd=TMP)
check("show accepts a project name", rc == 0 and "builder-backend" in out, (rc, out, err))
rc, out, err = shipm("team", "show", "no-such-project-xyz", cwd=TMP)
check("show of an unknown project -> exit 3", rc == 3, (rc, err))
rc, out, err = shipm("team", "show", "--role", "x", cwd=B)
check("--role on show is a usage error", rc == 2, (rc, err))
rc, out, err = shipm("team", "add", cwd=B)
check("add without an agent is a usage error", rc == 2, (rc, err))

# add keeps every other byte of an existing file and block
orig = "# SKILLS\nintro\n\n## Team\n" + T.BEGIN + "\r\n" + T.HEADER_LINE + "\r\n" + T.SEP_LINE + "\r\n" + R_BUILD + "\r\nnote line\r\n" + T.END + "\r\nafter\n"
C = mkproj("gamma", orig)
rc, out, err = shipm("team", "add", "verifier", "--role", "test", "--why", "w", cwd=C)
new = (C / "docs/SKILLS.md").read_bytes().decode()
check("add into an existing CRLF block keeps all other bytes and the line ending", rc == 0 and new == orig.replace("note line\r\n", "note line\r\n| test | verifier | - | w |\r\n"), (rc, err, new))
D = mkproj("delta", "# SKILLS\nsome text without newline at end")
shipm("team", "add", "verifier", "--role", "test", "--why", "w", cwd=D)
check("add to a file without a block appends one, text before stays", (D / "docs/SKILLS.md").read_text().startswith("# SKILLS\nsome text without newline at end\n\n## Team\n" + T.BEGIN), (D / "docs/SKILLS.md").read_text())
E = mkproj("eps", "x\n" + block(R_BUILD) + block(R_TEST))
rc, out, err = shipm("team", "add", "verifier", "--role", "test", "--why", "w", cwd=E)
check("add into a damaged block is refused, file unchanged", rc == 2 and "damaged" in err and (E / "docs/SKILLS.md").read_text() == "x\n" + block(R_BUILD) + block(R_TEST), (rc, err))
rc, out, err = shipm("team", "check", cwd=E)
check("check of a damaged block -> exit 1", rc == 1 and "damaged" in out, (rc, out))
nearly = block(*(["| build | agent-%d | - | w |" % i for i in range(5)] + ["filler note " + "x" * 200 for i in range(75)]))
check("fixture: block just under 16 KB", len(nearly.encode()) < T.MAX_BLOCK and len(nearly.encode()) > T.MAX_BLOCK - 400, len(nearly.encode()))
F = mkproj("zeta", nearly)
rc, out, err = shipm("team", "add", "verifier", "--role", "test", "--why", "x" * 190, cwd=F)
check("add that would pass 16 KB is refused, file unchanged", rc == 2 and "16 KB" in err and (F / "docs/SKILLS.md").read_text() == nearly, (rc, err))

# ------------------------------------------------------------------ cross-project refusal from a chat
H = mkproj("theta")
I = mkproj("iota")
rc, out, err = shipm("team", "add", "verifier", "--role", "test", "--why", "w", "iota", cwd=H, chat=True)
check("a chat in project theta cannot add to iota (exit 4), nothing written", rc == 4 and not (I / "docs/SKILLS.md").exists(), (rc, err))
rc, out, err = shipm("team", "add", "verifier", "--role", "test", "--why", "w", str(I), cwd=H, chat=True)
check("same with a path", rc == 4 and not (I / "docs/SKILLS.md").exists(), (rc, err))
rc, out, err = shipm("team", "add", "verifier", "--role", "test", "--why", "w", "theta", cwd=H, chat=True)
check("a chat may add to its own project (by name)", rc == 0 and (H / "docs/SKILLS.md").exists(), (rc, err))
rc, out, err = shipm("team", "add", "reviewer", "--role", "review", "--why", "w", cwd=H, chat=True)
check("a chat may add with no project argument", rc == 0, (rc, err))
rc, out, err = shipm("team", "show", "iota", cwd=H, chat=True)
check("a chat may read another project's team", rc == 0, (rc, err))
rc, out, err = shipm("team", "add", "verifier", "--role", "test", "--why", "w", "iota", cwd=H)
check("the owner at a terminal may add to another project", rc == 0 and (I / "docs/SKILLS.md").exists(), (rc, err))

# ------------------------------------------------------------------ shipm skills view keeps the block
hand = ("hand text that will be regenerated\nSkills review: 2026-09-02\nReviewed stack: web\n\n## Team\n" + T.BEGIN + "\r\n" + T.HEADER_LINE + "\r\n" + T.SEP_LINE + "\r\n"
        + R_BUILD + "\r\n|   test   |  verifier |   -   |  odd   spacing  |\r\nfree note ü — text\r\n" + T.END + "\r\n")
K = mkproj("kappa", hand)
want = hand[hand.index(T.BEGIN):hand.index(T.END) + len(T.END) + 2]
outs = []
for i in range(3):
    rc, out, err = shipm("skills", "view", "kappa", "--write", cwd=K)
    got = (K / "docs/SKILLS.md").read_bytes().decode()
    outs.append(got)
    check("skills view --write run %d: exit 0 and the Team block is byte for byte the same" % (i + 1), rc == 0 and want in got, (rc, err, got[:800]))
check("skills view: second and third run give identical files", outs[0] == outs[1] == outs[2])
check("skills view: header says do not edit outside the Team block", "do not edit outside the Team block" in outs[0].splitlines()[0])
check("skills view: still regenerates the rest (hand text gone, review line kept)", "hand text" not in outs[0] and "\nSkills review: 2026-09-02\n" in outs[0])
check("skills view: heading precedes the block", "## Team\n" + T.BEGIN in outs[0])
check("team rows survive the regeneration", [r["agent"] for r in T.team_rows(K)] == ["builder-backend", "verifier"])
Lp = mkproj("lambda", "Skills review: 2026-09-02\nReviewed stack: web\n")
shipm("skills", "view", "lambda", "--write", cwd=Lp)
got = (Lp / "docs/SKILLS.md").read_text()
check("skills view: no block in, no block invented", T.BEGIN not in got and "## Team" not in got and T.team_rows(Lp) == [])
Mp = mkproj("mu", "old\n" + block(R_BUILD) + block(R_TEST))
rc, out, err = shipm("skills", "view", "mu", "--write", cwd=Mp)
check("skills view: a damaged block is not regenerated over (exit 4, file unchanged)", rc == 4 and (Mp / "docs/SKILLS.md").read_text() == "old\n" + block(R_BUILD) + block(R_TEST), (rc, err))
rc, out, err = shipm("skills", "view", "mu", cwd=Mp)
check("skills view dry run of a damaged block also refuses", rc == 4, (rc, err))
Np = mkproj("nu", block(*["| build | agent-%d | - | %s |" % (i, "x" * 190) for i in range(100)]))
rc, out, err = shipm("skills", "view", "nu", "--write", cwd=Np)
check("skills view: a block over 16 KB is refused, file unchanged", rc == 4 and "16 KB" in err, (rc, err))
Op = mkproj("omicron")
os.symlink(str(TMP / "real.md"), str(Op / "docs/SKILLS.md"))
rc, out, err = shipm("skills", "view", "omicron", "--write", cwd=Op)
check("skills view: a symlinked SKILLS.md is refused and the link target untouched", rc == 4 and (TMP / "real.md").read_text() == block(R_BUILD), (rc, err))
Qp = mkproj("pi")
os.mkfifo(str(Qp / "docs/SKILLS.md"))
rc, out, err = shipm("skills", "view", "pi", "--write", cwd=Qp, timeout=15)
check("skills view: a FIFO SKILLS.md does not hang and is refused", rc == 4, (rc, err))

# ------------------------------------------------------------------ atomic write
Rp = mkproj("rho", "# keep me\n")
real_replace = os.replace


def boom(*_a, **_k):
    raise KeyboardInterrupt()


os.replace = boom
try:
    try:
        T.add_row(Rp, "verifier", "test", "w")
    except KeyboardInterrupt:
        pass
finally:
    os.replace = real_replace
check("atomic: an interruption before the rename leaves the old file and no temp file", (Rp / "docs/SKILLS.md").read_text() == "# keep me\n" and [f.name for f in (Rp / "docs").iterdir()] == ["SKILLS.md"], list((Rp / "docs").iterdir()))
T.add_row(Rp, "verifier", "test", "w")
check("atomic: afterwards a normal add works, mode 644", (Rp / "docs/SKILLS.md").stat().st_mode & 0o777 == 0o644 and len(T.team_rows(Rp)) == 1)


# ------------------------------------------------------------------ QA round: locking, full table, blanks, symlinked docs, permissions, fences
import concurrent.futures as cf
AGS = ["builder", "builder-frontend", "builder-backend", "builder-ops", "verifier", "reviewer", "designer", "scoper"]


def padd(pd, ag, **kw):
    return shipm("team", "add", ag, "--role", "build", "--why", "parallel " + ag, str(pd), **kw)


for trial in range(5):
    Pp = mkproj("par%d" % trial, "# S\n")
    with cf.ThreadPoolExecutor(8) as ex:
        res = list(ex.map(lambda ag: padd(Pp, ag), AGS))
    rows = T.load(Pp)
    check("parallel trial %d: 8 adds, all exit 0, all 8 rows present, no ignored rows" % trial,
          all(r[0] == 0 for r in res) and sorted(r["agent"] for r in rows.rows) == sorted(AGS) and not rows.ignored and rows.state == "ok", ([r[0:3:2] for r in res], rows))
Sp = mkproj("same", "# S\n")
with cf.ThreadPoolExecutor(2) as ex:
    res = list(ex.map(lambda _i: padd(Sp, "verifier"), range(2)))
codes = sorted(r[0] for r in res)
check("two parallel adds of the same agent: one succeeds, one is refused as duplicate", codes[0] == 0 and codes[1] == 2 and "already on the team" in "".join(r[2] for r in res) and len(T.team_rows(Sp)) == 1, res)
# lock timeout: hold the lock, add must fail with a clear message, not hang
from shipmiracle import state as ST
Tp = mkproj("locked", "# S\n")
T.LOCK_WAIT = 0.3
holder = None
with T._lock(Tp):
    T.LOCK_WAIT = 0.3
    try:
        import time as _t
        t0 = _t.time()
        T.add_row(Tp, "verifier", "test", "w")
        msg = "NO ERROR"
    except Exception as e:
        msg = str(e)
    el = _t.time() - t0
T.LOCK_WAIT = 10.0
check("lock held elsewhere: add gives a clear message after the wait, no hang, nothing written", "still running" in msg and el < 5 and T.team_rows(Tp) == [], (msg, el))

# full table
Fp = mkproj("full", "# S\n" + block(*["| build | agent-%d | - | w |" % i for i in range(T.MAX_ROWS)]))
rc, out, err = shipm("team", "add", "verifier", "--role", "test", "--why", "w", cwd=Fp)
check("add to a table with 40 rows is refused: the team is full", rc == 2 and "the team is full: 40 rows" in err, (rc, err))

# blanks
Bp = mkproj("blank", "# S\n")
for label, args in (("blank why", ["--role", "test", "--why", "   "]), ("blank role", ["--role", "  ", "--why", "w"]), ("blank skills", ["--role", "test", "--why", "w", "--skills", "  "]),
                    ("empty skill name in list", ["--role", "test", "--why", "w", "--skills", "a,,b"])):
    rc, out, err = shipm("team", "add", "verifier", *args, cwd=Bp)
    check("add refuses %s" % label, rc == 2 and T.team_rows(Bp) == [], (rc, err))

# symlinked docs folder
outside = TMP / "outside"; outside.mkdir()
Yp = mkproj("symdocs"); shutil.rmtree(str(Yp / "docs")); os.symlink(str(outside), str(Yp / "docs"))
rc, out, err = shipm("team", "add", "verifier", "--role", "test", "--why", "w", cwd=Yp)
check("docs/ that is a symlink: add refused (exit 4), nothing written outside", rc == 4 and not list(outside.iterdir()), (rc, err, list(outside.iterdir())))
(outside / "SKILLS.md").write_text(block(R_BUILD))
check("docs/ symlink: team_rows ignores the file behind it", T.team_rows(Yp) == [])
rc, out, err = shipm("team", "check", cwd=Yp)
check("docs/ symlink: check exit 1 and says why", rc == 1 and "symbolic link" in out, (rc, out))
rc, out, err = shipm("skills", "view", "symdocs", "--write", cwd=Yp)
check("docs/ symlink: skills view --write refused, outside file untouched", rc == 4 and (outside / "SKILLS.md").read_text() == block(R_BUILD), (rc, err))

# read-only docs folder: plain sentence, normal exit code
Wp = mkproj("ro", "# S\n")
os.chmod(str(Wp / "docs"), 0o555)
rc, out, err = shipm("team", "add", "verifier", "--role", "test", "--why", "w", cwd=Wp)
os.chmod(str(Wp / "docs"), 0o755)
check("read-only docs folder: plain sentence, exit 1, no 'unexpected error'", (rc == 1 and "cannot write docs/SKILLS.md" in err and "unexpected" not in err) or os.geteuid() == 0, (rc, err))

# show on a damaged block / unreadable
rc, out, err = shipm("team", "show", cwd=E)
check("show on a damaged block: exit 1 and the word damaged in the text", rc == 1 and "damaged" in out, (rc, out))
rc, out, err = shipm("team", "show", "--json", cwd=E)
check("show --json on a damaged block: exit 1", rc == 1 and json.loads(out)["state"] == "damaged", (rc, out))
Hp = mkproj("hugeblk", huge)
rc, out, err = shipm("team", "show", cwd=Hp)
check("show on a block over 16 KB: exit 1 damaged", rc == 1 and "damaged" in out, (rc, out))

# unknown project vs warnings: both exit 3, told apart
rc, out, err = shipm("team", "check", "no-such-project-xyz", cwd=TMP)
check("check of an unknown project: exit 3 with a 'shipm:' line on stderr and nothing on stdout", rc == 3 and err.startswith("shipm: ") and out == "", (rc, out, err))

# skill not installed: warning, row written
Kp = mkproj("skillwarn", "# S\n")
rc, out, err = shipm("team", "add", "designer", "--role", "design", "--why", "w", "--skills", "ghost", cwd=Kp)
check("add with a missing skill: exit 0, one warning line, row written", rc == 0 and "warning: skill ghost is not installed" in err and len(T.team_rows(Kp)) == 1, (rc, err))

# fenced example + real block
fenced = "# Format\n\n```\n" + block("| build | example-agent | - | an example |") + "```\n\nReal one:\n\n## Team\n" + block(R_BUILD, R_TEST) + "~~~\n" + T.BEGIN + "\n~~~\n"
ft = T.parse_text(fenced)
check("fenced example is ignored, the real block is the table", ft.state == "ok" and [r["agent"] for r in ft.rows] == ["builder-backend", "verifier"], ft)
check("only a fenced example: no table", T.parse_text("```\n" + block(R_BUILD) + "```\n").state == "none")
check("unclosed fence before the markers: damaged, never guessed", T.parse_text("```\n" + block(R_BUILD)).state == "damaged")
check("unclosed fence without markers: plain none", T.parse_text("```\ncode\n").state == "none")
Zp = mkproj("fenced", fenced)
before = T.block_text(fenced)
shipm("skills", "view", "fenced", "--write", cwd=Zp)
check("skills view keeps the real block when the doc also had a fenced example", before in (Zp / "docs/SKILLS.md").read_text() and "example-agent" not in (Zp / "docs/SKILLS.md").read_text(), (Zp / "docs/SKILLS.md").read_text()[:400])

# ------------------------------------------------------------------ help / registry
rc, out, err = shipm("--help")
check("shipm --help lists team", rc == 0 and "team" in out)
rc, out, err = shipm("team", "bogus")
check("unknown team action -> exit 2", rc == 2, (rc, err))

shutil.rmtree(str(TMP), ignore_errors=True)
print("\n%d checks, %d failed" % (n, fails))
sys.exit(1 if fails else 0)
