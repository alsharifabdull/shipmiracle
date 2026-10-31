// Panel v3 card buttons ({type:'act'}) against a stand-in for VS Code: the panel never writes a playbook, a charter or an approval; plan opens the plan; report stays inside the project.
// Run: node tests/ext_card_v3_test.js
require('./shipmiracle_isolation').apply();
const Module = require('module'); const path = require('path'); const fs = require('fs'); const os = require('os');
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'shipmiracle-c3-'));
const ST = path.join(tmp, 'state'), WSD = path.join(tmp, 'ws'), PROJ = path.join(tmp, 'Dev', 'demo');
for (const d of [ST, path.join(WSD, 'config'), path.join(PROJ, 'docs', 'plans'), path.join(PROJ, 'docs', 'reports')]) fs.mkdirSync(d, { recursive: true });
fs.writeFileSync(path.join(PROJ, 'docs', 'plans', 'a.md'), '# plan'); fs.writeFileSync(path.join(PROJ, 'docs', 'reports', 'r.md'), '# r'); fs.writeFileSync(path.join(tmp, 'secret.md'), 'x');
fs.symlinkSync(path.join(tmp, 'secret.md'), path.join(PROJ, 'docs', 'reports', 'link.md'));
Object.assign(process.env, { SHIPMIRACLE_TEST: '1', SHIPMIRACLE_EXT_STATE: ST, SHIPMIRACLE_EXT_WS: WSD, SHIPMIRACLE_EXT_DEV: path.join(tmp, 'Dev'), SHIPMIRACLE_DIAG_DIR: path.join(tmp, 'diag'), SHIPMIRACLE_HEAL_MS: '99999999' });
const execs = [], opened = [], infos = []; 
const proj = { name: 'demo', dir: PROJ, stack: 'web', state: 'idle', agents: [], tokens: {}, ideas: { open: [], evaluated: [], done: 0, dropped: 0 }, held: false, cr: [{ id: 'CR-013', status: 'queued' }], playbook: { type: 'software', autopilot: 'guided', level: 'strict' } };
const proxy = () => new Proxy(function () {}, { get: (t, k) => k === 'then' ? undefined : (k === 'dispose' ? () => {} : proxy()), apply: () => proxy() });
const vscode = new Proxy({}, { get: (t, k) => {
  if (k === 'window') return new Proxy({}, { get: (w, kk) => {
    if (kk === 'terminals') return [];
    if (kk === 'registerWebviewViewProvider') return (id, prov) => { module.provider = prov; return { dispose() {} }; };
    if (kk === 'showInformationMessage') return (m) => { infos.push(m); return Promise.resolve(); };
    if (kk === 'showTextDocument') return async d => { opened.push(d.uri.fsPath); };
    if (kk === 'activeTerminal') return undefined;
    return proxy(); } });
  if (k === 'workspace') return new Proxy({}, { get: (w, kk) => kk === 'openTextDocument' ? async u => ({ uri: u }) : proxy() });
  if (k === 'commands') return { registerCommand: () => ({ dispose() {} }), executeCommand: async () => {} };
  if (k === 'Uri') return { parse: s => ({ s }), file: f => ({ fsPath: f }) };
  if (k === 'ThemeIcon' || k === 'ThemeColor') return function (n) { this.n = n; };
  if (k === 'ViewColumn') return { Active: 1 };
  if (k === 'StatusBarAlignment') return { Left: 1 };
  return proxy(); } });
const real = Module._load;
Module._load = function (req, parent, ...r) {
  if (req === 'vscode') return vscode;
  if (req === 'child_process') return { execFile: (cmd, args, o, cb) => { execs.push([cmd, args]); (cb || o)(null, '', ''); return {}; } };
  if (req === './data') return { collect: async () => ({ projects: [proj], plan: {}, guard: {}, ask: null }) };
  return real.call(this, req, parent, ...r); };
const ext = require(path.join(__dirname, '../vscode-ext/shipmiracle-panel/extension.js'));
let fails = 0; const check = (n, c, info = '') => { console.log((c ? 'PASS ' : 'FAIL ') + n + (c ? '' : ' ' + info)); if (!c) fails++; };
const wait = ms => new Promise(r => setTimeout(r, ms));
const notice = () => { try { return JSON.parse(fs.readFileSync(path.join(ST, 'project-notice.json'), 'utf8')).text; } catch (e) { return null; } };
(async () => {
  ext.activate({ subscriptions: [], globalState: { get() {}, update() {} } }); await wait(300);
  let handler; const view = { webview: { options: {}, set html(v) {}, get html() { return ''; }, onDidReceiveMessage: f => { handler = f; return { dispose() {} }; } }, visible: true, onDidChangeVisibility: () => ({ dispose() {} }), onDidDispose: () => ({ dispose() {} }) };
  module.provider.resolveWebviewView(view); await wait(400);
  const send = async m => { try { fs.unlinkSync(path.join(ST, 'project-notice.json')); } catch (e) { /* none */ } execs.length = 0; opened.length = 0; infos.length = 0; await handler({ type: 'act', project: 'demo', ...m }); await wait(150); };
  const before = fs.readdirSync(PROJ).join();
  await send({ act: 'plan' });
  check('Review plan opens the newest plan and tells the owner to type "approved"; nothing is sent to a chat', opened.length === 1 && opened[0].endsWith('a.md') && /type "approved" in the chat/.test(infos[0] || '') && execs.length === 0, JSON.stringify([opened, infos, execs]));
  await send({ act: 'openreport', report: 'docs/reports/r.md' });
  check('report inside the project opens', opened.length === 1 && opened[0].endsWith('r.md'), JSON.stringify(opened));
  for (const bad of ['../../secret.md', '/etc/hosts', 'docs/reports/link.md', 'docs/reports/none.md']) { await send({ act: 'openreport', report: bad }); check('report ' + bad + ' is refused (outside, symlink out, or missing)', opened.length === 0 && !!notice(), JSON.stringify([opened, notice()])); }
  await send({ act: 'setup' });
  check('Set up playbook only tells the exact command; it runs nothing and writes nothing', /shipm playbook set type/.test(notice() || '') && execs.length === 0 && fs.readdirSync(PROJ).join() === before, notice());
  for (const to of ['manual', 'guided', 'full']) { await send({ act: 'ap', to }); check('autopilot ' + to + ': a notice (tests/ext_charter_test.js covers the terminal), no execFile, no file written', !!notice() && execs.length === 0 && fs.readdirSync(PROJ).join() === before, notice()); }
  await send({ act: 'ap', to: 'yolo' }); check('an unknown autopilot level is ignored', notice() === null && execs.length === 0);
  await send({ act: 'start', cr: 'CR-013;rm -rf' }); check('a malformed CR id is refused', /not queued/.test(notice() || ''), notice());
  await send({ act: 'start', cr: 'CR-099' }); check('a CR that is not queued is refused', /not queued/.test(notice() || ''), notice());
  await send({ act: 'nonsense' }); check('an unknown act does nothing', notice() === null && execs.length === 0);
  await handler({ type: 'act', act: 'plan', project: 'nope' }); await wait(100); check('an unknown project does nothing', opened.length === 0);
  console.log(fails ? `\nFAILED: ${fails}` : '\nALL PASS'); fs.rmSync(tmp, { recursive: true, force: true }); process.exit(fails ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
