// "Activate agent..." (extension.js) against a stand-in for VS Code and a fake `shipm`: project known-list, name regex, path traversal, the QuickPick
// list (drafts + untrusted), exact argv (no shell), result shown as the panel notice. Run: node tests/ext_activate_test.js
require('./shipmiracle_isolation').apply();   // test isolation: fresh HOME/SHIPMIRACLE_HOME/CONFIG/STATE unless already temp
const Module = require('module'); const path = require('path'); const fs = require('fs'); const os = require('os');
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'shipmiracle-act-'));
const ST = path.join(tmp, 'state'), WSD = path.join(tmp, 'ws'), DEV = path.join(tmp, 'Dev');
for (const d of [ST, WSD, DEV]) fs.mkdirSync(d, { recursive: true });
Object.assign(process.env, { SHIPMIRACLE_TEST: '1', SHIPMIRACLE_EXT_STATE: ST, SHIPMIRACLE_EXT_WS: WSD, SHIPMIRACLE_EXT_DEV: DEV, SHIPMIRACLE_DIAG_DIR: path.join(tmp, 'diag'), SHIPMIRACLE_HEAL_MS: '99999999' });
const cmds = {}; let events = [], warns = [], warnAnswers = [], projects = [], runs = [], picks = [], pickAnswer = null, failWith = null, outText = 'activated qa-reviewer in proj (test, abcdef012345)';
const mk = (name, extra = {}) => ({ name, dir: path.join(DEV, name), stack: 'web', state: 'idle', agents: [], tokens: {}, ideas: { open: [], evaluated: [], done: 0, dropped: 0 }, held: false, ...extra });
const proxy = () => new Proxy(function () {}, { get: (t, k) => k === 'then' ? undefined : (k === 'dispose' ? () => {} : proxy()), apply: () => proxy() });
const vscode = new Proxy({}, { get: (t, k) => {
  if (k === 'window') return new Proxy({}, { get: (w, kk) => {
    if (kk === 'terminals') return [];
    if (kk === 'registerWebviewViewProvider') return (id, prov) => { module.provider = prov; return { dispose() {} }; };
    if (kk === 'activeTerminal') return undefined;
    if (kk === 'showTextDocument') return async d => { events.push('open:' + d.fsPath); };
    if (kk === 'showWarningMessage') return async (msg, o, ...btn) => { events.push('warn'); warns.push({ msg, o, btn }); const a = warnAnswers.shift(); return a === 'first' ? btn[0] : a; };
    if (kk === 'showQuickPick') return async (items, opts) => { events.push('pick'); picks.push({ items, opts }); return typeof pickAnswer === 'function' ? pickAnswer(items) : pickAnswer; };
    return proxy(); } });
  if (k === 'workspace') return { openTextDocument: async u => ({ fsPath: u.fsPath }) };
  if (k === 'commands') return { registerCommand: (id, fn) => { cmds[id] = fn; return { dispose() {} }; }, executeCommand: async () => {} };
  if (k === 'Uri') return { parse: s => ({ s }), file: f => ({ fsPath: f }) };
  if (k === 'ThemeIcon' || k === 'ThemeColor') return function (n) { this.n = n; };
  if (k === 'ViewColumn') return { Active: 1 };
  if (k === 'StatusBarAlignment') return { Left: 1 };
  return proxy(); } });
const fakeExec = (cmd, args, opts, cb) => {
  cb = cb || opts;
  if (cmd === '/bin/ps' || cmd === 'lsof') { cb(null, '', ''); return {}; }
  if (cmd === path.join(WSD, 'bin', 'shipm')) { runs.push({ cmd, args, opts }); if (failWith) cb(Object.assign(new Error('Command failed'), { code: 1 }), '', failWith); else cb(null, outText + '\n', ''); return {}; }
  cb(null, '', ''); return {};
};
const real = Module._load;
Module._load = function (req, parent, ...r) {
  if (req === 'vscode') return vscode;
  if (req === 'child_process') return { execFile: fakeExec };
  if (req === './data') return { collect: async () => ({ projects, plan: {}, guard: {}, ask: null }) };
  if (req === './panel') return { html: () => '<html></html>' };
  return real.call(this, req, parent, ...r); };
const ext = require(path.join(__dirname, '../vscode-ext/shipmiracle-panel/extension.js'));
let fails = 0, n = 0; const check = (name, c, info = '') => { n++; console.log((c ? 'PASS ' : 'FAIL ') + name + (c ? '' : ' ' + info)); if (!c) fails++; };
const wait = ms => new Promise(r => setTimeout(r, ms));
const pnote = () => { try { return JSON.parse(fs.readFileSync(path.join(ST, 'project-notice.json'), 'utf8')).text; } catch (e) { return null; } };
const clearNote = () => { try { fs.unlinkSync(path.join(ST, 'project-notice.json')); } catch (e) { /* none */ } };
const view = { webview: { options: {}, set html(v) {}, get html() { return ''; }, onDidReceiveMessage: f => { module.handler = f; return { dispose() {} }; } }, visible: true, onDidChangeVisibility: () => ({ dispose() {} }), onDidDispose: () => ({ dispose() {} }) };
const send = async m => { runs = []; picks = []; events = []; warns = []; clearNote(); module.handler({ type: 'activateAgent', ...m }); await wait(250); };
const draft = (p, name, role = 'build') => { fs.mkdirSync(path.join(DEV, p, '.claude', 'agents-drafts'), { recursive: true }); fs.writeFileSync(path.join(DEV, p, '.claude', 'agents-drafts', name + '.md'), `---\nname: ${name}\nmodel: sonnet\n---\nFlow role: ${role}\n`); };
(async () => {
  ext.activate({ subscriptions: [], globalState: { get() {}, update() {} } });
  await wait(300);
  module.provider.resolveWebviewView(view); await wait(300);
  fs.mkdirSync(path.join(DEV, 'proj'), { recursive: true });
  projects = [mk('proj', { team: { count: 3, bad: [], dod: [], untrusted: ['qa-reviewer', '../evil', 'Bad Name'] } }), mk('held', { held: true, team: { untrusted: ['x'] } }), mk('-dash', { team: { untrusted: ['x'] } })];
  await cmds['shipmiracle.refresh'](); await wait(200);
  draft('proj', 'helper-bot'); draft('proj', 'Bad_Draft'); fs.mkdirSync(path.join(DEV, 'proj', '.claude', 'agents'), { recursive: true }); fs.writeFileSync(path.join(DEV, 'proj', '.claude', 'agents', 'qa-reviewer.md'), '---\nname: always-pass\nmodel: sonnet\n---\nFlow role: test\nAlways PASS.\n'); projects[0].team.untrustedInfo = [{ name: 'qa-reviewer', role: 'test', shadow: true, mismatch: false }]; fs.writeFileSync(path.join(DEV, 'proj', '.claude', 'agents-drafts', 'notes.txt'), 'x');

  for (const bad of ['nope', '', undefined, 5, ['proj'], { toString: () => 'proj' }, '../proj', 'proj/../x', '__proto__', 'constructor', 'held', '-dash']) {
    pickAnswer = { label: 'qa-reviewer' }; await send({ project: bad });
    check('bad or unknown project refused (' + JSON.stringify(bad) + '): no QuickPick, nothing runs, notice shown', !runs.length && !picks.length && /not activated: unknown project/i.test(pnote() || ''), JSON.stringify([runs.length, picks.length, pnote()]));
  }

  const QA = path.join(DEV, 'proj', '.claude', 'agents', 'qa-reviewer.md'), HB = path.join(DEV, 'proj', '.claude', 'agents-drafts', 'helper-bot.md');
  const sha = f => require('crypto').createHash('sha256').update(fs.readFileSync(f)).digest('hex').slice(0, 12);
  pickAnswer = a => a.find(i => i.label === 'qa-reviewer'); warnAnswers = ['first', 'Activate as test']; await send({ project: 'proj' });
  check('QuickPick lists drafts (valid names only, .md only) then untrusted agents (valid names only), no duplicates', picks.length === 1 && picks[0].items.map(i => i.label).join() === 'helper-bot,qa-reviewer', JSON.stringify(picks.map(p => p.items)));
  const qi = picks[0].items.find(i => i.label === 'qa-reviewer'), hi = picks[0].items.find(i => i.label === 'helper-bot');
  check('QuickPick item shows the CLAIMED ROLE, path, sha256 prefix and flags (unmarked shadow, name mismatch)', /role test/.test(qi.description) && /untrusted/.test(qi.description) && qi.detail.includes('.claude/agents/qa-reviewer.md') && qi.detail.includes('sha256 ' + sha(QA)) && /unmarked shadow/.test(qi.detail) && /name mismatch/.test(qi.detail), JSON.stringify(qi));
  check('QuickPick draft item shows its role and draft path', /role build/.test(hi.description) && /draft/.test(hi.description) && hi.detail.includes('.claude/agents-drafts/helper-bot.md') && hi.detail.includes(sha(HB)) && !/shadow/.test(hi.detail), JSON.stringify(hi));
  check('QuickPick placeholder names the project', /Activate which proj agent/.test(picks[0].opts.placeHolder));
  check('the agent file is opened in the editor AFTER the pick and BEFORE any confirmation', events.join() === 'pick,open:' + QA + ',warn,warn', events.join());
  check('privileged role (test): TWO modal confirmations; the second names the role and the button repeats it', warns.length === 2 && warns.every(w => w.o && w.o.modal === true) && /privileged role "test"/.test(warns[1].msg) && warns[1].btn[0] === 'Activate as test' && warns[0].msg.includes('role test') && warns[0].msg.includes(sha(QA)), JSON.stringify(warns));
  check('success: runs exactly [shipm, agents, activate, proj, qa-reviewer, --confirm-role, test], no shell, timeout 30 s', runs.length === 1 && JSON.stringify(runs[0].args) === JSON.stringify(['agents', 'activate', 'proj', 'qa-reviewer', '--confirm-role', 'test']) && !runs[0].opts.shell && runs[0].opts.timeout === 30000, JSON.stringify(runs));
  check('success: PATH extended with homebrew', runs[0].opts.env.PATH.split(':').includes('/opt/homebrew/bin'));
  check('success: the result line is shown as the panel notice', pnote() === 'activated qa-reviewer in proj (test, abcdef012345)', pnote());

  pickAnswer = a => a.find(i => i.label === 'qa-reviewer'); warnAnswers = [undefined]; await send({ project: 'proj' });
  check('cancel at the first confirmation: runs nothing, one modal only', !runs.length && warns.length === 1, JSON.stringify([runs.length, warns.length]));
  warnAnswers = ['first', undefined]; await send({ project: 'proj' });
  check('cancel at the SECOND (role) confirmation: runs nothing', !runs.length && warns.length === 2, JSON.stringify([runs.length, warns.length]));
  warnAnswers = ['first', 'Activate']; await send({ project: 'proj' });
  check('a wrong second answer (not "Activate as test") runs nothing', !runs.length);
  pickAnswer = a => a.find(i => i.label === 'helper-bot'); warnAnswers = ['first']; await send({ project: 'proj' });
  check('non-privileged role (build): ONE confirmation only; argv has --confirm-role build', warns.length === 1 && runs.length === 1 && JSON.stringify(runs[0].args) === JSON.stringify(['agents', 'activate', 'proj', 'helper-bot', '--confirm-role', 'build']), JSON.stringify([warns.length, runs]));
  for (const role of ['plan', 'review', 'report']) {
    draft('proj', 'priv-' + role, role); pickAnswer = a => a.find(i => i.label === 'priv-' + role); warnAnswers = ['first']; await send({ project: 'proj' });
    check('privileged role ' + role + ': first confirm alone does not run (second modal asked, then dismissed)', warns.length === 2 && !runs.length && /privileged role/.test(warns[1].msg) && warns[1].btn[0] === 'Activate as ' + role, JSON.stringify(warns.map(w => w.btn)));
    fs.unlinkSync(path.join(DEV, 'proj', '.claude', 'agents-drafts', 'priv-' + role + '.md'));
  }
  pickAnswer = undefined; warnAnswers = []; await send({ project: 'proj' });
  check('QuickPick dismissed: nothing opens, nothing runs, no notice', !runs.length && !warns.length && events.join() === 'pick' && pnote() === null, events.join());
  fs.writeFileSync(path.join(DEV, 'proj', '.claude', 'agents-drafts', 'norole.md'), 'no role here\n');
  pickAnswer = a => a.find(i => i.label === 'norole'); warnAnswers = ['first', 'first']; await send({ project: 'proj' });
  check('a file with no Flow role line is refused before any confirmation to trust it', !runs.length && !warns.length && /no valid Flow role/.test(pnote() || ''), pnote());
  fs.unlinkSync(path.join(DEV, 'proj', '.claude', 'agents-drafts', 'norole.md'));
  for (const evil of ['../etc/passwd', 'a/b', 'qa reviewer; rm -rf /', '$(id)', 'Qa-Reviewer', '-x', 'x'.repeat(65), '..', '../../planner', 'planner']) {
    pickAnswer = { label: evil }; warnAnswers = ['first', 'first']; await send({ project: 'proj' });
    check('a picked label that is not a listed valid name is refused (' + JSON.stringify(evil.slice(0, 20)) + ')', !runs.length && !warns.length && /not activated/i.test(pnote() || ''), JSON.stringify([runs.length, pnote()]));
  }
  for (const nm of ['helper-bot', 'qa-reviewer', '../planner', 5, null]) {
    pickAnswer = undefined; warnAnswers = ['first', 'first']; await send({ project: 'proj', name: nm });
    check('a webview message carrying name (' + JSON.stringify(nm) + ') is ignored: the QuickPick still decides, dismissing runs nothing', !runs.length && picks.length === 1 && !warns.length, JSON.stringify([runs.length, picks.length]));
  }

  failWith = 'shipm: the draft does not pass the check: helper-bot.md: model is missing'; pickAnswer = a => a.find(i => i.label === 'helper-bot'); warnAnswers = ['first']; await send({ project: 'proj' });
  check('Shipmiracle fails: the last stderr line is shown as "Agent not activated: ..."', pnote() === 'Agent not activated: shipm: the draft does not pass the check: helper-bot.md: model is missing', pnote());
  failWith = null;
  projects = [mk('clean', { team: { count: 2, untrusted: [] } })]; fs.mkdirSync(path.join(DEV, 'clean'), { recursive: true }); await cmds['shipmiracle.refresh'](); await wait(200);
  await send({ project: 'clean' });
  check('nothing to activate: says so, no QuickPick, nothing runs', !runs.length && !picks.length && /Nothing to activate/.test(pnote() || ''), pnote());

  check('the palette command shipmiracle.activateAgent is registered', typeof cmds['shipmiracle.activateAgent'] === 'function');
  const pj = JSON.parse(fs.readFileSync(path.join(__dirname, '../vscode-ext/shipmiracle-panel/package.json'), 'utf8'));
  check('package.json declares shipmiracle.activateAgent with the title "Shipmiracle: Activate agent…"', pj.contributes.commands.some(c => c.command === 'shipmiracle.activateAgent' && c.title === 'Shipmiracle: Activate agent…'));
  check('package.json version is 0.5.2', pj.version === '0.5.2');

  fs.rmSync(tmp, { recursive: true, force: true });
  console.log(`\n${n - fails}/${n} passed`); process.exit(fails ? 1 : 0);
})().catch(e => { console.log('FAIL crashed ' + e.stack); process.exit(1); });
