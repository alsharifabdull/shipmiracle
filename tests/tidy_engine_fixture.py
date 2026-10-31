#!/usr/bin/env python3
"""Real-engine fixtures for tests/panel_v3_tidy_test.js: runs the engine's OWN writer (shipmiracle.tidyweekly.run) over fake scans and prints what it wrote.
Input (stdin, JSON): {"<scenario>": [{"date": "YYYY-MM-DD", "hour": 12, "projects": [{"name", "disposable", "regenerable", "review", "idle", "partial"}]}, ...]}  (steps oldest first;
a step with "skip": true makes the scan fn raise for that step's projects = skipped project, partial scan).
Output (stdout, JSON): {"<scenario>": {"doc": <the tidy.json envelope as written>, "condition": <the engine's own condition>}}.
Regenerate by running: echo '{...}' | python3 tests/tidy_engine_fixture.py   (the node test does it for you). No file outside a temp folder is touched."""
import datetime, json, os, pathlib, sys, tempfile, types

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from shipmiracle import tidyweekly as tw  # noqa: E402


def rep(p):
    regen = p.get("regenerable", 0)
    return {"project": p["name"], "git": True, "partial": bool(p.get("partial")), "idle_days": p.get("idle", 30),
            "counts": {"regenerable": 1 if regen else 0, "disposable": 1 if p.get("disposable") else 0, "review": 1 if p.get("review") else 0, "never": 0},
            "bytes": {"regenerable": regen, "disposable": p.get("disposable", 0), "review": p.get("review", 0), "never": 7}}


def main():
    spec = json.load(sys.stdin)
    out = {}
    for name, steps in spec.items():
        base = tempfile.mkdtemp(prefix="tidyfx-")
        res = None
        for st in steps:
            d = datetime.datetime.strptime(st["date"], "%Y-%m-%d").replace(hour=st.get("hour", 12), tzinfo=datetime.timezone.utc)
            now = d.timestamp()
            projs = [types.SimpleNamespace(name=p["name"], real="/nonexistent/" + p["name"]) for p in st["projects"]]
            by = {pp.real: p for pp, p in zip(projs, st["projects"])}

            def scan_fn(root, max_seconds=None, now=None, by=by, skip=st.get("skip")):
                if skip:
                    raise RuntimeError("skipped")
                return rep(by[root])
            res = tw.run(True, False, now=now, base=base, scan_fn=scan_fn, projects_fn=lambda projs=projs: projs)
        env = json.loads((pathlib.Path(base) / "v1" / "tidy.json").read_text())
        out[name] = {"doc": env, "condition": res["condition"], "has_schema": "schema" in env["data"]}
    json.dump(out, sys.stdout)


if __name__ == "__main__":
    main()
