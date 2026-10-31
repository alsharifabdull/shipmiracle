"""The Health contract: every item kind and action is declared once in bin/shipm-watch (KINDS / OPS). This test fails the build for a kind that is raised but
not declared, a non-literal kind, a malformed entry, an unused action, a fix item without a recommendation, or "your call" in the panel.
Run: python3 tests/health_contract_test.py"""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import shipmiracle_isolation; shipmiracle_isolation.apply_to_environ()   # test isolation: fresh HOME/SHIPMIRACLE_HOME/CONFIG/STATE unless already temp
import datetime, importlib.machinery, importlib.util, json, os, pathlib, re, shutil, subprocess, sys, tempfile
ws = pathlib.Path(__file__).resolve().parent.parent
SRC = (ws / "bin/shipm-watch").read_text()
T0 = 1_800_000_000
T = pathlib.Path(tempfile.mkdtemp())
HOME, DEV, STATE, W, TMP = T / "home", T / "home/Developer", T / "state", T / "ws", T / "tasks"
for d in (DEV, STATE, W / "config", TMP):
    d.mkdir(parents=True, exist_ok=True)
ENV = dict(os.environ, SHIPMIRACLE_TEST="1", SHIPMIRACLE_HOME=str(HOME), SHIPMIRACLE_DEV=str(DEV), SHIPMIRACLE_STATE=str(STATE), SHIPMIRACLE_WS=str(W), SHIPMIRACLE_NOW=str(T0), SHIPMIRACLE_PS=str(T / "ps.txt"), SHIPMIRACLE_LSOF=str(T / "lsof.json"),
           SHIPMIRACLE_HOST=str(T / "host.json"), SHIPMIRACLE_KILL_LOG=str(T / "kills.log"), SHIPMIRACLE_TMP=str(TMP), SHIPMIRACLE_DOCKER=str(T / "docker.txt"), SHIPMIRACLE_COLIMA=str(T / "colima.txt"))
os.environ.update({k: v for k, v in ENV.items()})
(T / "lsof.json").write_text("{}"); (T / "docker.txt").write_text(""); (T / "colima.txt").write_text("running"); (T / "ps.txt").write_text("1 0 00:01 0.0 100 init\n")
spec = importlib.util.spec_from_loader("w", importlib.machinery.SourceFileLoader("w", str(ws / "bin/shipm-watch")))
w = importlib.util.module_from_spec(spec); spec.loader.exec_module(w)
fails = []


def check(n, c, info=""):
    print(("PASS " if c else "FAIL ") + n, "" if c else info)
    if not c:
        fails.append(n)


# ---- 1. the source: every raised kind has an entry, every kind is a literal ----
lits = re.findall(r'self\.add\(\s*"([a-z_]+)"', SRC)
calls = len(re.findall(r"self\.add\(", SRC))
check("every self.add(...) call passes the kind as a string literal", len(lits) == calls, f"{calls} calls, {len(lits)} literals")
missing = sorted({k for k in lits if k not in w.KINDS})
check("every raised kind has a KINDS entry", not missing, str(missing))
check("the registry has the kinds the closed-loop plan names", {"dead_agent", "orphan", "frozen_agent", "frozen_chat", "job_frozen", "context_full", "session_large", "duplicate", "duplicate_tabs", "idle_session", "playwright_dup", "vm_idle", "host_busy", "limit", "plan_approval", "waiting_you", "api_trouble", "waiting_job"} <= set(w.KINDS))
check("hog is no longer an item kind (heavy unowned processes are listed in host.unowned); leftover exists only as the fix for a PROVEN orphan when automatic cleanup is off", "hog" not in w.KINDS and w.KINDS["leftover"]["mode"] == "fix" and w.KINDS["leftover"]["chain"] == ["end-proc"])
check("the old 'report' op is gone", "report" not in w.OPS and "report" not in w.SAFE)

# ---- 2. each entry is well formed ----
for k, v in w.KINDS.items():
    ok = v["mode"] in ("auto", "fix", "info", "wait") and v["sev"] in ("red", "amber", "info") and all(isinstance(v[x], str) for x in ("fix_label", "proof", "info", "next", "verify")) and isinstance(v["chain"], list)
    ops_ok = all(o in w.OPS for o in v["chain"] + v.get("secondary", []))
    check(f"kind {k}: valid mode, severity, texts and ops", ok and ops_ok, str(v))
    if v["mode"] in ("fix", "auto"):
        check(f"kind {k}: a {v['mode']} kind has a chain, a fix label, a proof, a verify text, a next step and a red/amber severity", bool(v["chain"]) and bool(v["fix_label"]) and bool(v["proof"]) and bool(v["verify"]) and bool(v["next"]) and v["sev"] in ("red", "amber"), str(v))
    else:
        check(f"kind {k}: an info/wait kind is grey (severity info) and says what it is", v["sev"] == "info" and bool(v["info"]) and (v["chain"] == [] or v.get("dynamic")), str(v))
    check(f"kind {k}: no 'your call' wording", "your call" not in json.dumps(v).lower())

# ---- 3. the actions ----
used = {o for v in w.KINDS.values() for o in v["chain"] + v.get("secondary", []) + v.get("also", [])}
check("no unused action in OPS", not (set(w.OPS) - used), str(set(w.OPS) - used))
for o, v in w.OPS.items():
    check(f"op {o}: executor, wait_s, checks, destructive and an applicable() function", v["executor"] in ("ext", "watch") and isinstance(v["wait_s"], int) and isinstance(v["checks"], int) and v["checks"] >= 1 and isinstance(v["destructive"], bool) and callable(v["applicable"]), str(v))
    s = w.Scan.__new__(w.Scan); s.procs = {}
    check(f"op {o}: a plain-sentence impact and a safe text exist", bool(w.Scan.impact(s, o, {"pid": 0})) and bool(w.SAFE.get(o)))
check("each kind has at most one destructive step in its chain", all(sum(1 for o in v["chain"] if w.OPS[o]["destructive"]) <= 1 for v in w.KINDS.values()))
check("every executor 'ext' op is one the extension must implement: interrupt, relaunch, fresh", {o for o, v in w.OPS.items() if v["executor"] == "ext"} == {"interrupt", "relaunch", "fresh"})

nx = [v["next"] for v in w.KINDS.values() if v["mode"] in ("fix", "auto")]
check("every fix/auto kind has its own 'next' text (no generic copy shared between kinds)", len(nx) == len(set(nx)) and all(nx), str(nx))
check("host_busy's default 'next' is not an instruction for a fix chain (per-cause texts are set at run time)", "stop" not in w.KINDS["host_busy"]["next"].lower())

# ---- 4. an unknown kind is never silent and never crashes ----
s = w.Scan(); s.add("totally_new_kind", "red", "p", "t", "w")
it = s.items[0]
check("an unknown kind becomes an info item 'watcher bug: <kind> has no contract'", it["kind"] == "watcher_bug" and it["mode"] == "info" and "totally_new_kind has no contract" in it["title"] and it["actions"] == [], str(it))
check("...and it is logged to events.log", "totally_new_kind" in (STATE / "events.log").read_text())

# ---- 5. the contract command ----
r = subprocess.run([str(ws / "bin/shipm-watch"), "contract"], capture_output=True, text=True, env=ENV); c = json.loads(r.stdout)
check("contract: {kinds:{kind:{mode,chain,sev,fix_label,proof,info,next}}, ops:{op:{executor,wait_s,checks,destructive}}}", set(c) == {"kinds", "ops"} and all(set(v) == {"mode", "chain", "sev", "fix_label", "proof", "info", "next"} for v in c["kinds"].values())
      and all(set(v) == {"executor", "wait_s", "checks", "destructive"} for v in c["ops"].values()) and set(c["kinds"]) == set(w.KINDS) and set(c["ops"]) == set(w.OPS), r.stdout[:200])
check("contract: the extension's op list equals the watcher's ext ops", sorted(o for o, v in c["ops"].items() if v["executor"] == "ext") == ["fresh", "interrupt", "relaunch"])


# ---- 6. one scenario per kind: raised -> `can` ok for a chain op -> act (watch ops) -> the cause goes away -> `verify` says gone ----
GE = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")


def mk(n):
    d = DEV / n; subprocess.run(["git", "init", "-q", "-b", "main", str(d)], env=GE); (d / "a.txt").write_text("x\n")
    subprocess.run(["git", "-C", str(d), "add", "-A"], env=GE); subprocess.run(["git", "-C", str(d), "commit", "-q", "-m", "i"], env=GE)


def transcript(name, sid, quiet_s, lines=(), agents=None, size=0):
    d = HOME / ".claude/projects" / re.sub(r"[^A-Za-z0-9]", "-", str(DEV / name)); d.mkdir(parents=True, exist_ok=True)
    for old in d.glob("*.jsonl"):
        old.unlink()
    shutil.rmtree(d / sid, ignore_errors=True)
    f = d / f"{sid}.jsonl"; f.write_text("\n".join(lines) + ("\n" if lines else ""))
    if size:
        with open(f, "ab") as fh:
            fh.truncate(size)
    os.utime(f, (T0 - quiet_s, T0 - quiet_s))
    if agents:
        (d / sid / "subagents").mkdir(parents=True, exist_ok=True)
        for aid, q in agents.items():
            g = d / sid / "subagents" / f"agent-{aid}.jsonl"; g.write_text("{}\n"); os.utime(g, (T0 - q, T0 - q))
    return f


def iso(ago):
    return datetime.datetime.fromtimestamp(T0 - ago, datetime.timezone.utc).isoformat().replace("+00:00", "Z")


CL = lambda name, pid, et="05:00:00": f"{pid} 1 {et} 0.1 300000 /Users/x/.local/bin/claude --continue --name {name}"
VM = "120 1 3-00:00:00 1.0 6873424 /System/Library/Frameworks/Virtualization.framework/x/com.apple.Virtualization.VirtualMachine.xpc/Contents/MacOS/com.apple.Virtualization.VirtualMachine"
HA = "121 1 3-00:00:00 0.3 83648 /opt/homebrew/bin/limactl hostagent --pidfile /Users/x/.colima/_lima/colima/ha.pid"
rows_now = []


def world(rows, st=None, files=None, host_busy=False, docker=""):
    """Write a whole fake machine (no scan yet)."""
    for d in ("v1/cr", "v1/autopilot"):                                  # P5c: change-request logs and autopilot state are per scenario
        shutil.rmtree(STATE / d, ignore_errors=True)
    for f in list(STATE.glob("*")):
        if f.is_file():
            f.unlink()
    (T / "kills.log").unlink(missing_ok=True); (W / "config/watch.json").write_text("{}"); (T / "colima.txt").write_text("running"); (T / "docker.txt").write_text(docker)
    (T / "host.json").write_text(json.dumps({"swap_pct": 90 if host_busy else 10, "free_pct": 60, "load": 1.0, "cores": 8}))
    (STATE / "watch-state.json").write_text(json.dumps({"host_bad": 9 if host_busy else 0}))
    set_rows(rows)
    for name, state in (st or {}).items():
        (STATE / f"{name}.json").write_text(json.dumps({"project": name, "state": state, "ts": T0 - 60}))
    for k, v in (files or {}).items():
        (STATE / k).write_text(v)


def set_rows(rows):
    global rows_now
    rows_now = list(rows); (T / "ps.txt").write_text("\n".join(rows) + "\n")


def drop_row(pid):
    set_rows([r for r in rows_now if not r.startswith(f"{pid} ")])


def scan(n=2, dry=False):
    for _ in range(n):
        subprocess.run([str(ws / "bin/shipm-watch"), "scan", *(["--dry"] if dry else [])], capture_output=True, text=True, env=ENV)
    return json.loads((STATE / "health.json").read_text())


def cli(*a):
    r = subprocess.run([str(ws / "bin/shipm-watch"), *a], capture_output=True, text=True, env=ENV)
    try:
        return json.loads(r.stdout)
    except Exception:
        return {"_raw": r.stdout + r.stderr}


for n in ("p1", "p2", "p3", "p4", "p5", "p6", "p7", "p8"):
    mk(n)
items = []
SCEN = {}


def scenario(kind, **kw):
    def deco(fn):
        SCEN[kind] = (fn, kw); return fn
    return deco


@scenario("frozen_chat")
def _():
    transcript("p1", "s1", 25 * 60); world([CL("p1", 100)], {"p1": "working"}); return lambda: (STATE / "p1.json").write_text(json.dumps({"project": "p1", "state": "idle", "ts": T0}))


@scenario("frozen_agent")
def _():
    transcript("p5", "s5", 60, agents={"a1": 25 * 60}); world([CL("p5", 106)], {"p5": "working"}, {"p5.agents.json": json.dumps({"a1": {"type": "backend-engineer", "started": T0 - 3000}})}); return lambda: (STATE / "p5.agents.json").write_text("{}")


@scenario("job_frozen")
def _():
    transcript("p4", "s4", 3 * 3600); world([CL("p4", 103), "105 103 03:00:00 0.0 10000 sleep 123456"], {"p4": "done"}); return lambda: drop_row(105)


@scenario("waiting_job")
def _():
    transcript("p4", "s4", 3 * 3600); world([CL("p4", 103), "104 103 00:40:00 0.0 100000 sleep 9999"], {"p4": "done"}); return lambda: drop_row(104)


@scenario("context_full")
def _():
    transcript("p2", "s2", 120, lines=[json.dumps({"timestamp": iso(300), "text": "Prompt is too long"})]); world([CL("p2", 101)], {"p2": "working"})
    return lambda: set_rows([CL("p2", 131, "00:00:30")])           # Fresh chat: a newer chat process; the old file is no longer written


@scenario("session_large")
def _():
    transcript("p3", "s3", 100, size=90 * 1048576); world([CL("p3", 102)], {"p3": "done"}); return lambda: set_rows([CL("p3", 132, "00:00:30")])


@scenario("duplicate")
def _():
    transcript("p6", "s6", 60); world([CL("p6", 107), "700 1 02-03:00:00 0.0 150000 /Users/x/Library/Application Support/Claude/claude-code/2.1/x/claude.app/Contents/MacOS/claude --resume=s6 --model=opus"], {"p6": "done"}); return lambda: drop_row(700)


@scenario("duplicate_tabs")
def _():
    transcript("p6", "s6", 60); world([CL("p6", 107, "05:00:00"), CL("p6", 108, "01:00:00")], {"p6": "done"}); return lambda: drop_row(107)


@scenario("playwright_dup")
def _():
    transcript("p6", "s6", 60); world([CL("p6", 107), "109 107 00:30:00 0.0 100000 node /x/.bin/playwright-mcp", "110 107 00:20:00 0.0 100000 node /x/.bin/playwright-mcp"], {"p6": "done"}); return lambda: drop_row(109)


CHR = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome --headless=new --remote-debugging-port=9333 --user-data-dir=%s"
CHH = "/Applications/Google Chrome.app/Contents/Frameworks/Google Chrome Helper --type=renderer --user-data-dir=%s"
TMPPROF = "/private/var/folders/zz/T/shipmiracle-chrome-abc123"


@scenario("stray_browser")
def _():
    world([f"300 1 01:00:00 0.0 100000 {CHR % TMPPROF}", f"301 300 01:00:00 0.0 100000 {CHH % TMPPROF}"]); return lambda: set_rows([])


@scenario("stray_testrun")
def _():
    world(["310 1 00:30:00 0.0 100000 /usr/bin/python3 %s/bin/test-all" % W]); (T / "lsof.json").write_text(json.dumps({"310": str(DEV / "p1")})); return lambda: set_rows([])


@scenario("idle_session")
def _():
    transcript("p7", "s7", 30 * 3600); world(["111 1 05-00:00:00 0.1 600000 /Users/x/.local/bin/claude --continue --name p7"], {"p7": "done"}); return lambda: drop_row(111)


@scenario("vm_idle")
def _():
    world([VM, HA]); return lambda: set_rows([])


@scenario("host_busy")
def _():
    world([VM, HA], host_busy=True); return lambda: (set_rows([]), (T / "host.json").write_text(json.dumps({"swap_pct": 10, "free_pct": 60, "load": 1.0, "cores": 8})))


@scenario("dead_agent", dry=True)
def _():
    transcript("p8", "s8", 100); world([CL("p8", 112)], {"p8": "working"}, {"p8.agents.json": json.dumps({"dead1": {"type": "qa-engineer", "started": T0 - 99999}})}); return lambda: None


@scenario("orphan", dry=True)
def _():
    world(["113 1 00:40:00 0.0 10000 sleep 7777"], files={"lineage.json": json.dumps({"113": {"start": T0 - 2400, "cmd": "sleep 7777", "claude": 900, "claude_start": T0 - 9000, "project": "p8", "seen": T0 - 100}})}); return lambda: drop_row(113)


@scenario("leftover", auto_off=True)
def _():
    world(["113 1 00:40:00 0.0 10000 sleep 7777"], files={"lineage.json": json.dumps({"113": {"start": T0 - 2400, "cmd": "sleep 7777", "claude": 900, "claude_start": T0 - 9000, "project": "p8", "seen": T0 - 100}}, ), "auto-clean.off": ""}); return lambda: drop_row(113)


@scenario("limit")
def _():
    transcript("p1", "s1", 60); world([CL("p1", 100)], {"p1": "working"}, {"p1.limit.json": json.dumps({"until": T0 + 5400, "ts": T0 - 100})}); return None


@scenario("plan_approval")
def _():
    transcript("p1", "s1", 60); world([CL("p1", 100)], {"p1": "working"}, {"plan-pending.s1": "1"}); os.utime(STATE / "plan-pending.s1", (T0 - 600, T0 - 600)); return None


@scenario("waiting_you")
def _():
    transcript("p1", "s1", 60); world([CL("p1", 100)], {"p1": "needs-input"}); return None


@scenario("api_trouble")
def _():
    transcript("p1", "s1", 120, lines=[json.dumps({"type": "system", "timestamp": iso(60 + i), "subtype": "api_error", "level": "error"}) for i in range(4)]); world([CL("p1", 100)], {"p1": "working"}); return None


# ---- P5c / P6: change-request and autopilot kinds (the CR log is read through shipmiracle.playbook.store, the run state through shipmiracle.autopilot.state) ----
sys.path.insert(0, str(ws))
from shipmiracle import projects as shipmiracle_projects  # noqa: E402
from shipmiracle.autopilot import state as shipmiracle_ap  # noqa: E402
from shipmiracle.playbook import store as shipmiracle_store  # noqa: E402


def crlog(name, last_ago, block=None, hold=False, status="open"):
    """A change-request log for project `name`: CR-001 opened 3 h ago, last line `last_ago` seconds before now."""
    t0 = T0 - 3 * 3600
    lines = [{"ts": t0, "cr": "CR-001", "op": "open", "stage": None, "by": "owner", "sid8": None,
              "ev": {"kind": "cli_open", "ref": None, "data": {"title": "RTL fix", "lane": "full", "status": status, "base": None, "skip": [], "opened": t0}}}]
    if block:
        lines.append({"ts": T0 - last_ago, "cr": "CR-001", "op": "block", "stage": "verify", "by": "engine", "sid8": None, "ev": {"kind": "engine", "ref": None, "data": {"reason": block}}})
    elif hold:
        lines.append({"ts": T0 - last_ago, "cr": "CR-001", "op": "hold", "stage": None, "by": "engine", "sid8": None, "ev": {"kind": "hold", "ref": None, "data": {}}})
    else:
        lines.append({"ts": T0 - last_ago, "cr": "CR-001", "op": "report", "stage": None, "by": "engine", "sid8": None, "ev": {"kind": "engine", "ref": None, "data": {"path": "x"}}})
    shipmiracle_store.append(DEV / name, lines, base=STATE)


def aplog(name, **kw):
    pid = shipmiracle_projects.project_id(DEV / name)
    shipmiracle_ap.update(pid, lambda cur: dict(shipmiracle_ap.blank("a" * 64, T0 - 600), **kw), base=STATE)


@scenario("stage_stuck")
def _():
    transcript("p1", "s1", 120); world([CL("p1", 100)], {"p1": "working"}); crlog("p1", 40 * 60)
    return lambda: (STATE / "p1.json").write_text(json.dumps({"project": "p1", "state": "idle", "ts": T0}))


@scenario("verify_failed_twice")
def _():
    transcript("p2", "s2", 600); world([CL("p2", 101)], {"p2": "done"}); crlog("p2", 300, block="verify_twice"); return None


@scenario("autopilot_paused")
def _():
    transcript("p3", "s3", 600); world([CL("p3", 102)], {"p3": "done"}); crlog("p3", 300, hold=True); return None


@scenario("cr_orphan")
def _():
    transcript("p4", "s4", 30 * 3600); world([], {"p4": "done"}); crlog("p4", 30 * 3600); return None


@scenario("autopilot_stopped")
def _():
    transcript("p5", "s5", 600); world([CL("p5", 103)], {"p5": "done"})
    aplog("p5", state="paused", started=T0 - 500, expires=T0 + 9000, stop={"id": "H-1a2b3c", "rule": "H1", "ts": T0 - 100, "text": "git push --force refused"}); return None


@scenario("budget_reached")
def _():
    transcript("p6", "s6", 600); world([CL("p6", 104)], {"p6": "done"}); aplog("p6", state="ended", ended_reason="budget", ended_ts=T0 - 300, started=T0 - 5000, expires=T0 + 100); return None


def apevents(name, rows):
    """rows: (kind, seconds_ago, data). Written straight into <state>/v1/events.jsonl (the watcher's clock is SHIPMIRACLE_NOW=T0, not the wall clock)."""
    pid = shipmiracle_projects.project_id(DEV / name)
    f = STATE / "v1/events.jsonl"; f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("".join(json.dumps({"v": 1, "ts": T0 - ago, "kind": k, "project": pid, "src": "autopilot", "data": d}) + "\n" for k, ago, d in rows))


@scenario("autopilot_ended_time")
def _():
    transcript("p7", "s7", 600); world([CL("p7", 106)], {"p7": "done"}); aplog("p7", state="ended", ended_reason="time", ended_ts=T0 - 300, started=T0 - 9000, expires=T0 - 100); return None


@scenario("merge_waiting")
def _():
    transcript("p8", "s8", 600); world([CL("p8", 107)], {"p8": "done"}); aplog("p8", state="running", started=T0 - 500, expires=T0 + 9000)
    apevents("p8", [("autopilot.merge_waiting", 120, {"cr": "CR-012", "why": "the main checkout has uncommitted changes on files the branch touches (a.py)"})]); return None


for kind, (fn, kw) in SCEN.items():
    shutil.rmtree(HOME / ".claude", ignore_errors=True)
    resolve = fn()
    if kw.get("auto_off"):
        pass
    h = scan(2, dry=kw.get("dry", False)); its = [i for i in h["items"] if i["kind"] == kind]
    items += its
    check(f"scenario {kind}: raised", bool(its), str([i["kind"] for i in h["items"]]))
    if not its:
        continue
    it = its[0]
    if it["mode"] in ("fix", "auto"):
        oks = [op for op in it["chain"] if cli("can", op, it["id"]).get("ok")]
        check(f"scenario {kind}: `can` is ok for at least one chain op ({it['chain']})", bool(oks), str({op: cli('can', op, it['id']) for op in it["chain"]}))
        if oks:
            op = oks[0]; c = cli("can", op, it["id"])
            check(f"scenario {kind}: `can` reports project, kind and working from the fresh item", c.get("kind") == kind and c.get("project") == it["project"] and isinstance(c.get("working"), bool), str(c))
            if w.OPS[op]["executor"] == "watch":
                a = cli("act", op, it["id"]); check(f"scenario {kind}: act {op} succeeds", a.get("ok") is True, str(a))
            if resolve:
                resolve()
            v = cli("verify", it["id"])
            check(f"scenario {kind}: after the step verify says gone", v.get("gone") is True and v.get("checked") is True, str(v)[:300])
    else:
        check(f"scenario {kind}: an info/wait item is not fixable and offers no op", not it["actions"] and not it["fixable_now"])

seen_kinds = {i["kind"] for i in items}
check("EVERY registered kind (except watcher_bug) was raised by a scenario", not (set(w.KINDS) - seen_kinds - {"watcher_bug"}), str(set(w.KINDS) - seen_kinds - {"watcher_bug"}))
check("every fix/auto kind has a scenario that is fixable (a kind whose chain can never apply fails)", all(k in SCEN for k, v in w.KINDS.items() if v["mode"] in ("fix", "auto")))
# P5c: precedence, silence and the exact texts
world([CL("p1", 100)], {"p1": "working"}); transcript("p1", "s1", 25 * 60); crlog("p1", 40 * 60)
hh = scan(2)
check("frozen_chat wins: a frozen working chat does not also raise stage_stuck", any(i["kind"] == "frozen_chat" for i in hh["items"]) and not any(i["kind"] == "stage_stuck" for i in hh["items"]), str([i["kind"] for i in hh["items"]]))
world([CL("p1", 100)], {"p1": "working"}); transcript("p1", "s1", 120); crlog("p1", 10 * 60)
check("stage_stuck is silent when the CR moved less than 30 min ago", not any(i["kind"] == "stage_stuck" for i in scan(2)["items"]))
world([CL("p1", 100)], {"p1": "done"}); transcript("p1", "s1", 120); crlog("p1", 40 * 60)
check("stage_stuck is silent when the chat is not working", not any(i["kind"] == "stage_stuck" for i in scan(2)["items"]))
world([CL("p3", 102)], {"p3": "working"}); transcript("p3", "s3", 120); crlog("p3", 40 * 60, hold=True)
check("a held CR (manual autopilot) is waiting for the owner, never stuck", not any(i["kind"] in ("stage_stuck", "autopilot_paused") for i in scan(2)["items"]))
world([], {"p4": "done"}); transcript("p4", "s4", 2 * 3600); crlog("p4", 2 * 3600)
check("cr_orphan is silent when the newest transcript is under 24 h old", not any(i["kind"] == "cr_orphan" for i in scan(2)["items"]))
world([CL("p4", 105)], {"p4": "done"}); transcript("p4", "s4", 30 * 3600); crlog("p4", 30 * 3600)
check("cr_orphan is silent while a chat process of the project exists", not any(i["kind"] == "cr_orphan" for i in scan(2)["items"]))
world([], {"p4": "done"}); transcript("p4", "s4", 30 * 3600)
check("no CR log and no autopilot state file: none of the six kinds appears", not {i["kind"] for i in scan(2)["items"]} & {"stage_stuck", "verify_failed_twice", "autopilot_paused", "cr_orphan", "autopilot_stopped", "budget_reached", "autopilot_ended_time", "merge_waiting"})
world([CL("p5", 103)], {"p5": "done"}); transcript("p5", "s5", 600)
aplog("p5", state="paused", started=T0 - 500, expires=T0 + 9000, stop={"id": "H-1a2b3c", "rule": "H1", "ts": T0 - 100, "text": "x"})
st_item = [i for i in scan(2)["items"] if i["kind"] == "autopilot_stopped"]
check("autopilot_stopped: grey wait item whose next text carries the real stop id", len(st_item) == 1 and st_item[0]["severity"] == "info" and "allow: H-1a2b3c" in st_item[0]["next"] and "H-xxxxxx" not in st_item[0]["next"], str(st_item)[:300])
world([CL("p6", 104)], {"p6": "done"}); transcript("p6", "s6", 600)
aplog("p6", state="ended", ended_reason="budget", ended_ts=T0 - 3 * 86400, started=T0 - 5 * 86400, expires=T0 - 4 * 86400)
check("budget_reached expires 24 h after the run ended", not any(i["kind"] == "budget_reached" for i in scan(2)["items"]))
(STATE / "v1/autopilot").mkdir(parents=True, exist_ok=True); (STATE / f"v1/autopilot/{shipmiracle_projects.project_id(DEV / 'p6')}.json").write_text("{not json")
check("a damaged autopilot state file is ignored (no item, no crash)", not any(i["kind"] in ("autopilot_stopped", "budget_reached") for i in scan(2)["items"]))
(STATE / "v1/autopilot").mkdir(parents=True, exist_ok=True)
world([CL("p8", 107)], {"p8": "done"}); transcript("p8", "s8", 600); aplog("p8", state="running", started=T0 - 500, expires=T0 + 9000)
apevents("p8", [("autopilot.merge_waiting", 120, {"cr": "CR-012", "why": "w"}), ("autopilot.merged", 60, {"cr": "CR-012"})])
check("merge_waiting is silent once the CR was merged afterwards", not any(i["kind"] == "merge_waiting" for i in scan(2)["items"]))
apevents("p8", [("autopilot.merge_waiting", 7 * 3600, {"cr": "CR-012", "why": "w"})])
check("merge_waiting expires after 6 h", not any(i["kind"] == "merge_waiting" for i in scan(2)["items"]))
apevents("p8", [("autopilot.merge_waiting", 120, {"cr": "CR-012", "why": "w"})])
mw = [i for i in scan(2)["items"] if i["kind"] == "merge_waiting"]
check("merge_waiting: one grey wait item with its own next text and the CR id", len(mw) == 1 and mw[0]["severity"] == "info" and mw[0]["mode"] == "wait" and mw[0]["actions"] == [] and mw[0]["cr"] == "CR-012" and mw[0]["next"].startswith("Close the chat"), str(mw)[:300])
(STATE / "v1/events.jsonl").write_text("{not json\n")
check("a damaged events file raises no merge_waiting and does not crash the scan", not any(i["kind"] == "merge_waiting" for i in scan(2)["items"]))
world([CL("p7", 106)], {"p7": "done"}); transcript("p7", "s7", 600)
aplog("p7", state="ended", ended_reason="time", ended_ts=T0 - 3 * 86400, started=T0 - 5 * 86400, expires=T0 - 4 * 86400)
check("autopilot_ended_time expires 24 h after the run ended", not any(i["kind"] == "autopilot_ended_time" for i in scan(2)["items"]))

# 21 Oct 2026: stray_browser / stray_testrun precision (temp-only browsers, orphaned and old test runs only)
(T / "lsof.json").write_text("{}")
NONTEMP = "/Users/someone/chrome-debug"
world([f"300 1 01:00:00 0.0 100000 {CHR % NONTEMP}", f"302 1 00:05:00 0.0 100000 {CHR % TMPPROF}", "303 1 01:00:00 0.0 100000 /Applications/Google Chrome.app/Contents/MacOS/Google Chrome", f"304 1 02:00:00 0.0 100000 {CHR % '/tmp/../Users/someone/p'}"])
sb = [i for i in scan(2)["items"] if i["kind"] == "stray_browser"]
byp = {i["pid"]: i for i in sb}
check("stray_browser: a non-temp profile is listed grey and never fixable (can says no)", 300 in byp and byp[300]["mode"] == "info" and byp[300]["chain"] == [] and not byp[300]["fixable_now"], str(sb)[:300])
check("stray_browser: a '..' path that resolves outside the temp roots counts as non-temp", 304 in byp and byp[304]["mode"] == "info", str(sorted(byp)))
check("stray_browser: younger than 30 min, or a normal Chrome without automation flags: not listed", 302 not in byp and 303 not in byp, str(sorted(byp)))
check("stray_browser: act end-browser on a non-temp item is refused and nothing is killed", cli("act", "end-browser", byp[300]["id"]).get("ok") is False and not (T / "kills.log").exists())
world([f"300 1 01:00:00 0.0 100000 {CHR % TMPPROF}", f"301 300 01:00:00 0.0 100000 {CHH % TMPPROF}", f"305 300 01:00:00 0.0 100000 {CHH % NONTEMP}"])
sb = [i for i in scan(2)["items"] if i["kind"] == "stray_browser"]
check("stray_browser: one item for the main process (helpers are not items); temp profile -> fix, fixable now", len(sb) == 1 and sb[0]["pid"] == 300 and sb[0]["mode"] == "fix" and sb[0]["fixable_now"] and sb[0]["chain"] == ["end-browser"], str(sb)[:300])
a = cli("act", "end-browser", sb[0]["id"]); kl = (T / "kills.log").read_text() if (T / "kills.log").exists() else ""
check("stray_browser: Fix ends the main process and the helper with the temp profile, NOT a helper with another profile", a.get("ok") is True and "300 end-browser" in kl and "301 end-browser" in kl and "305" not in kl, (a, kl))
# test runs
LS = lambda **k: (T / "lsof.json").write_text(json.dumps({str(a): str(b) for a, b in k.items()}))
world(["310 1 00:30:00 0.0 100000 /usr/bin/python3 %s/bin/test-all" % W, "311 1 00:05:00 0.0 100000 %s/bin/test-all" % W, "312 50 00:40:00 0.0 100000 %s/bin/test-all" % W,
       "50 1 05:00:00 0.0 100000 -zsh", "313 1 00:40:00 0.0 100000 /usr/bin/python3 %s/bin/test-all" % W, "314 1 00:40:00 0.0 100000 /usr/bin/python3 %s/bin/not-test-all" % W, "315 999 00:40:00 0.0 100000 %s/bin/test-all" % W,
       "316 1 00:40:00 0.0 100000 /usr/bin/python3 %s/.worktrees/%s/wt1/bin/test-all" % (DEV, W.name),
       "317 1 00:40:00 0.0 100000 /usr/bin/python3 %s/p1/bin/test-all" % DEV, "318 1 00:40:00 0.0 100000 /usr/bin/python3 /opt/other/bin/test-all"])   # 317/318: a project's own and a stranger's test-all (L5: never ours)
LS(**{"310": DEV / "p1", "311": DEV / "p1", "312": DEV / "p1", "313": "/opt/other", "315": DEV / "p1", "316": DEV / "p1", "317": DEV / "p1", "318": "/opt/other"})
st = {i["pid"]: i for i in scan(2)["items"] if i["kind"] == "stray_testrun"}
check("stray_testrun: raised for an old test-all whose parent is pid 1 or missing; not for a young one, a live parent, or another script", set(st) == {310, 313, 315, 316}, str(sorted(st)))
check("stray_testrun: inside a known workspace -> fix; outside -> grey list only", st[310]["mode"] == "fix" and st[310]["fixable_now"] and st[313]["mode"] == "info" and not st[313]["fixable_now"], str((st[310]["mode"], st[313]["mode"])))
a = cli("act", "end-testrun", st[310]["id"]); kl = (T / "kills.log").read_text()
check("stray_testrun: Fix signals ONLY that process", a.get("ok") is True and kl.strip().splitlines()[-1] == "310 end-testrun" and "312" not in kl and "50 " not in kl, (a, kl))
check("stray_testrun: act on the outside-workspace item is refused", cli("act", "end-testrun", st[313]["id"]).get("ok") is False)
# the source: no kill path for these two kinds ever uses SIGKILL or touches a process not selected by the temp/orphan rules
SRC_NOW = (ws / "bin/shipm-watch").read_text()
seg = SRC_NOW[SRC_NOW.index('if op == "end-testrun":'):SRC_NOW.index('if op == "stop-colima":')]
check("end-testrun sends SIGTERM only (no SIGKILL in its code path)", "SIGTERM" in seg and "SIGKILL" not in seg)
KX = w.KINDS
check("exact next texts: merge_waiting / autopilot_ended_time are grey wait kinds without a button",
      all(KX[k]["mode"] == "wait" and KX[k]["sev"] == "info" and KX[k]["chain"] == [] and KX[k]["next"] for k in ("merge_waiting", "autopilot_ended_time")) and KX["merge_waiting"]["next"] != KX["autopilot_ended_time"]["next"])
check("exact texts: stage_stuck / verify_failed_twice / autopilot_paused / budget_reached / cr_orphan (spec p5 section 7)",
      KX["stage_stuck"]["next"] == "Open the chat, press Esc, then ask the lead which step of the CR is stuck and why." and KX["stage_stuck"]["chain"] == ["interrupt"]
      and KX["verify_failed_twice"]["next"] == "Open the chat and choose: change the plan, fix it again, or stop the CR (shipm cr abandon in a terminal)."
      and KX["autopilot_paused"]["next"] == "Open the chat and type next to let the manual autopilot run the following stage."
      and KX["budget_reached"]["next"] == "Raise the charter budget or go back to guided."
      and KX["cr_orphan"]["next"] == "Open the project's chat from its card and type /feature with no text to resume the CR."
      and KX["autopilot_stopped"]["next"] == "Open the auto chat: type allow: H-xxxxxx to allow that one action, or charter: off."
      and all(KX[k]["mode"] == "wait" and KX[k]["sev"] == "info" for k in ("verify_failed_twice", "autopilot_paused", "budget_reached", "autopilot_stopped")) and KX["cr_orphan"]["mode"] == "info")
FIELDS = {"id", "kind", "severity", "project", "title", "why", "since", "actions", "pid", "start", "mode", "chain", "fix_label", "proof", "info_only", "can", "fixable_now", "why_not", "verify_text", "next", "recommended", "reco_why", "impact", "safe", "destructive", "destructive_chain", "chat_start"}
check("every item has every contract field", all(FIELDS <= set(i) for i in items), str([(i["kind"], FIELDS - set(i)) for i in items if not FIELDS <= set(i)]))
fx = [i for i in items if i["mode"] in ("fix", "auto")]
check("no fix/auto item has an empty recommended (no 'your call')", fx and all(i["recommended"] == i["chain"][0] and i["reco_why"] for i in fx), str([(i["kind"], i["recommended"]) for i in fx if not i["recommended"]]))
check("can has exactly the item's actions; impact, safe and destructive too", all(set(i["can"]) == set(i["actions"]) == set(i["impact"]) == set(i["safe"]) == set(i["destructive"]) and all(isinstance(v, list) and len(v) == 2 for v in i["can"].values()) for i in items))
check("destructive_chain is true exactly when a chain op is destructive", all(i["destructive_chain"] == any(w.OPS[o]["destructive"] for o in i["chain"]) for i in items))
check("an info/wait item has no chain, is info_only, grey and not fixable", all(i["chain"] == [] and i["info_only"] and i["severity"] == "info" and not i["fixable_now"] for i in items if i["mode"] in ("info", "wait")))
check("a fix item that is not fixable now says why", all(i["why_not"] for i in items if i["mode"] == "fix" and not i["fixable_now"]))
check("a fix item's severity is red or amber; every action in actions is a registry op", all(i["severity"] in ("red", "amber") for i in fx) and all(o in w.OPS for i in items for o in i["actions"]))
world([CL("p1", 100)], {"p1": "needs-input"}); transcript("p1", "s1", 60)
check("a tidy scan's counts only count fix/auto items (a waiting chat is grey)", scan(2)["counts"] == {"red": 0, "amber": 0})
# the item list is appended in exactly one place
src_items = [m.start() for m in re.finditer(r"self\.items\.append\(", SRC)]
check("self.items.append appears exactly once, inside add()", len(src_items) == 1 and SRC.index("    def add(") < src_items[0] < SRC.index("    def impact("), str(src_items))

# ---- 7. the panel never says "your call" ----
panel = (ws / "vscode-ext/shipmiracle-panel/panel.js").read_text()
check('panel.js does not contain "your call"', "your call" not in panel.lower())

print("\nFAILED:" if fails else "\nALL PASS", fails)
sys.exit(1 if fails else 0)
