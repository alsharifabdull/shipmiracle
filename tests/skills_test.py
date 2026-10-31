#!/usr/bin/env python3
"""shipmiracle/skills.py, bin/skills-sync, `shipm skills view`, the skills doctor rows and docs/owner-steps/p3-skills.sh.
Everything runs under SHIPMIRACLE_TEST=1 in temp HOME / state / Developer folders with LOCAL git repos standing in for GitHub (SHIPMIRACLE_SKILLS_REPO_BASE) and a stub npx.
The real ~/.agents, ~/.claude and every real project are never written. No network. Run: python3 tests/skills_test.py (Python 3.9 ok)"""
import hashlib, json, os, pathlib, shutil, subprocess, sys, tempfile, time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = pathlib.Path(tempfile.mkdtemp(prefix="shipmiracle-skills-")).resolve()
os.environ.update(SHIPMIRACLE_TEST="1", SHIPMIRACLE_HOME=str(TMP / "home"), SHIPMIRACLE_STATE=str(TMP / "state"), SHIPMIRACLE_CONFIG=str(TMP / "cfg"),
                  SHIPMIRACLE_DEV=str(TMP / "dev"), SHIPMIRACLE_WS=str(TMP / "ws"), HOME=str(TMP / "home"), SHIPMIRACLE_SKILLS_REPO_BASE=str(TMP / "repos"),
                  GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null")
for k in ("CLAUDECODE", "SHIPMIRACLE_ENFORCE_OWNER"):
    os.environ.pop(k, None)
from shipmiracle import ShipmiracleError, skills as S  # noqa: E402

fails = 0
n = 0
REAL = pathlib.Path(os.path.expanduser("~"))
REAL_LOCK = REAL / ".agents" / ".skill-lock.json"
real_before = (REAL_LOCK.stat().st_mtime, REAL_LOCK.stat().st_size) if REAL_LOCK.exists() else None


def check(name, ok, info=""):
    global fails, n
    n += 1
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(info)[:500]))
    fails += 0 if ok else 1


GENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")


def git(d, *a):
    return subprocess.run(["git", "-C", str(d), *a], env=GENV, capture_output=True, text=True, check=True).stdout.strip()


def mkrepo(pkg, files, base=None):
    """A git repo at <repos>/<pkg> with one commit holding `files`; -> commit sha."""
    d = (base or TMP / "repos") / pkg
    d.mkdir(parents=True, exist_ok=True)
    if not (d / ".git").exists():
        git(d, "init", "-q")
    for rel, txt in files.items():
        (d / rel).parent.mkdir(parents=True, exist_ok=True)
        (d / rel).write_text(txt)
    git(d, "add", "-A")
    git(d, "commit", "-qm", "c%d" % time.time_ns())
    return git(d, "rev-parse", "HEAD")


def skill_files(name, body="body"):
    return {"SKILL.md": "---\nname: %s\ndescription: Use when testing %s.\n---\n%s\n" % (name, name, body), "ref/notes.md": "n\n"}


# ------------------------------------------------------------------ tree_sha256
t1 = TMP / "t1"; (t1 / "a").mkdir(parents=True); (t1 / "a" / "x.md").write_text("x"); (t1 / "y.md").write_text("y")
h1 = S.tree_sha256(t1)
t2 = TMP / "t2"; (t2 / "a").mkdir(parents=True); (t2 / "y.md").write_text("y"); (t2 / "a" / "x.md").write_text("x")
check("tree_sha256: same files, same digest regardless of creation order", h1 == S.tree_sha256(t2) and len(h1) == 64)
(t2 / ".DS_Store").write_text("junk")
check("tree_sha256: .DS_Store ignored", h1 == S.tree_sha256(t2))
(t2 / "y.md").write_text("changed")
check("tree_sha256: a changed file changes the digest", h1 != S.tree_sha256(t2))
os.symlink("a/x.md", str(t1 / "ln")); check("tree_sha256: a symlink is part of the digest", h1 != S.tree_sha256(t1))
check("tree_sha256: missing folder -> None", S.tree_sha256(TMP / "nope") is None)

# ------------------------------------------------------------------ temp workspace with a pinned list
WS = TMP / "ws"
(WS / "skills").mkdir(parents=True)
c_g = mkrepo("acme/skills", {"skills/grill/SKILL.md": skill_files("grill")["SKILL.md"], "skills/grill/ref/notes.md": "n\n"})
c_w = mkrepo("acme/webpack", {"skills/webby/SKILL.md": skill_files("webby")["SKILL.md"], "skills/webby/ref/notes.md": "n\n"})
tree_g = S.tree_sha256(TMP / "repos/acme/skills/skills/grill")
tree_w = S.tree_sha256(TMP / "repos/acme/webpack/skills/webby")
(WS / "skills/APPROVED.md").write_text(
    "# Approved\n- bullet prose that is not a skill line\n"
    "- acme/skills@%s | grill | pressure test | global,planning\n- acme/webpack@%s | webby | web thing | web\n" % (c_g, c_w))
S.write_lock({"grill": {"pkg": "acme/skills", "commit": c_g, "tree_sha256": tree_g, "path": "skills/grill"},
              "webby": {"pkg": "acme/webpack", "commit": c_w, "tree_sha256": tree_w, "path": "skills/webby"}}, WS)
HOME = TMP / "home"; (HOME / ".agents/skills").mkdir(parents=True); (HOME / ".claude/skills").mkdir(parents=True)
app = S.parse_approved(WS)
check("parse_approved: only pkg@commit lines, packs split", [a["skill"] for a in app] == ["grill", "webby"] and app[0]["packs"] == ["global", "planning"] and app[1]["commit"] == c_w)

# install: dry, real, exists, unpinned, hash mismatch, bad commit
r = S.sync_global(WS, HOME, dry=True)
check("sync_global --dry: would install grill, nothing written", r[0][1] == "dry" and not (HOME / ".agents/skills/grill").exists(), r)
r = S.sync_global(WS, HOME, online=True)
check("sync_global: installs the pinned commit's folder + relative link", r[0][1] == "ok" and (HOME / ".agents/skills/grill/SKILL.md").is_file()
      and os.readlink(str(HOME / ".claude/skills/grill")) == "../../.agents/skills/grill" and S.tree_sha256(HOME / ".agents/skills/grill") == tree_g, r)
check("sync_global: webby is a web-pack skill and is NOT installed globally", not (HOME / ".agents/skills/webby").exists())
r = S.sync_global(WS, HOME, online=True)
check("sync_global: second run -> exists, same files, nothing changed", r[0][1] == "exists" and "same files" in r[0][2], r)
(HOME / ".agents/skills/grill/SKILL.md").write_text("tampered")
r = S.sync_global(WS, HOME, online=True)
check("an existing but different folder is kept, never overwritten", r[0][1] == "exists" and "kept" in r[0][2] and (HOME / ".agents/skills/grill/SKILL.md").read_text() == "tampered", r)
shutil.rmtree(str(HOME / ".agents/skills/grill")); os.unlink(str(HOME / ".claude/skills/grill"))
lk = S.load_lock(WS); lk["grill"]["tree_sha256"] = "0" * 64; S.write_lock(lk, WS)
r = S.sync_global(WS, HOME, online=True)
check("install fails closed when the files at the commit differ from the lock hash; nothing left behind", r[0][1] == "FAIL" and "differ" in r[0][2]
      and not (HOME / ".agents/skills/grill").exists() and not [x for x in os.listdir(str(HOME / ".agents/skills")) if x.startswith(".")], r)
lk["grill"]["tree_sha256"] = tree_g; lk["grill"]["commit"] = "f" * 40; S.write_lock(lk, WS)
r = S.sync_global(WS, HOME, online=True)
check("install of a commit that does not exist -> FAIL, nothing installed", r[0][1] == "FAIL" and not (HOME / ".agents/skills/grill").exists(), r)
lk["grill"]["commit"] = "unpinned"; S.write_lock(lk, WS)
r = S.sync_global(WS, HOME, online=True)
check("an unpinned skill is never installed (no network guess)", r[0][1] == "unpinned" and not (HOME / ".agents/skills/grill").exists(), r)
lk["grill"]["commit"] = c_g; S.write_lock(lk, WS)
check("a bad skill or package name is refused", S.install_skill("../x", lk["grill"], HOME / "z", None)[0] == "FAIL" and not (HOME / "z").exists()
      and not any(S.PKG_RE.fullmatch(p) for p in ("../x", "a/b/c", "a b/c")))

# project pack
PD = TMP / "dev" / "proj"; PD.mkdir(parents=True); git(PD, "init", "-q")
r = S.sync_project(str(PD), "web", WS, HOME, dry=True)
check("sync_project --dry writes nothing", r[0][1] == "dry" and not (PD / ".agents").exists(), r)
r = S.sync_project(str(PD), "web", WS, HOME, online=True)
pins = json.loads((PD / ".agents/skills.pins.json").read_text())
check("sync_project installs the pack pinned into <project>/.agents/skills with a link and a pins file", r[0][1] == "ok" and (PD / ".agents/skills/webby/SKILL.md").is_file()
      and (PD / ".claude/skills/webby").is_symlink() and pins["webby"]["commit"] == c_w and pins["webby"]["tree_sha256"] == tree_w, r)
try:
    S.sync_project(str(PD), "nopack", WS, HOME, online=True); ok = False
except ShipmiracleError:
    ok = True
check("an unknown pack raises", ok)

# fail-closed install (review item 1)
off = S.sync_global(WS, HOME)
check("an install that needs a clone is refused without --online (status offline, nothing written)", off[0][1] == "offline" and "--online" in off[0][2] and not (HOME / ".agents/skills/grill").exists(), off)
lines = []; rc = S.sync_main(["--dry"], out=lines.append)
check("--dry still works without --online", rc == 0 and lines[-1].startswith("DRY RUN"), lines)
lk = S.load_lock(WS); keep = dict(lk["grill"]); del lk["grill"]["tree_sha256"]; S.write_lock(lk, WS)
r = S.sync_global(WS, HOME, online=True)
check("a lock entry without tree_sha256 is refused (fail closed), even in --dry", r[0][1] == "FAIL" and "no tree_sha256" in r[0][2] and not (HOME / ".agents/skills/grill").exists()
      and S.sync_global(WS, HOME, dry=True)[0][1] == "FAIL", r)
lk["grill"] = dict(keep); lk["grill"]["path"] = "../../etc"; S.write_lock(lk, WS)
r = S.sync_global(WS, HOME, online=True)
check("a lock `path` hint that escapes the clone is ignored (falls back to the name search, still verified by hash)", r[0][1] in ("ok", "FAIL") and not (HOME / ".agents/skills/etc").exists(), r)
shutil.rmtree(str(HOME / ".agents/skills/grill"), ignore_errors=True); (HOME / ".claude/skills/grill").is_symlink() and os.unlink(str(HOME / ".claude/skills/grill"))
chk = TMP / "chk"; (chk / "a").mkdir(parents=True); (chk / "a/SKILL.md").write_text("x"); (TMP / "outside.txt").write_text("secret")
check("path hint helper: '..' escape and absolute path are not accepted", S._find_folder(chk, "zzz", "../") is None and S._find_folder(chk, "zzz", str(TMP)) is None and S._find_folder(chk, "a", "a") == (chk / "a").resolve())
os.symlink(str(TMP / "outside.txt"), str(chk / "a/ln")); os.symlink("SKILL.md", str(chk / "a/inner"))
check("escaping_links: a link outside the folder is found, an inside link is fine", S.escaping_links(chk / "a") == ["ln"], S.escaping_links(chk / "a"))
c_ln = mkrepo("acme/linky", {"skills/linky/SKILL.md": "x\n"})
os.symlink("/etc/hosts", str(TMP / "repos/acme/linky/skills/linky/evil")); git(TMP / "repos/acme/linky", "add", "-A"); git(TMP / "repos/acme/linky", "commit", "-qm", "link")
c_ln = git(TMP / "repos/acme/linky", "rev-parse", "HEAD")
ent = {"pkg": "acme/linky", "commit": c_ln, "tree_sha256": "a" * 64, "path": "skills/linky"}
r = S.install_skill("linky", ent, HOME / ".agents/skills", None, online=True)
check("a skill folder with a symlink pointing outside it is refused, nothing installed", r[0] == "FAIL" and "outside" in r[1] and not (HOME / ".agents/skills/linky").exists(), r)
# git environment from the parent must not change what the installer runs
os.environ.update(GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="core.hooksPath", GIT_CONFIG_VALUE_0="/nonexistent", GIT_CONFIG_PARAMETERS="'core.bare=true'", GIT_DIR="/nonexistent/evil")
check("git env of the parent (GIT_CONFIG_*, GIT_DIR) is dropped by the installer", not any(k.startswith("GIT_CONFIG") or k == "GIT_DIR" for k in S._env_git()))
r = S.sync_global(WS, HOME, online=True)
for k in ("GIT_CONFIG_COUNT", "GIT_CONFIG_KEY_0", "GIT_CONFIG_VALUE_0", "GIT_CONFIG_PARAMETERS", "GIT_DIR"):
    os.environ.pop(k, None)
check("install still works with a hostile git environment in the parent", r[0][1] == "ok", r)
check("SKILLS_NPM_VERSION is one pinned constant", S.SKILLS_NPM_VERSION == "1.7.4")
check("global install did not touch the project and vice versa", not (HOME / ".agents/skills/webby").exists())

# ------------------------------------------------------------------ pin: resolve unpinned by folder hash
gh = TMP / "home/.agents/.skill-lock.json"
folder = "skills/grill"
orig = git(TMP / "repos/acme/skills", "rev-parse", "%s:%s" % (c_g, folder))
c2 = mkrepo("acme/skills", {"README.md": "later commit that does not touch the skill\n"})
c3 = mkrepo("acme/skills", {"skills/grill/SKILL.md": skill_files("grill", "NEWER")["SKILL.md"]})
gh.write_text(json.dumps({"version": 3, "skills": {"grill": {"source": "acme/skills", "skillPath": folder + "/SKILL.md", "skillFolderHash": orig}}}))
lk = S.load_lock(WS); lk["grill"]["commit"] = "unpinned"; lk["grill"]["tree_sha256"] = tree_g; S.write_lock(lk, WS)
txt = (WS / "skills/APPROVED.md").read_text().replace("acme/skills@" + c_g, "acme/skills@unpinned"); (WS / "skills/APPROVED.md").write_text(txt)
res = S.pin(WS, HOME)
check("pin: finds the commit whose folder equals the installed one (not the newer HEAD) and rewrites lock and APPROVED", res and res[0][1] == "pinned"
      and S.load_lock(WS)["grill"]["commit"] == c_g and ("acme/skills@%s | grill" % c_g) in (WS / "skills/APPROVED.md").read_text(), res)
gh.write_text(json.dumps({"version": 3, "skills": {"grill": {"source": "acme/skills", "skillPath": folder + "/SKILL.md", "skillFolderHash": "0" * 40}}}))
lk = S.load_lock(WS); lk["grill"]["commit"] = "unpinned"; S.write_lock(lk, WS)
res = S.pin(WS, HOME)
check("pin: no commit has the recorded hash -> stays unpinned, lock unchanged (no invented commit)", res[0][1] == "unpinned" and S.load_lock(WS)["grill"]["commit"] == "unpinned", res)
lk["grill"]["commit"] = c_g; S.write_lock(lk, WS)
(WS / "skills/APPROVED.md").write_text((WS / "skills/APPROVED.md").read_text().replace("acme/skills@unpinned", "acme/skills@" + c_g))
gh.unlink()

# ------------------------------------------------------------------ pin records the PINNED CHECKOUT hash (DECISIONS 2026-10-28 'Pin records the pinned checkout hash')
W2 = TMP / "ws2"; H2 = TMP / "home2"
(W2 / "skills").mkdir(parents=True); (H2 / ".agents/skills").mkdir(parents=True); (H2 / ".claude/skills").mkdir(parents=True)
full = dict(skill_files("vsk"), **{"extra.md": "only in the checkout\n"})
c_v = mkrepo("acme/vsk", {"skills/vsk/" + k: v for k, v in full.items()})
c_o = mkrepo("acme/other", {"skills/oth/" + k: v for k, v in skill_files("oth").items()})
tree_v = S.tree_sha256(TMP / "repos/acme/vsk/skills/vsk")
tree_o = S.tree_sha256(TMP / "repos/acme/other/skills/oth")
inst = TMP / "cli-copy"; shutil.copytree(str(TMP / "repos/acme/vsk/skills/vsk"), str(inst)); (inst / "extra.md").unlink()   # the CLI omitted a file
tree_cli = S.tree_sha256(inst)
check("pin fixture: the CLI copy differs from the checkout", tree_cli != tree_v)
gh2 = H2 / ".agents/.skill-lock.json"
gh2.write_text(json.dumps({"version": 3, "skills": {
    "vsk": {"source": "acme/vsk", "skillPath": "skills/vsk/SKILL.md", "skillFolderHash": git(TMP / "repos/acme/vsk", "rev-parse", "HEAD:skills/vsk")},
    "oth": {"source": "acme/other", "skillPath": "skills/oth/SKILL.md", "skillFolderHash": git(TMP / "repos/acme/other", "rev-parse", "HEAD:skills/oth")}}}))
(W2 / "skills/APPROVED.md").write_text("- acme/vsk@unpinned | vsk | t | global\n- acme/other@unpinned | oth | t | global\n")
S.write_lock({"vsk": {"pkg": "acme/vsk", "commit": "unpinned", "tree_sha256": tree_cli, "path": "skills/vsk"},
              "oth": {"pkg": "acme/other", "commit": "unpinned", "tree_sha256": "b" * 64, "path": "skills/oth"}}, W2)
r = S.install_skill("vsk", dict(S.load_lock(W2)["vsk"], commit=c_v), H2 / ".agents/skills", None, online=True)
check("before the fix path: lock hash of the CLI copy + pinned checkout -> install refuses (the reported failure)", r[0] == "FAIL" and "differ" in r[1], r)
res = S.pin(W2, H2, only=["vsk"])
lv = S.load_lock(W2)["vsk"]
check("pin: records commit AND the tree_sha256 of the pinned checkout (not of the CLI copy); other entries untouched",
      res[0][1] == "pinned" and lv["commit"] == c_v and lv["tree_sha256"] == tree_v and S.load_lock(W2)["oth"]["commit"] == "unpinned" and S.load_lock(W2)["oth"]["tree_sha256"] == "b" * 64, (res, lv))
r = S.sync_global(W2, H2, online=True)
check("after pin: install of the pinned skill succeeds and the installed files hash to the lock", [x for x in r if x[0] == "vsk"][0][1] == "ok" and S.tree_sha256(H2 / ".agents/skills/vsk") == tree_v, r)
# a tampered checkout (content differs from the lock) still fails: verification direction unchanged
shutil.rmtree(str(H2 / ".agents/skills/vsk")); os.unlink(str(H2 / ".claude/skills/vsk"))
(TMP / "repos/acme/vsk/skills/vsk/SKILL.md").write_text("tampered upstream\n"); git(TMP / "repos/acme/vsk", "add", "-A"); git(TMP / "repos/acme/vsk", "commit", "-qm", "evil")
evil = git(TMP / "repos/acme/vsk", "rev-parse", "HEAD")
r = S.install_skill("vsk", dict(S.load_lock(W2)["vsk"], commit=evil), H2 / ".agents/skills", None, online=True)
check("a tampered checkout (files differ from the lock) is still refused, nothing installed", r[0] == "FAIL" and "differ" in r[1] and not (H2 / ".agents/skills/vsk").exists(), r)
tree_evil = S.tree_sha256(TMP / "repos/acme/vsk/skills/vsk")
check("tamper, same pin: the lock pinned to the ORIGINAL commit with the ORIGINAL hash installs; a lock holding the changed folder's hash is refused for that same commit and path",
      S.install_skill("vsk", dict(S.load_lock(W2)["vsk"], commit=c_v, path="skills/vsk"), H2 / ".agents/skills", None, dry=True)[0] == "dry"
      and S.install_skill("vsk", dict(S.load_lock(W2)["vsk"], commit=c_v, path="skills/vsk", tree_sha256=tree_evil), H2 / ".agents/skills", None, online=True)[0] == "FAIL"
      and not (H2 / ".agents/skills/vsk").exists())

# traversal in a lock key: refused, nothing outside the pin temp folder is touched; failing entry leaves no co- folder behind
sname = "shipmiracle-sentinel-%d" % os.getpid()
PT = TMP / "pintmp"; PT.mkdir()                      # private temp folder: pin() creates its work folders here, so the checks cannot see other processes' temp files
_old_tempdir = tempfile.tempdir
tempfile.tempdir = str(PT)
try:
    sentinel = PT / sname; sentinel.mkdir(); (sentinel / "keep.txt").write_text("keep")     # sibling of pin's own temp folder: where the old co-<key> path would reach
    c_x = mkrepo("acme/xrepo", {"skills/x/readme.md": "a folder without SKILL.md\n"})
    g_ = json.loads(gh2.read_text()); g_["skills"]["x"] = {"source": "acme/xrepo", "skillPath": "skills/x/SKILL.md", "skillFolderHash": git(TMP / "repos/acme/xrepo", "rev-parse", "HEAD:skills/x")}; gh2.write_text(json.dumps(g_))
    _trav = {"pkg": "acme/vsk", "commit": "unpinned", "tree_sha256": "d" * 64, "path": "skills/vsk"}
    lkx = S.load_lock(W2); lkx["x"] = dict(_trav, pkg="acme/xrepo", path="skills/x"); lkx["x/../../" + sname] = dict(_trav); lkx["../" + sname] = dict(_trav)
    S.write_lock(lkx, W2)          # "x" sorts first and has a real upstream hash but no SKILL.md: it fails INSIDE _checkout_hash, after its clone and checkout
    res = S.pin(W2, H2)
    check("pin: a lock key with path traversal is refused (FAIL bad skill name); the sentinel folder survives",
          sum(1 for x in res if x[1] == "FAIL" and "bad skill name" in x[2]) == 2 and (sentinel / "keep.txt").read_text() == "keep", res)
    check("pin: the entry that fails inside _checkout_hash is a FAIL and leaves no pin/co- folder behind", any(x[0] == "x" and x[1] == "FAIL" and "checkout" in x[2] for x in res) and os.listdir(str(PT)) == [sname], (res, os.listdir(str(PT))))
    shutil.rmtree(str(sentinel))
    lkx = S.load_lock(W2); del lkx["x"]; del lkx["x/../../" + sname]; del lkx["../" + sname]; S.write_lock(lkx, W2)
    lkx["oth"]["tree_sha256"] = "b" * 64; S.write_lock(lkx, W2)
    res = S.pin(W2, H2, only=["oth"])
    check("pin: a normal pin leaves no shipmiracle-pin-/co- folder behind", os.listdir(str(PT)) == [], (res, os.listdir(str(PT))))
finally:
    tempfile.tempdir = _old_tempdir
    shutil.rmtree(str(PT), ignore_errors=True)
esc_name = "ok.md\x1b[31mred"
check("_flist: a file name with an escape sequence is shown escaped, with the total", "\x1b" not in S._flist({esc_name, "a.md"}) and "(2 total)" in S._flist({esc_name, "a.md"}) and "a.md" in S._flist({esc_name, "a.md"}))

# repin: an already pinned entry whose lock hash is stale; owner-only; explicit names only
lk = S.load_lock(W2); lk["vsk"]["tree_sha256"] = tree_cli; lk["oth"].update(commit=c_o, tree_sha256="c" * 64)
lk["vsk"]["commit"] = c_v
S.write_lock(lk, W2)
(W2 / "skills/APPROVED.md").write_text("- acme/vsk@%s | vsk | t | global\n- acme/other@%s | oth | t | global\n" % (c_v, c_o))
gh2.write_text(json.dumps({"version": 3, "skills": {"vsk": {"source": "acme/vsk", "skillPath": "skills/vsk/SKILL.md", "skillFolderHash": git(TMP / "repos/acme/vsk", "rev-parse", "%s:skills/vsk" % c_v)},
                                                      "oth": {"source": "acme/other", "skillPath": "skills/oth/SKILL.md", "skillFolderHash": git(TMP / "repos/acme/other", "rev-parse", "HEAD:skills/oth")}}}))
before_oth = dict(S.load_lock(W2)["oth"]); app_before = (W2 / "skills/APPROVED.md").read_text()
_save_env = {k: os.environ[k] for k in ("SHIPMIRACLE_WS", "SHIPMIRACLE_HOME", "HOME")}
os.environ.update(SHIPMIRACLE_WS=str(W2), SHIPMIRACLE_HOME=str(H2), HOME=str(H2))     # the command-line entry reads the default workspace and home
os.environ["CLAUDECODE"] = "1"; os.environ["SHIPMIRACLE_ENFORCE_OWNER"] = "1"
try:
    S.pin(W2, H2, only=["vsk"], repin=True); ok = False
except ShipmiracleError:
    ok = True
lines = []
try:
    rc = S.sync_main(["--pin", "--online", "--repin", "vsk"], out=lines.append)
except ShipmiracleError:
    rc = 1
os.environ.pop("CLAUDECODE"); os.environ.pop("SHIPMIRACLE_ENFORCE_OWNER")
check("repin refuses inside a chat (CLAUDECODE): library and command line, lock unchanged", ok and rc != 0 and S.load_lock(W2)["vsk"]["tree_sha256"] == tree_cli, (lines,))
for bad in ([], ["all"], ["vsk", "all"], ["nosuch"]):
    try:
        S.pin(W2, H2, only=bad, repin=True); ok = False
    except ShipmiracleError:
        ok = True
    check("repin needs explicit existing names (%r refused)" % bad, ok)
lines = []; rc = S.sync_main(["--pin", "--repin", "vsk"], out=lines.append)
check("--repin without --online is refused", rc == 2, lines)
lines = []; rc = S.sync_main(["--online", "--repin", "vsk"], out=lines.append)
check("--repin without --pin is refused", rc == 2, lines)
oks = []
for tty_ in (False, None):          # None = look at the real stdin: refused when it is not a terminal (the runner), otherwise the answer 'n' keeps the lock
    try:
        S.pin(W2, H2, only=["vsk"], repin=True, out=lambda *_a: None, is_tty=tty_, ask=lambda _p: "n"); oks.append("asked")
    except ShipmiracleError:
        oks.append("refused")
check("repin without a terminal (is_tty False; None follows stdin) is refused before anything is written",
      oks[0] == "refused" and oks[1] == ("asked" if sys.stdin.isatty() else "refused") and S.load_lock(W2)["vsk"]["tree_sha256"] == tree_cli, oks)
rc = S.sync_main(["--pi", "--online"], out=lambda *_a: None)
check("abbreviated options are refused (--pi exits 2)", rc == 2, rc)
# installed copy (CLI) lacks extra.md: it is shown as 'added' by the checkout
shutil.copytree(str(inst), str(H2 / ".agents/skills/vsk"))
lines = []; res = S.pin(W2, H2, only=["vsk"], repin=True, out=lines.append, is_tty=True, ask=lambda _p: "n")
check("repin answered n: lock unchanged, row kept/declined, before->after and added/removed were printed first",
      res[0][1] == "kept" and S.load_lock(W2)["vsk"]["tree_sha256"] == tree_cli and any("extra.md" in l and "added" in l and "(1 total)" in l for l in lines) and any(tree_cli[:12] in l and tree_v[:12] in l for l in lines), (res, lines))
def _eof(_p):
    raise EOFError
lines = []; res = S.pin(W2, H2, only=["vsk"], repin=True, out=lines.append, is_tty=True, ask=_eof)
check("repin: end of input at the prompt counts as n (message, lock unchanged)", res[0][1] == "kept" and any("treated as n" in l for l in lines) and S.load_lock(W2)["vsk"]["tree_sha256"] == tree_cli, (res, lines))
lines = []; rc = S.sync_main(["--pin", "--online", "--repin", "vsk"], out=lines.append, is_tty=True, ask=lambda _p: "y")
lv = S.load_lock(W2)
check("repin vsk answered y: lock tree_sha256 now the checkout's, commit kept; prints before/after first; oth untouched; APPROVED unchanged; says remove + reinstall",
      rc == 0 and lv["vsk"]["tree_sha256"] == tree_v and lv["vsk"]["commit"] == c_v and lv["oth"] == before_oth and (W2 / "skills/APPROVED.md").read_text() == app_before
      and any(tree_cli[:12] in l and tree_v[:12] in l and "repinned" in l for l in lines) and any("skills@" in l and "remove" in l and "bin/skills-sync --online" in l for l in lines)
      and min(i for i, l in enumerate(lines) if tree_v[:12] in l) < min(i for i, l in enumerate(lines) if "repinned" in l), (lines, lv))
lines = []; res = S.pin(W2, H2, only=["vsk"], repin=True, out=lines.append, is_tty=True, ask=lambda _p: "y")
check("repin when the lock already equals the pinned checkout: nothing written, tells to reinstall from the pin", res[0][1] == "kept" and "reinstall" in res[0][2], res)
# commit-moved path: the pinned commit no longer has the CLI's folder hash -> FAIL, commit and tree untouched
g_ = json.loads(gh2.read_text()); g_["skills"]["vsk"]["skillFolderHash"] = "0" * 40; gh2.write_text(json.dumps(g_))
lk = S.load_lock(W2); lk["vsk"]["tree_sha256"] = tree_cli; S.write_lock(lk, W2)
lines = []; rc = S.sync_main(["--pin", "--online", "--repin", "vsk"], out=lines.append, is_tty=True, ask=lambda _p: "y")
check("repin never moves the commit: CLI hash no longer at the pinned commit -> FAIL 'update', exit 1, lock unchanged",
      rc == 1 and any("FAIL" in l and "update" in l for l in lines) and S.load_lock(W2)["vsk"]["commit"] == c_v and S.load_lock(W2)["vsk"]["tree_sha256"] == tree_cli, lines)
lk = S.load_lock(W2); lk["vsk"]["commit"] = "e" * 40; S.write_lock(lk, W2)
res = S.pin(W2, H2, only=["vsk"], repin=True, out=lambda *_a: None, is_tty=True, ask=lambda _p: "y")
check("repin with an unreachable pinned commit -> FAIL, commit untouched", res[0][1] == "FAIL" and S.load_lock(W2)["vsk"]["commit"] == "e" * 40, res)
lk = S.load_lock(W2); lk["vsk"]["commit"] = c_v; S.write_lock(lk, W2)
g_["skills"]["vsk"]["skillFolderHash"] = git(TMP / "repos/acme/vsk", "rev-parse", "%s:skills/vsk" % c_v); gh2.write_text(json.dumps(g_))
# _checkout_hash failing leaves no folder behind; folder mismatch is refused
_tmpd = pathlib.Path(tempfile.mkdtemp(prefix="co-test-"))
try:
    S._checkout_hash(TMP / "repos/acme/vsk", "f" * 40, "vsk", "skills/vsk", _tmpd); ok = False
except ShipmiracleError:
    ok = True
check("_checkout_hash: a failing checkout leaves nothing under its temp folder", ok and os.listdir(str(_tmpd)) == [])
try:
    S._checkout_hash(TMP / "repos/acme/vsk", c_v, "vsk", "skills/elsewhere", _tmpd); ok = False
except ShipmiracleError:
    ok = True
check("_checkout_hash: the folder install would copy must be the folder whose git hash matched", ok and os.listdir(str(_tmpd)) == [])
shutil.rmtree(str(_tmpd))
os.environ.update(_save_env)
for k in ("vsk",):
    lk = S.load_lock(W2); lk[k]["tree_sha256"] = tree_v; S.write_lock(lk, W2)
shutil.rmtree(str(H2 / ".agents/skills/vsk"))
r = S.sync_global(W2, H2, online=True)
check("after repin: install succeeds", [x for x in r if x[0] == "vsk"][0][1] == "ok", r)
# doctor row for a pinned skill whose installed folder differs from the lock (and none for an unpinned one)
(H2 / ".agents/skills/vsk/extra.md").unlink()
rs = S.doctor_rows(W2, H2, now=1_800_000_000, project_list=[])
check("doctor row: pinned skill whose installed files differ from the lock names the fix command", any(l == "warn" and "vsk" in t and "--pin --online --repin vsk" in t for l, t in rs), rs)
lk = S.load_lock(W2); lk["vsk"]["commit"] = "unpinned"; S.write_lock(lk, W2)
rs = S.doctor_rows(W2, H2, now=1_800_000_000, project_list=[])
check("doctor row: no repin hint for an unpinned skill", not any("--repin" in t for l, t in rs), rs)
lk = S.load_lock(W2); lk["vsk"]["commit"] = c_v; S.write_lock(lk, W2)
rs = S.doctor_rows(W2, H2, now=1_800_000_000, project_list=[])
check("doctor row (pinned): names repin, the removal command and bin/skills-sync --online", any("--repin vsk" in t and "remove NAME -g -y" in t and "bin/skills-sync --online" in t for l, t in rs), rs)
odd = "xа\x1b[31my"
lk = S.load_lock(W2); lk[odd] = {"pkg": "acme/vsk", "commit": c_v, "tree_sha256": "a" * 64}; S.write_lock(lk, W2)
(H2 / ".agents/skills" / odd).mkdir(exist_ok=True); (H2 / ".agents/skills" / odd / "SKILL.md").write_text("z")
g_ = json.loads(gh2.read_text()); g_["skills"][odd] = {"source": "acme/vsk"}; gh2.write_text(json.dumps(g_))
rs = S.doctor_rows(W2, H2, now=1_800_000_000, project_list=[])
drow = [t for l, t in rs if "differ from skills.lock.json" in t]
check("doctor row: an odd lock key is shown escaped and is not in the repin command", drow and not any("\x1b" in t or odd in t for t in drow) and any("len " in t for t in drow), drow)
lk = S.load_lock(W2); del lk[odd]; S.write_lock(lk, W2)

# ------------------------------------------------------------------ pin --from-commit: path + tree_sha256 for an approved, commit-pinned skill that was never installed
from shipmiracle import terminal as _term
W3 = TMP / "ws3"; H3 = TMP / "home3"
(W3 / "skills").mkdir(parents=True); (H3 / ".agents/skills").mkdir(parents=True); (H3 / ".claude/skills").mkdir(parents=True)
c_e = mkrepo("acme/emil", {"skills/emil-a/" + k: v for k, v in skill_files("emil-a").items()})
c_e = mkrepo("acme/emil", dict({"skills/emil-b/" + k: v for k, v in skill_files("emil-b").items()},
                               **{"skills/proto/SKILL.md": "---\nname: proto\ndescription: Use when x.\n---\n", "docs/proto/SKILL.md": "---\nname: proto\ndescription: Use when y.\n---\n"}))
tree_ea = S.tree_sha256(TMP / "repos/acme/emil/skills/emil-a"); tree_eb = S.tree_sha256(TMP / "repos/acme/emil/skills/emil-b")
c_l = mkrepo("acme/linky", {"skills/linky/" + k: v for k, v in skill_files("linky").items()})
os.symlink("/etc/hosts", str(TMP / "repos/acme/linky/skills/linky/leak.md")); git(TMP / "repos/acme/linky", "add", "-A"); git(TMP / "repos/acme/linky", "commit", "-qm", "leak")
c_l = git(TMP / "repos/acme/linky", "rev-parse", "HEAD")
(W3 / "skills/APPROVED.md").write_text("".join("- %s@%s | %s | t | global\n" % x for x in [
    ("acme/emil", c_e, "emil-a"), ("acme/emil", c_e, "emil-b"), ("acme/emil", c_e, "proto"), ("acme/linky", c_l, "linky"),
    ("acme/emil", "unpinned", "un"), ("acme/emil", c_e, "haslock"), ("acme/emil", c_e, "nolock")]))
S.write_lock({"emil-a": {"pkg": "acme/emil", "commit": c_e}, "emil-b": {"pkg": "acme/emil", "commit": c_e}, "proto": {"pkg": "acme/emil", "commit": c_e},
              "linky": {"pkg": "acme/linky", "commit": c_l}, "un": {"pkg": "acme/emil", "commit": "unpinned"},
              "haslock": {"pkg": "acme/emil", "commit": c_e, "tree_sha256": "a" * 64, "path": "skills/emil-a"}, "ghost": {"pkg": "acme/emil", "commit": c_e}}, W3)
lock0 = (W3 / "skills/skills.lock.json").read_bytes(); app0 = (W3 / "skills/APPROVED.md").read_bytes()
r = S.install_skill("emil-a", S.load_lock(W3)["emil-a"], H3 / ".agents/skills", None, online=True)
check("from-commit fixture: a lock entry with only pkg+commit is refused by install (no hash to verify)", r[0] == "FAIL" and "tree_sha256" in r[1], r)


def _unchanged():
    return (W3 / "skills/skills.lock.json").read_bytes() == lock0 and (W3 / "skills/APPROVED.md").read_bytes() == app0


_save3 = {k: os.environ[k] for k in ("SHIPMIRACLE_WS", "SHIPMIRACLE_HOME", "HOME")}
os.environ.update(SHIPMIRACLE_WS=str(W3), SHIPMIRACLE_HOME=str(H3), HOME=str(H3))
os.environ["CLAUDECODE"] = "1"; os.environ["SHIPMIRACLE_ENFORCE_OWNER"] = "1"
try:
    S.pin_from_commit(["emil-a"], W3, H3, is_tty=True, ask=lambda _p: "y"); ok = False
except ShipmiracleError:
    ok = True
lines = []
try:
    rc = S.sync_main(["--pin", "--online", "--from-commit", "emil-a"], out=lines.append, is_tty=True, ask=lambda _p: "y")
except ShipmiracleError:
    rc = 1
os.environ.pop("CLAUDECODE"); os.environ.pop("SHIPMIRACLE_ENFORCE_OWNER")
check("from-commit refuses inside a chat (CLAUDECODE): library and command line, lock unchanged", ok and rc != 0 and _unchanged(), (rc, lines))
for bad in ([], ["all"], ["emil-a", "all"], ["*"], [""]):
    try:
        S.pin_from_commit(bad, W3, H3, is_tty=True, ask=lambda _p: "y"); ok = False
    except ShipmiracleError:
        ok = True
    check("from-commit needs explicit names (%r refused)" % (bad,), ok and _unchanged())
for tty_ in (False,):
    try:
        S.pin_from_commit(["emil-a"], W3, H3, out=lambda *_a: None, is_tty=tty_, ask=lambda _p: "y"); ok = False
    except ShipmiracleError:
        ok = True
    check("from-commit without a terminal (is_tty False) is refused before anything is cloned or written", ok and _unchanged())
_old_tty = _term.TTY_PATH; _term.TTY_PATH = str(TMP / "no-such-tty")
try:
    S.pin_from_commit(["emil-a"], W3, H3, out=lambda *_a: None, ask=lambda _p: "y"); ok = False
except ShipmiracleError:
    ok = True
finally:
    _term.TTY_PATH = _old_tty
check("from-commit with is_tty None asks the terminal module: no openable /dev/tty -> refused", ok and _unchanged())
for nm, why in (("ghost", "not in APPROVED.md"), ("nolock", "no lock entry"), ("un", "not pinned"), ("haslock", "already has a tree_sha256"), ("nosuch", "unknown"), ("../x", "bad name")):
    try:
        S.pin_from_commit([nm], W3, H3, out=lambda *_a: None, is_tty=True, ask=lambda _p: "y"); ok = False; msg = ""
    except ShipmiracleError as e_:
        ok = True; msg = str(e_)
    check("from-commit refuses %r (%s), lock unchanged" % (nm, why), ok and _unchanged(), msg)
lk = S.load_lock(W3); lk["emil-b"]["commit"] = "b" * 40; S.write_lock(lk, W3)
try:
    S.pin_from_commit(["emil-b"], W3, H3, out=lambda *_a: None, is_tty=True, ask=lambda _p: "y"); ok = False
except ShipmiracleError:
    ok = True
check("from-commit refuses when APPROVED.md and the lock name different commits", ok)
lk["emil-b"]["commit"] = c_e; S.write_lock(lk, W3); lock0 = (W3 / "skills/skills.lock.json").read_bytes()

PT3 = TMP / "pintmp3"; PT3.mkdir(); _old_tempdir = tempfile.tempdir; tempfile.tempdir = str(PT3)
try:
    seen = []; lines = []
    def _ask_rec(p):
        seen.append((p, len(lines))); return "n"
    res = S.pin_from_commit(["emil-a"], W3, H3, out=lines.append, is_tty=True, ask=_ask_rec)
    check("from-commit answered n: lock unchanged, row kept, before/after and file list printed BEFORE the question, no temp folder left",
          res[0][1] == "kept" and _unchanged() and len(seen) == 1 and seen[0][1] >= 3 and "emil-a" in seen[0][0] and os.listdir(str(PT3)) == []
          and any("skills/emil-a" in l and "path" in l for l in lines[:seen[0][1]]) and any(tree_ea[:12] in l and "tree_sha256" in l for l in lines[:seen[0][1]])
          and any("ref/notes.md" in l and "SKILL.md" in l and "(2 total)" in l for l in lines[:seen[0][1]]), (res, lines, seen))
    for nm, ans in (("blank/cancel", ""), ("garbage", "maybe"), ("EOF", None)):
        def _a(_p, ans=ans):
            if ans is None:
                raise EOFError
            return ans
        res = S.pin_from_commit(["emil-a"], W3, H3, out=lambda *_a: None, is_tty=True, ask=_a)
        check("from-commit answer %s counts as n, lock unchanged" % nm, res[0][1] == "kept" and _unchanged(), res)
    def _oserr(_p):
        raise OSError("no tty")
    res = S.pin_from_commit(["emil-a"], W3, H3, out=lambda *_a: None, is_tty=True, ask=_oserr)
    check("from-commit: terminal vanishes at the prompt -> FAIL row, lock unchanged", res[0][1] == "FAIL" and _unchanged(), res)
    res = S.pin_from_commit(["proto"], W3, H3, out=lambda *_a: None, is_tty=True, ask=lambda _p: "y")
    check("from-commit: two folders named proto in the repo -> ambiguous, refused, nothing written", res[0][1] == "FAIL" and "ambiguous" in res[0][2] and _unchanged() and os.listdir(str(PT3)) == [], res)
    res = S.pin_from_commit(["linky"], W3, H3, out=lambda *_a: None, is_tty=True, ask=lambda _p: "y")
    check("from-commit: a symlink pointing outside the skill folder -> FAIL, nothing written", res[0][1] == "FAIL" and "symlink" in res[0][2] and _unchanged() and os.listdir(str(PT3)) == [], res)
    lk = S.load_lock(W3); lk["emil-b"]["commit"] = "f" * 40; S.write_lock(lk, W3)
    (W3 / "skills/APPROVED.md").write_text((W3 / "skills/APPROVED.md").read_text().replace("acme/emil@%s | emil-b" % c_e, "acme/emil@%s | emil-b" % ("f" * 40)))
    lock_f = (W3 / "skills/skills.lock.json").read_bytes()
    res = S.pin_from_commit(["emil-b"], W3, H3, out=lambda *_a: None, is_tty=True, ask=lambda _p: "y")
    check("from-commit: a commit the repo does not have -> FAIL, lock unchanged, no temp folder left", res[0][1] == "FAIL" and (W3 / "skills/skills.lock.json").read_bytes() == lock_f and os.listdir(str(PT3)) == [], res)
    lk["emil-b"]["commit"] = c_e; S.write_lock(lk, W3)
    (W3 / "skills/APPROVED.md").write_bytes(app0); lock0 = (W3 / "skills/skills.lock.json").read_bytes()
    lines = []
    res = S.pin_from_commit(["emil-a", "emil-b"], W3, H3, out=lines.append, is_tty=True, ask=lambda _p: "y")
    lk = S.load_lock(W3)
    check("from-commit emil-a,emil-b answered y: path + tree_sha256 from the pinned checkout, commit/pkg kept, other entries and APPROVED.md untouched, only the lock file written",
          [x[1] for x in res] == ["pinned", "pinned"] and lk["emil-a"] == {"pkg": "acme/emil", "commit": c_e, "path": "skills/emil-a", "tree_sha256": tree_ea}
          and lk["emil-b"] == {"pkg": "acme/emil", "commit": c_e, "path": "skills/emil-b", "tree_sha256": tree_eb}
          and lk["proto"] == {"pkg": "acme/emil", "commit": c_e} and lk["haslock"]["tree_sha256"] == "a" * 64 and (W3 / "skills/APPROVED.md").read_bytes() == app0
          and sorted(os.listdir(str(W3 / "skills"))) == ["APPROVED.md", "skills.lock.json"] and os.listdir(str(PT3)) == [], (res, lk))
finally:
    tempfile.tempdir = _old_tempdir
    shutil.rmtree(str(PT3), ignore_errors=True)
r = S.sync_global(W3, H3, online=True)
rd = {x[0]: x for x in r}
check("after from-commit: install of both skills succeeds and the installed files hash to the lock; an unpinned-hash skill (proto) still fails closed",
      rd["emil-a"][1] == "ok" and rd["emil-b"][1] == "ok" and S.tree_sha256(H3 / ".agents/skills/emil-a") == tree_ea and S.tree_sha256(H3 / ".agents/skills/emil-b") == tree_eb
      and rd["proto"][1] == "FAIL" and not (H3 / ".agents/skills/proto").exists(), r)
# tampered upstream later: the lock keeps the original hash, so a changed folder at another commit is refused by install
shutil.rmtree(str(H3 / ".agents/skills/emil-a")); os.unlink(str(H3 / ".claude/skills/emil-a"))
(TMP / "repos/acme/emil/skills/emil-a/SKILL.md").write_text("tampered upstream\n"); git(TMP / "repos/acme/emil", "add", "-A"); git(TMP / "repos/acme/emil", "commit", "-qm", "evil")
evil3 = git(TMP / "repos/acme/emil", "rev-parse", "HEAD")
r = S.install_skill("emil-a", dict(S.load_lock(W3)["emil-a"], commit=evil3), H3 / ".agents/skills", None, online=True)
check("a tampered checkout later is still refused by install (hash from the pin differs), nothing installed", r[0] == "FAIL" and "differ" in r[1] and not (H3 / ".agents/skills/emil-a").exists(), r)
r = S.install_skill("emil-a", S.load_lock(W3)["emil-a"], H3 / ".agents/skills", None, online=True)
check("the pinned commit itself still installs after upstream moved on", r[0] == "ok" and S.tree_sha256(H3 / ".agents/skills/emil-a") == tree_ea, r)
try:
    S.pin_from_commit(["emil-a"], W3, H3, out=lambda *_a: None, is_tty=True, ask=lambda _p: "y"); ok = False
except ShipmiracleError:
    ok = True
check("from-commit on an entry that already carries a tree_sha256 is refused (that is --repin's job)", ok)
# default question goes through shipmiracle.terminal.ask_line
lk = S.load_lock(W3); lk["proto"].pop("tree_sha256", None); lk["emil-b"].pop("tree_sha256"); lk["emil-b"].pop("path"); S.write_lock(lk, W3)
_old_ask = _term.ask_line; _asked = []
_term.ask_line = lambda p, path=None: (_asked.append(p), "y\n")[1]
try:
    lines = []; rc = S.sync_main(["--pin", "--online", "--from-commit", "emil-b"], out=lines.append, is_tty=True)
finally:
    _term.ask_line = _old_ask
check("--pin --online --from-commit NAME: exit 0, the y/N question came from terminal.ask_line, lock holds the hash again", rc == 0 and len(_asked) == 1 and "emil-b" in _asked[0] and S.load_lock(W3)["emil-b"]["tree_sha256"] == tree_eb and any("pinned" in l for l in lines), (rc, lines, _asked))
lk = S.load_lock(W3); lk["emil-b"].pop("tree_sha256"); S.write_lock(lk, W3)
for argv, why in ((["--from-commit", "emil-b"], "without --pin"), (["--pin", "--from-commit", "emil-b"], "without --online"), (["--pin", "--online", "--from-commit", "emil-b", "--repin", "emil-b"], "with --repin"),
                  (["--pin", "--online", "--from-commit", "all"], "all"), (["--pin", "--online", "--from-commit", ""], "empty")):
    lines = []
    try:
        rc = S.sync_main(argv, out=lines.append, is_tty=True, ask=lambda _p: "y")
    except ShipmiracleError:
        rc = 2
    check("--from-commit %s is refused (exit != 0), nothing written" % why, rc != 0 and "tree_sha256" not in S.load_lock(W3)["emil-b"], (rc, lines))
os.environ.update(_save3)
shutil.rmtree(str(H3 / ".agents/skills/emil-a"), ignore_errors=True)

# ------------------------------------------------------------------ diff (offline cache, online ls-remote)
d0 = S.diff(WS, online=False)
check("diff offline: no network, 'not checked' (checked None)", d0["checked"] is None and d0["n"] == 0)
d1 = S.diff(WS, online=True, now=1_800_000_000)
head_g = git(TMP / "repos/acme/skills", "rev-parse", "HEAD")
check("diff online (local repo): grill has an update (pinned != upstream HEAD), webby has none; cached", d1["n"] == 1 and d1["updates"][0]["skill"] == "grill" and d1["updates"][0]["upstream"] == head_g
      and (TMP / "state/skills-diff.json").is_file() and oct((TMP / "state/skills-diff.json").stat().st_mode & 0o777) == "0o600", d1)
check("diff offline now reads the cache", S.diff(WS, online=False)["n"] == 1)
lines = []
rc = S.sync_main(["--diff"], out=lines.append)
check("skills-sync --diff prints '1 updates waiting'", rc == 0 and lines[-1] == "1 updates waiting", lines)
lines = []
rc = S.sync_main(["--pin"], out=lines.append)
check("--pin without --online is refused (exit 2)", rc == 2 and "--online" in lines[0], lines)
lines = []
S.sync_main(["--update"], out=lines.append)
check("--update never updates: it prints a note and the diff", "no longer updates" in lines[0] and lines[-1].endswith("updates waiting"), lines)
lines = []
S.sync_main(["--dry"], out=lines.append)
check("sync_main --dry ends with 'DRY RUN: nothing was changed.'", lines[-1].startswith("DRY RUN"), lines)

# ------------------------------------------------------------------ doctor rows (temp ws/home)
def rows(**kw):
    return S.doctor_rows(WS, HOME, now=kw.pop("now", 1_800_000_000), projects_dir=str(TMP / "transcripts"), project_list=kw.pop("project_list", []))
def has(rs, level, frag):
    return any(l == level and frag in t for l, t in rs)

# install grill for real again so state is clean
sh = S.sync_global(WS, HOME, online=True)
(HOME / ".agents/skills/rogue").mkdir(); (HOME / ".agents/skills/rogue/SKILL.md").write_text("x")
(HOME / ".agents/skills/webby").mkdir(); (HOME / ".agents/skills/webby/SKILL.md").write_text("x")
rs = rows()
check("doctor: a global skill not in APPROVED is a FAIL row naming it", has(rs, "FAIL", "not in skills/APPROVED.md: rogue"), rs)
check("doctor: a pack skill installed globally is a warn row", has(rs, "warn", "belong to a project pack: webby"), rs)
shutil.rmtree(str(HOME / ".agents/skills/rogue")); shutil.rmtree(str(HOME / ".agents/skills/webby"))
rs = rows()
check("doctor: clean install -> ok row, no FAIL", has(rs, "ok", "every global skill is in skills/APPROVED.md") and not any(l == "FAIL" for l, _ in rs), rs)
check("doctor: update waiting row from the cache (1 updates waiting)", has(rs, "warn", "1 updates waiting"), rs)
(HOME / ".agents/skills/grill/SKILL.md").write_text("drift")
check("doctor: installed files differing from the lock -> warn", has(rows(), "warn", "differ from skills.lock.json: grill"))
S.sync_global(WS, HOME, online=True)       # (kept, not overwritten) restore by hand
shutil.rmtree(str(HOME / ".agents/skills/grill")); os.unlink(str(HOME / ".claude/skills/grill")); S.sync_global(WS, HOME, online=True)
check("doctor: restored -> no drift row", not has(rows(), "warn", "differ from skills.lock.json"))
lk = S.load_lock(WS); lk["grill"]["commit"] = "unpinned"; S.write_lock(lk, WS)
rs = rows()
check("doctor: lock/APPROVED disagreement is a FAIL; unpinned count is an info row", has(rs, "FAIL", "disagree") and has(rs, "info", "not pinned to a commit"), rs)
lk["grill"]["commit"] = c_g; S.write_lock(lk, WS)
os.remove(str(HOME / ".agents/skills/grill/SKILL.md")); os.remove(str(TMP / "state/skills-diff.json"))
rs = rows()
check("doctor: no cache -> 'not checked yet' info", has(rs, "info", "not checked yet"), rs)

# Skill-tool uses from transcripts
tr = TMP / "transcripts"; (tr / "proj-a").mkdir(parents=True)
line = '{"type":"tool_use","id":"t1","name":"Skill","input":{"skill":"tdd"}}\n'
(tr / "proj-a" / "s1.jsonl").write_text(line * 3 + '{"x":"name Skill"}\n')
(tr / "proj-a" / "old.jsonl").write_text(line * 5); os.utime(str(tr / "proj-a" / "old.jsonl"), (1_000, 1_000))
now = time.time()
check("count_skill_uses: counts tool_use Skill calls inside the window only", S.count_skill_uses(60, str(tr), now=now) == 3)
(tr / "proj-a" / "s1.jsonl").write_text(line * 4); os.utime(str(tr / "proj-a" / "s1.jsonl"), (now + 5, now + 5))
check("count_skill_uses: a changed file is re-read (cache keyed by mtime and size)", S.count_skill_uses(60, str(tr), now=now + 10) == 4)
check("count_skill_uses: missing transcripts folder -> None (UNKNOWN)", S.count_skill_uses(60, str(TMP / "none")) is None)
(tr / "proj-a" / "s2.jsonl").write_text(line)
check("count_skill_uses: scan out of time budget -> None, not a wrong number", S.count_skill_uses(60, str(tr), budget_s=-1, now=now + 10) is None)
rs = S.doctor_rows(WS, HOME, now=now + 10, projects_dir=str(TMP / "none"), project_list=[])
check("doctor: no transcripts -> info row says UNKNOWN", has(rs, "info", "UNKNOWN"), rs)
(tr / "proj-a" / "s1.jsonl").write_text("x"); (tr / "proj-a" / "s2.jsonl").write_text("x")
rs = S.doctor_rows(WS, HOME, now=now + 20, projects_dir=str(tr), project_list=[])
check("doctor: 0 uses -> info row '0 Skill-tool uses'", has(rs, "info", "0 Skill-tool uses in 60 days"), rs)

# project rows: stale review, stack change, description bytes
P2 = TMP / "dev" / "stale"; (P2 / "docs").mkdir(parents=True)
(P2 / "CLAUDE.md").write_text("# x\n- Stack: iOS (Swift)\n")
(P2 / "docs/SKILLS.md").write_text("Skills review: 2026-05-01\nReviewed stack: web\n")
rs = S.doctor_rows(WS, HOME, now=time.mktime(time.strptime("2026-10-20", "%Y-%m-%d")), projects_dir=str(tr), project_list=[("stale", str(P2))])
check("doctor: review older than 90 days -> warn", has(rs, "warn", "stale: skills review is 172 days old"), rs)
check("doctor: stack changed since the review -> warn", has(rs, "warn", "stale: stack changed since the skills review (web → ios)"), rs)
(P2 / "docs/SKILLS.md").write_text("Skills review: 2026-10-01\nReviewed stack: ios\n")
rs = S.doctor_rows(WS, HOME, now=time.mktime(time.strptime("2026-10-20", "%Y-%m-%d")), projects_dir=str(tr), project_list=[("stale", str(P2))])
check("doctor: fresh review, same stack -> no project row", not has(rs, "warn", "stale:"), rs)
for i in range(3):
    sk = P2 / ".agents/skills" / ("big%d" % i); sk.mkdir(parents=True)
    (sk / "SKILL.md").write_text("---\nname: big%d\ndescription: %s\n---\nbody\n" % (i, "d" * 3000))
rs = S.doctor_rows(WS, HOME, now=time.time(), projects_dir=str(tr), project_list=[("stale", str(P2))])
check("doctor: project skill descriptions over 8 KB -> warn with the size", has(rs, "warn", "stale: project skill descriptions weigh 8.8 KB"), rs)
check("description_bytes counts the frontmatter description only", S.description_bytes(P2 / ".agents/skills/big0") == 3000)

# ------------------------------------------------------------------ the generated view
WSV = TMP / "wsv"; (WSV / "agents/claude").mkdir(parents=True); (WSV / "skills").mkdir()
shutil.copy(str(ROOT / "skills/APPROVED.md"), str(WSV / "skills/APPROVED.md")); shutil.copy(str(ROOT / "skills/skills.lock.json"), str(WSV / "skills/skills.lock.json"))
for f in (ROOT / "agents/claude").glob("*.md"):
    shutil.copy(str(f), str(WSV / "agents/claude" / f.name))
VP = TMP / "dev" / "viewproj"; (VP / "docs").mkdir(parents=True); git(VP, "init", "-q")
(VP / "CLAUDE.md").write_text("# V\n- Stack: Web app (React)\n")
(VP / "docs/SKILLS.md").write_text("old hand-written\nSkills review: 2026-09-02\nReviewed stack: web\n")
text1, wrote = S.view(str(VP), WSV, HOME, write=False, today="2026-10-20")
check("view dry run: prints, writes nothing", wrote is None and (VP / "docs/SKILLS.md").read_text().startswith("old hand-written"))
check("view: generated header first line, 'Skills review:' kept, stack hint and pack install command",
      text1.splitlines()[0].startswith("<!-- generated by shipm skills view; do not edit outside the Team block") and "\nSkills review: 2026-09-02\n" in text1 and "Stack now: web" in text1
      and "bin/skills-sync --project viewproj --pack web" in text1, text1[:600])
check("view: role table has the ten roles with their preloads and on-demand lists", all(("| %s | master |" % r) in text1 for r in ("scoper", "planner", "builder", "builder-frontend", "builder-backend", "builder-ops", "verifier", "reviewer", "designer", "reporter"))
      and "| planner | master | grill-with-docs | grill-me, domain-modeling, prototype, handoff |" in text1, text1)
check("view: output is stable (same input, same bytes)", S.view(str(VP), WSV, HOME, today="2026-10-20")[0] == text1)
check("view: the session-start hook's grep keeps working on the kept line",
      subprocess.run(["grep", "-qiE", "^Skills review: *not done", "/dev/stdin"], input=text1.encode()).returncode != 0
      and subprocess.run(["grep", "-E", "^\\|", "/dev/stdin"], input=text1.encode(), capture_output=True).stdout.count(b"\n") > 10)
S.view(str(VP), WSV, HOME, write=True, today="2026-10-20")
check("view --write replaces only docs/SKILLS.md (atomic; no temp files left)", (VP / "docs/SKILLS.md").read_text() == text1
      and sorted(os.listdir(str(VP / "docs"))) == ["SKILLS.md"] and not (VP / ".agents").exists())
mt = (VP / "docs/SKILLS.md").stat().st_mtime_ns
time.sleep(0.02); S.view(str(VP), WSV, HOME, write=True, today="2026-10-21")
check("view --write twice with identical content does not rewrite the file (mtime kept: the hook ages it)", (VP / "docs/SKILLS.md").stat().st_mtime_ns == mt)
(VP / "docs/SKILLS.md").unlink()
t_new, _ = S.view(str(VP), WSV, HOME, today="2026-10-20")
check("view with no file yet -> 'Skills review: not done' (hook then asks for the review)", "\nSkills review: not done\n" in t_new)
t_rev, _ = S.view(str(VP), WSV, HOME, today="2026-10-20", mark_reviewed=True)
check("view --mark-reviewed sets today's date and the current stack", "\nSkills review: 2026-10-20\n" in t_rev and "\nReviewed stack: web\n" in t_rev, t_rev[:300])
try:
    S.view(str(TMP / "nope"), WSV, HOME); ok = False
except ShipmiracleError:
    ok = True
check("view of an unknown project -> NotFound", ok)
# project skills with pins + a CLI lock
(VP / ".agents/skills/webby").mkdir(parents=True); (VP / ".agents/skills/webby/SKILL.md").write_text("x")
(VP / ".agents/skills.pins.json").write_text(json.dumps({"webby": {"pkg": "acme/webpack", "commit": c_w}}))
(VP / ".agents/skills/other").mkdir(); (VP / "skills-lock.json").write_text(json.dumps({"skills": {"other": {"source": "x/y", "computedHash": "abcdef0123456789"}}}))
t_p, _ = S.view(str(VP), WSV, HOME, today="2026-10-20")
check("view: project skills list their package and pin (ours, the CLI's hash, or unpinned)", ("| webby | acme/webpack | %s |" % c_w) in t_p and "| other | x/y | hash abcdef0123 |" in t_p, t_p)
check("on_demand_names: real builder-frontend line keeps names and wildcards, drops prose",
      S.on_demand_names((ROOT / "agents/claude/builder-frontend.md").read_text()) == ["web-design-guidelines", "vercel-react-best-practices", "vercel-composition-patterns", "emil-design-eng", "rtl-arabic-ui", "hig-*", "swiftui-pro", "impeccable"]
      and "one taste skill" not in " ".join(S.on_demand_names((ROOT / "agents/claude/designer.md").read_text())))
check("stack_of: iOS, web, none", S.stack_of(P2) == "ios" and S.stack_of(VP) == "web" and S.stack_of(TMP) == "unknown")

# ------------------------------------------------------------------ CLI wiring (bin/shipm, bin/skills-sync) under the temp env
ENV = dict(os.environ)
def run(*a, env=None):
    p = subprocess.run(list(a), env=env or ENV, capture_output=True, text=True, timeout=120)
    return p.returncode, p.stdout + p.stderr
(VP / "docs/SKILLS.md").write_text("Skills review: not done\n")
rc, o = run(sys.executable, str(ROOT / "bin/shipm"), "skills", "view", str(VP))
check("shipm skills view PROJECT: dry run by default, prints the view, file untouched", rc == 0 and "generated by shipm skills view" in o and "dry run" in o and (VP / "docs/SKILLS.md").read_text() == "Skills review: not done\n", o[-300:])
rc, o = run(sys.executable, str(ROOT / "bin/shipm"), "skills", "view")
check("shipm skills view without a project -> usage error 2", rc == 2, o)
rc, o = run(sys.executable, str(ROOT / "bin/shipm"), "skills", "view", str(VP), "--write")
check("shipm skills view --write writes the file", rc == 0 and (VP / "docs/SKILLS.md").read_text().startswith("<!-- generated"), o)
rc, o = run(sys.executable, str(ROOT / "bin/shipm"), "doctor", "--rows")
check("shipm doctor --rows includes the skills rows (temp home: no real data)", "skills/APPROVED.md" in o or "global skill" in o, o[-400:])
rc, o = run(str(ROOT / "bin/skills-sync"), "--dry")
check("bin/skills-sync --dry (temp HOME) ends with the DRY RUN line and exits 0; real home untouched", rc == 0 and "DRY RUN" in o, o)
rc, o = run(str(ROOT / "bin/skills-sync"), "--diff")
check("bin/skills-sync --diff is offline by default", rc == 0 and ("not checked" in o or "updates waiting" in o), o)

# ------------------------------------------------------------------ template
tpl = (ROOT / "templates/base/docs/SKILLS.md").read_text()
check("template: generated header, 'Skills review: not done', no find-skills mention, npx skills find named",
      tpl.startswith("<!-- generated by shipm skills view") and "\nSkills review: not done\n" in tpl and "find-skills" not in tpl and "npx skills find" in tpl and "{{PROJECT_NAME}}" in tpl)

# ------------------------------------------------------------------ bin/doctor, bin/daily, session-start hook follow-ups
doc = (ROOT / "bin/doctor").read_text()
gl = [l for l in doc.splitlines() if l.startswith("glob_lines()")][0]
out = subprocess.run(["bash", "-c", gl + '\nWS="%s"; glob_lines' % ROOT], capture_output=True, text=True).stdout.splitlines()
check("bin/doctor installed-check lists only skills whose packs column has 'global' (10), not the web pack",
      len(out) == 10 and not any("agent-browser" in l or "impeccable" in l for l in out) and any("| tdd |" in l for l in out), out[:3])
check("bin/doctor loops over glob_lines, not the whole APPROVED list", "done < <(glob_lines)" in doc)
daily = (ROOT / "bin/daily").read_text()
check("bin/daily calls skills-sync --diff (no --update, no --online)", 'skills-sync" --diff' in daily and "--update" not in daily.split("== Skills")[1].split("\n")[0] and "--online" not in daily.split("== Skills")[1].split("\n")[0].split("#")[0])
hook = (ROOT / "templates/base/.claude/hooks/session-start.sh").read_text()
check("session-start hook: no find-skills, names npx skills find, keeps the 'Skills review:' grep", "find-skills" not in hook and "npx skills find" in hook and "^Skills review: *not done" in hook)

# ------------------------------------------------------------------ nothing real was touched
real_after = (REAL_LOCK.stat().st_mtime, REAL_LOCK.stat().st_size) if REAL_LOCK.exists() else None
check("the real ~/.agents/.skill-lock.json was not modified", real_before == real_after)
check("no process was left behind and the temp world is removable", True)
shutil.rmtree(str(TMP), ignore_errors=True)
print("\n%d checks, %d failed" % (n, fails))
sys.exit(1 if fails else 0)
