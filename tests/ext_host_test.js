// Host awareness of the extension (task E10; parity P-1000..P-1003): which Claude chat is a terminal on darwin / linux / WSL / win32 with FAKE process tables (procx.js), the Windows / WSL
// host decision and the notice text (hostx.js), `os.level` read only when the CLI sends it, and the real extension activated on a fake win32 / Remote-WSL / linux host (no crash, the page carries the
// notice). Never starts a browser. Run: node tests/ext_host_test.js
require('./shipmiracle_isolation').apply();
const Module = require('module'), path = require('path'), fs = require('fs'), os = require('os');
const EXT = path.join(__dirname, '../vscode-ext/shipmiracle-panel');
let fails = 0, n = 0; const check = (name, c, info = '') => { n++; console.log((c ? 'PASS ' : 'FAIL ') + name + (c ? '' : ' ' + info)); if (!c) fails++; };
const wait = ms => new Promise(r => setTimeout(r, ms));
const P = require(path.join(EXT, 'procx.js')), HX = require(path.join(EXT, 'hostx.js')), SETUP = require(path.join(EXT, 'setup.js'));
const DEV = '/home/u/Developer';
const projectOfPath = p => { const rel = p && path.posix.relative(DEV, p); return rel && !rel.startsWith('..') && !path.posix.isAbsolute(rel) ? rel.split('/')[0] : ''; };

// ---- a fake machine: a process table, the calls made, and a /proc/<pid>/cwd table
function machine(platform, procs, cwds = {}) {
  const calls = [], reads = [];
  const run = async (file, args) => {
    calls.push([file, ...args].join(' '));
    if (file === '/bin/ps' || file === '/usr/bin/ps') {
      const pid = String(args[args.length - 1]), pr = procs[pid];
      if (args[0] === '-o') return pr ? pr.cmd + '\n' : '';
      if (args[0] === 'eww') return pr && !pr.noEnv ? 'PID TTY\n' + pr.cmd + ' ' + (pr.env || '') + '\n' : '';
      return '';
    }
    if (file === 'lsof') { const pid = String(args[2]); return cwds[pid] ? 'p' + pid + '\nn' + cwds[pid] + '\n' : ''; }
    return '';
  };
  const readlink = async p => { reads.push(p); const m = /^\/proc\/(\d+)\/cwd$/.exec(p); return m && cwds[m[1]] ? cwds[m[1]] + (cwds[m[1] + 'del'] ? ' (deleted)' : '') : ''; };
  const px = P.make({ platform: () => platform, run, readlink, psFile: '/bin/ps', projectOfPath });
  return { px, calls, reads };
}
const term = pid => ({ processId: Promise.resolve(pid) });

(async () => {
  // ---- darwin: ps for the command, ps eww for the port, lsof for the folder
  let m = machine('darwin', { 100: { cmd: 'claude --name alpha --continue', env: 'CLAUDE_CODE_SSE_PORT=4242 HOME=/home/u' }, 101: { cmd: '/home/u/.local/bin/claude', env: 'CLAUDE_CODE_SSE_PORT=7' }, 102: { cmd: '-zsh', env: '' }, 103: { cmd: 'claude', noEnv: true } },
    { 101: DEV + '/beta', 103: DEV + '/gamma' });
  let r = await m.px.inspect(term(100));
  check('darwin: a chat started with --name gives its project and its IDE port (ps eww)', r && r.project === 'alpha' && r.port === '4242' && r.portKnown === true && r.pid === 100, JSON.stringify(r));
  r = await m.px.inspect(term(101));
  check('darwin: a chat without --name is found by its folder (lsof)', r && r.project === 'beta' && r.port === '7' && m.calls.some(c => c.startsWith('lsof ')), JSON.stringify(r));
  check('darwin: a shell is not a chat; a chat whose environment cannot be read has portKnown false (never a guessed port)', (await m.px.inspect(term(102))) === null && (await m.px.inspect(term(103))).portKnown === false && (await m.px.inspect(term(103))).port === '');

  // ---- linux: portable ps flags only, /proc/<pid>/cwd, NEVER the environment
  m = machine('linux', { 200: { cmd: 'claude --name alpha --continue', env: 'CLAUDE_CODE_SSE_PORT=4242 SECRET_TOKEN=abc' }, 201: { cmd: '/home/u/.local/bin/claude' }, 202: { cmd: 'bash' }, 203: { cmd: 'claude' }, 204: { cmd: 'claude' } },
    { 201: DEV + '/beta', 203: '/tmp/elsewhere', 204: DEV + '/gone', '204del': 1 });
  r = await m.px.inspect(term(200));
  check('linux: --name chat -> project; the port is "" and portKnown false (the environment is never read)', r && r.project === 'alpha' && r.port === '' && r.portKnown === false, JSON.stringify(r));
  check('linux: no `ps eww` / `ps e` call, no /proc/<pid>/environ read, only `ps -o command= -p <pid>`', m.calls.every(c => /^\/bin\/ps -o command= -p \d+$/.test(c)) && m.reads.every(p => !/environ/.test(p)), JSON.stringify([m.calls, m.reads]));
  r = await m.px.inspect(term(201));
  check('linux: a chat without --name is found through /proc/<pid>/cwd (no lsof)', r && r.project === 'beta' && m.reads.includes('/proc/201/cwd') && !m.calls.some(c => c.startsWith('lsof')), JSON.stringify([r, m.reads]));
  check('linux: a shell, a chat outside the projects folder, an unreadable process: null (unknown), no throw', (await m.px.inspect(term(202))) === null && (await m.px.inspect(term(203))) === null && (await m.px.inspect(term(999))) === null);
  check('linux: "(deleted)" is cut from a folder that was removed', (await m.px.cwdOfPid(204)) === DEV + '/gone' && (await m.px.cwdOfPid(204)) !== '');

  // ---- WSL is linux to node: same code path, plus a Windows-mounted folder is just a path
  m = machine('linux', { 300: { cmd: 'claude --continue' } }, { 300: '/mnt/c/data/Developer/x' });
  check('wsl: a folder under /mnt/c is read through /proc like any other and is simply not one of the projects -> null', (await m.px.inspect(term(300))) === null && (await m.px.cwdOfPid(300)) === '/mnt/c/data/Developer/x');

  // ---- win32 / anything else: unknown, no process is started at all
  for (const plat of ['win32', 'freebsd', 'sunos']) {
    m = machine(plat, { 400: { cmd: 'claude --name alpha' } }, { 400: DEV + '/a' });
    check(`${plat}: inspect -> null and cwdOfPid -> "" without starting any process or reading /proc`, (await m.px.inspect(term(400))) === null && (await m.px.cwdOfPid(400)) === '' && m.calls.length === 0 && m.reads.length === 0, JSON.stringify([m.calls, m.reads]));
  }
  m = machine('linux', { 1: { cmd: 'claude --name a' } }, { 1: DEV + '/a' });
  const bad = [0, -5, '1;rm', 'abc', 1.5, null, undefined, '1 2', 99999999999];
  let all = true; for (const b of bad) { if ((await m.px.cwdOfPid(b)) !== '' || (await m.px.inspect(term(b))) !== null) all = false; }
  check('a pid that is not a plain positive number (0, -5, "1;rm", 1.5, null ...) is never looked up', all && m.calls.length === 0 && m.reads.length === 0, JSON.stringify([m.calls, m.reads]));
  const hang = { processId: new Promise(() => {}) }, boom = { get processId() { throw new Error('x'); } };
  const mh = P.make({ platform: () => 'linux', run: async () => '', readlink: async () => '', psFile: '/bin/ps', projectOfPath, within: (p, ms) => Promise.race([Promise.resolve(p), new Promise(r => setTimeout(() => r(undefined), 30))]) });
  check('a terminal whose process id never arrives, or throws, is "not a chat"', (await mh.inspect(hang)) === null && (await mh.inspect(boom)) === null);
  const code = fs.readFileSync(path.join(EXT, 'procx.js'), 'utf8').split('\n').filter(l => !/^\s*\/\//.test(l)).join('\n');
  check('source: procx.js has no code that mentions a process environment file', !/environ/.test(code.replace(/\/\/.*$/gm, '')));
  const ext0 = fs.readFileSync(path.join(EXT, 'extension.js'), 'utf8');
  check('source: extension.js no longer calls ps / lsof itself (all in procx.js) and has no /usr/bin/python3 or /usr/bin/git literal outside the lookup list', !/execFile\('\/bin\/ps'|execFile\('lsof'/.test(ext0) && (ext0.match(/'\/usr\/bin\/(python3|git)'/g) || []).length === 2);

  // ---- hostx: the host decision
  const H = (platform, remoteName) => HX.hostOf({ platform, remoteName });
  check('host: win32 -> windows (also over Remote-SSH to a Windows machine); linux + wsl -> wsl; linux/darwin otherwise -> other',
    H('win32').kind === 'windows' && H('win32', 'ssh-remote').kind === 'windows' && H('linux', 'wsl').kind === 'wsl' && H('linux').kind === 'other' && H('darwin', 'ssh-remote').kind === 'other' && H('darwin').kind === 'other');
  check('host: chat health is "known" only on darwin; unknown everywhere else', H('darwin').chatHealth === 'known' && ['linux', 'win32'].every(p => H(p).chatHealth === 'unknown') && H('linux', 'wsl').chatHealth === 'unknown');
  check('host: hostile or odd input becomes a harmless default (remote name must be a plain word)', HX.hostOf({ platform: 5, remoteName: '<script>' }).remote === '' && HX.hostOf().kind === 'other' && HX.cleanHost({ platform: 'win32', remote: 'x"y', kind: 'wsl' }).kind === 'windows' && HX.cleanHost(null).chatHealth === 'known' && HX.cleanHost('x').kind === 'other');
  const cliLine = 'This computer: Windows 11 (native). Shipmiracle runs inside WSL2 here: run "wsl --install", open Ubuntu, then install Shipmiracle there. Nothing was changed.';
  check('hint: the CLI\'s own os.line is used when os.kind is windows; the fallback only when the CLI sent nothing (or not a windows line)',
    HX.hintOf({ kind: 'windows', line: cliLine }) === cliLine && HX.hintOf(null) === HX.FALLBACK_HINT && HX.hintOf({ kind: 'macos', line: 'This computer: macOS' }) === HX.FALLBACK_HINT && HX.hintOf({ kind: 'windows', line: '' }) === HX.FALLBACK_HINT);
  const srcs = fs.readdirSync(EXT).filter(f => f.endsWith('.js')).filter(f => /wsl --install/.test(fs.readFileSync(path.join(EXT, f), 'utf8')));
  check('the fallback install hint exists in ONE file of the panel (never hard-coded twice)', srcs.join() === 'hostx.js', srcs.join());
  // ---- hostx: the notice
  const S = require(path.join(EXT, 'strings.js')), esc = x => String(x).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
  const t = (k, o) => { const v = k.split('.').reduce((a, x) => (a == null ? a : a[x]), S); return typeof v === 'string' ? v.replace(/\{(\w+)\}/g, (_, q) => (o && o[q] != null ? o[q] : '')) : k; };
  const D = { t, esc };
  const win = HX.notice(H('win32'), null, D, 'setup');
  check('windows notice: plain words ("not supported yet", "WSL 2"), the fallback hint when the CLI is silent, role=status, no markup from data', /not supported yet/.test(win) && /WSL 2/.test(win) && win.includes(esc(HX.FALLBACK_HINT)) && /role="status"/.test(win) && !/<script|onerror/.test(win));
  const winCli = HX.notice(H('win32'), { kind: 'windows', line: '<img src=x onerror=alert(1)> ' + cliLine }, D, 'projects');
  check('windows notice with the CLI line: the CLI text is shown, escaped (hostile markup stays text)', winCli.includes('runs inside WSL2 here') && !/<img/.test(winCli) && /&lt;img/.test(winCli) && /data-where="projects"/.test(winCli));
  check('wsl: NO "experimental" note unless the CLI says so; with os.level "experimental" the note shows (Setup only)',
    HX.notice(H('linux', 'wsl'), { kind: 'wsl', line: 'x' }, D, 'setup') === '' && HX.notice(H('linux'), { kind: 'linux', line: 'x', level: '' }, D, 'setup') === ''
    && /experimental/.test(HX.notice(H('linux', 'wsl'), { kind: 'wsl', line: 'x', level: 'experimental' }, D, 'setup')) && /experimental/.test(HX.notice(H('linux'), { kind: 'linux', line: 'x', level: 'experimental' }, D, 'setup'))
    && HX.notice(H('linux', 'wsl'), { kind: 'wsl', line: 'x', level: 'experimental' }, D, 'projects') === '');
  check('macOS never gets a host notice, even if a level is present', HX.notice(H('darwin'), { kind: 'macos', line: 'x', level: 'experimental' }, D, 'setup') === '');
  check('Health note exists only where the chat check is unknown, and says "unknown"', /unknown/.test(HX.healthNote(H('linux'), D)) && HX.healthNote(H('darwin'), D) === '' && HX.healthNote(null, D) === '');
  // ---- the CLI's os field
  const row = { n: 0, id: 'engine', title: 'Engine', need: 'required', state: 'green', detail: '', connect: { kind: 'hint', text: '' } };
  const pj = o => SETUP.parseCheck(JSON.stringify({ v: 1, ready: true, rows: [row], os: o }));
  check('setup.js: os.level is passed on only when the CLI sends a plain word; absent -> "" (the panel invents nothing)',
    pj({ kind: 'wsl', line: 'x', level: 'experimental' }).os.level === 'experimental' && pj({ kind: 'wsl', line: 'x' }).os.level === '' && pj({ kind: 'wsl', line: 'x', level: '<b>' }).os.level === '' && pj({ kind: 'wsl', line: 'x', level: 7 }).os.level === '');

  // ---- the real extension on a fake host
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'shipmiracle-host-')), ST = path.join(tmp, 'state'), WSD = path.join(tmp, 'ws'), DV = path.join(tmp, 'Dev');
  for (const d of [ST, path.join(WSD, 'bin'), DV]) fs.mkdirSync(d, { recursive: true });
  Object.assign(process.env, { SHIPMIRACLE_TEST: '1', SHIPMIRACLE_EXT_STATE: ST, SHIPMIRACLE_EXT_WS: WSD, SHIPMIRACLE_EXT_DEV: DV, SHIPMIRACLE_DIAG_DIR: path.join(tmp, 'diag'), SHIPMIRACLE_HEAL_MS: '99999999', SHIPMIRACLE_EXT_SETUP: '1' });
  let remoteName; let html = '', calls = [], cliOut = null;
  const proxy = () => new Proxy(function () {}, { get: (_, k) => k === 'then' ? undefined : (k === 'dispose' ? () => {} : proxy()), apply: () => proxy() });
  const cmds = {}; let provider;
  const vscode = new Proxy({}, { get: (_, k) => {
    if (k === 'env') return { get remoteName() { return remoteName; }, openExternal: () => {}, clipboard: { writeText: async () => {} } };
    if (k === 'window') return new Proxy({}, { get: (w, kk) => kk === 'terminals' ? [] : kk === 'registerWebviewViewProvider' ? (id, prov) => { provider = prov; return { dispose() {} }; } : kk === 'activeTerminal' ? undefined : proxy() });
    if (k === 'workspace') return { workspaceFolders: undefined, getConfiguration: () => ({ get: (_k, d) => d }), onDidChangeConfiguration: () => ({ dispose() {} }) };
    if (k === 'commands') return { registerCommand: (id, fn) => { cmds[id] = fn; return { dispose() {} }; }, executeCommand: async () => {} };
    if (k === 'Uri') return { parse: s => ({ s }), file: f => ({ fsPath: f }) };
    if (k === 'ThemeIcon' || k === 'ThemeColor') return function (nn) { this.n = nn; };
    if (k === 'StatusBarAlignment') return { Left: 1 };
    return proxy(); } });
  // on a host without the tools every program is missing: ENOENT, like native Windows
  const fakeExec = (cmd, args, opts, cb) => { cb = cb || opts; calls.push(cmd); if (cliOut !== null && String(cmd).endsWith(path.join('bin', 'shipm')) && args[0] === 'init') { cb(null, cliOut, ''); return {}; } cb(Object.assign(new Error('spawn ' + cmd + ' ENOENT'), { code: 'ENOENT' }), '', ''); return {}; };
  const real = Module._load;
  Module._load = function (req, parent, ...rest) {
    if (req === 'vscode') return vscode;
    if (req === 'child_process') return { execFile: fakeExec, spawn: () => proxy() };
    if (req === './data') return { collect: async () => ({ projects: [], plan: { meters: [] }, guard: {}, ask: null }) };
    return real.call(this, req, parent, ...rest); };
  const ext = require(path.join(EXT, 'extension.js'));
  const pd = Object.getOwnPropertyDescriptor(process, 'platform'), setP = v => Object.defineProperty(process, 'platform', { value: v });
  const view = { webview: { options: {}, set html(v) { html = v; }, get html() { return html; }, onDidReceiveMessage: () => ({ dispose() {} }) }, visible: true, onDidChangeVisibility: () => ({ dispose() {} }), onDidDispose: () => ({ dispose() {} }) };
  const thrown = []; process.on('unhandledRejection', e => thrown.push(e)); process.on('uncaughtException', e => thrown.push(e));
  const hostPage = async (platform, remote, cli) => {
    setP(platform); remoteName = remote; html = ''; cliOut = cli === undefined ? null : cli;
      ext.activate({ subscriptions: [], globalState: { get() {}, update() {} } }); await wait(250);
    provider.resolveWebviewView(view); await wait(900);
    return html;
  };
  try {
    let page = await hostPage('win32', undefined);
    const noPanel = !/Shipmiracle could not draw/.test(page);
    check('win32 host: the extension activates and draws (no crash, no "could not draw" page, no unhandled error) with every tool missing', page.length > 5000 && noPanel && thrown.length === 0, String(thrown[0] && thrown[0].stack || page.slice(0, 200)));
    check('win32 host: the Projects empty state and the Setup tab carry the Windows notice with the fallback hint (the CLI cannot run here)',
      (page.match(/data-host="windows"/g) || []).length === 2 && /data-where="projects"/.test(page) && /data-where="setup"/.test(page) && page.includes(esc(HX.FALLBACK_HINT)) && !/No projects yet/.test(page));
    check('win32 host: the Health tab says chat health is unknown', /data-host="chat-unknown"/.test(page));
    page = await hostPage('win32', undefined, JSON.stringify({ v: 1, ready: false, os: { kind: 'windows', line: cliLine }, rows: [row] }));
    await wait(300); page = html;
    check('win32 host with an answering CLI: the Setup notice shows the CLI\'s own line', page.includes(esc(cliLine)) && !page.includes(esc(HX.FALLBACK_HINT)), page.includes(esc(cliLine)) + '');
    page = await hostPage('linux', 'wsl');
    check('Remote-WSL host: no Windows notice, no "experimental" note (the CLI did not say so), chat health unknown', !/data-host="windows"/.test(page) && !/data-host="experimental"/.test(page) && /data-host="chat-unknown"/.test(page) && page.length > 5000);
    page = await hostPage('linux', 'wsl', JSON.stringify({ v: 1, ready: false, os: { kind: 'wsl', line: 'This computer: Ubuntu 24.04 on Windows (WSL 2).', level: 'experimental' }, rows: [row] }));
    await wait(300); page = html;
    check('Remote-WSL host with os.level "experimental" from the CLI: the experimental note is in the Setup tab', /data-host="experimental"/.test(page) && /experimental/.test(page));
    page = await hostPage('darwin', undefined);
    check('macOS host: no host notice at all, no chat-health line', !/data-host=/.test(page.replace(/\.hostn\b[^{]*\{/g, '')) && page.length > 5000);
    check('no unhandled error on any host', thrown.length === 0, String(thrown[0]));
  } finally { Object.defineProperty(process, 'platform', pd); }
  console.log(fails ? `\nFAILED: ${fails} of ${n}` : `\nALL PASS (${n})`); fs.rmSync(tmp, { recursive: true, force: true }); process.exit(fails ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
