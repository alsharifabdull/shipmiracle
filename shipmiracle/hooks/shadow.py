"""Shadow mode and recording (spec docs/plans/2026-10-20-p4-spec.md section 3). Imported by core.main ONLY when config hooks.dispatcher is shadow
or hooks.record is on; the legacy scripts stay authoritative and run exactly as in legacy mode (the shim runs them).
arm(): reads stdin once (the shim then reads it from an in-memory copy), takes the PRE-STATE snapshot before any legacy script runs, tees stdout/stderr
(the shim still writes them) and registers an atexit handler. At exit: post-state snapshot, flush, stdout/stderr/stdin closed (pointed at /dev/null),
then a detached double-forked child runs v1 against the pre-state in a private 0700 temp folder (SHIPMIRACLE_STATE=<tmp>, spawns stubbed and recorded as
intended effects), compares, appends a `hook_shadow` event (no raw text, only sha prefixes and lengths), optionally appends the redacted record
(`hooks.record`), removes the temp folder and exits. The child never raises, never writes the real state (except the one event and the record),
has a 30 s wall limit. A legacy exit code is inferred: 2 when the shim wrote to stderr, else 0 (the shim writes stderr only for exit 2).
Import budget of the parent path: os, json, re, time (everything else is imported in the child)."""
from __future__ import annotations

import json
import os
import re
import time

CAP_FILE = 1 << 20            # a state file larger than this is not snapshotted (counted in `skipped`)
CAP_TOTAL = 8 << 20
OTHER_FLOW_MAX = 30           # other sessions' flow.<sid>.json read by the gate (< 24 h): context only, never diffed
LOG_FILES = ("flow-events.jsonl", "away-decisions.jsonl", "flow-errors.log")
PID_FILES = ("shipmiracle-keep-awake.pid", "shipmiracle-limit-wait.pid")
CHILD_LIMIT = 30
MAX_CHILDREN = 4              # L8: shadow children running at the same time; further events are skipped and counted (hook_shadow_skipped)
SLOTS_REL = "v1/shadow-children"
RECORD_REL = "v1/hooks-record.jsonl"
RECORD_ROTATE = 10 << 20      # rotate at 10 MB, one rotated file kept: never more than 20 MB on disk
RECORD_DAYS = 7
EPOCH = (1.4e9, 4e9)
EFFECT_KINDS = ("caffeinate", "osascript", "git push", "gh", "pmset")
# same expressions as bin/shipm-watch red() (tests/hooks_replay_test.py compares the source text)
SECRET_RE = re.compile(r"(?i)(token|key|secret|password|authorization|bearer|passwd)([=: ]+)(?:(?:bearer|basic)\s+)?\S+")
B64_RE = re.compile(r"[A-Za-z0-9+/_-]{40,}={0,2}")
MODULE_OF = [(r"flow\..*", "flow"), (r"plan-(pending|model-told)\..*", "plan_approval"), (r".*\.agents\.json|agents\.paused", "agents"), (r"context\..*", "context"),
             (r"(user-active|handoff-.*|.*\.mode\.json)", "guard_hook"), (r"away.*", "keep_going"), (r".*\.limit\.json", "limit_wait"),
             (r"(plan\.json|.*\.model\.json)", "plan_capture/plan_approval")]


PATH_HINT = re.compile(r"/(src|docs|tests?|lib|bin|node_modules|Users|Developer|var|tmp|private|home|\.claude|\.local|\.config)/")

# Extra record redaction (security review M3). SECRET_RE/B64_RE above stay the shipm-watch expressions; these only ADD removals.
_VAL = r"""(?:(?:bearer|basic)\s+)?(?:"[^"]*"|'[^']*'|[^\s"']\S*)"""
KEYWORD_RE = re.compile(r"(?i)(token|key|secret|password|passwd|authorization|bearer)(\\?[\"']?[=: \t]+)" + _VAL)          # "password": "x", password=x, Bearer x
SHORT_KEY_RE = re.compile(r"(?i)(?<![A-Za-z0-9])(pass|pwd|credentials?|dsn)(\\?[\"']?[ \t]*[:=][ \t]*)(?![ \t/])" + _VAL)     # needs an explicit : or =; PWD=/some/dir (a path) stays
USERINFO_RE = re.compile(r"(?i)([a-z][a-z0-9+.-]*://[^\s/:@]*:)[^\s/@]+(@)")                                              # scheme://user:pass@host
MYSQL_RE = re.compile(r"(\bmysql(?:dump|admin)?\b[^\n|;&]*?\s-p)(\S+)")                                                     # mysql -uroot -pSECRET
TOKEN_RES = [re.compile(x) for x in (
    r"AKIA[0-9A-Z]{16}", r"\bgh[pousr]_[A-Za-z0-9]{20,}", r"\bgithub_pat_[A-Za-z0-9_]{20,}", r"\bxox[bpars]-[A-Za-z0-9-]{10,}",
    r"\bsk-ant-[A-Za-z0-9_-]{10,}", r"\bsk-proj-[A-Za-z0-9_-]{10,}", r"\bsk-[A-Za-z0-9]{32,}")]
SECRET_KEY_NAME = re.compile(r"(?i).*(token|secret|passw|pwd|credential|api[_-]?key|private[_-]?key|authorization|dsn).*")


def _secret_shape(seg: str) -> bool:
    """A path segment that looks like a secret: 20+ characters in all three of upper case, lower case and digits, or 32+ characters with high entropy."""
    if len(seg) < 20:
        return False
    if re.search(r"[A-Z]", seg) and re.search(r"[a-z]", seg) and re.search(r"[0-9]", seg):
        return True
    if len(seg) >= 32:
        import math
        n = len(seg)
        h = -sum(c / n * math.log2(c / n) for c in (seg.count(x) for x in set(seg)))
        return h > 4.3
    return False


def _b64(m) -> str:
    """shipm-watch removes every 40+ character run of the base64 alphabet; '/' is in that alphabet, so a long file path would vanish from a record and make it useless
    for replay. A run that starts like a path or holds a typical folder name stays, EXCEPT a segment with a secret shape (mixed case + digits, or high entropy):
    that segment alone is removed."""
    r = m.group(0)
    if not (r.startswith(("/", "~/", "./", "../")) or (r.count("/") >= 2 and PATH_HINT.search(r))):
        return "<redacted>"
    return "/".join("<redacted>" if _secret_shape(x) else x for x in r.split("/"))


def red(text) -> str:
    """A string as it may be stored: secrets and long base64-looking runs removed (normal paths stay)."""
    t = str(text)
    for rx in TOKEN_RES:
        t = rx.sub("<redacted>", t)
    t = USERINFO_RE.sub(lambda m: m.group(1) + "<redacted>" + m.group(2), t)
    t = MYSQL_RE.sub(lambda m: m.group(1) + "<redacted>", t)
    t = KEYWORD_RE.sub(lambda m: m.group(1) + m.group(2) + "<redacted>", t)
    t = SHORT_KEY_RE.sub(lambda m: m.group(1) + m.group(2) + "<redacted>", t)
    return B64_RE.sub(_b64, SECRET_RE.sub(lambda m: m.group(1) + m.group(2) + "<redacted>", t))


def red_obj(o):
    """Deep copy of a JSON value with every string redacted (keys are kept; a string value under a secret-looking key name is removed)."""
    if isinstance(o, str):
        return red(o)
    if isinstance(o, list):
        return [red_obj(x) for x in o]
    if isinstance(o, dict):
        return {k: ("<redacted>" if isinstance(v, str) and v and isinstance(k, str) and SECRET_KEY_NAME.fullmatch(k) else red_obj(v)) for k, v in o.items()}
    return o


# ---------------------------------------------------------------- snapshots (parent and child)
def wanted(name: str, sid: str, proj: str) -> bool:
    """The state files the modules of an event read or write (spec 3: pre-state snapshot)."""
    s, p = re.escape(sid), re.escape(proj or "\0")
    return re.fullmatch(r"flow\.%s\.(json|quiet)|plan-(pending|model-told)\.%s|context\.%s\.json|[^/]+\.agents\.json|%s\.(model|mode|limit)\.json"
                        r"|plan\.json|handoff-now|handoff-told\.%s|away\.json|agents\.paused|user-active|[^/]+\.limit\.json" % (s, s, s, p, p), name) is not None


def snapshot(state: str, sid: str, proj: str, tmpdir: str = "") -> dict:
    """{"files": {name: (bytes, mtime, own)}, "sizes": {log: size}, "pids": {name: text}, "skipped": n}. Never raises."""
    snap = {"files": {}, "sizes": {}, "pids": {}, "skipped": 0}
    total, others = 0, []
    try:
        with os.scandir(state) as it:
            entries = list(it)
    except OSError:
        entries = []
    for e in entries:
        try:
            if not e.is_file(follow_symlinks=False):
                continue
            n = e.name
            if n in LOG_FILES:
                snap["sizes"][n] = e.stat(follow_symlinks=False).st_size
                continue
            other_flow = re.fullmatch(r"flow\.[A-Za-z0-9_-]+\.json", n) is not None and not wanted(n, sid, proj)
            if not (wanted(n, sid, proj) or other_flow):
                continue
            st = e.stat(follow_symlinks=False)
            if other_flow:
                if time.time() - st.st_mtime < 86400:
                    others.append((st.st_mtime, n))
                continue
            if st.st_size > CAP_FILE or total + st.st_size > CAP_TOTAL:
                snap["skipped"] += 1
                continue
            with open(e.path, "rb") as f:
                snap["files"][n] = (f.read(CAP_FILE + 1)[:CAP_FILE], st.st_mtime, True)
            total += st.st_size
        except OSError:
            continue
    for _, n in sorted(others, reverse=True)[:OTHER_FLOW_MAX]:
        try:
            with open(os.path.join(state, n), "rb") as f:
                snap["files"][n] = (f.read(CAP_FILE), os.stat(os.path.join(state, n)).st_mtime, False)
        except OSError:
            pass
    try:                                                   # the user-level agent manifest the gate digests
        p = os.path.join(state, "v1", "agents.json")
        with open(p, "rb") as f:
            snap["files"]["v1/agents.json"] = (f.read(CAP_FILE), os.stat(p).st_mtime, True)
    except OSError:
        pass
    for n in PID_FILES:
        try:
            with open(os.path.join(tmpdir or os.environ.get("TMPDIR") or "/tmp", n), "r", errors="ignore") as f:
                snap["pids"][n] = f.read(64).strip()
        except OSError:
            pass
    return snap


def tail_lines(path: str, offset: int, cap: int = 1 << 18) -> list:
    """Complete lines appended to `path` after byte `offset` (at most `cap` bytes)."""
    try:
        with open(path, "rb") as f:
            f.seek(offset)
            data = f.read(cap)
    except OSError:
        return []
    return [l for l in data.decode("utf-8", "replace").split("\n") if l.strip()]


# ---------------------------------------------------------------- normalisation and decision records
def norm(o):
    if isinstance(o, bool) or o is None:
        return o
    if isinstance(o, (int, float)):
        return 0 if EPOCH[0] < o < EPOCH[1] else o
    if isinstance(o, list):
        return [norm(x) for x in o]
    if isinstance(o, dict):
        return {k: (0 if k == "pid" and isinstance(v, int) else norm(v)) for k, v in o.items()}
    return o


def canon(name: str, entry, roots=()):
    """Comparable form of a state file: None (absent), canonical JSON text, or text with epoch-like numbers zeroed."""
    if entry is None:
        return None
    text = entry[0].decode("utf-8", "replace")
    for r in roots:
        if r:
            text = text.replace(r, "<S>")
    try:
        o = json.loads(text)
    except ValueError:
        return re.sub(r"\b1[4-9]\d{8}(\.\d+)?\b", "0", text).strip()
    if isinstance(o, dict) and name.startswith("flow."):
        o.pop("env_override_logged", None)            # the child's SHIPMIRACLE_STATE override is its own, not the gate's decision
    return json.dumps(norm(o), sort_keys=True)


def collapse(s) -> str:
    return " ".join(str(s or "").split())


def sha(s: str) -> str:
    import hashlib
    return hashlib.sha256(s.encode("utf-8", "replace")).hexdigest()[:12]


def summarize(event: str, out: bytes, err: bytes, code: int) -> dict:
    """The comparable record of one hook answer: decision allow|deny|block|none, sha prefixes and lengths of the reason, the context and the
    system message (whitespace collapsed; plain stdout counts as context; exit 2 with stderr text equals a JSON deny/block with that text)."""
    txt, etxt = out.decode("utf-8", "replace"), err.decode("utf-8", "replace")
    decision, reason, ctx, sysm = "none", "", "", ""
    obj = None
    if txt.strip():
        try:
            obj = json.loads(txt)
        except ValueError:
            obj = None
        if isinstance(obj, dict):
            h = obj.get("hookSpecificOutput") if isinstance(obj.get("hookSpecificOutput"), dict) else {}
            decision = "allow"
            if h.get("permissionDecision") == "deny":
                decision, reason = "deny", str(h.get("permissionDecisionReason") or "")
            elif obj.get("decision") == "block":
                decision, reason = "block", str(obj.get("reason") or "")
            ctx, sysm = str(h.get("additionalContext") or ""), str(obj.get("systemMessage") or "")
        else:
            decision, ctx = "allow", txt
    if code == 2:
        decision, reason = ("deny" if event == "PreToolUse" else "block"), etxt
    reason, ctx, sysm = collapse(reason), collapse(ctx), collapse(sysm)
    return {"decision": decision, "reason_sha": sha(reason) if reason else "", "reason_len": len(reason), "ctx_sha": sha(ctx) if ctx else "",
            "sysmsg_sha": sha(sysm) if sysm else "", "exit": 2 if code == 2 and event not in ("PreToolUse", "Stop", "SubagentStop") else 0}


def effect_kinds(effects) -> list:
    out = []
    for e in effects:
        for k in EFFECT_KINDS:
            if str(e).startswith(k):
                out.append(k)
                break
    return sorted(set(out))


def module_of(name: str) -> str:
    for rx, m in MODULE_OF:
        if re.fullmatch(rx, name):
            return m
    return "?"


# ---------------------------------------------------------------- the v1 run in the private temp folder
def _stubs(tmp: str) -> str:
    d = os.path.join(tmp, "bin")
    os.mkdir(d, 0o700)
    for n in ("caffeinate", "osascript", "gh", "pmset"):
        p = os.path.join(d, n)
        with open(p, "w") as f:
            f.write("#!/bin/sh\nexit 0\n")
        os.chmod(p, 0o700)
    return d


def write_pre(tmp_state: str, pre: dict) -> None:
    os.makedirs(tmp_state, mode=0o700, exist_ok=True)
    for name, (data, mtime, _own) in pre["files"].items():
        p = os.path.join(tmp_state, name)
        os.makedirs(os.path.dirname(p), mode=0o700, exist_ok=True)
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.utime(p, (mtime, mtime))


def run_v1(event: str, raw: bytes, tmp_state: str, tmp: str):
    """v1 over the temp state. -> (stdout, stderr, exit, effects list, error count). Global modules only: a project module is owned by the project's
    own settings in shadow, so the legacy side never runs it. os.environ is changed (this is the throw-away child)."""
    bindir = _stubs(tmp)
    os.makedirs(os.path.join(tmp, "tmp"), mode=0o700, exist_ok=True)
    from . import io as hio0
    hio0._STATE_OVERRIDE = tmp_state                  # io.state_dir() ignores SHIPMIRACLE_STATE outside a test sandbox (M4); the throw-away child sets it in-process
    os.environ.update({"SHIPMIRACLE_STATE": tmp_state, "TMPDIR": os.path.join(tmp, "tmp"), "SHIPMIRACLE_HOOK_NO_SPAWN": "1",
                       "PATH": bindir + ":" + os.environ.get("PATH", "/usr/bin:/bin")})
    from . import core
    from . import io as hio
    errors = []
    hio.emit_event = lambda kind, data=None, project=None: errors.append(kind) or True       # module-error events must not reach the real log
    from . import activity
    spawned = []
    activity.spawn_caffeinate = lambda args, pidfile: spawned.append("caffeinate " + " ".join(map(str, args))) or True
    ctx = core.Ctx(raw, event)
    ctx.ws = os.path.join(tmp, "ws")      # L2: limit_wait's <ws>/reports log (the one module write outside the state folder) goes to the throw-away folder.
    # SHIPMIRACLE_WS itself is not changed: the gate reads it at import and protects the REAL workspace paths, so its decision must stay the one the legacy run made.
    saved = core.PIPELINES.get(event, [])
    core.PIPELINES[event] = [s for s in saved if not s.project]
    try:
        results = core.run_pipeline(ctx, event)
    finally:
        core.PIPELINES[event] = saved
    out, err, code = core.merge(event, results)
    eff = [e for r in results for e in r.effects] + spawned
    nerr = len(tail_lines(os.path.join(tmp_state, "flow-errors.log"), 0))      # module errors and the gate's own errors both land here (log_err / flow's log)
    return out, err, code, eff, nerr


def compare(st: dict, runner=None, limit: int = CHILD_LIMIT) -> dict:
    """Run v1 against the pre-state in a private temp folder and compare with the legacy result in `st`. -> the hook_shadow data dict.
    `runner` replaces run_v1 (tests). The temp folder is always removed."""
    import shutil
    import tempfile
    import signal
    event, raw, sid, proj = st["event"], st["raw"], st["sid"], st["proj"]
    tmp = tempfile.mkdtemp(prefix="shipmiracle-shadow-")
    t0 = time.time()
    rec = {"event": event, "tool": st.get("tool", ""), "project": proj, "sid8": sid[:8]}

    def on_alarm(sig, frm):
        raise TimeoutError("shadow child over %d s" % limit)
    try:
        try:
            signal.signal(signal.SIGALRM, on_alarm)
            signal.alarm(limit)
        except ValueError:                                         # not the main thread (tests): no wall limit
            pass
        tmp_state = os.path.join(tmp, "state")
        write_pre(tmp_state, st["pre"])
        out, err, code, eff, nerr = (runner or run_v1)(event, raw, tmp_state, tmp)
        signal.alarm(0)
        lo, le, lc = st["legacy"]
        leg, v1 = summarize(event, lo, le, lc), summarize(event, out, err, code)
        post, pre = st["post"], st["pre"]
        v1_snap = snapshot(tmp_state, sid, proj, os.path.join(tmp, "tmp"))
        roots = [tmp_state, st["state"]]
        diff = []
        for n in sorted(set(post["files"]) | set(v1_snap["files"])):
            a, b = post["files"].get(n), v1_snap["files"].get(n)
            if (a and not a[2]) or (b and not b[2]):
                continue                                           # other sessions' flow files: context only
            if canon(n, a, roots) != canon(n, b, roots):
                diff.append(n)
        for n in ("flow-events.jsonl", "away-decisions.jsonl"):    # lines appended by this event
            la = [l for l in tail_lines(os.path.join(st["state"], n), pre["sizes"].get(n, 0)) if n != "flow-events.jsonl" or '"session": "%s"' % sid in l]
            lb = [l for l in tail_lines(os.path.join(tmp_state, n), 0) if n != "flow-events.jsonl" or '"session": "%s"' % sid in l]
            na, nb = _norm_lines(la), _norm_lines(lb)
            if na != nb:
                diff.append(n)
        leg_eff = sorted({"caffeinate" for n, v in post["pids"].items() if v != pre["pids"].get(n, "")})
        eff_diff = sorted(set(leg_eff) ^ set(effect_kinds(eff)))
        leg_err = len(tail_lines(os.path.join(st["state"], "flow-errors.log"), pre["sizes"].get("flow-errors.log", 0)))
        rec.update({"legacy": leg, "v1": v1, "state_diff": diff, "effects_diff": eff_diff, "errors": {"legacy": leg_err, "v1": nerr},
                    "ms": int((time.time() - t0) * 1000), "skipped": pre["skipped"]})
        rec["agree"] = (leg == v1 and not diff and not eff_diff and nerr <= leg_err)
    except BaseException as e:                                     # incl. the alarm: recorded as an error, never raised
        rec.update({"error": type(e).__name__, "agree": None, "ms": int((time.time() - t0) * 1000)})
    finally:
        try:
            signal.alarm(0)
        except Exception:
            pass
        shutil.rmtree(tmp, ignore_errors=True)
    return rec


def _norm_lines(lines) -> list:
    out = []
    for l in lines:
        try:
            o = json.loads(l)
        except ValueError:
            out.append(re.sub(r"\d{10}", "0", l))
            continue
        if isinstance(o, dict) and o.get("event") == "gate_env_override" and "SHIPMIRACLE_STATE" in (o.get("vars") or []):
            continue
        out.append(json.dumps(norm(o), sort_keys=True))
    return out


def emit(rec: dict, base: str) -> bool:
    """The hook_shadow event in the REAL events.jsonl (base). No raw text: ids are sha prefixes, 8-char session prefix, counts."""
    try:
        from shipmiracle import events
        data = {k: v for k, v in rec.items() if k != "project"}
        data["project_name"] = rec.get("project", "")
        return events.emit("hook_shadow", data, src="hooks", base=base)
    except Exception:
        return False


# ---------------------------------------------------------------- recording (hooks.record)
def record_path(state: str) -> str:
    return os.path.join(state, RECORD_REL)


def prune(path: str, now: float = None) -> None:
    """Drop record lines older than 7 days (atomic rewrite); the rotated file goes when its mtime is older."""
    now = time.time() if now is None else now
    cut = now - RECORD_DAYS * 86400
    try:
        if os.path.getmtime(path + ".1") < cut:
            os.unlink(path + ".1")
    except OSError:
        pass
    try:
        with open(path, "rb") as f:
            first = f.readline()
        if json.loads(first.decode("utf-8", "replace")).get("ts", now) >= cut:
            return
    except (OSError, ValueError, AttributeError):
        return
    keep = []
    with open(path, "rb") as f:
        for l in f:
            try:
                if json.loads(l.decode("utf-8", "replace")).get("ts", now) >= cut:
                    keep.append(l)
            except ValueError:
                pass
    tmp = "%s.%d.tmp" % (path, os.getpid())
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(b"".join(keep))
    os.replace(tmp, path)


def append_record(state: str, obj: dict, rotate_at: int = RECORD_ROTATE, now: float = None) -> bool:
    """Append one redacted line to <state>/v1/hooks-record.jsonl (0600). Rotates at `rotate_at` bytes (one rotated file), prunes lines over 7 days."""
    from . import io as hio
    path = record_path(state)
    try:
        hio.ensure_dir(os.path.dirname(path))
        prune(path, now)
        try:
            if os.path.getsize(path) >= rotate_at:
                os.replace(path, path + ".1")
        except OSError:
            pass
        line = json.dumps(red_obj(obj), separators=(",", ":"))
        hio.append_line(path, line, 0o600, inside_root=state, fix_mode=True)      # O_NOFOLLOW, must resolve inside the state folder, fchmod on the opened file
        return True
    except Exception:
        return False


def make_record(st: dict) -> dict:
    lo, le, lc = st["legacy"]
    try:
        inp = json.loads(st["raw"].decode("utf-8", "replace"))
    except ValueError:
        inp = st["raw"].decode("utf-8", "replace")
    pre = {n: v[0].decode("utf-8", "replace") for n, v in st["pre"]["files"].items() if v[2]}
    return {"ts": int(time.time()), "event": st["event"], "project": st["proj"], "input": inp, "pre_state": pre,
            "legacy_result": {"exit": lc, "stdout": lo.decode("utf-8", "replace"), "stderr": le.decode("utf-8", "replace")}}


# ---------------------------------------------------------------- arming (parent process, legacy path)
class _Tee:
    """Wraps stdout/stderr so the shim's output is also kept in memory. Accepts str (shim stderr) and bytes (shim stdout.buffer)."""
    def __init__(self, real):
        self.real = real
        self.data = bytearray()

    @property
    def buffer(self):
        return self

    def write(self, d):
        if isinstance(d, str):
            self.data += d.encode("utf-8", "replace")
            return self.real.write(d)
        self.data += d
        return self.real.buffer.write(d)

    def flush(self):
        self.real.flush()

    def __getattr__(self, n):
        return getattr(self.real, n)


def arm(event: str, argv, shadow_on: bool, record_on: bool, state: str = None) -> None:
    """Called by core.main in legacy/shadow mode. Never raises; on any failure the legacy run is unaffected (stdin is restored from memory)."""
    import io
    import sys
    try:
        raw = sys.stdin.buffer.read()
    except Exception:
        raw = b""
    sys.stdin = io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8")
    try:
        if not event or "--slow" in (argv or []) or not (shadow_on or record_on):
            return
        from . import io as hio
        state = state or hio.state_dir()
        try:
            d = json.loads(raw.decode("utf-8", "replace")) if raw.strip() else {}
        except ValueError:
            d = {}
        d = d if isinstance(d, dict) else {}
        sid = re.sub(r"[^A-Za-z0-9_-]", "", d.get("session_id") if isinstance(d.get("session_id"), str) else "") or "x"
        pd = os.path.realpath(os.environ.get("CLAUDE_PROJECT_DIR") or (d.get("cwd") if isinstance(d.get("cwd"), str) else "") or "/")
        proj = os.path.basename(pd)
        st = {"event": event, "raw": raw, "sid": sid, "proj": proj, "state": state, "tool": d.get("tool_name") if isinstance(d.get("tool_name"), str) else "",
              "shadow": shadow_on, "record": record_on, "pre": snapshot(state, sid, proj)}
        sys.stdout, sys.stderr = _Tee(sys.stdout), _Tee(sys.stderr)
        st["tees"] = (sys.stdout, sys.stderr)
        import atexit
        atexit.register(finish, st)
    except Exception:
        return


def finish(st: dict) -> None:
    """atexit: post-state, close the hook's streams, then the detached double-forked child. Never raises."""
    import sys
    try:
        so, se = st["tees"]
        st["post"] = snapshot(st["state"], st["sid"], st["proj"])
        st["legacy"] = (bytes(so.data), bytes(se.data), 2 if se.data else 0)
        for s in (so, se):
            try:
                s.flush()
            except Exception:
                pass
        dn = os.open(os.devnull, os.O_RDWR)
        for fd in (0, 1, 2):
            os.dup2(dn, fd)
        if dn > 2:
            os.close(dn)
        pid = os.fork()
        if pid == 0:
            try:
                os.setsid()
                if os.fork() != 0:
                    os._exit(0)
                child(st)
            finally:
                os._exit(0)
        os.waitpid(pid, 0)
    except BaseException:
        pass


def acquire_slot(state: str, maxn: int = MAX_CHILDREN, pid: int = None, now: float = None) -> int:
    """Register this child in <state>/v1/shadow-children (flock-guarded, lines 'pid timestamp'). Entries of dead processes or older than the child
    limit + 30 s are dropped. -> 0 and registered when there was room, else the number of children running (nothing registered)."""
    import fcntl
    from . import io as hio
    pid = os.getpid() if pid is None else pid
    now = time.time() if now is None else now
    path = os.path.join(state, SLOTS_REL)
    hio.ensure_dir(os.path.dirname(path))
    if not hio.inside(path, state):
        raise PermissionError("refusing to write outside the state folder: " + path)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        live = []
        for l in os.read(fd, 4096).decode("ascii", "ignore").splitlines():
            try:
                p_, t_ = l.split()
                p_, t_ = int(p_), float(t_)
                if now - t_ < CHILD_LIMIT + 30 and p_ != pid:
                    os.kill(p_, 0)
                    live.append((p_, t_))
            except (ValueError, OSError):
                continue
        full = len(live) >= maxn
        if not full:
            live.append((pid, now))
        os.ftruncate(fd, 0)
        os.lseek(fd, 0, 0)
        os.write(fd, "".join("%d %.0f\n" % x for x in live).encode("ascii"))
        return len(live) if full else 0
    finally:
        os.close(fd)                                    # releases the flock


def release_slot(state: str, pid: int = None) -> None:
    import fcntl
    pid = os.getpid() if pid is None else pid
    path = os.path.join(state, SLOTS_REL)
    try:
        fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
    except OSError:
        return
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        keep = [l for l in os.read(fd, 4096).decode("ascii", "ignore").splitlines() if l.split()[:1] != [str(pid)]]
        os.ftruncate(fd, 0)
        os.lseek(fd, 0, 0)
        os.write(fd, "".join(l + "\n" for l in keep).encode("ascii"))
    except OSError:
        pass
    finally:
        os.close(fd)


def emit_skipped(rec: dict, base: str) -> bool:
    """hook_shadow_skipped: one event per shadow comparison not run because MAX_CHILDREN were already running."""
    try:
        from shipmiracle import events
        return events.emit("hook_shadow_skipped", rec, src="hooks", base=base)
    except Exception:
        return False


def child(st: dict) -> None:
    """The grandchild: compare, event, record. Returns normally; the caller exits."""
    try:
        test = os.environ.get("SHIPMIRACLE_TEST") == "1"
        pf = os.environ.get("SHIPMIRACLE_SHADOW_PIDFILE") if test else ""
        if pf:
            with open(pf, "w") as f:
                f.write(str(os.getpid()))
        if st.get("shadow"):
            maxn = int(os.environ.get("SHIPMIRACLE_SHADOW_MAX") or MAX_CHILDREN) if test else MAX_CHILDREN
            try:
                busy = acquire_slot(st["state"], maxn)
            except Exception:
                busy = 0                                           # a counter that cannot be used must not stop the shadow run
            if busy:
                emit_skipped({"event": st["event"], "running": busy, "max": maxn}, st["state"])
            else:
                try:
                    runner = None
                    if test and os.environ.get("SHIPMIRACLE_SHADOW_TEST_RUNNER"):
                        runner = _test_runner(os.environ["SHIPMIRACLE_SHADOW_TEST_RUNNER"])
                    emit(compare(st, runner, int(os.environ.get("SHIPMIRACLE_SHADOW_LIMIT") or CHILD_LIMIT) if test else CHILD_LIMIT), st["state"])
                finally:
                    release_slot(st["state"])
        if st.get("record"):
            append_record(st["state"], make_record(st))
    except BaseException:
        pass


def _test_runner(kind: str):
    """Fault injection for the end-to-end tests (SHIPMIRACLE_TEST=1 only): sleep (child timeout), crash (child exception)."""
    def run(event, raw, tmp_state, tmp):
        if kind == "sleep":
            time.sleep(60)
        if kind == "crash":
            raise RuntimeError("injected")
        return run_v1(event, raw, tmp_state, tmp)
    return run


# ---------------------------------------------------------------- shadow-report
def parse_since(s: str) -> int:
    m = re.fullmatch(r"(\d+)\s*([smhd])", (s or "24h").strip())
    if not m:
        raise ValueError("expected a duration like 24h, 90m, 7d")
    return int(m.group(1)) * {"s": 1, "m": 60, "h": 3600, "d": 86400}[m.group(2)]


def aggregate(evs, since_ts: float = 0.0) -> dict:
    """hook_shadow events (dicts as in events.jsonl) -> counts, agree rate, disagreements by event and by module, the first 20 details."""
    rows = [e for e in evs if isinstance(e, dict) and e.get("kind") == "hook_shadow" and e.get("ts", 0) >= since_ts and isinstance(e.get("data"), dict)]
    agree = [e for e in rows if e["data"].get("agree") is True]
    errs = [e for e in rows if e["data"].get("agree") is None]
    dis = [e for e in rows if e["data"].get("agree") is False]
    by_event, by_mod = {}, {}
    for e in dis:
        d = e["data"]
        by_event[d.get("event", "?")] = by_event.get(d.get("event", "?"), 0) + 1
        dims = []
        for k in ("decision", "reason_sha", "ctx_sha", "sysmsg_sha", "exit"):
            if (d.get("legacy") or {}).get(k) != (d.get("v1") or {}).get(k):
                dims.append("output:" + k)
        dims += ["state:" + module_of(n) for n in d.get("state_diff", [])] + ["effects"] * bool(d.get("effects_diff"))
        e_ = d.get("errors") or {}
        dims += ["v1_errors"] * (e_.get("v1", 0) > e_.get("legacy", 0))
        for m in dims or ["?"]:
            by_mod[m] = by_mod.get(m, 0) + 1
    decided = len(agree) + len(dis)
    skipped = sum(1 for e in evs if isinstance(e, dict) and e.get("kind") == "hook_shadow_skipped" and e.get("ts", 0) >= since_ts)
    return {"events": len(rows), "skipped": skipped, "agree": len(agree), "disagree": len(dis), "child_errors": len(errs),
            "agree_rate": round(len(agree) / decided, 4) if decided else None, "by_event": by_event, "by_module": by_mod,
            "details": [{"ts": e.get("ts"), **{k: v for k, v in e["data"].items() if k != "skipped"}} for e in dis[:20]]}


def aggregate_stage(evs, since_ts: float = 0.0) -> dict:
    """`stage.shadow` events (P5, gate.engine=shadow: what the stage module WOULD have refused) -> counts per refusal kind, per project and per stage,
    the first 20 details. A detail carries the kind, the stage name, the project id, the time and the first 8 hex of sha256 of the change-request id
    (never the id's text or anything else): enough to find the case in the log, nothing a transcript could hold."""
    rows = [e for e in evs if isinstance(e, dict) and e.get("kind") == "stage.shadow" and e.get("ts", 0) >= since_ts and isinstance(e.get("data"), dict)]
    by_kind, by_proj, by_stage = {}, {}, {}
    for e in rows:
        d = e["data"]
        for tbl, key in ((by_kind, str(d.get("kind", "?"))[:40]), (by_proj, str(e.get("project") or "-")[:40]), (by_stage, str(d.get("stage", "?"))[:40])):
            tbl[key] = tbl.get(key, 0) + 1
    return {"events": len(rows), "by_kind": by_kind, "by_project": by_proj, "by_stage": by_stage,
            "details": [{"ts": e.get("ts"), "project": e.get("project"), "kind": str(e["data"].get("kind", "?"))[:40], "stage": str(e["data"].get("stage", "?"))[:40],
                         "cr_sha": sha(str(e["data"].get("cr", "")))[:8] if e["data"].get("cr") else None} for e in rows[:20]]}
