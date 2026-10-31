// Same job as tests/shipmiracle_isolation.py for the node tests: call apply() first thing; every process the test starts inherits the isolation.
// SHIPMIRACLE_TEST, HOME, SHIPMIRACLE_HOME, CLAUDE_CONFIG_DIR, SHIPMIRACLE_CONFIG and SHIPMIRACLE_STATE that are unset or outside the system temp folder get a fresh temp folder (removed at exit).
// SHIPMIRACLE_WS and SHIPMIRACLE_DEV are left alone.
const fs = require('fs'), os = require('os'), path = require('path');
const BROWSER_ARGS = '--use-mock-keychain,--password-store=basic';
function underTemp(p) {
  let r; try { r = fs.realpathSync(p); } catch (e) { r = path.resolve(p); }
  const roots = new Set([os.tmpdir(), '/tmp', '/private/tmp', '/var/folders', '/private/var/folders'].map(x => { try { return fs.realpathSync(x); } catch (e) { return x; } }));
  for (const t of roots) if (r === t || r.startsWith(t.replace(/\/$/, '') + '/')) return true;
  return false;
}
function apply() {
  let root = null;
  const fresh = sub => {
    if (!root) {
      root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'shipmiracle-iso-')));
      fs.mkdirSync(path.join(root, 'h', '.claude'), { recursive: true });
      fs.writeFileSync(path.join(root, 'h', '.gitconfig'), '[user]\n\tname = Shipmiracle test\n\temail = test@example.com\n[init]\n\tdefaultBranch = main\n[commit]\n\tgpgsign = false\n');
      process.on('exit', () => { try { fs.rmSync(root, { recursive: true, force: true }); } catch (e) { /* best effort */ } });
    }
    return path.join(root, sub);
  };
  process.env.SHIPMIRACLE_TEST = '1';
  for (const [v, sub] of [['HOME', 'h'], ['SHIPMIRACLE_HOME', 'h'], ['CLAUDE_CONFIG_DIR', 'h/.claude'], ['SHIPMIRACLE_CONFIG', 'c'], ['SHIPMIRACLE_STATE', 's']]) {
    if (!process.env[v] || !underTemp(process.env[v])) process.env[v] = fresh(sub);
  }
  if (!process.env.AGENT_BROWSER_ARGS) process.env.AGENT_BROWSER_ARGS = BROWSER_ARGS;
  return root;
}
module.exports = { apply, underTemp, BROWSER_ARGS };
