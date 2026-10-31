// Setup tab data (UX spec section 7): `shipm init --check --json` (read-only, shipmiracle/setup/run.py) parsed strictly, and cached. Pure Node, no vscode.
// The rows and their ids come from the CLI, never from a list in the panel. Nothing here asks for or shows a secret: every text from the CLI is cut, cleaned of control characters
// and scrubbed of anything that looks like a token before it can reach the page.
const fs = require('fs');
const path = require('path');

const MAX_OUT = 512 * 1024;                 // stdout cap (the real output is about 8 KB)
const TIMEOUT_MS = 5000;
const TTL_MS = 10 * 60 * 1000;              // a check also lives only this long: tools installed outside Shipmiracle change the answer without touching init.json
const ERR_TTL_MS = 60 * 1000;
const NEEDS = ['required', 'recommended', 'optional', 'advisory', 'never'];
const STATES = ['green', 'red', 'skipped', 'advisory', 'never'];
const KINDS = ['write', 'hint', 'browser', 'prompt'];
const ID = /^[a-z][a-z0-9-]{0,30}$/;
const STAGES = ['connect', 'prefs', 'advanced'], CLASSES = ['required', 'recommended', 'optional', 'advanced', 'advisory', 'never'], OS_KINDS = ['macos', 'linux', 'wsl', 'windows'];
const CTRL = /[\u0000-\u001f\u007f-\u009f\u2028\u2029]+/g;
// token shapes: GitHub, Anthropic/OpenAI style, Slack, JWT, long base64-ish runs, key=value secrets
const SECRET = /\b(?:gh[pousr]_[A-Za-z0-9]{16,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{16,}|xox[abprs]-[A-Za-z0-9-]{10,}|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{6,}\.?[A-Za-z0-9_-]*|AKIA[0-9A-Z]{16})\b|\b[A-Za-z0-9+_=-]{40,}\b|\b(?:token|secret|password|passwd|api[_-]?key)\s*[=:]\s*\S+/gi;
const CF = /[\p{Cf}\p{Co}\p{Cn}]+/gu;               // bidi marks and overrides, zero-width characters, BOM, private-use and unassigned (as detail.js does)
const clean = (v, n) => (typeof v === 'string' ? v : '').replace(CTRL, ' ').replace(CF, '').replace(SECRET, '[hidden]').replace(/\s{2,}/g, ' ').trim().slice(0, n);

// -> { ok: true, ready, rows } | { ok: false, why }. Strict: one bad row makes the whole answer unreadable (the page then says "Could not read setup state").
function parseCheck(stdout) {
  if (typeof stdout !== 'string' || !stdout.trim()) return { ok: false, why: 'empty' };
  if (stdout.length > MAX_OUT) return { ok: false, why: 'too large' };
  let j; try { j = JSON.parse(stdout); } catch (e) { return { ok: false, why: 'not JSON' }; }
  if (!j || typeof j !== 'object' || Array.isArray(j) || j.v !== 1 || !Array.isArray(j.rows) || j.rows.length < 1 || j.rows.length > 40) return { ok: false, why: 'unexpected shape' };
  const rows = [], seen = new Set();
  for (const r of j.rows) {
    if (!r || typeof r !== 'object' || !Number.isInteger(r.n) || typeof r.id !== 'string' || !ID.test(r.id) || seen.has(r.id)) return { ok: false, why: 'bad row' };
    if (!NEEDS.includes(r.need) || !STATES.includes(r.state) || typeof r.title !== 'string' || !r.title.trim()) return { ok: false, why: 'bad row ' + r.id };
    const c = r.connect && typeof r.connect === 'object' ? r.connect : {};
    seen.add(r.id);
    const row = { n: r.n, id: r.id, title: clean(r.title, 80), need: r.need, state: r.state, detail: clean(r.detail, 300), connect: { kind: KINDS.includes(c.kind) ? c.kind : 'hint', text: clean(c.text, 300) } };
    if (STAGES.includes(r.stage)) { row.stage = r.stage; row.cls = CLASSES.includes(r.class) ? r.class : r.need; row.os_supported = r.os_supported !== false; row.docs = typeof r.docs === 'string' && /^https:\/\/[A-Za-z0-9.\/_%#?=&:+~-]{1,180}$/.test(r.docs) ? r.docs : ''; }   // onboarding fields (CLI 0542999+); an older CLI has none and the Quick setup card stays hidden
    rows.push(row);
  }
  rows.sort((a, b) => a.n - b.n);
  const o = j.os && typeof j.os === 'object' ? { kind: OS_KINDS.includes(j.os.kind) ? j.os.kind : 'other', line: clean(j.os.line, 300), level: typeof j.os.level === 'string' && /^[a-z]{3,16}$/.test(j.os.level) ? j.os.level : '' } : null;   // level: only if the CLI sends it ('experimental' shows a note); the panel adds nothing of its own
  return { ok: true, ready: j.ready === true, rows, os: o && o.line ? o : null, quick: rows.some(r => r.stage === 'prefs') && !!(o && o.line) };
}

const mtime = f => { try { return fs.statSync(f).mtimeMs; } catch (e) { return 0; } };

// A checker runs the CLI by argv (no shell), at most one at a time, and keeps the answer until init.json or the install manifest changes (or 10 minutes pass, or force).
//   runner(file, args, opts, cb) is child_process.execFile in the extension and a stand-in in the tests.
function makeChecker({ shipm, stateDir, runner, env, now = Date.now }) {
  let cache = null, inflight = null;
  const keyOf = () => mtime(path.join(stateDir, 'v1', 'init.json')) + '|' + mtime(path.join(stateDir, 'v1', 'install-manifest.json'));
  function run() {
    return new Promise(res => {
      try {
        runner(shipm, ['init', '--check', '--json'], { timeout: TIMEOUT_MS, maxBuffer: MAX_OUT, env, windowsHide: true }, (err, out) => {
          if (err) return res({ error: true, why: err.killed ? 'timeout' : 'failed', rows: [], ready: false });
          const p = parseCheck(String(out || ''));
          res(p.ok ? { error: false, rows: p.rows, ready: p.ready, os: p.os, quick: p.quick } : { error: true, why: p.why, rows: [], ready: false });
        });
      } catch (e) { res({ error: true, why: 'failed', rows: [], ready: false }); }
    });
  }
  async function get(force) {
    const key = keyOf();
    if (!force && cache && cache.key === key && now() - cache.at < (cache.value.error ? ERR_TTL_MS : TTL_MS)) return cache.value;      // an unreadable answer is also kept for a minute: no hammering
    if (inflight) return inflight;
    inflight = run().then(v => { cache = { key, at: now(), value: { ...v, at: now() } }; return cache.value; }).finally(() => { inflight = null; });
    return inflight;
  }
  return { get, peek: () => (cache ? cache.value : null) };
}

// Which buttons a row gets. The CLI decides what can be skipped (`shipm init --skip` refuses required rows), so the panel follows the row's own `need`.
//   Fix:  a red row, or a grey row the owner skipped earlier ("Turn on"). Advisory/never rows are information (their connect text is shown) except Remote Control (opt-in, addendum 3 section C).
//   Skip: only a red row that is recommended or optional (never a required row).
function rowActions(r) {
  const optIn = r.id === 'remote-control';
  const fix = r.state === 'red' || r.state === 'skipped' || (optIn && r.state === 'advisory');
  const skip = (r.state === 'red' || (optIn && r.state === 'advisory')) && (r.need === 'recommended' || r.need === 'optional' || optIn);
  return { fix, skip, again: r.state === 'skipped' };
}

module.exports = { MAX_OUT, TIMEOUT_MS, TTL_MS, ID, parseCheck, makeChecker, rowActions, clean };
