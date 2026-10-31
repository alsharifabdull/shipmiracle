// "Handoff + fresh chat" (extension.js) against a stand-in for VS Code, fake chat terminals and a temp state/project folder.
// What is asserted: the action sequence (ask -> STATUS newer -> checkpoint -> fresh chat beside the old one), what is refused
// (working project, unknown project, bad message, STATUS not newer), and that the old chat terminal is never closed or typed into twice.
// Run: node tests/ext_handoff_test.js
require('./shipmiracle_isolation').apply();   // test isolation: fresh HOME/SHIPMIRACLE_HOME/CONFIG/STATE unless already temp
const Module = require('module'); const path = require('path'); const fs = require('fs'); const os = require('os');
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'shipmiracle-ho-'));
const ST = path.join(tmp, 'state'), WSD = path.join(tmp, 'ws'), DEV = path.join(tmp, 'Dev');
for (const d of [ST, WSD, DEV]) fs.mkdirSync(d, { recursive: true });
fs.mkdirSync(path.join(tmp, 'ide')); fs.writeFileSync(path.join(tmp, 'ide', '1234.lock'), JSON.stringify({ pid: process.pid }));   // the fake chats' IDE port is alive: the panel's own chat health leaves them alone
Object.assign(process.env, { SHIPMIRACLE_IDE_DIR: path.join(tmp, 'ide'), SHIPMIRACLE_TEST: '1', SHIPMIRACLE_EXT_STATE: ST, SHIPMIRACLE_EXT_WS: WSD, SHIPMIRACLE_EXT_DEV: DEV, SHIPMIRACLE_DIAG_DIR: path.join(tmp, 'diag'), SHIPMIRACLE_HEAL_MS: '99999999', SHIPMIRACLE_FIX_WAIT_SCALE: '0' });
const STATUS = n => path.join(DEV, n, 'docs', 'STATUS.md');
const cmds = {}; let projects = [], lastData = null, terms = [], created = [], watchCalls = [], checkpoint = { ok: true, did: 'nothing to save' }, psMap = {}, psCmd = pid => 'claude --name ' + (psMap[pid] || 'x');
const mk = (name, state = 'idle', extra = {}) => ({ name, dir: path.join(DEV, name), stack: 'web', state, agents: [], tokens: {}, ideas: { open: [], evaluated: [], done: 0, dropped: 0 }, held: false, ...extra });
const term = (name, pid) => { const t = { name, exitStatus: undefined, sent: [], disposed: 0, shown: 0, processId: Promise.resolve(pid), sendText(x, nl) { if (!/^\/rename /.test(x)) this.sent.push([x, nl]); }, dispose() { this.disposed++; }, show() { this.shown++; } }; terms.push(t); return t; };
const proxy = () => new Proxy(function () {}, { get: (t, k) => k === 'then' ? undefined : (k === 'dispose' ? () => {} : proxy()), apply: () => proxy() });
const vscode = new Proxy({}, { get: (t, k) => {
  if (k === 'window') return new Proxy({}, { get: (w, kk) => {
    if (kk === 'terminals') return terms;
    if (kk === 'registerWebviewViewProvider') return (id, prov) => { module.provider = prov; return { dispose() {} }; };
    if (kk === 'activeTerminal') return undefined;
    if (kk === 'createTerminal') return o => { const t = term(o.name, 5000 + created.length); t.opts = o; created.push(t); return t; };
    return proxy(); } });
  if (k === 'commands') return { registerCommand: (id, fn) => { cmds[id] = fn; return { dispose() {} }; }, executeCommand: async () => {} };
  if (k === 'Uri') return { parse: s => ({ s }), file: f => ({ fsPath: f }) };
  if (k === 'ThemeIcon' || k === 'ThemeColor') return function (n) { this.n = n; };
  if (k === 'ViewColumn') return { Active: 1 };
  if (k === 'StatusBarAlignment') return { Left: 1 };
  return proxy(); } });
const fakeExec = (cmd, args, opts, cb) => {
  cb = cb || opts;
  if (cmd === '/bin/ps') { if (args[0] === '-o') cb(null, psCmd(+args[args.length - 1]) + '\n', ''); else cb(null, 'PID CMD CLAUDE_CODE_SSE_PORT=1234\n', ''); return {}; }
  if (/shipm-watch$/.test(String(args[0]))) { watchCalls.push(args.slice(1)); cb(null, JSON.stringify(checkpoint), ''); return {}; }
  cb(null, '', ''); return {};
};
const real = Module._load;
Module._load = function (req, parent, ...r) {
  if (req === 'vscode') return vscode;
  if (req === 'child_process') return { execFile: fakeExec };
  if (req === './data') return { collect: async () => ({ projects, plan: {}, guard: {}, ask: null }) };
  if (req === './panel') return { html: d => { lastData = d; return '<html></html>'; } };
  return real.call(this, req, parent, ...r); };
const ext = require(path.join(__dirname, '../vscode-ext/shipmiracle-panel/extension.js'));
let fails = 0, n = 0; const check = (name, c, info = '') => { n++; console.log((c ? 'PASS ' : 'FAIL ') + name + (c ? '' : ' ' + info)); if (!c) fails++; };
const wait = ms => new Promise(r => setTimeout(r, ms));
const TEXT = require('../vscode-ext/shipmiracle-panel/strings.js').panelMarker + 'Write your handoff now: update docs/STATUS.md (what changed, verified, next, handoff) and commit, then reply HANDOFF DONE.';
const pnote = () => { try { return JSON.parse(fs.readFileSync(path.join(ST, 'project-notice.json'), 'utf8')).text; } catch (e) { return null; } };
const clearNote = () => { try { fs.unlinkSync(path.join(ST, 'project-notice.json')); } catch (e) { /* none */ } };
const freshFiles = () => fs.readdirSync(ST).filter(f => f.startsWith('chat-fresh.'));
const view = { webview: { options: {}, set html(v) {}, get html() { return ''; }, onDidReceiveMessage: f => { module.handler = f; return { dispose() {} }; } }, visible: true, onDidChangeVisibility: () => ({ dispose() {} }), onDidDispose: () => ({ dispose() {} }) };
const touch = (n, ms) => { fs.writeFileSync(STATUS(n), 'new ' + ms + '\n'); const t = new Date(ms); fs.utimesSync(STATUS(n), t, t); };
const pOf = n => (lastData.projects || []).find(p => p.name === n);
let oldA, oldB, A, B, ctr = 0, pidN = 4000;
// every scenario gets its own two projects (the extension keeps handoff state per project name for the life of the panel)
const reset0 = () => { terms.length = 0; created.length = 0; watchCalls.length = 0; clearNote(); for (const f of freshFiles()) fs.unlinkSync(path.join(ST, f)); checkpoint = { ok: true, did: 'nothing to save' };
  ctr++; A = 'pa' + ctr; B = 'pb' + ctr; for (const nm of [A, B]) { fs.mkdirSync(path.join(DEV, nm, 'docs'), { recursive: true }); fs.writeFileSync(STATUS(nm), 'old\n'); }
  const pa = ++pidN, pb = ++pidN; psMap = { [pa]: A, [pb]: B }; psCmd = pid => 'claude --name ' + (psMap[pid] || 'x');
  oldA = term(A + ' · Claude', pa); oldB = term(B + ' · Claude', pb); projects = [mk(A), mk(B)]; };
const reset = async () => { reset0(); await refreshed(); };
const setP = async list => { projects = list; await refreshed(); };
const refreshed = async () => { await cmds['shipmiracle.refresh'](); await wait(150); };
const send = async m => { module.handler(m); await wait(250); };
const noEffect = (label, extra = true) => check(label, !oldA.sent.length && !oldB.sent.length && !created.length && !watchCalls.length && !oldA.disposed && !oldB.disposed && extra, JSON.stringify({ a: oldA.sent, b: oldB.sent, created: created.length, watch: watchCalls, d: [oldA.disposed, oldB.disposed] }));
(async () => {
  ext.activate({ subscriptions: [], globalState: { get() {}, update() {} } });
  await wait(300);
  module.provider.resolveWebviewView(view); await wait(300);

  // ---- refusals
  await reset(); await setP([mk(A, 'working'), mk(B)]);
  await send({ type: 'handoff', step: 'ask', project: A });
  noEffect('ask while the project is working: nothing typed into the chat', /Wait: an agent is working/.test(pnote() || ''));
  await reset(); await setP([mk(A, 'needs-input'), mk(B)]); await send({ type: 'handoff', step: 'ask', project: A }); noEffect('ask while the chat waits for you: refused', /Wait/.test(pnote() || ''));
  await reset(); await setP([mk(A, 'idle', { agents: [{ id: 'a1', type: 'qa-engineer' }] }), mk(B)]); await send({ type: 'handoff', step: 'ask', project: A }); noEffect('ask while an agent is running: refused', /Wait/.test(pnote() || ''));
  await reset();
  for (const m of [{ type: 'handoff', step: 'ask', project: 'nope' }, { type: 'handoff', step: 'ask', project: '../' + A }, { type: 'handoff', step: 'ask', project: '__proto__' }, { type: 'handoff', step: 'ask', project: 'constructor' },
    { type: 'handoff', step: 'ask', project: [A] }, { type: 'handoff', step: 'ask', project: { toString: () => A } }, { type: 'handoff', step: 'ask', project: A.repeat(60) }, { type: 'handoff', step: 'ask' }, { type: 'handoff', project: A },
    { type: 'handoff', step: 'close', project: A }, { type: 'handoff', step: 'ASK', project: A }, { type: 'handoff', step: ['ask'], project: A }, { type: 'handoff', step: 'open', project: 'nope' }]) {
    await send(m); noEffect('refused message ' + JSON.stringify(m).slice(0, 70), pnote() === null);
  }
  await send({ type: 'handoff', step: 'ask', project: A, text: 'rm -rf ~', command: 'x' });
  check('the text typed into the chat is fixed: a text/command field in the message is ignored', oldA.sent.length === 1 && oldA.sent[0][0] === TEXT, JSON.stringify(oldA.sent));
  try { module.handler(null); module.handler(undefined); module.handler('handoff'); await wait(100); check('null / undefined / string message do not crash', true); } catch (e) { check('null / undefined / string message do not crash', false, e.message); }

  await reset(); terms.length = 0; await refreshed(); await send({ type: 'handoff', step: 'ask', project: A });
  check('ask without any open chat: nothing sent, owner told', !created.length && new RegExp('no ' + A + ' chat is open').test(pnote() || ''), pnote());
  await reset(); psCmd = () => '-zsh'; await send({ type: 'handoff', step: 'ask', project: A });
  noEffect('ask when the terminal is not a Claude chat (ps says a shell): nothing typed', /could not confirm/.test(pnote() || ''));
  await reset(); const nameB = B; psCmd = () => 'claude --name ' + nameB; await send({ type: 'handoff', step: 'ask', project: A });
  noEffect('ask when the terminal named for one project is really another project chat: nothing typed', /could not confirm/.test(pnote() || ''));
  await reset(); await send({ type: 'handoff', step: 'open', project: A });
  noEffect('open without a prior ask: refused', /Ask for the handoff first/.test(pnote() || ''));

  // ---- the sequence
  await reset(); const askedAt = Date.now();
  await send({ type: 'handoff', step: 'ask', project: A });
  check('step 1: exactly the fixed handoff text goes to the project chat, submitted, nothing else', oldA.sent.length === 1 && oldA.sent[0][0] === TEXT && oldA.sent[0][1] === true && !oldB.sent.length, JSON.stringify(oldA.sent));
  check('step 1: no fresh chat, no checkpoint yet; the old terminal is intact', !created.length && !watchCalls.length && !oldA.disposed);
  check('step 1: the card now carries handoff {asked, ready:false}', pOf(A).handoff && pOf(A).handoff.asked === true && pOf(A).handoff.ready === false && pOf(B).handoff === null, JSON.stringify(pOf(A).handoff));
  check('step 1: owner gets a notice', new RegExp('Handoff asked in the ' + A + ' chat').test(pnote() || ''));
  await send({ type: 'handoff', step: 'ask', project: A });
  check('a second click within 2 minutes does not type the text twice', oldA.sent.length === 1 && /already asked/.test(pnote() || ''));
  clearNote(); await send({ type: 'handoff', step: 'open', project: A });
  check('step 2 gating: STATUS.md not changed since the ask -> no fresh chat, no checkpoint, tooltip-style reason', !created.length && !watchCalls.length && /docs\/STATUS\.md has not changed since you asked/.test(pnote() || ''), pnote());
  const askMs = pOf(A) && Date.now();
  touch(A, askedAt - 60000); await send({ type: 'handoff', step: 'open', project: A });
  check('STATUS.md changed BEFORE the ask does not count', !created.length && !watchCalls.length && pOf(A).handoff.ready === false);
  touch(A, Date.now() + 5000); await wait(50);
  await send({ type: 'handoff', step: 'ask', project: B });  // another project asked meanwhile; independent
  check('another project has its own independent handoff state', pOf(B).handoff && pOf(B).handoff.ready === false && oldB.sent.length === 1);
  await setP([mk(A, 'working'), mk(B)]);
  clearNote(); await send({ type: 'handoff', step: 'open', project: A });
  check('step 3 refused while the project is working, even with STATUS newer', !created.length && !watchCalls.length && /Wait: an agent is working/.test(pnote() || ''));
  await setP([mk(A), mk(B)]);
  check('card shows ready:true once STATUS.md is newer than the ask', (await send({ type: 'handoff', step: 'ask', project: B }), pOf(A).handoff.ready === true), JSON.stringify(pOf(A).handoff));
  checkpoint = { ok: false, why: 'git is locked' }; clearNote();
  await send({ type: 'handoff', step: 'open', project: A });
  check('step 3: if the safety checkpoint fails nothing opens and the old chat stays', created.length === 0 && !oldA.disposed && /Handoff not saved/.test(pnote() || '') && watchCalls.length === 1, JSON.stringify([created.length, pnote()]));
  checkpoint = { ok: true, did: 'saved to wip/battery-1' }; watchCalls.length = 0; clearNote();
  await send({ type: 'handoff', step: 'open', project: A });
  check('step 3: the same checkpoint safety as the Health fresh fix runs first (act checkpoint alpha)', JSON.stringify(watchCalls) === JSON.stringify([['act', 'checkpoint', A]]), JSON.stringify(watchCalls));
  const ft = created[0];
  check('step 3: one new chat terminal in the project folder, launched through bin/shipm-chat with the project name', created.length === 1 && ft.opts.cwd === path.join(DEV, A) && ft.opts.shellPath === '/bin/bash' && ft.opts.shellArgs[0] === '-p' && /bin\/shipm-chat$/.test(ft.opts.shellArgs[1]) && ft.opts.shellArgs[2] === A && /^[0-9a-f]{16}$/.test(ft.opts.shellArgs[3]), JSON.stringify(ft && ft.opts));
  check('step 3: it is a FRESH conversation (chat-fresh marker for that nonce, 0600) and is named so it can be told apart', freshFiles().length === 1 && freshFiles()[0] === 'chat-fresh.' + A + '.' + ft.opts.shellArgs[3] && (fs.statSync(path.join(ST, freshFiles()[0])).mode & 0o777) === 0o600 && / \(fresh\)$/.test(ft.opts.name), freshFiles().join());
  check('step 3: the OLD chat terminal is never closed, hidden or typed into again', oldA.disposed === 0 && oldA.exitStatus === undefined && oldA.sent.length === 1, JSON.stringify([oldA.disposed, oldA.sent.length]));
  check('step 3: the other project is untouched', oldB.disposed === 0 && oldB.sent.length === 1 && created.every(t => t.opts.shellArgs[2] === A));
  check('step 3: success notice tells the old chat stays open; handoff state cleared', new RegExp('Handoff saved\\. Fresh chat opened for ' + A + '\\. The old chat is still open').test(pnote() || '') && pOf(A).handoff === null, pnote());
  await send({ type: 'handoff', step: 'open', project: A });
  check('a second "open" does not open another chat', created.length === 1 && /Ask for the handoff first/.test(pnote() || ''));

  // ---- STATUS.md edge cases
  await reset(); await send({ type: 'handoff', step: 'ask', project: A });
  fs.unlinkSync(STATUS(A)); fs.symlinkSync(STATUS(B), STATUS(A)); touch(B, Date.now() + 9000);
  await send({ type: 'handoff', step: 'open', project: A });
  check('a STATUS.md that is a symlink never counts as updated', !created.length && pOf(A).handoff.ready === false);
  fs.unlinkSync(STATUS(A)); fs.writeFileSync(STATUS(A), 'x'); 
  await reset(); await send({ type: 'handoff', step: 'ask', project: A }); fs.unlinkSync(STATUS(A)); await send({ type: 'handoff', step: 'open', project: A });
  check('a missing STATUS.md never counts as updated', !created.length && pOf(A).handoff.ready === false); fs.writeFileSync(STATUS(A), 'x');
  await reset(); await send({ type: 'handoff', step: 'ask', project: A }); const edge = Date.now() + 2000;
  touch(A, edge); const h0 = pOf(A).handoff; await send({ type: 'handoff', step: 'open', project: A });
  check('newer STATUS.md opens the chat (positive control)', created.length === 1, JSON.stringify(h0));
  await reset(); terms.length = 0; const t4 = term(A + ' · Claude', +Object.keys(psMap)[0]); await setP([mk(A)]); await send({ type: 'handoff', step: 'ask', project: A });
  t4.exitStatus = { code: 0 }; touch(A, Date.now() + 9000); await send({ type: 'handoff', step: 'open', project: A });
  check('"open" still works when the old chat has since exited (it only needs the project and the newer STATUS)', created.length === 1 && t4.disposed === 0);

  const src = fs.readFileSync(path.join(__dirname, '../vscode-ext/shipmiracle-panel/extension.js'), 'utf8');
  const fn = src.slice(src.indexOf('async function handoffAction'), src.indexOf('async function relaunch'));
  check('source: handoffAction never calls dispose() / shell strings, and uses sendText only with the fixed constant', !/\.dispose\(\)/.test(fn) && !/\bexec\(/.test(fn) && (fn.match(/sendText\(([^)]*)\)/g) || []).join() === 'sendText(HANDOFF_TEXT, true)', (fn.match(/sendText\([^)]*\)/g) || []).join());
  fs.rmSync(tmp, { recursive: true, force: true });
  console.log(`\n${n - fails}/${n} passed`); process.exit(fails ? 1 : 0);
})().catch(e => { console.log('FAIL crashed ' + e.stack); process.exit(1); });
