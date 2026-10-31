#!/usr/bin/env python3
"""shipm brief / shipm playbook (parser, show, exit codes) and the registry's `playbook` snapshot field. Real subprocesses with SHIPMIRACLE_TEST=1 and
temp git projects. Run: python3 tests/shipmiracle_playbook_cli_test.py"""
import json, os, pathlib, subprocess, sys, tempfile, time
os.environ.pop("CLAUDECODE", None)       # the owner check only runs in a fully temp sandbox or outside a chat (H1)

ROOT = pathlib.Path(__file__).resolve().parent.parent
SHIPM = str(ROOT / "bin" / "shipm")
TMP = pathlib.Path(tempfile.mkdtemp(prefix="shipmiracle-pbcli-")).resolve()
HOME, DEV, STATE, CONF, WS = (TMP / n for n in ("home", "dev", "state", "config", "ws"))
ENV = dict(os.environ, SHIPMIRACLE_TEST="1", SHIPMIRACLE_HOME=str(HOME), SHIPMIRACLE_DEV=str(DEV), SHIPMIRACLE_STATE=str(STATE), SHIPMIRACLE_CONFIG=str(CONF), SHIPMIRACLE_WS=str(WS), HOME=str(HOME))
for k in ("SHIPMIRACLE_DEBUG", "CLAUDECODE", "SHIPMIRACLE_ENFORCE_OWNER"):
    ENV.pop(k, None)
REAL = pathlib.Path(os.path.expanduser("~"))
CANARY = [REAL / ".config" / "shipmiracle" / "registry.json", REAL / ".config" / "shipmiracle" / "config.json", REAL / ".claude" / "settings.json"]
before = [(p.stat().st_mtime_ns if p.exists() else None) for p in CANARY]
os.environ.update({k: v for k, v in ENV.items() if k.startswith("SHIPMIRACLE_")})
sys.path.insert(0, str(ROOT))
from shipmiracle import UsageError, registry, projects  # noqa: E402
from shipmiracle.playbook import config as pbc  # noqa: E402

fails = 0
def check(name, ok, info=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(info)[:600]))
    fails += 0 if ok else 1

def shipm(*args, env=None, cwd=None):
    r = subprocess.run([sys.executable, SHIPM] + list(args), env=env or ENV, capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL, cwd=cwd)
    return r.returncode, r.stdout, r.stderr

HOME.mkdir(parents=True)
(HOME / ".gitconfig").write_text("[user]\n name = t\n email = t@example.com\n[init]\n defaultBranch = main\n[commit]\n gpgsign = false\n")
(WS / "config").mkdir(parents=True)
(WS / "config" / "flow.json").write_text('{\n  "default": "strict",\n  "projects": {}\n}\n')
for n in ("alpha", "app1"):
    d = DEV / n
    d.mkdir(parents=True)
    subprocess.run(["git", "-C", str(d), "init", "-q"], env=ENV, check=True)
    (d / "a.txt").write_text("1\n")
    subprocess.run(["git", "-C", str(d), "add", "-A"], env=ENV, check=True)
    subprocess.run(["git", "-C", str(d), "commit", "-q", "-m", "init"], env=ENV, check=True)
A = str(DEV / "alpha")
STATE.mkdir(parents=True, exist_ok=True)
(STATE / "health.json").write_text(json.dumps({"ts": time.time(), "chats": {"alpha": {"chats": 0}, "app1": {"chats": 0}}}))

# ---- help and usage ----
for cmd in ("playbook", "cr", "brief"):
    code, out, err = shipm(cmd, "--help")
    check("%s --help: exit 0 with usage" % cmd, code == 0 and "usage: shipm %s" % cmd in out, (code, out[:100], err))
code, out, err = shipm("--help")
check("top-level help lists playbook, cr and brief", all(w in out for w in ("playbook", "cr", "brief")), out[:300])
code, out, err = shipm("playbook")
check("playbook without an action: exit 2", code == 2, (code, err))
code, out, err = shipm("playbook", "set", "type")
check("playbook set with one argument: exit 2", code == 2, (code, err))
code, out, err = shipm("playbook", "frobnicate")
check("playbook unknown action: exit 2", code == 2 and err.startswith("shipm: "), (code, err))
code, out, err = shipm("playbook", "show", "--project", str(TMP / "none"))
check("show for a folder that is not there: exit 3", code == 3, (code, err))

# ---- brief: nothing without work.json ----
code, out, err = shipm("brief", "--project", A)
check("brief without .shipmiracle/work.json: exit 0, no output", code == 0 and out == "" and err == "", (code, out, err))
code, out, err = shipm("brief", cwd=str(TMP))
check("brief outside any project: exit 0, no output", code == 0 and out == "", (code, out, err))
code, out, err = shipm("brief", "--project", str(TMP / "nowhere"))
check("brief for a missing folder: exit 0, no output", code == 0 and out == "", (code, out, err))
check("set type software (creates the playbook)", shipm("playbook", "set", "type", "software", "--project", "alpha")[0] == 0)
code, out, err = shipm("brief", "--project", A)
check("brief with a playbook but no work.json: still nothing", code == 0 and out == "", (code, out))
wj = pathlib.Path(A) / ".shipmiracle" / "work.json"
wj.write_text('{"v":1,"active":null,"queue":[],"crs":[]}\n')
code, out, err = shipm("brief", "--project", A)
lines = out.splitlines()
check("brief with an empty work.json: the six lines", code == 0 and len(lines) == 6 and lines[0].startswith("Playbook: software · strict · guided (alpha)")
      and lines[1] == "Active: none" and lines[2] == "Waiting on owner: none" and lines[3] == "Queue: none" and lines[4] == "Last verdict: none" and lines[5].startswith("Rules:"), out)
code, out, err = shipm("brief", cwd=A)
check("brief in the project folder (no --project): same text", code == 0 and out.splitlines()[0].startswith("Playbook: software"), out)
sub = pathlib.Path(A) / "deep" / "er"
sub.mkdir(parents=True)
code, out, err = shipm("brief", cwd=str(sub))
check("brief from a sub folder resolves the project", code == 0 and out.startswith("Playbook: software"), (code, out))

# ---- brief with CRs: size and unicode ----
code, out, err = shipm("cr", "open", "إصلاح اتجاه RTL في تسجيل الدخول", "--lane", "full", "--project", A)
for i in range(12):
    shipm("cr", "open", "queued request number %d with a fairly long descriptive title to push the size %s" % (i, "ا" * 60), "--project", A)
code, out, err = shipm("brief", "--project", A)
check("brief with 1 active + 12 queued long unicode titles: <= 1 KB", code == 0 and 0 < len(out.encode("utf-8")) <= 1024, len(out.encode("utf-8")))
check("brief names the active CR and its stage", 'Active: CR-001 "' in out and "full lane" in out and "at Scope" in out, out)
check("brief valid UTF-8 text with no control characters", all(ord(c) >= 32 or c == "\n" for c in out), repr(out[:80]))
code, out, err = shipm("brief", "--project", A, env=dict(ENV, CLAUDECODE="1", SHIPMIRACLE_ENFORCE_OWNER="1"))
check("brief is available from a chat (anyone)", code == 0 and out.startswith("Playbook:"), (code, err))

# ---- show ----
code, out, err = shipm("playbook", "show", "--project", "alpha")
check("show: text with trust and level", code == 0 and "Trust: trusted" in out and "Level (config/flow.json): strict" in out, out)
code, out, err = shipm("playbook", "show", "--project", "app1", "--json")
j = json.loads(out)
check("show --json for a project without playbook: config null, trust none", code == 0 and j["v"] == 1 and j["config"] is None and j["trust"] == "none" and j["file"] is False, j)
code, out, err = shipm("playbook", "show", "--project", "alpha", "--json")
j = json.loads(out)
check("show --json: field set", set(j) == {"v", "project", "trust", "reason", "config", "file", "sha256", "flow_level"}, sorted(j))

# ---- set: more keys ----
code, out, err = shipm("playbook", "set", "report.lang", "ar", "--project", "alpha")
check("set report.lang ar", code == 0 and json.loads((pathlib.Path(A) / ".shipmiracle" / "playbook.json").read_text())["report"]["lang"] == "ar", (code, err))
code, out, err = shipm("playbook", "set", "lang", "xx", "--project", "alpha")
check("set lang xx: exit 2", code == 2, (code, err))
code, out, err = shipm("playbook", "set", "test_cmd", "nope/missing.sh", "--project", "alpha")
check("set test_cmd to a file that is not there: exit 2", code == 2, (code, err))
(pathlib.Path(A) / "t.sh").write_text("#!/bin/sh\n")
code, out, err = shipm("playbook", "set", "test_cmd", "t.sh", "--project", "alpha")
check("set test_cmd to an existing file", code == 0, (code, err))
code, out, err = shipm("playbook", "set", "test_cmd", "-", "--project", "alpha")
check("set test_cmd - removes the override", code == 0 and "test_cmd" not in json.loads((pathlib.Path(A) / ".shipmiracle" / "playbook.json").read_text())["overrides"], (code, err))
code, out, err = shipm("playbook", "set", "fast_lane", '{"max_files": 2, "max_lines": 20}', "--project", "alpha")
check("set fast_lane JSON", code == 0 and json.loads((pathlib.Path(A) / ".shipmiracle" / "playbook.json").read_text())["overrides"]["fast_lane"] == {"max_files": 2, "max_lines": 20}, (code, err))
size = (pathlib.Path(A) / ".shipmiracle" / "playbook.json").stat().st_size
check("playbook.json stays under 4 KB and is mode 0644", size < 4096 and oct((pathlib.Path(A) / ".shipmiracle" / "playbook.json").stat().st_mode & 0o777) == "0o644", size)
# a symlinked .shipmiracle is refused
import shutil
shutil.rmtree(str(DEV / "app1" / ".shipmiracle"), ignore_errors=True)
os.symlink(str(TMP), str(DEV / "app1" / ".shipmiracle"))
code, out, err = shipm("playbook", "set", "type", "software", "--project", "app1")
check("a symlinked .shipmiracle folder is refused: exit 4, nothing written outside", code == 4 and not (TMP / "playbook.json").exists(), (code, err))
os.unlink(str(DEV / "app1" / ".shipmiracle"))

# ---- registry playbook field ----
pid = projects.project_id(A)
snap = pbc.snapshot_of(pbc.validate({"v": 1, "type": "software"}))
try:
    registry.set_field(pid, "playbook", snap)
    ok = registry.entry(pid)["playbook"] == snap
except Exception as e:
    ok = repr(e)
check("registry.set_field accepts a valid playbook snapshot", ok is True, ok)
for bad in ("text", {"sha256": "zz", "type": "software", "autopilot": "guided", "overrides": {}}, dict(snap, type="spaceship"), dict(snap, extra=1), None):
    try:
        registry.set_field(pid, "playbook", bad)
        res = "accepted"
    except UsageError:
        res = "refused"
    check("registry.set_field refuses a bad snapshot %s" % (str(bad)[:30],), res == "refused", res)
check("registry SETTABLE lists playbook", "playbook" in registry.SETTABLE)
code, out, err = shipm("config", "list")
check("config list shows gate.engine = legacy", code == 0 and "gate.engine" in out and "legacy" in out, out)

after = [(p.stat().st_mtime_ns if p.exists() else None) for p in CANARY]
check("canary: real registry, config and settings untouched", before == after)
print("\n%s (%d failed)" % ("ALL PASS" if not fails else "FAILURES", fails))
sys.exit(1 if fails else 0)
