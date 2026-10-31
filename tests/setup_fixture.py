"""Shared helpers for tests/setup_init_test.py and tests/setup_uninstall_test.py (not a test itself: the runner glob only takes *_test.py).
Builds a temp HOME / STATE / CONFIG / Developer folder, a temp engine checkout, and a seam folder SHIPMIRACLE_SETUP_BIN holding the fake tools from
tests/fakes/bin. Importing it sets SHIPMIRACLE_TEST=1 and the temp overrides BEFORE any Shipmiracle module is imported."""
import hashlib, json, os, pathlib, shutil, subprocess, sys, tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = pathlib.Path(tempfile.mkdtemp(prefix="shipmiracle-setup-")).resolve()
HOME, DEV, WS, STATE, CFG, SEAM, FAKE = (TMP / n for n in ("home", "home/Developer", "ws", "state", "cfg", "seam", "fake"))
LOG = TMP / "fake.log"
os.environ.update(SHIPMIRACLE_TEST="1", SHIPMIRACLE_HOME=str(HOME), SHIPMIRACLE_STATE=str(STATE), SHIPMIRACLE_CONFIG=str(CFG), SHIPMIRACLE_DEV=str(DEV), SHIPMIRACLE_WS=str(WS),
                  SHIPMIRACLE_SETUP_BIN=str(SEAM), SHIPMIRACLE_FAKE_DIR=str(FAKE), SHIPMIRACLE_FAKE_LOG=str(LOG), HOME=str(TMP / "gh"))
import shipmiracle_isolation  # noqa: E402  (tests/ is on sys.path when a suite imports this file)
shipmiracle_isolation.mac_platform_off_mac("the setup suites check the launchd/macOS branch; the Linux timer has its own suite (setup_timer_test)")
for k in ("CLAUDECODE", "SHIPMIRACLE_ENFORCE_OWNER", "SHIPMIRACLE_DEBUG"):
    os.environ.pop(k, None)
(TMP / "gh").mkdir(parents=True, exist_ok=True)

from shipmiracle import config  # noqa: E402

FAKE_TOOLS = ("claude", "gh", "code", "git", "brew", "node", "xcode-select", "launchctl", "tmutil", "xcodebuild", "docker", "scutil", "id", "gitleaks")

STUB_EXT = """#!/usr/bin/env python3
# test stub for bin/install-shipm-ext: logs, then installs through the (fake) code on PATH
import subprocess, sys
subprocess.run(["code", "--install-extension", "shipmiracle.shipmiracle-panel"])
"""


def make_engine():
    """A temp engine checkout: the masters, the launchd templates, a bin/shipm to link to, a stub bin/install-shipm-ext."""
    if WS.exists():
        shutil.rmtree(WS)
    shutil.copytree(ROOT / "agents" / "claude", WS / "agents" / "claude")
    shutil.copytree(ROOT / "templates" / "launchd", WS / "templates" / "launchd")
    shutil.copytree(ROOT / "templates" / "systemd", WS / "templates" / "systemd")
    (WS / "hooks").mkdir()
    shutil.copy(ROOT / "hooks" / "shipm-hook", WS / "hooks" / "shipm-hook")      # row 0 starts the REGISTERED dispatcher for real (--selftest): it needs the script and the Shipmiracle package
    (WS / "hooks" / "shipm-hook").chmod(0o755)
    os.symlink(str(ROOT / "shipmiracle"), str(WS / "shipmiracle"))
    (WS / "bin").mkdir()
    (WS / "bin" / "shipm").write_text("#!/bin/sh\n")
    (WS / "bin" / "install-shipm-ext").write_text(STUB_EXT)
    (WS / "bin" / "shipm-guard-admin").write_text("#!/bin/sh\n")
    for f in (WS / "bin").iterdir():
        f.chmod(0o755)


def reset(with_fakes=True, logins=True, git_id=True):
    """Fresh account: empty home / state / config / Developer; fakes installed (or not); logins present (or not)."""
    for d in (HOME, STATE, CFG, SEAM, FAKE):
        if d.exists():
            shutil.rmtree(d)
    HOME.mkdir(parents=True); SEAM.mkdir(); FAKE.mkdir()
    if LOG.exists():
        LOG.unlink()
    make_engine()
    if with_fakes:
        for t in FAKE_TOOLS:
            shutil.copy(ROOT / "tests" / "fakes" / "bin" / t, SEAM / t)
            (SEAM / t).chmod(0o755)
    if logins:
        for n in ("claude-logged-in", "gh-logged-in"):
            (FAKE / n).write_text("")
    if git_id:
        (FAKE / "git-name").write_text("Test User\n"); (FAKE / "git-email").write_text("test@example.com\n")
    config._cache.clear()


def fake_calls():
    return LOG.read_text().splitlines() if LOG.exists() else []


def make_project(name):
    d = DEV / name
    d.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(d)], check=True)
    subprocess.run(["git", "-C", str(d), "remote", "add", "origin", "https://github.com/tester/%s.git" % name], check=True)
    return d


def snapshot(*roots):
    """{relative-ish path: kind+sha} of every file, folder and symlink under the roots (the roots themselves are keyed too)."""
    out = {}
    for r in roots:
        r = pathlib.Path(r)
        if not os.path.lexists(str(r)):
            out[str(r)] = "absent"
            continue
        for dp, dns, fns in os.walk(str(r)):
            for n in dns + fns:
                p = os.path.join(dp, n)
                if os.path.islink(p):
                    out[p] = "link:" + os.readlink(p)
                elif os.path.isdir(p):
                    out[p] = "dir"
                else:
                    out[p] = hashlib.sha256(open(p, "rb").read()).hexdigest()
    return out


def diff(a, b):
    return sorted(set(k for k in set(a) | set(b) if a.get(k) != b.get(k)))


def cli(*args, env=None):
    e = dict(os.environ)
    e.pop("CLAUDECODE", None); e.pop("SHIPMIRACLE_ENFORCE_OWNER", None)
    e.update(env or {})
    r = subprocess.run([sys.executable, str(ROOT / "bin" / "shipm")] + list(args), env=e, stdin=subprocess.DEVNULL, capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


# ---- the real-file guard: nothing here may touch the account's real files -------------------------
def _real_fp():
    h = pathlib.Path(__import__("pwd").getpwuid(os.getuid()).pw_dir)
    out = {}

    def fsha(p):
        try:
            return hashlib.sha256(open(p, "rb").read()).hexdigest()
        except OSError:
            return "absent"
    out["settings.json"] = fsha(h / ".claude" / "settings.json")
    ad = h / ".claude" / "agents"
    out["agents"] = sorted((n, fsha(ad / n)) for n in os.listdir(ad)) if ad.is_dir() else "absent"
    la = h / "Library" / "LaunchAgents"
    out["launchagents"] = sorted((n, fsha(la / n)) for n in os.listdir(la) if n.startswith("com.shipmiracle.")) if la.is_dir() else "absent"
    lk = h / ".local" / "bin" / "shipm"
    out["shipmiracle-link"] = ("link:" + os.readlink(lk)) if os.path.islink(lk) else ("file:" + fsha(lk) if lk.exists() else "absent")
    out["config"] = [fsha(h / ".config" / "shipmiracle" / n) for n in ("config.json", "registry.json")]
    sv = h / ".local" / "state" / "shipmiracle" / "v1"
    out["state"] = [(n, os.path.exists(sv / n)) for n in ("install-manifest.json", "init.json", "install-backups")]
    return out


REAL_BEFORE = _real_fp()


def real_unchanged():
    return _real_fp() == REAL_BEFORE
