// Chat health against a stand-in for VS Code: chats are found by their process, stale ones (dead IDE port) are closed or relaunched safely.
// Run: node tests/chat_health_test.js
require('./shipmiracle_isolation').apply();   // test isolation: fresh HOME/SHIPMIRACLE_HOME/CONFIG/STATE unless already temp
const Module = require('module'), path = require('path'), os = require('os'), fs = require('fs');
const IDE = fs.mkdtempSync('/tmp/shipmiracle-ide-'); fs.writeFileSync(path.join(IDE, '28820.lock'), JSON.stringify({ pid: process.pid }));   // the live IDE connection
const ST = fs.mkdtempSync('/tmp/shipmiracle-st-'); process.env.SHIPMIRACLE_TEST = '1'; process.env.SHIPMIRACLE_EXT_STATE = ST; process.env.SHIPMIRACLE_IDE_DIR = IDE; process.env.SHIPMIRACLE_HEAL_MS = '0'; process.env.SHIPMIRACLE_FIX_WAIT_SCALE = '0';
const DEV = path.join(os.homedir(), 'Developer');
let terms = [], active, html = '', htmlSets = 0, nextPid = 9000; const shown = [], created = [], cmds = {}, envs = {}, cwds = {};
const launch = o => { const a = o.shellArgs || []; return { ok: o.shellPath === '/bin/bash' && (a.length === 4 || a.length === 5) && a[0] === '-p' && /\/bin\/shipm-chat$/.test(a[1]) && /^[0-9a-f]{16}$/.test(a[3]) && (a.length === 4 || /^[0-9a-f]{32}$/.test(a[4])), name: a[2], nonce: a[3], hash: a[4] }; };
const mkTerm = (name, pid, cmd, env, cwd) => { const t = { name, exitStatus: undefined, disposed: false, shown: 0, sent: [], processId: Promise.resolve(pid), show() { this.shown++; }, sendText(x) { this.sent.push(x); }, dispose() { this.disposed = true; this.exitStatus = { code: 0 }; } }; cmds[pid] = cmd; envs[pid] = env || ''; cwds[pid] = cwd || ''; terms.push(t); return t; };
const proxy = () => new Proxy(function () {}, { get: (t, k) => k === 'then' ? undefined : (k === 'dispose' ? () => {} : proxy()), apply: () => proxy() });
let handler, provider, visCb;
const vscode = new Proxy({}, { get: (t, k) => {
  if (k === 'window') return new Proxy({}, { get: (w, kk) => {
    if (kk === 'terminals') return terms;
    if (kk === 'activeTerminal') return active;
    if (kk === 'createTerminal') return o => { const t = mkTerm(o.name, ++nextPid, '/Users/x/.local/bin/claude --continue --model opusplan --name ' + o.shellArgs[1] + ' --remote-control ' + o.shellArgs[1], 'CLAUDE_CODE_SSE_PORT=28820', o.cwd); t.opts = o; created.push(t); return t; };
    if (kk === 'registerWebviewViewProvider') return (id, prov) => { provider = prov; return { dispose() {} }; };
    if (kk === 'showInformationMessage' || kk === 'showErrorMessage' || kk === 'showWarningMessage') return async m => { shown.push(m); };
    return proxy(); } });
  if (k === 'commands') return { registerCommand: () => ({ dispose() {} }), executeCommand: async () => {} };
  if (k === 'ThemeIcon' || k === 'ThemeColor') return function (n) { this.n = n; };
  if (k === 'ViewColumn') return { Active: 1 };
  if (k === 'StatusBarAlignment') return { Left: 1 };
  return proxy(); } });
const P = (name, state) => ({ name, dir: path.join(DEV, name), stack: 'web', state, agents: [], tokens: {}, ideas: { open: [], evaluated: [], done: 0, dropped: 0 }, held: false });
let projects = [];
const fakeExec = (cmd, args, opts, cb) => {
  const done = cb || opts;
  if (cmd === '/bin/ps' && args[0] === '-o') return done(null, (cmds[args[args.length - 1]] || '') + '\n', '');
  if (cmd === '/bin/ps' && args[0] === 'eww') return done(null, 'PID TTY\n' + (cmds[args[2]] || '') + ' ' + (envs[args[2]] || '') + '\n', '');
  if (cmd === 'lsof') return done(null, 'p1\nn' + (cwds[args[2]] || '/') + '\n', '');
  if (/shipm-watch$/.test(String(args[0]))) {                  // the watcher's JSON contract (health closed loop), scripted: everything applies and every fix is verified
    const w = args[1];
    if (w === 'contract') return done(null, JSON.stringify({ kinds: {}, ops: { interrupt: { executor: 'ext', wait_s: 0, checks: 1 }, relaunch: { executor: 'ext', wait_s: 0, checks: 1 }, fresh: { executor: 'ext', wait_s: 0, checks: 1 } } }), '');
    if (w === 'can') { let it = {}; try { it = JSON.parse(fs.readFileSync(path.join(ST, 'health.json'), 'utf8')).items.find(i => i.id === args[3]) || {}; } catch (e) { /* none */ } return done(null, JSON.stringify({ ok: true, why: '', project: it.project, kind: it.kind, working: true }), ''); }
    if (w === 'verify') return done(null, '{"gone": true, "detail": "", "chat_state": "idle"}', '');
    if (w === 'act' && args[2] === 'checkpoint') return done(null, 'nothing to save', '');
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
const CLAUDE = (name, extra = '') => `/Users/x/.local/bin/claude --continue --name ${name} --remote-control ${name}${extra}`;
const STALE = 'CLAUDE_CODE_SSE_PORT=44389', LIVE = 'CLAUDE_CODE_SSE_PORT=28820';
(async () => {
  ext.activate({ subscriptions: [], globalState: { get() {}, update() {} } });
  const view = { webview: { options: {}, set html(v) { html = v; htmlSets++; }, get html() { return html; }, onDidReceiveMessage: f => { handler = f; return { dispose() {} }; } }, visible: true, onDidChangeVisibility: f => { visCb = f; return { dispose() {} }; }, onDidDispose: () => ({ dispose() {} }) };
  provider.resolveWebviewView(view);
  const scenario = async (ps, setup) => { terms = []; created.length = 0; active = undefined; projects = ps; setup(); visCb(); await sleep(120); visCb(); await sleep(250); };   // refresh -> heal (twice: collect first, then heal sees the projects)
  await scenario([P('alpha', 'calm')], () => { mkTerm('claude', 101, CLAUDE('alpha'), STALE); mkTerm('alpha · Claude', 102, CLAUDE('alpha'), LIVE); });
  check('a revived stale chat next to a healthy one for the same project: the stale one is closed, the healthy one stays, nothing new opens', terms[0].disposed && !terms[1].disposed && created.length === 0);
  await scenario([P('sandbox', 'calm')], () => { mkTerm('claude', 201, CLAUDE('sandbox'), STALE); });
  check('a lone stale chat of an idle project is relaunched through bin/shipm-chat (it adds --continue itself), no focus stolen', terms[0].disposed && created.length === 1 && launch(created[0].opts).ok && launch(created[0].opts).name === 'sandbox' && !fs.readdirSync(ST).some(f => /^chat-fresh\.sandbox/.test(f)) && created[0].opts.location.preserveFocus === true, JSON.stringify(created.map(c => c.opts && c.opts.shellArgs)));
  await scenario([P('gamma', 'working')], () => { mkTerm('claude', 301, CLAUDE('gamma'), STALE); });
  check('a stale chat of a WORKING project is left alone and gets a "relaunch chat" chip', !terms[0].disposed && created.length === 0 && /data-relaunch="[^"]*gamma"/.test(html), html.slice(0, 80));
  await scenario([P('delta', 'calm')], () => { const t = mkTerm('claude', 401, CLAUDE('delta'), STALE); active = t; });
  check('the chat you are looking at is never closed automatically (chip instead)', !terms[0].disposed && created.length === 0 && /data-relaunch="[^"]*delta"/.test(html));
  await scenario([P('eps', 'working')], () => { mkTerm('claude', 501, CLAUDE('eps'), STALE); });
  await handler({ type: 'relaunch', dir: path.join(DEV, 'eps'), project: 'eps' }); await sleep(150);
  check('pressing "relaunch chat" closes the stale chat, opens a fresh one in front, and the chip goes away', terms[0].disposed && created.length === 1 && created[0].shown >= 1 && !/data-relaunch="[^"]*eps/.test(html), html.slice(0, 80));
  await scenario([P('kappa', 'working')], () => { mkTerm('claude', 1101, CLAUDE('kappa'), STALE); mkTerm('kappa · Claude', 1102, CLAUDE('kappa'), LIVE); });
  check('a working project with a stale duplicate: nothing is closed automatically, the chip appears', !terms[0].disposed && !terms[1].disposed && /data-relaunch="[^"]*kappa"/.test(html));
  await handler({ type: 'relaunch', dir: path.join(DEV, 'kappa'), project: 'kappa' }); await sleep(150);
  check('pressing relaunch there closes only the stale duplicate and keeps the healthy chat (nothing new opens)', terms[0].disposed && !terms[1].disposed && created.length === 0 && !/data-relaunch="[^"]*kappa/.test(html));
  fs.writeFileSync(path.join(ST, 'health.json'), JSON.stringify({ items: [{ id: 'h1', project: 'phi', actions: ['relaunch', 'fresh'] }] }));
  await scenario([P('phi', 'calm')], () => { mkTerm('claude', 1201, CLAUDE('phi'), LIVE); });
  await handler({ type: 'health', op: 'fresh', id: 'h1' }); await sleep(200);
  check('health "fresh chat" writes the one-shot chat-fresh marker before opening the chat; args are the same as for any launch', created.length === 1 && fs.existsSync(path.join(ST, 'chat-fresh.phi.' + launch(created[0].opts).nonce)) && launch(created[0].opts).ok && launch(created[0].opts).name === 'phi', JSON.stringify(created.map(c => c.opts.shellArgs)));
  await scenario([P('phi', 'calm')], () => { mkTerm('claude', 1202, CLAUDE('phi'), LIVE); });
  await handler({ type: 'health', op: 'relaunch', id: 'h1' }); await sleep(200);
  check('health "relaunch" writes no fresh marker (the wrapper continues the conversation)', created.length === 1 && !fs.existsSync(path.join(ST, 'chat-fresh.phi.' + launch(created[0].opts).nonce)), JSON.stringify(created.map(c => c.opts.shellArgs)));
  await scenario([P('pre', 'calm')], () => { mkTerm('pre · Claude', 1301, '/bin/bash /Users/x/Developer/AI-Workspace/bin/shipm-chat pre 0123456789abcdef', LIVE); mkTerm('pre2', 1302, '/bin/bash -p /w/bin/shipm-chat pre 0123456789abcdef', STALE); });
  check('a terminal whose process is still the wrapper (bash/env, before exec) is not a chat: nothing closed, nothing relaunched', terms.every(t => !t.disposed) && created.length === 0 && !/data-relaunch="/.test(html), JSON.stringify(terms.map(t => t.disposed)));
  const oldT = (name, pid) => { const t = mkTerm('claude', pid, '/Users/x/.local/bin/claude --continue --model opusplan --name ' + name + ' --remote-control ' + name, LIVE); t.creationOptions = { shellPath: '/Users/x/.local/bin/claude', shellArgs: ['--model', 'opusplan', '--name', name] }; return t; };
  await scenario([P('omega', 'calm')], () => { oldT('omega', 1401); });
  check('old-launcher chat (shellPath claude): never closed automatically, card gets the relaunch chip with the old-launcher tooltip', !terms[0].disposed && created.length === 0 && /data-relaunch="[^"]*omega"[^>]*title="This chat was started by the old launcher: a full VS Code restart would open a blank conversation\. Click to reopen it once \(the conversation continues\)"/.test(html), html.slice(0, 300));
  await handler({ type: 'relaunch', dir: path.join(DEV, 'omega'), project: 'omega' }); await sleep(150);
  check('pressing the chip on a calm project closes the old-launcher chat and reopens it through bin/shipm-chat; chip gone', terms[0].disposed && created.length === 1 && launch(created[0].opts).ok && launch(created[0].opts).name === 'omega' && !/data-relaunch="[^"]*omega"/.test(html), html.slice(0, 200));
  await sleep(150); const hn1 = JSON.parse(fs.readFileSync(path.join(ST, 'health-notice.json'), 'utf8')).text;
  check('chip result is verified and shown: "Relaunched omega: linked to VS Code again."', hn1 === 'Relaunched omega: linked to VS Code again.', hn1);
  await scenario([P('sigma', 'working')], () => { oldT('sigma', 1501); });
  await handler({ type: 'relaunch', dir: path.join(DEV, 'sigma'), project: 'sigma' }); await sleep(150);
  check('busy project with an old-launcher chat: chip shown, pressing it closes nothing', !terms[0].disposed && created.length === 0 && /data-relaunch="[^"]*sigma"/.test(html));
  const hn2 = JSON.parse(fs.readFileSync(path.join(ST, 'health-notice.json'), 'utf8')).text;
  check('pressing the chip on a working project is no longer silent: "Not done: sigma is working; the chip stays until it is idle."', hn2 === 'Not done: sigma is working; the chip stays until it is idle.', hn2);
  await scenario([P('tau', 'calm')], () => { const t = mkTerm('claude', 1601, CLAUDE('tau'), LIVE); });
  check('revived terminal where VS Code gives no creationOptions: treated as unknown, nothing flagged or closed', !terms[0].disposed && created.length === 0 && !/data-relaunch="/.test(html));
  await scenario([P('upsilon', 'calm')], () => { const t = mkTerm('claude', 1701, CLAUDE('upsilon'), LIVE); t.creationOptions = { shellPath: '/bin/bash', shellArgs: ['-p', '/w/bin/shipm-chat', 'upsilon', '0123456789abcdef'] }; });
  check('a chat started by the new launcher is not flagged', !terms[0].disposed && !/data-relaunch="/.test(html));
  fs.writeFileSync(path.join(ST, 'health.json'), JSON.stringify({ items: [{ id: 'h2', project: 'psi', actions: ['relaunch', 'fresh'] }] }));
  await scenario([P('psi', 'calm')], () => { mkTerm('psi · Claude', 1801, '-zsh', ''); });
  try { fs.unlinkSync(path.join(ST, 'health-notice.json')); } catch (e) { /* none */ }
  await handler({ type: 'health', op: 'fresh', id: 'h2' }); await sleep(200);
  const hn = JSON.parse(fs.readFileSync(path.join(ST, 'health-notice.json'), 'utf8')).text;
  check('Fresh chat when the open tab is not a chat of this project: skipped with the reason, nothing opened, never silent', created.length === 0 && /Fresh chat: skipped - no psi chat in this VS Code window/.test(hn), hn);
  await scenario([P('-bad', 'calm')], () => {});
  await handler({ type: 'relaunch', dir: path.join(DEV, '-bad'), project: '-bad' }); await sleep(150);
  const pn = JSON.parse(fs.readFileSync(path.join(ST, 'project-notice.json'), 'utf8')).text;
  check('a folder name the launcher does not accept opens no terminal and shows a notice', created.length === 0 && /^Chat not opened: the folder name -bad has characters the chat launcher does not accept; rename the folder$/.test(pn), pn);
  fs.writeFileSync(path.join(ST, 'health.json'), JSON.stringify({ items: [{ id: 'h3', project: 'chi', actions: ['relaunch', 'fresh'] }] }));
  await scenario([P('chi', 'calm')], () => { mkTerm('claude', 1901, CLAUDE('chi'), LIVE); });
  fs.chmodSync(ST, 0o500); shown.length = 0;
  try { await handler({ type: 'health', op: 'fresh', id: 'h3' }); await sleep(200); } finally { fs.chmodSync(ST, 0o700); }
  check('Fresh chat whose marker cannot be written starts NO terminal (it must not silently continue the old conversation) and says so', created.length === 0 && shown.some(m => /could not be saved/.test(m)), JSON.stringify([created.length, shown]));
  await scenario([P('zeta', 'calm')], () => { mkTerm('zsh', 601, '-zsh', STALE, DEV); });
  check('an ordinary shell terminal is never touched', !terms[0].disposed && created.length === 0);
  await scenario([P('sample-app', 'calm')], () => { mkTerm('claude', 701, '/Users/x/.local/bin/claude --continue', STALE, path.join(DEV, 'sample-app')); });
  check('an older chat without --name is recognised by its working folder and relaunched', terms[0].disposed && created.length === 1 && created[0].opts.cwd === path.join(DEV, 'sample-app'));
  await scenario([P('eta', 'calm')], () => { mkTerm('claude', 801, CLAUDE('eta'), LIVE); mkTerm('claude', 802, CLAUDE('eta'), LIVE); });
  check('two healthy chats for one project are both left alone (never guess which one to close)', terms.every(t => !t.disposed) && created.length === 0);
  await scenario([P('theta', 'calm')], () => { mkTerm('claude', 901, CLAUDE('theta'), ''); });
  check('a chat with no IDE port at all is not treated as stale', !terms[0].disposed && created.length === 0);
  await scenario([P('iota', 'calm')], () => { mkTerm('claude', 1001, CLAUDE('iota'), LIVE); });
  const before = terms.length; await handler({ type: 'open', dir: path.join(DEV, 'iota') }); await sleep(100);
  check('clicking a project card finds a revived chat (renamed tab) by its process: no second chat is opened', terms.length === before && created.length === 0 && terms[0].shown >= 1);
  console.log('   chips in the last render:', (html.match(/data-relaunch="[^"]*"/g) || []).join(' ') || 'none');
  check('a project with a healthy chat shows no "relaunch chat" chip', !/data-relaunch="/.test(html));
  projects = [P('same', 'calm')]; visCb(); await sleep(200); const s1 = htmlSets; visCb(); await sleep(200); visCb(); await sleep(200);
  check('refreshing with nothing new does not set the page again (a redraw would close an open add form)', htmlSets === s1, htmlSets + ' vs ' + s1);
  projects = [P('same', 'calm')]; visCb(); await sleep(200);
  await handler({ type: 'editing', on: true }); const e0 = htmlSets; projects = [P('same', 'working')]; visCb(); await sleep(250); visCb(); await sleep(250);
  check('while you are typing in the add box the panel is not redrawn, however often the data changes', htmlSets === e0, htmlSets + ' vs ' + e0);
  await handler({ type: 'editing', on: false }); await sleep(150);
  check('as soon as you leave the box the held redraw is drawn once, with the newest data', htmlSets === e0 + 1 && /same/.test(html), htmlSets + ' vs ' + e0);
  console.log(fails ? '\nFAILED: ' + fails : '\nALL PASS'); fs.rmSync(IDE, { recursive: true, force: true }); process.exit(fails ? 1 : 0);
})().catch(e => { console.error('test crashed:', e); process.exit(2); });
