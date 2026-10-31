"""Shared helpers for the flow-gate suites (not a test itself: the runner glob only takes *_test.py).
make_project() builds a temp ~/Developer/<name> git project with a team, plus temp STATE / DEV / WS folders, and returns a Proj."""
import json, os, pathlib, shutil, subprocess, tempfile
WS = pathlib.Path(__file__).resolve().parent.parent
HK = "hoo" + "ks"                      # the legacy shell hooks folder of the owner's checkout; built from parts: the public export does not carry those scripts
GATE_REL = HK + "/flow-gate.sh"
LEGACY_HOOK = WS / HK / "flow-gate.sh"
V1_HOOK = WS / "tests/fixtures/hooks/flow/v1_hook.sh"
IMPL = os.environ.get("SHIPMIRACLE_GATE_IMPL") or ("legacy" if LEGACY_HOOK.exists() else "v1")   # legacy = the shell gate (default where present) | v1 = the flow slot of the dispatcher (shipmiracle/hooks/flow.py; the only gate in a public checkout)
if IMPL not in ("legacy", "v1"):
    raise SystemExit("SHIPMIRACLE_GATE_IMPL must be legacy or v1, got %r" % IMPL)


class _V1Hook:
    """Runs as the v1 shim (str/fspath) but reads as the legacy gate: suites that parse the gate source via HOOK.read_text() keep working."""
    def __str__(self): return str(V1_HOOK)
    def __fspath__(self): return str(V1_HOOK)
    def read_text(self, *a, **k): return (LEGACY_HOOK if LEGACY_HOOK.exists() else WS / "shipmiracle/hooks/flow.py").read_text(*a, **k)


HOOK = pathlib.Path(os.environ["SHIPMIRACLE_TEST_HOOK"]) if os.environ.get("SHIPMIRACLE_TEST_HOOK") else (_V1Hook() if IMPL == "v1" else LEGACY_HOOK)

def gate_source():
    """The python part of the flow gate: from the legacy shell script when it exists, else the gate block of shipmiracle/hooks/flow.py."""
    if LEGACY_HOOK.exists():
        return LEGACY_HOOK.read_text().split("\n#--PYTHON-BEGIN--\n", 1)[1]
    t = (WS / "shipmiracle/hooks/flow.py").read_text()
    return t.split("# --- SHIPMIRACLE GATE SOURCE BEGIN", 1)[1].split("\n", 1)[1].split("# --- SHIPMIRACLE GATE SOURCE END", 1)[0]


AGENT_TEXT = "---\nname: {n}\nmodel: {m}\n---\nModel reason: test agent.\nFlow role: {r}\n"
DEFAULT_AGENTS = {
    "solution-architect": AGENT_TEXT.format(n="solution-architect", m="opus", r="plan"),
    "qa-engineer": AGENT_TEXT.format(n="qa-engineer", m="sonnet", r="test"),
    "backend-engineer": AGENT_TEXT.format(n="backend-engineer", m="sonnet", r="build"),
    "frontend-engineer": AGENT_TEXT.format(n="frontend-engineer", m="sonnet", r="build"),
}


def deny(o):
    return (o.get("hookSpecificOutput") or {}).get("permissionDecision") == "deny" or o.get("decision") == "block"


def note(o):
    """The text a hook output carries besides a refusal (systemMessage or additionalContext), '' if none."""
    return (o.get("systemMessage") or "") + ((o.get("hookSpecificOutput") or {}).get("additionalContext") or "")


def text(o):
    return json.dumps(o, ensure_ascii=False)


class Proj:
    def __init__(self, name, records_dir, agents):
        self.T = pathlib.Path(tempfile.mkdtemp()).resolve()
        self.DEV = self.T / "Developer"; self.P = self.DEV / name
        self.STATE = self.T / "state"; self.WSF = self.T / "ws"
        (self.P / ".claude/agents").mkdir(parents=True); (self.P / "src").mkdir(); (self.P / records_dir).mkdir(); (self.WSF / "config").mkdir(parents=True)
        for n, t in agents.items():
            (self.P / ".claude/agents" / (n + ".md")).write_text(t)
        (self.P / "src/app.py").write_text("x = 1\n")
        git = ["git", "-C", str(self.P)]
        subprocess.run(["git", "init", "-q", str(self.P)], check=True)
        subprocess.run(git + ["add", "-A"], check=True)
        subprocess.run(git + ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "i"], check=True, capture_output=True)
        self.level("strict")
        self.ENV = dict(os.environ, SHIPMIRACLE_STATE=str(self.STATE), SHIPMIRACLE_DEV=str(self.DEV), SHIPMIRACLE_WS=str(self.WSF), CLAUDE_PROJECT_DIR=str(self.P), SHIPMIRACLE_TEST="1")
        self.ENV.pop("SHIPMIRACLE_QUIET", None); self.ENV.pop("SHIPMIRACLE_FLOW_TAMPER_OK", None)
        self.run_cwd = None                                      # cwd of the hook process (Claude Code runs hooks in the project folder)

    # --- running the hook
    def level(self, lv):
        (self.WSF / "config/flow.json").write_text(json.dumps({"default": lv}))

    def popen(self, ev, sid="s1", env=None, **kw):
        d = {"hook_event_name": ev, "session_id": sid, "cwd": str(self.P), **kw}
        p = subprocess.Popen(["bash", str(HOOK)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env or self.ENV, cwd=self.run_cwd)
        p.payload = json.dumps(d)                                # feed with p.communicate(p.payload)
        return p

    def run_raw(self, raw, env=None):
        return subprocess.run(["bash", str(HOOK)], input=raw, capture_output=True, text=True, env=env or self.ENV, cwd=self.run_cwd)

    def hook(self, ev, sid="s1", env=None, **kw):
        d = {"hook_event_name": ev, "session_id": sid, "cwd": str(self.P), **kw}
        r = self.run_raw(json.dumps(d), env)
        try:
            return json.loads(r.stdout) if r.stdout.strip() else {}
        except Exception:
            return {"raw": r.stdout}

    # --- shortcuts
    def prompt(self, t="go on", sid="s1"):
        return self.hook("UserPromptSubmit", sid, prompt=t)

    def _who(self, agent):
        return {"agent_id": "ag1", "agent_type": agent} if agent else {}

    def pre(self, tool, ti, sid="s1", agent=None):
        return self.hook("PreToolUse", sid, tool_name=tool, tool_input=ti, **self._who(agent))

    def post(self, tool, ti, sid="s1", agent=None):
        return self.hook("PostToolUse", sid, tool_name=tool, tool_input=ti, **self._who(agent))

    def edit(self, path, old="a", new="b", sid="s1", agent=None, **extra):
        return self.pre("Edit", {"file_path": str(self.P / path), "old_string": old, "new_string": new, **extra}, sid, agent)

    def write(self, path, content, sid="s1", agent=None):
        return self.pre("Write", {"file_path": str(self.P / path), "content": content}, sid, agent)

    def bash(self, cmd, sid="s1"):
        return self.pre("Bash", {"command": cmd}, sid)

    def sub_stop(self, agent_type, sid="s1"):
        return self.hook("SubagentStop", sid, agent_id="sa", agent_type=agent_type)

    def stop(self, sid="s1", active=False):
        return self.hook("Stop", sid, stop_hook_active=active)

    # --- inspecting
    def state(self, sid="s1"):
        try:
            return json.load(open(self.STATE / f"flow.{sid}.json"))
        except Exception:
            return {}

    def events(self):
        try:
            return [json.loads(l) for l in (self.STATE / "flow-events.jsonl").read_text().splitlines() if l.strip()]
        except Exception:
            return []

    def errors(self):
        try:
            return (self.STATE / "flow-errors.log").read_text()
        except OSError:
            return ""

    def put(self, path, content):
        f = self.P / path; f.parent.mkdir(parents=True, exist_ok=True); f.write_text(content); return f

    def cleanup(self):
        try:
            os.chmod(self.STATE, 0o755)
        except OSError:
            pass
        shutil.rmtree(self.T, ignore_errors=True)


def make_project(name="proj", records_dir="docs", agents=None):
    return Proj(name, records_dir, dict(DEFAULT_AGENTS) if agents is None else agents)
