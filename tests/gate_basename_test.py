#!/usr/bin/env python3
"""gate_basename_test: (1) writes through an unresolved folder (variable, substitution, glob) to a gate/state BASENAME are refused at strict, for the main chat and for agents,
in both gate copies; ordinary project paths stay allowed. (2) the compiled-code cache of the legacy shell gate (<state>/v1/pyc): only a regular, own, 0600, non-symlink file holding a code object
is ever run; corrupt / wrong-type / group-writable / symlink caches are ignored (compile instead, no lockout); the cache is written 0600; stale caches are removed.
The cache is NOT a security boundary (same accepted limit as v1/pyc: a same-user writer); the defence is the refusal in (1). Run: python3 tests/gate_basename_test.py"""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import shipmiracle_isolation; shipmiracle_isolation.apply_to_environ()   # test isolation
import json, marshal, os, pathlib, shutil, stat, subprocess, sys, tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import flow_fixture as F
from flow_fixture import deny

fails = []; n_checks = [0]; projects = []


def check(name, ok, info=""):
    n_checks[0] += 1
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(info)[:500]))
    if not ok:
        fails.append(name)


IMPLS = ([("legacy", F.LEGACY_HOOK)] if F.LEGACY_HOOK.exists() else []) + [("v1", F.V1_HOOK)]
tempfile.tempdir = next((d for d in ("/var/tmp", str(pathlib.Path.home() / ".cache")) if os.path.isdir(d) and os.access(d, os.W_OK)), None)


class W:
    def __init__(self, hook):
        self.hook = hook
        self.p = p = F.make_project("proj"); projects.append(p)
        self.home = p.T / "home"; self.home.mkdir(); (p.T / "hooktmp").mkdir()
        p.ENV.update(HOME=str(self.home), SHIPMIRACLE_HOME=str(self.home), SHIPMIRACLE_CONFIG=str(p.T / "cfg"), TMPDIR=str(p.T / "hooktmp"))
        p.level("strict")
        p.prompt("go", "s0")

    def call(self, tool, ti, agent=None):
        d = {"hook_event_name": "PreToolUse", "session_id": "s1", "cwd": str(self.p.P), "tool_name": tool, "tool_input": ti}
        if agent:
            d.update(agent_id="ag1", agent_type=agent)
        r = subprocess.run(["bash", str(self.hook)], input=json.dumps(d), capture_output=True, text=True, env=dict(self.p.ENV), cwd=str(self.p.P))
        try:
            return json.loads(r.stdout) if r.stdout.strip() else {}
        except Exception:
            return {"raw": r.stdout, "err": r.stderr}


ROUTES = [
    "d=$WS/hooks; echo x > $d/flow-gate.sh",
    "d=$S; echo x > $d/flow-gate.0123456789abcdef01234567.code",
    "d=$S/v1/pyc; echo x > $d/x.pyc",
    "d=$S; echo x > $d/flow.s1.json",
    "cp /tmp/a ~/.local/state/shipm*/flow-gate.H.code",
    "d=$(printf %s hooks); echo x > $(pwd)/../$d/flow-gate.sh",
    "d=$X; cp /tmp/a $d/shipm-hook",
    "d=$X; echo x > $d/FLOW-GATE.SH",
    "python3 -c \"import os;open(os.path.expanduser('~')+'/.local/state/shipmiracle/v1/pyc/'+'x'+'/flow-gate.sh','w').write('x')\"",
    "python3 -c \"import os;d=os.environ['W']+'/hooks';open(d+'/flow-gate.sh','w').write('x')\"",
]
for impl, hook in IMPLS:
    w = W(hook)
    for who in (None, "backend-engineer", "qa-engineer"):
        for c in ROUTES:
            check("%s %s refuses: %s" % (impl, who or "main chat", c[:70]), bool(deny(w.call("Bash", {"command": c}, who))), c)
    ok_ = w.call("Bash", {"command": "echo x > src/flow.py"}, "backend-engineer")
    check("%s agent may write a project file named flow.py (literal path)" % impl, not deny(ok_), ok_)
    ok_ = w.call("Bash", {"command": "d=$PWD/src; echo x > $d/app.txt"}, "backend-engineer")
    check("%s agent may write through a variable to an ordinary name" % impl, not deny(ok_), ok_)
    ok_ = w.call("Bash", {"command": "d=$TMPDIR; echo x > /tmp/$$/flow-gate.sh"}, "backend-engineer")
    check("%s a /tmp scratch file with a gate name is not a gate file" % impl, not deny(ok_), ok_)
    ok_ = w.call("Bash", {"command": "d=$X; cat $d/flow-gate.sh"}, None)
    check("%s reading through a variable is not a write" % impl, not deny(ok_), ok_)
    for tool, ti in (("Write", {"file_path": str(w.p.STATE / "v1/pyc/flow-gate.x.code"), "content": "x"}), ("Edit", {"file_path": str(w.p.STATE / "flow.s1.json"), "old_string": "a", "new_string": "b"})):
        for who in (None, "backend-engineer"):
            check("%s %s %s of a state file is refused" % (impl, who or "main chat", tool), bool(deny(w.call(tool, ti, who))))

# ---- cache of the legacy shell gate
if F.LEGACY_HOOK.exists():
    w = W(F.LEGACY_HOOK); p = w.p
    pyc = w.home / ".local/state/shipmiracle/v1/pyc"
    marker = p.T / "PWNED"
    benign = {"command": "ls"}
    w.call("Bash", benign, "backend-engineer")
    files = sorted(pyc.glob("flow-gate.*.code")) if pyc.is_dir() else []
    check("cache: one file after the first call", len(files) == 1, files)
    f = files[0] if files else None
    check("cache: written with mode 0600", bool(f) and stat.S_IMODE(f.stat().st_mode) == 0o600, oct(f.stat().st_mode) if f else "")
    check("cache: holds a code object", bool(f) and type(marshal.loads(f.read_bytes())).__name__ == "code")
    evil = marshal.dumps(compile("open(%r,'w').write('x')" % str(marker), "e", "exec"))

    def restored():
        try:
            return type(marshal.loads(f.read_bytes())).__name__ == "code" and stat.S_IMODE(f.stat().st_mode) == 0o600 and marker.exists() is False
        except Exception:
            return False
    f.write_bytes(evil); os.chmod(f, 0o664)
    w.call("Bash", benign, "backend-engineer")
    check("cache: group-writable planted code is not run, file rewritten 0600", not marker.exists() and restored())
    f.write_bytes(evil); os.chmod(f, 0o604)
    w.call("Bash", benign, "backend-engineer")
    check("cache: world-readable planted code is not run (mode must be 0600)", not marker.exists() and restored())
    f.write_bytes(marshal.dumps({"a": 1})); os.chmod(f, 0o600)
    r = w.call("Bash", benign, "backend-engineer")
    check("cache: a marshalled non-code object is ignored and replaced, no lockout", not deny(r) and restored(), r)
    f.write_bytes(b"\x00garbage"); os.chmod(f, 0o600)
    r = w.call("Bash", benign, "backend-engineer")
    check("cache: corrupt bytes are ignored and replaced, no lockout", not deny(r) and restored(), r)
    real = p.T / "real.code"; real.write_bytes(evil); os.chmod(real, 0o600)
    f.unlink(); os.symlink(str(real), str(f))
    w.call("Bash", benign, "backend-engineer")
    check("cache: a symlink is not followed (planted code not run)", not marker.exists(), "")
    check("cache: the symlink was replaced by a regular file", f.is_file() and not f.is_symlink() and restored())
    stale = pyc / ("flow-gate.%s.code" % ("0" * 24)); stale.write_bytes(b"old"); os.chmod(stale, 0o600)
    f.write_bytes(b"x"); os.chmod(f, 0o600)
    w.call("Bash", benign, "backend-engineer")
    check("cache: stale caches of other sources are removed", not stale.exists() and f.exists())
    check("cache: the gate still works after all that (a gate-file write is refused)", bool(deny(w.call("Bash", {"command": "d=$X; echo x > $d/flow-gate.sh"}, "backend-engineer"))))

for p in projects:
    try:
        p.cleanup()
    except Exception:
        pass
print("\n%d checks, %d failed" % (n_checks[0], len(fails)))
sys.exit(1 if fails else 0)
