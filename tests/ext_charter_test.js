// Charter editor, autopilot level and hard-stop routes of the extension against a stand-in for VS Code (never a real terminal):
//  - the panel never runs the charter CLI itself (no execFile of shipm); the owner's commands are typed into an integrated terminal, quoted as argv
//  - hostile input (quotes, $(), backticks, newlines, Arabic, leading dashes) can never become shell syntax
//  - the extension re-validates everything the page sent; it never sends approval / allow: / charter: text anywhere
//  - charter.js (caps and messages) matches shipmiracle/autopilot/charter.py (drift check)
// Run: node tests/ext_charter_test.js
require('./shipmiracle_isolation').apply();
const Module = require('module'); const path = require('path'); const fs = require('fs'); const os = require('os'); const { spawnSync } = require('child_process');
const C = require('../vscode-ext/shipmiracle-panel/charter.js');
let fails = 0; const check = (n, c, info = '') => { console.log((c ? 'PASS ' : 'FAIL ') + n + (c ? '' : ' ' + info)); if (!c) fails++; };

// ---------- 1. drift: charter.js against shipmiracle/autopilot/charter.py ----------
const py = fs.readFileSync(path.join(__dirname, '..', 'shipmiracle', 'autopilot', 'charter.py'), 'utf8');
const num = n => { const m = new RegExp('^' + n + ' *= *([0-9.]+)', 'm').exec(py); return m ? Number(m[1]) : NaN; };
const pair = (n, k) => { const m = new RegExp('^' + n + ' *= *([0-9.]+), *([0-9.]+)', 'm').exec(py); return m ? Number(m[k]) : NaN; };
const tri = (n, k) => { const m = new RegExp('^' + n + ' *= *([0-9.]+), *([0-9.]+), *([0-9.]+)', 'm').exec(py); return m ? Number(m[k]) : NaN; };
const R = C.RULES;
check('drift: GOAL_MAX, SCOPE_MAX_GLOBS/LEN, DEPS_MAX, ENDS_MAX equal charter.py', R.goalMax === num('GOAL_MAX') && R.scopeMaxGlobs === pair('SCOPE_MAX_GLOBS, SCOPE_MAX_LEN', 1) && R.scopeMaxLen === pair('SCOPE_MAX_GLOBS, SCOPE_MAX_LEN', 2) && R.depsMax === num('DEPS_MAX') && R.endsMax === num('ENDS_MAX'), JSON.stringify([num('GOAL_MAX'), pair('SCOPE_MAX_GLOBS, SCOPE_MAX_LEN', 1)]));
check('drift: BUDGET_MIN/MAX/DEFAULT (1, 25, 10) and TIME_MIN/MAX/DEFAULT (0.25, 8, 3) equal charter.py', R.budgetMin === tri('BUDGET_MIN, BUDGET_MAX, BUDGET_DEFAULT', 1) && R.budgetMax === tri('BUDGET_MIN, BUDGET_MAX, BUDGET_DEFAULT', 2) && R.budgetDefault === tri('BUDGET_MIN, BUDGET_MAX, BUDGET_DEFAULT', 3)
  && R.timeMin === tri('TIME_MIN, TIME_MAX, TIME_DEFAULT', 1) && R.timeMax === tri('TIME_MIN, TIME_MAX, TIME_DEFAULT', 2) && R.timeDefault === tri('TIME_MIN, TIME_MAX, TIME_DEFAULT', 3));
const ex = /ALWAYS_EXCLUDED = \(([^)]*)\)/.exec(py);
const pyEx = ex ? ex[1].replace(/"\s+"/g, '').match(/"([^"]*)"/g).map(x => x.slice(1, -1)) : [];     // adjacent string literals are one string in Python
check('drift: ALWAYS_EXCLUDED has the same 14 entries in the same order', pyEx.length === 14 && JSON.stringify(pyEx) === JSON.stringify(R.alwaysExcluded), JSON.stringify(pyEx));
const fnSrc = py.slice(py.indexOf('def clean_goal'), py.indexOf('# ---------------------------------------------------------------- schema'));
const pyMsgs = [...fnSrc.matchAll(/CharterError\(\s*"((?:[^"\\]|\\.)*)"/g)].map(m => m[1]);
const NOT_MIRRORED = new Set([      // messages of the text-parsing forms the page does not use (a range or comma list typed into one box, non-text input): documented, not copied
  'goal: expected text', 'budget: expected a whole number of percent', 'time: expected hours', 'deps: expected none or a list of package names', 'deps: mode none takes no names',
  'ends: a range looks like CR-012..CR-014', 'ends: the range runs backwards (%s..%s)', 'ends: a range covers at most %d change requests (got %d)', 'ends: expected CR-012..CR-014 or CR-012,CR-015', 'ends: at most %d change requests (got %d)',
  // option C day slice and requests a day: the page takes them from preset buttons and checks them with charter.js untilCheck() (own wording, ranges tested in ext_rev2_test); the CLI text-parsing forms are not copied
  'day: expected a whole number of percent of the week, like 4%%, got %r', 'day: %s%% is outside %d-%d%% of the week a day', 'crs-day: expected a whole number of requests, got %r', 'crs-day: %s is outside %d-%d requests a day']);
const mirrored = Object.values(C.MSG), missingInJs = pyMsgs.filter(m => !mirrored.includes(m) && !NOT_MIRRORED.has(m)), notInPy = mirrored.filter(m => !pyMsgs.includes(m));
check('drift: every message of charter.py clean_* is in charter.js MSG (or on the documented not-mirrored list), and every MSG text exists in charter.py', pyMsgs.length >= 16 && missingInJs.length === 0 && notInPy.length === 0, JSON.stringify({ missingInJs, notInPy, n: pyMsgs.length }));
const pyOk = spawnSync(process.env.SHIPMIRACLE_PY || 'python3', ['-I', '-c', `
import sys; sys.path.insert(0, ${JSON.stringify(path.join(__dirname, '..'))})
from shipmiracle.autopilot import charter as c
import json
out = {}
for k, f, v in [("goal", c.clean_goal, "x" * 201), ("scope", c.clean_scope, "/etc"), ("scope2", c.clean_scope, "a/../b"), ("budget", c.clean_budget, "26"), ("time", c.clean_time, "9"), ("time2", c.clean_time, "0.1"), ("deps", c.clean_deps, "Bad Name"), ("ends", c.clean_ends, [])]:
    try: f(v); out[k] = None
    except Exception as e: out[k] = str(e)
print(json.dumps(out))
`], { encoding: 'utf8', env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1' } });
if (pyOk.status === 0) {
  const o = JSON.parse(pyOk.stdout.trim().split('\n').pop()), ok = (f, openCrs = ['CR-012']) => C.check({ goal: 'g', scope: 'src/', budget: '10', time: '3', depsMode: 'none', ends: ['CR-012'], ...f }, openCrs).errors;
  check('drift (live): the real Python messages equal the JS ones for goal, scope, budget, time, deps, ends', o.goal === ok({ goal: 'x'.repeat(201) }).goal && o.scope === ok({ scope: '/etc' }).scope && o.scope2 === ok({ scope: 'a/../b' }).scope && o.budget === ok({ budget: '26' }).budget && o.time === ok({ time: '9' }).time && o.time2 === ok({ time: '0.1' }).time
    && o.deps === ok({ depsMode: 'listed', deps: 'Bad Name' }).deps && o.ends === ok({ ends: [] }).ends, JSON.stringify([o, ok({ goal: 'x'.repeat(201) })]));
} else check('drift (live): python3 ran', false, pyOk.stderr);

// ---------- 2. quoting and argv ----------
const sh = cmd => spawnSync('/bin/sh', ['-c', cmd], { encoding: 'utf8' });
const HOSTILE = ["it's", 'say "hi"', '$(touch /tmp/pwn-shipmiracle)', '`touch /tmp/pwn-shipmiracle`', '; rm -rf ~', '-x --yes', 'إصلاح الواجهة RTL', '\\n', "a'b'c", '*', '$HOME ${HOME}', '&& echo owned', '| cat'];
let allOk = true, bad = '';
for (const h of HOSTILE) { const r = sh('printf %s ' + C.quote(h)); if (r.stdout !== h) { allOk = false; bad = JSON.stringify([h, r.stdout]); } }
check('quote(): a shell gets every hostile value back byte for byte (quotes, $(), backticks, ;, &&, |, globs, dashes, Arabic)', allOk, bad);
check('quote(): a newline, tab or escape character is refused (the terminal would type it as a key press)', ['a\nb', 'a\tb', 'a\u001bb', 'a\rb'].every(v => { try { C.quote(v); return false; } catch (e) { return true; } }));
const goal = "it's $(touch /tmp/pwn-shipmiracle) `x` \"q\" ; rm -rf ~ إصلاح";
const v = C.check({ goal, scope: 'src/**, tests/', budget: '10', time: '3', depsMode: 'none', ends: ['CR-012'] }, ['CR-012']);
check('hostile goal is valid text and passes the rules (the quoting, not the validator, keeps it harmless)', v.ok, JSON.stringify(v.errors));
const cmds = C.charterArgv('/w s/bin/shipm', 'demo', v.value, true);
check('charterArgv: playbook set autopilot full, charter set, then start, each one argv; the goal is ONE argument "--goal=..."', cmds.length === 3 && cmds[0].join(' ') === '/w s/bin/shipm playbook set autopilot full --project demo --allow-open-chat' && cmds[1].includes('--goal=' + goal) && cmds[1].filter(a => a.startsWith('--goal')).length === 1 && cmds[2].join(' ') === '/w s/bin/shipm autopilot start --project demo', JSON.stringify(cmds));
check('charterArgv: no playbook-set step when the level is already full', C.charterArgv('/a', 'demo', v.value, false).length === 2);
const line = C.joinCmds(cmds);
const echoed = sh('set -f; for a in ' + C.joinCmds([cmds[1]]).replace(/^/, '') + '; do :; done');   // syntax check only: it must parse
const parsed = spawnSync('/bin/sh', ['-c', 'exec 3>&1; f() { for a in "$@"; do printf "%s\\0" "$a"; done; }; f ' + C.line(cmds[1].map(x => x))], { encoding: 'utf8' });
check('the typed line parses back to exactly the argv (hostile goal included) and nothing was executed', parsed.stdout.split('\0').slice(0, -1).join('\u0001') === cmds[1].join('\u0001') && !fs.existsSync('/tmp/pwn-shipmiracle') && /&& /.test(line), JSON.stringify(parsed.stdout.slice(0, 200)));
check('a leading dash in the goal cannot become an option (--goal=-x)', C.charterArgv('/a', 'demo', C.check({ goal: '--yes', scope: 'a', budget: 10, time: 3, depsMode: 'none', ends: ['CR-012'] }, ['CR-012']).value, false)[0].includes('--goal=--yes'));
check('unsafe project names are refused (quotes, spaces, leading dash, slash)', ["x'; rm", 'a b', '-p', '../x', 'a/b', ''].every(n => { try { C.charterArgv('/a', n, v.value, false); return false; } catch (e) { return true; } }));
check('allow / level / back argv: exact commands; a bad stop id or level is refused', C.allowArgv('/a', 'demo', 'H-1a2b3c')[0].join(' ') === '/a autopilot allow H-1a2b3c --project demo' && (() => { try { C.allowArgv('/a', 'demo', 'H-1; rm'); return false; } catch (e) { return true; } })()
  && C.apLevelArgv('/a', 'demo', 'manual')[0].join(' ') === '/a playbook set autopilot manual --project demo --allow-open-chat' && (() => { try { C.apLevelArgv('/a', 'demo', 'full'); return false; } catch (e) { return true; } })()
  && C.backToGuidedArgv('/a', 'demo').map(x => x.join(' ')).join('|') === '/a autopilot stop --project demo|/a playbook set autopilot guided --project demo --allow-open-chat');

// ---------- 3. the extension against a stand-in vscode ----------
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'shipmiracle-ch-'));
const ST = path.join(tmp, 'state'), WSD = path.join(tmp, 'ws'), PROJ = path.join(tmp, 'Dev', 'demo');
for (const d of [ST, path.join(WSD, 'config'), PROJ]) fs.mkdirSync(d, { recursive: true });
Object.assign(process.env, { SHIPMIRACLE_TEST: '1', SHIPMIRACLE_EXT_STATE: ST, SHIPMIRACLE_EXT_WS: WSD, SHIPMIRACLE_EXT_DEV: path.join(tmp, 'Dev'), SHIPMIRACLE_DIAG_DIR: path.join(tmp, 'diag'), SHIPMIRACLE_HEAL_MS: '99999999' });
const execs = [], terms = [], sent = [];
const base = { name: 'demo', dir: PROJ, stack: 'web', state: 'idle', agents: [], tokens: {}, ideas: { open: [], evaluated: [], done: 0, dropped: 0 }, held: false, level: 'strict', cr: [{ id: 'CR-012', status: 'queued', title: 'a' }, { id: 'CR-013', status: 'open', title: 'b' }, { id: 'CR-014', status: 'delivered', title: 'c' }], playbook: { type: 'software', autopilot: 'guided', level: 'strict' }, autopilot: null };
const PS = [{ ...base }];                                   // the extension reads data.projects from the last refresh: the array is shared so reset() is seen at once
const proxy = () => new Proxy(function () {}, { get: (t, k) => k === 'then' ? undefined : (k === 'dispose' ? () => {} : proxy()), apply: () => proxy() });
const clears = { n: 0 };      // Ctrl-U sent before every prefilled line (the panel clears the prompt line); counted, not part of the typed lines
const term = o => { const x = { name: o.name, opts: o, exitStatus: undefined, shown: 0, show() { this.shown++; }, sendText(t, nl) { if (t === '\u0015') { clears.n++; return; } sent.push({ term: this, text: t, nl }); }, processId: Promise.resolve(1), dispose() {} }; return x; };
const vscode = new Proxy({}, { get: (t, k) => {
  if (k === 'window') return new Proxy({}, { get: (w, kk) => {
    if (kk === 'terminals') return terms;
    if (kk === 'createTerminal') return o => { const x = term(o); terms.push(x); return x; };
    if (kk === 'registerWebviewViewProvider') return (id, prov) => { module.provider = prov; return { dispose() {} }; };
    if (kk === 'activeTerminal') return undefined;
    return proxy(); } });
  if (k === 'commands') return { registerCommand: () => ({ dispose() {} }), executeCommand: async () => {} };
  if (k === 'Uri') return { parse: s => ({ s }), file: f => ({ fsPath: f }) };
  if (k === 'ThemeIcon' || k === 'ThemeColor') return function (n) { this.n = n; };
  if (k === 'ViewColumn') return { Active: 1 };
  if (k === 'StatusBarAlignment') return { Left: 1 };
  return proxy(); } });
const real = Module._load;
Module._load = function (req, parent, ...r) {
  if (req === 'vscode') return vscode;
  if (req === 'child_process') return { execFile: (cmd, args, o, cb) => { execs.push([cmd, args]); (cb || o)(null, '', ''); return {}; } };
  if (req === './data') return { collect: async () => ({ projects: PS, plan: {}, guard: {}, ask: null }) };
  return real.call(this, req, parent, ...r); };
const ext = require(path.join(__dirname, '../vscode-ext/shipmiracle-panel/extension.js'));
const wait = ms => new Promise(r => setTimeout(r, ms));
const notice = () => { try { return JSON.parse(fs.readFileSync(path.join(ST, 'project-notice.json'), 'utf8')).text; } catch (e) { return null; } };
(async () => {
  ext.activate({ subscriptions: [], globalState: { get() {}, update() {} } }); await wait(300);
  let handler; const view = { webview: { options: {}, set html(x) {}, get html() { return ''; }, onDidReceiveMessage: f => { handler = f; return { dispose() {} }; } }, visible: true, onDidChangeVisibility: () => ({ dispose() {} }), onDidDispose: () => ({ dispose() {} }) };
  module.provider.resolveWebviewView(view); await wait(400);
  const reset = o => { PS[0] = { ...base, ...o }; terms.length = 0; sent.length = 0; execs.length = 0; try { fs.unlinkSync(path.join(ST, 'project-notice.json')); } catch (e) { /* none */ } };
  const send = async m => { await handler(m); await wait(120); };
  const SHIPM = path.join(WSD, 'bin', 'shipm');
  const good = { type: 'charter', op: 'start', project: 'demo', goal, scope: 'src/**, tests/', budget: '10', time: '3', depsMode: 'none', deps: '', ends: ['CR-012'] };

  reset(); await send({ ...good });
  check('Start: one integrated terminal named after the project, cwd = the project, shown to the owner', terms.length === 1 && terms[0].name === 'Shipmiracle · demo' && terms[0].opts.cwd === PROJ && terms[0].shown >= 1, JSON.stringify(terms.map(x => [x.name, x.opts])));
  check('Start: exactly one line PREFILLED, not run (no Enter): playbook set autopilot full --allow-open-chat && charter set ... && start', sent.length === 1 && sent[0].nl === false && /'--allow-open-chat'/.test(sent[0].text) && sent[0].text === C.joinCmds(C.charterArgv(SHIPM, 'demo', v.value && C.check({ goal, scope: 'src/**, tests/', budget: '10', time: '3', depsMode: 'none', ends: ['CR-012'] }, ['CR-012']).value, true)) && /autopilot' 'start' '--project' 'demo'$/.test(sent[0].text), JSON.stringify(sent));
  check('Start: the panel NEVER runs the charter CLI itself (no execFile of Shipmiracle at all)', !execs.some(e => /shipm/.test(e[0]) || e[1].some(a => /autopilot|charter|playbook/.test(String(a)))), JSON.stringify(execs));
  check('Start: the owner is told what happens (terminal, type yes), no file was written in the project', /Typed the commands in a terminal for demo/.test(notice() || '') && /Press Enter in the terminal to run (it|them)/.test(notice() || '') && fs.readdirSync(PROJ).length === 0, notice());
  reset({ playbook: { type: 'software', autopilot: 'full', level: 'strict' } }); await send({ ...good });
  check('Start with the level already full: no playbook-set step', sent.length === 1 && !/'playbook' 'set'/.test(sent[0].text) && /'charter' 'set'/.test(sent[0].text), JSON.stringify(sent));
  // refusals: nothing typed anywhere
  const refusals = [['level warn', { level: 'warn' }, good], ['project held', { held: true }, good], ['project working', { state: 'working' }, good], ['not software', { playbook: { type: 'content', autopilot: 'guided' } }, good], ['switch off', { autopilot: { enabled: false } }, good],
    ['no playbook', { playbook: null }, good], ['unknown project', {}, { ...good, project: 'nope' }], ['scope /etc', {}, { ...good, scope: '/etc' }], ['scope .shipmiracle', {}, { ...good, scope: '.shipmiracle/**' }], ['budget 26', {}, { ...good, budget: '26' }], ['time 9', {}, { ...good, time: '9' }],
    ['end that is not open/queued (delivered)', {}, { ...good, ends: ['CR-014'] }], ['end that does not exist', {}, { ...good, ends: ['CR-099'] }], ['no ends', {}, { ...good, ends: [] }], ['bad deps', {}, { ...good, depsMode: 'listed', deps: 'Bad Name' }], ['goal empty', {}, { ...good, goal: '' }],
    ['non-string fields', {}, { ...good, goal: { x: 1 }, scope: 5 }], ['bad op', {}, { ...good, op: 'run' }]];
  for (const [name, o, msg] of refusals) { reset(o); await send(msg); check('refused, nothing typed: ' + name, terms.length === 0 && sent.length === 0 && execs.length === 0 && (name === 'bad op' || !!notice()), JSON.stringify([terms.length, sent, notice()])); }
  reset(); await send({ ...good, goal: 'a\nb\u001b[31m' });
  check('control characters in the goal are removed, never typed (no newline reaches the terminal)', sent.length === 1 && !/[\u0000-\u001f\u007f]/.test(sent[0].text) && sent[0].text.includes("--goal=ab[31m"), JSON.stringify(sent));
  // autopilot level through the chip
  reset(); await send({ type: 'act', act: 'ap', project: 'demo', to: 'manual' });
  check('chip -> Manual: the owner command `shipm playbook set autopilot manual --project demo` is typed into a terminal; execFile never used', sent.length === 1 && sent[0].nl === false && sent[0].text === C.joinCmds(C.apLevelArgv(SHIPM, 'demo', 'manual')) && /'--allow-open-chat'/.test(sent[0].text) && execs.length === 0 && /Press Enter in the terminal to run it/.test(notice() || ''), JSON.stringify(sent));
  reset(); await send({ type: 'act', act: 'ap', project: 'demo', to: 'guided' }); check('chip -> Guided when already guided: a notice, nothing typed', sent.length === 0 && /already/.test(notice() || ''), notice());
  reset({ state: 'working' }); await send({ type: 'act', act: 'ap', project: 'demo', to: 'manual' }); check('level change is disabled while the project works', sent.length === 0 && /Not now/.test(notice() || ''), notice());
  reset({ held: true }); await send({ type: 'act', act: 'ap', project: 'demo', to: 'manual' }); check('level change is disabled for a held project', sent.length === 0);
  reset(); await send({ type: 'act', act: 'ap', project: 'demo', to: 'full' }); check('chip -> Full is the editor\'s job: the extension only points to it, types nothing', sent.length === 0 && /charter editor/.test(notice() || ''));
  // Back to guided: always allowed, even while working
  reset({ state: 'working', playbook: { type: 'software', autopilot: 'full', level: 'strict' }, autopilot: { state: 'running', enabled: true } }); await send({ type: 'act', act: 'ap', project: 'demo', to: 'guided' });
  check('Back to guided works while the run is working: `autopilot stop` (ends the run and clears the charter) then `playbook set autopilot guided`, same terminal', sent.length === 1 && sent[0].nl === false && sent[0].text === C.joinCmds(C.backToGuidedArgv(SHIPM, 'demo')) && execs.length === 0 && /Press Enter in the terminal to run it, then type guided/.test(notice() || ''), JSON.stringify(sent));
  // waiting state shown in the panel data
  const { html } = require('../vscode-ext/shipmiracle-panel/panel.js');
  const pg = html({ plan: {}, guard: {}, ask: null, projects: [{ ...base, state: 'idle', agents: [], tokens: { claudeDay: 0 }, flow: null, lastCommit: 0, ideas: base.ideas, stageLabels: null, nextAction: null, lastVerdict: null, apWait: { kind: 'full', to: '', at: Date.now() } }] }, {});
  check('the card shows "Waiting for you in the terminal" while the command is pending', /Waiting for you in the terminal/.test(pg) && /data-act="showterm"/.test(pg));
  // hard stop: the command is typed but not run; no allow: text anywhere
  reset({ playbook: { type: 'software', autopilot: 'full', level: 'strict' }, autopilot: { state: 'paused', enabled: true, stop: { id: 'H-1a2b3c', rule: 'push_public', text: 'push publicly', ts: 1 } } });
  await send({ type: 'act', act: 'allowterm', project: 'demo', id: 'H-ffffff' });
  check('hard stop: `shipm autopilot allow H-1a2b3c --project demo` is typed WITHOUT Enter (the owner runs it); the id comes from the data, not from the page', sent.length === 1 && sent[0].nl === false && sent[0].text === C.joinCmds(C.allowArgv(SHIPM, 'demo', 'H-1a2b3c')) && !/ffffff/.test(sent[0].text), JSON.stringify(sent));
  reset({ autopilot: { state: 'paused', stop: { id: 'H-1; rm -rf', text: 'x' } } }); await send({ type: 'act', act: 'allowterm', project: 'demo' }); check('hard stop: a malformed stop id types nothing', sent.length === 0);
  // approval and chat text: never
  reset(); for (const m of [{ type: 'act', act: 'plan', project: 'demo' }, { type: 'act', act: 'ap', project: 'demo', to: 'manual' }, { type: 'act', act: 'allowterm', project: 'demo' }, good, { type: 'act', act: 'start', project: 'demo', cr: 'CR-012' }]) await send(m);
  check('the extension never types approval text: nothing sent to any terminal starts with approved / allow: / charter: and no line carries a bare "approved"', sent.every(x => !/^\s*(approved|allow:|charter:)/i.test(x.text))  && !sent.some(x => /(^|[^-\w])approved([^-\w]|$)/i.test(x.text.replace(/--goal=[^ ]*/, ''))), JSON.stringify(sent.map(x => x.text.slice(0, 40))));
  const planOnly = []; reset(); await send({ type: 'act', act: 'plan', project: 'demo' }); planOnly.push(...sent);
  check('Review plan sends nothing at all to a terminal or chat (the owner types "approved")', planOnly.length === 0);
  // source checks: no execFile of the charter CLI anywhere in the extension, no hard-coded English left in panel.js for the blocked branch
  const src = fs.readFileSync(path.join(__dirname, '../vscode-ext/shipmiracle-panel/extension.js'), 'utf8'), psrc = fs.readFileSync(path.join(__dirname, '../vscode-ext/shipmiracle-panel/panel.js'), 'utf8');
  check('source: extension.js has no execFile of `shipm` with playbook/autopilot/charter arguments', !/execFile\([^)]*(bin['", ]+shipm['"])[^)]*(playbook|autopilot|charter)/.test(src.replace(/\n/g, ' ')) && !/execFile\([^)]*'autopilot'/.test(src));
  check('source: panel.js keeps no English for the blocked / failed-twice Now rows (moved to strings.js, null-guarded)', !/failed twice \(\$\{/.test(psrc) && !/\$\{a\.id\} is blocked/.test(psrc) && /now\.blocked/.test(psrc) && /now\.crFallback/.test(psrc));
  console.log(fails ? `\nFAILED: ${fails}` : '\nALL PASS'); fs.rmSync(tmp, { recursive: true, force: true }); process.exit(fails ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
