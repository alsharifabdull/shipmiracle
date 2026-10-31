#!/usr/bin/env python3
"""shipmiracle/playbook/types.py + config.py: the six type files validate (and bad variants do not), every rule of .shipmiracle/playbook.json, canonical
form and sha, the trust fallback matrix, stage_rules. Temp dirs + SHIPMIRACLE_TEST=1 only. Run: python3 tests/playbook_types_test.py"""
import copy, json, os, pathlib, sys, tempfile, time

ROOT = pathlib.Path(__file__).resolve().parent.parent
TMP = pathlib.Path(tempfile.mkdtemp()).resolve()
os.environ.update(SHIPMIRACLE_TEST="1", SHIPMIRACLE_HOME=str(TMP / "home"), SHIPMIRACLE_STATE=str(TMP / "state"), SHIPMIRACLE_CONFIG=str(TMP / "config"),
                  SHIPMIRACLE_DEV=str(TMP / "dev"), SHIPMIRACLE_WS=str(TMP / "ws"))
sys.path.insert(0, str(ROOT))
from shipmiracle import SchemaError, UsageError  # noqa: E402
from shipmiracle.playbook import config, gate, types  # noqa: E402

fails = 0
def check(name, ok, info=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(info)))
    fails += 0 if ok else 1

def raises(exc, fn, *a, **k):
    try:
        fn(*a, **k)
    except exc as e:
        return str(e)
    except Exception as e:
        return None
    return None

def bad(name, d, frag=None, **k):
    msg = raises(UsageError, config.validate, d, **k)
    check(name, msg is not None and (frag is None or frag in msg), msg)

# ---- the six type files ------------------------------------------------------------------------
check("six types", list(types.TYPES) == ["software", "app", "content", "research", "ops", "notes"])
al = types.load_all()
check("all six type files load and validate", sorted(al) == sorted(types.TYPES))
check("stage ids are the nine fixed ones", types.STAGES == ("intake", "scope", "plan", "approve", "do", "verify", "review", "deliver", "learn"))
L = lambda t: [al[t]["labels"][s] for s in ("do", "verify", "deliver")]
check("labels per type (section 2.1)", L("software") == ["Build", "Test", "Release"] and L("app") == ["Build", "Test", "Release"]
      and L("content") == ["Write", "Check", "Publish"] and L("research") == ["Draft", "Check", "Hand over"]
      and L("ops") == ["Change", "Dry-run", "Apply"] and L("notes") == ["Write", "Check", "File"], [L(t) for t in al])
check("default lanes: ops full, the rest fast", {t: al[t]["lane"]["default"] for t in al} == {"software": "fast", "app": "fast", "content": "fast", "research": "fast", "ops": "full", "notes": "fast"})
check("fast allowed: all but ops", {t: al[t]["lane"]["fast_allowed"] for t in al} == {"software": True, "app": True, "content": True, "research": True, "ops": False, "notes": True})
check("fast limits", [al[t]["fast_limit"] for t in ("software", "app", "content", "research", "ops", "notes")] ==
      [{"max_files": 3, "max_lines": 50}, {"max_files": 3, "max_lines": 50}, {"max_files": 3, "max_lines": 150}, {"max_files": 3, "max_lines": 200}, None,
       {"max_files": 5, "max_lines": None}])
check("review lenses", al["software"]["review"] == {"full": ["correctness"], "on_risk": ["risk"], "on_ui": [], "always": []}
      and al["app"]["review"]["on_ui"] == ["design"] and al["ops"]["review"]["always"] == ["correctness", "risk"]
      and al["notes"]["review"] == {"full": [], "on_risk": [], "on_ui": [], "always": []}
      and al["content"]["review"]["full"] == ["correctness"] and al["research"]["review"]["full"] == ["correctness"])
check("verify brief checks", al["software"]["checks"] == ["tests", "lint", "criteria"] and "contrast 4.5" in al["app"]["checks"]
      and al["ops"]["checks"] == ["dry-run output", "rollback tested", "health check"] and al["notes"]["checks"] == ["file saved", "links"]
      and al["content"]["checks"] == ["spelling", "length/tone", "sources", "rtl"] and al["research"]["checks"] == ["links", "answer-first", "confidence", "unknowns"])
check("risk_paths_default only software and app", [bool(al[t]["risk_paths_default"]) for t in types.TYPES] == [True, True, False, False, False, False]
      and al["software"]["risk_paths_default"] == al["app"]["risk_paths_default"] and "**/auth/**" in al["software"]["risk_paths_default"]
      and ".github/workflows/**" in al["software"]["risk_paths_default"] and len(al["software"]["risk_paths_default"]) == 10)
check("dep_files", "package.json" in al["software"]["dep_files"] and "Cargo.*" in al["app"]["dep_files"] and len(al["software"]["dep_files"]) == 17)
check("ui_paths only for app", al["app"]["ui_paths"] == ["**/*.{tsx,jsx,css,scss,html,vue,svelte,swift}"] and not al["software"]["ui_paths"])
check("fast lane skips scope, plan, approve, review", al["software"]["skips"] == {"fast": ["scope", "plan", "approve", "review"]})
check("roles: approve owner, app has design", al["software"]["roles"]["approve"] == "owner" and al["app"]["roles"]["design"] == "design"
      and "design" not in al["software"]["roles"] and al["software"]["roles"]["do"] == "build" and al["software"]["roles"]["verify"] == "test")
check("load returns a copy", (lambda: (al["app"].update(type="x"), types.load("app")["type"])[1])() == "app")
check("unknown type name refused", raises(SchemaError, types.load, "nope") is not None and raises(SchemaError, types.load, 3) is not None)

base = types.load("software")
def tbad(name, mut, name_arg=None):
    d = copy.deepcopy(base)
    mut(d)
    check("bad type variant: " + name, raises(SchemaError, types.validate_type, d, name_arg) is not None)
tbad("extra key", lambda d: d.update(extra=1))
tbad("missing key", lambda d: d.pop("labels"))
tbad("v=2", lambda d: d.update(v=2))
tbad("unknown type", lambda d: d.update(type="web"))
tbad("name mismatch", lambda d: None, "app")
tbad("label missing", lambda d: d["labels"].pop("learn"))
tbad("label too long", lambda d: d["labels"].update(do="x" * 30))
tbad("role unknown", lambda d: d["roles"].update(do="king"))
tbad("agents missing", lambda d: d["agents"].pop("design"))
tbad("agent bad name", lambda d: d["agents"].update(plan="Bad Name"))
tbad("default fast without fast_allowed", lambda d: d["lane"].update(fast_allowed=False))
tbad("fast_limit required", lambda d: d.update(fast_limit=None))
tbad("fast_limit files 11", lambda d: d["fast_limit"].update(max_files=11))
tbad("fast_limit lines 501", lambda d: d["fast_limit"].update(max_lines=501))
tbad("fast_limit bool", lambda d: d["fast_limit"].update(max_files=True))
tbad("review unknown lens", lambda d: d["review"].update(full=["style"]))
tbad("design lens without design role", lambda d: d["review"].update(on_ui=["design"]))
tbad("skips unknown stage", lambda d: d["skips"].update(fast=["intake"]))
tbad("checks not strings", lambda d: d.update(checks=[1]))
tbad("risk glob too long", lambda d: d.update(risk_paths_default=["x" * 201]))
check("not an object", raises(SchemaError, types.validate_type, []) is not None)

# ---- config.validate: every rule -----------------------------------------------------------------
full = {"v": 1, "type": "software", "level": "strict", "autopilot": "guided",
        "overrides": {"risk_paths": ["src/auth/**"], "test_cmd": ".claude/test-command", "fast_lane": {"max_files": 3, "max_lines": 50}},
        "charter": None, "report": {"lang": "en"}, "set_by": "shipm playbook set", "ts": 1760950000}
proj = TMP / "proj"
(proj / ".claude").mkdir(parents=True)
(proj / ".claude" / "test-command").write_text("npm test\n")
n = config.validate(full, project_dir=proj)
check("the spec example validates and normalises to itself", n == full, n)
check("defaults filled", config.validate({"v": 1, "type": "notes"}) == {"v": 1, "type": "notes", "level": "strict", "autopilot": "guided", "overrides": {},
                                                                         "charter": None, "report": {"lang": "en"}})
for t in types.TYPES:
    check("type %s accepted" % t, config.validate({"v": 1, "type": t})["type"] == t)
bad("unknown top-level key refused", dict(full, extra=1), "unknown keys")
bad("unknown override key refused", {"v": 1, "type": "app", "overrides": {"autopilot": "full"}}, "overrides")
bad("unknown report key refused", {"v": 1, "type": "app", "report": {"lang": "en", "x": 1}})
bad("missing v", {"type": "app"})
bad("v=2", {"v": 2, "type": "app"})
bad("v=True", {"v": True, "type": "app"})
bad("type missing", {"v": 1})
bad("type unknown", {"v": 1, "type": "web"})
bad("type not a string", {"v": 1, "type": ["app"]})
bad("level bad", {"v": 1, "type": "app", "level": "loud"}, "level")
for lv in ("strict", "warn", "off"):
    check("level %s accepted" % lv, config.validate({"v": 1, "type": "app", "level": lv})["level"] == lv)
bad("autopilot full refused with the exact message", {"v": 1, "type": "app", "autopilot": "full"}, "full autopilot arrives in P6")
check("autopilot full message is exactly that", raises(UsageError, config.validate, {"v": 1, "type": "app", "autopilot": "full"}) == "full autopilot arrives in P6")
bad("autopilot nonsense", {"v": 1, "type": "app", "autopilot": "turbo"})
check("autopilot manual kept", config.validate({"v": 1, "type": "app", "autopilot": "manual"})["autopilot"] == "manual")
check("autopilot off forces manual", config.validate({"v": 1, "type": "app", "autopilot": "off"})["autopilot"] == "manual")
check("level off forces manual", config.validate({"v": 1, "type": "app", "level": "off", "autopilot": "guided"})["autopilot"] == "manual")
ov = lambda **k: {"v": 1, "type": "software", "overrides": k}
check("risk_paths 50 globs ok", len(config.validate(ov(risk_paths=["a/%d/**" % i for i in range(50)]))["overrides"]["risk_paths"]) == 50)
bad("risk_paths 51 globs", ov(risk_paths=["a/%d" % i for i in range(51)]))
bad("risk_paths glob 201 chars", ov(risk_paths=["x" * 201]))
check("risk_paths glob 200 chars ok", bool(config.validate(ov(risk_paths=["x" * 200]))))
bad("risk_paths empty glob", ov(risk_paths=[""]))
bad("risk_paths absolute", ov(risk_paths=["/etc/**"]))
bad("risk_paths dotdot", ov(risk_paths=["a/../b"]))
bad("risk_paths leading ..", ov(risk_paths=["../x"]))
bad("risk_paths tilde", ov(risk_paths=["~/x"]))
bad("risk_paths control char", ov(risk_paths=["a\nb"]))
bad("risk_paths backslash", ov(risk_paths=["a\\b"]))
bad("risk_paths not a list", ov(risk_paths="src/**"))
bad("risk_paths item not a string", ov(risk_paths=[1]))
check("risk_paths dots inside names ok", bool(config.validate(ov(risk_paths=["a..b/**", ".env*"]))))
check("test_cmd relative accepted without a project", config.validate(ov(test_cmd="bin" "/test"))["overrides"]["test_cmd"] == "bin" "/test")
bad("test_cmd absolute", ov(test_cmd="/bin/sh"))
bad("test_cmd dotdot", ov(test_cmd="../x"))
bad("test_cmd not a string", ov(test_cmd=["x"]))
bad("test_cmd missing file with a project", ov(test_cmd="nope.sh"), "no such file", project_dir=proj)
(TMP / "outside.sh").write_text("x")
os.symlink(str(TMP / "outside.sh"), str(proj / "link.sh"))
bad("test_cmd symlink escaping the project", ov(test_cmd="link.sh"), "outside", project_dir=proj)
check("test_cmd file inside the project ok", config.validate(ov(test_cmd=".claude/test-command"), project_dir=proj)["overrides"]["test_cmd"] == ".claude/test-command")
for k, v in (("max_files", 0), ("max_files", 11), ("max_files", "3"), ("max_files", True), ("max_files", 2.5), ("max_lines", 0), ("max_lines", 501), ("max_lines", None)):
    bad("fast_lane %s=%r refused" % (k, v), ov(fast_lane={k: v}))
for k, v in (("max_files", 1), ("max_files", 10), ("max_lines", 1), ("max_lines", 500)):
    check("fast_lane %s=%d accepted (range edge)" % (k, v), config.validate(ov(fast_lane={k: v}))["overrides"]["fast_lane"] == {k: v})
bad("fast_lane unknown key", ov(fast_lane={"max_bytes": 5}))
bad("fast_lane empty", ov(fast_lane={}))
bad("charter must be null", dict(full, charter={"goal": "x"}), "charter")
bad("charter string", dict(full, charter="x"))
bad("report.lang bad", dict(full, report={"lang": "fr"}))
check("report.lang ar", config.validate(dict(full, report={"lang": "ar"}))["report"]["lang"] == "ar")
bad("set_by too long", dict(full, set_by="x" * 41))
bad("ts negative", dict(full, ts=-1))
bad("not an object", [])
bad("overrides not an object", {"v": 1, "type": "app", "overrides": []})

# ---- parse / canonical / sha -----------------------------------------------------------------------
raw = json.dumps(full).encode()
check("parse accepts the example", config.parse(raw) == config.validate(full))
check("parse refuses > 4 KB", raises(UsageError, config.parse, b" " * 4097 + raw) is not None)
check("parse refuses non-JSON and NaN", raises(UsageError, config.parse, b"{") is not None and raises(UsageError, config.parse, b'{"v":NaN}') is not None)
check("parse refuses invalid utf-8", raises(UsageError, config.parse, b"\xff\xfe") is not None)
a = {"type": "app", "v": 1, "overrides": {"fast_lane": {"max_lines": 9, "max_files": 2}, "risk_paths": ["x/**"]}}
b = {"overrides": {"risk_paths": ["x/**"], "fast_lane": {"max_files": 2, "max_lines": 9}}, "v": 1, "type": "app"}
check("sha is stable across key order", config.digest(a) == config.digest(b) and len(config.digest(a)) == 64)
check("sha ignores omitted defaults", config.digest(a) == config.digest(config.validate(a)))
check("canonical is sorted, compact, ASCII", config.canonical({"b": 1, "a": "é"}) == b'{"a":"\\u00e9","b":1}')
check("sha changes with content", config.digest(a) != config.digest(dict(a, type="software")) and config.digest(a) != config.digest(dict(a, level="warn")))
check("sha is a known value (pinned)", config.digest({"v": 1, "type": "software"}) == __import__("hashlib").sha256(
    b'{"autopilot":"guided","charter":null,"level":"strict","overrides":{},"report":{"lang":"en"},"type":"software","v":1}').hexdigest())
sn = config.snapshot_of(a)
check("snapshot has exactly sha256/type/autopilot/overrides", set(sn) == {"sha256", "type", "autopilot", "overrides"} and sn["sha256"] == config.digest(a))

# ---- trust rule ------------------------------------------------------------------------------------
def mkproj(name, playbook=None):
    p = TMP / name
    (p / ".shipmiracle").mkdir(parents=True)
    if playbook is not None:
        (p / ".shipmiracle" / "playbook.json").write_bytes(playbook if isinstance(playbook, bytes) else json.dumps(playbook).encode())
    return p

good = {"v": 1, "type": "app", "level": "strict", "autopilot": "guided", "overrides": {"risk_paths": ["src/auth/**"]}}
loose = {"v": 1, "type": "notes", "level": "off", "autopilot": "manual", "overrides": {"fast_lane": {"max_files": 10, "max_lines": 500}}}
entry = {"playbook": config.snapshot_of(good)}
p = mkproj("t1", good)
cfg, st, why = config.load_trusted(p, entry)
check("matching sha: trusted, file used", st == "trusted" and cfg == config.validate(good), (st, why))
check("trusted pretty-printed / reordered file still matches", config.load_trusted(mkproj("t1b", json.dumps(good, indent=3, sort_keys=True).encode()), entry)[1] == "trusted")
p = mkproj("t2", loose)
cfg, st, why = config.load_trusted(p, entry)
check("edited file (sha mismatch): untrusted, registry snapshot used", st == "untrusted" and cfg["type"] == "app" and cfg["overrides"] == {"risk_paths": ["src/auth/**"]}
      and cfg["autopilot"] == "guided" and "registry snapshot" in why, (st, cfg, why))
cfg, st, why = config.load_trusted(p, {})
check("file but no registry snapshot: untrusted, software defaults, guided, no overrides", st == "untrusted" and cfg == config.defaults() and cfg["type"] == "software"
      and cfg["autopilot"] == "guided" and cfg["overrides"] == {}, (st, cfg))
cfg, st, why = config.load_trusted(p, None)
check("file and no registry entry at all: same fallback", st == "untrusted" and cfg == config.defaults())
cfg, st, why = config.load_trusted(mkproj("t3", b"{not json"), entry)
check("invalid JSON counts as untrusted (snapshot)", st == "untrusted" and cfg["type"] == "app" and "invalid" in why, (st, why))
cfg, st, why = config.load_trusted(mkproj("t3b", dict(good, charter={"x": 1})), entry)
check("invalid content counts as untrusted (snapshot)", st == "untrusted" and cfg["type"] == "app")
cfg, st, why = config.load_trusted(mkproj("t3c", dict(good, autopilot="full")), entry)
check("autopilot full in the file is untrusted, never effective", st == "untrusted" and cfg["autopilot"] == "guided")
cfg, st, why = config.load_trusted(mkproj("t3d", b"x" * 5000), {})
check("oversize file: untrusted, defaults", st == "untrusted" and cfg == config.defaults())
cfg, st, why = config.load_trusted(mkproj("t4"), entry)
check("no file but a snapshot: snapshot state, snapshot used", st == "snapshot" and cfg["type"] == "app" and cfg["overrides"] == good["overrides"], (st, why))
cfg, st, why = config.load_trusted(mkproj("t5"), {})
check("no file and no snapshot: none", cfg is None and st == "none")
cfg, st, why = config.load_trusted(TMP / "no-such-dir", None)
check("project without .shipmiracle: none", cfg is None and st == "none")
for name, e in (("sha not hex", {"playbook": dict(entry["playbook"], sha256="zz")}), ("snapshot extra key", {"playbook": dict(entry["playbook"], x=1)}),
                ("snapshot type bad", {"playbook": dict(entry["playbook"], type="web")}), ("snapshot autopilot full", {"playbook": dict(entry["playbook"], autopilot="full")}),
                ("snapshot not a dict", {"playbook": "x"})):
    cfg, st, why = config.load_trusted(mkproj("d-" + name.replace(" ", "")), e)
    check("damaged snapshot (%s) is ignored" % name, cfg is None and st == "none", (st, cfg))
cfg, st, why = config.load_trusted(mkproj("d2", good), {"playbook": dict(entry["playbook"], autopilot="full")})
check("damaged snapshot + file: untrusted defaults", st == "untrusted" and cfg == config.defaults())
pl = mkproj("t6")
os.symlink(str(TMP / "proj" / ".claude" / "test-command"), str(pl / ".shipmiracle" / "playbook.json"))
cfg, st, why = config.load_trusted(pl, entry)
check("playbook.json as a symlink is untrusted (snapshot)", st == "untrusted" and cfg["type"] == "app", (st, why))
# a chat that loosens the file after the owner set it can never widen anything
p = mkproj("t7", good)
(p / ".shipmiracle" / "playbook.json").write_text(json.dumps(dict(good, level="off", autopilot="manual", overrides={"fast_lane": {"max_files": 10, "max_lines": 500}})))
cfg, st, why = config.load_trusted(p, entry)
check("loosened file ignored: fast_lane override not present", st == "untrusted" and "fast_lane" not in cfg["overrides"])

# ---- stage_rules (the adapter) -------------------------------------------------------------------------
import shipmiracle.registry as registry, shipmiracle.projects as projects
proj_dir = TMP / "dev" / "Demo"
(proj_dir / ".shipmiracle").mkdir(parents=True)
(proj_dir / ".git").mkdir()
(proj_dir / ".shipmiracle" / "playbook.json").write_text(json.dumps(good))
(TMP / "config").mkdir(exist_ok=True)
(TMP / "ws" / "config").mkdir(parents=True)
(TMP / "ws" / "config" / "flow.json").write_text(json.dumps({"default": "strict", "projects": {"Demo": "warn"}}))
pid = projects.project_id(proj_dir)
(TMP / "config" / "registry.json").write_text(json.dumps({"v": 1, "projects": {pid: {"name": "Demo", "playbook": config.snapshot_of(good)}}}))
os.chmod(TMP / "config", 0o700)
r = gate.stage_rules(proj_dir)
check("stage_rules: trusted app rules", r["type"] == "app" and r["trusted"] and r["trust"] == "trusted" and r["autopilot"] == "guided", r and (r["trust"], r["reason"]))
check("stage_rules: level comes from config/flow.json", r["level"] == "warn")
check("stage_rules: overrides first in risk, then defaults", r["risk"][0] == "src/auth/**" and "**/auth/**" in r["risk"] and len(r["risk"]) == 11)
check("stage_rules: limits, ui, deps, review, labels", r["limits"] == {"max_files": 3, "max_lines": 50} and r["ui"] and r["deps"] and r["review"]["on_ui"] == ["design"]
      and r["labels"]["verify"] == "Test" and r["lanes"]["fast_allowed"] and r["project"] == "Demo")
r2 = gate.stage_rules(proj_dir)
r2["risk"].append("zzz")
check("stage_rules returns copies and caches", gate.stage_rules(proj_dir)["risk"] == r["risk"])
time.sleep(0.02)
(proj_dir / ".shipmiracle" / "playbook.json").write_text(json.dumps(dict(good, type="ops")))
r3 = gate.stage_rules(proj_dir)
check("stage_rules: cache follows the playbook mtime; edited file falls back to the snapshot (untrusted)", r3["trust"] == "untrusted" and r3["type"] == "app" and not r3["trusted"])
(TMP / "ws" / "config" / "flow.json").write_text(json.dumps({"default": "off"}))
r4 = gate.stage_rules(proj_dir)
check("stage_rules: flow.json change refreshes the level; level off forces manual", r4["level"] == "off" and r4["autopilot"] == "manual", r4["level"])
(TMP / "ws" / "config" / "flow.json").write_text("{broken")
check("stage_rules: unreadable flow.json = strict", gate.stage_rules(proj_dir)["level"] == "strict")
ops_dir = TMP / "dev" / "OpsP"
(ops_dir / ".shipmiracle").mkdir(parents=True); (ops_dir / ".git").mkdir()
o = {"v": 1, "type": "ops", "overrides": {"fast_lane": {"max_files": 2}}}
(ops_dir / ".shipmiracle" / "playbook.json").write_text(json.dumps(o))
reg = json.loads((TMP / "config" / "registry.json").read_text())
reg["projects"][projects.project_id(ops_dir)] = {"name": "OpsP", "playbook": config.snapshot_of(o)}
(TMP / "config" / "registry.json").write_text(json.dumps(reg))
ro = gate.stage_rules(ops_dir)
check("stage_rules: ops has no limits and no fast lane", ro["limits"] is None and not ro["lanes"]["fast_allowed"] and ro["lanes"]["default"] == "full")
none_dir = TMP / "dev" / "Plain"; (none_dir).mkdir(); (none_dir / ".git").mkdir()
check("stage_rules: no playbook -> None", gate.stage_rules(none_dir) is None)

print("\nFAILED: %d" % fails if fails else "\nALL PASS")
sys.exit(1 if fails else 0)
