#!/usr/bin/env python3
"""shipmiracle/standard.py + docs/standards: base.md size and markers,
render and refresh of the managed block, on-demand files, the optional known-v1 folder.
Never touches the real state, config or projects (SHIPMIRACLE_TEST=1 + temp dirs). Run: python3 tests/standard_test.py (the migration and containment checks are in tests/private/standard_owner_test.py)"""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import shipmiracle_isolation; shipmiracle_isolation.apply_to_environ()   # test isolation: fresh HOME/SHIPMIRACLE_HOME/CONFIG/STATE unless already temp
import json, os, pathlib, re, shutil, stat, subprocess, sys, tempfile
os.environ.pop("CLAUDECODE", None)       # the owner check only runs in a fully temp sandbox or outside a chat (H1)

ROOT = pathlib.Path(__file__).resolve().parent.parent
TMP = pathlib.Path(tempfile.mkdtemp(prefix="shipmiracle-std-")).resolve()
os.environ.update(SHIPMIRACLE_TEST="1", SHIPMIRACLE_HOME=str(TMP / "home"), SHIPMIRACLE_STATE=str(TMP / "state"), SHIPMIRACLE_CONFIG=str(TMP / "config"),
                  SHIPMIRACLE_DEV=str(TMP / "dev"))
os.environ.pop("SHIPMIRACLE_WS", None)
sys.path.insert(0, str(ROOT))
from shipmiracle import SafetyError, UsageError, paths, projects, registry, standard, state  # noqa: E402

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
    except Exception as e:
        return "wrong exception %r" % e
    return False

STD = ROOT / "docs" / "standards"
BASE = (STD / "base.md").read_text(encoding="utf-8")

# ---- 1. base.md ----------------------------------------------------------------------------------
check("base.md is at most 4096 bytes (enforced)", len((STD / "base.md").read_bytes()) <= 4096, len((STD / "base.md").read_bytes()))
for need in ("Before any work", "The repo is the memory", "### 3. Modes", "Plan first", "Approval", "Plan on Opus", "just do it", "<= 10 lines",
             "verifier PASS", "Read on demand: docs/standards/*.md", "Quality gates", "Security and privacy", "scoper", "planner", "-frontend",
             "-backend", "-ops", "verifier", "reviewer", "designer", "aliases", "authorization to build", "Old names (product-analyst, solution-architect,", "still resolve as aliases", "CLAUDE.md, STATUS", "docs/standards/team.md"):
    if need not in BASE:
        check("base.md keeps the rule/word %r" % need, False)
check("base.md has every behaviour-gating keyword", all(n in BASE for n in ("Plan first", "Approval", "Plan on Opus", "just do it", "verifier PASS")))
for f in ["base.md"] + list(standard.ON_DEMAND):
    txt = (STD / f).read_text(encoding="utf-8")
    check("%s: Claude-only (no second engine, no AGENTS.md)" % f, not (re.search(r"(?i)co" + "dex", txt) or re.search(r"AGENTS", txt)))
check("all five on-demand files exist", all((STD / f).is_file() for f in standard.ON_DEMAND))
check("base.md names every on-demand file", all(n in BASE for n in ("team", "records", "skills", "ideas", "long-jobs")))

# ---- 2. render / markers / idempotence -------------------------------------------------------------
blk = standard.render(BASE)
check("render: starts with the v2 BEGIN marker, ends with the END marker",
      blk.startswith("<!-- SHIPMIRACLE-STANDARD BEGIN v2 (managed by shipm sync; edit AI-Workspace/docs/standards/base.md) -->\n") and blk.endswith("\n<!-- SHIPMIRACLE-STANDARD END -->\n"))
check("render: one BEGIN, one END, base text inside", blk.count("SHIPMIRACLE-STANDARD BEGIN") == 1 and blk.count("SHIPMIRACLE-STANDARD END") == 1 and BASE.strip("\n") in blk)
check("render is deterministic", standard.render(BASE) == blk)
doc = "# T\n\n" + blk + "\n## Project\nmine\n"
check("refresh with the same base is a no-op (idempotent)", standard.refresh(doc, BASE) == doc)
changed = standard.refresh(doc, "## Other\nline\n")
check("refresh replaces only the block", changed.startswith("# T\n\n<!-- SHIPMIRACLE-STANDARD BEGIN") and "## Other" in changed and "Before any work" not in changed and changed.endswith("## Project\nmine\n"), changed)
check("refresh of a text without block is unchanged", standard.refresh("# x\n", BASE) == "# x\n")
check("render refuses empty base and base with markers", raises(UsageError, standard.render, "  ") is True and raises(UsageError, standard.render, "a SHIPMIRACLE-STANDARD b") is True)
check("on_demand_files: managed header first line, five files", sorted(standard.on_demand_files()) == sorted(standard.ON_DEMAND)
      and all(t.startswith("<!-- managed by shipm sync from AI-Workspace/docs/standards/") for t in standard.on_demand_files().values()))

# the known-v1 folder is optional (absent in a public checkout)
NOWS = TMP / "nows"; (NOWS / "docs" / "standards").mkdir(parents=True)
check("known_lines: no docs/standards/known folder -> empty, no error", not standard.known_lines(NOWS))
(NOWS / "docs" / "standards" / "known").mkdir(); (NOWS / "docs" / "standards" / "known" / "ok.txt").write_text("- Line one\n\n- Line two\n", encoding="utf-8")
check("known_lines: a present folder still counts its lines", sum(standard.known_lines(NOWS).values()) == 2, standard.known_lines(NOWS))
check("registry has no built-in project names (EXCEPTIONS table is gone)", not hasattr(registry, "EXCEPTIONS"))

shutil.rmtree(TMP, ignore_errors=True)
print("\nFAILED: %d" % fails if fails else "\nALL PASS"); sys.exit(1 if fails else 0)
