// The panel's New project box against a stand-in for VS Code: exact argv (no shell), validation, one run at a time, notices, chat opened.
// Run: node tests/ext_newproject_test.js
require('./shipmiracle_isolation').apply();   // test isolation: fresh HOME/SHIPMIRACLE_HOME/CONFIG/STATE unless already temp
const Module = require('module'); const path = require('path'); const fs = require('fs'); const os = require('os');
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'shipmiracle-np-'));
const ST = path.join(tmp, 'state'), DV = path.join(tmp, 'Developer'), WSD = path.join(tmp, 'ws');
for (const d of [ST, DV, WSD, path.join(DV, 'exists')]) fs.mkdirSync(d, { recursive: true });
Object.assign(process.env, { SHIPMIRACLE_TEST: '1', SHIPMIRACLE_EXT_STATE: ST, SHIPMIRACLE_EXT_DEV: DV, SHIPMIRACLE_EXT_WS: WSD, SHIPMIRACLE_DIAG_DIR: path.join(tmp, 'diag'), SHIPMIRACLE_HEAL_MS: '99999999' });
const calls = [], terms = [], registered = [], cmds = [], popups = []; let hold = null, failWith = null, failCode = 1, killedRun = false;
const proxy = () => new Proxy(function () {}, { get: (t, k) => k === 'then' ? undefined : (k === 'dispose' ? () => {} : proxy()), apply: () => proxy() });
const term = o => ({ name: o.name, opts: o, exitStatus: undefined, show() {}, sendText() {}, processId: Promise.resolve(1) });
const vscode = new Proxy({}, { get: (t, k) => {
  if (k === 'window') return new Proxy({}, { get: (w, kk) => {
    if (kk === 'terminals') return terms;
    if (kk === 'createTerminal') return o => { const x = term(o); terms.push(x); return x; };
    if (kk === 'registerWebviewViewProvider') return (id, prov) => { module.provider = prov; return { dispose() {} }; };
    if (kk === 'activeTerminal') return undefined;
    if (/^show(Information|Warning|Error)Message$|^showQuickPick$|^showInputBox$|^showTextDocument$/.test(kk)) return async m => { popups.push(kk); };
    return proxy(); } });
  if (k === 'commands') return { registerCommand: id => { registered.push(id); return { dispose() {} }; }, executeCommand: async c => { if (c !== 'setContext') cmds.push(c); } };
  if (k === 'Uri') return { parse: s => ({ s }), file: f => ({ fsPath: f }) };
  if (k === 'ThemeIcon' || k === 'ThemeColor') return function (n) { this.n = n; };
  if (k === 'ViewColumn') return { Active: 1 };
  if (k === 'StatusBarAlignment') return { Left: 1 };
  return proxy(); } });
const fakeExec = (cmd, args, opts, cb) => {
  if (cmd === '/bin/ps' || cmd === 'lsof') { (cb || opts)(null, '', ''); return; }
  if (cmd === '/bin/bash') {
    calls.push({ cmd, args, opts });
    const done = () => killedRun ? cb(Object.assign(new Error('Command failed: timed out'), { killed: true, signal: 'SIGTERM', code: null }), '', 'warning: still working') : failWith ? cb(Object.assign(new Error('Command failed'), { code: failCode }), '', failWith) : cb(null, 'Project ready', '');
    if (hold) hold.push(done); else done();
    return {};
  }
  (cb || opts)(null, '', ''); return {};
};
const real = Module._load;
Module._load = function (req, parent, ...r) {
  if (req === 'vscode') return vscode;
  if (req === 'child_process') return { execFile: fakeExec };
  if (req === './data') return { collect: async () => ({ projects: [], plan: {}, guard: {}, ask: null }) };
  return real.call(this, req, parent, ...r); };
const ext = require(path.join(__dirname, '../vscode-ext/shipmiracle-panel/extension.js'));
let fails = 0; const check = (n, c, info = '') => { console.log((c ? 'PASS ' : 'FAIL ') + n + (c ? '' : ' ' + info)); if (!c) fails++; };
const wait = ms => new Promise(r => setTimeout(r, ms));
const rd = f => { try { return JSON.parse(fs.readFileSync(path.join(ST, f), 'utf8')); } catch (e) { return null; } };
(async () => {
  ext.activate({ subscriptions: [], globalState: { get() {}, update() {} } });
  await wait(300);
  let handler; const view = { webview: { options: {}, set html(v) {}, get html() { return ''; }, onDidReceiveMessage: f => { handler = f; return { dispose() {} }; } }, visible: true, onDidChangeVisibility: () => ({ dispose() {} }), onDidDispose: () => ({ dispose() {} }) };
  module.provider.resolveWebviewView(view); await wait(300);
  const send = async m => { calls.length = 0; terms.length = 0; try { fs.unlinkSync(path.join(ST, 'project-notice.json')); } catch (e) { /* none */ } await handler({ type: 'newproject', ...m }); await wait(150); };
  const script = path.join(WSD, 'bin', 'new-project');

  await send({ name: 'My Notes', kind: 'notes', about: 'Recipes' });
  check('exact argv, no shell: /bin/bash [script, name, --type, kind, --about, text, --no-open]', calls.length === 1 && calls[0].cmd === '/bin/bash' && JSON.stringify(calls[0].args) === JSON.stringify([script, 'my-notes', '--type', 'notes', '--about', 'Recipes', '--no-open']), JSON.stringify(calls.map(c => c.args)));
  check('timeout 180 s, no shell option', calls[0].opts.timeout === 180000 && !calls[0].opts.shell);
  check('PATH extended with homebrew, /usr/local/bin and ~/.local/bin', ['/opt/homebrew/bin', '/usr/local/bin', path.join(os.homedir(), '.local', 'bin')].every(x => calls[0].opts.env.PATH.split(':').includes(x)));
  check('success: notice "Created my-notes. Its card is below: click it to open the chat."', (rd('project-notice.json') || {}).text === 'Created my-notes. Its card is below: click it to open the chat.' && typeof rd('project-notice.json').ts === 'number', JSON.stringify(rd('project-notice.json')));
  check('success: NO terminal is created, nothing opens (the card appears instead)', terms.length === 0 && popups.length === 0 && cmds.length === 0, JSON.stringify([terms.length, popups, cmds]));
  check('project-creating.json is gone after the run', rd('project-creating.json') === null);

  await send({ name: 'x', kind: 'web', about: '' });
  check('empty about: no --about in argv', JSON.stringify(calls[0].args) === JSON.stringify([script, 'x', '--type', 'web', '--no-open']), JSON.stringify(calls[0] && calls[0].args));
  await send({ name: 'y', kind: 'web', about: 'a\u0000b\u001b[31m\r\nc' + 'z'.repeat(300) });
  const ab = calls[0].args[calls[0].args.indexOf('--about') + 1];
  check('about: control characters stripped, cut to 140', ab.length === 140 && !/[\u0000-\u001f\u007f]/.test(ab), JSON.stringify(ab));

  for (const bad of ['rm -rf /', 'web;ls', '', undefined, 5, ['web'], 'WEB', 'ios ']) {
    await send({ name: 'okname', kind: bad });
    check('bad type refused (' + JSON.stringify(bad) + '): nothing runs, notice shown', calls.length === 0 && /Not created/.test((rd('project-notice.json') || {}).text || ''), JSON.stringify(calls.map(c => c.args)));
  }
  await send({ name: 'a;rm -rf /', kind: 'web' });
  const nm = calls[0] && calls[0].args[1];
  check('"a;rm -rf /" is tidied to a safe name', /^[a-z0-9][a-z0-9._-]*$/.test(nm || '') && nm === 'a-rm--rf', nm);
  await send({ name: '$(touch /tmp/x) `id` ../../etc', kind: 'web' });
  check('substitution and path tricks are tidied (no / and no leading dot or dash)', /^[a-z0-9][a-z0-9._-]*$/.test(calls[0].args[1]) && !calls[0].args[1].includes('/'), calls[0].args[1]);
  await send({ name: '...hidden', kind: 'web' });
  check('leading dots removed', calls[0].args[1] === 'hidden', calls[0] && calls[0].args[1]);
  await send({ name: 'n'.repeat(80), kind: 'web' });
  check('name cut to 40', calls[0].args[1] === 'n'.repeat(40));
  for (const bad of ['', '   ', '!!!', '..', undefined, null]) { await send({ name: bad, kind: 'web' }); check('name with no letter or digit refused (' + JSON.stringify(bad) + ')', calls.length === 0 && /Not created/.test((rd('project-notice.json') || {}).text || '')); }
  for (const rn of ['__proto__', 'constructor', 'Prototype']) { await send({ name: rn, kind: 'web' }); check('reserved name refused: ' + rn, calls.length === 0 && /reserved name/.test((rd('project-notice.json') || {}).text || ''), JSON.stringify(rd('project-notice.json'))); }
  await send({ name: 'Exists', kind: 'web' });
  check('existing folder refused, nothing runs', calls.length === 0 && /exists/.test((rd('project-notice.json') || {}).text || ''), JSON.stringify(rd('project-notice.json')));
  for (const k of ['web', 'ios', 'python', 'api', 'home', 'notes', 'other']) { await send({ name: 'k-' + k, kind: k }); if (calls.length !== 1 || calls[0].args[3] !== k) check('kind ' + k + ' accepted', false); }
  check('all 7 kinds accepted', true);

  // one at a time
  hold = []; calls.length = 0;
  await handler({ type: 'newproject', name: 'slow', kind: 'web' }); await wait(100);
  const creating = rd('project-creating.json');
  await handler({ type: 'newproject', name: 'slow2', kind: 'web' }); await handler({ type: 'newproject', name: 'slow', kind: 'web' }); await wait(100);
  check('while running: project-creating.json {name, ts} exists', creating && creating.name === 'slow' && typeof creating.ts === 'number', JSON.stringify(creating));
  check('a second click while running is ignored', calls.length === 1, String(calls.length));
  hold.splice(0).forEach(f => f()); hold = null; await wait(150);
  check('after it finishes: creating file deleted and a new run is allowed', rd('project-creating.json') === null);
  await send({ name: 'after', kind: 'web' });
  check('next create works after the first finished', calls.length === 1 && calls[0].args[1] === 'after');

  // failure
  failWith = 'warning: x\nGitHub: something broke\n'; terms.length = 0;
  await send({ name: 'fails', kind: 'web' });
  check('failure: notice "Not created: <last stderr line>"', (rd('project-notice.json') || {}).text === 'Not created: GitHub: something broke', JSON.stringify(rd('project-notice.json')));
  check('failure: no chat opened, creating file deleted', terms.length === 0 && rd('project-creating.json') === null);
  failWith = null;

  // exit 3 = created, GitHub missing
  failWith = 'GitHub: FAILED - name already exists on this account\n'; failCode = 3; terms.length = 0;
  await send({ name: 'nogh', kind: 'web' });
  check('exit 3: notice "Created <name> (GitHub not set up: <line>). Its card is below…" and still no terminal', (rd('project-notice.json') || {}).text === 'Created nogh (GitHub not set up: GitHub: FAILED - name already exists on this account). Its card is below: click it to open the chat.' && terms.length === 0 && popups.length === 0, JSON.stringify(rd('project-notice.json')));
  failCode = 2; await send({ name: 'bad2', kind: 'web' });
  check('exit 2 stays "Not created: <last line>"', /^Not created: /.test((rd('project-notice.json') || {}).text) && terms.length === 0);
  failWith = null; failCode = 1;
  // timeout
  killedRun = true; terms.length = 0;
  await send({ name: 'slowpoke', kind: 'web' });
  check('timeout: notice says stopped after 3 minutes and how to finish; it wins over stderr text', (rd('project-notice.json') || {}).text === 'Stopped after 3 minutes; ' + DV + '/slowpoke may be half-created: finish with bin/new-project slowpoke in a terminal.', JSON.stringify(rd('project-notice.json')));
  check('timeout: project-creating.json cleaned up, no chat opened, a new run is allowed', rd('project-creating.json') === null && terms.length === 0);
  killedRun = false; await send({ name: 'afterkill', kind: 'web' });
  check('after a timeout the next create runs', calls.length === 1);

  // dismiss + fallback
  fs.writeFileSync(path.join(ST, 'project-notice.json'), '{"ts":1,"text":"x"}');
  await handler({ type: 'health', op: 'dismiss-project-notice' }); await wait(100);
  check('health op dismiss-project-notice deletes project-notice.json', rd('project-notice.json') === null);
  cmds.length = 0; await handler({ type: 'cmd', name: 'newProject' }); await wait(50);
  check('task fallback intact: shipmiracle.newProject registered and the cmd message still runs it', registered.includes('shipmiracle.newProject') && JSON.stringify(cmds) === JSON.stringify(['shipmiracle.newProject']), JSON.stringify(cmds));
  const tf = path.join(__dirname, '../dotfiles/vscode-tasks.json');   // the owner's dotfiles are not part of the public export
  if (fs.existsSync(tf)) check('the "Shipmiracle: New project" task is still in dotfiles/vscode-tasks.json', fs.readFileSync(tf, 'utf8').includes('"Shipmiracle: New project"'));
  fs.rmSync(tmp, { recursive: true, force: true });
  await send({ name: 'priv-check', kind: 'web', visibility: 'public', public: true, private: false, extra: '--public' });
  check('no public option: extra fields from the page (visibility, public, extra) never reach the argv; the repo stays private (bin/new-project creates --private only)', calls.length === 1 && JSON.stringify(calls[0].args) === JSON.stringify([script, 'priv-check', '--type', 'web', '--no-open']) && !calls[0].args.some(x => /public/i.test(x)), JSON.stringify(calls));
  console.log(fails ? '\nFAILED: ' + fails : '\nALL PASS'); process.exit(fails ? 1 : 0);
})().catch(e => { console.error('test crashed:', e); process.exit(2); });
