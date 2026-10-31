// The two timeline buttons ({type:'act', act:'tlmark'|'tlcr'}) against a stand-in for VS Code: the extension re-checks the version, the project and the data, then only TYPES the command into the owner's
// terminal (Ctrl-U, the line, never Enter); it never runs anything itself.
// Run: node tests/ext_timeline_route_test.js
require('./shipmiracle_isolation').apply();
const Module = require('module'); const path = require('path'); const fs = require('fs'); const os = require('os');
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'shipmiracle-tlr-'));
const ST = path.join(tmp, 'state'), WSD = path.join(tmp, 'ws'), PROJ = path.join(tmp, 'Dev', 'demo');
for (const d of [ST, path.join(WSD, 'config'), PROJ]) fs.mkdirSync(d, { recursive: true });
Object.assign(process.env, { SHIPMIRACLE_TEST: '1', SHIPMIRACLE_EXT_STATE: ST, SHIPMIRACLE_EXT_WS: WSD, SHIPMIRACLE_EXT_DEV: path.join(tmp, 'Dev'), SHIPMIRACLE_DIAG_DIR: path.join(tmp, 'diag'), SHIPMIRACLE_HEAL_MS: '99999999' });
const execs = [], typed = [], terms = [];
const rel = (o = {}) => ({ last: { version: '1.0', date: '2026-10-12', tag: 'v1.0' }, working: { version: '1.1', source: 'package.json' }, since: { changes: 3, commits: 6 }, ...o });
const base = { name: 'demo', dir: PROJ, stack: 'web', state: 'idle', agents: [], tokens: {}, ideas: { open: [], evaluated: [], done: 0, dropped: 0 }, held: false, cr: [], playbook: { type: 'software', autopilot: 'guided', level: 'strict' }, release: rel(), history: [] };
const proj = {}, caps = {};                                          // the extension keeps these two objects from the first collect(); each test rewrites them in place
const set = (p, c) => { for (const k of Object.keys(proj)) delete proj[k]; Object.assign(proj, p); for (const k of Object.keys(caps)) delete caps[k]; Object.assign(caps, c); };
const proxy = () => new Proxy(function () {}, { get: (t, k) => k === 'then' ? undefined : (k === 'dispose' ? () => {} : proxy()), apply: () => proxy() });
const vscode = new Proxy({}, { get: (t, k) => {
  if (k === 'window') return new Proxy({}, { get: (w, kk) => {
    if (kk === 'terminals') return [];
    if (kk === 'createTerminal') return o => { const term = { name: o && o.name, cwd: o && o.cwd, show() {}, exitStatus: undefined, sendText(s, enter) { typed.push([s, enter]); } }; terms.push(term); return term; };
    if (kk === 'registerWebviewViewProvider') return (id, prov) => { module.provider = prov; return { dispose() {} }; };
    if (kk === 'showInformationMessage') return () => Promise.resolve();
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
  if (req === './data') return { collect: async () => ({ projects: [proj], plan: {}, guard: {}, ask: null, capabilities: caps }) };
  return real.call(this, req, parent, ...r); };
const ext = require(path.join(__dirname, '../vscode-ext/shipmiracle-panel/extension.js'));
let fails = 0, total = 0; const check = (n, c, info = '') => { total++; console.log((c ? 'PASS ' : 'FAIL ') + n + (c ? '' : ' ' + String(info).slice(0, 300))); if (!c) fails++; };
const wait = ms => new Promise(r => setTimeout(r, ms));
const notice = () => { try { return JSON.parse(fs.readFileSync(path.join(ST, 'project-notice.json'), 'utf8')).text; } catch (e) { return null; } };
const SHIPM = path.join(WSD, 'bin', 'shipm');
(async () => {
  set(base, { release: true });
  ext.activate({ subscriptions: [], globalState: { get() {}, update() {} } }); await wait(300);
  let handler; const view = { webview: { options: {}, set html(v) {}, get html() { return ''; }, onDidReceiveMessage: f => { handler = f; return { dispose() {} }; } }, visible: true, onDidChangeVisibility: () => ({ dispose() {} }), onDidDispose: () => ({ dispose() {} }) };
  module.provider.resolveWebviewView(view); await wait(400);
  const send = async (m, p = base, c = { release: true }) => { set(p, c); try { fs.unlinkSync(path.join(ST, 'project-notice.json')); } catch (e) { /* none */ } execs.length = 0; typed.length = 0; terms.length = 0; await handler({ type: 'act', project: 'demo', ...m }); await wait(150); };
  const before = fs.readdirSync(PROJ).join();

  await send({ act: 'tlmark', verb: '1.1' });
  check('Mark released types the exact command in a terminal inside the project, without Enter', typed.length === 2 && typed[0][0] === '\u0015' && typed[0][1] === false && typed[1][0] === `'${SHIPM}' 'release' 'mark' '1.1' '--project' 'demo'` && typed[1][1] === false && terms[0].cwd === PROJ, JSON.stringify(typed));
  check('Mark released runs nothing itself and writes nothing', execs.length === 0 && fs.readdirSync(PROJ).join() === before);
  check('Mark released tells the owner what was typed', /demo/.test(notice() || '') && /release mark 1\.1/.test(notice() || ''), notice());
  for (const bad of ['1.2', '1.1;rm -rf', '1.1 && ls', '$(x)', '', '1.1\n', '1.1.1.1.1', 'v1.1x']) { await send({ act: 'tlmark', verb: bad }); check('Mark released with ' + JSON.stringify(bad) + ' types nothing', typed.length === 0 && !!notice(), JSON.stringify([typed, notice()])); }
  await send({ act: 'tlmark', verb: 'v1.1' }); check('a leading v in the version is accepted and typed clean (1.1)', typed.length === 2 && /'mark' '1\.1' /.test(typed[1][0]), JSON.stringify(typed));
  await send({ act: 'tlmark', verb: '1.1' }, { ...base, cr: [{ id: 'CR-013', title: 'x', status: 'open', stage: 'do' }] }); check('not typed while a change is open', typed.length === 0 && !!notice(), notice());
  await send({ act: 'tlmark', verb: '1.1' }, { ...base, cr: [{ id: 'CR-013', title: 'x', status: 'queued', stage: 'scope' }] }); check('not typed while a change is queued', typed.length === 0);
  await send({ act: 'tlmark', verb: '1.1' }, { ...base, release: rel({ since: { changes: 0, commits: 0 } }) }); check('not typed when nothing was done since the release', typed.length === 0);
  await send({ act: 'tlmark', verb: '1.1' }, { ...base, release: rel({ working: { version: '1.0', source: 'p' } }) }); check('not typed when the working version is not above the release', typed.length === 0);
  await send({ act: 'tlmark', verb: '1.1' }, { ...base, release: rel({ working: null }) }); check('not typed when there is no working version', typed.length === 0);
  await send({ act: 'tlmark', verb: '1.1' }, base, { release: false }); check('not typed when the engine does not report caps.release', typed.length === 0 && !!notice(), notice());
  await send({ act: 'tlmark', verb: '1.1' }, { ...base, playbook: null }); check('not typed for a project without a playbook', typed.length === 0);
  await send({ act: 'tlmark', verb: '1.1' }, { ...base, release: undefined }); check('not typed when the project has no release data', typed.length === 0);
  typed.length = 0; await handler({ type: 'act', act: 'tlmark', verb: '1.1', project: 'nope' }); await wait(100); check('an unknown project types nothing', typed.length === 0);

  typed.length = 0; terms.length = 0;
  await send({ act: 'tlcr' });
  check("Start a change types `shipm cr open --project demo ''` without Enter and puts the cursor between the quotes", typed.length === 3 && typed[0][0] === '\u0015' && typed[1][0] === `'${SHIPM}' 'cr' 'open' '--project' 'demo' ''` && typed[1][1] === false && typed[2][0] === '\u001b[D' && typed[2][1] === false, JSON.stringify(typed));
  check('Start a change runs nothing itself', execs.length === 0 && fs.readdirSync(PROJ).join() === before);
  await send({ act: 'tlcr' }, base, { release: false }); check('Start a change is refused without caps.release', typed.length === 0);
  await send({ act: 'tlcr' }, { ...base, playbook: null }); check('Start a change is refused without a playbook', typed.length === 0);
  await send({ act: 'tlcr' }, { ...base, held: true }); check('Start a change is refused for a held project', typed.length === 0);
  await send({ act: 'tlcr', verb: '"; rm -rf /' }); check('nothing from the page ends up in the typed line (only the fixed command)', typed.length === 3 && !/rm -rf/.test(JSON.stringify(typed)), JSON.stringify(typed));
  console.log(fails ? `\nFAILED: ${fails} of ${total}` : `\nALL PASS (${total})`); fs.rmSync(tmp, { recursive: true, force: true }); process.exit(fails ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
