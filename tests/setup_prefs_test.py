#!/usr/bin/env python3
"""The standard onboarding (plan 2026-10-21-cross-platform-onboarding.md, acceptance O1-O11): Check / Quick setup / Connect, the five choices, --prefs, --undo prefs,
--yes, per-OS rows with SHIPMIRACLE_FAKE_OS, the hook self-test of row 0, and the output scan. Everything runs under SHIPMIRACLE_TEST=1 with the temp home of tests/setup_fixture.py
and FAKE tools in SHIPMIRACLE_SETUP_BIN; no real claude, launchctl, brew or browser. Run: python3 tests/setup_prefs_test.py"""
import json, os, pathlib, re, shutil, subprocess, sys, time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import setup_fixture as F  # noqa: E402
from shipmiracle import config, platform as aplat  # noqa: E402
from shipmiracle.setup import manifest, onboard, rows, run  # noqa: E402

fails = 0
n_checks = 0
ALL_OUT = []                    # every line any run printed (O11 scans it)


def check(name, ok, info=""):
    global fails, n_checks
    n_checks += 1
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(info)[:600]))
    fails += 0 if ok else 1


os.environ["SHIPMIRACLE_FAKE_OS"] = "macos"
ALL = (F.HOME, F.STATE, F.CFG, F.WS)
CFGFILE = F.CFG / "config.json"


def stored():
    config._cache.clear()
    return {k: config.get(k, None) for k in onboard_keys}


onboard_keys = ("prefs.lang", "paths.projects_dir", "prefs.autonomy", "prefs.keep_awake", "prefs.notify")


class Asker:
    """Stands in for the terminal: records every prompt, answers '' (Enter) to the choices and 'y' to [y/N] questions unless `answers` says otherwise."""
    def __init__(self, answers=None, boom=None):
        self.prompts, self.answers, self.boom = [], dict(answers or {}), boom

    def __call__(self, prompt):
        self.prompts.append(prompt)
        if self.boom and self.boom in prompt:
            raise KeyboardInterrupt
        for k, v in self.answers.items():
            if k in prompt:
                return v
        return "y" if "[y/N]" in prompt else ""

    def choices(self):
        return [p for p in self.prompts if re.search(r"\d/\d ", p) and "?" in p]


def go(asker=None, yes=False, **kw):
    lines = []
    ctx = run.Ctx(yes=yes, say=lines.append, ask=asker, **kw)
    rc = onboard.run_all(ctx)
    ALL_OUT.extend(lines)
    return rc, lines


def steps(action):
    return [s for s in manifest.load()["steps"] if s["action"] == action]


# ================================================================ O1 fresh account, Enter x5
F.reset()
a = Asker()
rc, lines = go(a)
check("O1: exactly 5 choice prompts (Enter x5)", len(a.choices()) == 5, a.choices())
st = stored()
check("O1: the 5 config keys hold the defaults", st["prefs.lang"] == "en" and st["prefs.autonomy"] == "normal" and st["prefs.keep_awake"] is True and st["prefs.notify"] == "vscode" and st["paths.projects_dir"], st)
check("O1: one manifest step for the choices", len(steps("prefs")) == 1 and sorted(steps("prefs")[0]["keys"]) == sorted(onboard_keys), steps("prefs"))
check("O1: ends ready, exit 0 (Connect verified the missing items)", rc == 0 and any("Ready: yes" in l for l in lines), (rc, lines[-6:]))
check("O1: the three stages are printed", lines[0].startswith("This computer:") and "Check" in lines and any(l.startswith("Quick setup") for l in lines) and any(l.startswith("Connect (") for l in lines), lines[:12])
check("O1: answers live only in the user config, not in the projects folder or the engine", not any(F.DEV.rglob("*")) or all("prefs" not in p.name for p in F.DEV.rglob("*")))
check("O1: the choices are stored by the guarded writer (0600 file)", (CFGFILE.stat().st_mode & 0o777) == 0o600)

# ================================================================ O2 rerun
a = Asker()
before = F.snapshot(*ALL)
rc, lines = go(a)
check("O2: rerun asks nothing, prints at most 3 lines, exit 0", a.prompts == [] and len(lines) <= 3 and rc == 0, (a.prompts, lines))
check("O2: the short form says what is ready", any(l.startswith("Check: all ") and "required ready" in l for l in lines) and lines[-1] == "Nothing to do.", lines)
check("O2: rerun changes no file except the (unchanged) state", [p for p in F.diff(before, F.snapshot(*ALL)) if not p.endswith("flow-errors.log")] == [], F.diff(before, F.snapshot(*ALL)))

# ================================================================ O4 undo prefs / O5 --prefs
before_prefs = stored()
a = Asker({"Language": "arabic", "Notifications": "none"})
lines = []
ctx = run.Ctx(say=lines.append, ask=a)
onboard.run_prefs(ctx)
check("O5: --prefs asks the 5 again with the current answers in brackets", len(a.choices()) == 5 and "[English]" in a.choices()[0] and "[Normal]" in a.choices()[2], a.choices())
st = stored()
check("O5: changed answers are saved", st["prefs.lang"] == "ar" and st["prefs.notify"] == "none" and st["prefs.autonomy"] == "normal", st)
check("O5: a second recorded step exists", len(steps("prefs")) == 2)
a = Asker({"Language": ""})
lines = []
onboard.run_prefs(run.Ctx(say=lines.append, ask=a))
check("O5: answering with Enter now keeps Arabic (bracket default is the stored value)", "[Arabic]" in a.choices()[0] and stored()["prefs.lang"] == "ar", a.choices()[0])
check("O5: nothing changed means no new step", len(steps("prefs")) == 2)
lines = []
res = run.undo("prefs", run.Ctx(say=lines.append))
check("O4: --undo prefs puts the previous values back (one answer set)", stored()["prefs.lang"] == "en" and stored()["prefs.notify"] == "vscode" and res["reversed"] == 1, (stored(), lines))
res = run.undo("prefs", run.Ctx(say=lines.append))
check("O4: undo again reaches the state before the first run: absent keys are removed", all(v is None for v in stored().values()), stored())
check("O4: the choices are asked again after the undo", run.Ctx().init_state.get("prefs_done") is None and rows.BY_ID["prefs"]["probe"](run.Ctx())[0] == "skipped")

# ================================================================ O3 --yes in CI
F.reset(logins=False)
snap_log = F.fake_calls()
rc, out, err = F.cli("init", "--yes", env={"CI": "true", "SHIPMIRACLE_FAKE_OS": "macos"})
ALL_OUT.extend(out.splitlines())
check("O3: --yes with no tty: no choice prompt, defaults stored", "Language for reports?" not in out and stored()["prefs.lang"] == "en" and stored()["prefs.notify"] == "vscode", (out[-400:], err))
calls = F.fake_calls()
check("O3: --yes never opens a browser login (no gh auth login, no claude run beyond the checks) and never sudo", not any(c.startswith("gh auth login") for c in calls) and "sudo" not in out and not any("login" in c and c.startswith("claude") for c in calls), calls)
check("O3: not logged in to Claude: exit 1 (not ready) and the next step is printed", rc == 1 and "Claude Code login" in out and "Ready: no" in out, (rc, out[-500:]))
F.reset()
rc, out, err = F.cli("init", "--yes", env={"CI": "true", "SHIPMIRACLE_FAKE_OS": "macos"})
check("O3: --yes on a machine whose tools are fine ends ready, exit 0", rc == 0 and "Ready: yes" in out, (rc, out[-500:], err))
rc, out, err = F.cli("init", env={"SHIPMIRACLE_FAKE_OS": "macos"})
check("O3: no --yes and no terminal: nothing is asked, exit 0 when ready", rc == 0 and "Language for reports?" not in out, (rc, out))

# ================================================================ O6 optional red, required green
F.reset()
go(Asker())
for t in ("gitleaks", "docker"):
    (F.SEAM / t).unlink()
res = json.loads(run.check(as_json=True))
stt = {r["id"]: r["state"] for r in res["rows"]}
a = Asker()
rc, lines = go(a)
check("O6: optional rows red, required green: ready is true", res["ready"] is True and stt["gitleaks"] == "red" and len(stt) == 22, stt)
check("O6: Connect lists no optional row, nothing is asked", not any(l.startswith("Connect") for l in lines) and a.prompts == [] and rc == 0, lines)
txt = "\n".join(onboard.render_check(res, run.Ctx(ascii_mode=False)))
check("O6: the Check screen shows an optional row only as a count, never as !", "gitleaks" not in txt and "Optional:" in txt, txt)

# ================================================================ O7 native Windows
F.reset()
snap = F.snapshot(*ALL)
rc, out, err = F.cli("init", env={"SHIPMIRACLE_FAKE_OS": "windows"})
check("O7: SHIPMIRACLE_FAKE_OS=windows: WSL2 line, exit 3, home/state/config untouched", rc == 3 and "wsl --install" in out and F.snapshot(*ALL) == snap, (rc, out, err))
rc, out, err = F.cli("init", "--check", "--json", env={"SHIPMIRACLE_FAKE_OS": "windows"})
check("O7: --check says the same and prints no JSON", rc == 3 and "WSL2" in out and not out.lstrip().startswith("{"), (rc, out))
r = subprocess.run([sys.executable, "-c", "import os, runpy; os.name = 'nt'; runpy.run_path(%r, run_name='__main__')" % str(F.ROOT / "bin" / "shipm")], capture_output=True, text=True, stdin=subprocess.DEVNULL)
check("O7: the launcher on a real native Windows (os.name nt) prints 'Use WSL 2' and exits 2 before importing Shipmiracle", r.returncode == 2 and "Use WSL 2" in r.stderr and "Traceback" not in r.stderr, (r.returncode, r.stderr))

# ================================================================ O8 WSL, project under /mnt/c
F.reset()
env = {"SHIPMIRACLE_FAKE_OS": "wsl", "SHIPMIRACLE_DEV": "/mnt/c/Users/x/dev"}
rc, out, err = F.cli("init", "--check", "--json", env=env)
res = json.loads(out)
byid = {r["id"]: r for r in res["rows"]}
check("O8: WSL, folder on /mnt/c: row 7 needs you and says move it into the Linux home", byid["projects"]["state"] == "red" and "Linux home" in byid["projects"]["detail"], byid["projects"])
check("O8: iOS and backup are 'not on this system' (skipped, os_supported false), never red", all(byid[i]["state"] == "skipped" and byid[i]["os_supported"] is False for i in ("ios", "backup")), [byid[i] for i in ("ios", "backup")])
check("O8: row 9 exists on WSL as the daily systemd timer (optional, never blocks the Check): supported, and without systemd it says why in plain words", byid["guard"]["os_supported"] is True and byid["guard"]["need"] == "optional" and ("systemd" in byid["guard"]["detail"] or byid["guard"]["state"] == "green"), byid["guard"])
check("O8: notifications are not on this system on WSL (panel only)", byid["notify"]["os_supported"] is False)
check("O8: the OS line names WSL", "WSL" in res["os"]["line"] and res["os"]["kind"] == "wsl", res["os"])
rc, out, err = F.cli("init", "--check", env=env)
check("O8: --check text uses the cross symbol for rows that do not exist here (--more) and counts them", rc == 0 and "not on this system" in out, out)
a = Asker()
os.environ["SHIPMIRACLE_FAKE_OS"] = "wsl"
qs = onboard.questions()
check("O8: keep-awake is not asked on WSL (4 choices); system pop-ups are not offered", [q["key"] for q in qs] == ["prefs.lang", "paths.projects_dir", "prefs.autonomy", "prefs.notify"] and [v for v, _ in qs[-1]["opts"]] == ["vscode", "none"], [q["key"] for q in qs])
os.environ["SHIPMIRACLE_FAKE_OS"] = "macos"
res_unsupported_ready = all(r["state"] != "red" for r in res["rows"] if not r["os_supported"])
check("O8: a row that does not exist here never turns the Check red", res_unsupported_ready)

# ================================================================ per-OS rows
for kind, word in (("macos", "xcode-select --install"), ("linux", "sudo apt install git python3"), ("wsl", "sudo apt install git python3")):
    F.reset(with_fakes=False)
    rc, out, err = F.cli("init", "--check", "--json", env={"SHIPMIRACLE_FAKE_OS": kind})
    b = {r["id"]: r for r in json.loads(out)["rows"]}
    check("rows: %s base-tools connect text is the OS's own (%s)" % (kind, word), word in b["base"]["connect"]["text"], b["base"]["connect"])
F.reset(with_fakes=True)
(F.SEAM / "xcode-select").unlink()
os.environ["SHIPMIRACLE_FAKE_OS"] = "linux"
res = json.loads(run.check(as_json=True))
b = {r["id"]: r for r in res["rows"]}
check("rows: Linux does not probe xcode-select: base tools are green with git and python only", b["base"]["state"] == "green", b["base"])
os.environ["SHIPMIRACLE_FAKE_OS"] = "macos"
res = json.loads(run.check(as_json=True))
check("rows: macOS still needs xcode-select", {r["id"]: r for r in res["rows"]}["base"]["state"] == "red")
F.reset()
res = json.loads(run.check(as_json=True))
b = {r["id"]: r for r in res["rows"]}
check("rows: new rows 20 prefs, 21 gitleaks; gitleaks is optional and green with the fake; 22 rows only", [b[i]["n"] for i in ("prefs", "gitleaks")] == [20, 21] and b["gitleaks"]["state"] == "green" and len(b) == 22, b["gitleaks"])
check("rows: every row carries stage, class, os_supported, docs; v stays 1", res["v"] == 1 and all({"stage", "class", "os_supported", "docs"} <= set(r) for r in res["rows"]))
check("rows: prefs is never red and not in the ready rows", b["prefs"]["state"] in ("skipped", "green") and 20 not in rows.READY_ROWS)
check("rows: MCP servers are folded into row 13 (names only)", b["connectors"]["state"] == "advisory" and "MCP" in b["connectors"]["detail"])
(F.HOME / ".claude.json").write_text(json.dumps({"mcpServers": {"playwright": {"command": "npx", "env": {"TOKEN": "zzz-not-shown"}}}}))
res = json.loads(run.check(as_json=True))
d13 = {r["id"]: r for r in res["rows"]}["connectors"]["detail"]
check("rows: the MCP names are listed, commands and env values never", "playwright" in d13 and "zzz" not in d13 and "npx" not in d13, d13)

# ================================================================ O10 hook self-test in row 0
F.reset()
go(Asker())
hook = F.WS / "hooks" / "shipm-hook"
good = hook.read_text()
t0 = time.time()
res = json.loads(run.check(as_json=True))
b = {r["id"]: r for r in res["rows"]}
check("O10: a working registration is green within 2 s of probing", b["engine"]["state"] == "green" and time.time() - t0 < 4, (b["engine"], time.time() - t0))
hook.write_text("import sys\nsys.exit(1)\n")
b = {r["id"]: r for r in json.loads(run.check(as_json=True))["rows"]}
check("O10: a registration whose command fails is red with a next step", b["engine"]["state"] == "red" and "do not work" in b["engine"]["detail"] and "Next step" in b["engine"]["detail"], b["engine"])
hook.write_text("import time\ntime.sleep(5)\n")
t0 = time.time()
b = {r["id"]: r for r in json.loads(run.check(as_json=True))["rows"]}
check("O10: a registration that hangs is red after 2 s, not 5", b["engine"]["state"] == "red" and "within 2 s" in b["engine"]["detail"] and time.time() - t0 < 4.5, (b["engine"]["detail"], time.time() - t0))
hook.write_text(good)
b = {r["id"]: r for r in json.loads(run.check(as_json=True))["rows"]}
check("O10: repaired: green again", b["engine"]["state"] == "green", b["engine"])
st = json.loads((F.HOME / ".claude" / "settings.json").read_text())
cmd = st["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"]
other = F.HOME / "elsewhere"; other.mkdir(); (other / "shipm-hook").write_text("#!/bin/sh\necho shipm-hook selftest ok\n"); (other / "shipm-hook").chmod(0o755)
b2 = json.loads(json.dumps(st)); b2["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"] = cmd.replace(str(F.WS / "hooks" / "shipm-hook"), str(other / "shipm-hook"))
(F.HOME / ".claude" / "settings.json").write_text(json.dumps(b2))
b = {r["id"]: r for r in json.loads(run.check(as_json=True))["rows"]}
check("O10: only the engine's own hooks/shipm-hook is ever run (another path is red, not executed)", b["engine"]["state"] == "red", b["engine"]["detail"])

# ================================================================ autonomy, resume, ascii, flags
F.reset()
a = Asker({"by itself": "on its own"})
rc, lines = go(a)
txt = "\n".join(lines)
config._cache.clear()
check("prefs: 'On its own' prints the owner step and never turns full autopilot on", "never switches full autopilot on" in txt and "shipm switch autopilot.full.enabled on" in txt and config.get("autopilot.full.enabled") is False and stored()["prefs.autonomy"] == "own", txt[-600:])
F.reset(logins=False)
a = Asker(boom="Press Enter")
rc, lines = go(a)
check("resume: Ctrl-C in Connect stops with exit 130 and remembers where", rc == 130 and run.Ctx().init_state.get("connect_next") == "claude", (rc, run.Ctx().init_state))
(F.FAKE / "claude-logged-in").write_text("")
a = Asker()
rc, lines = go(a)
check("resume: the next shipm init continues, asks no choice again, and ends ready", rc == 0 and a.choices() == [] and run.Ctx().init_state.get("connect_next") is None, (rc, lines[-5:]))
F.reset(logins=False)
rc, lines = go(Asker(), ascii_mode=True)
t = "\n".join(lines)
check("ascii fallback: '!!' and 'ok' replace the symbols, no non-ASCII character is printed", "!!" in t and all(ord(c) < 128 for c in t.replace("–", "-")), [c for c in t if ord(c) > 127][:5])
F.reset()
rc, lines = go(Asker(), ascii_mode=False)
check("unicode symbols appear when the terminal can show them", any("✓" in l for l in lines) or any("✓" in l for l in onboard.render_check(json.loads(run.check(as_json=True)), run.Ctx(ascii_mode=False))))
F.reset()
rc, out, err = F.cli("init", "--prefs", "--lang", "ar", "--folder", "~/Developer", "--autonomy", "step", "--awake", "no", "--notify", "none", env={"SHIPMIRACLE_FAKE_OS": "macos"})
st = stored()
check("flags: --prefs with all five flags asks nothing and stores them", rc == 0 and "Language for reports?" not in out and st == {"prefs.lang": "ar", "paths.projects_dir": "~/Developer", "prefs.autonomy": "step", "prefs.keep_awake": False, "prefs.notify": "none"}, (rc, out, err, st))
rc, out, err = F.cli("init", "--lang", "ar")
check("flags: --lang without --prefs is a usage error (exit 2)", rc == 2, (rc, out, err))
rc, out, err = F.cli("init", "--prefs", "--lang", "fr")
check("flags: an unknown choice is a usage error", rc == 2, (rc, err))
rc, out, err = F.cli("init", "--undo", "prefs")
check("flags: --undo prefs from the CLI restores the previous values", rc == 0 and all(v is None for v in stored().values()), (rc, out, err, stored()))
rc, out, err = F.cli("init", "--more")
check("flags: --more lists every row (22) read-only", rc == 0 and out.count("\n") > 22 and "gitleaks" in out and "second" not in out.lower() and "Quick setup choices" in out, out[-300:])
rc, out, err = F.cli("init", "--more", "--yes")
check("flags: --more with another option is a usage error", rc == 2)
F.reset()
bad = Asker({"Projects folder": "relative/path"})
lines = []
try:
    onboard.run_prefs(run.Ctx(say=lines.append, ask=bad))
except Exception as e:
    lines.append("EXC " + repr(e))
check("prefs: an invalid folder answer is refused and re-asked, then the default is used", sum(1 for p in bad.prompts if "Projects folder" in p) == 3 and not any(l.startswith("EXC") for l in lines), (bad.prompts, lines))


# ================================================================ D4 projects folder rules (QA)
from shipmiracle import folder_check  # noqa: E402
F.reset()
real_etc = F.HOME / "link-to-etc"; os.symlink("/etc", str(real_etc))
afile = F.HOME / "a-file"; afile.write_text("x")
os.environ["SHIPMIRACLE_FAKE_OS"] = "macos"
for label, val in (("/etc", "/etc"), ("a symlink to /etc", str(real_etc)), ("a regular file", str(afile)), ("the root", "/"), ("/usr/local/x", "/usr/local/x"), ("/opt/projects", "/opt/projects"),
                   ("a folder of another user", "/Volumes"), ("a relative path", "projects"), ("the whole home", "~/"), ("/etc via ..", "/tmp/../etc")):
    rc, out, err = F.cli("init", "--prefs", "--folder", val, "--lang", "en", "--autonomy", "normal", "--awake", "yes", "--notify", "vscode")
    st = stored()
    check("D4: --folder %s is refused (exit 2, nothing stored, a plain sentence with the next step)" % label, rc == 2 and st["paths.projects_dir"] is None and "shipm init --prefs" in err + out, (rc, err[-200:], st))
rc, out, err = F.cli("config", "set", "paths.projects_dir", "/etc")
check("D4: `shipm config set paths.projects_dir /etc` is refused too", rc != 0 and stored()["paths.projects_dir"] is None, (rc, err))
good = F.HOME / "work" / "projects"
rc, out, err = F.cli("init", "--prefs", "--folder", str(good), "--lang", "en", "--autonomy", "normal", "--awake", "yes", "--notify", "vscode")
check("D4: a normal folder in the home (not yet created) is accepted", rc == 0 and stored()["paths.projects_dir"] == str(good), (rc, err, out[-200:]))
# the probe: a stored bad value (older version, hand edit) shows a red row with the plain message, never green
config._cache.clear()
(F.CFG / "config.json").write_text(json.dumps({"paths.projects_dir": "/etc"}))
config._cache.clear()
try:
    rows.probe_projects(run.Ctx())
    probe_msg = "no error"
except Exception as e:
    probe_msg = repr(e)
res = json.loads(run.check(as_json=True))
b = {r["id"]: r for r in res["rows"]}
check("D4: a stored /etc never makes the Projects folder row green (the config is refused as damaged)", b["projects"]["state"] != "green", b["projects"])
os.unlink(F.CFG / "config.json"); config._cache.clear()
# the probe itself, with the folder given through the test override (SHIPMIRACLE_DEV)
for label, path in (("a regular file", str(afile)), ("a link to /etc", str(real_etc))):
    os.environ["SHIPMIRACLE_DEV"] = path
    r_ = {x["id"]: x for x in json.loads(run.check(as_json=True))["rows"]}["projects"]
    check("D4: row 7 is red for %s with the message and next step" % label, r_["state"] == "red" and "shipm init --prefs" in r_["detail"], r_)
os.environ["SHIPMIRACLE_DEV"] = str(F.DEV)
# rules that the test-temp exemption hides: run them with the exemption off (a real, non-test run) and an explicit home
save = os.environ.pop("SHIPMIRACLE_TEST")
try:
    H = str(F.HOME)
    outside = str(F.ROOT / "tests" / "fixtures")           # a real folder outside the home that is no system folder (the repository)
    lnk = F.HOME / "lnk-out"; os.symlink(outside, str(lnk))
    p1 = folder_check.problem(str(lnk), home=H)
    check("D4: a link that leaves the home is refused", p1 and "link" in p1, p1)
    inner = F.HOME / "real-inner"; inner.mkdir()
    lnk2 = F.HOME / "lnk-in"; os.symlink(str(inner), str(lnk2))
    check("D4: a link that stays inside the home is fine", folder_check.problem(str(lnk2), home=H) is None, folder_check.problem(str(lnk2), home=H))
    check("D4: /etc, /usr/x, /opt/x, / and the home itself are refused with the real rules", all(folder_check.problem(v, home=H) for v in ("/etc", "/usr/x", "/opt/x", "/", H)))
    check("D4: a normal folder in the home passes the real rules", folder_check.problem(H + "/Developer", home=H) is None and folder_check.problem(str(inner), home=H) is None)
    ro = F.HOME / "ro"; ro.mkdir(); os.chmod(ro, 0o500)
    check("D4: a folder the user cannot write in is refused", "cannot write" in (folder_check.problem(str(ro / "sub"), home=H) or ""), folder_check.problem(str(ro / "sub"), home=H))
    os.chmod(ro, 0o700)
finally:
    os.environ["SHIPMIRACLE_TEST"] = save


# ================================================================ D5 input ends (Ctrl-D) / M1 Check order
def wrote_engine_early():
    config._cache.clear()
    return (F.HOME / '.claude' / 'settings.json').exists() or config.get('engine.dir', None) is not None


class EofAfter:
    def __init__(self, n, **kw): self.n, self.prompts = n, []
    def __call__(self, prompt):
        self.prompts.append(prompt)
        if len([p for p in self.prompts if "/5 " in p or "/4 " in p]) > self.n and ("?" in prompt):
            raise EOFError
        return "y" if "[y/N]" in prompt else ""
F.reset()
a = EofAfter(2)
rc, lines = go(a)
txt = "\n".join(lines)
st = stored()
check("D5: input ending in Quick setup pauses the whole run (130, plain sentence, no traceback) and saves nothing half-asked", rc == 130 and "Setup paused. Run shipm init to continue." in txt and "EOFError" not in txt and all(v is None for v in st.values()) and not wrote_engine_early(), (rc, txt[-400:], st))
lines = []
a = EofAfter(2)
onboard.run_prefs(run.Ctx(say=lines.append, ask=a))
st = stored()
check("D5: `--prefs` alone (not inside the run): input ending keeps the answers so far and takes the recommended ones for the rest", "No more input" in "\n".join(lines) and st["prefs.lang"] == "en" and st["prefs.notify"] == "vscode", (lines, st))
F.reset(logins=False)
class EofConnect(Asker):
    def __call__(self, prompt):
        if "Press Enter" in prompt:
            raise EOFError
        return super().__call__(prompt)
rc, lines = go(EofConnect())
txt = "\n".join(lines)
check("D5: input ending at a Connect prompt pauses cleanly: 'Setup paused. Run shipm init to continue.', exit 130, place remembered", rc == 130 and "Setup paused. Run shipm init to continue." in txt and "EOFError" not in txt and run.Ctx().init_state.get("connect_next"), (rc, txt[-400:]))
F.reset(logins=False)
rc, out, err = F.cli("init", env={"SHIPMIRACLE_FAKE_TTY": "1", "SHIPMIRACLE_FAKE_OS": "macos"})
check("D5: a real closed stdin (fake terminal, </dev/null) never ends in a traceback or 'unexpected error'", "Traceback" not in err + out and "EOFError" not in err + out and "unexpected error" not in (err + out).lower() and rc in (0, 1, 130), (rc, err[-300:], out[-300:]))
F.reset(logins=False)
res = json.loads(run.check(as_json=True))
shown = [l.split()[1:3] for l in onboard.render_check(res, run.Ctx(ascii_mode=False))[1:-1]]
titles = [rows.BY_ID[r["id"]]["title"] for r in rows.CONNECT_ROWS]
got = [l for l in onboard.render_check(res, run.Ctx(ascii_mode=False))[1:-1]]
pos = [next(i for i, l in enumerate(got) if t in l) for t in titles]
check("M1: the Check list follows the Connect order (dependencies first), then recommended items", pos == sorted(pos) and len(pos) == len(titles), (pos, got))


# ================================================================ D5b input ends at ANY Connect prompt: pause, apply nothing more (real pty and </dev/null)
import pty, select, signal  # noqa: E402


def pty_run(args, chunks, env_extra=None, timeout=60):
    """Run `bin/shipm ARGS` on a real pseudo-terminal; send each chunk when the output goes quiet (b'\\x04' = Ctrl-D). -> (exit code, output)."""
    env = dict(os.environ); env.pop("CLAUDECODE", None); env.update(env_extra or {}); env["SHIPMIRACLE_FAKE_OS"] = "macos"
    m, sl = pty.openpty()
    p = subprocess.Popen([sys.executable, str(F.ROOT / "bin" / "shipm")] + list(args), stdin=sl, stdout=sl, stderr=sl, env=env, close_fds=True)
    os.close(sl)
    out, chunks, t0 = b"", list(chunks), time.time()
    while p.poll() is None and time.time() - t0 < timeout:
        r, _, _ = select.select([m], [], [], 1.0)
        if r:
            try:
                x = os.read(m, 4096)
            except OSError:
                break
            out += x
        elif chunks:
            c = chunks.pop(0)
            if c == b"SIGINT" and b"1/5" not in out and b"[y/N]" not in out:
                chunks.insert(0, c)                    # wait until Quick setup is on screen
                continue
            if c == b"SIGINT":
                p.send_signal(signal.SIGINT)         # the pty is not this child's controlling terminal, so ^C would not raise it: send the signal itself
            else:
                os.write(m, c)
    try:
        while True:
            r, _, _ = select.select([m], [], [], 0.3)
            if not r:
                break
            x = os.read(m, 4096)
            if not x:
                break
            out += x
    except OSError:
        pass
    rc = p.wait(timeout=10) if p.poll() is not None else None
    os.close(m)
    return rc, out.decode("utf-8", "replace").replace("\r", "")


SETTINGS_F = F.HOME / ".claude" / "settings.json"
def wrote_engine():
    config._cache.clear()
    return SETTINGS_F.exists() or config.get("engine.dir", None) is not None or config.get("hooks.dispatcher", "legacy") != "legacy"


F.reset()
rc, out = pty_run(["init"], [b"\n"] * 5 + [b"\x04"])
check("D5b: pty, Ctrl-D at the first y/N question of Connect: pause message, exit 130, newline printed after the ^D", rc == 130 and "Setup paused. Run shipm init to continue." in out and "not confirmed" not in out, (rc, out[-500:]))
check("D5b: nothing was applied after the Ctrl-D (no hooks in settings.json, no engine.dir / hooks.dispatcher in the config)", not wrote_engine(), out[-300:])
check("D5b: the place is remembered for the next run", run.Ctx().init_state.get("connect_next") == "projects", run.Ctx().init_state)
F.reset()
rc, out = pty_run(["init"], [b"\x04"])
check("D5b: pty, Ctrl-D at the first Quick setup question: paused (130), nothing applied, no choices stored", rc == 130 and "Setup paused" in out and not wrote_engine() and stored()["prefs.lang"] is None and "Saved in" not in out, (rc, out[-400:], stored()))
F.reset(logins=False)
rc, out = pty_run(["init"], [b"\n"] * 5 + [b"\x04"])
check("D5b: pty, Ctrl-D at a 'Press Enter' prompt: paused (130), nothing applied", rc == 130 and "Setup paused" in out and not wrote_engine(), (rc, out[-400:]))
F.reset()
before = F.snapshot(F.HOME, F.CFG)
rc, out, err = F.cli("init", env={"SHIPMIRACLE_FAKE_OS": "macos"})
after = F.snapshot(F.HOME, F.CFG)
check("D5b: no terminal at all and no --yes: nothing that changes settings or config is written (tree diff of home and config is empty)", F.diff(before, after) == [] and not wrote_engine(), F.diff(before, after))
check("D5b: ... and it says which rows were skipped and the one command to run in a terminal", "Not applied" in out and "Engine" in out and "shipm init" in out and rc == 1 and "Traceback" not in err, (rc, out[-500:], err[-200:]))
rc, out, err = F.cli("init", "--yes", env={"SHIPMIRACLE_FAKE_OS": "macos"})
check("D5b: with --yes the same machine IS set up (the explicit flag is the consent)", rc == 0 and wrote_engine(), (rc, out[-300:]))

# ================================================================ D6 folder messages, a bad stored value in --check
long_ = "/" + "a" * 600
rc, out, err = F.cli("init", "--prefs", "--folder", long_)
check("D6: a >512-character folder says 'too long'", rc == 2 and "too long" in err, err)
rc, out, err = F.cli("init", "--prefs", "--folder", "~/x\ny")
check("D6: a folder with a line break says 'no line breaks'", rc == 2 and "line break" in err, err)
F.reset()
F.CFG.mkdir(parents=True, exist_ok=True)
(F.CFG / "config.json").write_text(json.dumps({"paths.projects_dir": "/etc"}))
config._cache.clear()
b = {r["id"]: r for r in json.loads(run.check(as_json=True))["rows"]}
check("D6: `shipm init --check` row 7 shows an invalid stored paths.projects_dir as red with the fix command", b["projects"]["state"] == "red" and "shipm init --prefs --folder" in b["projects"]["detail"], b["projects"])
os.unlink(F.CFG / "config.json"); config._cache.clear()


# ================================================================ D5c `shipm init --prefs` alone, Ctrl-C in Quick setup, resume at connect_next, long details
F.reset()
a = EofAfter(1)
lines = []
ctx = run.Ctx(say=lines.append, ask=a)
rc = onboard.run_all(ctx, prefs_only=True)
st = stored()
check("D5c: run_all(prefs_only) with the input ending at Q2: exit 0, 'No more input', first answer + recommended rest saved (no 'Paused' crash)", rc == 0 and any("No more input" in l for l in lines) and st["prefs.lang"] == "en" and st["prefs.autonomy"] == "normal" and st["prefs.notify"] == "vscode", (rc, lines, st))
F.reset()
rc, out = pty_run(["init", "--prefs"], [b"arabic\n", b"\x04"])
st = stored()
check("D5c: pty `shipm init --prefs`, answer Q1 then Ctrl-D at Q2: exit 0, message, Q1 saved, recommended defaults for the rest", rc == 0 and "No more input" in out and "unexpected error" not in out and st["prefs.lang"] == "ar" and st["prefs.autonomy"] == "normal" and st["prefs.notify"] == "vscode", (rc, out[-400:], st))
F.reset()
rc, out = pty_run(["init", "--prefs"], [b"\x04"])
st = stored()
check("D5c: pty `shipm init --prefs`, Ctrl-D at Q1: exit 0, all recommended answers saved", rc == 0 and "No more input" in out and st["prefs.lang"] == "en" and st["prefs.notify"] == "vscode", (rc, out[-400:], st))
F.reset()
rc, out, err = F.cli("init", "--prefs", env={"SHIPMIRACLE_FAKE_TTY": "1", "SHIPMIRACLE_FAKE_OS": "macos"})
st = stored()
check("D5c: SHIPMIRACLE_FAKE_TTY=1 `shipm init --prefs` </dev/null: exit 0, no crash, newline before the message, recommended answers saved", rc == 0 and "unexpected error" not in out + err and "[English] / Arabic: \n" in out and "No more input" in out and st["prefs.lang"] == "en", (rc, out[-300:], err[-200:]))
F.reset()
rc, out = pty_run(["init"], [b"SIGINT"])
check("D5c: Ctrl-C inside Quick setup: 'Setup paused. Run shipm init to continue.', exit 130, nothing saved", rc == 130 and "Setup paused. Run shipm init to continue." in out and "Traceback" not in out and all(v is None for v in stored().values()), (rc, out[-300:], stored()))

# resume at connect_next
F.reset(logins=False, git_id=False)
class Later(Asker):
    def __call__(self, prompt):
        if "Press Enter" in prompt:
            self.prompts.append(prompt)
            self.n = getattr(self, "n", 0) + 1
            if self.n == 1:
                return "later"
            raise EOFError
        return super().__call__(prompt)
rc, lines = go(Later())
ci = run.Ctx().init_state
check("resume: 'later' on the first row, Ctrl-D on the next: connect_next is the row that was not finished (not the deferred one)", rc == 130 and ci.get("connect_next") == "claude", (rc, ci, lines[-8:]))
a = Asker()
rc, lines = go(a)
first = next(l for l in lines if l.startswith("  1/"))
check("resume: the next run continues at connect_next first ('Continuing at'), then the rest", "Claude Code login" in first and any(l.startswith("Continuing at") for l in lines), (first, lines[:30]))
check("resume: rows still red after a pass keep connect_next on the first of them (not cleared)", run.Ctx().init_state.get("connect_next") == "claude", run.Ctx().init_state)
(F.FAKE / "claude-logged-in").write_text(""); (F.FAKE / "git-name").write_text("T\n"); (F.FAKE / "git-email").write_text("t@e.x\n")
rc, lines = go(Asker())
check("resume: when everything is green connect_next is cleared", rc == 0 and run.Ctx().init_state.get("connect_next") is None, (rc, run.Ctx().init_state))
F.reset()
(F.CFG).mkdir(parents=True, exist_ok=True)
rc, out, err = F.cli("init", env={"SHIPMIRACLE_FAKE_OS": "macos"})
check("resume: no terminal and no --yes: connect_next is the first row that was not applied", run.Ctx().init_state.get("connect_next") == "projects", run.Ctx().init_state)

# long detail
long_detail = "Your saved projects folder cannot be used (" + "x " * 300 + "). Fix it with: shipm init --prefs --folder ~/Developer"
cut = run.cut_detail(long_detail)
check("details: a long text is cut at a word boundary with an ellipsis, within 400 characters, and the fix command stays whole", len(cut) <= 400 and cut.endswith("Fix it with: shipm init --prefs --folder ~/Developer") and "..." in cut and long_detail.startswith(cut.split("...")[0]) and long_detail[len(cut.split("...")[0])] == " ", cut)
check("details: a short text is unchanged; a long text without a fix is cut at a word", run.cut_detail("short") == "short" and len(run.cut_detail("word " * 200)) <= 400 and run.cut_detail("word " * 200).endswith("..."))


# ================================================================ D7 --step with Ctrl-C, cut_detail limits and cleaning, messages
F.reset()
rc, out = pty_run(["init", "--step", "prefs"], [b"SIGINT"])
check("D7: `shipm init --step prefs` + real SIGINT: 'Setup paused', exit 130, no traceback, nothing saved", rc == 130 and "Setup paused. Run shipm init to continue." in out and "Traceback" not in out and all(v is None for v in stored().values()), (rc, out[-300:]))
F.reset()
rc, out = pty_run(["init", "--step", "projects"], [b"SIGINT"])
check("D7: `shipm init --step projects` (waits at its y/N question) + real SIGINT: 130, no traceback, folder not created", rc == 130 and "Traceback" not in out and "Setup paused" in out and not F.DEV.exists(), (rc, out[-300:]))
for lim_in in ("a" * 401, "a" * 2000, "word " * 500, "x" * 400, "x" * 399, "short"):
    c = run.cut_detail(lim_in)
    check("D7: cut_detail(%d chars) is never longer than min(400, input): %d" % (len(lim_in), len(c)), len(c) <= min(400, len(lim_in)), len(c))
for lim in (50, 100, 400):
    check("D7: cut_detail respects a custom limit %d" % lim, all(len(run.cut_detail(t, lim)) <= lim for t in ("a" * 900, "word " * 300 + "Fix it with: shipm init --prefs", "Fix it with: " + "y" * 500)))
t = "word " * 200 + "Fix it with: " + "y" * 350
c = run.cut_detail(t)
check("D7: a 363-character fix sentence that fits in 400 is kept whole; the lead part is shortened", c.endswith("Fix it with: " + "y" * 350) and len(c) <= 400 and "..." in c, c[:80])
dirty = "ok \x1b[31mred\x1b[0m bell\x07 csi\x9b osc\x1b]0;title\x07 done\x1b7 nul\x00 tab\tnl\nend"
c = run.cut_detail(dirty)
check("D7: control and escape characters are stripped from details (C0, C1, CSI, OSC)", all(ord(ch) >= 32 and not 0x7f <= ord(ch) <= 0x9f for ch in c) and "[31m" not in c and "title" not in c and "end" in c, repr(c))
F.reset()
(F.CFG).mkdir(parents=True, exist_ok=True)
(F.CFG / "config.json").write_text(json.dumps({"paths.projects_dir": "/etc/\x1b[31m" + "x" * 600}))
config._cache.clear()
b = {r["id"]: r for r in json.loads(run.check(as_json=True))["rows"]}
check("D7: a hostile stored value never puts escape characters into the Check detail", "\x1b" not in b["projects"]["detail"] and len(b["projects"]["detail"]) <= 400, repr(b["projects"]["detail"][:120]))
os.unlink(F.CFG / "config.json"); config._cache.clear()
for v in ("/", "/etc", "/usr/", "/etc/"):
    rc, out, err = F.cli("init", "--prefs", "--folder", v)
    check("D7: --folder %s says it is a system folder, never 'must start with /'" % v, rc == 2 and "system folder" in err and "must start" not in err and "~/Developer" in err, err)
rc, out, err = F.cli("config", "set", "paths.projects_dir", "/")
check("D7: `shipm config set paths.projects_dir /` says system folder", rc != 0 and "system folder" in err and "must start" not in err, err)
rc, out, err = F.cli("init", "--prefs", "--folder", "/tmp/../etc")
check("D7: a path with '..' says so", rc == 2 and "'..'" in err and "must start" not in err, err)
# 'Continuing at' also when the resume point is the first red row
F.reset(logins=False)
rc, lines = go(Later())
a = Asker()
rc, lines = go(a)
check("D7: 'Continuing at:' is printed when resuming at the first red row too", any(l.startswith("Continuing at: ") for l in lines), lines[:25])

# ================================================================ O9 old panel parser still reads the new JSON
node = shutil.which("node")
F.reset()
rc, out, err = F.cli("init", "--check", "--json", env={"SHIPMIRACLE_FAKE_OS": "macos"})
if node:
    js = "const s=require(%r); const r=s.parseCheck(require('fs').readFileSync(0,'utf8')); console.log(JSON.stringify({ok:r.ok,why:r.why,n:r.rows&&r.rows.length}))" % str(F.ROOT / "vscode-ext" / "shipmiracle-panel" / "setup.js")
    r = subprocess.run([node, "-e", js], input=out, capture_output=True, text=True)
    j = json.loads(r.stdout or "{}")
    check("O9: the panel's current setup.js parser reads the new JSON (ok, all 22 rows)", j.get("ok") is True and j.get("n") == 22, (r.stdout, r.stderr[:200]))
else:
    check("O9: (node not installed: parser check NOT RUN)", True)
old_shape = json.loads(out)
for r_ in old_shape["rows"]:
    for k in ("stage", "class", "os_supported", "docs"):
        r_.pop(k, None)
old_shape.pop("os", None)
check("O9: the JSON minus the new fields is exactly today's shape (v:1, same row keys)", old_shape["v"] == 1 and all(set(r_) == {"n", "id", "title", "need", "state", "detail", "connect", "fix", "undo", "writes"} for r_ in old_shape["rows"]))

# ================================================================ O11 output scan, real files
TOKEN = re.compile(r"gh[pousr]_[A-Za-z0-9]{16,}|github_pat_|sk-[A-Za-z0-9_-]{16,}|xox[abprs]-|eyJ[A-Za-z0-9_-]{10,}\.|AKIA[0-9A-Z]{16}|\b[A-Za-z0-9+/_=-]{40,}\b")
bad = [l for l in ALL_OUT if TOKEN.search(re.sub(r"\S*/\S*", "", l))]      # file paths are long but are not secrets
check("O11: no token-shaped string in anything Check, Quick setup or Connect printed (%d lines)" % len(ALL_OUT), len(ALL_OUT) > 40 and not bad, bad[:3])
check("nothing real was touched (settings.json, agents, LaunchAgents, link, config, state fingerprints equal)", F.real_unchanged())

print("\n%d checks" % n_checks)
print("\nFAILED: %d" % fails if fails else "\nALL PASS")
sys.exit(1 if fails else 0)
