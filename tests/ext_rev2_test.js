// Panel v3 revision v2, extension side, against a stand-in vscode: Safe mode, Stop autopilot, the option C verbs (checkpoint / resume / admit / drop), the "Until I disable it" charter,
// and the Ask model. Everything is a PREFILLED terminal line (no Enter); the panel never runs Shipmiracle, never writes a file; C commands are refused until the data says the engine has them.
// Run: node tests/ext_rev2_test.js
require('./shipmiracle_isolation').apply();
const Module = require('module'), path = require('path'), fs = require('fs'), os = require('os');
const C = require('../vscode-ext/shipmiracle-panel/charter.js'), ASK = require('../vscode-ext/shipmiracle-panel/ask.js');
let fails = 0, n = 0; const check = (name, c, info = '') => { n++; console.log((c ? 'PASS ' : 'FAIL ') + name + (c ? '' : ' ' + info)); if (!c) fails++; };
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'shipmiracle-r2-'));
const ST = path.join(tmp, 'state'), WSD = path.join(tmp, 'ws'), PROJ = path.join(tmp, 'Dev', 'demo'), ASKD = path.join(tmp, 'Dev', 'ask');
for (const d of [ST, path.join(WSD, 'config'), PROJ, ASKD]) fs.mkdirSync(d, { recursive: true });
Object.assign(process.env, { SHIPMIRACLE_TEST: '1', SHIPMIRACLE_EXT_STATE: ST, SHIPMIRACLE_EXT_WS: WSD, SHIPMIRACLE_EXT_DEV: path.join(tmp, 'Dev'), SHIPMIRACLE_DIAG_DIR: path.join(tmp, 'diag'), SHIPMIRACLE_HEAL_MS: '99999999' });
const execs = [], terms = [], sent = [];
const base = { name: 'demo', dir: PROJ, stack: 'web', state: 'idle', agents: [], tokens: {}, ideas: { open: [], evaluated: [], done: 0, dropped: 0 }, held: false, level: 'strict', cr: [{ id: 'CR-012', status: 'queued', title: 'a' }, { id: 'CR-013', status: 'open', title: 'b' }], playbook: { type: 'software', autopilot: 'guided', level: 'strict', trusted: true, valid: true }, autopilot: null };
const askP = (o = {}) => ({ name: 'ask', dir: ASKD, stack: 'notes', state: 'idle', agents: [], tokens: {}, ideas: { open: [], evaluated: [], done: 0, dropped: 0 }, held: false, ask: { inbox: true, questions_today: 0, limit: 20, notes: 0, last: null, ...o } });
const PS = [{ ...base }], DATA = { projects: PS, plan: {}, guard: {}, ask: null, autopilot: { until_disabled_supported: false } };
const proxy = () => new Proxy(function () {}, { get: (t, k) => k === 'then' ? undefined : (k === 'dispose' ? () => {} : proxy()), apply: () => proxy() });
const term = o => ({ name: o.name, opts: o, exitStatus: undefined, show() {}, sendText(t, nl) { if (t === '\u0015') return; sent.push({ text: t, nl }); }, processId: Promise.resolve(1), dispose() {} });
const vscode = new Proxy({}, { get: (t, k) => {
  if (k === 'window') return new Proxy({}, { get: (w, kk) => {
    if (kk === 'terminals') return terms;
    if (kk === 'createTerminal') return o => { const x = term(o); terms.push(x); return x; };
    if (kk === 'registerWebviewViewProvider') return (id, prov) => { module.provider = prov; return { dispose() {} }; };
    if (kk === 'activeTerminal') return undefined;
    return proxy(); } });
  if (k === 'commands') return { registerCommand: () => ({ dispose() {} }), executeCommand: async () => {} };
  if (k === 'Uri') return { parse: s => ({ s }), file: f => ({ fsPath: f }) };
  if (k === 'ThemeIcon' || k === 'ThemeColor') return function (nn) { this.n = nn; };
  if (k === 'ViewColumn') return { Active: 1 };
  if (k === 'StatusBarAlignment') return { Left: 1 };
  return proxy(); } });
const real = Module._load;
Module._load = function (req, parent, ...r) {
  if (req === 'vscode') return vscode;
  if (req === 'child_process') return { execFile: (cmd, args, o, cb) => { execs.push([cmd, args]); (cb || o)(null, '', ''); return {}; } };
  if (req === './data') return { collect: async () => DATA };
  return real.call(this, req, parent, ...r); };
const ext = require(path.join(__dirname, '../vscode-ext/shipmiracle-panel/extension.js'));
const wait = ms => new Promise(r => setTimeout(r, ms));
const notice = () => { try { return JSON.parse(fs.readFileSync(path.join(ST, 'project-notice.json'), 'utf8')).text; } catch (e) { return null; } };
(async () => {
  ext.activate({ subscriptions: [], globalState: { get() {}, update() {} } }); await wait(300);
  let handler; const view = { webview: { options: {}, set html(x) {}, get html() { return ''; }, onDidReceiveMessage: f => { handler = f; return { dispose() {} }; } }, visible: true, onDidChangeVisibility: () => ({ dispose() {} }), onDidDispose: () => ({ dispose() {} }) };
  module.provider.resolveWebviewView(view); await wait(400);
  const reset = (o, supported = false, extra = []) => { PS.length = 0; PS.push({ ...base, ...o }, ...extra); DATA.autopilot = { until_disabled_supported: supported }; terms.length = 0; sent.length = 0; execs.length = 0; try { fs.unlinkSync(path.join(ST, 'project-notice.json')); } catch (e) { /* none */ } };
  const send = async m => { await handler(m); await wait(120); };
  const SHIPM = path.join(WSD, 'bin', 'shipm');
  const noRun = () => sent.every(s => s.nl === false) && execs.length === 0 && fs.readdirSync(PROJ).length === 0;

  // ---- charter.js builders
  check('safeArgv: playbook set level strict|warn with --allow-open-chat; off, bad names and bad levels are refused', C.safeArgv('/a', 'demo', 'warn')[0].join(' ') === '/a playbook set level warn --project demo --allow-open-chat' && ['off', 'x', '', 'strict; rm'].every(l => { try { C.safeArgv('/a', 'demo', l); return false; } catch (e) { return true; } }) && (() => { try { C.safeArgv('/a', "x'; rm", 'strict'); return false; } catch (e) { return true; } })());
  check('stopArgv and cVerbArgv: exact commands; a bad verb, a bad CR id or an unsafe project is refused', C.stopArgv('/a', 'demo')[0].join(' ') === '/a autopilot stop --project demo' && C.cVerbArgv('/a', 'demo', 'checkpoint')[0].join(' ') === '/a autopilot checkpoint --project demo'
    && C.cVerbArgv('/a', 'demo', 'admit', 'CR-015')[0].join(' ') === '/a autopilot admit CR-015 --project demo' && C.cVerbArgv('/a', 'demo', 'drop', 'CR-013')[0].join(' ') === '/a autopilot drop CR-013 --project demo'
    && [['rm', ''], ['admit', 'CR-1; rm'], ['admit', ''], ['drop', 'x']].every(([v, c]) => { try { C.cVerbArgv('/a', 'demo', v, c); return false; } catch (e) { return true; } }));
  check('untilCheck: day 1-10 and never above the week; requests a day 1-5', C.untilCheck(4, 3, 10) === '' && C.untilCheck(11, 3, 25) !== '' && C.untilCheck(0, 3, 25) !== '' && C.untilCheck(8, 3, 5) !== '' && C.untilCheck(4, 6, 10) !== '' && C.untilCheck(4, 0, 10) !== '' && C.untilCheck('x', 3, 10) !== '');
  const v = C.check({ goal: 'g', scope: 'src/', budget: '10', time: '3', depsMode: 'none', ends: ['CR-012'] }, ['CR-012']).value;
  const a = C.charterArgv('/a', 'demo', v, false)[0].join(' '), c = C.charterArgv('/a', 'demo', { ...v, until: 'disabled', day: 4, crsDay: 3 }, false)[0].join(' ');
  check('charterArgv A/B unchanged (--time, no --until); C has --until=disabled --day=4% --crs-day=3 and no --time', /--time=3h/.test(a) && !/--until/.test(a) && /--until=disabled --day=4% --crs-day=3/.test(c) && !/--time/.test(c) && /--budget=10%/.test(c));
  { const page = new Function(C.clientSource() + '; return { a: CHUC(4, 3, 10), b: CHUC(8, 3, 5), c: CHUC(4, 9, 10) };')(); check('the page copy of untilCheck runs on its own (UNTIL included): valid, day above week, requests a day out of range', page.a === '' && /more than the week/.test(page.b) && /Requests a day/.test(page.c), JSON.stringify(page)); }

  // ---- Safe mode
  reset(); await send({ type: 'safe', project: 'demo', to: 'warn' });
  check('Safe mode -> warnings only: one prefilled line `shipm playbook set level warn ... --allow-open-chat`, no Enter, nothing run', sent.length === 1 && sent[0].text === C.joinCmds(C.safeArgv(SHIPM, 'demo', 'warn')) && noRun(), JSON.stringify(sent));
  for (const [name, o, m] of [['to off', {}, { to: 'off' }], ['same level', {}, { to: 'strict' }], ['project working', { state: 'working' }, { to: 'warn' }], ['project held', { held: true }, { to: 'warn' }], ['unknown project', {}, { project: 'nope', to: 'warn' }], ['no playbook', { playbook: null }, { to: 'warn' }], ['level switch blocked', { levelSwitch: { ok: false, why: 'x' } }, { to: 'warn' }], ['non-string', {}, { to: { x: 1 } }]]) {
    reset(o); await send({ type: 'safe', project: 'demo', ...m }); check('Safe mode refused, nothing typed: ' + name, sent.length === 0 && terms.length === 0 && execs.length === 0, JSON.stringify(sent)); }

  // ---- Stop autopilot
  reset({ playbook: { ...base.playbook, autopilot: 'full' }, autopilot: { state: 'running', until: 'disabled' } }); await send({ type: 'act', act: 'apstop', project: 'demo' });
  check('Stop autopilot (C): `shipm autopilot stop --project demo` prefilled, no Enter', sent.length === 1 && sent[0].text === C.joinCmds(C.stopArgv(SHIPM, 'demo')) && noRun(), JSON.stringify(sent));
  reset(); await send({ type: 'act', act: 'apstop', project: 'demo' }); check('Stop with no run: nothing typed', sent.length === 0);

  // ---- option C verbs: refused until the engine is ready, then exact commands
  const cap = (o = {}) => ({ playbook: { ...base.playbook, autopilot: 'full' }, autopilot: { state: 'paused', until: 'disabled', reason: 'qa_fail', cr: 'CR-013', waiting: [{ id: 'CR-015', title: 't', in_chat: true }], ...o } });
  reset(cap(), false); await send({ type: 'act', act: 'cverb', verb: 'resume', project: 'demo' });
  check('engine not ready (data.autopilot.until_disabled_supported false): resume is refused with a notice, nothing typed', sent.length === 0 && /does not support this yet/.test(notice() || ''), notice());
  for (const [verb, cr, line] of [['resume', '', 'resume'], ['drop', 'CR-013', 'drop CR-013'], ['checkpoint', '', 'checkpoint']]) {
    reset(cap(verb === 'checkpoint' ? { reason: 'checkpoint' } : {}), true); await send({ type: 'act', act: 'cverb', verb, cr, project: 'demo' });
    check('engine ready: ' + verb + ' types `shipm autopilot ' + line + '` (no Enter)', sent.length === 1 && sent[0].text === C.joinCmds(C.cVerbArgv(SHIPM, 'demo', verb, cr)) && noRun() && sent[0].text.includes("'" + line.split(' ')[0] + "'"), JSON.stringify(sent)); }
  reset(cap({ reason: '' , state: 'running' }), true); await send({ type: 'act', act: 'cverb', verb: 'admit', cr: 'CR-015', project: 'demo' });
  check('admit CR-015 (waiting): typed exactly', sent.length === 1 && sent[0].text === C.joinCmds(C.cVerbArgv(SHIPM, 'demo', 'admit', 'CR-015')) && noRun(), JSON.stringify(sent));
  for (const [name, o, m] of [['admit a request that is not waiting', cap(), { verb: 'admit', cr: 'CR-099' }], ['drop a request that is not the paused one', cap(), { verb: 'drop', cr: 'CR-012' }], ['resume while running', cap({ state: 'running' }), { verb: 'resume' }], ['not a C run', { playbook: { ...base.playbook, autopilot: 'full' }, autopilot: { state: 'paused' } }, { verb: 'resume' }], ['unknown verb', cap(), { verb: 'approve' }], ['verb with shell text', cap(), { verb: 'resume; rm -rf' }], ['bad CR id', cap(), { verb: 'admit', cr: 'CR-1;rm' }]]) {
    reset(o, true); await send({ type: 'act', act: 'cverb', project: 'demo', ...m }); check('C verb refused, nothing typed: ' + name, sent.length === 0, JSON.stringify(sent)); }

  // ---- charter C
  const good = { type: 'charter', op: 'start', project: 'demo', goal: 'Finish CR-012', scope: 'src/**', budget: '10', time: '', depsMode: 'none', deps: '', ends: ['CR-012', 'CR-013'], until: 'c', day: 4, crsDay: 3 };
  reset({}, false); await send({ ...good }); check('charter C with the engine not ready: refused ("engine not ready"), nothing typed', sent.length === 0 && /engine not ready/.test(notice() || ''), notice());
  reset({}, true); await send({ ...good, ends: ['CR-012', 'CR-013'] });
  check('charter C with the engine ready: set + start typed as one prefilled line with --until=disabled --day=4% --crs-day=3 and no --time', sent.length === 1 && sent[0].nl === false && /'--until=disabled' '--day=4%' '--crs-day=3'/.test(sent[0].text) && !/--time/.test(sent[0].text) && noRun(), JSON.stringify(sent));
  for (const [name, m] of [['day above the week', { budget: '5', day: 8 }], ['day 0', { day: 0 }], ['day 11', { day: 11 }], ['requests a day 6', { crsDay: 6 }], ['requests a day text', { crsDay: 'x' }]]) { reset({}, true); await send({ ...good, ...m }); check('charter C refused: ' + name, sent.length === 0 && /Not started/.test(notice() || ''), notice()); }
  reset({}, true); await send({ ...good, until: 'b', time: '8', day: 0, crsDay: 0 });
  check('charter B (I stop it): the same A/B command with --time=8h and no --until', sent.length === 1 && /--time=8h/.test(sent[0].text) && !/--until/.test(sent[0].text), JSON.stringify(sent));
  reset({}, true); await send({ ...good, until: 'a', time: '3', day: 0, crsDay: 0, ends: ['CR-012'] });
  check('charter A (this request is done): --time=3h, no --until, deep-equal the charter editor command', sent.length === 1 && sent[0].text === C.joinCmds(C.charterArgv(SHIPM, 'demo', C.check({ goal: 'Finish CR-012', scope: 'src/**', budget: '10', time: '3', depsMode: 'none', ends: ['CR-012'] }, ['CR-012', 'CR-013']).value, true)), JSON.stringify(sent));

  // ---- Ask model
  const askData = (supported, o) => { reset({}, false, [askP({ model_supported: supported })]); void o; };
  askData(true); await send({ type: 'ask', op: 'type', q: 'What is a monad?', model: 'sonnet' });
  check('Ask with a model (CLI supports --model): `shipm ask --inbox --model sonnet <question>` prefilled, no Enter', sent.length === 1 && sent[0].nl === false && sent[0].text === C.joinCmds([ASK.inboxArgv(SHIPM, 'What is a monad?', 'sonnet')]) && /'--model' 'sonnet'/.test(sent[0].text) && execs.length === 0, JSON.stringify(sent));
  for (const m of ['opus', 'haiku']) { askData(true); await send({ type: 'ask', op: 'type', q: 'hi', model: m }); check('Ask model ' + m + ' is typed', sent.length === 1 && sent[0].text.includes("'--model' '" + m + "'")); }
  askData(true); await send({ type: 'ask', op: 'type', q: 'hi', model: 'gpt-9; rm' }); check('Ask with an unknown model: no --model is typed (the CLI default applies)', sent.length === 1 && !/--model/.test(sent[0].text));
  askData(false); await send({ type: 'ask', op: 'type', q: 'hi', model: 'sonnet' }); check('Ask when the CLI has no --model yet: the model is ignored, the plain command is typed', sent.length === 1 && !/--model/.test(sent[0].text) && sent[0].text === C.joinCmds([ASK.inboxArgv(SHIPM, 'hi')]));
  check('inboxArgv: model must be opus, sonnet or haiku', (() => { try { ASK.inboxArgv('/a', 'q', 'gpt'); return false; } catch (e) { return true; } })() && ASK.inboxArgv('/a', 'q', 'haiku').join(' ') === '/a ask --inbox --model haiku q' && ASK.inboxArgv('/a', 'q').join(' ') === '/a ask --inbox q');
  console.log(fails ? `\nFAILED: ${fails} of ${n}` : `\nALL PASS (${n})`); fs.rmSync(tmp, { recursive: true, force: true }); process.exit(fails ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
