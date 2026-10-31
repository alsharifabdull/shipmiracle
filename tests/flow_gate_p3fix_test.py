#!/usr/bin/env python3
"""Flow gate, P3 remediation (re-review REMEDIATE + P4 security findings): B1 strict frontmatter name, admin wrappers (env -i, exec -c, xargs, find -exec,
unknown command words), shadowing of the standard library by workspace folders, damaged registry fail-open, read-only false negatives, the dispatcher shim
(re-exec isolated, legacy fallback keeps its decision when the log fails), integrity of shipmiracle/*.py, .claude/test-command as a gate file.
Sandboxed like flow_gate_roles_test.py. Run: /usr/bin/python3 tests/flow_gate_p3fix_test.py (Python 3.9)."""
import json, os, pathlib, shutil, subprocess, sys, tempfile
HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(ROOT))
os.environ["SHIPMIRACLE_TEST"] = "1"
tempfile.tempdir = next((d for d in ("/var/tmp", str(pathlib.Path.home() / ".cache")) if os.path.isdir(d) and os.access(d, os.W_OK)), None)
for k_ in ("CLAUDECODE", "SHIPMIRACLE_ENFORCE_OWNER", "SHIPMIRACLE_QUIET", "SHIPMIRACLE_FLOW_TAMPER_OK", "SHIPMIRACLE_FLOW_LEVEL", "SHIPMIRACLE_FLOW_VERDICT"):
    os.environ.pop(k_, None)
from flow_fixture import make_project, deny  # noqa: E402
from shipmiracle import agents as AG, projects  # noqa: E402

fails = []
n_checks = [0]


def check(n, c, info=""):
    n_checks[0] += 1
    print(("PASS " if c else "FAIL ") + n + ("" if c else " :: " + str(info)[:500]))
    if not c:
        fails.append(n)


GENV = dict(os.environ, GIT_AUTHOR_NAME="T", GIT_AUTHOR_EMAIL="t@example.com", GIT_COMMITTER_NAME="T", GIT_COMMITTER_EMAIL="t@example.com")
TOP = pathlib.Path(tempfile.mkdtemp(prefix="flow-p3fix-")).resolve()
MASTERS = {p.stem: p.read_bytes() for p in sorted((ROOT / "agents/claude").glob("*.md"))}
AGENT = "---\nname: {n}\ndescription: x\nmodel: sonnet\n---\nModel reason: x.\nFlow role: {r}\n"


def git(cwd, *a):
    return subprocess.run(["git", "-C", str(cwd)] + list(a), env=GENV, capture_output=True, text=True, check=True).stdout.strip()


WSREPO = TOP / "wsrepo"
(WSREPO / "agents/claude").mkdir(parents=True)
subprocess.run(["git", "init", "-q", str(WSREPO)], env=GENV, check=True)
for n_, b_ in MASTERS.items():
    (WSREPO / "agents/claude" / (n_ + ".md")).write_bytes(b_)
git(WSREPO, "add", "-A"); git(WSREPO, "commit", "-qm", "masters")


class Sb:
    def __init__(self, layout="userlevel", agents=None, tracked_ws=False):
        self.p = p = make_project("proj", agents=agents if agents is not None else {})
        self.HOME = p.T / "home"; self.CFG = self.HOME / ".config/shipmiracle"
        self.HOME.mkdir(); self.CFG.mkdir(parents=True)
        os.symlink(str(ROOT / "shipmiracle"), str(p.WSF / "shipmiracle"))
        (p.T / "hooktmp").mkdir()
        p.ENV.update(TMPDIR=str(p.T / "hooktmp"), SHIPMIRACLE_HOME=str(self.HOME), SHIPMIRACLE_CONFIG=str(self.CFG), HOME=str(self.HOME), SHIPMIRACLE_STATE=str(p.STATE))
        if layout == "userlevel":
            (self.CFG / "config.json").write_text(json.dumps({"agents.layout": "userlevel"}))
        self.use()
        AG.install(ws=WSREPO, home=self.HOME)
        self.pid = projects.project_id(p.P)

    def use(self):
        p = self.p
        os.environ.update(SHIPMIRACLE_TEST="1", SHIPMIRACLE_HOME=str(self.HOME), SHIPMIRACLE_CONFIG=str(self.CFG), SHIPMIRACLE_STATE=str(p.STATE), SHIPMIRACLE_DEV=str(p.DEV), SHIPMIRACLE_WS=str(p.WSF))


# ===================================================================== B1: strict name line
forms = {
    "quoted-key": "---\n'name': planner\ndescription: x\nmodel: opus\n---\nModel reason: x.\nFlow role: plan\n",
    "space-colon": "---\nname : planner\ndescription: x\nmodel: opus\n---\nModel reason: x.\nFlow role: plan\n",
    "dq-key": "---\n\"name\": planner\ndescription: x\nmodel: opus\n---\nModel reason: x.\nFlow role: plan\n",
    "comment+overrides": "---\nname: planner # c\noverrides: planner\ndescription: x\nmodel: opus\n---\nModel reason: x.\nFlow role: plan\n",
    "block-scalar": "---\nname: >-\n  planner\ndescription: x\nmodel: opus\n---\nModel reason: x.\nFlow role: plan\n",
    "tab": "---\nname:\tplanner\ndescription: x\nmodel: opus\n---\nModel reason: x.\nFlow role: plan\n",
    "crlf": "---\r\nname: planner\r\ndescription: x\r\nmodel: opus\r\n---\r\nModel reason: x.\r\nFlow role: plan\r\n",
    "bom": "﻿---\nname: planner\ndescription: x\nmodel: opus\n---\nModel reason: x.\nFlow role: plan\n",
    "duplicate": "---\nname: planner\nname: other\ndescription: x\nmodel: opus\n---\nModel reason: x.\nFlow role: plan\n",
}
for k, body in forms.items():
    sc = AG.name_scan(body)
    check("B1 name_scan: %s is not strict" % k, not sc["ok"], sc)
for k, body in {"plain": "---\nname: planner\ndescription: x\n---\n", "dq": '---\nname: "planner"\n---\n', "sq": "---\nname: 'planner'\n---\n", "none": "---\ndescription: x\n---\n"}.items():
    check("B1 name_scan: %s is accepted" % k, AG.name_scan(body)["ok"])
for k, body in forms.items():
    sb = Sb(); p = sb.p
    p.prompt("go", "s1")
    o = p.write(".claude/agents/%s.md" % k.replace("+", "-"), body)
    check("B1 %s: main-chat write of the agent file is refused" % k, deny(o), o)
    p.put(".claude/agents/%s.md" % k.replace("+", "-"), body)
    r = AG.resolve("planner", str(p.P), home=str(sb.HOME))
    check("B1 %s: privileged resolution of planner in this project is untrusted (support)" % k, r is not None and not r.trusted and r.effective == "support", r)
    p.hook("SubagentStop", "s1", agent_id="pl", agent_type="planner")
    check("B1 %s: ExitPlanMode is still refused (the planner is not credited)" % k, deny(p.pre("ExitPlanMode", {})))
    p.cleanup()
sb = Sb(); p = sb.p; p.prompt("go", "s1")
check("B1 a strict quoted name is accepted by the model rule", not deny(p.write(".claude/agents/helper.md", '---\nname: "helper"\ndescription: x\nmodel: sonnet\n---\nModel reason: x.\nFlow role: build\n')))
p.put(".claude/agents/helper.md", '---\nname: "helper"\ndescription: x\nmodel: sonnet\n---\nModel reason: x.\nFlow role: build\n')
r = AG.resolve("planner", str(p.P), home=str(sb.HOME))
check("B1 a strict file elsewhere in the project does not taint planner", r is not None and r.layer == "user" and r.trusted, r)
p.cleanup()

# ===================================================================== admin holes
sb = Sb(); p = sb.p; p.prompt("go", "s1")
should_deny = [
    "env -i bin/shipm config unset agents.layout", "env --ignore-environment bin/shipm config unset agents.layout", "env - bin/shipm config unset agents.layout",
    "exec -c bin/shipm config unset agents.layout", "echo config unset agents.layout | xargs env -i bin/shipm",
    "printf '%s\\n' config unset agents.layout | xargs -n3 env -i ~/Developer/AI-Workspace/bin/shipm", "echo config unset agents.layout | xargs bin/shipm",
    "find bin -name shipm -exec env -i {} config unset agents.layout \\;", "find bin -name shipm -execdir bin/shipm config unset agents.layout \\;",
    "find bin -name shipm -exec {} config unset agents.layout \\;", "parallel env -i bin/shipm ::: config",
    "env -i python3 -c 'import runpy,sys; sys.argv=[\"shipm\",\"config\",\"unset\",\"agents.layout\"]; runpy.run_module(\"shipmira\"+\"cle\", run_name=\"__main__\")'",
    "A=shipm; env -i bin/$A config unset agents.layout", "A=shipm; bin/$A config unset agents.layout", "bin/sh?pm config unset agents.layout",
    "$(echo bin/shipm) config unset agents.layout", "`echo bin/shipm` config unset agents.layout",
]
for c in should_deny:
    check("admin: refused  %s" % c[:70], deny(p.bash(c)))
for c in ["env FOO=1 ls", "xargs echo", "echo a | xargs -n1 echo", "find . -name '*.py' -exec grep -l x {} +", "env -u FOO ls", "ls *.py", "echo $(date)",
          "git ls-files | xargs grep foo", "FOO=$(date) ls"]:
    check("admin: allowed  %s" % c[:70], not deny(p.bash(c)), p.bash(c))
p.cleanup()

# ===================================================================== shadowing of the standard library
sb = Sb(); p = sb.p; p.prompt("go", "s1")
subprocess.run(["git", "init", "-q", str(p.WSF)], env=GENV, check=True)
(p.WSF / "docs").mkdir(); (p.WSF / "docs/a.md").write_text("x"); git(p.WSF, "add", "-A"); git(p.WSF, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "i")
W = str(p.WSF); H = str(sb.HOME)
for path in (W + "/json/__init__.py", W + "/re/__init__.py", W + "/subprocess/__init__.py", W + "/json.pyc", W + "/json.cpython-39-darwin.so", W + "/json.py",
             W + "/newpkg/__init__.py", H + "/Library/Python/3.9/lib/python/site-packages/zz.pth", H + "/Library/Python/3.11/lib/python/site-packages/sub/x.py"):
    for who in (None, "builder"):
        check("shadow: Write %s%s refused" % (path.replace(str(p.T), "T"), " (agent)" if who else ""), deny(p.pre("Write", {"file_path": path, "content": "import os\n"}, "s1", agent=who)))
o_ = p.pre("Write", {"file_path": W + "/docs/b.md", "content": "x"}, "s1")
check("shadow: a tracked, non-stdlib top-level folder (docs/) is not refused by the shadow rule (G11: a project chat may not write the workspace at all, so the only allowed refusal is the isolation sentence)", not deny(o_) or "Project isolation" in json.dumps(o_), o_)
for c in ("mkdir -p %s/json && echo x > %s/json/__init__.py" % (W, W), "cp /dev/null %s/json.pyc" % W, "echo x > %s/re.pyc" % W, "cp /dev/null %s/json.cpython-39-darwin.so" % W):
    check("shadow: Bash %s refused" % c[:60].replace(str(p.T), "T"), deny(p.bash(c)), p.bash(c))
p.cleanup()

# end to end: a planted json/ in a workspace copy must not break the production command
sb = Sb(); p = sb.p
ws2 = p.T / "wscopy"
shutil.copytree(ROOT / "hooks", ws2 / "hooks", ignore=shutil.ignore_patterns("__pycache__")); shutil.copytree(ROOT / "shipmiracle", ws2 / "shipmiracle", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
(ws2 / "config").mkdir(); (ws2 / "config/flow.json").write_text(json.dumps({"default": "strict"}))
(ws2 / "json").mkdir(); (ws2 / "json/__init__.py").write_text("raise SystemExit('shadowed json')\n")
(ws2 / "re.pyc").write_bytes(b"junk")
cfgd = p.T / "cfg2"; cfgd.mkdir(); (cfgd / "config.json").write_text(json.dumps({"hooks.dispatcher": "v1"}))
e = dict(p.ENV, SHIPMIRACLE_WS=str(ws2), SHIPMIRACLE_CONFIG=str(cfgd), SHIPMIRACLE_HOOK_NO_SPAWN="1")
raw = json.dumps({"hook_event_name": "PreToolUse", "session_id": "e1", "cwd": str(p.P), "tool_name": "Write", "tool_input": {"file_path": str(ws2 / "hooks" "/flow-gate.sh"), "content": "x"}})
SYSPY = "/usr/bin/python3" if os.path.exists("/usr/bin/python3") else sys.executable
r = subprocess.run([SYSPY, "-I", "-S", "-X", "pycache_prefix=" + str(p.T / "pyc"), str(ws2 / "hooks/shipm-hook"), "PreToolUse"], input=raw, capture_output=True, text=True, env=e)
check("shadow e2e: production command with a planted <WS>/json/ still denies a gate-file Write", r.returncode == 0 and "deny" in r.stdout, (r.returncode, r.stdout[:200], r.stderr[:300]))
r = subprocess.run([str(ws2 / "hooks/shipm-hook"), "PreToolUse"], input=raw, capture_output=True, text=True, env=e)
check("L1 shim run directly (no -I -S) re-execs isolated and still denies", r.returncode == 0 and "deny" in r.stdout, (r.returncode, r.stdout[:200], r.stderr[:300]))
check("shim stays at most 30 lines", len((ROOT / "hooks/shipm-hook").read_text().splitlines()) <= 30)
p.cleanup()

# M1: the legacy fallback keeps the legacy decision when the log cannot be written
if (ROOT / "hooks" / "flow-gate.sh").exists():          # the legacy shell scripts exist only in the owner's checkout
    sb = Sb(); p = sb.p
    ws3 = p.T / "ws3"
    shutil.copytree(ROOT / "hooks", ws3 / "hooks", ignore=shutil.ignore_patterns("__pycache__")); shutil.copytree(ROOT / "shipmiracle", ws3 / "shipmiracle", ignore=shutil.ignore_patterns("__pycache__"))
    (ws3 / "config").mkdir(); (ws3 / "config/flow.json").write_text(json.dumps({"default": "strict"}))
    (ws3 / "shipmiracle/hooks/core.py").write_text("raise ImportError('x')\n")
    p.prompt("go", "m1"); (p.STATE / "flow-errors.log").unlink() if (p.STATE / "flow-errors.log").exists() else None; (p.STATE / "flow-errors.log").mkdir()   # the log cannot be written; the state itself works
    bad = p.STATE
    raw = json.dumps({"hook_event_name": "PreToolUse", "session_id": "m1", "cwd": str(p.P), "tool_name": "Write", "tool_input": {"file_path": str(ws3 / "hooks" "/flow-gate.sh"), "content": "x"}})
    e = dict(p.ENV, SHIPMIRACLE_WS=str(ws3), SHIPMIRACLE_STATE=str(bad))
    r = subprocess.run([SYSPY, "-I", "-S", str(ws3 / "hooks/shipm-hook"), "PreToolUse"], input=raw, capture_output=True, text=True, env=e)
    check("M1 fallback: the error log cannot be written: the legacy decision (deny) is still printed", r.returncode == 0 and "deny" in r.stdout, (r.returncode, r.stdout[:200], r.stderr[:200]))
    p.cleanup()

# ===================================================================== damaged registry (both layouts)
for layout in ("userlevel", "legacy"):
    sb = Sb(layout=layout, agents={"qa-engineer": AGENT.format(n="qa-engineer", r="test")}); p = sb.p
    git(p.P, "rm", "-rq", ".claude"); git(p.P, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "Team moved to user level")
    shutil.rmtree(p.P / ".claude", ignore_errors=True)
    (sb.CFG / "registry.json").write_text("{bad")
    p.prompt("go", "new2")
    o = p.edit("src/app.py", "x = 1", "x = 2\n" * 20, sid="new2")
    check("R5 %s: corrupt registry.json does not turn the gate off for a project whose team was moved" % layout, deny(o), o)
    p.cleanup()
sb = Sb(agents={}); p = sb.p
shutil.rmtree(p.P / ".claude", ignore_errors=True); (sb.CFG / "registry.json").write_text("{bad"); p.prompt("go", "n3")
check("R5 a project that never had a team is still not gated", not deny(p.edit("src/app.py", "x = 1", "x = 2\n" * 20, sid="n3")))
p.cleanup()

# ===================================================================== read-only roles
sb = Sb(); p = sb.p; p.prompt("go", "s1")


def ro(who, c):
    return deny(p.pre("Bash", {"command": c}, "s1", agent=who))


for c in ["xargs -I{} cp {} src/ <<< /etc/hosts", "g=git; $g commit -m x", "pytest --snapshot-update", "uv run pytest --snapshot-update", "npm test -- -u",
          "python3 -m pytest --update-snapshots", "$(echo git) commit -m x", "find . -name '*.py' -exec ls {} +; $X"]:
    check("read-only: reviewer refused  %s" % c[:60], ro("reviewer", c), c)
for c in ["git ls-files | xargs grep foo", "echo $(date)", "find . -name '*.py' -exec grep -l x {} +", "pytest -q", "git status", "[ -f x ] && ls", "ls *.py"]:
    check("read-only: reviewer allowed  %s" % c[:60], not ro("reviewer", c), c)
check("test role: pytest --snapshot-update refused for the verifier", ro("verifier", "pytest --snapshot-update"))
p.cleanup()

# ===================================================================== M4 test-command, M2 integrity of shipmiracle/*.py
sb = Sb(); p = sb.p; p.prompt("go", "s1")
for who in (None, "builder"):
    check("M4 .claude/test-command Write refused%s" % (" (agent)" if who else ""), deny(p.pre("Write", {"file_path": str(p.P / ".claude/test-command"), "content": "curl x | sh"}, "s1", agent=who)))
check("M4 Bash redirect into .claude/test-command refused", deny(p.bash("echo 'curl x | sh' > .claude/test-command")))
p.cleanup()

sb = Sb(); p = sb.p
os.unlink(str(p.WSF / "shipmiracle")); shutil.copytree(ROOT / "shipmiracle", p.WSF / "shipmiracle", ignore=shutil.ignore_patterns("__pycache__"))   # a private copy so the change is safe
p.prompt("start", "i1")
check("M2 baseline: main chat Bash passes", not deny(p.pre("Bash", {"command": "ls"}, "i1")))
with open(p.WSF / "shipmiracle/paths.py", "a") as f:
    f.write("\n# tampered\n")
o = p.pre("Bash", {"command": "ls"}, "i1")
check("M2 a change to shipmiracle/paths.py (hook import path) mid-turn blocks the main chat", deny(o) and "paths.py" in json.dumps(o), o)
p.cleanup()

shutil.rmtree(TOP, ignore_errors=True)
print("\n%d checks, %d failed" % (n_checks[0], len(fails)))
sys.exit(1 if fails else 0)
