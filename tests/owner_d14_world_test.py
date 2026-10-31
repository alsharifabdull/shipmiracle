#!/usr/bin/env python3
"""owner_d14_world_test: checklist D14, the owner-proof recheck fixes that need the autopilot world (tests/autopilot_engine_fixture.py: fully temp HOME / DEV / STATE / config / workspace,
SHIPMIRACLE_TEST=1, project `sandbox`, local bare origin, no network, no real claude, no real autopilot run: every run here is the test world's own).
  M2  every hook call of a STANDING run checks that the Claude sandbox setting named by the P6-1 record is on for the auto worktree; missing -> the run pauses `standing_off` and the call is refused.
      Dormant for A/B runs and for a separate account (the account is the boundary). Fake records and fake settings only.
  m4  `charter set --until=disabled` checks standing_allowed and the prerequisites BEFORE the owner is asked for the touch;
  m5  `admit` and `checkpoint` prune the stale admissions only AFTER the owner check passed: a refused proof leaves the state byte-identical;
  m6  standing_allowed refuses a P6-1 record whose time is more than 300 s in the future.
Run: python3 tests/owner_d14_world_test.py"""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import shipmiracle_isolation; shipmiracle_isolation.apply_to_environ()   # test isolation
import contextlib, hashlib, io, json, os, pathlib, re, sys, time, types

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import autopilot_engine_fixture as X  # noqa: E402  (builds the temp world, rewrites os.environ)
from autopilot_engine_fixture import check, sh, S, PID, MAIN, STATE, engine, store, F, ch  # noqa: E402
from shipmiracle import registry, ShipmiracleError  # noqa: E402
from shipmiracle.autopilot import cli as apcli  # noqa: E402
from shipmiracle import owner  # noqa: E402
import shipmiracle.config as acfg  # noqa: E402
import shipmiracle.hooks.autopilot as AP  # noqa: E402

ROOT = HERE.parent
X.build()
AP._PS_CHAIN_OVERRIDE = ["claude", "zsh", "Terminal"]
owner._ACCOUNT_OVERRIDE = lambda: True
CONF = pathlib.Path(os.environ["SHIPMIRACLE_CONFIG"])
MARKER = CONF / "throwaway-account"
HOMEDIR = pathlib.Path(os.environ["HOME"])
CLAUDE_DIR = pathlib.Path(os.environ.get("CLAUDE_CONFIG_DIR") or (HOMEDIR / ".claude"))
USER_SETTINGS = CLAUDE_DIR / "settings.json"
RISK = "until I disable it"
SCOPE = "src/**,tests/**,docs/**,package.json"
SHIPM = str(ROOT / "bin" / "shipm")
LINES = list(owner.P61_LINES)


def open_cr(tag):
    code, out, err = sh([sys.executable, SHIPM, "cr", "open", "change " + tag, "--project", str(MAIN)])
    m = re.search(r"CR-\d+", out)
    if not m:
        raise SystemExit("open_cr failed: %s %s %s" % (code, out[-300:], err[-300:]))
    return m.group(0)


def purge_crs():
    from shipmiracle.playbook import gate
    rules = gate.stage_rules(str(MAIN))

    def fn(work):
        trs = []
        for c in list(work["crs"]):
            if c["status"] in ("open", "queued", "blocked"):
                c["lease"] = None
                trs += engine.abandon(work, c["id"], {"kind": "owner_override", "by": "cli", "ts": int(time.time()), "data": {"reason": "test"}}, rules)
        return None, trs
    store.transact(str(MAIN), fn)


def vis():
    X.visibility.write_entry(str(X.ORIGIN), True, now=time.time())


def standing_charter(crs):
    return {"goal": "g", "scope": ch.clean_scope(SCOPE), "ends": crs, "budget": 10, "deps": {"mode": "none"}, "until": "disabled", "day": 4, "crs_day": 3}


def standing_run(tag, n=2):
    """A standing run, running, in its auto worktree. -> (crs, Chat)."""
    X.cleanup(); purge_crs(); vis(); F.write_plan(34); X.fresh_health()
    crs = [open_cr("%s %d" % (tag, i)) for i in range(n)]
    ch.store_charter(PID, standing_charter(crs), "cli")
    code, out, err = sh([sys.executable, SHIPM, "autopilot", "start", "--project", "sandbox", "--yes", "--ack-risk", RISK])
    if code != 0:
        raise SystemExit("start failed: %s %s" % (out, err))
    return crs, X.Chat(X.wt_path(crs[0]), sid="d14%05d" % int(time.time() * 1000 % 100000))


def run_state():
    return S.read(PID)


def write_user_settings(obj):
    CLAUDE_DIR.mkdir(parents=True, exist_ok=True)
    if obj is None:
        if USER_SETTINGS.exists():
            USER_SETTINGS.unlink()
    else:
        USER_SETTINGS.write_text(obj if isinstance(obj, str) else json.dumps(obj))


def write_wt_settings(chat, name, obj):
    d = chat.wt / ".claude"
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    if obj is None:
        if p.exists():
            p.unlink()
    else:
        p.write_text(obj if isinstance(obj, str) else json.dumps(obj))
    return p


def denied(o):
    h = o.get("hookSpecificOutput") or {}
    return h.get("permissionDecision") == "deny", h.get("permissionDecisionReason", "")


def set_standing_basis(record=None, marker=False):
    """The reason option C is allowed: the P6-1 record (fake) and / or the separate-account marker."""
    if MARKER.exists():
        MARKER.unlink()
    if marker:
        MARKER.write_text("test\n")
    pf = CONF / "probes.json"
    if pf.exists():
        pf.unlink()
    if record == "pass":
        owner.record_probe("pass", LINES)
    elif isinstance(record, dict):
        owner.record_probe("pass", LINES)
        d = json.loads(pf.read_text())
        d["P6-1"].update(record)
        pf.write_text(json.dumps(d))


# ================================================================ M2 the sandbox check on every hook call of a standing run
print("# M2")
set_standing_basis(marker=True)
acfg.set("autopilot.standing.enabled", "on")
crs, chat = standing_run("m2a")
write_user_settings(None)
o = chat.hk("PreToolUse", tool_name="Bash", tool_input={"command": "ls src"})
d, why = denied(o)
check("M2 separate account (the marker): no sandbox setting is needed, the call is not refused for it", run_state()["state"] == "running" and "standing" not in why.lower(), (run_state(), why))
set_standing_basis("pass")
write_user_settings(None)
o = chat.hk("PreToolUse", tool_name="Bash", tool_input={"command": "ls src"})
d, why = denied(o)
st = run_state()
check("M2 P6-1 record, no sandbox setting anywhere: the run pauses standing_off", st["state"] == "paused" and st["paused_reason"] == "standing_off", st)
check("M2 ... and that call is refused, with a plain sentence that names the sandbox", d and "sandbox" in why.lower() and "Traceback" not in why, (d, why))
check("M2 ... an autopilot.paused event with reason standing_off is recorded", any(e.get("data", {}).get("reason") == "standing_off" for e in X.events("autopilot.paused")), X.events("autopilot.paused")[-3:])
o2 = chat.hk("PreToolUse", tool_name="Read", tool_input={"file_path": str(chat.wt / "src/a.py")})
check("M2 ... a read stays allowed while paused (the pause is the existing standing_off state)", not denied(o2)[0], o2)

# resume path: the daily check-in clears standing_off (existing behaviour), the sandbox setting must be on again before the next hook call lets the run work
for label, user, wt_local, want_running in (
        ("user settings sandbox.enabled true", {"sandbox": {"enabled": True}}, None, True),
        ("user settings sandbox.enabled false", {"sandbox": {"enabled": False}}, None, False),
        ("user settings sandbox.enabled the string 'true'", {"sandbox": {"enabled": "true"}}, None, False),
        ("user settings sandbox is a bare true", {"sandbox": True}, None, False),
        ("user settings malformed JSON", "{not json", None, False),
        ("user settings an array", [1, 2], None, False),
        ("user on, worktree settings.local.json off (the nearer file wins)", {"sandbox": {"enabled": True}}, {"sandbox": {"enabled": False}}, False),
        ("user off, worktree settings.local.json on (the nearer file wins)", {"sandbox": {"enabled": False}}, {"sandbox": {"enabled": True}}, True),
        ("no user file, worktree settings.local.json on", None, {"sandbox": {"enabled": True}}, True)):
    crs, chat = standing_run("m2b")
    write_user_settings(user)
    loc = write_wt_settings(chat, "settings.local.json", wt_local)
    o = chat.hk("PreToolUse", tool_name="Bash", tool_input={"command": "ls src"})
    st = run_state()
    d, why = denied(o)
    if want_running:
        check("M2 %s: the run keeps running, no standing_off" % label, st["state"] == "running" and not (d and "sandbox" in why.lower()), (st["state"], st.get("paused_reason"), why))
    else:
        check("M2 %s: the run pauses standing_off and the call is refused" % label, st["state"] == "paused" and st["paused_reason"] == "standing_off" and d, (st["state"], st.get("paused_reason"), d, why))
    if loc.exists():
        loc.unlink()

# the setting name comes from the record, but only a known name counts (a forged record cannot point the check at a key it controls)
crs, chat = standing_run("m2c")
set_standing_basis({"sandbox_setting": "evil.enabled"})
write_user_settings({"evil": {"enabled": True}})
o = chat.hk("PreToolUse", tool_name="Bash", tool_input={"command": "ls src"})
check("M2 a record naming an unknown setting falls back to sandbox.enabled (the unknown key does not count)", run_state()["paused_reason"] == "standing_off", run_state())
crs, chat = standing_run("m2d")
set_standing_basis({"sandbox_setting": "sandbox.enabled"})
write_user_settings({"sandbox": {"enabled": True}})
o = chat.hk("PreToolUse", tool_name="Bash", tool_input={"command": "ls src"})
check("M2 a record naming sandbox.enabled with the setting on keeps the run going", run_state()["state"] == "running", run_state())
check("M2 owner.sandbox_setting() reads the name from the P6-1 record (default sandbox.enabled)", owner.sandbox_setting() == "sandbox.enabled")
set_standing_basis("pass")
check("M2 ... and a record without a name gives the default", owner.sandbox_setting() == "sandbox.enabled")

# D14 #7: a closer settings file that exists but cannot be read pauses the run (it does not fall through to a user file that says true)
set_standing_basis("pass")
crs, chat = standing_run("m2e")
write_user_settings({"sandbox": {"enabled": True}})
loc = write_wt_settings(chat, "settings.local.json", "{broken json")
o = chat.hk("PreToolUse", tool_name="Bash", tool_input={"command": "ls src"})
check("D14 #7 an unparseable worktree settings.local.json pauses the run (standing_off), the user file saying true does not rescue it", run_state()["state"] == "paused" and run_state()["paused_reason"] == "standing_off" and denied(o)[0], (run_state()["state"], denied(o)))
loc.unlink()
# D14 #7: the sandbox object is hashed in the P6-1 record; a widened object pauses the run
write_user_settings({"sandbox": {"enabled": True, "excludedCommands": ["git"]}})
set_standing_basis("pass")
check("D14 #7 the P6-1 record carries a sha256 of the user's `sandbox` settings", owner.sandbox_hash_recorded() == owner.sandbox_digest({"enabled": True, "excludedCommands": ["git"]}), owner.sandbox_hash_recorded())
crs, chat = standing_run("m2f")
o = chat.hk("PreToolUse", tool_name="Bash", tool_input={"command": "ls src"})
check("D14 #7 the same sandbox object as tested: the run keeps running", run_state()["state"] == "running", (run_state(), denied(o)))
write_user_settings({"sandbox": {"enabled": True, "excludedCommands": ["git", "curl"]}})
o = chat.hk("PreToolUse", tool_name="Bash", tool_input={"command": "ls src"})
d_, why_ = denied(o)
check("D14 #7 a widened sandbox object (an extra excluded command) pauses the run with the 'differ' sentence and refuses the call", run_state()["state"] == "paused" and run_state()["paused_reason"] == "standing_off" and d_ and "differ" in why_, (run_state()["state"], d_, why_))
crs, chat = standing_run("m2g")
write_user_settings({"sandbox": {"enabled": True, "excludedCommands": ["git"]}})
loc = write_wt_settings(chat, "settings.json", {"sandbox": {"enabled": True, "network": {"allowedDomains": ["evil.example"]}}})
o = chat.hk("PreToolUse", tool_name="Bash", tool_input={"command": "ls src"})
check("D14 #7 a worktree settings.json that carries a different sandbox object (network widened) pauses the run", run_state()["paused_reason"] == "standing_off", run_state())
loc.unlink()
set_standing_basis("pass")
write_user_settings(None)

# dormant for an A/B run: no sandbox setting, no pause
write_user_settings(None)
cr, chat = X.new_run("m2ab")
o = chat.hk("PreToolUse", tool_name="Bash", tool_input={"command": "ls src"})
check("M2 an A/B run (not standing) is never paused for the sandbox setting (dormant while option C is off)", run_state()["state"] == "running" and not run_state().get("paused_reason"), run_state())
check("M2 option C stays OFF by default and unsupported-until-disabled is untouched", acfg.SCHEMA["autopilot.standing.enabled"][1]() in (False, None), acfg.SCHEMA["autopilot.standing.enabled"][1]())
set_standing_basis(marker=True)

# ================================================================ m6 a P6-1 record from the future
print("# m6")
set_standing_basis()
T = 1_800_000_000
owner.record_probe("pass", LINES, now=T + 301)
ok, why = owner.standing_allowed(now=T)
check("m6 a record dated 301 s in the future is refused", not ok and "future" in why, (ok, why))
owner.record_probe("pass", LINES, now=T + 300)
ok, why = owner.standing_allowed(now=T)
check("m6 a record dated exactly 300 s ahead (clock slack) is accepted", ok, why)
owner.record_probe("pass", LINES, now=T + 299)
ok, why = owner.standing_allowed(now=T)
check("m6 a record 299 s ahead is accepted", ok, why)
owner.record_probe("pass", LINES, now=T - 10)
ok, why = owner.standing_allowed(now=T)
check("m6 a record from the past is accepted (positive control)", ok, why)
owner.record_probe("pass", LINES, now=T + 10 * 86400)
ok, why = owner.standing_allowed(now=T)
check("m6 a record ten days ahead (a forged long-lived record) is refused", not ok and "future" in why, (ok, why))
ok, why = owner.standing_allowed(now=T + 10 * 86400 + 31 * 86400)
check("m6 ... and the 30-day expiry still applies from its own date", not ok and "30 days" in why, (ok, why))
set_standing_basis(marker=True)

# ================================================================ plumbing for the CLI cases
class Fake(owner.Provider):
    def __init__(self, name, tier, probe="ready", ask="ok"):
        self.name, self.tier, self._probe, self._ask, self.calls = name, tier, probe, ask, []

    def probe(self):
        return self._probe

    def ask(self, reason, timeout):
        self.calls.append(reason)
        return self._ask


def ns(**kw):
    d = dict(action=None, rargs=[], project="sandbox", goal=None, scope=None, budget=None, time=None, deps=None, ends=None, until=None, day=None, crs_day=None, yes=False, ack=None,
             ack_risk=None, launch=False, json=False, lines=None)
    d.update(kw)
    return types.SimpleNamespace(**d)


def cli(action, *rargs, **kw):
    out = io.StringIO()
    err, rc = "", 0
    old = (apcli._is_tty, apcli._ask)
    apcli._is_tty = lambda: False
    apcli._ask = lambda prompt: ""
    try:
        with contextlib.redirect_stdout(out):
            rc = apcli.run(ns(action=action, rargs=list(rargs), **kw))
    except ShipmiracleError as e:
        rc, err = getattr(e, "exit_code", 1), "%s: %s" % (type(e).__name__, e)
    finally:
        apcli._is_tty, apcli._ask = old
    return rc, out.getvalue(), err


class enforce:
    def __init__(self, providers):
        self.providers = providers

    def __enter__(self):
        self.old = (owner.PROVIDERS, owner._CHAIN_OVERRIDE, os.environ.get("SHIPMIRACLE_ENFORCE_OWNER"))
        owner.PROVIDERS, owner._CHAIN_OVERRIDE = self.providers, ["python3", "zsh", "login", "Terminal"]
        owner.reset_cache()
        os.environ["SHIPMIRACLE_ENFORCE_OWNER"] = "1"
        reset_state()
        return self

    def __exit__(self, *a):
        owner.PROVIDERS, owner._CHAIN_OVERRIDE = self.old[0], self.old[1]
        os.environ.pop("SHIPMIRACLE_ENFORCE_OWNER", None)
        if self.old[2]:
            os.environ["SHIPMIRACLE_ENFORCE_OWNER"] = self.old[2]
        reset_state()


def reset_state():
    try:
        os.unlink(str(owner._state_file()))
    except OSError:
        pass


# ================================================================ m4 charter set --until: checks before the touch
print("# m4")
X.cleanup(); purge_crs(); vis(); F.write_plan(34); X.fresh_health()
crs4 = [open_cr("m4 %d" % i) for i in range(2)]
touch = Fake("pw", "medium")
kw = dict(goal="g", scope=SCOPE, ends=",".join(crs4), until="disabled")
set_standing_basis()
with enforce([touch]):
    rc, out, err = cli("charter", "set", **kw)
    check("m4 no P6-1 record and no marker: refused BEFORE the owner is asked (no touch)", rc != 0 and not touch.calls and "option C stays off" in err, (rc, err, touch.calls))
    set_standing_basis("pass")
    acfg.set("autopilot.standing.enabled", "off")
    touch.calls.clear()
    rc, out, err = cli("charter", "set", **kw)
    check("m4 a prerequisite fails (the option C switch is off): refused BEFORE the touch, the reason is named", rc != 0 and not touch.calls and "autopilot.standing.enabled" in err, (rc, err, touch.calls))
    acfg.set("autopilot.standing.enabled", "on")               # (this switch is itself an escalation: one touch)
    touch.calls.clear()
    X.visibility.write_entry(str(X.ORIGIN), False, now=time.time())
    rc, out, err = cli("charter", "set", **kw)
    check("m4 another prerequisite fails (remote not private): refused BEFORE the touch", rc != 0 and not touch.calls and "remote" in err, (rc, err, touch.calls))
    vis()
    rc, out, err = cli("charter", "set", goal="g", scope=SCOPE, ends=",".join(crs4), until="disabled", time="3h")
    check("m4 a malformed charter (--time with --until) is refused BEFORE the touch", rc != 0 and not touch.calls, (rc, err, touch.calls))
    rc, out, err = cli("charter", "set", goal="g", scope=SCOPE, ends=",".join(crs4), until="disabled", budget=40)
    check("B1 a charter error from the fields (budget 40) is the plain refusal 'Charter NOT set' (exit 1), before any touch", rc == 1 and "Charter NOT set" in err and not touch.calls, (rc, err, touch.calls))
    with enforce([Fake("pw", "medium", ask="refused")]) as _e:
        refused_p = _e.providers[0]
        rc, out, err = cli("charter", "set", **kw)
    check("B1 a refused touch: exactly one provider call, the command fails, NOTHING is stored", rc != 0 and len(refused_p.calls) == 1 and registry.autopilot_of(registry.entry(PID)) is None, (rc, err, refused_p.calls))
    reset_state()
    rc, out, err = cli("charter", "set", **kw)
    check("m4 everything in order: ONE touch, then the charter is stored", rc == 0 and len(touch.calls) == 1 and registry.autopilot_of(registry.entry(PID)) is not None, (rc, err, touch.calls))
    check("m4 ... the standing charter is the one stored", ch.is_standing(registry.autopilot_of(registry.entry(PID))["charter"]))
set_standing_basis(marker=True)

# ================================================================ m5 prune only after the owner check
print("# m5")


def tree():
    """Everything a prune could change: the registry file, and the run state files."""
    h = hashlib.sha256()
    files = [pathlib.Path(registry.path())] if hasattr(registry, "path") else [CONF / "registry.json"]
    sd = STATE / "v1" / "autopilot"
    if sd.exists():
        files += sorted(p for p in sd.rglob("*") if p.is_file())
    for f in files:
        try:
            h.update(str(f).encode() + b"\0" + f.read_bytes() + b"\0")
        except OSError:
            h.update(b"missing\0")
    return h.hexdigest()


def stale_admission_world(tag):
    """A standing run paused at switch_off with ONE admission whose request was abandoned afterwards (a prune would remove it). -> (crs, stale cr, fresh cr)."""
    X.cleanup(); purge_crs(); vis(); F.write_plan(34); X.fresh_health()
    crs = [open_cr("%s %d" % (tag, i)) for i in range(2)]
    ch.store_charter(PID, standing_charter(crs[:1]), "cli")
    code, out, err = sh([sys.executable, SHIPM, "autopilot", "start", "--project", "sandbox", "--yes", "--ack-risk", RISK])
    assert code == 0, (out, err)
    stale = open_cr("%s stale" % tag)
    rc, out, err = cli("admit", stale, yes=True)
    assert rc == 0, (rc, out, err)
    from shipmiracle.playbook import gate
    rules = gate.stage_rules(str(MAIN))

    def fn(work):
        c = engine.get_cr(work, stale)
        c["lease"] = None
        return None, engine.abandon(work, stale, {"kind": "owner_override", "by": "cli", "ts": int(time.time()), "data": {"reason": "test"}}, rules)
    store.transact(str(MAIN), fn)
    acfg.set("autopilot.full.enabled", "off"); S.settle(PID); acfg.set("autopilot.full.enabled", "on")
    assert run_state()["state"] == "paused", run_state()
    fresh = open_cr("%s fresh" % tag)
    return crs, stale, fresh


def admitted_ids():
    rec = registry.autopilot_of(registry.entry(PID)) or {}
    return [a["id"] for a in (rec.get("admitted") or [])]


crs, stale, fresh = stale_admission_world("m5a")
check("m5 setup: the stale admission is recorded", stale in admitted_ids(), admitted_ids())
before = tree()
refuse = Fake("pw", "medium", ask="refused")
with enforce([refuse]):
    rc, out, err = cli("admit", fresh, yes=True)
check("m5 admit: a refused proof is refused (the provider was asked once)", rc != 0 and len(refuse.calls) == 1, (rc, err, refuse.calls))
check("m5 admit: ... and the state tree is BYTE-IDENTICAL (the stale admission was not pruned)", tree() == before and stale in admitted_ids(), admitted_ids())
refuse2 = Fake("pw", "medium", ask="unavailable")
reset_state()
with enforce([refuse2]):
    rc, out, err = cli("admit", fresh, yes=True)
check("m5 admit: an unavailable check changes nothing either", rc != 0 and tree() == before, (rc, err))
okp = Fake("pw", "medium")
with enforce([okp]):
    rc, out, err = cli("admit", fresh, yes=True)
check("m5 admit: with the proof passed the stale admission IS pruned and the new one admitted (positive control)", rc == 0 and stale not in admitted_ids() and fresh in admitted_ids() and tree() != before, (rc, err, admitted_ids()))

crs, stale, fresh = stale_admission_world("m5b")
before = tree()
refuse = Fake("pw", "medium", ask="refused")
with enforce([refuse]):
    rc, out, err = cli("checkpoint", yes=True)
check("m5 checkpoint: a refused proof is refused (the provider was asked)", rc != 0 and len(refuse.calls) == 1, (rc, err, refuse.calls))
check("m5 checkpoint: ... and the state tree is BYTE-IDENTICAL", tree() == before and stale in admitted_ids() and run_state()["state"] == "paused", (admitted_ids(), run_state()["state"]))
okp = Fake("pw", "medium")
reset_state()
with enforce([okp]):
    rc, out, err = cli("checkpoint", yes=True)
check("m5 checkpoint: with the proof passed the stale admission is pruned and the run continues (positive control)", rc == 0 and stale not in admitted_ids() and run_state()["state"] == "running", (rc, err, admitted_ids(), run_state()["state"]))

X.cleanup()
print("owner_d14_world: %d failed" % X.fails)
sys.exit(1 if X.fails else 0)
