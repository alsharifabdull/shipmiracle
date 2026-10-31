// The panel's Ideas buttons against a stand-in for VS Code: does each action run bin/idea with the right arguments (no shell), and open the right chat?
// Run: node tests/ext_ideas_test.js
require('./shipmiracle_isolation').apply();   // test isolation: fresh HOME/SHIPMIRACLE_HOME/CONFIG/STATE unless already temp
const Module = require('module'); const path = require('path'); const fs = require('fs'), os = require('os');
const ST = fs.mkdtempSync(path.join(os.tmpdir(), 'shipmiracle-ideas-st-')); process.env.SHIPMIRACLE_TEST = '1'; process.env.SHIPMIRACLE_EXT_STATE = ST;   // the panel writes chat-fresh / chat-prompt files here
const launch = o => { const a = o.shellArgs || []; return { ok: o.shellPath === '/bin/bash' && (a.length === 4 || a.length === 5) && a[0] === '-p' && /\/bin\/shipm-chat$/.test(a[1]) && /^[0-9a-f]{16}$/.test(a[3]) && (a.length === 4 || /^[0-9a-f]{32}$/.test(a[4])), name: a[2], nonce: a[3], hash: a[4] }; };
const stfile = (kind, term) => { const l = launch(term.opts); try { return fs.readFileSync(path.join(ST, 'chat-' + kind + '.' + l.name + '.' + l.nonce), 'utf8'); } catch (e) { return null; } };
const calls = [], terms = [], msgs = [], opened = [], external = [], docs = [], cmds = []; let answers = { pick: null, input: 'My new idea #x', warn: 'Drop' };
const proxy = () => new Proxy(function () {}, { get: (t, k) => k === 'then' ? undefined : (k === 'dispose' ? () => {} : proxy()), apply: () => proxy() });
const term = (o) => ({ name: o.name, opts: o, exitStatus: undefined, shown: 0, sent: [], show() { this.shown++; }, sendText(t, nl) { this.sent.push([t, nl]); }, processId: Promise.resolve(1) });
const projects = [
  { name: 'sample-app', dir: '/d/sample-app', stack: 'ios', state: 'calm', agents: [], tokens: {}, ideas: { open: [{ id: 'F1', text: 'a', tags: [], verdict: '' }, { id: 'F2', text: 'b', tags: [], verdict: '' }], evaluated: [], done: 0, dropped: 0 }, held: false },
  { name: 'gate', dir: '/d/gate', stack: 'web', state: 'working', agents: [], tokens: {}, ideas: { open: [], evaluated: [], done: 0, dropped: 0 }, held: true },
  { name: 'busy', dir: '/d/busy', stack: 'web', state: 'working', agents: [], tokens: {}, ideas: { open: [{ id: 'F1', text: 'z', tags: [], verdict: '' }], evaluated: [], done: 0, dropped: 0 }, held: false },
  { name: 'ideas', dir: '/d/ideas', stack: 'notes', special: 'ideas', state: 'idle', agents: [], tokens: {}, ideas: { open: [], evaluated: [], done: 0, dropped: 0 }, held: false },
];
const vscode = new Proxy({}, { get: (t, k) => {
  if (k === 'window') return new Proxy({}, { get: (w, kk) => {
    if (kk === 'terminals') return terms;
    if (kk === 'createTerminal') return o => { const x = term(o); terms.push(x); return x; };
    if (kk === 'showQuickPick') return async items => answers.pick ? items.find(i => i.name === answers.pick) : items[0];
    if (kk === 'showInputBox') return async () => answers.input;
    if (kk === 'showWarningMessage') return async () => answers.warn;
    if (kk === 'showInformationMessage' || kk === 'showErrorMessage') return async (m, ...btns) => { msgs.push(m); return answers.info && btns.includes(answers.info) ? answers.info : undefined; };
    if (kk === 'registerWebviewViewProvider') return (id, prov) => { module.provider = prov; return { dispose() {} }; };
    if (kk === 'activeTerminal') return undefined;
    if (kk === 'showTextDocument') return async d => { docs.push('show ' + d.doc); };
    return proxy(); } });
  if (k === 'env') return { openExternal: u => { external.push(u.s); return Promise.resolve(true); } };
  if (k === 'workspace') return { openTextDocument: u => { docs.push('open ' + u.fsPath); return Promise.resolve({ doc: u.fsPath }); } };
  if (k === 'Uri') return { parse: s => ({ s }), file: f => ({ fsPath: f }) };
  if (k === 'commands') return { registerCommand: () => ({ dispose() {} }), executeCommand: async c => { cmds.push(c); } };
  if (k === 'ThemeIcon' || k === 'ThemeColor') return function (n) { this.n = n; };
  if (k === 'ViewColumn') return { Active: 1 };
  if (k === 'StatusBarAlignment') return { Left: 1 };
  return proxy(); } });
const fakeExec = (cmd, args, opts, cb) => { if (cmd === '/bin/ps' || cmd === 'lsof') { (cb || opts)(null, '', ''); return; } calls.push(args.slice(1)); const out = args.includes('add') ? 'p: added F9' : args.includes('render') ? '/tmp/shipmiracle/away-decisions.md\n' : args.includes('eval-prompt') ? (global.__eval !== undefined ? global.__eval : 'EVAL PROMPT ' + args.slice(args.indexOf('eval-prompt') + 1).join(',')) : 'ok'; (cb || opts)(null, out, ''); };
const real = Module._load;
Module._load = function (req, parent, ...r) {
  if (req === 'vscode') return vscode;
  if (req === 'child_process') return { execFile: fakeExec };
  if (req === './data') return { collect: async () => ({ projects, plan: {}, guard: global.__guard || {}, ask: null }) };
  return real.call(this, req, parent, ...r); };
const ext = require(path.join(__dirname, '../vscode-ext/shipmiracle-panel/extension.js'));
let fails = 0; const check = (n, c, info = '') => { console.log((c ? 'PASS ' : 'FAIL ') + n + (c ? '' : ' ' + info)); if (!c) fails++; };
(async () => {
  ext.activate({ subscriptions: [], globalState: { get() {}, update() {} } });
  await new Promise(r => setTimeout(r, 400));
  let handler; const view = { webview: { options: {}, set html(v) {}, get html() { return ''; }, onDidReceiveMessage: f => { handler = f; return { dispose() {} }; } }, visible: true, onDidChangeVisibility: () => ({ dispose() {} }), onDidDispose: () => ({ dispose() {} }) };
  module.provider.resolveWebviewView(view); await new Promise(r => setTimeout(r, 300));
  const send = async m => { calls.length = 0; msgs.length = 0; await handler({ type: 'idea', ...m }); await new Promise(r => setTimeout(r, 120)); return calls.map(c => c.join(' ')); };
  const T = 'My new idea #x';
  check('add: runs idea add with the text and project taken from the tab (no VS Code pop-up)', JSON.stringify(await send({ op: 'add', project: 'sample-app', text: T })) === JSON.stringify(['-p sample-app add ' + T]));
  check('add to the Inbox', (await send({ op: 'add', project: 'ideas', text: T }))[0] === '-p ideas add ' + T);
  check('add with no text does nothing', (await send({ op: 'add', project: 'sample-app', text: '   ' })).length === 0);
  check('add to a held project does nothing', (await send({ op: 'add', project: 'gate', text: T })).length === 0);
  check('add to an unknown project does nothing', (await send({ op: 'add', project: '../x', text: T })).length === 0);
  check('long text is cut to 500 characters', (await send({ op: 'add', project: 'sample-app', text: 'a'.repeat(900) }))[0].length === ('-p sample-app add '.length + 500));
  check('done', JSON.stringify(await send({ op: 'done', project: 'sample-app', id: 'F2' })) === JSON.stringify(['-p sample-app done F2']));
  check('drop runs at once (the tab already asked "Sure?")', JSON.stringify(await send({ op: 'drop', project: 'sample-app', id: 'F2' })) === JSON.stringify(['-p sample-app drop F2']));
  check('move to the project chosen in the tab dropdown', JSON.stringify(await send({ op: 'move', project: 'sample-app', id: 'F1', to: 'ideas' })) === JSON.stringify(['-p sample-app move F1 --to ideas']));
  check('move without a target does nothing', (await send({ op: 'move', project: 'sample-app', id: 'F1' })).length === 0);
  check('move to itself or to a held project does nothing', (await send({ op: 'move', project: 'sample-app', id: 'F1', to: 'sample-app' })).length === 0 && (await send({ op: 'move', project: 'sample-app', id: 'F1', to: 'gate' })).length === 0);
  check('copy keeps the original (copy command, not move)', JSON.stringify(await send({ op: 'copy', project: 'sample-app', id: 'F1', to: 'ideas' })) === JSON.stringify(['-p sample-app copy F1 --to ideas']) && msgs.some(m => /Copied F1 to Inbox/.test(m)), JSON.stringify(msgs));
  check('moveto: the recommended project from the verdict button', JSON.stringify(await send({ op: 'moveto', project: 'sample-app', id: 'F1', to: 'busy' })) === JSON.stringify(['-p sample-app move F1 --to busy']));
  check('moveto to an unknown project is ignored', (await send({ op: 'moveto', project: 'sample-app', id: 'F1', to: '../x' })).length === 0);
  terms.length = 0; const ar = await send({ op: 'add', project: 'sample-app', text: T, review: true });
  check('"Add and check if it is worth it" adds and opens the review chat at once', ar.includes('-p sample-app add ' + T) && ar.includes('-p sample-app eval-prompt F9') && terms.length === 1 && /EVAL PROMPT F9/.test(stfile('prompt', terms[0]) || '') && !terms[0].opts.shellArgs.join(' ').includes('EVAL PROMPT'), JSON.stringify(ar) + terms.length);
  terms.length = 0; answers.info = 'Is it worth it? Review now'; const ar1 = await send({ op: 'add', project: 'sample-app', text: T }); answers.info = null;
  check('plain Add: accepting the "Review now" offer opens the review chat', ar1.includes('-p sample-app eval-prompt F9') && terms.length === 1, JSON.stringify(ar1) + terms.length);
  terms.length = 0; const ar2 = await send({ op: 'add', project: 'sample-app', text: T });
  check('plain Add: ignoring the offer opens nothing', terms.length === 0 && !ar2.some(c => c.includes('eval-prompt')) && msgs.some(m => /Added F9 to sample-app/.test(m)), JSON.stringify(ar2));
  cmds.length = 0; await handler({ type: 'cmd', name: 'newProject' }); await handler({ type: 'cmd', name: 'check' }); await handler({ type: 'cmd', name: 'rm -rf /' }); await handler({ type: 'cmd', name: 'shipmiracle.delete' });
  check('the tab buttons run New project and Check & update only (anything else is ignored)', JSON.stringify(cmds) === JSON.stringify(['shipmiracle.newProject', 'shipmiracle.check']), JSON.stringify(cmds));
  check('a bad id is ignored', (await send({ op: 'done', project: 'sample-app', id: 'F1; rm -rf /' })).length === 0);
  check('an unknown project is ignored', (await send({ op: 'done', project: '../etc', id: 'F1' })).length === 0);
  terms.length = 0; await send({ op: 'worth', project: 'sample-app', id: 'F1' });
  check('Worth it? opens that project chat; the evaluation prompt goes in the one-shot chat-prompt file, not in the args', terms.length === 1 && terms[0].name === 'sample-app · Claude' && !terms[0].opts.shellArgs.includes('--') && /EVAL PROMPT F1/.test(stfile('prompt', terms[0]) || '') && terms[0].opts.cwd === '/d/sample-app', JSON.stringify(terms[0] && terms[0].opts.shellArgs));
  const before = terms.length; await send({ op: 'worth', project: 'sample-app', id: 'F2' });
  check('chat already open and calm: Ctrl-U first, then the message, Enter left to the owner', terms.length === before && terms[0].sent.length === 2 && terms[0].sent[0][0] === '\u0015' && terms[0].sent[0][1] === false && /^\[panel\] EVAL PROMPT/.test(terms[0].sent[1][0]) && terms[0].sent[1][1] === false, JSON.stringify(terms[0].sent));
  terms.length = 0; await send({ op: 'worth', project: 'busy', id: 'F1' });
  check('busy project: new chat still starts the prompt', terms.length === 1);
  terms.push(term({ name: 'busy · Claude' })); const n = terms.length; await send({ op: 'worth', project: 'busy', id: 'F1' });
  check('open chat that is busy is never typed into', terms[n - 1].sent.length === 0 && msgs.some(m => /busy right now/.test(m)), JSON.stringify(msgs));
  const r = await send({ op: 'review', project: 'sample-app' }); check('review: prompt for all open ideas, then dismisses the ask', r.includes('-p sample-app eval-prompt F1 F2') && r.includes('dismiss'), JSON.stringify(r));
  check('later dismisses', JSON.stringify(await send({ op: 'later' })) === JSON.stringify(['dismiss']));
  check('never mutes the project', JSON.stringify(await send({ op: 'never', project: 'sample-app' })) === JSON.stringify(['never sample-app']));
  terms.length = 0; await send({ op: 'newproject', project: 'sample-app', id: 'F3' });
  check('Create project… opens the ideas chat', terms.length === 1 && terms[0].opts.cwd.endsWith('/Developer/ideas') && /^\[panel\] .*Create nothing until I tell you the name and type/.test(stfile('prompt', terms[0]) || ''));
  const ev = async m => { calls.length = 0; external.length = 0; docs.length = 0; await handler(m); await new Promise(r => setTimeout(r, 120)); };
  await ev({ type: 'ci', url: 'https://github.com/me/x/actions/runs/1' });
  check('ci chip opens a github.com run URL outside VS Code', JSON.stringify(external) === JSON.stringify(['https://github.com/me/x/actions/runs/1']), JSON.stringify(external));
  let leaked = [];
  for (const u of ['http://github.com/x', 'https://evil.example/https://github.com/', 'javascript:alert(1)', '', undefined, 5]) { await ev({ type: 'ci', url: u }); leaked = leaked.concat(external); }
  check('ci chip refuses non-GitHub and non-https URLs', leaked.length === 0, JSON.stringify(leaked));
  await ev({ type: 'away' });
  check('away row: render, open the markdown in the editor, then review (in that order)', JSON.stringify(calls.map(c => c[c.length - 1])) === JSON.stringify(['render', 'review']) && JSON.stringify(docs) === JSON.stringify(['open /tmp/shipmiracle/away-decisions.md', 'show /tmp/shipmiracle/away-decisions.md']), JSON.stringify(calls) + JSON.stringify(docs));
  check('every chat the panel opens runs bin/shipm-chat <name> under bash (the wrapper adds --model opusplan and --continue at each launch)', terms.length > 0 && terms.every(x => launch(x.opts).ok && launch(x.opts).name === x.name.replace(' · Claude', '')), JSON.stringify(terms.map(x => x.opts.shellArgs)));
  terms.length = 0; await send({ op: 'worth', project: 'busy', id: 'F1' });
  const fst = fs.statSync(path.join(ST, 'chat-prompt.busy.' + launch(terms[0].opts).nonce));
  check('the one-shot prompt file is private (mode 600) and named with the launch nonce', (fst.mode & 0o777) === 0o600, fst.mode.toString(8));
  check('every launch gets its own random nonce', (() => { const n = new Set(); for (const x of terms) n.add(launch(x.opts).nonce); return n.size === terms.length; })());
  const hs = terms[terms.length - 1]; terms.length = 0; await send({ op: 'worth', project: 'busy', id: 'F1' });
  const hl = launch(terms[0].opts), body = stfile('prompt', terms[0]);
  check('the prompt file is bound to the launch by a 32-hex sha256 argument of exactly its content', hl.ok && hl.hash === require('crypto').createHash('sha256').update(body).digest('hex').slice(0, 32) && terms[0].opts.shellArgs.length === 5, JSON.stringify(terms[0].opts.shellArgs));
  const nfiles = () => fs.readdirSync(ST).filter(f => /^chat-/.test(f)).length;
  for (const [label, val] of [['longer than 4000 characters', 'x'.repeat(4001)], ['containing a NUL', 'a\0b']]) {
    global.__eval = val; terms.length = 0; const n0 = nfiles(); await send({ op: 'worth', project: 'busy', id: 'F1' }); global.__eval = undefined;
    check('a prompt ' + label + ' is refused: no terminal, no file, a notice', terms.length === 0 && nfiles() === n0 && msgs.some(m => /^Chat not opened: the launch instruction could not be saved/.test(m)) || (terms.length === 0 && nfiles() === n0 && (() => { try { return /could not be saved/.test(JSON.parse(fs.readFileSync(path.join(ST, 'project-notice.json'), 'utf8')).text); } catch (e) { return false; } })()), JSON.stringify([terms.length, msgs, nfiles() - n0, fs.existsSync(path.join(ST, 'project-notice.json'))]));
  }
  global.__eval = 'x'.repeat(4000 - require('../vscode-ext/shipmiracle-panel/strings.js').panelMarker.length); terms.length = 0; await send({ op: 'worth', project: 'busy', id: 'F1' }); global.__eval = undefined;
  check('a prompt of exactly 4000 characters is accepted', terms.length === 1);
  const argsFor = async proj => { terms.length = 0; await send({ op: 'worth', project: proj, id: 'F1' }); return terms[0] && terms[0].opts.shellArgs; };
  const aa = await argsFor('sample-app'), ab = await argsFor('busy');
  check('launch args never depend on history (no --continue, no model flags: the wrapper decides at each launch)', aa && ab && !aa.includes('--continue') && aa.slice(0, 2).join() === ab.slice(0, 2).join() && aa[2] === 'sample-app' && ab[2] === 'busy' && aa.length === ab.length, JSON.stringify([aa, ab]));
  global.__guard = { on: true, running: false }; calls.length = 0;
  for (let k = 0; k < 4; k++) { await handler({ type: 'guard' }); await new Promise(r => setTimeout(r, 700)); }
  check('watchdog: guard on but not running -> loads it again (shipm-guard install), only once within 5 minutes', calls.filter(c => c.join(' ') === 'install').length === 1, JSON.stringify(calls));
  global.__guard = { on: false, running: false }; calls.length = 0; await handler({ type: 'guard' }); await new Promise(r => setTimeout(r, 700));
  check('watchdog: guard switched off by the owner -> left alone', !calls.some(c => c.join(' ') === 'install'));
  console.log(fails ? '\nFAILED: ' + fails : '\nALL PASS'); process.exit(fails ? 1 : 0);
})().catch(e => { console.error('test crashed:', e); process.exit(2); });
