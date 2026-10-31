#!/usr/bin/env python3
"""name_protection_test: the ORACLE for the rename (plan docs/plans/2026-10-21-sm-rename-plan.md section 7). A hand-written table of the 11 protected-path rows, NOT derived
from any constant in the code, so a wrong rule applied to the code AND to the other tests is still caught. Per row: the old path (spelled in two pieces here), the new
path(s), and the suites that also deny a write. For every new path: Edit, Write, MultiEdit and NotebookEdit are refused for the main chat and for an agent, and the
shell write forms of tests/fixtures/flow/p4-targets.json (redirect, cp, rm, sed -i) are refused, in BOTH gate copies (legacy shell gate where it exists, and
shipmiracle/hooks/flow.py through the v1 shim). A look-alike folder next to each protected one stays writable. Row 10 (the launchd labels of test-all's fingerprint) and
row 11 (SHIPMIRACLE_* in a chat's admin command) have their own checks.
Run: python3 tests/name_protection_test.py"""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import shipmiracle_isolation; shipmiracle_isolation.apply_to_environ()   # test isolation
import json, os, pathlib, subprocess, sys
from concurrent.futures import ThreadPoolExecutor

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
import flow_fixture as F
from flow_fixture import deny, text

OLD = "a" + "iw"          # the retired name, built in two pieces: this file is listed nowhere in the legacy-name allowlist
fails = []


def check(name, ok, info=""):
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(info)[:500]))
    if not ok:
        fails.append(name)


# Placeholders: ~ = the (temp) home, @WS@ = the engine checkout, @P@ = a project, @CFG@ = ~/.config/shipmiracle, @STATE@ = the state folder the gate runs with
# (SHIPMIRACLE_STATE, a temp folder in tests; ~/.local/state/shipmiracle on the owner's machine).
ROWS = [
    # (row, old path, [new paths], suites that deny a write too)
    (1, "~/.config/%s/**" % OLD, ["@CFG@/x", "@CFG@/config.json", "@CFG@/registry.json"],
     ["flow_gate_roles_test", "gate_deny_test", "shipmiracle_paths_test"]),
    (2, "~/.local/state/%s/*, *.json, *.jsonl" % OLD, ["@STATE@/x", "@STATE@/events.json", "@STATE@/flow-events.jsonl"],
     ["gate_deny_test"]),
    (3, "~/.local/state/%s/v1/**, v1/pyc" % OLD, ["@STATE@/v1/x.json", "@STATE@/v1/pyc/y.pyc"],
     ["flow_gate_p4_test", "settings_sync_test"]),
    (4, "~/.local/share/%s (engine link)" % OLD, ["~/.local/share/shipmiracle/engine/hooks/a.sh", "~/.local/share/shipmiracle/x"],
     ["flow_gate_bash_test"]),
    (5, "<WS>/%s/**, <WS>/%s/hooks/*.py (also a brand-new module)" % (OLD, OLD), ["@WS@/shipmiracle/cli.py", "@WS@/shipmiracle/hooks/core.py", "@WS@/shipmiracle/hooks/brand_new_module.py"],
     ["flow_gate_p4_test", "gate_deny_test"]),
    (6, "<WS>/hooks/%s-hook" % OLD, ["@WS@/hooks/shipm-hook"],
     ["flow_gate_p4_test", "hooks_p4sec_test"]),
    (7, "<WS>/bin/%s-chat" % OLD, ["@WS@/bin/shipm-chat"],
     ["gate_deny_test"]),
    (8, "<P>/.%s/** (playbook.json, work.json, a new file, the folder itself)" % OLD, ["@P@/.shipmiracle/playbook.json", "@P@/.shipmiracle/work.json", "@P@/.shipmiracle/new_file.json", "@P@/.shipmiracle"],
     ["flow_gate_playbook_test", "hardstop_test", "flow_gate_worktree_test"]),
    (9, "<config>/bin/%s-presence, presence.sha256, probes.json, throwaway-account" % OLD, ["@CFG@/bin/shipm-presence", "@CFG@/presence.sha256", "@CFG@/probes.json", "@CFG@/throwaway-account"],
     ["owner_proof_redteam_test", "flow_gate_bash_test", "hardstop_test"]),
]
# look-alikes that must stay writable by the gate's name rules (outside the engine folder, which is protected as a whole) (the message of a protected path is "control the team-flow" / "ask the owner to change them")
LOOKALIKES = ["~/.config/shipmate/x", "@STATE@-old/x", "~/.local/share/shipmate/x", "@P@/shipment/.x",
              "~/.config/shipmiracle-old/x"]
MARK = ("control the team-flow", "ask the owner to change them", "decide who counts", "only you change them")

p = F.make_project()
p.put("src/a.py", "x\n")
p.prompt()
home = os.environ["HOME"]
FX = json.loads((ROOT / "tests/fixtures/flow/p4-targets.json").read_text())
WRITES = FX["bash_writes"] + ["sed -i '' s/a/b/ '{T}'"]
IMPLS = []
if F.LEGACY_HOOK.exists():
    IMPLS.append(("legacy gate", str(F.LEGACY_HOOK)))
IMPLS.append(("v1 gate", str(F.V1_HOOK)))
n = [0]


def sub(t):
    return t.replace("@CFG@", home + "/.config/shipmiracle").replace("@STATE@", str(p.STATE)).replace("@WS@", str(p.WSF)).replace("@P@", str(p.P)).replace("~", home)


def call(hook, tool, ti, agent=None):
    n[0] += 1
    d = {"hook_event_name": "PreToolUse", "session_id": "o%d" % n[0], "cwd": str(p.P), "tool_name": tool, "tool_input": ti}
    if agent:
        d.update(agent_id="ag1", agent_type=agent)
    r = subprocess.run(["bash", hook], input=json.dumps(d), capture_output=True, text=True, env=p.ENV, cwd=str(p.P))
    try:
        return json.loads(r.stdout) if r.stdout.strip() else {}
    except Exception:
        return {"raw": r.stdout, "err": r.stderr}


def edit_forms(t):
    return [("Edit", {"file_path": t, "old_string": "a", "new_string": "b"}), ("Write", {"file_path": t, "content": "x"}),
            ("MultiEdit", {"file_path": t, "edits": [{"old_string": "a", "new_string": "b"}]}), ("NotebookEdit", {"notebook_path": t, "new_source": "x", "edit_mode": "insert"})]


check("the table has the 9 path rows plus the 2 name rows below (11 rows in all)", len(ROWS) == 9)
for row, old, news, suites in ROWS:
    check("row %d: the suites named for it exist (%s)" % (row, ", ".join(suites)), all((ROOT / "tests" / (s + ".py")).exists() or (ROOT / "tests/private" / (s + ".py")).exists() for s in suites), suites)
    for label, hook in IMPLS:
        for newp in news:
            t = sub(newp)
            for who, ag in (("main chat", None), ("agent", "backend-engineer")):
                with ThreadPoolExecutor(4) as ex:
                    outs = list(ex.map(lambda f: call(hook, f[0], f[1], ag), edit_forms(t)))
                check("row %d %s: %s refuses Edit/Write/MultiEdit/NotebookEdit of %s" % (row, label, who, newp), all(deny(o) for o in outs), [text(o)[:150] for o in outs if not deny(o)])
            if not newp.endswith("/.shipmiracle") or True:
                forms = [w.replace("{T}", t) for w in WRITES]
                with ThreadPoolExecutor(4) as ex:
                    outs = list(ex.map(lambda c: call(hook, "Bash", {"command": c}), forms))
                check("row %d %s: the shell write forms to %s are refused" % (row, label, newp), all(deny(o) for o in outs), [c for c, o in zip(forms, outs) if not deny(o)])
# ---- the same protected paths spelled with letters the file system folds to the real ones (security review F2): U+017F long s -> s and U+212A Kelvin sign -> k are the same file on
# APFS, so a write through such a spelling must be refused like the real one. Only the part below the temp root / home is changed.
def folded_variants(path):
    root = str(p.T) if path.startswith(str(p.T)) else home
    head, tail = path[:len(root)], path[len(root):]
    out = []
    if "s" in tail.lower():
        out.append(("long s", head + tail.replace("s", "\u017f").replace("S", "\u017f")))
    if "k" in tail.lower():
        out.append(("Kelvin sign", head + tail.replace("k", "\u212a").replace("K", "\u212a")))
    return out


FOLD_ROWS = [r for r in ROWS if r[0] in (1, 2, 3, 4, 5, 6, 7, 8, 9)]
for row, old, news, suites in FOLD_ROWS:
    for label, hook in IMPLS:
        for newp in news:
            for vname, vpath in folded_variants(sub(newp)):
                outs = [call(hook, tool, ti) for tool, ti in edit_forms(vpath)[:2]]       # Edit and Write of the main chat
                check("row %d %s: %s spelling of %s is refused (Edit, Write)" % (row, label, vname, newp), all(deny(o) for o in outs), [text(o)[:120] for o in outs if not deny(o)])
                forms = [w.replace("{T}", vpath) for w in WRITES[:2]]
                outs = [call(hook, "Bash", {"command": c}) for c in forms]
                check("row %d %s: %s spelling of %s: the shell write forms are refused" % (row, label, vname, newp), all(deny(o) for o in outs), [c[:80] for c, o in zip(forms, outs) if not deny(o)])

for label, hook in IMPLS:
    for look in LOOKALIKES:
        t = sub(look)
        o = call(hook, "Write", {"file_path": t, "content": "x"}, "backend-engineer")
        check("look-alike %s %s is not refused as a protected name" % (label, look), not deny(o) or not any(m in text(o) for m in MARK), o)

# row 10: the launchd labels of test-all's fingerprint of the real machine state
ta = (ROOT / "bin/test-all").read_text()
check("row 10: bin/test-all fingerprints ~/Library/LaunchAgents/com.shipmiracle.* and tests/test_all_test.py exists",
      '"LaunchAgents", "com.shipmiracle.*"' in ta and (ROOT / "tests/test_all_test.py").exists())
check("row 10: the plist templates carry the new label", all((ROOT / "templates/launchd" / ("com.shipmiracle.%s.plist.in" % w)).exists() for w in ("guard", "daily")))

# row 11: SHIPMIRACLE_TEST/CONFIG/STATE/WS/DEV= in a chat's admin command
ENVCMDS = ["SHIPMIRACLE_TEST=1 shipm doctor", "SHIPMIRACLE_CONFIG=/tmp/c shipm status", "env SHIPMIRACLE_STATE=/tmp/s shipm doctor", "SHIPMIRACLE_WS=/tmp/w shipm sync",
           "SHIPMIRACLE_DEV=/tmp/d shipm projects", "export SHIPMIRACLE_STATE=/tmp/s; shipm doctor"]
for label, hook in IMPLS:
    for c in ENVCMDS:
        check("row 11 %s: %r is refused" % (label, c), deny(call(hook, "Bash", {"command": c})), c)

p.cleanup()
print("\nFAILED: %d" % len(fails) if fails else "\nALL PASS")
sys.exit(1 if fails else 0)
