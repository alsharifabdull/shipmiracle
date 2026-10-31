#!/usr/bin/env python3
"""Owner proof for the human-only autopilot commands (design docs/plans/2026-10-21-owner-proof-design.md, B1/B2): the red-team cases RT1-RT11, the friction
requirements (one touch per action, no re-prompt loop, plain refusals, fail-soft kill switches), the gate/hardstop cases. World: tests/autopilot_engine_fixture.py
(fully temp HOME / DEV / STATE / config / workspace, SHIPMIRACLE_TEST=1, project `sandbox`, local bare origin, no network, no real claude). SHIPMIRACLE_ENFORCE_OWNER=1 switches the
owner locks ON inside the sandbox (they are skipped there otherwise, like lock 1 today). A REAL Touch ID touch cannot be automated: the presence helper is replaced by a
fake script through the test-only seam SHIPMIRACLE_PRESENCE_BIN (honoured only when sandboxed). Run: python3 tests/owner_proof_redteam_test.py"""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import shipmiracle_isolation; shipmiracle_isolation.apply_to_environ()   # test isolation
import contextlib, io, json, os, pathlib, re, shutil, subprocess, sys, tempfile, time, types

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import autopilot_engine_fixture as X  # noqa: E402  (builds the temp world, rewrites os.environ)
from autopilot_engine_fixture import check, git, sh, S, PID, MAIN, DEV, STATE, engine, store, W, F, ch  # noqa: E402
from shipmiracle import registry, paths, ShipmiracleError, UsageError, SafetyError  # noqa: E402
from shipmiracle.autopilot import cli as apcli, standing as SG  # noqa: E402
from shipmiracle import owner  # noqa: E402
import shipmiracle.config as acfg  # noqa: E402

ROOT = HERE.parent
REAL = pathlib.Path(os.path.expanduser("~"))
CANARY = [REAL / ".config" / "shipmiracle" / "registry.json", REAL / ".config" / "shipmiracle" / "config.json", REAL / ".claude" / "settings.json", REAL / ".local/state/shipmiracle/events.jsonl"]
CANARY_BEFORE = [(p.stat().st_mtime_ns if p.exists() else None) for p in CANARY]
X.build()
from shipmiracle import config as _cfg, owner as _owner  # noqa: E402
_owner._ACCOUNT_OVERRIDE = lambda: True          # this sandbox account counts as a standard (non-admin) user; the admin case is tested below
(pathlib.Path(os.environ["SHIPMIRACLE_CONFIG"]) / "throwaway-account").write_text("test\n")      # option C go-live (B2): a throwaway-account marker stands in for the recorded P6-1 pass
_cfg.set("autopilot.standing.enabled", "on")
RISK = "until I disable it"
SCOPE = "src/**,tests/**,docs/**,package.json"
SHIPM = str(ROOT / "bin" / "shipm")


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


def standing_paused(tag):
    """A standing run, started (sandboxed `--yes`), then paused at a check-in (switch_off: the check-in is allowed at once). -> list of CR ids."""
    X.cleanup(); purge_crs(); vis(); F.write_plan(34); X.fresh_health()
    crs = [open_cr("%s %d" % (tag, i)) for i in range(2)]
    ch.store_charter(PID, {"goal": "g", "scope": ch.clean_scope(SCOPE), "ends": crs, "budget": 10, "deps": {"mode": "none"}, "until": "disabled", "day": 4, "crs_day": 3}, "cli")
    code, out, err = sh([sys.executable, SHIPM, "autopilot", "start", "--project", "sandbox", "--yes", "--ack-risk", RISK])
    if code != 0:
        raise SystemExit("start failed: %s %s" % (out, err))
    from shipmiracle import config
    config.set("autopilot.full.enabled", "off"); S.settle(PID); config.set("autopilot.full.enabled", "on")
    st = S.read(PID)
    assert st["state"] == "paused" and st["paused_reason"] == "switch_off", st
    return crs


def run_state():
    return S.read(PID)


def events(kind):
    return X.events(kind)


# ================================================================ RT1: the proven repro (must be RED on code without the owner proof)
print("# RT1")
standing_paused("rt1")
st0 = run_state()
env = dict(F.ENV, SHIPMIRACLE_ENFORCE_OWNER="1", CLAUDECODE="1")                 # the chat's shell: CLAUDECODE is set there
inner = "env -u CLAUDECODE %s %s autopilot checkpoint --project sandbox" % (sys.executable, SHIPM)
if sys.platform == "darwin":
    cmd = "(sleep 2; printf 'yes\\n') | script -q /dev/null %s" % inner       # a pty: stdin and stdout are ttys, yes is typed by a pipe (BSD script: script file command...)
else:
    cmd = "(sleep 2; printf 'yes\\n') | script -q -c %s /dev/null" % __import__("shlex").quote(inner)       # util-linux script: script -c command file
r = subprocess.run(["/bin/sh", "-c", cmd], env=env, capture_output=True, text=True, timeout=120)
st1 = run_state()
check("RT1 the repro `script -q /dev/null env -u CLAUDECODE shipm autopilot checkpoint` (yes fed through a pipe) does NOT continue the run",
      st1["state"] == "paused" and st1["paused_reason"] == "switch_off" and st1["seg"]["n"] == st0["seg"]["n"], (r.stdout[-300:], r.stderr[-200:], st1["state"], st1.get("paused_reason")))
check("RT1 ... and the refusal is recorded as an owner.presence event", any(e["data"].get("ok") is False for e in events("owner.presence")), events("owner.presence"))



# ================================================================ plumbing for the in-process cases
class Fake(owner.Provider):
    """A provider whose probe and answer are chosen by the test; counts its calls."""
    def __init__(self, name, tier, probe="ready", ask="ok"):
        self.name, self.tier, self._probe, self._ask, self.calls = name, tier, probe, ask, []

    def probe(self):
        return self._probe

    def ask(self, reason, timeout):
        self.calls.append((reason, timeout))
        return self._ask


CLEAN = ["python3", "zsh", "login", "Terminal"]


def ns(**kw):
    d = dict(action=None, rargs=[], project="sandbox", goal=None, scope=None, budget=None, time=None, deps=None, ends=None, until=None, day=None, crs_day=None, yes=False, ack=None,
             ack_risk=None, launch=False, json=False, lines=None)
    d.update(kw)
    return types.SimpleNamespace(**d)


def cli(action, *rargs, tty=False, typed=(), **kw):
    """The owner CLI in process. -> (rc, stdout, error text). `typed` answers the terminal prompts in order; every prompt is recorded in cli.prompts."""
    answers = list(typed)
    old = (apcli._is_tty, apcli._ask)
    cli.prompts = []
    apcli._is_tty = lambda: tty

    def ask(prompt):
        cli.prompts.append(prompt)
        return answers.pop(0) if answers else ""
    apcli._ask = ask
    out = io.StringIO()
    err, rc = "", 0
    try:
        with contextlib.redirect_stdout(out):
            rc = apcli.run(ns(action=action, rargs=list(rargs), **kw))
    except ShipmiracleError as e:
        rc, err = getattr(e, "exit_code", 1), "%s: %s" % (type(e).__name__, e)
    finally:
        apcli._is_tty, apcli._ask = old
    return rc, out.getvalue(), err


class enforce:
    """SHIPMIRACLE_ENFORCE_OWNER=1 (the owner locks switch ON inside the sandbox), a clean process chain and the given providers."""
    def __init__(self, providers, chain=None, setting=None):
        self.providers, self.chain, self.setting = providers, chain if chain is not None else CLEAN, setting

    def __enter__(self):
        self.old = (owner.PROVIDERS, owner._CHAIN_OVERRIDE, os.environ.get("SHIPMIRACLE_ENFORCE_OWNER"), acfg.get("owner.presence"))
        owner.PROVIDERS, owner._CHAIN_OVERRIDE = self.providers, self.chain
        owner.reset_cache()
        if self.setting:
            acfg.set("owner.presence", self.setting)          # still in the sandbox here: setting it asks nothing
        os.environ["SHIPMIRACLE_ENFORCE_OWNER"] = "1"
        reset_state()
        return self

    def __exit__(self, *a):
        owner.PROVIDERS, owner._CHAIN_OVERRIDE = self.old[0], self.old[1]
        os.environ.pop("SHIPMIRACLE_ENFORCE_OWNER", None)                    # back in the sandbox: restoring the setting asks nothing
        if self.old[2]:
            os.environ["SHIPMIRACLE_ENFORCE_OWNER"] = self.old[2]
        acfg.set("owner.presence", self.old[3])
        reset_state()


def reset_state():
    """Forget the cool-down and the one-time warning between cases."""
    try:
        os.unlink(str(owner._state_file()))
    except OSError:
        pass


def txt_ok(e):
    """One plain sentence or two (a refusal + the next step), never a stack trace or jargon."""
    t = str(e)
    return bool(t) and "Traceback" not in t and "File \"" not in t and t.count(". ") <= 2 and len(t) < 420


def paused_standing(tag):
    """A standing run paused at a check-in (switch_off), made with the old sandboxed --yes path; -> CR ids."""
    return standing_paused(tag)


# ================================================================ RT2-RT4: the same attacks through a python pty / allow / resume / drop (real subprocesses, locks ON)
print("# RT2-RT4")
crs = standing_paused("rt2")
cand = open_cr("rt2 candidate")
env_enf = dict(F.ENV, SHIPMIRACLE_ENFORCE_OWNER="1")
code = "import pty,sys; pty.spawn([sys.executable, %r, 'autopilot', 'admit', %r, '--project', 'sandbox'])" % (SHIPM, cand)
r = subprocess.run(["/bin/sh", "-c", "(sleep 2; printf 'yes\\n') | " + sys.executable + " -c \"%s\"" % code.replace('"', '\\"')], env=dict(env_enf, CLAUDECODE="1"), capture_output=True, text=True, timeout=120)
check("RT2 `python -c pty.spawn(['shipm','autopilot','admit',CR])` with a typed yes does not admit anything", not (registry.autopilot_of(registry.entry(PID)) or {}).get("admitted"), (r.stdout[-300:], r.stderr[-200:]))
st_ = run_state()
S.pause(PID, {"id": "H-aaaaaa", "rule": "H5", "ts": int(time.time()), "text": "git push", "cmd_sha": "a" * 64}, "hard_stop") if st_["state"] == "running" else None
S.update(PID, lambda c: dict(c, state="paused", paused_reason="hard_stop", stop={"id": "H-aaaaaa", "rule": "H5", "ts": int(time.time()), "text": "git push", "cmd_sha": "b" * 64}))
r = subprocess.run([sys.executable, SHIPM, "autopilot", "allow", "H-aaaaaa", "--project", "sandbox"], env=env_enf, capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)
check("RT3 `shipm autopilot allow H-x` with CLAUDECODE removed and no tty is refused; the run is still paused", r.returncode != 0 and run_state()["state"] == "paused" and not run_state()["allow"], (r.returncode, r.stdout[-200:], r.stderr[-300:]))
S.update(PID, lambda c: dict(c, state="paused", paused_reason="qa_fail", stop=None))
for verb, args in (("resume", []), ("drop", [crs[0]])):
    r = subprocess.run([sys.executable, SHIPM, "autopilot", verb] + args + ["--project", "sandbox"], env=env_enf, capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)
    check("RT4 `shipm autopilot %s` (standing run, qa_fail pause) is refused without the owner check; the state is unchanged" % verb, r.returncode != 0 and run_state()["state"] == "paused" and run_state()["paused_reason"] == "qa_fail", (r.returncode, r.stdout[-200:], r.stderr[-300:]))
check("RT2-RT4 each refusal is plain: no traceback", "Traceback" not in r.stderr, r.stderr[-300:])

# ================================================================ RT5-RT10 (locks 2 and 3, in process)
print("# RT5-RT10")
crs = standing_paused("rt5")
tf = Fake("fake-touch", "strong")
with enforce([tf], chain=["python3", "claude", "zsh", "Terminal"]):
    rc, out, err = cli("checkpoint", tty=True, typed=("yes",))
    check("RT5 a chain with `claude` above is refused BEFORE any presence call", rc != 0 and not tf.calls and run_state()["state"] == "paused" and txt_ok(err), (rc, err, tf.calls))
with enforce([tf], chain=["python3", "launchd-job", "launchd"]):
    rc, out, err = cli("checkpoint", tty=True, typed=("yes",))
    check("RT6 a chain without an owner host (ends at launchd) is refused", rc != 0 and not tf.calls and txt_ok(err), (rc, err))
with enforce([tf]):
    rc, out, err = cli("checkpoint", tty=True, typed=("yes",))
    check("RT7 a clean chain and a presence fake that says ok: the check-in works (positive control)", rc == 0 and run_state()["state"] == "running" and len(tf.calls) == 1, (rc, err, out[-200:]))
fb = Fake("p", "strong")
seam_env = os.environ.get("SHIPMIRACLE_PRESENCE_BIN")
os.environ["SHIPMIRACLE_PRESENCE_BIN"] = "/tmp/evil-helper"
old_sb = paths.sandboxed
paths.sandboxed = lambda: False
try:
    hp, used_seam = owner.helper_path()
finally:
    paths.sandboxed = old_sb
    os.environ.pop("SHIPMIRACLE_PRESENCE_BIN", None) if seam_env is None else os.environ.__setitem__("SHIPMIRACLE_PRESENCE_BIN", seam_env)
check("RT8 SHIPMIRACLE_PRESENCE_BIN is ignored when the run is not sandboxed (the fixed path is used)", not used_seam and hp.endswith("/bin/shipm-presence") and "evil" not in hp, hp)
# RT9: helper present, record says another sha -> broken -> refused, no weaker prompt
cfgd = pathlib.Path(os.environ["SHIPMIRACLE_CONFIG"])
(cfgd / "bin").mkdir(exist_ok=True)
(cfgd / "bin" / "shipm-presence").write_text("#!/bin/sh\necho ok\n")
os.chmod(str(cfgd / "bin" / "shipm-presence"), 0o700)
(cfgd / "presence.sha256").write_text("0" * 64 + " " + "1" * 64 + "\n")
typed_fake = Fake("typed", "basic")
real_providers = [owner.HelperProvider("macos-touchid", "strong", "strong"), owner.HelperProvider("macos-password", "medium", "owner"), typed_fake]
old_plat = sys.platform
with enforce(real_providers):
    sys.platform = "darwin"
    try:
        sel_err = None
        try:
            owner.select()
        except owner.OwnerRefused as e:
            sel_err = str(e)
    finally:
        sys.platform = old_plat
    check("RT9/RT13 a helper whose sha differs from the record is refused (broken), and the typed code is NOT offered instead", sel_err and "will not fall back" in sel_err and not typed_fake.calls and txt_ok(sel_err), sel_err)
(cfgd / "bin" / "shipm-presence").unlink(); 
with enforce(real_providers):
    sys.platform = "darwin"
    try:
        sel_err = None
        try:
            owner.select()
        except owner.OwnerRefused as e:
            sel_err = str(e)
    finally:
        sys.platform = old_plat
    check("RT13 record exists, helper deleted -> refused (broken), no medium / basic prompt", sel_err and "will not fall back" in sel_err and not typed_fake.calls, sel_err)
(cfgd / "presence.sha256").unlink()
# RT10: a second confirm while one prompt is open
from shipmiracle import state as core
with enforce([Fake("p", "strong")]):
    lockp = core.ensure_dir(core.ensure_root()) / "presence.lock"
    with core.lock_file(lockp):
        sel = owner.select()
        try:
            owner.touch("checkpoint", "x", sel=sel); r10 = None
        except owner.OwnerRefused as e:
            r10 = str(e)
check("RT10 two concurrent owner checks: the second is refused with one plain sentence", r10 and "already open" in r10 and txt_ok(r10), r10)

# ================================================================ RT11: the option C go-live switch and the tier minimum for C
print("# RT11")
marker = cfgd / "throwaway-account"
marker.unlink()
acfg.set("autopilot.standing.enabled", "off")
tf = Fake("fake-touch", "strong")
with enforce([tf]):
    try:
        acfg.set("autopilot.standing.enabled", "on"); r11 = None
    except ShipmiracleError as e:
        r11 = str(e)
    check("RT11 `shipm switch autopilot.standing.enabled on` without a P6-1 record or a separate-account marker is refused (before any prompt)", r11 and "Option C stays off" in r11 and not tf.calls and txt_ok(r11), r11)
    owner.record_probe("pass", list(owner.P61_LINES))
    acfg.set("autopilot.standing.enabled", "on")
    check("RT11 ... with a recorded P6-1 pass (all seven lines) it goes on after ONE presence check", acfg.get("autopilot.standing.enabled") is True and len(tf.calls) == 1, tf.calls)
    try:
        owner.record_probe("pass", ["1", "7"]); r11b = None
    except owner.OwnerRefused as e:
        r11b = str(e)
    check("RT11 a partial P6-1 pass (lines 1 and 7 only) cannot be recorded as a pass (owner answer Q8)", r11b and "all seven" in r11b, r11b)
    owner.record_probe("fail", ["1", "7"])
    acfg.set("autopilot.standing.enabled", "off")
    try:
        acfg.set("autopilot.standing.enabled", "on"); r11c = None
    except ShipmiracleError as e:
        r11c = str(e)
    check("RT11 ... after a recorded fail the switch stays off", r11c and "Option C stays off" in r11c, r11c)
    old_now = owner.time.time
    owner.record_probe("pass", list(owner.P61_LINES), now=time.time() - 31 * 86400)
    try:
        acfg.set("autopilot.standing.enabled", "on"); r11d = None
    except ShipmiracleError as e:
        r11d = str(e)
    check("RT11 ... and a pass older than 30 days no longer counts", r11d and "older than 30 days" in r11d, r11d)
marker.write_text("separate account\n")
acfg.set("autopilot.standing.enabled", "on")
# the standing run pauses with standing_off when the switch goes off; the check-in after the switch is on again continues
crs = standing_paused("rt11")
S.update(PID, lambda c: dict(c, state="running", paused_reason=None))
acfg.set("autopilot.standing.enabled", "off")
cur = S.settle(PID)
check("RT11 a running standing run pauses with standing_off when its switch is off", cur["state"] == "paused" and cur["paused_reason"] == "standing_off", cur)
acfg.set("autopilot.standing.enabled", "on")
check("RT11 ... switching on again does not resume it", S.settle(PID)["state"] == "paused")
def repause():
    S.update(PID, lambda c: dict(c, state="paused", paused_reason="switch_off", stop=None))


repause()
tcode = Fake("typed", "basic")
with enforce([tcode], setting="basic-ok"):
    rc, out, err = cli("checkpoint", tty=True, typed=())
    check("RT11 C at the typed-code tier WITH the separate-account marker is allowed; the code REPLACES the typed yes (no yes prompt)", rc == 0 and len(tcode.calls) == 1 and not any("yes" in x for x in cli.prompts)
          and run_state()["state"] == "running", (rc, err, cli.prompts))
repause()
marker.unlink()
with enforce([Fake("typed", "basic")], setting="basic-ok"):
    rc, out, err = cli("checkpoint", tty=True, typed=("yes",))
    check("RT11 C at the typed-code tier WITHOUT the marker is refused with the plain sentence", rc != 0 and "stronger owner check" in err and run_state()["state"] == "paused" and txt_ok(err), (rc, err))
marker.write_text("separate account\n")


# ================================================================ friction at the CLI (locks ON, fake providers)
print("# friction (CLI)")
marker.write_text("separate account\n")
# (2) start = one check covering the whole start flow; the typed yes appears once
X.cleanup(); purge_crs(); vis(); F.write_plan(34); X.fresh_health()
crs = [open_cr("fr start %d" % i) for i in range(2)]
ch.store_charter(PID, {"goal": "g", "scope": ch.clean_scope(SCOPE), "ends": crs, "budget": 10, "deps": {"mode": "none"}, "until": "disabled", "day": 4, "crs_day": 3}, "cli")
tf = Fake("fake-touch", "strong")
with enforce([tf]):
    rc, out, err = cli("start", tty=True, typed=("yes", RISK))
    check("friction 2/9: `start` of option C = ONE presence check, ONE typed yes line and ONE risk line (no repeated prompts)", rc == 0 and len(tf.calls) == 1 and [x for x in cli.prompts].count('Type "yes" to start: ') == 1
          and sum(1 for x in cli.prompts if "until I disable it" in x) == 1 and len(cli.prompts) == 2, (rc, err, cli.prompts, tf.calls))
    check("friction 2: the check text names the action and the project and says when to cancel", tf.calls and "start autopilot on sandbox" in tf.calls[0][0] and "Cancel if you did not just type this yourself" in tf.calls[0][0], tf.calls)
S.update(PID, lambda c: dict(c, state="paused", paused_reason="switch_off", stop=None))
tf = Fake("fake-touch", "strong")
a1, a2 = open_cr("fr admit a"), open_cr("fr admit b")
with enforce([tf]):
    rc, out, err = cli("admit", a1, a2, tty=True, typed=("yes",))
    check("friction 2: `admit CR-a CR-b` takes both ids with ONE typed yes and ONE presence check", rc == 0 and len(tf.calls) == 1 and len(cli.prompts) == 1
          and {x["id"] for x in registry.autopilot_of(registry.entry(PID))["admitted"]} == {a1, a2}, (rc, err, cli.prompts, tf.calls))
    S.update(PID, lambda c: dict(c, state="paused", paused_reason="switch_off", stop=None))
    tf.calls.clear()
    rc, out, err = cli("checkpoint", tty=True, typed=("yes",))
    check("friction 2: the daily check-in = ONE presence check and ONE typed yes", rc == 0 and len(tf.calls) == 1 and len(cli.prompts) == 1, (rc, err, cli.prompts))
    check("friction 2: the check-in prints the owner-check summary line (approved / refused counts by kind)", "Owner checks in the last 24 h" in out and "approved" in out and "refused" in out, out[-400:])
# (3) cancel -> one clear line, no loop, 30 s cool-down
S.update(PID, lambda c: dict(c, state="paused", paused_reason="switch_off", stop=None))
cancel = Fake("fake-touch", "strong", ask="refused")
with enforce([cancel]):
    rc1, out1, err1 = cli("checkpoint", tty=True, typed=("yes", "yes"))
    rc2, out2, err2 = cli("checkpoint", tty=True, typed=("yes", "yes"))
    check("friction 3: a cancelled check is refused with one sentence; the immediate retry is refused for 30 s WITHOUT asking again (and without a typed-yes prompt for nothing)",
          rc1 != 0 and rc2 != 0 and len(cancel.calls) == 1 and "wait" in err2 and txt_ok(err1) and txt_ok(err2) and run_state()["state"] == "paused", (err1, err2, cancel.calls))
# (1) normal work never prompts; (5) stop / clear / off / show work with a broken provider
bad = Fake("broken", "strong", probe="broken", ask="refused")
with enforce([bad], setting="strong-only"):
    allowed = []
    for verb in ("show",):
        rc, out, err = cli(verb)
        allowed.append((verb, rc))
    rc_o, _o, _e = sh([sys.executable, SHIPM, "cr", "list", "--project", "sandbox"], env=dict(F.ENV, SHIPMIRACLE_ENFORCE_OWNER="1"))[0:3]
    check("friction 1/5: `show` and ordinary Shipmiracle commands (cr list) never prompt and work although the owner-check provider is broken", all(rc == 0 for _v, rc in allowed) and rc_o == 0 and not bad.calls, (allowed, rc_o))
    acfg.set("autopilot.full.enabled", "off")
    rc, out, err = cli("stop")
    check("friction 5: `stop` works with a broken provider and strong-only (the kill switch never needs a check); switching a setting OFF asked nothing", rc == 0 and not bad.calls and run_state()["state"] == "ended", (rc, out, err))
acfg.set("autopilot.full.enabled", "on")
# (4) plain refusals for the common failure states
X.cleanup(); purge_crs(); vis(); F.write_plan(34); X.fresh_health()
crs = [open_cr("fr refuse %d" % i) for i in range(2)]
ch.store_charter(PID, {"goal": "g", "scope": ch.clean_scope(SCOPE), "ends": crs, "budget": 10, "deps": {"mode": "none"}, "until": "disabled", "day": 4, "crs_day": 3}, "cli")
cases = {}
with enforce([]):
    cases["no provider at all and no tty"] = cli("start", tty=True, typed=("yes", RISK))
with enforce([Fake("h", "strong", probe="setup")]):
    cases["helper not built"] = cli("start", tty=True, typed=("yes", RISK))
with enforce([Fake("h", "strong", probe="broken")]):
    cases["helper changed"] = cli("start", tty=True, typed=("yes", RISK))
with enforce([Fake("h", "strong", ask="unavailable")], setting="strong-only"):
    cases["sensor unavailable"] = cli("start", tty=True, typed=("yes", RISK))
with enforce([Fake("h", "strong")], chain=["python3", "claude", "zsh", "Terminal"]):
    cases["inside a Claude chat"] = cli("start", tty=True, typed=("yes", RISK))
check("friction 4: every refusal is ONE plain sentence plus the next step, never a stack trace or jargon", all(rc != 0 and txt_ok(err) and "OwnerRefused" in err for rc, _o, err in cases.values()) and run_state()["state"] == "set",
      {k: v[2] for k, v in cases.items()})
check("friction 4: the texts name the exact next step", "bin/shipm-presence-build" in cases["helper not built"][2] and "bin/shipm-presence-build" in cases["helper changed"][2]
      and "stop and switch-off still work" in cases["sensor unavailable"][2] and "Terminal" in cases["inside a Claude chat"][2], {k: v[2] for k, v in cases.items()})

# RT17 the chat `allow:` hook route at the typed-code tier: refused with the terminal command (no hang, no state change)
from shipmiracle.hooks import autopilot as AP  # noqa: E402
S.update(PID, lambda c: dict(c, state="paused", paused_reason="hard_stop", stop={"id": "H-bbbbbb", "rule": "H5", "ts": int(time.time()), "text": "git push", "cmd_sha": "c" * 64}))
from shipmiracle.autopilot import charter as _ch  # noqa: E402
for provs, label in (([Fake("code", "basic")], "typed code only"), ([Fake("pw", "medium", ask="refused")], "password dialog cancelled")):
    with enforce(provs):
        try:
            AP._allow(PID, "H-bbbbbb", "sandbox"); r17 = None
        except _ch.CharterError as e:
            r17 = str(e)
        check("RT17 hook `allow:` (%s) is refused with the exact terminal command; the run stays paused" % label, r17 and "shipm autopilot allow H-bbbbbb --project sandbox" in r17 and run_state()["state"] == "paused"
              and not run_state()["allow"], r17)
with enforce([Fake("pw", "medium")]):
    msg = AP._allow(PID, "H-bbbbbb", "sandbox")
    check("RT17 ... and with a medium-tier check that passes, the line works (one check)", "Allowed H-bbbbbb" in msg and run_state()["state"] == "running", msg)


# ================================================================ review round 2: F1 (b, c), F5, prompt storms and replay on the hook route
print("# review round 2")
from shipmiracle import SafetyError  # noqa: E402
marker.write_text("separate account\n")
owner._ACCOUNT_OVERRIDE = lambda: False                    # a REAL administrator account
check("F1 a forged marker on an administrator account is not a separate account (computed, not trusted from the file)", owner.separate_marker() and not owner.separate_account())
acfg.set("autopilot.standing.enabled", "off")
os.unlink(str(cfgd / "probes.json")) if (cfgd / "probes.json").exists() else None
try:
    with enforce([Fake("touch", "strong")]):
        acfg.set("autopilot.standing.enabled", "on"); r_adm = None
except ShipmiracleError as e:
    r_adm = str(e)
check("F1 ... so the option C switch stays off on an administrator account with only the marker (no P6-1 record)", r_adm and "Option C stays off" in r_adm and "no recorded sandbox test" in r_adm, r_adm)
with enforce([Fake("touch", "strong")]):
    try:
        owner.mark_separate_account(); r_mk = None
    except owner.OwnerRefused as e:
        r_mk = str(e)
check("F1 `shipm owner mark-separate-account` on an administrator account is refused with the plain sentence (it cannot mark itself)", r_mk and "administrator rights" in r_mk and txt_ok(r_mk), r_mk)
owner._ACCOUNT_OVERRIDE = lambda: True
marker.unlink()
tmk = Fake("typed", "basic")
with enforce([tmk], setting="basic-ok"):
    p_ = owner.mark_separate_account()
check("F1 on a standard account it needs the owner check (typed code here), then writes the marker through the hardened writer and logs an event", pathlib.Path(p_).is_file() and len(tmk.calls) == 1
      and (os.stat(p_).st_mode & 0o777) == 0o600 and any(e["data"].get("action") == "mark-separate-account" for e in events("owner.presence")), (p_, tmk.calls))
# (c) the marker never lowers the tier on a machine that HAS an OS prompt
with enforce([Fake("macos-password", "medium", ask="unavailable"), Fake("typed", "basic")], setting="auto"):
    try:
        owner.select(min_tier="strong", separate_ok=True); r_c = None
    except owner.OwnerRefused as e:
        r_c = str(e)
check("F1(c) with an OS prompt available the marker does not lower anything: a strong-tier action is still refused at medium", r_c and "stronger owner check" in r_c, r_c)
# F5: symlinks are refused by the writer
for name, fn in (("probes.json", lambda: owner.record_probe("fail", ["1"])), ("throwaway-account", lambda: (marker.unlink(), None)[1])):
    pass
victim = TMP_V = pathlib.Path(tempfile.mkdtemp(prefix="symv-")).resolve() / "victim.txt"
victim.write_text("precious\n")
pj = cfgd / "probes.json"
if pj.exists() or pj.is_symlink():
    pj.unlink()
os.symlink(str(victim), str(pj))
try:
    owner.record_probe("fail", ["1"]); r_sym = None
except SafetyError as e:
    r_sym = str(e)
check("F5 record_probe refuses to write through a symlink (and the target is untouched)", r_sym and victim.read_text() == "precious\n", r_sym)
pj.unlink()
stf = owner._state_file()
if stf.exists() or stf.is_symlink():
    stf.unlink()
os.symlink(str(victim), str(stf))
owner._save_state({"fail_ts": 1})
check("F5 the presence state file is not written through a symlink either (cool-down bookkeeping is best effort, the target stays intact)", victim.read_text() == "precious\n")
stf.unlink()
mk2 = cfgd / "throwaway-account"
if mk2.exists():
    mk2.unlink()
os.symlink(str(victim), str(mk2))
with enforce([Fake("typed", "basic")], setting="basic-ok"):
    try:
        owner.mark_separate_account(); r_sym2 = None
    except SafetyError as e:
        r_sym2 = str(e)
check("F5 mark-separate-account refuses a symlinked marker path", r_sym2 and victim.read_text() == "precious\n", r_sym2)
mk2.unlink()
marker.write_text("separate account\n")

# hook route: prompt storms and replay
acfg.set("autopilot.standing.enabled", "on")
crs = standing_paused("storm")
S.update(PID, lambda c: dict(c, state="paused", paused_reason="hard_stop", stop={"id": "H-cccccc", "rule": "H5", "ts": int(time.time()), "text": "git push", "cmd_sha": "d" * 64}))
nope = Fake("pw", "medium", ask="refused")
with enforce([nope]):
    res = []
    for _i in range(4):
        try:
            AP._allow(PID, "H-cccccc", "sandbox"); res.append("ok")
        except _ch.CharterError as e:
            res.append(str(e))
    check("hook route: four `allow:` lines in a row after a cancel cause ONE prompt (the 30 s cool-down), never a prompt storm", len(nope.calls) == 1 and all(x != "ok" for x in res) and "wait" in res[-1], (len(nope.calls), res))
okp = Fake("pw", "medium")
with enforce([okp]):
    m1 = AP._allow(PID, "H-cccccc", "sandbox")
    try:
        AP._allow(PID, "H-cccccc", "sandbox"); m2 = None
    except _ch.CharterError as e:
        m2 = str(e)
    check("hook route: replaying the same `allow:` line after it worked asks nothing and does nothing (no paused run on that stop any more)", "Allowed" in m1 and m2 and "no paused run" in m2 and len(okp.calls) == 1, (m1, m2, len(okp.calls)))

print("\nALL PASS" if not X.fails else "\nFAILED: %d" % X.fails)
sys.exit(1 if X.fails else 0)
