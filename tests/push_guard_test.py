#!/usr/bin/env python3
"""shipm push-check and the pre-push hook block (P8 T5): the registry decides where a repo may push. Local bare repos T/public.git, T/proj.git and
T/other.git stand in for remotes (file:// URLs are accepted by the registry only under SHIPMIRACLE_TEST=1); the real `git push` runs the real hook, which
runs the real `bin/shipm push-check`. Matrix: project -> public refused (R2), project -> own remote allowed, project -> an unregistered remote refused
(R1), extra remote allowed, export stage -> public without / with / stale / wrong-flags stamp (R3), wrong refs, delete, foreign author, an
unregistered repo (R4), Shipmiracle missing and an old Shipmiracle (the hook warns and allows). Zero network: `gh` on PATH is a logging fake, remotes are local.
Run: python3 tests/push_guard_test.py   (Python 3.9)"""
import json, os, pathlib, shutil, subprocess, sys, tempfile, time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = pathlib.Path(tempfile.mkdtemp(prefix="shipmiracle-pushg-")).resolve()
FAKEBIN = TMP / "fakebin"
FAKEBIN.mkdir()
GHLOG = TMP / "gh.log"
(FAKEBIN / "gh").write_text('#!/bin/sh\necho "$@" >> "%s"\nexit 9\n' % GHLOG)
os.chmod(str(FAKEBIN / "gh"), 0o755)
BASE_PATH = "%s:/usr/bin:/bin:/usr/sbin:/sbin" % FAKEBIN
os.environ.update(SHIPMIRACLE_TEST="1", SHIPMIRACLE_HOME=str(TMP / "home"), SHIPMIRACLE_STATE=str(TMP / "state"), SHIPMIRACLE_CONFIG=str(TMP / "cfg"), SHIPMIRACLE_DEV=str(TMP / "dev"),
                  HOME=str(TMP / "home"), PATH=BASE_PATH, GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1", SHIPMIRACLE_ENGINE=str(ROOT))
for k in ("CLAUDECODE", "SHIPMIRACLE_ENFORCE_OWNER", "SHIPMIRACLE_WS"):
    os.environ.pop(k, None)
for d in ("home", "state", "dev", "cfg"):
    (TMP / d).mkdir()
os.chmod(str(TMP / "cfg"), 0o700)

from shipmiracle import UsageError, config, projects, registry, state  # noqa: E402
from shipmiracle.release import pushcheck  # noqa: E402

fails = 0


def check(name, ok, info=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(info)[:700]))
    fails += 0 if ok else 1


EMAIL = "424242+octo-user@users.noreply.github.com"
NOREPLY_ENV = {"GIT_AUTHOR_NAME": "octo-user", "GIT_AUTHOR_EMAIL": EMAIL, "GIT_COMMITTER_NAME": "octo-user", "GIT_COMMITTER_EMAIL": EMAIL}
OTHER_ENV = {"GIT_AUTHOR_NAME": "Some Dev", "GIT_AUTHOR_EMAIL": "dev@example.invalid", "GIT_COMMITTER_NAME": "Some Dev", "GIT_COMMITTER_EMAIL": "dev@example.invalid"}


def git(cwd, *args, env=None, rc=False):
    e = dict(os.environ)
    e.update(env or OTHER_ENV)
    r = subprocess.run(["git"] + list(args), cwd=str(cwd), env=e, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    if rc:
        return r
    if r.returncode != 0:
        raise RuntimeError("git %s: %s" % (args, r.stderr))
    return r.stdout.strip()


def bare(name):
    p = TMP / "remote" / name
    p.parent.mkdir(exist_ok=True)
    git(TMP, "init", "-q", "--bare", str(p))
    return p


def url(p):
    return "file://" + str(pathlib.Path(p).resolve())


def refs(p):
    return git(p, "for-each-ref", "--format=%(refname)").split()


PUBLIC, PROJ, OTHER, EXTRA = bare("public.git"), bare("proj.git"), bare("other.git"), bare("extra.git")
HOOK = (ROOT / "templates/base/.githooks/pre-push").read_text()      # the shipped hook; the owner's own .githooks/pre-push must equal it (checked below where that file exists)


def make_repo(path, hook=True, env=None):
    path = pathlib.Path(path)
    path.mkdir(parents=True)
    git(path, "init", "-q")
    git(path, "symbolic-ref", "HEAD", "refs/heads/main")
    (path / "f.txt").write_text("1\n")
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "c1", env=env)
    if hook:
        h = path / ".git" / "hooks" / "pre-push"
        h.write_text(HOOK)
        os.chmod(str(h), 0o755)
    return path


def push(repo, target, *refspec, env=None):
    e = dict(os.environ)
    e.update(env or {})
    return subprocess.run(["git", "-C", str(repo), "push", url(target) if not isinstance(target, str) else target] + list(refspec or ["main"]),
                          env=e, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)


# ---- registry: seed -------------------------------------------------------------------------------------------
P = make_repo(TMP / "dev" / "proj")
U = make_repo(TMP / "dev" / "loose")                       # not registered
proj_id = projects.project_id(P)
registry.write_missing({"v": 1, "projects": {proj_id: {"name": "proj", "remote": url(PROJ), "extra_remotes": [{"name": "backup", "remote": url(EXTRA)}],
                                                       "protected": False, "exceptions": [], "team": "on", "standard": "auto", "test_paths": [], "agents": {}}}})
registry.add_remote_only("public-engine", url(PUBLIC), "public")

check("reg a: role defaults to project; public_engines() finds the remote-only entry", registry.role_of(registry.load()["projects"][proj_id]) == "project"
      and [x["remote"] for x in registry.public_engines()] == [url(PUBLIC)])
check("reg b: file:// remotes are refused when SHIPMIRACLE_TEST is not 1", (lambda: (os.environ.pop("SHIPMIRACLE_TEST"), registry.normalise_remote(url(PUBLIC)), os.environ.__setitem__("SHIPMIRACLE_TEST", "1"))[1])() is None)
check("reg c: file:// remotes normalise to the realpath under SHIPMIRACLE_TEST=1", registry.normalise_remote(url(PUBLIC)) == url(PUBLIC))
check("reg d: remote_arg reads owner/name as GitHub, rejects hosts and junk", registry.remote_arg("octo-user/shipmiracle") == "octo-user/shipmiracle"
      and registry.remote_arg("https://github.com/octo-user/shipmiracle.git") == "octo-user/shipmiracle" and registry.remote_arg("https://gitlab.example/a/b") is None
      and registry.remote_arg("nonsense") is None)
registry.set_field(proj_id, "role", "workspace")
registry.set_field(proj_id, "expected_remote", "octo-user/proj")
registry.set_field(proj_id, "expected_visibility", "private")
e = registry.entry(proj_id)
check("reg e: set role / expected_remote / expected_visibility", e["role"] == "workspace" and e["expected_remote"] == "octo-user/proj" and e["expected_visibility"] == "private", e)
for key, val in (("role", "public-engine"), ("role", "x"), ("expected_visibility", "secret"), ("expected_remote", "nonsense")):
    try:
        registry.set_field(proj_id, key, val); bad = False
    except UsageError:
        bad = True
    check("reg f: set %s=%s is refused" % (key, val), bad)
# back to the file:// remote as the project's expected remote
registry.set_field(proj_id, "expected_remote", url(PROJ))
registry.set_field(proj_id, "role", "project")

# ---- R1 / R2 / R4 with the real hook ---------------------------------------------------------------------------
p = push(P, PUBLIC)
check("R2 a project cannot push to the public remote", p.returncode != 0 and "R2" in p.stderr and refs(PUBLIC) == [], p.stderr)
p = push(P, PROJ)
check("R1 a project pushes to its own remote", p.returncode == 0 and refs(PROJ) == ["refs/heads/main"], p.stderr)
p = push(P, OTHER)
check("R1 a project cannot push to a remote that is not registered", p.returncode != 0 and "R1" in p.stderr and refs(OTHER) == [], p.stderr)
p = push(P, EXTRA)
check("R1 a registered extra remote is allowed", p.returncode == 0 and refs(EXTRA) == ["refs/heads/main"], p.stderr)
p = push(U, OTHER)
check("R4 an unregistered repo may push to an ordinary remote", p.returncode == 0 and refs(OTHER) == ["refs/heads/main"], p.stderr)
p = push(U, PUBLIC)
check("R2/R4 an unregistered repo cannot push to the public remote", p.returncode != 0 and "R2" in p.stderr and refs(PUBLIC) == [], p.stderr)
(P / "g.txt").write_text("2"); git(P, "add", "-A"); git(P, "commit", "-q", "-m", "c2")
p = push(P, PUBLIC, "HEAD:refs/heads/release")
check("R2 any ref name is refused for the public remote", p.returncode != 0 and refs(PUBLIC) == [], p.stderr)

# ---- R3: the export stage --------------------------------------------------------------------------------------
config.set("release.author_email", EMAIL)
config.set("release.author_name", "octo-user")
STATE_REL = TMP / "state" / "v1" / "release"
STAGE = STATE_REL / "stage-20261020000000" / "repo"
make_repo(STAGE, hook=False, env=NOREPLY_ENV)
(STAGE / ".git" / "hooks" / "pre-push").write_text(
    "#!/usr/bin/env bash\nrefs=$(cat)\nprintf '%%s\\n' \"$refs\" | %s push-check \"${1:-}\" \"${2:-}\" || exit 1\n" % str(ROOT / "bin" / "shipm"))
os.chmod(str(STAGE / ".git" / "hooks" / "pre-push"), 0o755)


def stamp(tree, ts=None, **over):
    body = {"v": 1, "result": "PASS", "tree_sha": tree, "ts": int(time.time()) if ts is None else ts, "files": 3, "skipped": [],
            "flags": {"no_denylist": False, "require_denylist": True, "require_gitleaks": False, "denylist_used": True}}
    body.update(over)
    p = STATE_REL / ("check-%s.json" % tree)
    state.atomic_write(p, (json.dumps(body) + "\n").encode())
    return p


def unstamp():
    for f in STATE_REL.glob("check-*.json"):
        f.unlink()


TREE = git(STAGE, "rev-parse", "HEAD^{tree}")
unstamp()
p = push(STAGE, PUBLIC)
check("R3 stage: no stamp, refused", p.returncode != 0 and "R3" in p.stderr and "no release-check stamp" in p.stderr and refs(PUBLIC) == [], p.stderr)
stamp(TREE, ts=int(time.time()) - 2 * 3600)
p = push(STAGE, PUBLIC)
check("R3 stage: stamp older than 1 hour, refused", p.returncode != 0 and "older than 1 hour" in p.stderr and refs(PUBLIC) == [], p.stderr)
stamp(TREE, flags={"no_denylist": True, "require_denylist": False, "require_gitleaks": False, "denylist_used": False})
p = push(STAGE, PUBLIC)
check("R3 stage: a --no-denylist stamp is not accepted", p.returncode != 0 and "not made with the denylist" in p.stderr and refs(PUBLIC) == [], p.stderr)
stamp(TREE, flags={"no_denylist": False, "require_denylist": True, "require_gitleaks": False, "denylist_used": False})
p = push(STAGE, PUBLIC)
check("R3 stage: denylist_used false is not accepted", p.returncode != 0 and refs(PUBLIC) == [], p.stderr)
stamp(TREE, skipped=["identifier"])
p = push(STAGE, PUBLIC)
check("R3 stage: a stamp that skipped the identifier check is not accepted", p.returncode != 0 and refs(PUBLIC) == [], p.stderr)
stamp(TREE, result="FAIL")
p = push(STAGE, PUBLIC)
check("R3 stage: a FAIL stamp is not accepted", p.returncode != 0 and refs(PUBLIC) == [], p.stderr)
stamp(TREE, tree_sha="0" * 40)
p = push(STAGE, PUBLIC)
check("R3 stage: a stamp naming another tree is not accepted", p.returncode != 0 and refs(PUBLIC) == [], p.stderr)
stamp(TREE, ts=int(time.time()) + 4000)
p = push(STAGE, PUBLIC)
check("R3 stage: a stamp dated in the future is not accepted", p.returncode != 0 and refs(PUBLIC) == [], p.stderr)
(STATE_REL / ("check-%s.json" % TREE)).write_text("not json")
p = push(STAGE, PUBLIC)
check("R3 stage: an unreadable stamp is not accepted", p.returncode != 0 and refs(PUBLIC) == [], p.stderr)
stamp(TREE)
THIRD = bare("third.git")
p = push(STAGE, THIRD)
check("R3 stage: it cannot push to another remote even with a stamp", p.returncode != 0 and "R3" in p.stderr and refs(THIRD) == [], p.stderr)
git(STAGE, "branch", "dev")
p = push(STAGE, PUBLIC, "dev")
check("R3 stage: only main and v* tags (a branch is refused)", p.returncode != 0 and "only refs/heads/main" in p.stderr and refs(PUBLIC) == [], p.stderr)
p = push(STAGE, PUBLIC, ":main")
check("R3 stage: deleting a ref is refused", p.returncode != 0 and refs(PUBLIC) == [], p.stderr)
p = push(STAGE, PUBLIC, "main")
check("R3 stage: fresh stamp with the denylist, noreply commit, main: allowed", p.returncode == 0 and refs(PUBLIC) == ["refs/heads/main"], p.stderr)
git(STAGE, "tag", "v0.1.0")
p = push(STAGE, PUBLIC, "v0.1.0")
check("R3 stage: a v* tag is allowed", p.returncode == 0 and "refs/tags/v0.1.0" in refs(PUBLIC), p.stderr)
# a foreign author commit on top: new tree gets its own stamp but the author check refuses
(STAGE / "h.txt").write_text("3"); git(STAGE, "add", "-A"); git(STAGE, "commit", "-q", "-m", "foreign", env=OTHER_ENV)
stamp(git(STAGE, "rev-parse", "HEAD^{tree}"))
p = push(STAGE, PUBLIC, "main")
check("R3 stage: a commit with a non-noreply author is refused", p.returncode != 0 and "noreply" in p.stderr, p.stderr)
git(STAGE, "reset", "-q", "--hard", "HEAD~1")
# a moved stage: not under <state>/v1/release is just a project
MOVED = make_repo(TMP / "elsewhere" / "repo", hook=True, env=NOREPLY_ENV)
p = push(MOVED, PUBLIC)
check("R2 a repo named repo outside the stage folder is not the stage", p.returncode != 0 and "R2" in p.stderr, p.stderr)

# ---- registry gaps in the stage ---------------------------------------------------------------------------------
os.unlink(str(registry.path()))
stamp(TREE)
p = push(STAGE, PUBLIC, "main")
check("R3 stage: no public-engine entry in the registry: refused", p.returncode != 0 and "exactly one" in p.stderr, p.stderr)
registry.add_remote_only("public-engine", url(PUBLIC), "private")
p = push(STAGE, PUBLIC, "main")
check("R3 stage: expected_visibility=private is no longer refused for its visibility (export checks the real one)", "expected_visibility" not in p.stderr, p.stderr)
registry.forget(registry.public_engines()[0]["id"])
registry.add_remote_only("public-engine", url(PUBLIC), "public")
registry.write_missing({"v": 1, "projects": {proj_id: registry.entry(proj_id) or {"name": "proj", "remote": url(PROJ), "extra_remotes": []}}})

# ---- the hook itself -------------------------------------------------------------------------------------------
N = make_repo(TMP / "dev" / "nohook-shipmiracle")
env = {"PATH": BASE_PATH, "HOME": str(TMP / "gh-home")}
os.makedirs(env["HOME"], exist_ok=True)
e2 = dict(os.environ); e2.pop("SHIPMIRACLE_ENGINE"); e2.update(env)
p = subprocess.run(["git", "-C", str(N), "push", url(OTHER), "main:refs/heads/nh"], env=e2, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
check("hook: Shipmiracle not found -> warns and allows", p.returncode == 0 and "release push guard skipped" in p.stderr and "refs/heads/nh" in refs(OTHER), p.stderr)
old = TMP / "oldengine"; (old / "bin").mkdir(parents=True)
(old / "bin" / "shipm").write_text("#!/bin/sh\nexit 2\n"); os.chmod(str(old / "bin" / "shipm"), 0o755)
e3 = dict(os.environ); e3["SHIPMIRACLE_ENGINE"] = str(old)
p = subprocess.run(["git", "-C", str(N), "push", url(OTHER), "main:refs/heads/old"], env=e3, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
check("hook: an Shipmiracle without push-check (exit 2) -> warns and allows", p.returncode == 0 and "exited 2" in p.stderr, p.stderr)
(old / "bin" / "shipm").write_text("#!/bin/sh\nexit 1\n")
p = subprocess.run(["git", "-C", str(N), "push", url(OTHER), "main:refs/heads/old2"], env=e3, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
check("hook: exit 1 of push-check refuses", p.returncode != 0 and "refs/heads/old2" not in refs(OTHER), p.stderr)
txt = HOOK
check("hook: gitleaks block intact, release block after its END marker, one final exit 0",
      txt.index("#--GITLEAKS-PREPUSH-END--") < txt.index("#--RELEASE-PREPUSH-BEGIN--") < txt.index("#--RELEASE-PREPUSH-END--") and txt.rstrip().endswith("exit 0")
      and txt.count("refs=$(cat)") == 1 and (not (ROOT / ".githooks/pre-push").exists() or (ROOT / ".githooks/pre-push").read_text() == txt))

# ---- in-process: stdin, errors, no writes -----------------------------------------------------------------------
before = sorted(str(p) for p in TMP.rglob("*") if p.is_file() and ".git/" not in str(p))
r = pushcheck.check("origin", url(PUBLIC), "", cwd=str(P))
check("check(): a project pushing to the public remote with no ref lines is still R2", r.refused and r.rule == "R2")
r = pushcheck.check("origin", "", "", cwd=str(TMP))
check("check(): outside a git work tree it allows", not r.refused)
after = sorted(str(p) for p in TMP.rglob("*") if p.is_file() and ".git/" not in str(p))
check("check() is read-only (no file created or removed)", before == after, set(before) ^ set(after))
pathlib.Path(str(registry.path())).write_text("{not json")
r = pushcheck.check("origin", url(OTHER), "", cwd=str(P))
check("a damaged registry: a project push is allowed with a warning", not r.refused and any("registry unreadable" in l for l in r.lines), r.lines)
r = pushcheck.check("origin", url(PUBLIC), "refs/heads/main %s refs/heads/main %s\n" % (git(STAGE, "rev-parse", "HEAD"), "0" * 40), cwd=str(STAGE))
check("a damaged registry: the export stage is refused (fail closed)", r.refused and r.rule == "R3", r.lines)
rc = subprocess.run([sys.executable, str(ROOT / "bin" / "shipm"), "push-check", "origin", url(OTHER)], cwd=str(U), stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=dict(os.environ)).returncode
check("CLI: a damaged registry for an unregistered repo exits 0", rc == 0)

# ---- zero network -----------------------------------------------------------------------------------------------
check("the fake gh was never called", not GHLOG.exists(), GHLOG.read_text() if GHLOG.exists() else "")
src = (ROOT / "shipmiracle" / "release" / "pushcheck.py").read_text()
check("pushcheck.py has no network code and no gh", all(w not in src for w in ("socket", "urllib", "http.client", '"gh"', "ls-remote", "fetch")))

shutil.rmtree(str(TMP), ignore_errors=True)
print("ALL PASS" if not fails else "%d FAILED" % fails)
sys.exit(1 if fails else 0)
