// Card extras of the panel v3 UX addendum (21 Oct): F9 Details region, F8 marker helpers, F7 Set aside list, F5 Toolbox sheet, F6 Describe your work (choice sheet, mirror, draft), plus their CSS and the page script
// they need. Split out of panel.js to keep it under the export's 200 KB file limit. A factory: panel.js passes the few helpers it shares (t, esc, strings, step tables).
module.exports = function make(D) {
const { t, esc, S, cap, crInfo, stageNames, STAGE_IDS, STEPS } = D;
// ---- F9 Details (UX addendum 2026-10-21 section 5, layout A). The collapsed card gets one 22 px toggle in the title row and, when the project is quiet, one grey line under Next.
// The region holds four read-only blocks in a fixed order (Now, Last from the chat, Latest report, STATUS), each a heading line over a label/value grid. All text is escaped; the data
// (chat excerpt, report, STATUS line) comes from the extension's `detail` answer (detail.js) and is already cleaned and capped there and again in sane.js.
let CTX = { detail: Object.create(null), settings: { cardChatExcerpt: true, unreadMarker: true }, capabilities: {} };       // set by render(): the whole data object
const own1 = (o, k) => o && Object.prototype.hasOwnProperty.call(o, k) ? o[k] : undefined;
const p2 = n => String(n).padStart(2, '0');
function relTime(ts, nowMs = Date.now()) {                  // 5i Time: under a minute "just now", under an hour "N min ago", today "N h ago", "yesterday", "20 Oct", "20 Oct 2025"
  const d = new Date(ts * 1000), n = new Date(nowMs), diff = (nowMs - ts * 1000) / 1000;
  if (!(diff >= 60)) return t('details.justNow');
  if (diff < 3600) return t('details.minAgo', { n: Math.floor(diff / 60) });
  if (d.toDateString() === n.toDateString()) return t('details.hAgo', { n: Math.floor(diff / 3600) });
  const y = new Date(n); y.setDate(y.getDate() - 1);
  if (d.toDateString() === y.toDateString()) return t('details.yesterday');
  const day = d.getDate() + ' ' + S.details.months[d.getMonth()];
  return d.getFullYear() === n.getFullYear() ? day : day + ' ' + d.getFullYear();
}
function absTime(ts) { const d = new Date(ts * 1000); return d.getDate() + ' ' + S.details.months[d.getMonth()] + ' ' + d.getFullYear() + ', ' + p2(d.getHours()) + ':' + p2(d.getMinutes()); }
const timeEl = (ts, cls = '') => ts > 0 ? `<time${cls ? ` class="${cls}"` : ''} datetime="${esc(new Date(ts * 1000).toISOString())}" title="${esc(absTime(ts))}">${esc(relTime(ts))}</time>` : '';
const dId = name => 'detail-' + String(name).replace(/[^A-Za-z0-9_-]/g, '_');
const dRow = (label, valueHtml, cls = '', attrs = '') => `<dt>${esc(label)}</dt><dd${cls ? ` class="${cls}"` : ''}${attrs}>${valueHtml}</dd>`;
const dBlock = (idx, pid, title, time, body) => `<section class="dblk" aria-labelledby="${pid}-h${idx}"><div class="dh"><h4 id="${pid}-h${idx}">${esc(title)}</h4>${time || ''}</div>${body}</section>`;
function quietText(q) { return '◷ ' + t('details.quiet', { n: q.min }) + (q.tests ? ' ' + t('details.quietTests', { n: q.tests }) : ''); }
const MDL = m => cap(String(m || '').trim().split(/\s+/)[0]);
function stageWord(p) {                                     // the name of the step the project is at (the card's own words), '' when unknown
  const a = crInfo(p).active;
  if (p.playbook && a) return stageNames(p)[STAGE_IDS.indexOf(a.stage)] || '';
  const fs = p.flow && p.flow.stage; const hit = STEPS.find(x => x[0] === fs); return hit ? hit[1] : (fs === 'done' ? 'Done' : '');
}
function nowBlock1(p, pid) {
  const rows = [], run = (p.agents || []).filter(a => !a.stalled), idle = !(p.state === 'working' || p.state === 'needs-input') && !run.length, nowMs = Date.now();
  if (p.quiet) rows.push(dRow(t('details.rowQuiet'), `<span class="dquiet">${esc(quietText(p.quiet))}</span>`, 'c2'));
  const stg = stageWord(p);
  if (idle) rows.push(dRow(t('details.rowStage'), esc(t('details.agentNone'))));
  else if (stg) rows.push(dRow(t('details.rowStage'), esc(stg)));
  if (idle) rows.push(dRow(t('details.rowAgent'), esc(t('details.agentNone'))));
  else if (run.length) {
    const one = a => { const nm = a.type + (a.model ? ' (' + MDL(a.model) + ')' : ''); return a.quiet != null ? t('details.agentVal', { agent: nm, when: relTime((nowMs / 1000) - a.quiet, nowMs) }) : nm; };
    const lines = run.slice(0, 3).map(a => `<div class="c2" dir="auto">${esc(one(a))}</div>`);
    if (run.length > 3) lines.push(`<div>${esc(t('details.moreAgents', { n: run.length - 3 }))}</div>`);
    rows.push(dRow(t('details.rowAgent'), lines.join('')));
  }
  if (p.lastCommit > 0 || p.dirty > 0) rows.push(dRow(t('details.rowCommit'), esc(p.lastCommit > 0 ? (p.dirty > 0 ? t('details.commitVal', { when: relTime(p.lastCommit), n: p.dirty }) : relTime(p.lastCommit)) : t('details.commitOnly', { n: p.dirty }))));
  return rows.length ? dBlock(1, pid, t('details.now'), '', `<dl class="dg">${rows.join('')}</dl>`) : '';
}
function chatBlock1(p, pid, dt) {
  if (!CTX.settings.cardChatExcerpt) return dBlock(2, pid, t('details.chat'), '', `<p class="dnote">${esc(t('details.chatHidden', { setting: t('details.settingName') }))}</p>`);
  const c = dt.chat; if (!c || c.state === 'none') return '';
  if (c.state === 'hidden') return dBlock(2, pid, t('details.chat'), '', `<p class="dnote">${esc(t('details.chatHidden', { setting: t('details.settingName') }))}</p>`);
  if (c.state === 'error') return dBlock(2, pid, t('details.chat'), '', `<p class="dnote">${esc(t('details.chatError'))}</p>`);
  const more = `<button type="button" class="lnk dmore" data-dmore aria-expanded="false" data-more="${esc(t('details.showMore'))}" data-less="${esc(t('details.showLess'))}" hidden>${esc(t('details.showMore'))}</button>`;
  return dBlock(2, pid, t('details.chat'), timeEl(c.ts, ''), `<div class="dq" dir="auto">${esc(c.text)}</div>${more}${c.tool ? `<dl class="dg">${dRow(t('details.rowTool'), esc(c.tool))}</dl>` : ''}`);
}
const VERD = { PASS: ['✓', 'dv-pass'], FAIL: ['✕', 'dv-fail'], BLOCKED: ['!', 'dv-blk'] };
function reportBlock1(p, pid, dt) {
  const r = dt.report; if (!r) return '';
  const rows = [], v = VERD[r.verdict];
  if (v) rows.push(dRow(t('details.rowVerdict'), `<span class="${v[1]}"><span aria-hidden="true">${v[0]}</span> ${esc(r.verdict)}</span>`));
  if (r.title) rows.push(dRow(t('details.rowTitle'), esc(r.title), 'c1', ` dir="auto" title="${esc(r.title)}"`));
  if (r.summary) rows.push(dRow(t('details.rowSummary'), esc(r.summary), 'c3', ' dir="auto"'));
  const link = `<div class="dlink"><button type="button" class="lnk" data-rv="open" data-id="${esc(r.id)}" aria-label="${esc(t('details.reportLinkAria', { project: p.name }))}">${esc(t('details.reportLink'))}</button></div>`;
  return dBlock(3, pid, t('details.report'), timeEl(r.ts), `${rows.length ? `<dl class="dg">${rows.join('')}</dl>` : ''}${link}`);
}
function statusBlock1(p, pid, dt) {
  const s = dt.status, rows = [];
  if (s && s.note) rows.push(dRow(t('details.rowNote'), esc(s.note), 'c4', ' dir="auto"'));
  if (p.next) rows.push(dRow(t('details.rowNext'), esc(p.next), 'c2', ' dir="auto"'));
  return rows.length ? dBlock(4, pid, t('details.status'), s ? timeEl(s.ts) : '', `<dl class="dg">${rows.join('')}</dl>`) : '';
}
// -> { html, ready }: the region's inner markup. No entry for the project = loading (96 px reserved); an error entry = the one-sentence error with Try again.
function detailInner(p, pid) {
  const dt = own1(CTX.detail, p.name);
  if (!dt) return { html: `<p class="dload">${esc(t('details.loading'))}</p>`, ready: false };
  if (dt.error) return { html: `<div class="dload"><p class="dnote">${esc(t('details.error'))}</p><button type="button" class="lnk" data-dretry="${esc(p.name)}">${esc(t('details.retry'))}</button></div>`, ready: false };
  const blocks = [nowBlock1(p, pid), chatBlock1(p, pid, dt), reportBlock1(p, pid, dt), statusBlock1(p, pid, dt)].filter(Boolean);
  return { html: blocks.length ? blocks.join('') : `<p class="dnote">${esc(t('details.empty'))}</p>`, ready: true };
}
function detailRegion(p) {
  const id = dId(p.name), pid = id.replace(/^detail-/, 'd-') , inner = detailInner(p, pid);
  return { ready: inner.ready, html: `<div class="dtl" id="${id}" role="region" aria-label="${esc(t('details.region', { project: p.name }))}" hidden>${inner.html}</div>` };
}
const detailToggle = p => `<button type="button" class="dtog" data-project="${esc(p.name)}" aria-expanded="false" aria-controls="${dId(p.name)}" aria-label="${esc(t('details.toggleAria', { project: p.name }))}" title="${esc(t('details.toggleTip'))}" data-tip="${esc(t('details.toggleTip'))}" data-tipopen="${esc(t('details.toggleTipOpen'))}"><span class="dchev" aria-hidden="true">▾</span></button>`;
// ---- F7 Set aside (UX addendum 3). Data: p.aside {on, since, note, canAside, reason, backOnList} from `shipm report panel`; shown only when the CLI says caps.aside. The panel only TYPES
// `shipm project aside|unaside NAME` into the owner's terminal (no Enter). An aside project collapses to one quiet row under "Set aside (n)", is left out of Now / Next / Waiting and the tab
// badges; one with backOnList (it started work or hit a hard stop) is a normal card with "Back on the list: ...".
const asideOn = () => CTX.capabilities && CTX.capabilities.aside === true;
const isAsideRow = p => asideOn() && !!p.aside && p.aside.on === true && !p.aside.backOnList;
const sinceText = ts => { const d = new Date(ts * 1000); return d.getDate() + ' ' + S.details.months[d.getMonth()]; };
function asideRows(ps, cardHtml) {
  if (!ps.length) return '';
  const rows = ps.map((p, k) => { const date = sinceText(p.aside.since), nm = esc(p.name);
    return `<div class="asr" data-asiderow="${nm}"><div class="asrh"><button type="button" class="asrb" data-asideopen="${nm}" aria-expanded="false" title="${esc(p.aside.note || '')}" aria-label="${esc(t('aside.rowAria', { project: p.name, date }))}"><span aria-hidden="true">⏸</span> <span class="asn" dir="auto">${nm}</span> · ${esc(t('aside.since', { date }))}</button><button type="button" class="btn quiet asbb" data-aside="unaside" data-project="${nm}">${esc(t('aside.bringBack'))}</button></div><div class="asc" hidden>${cardHtml(p, 1000 + k)}</div></div>`; }).join('');
  return `<section class="asideset" aria-label="${esc(t('aside.heading', { n: ps.length }))}"><button type="button" class="asidehd" data-asidetoggle aria-expanded="false" aria-controls="aside-list">${esc(t('aside.heading', { n: ps.length }))}</button><div id="aside-list" hidden>${rows}</div></section>`;
}
function asideNotice(data) {
  const l = (Array.isArray(data.asideNotice) ? data.asideNotice : []).slice(0, 5);
  return l.map(n => `<div class="asnote" role="status" aria-live="polite"><span>${esc(t(n.why === 'hard_stop' ? 'aside.returnedStop' : 'aside.returnedWork', { project: n.project }))}</span><button type="button" class="btn quiet" data-asidedismiss="${esc(n.project)}" data-ts="${esc(n.ts)}">${esc(t('aside.dismiss'))}</button></div>`).join('');
}
function asideHealth(h) {
  const l = asideOn() && h && Array.isArray(h.aside_items) ? h.aside_items.slice(0, 50) : []; if (!l.length) return '';
  return `<div class="hsec"><div class="hsech">${esc(t('aside.healthHeading', { n: l.length }))}</div><ul class="hlist">${l.map(i => `<li class="hrow"><div class="hmain"><div class="hline1"><b dir="auto">${esc(t('aside.healthRow', { project: i.project, title: i.title || i.kind }))}</b></div></div><button type="button" class="btn quiet" data-aside="unaside" data-project="${esc(i.project)}">${esc(t('aside.bringBack'))}</button></li>`).join('')}</ul></div>`;
}
// ---- F5 Toolbox sheet (UX addendum 1a). Data: p.toolbox {count, changed, assets[{path, stage, stageLabel, purpose, status}]} from `shipm report panel`; shown only when caps.toolbox. Every action TYPES a command
// into the owner's terminal (the extension, no Enter); the panel never edits the playbook.
const tbOn = p => CTX.capabilities.toolbox === true && !!p.toolbox && !!p.playbook;
const busyP = p => p.state === 'working' || p.state === 'needs-input' || (p.agents || []).length > 0;
function toolboxSheet(p) {
  if (!tbOn(p)) return '';
  const nm = esc(p.name), tb = p.toolbox, busy = busyP(p), off = busy ? ` disabled title="${esc(t('toolbox.held'))}"` : '';
  const shown = tb.assets.slice(0, 20), more = tb.assets.length - shown.length + Math.max(0, tb.count - tb.assets.length);
  const rows = shown.map(a => { const bad = a.status !== 'ok', word = a.status === 'ok' ? t('toolbox.ok') : a.status === 'missing' ? t('toolbox.missing') : t('toolbox.changed'), pa = esc(a.path);
    return `<li class="tbr" aria-label="${esc(t('toolbox.rowAria', { path: a.path, stage: a.stageLabel || a.stage, status: word, purpose: a.purpose }))}"><div class="tbh"><b class="tbp" dir="auto" title="${pa}">${pa}</b><span class="chip">${esc(a.stageLabel || a.stage)}</span></div>`
      + `<div class="tbd" dir="auto">${esc(a.purpose)}</div><div class="tbst${bad ? ' tbw' : ''}"><span aria-hidden="true">${bad ? '!' : '✓'}</span> ${esc(word)}</div>${bad ? `<div class="nhint">${esc(t('toolbox.changedHint'))}</div>` : ''}`
      + `<div class="tbact">${bad ? `<button type="button" class="btn quiet" data-tb="resign" data-project="${nm}" data-path="${pa}"${off}>${esc(t('toolbox.resignCmd'))}</button>` : ''}<button type="button" class="btn quiet" data-tb="remove" data-project="${nm}" data-path="${pa}"${off}>${esc(t('toolbox.removeCmd'))}</button></div></li>`; }).join('');
  return `<div class="sheet tbx" data-sheetbox="toolbox" data-project="${nm}" role="group" aria-label="${esc(t('toolbox.heading', { project: p.name }))}" hidden><div class="tbhead"><b>${esc(t('toolbox.heading', { project: p.name }))}</b><button type="button" class="btn quiet" data-sheetclose>${esc(t('toolbox.back'))}</button></div>`
    + `<div class="nhint">${esc(t('toolbox.intro'))}</div>${rows ? `<ul class="tbl">${rows}</ul>${more > 0 ? `<div class="nhint">${esc(t('toolbox.more', { n: more }))}</div>` : ''}` : `<div class="nhint">${esc(t('toolbox.empty'))}</div>`}`
    + `<button type="button" class="btn quiet" data-tb="add" data-project="${nm}"${off}>${esc(t('toolbox.add'))}</button><div class="nhint">${esc(t('toolbox.addNote'))}</div></div>`;
}
// ---- F5 Learn: proposed assets. p.proposed [{path, why, stage, command}] (proposed.js; at most 3). Path and why are plain text; the command is text to COPY: no control here runs it (the owner runs it in a terminal; the engine
// refuses it from a chat). Hidden when there is none.
function proposedBlock(p) {
  if (CTX.capabilities.toolbox !== true || !p.playbook || !Array.isArray(p.proposed) || !p.proposed.length) return '';
  const nm = esc(p.name), rows = p.proposed.map((a, i) => `<li class="tbr prr" aria-label="${esc(t('proposed.rowAria', { path: a.path, why: a.why }))}"><b class="pap" dir="auto">${esc(a.path)}</b><div class="tbd prw" dir="auto">${esc(a.why)}</div>`
    + (a.command ? `<div class="prl">${esc(t('proposed.cmdLabel'))}</div><code class="pcmd" dir="ltr" tabindex="0">${esc(a.command)}</code><div class="tbact"><button type="button" class="btn quiet" data-pacopy="${i}" data-project="${nm}" aria-label="${esc(t('proposed.copyAria', { path: a.path }))}">${esc(t('proposed.addCmd'))}</button></div>`
      : `<div class="nhint">${esc(t('proposed.noCmd'))}</div>`) + '</li>').join('');
  return `<section class="prop" data-proposed="${nm}" aria-label="${esc(t('proposed.heading', { n: p.proposed.length }))}"><b class="proph">${esc(t('proposed.heading', { n: p.proposed.length }))}</b><div class="nhint">${esc(t('proposed.note'))}</div><ul class="tbl">${rows}</ul></section>`;
}
// ---- F6 Describe your work (UX addendum 2). The choice sheet (card menu, projects without a playbook), the read-only mirror of the interview that runs in the owner's terminal, the draft view.
const ivOn = () => CTX.capabilities.interview === true;
function describeSheet(p, i) {
  if (!ivOn() || p.playbook || p.held) return '';
  const nm = esc(p.name), busy = busyP(p), sugg = p.lastCommit > 0 ? 'short' : 'long', cont = !!(p.interview && p.interview.mode === 'short' && ['draft', 'done'].includes(p.interview.status));
  const opt = (v, name, meta, why) => `<label class="dsopt"><input type="radio" name="dsm-${i}" value="${v}"${v === sugg ? ' checked' : ''}><span><b>${esc(name)}</b>${v === sugg ? ` <span class="dsug">${esc(t('describe.suggested'))}</span>` : ''} · ${esc(meta)}<br><span class="nhint">${esc(why)}</span></span></label>`;
  return `<div class="sheet dsx" data-sheetbox="describe" data-project="${nm}" role="group" aria-label="${esc(t('describe.heading', { project: p.name }))}" hidden><fieldset class="chfs"><legend>${esc(t('describe.heading', { project: p.name }))}</legend>`
    + opt('short', t('describe.shortName'), t('describe.shortMeta'), t('describe.shortWhy')) + opt('long', t('describe.longName'), t('describe.longMeta'), t('describe.longWhy') + (cont ? ' ' + t('describe.longContinues') : ''))
    + `</fieldset>${busy ? `<div class="nhint">${esc(t('describe.busy', { project: p.name }))}</div>` : ''}<div class="brow"><button type="button" class="btn go" data-describe="start" data-project="${nm}"${busy ? ` disabled title="${esc(t('describe.busy', { project: p.name }))}"` : ''}>${esc(t('describe.startTerm'))}</button><button type="button" class="btn quiet" data-sheetclose>${esc(t('describe.cancel'))}</button></div></div>`;
}
function interviewBlock(p) {
  const m = p.mirror; if (!ivOn() || !m) return '';
  const nm = esc(p.name), head = `<div class="mh1"><b>${esc(t('describe.mirrorHead', { project: p.name }))}</b><span class="chip">${esc(t(m.mode === 'long' ? 'describe.modeLong' : 'describe.modeShort'))}</span></div>`;
  const sureBtn = (op, label) => `<button type="button" class="btn quiet" data-describe="${op}" data-project="${nm}" data-sure="${esc(t('describe.sure'))}">${esc(label)}</button>`;
  if (m.status === 'asking') {
    const w = Math.max(0, Math.min(10, Math.round((m.total ? m.n / m.total : 0) * 10)));
    return `<div class="mirror" data-mirror="asking">${head}<div aria-live="polite"><div class="mq">${esc(t('describe.progress', { n: m.n, total: m.total }))}</div><div class="sbar" role="progressbar" aria-valuemin="0" aria-valuemax="${m.total}" aria-valuenow="${m.n}" aria-label="${esc(t('describe.progress', { n: m.n, total: m.total }))}"><i class="bw${w}"></i></div>`
      + (m.question ? `<p class="mqt" dir="auto">${esc(m.question.text)}</p>${m.question.recommended ? `<p class="nhint" dir="auto">${esc(t('describe.recommended'))}: ${esc(m.question.recommended)}</p>` : ''}` : '') + `</div>`
      + `<p class="nhint">${esc(t('describe.termHint'))} ${esc(t('describe.keys'))}</p><button type="button" class="btn quiet" data-describe="show" data-project="${nm}">${esc(t('describe.showTerm'))}</button>`
      + (m.assumed.length ? `<div class="nhint">${esc(t('describe.assumed', { n: m.assumed.length }))}</div><ul class="mas">${m.assumed.map(x => `<li dir="auto"><span aria-hidden="true">~</span> ${esc(x)}</li>`).join('')}</ul>` : '')
      + (m.prototype.length ? `<div class="nhint">${esc(t('describe.prototype'))}</div>` : '') + `</div>`;
  }
  if (m.status === 'paused') return `<div class="mirror" data-mirror="paused">${head}<div class="mq">${esc(t('describe.paused', { n: Math.max(1, m.n), total: m.total }))}</div><div class="brow"><button type="button" class="btn go" data-describe="resume" data-project="${nm}">${esc(t('describe.resume'))}</button>${sureBtn('restart', t('describe.startOver'))}</div></div>`;
  if (m.status === 'error') return `<div class="mirror" data-mirror="error">${head}<div class="mq">${esc(t('describe.errInterview'))}</div><div class="brow">${sureBtn('restart', t('describe.startOver'))}</div></div>`;
  if (m.status === 'draft' && m.draftOk) return `<div class="mirror" data-mirror="draft">${head}<div class="mq">${esc(t('describe.draftHeading'))}</div><dl class="dg">${m.rows.map(r => `<dt>${esc(r.label)}</dt><dd dir="auto">${esc(r.text)}</dd>`).join('')}</dl><p class="nhint">${esc(t('describe.draftNote'))}</p>`
    + `<div class="brow"><button type="button" class="btn go" data-describe="open" data-project="${nm}">${esc(t('describe.openDraft'))}</button><button type="button" class="btn" data-describe="set" data-project="${nm}">${esc(t('describe.copySet'))}</button></div></div>`;
  if (m.status === 'draft') return `<div class="mirror" data-mirror="draft-error"><div class="mq">${esc(t('describe.errDraft'))}</div><div class="brow"><button type="button" class="btn go" data-describe="open" data-project="${nm}">${esc(t('describe.openDraft'))}</button>${sureBtn('restart', t('describe.startOver'))}</div></div>`;
  return '';
}
const css = String.raw`/* ---- F9 Details (UX addendum 5): toggle, quiet line, region with four blocks (layout A). Sizes 11 / 12 only, spacing 4 / 8 / 12 only, colours ink / text-2 / accent / status word only ---- */
.top{flex-wrap:nowrap}
.dtog{flex:none;width:22px;min-width:22px;height:22px;margin-block:-2px;padding:0;border:0;border-radius:6px;background:transparent;color:var(--mutt);display:inline-flex;align-items:center;justify-content:center;font-size:12px;line-height:1;cursor:pointer}
.dtog:hover{background:color-mix(in srgb,var(--fg) 8%,transparent);border:0}.dtog:focus-visible{outline:2px solid var(--acc);outline-offset:1px}
.dchev{display:inline-block;transition:transform .15s ease-out}.dtog[aria-expanded="true"] .dchev{transform:rotate(180deg)}
.card.dopen.dok .quietl{display:none}
.dtl{margin-top:8px;padding-top:12px;border-top:1px solid var(--bd);cursor:default;font-size:12px;line-height:17px;font-weight:400;color:var(--fg);text-align:start}
.dtl.anim{overflow:hidden}
.dblk+.dblk{margin-top:12px}
.dh{display:flex;justify-content:space-between;align-items:baseline;gap:8px;margin:0 0 4px;font-size:11px;line-height:16px;color:var(--mutt)}
.dh h4{margin:0;font-size:11px;line-height:16px;font-weight:600;color:var(--mutt)}.dh time{font-weight:400;white-space:nowrap}
.dg{display:grid;grid-template-columns:64px minmax(0,1fr);column-gap:8px;row-gap:4px;align-items:baseline;margin:0}
.dg dt{margin:0;font-size:12px;line-height:17px;font-weight:400;color:var(--mutt)}
.dg dd{margin:0;min-width:0;font-size:12px;line-height:17px;font-weight:400;overflow-wrap:anywhere;color:var(--fg)}
.dg dd.c1,.dg dd.c2,.dg dd.c3,.dg dd.c4,.dg dd .c2{display:-webkit-box;-webkit-box-orient:vertical;overflow:hidden}
.dg dd.c1{-webkit-line-clamp:1}.dg dd.c2,.dg dd .c2{-webkit-line-clamp:2}.dg dd.c3{-webkit-line-clamp:3}.dg dd.c4{-webkit-line-clamp:4}
.dq{display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:4;overflow:hidden;overflow-wrap:anywhere;padding-inline-start:8px;border-inline-start:2px solid var(--bd);color:var(--fg)}
.dq.open{display:block;overflow:visible}
.dq~.dg{margin-top:4px}.dq+.dmore~.dg{margin-top:4px}
.dtl button.lnk{height:22px;min-width:22px;padding:0 4px;font-size:12px;line-height:22px;font-weight:400}
.dmore{display:block;margin:4px 0 0;margin-inline-start:6px}.dmore[hidden]{display:none}
.dlink{margin-top:4px;padding-inline-start:68px}
.dlink:first-child{margin-top:0}
.dnote{margin:0;font-size:12px;line-height:17px;color:var(--mutt)}
.dload{margin:0;min-height:96px;font-size:12px;line-height:17px;color:var(--mutt)}.dload .dnote{margin:0 0 4px}
.dquiet{color:var(--mutt)}
.dv-pass{color:var(--okt);font-weight:600}.dv-fail{color:var(--dangert);font-weight:600}.dv-blk{color:var(--warnt);font-weight:600}
.newm{flex:none;display:inline-flex;align-items:center;gap:4px;font-size:11px;line-height:16px;font-weight:600;color:var(--acct);white-space:nowrap}
.udot{display:inline-block;flex:none;width:6px;height:6px;border-radius:50%;background:var(--acct)}.udotb{position:absolute;inset-inline-start:8px;top:50%;margin-top:-3px;background:currentColor}.brow .btn.primary{position:relative}
body.vscode-high-contrast .udot{outline:1px solid var(--vscode-contrastBorder,currentColor);outline-offset:0}
.asideset{margin:0 0 10px}.asidehd{display:block;width:100%;height:26px;padding:0 4px;border:0;border-top:1px solid var(--bd);border-radius:0;background:transparent;color:var(--mutt);font:inherit;font-size:11.5px;font-weight:600;text-align:start;cursor:pointer}.asidehd::before{content:"▸ "}.asidehd[aria-expanded="true"]::before{content:"▾ "}
.asr{margin:0 0 4px}.asrh{display:flex;align-items:center;justify-content:space-between;gap:8px;min-height:26px}.asrb{flex:1;min-width:0;height:26px;padding:0 4px;border:0;background:transparent;color:var(--mutt);font:inherit;font-size:11.5px;text-align:start;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;cursor:pointer}
.asrb .asn{font-weight:600}.asbb{flex:none;height:24px;padding:0 8px}.asc{margin-top:4px}
.asnote{display:flex;align-items:center;justify-content:space-between;gap:8px;margin:0 0 8px;padding:6px 8px;border-radius:6px;background:var(--acc-soft);font-size:11.5px}.asnote .btn{flex:none;height:24px}
.backl{margin-top:4px;color:var(--warnt)}.asidehd:focus-visible,.asrb:focus-visible{outline:2px solid var(--acc);outline-offset:1px}
body.vscode-high-contrast .asnote{border:1px solid var(--vscode-contrastBorder,currentColor)}
.tbl{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:8px}.tbr{padding:8px;border:1px solid var(--bd);border-radius:6px;display:flex;flex-direction:column;gap:4px}
.tbh{display:flex;align-items:center;justify-content:space-between;gap:8px;min-width:0}.tbp{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12px}.tbd{font-size:11.5px;color:var(--mutt);overflow-wrap:anywhere;display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2;overflow:hidden}
.tbst{font-size:11.5px;color:var(--okt)}.tbst.tbw{color:var(--warnt);font-weight:600}.tbact{display:flex;flex-wrap:wrap;gap:6px}.tbact .btn{height:24px;padding:0 8px;white-space:normal;line-height:1.2}
.prop{margin:8px 0 0;padding:8px 10px;border:1px solid var(--bd);border-radius:6px;display:flex;flex-direction:column;gap:6px}.proph{font-size:12.5px}.pap{font-size:12px;overflow-wrap:anywhere}.prw{display:block;-webkit-line-clamp:unset}
.prl{font-size:11px;font-weight:600;color:var(--mutt)}.pcmd{display:block;padding:6px 8px;border:1px solid var(--bd);border-radius:6px;background:color-mix(in srgb,var(--fg) 6%,transparent);color:var(--fg);font:11px/1.4 var(--vscode-editor-font-family,ui-monospace,monospace);white-space:pre-wrap;overflow-wrap:anywhere;user-select:all}
.pcmd:focus-visible{outline:2px solid var(--acc);outline-offset:1px}body.vscode-high-contrast .prop,body.vscode-high-contrast .pcmd{border:1px solid var(--vscode-contrastBorder,currentColor)}
.dsopt{display:flex;align-items:flex-start;gap:8px;min-height:44px;padding:6px 8px;border:1px solid var(--bd);border-radius:6px;font-size:12px;cursor:pointer}.dsopt input{margin:3px 0 0;flex:none}.dsug{font-size:10.5px;color:var(--acct);font-weight:600}
.mirror{margin-top:8px;padding:8px 10px;border:1px solid var(--bd);border-radius:6px;display:flex;flex-direction:column;gap:6px;cursor:default}.mh1{display:flex;align-items:center;justify-content:space-between;gap:8px;font-size:12px}.mq{font-size:12px}.mqt{margin:0;font-size:12.5px;font-weight:600;overflow-wrap:anywhere}.mirror p{margin:0}
.mas{list-style:none;margin:0;padding:0;font-size:11.5px;color:var(--mutt)}.mas li{overflow-wrap:anywhere}.bw0{width:0}.mirror .brow{margin-top:0}.mirror .dg{margin:0}.mirror .dg dd{overflow-wrap:anywhere}
body.vscode-high-contrast .mirror,body.vscode-high-contrast .tbr,body.vscode-high-contrast .dsopt{border:1px solid var(--vscode-contrastBorder,currentColor)}
body.vscode-high-contrast .dtog{border:1px solid var(--vscode-contrastBorder,currentColor)}
body.vscode-high-contrast .dtl{border-top-color:var(--vscode-contrastBorder,currentColor)}body.vscode-high-contrast .dq{border-inline-start-color:var(--vscode-contrastBorder,currentColor)}
body.vscode-high-contrast .dh,body.vscode-high-contrast .dh h4,body.vscode-high-contrast .dg dt,body.vscode-high-contrast .dnote,body.vscode-high-contrast .dload,body.vscode-high-contrast .dquiet,body.vscode-high-contrast .dtog,body.vscode-high-contrast .quietl{color:var(--fg)}`;
const clientJs = String.raw`// ---- F9 Details: open / close the region of a card, ask the extension for the text, keep the open set across redraws. The page sends only {type:'detail', project}.
const dOpenSet = () => S.dopen || (S.dopen = {});
const dReduced = () => window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const dToggleOf = name => [...document.querySelectorAll('.dtog')].find(b => b.dataset.project === name) || null;
function dMeasure(reg) {                                    // "Show more" exists only for a quote that is clamped (measured here, while the region is visible and before it animates)
  reg.querySelectorAll('.dq').forEach(q => { const more = q.parentElement.querySelector('[data-dmore]'); if (!more) return; const open = more.getAttribute('aria-expanded') === 'true'; if (!open) more.hidden = !(q.scrollHeight > q.clientHeight + 1); });
}
function dAsk(name) { vscode.postMessage({ type: 'detail', project: name }); }
let dTimer = 0;
function dSchedule() { clearInterval(dTimer); dTimer = 0; if (Object.keys(dOpenSet()).length) dTimer = setInterval(() => { Object.keys(dOpenSet()).forEach(dAsk); }, 30000); }   // the extension answers from its 15 s cache, so this costs one read at most
function dSet(tog, open, o = {}) {
  const reg = document.getElementById(tog.getAttribute('aria-controls')), card = tog.closest('.card'), name = tog.dataset.project; if (!reg) return;
  tog.setAttribute('aria-expanded', open ? 'true' : 'false'); tog.title = open ? tog.dataset.tipopen : tog.dataset.tip;
  reg.getAnimations().forEach(a => a.cancel()); reg.classList.remove('anim');
  if (open) {
    reg.hidden = false; card.classList.add('dopen'); dMeasure(reg);
    if (!o.restore && !dReduced() && reg.animate) { const h = reg.getBoundingClientRect().height; reg.classList.add('anim'); const a = reg.animate([{ height: '0px', opacity: 0 }, { height: h + 'px', opacity: 1 }], { duration: 150, easing: 'ease-out' }); a.onfinish = a.oncancel = () => reg.classList.remove('anim'); }
    dOpenSet()[name] = 1; vscode.setState(S); dSchedule(); dAsk(name);
  } else {
    const done = () => { reg.hidden = true; reg.classList.remove('anim'); card.classList.remove('dopen'); };
    if (!o.restore && !dReduced() && reg.animate) { const h = reg.getBoundingClientRect().height; reg.classList.add('anim'); const a = reg.animate([{ height: h + 'px', opacity: 1 }, { height: '0px', opacity: 0 }], { duration: 120, easing: 'ease-out' }); a.onfinish = done; a.oncancel = () => { if (tog.getAttribute('aria-expanded') !== 'true') done(); }; } else done();
    delete dOpenSet()[name]; vscode.setState(S); dSchedule();
  }
}
function dCloseFrom(el) { const card = el.closest('.card'), tog = card && card.querySelector('.dtog'); if (!tog || tog.getAttribute('aria-expanded') !== 'true') return false; dSet(tog, false); tog.focus(); return true; }
{ const set = dOpenSet(); Object.keys(set).forEach(n => { const tg = dToggleOf(n); if (tg) dSet(tg, true, { restore: true }); else delete set[n]; }); vscode.setState(S); }
// ---- F5: Copy for a proposed asset's add command. The page sends only the project and the row number; the extension copies the command it built itself (nothing is run).
document.addEventListener('click', e => { const b = e.target.closest('[data-pacopy]'); if (!b) return; e.stopImmediatePropagation(); vscode.postMessage({ type: 'proposed', op: 'copy', project: b.dataset.project || '', i: Number(b.dataset.pacopy) }); });
// ---- F7: the Set aside list under Projects (kept open across redraws) and one card shown for a look
function asideList(open, restore) { const b = $(document, '[data-asidetoggle]'); if (!b) return; b.setAttribute('aria-expanded', open ? 'true' : 'false'); const l = document.getElementById('aside-list'); if (l) l.hidden = !open; if (open) S.asideList = 1; else { delete S.asideList; delete S.asideCard; } vscode.setState(S); }
function asideCard(name, open, focus) { const row = [...document.querySelectorAll('[data-asiderow]')].find(r => r.dataset.asiderow === name); if (!row) return; const b = $(row, '[data-asideopen]'), c = $(row, '.asc'); b.setAttribute('aria-expanded', open ? 'true' : 'false'); c.hidden = !open; if (open) S.asideCard = name; else if (S.asideCard === name) delete S.asideCard; vscode.setState(S); if (focus && !open) b.focus(); }
if (S.asideList) asideList(true, true);
if (S.asideCard) { if ($(document, '[data-asidetoggle]') && S.asideList) asideCard(S.asideCard, true); else delete S.asideCard; }`;
return { setCtx: d => { CTX = d; }, getCtx: () => CTX, detailRegion, detailToggle, quietText, toolboxSheet, proposedBlock, describeSheet, interviewBlock, asideRows, asideNotice, asideHealth, isAsideRow, asideOn, tbOn, ivOn, css, clientJs };
};
