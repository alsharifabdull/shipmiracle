#!/usr/bin/env python3
"""shipm cr open|list|show|start|delta|render|abandon|advance as real subprocesses (SHIPMIRACLE_TEST=1, temp git projects and SHIPMIRACLE_* folders): outputs,
impact text, --json schema, exit codes 0/1/2/3/4, owner guard for abandon/advance, trust refusal, title sanitising, unicode/RTL titles,
the flow open -> queue -> start -> delta -> abandon end to end. Run: python3 tests/shipmiracle_cr_cli_test.py"""
import json, os, pathlib, re, stat, subprocess, sys, tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
SHIPM = str(ROOT / "bin" / "shipm")
TMP = pathlib.Path(tempfile.mkdtemp(prefix="shipmiracle-crcli-")).resolve()
HOME, DEV, STATE, CONF, WS = (TMP / n for n in ("home", "dev", "state", "config", "ws"))
ENV = dict(os.environ, SHIPMIRACLE_TEST="1", SHIPMIRACLE_HOME=str(HOME), SHIPMIRACLE_DEV=str(DEV), SHIPMIRACLE_STATE=str(STATE), SHIPMIRACLE_CONFIG=str(CONF), SHIPMIRACLE_WS=str(WS), HOME=str(HOME))
for k in ("SHIPMIRACLE_DEBUG", "CLAUDECODE", "SHIPMIRACLE_ENFORCE_OWNER"):
    ENV.pop(k, None)
CHAT = dict(ENV, CLAUDECODE="1", SHIPMIRACLE_ENFORCE_OWNER="1")
REAL = pathlib.Path(os.path.expanduser("~"))
CANARY = [REAL / ".config" / "shipmiracle" / "registry.json", REAL / ".config" / "shipmiracle" / "config.json", REAL / ".claude" / "settings.json"]
before = [(p.stat().st_mtime_ns if p.exists() else None) for p in CANARY]
os.environ.update({k: v for k, v in ENV.items() if k.startswith("SHIPMIRACLE_")})
sys.path.insert(0, str(ROOT))
from shipmiracle import projects  # noqa: E402

fails = 0
def check(name, ok, info=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(info)[:700]))
    fails += 0 if ok else 1

def shipm(*args, env=None, cwd=None):
    r = subprocess.run([sys.executable, SHIPM] + list(args), env=env or ENV, capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL, cwd=cwd)
    return r.returncode, r.stdout, r.stderr

HOME.mkdir(parents=True)
(HOME / ".gitconfig").write_text("[user]\n name = t\n email = t@example.com\n[init]\n defaultBranch = main\n[commit]\n gpgsign = false\n")
(WS / "config").mkdir(parents=True)
(WS / "config" / "flow.json").write_text('{\n  "default": "strict",\n  "projects": {}\n}\n')
for n in ("alpha", "beta"):
    d = DEV / n
    d.mkdir(parents=True)
    for c in (["init", "-q"], ["add", "-A"]):
        pass
    subprocess.run(["git", "-C", str(d), "init", "-q"], env=ENV, check=True)
    (d / "a.txt").write_text("1\n")
    subprocess.run(["git", "-C", str(d), "add", "-A"], env=ENV, check=True)
    subprocess.run(["git", "-C", str(d), "commit", "-q", "-m", "init"], env=ENV, check=True)
A, B = str(DEV / "alpha"), str(DEV / "beta")
STATE.mkdir(parents=True, exist_ok=True)

# ---- no playbook: refused, with the hint ----
code, out, err = shipm("cr", "open", "first", "--project", A)
check("open without a playbook: exit 1 and 'shipm playbook' hint", code == 1 and "shipm playbook" in err and err.startswith("shipm: "), (code, err))
code, out, err = shipm("cr", "list", "--project", A)
check("list without a playbook still works (read-only): exit 0", code == 0 and "No change requests" in out, (code, out, err))
code, out, err = shipm("cr", "show", "--next", "--project", A)
check("show --next without a playbook: exit 1", code == 1, (code, err))

# playbook for alpha (software) and beta (ops: always full lane)
import time
(STATE / "health.json").write_text(json.dumps({"ts": time.time(), "chats": {"alpha": {"chats": 0}, "beta": {"chats": 0}}}))
check("set type software", shipm("playbook", "set", "type", "software", "--project", "alpha")[0] == 0)
check("set type ops", shipm("playbook", "set", "type", "ops", "--project", "beta")[0] == 0)

# ---- errors that are not about the playbook ----
code, out, err = shipm("cr", "open", "x", cwd=str(TMP))
check("outside any project: exit 3", code == 3 and err.startswith("shipm: "), (code, err))
code, out, err = shipm("cr", "open", "x", "--project", str(TMP / "nowhere"))
check("--project that does not exist: exit 3", code == 3, (code, err))
code, out, err = shipm("cr", "open", "--project", A)
check("open without a title: exit 2", code == 2, (code, err))
code, out, err = shipm("cr", "open", "   \x07\x1b  ", "--project", A)
check("open with a title that is only control characters: exit 2", code == 2, (code, err))
code, out, err = shipm("cr", "open", "x", "--lane", "slow", "--project", A)
check("bad --lane: exit 2", code == 2, (code, err))
code, out, err = shipm("cr", "bogus")
check("unknown cr action: exit 2", code == 2, (code, err))
code, out, err = shipm("cr", "start", "nope", "--project", A)
check("bad CR id: exit 2", code == 2, (code, err))
code, out, err = shipm("cr", "show", "CR-099", "--project", A)
check("show of a CR that does not exist: exit 3", code == 3, (code, err))
code, out, err = shipm("cr", "open", "x", "--lane", "fast", "--project", B)
check("ops type has no fast lane: exit 1 with the reason", code == 1 and "fast" in err, (code, err))

# ---- open (active) ----
TITLE = "إصلاح RTL fix on login"
code, out, err = shipm("cr", "open", TITLE, "--lane", "full", "--project", A)
check("open: exit 0, id, title, lane and the next step", code == 0 and out.startswith('CR-001 opened: "%s"' % TITLE) and "active" in out and "CR-001:" in out, (code, out, err))
wj = pathlib.Path(A) / ".shipmiracle" / "work.json"
d = json.loads(wj.read_text())
check("open: .shipmiracle/work.json rendered with the CR (unicode kept) and mode 0644", d["active"] == "CR-001" and d["crs"][0]["title"] == TITLE and stat.S_IMODE(wj.stat().st_mode) == 0o644, d)
pid = projects.project_id(A)
snaps = list((STATE / "v1" / "cr").glob("%s.CR-001.snap.json" % pid))
snap = json.loads(snaps[0].read_text()) if snaps else {}
check("open: the diffstat snapshot was saved first (base is a commit id)", bool(snaps) and re.fullmatch(r"[0-9a-f]{40,64}", snap.get("base", "")) is not None, snap)
check("open: base recorded in the CR equals the snapshot", d["crs"][0]["base"] == snap.get("base"), d["crs"][0].get("base"))
log = STATE / "v1" / "cr" / (pid + ".jsonl")
check("open: log line in the state folder, 0600", log.exists() and stat.S_IMODE(log.stat().st_mode) == 0o600)
check("open: .shipmiracle/ not committed by cr open (engine files stay out of git until the owner commits)", subprocess.run(["git", "-C", A, "log", "--oneline"], env=ENV, capture_output=True, text=True).stdout.count("\n") >= 2)

# ---- open --json schema ----
code, out, err = shipm("cr", "open", "Arabic numerals ٠١٢٣", "--project", A, "--json")
j = json.loads(out)
check("open --json (queued): v=1, cr, queued, impact, next", code == 0 and j["v"] == 1 and j["queued"] is True and j["cr"]["id"] == "CR-002" and j["cr"]["status"] == "queued"
      and isinstance(j["impact"], str) and set(j["next"]) >= {"cr", "stage", "role", "agent", "waiting_on", "text"}, (code, out))
IMPACT = ("CR-002 queued behind CR-001 (at Scope). Impact check: ask planner whether CR-002 changes CR-001's scope or plan (brief: both titles, CR-001's plan, "
          "`git diff --stat`). If it does, run `shipm cr delta CR-001 --from CR-002 --reset-to plan` (the owner approves the new plan). If not, leave it queued.")
check("queued: the exact impact text", j["impact"] == IMPACT, j["impact"])
code, out, err = shipm("cr", "open", "third request", "--project", A)
check("open (queued, text mode) prints only the impact text", code == 0 and out.strip().startswith("CR-003 queued behind CR-001 (at Scope). Impact check:") and "`shipm cr delta CR-001 --from CR-003 --reset-to plan`" in out, out)

# ---- list / show ----
code, out, err = shipm("cr", "list", "--project", A)
lines = out.splitlines()
check("list: one line per CR, active first", code == 0 and len(lines) == 3 and lines[0].startswith("CR-001") and "open" in lines[0] and lines[1].startswith("CR-002") and "queued" in lines[1], out)
code, out, err = shipm("cr", "list", "--project", A, "--json")
j = json.loads(out)
check("list --json: v=1, active, queue, crs", j["v"] == 1 and j["active"] == "CR-001" and j["queue"] == ["CR-002", "CR-003"] and [c["id"] for c in j["crs"]] == ["CR-001", "CR-002", "CR-003"], j)
code, out, err = shipm("cr", "show", "--project", A)
check("show (no id) = the active CR: title, status, stages, diff, next", code == 0 and "CR-001" in out and TITLE in out and "Status: open" in out and "Stages:" in out and "Diff:" in out and "Next:" in out, out)
code, out, err = shipm("cr", "show", "CR-002", "--project", A)
check("show CR-002 (queued)", code == 0 and "Status: queued" in out, out)
code, out, err = shipm("cr", "show", "CR-001", "--project", A, "--json")
j = json.loads(out)
check("show --json: v=1, cr with stages, next", j["v"] == 1 and j["cr"]["id"] == "CR-001" and set(j["cr"]["stages"]) >= {"scope", "plan", "approve", "do", "verify", "review", "deliver", "learn"} and j["next"]["cr"] == "CR-001", j)
code, out, err = shipm("cr", "show", "--next", "--project", A)
check("show --next: the engine's next_action text", code == 0 and out.startswith("CR-001:") and out.count("\n") == 1, out)
code, out, err = shipm("cr", "show", "--next", "--json", "--project", A)
j = json.loads(out)
check("show --next --json: v=1 and next_action fields", j["v"] == 1 and j["next"]["waiting_on"] in ("lead", "owner", "none") and j["next"]["stage"] in ("scope", "plan"), j)
code, out, err = shipm("cr", "show", "CR-002", "--next", "--project", A)
check("show CR-002 --next (not active): exit 2", code == 2, (code, err))

# ---- start (WIP = 1) ----
code, out, err = shipm("cr", "start", "CR-002", "--project", A)
check("start while another CR is active: exit 1 (one at a time)", code == 1 and "wip" in err, (code, err))

# ---- delta: CR-002 changes CR-001 ----
code, out, err = shipm("cr", "delta", "CR-001", "--from", "CR-002", "--reset-to", "plan", "--project", A)
check("delta: CR-002 merged into CR-001, CR-001 back to Plan, next printed", code == 0 and "CR-002 merged into CR-001" in out and "back to Plan" in out, (code, out, err))
code, out, err = shipm("cr", "delta", "CR-001", "--from", "CR-002", "--reset-to", "plan", "--project", A)
check("delta again (source no longer queued): exit 1", code == 1, (code, err))
code, out, err = shipm("cr", "delta", "CR-001", "--from", "CR-003", "--project", A)
check("delta without --reset-to: exit 2", code == 2, (code, err))
code, out, err = shipm("cr", "delta", "CR-001", "--from", "CR-003", "--reset-to", "approve", "--project", A)
check("delta with a bad --reset-to: exit 2", code == 2, (code, err))
code, out, err = shipm("cr", "delta", "CR-001", "--from", "CR-003", "--reset-to", "scope", "--project", A, "--json", env=CHAT)
j = json.loads(out)
check("delta is allowed for anyone (also from a chat), --json v=1", code == 0 and j["v"] == 1 and j["merged"] == "CR-003" and j["reset_to"] == "scope", (code, out, err))

# ---- owner-only: abandon / advance ----
code, out, err = shipm("cr", "abandon", "CR-001", "--project", A, env=CHAT)
check("abandon from a chat: refused, exit 4", code == 4, (code, err))
code, out, err = shipm("cr", "advance", "CR-001", "--stage", "scope", "--reason", "x", "--project", A, env=CHAT)
check("advance from a chat: refused, exit 4", code == 4, (code, err))
code, out, err = shipm("cr", "advance", "CR-001", "--stage", "scope", "--project", A)
check("advance without --reason: exit 2", code == 2, (code, err))
code, out, err = shipm("cr", "advance", "CR-001", "--stage", "verify", "--reason", "skip", "--project", A)
check("advance out of order: exit 1", code == 1 and "order" in err, (code, err))
code, out, err = shipm("cr", "advance", "CR-001", "--stage", "scope", "--reason", "owner knows the scope", "--project", A)
check("advance (owner, with a reason): the stage passes, next printed", code == 0 and "passed by the owner" in out, (code, out, err))
log_text = log.read_text()
check("advance is logged as override with the reason", '"op":"override"' in log_text and "owner knows the scope" in log_text)
# P5 security M5: a terminal and a typed confirmation, unless fully temp sandboxed; the override line records its origin
check("advance override line records the origin (tty no, chat no)", '"tty":false' in log_text.replace(" ", "") and '"chat":false' in log_text.replace(" ", ""), log_text[-400:])
OWNER = dict(ENV, SHIPMIRACLE_ENFORCE_OWNER="1")        # a terminal-less owner run with the sandbox shortcut off
def shipmiracle_notty(*args, env):
    r = subprocess.run([sys.executable, SHIPM] + list(args), env=env, capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL, start_new_session=True)
    return r.returncode, r.stdout, r.stderr
code, out, err = shipmiracle_notty("cr", "abandon", "CR-001", "--project", A, env=OWNER)
check("abandon without a terminal (shortcut off): refused, exit 4, needs a terminal", code == 4 and "terminal" in err, (code, err))
code, out, err = shipmiracle_notty("cr", "advance", "CR-001", "--stage", "plan", "--reason", "x", "--project", A, env=OWNER)
check("advance without a terminal (shortcut off): refused, exit 4", code == 4 and "terminal" in err, (code, err))
sys.path.insert(0, str(ROOT))
from shipmiracle.playbook import cli as pcli  # noqa: E402
from shipmiracle import SafetyError  # noqa: E402
def conf(typed, what="shipm cr abandon", exp="CR-001", enforce=True):
    old = os.environ.get("SHIPMIRACLE_ENFORCE_OWNER"), pcli._tty_ask
    try:
        if enforce:
            os.environ["SHIPMIRACLE_ENFORCE_OWNER"] = "1"
        pcli._tty_ask = lambda prompt: typed
        pcli.confirm_owner(what, exp)
        return "ok"
    except SafetyError as e:
        return "refused"
    finally:
        pcli._tty_ask = old[1]
        if old[0] is None:
            os.environ.pop("SHIPMIRACLE_ENFORCE_OWNER", None)
        else:
            os.environ["SHIPMIRACLE_ENFORCE_OWNER"] = old[0]
check("confirm_owner: the typed CR id is accepted", conf("CR-001") == "ok")
check("confirm_owner: a wrong or empty answer is refused", conf("CR-002") == "refused" and conf("") == "refused" and conf("yes") == "refused")
check("confirm_owner: no terminal (None) is refused", conf(None) == "refused")
_sb = pcli.paths.sandboxed
pcli.paths.sandboxed = lambda: True
check("confirm_owner: the fully temp sandbox accepts without typing", conf(None, enforce=False) == "ok")
pcli.paths.sandboxed = _sb
code, out, err = shipm("cr", "open", "queued for abandon", "--project", A)
code, out, err = shipm("cr", "abandon", "CR-004", "--project", A, "--json")
j = json.loads(out)
check("abandon a queued CR (owner): --json v=1", code == 0 and j["v"] == 1 and j["abandoned"] is True, (code, out, err))
code, out, err = shipm("cr", "abandon", "CR-001", "--project", A)
check("abandon the active CR: exit 0; with guided autopilot the queue is empty so no active CR", code == 0 and "CR-001 abandoned." in out, (code, out, err))
code, out, err = shipm("cr", "abandon", "CR-001", "--project", A)
check("abandon a closed CR: exit 1", code == 1, (code, err))
code, out, err = shipm("cr", "list", "--project", A, "--json")
j = json.loads(out)
st = {c["id"]: c["status"] for c in j["crs"]}
check("end state: CR-002/CR-003 merged, CR-004 abandoned (render keeps the last 3 finished), nothing active", st == {"CR-002": "merged", "CR-003": "merged", "CR-004": "abandoned"} and j["active"] is None, st)
code, out, err = shipm("cr", "show", "CR-001", "--project", A)
check("the abandoned CR-001 is still readable from the log (show): status abandoned", code == 0 and "Status: abandoned" in out, (code, out, err))

# ---- queue: start a queued CR once the active one is gone ----
code, out, err = shipm("cr", "open", "one", "--project", B)
code, out, err = shipm("cr", "open", "two", "--project", B)
code, out, err = shipm("cr", "abandon", "CR-001", "--project", B)
code, out2, err2 = shipm("cr", "list", "--project", B, "--json")
j = json.loads(out2)
check("guided: abandoning the active CR starts the queued one", j["active"] == "CR-002", j)
code, out, err = shipm("playbook", "set", "autopilot", "manual", "--project", "beta")
code, out, err = shipm("cr", "open", "three", "--project", B)
code, out, err = shipm("cr", "abandon", "CR-002", "--project", B)
code, out, err = shipm("cr", "show", "--next", "--project", B)
check("manual: nothing starts by itself; next says to start the queued CR", code == 0 and "shipm cr start CR-003" in out, out)
code, out, err = shipm("cr", "start", "CR-003", "--project", B)
check("start CR-003 (anyone): exit 0 and next printed", code == 0 and out.startswith("CR-003 started."), (code, out, err))
code, out, err = shipm("cr", "start", "CR-003", "--project", B)
check("start an already active CR: exit 1", code == 1, (code, err))

# ---- title sanitising ----
long_t = "x" * 300
code, out, err = shipm("cr", "open", long_t, "--project", A, "--json")
j = json.loads(out)
check("title is cut to 120 characters", code == 0 and len(j["cr"]["title"]) == 120, len(j["cr"]["title"]))
code, out, err = shipm("cr", "open", "bell\x07 and\x1b[31m escape\nnewline", "--project", A, "--json")
j = json.loads(out)
check("control characters are stripped from the title", code == 0 and not any(ord(c) < 32 or ord(c) == 127 for c in j["cr"]["title"]) and "newline" in j["cr"]["title"], j["cr"]["title"])
code, out, err = shipm("cr", "open", "bidi ‮ attack ​", "--project", A, "--json")
j = json.loads(out)
check("bidi/format characters are stripped too", code == 0 and "‮" not in j["cr"]["title"] and "​" not in j["cr"]["title"], j["cr"]["title"])
code, out, err = shipm("cr", "open", "rm -rf $(whoami) `id` ; echo", "--project", A, "--json")
check("shell characters in a title are only text", code == 0 and json.loads(out)["cr"]["title"] == "rm -rf $(whoami) `id` ; echo", out)

# ---- render ----
code, out, err = shipm("cr", "render", "--project", A)
check("render: exit 0, count and compaction reported", code == 0 and out.startswith("rendered .shipmiracle/work.json") and "compacted 0" in out, (code, out, err))
wj.write_text('{"v":1,"render":"shipmiracle-engine","active":"CR-001","queue":[],"crs":[{"id":"CR-001","status":"delivered"}]}\n')
code, out, err = shipm("cr", "render", "--project", A)
d = json.loads(wj.read_text())
check("render rewrites a forged work.json from the log", code == 0 and d["active"] != "CR-001" and all(c.get("status") != "delivered" for c in d["crs"]), d)
code, out, err = shipm("cr", "render", "--project", A, "--json")
j = json.loads(out)
check("render --json: v=1", code == 0 and j["v"] == 1 and j["rendered"] is True and "compacted" in j, out)
ev = (STATE / "v1" / "events.jsonl")
evtext = "".join(p.read_text() for p in (STATE / "v1").glob("events*")) if (STATE / "v1").exists() else ""
check("the forged work.json was reported as cr.work_forged", "cr.work_forged" in evtext, evtext[-300:])

# ---- an untrusted playbook (edited file) refuses writes, not reads ----
pbf = pathlib.Path(A) / ".shipmiracle" / "playbook.json"
pb = json.loads(pbf.read_text())
pb["overrides"] = {"risk_paths": ["nothing/**"]}
pbf.write_text(json.dumps(pb))
code, out, err = shipm("cr", "open", "after tamper", "--project", A)
check("open with an edited (untrusted) playbook.json: exit 4", code == 4 and "not trusted" in err, (code, err))
code, out, err = shipm("cr", "list", "--project", A)
check("list still works", code == 0, (code, err))

# ---- canary ----
after = [(p.stat().st_mtime_ns if p.exists() else None) for p in CANARY]
check("canary: real registry, config and settings untouched", before == after)
print("\n%s (%d failed)" % ("ALL PASS" if not fails else "FAILURES", fails))
sys.exit(1 if fails else 0)
