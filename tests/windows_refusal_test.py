#!/usr/bin/env python3
"""Native Windows refusal (cross-platform task 8): the only test that runs on the `windows-latest` CI job. Shipmiracle needs a POSIX system; on native Windows
bin/shipm must print a "use WSL 2" message, exit non-zero, show no traceback and change nothing. On macOS and Linux the same file checks that the guard is in
place (it comes before any Shipmiracle import) and that shipmiracle.platform's refusal text names WSL. Stdlib only, no `pwd`/`fcntl`, so it can run on Windows.
Run: python3 tests/windows_refusal_test.py"""
import os, pathlib, subprocess, sys, tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
fails = 0


def check(name, ok, info=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(info)[:1200]))
    fails += 0 if ok else 1


src = (ROOT / "bin" / "shipm").read_text(encoding="utf-8")
guard, imp = src.find('os.name == "nt"'), src.find("from shipmiracle.cli import")
check("bin/shipm: the native-Windows guard comes before the first Shipmiracle import", 0 <= guard < imp, (guard, imp))
check("bin/shipm: the guard names WSL and exits non-zero", "WSL" in src[guard:imp] and "sys.exit(" in src[guard:imp])

if os.name == "nt":
    home = tempfile.mkdtemp(prefix="shipmiracle-win-")
    env = dict(os.environ, SHIPMIRACLE_TEST="1", SHIPMIRACLE_HOME=home, HOME=home, USERPROFILE=home, SHIPMIRACLE_CONFIG=home + "\\c", SHIPMIRACLE_STATE=home + "\\s",
               SHIPMIRACLE_WS=home + "\\w", SHIPMIRACLE_DEV=home + "\\dev", CLAUDE_CONFIG_DIR=home + "\\.claude")
    r = subprocess.run([sys.executable, str(ROOT / "bin" / "shipm"), "version"], env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)
    out = r.stdout + r.stderr
    check("native Windows: exit non-zero", r.returncode != 0, r.returncode)
    check("native Windows: the message says to use WSL 2", "WSL" in out, out)
    check("native Windows: no traceback", "Traceback" not in out, out)
    check("native Windows: nothing was created in the fake home", os.listdir(home) == [], os.listdir(home))
else:
    sys.path.insert(0, str(ROOT))
    from shipmiracle import platform as plat
    t = plat.refusal_text() if hasattr(plat, "refusal_text") else ""
    check("shipmiracle.platform.refusal_text() tells the user to use WSL 2", "WSL" in t, t)
    print("SKIP native Windows run (this is %s; the real run happens on the windows-latest CI job)" % sys.platform)
print("FAILED %d" % fails if fails else "ALL PASS")
sys.exit(1 if fails else 0)
