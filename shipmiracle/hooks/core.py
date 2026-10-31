"""The hook dispatcher core (spec docs/plans/2026-10-20-p4-spec.md section 2): Ctx, Result, PIPELINES, register, run_module, merge, main.
Import budget: only os, json, re, time at module level (plus the sibling io module); everything else is imported where it is used.
Every hook fails open: a module that raises counts as "no output" (logged); main never raises and exits 0 on internal errors.
Modules live in shipmiracle/hooks/<file>.py (activity, plan_approval, agents, flow, ...), are imported only when their slot matches, and call
register(event, name, matcher, fn, project_module) at import time. fn(ctx) returns a Result or None."""
from __future__ import annotations

import json
import os
import re
import time

from . import io as hio

MODES = ("legacy", "shadow", "v1")
MAX_CONFIG_BYTES = 1 << 20
MAX_JSON_BYTES = 4 << 20
LARGE_OUTPUT = 4000
CTX_EVENTS = ("UserPromptSubmit", "PreToolUse", "PostToolUse", "SessionStart", "SubagentStart")   # events whose hookSpecificOutput takes additionalContext
DENY_EVENTS = ("PreToolUse",)                                                                         # block -> permissionDecision deny
BLOCK_EVENTS = ("Stop", "SubagentStop")                                                               # block -> {"decision":"block","reason":...}
# every other event: a block is the legacy exit 2 with the reasons on stderr

PROJECT_SH = {"shipmiracle_state": "shipm-state.sh", "session_start": "session-start.sh", "block_secrets": "block-secrets.sh", "stop_fast": "stop-gate.sh",
              "stop_tests": "stop-gate.sh", "save_plan": "save-plan.sh", "model_switch": "model-switch.sh"}
SWITCH = {"context": "tokens.nudge"}      # off by default
MODULE_FILE = {"keep_awake": "activity", "guard_hook": "activity", "plan_approval": "plan_approval", "agent_cap": "agents", "agent_state": "agents",
               "flow": "flow", "stage": "stage", "autopilot": "autopilot", "keep_going": "keep_going", "limit_wait": "limit_wait", "plan_capture": "statusline", "context": "context",
               "shipmiracle_state": "project", "session_start": "project", "block_secrets": "project", "stop_fast": "project", "stop_tests": "project",
               "save_plan": "project", "model_switch": "project"}


class Result:
    """What one module returns (a plain class, not a dataclass: dataclasses+inspect cost ~3 ms of import on every hook call)."""
    __slots__ = ("block", "reason", "additional_context", "system_message", "plain_stdout", "exit_code", "effects")

    def __init__(self, block=False, reason="", additional_context="", system_message="", plain_stdout="", exit_code=0, effects=None):
        self.block = block                      # PreToolUse deny / Stop block / legacy exit 2
        self.reason = reason                    # the text that goes with the block (a legacy exit-2 module: its stderr text)
        self.additional_context = additional_context
        self.system_message = system_message
        self.plain_stdout = plain_stdout        # legacy plain stdout (SessionStart, UserPromptSubmit): byte-identical when nothing structured is present
        self.exit_code = exit_code              # the module's own legacy exit code (informational; the merged exit code is computed)
        self.effects = list(effects) if effects else []   # intended side effects (recorded by shadow runs)

    def __eq__(self, o):
        return isinstance(o, Result) and all(getattr(self, k) == getattr(o, k) for k in self.__slots__)

    def __repr__(self):
        return "Result(%s)" % ", ".join("%s=%r" % (k, getattr(self, k)) for k in self.__slots__)


class Slot:
    """One place in a pipeline: name, tool matcher (regex, full match; "*" = every call), the function once registered."""
    def __init__(self, name: str, matcher: str = "*", project: bool = False, switch: str = ""):
        self.name = name
        self.fn: Optional[Callable] = None
        self.project = project
        self.switch = switch or SWITCH.get(name, "")   # config key that must be on for the module to run ("" = always)
        self.set_matcher(matcher)

    def set_matcher(self, matcher) -> None:
        self.matcher = matcher or "*"
        self.rx = False                 # compiled on first use (most slots never meet a tool call)

    def matches(self, tool: str) -> bool:
        if self.matcher == "*":
            return True
        if self.rx is False:
            self.rx = re.compile(self.matcher)
        return self.rx.fullmatch(tool or "") is not None


def _p(spec) -> List[Slot]:
    out = []
    for item in spec:
        item = (item,) if isinstance(item, str) else tuple(item)
        name = item[0]
        matcher = item[1] if len(item) > 1 else "*"
        project = item[2] if len(item) > 2 else False
        out.append(Slot(name, matcher, project))
    return out


FILE_MODS = "ExitPlanMode|Edit|Write|NotebookEdit|MultiEdit|Bash"
FLOW_PRE = FILE_MODS + "|Read|Grep|Glob|LS|NotebookRead"      # G11: the flow slot also sees the read tools (project isolation and the secret-read rule only)
PIPELINES: Dict[str, List[Slot]] = {                       # spec 2.4: fixed order = today's registration order, globals first, then project modules
    "UserPromptSubmit": _p(["keep_awake", "guard_hook", "plan_approval", "flow", "stage", "autopilot", "context", ("shipmiracle_state", "*", True)]),
    "PreToolUse": _p([("keep_awake", "*"), ("guard_hook", "*"), ("plan_approval", "Edit|Write|NotebookEdit"), ("agent_cap", "Agent|Task"),
                      ("flow", FLOW_PRE), ("stage", "Agent|Task"), ("autopilot", "*"), ("block_secrets", "Bash", True), ("shipmiracle_state", "*", True)]),
    "PostToolUse": _p([("plan_approval", "ExitPlanMode"), ("flow", "Edit|Write|NotebookEdit|MultiEdit"), ("stage", "ExitPlanMode|Agent|Task"), ("autopilot", "Write|Edit|MultiEdit|NotebookEdit"), ("save_plan", "ExitPlanMode", True)]),
    "Stop": _p(["keep_going", "flow", "stage", "autopilot", ("stop_fast", "*", True), ("shipmiracle_state", "*", True)]),
    "Stop--slow": _p([("stop_tests", "*", True)]),
    "SubagentStart": _p(["agent_state"]),
    "SubagentStop": _p(["agent_state", "flow", "stage", "autopilot"]),
    "StopFailure": _p(["limit_wait"]),
    "SessionStart": _p([("session_start", "*", True)]),
    "Notification": _p([("shipmiracle_state", "*", True)]),
    "PreModelSwitch": _p([("model_switch", "*", True)]),
    "StatusLine": _p(["plan_capture"]),
}


def register(event: str, name: str, matcher: Optional[str], fn: Callable, project_module: bool = False) -> Slot:
    """Fill the slot (event, name) of PIPELINES with fn; a name the table does not know is appended at the end of the event's pipeline.
    matcher=None keeps the table's matcher. A project module (runs only for projects the registry owns) is never downgraded to a global one."""
    slots = PIPELINES.setdefault(event, [])
    for s in slots:
        if s.name == name:
            break
    else:
        s = Slot(name, matcher or "*", project_module)
        slots.append(s)
    if matcher is not None:
        s.set_matcher(matcher)
    s.fn = fn
    s.project = s.project or bool(project_module)
    return s


def unregister(event: str, name: str) -> None:
    """Clear the function of a slot (tests); a slot that is not in the table's own list disappears."""
    for s in list(PIPELINES.get(event, [])):
        if s.name == name:
            s.fn = None


def _test() -> bool:
    return os.environ.get("SHIPMIRACLE_TEST") == "1"


# ---------------------------------------------------------------- config (cached file read; no Shipmiracle import on the hot path)
_FILES: Dict[str, Any] = {}


_BAD = object()


def _read_json(path: str, limit: int = MAX_JSON_BYTES, default=None):
    """Parsed JSON file or `default`; cached per process (a hook call is one process)."""
    val = _FILES.get(path, None)
    if val is None:
        val = _BAD
        try:
            with open(path, "rb") as f:
                raw = f.read(limit + 1)
            if len(raw) <= limit:
                val = json.loads(raw.decode("utf-8", "replace"))
        except (OSError, ValueError):
            val = _BAD
        _FILES[path] = _BAD if val is None else val        # a file holding JSON null counts as unreadable
    return default if val is _BAD else val


def config_path() -> str:
    """<config>/config.json with shipmiracle.paths' rules: SHIPMIRACLE_CONFIG / SHIPMIRACLE_HOME only under SHIPMIRACLE_TEST=1, else the account's home (pwd), not $HOME."""
    if _test() and os.environ.get("SHIPMIRACLE_CONFIG"):
        return os.path.join(os.environ["SHIPMIRACLE_CONFIG"], "config.json")
    if _test() and os.environ.get("SHIPMIRACLE_HOME"):
        home = os.environ["SHIPMIRACLE_HOME"]
    else:
        import pwd
        home = pwd.getpwuid(os.getuid()).pw_dir
    return os.path.join(home, ".config", "shipmiracle", "config.json")


def config_get(key: str, default=None):
    d = _read_json(config_path(), MAX_CONFIG_BYTES, {})
    return d.get(key, default) if isinstance(d, dict) else default


def projects_dir(home: str, env=None) -> str:
    """The projects folder (resolved): SHIPMIRACLE_DEV, else config paths.projects_dir (absolute or ~/...), else <home>/Developer."""
    env = os.environ if env is None else env
    v = env.get("SHIPMIRACLE_DEV")
    if not v:
        c = config_get("paths.projects_dir", None)
        if isinstance(c, str) and c and "\0" not in c and (c.startswith("/") or c.startswith("~/")):
            v = os.path.join(home, c[2:]) if c.startswith("~/") else c
    return os.path.realpath(v or os.path.join(home, "Developer"))


def engine_dir() -> str:
    """The engine checkout this module runs from (shipmiracle/hooks/core.py -> three levels up)."""
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def on(v) -> bool:
    return v is True or (isinstance(v, str) and v.strip().lower() in ("on", "true", "1", "yes"))


def _legacy_scripts_present() -> bool:
    """The registered legacy shell scripts (the gate one is named in the check below) are not part of the public export; they exist only in the private workspace."""
    try:
        return os.path.isfile(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "hooks", "flow-gate.sh"))
    except Exception:
        return False


def mode() -> str:
    """config hooks.dispatcher: legacy (default) | shadow | v1. Anything else, or any error: legacy, EXCEPT when the legacy scripts do not exist
    (a public install): then v1, because the legacy fallback would have nothing to run and every PreToolUse would be refused."""
    try:
        v = config_get("hooks.dispatcher", "legacy")
        m = v if v in MODES else "legacy"
    except Exception:
        m = "legacy"
    return m if (m == "v1" or _legacy_scripts_present()) else "v1"


# ---------------------------------------------------------------- context
class Ctx:
    def __init__(self, raw: bytes, event: str, env=None):
        self.raw = raw if isinstance(raw, bytes) else bytes(raw or b"")
        self.env = os.environ if env is None else env
        self.event = event
        self.data: dict = {}
        try:
            d = json.loads(self.raw.decode("utf-8", "replace")) if self.raw.strip() else {}
            self.data = d if isinstance(d, dict) else {}
        except ValueError:
            self.data = {}
        self.tool_name = self._s("tool_name")
        self.session_id = self._s("session_id")
        self.sid = re.sub(r"[^A-Za-z0-9_-]", "", self.session_id) or "x"        # the gate's session key
        self.agent_id = self._s("agent_id")
        self.agent_type = self._s("agent_type")
        self.pd = os.path.realpath(self.env.get("CLAUDE_PROJECT_DIR") or self._s("cwd") or "/")
        self.state = hio.state_dir()
        self.home = os.path.expanduser("~")
        self.dev = projects_dir(self.home, self.env)
        self.ws = self.env.get("SHIPMIRACLE_WS") or engine_dir()
        self.quiet = bool(self.env.get("SHIPMIRACLE_QUIET"))
        self.now = time.time()
        self._project: Optional[str] = None
        self._owned: Dict[str, bool] = {}

    def _s(self, key: str) -> str:
        v = self.data.get(key)
        return v if isinstance(v, str) else ""

    @property
    def is_agent(self) -> bool:
        return bool(self.agent_id)

    @property
    def project(self) -> str:
        """Project name: shipmiracle.projects when it can resolve the folder, else the folder's basename."""
        if self._project is None:
            name = os.path.basename(self.pd)
            try:
                from shipmiracle import projects
                p = projects.resolve(self.pd, self.dev)
                name = p.name if p is not None else name
            except Exception:
                pass
            self._project = name
        return self._project

    def memo_json(self, path, default=None):
        """Cached JSON read of a file (parse failure or missing file: default)."""
        return _read_json(str(path), MAX_JSON_BYTES, default)

    def config(self, key: str, default=None):
        return config_get(key, default)

    def project_owned(self, hook_name: str) -> bool:
        if hook_name not in self._owned:
            self._owned[hook_name] = project_owned(self.pd, hook_name, self.dev)
        return self._owned[hook_name]


def project_owned(pd: str, hook_name: str, dev: Optional[str] = None) -> bool:
    """True when the dispatcher runs project module `hook_name` for folder pd: the project is in the registry AND its .claude/settings.json no
    longer registers the matching .claude/hooks/<x>.sh (a hook never runs twice). Any error: False.
    Fast path (no Shipmiracle import): the registry id is sha256("shipmiracle-project:" + realpath)[:12] (shipmiracle.projects.project_id); a folder that is not
    a direct child of the Developer folder (subfolder, worktree) is resolved with shipmiracle.projects, lazily."""
    try:
        sh = PROJECT_SH.get(hook_name)
        if not sh:
            return False
        real = os.path.realpath(pd)
        reg = _read_json(os.path.join(os.path.dirname(config_path()), "registry.json"), MAX_JSON_BYTES, None)
        projs = reg.get("projects") if isinstance(reg, dict) and reg.get("v") == 1 else None
        if not isinstance(projs, dict):
            return False
        devp = os.path.realpath(dev) if dev else projects_dir(os.path.expanduser("~"))
        if os.path.dirname(real) == devp:
            import hashlib
            pid = hashlib.sha256(("shipmiracle-project:" + real).encode("utf-8", "surrogateescape")).hexdigest()[:12]
        else:
            from shipmiracle import projects
            p = projects.resolve(real, devp)
            if p is None:
                return False
            pid, real = p.id, p.real
        if pid not in projs:
            return False
        for fn in ("settings.json", "settings.local.json"):
            try:
                with open(os.path.join(real, ".claude", fn), "rb") as f:
                    if (".claude/hooks/" + sh).encode() in f.read(MAX_JSON_BYTES):
                        return False
            except FileNotFoundError:
                continue
        return True
    except Exception:
        return False


# ---------------------------------------------------------------- running modules
def _injected(name: str) -> bool:
    return _test() and name in [x.strip() for x in os.environ.get("SHIPMIRACLE_HOOK_INJECT", "").split(",") if x.strip()]


_ISO_TOOLS = frozenset(("Read", "Grep", "Glob", "LS", "NotebookRead", "Edit", "Write", "MultiEdit", "NotebookEdit", "Bash"))
_LOAD_FAILED = set()


def _iso_level(ctx: "Ctx") -> str:
    """The isolation level the gate would use (same rules as flow.iso_level); any error: strict."""
    ov = os.environ.get("SHIPMIRACLE_ISOLATION")
    if _test() and ov in ("strict", "warn", "off"):
        return ov
    try:
        cfg = json.load(open(os.path.join(ctx.ws, "config/flow.json")))
        blk = cfg.get("isolation") if isinstance(cfg, dict) else None
        if not isinstance(blk, dict):
            return "strict"
        pj = blk.get("projects")
        lv = (pj if isinstance(pj, dict) else {}).get(os.path.basename(ctx.pd), blk.get("default", "strict"))
        return lv if lv in ("strict", "warn", "off") else "strict"
    except Exception:
        return "strict"


def _flow_closed(ctx: "Ctx") -> Optional[Result]:
    """G11 F2: the flow module (it holds the project-isolation check) failed to load or crashed. At strict a PreToolUse for Bash and the file tools is REFUSED
    (fail closed); at warn/off, and for every other event, the failure stays a logged non-event."""
    try:
        if ctx.event == "PreToolUse" and ctx.tool_name in _ISO_TOOLS and _iso_level(ctx) == "strict":
            return Result(block=True, reason="Project isolation: the isolation check could not run (the error is in the hook error log); the call is refused until it can. Ask the owner to run `shipm doctor`.")
    except Exception:
        pass
    return None


def run_module(ctx: Ctx, slot: Slot) -> Optional[Result]:
    """Run one module; an exception is logged (flow-errors.log + event hook_module_error) and counts as no output (the flow module at strict: a refusal)."""
    try:
        if _injected(slot.name):
            raise RuntimeError("SHIPMIRACLE_HOOK_INJECT: injected crash in " + slot.name)
        r = slot.fn(ctx)
        return r if isinstance(r, Result) else None
    except BaseException as e:                       # SystemExit and KeyboardInterrupt from a module are crashes too (fail closed for the flow module at strict)
        hio.log_err(slot.name, e)
        hio.emit_event("hook_module_error", {"module": slot.name, "event": ctx.event, "error": type(e).__name__})
        return _flow_closed(ctx) if slot.name == "flow" else None


def _load(slot: Slot, event: str) -> None:
    """Import the file that holds the module (it registers itself). A file that does not exist yet is skipped; any other failure is logged."""
    f = MODULE_FILE.get(slot.name)
    if not f or (_test() and os.environ.get("SHIPMIRACLE_HOOK_NO_LOAD") == "1"):
        return
    try:
        __import__("shipmiracle.hooks." + f)
    except ImportError as e:
        if getattr(e, "name", None) != "shipmiracle.hooks." + f:
            hio.log_err(slot.name, e)
            hio.emit_event("hook_module_error", {"module": slot.name, "event": event, "error": "ImportError"})
            _LOAD_FAILED.add(slot.name)
    except BaseException as e:
        hio.log_err(slot.name, e)
        hio.emit_event("hook_module_error", {"module": slot.name, "event": event, "error": type(e).__name__})
        _LOAD_FAILED.add(slot.name)


def eligible(ctx: Ctx, slot: Slot) -> bool:
    """Cheap checks before anything is imported: the tool matcher and SHIPMIRACLE_QUIET."""
    if not slot.matches(ctx.tool_name):
        return False
    return not (ctx.quiet and not slot.project and slot.name not in ("flow", "autopilot"))   # SHIPMIRACLE_QUIET: global modules return early (flow runs only its own quiet note; project modules ignore SHIPMIRACLE_QUIET)


def permitted(ctx: Ctx, slot: Slot) -> bool:
    """Checks that may read config or the registry; only done for a module that exists."""
    if slot.switch and not on(ctx.config(slot.switch, False)):
        return False
    return not (slot.project and not ctx.project_owned(slot.name))


def run_pipeline(ctx: Ctx, key: str) -> List[Result]:
    """Run EVERY applicable module of the pipeline (no short-circuit) in table order; results of modules that produced one."""
    out = []
    for slot in list(PIPELINES.get(key, [])):
        try:
            if not eligible(ctx, slot):
                continue
            if slot.fn is None:
                _load(slot, ctx.event)
            if slot.fn is None and slot.name == "flow" and "flow" in _LOAD_FAILED:
                fc = _flow_closed(ctx)
                if fc is not None:
                    out.append(fc)
                continue
            if slot.fn is None or not permitted(ctx, slot):
                continue
        except BaseException as e:
            hio.log_err(slot.name, e)
            if slot.name == "flow":
                fc = _flow_closed(ctx)
                if fc is not None:
                    out.append(fc)
            continue
        r = run_module(ctx, slot)
        if r is not None:
            out.append(r)
    return out


# ---------------------------------------------------------------- merge (spec 2.4 rules)
def _join_plain(parts: List[str]) -> str:
    out = ""
    for p in parts:
        out += p if not out or out.endswith("\n") else " " + p
    return out


def merge(event: str, results: List[Result]):
    """-> (stdout bytes, stderr bytes, exit code). No short-circuit: all results contribute, in pipeline order.
    PreToolUse: any block -> permissionDecision deny, reasons joined with a newline. Stop/SubagentStop: any block -> {"decision":"block","reason":joined}.
    Other events: any block -> legacy exit 2 with the reasons on stderr. additionalContext, systemMessage and plain stdout join with a space
    (no extra space after a newline). Nothing structured -> the plain stdout of the modules, byte-identical. Exit code 0 with JSON."""
    results = [r for r in results if r is not None]
    blocks = [(r.reason or "").rstrip("\n") for r in results if r.block]
    ctxs = [r.additional_context for r in results if r.additional_context]
    sysm = [r.system_message for r in results if r.system_message]
    plain = [r.plain_stdout for r in results if r.plain_stdout]
    reason = "\n".join(b for b in blocks if b) or "blocked"
    structured_block = bool(blocks) and (event in DENY_EVENTS or event in BLOCK_EVENTS)
    err, code = b"", 0
    if blocks and not structured_block:
        err, code = (reason + "\n").encode("utf-8", "replace"), 2
    if not (ctxs or sysm or structured_block):
        return _join_plain(plain).encode("utf-8", "surrogateescape"), err, code
    if plain:                                           # structured output exists: the plain texts travel as context
        ctxs.append(_join_plain(plain).strip())
    obj: Dict[str, Any] = {}
    cx = " ".join(ctxs)
    if event in CTX_EVENTS:
        hso: Dict[str, Any] = {"hookEventName": event}
        if event in DENY_EVENTS and blocks:
            hso["permissionDecision"] = "deny"
            hso["permissionDecisionReason"] = reason
        if cx:
            hso["additionalContext"] = cx
        if len(hso) > 1:
            obj["hookSpecificOutput"] = hso
    else:
        if event in BLOCK_EVENTS and blocks:
            obj["decision"], obj["reason"] = "block", reason
        if cx:
            sysm.append(cx)                             # this event has no additionalContext: shown as a message
    if sysm:
        obj["systemMessage"] = " ".join(sysm)
    return (json.dumps(obj) + "\n").encode("utf-8"), err, code


# ---------------------------------------------------------------- entry
def _capture(ctx: Ctx) -> None:
    d = os.environ.get("SHIPMIRACLE_HOOK_CAPTURE")
    if not (_test() and d):
        return
    try:
        tool = re.sub(r"[^A-Za-z0-9_-]", "", ctx.tool_name)
        name = "%s%s-%s.json" % (ctx.event, "-" + tool if tool else "", "agent" if ctx.is_agent else "main")
        hio.ensure_dir(d)
        tmp = os.path.join(d, name + ".%d.tmp" % os.getpid())
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(ctx.raw)
        os.replace(tmp, os.path.join(d, name))
    except Exception as e:
        hio.log_err("capture", e)


OUTER_WD = 9.0                                       # total wall limit of one PreToolUse dispatch at strict (Bash and the file tools); a hang anywhere gets ONE deny
_EMIT = [None, False]                                # (lock, answered): the main thread and the watchdog never both answer


def _outer_watchdog(ctx: "Ctx"):
    try:
        if ctx.event != "PreToolUse" or ctx.tool_name not in _ISO_TOOLS or _iso_level(ctx) != "strict":
            return None
        import threading
        _EMIT[0] = _EMIT[0] or threading.Lock()
        msg = "Project isolation: the isolation check did not finish in time; the call is refused until it can. Ask the owner to run `shipm doctor`."

        def fire():
            with _EMIT[0]:
                if _EMIT[1]:
                    return
                _EMIT[1] = True
                try:
                    os.write(1, (json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": msg}}) + "\n").encode())
                finally:
                    os._exit(0)
        t = threading.Timer(float(os.environ.get("SHIPMIRACLE_GATE_OUTER_WD") or OUTER_WD) if _test() else OUTER_WD, fire)
        t.daemon = True
        t.start()
        return t
    except Exception:
        return None


def run(event: str, raw: bytes, slow: bool = False, env=None, ctx=None):
    """The whole dispatch for one call, without touching stdin/stdout: (stdout bytes, stderr bytes, exit code)."""
    ctx = ctx or Ctx(raw, event, env)
    _capture(ctx)
    results = run_pipeline(ctx, event + "--slow" if slow else event)
    out, err, code = merge(event, results)
    if len(out) + len(err) > LARGE_OUTPUT:
        hio.emit_event("hook_output_large", {"event": event, "bytes": len(out) + len(err)})
    return out, err, code


def _write(fd_stream, data: bytes) -> None:
    if data:
        fd_stream.write(data)
    fd_stream.flush()


def main(argv):
    """argv = [Event, --slow?]. Returns the process exit code (0 on every internal error, with empty output), or the string "legacy" when
    config hooks.dispatcher is legacy or shadow: the shim then runs the legacy scripts itself (shadow/record: stdin is re-served from memory, see shadow.py). Never raises."""
    try:
        if "--selftest" in (argv or []):                  # `shipm init` row 0: proves the registered command starts and imports the dispatcher; reads no stdin, runs no module
            import sys
            sys.stdout.write("shipm-hook selftest ok\n")
            return 0
        args = [a for a in (argv or []) if not a.startswith("--")]
        event = args[0] if args else ""
        m = mode()
        if m != "v1":
            rec = on(config_get("hooks.record", False))
            if m == "shadow" or rec:                      # shadow.py: pre-state snapshot, detached v1 child after exit, optional record (never raises)
                try:
                    from . import shadow
                    shadow.arm(event, argv, m == "shadow", rec)
                except Exception as e:
                    hio.log_err("shadow", e)
            return "legacy"
        import sys
        raw = b""
        try:
            raw = sys.stdin.buffer.read()
        except Exception:
            raw = b""
        ctx0 = Ctx(raw, event)
        _outer_watchdog(ctx0)
        out, err, code = run(event, raw, "--slow" in (argv or []), ctx=ctx0)
        lk = _EMIT[0]
        if lk is not None:
            lk.acquire()                             # blocks while the watchdog is answering (it ends the process); afterwards the watchdog stays silent
            _EMIT[1] = True
        try:
            _write(sys.stdout.buffer, out)
            _write(sys.stderr.buffer, err)
        except Exception:
            pass
        return code
    except BaseException as e:
        hio.log_err("dispatcher", e)
        hio.emit_event("hook_module_error", {"module": "dispatcher", "error": type(e).__name__})
        try:                                              # F2: a crash of the dispatcher itself must not open the isolation check at strict
            import sys
            ctx = Ctx(locals().get("raw") or b"", next((x for x in (argv or []) if not x.startswith("--")), ""))
            fc = _flow_closed(ctx)
            if fc is not None:
                sys.stdout.buffer.write((json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": fc.reason}}) + "\n").encode())
                sys.stdout.buffer.flush()
        except Exception:
            pass
        return 0
