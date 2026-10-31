#!/usr/bin/env python3
"""diffstat.evaluate runs its git reads in parallel (latency); results must equal the sequential path, including a missing base and a failing git."""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import shipmiracle_isolation; shipmiracle_isolation.apply_to_environ()   # test isolation: fresh HOME/SHIPMIRACLE_HOME/CONFIG/STATE unless already temp
import os, pathlib, subprocess, sys, tempfile
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["SHIPMIRACLE_TEST"] = "1"
from shipmiracle.playbook import diffstat as D  # noqa: E402

fails = 0
def check(n, ok):
    global fails
    print(("PASS " if ok else "FAIL ") + n); fails += 0 if ok else 1

d = pathlib.Path(tempfile.mkdtemp()) / "p"; d.mkdir()
g = lambda *a: subprocess.run(["git", "-C", str(d)] + list(a), check=True, capture_output=True)
g("init", "-q"); (d / "a.py").write_text("x\n"); g("add", "-A"); g("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "i")
base = D.head(d)
(d / "a.py").write_text("x\ny\nz\n"); (d / "new.py").write_text("1\n2\n")
r = D.evaluate(d, {"base": base, "untracked": []})
check("tracked + untracked counted", r["files"] == 2 and r["lines"] == 4)
check("untracked seen in snapshot is skipped", D.evaluate(d, {"base": base, "untracked": ["new.py"]})["files"] == 1)
r2 = D.evaluate(d, {"base": "0" * 40, "untracked": []})
check("missing base: measured against the empty tree (whole tree counts)", r2["files"] == 2 and r2["lines"] == 5)
try:
    D.evaluate(d / "nope", {"base": base, "untracked": []}); ok = False
except D.GitError:
    ok = True
check("git failure raises GitError", ok)
print("\n%s: %d failed" % ("FAIL" if fails else "ALL PASS", fails)); sys.exit(1 if fails else 0)
