// Fixtures for the F9 Details tests (UX addendum section 5, mock v2 data): projects in the shape data.js produces plus the `detail` answers the extension hands to html().
// Hostile strings are built from code points (never typed as escapes in text). Not a test.
const F = require('./panel_v3_fixtures');
const now = Math.floor(Date.now() / 1000);
const U = h => String.fromCharCode(parseInt(h, 16));
const BIDI = U('202e') + U('2066') + U('200f') + U('061c');
const AR = 'مرحبا بالعالم، هذا اختبار لنص عربي طويل يظهر داخل بطاقة المشروع';
const LONGPATH = 'nested/dev/' + 'deeply-nested-folder-name/'.repeat(8) + 'file-with-a-very-long-name.json';

const full = (o = {}) => ({
  error: false, at: now,
  chat: { state: 'ok', text: 'Seed script is done and the RTL checklist is wired into the menu page. Next I run the whole test suite, then fix whatever it finds before the review step starts.', ts: now - 180, tool: 'Bash' },
  report: { id: 'r-test-1', verdict: 'PASS', title: 'Test report', summary: '214 of 214 tests passed. No failures. 2 skipped by design.', ts: now - 30 * 3600 },
  status: { note: '21 Oct 2026, Claude Sonnet, BUILD. Seed script done, RTL checklist wiring in progress.', ts: now - 3 * 3600 },
  ...o
});
const busy = (name, o = {}) => F.mk(name, 'software', {
  state: 'working', next: 'run the full suite', lastCommit: now - 54 * 60, dirty: 3,
  agents: [{ id: 'a1', type: 'frontend-engineer', model: 'sonnet', started: now - 900, mins: 15, quiet: 60, stalled: false }],
  cr: [F.cr('CR-012', 'RTL fix', 'open', 'do')], flow: F.run('frontend-engineer', 'sonnet'), ...o
});
const P = {
  quiet: busy('quiet-app', { quiet: { min: 34, tests: 12 }, progress: { ts: now - 34 * 60, src: 'commit' } }),
  plain: busy('plain-app'),
  idle: F.mk('idle-app', 'software', { next: 'ship it', lastCommit: now - 7200 }),
  empty: { ...F.mk('empty-app', 'software', { state: 'working', lastCommit: 0, dirty: 0, next: '', agents: [], flow: F.flow() }), playbook: null, cr: null, stageLabels: null },
  hostile: busy('hostile-app', { next: 'x'.repeat(300), agents: [{ id: 'a1', type: 'agent-' + 'z'.repeat(120), model: 'sonnet', started: now - 900, mins: 15, quiet: 90 }, { id: 'a2', type: 'b', model: 'opus', started: now - 900, mins: 15, quiet: null }, { id: 'a3', type: 'c', model: 'haiku', started: now - 900, mins: 15, quiet: 5000 }, { id: 'a4', type: 'd', model: '', started: now - 900, mins: 15, quiet: 4 }] }),
  arabic: busy('arabic-app', {}),
  noplaybook: { ...F.mk('legacy-app', 'software', {}), playbook: null, cr: null, stageLabels: null }
};
const HOSTILE_CHAT = '<img src=x onerror=alert(1)> <script>alert(2)</script> [click me](javascript:alert(3)) **bold** ' + BIDI + ' ' + AR + ' ' + 'W'.repeat(120) + ' ' + LONGPATH + ' ' + 'tail '.repeat(1000);
const D = {
  full: full(),
  noChat: full({ chat: { state: 'none', text: '', ts: 0, tool: '' } }),
  noReport: full({ report: null }),
  noStatus: full({ status: null }),
  none: full({ chat: { state: 'none', text: '', ts: 0, tool: '' }, report: null, status: null }),
  chatErr: full({ chat: { state: 'error', text: '', ts: 0, tool: '' } }),
  noTool: full({ chat: { state: 'ok', text: 'Short answer.', ts: now - 20, tool: '' } }),
  fail: full({ report: { id: 'r-fail', verdict: 'FAIL', title: 'Test report', summary: '212 of 214 passed, 2 failed.', ts: now - 400 } }),
  blocked: full({ report: { id: 'r-blk', verdict: 'BLOCKED', title: 'Test report', summary: 'Tests could not run.', ts: now - 90000 } }),
  err: { error: true },
  hostile: full({ chat: { state: 'ok', text: HOSTILE_CHAT, ts: now - 30, tool: 'Bash' }, report: { id: 'r-h', verdict: 'PASS', title: '<b>Title</b> ' + LONGPATH, summary: 'S'.repeat(400) + ' [x](http://evil.example) <i>', ts: now - 86400 * 9 }, status: { note: 'N'.repeat(300) + ' <u>note</u>', ts: now - 86400 * 400 } })
};
module.exports = { now, U, BIDI, AR, LONGPATH, full, busy, P, D, HOSTILE_CHAT };
