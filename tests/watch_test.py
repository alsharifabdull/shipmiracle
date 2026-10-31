"""bin/shipm-watch against fake process tables, fake transcripts and a fake clock. Nothing real is touched. Run: python3 tests/watch_test.py"""
import shutil
import datetime, json, os, pathlib, re, subprocess, sys, tempfile, time
ws = pathlib.Path(__file__).resolve().parent.parent
T0 = 1_800_000_000
T = pathlib.Path(tempfile.mkdtemp())
HOME, DEV, STATE, W, TMP = T / "home", T / "home/Developer", T / "state", T / "ws", T / "tasks"
for d in (DEV, STATE, W / "config", TMP):
    d.mkdir(parents=True, exist_ok=True)
GE = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
ENV = dict(GE, SHIPMIRACLE_TEST="1", SHIPMIRACLE_CONFIG=str(HOME / ".config/shipmiracle"), SHIPMIRACLE_HOME=str(HOME), SHIPMIRACLE_DEV=str(DEV), SHIPMIRACLE_STATE=str(STATE), SHIPMIRACLE_WS=str(W), SHIPMIRACLE_NOW=str(T0), SHIPMIRACLE_PS=str(T / "ps.txt"), SHIPMIRACLE_LSOF=str(T / "lsof.json"),
           SHIPMIRACLE_HOST=str(T / "host.json"), SHIPMIRACLE_KILL_LOG=str(T / "kills.log"), SHIPMIRACLE_TMP=str(TMP))
(T / "lsof.json").write_text("{}")
fails = []
AW_SRC = str(ws / "bin/shipm-watch")


def check(n, c, info=""):
    print(("PASS " if c else "FAIL ") + n, "" if c else info)
    if not c:
        fails.append(n)


def mkproj(name):
    d = DEV / name; subprocess.run(["git", "init", "-q", "-b", "main", str(d)], env=GE); (d / "a.txt").write_text("x\n")
    subprocess.run(["git", "-C", str(d), "add", "-A"], env=GE); subprocess.run(["git", "-C", str(d), "commit", "-q", "-m", "i"], env=GE); return d


def transcript(name, sid, quiet_s, lines=(), agents=None, size=0):
    d = HOME / ".claude/projects" / re.sub(r"[^A-Za-z0-9]", "-", str(DEV / name)); d.mkdir(parents=True, exist_ok=True)
    for old in d.glob("*.jsonl"):
        old.unlink()
    shutil.rmtree(d / sid, ignore_errors=True)  # sub-agent files of an earlier case would look like fresh activity
    f = d / f"{sid}.jsonl"; f.write_text("\n".join(lines) + ("\n" if lines else ""));
    if size:
        with open(f, "ab") as fh:
            fh.truncate(size)
    os.utime(f, (T0 - quiet_s, T0 - quiet_s))
    sub = d / sid / "subagents"
    if agents:
        sub.mkdir(parents=True, exist_ok=True)
        for aid, q in agents.items():
            g = sub / f"agent-{aid}.jsonl"; g.write_text("{}\n"); os.utime(g, (T0 - q, T0 - q))
    return f


def iso(ago):
    return datetime.datetime.fromtimestamp(T0 - ago, datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def ps(*rows):
    (T / "ps.txt").write_text("\n".join(f"{p} {pp} {et} {cpu} {rss} {cmd}" for p, pp, et, cpu, rss, cmd in rows) + "\n")


def state(name, st="working", age=60, **kw):
    (STATE / f"{name}.json").write_text(json.dumps({"project": name, "state": st, "ts": T0 - age, **kw}))


def reset():
    for f in list(STATE.glob("*")) + list(TMP.rglob("*")):
        if f.is_file(): f.unlink()
    (T / "kills.log").unlink(missing_ok=True); (T / "host.json").write_text(json.dumps({"swap_pct": 10, "free_pct": 60, "load": 1.0, "cores": 8}))
    (W / "config/watch.json").write_text("{}")


def scan(n=2, *args):
    out = None
    for _ in range(n):
        out = subprocess.run([str(ws / "bin/shipm-watch"), "scan", *args], capture_output=True, text=True, env=ENV)
        if out.returncode != 0:
            print(out.stderr[-400:])
    return json.loads((STATE / "health.json").read_text())


def kinds(h, project=None):
    return sorted(i["kind"] for i in h["items"] if project is None or i["project"] == project)


CL = lambda name, pid=100: (pid, 1, "05:00:00", 0.1, 300000, f"/Users/x/.local/bin/claude --continue --name {name} --remote-control {name}")
for n in ("p1", "p2", "ideas"):
    mkproj(n)

# ---- chats: frozen, busy, waits ----
reset(); transcript("p1", "s1", 25 * 60); state("p1", "working"); ps(CL("p1"))
h = scan(1); check("a frozen chat is not shown after one scan (needs 2 in a row)", "frozen_chat" not in kinds(h))
h = scan(1); fi = [i for i in h["items"] if i["kind"] == "frozen_chat"]
check("working + quiet 25 min + nothing busy -> frozen chat (red), Fix chain interrupt -> relaunch, Fresh chat secondary; 'Ask to report' is gone (D4)", len(fi) == 1 and fi[0]["severity"] == "red" and fi[0]["chain"] == ["interrupt", "relaunch"] and fi[0]["actions"] == ["interrupt", "relaunch", "fresh"] and fi[0]["recommended"] == "interrupt" and fi[0]["mode"] == "fix" and fi[0]["fixable_now"], kinds(h))
check("the red count on the Health tab is 1", h["counts"]["red"] == 1)
check("nothing is ever killed for a frozen chat", not (T / "kills.log").exists())
reset(); transcript("p1", "s1", 25 * 60); state("p1", "working"); ps(CL("p1"), (101, 100, "00:25:00", 62.0, 800000, "node /x/node_modules/.bin/tsx scripts/bench/run.mts"))
check("a busy child (benchmark using CPU) means the chat is not frozen", "frozen_chat" not in kinds(scan()))
reset(); transcript("p1", "s1", 25 * 60); state("p1", "needs-input", message="Approve?"); ps(CL("p1")); h = scan()
check("waiting for you is shown as that, not as frozen", "waiting_you" in kinds(h) and "frozen_chat" not in kinds(h) and h["counts"]["red"] == 0)
reset(); transcript("p1", "s1", 25 * 60); state("p1", "working"); (STATE / "plan-pending.s1").write_text("1"); os.utime(STATE / "plan-pending.s1", (T0 - 600, T0 - 600)); ps(CL("p1")); h = scan()
check("waiting for plan approval is not frozen", "plan_approval" in kinds(h) and "frozen_chat" not in kinds(h))
reset(); transcript("p1", "s1", 25 * 60); state("p1", "working"); (STATE / "p1.limit.json").write_text(json.dumps({"until": T0 + 5400, "ts": T0 - 100})); ps(CL("p1")); h = scan()
li = [i for i in h["items"] if i["kind"] == "limit"]; check("a usage-limit wait shows the reset time and is not frozen", li and "usage limit until" in li[0]["title"] and "frozen_chat" not in kinds(h))
reset(); transcript("p1", "s1", 120, lines=[json.dumps({"type": "system", "timestamp": iso(60 + i), "subtype": "api_error", "level": "error"}) for i in range(4)]); state("p1", "working"); ps(CL("p1")); h = scan()
check("4 API errors in 10 minutes -> API trouble (amber), not frozen", "api_trouble" in kinds(h) and "frozen_chat" not in kinds(h))
reset(); transcript("p1", "s1", 120, lines=[json.dumps({"timestamp": iso(300), "text": "Prompt is too long"})]); state("p1", "working"); ps(CL("p1")); h = scan()
ci = [i for i in h["items"] if i["kind"] == "context_full"]; check("'Prompt is too long' -> context full with a Fresh chat action", ci and "fresh" in ci[0]["actions"])
reset(); transcript("p1", "s1", 60, size=90 * 1048576); state("p1", "done"); ps(CL("p1")); h = scan()
sl = [i for i in h["items"] if i["kind"] == "session_large"]; check("a 90 MB conversation -> session large with Fresh chat", sl and "fresh" in sl[0]["actions"] and "90 MB" in sl[0]["title"], kinds(h))
reset(); transcript("p1", "s1", 3 * 3600); state("p1", "done"); ps(CL("p1"), (110, 100, "00:40:00", 0.0, 100000, "sleep 9999")); h = scan()
check("the chat ended its turn but a background job is alive -> waiting on a job (amber), not frozen", "waiting_job" in kinds(h) and "frozen_chat" not in kinds(h), kinds(h))
# ---- agents ----
reset(); transcript("p1", "s1", 60, agents={"a1": 25 * 60, "a2": 30}); state("p1", "working"); (STATE / "p1.agents.json").write_text(json.dumps({"a1": {"type": "backend-engineer", "started": T0 - 3000}, "a2": {"type": "qa", "started": T0 - 3000}})); ps(CL("p1")); h = scan()
fa = [i for i in h["items"] if i["kind"] == "frozen_agent"]; check("an agent quiet 25 min is frozen; one writing now is not", len(fa) == 1 and fa[0]["agent"] == "a1", kinds(h))
# ---- orphans ----
reset(); ps((500, 1, "00:40:00", 0.0, 10000, "sleep 7777")); (STATE / "lineage.json").write_text(json.dumps({"500": {"start": T0 - 2400, "cmd": "sleep 7777", "claude": 900, "claude_start": T0 - 9000, "project": "p1", "seen": T0 - 100}}))
scan(1); check("a proven orphan (allowlist, its chat is dead, same start time) is ended automatically", (T / "kills.log").exists() and "500 orphan" in (T / "kills.log").read_text())
reset(); ps((500, 1, "00:40:00", 0.0, 10000, "sleep 7777"), (900, 1, "02:30:00", 0.1, 300000, "/Users/x/.local/bin/claude --continue --name p1")); (STATE / "lineage.json").write_text(json.dumps({"500": {"start": T0 - 2400, "cmd": "sleep 7777", "claude": 900, "claude_start": T0 - 9000, "project": "p1", "seen": T0 - 100}}))
scan(1); check("an orphan-looking process whose chat is ALIVE is never ended", not (T / "kills.log").exists())
reset(); ps((500, 1, "00:40:00", 0.0, 10000, "sleep 7777")); (STATE / "lineage.json").write_text(json.dumps({"500": {"start": T0 - 99999, "cmd": "sleep 7777", "claude": 900, "claude_start": T0 - 9000, "project": "p1", "seen": T0 - 100}}))
h = scan(2); check("pid reuse (same pid, different start time) is not proof: nothing killed, not raised (no proof = host.unowned only)", not (T / "kills.log").exists() and "leftover" not in kinds(h) and any(u["pid"] == 500 for u in h["host"]["unowned"]), (kinds(h), h["host"].get("unowned")))
reset(); ps((500, 1, "00:40:00", 0.0, 10000, "python3 -m http.server 8000")); scan(1); check("a process that is not on the allowlist is never touched", not (T / "kills.log").exists())
reset(); ps((500, 1, "00:10:00", 0.0, 10000, "sleep 7777")); (STATE / "lineage.json").write_text(json.dumps({"500": {"start": T0 - 600, "cmd": "sleep 7777", "claude": 900, "claude_start": T0 - 9000, "project": "p1", "seen": T0 - 100}}))
scan(1); check("younger than 30 minutes: left alone", not (T / "kills.log").exists())
reset(); ps((500, 1, "00:40:00", 0.0, 10000, "sleep 7777")); (STATE / "lineage.json").write_text(json.dumps({"500": {"start": T0 - 2400, "cmd": "sleep 7777", "claude": 900, "claude_start": T0 - 9000, "project": "p1", "seen": T0 - 100}}))
scan(1, "--dry"); check("--dry changes nothing", not (T / "kills.log").exists())
# ---- duplicates, idle, playwright ----
reset(); transcript("p1", "s1", 60); state("p1", "done"); ps(CL("p1"), (700, 1, "02-03:00:00", 0.0, 150000, "/Users/x/Library/Application Support/Claude/claude-code/2.1/x/claude.app/Contents/MacOS/claude --resume=s1 --model=opus")); h = scan()
du = [i for i in h["items"] if i["kind"] == "duplicate"]; check("the same conversation in the desktop app and VS Code -> duplicate with 'close the duplicate' (the desktop copy)", du and "close-duplicate" in du[0]["actions"] and du[0]["pid"] == 700, kinds(h))
reset(); transcript("p1", "s1", 60); state("p1", "done"); ps((100, 1, "05:00:00", 0.1, 300000, "/Users/x/.local/bin/claude --continue --name p1"), (101, 1, "01:00:00", 0.1, 300000, "/Users/x/.local/bin/claude --continue --name p1")); h = scan()
du = [i for i in h["items"] if i["kind"] == "duplicate_tabs"]; check("two VS Code chats on one conversation -> duplicate_tabs: quit-session on the OLDER process", du and du[0]["chain"] == ["quit-session"] and du[0]["pid"] == 100 and "duplicate" not in kinds(h), kinds(h))
reset(); transcript("p1", "s1", 30 * 3600); state("p1", "done"); ps((100, 1, "05-00:00:00", 0.1, 600000, "/Users/x/.local/bin/claude --continue --name p1")); h = scan()
check("a big chat nobody used for a day is offered for quitting", "idle_session" in kinds(h) and "quit-session" in [a for i in h["items"] if i["kind"] == "idle_session" for a in i["actions"]], (kinds(h), h["chats"]))
reset(); transcript("p1", "s1", 60); state("p1", "done"); ps(CL("p1"), (200, 100, "00:30:00", 0.0, 50000, "npm exec @playwright/mcp@latest"), (201, 200, "00:30:00", 0.0, 100000, "node /x/.bin/playwright-mcp"), (210, 100, "00:20:00", 0.0, 50000, "npm exec @playwright/mcp@latest"), (211, 210, "00:20:00", 0.0, 100000, "node /x/.bin/playwright-mcp"))
h = scan(); check("two Playwright servers for one chat -> the extra one is offered to end", [i["pid"] for i in h["items"] if i["kind"] == "playwright_dup"] == [201], kinds(h))
# ---- host ----
reset(); (T / "host.json").write_text(json.dumps({"swap_pct": 85, "free_pct": 60, "load": 1.0, "cores": 8})); ps(); h = scan(4); check("high swap for 4 scans is not yet 'Mac busy' (needs 5 minutes)", "host_busy" not in kinds(h))
h = scan(3); hb = [i for i in h["items"] if i["kind"] == "host_busy"]
check("high swap for 5+ scans -> Mac busy; with none of our agents running it is information (grey, no button, not in the badge)", len(hb) == 1 and hb[0]["mode"] == "info" and hb[0]["info_only"] and hb[0]["actions"] == [] and h["counts"] == {"red": 0, "amber": 0}, str(hb))
(T / "host.json").write_text(json.dumps({"swap_pct": 75, "free_pct": 60, "load": 1.0, "cores": 8})); h = scan(3); check("between the thresholds (75 %) it neither starts nor clears: still busy (hysteresis)", "host_busy" in kinds(h))
(T / "host.json").write_text(json.dumps({"swap_pct": 40, "free_pct": 60, "load": 1.0, "cores": 8})); h = scan(3); check("below 70 % it clears", "host_busy" not in kinds(h))
# ---- housekeeping ----
reset(); transcript("p1", "s1", 100 * 60); state("p1", "done"); ps(CL("p1")); (STATE / "p1.agents.json").write_text(json.dumps({"dead": {"type": "x", "started": T0 - 100}, "old": {"type": "y", "started": T0 - 4 * 3600}}))
d = HOME / ".claude/projects" / re.sub(r"[^A-Za-z0-9]", "-", str(DEV / "p1")); g = d / "s1" / "subagents"; g.mkdir(parents=True, exist_ok=True); (g / "agent-dead.jsonl").write_text("{}"); os.utime(g / "agent-dead.jsonl", (T0 - 70 * 60, T0 - 70 * 60))
scan(1); left = json.loads((STATE / "p1.agents.json").read_text()) if (STATE / "p1.agents.json").exists() else {}
check("a record older than 3 h with no live file is dropped; a 70-min-quiet record started after the chat is NOT dropped any more (it may be alive)", list(left) == ["dead"], str(left))
reset(); od = TMP / "proj" / "tasks"; od.mkdir(parents=True, exist_ok=True); old, new = od / "old.output", od / "new.output"; old.write_text("x"); new.write_text("y"); os.utime(old, (T0 - 8 * 86400, T0 - 8 * 86400)); os.utime(new, (T0 - 86400, T0 - 86400))
(STATE / "ghost-proj.mode.json").write_text("{}"); (STATE / "p1.mode.json").write_text("{}"); ps(); scan(1)
check("task outputs older than 7 days are deleted, newer kept", not old.exists() and new.exists())
check("state files of projects that do not exist are deleted, real projects' kept", not (STATE / "ghost-proj.mode.json").exists() and (STATE / "p1.mode.json").exists())
h = json.loads((STATE / "health.json").read_text()); check("what was cleaned is listed in health.json", any(x["what"] == "old task outputs" for x in h["cleaned"]) and any(x["what"] == "leaked state file" for x in h["cleaned"]))
reset(); legit = ("skills-uses.json", "skills-diff.json", "model-reset.json", "plan.json", "guard.json", "away.json", "ci.json", "idea-prefs.json", "idea-ask.json", "away-decisions.json", "watch-state.json", "lineage.json")
for n in legit:
    (STATE / n).write_text("{}")
(STATE / "ghost-proj.json").write_text("{}"); ps(); scan(1)
check("state files written by our own tools (skills-uses.json etc.) are never deleted as 'leaked'; an unknown one still is", all((STATE / n).exists() for n in legit if n not in ("watch-state.json", "lineage.json")) and not (STATE / "ghost-proj.json").exists(), [n for n in legit if not (STATE / n).exists()])
reset()
for _n in ("ledger.summary.json", "ledger.offsets.json", "scorecard.json"):
    (STATE / _n).write_text("{}")
(STATE / "ghost-proj.json").write_text("{}"); ps(); scan(1)
check("housekeeping keeps ledger.summary.json, ledger.offsets.json and scorecard.json (not a leaked state file); an unknown one is still removed", all((STATE / _n).exists() for _n in ("ledger.summary.json", "ledger.offsets.json", "scorecard.json")) and not (STATE / "ghost-proj.json").exists())
import re as _re
written = set()                                                          # every "<name>.json" the code writes under the state dir
for _f in [*(ws / "shipmiracle").rglob("*.py"), *(ws / "bin").glob("*"), *(ws / "hooks").glob("*")]:
    try:
        _t = _f.read_text()
    except (OSError, UnicodeDecodeError):
        continue
    written |= set(_re.findall(r"(?:STATE\w*|state_dir\(\)|_state_file)\s*[/(]\s*[\"']([a-z][a-z0-9.-]*)\.json[\"']", _t))        # names may hold dots (ledger.summary.json)
    written |= set(_re.findall(r"os\.path\.join\(\s*(?:\w*[Ss][Tt][Aa][Tt][Ee]\w*|state_dir\(\)|SD|sd)\s*,\s*[\"']([a-z][a-z0-9.-]*)\.json[\"']", _t))    # and be built with os.path.join
kept = set(_re.search(r"STATE_KEEP = frozenset\(\{([^}]*)\}", open(AW_SRC).read()).group(1).replace('"', "").replace(" ", "").split(","))
check("the scanner sees dotted and os.path.join-built names (ledger.summary.json is written by shipm-ledger)", "ledger.summary" in written and "ledger.offsets" in written, sorted(written)[:40])
check("every state file name the code writes is in shipm-watch STATE_KEEP", written and not (written - kept), sorted(written - kept))
reset(); fl = {n: STATE / n for n in ("flow.old.json", "flow.old.json.lock", "flow.old.json.123.tmp", "flow.new.json", "flow.new.json.lock", "flow.old.quiet", "flow.new.quiet")}
for n, q in fl.items():
    q.write_text("{}")
    d_ = 15 if n.startswith("flow.old") else 1
    os.utime(q, (T0 - d_ * 86400, T0 - d_ * 86400))
ps(); scan(1)
check("team-flow state, lock, tmp and .quiet files older than 14 days are deleted, newer kept (and an active flow.*.json is not 'leaked')", not any(fl[n].exists() for n in fl if n.startswith("flow.old")) and fl["flow.new.json"].exists() and fl["flow.new.json.lock"].exists())
h = json.loads((STATE / "health.json").read_text()); check("the team-flow cleanup is listed in health.json", any(x["what"] == "old team-flow state files" for x in h["cleaned"]))
reset(); (W / "config/watch.json").write_text('{"auto": false}'); old = od / "old.output"; old.write_text("x"); os.utime(old, (T0 - 8 * 86400, T0 - 8 * 86400)); ps(); scan(1); check("auto:false in config/watch.json turns every automatic action off", old.exists())
# ---- hold release signal ----
reset(); transcript("p1", "s1", 25 * 60); state("p1", "working"); ps(CL("p1")); h = scan(2); check("only frozen work: all_work_frozen_since is set", h["all_work_frozen_since"] is not None, (kinds(h), h["chats"]))
reset(); transcript("p1", "s1", 60); state("p1", "working"); ps(CL("p1")); h = scan(2); check("work that is moving: all_work_frozen_since is empty", h["all_work_frozen_since"] is None)
# ---- owner actions ----
reset(); ps((600, 100, "03:00:00", 0.0, 10000, "sleep 123456"), CL("p1")); transcript("p1", "s1", 3 * 3600); state("p1", "done")
h = scan(2); jb = [i for i in h["items"] if i["kind"] == "job_frozen"]; check("a job older than 2 h with no CPU and no output -> frozen job with End job", jb and jb[0]["actions"] == ["end-job"], kinds(h))
if jb:
    r = subprocess.run([str(ws / "bin/shipm-watch"), "act", "end-job", jb[0]["id"]], capture_output=True, text=True, env=ENV)
    check("End job ends exactly that process (after a checkpoint)", "600 end-job" in (T / "kills.log").read_text() if (T / "kills.log").exists() else False, r.stdout + r.stderr)
    (T / "kills.log").unlink(missing_ok=True); ps((600, 100, "00:01:00", 0.0, 10000, "other thing"), CL("p1"))
    r = subprocess.run([str(ws / "bin/shipm-watch"), "act", "end-job", jb[0]["id"]], capture_output=True, text=True, env=ENV)
    check("if the pid now belongs to a different process (reuse), nothing is ended", not (T / "kills.log").exists() and "gone or changed" in r.stdout, r.stdout)
r = subprocess.run([str(ws / "bin/shipm-watch"), "act", "end-job", "doesnotexist"], capture_output=True, text=True, env=ENV); check("an action that is not in health.json is refused", "not a current action" in r.stdout)
r = subprocess.run([str(ws / "bin/shipm-watch"), "act", "pause-agents", "-"], capture_output=True, text=True, env=ENV); check("pause-agents writes the flag, resume-agents removes it", (STATE / "agents.paused").exists())
subprocess.run([str(ws / "bin/shipm-watch"), "act", "resume-agents", "-"], capture_output=True, text=True, env=ENV); check("resume removes it", not (STATE / "agents.paused").exists())
(DEV / "p2" / "dirty.txt").write_text("unsaved work\n"); (DEV / "p2" / ".env").write_text("SECRET=1\n")
r = subprocess.run([str(ws / "bin/shipm-watch"), "act", "checkpoint", "p2"], capture_output=True, text=True, env=ENV); br = r.stdout.strip()
files = subprocess.run(["git", "-C", str(DEV / "p2"), "ls-tree", "-r", "--name-only", br], capture_output=True, text=True).stdout.split()
check("checkpoint saves uncommitted work to wip/frozen-<date> without the secret file, and leaves the working tree alone", br.startswith("wip/frozen-") and "dirty.txt" in files and ".env" not in files and (DEV / "p2" / "dirty.txt").exists() and "dirty.txt" in subprocess.run(["git", "-C", str(DEV / "p2"), "status", "--porcelain"], capture_output=True, text=True).stdout, br + str(files))
# ---- host command, speed ----
(T / "host.json").write_text(json.dumps({"swap_pct": 50, "free_pct": 60, "load": 2.0, "cores": 8})); r = subprocess.run([str(ws / "bin/shipm-watch"), "host", "--heavy-ok"], capture_output=True, text=True, env=ENV); check("host --heavy-ok: fine Mac -> exit 0", r.returncode == 0, r.stdout)
(T / "host.json").write_text(json.dumps({"swap_pct": 75, "free_pct": 60, "load": 2.0, "cores": 8})); r = subprocess.run([str(ws / "bin/shipm-watch"), "host", "--heavy-ok"], capture_output=True, text=True, env=ENV); check("host --heavy-ok: swap 75 % -> exit 1 with the reason", r.returncode == 1 and "swap 75" in r.stdout, r.stdout)
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent)); import shipmiracle_timing as _T
def _scan_time():
    reset(); ps(*[CL(f"p{i}", 100 + i) for i in range(1, 3)]); return _T.timed(lambda: scan(1))
_ok, _rep, _ = _T.robust(_scan_time, lambda: _T.spawn_ref(10), 1.5, 15)   # limit 1.5 s, or 15 x python start measured just before
check("a scan takes well under a second (max(1.5 s, 15 x python start)): " + _rep, _ok, _rep)
reset(); ps(CL("p1", 101)); subprocess.run([str(ws / "bin/shipm-watch"), "act", "auto-clean-off", "-"], capture_output=True, env=ENV); scan(1)
h = json.loads((STATE / "health.json").read_text()); check("the owner's switch off: no housekeeping runs and health says so", h["auto"] is False and h["hk_last"] == 0, str((h["auto"], h["hk_last"])))
subprocess.run([str(ws / "bin/shipm-watch"), "act", "auto-clean-on", "-"], capture_output=True, env=ENV); scan(1)
h = json.loads((STATE / "health.json").read_text()); check("switch on again: housekeeping runs and the run time is recorded", h["auto"] is True and h["hk_last"] > 0, str((h["auto"], h["hk_last"])))
# ---- registry, lock, JSON actions ----
import fcntl
reset(); ps(CL("p1")); STATE.mkdir(exist_ok=True); lk = open(STATE / "watch.lock", "a"); fcntl.flock(lk, fcntl.LOCK_EX)
r = subprocess.run([str(ws / "bin/shipm-watch"), "scan"], capture_output=True, text=True, env=dict(ENV, SHIPMIRACLE_LOCK_WAIT="1"))
check("the scan lock: a scan started while another holds it is skipped (not run in parallel)", "skipped" in r.stdout and not (STATE / "health.json").exists(), r.stdout)
fcntl.flock(lk, fcntl.LOCK_UN); lk.close()
r = subprocess.run([str(ws / "bin/shipm-watch"), "scan"], capture_output=True, text=True, env=ENV); check("...and runs normally once the lock is free", "red" in r.stdout and (STATE / "health.json").exists(), r.stdout)
reset(); transcript("p1", "s1", 3 * 3600); state("p1", "done"); ps(CL("p1"), (110, 100, "03:00:00", 0.0, 100000, "sleep 123456")); h = scan(2); jb = [i for i in h["items"] if i["kind"] == "job_frozen"]
r = subprocess.run([str(ws / "bin/shipm-watch"), "act", "end-job", jb[0]["id"]], capture_output=True, text=True, env=ENV); j = json.loads(r.stdout)
check("act returns JSON {ok, did, why} and exit 0 on success", j["ok"] is True and "110" in j["did"] and j["why"] == "" and r.returncode == 0, r.stdout)
r = subprocess.run([str(ws / "bin/shipm-watch"), "act", "end-job", "nope"], capture_output=True, text=True, env=ENV); j = json.loads(r.stdout)
check("a refused act is JSON {ok:false, why} with exit 2", j["ok"] is False and j["why"] and r.returncode == 2, r.stdout)
reset(); (T / "host.json").write_text(json.dumps({"swap_pct": 90, "free_pct": 60, "load": 1.0, "cores": 8})); ps(); (STATE / "watch-state.json").write_text(json.dumps({"host_bad": 9})); h = scan(1)
check("an info item (Mac busy, nothing of ours to stop) is shown at once and is not counted in the badge", "host_busy" in kinds(h) and h["counts"] == {"red": 0, "amber": 0})
# ---- review round: ids, pid-reuse proof, checkpoint, kill, env gating, redaction, lock ----
import importlib.machinery, importlib.util, re as _re, stat as _stat
AW = str(ws / "bin/shipm-watch")
def aw(*a, env=None):
    return subprocess.run([AW, *a], capture_output=True, text=True, env=env or ENV)
def mod(extra_env):
    code = "import importlib.machinery as m, importlib.util as u; sp=u.spec_from_loader('w', m.SourceFileLoader('w', %r)); w=u.module_from_spec(sp); sp.loader.exec_module(w); " % AW
    return code
reset(); ps((600, 100, "03:00:00", 0.0, 10000, "sleep 123456"), CL("p1")); transcript("p1", "s1", 3 * 3600); state("p1", "done")
h = scan(2); jb = [i for i in h["items"] if i["kind"] == "job_frozen"][0]
ps((600, 100, "03:00:01", 0.0, 10000, "sleep 123456"), CL("p1"))      # the same process one second later: etime is whole seconds, so its computed start drifts by 1 s
h2 = scan(2); jb2 = [i for i in h2["items"] if i["kind"] == "job_frozen"]
check("the item id does not change when the computed start time drifts by 1 s", len(jb2) == 1 and jb2[0]["id"] == jb["id"])
c = json.loads(aw("can", "end-job", jb["id"]).stdout); v = json.loads(aw("verify", jb["id"]).stdout)
check("...can end-job is still ok and verify says not gone", c["ok"] and v["gone"] is False and v["checked"] is True, str((c, v)))
ps((600, 100, "00:30:00", 0.0, 10000, "sleep 123456"), CL("p1"))      # same pid, started 2.5 h later: a different process
c = json.loads(aw("can", "end-job", jb["id"]).stdout); v = json.loads(aw("verify", jb["id"]).stdout)
check("a pid with a start time more than 5 s away is another process: can refuses, verify says gone", not c["ok"] and v["gone"] is True, str((c, v)))
# planted health.json cannot widen what a step may do
reset(); transcript("p1", "s1", 25 * 60); state("p1", "working"); ps(CL("p1")); h = scan(2); fc = [i for i in h["items"] if i["kind"] == "frozen_chat"][0]
planted = json.loads((STATE / "health.json").read_text()); planted["items"][[i["id"] for i in planted["items"]].index(fc["id"])]["actions"] += ["end-job", "stop-colima"]; (STATE / "health.json").write_text(json.dumps(planted))
c = json.loads(aw("can", "end-job", fc["id"]).stdout); r = aw("act", "end-job", fc["id"])
check("an op that a planted health.json lists but the FRESH scan does not offer is refused (can and act)", not c["ok"] and not json.loads(r.stdout)["ok"] and not (T / "kills.log").exists(), str((c, r.stdout)))
planted["items"].append({"id": "feedfacefe", "kind": "job_frozen", "project": "p1", "pid": 100, "start": T0 - 18000, "actions": ["end-job"], "chain": ["end-job"]}); (STATE / "health.json").write_text(json.dumps(planted))
r = aw("act", "end-job", "feedfacefe"); check("a planted item that no fresh scan raises can never kill anything", not json.loads(r.stdout)["ok"] and not (T / "kills.log").exists(), r.stdout)
c = json.loads(aw("can", "interrupt", fc["id"]).stdout)
check("can returns ok, why, project, kind and working from the FRESH item", set(c) == {"ok", "why", "project", "kind", "working"} and c["ok"] and c["project"] == "p1" and c["kind"] == "frozen_chat" and c["working"] is True, str(c))
v = json.loads(aw("verify", fc["id"]).stdout); check("verify: a frozen chat is working:true", v["working"] is True and v["chat_state"] == "frozen", str(v)[:200])
state("p1", "idle"); v = json.loads(aw("verify", fc["id"]).stdout); check("verify: an idle chat is working:false", v["gone"] is True and v["working"] is False, str(v)[:200])
# the lock: verify says 'could not check', never 'not fixed'
lk = open(STATE / "watch.lock", "a"); fcntl.flock(lk, fcntl.LOCK_EX)
v = json.loads(aw("verify", fc["id"], env=dict(ENV, SHIPMIRACLE_LOCK_WAIT="1")).stdout)
check("verify while another scan holds the lock answers could-not-check (checked:false, gone:false)", v["gone"] is False and v["checked"] is False and "could not check" in v["detail"], str(v))
fcntl.flock(lk, fcntl.LOCK_UN); lk.close()
# interrupt marker: only a structured user message counts
reset(); lead = transcript("p1", "s1", 25 * 60); state("p1", "working", age=300); ps(CL("p1"))
quoted = [json.dumps({"type": "assistant", "timestamp": iso(100), "message": {"content": [{"type": "text", "text": "I read: [Request interrupted by user for tool use] in the file"}]}}),
          json.dumps({"type": "user", "timestamp": iso(90), "message": {"content": [{"type": "tool_result", "tool_use_id": "x", "content": "[Request interrupted by user for tool use]"}]}}),
          json.dumps({"type": "user", "timestamp": iso(80), "message": {"content": [{"type": "text", "text": "please grep for [Request interrupted by user in the code"}]}})]
lead.write_text("\n".join(quoted) + "\n"); os.utime(lead, (T0 - 25 * 60, T0 - 25 * 60)); h = scan(2)
check("the interrupt string quoted in assistant text, a tool_result or a user sentence does NOT clear 'working'", "frozen_chat" in kinds(h), kinds(h))
lead.write_text(json.dumps({"type": "user", "timestamp": iso(50), "message": {"role": "user", "content": "[Request interrupted by user]"}}) + "\n"); os.utime(lead, (T0 - 25 * 60, T0 - 25 * 60)); h = scan(2)
check("a real interrupt record (string content) clears it", "frozen_chat" not in kinds(h), kinds(h))
# env overrides only count with SHIPMIRACLE_TEST=1
r1 = subprocess.run([sys.executable, "-c", mod({}) + "print(w.STATE)"], capture_output=True, text=True, env=dict(os.environ, SHIPMIRACLE_STATE="/tmp/evil-state", SHIPMIRACLE_TEST="")).stdout.strip()
r2 = subprocess.run([sys.executable, "-c", mod({}) + "print(w.STATE)"], capture_output=True, text=True, env=dict(os.environ, SHIPMIRACLE_STATE="/tmp/evil-state", SHIPMIRACLE_TEST="1")).stdout.strip()
check("SHIPMIRACLE_* overrides are ignored unless SHIPMIRACLE_TEST=1", r1 != "/tmp/evil-state" and r1.endswith(".local/state/shipmiracle") and r2 == "/tmp/evil-state", (r1, r2))
# kill: the start time is re-read right before the signal
sl = subprocess.Popen(["/bin/sleep", "60"]); time.sleep(0.3)
code = mod({}) + "s=w.Scan.__new__(w.Scan); s.t=0; s.cleaned=[]; import sys; p={'pid': int(sys.argv[1]), 'start': float(sys.argv[2]), 'cmd': 'sleep 60 --token abcdef123'}; print(s.kill(p, 'test'))"
kenv = {k: v for k, v in os.environ.items() if not k.startswith("SHIPMIRACLE_")}; kenv.update(SHIPMIRACLE_TEST="1", SHIPMIRACLE_STATE=str(STATE), SHIPMIRACLE_HOME=str(HOME))
r = subprocess.run([sys.executable, "-c", code, str(sl.pid), str(time.time() - 5000)], capture_output=True, text=True, env=kenv)
check("kill aborts when the pid's start time is not the one we saw (pid reuse): nothing is sent", r.stdout.strip() == "False" and sl.poll() is None, r.stdout + r.stderr[-300:])
r = subprocess.run([sys.executable, "-c", code, str(sl.pid), str(time.time() - 0.3)], capture_output=True, text=True, env=kenv)
check("...and it ends the process when the start time matches", r.stdout.strip() == "True" and (sl.wait(timeout=15) is not None), r.stdout + r.stderr[-300:])
# redaction and file modes
code = mod({}) + "print(w.red('node x.js --token abc123 --api-key=SECRETVALUE Authorization: Bearer abc.def ' + 'A'*60 + ' ok'))"
out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=kenv).stdout
check("red(): token, key, secret, password, authorization/bearer values and long base64 runs are removed", all(x not in out for x in ("abc123", "SECRETVALUE", "abc.def", "A" * 60)) and "node x.js" in out and "ok" in out, out)
reset(); ps(CL("p1"), (500, 1, "00:40:00", 0.0, 10000, "sleep 7777 --password hunter2")); (STATE / "lineage.json").write_text(json.dumps({"500": {"start": T0 - 2400, "cmd": "sleep 7777 --password hunter2", "claude": 900, "claude_start": T0 - 9000, "project": "p1", "seen": T0 - 100}})); scan(1)
check("a stored lineage / cleaned command line has its secrets redacted", "hunter2" not in (STATE / "lineage.json").read_text() and "hunter2" not in (STATE / "health.json").read_text() and "hunter2" not in (STATE / "events.log").read_text() if (STATE / "events.log").exists() else True)
check("health.json, lineage.json and watch-state.json are written 0600", all(_stat.S_IMODE((STATE / n).stat().st_mode) == 0o600 for n in ("health.json", "lineage.json", "watch-state.json")))
big = {str(i): {"start": T0, "cmd": "x", "claude": 1, "claude_start": 1, "project": "p1", "seen": T0 - 100 - i} for i in range(5200)}; (STATE / "lineage.json").write_text(json.dumps(big)); ps(CL("p1")); scan(1)
check("lineage.json is capped (about 5000 newest entries)", len(json.loads((STATE / "lineage.json").read_text())) <= 5001)
# checkpoint
def cp(proj, e=None):
    return subprocess.run([AW, "act", "checkpoint", proj], capture_output=True, text=True, env=e or ENV)
reset(); ps()
for f, body in ((".env", "A=1"), (".env.local", "A=2"), ("id_rsa", "k"), ("id_ed25519.pub", "pubkey"), ("server.pem", "p"), ("a.p8", "p"), ("x.jks", "p"), ("app.mobileprovision", "p"), (".netrc", "n"), (".npmrc", "n"), (".pypirc", "n"),
                ("aws-credentials.txt", "c"), ("my_secret_notes.txt", "s"), ("api-token.txt", "t"), ("service-account-prod.json", "{}"), ("src.txt", "real work")):
    (DEV / "p2" / f).write_text(body)
(DEV / "p2" / ".env.example").write_text("A=\n"); subprocess.run(["git", "-C", str(DEV / "p2"), "add", ".env.example"], env=GE); subprocess.run(["git", "-C", str(DEV / "p2"), "commit", "-q", "-m", "ex"], env=GE); (DEV / "p2" / ".env.example").write_text("A=changed\n")
r = cp("p2"); br = r.stdout.strip(); files = subprocess.run(["git", "-C", str(DEV / "p2"), "ls-tree", "-r", "--name-only", br], capture_output=True, text=True).stdout.split()
bad = [f for f in files if f in (".env", ".env.local", "id_rsa", "server.pem", "a.p8", "x.jks", "app.mobileprovision", ".netrc", ".npmrc", ".pypirc", "aws-credentials.txt", "my_secret_notes.txt", "api-token.txt", "service-account-prod.json")]
check("checkpoint: no new secret-looking file ends up in the wip tree; real work, a .pub key and the tracked .env.example do", not bad and "src.txt" in files and "id_ed25519.pub" in files and ".env.example" in files and br.startswith("wip/frozen-"), str((bad, files, r.stdout, r.stderr)))
check("checkpoint: the branch really points at the commit; a push failure (no origin) is only a warning", subprocess.run(["git", "-C", str(DEV / "p2"), "rev-parse", "--verify", br], capture_output=True).returncode == 0 and "push" in r.stderr and r.returncode == 0, r.stderr)
for bad_arg in ("../p2", "/etc", "p2/../p1", "nope", "-p2", ""):
    r = cp(bad_arg); check(f"checkpoint refuses the project argument {bad_arg!r}", r.stdout.startswith("failed:") and r.returncode == 2, r.stdout)
mkd = DEV / "unborn"; mkd.mkdir(exist_ok=True); subprocess.run(["git", "init", "-q", "-b", "main", str(mkd)], env=GE); (mkd / "f.txt").write_text("x")
r = cp("unborn"); check("checkpoint of a repository without a commit is 'failed: ...', not 'nothing to save'", r.stdout.startswith("failed:") and "nothing to save" not in r.stdout and r.returncode == 2, r.stdout)
r = cp("p1"); check("checkpoint of a clean repo says nothing to save", r.stdout.strip() == "nothing to save", r.stdout)
# ---- P2/T5: shared project discovery, uid-based temp path, health.json mirror, guarded import ----
import shutil
sys.path.insert(0, str(ws))
from shipmiracle import projects as shipmiracle_projects
(DEV / ".hid").mkdir(exist_ok=True); (DEV / ".hid/.git").mkdir(exist_ok=True)       # dot-named: the one documented narrowing
(DEV / "plain").mkdir(exist_ok=True)                                                  # no .git: never a project
r = subprocess.run([sys.executable, "-c", mod({}) + "import json; print(json.dumps(w.projects()))"], capture_output=True, text=True, env=ENV)
check("discovery: shipm-watch projects() equals shipmiracle.projects.names(dev=DEV)", json.loads(r.stdout) == shipmiracle_projects.names(dev=DEV) and ".hid" not in r.stdout and "plain" not in r.stdout, r.stdout + r.stderr)
r = subprocess.run([sys.executable, "-c", mod({}) + "print(w.TMP)"], capture_output=True, text=True, env=dict(os.environ, SHIPMIRACLE_TEST="", SHIPMIRACLE_TMP="/tmp/evil"))
check("temp path uses the real uid, not 501", r.stdout.strip() == ("/private/tmp" if sys.platform == "darwin" else "/tmp") + "/claude-%d" % os.getuid(), r.stdout)
reset(); h = scan(1)
v1 = STATE / "v1" / "health.json"; env1 = json.loads(v1.read_text()) if v1.exists() else {}
check("mirror: v1/health.json (writer shipm-watch, 0600) holds the same data as health.json", env1.get("writer") == "shipmiracle-watch" and env1.get("data") == h and (v1.stat().st_mode & 0o777) == 0o600, str(env1)[:200])
HC = HOME / ".config/shipmiracle"; HC.mkdir(parents=True, exist_ok=True); (HC / "config.json").write_text(json.dumps({"switches.state.v1": False}))
shutil.rmtree(STATE / "v1"); h = scan(1)
check("switch off: health.json written, no v1 file", h["ts"] and not (STATE / "v1/health.json").exists())
(HC / "config.json").unlink(); shutil.rmtree(STATE / "v1", ignore_errors=True); (STATE / "v1/health.json").mkdir(parents=True)
h = scan(1); evl = (STATE / "v1/events.jsonl").read_text().splitlines() if (STATE / "v1/events.jsonl").exists() else []
check("mirror failure: legacy health.json complete, exactly one state.v1_write_failed event", h["ts"] and sum('"state.v1_write_failed"' in l for l in evl) == 1, str(evl))
shutil.rmtree(STATE / "v1")
def broken_pkg(c):
    (c / "shipmiracle").mkdir(); (c / "shipmiracle/__init__.py").write_text("def (:\n")
def no_mirror_pkg(c):
    shutil.copytree(ws / "shipmiracle", c / "shipmiracle", ignore=shutil.ignore_patterns("__pycache__"))
    st = (c / "shipmiracle/state.py").read_text(); (c / "shipmiracle/state.py").write_text(st.replace("def mirror(", "def _renamed_mirror("))
for label, mk in (("missing shipmiracle/", lambda c: None), ("shipmiracle/ with a SyntaxError", broken_pkg), ("shipmiracle/ whose state lacks mirror", no_mirror_pkg)):
    c = T / ("copy_" + str(abs(hash(label)))); (c / "bin").mkdir(parents=True); shutil.copy(ws / "bin/shipm-watch", c / "bin/shipm-watch"); mk(c)
    shutil.rmtree(STATE / "v1", ignore_errors=True); (STATE / "health.json").unlink(missing_ok=True)
    r = subprocess.run([sys.executable, str(c / "bin/shipm-watch"), "scan"], capture_output=True, text=True, env=ENV)
    pj = subprocess.run([sys.executable, "-c", "import importlib.machinery as m, importlib.util as u, json; sp=u.spec_from_loader('w', m.SourceFileLoader('w', %r)); w=u.module_from_spec(sp); sp.loader.exec_module(w); print(json.dumps([w.projects(), w.shipmiracle_projects is None]))" % str(c / "bin/shipm-watch")], capture_output=True, text=True, env=ENV, cwd=str(c))
    names, off = json.loads(pj.stdout)
    check("guarded import (%s): scan exits 0, writes health.json, no v1 copy, old discovery (includes dot-named .git folders)" % label,
          r.returncode == 0 and (STATE / "health.json").exists() and not (STATE / "v1").exists() and (off or "lacks" in label) and (".hid" in names or "lacks" in label), r.stderr[-300:] + pj.stderr[-300:])

print("\nFAILED:" if fails else "\nALL PASS", fails)
sys.exit(1 if fails else 0)
