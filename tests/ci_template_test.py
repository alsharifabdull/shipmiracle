#!/usr/bin/env python3
"""ci_template_test: checks templates/base/.github/workflows/ci.yml locally (no network, no GitHub).
Parses the workflow, checks the setup-node guards, runs the Detect and Build snippets with bash in temp dirs."""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import shipmiracle_isolation; shipmiracle_isolation.apply_to_environ()   # test isolation: fresh HOME/SHIPMIRACLE_HOME/CONFIG/STATE unless already temp
import os, re, shutil, subprocess, sys, tempfile, json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WF = ROOT / "templates/base/.github/workflows/ci.yml"
fails = []
def check(name, ok, info=""):
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else "  " + info))
    if not ok: fails.append(name)

def load_steps(text):
    try:
        import yaml
        doc = yaml.safe_load(text)
        return doc["jobs"]["test"]["steps"]
    except ImportError:
        pass
    if shutil.which("ruby"):
        r = subprocess.run(["ruby", "-ryaml", "-rjson", "-e", "puts JSON.generate(YAML.safe_load(STDIN.read)['jobs']['test']['steps'])"],
                           input=text, capture_output=True, text=True)
        if r.returncode == 0: return json.loads(r.stdout)
    if sys.platform != "darwin":
        print("SKIP ci_template_test: no YAML parser (PyYAML or ruby) in this environment (the Linux container image has neither; the Mac has ruby, the CI runners have both)")
        sys.exit(0)
    sys.exit("no YAML parser (PyYAML or ruby) available")

text = WF.read_text()
def load_doc(txt):
    try:
        import yaml; return yaml.safe_load(txt)
    except ImportError:
        r = subprocess.run(["ruby", "-ryaml", "-rjson", "-e", "puts JSON.generate(YAML.safe_load(STDIN.read))"], input=txt, capture_output=True, text=True)
        return json.loads(r.stdout)
steps = load_steps(text)
G_NVM = "steps.detect.outputs.kind == 'node' && hashFiles('.nvmrc') != ''"
G_LTS = "steps.detect.outputs.kind == 'node' && hashFiles('.nvmrc') == ''"
nodes = [s for s in steps if str(s.get("uses", "")).startswith("actions/setup-node")]
check("two setup-node steps", len(nodes) == 2, str(len(nodes)))
nvm = [s for s in nodes if s.get("if") == G_NVM]
lts = [s for s in nodes if s.get("if") == G_LTS]
check("nvmrc step has the exact guard", len(nvm) == 1)
check("lts step has the exact guard", len(lts) == 1)
if nvm and lts:
    check("nvmrc step: node-version-file .nvmrc, no node-version", nvm[0]["with"] == {"node-version-file": ".nvmrc"}, str(nvm[0]["with"]))
    check("lts step: node-version lts/*, no node-version-file", lts[0]["with"] == {"node-version": "lts/*"}, str(lts[0]["with"]))

def guard(expr, kind, has_nvmrc):
    """simulate the two plain guards: hashFiles(x) is '' when no file matches"""
    hf = "abc" if has_nvmrc else ""
    py = expr.replace("steps.detect.outputs.kind", repr(kind)).replace("hashFiles('.nvmrc')", repr(hf))
    py = py.replace("&&", " and ")
    return eval(py, {"__builtins__": {}})
for kind in ("node", "python", "none"):
    for has in (True, False):
        n = [guard(G_NVM, kind, has), guard(G_LTS, kind, has)].count(True)
        check(f"kind={kind} nvmrc={has}: {'exactly one' if kind=='node' else 'no'} node setup", n == (1 if kind == "node" else 0), str(n))

node_i = next(i for i, s in enumerate(steps) if s.get("name") == "Node tests")
run = steps[node_i]["run"]
check("build precedes npm test", run.index("npm run build --if-present") < run.index("npm test") and run.index("npx --no-install tsc -b") < run.index("npm test"))
check("build is in the tsconfig-references guard", "grep -q '\"references\"' tsconfig.json" in run)

# --- execute snippets with bash
detect = next(s for s in steps if s.get("id") == "detect")["run"]
build_lines = [l.strip() for l in run.splitlines() if l.strip().startswith("if [ -f tsconfig.json ]")]
check("one build snippet found", len(build_lines) == 1)
build = build_lines[0] if build_lines else "false"

tmp = Path(tempfile.mkdtemp(prefix="ci_tpl_"))
stubs = tmp / "stubs"; stubs.mkdir()
log = tmp / "argv.log"
for n in ("npx", "npm"):
    (stubs / n).write_text(f'#!/bin/bash\necho "{n} $*" >> "{log}"\nexit 0\n'); (stubs / n).chmod(0o755)
def sh(cmd, cwd, extra=None):
    env = dict(os.environ, PATH=f"{stubs}:{os.environ['PATH']}", GITHUB_OUTPUT=str(cwd / "out"))
    return subprocess.run(["bash", "-e", "-c", cmd], cwd=cwd, env=env, capture_output=True, text=True)
def project(name, files):
    d = tmp / name; d.mkdir()
    for f, c in files.items():
        (d / f).parent.mkdir(parents=True, exist_ok=True); (d / f).write_text(c)
    return d
def kind_of(d):
    r = sh(detect, d); o = (d / "out").read_text() if (d / "out").exists() else ""
    return r.returncode, o.strip()

cases = {
 "refs":   ({"package.json": '{"scripts":{"test":"x"}}', "tsconfig.json": '{"references":[{"path":"a"}]}'}, "kind=node", "npx --no-install tsc -b"),
 "build":  ({"package.json": '{"scripts":{"test":"x","build":"y"}}', "tsconfig.json": '{}'}, "kind=node", "npm run build --if-present"),
 "nobuild":({"package.json": '{"scripts":{"test":"x"}}'}, "kind=node", "npm run build --if-present"),
}
for name, (files, kind, expect) in cases.items():
    d = project(name, files); log.write_text("")
    rc, k = kind_of(d)
    check(f"{name}: detect -> {kind}", rc == 0 and k == kind, f"{rc} {k}")
    r = sh(build, d)
    got = log.read_text().strip().splitlines()
    check(f"{name}: build runs '{expect}' and exits 0", r.returncode == 0 and got == [expect], f"{r.returncode} {got} {r.stderr}")
    if name == "refs":
        check("refs: npm build not used", not any(l.startswith("npm") for l in got))
    else:
        check(f"{name}: tsc not used", not any(l.startswith("npx") for l in got))
# hardening checks
check("top-level permissions: contents: read", load_doc(text).get("permissions") == {"contents": "read"})
co = [s for s in steps if str(s.get("uses", "")).startswith("actions/checkout")]
check("checkout has persist-credentials: false", len(co) == 1 and co[0].get("with", {}).get("persist-credentials") is False, str(co))
check("no bare 'npx tsc'", not re.search(r"npx\s+tsc", run) and "npx --no-install tsc -b" in run)
check("npm ci uses explicit if/else (no && || fallback)", "if [ -f package-lock.json ]; then npm ci; else npm install; fi" in run and "npm ci || " not in run)
# stub npx that behaves like --no-install with tsc missing: fails unless --no-install is given AND tsc exists
(stubs / "npx").write_text('#!/bin/bash\necho "npx $*" >> "%s"\n[ "$1" = "--no-install" ] || { echo "would download $2" >&2; exit 0; }\necho "npx: tsc not installed" >&2; exit 1\n' % log)
d = project("notsc", cases["refs"][0]); log.write_text("")
r = sh(build, d)
check("missing local tsc: step fails with clear message, no download", r.returncode != 0 and "tsc not found" in (r.stdout + r.stderr) and "would download" not in r.stderr, f"{r.returncode} {r.stdout}{r.stderr}")
d = project("py", {"pyproject.toml": "[project]\n"}); rc, k = kind_of(d)
check("python-only: kind=python (no node steps)", rc == 0 and k == "kind=python", k)
d = project("empty", {}); rc, k = kind_of(d)
check("empty: kind=none", rc == 0 and k == "kind=none", k)
shutil.rmtree(tmp, ignore_errors=True)

# --- optional regression vs a reference workflow of a real project. Opt-in: SHIPMIRACLE_CI_REFERENCE=/path/to/ci.yml. It is not part of the default run because the
# reference is a file outside this repository that its own project keeps changing (it drifted on 24 Oct: newer checkout action, Node 22, ci:local) and a test must
# never read the owner's real home; an exported tree has no such file at all.
REF = Path(os.environ["SHIPMIRACLE_CI_REFERENCE"]) if os.environ.get("SHIPMIRACLE_CI_REFERENCE") else None
if REF is not None and os.access(REF, os.R_OK):
    # lines that are meant to differ: the node setup + build lines (and their comments); everything else must be identical
    intended = ("setup-node", "node-version", "tsc -b", "npm run build", "# Build before", "# references", "the workspace packages",
               "permissions:", "contents: read", "persist-credentials", "package-lock.json", "deliberately unpinned")  # hardening, deliberately ahead of the reference
    keep = lambda txt: [l for l in txt.splitlines() if l.strip() and not any(x in l for x in intended)]
    ka, kb = keep(text), keep(REF.read_text())
    # the reference's single 'if: ... kind == node' lines for setup-node/Node tests exist in both; the template has one extra guarded line
    extra = [l for l in ka if l not in kb]
    check("template matches the reference outside the intended lines", all("hashFiles('.nvmrc')" in l or l.strip().startswith("if [ -f tsconfig") for l in extra), str(extra))
    missing = [l for l in kb if l not in ka]
    check("nothing from the reference is lost", not missing, str(missing))
else:
    print("SKIP reference comparison (opt-in: set SHIPMIRACLE_CI_REFERENCE to a reference ci.yml)")

print(f"\n{'FAILED: ' + ', '.join(fails) if fails else 'ALL PASS'}")
sys.exit(1 if fails else 0)
