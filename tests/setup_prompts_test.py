#!/usr/bin/env python3
"""Which `shipm init` operations ASK a question in the terminal, pinned from the code so the panel's wording can never drift from the CLI.
The VS Code panel runs Setup Fix / Skip / Undo / Quick setup with Enter (owner decision 31 Oct 2026, option A) and tells the owner either
"answer its prompt in the terminal" or "this change is applied at once". That is only honest if:
  * `--step ID` asks a question exactly for the rows listed in extension.js SETUP_PROMPT_ROWS (read here from the source), and
  * `--skip`, `--undo` and `--prefs` (all choices given as flags) never ask anything.
Read-only: the code is parsed (ast), nothing is written, nothing is run except two calls with a stand-in terminal in the isolated temp home.
Run: python3 tests/setup_prompts_test.py"""
import ast, pathlib, re, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import setup_fixture as F  # noqa: E402,F401  (isolated HOME / state / config)
from shipmiracle.setup import onboard, rows, run  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
fails = 0


def check(name, ok, info=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(info)[:600]))
    fails += 0 if ok else 1


ASKS = {"confirm", "confirm_word", "confirm_adopt", "input"}                 # the Ctx methods that put a question to the owner


def funcs(path):
    tree = ast.parse(pathlib.Path(path).read_text(encoding="utf-8"))
    return {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}


def asks_directly(fn):
    return any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in ASKS for n in ast.walk(fn))


def calls(fn):
    return {n.func.id for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}


def asks(name, table, seen=()):
    """True when function `name` of rows.py asks, directly or through another function of the same file (apply_guard -> apply_timer)."""
    fn = table.get(name)
    if fn is None or name in seen:
        return False
    return asks_directly(fn) or any(asks(c, table, seen + (name,)) for c in calls(fn))


RF = funcs(ROOT / "shipmiracle" / "setup" / "rows.py")
prompting_rows = sorted(r["id"] for r in rows.ROWS if r["apply"] is not None and asks(r["apply"].__name__, RF))
EXPECT_STEP_PROMPTS = ["ask-inbox", "github", "guard", "projects", "remote-control", "vscode"]
check("--step asks a question (confirm / typed word) for exactly these rows: " + ", ".join(EXPECT_STEP_PROMPTS), prompting_rows == EXPECT_STEP_PROMPTS, prompting_rows)
quiet_rows = sorted(r["id"] for r in rows.ROWS if r["apply"] is not None and not asks(r["apply"].__name__, RF))
check("the rows with an apply step but no question in rows.py are exactly: engine, registry (applied at once) and prefs (apply_prefs delegates to onboard.run_prefs, which asks: checked below); every other row has no apply step (`--step` only shows its hint)", quiet_rows == ["engine", "prefs", "registry"], quiet_rows)
check("the prefs row (`--step prefs`) asks the five choices: onboard.run_prefs reads ctx.input", asks_directly(funcs(ROOT / "shipmiracle" / "setup" / "onboard.py")["run_prefs"]))

RN = funcs(ROOT / "shipmiracle" / "setup" / "run.py")
check("`--skip` never asks (run.skip has no confirm / input call)", not asks_directly(RN["skip"]))
check("`--undo` never asks (run.undo has no confirm / input call)", not asks_directly(RN["undo"]))

# the panel's list must be the same list (extension.js is the only place that words the notice)
src = (ROOT / "vscode-ext" / "shipmiracle-panel" / "extension.js").read_text(encoding="utf-8")
m = re.search(r"const SETUP_PROMPT_ROWS = \[([^\]]*)\]", src)
panel = sorted(re.findall(r"'([a-z-]+)'", m.group(1))) if m else None
check("extension.js SETUP_PROMPT_ROWS = the rows above plus prefs (so a row that starts to ask, or stops asking, fails this test until the wording is fixed)", panel == sorted(EXPECT_STEP_PROMPTS + ["prefs"]), panel)


# ---- behaviour with a stand-in terminal: skip / undo / --prefs with every flag never put a question
class Asker:
    def __init__(self):
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        return ""


try:
    a = Asker(); lines = []
    ctx = run.Ctx(yes=False, say=lines.append, ask=a)
    run.skip("docker", ctx)
    check("run.skip('docker') with a terminal that could answer asks nothing", a.prompts == [], a.prompts)
    run.undo("docker", ctx)
    check("run.undo('docker') asks nothing", a.prompts == [], a.prompts)
    given = {"prefs.lang": "en", "paths.projects_dir": "~/Developer", "prefs.autonomy": "normal", "prefs.keep_awake": True, "prefs.notify": "vscode"}
    a2 = Asker(); ctx2 = run.Ctx(yes=False, say=lines.append, ask=a2)
    onboard.run_prefs(ctx2, interactive=True, given=given)
    check("onboard.run_prefs with every choice given as a flag asks nothing (`shipm init --prefs --lang ... --notify ...`)", a2.prompts == [], a2.prompts)
except Exception as e:  # a failure to run is a failure of the test, never a silent pass
    check("behaviour part ran", False, repr(e))

print("\nFAILED: %d" % fails if fails else "\nALL PASS")
sys.exit(1 if fails else 0)
