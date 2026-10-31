// Setup Fix / Skip / Undo / Quick-setup "Run in terminal" actually RUN (owner request 31 Oct 2026): the extension types the exact argv it built and presses Enter in the visible
// "Shipmiracle · setup" terminal (the CLI asks the owner's proof there and refuses without a tty), then re-checks by itself when the command ends. Every other owner-terminal route stays typed-only.
// Run: node tests/ext_setup_run_test.js
require('./shipmiracle_isolation').apply();
const Module = require('module'), path = require('path'), fs = require('fs'), os = require('os');
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'shipmiracle-sr-'));
const ST = path.join(tmp, 'state'), WSD = path.join(tmp, 'ws'), DEV = path.join(tmp, 'Dev');
for (const d of [ST, path.join(WSD, 'config'), path.join(WSD, 'bin'), DEV]) fs.mkdirSync(d, { recursive: true });
fs.writeFileSync(path.join(WSD, 'bin', 'shipm'), '#!/bin/sh\nexit 0\n');
Object.assign(process.env, { SHIPMIRACLE_TEST: '1', SHIPMIRACLE_EXT_STATE: ST, SHIPMIRACLE_EXT_WS: WSD, SHIPMIRACLE_EXT_DEV: DEV, SHIPMIRACLE_EXT_SETUP: '1', SHIPMIRACLE_DIAG_DIR: path.join(tmp, 'diag'), SHIPMIRACLE_HEAL_MS: '99999999',
  SHIPMIRACLE_SETUP_POLL_MS: '100', SHIPMIRACLE_SETUP_LIMIT_MS: '2500' });
const EXT = path.join(__dirname, '../vscode-ext/shipmiracle-panel');
const C = require(path.join(EXT, 'charter.js')), SU = require(path.join(EXT, 'setup.js'));
let fails = 0; const check = (n, c, info = '') => { console.log((c ? 'PASS ' : 'FAIL ') + n + (c ? '' : ' ' + info)); if (!c) fails++; };
const wait = ms => new Promise(r => setTimeout(r, ms));
const SHIPM = path.join(WSD, 'bin', 'shipm');
const made = [], execs = [], closeH = [], endH = [], startH = []; let SI = false;                 // SI: new terminals report shell integration
const STATE = { 'engine': 'green', 'git-id': 'red', 'github': 'red', 'docker': 'red', 'remote-control': 'green', 'prefs': 'green' };
const NEED = { 'engine': 'required', 'git-id': 'required', 'github': 'recommended', 'docker': 'optional', 'remote-control': 'optional', 'prefs': 'optional' };
const STAGE = { 'prefs': 'prefs' };
const checkJson = () => JSON.stringify({ v: 1, ready: true, os: { kind: 'linux', line: 'This computer: Ubuntu' }, rows: Object.keys(STATE).map((id, n) => ({ n, id, title: id, need: NEED[id], state: STATE[id], detail: '', connect: { kind: 'hint', text: '' }, stage: STAGE[id] || 'connect', class: NEED[id], os_supported: true, docs: '' })) });
const proxy = () => new Proxy(function () {}, { get: (t, k) => k === 'then' ? undefined : (k === 'dispose' ? () => {} : proxy()), apply: () => proxy() });
const vscode = new Proxy({}, { get: (t, k) => {
  if (k === 'window') return new Proxy({}, { get: (w, kk) => {
    if (kk === 'terminals') return made;
    if (kk === 'registerWebviewViewProvider') return (id, prov) => { module.provider = prov; return { dispose() {} }; };
    if (kk === 'onDidCloseTerminal') return f => { closeH.push(f); return { dispose() {} }; };
    if (kk === 'onDidEndTerminalShellExecution') return f => { endH.push(f); return { dispose() {} }; };
    if (kk === 'onDidStartTerminalShellExecution') return f => { startH.push(f); return { dispose() {} }; };
    if (kk === 'createTerminal') return o => { const tt = { name: o.name, exitStatus: undefined, shellIntegration: SI ? {} : undefined, sent: [], shown: 0, show() { this.shown++; }, sendText(x, nl) { this.sent.push([x, nl]); }, dispose() {} }; made.push(tt); return tt; };
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
  if (req === 'child_process') return { execFile: (cmd, args, o, cb) => { execs.push([cmd, args]); const f = cb || o; if (args && args[0] === 'init' && args[1] === '--check') f(null, checkJson(), ''); else f(null, '', ''); return {}; } };
  if (req === './data') return { collect: async () => ({ projects: [], plan: {}, guard: {}, ask: null }) };
  return real.call(this, req, parent, ...rest); };
const ext = require(path.join(EXT, 'extension.js'));
const checks = () => execs.filter(e => e[1] && e[1][0] === 'init' && e[1][1] === '--check').length;
const notice = () => { try { return JSON.parse(fs.readFileSync(path.join(ST, 'project-notice.json'), 'utf8')).text; } catch (e) { return ''; } };
const clearNotice = () => { try { fs.unlinkSync(path.join(ST, 'project-notice.json')); } catch (e) { /* none */ } };
(async () => {
  ext.activate({ subscriptions: [], globalState: { get() {}, update() {} } }); await wait(400);
  let handler, page = ''; const view = { webview: { options: {}, set html(v) { page = v; }, get html() { return page; }, onDidReceiveMessage: f => { handler = f; return { dispose() {} }; } }, visible: true, onDidChangeVisibility: () => ({ dispose() {} }), onDidDispose: () => ({ dispose() {} }) };
  module.provider.resolveWebviewView(view); await wait(800); await module.cmds['shipmiracle.refresh'](); await wait(300);
  const send = async m => { await handler(m); await wait(120); };
  const term = () => made.find(x => x.name === 'Shipmiracle · setup');
  const reset = () => { for (const t of made) t.sent.length = 0; clearNotice(); };
  const lines = () => (term() ? term().sent.filter(x => x[0] !== '\u0005\u0015') : []);
  const hdr = () => { const m = /Setup · (\d+) to fix/.exec(page); return m ? +m[1] : /<b class="scalm">[\s\S]*?Setup complete<\/b>/.test(page) ? 0 : null; };      // number of required rows to fix: 0 = the calm "Setup complete" line
  const startEx = async (ex = {}) => { for (const f of startH) f({ terminal: term(), execution: ex }); await wait(30); return ex; };      // VS Code: a command starts in the terminal
  const endEx = async (ex, code) => { for (const f of endH) f({ terminal: term(), exitCode: code, execution: ex }); await wait(250); };
  const endOk = async code => { const ex = await startEx(); await endEx(ex, code); };                                              // the command of our click starts and ends
  const STILL = 'A command is still running in the setup terminal: finish it first.';

  check('start: the Setup header reads "Setup · 1 to fix" (git-id is red) and the extension subscribed to terminal close and to the start and end of shell executions', hdr() === 1 && closeH.length >= 1 && endH.length === 1 && startH.length === 1, JSON.stringify([hdr(), closeH.length, endH.length, startH.length]));

  // ---- the four operations run with Enter
  await send({ type: 'setup', op: 'fix', id: 'git-id' });
  check('Fix: ONE terminal "Shipmiracle · setup", Ctrl-E then Ctrl-U (one send, no Enter) clear the WHOLE prompt line, then the exact quoted line is sent WITH Enter (run:true)', made.length === 1 && term().shown >= 1 && term().sent.length === 2 && term().sent[0][0] === '\u0005\u0015' && term().sent[0][1] === false
    && term().sent[1][1] === true && term().sent[1][0] === C.joinCmds([[SHIPM, 'init', '--step', 'git-id']]), JSON.stringify(term().sent));
  check('Fix on a row that does NOT prompt (git-id): the notice says plainly it is applied at once, with the undo command (no "answer its prompt")', notice() === 'Running: this change is applied at once (undo: shipm init --undo git-id).', notice());
  check('Fix: the panel never runs init itself (execFile only ever ran the read-only --check)', execs.filter(e => e[0] === SHIPM).every(e => e[1] && e[1][0] === 'init' && e[1][1] === '--check'), JSON.stringify(execs.filter(e => e[0] === SHIPM && !(e[1] && e[1][1] === '--check'))));
  await endOk(1);

  reset(); await send({ type: 'setup', op: 'skip', id: 'github' });
  check('Skip (recommended row): `shipm init --skip github` is sent with Enter', lines().length === 1 && lines()[0][1] === true && lines()[0][0] === C.joinCmds([[SHIPM, 'init', '--skip', 'github']]), JSON.stringify(lines()));
  await endOk(1);
  reset(); await send({ type: 'setup', op: 'undo', id: 'remote-control' });
  check('Undo (Remote Control, row on): `shipm init --undo remote-control` is sent with Enter', lines().length === 1 && lines()[0][1] === true && lines()[0][0] === C.joinCmds([[SHIPM, 'init', '--undo', 'remote-control']]), JSON.stringify(lines()));
  await endOk(1);
  reset(); await send({ type: 'setup', op: 'prefs', id: '', prefs: { lang: 'en', folder: '~/Developer', autonomy: 'normal', awake: 'yes', notify: 'vscode' } });
  check('Quick setup Run in terminal: `shipm init --prefs ...` is sent with Enter, the notice says it is running', lines().length === 1 && lines()[0][1] === true && lines()[0][0] === C.joinCmds([[SHIPM, 'init', '--prefs', '--lang', 'en', '--folder', '~/Developer', '--autonomy', 'normal', '--awake', 'yes', '--notify', 'vscode']]) && notice() === 'Running: this change is applied at once (undo: shipm init --undo prefs).', JSON.stringify([lines(), notice()]));
  await endOk(1);

  // ---- honest wording per row type (the CLI prompts only for --step of vscode, github, projects, guard, remote-control, ask-inbox, prefs: tests/setup_prompts_test.py pins that list)
  reset(); await send({ type: 'setup', op: 'fix', id: 'github' });
  check('Fix on a row whose step PROMPTS (github): "Running: answer its prompt in the terminal; the row updates by itself."', notice() === 'Running: answer its prompt in the terminal; the row updates by itself.', notice()); await endOk(1);
  STATE['remote-control'] = 'advisory'; await send({ type: 'setup', op: 'recheck' }); reset(); await send({ type: 'setup', op: 'fix', id: 'remote-control' });
  check('Fix on Remote Control (prompts for a typed yes): the same "answer its prompt" wording', notice() === 'Running: answer its prompt in the terminal; the row updates by itself.', notice()); await endOk(1);
  STATE['remote-control'] = 'green'; await send({ type: 'setup', op: 'recheck' });
  reset(); await send({ type: 'setup', op: 'skip', id: 'github' });
  check('Skip (no prompt): "applied at once" and the way back is `shipm init --step github`', notice() === 'Running: this change is applied at once (undo: shipm init --step github).', notice()); await endOk(1);
  reset(); await send({ type: 'setup', op: 'undo', id: 'remote-control' });
  check('Undo (no prompt): "applied at once", the way back is `shipm init --step remote-control`', notice() === 'Running: this change is applied at once (undo: shipm init --step remote-control).', notice()); await endOk(1);
  {
    const S = require(path.join(EXT, 'strings.js'));
    check('no Setup text promises a prompt or a save that does not exist: Quick setup no longer says "Nothing is saved until you press Enter"; the folder refusal does not say "Not typed"', !/press Enter/i.test(S.quick.intro) && /at once/.test(S.quick.intro) && S.quick.badFolder.startsWith('Not run:') && !/Not typed/.test(S.quick.badFolder) && !/answer its prompt/i.test(S.setup.skipTip + S.setup.undoTip + S.quick.intro), JSON.stringify([S.quick.intro, S.quick.badFolder]));
  }

  // ---- a command is still running in the setup terminal: refuse, never type into it
  reset(); await send({ type: 'setup', op: 'fix', id: 'docker' }); const armed = lines().length;
  clearNotice(); await send({ type: 'setup', op: 'fix', id: 'github' });
  check('the wait for the first command is still armed: a second click is REFUSED ("A command is still running ... finish it first"), nothing is sent', lines().length === armed && notice() === STILL, JSON.stringify([lines().length, armed, notice()]));
  const exA = await startEx(), exOld = {};
  await endEx(exOld, 0);
  check('an OLD command\'s end event is not taken as the end of ours (no re-check, still waiting)', notice() === STILL && hdr() === 1);
  await endEx(exA, 1);
  check('our command\'s own end event is taken ("Not done: see the terminal" on exit 1)', notice() === 'Not done: see the terminal.', notice());
  reset(); const exX = await startEx();                                             // the owner runs something else in the setup terminal; shell integration says it is running
  await send({ type: 'setup', op: 'fix', id: 'docker' });
  check('shell integration reports a running command in the setup terminal (not ours): the click is refused, nothing is sent', lines().length === 0 && notice() === STILL, JSON.stringify([lines(), notice()]));
  await endEx(exX, 0); reset(); await send({ type: 'setup', op: 'fix', id: 'docker' });
  check('after that command ends the click works again', lines().length === 1 && lines()[0][1] === true); await endOk(1);

  // ---- every other owner route stays typed-only
  reset(); const nTerms = made.length; await send({ type: 'tidy-open' });
  const tidy = made.find(x => x.name === 'Shipmiracle · tidy');
  check('Tidy (another owner route) is still typed only: the line is sent WITHOUT Enter', made.length === nTerms + 1 && tidy && tidy.sent.some(x => x[0] === C.joinCmds([[SHIPM, 'tidy', '--all']]) && x[1] === false) && tidy.sent.every(x => x[1] === false), JSON.stringify(tidy && tidy.sent));
  const src = fs.readFileSync(path.join(EXT, 'extension.js'), 'utf8');
  const runs = [...src.matchAll(/\brun: (true|false)\b/g)].map(m => m[1]);
  check('source: exactly ONE option object asks for run:true (the Setup helper); every other ownerTerminal route says run:false', runs.filter(x => x === 'true').length === 1 && runs.filter(x => x === 'false').length >= 12, runs.join());
  check('source: ownerTerminal honours run:true only for kind "init" (any other kind is typed only, whatever the caller passes)', /o\.run === true && o\.kind === 'init'/.test(src));
  const calls = [...src.matchAll(/ownerTerminal\(([^\n]*)/g)].map(m => m[1]).filter(l => /kind: 'init'/.test(l));
  check('source: exactly one ownerTerminal call has kind "init" and it is the Setup helper with run:true (no second route can run a command)', calls.length === 1 && /run: true/.test(calls[0]), calls.join(' | '));

  // ---- refused input: no terminal opens, nothing is sent
  reset(); const before = made.reduce((n, t) => n + t.sent.length, 0), nb = made.length;
  for (const m of [{ op: 'skip', id: 'git-id' }, { op: 'skip', id: 'engine' }, { op: 'fix', id: 'engine' }, { op: 'fix', id: 'nope' }, { op: 'fix', id: "git-id; rm -rf ~ #" }, { op: 'fix', id: '$(touch /tmp/pwn-shipmiracle-sr)' }, { op: 'fix', id: "x'y" }, { op: 'fix', id: 42 }, { op: 'fix', id: { a: 1 } }, { op: 'fix', id: '' }, { op: 'skip', id: '../x' },
    { op: 'rm -rf', id: 'git-id' }, { op: 'run', id: 'git-id' }, { op: 'prefs', id: '' }, { op: 'prefs', id: '', prefs: 'x' },
    ...[{ lang: 'fr' }, { autonomy: 'full' }, { notify: 'sms' }, { awake: 'maybe' }, { folder: 'relative/path' }, { folder: '~/../etc' }, { folder: '-rf' }, { folder: '~/x\ny' }, { folder: '~/' + 'a'.repeat(300) }, { lang: ['en'] }].map(b => ({ op: 'prefs', id: '', prefs: { lang: 'en', folder: '~/Developer', autonomy: 'normal', notify: 'vscode', ...b } }))]) {
    await handler({ type: 'setup', ...m });
  }
  await wait(150);
  check('invalid ids, ops and prefs values are refused before any terminal opens: no new terminal, nothing sent, nothing ran', made.length === nb && made.reduce((n, t) => n + t.sent.length, 0) === before && !fs.existsSync('/tmp/pwn-shipmiracle-sr'));
  check('...and no wait is armed by a refusal: a stray end-of-execution event changes nothing (no re-check, no notice)', await (async () => { clearNotice(); const c = checks(); await endOk(0); return checks() === c && notice() === ''; })());
  STATE['remote-control'] = 'skipped'; await send({ type: 'setup', op: 'recheck' }); reset();
  await send({ type: 'setup', op: 'undo', id: 'remote-control' });
  check('Undo when Remote Control is not on: refused, nothing sent', lines().length === 0);
  STATE['remote-control'] = 'green'; await send({ type: 'setup', op: 'recheck' });

  // ---- after the command ends: the row turns green by itself
  reset(); STATE['git-id'] = 'red'; await send({ type: 'setup', op: 'recheck' });
  await send({ type: 'setup', op: 'fix', id: 'git-id' });
  check('before the command ends the row is still red ("1 to fix")', hdr() === 1, JSON.stringify(hdr()));
  const c1 = checks(); STATE['git-id'] = 'green';                               // what the CLI did inside the terminal
  await endOk(0);
  check('exit 0: the extension forces a fresh `shipm init --check` by itself and the Setup header goes "1 to fix" -> "Setup complete"', checks() === c1 + 1 && hdr() === 0, JSON.stringify([checks() - c1, hdr()]));
  check('exit 0: the notice becomes "Done", not the stale "Running" text', /^Done/.test(notice()), notice());

  reset(); STATE['git-id'] = 'red'; await send({ type: 'setup', op: 'recheck' });
  await send({ type: 'setup', op: 'fix', id: 'git-id' }); const c2 = checks();
  await endOk(1);
  check('non-zero exit: "Not done: see the terminal", the row stays red ("1 to fix"), no re-check is run', notice() === 'Not done: see the terminal.' && hdr() === 1 && checks() === c2, JSON.stringify([notice(), hdr(), checks() - c2]));
  await endOk(undefined);
  check('after a failure the wait is over: a later end event does nothing', checks() === c2 && notice() === 'Not done: see the terminal.');

  reset(); await send({ type: 'setup', op: 'skip', id: 'docker' }); const c3 = checks();
  term().exitStatus = { code: undefined }; for (const f of closeH) f(term()); await wait(250);
  check('the terminal is closed before the command ends: "Not done: see the terminal", row stays red, no re-check', notice() === 'Not done: see the terminal.' && checks() === c3, notice());
  made.length = 0;                                                                // the closed terminal is gone; the next click opens a new one

  // ---- with shell integration there is no poll: only the end event of our own command counts
  SI = true; reset(); STATE['git-id'] = 'red'; await send({ type: 'setup', op: 'recheck' });
  await send({ type: 'setup', op: 'fix', id: 'git-id' }); STATE['git-id'] = 'green'; const c8 = checks(); await wait(900);
  check('the terminal has shell integration: the poll timer is NOT started (no check runs while the command runs)', checks() === c8 && hdr() === 1, String(checks() - c8));
  await endOk(0);
  check('...and its own end event (exit 0) then forces the re-check: "Setup complete"', checks() === c8 + 1 && hdr() === 0, JSON.stringify([checks() - c8, hdr()]));
  SI = false; made.length = 0;

  // ---- no shell integration: the poll finds the change by itself
  reset(); STATE['git-id'] = 'red'; await send({ type: 'setup', op: 'recheck' });
  await send({ type: 'setup', op: 'fix', id: 'git-id' }); STATE['git-id'] = 'green'; const c4 = checks();
  await wait(1300);
  check('no end-of-execution event (no shell integration): the poll re-checks by itself and the header goes to "Setup complete"; the poll then stops', hdr() === 0 && /^Done/.test(notice()) && checks() > c4, JSON.stringify([hdr(), notice(), checks() - c4]));
  const c5 = checks(); await wait(700);
  check('the poll stopped after the change showed (no more checks)', checks() === c5, String(checks() - c5));

  // ---- the poll gives up after the limit
  reset(); STATE['github'] = 'red'; await send({ type: 'setup', op: 'recheck' });
  await send({ type: 'setup', op: 'skip', id: 'github' }); await wait(3100);
  check('after the time limit with no change the wait ends with "Not done: see the terminal" (row stays red)', notice() === 'Not done: see the terminal.', notice());
  const c6 = checks(); await wait(500);
  check('...and the poll timer is stopped', checks() === c6);

  // ---- Re-check all: forced, clears the cache, shows the new count
  reset(); STATE['git-id'] = 'red'; await send({ type: 'setup', op: 'recheck' }); const c7 = checks(); STATE['git-id'] = 'green'; await send({ type: 'setup', op: 'recheck' });
  check('Re-check all: runs a forced `shipm init --check` even though init.json did not change (cache cleared) and the count goes "1 to fix" -> "Setup complete"', checks() === c7 + 1 && hdr() === 0, JSON.stringify([checks() - c7, hdr()]));
  check('Re-check all: the page-side button carries the busy label (Checking...) until the redraw', /data-setup="recheck" data-busy="[^"]+"/.test(page));

  // ---- checker: Re-check all (force) clears the cache
  {
    const calls = []; let n = 0; const sdir = path.join(tmp, 'ck'); fs.mkdirSync(sdir, { recursive: true });
    const runner = (f, a, o, cb) => { const i = ++n; calls.push(i); setTimeout(() => cb(null, JSON.stringify({ v: 1, ready: true, rows: [{ n: 0, id: 'engine', title: 'run ' + i, need: 'required', state: 'green', detail: '', connect: { kind: 'hint', text: '' } }] }), ''), 80); };
    const ck = SU.makeChecker({ shipm: '/x', stateDir: sdir, runner, env: {} });
    const va = await ck.get(false), vb = await ck.get(false), vc = await ck.get(true);
    check('checker: a plain get is served from the cache (1 run), a forced get bypasses it (2nd run, fresh answer)', calls.length === 2 && va === vb && vc !== va && vc.rows[0].title === 'run 2', JSON.stringify([calls, va.rows[0].title, vc.rows[0].title]));
  }
  console.log(fails ? `\nFAILED: ${fails}` : '\nALL PASS'); fs.rmSync(tmp, { recursive: true, force: true }); process.exit(fails ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
