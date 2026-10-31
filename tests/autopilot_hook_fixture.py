"""Shared world for the P6 T4 suites (tests/autopilot_hook_test.py, tests/keep_going_away_test.py). Not a test: test-all only runs *_test.py.
Importing it builds a temp HOME / DEV / STATE / config / workspace (SHIPMIRACLE_TEST=1), a `sandbox` software project with a team-less trusted playbook
(autopilot full), CRs 001-003, a fresh plan.json, and rewrites os.environ for this process. `World.start()` sets a charter through a real
UserPromptSubmit, starts it with the owner CLI (`--yes --ack`) and has the worktree created by `shipm autopilot start` (P6 T5). Nothing real is touched."""
import json, os, pathlib, subprocess, sys, tempfile, time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = pathlib.Path(tempfile.mkdtemp(prefix="aphook-")).resolve()
HOME, DEV, STATE, CONF, WS = (TMP / n for n in ("home", "dev", "state", "config", "ws"))
BASE_PATH = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
ENV = dict(os.environ, SHIPMIRACLE_TEST="1", SHIPMIRACLE_HOME=str(HOME), SHIPMIRACLE_DEV=str(DEV), SHIPMIRACLE_STATE=str(STATE), SHIPMIRACLE_CONFIG=str(CONF), SHIPMIRACLE_WS=str(WS), HOME=str(HOME), PATH=BASE_PATH)
for k in ("SHIPMIRACLE_DEBUG", "CLAUDECODE", "SHIPMIRACLE_ENFORCE_OWNER", "SHIPMIRACLE_QUIET", "SHIPMIRACLE_GATE_ENGINE", "SHIPMIRACLE_HOOK_INJECT", "SHIPMIRACLE_HOOK_NO_SPAWN", "SHIPMIRACLE_STAGE_REPLAY", "CLAUDE_PROJECT_DIR",
          "SHIPMIRACLE_FLOW_LEVEL", "SHIPMIRACLE_FLOW_VERDICT", "SHIPMIRACLE_HOOK_NO_LOAD", "SHIPMIRACLE_TEST_NOW", "CLAUDE_CODE_ENTRYPOINT", "SHIPMIRACLE_HOOK_CAPTURE"):
    ENV.pop(k, None)
os.environ.clear()
os.environ.update(ENV)
SCRATCH = TMP / "scratch"                         # the only place the hook treats as "tmp" (the whole fixture world lives under the system tmp folder)
for d in (HOME, DEV, STATE, CONF, WS / "config", SCRATCH):
    d.mkdir(parents=True, exist_ok=True)
(HOME / ".gitconfig").write_text("[user]\n name = t\n email = t@example.com\n[init]\n defaultBranch = main\n[commit]\n gpgsign = false\n")
(WS / "config" / "flow.json").write_text('{"default": "strict", "projects": {}}')
FLOWJ = WS / "config" / "flow.json"
(STATE / "health.json").write_text(json.dumps({"ts": time.time(), "chats": {"sandbox": {"chats": 0}}}))

from shipmiracle.hooks import core  # noqa: E402
from shipmiracle.hooks import autopilot as AP  # noqa: E402  (registers into the untrimmed table; the test-only overrides are module attributes, never env vars)
from shipmiracle import config, projects, registry  # noqa: E402
from shipmiracle.autopilot import state as S  # noqa: E402
from shipmiracle.playbook import engine, store  # noqa: E402

MAIN = DEV / "sandbox"
WT = DEV / ".worktrees" / "sandbox" / "auto-CR-001"
PID = projects.project_id(str(MAIN))
URL = "https://github.com/owner/sandbox.git"
LINE = 'charter: goal="ship login"; scope="src/**,tests/**,docs/**,package.json"; budget=10%; time=3h; deps=none; ends=CR-001..CR-003'
CHAIN_OK = "claude,zsh,login"


def sh(args, cwd=None, env=None):
    r = subprocess.run(args, env=env or ENV, cwd=cwd, capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)
    return r.returncode, r.stdout, r.stderr


def git(d, *a):
    code, out, err = sh(["git", "-C", str(d)] + list(a))
    if code:
        raise SystemExit("git %s failed: %s %s" % (a, out, err))
    return out


def shipm(*args):
    return sh([sys.executable, str(ROOT / "bin" / "shipm")] + list(args))


def now():
    return float(os.environ.get("SHIPMIRACLE_TEST_NOW") or time.time())


RESETS = int(time.time()) + 3 * 86400            # the weekly window of the fixture world: fixed, so a fake clock does not look like a week reset


def write_plan(pct=34, resets=None, age=0, seven=True):
    n = now()
    resets = resets if resets is not None else RESETS
    rl = {"five_hour": {"used_percentage": 5, "resets_at": resets - 10}}
    if seven:
        rl["seven_day"] = {"used_percentage": pct, "resets_at": resets}
    (STATE / "plan.json").write_text(json.dumps({"at": int(n) - age, "rate_limits": rl, "model": "x"}))


class chain:
    """Fake `ps` ancestry for the hook under test (module attribute, like a patched subprocess.run): comma separated comm names, nearest first."""
    def __init__(self, names):
        self.names = [x for x in names.split(",") if x]

    def __enter__(self):
        self.old = AP._PS_CHAIN_OVERRIDE
        AP._PS_CHAIN_OVERRIDE = self.names

    def __exit__(self, *a):
        AP._PS_CHAIN_OVERRIDE = self.old


class env_set:
    """Temporarily set/unset os.environ keys."""
    def __init__(self, **kv):
        self.kv, self.old = kv, {}

    def __enter__(self):
        for k, v in self.kv.items():
            self.old[k] = os.environ.get(k)
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def __exit__(self, *a):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def build_world():
    MAIN.mkdir(parents=True)
    (MAIN / "src" / "login").mkdir(parents=True)
    for i in range(7):
        (MAIN / "src" / "login" / ("f%d.py" % i)).write_text("x%d = %d\n" % (i, i))
    (MAIN / "src" / "app.py").write_text("print('hi')\n")
    (MAIN / "tests").mkdir()
    (MAIN / "tests" / "test_app.py").write_text("def test_a():\n    assert True\n")
    (MAIN / "docs").mkdir()
    (MAIN / "docs" / "STATUS.md").write_text("Updated: 2020-01-01\n")
    (MAIN / "docs" / "DECISIONS.md").write_text("# decisions\n")
    (MAIN / "docs" / "guide.md").write_text("guide\n")
    (MAIN / "README.md").write_text("readme\n")
    (MAIN / "package.json").write_text('{"name": "sandbox", "scripts": {"build": "echo build"}}\n')
    (MAIN / ".gitignore").write_text("*.log\nnode_modules/\n")
    git(MAIN, "init", "-q")
    git(MAIN, "add", "-A")
    git(MAIN, "commit", "-qm", "init")
    for k, v in (("hooks.dispatcher", "v1"), ("gate.engine", "playbook"), ("autopilot.full.enabled", "on")):
        config.set(k, v)
    code, out, err = shipm("playbook", "set", "type", "software", "--project", "sandbox", "--allow-open-chat")
    assert code == 0, (out, err)
    for t in ("one", "two", "three"):
        shipm("cr", "open", t, "--project", str(MAIN))
    code, out, err = shipm("playbook", "set", "autopilot", "full", "--project", "sandbox", "--allow-open-chat")
    assert code == 0, (out, err)
    write_plan(34)


AP._TMP_ROOTS_OVERRIDE = [str(SCRATCH)]
ONLY = ["autopilot"]
ORIG = {k: list(v) for k, v in core.PIPELINES.items()}      # the full table, taken before any trimming (the same Slot objects get their fn when a module loads)


def reset_core(only=None):
    """Only the module(s) under test stay in the pipelines (the others have their own suites and side effects). hardstop imports shipmiracle.hooks.flow, which
    registers the flow slot again, so hook() trims on every call."""
    if only is not None:
        ONLY[:] = list(only)
    for _ev, _slots in ORIG.items():
        core.PIPELINES[_ev] = [s for s in _slots if s.name in ONLY]


def hook(event, cwd=None, project_dir=None, sid="sess0001abc", **kw):
    """One dispatcher call in this process: (parsed stdout dict, stderr text, exit code)."""
    core._FILES.clear()
    reset_core()
    d = {"hook_event_name": event, "session_id": sid, "cwd": str(cwd or WT)}
    d.update(kw)
    with env_set(CLAUDE_PROJECT_DIR=str(project_dir or cwd or WT)):
        out, err, code = core.run(event, json.dumps(d).encode())
    return (json.loads(out) if out.strip() else {}), err.decode("utf-8", "replace"), code


def denied(r):
    o = r[0].get("hookSpecificOutput") or {}
    return o.get("permissionDecision") == "deny", o.get("permissionDecisionReason", "")


def events(kind=None):
    p = STATE / "v1" / "events.jsonl"
    out = []
    if p.exists():
        for ln in p.read_text().splitlines():
            try:
                e = json.loads(ln)
            except ValueError:
                continue
            if kind is None or e.get("kind") == kind:
                out.append(e)
    return out


def st():
    return S.read(PID)


def make_worktree(branch="auto/CR-001", name="auto-CR-001"):
    wt = DEV / ".worktrees" / "sandbox" / name
    if wt.exists():
        git(MAIN, "worktree", "remove", "--force", str(wt))
        sh(["git", "-C", str(MAIN), "branch", "-D", branch])
    wt.parent.mkdir(parents=True, exist_ok=True)
    git(MAIN, "worktree", "add", "-q", "-b", branch, str(wt), "HEAD")
    from shipmiracle.autopilot import worktree as W0
    W0.isolate_hooks(str(MAIN), str(wt))                 # C1: the engine's per-worktree empty core.hooksPath (the hook module re-checks it on every call)
    (wt / ".claude").mkdir(exist_ok=True)
    return wt


def open_wt_cr(wt, title="login"):
    """Open (and so activate) a CR in the worktree's own engine log."""
    def fn(work):
        cr, trs = engine.open_cr(work, title, "test", int(now()), rules={"lanes": {"default": "full"}})
        return cr["id"], trs
    return store.transact(str(wt), fn, do_render=False)


class Run:
    """A started run: charter set by a real prompt, started by the owner CLI, worktree created."""
    pass


def start(line=LINE, wt_cr=True, fresh=True):
    """Clean slate -> charter via the hook -> `shipm autopilot start --yes --ack` -> worktree. Returns the worktree path."""
    keep = list(ONLY)
    reset_core(only=["autopilot"])
    try:
        return _start(line, wt_cr, fresh)
    finally:
        reset_core(only=keep)


def _start(line, wt_cr, fresh):
    if fresh:
        shipm("autopilot", "stop", "--project", "sandbox")
        write_plan(34)
        S.delete(PID)
        old = DEV / ".worktrees" / "sandbox" / "auto-CR-001"
        if old.exists():
            sh(["git", "-C", str(MAIN), "worktree", "remove", "--force", str(old)])
        sh(["git", "-C", str(MAIN), "branch", "-D", "auto/CR-001"])
    with chain(CHAIN_OK):
        r = hook("UserPromptSubmit", cwd=MAIN, prompt=line, project_dir=MAIN)
    c = registry.autopilot_of(registry.entry(PID))
    if c is None:
        raise SystemExit("fixture: charter not stored: %s" % (r,))
    code, out, err = shipm("autopilot", "start", "--project", "sandbox", "--yes", "--ack", c["charter"]["id"])
    if code != 0:
        raise SystemExit("fixture: start failed: %s %s" % (out, err))
    wt = DEV / ".worktrees" / "sandbox" / "auto-CR-001"          # P6 T5: `shipm autopilot start` creates the worktree and imports CR-001 into its own log
    if not wt.exists():
        wt = make_worktree()
    (wt / ".claude").mkdir(exist_ok=True)
    if wt_cr and engine.active_cr(store.load(str(wt))) is None:
        open_wt_cr(wt)
    S.set_progress(PID, cr="CR-001", branch="auto/CR-001", worktree=str(wt))
    return wt
