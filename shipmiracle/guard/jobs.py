"""The guard's periodic jobs, in process (Platform v2 P4b, spec docs/plans/2026-10-20-p4-spec.md section 5).

Scheduler: the pure function `due(jobs, now, sysd)`. Runner: at most ONE worker thread at a time; the guard loop never waits for it
(`tick` only looks at `thread.is_alive()`). A job alive past its budget is marked stuck (event `guard_job_stuck`) and is not scheduled
again until its thread ends; a stuck job does not stop the other jobs (the number of leaked threads is bounded by the number of jobs).
Isolation: everything a job does, including loading its script, runs inside try/except BaseException in the worker; after 5 failures in a
row the job sleeps 30 minutes (event `guard_job_backoff` and a line in guard.err). Nothing here raises into the guard loop.
Script jobs (shipm-watch scan, idea nudge, ci-status) RELOAD the bin script on every run through SourceFileLoader into a fresh module
(fresh globals = same state as a subprocess); the module is dropped and collected afterwards. Standard library only; commands are always argument lists (no shell).
ISOLATION LIMITS (security review L6, accepted and documented, not fixed): a job is a THREAD of the guard process, not a subprocess. try/except
BaseException contains Python exceptions, SystemExit and a stuck job (the budget marker), but it cannot contain what a thread shares with the guard:
os._exit / a fatal signal / a native crash, os.chdir and os.environ changes, signal handlers, file descriptors and memory growth. The code that runs is
the workspace's own bin scripts (a script a job loads is code the owner already trusts and the gate protects: bin/** is a gate-protected path), so this is
a robustness limit, not a privilege boundary. If a job ever needs to run foreign or less trusted code it must be moved to a subprocess first."""
from __future__ import annotations

import gc
import importlib.machinery
import importlib.util
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

LOW_PCT = 20            # battery percent below which (unplugged) the low-battery intervals apply
FAIL_LIMIT = 5          # consecutive failures before the backoff
BACKOFF_S = 30 * 60
TIER_TTL = 60.0         # therm / notifyutil answers are reused this long


class Job:
    def __init__(self, name, fn, interval, low_interval=None, needs_vscode=False, budget=60.0, gate=None):
        self.name = name
        self.fn = fn
        self.interval = float(interval)
        self.low_interval = float(low_interval if low_interval is not None else interval)
        self.needs_vscode = needs_vscode
        self.budget = float(budget)
        self.gate = gate                 # optional callable: False = not startable now (the ledger job: previous process still running)
        self.last_run = 0.0              # start time of the last run
        self.failures = 0
        self.backoff_until = 0.0
        self.thread = None
        self.started = 0.0
        self.stuck = False
        self.outcome = None              # set by the worker: ("ok", None) or ("error", text)

    def alive(self) -> bool:
        return self.thread is not None and self.thread.is_alive()


def low_battery(sysd) -> bool:
    try:
        return (not sysd.get("on_ac", True)) and int(sysd.get("battery_pct", 100)) < LOW_PCT
    except (TypeError, ValueError):
        return False


def interval_of(job, sysd) -> float:
    return job.low_interval if low_battery(sysd or {}) else job.interval


def due(jobs, now, sysd):
    """Jobs that may start at `now`, in table order. Pure: reads the job fields and `sysd` (on_ac, battery_pct, vscode), changes nothing."""
    sysd = sysd or {}
    out = []
    for j in jobs:
        if j.alive() or j.stuck or now < j.backoff_until:
            continue
        if j.needs_vscode and not sysd.get("vscode"):
            continue
        if now - j.last_run < interval_of(j, sysd):
            continue
        if j.gate is not None:
            try:
                if not j.gate():
                    continue
            except Exception:
                continue
        out.append(j)
    return out


class TierCache:
    """Cheap system probes (pmset therm, notifyutil) answered from a cache for `ttl` seconds."""

    def __init__(self, ttl=TIER_TTL, clock=time.time):
        self.ttl = ttl
        self.clock = clock
        self.vals = {}

    def get(self, name, fn):
        now = self.clock()
        hit = self.vals.get(name)
        if hit is not None and 0 <= now - hit[0] < self.ttl:
            return hit[1]
        v = fn()
        self.vals[name] = (now, v)
        return v


def _default_emit(kind, data, state=None):
    try:
        from shipmiracle import events
        events.emit(kind, data, src="shipmiracle-guard", base=state)
    except BaseException as e:               # an event must never matter
        if isinstance(e, (KeyboardInterrupt, SystemExit)):
            raise


class Runner:
    def __init__(self, jobs, clock=time.time, state=None, emit=None):
        self.jobs = list(jobs)
        self.clock = clock
        self.state = Path(state) if state is not None else None
        self._emit = emit
        self.events = []                 # (kind, data) of this process; handy for tests and diagnostics

    # ---- helpers that never raise ----
    def emit(self, kind, data):
        self.events.append((kind, data))
        try:
            if self._emit is not None:
                self._emit(kind, data)
            else:
                _default_emit(kind, data, self.state)
        except BaseException as e:
            if isinstance(e, (KeyboardInterrupt, SystemExit)):
                raise

    def errlog(self, text):
        if self.state is None:
            return
        try:
            self.state.mkdir(parents=True, exist_ok=True)
            with open(self.state / "guard.err", "a") as f:
                f.write("%s %s\n" % (time.strftime("%F %T"), text[:300]))
        except Exception:
            pass

    # ---- worker ----
    @staticmethod
    def _work(job):
        try:
            job.fn()
            job.outcome = ("ok", None)
        except BaseException as e:            # SyntaxError/ImportError from the script loader, sys.exit() in a script, anything
            job.outcome = ("error", "%s: %s" % (type(e).__name__, str(e)[:160]))

    def _fail(self, job, now, why):
        job.failures += 1
        if job.failures >= FAIL_LIMIT:
            job.backoff_until = now + BACKOFF_S
            job.failures = 0
            self.emit("guard_job_backoff", {"job": job.name, "minutes": BACKOFF_S // 60, "reason": why[:120]})
            self.errlog("job %s failed %d times in a row (%s): paused %d min" % (job.name, FAIL_LIMIT, why, BACKOFF_S // 60))

    def _reap(self, now):
        for j in self.jobs:
            if j.thread is not None and not j.thread.is_alive():
                j.thread.join(0)
                out, j.outcome = j.outcome, None
                was_stuck = j.stuck
                j.thread = None
                j.stuck = False
                if was_stuck:
                    continue                  # already counted as a failure when it was marked stuck
                if out and out[0] == "error":
                    self._fail(j, now, out[1])
                else:
                    j.failures = 0

    def _mark_stuck(self, now):
        for j in self.jobs:
            if j.alive() and not j.stuck and now - j.started > j.budget:
                j.stuck = True
                self.emit("guard_job_stuck", {"job": j.name, "age_s": int(now - j.started), "budget_s": int(j.budget)})
                self._fail(j, now, "stuck")

    def tick(self, now=None, sysd=None, only=None):
        """Called from the guard loop every step. Reaps a finished job, flags a stuck one, starts at most one due job. Returns the job
        started (or None). Never blocks and never raises."""
        try:
            now = self.clock() if now is None else now
            self._reap(now)
            self._mark_stuck(now)
            if any(j.alive() and not j.stuck for j in self.jobs):
                return None                   # one worker at a time
            for j in due(self.jobs, now, sysd):
                if only is not None and j.name not in only:
                    continue
                j.last_run = now
                j.started = now
                j.outcome = None
                j.thread = threading.Thread(target=self._work, args=(j,), name="shipmiracle-job-" + j.name, daemon=True)
                j.thread.start()
                return j
        except Exception as e:                # the scheduler itself must not take the guard step down
            self.errlog("scheduler error: %s: %s" % (type(e).__name__, str(e)[:120]))
        return None

    def join_all(self, timeout=5.0):
        """For tests and shutdown: wait for worker threads to end."""
        end = time.time() + timeout
        for j in self.jobs:
            if j.thread is not None:
                j.thread.join(max(0.0, end - time.time()))
        return not any(j.alive() for j in self.jobs)


# ---------- script jobs ----------
def load_script(path, modname):
    """Execute bin/<script> into a NEW module (not registered in sys.modules): fresh globals every time, like a new process. sys.path is
    restored afterwards (the scripts insert the workspace at the front). Bytecode is cached by SourceFileLoader, so a reload is cheap."""
    saved = list(sys.path)
    try:
        loader = importlib.machinery.SourceFileLoader(modname, str(path))
        spec = importlib.util.spec_from_loader(modname, loader)
        mod = importlib.util.module_from_spec(spec)
        loader.exec_module(mod)
        return mod
    finally:
        sys.path[:] = saved


def run_script(path, modname, call):
    """Reload `path`, run call(module), drop the module and collect it."""
    mod = load_script(path, modname)
    try:
        return call(mod)
    finally:
        del mod
        gc.collect()


class LedgerSpawn:
    """shipm-ledger --update stays a subprocess (low memory). Starts it without waiting; a second one never starts while one runs."""

    def __init__(self, ws, python=None):
        self.ws = Path(ws)
        self.python = python or sys.executable
        self.proc = None

    def idle(self):
        return self.proc is None or self.proc.poll() is not None

    def __call__(self):
        if not self.idle():
            return
        self.proc = subprocess.Popen([self.python, str(self.ws / "bin/shipm-ledger"), "--update"],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _report_pending() -> bool:
    """Gate of the summary job: something is waiting in the report queue (a listdir; never raises)."""
    try:
        from ..report import queue
        return queue.has_pending()
    except Exception:
        return False


def _report_run():
    from ..report import queue
    return queue.job()


def default_jobs(ws, python=None):
    """The job table of spec section 5. Intervals: normal / battery below 20 percent unplugged."""
    ws = Path(ws)
    ledger = LedgerSpawn(ws, python)
    return [
        Job("scan", lambda: run_script(ws / "bin/shipm-watch", "shipmiracle_watch_job", lambda m: m.scan()), 60, 300, budget=45),
        Job("nudge", lambda: run_script(ws / "bin/idea", "shipmiracle_idea_job", lambda m: m.nudge([])), 600, 600, budget=45),
        Job("ci", lambda: run_script(ws / "bin/ci-status", "shipmiracle_ci_job", lambda m: m.main([])), 600, 1200, needs_vscode=True, budget=300),
        Job("ledger", ledger, 600, 1200, budget=30, gate=ledger.idle),
        # P5c: fills `Summary: pending` of CR reports (shipmiracle.report.queue). Nothing at all on low battery (interval far beyond any uptime).
        Job("report_summaries", _report_run, 300, 10 ** 12, budget=120, gate=_report_pending),
    ]
