#!/usr/bin/env python3
"""Project list parity: the panel's real data.js listProjectNames (run by node), the old bin/idea and bin/shipm-watch expression
(copied verbatim below) and shipmiracle.projects.names on the same fixture trees. The narrowings are asserted explicitly.
Run: python3 tests/projects_parity_test.py"""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import shipmiracle_isolation; shipmiracle_isolation.apply_to_environ()   # test isolation: fresh HOME/SHIPMIRACLE_HOME/CONFIG/STATE unless already temp
import json, os, pathlib, shutil, subprocess, sys, tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["SHIPMIRACLE_TEST"] = "1"
from shipmiracle import projects  # noqa: E402
if shutil.which("node") is None and sys.platform != "darwin":
    print("SKIP projects_parity_test: node is not installed here (the Linux container image is python-only by design); the panel side of the parity runs on the Mac and in CI")
    sys.exit(0)

fails = 0
def check(name, ok, info=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(info)))
    fails += 0 if ok else 1

# --- fixtures copied verbatim from the old code ---
def old_idea(DEV):          # bin/idea:241
    names = sorted(p.name for p in DEV.iterdir() if (p / ".git").exists())
    return names
def old_idea_guarded(DEV):  # bin/idea:301
    return sorted(p.name for p in DEV.iterdir() if (p / ".git").exists()) if DEV.exists() else []
def old_watch(DEV):         # bin/shipm-watch:226 (inside projects())
    try:
        return sorted(p.name for p in DEV.iterdir() if (p / ".git").exists())
    except Exception:
        return []

NODE = """
const path = require('path'); process.env.SHIPMIRACLE_TEST='1'; process.env.SHIPMIRACLE_EXT_STATE=process.argv[2]+'/state'; process.env.SHIPMIRACLE_EXT_DEV=process.argv[1]; process.env.SHIPMIRACLE_EXT_WS=process.argv[2]+'/ws';
const d = require(path.join(process.argv[3], 'vscode-ext/shipmiracle-panel/data.js'));
console.log(JSON.stringify(d.listProjectNames(process.argv[1])));
"""
def node_names(dev, scratch):
    r = subprocess.run(["node", "-e", NODE, str(dev), str(scratch), str(ROOT)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    if r.returncode != 0:
        return "node failed: " + r.stderr[-300:]
    return json.loads(r.stdout)

TMP = pathlib.Path(tempfile.mkdtemp(prefix="shipmiracle-par-"))
def mk(i, fn):
    base = TMP / ("c%d" % i); dev = base / "dev"; dev.mkdir(parents=True); fn(dev, base); return dev, base

def f_basic(dev, base):
    for n in ("alpha", "Beta", "zeta", "ünï"):
        (dev / n / ".git").mkdir(parents=True)
    (dev / "plainfile").write_text("x")
    (dev / "nogit").mkdir()
def f_dot(dev, base):                       # narrowing 1: dot-named with .git
    (dev / "a" / ".git").mkdir(parents=True); (dev / ".dot" / ".git").mkdir(parents=True); (dev / ".worktrees" / "a").mkdir(parents=True)
def f_nongit(dev, base):                    # narrowing 2: non-git folder with the workspace files (only sync-tools loop 1 took it)
    (dev / "x").mkdir(); (dev / "x" / "AGENTS.md").write_text("a"); (dev / "x" / ".claude").mkdir(); (dev / "x" / "docs").mkdir(); (dev / "x" / "docs" / "STATUS.md").write_text("s")
    (dev / "g" / ".git").mkdir(parents=True)
def f_link(dev, base):                      # symlink to a repo outside, broken symlink, .git file
    (base / "ext" / ".git").mkdir(parents=True); os.symlink(base / "ext", dev / "lnk"); os.symlink(base / "gone", dev / "broken")
    (dev / "gf").mkdir(); (dev / "gf" / ".git").write_text("gitdir: /x/.git/worktrees/y\n")
    (dev / "brokengit").mkdir(); os.symlink(base / "nowhere", dev / "brokengit" / ".git")
def f_empty(dev, base): pass
def f_many(dev, base):
    for i in range(40):
        (dev / ("p%02d" % i) / ".git").mkdir(parents=True)
    for n in ("B", "a", "_u", "-d", "A b"):
        (dev / n / ".git").mkdir(parents=True)

for i, (label, fn) in enumerate([("basic", f_basic), ("dot-named", f_dot), ("non-git", f_nongit), ("links", f_link), ("empty", f_empty), ("many", f_many)]):
    dev, base = mk(i, fn)
    new = projects.names(dev)
    nodes = node_names(dev, base)
    check("%s: panel (node data.js) list == Shipmiracle names" % label, isinstance(nodes, list) and sorted(nodes) == new, (nodes, new))
    nodot = [n for n in old_idea(dev) if not n.startswith(".")]
    check("%s: old bin/idea expression == Shipmiracle names (for every non-dot name)" % label, nodot == new, (nodot, new))
    check("%s: old bin/shipm-watch expression == bin/idea expression" % label, old_watch(dev) == old_idea(dev) == old_idea_guarded(dev))
    check("%s: Shipmiracle names == list_projects names" % label, new == [p.name for p in projects.list_projects(dev)])

# narrowings, explicit
dev = TMP / "c1" / "dev"
check("narrowing: old idea/watch listed the dot-named folder with .git, Shipmiracle and the panel never did",
      ".dot" in old_idea(dev) and ".dot" not in projects.names(dev) and ".dot" not in node_names(dev, TMP / "c1"))
dev = TMP / "c2" / "dev"
check("narrowing: a non-git folder with AGENTS.md/.claude/STATUS is not a project for anyone here (only sync-tools loop 1 looked at it)",
      projects.names(dev) == ["g"] and old_idea(dev) == ["g"] and node_names(dev, TMP / "c2") == ["g"])
dev = TMP / "c3" / "dev"
check("links: symlinked repo and .git file are listed; broken symlinks and a broken .git link are not",
      projects.names(dev) == ["gf", "lnk"], projects.names(dev))
check("missing folder: all of them give an empty list",
      projects.names(TMP / "nope") == [] and old_watch(TMP / "nope") == [] and old_idea_guarded(TMP / "nope") == [] and node_names(TMP / "nope", TMP) == [])
# the live-tree equality is covered by projects_live_test.py
shutil.rmtree(TMP, ignore_errors=True)
print("\nFAILED: %d" % fails if fails else "\nALL PASS"); sys.exit(1 if fails else 0)
