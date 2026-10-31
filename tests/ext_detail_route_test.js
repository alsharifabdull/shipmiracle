// F9 and F8 in the extension, against a stand-in for VS Code (acceptance 19, 24, 25): the `detail` route is read-only and takes only a project name from the page; the answer is cached 15 s and
// an identical page is not set again; shipmiracle.cardChatExcerpt off reads no transcript; the unread marker is set / cleared / persisted per chat name and respects shipmiracle.unreadMarker.
// Run: node tests/ext_detail_route_test.js
require('./shipmiracle_isolation').apply();
const Module = require('module'), path = require('path'), fs = require('fs'), os = require('os');
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'shipmiracle-dr-'));
const ST = path.join(tmp, 'state'), WSD = path.join(tmp, 'ws'), DEV = path.join(tmp, 'Dev'), PROJ = path.join(DEV, 'demo'), CL = path.join(tmp, 'claude');
const SESS = path.join(CL, PROJ.replace(/[^A-Za-z0-9]/g, '-'));
for (const d of [ST, path.join(WSD, 'config'), path.join(PROJ, 'docs'), SESS]) fs.mkdirSync(d, { recursive: true });
fs.writeFileSync(path.join(PROJ, 'docs', 'STATUS.md'), '# S\n\nUpdated: 21 Oct 2026, test run.\n');
const transcript = text => fs.writeFileSync(path.join(SESS, 's.jsonl'), JSON.stringify({ type: 'assistant', timestamp: new Date().toISOString(), message: { content: [{ type: 'text', text }, { type: 'tool_use', name: 'Bash', input: { command: 'SECRET-ARG' } }] } }) + '\n');
transcript('The transcript says: tests are running.');
Object.assign(process.env, { SHIPMIRACLE_TEST: '1', SHIPMIRACLE_EXT_STATE: ST, SHIPMIRACLE_EXT_WS: WSD, SHIPMIRACLE_EXT_DEV: DEV, SHIPMIRACLE_EXT_CLAUDE: CL, SHIPMIRACLE_DIAG_DIR: path.join(tmp, 'diag'), SHIPMIRACLE_HEAL_MS: '99999999' });
let fails = 0; const check = (n, c, info = '') => { console.log((c ? 'PASS ' : 'FAIL ') + n + (c ? '' : ' ' + info)); if (!c) fails++; };
const wait = ms => new Promise(r => setTimeout(r, ms));

const mkP = (name, dir, state) => ({ name, dir, stack: 'web', state, agents: [], tokens: { claudeDay: 0, claudeWeek: 0 }, ideas: { open: [], evaluated: [], done: 0, dropped: 0 }, held: false, cr: null, playbook: null, flow: null, next: 'do the next thing', lastCommit: 0, dirty: 0, health: [] });
const PROJ2 = path.join(DEV, 'sec'), SESS2 = path.join(CL, PROJ2.replace(/[^A-Za-z0-9]/g, '-')); fs.mkdirSync(PROJ2, { recursive: true }); fs.mkdirSync(SESS2, { recursive: true });
const world = { projects: [mkP('demo', PROJ, 'idle'), mkP('sec', PROJ2, 'idle')] };
const cfg = { cardChatExcerpt: true, unreadMarker: true };
const cbs = {}; const terms = []; let active; let focused = true;
const opened = [], calls = []; const realOpen = fs.openSync; fs.openSync = function (f) { opened.push(String(f)); return realOpen.apply(this, arguments); };
const proxy = () => new Proxy(function () {}, { get: (t, k) => k === 'then' ? undefined : (k === 'dispose' ? () => {} : proxy()), apply: () => proxy() });
const vscode = new Proxy({}, { get: (t, k) => {
  if (k === 'window') return new Proxy({}, { get: (w, kk) => {
    if (kk === 'terminals') return terms; if (kk === 'activeTerminal') return active; if (kk === 'state') return { focused };
    if (kk === 'registerWebviewViewProvider') return (id, prov) => { module.provider = prov; return { dispose() {} }; };
    if (kk === 'onDidChangeActiveTerminal') return f => { (cbs.activeTerminal = cbs.activeTerminal || []).push(f); return { dispose() {} }; };
    if (kk === 'createTerminal') return o => { const tt = { name: o.name, exitStatus: undefined, show() {}, sendText() {}, dispose() {} }; terms.push(tt); return tt; };
    return proxy(); } });
  if (k === 'workspace') return new Proxy({}, { get: (w, kk) => kk === 'getConfiguration' ? () => ({ get: key => cfg[key] }) : proxy() });
  if (k === 'commands') return { registerCommand: (id, f) => { cbs[id] = f; return { dispose() {} }; }, executeCommand: async () => {} };
  if (k === 'Uri') return { parse: s => ({ s }), file: f => ({ fsPath: f }) };
  if (k === 'ThemeIcon' || k === 'ThemeColor') return function (n) { this.n = n; };
  if (k === 'ViewColumn') return { Active: 1 }; if (k === 'StatusBarAlignment') return { Left: 1 };
  return proxy(); } });
const real = Module._load;
Module._load = function (req, parent, ...r) {
  if (req === 'vscode') return vscode;
  if (req === 'child_process') return { execFile: (cmd, args, o, cb) => { if (args[0] === 'project') calls.push({ cmd, args }); if (args[0] === 'project' && args[1] === 'seen') world.projects[0].unread = ''; (cb || o)(null, '', ''); return {}; } };
  if (req === './data') return { collect: async () => ({ projects: world.projects.map(p => ({ ...p })), plan: {}, guard: {}, ask: null }) };
  return real.call(this, req, parent, ...r); };
const ext = require(path.join(__dirname, '../vscode-ext/shipmiracle-panel/extension.js'));

(async () => {
  const ctx = { subscriptions: [], globalState: { get() {}, update() {} } };
  ext.activate(ctx); await wait(300);
  let handler, sets = 0, page = ''; const view = { webview: { options: {}, set html(v) { sets++; page = v; }, get html() { return page; }, onDidReceiveMessage: f => { handler = f; return { dispose() {} }; } }, visible: true, onDidChangeVisibility: () => ({ dispose() {} }), onDidDispose: () => ({ dispose() {} }) };
  module.provider.resolveWebviewView(view); await wait(500);
  const refresh = async () => { await cbs['shipmiracle.refresh'](); await wait(60); };
  const claudeOpens = () => opened.filter(f => f.startsWith(CL)).length;

  // ---- F9 route
  const before = fs.readdirSync(PROJ).join() + fs.readdirSync(path.join(PROJ, 'docs')).join();
  check('before any request no transcript has been opened and the page carries no chat text', claudeOpens() === 0 && !page.includes('The transcript says'));
  await handler({ type: 'detail', project: 'demo' }); await wait(80);
  check('detail for a known project: the next page carries the chat text, the Bash tool name and the STATUS note, escaped', page.includes('The transcript says: tests are running.') && page.includes('Bash') && page.includes('21 Oct 2026, test run.') && !page.includes('SECRET-ARG'));
  check('it read the transcript (the newest session file) exactly through detail.js', claudeOpens() >= 1);
  const n1 = sets, c1 = claudeOpens(); await handler({ type: 'detail', project: 'demo' }); await wait(80);
  check('a second request inside 15 s is answered from the cache: no new transcript read, the identical page is not set again', claudeOpens() === c1 && sets === n1, `${claudeOpens()} ${c1} ${sets} ${n1}`);
  for (const bad of [{ type: 'detail', project: 'nope' }, { type: 'detail', project: '../../etc' }, { type: 'detail' }, { type: 'detail', project: 42 }, { type: 'detail', project: { x: 1 } }, { type: 'detail', project: 'x'.repeat(500) }]) { const c = claudeOpens(); await handler(bad); await wait(30); check('detail ignored: ' + JSON.stringify(bad).slice(0, 50), claudeOpens() === c); }
  const c2 = claudeOpens(); await handler({ type: 'detail', project: 'demo', dir: '/etc', path: '/etc/passwd', file: '../../secret', report: '/etc/hosts' }); await wait(50);
  check('a path or any other field sent by the page is ignored (the folder comes from the extension\'s own data)', !opened.some(f => f.startsWith('/etc')) && claudeOpens() === c2);
  check('the route writes nothing in the project or its docs', fs.readdirSync(PROJ).join() + fs.readdirSync(path.join(PROJ, 'docs')).join() === before);
  // setting off
  cfg.cardChatExcerpt = false; transcript('NEW words after the setting went off.'); const t = Date.now() + 16000; const realNow = Date.now; Date.now = () => t;
  const c3 = claudeOpens(); await handler({ type: 'detail', project: 'demo' }); await wait(80); Date.now = realNow;
  check('shipmiracle.cardChatExcerpt off: no transcript file is opened at all, the page says Hidden and holds no chat text (old or new)', claudeOpens() === c3 && page.includes('Hidden. Turn on shipmiracle.cardChatExcerpt in Settings to see it here.') && !page.includes('tests are running') && !page.includes('NEW words'), String(claudeOpens() - c3));
  cfg.cardChatExcerpt = true;


  // ---- a secret in the transcript never reaches the page, the trace log or the console (redaction happens in detail.js, before anything is stored or drawn)
  { const J = (...a) => a.join(''), secrets = [J('sk-', 'ant-', 'api03-', 'Qq1Ww2', 'Ee3Rr4Tt5'), J('DB_PASS', 'WORD=hunt', 'er2xyz'), J('Authori', 'zation: Bas', 'ic dXNlcjpwYXNzd29yZA=='), J('postgres://adm', 'in:S3cr3tPw@db.example.com/app')];
    const logs = [], keep = { log: console.log, error: console.error, warn: console.warn, info: console.info }; for (const k of Object.keys(keep)) console[k] = (...a) => { logs.push(a.join(' ')); };
    fs.writeFileSync(path.join(SESS2, 's.jsonl'), JSON.stringify({ type: 'assistant', timestamp: new Date().toISOString(), message: { content: [{ type: 'text', text: 'Here are the settings: ' + secrets.join(' and ') + ' done' }] } }) + '\n');
    await refresh(); await handler({ type: 'detail', project: 'sec' }); await wait(120); for (const k of Object.keys(keep)) console[k] = keep[k];
    const trace = (() => { try { return fs.readFileSync(path.join(tmp, 'diag', 'panel-trace.log'), 'utf8'); } catch (e) { return ''; } })();
    const hay = { page, trace, console: logs.join('\n') }; const found = [];
    for (const needle of ['Qq1Ww2', 'Ee3Rr4Tt5', 'hunter2xyz', 'dXNlcjpwYXNzd29yZA', 'S3cr3tPw']) for (const [where, text] of Object.entries(hay)) if (text.includes(needle)) found.push(where + ':' + needle.slice(0, 8));
    check('a secret in the transcript is in none of: the page HTML, panel-trace.log, any console output (the masked words are shown)', found.length === 0 && page.includes('Here are the settings:') && page.includes('[hidden]'), JSON.stringify(found)); }

  // ---- F8 unread marker: the CLI says what is new (p.unread from `shipm report panel`), the extension calls `shipm project seen NAME` and shows / hides the marker
  const marker = () => /class="newm"/.test(page);
  world.projects[0].unread = '';
  await refresh(); check('no unread data: no marker, no `shipm project seen` call', !marker() && calls.length === 0);
  world.projects[0].unread = 'turn'; await refresh();
  check('unread "turn": marker "New", the title "New: its chat finished a turn.", the card aria-label contains "new"', marker() && page.includes('New: its chat finished a turn.') && /aria-label="demo, new: the chat finished a turn/.test(page));
  check('the marker is not counted in any badge', !/class="hbadge[^"]*">1/.test(page));
  check('the primary Open chat button carries the 6 px dot (aria-hidden)', /<button class="btn primary"[^>]*><i class="udot udotb" aria-hidden="true"><\/i>Open chat/.test(page));
  await refresh(); check('it survives a redraw', marker() && calls.length === 0);
  cfg.unreadMarker = false; await refresh(); check('shipmiracle.unreadMarker off: nothing shown, nothing called', !marker() && calls.length === 0);
  cfg.unreadMarker = true; await refresh(); check('on again: shown again', marker());
  calls.length = 0; await handler({ type: 'open', dir: PROJ }); await wait(150);
  check('Open chat calls exactly `shipm project seen demo` (argv, no shell) and the marker goes', calls.length >= 1 && calls[0].args.join(' ') === 'project seen demo' && calls[0].cmd.endsWith(path.join('bin', 'shipm')) && !marker(), JSON.stringify(calls));
  world.projects[0].unread = 'wait'; await refresh(); check('unread "wait": the waiting text', marker() && page.includes('New: its chat is waiting for you.'));
  calls.length = 0; await wait(450);
  const tt = terms.find(x => x.name === 'demo · Claude') || (terms.push({ name: 'demo · Claude', exitStatus: undefined, show() {}, sendText() {}, dispose() {} }), terms[terms.length - 1]);
  (cbs.activeTerminal || []).forEach(f => f(tt)); await wait(150);
  check('focusing the chat terminal calls `shipm project seen demo`', calls.some(c => c.args.join(' ') === 'project seen demo'), JSON.stringify(calls));
  await wait(450); world.projects[0].unread = 'turn'; active = tt; focused = true; calls.length = 0; await wait(400); await refresh(); await refresh(); await wait(100);
  check('a marked project whose chat is the focused tab is marked seen at once (never "new" while you look)', calls.length >= 1 && !marker());
  active = undefined; world.projects[0].unread = 'turn'; calls.length = 0; await handler({ type: 'seen', project: 'demo' }); await wait(50);
  check('a page cannot mark anything seen (no such message)', calls.length === 0);
  console.log(fails ? `\nFAILED: ${fails}` : '\nALL PASS'); fs.rmSync(tmp, { recursive: true, force: true }); process.exit(fails ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
