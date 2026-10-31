#!/usr/bin/env python3
"""Tests for bin/gate-deny. Temp settings files only; never touches ~/.claude."""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import shipmiracle_isolation; shipmiracle_isolation.apply_to_environ()   # test isolation: fresh HOME/SHIPMIRACLE_HOME/CONFIG/STATE unless already temp
import json, os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.join(HERE, "..", "bin", "gate-deny")
sys.path.insert(0, os.path.join(HERE, "..", "bin"))
RULES, ENGINE, PROJECTS = json.loads(subprocess.run(
    [sys.executable, "-c", "import importlib.machinery as m,sys;mod=m.SourceFileLoader('gd',sys.argv[1]).load_module();import json;print(json.dumps([mod.RULES, mod.ENGINE, mod.PROJECTS]))", BIN],
    capture_output=True, text=True).stdout)
fails = 0


def res(ok, name):
    global fails
    print(("PASS " if ok else "FAIL ") + name)
    fails += 0 if ok else 1


def run(cmd, path):
    return subprocess.run([sys.executable, BIN, cmd, "--settings", path], capture_output=True, text=True)


def rd(p):
    return json.load(open(p))


tmp = tempfile.mkdtemp()
res(len(RULES) == 18 and RULES[0] == "Edit(~/.claude/settings.json)" and RULES[10] == "Edit(~/.local/state/shipmiracle/*)" and RULES[14] == "Edit(~/.local/state/shipmiracle/v1/**)", "rule list has 18 rules in order (11 + the four Phase 3b rules + the two Phase 5 .shipmiracle rules + the engine link folder rule)")
res(RULES[15:17] == ["Edit(~/Developer/*/.shipmiracle/**)", "Edit(**/.shipmiracle/**)"], "Phase 5 T4: .shipmiracle deny rules present")
res(RULES[17] == "Edit(~/.local/share/shipmiracle/**)" and RULES[-1] == RULES[17], "F6: the engine link folder ~/.local/share/shipmiracle has a native deny rule (gate_dirs lists it), last in the list")

# missing file
p = os.path.join(tmp, "new", "s.json")
r = run("install", p)
res(r.returncode == 0 and rd(p)["permissions"]["deny"] == RULES, "missing file: created with all rules in order")
# idempotent
before = open(p).read()
r = run("install", p)
res(r.returncode == 0 and open(p).read() == before and all(rd(p)["permissions"]["deny"].count(x) == 1 for x in RULES), "idempotent: one copy each")
res(run("check", p).returncode == 0, "check passes when complete")

# empty {}
p = os.path.join(tmp, "e.json"); open(p, "w").write("{}")
run("install", p)
res(rd(p) == {"permissions": {"deny": RULES}}, "empty {}: structure created")

# keeps existing
p = os.path.join(tmp, "k.json")
orig = {"model": "x", "permissions": {"allow": ["Bash(ls)"], "ask": ["Bash(rm*)"], "deny": ["Read(~/.ssh/**)", RULES[2]], "defaultMode": "plan"}, "hooks": {"Stop": []}}
json.dump(orig, open(p, "w"))
run("install", p)
d = rd(p)
exp = ["Read(~/.ssh/**)", RULES[2]] + [x for x in RULES if x != RULES[2]]
res(d["permissions"]["deny"] == exp, "existing deny rules kept first, in order; only missing appended")
res(all(d[k] == orig[k] for k in ("model", "hooks")) and d["permissions"]["allow"] == ["Bash(ls)"] and d["permissions"]["ask"] == ["Bash(rm*)"] and d["permissions"]["defaultMode"] == "plan", "allow/ask/other keys untouched")

# malformed
for name, txt in (("bad", "{not json"), ("arr", "[1]")):
    p = os.path.join(tmp, name + ".json"); open(p, "w").write(txt)
    r = run("install", p)
    res(r.returncode == 2 and open(p).read() == txt, "%s file: exit 2, untouched" % name)
p = os.path.join(tmp, "pd.json"); open(p, "w").write('{"permissions": {"deny": "x"}}')
r = run("install", p)
res(r.returncode == 2 and open(p).read() == '{"permissions": {"deny": "x"}}', "deny not a list: exit 2, untouched")

# check finds missing
p = os.path.join(tmp, "c.json")
json.dump({"permissions": {"deny": RULES[:-1]}}, open(p, "w"))
r = run("check", p)
res(r.returncode == 1 and "missing: " + RULES[-1] in r.stdout and "missing: " + RULES[0] not in r.stdout, "check finds the one missing rule (exit 1)")
p2 = os.path.join(tmp, "nofile.json")
res(run("check", p2).returncode == 1 and not os.path.exists(p2), "check on a missing file: exit 1, nothing created")

# remove
p = os.path.join(tmp, "r.json")
json.dump({"a": 1, "permissions": {"allow": ["x"], "deny": ["Read(~/.ssh/**)"] + RULES + ["Bash(rm -rf*)"]}}, open(p, "w"))
run("remove", p)
res(rd(p) == {"a": 1, "permissions": {"allow": ["x"], "deny": ["Read(~/.ssh/**)", "Bash(rm -rf*)"]}}, "remove deletes exactly ours")
p = os.path.join(tmp, "r2.json"); run("install", p); run("remove", p)
res(rd(p) == {"permissions": {"deny": []}}, "remove leaves an empty deny list")
res(not [f for f in os.listdir(tmp) if f.startswith(".gate-deny")], "no temp files left")

# ensure_ascii=False: non-ASCII text in other keys stays readable
p = os.path.join(tmp, "u.json")
open(p, "w", encoding="utf-8").write('{"note": "مرحبا é"}')
run("install", p)
raw = open(p, encoding="utf-8").read()
res("مرحبا é" in raw and "\\u" not in raw, "non-ASCII kept as written (ensure_ascii=False)")

# --auto honours the opt-out marker
off = os.path.join(tmp, "gate-deny.off"); open(off, "w").write("")
p = os.path.join(tmp, "o.json")
env = dict(os.environ, SHIPMIRACLE_GATE_DENY_OFF=off)
r = subprocess.run([sys.executable, BIN, "install", "--auto", "--settings", p], capture_output=True, text=True, env=env)
res(r.returncode == 0 and not os.path.exists(p) and "switched off" in r.stdout, "install --auto skipped when the opt-out file exists")
r = subprocess.run([sys.executable, BIN, "check", "--auto", "--settings", p], capture_output=True, text=True, env=env)
res(r.returncode == 0 and "switched off" in r.stdout, "check --auto exits 0 with the info text when switched off")
r = subprocess.run([sys.executable, BIN, "install", "--auto", "--settings", p], capture_output=True, text=True, env=dict(os.environ, SHIPMIRACLE_GATE_DENY_OFF=off + ".none"))
res(r.returncode == 0 and os.path.exists(p), "install --auto installs when the opt-out file is absent")
r = subprocess.run([sys.executable, BIN, "install", "--settings", os.path.join(tmp, "o2.json")], capture_output=True, text=True, env=env)
res(os.path.exists(os.path.join(tmp, "o2.json")), "plain install ignores the opt-out file (owner is explicit)")


# new rules present
res(all(x in RULES for x in ("Edit(%s/config/gate-deny.off)" % ENGINE, "Edit(%s/bin/gate-deny)" % ENGINE, "Edit(%s/bin/shipm-chat)" % ENGINE,
    "Edit(%s/*/.claude/settings.json)" % PROJECTS, "Edit(%s/*/.claude/settings.local.json)" % PROJECTS, "Edit(%s/*/.claude/hooks/**)" % PROJECTS)), "self-protection and project .claude rules in the list")

# Phase 3b rules (user-level team, config folder, engine, v1 state)
res(RULES[11:15] == ["Edit(~/.claude/agents/**)", "Edit(~/.config/shipmiracle/**)", "Edit(%s/shipmiracle/**)" % ENGINE, "Edit(~/.local/state/shipmiracle/v1/**)"]
    and "Edit(%s/hooks/**)" % ENGINE in RULES and len(set(RULES)) == len(RULES), "Phase 3b deny rules present, hooks rule kept, no duplicates")
p = os.path.join(tmp, "p3b.json")
json.dump({"permissions": {"deny": RULES[:11]}}, open(p, "w"))
r = run("check", p)
res(r.returncode == 1 and all("missing: " + x in r.stdout for x in RULES[11:]), "a settings file with only the first 11 rules: check names the six new ones")
run("install", p)
res(rd(p)["permissions"]["deny"] == RULES and run("check", p).returncode == 0, "install over the 11-rule list appends exactly the four new rules")

# old generation migration
OLD = ["Edit(~/.local/state/shipmiracle/*.json)", "Edit(~/.local/state/shipmiracle/*.jsonl)", "Edit(~/.local/state/shipmiracle/*.lock)", "Edit(~/.local/state/shipmiracle/plan-pending.*)"]
p = os.path.join(tmp, "old.json")
json.dump({"permissions": {"deny": ["Read(~/.ssh/**)"] + RULES[:4] + OLD + ["Bash(rm -rf*)"]}}, open(p, "w"))
r = run("install", p)
dl = rd(p)["permissions"]["deny"]
res(not any(o in dl for o in OLD) and dl[0] == "Read(~/.ssh/**)" and "Bash(rm -rf*)" in dl and all(dl.count(x) == 1 for x in RULES), "install over old generation: old state rules dropped, others kept")
res(dl[:5] == ["Read(~/.ssh/**)"] + RULES[:4] and dl[-1] == RULES[-1], "old-generation install keeps order, appends new")
b4 = open(p).read(); run("install", p)
res(open(p).read() == b4, "migration is idempotent")
p = os.path.join(tmp, "oldonly.json")
json.dump({"permissions": {"deny": RULES[:-1] + OLD}}, open(p, "w"))
res(run("check", p).returncode == 1, "check: complete new list needed")
json.dump({"permissions": {"deny": RULES + OLD}}, open(p, "w"))
res(run("check", p).returncode == 0, "check: extra old rules are not an error")
json.dump({"permissions": {"deny": ["Read(~/.ssh/**)"] + OLD + RULES}}, open(p, "w"))
run("remove", p)
res(rd(p) == {"permissions": {"deny": ["Read(~/.ssh/**)"]}}, "remove deletes both generations")

# symlinked settings file stays a symlink
real = os.path.join(tmp, "realdir"); os.makedirs(real)
open(os.path.join(real, "s.json"), "w").write("{}")
link = os.path.join(tmp, "link.json"); os.symlink(os.path.join(real, "s.json"), link)
run("install", link)
res(os.path.islink(link) and rd(os.path.join(real, "s.json"))["permissions"]["deny"] == RULES and not [f for f in os.listdir(tmp) if f.startswith(".gate-deny")], "symlinked settings stays a symlink, target updated")

# concurrent change between read and replace is retried
import importlib.machinery as _m
mod = _m.SourceFileLoader("gd2", BIN).load_module()
p = os.path.join(tmp, "race.json"); json.dump({"model": "a"}, open(p, "w"))
calls = []
def hook():
    if not calls:
        calls.append(1)
        json.dump({"model": "a", "added_meanwhile": True}, open(p, "w"), indent=4)
mod._TEST_HOOK = hook
rc = mod.main(["install", "--settings", p])
d = rd(p)
res(rc == 0 and d.get("added_meanwhile") is True and d["permissions"]["deny"] == RULES and len(calls) == 1, "change between read and replace: retried, concurrent edit kept")
p2 = os.path.join(tmp, "race2.json"); open(p2, "w").write("{}")
mod._TEST_HOOK = lambda: open(p2, "a").write(" ")
try:
    mod.main(["install", "--settings", p2]); ok = False
except SystemExit as e:
    ok = e.code == 2 and open(p2).read().strip() == "{}"
res(ok, "file that keeps changing: exit 2 after 3 tries")
mod._TEST_HOOK = None

print("all checks done, %d failures" % fails)
sys.exit(1 if fails else 0)
