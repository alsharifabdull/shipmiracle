// A throw-away LIVE world for the panel tests: fresh folders for HOME, config, state, workspace and projects (never the owner's), the fixture builder
// tests/panel_live_fixture.py run against them (real engine APIs), and the process environment pointed at them BEFORE data.js is loaded.
// Every child process gets the FULL isolation env (SHIPMIRACLE_TEST, SHIPMIRACLE_HOME, HOME, SHIPMIRACLE_CONFIG, SHIPMIRACLE_STATE, SHIPMIRACLE_WS, SHIPMIRACLE_DEV, CLAUDE_CONFIG_DIR); CLAUDECODE is dropped.
// The panel code is pointed at the sandbox with its own test seams (SHIPMIRACLE_EXT_STATE / SHIPMIRACLE_EXT_DEV, read only under SHIPMIRACLE_TEST=1); SHIPMIRACLE_EXT_WS is the checkout
// (read-only: bin/shipm and config/flow.json), so the panel runs the real `shipm report panel`.
require('./shipmiracle_isolation');
const fs = require('fs'), os = require('os'), path = require('path'), { spawnSync } = require('child_process');
const ROOT = path.join(__dirname, '..');

function make(profile) {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'shipmiracle-live-')));
  for (const d of ['h/.claude', 'c', 's', 'w', 'dev']) fs.mkdirSync(path.join(root, d), { recursive: true });
  fs.writeFileSync(path.join(root, 'h', '.gitconfig'), '[user]\n\tname = Shipmiracle test\n\temail = test@example.com\n[init]\n\tdefaultBranch = main\n[commit]\n\tgpgsign = false\n');
  const env = { ...process.env };
  for (const k of Object.keys(env)) if (k.startsWith('SHIPMIRACLE_') || k === 'CLAUDECODE' || k === 'CLAUDE_CONFIG_DIR') delete env[k];
  env.PATH = '/opt/homebrew/bin:/usr/local/bin:' + (process.env.PATH || '/usr/bin:/bin');
  Object.assign(env, { SHIPMIRACLE_TEST: '1', HOME: root + '/h', SHIPMIRACLE_HOME: root + '/h', CLAUDE_CONFIG_DIR: root + '/h/.claude', SHIPMIRACLE_CONFIG: root + '/c', SHIPMIRACLE_STATE: root + '/s', SHIPMIRACLE_WS: root + '/w', SHIPMIRACLE_DEV: root + '/dev',
    SHIPMIRACLE_EXT_STATE: root + '/s', SHIPMIRACLE_EXT_DEV: root + '/dev', SHIPMIRACLE_EXT_WS: ROOT, GIT_CONFIG_NOSYSTEM: '1', TZ: 'UTC' });
  const w = { root, env, dev: root + '/dev', state: root + '/s', dirs: [], cleanup() { try { fs.rmSync(root, { recursive: true, force: true }); } catch (e) { /* best effort */ } } };
  w.run = (cmd, args, o = {}) => spawnSync(cmd, args, { env, encoding: 'utf8', timeout: 180000, stdio: ['ignore', 'pipe', 'pipe'], cwd: ROOT, maxBuffer: 64 << 20, ...o });
  w.shipm = (...args) => w.run(path.join(ROOT, 'bin', 'shipm'), args);
  if (profile) {
    const r = w.run('python3', [path.join(__dirname, 'panel_live_fixture.py'), profile]);
    if (r.status !== 0) throw new Error('fixture builder failed: ' + (r.stderr || r.stdout).slice(0, 600));
    w.manifest = JSON.parse(r.stdout.trim().split('\n').pop()); w.dirs = w.manifest.projects;
  }
  process.on('exit', w.cleanup);
  return w;
}
// Point THIS process at the sandbox (os.homedir() follows $HOME); call before require('../vscode-ext/shipmiracle-panel/data.js').
function enter(w) { for (const k of Object.keys(process.env)) if (k.startsWith('SHIPMIRACLE_') || k === 'CLAUDE_CONFIG_DIR') delete process.env[k]; Object.assign(process.env, w.env); return w; }

module.exports = { make, enter, ROOT };
