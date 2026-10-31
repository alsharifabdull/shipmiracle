#!/usr/bin/env python3
"""bin/shipm + shipmiracle/cli.py: every subcommand, flag and exit code, run as real subprocesses with SHIPMIRACLE_TEST=1 and temp SHIPMIRACLE_* folders.
Run: python3 tests/shipmiracle_cli_test.py"""
import json, os, pathlib, re, stat, subprocess, sys, tempfile, time
os.environ.pop("CLAUDECODE", None)       # the owner check only runs in a fully temp sandbox or outside a chat (H1)

ROOT = pathlib.Path(__file__).resolve().parent.parent
SHIPM = str(ROOT / "bin" / "shipm")
TMP = pathlib.Path(tempfile.mkdtemp(prefix="shipmiracle-cli-")).resolve()
HOME, DEV, STATE, CONF, WS = (TMP / n for n in ("home", "dev", "state", "config", "ws"))
ENV = dict(os.environ, SHIPMIRACLE_TEST="1", SHIPMIRACLE_HOME=str(HOME), SHIPMIRACLE_DEV=str(DEV), SHIPMIRACLE_STATE=str(STATE), SHIPMIRACLE_CONFIG=str(CONF), SHIPMIRACLE_WS=str(WS), HOME=str(HOME))
ENV.pop("SHIPMIRACLE_DEBUG", None)
os.environ.update({k: v for k, v in ENV.items() if k.startswith("SHIPMIRACLE_")})
sys.path.insert(0, str(ROOT))
from shipmiracle import config, events, projects, state  # noqa: E402

fails = 0
def check(name, ok, info=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(info)))
    fails += 0 if ok else 1

def shipm(*args, env=None, inp=None):
    r = subprocess.run([sys.executable, SHIPM] + list(args), env=env or ENV, capture_output=True, text=True, timeout=60, input=inp)
    return r.returncode, r.stdout, r.stderr

def write(p, text=""):
    p = pathlib.Path(p); p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text)

# ---- fixture tree: alpha, beta (held, symlink-free), gamma (no AGENTS.md), .hidden, plain (no .git), file ----
for n in ("alpha", "beta", "gamma"):
    (DEV / n / ".git").mkdir(parents=True)
write(DEV / "alpha" / "AGENTS.md", "x"); (DEV / "alpha" / ".claude").mkdir()
write(DEV / "beta" / "AGENTS.md", "x"); (DEV / "beta" / ".claude").mkdir()
(DEV / ".hidden" / ".git").mkdir(parents=True); (DEV / "plain").mkdir(); write(DEV / "afile")
write(WS / "config" / "ci-hold.txt", "# held\nbeta\n")
write(WS / "config" / "watch.json", json.dumps({"quiet": 5}))
subprocess.run(["git", "-C", str(DEV / "alpha"), "init", "-q"], check=True)
subprocess.run(["git", "-C", str(DEV / "alpha"), "remote", "add", "origin", "https://user:pw@github.com/Owner/Alpha.git"], check=True)

# ---- help and global behaviour ----
code, out, err = shipm("--help")
check("--help exits 0 and lists every command", code == 0 and all(c in out for c in ("projects", "state", "config", "switch", "registry", "events", "doctor", "idea", "bg")), out[:200])
for cmd in ("projects", "state", "config", "switch", "registry", "events", "doctor"):
    code, out, err = shipm(cmd, "--help")
    check("%s --help exits 0 with usage" % cmd, code == 0 and "usage: shipm %s" % cmd in out, (code, out[:80], err))
code, out, err = shipm()
check("no command: exit 2, one shipm: line, no traceback", code == 2 and err.startswith("shipm: ") and "Traceback" not in err, (code, err))
code, out, err = shipm("bogus")
check("unknown command: exit 2", code == 2 and err.startswith("shipm: "), err)
code, out, err = shipm("projects", "--names", "--json")
check("conflicting output flags: exit 2", code == 2 and err.startswith("shipm: "), (code, err))
check("bin/shipm is executable with the isolated python3 shebang (env -S python3 -IS, D14 #8)", os.access(SHIPM, os.X_OK) and open(SHIPM).readline().strip() == "#!/usr/bin/env -S python3 -IS")

# ---- projects ----
names = projects.names(dev=str(DEV))
check("fixture list is alpha beta gamma", names == ["alpha", "beta", "gamma"], names)
code, out, _ = shipm("projects")
check("projects (default) = projects.names", code == 0 and out.split("\n")[:-1] == names, out)
code, out, _ = shipm("projects", "--names")
check("--names equals projects.names", out.split("\n")[:-1] == names)
code, out, _ = shipm("projects", "--paths")
check("--paths equals the listed paths", out.split("\n")[:-1] == [p.path for p in projects.list_projects(dev=str(DEV))], out)
code, out, _ = shipm("projects", "--ids")
check("--ids is id<TAB>name equal to the library", out.split("\n")[:-1] == ["%s\t%s" % (p.id, p.name) for p in projects.list_projects(dev=str(DEV))], out)
code, out, _ = shipm("projects", "--json")
j = json.loads(out)
check("--json: v=1 first key and the project fields", code == 0 and out.startswith('{"v": 1') and j["v"] == 1
      and [p["name"] for p in j["projects"]] == names and set(j["projects"][0]) == {"id", "name", "path", "real", "symlink", "git", "hub", "held", "registry"}, out[:200])
check("--json held flag and registry null when absent", {p["name"]: p["held"] for p in j["projects"]} == {"alpha": False, "beta": True, "gamma": False}
      and all(p["registry"] is None for p in j["projects"]))
code, out, _ = shipm("projects", "--scope", "template")
check("--scope template: only alpha (beta held, gamma has no AGENTS.md)", out.split("\n")[:-1] == ["alpha"], out)
code, out, _ = shipm("projects", "--scope", "standards")
check("--scope standards = library", out.split("\n")[:-1] == [p.name for p in projects.scope(projects.list_projects(dev=str(DEV)), "standards")], out)
code, out, _ = shipm("projects", "--scope", "ci")
check("--scope ci = library (git status needed: alpha/beta have no tracked STATUS)", out.split("\n")[:-1] == [p.name for p in projects.scope(projects.list_projects(dev=str(DEV)), "ci")], out)
code, out, err = shipm("projects", "--scope", "nope")
check("bad --scope: exit 2", code == 2 and err.startswith("shipm: "), err)
code, out, _ = shipm("projects", "--held")
check("--held lists only beta", out.split("\n")[:-1] == ["beta"], out)
code, out, _ = shipm("projects", "--held", "--paths")
check("--held --paths", out.strip() == str(DEV / "beta"), out)
code, out, _ = shipm("projects", "--resolve", str(DEV / "alpha" / "sub" / "deep"))
check("--resolve inside a project: hit (even if the folder is missing)", code == 0 and out.split("\t")[1].strip() == "alpha" and re.fullmatch(r"[0-9a-f]{12}\talpha\n", out), (code, out))
(DEV / "alpha" / "sub").mkdir()
code, out, _ = shipm("projects", "--resolve", str(DEV / "alpha" / "sub"))
check("--resolve of a real subfolder: hit", code == 0 and out.endswith("\talpha\n"), (code, out))
code, out, err = shipm("projects", "--resolve", str(TMP / "elsewhere"))
check("--resolve outside: exit 3, shipm: message", code == 3 and out == "" and err.startswith("shipm: "), (code, out, err))
code, out, err = shipm("projects", "--resolve", "relative/path")
check("--resolve relative path: exit 3 (never guesses)", code == 3, (code, err))

# ---- config ----
code, out, _ = shipm("config", "path")
check("config path", code == 0 and out.strip() == str(CONF / "config.json"), out)
code, out, _ = shipm("config", "list")
check("config list shows defaults", code == 0 and "logs.retention_days = 30" in out and "switches.state.v1 = true" in out and "release.author_name = null" in out, out)
check("config list has no removed wifi keys", "wifi" not in out, out)
code, out, _ = shipm("config", "set", "release.author_name", "someuser")
check("config set release.author_name ok", code == 0, out)
code, out, _ = shipm("config", "list", "--json")
jj = json.loads(out)
check("config list --json, v=1", jj["v"] == 1 and jj["config"]["release.author_name"] == "someuser" and jj["config"]["logs.retention_days"] == 30, out)
code, out, _ = shipm("config", "get", "release.author_name")
check("config get shows the value", out.strip() == "someuser", out)
raw = (CONF / "config.json").read_text()
check("stored value is there with mode 0600", "someuser" in raw and stat.S_IMODE(os.stat(CONF / "config.json").st_mode) == 0o600)
code, out, _ = shipm("events", "tail", "-n", "50")
check("events carry the key, not the value", "someuser" not in out and "config.set" in out, out)
code, out, err = shipm("config", "set", "wifi.hotspot", "x")
check("the removed wifi.hotspot key is now an unknown key (exit 2)", code == 2, (code, err))
code, out, _ = shipm("config", "set", "logs.retention_days", "7")
code, out, _ = shipm("config", "get", "logs.retention_days")
check("config set/get int", out.strip() == "7", out)
code, out, _ = shipm("config", "get", "switches.state.v1")
check("config get bool prints JSON true", out.strip() == "true", out)
for args, why in ((("set", "logs.retention_days", "0"), "range"), (("set", "logs.retention_days", "abc"), "type"),
                  (("set", "owner.user", "Bad User"), "regex"), (("set", "nope.key", "1"), "unknown key"),
                  (("set", "switches.state.v1", "maybe"), "bool"), (("set", "release.author_name", "x" * 65), "length"),
                  (("set", "logs.retention_days"), "missing value"), (("get", "nope.key"), "unknown get"), (("get",), "missing key"),
                  (("unset", "nope.key"), "unknown unset")):
    code, out, err = shipm("config", *args)
    check("config %s: exit 2 (%s)" % (" ".join(args[:2]), why), code == 2 and err.startswith("shipm: ") and "Traceback" not in err, (code, err))
for sec in ("watch", "ideas", "notifications"):
    code, out, err = shipm("config", "set", sec + ".x", "1")
    check("config set %s.x: exit 2 pointing to the repo file" % sec, code == 2 and "config/%s.json" % sec in err, err)
code, out, err = shipm("config", "unset", "watch.quiet")
check("config unset on a get-only section: exit 2", code == 2 and "config/watch.json" in err, err)
code, out, _ = shipm("config", "get", "watch.quiet")
check("config get on a get-only section reads the repo file", code == 0 and out.strip() == "5", (code, out))
code, out, _ = shipm("config", "unset", "release.author_name")
code, out2, _ = shipm("config", "get", "release.author_name")
check("config unset removes the value", code == 0 and out2.strip() == "null", out2)
write(CONF / "config.json", "{not json")
code, out, err = shipm("config", "list")
check("damaged config file: exit 1 with shipm: message, no traceback", code == 1 and err.startswith("shipm: ") and "Traceback" not in err, (code, err))
os.unlink(CONF / "config.json")

# ---- switch ----
code, out, _ = shipm("switch", "state.v1")
check("switch NAME shows on (default)", code == 0 and out.strip() == "on", out)
code, out, _ = shipm("switch", "state.v1", "off")
code, out2, _ = shipm("switch", "state.v1")
check("switch off round trip", code == 0 and out2.strip() == "off" and config.switch("state.v1") is False, (out, out2))
code, out, _ = shipm("switch", "state.v1", "on")
code, out2, _ = shipm("switch", "state.v1")
check("switch on round trip", code == 0 and out2.strip() == "on")
for args in (("nope",), ("state.v1", "maybe"), ("../x", "on")):
    code, out, err = shipm("switch", *args)
    check("switch %s: exit 2" % " ".join(args), code == 2 and err.startswith("shipm: "), (code, err))

# ---- state ----
code, out, _ = shipm("state", "ls")
check("state ls on an empty state folder lists the mirrored names and the agents manifest as none", code == 0 and out.split("\n")[:-1] == ["agents.json\tnone", "aside.json\tnone", "away.json\tnone", "ci.json\tnone", "guard.json\tnone", "health.json\tnone", "seen.json\tnone", "tidy.json\tnone"], out)
code, out, err = shipm("state", "get", "guard.json")
check("state get of an absent name: exit 3", code == 3 and err.startswith("shipm: "), (code, err))
code, out, err = shipm("state", "get")
check("state get without NAME: exit 2", code == 2, (code, err))
code, out, err = shipm("state", "get", "../etc")
check("state get invalid name: exit 2", code == 2, (code, err))
state.write("guard.json", {"mode": "on", "n": 1}, "shipmiracle-guard", base=STATE)
write(STATE / "guard.json", json.dumps({"mode": "on", "n": 1}))
os.chmod(STATE, 0o700); os.chmod(STATE / "guard.json", 0o600)
old = time.time() - 3600
os.utime(STATE / "guard.json", (old, old))
code, out, _ = shipm("state", "ls")
check("state ls shows both", "guard.json\tboth" in out, out)
code, out, _ = shipm("state", "ls", "--json")
check("state ls --json", json.loads(out)["v"] == 1 and {"name": "guard.json", "v1": True, "legacy": True} in json.loads(out)["state"], out)
code, out, _ = shipm("state", "get", "guard.json")
check("state get prints the data", code == 0 and json.loads(out) == {"mode": "on", "n": 1}, out)
code, out, _ = shipm("state", "check")
check("state check healthy: exit 0 'ok'", code == 0 and out.strip() == "ok", (code, out))
code, out, _ = shipm("state", "check", "--json")
check("state check --json healthy", code == 0 and json.loads(out) == {"v": 1, "ok": True, "problems": []}, out)
# drift: legacy differs and is old (settled) -> problem
write(STATE / "guard.json", json.dumps({"mode": "off"})); os.chmod(STATE / "guard.json", 0o600)
os.utime(STATE / "guard.json", (old, old))
code, out, _ = shipm("state", "check")
check("state check detects drift (legacy older than 60 s): exit 1", code == 1 and "guard.json" in out and "differs" in out, (code, out))
code, out, _ = shipm("state", "check", "--json")
check("state check --json drift", code == 1 and json.loads(out)["ok"] is False and json.loads(out)["v"] == 1, out)
# a fresh legacy write (< 60 s) is not counted yet
now = time.time()
os.utime(STATE / "guard.json", (now - 5, now - 5))
code, out, _ = shipm("state", "check")
check("fresh legacy write (younger than 60 s) is not drift", code == 0, (code, out))
os.utime(STATE / "guard.json", (now - 61, now - 61))
code, out, _ = shipm("state", "check")
check("legacy 61 s old and different is drift", code == 1, (code, out))
# switch off: drift is not counted
shipm("switch", "state.v1", "off")
code, out, _ = shipm("state", "check")
check("with switch state.v1 off drift is not counted", code == 0, (code, out))
shipm("switch", "state.v1", "on")
# read_compat through the CLI: the newest copy wins (legacy is newer than v1 here)
v1m = old - 100
os.utime(STATE / "v1" / "guard.json", (v1m, v1m))
code, out, _ = shipm("state", "get", "guard.json")
check("state get takes the newest copy (legacy)", json.loads(out) == {"mode": "off"}, out)
# legacy unreadable
write(STATE / "guard.json", "{broken"); os.chmod(STATE / "guard.json", 0o600); os.utime(STATE / "guard.json", (old, old))
code, out, _ = shipm("state", "check")
check("unreadable legacy file is a problem", code == 1 and "unreadable" in out, out)
os.unlink(STATE / "guard.json")
# permissions
os.chmod(STATE, 0o755)
code, out, _ = shipm("state", "check")
check("state folder mode 755 is a problem: exit 1", code == 1 and "755" in out, (code, out))
os.chmod(STATE, 0o700)
os.chmod(STATE / "v1" / "guard.json", 0o644)
code, out, _ = shipm("state", "check")
check("v1 file mode 644 is a problem: exit 1", code == 1 and "644" in out, out)
os.chmod(STATE / "v1" / "guard.json", 0o600)
code, out, _ = shipm("state", "check")
check("healthy again after fixing modes", code == 0, (code, out))
# state commands are read-only
before = sorted(str(p) for p in STATE.rglob("*") if "events" not in p.name)
for a in (("ls",), ("get", "guard.json"), ("check",)):
    shipm("state", *a)
check("state commands did not create or remove files", before == sorted(str(p) for p in STATE.rglob("*") if "events" not in p.name))
# refusal of the real folders under SHIPMIRACLE_TEST (exit 4)
real = pathlib.Path(__import__("pwd").getpwuid(os.getuid()).pw_dir) / ".config" / "shipmiracle"     # the account's real home from the password database, not $HOME (a run under a temp HOME must still refuse the real folder)
e2 = dict(ENV, SHIPMIRACLE_CONFIG=str(real))
code, out, err = shipm("config", "set", "logs.retention_days", "9", env=e2)
check("write to the real config folder under SHIPMIRACLE_TEST is refused with exit 4", code == 4 and err.startswith("shipm: "), (code, err))

# ---- registry ----
reg_path = CONF / "registry.json"
code, out, _ = shipm("registry", "propose")
lines = out.split("\n")[:-1]
check("registry propose: one line per project with the normalised remote", code == 0 and len(lines) == 3 and any(l.endswith("\talpha\tOwner/Alpha") for l in lines) and "pw" not in out, out)
check("registry propose writes nothing", not reg_path.exists())
code, out, _ = shipm("registry", "propose", "--json")
pj = json.loads(out)
check("registry propose --json: v=1 and entries by id", pj["v"] == 1 and len(pj["projects"]) == 3 and "pw" not in out and not reg_path.exists(), out[:200])
code, out, _ = shipm("registry", "write")
check("registry write adds all three", code == 0 and out.startswith("added 3") and reg_path.exists() and stat.S_IMODE(os.stat(reg_path).st_mode) == 0o600, out)
code, out, _ = shipm("registry", "write")
check("registry write again adds none", out.strip() == "added 0", out)
code, out, _ = shipm("projects", "--json")
check("projects --json now carries the registry entry", any(p["registry"] and p["registry"]["name"] == "alpha" for p in json.loads(out)["projects"]), out[:200])
code, out, err = shipm("registry", "bogus")
check("registry bad action: exit 2", code == 2, err)
write(reg_path, "{bad"); os.chmod(reg_path, 0o600)
code, out, err = shipm("registry", "write")
check("damaged registry: exit 1, file untouched", code == 1 and err.startswith("shipm: ") and reg_path.read_text() == "{bad", (code, err))
code, out, _ = shipm("projects", "--json")
check("projects --json survives a damaged registry (registry null)", code == 0 and all(p["registry"] is None for p in json.loads(out)["projects"]))
code, out, _ = shipm("doctor", "--rows")
check("doctor --rows reports a damaged registry as FAIL (exit 1)", code == 1 and re.search(r"^  FAIL project registry", out, re.M), (code, out))
os.unlink(reg_path)

# ---- events ----
events.append("test.one", {"a": 1}, src="shipmiracle-test", base=STATE)
events.append("test.two", {"b": 2}, src="shipmiracle-test", base=STATE)
code, out, _ = shipm("events", "tail", "-n", "2")
ls = out.split("\n")[:-1]
check("events tail -n 2: two lines, oldest first, ISO time", code == 0 and len(ls) == 2 and "test.one" in ls[0] and "test.two" in ls[1] and re.match(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ ", ls[0]), out)
code, out, _ = shipm("events", "tail", "-n", "1", "--json")
je = json.loads(out)
check("events tail --json: v=1, last event", je["v"] == 1 and len(je["events"]) == 1 and je["events"][0]["kind"] == "test.two" and je["events"][0]["v"] == 1, out)
code, out, _ = shipm("events", "tail", "-n", "0")
check("events tail -n 0 prints nothing", code == 0 and out == "")
code, out, err = shipm("events", "tail", "-n", "-3")
check("events tail negative n: exit 2", code == 2, (code, err))
code, out, err = shipm("events", "tail", "-n", "x")
check("events tail non-number: exit 2", code == 2, (code, err))
code, out, _ = shipm("events", "tail")
check("events tail default count works", code == 0 and "test.two" in out)

# ---- doctor ----
code, out, _ = shipm("doctor", "--rows")
lines = out.split("\n")[:-1]
check("doctor --rows: every line matches doctor's style", lines and all(re.match(r"^  (ok|warn|FAIL|info) ", l) for l in lines), out)
check("doctor --rows covers python, state, drift, config, registry", all(any(k in l for l in lines) for k in ("python", "state folder", "state v1", "owner config", "registry")), out)
check("doctor --rows healthy -> exit 0", code == 0, (code, out))
check("doctor has no Wi-Fi row", "Wi-Fi" not in out and "wifi" not in out.lower(), out)
os.chmod(STATE, 0o755)
code, out, _ = shipm("doctor", "--rows")
check("doctor warns on state perms (warn, exit 0)", re.search(r"^  warn state folder", out, re.M) and code == 0, (code, out))
os.chmod(STATE, 0o700)
write(STATE / "guard.json", json.dumps({"mode": "zzz"})); os.chmod(STATE / "guard.json", 0o600); os.utime(STATE / "guard.json", (old, old))
code, out, _ = shipm("doctor", "--rows")
check("doctor FAILs on drift (exit 1)", re.search(r"^  FAIL state drift", out, re.M) and code == 1, (code, out))
os.unlink(STATE / "guard.json")
write(CONF / "config.json", "{bad")
code, out, _ = shipm("doctor", "--rows")
check("doctor FAILs on invalid config (exit 1)", re.search(r"^  FAIL owner config invalid", out, re.M) and code == 1, (code, out))
os.unlink(CONF / "config.json")
code, out, err = shipm("doctor")
check("doctor without --rows: exit 2", code == 2, err)

# ---- idea / bg hand-over ----
fake = TMP / "fake-tool"
write(fake, '#!/bin/sh\necho "FAKE $0 $#"\nfor a in "$@"; do echo "arg=$a"; done\nexit 7\n'); os.chmod(fake, 0o755)
code, out, _ = shipm("idea", "-p", "alpha", "list", "--help", "a b", env=dict(ENV, SHIPMIRACLE_EXEC_IDEA=str(fake)))
check("idea forwards every argument unchanged and passes the exit code", code == 7 and "FAKE" in out and out.count("arg=") == 5 and "arg=a b" in out and "arg=--help" in out, (code, out))
code, out, _ = shipm("bg", "5", "--", "sleep", "1", env=dict(ENV, SHIPMIRACLE_EXEC_BG=str(fake)))
check("bg forwards its arguments", code == 7 and "arg=5" in out and "arg=sleep" in out and out.count("arg=") == 4, (code, out))
code, out, err = shipm("idea", "list", env=dict(ENV, SHIPMIRACLE_EXEC_IDEA=str(TMP / "missing")))
check("missing target: exit 3, refused", code == 3 and err.startswith("shipm: "), (code, err))
write(TMP / "noexec", "#!/bin/sh\n"); os.chmod(TMP / "noexec", 0o644)
code, out, err = shipm("bg", env=dict(ENV, SHIPMIRACLE_EXEC_BG=str(TMP / "noexec")))
check("non-executable target: exit 3", code == 3, (code, err))
envp = dict(ENV, SHIPMIRACLE_EXEC_BG=str(fake)); envp.pop("SHIPMIRACLE_TEST")
code, out, err = shipm("bg", env=envp)
check("the exec seam is ignored without SHIPMIRACLE_TEST (real bin/shipm-bg usage shown)", "FAKE" not in out and "usage: shipm-bg" in (out + err), (code, out, err))
code, out, err = shipm("idea", "--help")
check("idea without a seam runs the real bin/idea", code == 0 and "idea —" in out, (code, out[:80], err))

# ---- unexpected exceptions ----
code, out, err = shipm("projects", env=dict(ENV, SHIPMIRACLE_DEV=str(TMP / "dev" / "afile")))
check("unexpected/odd input never shows a traceback", "Traceback" not in err and code in (0, 1, 2, 3, 4), (code, err))
boom = TMP / "boomlaunch.py"
write(boom, "import sys\nsys.path.insert(0, %r)\nfrom shipmiracle import cli\ndef bad(a):\n    raise ZeroDivisionError('secret detail')\ncli.cmd_events = bad\nsys.exit(cli.main(['events', 'tail']))\n" % str(ROOT))
for dbg, expect_trace in ((None, False), ("1", True)):
    e = dict(ENV)
    if dbg: e["SHIPMIRACLE_DEBUG"] = dbg
    r = subprocess.run([sys.executable, str(boom)], env=e, capture_output=True, text=True)
    # build_parser binds cmd_events at call time via set_defaults(fn=cmd_events), so the patched name is used
    check("unexpected exception (debug=%s): exit 1, one line with the class%s" % (dbg, ", trace shown" if expect_trace else ""),
          r.returncode == 1 and "shipm: unexpected error (ZeroDivisionError)" in r.stderr and ("Traceback" in r.stderr) == expect_trace and "secret detail" not in r.stderr.split("Traceback")[0], (r.returncode, r.stderr))
e = dict(ENV, SHIPMIRACLE_DEBUG="1"); e.pop("SHIPMIRACLE_TEST")
r = subprocess.run([sys.executable, str(boom)], env=e, capture_output=True, text=True)
check("SHIPMIRACLE_DEBUG alone (without SHIPMIRACLE_TEST) never prints a trace", r.returncode == 1 and "Traceback" not in r.stderr, r.stderr)


# ---- review fixes: drift (frozen mirror, scrubbed guard actions), SystemExit codes, odd folder names, alias folders ----
from shipmiracle import cli  # noqa: E402
DB = TMP / "driftbase"
nowt = time.time()
def v1_with_ts(base, name, data, ts, writer="shipmiracle-guard"):
    state.write(name, data, writer, base=base)
    f = state.root(base) / name
    env = json.loads(f.read_text()); env["ts"] = int(ts); f.write_text(json.dumps(env))
    os.chmod(f, 0o600)
def legacy_at(base, name, data, mtime):
    f = base / name; f.write_text(json.dumps(data)); os.utime(f, (mtime, mtime)); os.chmod(f, 0o600)
v1_with_ts(DB, "guard.json", {"mode": "on", "n": 1}, nowt - 300)
for k in range(4):                                     # the guard rewrites its legacy file every few seconds; the mirror is stuck
    legacy_at(DB, "guard.json", {"mode": "on", "n": 2 + k}, nowt - 4 + k)
dp = cli.drift_problems(DB)
check("legacy rewritten repeatedly next to a frozen v1 copy is drift (even though legacy is young)", len(dp) == 1 and "behind" in dp[0] and "guard.json" in dp[0], dp)
v1_with_ts(DB, "guard.json", {"mode": "on", "n": 9}, nowt - 2)
check("a live mirror (v1 ts close to the legacy mtime) is not drift", cli.drift_problems(DB) == [])
legacy_at(DB, "guard.json", {"mode": "on", "n": 9, "actions": ["step A now"]}, nowt - 200)
v1_with_ts(DB, "guard.json", {"mode": "on", "n": 9, "actions": ["step B now"]}, nowt - 200)
check("stopped guard: different actions text in v1 and legacy is not drift", cli.drift_problems(DB) == [], cli.drift_problems(DB))
v1_with_ts(DB, "guard.json", {"mode": "off", "n": 9, "actions": ["step B now"]}, nowt - 200)
check("a real data difference outside actions is still drift", len(cli.drift_problems(DB)) == 1 and "differs" in cli.drift_problems(DB)[0])
legacy_at(DB, "away.json", {"away": False, "ts": 1}, nowt - 200)
v1_with_ts(DB, "away.json", {"away": True, "ts": 1}, nowt - 200)
check("away.json (not guard.json) is compared in full", any("away.json: v1 copy differs" in x for x in cli.drift_problems(DB)))

real_cmd = cli.cmd_events
for val, want in ((None, 0), (0, 0), (3, 3), ("message", 1), (True, 1), (2.5, 1), (b"x", 1)):
    def raiser(a, val=val):
        raise SystemExit(val)
    cli.cmd_events = raiser
    try:
        got = cli.main(["events", "tail"])
    finally:
        cli.cmd_events = real_cmd
    check("SystemExit(%r) -> exit code %d" % (val, want), got == want, got)

odd = DEV / "Held\nx"
(odd / ".git").mkdir(parents=True)
code, out, err = shipm("projects", "--paths")
check("a folder named 'Held<newline>x' adds no line to --paths and gives a stderr warning", code == 0 and "Held" not in out.replace("beta", "") and "Held\\nx" in err and out.count("\n") == len(out.splitlines()), (out, err))
for flag in ("--names", "--ids", "--json"):
    code, out, err = shipm("projects", flag)
    check("projects %s skips the odd folder" % flag, code == 0 and "Held" not in out and "Held\\nx" in err, (out, err))
code, out, _ = shipm("doctor", "--rows")
check("doctor warns about the odd folder", "ignored (control character" in out, out)
import shutil
shutil.rmtree(odd)

os.symlink(DEV / "alpha", DEV / "alpha2")
code1, names_out, e1 = shipm("projects", "--names")
code2, ids_out, _ = shipm("projects", "--ids")
code3, js, _ = shipm("projects", "--json")
code4, paths_out, _ = shipm("projects", "--paths", "--scope", "template")
code5, rs, _ = shipm("projects", "--resolve", str(DEV / "alpha2" / "x"))
code6, doc, _ = shipm("doctor", "--rows")
code7, reg, _ = shipm("registry", "propose")
code8, st, _ = shipm("state", "check")
check("with an alias folder alpha2 -> alpha every command still works", all(c == 0 for c in (code1, code2, code3, code4, code6, code7, code8)) and code5 == 0, (code1, code2, code3, code4, code5, code6, code7, code8))
check("the alias is not a project; the real folder is", "alpha2" not in names_out and "alpha" in names_out.split() and "alpha2" not in paths_out and "alpha2" not in reg and "alpha2" not in js)
check("the alias path resolves to the real project", rs.split("\t")[1].strip() == "alpha", rs)
check("doctor has the warn row 'alias folder alpha2 -> alpha ignored'", re.search(r"^  warn alias folder alpha2 -> alpha ignored", doc, re.M) is not None, doc)
check("a warn row does not fail doctor (exit 0 unless a FAIL row)", "FAIL" not in doc and code6 == 0, doc)
os.unlink(DEV / "alpha2")
print("\nFAILED: %d" % fails if fails else "\nALL PASS"); sys.exit(1 if fails else 0)
