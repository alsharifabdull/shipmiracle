#!/usr/bin/env python3
"""'Found, not approved' for skills and plugins: shipmiracle/skills.py (found_scan, found_rows, approve, ignore, remove) and `shipm skills found|approve|ignore|remove`.
Everything runs in a temp world (SHIPMIRACLE_TEST=1, temp HOME / workspace / projects); nothing real is read or written, nothing is installed or removed,
no network, no child process (the remove runner is a stub). Run: python3 tests/skills_found_test.py (Python 3.9 ok)"""
import io, json, os, pathlib, shutil, sys, tempfile, contextlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = pathlib.Path(tempfile.mkdtemp(prefix="shipmiracle-found-")).resolve()
os.environ.update(SHIPMIRACLE_TEST="1", SHIPMIRACLE_HOME=str(TMP / "home"), SHIPMIRACLE_STATE=str(TMP / "state"), SHIPMIRACLE_CONFIG=str(TMP / "cfg"),
                  SHIPMIRACLE_DEV=str(TMP / "dev"), SHIPMIRACLE_WS=str(TMP / "ws"), HOME=str(TMP / "home"), CLAUDE_CONFIG_DIR=str(TMP / "home/.claude"))
for k in ("CLAUDECODE", "SHIPMIRACLE_ENFORCE_OWNER"):
    os.environ.pop(k, None)
from shipmiracle import ShipmiracleError, SafetyError, UsageError, skills as S, cli  # noqa: E402

fails = 0
n = 0


def check(name, ok, info=""):
    global fails, n
    n += 1
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(info)[:600]))
    fails += 0 if ok else 1


def mk(p, text="x"):
    p = pathlib.Path(p)
    p.mkdir(parents=True, exist_ok=True)
    (p / "SKILL.md").write_text(text)


WS, HOME = TMP / "ws", TMP / "home"
(WS / "skills").mkdir(parents=True)
APPROVED = ("# Approved\n\n## Approved\n- acme/skills@unpinned | grill | pressure test | global\n\n"
            "## Approved plugins\nprose line\n- plugin plug-a@mkt | a plugin\n\n"
            "## Retired\noldskill (gone)\n- oldplug@mkt | gone\n\n## Reference " + "catalog (not approved)\n- acme/x@unpinned | refonly | not read | global\n")   # assembled: the marker text must not appear in an exported test
(WS / "skills/APPROVED.md").write_text(APPROVED)
(WS / "skills/IGNORED.md").write_text("# ignored\n- ign1 | looked at it, not needed | 2026-10-27\n- ign2 |  | 2026-10-27\n- plug-ign@mkt | personal use | 2026-10-27\n")

ag = HOME / ".agents/skills"
for s in ("grill", "rogue", "oldskill", "ign1", "ign2"):
    mk(ag / s)
cs = HOME / ".claude/skills"
cs.mkdir(parents=True)
os.symlink("../../.agents/skills/grill", str(cs / "grill"))
mk(cs / "realdir")
(TMP / "elsewhere/foreign").mkdir(parents=True)
os.symlink(str(TMP / "elsewhere/foreign"), str(cs / "foreign"))
(cs / "synced/abc").mkdir(parents=True)
(HOME / ".claude/settings.json").write_text(json.dumps({"enabledPlugins": {"plug-a@mkt": True, "plug-x@mkt": True, "plug-off@mkt": False, "oldplug@mkt": True, "plug-ign@mkt": True}}))
(HOME / ".claude/plugins").mkdir(parents=True)
(HOME / ".claude/plugins/installed_plugins.json").write_text(json.dumps({"version": 2, "plugins": {"plug-a@mkt": [{}], "plug-x@mkt": [{}], "plug-off@mkt": [{}], "oldplug@mkt": [{}], "plug-ign@mkt": [{}]}}))
PD = TMP / "dev/proj"
mk(PD / ".agents/skills/psk1"); mk(PD / ".agents/skills/psk2"); mk(PD / ".agents/skills/grill")
(PD / "docs").mkdir(parents=True)
(PD / "docs/SKILLS.md").write_text("| psk2 | listed |\n")

fnd = S.found_scan(WS, HOME, [("proj", str(PD))])


def find(name, scope):
    return next((f for f in fnd if f["name"] == name and f["scope"] == scope), None)


def cls(name, scope):
    f = find(name, scope)
    return (f["cls"], f["level"]) if f else None


check("approved global skill: ok", cls("grill", "global") == ("approved", "ok"), fnd)
check("global skill not listed: unlisted FAIL", cls("rogue", "global") == ("unlisted", "FAIL"))
check("a symlink into ~/.agents counts once (no claude-scope row for grill)", find("grill", "claude") is None)
check("a real folder in ~/.claude/skills: unlisted FAIL", cls("realdir", "claude") == ("unlisted", "FAIL"))
check("a foreign symlink in ~/.claude/skills: unlisted FAIL", cls("foreign", "claude") == ("unlisted", "FAIL"))
check("synced/ is skipped with one info finding", cls("synced", "claude") == ("skipped", "info") and sum(f["name"] == "synced" for f in fnd) == 1)
check("retired and installed: FAIL with the remove hint", cls("oldskill", "global") == ("retired", "FAIL") and find("oldskill", "global")["hint"] == "shipm skills remove oldskill")
check("ignored with a reason: info", cls("ign1", "global") == ("ignored", "info"))
check("ignore line with an empty reason does not count: unlisted FAIL", cls("ign2", "global") == ("unlisted", "FAIL"))
check("enabled approved plugin: ok", cls("plug-a@mkt", "plugin") == ("approved", "ok"))
check("enabled unlisted plugin: FAIL", cls("plug-x@mkt", "plugin") == ("unlisted", "FAIL"))
check("installed but disabled unlisted plugin: info", cls("plug-off@mkt", "plugin") == ("unlisted", "info"))
check("retired plugin installed: FAIL", cls("oldplug@mkt", "plugin") == ("retired", "FAIL"))
check("ignored plugin: info", cls("plug-ign@mkt", "plugin") == ("ignored", "info"))
check("project skill not in APPROVED or docs/SKILLS.md: warn", cls("psk1", "project:proj") == ("unlisted", "warn"))
check("project skill listed in the project's docs/SKILLS.md: ok", cls("psk2", "project:proj") == ("approved", "ok"))
check("project skill that is an approved pack skill: ok", cls("grill", "project:proj") == ("approved", "ok"))
check("a plugin line is not read as a skill line", [a["skill"] for a in S.parse_approved(WS)].count("plug-a") == 0)
check("parse_plugins reads only the plugin section", list(S.parse_plugins(WS)) == ["plug-a@mkt"])

rows = S.found_rows(fnd, 5)
txt = "\n".join("%s %s" % r for r in rows)
check("rows: FAIL for unlisted global, claude-dir, enabled plugin, retired", all(any(l == "FAIL" and f in t for l, t in rows) for f in ("rogue", "realdir", "plug-x@mkt", "oldskill", "oldplug@mkt")), txt)
check("rows: disabled plugin and ignored items are info", any(l == "info" and "plug-off@mkt" in t for l, t in rows) and any(l == "info" and "ign1" in t for l, t in rows))
check("rows: project warn row names the project", any(l == "warn" and t.startswith("proj: project skills") and "psk1" in t for l, t in rows), txt)
check("rows: no ok 'every global skill' row while a global finding is open", not any(t.startswith("every global skill") for _l, t in rows))

# doctor_rows feeds the same rows
dr = S.doctor_rows(WS, HOME, now=1_800_000_000, projects_dir=str(TMP / "none"), project_list=[("proj", str(PD))])
check("doctor_rows includes the found rows", any(l == "FAIL" and "rogue" in t for l, t in dr) and any(l == "info" and "plug-off@mkt" in t for l, t in dr), dr)

# ------------------------------------------------------------------ approve
ag2 = HOME / ".agents"
mk(ag / "newsk", "---\nname: newsk\n---\nbody\n")
(ag2 / ".skill-lock.json").write_text(json.dumps({"version": 3, "skills": {"newsk": {"source": "acme/skills", "skillPath": "skills/x/newsk/SKILL.md", "skillFolderHash": "abc"}}}))
before = (WS / "skills/APPROVED.md").read_text().splitlines()
lock_before = S.load_lock(WS)
msg = S.approve("newsk", "tested it", None, WS, HOME)
after = (WS / "skills/APPROVED.md").read_text().splitlines()
added = [l for l in after if l not in before]
check("approve skill: exactly one new APPROVED line, pkg@unpinned, in the approved list", added == ["- acme/skills@unpinned | newsk | tested it | global"]
      and after.index(added[0]) < after.index("## Approved plugins"), (added, msg))
lk = S.load_lock(WS)
check("approve skill: exactly one lock entry with the tree hash of what is installed", set(lk) - set(lock_before) == {"newsk"} and lk["newsk"]["tree_sha256"] == S.tree_sha256(ag / "newsk")
      and lk["newsk"]["pkg"] == "acme/skills" and lk["newsk"]["commit"] == "unpinned", lk)
snap = ((WS / "skills/APPROVED.md").read_text(), (WS / "skills/skills.lock.json").read_text())
msg2 = S.approve("newsk", "again", None, WS, HOME)
check("approve skill is idempotent", "already approved" in msg2 and snap == ((WS / "skills/APPROVED.md").read_text(), (WS / "skills/skills.lock.json").read_text()), msg2)
check("the approved line parses and the doctor sees newsk as approved", any(a["skill"] == "newsk" for a in S.parse_approved(WS)) and S.found_scan(WS, HOME, [])[[f["name"] for f in S.found_scan(WS, HOME, [])].index("newsk")]["cls"] == "approved")
try:
    S.approve("realdir", "x", None, WS, HOME); ok = False
except SafetyError as e:
    ok = "ignore" in str(e) and "remove" in str(e) and "project-only" in str(e)
check("approve of a skill with no known source is refused and points to ignore / remove / project-only", ok and "realdir" not in (WS / "skills/APPROVED.md").read_text())
for bad in ("", "has | pipe", "two\nlines"):
    try:
        S.approve("newsk2", bad, None, WS, HOME); ok = False
    except UsageError:
        ok = True
    check("approve refuses a --why of %r" % bad, ok)
try:
    S.approve("oldskill", "x", None, WS, HOME); ok = False
except SafetyError:
    ok = True
check("approve refuses a retired name", ok)
before = (WS / "skills/APPROVED.md").read_text().splitlines()
S.approve("plug-x@mkt", "needed", None, WS, HOME)
after = (WS / "skills/APPROVED.md").read_text().splitlines()
added = [l for l in after if l not in before]
i0, i1 = after.index("## Approved plugins"), after.index("## Retired")
check("approve plugin: one line under ## Approved plugins, lock untouched", added == ["- plugin plug-x@mkt | needed"] and i0 < after.index(added[0]) < i1 and "plug-x@mkt" not in S.load_lock(WS))
snap = (WS / "skills/APPROVED.md").read_text()
check("approve plugin is idempotent", "already approved" in S.approve("plug-x@mkt", "needed", None, WS, HOME) and snap == (WS / "skills/APPROVED.md").read_text())
check("approved plugin is now ok in the scan", {f["name"]: f["cls"] for f in S.found_scan(WS, HOME, [])}["plug-x@mkt"] == "approved")

# ------------------------------------------------------------------ ignore
msg = S.ignore("rogue", "keeping it for a trial", WS, today="2026-10-28")
check("ignore appends '- name | reason | date'", (WS / "skills/IGNORED.md").read_text().endswith("- rogue | keeping it for a trial | 2026-10-28\n"), msg)
check("ignore twice changes nothing", "already ignored" in S.ignore("rogue", "other", WS, today="2026-10-29") and (WS / "skills/IGNORED.md").read_text().count("rogue") == 1)
try:
    S.ignore("zzz", "  ", WS); ok = False
except UsageError:
    ok = True
check("ignore without a reason is refused and writes nothing", ok and "zzz" not in (WS / "skills/IGNORED.md").read_text())
check("an ignored skill turns info in the scan", {(f["name"], f["scope"]): f["cls"] for f in S.found_scan(WS, HOME, [])}[("rogue", "global")] == "ignored")
W2 = TMP / "ws2"; (W2 / "skills").mkdir(parents=True)
S.ignore("abc", "why", W2, today="2026-10-28")
check("ignore creates skills/IGNORED.md with the header when missing", (W2 / "skills/IGNORED.md").read_text().startswith("# Ignored skills") and S.parse_ignored(W2)["abc"]["date"] == "2026-10-28")

# ------------------------------------------------------------------ remove
try:
    S.remove("rogue", HOME, is_tty=False, ask=lambda p: "y", run=lambda a: 0, out=lambda s: None); ok = False
except SafetyError as e:
    ok = "terminal" in str(e)
check("remove refuses without a tty", ok)
ran, said = [], []
rc = S.remove("rogue", HOME, is_tty=True, ask=lambda p: "n", run=lambda a: ran.append(a) or 0, out=said.append)
check("remove prints the exact command first; 'n' runs nothing", rc == 1 and not ran and said[0] == "would run: npx --yes skills@%s remove rogue -g -y" % S.SKILLS_NPM_VERSION, said)
rc = S.remove("rogue", HOME, is_tty=True, ask=lambda p: "y", run=lambda a: ran.append(a) or 0, out=said.append)
check("remove with y runs the printed command through the runner", rc == 0 and ran == [["npx", "--yes", "skills@%s" % S.SKILLS_NPM_VERSION, "remove", "rogue", "-g", "-y"]], ran)
said = []
S.remove("plug-off@mkt", HOME, is_tty=True, ask=lambda p: "n", run=lambda a: 0, out=said.append)
check("plugin removal command is printed for confirmation", said[0] == "would run: claude plugin uninstall plug-off@mkt", said)
try:
    S.remove("nothere", HOME, is_tty=True, ask=lambda p: "y", run=lambda a: 0, out=lambda s: None); ok = False
except ShipmiracleError:
    ok = True
check("remove refuses a name that is not installed", ok)

# ------------------------------------------------------------------ command line
def run(*argv, env=None):
    out, err = io.StringIO(), io.StringIO()
    old = dict(os.environ)
    os.environ.update(env or {})
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = cli.main(list(argv))
    finally:
        os.environ.clear(); os.environ.update(old)
    return rc, out.getvalue(), err.getvalue()


snap = ((WS / "skills/APPROVED.md").read_text(), (WS / "skills/IGNORED.md").read_text(), (WS / "skills/skills.lock.json").read_text())
chat = {"CLAUDECODE": "1", "SHIPMIRACLE_ENFORCE_OWNER": "1"}
for argv in (("skills", "approve", "newsk3", "--why", "x"), ("skills", "ignore", "foo", "--reason", "x"), ("skills", "remove", "rogue")):
    rc, o, e = run(*argv, env=chat)
    check("inside a Claude chat `shipm %s` is refused" % " ".join(argv[:2]), rc != 0 and "not inside a Claude Code chat" in e, (rc, e))
check("the refused commands changed nothing", snap == ((WS / "skills/APPROVED.md").read_text(), (WS / "skills/IGNORED.md").read_text(), (WS / "skills/skills.lock.json").read_text()))
rc, o, e = run("skills", "found", "--short")
check("shipm skills found --short: one summary line, exit 1 while FAIL rows exist", rc == 1 and o.strip().startswith("found, not approved:") and len(o.strip().splitlines()) == 1, (rc, o, e))
rc, o, e = run("skills", "found")
check("shipm skills found lists the open findings", "realdir" in o and "oldskill" in o and "plug-off@mkt" in o, o)
rc, o, e = run("skills", "ignore", "foo2")
check("shipm skills ignore without --reason is a usage error", rc != 0 and "foo2" not in (WS / "skills/IGNORED.md").read_text(), (rc, e))
rc, o, e = run("skills", "ignore", "foo3", "--reason", "just because")
check("shipm skills ignore NAME --reason works for the owner", rc == 0 and "foo3 | just because" in (WS / "skills/IGNORED.md").read_text(), (rc, o, e))

# ------------------------------------------------------------------ review fixes (F2 F4 F5 F6 F7 F9 F10)
# F2: the library functions refuse inside a chat by themselves, not only the CLI
snap = ((WS / "skills/APPROVED.md").read_text(), (WS / "skills/IGNORED.md").read_text(), (WS / "skills/skills.lock.json").read_text())
os.environ.update(chat)
for label, fn in (("approve", lambda: S.approve("newsk", "x", None, WS, HOME)), ("approve plugin", lambda: S.approve("plug-z@mkt", "x", None, WS, HOME)),
                  ("ignore", lambda: S.ignore("zz9", "x", WS)), ("remove", lambda: S.remove("rogue", HOME, is_tty=True, ask=lambda p: "y", run=lambda a: ran.append(a) or 0, out=said.append))):
    ran, said = [], []
    try:
        fn(); ok = False
    except SafetyError as e:
        ok = "not inside a Claude Code chat" in str(e)
    check("library %s with CLAUDECODE set is refused" % label, ok and not ran and not said)
for k in chat:
    os.environ.pop(k, None)
check("the refused library calls wrote nothing", snap == ((WS / "skills/APPROVED.md").read_text(), (WS / "skills/IGNORED.md").read_text(), (WS / "skills/skills.lock.json").read_text()))

# F4: any character that makes splitlines() split, or a control/format character, is refused
for bad in ("a b", "a b", "a\x85b", "a\x0bb", "a\x1cb", "a\x1bb", "a​b", "a‮b"):
    try:
        S.approve("newsk2", bad, None, WS, HOME); ok = False
    except UsageError:
        ok = True
    try:
        S.ignore("zz8", bad, WS); ok = ok and False
    except UsageError:
        pass
    check("--why / --reason %r is refused" % bad, ok and "zz8" not in (WS / "skills/IGNORED.md").read_text())

# F5: ASCII-only names (Cyrillic i in 'grill' is not 'grill')
homo = "grіll"
for fn in (lambda: S.approve(homo, "x", None, WS, HOME), lambda: S.ignore(homo, "x", WS), lambda: S.approve(homo + "@mkt", "x", None, WS, HOME)):
    try:
        fn(); ok = False
    except UsageError:
        ok = True
    check("a Cyrillic homoglyph name is refused", ok)
check("the homoglyph is not a skill name for the strict patterns", not S.SKILL_RE.fullmatch(homo) and not S.PLUGIN_RE.fullmatch(homo + "@mkt"))
check("a homoglyph line in IGNORED.md is not read", S.IGNORED_RE.match("- %s | why | 2026-10-28" % homo) is None)

# F6: odd names are shown by repr, never raw
odd = {"kind": "skill", "name": "evil\x1b[31mred‮", "scope": "global", "cls": "unlisted", "level": "FAIL", "hint": ""}
orow = " ".join(t for _l, t in S.found_rows([odd], 1)) + S.found_lines([odd])[0]
check("a name with escape / bidi characters is shown escaped", "\x1b" not in orow and "‮" not in orow and "evil" in orow, repr(orow))

# F7: a deeply nested JSON file does not crash the readers
(HOME / ".agents/.skill-lock.json.bak").write_text("x")
deep = "[" * 200000
lk_keep = (HOME / ".agents/.skill-lock.json").read_text()
(HOME / ".agents/.skill-lock.json").write_text(deep)
try:
    gl = S.global_lock(HOME); ok = gl == {}
except Exception as e:  # noqa: BLE001
    ok = False; gl = repr(e)
check("a deeply nested ~/.agents/.skill-lock.json reads as empty (no RecursionError)", ok, gl)
(HOME / ".agents/.skill-lock.json").write_text(lk_keep)
(HOME / ".claude/settings.json.keep").write_text((HOME / ".claude/settings.json").read_text())
(HOME / ".claude/settings.json").write_text(deep)
try:
    pst = S.plugin_state(HOME); ok = pst[2] is not None
except Exception as e:  # noqa: BLE001
    ok = False; pst = repr(e)
check("a deeply nested settings.json is reported as a problem (no RecursionError)", ok, pst)
(HOME / ".claude/settings.json").write_text((HOME / ".claude/settings.json.keep").read_text())

# F9: the plugins heading with trailing spaces is found (no second heading)
W3 = TMP / "ws3"; (W3 / "skills").mkdir(parents=True)
(W3 / "skills/APPROVED.md").write_text("# A\n## Approved plugins   \n- plugin one@mkt | first\n\n## Retired\nold (x)\n")
S.approve("two@mkt", "second", None, W3, HOME)
t3 = (W3 / "skills/APPROVED.md").read_text()
check("approve plugin finds '## Approved plugins' with trailing spaces", t3.count("## Approved plugins") == 1 and sorted(S.parse_plugins(W3)) == ["one@mkt", "two@mkt"], t3)

# F10: a real folder in ~/.claude/skills gets the manual path, not the npx command
ran, said = [], []
rc = S.remove("realdir", HOME, is_tty=True, ask=lambda p: "y", run=lambda a: ran.append(a) or 0, out=said.append)
check("remove of a real ~/.claude/skills folder prints the manual rm path and runs nothing", rc == 1 and not ran and any("rm -r " in s and ".claude/skills/realdir" in s for s in said)
      and not any("npx" in s for s in said), said)
ran, said = [], []
rc = S.remove("foreign", HOME, is_tty=True, ask=lambda p: "y", run=lambda a: ran.append(a) or 0, out=said.append)
check("remove of a foreign link in ~/.claude/skills: the same", rc == 1 and not ran and any(".claude/skills/foreign" in s for s in said) and not any("npx" in s for s in said), said)

# ------------------------------------------------------------------ review round 2 (E2 E3 E5 E6 E7)
import time as _t
# E2: a homoglyph APPROVED.md line is not read as approved
W4 = TMP / "ws4"; (W4 / "skills").mkdir(parents=True)
(W4 / "skills/APPROVED.md").write_text("## Approved\n- acme/skills@unpinned | grіll | cyrillic | global\n- acme/skіlls@unpinned | grill | cyrillic pkg | global\n- acme/skills@unpinned | grill | ascii | global\n")
check("E2 homoglyph skill / package lines in APPROVED.md are not read", [(a["pkg"], a["skill"]) for a in S.parse_approved(W4)] == [("acme/skills", "grill")], S.parse_approved(W4))
check("E2 PKG_RE is ASCII only", S.PKG_RE.fullmatch("acme/skіlls") is None)
# E5: long whitespace lines are cheap
W5 = TMP / "ws5"; (W5 / "skills").mkdir(parents=True)
(W5 / "skills/APPROVED.md").write_text("## Approved plugins\n- plugin one@mkt | x" + " " * 40000 + "\n- plugin two@mkt |" + " " * 40000 + "\n- plugin three@mkt | " + "a " * 20000 + "\n")
(W5 / "skills/IGNORED.md").write_text("- aa | r" + " " * 40000 + "\n- bb |" + " " * 40000 + "\n- cc | " + "x " * 20000 + "\n")
t0 = _t.time(); pp = S.parse_plugins(W5); pi = S.parse_ignored(W5); dt = _t.time() - t0
check("E5 40k-space plugin / ignored lines parse in < 0.5 s", dt < 0.5, dt)
check("E5 trailing blanks are stripped; empty why and lines over 1000 chars are not read", list(pp) == ["one@mkt"] and list(pi) == ["aa"], (list(pp), list(pi)))
# E6: control characters in an IGNORED.md reason are dropped before display
W6 = TMP / "ws6"; (W6 / "skills").mkdir(parents=True)
(W6 / "skills/IGNORED.md").write_text("- aa | fine\x1b[31m red‮ | 2026-10-28\n")
rs = S.parse_ignored(W6)["aa"]["reason"]
check("E6 the ignored reason has no control or bidi characters", "\x1b" not in rs and "‮" not in rs and rs.startswith("fine"), repr(rs))
# E3: an invalid name gets 'remove it by hand', and its display carries the length
cs_bad = cs / "badіname"
mk(cs_bad)
fb = [f for f in S.found_scan(WS, HOME, []) if f["scope"] == "claude" and f["name"] == "badіname"]
check("E3 an invalid ~/.claude/skills name: hint says remove it by hand with the path, no command", len(fb) == 1 and "remove it by hand" in fb[0]["hint"] and ".claude/skills/" in fb[0]["hint"] and "shipm skills" not in fb[0]["hint"], fb)
check("E3 the escaped display carries the length", "(len 8)" in S._shown("badіname"), S._shown("badіname"))
shutil.rmtree(str(cs_bad))
# E7: a name that is both a real ~/.claude/skills folder and installed globally: manual path first, global command also printed
mk(ag / "dual"); mk(cs / "dual")
ran, said = [], []
rc = S.remove("dual", HOME, is_tty=True, ask=lambda p: "y", run=lambda a: ran.append(a) or 0, out=said.append)
check("E7 real folder + global copy: manual rm path printed first, global command printed too, nothing run", rc == 1 and not ran and "rm -r " in said[1] and "npx" in said[2], said)

# release export: IGNORED.md must not be on the allowlist
if (ROOT / "release/allowlist.txt").is_file():
    allow = (ROOT / "release/allowlist.txt").read_text().splitlines()
    check("skills/IGNORED.md is not in the release allowlist", not any("IGNORED" in l for l in allow))
else:       # exported tree: the release data files are not shipped
    print("SKIP allowlist check (release/allowlist.txt is not in this tree)")

shutil.rmtree(str(TMP), ignore_errors=True)
print("\n%d checks, %d failed" % (n, fails))
sys.exit(1 if fails else 0)
