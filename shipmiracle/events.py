"""Event log <state>/v1/events.jsonl: one JSON object per line, appended under a lock, rotated at 5 MiB to .1/.2/.3, old rotated files
deleted after logs.retention_days. Never put secrets in events: keys token/secret/password are refused."""
from __future__ import annotations

import errno
import json
import os
import re
import stat
import time
import unicodedata
from pathlib import Path

from . import SafetyError, SchemaError, UsageError
from . import paths, state

KIND_RE = re.compile(r"[a-z][a-z0-9_.]{0,63}")
SRC_RE = re.compile(r"[a-z][a-z0-9_.-]{0,31}")
PROJECT_RE = re.compile(r"[0-9a-f]{12}")
MAX_LINE = 4096                       # bytes, without the newline
MAX_BYTES = 5 * 1024 * 1024
REFUSED = ("token", "secret", "password", "passwd", "apikey", "accesskey")
KEEP = 3                              # rotated files kept: .1 .2 .3


def _max_bytes() -> int:
    v = paths.test_override("SHIPMIRACLE_EVENTS_MAX_BYTES", str(MAX_BYTES))
    try:
        return max(1, int(str(v)))
    except ValueError:
        return MAX_BYTES


def _squash(key) -> str:
    """Key in comparable form: NFKC (fullwidth and lookalike forms), case-folded, only letters and digits (so '_', '-', '.', spaces and
    zero-width characters between the parts vanish)."""
    k = unicodedata.normalize("NFKC", str(key)).casefold()
    return "".join(c for c in k if unicodedata.category(c)[0] in "LN")


def _key_refused(key) -> bool:
    k = _squash(key).replace("tokens", "")      # `tokens` (a count, as in the ledger) is allowed; `token` is not
    return any(r in k for r in REFUSED)


def _refuse_keys(obj, depth=0) -> None:
    """Only KEYS are checked (at any depth); values are never inspected, so private text must not be passed as a value either."""
    if depth > 8:
        raise UsageError("event data nested too deep")
    if isinstance(obj, dict):
        for k, v in obj.items():
            if _key_refused(k):
                raise UsageError("event key %r is refused (private data)" % str(k)[:40])
            _refuse_keys(v, depth + 1)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _refuse_keys(v, depth + 1)


def _retention_days() -> int:
    try:
        from . import config
        return int(config.get("logs.retention_days"))
    except Exception:
        return 30


def _rotated(r: Path, i: int) -> Path:
    return r / ("events.jsonl.%d" % i)


def _rotate(r: Path) -> None:
    live = r / "events.jsonl"
    for p in (_rotated(r, KEEP),):
        try:
            os.unlink(p)
        except FileNotFoundError:
            pass
    for i in range(KEEP - 1, 0, -1):
        try:
            os.replace(_rotated(r, i), _rotated(r, i + 1))
        except FileNotFoundError:
            pass
    os.replace(live, _rotated(r, 1))


def _expire(r: Path) -> None:
    cutoff = time.time() - _retention_days() * 86400
    for i in range(1, KEEP + 1):
        p = _rotated(r, i)
        try:
            st = os.lstat(p)
            if st.st_mtime < cutoff:
                os.unlink(p)
        except FileNotFoundError:
            pass


def _open_live(r: Path) -> int:
    try:
        fd = os.open(str(r / "events.jsonl"), os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    except OSError as e:
        if e.errno == errno.ELOOP:
            raise SafetyError("events.jsonl is a symlink")
        raise
    st = os.fstat(fd)
    if not stat.S_ISREG(st.st_mode) or st.st_uid != state._uid():
        os.close(fd)
        raise SafetyError("events.jsonl is not our regular file")
    return fd


def append(kind, data=None, project=None, src="shipmiracle", base=None, timeout: float = 5.0) -> dict:
    """Append one event; raises UsageError (bad kind/src/project/keys/size), SafetyError, LockTimeout. Returns the event."""
    b = Path(base) if base is not None else paths.state_dir()
    paths.assert_isolated(b)
    if not isinstance(kind, str) or not KIND_RE.fullmatch(kind):
        raise UsageError("invalid event kind")
    if not isinstance(src, str) or not SRC_RE.fullmatch(src):
        raise UsageError("invalid event src")
    if project is not None and not (isinstance(project, str) and PROJECT_RE.fullmatch(project)):
        raise UsageError("invalid event project id")
    data = {} if data is None else data
    if not isinstance(data, dict):
        raise UsageError("event data must be an object")
    _refuse_keys(data)
    ev = {"v": 1, "ts": int(time.time()), "kind": kind, "project": project, "src": src, "data": data}
    try:
        text = json.dumps(ev, separators=(",", ":"))
    except (TypeError, ValueError):
        raise UsageError("event data is not JSON-serialisable")
    line = text.encode("utf-8")
    if len(line) > MAX_LINE:
        raise UsageError("event line is %d bytes (max %d)" % (len(line), MAX_LINE))
    line += b"\n"
    r = state.ensure_root(b)
    with state.lock_file(r / ".locks" / "events.lock", timeout):
        fd = _open_live(r)
        try:
            size = os.fstat(fd).st_size
            if size > 0 and size + len(line) > _max_bytes():
                os.close(fd)
                fd = -1
                _rotate(r)
                fd = _open_live(r)
            os.write(fd, line)
        finally:
            if fd >= 0:
                os.close(fd)
        _expire(r)
    return ev


def emit(kind, data=None, project=None, src="shipmiracle", base=None) -> bool:
    """append() that never raises; True when the event was written."""
    try:
        append(kind, data, project, src, base)
        return True
    except Exception:
        return False


def tail(n: int = 50, base=None) -> list:
    """The last `n` events (oldest first), read across rotated files; damaged lines are skipped."""
    b = Path(base) if base is not None else paths.state_dir()
    r = state.root(b)
    out = []                                   # newest first
    for p in (r / "events.jsonl", _rotated(r, 1), _rotated(r, 2), _rotated(r, 3)):
        if len(out) >= n:
            break
        try:
            raw = state.read_bytes_nofollow(p)
        except FileNotFoundError:
            continue
        except SchemaError:                    # a file over the read cap is skipped, not loaded
            continue
        for ln in reversed(raw.splitlines()):
            try:
                v = json.loads(ln.decode("utf-8"))
            except ValueError:
                continue
            if isinstance(v, dict):
                out.append(v)
    return list(reversed(out[:n])) if n > 0 else []
