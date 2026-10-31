// Shared Chrome launcher for the node UI tests. Every test that opens a browser goes through this file (release-check's isolation lint enforces it).
// - safe flags always: --use-mock-keychain --password-store=basic (no login-keychain popup), --disable-sync, --no-default-browser-check, --no-first-run
// - Chrome runs detached in its OWN process group; the whole group (renderer, GPU and helper processes too) is killed on normal exit, failure,
//   uncaughtException, unhandledRejection, SIGINT, SIGTERM and process 'exit'; the temp profile and the temp work folder are removed.
// - Temp folders come from os.tmpdir() (TMPDIR-independent: nothing is hardcoded to /tmp).
// Usage:  const H = require('./chrome_helper'); if (!H.available()) { console.log('SKIP no Chrome'); process.exit(0); }
//         const { port, kill } = H.launch({ size: '345,900' });   H.work = a private temp folder for html/png files
const fs = require('fs'), os = require('os'), path = require('path'), { spawn } = require('child_process');

const DEFAULT_CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const CHROME = process.env.SHIPMIRACLE_CHROME || DEFAULT_CHROME;           // SHIPMIRACLE_CHROME: tests of this helper point it at a dummy executable
const FLAGS = ['--use-mock-keychain', '--password-store=basic', '--disable-sync', '--no-default-browser-check', '--no-first-run'];
const work = fs.mkdtempSync(path.join(os.tmpdir(), 'shipmiracle-ui-work-'));
const live = new Set();                                              // { pid, prof }

function killGroup(pid) {
  for (const sig of ['SIGTERM', 'SIGKILL']) { try { process.kill(-pid, sig); } catch (e) { /* group already gone */ } }
}
function cleanupAll() {
  for (const c of live) { killGroup(c.pid); try { fs.rmSync(c.prof, { recursive: true, force: true }); } catch (e) { /* best effort */ } }
  live.clear();
  try { fs.rmSync(work, { recursive: true, force: true }); } catch (e) { /* best effort */ }
}
let hooked = false;
function hook() {
  if (hooked) return; hooked = true;
  process.on('exit', cleanupAll);
  for (const [sig, code] of [['SIGINT', 130], ['SIGTERM', 143], ['SIGHUP', 129]]) process.on(sig, () => { cleanupAll(); process.exit(code); });
  process.on('uncaughtException', e => { console.error('uncaught exception:', e && e.stack || e); cleanupAll(); process.exit(2); });
  process.on('unhandledRejection', e => { console.error('unhandled rejection:', e && e.stack || e); cleanupAll(); process.exit(2); });
}
hook();                                                              // the work folder is removed even when the test skips or never launches

function available() { return fs.existsSync(CHROME); }

/** Start headless Chrome. -> { chrome, port, prof, kill() }. opts: size 'W,H', port (default random 9400-9999), extraArgs. */
function launch(opts = {}) {
  const port = opts.port || 9400 + Math.floor(Math.random() * 600);
  const prof = fs.mkdtempSync(path.join(os.tmpdir(), 'shipmiracle-chrome-'));
  const args = ['--headless=new', `--remote-debugging-port=${port}`, `--user-data-dir=${prof}`, ...FLAGS];
  if (opts.size) args.push(`--window-size=${opts.size}`);
  args.push(...(opts.extraArgs || []), 'about:blank');
  const chrome = spawn(CHROME, args, { stdio: 'ignore', detached: true });
  chrome.on('error', e => { console.error('could not start Chrome:', e.message); });
  chrome.unref();
  const rec = { pid: chrome.pid, prof };
  if (chrome.pid) live.add(rec);
  return { chrome, port, prof, kill() { if (chrome.pid) killGroup(chrome.pid); try { fs.rmSync(prof, { recursive: true, force: true }); } catch (e) { /* ok */ } live.delete(rec); } };
}

module.exports = { CHROME, FLAGS, available, launch, work, killGroup, cleanupAll };
