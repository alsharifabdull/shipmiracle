"""macOS notifications are off by default and only appear when config/notifications.json says {"mac": true}. A recorder stands in for osascript. Run: python3 tests/notifications_test.py"""
import importlib.machinery, importlib.util, json, os, pathlib, re, stat, sys, tempfile
ws = pathlib.Path(__file__).resolve().parent.parent
T = pathlib.Path(tempfile.mkdtemp()); W = T / "ws"; (W / "config").mkdir(parents=True); STATE = T / "state"; STATE.mkdir()
rec = T / "osascript"; log = T / "calls.log"
rec.write_text(f"#!/bin/sh\necho \"$@\" >> {log}\n"); rec.chmod(rec.stat().st_mode | stat.S_IXUSR)
os.environ.update(SHIPMIRACLE_WS=str(W), SHIPMIRACLE_STATE=str(STATE), SHIPMIRACLE_OSASCRIPT=str(rec))
os.environ.pop("SHIPMIRACLE_GUARD_FAKE", None)
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent)); import shipmiracle_isolation; shipmiracle_isolation.mac_platform_off_mac("the notification test drives the osascript recorder")
os.environ["SHIPMIRACLE_TEST"] = "1"          # SHIPMIRACLE_OSASCRIPT (the recorder) counts only under SHIPMIRACLE_TEST=1; without the recorder a test never reaches the real osascript
def load(name):
    spec = importlib.util.spec_from_loader(name, importlib.machinery.SourceFileLoader(name, str(ws / "bin" / name))); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
guard = load("shipm-guard")
fails = []
def check(n, c, info=""):
    print(("PASS " if c else "FAIL ") + n, "" if c else info)
    if not c: fails.append(n)
def calls(): return log.read_text().count("\n") if log.exists() else 0
def fire():
    guard.notify("Shipmiracle", "battery 14%")
for label, cfg in (("no config file", None), ("mac:false", {"mac": False})):
    log.unlink(missing_ok=True)
    if cfg is not None: (W / "config/notifications.json").write_text(json.dumps(cfg))
    fire(); check(f"{label}: guard sends no notification", calls() == 0, log.read_text() if log.exists() else "")
(W / "config/notifications.json").write_text('{"mac": true}'); log.unlink(missing_ok=True); fire()
check("mac:true: guard sends one notification, the text passed as an argument", calls() == 1 and "battery 14%" in log.read_text(), log.read_text() if log.exists() else "")
real = json.loads((ws / "config/notifications.json").read_text()); check("the shipped setting is off", real == {"mac": False}, str(real))
d = (ws / "bin/daily").read_text(); check("daily's health pop-up goes through shipmiracle.platform (prefs.notify, else the old switch); no raw osascript call is left", "python3 -m shipmiracle.platform notify" in d and "osascript" not in d.split("# notify-begin")[1].split("# notify-end")[0].replace("never splice", ""), d[d.index("# notify-begin"):][:300])
del os.environ["SHIPMIRACLE_OSASCRIPT"]; log.unlink(missing_ok=True); fire()
check("without SHIPMIRACLE_OSASCRIPT a test run never reaches the real osascript", calls() == 0)
os.environ["SHIPMIRACLE_OSASCRIPT"] = str(rec); os.environ.pop("SHIPMIRACLE_TEST"); log.unlink(missing_ok=True); fire()
check("outside SHIPMIRACLE_TEST=1 the SHIPMIRACLE_OSASCRIPT variable is ignored (a stray variable cannot redirect the pop-up)", calls() == 0)
print("\nFAILED:" if fails else "\nALL PASS", fails); sys.exit(1 if fails else 0)
