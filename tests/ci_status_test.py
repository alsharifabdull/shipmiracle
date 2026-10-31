"""bin/ci-status against a fake gh and fake project folders. Run: python3 tests/ci_status_test.py"""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import shipmiracle_isolation; shipmiracle_isolation.apply_to_environ()   # test isolation: fresh HOME/SHIPMIRACLE_HOME/CONFIG/STATE unless already temp
import json, os, pathlib, subprocess, sys, tempfile
ws = pathlib.Path(__file__).resolve().parent.parent
tmp = pathlib.Path(tempfile.mkdtemp())
dev, state, fakes = tmp / "dev", tmp / "state", tmp / "fakes"
for d in (dev, state, fakes):
    d.mkdir()
fails = []
def check(name, cond, info=""):
    print(("PASS " if cond else "FAIL ") + name, info if not cond else "")
    if not cond: fails.append(name)

def project(name, workflows=True, remote=True):
    p = dev / name; p.mkdir()
    subprocess.run(["git", "-C", str(p), "init", "-q"], check=True)
    if remote: subprocess.run(["git", "-C", str(p), "remote", "add", "origin", f"https://github.com/me/{name}.git"], check=True)
    if workflows: (p / ".github/workflows").mkdir(parents=True)

# fake gh: prints fakes/<repo name>.json, or fails when fakes/<repo name>.fail exists; records its arguments
gh = tmp / "gh"
gh.write_text(f"""#!/bin/sh
echo "$@" >> {tmp}/gh.log
repo=$(echo "$@" | sed -n 's/.*--repo me\\/\\([^ ]*\\).*/\\1/p')
[ -f {fakes}/$repo.fail ] && {{ echo "token ghp_SECRET" >&2; exit 1; }}
cat {fakes}/$repo.json
""")
gh.chmod(0o755)
env = dict(os.environ, SHIPMIRACLE_GH=str(gh), SHIPMIRACLE_STATE=str(state), SHIPMIRACLE_DEV=str(dev))
def run(): return subprocess.run([sys.executable, str(ws / "bin/ci-status")], env=env, capture_output=True, text=True)
def ci(): return json.loads((state / "ci.json").read_text())
def fake(name, **kw):
    (fakes / f"{name}.json").write_text(json.dumps([{"conclusion": "", "status": "completed", "displayTitle": "t", "url": f"https://github.com/me/{name}/actions/runs/1", "createdAt": "2026-10-19T01:00:00Z", **kw}]))

for n in ("good", "bad", "going", "flaky"): project(n); fake(n)
project("noflow", workflows=False); project("noremote", remote=False)
fake("good", conclusion="success"); fake("bad", conclusion="failure", displayTitle="Broken build"); fake("going", status="in_progress")
fake("flaky", conclusion="success")
r = run(); d = ci()
check("exits 0", r.returncode == 0, r.stderr)
check("only projects with a remote and workflows", sorted(d) == ["bad", "flaky", "going", "good"], str(sorted(d)))
check("success", d["good"]["conclusion"] == "success" and d["good"]["status"] == "completed" and "error" not in d["good"])
check("failure keeps title and url", d["bad"]["conclusion"] == "failure" and d["bad"]["title"] == "Broken build" and d["bad"]["url"].startswith("https://github.com/me/bad"))
check("in progress has no conclusion", d["going"]["status"] == "in_progress" and d["going"]["conclusion"] == "")
check("asks gh for main, one run, the right fields", "--repo me/good --branch main --limit 1 --json conclusion,status,displayTitle,url,createdAt" in (tmp / "gh.log").read_text())
(fakes / "flaky.fail").write_text("")
r = run(); d = ci()
check("gh error keeps the old entry and adds error", d["flaky"]["conclusion"] == "success" and "error" in d["flaky"] and d["good"]["conclusion"] == "success", str(d["flaky"]))
check("gh output (tokens) is never stored or printed", "ghp_SECRET" not in (state / "ci.json").read_text() + r.stdout + r.stderr)
(fakes / "flaky.fail").unlink()
run(); check("recovers on the next run", "error" not in ci()["flaky"])
(fakes / "bad.json").write_text("[]")
run(); check("a repo with no runs is not a failure", ci()["bad"]["conclusion"] == "" and ci()["bad"]["status"] == "none")
# gh missing from PATH but present in an extra dir (SHIPMIRACLE_GH_PATHS); no SHIPMIRACLE_GH override
extra = tmp / "extra"; extra.mkdir(); (extra / "gh").write_text(gh.read_text()); (extra / "gh").chmod(0o755)
bare = dict(os.environ, SHIPMIRACLE_STATE=str(state), SHIPMIRACLE_DEV=str(dev), PATH="/usr/bin:/bin")
bare.pop("SHIPMIRACLE_GH", None)
def run_bare(paths):
    return subprocess.run([sys.executable, str(ws / "bin/ci-status")], env=dict(bare, SHIPMIRACLE_GH_PATHS=paths), capture_output=True, text=True)
(fakes / "bad.json").write_text(json.dumps([{"conclusion": "failure", "status": "completed", "displayTitle": "x", "url": "u", "createdAt": "2026-10-19T02:00:00Z"}]))
r = run_bare(str(extra)); d = ci()
check("finds gh in the extra dirs", r.returncode == 0 and d["bad"]["conclusion"] == "failure" and "error" not in d["bad"] and "stale" not in d["bad"], r.stderr + str(d["bad"]))
check("success records checked_at", d["bad"].get("checked_at") and d["bad"].get("last_ok") == d["bad"]["checked_at"])
before = d["bad"]["checked_at"]
import time; time.sleep(1.1)
r = run_bare(str(tmp / "nowhere")); d = ci()
check("gh absent: clear error", d["bad"].get("error") == "gh not found: install it or add it to PATH", str(d["bad"]))
check("gh absent: checked_at updates, old result kept, not stale yet", d["bad"]["checked_at"] > before and d["bad"]["conclusion"] == "failure" and d["bad"]["stale"] is False, str(d["bad"]))
# last good check 40 minutes ago -> stale
import datetime
old = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=40)).isoformat(timespec="seconds")
d["bad"]["last_ok"] = old; (state / "ci.json").write_text(json.dumps(d))
run_bare(str(tmp / "nowhere")); d = ci()
check("error and last good check over 30 min old -> stale true", d["bad"]["stale"] is True and d["bad"]["last_ok"] == old, str(d["bad"]))
d["bad"].pop("last_ok"); (state / "ci.json").write_text(json.dumps(d))
run_bare(str(tmp / "nowhere")); check("error with unknown last good check -> stale true", ci()["bad"]["stale"] is True)
run_bare(str(extra)); d = ci()
check("recovery clears error and stale", "error" not in d["bad"] and "stale" not in d["bad"])
check("no tmp file left behind", not (state / "ci.json.tmp").exists())

# ---- P2/T5: discovery through shipmiracle.projects, v1 mirror, guarded import ----
import shutil
cfg = tmp / "cfg"; cfg.mkdir()
env.update(SHIPMIRACLE_TEST="1", SHIPMIRACLE_CONFIG=str(cfg), SHIPMIRACLE_HOME=str(tmp / "home"))
(dev / "nogit").mkdir(); (dev / "nogit/.github/workflows").mkdir(parents=True)          # workflows but no git: never listed
project(".hidden")                                                                      # dot-named: skipped
run(); d = ci()
check("discovery unchanged on fixtures: non-git and dot-named folders with workflows are still skipped", sorted(d) == ["bad", "flaky", "going", "good"], str(sorted(d)))
v1 = state / "v1" / "ci.json"
env_v1 = json.loads(v1.read_text()) if v1.exists() else {}
check("mirror: v1/ci.json is an envelope by writer ci-status and its data equals the legacy file", env_v1.get("writer") == "ci-status" and env_v1.get("data") == d and env_v1.get("v") == 1, str(env_v1)[:200])
check("mirror: the v1 file is 0600", v1.exists() and (v1.stat().st_mode & 0o777) == 0o600)
shutil.rmtree(state / "v1"); (cfg / "config.json").write_text(json.dumps({"switches.state.v1": False}))
run(); check("switch off: legacy ci.json still written, no v1 file", ci() and not (state / "v1" / "ci.json").exists())
(cfg / "config.json").unlink()
shutil.rmtree(state / "v1", ignore_errors=True); (state / "v1" / "ci.json").mkdir(parents=True)      # a folder where the v1 file must go: the copy fails
r = run(); evl = (state / "v1/events.jsonl").read_text().splitlines() if (state / "v1/events.jsonl").exists() else []
check("mirror failure: exit 0, the legacy ci.json is complete, exactly one state.v1_write_failed event", r.returncode == 0 and sorted(ci()) == ["bad", "flaky", "going", "good"] and sum('"state.v1_write_failed"' in l for l in evl) == 1, r.stderr + str(evl))
shutil.rmtree(state / "v1")
# guarded import: a copy of bin/ without (or with a broken) neighbour shipmiracle/ package must still work
def broken_pkg(c):
    (c / "shipmiracle").mkdir(); (c / "shipmiracle/__init__.py").write_text("def (:\n")
def no_mirror_pkg(c):
    shutil.copytree(ws / "shipmiracle", c / "shipmiracle", ignore=shutil.ignore_patterns("__pycache__"))
    st = (c / "shipmiracle/state.py").read_text(); (c / "shipmiracle/state.py").write_text(st.replace("def mirror(", "def _renamed_mirror("))
for label, mk in (("missing shipmiracle/", lambda c: None), ("shipmiracle/ with a SyntaxError", broken_pkg), ("shipmiracle/ whose state lacks mirror", no_mirror_pkg)):
    c = tmp / ("copy_" + str(abs(hash(label)))); (c / "bin").mkdir(parents=True); shutil.copy(ws / "bin/ci-status", c / "bin/ci-status"); mk(c)
    st2 = tmp / ("st_" + str(abs(hash(label)))); st2.mkdir()
    r = subprocess.run([sys.executable, str(c / "bin/ci-status")], env=dict(env, SHIPMIRACLE_STATE=str(st2)), capture_output=True, text=True)
    out = json.loads((st2 / "ci.json").read_text()) if (st2 / "ci.json").exists() else None
    check("guarded import (%s): still exits 0 and writes ci.json with the old discovery, no v1 copy" % label, r.returncode == 0 and out is not None and sorted(out) == ["bad", "flaky", "going", "good"] and not (st2 / "v1").exists(), r.stderr[-300:])
print("\nFAILED: %d" % len(fails) if fails else "\nALL PASS"); sys.exit(1 if fails else 0)
