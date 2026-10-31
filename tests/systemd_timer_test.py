#!/usr/bin/env python3
"""Linux / WSL2 daily timer (cross-platform task 7): templates/systemd/*.in rendered by bin/shipm-timer and loaded through shipmiracle.platform.service() (the
SystemdUser class built by the platform task). Fake systemctl through SHIPMIRACLE_SETUP_BIN, SHIPMIRACLE_FAKE_OS / SHIPMIRACLE_FAKE_PROC; never a real systemd.
TODO-checked interface: the test fails loudly if shipmiracle.platform.service() or SystemdUser.load/unload/is_loaded disappear or change their names.
Run: python3 tests/systemd_timer_test.py"""
import os, pathlib, re, shutil, subprocess, sys, tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import shipmiracle_isolation as iso  # noqa: E402
fails = 0


def check(name, ok, info=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(info)[:1200]))
    fails += 0 if ok else 1


tmp = pathlib.Path(tempfile.mkdtemp(prefix="systd-")).resolve()
env, root = iso.isolated_env(root=str(tmp / "iso"))
bindir, proc, log = tmp / "bin", tmp / "proc", tmp / "calls.log"
bindir.mkdir(); (proc / "systemd").mkdir(parents=True)
(bindir / "systemctl").write_text('#!/bin/sh\n# shell builtins only (the seam PATH holds nothing else)\nprintf "%s\\n" "$*" >> "$SHIPMIRACLE_FAKE_LOG"\ncase "$*" in\n  *is-active*) read -r v < "$SHIPMIRACLE_FAKE_DIR/on" 2>/dev/null; [ "$v" = 1 ] && exit 0; exit 3 ;;\n  *disable*) echo 0 > "$SHIPMIRACLE_FAKE_DIR/on"; exit 0 ;;\n  *enable*) echo 1 > "$SHIPMIRACLE_FAKE_DIR/on"; exit 0 ;;\nesac\nexit 0\n')
os.chmod(bindir / "systemctl", 0o755)
(tmp / "fd").mkdir()
env.update(SHIPMIRACLE_SETUP_BIN=str(bindir), SHIPMIRACLE_FAKE_LOG=str(log), SHIPMIRACLE_FAKE_DIR=str(tmp / "fd"), SHIPMIRACLE_FAKE_OS="linux", SHIPMIRACLE_FAKE_PROC=str(proc))
units = pathlib.Path(env["HOME"]) / ".config/systemd/user"
T = ROOT / "bin" / "shipm-timer"


def run(*a, e=None):
    return subprocess.run([sys.executable, str(T), *a], env=e or env, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)


# interface the platform layer must keep (a TODO that fails if the backend API moves)
sys.path.insert(0, str(ROOT))
os.environ.update(env)
from shipmiracle import platform as plat  # noqa: E402
check("interface: shipmiracle.platform.service() and SystemdUser.{available,is_loaded,load,unload} exist", callable(getattr(plat, "service", None))
      and all(callable(getattr(getattr(plat, "SystemdUser", None), m, None)) for m in ("available", "is_loaded", "load", "unload")))
check("interface: on a fake Linux with systemd and systemctl, service().name == systemd", plat.service().name == "systemd", plat.service().name)

# templates
for s in (".service", ".timer"):
    check("template exists: com.shipmiracle.daily%s.in" % s, (ROOT / "templates/systemd" / ("com.shipmiracle.daily%s.in" % s)).is_file())
svc = (ROOT / "templates/systemd/com.shipmiracle.daily.service.in").read_text()
tim = (ROOT / "templates/systemd/com.shipmiracle.daily.timer.in").read_text()
check("service: oneshot, runs bin/daily with bash, NoNewPrivileges, no root/User=", "Type=oneshot" in svc and 'ExecStart=/bin/bash "@WS@/bin/daily"' in svc and "NoNewPrivileges=yes" in svc and "User=" not in svc)
check("timer: 09:00 daily, Persistent, installs into timers.target", "OnCalendar=*-*-* 09:00:00" in tim and "Persistent=true" in tim and "WantedBy=timers.target" in tim)

# render
r = run("render", "--dir", str(tmp / "out"))
svc_txt = (tmp / "out/com.shipmiracle.daily.service").read_text()
check("render writes both units, placeholders replaced", r.returncode == 0 and "@WS@" not in svc_txt and "@STATE@" not in svc_txt and (tmp / "out/com.shipmiracle.daily.timer").exists(), (r.stdout, r.stderr))
check("rendered ExecStart points at this workspace's bin/daily", ('ExecStart=/bin/bash "%s/bin/daily"' % ROOT) in svc_txt, svc_txt)
check("a second render changes nothing", run("render", "--dir", str(tmp / "out")).stdout.strip().endswith("already current)"))
(tmp / "out/com.shipmiracle.daily.timer").write_text("edited\n")
r = run("render", "--dir", str(tmp / "out"))
check("a changed unit file is not overwritten", r.returncode == 1 and "differs" in r.stdout and (tmp / "out/com.shipmiracle.daily.timer").read_text() == "edited\n", (r.stdout, r.stderr))
sys.path.insert(0, str(ROOT / "bin"))
import importlib.machinery, importlib.util  # noqa: E402
ld = importlib.machinery.SourceFileLoader("shipmiracle_timer", str(T)); sp = importlib.util.spec_from_loader("shipmiracle_timer", ld); m = importlib.util.module_from_spec(sp); ld.exec_module(m)
check("escaping: % and $ doubled", m.esc("/a b/100%/$HOME") == "/a b/100%%/$$HOME")
bad = 0
for v in ("/x\ny", '/x"y', "/x\\y"):
    try:
        m.esc(v)
    except ValueError:
        bad += 1
check("escaping: newline, quote and backslash in a path are refused", bad == 3)

# D9 m5: `$` is a systemd variable marker only in Exec* lines; every other line (StandardOutput=, WorkingDirectory=) keeps a single `$`, and `%` is doubled everywhere
from shipmiracle import timer as TM  # noqa: E402
wsx = tmp / "w$x%y"; (wsx / "templates/systemd").mkdir(parents=True)
for _n in ("com.shipmiracle.daily.service", "com.shipmiracle.daily.timer"):
    shutil.copy(ROOT / "templates/systemd" / (_n + ".in"), wsx / "templates/systemd" / (_n + ".in"))
txt = TM.render("com.shipmiracle.daily.service", str(wsx), str(tmp / "st$ate")).decode()
exec_lines = [l for l in txt.splitlines() if l.startswith("ExecStart=")]
out_lines = [l for l in txt.splitlines() if l.startswith("StandardOutput=")]
check("m5: ExecStart doubles $ and %", exec_lines == ['ExecStart=/bin/bash "%s/bin/daily"' % str(wsx).replace("%", "%%").replace("$", "$$")], exec_lines)
check("m5: StandardOutput keeps a single $ (only % doubled)", out_lines == ["StandardOutput=append:%s/v1/logs/systemd-daily.log" % str(tmp / "st$ate").replace("%", "%%")], out_lines)
check("m5: esc() itself still doubles both (Exec-class escaper)", TM.esc("/a$b%c") == "/a$$b%%c" and TM.esc_plain("/a$b%c") == "/a$b%%c")

# D9 m6: a relative XDG_CONFIG_HOME is ignored, and an absolute one outside the home folder is ignored; one below the home folder is honoured (outside tests)
from shipmiracle import paths as _paths  # noqa: E402
_fake_home = tmp / "fakehome"; _fake_home.mkdir(exist_ok=True)
_old = (os.environ.get("SHIPMIRACLE_TEST"), os.environ.get("XDG_CONFIG_HOME"), _paths.home)
try:
    os.environ["SHIPMIRACLE_TEST"] = "0"; _paths.home = lambda: _fake_home
    want_default = _fake_home / ".config/systemd/user"
    for xdg, want, label in (("rel/cfg", want_default, "a relative path"), ("", want_default, "empty"), ("/etc/evil", want_default, "an absolute path outside the home folder"),
                             (str(_fake_home / "../elsewhere"), want_default, "a path that climbs out of the home folder"),
                             (str(_fake_home / "cfg"), _fake_home / "cfg/systemd/user", "an absolute path below the home folder")):
        os.environ["XDG_CONFIG_HOME"] = xdg
        check("m6: XDG_CONFIG_HOME=%r (%s) -> %s" % (xdg, label, want.relative_to(_fake_home)), TM.unit_dir() == want, TM.unit_dir())
    (_fake_home / "cfg").mkdir(exist_ok=True)
    _outside = tmp / "outside-cfg"; _outside.mkdir(exist_ok=True)
    try:
        os.symlink(str(_outside), str(_fake_home / "link"))
    except FileExistsError:
        pass
    os.environ["XDG_CONFIG_HOME"] = str(_fake_home / "link")
    check("m6: a symlink below the home folder that points elsewhere is rejected (real paths are compared)", TM.unit_dir() == want_default, TM.unit_dir())
    os.environ["XDG_CONFIG_HOME"] = str(_fake_home / "link" / "sub")
    check("m6: a path through such a symlink is rejected too", TM.unit_dir() == want_default, TM.unit_dir())
    os.symlink(str(_fake_home / "cfg"), str(_fake_home / "okay")) if not (_fake_home / "okay").exists() else None
    os.environ["XDG_CONFIG_HOME"] = str(_fake_home / "okay")
    check("m6: a symlink that stays below the home folder is honoured", TM.unit_dir() == _fake_home / "okay/systemd/user", TM.unit_dir())
    os.environ.pop("XDG_CONFIG_HOME", None)
    check("m6: no XDG_CONFIG_HOME -> ~/.config/systemd/user", TM.unit_dir() == want_default)
finally:
    _t, _x, _paths.home = _old
    os.environ.pop("SHIPMIRACLE_TEST", None) if _t is None else os.environ.__setitem__("SHIPMIRACLE_TEST", _t)
    os.environ.pop("XDG_CONFIG_HOME", None) if _x is None else os.environ.__setitem__("XDG_CONFIG_HOME", _x)

# install / status / remove through the fake systemctl
r = run("install")
check("install: exit 0, timer enabled", r.returncode == 0 and "enabled" in r.stdout, (r.stdout, r.stderr))
check("install: unit files in ~/.config/systemd/user, mode 0644, state log folder 0700", all((units / ("com.shipmiracle.daily" + s)).is_file() for s in (".service", ".timer"))
      and oct((units / "com.shipmiracle.daily.timer").stat().st_mode & 0o777) == "0o644" and oct((pathlib.Path(env["SHIPMIRACLE_STATE"]) / "v1/logs").stat().st_mode & 0o777) == "0o700")
calls = log.read_text()
check("install: daemon-reload before enable --now, both --user", re.search(r"--user daemon-reload\n--user enable --now com\.shipmiracle\.daily\.timer", calls) is not None, calls)
check("status: loaded", run("status").stdout.strip() == "loaded")
r = run("remove")
check("remove: timer disabled, unit files gone, status not loaded", r.returncode == 0 and not list(units.glob("com.shipmiracle.daily.*")) and run("status").stdout.strip() == "not loaded", (r.stdout, r.stderr))
(units).mkdir(parents=True, exist_ok=True)
(units / "com.shipmiracle.daily.timer").write_text("mine\n")
run("remove")
check("remove: a unit file that is no longer exactly ours is kept", (units / "com.shipmiracle.daily.timer").read_text() == "mine\n")
check("no call was made without --user", all(l.startswith("--user") for l in log.read_text().splitlines()), log.read_text())

# no systemd
shutil.rmtree(units.parent, ignore_errors=True)
for label, over in (("macOS", dict(SHIPMIRACLE_FAKE_OS="macos")), ("Linux without systemd", dict(SHIPMIRACLE_FAKE_PROC=str(tmp / "noproc"))), ("Windows", dict(SHIPMIRACLE_FAKE_OS="windows"))):
    (tmp / "noproc").mkdir(exist_ok=True)
    r = run("install", e=dict(env, **over))
    check("install on %s: exit 3, one line, nothing written" % label, r.returncode == 3 and len(r.stdout.strip().splitlines()) == 1 and not units.exists(), (r.returncode, r.stdout, r.stderr))

# real unit syntax when systemd-analyze exists (Linux CI / container)
sa = shutil.which("systemd-analyze")
if sa:
    r = subprocess.run([sa, "verify", "--user", str(tmp / "out/com.shipmiracle.daily.service")], capture_output=True, text=True)
    print("INFO systemd-analyze verify: exit %d %s" % (r.returncode, (r.stdout + r.stderr).strip()[:300]))
else:
    print("SKIP systemd-analyze not installed (unit syntax not machine-checked here)")
shutil.rmtree(tmp, ignore_errors=True)
print("FAILED %d" % fails if fails else "ALL PASS")
sys.exit(1 if fails else 0)
