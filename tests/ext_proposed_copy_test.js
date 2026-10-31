// Proposed assets, Copy handler (extension.js proposedAction) run for real against a stand-in for VS Code: the text on the clipboard is ALWAYS the command the extension rebuilt from its own data,
// never anything the webview message carries; every malformed message copies nothing, throws nothing, creates no terminal and starts no process. Run: node tests/ext_proposed_copy_test.js
require('./shipmiracle_isolation').apply();
const Module = require('module'), path = require('path'), fs = require('fs'), os = require('os');
const PR = require('../vscode-ext/shipmiracle-panel/proposed.js');
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'shipmiracle-pcopy-'));
const ST = path.join(tmp, 'state'), WSD = path.join(tmp, 'ws'), DEV = path.join(tmp, 'Dev');
for (const d of [ST, WSD, DEV]) fs.mkdirSync(d, { recursive: true });
Object.assign(process.env, { SHIPMIRACLE_TEST: '1', SHIPMIRACLE_EXT_STATE: ST, SHIPMIRACLE_EXT_WS: WSD, SHIPMIRACLE_EXT_DEV: DEV, SHIPMIRACLE_DIAG_DIR: path.join(tmp, 'diag'), SHIPMIRACLE_HEAL_MS: '99999999' });
let clip = [], terminals = 0, execs = [], clipFail = false, caps = { toolbox: true }, projects = [];
const cmds = {};
const proxy = () => new Proxy(function () {}, { get: (t, k) => k === 'then' ? undefined : (k === 'dispose' ? () => {} : proxy()), apply: () => proxy() });
const vscode = new Proxy({}, { get: (t, k) => {
  if (k === 'env') return new Proxy({ clipboard: { writeText: async s => { if (clipFail) throw new Error('no clipboard'); clip.push(s); } } }, { get: (o, kk) => kk in o ? o[kk] : (kk === 'remoteName' ? undefined : proxy()) });
  if (k === 'window') return new Proxy({}, { get: (w, kk) => {
    if (kk === 'terminals') return [];
    if (kk === 'createTerminal') return () => { terminals++; return { show() {}, sendText() { terminals++; }, dispose() {} }; };
    if (kk === 'registerWebviewViewProvider') return (id, prov) => { module.provider = prov; return { dispose() {} }; };
    if (kk === 'activeTerminal') return undefined;
    return proxy(); } });
  if (k === 'workspace') return { openTextDocument: async u => ({ fsPath: u.fsPath }) };
  if (k === 'commands') return { registerCommand: (id, fn) => { cmds[id] = fn; return { dispose() {} }; }, executeCommand: async () => {} };
  if (k === 'Uri') return { parse: s => ({ s }), file: f => ({ fsPath: f }) };
  if (k === 'ThemeIcon' || k === 'ThemeColor') return function (n) { this.n = n; };
  if (k === 'ViewColumn') return { Active: 1 };
  if (k === 'StatusBarAlignment') return { Left: 1 };
  return proxy(); } });
const fakeExec = (cmd, args, opts, cb) => { cb = cb || opts; execs.push(cmd); cb(null, '', ''); return {}; };
const real = Module._load;
Module._load = function (req, parent, ...r) {
  if (req === 'vscode') return vscode;
  if (req === 'child_process') return { execFile: fakeExec, spawn: (...a) => { execs.push('spawn'); return { on() {}, stdout: { on() {} }, stderr: { on() {} }, unref() {} }; }, exec: (...a) => { execs.push('exec'); }, execFileSync: (...a) => { execs.push('sync'); return ''; }, execSync: (...a) => { execs.push('sync'); return ''; } };
  if (req === './data') return { collect: async () => ({ projects, plan: {}, guard: {}, ask: null, capabilities: caps }) };
  if (req === './panel') return { html: () => '<html></html>' };
  return real.call(this, req, parent, ...r); };
const ext = require(path.join(__dirname, '../vscode-ext/shipmiracle-panel/extension.js'));
let fails = 0, n = 0; const check = (name, c, info = '') => { n++; console.log((c ? 'PASS ' : 'FAIL ') + name + (c ? '' : ' ' + info)); if (!c) fails++; };
const wait = ms => new Promise(r => setTimeout(r, ms));
const note = () => { try { return JSON.parse(fs.readFileSync(path.join(ST, 'project-notice.json'), 'utf8')).text; } catch (e) { return null; } };
const view = { webview: { options: {}, set html(v) {}, get html() { return ''; }, onDidReceiveMessage: f => { module.handler = f; return { dispose() {} }; } }, visible: true, onDidChangeVisibility: () => ({ dispose() {} }), onDidDispose: () => ({ dispose() {} }) };
const ROWS = [{ path: 'scripts/seed_menu.py', why: 'new script, 3 KB, in scripts', stage: 'do' }, { path: 'docs/rtl-checklist.md', why: 'changed document, 2 KB, in docs', stage: 'verify' }, { path: 'templates/page.html', why: 'new template, 1 KB', stage: 'plan' }];
const mk = (name, extra = {}) => ({ name, dir: path.join(DEV, name), stack: 'web', state: 'idle', agents: [], tokens: {}, ideas: { open: [], evaluated: [], done: 0, dropped: 0 }, held: false, playbook: { level: 'normal' }, ...extra });
const LONG = 'n'.repeat(101);
const CMD = i => PR.clean(ROWS, 'alpha')[i].command;
// send one message; -> { copied, terminals, execs, threw }
const send = async m => {
  clip = []; terminals = 0; execs = []; let threw = false;
  const onerr = () => { threw = true; }; process.once('unhandledRejection', onerr);
  try { module.handler(m); } catch (e) { threw = true; }
  await wait(60); process.removeListener('unhandledRejection', onerr);
  return { copied: clip.slice(), terminals, execs: execs.slice(), threw };
};
const nothing = (r, what) => r.copied.length === 0 && r.terminals === 0 && r.execs.length === 0 && !r.threw;

(async () => {
  ext.activate({ subscriptions: [], globalState: { get() {}, update() {} } });
  await wait(300); module.provider.resolveWebviewView(view); await wait(300);
  fs.mkdirSync(path.join(DEV, 'alpha'), { recursive: true });
  projects = [mk('alpha', { proposed: PR.clean(ROWS, 'alpha') }), mk('beta', { proposed: PR.clean(ROWS.slice(0, 1), 'beta') }), mk('nopb', { playbook: null, proposed: PR.clean(ROWS, 'nopb') }), mk('empty', { proposed: [] }), mk(LONG, { proposed: PR.clean(ROWS, 'long') })];
  await cmds['shipmiracle.refresh'](); await wait(300);
  const good = { type: 'proposed', op: 'copy', project: 'alpha', i: 1 };
  let r = await send(good);
  check('the real handler: Copy of row 1 puts exactly the extension-rebuilt command on the clipboard (one write), no terminal, no process', r.copied.length === 1 && r.copied[0] === CMD(1) && PR.CMD.test(r.copied[0]) && r.terminals === 0 && r.execs.length === 0 && !r.threw, JSON.stringify(r));
  check('...and the panel notice says it was copied', /Copied the add command/.test(note() || ''), note());
  for (const i of [0, 2]) { r = await send({ ...good, i }); check('rows 0 and 2 copy their own commands (i=' + i + ')', r.copied.length === 1 && r.copied[0] === CMD(i), JSON.stringify(r.copied)); }
  r = await send({ ...good, project: 'beta', i: 0 });
  check('another project copies its own command (--project beta)', r.copied.length === 1 && /--project beta$/.test(r.copied[0]) && r.copied[0] === PR.clean(ROWS.slice(0, 1), 'beta')[0].command, JSON.stringify(r.copied));
  // forged fields in the message are ignored
  for (const forged of ['rm -rf ~', "shipm playbook asset add x --stage do --purpose 'evil'", CMD(0).replace('seed_menu', 'other'), '']) {
    r = await send({ ...good, command: forged, text: forged, cmd: forged, path: 'etc/passwd', why: forged, stage: 'deliver' });
    check('a forged command/path/why/stage in the message is ignored: clipboard = the rebuilt command (' + JSON.stringify(forged).slice(0, 30) + ')', r.copied.length === 1 && r.copied[0] === CMD(1) && !r.threw, JSON.stringify(r.copied));
  }
  // bad row numbers
  const BADI = [-1, NaN, Infinity, 1e9, 0.5, 3, '0', '1', {}, [0], [1], '__proto__', 'length', 'constructor', null, undefined, true, false, -0.0001, 2 ** 53, '1e0', ' 1', { valueOf: () => 1 }, { toString: () => '1' }, 4294967297];
  for (const i of BADI) { r = await send({ type: 'proposed', op: 'copy', project: 'alpha', i }); check('bad row number ' + (typeof i === 'object' && i ? JSON.stringify(i) : String(i)) + (typeof i === 'string' ? ' (string)' : '') + ': nothing copied, no throw, no terminal, no process', nothing(r), JSON.stringify(r)); }
  // bad projects
  const big = 'a'.repeat(1 << 20);
  for (const p of ['nope', '', undefined, null, 5, {}, [], ['alpha'], { toString: () => 'alpha' }, '../alpha', 'alpha/../alpha', 'alpha ', 'ALPHA', '__proto__', 'constructor', 'toString', big, 'alpha' + '\0', true]) {
    r = await send({ type: 'proposed', op: 'copy', project: p, i: 0 });
    check('bad or unknown project ' + (typeof p === 'string' ? JSON.stringify(p.slice(0, 20)) + (p.length > 20 ? ' (' + p.length + ' chars)' : '') : JSON.stringify(p) + ' (' + typeof p + ')') + ': nothing copied, no throw, no terminal, no process', nothing(r), JSON.stringify(r).slice(0, 200));
  }
  r = await send({ type: 'proposed', op: 'copy', project: LONG, i: 0 }); check('a project name over 100 characters is refused even when such a project is known (the name bound is the handler\'s own)', nothing(r), JSON.stringify(r).slice(0, 200));
  r = await send({ type: 'proposed', op: 'copy', project: 'nopb', i: 0 }); check('a project without a playbook: nothing copied', nothing(r));
  r = await send({ type: 'proposed', op: 'copy', project: 'empty', i: 0 }); check('a project with no proposed rows: nothing copied', nothing(r));
  // bad ops and message shapes
  for (const m of [{ ...good, op: 'run' }, { ...good, op: 'add' }, { ...good, op: 'type' }, { ...good, op: 'COPY' }, { ...good, op: ['copy'] }, { ...good, op: undefined }, { type: 'proposed', project: 'alpha', i: 1 }, { ...good, type: 'proposedx' }, { ...good, type: ['proposed'] },
    { type: 'proposed' }, { type: 'proposed', op: 'copy' }, {}, null, undefined, 'proposed', 'copy', 5, true, [], [good], [{ type: 'proposed' }], Object.create(null)]) {
    r = await send(m); check('message ' + JSON.stringify(m === undefined ? 'undefined' : m).slice(0, 70) + ': nothing copied, no throw, no terminal, no process', nothing(r) || (m && m.type !== 'proposed' && r.copied.length === 0 && !r.threw && r.terminals === 0 && r.execs.length === 0), JSON.stringify(r));
  }
  // capability off: nothing
  caps = { toolbox: false }; await cmds['shipmiracle.refresh'](); await wait(300);
  r = await send(good); check('the CLI has no toolbox capability: nothing copied', nothing(r), JSON.stringify(r));
  caps = { toolbox: true }; await cmds['shipmiracle.refresh'](); await wait(300);
  // a clipboard that fails: notice, no throw, still no terminal
  clipFail = true; r = await send(good); clipFail = false;
  check('a clipboard that fails: no throw, no terminal, no process, the notice says so', r.copied.length === 0 && !r.threw && r.terminals === 0 && r.execs.length === 0 && /Could not read the proposed assets/.test(note() || '') || /proposed/i.test(note() || ''), note());
  // a row whose stored command was tampered with (data side): refused by the strict shape
  projects[0].proposed[0].command = "shipm playbook asset add x --stage do --purpose 'a' ; rm -rf ~"; await cmds['shipmiracle.refresh'](); await wait(300);
  r = await send({ ...good, i: 0 }); check('a stored command that breaks the strict shape is never copied', nothing(r), JSON.stringify(r));
  r = await send({ ...good, i: 1 }); check('...while the untouched rows still copy', r.copied.length === 1 && r.copied[0] === CMD(1));
  fs.rmSync(tmp, { recursive: true, force: true });
  console.log(`\n${n - fails}/${n} passed`); process.exit(fails ? 1 : 0);
})().catch(e => { console.log('FAIL crashed ' + e.stack); process.exit(1); });
