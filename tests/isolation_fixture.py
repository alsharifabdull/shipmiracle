"""Shared world for the G11 / D11 suites (project isolation layer 1 and the secret-read rule). Not a test itself (the runner glob only takes *_test.py).
World(): a temp projects folder DEV with
  proj      the project the chat works in (a team, git)
  other     another registered project (src/a.py, .env, notes.md)      third  a second other project           kiosk  a project whose name starts with k (Kelvin sign spelling)
  hub       the workspace (WS) as a project of DEV: bin/, README.md, shipmiracle/, reference/, docs/STATUS.md, docs/plans/, config/flow.json
  notes     a folder without .git (not a project)
  DEV/.worktrees/other/wt1  a worktree folder of `other`;   DEV/.worktrees/ghost/x  a worktrees folder that matches no project
call(tool, tool_input, impl=..., agent=None, who="proj") runs one PreToolUse through the legacy shell gate (impl "legacy") or the v1 dispatcher flow slot (impl "v1")."""
import json, os, pathlib, re, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import flow_fixture as F
import pwd, shipmiracle_isolation

shipmiracle_isolation.apply_to_environ()           # a caller that forgot gets a temp HOME, never the real one


def require_temp_home():
    """Abort unless HOME is a temp folder that is not the account's real home (a probe once overwrote ~/.docker/config.json through a real HOME)."""
    h = os.path.realpath(os.environ.get("HOME", ""))
    if not h or h == os.path.realpath(pwd.getpwuid(os.getuid()).pw_dir) or not shipmiracle_isolation._under_temp(h):
        raise SystemExit("isolation_fixture: HOME %r is not a temp folder; refusing to run" % h)


require_temp_home()

PREFIX = "Project isolation:"
CERT = "-----BEGIN CERTIFICATE-----\nMIIBkTCB+wIJAKHBfpegPjMCMA0GCSqGSIb3DQEBCwUA\n-----END CERTIFICATE-----\n"          # a public certificate (not secret)
PRIV = "-----BEGIN PRIV" + "ATE KEY-----\nMIIBVQIBADANBgkq\n-----END PRIV" + "ATE KEY-----\n"        # a .pem/.key file counts as secret when it holds a private key (public certificates do not)
IMPLS = ([("legacy", str(F.LEGACY_HOOK))] if F.LEGACY_HOOK.exists() else []) + [("v1", str(F.V1_HOOK))]


class World:
    def __init__(self, level=None):
        require_temp_home()
        self.p = p = F.make_project("proj")
        self.T = p.T; self.DEV = p.DEV
        self.P = p.P
        for n in ("other", "third", "kiosk", "hub"):
            (p.DEV / n / ".git").mkdir(parents=True)
        self.B = p.DEV / "other"; self.C = p.DEV / "third"; self.K = p.DEV / "kiosk"; self.HUB = p.DEV / "hub"
        for rel, txt in (("src/a.py", "print(1)\n"), (".env", "KEY=1\n"), ("notes.md", "n\n"), ("server.pem", PRIV), (".env.example", "KEY=\n")):
            f = self.B / rel; f.parent.mkdir(parents=True, exist_ok=True); f.write_text(txt)
        (self.C / "c.txt").write_text("c\n"); (self.K / "k.txt").write_text("k\n")
        for rel, txt in (("bi" + "n/tool", "#!/bin/sh\n"), ("README.md", "r\n"), ("shipmiracle/x.py", "x\n"), ("reference/ref.md", "ref\n"), ("docs/STATUS.md", "s\n"), ("docs/plans/p.md", "p\n"),
                         ("docs/standards/s.md", "s\n"), ("config/other.json", "{}\n"), ("tests/t.py", "t\n"), ("memory/m.md", "m\n"), ("AGENTS.md", "a\n"), ("agents/a.md", "a\n")):
            f = self.HUB / rel; f.parent.mkdir(parents=True, exist_ok=True); f.write_text(txt)
        (p.DEV / "notes").mkdir(); (p.DEV / "notes/n.txt").write_text("n\n")
        for rel in (".worktrees/other/wt1", ".worktrees/ghost/x"):
            (p.DEV / rel).mkdir(parents=True); (p.DEV / rel / "f.txt").write_text("w\n")
        (self.P / "src/mine.py").write_text("mine\n")
        self.cfg = self.T / "cfg"; self.cfg.mkdir()
        self.home = pathlib.Path(os.environ["HOME"])
        self.env = dict(p.ENV, SHIPMIRACLE_WS=str(self.HUB), SHIPMIRACLE_CONFIG=str(self.cfg))
        self.env.pop("SHIPMIRACLE_ISOLATION", None)
        self.set_level(level or "strict")
        self.n = 0
        p.prompt()

    def set_level(self, level, projects=None, block=True):
        j = {"default": "strict"}
        if block:
            j["isolation"] = {"default": level, "projects": projects or {}}
        (self.HUB / "config/flow.json").write_text(json.dumps(j))

    def set_links(self, links):
        """links: [(from path, to path, mode)] -> project-links.json with the real ids."""
        from shipmiracle import projects as PR
        rows = [{"from": PR.project_id(a), "to": PR.project_id(b), "mode": m, "from_name": os.path.basename(str(a)), "to_name": os.path.basename(str(b)), "ts": 1} for a, b, m in links]
        (self.cfg / "project-links.json").write_text(json.dumps({"v": 1, "links": rows}))

    def call(self, tool, ti, impl="legacy", agent=None, who="proj", cwd=None, env=None, sid=None):
        """-> the hook's JSON answer ({} when it says nothing)."""
        hook = dict(IMPLS)[impl]
        self.n += 1
        e = dict(env or self.env)
        base = self.P if who == "proj" else self.HUB
        e["CLAUDE_PROJECT_DIR"] = str(base)
        d = {"hook_event_name": "PreToolUse", "session_id": sid or ("w%d" % self.n), "cwd": str(cwd or base), "tool_name": tool, "tool_input": ti}
        if agent:
            d.update({"agent_id": "ag1", "agent_type": agent})
        r = subprocess.run(["bash", hook], input=json.dumps(d), capture_output=True, text=True, env=e, cwd=str(base))
        try:
            return json.loads(r.stdout) if r.stdout.strip() else {}
        except Exception:
            return {"raw": r.stdout, "err": r.stderr}

    def events(self):
        return self.p.events()

    def cleanup(self):
        self.p.cleanup()


def reason(o):
    return ((o.get("hookSpecificOutput") or {}).get("permissionDecisionReason") or o.get("reason") or "")


def iso_denied(o):
    return F.deny(o) and PREFIX in reason(o)


def note_of(o):
    return F.note(o)
