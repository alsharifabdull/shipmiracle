"""Guard decisions with faked readings (no system changes). Run: python3 tests/guard_test.py"""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import shipmiracle_isolation; shipmiracle_isolation.apply_to_environ()   # test isolation: fresh HOME/SHIPMIRACLE_HOME/CONFIG/STATE unless already temp
import importlib.machinery, importlib.util, json, os, pathlib, sys, tempfile, time
tmp = pathlib.Path(tempfile.mkdtemp()); os.environ["SHIPMIRACLE_TEST"] = "1"; os.environ["SHIPMIRACLE_STATE"] = str(tmp)
fake = tmp / "fake.json"; os.environ["SHIPMIRACLE_GUARD_FAKE"] = str(fake)
cs = tmp / "claude-settings.json"; cs.write_text(json.dumps({"model": "opusplan", "x": 1})); os.environ["SHIPMIRACLE_CLAUDE_SETTINGS"] = str(cs)
ws = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_loader("g", importlib.machinery.SourceFileLoader("g", str(ws / "bin/shipm-guard")))
g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
fails = []
def check(name, cond, info=""):
    print(("PASS " if cond else "FAIL ") + name, info if not cond else ""); 
    if not cond: fails.append(name)
def run(G, **kw):
    fake.write_text(json.dumps(kw)); return G.step()

G = g.Guard()
o = run(G, claude_working=False); check("idle: no work, nothing held", not o["work"] and not o["hold"])
o = run(G, claude_working=True); check("claude working -> hold", o["hold"] and "caffeinate on" in " ".join(o["actions"]))
o = run(G, claude_working=False, vscode_busy=True); check("busy VS Code process -> hold", o["hold"])
G.last_sign = time.time() - 300
o = run(G); check("5 min after last sign still held", o["hold"])
G.last_sign = time.time() - 700
o = run(G); check("10+ min after last sign released", not o["hold"] and "caffeinate off" not in "" )
o = run(G, vscode=False, claude_working=True); check("work outside VS Code ignored", not o["work"])
G = g.Guard()
o = run(G, claude_working=True, on_ac=False, lid_closed=True, idle_s=60); check("battery+lid closed -> low power on", o["lpm"] and any("low power mode on" in a for a in o["actions"]))
o = run(G, claude_working=True, on_ac=False, lid_closed=False, idle_s=3); check("you are back -> low power off", not o["lpm"])
o = run(G, claude_working=True, on_ac=True, lid_closed=True, idle_s=60); check("on power: never low power", not o["lpm"] and o["hold"])
G = g.Guard()
o = run(G, claude_working=True, on_ac=False, battery_pct=24); check("25%: wrap-up flag", any("wrap-up" in a for a in o["actions"]))
o = run(G, claude_working=True, on_ac=False, battery_pct=14); check("15%: checkpoint and release", any("checkpoint" in a for a in o["actions"]) and not o["hold"])
o = run(G, claude_working=True, on_ac=False, battery_pct=14); check("stays released while unplugged", not o["hold"])
o = run(G, claude_working=True, on_ac=True, battery_pct=14); check("plugged in: hold again", o["hold"])
G = g.Guard(); (tmp / "guard.off").write_text("off")
o = run(G, claude_working=True); check("switch off: nothing held", not o["hold"] and o["reason"] == "switched off")
(tmp / "guard.off").unlink()
G = g.Guard()
o = run(G, claude_working=True, thermal_limit=60); check("hot Mac: released", not o["hold"])
G = g.Guard(); G.stretch_start = time.time() - 13 * 3600; G.last_sign = time.time()
o = run(G, claude_working=True); check("12 h stuck: released", not o["hold"])
# Wi-Fi recovery was removed by owner decision (21 Oct): failed internet checks change nothing and no hotspot state exists
G = g.Guard()
_acts = []
for _ in range(6): o = run(G, claude_working=True, internet=False); _acts += o["actions"]
check("no Wi-Fi recovery: failed internet checks do nothing and the output has no hotspot field", not any(("radio" in a or "join" in a or "Wi-Fi" in a) for a in _acts) and "hotspot" not in o and o["hold"], str(_acts))
check("the Wi-Fi helpers are gone", not any(hasattr(g, n) for n in ("hotspot", "home_nets", "internet_ok", "HOTSPOT", "HOME_NETS", "_no_ssid")) and not hasattr(g.Guard, "wifi"))
o = run(G, claude_working=True, idle_s=2000, lid_closed=False); check("idle 15 min = away", o["away"])
# frozen work does not keep the Mac awake (shipm-watch: every working chat frozen)
G = g.Guard(); o = run(G, claude_working=True, frozen_since=time.time() - 40 * 60); check("work frozen for 40 min: the awake hold is released (reason says so)", not o["hold"] and o["reason"] == "released: work frozen", str(o))
G = g.Guard(); o = run(G, claude_working=True, frozen_since=time.time() - 10 * 60); check("work frozen for only 10 min: still held", o["hold"], str(o))
G = g.Guard(); o = run(G, claude_working=True, frozen_since=time.time() - 40 * 60, vscode_busy=True); check("a busy terminal process means it is not frozen: still held", o["hold"], str(o))
G = g.Guard(); o = run(G, claude_working=True, frozen_since=None); check("moving work: held", o["hold"], str(o))
cs.write_text(json.dumps({"model": "opus", "x": 1})); run(g.Guard())
d = json.loads(cs.read_text()); r = json.loads((tmp / "model-reset.json").read_text())
check("a /model opus that changed the saved default is put back to opusplan, other keys kept, note for the panel", d["model"] == "opusplan" and d["x"] == 1 and r["was"] == "opus")
(tmp / "model-reset.json").unlink(); run(g.Guard()); check("already opusplan: nothing written", not (tmp / "model-reset.json").exists())
# shipm-ledger runs in the background every 10 min (same spawn pattern as ci-status), never twice at once
class _P:
    def __init__(self, alive): self.alive = alive
    def poll(self): return None if self.alive else 0
_spawned = []; _real_popen, _real_fake = g.subprocess.Popen, g.FAKE
g.subprocess.Popen = lambda cmd, **kw: (_spawned.append(cmd), _P(True))[1]; g.FAKE = None
try:
    G = g.Guard(); t0 = 1_000_000.0
    G.ledger_check(t0); check("ledger: first check starts shipm-ledger --update", len(_spawned) == 1 and _spawned[0][1].endswith("bin/shipm-ledger") and _spawned[0][2] == "--update", str(_spawned))
    G.ledger_proc = _P(False); G.ledger_check(t0 + 599); check("ledger: not again before 10 minutes", len(_spawned) == 1)
    G.ledger_check(t0 + 600); check("ledger: again after 10 minutes", len(_spawned) == 2)
    G.ledger_check(t0 + 1300); check("ledger: never a second one while the first still runs", len(_spawned) == 2)
    G.ledger_proc = _P(False); G.ledger_check(t0 + 1300); check("ledger: next one once the first has finished", len(_spawned) == 3)
    g.FAKE = "x"; G.ledger_proc = _P(False); G.ledger_check(t0 + 99999); check("ledger: nothing in fake/test mode", len(_spawned) == 3)
finally:
    g.subprocess.Popen = _real_popen; g.FAKE = _real_fake
# ---- P2/T5: v1 mirror, guarded import, no literal user ----
import pwd, shutil, subprocess
cfgdir = tmp / "cfg"; cfgdir.mkdir(); os.environ["SHIPMIRACLE_CONFIG"] = str(cfgdir); os.environ["SHIPMIRACLE_HOME"] = str(tmp / "home")
def v1env(name):
    f = tmp / "v1" / name
    return json.loads(f.read_text()) if f.exists() else None
check("Shipmiracle imported in the normal case", g.shipmiracle_state is not None and g.shipmiracle_config is not None)
obj = {"work": True, "hold": True, "actions": ["wrap-up flag", "checkpoint"], "ts": 5, "on": True}
g.jwrite_mirrored("guard.json", obj)
check("mirror on: legacy guard.json is exactly json.dumps(obj), the v1 data equals it", (tmp / "guard.json").read_text() == json.dumps(obj)
      and v1env("guard.json")["writer"] == "shipmiracle-guard" and v1env("guard.json")["data"] == obj, str(v1env("guard.json")))
(cfgdir / "config.json").unlink() if (cfgdir / "config.json").exists() else None
g.jwrite_mirrored("away.json", {"away": True, "ts": 7})
check("mirror: away.json legacy content == v1 data", json.loads((tmp / "away.json").read_text()) == v1env("away.json")["data"] == {"away": True, "ts": 7})
shutil.rmtree(tmp / "v1"); (cfgdir / "config.json").write_text(json.dumps({"switches.state.v1": False}))
g.jwrite_mirrored("guard.json", obj)
check("switch off: legacy written, no v1 file", (tmp / "guard.json").exists() and not (tmp / "v1/guard.json").exists())
(cfgdir / "config.json").unlink()
(tmp / "v1/guard.json").mkdir(parents=True); g.shipmiracle_state._mirror_failed = False
g.jwrite_mirrored("guard.json", {"a": 1}); g.jwrite_mirrored("guard.json", {"a": 2})
evs = [l for l in (tmp / "v1/events.jsonl").read_text().splitlines() if "state.v1_write_failed" in l] if (tmp / "v1/events.jsonl").exists() else []
check("unwritable v1: the legacy file still written both times, exactly one state.v1_write_failed event", json.loads((tmp / "guard.json").read_text()) == {"a": 2} and len(evs) == 1, str(evs))
shutil.rmtree(tmp / "v1")
(cfgdir / "config.json").unlink() if (cfgdir / "config.json").exists() else None
# the real step() path writes both files through the helper (not in FAKE/DRY mode: a stub system reading, no spawns)
_f, _rs, _kd, _hp, _lc = g.FAKE, g.read_system, g.keep_default_model, g.Guard.held_projects, g.Guard.ledger_check
g.FAKE = None; g.keep_default_model = lambda: None; g.Guard.held_projects = lambda self, now: None; g.Guard.ledger_check = lambda self, now: None
g.Guard.ci_check = lambda self, now, vs: None
g.read_system = lambda: {"vscode": False, "claude_working": False, "agents": 0, "vscode_busy": False, "lid_closed": False, "idle_s": 0, "poke_age": 999,
                         "on_ac": True, "battery_pct": 100, "thermal_limit": 100, "sleep_disabled": False, "lpm": False}
g.Guard.awake = lambda self, *a: None; g.Guard.lowpower = lambda self, *a: None
try:
    o = g.Guard().step()
finally:
    g.FAKE, g.read_system, g.keep_default_model, g.Guard.held_projects, g.Guard.ledger_check = _f, _rs, _kd, _hp, _lc
check("step(): guard.json and away.json written to legacy and v1, same data", json.loads((tmp / "guard.json").read_text()) == v1env("guard.json")["data"] == o and v1env("away.json")["data"] == json.loads((tmp / "away.json").read_text()), str(o)[:200])
# guarded import: a copy of bin/ with no shipmiracle/ (or a broken one) next to it must load, stay alive and write guard.json
def broken_pkg(c):
    (c / "shipmiracle").mkdir(); (c / "shipmiracle/__init__.py").write_text("def (:\n")
for label, mk in (("missing shipmiracle/", lambda c: None), ("shipmiracle/ with a SyntaxError", broken_pkg)):
    c = tmp / ("copy_" + label.split()[0].replace("/", "")); (c / "bin").mkdir(parents=True); shutil.copy(ws / "bin/shipm-guard", c / "bin/shipm-guard"); mk(c)
    st2 = c / "state"; st2.mkdir()
    code = ("import importlib.machinery as m, importlib.util as u, json; sp=u.spec_from_loader('g', m.SourceFileLoader('g', %r)); g=u.module_from_spec(sp); sp.loader.exec_module(g); "
            "g.jwrite_mirrored('guard.json', {'x': 1}); print(json.dumps([g.shipmiracle_state is None, g.shipmiracle_config is None]))") % str(c / "bin/shipm-guard")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=str(c), env=dict(os.environ, SHIPMIRACLE_STATE=str(st2)))
    check("guarded import (%s): module loads without exiting, Shipmiracle is off, guard.json still written" % label,
          r.returncode == 0 and r.stdout.strip() == "[true, true]" and json.loads((st2 / "guard.json").read_text()) == {"x": 1} and not (st2 / "v1").exists(), r.stdout + r.stderr[-300:])
    r = subprocess.run([sys.executable, str(c / "bin/shipm-guard"), "status"], capture_output=True, text=True, cwd=str(c), env=dict(os.environ, SHIPMIRACLE_STATE=str(st2)))
    check("guarded import (%s): the script itself still runs (status)" % label, r.returncode == 0 and '"x": 1' in r.stdout, r.stdout + r.stderr[-300:])
# no literal account name in bin/ (derived at test time)
me = pwd.getpwuid(os.getuid()).pw_name
hits = [str(f.relative_to(ws)) for f in (ws / "bin").iterdir() if f.is_file() and not f.is_symlink() and me.encode() in f.read_bytes()]
check("no literal account name (%s) in any file of bin/" % me, not hits, str(hits))
# admin-setup text uses the account name from the password database
r = subprocess.run([sys.executable, str(ws / "bin/shipm-guard"), "admin-setup"], capture_output=True, text=True, env=dict(os.environ, SHIPMIRACLE_STATE=str(tmp)))
check("admin-setup prints the sudoers line for the pwd account", r.returncode == 0 and f"{me} ALL=(root) NOPASSWD: /usr/bin/pmset -a disablesleep 1" in r.stdout, r.stdout + r.stderr)
check("admin-setup points to bin/shipm-guard-admin and names no /tmp path", f"sudo {ws}/bin/shipm-guard-admin" in r.stdout and "/tmp" not in r.stdout and "visudo -cf" not in r.stdout, r.stdout)

# ======== T1: reload on code change (same pid, caffeinate kept, no disablesleep 0, a broken file is not loaded) ========
import hashlib, re as _re
EV = tmp / "events.log"
def ev_lines(): return EV.read_text().splitlines() if EV.exists() else []
def reset_reload(path, code_sha):
    g.SELF = path; g.CODE_SHA = code_sha; g._RELOAD.update(sig=None, bad=None)
src = (ws / "bin/shipm-guard").read_bytes()
cand = tmp / "rl_self"; cand.write_bytes(src)
_calls = []; _real_execv = os.execv
os.execv = lambda exe, argv: _calls.append((exe, list(argv), os.getpid(), os.environ.get(g.CARRY_ENV)))
_orig_self, _orig_sha = g.SELF, g.CODE_SHA
_real_settle = g._settle_sleep; _waits = []; g._settle_sleep = lambda s: _waits.append(s)       # the 1 s settle wait is skipped in the unit tests (one test below uses it for real)
try:
    EV.unlink() if EV.exists() else None
    reset_reload(cand, hashlib.sha256(src).hexdigest()[:12])
    G = g.Guard(); G.last_sign = 123.0; G.cut = True
    check("reload: unchanged file -> no exec", g.reload_check(G) == "same" and not _calls)
    cand.write_bytes(src + b"\n# a harmless change\n")
    pid_before = os.getpid()
    r1 = g.reload_check(G)
    check("reload: changed + compiles -> execv(python, [python, file, 'run', '--reloaded']) in the SAME process (same pid)",
          r1 == "reloading" and len(_calls) == 1 and _calls[0][0] == sys.executable and _calls[0][1] == [sys.executable, str(cand), "run", "--reloaded"] and _calls[0][2] == pid_before, str(_calls))
    carried = json.loads(_calls[0][3] or "{}")
    check("reload: the hold timers and latches travel with it", carried.get("last_sign") == 123.0 and carried.get("cut") is True and carried.get("caff") is None, str(carried))
    check("reload: the change is logged once with the old and new code hash", sum("reload pid=%d" % pid_before in l for l in ev_lines()) == 1)
    os.environ.pop(g.CARRY_ENV, None)
    # broken new file: not loaded, logged once (and not again on the next loops)
    _calls.clear(); EV.unlink()
    reset_reload(cand, hashlib.sha256(src).hexdigest()[:12])
    cand.write_bytes(src + b"\ndef (:\n")
    rs = [g.reload_check(G) for _ in range(3)]
    check("reload: a file that does not compile is not loaded (no exec)", rs[0] == "bad" and not _calls, str(rs))
    check("reload: ... and it is logged exactly once", sum("does not compile" in l for l in ev_lines()) == 1, str(ev_lines()))
    cand.write_bytes(src + b"\ndef (:  # still broken, different bytes\n")
    g.reload_check(G)
    check("reload: a different broken version is logged again, still never loaded", sum("does not compile" in l for l in ev_lines()) == 2 and not _calls)
    check("reload: no .pyc litter next to the checked file", not list(tmp.glob("__pycache__")) and not (ws / "bin/__pycache__").exists())
    cand.write_bytes(src + b"\n# fixed\n")
    check("reload: the fixed file loads", g.reload_check(G) == "reloading" and len(_calls) == 1)
    os.environ.pop(g.CARRY_ENV, None)
    check("reload: a changed file waits RELOAD_SETTLE (1 s) before it is judged", _waits and all(w == 1.0 for w in _waits) and g.RELOAD_SETTLE == 1.0, str(_waits))
    # half-written file: it changes again during the wait -> not loaded, not remembered; once it stays the same it loads
    _calls.clear(); _waits.clear(); reset_reload(cand, hashlib.sha256(src).hexdigest()[:12])
    cand.write_bytes(src + b"\n# half")
    def _grow(secs, _n=[0]):
        _n[0] += 1; _waits.append(secs)
        if _n[0] <= 2: cand.write_bytes(cand.read_bytes() + b" more%d" % _n[0])        # still being written during the wait
    g._settle_sleep = _grow
    rs = [g.reload_check(G) for _ in range(3)]
    check("reload: a file still changing during the wait is not loaded (unstable twice), then loads once unchanged", rs == ["unstable", "unstable", "reloading"] and len(_calls) == 1, str((rs, _calls)))
    os.environ.pop(g.CARRY_ENV, None)
    # the same size and mtime on both checks is the only thing that counts (content is not compared before the wait)
    _calls.clear(); reset_reload(cand, hashlib.sha256(src).hexdigest()[:12]); g._settle_sleep = lambda s: None
    cand.write_bytes(src + b"\n# stable\n"); check("reload: a stable changed file loads on the first look after the wait", g.reload_check(G) == "reloading" and len(_calls) == 1)
    os.environ.pop(g.CARRY_ENV, None)
finally:
    os.execv = _real_execv; g.SELF, g.CODE_SHA = _orig_self, _orig_sha; os.environ.pop(g.CARRY_ENV, None); g._settle_sleep = _real_settle
# start-up reset of disablesleep: normal start resets a stale block, a --reloaded start does not
_real_sh = g.sh; _real_sp = g.Guard.sudo_pmset; _pm = []
g.sh = lambda cmd, timeout=8: "SleepDisabled\t1\n"; g.Guard.sudo_pmset = lambda self, *a: (_pm.append(a), True)[1]
try:
    G = g.Guard(); g.startup_reset(G, reloaded=False); a1 = list(_pm); _pm.clear()
    g.startup_reset(G, reloaded=True); a2 = list(_pm)
finally:
    g.sh = _real_sh; g.Guard.sudo_pmset = _real_sp
check("start-up: a stale sleep block is reset (disablesleep 0)", a1 == [("-a", "disablesleep", "0")], str(a1))
check("start-up with --reloaded: no disablesleep 0 (no sleep gap)", a2 == [], str(a2))
# the caffeinate of the old incarnation is adopted, not doubled; only if it really is caffeinate -w <our pid>
_sleeper = subprocess.Popen(["/bin/sleep", "60"])
try:
    G = g.Guard(); G.caff = g._Adopted(_sleeper.pid)
    c = G.carry(); check("carry: live caffeinate pid handed over", c["caff"] == _sleeper.pid, str(c))
    g.sh = lambda cmd, timeout=8: f"/usr/bin/caffeinate -i -s -w {os.getpid()}\n"
    G2 = g.Guard(); G2.adopt(c)
    check("adopt: a real 'caffeinate -w <our pid>' is taken over and seen alive", isinstance(G2.caff, g._Adopted) and G2.caff.poll() is None)
    g.sh = lambda cmd, timeout=8: "/usr/bin/vim\n"
    G3 = g.Guard(); G3.adopt(c)
    check("adopt: a pid that is not our caffeinate is not adopted", G3.caff is None)
    g.sh = lambda cmd, timeout=8: f"/usr/bin/caffeinate -i -s -w {os.getpid() + 1}\n"
    G4 = g.Guard(); G4.adopt(c); check("adopt: caffeinate watching another pid is not adopted", G4.caff is None)
    for label, line in (("a longer pid that starts with ours (-w <pid>9)", f"/usr/bin/caffeinate -i -s -w {os.getpid()}9"),
                        ("our pid text only inside another token (-w=<pid>)", f"/usr/bin/caffeinate -i -s -w={os.getpid()}"),
                        ("-w not followed by our pid but our pid elsewhere", f"/usr/bin/caffeinate -w 1 {os.getpid()}"),
                        ("another program that merely mentions caffeinate and -w <pid>", f"/usr/bin/sleep 60 caffeinate -w {os.getpid()}"),
                        ("-w <pid> as the last token with nothing before the program", f"-w {os.getpid()}"),
                        ("empty ps answer", "")):
        g.sh = lambda cmd, timeout=8, line=line: line + "\n"
        Gx = g.Guard(); Gx.adopt(c); check("adopt: %s is not adopted" % label, Gx.caff is None, line)
    g.sh = lambda cmd, timeout=8: f"/usr/bin/caffeinate -i -s -w {os.getpid()}\n"
    Gx = g.Guard(); Gx.adopt(c); check("adopt: exact tokens '-w' + our pid are adopted", isinstance(Gx.caff, g._Adopted))
    # carried times are clamped to <= now
    _n = time.time(); Gx = g.Guard(); Gx.adopt({"last_sign": _n + 10 ** 7, "stretch_start": _n + 5 * 3600})
    check("adopt: a last_sign / stretch_start in the future is clamped to now", Gx.last_sign <= time.time() and Gx.stretch_start <= time.time() and Gx.last_sign >= _n and Gx.stretch_start >= _n, f"{Gx.last_sign} {Gx.stretch_start}")
    Gx = g.Guard(); Gx.adopt({"last_sign": float("inf"), "stretch_start": float("nan")})
    check("adopt: inf / NaN times are clamped to now too", Gx.last_sign <= time.time() and Gx.stretch_start <= time.time(), f"{Gx.last_sign} {Gx.stretch_start}")
    Gx = g.Guard(); Gx.adopt({"last_sign": 123.5, "stretch_start": 100}); check("adopt: past times stay as carried", Gx.last_sign == 123.5 and Gx.stretch_start == 100)
    G2.caff.terminate(); _sleeper.wait(timeout=10)
    check("adopted caffeinate: poll() sees it end after terminate()", G2.caff.poll() is not None)
finally:
    g.sh = _real_sh
    if _sleeper.poll() is None: _sleeper.kill(); _sleeper.wait()
# end to end, real process: edit its own file -> same pid re-executes; a broken edit is ignored; fake readings so no pmset is ever changed
def wait_for(pred, secs):
    end = time.time() + secs
    while time.time() < end:
        if pred(): return True
        time.sleep(0.3)
    return False
rl = tmp / "rl"; (rl / "bin").mkdir(parents=True); rl_state = rl / "state"; rl_state.mkdir()
(rl / "fake.json").write_text(json.dumps({"vscode": False}))
rl_file = rl / "bin/shipm-guard"; rl_file.write_bytes(src)
rl_ev = rl_state / "events.log"
def rl_lines(): return rl_ev.read_text().splitlines() if rl_ev.exists() else []
proc = subprocess.Popen([sys.executable, str(rl_file), "run"], env=dict(os.environ, SHIPMIRACLE_STATE=str(rl_state), SHIPMIRACLE_GUARD_FAKE=str(rl / "fake.json")),
                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
try:
    check("e2e reload: the daemon starts (reloaded=False, its pid logged)", wait_for(lambda: any(f"started pid={proc.pid} " in l and "reloaded=False" in l for l in rl_lines()), 20), str(rl_lines()))
    rl_file.write_bytes(src + b"\ndef (:\n"); time.sleep(3.5)
    check("e2e reload: a broken edit is not loaded (process alive, no restart line, one 'does not compile' line)", proc.poll() is None and sum("reloaded=True" in l for l in rl_lines()) == 0 and sum("does not compile" in l for l in rl_lines()) == 1, str(rl_lines()))
    rl_file.write_bytes(src + b"\n# new version\n")
    check("e2e reload: a good edit restarts the code in the SAME pid (reloaded=True, same pid, still running)",
          wait_for(lambda: any(f"started pid={proc.pid} " in l and "reloaded=True" in l for l in rl_lines()), 20) and proc.poll() is None, str(rl_lines()))
    check("e2e reload: the new process logs the new code hash", len({_re.search(r"code=(\w+)", l).group(1) for l in rl_lines() if " started pid=" in l}) == 2, str(rl_lines()))
finally:
    proc.terminate()
    try: proc.wait(timeout=15)
    except subprocess.TimeoutExpired: proc.kill(); proc.wait()
# guard.json says which code runs (non-fake path): code_started = {sha, ts}, plus pid and manual_until
check("guard.json: code_started.sha is the sha256 prefix of the running file, ts is recent, pid is ours",
      json.loads((tmp / "guard.json").read_text()).get("code_started", {}).get("sha") == hashlib.sha256((ws / "bin/shipm-guard").read_bytes()).hexdigest()[:12]
      and abs(json.loads((tmp / "guard.json").read_text())["code_started"]["ts"] - time.time()) < 600 and json.loads((tmp / "guard.json").read_text())["pid"] == os.getpid()
      and "manual_until" in json.loads((tmp / "guard.json").read_text()), (tmp / "guard.json").read_text()[:300])

# ======== T2: manual hold ========
GUARD = str(ws / "bin/shipm-guard"); HOLDF = tmp / "guard.hold"
def cli(*args):
    return subprocess.run([sys.executable, GUARD, *args], capture_output=True, text=True, env={**{k: v for k, v in os.environ.items() if k != "CLAUDECODE"}, "SHIPMIRACLE_STATE": str(tmp)})
def until_of():
    return json.loads(HOLDF.read_text())["until"] if HOLDF.exists() else None
HOLDF.unlink(missing_ok=True)
t0 = time.time(); r = cli("hold", "90m")
check("hold 90m: exit 0, end time ~ now + 90 min", r.returncode == 0 and until_of() is not None and abs(until_of() - (t0 + 5400)) < 15, r.stdout + r.stderr)
r = cli("hold", "2h"); check("hold 2h: replaces it, ~ now + 2 h", r.returncode == 0 and abs(until_of() - (time.time() + 7200)) < 15)
tgt = time.strftime("%H:%M", time.localtime(time.time() + 1800)); r = cli("hold", "until", tgt)
check("hold until HH:MM: the next such time (about 30 min away)", r.returncode == 0 and 1700 <= until_of() - time.time() <= 1860, f"{tgt} {r.stdout}{r.stderr}")
r = cli("hold", f"until {tgt}"); check("hold 'until HH:MM' as one argument works too", r.returncode == 0)
HOLDF.unlink()
for bad in (["25h"], ["1441m"], ["0m"], ["abc"], ["until", "25:00"], ["until", "12:60"], []):
    r = cli("hold", *bad)
    check("hold %s: refused with exit 2 and no hold written" % (" ".join(bad) or "(nothing)"), r.returncode == 2 and not HOLDF.exists() and r.stderr.strip() != "", r.stdout + r.stderr)
r = cli("hold", "24h"); check("hold 24h exactly: allowed (the maximum)", r.returncode == 0 and HOLDF.exists()); HOLDF.unlink()
now = time.time(); hold_until = int(now + 3600)
def put_hold(until, set_at=None): HOLDF.write_text(json.dumps({"until": int(until), "set": int(set_at if set_at is not None else now)}))
put_hold(hold_until)
G = g.Guard(); o = run(G, vscode=False)
check("manual hold with no work: held, reason 'manual until HH:MM', guard.json field manual_until", o["hold"] and o["reason"] == "manual until " + time.strftime("%H:%M", time.localtime(hold_until)) and o["manual_until"] == hold_until and not o["work"], str(o))
o = run(G, vscode=False, on_ac=False, battery_pct=40); check("manual hold on battery above 15%: still held", o["hold"])
G = g.Guard(); o = run(G, vscode=False, on_ac=False, battery_pct=14)
check("manual hold with NO work: the 15% battery cut still releases it, but no checkpoint (no push of wip/battery-*) and no wrap-up flag", not o["hold"] and o["reason"] == "released: battery cut-off"
      and not any("checkpoint" in x and "no checkpoint" not in x for x in o["actions"]) and not any("wrap-up" in x for x in o["actions"]), str(o))
G = g.Guard(); o = run(G, vscode=False, on_ac=False, battery_pct=24); check("manual hold with no work at 24%: no wrap-up flag (only real work gets one)", o["hold"] and not any("wrap-up" in x for x in o["actions"]), str(o))
G = g.Guard(); o = run(G, claude_working=True, on_ac=False, battery_pct=14)
check("manual hold WITH work: the 15% cut checkpoints as before", not o["hold"] and any(x == "checkpoint" for x in o["actions"]), str(o))
o = run(G, vscode=False, on_ac=False, battery_pct=14); check("manual hold: stays released while unplugged", not o["hold"])
o = run(G, vscode=False, on_ac=True, battery_pct=14); check("manual hold: plugged in again -> held again", o["hold"] and o["reason"].startswith("manual until"))
G = g.Guard(); o = run(G, vscode=False, thermal_limit=60); check("manual hold: a hot Mac still releases it", not o["hold"] and o["reason"] == "released: Mac is hot", str(o))
(tmp / "guard.off").write_text("off"); G = g.Guard(); o = run(G, vscode=False)
check("manual hold: the Off switch still wins", not o["hold"] and o["reason"] == "switched off" and HOLDF.exists(), str(o))
(tmp / "guard.off").unlink()
G = g.Guard(); o = run(G, claude_working=True, frozen_since=time.time() - 40 * 60)
check("manual hold does NOT override 'work frozen' (released, reason says so)", not o["hold"] and o["reason"] == "released: work frozen", str(o))
G = g.Guard(); o = run(G, vscode=False, frozen_since=time.time() - 40 * 60); check("manual hold, frozen_since set but no work: still held (nothing to release)", o["hold"] and o["reason"].startswith("manual until"), str(o))
G = g.Guard(); G.stretch_start = time.time() - 13 * 3600; G.last_sign = time.time(); o = run(G, claude_working=True)
check("manual hold does NOT override the 12 h stuck release", not o["hold"] and o["reason"] == "released: same work for 12 h", str(o))
G = g.Guard(); o = run(G, claude_working=True, frozen_since=time.time() - 10 * 60); check("manual hold + work frozen for only 10 min: held", o["hold"], str(o))
r = cli("status"); st = json.loads(r.stdout)
check("status shows the manual hold", st.get("manual_until") == hold_until and st.get("manual", "").startswith("manual until "), r.stdout[:300])
r = cli("release"); G = g.Guard(); o = run(G, vscode=False)
check("release: file gone, exit 0, no hold, manual_until null", r.returncode == 0 and not HOLDF.exists() and not o["hold"] and o["manual_until"] is None, r.stdout + str(o))
check("release without a hold: exit 0, says so", cli("release").returncode == 0 and "no manual hold" in cli("release").stdout)
put_hold(time.time() - 5, time.time() - 3600); G = g.Guard(); o = run(G, vscode=False)
check("expired hold: not held, file removed, 'manual hold ended' logged", not o["hold"] and o["manual_until"] is None and not HOLDF.exists() and any("manual hold ended" in l for l in ev_lines()), str(o))
put_hold(time.time() + 48 * 3600, time.time()); G = g.Guard(); o = run(G, vscode=False)
check("a hand-edited hold longer than 24 h is ignored and removed", not o["hold"] and o["manual_until"] is None and not HOLDF.exists(), str(o))
HOLDF.write_text("not json"); G = g.Guard(); o = run(G, vscode=False)
check("a malformed hold file is ignored and removed (fail closed)", not o["hold"] and not HOLDF.exists())
# the cap cannot be bypassed by a hand-edited set time: set in the future, or an end more than 24 h from now
for label, (u_, s_) in {"set 3 h in the future, ends 4 h from now": (time.time() + 4 * 3600, time.time() + 3 * 3600),
                        "set now, ends 25 h from now": (time.time() + 25 * 3600, time.time()),
                        "set 30 h ahead, ends 40 h ahead (10 h long)": (time.time() + 40 * 3600, time.time() + 30 * 3600)}.items():
    EV.unlink() if EV.exists() else None
    put_hold(u_, s_); G = g.Guard(); o = run(G, vscode=False); o2 = run(G, vscode=False)
    check("hold cap bypass (%s): ignored, removed, logged once" % label, not o["hold"] and o["manual_until"] is None and not HOLDF.exists() and not o2["hold"]
          and sum("manual hold file ignored" in l for l in ev_lines()) == 1, str(o) + str(ev_lines()))
put_hold(time.time() + 24 * 3600 - 30, time.time() - 30); G = g.Guard(); o = run(G, vscode=False)
check("a hold of exactly the 24 h maximum is still honoured", o["hold"] and o["manual_until"] is not None and HOLDF.exists(), str(o)); HOLDF.unlink()
# hold / release are owner-only: refused inside a Claude chat (CLAUDECODE set, any value), nothing changed
def cli_chat(*args, value="1"):
    return subprocess.run([sys.executable, GUARD, *args], capture_output=True, text=True, env={**os.environ, "CLAUDECODE": value, "SHIPMIRACLE_STATE": str(tmp)})
HOLDF.unlink(missing_ok=True)
r = cli_chat("hold", "90m")
check("hold inside a chat (CLAUDECODE=1): exit 2, clear message, no hold file", r.returncode == 2 and not HOLDF.exists() and "owner" in r.stderr and "CLAUDECODE" in r.stderr, r.stdout + r.stderr)
r = cli_chat("hold", "90m", value="")
check("hold with CLAUDECODE set but empty: still refused", r.returncode == 2 and not HOLDF.exists(), r.stdout + r.stderr)
put_hold(time.time() + 3600); before = HOLDF.read_text(); r = cli_chat("release")
check("release inside a chat: exit 2, the hold file is untouched", r.returncode == 2 and HOLDF.exists() and HOLDF.read_text() == before and "owner" in r.stderr, r.stdout + r.stderr)
r = cli_chat("status"); check("status stays readable inside a chat", r.returncode == 0 and "manual_until" in r.stdout, r.stdout + r.stderr)
r = cli("release"); check("release in the owner's terminal (no CLAUDECODE) works", r.returncode == 0 and not HOLDF.exists(), r.stdout + r.stderr)

# ======== T3: one events.log line per network outage ========
EV.unlink() if EV.exists() else None
G = g.Guard(); base = 1_800_000_000.0
for dt, up in ((0, True), (30, False), (60, True)): G.net_watch(base + dt, up)
check("outage: a single failed probe (blip) logs nothing", not any("net_outage" in l for l in ev_lines()), str(ev_lines()))
for dt, up in ((100, True), (130, False), (160, False), (190, False), (220, True), (250, True)): G.net_watch(base + dt, up)
outs = [l for l in ev_lines() if "net_outage" in l]
check("outage: two failed probes then a good one = exactly one line", len(outs) == 1, str(outs))
m = _re.fullmatch(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d net_outage start=(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d) end=(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d) gap_s=(\d+)", outs[0]) if outs else None
check("outage line format: start, end, gap_s; start = first failed probe, end = first good probe", bool(m) and m.group(3) == "90" and m.group(1) == time.strftime("%FT%T", time.localtime(base + 130)) and m.group(2) == time.strftime("%FT%T", time.localtime(base + 220)), outs[0] if outs else "")
for dt, up in ((300, False), (330, False), (360, True)): G.net_watch(base + dt, up)
check("outage: a second outage adds a second line (gap 60)", len([l for l in ev_lines() if "net_outage" in l]) == 2 and ev_lines()[-1].endswith("gap_s=60"), str(ev_lines()))
G.net_watch(base + 400, None); G.net_watch(base + 430, None)
check("outage: no probe (None) changes nothing", len([l for l in ev_lines() if "net_outage" in l]) == 2)
# the probe: Apple's captive page, every 30 s at most, reads no network name; the log never has a network name
_probes = []; _real_sh = g.sh; g.sh = lambda cmd, timeout=8: (_probes.append(cmd), "<HTML><BODY>Success</BODY></HTML>")[1]
try:
    g._NET["t"] = 0; u1 = g.net_probe(1000.0); u2 = g.net_probe(1010.0); u3 = g.net_probe(1031.0)
    g.sh = lambda cmd, timeout=8: (_probes.append(cmd), "")[1]; u4 = g.net_probe(1100.0)
finally:
    g.sh = _real_sh
check("probe: True when the page says Success, None while not due (30 s), False when it does not", (u1, u2, u3, u4) == (True, None, True, False) and len(_probes) == 3 and "captive.apple.com" in " ".join(_probes[0]), str((u1, u2, u3, u4, _probes)))
# the probe runs only while the guard is ON and HOLDING (step() in the real, non-fake path with a stub reading); never when off or idle
_f, _rs, _kd, _np = g.FAKE, g.read_system, g.keep_default_model, g.net_probe
_sys = {"vscode": True, "claude_working": True, "agents": 0, "vscode_busy": False, "lid_closed": False, "idle_s": 0, "poke_age": 999,
        "on_ac": True, "battery_pct": 100, "thermal_limit": 100, "sleep_disabled": False, "lpm": False}
_asked = []; _hp2, _lc2, _ci2 = g.Guard.held_projects, g.Guard.ledger_check, g.Guard.ci_check      # no scan / ledger / ci process is started
g.Guard.held_projects = lambda self, now: None; g.Guard.ledger_check = lambda self, now: None; g.Guard.ci_check = lambda self, now, vs: None
g.FAKE = None; g.keep_default_model = lambda: None; g.net_probe = lambda now: (_asked.append(now), True)[1]
try:
    g.read_system = lambda: dict(_sys)
    G = g.Guard(); G.step(); n_hold = len(_asked)
    check("probe: asked when the guard is on and holding", n_hold == 1, str(_asked))
    g.read_system = lambda: dict(_sys, claude_working=False, vscode_busy=False, vscode=True)
    G = g.Guard(); G.step(); G.step()
    check("probe: not asked when idle (no work, no manual hold)", len(_asked) == n_hold, str(_asked))
    (tmp / "guard.off").write_text("off"); g.read_system = lambda: dict(_sys)
    G = g.Guard(); G.step()
    check("probe: not asked when the guard is OFF (even with work)", len(_asked) == n_hold, str(_asked)); (tmp / "guard.off").unlink()
    HOLDF.write_text(json.dumps({"until": int(time.time() + 3600), "set": int(time.time())})); g.read_system = lambda: dict(_sys, claude_working=False)
    G = g.Guard(); G.step()
    check("probe: asked during a manual hold without work", len(_asked) == n_hold + 1, str(_asked)); HOLDF.unlink()
    # an open outage is dropped when holding stops (its start would be stale), so no wrong gap is logged later
    EV.unlink() if EV.exists() else None
    g.net_probe = lambda now: False; g.read_system = lambda: dict(_sys); G = g.Guard(); G.step(); G.step()
    g.read_system = lambda: dict(_sys, claude_working=False, vscode=False); G.last_sign = 0; G.step()
    check("probe: an open outage is forgotten when holding ends", G.net == {}, str(G.net))
finally:
    g.FAKE, g.read_system, g.keep_default_model, g.net_probe = _f, _rs, _kd, _np
    g.Guard.held_projects, g.Guard.ledger_check, g.Guard.ci_check = _hp2, _lc2, _ci2
src_text = (ws / "bin/shipm-guard").read_text()
check("no network name is read or logged anywhere in the guard (no ssid / airport / networksetup)", not _re.search(r"ssid|airport|networksetup|wdutil", src_text, _re.I) and not any("ssid" in l.lower() for l in ev_lines()))
print("\nFAILED:" if fails else "\nALL PASS", fails)
sys.exit(1 if fails else 0)
