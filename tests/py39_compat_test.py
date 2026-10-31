#!/usr/bin/env python3
"""The Shipmiracle package (and bin/shipm once it exists) must parse as Python 3.9 and carry `from __future__ import annotations`.
Also catches `match` statements and X | Y annotations evaluated at runtime. Run: python3 tests/py39_compat_test.py"""
import ast, os, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
fails = 0
def check(name, ok, info=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(info)))
    fails += 0 if ok else 1

files = sorted((ROOT / "shipmiracle").glob("*.py")) + sorted((ROOT / "shipmiracle" / "hooks").glob("*.py")) + sorted((ROOT / "shipmiracle" / "playbook").glob("*.py"))
if (ROOT / "bin" / "shipm").is_file():
    files.append(ROOT / "bin" / "shipm")
check("found the Shipmiracle package files", len(files) >= 5, files)
for f in files:
    rel = str(f.relative_to(ROOT))
    src = f.read_text(encoding="utf-8")
    try:
        tree = ast.parse(src, filename=rel, feature_version=(3, 9))
    except SyntaxError as e:
        check("parses as Python 3.9: " + rel, False, e); continue
    check("parses as Python 3.9: " + rel, True)
    future = any(isinstance(n, ast.ImportFrom) and n.module == "__future__" and any(a.name == "annotations" for a in n.names) for n in tree.body)
    check("has `from __future__ import annotations`: " + rel, future)
    bad = [n.lineno for n in ast.walk(tree) if isinstance(n, getattr(ast, "Match", ()))]   # empty tuple when the parser has no Match
    check("no match statement: " + rel, not bad, bad)
# the check itself works: a 3.10 construct is rejected
try:
    ast.parse("match x:\n    case 1: pass\n", feature_version=(3, 9)); rejected = False
except SyntaxError:
    rejected = True
check("the 3.9 parse really rejects `match`", rejected)
print("\nFAILED: %d" % fails if fails else "\nALL PASS"); sys.exit(1 if fails else 0)
