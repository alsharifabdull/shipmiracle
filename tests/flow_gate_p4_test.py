#!/usr/bin/env python3
"""Phase 4 T8 hardening of the flow gate: the dispatcher shim (hooks/shipm-hook), the dispatcher modules (<WS>/shipmiracle/hooks/**) and the bytecode cache
(<state>/v1/pyc/**) are gate files: writes are refused (main chat and agents), a change mid-session trips the integrity block, harmless commands
still pass, the check costs next to nothing. Plus: no shell=True in shipmiracle/hooks/** and shipmiracle/guard/**.
Runs against the gate chosen by SHIPMIRACLE_GATE_IMPL (legacy default) like every flow suite. Run: python3 tests/flow_gate_p4_test.py"""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import shipmiracle_isolation; shipmiracle_isolation.apply_to_environ()   # test isolation: fresh HOME/SHIPMIRACLE_HOME/CONFIG/STATE unless already temp
import json, os, pathlib, re, subprocess, sys, time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import flow_fixture as F
from flow_fixture import deny, text

ROOT = pathlib.Path(__file__).resolve().parent.parent
fails = []; projects = []
def check(n, c, info=""):
    print(("PASS " if c else "FAIL ") + n + ("" if c else " " + str(info)[:300]))
    if not c: fails.append(n)
def mk(*a, **k):
    p = F.make_project(*a, **k); projects.append(p); return p
FX = json.loads((ROOT / "tests/fixtures/flow/p4-targets.json").read_text())
REFUSAL = "ask the owner to change them"

p = mk(); p.prompt()
sub = lambda t: t.replace("{WS}", str(p.WSF)).replace("{STATE}", str(p.STATE))
targets = [sub(t) for t in FX["protected"]]
for t in targets:
    short = t.replace(str(p.WSF), "<WS>").replace(str(p.STATE), "<STATE>")
    for who, ag in (("main chat", None), ("agent", "backend-engineer")):
        outs = [p.pre("Edit", {"file_path": t, "old_string": "a", "new_string": "b"}, agent=ag), p.pre("Write", {"file_path": t, "content": "x"}, agent=ag),
                p.pre("MultiEdit", {"file_path": t, "edits": [{"old_string": "a", "new_string": "b"}]}, agent=ag),
                p.pre("NotebookEdit", {"notebook_path": t, "new_source": "x", "edit_mode": "insert"}, agent=ag)]
        check(f"p4 tamper: {who} Edit/Write/MultiEdit/NotebookEdit of {short} refused with the plain reason", all(deny(o) and REFUSAL in text(o) for o in outs), outs[0])
    for tpl in FX["bash_writes"]:
        cmd = tpl.replace("{T}", t)
        check(f"p4 tamper: Bash {cmd[:70]} refused (main chat)", deny(p.bash(cmd)), cmd)
    check(f"p4 tamper: Bash write to {short} refused for an agent", deny(p.pre("Bash", {"command": f"echo x > '{t}'"}, agent="backend-engineer")))
ev = p.events()
check("p4 tamper: refusals are logged as gate_tamper (main chat and agent)", any(e["event"] == "gate_tamper" and e.get("agent") == "backend-engineer" for e in ev) and any(e["event"] == "gate_tamper" and not e.get("agent") for e in ev))
check("p4 tamper: no refusal cap (6 in a row)", all(deny(p.pre("Write", {"file_path": targets[0], "content": "x"})) for _ in range(6)))
p.prompt("just do it")
check("p4 tamper: 'just do it' does not lift it", deny(p.pre("Write", {"file_path": targets[1], "content": "x"})))
ET = dict(p.ENV, SHIPMIRACLE_FLOW_TAMPER_OK="1")
check("p4 tamper: the owner-only hook-process variable lets an agent through but never the main chat",
      not deny(p.hook("PreToolUse", env=ET, tool_name="Write", tool_input={"file_path": targets[1], "content": "x"}, agent_id="a", agent_type="backend-engineer"))
      and deny(p.hook("PreToolUse", env=ET, tool_name="Write", tool_input={"file_path": targets[1], "content": "x"})))
check("p4 tamper: warn level still refuses", (p.level("warn") or p.prompt("n") or True) and deny(p.pre("Write", {"file_path": targets[0], "content": "x"})))
p.level("strict"); p.prompt("n")
for tpl in FX["harmless"]:
    cmd = sub(tpl)
    check("p4 harmless: " + cmd[:70] + " is not refused", not deny(p.bash(cmd)), p.bash(cmd))
check("p4 harmless: a lookalike name outside the gate paths is allowed", not deny(p.bash("echo x > /tmp/shipmiracle-hook-notes.txt")) and not deny(p.write("docs/pyc/shipm-hook.md", "x")))
check("p4 harmless: a records edit (docs/STATUS.md) is still allowed", not deny(p.edit("docs/STATUS.md", "a", "b")))
check("p4 tamper: python code writing '$DIR/shipm-hook' (unresolvable base) is refused", deny(p.bash('python3 -c "open(\'$DIR/shipm-hook\',\'w\').write(\'x\')"')), p.bash('python3 -c "open(\'$DIR/shipm-hook\',\'w\').write(\'x\')"'))

# ---- integrity: the files appear in the snapshot (both layouts); a mid-session change blocks main-chat tool calls
def integrity_case(label, layout):
    q = mk(); HM = q.T / "home"; (HM / ".claude").mkdir(parents=True); (HM / ".claude/settings.json").write_text("{}")
    (q.WSF / "hooks").mkdir(); (q.WSF / "hooks/shipm-hook").write_text("#!/bin/bash\nexec true\n"); (q.WSF / "shipmiracle/hooks").mkdir(parents=True)
    (q.WSF / "shipmiracle/hooks/core.py").write_text("x = 1\n"); (q.WSF / "shipmiracle/hooks/flow.py").write_text("y = 1\n")
    envx = dict(q.ENV, HOME=str(HM))
    if layout == "userlevel":
        cfg = q.T / "cfg"; cfg.mkdir(); (cfg / "config.json").write_text(json.dumps({"agents.layout": "userlevel"})); envx["SHIPMIRACLE_CONFIG"] = str(cfg)
    hk = lambda ev_, **kw: q.hook(ev_, env=envx, **kw)
    small = dict(tool_name="Edit", tool_input={"file_path": str(q.P / "docs/STATUS.md"), "old_string": "a", "new_string": "b"})
    hk("UserPromptSubmit", prompt="go")
    base = hk("PreToolUse", **small)
    if deny(base):
        check(f"p4 integrity [{label}]: baseline call passes", False, base); return
    check(f"p4 integrity [{label}]: baseline call passes", True)
    (q.WSF / "hooks/shipm-hook").touch()
    check(f"p4 integrity [{label}]: only the mtime changed -> passes", not deny(hk("PreToolUse", **small)))
    (q.WSF / "hooks/shipm-hook").write_text("#!/bin/bash\nexit 1\n")
    o = hk("PreToolUse", **small)
    check(f"p4 integrity [{label}]: hooks/shipm-hook changed -> blocked, message names it", deny(o) and "shipm-hook" in text(o) and "Tell the owner or revert it" in text(o), o)
    hk("UserPromptSubmit", prompt="ok")
    check(f"p4 integrity [{label}]: the owner's next message re-baselines", not deny(hk("PreToolUse", **small)))
    (q.WSF / "shipmiracle/hooks/core.py").write_text("x = 2\n")
    o = hk("PreToolUse", **small)
    check(f"p4 integrity [{label}]: shipmiracle/hooks/core.py changed -> blocked, names core.py", deny(o) and "core.py" in text(o), o)
    hk("UserPromptSubmit", prompt="ok"); (q.WSF / "shipmiracle/hooks/brand_new.py").write_text("z = 1\n")
    check(f"p4 integrity [{label}]: a new shipmiracle/hooks/*.py is a change", deny(hk("PreToolUse", **small)))
    hk("UserPromptSubmit", prompt="ok"); os.remove(q.WSF / "shipmiracle/hooks/brand_new.py")
    check(f"p4 integrity [{label}]: a deleted module is a change", deny(hk("PreToolUse", **small)))
    hk("UserPromptSubmit", prompt="ok"); (q.WSF / "shipmiracle/hooks/notes.txt").write_text("n"); (q.WSF / "shipmiracle/hooks/.hidden.py").write_text("h")
    (q.WSF / "shipmiracle/hooks/__pycache__").mkdir(); (q.WSF / "shipmiracle/hooks/__pycache__/core.pyc").write_text("c")
    check(f"p4 integrity [{label}]: non-.py files, dotfiles and __pycache__ do not block", not deny(hk("PreToolUse", **small)))
    names = [e for e in q.events() if e["event"] == "gate_tamper_detected"]
    check(f"p4 integrity [{label}]: gate_tamper_detected events carry the changed file names", len(names) >= 3 and any("shipm-hook" in json.dumps(e) for e in names) and any("core.py" in json.dumps(e) for e in names), names)
    check(f"p4 integrity [{label}]: a subagent is not blocked by it", (q.WSF / "shipmiracle/hooks/core.py").write_text("x = 3\n") is not None
          and not deny(hk("PreToolUse", tool_name="Bash", tool_input={"command": "ls"}, agent_id="a", agent_type="backend-engineer")))
integrity_case("legacy", "legacy")
integrity_case("userlevel", "userlevel")

# ---- perf: the added checks cost (nearly) nothing: gate_dirs/gate_files grew by a few entries, the snapshot by a glob
q = mk(); (q.WSF / "shipmiracle/hooks").mkdir(parents=True); (q.WSF / "hooks").mkdir()
for i in range(12): (q.WSF / f"shipmiracle/hooks/m{i}.py").write_text("x = %d\n" % i)
q.prompt()
def timed(fn, n=15):
    xs = []
    for _ in range(n):
        t0 = time.perf_counter(); fn(); xs.append((time.perf_counter() - t0) * 1000)
    xs.sort(); return xs[len(xs) // 2]
ref = timed(lambda: subprocess.run(["/usr/bin/python3", "-I", "-S", "-c", "pass"]))
cost = timed(lambda: q.pre("Bash", {"command": "ls src"}))
check(f"p4 perf: PreToolUse Bash with 12 modules in shipmiracle/hooks stays within max(120 ms, 6 x spawn ref) (median {cost:.0f} ms, ref {ref:.0f} ms)", cost <= max(120, 6 * ref + 60))

# ---- no shell=True in the dispatcher or the guard (static grep; comments and string mentions do not count)
bad = []
for folder in ("shipmiracle/hooks", "shipmiracle/guard"):
    for f in sorted((ROOT / folder).rglob("*.py")):
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("#", 1)[0]
            if re.search(r"shell\s*=\s*True", code) or re.search(r"\bos\.(system|popen)\(", code):
                bad.append(f"{f.relative_to(ROOT)}:{n}")
check("p4 hardening: no shell=True / os.system / os.popen in shipmiracle/hooks/** and shipmiracle/guard/**", not bad, bad)
check("p4 hardening: the scan sees the files (shipmiracle/hooks has modules, shipmiracle/guard exists)", len(list((ROOT / "shipmiracle/hooks").glob("*.py"))) >= 5 and (ROOT / "shipmiracle/guard").is_dir())

for pr in projects: pr.cleanup()
print("\nFAILED: " + ", ".join(fails) if fails else "\nALL PASS")
sys.exit(1 if fails else 0)
