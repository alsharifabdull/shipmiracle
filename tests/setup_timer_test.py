#!/usr/bin/env python3
"""`shipm init` row 9 and `shipm uninstall` on Linux / WSL 2 (cross-platform task 7, checklist E7): the daily job as a systemd USER timer. Same sandbox as
setup_init_test.py (temp HOME / state / config / engine, fake tools in SHIPMIRACLE_SETUP_BIN) plus a fake systemctl and SHIPMIRACLE_FAKE_OS / SHIPMIRACLE_FAKE_PROC; never a
real systemd, never root. Covers: unit files + enable recorded in the install manifest (new step type `systemd`), idempotence, uninstall removes only what it owns (a unit
file changed since is kept), forged manifest steps are refused, no systemd = one plain line and nothing written, the macOS branch is untouched (no systemctl call).
Run: python3 tests/setup_timer_test.py"""
import json, os, pathlib, shutil, sys, tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import setup_fixture as F  # noqa: E402
from shipmiracle import timer  # noqa: E402
from shipmiracle.setup import manifest, run, uninstall  # noqa: E402

fails = 0


def check(name, ok, info=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(info)[:600]))
    fails += 0 if ok else 1


PROC = pathlib.Path(tempfile.mkdtemp(prefix="timer-proc-")).resolve()
(PROC / "systemd").mkdir()
NOPROC = PROC.parent / (PROC.name + "-none"); NOPROC.mkdir()
UD = F.HOME / ".config" / "systemd" / "user"
LA = F.HOME / "Library" / "LaunchAgents"


def fresh(os_kind="linux", systemd=True):
    F.reset()
    shutil.copy(F.ROOT / "tests" / "fakes" / "bin" / "systemctl", F.SEAM / "systemctl")
    (F.SEAM / "systemctl").chmod(0o755)
    os.environ["SHIPMIRACLE_FAKE_OS"] = os_kind
    os.environ["SHIPMIRACLE_FAKE_PROC"] = str(PROC if systemd else NOPROC)
    F.make_project("alpha")


def init(yes=True, step=None):
    lines = []
    res = run.apply_rows(run.Ctx(yes=yes, say=lines.append), only=step)
    if yes and step is None:                       # --yes alone no longer applies the OPTIONAL guard row: opt in by name, as a person would
        res = run.apply_rows(run.Ctx(yes=yes, say=lines.append), only="guard")
    return res, lines


def states(res):
    return {r["id"]: r["state"] for r in res["rows"]}


def unins(apply=True):
    lines = []
    rc = uninstall.run(apply=apply, confirm=lambda *_: True, say=lines.append)
    return rc, "\n".join(lines)


def calls():
    return F.fake_calls()


ALL = (F.HOME, F.STATE, F.CFG)

# ------------------------------------------------------------------ 1. Linux with systemd: init writes the units and enables the timer
fresh("linux")
before = F.snapshot(*ALL)
chk = json.loads(run.check(as_json=True))
g = next(r for r in chk["rows"] if r["id"] == "guard")
check("--check on Linux: row 9 is red 'not installed', the connect text is the Linux one, and nothing is written", g["state"] == "red" and "systemd" in g["connect"]["text"] and F.diff(before, F.snapshot(*ALL)) == [], (g, F.diff(before, F.snapshot(*ALL))))
check("--check made no systemctl call that changes anything", all(" enable" not in c and " disable" not in c for c in calls()), calls())
res, _ = init(yes=True)
check("init --yes on Linux: row 9 green", states(res)["guard"] == "green", states(res))
svc, tim = UD / "com.shipmiracle.daily.service", UD / "com.shipmiracle.daily.timer"
check("both unit files exist, mode 0644, rendered from the engine (this temp engine's bin/daily), no placeholder left",
      svc.is_file() and tim.is_file() and oct(svc.stat().st_mode & 0o777) == "0o644" and ('ExecStart=/bin/bash "%s/bin/daily"' % F.WS) in svc.read_text() and "@" not in svc.read_text() + tim.read_text(),
      svc.read_text() if svc.exists() else "no file")
check("the state log folder exists, 0700 (systemd opens the log before bin/daily runs)", oct((F.STATE / "v1" / "logs").stat().st_mode & 0o777) == "0o700")
cs = calls()
check("fake systemctl saw daemon-reload then enable --now, both with --user, and nothing else mutating", "systemctl --user daemon-reload" in cs and "systemctl --user enable --now com.shipmiracle.daily.timer" in cs
      and cs.index("systemctl --user daemon-reload") < cs.index("systemctl --user enable --now com.shipmiracle.daily.timer") and all(c.startswith("systemctl --user") for c in cs if c.startswith("systemctl")), cs)
check("no launchctl call and no LaunchAgents folder on Linux", not any(c.startswith("launchctl") for c in cs) and not LA.exists(), cs)
steps = manifest.load()["steps"]
acts = [(s["action"], os.path.basename(s.get("path") or s.get("key") or "")) for s in steps if s["row"] == 9]
check("manifest: file_write x2 + the new `systemd` step (and the folders it created), none pending", ("file_write", "com.shipmiracle.daily.service") in acts and ("file_write", "com.shipmiracle.daily.timer") in acts
      and ("systemd", "com.shipmiracle.daily.timer") in acts and all(not s.get("pending") for s in steps), acts)
sd = next(s for s in steps if s["action"] == "systemd")
check("the systemd step carries the label and a path (the .timer unit)", sd["label"] == "com.shipmiracle.daily" and sd["path"] == str(tim), sd)

# idempotent
n_steps, n_calls = len(manifest.load()["steps"]), len(calls())
snap = F.snapshot(*ALL)
res2, _ = init(yes=True, step="guard")
check("a second init changes no file and adds no manifest step", F.diff(snap, F.snapshot(*ALL)) == [] and len(manifest.load()["steps"]) == n_steps, F.diff(snap, F.snapshot(*ALL)))
check("a second init makes no enable call", not any("enable" in c for c in calls()[n_calls:]), calls()[n_calls:])

# ------------------------------------------------------------------ 2. uninstall removes only what it owns
rc, out = unins(apply=False)
check("uninstall (dry run) lists the timer steps and changes nothing", rc == 0 and "disable" in out.lower() or "systemd" in out, out)
tim.write_text(tim.read_text() + "# edited by the owner\n")
rc, out = unins(apply=True)
check("uninstall --apply: exit 1 because one step was skipped (the edited unit), the rest was reversed", rc == 1 and "REVERSED" in out, (rc, out))
check("it disabled the timer through the user manager", "systemctl --user disable --now com.shipmiracle.daily.timer" in calls(), calls())
check("the unit file the owner edited is kept; the untouched one is removed", tim.is_file() and not svc.exists(), (tim.exists(), svc.exists(), out))
check("the report says the edited file was left as it is", "changed since init" in out or "left" in out, out)

# a clean round trip leaves the tree as it was
fresh("linux")
snap0 = F.snapshot(F.HOME)
init(yes=True)
rc, out = unins(apply=True)
after = F.snapshot(F.HOME)
extra = [k for k in F.diff(snap0, after) if "/.config/systemd" in k or "Library" in k]
check("init then uninstall --apply: the systemd folders and units are gone again, no LaunchAgents", rc == 0 and not UD.exists() and extra == [], (rc, extra, out))
check("a second uninstall has nothing to do", unins(apply=True)[0] == 0)

# ------------------------------------------------------------------ 3. forged manifest steps are refused
fresh("linux")
init(yes=True)
good = manifest.load()
evil_file = {"id": 900, "row": 9, "action": "file_write", "path": str(F.HOME / ".bashrc"), "before": None, "before_sha256": None, "after_sha256": "x", "backup": None, "mode": None, "ts": 1, "pending": False}
evil_sd = {"id": 901, "row": 9, "action": "systemd", "path": str(tim), "label": "evil.service", "before": False, "before_sha256": None, "after_sha256": "x", "backup": None, "mode": None, "ts": 1, "pending": False}
evil_sd2 = {"id": 902, "row": 9, "action": "systemd", "path": str(F.HOME / ".config/systemd/user/other.timer"), "label": timer.LABEL, "before": False, "before_sha256": None, "after_sha256": "x", "backup": None, "mode": None, "ts": 1, "pending": False}
ok1, why1 = uninstall.validate(evil_file)
ok2, why2 = uninstall.validate(evil_sd)
ok3, why3 = uninstall.validate(evil_sd2)
ok4, _ = uninstall.validate(next(s for s in good["steps"] if s["action"] == "systemd"))
check("validate: a file_write outside the init files, a systemd step with another label or another unit are refused; the real step is accepted", not ok1 and not ok2 and not ok3 and ok4, (why1, why2, why3))

# ------------------------------------------------------------------ 4. no systemd: one plain line, nothing written
for label, kind, sysd in (("Linux without systemd", "linux", False), ("WSL 2 without systemd", "wsl", False)):
    fresh(kind, systemd=sysd)
    snap = F.snapshot(*ALL)
    res, lines = init(yes=True)
    check("%s: row 9 stays red with a plain sentence, no unit file, no enable call" % label, states(res)["guard"] == "red" and not UD.exists() and not any("enable" in c for c in calls()), (states(res)["guard"], lines))
    text = " ".join(lines) + " " + next(r for r in res["rows"] if r["id"] == "guard")["detail"]
    check("%s: the sentence mentions systemd and the by-hand fallback" % label, "systemd" in text and "shipm daily" in text, text)

# ------------------------------------------------------------------ 5. WSL 2 with systemd behaves like Linux
fresh("wsl")
res, _ = init(yes=True)
check("WSL 2 with systemd: row 9 green, units written", states(res)["guard"] == "green" and (UD / "com.shipmiracle.daily.timer").is_file(), states(res))

# ------------------------------------------------------------------ 6. an existing, different unit file is never replaced
fresh("linux")
UD.mkdir(parents=True)
(UD / "com.shipmiracle.daily.timer").write_text("mine\n")
res, lines = init(yes=True)
check("a different unit file already there: not replaced, the row says why, no enable call", (UD / "com.shipmiracle.daily.timer").read_text() == "mine\n" and not any("enable" in c for c in calls()), lines)

# ------------------------------------------------------------------ 7. a path that systemd cannot hold safely is refused (unit-file injection)
fresh("linux")
bad_ws = F.WS.parent / 'ws"x'
try:
    timer.render("com.shipmiracle.daily.service", bad_ws)
    refused = False
except ValueError:
    refused = True
check("render refuses a quote in the engine path", refused)
pw = F.WS.parent / "100%ws"; (pw / "templates").mkdir(parents=True); shutil.copytree(F.ROOT / "templates" / "systemd", pw / "templates" / "systemd")
pct = timer.render("com.shipmiracle.daily.service", pw).decode()
check("a percent sign is doubled for systemd", "100%%ws" in pct, pct)

# ------------------------------------------------------------------ 8. macOS branch untouched: launchd, no systemctl
fresh("macos")
res, _ = init(yes=True)
check("macOS: row 9 green through launchd; no systemctl call, no systemd folder", states(res)["guard"] == "green" and not any(c.startswith("systemctl") for c in calls()) and not UD.exists() and LA.exists(), calls())
check("the real account's files were not touched", F.real_unchanged())

shutil.rmtree(PROC, ignore_errors=True); shutil.rmtree(NOPROC, ignore_errors=True)
print("\nFAILED: %d" % fails if fails else "\nALL PASS")
sys.exit(1 if fails else 0)
