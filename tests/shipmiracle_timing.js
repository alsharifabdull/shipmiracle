// Shared helper for wall-clock assertions (not a test; test-all only runs *_test.js). Same rule as tests/shipmiracle_timing.py:
// an attempt passes when value <= max(limit, K x baseline), the baseline measured right BEFORE and right AFTER the measurement (the larger one is used), the check passes when any of
// `attempts` passes. K is chosen per test as about limit / (the baseline on a quiet machine). All values in milliseconds.
'use strict';
const now = () => Number(process.hrtime.bigint()) / 1e6;
const timed = fn => { const t = now(); fn(); return now() - t; };
function robustAround(measure, ref, limit, k, attempts = 5) {
  const rows = [];
  for (let i = 0; i < attempts; i++) {
    const r0 = ref(), v = measure(), r1 = ref(), r = Math.max(r0, r1);
    rows.push([v, r]);
    if (v <= Math.max(limit, k * r)) return { ok: true, report: `value ${v.toFixed(1)} ms, baseline ${r.toFixed(1)} ms, ratio ${(r ? v / r : 0).toFixed(1)}, limit ${limit} ms, k ${k} (attempt ${rows.length})` };
  }
  return { ok: false, report: rows.map(([v, r], i) => `attempt ${i + 1}: value ${v.toFixed(1)} ms, baseline ${r.toFixed(1)} ms (k*baseline ${(k * r).toFixed(1)})`).join('; ') + `; limit ${limit} ms, k ${k}` };
}
// the code under test made artificially slower (busy wait of `delay` ms): the relative check must still FAIL
const slowed = (fn, delay) => (...a) => { const t = now(); while (now() - t < delay); return fn(...a); };
function mutantNoticed(one, ref, limit, k, factor = 4) {
  const delay = factor * Math.max(limit, k * ref());
  return !robustAround(() => timed(slowed(one, delay)), ref, limit, k, 2).ok;
}
module.exports = { now, timed, robustAround, slowed, mutantNoticed };
