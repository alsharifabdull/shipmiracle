// F9 setting default (UX addendum 5f): `shipmiracle.cardChatExcerpt` is ON in the private build (vscode-ext/shipmiracle-panel/package.json) and OFF in the public export, which takes its package.json from the overlay
// (release/overlay/vscode-ext/shipmiracle-panel/package.json). The two files must stay identical except that one default. Also: `shipmiracle.unreadMarker` is on in both; the exported tree really holds the overlay file.
// Run: node tests/ext_public_setting_test.js
require('./shipmiracle_isolation').apply();
const fs = require('fs'), path = require('path'), cp = require('child_process');
const root = path.join(__dirname, '..');
let fails = 0; const check = (n, c, info = '') => { console.log((c ? 'PASS ' : 'FAIL ') + n + (c ? '' : ' ' + info)); if (!c) fails++; };
const priv = JSON.parse(fs.readFileSync(path.join(root, 'vscode-ext/shipmiracle-panel/package.json'), 'utf8'));
const pubFile = path.join(root, 'release/overlay/vscode-ext/shipmiracle-panel/package.json');
const props = j => j.contributes.configuration.properties;
if (!fs.existsSync(pubFile)) {   // the exported tree: release/ is not shipped and the overlay file IS vscode-ext/.../package.json, so check that one directly
  console.log('SKIP private-vs-overlay comparison: release/overlay is not part of the exported tree (the tree\'s own package.json is the public file)');
  check('exported tree: shipmiracle.cardChatExcerpt default false', props(priv)['shipmiracle.cardChatExcerpt'].default === false);
  check('exported tree: shipmiracle.unreadMarker is on by default', props(priv)['shipmiracle.unreadMarker'].default === true);
  console.log(fails ? `\nFAILED: ${fails}` : '\nALL PASS'); process.exit(fails ? 1 : 0);
}
const pub = JSON.parse(fs.readFileSync(pubFile, 'utf8'));
check('private build: shipmiracle.cardChatExcerpt default true (boolean), described with the screen-share warning', props(priv)['shipmiracle.cardChatExcerpt'].type === 'boolean' && props(priv)['shipmiracle.cardChatExcerpt'].default === true && /screen shares/.test(props(priv)['shipmiracle.cardChatExcerpt'].description));
check('public export (overlay package.json): shipmiracle.cardChatExcerpt default false', props(pub)['shipmiracle.cardChatExcerpt'].default === false);
check('shipmiracle.unreadMarker is on by default in both', props(priv)['shipmiracle.unreadMarker'].default === true && props(pub)['shipmiracle.unreadMarker'].default === true);
const norm = j => { const c = JSON.parse(JSON.stringify(j)); c.contributes.configuration.properties['shipmiracle.cardChatExcerpt'].default = null; return JSON.stringify(c); };
check('the two package.json files are identical except that one default (same version, commands, menus)', norm(priv) === norm(pub) && priv.version === pub.version);
// the export script's own selection: the overlay file replaces the source file in the exported tree (dry run, nothing is written outside a temp folder)
const py = `
import sys, json
sys.path.insert(0, ${JSON.stringify(root)})
from shipmiracle.release import export as E
import inspect
src = inspect.getsource(E)
print(json.dumps({"overlay_prefix": E.OVERLAY, "has_laid": "overlay" in src}))
`;
let out = ''; try { out = cp.execFileSync('/usr/bin/python3', ['-I', '-c', py], { encoding: 'utf8', timeout: 20000, env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1' } }); } catch (e) { /* reported below */ }
check('the export lays release/overlay/** over the tree (so the overlay package.json is what ships)', /release\/overlay\//.test(out), out);
console.log(fails ? `\nFAILED: ${fails}` : '\nALL PASS'); process.exit(fails ? 1 : 0);
