#!/usr/bin/env python3
"""shipmiracle/registry.py: propose never writes, write_missing adds only missing ids, 0600, remote normalisation, extra remotes,
exceptions seed, timeout on a hanging git (seam: registry.GIT / registry.TIMEOUT), malformed file. Run: python3 tests/shipmiracle_registry_test.py"""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import shipmiracle_isolation; shipmiracle_isolation.apply_to_environ()   # test isolation: fresh HOME/SHIPMIRACLE_HOME/CONFIG/STATE unless already temp
import json, os, pathlib, shutil, stat, subprocess, sys, tempfile, time
os.environ.pop("CLAUDECODE", None)       # the owner check only runs in a fully temp sandbox or outside a chat (H1)

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["SHIPMIRACLE_TEST"] = "1"
from shipmiracle import SchemaError, UsageError, SafetyError, paths, projects, registry  # noqa: E402

def raises_(exc, fn, *a):
    try:
        fn(*a)
    except exc:
        return True
    return False
fails = 0
def check(name, ok, info=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(info)))
    fails += 0 if ok else 1

TMP = pathlib.Path(tempfile.mkdtemp(prefix="shipmiracle-reg-"))
os.environ["SHIPMIRACLE_CONFIG"] = str(TMP / "cfg")
os.environ["SHIPMIRACLE_STATE"] = str(TMP / "state")      # owner-only writers run unguarded only when config AND state are temp folders
dev = TMP / "dev"
def mk(name, origin=None, extra=None):
    d = dev / name
    subprocess.run(["git", "init", "-q", str(d)], check=True)
    if origin: subprocess.run(["git", "-C", str(d), "remote", "add", "origin", origin], check=True)
    for k, v in (extra or {}).items(): subprocess.run(["git", "-C", str(d), "remote", "add", k, v], check=True)
mk("sample-app", "git@github.com:octo-user/sample-app.git")
mk("sandbox", "https://tok3n:x@github.com/octo-user/sandbox", {"upstream": "ssh://git@github.com:22/other/sandbox.git", "bb": "https://bitbucket.org/o/n.git"})
mk("norem"); mk("ideas", "/local/path/only")
(dev / "AI-Workspace" / ".git").mkdir(parents=True)

# normalisation
N = registry.normalise_remote
cases = {
    "https://github.com/o/n": "o/n", "https://github.com/o/n.git": "o/n", "https://github.com/o/n/": "o/n",
    "git@github.com:o/n.git": "o/n", "git@github.com:o/n": "o/n", "ssh://git@github.com/o/n.git": "o/n",
    "ssh://git@github.com:22/o/n.git": "o/n", "https://user:tok@github.com/o/n.git": "o/n",
    "https://gitlab.com/g/s/o/n.git": "gitlab.com/g/s/o/n", "git@gitlab.com:g/s/o/n.git": "gitlab.com/g/s/o/n", "  https://github.com/o/n.git \n": "o/n",
    "/local/path": None, "./rel": None, "": None, "junk": None, "https://github.com/onlyone": None, None: None,
    "https://github.com/o/n m": None, "C:\\x": None,
}
cases.update({
    "https://user:p@ss@github.com/o/r.git": "o/r", "https://user:p@ss@gitlab.com/o/r.git": "gitlab.com/o/r",
    "https://a@b@github.com/o/r": "o/r", "https://github.com@evil.com/o/r": "evil.com/o/r",
    "https://u:p@ss@/o/r": None, "https://evil.com@/o/r": None, "a@b@github.com:o/r.git": None, "https://@github.com/o/r": "o/r",
    "https://github.com/o/../r": None, "https://github.com:8080/o/r": "o/r",
})
for u, want in cases.items():
    check("normalise %r" % (u,), N(u) == want, N(u))

# propose
before = registry.path().exists()
for u in ("https://user:p@ss@github.com/o/r.git", "https://user:p@ss@gitlab.com/o/r.git", "https://a:b@c@d@github.com/o/r"):
    out = N(u)
    check("a password with '@' is never stored: %r" % u, out is None or ("ss@" not in out and "@" not in out), out)
prop = registry.propose(dev=dev)
check("propose does not write", not before and not registry.path().exists() and not (TMP / "cfg").exists())
by = {e["name"]: e for e in prop["projects"].values()}
check("propose: origin normalised, nothing raw stored", by["sample-app"]["remote"] == "octo-user/sample-app" and "tok3n" not in json.dumps(prop))
check("propose: credentials stripped", by["sandbox"]["remote"] == "octo-user/sandbox")
check("propose: extra remotes listed", by["sandbox"]["extra_remotes"] == [{"name": "bb", "remote": "bitbucket.org/o/n"}, {"name": "upstream", "remote": "other/sandbox"}], by["sandbox"]["extra_remotes"])
check("propose: no remote -> null; local path -> null", by["norem"]["remote"] is None and by["ideas"]["remote"] is None)
check("propose: visibility/type are null", all(e["visibility"] is None and e["type"] is None for e in by.values()))
check("propose: no project is protected or special by built-in data", all(not e["protected"] and e["special"] is None and e["exceptions"] == [] and e["standard"] == "auto" for e in by.values()))
check("propose: keyed by project id", set(prop["projects"]) == {p.id for p in projects.list_projects(dev)})
ids = {e["name"]: i for i, e in prop["projects"].items()}

# apply_seed: owner data -> registry entries (fill defaults only, idempotent, never overwrites an owner change)
SEED = {"sample-app": {"protected": True, "standard": "manual", "exceptions": ["a", "b", "c"]}, "ideas": {"special": "panel-only"}, "AI-Workspace": {"protected": True}, "absent-project": {"protected": True}}
plan = registry.seed_plan(SEED, dev=dev)
check("seed_plan: lists existing projects only, read-only", sorted(x["name"] for x in plan) == ["AI-Workspace", "ideas", "sample-app"] and all(x["new"] for x in plan) and not registry.path().exists(), plan)
check("seed_plan: invalid value raises UsageError", raises_(UsageError, registry.seed_plan, {"x": {"protected": "yes"}}) and raises_(UsageError, registry.seed_plan, {"x": {"standard": "bad"}}) and raises_(UsageError, registry.seed_plan, ["x"]))
changed = registry.apply_seed(SEED, dev=dev)
reg_ = registry.load()["projects"]
e_ = {v["name"]: v for v in reg_.values()}
check("apply_seed: entries added with the seeded fields", len(changed) == 3 and e_["sample-app"]["protected"] and e_["sample-app"]["standard"] == "manual" and len(e_["sample-app"]["exceptions"]) == 3
      and e_["ideas"]["special"] == "panel-only" and e_["AI-Workspace"]["protected"] and "absent-project" not in e_ and "sandbox" not in e_, e_.keys())
check("apply_seed: idempotent (second run changes nothing)", registry.apply_seed(SEED, dev=dev) == [] and registry.seed_plan(SEED, dev=dev) == [])
sid = [i for i, v in reg_.items() if v["name"] == "sample-app"][0]
registry._mutate("t", lambda cur: (None, cur["projects"][sid].__setitem__("exceptions", ["mine"]) is None))
registry.apply_seed({"sample-app": {"exceptions": ["other"]}}, dev=dev)
check("apply_seed: a field the owner changed is not overwritten", registry.entry(sid)["exceptions"] == ["mine"])
check("apply_seed never lowers protection (protected False in a seed does not clear True)", registry.apply_seed({"sample-app": {"protected": False}}, dev=dev) == [] and registry.entry(sid)["protected"] is True)
shutil.rmtree(TMP / "cfg", ignore_errors=True)

# write_missing
check("load of an absent file is empty", registry.load() == {"v": 1, "projects": {}} and registry.entry("abc") is None)
added = registry.write_missing(prop)
check("write_missing adds all on first run", sorted(added) == sorted(prop["projects"]), added)
mode = stat.S_IMODE(os.stat(registry.path()).st_mode); dmode = stat.S_IMODE(os.stat(TMP / "cfg").st_mode)
check("registry.json is 0600 in a 0700 folder", mode == 0o600 and dmode == 0o700, (oct(mode), oct(dmode)))
d = json.loads(registry.path().read_text()); d["projects"][ids["sandbox"]]["visibility"] = "private"; d["projects"][ids["sandbox"]]["type"] = "app"
registry.path().write_text(json.dumps(d))
os.chmod(registry.path(), 0o600)
mk("fresh", "https://github.com/o/fresh.git")
prop2 = registry.propose(dev=dev)
prop2["projects"][ids["sandbox"]]["visibility"] = "public"          # a re-proposal must not overwrite the owner's values
added = registry.write_missing(prop2)
check("write_missing adds only the missing id", [prop2["projects"][i]["name"] for i in added] == ["fresh"], added)
e = registry.entry(ids["sandbox"])
check("existing entries are never overwritten", e["visibility"] == "private" and e["type"] == "app")
check("entry(id) returns a copy", registry.entry(added[0])["remote"] == "o/fresh" and registry.entry("zzz") is None)
check("second write_missing is a no-op", registry.write_missing(prop2) == [])
check("still 0600 after rewrite", stat.S_IMODE(os.stat(registry.path()).st_mode) == 0o600)
check("no temp files left", [p.name for p in (TMP / "cfg").iterdir() if p.name.endswith(".tmp")] == [])
try:
    registry.write_missing({"x": 1}); raised = False
except UsageError:
    raised = True
check("write_missing rejects a bad proposal", raised)

# malformed file
for bad in (b"{not json", b"[]", b'{"v":2,"projects":{}}', b'{"v":1,"projects":[]}', b'{"v":1,"projects":{"a":5}}'):
    registry.path().write_bytes(bad); os.chmod(registry.path(), 0o600)
    try:
        registry.load(); r1 = False
    except SchemaError:
        r1 = True
    try:
        registry.write_missing(prop); r2 = False
    except SchemaError:
        r2 = True
    check("malformed registry %r: load and write_missing raise SchemaError, file untouched" % bad[:14], r1 and r2 and registry.path().read_bytes() == bad)
os.remove(registry.path()); os.symlink("/etc/hosts", registry.path())
try:
    registry.load(); sym = False
except SafetyError:
    sym = True
check("a symlinked registry.json is refused", sym)
os.remove(registry.path())

# isolation: the real config folder is refused under SHIPMIRACLE_TEST
os.environ["SHIPMIRACLE_CONFIG"] = str(paths.real_home() / ".config" / "shipmiracle")
try:
    registry.write_missing(prop); iso = False
except SafetyError:
    iso = True
check("write_missing refuses the real config folder under SHIPMIRACLE_TEST", iso)
os.environ["SHIPMIRACLE_CONFIG"] = str(TMP / "cfg")

# hanging git: real subprocess timeout through the seams (a hanging executable, short timeout)
hang = TMP / "hang.sh"; hang.write_text("#!/bin/sh\nexec sleep 30\n"); os.chmod(hang, 0o755)
registry.GIT, registry.TIMEOUT = str(hang), 0.5
t = time.time()
r = registry.propose(dev=dev)
el = time.time() - t
check("hanging git: each project gives remote null after the timeout, run bounded", all(e["remote"] is None for e in r["projects"].values()) and el < 0.5 * 6 + 3, el)
registry.GIT = str(TMP / "does-not-exist")
check("missing git executable -> remote null", all(e["remote"] is None for e in registry.propose(dev=dev)["projects"].values()))
registry.GIT, registry.TIMEOUT = "git", 5.0
check("production defaults: git on PATH, timeout 5 s", registry.GIT == "git" and registry.TIMEOUT == 5.0)
seen_argv = []
real_run = registry.subprocess.run
def spy(argv, **kw):
    seen_argv.append((argv, kw.get("env"))); return real_run(argv, **kw)
registry.subprocess.run = spy
os.environ.update(GIT_DIR="/nonexistent", GIT_WORK_TREE="/nonexistent", GIT_CONFIG_GLOBAL="/nonexistent")
try:
    r1 = registry.propose(dev=dev)
finally:
    registry.subprocess.run = real_run
    for k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_CONFIG_GLOBAL"):
        os.environ.pop(k, None)
check("registry git call uses the hardened prefix and a clean environment", seen_argv and all(a[:5] == ["git", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null"]
      and not [k for k in (e or {}) if k.startswith("GIT_")] for a, e in seen_argv), seen_argv[:1])
check("a GIT_DIR in the caller's environment does not change the proposal", r1 == registry.propose(dev=dev))
src = (ROOT / "shipmiracle" / "registry.py").read_text()
check("no shell use in registry.py", "shell=True" not in src and "os.system" not in src)

shutil.rmtree(TMP, ignore_errors=True)
print("\nFAILED: %d" % fails if fails else "\nALL PASS"); sys.exit(1 if fails else 0)
