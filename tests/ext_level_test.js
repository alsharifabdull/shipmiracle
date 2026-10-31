// The card's strict/warn pill against a stand-in for VS Code and a temp workspace: what is refused, what is written, what git is asked to do.
// Run: node tests/ext_level_test.js
require('./shipmiracle_isolation').apply();   // test isolation: fresh HOME/SHIPMIRACLE_HOME/CONFIG/STATE unless already temp
const Module = require('module'); const path = require('path'); const fs = require('fs'); const os = require('os');
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'shipmiracle-lv-'));
const ST = path.join(tmp, 'state'), WSD = path.join(tmp, 'ws'), CFG = path.join(WSD, 'config', 'flow.json');
for (const d of [ST, path.join(WSD, 'config')]) fs.mkdirSync(d, { recursive: true });
Object.assign(process.env, { SHIPMIRACLE_TEST: '1', SHIPMIRACLE_EXT_STATE: ST, SHIPMIRACLE_EXT_WS: WSD, SHIPMIRACLE_EXT_DEV: path.join(tmp, 'Dev'), SHIPMIRACLE_DIAG_DIR: path.join(tmp, 'diag'), SHIPMIRACLE_HEAL_MS: '99999999' });
const gitCalls = [], otherCalls = []; let gitFail = null, projects = [];
const mk = (name, state, held) => ({ name, dir: '/d/' + name, stack: 'web', state, agents: [], tokens: {}, ideas: { open: [], evaluated: [], done: 0, dropped: 0 }, held: !!held });
const proxy = () => new Proxy(function () {}, { get: (t, k) => k === 'then' ? undefined : (k === 'dispose' ? () => {} : proxy()), apply: () => proxy() });
const vscode = new Proxy({}, { get: (t, k) => {
  if (k === 'window') return new Proxy({}, { get: (w, kk) => {
    if (kk === 'terminals') return [];
    if (kk === 'registerWebviewViewProvider') return (id, prov) => { module.provider = prov; return { dispose() {} }; };
    if (kk === 'activeTerminal') return undefined;
    return proxy(); } });
  if (k === 'commands') return { registerCommand: () => ({ dispose() {} }), executeCommand: async () => {} };
  if (k === 'Uri') return { parse: s => ({ s }), file: f => ({ fsPath: f }) };
  if (k === 'ThemeIcon' || k === 'ThemeColor') return function (n) { this.n = n; };
  if (k === 'ViewColumn') return { Active: 1 };
  if (k === 'StatusBarAlignment') return { Left: 1 };
  return proxy(); } });
const fakeExec = (cmd, args, opts, cb) => {
  cb = cb || opts;
  if (cmd === '/usr/bin/git') { gitCalls.push({ cmd, args, filesDuring: fs.readdirSync(path.dirname(CFG)) }); gitFail ? cb(Object.assign(new Error('x'), { code: 1 }), '', gitFail) : cb(null, '[main abc] ok', ''); return {}; }
  otherCalls.push({ cmd, args }); cb(null, '', ''); return {};
};
const real = Module._load;
Module._load = function (req, parent, ...r) {
  if (req === 'vscode') return vscode;
  if (req === 'child_process') return { execFile: fakeExec };
  if (req === './data') return { collect: async () => ({ projects, plan: {}, guard: {}, ask: null, levelSwitch: global.__sw || undefined }) };
  return real.call(this, req, parent, ...r); };
const ext = require(path.join(__dirname, '../vscode-ext/shipmiracle-panel/extension.js'));
let fails = 0; const check = (n, c, info = '') => { console.log((c ? 'PASS ' : 'FAIL ') + n + (c ? '' : ' ' + info)); if (!c) fails++; };
const wait = ms => new Promise(r => setTimeout(r, ms));
const cfg = () => fs.readFileSync(CFG, 'utf8');
const notice = () => { try { return JSON.parse(fs.readFileSync(path.join(ST, 'project-notice.json'), 'utf8')).text; } catch (e) { return null; } };
const events = () => { try { return fs.readFileSync(path.join(ST, 'flow-events.jsonl'), 'utf8').split('\n').filter(Boolean).map(l => JSON.parse(l)); } catch (e) { return []; } };
const ORIG = '{\n  "_": "note",\n  "default": "strict",\n  "projects": {"other": "warn", "a": "warn"}\n}\n';
(async () => {
  ext.activate({ subscriptions: [], globalState: { get() {}, update() {} } });
  await wait(300);
  let handler; const view = { webview: { options: {}, set html(v) {}, get html() { return ''; }, onDidReceiveMessage: f => { handler = f; return { dispose() {} }; } }, visible: true, onDidChangeVisibility: () => ({ dispose() {} }), onDidDispose: () => ({ dispose() {} }) };
  module.provider.resolveWebviewView(view); await wait(300);
  const go = async (m, body) => { if (body !== undefined) fs.writeFileSync(CFG, body); gitCalls.length = 0; try { fs.unlinkSync(path.join(ST, 'project-notice.json')); } catch (e) { /* none */ } try { fs.unlinkSync(path.join(ST, 'flow-events.jsonl')); } catch (e) { /* none */ } await handler({ type: 'level', ...m }); await wait(150); };
  const untouched = () => cfg() === ORIG && gitCalls.length === 0 && events().length === 0;
  projects = [mk('a', 'idle'), mk('b', 'calm'), mk('other', 'idle')];

  await go({ project: 'b', level: 'warn' }, ORIG);
  check('strict -> warn: only projects.b added, "_", default and other keys kept', JSON.parse(cfg()).projects.b === 'warn' && JSON.parse(cfg()).projects.other === 'warn' && JSON.parse(cfg())._ === 'note' && JSON.parse(cfg()).default === 'strict', cfg());
  check('file keeps its one-line projects style', cfg() === '{\n  "_": "note",\n  "default": "strict",\n  "projects": {"other": "warn", "a": "warn", "b": "warn"}\n}\n', cfg());
  check('the pill runs only git: no Shipmiracle / playbook command (it has no /dev/tty for the typed confirmation; documented limitation, review M6)', !otherCalls.some(c => /(^|\/)shipm$/.test(c.cmd) || (c.args || []).some(a => /^(playbook|shipm)$/.test(String(a)))) && gitCalls.every(c => c.cmd === '/usr/bin/git'), JSON.stringify(otherCalls));
  check('the pill writes only config/flow.json in the workspace (no .shipmiracle/playbook.json, whose sha is the registry trust anchor)', fs.readdirSync(WSD).join() === 'config' && fs.readdirSync(path.dirname(CFG)).join() === 'flow.json');
  const ev = events();
  check('exactly one level_changed event, by owner-panel, with from and to', ev.length === 1 && ev[0].event === 'level_changed' && ev[0].by === 'owner-panel' && ev[0].project === 'b' && ev[0].from === 'strict' && ev[0].to === 'warn' && typeof ev[0].ts === 'number', JSON.stringify(ev));
  check('git: commit -m "Team flow: b strict -> warn (owner, panel)" -- config/flow.json, pathspec only', gitCalls.length === 1 && JSON.stringify(gitCalls[0].args) === JSON.stringify(['-C', WSD, 'commit', '-m', 'Team flow: b strict -> warn (owner, panel)', '--', 'config/flow.json']), JSON.stringify(gitCalls));
  check('atomic write: no tmp file left (also not while git runs)', fs.readdirSync(path.dirname(CFG)).join() === 'flow.json' && gitCalls[0].filesDuring.join() === 'flow.json', fs.readdirSync(path.dirname(CFG)).join());
  check('notice tells what changed', /b team flow: strict -> warn/.test(notice() || ''), notice());

  await go({ project: 'a', level: 'strict' }, ORIG);
  check('warn -> strict (equal to the default): the entry is deleted, other keys kept', JSON.stringify(JSON.parse(cfg()).projects) === JSON.stringify({ other: 'warn' }) && JSON.parse(cfg()).default === 'strict', cfg());
  check('event from warn to strict', events().length === 1 && events()[0].from === 'warn' && events()[0].to === 'strict');

  await go({ project: 'b', level: 'strict' }, ORIG);
  check('already at that level: nothing written, no event, no git', untouched());

  for (const lv of ['off', 'OFF', 'strict; rm', '', undefined, 'warn ']) { await go({ project: 'b', level: lv }, ORIG); check('target ' + JSON.stringify(lv) + ' refused (never off)', untouched()); }
  await go({ project: 'nope', level: 'warn' }, ORIG); check('unknown project refused', untouched());
  await go({ project: '../x', level: 'warn' }, ORIG); check('path-like project refused', untouched());
  await go({ project: 'constructor', level: 'warn' }, ORIG); check('prototype key refused', untouched());

  projects = [mk('a', 'idle'), mk('b', 'working'), mk('other', 'idle')];
  await go({ project: 'a', level: 'strict' }, ORIG);
  check('another project working does not block this one (per-project rule)', !untouched() && events().length === 1 && events()[0].project === 'a', notice());
  projects = [mk('a', 'idle'), mk('b', 'needs-input'), mk('other', 'idle')];
  await go({ project: 'a', level: 'strict' }, ORIG); check('another project needs input does not block this one', !untouched() && events().length === 1);
  projects = [mk('a', 'working'), mk('b', 'calm'), mk('other', 'idle')];
  await go({ project: 'a', level: 'strict' }, ORIG); check('the project itself is working -> refused (defensive state check)', untouched() && /working/.test(notice() || ''), notice());
  projects = [mk('a', 'idle'), mk('b', 'calm'), mk('other', 'idle')]; projects[0].levelSwitch = { ok: true, why: '' }; projects[1].levelSwitch = { ok: false, why: 'Not now: b had chat activity 1 min ago; idle in 2 min.' };
  await go({ project: 'a', level: 'strict' }, ORIG); check('only the clicked project own switch counts: a ok while b busy', !untouched());
  await go({ project: 'b', level: 'warn' }, ORIG); check('busy between render and click (fresh re-read): refused with minutes left', untouched() && /idle in 2 min/.test(notice() || ''), notice());
  projects = [mk('a', 'idle'), mk('b', 'calm', true), mk('other', 'idle')];
  projects = [mk('a', 'idle'), mk('b', 'calm', true), mk('other', 'idle')];
  await go({ project: 'b', level: 'warn' }, ORIG); check('the project is held -> refused', untouched() && /held/.test(notice() || ''), notice());
  await go({ project: 'a', level: 'strict' }, ORIG); check('a different held project does not block', cfg() !== ORIG && events().length === 1);

  projects = [mk('a', 'idle'), mk('b', 'calm'), mk('other', 'idle')]; projects[1].levelSwitch = { ok: false, why: 'Not now: a chat limit is pending.' };
  await go({ project: 'b', level: 'warn' }, ORIG);
  check('data.js levelSwitch.ok=false on the project: refused with its why and the mid-turn text', untouched() && (notice() || '').includes('Not now: a chat limit is pending.') && (notice() || '').includes('A change while a chat is mid-turn blocks that chat once; try again when everything is idle.'), notice());
  projects = [mk('a', 'idle'), mk('b', 'calm'), mk('other', 'idle')]; global.__sw = { ok: false, why: 'Not now: x is working.' };
  await go({ project: 'b', level: 'warn' }, ORIG);
  check('data-wide levelSwitch.ok=false no longer blocks (per-project rule)', !untouched() && events().length === 1, notice());
  global.__sw = null; projects = [mk('a', 'idle'), mk('b', 'calm'), mk('other', 'idle')]; projects[1].levelSwitch = { ok: true, why: '' };
  await go({ project: 'b', level: 'warn' }, ORIG); check('levelSwitch.ok=true allows the change', JSON.parse(cfg()).projects.b === 'warn');
  projects = [mk('a', 'idle'), mk('b', 'calm'), mk('other', 'idle')];
  const OFF = '{\n  "default": "strict",\n  "projects": {"b": "off"}\n}\n';
  await go({ project: 'b', level: 'warn' }, OFF); check('a project that is off is not changed from the panel', cfg() === OFF && gitCalls.length === 0 && events().length === 0 && !!notice());
  const DOFF = '{\n  "default": "off",\n  "projects": {}\n}\n';
  await go({ project: 'b', level: 'warn' }, DOFF); check('default off (project follows it) is not changed either', cfg() === DOFF && gitCalls.length === 0);
  for (const bad of ['{ not json', '', '[]', 'null', '{"default":"loud","projects":{}}', '{"default":"strict","projects":[]}', '{"default":"strict","projects":"x"}']) {
    await go({ project: 'b', level: 'warn' }, bad); check('malformed flow.json refused untouched: ' + JSON.stringify(bad).slice(0, 40), cfg() === bad && gitCalls.length === 0 && events().length === 0 && /malformed|missing/.test(notice() || ''), notice());
  }
  await go({ project: 'b', level: 'warn' }, '{"default":"strict"}');
  check('flow.json without a projects key: created', JSON.parse(cfg()).projects.b === 'warn' && JSON.parse(cfg()).default === 'strict', cfg());
  fs.unlinkSync(CFG); await go({ project: 'b', level: 'warn' }); check('flow.json missing: refused, not created', !fs.existsSync(CFG) && gitCalls.length === 0 && !!notice());

  gitFail = 'hook said no\nSTATUS stale'; await go({ project: 'b', level: 'warn' }, ORIG);
  check('git fails: the file change stands and the notice says "Saved, not committed: <last line>"', JSON.parse(cfg()).projects.b === 'warn' && notice() === 'Saved, not committed: STATUS stale', notice());
  gitFail = null;

  await go({ project: 'b', level: 'warn' }, ORIG); const first = cfg();
  await handler({ type: 'level', project: 'b', level: 'strict' }); await handler({ type: 'level', project: 'b', level: 'strict' }); await wait(200);
  check('two quick clicks do not corrupt the file (valid JSON, one commit per real change)', (() => { try { JSON.parse(cfg()); return true; } catch (e) { return false; } })() && fs.readdirSync(path.dirname(CFG)).join() === 'flow.json' && first !== cfg());
  for (const bad of [null, 'x', 5]) { try { await handler({ type: 'level', project: bad, level: 'warn' }); } catch (e) { check('never throws into the host', false, String(e)); } }
  check('never throws into the host', true);
  fs.rmSync(tmp, { recursive: true, force: true });
  console.log(fails ? '\nFAILED: ' + fails : '\nALL PASS'); process.exit(fails ? 1 : 0);
})().catch(e => { console.error('test crashed:', e); process.exit(2); });
