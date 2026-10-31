#!/usr/bin/env python3
"""A public install has no hooks/*.sh (only hooks/shipm-hook is exported). With an unreadable or missing hooks.dispatcher value the dispatcher must NOT fall back to
the legacy scripts (there are none, so every PreToolUse would be refused): it runs v1, which answers real dangers and lets a harmless call through.
Builds a temp copy of the export shape (shipmiracle/ + hooks/shipm-hook, no hooks/*.sh), runs the shim there. Python 3.9, standard library.
Run: python3 tests/hooks_public_install_test.py"""
import json, os, pathlib, shutil, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import shipmiracle_isolation as ISO  # noqa: E402
ISO.apply_to_environ()

passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    passed, failed = passed + bool(ok), failed + (not ok)
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(detail)[:500]))


import isolation_fixture as X  # noqa: E402  (a world with a project, a second project and a hub; strict isolation)
X.require_temp_home()
W = X.World()
TMP = str(W.T)
ENV = dict(W.env)
ENV.pop("CLAUDECODE", None)
PY = "/usr/bin/python3" if os.path.exists("/usr/bin/python3") else sys.executable
PUB = pathlib.Path(TMP) / "public"
(PUB / "hooks").mkdir(parents=True)
shutil.copytree(str(ROOT / "shipmiracle"), str(PUB / "shipmiracle"), ignore=shutil.ignore_patterns("__pycache__"))
shutil.copy(str(ROOT / "hooks" / "shipm-hook"), str(PUB / "hooks" / "shipm-hook"))
check("the temp export has no hooks/*.sh", not list((PUB / "hooks").glob("*.sh")))
CFG = pathlib.Path(ENV["SHIPMIRACLE_CONFIG"]) / "config.json"


def run(hook, tool, ti):
    d = {"hook_event_name": "PreToolUse", "session_id": "pub1", "cwd": str(W.P), "tool_name": tool, "tool_input": ti}
    e = dict(ENV, CLAUDE_PROJECT_DIR=str(W.P))
    p = subprocess.run([PY, str(hook), "PreToolUse"], input=json.dumps(d).encode(), env=e, cwd=str(W.P), capture_output=True, timeout=60)
    try:
        o = json.loads(p.stdout) if p.stdout.strip() else {}
    except ValueError:
        o = {"raw": p.stdout.decode("utf-8", "replace")}
    return p.returncode, o, p.stderr.decode("utf-8", "replace")


benign = ("Read", {"file_path": str(W.P / "src/mine.py")})
danger = ("Read", {"file_path": str(W.B / ".env")})          # another project's secret file: refused by the isolation rule at strict
for label, raw in (("unreadable config ('{')", "{"), ("no hooks.dispatcher value", "{}"), ("dispatcher set to nonsense", json.dumps({"hooks.dispatcher": 7})), ("dispatcher explicitly legacy", json.dumps({"hooks.dispatcher": "legacy"}))):
    CFG.write_text(raw)
    rc, o, err = run(PUB / "hooks" / "shipm-hook", *benign)
    check("public install, %s: a harmless Read is not refused (rc %s)" % (label, rc), rc == 0 and not X.iso_denied(o) and "deny" not in json.dumps(o), (rc, o, err[:200]))
    rc, o, err = run(PUB / "hooks" / "shipm-hook", *danger)
    check("public install, %s: another project's .env is still refused by v1" % label, X.iso_denied(o) or rc == 2, (rc, o, err[:200]))
CFG.write_text("{")
rc, o, err = run(ROOT / "hooks" / "shipm-hook", *benign)
check("workspace copy (legacy scripts present), unreadable config: harmless Read still allowed", rc == 0 and "deny" not in json.dumps(o), (rc, o))
# the private workspace keeps its default (legacy scripts present)
sys.path.insert(0, str(ROOT))
os.environ.update({k: v for k, v in ENV.items() if k.startswith("SHIPMIRACLE_") or k in ("HOME",)})
CFG.write_text("{")
from shipmiracle.hooks import core  # noqa: E402
core._FILES.clear()

orig_present = core._legacy_scripts_present()
if orig_present:
    check("workspace with the legacy gate script and unreadable config: mode stays legacy", core.mode() == "legacy", core.mode())
else:
    print("SKIP workspace-default check (no legacy gate script in this tree)")
orig = core._legacy_scripts_present
core._legacy_scripts_present = lambda: False
core._FILES.clear()
check("same config without legacy scripts: mode is v1", core.mode() == "v1", core.mode())
CFG.write_text(json.dumps({"hooks.dispatcher": "shadow"}))
core._FILES.clear()
check("shadow without legacy scripts: v1 as well (nothing to shadow)", core.mode() == "v1", core.mode())
core._legacy_scripts_present = orig
W.cleanup()
print("hooks_public_install_test: %d passed, %d failed" % (passed, failed))
sys.exit(1 if failed else 0)
