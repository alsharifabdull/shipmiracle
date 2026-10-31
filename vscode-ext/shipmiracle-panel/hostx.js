// Where is the panel running? (task E10) Native Windows is not supported yet: the panel says so in plain words and points to WSL 2, using the install hint the CLI itself sends in
// `shipm init --check --json` (field os.line when os.kind is "windows"); the one fallback sentence below is used only when the CLI could not answer (it cannot run on native Windows).
// "Experimental" on Linux / WSL is shown ONLY when the CLI says so (os.level === 'experimental'); the panel never decides that itself. The stale-chat check needs the chat's IDE port, which is
// only readable on macOS (procx.js never reads a process environment elsewhere), so on other systems the Health tab says "chat health: unknown". Pure Node, no vscode, everything escaped.
const FALLBACK_HINT = 'Install WSL 2: open PowerShell as administrator, run "wsl --install", restart, open Ubuntu, then install Shipmiracle there.';
const REMOTE = /^[a-z][a-z0-9-]{0,40}$/;

// -> the host as the page needs it. `platform` is process.platform, `remoteName` is vscode.env.remoteName ('wsl', 'ssh-remote', 'dev-container' ... or undefined)
function hostOf({ platform, remoteName } = {}) {
  const p = typeof platform === 'string' ? platform : '', r = typeof remoteName === 'string' && REMOTE.test(remoteName) ? remoteName : '';
  return { platform: p.slice(0, 20), remote: r, kind: p === 'win32' ? 'windows' : r === 'wsl' ? 'wsl' : 'other', chatHealth: p === 'darwin' ? 'known' : 'unknown' };
}
// the same, read back from untrusted page data (sane.js)
function cleanHost(h) {
  if (!h || typeof h !== 'object') return { platform: '', remote: '', kind: 'other', chatHealth: 'known' };
  const x = hostOf({ platform: h.platform, remoteName: h.remote });
  if (h.chatHealth === 'known' || h.chatHealth === 'unknown') x.chatHealth = h.chatHealth; else x.chatHealth = x.platform ? x.chatHealth : 'known';
  return x;
}
// the install hint: the CLI's own sentence when it describes a native Windows host, else the fallback
function hintOf(os) {
  const line = os && os.kind === 'windows' && typeof os.line === 'string' ? os.line.replace(/[\u0000-\u001f\u007f-\u009f\u2028\u2029]+/g, ' ').replace(/[\p{Cf}\p{Co}\p{Cn}]+/gu, '').replace(/\s+/g, ' ').trim().slice(0, 300) : '';
  return line || FALLBACK_HINT;
}
const experimental = os => !!os && os.level === 'experimental';

// -> '' or the notice for the Setup tab and the Projects empty state. `where` is 'setup' | 'projects'.
function notice(host, os, { t, esc }, where) {
  const h = host || {};
  if (h.kind === 'windows') {
    return `<section class="hostn warn" data-host="windows" data-where="${esc(where)}" role="status" aria-label="${esc(t('host.winTitle'))}"><b dir="auto">${esc(t('host.winTitle'))}</b>`
      + `<p dir="auto">${esc(t('host.winBody'))}</p><div class="hostl">${esc(t('host.hintLabel'))}</div><p class="hosth" dir="auto">${esc(hintOf(os))}</p></section>`;
  }
  if (where === 'setup' && h.platform !== 'darwin' && (h.kind === 'wsl' || (os && os.kind === 'wsl') || (os && os.kind === 'linux')) && experimental(os)) {
    return `<section class="hostn" data-host="experimental" data-where="setup" role="status"><p dir="auto">${esc(t('host.experimental'))}</p></section>`;
  }
  return '';
}
// the Health tab's honest line when the stale-chat check cannot work here
const healthNote = (host, { t, esc }) => host && host.chatHealth === 'unknown'
  ? `<div class="hostn" data-host="chat-unknown" role="status"><p dir="auto">${esc(t('host.chatUnknown'))}</p></div>` : '';

const css = String.raw`.hostn{margin:0 0 10px;padding:8px 10px;border:1px solid var(--bd);border-radius:8px;background:var(--card);font-size:12px;color:var(--fg);overflow-wrap:anywhere}
.hostn.warn{border-color:color-mix(in srgb,var(--warn) 45%,transparent);background:var(--warnbg)}.hostn.warn b{color:var(--warnt)}.hostn p{margin:4px 0 0}.hostn b{font-size:13px}
.hostl{margin-top:6px;font-size:11px;font-weight:600;color:var(--mutt)}.hosth{user-select:all}
body.vscode-high-contrast .hostn{border:1px solid var(--vscode-contrastBorder,currentColor)}`;
module.exports = { FALLBACK_HINT, hostOf, cleanHost, hintOf, notice, healthNote, css };
