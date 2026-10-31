#!/usr/bin/env python3
"""Review remediation A: `shipm rollback PHASE` (M3), the value switches (tokens.nudge, guard.jobs, agents.maxTurns, prefix.trim, reporter.model),
`shipm project hooks-global` (M4), `shipm hooks shadow-report --stage` (M5), the legacy-hook-scripts refusal (m7), and the scorecard's switch note.
Everything runs as real subprocesses in a fully temp sandbox (SHIPMIRACLE_TEST=1, fresh config/state/ws/dev/home folders); no real file is read or written.
Run: python3 tests/rollback_hooksglobal_test.py"""
import copy, importlib.machinery, importlib.util, json, os, pathlib, shutil, stat, subprocess, sys, tempfile, time

ROOT = pathlib.Path(__file__).resolve().parent.parent
if not (ROOT / "docs" / "baseline" / "switches.json").is_file():
    print("SKIP-ALL docs/baseline/switches.json (the rollback switch table) is not shipped in the public tree"); sys.exit(0)
TMP = pathlib.Path(tempfile.mkdtemp(prefix="shipmiracle-rbk-")).resolve()
HOME, DEV, STATE, CONF, WS = (TMP / n for n in ("home", "dev", "state", "config", "ws"))
for d in (HOME / ".claude", DEV, STATE, CONF, WS / "docs" / "baseline", WS / "hooks"):
    d.mkdir(parents=True, exist_ok=True)
shutil.copy(ROOT / "docs" / "baseline" / "switches.json", WS / "docs" / "baseline" / "switches.json")
ENV = dict(os.environ, SHIPMIRACLE_TEST="1", SHIPMIRACLE_HOME=str(HOME), SHIPMIRACLE_DEV=str(DEV), SHIPMIRACLE_STATE=str(STATE), SHIPMIRACLE_CONFIG=str(CONF), SHIPMIRACLE_WS=str(WS), HOME=str(HOME))
for k in ("SHIPMIRACLE_DEBUG", "CLAUDECODE", "SHIPMIRACLE_ENFORCE_OWNER", "SHIPMIRACLE_ENFORCE_LEGACY_HOOKS"):
    ENV.pop(k, None)
os.environ.update({k: v for k, v in ENV.items() if k.startswith("SHIPMIRACLE_") or k == "HOME"})
for k in ("CLAUDECODE", "SHIPMIRACLE_ENFORCE_OWNER", "SHIPMIRACLE_ENFORCE_LEGACY_HOOKS"):
    os.environ.pop(k, None)
sys.path.insert(0, str(ROOT))
from shipmiracle import cli, config, events, settings_sync as ss  # noqa: E402
from shipmiracle.hooks import shadow  # noqa: E402

fails = 0
def check(name, ok, info=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(info)[:700]))
    fails += 0 if ok else 1

def shipm(*args, env=None, inp=""):
    r = subprocess.run([sys.executable, str(ROOT / "bin" / "shipm")] + list(args), env=env or ENV, capture_output=True, text=True, timeout=90, input=inp)
    return r.returncode, r.stdout, r.stderr

def cfg():
    p = CONF / "config.json"
    return json.loads(p.read_text()) if p.exists() else {}

TABLE = json.loads((ROOT / "docs" / "baseline" / "switches.json").read_text())

# ---------------------------------------------------------------- the switch table and the value switches
check("every switch of the table (but panel.v3, built in P7) is a config key `shipm switch` knows", all(cli._switch_now(n) is not None for ph in TABLE["phases"].values() for n in ph if n != "panel.v3"),
      [n for ph in TABLE["phases"].values() for n in ph if cli._switch_now(n) is None])
check("every switch of the table has a legacy value", all(n in TABLE["legacy"] for ph in TABLE["phases"].values() for n in ph))
check("P5 names gate.engine and reporter.model, both real keys", TABLE["phases"]["P5"] == ["gate.engine", "reporter.model"] and "gate.engine" in config.SCHEMA and "reporter.model" in config.SCHEMA)
for name, first, setv, then in (("tokens.nudge", "off", "on", "on"), ("guard.jobs", "off", "on", "on"), ("agents.maxTurns", "on", "off", "off"), ("prefix.trim", "on", "off", "off"),
                                ("reporter.model", "haiku", "sonnet", "sonnet")):
    c0, o0, e0 = shipm("switch", name)
    c1, o1, e1 = shipm("switch", name, setv)
    c2, o2, _ = shipm("switch", name)
    check("shipm switch %s: shows %s, sets %s, shows %s" % (name, first, setv, then), (c0, o0.strip(), c1, c2, o2.strip()) == (0, first, 0, 0, then) and "%s %s" % (name, setv) in o1, (o0, e0, o1, e1, o2))
for name, bad in (("tokens.nudge", "maybe"), ("reporter.model", "gpt"), ("agents.maxTurns", "5")):
    c, o, e = shipm("switch", name, bad)
    check("shipm switch %s %s: usage error 2, value unchanged" % (name, bad), c == 2 and e.startswith("shipm: "), (c, e))
check("shipm switch hooks.record shows on/off now (was true/false)", shipm("switch", "hooks.record")[1].strip() == "off")
(CONF / "config.json").unlink()

# ---------------------------------------------------------------- shipm rollback
c, o, e = shipm("rollback", "P1")
check("rollback P1 dry run: lists the three switches newest first, changes nothing", c == 0 and "dry run" in o and o.index("prefix.trim") < o.index("agents.maxTurns") < o.index("tokens.nudge")
      and not (CONF / "config.json").exists(), (c, o, e))
c, o, e = shipm("rollback", "p1", "--json")
j = json.loads(o)
check("rollback --json: v1, phase upper-cased, rows with now/back/action, manual notes", c == 0 and j["v"] == 1 and j["phase"] == "P1" and [r["switch"] for r in j["switches"]] == ["prefix.trim", "agents.maxTurns", "tokens.nudge"]
      and j["switches"][0]["back"] == "off" and j["switches"][0]["action"] == "change" and j["switches"][2]["action"] == "keep" and j["manual"] and j["applied"] == [], o)
c, o, e = shipm("rollback", "P9")
check("rollback unknown phase: exit 2 and the known phases are named", c == 2 and "P4" in e and e.startswith("shipm: "), (c, e))
c, o, e = shipm("rollback", "P7")
check("rollback P7: panel.v3 is reported as not available (no config key yet), exit 0", c == 0 and "panel.v3" in o and "not available" in o, (c, o))
c, o, e = shipm("rollback", "P1", "--apply", inp="no\n")
check("rollback --apply without the typed yes: exit 2, nothing changed", c == 2 and "not confirmed" in e and not (CONF / "config.json").exists(), (c, e))
c, o, e = shipm("rollback", "P1", "--apply", inp="")
check("rollback --apply with no input (closed stdin): refused, nothing changed", c == 2 and not (CONF / "config.json").exists(), (c, e))
c, o, e = shipm("rollback", "P1", "--apply", inp="yes\n")
check("rollback P1 --apply + yes: prefix.trim and agents.maxTurns go off, tokens.nudge was already off; undo lines printed", c == 0 and cfg().get("prefix.trim") is False and cfg().get("agents.maxTurns") is False
      and "undo: shipm switch prefix.trim on" in o and "undo: shipm switch agents.maxTurns on" in o and "tokens.nudge" in o and "(already)" in o, (c, o, e, cfg()))
c, o, e = shipm("rollback", "P1", "--apply", inp="yes\n")
check("rollback P1 again: nothing to change, no prompt needed, exit 0", c == 0 and "set " not in o and "type yes" not in e, (c, o, e))
# P4 + P5 + P6
for k, v in (("hooks.dispatcher", "v1"), ("guard.jobs", "on"), ("gate.engine", "playbook"), ("reporter.model", "sonnet"), ("autopilot.full.enabled", "on")):
    assert shipm("switch", k, v)[0] == 0, k
c, o, e = shipm("rollback", "P4")
check("rollback P4 dry run: hooks.dispatcher v1 -> legacy first, guard.jobs on -> off; warns that gate.engine is playbook; names `shipm sync --hooks legacy`", c == 0 and o.index("hooks.dispatcher") < o.index("guard.jobs")
      and "v1 -> legacy" in o and "on -> off" in o and "roll back P5" in o and "shipm sync --hooks legacy" in o, o)
c, o, e = shipm("rollback", "P5", "--apply", inp="yes\n")
check("rollback P5 --apply: reporter.model off, gate.engine legacy", c == 0 and cfg().get("reporter.model") == "off" and cfg().get("gate.engine") == "legacy", (c, o, e, cfg()))
c, o, e = shipm("rollback", "P6", "--apply", inp="yes\n")
check("rollback P6 --apply: autopilot.full.enabled off", c == 0 and cfg().get("autopilot.full.enabled") is False, (c, o, e))
c, o, e = shipm("rollback", "P4", "--apply", inp="yes\n")
check("rollback P4 --apply: dispatcher legacy, guard.jobs off", c == 0 and cfg().get("hooks.dispatcher") == "legacy" and cfg().get("guard.jobs") is False, (c, o, e, cfg()))
# a failing step stops the run and says what was done before it
shipm("switch", "hooks.dispatcher", "v1"); shipm("switch", "guard.jobs", "on")
env2 = dict(ENV, SHIPMIRACLE_ENFORCE_LEGACY_HOOKS="1")
c, o, e = shipm("rollback", "P4", "--apply", env=env2, inp="yes\n")
check("m7 rollback P4 on an install without the legacy scripts: hooks.dispatcher is refused (exit 4), nothing was changed before it", c == 4 and "legacy hook scripts" in e and cfg().get("hooks.dispatcher") == "v1" and cfg().get("guard.jobs") is True, (c, e, cfg()))
# m7 on the other entry points
c, o, e = shipm("switch", "hooks.dispatcher", "legacy", env=env2)
check("m7 shipm switch hooks.dispatcher legacy without scripts: exit 2, value unchanged", c == 2 and "v1" in e and cfg().get("hooks.dispatcher") == "v1", (c, e))
c, o, e = shipm("switch", "hooks.dispatcher", "shadow", env=env2)
check("m7 ... shadow too", c == 2 and cfg().get("hooks.dispatcher") == "v1", (c, e))
c, o, e = shipm("sync", "--hooks", "legacy", "--dry-run", env=env2)
check("m7 shipm sync --hooks legacy without scripts: exit 2 and no settings file written", c == 2 and "legacy hook scripts" in e and not (HOME / ".claude" / "settings.json").exists(), (c, e))
c, o, e = shipm("sync", "--legacy-hooks", "--dry-run", env=env2)
check("m7 shipm sync --legacy-hooks: same", c == 2, (c, e))
c, o, e = shipm("sync", "--hooks", "v1", "--dry-run", env=env2)
check("m7 shipm sync --hooks v1 needs no scripts", c == 0, (c, o, e))
c, o, e = shipm("sync", "--hooks", "off", "--dry-run", env=env2)
check("m7 shipm sync --hooks off needs no scripts", c == 0, (c, o, e))
# owner only
env3 = dict(ENV, CLAUDECODE="1", SHIPMIRACLE_ENFORCE_OWNER="1")
c, o, e = shipm("rollback", "P1", "--apply", env=env3, inp="yes\n")
check("rollback --apply inside a chat (CLAUDECODE, owner check on): refused with exit 4 and no change", c == 4 and "terminal" in e, (c, e))
shipm("switch", "prefix.trim", "on")
c, o, e = shipm("rollback", "P1", env=env3)
check("rollback dry run is allowed inside a chat", c == 0 and "dry run" in o, (c, e))
(CONF / "config.json").unlink()

# ---------------------------------------------------------------- scorecard note
ld = importlib.machinery.SourceFileLoader("shipmiracle_scorecard_mod", str(ROOT / "bin" / "shipm-scorecard"))
S = importlib.util.module_from_spec(importlib.util.spec_from_loader(ld.name, ld)); ld.exec_module(S)
red = [{"id": "Q1", "kind": "weekly watch", "status": "FLAG"}]
sw = {"merged": ["P4"], "phases": TABLE["phases"], "legacy": TABLE["legacy"]}
T0, WK = 1_760_000_000, 7 * 86400
n2 = S.update_state(S.update_state({}, red, T0, sw), red, T0 + WK, sw)["switch_note"]
check("scorecard note for a value switch says the legacy value (hooks.dispatcher legacy), not 'off'", "shipm switch hooks.dispatcher legacy" in n2, n2)
sw2 = {"merged": ["P2"], "phases": TABLE["phases"], "legacy": TABLE["legacy"]}
check("scorecard note for a plain switch says off", "shipm switch state.v1 off" in S.update_state(S.update_state({}, red, T0, sw2), red, T0 + WK, sw2)["switch_note"])
sw3 = {"merged": ["P2"], "phases": TABLE["phases"]}
check("scorecard note without a legacy table still says off (older switches.json)", "shipm switch state.v1 off" in S.update_state(S.update_state({}, red, T0, sw3), red, T0 + WK, sw3)["switch_note"])

# ---------------------------------------------------------------- shadow-report --stage
for k, proj, cr, st in (("cr_needs_plan", "aaaaaaaaaaaa", "CR-001", "Do"), ("cr_needs_plan", "aaaaaaaaaaaa", "CR-002", "Do"), ("cr_continue", "bbbbbbbbbbbb", "CR-009", "Verify")):
    events.emit("stage.shadow", {"kind": k, "cr": cr, "stage": st}, project=proj, src="hooks")
events.emit("hook_shadow", {"event": "Stop", "agree": True}, src="hooks")
c, o, e = shipm("hooks", "shadow-report", "--stage", "--json")
j = json.loads(o)
check("shadow-report --stage --json: counts per kind, project and stage", c == 0 and j["v"] == 1 and j["events"] == 3 and j["by_kind"] == {"cr_needs_plan": 2, "cr_continue": 1}
      and j["by_project"] == {"aaaaaaaaaaaa": 2, "bbbbbbbbbbbb": 1} and j["by_stage"] == {"Do": 2, "Verify": 1}, o)
check("... details carry only the sha prefix of the CR id, never its text", len(j["details"]) == 3 and all(len(d["cr_sha"]) == 8 for d in j["details"]) and "CR-00" not in o, o)
c, o, e = shipm("hooks", "shadow-report", "--stage")
check("shadow-report --stage (text): header, by_kind lines, exit 0 even though there are would-refusals", c == 0 and "stage.shadow events" in o and "by_kind cr_needs_plan: 2" in o, o)
c, o, e = shipm("hooks", "shadow-report", "--stage", "--since", "bogus")
check("shadow-report --stage bad window: exit 2", c == 2, (c, e))
check("shadow-report without --stage still reads hook_shadow events", json.loads(shipm("hooks", "shadow-report", "--json")[1])["events"] == 1)
evs = events.tail(100)
check("aggregate_stage: the window excludes older events", shadow.aggregate_stage(evs, time.time() + 100)["events"] == 0)
many = [{"ts": 5, "kind": "stage.shadow", "project": "p" * 12, "data": {"kind": "k%d" % i, "cr": "CR-%03d" % i, "stage": "Do"}} for i in range(30)]
check("aggregate_stage: at most 20 details, all 30 counted; junk rows ignored", len(shadow.aggregate_stage(many + [{"kind": "stage.shadow", "data": 5}, "x", {"kind": "other"}])["details"]) == 20
      and shadow.aggregate_stage(many)["events"] == 30)

# ---------------------------------------------------------------- hooks-global: the pure planner
TEMPLATE = json.loads((ROOT / "templates" / "base" / ".claude" / "settings.json").read_text())
FULL = ss.dispatcher_events({"hooks": {ev: [{"hooks": [{"command": ss.spec.dispatcher_command(ss.spec.hooks_prefix(WS, HOME)[0], e2, w, HOME)}]} for e2, _m, w in ss.spec.V1 if e2 == ev] for ev in {x[0] for x in ss.spec.V1}}}, WS, HOME)
ALL = {("UserPromptSubmit", False), ("PreToolUse", False), ("PostToolUse", False), ("Stop", False), ("Stop", True), ("SessionStart", False), ("Notification", False), ("PreModelSwitch", False)}
def cmds(s):
    return [h["command"] for g in sum(s.get("hooks", {}).values(), []) for h in g["hooks"]]
new, removed, kept = ss.plan_project_hooks_global(TEMPLATE, ALL)
check("spec.V1 itself now covers every event of the six template scripts (all six move, nothing kept)", FULL >= ALL and ss.plan_project_hooks_global(TEMPLATE, FULL)[2] == [], FULL)
check("planner, everything covered: the six template scripts go, format.sh stays, the model line stays", [c for c in cmds(new)] == ["$CLAUDE_PROJECT_DIR/.claude/hooks/format.sh"] and new["model"] == "opusplan"
      and len(removed) == 9 and kept == [], (cmds(new), removed, kept))
check("... the input was not modified", cmds(TEMPLATE).count("$CLAUDE_PROJECT_DIR/.claude/hooks/block-secrets.sh") == 1 and len(cmds(TEMPLATE)) == 10)
V1G = {}
for _ev, _m, _w in ss.spec.V1[:8]:           # the first eight registrations = the spec before SessionStart/Notification/PreModelSwitch joined (a public install on an older registration)
    V1G.setdefault(_ev, []).append({"matcher": _m, "hooks": [{"command": ss.spec.dispatcher_command(ss.spec.hooks_prefix(WS, HOME)[0], _ev, _w, HOME)}]} if _m else
                                   {"hooks": [{"command": ss.spec.dispatcher_command(ss.spec.hooks_prefix(WS, HOME)[0], _ev, _w, HOME)}]})
ONLY_V1 = ss.dispatcher_events({"hooks": V1G}, WS, HOME)
new, removed, kept = ss.plan_project_hooks_global(TEMPLATE, ONLY_V1)
check("planner, only the first eight V1 registrations (pre-extension): block-secrets, stop-gate and save-plan go; session-start, shipm-state and model-switch stay with the reason",
      sorted(c.split("/")[-1] for _e, c in removed) == ["block-secrets.sh", "save-plan.sh", "stop-gate.sh"] and sorted(k[0] for k in kept) == ["model-switch.sh", "session-start.sh", "shipm-state.sh"]
      and any("SessionStart" in k[1] for k in kept) and any("Notification" in k[1] for k in kept) and any("PreModelSwitch" in k[1] for k in kept), (removed, kept))
check("... shipm-state.sh is kept whole (a half-removal would silence the module): all four of its entries remain", sum(1 for c in cmds(new) if "shipm-state.sh" in c) == 4)
new, removed, kept = ss.plan_project_hooks_global(TEMPLATE, {("Stop", False)})
check("planner: stop-gate.sh needs the --slow entry too, or it stays", "stop-gate.sh" in [k[0] for k in kept] and any("--slow" in k[1] for k in kept) and not removed, (removed, kept))
new, removed, kept = ss.plan_project_hooks_global(TEMPLATE, ALL, local_text='{"hooks": {"Stop": [{"hooks": [{"command": "$CLAUDE_PROJECT_DIR/.claude/hooks/save-plan.sh"}]}]}}')
check("planner: settings.local.json naming a script keeps it (the dispatcher module would not run)", "save-plan.sh" in [k[0] for k in kept] and "save-plan.sh" in " ".join(cmds(new)) and "block-secrets.sh" not in " ".join(cmds(new)), kept)
foreign = copy.deepcopy(TEMPLATE)
foreign["hooks"]["PreToolUse"][0]["hooks"] += [{"type": "command", "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/block-secrets.sh --extra"}, {"type": "command", "command": "/opt/x/block-secrets.sh"},
                                             {"type": "command", "command": "echo $CLAUDE_PROJECT_DIR/.claude/hooks/block-secrets.sh"}, {"type": "command", "command": ["not", "a", "string"]}]
foreign["hooks"]["Stop"].append({"matcher": "x", "hooks": [{"type": "command", "command": "keep-me.sh", "timeout": 5}], "extra": 1})
foreign["hooks"]["MyEvent"] = [{"hooks": []}]
new, removed, kept = ss.plan_project_hooks_global(foreign, ALL)
c_after = cmds(new)
check("planner: only EXACT template commands go; near-misses, other scripts, non-string commands, extra keys and odd events stay",
      all(x in c_after for x in ("$CLAUDE_PROJECT_DIR/.claude/hooks/block-secrets.sh --extra", "/opt/x/block-secrets.sh", "echo $CLAUDE_PROJECT_DIR/.claude/hooks/block-secrets.sh", "keep-me.sh"))
      and ["not", "a", "string"] in c_after and new["hooks"]["Stop"][0]["extra"] == 1 and new["hooks"]["Stop"][0]["hooks"][0]["timeout"] == 5 and new["hooks"]["MyEvent"] == [{"hooks": []}], c_after)
check("planner: an event whose groups all went is dropped, a group that keeps a foreign hook stays", "SessionStart" not in new["hooks"] and len(new["hooks"]["PreToolUse"]) >= 1)
for bad in ([], {"hooks": []}, {"hooks": {"Stop": "x"}}):
    try:
        ss.plan_project_hooks_global(bad, ALL) if bad != {"hooks": {"Stop": "x"}} else ss.plan_project_hooks_global(bad, ALL)
        ok = bad == {"hooks": {"Stop": "x"}}            # a non-list event value is passed through untouched
    except Exception as ex:
        ok = type(ex).__name__ == "SchemaError"
    check("planner on a damaged shape %r: SchemaError or untouched" % (bad,), ok)

# ---------------------------------------------------------------- hooks-global: the command, with temp projects
def mkproj(name, settings=None, git=True):
    d = DEV / name
    (d / ".claude").mkdir(parents=True, exist_ok=True)
    if git:
        (d / ".git").mkdir(exist_ok=True)
    (d / "AGENTS.md").write_text("x")
    (d / ".claude" / "settings.json").write_text(json.dumps(settings if settings is not None else TEMPLATE, indent=2) + "\n")
    os.chmod(d / ".claude" / "settings.json", 0o644)
    return d / ".claude" / "settings.json"

SET_A = mkproj("alpha", foreign)
SET_B = mkproj("beta")
subprocess.run(["git", "init", "-q", str(DEV / "alpha")], check=True)
orig = SET_A.read_bytes()
GLOBAL = HOME / ".claude" / "settings.json"
c, o, e = shipm("project", "hooks-global", "alpha")
check("hooks-global with hooks.dispatcher legacy: refused (exit 4), nothing written", c == 4 and "not v1" in e and SET_A.read_bytes() == orig, (c, e))
shipm("switch", "hooks.dispatcher", "v1")
c, o, e = shipm("project", "hooks-global", "alpha")
check("hooks-global for a project that is not in the registry: refused (exit 4)", c == 4 and "registry" in e and SET_A.read_bytes() == orig, (c, e))
check("setup: registry write", shipm("registry", "write")[0] == 0)
c, o, e = shipm("project", "hooks-global", "alpha")
check("hooks-global with no dispatcher registered globally yet: dry run, exit 0, every script kept with the reason, no change", c == 0 and "dry run" in o and "kept block-secrets.sh" in o
      and "no change" in o and SET_A.read_bytes() == orig, (c, o, e))
check("setup: shipm sync --hooks v1 (temp HOME)", shipm("sync", "--hooks", "v1")[0] == 0 and GLOBAL.exists())
gorig = GLOBAL.read_bytes()
c, o, e = shipm("project", "hooks-global", "alpha")
check("dry run: shows would-remove for all six template scripts (nine entries) and the diff, keeps nothing back, writes nothing",
      c == 0 and "dry run" in o and o.count("would remove") == 9 and "block-secrets.sh" in o and "stop-gate.sh" in o and "save-plan.sh" in o
      and "session-start.sh" in o and "shipm-state.sh" in o and "model-switch.sh" in o and "kept " not in o
      and "-            \"command\": \"$CLAUDE_PROJECT_DIR/.claude/hooks/block-secrets.sh\"" in o and SET_A.read_bytes() == orig, (c, o, e))
check("... the global settings were only read", GLOBAL.read_bytes() == gorig)
c, o, e = shipm("project", "hooks-global", "alpha", "--apply", env=env3)
check("--apply inside a chat (owner check on): refused with exit 4, nothing written", c == 4 and SET_A.read_bytes() == orig, (c, e))
c, o, e = shipm("project", "hooks-global", "alpha", "--apply")
after = json.loads(SET_A.read_text())
left = cmds(after)
bk = sorted((STATE / "v1" / "backups").glob("project-settings-*.json"))
check("--apply: all six scripts' entries are gone; format.sh, the foreign and near-miss entries stay",
      c == 0 and "removed" in o and not any(n in x for x in left for n in ("stop-gate.sh", "save-plan.sh", "session-start.sh", "model-switch.sh", "shipm-state.sh")) and "$CLAUDE_PROJECT_DIR/.claude/hooks/block-secrets.sh" not in left
      and "keep-me.sh" in left and "/opt/x/block-secrets.sh" in left and "$CLAUDE_PROJECT_DIR/.claude/hooks/format.sh" in left and after["model"] == "opusplan", (c, o, e, left))
check("--apply: a 0600 backup holds the original bytes; undo lines are printed; file mode kept", len(bk) == 1 and bk[0].read_bytes() == orig and stat.S_IMODE(os.stat(bk[0]).st_mode) == 0o600
      and "undo: shipm project hooks-global alpha --undo" in o and "cp " in o and stat.S_IMODE(os.stat(SET_A).st_mode) == 0o644, (bk, o))
check("--apply: the file keeps its indent and final newline", SET_A.read_text().endswith("}\n") and '\n  "hooks": {' in SET_A.read_text())
mid = SET_A.read_bytes()
c, o, e = shipm("project", "hooks-global", "alpha", "--apply")
check("--apply again: no change, no second backup", c == 0 and "no change" in o and SET_A.read_bytes() == mid and len(list((STATE / "v1" / "backups").glob("project-settings-*.json"))) == 1, (c, o))
c, o, e = shipm("project", "hooks-global", "alpha", "--undo", env=env3)
check("--undo inside a chat (owner check on): refused, file as it was", c == 4 and SET_A.read_bytes() == mid, (c, e))
c, o, e = shipm("project", "hooks-global", "alpha", "--undo")
check("--undo restores the original bytes", c == 0 and "restored" in o and SET_A.read_bytes() == orig, (c, o, e))
c, o, e = shipm("project", "hooks-global", "alpha", "--undo")
check("--undo twice: already identical, no change", c == 0 and "already identical" in o and SET_A.read_bytes() == orig, (c, o))
shipm("switch", "hooks.dispatcher", "legacy")
c, o, e = shipm("project", "hooks-global", "alpha", "--undo")
check("--undo works whatever hooks.dispatcher is (the way back is never blocked)", c == 0, (c, o, e))
shipm("switch", "hooks.dispatcher", "v1")
c, o, e = shipm("project", "hooks-global", "beta", "--undo")
check("--undo with no backup for that project: refused, file untouched", c == 4 and "no backup" in e, (c, e))
c, o, e = shipm("project", "hooks-global", "alpha", "--apply", "--undo")
check("--apply and --undo together: usage error 2", c == 2, (c, e))
c, o, e = shipm("project", "hooks-global")
check("hooks-global without a project: usage error 2", c == 2 and "PROJECT" in e, (c, e))
c, o, e = shipm("project", "hooks-global", "nope")
check("hooks-global with an unknown project: not found (exit 3)", c == 3, (c, e))
c, o, e = shipm("project", "migrate-team", "alpha", "--undo")
check("--undo on migrate-team: usage error 2", c == 2, (c, e))
# symlinked and damaged settings
real = DEV / "beta" / ".claude" / "settings.real.json"
SET_B.rename(real); os.symlink(str(real), str(SET_B))
c, o, e = shipm("project", "hooks-global", "beta", "--apply")
check("a symlinked settings.json is refused (exit 4) and the target is untouched", c == 4 and "symlink" in e and json.loads(real.read_text()) == TEMPLATE, (c, e))
SET_B.unlink(); real.rename(SET_B)
SET_B.write_text("{not json")
c, o, e = shipm("project", "hooks-global", "beta", "--apply")
check("damaged settings.json: refused, file untouched", c != 0 and SET_B.read_text() == "{not json", (c, e))
SET_B.unlink()
c, o, e = shipm("project", "hooks-global", "beta")
check("no settings.json: refused with a message", c != 0 and "does not exist" in e, (c, e))
# a fuller global registration (all events) removes all six scripts: simulate by adding the three missing events to the global file
g = json.loads(GLOBAL.read_text())
pre = ss.spec.hooks_prefix(WS, HOME)[0]
for ev in ("SessionStart", "Notification", "PreModelSwitch"):
    g["hooks"][ev] = [{"hooks": [{"type": "command", "command": ss.spec.dispatcher_command(pre, ev, (), HOME)}]}]
GLOBAL.write_text(json.dumps(g, indent=2) + "\n")
SET_B = mkproj("beta")
c, o, e = shipm("project", "hooks-global", "beta", "--apply")
check("when the dispatcher is registered for every event, all six scripts go and only format.sh remains", c == 0 and cmds(json.loads(SET_B.read_text())) == ["$CLAUDE_PROJECT_DIR/.claude/hooks/format.sh"] and "kept" not in o, (c, o, e))
# settings.local.json
SET_C = mkproj("gamma")
subprocess.run(["git", "init", "-q", str(DEV / "gamma")], check=True)
(DEV / "gamma" / ".claude" / "settings.local.json").write_text(json.dumps({"hooks": {"Stop": [{"hooks": [{"command": "$CLAUDE_PROJECT_DIR/.claude/hooks/model-switch.sh"}]}]}}))
shipm("registry", "write")
c, o, e = shipm("project", "hooks-global", "gamma", "--apply")
check("settings.local.json that names a script keeps that script", c == 0 and "kept model-switch.sh: .claude/settings.local.json names it too" in o and "model-switch.sh" in SET_C.read_text() and "block-secrets.sh" not in SET_C.read_text(), (c, o, e))
from shipmiracle.hooks import core  # noqa: E402
os.environ["SHIPMIRACLE_CONFIG"] = str(CONF)
check("core.project_owned: block_secrets is now served by the dispatcher for gamma, model_switch is not", core.project_owned(str(DEV / "gamma"), "block_secrets", str(DEV)) is True
      and core.project_owned(str(DEV / "gamma"), "model_switch", str(DEV)) is False)

# ---------------------------------------------------------------- docs/owner-steps/p5-playbook.sh
SCRIPT = str(ROOT / "docs" / "owner-steps" / "p5-playbook.sh")
def script(*args, env=None, inp=""):
    r = subprocess.run(["bash", SCRIPT] + list(args), env=env or ENV, capture_output=True, text=True, timeout=120, input=inp)
    return r.returncode, r.stdout, r.stderr
(CONF / "config.json").write_text("{}")
c, o, e = script("--help")
check("p5 script --help: exit 0, prints the header with the steps and undo lines", c == 0 and "shadow-report --stage" in o and "undo:" in o, (c, o[:200], e))
c, o, e = script("--bogus")
check("p5 script bad option: exit 2", c == 2 and "usage" in e, (c, e))
shipm("switch", "hooks.dispatcher", "legacy")
c, o, e = script()
check("p5 dry run, dispatcher not v1: BLOCKED (exit 1), names the remedy, writes nothing", c == 1 and "MISSING  hooks.dispatcher is v1" in o and "shipm switch hooks.dispatcher v1" in o and "dry run" in o
      and cfg().get("gate.engine") is None, (c, o, e))
check("p5 script refuses --promote while gate.engine is not shadow", script("--promote")[0] == 1 and "not shadow" in script("--promote")[2])
shipm("switch", "hooks.dispatcher", "v1"); shipm("sync", "--hooks", "v1")
c, o, e = script()
check("p5 dry run with the v1 registration in place: exit 0, per-project dry runs, plan with undo lines, nothing written", c == 0 and "DRY RUN done" in o and "undo: shipm switch gate.engine legacy" in o
      and "-- alpha" in o and cfg().get("gate.engine") is None and not (DEV / "alpha" / ".shipmiracle").exists(), (c, o, e))
c, o, e = script("--apply", inp="no\n")
check("p5 --apply without yes: exit 2, gate.engine unchanged", c == 2 and "not confirmed" in e and cfg().get("gate.engine") is None, (c, e))
c, o, e = script("--apply", inp="yes\n")
check("p5 --apply + yes: gate.engine is shadow (the sandbox seed knows no project, so Shipmiracle skips them and the script says so, exit 1)", c == 1 and cfg().get("gate.engine") == "shadow" and "some projects were skipped" in o
      and "Undo: shipm switch gate.engine legacy" in o, (c, o, e, cfg()))
events.emit("stage.shadow", {"kind": "cr_needs_plan", "cr": "CR-777", "stage": "Do"}, project="cccccccccccc", src="hooks")
c, o, e = script("--promote")
check("p5 --promote dry run: shows the stage report and the plan, switches nothing", c == 0 and "stage.shadow events" in o and "cr_needs_plan" in o and "CR-777" not in o and cfg().get("gate.engine") == "shadow", (c, o, e))
c, o, e = script("--promote", "--apply", inp="no\n")
check("p5 --promote --apply without yes: exit 2, still shadow", c == 2 and cfg().get("gate.engine") == "shadow", (c, e))
c, o, e = script("--promote", "--apply", inp="yes\n")
check("p5 --promote --apply + yes: gate.engine playbook", c == 0 and cfg().get("gate.engine") == "playbook" and "Undo: shipm switch gate.engine shadow" in o, (c, o, e))
# the chat refusal mirrors paths.sandboxed()
chat = dict(ENV, CLAUDECODE="1")
c, o, e = script(env=chat)
check("p5 inside a chat but in a FULL temp sandbox (SHIPMIRACLE_TEST + HOME/STATE/CONFIG/WS/DEV all under temp): allowed", c in (0, 1) and "BLOCKED: run this in a normal terminal" not in e, (c, e))
for var in ("SHIPMIRACLE_DEV", "SHIPMIRACLE_WS"):
    part = dict(chat); part.pop(var)
    c, o, e = script(env=part)
    check("p5 inside a chat with %s missing (partial sandbox): refused, exit 1" % var, c == 1 and "not inside a Claude chat" in e, (c, e))
c, o, e = script(env=dict(chat, SHIPMIRACLE_STATE="/var/lib/not-temp-shipm-state"))
check("p5 inside a chat with SHIPMIRACLE_STATE outside the temp folder: refused", c == 1 and "not inside a Claude chat" in e, (c, e))
c, o, e = script(env=dict(chat, SHIPMIRACLE_TEST="0"))
check("p5 inside a chat without SHIPMIRACLE_TEST=1: refused", c == 1 and "not inside a Claude chat" in e, (c, e))

print("\nFAILED: %d" % fails if fails else "\nALL PASS"); sys.exit(1 if fails else 0)
