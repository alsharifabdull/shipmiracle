#!/usr/bin/env python3
"""Phase 5 T4: gate invariants for the playbook engine, in BOTH gate copies (SHIPMIRACLE_GATE_IMPL picks one like every flow suite).
<project>/.shipmiracle/** is a gate path (Edit/Write/Bash/removal refused for the main chat and agents, no cap, not liftable by "just do it"); the owner-only
subcommands `shipm playbook set|init|accept` and `shipm cr abandon|advance` count as admin commands; .shipmiracle/ and docs/reports/ are never "outside the team"
or agent credit; the integrity snapshot watches .shipmiracle/playbook.json and the gate.engine switch. Run: python3 tests/flow_gate_playbook_test.py"""
import json, os, pathlib, sys
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
FX = json.loads((ROOT / "tests/fixtures/flow/p5-shipmiracle-targets.json").read_text())
REFUSAL = "ask the owner to change them"

p = mk(); (p.P / ".shipmiracle").mkdir(); (p.P / ".shipmiracle/playbook.json").write_text('{"v":1}'); p.prompt()
targets = [t.replace("{P}", str(p.P)) for t in FX["protected"]]
for t in targets:
    short = t.replace(str(p.P), "<P>")
    for who, ag in (("main chat", None), ("agent", "backend-engineer")):
        outs = [p.pre("Edit", {"file_path": t, "old_string": "a", "new_string": "b"}, agent=ag), p.pre("Write", {"file_path": t, "content": "x"}, agent=ag),
                p.pre("MultiEdit", {"file_path": t, "edits": [{"old_string": "a", "new_string": "b"}]}, agent=ag)]
        check(f"p5 tamper: {who} Edit/Write/MultiEdit of {short} refused", all(deny(o) and REFUSAL in text(o) for o in outs), outs[0])
    for tpl in FX["bash_writes"]:
        cmd = tpl.replace("{T}", t)
        check(f"p5 tamper: Bash {cmd[:70]} refused", deny(p.bash(cmd)), cmd)
    check(f"p5 tamper: Bash write to {short} refused for an agent", deny(p.pre("Bash", {"command": f"echo x > '{t}'"}, agent="backend-engineer")))
check("p5 tamper: relative path .shipmiracle/playbook.json refused", deny(p.write(".shipmiracle/playbook.json", "x")) and deny(p.bash("echo x > .shipmiracle/work.json")))
check("p5 tamper: refusals logged as gate_tamper", any(e["event"] == "gate_tamper" for e in p.events()))
check("p5 tamper: no refusal cap (6 in a row)", all(deny(p.pre("Write", {"file_path": targets[0], "content": "x"})) for _ in range(6)))
p.prompt("just do it")
check("p5 tamper: 'just do it' does not lift it", deny(p.pre("Write", {"file_path": targets[0], "content": "x"})))
p.level("warn"); p.prompt("n")
check("p5 tamper: warn level still refuses", deny(p.pre("Write", {"file_path": targets[0], "content": "x"})))
p.level("strict"); p.prompt("n")
for tpl in FX["harmless"]:
    cmd = tpl.replace("{P}", str(p.P))
    check("p5 harmless: " + cmd[:70] + " is not refused", not deny(p.bash(cmd)), p.bash(cmd))
check("p5 harmless: a lookalike (docs/shipmiracle.md, /tmp/shipmiraclex.txt) is allowed", not deny(p.write("docs/shipmiracle.md", "x")) and not deny(p.bash("echo x > /tmp/shipmiraclex.txt")))
check("p5 harmless: a records edit (docs/STATUS.md) is still allowed", not deny(p.edit("docs/STATUS.md", "a", "b")))
q = mk(); q.prompt()   # no .shipmiracle folder at all: creating it is refused too
check("p5 tamper: creating .shipmiracle/playbook.json in a project without .shipmiracle is refused", deny(q.write(".shipmiracle/playbook.json", "{}")) and deny(q.bash("mkdir -p .shipmiracle && echo x > .shipmiracle/playbook.json")))

# ---- admin subcommands: refused for the model whatever the spelling, other cr/playbook subcommands pass
a = mk(); a.prompt()
for cmd in FX["admin_denied"]:
    check("p5 admin: refused: " + cmd[:70], deny(a.bash(cmd)) and deny(a.pre("Bash", {"command": cmd}, agent="backend-engineer")), a.bash(cmd))
for cmd in FX["admin_allowed"]:
    check("p5 admin: allowed: " + cmd[:70], not deny(a.bash(cmd)), a.bash(cmd))

# ---- outside-team / agent credit exclusion
o = mk(); o.prompt(); o.put(".shipmiracle/work.json", "{}"); o.put("docs/reports/CR-001.md", "r\n")
check("p5 outside: engine-written .shipmiracle/ and docs/reports/ files do not block Stop", not deny(o.stop()), o.stop())
check("p5 outside: they are not listed in state.outside", not any(f.startswith((".shipmiracle/", "docs/reports/")) for f in o.state().get("outside", [])), o.state().get("outside"))
o.put("src/gen.py", "z\n")
out = o.stop()
check("p5 outside: a real outside file in the same project still blocks and only it is named", deny(out) and "src/gen.py" in text(out) and ".shipmiracle" not in text(out) and "docs/reports" not in text(out), out)
c = mk(); c.prompt(); c.put(".shipmiracle/work.json", "{}"); c.put("docs/reports/CR-002.md", "r\n"); c.put("src/made.py", "m\n")
c.sub_stop("backend-engineer")
ed = c.state().get("agent_edits", [])
check("p5 credit: a build-role stop credits src/made.py but not .shipmiracle/ or docs/reports/", "src/made.py" in ed and not any(f.startswith((".shipmiracle/", "docs/reports/")) for f in ed), ed)
b = mk(); b.prompt(); b.pre("Edit", {"file_path": str(b.P / "docs/reports/x.md"), "old_string": "a", "new_string": "b"}, agent="backend-engineer")
b.post("Edit", {"file_path": str(b.P / "docs/reports/x.md")}, agent="backend-engineer")
check("p5 credit: an agent PostToolUse Edit of docs/reports/x.md is not agent credit", "docs/reports/x.md" not in b.state().get("agent_edits", []), b.state().get("agent_edits"))

# ---- integrity: .shipmiracle/playbook.json digest and the gate.engine switch
def integrity_case(label, engine_mode):
    q = mk(); HM = q.T / "home"; (HM / ".claude").mkdir(parents=True); (HM / ".claude/settings.json").write_text("{}")
    (q.P / ".shipmiracle").mkdir(); (q.P / ".shipmiracle/playbook.json").write_text('{"v":1,"level":"strict"}')
    envx = dict(q.ENV, HOME=str(HM)); cfg = q.T / "cfg"; cfg.mkdir(); envx["SHIPMIRACLE_CONFIG"] = str(cfg)
    if engine_mode == "file":
        (cfg / "config.json").write_text(json.dumps({"gate.engine": "legacy"}))
    hk = lambda ev_, **kw: q.hook(ev_, env=envx, **kw)
    small = dict(tool_name="Edit", tool_input={"file_path": str(q.P / "docs/STATUS.md"), "old_string": "a", "new_string": "b"})
    hk("UserPromptSubmit", prompt="go")
    check(f"p5 integrity [{label}]: baseline call passes", not deny(hk("PreToolUse", **small)))
    (q.P / ".shipmiracle/playbook.json").write_text('{"v":1,"level":"strict"}')
    check(f"p5 integrity [{label}]: same content rewritten -> passes", not deny(hk("PreToolUse", **small)))
    (q.P / ".shipmiracle/playbook.json").write_text('{"v":1,"level":"off"}')
    o_ = hk("PreToolUse", **small)
    check(f"p5 integrity [{label}]: playbook.json changed mid-turn -> blocked, names it", deny(o_) and "playbook.json" in text(o_) and "Tell the owner or revert it" in text(o_), o_)
    check(f"p5 integrity [{label}]: gate_tamper_detected logged", any(e["event"] == "gate_tamper_detected" and "playbook.json" in json.dumps(e) for e in q.events()))
    hk("UserPromptSubmit", prompt="ok")
    check(f"p5 integrity [{label}]: the owner's next message re-baselines", not deny(hk("PreToolUse", **small)))
    os.remove(q.P / ".shipmiracle/playbook.json")
    check(f"p5 integrity [{label}]: deleting playbook.json is a change", deny(hk("PreToolUse", **small)))
    hk("UserPromptSubmit", prompt="ok")
    # the engine switch
    if engine_mode == "file":
        (cfg / "config.json").write_text(json.dumps({"gate.engine": "playbook"}))
    else:
        envx["SHIPMIRACLE_GATE_ENGINE"] = "playbook"
    o_ = hk("PreToolUse", **small)
    check(f"p5 integrity [{label}]: gate.engine switched mid-turn -> blocked, names gate.engine", deny(o_) and "gate.engine" in text(o_), o_)
    hk("UserPromptSubmit", prompt="ok")
    check(f"p5 integrity [{label}]: re-baselined after the owner spoke", not deny(hk("PreToolUse", **small)))
    if engine_mode == "file":
        (cfg / "config.json").write_text("{not json")
        check(f"p5 integrity [{label}]: a broken config.json is a change", deny(hk("PreToolUse", **small)))
    ag_ = deny(hk("PreToolUse", tool_name="Bash", tool_input={"command": "ls"}, agent_id="a", agent_type="backend-engineer"))   # P6 T3: agents see layout/registry/gate.engine changes
    check(f"p5 integrity [{label}]: a subagent is blocked only by a gate.engine change (broken config.json), not by playbook/settings churn", ag_ == (engine_mode == "file"))
integrity_case("config file", "file")
integrity_case("env (SHIPMIRACLE_TEST)", "env")
n = mk(); n.prompt()
check("p5 integrity: no .shipmiracle folder and no config -> no false positive on ordinary calls", not deny(n.edit("docs/STATUS.md", "a", "b")) and not deny(n.bash("ls")))

for pr in projects: pr.cleanup()
print("\nFAILED: " + ", ".join(fails) if fails else "\nALL PASS")
sys.exit(1 if fails else 0)
