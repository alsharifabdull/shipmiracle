#!/usr/bin/env python3
"""Health kinds for change requests (P5 spec section 7): the five declared kinds carry exactly the contract of the spec (mode, severity, chain, verify text,
the exact next-step sentence), only stage_stuck has a button, no OPS were added for them, and the behaviour tests (raise conditions, precedence vs
frozen_chat) live in health_contract_test.py (scenarios stage_stuck ... cr_orphan) which this file checks are present. Run: python3 tests/health_cr_test.py"""
import importlib.machinery, importlib.util, pathlib, re, sys

ws = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_loader("w", importlib.machinery.SourceFileLoader("w", str(ws / "bin/shipm-watch")))
w = importlib.util.module_from_spec(spec); spec.loader.exec_module(w)
fails = 0
def check(name, ok, info=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(info)[:400]))
    fails += 0 if ok else 1

SPEC = {
    "stage_stuck": ("fix", "amber", ["interrupt"], "the CR's stage changed or the chat is no longer working", "Open the chat, press Esc, then ask the lead which step of the CR is stuck and why."),
    "verify_failed_twice": ("wait", "info", [], "", "Open the chat and choose: change the plan, fix it again, or stop the CR (shipm cr abandon in a terminal)."),
    "autopilot_paused": ("wait", "info", [], "", "Open the chat and type next to let the manual autopilot run the following stage."),
    "budget_reached": ("wait", "info", [], "", "Raise the charter budget or go back to guided."),
    "cr_orphan": ("info", "info", [], "", "Open the project's chat from its card and type /feature with no text to resume the CR."),
}
for k, (mode, sev, chain, verify, nxt) in SPEC.items():
    e = w.KINDS.get(k)
    check("%s is declared with the contract of spec section 7" % k, e is not None and (e["mode"], e["sev"], e["chain"], e["verify"], e["next"]) == (mode, sev, chain, verify, nxt), e)
check("stage_stuck is the only CR kind with a fix label and a proof", w.KINDS["stage_stuck"]["fix_label"] and w.KINDS["stage_stuck"]["proof"]
      and not any(w.KINDS[k]["fix_label"] for k in SPEC if k != "stage_stuck"))
check("the wait kinds stay info (the contract forces grey)", all(w.KINDS[k]["sev"] == "info" for k in SPEC if w.KINDS[k]["mode"] in ("wait", "info")))
check("no new OPS were added for the CR kinds", set(w.OPS) >= {"interrupt"} and not any("cr" in o.split("_")[:1] for o in w.OPS), sorted(w.OPS))
ct = (ws / "tests/health_contract_test.py").read_text()
check("health_contract_test.py has a scenario per CR kind and the precedence/silent-case checks", all('@scenario("%s")' % k in ct for k in ("stage_stuck", "verify_failed_twice", "autopilot_paused", "cr_orphan"))
      and "frozen_chat wins" in ct and "none of the six kinds appears" in ct)
check("bin/shipm-watch raises each kind from the read-only CR store (no write call)", all(re.search(r'self\.add\("%s"' % k, (ws / "bin/shipm-watch").read_text()) for k in ("stage_stuck", "verify_failed_twice", "autopilot_paused", "cr_orphan"))
      and "shipmiracle_cr.load(" in (ws / "bin/shipm-watch").read_text() and "shipmiracle_cr.transact" not in (ws / "bin/shipm-watch").read_text() and "shipmiracle_cr.append" not in (ws / "bin/shipm-watch").read_text())
print("\nFAILED: %d" % fails if fails else "\nALL PASS"); sys.exit(1 if fails else 0)
