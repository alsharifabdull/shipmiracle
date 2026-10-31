// data.js and the timeline fields of `shipm report panel`: caps.release, release {last, working, since} and history[] are cleaned and handed on; the per-project answer is re-read when a tag, packed-refs,
// the version file or a commit changes (and not before). A stand-in engine answers and counts its calls.
// Run: node tests/data_timeline_test.js
require('./shipmiracle_isolation').apply();
const fs = require('fs'); const os = require('os'); const path = require('path');
const ROOT = fs.mkdtempSync(path.join(os.tmpdir(), 'shipmiracle-datatl-'));
const STATE = path.join(ROOT, 'state'), DEV = path.join(ROOT, 'dev'), WS = path.join(DEV, 'AI-Workspace'), COUNT = path.join(ROOT, 'calls.txt'), REPLY = path.join(ROOT, 'reply.json');
delete process.env.CLAUDECODE;
Object.assign(process.env, { SHIPMIRACLE_TEST: '1', SHIPMIRACLE_EXT_STATE: STATE, SHIPMIRACLE_EXT_DEV: DEV, SHIPMIRACLE_EXT_WS: WS, SHIPMIRACLE_HOME: path.join(ROOT, 'home'), SHIPMIRACLE_STATE: STATE });
const PD = path.join(DEV, 'app');
for (const d of [path.join(WS, 'bin'), path.join(WS, 'config'), STATE, path.join(PD, '.git', 'refs', 'tags'), path.join(PD, '.git', 'logs'), path.join(PD, '.shipmiracle'), path.join(DEV, 'plain', '.git')]) fs.mkdirSync(d, { recursive: true });
fs.writeFileSync(path.join(PD, '.shipmiracle', 'playbook.json'), '{}\n'); fs.writeFileSync(path.join(PD, 'package.json'), '{"version":"1.0.0"}\n');
fs.writeFileSync(path.join(WS, 'bin', 'shipm'), `#!/bin/bash\nif [ "$1 $2" = "report panel" ]; then echo x >> "${COUNT}"; cat "${REPLY}"; fi\n`, { mode: 0o755 });
const reply = o => fs.writeFileSync(REPLY, JSON.stringify({ v: 1, playbook: { type: 'software', level: 'strict', autopilot: 'guided' }, cr: [], stageLabels: null, nextAction: null, lastVerdict: null, autopilot: null, ...o }));
const good = { last: { version: '1.0', date: '2026-10-12', tag: 'v1.0' }, working: { version: '1.1', source: 'package.json' }, since: { changes: 2, commits: 5 } };
const hist = [{ id: 'CR-009', title: 'Arabic onboarding', status: 'delivered', closed: '2026-10-11', release: '1.0' }, { id: 'CR-010', title: 'Next thing', status: 'delivered', closed: '2026-10-20', release: null }];
reply({ caps: { toolbox: true, interview: true, aside: true, unread: true, release: true }, release: good, history: hist });
const { collect } = require(path.join(__dirname, '../vscode-ext/shipmiracle-panel/data.js'));
let fails = 0, total = 0; const check = (n, c, info = '') => { total++; console.log((c ? 'PASS ' : 'FAIL ') + n + (c ? '' : ' ' + String(info).slice(0, 300))); if (!c) fails++; };
const calls = () => { try { return fs.readFileSync(COUNT, 'utf8').trim().split('\n').length; } catch (e) { return 0; } };
const wait = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  let d = await collect(), p = d.projects.find(x => x.name === 'app');
  check('capabilities.release is true when the engine says caps.release', d.capabilities.release === true, JSON.stringify(d.capabilities));
  check('release and history reach the project unchanged', JSON.stringify(p.release) === JSON.stringify(good) && JSON.stringify(p.history) === JSON.stringify(hist), JSON.stringify([p.release, p.history]));
  const plain = d.projects.find(x => x.name === 'plain');
  check('a project without a playbook gets release null and history null', plain.release === null && plain.history === null, JSON.stringify([plain.release, plain.history]));
  const n1 = calls(); await collect(); check('a second refresh answers from the cache (no new engine call)', calls() === n1, n1 + ' -> ' + calls());
  const bump = async (what, fn) => { const before = calls(); await wait(25); fn(); await collect(); check(what + ' re-reads the engine', calls() === before + 1, before + ' -> ' + calls()); };
  await bump('a new tag file in .git/refs/tags', () => fs.writeFileSync(path.join(PD, '.git', 'refs', 'tags', 'v1.1'), 'abc\n'));
  await bump('a changed .git/packed-refs', () => fs.writeFileSync(path.join(PD, '.git', 'packed-refs'), '# pack-refs\nabc refs/tags/v1.2\n'));
  await bump('a changed version file (package.json)', () => fs.writeFileSync(path.join(PD, 'package.json'), '{"version":"1.1.0"}\n'));
  await bump('a new commit (.git/logs/HEAD)', () => fs.writeFileSync(path.join(PD, '.git', 'logs', 'HEAD'), 'x\n'));
  const n2 = calls(); await collect(); check('nothing changed again -> cached', calls() === n2);

  reply({ caps: { release: true }, release: { last: { version: 7, date: ['x'], tag: {} }, working: { version: '', source: 'x' }, since: { changes: -3, commits: 'many' } }, history: [1, null, { id: '', title: 'no id' }, ...Array.from({ length: 14 }, (_, i) => ({ id: 'CR-' + (100 + i), title: 'T' + i, status: 'delivered', closed: '2026-10-01', release: i % 2 ? '1.0' : null }))] });
  await wait(25); fs.writeFileSync(path.join(PD, '.git', 'logs', 'HEAD'), 'y\n'); d = await collect(); p = d.projects.find(x => x.name === 'app');
  check('hostile release data is cleaned: no last/working from wrong types, counts 0', p.release && p.release.last === null && p.release.working === null && p.release.since.changes === 0 && p.release.since.commits === 0, JSON.stringify(p.release));
  check('history keeps only rows with an id, at most 10, every field text (release null stays null)', p.history.length === 10 && p.history.every(x => x.id && typeof x.title === 'string' && typeof x.status === 'string') && p.history[0].release === null && p.history[1].release === '1.0', JSON.stringify(p.history).slice(0, 200));

  reply({ caps: { toolbox: true, release: false }, release: good, history: hist });
  await wait(25); fs.writeFileSync(path.join(PD, '.git', 'logs', 'HEAD'), 'z\n'); d = await collect();
  check('capabilities.release never flips back off once the engine has shown it (same as the other flags)', d.capabilities.release === true);
  reply({ caps: { toolbox: true } });
  await wait(25); fs.writeFileSync(path.join(PD, '.git', 'logs', 'HEAD'), 'w\n'); d = await collect(); p = d.projects.find(x => x.name === 'app');
  check('an engine answer without release/history gives null for both', p.release === null && p.history === null, JSON.stringify([p.release, p.history]));
  console.log(fails ? `\nFAILED: ${fails} of ${total}` : `\nALL PASS (${total})`); fs.rmSync(ROOT, { recursive: true, force: true }); process.exit(fails ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
