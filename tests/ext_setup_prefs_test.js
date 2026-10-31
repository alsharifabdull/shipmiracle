// Quick setup in the extension (plan 2026-10-21-cross-platform-onboarding.md, O12) and the chat-folder lookup on every OS: {type:'setup', op:'prefs'} RUNS `shipm init --prefs ...` in the owner terminal (Enter sent since 31 Oct 2026),
// re-checks every value, refuses it with an older CLI (no onboarding fields); cwdOfPid uses lsof on darwin, /proc on linux, and answers '' (never a crash, never a guess) anywhere else.
// Run: node tests/ext_setup_prefs_test.js
require('./shipmiracle_isolation').apply();
const Module = require('module'), path = require('path'), fs = require('fs'), os = require('os');
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'shipmiracle-sp-'));
const ST = path.join(tmp, 'state'), WSD = path.join(tmp, 'ws'), DEV = path.join(tmp, 'Dev');
for (const d of [ST, path.join(WSD, 'config'), DEV]) fs.mkdirSync(d, { recursive: true });
Object.assign(process.env, { SHIPMIRACLE_TEST: '1', SHIPMIRACLE_EXT_STATE: ST, SHIPMIRACLE_EXT_WS: WSD, SHIPMIRACLE_EXT_DEV: DEV, SHIPMIRACLE_EXT_SETUP: '1', SHIPMIRACLE_DIAG_DIR: path.join(tmp, 'diag'), SHIPMIRACLE_HEAL_MS: '99999999', SHIPMIRACLE_SETUP_POLL_MS: '40', SHIPMIRACLE_SETUP_LIMIT_MS: '60' });      // a click arms a wait for its command; no command ends here, so the short limit frees the terminal before the next click
let fails = 0; const check = (n, c, info = '') => { console.log((c ? 'PASS ' : 'FAIL ') + n + (c ? '' : ' ' + info)); if (!c) fails++; };
const wait = ms => new Promise(r => setTimeout(r, ms));
const sent = [], made = []; let NEW = true;
const row = (n, id, extra = {}) => ({ n, id, title: id, need: n < 2 ? 'required' : 'optional', state: 'green', detail: '', connect: { kind: 'hint', text: '' }, ...extra });
const checkJson = () => JSON.stringify(NEW ? { v: 1, ready: true, os: { kind: 'linux', line: 'This computer: Ubuntu' }, rows: [row(0, 'engine', { stage: 'connect', class: 'required', os_supported: true, docs: '' }), row(1, 'prefs', { stage: 'prefs', class: 'optional', os_supported: true, docs: '' })] } : { v: 1, ready: true, rows: [row(0, 'engine'), row(1, 'prefs')] });
const proxy = () => new Proxy(function () {}, { get: (t, k) => k === 'then' ? undefined : (k === 'dispose' ? () => {} : proxy()), apply: () => proxy() });
const vscode = new Proxy({}, { get: (t, k) => {
  if (k === 'window') return new Proxy({}, { get: (w, kk) => {
    if (kk === 'terminals') return made;
    if (kk === 'registerWebviewViewProvider') return (id, prov) => { module.provider = prov; return { dispose() {} }; };
    if (kk === 'createTerminal') return o => { const tt = { name: o.name, exitStatus: undefined, show() {}, sendText: (x, nl) => sent.push([x, nl]), dispose() {} }; made.push(tt); return tt; };
    return proxy(); } });
  if (k === 'workspace') return new Proxy({}, { get: (w, kk) => kk === 'getConfiguration' ? () => ({ get: () => undefined }) : proxy() });
  if (k === 'commands') return { registerCommand: (id, f) => { (module.cmds = module.cmds || {})[id] = f; return { dispose() {} }; }, executeCommand: async () => {} };
  if (k === 'Uri') return { parse: s => ({ s }), file: f => ({ fsPath: f }) };
  if (k === 'ThemeIcon' || k === 'ThemeColor') return function (n) { this.n = n; };
  if (k === 'ViewColumn') return { Active: 1 }; if (k === 'StatusBarAlignment') return { Left: 1 };
  return proxy(); } });
const real = Module._load;
Module._load = function (req, parent, ...rest) {
  if (req === 'vscode') return vscode;
  if (req === 'child_process') return { execFile: (cmd, args, o, cb) => { const f = cb || o; if (args && args[0] === 'init' && args[1] === '--check') f(null, checkJson(), ''); else f(null, '', ''); return {}; } };
  if (req === './data') return { collect: async () => ({ projects: [], plan: {}, guard: {}, ask: null }) };
  return real.call(this, req, parent, ...rest); };
const ext = require(path.join(__dirname, '../vscode-ext/shipmiracle-panel/extension.js'));
(async () => {
  ext.activate({ subscriptions: [], globalState: { get() {}, update() {} } }); await wait(400);
  let handler, page = ''; const view = { webview: { options: {}, set html(v) { page = v; }, get html() { return page; }, onDidReceiveMessage: f => { handler = f; return { dispose() {} }; } }, visible: true, onDidChangeVisibility: () => ({ dispose() {} }), onDidDispose: () => ({ dispose() {} }) };
  module.provider.resolveWebviewView(view); await wait(800); await module.cmds['shipmiracle.refresh'](); await wait(300);
  const send = async prefs => { sent.length = 0; await handler({ type: 'setup', op: 'prefs', id: '', prefs }); await wait(300); };
  const line = () => (sent.find(x => x[1] === true && x[0] !== '\u0005\u0015') || [''])[0];       // since 31 Oct 2026 the Quick setup line is run (Enter sent); only the Ctrl-U line clear has no Enter
  check('the page shows the Quick setup card when the CLI sent the onboarding fields', /<section class="qs"/.test(page) && /This computer: Ubuntu/.test(page));
  await send({ lang: 'en', folder: '~/Developer', autonomy: 'normal', awake: 'yes', notify: 'vscode' });
  check('Quick setup runs `shipm init --prefs --lang en --folder ~/Developer --autonomy normal --awake yes --notify vscode` (quoted argv) with Enter', /^'[^']*\/bin\/shipm' 'init' '--prefs' '--lang' 'en' '--folder' '~\/Developer' '--autonomy' 'normal' '--awake' 'yes' '--notify' 'vscode'$/.test(line()) && sent.filter(x => x[0] !== '\u0005\u0015').every(x => x[1] === true), JSON.stringify(sent));
  await send({ lang: 'ar', folder: '/srv/work dir', autonomy: 'step', notify: 'none' }); check('without the awake choice (Linux) the command has no --awake; a folder with a space stays one quoted argument', /'--folder' '\/srv\/work dir' '--autonomy' 'step' '--notify' 'none'$/.test(line()) && !/awake/.test(line()), line());
  const bads = [{ lang: 'fr' }, { autonomy: 'full' }, { notify: 'sms' }, { awake: 'maybe' }, { folder: 'relative/path' }, { folder: '~/../etc' }, { folder: "~/x'; rm -rf ~; '" + String.fromCharCode(10) + 'y' }, { folder: '-rf' }, { folder: '~/' + 'a'.repeat(300) }, { lang: ['en'] }];
  for (const b of bads) { await send({ lang: 'en', folder: '~/Developer', autonomy: 'normal', notify: 'vscode', ...b }); check('refused: ' + JSON.stringify(b).slice(0, 60).replace(/\n/g, ' '), sent.length === 0); }
  await sent.splice(0); await handler({ type: 'setup', op: 'prefs', id: '' }); await handler({ type: 'setup', op: 'prefs', id: '', prefs: 'x' }); await wait(50); check('no prefs object / a non-object: nothing typed', sent.length === 0);
  NEW = false; await handler({ type: 'setup', op: 'recheck' }); await wait(800); await module.cmds['shipmiracle.refresh'](); await wait(300);
  await send({ lang: 'en', folder: '~/Developer', autonomy: 'normal', notify: 'vscode' });
  check('an older CLI (no onboarding fields): the card is gone and the message types nothing', !/<section class="qs"/.test(page) && !/data-os=/.test(page) && sent.length === 0);

  // platform lookup of a chat's folder
  const cwd = ext.cwdOfPid, pd = Object.getOwnPropertyDescriptor(process, 'platform'), setP = v => Object.defineProperty(process, 'platform', { value: v });
  try {
    setP('linux'); const own = '/proc/' + process.pid + '/cwd'; const expect = (() => { try { return fs.readlinkSync(own); } catch (e) { return ''; } })();
    check('linux: reads /proc/<pid>/cwd (this machine has no /proc: an empty answer, no crash)', (await cwd(process.pid)) === expect);
    check('linux: a pid that does not exist, or is not a number, gives ""', (await cwd(2147483000)) === '' && (await cwd('abc')) === '' && (await cwd(-5)) === '' && (await cwd('1;rm')) === '');
    setP('win32'); check('win32: unknown (""), no lsof is run', (await cwd(process.pid)) === '');
    setP('freebsd'); check('any other platform: unknown ("")', (await cwd(process.pid)) === '');
  } finally { Object.defineProperty(process, 'platform', pd); }
  if (process.platform === 'darwin') check('darwin: lsof answers with this process\'s folder', fs.realpathSync(await cwd(process.pid)) === fs.realpathSync(process.cwd()));
  const src = fs.readFileSync(path.join(__dirname, '../vscode-ext/shipmiracle-panel/procx.js'), 'utf8');   // the lookup moved to procx.js (E10); tests/ext_host_test.js covers it with fake process tables
  check('source: lsof is called only inside the darwin branch of cwdOfPid', (src.match(/run\('lsof'/g) || []).length === 1 && /if \(os !== 'darwin'\) return '';\s*\n\s*const out = await d\.run\('lsof'/.test(src));
  console.log(fails ? `\nFAILED: ${fails}` : '\nALL PASS'); fs.rmSync(tmp, { recursive: true, force: true }); process.exit(fails ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
