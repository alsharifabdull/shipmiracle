// Panel v3 task 4b: Ask aside (F3, /btw), Ask inbox (F4) and the Remote Control Undo, as far as the extension side goes (vscode-ext/shipmiracle-panel/ask.js + extension.js against a stand-in vscode).
// What is asserted: the command builders and the hostile-input behaviour, the Open path guard, the exact text sent to a chat or typed into the owner terminal (never Enter), and that `shipm ask`
// is never executed by the panel. Run: node tests/ext_ask_test.js
require('./shipmiracle_isolation').apply();
const Module = require('module'); const path = require('path'); const fs = require('fs'); const os = require('os');
const { spawnSync } = require('child_process');
const ASK = require('../vscode-ext/shipmiracle-panel/ask.js'); const C = require('../vscode-ext/shipmiracle-panel/charter.js'); const F3 = require('./panel_v3_tab_fixtures.js');
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'shipmiracle-ask-'));
let fails = 0, n = 0; const check = (name, c, info = '') => { n++; console.log((c ? 'PASS ' : 'FAIL ') + name + (c ? '' : ' ' + info)); if (!c) fails++; };
const SHIPM = '/ws dir/it\'s/bin/shipm';

// ---------- 1. drift against shipmiracle/ask.py ----------
const py = fs.readFileSync(path.join(__dirname, '..', 'shipmiracle', 'ask.py'), 'utf8');
check('drift: MAX_Q, DAILY_CAP and NOTE_RE equal shipmiracle/ask.py', new RegExp('^MAX_Q = ' + ASK.MAX_Q + '$', 'm').test(py) && new RegExp('^DAILY_CAP = ' + ASK.DAILY_CAP + '(\\s|$)', 'm').test(py)
  && py.includes('NOTE_RE = re.compile(r"' + ASK.NOTE_RE.source.replace(/^\^/, '').replace(/\$$/, '') + '")'), ASK.NOTE_RE.source);

// ---------- 2. the question ----------
const ok = s => ASK.checkQuestion(s).ok;
check('question: plain text, Arabic and mixed text are accepted and kept', ok('What is a monad?') && ASK.checkQuestion('ما هو الفرق بين الذاكرة والتخزين؟').value === 'ما هو الفرق بين الذاكرة والتخزين؟' && ok('اشرح git rebase'));
check('question: exactly 2000 characters (code points) pass, 2001 are refused; emoji count once', ok('a'.repeat(2000)) && ASK.checkQuestion('a'.repeat(2001)).why === 'tooLong' && ok('😀'.repeat(2000)) && !ok('😀'.repeat(2001)));
check('question: a line break of any kind is refused (not silently joined)', ['a\nb', 'a\r\nb', 'a\rb', 'a b', 'a b', '\nask'].every(s => ASK.checkQuestion(s).why === 'newline'));
check('question: tab, NUL, ESC, DEL and C1 controls are refused', ['a\tb', 'a\0b', 'a\u001bb', 'a\u007fb', 'a\u0085b'].every(s => ASK.checkQuestion(s).why === 'control' || ASK.checkQuestion(s).why === 'newline'));
check('question: empty, spaces only, non-strings are refused', ['', '   ', null, undefined, 5, {}, ['a']].every(s => ASK.checkQuestion(s).why === 'empty'));
check('question: a leading dash is refused (the CLI would read it as an option); a dash inside is fine', ASK.checkQuestion('-rf').why === 'dash' && ASK.checkQuestion('  --inbox x').why === 'dash' && ok('a - b') && ok('x-y'));
check('question: bidi marks and zero-width joiners are removed, the rest is kept', ASK.checkQuestion('a‮b‍c').value === 'abc');

// ---------- 3. the typed command: argv-quoted, round trip through /bin/sh ----------
const roundTrip = argv => { const o = spawnSync('/bin/sh', ['-c', 'f() { for a in "$@"; do printf "%s\\0" "$a"; done; }; f ' + C.joinCmds([argv])], { encoding: 'utf8' }); return o.status === 0 ? o.stdout.split('\0').slice(0, -1) : null; };
const PWN = path.join(tmp, 'pwned');
const hostile = ["it's a \"test\"", '$(touch ' + PWN + ')', '`touch ' + PWN + '`', 'a; touch ' + PWN, 'a && touch ' + PWN + ' #', 'a | cat', "'; touch " + PWN + "; '", 'back\\slash \\$HOME ${HOME}', '~ * ? [a] {b,c} !! !x', 'ما هو $(touch ' + PWN + ') الفرق؟', '<script>alert(1)</script>', '%s %d \\n', "x'\"y'\"z"];
for (const q of hostile) { let r = null; try { r = roundTrip(ASK.inboxArgv(SHIPM, q)); } catch (e) { r = null; } check('command: ' + JSON.stringify(q).slice(0, 50) + ' comes out of the shell as exactly one argument, nothing runs', !!r && r.join('|') === [SHIPM, 'ask', '--inbox', q].join('|') && !fs.existsSync(PWN), JSON.stringify(r)); }
check('command: the exact shape is <shipm> ask --inbox <question>, each word single-quoted', ASK.inboxArgv(SHIPM, 'hi').join(' ') === SHIPM + ' ask --inbox hi' && C.joinCmds([ASK.inboxArgv('/w/shipm', 'hi there')]) === "'/w/shipm' 'ask' '--inbox' 'hi there'");
for (const bad of ['a\nb', '', '-x', 'a'.repeat(2001), 'a\u001bb']) { let t = false; try { ASK.inboxArgv(SHIPM, bad); } catch (e) { t = true; } check('command: inboxArgv refuses ' + JSON.stringify(bad).slice(0, 20), t); }
check('promote: only a real note name; no path, no traversal, no other file name', ASK.promoteArgv('/w/shipm', '2026-10-21-what-is-a-monad.md').slice(1).join(' ') === 'ask promote 2026-10-21-what-is-a-monad.md'
  && ['../2026-10-21-x.md', 'docs/notes/2026-10-21-x.md', '2026-10-21-X.md', 'x.md', '2026-10-21-x.md\n', '2026-10-21-x.md; rm', '2026-10-21-.md', '', null].every(b => { try { ASK.promoteArgv('/w/shipm', b); return false; } catch (e) { return true; } }));
check('remote: Turn on and Undo are fixed argv with no user text', ASK.remoteFixArgv('/w/shipm').join(' ') === '/w/shipm init --step remote-control' && ASK.remoteUndoArgv('/w/shipm').join(' ') === '/w/shipm init --undo remote-control');

// ---------- 4. the Open guard ----------
const mkAsk = name => { const d = path.join(tmp, name); fs.mkdirSync(path.join(d, 'docs', 'notes'), { recursive: true }); return d; };
const NOTE = '2026-10-21-what-is-a-monad.md';
{
  const d = mkAsk('ask1'); fs.writeFileSync(path.join(d, 'docs', 'notes', NOTE), 'x'); fs.writeFileSync(path.join(tmp, 'secret.md'), 'SECRET');
  const g = ASK.guardNote(d, 'docs/notes/' + NOTE);
  check('guard: a real note inside docs/notes opens (real path returned)', g.ok && g.file === fs.realpathSync(path.join(d, 'docs', 'notes', NOTE)), JSON.stringify(g));
  const no = (label, r) => check('guard: ' + label + ' is refused', r.ok === false, JSON.stringify(r));
  no('traversal docs/notes/../../x', ASK.guardNote(d, 'docs/notes/../../secret.md')); no('traversal ../secret.md', ASK.guardNote(d, '../secret.md')); no('an absolute path', ASK.guardNote(d, path.join(tmp, 'secret.md')));
  no('a path in another folder (docs/other)', ASK.guardNote(d, 'docs/other/' + NOTE)); no('a sub folder', ASK.guardNote(d, 'docs/notes/sub/' + NOTE)); no('a wrong file name', ASK.guardNote(d, 'docs/notes/README.md')); no('NUL', ASK.guardNote(d, 'docs/notes/' + NOTE + '\0.md'));
  no('a missing note', ASK.guardNote(d, 'docs/notes/2026-10-21-gone.md')); no('non-strings', ASK.guardNote(d, null)); no('an empty ask folder', ASK.guardNote('', 'docs/notes/' + NOTE));
  fs.symlinkSync(path.join(tmp, 'secret.md'), path.join(d, 'docs', 'notes', '2026-10-21-link-out.md')); no('a symlink to a file outside', ASK.guardNote(d, 'docs/notes/2026-10-21-link-out.md'));
  fs.symlinkSync(path.join(d, 'docs', 'notes', NOTE), path.join(d, 'docs', 'notes', '2026-10-21-link-in.md')); no('a symlink that points inside (the file itself must be real)', ASK.guardNote(d, 'docs/notes/2026-10-21-link-in.md'));
  fs.mkdirSync(path.join(d, 'docs', 'notes', '2026-10-21-adir.md')); no('a folder named like a note', ASK.guardNote(d, 'docs/notes/2026-10-21-adir.md'));
  const e = mkAsk('ask2'); fs.rmSync(path.join(e, 'docs', 'notes'), { recursive: true }); fs.mkdirSync(path.join(tmp, 'outside')); fs.writeFileSync(path.join(tmp, 'outside', NOTE), 'x'); fs.symlinkSync(path.join(tmp, 'outside'), path.join(e, 'docs', 'notes'));
  no('docs/notes itself is a symlink out', ASK.guardNote(e, 'docs/notes/' + NOTE));
  const f = mkAsk('ask3'); fs.rmSync(path.join(f, 'docs'), { recursive: true }); fs.mkdirSync(path.join(tmp, 'outdocs', 'notes'), { recursive: true }); fs.writeFileSync(path.join(tmp, 'outdocs', 'notes', NOTE), 'x'); fs.symlinkSync(path.join(tmp, 'outdocs'), path.join(f, 'docs'));
  no('docs is a symlink out', ASK.guardNote(f, 'docs/notes/' + NOTE));
}
check('inboxProject: only a project whose data says ask.inbox === true with an absolute dir', ASK.inboxProject([{ name: 'a', dir: '/x' }, { name: 'ask', dir: '/y/ask', ask: { inbox: true } }]).name === 'ask' && ASK.inboxProject([{ name: 'ask', dir: '/y', ask: { inbox: 'yes' } }, { name: 'b', dir: 'rel', ask: { inbox: true } }, null]) === null);

// ---------- 5. the extension against a stand-in vscode ----------
const ST = path.join(tmp, 'state'), WSD = path.join(tmp, 'ws'), DEV = path.join(tmp, 'Dev');
for (const d of [ST, WSD, DEV, path.join(WSD, 'config'), path.join(WSD, 'bin')]) fs.mkdirSync(d, { recursive: true });
fs.mkdirSync(path.join(tmp, 'ide')); fs.writeFileSync(path.join(tmp, 'ide', '1234.lock'), JSON.stringify({ pid: process.pid }));
Object.assign(process.env, { SHIPMIRACLE_IDE_DIR: path.join(tmp, 'ide'), SHIPMIRACLE_TEST: '1', SHIPMIRACLE_EXT_STATE: ST, SHIPMIRACLE_EXT_WS: WSD, SHIPMIRACLE_EXT_DEV: DEV, SHIPMIRACLE_DIAG_DIR: path.join(tmp, 'diag'), SHIPMIRACLE_HEAL_MS: '99999999', SHIPMIRACLE_FIX_WAIT_SCALE: '0', SHIPMIRACLE_EXT_SETUP: '1' });
const cmds = {}; let projects = [], terms = [], created = [], opened = [], remote = { state: 'off' }, psMap = {}, execs = [], rowsAnswer = '';
const term = (name, pid) => { const t = { name, exitStatus: undefined, sent: [], raw: [], shown: 0, processId: Promise.resolve(pid), sendText(x, nl) { this.raw.push([x, nl]); if (!/^\/rename /.test(x) && x !== '\u0015' && x !== '\u0005\u0015') this.sent.push([x, nl]); }, dispose() {}, show() { this.shown++; } }; terms.push(t); return t; };
const proxy = () => new Proxy(function () {}, { get: (t, k) => k === 'then' ? undefined : (k === 'dispose' ? () => {} : proxy()), apply: () => proxy() });
const vscode = new Proxy({}, { get: (t, k) => {
  if (k === 'window') return new Proxy({}, { get: (w, kk) => {
    if (kk === 'terminals') return terms;
    if (kk === 'registerWebviewViewProvider') return (id, prov) => { module.provider = prov; return { dispose() {} }; };
    if (kk === 'activeTerminal') return undefined;
    if (kk === 'createTerminal') return o => { const x = term(o.name, 5000 + created.length); x.opts = o; created.push(x); return x; };
    if (kk === 'showTextDocument') return async d => { opened.push(d.uri.fsPath); };
    return proxy(); } });
  if (k === 'workspace') return new Proxy({}, { get: (w, kk) => kk === 'openTextDocument' ? async u => ({ uri: u }) : proxy() });
  if (k === 'commands') return { registerCommand: (id, fn) => { cmds[id] = fn; return { dispose() {} }; }, executeCommand: async () => {} };
  if (k === 'Uri') return { parse: s => ({ s }), file: f => ({ fsPath: f }) };
  if (k === 'ThemeIcon' || k === 'ThemeColor') return function (nn) { this.n = nn; };
  if (k === 'ViewColumn') return { Active: 1 };
  if (k === 'StatusBarAlignment') return { Left: 1 };
  return proxy(); } });
const fakeExec = (cmd, args, opts, cb) => {
  cb = cb || opts; execs.push([cmd, args]);
  if (cmd === '/bin/ps') { if (args[0] === '-o') cb(null, 'claude --name ' + (psMap[args[args.length - 1]] || 'x') + '\n', ''); else cb(null, 'PID CMD CLAUDE_CODE_SSE_PORT=1234\n', ''); return {}; }
  if (args && args[0] === 'init') { cb(null, rowsAnswer, ''); return {}; }
  cb(null, '', ''); return {};
};
const real = Module._load;
Module._load = function (req, parent, ...r) {
  if (req === 'vscode') return vscode;
  if (req === 'child_process') return { execFile: fakeExec };
  if (req === './data') return { collect: async () => ({ projects, plan: {}, guard: {}, ask: null, remote }) };
  if (req === './panel') return { html: () => '<html></html>' };
  return real.call(this, req, parent, ...r); };
const ext = require(path.join(__dirname, '../vscode-ext/shipmiracle-panel/extension.js'));
const wait = ms => new Promise(r => setTimeout(r, ms));
const mk = (name, extra = {}) => ({ name, dir: path.join(DEV, name), stack: 'web', state: 'idle', agents: [], tokens: {}, ideas: { open: [], evaluated: [], done: 0, dropped: 0 }, held: false, ...extra });
const pnote = () => { try { return JSON.parse(fs.readFileSync(path.join(ST, 'project-notice.json'), 'utf8')).text; } catch (e) { return null; } };
const view = { webview: { options: {}, set html(v) {}, get html() { return ''; }, onDidReceiveMessage: f => { module.handler = f; return { dispose() {} }; } }, visible: true, onDidChangeVisibility: () => ({ dispose() {} }), onDidDispose: () => ({ dispose() {} }) };
const refreshed = async () => { await cmds['shipmiracle.refresh'](); await wait(150); };
const send = async m => { module.handler(m); await wait(250); };
const askDir = path.join(DEV, 'ask');
fs.mkdirSync(path.join(askDir, 'docs', 'notes'), { recursive: true }); fs.writeFileSync(path.join(askDir, 'docs', 'notes', NOTE), 'Question: x\n');
const askP = (extra = {}) => mk('ask', { ask: { inbox: true, questions_today: 3, notes: 1, last: { title: 'What is a monad?', path: 'docs/notes/' + NOTE, ts: 1 }, ...extra } });
let ctr = 0, A, chat;
const reset = async (list) => { terms.length = 0; created.length = 0; opened.length = 0; execs.length = 0; try { fs.unlinkSync(path.join(ST, 'project-notice.json')); } catch (e) { /* none */ }
  ctr++; A = 'proj' + ctr; psMap = {}; chat = null; projects = list ? list(A) : [mk(A), askP()]; await refreshed(); };
const openChat = () => { const pid = 4000 + ctr; psMap[pid] = A; chat = term(A + ' · Claude', pid); return chat; };
const shipmiracleLine = () => created.map(t => t.sent).flat();
const noShipmiracleAsk = () => !execs.some(e => e[1] && (e[1][0] === 'ask' || e[1].includes('ask')));
(async () => {
  ext.activate({ subscriptions: [], globalState: { get() {}, update() {} } }); await wait(300);
  module.provider.resolveWebviewView(view); await wait(300);

  // ---- Ask aside
  await reset(); openChat(); await refreshed();
  await send({ type: 'ask', op: 'aside', project: A });
  check('aside: exactly "/btw " is sent to the project chat with Enter=false, and nothing else (no terminal created, no command)', chat.sent.length === 1 && chat.sent[0][0] === '/btw ' && chat.sent[0][1] === false && !created.length && chat.shown === 1, JSON.stringify([chat.sent, created.length]));
  check('aside: the owner is told to type the question and press Enter', new RegExp('Typed /btw in the ' + A + ' chat').test(pnote() || ''), pnote());
  await send({ type: 'ask', op: 'aside', project: A, text: 'rm -rf ~', q: 'x', command: 'y' });
  check('aside: extra fields in the message are ignored: still only "/btw "', chat.sent.length === 2 && chat.sent.every(s => s[0] === '/btw ' && s[1] === false));
  await reset(); await send({ type: 'ask', op: 'aside', project: A });
  check('aside: no open chat -> nothing sent anywhere, owner told', !created.length && !terms.some(t => t.sent.length) && new RegExp('no ' + A + ' chat is open').test(pnote() || ''), pnote());
  await reset(); openChat(); psMap[4000 + ctr] = 'someone-else'; await send({ type: 'ask', op: 'aside', project: A });
  check('aside: a terminal named for this project that is really another chat -> nothing typed', !chat.sent.length && /could not confirm/.test(pnote() || ''), pnote());
  await reset(); openChat();
  for (const m of [{ type: 'ask', op: 'aside', project: 'nope' }, { type: 'ask', op: 'aside', project: '../' + A }, { type: 'ask', op: 'aside', project: '__proto__' }, { type: 'ask', op: 'aside', project: [A] }, { type: 'ask', op: 'aside' }, { type: 'ask', op: 'ASIDE', project: A }, { type: 'ask', project: A }, { type: 'ask', op: ['aside'], project: A }, { type: 'ask', op: 'aside', project: A.repeat(60) }]) { await send(m); }
  check('aside: unknown / hostile / malformed messages type nothing', !chat.sent.length && !created.length);
  try { module.handler(null); module.handler('ask'); module.handler({ type: 'ask' }); await wait(100); check('ask: null / string / bare messages do not crash', true); } catch (e) { check('ask: null / string / bare messages do not crash', false, e.message); }

  // ---- Ask inbox: type
  await reset();
  await send({ type: 'ask', op: 'type', q: 'What is a monad?' });
  check('inbox: the command is typed in one owner terminal WITHOUT Enter, in the ask project folder', created.length === 1 && created[0].sent.length === 1 && created[0].sent[0][1] === false && created[0].opts.cwd === askDir, JSON.stringify(created.map(t => [t.sent, t.opts])));
  check('inbox: the typed line is exactly the quoted argv (<Shipmiracle> ask --inbox <question>)', created[0].sent[0][0] === C.joinCmds([[path.join(WSD, 'bin', 'shipm'), 'ask', '--inbox', 'What is a monad?']]), created[0].sent[0][0]);
  check('inbox: the panel never executes `shipm ask` itself (no execFile of it)', noShipmiracleAsk(), JSON.stringify(execs));
  for (const q of hostile.slice(0, 7)) { await reset(); await send({ type: 'ask', op: 'type', q }); const got = created[0] && roundTrip(['ignored']) && created[0].sent[0][0];
    const o = spawnSync('/bin/sh', ['-c', 'f() { for a in "$@"; do printf "%s\\0" "$a"; done; }; f ' + (got || '')], { encoding: 'utf8' }); const args = o.stdout.split('\0').slice(0, -1);
    check('inbox: hostile question ' + JSON.stringify(q).slice(0, 40) + ' -> one typed argument, Enter not pressed, nothing runs', !!got && created[0].sent[0][1] === false && args.length === 4 && args[3] === q && !fs.existsSync(PWN), JSON.stringify(args)); }
  // two clicks in a row reuse ONE terminal: each line is preceded by Ctrl-U (clear the prompt line) and neither is submitted, so the two never run together
  await reset(); await send({ type: 'ask', op: 'type', q: 'first question' }); await send({ type: 'ask', op: 'type', q: 'second question' });
  const raw = created[0] ? created[0].raw : [];
  check('inbox: two successive Ask clicks reuse one terminal and never concatenate: [Ctrl-U, line 1, Ctrl-U, line 2], no Enter anywhere', created.length === 1 && raw.length === 4 && raw[0][0] === '\u0015' && raw[2][0] === '\u0015' && /first question/.test(raw[1][0]) && /second question/.test(raw[3][0]) && raw.every(r => r[1] === false), JSON.stringify(raw));
  await reset(); await send({ type: 'ask', op: 'type', q: 'ما هو الفرق بين git و GitHub؟' });
  check('inbox: an Arabic question is typed unchanged', created.length === 1 && created[0].sent[0][0].includes("'ما هو الفرق بين git و GitHub؟'"), JSON.stringify(created.map(t => t.sent)));
  for (const [label, q, re] of [['a newline', 'a\nb', /one line/], ['a long question', 'a'.repeat(2001), /longer than 2000/], ['a leading dash', '-x', /start the question/], ['an empty question', '   ', /Type a question/], ['a control character', 'a\u001bb', /control/], ['a non-string', { toString: () => 'x' }, /Type a question/]]) {
    await reset(); await send({ type: 'ask', op: 'type', q }); check('inbox: ' + label + ' is refused, nothing typed, owner told', !created.length && re.test(pnote() || ''), pnote()); }
  await reset(() => [mk('z' + ctr)]); await send({ type: 'ask', op: 'type', q: 'hello' });
  check('inbox: without an ask project in the data nothing is typed (Setup row Ask inbox is the entry)', !created.length && /not set up/.test(pnote() || ''), pnote());
  await reset(() => [mk('ask', { ask: { inbox: 'yes' } })]); await send({ type: 'ask', op: 'type', q: 'hello' });
  check('inbox: a project that merely is called ask but whose data lacks inbox:true is not used', !created.length);
  await reset(); await send({ type: 'ask', op: 'type', q: 'one' }); await send({ type: 'ask', op: 'type', q: 'two' });
  check('inbox: a second question reuses the same terminal (second line typed, still no Enter)', created.length === 1 && created[0].sent.length === 2 && created[0].sent.every(s => s[1] === false));

  // ---- Open / Promote
  await reset(); await send({ type: 'ask', op: 'open', path: '/etc/passwd', project: 'ask' });
  check('open: opens the last note from the panel data, never a path the page sent', opened.length === 1 && opened[0] === fs.realpathSync(path.join(askDir, 'docs', 'notes', NOTE)), JSON.stringify(opened));
  await reset(() => [mk('ask', { ask: { inbox: true, questions_today: 1, notes: 1, last: { title: 't', path: '../../etc/passwd', ts: 1 } } })]); await send({ type: 'ask', op: 'open' });
  check('open: a note path that leaves docs/notes in the data is refused with a reason', !opened.length && /Not opened/.test(pnote() || ''), pnote());
  const link = '2026-10-21-sym.md'; fs.symlinkSync(path.join(tmp, 'secret.md'), path.join(askDir, 'docs', 'notes', link));
  await reset(() => [mk('ask', { ask: { inbox: true, questions_today: 1, notes: 1, last: { title: 't', path: 'docs/notes/' + link, ts: 1 } } })]); await send({ type: 'ask', op: 'open' }); const o1 = opened.length; await send({ type: 'ask', op: 'promote' });
  check('open / promote: a symlinked note is refused for both', o1 === 0 && !created.length && /Not opened/.test(pnote() || ''), pnote());
  await reset(() => [askP({ last: null })]); await send({ type: 'ask', op: 'open' }); await send({ type: 'ask', op: 'promote' });
  check('open / promote: with no last note nothing happens', !opened.length && !created.length);
  await reset(); await send({ type: 'ask', op: 'promote', note: '../../x.md', path: 'x' });
  check('promote: types `shipm ask promote <note>` WITHOUT Enter; the note name comes from the panel data, a page-sent name is ignored', created.length === 1 && created[0].sent.length === 1 && created[0].sent[0][1] === false
    && created[0].sent[0][0] === C.joinCmds([[path.join(WSD, 'bin', 'shipm'), 'ask', 'promote', NOTE]]), JSON.stringify(created.map(t => t.sent)));
  check('promote: nothing is executed by the panel', noShipmiracleAsk());

  // ---- Remote Control Undo (Setup)
  rowsAnswer = JSON.stringify({ v: 1, ready: true, rows: F3.ROWS({ 'remote-control': 'green' }) });
  await reset(); remote = { state: 'on' }; await send({ type: 'setup', op: 'recheck' }); await wait(300); await refreshed(); created.length = 0; terms.length = 0;
  await send({ type: 'setup', op: 'undo', id: 'remote-control' });
  check('undo: runs `shipm init --undo remote-control` in the terminal (Enter sent, since 31 Oct 2026) when Remote Control is on', created.length === 1 && created[0].sent.length === 1 && created[0].sent[0][1] === true && created[0].sent[0][0] === C.joinCmds([[path.join(WSD, 'bin', 'shipm'), 'init', '--undo', 'remote-control']]), JSON.stringify(created.map(t => t.sent)));
  check('undo: the panel does not run init and never touches settings.json', !execs.some(e => (e[1] || []).includes('--undo')) && !/settings\.json/.test(JSON.stringify(created.map(t => t.sent))));
  await reset(); created.length = 0; remote = { state: 'off' }; rowsAnswer = JSON.stringify({ v: 1, ready: true, rows: F3.ROWS({ 'remote-control': 'skipped' }) }); await send({ type: 'setup', op: 'recheck' }); await wait(300); await refreshed();
  created.length = 0; await send({ type: 'setup', op: 'undo', id: 'remote-control' }); await send({ type: 'setup', op: 'undo', id: 'git-id' });
  check('undo: when Remote Control is off nothing is typed; other ids are never accepted', !created.length);


  // ---------- 6. data.js: `shipm report panel` remote + ask fields (fake Shipmiracle in a temp engine folder; nothing real runs) ----------
  {
    const ws2 = path.join(tmp, 'ws2'), dev2 = path.join(tmp, 'dev2'), st2 = path.join(tmp, 'st2'); for (const d of [path.join(ws2, 'bin'), path.join(ws2, 'config'), st2, path.join(dev2, 'ask', '.shipmiracle'), path.join(dev2, 'plain', '.shipmiracle'), path.join(dev2, 'bogus', '.shipmiracle')]) fs.mkdirSync(d, { recursive: true });
    for (const nm of ['ask', 'plain', 'bogus']) { fs.mkdirSync(path.join(dev2, nm, '.git'), { recursive: true }); }
    const answers = { ask: { v: 1, playbook: null, cr: [], remote: { state: 'on' }, ask: { inbox: true, questions_today: 4, notes: 2, last: { title: 'T\u0007itle', path: 'docs/notes/' + NOTE, ts: 5 } } }, plain: { v: 1, playbook: null, cr: [], remote: { state: 'on' } }, bogus: { v: 1, playbook: null, cr: [], remote: { state: 'maybe' }, ask: { inbox: 'yes', questions_today: 'x' } } };
    fs.writeFileSync(path.join(ws2, 'answers.json'), JSON.stringify(answers));
    fs.writeFileSync(path.join(ws2, 'bin', 'shipm'), '#!/usr/bin/env node\nconst a = require(__dirname + "/../answers.json"); const i = process.argv.indexOf("--project"); const n = require("path").basename(process.argv[i + 1]); console.log(JSON.stringify(a[n] || {}));\n', { mode: 0o755 });
    const run = () => spawnSync(process.execPath, ['-e', "require('./vscode-ext/shipmiracle-panel/data.js').collect().then(d => console.log(JSON.stringify({ remote: d.remote, ps: d.projects.map(p => [p.name, p.ask || null]) })))"], { cwd: path.join(__dirname, '..'), encoding: 'utf8', timeout: 60000, env: { ...process.env, SHIPMIRACLE_TEST: '1', SHIPMIRACLE_EXT_STATE: st2, SHIPMIRACLE_EXT_WS: ws2, SHIPMIRACLE_EXT_DEV: dev2 } });
    const o = run(); let j = null; try { j = JSON.parse(o.stdout.trim().split('\n').pop()); } catch (e) { /* reported below */ }
    const by = n => j && Object.fromEntries(j.ps)[n];
    check('data: collect() carries remote.state from `shipm report panel` (on/off only, anything else = unknown)', !!j && ['on', 'unknown'].includes(j.remote.state), (o.stderr || '') + o.stdout.slice(0, 300));
    check('data: the ask project gets p.ask {inbox, questions_today, notes, last} with the title cleaned of control characters; other projects have none; a bogus ask block (inbox "yes") is dropped', !!j && by('ask') && by('ask').inbox === true && by('ask').questions_today === 4 && by('ask').notes === 2 && by('ask').last.path === 'docs/notes/' + NOTE && !/\u0007/.test(by('ask').last.title) && by('plain') === null && by('bogus') === null, JSON.stringify(j));
  }
  const src = fs.readFileSync(path.join(__dirname, '../vscode-ext/shipmiracle-panel/extension.js'), 'utf8');
  const fn = src.slice(src.indexOf('async function askAction'), src.indexOf('// ---- Handoff + fresh chat'));
  check('source: askAction sends to a chat only the constant ASIDE_TEXT with Enter=false, and never calls exec / spawn / dispose / sendText(…, true)', (fn.match(/sendText\(([^)]*)\)/g) || []).join() === 'sendText(ASK.ASIDE_TEXT, false)' && !/\bexec(File)?\(|spawn|\.dispose\(\)/.test(fn));
  fs.rmSync(tmp, { recursive: true, force: true });
  console.log(`\n${n - fails}/${n} passed`); process.exit(fails ? 1 : 0);
})().catch(e => { console.log('FAIL crashed ' + e.stack); process.exit(1); });
