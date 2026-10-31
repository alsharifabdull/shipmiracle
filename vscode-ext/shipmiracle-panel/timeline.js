// Two-level project timeline of the card (owner approved 30 Oct 2026): LEVEL 1 = the release line ("Released v1.0 · 12 Oct · working on v1.1 · 2 changes done"), LEVEL 2 = the changes (the 7-step rail,
// shown only while a change is open, blocked or queued). When no change is open the card shows "Last change" + "Next: start a change" instead of a rail (never an all-done or empty rail for an idle
// project), a chat that edits without a change shows "Unplanned work", and "History (N)" lists the last 10 changes grouped under their release.
// Everything here is gated on caps.release === true AND p.release (data.js / sane.js pass them through); with either missing the card is drawn exactly as before.
// The card only TYPES two commands into the owner's terminal, never Enter: `shipm release mark VERSION --project NAME` and `shipm cr open --project NAME ''` (the extension re-checks both, see markArgv / openLine).
// A factory like cardx.js, split out of panel.js to keep it under the export's 200 KB file limit: panel.js passes the few helpers it shares.
const CHARTER = require('./charter');
const DETAIL = require('./detail');                           // text hygiene (control and bidi characters out, secrets masked, length capped)
const VER =/^\d+(\.\d+){0,3}$/;                              // the only version text the panel will ever type: 1, 1.1, 1.1.2, 1.1.2.3
const ver = v => String(v == null ? '' : v).replace(/^v/i, '');          // no trimming: a version with a space or a newline is not a version
const verOk = v => VER.test(String(v));
const cmpVer = (a, b) => { const x = String(a).split('.').map(Number), y = String(b).split('.').map(Number); for (let i = 0; i < 4; i++) { const d = (x[i] || 0) - (y[i] || 0); if (d) return d < 0 ? -1 : 1; } return 0; };
// ---- the cleaners of the two data fields (used by data.js when it reads `shipm report panel` and again by sane.js in front of the page). A value of the wrong type becomes null / '' / 0; nothing is guessed.
const isObj = v => v !== null && typeof v === 'object' && !Array.isArray(v);
const txt = (v, n) => (typeof v === 'string' ? DETAIL.sanitize(v, n) : '');
const cnt = (v, max) => (Number.isInteger(v) && v >= 0 ? Math.min(v, max) : 0);
function cleanRelease(r) {                                    // {last:{version,date,tag}|null, working:{version,source}|null, since:{changes,commits}} | null
  if (!isObj(r)) return null;
  const lv = isObj(r.last) ? txt(r.last.version, 30) : '', wv = isObj(r.working) ? txt(r.working.version, 30) : '', s = isObj(r.since) ? r.since : {};
  return { last: lv ? { version: lv, date: txt(r.last.date, 40), tag: txt(r.last.tag, 60) } : null, working: wv ? { version: wv, source: txt(r.working.source, 40) } : null, since: { changes: cnt(s.changes, 100000), commits: cnt(s.commits, 1000000) } };
}
function cleanHistory(h) {                                    // [{id,title,status,closed,release}] newest first, at most 10 | null
  if (!Array.isArray(h)) return null;
  return h.filter(x => isObj(x) && txt(x.id, 30)).slice(0, 10).map(x => ({ id: txt(x.id, 30), title: txt(x.title, 120), status: txt(x.status, 20),
    closed: typeof x.closed === 'number' && Number.isFinite(x.closed) && x.closed > 0 ? Math.floor(x.closed) : txt(x.closed, 40),
    release: typeof x.release === 'string' || typeof x.release === 'number' ? txt(String(x.release), 30) || null : null }));
}
// ---- the owner's terminal commands (typed, never run). The extension calls these with data it re-checked; both throw on anything unsafe.
function markArgv(shipm, project, version) {
  const v = ver(version);
  if (!CHARTER.SAFE_NAME.test(project) || project.startsWith('-') || !verOk(v)) throw new Error('bad release request');
  return [[shipm, 'release', 'mark', v, '--project', project]];
}
function openLine(shipm, project) {                                         // the cursor goes back one place, between the single quotes, where the owner types the title (the extension types it, never Enter)
  if (!CHARTER.SAFE_NAME.test(project) || project.startsWith('-')) throw new Error('bad change request');
  return CHARTER.line([shipm, 'cr', 'open', '--project', project]) + " ''";
}

const css = `
.tlrel{display:flex;flex-wrap:wrap;align-items:center;gap:3px 8px;margin-top:3px;font-size:12px;line-height:1.35;color:var(--fg)}.tlrel .tlt{min-width:0;overflow-wrap:anywhere}.tlrel.ready .tlt{font-weight:600;color:var(--okt)}
.tlrel .btn,.tlidle .btn{flex:none;max-width:100%;font-size:11.5px;height:26px;padding:0 10px}
.tlidle{display:flex;flex-direction:column;gap:4px;margin-top:6px}.tll,.tln{display:flex;flex-wrap:wrap;align-items:center;gap:3px 8px;font-size:11.5px;line-height:1.35;color:var(--mutt);overflow-wrap:anywhere}.tll bdi{color:var(--fg)}
.tlhw{margin-top:4px}.tlhw .tlhb.lnk{position:relative;display:inline-flex;align-items:center;height:24px;min-height:24px;min-width:24px;padding-inline-end:20px}.tlchev{position:absolute;top:50%;inset-inline-end:6px;margin-top:-.5em;line-height:1;text-decoration:none;transition:transform .15s ease-out}.tlhb[aria-expanded="true"] .tlchev{transform:rotate(90deg)}
.tlhist{margin:2px 0 0;font-size:11.5px;color:var(--fg)}.tlhist h5{margin:6px 0 2px;font-size:11px;font-weight:700;color:var(--mutt)}.tlhist ul{list-style:none;margin:0;padding:0}.tlhist li{padding:1px 0;overflow-wrap:anywhere}
.tlhb:focus-visible,.tlmark:focus-visible,.tlcr:focus-visible{outline:2px solid var(--acc);outline-offset:1px}
@media (prefers-reduced-motion:reduce){.tlchev{transition:none}}
body.vscode-high-contrast .tlrel.ready .tlt,body.vscode-high-contrast .tll,body.vscode-high-contrast .tln{color:var(--fg)}`;
const clientJs = String.raw`// ---- timeline: the History disclosure of a card (kept open across redraws by project name). The page sends nothing; it only shows or hides text that is already in the card.
function tlHist(btn, open) { const reg = document.getElementById(btn.getAttribute('aria-controls')); if (!reg) return; btn.setAttribute('aria-expanded', open ? 'true' : 'false'); reg.hidden = !open; const o = S.tlh || (S.tlh = {}); if (open) o[btn.dataset.tlh] = 1; else delete o[btn.dataset.tlh]; vscode.setState(S); }
document.addEventListener('click', e => { const b = e.target.closest('[data-tlh]'); if (!b) return; e.stopImmediatePropagation(); tlHist(b, b.getAttribute('aria-expanded') !== 'true'); });
// The two buttons that only TYPE a command (Mark released, Start a change) are handled here, before the card's general button handler (which also posts an 'editing' message that this click never needs). It still ends an open menu or an armed "Sure?" first.
document.addEventListener('click', e => { const b = e.target.closest('[data-act^="tl"]'); if (!b || (b.dataset.act !== 'tlmark' && b.dataset.act !== 'tlcr')) return; e.stopImmediatePropagation(); e.stopPropagation(); if (b.disabled) return;
  const held = !!armedBtn; disarm(true); closeMenu(false); if (held) vscode.postMessage({ type: 'editing', on: false });
  const card = b.closest('[data-dir]'); vscode.postMessage({ type: 'act', act: b.dataset.act, project: b.dataset.project || '', dir: card ? card.dataset.dir : '', cr: '', to: '', report: '', verb: b.dataset.verb || '' }); });
document.querySelectorAll('[data-tlh]').forEach(b => { if (S.tlh && S.tlh[b.dataset.tlh]) tlHist(b, true); });`;
module.exports = function make(D) {
const { t, esc, S, crInfo, caps } = D;     // D also carries stageNames
const on = p => !!(p && p.playbook && p.release && typeof p.release === 'object' && caps() && caps().release === true);
const plural = (n, one, many, o) => t(n === 1 ? one : many, { n, ...o });
function dm(d) {                                              // 'YYYY-MM-DD…' text or epoch seconds -> '12 Oct' (and the year when it is not this year); '' when unknown. No time zone maths for a plain date.
  let y, m, day;
  if (typeof d === 'number' && d > 0) { const x = new Date(d * 1000); y = x.getFullYear(); m = x.getMonth(); day = x.getDate(); }
  else { const r = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(d || '')); if (!r) return ''; y = +r[1]; m = +r[2] - 1; day = +r[3]; }
  if (!(m >= 0 && m < 12 && day >= 1 && day <= 31)) return '';
  return day + ' ' + S.details.months[m] + (y !== new Date().getFullYear() ? ' ' + y : '');
}
const hist = p => (Array.isArray(p.history) ? p.history : []).filter(h => h && typeof h === 'object' && h.id).slice(0, 10);
const DONE = ['delivered', 'merged'];
function lastDone(p) {                                         // the newest finished change: from History first, else the card's own finished request (no date then)
  const h = hist(p).find(x => DONE.includes(x.status)); if (h) return { id: h.id, title: h.title || '', date: dm(h.closed) };
  const f = crInfo(p).fin; return f && DONE.includes(f.status) ? { id: f.id, title: f.title || '', date: '' } : null;
}
// -> { text, btn: version|null, mark: true when it is the "ready" line }. The one release line (state table of the approved mockups).
function releaseOf(p) {
  const r = p.release, ci = crInfo(p), last = r.last && typeof r.last === 'object' && r.last.version ? { v: ver(r.last.version), date: dm(r.last.date) } : null;
  const w = r.working && typeof r.working === 'object' && r.working.version ? { v: ver(r.working.version), src: String(r.working.source || '') } : null;
  const n = r.since && Number.isInteger(r.since.changes) && r.since.changes > 0 ? r.since.changes : 0, idle = ci.open.length === 0;
  const J = (...a) => a.filter(Boolean).join(' · ');
  if (last) {
    const head = J(t('tl.released', { v: last.v }), last.date);
    if (w && cmpVer(w.v, last.v) > 0) {
      if (idle && n > 0) return { text: J(t('tl.ready', { v: w.v }), plural(n, 'tl.readyOne', 'tl.readyN', { v: last.v })), btn: verOk(w.v) ? w.v : null, mark: true };
      return { text: J(head, t('tl.working', { v: w.v }), n > 0 ? plural(n, 'tl.doneOne', 'tl.doneN') : ''), btn: null };
    }
    return { text: J(head, n > 0 ? plural(n, 'tl.sinceDoneOne', 'tl.sinceDoneN') : t('tl.nothingNew')), btn: null };
  }
  if (w) return { text: J(t('tl.noRelease'), w.src ? t('tl.building', { v: w.v, src: w.src }) : t('tl.buildingNoSrc', { v: w.v })), btn: null };
  const d = lastDone(p);
  return { text: d ? J(t('tl.lastDone', { cr: d.id }), d.date) : t('tl.noRelease'), btn: null };
}
function releaseLine(p) {
  const r = releaseOf(p), nm = esc(p.name);
  const btn = r.btn ? `<button type="button" class="btn tlmark" data-act="tlmark" data-verb="${esc(r.btn)}" data-project="${nm}" title="${esc(t('tl.markTip', { v: r.btn }))}" aria-label="${esc(t('tl.markAria', { v: r.btn, project: p.name }))}">${esc(t('tl.mark', { v: r.btn }))}</button>` : '';
  return `<div class="tlrel${r.mark ? ' ready' : ''}" data-tlrel role="group" aria-label="${esc(t('tl.relAria', { text: r.text.replace(/ · /g, ', ') }))}"><span class="tlt" dir="auto">${esc(r.text)}</span>${btn}</div>`;
}
// Status wording for a chat that is open but has no change: edits -> "Unplanned work", only talking -> "Chat open · no change yet". null when it does not apply.
function chatState(p) {
  if (!on(p) || crInfo(p).open.length || !p.chatOpen) return null;
  if (p.state === 'working' && p.dirty > 0) return { id: 'unplanned', text: t('tl.unplanned'), tone: 'warn' };
  return { id: 'chatonly', text: t('tl.chatOnly'), tone: '' };
}
// The block that stands where the rail would be while no change is open.
function idleBlock(p, st) {
  const nm = esc(p.name), d = lastDone(p), noStart = ['held', 'integrity', 'frozen', 'limit', 'hardstop', 'cpause'].includes(st.id);
  const last = d ? t('tl.lastChange') + ' ' + esc(d.id) + (d.title ? ` <bdi dir="auto">${esc(d.title)}</bdi>` : '') + (d.date ? ' · ' + esc(t('tl.doneOn', { date: d.date })) : '') : esc(t('tl.noChangeYet'));
  const cmd = (label, aria) => `<button type="button" class="btn tlcr" data-act="tlcr" data-project="${nm}" title="${esc(t('tl.startTip'))}" aria-label="${esc(t(aria, { project: p.name }))}">${esc(t(label))}</button>`;
  const next = noStart ? '' : st.id === 'unplanned' ? `<div class="tln">${cmd('tl.track', 'tl.trackAria')}</div>`
    : `<div class="tln"><span>${esc(t('tl.nextStart', { first: D.stageNames(p)[0] }))}</span>${cmd('tl.start', 'tl.startAria')}</div>`;
  return `<div class="tlidle" data-tlidle role="group" aria-label="${esc(t('tl.idleAria', { project: p.name }))}"><div class="tll">${last}</div>${next}</div>`;
}
const stageLabelsFor = (p, names) => {                         // display only: the last step reads "Done" (Ship/Post/Send/Apply/File are the old words) unless the data renames it itself
  if (!on(p)) return names;
  const out = names.slice(), legacy = names[names.length - 1], sl = p.stageLabels && p.stageLabels.deliver;
  const stock = ['Release', 'Apply', 'File', 'Publish', 'Hand over'];     // the playbooks' own last-step names (shipmiracle/playbooks/*.json): the engine always sends one of them, so they are the old word, not a rename
  out[out.length - 1] = sl && sl !== legacy && !stock.includes(sl) ? sl : t('tl.done'); return out;
};
function historyBlock(p) {
  const h = hist(p); if (!h.length) return '';
  const id = 'tlh-' + String(p.name).replace(/[^A-Za-z0-9_-]/g, '_'), groups = [];
  for (const x of h) { const v = x.release ? ver(x.release) : ''; const g = groups.find(q => q.v === v); if (g) g.items.push(x); else groups.push({ v, items: [x] }); }
  const last = p.release && p.release.last && p.release.last.version ? ver(p.release.last.version) : '';
  const body = groups.map(g => {
    const head = g.v ? t('tl.hRel', { v: g.v }) + (g.v === last && dm(p.release.last.date) ? ' · ' + dm(p.release.last.date) : '') : t('tl.hNone');
    return `<h5 dir="auto">${esc(head)}</h5><ul>${g.items.map(x => `<li><b>${esc(x.id)}</b> <bdi dir="auto">${esc(x.title || '')}</bdi>${DONE.includes(x.status) ? '' : ' · ' + esc(String(x.status || ''))}${dm(x.closed) ? ' · ' + esc(dm(x.closed)) : ''}</li>`).join('')}</ul>`;
  }).join('');
  return `<div class="tlhw"><button type="button" class="lnk tlhb" data-tlh="${esc(p.name)}" aria-expanded="false" aria-controls="${id}" aria-label="${esc(t('tl.histAria', { n: h.length, project: p.name }))}">${esc(t('tl.hist', { n: h.length }))} <span class="tlchev" aria-hidden="true">▸</span></button><div class="tlhist" id="${id}" role="region" aria-label="${esc(t('tl.histRegion', { project: p.name }))}" hidden>${body}</div></div>`;
}
return { on, releaseOf, releaseLine, chatState, idleBlock, historyBlock, stageLabelsFor };
};
Object.assign(module.exports, { cleanRelease, cleanHistory, markArgv, openLine, verOk, cmpVer, ver, css, clientJs });       // the pure parts, usable without a card (the extension re-checks every click with them)
