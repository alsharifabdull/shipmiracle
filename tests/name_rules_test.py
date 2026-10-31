#!/usr/bin/env python3
"""name_rules_test: the command token `shipm` (rename plan docs/plans/2026-10-21-sm-rename-plan.md section 5). `shipm` is a substring of real words (shipment, shipmate,
midshipman) and of project names (shipm8, ShipManifest, shipment-tracker), so the gate and the autopilot hard stop find it by command position and explicit word
boundaries, never by substring. Every case runs against BOTH gate copies (the legacy shell gate where it exists, and shipmiracle/hooks/flow.py through the
v1 shim) and against shipmiracle/autopilot/hardstop.py. DENIED commands must be refused; ALLOWED commands must pass. Also the SHIPM regex itself, the autopilot diff
scanner rules, and the protected paths (Write): ~/.config/shipmiracle and <project>/.shipmiracle are refused, ~/.config/shipmate and <project>/shipment are not.
Run: python3 tests/name_rules_test.py"""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import shipmiracle_isolation; shipmiracle_isolation.apply_to_environ()   # test isolation
import ast, json, os, pathlib, re, sys, tempfile
from concurrent.futures import ThreadPoolExecutor

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import flow_fixture as F
from flow_fixture import deny, text
from shipmiracle.autopilot import hardstop as H

fails = []


def check(name, ok, info=""):
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(info)[:500]))
    if not ok:
        fails.append(name)


# ------------------------------------------------------------------ the tables (section 5 of the plan)
DENIED = [
    # plain and case variants
    "shipm autopilot start", "SHIPM autopilot start", "Shipm autopilot stop",
    # path-invoked
    "./shipm autopilot start", "~/.local/bin/shipm autopilot checkpoint", "bin/shipm switch autopilot.full.enabled on",
    # quoted and env
    '"shipm" autopilot admit', "env X=1 shipm autopilot start", "env SHIPMIRACLE_TEST=1 shipm status",
    # wrapped in other programs
    "script -q /dev/null shipm autopilot checkpoint",
    "python3 -c \"import subprocess;subprocess.run(['shipm','autopilot','start'])\"",
    "python3 -c \"import subprocess;subprocess.run(['./shipm','autopilot','start'])\"",
    "bash <<EOF\nshipm autopilot resume\nEOF",
    "tmux new 'shipm sync'",
    "osascript -e 'do shell script \"shipm sync\"'",
    # python module
    "python3 -m shipmiracle autopilot start",
    # escaped spelling (decoded by the shell parser first)
    "s\\hipm autopilot start",
]
DENIED2 = [
    # the owner-machine migration is for a terminal (defence in depth; the tool also refuses inside a chat)
    "shipm migrate --apply", "shipm migrate", "bin/shipm migrate --rollback 20261022-100000 --apply",
    "$'\\u017fhipm' sync", "$'\\xc5\\xbfhipm' sync", "$'s\\x68ipm' sync", "$'shipm' sync",
    # a backslash before the name: other interpreters (Tcl/expect, sh, perl, node, awk, python) decode `\s` to `s` inside their own strings (security review F1)
    "expect -c 'spawn \\shipm sync'", "expect -c 'spawn env -i HOME=$HOME \\shipm switch hooks.dispatcher off'",
    "python3 -c 'import os; os.system(\"\\shipm autopilot start\")'", "perl -e 'system(\"\\shipm autopilot start\")'",
    "node -e 'require(\"child_process\").execSync(\"\\shipm autopilot start\")'", "awk 'BEGIN{system(\"\\shipm autopilot start\")}'",
    "ssh -o 'ProxyCommand=shipm autopilot start' localhost",
    # names the APFS file system folds to the real file (U+017F long s -> s) and NFKC look-alikes (fullwidth s): the command word is compared folded (security review F2)
    "\u017fhipm autopilot start", "\u017fhipm sync", "\u017fhipm switch hooks.dispatcher off", "bin/\u017fhipm config set gate.engine legacy", 'bash -c "\u017fhipm sync"',
    "\uff53hipm sync", "\u017fHIPM sync", "./\u017fHIPM autopilot checkpoint", "env X=1 \u017fhipm autopilot start",
    "python3 -c \"import subprocess;subprocess.run(['\u017fhipm','autopilot','start'])\"", "tmux new '\u017fhipm sync'",
]
ALLOWED = [
    # real words
    "shipment status", "shipmate", "echo shipmaster midshipman shipman", "python3 preshipment.py", "git log --grep shipment",
    # look-alike names
    "echo shipm_x", "ls shipm8/ ShipManifest/ shipment-tracker/", "cat ShipMMG.md", "node tools/shipment-tracker autopilot start", 'echo "shipment autopilot start"',
    # ordinary tools
    "tmux ls", "osascript -e 'display notification \"done\" with title \"x\"'",
]
# commands that only the gate treats as allowed (the hard stop refuses launchers such as osascript and tmux in any form, by design)
GATE_ONLY_ALLOWED = {"tmux ls", "osascript -e 'display notification \"done\" with title \"x\"'"}
PATHS_DENIED = ["~/.config/shipmiracle/x", "@P@/.shipmiracle/playbook.json"]
PATHS_ALLOWED = ["~/.config/shipmate/x", "@P@/shipment/.x"]

# ------------------------------------------------------------------ the regex itself, from the gate source
src = F.gate_source()
m = re.search(r'^SHIPM = (r"[^\n]*")$', src, re.M)
check("the gate source defines SHIPM once", m is not None and len(re.findall(r"^SHIPM = ", src, re.M)) == 1)
SHIPM = ast.literal_eval(m.group(1)) if m else r"(?!)"
check("SHIPM is the exact token rule of the plan", SHIPM == r"(?<![\w.\-$@%+:~])(?i:shipm)(?![\w.\-/])", SHIPM)
RX = re.compile(SHIPM)
for s, want in [("shipm", True), ("SHIPM sync", True), ("Shipm", True), ("./shipm sync", True), ("bin/shipm", True), ("~/.local/bin/shipm autopilot", True), ("'shipm',", True),
                ("shipment", False), ("shipmate", False), ("shipmaster", False), ("shipman", False), ("midshipman", False), ("preshipment", False), ("shipm8", False),
                ("shipm_x", False), ("shipm.py", False), ("shipm-watch", False), ("shipm/", False), ("x.shipm", False), ("my-shipm", False), ("$shipm", False),
                ("s\\hipm", False), ("A=shipm", True), ("shipm=1", True), ("a:shipm", False), ("%shipm", False), ("@shipm", False), ("+shipm", False), ("~shipm", False)]:
    check("SHIPM %s %r" % ("finds" if want else "ignores", s), bool(RX.search(s)) == want, s)
# The plan's prose says `${shipm}` is excluded by the lookbehind; its character class has no `{`, so the token IS found there (over-refusal, never under-refusal: a
# command word built from a variable is also caught by unknown_cmd). Documented here, decision for the security review.
check("SHIPM finds '${shipm}' (the plan's class has no brace; the safe direction)", bool(RX.search("${shipm} autopilot start")))
check("the gate source tests the prefilter on the folded text (a superset of SHIPM; U+017F folds to s)", '"shipm" not in tf and "shipm" not in tnf' in src)
check("the unknown-command check is anchored (shipment alone does not make a command unknown)", "(?<![A-Za-z0-9])(?i:shipm)(?![A-Za-z0-9])|shipmiracle|config|agents|registry" in src)

# ------------------------------------------------------------------ both gate copies
p = F.make_project()
p.put("src/a.py", "x\n")
p.prompt()
IMPLS = []
if F.LEGACY_HOOK.exists():
    IMPLS.append(("legacy shell gate", str(F.LEGACY_HOOK)))
IMPLS.append(("v1 gate (shipmiracle/hooks/flow.py)", str(F.V1_HOOK)))
cnt = [0]


def run_cmd(hook, cmd, agent=None):
    cnt[0] += 1
    sid = "n%d" % cnt[0]
    d = {"hook_event_name": "PreToolUse", "session_id": sid, "cwd": str(p.P), "tool_name": "Bash", "tool_input": {"command": cmd}}
    if agent:
        d.update(agent_id="ag1", agent_type=agent)
    import subprocess
    r = subprocess.run(["bash", hook], input=json.dumps(d), capture_output=True, text=True, env=p.ENV, cwd=str(p.P))
    try:
        return json.loads(r.stdout) if r.stdout.strip() else {}
    except Exception:
        return {"raw": r.stdout, "err": r.stderr}


for label, hook in IMPLS:
    with ThreadPoolExecutor(6) as ex:
        den = list(ex.map(lambda c: run_cmd(hook, c), DENIED + DENIED2))
        alw = list(ex.map(lambda c: run_cmd(hook, c), ALLOWED))
    for c, o in zip(DENIED + DENIED2, den):
        check("%s DENIED: %r" % (label, c[:60]), deny(o) and "Traceback" not in text(o), o)
    for c, o in zip(ALLOWED, alw):
        check("%s ALLOWED: %r" % (label, c[:60]), not deny(o), o)
check("hook errors log stays empty", p.errors() == "", p.errors())

# The retired command no longer exists: recorded inputs that use the OLD name get no admin verdict from either gate copy (expected after the rename, listed here).
OLDNAME = "a" + "iw"
LEGACY_INPUTS = [OLDNAME + " autopilot start", "bin/" + OLDNAME + " switch autopilot.full.enabled on", OLDNAME.upper() + " autopilot stop"]
for label, hook in IMPLS:
    for c in LEGACY_INPUTS:
        o = run_cmd(hook, c)
        check("%s: the old command %r gets no admin verdict (it no longer exists)" % (label, c.replace(OLDNAME, "<old>").replace(OLDNAME.upper(), "<OLD>")), not deny(o), o)

# ------------------------------------------------------------------ the autopilot hard stop
WT = pathlib.Path(tempfile.mkdtemp()).resolve() / "dev" / ".worktrees" / "sandbox" / "auto-CR-012"
WT.mkdir(parents=True)
for f in ("shipm8/x", "ShipManifest/x", "shipment-tracker/x", "src/a.py"):
    (WT / f).parent.mkdir(parents=True, exist_ok=True); (WT / f).write_text("x\n")
HOME = os.path.realpath(os.environ["HOME"])


def hs(cmd):
    c = H.Ctx(root=str(WT), base_sha="abc123", scope=["src/**"], tracked=lambda rel: ["src/a.py"], changed=set(), read_text=lambda r: None, added_text=lambda r: None,
              home=HOME, tmp_roots=["/tmp", "/private/tmp"], active_cr="CR-012", ends=["CR-012"], auto_branch="auto/CR-012", ahead=1)
    return H.check("PreToolUse", "Bash", {"command": cmd}, str(WT), c)


H.RAISE = True
for c in DENIED + DENIED2:
    got = hs(c)
    check("hard stop DENIED: %r" % c[:60], bool(got) and (c in DENIED2 or any(s.rule == "H5" for s in got)), [s.rule for s in got])
for c in ALLOWED:
    if c in GATE_ONLY_ALLOWED:
        continue
    got = hs(c)
    check("hard stop ALLOWED: %r" % c[:60], not got, [(s.rule, s.text[:80]) for s in got])
check("hard stop: `shipm admin command` label", any("shipm admin command" in s.text for s in hs("shipm sync")), [s.text[:80] for s in hs("shipm sync")])

# ------------------------------------------------------------------ the autopilot diff scanner (rules.py): our own words are flagged, a project's `shipment` is not
from shipmiracle.autopilot import rules as R
FORB = R.FORBIDDEN
flag = lambda line: [name for name, rx, rule in FORB if rx.search(line)]
for line in ("shipment = load()", "SHIPMENT_ID = 1", "class Shipment: pass", "shipmate = 3", "from shipment import x", "import shipman", "x = shipm8"):
    check("diff scanner does not flag %r" % line, flag(line) == [], flag(line))
for line, want in (("SHIPMIRACLE_TEST = 1", "SHIPMIRACLE_"), ("open('.shipmiracle/work.json')", ".shipmiracle"), ("import shipmiracle", "import shipmiracle"), ("from shipmiracle import cli", "from shipmiracle")):
    check("diff scanner flags %r" % line, want in flag(line), flag(line))

# ------------------------------------------------------------------ protected paths (Write): refused / not refused
home = os.environ["HOME"]
PROT_MARK = ("control the team-flow", "gate", "owner")
for label, hook in IMPLS:
    F.HOOK = type("H", (), {"__str__": lambda s, h=hook: h, "__fspath__": lambda s, h=hook: h})()
    for tmpl in PATHS_DENIED:
        fp = tmpl.replace("~", home).replace("@P@", str(p.P))
        o = p.pre("Write", {"file_path": fp, "content": "x"}, sid="pw1")
        check("%s Write %s is refused" % (label, tmpl), deny(o), o)
    for tmpl in PATHS_ALLOWED:
        fp = tmpl.replace("~", home).replace("@P@", str(p.P))
        o = p.pre("Write", {"file_path": fp, "content": "x"}, sid="pw2")
        why = text(o)
        check("%s Write %s is not refused as a protected name" % (label, tmpl), not deny(o) or "control the team-flow" not in why, o)

p.cleanup()
print("\nFAILED: %d" % len(fails) if fails else "\nALL PASS")
sys.exit(1 if fails else 0)
