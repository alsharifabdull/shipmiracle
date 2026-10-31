// Which Claude chat is a terminal, on every OS the panel can run on (task E10). Pure Node, no vscode; every outside thing is injected so the tests can use fake process tables.
//   darwin : `ps -o command=` for the command, `ps eww` for the chat's IDE port, `lsof` for its folder.
//   linux / WSL : `ps -o command=` (portable flags only), /proc/<pid>/cwd for the folder. The environment of a process is NEVER read there (no /proc/<pid>/environ, no `ps e`):
//                 the port stays '' and portKnown is false, so the stale-chat check is "unknown", not a guess, and nothing is closed or relaunched because of it.
//   anything else (win32, freebsd ...) : no lookup, an unknown answer. Nothing here throws.
const fs = require('fs');
const { execFile } = require('child_process');

const PS_PATHS = ['/bin/ps', '/usr/bin/ps'];
const psFile = () => PS_PATHS.find(p => { try { return fs.statSync(p).isFile(); } catch (e) { return false; } }) || '';
const realRun = (file, args) => new Promise(res => {
  if (!file) return res('');
  try { execFile(file, args, { timeout: 3000, maxBuffer: 1 << 20 }, (err, out) => res(err ? '' : String(out))); } catch (e) { res(''); }
});
const realReadlink = p => new Promise(res => fs.readlink(p, (err, v) => res(err || typeof v !== 'string' ? '' : v)));
const goodPid = pid => Number.isInteger(Number(pid)) && Number(pid) > 0 && /^\d{1,10}$/.test(String(pid));

function make(deps) {
  const d = { platform: () => process.platform, run: realRun, readlink: realReadlink, projectOfPath: () => '', within: p => p, ...deps };
  const ps = args => d.run(d.psFile !== undefined ? d.psFile : psFile(), args);

  // The folder a chat process works in, or '' (unknown). Never a guess.
  async function cwdOfPid(pid) {
    if (!goodPid(pid)) return '';
    const os = d.platform();
    if (os === 'linux') { const p = await d.readlink('/proc/' + Number(pid) + '/cwd'); return typeof p === 'string' ? p.replace(/ \(deleted\)$/, '') : ''; }
    if (os !== 'darwin') return '';
    const out = await d.run('lsof', ['-a', '-p', String(Number(pid)), '-d', 'cwd', '-Fn']);
    const m = /^n(.+)$/m.exec(out); return m ? m[1] : '';
  }

  // -> { project, port, pid, portKnown } for a terminal that runs a Claude chat, or null (not a chat, or this OS cannot tell)
  async function inspect(t) {
    const os = d.platform();
    if (os !== 'darwin' && os !== 'linux') return null;
    let pid; try { pid = await d.within(t.processId, 1200); } catch (err) { return null; }
    if (!goodPid(pid)) return null;
    const cmd = (await ps(['-o', 'command=', '-p', String(Number(pid))])).trim();
    if (!/^(\S*\/)?claude(\s|$)/.test(cmd)) return null;                                // a shell or something else: not a chat
    let port = '', portKnown = false;
    if (os === 'darwin') {
      const env = await ps(['eww', '-p', String(Number(pid))]);
      port = (/CLAUDE_CODE_SSE_PORT=(\d+)/.exec(env) || [])[1] || ''; portKnown = env.length > 0;
    }
    const nm = /\s--name\s+(\S+)/.exec(cmd);
    const project = nm ? nm[1] : d.projectOfPath(await cwdOfPid(pid));                  // chats opened by older panel versions have no --name
    return project ? { project, port, pid, portKnown } : null;
  }
  return { cwdOfPid, inspect };
}
module.exports = { make, goodPid };
