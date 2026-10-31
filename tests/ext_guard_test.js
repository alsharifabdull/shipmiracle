// Safe by construction: SHIPMIRACLE_EXT_* set without SHIPMIRACLE_TEST=1 must never write to the real workspace or state folder.
// Everything here runs in a child process with a THROW-AWAY HOME; the real files are never touched (and checked before/after).
// Run: node tests/ext_guard_test.js
const cp = require('child_process'), fs = require('fs'), os = require('os'), path = require('path'), crypto = require('crypto');
const home = fs.mkdtempSync(path.join(os.tmpdir(), 'shipmiracle-guard-home-'));
const WSR = path.join(home, 'Developer/AI-Workspace'), STR = path.join(home, '.local/state/shipmiracle');
fs.mkdirSync(path.join(WSR, 'config'), { recursive: true }); fs.mkdirSync(STR, { recursive: true });
const FLOW = '{\n  "default": "strict",\n  "projects": {}\n}\n'; fs.writeFileSync(path.join(WSR, 'config/flow.json'), FLOW);
const child = `
const Module = require('module'), path = require('path'), fs = require('fs'); const gitCalls = []; let handler, prov;
const proxy = () => new Proxy(function () {}, { get: (t, k) => k === 'then' ? undefined : (k === 'dispose' ? () => {} : proxy()), apply: () => proxy() });
const vscode = new Proxy({}, { get: (t, k) => { if (k === 'window') return new Proxy({}, { get: (w, kk) => kk === 'terminals' ? [] : kk === 'activeTerminal' ? undefined : kk === 'registerWebviewViewProvider' ? (id, p) => { prov = p; return { dispose() {} }; } : proxy() });
  if (k === 'commands') return { registerCommand: () => ({ dispose() {} }), executeCommand: async () => {} }; if (k === 'Uri') return { parse: s => ({ s }), file: f => ({ fsPath: f }) }; if (k === 'ThemeIcon' || k === 'ThemeColor') return function () {}; if (k === 'ViewColumn') return { Active: 1 }; if (k === 'StatusBarAlignment') return { Left: 1 }; return proxy(); } });
const real = Module._load;
Module._load = function (req, parent, ...r) { if (req === 'vscode') return vscode; if (req === 'child_process') return { execFile: (c, a, o, cb) => { gitCalls.push(c + ' ' + a.join(' ')); (cb || o)(null, '', ''); return {}; } };
  if (req === './data') return { collect: async () => ({ projects: [{ name: 'b', dir: '/d/b', stack: 'web', state: 'idle', agents: [], tokens: {}, ideas: { open: [], evaluated: [], done: 0, dropped: 0 }, held: false }], plan: {}, guard: {}, ask: null }) }; return real.call(this, req, parent, ...r); };
const ext = require(${JSON.stringify(path.resolve(__dirname, '../vscode-ext/shipmiracle-panel/extension.js'))});
(async () => { ext.activate({ subscriptions: [], globalState: { get() {}, update() {} } }); await new Promise(r => setTimeout(r, 300));
  const view = { webview: { options: {}, set html(v) {}, get html() { return ''; }, onDidReceiveMessage: f => { handler = f; return { dispose() {} }; } }, visible: true, onDidChangeVisibility: () => ({ dispose() {} }), onDidDispose: () => ({ dispose() {} }) };
  prov.resolveWebviewView(view); await new Promise(r => setTimeout(r, 300));
  await handler({ type: 'level', project: 'b', level: 'warn' }); await handler({ type: 'newproject', name: 'zzz', kind: 'web', about: '' });
  await handler({ type: 'health', op: 'fix', id: 'abc' }); await handler({ type: 'health', op: 'dismiss-notice', id: '' }); await handler({ type: 'idea', op: 'done', project: 'b', id: 'F1' });
  await new Promise(r => setTimeout(r, 300)); console.log(JSON.stringify({ git: gitCalls.filter(c => /git|new-project|shipm-watch|idea/.test(c)) })); process.exit(0); })();`;
const snap = dir => { const o = {}; const walk = d => { for (const f of fs.readdirSync(d, { withFileTypes: true })) { const p = path.join(d, f.name); if (f.isDirectory()) walk(p); else o[p.replace(home, '')] = crypto.createHash('md5').update(fs.readFileSync(p)).digest('hex'); } }; walk(dir); return o; };
let fails = 0; const check = (n, c, info = '') => { console.log((c ? 'PASS ' : 'FAIL ') + n + (c ? '' : ' ' + info)); if (!c) fails++; };
const run = env => cp.spawnSync(process.execPath, ['-e', child], { env: { PATH: process.env.PATH, HOME: home, ...env }, encoding: 'utf8', timeout: 60000 });
const before = JSON.stringify([snap(WSR), fs.readdirSync(STR)]);
let r = run({ SHIPMIRACLE_EXT_WS: WSR, SHIPMIRACLE_EXT_STATE: STR});          // half-configured: no SHIPMIRACLE_TEST
const out = JSON.parse(r.stdout.trim().split('\n').pop() || '{}');
check('SHIPMIRACLE_EXT_* without SHIPMIRACLE_TEST=1: flow.json untouched, no events file, no notice, no state file written', fs.readFileSync(path.join(WSR, 'config/flow.json'), 'utf8') === FLOW && JSON.stringify([snap(WSR), fs.readdirSync(STR)]) === before, r.stderr.slice(-300));
check('...and no git, new-project, watcher or idea tool was started', Array.isArray(out.git) && out.git.length === 0, JSON.stringify(out));
const trace = (() => { try { return fs.readFileSync(path.join(home, '.local/state/shipmiracle-diag/panel-trace.log'), 'utf8'); } catch (e) { return ''; } })();
check('...and exactly one trace line says why', (trace.match(/SHIPMIRACLE_EXT_\* set without SHIPMIRACLE_TEST=1: refusing to write/g) || []).length === 1, trace);
r = run({ SHIPMIRACLE_TEST: '1', SHIPMIRACLE_EXT_WS: WSR, SHIPMIRACLE_EXT_STATE: STR, SHIPMIRACLE_DIAG_DIR: path.join(home, 'diag2') });
check('control: with SHIPMIRACLE_TEST=1 the same run does write (level change in the throw-away workspace)', /"b": "warn"/.test(fs.readFileSync(path.join(WSR, 'config/flow.json'), 'utf8')), r.stderr.slice(-300));
const src = fs.readFileSync(path.join(__dirname, '../vscode-ext/shipmiracle-panel/extension.js'), 'utf8');
check('every writer is behind the guard (level, newproject, health, idea, notices, one-shot files)', ['async function levelAction', 'async function newProjectAction', 'async function runFix', 'async function healthAction', 'async function ideaAction', 'const writeNotice', 'const pnotice', 'function oneShot'].every(k => { const i = src.indexOf(k); return i > 0 && src.slice(i, i + 400).includes('leakBlock()'); }));
fs.rmSync(home, { recursive: true, force: true });
console.log(fails ? '\nFAILED: ' + fails : '\nALL PASS'); process.exit(fails ? 1 : 0);
