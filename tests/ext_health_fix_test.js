// The Health "Fix" chain runner against a stand-in for VS Code and a scripted bin/shipm-watch (contract / can / act / verify as JSON).
// Run: node tests/ext_health_fix_test.js
require('./shipmiracle_isolation').apply();   // test isolation: fresh HOME/SHIPMIRACLE_HOME/CONFIG/STATE unless already temp
const realCp = require('child_process');
const Module = require('module'), path = require('path'), os = require('os'), fs = require('fs');
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'shipmiracle-fix-'));
const ST = path.join(tmp, 'state'), DEVD = path.join(tmp, 'Developer'); fs.mkdirSync(ST); fs.mkdirSync(DEVD);
const IDE = path.join(tmp, 'ide'); fs.mkdirSync(IDE); fs.writeFileSync(path.join(IDE, '28820.lock'), JSON.stringify({ pid: process.pid }));
Object.assign(process.env, { SHIPMIRACLE_TEST: '1', SHIPMIRACLE_EXT_STATE: ST, SHIPMIRACLE_EXT_DEV: DEVD, SHIPMIRACLE_EXT_WS: path.join(tmp, 'ws'), SHIPMIRACLE_IDE_DIR: IDE, SHIPMIRACLE_DIAG_DIR: path.join(tmp, 'diag'), SHIPMIRACLE_HEAL_MS: '99999999', SHIPMIRACLE_FIX_WAIT_SCALE: '0' });
let terms = [], nextPid = 9000; const created = [], shown = [], cmds = {}, envs = {}, watchCalls = []; let projects = [];
const mkTerm = (name, pid, cmd) => { const t = { name, exitStatus: undefined, disposed: false, sent: [], processId: Promise.resolve(pid), show() {}, sendText(x) { this.sent.push(x); }, dispose() { this.disposed = true; this.exitStatus = { code: 0 }; } }; cmds[pid] = cmd; envs[pid] = 'CLAUDE_CODE_SSE_PORT=28820'; terms.push(t); return t; };
const CLAUDE = n => `/Users/x/.local/bin/claude --continue --name ${n} --remote-control ${n}`;
const proxy = () => new Proxy(function () {}, { get: (t, k) => k === 'then' ? undefined : (k === 'dispose' ? () => {} : proxy()), apply: () => proxy() });
let handler, provider;
const vscode = new Proxy({}, { get: (t, k) => {
  if (k === 'window') return new Proxy({}, { get: (w, kk) => {
    if (kk === 'terminals') return terms;
    if (kk === 'activeTerminal') return undefined;
    if (kk === 'createTerminal') return o => { const t = mkTerm(o.name, ++nextPid, CLAUDE(o.shellArgs[2])); t.opts = o; created.push(t); return t; };
    if (kk === 'registerWebviewViewProvider') return (id, prov) => { provider = prov; return { dispose() {} }; };
    if (kk === 'showInformationMessage' || kk === 'showErrorMessage' || kk === 'showWarningMessage') return async m => { shown.push(m); };
    return proxy(); } });
  if (k === 'commands') return { registerCommand: () => ({ dispose() {} }), executeCommand: async () => {} };
  if (k === 'ThemeIcon' || k === 'ThemeColor') return function (n) { this.n = n; };
  if (k === 'ViewColumn') return { Active: 1 };
  if (k === 'StatusBarAlignment') return { Left: 1 };
  return proxy(); } });
// ---- the scripted watcher
const OPS = { interrupt: { executor: 'ext', wait_s: 8, checks: 1 }, relaunch: { executor: 'ext', wait_s: 20, checks: 3 }, fresh: { executor: 'ext', wait_s: 20, checks: 3 }, 'end-proc': { executor: 'watch', wait_s: 2, checks: 1 }, 'stop-colima': { executor: 'watch', wait_s: 5, checks: 2 } };
let S = {};
const reset = () => { S = { can: {}, verify: [], verifyDefault: { gone: false, checked: true, detail: 'still raised', chat_state: 'frozen', working: true }, act: {}, checkpoint: 'wip/frozen-2026-10-19-2300', hold: null }; watchCalls.length = 0; shown.length = 0; created.length = 0; };
const fakeExec = (cmd, args, opts, cb) => {
  const done = cb || opts;
  if (cmd === '/bin/ps' && args[0] === '-o') return done(null, (cmds[args[args.length - 1]] || '') + '\n', '');
  if (cmd === '/bin/ps' && args[0] === 'eww') return done(null, 'PID TTY\n' + (cmds[args[2]] || '') + ' ' + (envs[args[2]] || '') + '\n', '');
  if (cmd === 'lsof') return done(null, 'p1\nn/\n', '');
  if (/shipm-watch$/.test(String(args[0]))) {
    const w = args.slice(1); watchCalls.push(w.join(' '));
    const out = o => done(null, typeof o === 'string' ? o : JSON.stringify(o), '');
    if (w[0] === 'contract') return out({ kinds: {}, ops: global.__contractOps || OPS });
    if (w[0] === 'can') { const it = ((JSON.parse(fs.readFileSync(path.join(ST, 'health.json'), 'utf8')).items) || [])[0] || {}; return out({ ok: true, why: '', project: S.project || it.project, kind: S.kind || it.kind, working: S.working !== false, ...(S.can[w[1]] || {}) }); }
    if (w[0] === 'act' && w[1] === 'checkpoint') return out(S.checkpoint);
    if (w[0] === 'act') return out(S.act[w[1]] || { ok: true, did: 'ended pid 1', why: '' });
    if (w[0] === 'verify') { const go = () => out(S.verify.length ? S.verify.shift() : S.verifyDefault); return S.hold ? S.hold.then(go) : go(); }
    return out('ok');
  }
  done(null, 'ok', ''); };
const real = Module._load;
Module._load = function (req, parent, ...r) {
  if (req === 'vscode') return vscode;
  if (req === 'child_process') return { execFile: fakeExec };
  if (req === './data') return { collect: async () => ({ projects, plan: {}, guard: {}, ask: null }) };
  return real.call(this, req, parent, ...r); };
const ext = require(path.join(__dirname, '../vscode-ext/shipmiracle-panel/extension.js'));
let fails = 0; const check = (n, c, info = '') => { console.log((c ? 'PASS ' : 'FAIL ') + n + (c ? '' : ' ' + info)); if (!c) fails++; };
const sleep = ms => new Promise(r => setTimeout(r, ms));
const P = name => ({ name, dir: path.join(DEVD, name), stack: 'web', state: 'working', agents: [], tokens: {}, ideas: { open: [], evaluated: [], done: 0, dropped: 0 }, held: false });
const note = () => { try { return JSON.parse(fs.readFileSync(path.join(ST, 'health-notice.json'), 'utf8')); } catch (e) { return null; } };
const setItem = (o = {}) => fs.writeFileSync(path.join(ST, 'health.json'), JSON.stringify({ ts: 1, items: [{ id: 'it1', project: 'alpha', kind: 'frozen_chat', title: 'alpha chat is frozen', chain: ['interrupt', 'relaunch'], actions: ['interrupt', 'relaunch', 'fresh'], next: 'Open the chat and look at what it waits for', ...o }] }));
const fix = async (op = 'fix', id = 'it1') => { await handler({ type: 'health', op, id }); await sleep(60); };
const calls = prefix => watchCalls.filter(c => c.startsWith(prefix));
(async () => {
  ext.activate({ subscriptions: [], globalState: { get() {}, update() {} } });
  const view = { webview: { options: {}, set html(v) {}, get html() { return ''; }, onDidReceiveMessage: f => { handler = f; return { dispose() {} }; } }, visible: true, onDidChangeVisibility: () => ({ dispose() {} }), onDidDispose: () => ({ dispose() {} }) };
  provider.resolveWebviewView(view); await sleep(300);
  const withChat = (name = 'alpha') => { terms = []; projects = [P(name)]; const t = mkTerm(name + ' · Claude', 101, CLAUDE(name)); return t; };

  // 1 step 1 fixes: step 2 never runs
  reset(); setItem(); let t = withChat();
  S.verify = [{ gone: true, detail: '', interrupted_at: 0, working: false }];
  await fix();
  check('step 1 fixes it: Esc sent once, notice "Fixed: …", step 2 never asked or run', t.sent.length === 1 && t.sent[0] === '\u001b' && /^Fixed: alpha chat is frozen\. Ran: Interrupt: /.test(note().text) && calls('can relaunch').length === 0 && calls('act checkpoint').length === 0 && created.length === 0 && !t.disposed, JSON.stringify([note(), watchCalls]));
  check('the notice file carries id, busy:false and the steps', note().id === 'it1' && note().busy === false && Array.isArray(note().steps) && note().steps.length === 1, JSON.stringify(note()));

  // 2 step 1 fails -> step 2 (relaunch, checkpoint first) fixes
  reset(); setItem(); t = withChat();
  S.verify = [{ gone: false, chat_state: 'frozen', working: true, interrupted_at: 0, detail: 'no change' }, { gone: true, detail: '' }];
  await fix();
  const nt = note().text;
  check('Esc with no visible effect is reported, then step 2 runs: checkpoint, old chat closed, new chat opened, "Fixed:"', t.disposed && created.length === 1 && /Esc had no visible effect \(a tool call may be hung\)/.test(nt) && /Relaunch: done \(work saved to wip\/frozen-/.test(nt) && /^Fixed:/.test(nt), nt);
  check('checkpoint ran before anything was closed (order of calls)', watchCalls.indexOf('act checkpoint alpha') > watchCalls.indexOf('can relaunch it1') && watchCalls.indexOf('act checkpoint alpha') > -1, JSON.stringify(watchCalls));
  check('interrupt verify used --since with a timestamp', calls('verify it1 --since ').length === 1 && /--since \d{10}$/.test(calls('verify it1 --since ')[0]), JSON.stringify(watchCalls));

  // 3 interrupt took effect (idle now) but item still raised -> relaunch also not gone, `checks` attempts -> chain used up
  reset(); setItem(); t = withChat();
  S.verify = [{ gone: false, working: false, interrupted_at: 9999999999, detail: 'idle' }];
  S.verifyDefault = { gone: false, detail: 'chat still marked frozen', chat_state: 'frozen', working: true };
  await fix();
  check('"Interrupted: the chat is idle now" when the watcher saw the marker', /Interrupt: Interrupted: the chat is idle now/.test(note().text), note().text);
  check('chain used up: "Not fixed: … Ran: … Now: … Next: …"', /^Not fixed: alpha chat is frozen\. Ran: .*Relaunch: done.*Now: chat still marked frozen\. Next: Open the chat and look at what it waits for\.$/.test(note().text), note().text);
  check('relaunch is verified `checks` (3) times', calls('verify it1').length >= 1 + 3, String(calls('verify it1').length));

  // 4 interrupt with no terminal
  reset(); setItem({ chain: ['interrupt'], actions: ['interrupt'] }); terms = []; projects = [P('alpha')];
  await fix();
  check('interrupt with no terminal: explicit "skipped - no alpha chat in this VS Code window" (never silent)', /Interrupt: skipped - no alpha chat in this VS Code window/.test(note().text) && /^Not fixed:/.test(note().text) && calls('act').length === 0, note() && note().text);

  // 5 interrupt on an idle chat
  reset(); setItem({ chain: ['interrupt'], actions: ['interrupt'] }); t = withChat();
  S.working = false;
  await fix();
  check('interrupt on an idle chat: "The chat was already idle", no Esc sent', t.sent.length === 0 && /Interrupt: The chat was already idle/.test(note().text), note().text);

  // 6 can refuses
  reset(); setItem(); t = withChat(); S.can = { interrupt: { ok: false, why: 'the chat is not mid-turn' }, relaunch: { ok: false, why: 'a build is running' } };
  await fix();
  check('can refuses: both reasons shown, nothing performed (no Esc, no checkpoint, nothing closed or opened)', /Interrupt: skipped - the chat is not mid-turn/.test(note().text) && /Relaunch: skipped - a build is running/.test(note().text) && t.sent.length === 0 && !t.disposed && created.length === 0 && calls('act').length === 0, note().text);

  // 7 checkpoint failure
  reset(); setItem({ chain: ['relaunch'], actions: ['relaunch', 'fresh'] }); t = withChat(); S.checkpoint = 'no such project';
  await fix();
  check('checkpoint failure: nothing closed, nothing opened, "could not save your work first; nothing closed"', !t.disposed && created.length === 0 && /could not save your work first; nothing closed/.test(note().text) && /^Not fixed:/.test(note().text), note().text);
  reset(); setItem({ chain: ['relaunch'], actions: ['relaunch'] }); t = withChat(); S.checkpoint = JSON.stringify({ ok: false, did: '', why: 'git failed' });
  await fix();
  check('checkpoint reported as JSON ok:false is a failure too', !t.disposed && created.length === 0, note().text);
  reset(); setItem({ chain: ['fresh'], actions: ['fresh'] }); t = withChat(); S.checkpoint = 'nothing to save'; S.verifyDefault = { gone: true, detail: '' };
  await fix();
  check('"nothing to save" is a good checkpoint: fresh chat opened with the one-shot marker', created.length === 1 && t.disposed && fs.readdirSync(ST).some(f => /^chat-fresh\.alpha\./.test(f)) && /^Fixed:/.test(note().text), note().text);

  // 8 second press refused
  reset(); setItem(); t = withChat(); let release; S.hold = new Promise(r => { release = r; }); S.verify = [{ gone: true }];
  const first = handler({ type: 'health', op: 'fix', id: 'it1' }); await sleep(100);
  const mid = note();
  await handler({ type: 'health', op: 'fix', id: 'it1' }); await sleep(30);
  check('while a fix runs the notice is busy:true with the item id', mid && mid.busy === true && mid.id === 'it1', JSON.stringify(mid));
  check('a second press is refused ("A fix is already running for …"), the Esc is sent once', shown.some(m => /A fix is already running for alpha chat is frozen/.test(m)) && t.sent.length <= 1, JSON.stringify(shown));
  release(); S.hold = null; await first; await sleep(80);
  check('after the first finishes a new fix is accepted', note().busy === false);

  // 9 watch executor op, secondary button
  reset(); setItem({ chain: ['end-proc'], actions: ['end-proc', 'fresh'], kind: 'playwright_dup', title: 'Playwright twice' }); terms = []; projects = [P('alpha')];
  S.verifyDefault = { gone: true, detail: '' };
  await fix('end-proc');
  check('watch op: can -> act -> verify, no terminal needed', JSON.stringify(watchCalls.filter(c => !/^contract/.test(c))) === JSON.stringify(['can end-proc it1', 'act end-proc it1', 'verify it1']) && /^Fixed: Playwright twice\. Ran: End process: ended pid 1/.test(note().text), JSON.stringify(watchCalls) + note().text);
  reset(); setItem({ chain: ['end-proc'], actions: ['end-proc'] }); S.act['end-proc'] = { ok: false, did: '', why: 'pid is not ours any more' };
  await fix();
  check('watch op refused by act: reason shown, no verify loop', /End process: failed - pid is not ours any more/.test(note().text) && /^Not fixed:/.test(note().text), note().text);
  reset(); setItem({ chain: ['fresh'], actions: ['fresh'] }); t = withChat(); await fix('relaunch');
  check('a secondary op the item does not offer is refused', calls('act').length === 0 && !t.disposed && shown.some(m => /not available/.test(m)), JSON.stringify(shown));

  // 10 item gone
  reset(); fs.writeFileSync(path.join(ST, 'health.json'), JSON.stringify({ items: [] }));
  await fix();
  check('item already gone: "Already fixed: …" and nothing run', /^Already fixed: .* is gone\.$/.test(note().text) && calls('can').length === 0);

  // 11 whitelist
  reset(); setItem(); t = withChat();
  for (const bad of ['report', 'rm -rf', 'checkpoint', '', 'stop-everything']) await fix(bad);
  check('unknown ops are rejected: nothing run, nothing sent', calls('act').length === 0 && calls('can').length === 0 && t.sent.length === 0);
  reset(); await handler({ type: 'health', op: 'fix', id: '../../x; rm' }); await sleep(30);
  check('a malformed id is rejected', watchCalls.length === 0);
  global.__contractOps = { interrupt: OPS.interrupt, 'bogus-ext': { executor: 'ext', wait_s: 1, checks: 1 } };
  reset(); setItem({ chain: ['bogus-ext'], actions: ['bogus-ext'] }); t = withChat(); await fix('bogus-ext');
  check('an ext op the extension does not implement (not in EXT_OPS) is never run even if the contract lists it', calls('can').length === 0 && t.sent.length === 0, JSON.stringify(watchCalls));
  global.__contractOps = null;
  const contractExt = Object.entries(OPS).filter(([, v]) => v.executor === 'ext').map(([k]) => k);
  check('every executor:"ext" op in the (fake) contract is in EXT_OPS, and EXT_OPS has nothing else', contractExt.every(o => ext.EXT_OPS.includes(o)) && ext.EXT_OPS.every(o => contractExt.includes(o)), JSON.stringify(ext.EXT_OPS));
  const realContract = (() => { try { return JSON.parse(realCp.execFileSync('/usr/bin/python3', [path.join(__dirname, '../bin/shipm-watch'), 'contract'], { timeout: 20000 }).toString()); } catch (e) { return null; } })();
  if (realContract && realContract.ops) check('the REAL `shipm-watch contract`: every executor:"ext" op is in EXT_OPS', Object.entries(realContract.ops).filter(([, v]) => v.executor === 'ext').every(([k]) => ext.EXT_OPS.includes(k)), JSON.stringify(Object.keys(realContract.ops)));
  else console.log('NOTE the real `shipm-watch contract` is not available yet: that check was skipped');

  // security: identity comes from the watcher's fresh scan
  reset(); setItem(); t = withChat(); S.project = 'beta';
  await fix();
  check('can answers another project than the item says: "Not done: the item changed; refresh.", no Esc, nothing opened', note().text === 'Not done: the item changed; refresh.' && t.sent.length === 0 && created.length === 0 && calls('act').length === 0, note().text);
  reset(); setItem(); t = withChat(); S.kind = 'idle_session';
  await fix(); check('can answers another kind than the item says: refused the same way', note().text === 'Not done: the item changed; refresh.' && t.sent.length === 0);
  reset(); setItem({ project: '../../etc' }); terms = []; projects = [P('alpha')]; S.project = '../../etc';
  await fix(); check('a planted project name is never used for a terminal or a marker', created.length === 0 && !fs.readdirSync(ST).some(f => /^chat-fresh\.\.\./.test(f)) && /skipped - no/.test(note().text));
  // verify could not take the lock
  reset(); setItem({ chain: ['end-proc'], actions: ['end-proc'] }); S.verifyDefault = { gone: false, checked: false, detail: 'could not check: a scan is running' };
  await fix();
  check('verify checked:false -> "Could not check yet (a scan is running); the fix may still have worked: refresh in a minute", not "Not fixed"', /^Could not check yet \(a scan is running\); the fix may still have worked: refresh in a minute\./.test(note().text) && !/^Not fixed/.test(note().text), note().text);
  // text from processes is capped and stripped
  reset(); setItem({ chain: ['end-proc'], actions: ['end-proc'], title: 'T\u001b[31m' + 'x'.repeat(500) }); S.act['end-proc'] = { ok: false, why: 'bad\u0007\nline\u001b]0;pwn\u0007 ' + 'y'.repeat(600) };
  await fix();
  check('notice text from the watcher/health.json has no control characters and is capped', !/[\u0000-\u001f\u007f]/.test(note().text) && note().text.length < 1200 && note().steps.every(x => x.length < 300), String(note().text.length));
  // only the proven chat is closed
  reset(); setItem({ chain: ['relaunch'], actions: ['relaunch'] }); t = withChat(); const other = mkTerm('alpha · Claude', 102, CLAUDE('alpha')); S.verifyDefault = { gone: true };
  await fix();
  check('relaunch closes only the terminal inspectChat proved (a second chat tab of the project is left alone)', t.disposed && !other.disposed, JSON.stringify([t.disposed, other.disposed]));
  // production code: no SHIPMIRACLE_* test knob is read unless SHIPMIRACLE_TEST=1
  const src = ['extension.js', 'data.js', 'locations.js'].map(f => fs.readFileSync(path.join(__dirname, '../vscode-ext/shipmiracle-panel', f), 'utf8')).join('\n');
  check('no SHIPMIRACLE_* override is read directly in production code (only through testEnv, behind SHIPMIRACLE_TEST=1)', !/process\.env\.SHIPMIRACLE_(?!TEST\b|QUIET\b)/.test(src) && /testEnv\('SHIPMIRACLE_EXT_WS'\)/.test(src), (src.match(/process\.env\.SHIPMIRACLE_\w+/g) || []).join());
  check('the removed "report" op is gone from production code', !/op === 'report'|'report'/.test(fs.readFileSync(path.join(__dirname, '../vscode-ext/shipmiracle-panel/extension.js'), 'utf8')));

  // 12 dismiss + data.js passthrough
  fs.writeFileSync(path.join(ST, 'health-notice.json'), JSON.stringify({ ts: Date.now(), text: 'x', id: 'it1', busy: true, steps: ['a', 'b'] }));
  const info = JSON.parse(realCp.execFileSync('node', ['-e', "require(process.argv[1]).collect().then(d=>console.log(JSON.stringify([d.health.notice,d.health.noticeInfo])))", path.join(__dirname, '../vscode-ext/shipmiracle-panel/data.js')], { env: { ...process.env }, timeout: 30000 }).toString().trim().split('\n').pop());
  fs.writeFileSync(path.join(ST, 'health.json'), JSON.stringify({ ts: Math.floor(Date.now() / 1000), items: [] }));
  const info2 = JSON.parse(realCp.execFileSync('node', ['-e', "require(process.argv[1]).collect().then(d=>console.log(JSON.stringify([d.health.notice,d.health.noticeInfo])))", path.join(__dirname, '../vscode-ext/shipmiracle-panel/data.js')], { env: { ...process.env }, timeout: 30000 }).toString().trim().split('\n').pop());
  check('data.js: health.notice stays a string and health.noticeInfo = {busy,id,steps}', info2[0] === 'x' && info2[1].busy === true && info2[1].id === 'it1' && info2[1].steps.join() === 'a,b', JSON.stringify(info2));
  await handler({ type: 'health', op: 'dismiss-notice', id: '' }); await sleep(50);
  check('dismiss-notice still deletes the notice', note() === null);
  fs.rmSync(tmp, { recursive: true, force: true });
  console.log(fails ? '\nFAILED: ' + fails : '\nALL PASS'); process.exit(fails ? 1 : 0);
})().catch(e => { console.error('test crashed:', e); process.exit(2); });
