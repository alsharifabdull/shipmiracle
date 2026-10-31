// F7 Set aside in the extension (acceptance 18): the page's {type:'aside'} message only TYPES `shipm project aside|unaside NAME` into the owner's terminal (no Enter), checks the CLI's own
// answer (caps.aside, p.aside.canAside / on) and the project name, and keeps a dismissed notice out of the next page. Stand-in for VS Code. Run: node tests/ext_aside_test.js
require('./shipmiracle_isolation').apply();
const Module = require('module'), path = require('path'), fs = require('fs'), os = require('os');
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'shipmiracle-as-'));
const ST = path.join(tmp, 'state'), WSD = path.join(tmp, 'ws'), DEV = path.join(tmp, 'Dev');
for (const d of [ST, path.join(WSD, 'config'), path.join(DEV, 'demo')]) fs.mkdirSync(d, { recursive: true });
Object.assign(process.env, { SHIPMIRACLE_TEST: '1', SHIPMIRACLE_EXT_STATE: ST, SHIPMIRACLE_EXT_WS: WSD, SHIPMIRACLE_EXT_DEV: DEV, SHIPMIRACLE_DIAG_DIR: path.join(tmp, 'diag'), SHIPMIRACLE_HEAL_MS: '99999999' });
let fails = 0; const check = (n, c, info = '') => { console.log((c ? 'PASS ' : 'FAIL ') + n + (c ? '' : ' ' + info)); if (!c) fails++; };
const wait = ms => new Promise(r => setTimeout(r, ms));
const sent = [], made = [];
const proxy = () => new Proxy(function () {}, { get: (t, k) => k === 'then' ? undefined : (k === 'dispose' ? () => {} : proxy()), apply: () => proxy() });
const vscode = new Proxy({}, { get: (t, k) => {
  if (k === 'window') return new Proxy({}, { get: (w, kk) => {
    if (kk === 'terminals') return made;
    if (kk === 'registerWebviewViewProvider') return (id, prov) => { module.provider = prov; return { dispose() {} }; };
    if (kk === 'createTerminal') return o => { const tt = { name: o.name, exitStatus: undefined, show() {}, sendText: (x, nl) => sent.push([x, nl]), dispose() {} }; made.push(tt); return tt; };
    return proxy(); } });
  if (k === 'workspace') return new Proxy({}, { get: (w, kk) => kk === 'getConfiguration' ? () => ({ get: () => undefined }) : proxy() });
  if (k === 'commands') return { registerCommand: (id, f) => ({ dispose() {} }), executeCommand: async () => {} };
  if (k === 'Uri') return { parse: s => ({ s }), file: f => ({ fsPath: f }) };
  if (k === 'ThemeIcon' || k === 'ThemeColor') return function (n) { this.n = n; };
  if (k === 'ViewColumn') return { Active: 1 }; if (k === 'StatusBarAlignment') return { Left: 1 };
  return proxy(); } });
const mk = (name, aside) => ({ name, dir: path.join(DEV, name), stack: 'web', state: 'idle', agents: [], tokens: { claudeDay: 0, claudeWeek: 0 }, ideas: { open: [], evaluated: [], done: 0, dropped: 0 }, held: false, cr: null, playbook: null, flow: null, next: '', lastCommit: 0, dirty: 0, health: [], aside });
const W = { caps: { aside: true }, projects: [mk('demo', { on: false, since: null, note: null, canAside: true, reason: null, backOnList: null }), mk('busy', { on: false, canAside: false, reason: 'Not now: autopilot is running.', since: null, note: null, backOnList: null }), mk('parked', { on: true, since: 5, note: null, canAside: false, reason: null, backOnList: null }), mk('legacy', null)],
  returned: [{ project: 'parked', why: 'work', ts: Math.floor(Date.now() / 1000) - 10 }] };
const real = Module._load;
Module._load = function (req, parent, ...r) {
  if (req === 'vscode') return vscode;
  if (req === 'child_process') return { execFile: (cmd, args, o, cb) => { (cb || o)(null, '', ''); return {}; } };
  if (req === './data') return { collect: async () => ({ projects: W.projects.map(p => ({ ...p })), plan: {}, guard: {}, ask: null, capabilities: W.caps, asideReturned: W.returned }) };
  return real.call(this, req, parent, ...r); };
const ext = require(path.join(__dirname, '../vscode-ext/shipmiracle-panel/extension.js'));
(async () => {
  ext.activate({ subscriptions: [], globalState: { get() {}, update() {} } }); await wait(300);
  let handler, page = ''; const view = { webview: { options: {}, set html(v) { page = v; }, get html() { return page; }, onDidReceiveMessage: f => { handler = f; return { dispose() {} }; } }, visible: true, onDidChangeVisibility: () => ({ dispose() {} }), onDidDispose: () => ({ dispose() {} }) };
  module.provider.resolveWebviewView(view); await wait(500);
  const send = async m => { sent.length = 0; await handler({ type: 'aside', ...m }); await wait(80); };
  check('the page carries the un-aside notice from the data (once)', (page.match(/data-asidedismiss="parked"/g) || []).length === 1);
  await send({ op: 'aside', project: 'demo' });
  check('Set aside types the exact line `shipm project aside demo` (quoted argv) and does NOT press Enter', sent.length === 2 && sent[0][0] === '\u0015' && sent[1][1] === false && /^'[^']*\/bin\/shipm' 'project' 'aside' 'demo'$/.test(sent[1][0]), JSON.stringify(sent));
  await send({ op: 'aside', project: 'busy' }); check('canAside false: nothing typed (the CLI\'s reason is the notice)', sent.length === 0);
  await send({ op: 'aside', project: 'parked' }); check('Set aside on an already aside project: nothing typed', sent.length === 0);
  await send({ op: 'unaside', project: 'parked' }); check('Bring back types `shipm project unaside parked`', sent.length === 2 && /'project' 'unaside' 'parked'$/.test(sent[1][0]) && sent[1][1] === false, JSON.stringify(sent));
  await send({ op: 'unaside', project: 'demo' }); check('Bring back on a project that is not aside: nothing typed', sent.length === 0);
  await send({ op: 'aside', project: 'legacy' }); check('a project without aside data: nothing typed', sent.length === 0);
  for (const bad of [{ op: 'aside', project: 'nope' }, { op: 'aside', project: '--evil' }, { op: 'aside', project: "x'; rm -rf ~" }, { op: 'aside' }, { op: 'wipe', project: 'demo' }, { op: 'aside', project: 42 }, { op: 'aside', project: 'x'.repeat(300) }]) { await send(bad); check('refused: ' + JSON.stringify(bad).slice(0, 50), sent.length === 0); }
  await send({ op: 'dismiss', project: 'parked', ts: W.returned[0].ts });
  check('a dismissed notice is gone from the next page', !/data-asidedismiss="parked"/.test(page));
  console.log(fails ? `\nFAILED: ${fails}` : '\nALL PASS'); fs.rmSync(tmp, { recursive: true, force: true }); process.exit(fails ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
