// F5 Toolbox and F6 Describe your work, extension side and the mirror reader (acceptance 13, 15-17): only prefilled terminal lines (no Enter), checked against the CLI's capability flags and the
// project's own data; the page can name an asset only from the CLI's list; interview.js reads the progress and draft files read-only (symlink, oversize, junk refused; a dead pid = paused).
// Run: node tests/ext_f56_test.js
require('./shipmiracle_isolation').apply();
const Module = require('module'), path = require('path'), fs = require('fs'), os = require('os');
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'shipmiracle-f56-'));
const ST = path.join(tmp, 'state'), WSD = path.join(tmp, 'ws'), DEV = path.join(tmp, 'Dev'), PD = path.join(DEV, 'demo');
for (const d of [ST, path.join(WSD, 'config'), path.join(PD, '.shipmiracle')]) fs.mkdirSync(d, { recursive: true });
Object.assign(process.env, { SHIPMIRACLE_TEST: '1', SHIPMIRACLE_EXT_STATE: ST, SHIPMIRACLE_EXT_WS: WSD, SHIPMIRACLE_EXT_DEV: DEV, SHIPMIRACLE_DIAG_DIR: path.join(tmp, 'diag'), SHIPMIRACLE_HEAL_MS: '99999999' });
let fails = 0; const check = (n, c, info = '') => { console.log((c ? 'PASS ' : 'FAIL ') + n + (c ? '' : ' ' + info)); if (!c) fails++; };
const wait = ms => new Promise(r => setTimeout(r, ms));
const IV = require(path.join(__dirname, '../vscode-ext/shipmiracle-panel/interview.js'));
const progress = (o = {}) => ({ v: 1, project: 'demo', mode: 'short', status: 'asking', n: 2, total: 3, question: { id: 'q2', topic: 'inputs', text: 'What goes in?', recommended: 'A CSV' }, answered: [], assumed: [{ id: 'q1', topic: 'work', text: 'a web page' }], prototype: [{ id: 'q9', text: 'look' }], updated: 1700000000, pid: process.pid, ...o });
const wp = (o) => fs.writeFileSync(path.join(PD, '.shipmiracle', 'playbook.interview.json'), JSON.stringify(progress(o)));
const NINE = ['Work', 'Inputs', 'Outputs', 'Tools', 'Risks', 'Who approves', 'Definition of done', 'Never allowed', 'Assumed'];
const draft = (labels = NINE) => '# Draft playbook (not trusted)\n\nProject: demo\n\n' + labels.map(l => `## ${l}\n\n- ${l} answer one\n- second <b>bold</b> [link](http://evil.example)\n`).join('\n');
const wd = t => fs.writeFileSync(path.join(PD, '.shipmiracle', 'playbook.draft.md'), t);

(async () => {
  // ---- interview.js
  wp(); let r = IV.readProgress(PD);
  check('progress: status asking while the process is alive, with question, assumed and prototype text', r && r.status === 'asking' && r.n === 2 && r.total === 3 && r.question.text === 'What goes in?' && r.assumed[0] === 'a web page' && r.prototype[0] === 'look', JSON.stringify(r));
  wp({ pid: 2147483000 }); check('a dead pid turns asking into paused (the terminal closed)', IV.readProgress(PD).status === 'paused');
  wp({ pid: 0 }); check('no pid: paused', IV.readProgress(PD).status === 'paused');
  wp({ status: 'draft', pid: 0 }); check('a finished draft stays draft (not paused)', IV.readProgress(PD).status === 'draft');
  for (const bad of [{ v: 2 }, { status: 'weird' }, { mode: 'huge' }]) { wp(bad); check('progress refused: ' + JSON.stringify(bad), IV.readProgress(PD) === null); }
  fs.writeFileSync(path.join(PD, '.shipmiracle', 'playbook.interview.json'), '{junk'); check('progress: junk is no interview', IV.readProgress(PD) === null);
  fs.rmSync(path.join(PD, '.shipmiracle', 'playbook.interview.json')); fs.symlinkSync(path.join(tmp, 'x.json'), path.join(PD, '.shipmiracle', 'playbook.interview.json')); fs.writeFileSync(path.join(tmp, 'x.json'), JSON.stringify(progress()));
  check('progress: a symlink is never followed', IV.readProgress(PD) === null); fs.rmSync(path.join(PD, '.shipmiracle', 'playbook.interview.json'));
  wp({ question: { text: 'q'.repeat(500) + '‮', recommended: 'r' } }); check('progress text is cleaned and cut (200)', IV.readProgress(PD).question.text.length <= 201 && !/‮/.test(IV.readProgress(PD).question.text));
  wd(draft()); let d = IV.readDraft(PD);
  check('draft: nine labelled rows in order, bullets joined, markup kept as text', d.ok && d.rows.map(x => x.label).join() === NINE.join() && d.rows[0].text === 'Work answer one · second <b>bold</b> [link](http://evil.example)');
  wd(draft(NINE.slice(0, 8))); check('draft: a missing section = not ok (incomplete)', IV.readDraft(PD).ok === false);
  wd('x'.repeat(41 * 1024)); check('draft: over 40 KB = not ok', IV.readDraft(PD).ok === false);
  fs.rmSync(path.join(PD, '.shipmiracle', 'playbook.draft.md')); fs.symlinkSync(path.join(tmp, 'x.json'), path.join(PD, '.shipmiracle', 'playbook.draft.md'));
  check('draft: a symlink is not ok and not an openable file', IV.readDraft(PD).ok === false && IV.draftFile(PD) === ''); fs.rmSync(path.join(PD, '.shipmiracle', 'playbook.draft.md'));
  wp({ status: 'draft', pid: 0 }); wd(draft()); const mm = IV.mirrorOf(PD, 'draft'); check('mirrorOf: draft with rows', mm.status === 'draft' && mm.draftOk && mm.rows.length === 9);
  check('mirrorOf: done or no CLI status = nothing', IV.mirrorOf(PD, 'done') === null && IV.mirrorOf(PD, null) === null);

  // ---- extension
  const sent = [], made = [], opened = [], infos = []; let CAPS = { toolbox: true, interview: true };
  const proxy = () => new Proxy(function () {}, { get: (t, k) => k === 'then' ? undefined : (k === 'dispose' ? () => {} : proxy()), apply: () => proxy() });
  const vscode = new Proxy({}, { get: (t, k) => {
    if (k === 'window') return new Proxy({}, { get: (w, kk) => {
      if (kk === 'terminals') return made; if (kk === 'showTextDocument') return async dd => { opened.push(dd.uri.fsPath); };
      if (kk === 'registerWebviewViewProvider') return (id, prov) => { module.provider = prov; return { dispose() {} }; };
      if (kk === 'createTerminal') return o => { const tt = { name: o.name, exitStatus: undefined, show() { tt.shown = true; }, sendText: (x, nl) => sent.push([x, nl]), dispose() {} }; made.push(tt); return tt; };
      return proxy(); } });
    if (k === 'workspace') return new Proxy({}, { get: (w, kk) => kk === 'getConfiguration' ? () => ({ get: () => undefined }) : kk === 'openTextDocument' ? async u => ({ uri: u }) : proxy() });
    if (k === 'commands') return { registerCommand: (id, f) => { module.cmds = module.cmds || {}; module.cmds[id] = f; return { dispose() {} }; }, executeCommand: async () => {} };
    if (k === 'Uri') return { parse: s => ({ s }), file: f => ({ fsPath: f }) };
    if (k === 'ThemeIcon' || k === 'ThemeColor') return function (n) { this.n = n; };
    if (k === 'ViewColumn') return { Active: 1 }; if (k === 'StatusBarAlignment') return { Left: 1 };
    return proxy(); } });
  const assets = [{ path: 'scripts/seed.py', stage: 'do', stageLabel: 'Build', purpose: 'Seeds "data"; rm -rf ~ $(x)', status: 'ok' }, { path: 'docs/a.md', stage: 'verify', stageLabel: 'Test', purpose: 'Checklist', status: 'changed' }];
  const mk = (name, o = {}) => ({ name, dir: path.join(DEV, name), stack: 'web', state: 'idle', agents: [], tokens: { claudeDay: 0, claudeWeek: 0 }, ideas: { open: [], evaluated: [], done: 0, dropped: 0 }, held: false, cr: null, flow: null, next: '', lastCommit: 0, dirty: 0, health: [], playbook: null, ...o });
  for (const n of ['demo', 'busy', 'plain']) fs.mkdirSync(path.join(DEV, n), { recursive: true });
  const W = { projects: [mk('demo', { playbook: { type: 'software', level: 'strict', autopilot: 'guided' }, toolbox: { count: 2, changed: 1, assets } }), mk('busy', { state: 'working', playbook: { type: 'software', level: 'strict', autopilot: 'guided' }, toolbox: { count: 2, changed: 1, assets } }),
    mk('plain', { mirror: { status: 'paused', mode: 'short', n: 2, total: 3, question: null, assumed: [], prototype: [], draftOk: false, rows: [], updated: 1 } })] };
  const real = Module._load;
  Module._load = function (req, parent, ...rest) {
    if (req === 'vscode') return vscode;
    if (req === 'child_process') return { execFile: (cmd, args, o, cb) => { (cb || o)(null, '', ''); return {}; } };
    if (req === './data') return { collect: async () => ({ projects: W.projects.map(p => ({ ...p })), plan: {}, guard: {}, ask: null, capabilities: CAPS }) };
    return real.call(this, req, parent, ...rest); };
  const ext = require(path.join(__dirname, '../vscode-ext/shipmiracle-panel/extension.js'));
  ext.activate({ subscriptions: [], globalState: { get() {}, update() {} } }); await wait(300);
  let handler; const view = { webview: { options: {}, set html(v) {}, get html() { return ''; }, onDidReceiveMessage: f => { handler = f; return { dispose() {} }; } }, visible: true, onDidChangeVisibility: () => ({ dispose() {} }), onDidDispose: () => ({ dispose() {} }) };
  module.provider.resolveWebviewView(view); await wait(500);
  const send = async m => { sent.length = 0; opened.length = 0; await handler(m); await wait(80); };
  const line = () => (sent.find(x => x[1] === false && x[0] !== '\u0015') || [''])[0];
  const never = () => sent.every(x => x[1] === false);

  await send({ type: 'toolbox', op: 'remove', project: 'demo', path: 'scripts/seed.py' });
  check('Copy remove command types `shipm playbook asset remove <path> --project demo` (quoted argv), no Enter', /^'[^']*\/bin\/shipm' 'playbook' 'asset' 'remove' 'scripts\/seed\.py' '--project' 'demo'$/.test(line()) && never(), JSON.stringify(sent));
  await send({ type: 'toolbox', op: 'resign', project: 'demo', path: 'scripts/seed.py' });
  check('Re-sign types `asset add <path> --stage do --purpose \'…\'` with the purpose single-quoted (a hostile purpose cannot become shell syntax)', line().includes("'asset' 'add' 'scripts/seed.py' '--stage' 'do' '--purpose' 'Seeds \"data\"; rm -rf ~ $(x)' '--project' 'demo'") && never(), line());
  await send({ type: 'toolbox', op: 'add', project: 'demo' });
  check('Add an asset… types `asset add  --stage  --purpose "" --project demo` and moves the cursor left to the path (escape sequence, no Enter)', /playbook asset add  --stage  --purpose "" --project 'demo'$/.test(line()) && sent.some(x => /^(\u001b\[D)+$/.test(x[0]) && x[1] === false) && never(), JSON.stringify(sent));
  const left = sent.find(x => /^(\u001b\[D)+$/.test(x[0])); check('the cursor goes back exactly over the part after the path (` --stage  --purpose "" --project \'demo\'`)', left && left[0].length / 3 === ` --stage  --purpose "" --project 'demo'`.length, left && String(left[0].length / 3));
  for (const bad of [{ op: 'remove', project: 'demo', path: '/etc/passwd' }, { op: 'remove', project: 'demo', path: '../x' }, { op: 'remove', project: 'demo', path: '' }, { op: 'wipe', project: 'demo', path: 'scripts/seed.py' }, { op: 'remove', project: 'nope', path: 'scripts/seed.py' }, { op: 'remove', project: 'plain', path: 'scripts/seed.py' }, { op: 'remove', project: 'demo', path: 5 }]) { await send({ type: 'toolbox', ...bad }); check('toolbox refused: ' + JSON.stringify(bad).slice(0, 60), sent.length === 0); }
  await send({ type: 'toolbox', op: 'remove', project: 'busy', path: 'scripts/seed.py' }); check('a project whose session is running: nothing typed', sent.length === 0);

  await send({ type: 'describe', op: 'start', project: 'plain', mode: 'short' });
  check('Start (Short) types `shipm playbook interview --short --project plain`, no Enter', /'playbook' 'interview' '--short' '--project' 'plain'$/.test(line()) && never(), JSON.stringify(sent));
  await send({ type: 'describe', op: 'start', project: 'plain', mode: 'long' }); check('Start (Long) types --long', /'--long' '--project' 'plain'$/.test(line()));
  await send({ type: 'describe', op: 'start', project: 'plain', mode: 'huge' }); check('an unknown mode is refused', sent.length === 0);
  await send({ type: 'describe', op: 'start', project: 'demo', mode: 'short' }); check('Start on a project that has a playbook: refused', sent.length === 0);
  await send({ type: 'describe', op: 'resume', project: 'plain' }); check('Resume types `--resume --project plain`', /'interview' '--resume' '--project' 'plain'$/.test(line()) && never());
  await send({ type: 'describe', op: 'restart', project: 'plain' }); check('Start over types `--restart --project plain`', /'interview' '--restart' '--project' 'plain'$/.test(line()) && never());
  await send({ type: 'describe', op: 'set', project: 'plain' }); check('Copy set command is refused while no readable draft is waiting', sent.length === 0);
  W.projects[2].mirror = { status: 'draft', mode: 'short', n: 3, total: 3, question: null, assumed: [], prototype: [], draftOk: true, rows: [], updated: 1 }; await module.cmds['shipmiracle.refresh'](); await wait(100);
  await send({ type: 'describe', op: 'set', project: 'plain' }); check('with a draft waiting: Copy set command types `shipm playbook set --from-draft --project plain --allow-open-chat`, no Enter', /'playbook' 'set' '--from-draft' '--project' 'plain' '--allow-open-chat'$/.test(line()) && never(), JSON.stringify(sent));
  fs.mkdirSync(path.join(DEV, 'plain', '.shipmiracle'), { recursive: true }); fs.writeFileSync(path.join(DEV, 'plain', '.shipmiracle', 'playbook.draft.md'), draft());
  await send({ type: 'describe', op: 'open', project: 'plain' }); check('Open draft opens exactly <project>/.shipmiracle/playbook.draft.md', opened.length === 1 && opened[0].endsWith(path.join('plain', '.shipmiracle', 'playbook.draft.md')), JSON.stringify(opened));
  fs.rmSync(path.join(DEV, 'plain', '.shipmiracle', 'playbook.draft.md')); fs.symlinkSync(path.join(tmp, 'x.json'), path.join(DEV, 'plain', '.shipmiracle', 'playbook.draft.md'));
  await send({ type: 'describe', op: 'open', project: 'plain' }); check('Open draft on a symlink opens nothing', opened.length === 0);
  for (const bad of [{ op: 'start', project: '--evil', mode: 'short' }, { op: 'show', project: 5 }, { op: 'format', project: 'plain' }]) { await send({ type: 'describe', ...bad }); check('describe refused: ' + JSON.stringify(bad), sent.length === 0 && opened.length === 0); }
  CAPS = { toolbox: false, interview: false }; await module.cmds['shipmiracle.refresh'](); await wait(100);
  await send({ type: 'describe', op: 'start', project: 'plain', mode: 'short' }); const a1 = sent.length; await send({ type: 'toolbox', op: 'add', project: 'demo' });
  check('capability flags false: neither route types anything', a1 === 0 && sent.length === 0);
  console.log(fails ? `\nFAILED: ${fails}` : '\nALL PASS'); fs.rmSync(tmp, { recursive: true, force: true }); process.exit(fails ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
