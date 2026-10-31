// Panel v3 task 3, extension side: the Reports tab data and its two path guards (project folder; exactly the two state report folders), the Setup tab's
// `shipm init --check --json` parser and cache, and the owner-terminal route of Fix / Skip (argv-quoted, RUN with Enter since 31 Oct 2026). Stand-in VS Code; no real terminal, no real Shipmiracle write.
// Run: node tests/ext_reports_test.js
require('./shipmiracle_isolation').apply();
const Module = require('module'); const path = require('path'); const fs = require('fs'); const os = require('os'); const { spawnSync } = require('child_process');
const R = require('../vscode-ext/shipmiracle-panel/reports.js'), SU = require('../vscode-ext/shipmiracle-panel/setup.js'), C = require('../vscode-ext/shipmiracle-panel/charter.js');
const F3 = require('./panel_v3_tab_fixtures.js');
let fails = 0; const check = (n, c, info = '') => { console.log((c ? 'PASS ' : 'FAIL ') + n + (c ? '' : ' ' + String(info).slice(0, 600))); if (!c) fails++; };
const tmp = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'shipmiracle-rep-')));
const ST = path.join(tmp, 'state'), OUT = path.join(tmp, 'outside'), PROJ = path.join(tmp, 'Dev', 'demo'), EVIL = path.join(tmp, 'Dev', 'demo-evil');
const WSD = path.join(tmp, "ws o'x");                                       // a path with a space and a quote: the typed command must still round-trip
const w = (f, s) => { fs.mkdirSync(path.dirname(f), { recursive: true }); fs.writeFileSync(f, s); return f; };
const HEX = 'aaaaaaaaaaaa';
// ---- the state folder
const stageOk = w(path.join(ST, 'v1', 'reports', HEX, '2026-10-20-CR-012-verify.md'), F3.STAGE_MD);
w(path.join(OUT, 'secret.md'), 'TOP SECRET'); w(path.join(OUT, 'dir', 'y.md'), 'TOP SECRET 2'); w(path.join(ST, 'v1', 'secret.json'), '{"k":"s"}');
fs.symlinkSync(path.join(OUT, 'secret.md'), path.join(ST, 'v1', 'reports', HEX, 'link.md'));                   // a file symlinked out
fs.mkdirSync(path.join(ST, 'v1', 'reports', 'bbbbbbbbbbbb'), { recursive: true }); fs.rmSync(path.join(ST, 'v1', 'reports', 'bbbbbbbbbbbb'), { recursive: true });
fs.symlinkSync(path.join(OUT, 'dir'), path.join(ST, 'v1', 'reports', 'cccccccccccc'));                          // a pid folder symlinked out
fs.symlinkSync(path.join(ST, 'v1', 'secret.json'), path.join(ST, 'v1', 'reports', HEX, 'inside-link.md'));       // a symlink that stays inside the state folder but leaves the reports folder
w(path.join(ST, 'v1', 'reports', 'not-a-pid', 'z.md'), 'x'); w(path.join(ST, 'v1', 'reports', HEX, 'sub', 'deep.md'), 'x'); w(path.join(ST, 'v1', 'reports', HEX, 'note.txt'), 'x');
const digestOk = w(path.join(ST, 'v1', 'digest', '2026-10-20.md'), '# Digest · 2026-10-20\nTotals: 0\nNot verified: x\n'); w(path.join(ST, 'v1', 'digest', 'other.md'), 'x');
// ---- the projects
const crOk = w(path.join(PROJ, 'docs', 'reports', '2026-10-19-CR-011.md'), '# CR-011 Export · DELIVERED · PASS\nSummary: ok\nNot verified: None\n'); w(path.join(EVIL, 'f.md'), 'EVIL');
fs.symlinkSync(path.join(OUT, 'secret.md'), path.join(PROJ, 'docs', 'reports', 'link.md')); fs.symlinkSync(OUT, path.join(PROJ, 'docs', 'out')); w(path.join(PROJ, 'docs', 'reports', 'notes.txt'), 'x');

// ---------- 1. the index ----------
const IDX = path.join(ST, 'v1', 'reports', 'index.json');
const item = (id, kind, p, o = {}) => ({ id, project: kind === 'digest' ? '' : 'demo', kind, cr: 'CR-012', stage: kind === 'stage' ? 'verify' : null, verdict: 'PASS', ts: 1760000000, title: 't ' + id, sub: 's', path: p, private: kind !== 'cr', ...o });
const wi = items => w(IDX, JSON.stringify({ v: 1, items }));
check('index missing: an empty list with status "missing"', (() => { const x = R.readIndex(path.join(tmp, 'nostate')); return x.items.length === 0 && x.status === 'missing'; })());
wi([item('ok-stage', 'stage', stageOk, { verdict: 'fail', title: 'a\nb\u001b[31m' + 'x'.repeat(400) }), item('ok-cr', 'cr', crOk), item('ok-digest', 'digest', digestOk, { verdict: 'whatever' }), { id: 'bad kind', kind: 'stage' }, item('x', 'weird', stageOk), 5, null, 'str', [1], item('ok-stage', 'stage', stageOk), { ...item('nopath', 'stage', 7) }, { id: '../etc', kind: 'stage' }]);
const ix = R.readIndex(ST);
check('index: valid entries kept, bad kinds / bad ids / non-objects / duplicates dropped; verdict upper-cased, unknown verdict = NOT TESTED; control characters removed; titles cut to 160',
  ix.status === 'ok' && ix.items.map(x => x.id).join() === 'ok-stage,ok-cr,ok-digest,nopath' && ix.items[0].verdict === 'FAIL' && ix.items[2].verdict === 'NOT TESTED' && !/[\u0000-\u001f]/.test(ix.items[0].title) && ix.items[0].title.length <= 160 && ix.items[3].path === '', JSON.stringify(ix.items.map(x => [x.id, x.verdict, x.title.length])));
for (const [name, body] of [['malformed JSON', '{"v":1,"items":['], ['not an object', '[1,2]'], ['items not a list', '{"v":1,"items":5}'], ['empty file', '']]) {
  w(IDX, body); const x = R.readIndex(ST); check('index ' + name + ': empty list, status "bad", no crash', x.items.length === 0 && x.status === 'bad', JSON.stringify(x));
}
w(IDX, '{"v":1,"items":[' + '{"id":"a","kind":"stage","title":"' + 'x'.repeat(100) + '"},'.repeat(1) + ' '.repeat(1100000) + ']}');
{ const t0 = Date.now(); const x = R.readIndex(ST); check('index larger than 1 MB: not read (status "bad"), fast', x.status === 'bad' && x.items.length === 0 && Date.now() - t0 < 1500, JSON.stringify(x).slice(0, 100)); }
{ fs.unlinkSync(IDX); const mk = spawnSync('mkfifo', [IDX]); const t0 = Date.now(); const x = mk.status === 0 ? R.readIndex(ST) : { status: 'bad', items: [] }; check('index that is a FIFO: does not hang, status "bad"', x.status === 'bad' && Date.now() - t0 < 1500, JSON.stringify(x)); fs.unlinkSync(IDX); }
w(IDX, JSON.stringify({ v: 1, items: Array.from({ length: 700 }, (_, i) => item('r' + i, 'stage', stageOk)) })); check('index: at most 500 items', R.readIndex(ST).items.length === 500);
wi([item('ok-stage', 'stage', stageOk), item('ok-cr', 'cr', crOk), item('ok-digest', 'digest', digestOk)]);

// ---------- 2. guard for the state folder (stage and digest) ----------
const gs = (kind, f) => R.guardState(ST, kind, f);
check('state guard: a stage report <state>/v1/reports/<12 hex>/<name>.md is allowed; a digest <state>/v1/digest/YYYY-MM-DD.md too', gs('stage', stageOk).ok && gs('digest', digestOk).ok);
const refused = [['a file symlinked out of the state folder', 'stage', path.join(ST, 'v1', 'reports', HEX, 'link.md')], ['a pid folder symlinked out', 'stage', path.join(ST, 'v1', 'reports', 'cccccccccccc', 'y.md')],
  ['a symlink that stays in the state folder but leaves the reports folder', 'stage', path.join(ST, 'v1', 'reports', HEX, 'inside-link.md')], ['traversal with ..', 'stage', path.join(ST, 'v1', 'reports', HEX, '..', '..', 'secret.json')],
  ['another state file (v1/secret.json)', 'stage', path.join(ST, 'v1', 'secret.json')], ['the index itself', 'stage', IDX], ['a folder that is not a 12-hex pid', 'stage', path.join(ST, 'v1', 'reports', 'not-a-pid', 'z.md')], ['a file one level too deep', 'stage', path.join(ST, 'v1', 'reports', HEX, 'sub', 'deep.md')],
  ['not Markdown', 'stage', path.join(ST, 'v1', 'reports', HEX, 'note.txt')], ['a digest file with another name', 'digest', path.join(ST, 'v1', 'digest', 'other.md')], ['a stage report asked as a digest', 'digest', stageOk], ['a digest asked as a stage report', 'stage', digestOk],
  ['a path outside the state folder', 'stage', path.join(OUT, 'secret.md')], ['a relative path', 'stage', 'v1/reports/' + HEX + '/x.md'], ['a NUL byte', 'stage', stageOk + '\0.md'], ['not a string', 'stage', 42], ['an unknown kind (cr is not a state report)', 'cr', stageOk], ['the reports folder itself', 'stage', path.join(ST, 'v1', 'reports')]];
for (const [n, k, f] of refused) check('state guard refuses ' + n, !gs(k, f).ok, JSON.stringify(gs(k, f)));
// ---------- 3. guard for a project folder ----------
const gp = f => R.guardProject(PROJ, f);
check('project guard: docs/reports/<name>.md (relative or absolute) is allowed', gp('docs/reports/2026-10-19-CR-011.md').ok && gp(crOk).ok);
for (const [n, f] of [['traversal ../', '../demo-evil/f.md'], ['the sibling "demo-evil" (a prefix of the project name)', path.join(EVIL, 'f.md')], ['a file symlinked out', 'docs/reports/link.md'], ['a folder symlinked out', 'docs/out/secret.md'], ['/etc/hosts', '/etc/hosts'], ['not Markdown', 'docs/reports/notes.txt'], ['a missing file', 'docs/reports/none.md'], ['the project folder itself', '.'], ['a NUL byte', 'docs/reports/a.md\0'], ['empty', '']])
  check('project guard refuses ' + n, !gp(f).ok, JSON.stringify(gp(f)));
check('project guard: a project folder that does not exist is refused', !R.guardProject(path.join(tmp, 'nope'), 'docs/a.md').ok && !R.guardProject('', 'docs/a.md').ok);
const ga = f => R.guardAny(ST, PROJ, f);
check('the card link guard (state folders or project): project file, absolute stage report and digest are allowed; everything else is refused', ga('docs/reports/2026-10-19-CR-011.md').ok && ga(stageOk).ok && ga(digestOk).ok && !ga(path.join(ST, 'v1', 'secret.json')).ok && !ga(IDX).ok && !ga(path.join(ST, 'v1', 'reports', HEX, 'link.md')).ok && !ga('/etc/hosts').ok && !ga('../../x.md').ok && !ga(path.join(OUT, 'secret.md')).ok);
// ---------- 4. load(): the page sends an id, the extension finds the item and guards its path again ----------
const dirOf = n => n === 'demo' ? PROJ : '';
let L = R.load(ST, dirOf, 'ok-stage'); check('load: a stage report returns its text', L.ok && /live PDF printing/.test(L.text) && L.item.id === 'ok-stage', JSON.stringify(L).slice(0, 200));
L = R.load(ST, dirOf, 'ok-cr'); check('load: a CR report of a known project returns its text', L.ok && /CR-011/.test(L.text));
L = R.load(ST, () => '', 'ok-cr'); check('load: a CR report of an unknown project is refused', !L.ok && /unknown project/.test(L.why), JSON.stringify(L));
L = R.load(ST, dirOf, 'nope'); check('load: an id that is not in the index is refused', !L.ok && /not in the list/.test(L.why));
wi([item('t1', 'stage', path.join(ST, 'v1', 'secret.json')), item('t2', 'stage', path.join(ST, 'v1', 'reports', HEX, 'link.md')), item('t3', 'cr', path.join(OUT, 'secret.md')), item('t4', 'cr', '/etc/hosts'), item('t5', 'digest', stageOk), item('t6', 'cr', 'docs/reports/link.md'), item('big', 'stage', path.join(ST, 'v1', 'reports', HEX, 'big.md'))]);
w(path.join(ST, 'v1', 'reports', HEX, 'big.md'), 'x'.repeat(R.MAX_TEXT + 10));
for (const id of ['t1', 't2', 't3', 't4', 't5', 't6']) { L = R.load(ST, dirOf, id); check('load: a tampered index entry ' + id + ' (path outside its folder, wrong kind or symlink out) is refused and never read', !L.ok && !/SECRET/.test(JSON.stringify(L)), JSON.stringify(L)); }
L = R.load(ST, dirOf, 'big'); check('load: a report larger than 256 KB is not read into the panel (use Open file)', !L.ok && /too large/.test(L.why), JSON.stringify(L));
w(IDX, '{oops'); L = R.load(ST, dirOf, 'ok-stage'); check('load: with an unreadable index nothing opens', !L.ok);
wi([item('ok-stage', 'stage', stageOk), item('ok-cr', 'cr', crOk), item('ok-digest', 'digest', digestOk)]);

// ---------- 5. `shipm init --check --json`: the live contract and the parser ----------
const ROOT = path.join(__dirname, '..');
const live = spawnSync(path.join(ROOT, 'bin', 'shipm'), ['init', '--check', '--json'], { encoding: 'utf8', env: process.env, timeout: 30000, stdio: ['ignore', 'pipe', 'pipe'] });
const P = SU.parseCheck(live.stdout);
check('live: `shipm init --check --json` (isolation env, read-only) parses: N rows (N read from the CLI), n 0..N-1 in order, unique ids, every need and state known', live.status === 0 && P.ok && P.rows.length >= 19 && P.rows.map(r => r.n).join() === [...Array(P.rows.length).keys()].join() && new Set(P.rows.map(r => r.id)).size === P.rows.length, (live.stderr || '') + JSON.stringify(P).slice(0, 200));
check('live: the fixture rows (tests/panel_v3_tab_fixtures.js) have the same ids, titles and needs as the CLI', P.ok && F3.ROWS().map(r => [r.n, r.id, r.title, r.need].join('|')).join('~') === P.rows.map(r => [r.n, r.id, r.title, r.need].join('|')).join('~'), JSON.stringify(P.rows.map(r => r.id)));
check('live: no text from the CLI contains a token shape or a control character', P.ok && P.rows.every(r => !/ghp_|sk-ant|[\u0000-\u001f]/.test(r.detail + r.title + r.connect.text)));
check('live: required rows (the CLI\'s own need) never get Skip; Skip only for recommended / optional red rows (and the Remote Control opt-in)', P.ok && P.rows.every(r => { const a = SU.rowActions(r); return !(a.skip && r.need === 'required') && (!a.skip || ['recommended', 'optional'].includes(r.need) || r.id === 'remote-control'); }) && P.rows.filter(r => r.need === 'required').length >= 7);
// the CLI refuses --skip for required rows: the same rule in the source (shipmiracle/setup/run.py skip())
const runPy = fs.readFileSync(path.join(ROOT, 'shipmiracle', 'setup', 'run.py'), 'utf8');
check('drift: shipmiracle/setup/run.py allows --skip only for need recommended / optional (the panel follows it)', /r\["need"\] not in \("recommended", "optional"\)/.test(runPy));
const rowsJson = rows => JSON.stringify({ v: 1, ready: false, rows });
const good = () => JSON.parse(JSON.stringify(F3.ROWS()));
const bad = [['empty', ''], ['not JSON', 'Traceback (most recent call last)'], ['a list', '[]'], ['wrong version', JSON.stringify({ v: 2, ready: true, rows: good() })], ['rows missing', '{"v":1}'], ['no rows', rowsJson([])], ['41 rows', rowsJson(Array.from({ length: 41 }, (_, i) => ({ ...good()[1], n: i, id: 'r' + i })))],
  ['an id with a slash', rowsJson(good().map((r, i) => i === 2 ? { ...r, id: '../x' } : r))], ['an id with a space', rowsJson(good().map((r, i) => i === 2 ? { ...r, id: 'a b' } : r))], ['a duplicate id', rowsJson(good().map((r, i) => i === 2 ? { ...r, id: 'base' } : r))], ['an unknown need', rowsJson(good().map((r, i) => i === 2 ? { ...r, need: 'maybe' } : r))],
  ['an unknown state', rowsJson(good().map((r, i) => i === 2 ? { ...r, state: 'purple' } : r))], ['n not an integer', rowsJson(good().map((r, i) => i === 2 ? { ...r, n: '2' } : r))], ['no title', rowsJson(good().map((r, i) => i === 2 ? { ...r, title: '' } : r))], ['a null row', rowsJson([null])], ['output over 512 KB', ' '.repeat(600000) + rowsJson(good())]];
for (const [n, s] of bad) check('parseCheck: ' + n + ' is unreadable (ok:false), never a partial list', SU.parseCheck(s).ok === false, JSON.stringify(SU.parseCheck(s)));
{ const rows = good(); rows[5].detail = 'failed ' + 'ghp' + '_abcdefghijklmnopqrstuvwxyz0123456789' + ' token=abc123 password: hunter2 ' + 'sk-ant' + '-api03-abcdefghijklmnopqrstuvwxyz' + '\u001b[31m\nnext'; rows[5].connect.text = 'word '.repeat(100); rows[6].title = 'Ta '.repeat(100); rows[7].detail = 'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abc and ' + 'A1b2'.repeat(15);
  const p = SU.parseCheck(rowsJson(rows)); const t = JSON.stringify(p);
  check('parseCheck: tokens, password=..., JWTs, long base64 runs and control characters never get through; long texts are cut (300 / 80)', p.ok && !/ghp_|hunter2|sk-ant|eyJhbGci|A1b2A1b2|abc123|\\u001b/.test(t) && /\[hidden\]/.test(p.rows[5].detail) && p.rows[5].connect.text.length === 300 && p.rows[6].title.length === 80, t.slice(0, 300)); }
check('parseCheck: unknown fields are dropped and rows are sorted by n', (() => { const rows = good().reverse().map(r => ({ ...r, evil: '<script>' })); const p = SU.parseCheck(rowsJson(rows)); return p.ok && p.rows[0].n === 0 && !('evil' in p.rows[0]) && Object.keys(p.rows[0]).sort().join() === 'connect,detail,id,n,need,state,title'; })());
// the checker: argv, timeout, cache by mtime, one run at a time
(async () => {
  const sdir = path.join(tmp, 'cstate'); fs.mkdirSync(path.join(sdir, 'v1'), { recursive: true });
  let calls = [], answer = JSON.stringify({ v: 1, ready: true, rows: good() }), fail = null, clock = 1000, delay = 0;
  const runner = (file, args, opts, cb) => { calls.push({ file, args, opts }); const go = () => fail ? cb(fail, '', '') : cb(null, answer, ''); delay ? setTimeout(go, delay) : go(); return {}; };
  const ck = SU.makeChecker({ shipm: '/w/bin/shipm', stateDir: sdir, runner, env: { PATH: '/x' }, now: () => clock });
  let v = await ck.get(false);
  check('checker: one call, argv [shipm, init, --check, --json] (no shell), 5 s timeout, output cap, env passed', calls.length === 1 && calls[0].file === '/w/bin/shipm' && calls[0].args.join(' ') === 'init --check --json' && calls[0].opts.timeout === 5000 && calls[0].opts.maxBuffer === 512 * 1024 && calls[0].opts.env.PATH === '/x' && v.error === false && v.rows.length === F3.ROWS().length, JSON.stringify(calls[0]));
  await ck.get(false); clock += 5 * 60 * 1000; await ck.get(false); check('checker: cached while init.json and the install manifest are unchanged (and for 10 minutes)', calls.length === 1);
  clock += 6 * 60 * 1000; await ck.get(false); check('checker: re-run after 10 minutes', calls.length === 2);
  fs.writeFileSync(path.join(sdir, 'v1', 'init.json'), '{"v":1,"skipped":{}}'); await ck.get(false); check('checker: re-run when init.json changes (mtime)', calls.length === 3);
  const t2 = new Date(Date.now() + 5000); fs.writeFileSync(path.join(sdir, 'v1', 'install-manifest.json'), '{}'); fs.utimesSync(path.join(sdir, 'v1', 'install-manifest.json'), t2, t2); await ck.get(false); check('checker: re-run when the install manifest changes', calls.length === 4);
  await ck.get(true); check('checker: "Re-check all" (force) always runs', calls.length === 5);
  calls = []; delay = 30; const both = await Promise.all([ck.get(true), ck.get(true), ck.get(true)]); delay = 0; check('checker: concurrent calls share one run', calls.length === 1 && both[0] === both[1] && both[1] === both[2]);
  calls = []; fail = Object.assign(new Error('timed out'), { killed: true }); v = await ck.get(true); check('checker: a timeout is an error state ("Could not read setup state"), no rows', v.error === true && v.why === 'timeout' && v.rows.length === 0);
  await ck.get(false); clock += 30000; await ck.get(false); check('checker: an error is kept for a minute (no hammering) and then retried', calls.length === 1); clock += 40000; await ck.get(false); check('checker: retried after the minute', calls.length === 2);
  fail = null; answer = 'garbage'; v = await ck.get(true); check('checker: unreadable output is an error state', v.error === true && v.rows.length === 0, JSON.stringify(v));
  answer = ' '.repeat(700000); v = await ck.get(true); check('checker: huge output is an error state', v.error === true);
  const ck2 = SU.makeChecker({ shipm: '/x', stateDir: sdir, runner: () => { throw new Error('spawn failed'); }, env: {} }); v = await ck2.get(true); check('checker: a runner that throws is an error state, not a crash', v.error === true);
  const ck3 = SU.makeChecker({ shipm: '/x', stateDir: sdir, runner: (f, a, o, cb) => cb(null, JSON.stringify({ v: 1, ready: true, rows: good().map(r => r.id === 'git-id' ? { ...r, state: 'green' } : r) }), ''), env: {} }); v = await ck3.get(true); check('checker: a row that flips to green is passed on as is', v.rows.find(r => r.id === 'git-id').state === 'green');

  // ---------- 6. data.js: collect() hands the panel the reports index ----------
  const dj = spawnSync(process.execPath, ['-e', "require('./vscode-ext/shipmiracle-panel/data.js').collect().then(d => console.log(JSON.stringify(d.reports)))"], { cwd: ROOT, encoding: 'utf8', timeout: 60000, env: { ...process.env, SHIPMIRACLE_TEST: '1', SHIPMIRACLE_EXT_STATE: ST, SHIPMIRACLE_EXT_DEV: path.join(tmp, 'emptydev'), SHIPMIRACLE_EXT_WS: WSD } });
  let dr = null; try { dr = JSON.parse(dj.stdout.trim().split('\n').pop()); } catch (e) { /* none */ }
  check('data.js collect(): `reports` = { items, status } read from <state>/v1/reports/index.json', dr && dr.status === 'ok' && dr.items.map(x => x.id).join() === 'ok-stage,ok-cr,ok-digest', (dj.stderr || '') + dj.stdout.slice(0, 200));
  w(IDX, 'nope'); const dj2 = spawnSync(process.execPath, ['-e', "require('./vscode-ext/shipmiracle-panel/data.js').collect().then(d => console.log(JSON.stringify(d.reports)))"], { cwd: ROOT, encoding: 'utf8', timeout: 60000, env: { ...process.env, SHIPMIRACLE_TEST: '1', SHIPMIRACLE_EXT_STATE: ST, SHIPMIRACLE_EXT_DEV: path.join(tmp, 'emptydev'), SHIPMIRACLE_EXT_WS: WSD } });
  check('data.js collect(): a malformed index = an empty list, status "bad" (no crash)', /"status":"bad"/.test(dj2.stdout) && /"items":\[\]/.test(dj2.stdout), dj2.stdout.slice(0, 200));
  wi([item('ok-stage', 'stage', stageOk), item('ok-cr', 'cr', crOk), item('ok-digest', 'digest', digestOk)]);

  // ---------- 7. the extension against a stand-in vscode ----------
  fs.mkdirSync(path.join(WSD, 'config'), { recursive: true }); fs.mkdirSync(path.join(WSD, 'bin'), { recursive: true });
  Object.assign(process.env, { SHIPMIRACLE_TEST: '1', SHIPMIRACLE_EXT_STATE: ST, SHIPMIRACLE_EXT_WS: WSD, SHIPMIRACLE_EXT_DEV: path.join(tmp, 'Dev'), SHIPMIRACLE_DIAG_DIR: path.join(tmp, 'diag'), SHIPMIRACLE_HEAL_MS: '99999999', SHIPMIRACLE_EXT_SETUP: '1' });
  const execs = [], terms = [], sent = [], opened = [], clip = [], infos = []; let setupAnswer = JSON.stringify({ v: 1, ready: false, rows: good().map(r => r.id === 'git-id' ? { ...r, state: 'red' } : r.id === 'remote-control' ? { ...r, state: 'advisory' } : r) });
  const PS = [{ name: 'demo', dir: PROJ, stack: 'web', state: 'idle', agents: [], tokens: {}, ideas: { open: [], evaluated: [], done: 0, dropped: 0 }, held: false, level: 'strict', cr: [], playbook: { type: 'software', autopilot: 'guided', level: 'strict' } }];
  const proxy = () => new Proxy(function () {}, { get: (t, k) => k === 'then' ? undefined : (k === 'dispose' ? () => {} : proxy()), apply: () => proxy() });
  const term = o => ({ name: o.name, opts: o, exitStatus: undefined, shown: 0, show() { this.shown++; }, sendText(t, nl) { if (t === '\u0015' || t === '\u0005\u0015') return; sent.push({ term: this, text: t, nl }); }, processId: Promise.resolve(1), dispose() {} });
  const vscode = new Proxy({}, { get: (t, k) => {
    if (k === 'window') return new Proxy({}, { get: (ww, kk) => {
      if (kk === 'terminals') return terms;
      if (kk === 'createTerminal') return o => { const x = term(o); terms.push(x); return x; };
      if (kk === 'registerWebviewViewProvider') return (id, prov) => { module.provider = prov; return { dispose() {} }; };
      if (kk === 'showTextDocument') return async d => { opened.push(d.uri.fsPath); };
      if (kk === 'showInformationMessage') return async m => { infos.push(m); };
      if (kk === 'activeTerminal') return undefined;
      return proxy(); } });
    if (k === 'workspace') return new Proxy({}, { get: (ww, kk) => kk === 'openTextDocument' ? async u => ({ uri: u }) : proxy() });
    if (k === 'env') return { clipboard: { writeText: async s => { clip.push(s); } } };
    if (k === 'commands') return { registerCommand: () => ({ dispose() {} }), executeCommand: async () => {} };
    if (k === 'Uri') return { parse: s => ({ s }), file: f => ({ fsPath: f }) };
    if (k === 'ThemeIcon' || k === 'ThemeColor') return function (n) { this.n = n; };
    if (k === 'ViewColumn') return { Active: 1 };
    if (k === 'StatusBarAlignment') return { Left: 1 };
    return proxy(); } });
  const real = Module._load;
  Module._load = function (req, parent, ...r) {
    if (req === 'vscode') return vscode;
    if (req === 'child_process') return { execFile: (cmd, args, o, cb) => { execs.push([cmd, args]); const f = cb || o; if (args && args[0] === 'init') f(null, setupAnswer, ''); else f(null, '', ''); return {}; } };
    if (req === './data') return { collect: async () => ({ projects: PS, plan: {}, guard: {}, ask: null, reports: R.readIndex(ST) }) };
    return real.call(this, req, parent, ...r); };
  const ext = require(path.join(__dirname, '../vscode-ext/shipmiracle-panel/extension.js'));
  const wait = ms => new Promise(r => setTimeout(r, ms));
  const notice = () => { try { return JSON.parse(fs.readFileSync(path.join(ST, 'project-notice.json'), 'utf8')).text; } catch (e) { return null; } };
  ext.activate({ subscriptions: [], globalState: { get() {}, update() {} } }); await wait(400);
  let handler, page = ''; const view = { webview: { options: {}, set html(x) { page = x; }, get html() { return page; }, onDidReceiveMessage: f => { handler = f; return { dispose() {} }; } }, visible: true, onDidChangeVisibility: () => ({ dispose() {} }), onDidDispose: () => ({ dispose() {} }) };
  module.provider.resolveWebviewView(view); await wait(700);
  const SHIPM = path.join(WSD, 'bin', 'shipm');
  const reset = () => { terms.length = 0; sent.length = 0; opened.length = 0; clip.length = 0; infos.length = 0; for (const f of ['project-notice.json']) try { fs.unlinkSync(path.join(ST, f)); } catch (e) { /* none */ } };
  const send = async m => { await handler(m); await wait(150); };
  const checks = () => execs.filter(e => e[1] && e[1][0] === 'init' && e[1].includes('--check'));
  check('Setup: at start the extension ran `shipm init --check --json` (argv, no shell) and the page shows every fixture row and the header "Setup · 10 of M ready" (M = the fixture row count)', checks().length >= 1 && checks()[0][1].join(' ') === 'init --check --json' && (page.match(/class="chk /g) || []).length === F3.ROWS().length && new RegExp('Setup · 10 of ' + (F3.ROWS().length - 1) + ' ready').test(page), (page.match(/class="chk /g) || []).length + ' ' + execs.length);
  check('Reports: the page carries the index rows (3) and no viewer', (page.match(/class="rrow"/g) || []).length === 3 && !/class="rview"/.test(page));
  // --- Fix / Skip: RUN in the owner's terminal (Enter sent, since 31 Oct 2026); the finer behaviour is in tests/ext_setup_run_test.js
  reset(); const n0 = execs.length; await send({ type: 'setup', op: 'fix', id: 'git-id' });
  check('Setup Fix: ONE terminal "Shipmiracle · setup", the line `shipm init --step git-id` is sent WITH Enter (run), each argument single-quoted', terms.length === 1 && terms[0].name === 'Shipmiracle · setup' && terms[0].shown >= 1 && sent.length === 1 && sent[0].nl === true && sent[0].text === C.joinCmds([[SHIPM, 'init', '--step', 'git-id']]) && / 'init' '--step' 'git-id'$/.test(sent[0].text), JSON.stringify(sent.map(s => [s.text, s.nl])));
  check('Setup Fix: the quoted line round-trips through /bin/sh to the exact argv (the engine path has a space and a quote)', (() => { const o = spawnSync('/bin/sh', ['-c', 'f() { for a in "$@"; do printf "%s\\0" "$a"; done; }; f ' + sent[0].text], { encoding: 'utf8' }); return o.stdout.split('\0').slice(0, -1).join('\u0001') === [SHIPM, 'init', '--step', 'git-id'].join('\u0001'); })());
  check('Setup Fix: the panel never runs init itself (the only execFile of Shipmiracle is the read-only --check), and tells the owner it is running in the terminal', execs.slice(n0).every(e => !(e[1] || []).includes('--step')) && /^Running: this change is applied at once \(undo: shipm init --undo git-id\)\.$/.test(notice() || ''), JSON.stringify(execs.slice(n0)));
  reset(); await send({ type: 'setup', op: 'skip', id: 'github' });
  check('Setup Skip on a recommended row runs `shipm init --skip github` (Enter sent)', sent.length === 1 && sent[0].nl === true && sent[0].text === C.joinCmds([[SHIPM, 'init', '--skip', 'github']]), JSON.stringify(sent.map(s => [s.text, s.nl])));
  reset(); await send({ type: 'setup', op: 'skip', id: 'docker' }); check('Setup Skip on an optional row runs too', sent.length === 1 && /'--skip' 'docker'/.test(sent[0].text));
  reset(); await send({ type: 'setup', op: 'skip', id: 'remote-control' }); check('Setup Skip on Remote Control (opt-in row) goes through the same terminal route', sent.length === 1 && /'--skip' 'remote-control'/.test(sent[0].text) && sent[0].nl === true);
  reset(); await send({ type: 'setup', op: 'fix', id: 'remote-control' }); check('Setup Fix on Remote Control runs `shipm init --step remote-control` (the toggle itself is a later task)', sent.length === 1 && /'--step' 'remote-control'/.test(sent[0].text) && sent[0].nl === true);
  for (const [n, id] of [['a required row (git-id is red but required): no Skip, whatever the page says', 'git-id'], ['a green row', 'node'], ['an advisory row without a Fix (connectors)', 'connectors'], ['the "never" row (publishing)', 'publishing'], ['an unknown row', 'nope'], ['an id that is shell syntax', "git-id; rm -rf ~ #"], ['an id with a quote', "x'y"], ['an id that is not a string', 42], ['an empty id', '']]) {
    reset(); await send({ type: 'setup', op: 'skip', id }); check('Setup Skip refused, nothing typed: ' + n, terms.length === 0 && sent.length === 0, JSON.stringify(sent));
  }
  for (const [n, id] of [['a green row (nothing to fix)', 'node'], ['an advisory row with no Fix (backup)', 'backup'], ['an unknown row', 'nope'], ['shell syntax', '$(touch /tmp/pwn-shipmiracle)'], ['not a string', { a: 1 }]]) {
    reset(); await send({ type: 'setup', op: 'fix', id }); check('Setup Fix refused, nothing typed: ' + n, terms.length === 0 && sent.length === 0 && !fs.existsSync('/tmp/pwn-shipmiracle'), JSON.stringify(sent));
  }
  reset(); await send({ type: 'setup', op: 'rm -rf', id: 'git-id' }); await send({ type: 'setup' }); await send({ type: 'setup', op: 'fix', id: 'skipped-or-not', extra: 'x' }); check('Setup: an unknown op or a malformed message does nothing', sent.length === 0 && terms.length === 0);
  reset(); await send({ type: 'setup', op: 'fix', id: 'notify' }); check('Setup: a skipped row can be turned on again (`shipm init --step notify`)', sent.length === 1 && /'--step' 'notify'/.test(sent[0].text) && sent[0].nl === true, JSON.stringify(sent));
  reset(); await send({ type: 'setup', op: 'fix', id: 'base' }); await send({ type: 'setup', op: 'fix', id: 'github' }); check('Setup: a second Fix reuses the same terminal and sends a second line (run)', terms.length === 0 || terms.length === 1, String(terms.length));
  // --- Re-check all flips a row
  const c0 = checks().length; setupAnswer = JSON.stringify({ v: 1, ready: true, rows: good().map(r => r.id === 'git-id' ? { ...r, state: 'green' } : r) }); await send({ type: 'setup', op: 'recheck' });
  check('Setup Re-check all: runs `shipm init --check --json` again (forced) and the page flips git-id to green: "Setup · 11 of M ready"', checks().length === c0 + 1 && new RegExp('Setup · 11 of ' + (F3.ROWS().length - 1) + ' ready').test(page) && /data-row="git-id" data-need="required" data-state="green"/.test(page), checks().length + ' ' + (page.match(/Setup · \d+ of \d+/) || [])[0]);
  setupAnswer = 'not json'; await send({ type: 'setup', op: 'recheck' }); check('Setup: a check that cannot be read shows "Could not read setup state" in the page', /Could not read setup state/.test(page) && !/data-row="git-id"/.test(page));
  setupAnswer = JSON.stringify({ v: 1, ready: true, rows: good() }); await send({ type: 'setup', op: 'recheck' });
  // --- Reports viewer
  reset(); await send({ type: 'rview', op: 'view', id: 'ok-stage' });
  check('Reports view: the page now shows the viewer with the report text (labelled rows, Not verified)', /class="rview"/.test(page) && /live PDF printing on a real printer/.test(page) && /data-rv="back"/.test(page) && !/class="rrow"/.test(page), page.length);
  await send({ type: 'rview', op: 'back' }); check('Reports back: the list is shown again', !/class="rview"/.test(page) && (page.match(/class="rrow"/g) || []).length === 3);
  await send({ type: 'rview', op: 'view', id: 'ok-cr' }); check('Reports view of a CR report (inside the project)', /class="rview"/.test(page) && /Summary/.test(page) && /None listed/.test(page)); await send({ type: 'rview', op: 'back' });
  reset(); await send({ type: 'rview', op: 'open', id: 'ok-stage', path: '/etc/hosts' });
  check('Reports Open file: opens the index\'s own (guarded) path; a path field sent by the page is ignored', opened.length === 1 && opened[0] === stageOk && !opened.includes('/etc/hosts'), JSON.stringify(opened));
  reset(); await send({ type: 'rview', op: 'copy', id: 'ok-digest' }); check('Reports Copy path: the guarded real path goes to the clipboard and the owner is told', clip.length === 1 && clip[0] === digestOk && /Path copied/.test(notice() || ''), JSON.stringify([clip, notice()]));
  wi([item('t1', 'stage', path.join(ST, 'v1', 'secret.json')), item('t2', 'stage', path.join(ST, 'v1', 'reports', HEX, 'link.md')), item('t3', 'cr', path.join(OUT, 'secret.md')), item('ok-stage', 'stage', stageOk)]); await send({ type: 'rview', op: 'retry' }); await wait(300);
  for (const id of ['t1', 't2', 't3']) { reset(); await send({ type: 'rview', op: 'open', id }); const o1 = opened.length; await send({ type: 'rview', op: 'copy', id }); await send({ type: 'rview', op: 'view', id });
    check('Reports ' + id + ' (a tampered index entry): Open, Copy and View all refuse; the page says "Report not opened" and shows none of the file', o1 === 0 && opened.length === 0 && clip.length === 0 && /Report not opened/.test(page) && !/SECRET|"k":"s"/.test(page), JSON.stringify([opened, clip])); await send({ type: 'rview', op: 'back' }); }
  for (const bad of ['../etc/passwd', 'a b', '', 42, null, 'x'.repeat(200)]) { reset(); await send({ type: 'rview', op: 'view', id: bad }); await send({ type: 'rview', op: 'open', id: bad }); check('Reports: a malformed id (' + JSON.stringify(bad).slice(0, 20) + ') does nothing', opened.length === 0 && !/class="rview"/.test(page)); }
  reset(); await send({ type: 'rview', op: 'explode', id: 'ok-stage' }); check('Reports: an unknown op does nothing', opened.length === 0 && clip.length === 0 && !/class="rview"/.test(page));
  // --- the card's "report ›" link: the second guard
  wi([item('ok-stage', 'stage', stageOk)]);
  const card = async report => { reset(); await send({ type: 'act', act: 'openreport', project: 'demo', report }); };
  await card('docs/reports/2026-10-19-CR-011.md'); check('card report link: a file inside the project opens', opened.length === 1 && opened[0] === crOk, JSON.stringify(opened));
  await card(stageOk); check('card report link: an absolute stage report under <state>/v1/reports opens (second guard)', opened.length === 1 && opened[0] === stageOk, JSON.stringify(opened));
  await card(digestOk); check('card report link: an absolute digest under <state>/v1/digest opens', opened.length === 1 && opened[0] === digestOk);
  for (const [n, f] of [['another state file', path.join(ST, 'v1', 'secret.json')], ['the index', IDX], ['a symlink out of the reports folder', path.join(ST, 'v1', 'reports', HEX, 'link.md')], ['a symlink inside that leaves the folder', path.join(ST, 'v1', 'reports', HEX, 'inside-link.md')], ['a pid folder symlinked out', path.join(ST, 'v1', 'reports', 'cccccccccccc', 'y.md')], ['traversal in the state folder', path.join(ST, 'v1', 'reports', HEX, '..', '..', 'secret.json')], ['the project symlink out', 'docs/reports/link.md'], ['/etc/hosts', '/etc/hosts'], ['a sibling project', '../demo-evil/f.md']]) {
    await card(f); check('card report link refused (' + n + ')', opened.length === 0 && /Report not opened|Report not found/.test(notice() || ''), JSON.stringify([opened, notice()])); }
  // source rules
  const src = fs.readFileSync(path.join(ROOT, 'vscode-ext', 'shipmiracle-panel', 'extension.js'), 'utf8');
  const sa = src.slice(src.indexOf('function setupAction'), src.indexOf('// ---- Handoff + fresh chat'));
  check('source: setupAction only reaches the terminal route (no execFile, no exec, no spawn, no sendText with Enter)', !/execFile|\bexec\(|spawn|runner|sendText\([^)]*true/.test(sa) && /run: false/.test(sa));
  check('source: every ownerTerminal call of the extension prefills (run: false) except the one Setup helper (run: true, kind init; owner decision 31 Oct, was 21 Oct)', (src.match(/run: true/g) || []).length === 1 && /kind: 'init', run: true/.test(src) && (src.match(/ownerTerminal\(/g) || []).length >= 5);
  check('source: the panel never writes in the reports or setup routes (no writeFile / unlink in reportAction or setupAction)', !/writeFile|unlink|rename|mkdir/.test(src.slice(src.indexOf('async function reportAction'), src.indexOf('function setupAction'))) && !/writeFile|unlink|rename|mkdir/.test(sa));
  console.log(fails ? `\nFAILED: ${fails}` : '\nALL PASS'); fs.rmSync(tmp, { recursive: true, force: true }); process.exit(fails ? 1 : 0);
})().catch(e => { console.error(e); try { fs.rmSync(tmp, { recursive: true, force: true }); } catch (x) { /* */ } process.exit(2); });
