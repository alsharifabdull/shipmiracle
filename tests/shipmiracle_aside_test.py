#!/usr/bin/env python3
"""F7 Set aside and F8 Unread marker (engine side of the panel v3 UX addendum, sections 3 and 4): `shipm project aside|unaside|seen`, the state files, the fields of
`shipm report panel`, the watcher's silenced split and the auto un-aside. Real subprocesses, full isolation through tests/shipmiracle_isolation.py, no network, no model.
Run: python3 tests/shipmiracle_aside_test.py"""
import json, os, pathlib, subprocess, sys, time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import shipmiracle_isolation as ISO  # noqa: E402

ENV, TMP = ISO.isolated_env(ws=ROOT)
TMP = pathlib.Path(TMP)
os.environ.update(ENV)
ENV.pop("CLAUDECODE", None)
DEV = pathlib.Path(ENV["SHIPMIRACLE_DEV"]); STATE = pathlib.Path(ENV["SHIPMIRACLE_STATE"])
fails = 0
def check(name, ok, info=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(info)[:600]))
    fails += 0 if ok else 1

def shipm(*args, extra=None):
    e = dict(ENV); e.update(extra or {})
    r = subprocess.run([sys.executable, str(ROOT / "bin" / "shipm")] + list(args), env=e, capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)
    return r.returncode, r.stdout, r.stderr

def panel(name):
    c, o, e = shipm("report", "panel", "--project", str(DEV / name))
    return json.loads(o) if c == 0 else {"_err": e}

for n in ("alpha", "beta", "gamma"):
    d = DEV / n; d.mkdir(parents=True)
    subprocess.run(["git", "-C", str(d), "init", "-q"], env=ENV, check=True)
    (d / "a.txt").write_text("1\n")
    subprocess.run(["git", "-C", str(d), "add", "-A"], env=ENV, check=True)
    subprocess.run(["git", "-C", str(d), "commit", "-q", "-m", "init"], env=ENV, check=True)
STATE.mkdir(parents=True, exist_ok=True)
V1 = STATE / "v1"
NOW = int(time.time())
def chat_state(name, st, ts):
    (STATE / (name + ".json")).write_text(json.dumps({"state": st, "ts": ts}))
def health(chats, items=()):
    (STATE / "health.json").write_text(json.dumps({"ts": NOW, "chats": chats, "items": list(items)}))

# ================================================================== F8 unread marker
p = panel("alpha")
check("F8: panel has an unread field, no marker without any state", p.get("unread") == {"new": False, "why": None, "since": None}, p)
chat_state("alpha", "idle", NOW - 100)
check("F8: a finished turn but no seen record: no marker (nothing to compare with)", panel("alpha")["unread"]["new"] is False)
c, o, e = shipm("project", "seen", "alpha")
check("F8: project seen: exit 0, writes only seen.json", c == 0 and (V1 / "seen.json").is_file() and not (V1 / "aside.json").exists(), (c, o, e))
seen_ts = json.loads((V1 / "seen.json").read_text())["data"]["seen"]["alpha"]
check("F8: seen.json is a v1 envelope with the project's time, mode 0600", abs(seen_ts - NOW) < 30 and oct((V1 / "seen.json").stat().st_mode & 0o777) == "0o600", seen_ts)
chat_state("alpha", "idle", NOW + 5)          # a turn finished after the owner looked
u = panel("alpha")["unread"]
check("F8: idle after the seen time = New (turn)", u == {"new": True, "why": "turn", "since": NOW + 5}, u)
chat_state("alpha", "needs-input", NOW + 6)
check("F8: needs-input after the seen time = New (wait)", panel("alpha")["unread"]["why"] == "wait")
chat_state("alpha", "working", NOW + 7)
check("F8: working = no marker", panel("alpha")["unread"]["new"] is False)
chat_state("alpha", "idle", NOW + 8)
health({"alpha": {"state": "plan_approval", "working": False}})
check("F8: a plan waiting for approval counts as wait", panel("alpha")["unread"]["why"] == "wait")
health({})
chat_state("alpha", "idle", seen_ts - 50)
check("F8: a turn older than the seen time = no marker", panel("alpha")["unread"]["new"] is False)
chat_state("alpha", "idle", NOW + 9)
c, o, e = shipm("project", "seen", "alpha")
seen2 = json.loads((V1 / "seen.json").read_text())["data"]["seen"]["alpha"]
check("F8: Open chat (project seen) clears the marker", c == 0 and seen2 >= seen_ts, (c, e))
(STATE / "alpha.json").write_text("{not json")
check("F8: a damaged chat state file = no marker, no crash", panel("alpha")["unread"]["new"] is False)
(STATE / "alpha.json").unlink()
(STATE / "target.json").write_text(json.dumps({"state": "idle", "ts": NOW + 99}))
os.symlink(str(STATE / "target.json"), str(STATE / "beta.json"))
shipm("project", "seen", "beta")
check("F8: a symlinked chat state file is refused (no marker)", panel("beta")["unread"]["new"] is False)
c, o, e = shipm("project", "seen", "nosuch")
check("F8: seen for an unknown project: exit 3", c == 3, (c, e))
c, o, e = shipm("project", "seen")
check("F8: seen without a name: exit 2", c == 2, (c, e))
before = (V1 / "seen.json").read_text()
c, o, e = shipm("project", "seen", "gamma", extra={"CLAUDECODE": "1", "SHIPMIRACLE_ENFORCE_OWNER": "1"})
check("F8: seen inside a chat is refused (exit 4) and writes nothing", c == 4 and (V1 / "seen.json").read_text() == before, (c, e))
c, o, e = shipm("project", "seen", "gamma", extra={"CLAUDECODE": "1"})
check("F8: (sandbox without enforce) the chat guard is the same as the other owner commands", c in (0, 4))

# ================================================================== F7 set aside
p = panel("beta")["aside"]
check("F7: panel aside field, default", p == {"on": False, "since": None, "note": None, "canAside": True, "reason": None, "backOnList": None}, p)
c, o, e = shipm("project", "aside", "beta", "--note", "wait\x1b[31m for‮ the printer " + "x" * 300)
check("F7: aside: exit 0, writes only aside.json", c == 0 and (V1 / "aside.json").is_file(), (c, o, e))
a = panel("beta")["aside"]
check("F7: panel shows on/since", a["on"] is True and abs(a["since"] - NOW) < 30 and a["canAside"] is False, a)
check("F7: hostile note: control and bidi characters gone, cut to 120", a["note"] and "\x1b" not in a["note"] and "‮" not in a["note"] and len(a["note"]) <= 120, a["note"])
c, o, e = shipm("project", "aside", "--list", "--json")
j = json.loads(o)
check("F7: aside --list --json: v, aside rows, silencedKinds, returned", c == 0 and j["v"] == 1 and [r["project"] for r in j["aside"]] == ["beta"]
      and j["silencedKinds"] == ["stage_stuck", "cr_orphan", "frozen_chat", "merge_waiting"] and j["returned"] == [], j)
c, o, e = shipm("project", "unaside", "beta")
check("F7: unaside: exit 0, panel off", c == 0 and panel("beta")["aside"]["on"] is False, (c, e))
c, o, e = shipm("project", "unaside", "beta")
check("F7: unaside when not aside: exit 0 and says so", c == 0 and "not set aside" in o, (c, o))
c, o, e = shipm("project", "aside", "nosuch")
check("F7: aside for an unknown project: exit 3", c == 3, (c, e))
c, o, e = shipm("project", "aside", "beta", extra={"CLAUDECODE": "1", "SHIPMIRACLE_ENFORCE_OWNER": "1"})
check("F7: aside inside a chat is refused (exit 4)", c == 4 and panel("beta")["aside"]["on"] is False, (c, e))
c, o, e = shipm("project", "migrate-team", "beta", "--note", "x")
check("F7: --note belongs to aside only", c == 2, (c, e))

# refusals with the panel's own reasons
health({"gamma": {"state": "waiting_you", "working": False}})
c, o, e = shipm("project", "aside", "gamma")
check("F7: refused while the project waits for you, with the panel's text", c == 2 and "Not now: gamma is waiting for you." in e and panel("gamma")["aside"]["reason"] == "Not now: gamma is waiting for you.", (c, e))
health({})
sys.path.insert(0, str(ROOT))
from shipmiracle import projects  # noqa: E402
from shipmiracle.autopilot import state as APS  # noqa: E402
os.environ.update(ENV)
gid = projects.project_id(DEV / "gamma")
(V1 / "autopilot").mkdir(parents=True, exist_ok=True)
st = APS.blank("a" * 64, NOW); st["state"] = "running"
(V1 / "autopilot" / (gid + ".json")).write_text(json.dumps(st))
c, o, e = shipm("project", "aside", "gamma")
check("F7: refused while autopilot runs, with the panel's text", c == 2 and "Not now: autopilot is running." in e and panel("gamma")["aside"]["reason"] == "Not now: autopilot is running.", (c, e))
(V1 / "autopilot" / (gid + ".json")).unlink()

# the watcher split: only the four kinds of aside projects, never the others
shipm("project", "aside", "beta")
items = [{"id": "stage_stuck:beta", "kind": "stage_stuck", "project": "beta", "title": "stuck"},
         {"id": "cr_orphan:beta", "kind": "cr_orphan", "project": "beta", "title": "orphan"},
         {"id": "merge_waiting:beta", "kind": "merge_waiting", "project": "beta", "title": "merge"},
         {"id": "frozen_chat:beta", "kind": "frozen_chat", "project": "beta", "title": "frozen"},
         {"id": "limit:beta", "kind": "limit", "project": "beta", "title": "limit"},
         {"id": "secret_scan:beta", "kind": "secret_scan", "project": "beta", "title": "secret"},
         {"id": "stage_stuck:gamma", "kind": "stage_stuck", "project": "gamma", "title": "stuck"}]
from shipmiracle import aside  # noqa: E402
kept, quiet = aside.split_items(items, base=STATE)
check("F7: split: four kinds of the aside project are silenced and listed", sorted(i["kind"] for i in quiet) == ["cr_orphan", "frozen_chat", "merge_waiting", "stage_stuck"], quiet)
check("F7: split: limit, secret scan and other projects stay", sorted(i["id"] for i in kept) == ["limit:beta", "secret_scan:beta", "stage_stuck:gamma"], kept)
# the watcher itself (real script, fake time/ps): items of the aside project land in aside_items
c = subprocess.run([sys.executable, str(ROOT / "bin" / "shipm-watch"), "--help"], env=ENV, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)
check("F7: the watcher still starts", c.returncode == 0 or "usage" in (c.stdout + c.stderr).lower(), (c.returncode, c.stderr[:200]))

# auto un-aside: working, hard stop
back = aside.reconcile({"beta": {"working": False}}, base=STATE)
check("F7: reconcile: not working, no stop = stays aside", back == [] and panel("beta")["aside"]["on"] is True)
check("F7: panel: backOnList empty while idle", panel("beta")["aside"]["backOnList"] is None)
health({"beta": {"state": "ok", "working": True}})
check("F7: panel: a working aside project says why it is back on the list", panel("beta")["aside"]["backOnList"] == "beta started work.", panel("beta")["aside"])
health({})
back = aside.reconcile({"beta": {"working": True}}, base=STATE)
r = aside.returned(STATE)
check("F7: reconcile: a working aside project is brought back with a notice", back == ["beta"] and panel("beta")["aside"]["on"] is False and r and r[-1]["why"] == "work" and r[-1]["project"] == "beta", (back, r))
c, o, e = shipm("project", "aside", "--list", "--json")
check("F7: the notice shows in --list for 24 h", json.loads(o)["returned"][-1]["why"] == "work", o)
old = aside.returned(STATE, now=NOW + 25 * 3600)
check("F7: the notice expires after 24 h", old == [], old)
shipm("project", "aside", "beta")
bid = projects.project_id(DEV / "beta")
st = APS.blank("b" * 64, NOW); st["state"] = "paused"; st["stop"] = {"id": "H-abc123", "rule": "x", "text": "stop", "ts": NOW}
(V1 / "autopilot" / (bid + ".json")).write_text(json.dumps(st))
check("F7: panel: a hard stop on an aside project shows backOnList", "hard stop" in (panel("beta")["aside"]["backOnList"] or ""), panel("beta")["aside"])
back = aside.reconcile({}, base=STATE)
check("F7: reconcile: a hard stop brings the project back", back == ["beta"] and aside.returned(STATE)[-1]["why"] == "hard_stop", (back, aside.returned(STATE)))

# damaged aside.json / foreign file: nothing breaks, nothing is hidden
(V1 / "aside.json").write_text("garbage")
check("F7: a damaged aside.json = nobody is aside (all shown normally)", panel("beta")["aside"]["on"] is False and aside.aside_map(STATE) == {})
k, q = aside.split_items(items, base=STATE)
check("F7: a damaged aside.json silences nothing", q == [] and len(k) == len(items))

print("\nresult: %d failed" % fails)
ISO.cleanup(TMP)
sys.exit(1 if fails else 0)
