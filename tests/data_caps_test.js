// Capability flags come from the engine once, even when no project has a playbook (no .shipmiracle folder, no autopilot file).
// Run: node tests/data_caps_test.js
require('./shipmiracle_isolation').apply();
const fs = require('fs'); const os = require('os'); const path = require('path');
const ROOT = fs.mkdtempSync(path.join(os.tmpdir(), 'shipmiracle-datacaps-'));
const STATE = path.join(ROOT, 'state'), DEV = path.join(ROOT, 'dev'), WS = path.join(DEV, 'AI-Workspace'), COUNT = path.join(ROOT, 'calls.txt');
delete process.env.CLAUDECODE;
Object.assign(process.env, { SHIPMIRACLE_TEST: '1', SHIPMIRACLE_EXT_STATE: STATE, SHIPMIRACLE_EXT_DEV: DEV, SHIPMIRACLE_EXT_WS: WS, SHIPMIRACLE_HOME: path.join(ROOT, 'home'), SHIPMIRACLE_STATE: STATE });
for (const d of [path.join(WS, 'bin'), path.join(WS, 'config'), STATE, path.join(DEV, 'plainone', '.git'), path.join(DEV, 'plaintwo', '.git')]) fs.mkdirSync(d, { recursive: true });
// stand-in engine: answers `report panel` with capability flags and no playbook; counts its calls
fs.writeFileSync(path.join(WS, 'bin', 'shipm'), `#!/bin/bash\nif [ "$1 $2" = "report panel" ]; then echo x >> "${COUNT}"; echo '{"v":1,"playbook":null,"caps":{"toolbox":true,"interview":true,"aside":true,"unread":true}}'; fi\n`, { mode: 0o755 });
const { collect } = require(path.join(__dirname, '../vscode-ext/shipmiracle-panel/data.js'));
let fails = 0; const check = (n, c, info = '') => { console.log((c ? 'PASS ' : 'FAIL ') + n + (c ? '' : ' ' + info)); if (!c) fails++; };
(async () => {
  const d = await collect();
  const names = d.projects.map(p => p.name);
  check('fixture projects have no .shipmiracle folder', names.includes('plainone') && names.includes('plaintwo') && !fs.existsSync(path.join(DEV, 'plainone', '.shipmiracle')), names.join());
  check('playbook stays null for projects without one', d.projects.filter(p => /^plain/.test(p.name)).every(p => p.playbook === null));
  check('capabilities flags are true although no project has a playbook', ['toolbox', 'interview', 'aside', 'unread'].every(k => d.capabilities[k] === true), JSON.stringify(d.capabilities));
  const n1 = fs.readFileSync(COUNT, 'utf8').trim().split('\n').length;
  await collect();
  const n2 = fs.readFileSync(COUNT, 'utf8').trim().split('\n').length;
  check('the engine is asked once, not per project or per refresh', n1 === 1 && n2 === 1, n1 + ',' + n2);
  console.log(fails ? 'FAILED ' + fails : 'ALL PASS'); process.exit(fails ? 1 : 0);
})();
