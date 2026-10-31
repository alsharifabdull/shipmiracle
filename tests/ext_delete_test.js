// The panel's "Delete project" entry exists only where the delete-project tool exists (the owner's checkout); the public build has no such tool.
// Stand-in VS Code; the tool is never run (executeTask is a recorder, the "tool" is an empty file). Run: node tests/ext_delete_test.js
const Module = require('module'); const path = require('path'); const fs = require('fs'); const os = require('os');
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'shipmiracle-del-'));
const ST = path.join(tmp, 'state'), DV = path.join(tmp, 'Developer'), WS_NO = path.join(tmp, 'ws-public'), WS_YES = path.join(tmp, 'ws-owner');
for (const d of [ST, DV, WS_NO, path.join(WS_YES, 'bin'), path.join(DV, 'demo')]) fs.mkdirSync(d, { recursive: true });
fs.writeFileSync(path.join(WS_YES, 'bin', 'delete-project'), '# stand-in, never executed\n');
Object.assign(process.env, { SHIPMIRACLE_TEST: '1', SHIPMIRACLE_EXT_STATE: ST, SHIPMIRACLE_EXT_DEV: DV, SHIPMIRACLE_DIAG_DIR: path.join(tmp, 'diag'), SHIPMIRACLE_HEAL_MS: '99999999' });
const ctxCalls = [], handlers = {}, tasks = [], popups = []; let pick = { label: 'Mac only', v: 'mac' }, confirm = 'Delete';
const proxy = () => new Proxy(function () {}, { get: (t, k) => k === 'then' ? undefined : (k === 'dispose' ? () => {} : proxy()), apply: () => proxy() });
function Task(def, scope, name, source, exec) { this.def = def; this.name = name; this.exec = exec; }
function ProcessExecution(cmd, args) { this.cmd = cmd; this.args = args; }
const vscode = new Proxy({}, { get: (t, k) => {
  if (k === 'window') return new Proxy({}, { get: (w, kk) => {
    if (kk === 'terminals') return [];
    if (kk === 'activeTerminal') return undefined;
    if (kk === 'showQuickPick') return async () => pick;
    if (kk === 'showWarningMessage') return async (m, ...r) => { popups.push(['warn', m]); return r.includes('Delete') ? confirm : undefined; };
    if (kk === 'showInformationMessage' || kk === 'showErrorMessage') return async m => { popups.push([kk, m]); };
    if (kk === 'registerWebviewViewProvider') return () => ({ dispose() {} });
    return proxy(); } });
  if (k === 'commands') return { registerCommand: (id, fn) => { handlers[id] = fn; return { dispose() {} }; }, executeCommand: async (...a) => { ctxCalls.push(a); } };
  if (k === 'tasks') return { executeTask: async t => { tasks.push(t); }, fetchTasks: async () => [] };
  if (k === 'Task') return Task;
  if (k === 'ProcessExecution') return ProcessExecution;
  if (k === 'TaskScope') return { Global: 1 };
  if (k === 'Uri') return { parse: s => ({ s }), file: f => ({ fsPath: f }) };
  if (k === 'ThemeIcon' || k === 'ThemeColor') return function (n) { this.n = n; };
  if (k === 'ViewColumn') return { Active: 1 };
  if (k === 'StatusBarAlignment') return { Left: 1 };
  return proxy(); } });
const real = Module._load;
Module._load = function (req, parent, ...r) {
  if (req === 'vscode') return vscode;
  if (req === './data') return { collect: async () => ({ projects: [], plan: {}, guard: {}, ask: null }) };
  return real.call(this, req, parent, ...r); };
let fails = 0; const check = (n, c, info = '') => { console.log((c ? 'PASS ' : 'FAIL ') + n + (c ? '' : ' ' + info)); if (!c) fails++; };
const wait = ms => new Promise(r => setTimeout(r, ms));
const EXT = path.join(__dirname, '../vscode-ext/shipmiracle-panel/extension.js'), LOC = path.join(__dirname, '../vscode-ext/shipmiracle-panel/locations.js');
const load = ws => {                                                // a fresh copy of the extension for a given workspace folder
  delete require.cache[EXT]; delete require.cache[LOC]; process.env.SHIPMIRACLE_EXT_WS = ws;
  ctxCalls.length = 0; tasks.length = 0; popups.length = 0; for (const k of Object.keys(handlers)) delete handlers[k];
  const ext = require(EXT); ext.activate({ subscriptions: [], globalState: { get() {}, update() {} } }); return ext;
};
const card = { name: 'demo', dir: path.join(DV, 'demo') };
(async () => {
  // public build: no delete-project tool
  load(WS_NO); await wait(200);
  const ctxNo = ctxCalls.filter(a => a[0] === 'setContext' && a[1] === 'shipmiracle.deleteAvailable');
  check('no delete-project tool: context shipmiracle.deleteAvailable is set to false', ctxNo.length === 1 && ctxNo[0][2] === false, JSON.stringify(ctxNo));
  check('the command stays registered (a stale menu entry cannot crash)', typeof handlers['shipmiracle.delete'] === 'function');
  await handlers['shipmiracle.delete'](card); await wait(100);
  check('no delete-project tool: the command runs nothing and says it is unavailable', tasks.length === 0 && popups.some(p => p[0] === 'showInformationMessage' && /not available/.test(p[1])), JSON.stringify([tasks.length, popups]));
  // the owner's checkout: the tool exists
  load(WS_YES); await wait(200);
  const ctxYes = ctxCalls.filter(a => a[0] === 'setContext' && a[1] === 'shipmiracle.deleteAvailable');
  check('with the delete-project tool: context shipmiracle.deleteAvailable is true', ctxYes.length === 1 && ctxYes[0][2] === true, JSON.stringify(ctxYes));
  await handlers['shipmiracle.delete'](card); await wait(100);
  check('with the delete-project tool: the confirmed flow runs the tool with the same argv as before (name, --where, --confirm yes)',
    tasks.length === 1 && tasks[0].exec.cmd === path.join(WS_YES, 'bin', 'delete-project') && JSON.stringify(tasks[0].exec.args) === JSON.stringify(['demo', '--where', 'mac', '--confirm', 'yes']), JSON.stringify(tasks.map(t => t.exec)));
  confirm = undefined; tasks.length = 0; await handlers['shipmiracle.delete'](card); await wait(100);
  check('with the delete-project tool: declining the confirmation runs nothing', tasks.length === 0);
  confirm = 'Delete'; await handlers['shipmiracle.delete']({ name: 'bad name;rm', dir: path.join(DV, 'x') }); await wait(100);
  check('with the delete-project tool: an unsafe name is still refused before anything runs', tasks.length === 0 && popups.some(p => /unexpected characters/.test(p[1] || '')));
  // the manifest follows: menu entry and palette entry both need the context key
  const pj = JSON.parse(fs.readFileSync(path.join(__dirname, '../vscode-ext/shipmiracle-panel/package.json'), 'utf8'));
  const menus = pj.contributes.menus;
  const web = (menus['webview/context'] || []).filter(m => m.command === 'shipmiracle.delete'), pal = (menus.commandPalette || []).filter(m => m.command === 'shipmiracle.delete');
  check('package.json: the project menu entry shows only when shipmiracle.deleteAvailable', web.length === 1 && /shipmiracle\.deleteAvailable/.test(web[0].when) && /webviewSection == 'project'/.test(web[0].when), JSON.stringify(web));
  check('package.json: the palette entry shows only when shipmiracle.deleteAvailable', pal.length === 1 && pal[0].when === 'shipmiracle.deleteAvailable', JSON.stringify(pal));
  fs.rmSync(tmp, { recursive: true, force: true });
  console.log(fails ? '\nFAILED: ' + fails : '\nALL PASS'); process.exit(fails ? 1 : 0);
})();
