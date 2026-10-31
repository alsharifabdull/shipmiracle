// Panel locations (vscode-ext/shipmiracle-panel/locations.js): folders and the protected rule come from the shipm config and registry, not from names in code.
// Temp folders only (SHIPMIRACLE_TEST=1 + SHIPMIRACLE_CONFIG). Run: node tests/locations_test.js
const fs = require('fs'); const os = require('os'); const path = require('path'); const { execFileSync } = require('child_process');
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'shipmiracle-loc-')); const cfg = path.join(tmp, 'cfg'); fs.mkdirSync(cfg);
const eng = path.join(tmp, 'engine-x'); const dev = path.join(tmp, 'work'); fs.mkdirSync(eng); fs.mkdirSync(path.join(dev, 'alpha'), { recursive: true });
let fails = 0; const check = (n, c, i = '') => { console.log((c ? 'PASS ' : 'FAIL ') + n + (c ? '' : ' ' + i)); if (!c) fails++; };
const probe = (config, registry) => {
  fs.writeFileSync(path.join(cfg, 'config.json'), JSON.stringify(config)); fs.writeFileSync(path.join(cfg, 'registry.json'), JSON.stringify(registry));
  const code = `const l = require(${JSON.stringify(path.join(__dirname, '../vscode-ext/shipmiracle-panel/locations.js'))}); console.log(JSON.stringify({ DEV: l.DEV, WS: l.WS, hub: l.isHub(${JSON.stringify(eng)}), alpha: l.isProtected('alpha', ${JSON.stringify(path.join(dev, 'alpha'))}), beta: l.isProtected('beta', '/nowhere/beta'), eng: l.isProtected('x', ${JSON.stringify(eng)}) }))`;
  const env = { PATH: process.env.PATH, HOME: tmp, SHIPMIRACLE_TEST: '1', SHIPMIRACLE_CONFIG: cfg };
  return JSON.parse(execFileSync(process.execPath, ['-e', code], { env, encoding: 'utf8' }));
};
let r = probe({ 'engine.dir': eng, 'paths.projects_dir': dev }, { v: 1, projects: { a1: { name: 'alpha', protected: true }, b1: { name: 'beta', protected: false } } });
check('engine.dir and paths.projects_dir come from the config', r.WS === eng && r.DEV === dev, JSON.stringify(r));
check('the hub is the folder equal to engine.dir; a registry protected project and the engine are protected, others are not', r.hub && r.alpha && r.eng && !r.beta, JSON.stringify(r));
r = probe({ 'paths.projects_dir': '~/proj' }, { v: 1, projects: {} });
check('~/... projects_dir follows the home folder; no engine.dir -> <projects>/shipmiracle; nothing is protected by name', r.DEV === path.join(tmp, 'proj') && r.WS === path.join(tmp, 'proj', 'shipmiracle') && !r.alpha && !r.beta, JSON.stringify(r));
r = probe({}, { v: 1, projects: {} });
check('empty config -> ~/Developer and ~/Developer/shipmiracle', r.DEV === path.join(tmp, 'Developer') && r.WS === path.join(tmp, 'Developer', 'shipmiracle'), JSON.stringify(r));
const src = ['data.js', 'extension.js', 'locations.js', 'preview.js'].map(f => fs.readFileSync(path.join(__dirname, '../vscode-ext/shipmiracle-panel', f), 'utf8')).join('\n');
const NAMES = new RegExp(['Sha' + 'jarah', 'Home-Intel' + 'ligence', 'AI-Work' + 'space', 'al' + 'sharif'].join('|'), 'i'), NAMES_G = new RegExp(NAMES.source, 'gi');   // built from parts: this file carries no name itself
check('no project or account name is in the panel code', !NAMES.test(src), (src.match(NAMES_G) || []).join());
fs.rmSync(tmp, { recursive: true, force: true });
console.log(fails ? 'FAILED: ' + fails : 'ALL PASS'); process.exit(fails ? 1 : 0);
