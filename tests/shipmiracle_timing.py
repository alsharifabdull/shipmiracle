"""Shared helper for wall-clock assertions (not a test; test-all only runs *_test.py).
A latency check must not fail just because the Mac is busy, and must still catch a real regression. Rule:
  an attempt PASSES when  value <= max(limit, K * reference)   (reference = the same kind of work measured right before, on the same machine, same load)
  the check PASSES when any of 3 attempts passes. It FAILS only when the value exceeds BOTH the absolute limit AND K x reference in ALL 3 attempts.
The failure text prints every attempt: value, reference, limit and K."""
import subprocess, sys, time

def median(xs):
    s = sorted(xs); return s[len(s) // 2]

def p95(xs):
    s = sorted(xs); return s[max(0, int(len(s) * 0.95) - 1)]

def timed(fn):
    t0 = time.perf_counter(); fn(); return time.perf_counter() - t0

def spawn_ref(n=15, stat=median, cmd=None):
    """Reference: seconds to start+run a trivial process (python3 -I -c pass by default); stat of n runs."""
    cmd = cmd or [sys.executable, "-I", "-c", "pass"]
    return stat([timed(lambda: subprocess.run(cmd, capture_output=True)) for _ in range(n)])

def robust(measure, ref, limit, k, attempts=3):
    """measure() and ref() return seconds (floats). Returns (ok, report, best_value)."""
    rows = []
    for _ in range(attempts):
        r = ref(); v = measure()
        rows.append((v, r))
        if v <= max(limit, k * r):
            return True, "value %.3f s, reference %.3f s, limit %.3f s, k %g (attempt %d)" % (v, r, limit, k, len(rows)), v
    return False, "; ".join("attempt %d: value %.3f s, reference %.3f s (k*ref %.3f)" % (i + 1, v, r, k * r) for i, (v, r) in enumerate(rows)) + "; limit %.3f s, k %g" % (limit, k), min(v for v, _ in rows)


# ---- 26 Oct 2026: load-tolerant calibration used by every absolute wall-clock check ------------------------------------------------------------------------------
def robust_around(measure, ref, limit, k, attempts=5):
    """Like robust(), but the reference is measured immediately BEFORE and immediately AFTER the measurement and the larger of the two is used: load that rises or falls during
    the attempt moves the reference with it. measure() and ref() return seconds. An attempt passes when value <= max(limit, k * ref); the check passes when any attempt passes and
    fails only when ALL attempts exceed both. K is chosen per test as about limit / (the reference on a quiet machine), so a quiet machine behaves like the absolute limit and a
    loaded one gets proportionally more room. Returns (ok, report, best_value)."""
    rows = []
    for _ in range(attempts):
        r0 = ref(); v = measure(); r1 = ref(); r = max(r0, r1)
        rows.append((v, r))
        if v <= max(limit, k * r):
            return True, "value %.4f s, baseline %.4f s, ratio %.1f, limit %.4f s, k %g (attempt %d)" % (v, r, v / r if r else 0.0, limit, k, len(rows)), v
    return False, "; ".join("attempt %d: value %.4f s, baseline %.4f s, ratio %.1f (k*baseline %.4f)" % (i + 1, v, r, v / r if r else 0.0, k * r) for i, (v, r) in enumerate(rows)) + "; limit %.4f s, k %g" % (limit, k), min(v for v, _ in rows)


def p95_of(fn, n):
    """p95 (seconds) of n calls of fn()."""
    xs = sorted(timed(fn) for _ in range(n))
    return xs[max(0, int(len(xs) * 0.95) - 1)]


def slowed(fn, delay):
    """The code under test made artificially slower (a sleep before it runs): the MUTANT every relative check must still catch."""
    def w(*a, **kw):
        time.sleep(delay)
        return fn(*a, **kw)
    return w


def mutant_noticed(one, ref, limit, k, n=30, factor=4.0):
    """True when robust_around() FAILS for `one` (the code under test, a callable) made artificially slower by a sleep of factor x max(limit, k x baseline): the relative check
    still catches a real regression however loaded the machine is (the delay is sized from the baseline measured right now)."""
    delay = factor * max(limit, k * ref())
    ok, _rep, _best = robust_around(lambda: p95_of(slowed(one, delay), n), ref, limit, k, attempts=2)
    return not ok


def cpu_ref(n=15):
    """Generic CPU + small-file baseline (seconds, p95 of n runs of a fixed pure-python workload with one tiny file write/read): the same machine load slows it the same way it slows the code
    under test. About 3-4 ms on a quiet Mac; use K = limit / that."""
    import os, tempfile
    def work():
        s = 0
        for i in range(60000):
            s += i * i
        fd, path = tempfile.mkstemp()
        os.write(fd, b"x" * 1024); os.close(fd)
        with open(path, "rb") as f:
            f.read()
        os.unlink(path)
        return s
    return p95_of(work, n)
