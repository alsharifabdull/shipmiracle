// tests/chrome_helper.js with a tiny dummy executable instead of Chrome: a test that ends normally, fails, throws, or is killed leaves NO browser process
// (the whole process group goes) and no temp profile. Safe flags are always passed. Run: node tests/chrome_helper_test.js
require('./shipmiracle_isolation').apply();   // fresh HOME / SHIPMIRACLE_* folders for this process and what it starts
const fs = require('fs'), os = require('os'), path = require('path'), { spawn, spawnSync } = require('child_process');
const HELPER = path.join(__dirname, 'chrome_helper.js');
const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'shipmiracle-chtest-'));
const dummy = path.join(dir, 'dummy-chrome');
fs.writeFileSync(dummy, '#!/bin/sh\necho "$$" > "$DUMMY_OUT/pids"\necho "$@" > "$DUMMY_OUT/args"\nsleep 300 &\necho "$!" >> "$DUMMY_OUT/pids"\nsleep 300 &\necho "$!" >> "$DUMMY_OUT/pids"\nwait\n');
fs.chmodSync(dummy, 0o755);
let fails = 0; const check = (n, c, info = '') => { console.log((c ? 'PASS ' : 'FAIL ') + n + (c ? '' : ' ' + info)); if (!c) fails++; };
const sleep = ms => new Promise(r => setTimeout(r, ms));
const alive = pid => { try { process.kill(pid, 0); return true; } catch (e) { return false; } };
const SCEN = {
  normal: 'process.exit(0)',
  failure: 'process.exit(1)',
  throws: 'setTimeout(() => { throw new Error("boom") }, 10)',
  reject: 'Promise.reject(new Error("rej"))',
  sigterm: 'process.kill(process.pid, "SIGTERM")',
  sigint: 'process.kill(process.pid, "SIGINT")',
  sigkill: 'process.kill(process.pid, "SIGKILL")',   // cannot be caught: only the detached group + its own parent-death logic could help; documented below
};
(async () => {
  for (const [name, code] of Object.entries(SCEN)) {
    const out = fs.mkdtempSync(path.join(dir, name + '-'));
    const src = `const H = require(${JSON.stringify(HELPER)}); const r = H.launch({ size: '345,900' }); require('fs').writeFileSync(process.env.DUMMY_OUT + '/prof', r.prof);
      (async () => { for (let i = 0; i < 100 && !require('fs').existsSync(process.env.DUMMY_OUT + '/pids'); i++) await new Promise(x => setTimeout(x, 50)); await new Promise(x => setTimeout(x, 200)); ${code} })();`;
    const child = spawn(process.execPath, ['-e', src], { env: { ...process.env, SHIPMIRACLE_CHROME: dummy, DUMMY_OUT: out }, stdio: 'ignore' });
    await new Promise(r => child.on('exit', r));
    await sleep(500);
    const pids = fs.existsSync(path.join(out, 'pids')) ? fs.readFileSync(path.join(out, 'pids'), 'utf8').split('\n').filter(Boolean).map(Number) : [];
    const prof = fs.existsSync(path.join(out, 'prof')) ? fs.readFileSync(path.join(out, 'prof'), 'utf8') : '';
    const left = pids.filter(alive);
    if (name === 'sigkill') {                       // SIGKILL of the test itself cannot run any handler: clean up here and report as a known limit, not a pass
      left.forEach(p => { try { process.kill(-pids[0], 'SIGKILL'); } catch (e) { /* gone */ } });
      console.log('NOTE sigkill: ' + (left.length ? 'the browser group survives a SIGKILL of the test (known limit; stray_browser in shipm-watch cleans temp-profile browsers after 30 min)' : 'group gone'));
      if (prof) fs.rmSync(prof, { recursive: true, force: true });
      continue;
    }
    check(`${name}: the dummy browser and its 2 helper processes are all gone`, pids.length === 3 && left.length === 0, JSON.stringify({ pids, left }));
    check(`${name}: the temp profile is removed`, prof && !fs.existsSync(prof), prof);
    left.forEach(p => { try { process.kill(p, 'SIGKILL'); } catch (e) { /* gone */ } });
    if (name === 'normal') {
      const args = fs.readFileSync(path.join(out, 'args'), 'utf8');
      check('safe flags are always passed', ['--use-mock-keychain', '--password-store=basic', '--disable-sync', '--no-default-browser-check', '--no-first-run', '--headless=new', '--remote-debugging-port='].every(f => args.includes(f)), args);
      check('the profile is a temp folder', /--user-data-dir=\S*shipmiracle-chrome-/.test(args), args);
    }
  }
  // an explicit kill() inside the test also removes everything at once
  const out = fs.mkdtempSync(path.join(dir, 'kill-'));
  const r = spawnSync(process.execPath, ['-e', `const H = require(${JSON.stringify(HELPER)}); const r = H.launch({}); setTimeout(() => { r.kill(); setTimeout(() => process.exit(0), 100); }, 500);`], { env: { ...process.env, SHIPMIRACLE_CHROME: dummy, DUMMY_OUT: out } });
  const pids = fs.readFileSync(path.join(out, 'pids'), 'utf8').split('\n').filter(Boolean).map(Number);
  check('kill(): the whole group is gone', r.status === 0 && pids.every(p => !alive(p)), JSON.stringify(pids));
  fs.rmSync(dir, { recursive: true, force: true });
  console.log(fails ? '\nFAILED: ' + fails : '\nALL PASS'); process.exit(fails ? 1 : 0);
})();
