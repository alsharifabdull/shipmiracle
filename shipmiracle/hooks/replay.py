"""Replay of hook inputs through BOTH implementations (spec docs/plans/2026-10-20-p4-spec.md section 3): the legacy scripts (hooks.dispatcher=legacy: the
real entry hooks/shipm-hook running hooks/*.sh) and v1 (hooks.dispatcher=v1: the modules), as subprocesses of the real entry, each in its own FAKE HOME.
Nothing outside the temp folder is written: a fake HOME (state, config, ~/.claude/settings.json sanitised, a `git clone --local` of the project at HEAD,
stubs for caffeinate/osascript/gh/pmset on PATH). The real state, ~/.claude and the real repos are only read (the clone source, settings, transcripts).
Corpora: fixtures (tests/fixtures/flow/*.json + tests/fixtures/hooks/replay/*.jsonl), record (v1/hooks-record.jsonl), transcripts (derived from
~/.claude/projects/*/*.jsonl, last 14 days). Inputs run in order per session with the state carried forward per implementation.
Comparison per event: decision / reason / context / system message (whitespace collapsed; exit 2 + stderr text equals a JSON deny/block with that text),
exit code, the state folder after the event (canonical JSON, epoch numbers zeroed), intended effects (stub log), error counts.
Reports contain counts, event kinds and sha prefixes only; full texts only in a local file under the state folder (--full-local).
Case format (one JSON object): {session, project ("@synthetic" or a project name), event, input | raw, pre_state {name: text | {text, age_s}},
env {NAME: value}, transcript_text}. Strings in input may use {P} (project dir), {HOME}, {STATE}, {T} (transcripts folder) placeholders."""
from __future__ import annotations

import collections
import concurrent.futures
import glob
import json
import os
import pwd
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import shadow as S

WS = Path(__file__).resolve().parents[2]
ENTRY = WS / "hooks" / "shipm-hook"
SYSPY = "/usr/bin/python3" if os.path.exists("/usr/bin/python3") else "python3"
CALL_TIMEOUT = 120
MAX_LARGE = 200000                 # an input string longer than this is skipped when deriving from transcripts
AGENT_TEXT = "---\nname: {n}\nmodel: {m}\n---\nModel reason: test agent.\nFlow role: {r}\n"
SYNTH_AGENTS = {"solution-architect": ("opus", "plan"), "qa-engineer": ("sonnet", "test"), "backend-engineer": ("sonnet", "build"), "frontend-engineer": ("sonnet", "build")}
SYNTH_NAME = "proj"
_LOCK = threading.Lock()
SKIP_TOOL_STATE = re.compile(r"\.(tmp|lock)$")


ENGINE = None                                    # set by the CLI (--engine); None = the stage module stays inert


class ReplayError(Exception):
    pass


def real_home() -> str:
    return pwd.getpwuid(os.getuid()).pw_dir


def sha8(s: str) -> str:
    return S.sha(s)[:8]


# ---------------------------------------------------------------- the fake home
STUB = "#!/bin/sh\necho \"$(basename \"$0\") $*\" >> \"$STUBLOG\"\n%s\n"


def _run(cmd, **kw):
    return subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=kw.pop("timeout", 600), **kw)


def clean_env(extra=None) -> dict:
    e = {"PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin", "LANG": "en_US.UTF-8", "GIT_TERMINAL_PROMPT": "0"}
    e.update(extra or {})
    return e


def make_template(base: Path) -> Path:
    """A small synthetic project with a team (what tests/flow_fixture.make_project builds), committed."""
    p = base / "template" / SYNTH_NAME
    (p / ".claude/agents").mkdir(parents=True)
    (p / "src").mkdir()
    (p / "docs").mkdir()
    for n, (m, r) in SYNTH_AGENTS.items():
        (p / ".claude/agents" / (n + ".md")).write_text(AGENT_TEXT.format(n=n, m=m, r=r))
    (p / "src/app.py").write_text("x = 1\n")
    env = clean_env({"HOME": str(base), "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"})
    for c in (["git", "init", "-q", str(p)], ["git", "-C", str(p), "add", "-A"],
              ["git", "-C", str(p), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "i"]):
        r = _run(c, env=env)
        if r.returncode:
            raise ReplayError("git failed: " + r.stderr[:200])
    return p


def sanitized_settings(src: str) -> dict:
    """Only what the gate digests (hooks, disableAllHooks, env keys with dummy values): permissions, MCP and other keys can hold private data."""
    try:
        d = json.loads(Path(src).read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}
    out = {k: d[k] for k in ("hooks", "disableAllHooks") if isinstance(d, dict) and k in d}
    if isinstance(d, dict) and isinstance(d.get("env"), dict):
        out["env"] = {k: "x" for k in d["env"]}
    return out


class Home:
    """One implementation's fake HOME for one project."""

    def __init__(self, base: Path, label: str, impl: str, project: str, src_project: Optional[str], template: Optional[Path], settings_src: str, pyc: Path,
                 code: Optional[Path] = None):
        self.impl, self.project = impl, project
        self.entry = (Path(code) / "hooks" / "shipm-hook") if code else ENTRY          # a frozen copy of the code under test (replay_cases) or the live worktree
        self.root = base / label
        self.home = self.root / "home"
        self.dev = self.home / "Developer"
        self.proj = self.dev / project
        self.state = self.home / ".local/state/shipmiracle"
        self.cfg = self.home / ".config/shipmiracle"
        self.ws = self.root / "ws"
        self.tmp = self.home / "tmp"
        self.tr = self.root / "tr"
        self.bin = self.root / "bin"
        self.stublog = self.root / "stub.log"
        self.sleep_tag = "3600.%06d" % (int.from_bytes(os.urandom(3), "big") % 1000000)        # the stub caffeinate sleeps this long: unique to this home, so cleanup finds exactly its own
        self.pyc = pyc
        self._stub_pos = 0
        self._ev_pos = 0
        self.dev.mkdir(parents=True)
        src = src_project or str(template)
        r = _run(["git", "clone", "--local", "-q", src, str(self.proj)], env=clean_env({"HOME": str(self.root)}))
        if r.returncode:
            raise ReplayError("clone of %s failed: %s" % (os.path.basename(src), r.stderr.strip()[:200]))
        for d in (self.state, self.cfg, self.tmp, self.tr, self.bin, self.ws / "config", self.home / ".claude"):
            d.mkdir(parents=True, exist_ok=True)
        os.chmod(self.state, 0o700)
        (self.cfg / "config.json").write_text(json.dumps({"hooks.dispatcher": impl}))
        (self.home / ".claude/settings.json").write_text(json.dumps(sanitized_settings(settings_src)))
        flow_cfg = (Path(code) if code else WS) / "config/flow.json"
        if flow_cfg.exists():
            shutil.copyfile(flow_cfg, self.ws / "config/flow.json")
        else:
            (self.ws / "config/flow.json").write_text('{"default": "strict"}')
        self.stublog.write_text("")
        for n in ("caffeinate", "osascript", "gh", "pmset"):
            p = self.bin / n
            p.write_text(STUB % ("exec /bin/sleep " + self.sleep_tag if n == "caffeinate" else "exit 0"))
            p.chmod(0o755)

    def env(self, extra=None) -> dict:
        e = clean_env({"PATH": "%s:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin" % self.bin, "HOME": str(self.home), "TMPDIR": str(self.tmp), "SHIPMIRACLE_TEST": "1",
                       "SHIPMIRACLE_HOME": str(self.home), "SHIPMIRACLE_CONFIG": str(self.cfg), "SHIPMIRACLE_STATE": str(self.state), "SHIPMIRACLE_DEV": str(self.dev), "SHIPMIRACLE_WS": str(self.ws),
                       "CLAUDE_PROJECT_DIR": str(self.proj), "STUBLOG": str(self.stublog), "SHIPMIRACLE_HOOK_NO_SPAWN": "1"})
        if os.environ.get("SHIPMIRACLE_TEST") == "1" and os.environ.get("SHIPMIRACLE_FAKE_OS"):
            e["SHIPMIRACLE_FAKE_OS"] = os.environ["SHIPMIRACLE_FAKE_OS"]      # a test says which OS the replayed hooks pretend to run on (the legacy scripts are the macOS ones)
        if ENGINE:                                   # `shipm hooks replay --engine shadow|playbook`: the stage module runs on the replayed events (no work.json is rendered)
            e.update({"SHIPMIRACLE_STAGE_REPLAY": "1", "SHIPMIRACLE_GATE_ENGINE": ENGINE})
        e.update(extra or {})
        return e

    def subst(self, text: str) -> str:
        return (text.replace("{P}", str(self.proj)).replace("{HOME}", str(self.home)).replace("{STATE}", str(self.state)).replace("{T}", str(self.tr)).replace("{WS}", str(self.ws)).replace("{NOW}", str(int(time.time()))))

    def stage_shadow_events(self) -> List[Tuple[str, str]]:
        """[(kind, stage)] of the `stage.shadow` events (what the shadow stage engine would have refused) appended to this home's event log since the last call."""
        try:
            data = (self.state / "v1" / "events.jsonl").read_bytes()
        except OSError:
            return []
        new, self._ev_pos = data[self._ev_pos:], len(data)
        out = []
        for ln in new.splitlines():
            if b'"stage.shadow"' not in ln:
                continue
            try:
                e = json.loads(ln.decode("utf-8"))
                if e.get("kind") == "stage.shadow":
                    out.append((str(e["data"].get("kind", "?"))[:40], str(e["data"].get("stage", "?"))[:40]))
            except (ValueError, KeyError, AttributeError):
                continue
        return out

    def reset_state(self, pre_state: Optional[dict]) -> None:
        self.kill_stubs()
        self._ev_pos = 0
        shutil.rmtree(self.state, ignore_errors=True)
        self.state.mkdir(parents=True)
        os.chmod(self.state, 0o700)
        for f in self.tmp.iterdir():
            f.unlink() if f.is_file() else shutil.rmtree(f, ignore_errors=True)
        for name, v in (pre_state or {}).items():
            text, age = (v.get("text", ""), v.get("age_s", 0)) if isinstance(v, dict) else (v, 0)
            p = self.state / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(self.subst(text))
            if age:
                t = time.time() - age
                os.utime(p, (t, t))

    def kill_stubs(self) -> None:
        """Stop the stub caffeinate processes this home's hooks started: the stub script (before its exec) or its unique `sleep <token>` (after). Only those."""
        for pat in (re.escape(str(self.bin) + "/"), re.escape("/bin/sleep " + self.sleep_tag)):
            for _ in range(2):
                r = _run(["pgrep", "-f", pat])
                for pid in r.stdout.split():
                    try:
                        os.kill(int(pid), 15)
                    except (OSError, ValueError):
                        pass
                if not r.stdout.strip():
                    break
                time.sleep(0.05)

    def effects(self) -> List[str]:
        try:
            txt = self.stublog.read_text()
        except OSError:
            return []
        new, self._stub_pos = txt[self._stub_pos:], len(txt)
        return sorted(re.sub(r"\d+", "N", l) for l in new.splitlines() if l.strip())

    def command(self, event: str) -> List[str]:
        return [SYSPY, "-I", "-S", "-X", "pycache_prefix=" + str(self.pyc), str(self.entry), event]

    def call(self, event: str, raw: bytes, env_extra=None) -> dict:
        try:
            p = subprocess.run(self.command(event), input=raw, capture_output=True, env=self.env(env_extra), cwd=str(self.proj), timeout=CALL_TIMEOUT)
            return {"exit": p.returncode, "out": p.stdout, "err": p.stderr, "timeout": False}
        except subprocess.TimeoutExpired:
            return {"exit": -1, "out": b"", "err": b"", "timeout": True}

    def state_view(self) -> dict:
        """The state folder as comparable values: {name: canonical}. Logs: lines without timestamps; flow-errors.log: the line count only."""
        roots = [str(self.root)]
        out = {}
        try:
            names = sorted(os.listdir(self.state))
        except OSError:
            return out
        for n in names:
            p = self.state / n
            if SKIP_TOOL_STATE.search(n) or not p.is_file() or n.startswith("."):
                continue
            try:
                data = p.read_bytes()[:S.CAP_FILE]
            except OSError:
                continue
            text = data.decode("utf-8", "replace")
            for r in roots:
                text = text.replace(r, "<H>")
            if n == "flow-errors.log":
                out[n] = len([l for l in text.splitlines() if l.strip()])
            elif n.endswith(".jsonl") or n.endswith(".log"):
                out[n] = S._norm_lines([re.sub(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d ", "", l) for l in text.splitlines() if l.strip()])
            else:
                out[n] = S.canon(n, (text.encode(), 0, True))
        return out

    def cleanup(self) -> None:
        self.kill_stubs()
        shutil.rmtree(self.root, ignore_errors=True)


# ---------------------------------------------------------------- comparison
def _ctx_beside_deny(d: dict) -> bool:
    """Same deny and reason, but v1 also carries a module's additionalContext (e.g. the flow gate's "let through" note) that the legacy-mode shim dropped."""
    l, v = d["legacy"], d["v1"]
    return (d["event"] == "PreToolUse" and d["dims"] == ["context"] and l["decision"] == "deny" == v["decision"] and l["reason_sha"] == v["reason_sha"]
            and l["ctx_sha"] == "" and v["ctx_sha"] != "")


# (name, predicate(disagreement) -> bool, why): the documented, understood differences. Anything else is "unexplained" and fails the run.
EXPLAINED: List[Tuple[str, Any, str]] = [
    ("shim-drops-context-beside-deny", _ctx_beside_deny,
     "hooks/shipm-hook legacy() builds a bare deny and drops the additionalContext of the other modules; core.merge (v1) keeps it next to the deny as spec 2.4 rule 4 says until probe P4-1 is answered"),
]


def classify(d: dict) -> Tuple[str, str]:
    for name, pred, why in EXPLAINED:
        try:
            if pred(d):
                return "explained", "%s: %s" % (name, why)
        except Exception:
            continue
    return "unexplained", ""


def diff_state(a: dict, b: dict) -> List[str]:
    return [n for n in sorted(set(a) | set(b)) if a.get(n) != b.get(n)]


def _unroot(r: dict, root) -> dict:
    """The answer with the fake home's folder replaced by <H> (the two implementations run in differently named folders)."""
    b = str(root).encode()
    return dict(r, out=r["out"].replace(b, b"<H>"), err=r["err"].replace(b, b"<H>"))


def compare_results(event: str, la: dict, lb: dict, ra=None, rb=None) -> Tuple[List[str], dict, dict]:
    if ra is not None:
        la, lb = _unroot(la, ra), _unroot(lb, rb)
    sa, sb = S.summarize(event, la["out"], la["err"], la["exit"]), S.summarize(event, lb["out"], lb["err"], lb["exit"])
    dims = []
    if la["timeout"] or lb["timeout"]:
        dims.append("timeout")
    else:
        for k, n in (("decision", "decision"), ("reason_sha", "reason"), ("ctx_sha", "context"), ("sysmsg_sha", "sysmsg"), ("exit", "exit")):
            if sa[k] != sb[k]:
                dims.append(n)
    return dims, sa, sb


def texts_of(event: str, r: dict) -> dict:
    """Full normalised texts of one answer (local file only)."""
    txt, etxt = r["out"].decode("utf-8", "replace"), r["err"].decode("utf-8", "replace")
    return {"exit": r["exit"], "stdout": S.collapse(txt), "stderr": S.collapse(etxt)}


def run_session(ha: Home, hb: Home, cases: List[dict], corpus: str, stats: dict, full: bool) -> List[dict]:
    """The cases of one session in order through legacy (ha) and v1 (hb); state carried forward. -> the disagreements."""
    out = []
    ha.reset_state(cases[0].get("pre_state"))
    hb.reset_state(cases[0].get("pre_state"))
    carried = set()
    ha.effects(), hb.effects()
    prev = (ha.state_view(), hb.state_view())
    for i, c in enumerate(cases):
        event = c["event"]
        if c.get("transcript_text") is not None:
            for h in (ha, hb):
                tp = h.subst(str((c.get("input") or {}).get("transcript_path") or ""))
                p = Path(tp) if tp.startswith(str(h.tr) + "/") else h.tr / (re.sub(r"[^A-Za-z0-9_-]", "", str(c["session"])) + ".jsonl")
                p.write_text(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": c["transcript_text"]}]}}) + "\n")
        if "raw" in c:
            raws = [h.subst(c["raw"]).encode() for h in (ha, hb)]
        else:
            raws = [h.subst(json.dumps(c["input"])).encode() for h in (ha, hb)]
        extra = c.get("env") or {}
        with concurrent.futures.ThreadPoolExecutor(2) as ex:
            fa, fb = ex.submit(ha.call, event, raws[0], extra), ex.submit(hb.call, event, raws[1], extra)
            la, lb = fa.result(), fb.result()
        dims, sa, sb = compare_results(event, la, lb, ha.root, hb.root)
        va, vb = ha.state_view(), hb.state_view()
        sd = diff_state(va, vb)
        new_sd = [n for n in sd if n not in carried]
        carried = set(sd)
        ea, eb = [], []
        for _ in range(12):                                   # the legacy scripts start caffeinate in the background (`nohup ... &`): give the stub a moment to log
            ea, eb = sorted(ea + ha.effects()), sorted(eb + hb.effects())
            if ea == eb:
                break
            time.sleep(0.05)
        if ea != eb:
            dims.append("effects")
        dims += ["state:" + n for n in new_sd]
        tool = (c.get("input") or {}).get("tool_name", "") if isinstance(c.get("input"), dict) else ""
        sh = hb.stage_shadow_events() if ENGINE else []
        with _LOCK:
            stats["events"] += 1
            stats["by_event"][event] += 1
            stats["by_project"][c.get("project_real") or c["project"]] += 1
            stats["decisions"]["legacy"][sa["decision"]] += 1
            stats["decisions"]["v1"][sb["decision"]] += 1
            stats["effects"]["legacy"].update(ea)
            stats["effects"]["v1"].update(eb)
            stats["state_changes"]["legacy"] += va != prev[0]
            stats["state_changes"]["v1"] += vb != prev[1]
            for kind, stg in sh:
                stats["stage_shadow"]["by_kind"][kind] += 1
                stats["stage_shadow"]["by_stage"][stg] += 1
                stats["stage_shadow"]["events"] += 1
        prev = (va, vb)
        if dims:
            d = {"corpus": corpus, "project": c.get("project_real") or c["project"], "session": sha8(str(c["session"])), "idx": i, "event": event, "tool": tool,
                 "dims": dims, "legacy": sa, "v1": sb, "effects": {"legacy": ea, "v1": eb}, "input_sha": sha8(json.dumps(c.get("input") or c.get("raw"), sort_keys=True))}
            d["classification"], d["why"] = classify(d)
            if full:
                d["full"] = {"legacy": texts_of(event, _unroot(la, ha.root)), "v1": texts_of(event, _unroot(lb, hb.root)), "input": c.get("input") or c.get("raw"),
                             "state": {n: {"legacy": va.get(n), "v1": vb.get(n)} for n in new_sd}}
            out.append(d)
    return out


def code_rev() -> str:
    """git short rev of the worktree, plus +dirty when files differ from it (what the report says it ran)."""
    try:
        rev = _run(["git", "-C", str(WS), "rev-parse", "--short", "HEAD"], timeout=20).stdout.strip()
        dirty = _run(["git", "-C", str(WS), "status", "--porcelain", "--", "shipmiracle", "hooks", "config"], timeout=20).stdout.strip()
        return rev + ("+dirty" if dirty else "")
    except Exception:
        return "unknown"


def replay_cases(cases: List[dict], corpus: str, src_home: str = None, workers: int = 4, full: bool = False, base: Path = None, progress=None, freeze: bool = True) -> dict:
    """Run all cases (any number of sessions/projects) through both implementations in fake homes. -> the report dict."""
    src_home = src_home or real_home()
    t0 = time.time()
    own_base = base is None
    base = Path(base) if base else Path(tempfile.mkdtemp(prefix="shipmiracle-replay-"))
    stats = {"events": 0, "by_event": collections.Counter(), "by_project": collections.Counter(), "decisions": {"legacy": collections.Counter(), "v1": collections.Counter()},
             "effects": {"legacy": collections.Counter(), "v1": collections.Counter()}, "state_changes": {"legacy": 0, "v1": 0},
             "stage_shadow": {"events": 0, "by_kind": collections.Counter(), "by_stage": collections.Counter()}}
    skipped = collections.Counter()
    by_proj: Dict[str, Dict[str, List[dict]]] = collections.OrderedDict()
    for c in cases:
        by_proj.setdefault(c["project"], collections.OrderedDict()).setdefault(c["session"], []).append(c)
    settings_src = os.path.join(src_home, ".claude/settings.json")
    template = None
    pyc = base / "pyc"
    pyc.mkdir(parents=True, exist_ok=True)
    code = None
    if freeze:                                                  # the code under test is copied once: another session editing the worktree cannot change a run half way
        code = base / "code"
        for d in ("shipmiracle", "hooks", "config"):
            shutil.copytree(WS / d, code / d, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    disagreements: List[dict] = []
    try:
        if "@synthetic" in by_proj:
            template = make_template(base)

        def work(item):
            proj, sessions = item
            label = re.sub(r"[^A-Za-z0-9_-]", "_", proj)
            hs = []
            try:
                synth = proj == "@synthetic"
                src = None if synth else os.path.join(src_home, "Developer", proj)
                if not synth and not os.path.isdir(os.path.join(src, ".git")):
                    skipped["no_project_repo"] += sum(len(v) for v in sessions.values())
                    return []
                name = SYNTH_NAME if synth else proj
                ha = Home(base, label + "-legacy", "legacy", name, src, template, settings_src, pyc, code)
                hs.append(ha)
                hb = Home(base, label + "-v1", "v1", name, src, template, settings_src, pyc, code)
                hs.append(hb)
                out = []
                for sid, cs in sessions.items():
                    out += run_session(ha, hb, cs, corpus, stats, full)
                    if progress:
                        progress(proj, stats["events"])
                return out
            except ReplayError as e:
                skipped["setup_failed:" + str(e)[:60]] += sum(len(v) for v in sessions.values())
                return []
            finally:
                for h in hs:
                    h.cleanup()
        with concurrent.futures.ThreadPoolExecutor(max(1, workers)) as ex:
            for part in ex.map(work, list(by_proj.items())):
                disagreements += part
    finally:
        if own_base:
            shutil.rmtree(base, ignore_errors=True)
    rev = code_rev()
    unexpl = [d for d in disagreements if d["classification"] == "unexplained"]
    return {"v": 1, "corpus": corpus, "code": rev, "events": stats["events"], "by_event": dict(stats["by_event"]), "by_project": dict(stats["by_project"]),
            "decisions": {k: dict(v) for k, v in stats["decisions"].items()}, "effects": {k: dict(v) for k, v in stats["effects"].items()},
            "state_changes": stats["state_changes"], "stage_shadow": {"events": stats["stage_shadow"]["events"], "by_kind": dict(stats["stage_shadow"]["by_kind"]),
                                                                    "by_stage": dict(stats["stage_shadow"]["by_stage"]), "engine": ENGINE}, "skipped": dict(skipped), "secs": round(time.time() - t0, 1),
            "disagreements": disagreements, "explained": len(disagreements) - len(unexpl), "unexplained": len(unexpl)}


# ---------------------------------------------------------------- corpora
def fixture_cases(ws: Path = None, flow_dir: str = None, replay_dir: str = None) -> List[dict]:
    ws = Path(ws) if ws else WS
    cases = []
    for f in sorted(glob.glob(str(flow_dir or ws / "tests/fixtures/flow/*.json"))):
        try:
            d = json.loads(Path(f).read_text())
        except (OSError, ValueError):
            continue
        if not (isinstance(d, dict) and isinstance(d.get("hook_event_name"), str)):
            continue
        txt = json.dumps(d).replace('"PROJECT/', '"{P}/').replace('"PROJECT"', '"{P}"').replace('"SESSION"', '"fixture-s1"')
        cases.append({"session": "flowfix:" + os.path.basename(f), "project": "@synthetic", "event": d["hook_event_name"], "input": json.loads(txt)})
    for f in sorted(glob.glob(str(replay_dir or ws / "tests/fixtures/hooks/replay/*.jsonl"))):
        for l in Path(f).read_text().splitlines():
            if l.strip():
                try:
                    c = json.loads(l)
                except ValueError:
                    continue
                if isinstance(c, dict) and c.get("event"):
                    c.setdefault("project", "@synthetic")
                    c["session"] = "%s:%s" % (os.path.basename(f), c.get("session", "s"))
                    cases.append(c)
    return cases


def _generalize(text: str, dev_real: str, proj: str = "") -> str:
    """Real paths -> placeholders: the project folder (also a worktree of it and the ~/ symlink spelling) -> {P}, the home -> {HOME}."""
    home = os.path.dirname(dev_real)
    end = r"(?![A-Za-z0-9._-])"
    if proj:
        for p in (re.escape(dev_real + "/.worktrees/" + proj) + r"/[^/\"\\\s]+", re.escape(dev_real + "/" + proj) + end, re.escape(home + "/" + proj) + end):
            text = re.sub(p, "{P}", text)
    return text.replace(home, "{HOME}")


def record_cases(state: str = None, limit: int = 0, project: str = None) -> List[dict]:
    """Sessions from <state>/v1/hooks-record.jsonl (redacted records): the first record of a session carries its pre-state."""
    state = state or os.environ.get("SHIPMIRACLE_STATE") or os.path.join(real_home(), ".local/state/shipmiracle")
    cases, seen = [], set()
    for path in (S.record_path(state) + ".1", S.record_path(state)):
        try:
            lines = Path(path).read_text(errors="replace").splitlines()
        except OSError:
            continue
        for l in lines:
            try:
                r = json.loads(l)
                inp = r["input"]
                sid = (inp.get("session_id") if isinstance(inp, dict) else None) or "x"
            except (ValueError, KeyError, AttributeError):
                continue
            cwd = inp.get("cwd", "") if isinstance(inp, dict) else ""
            m = re.search(r"/Developer/(?:\.worktrees/)?([^/]+)", cwd or "")
            proj = r.get("project") or (m.group(1) if m else "")
            if not proj or (project and proj != project):
                continue
            dm = re.match(r"(.*)/Developer/", cwd or "")
            dev_real = dm.group(1) + "/Developer" if dm else ""
            c = {"session": "rec:" + str(sid), "project": proj, "event": r["event"], "project_real": proj,
                 "input": json.loads(_generalize(json.dumps(inp), dev_real, proj)) if dev_real else inp}
            if (sid, proj) not in seen:
                seen.add((sid, proj))
                c["pre_state"] = {n: _generalize(t, dev_real, proj) if dev_real else t for n, t in (r.get("pre_state") or {}).items()}
            cases.append(c)
            if limit and len(cases) >= limit:
                return cases
    return cases


def _text_of(msg) -> Tuple[str, bool]:
    """(prompt text, is_tool_result_only) of a user message."""
    c = msg.get("content") if isinstance(msg, dict) else None
    if isinstance(c, str):
        return c, False
    if isinstance(c, list):
        texts = [b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text"]
        res = any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c)
        return "\n".join(texts), res and not texts
    return "", False


def _events_from_lines(lines, sid: str, project: str, dev_real: str, quota: int, subs: dict, state: dict = None) -> Tuple[List[dict], int]:
    """Hook inputs derived from one session's records (chronological): tool_use -> PreToolUse + PostToolUse, a real user prompt -> UserPromptSubmit,
    the end of a turn -> Stop, Agent/Task tool_use -> SubagentStart (+ the subagent's own calls with agent_id/agent_type) + SubagentStop.
    -> (cases, bad lines). Stops after `quota` events."""
    cases: List[dict] = []
    bad = 0
    turn_open, last_text = False, ""

    def gen(o):
        o = json.loads(_generalize(json.dumps(o), dev_real, project))
        if isinstance(o, dict) and isinstance(o.get("cwd"), str) and not o["cwd"].startswith("{P}"):
            o["cwd"] = "{P}"                       # a session that wandered to another folder still reaches its own project's hooks here
        return o

    def add(event, inp, **kw):
        if len(json.dumps(inp)) > MAX_LARGE:
            return False
        c = {"session": "tr:" + sid, "project": project, "event": event, "input": gen(inp)}
        c.update(kw)
        cases.append(c)
        return True

    def stop():
        nonlocal turn_open
        if turn_open:
            add("Stop", {"hook_event_name": "Stop", "session_id": sid, "cwd": "{P}", "stop_hook_active": False, "transcript_path": "{T}/%s.jsonl" % re.sub(r"[^A-Za-z0-9_-]", "", sid)},
                transcript_text=gen(last_text) if last_text else "")
            turn_open = False

    def tool_events(blocks, cwd, agent=None):
        for b in blocks:
            if not (isinstance(b, dict) and b.get("type") == "tool_use" and isinstance(b.get("name"), str) and isinstance(b.get("input"), dict)):
                continue
            base = {"session_id": sid, "cwd": cwd or "{P}", "permission_mode": "default", "tool_name": b["name"], "tool_input": b["input"], "tool_use_id": str(b.get("id", ""))}
            if agent:
                base.update(agent_id=agent[0], agent_type=agent[1])
            if b["name"] in ("Agent", "Task") and not agent:
                meta = subs.get(b.get("id"))
                aid, atype = (meta["id"], meta["type"]) if meta else ("agent-" + sha8(str(b.get("id"))), str((b["input"] or {}).get("subagent_type") or "general-purpose"))
                add("PreToolUse", dict(base, hook_event_name="PreToolUse"))
                add("SubagentStart", {"hook_event_name": "SubagentStart", "session_id": sid, "cwd": cwd or "{P}", "agent_id": aid, "agent_type": atype})
                if meta:
                    n = 0
                    for sl in meta["lines"]:
                        if n >= 12:
                            break
                        try:
                            sr = json.loads(sl)
                        except ValueError:
                            continue
                        if sr.get("type") == "assistant":
                            sb = (sr.get("message") or {}).get("content")
                            if isinstance(sb, list):
                                before = len(cases)
                                tool_events(sb, sr.get("cwd") or cwd, (aid, atype))
                                n += len(cases) - before
                add("SubagentStop", {"hook_event_name": "SubagentStop", "session_id": sid, "cwd": cwd or "{P}", "agent_id": aid, "agent_type": atype, "stop_hook_active": False})
                add("PostToolUse", dict(base, hook_event_name="PostToolUse", tool_response={}))
            else:
                add("PreToolUse", dict(base, hook_event_name="PreToolUse"))
                add("PostToolUse", dict(base, hook_event_name="PostToolUse", tool_response={}))

    for line in lines:
        if len(cases) >= quota:
            break
        if '"type":"assistant"' not in line and '"type":"user"' not in line and '"type": "assistant"' not in line and '"type": "user"' not in line:
            continue
        try:
            r = json.loads(line)
        except ValueError:
            bad += 1
            continue
        if not isinstance(r, dict) or r.get("isSidechain"):
            continue
        t, msg = r.get("type"), r.get("message")
        if t == "user" and not r.get("isMeta"):
            text, only_result = _text_of(msg)
            if only_result or not text.strip():
                continue
            stop()
            add("UserPromptSubmit", {"hook_event_name": "UserPromptSubmit", "session_id": sid, "cwd": r.get("cwd") or "{P}", "permission_mode": "default", "prompt": text})
            turn_open, last_text = True, ""
        elif t == "assistant" and isinstance(msg, dict) and isinstance(msg.get("content"), list):
            turn_open = True
            texts = [b.get("text", "") for b in msg["content"] if isinstance(b, dict) and b.get("type") == "text"]
            if " ".join(texts).strip():
                last_text = " ".join(texts).strip()
            tool_events(msg["content"], r.get("cwd"))
    stop()
    return cases, bad


def _enc(path: str) -> str:
    return re.sub(r"[^A-Za-z0-9-]", "-", path)


def _project_of_dir(dirname: str, dev_real: str) -> str:
    """Project of a ~/.claude/projects/<folder>: the folder name is the launch directory with / and . turned into - (also worktrees and the ~/<name> symlinks)."""
    try:
        names = [n for n in os.listdir(dev_real) if not n.startswith(".") and os.path.isdir(os.path.join(dev_real, n, ".git"))]
    except OSError:
        return ""
    home = os.path.dirname(dev_real)
    for n in sorted(names, key=len, reverse=True):
        for pre in (_enc(dev_real + "/" + n), _enc(dev_real + "/.worktrees/" + n), _enc(home + "/" + n)):
            if dirname == pre or dirname.startswith(pre + "-"):
                return n
    return ""


def _project_of(cwd: str, dev_real: str) -> str:
    try:
        real = os.path.realpath(cwd)
    except (OSError, ValueError):
        return ""
    dr = os.path.realpath(dev_real)
    if not real.startswith(dr + "/"):
        return ""
    parts = real[len(dr) + 1:].split("/")
    if parts[0] == ".worktrees" and len(parts) > 1:
        return parts[1]
    return "" if parts[0].startswith(".") else parts[0]


def transcript_cases(root: str = None, dev_real: str = None, days: int = 14, limit: int = 3000, min_projects: int = 5, project: str = None,
                     now: float = None, max_file_mb: int = 600) -> Tuple[List[dict], dict]:
    """Hook inputs derived from the Claude Code transcripts (READ-ONLY): -> (cases, info). Quotas: limit split evenly over the projects found; a session
    is skipped when more than 5% of the records it yields do not parse."""
    root = root or os.path.join(real_home(), ".claude/projects")
    dev_real = dev_real or os.path.join(real_home(), "Developer")
    now = time.time() if now is None else now
    cut = now - days * 86400
    per_proj: Dict[str, List[Tuple[float, str]]] = collections.defaultdict(list)
    skipped = collections.Counter()
    for f in glob.glob(os.path.join(root, "*", "*.jsonl")):
        try:
            st = os.stat(f)
        except OSError:
            continue
        if st.st_mtime < cut or st.st_size > max_file_mb << 20:
            skipped["old_or_huge"] += st.st_mtime >= cut
            continue
        cwd = ""
        try:
            with open(f, "r", errors="replace") as fh:
                for i, l in enumerate(fh):
                    if i > 6000:
                        break
                    if '"cwd"' in l:
                        try:
                            cwd = json.loads(l).get("cwd") or ""
                        except ValueError:
                            cwd = ""
                        if cwd:
                            break
        except OSError:
            continue
        p = _project_of_dir(os.path.basename(os.path.dirname(f)), dev_real) or (_project_of(cwd, dev_real) if cwd else "")
        if not p or (project and p != project):
            skipped["no_project"] += 1
            continue
        if os.path.isdir(os.path.join(dev_real, p, ".git")):
            per_proj[p].append((st.st_mtime, f))
        else:
            skipped["no_repo"] += 1
    projs = sorted(per_proj)
    cases: List[dict] = []
    info = {"projects": {}, "skipped": dict(skipped), "sessions": 0, "min_projects": min_projects}
    if not projs:
        return cases, dict(info, projects_found=0)
    bad_sessions = set()

    def derive(p, quota):
        for sess_cap in (max(60, quota // 4), quota):              # first a slice of every session (variety), then whole sessions if the project is still short
            pcases, used, sessions = [], 0, 0
            for _, f in sorted(per_proj[p], reverse=True):
                if used >= quota:
                    break
                sid = os.path.basename(f)[:-6]
                subs = {}
                for mf in glob.glob(os.path.join(root, os.path.basename(os.path.dirname(f)), sid, "subagents", "agent-*.meta.json")):
                    try:
                        m = json.loads(Path(mf).read_text())
                        jf = mf[:-len(".meta.json")] + ".jsonl"
                        if isinstance(m, dict) and m.get("toolUseId") and os.path.getsize(jf) < 20 << 20:
                            subs[m["toolUseId"]] = {"id": os.path.basename(jf)[:-6], "type": str(m.get("agentType") or "general-purpose"), "lines": Path(jf).read_text(errors="replace").splitlines()}
                    except (OSError, ValueError):
                        continue
                try:
                    with open(f, "r", errors="replace") as fh:
                        cs, bad = _events_from_lines(fh, sid, p, dev_real, min(quota - used, sess_cap), subs)
                except OSError:
                    continue
                if bad > max(2, 0.05 * max(1, len(cs))):
                    bad_sessions.add(f)
                    continue
                if cs:
                    pcases += cs
                    used += len(cs)
                    sessions += 1
            if used >= quota:
                break
        return pcases, used, sessions

    quota_p = max(1, limit // len(projs))
    got = {}
    for p in projs:
        got[p] = derive(p, quota_p)
    spare = limit - sum(v[1] for v in got.values())
    full = [p for p in projs if got[p][1] >= quota_p]
    if spare > 0 and full:                                         # projects with few events leave quota unused: the busy ones take it
        for p in full:
            got[p] = derive(p, quota_p + spare // len(full))
    for p in projs:
        cases += got[p][0]
        info["sessions"] += got[p][2]
        info["projects"][p] = got[p][1]
    if bad_sessions:
        info["skipped"]["unparseable_session"] = len(bad_sessions)
    info["projects_found"] = len([p for p, n in info["projects"].items() if n])
    if len(cases) > limit:
        cases = cases[:limit]
    return cases, info


def load_corpus(name: str, project: str = None, limit: int = 0, state: str = None, src_home: str = None) -> Tuple[List[dict], dict]:
    if name == "fixtures":
        cases, info = fixture_cases(), {}
    elif name == "record":
        cases, info = record_cases(state, 0, project), {}
    elif name == "transcripts":
        cases, info = transcript_cases(os.path.join(src_home, ".claude/projects") if src_home else None, os.path.join(src_home, "Developer") if src_home else None,
                                       limit=limit or 3000, project=project)
    else:
        raise ReplayError("unknown corpus %r (fixtures, record, transcripts)" % name)
    if project and name != "transcripts":
        cases = [c for c in cases if c["project"] == project or c["project"] == "@synthetic"]
    if limit and len(cases) > limit:
        cases = cases[:limit]
    return cases, info


# ---------------------------------------------------------------- reports
def render_md(rep: dict, info: dict = None) -> str:
    """Counts, event kinds and sha prefixes only: no input or transcript text."""
    L = ["# Hook replay report", "", "code: %s; corpus: %s; events: %d; projects: %d; %.0f s; disagreements: %d (explained %d, unexplained %d)"
         % (rep.get("code", "?"), rep["corpus"], rep["events"], len(rep["by_project"]), rep["secs"], len(rep["disagreements"]), rep["explained"], rep["unexplained"]), ""]
    L += ["| Event | Events |", "|---|---|"] + ["| %s | %d |" % (k, v) for k, v in sorted(rep["by_event"].items())] + [""]
    L += ["| Project | Events |", "|---|---|"] + ["| %s | %d |" % (k, v) for k, v in sorted(rep["by_project"].items())] + [""]
    L += ["decisions legacy: %s; v1: %s" % (json.dumps(rep["decisions"].get("legacy", {}), sort_keys=True), json.dumps(rep["decisions"].get("v1", {}), sort_keys=True))]
    L += ["effects (stub calls) legacy: %s; v1: %s; events that changed the state folder: legacy %d, v1 %d"
          % (json.dumps(rep.get("effects", {}).get("legacy", {}), sort_keys=True), json.dumps(rep.get("effects", {}).get("v1", {}), sort_keys=True),
             rep.get("state_changes", {}).get("legacy", 0), rep.get("state_changes", {}).get("v1", 0))]
    if (rep.get("stage_shadow") or {}).get("engine"):
        ss = rep["stage_shadow"]
        L += ["stage engine %s (v1 side): stage.shadow would-refusals %d; by kind %s; by stage %s"
              % (ss["engine"], ss["events"], json.dumps(ss["by_kind"], sort_keys=True), json.dumps(ss["by_stage"], sort_keys=True))]
    if rep.get("skipped"):
        L += ["skipped: " + json.dumps(rep["skipped"], sort_keys=True)]
    if info:
        L += ["transcripts: " + json.dumps({k: info[k] for k in ("sessions", "projects_found") if k in info})]
    L += ["", "## Disagreements", ""]
    if not rep["disagreements"]:
        L += ["none"]
    groups = collections.OrderedDict()
    for d in rep["disagreements"]:
        key = (d["classification"], d["why"], d["project"], d["event"] + ("/" + d["tool"] if d["tool"] else ""), ",".join(d["dims"]), d["legacy"]["decision"], d["v1"]["decision"])
        groups.setdefault(key, []).append(d)
    for (cl, why, proj, ev, dims, ld, vd), ds in groups.items():
        L += ["- [%s] %s %s %s: %s; legacy %s, v1 %s; %d event(s), session(s) %s, first input %s, reason sha legacy/v1 %s/%s%s"
              % (cl, ds[0]["corpus"], proj, ev, dims, ld, vd, len(ds), ",".join(sorted({d["session"] for d in ds})), ds[0]["input_sha"], ds[0]["legacy"]["reason_sha"][:8],
                 ds[0]["v1"]["reason_sha"][:8], (" (" + why + ")") if why else "")]
    return "\n".join(L) + "\n"


REPORT_HEADER = "# Hook replay report"


def check_report_path(path: str, state: str = None) -> str:
    """L4: where `shipm hooks replay --report` may write. The file must be a .md, resolve (symlinks followed on the folder) inside this repo, the state
    folder or the temp folder, not be a symlink itself, and, if it exists, be an earlier replay report (so a config or settings file can never be
    overwritten by a mistyped or injected path). -> the absolute path; raises ReplayError."""
    from . import io as hio
    if not path or not isinstance(path, str) or "\x00" in path:
        raise ReplayError("--report needs a file path")
    p = os.path.abspath(os.path.expanduser(path))
    if not p.endswith(".md"):
        raise ReplayError("--report must name a .md file: " + path)
    roots = [str(Path(__file__).resolve().parents[2]), state or hio.state_dir(), tempfile.gettempdir(), "/tmp"]
    if not any(hio.inside(p, r) for r in roots):
        raise ReplayError("--report must be inside the repository, the state folder or the temp folder: " + path)
    if os.path.islink(p):
        raise ReplayError("--report must not be a symlink: " + path)
    if os.path.lexists(p):
        try:
            with open(p, "rb") as f:
                head = f.read(len(REPORT_HEADER))
        except OSError as e:
            raise ReplayError("--report file is not readable: %s" % e)
        if head != REPORT_HEADER.encode():
            raise ReplayError("--report would overwrite a file that is not a replay report: " + path)
    return p


def write_report(rep: dict, path: str, info: dict = None) -> None:
    p = check_report_path(path)
    body = render_md(rep, info)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o644)
    with os.fdopen(fd, "w") as f:
        f.write(body)


def write_full_local(rep: dict, state: str = None) -> str:
    """Full texts of every disagreement in a local-only file under <state>/v1 (0600)."""
    from . import io as hio
    state = state or hio.state_dir()
    p = os.path.join(state, "v1", "replay-full-%d.json" % int(time.time()))
    hio.atomic_json(p, rep, 0o600)
    return p
