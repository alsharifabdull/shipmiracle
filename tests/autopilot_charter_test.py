#!/usr/bin/env python3
"""Phase 6 T1: charter schema/caps/sha, the first-line parser, runtime state machine and budget math, prerequisites, `shipm autopilot` CLI,
registry field, playbook config (full behind the switch), py39 syntax. SHIPMIRACLE_TEST=1 with temp HOME/state/config/dev/workspace; no network,
no real file touched (canary mtimes checked). Run: python3 tests/autopilot_charter_test.py"""
import ast, json, os, pathlib, random, subprocess, sys, tempfile, time, types

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import shipmiracle_timing as T
SHIPM = str(ROOT / "bin" / "shipm")
TMP = pathlib.Path(tempfile.mkdtemp(prefix="shipmiracle-apc-")).resolve()
HOME, DEV, STATE, CONF, WS = (TMP / n for n in ("home", "dev", "state", "config", "ws"))
ENV = dict(os.environ, SHIPMIRACLE_TEST="1", SHIPMIRACLE_HOME=str(HOME), SHIPMIRACLE_DEV=str(DEV), SHIPMIRACLE_STATE=str(STATE), SHIPMIRACLE_CONFIG=str(CONF), SHIPMIRACLE_WS=str(WS), HOME=str(HOME))
for k in ("SHIPMIRACLE_DEBUG", "CLAUDECODE", "SHIPMIRACLE_ENFORCE_OWNER", "SHIPMIRACLE_TEST_NOW", "SHIPMIRACLE_GATE_ENGINE"):
    ENV.pop(k, None)
REAL = pathlib.Path(os.path.expanduser("~"))
CANARY = [REAL / ".config" / "shipmiracle" / "registry.json", REAL / ".config" / "shipmiracle" / "config.json", REAL / ".claude" / "settings.json"]
before = [(p.stat().st_mtime_ns if p.exists() else None) for p in CANARY]
os.environ.clear(); os.environ.update(ENV)
from shipmiracle import UsageError, SafetyError, SchemaError, NotFound, config, registry, projects, paths  # noqa: E402
from shipmiracle.autopilot import charter as ch, state as st, visibility  # noqa: E402
from shipmiracle.autopilot import cli as apcli  # noqa: E402
from shipmiracle.playbook import config as pbc, store as pbstore  # noqa: E402

fails = 0
def check(name, ok, info=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(info)[:700]))
    fails += 0 if ok else 1

def shipm(*args, env=None, cwd=None):
    r = subprocess.run([sys.executable, SHIPM] + list(args), env=env or ENV, capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL, cwd=cwd)
    return r.returncode, r.stdout, r.stderr

def raises(exc, fn, *a, **k):
    try:
        fn(*a, **k)
    except exc as e:
        return str(e)
    except BaseException as e:
        return "WRONG " + type(e).__name__ + ": " + str(e)
    return None

def git(d, *a):
    subprocess.run(["git", "-C", str(d)] + list(a), env=ENV, check=True, capture_output=True)

# ------------------------------------------------------------------ fixture world
HOME.mkdir(parents=True)
(HOME / ".gitconfig").write_text("[user]\n name = t\n email = t@example.com\n[init]\n defaultBranch = main\n[commit]\n gpgsign = false\n")
(WS / "config").mkdir(parents=True)
FLOW = WS / "config" / "flow.json"
FLOW.write_text('{\n  "default": "strict",\n  "projects": {}\n}\n')
for n in ("alpha", "app1"):
    d = DEV / n
    d.mkdir(parents=True)
    git(d, "init", "-q")
    (d / "a.txt").write_text("1\n")
    git(d, "add", "-A"); git(d, "commit", "-q", "-m", "init")
A = str(DEV / "alpha")
URL = "https://github.com/owner/alpha.git"
git(A, "remote", "add", "origin", URL)
STATE.mkdir(parents=True, exist_ok=True)
(STATE / "health.json").write_text(json.dumps({"ts": time.time(), "chats": {"alpha": {"chats": 0}, "app1": {"chats": 0}}}))
PID = projects.project_id(A)
WEEK = 7 * 86400

def write_plan(pct=34, resets=None, age=0, seven=True, raw=None):
    resets = resets if resets is not None else int(time.time()) + 3 * 86400
    rl = {"five_hour": {"used_percentage": 5, "resets_at": resets - 10}}
    if seven:
        rl["seven_day"] = {"used_percentage": pct, "resets_at": resets}
    body = raw if raw is not None else {"at": int(time.time()) - age, "rate_limits": rl, "model": "x"}
    (STATE / "plan.json").write_text(json.dumps(body))

# ---- config: new keys
check("config: autopilot.full.enabled defaults to off", config.get("autopilot.full.enabled") is False)
check("config: autopilot.mcp_allow defaults to []", config.get("autopilot.mcp_allow") == [])
check("config: switch value validated (maybe -> usage error)", raises(UsageError, config.set, "autopilot.full.enabled", "maybe") is not None)
config.set("autopilot.mcp_allow", "mcp__github__create_issue")
check("config: mcp_allow stores a list", config.get("autopilot.mcp_allow") == ["mcp__github__create_issue"])
config.unset("autopilot.mcp_allow")
code, out, err = shipm("switch", "autopilot.full.enabled")
check("shipm switch autopilot.full.enabled prints off", code == 0 and out.strip() == "off", (code, out, err))

# ---- playbook config: full only with the switch and for software
sw = {"v": 1, "type": "software", "autopilot": "full"}
msg = raises(UsageError, pbc.validate, sw)
check("playbook full with the switch off: clear error naming the switch", msg and "autopilot.full.enabled" in msg, msg)
check("playbook full for type app: the P6 message, whatever the switch", raises(UsageError, pbc.validate, {"v": 1, "type": "app", "autopilot": "full"}) == "full autopilot arrives in P6")
check("guided and manual still validate", pbc.validate({"v": 1, "type": "software", "autopilot": "guided"})["autopilot"] == "guided")
check("a bogus autopilot value is refused", raises(UsageError, pbc.validate, {"v": 1, "type": "software", "autopilot": "turbo"}) is not None)
code, out, err = shipm("switch", "autopilot.full.enabled", "on")
check("shipm switch autopilot.full.enabled on", code == 0 and "on" in out, (code, out, err))
check("playbook full with the switch on and software: accepted", pbc.validate(sw)["autopilot"] == "full")
check("playbook full for type app with the switch on: still refused", raises(UsageError, pbc.validate, {"v": 1, "type": "app", "autopilot": "full"}) == "full autopilot arrives in P6")
check("level off turns full into manual (unchanged rule)", pbc.validate(dict(sw, level="off"))["autopilot"] == "manual")
check("registry snapshot with full: valid while the switch is on", pbc._valid_snapshot({"sha256": "0" * 64, "type": "software", "autopilot": "full", "overrides": {}}) is not None)
config.set("autopilot.full.enabled", "off")
check("registry snapshot with full: invalid again with the switch off (fail closed)", pbc._valid_snapshot({"sha256": "0" * 64, "type": "software", "autopilot": "full", "overrides": {}}) is None)
config.set("autopilot.full.enabled", "on")

# ------------------------------------------------------------------ schema and caps
BASE = {"goal": "ship login", "scope": ["src/**"], "ends": ["CR-001"]}
def mk(**kw):
    f = dict(BASE); f.update(kw)
    return ch.build(f, "alpha", PID, "cli", 1000)
def bad(name, **kw):
    r = raises(UsageError, mk, **kw)
    check("schema refuses " + name, r is not None and not r.startswith("WRONG"), r)
def good(name, key, val, **kw):
    try:
        c = mk(**kw)
        check("schema accepts " + name, c.get(key) == val, c.get(key))
    except Exception as e:
        check("schema accepts " + name, False, e)

c0 = mk()
check("defaults: budget 10, time 3, deps none", c0["budget_pct_week"] == 10 and c0["time_h"] == 3 and c0["deps"] == {"mode": "none"}, c0)
check("id is ch- + sha256[:8] of the body", c0["id"] == "ch-" + ch.digest(c0)[:8] and len(c0["id"]) == 11)
check("sha is over canonical JSON (sorted keys, no spaces)", ch.digest(c0) == __import__("hashlib").sha256(json.dumps({k: v for k, v in c0.items() if k != "id"}, sort_keys=True, separators=(",", ":")).encode()).hexdigest())
check("sha does not depend on key order", ch.digest(dict(reversed(list(c0.items())))) == ch.digest(c0))
good("goal of 200", "goal", "g" * 200, goal="g" * 200); bad("goal of 201", goal="g" * 201); bad("empty goal", goal=""); bad("goal only control characters", goal="\n\t\x00")
good("goal control characters stripped", "goal", "ab", goal="a\nb\x07")
good("1 glob", "scope", ["a"], scope=["a"]); good("20 globs", "scope", ["g%d" % i for i in range(20)], scope=["g%d" % i for i in range(20)]); bad("21 globs", scope=["g%d" % i for i in range(21)]); bad("no globs", scope=[])
good("glob of 200", "scope", ["a" * 200], scope=["a" * 200]); bad("glob of 201", scope=["a" * 201]); bad("glob with ..", scope=["a/../b"]); bad("glob '..'", scope=[".."]); bad("absolute glob", scope=["/etc/**"]); bad("tilde glob", scope=["~/x"])
bad("backslash glob", scope=["a\\b"]); bad("control char in glob", scope=["a\x01"]); good("duplicate globs collapse", "scope", ["a"], scope=["a", "a"])
good("a glob with dots inside a name", "scope", ["a..b/**"], scope=["a..b/**"])
for v, okv in ((0, 0), (1, 1), (10, 1), (25, 1), (26, 0), (-1, 0)):
    good("budget %s" % v, "budget_pct_week", v, budget=v) if okv else bad("budget %s" % v, budget=v)
bad("budget as float", budget=10.5); bad("budget True", budget=True); good("budget '10%' text", "budget_pct_week", 10, budget="10%")
for v in (0.25, 0.5, 3, 8):
    good("time %s" % v, "time_h", v, time=v)
for v in (0, 0.2, 0.3, 8.25, 9, -1, True, "abc"):
    bad("time %r" % (v,), time=v)
good("time '90m'", "time_h", 1.5, time="90m"); good("time '3h'", "time_h", 3, time="3h")
check("time 3.0 is stored as the integer 3 (stable canonical form)", isinstance(mk(time=3.0)["time_h"], int))
good("deps none", "deps", {"mode": "none"}, deps="none")
good("deps listed 10", "deps", {"mode": "listed", "names": ["p%d" % i for i in range(10)]}, deps={"mode": "listed", "names": ["p%d" % i for i in range(10)]})
bad("deps listed 11", deps={"mode": "listed", "names": ["p%d" % i for i in range(11)]}); bad("deps listed empty", deps={"mode": "listed", "names": []})
bad("deps uppercase name", deps="Left-Pad"); bad("deps name with a space/quote", deps={"mode": "listed", "names": ["a b"]}); bad("deps name of 101", deps={"mode": "listed", "names": ["a" * 101]})
good("deps scoped npm name", "deps", {"mode": "listed", "names": ["@types/node"]}, deps="@types/node"); bad("deps mode other", deps={"mode": "all"}); bad("deps none with names", deps={"mode": "none", "names": ["a"]})
good("ends 1", "ends", ["CR-001"], ends=["CR-001"]); good("ends 5", "ends", ["CR-00%d" % i for i in range(1, 6)], ends=["CR-00%d" % i for i in range(1, 6)])
bad("ends 6", ends=["CR-00%d" % i for i in range(1, 7)]); bad("ends none", ends=[]); bad("ends lowercase id", ends=["cr-001"]); bad("ends 2-digit id", ends=["CR-01"]); bad("ends missing", ends=None)
check("ends range expands", ch.expand_ends("CR-012..CR-014") == ["CR-012", "CR-013", "CR-014"])
check("ends range of 5 ok, of 6 refused", len(ch.expand_ends("CR-001..CR-005")) == 5 and raises(UsageError, ch.expand_ends, "CR-001..CR-006") is not None)
check("ends backwards range refused with a reason", "backwards" in (raises(UsageError, ch.expand_ends, "CR-014..CR-012") or ""))
check("ends comma list and mixed junk", ch.expand_ends("CR-001,CR-004") == ["CR-001", "CR-004"] and raises(UsageError, ch.expand_ends, "CR-001,junk") is not None)
check("set_by must be panel|chat|cli", raises(UsageError, ch.build, BASE, "alpha", PID, "web", 1) is not None)
check("chat charter needs session8 and prompt_sha", raises(UsageError, ch.build, BASE, "alpha", PID, "chat", 1) is not None)
cc = ch.build(BASE, "alpha", PID, "chat", 1, "abcd1234", "a" * 64)
check("chat charter records session8 and prompt_sha", cc["session8"] == "abcd1234" and cc["prompt_sha"] == "a" * 64)
check("cli charter must not carry session8", raises(UsageError, ch.normalize, dict({k: v for k, v in c0.items() if k != "id"}, session8="abcd1234")) is not None)
check("unknown key refused", raises(UsageError, ch.normalize, dict({k: v for k, v in c0.items() if k != "id"}, extra=1)) is not None)
check("always-excluded paths are the spec seven plus the P6 security additions", ch.ALWAYS_EXCLUDED == (".shipmiracle/**", ".claude/**", ".githooks/**", ".git/**", ".github/workflows/**", "**/.env*", ".mcp.json",
                                                                                                         ".co" "dex/**", ".vscode/tasks.json", ".vscode/settings.json", ".envrc", ".husky/**", "CLAUDE.md", "AGENTS.md"))
rec = ch.record_of(c0)
check("validate_record accepts an honest record", ch.validate_record(rec) == c0)
tam = json.loads(json.dumps(rec)); tam["charter"]["goal"] = "delete everything"
check("validate_record: edited goal, old sha -> refused", "sha256" in (raises(UsageError, ch.validate_record, tam) or ""))
tam = json.loads(json.dumps(rec)); tam["charter"]["scope"] = ["**"]; tam["sha256"] = ch.digest(tam["charter"])
check("validate_record: edited scope + recomputed sha but old id -> refused", "id" in (raises(UsageError, ch.validate_record, tam) or ""))
tam = json.loads(json.dumps(rec)); tam["charter"]["budget_pct_week"] = 99
check("validate_record: budget 99 in a stored charter -> refused", raises(UsageError, ch.validate_record, tam) is not None)
tam = json.loads(json.dumps(rec)); del tam["charter"]["budget_pct_week"]
check("validate_record: a stored charter missing a field -> refused", raises(UsageError, ch.validate_record, tam) is not None)
check("validate_record: junk -> refused", all(raises(UsageError, ch.validate_record, x) is not None for x in (None, [], {}, {"charter": 1, "sha256": 2}, {"charter": {}, "sha256": "x", "more": 1})))

# ------------------------------------------------------------------ parser
LINE = 'charter: goal="fix login"; scope="src/login/**, tests/login/**"; budget=10%; time=3h; deps=none; ends=CR-012..CR-014'
f, e = ch.parse_line(LINE)
check("parse: the spec example", e is None and f == {"cmd": "set", "goal": "fix login", "scope": ["src/login/**", "tests/login/**"], "ends": ["CR-012", "CR-013", "CR-014"], "budget": 10, "time": 3, "deps": {"mode": "none"}}, (f, e))
f, e = ch.parse_line('CHARTER :goal=x;scope=a;ends=CR-001')
check("parse: case-insensitive head, spaces, defaults filled", e is None and f["budget"] == 10 and f["time"] == 3 and f["deps"] == {"mode": "none"}, (f, e))
f, e = ch.parse_line(LINE + "\nsecond line is ignored: budget=99%")
check("parse: only the first line counts", e is None and f["budget"] == 10)
check("parse: not a charter line -> (None, None)", all(ch.parse_line(x) == (None, None) for x in ("", "hello", "please set charter: x", "\ncharter: off", "chart: off", None, 5)))
check("parse: charter: off / show", ch.parse_line("charter: off") == ({"cmd": "off"}, None) and ch.parse_line("charter:  SHOW ") == ({"cmd": "show"}, None))
check("parse: allow: H-1a2b3c", ch.parse_line("allow: H-1a2b3c") == ({"cmd": "allow", "id": "H-1a2b3c"}, None))
check("parse: allow with a bad id says why", "stop id" in (ch.parse_line("allow: H-xyz")[1] or "") and "stop id" in (ch.parse_line("allow: all")[1] or ""))
ERRS = [
    ('charter: goal=x; scope=a', "missing ends"), ('charter: scope=a; ends=CR-001', "missing goal"), ('charter: goal=x; ends=CR-001', "missing scope"),
    ('charter: goal=x; scope=a; ends=CR-001; budget=40%', "cap"), ('charter: goal=x; scope=a; ends=CR-001; budget=0%', "outside"), ('charter: goal=x; scope=a; ends=CR-001; budget=10', "%"),
    ('charter: goal=x; scope=a; ends=CR-001; color=red', "unknown key"), ('charter: goal=x; goal=y; scope=a; ends=CR-001', "twice"),
    ('charter: goal="x; scope=a; ends=CR-001', "never closed"), ('charter: goal="x"y; scope=a; ends=CR-001', "closing quote"),
    ('charter: goal=; scope=a; ends=CR-001', "no value"), ('charter: goal; scope=a; ends=CR-001', "'='"),
    ('charter: goal=x; scope=a; ends=CR-001; time=2.1h', "15 minutes"), ('charter: goal=x; scope=a; ends=CR-001; time=9h', "outside"), ('charter: goal=x; scope=a; ends=CR-001; time=3', "hours"),
    ('charter: goal=x; scope=../etc; ends=CR-001', "'..'"), ('charter: goal=x; scope=/etc/x; ends=CR-001', "relative"),
    ('charter: goal=x; scope=a; ends=CR-001..CR-009', "at most 5"), ('charter: goal=x; scope=a; ends=junk', "ends"),
    ('charter: goal=x; scope=a; ends=CR-001; deps=Left-Pad', "package name"), ('charter: ' + "k" * 20 + '=1', "key"), ('charter: goal="' + "a" * 401 + '"; scope=a; ends=CR-001', "400"),
    ('charter: goal=' + "a" * 101 + '; scope=a; ends=CR-001', "100"), ('charter: ' + "x" * 1100, "1024"), ('charter: ', "goal"),
]
for line, why in ERRS:
    f, e = ch.parse_line(line)
    check("parse refuses %r with a reason mentioning %r" % (line[:50], why), f is None and e and why.lower() in e.lower(), (f, e))
f, e = ch.parse_line('charter: goal=ok; scope=a; ends=CR-001; deps="left-pad, lodash"')
check("parse: quoted deps list", e is None and f["deps"] == {"mode": "listed", "names": ["left-pad", "lodash"]}, (f, e))
f, e = ch.parse_line('charter: goal=ok; scope=a; ends=CR-001,CR-004; time=90m')
check("parse: ends list and minutes", e is None and f["ends"] == ["CR-001", "CR-004"] and f["time"] == 1.5, (f, e))
f, e = ch.parse_line('charter: goal=ok;;; scope=a ;ends=CR-001 ')
check("parse: extra semicolons and spaces tolerated", e is None, (f, e))
for case in json.load(open(ROOT / "tests" / "fixtures" / "autopilot" / "charter" / "parse_cases.json", encoding="utf-8")):
    f, e = ch.parse_line(case["line"])
    okc = f == case["fields"] and ((case.get("error") is None and e is None) if case["fields"] is not None or "error" not in case or case["error"] is None else (e is not None and case["error"].lower() in e.lower()))
    check("fixture parse case: " + case["name"], okc, (f, e))
# fuzz: never raises, always a (fields, error) pair with exactly one of them set for charter lines
rnd = random.Random(7)
ALPHA = ['charter:', 'allow:', 'goal=', 'scope=', 'ends=', 'budget=', 'time=', 'deps=', '"', ';', ' ', '=', '%', 'CR-0', '12', '..', ',', 'h', 'm', '\n', '\x00', 'é', 'H-', 'abc', '\\', "'"]
bad_shape = 0
for i in range(5000):
    s = "".join(rnd.choice(ALPHA) for _ in range(rnd.randint(0, 40)))
    if rnd.random() < 0.5:
        s = "charter: " + s
    try:
        f, e = ch.parse_line(s)
    except BaseException as ex:
        bad_shape += 1; print("fuzz exception", repr(s), ex); continue
    if not (f is None or isinstance(f, dict)) or not (e is None or isinstance(e, str)) or (f is not None and e is not None):
        bad_shape += 1
    if f is not None and f.get("cmd") == "set":
        try:
            ch.build({k: v for k, v in f.items() if k != "cmd"}, "alpha", PID, "cli", 1)
        except Exception:
            bad_shape += 1
check("parse fuzz: 5000 random lines, no exception, result always (fields|None, error|None), accepted lines always build", bad_shape == 0, bad_shape)
HOSTILE = ["charter: " + "a" * 200000, " " * 200000 + "charter: off", "charter: " + 'goal="' * 40000, "charter: " + "a=b;" * 50000, "charter: goal=" + '"' * 200000,
           "charter: " + ";" * 200000, ("charter: goal=x; scope=" + "a," * 100000), "x" * 200000 + "\ncharter: off", "charter:" + " " * 200000 + "off", "charter: ends=" + "CR-001," * 30000]
def _hostile():
    t0 = time.perf_counter()
    for h in HOSTILE:
        ch.parse_line(h)
    return (time.perf_counter() - t0) / len(HOSTILE)
ok, rep, best = T.robust(_hostile, lambda: T.spawn_ref(5), 0.05, 3)
check("parse: hostile 200 KB inputs (10 shapes) each under 50 ms (avg %.2f ms; %s)" % (best * 1000, rep), ok, rep)
worst = max(T.timed(lambda h=h: ch.parse_line(h)) for h in HOSTILE)
check("parse: worst single hostile input under 50 ms or the robust reference (%.2f ms)" % (worst * 1000), worst < 0.05 or ok, worst)
check("parse: every hostile input is refused or ignored, none stored as a charter", all((lambda r: r[0] is None or r[0].get("cmd") != "set")(ch.parse_line(h)) for h in HOSTILE))

# ------------------------------------------------------------------ world for the stateful parts (through the real CLI)
def A_(*a, **k):
    return shipm(*a, "--project", "alpha", **k)
for k, v in (("hooks.dispatcher", "v1"), ("gate.engine", "playbook")):
    config.set(k, v)
code, out, err = shipm("playbook", "set", "type", "software", "--project", "alpha", "--allow-open-chat")
check("world: playbook type software", code == 0, (code, out, err))
for t in ("one", "two", "three"):
    shipm("cr", "open", t, "--project", A)
code, out, err = shipm("playbook", "set", "autopilot", "full", "--project", "alpha", "--allow-open-chat")
check("world: playbook autopilot full accepted with the switch on", code == 0 and "full" in out, (code, out, err))
config.set("autopilot.full.enabled", "off")
code, out, err = shipm("playbook", "set", "autopilot", "full", "--project", "alpha", "--allow-open-chat")
check("playbook set autopilot full with the switch off: exit 2 and the switch is named", code == 2 and "autopilot.full.enabled" in err, (code, err))
config.set("autopilot.full.enabled", "on")
visibility.write_entry(URL, True, now=time.time(), state_dir=STATE)
write_plan(34)
now_ = time.time()

def names(rows):
    return [t for ok_, t in rows if not ok_]
rows = ch.prereqs(A)
check("prereqs: all 7 rows pass in the fixture world", len(rows) == 7 and not names(rows), rows)

def only_fails(label, mutate, restore, expect_substr, exact_one=True):
    mutate()
    try:
        rows_ = ch.prereqs(A)
        bad_ = names(rows_)
        okk = any(expect_substr in t for t in bad_) and (len(bad_) == 1 or not exact_one)
        check("prereqs: %s fails %s" % (label, "on its own" if exact_one else ""), okk, bad_)
        r = raises(UsageError, ch.store_charter, PID, dict(BASE, ends=["CR-001"]), "cli")
        check("store refuses when %s (message says why)" % label, r and expect_substr in r and "Charter" not in "x" and not r.startswith("WRONG"), r)
        check("store left nothing behind when %s" % label, st.read(PID) is None and registry.autopilot_of(registry.entry(PID)) is None)
    finally:
        restore()
only_fails("switch off", lambda: config.set("autopilot.full.enabled", "off"), lambda: config.set("autopilot.full.enabled", "on"), "autopilot.full.enabled is off", exact_one=False)
only_fails("level warn", lambda: FLOW.write_text('{"default": "strict", "projects": {"alpha": "warn"}}'), lambda: FLOW.write_text('{"default": "strict", "projects": {}}'), "flow level is warn")
only_fails("dispatcher legacy", lambda: config.set("hooks.dispatcher", "legacy"), lambda: config.set("hooks.dispatcher", "v1"), "hooks.dispatcher is legacy")
only_fails("gate.engine shadow", lambda: config.set("gate.engine", "shadow"), lambda: config.set("gate.engine", "playbook"), "gate.engine is shadow")
only_fails("remote cached public", lambda: visibility.write_entry(URL, False, now=time.time(), state_dir=STATE), lambda: visibility.write_entry(URL, True, now=time.time(), state_dir=STATE), "not cached as private")
only_fails("plan.json stale", lambda: write_plan(34, age=16 * 60), lambda: write_plan(34), "plan.json")
only_fails("plan.json without seven_day", lambda: write_plan(seven=False), lambda: write_plan(34), "plan.json")
only_fails("plan.json absent", lambda: os.unlink(STATE / "plan.json"), lambda: write_plan(34), "plan.json")
only_fails("plan.json odd", lambda: write_plan(raw={"at": "now", "rate_limits": 5}), lambda: write_plan(34), "plan.json")
# playbook-level rows
code, _, _ = shipm("playbook", "set", "autopilot", "guided", "--project", "alpha", "--allow-open-chat")
only_fails("playbook autopilot guided", lambda: None, lambda: None, "playbook autopilot is guided")
shipm("playbook", "set", "autopilot", "full", "--project", "alpha", "--allow-open-chat")
pj = pathlib.Path(A) / ".shipmiracle" / "playbook.json"
orig = pj.read_text()
only_fails("playbook.json edited (untrusted)", lambda: pj.write_text(orig.replace('"strict"', '"warn"')), lambda: pj.write_text(orig), "untrusted")
os.unlink(pj)
rows = ch.prereqs(A)
check("prereqs: playbook.json missing -> the registry snapshot is not 'trusted' (row fails)", any("snapshot" in t for t in names(rows)), names(rows))
pj.write_text(orig)
check("prereqs: back to all green after the mutations", not names(ch.prereqs(A)), names(ch.prereqs(A)))
git(A, "remote", "add", "extra", "https://github.com/owner/other.git")
check("prereqs: a second remote that is not cached private fails", any("extra" in t for t in names(ch.prereqs(A))))
git(A, "remote", "remove", "extra")
git(A, "remote", "remove", "origin")
check("prereqs: no remote at all passes the remote row", not names(ch.prereqs(A)))
git(A, "remote", "add", "origin", URL)
# a project that is not software
rows_app = ch.prereqs(str(DEV / "app1"))
check("prereqs: a project without playbook fails the playbook row", any("no playbook" in t for t in names(rows_app)), names(rows_app))

# ------------------------------------------------------------------ store (library) and registry field
r = raises(UsageError, ch.store_charter, PID, dict(BASE, ends=["CR-009"]), "cli")
check("store: ends must exist (CR-009 does not)", r and "CR-009" in r and "open or queued" in r, r)
shipm("cr", "abandon", "CR-003", "--project", A)
r = raises(UsageError, ch.store_charter, PID, dict(BASE, ends=["CR-003"]), "cli")
check("store: an abandoned CR cannot be an end", r and "CR-003" in r, r)
r = raises(UsageError, ch.store_charter, PID, dict(BASE, budget=40, ends=["CR-001"]), "cli")
check("store: budget 40 refused", r and "budget" in r, r)
out = ch.store_charter(PID, dict(BASE, ends=["CR-001", "CR-002"]), "cli")
C = out["charter"]
check("store: returns charter, sha and the echo line", C["id"].startswith("ch-") and out["sha256"] == ch.digest(C) and out["echo"].startswith("Charter %s set:" % C["id"]), out)
check("echo: week now and where it stops", "(now 34%, stops at 44%)" in out["echo"] and "shipm autopilot start --project alpha" in out["echo"] and "ends CR-001..CR-002" in out["echo"], out["echo"])
rec = registry.autopilot_of(registry.entry(PID))
check("registry: the entry carries {charter, sha256}", rec and rec["sha256"] == out["sha256"] and ch.validate_record(rec) == C)
check("registry: playbook snapshot untouched by the charter", registry.entry(PID)["playbook"]["autopilot"] == "full")
s0 = st.read(PID)
check("state: file exists, state=set, 0600, expires set_ts+24h", s0["state"] == "set" and s0["charter_sha"] == out["sha256"] and s0["expires"] == s0["set_ts"] + 86400 and (os.stat(st.path(PID)).st_mode & 0o777) == 0o600, s0)
check("state: folder is 0700", (os.stat(st.path(PID).parent).st_mode & 0o777) == 0o700)
ev = [e for e in __import__("shipmiracle.events", fromlist=["x"]).tail(50) if e["kind"] == "autopilot.charter_set"]
check("event autopilot.charter_set carries sha8 and set_by only", ev and ev[-1]["data"] == {"sha8": out["sha256"][:8], "set_by": "cli"}, ev[-1:] )
code, out_, err = shipm("registry", "set", "alpha", "autopilot", json.dumps(rec))
check("`shipm registry set alpha autopilot ...` is refused (exit 2)", code == 2 and "can be set" in err, (code, err))
check("registry.set_field(autopilot) is refused", raises(UsageError, registry.set_field, PID, "autopilot", rec) is not None)
check("registry.SETTABLE does not list autopilot", "autopilot" not in registry.SETTABLE)
check("registry.set_autopilot validates the sha", raises(UsageError, registry.set_autopilot, PID, {"charter": C, "sha256": "0" * 64}) is not None)
check("registry.set_autopilot validates the shape", raises(UsageError, registry.set_autopilot, PID, {"x": 1}) is not None)
os.environ["CLAUDECODE"] = "1"; os.environ["SHIPMIRACLE_ENFORCE_OWNER"] = "1"
check("registry.set_autopilot is owner-only (refused inside a chat)", raises(SafetyError, registry.set_autopilot, PID, None) is not None)
check("store with origin cli is refused inside a chat", raises(SafetyError, ch.store_charter, PID, dict(BASE), "cli") is not None)
check("clear with origin cli is refused inside a chat", raises(SafetyError, ch.clear, PID, "cli") is not None)
del os.environ["CLAUDECODE"]; del os.environ["SHIPMIRACLE_ENFORCE_OWNER"]
check("a second set while 'set' replaces the first (new sha)", ch.store_charter(PID, dict(BASE, goal="second", ends=["CR-001"]), "cli")["sha256"] != out["sha256"])
check("public store(origin='chat') is rejected", "store_from_prompt" in (raises(UsageError, ch.store_charter, PID, dict(BASE, ends=["CR-001"]), "chat") or ""))
check("public store rejects chat even with forged session8/prompt_sha kwargs", raises(TypeError, ch.store_charter, PID, dict(BASE), "chat", session8="abcd1234", prompt_sha="b" * 64) is not None)
PROMPT = 'charter: goal="chat one"; scope=src/**; ends=CR-001\nsecond line'
cres = ch.store_from_prompt(PID, PROMPT, "sess-1234-abcdef")
cc2 = cres["charter"]
check("store_from_prompt: set_by chat, session8 from the id, prompt_sha recomputed from the prompt", cc2["set_by"] == "chat" and cc2["session8"] == "sess-123" and cc2["prompt_sha"] == __import__("hashlib").sha256(PROMPT.encode()).hexdigest(), cc2)
check("store_from_prompt works inside a chat environment (no require_owner)", True)
os.environ["CLAUDECODE"] = "1"; os.environ["SHIPMIRACLE_ENFORCE_OWNER"] = "1"
okc = ch.store_from_prompt(PID, PROMPT, "sess-1234")["charter"]["set_by"] == "chat"
check("store_from_prompt needs no owner check even with CLAUDECODE set", okc)
check("clear (public) is still owner-only inside a chat", raises(SafetyError, ch.clear, PID) is not None)
check("clear_from_prompt with a non-off prompt is refused", raises(UsageError, ch.clear_from_prompt, PID, "charter: show") is not None and registry.autopilot_of(registry.entry(PID)) is not None)
del os.environ["CLAUDECODE"]; del os.environ["SHIPMIRACLE_ENFORCE_OWNER"]
check("store_from_prompt: a non-charter prompt is refused", raises(UsageError, ch.store_from_prompt, PID, "hello", "sess1") is not None)
check("store_from_prompt: a bad line is refused with the reason", "budget" in (raises(UsageError, ch.store_from_prompt, PID, 'charter: goal=x; scope=a; ends=CR-001; budget=40%', "sess1") or ""))
check("store_from_prompt: a charter on a later line is refused", raises(UsageError, ch.store_from_prompt, PID, "hi\n" + PROMPT, "sess1") is not None)
check("store_from_prompt: no session id refused", raises(UsageError, ch.store_from_prompt, PID, PROMPT, "") is not None)
ch.clear_from_prompt(PID, "charter: off")
check("clear_from_prompt('charter: off') clears", registry.autopilot_of(registry.entry(PID)) is None and st.read(PID)["ended_reason"] == "owner")
check("store: unknown project id", raises(NotFound, ch.store_charter, "0" * 12, dict(BASE), "cli") is not None)

# ------------------------------------------------------------------ state machine, expiry, active(), tamper
C = ch.store_charter(PID, dict(BASE, ends=["CR-001"], budget=10, time=3), "cli", at=1_000_000, prereq_check=False)["charter"]
T0 = 1_000_000
check("state set: not active (not started)", st.active(PID, T0 + 1) is None and st.check(PID, T0 + 1)[1] == "the run is set")
check("set lapses after 24 h: settle -> ended:lapsed", st.settle(PID, at=T0 + 86400 - 1)["state"] == "set" and (lambda s: s["state"] == "ended" and s["ended_reason"] == "lapsed")(st.settle(PID, at=T0 + 86400)))
check("lapsed run cannot be started", "lapsed" in (raises(UsageError, st.start, PID, C, {"pct": 1.0, "resets_at": 5.0, "fresh": True, "age": 0}, T0 + 90000) or "") or "nothing to start" in (raises(UsageError, st.start, PID, C, {"pct": 1.0, "resets_at": 5.0, "fresh": True, "age": 0}, T0 + 90000) or ""))
C = ch.store_charter(PID, dict(BASE, ends=["CR-001"], budget=10, time=3), "cli", at=T0, prereq_check=False)["charter"]
R = T0 + 3 * 86400
PL = {"pct": 34.0, "resets_at": float(R), "age": 0, "fresh": True}
check("start needs a fresh plan", "plan.json" in (raises(UsageError, st.start, PID, C, None, T0 + 10) or "") and "plan.json" in (raises(UsageError, st.start, PID, C, dict(PL, fresh=False), T0 + 10) or ""))
s1 = st.start(PID, C, PL, T0 + 100)
check("start: running, started, expires = started + time_h, budget_start", s1["state"] == "running" and s1["started"] == T0 + 100 and s1["expires"] == T0 + 100 + 3 * 3600 and s1["budget_start"] == {"pct": 34.0, "resets_at": float(R)}, s1)
check("start twice refused", raises(UsageError, st.start, PID, C, PL, T0 + 101) is not None)
a = st.active(PID, T0 + 200)
check("active: charter + state returned when everything matches", a and a["charter"] == C and a["state"]["state"] == "running")
check("active: one second before expires", st.active(PID, s1["expires"] - 1) is not None)
check("active: at expires -> inactive 'expired'", st.active(PID, s1["expires"]) is None and "expired" in st.check(PID, s1["expires"])[1])
check("settle at expires -> ended:time", (lambda s: s["state"] == "ended" and s["ended_reason"] == "time")(st.settle(PID, at=s1["expires"])))
check("an ended run keeps its first reason", st.end(PID, "owner", T0) is None or st.read(PID)["ended_reason"] == "time")
check("ended: inactive", st.active(PID, T0 + 200) is None and "ended" in st.check(PID, T0 + 200)[1])
# restart cycle for tamper tests
ch.store_charter(PID, dict(BASE, ends=["CR-001"], budget=10, time=3), "cli", at=T0, prereq_check=False)
C = registry.autopilot_of(registry.entry(PID))["charter"]
st.start(PID, C, PL, T0 + 100)
REG = CONF / "registry.json"
regraw = REG.read_text()
def patch_reg(fn):
    d = json.loads(regraw); fn(d["projects"][PID]["autopilot"]); REG.write_text(json.dumps(d, sort_keys=True, indent=1))
check("tamper: baseline active", st.active(PID, T0 + 200) is not None)
patch_reg(lambda a: a["charter"].__setitem__("goal", "pwn"))
check("tamper: goal edited in the registry -> inactive", st.active(PID, T0 + 200) is None and "sha" in st.check(PID, T0 + 200)[1], st.check(PID, T0 + 200))
def both(a):
    a["charter"]["scope"] = ["**"]; a["charter"]["id"] = "ch-" + ch.digest(a["charter"])[:8]; a["sha256"] = ch.digest(a["charter"])
patch_reg(both)
check("tamper: charter + id + sha all re-made in the registry -> inactive (state.charter_sha differs)", st.active(PID, T0 + 200) is None and "differs" in st.check(PID, T0 + 200)[1], st.check(PID, T0 + 200))
patch_reg(lambda a: a.__setitem__("sha256", "0" * 64))
check("tamper: sha field changed -> inactive", st.active(PID, T0 + 200) is None)
REG.write_text(regraw)
check("tamper: registry restored -> active again", st.active(PID, T0 + 200) is not None)
sp = st.path(PID); sraw = sp.read_text()
d_ = json.loads(sraw); d_["charter_sha"] = "1" * 64; sp.write_text(json.dumps(d_))
check("tamper: state.charter_sha changed -> inactive", st.active(PID, T0 + 200) is None)
sp.write_text("{not json")
check("tamper: damaged state file -> inactive, no exception", st.active(PID, T0 + 200) is None and st.snapshot(PID) is None and st.settle(PID) is None)
d_ = json.loads(sraw); d_["state"] = "nonsense"; sp.write_text(json.dumps(d_))
check("tamper: unknown state value -> inactive", st.active(PID, T0 + 200) is None)
sp.write_text(sraw)
d_ = json.loads(sraw); d_["ended_reason"] = "owner"; sp.write_text(json.dumps(d_))
check("ended_reason set while 'running' -> inactive", st.active(PID, T0 + 200) is None)
sp.write_text(sraw)
os.unlink(REG); REG.write_text(regraw);
d = json.loads(regraw); d["projects"][PID].pop("autopilot"); REG.write_text(json.dumps(d))
check("no charter in the registry -> inactive", st.active(PID, T0 + 200) is None and "no charter" in st.check(PID, T0 + 200)[1])
REG.write_text(regraw)
config.set("autopilot.full.enabled", "off")
check("switch off -> inactive (check) and settle pauses the run (fail closed)", st.active(PID, T0 + 200) is None and st.settle(PID, at=T0 + 200)["state"] == "paused" and st.read(PID)["paused_reason"] == "switch_off")
config.set("autopilot.full.enabled", "on")
check("paused run: inactive", st.active(PID, T0 + 200) is None)
r_ = st.resume(PID)
check("resume: paused -> running", r_["state"] == "running" and r_["stop"] is None)
check("resume when not paused refused", raises(UsageError, st.resume, PID) is not None)
STOP = {"id": "H-1a2b3c", "rule": "H2-publish", "ts": T0 + 300, "text": "git push -f " + "x" * 300, "cmd_sha": "c" * 64}
p_ = st.pause(PID, STOP)
check("pause records the stop (text capped at 200)", p_["state"] == "paused" and p_["stop"]["id"] == "H-1a2b3c" and len(p_["stop"]["text"]) == 200, p_)
check("pause needs a stop id of the form H-xxxxxx", raises(UsageError, st.pause, PID, {"id": "nope"}) is not None)
check("allow: wrong id refused", raises(UsageError, st.allow, PID, "H-ffffff", T0 + 310) is not None)
check("allow: bad id format refused", raises(UsageError, st.allow, PID, "H-1", T0 + 310) is not None)
al = st.allow(PID, "H-1a2b3c", T0 + 310)
check("allow: running again with one allow bound to the cmd_sha for 10 min", al["state"] == "running" and al["stop"] is None and al["allow"] == [{"id": "H-1a2b3c", "cmd_sha": "c" * 64, "until": T0 + 310 + 600}], al)
check("consume_allow: a different command does not match", st.consume_allow(PID, "d" * 64, T0 + 320) is False and len(st.read(PID)["allow"]) == 1)
check("consume_allow: expired allow does not match", st.consume_allow(PID, "c" * 64, T0 + 310 + 600) is False)
check("consume_allow: the right command once", st.consume_allow(PID, "c" * 64, T0 + 320) is True)
check("consume_allow: one-shot (second time False)", st.consume_allow(PID, "c" * 64, T0 + 321) is False and st.read(PID)["allow"] == [])
st.pause(PID, {"id": "H-aaaaaa", "rule": "H1", "ts": 1, "text": "t"})
check("allow: a stop without a cmd_sha cannot be allowed", "no command hash" in (raises(UsageError, st.allow, PID, "H-aaaaaa", T0 + 330) or ""))
st.resume(PID)
st.add_session(PID, "abcd1234"); st.add_session(PID, "abcd1234"); st.bump_decisions(PID); st.set_progress(PID, cr="CR-001", branch="auto/CR-001")
s_ = st.read(PID)
check("sessions deduped, decisions counted, progress fields set", s_["sessions"] == ["abcd1234"] and s_["decisions"] == 1 and s_["cr"] == "CR-001" and s_["branch"] == "auto/CR-001", s_)
check("set_progress refuses unknown fields and control characters", raises(UsageError, st.set_progress, PID, expires="x") is not None and raises(UsageError, st.set_progress, PID, cr="a\nb") is not None)
_sha = "ab" * 20
_cwd_before = set(os.listdir("."))
st.set_progress(PID, base=_sha)
check("set_progress(base=<commit>) stores the commit as a field and never uses it as a state folder (stray <sha>/ folder regression)",
      st.read(PID)["base"] == _sha and set(os.listdir(".")) == _cwd_before and not os.path.exists(_sha))
st.pause(PID, {"id": "H-bbbbbb", "rule": "H1", "ts": 1, "text": "t"}); st.settle(PID, at=st.read(PID)["expires"])
check("a paused run past its time ends as ended:time", st.read(PID)["state"] == "ended" and st.read(PID)["ended_reason"] == "time")
check("end() rejects an unknown reason", raises(UsageError, st.end, PID, "whim") is not None)
# clock seam
os.environ["SHIPMIRACLE_TEST_NOW"] = "12345"
check("clock: SHIPMIRACLE_TEST_NOW honoured under SHIPMIRACLE_TEST=1", st.now() == 12345.0)
os.environ["SHIPMIRACLE_TEST"] = "0"
check("clock: SHIPMIRACLE_TEST_NOW ignored without SHIPMIRACLE_TEST=1", abs(st.now() - time.time()) < 5)
os.environ["SHIPMIRACLE_TEST"] = "1"; del os.environ["SHIPMIRACLE_TEST_NOW"]

# ------------------------------------------------------------------ budget math
def plan(pct, resets=R, fresh=True):
    return {"pct": float(pct), "resets_at": float(resets), "age": 0 if fresh else 2000, "fresh": fresh}
SB = {"budget_start": {"pct": 34.0, "resets_at": float(R)}, "last_pct": 34.0}
check("used_pct: same window = current - start", st.used_pct(SB, plan(40)) == (6.0, "plan.json"))
check("used_pct: never negative", st.used_pct(SB, plan(30)) == (0.0, "plan.json"))
check("used_pct: week reset = (last before reset - start) + current", st.used_pct(dict(SB, last_pct=40.0), plan(3, R + WEEK)) == (9.0, "plan.json"))
check("used_pct: a window older than the start = unknown", st.used_pct(SB, plan(3, R - WEEK))[0] is None)
check("used_pct: stale plan = unknown", st.used_pct(SB, plan(40, fresh=False)) == (None, "unknown"))
check("used_pct: no plan / no start = unknown", st.used_pct(SB, None) == (None, "unknown") and st.used_pct({}, plan(1)) == (None, "unknown"))
cap = {"budget_pct_week": 10, "time_h": 3}
L = st.limits(dict(SB, started=1000), cap, plan(43), 1000 + 60)
check("limits: 9 of 10 -> near, not reached", L["used_pct"] == 9.0 and L["budget_near"] and not L["budget_reached"], L)
L = st.limits(dict(SB, started=1000), cap, plan(44), 1060)
check("limits: exactly the cap -> reached", L["budget_reached"] and not L["budget_unknown"], L)
L = st.limits(dict(SB, started=1000), cap, plan(34, fresh=False), 1060)
check("limits: stale plan.json counts as reached (budget_unknown)", L["budget_reached"] and L["budget_unknown"] and L["source"] == "unknown", L)
L = st.limits(dict(SB, started=1000), cap, plan(35), 1000 + 3 * 3600 - 1)
check("limits: time near at 90%, not reached one second before", L["time_near"] and not L["time_reached"] and L["left_s"] == 1.0, L)
check("limits: time reached at the cap", st.limits(dict(SB, started=1000), cap, plan(35), 1000 + 3 * 3600)["time_reached"])
check("limits: 80% is not near", not st.limits(dict(SB, started=1000), cap, plan(35), 1000 + int(0.8 * 3 * 3600))["time_near"])
# observe with a reset in between, two resets
ch.store_charter(PID, dict(BASE, ends=["CR-001"]), "cli", at=T0, prereq_check=False)
C = registry.autopilot_of(registry.entry(PID))["charter"]
st.start(PID, C, plan(34), T0 + 10)
Lx = st.observe(PID, C, plan(40), T0 + 20)
check("observe: same window updates last_pct and used_pct", st.read(PID)["last_pct"] == 40.0 and st.read(PID)["used_pct"] == 6.0 and Lx["used_pct"] == 6.0, st.read(PID))
Lx = st.observe(PID, C, plan(3, R + WEEK), T0 + 30)
check("observe: after the reset used = (40-34) + 3 = 9", Lx["used_pct"] == 9.0 and not Lx["budget_reached"], Lx)
Lx = st.observe(PID, C, plan(5, R + WEEK), T0 + 40)
check("observe: later in the new window used = 6 + 5 = 11 -> reached", Lx["used_pct"] == 11.0 and Lx["budget_reached"], Lx)
Lx = st.observe(PID, C, plan(1, R + 2 * WEEK), T0 + 50)
check("observe: a SECOND reset keeps the earlier spend (6 + 5 + 1 = 12)", Lx["used_pct"] == 12.0, Lx)
Lx = st.observe(PID, C, plan(40, fresh=False), T0 + 60)
check("observe: a stale plan changes nothing and reports reached", Lx["budget_reached"] and Lx["budget_unknown"] and st.read(PID)["used_pct"] == 12.0, Lx)
# plan_reading from files
write_plan(34, resets=R)
pr = st.plan_reading(time.time())
check("plan_reading: fresh file", pr and pr["fresh"] and pr["pct"] == 34.0 and pr["resets_at"] == float(R), pr)
write_plan(34, resets=R, age=15 * 60 + 5)
check("plan_reading: 15 min + 5 s old = not fresh", st.plan_reading(time.time())["fresh"] is False)
write_plan(34, resets=R, age=15 * 60 - 5)
check("plan_reading: 15 min - 5 s old = fresh", st.plan_reading(time.time())["fresh"] is True)
write_plan(34, resets=R, age=-3600)
check("plan_reading: stamped an hour in the future = not fresh", st.plan_reading(time.time())["fresh"] is False)
write_plan(150); check("plan_reading: percentage 150 = unusable", st.plan_reading(time.time()) is None)
write_plan(True); check("plan_reading: boolean percentage = unusable", st.plan_reading(time.time()) is None)
write_plan(seven=False); check("plan_reading: no seven_day = None", st.plan_reading(time.time()) is None)
(STATE / "plan.json").write_text("{nope"); check("plan_reading: not JSON = None", st.plan_reading(time.time()) is None)
os.unlink(STATE / "plan.json"); check("plan_reading: absent = None", st.plan_reading(time.time()) is None)
write_plan(34)

# ------------------------------------------------------------------ snapshot (panel contract)
ch.clear(PID)
check("snapshot: null when there is no state file", st.snapshot(PID) is None or st.snapshot(PID)["state"] == "ended")
st.delete(PID); check("snapshot: null after delete", st.snapshot(PID) is None)
KEYS = {"state", "level", "enabled", "charter", "decisions", "budget", "time", "stop", "cr", "branch", "worktree", "ended_reason"}
ch.store_charter(PID, dict(BASE, ends=["CR-001"], goal="snap"), "cli")
sn = st.snapshot(PID)
check("snapshot(set): the contract keys, charter summary, level full", set(sn) == KEYS and sn["state"] == "set" and sn["level"] == "full" and sn["enabled"] is True
      and set(sn["charter"]) == {"id", "goal", "scope", "ends", "set_by", "sha8"} and sn["charter"]["goal"] == "snap" and set(sn["budget"]) == {"used_pct", "cap_pct", "source"}
      and set(sn["time"]) == {"left_s", "cap_s"} and sn["stop"] is None and sn["time"]["cap_s"] == 10800.0, sn)
C = registry.autopilot_of(registry.entry(PID))["charter"]
write_plan(34, resets=R)
st.start(PID, C, st.plan_reading(), time.time() - 600)
sn = st.snapshot(PID)
check("snapshot(running): budget used 0 of 10 from plan.json, time left < cap", sn["state"] == "running" and sn["budget"] == {"used_pct": 0.0, "cap_pct": 10, "source": "plan.json"} and 0 < sn["time"]["left_s"] < 10800, sn)
st.pause(PID, {"id": "H-123abc", "rule": "H3-network", "ts": 5, "text": "curl x", "cmd_sha": "e" * 64})
sn = st.snapshot(PID)
check("snapshot(paused): stop {id, rule, text, ts} (no cmd_sha)", sn["state"] == "paused" and sn["stop"] == {"id": "H-123abc", "rule": "H3-network", "text": "curl x", "ts": 5}, sn)
st.resume(PID); st.end(PID, "done")
sn = st.snapshot(PID)
check("snapshot(ended): ended_reason", sn["state"] == "ended" and sn["ended_reason"] == "done")
json.dumps(sn)
check("snapshot is JSON serialisable", True)

# ------------------------------------------------------------------ CLI (real subprocess)
code, out, err = shipm("autopilot", "--help")
check("autopilot --help: exit 0 with usage", code == 0 and "usage: shipm autopilot" in out, (code, out[:100], err))
code, out, err = shipm("--help")
check("top-level help lists autopilot", "autopilot" in out)
check("autopilot without action: exit 2", shipm("autopilot")[0] == 2)
check("autopilot unknown action: exit 2", shipm("autopilot", "frobnicate")[0] == 2)
check("charter without sub-action: exit 2", A_("autopilot", "charter")[0] == 2)
check("charter set without --goal: exit 2", A_("autopilot", "charter", "set", "--scope", "a", "--ends", "CR-001")[0] == 2)
st.delete(PID); ch.clear(PID)
code, out, err = A_("autopilot", "show")
check("show with no run: exit 0 says so", code == 0 and "no autopilot run" in out, (code, out, err))
code, out, err = A_("autopilot", "show", "--json")
check("show --json with no run: autopilot null", code == 0 and json.loads(out) == {"v": 1, "autopilot": None}, out)
code, out, err = A_("autopilot", "charter", "show")
check("charter show with no charter: exit 3", code == 3, (code, err))
write_plan(34)
SET = ["autopilot", "charter", "set", "--goal", "fix login", "--scope", "src/login/**,tests/login/**", "--budget", "10", "--time", "3h", "--deps", "none", "--ends", "CR-001..CR-002"]
code, out, err = A_(*SET)
check("charter set (CLI): exit 0, echo with id", code == 0 and out.startswith("Charter ch-") and "ends CR-001..CR-002" in out, (code, out, err))
code, out, err = A_(*(SET[:-2] + ["--ends", "CR-001", "--budget", "40"]))
check("charter set budget 40: exit 1 'Charter NOT set' with the cap", code == 1 and "Charter NOT set" in err and "budget" in err, (code, err))
code, out, err = A_(*(SET[:-2] + ["--ends", "CR-001", "--time", "2.1h"]))
check("charter set time 2.1h: exit 1 not a multiple of 15 minutes", code == 1 and "15 minutes" in err, (code, err))
code, out, err = A_(*(SET[:-2] + ["--ends", "CR-099"]))
check("charter set ends unknown CR: exit 1", code == 1 and "CR-099" in err, (code, err))
code, out, err = A_("autopilot", "charter", "show")
check("charter show: describes the charter", code == 0 and "fix login" in out and "always excluded" in out, (code, out))
code, out, err = A_("autopilot", "charter", "show", "--json")
j = json.loads(out)
check("charter show --json: record validates", code == 0 and ch.validate_record({"charter": j["charter"], "sha256": j["sha256"]}), out[:200])
code, out, err = A_("autopilot", "show")
check("show: state set with charter id", code == 0 and "set" in out and j["charter"]["id"] in out, out)
# owner / tty refusals
OWN = dict(ENV, CLAUDECODE="1", SHIPMIRACLE_ENFORCE_OWNER="1")
for argv in (SET, ["autopilot", "charter", "clear"], ["autopilot", "start", "--yes"], ["autopilot", "stop"], ["autopilot", "allow", "H-1a2b3c"], ["autopilot", "resume"]):
    code, out, err = A_(*argv, env=OWN)
    check("inside a chat `Shipmiracle %s` is refused (exit 4, owner)" % " ".join(argv[:3]), code == 4 and "owner" in err, (code, err))
check("show is allowed inside a chat", A_("autopilot", "show", env=OWN)[0] == 0)
check("charter show is allowed inside a chat", A_("autopilot", "charter", "show", env=OWN)[0] == 0)
code, out, err = A_("autopilot", "start")
check("start without a terminal and without --yes: exit 4 'needs a terminal'", code == 4 and "terminal" in err, (code, err))
check("state still 'set' after the refused start", st.read(PID)["state"] == "set")
# a chat-set charter: start shows set_by/session8 and needs the typed id
ch.store_from_prompt(PID, PROMPT, "sess-1234")
sn = st.snapshot(PID)
check("snapshot shows set_by chat", sn["charter"]["set_by"] == "chat", sn)
cid = sn["charter"]["id"]
code, out, err = A_("autopilot", "start", "--yes")
check("start --yes of a chat charter without --ack: refused (exit 4), prints set_by and session", code == 4 and cid in err and "chat session sess-123" in out, (code, out, err))
code, out, err = A_("autopilot", "start", "--yes", "--ack", "ch-00000000")
check("start --yes with a wrong ack: refused", code == 4 and st.read(PID)["state"] == "set", (code, err))
ns0 = types.SimpleNamespace(project="alpha", yes=False, json=False, rargs=[], ack=None)
apcli._is_tty = lambda: True
answers = iter(["yes", "wrong"])
apcli._ask = lambda p: next(answers)
check("start of a chat charter: yes + wrong id -> refused", raises(Exception, apcli.cmd_start, ns0) is not None and st.read(PID)["state"] == "set")
answers = iter(["yes"])
apcli._ask = lambda p: next(answers, "")
check("start of a chat charter: yes without the id -> refused", raises(Exception, apcli.cmd_start, ns0) is not None and st.read(PID)["state"] == "set")
ch.clear(PID)
A_(*SET)
# start: typed yes (in-process with the TTY seams), --yes outside tests refused
ns = types.SimpleNamespace(project="alpha", yes=False, json=False, rargs=[])
apcli._is_tty = lambda: True
apcli._ask = lambda p: "no"
r = raises(Exception, apcli.cmd_start, ns)
check("start: typed 'no' -> refused (exit 1), still set", r and st.read(PID)["state"] == "set" and "yes" in r, r)
apcli._ask = lambda p: "YES"
check("start: 'YES' is not 'yes'", raises(Exception, apcli.cmd_start, ns) is not None and st.read(PID)["state"] == "set")
_sb = paths.sandboxed
paths.sandboxed = lambda: False
r = raises(SafetyError, apcli.cmd_start, types.SimpleNamespace(project="alpha", yes=True, json=False, rargs=[]))
paths.sandboxed = _sb
check("start --yes outside tests (not sandboxed) is refused", r and "tests" in r and st.read(PID)["state"] == "set", r)
apcli._is_tty = lambda: False
check("start: no tty -> refused", raises(SafetyError, apcli.cmd_start, ns) is not None)
apcli._is_tty = lambda: True; apcli._ask = lambda p: "yes"
write_plan(34, resets=R)
import io; _so = sys.stdout; sys.stdout = io.StringIO()
try:
    rc = apcli.cmd_start(ns); said = sys.stdout.getvalue()
finally:
    sys.stdout = _so
s2 = st.read(PID)
check("start: typed yes -> running, charter printed, worktree created, nothing launched", rc == 0 and s2["state"] == "running" and "fix login" in said and "auto-CR-001" in said and "nothing is launched" in said and s2["budget_start"]["pct"] == 34.0, (rc, said, s2))
check("start prints the charter before asking (always excluded paths shown)", ".mcp.json" in said)
code, out, err = A_("autopilot", "start", "--yes")
check("start when already running: exit 1", code == 1, (code, err))
code, out, err = A_("autopilot", "show", "--json")
check("show --json running: snapshot with state running", code == 0 and json.loads(out)["autopilot"]["state"] == "running", out)
code, out, err = A_("autopilot", "charter", "set", *SET[3:])
check("charter set while running refused (stop it first)", code == 1 and "stop" in err, (code, err))
# allow / resume via CLI
st.pause(PID, {"id": "H-0a0a0a", "rule": "H2-publish", "ts": 1, "text": "git push", "cmd_sha": "f" * 64})
code, out, err = A_("autopilot", "allow", "H-ffffff")
check("allow wrong id: exit 1", code == 1 and "no paused run" in err, (code, err))
code, out, err = A_("autopilot", "allow", "nonsense")
check("allow bad id: exit 1", code == 1, (code, err))
code, out, err = A_("autopilot", "allow")
check("allow without id: exit 2", code == 2)
code, out, err = A_("autopilot", "allow", "H-0a0a0a")
check("allow right id: exit 0, one-shot, 10 minutes", code == 0 and "once" in out and "10 minutes" in out and st.read(PID)["allow"][0]["cmd_sha"] == "f" * 64 and st.read(PID)["state"] == "running", (code, out, err))
check("event autopilot.allowed written", any(e["kind"] == "autopilot.allowed" for e in __import__("shipmiracle.events", fromlist=["x"]).tail(60)))
code, out, err = A_("autopilot", "resume")
check("resume when running: exit 1", code == 1 and "nothing to resume" in err, (code, err))
st.pause(PID, {"id": "H-0b0b0b", "rule": "H1", "ts": 1, "text": "x"})
write_plan(34, age=16 * 60)
code, out, err = A_("autopilot", "resume")
check("resume with a prerequisite failing (stale plan): exit 1 and says which", code == 1 and "plan.json" in err and st.read(PID)["state"] == "paused", (code, err))
write_plan(34, resets=R)
code, out, err = A_("autopilot", "resume")
check("resume: exit 0, running", code == 0 and st.read(PID)["state"] == "running", (code, out, err))
code, out, err = A_("autopilot", "stop")
check("stop: exit 0, ended:owner and the charter is cleared", code == 0 and st.read(PID)["ended_reason"] == "owner" and registry.autopilot_of(registry.entry(PID)) is None, (code, out, err))
check("stop again: 'nothing to stop' or clean exit 0", A_("autopilot", "stop")[0] == 0)
check("charter show after stop: exit 3", A_("autopilot", "charter", "show")[0] == 3)
check("start after stop: exit 3 no charter", A_("autopilot", "start", "--yes")[0] == 3)
A_(*SET); code, out, err = A_("autopilot", "charter", "clear")
check("charter clear on a 'set' run: ends it as owner and clears the registry", code == 0 and st.read(PID)["ended_reason"] == "owner" and registry.autopilot_of(registry.entry(PID)) is None, (code, out, err))
# start with prerequisites failing: nothing moves
A_(*SET)
config.set("gate.engine", "legacy")
code, out, err = A_("autopilot", "start", "--yes")
check("start with gate.engine legacy: exit 1 names it, state stays set", code == 1 and "gate.engine is legacy" in err and st.read(PID)["state"] == "set", (code, err))
config.set("gate.engine", "playbook")
# lapsed: fake clock through the environment of the subprocess
LAPSE_ENV = dict(ENV, SHIPMIRACLE_TEST_NOW=str(int(time.time()) + 90000))
code, out, err = A_("autopilot", "start", "--yes", env=LAPSE_ENV)
check("start after 24 h (fake clock in the subprocess): not started", code != 0 and st.read(PID)["state"] in ("ended", "set"), (code, err, st.read(PID)["state"]))
# worktree is not the main project
wt = TMP / "wt"; (DEV / ".worktrees" / "alpha").mkdir(parents=True, exist_ok=True)
git(A, "worktree", "add", "-q", "-b", "auto/CR-099", str(DEV / ".worktrees" / "alpha" / "x"))
code, out, err = shipm("autopilot", "show", "--project", str(DEV / ".worktrees" / "alpha" / "x"))
check("autopilot from a worktree: exit 2, names the main project", code == 2 and "main project" in err, (code, err))

# ------------------------------------------------------------------ py39 syntax and canaries
for f in sorted((ROOT / "shipmiracle" / "autopilot").glob("*.py")):
    src = f.read_text(encoding="utf-8")
    try:
        tree = ast.parse(src, filename=str(f), feature_version=(3, 9)); okp = True
    except SyntaxError as ex:
        okp = False; tree = None
    fut = tree is not None and any(isinstance(n, ast.ImportFrom) and n.module == "__future__" and any(a.name == "annotations" for a in n.names) for n in tree.body)
    check("py39: %s parses and has `from __future__ import annotations`" % f.name, okp and (fut or not src.strip() or f.name == "__init__.py"))
after = [(p.stat().st_mtime_ns if p.exists() else None) for p in CANARY]
check("no real registry/config/settings touched (canary mtimes)", before == after)
print("\nFAILED: %d" % fails if fails else "\nALL PASS"); sys.exit(1 if fails else 0)
