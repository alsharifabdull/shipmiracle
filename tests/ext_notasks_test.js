// shipmiracle.check and shipmiracle.newProject work with no tasks.json (fetchTasks returns nothing): they launch their own script.
// Run: node tests/ext_notasks_test.js
require('./shipmiracle_isolation').apply();
const Module = require('module'); const path = require('path'); const fs = require('fs'); const os = require('os');
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'shipmiracle-nt-'));
const ST = path.join(tmp, 'state'), DV = path.join(tmp, 'Developer'), WSD = path.join(tmp, 'ws');
for (const d of [ST, DV, WSD]) fs.mkdirSync(d, { recursive: true });
Object.assign(process.env, { SHIPMIRACLE_TEST: '1', SHIPMIRACLE_EXT_STATE: ST, SHIPMIRACLE_EXT_DEV: DV, SHIPMIRACLE_EXT_WS: WSD, SHIPMIRACLE_DIAG_DIR: path.join(tmp, 'diag'), SHIPMIRACLE_HEAL_MS: '99999999' });
const handlers = {}, tasks = [], popups = [], execs = []; let name = 'My Notes';
const proxy = () => new Proxy(function () {}, { get: (t, k) => k === 'then' ? undefined : (k === 'dispose' ? () => {} : proxy()), apply: () => proxy() });
function Task(def, scope, nm, source, exec) { this.def = def; this.name = nm; this.exec = exec; }
function ProcessExecution(cmd, args) { this.cmd = cmd; this.args = args; }
const vscode = new Proxy({}, { get: (t, k) => {
  if (k === 'window') return new Proxy({}, { get: (w, kk) => {
    if (kk === 'terminals') return [];
    if (kk === 'activeTerminal') return undefined;
    if (kk === 'showInputBox') return async () => name;
    if (kk === 'showQuickPick') return async () => 'notes';
    if (/^show(Information|Warning|Error)Message$/.test(kk)) return async m => { popups.push(m); };
    if (kk === 'registerWebviewViewProvider') return () => ({ dispose() {} });
    return proxy(); } });
  if (k === 'commands') return { registerCommand: (id, fn) => { handlers[id] = fn; return { dispose() {} }; }, executeCommand: async () => {} };
  if (k === 'tasks') return { executeTask: async t => { tasks.push(t); }, fetchTasks: async () => [] };   // the user has no tasks.json
  if (k === 'Task') return Task; if (k === 'ProcessExecution') return ProcessExecution; if (k === 'TaskScope') return { Global: 1 };
  if (k === 'Uri') return { parse: s => ({ s }), file: f => ({ fsPath: f }) };
  if (k === 'ThemeIcon' || k === 'ThemeColor') return function (n) { this.n = n; };
  if (k === 'ViewColumn') return { Active: 1 };
  if (k === 'StatusBarAlignment') return { Left: 1 };
  return proxy(); } });
const fakeExec = (cmd, args, opts, cb) => { if (cmd === '/bin/bash') execs.push({ cmd, args }); (cb || opts)(null, '', ''); return {}; };
const real = Module._load;
Module._load = function (req, parent, ...r) {
  if (req === 'vscode') return vscode;
  if (req === 'child_process') return { execFile: fakeExec };
  if (req === './data') return { collect: async () => ({ projects: [], plan: {}, guard: {}, ask: null }) };
  return real.call(this, req, parent, ...r); };
let fails = 0; const check = (n, c, info = '') => { console.log((c ? 'PASS ' : 'FAIL ') + n + (c ? '' : ' ' + info)); if (!c) fails++; };
const wait = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  require(path.join(__dirname, '../vscode-ext/shipmiracle-panel/extension.js')).activate({ subscriptions: [], globalState: { get() {}, update() {} } });
  await wait(200);
  await handlers['shipmiracle.check'](); await wait(50);
  check('Check & update runs bin/daily --show with no tasks.json', tasks.length === 1 && tasks[0].exec.cmd === path.join(WSD, 'bin', 'daily') && JSON.stringify(tasks[0].exec.args) === '["--show"]', JSON.stringify(tasks.map(t => t.exec)));
  check('no "Task not found" warning', popups.length === 0, JSON.stringify(popups));
  tasks.length = 0;
  await handlers['shipmiracle.newProject'](); await wait(300);
  check('New project runs bin/new-project with a tidied name and the chosen type, no tasks.json', execs.length === 1 && JSON.stringify(execs[0].args) === JSON.stringify([path.join(WSD, 'bin', 'new-project'), 'my-notes', '--type', 'notes', '--no-open']), JSON.stringify(execs));
  check('no "Task not found" warning (new project)', popups.length === 0, JSON.stringify(popups));
  execs.length = 0; name = '';
  await handlers['shipmiracle.newProject'](); await wait(100);
  check('cancelled name runs nothing', execs.length === 0);
  console.log(fails ? 'FAILED ' + fails : 'ALL PASS'); process.exit(fails ? 1 : 0);
})();
