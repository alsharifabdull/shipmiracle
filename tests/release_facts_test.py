#!/usr/bin/env python3
"""release_facts_test: shipmiracle/report/release.py (last release, working version, since, history) and its place in `shipm report panel`.
Fixture git repositories with fixed commit dates (Xcode / package.json / pyproject / VERSION / none), a tag on a side branch, lightweight and annotated tags,
a git timeout (fail soft), read-only behaviour, and the panel JSON shape (release, history, caps.release; every older key unchanged).
Run: python3 tests/release_facts_test.py"""
import json, os, pathlib, subprocess, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import shipmiracle_isolation  # noqa: F401 (release_fixture applies the full test isolation before anything else runs)
import release_fixture as X
from release_fixture import check, git, mkrepo, commit

from shipmiracle.report import release as R, panel  # noqa: E402
from shipmiracle.playbook import store  # noqa: E402

# ---------------------------------------------------------------- 1. last release and since (tags)
d = mkrepo("tags1", "2026-01-10")
c1 = git(d, "rev-parse", "HEAD")
git(d, "tag", "-a", "v1.0", "-m", "Release 1.0", date="2026-01-10")
c2 = commit(d, "two", "2026-02-01")
c3 = commit(d, "three", "2026-03-01")
f = R.facts(d)
check("last release: annotated tag v1.0 with the date of its commit", f["last"] == {"version": "1.0", "date": "2026-01-10", "tag": "v1.0"}, f)
check("since: two commits after the tag, no delivered CR yet", f["since"] == {"changes": 0, "commits": 2}, f)
check("working: no version file -> None", f["working"] is None, f)

git(d, "tag", "v1.1", c2)                                                       # lightweight, newer than v1.0 on the main line
git(d, "tag", "build-5", c3); git(d, "tag", "v1-beta", c3); git(d, "tag", "v1.2.3.4.5", c3)    # not version tags
f = R.facts(d)
check("last release: a lightweight tag counts; names that are not versions are ignored", f["last"] == {"version": "1.1", "date": "2026-02-01", "tag": "v1.1"} and f["since"]["commits"] == 1, f)
git(d, "tag", "1.2", c3)                                                         # without the v
check("last release: a bare version tag (no v) counts", R.facts(d)["last"]["tag"] == "1.2" and R.facts(d)["last"]["version"] == "1.2", R.facts(d))
git(d, "tag", "v1.10", c3)
check("last release: versions compare as numbers on the same commit (1.10 > 1.2)", R.facts(d)["last"]["tag"] == "v1.10", R.facts(d))

# a tag on a side branch is ignored, also after the branch is merged (it is not on the main line)
s = mkrepo("side", "2026-01-10")
git(s, "tag", "v1.0")
git(s, "checkout", "-q", "-b", "side")
sc = commit(s, "side work", "2026-01-20")
git(s, "tag", "v9.0", sc)
git(s, "checkout", "-q", "main")
commit(s, "main work", "2026-01-25", fname="g.txt")
check("side branch tag v9.0 is not reachable from main: ignored", R.facts(s)["last"]["tag"] == "v1.0", R.facts(s))
git(s, "merge", "-q", "--no-ff", "-m", "merge side", "side", date="2026-02-01")
check("... also after the merge (first-parent line only)", R.facts(s)["last"]["tag"] == "v1.0", R.facts(s))
git(s, "checkout", "-q", "side")
check("... and on the side branch itself the side tag is the last release", R.facts(s)["last"]["tag"] == "v9.0", R.facts(s))

# no tag at all, not a repository, empty repository
n = mkrepo("notag", "2026-01-10")
commit(n, "b", "2026-01-11")
check("no tag: last None, since counts every commit", R.facts(n)["last"] is None and R.facts(n)["since"] == {"changes": 0, "commits": 2}, R.facts(n))
plain = X.DEV / "plain"; plain.mkdir()
check("not a git repository: last None, working None, since zeros, no exception", R.facts(plain) == {"last": None, "working": None, "since": {"changes": 0, "commits": 0}}, R.facts(plain))
empty = X.DEV / "empty"; empty.mkdir(); git(empty, "init", "-q", "-b", "main")
check("repository without commits: no exception, last None", R.facts(empty)["last"] is None, R.facts(empty))

# ---------------------------------------------------------------- 2. working version from the version files
def with_tag(name, version_files, tag="v1.0"):
    r = mkrepo(name, "2026-01-10")
    git(r, "tag", "-a", tag, "-m", "r", date="2026-01-10")
    for rel, txt in version_files.items():
        p = r / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(txt)
    return r

PBX = "buildSettings = {\n MARKETING_VERSION = 1.4;\n};\nbuildSettings = {\n MARKETING_VERSION = 1.4;\n};\nbuildSettings = {\n MARKETING_VERSION = 1.0;\n};\nbuildSettings = {\n MARKETING_VERSION = \"$(OTHER)\";\n};\n"
r = with_tag("xc", {"App.xcodeproj/project.pbxproj": PBX})
check("Xcode: the most common MARKETING_VERSION (1.4 twice beats 1.0 once; $(VAR) ignored)", R.facts(r)["working"] == {"version": "1.4", "source": "Xcode project"}, R.facts(r))
r = with_tag("xc2", {"ios/App.xcodeproj/project.pbxproj": PBX})
check("Xcode: found one folder down", R.facts(r)["working"] == {"version": "1.4", "source": "Xcode project"}, R.facts(r))
r = with_tag("xc3", {"App.xcodeproj/project.pbxproj": PBX.replace("1.4", "1.0")})
check("Xcode: equal to the last release -> working None", R.facts(r)["working"] is None, R.facts(r))
r = with_tag("pkg", {"package.json": json.dumps({"name": "x", "version": "2.0.1"})})
check("package.json version", R.facts(r)["working"] == {"version": "2.0.1", "source": "package.json"}, R.facts(r))
r = with_tag("pkg2", {"package.json": json.dumps({"name": "x", "version": "1.0.0"})})
check("package.json 1.0.0 equals tag v1.0 -> None (trailing zeros do not matter)", R.facts(r)["working"] is None, R.facts(r))
r = with_tag("pkg3", {"package.json": "{not json"})
check("package.json broken -> None, no exception", R.facts(r)["working"] is None)
r = with_tag("py", {"pyproject.toml": '[build-system]\nrequires = ["x"]\n\n[project]\nname = "x"\nversion = "1.3.0"  # bump\n\n[tool.x]\nversion = "9.9"\n'})
check("pyproject.toml: [project] version only (not [tool.x])", R.facts(r)["working"] == {"version": "1.3.0", "source": "pyproject.toml"}, R.facts(r))
r = with_tag("ver", {"VERSION": "1.0.1\n"})
check("VERSION file", R.facts(r)["working"] == {"version": "1.0.1", "source": "VERSION"}, R.facts(r))
r = with_tag("verbad", {"VERSION": "next\n"})
check("VERSION file that is not a version -> None", R.facts(r)["working"] is None)
r = with_tag("multi", {"package.json": json.dumps({"version": "1.7"}), "VERSION": "5.0\n"})
check("several files: Xcode, then package.json, then pyproject, then VERSION (first wins)", R.facts(r)["working"]["source"] == "package.json", R.facts(r))
r = mkrepo("nolast", "2026-01-10"); (r / "VERSION").write_text("0.1\n")
check("no release yet: any version file is the working version", R.facts(r)["working"] == {"version": "0.1", "source": "VERSION"} and R.facts(r)["last"] is None, R.facts(r))
r = with_tag("lnk", {})
(r / "VERSION").symlink_to(X.TMP / "outside-version"); (X.TMP / "outside-version").write_text("7.0\n")
check("a symlinked version file is not read", R.facts(r)["working"] is None, R.facts(r))

# ---------------------------------------------------------------- 3. fail soft: timeout, no git
calls = []
real_run = R.RUN
def slow(argv, **kw):
    calls.append(argv)
    raise subprocess.TimeoutExpired(argv, kw.get("timeout"))
R.RUN = slow
try:
    fs = R.facts(d)
    check("timeout: last None, since zeros, no exception", fs["last"] is None and fs["since"] == {"changes": 0, "commits": 0}, fs)
    check("timeout: git is asked once (2 s), not once per fact", len(calls) == 1, len(calls))
finally:
    R.RUN = real_run
seen_kw = {}
def spy(argv, **kw):
    seen_kw.update(kw)
    return real_run(argv, **kw)
R.RUN = spy
try:
    R.facts(d)
finally:
    R.RUN = real_run
check("git is called with timeout=2.0, no shell, stdin closed", seen_kw.get("timeout") == 2.0 and seen_kw.get("shell") is False and seen_kw.get("stdin") == subprocess.DEVNULL, seen_kw)
def nogit(argv, **kw):
    raise FileNotFoundError("git")
R.RUN = nogit
try:
    check("git missing: all facts None / zero", R.facts(d)["last"] is None and R.facts(d)["since"]["commits"] == 0)
finally:
    R.RUN = real_run

# ---------------------------------------------------------------- 4. read-only
before = sorted(str(p.relative_to(d)) for p in d.rglob("*") if ".git" not in p.parts)
tags_before = git(d, "tag")
refs_before = git(d, "for-each-ref")
state_before = sorted(str(p) for p in X.STATE.rglob("*"))
R.facts(d)
check("facts write nothing: no file in the project, no tag or ref, nothing in the state folder",
      before == sorted(str(p.relative_to(d)) for p in d.rglob("*") if ".git" not in p.parts) and git(d, "tag") == tags_before and git(d, "for-each-ref") == refs_before
      and state_before == sorted(str(p) for p in X.STATE.rglob("*")))

# ---------------------------------------------------------------- 5. CRs: since.changes and history, and the panel contract
p = mkrepo("crs", "2026-01-10")
h1 = git(p, "rev-parse", "HEAD")
git(p, "tag", "-a", "v1.0", "-m", "r", date="2026-01-10")
h2 = commit(p, "feature two", "2026-02-01")
git(p, "tag", "-a", "v1.1", "-m", "r", date="2026-02-01")
h3 = commit(p, "feature three", "2026-03-01")
X.set_software(p)
sim = X.Sim(p, t=1775001600)
sim.deliver("Old work", head=h1)
sim.deliver("Second feature", head=h2)
sim.abandon("Dropped idea")
sim.deliver("Third feature", head=h3)
sim.deliver("Delivered without a recorded commit")
sim.append()
out = panel.data(p, X.STATE)
OLD_KEYS = {"v", "playbook", "cr", "stageLabels", "nextAction", "lastVerdict", "autopilot", "remote", "owner_check", "aside", "unread", "toolbox", "proposed_assets", "caps", "interview"}
check("panel: every older key is still there and the only new ones are release and history", set(out) == OLD_KEYS | {"release", "history"}, sorted(set(out) ^ OLD_KEYS))
check("panel: caps.release is true and the older caps are unchanged", out["caps"] == {"toolbox": True, "interview": True, "aside": True, "unread": True, "release": True}, out["caps"])
rel = out["release"]
check("panel: release shape {last:{version,date,tag}, working, since:{changes,commits}}", set(rel) == {"last", "working", "since"} and set(rel["last"]) == {"version", "date", "tag"}
      and rel["last"] == {"version": "1.1", "date": "2026-02-01", "tag": "v1.1"} and rel["working"] is None and set(rel["since"]) == {"changes", "commits"}, rel)
n_after = len(git(p, "rev-list", "v1.1..HEAD").split())       # feature three + whatever `playbook set` committed
check("panel: since.commits = the commits after v1.1; changes = the CR on one of them + the CR with no recorded commit closed after the release commit",
      rel["since"] == {"changes": 2, "commits": n_after} and n_after >= 1, (rel["since"], n_after, git(p, "log", "--format=%s", "v1.1..HEAD")))
hist = out["history"]
check("history: newest first, 5 finished CRs, keys id/title/status/closed/release",
      [h["id"] for h in hist] == ["CR-005", "CR-004", "CR-003", "CR-002", "CR-001"] and all(set(h) == {"id", "title", "status", "closed", "release"} for h in hist), hist)
by = {h["id"]: h for h in hist}
check("history: release = the version that first contained the CR's commit (CR-001 in 1.0, CR-002 in 1.1)", by["CR-001"]["release"] == "1.0" and by["CR-002"]["release"] == "1.1", by)
check("history: unreleased commit, abandoned CR and CR without a commit have release None", by["CR-004"]["release"] is None and by["CR-003"]["release"] is None and by["CR-005"]["release"] is None, by)
check("history: status and closed are the engine's (epoch seconds)", by["CR-003"]["status"] == "abandoned" and by["CR-001"]["status"] == "delivered" and all(isinstance(h["closed"], int) for h in hist), by)
check("history: JSON-serialisable", json.loads(json.dumps(out)) == out)

# max 10, newest first
sim2 = X.Sim(p, t=1777593600)
sim2.w = sim.w
for i in range(12):
    sim2.deliver("Bulk %d" % i)
sim2.append()
hist2 = panel.data(p, X.STATE)["history"]
check("history: at most 10 entries, newest first", len(hist2) == 10 and hist2[0]["title"] == "Bulk 11" and hist2[-1]["title"] == "Bulk 2", [h["title"] for h in hist2])

# a project without CRs and a project that is not a repository
q = mkrepo("nocr", "2026-01-10")
oq = panel.data(q, X.STATE)
check("panel: a project without a playbook or CRs still carries release and history ([])", oq["history"] == [] and oq["release"]["last"] is None and oq["caps"]["release"] is True, oq["release"])
check("panel: not a git repository -> release nulls, history [] (no exception)", panel.data(X.DEV / "plain", X.STATE)["release"] == {"last": None, "working": None, "since": {"changes": 0, "commits": 0}})

# CLI: shipm report panel prints the same shape
rc, o, e = X.shipm("report", "panel", "--project", str(p))
j = json.loads(o) if rc == 0 else {}
check("shipm report panel --project: exit 0, JSON has release, history, caps.release", rc == 0 and j.get("caps", {}).get("release") is True and "release" in j and isinstance(j.get("history"), list), (rc, e[-300:]))

X.finish()
