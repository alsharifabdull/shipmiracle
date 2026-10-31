#!/usr/bin/env python3
"""F5 Toolbox, CLI side (panel v3 UX addendum section 1): the `assets` field of playbook.json (schema, caps, canonical form), `shipm playbook asset add|remove|list`,
trust through the registry sha, owner-only refusals, the typed confirmation, the guarded writer and the `toolbox` / `caps` fields of `shipm report panel`.
Real subprocesses in full isolation (tests/shipmiracle_isolation.py), no model, no network. Run: python3 tests/shipmiracle_assets_test.py"""
import hashlib, json, os, pathlib, subprocess, sys, time, types

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import shipmiracle_isolation as ISO  # noqa: E402

ENV, TMP = ISO.isolated_env()
TMP = pathlib.Path(TMP)
(pathlib.Path(ENV["SHIPMIRACLE_WS"]) / "config").mkdir(parents=True, exist_ok=True)
(pathlib.Path(ENV["SHIPMIRACLE_WS"]) / "config" / "flow.json").write_text('{"default": "strict", "projects": {}}\n')
os.environ.update(ENV)
ENV.pop("CLAUDECODE", None); os.environ.pop("CLAUDECODE", None)
DEV = pathlib.Path(ENV["SHIPMIRACLE_DEV"]); STATE = pathlib.Path(ENV["SHIPMIRACLE_STATE"])
from shipmiracle import UsageError, SafetyError, registry  # noqa: E402
from shipmiracle.playbook import config as pbc, assets as PA  # noqa: E402

fails = 0
def check(name, ok, info=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(info)[:600]))
    fails += 0 if ok else 1

def raises(exc, fn, *a, **k):
    try:
        fn(*a, **k)
    except exc:
        return True
    except BaseException:
        return False
    return False

def shipm(*args, extra=None):
    e = dict(ENV); e.update(extra or {})
    r = subprocess.run([sys.executable, str(ROOT / "bin" / "shipm")] + list(args), env=e, capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)
    return r.returncode, r.stdout, r.stderr

def git(d, *a):
    return subprocess.run(["git", "-C", str(d)] + list(a), env=ENV, capture_output=True, text=True).stdout

D = DEV / "alpha"; D.mkdir(parents=True)
subprocess.run(["git", "-C", str(D), "init", "-q"], env=ENV, check=True)
(D / "scripts").mkdir(); (D / "docs").mkdir()
(D / "scripts" / "seed_menu.py").write_text("print('seed')\n")
(D / "docs" / "rtl-checklist.md").write_text("# RTL\n")
(D / ".env").write_text("K=v\n")
(D / "id_rsa").write_text("x")
os.symlink(str(D / "scripts" / "seed_menu.py"), str(D / "scripts" / "link.py"))
subprocess.run(["git", "-C", str(D), "add", "-A"], env=ENV, check=True)
subprocess.run(["git", "-C", str(D), "commit", "-q", "-m", "init"], env=ENV, check=True)
STATE.mkdir(parents=True, exist_ok=True)
(STATE / "health.json").write_text(json.dumps({"ts": time.time(), "chats": {"alpha": {"chats": 0}}}))
SHA1 = hashlib.sha256(b"print('seed')\n").hexdigest()

# ---------------------------------------------------------------- schema and canonical form
base = {"v": 1, "type": "software"}
def ent(i, **kw):
    d = {"path": "scripts/s%d.py" % i, "sha256": "a" * 64, "purpose": "p", "stage": "do"}; d.update(kw); return d
check("schema: no assets = old canonical form (key absent, same sha as before)", "assets" not in pbc.validate(base) and pbc.digest(base) == pbc.digest(dict(base, assets=[])))
check("schema: one valid asset is kept", pbc.validate(dict(base, assets=[ent(1)]))["assets"] == [ent(1)])
check("schema: sorted by path (order does not change the sha)", pbc.digest(dict(base, assets=[ent(2), ent(1)])) == pbc.digest(dict(base, assets=[ent(1), ent(2)])))
check("schema: 40 assets ok, 41 refused", len(pbc.validate(dict(base, assets=[ent(i) for i in range(40)]))["assets"]) == 40 and raises(UsageError, pbc.validate, dict(base, assets=[ent(i) for i in range(41)])))
check("schema: duplicate path refused", raises(UsageError, pbc.validate, dict(base, assets=[ent(1), ent(1)])))
for label, kw in (("absolute path", dict(path="/etc/passwd")), ("dotdot", dict(path="a/../../b")), ("home", dict(path="~/x")), ("bad sha", dict(sha256="xyz")), ("empty purpose", dict(purpose="  ")),
                  ("control char in purpose", dict(purpose="a\x1bb")), ("purpose 121", dict(purpose="x" * 121)), ("unknown stage", dict(stage="build")), ("backslash", dict(path="a\\b")), ("trailing slash", dict(path="a/"))):
    check("schema: %s refused" % label, raises(UsageError, pbc.validate, dict(base, assets=[ent(1, **kw)])))
check("schema: an extra key in an asset refused", raises(UsageError, pbc.validate, dict(base, assets=[dict(ent(1), x=1)])))
check("schema: assets not a list refused", raises(UsageError, pbc.validate, dict(base, assets="x")) and raises(UsageError, pbc.validate, dict(base, assets=None)))
raw = json.dumps(base).encode()
check("size: no assets keeps the 4 KB cap", raises(UsageError, pbc.parse, b" " * 4097 + raw) and pbc.parse(b" " * 3000 + raw)["type"] == "software")
big = json.dumps(dict(base, assets=[ent(i, purpose="y" * 100) for i in range(30)]), indent=1).encode()
check("size: with assets the cap is 16 KB (a 6-16 KB file parses)", 4096 < len(big) <= 16384 and len(pbc.parse(big)["assets"]) == 30, len(big))
check("size: over 16 KB refused even with assets", raises(UsageError, pbc.parse, big + b" " * 17000))

# ---------------------------------------------------------------- CLI
A = str(D)
c, o, e = shipm("playbook", "asset", "list", "--project", A)
check("list with no playbook: exit 0, 'no assets yet'", c == 0 and "no assets yet" in o, (c, o, e))
c, o, e = shipm("playbook", "asset", "add", "scripts/seed_menu.py", "--stage", "do", "--purpose", "Seeds", "--project", A)
check("add without a playbook: exit 1 and says what to do", c == 1 and "no playbook" in e, (c, e))
check("set type software", shipm("playbook", "set", "type", "software", "--project", A)[0] == 0)
c, o, e = shipm("playbook", "asset", "add", "scripts/seed_menu.py", "--stage", "do", "--purpose", "Seeds  the\n demo menu", "--project", A)
check("add: exit 0, prints sha and the purpose, committed", c == 0 and SHA1 in o and "committed" in o, (c, o, e))
pb = json.loads((D / ".shipmiracle" / "playbook.json").read_text())
check("add: playbook.json has the asset with the sha256 and a tidy purpose", pb["assets"] == [{"path": "scripts/seed_menu.py", "sha256": SHA1, "purpose": "Seeds the demo menu", "stage": "do"}], pb)
check("add: git log has the commit", "shipm: playbook asset add" in git(D, "log", "--format=%s", "-3"))
c, o, e = shipm("playbook", "show", "--project", A, "--json")
check("add: still trusted (registry sha covers the assets)", json.loads(o)["trust"] == "trusted", o[:300])
c, o, e = shipm("playbook", "asset", "list", "--project", A, "--json")
j = json.loads(o)
check("list --json: v, total, changed, row fields", c == 0 and j["v"] == 1 and j["total"] == 1 and j["changed"] == 0 and j["assets"][0]["status"] == "ok"
      and j["assets"][0]["stage"] == "do" and j["assets"][0]["stageLabel"] and j["assets"][0]["purpose"] == "Seeds the demo menu", o)
c, o, e = shipm("playbook", "asset", "add", "scripts/seed_menu.py", "--stage", "do", "--purpose", "Seeds the demo menu", "--project", A)
check("add of an identical asset: unchanged, no new commit", c == 0 and "unchanged" in o, (c, o))
# a second asset, then edit the first: changed first in the list
check("add a second asset (docs, review)", shipm("playbook", "asset", "add", "docs/rtl-checklist.md", "--stage", "review", "--purpose", "RTL checks", "--project", A)[0] == 0)
(D / "scripts" / "seed_menu.py").write_text("print('seed 2')\n")
c, o, e = shipm("playbook", "asset", "list", "--project", A, "--json")
j = json.loads(o)
check("list: the changed asset comes first, with status changed", [r["status"] for r in j["assets"]] == ["changed", "ok"] and j["assets"][0]["path"] == "scripts/seed_menu.py" and j["changed"] == 1, o)
p = json.loads(shipm("report", "panel", "--project", A)[1])
check("panel: toolbox count/changed/assets, no sha in the rows", p["toolbox"]["count"] == 2 and p["toolbox"]["changed"] == 1 and p["toolbox"]["assets"][0]["status"] == "changed"
      and "sha256" not in p["toolbox"]["assets"][0] and set(p["toolbox"]["assets"][0]) == {"path", "stage", "stageLabel", "purpose", "status"}, p.get("toolbox"))
check("panel: caps flags", p["caps"] == {"toolbox": True, "interview": True, "aside": True, "unread": True, "release": True}, p.get("caps"))
c, o, e = shipm("playbook", "asset", "add", "scripts/seed_menu.py", "--stage", "do", "--purpose", "Seeds the demo menu", "--project", A)
check("re-sign (add again after a change): says re-signed, new sha stored", c == 0 and "re-signed" in o and json.loads((D / ".shipmiracle" / "playbook.json").read_text())["assets"][1]["sha256"] == hashlib.sha256(b"print('seed 2')\n").hexdigest(), (c, o, e))
check("re-sign: nothing is changed any more", json.loads(shipm("playbook", "asset", "list", "--project", A, "--json")[1])["changed"] == 0)
(D / "docs" / "rtl-checklist.md").unlink()
j = json.loads(shipm("playbook", "asset", "list", "--project", A, "--json")[1])
check("a deleted asset file shows as missing (first), not dropped", j["assets"][0]["status"] == "missing" and j["total"] == 2, j)
(D / "docs" / "rtl-checklist.md").write_text("# RTL\n")
c, o, e = shipm("playbook", "asset", "remove", "docs/rtl-checklist.md", "--project", A)
check("remove: exit 0, gone from the file and the list", c == 0 and json.loads(shipm("playbook", "asset", "list", "--project", A, "--json")[1])["total"] == 1, (c, o, e))
c, o, e = shipm("playbook", "asset", "remove", "docs/rtl-checklist.md", "--project", A)
check("remove of an absent asset: exit 3", c == 3, (c, e))
c, o, e = shipm("playbook", "asset", "remove", "scripts/seed_menu.py", "--project", A)
pb = json.loads((D / ".shipmiracle" / "playbook.json").read_text())
check("remove of the last asset leaves no assets key and the playbook still trusted", c == 0 and "assets" not in pb and json.loads(shipm("playbook", "show", "--project", A, "--json")[1])["trust"] == "trusted", (c, pb))

# refusals
for label, args in (("a missing file", ("nope.py",)), ("dotdot", ("../x",)), ("absolute", ("/etc/hosts",)), (".env", (".env",)), ("a key file", ("id_rsa",)), ("a folder", ("scripts",)),
                    ("inside .git", (".git/config",)), ("a symlink", ("scripts/link.py",)), ("inside .shipmiracle", (".shipmiracle/playbook.json",))):
    c, o, e = shipm("playbook", "asset", "add", *args, "--stage", "do", "--purpose", "x", "--project", A)
    check("add refuses %s" % label, c in (2, 4) and e.startswith("shipm: "), (c, e))
c, o, e = shipm("playbook", "asset", "add", "scripts/seed_menu.py", "--stage", "nonsense", "--purpose", "x", "--project", A)
check("add with an unknown stage: exit 2", c == 2, (c, e))
c, o, e = shipm("playbook", "asset", "add", "scripts/seed_menu.py", "--project", A)
check("add without --stage/--purpose: exit 2", c == 2, (c, e))
c, o, e = shipm("playbook", "asset", "frob", "--project", A)
check("asset with an unknown verb: exit 2", c == 2, (c, e))
before = (D / ".shipmiracle" / "playbook.json").read_bytes()
c, o, e = shipm("playbook", "asset", "add", "scripts/seed_menu.py", "--stage", "do", "--purpose", "x", "--project", A, extra={"CLAUDECODE": "1", "SHIPMIRACLE_ENFORCE_OWNER": "1"})
check("add inside a chat is refused (exit 4) and the file is untouched", c == 4 and (D / ".shipmiracle" / "playbook.json").read_bytes() == before, (c, e))
c, o, e = shipm("playbook", "asset", "list", "--project", A, "--json", extra={"CLAUDECODE": "1", "SHIPMIRACLE_ENFORCE_OWNER": "1"})
check("list is read-only and works inside a chat", c == 0, (c, e))
# a model that edits playbook.json by hand cannot add an asset: the file no longer matches the registry sha
pb = json.loads(before); pb["assets"] = [{"path": "scripts/seed_menu.py", "sha256": "b" * 64, "purpose": "evil", "stage": "do"}]
(D / ".shipmiracle" / "playbook.json").write_text(json.dumps(pb))
j = json.loads(shipm("playbook", "asset", "list", "--project", A, "--json")[1])
check("a hand-edited playbook.json with an asset is untrusted: the list stays empty", j["trust"] == "untrusted" and j["total"] == 0 and json.loads(shipm("report", "panel", "--project", A)[1])["toolbox"]["count"] == 0, j)
c, o, e = shipm("playbook", "asset", "add", "scripts/seed_menu.py", "--stage", "do", "--purpose", "x", "--project", A)
check("add refuses to sign into an untrusted playbook (exit 4)", c == 4 and "not trusted" in e, (c, e))
(D / ".shipmiracle" / "playbook.json").write_bytes(before)
# open chat blocks it, like playbook set
(STATE / "health.json").write_text(json.dumps({"ts": time.time(), "chats": {"alpha": {"chats": 1}}}))
c, o, e = shipm("playbook", "asset", "add", "scripts/seed_menu.py", "--stage", "do", "--purpose", "x", "--project", A)
check("add while a chat is open: refused (exit 4) unless --allow-open-chat", c == 4 and "chat" in e, (c, e))
c, o, e = shipm("playbook", "asset", "add", "scripts/seed_menu.py", "--stage", "do", "--purpose", "x", "--project", A, "--allow-open-chat")
check("add --allow-open-chat works", c == 0, (c, e))

# ---------------------------------------------------------------- typed confirmation (in process, the terminal seam)
os.environ["SHIPMIRACLE_ENFORCE_OWNER"] = "1"
from shipmiracle.playbook import cli as PB  # noqa: E402
def ns(**kw):
    d = dict(rargs=["add", "docs/rtl-checklist.md"], project=A, stage="review", purpose="RTL", allow_open_chat=True, json=False); d.update(kw); return types.SimpleNamespace(**d)
pb0 = (D / ".shipmiracle" / "playbook.json").read_bytes()
PB._tty_ask = lambda prompt: None
check("typed confirmation: no terminal = refused, nothing written", raises(SafetyError, PB.cmd_asset, ns()) and (D / ".shipmiracle" / "playbook.json").read_bytes() == pb0)
PB._tty_ask = lambda prompt: "yes"
check("typed confirmation: a wrong word = refused, nothing written", raises(SafetyError, PB.cmd_asset, ns()) and (D / ".shipmiracle" / "playbook.json").read_bytes() == pb0)
asked = []
PB._tty_ask = lambda prompt: asked.append(prompt) or "docs/rtl-checklist.md"
rc = PB.cmd_asset(ns())
check("typed confirmation: typing the path signs it; the prompt names the action", rc == 0 and asked and "asset add" in asked[0] and "docs/rtl-checklist.md" in asked[0]
      and any(x["path"] == "docs/rtl-checklist.md" for x in json.loads((D / ".shipmiracle" / "playbook.json").read_text())["assets"]), asked)
PB._tty_ask = lambda prompt: "docs/rtl-checklist.md"
rc = PB.cmd_asset(ns(rargs=["remove", "docs/rtl-checklist.md"]))
check("typed confirmation: remove needs the path typed too", rc == 0 and "docs/rtl-checklist.md" not in (D / ".shipmiracle" / "playbook.json").read_text())
PB._tty_ask = lambda prompt: None
check("typed confirmation: remove without a terminal is refused", raises(SafetyError, PB.cmd_asset, ns(rargs=["remove", "scripts/seed_menu.py"])))

# ---------------------------------------------------------------- guarded writer: a symlinked playbook.json is refused
os.environ.pop("SHIPMIRACLE_ENFORCE_OWNER", None)
(D / ".shipmiracle" / "playbook.json").unlink()
os.symlink(str(TMP / "elsewhere.json"), str(D / ".shipmiracle" / "playbook.json"))
c, o, e = shipm("playbook", "asset", "add", "docs/rtl-checklist.md", "--stage", "review", "--purpose", "RTL", "--project", A, "--allow-open-chat")
check("a symlinked playbook.json is never written through (exit nonzero, target not created)", c != 0 and not (TMP / "elsewhere.json").exists(), (c, e))

print("\nresult: %d failed" % fails)
ISO.cleanup(TMP)
sys.exit(1 if fails else 0)
