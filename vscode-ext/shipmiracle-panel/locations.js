// Where things live: the projects folder, the Shipmiracle engine checkout, the registry. Shared by data.js and extension.js (tests replace ./data, not this file).
const fs = require('fs');
const os = require('os');
const path = require('path');

const HOME = os.homedir();
const testEnv = k => process.env.SHIPMIRACLE_TEST === '1' ? process.env[k] : undefined;     // test-only overrides (SHIPMIRACLE_EXT_*, SHIPMIRACLE_CONFIG) are read only when SHIPMIRACLE_TEST=1
// Folders come from the shipm config (~/.config/shipmiracle/config.json): paths.projects_dir (default ~/Developer) and engine.dir (the Shipmiracle engine checkout;
// default ~/Developer/shipmiracle, the clone folder of the public install). SHIPMIRACLE_CONFIG (the config folder) is read only when SHIPMIRACLE_TEST=1.
const CONFIG_DIR = testEnv('SHIPMIRACLE_CONFIG') || path.join(HOME, '.config', 'shipmiracle');
const jsonOrNull = f => require('./reports').readJson(f);
const cfgPath = key => {
  const c = jsonOrNull(path.join(CONFIG_DIR, 'config.json')); let v = c && typeof c === 'object' ? c[key] : null;
  if (typeof v === 'string' && v.startsWith('~/')) v = path.join(HOME, v.slice(2));
  return typeof v === 'string' && path.isAbsolute(v) ? v : null;
};
const DEV = testEnv('SHIPMIRACLE_EXT_DEV') || cfgPath('paths.projects_dir') || path.join(HOME, 'Developer');
const WS = testEnv('SHIPMIRACLE_EXT_WS') || cfgPath('engine.dir') || path.join(DEV, 'shipmiracle');
const realOr = p => { try { return fs.realpathSync(p); } catch (e) { return path.resolve(p); } };
const isHub = dir => realOr(dir) === realOr(WS);        // the hub is the engine checkout itself, not a project with a certain name
// A project the registry marks protected (or the engine itself) cannot be deleted from the panel (the delete tool checks again).
function isProtected(name, dir) {
  if (dir && isHub(dir)) return true;
  const r = jsonOrNull(path.join(CONFIG_DIR, 'registry.json')); const ps = r && r.projects && typeof r.projects === 'object' ? r.projects : {};
  return Object.values(ps).some(e => e && e.name === name && (e.protected === true || e.role === 'workspace' || e.role === 'public-engine'));
}

module.exports = { CONFIG_DIR, DEV, WS, isHub, isProtected };
