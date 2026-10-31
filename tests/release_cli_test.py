#!/usr/bin/env python3
"""release_cli_test: `shipm release status` (read-only) and `shipm release mark X.Y [--date] [--push]` (owner only), and the flow gate in front of them.
Fixture git repositories, a bare temp repository as the remote (no network). mark: bad versions, an existing release, a chat (CLAUDECODE), a tag-triggered
workflow only adds a warning with --push (a plain mark never pushes), --date picks the newest commit on or before the day, no remote. The old `release` actions keep working.
Gate: `shipm release mark` is refused in both gate copies, `release status|denylist|export` are not (cases also in tests/fixtures/flow/p5-shipmiracle-targets.json,
run by flow_gate_playbook_test for both copies).
Run: python3 tests/release_cli_test.py"""
import json, os, pathlib, re, subprocess, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import shipmiracle_isolation  # noqa: F401 (release_fixture applies the full test isolation before anything else runs)
import release_fixture as X
from release_fixture import check, git, mkrepo, commit, shipm

def tagobj(d, name):
    return git(d, "cat-file", "-t", "refs/tags/" + name, check_rc=False)

def with_remote(d):
    bare = X.TMP / (pathlib.Path(d).name + "-origin.git")
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], env=X.ENV, check=True)
    git(d, "remote", "add", "origin", str(bare))
    return bare

def remote_tags(bare):
    return git(bare, "tag", "--list")

# ---------------------------------------------------------------- status
s = mkrepo("st", "2026-01-10")
git(s, "tag", "-a", "v1.0", "-m", "r", date="2026-01-10")
commit(s, "later", "2026-02-01")
(s / "VERSION").write_text("1.1\n")
rc, o, e = shipm("release", "status", "--project", str(s))
check("status: exit 0, three lines with last release, working version and what is since", rc == 0 and o.splitlines() == [
    "last release: 1.0 (2026-01-10, tag v1.0)", "working version: 1.1 (from VERSION)", "since the last release: 0 changes, 1 commit"], (rc, o, e))
rc, o, e = shipm("release", "status", "--project", str(s), "--json")
j = json.loads(o)
check("status --json: {last:{version,date,tag}, working:{version,source}, since:{changes,commits}}", rc == 0 and j == {"last": {"version": "1.0", "date": "2026-01-10", "tag": "v1.0"},
      "working": {"version": "1.1", "source": "VERSION"}, "since": {"changes": 0, "commits": 1}}, o)
snap = lambda: (git(s, "for-each-ref"), sorted(str(p.relative_to(s)) for p in s.rglob("*") if ".git" not in p.parts), sorted(str(p) for p in X.STATE.rglob("*")))
b = snap(); shipm("release", "status", "--project", str(s)); shipm("release", "status", "--project", str(s), "--json")
check("status writes nothing (no tag, no ref, no file in the project, nothing in the state folder)", snap() == b)
n0 = mkrepo("st0", "2026-01-10")
rc, o, e = shipm("release", "status", "--project", str(n0))
check("status without any tag says so", rc == 0 and o.startswith("last release: none"), o)
rc, o, e = shipm("release", "status", "--project", str(X.TMP))
check("status outside a workspace project: exit 3, a clear message", rc == 3 and "not inside a git project" in e or "not one of the workspace projects" in e, (rc, e))

# ---------------------------------------------------------------- mark: the normal case (the tag stays local; --push pushes)
m = mkrepo("mk", "2026-01-10")
c_a = commit(m, "second", "2026-02-01")
c_b = commit(m, "third", "2026-03-01")
bare = with_remote(m)
rc, o, e = shipm("release", "mark", "1.2", "--project", str(m))
check("mark 1.2: exit 0, tag v1.2 created and NOT pushed by default; the output prints the exact push command", rc == 0 and "tagged v1.2 at " + c_b[:7] in o and "pushed to" not in o and"git push origin v1.2" in o, (rc, o, e))
check("mark: an annotated tag (a tag object, message 'Release 1.2') on HEAD", tagobj(m, "v1.2") == "tag" and git(m, "rev-parse", "v1.2^{commit}") == c_b and git(m, "tag", "-l", "--format=%(contents:subject)", "v1.2") == "Release 1.2")
check("mark: the remote does NOT have the tag", remote_tags(bare) == "", remote_tags(bare))
rc, o, e = shipm("release", "status", "--project", str(m))
check("status after mark: last release is 1.2", o.splitlines()[0].startswith("last release: 1.2 (2026-03-01, tag v1.2)"), o)

rc, o, e = shipm("release", "mark", "1.3", "--push", "--project", str(m))
check("mark --push: pushed to origin, the remote has the tag, no deploy warning without a workflow", rc == 0 and "pushed to origin" in o and remote_tags(bare) == "v1.3" and "may start a deploy" not in (o + e), (rc, o, e, remote_tags(bare)))

# ---------------------------------------------------------------- mark: refusals
before = git(m, "tag", "--list")
for bad in ("1.", "v1.3", "1.2.3.4.5", "abc", "1..2", "1.2-beta", "-1", "1.2 ", "٣.٤"):
    rc, o, e = shipm("release", "mark", bad, "--project", str(m))
    check("mark refuses the version %r (exit 2, no tag)" % bad, rc in (2,) and git(m, "tag", "--list") == before, (rc, e))
rc, o, e = shipm("release", "mark", "--project", str(m))
check("mark without a version: exit 2", rc == 2, (rc, e))
for dup in ("1.2", "1.2.0", "1.2.0.0"):
    rc, o, e = shipm("release", "mark", dup, "--project", str(m))
    check("mark refuses %s: release 1.2 already exists (exit 2, nothing moved)" % dup, rc == 2 and "already exists" in e and git(m, "tag", "--list") == before and git(m, "rev-parse", "v1.2^{commit}") == c_b, (rc, e))
git(m, "tag", "3.0", c_a)
rc, o, e = shipm("release", "mark", "3.0", "--project", str(m))
check("mark refuses a version that exists as a bare tag (no v)", rc == 2 and "already exists" in e and tagobj(m, "v3.0") != "tag", (rc, e))
for bd in ("2026-13-01", "2026-02-30", "01-02-2026", "yesterday", "2026-2-1"):
    rc, o, e = shipm("release", "mark", "4.0", "--date", bd, "--project", str(m))
    check("mark refuses the date %r (exit 2, no tag)" % bd, rc == 2 and tagobj(m, "v4.0") != "tag", (rc, e))
rc, o, e = shipm("release", "mark", "4.0", "--date", "2025-12-31", "--project", str(m))
check("mark: a day before the first commit -> exit 3, no tag", rc == 3 and tagobj(m, "v4.0") != "tag", (rc, e))
chat = dict(X.ENV, CLAUDECODE="1", SHIPMIRACLE_ENFORCE_OWNER="1")
rc, o, e = shipm("release", "mark", "5.0", "--project", str(m), env=chat)
check("mark in a Claude chat (CLAUDECODE set): refused, exit 4, no tag, nothing pushed", rc == 4 and "not inside a Claude Code chat" in e.replace("\n", " ") or "for the owner in a terminal" in e, (rc, e))
check("... and no tag v5.0 exists locally or on the remote", tagobj(m, "v5.0") != "tag" and "v5.0" not in remote_tags(bare))
rc, o, e = shipm("release", "status", "--project", str(m), env=chat)
check("status is allowed in a chat (read-only)", rc == 0, (rc, e))
nr = X.DEV / "notarepo"; nr.mkdir()
rc, o, e = shipm("release", "mark", "1.0", "--project", str(nr))
check("mark in a folder that is not a project: exit 3", rc == 3, (rc, e))

# ---------------------------------------------------------------- mark --date
dt = mkrepo("dt", "2026-01-10")
d1 = git(dt, "rev-parse", "HEAD")
d2 = commit(dt, "feb", "2026-02-15")
d3 = commit(dt, "mar", "2026-03-15")
bare_dt = with_remote(dt)
rc, o, e = shipm("release", "mark", "1.0", "--date", "2026-02-20", "--project", str(dt))
check("mark --date 2026-02-20: tags the newest commit on or before that day (the 15 Feb one)", rc == 0 and git(dt, "rev-parse", "v1.0^{commit}") == d2 and "(2026-02-15)" in o, (rc, o, e))
rc, o, e = shipm("release", "mark", "0.9", "--date", "2026-02-15", "--project", str(dt))
check("mark --date on the day of a commit includes that commit", rc == 0 and git(dt, "rev-parse", "v0.9^{commit}") == d2, (rc, o, e))
rc, o, e = shipm("release", "mark", "0.1", "--date", "2026-01-10", "--project", str(dt))
check("mark --date on the first commit's day", rc == 0 and git(dt, "rev-parse", "v0.1^{commit}") == d1, (rc, o, e))

# ---------------------------------------------------------------- mark: a tag-triggered workflow only adds a warning when --push is used
def wfrepo(name, fname, body):
    r = mkrepo(name, "2026-01-10")
    (r / ".github" / "workflows").mkdir(parents=True)
    (r / ".github" / "workflows" / fname).write_text(body)
    git(r, "add", "-A"); git(r, "commit", "-q", "-m", "ci", date="2026-01-11")
    return r, with_remote(r)

w, bare_w = wfrepo("wf", "release.yml", "name: release\non:\n  push:\n    tags:\n      - 'v*'\njobs:\n  x:\n    runs-on: ubuntu-latest\n    steps: []\n")
(w / ".github" / "workflows" / "ci.yml").write_text("name: ci\non:\n  push:\n    branches: [main]\n")
rc, o, e = shipm("release", "mark", "1.0", "--project", str(w))
check("tag-triggered workflow, no --push: tag local, nothing pushed, exact push command printed, no warning needed", rc == 0 and tagobj(w, "v1.0") == "tag" and "git push origin v1.0" in o and remote_tags(bare_w) == "", (rc, o, e))
rc, o, e = shipm("release", "mark", "1.1", "--push", "--project", str(w))
check("--push with a tag-triggered workflow: pushes, and warns 'this push may start a deploy: release.yml'", rc == 0 and "pushed to origin" in o and remote_tags(bare_w) == "v1.1" and "this push may start a deploy: release.yml" in (o + e), (rc, o, e, remote_tags(bare_w)))
for nm, fname, body, why in (
    ("wf2", "ci.yml", "name: ci\non:\n  push:\n    branches: [main]\n  pull_request:\n# tags: only in a comment\n", "a branches-only push trigger and a commented tags: do not warn"),
):
    r, bw = wfrepo(nm, fname, body)
    rc, o, e = shipm("release", "mark", "1.0", "--push", "--project", str(r))
    check("--push: " + why, rc == 0 and remote_tags(bw) == "v1.0" and "may start a deploy" not in (o + e), (rc, o, e))
for nm, fname, body, why in (
    ("wf3", "x.yaml", "on:\n  push:\n    tags-ignore:\n      - 'nightly*'\n", "tags-ignore (a .yaml file)"),
    ("wf4", "p.yml", "on: push\njobs: {}\n", "`on: push` with no filter at all"),
    ("wf5", "q.yml", "on: [push, pull_request]\njobs: {}\n", "`on: [push, ...]`"),
    ("wf6", "r.yml", "on:\n  push:\n  pull_request:\njobs: {}\n", "a bare `push:` key"),
    ("wf7", "s.yml", "on:\n  create:\njobs: {}\n", "`on: create`"),
):
    r, bw = wfrepo(nm, fname, body)
    rc, o, e = shipm("release", "mark", "1.0", "--project", str(r))
    check("no --push, " + why + ": nothing pushed", rc == 0 and remote_tags(bw) == "" and tagobj(r, "v1.0") == "tag", (rc, o, e))
    rc, o, e = shipm("release", "mark", "1.1", "--push", "--project", str(r))
    check("--push, " + why + ": warns it may start a deploy: " + fname, rc == 0 and "this push may start a deploy: " + fname in (o + e), (rc, o, e))

# ---------------------------------------------------------------- mark: no remote, push failing
nr1 = mkrepo("noremote", "2026-01-10")
rc, o, e = shipm("release", "mark", "1.0", "--project", str(nr1))
check("no remote: the tag stays local and the output says so (exit 0)", rc == 0 and tagobj(nr1, "v1.0") == "tag" and "no git remote" in o, (rc, o, e))
rc, o, e = shipm("release", "mark", "1.1", "--push", "--project", str(nr1))
check("--push with no remote: exit 1, the message says the tag exists locally", rc == 1 and tagobj(nr1, "v1.1") == "tag" and "created locally" in e, (rc, e))
bad = mkrepo("badremote", "2026-01-10")
git(bad, "remote", "add", "origin", str(X.TMP / "does-not-exist.git"))
rc, o, e = shipm("release", "mark", "1.0", "--push", "--project", str(bad))
check("a failing push: exit 1, the tag stays, the message gives the command to push it later", rc == 1 and tagobj(bad, "v1.0") == "tag" and "created locally" in e and "git push origin v1.0" in e, (rc, e))
check("a second mark of the same version after that is refused (nothing is moved)", shipm("release", "mark", "1.0", "--project", str(bad))[0] == 2)

# ---------------------------------------------------------------- the old release actions still work
rc, o, e = shipm("release", "denylist")
check("release denylist still answers (no denylist on this machine: exit 3 with the old message)", rc == 3 and "no denylist yet" in e, (rc, o, e))
rc, o, e = shipm("release", "--help")
check("release --help lists denylist, export, status and mark", all(w_ in o for w_ in ("denylist", "export", "status", "mark")), o[:300])
rc, o, e = shipm("release", "bogus")
check("an unknown action is a usage error (exit 2)", rc == 2, (rc, e))

# ---------------------------------------------------------------- the gate: `release mark` is the owner's, in both copies
from shipmiracle.hooks import flow
legacy_p = X.ROOT / "hooks" / "flow-gate.sh"
def sub(txt):
    m_ = re.search(r'^ADMIN_SUB = \{.*?\}', txt, re.S | re.M)
    return m_.group(0) if m_ else ""
if legacy_p.is_file():
    legacy = legacy_p.read_text()
    check('both gate copies list "release": ("mark",) in ADMIN_SUB, identically', '"release": ("mark",)' in sub(legacy) and sub(legacy) == sub((X.ROOT / "shipmiracle" / "hooks" / "flow.py").read_text()))
else:       # exported tree: the legacy gate script is private and not shipped; the v1 copy is still checked on its own
    print("SKIP legacy gate copy comparison (the legacy gate script is not in this tree)")
    check('the v1 gate copy lists "release": ("mark",) in ADMIN_SUB', '"release": ("mark",)' in sub((X.ROOT / "shipmiracle" / "hooks" / "flow.py").read_text()))
for cmd in (["shipm", "release", "mark", "1.2"], ["bin/shipm", "release", "mark", "1.2", "--push"], ["shipm", "release", "--project", "x", "mark", "2.0"]):
    check("gate (v1 copy) refuses " + " ".join(cmd), flow.admin_seg([], [], cmd) is True)
for cmd in (["shipm", "release", "status"], ["shipm", "release", "status", "--json"], ["shipm", "release", "denylist"], ["shipm", "release", "denylist", "--show-hashes"], ["shipm", "release", "export", "--dry-run"]):
    check("gate (v1 copy) does not refuse " + " ".join(cmd), flow.admin_seg([], [], cmd) is False)
fx = json.loads((X.ROOT / "tests/fixtures/flow/p5-shipmiracle-targets.json").read_text())
check("the gate fixture (run against both copies by flow_gate_playbook_test) names mark as denied and status/denylist/export as allowed",
      any("release mark" in c for c in fx["admin_denied"]) and all(any(k in c for c in fx["admin_allowed"]) for k in ("release status", "release denylist", "release export")))

X.finish()
