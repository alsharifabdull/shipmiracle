"""State v1: <state>/v1/<name> JSON envelopes {"v":1,"ts":..,"writer":..,"data":..}. Atomic, flock-ed, 0600 files in 0700 dirs,
never through a symlink. The old files stay the authority; mirror() is the only thing daemons call in P2."""
from __future__ import annotations

import contextlib
import errno
import fcntl
import json
import os
import re
import stat
import tempfile
import time
from pathlib import Path

from . import LockTimeout, NotFound, SafetyError, SchemaError, UsageError
from . import paths

NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
# who may write which file: a bug catcher (a wrong writer name raises), not a security boundary. Unknown names are refused.
OWNERS = {"guard.json": "shipmiracle-guard", "away.json": "shipmiracle-guard", "health.json": "shipmiracle-watch", "ci.json": "ci-status", "agents.json": "shipmiracle-agents",
          "aside.json": "shipmiracle-project", "seen.json": "shipmiracle-project",
          "tidy.json": "shipmiracle-tidy"}
MAX_READ = 8 * 1024 * 1024      # whole-file reads (state, config, events.tail) refuse anything larger
_mirror_failed = False          # one state.v1_write_failed event per process


def _uid() -> int:
    """Seam: tests replace this to simulate a folder owned by someone else."""
    return os.getuid()


def _base(base) -> Path:
    return Path(base) if base is not None else paths.state_dir()


def root(base=None) -> Path:
    return _base(base) / "v1"


def _check_name(name) -> str:
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        raise UsageError("invalid state name")
    return name


def ensure_dir(path) -> Path:
    """Create `path` (0700) or harden it: a symlink, a non-directory or a foreign owner raises SafetyError; group/other bits are removed."""
    path = Path(path)
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.mkdir(path, 0o700)
        except FileExistsError:
            pass
        st = os.lstat(path)
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        raise SafetyError("%s is a symlink or not a folder" % path)
    if st.st_uid != _uid():
        raise SafetyError("%s is owned by another user" % path)
    if st.st_mode & 0o077:                 # only remove group/other access; owner bits are never widened (a deliberate 0500 stays)
        os.chmod(path, stat.S_IMODE(st.st_mode) & 0o700)
    return path


def ensure_root(base=None) -> Path:
    """Make <base> and <base>/v1 (and v1/.locks); hardens the legacy base folder too (it holds the old 0644 files)."""
    b = _base(base)
    ensure_dir(b)
    r = ensure_dir(b / "v1")
    ensure_dir(r / ".locks")
    return r


def atomic_write(path, data: bytes, mode: int = 0o600) -> None:
    """Write `data` to `path` via a temp file in the same folder (fchmod, fsync, os.replace). Refuses a symlink or non-file target."""
    path = Path(path)
    paths.guard_real_write(path, "write")
    try:
        st = os.lstat(path)
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
            raise SafetyError("%s is a symlink or not a regular file" % path)
    except FileNotFoundError:
        pass
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix="." + path.name + ".", suffix=".tmp")
    try:
        try:
            os.fchmod(fd, mode)
            view = memoryview(data)
            while view:
                view = view[os.write(fd, view):]
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


@contextlib.contextmanager
def lock_file(path, timeout: float = 2.0):
    """Exclusive flock on `path` (created 0600, O_NOFOLLOW), polled every 10 ms; LockTimeout after `timeout` seconds."""
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    except OSError as e:
        if e.errno == errno.ELOOP:
            raise SafetyError("%s is a symlink" % path)
        raise
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != _uid():
            raise SafetyError("%s is not our regular file" % path)
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as e:
                if e.errno not in (errno.EWOULDBLOCK, errno.EAGAIN, errno.EACCES):
                    raise
                if time.monotonic() >= deadline:
                    raise LockTimeout("lock %s busy for %.1fs" % (Path(path).name, timeout))
                time.sleep(0.01)
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def locked(name: str, base=None, timeout: float = 2.0):
    """Lock `v1/.locks/<name>.lock` (context manager)."""
    _check_name(name)
    return lock_file(ensure_root(base) / ".locks" / (name + ".lock"), timeout)


def read_bytes_nofollow(path) -> bytes:
    """Read a regular file we own without following a symlink; FileNotFoundError if absent, SafetyError for a symlink or foreign owner,
    SchemaError when larger than MAX_READ."""
    try:
        fd = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)     # O_NONBLOCK: a FIFO must not hang the open; fstat rejects it below
    except OSError as e:
        if e.errno == errno.ELOOP:
            raise SafetyError("%s is a symlink" % path)
        raise
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != _uid():
            raise SafetyError("%s is not our regular file" % path)
        if st.st_size > MAX_READ:
            raise SchemaError("%s is larger than %d MiB" % (Path(path).name, MAX_READ >> 20))
        chunks, total = [], 0
        while True:
            c = os.read(fd, 1 << 16)
            if not c:
                return b"".join(chunks)
            total += len(c)
            if total > MAX_READ:
                raise SchemaError("%s is larger than %d MiB" % (Path(path).name, MAX_READ >> 20))
            chunks.append(c)
    finally:
        os.close(fd)


def _owner_check(name: str, writer: str) -> None:
    if OWNERS.get(name) != writer:
        raise SafetyError("%s is not written by %r" % (name, writer))


def write(name: str, data, writer: str, base=None, timeout: float = 2.0) -> dict:
    """Write `data` (JSON-able) as an envelope under lock. Returns the envelope."""
    paths.assert_isolated(_base(base))
    _check_name(name)
    _owner_check(name, writer)
    env = {"v": 1, "ts": int(time.time()), "writer": writer, "data": data}
    try:
        raw = (json.dumps(env, sort_keys=True) + "\n").encode("utf-8")
    except (TypeError, ValueError) as e:
        raise UsageError("data is not JSON-serialisable: %s" % type(e).__name__)
    with locked(name, base, timeout):
        atomic_write(root(base) / name, raw)
    return env


def read(name: str, base=None) -> dict:
    """The envelope of `name`. NotFound if absent, SchemaError if malformed, SafetyError for symlinks/foreign owner."""
    _check_name(name)
    try:
        raw = read_bytes_nofollow(root(base) / name)
    except FileNotFoundError:
        raise NotFound("no state %s" % name)
    try:
        env = json.loads(raw.decode("utf-8"))
    except ValueError:
        raise SchemaError("%s is not valid JSON" % name)
    if (not isinstance(env, dict) or env.get("v") != 1 or not isinstance(env.get("ts"), int) or isinstance(env.get("ts"), bool)
            or not isinstance(env.get("writer"), str) or "data" not in env):
        raise SchemaError("%s is not a v1 envelope" % name)
    return env


def read_data(name: str, default=None, base=None):
    """The data of `name`, or `default` on any problem. Never raises."""
    try:
        return read(name, base)["data"]
    except Exception:
        return default


def delete(name: str, writer: str, base=None, timeout: float = 2.0) -> bool:
    """Remove `name` under lock; True if it existed."""
    paths.assert_isolated(_base(base))
    _check_name(name)
    _owner_check(name, writer)
    with locked(name, base, timeout):
        try:
            os.unlink(root(base) / name)
            return True
        except FileNotFoundError:
            return False


def mirror(name: str, data, writer: str, base) -> bool:
    """Second copy of a legacy write. Never raises. No-op (False) when switch state.v1 is off. On failure emits state.v1_write_failed
    once per process (error class only) and returns False. True when the copy was written."""
    global _mirror_failed
    try:
        from . import config
        if not config.switch("state.v1"):
            return False
        write(name, data, writer, base)
        return True
    except BaseException as e:
        if isinstance(e, (KeyboardInterrupt, SystemExit)):
            raise
        if not _mirror_failed:
            _mirror_failed = True
            try:
                from . import events
                events.emit("state.v1_write_failed", {"name": str(name)[:128], "error": type(e).__name__}, base=base)
            except BaseException as e2:
                if isinstance(e2, (KeyboardInterrupt, SystemExit)):
                    raise
        return False


def _load_json_file(path):
    try:
        return json.loads(read_bytes_nofollow(path).decode("utf-8"))
    except (OSError, ValueError, SafetyError):
        return None


def read_compat(name: str, legacy_path, base=None):
    """(data, "v1"|"legacy"|None): whichever copy is newer by file mtime (a tie goes to legacy, the authority). An unreadable copy loses.
    When the legacy file is absent and a readable v1 copy exists, the v1 copy is returned (marked "v1"); callers that treat
    legacy as the only authority must test for the legacy file themselves."""
    cands = []
    try:
        mt = os.lstat(root(base) / _check_name(name)).st_mtime_ns
        cands.append((mt, 0, "v1", lambda: read(name, base)["data"]))
    except OSError:
        pass
    try:
        mt = os.lstat(legacy_path).st_mtime_ns
        cands.append((mt, 1, "legacy", lambda: _legacy(legacy_path)))
    except OSError:
        pass
    for _, _, src, get in sorted(cands, key=lambda c: (c[0], c[1]), reverse=True):
        try:
            return get(), src
        except Exception:
            continue
    return None, None


def _legacy(path):
    v = json.loads(read_bytes_nofollow(path).decode("utf-8"))
    return v


def check(base=None) -> list:
    """Problems found under <base> (list of strings; empty = healthy): wrong modes, symlinks, foreign owners, bad envelopes."""
    b = _base(base)
    out = []
    try:
        st = os.lstat(b)
    except FileNotFoundError:
        return out
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        return ["state folder is a symlink or not a folder"]
    if st.st_uid != _uid():
        out.append("state folder owned by another user")
    if st.st_mode & 0o077:
        out.append("state folder mode %o (want 700)" % stat.S_IMODE(st.st_mode))
    r = b / "v1"
    pyc = r / "pyc"
    for dp, dns, fns in os.walk(r):
        in_pyc = Path(dp) == pyc or pyc in Path(dp).parents
        for n in dns + fns:                                    # in_pyc: the entries listed under v1/pyc (v1/pyc itself is listed under v1 and keeps its mode check)
            p = Path(dp) / n
            if n.startswith(".") and n.endswith(".tmp"):      # an in-flight atomic write
                continue
            rel = str(p.relative_to(b))
            try:
                s = os.lstat(p)
            except FileNotFoundError:                         # vanished while we walked
                continue
            if stat.S_ISLNK(s.st_mode):
                out.append("%s is a symlink" % rel)
            elif s.st_uid != _uid():
                out.append("%s owned by another user" % rel)
            elif s.st_mode & 0o077 and not in_pyc:           # v1/pyc is Python's bytecode cache (hook wrapper): its contents may have any mode; symlinks and foreign owners inside still count
                out.append("%s mode %o" % (rel, stat.S_IMODE(s.st_mode)))
        dns[:] = [d for d in dns if not os.path.islink(os.path.join(dp, d))]
    for name in OWNERS:
        if os.path.lexists(r / name):
            try:
                read(name, b)
            except Exception as e:
                out.append("v1/%s unreadable: %s" % (name, type(e).__name__))
    return out
