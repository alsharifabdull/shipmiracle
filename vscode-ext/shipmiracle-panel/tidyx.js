// Tidy up card (G2 step 4, UX addendum section 11): a read-only Health section that shows what `shipm tidy` last measured (<state>/v1/tidy.json, written weekly by the daily check) and offers ONE button that
// only TYPES `shipm tidy --all` into a terminal (the extension builds that command itself; the page sends {type:'tidy-open'} and nothing else). Pure Node, no vscode, the same split as proposed.js:
//   read(stateDir)  -> {status:'none'|'bad'|'ok', doc}   size-capped, no symlink, no FIFO, a missing file is 'none', anything else unusable is 'bad'
//   clean(doc, names) -> the model the card draws: {state:'none'|'bad'|'ok', ...}. NOTHING from the file is trusted: every number is a finite integer 0..2^53, only the known keys are read, a project is kept only when its
//        name is in the registry (the displayed name is the registry's own), at most 100 projects and 8 scans, and the condition (weeks over / met) is RE-DERIVED from the stored scans; a stored condition that
//        disagrees makes the whole file 'bad'. There is no file name, path or free text in the file, so none can reach the page.
//   card(model, o)  -> the HTML section (everything escaped; sizes are plain text; no live region, no animation, no status colour; one button).
const fs = require('fs'), path = require('path');
const REPORTS = require('./reports');
const STR = require('./strings').tidy;

const MAX_FILE = 64 * 1024, MAX_SCANS = 8, MAX_PROJECTS = 100, MAX_ROWS = 3, OLD_DAYS = 9, WRITER = 'shipmiracle-tidy';
const MAXN = 2 ** 53, KEYS = ['disposable', 'regenerable_idle', 'regenerable_in_use', 'review'];
const own = (o, k) => Object.prototype.hasOwnProperty.call(o, k);
const isObj = v => !!v && typeof v === 'object' && !Array.isArray(v);
const int = v => typeof v === 'number' && Number.isInteger(v) && v >= 0 && v <= MAXN;
const RANGES = [[0, 31], [127, 159], [173, 173], [1564, 1564], [8203, 8207], [8232, 8238], [8288, 8303], [65279, 65279], [57344, 63743], [65529, 65531]];   // controls, soft hyphen, bidi and zero-width marks, private use
const CTRL = new RegExp('[' + RANGES.map(([a, b]) => String.fromCharCode(a) + (b > a ? '-' + String.fromCharCode(b) : '')).join('') + ']', 'g');

// ---- reading
function read(stateDir) {
  const f = path.join(stateDir, 'v1', 'tidy.json');
  try { fs.lstatSync(f); } catch (e) { return { status: e && e.code === 'ENOENT' ? 'none' : 'bad' }; }
  const r = REPORTS.readCapped(f, MAX_FILE, false);                    // O_NOFOLLOW + O_NONBLOCK, regular file only, at most 64 KB
  if (!r.ok) return { status: 'bad' };
  try { return { status: 'ok', doc: JSON.parse(r.text) }; } catch (e) { return { status: 'bad' }; }
}

// ---- cleaning
const shownName = n => { const c = n.replace(CTRL, ''); return c.length > 200 ? c.slice(0, 199) + String.fromCharCode(8230) : c; };   // the CSS clamps to 2 lines with an ellipsis; the title carries the same text
const BAD = Object.freeze({ state: 'bad' }), NONE = Object.freeze({ state: 'none' });
function bytesOf(b) {                                                    // {disposable, regenerable_idle, regenerable_in_use, review} -> same keys, or null
  if (!isObj(b)) return null;
  const o = {}; let sum = 0;
  for (const k of KEYS) { if (!own(b, k) || !int(b[k])) return null; o[k] = b[k]; sum += b[k]; }
  return sum <= MAXN ? o : null;
}
// A PROJECT row as the engine writes it: bytes {disposable, regenerable, review, never} plus its own `freeable` (disposable + regenerable only when the project is idle: the panel does not guess idleness).
// -> {free, decide} or null. free is the engine's number after a sanity check (0 <= freeable <= disposable + regenerable); decide is bytes.review.
function projBytes(b, freeable) {
  if (!isObj(b) || !int(freeable)) return null;
  let sum = 0; for (const k of ['disposable', 'regenerable', 'review', 'never']) { if (!own(b, k) || !int(b[k])) return null; sum += b[k]; }
  if (sum > MAXN || freeable > b.disposable + b.regenerable) return null;
  return { free: freeable, decide: b.review };
}
const freeOf = b => b.disposable + b.regenerable_idle, decideOf = b => b.review + b.regenerable_in_use;
// -> weeks in a row over the threshold, newest first. A week with no complete scan is skipped (neither counts nor resets); a lower week stops the run; strictly more than the threshold; one entry per week.
function deriveWeeks(scans, threshold) {
  const seen = new Set(), weeks = [];
  for (const s of scans.slice().sort((a, b) => b.ts - a.ts)) { if (!s.complete || seen.has(s.week)) continue; seen.add(s.week); weeks.push(s); }
  let k = 0; for (const s of weeks) { if (freeOf(s.bytes) > threshold) k++; else break; }
  return k;
}
// doc: the parsed envelope {v, ts, writer, data}. names: the project registry (array or Set of names).
function clean(doc, names) {
  try {
    if (!isObj(doc) || doc.v !== 1 || doc.writer !== WRITER || !isObj(doc.data)) return BAD;
    const d = doc.data;
    if (d.schema !== 1 || !Array.isArray(d.scans) || d.scans.length > MAX_SCANS || !Array.isArray(d.projects) || d.projects.length > MAX_PROJECTS || !isObj(d.condition)) return BAD;
    const scans = [];
    for (const s of d.scans) {
      if (!isObj(s)) return BAD;
      const bytes = bytesOf(s.bytes);
      if (typeof s.ts !== 'number' || !Number.isFinite(s.ts) || s.ts <= 0 || s.ts > 4102444800 || typeof s.iso_week !== 'string' || !/^\d{4}-W(0[1-9]|[1-4]\d|5[0-3])$/.test(s.iso_week)
        || typeof s.complete !== 'boolean' || !int(s.projects_scanned) || !int(s.projects_skipped) || typeof s.duration_s !== 'number' || !Number.isFinite(s.duration_s) || s.duration_s < 0 || !bytes) return BAD;
      scans.push({ ts: s.ts, week: s.iso_week, complete: s.complete, scanned: s.projects_scanned, bytes });
    }
    const c = d.condition;
    if (!int(c.threshold_bytes) || c.threshold_bytes < 1 || !int(c.weeks_needed) || c.weeks_needed < 2 || c.weeks_needed > MAX_SCANS || !int(c.weeks_over) || typeof c.met !== 'boolean') return BAD;
    const over = deriveWeeks(scans, c.threshold_bytes), met = over >= c.weeks_needed;
    if (c.weeks_over !== over || c.met !== met) return BAD;                // a stored condition that the history does not support: nothing from the file is shown
    const reg = new Set(names || []);
    const rows = [], seenName = new Set();
    for (const p of d.projects) {
      if (!isObj(p) || typeof p.name !== 'string' || !reg.has(p.name) || seenName.has(p.name)) { if (!isObj(p)) return BAD; continue; }   // not in the registry (or a repeat): dropped, never shown
      const pb = projBytes(p.bytes, p.freeable);
      if (!pb || typeof p.partial !== 'boolean') return BAD;
      seenName.add(p.name);
      const { free, decide } = pb, shown = shownName(p.name);
      if (free || decide) rows.push({ name: shown, full: shown, free, decide, partial: p.partial });
    }
    rows.sort((a, b) => b.free - a.free || (a.name < b.name ? -1 : a.name > b.name ? 1 : 0));
    if (!scans.length) return NONE;
    const top = scans.slice().sort((a, b) => b.ts - a.ts)[0];
    return { state: 'ok', ts: top.ts, scanned: top.scanned, free: freeOf(top.bytes), decide: decideOf(top.bytes), partialTotal: !top.complete, rows, threshold: c.threshold_bytes, needed: c.weeks_needed, over, met };
  } catch (e) { return BAD; }
}
// -> the model for a state folder and a registry. Never throws.
function load(stateDir, names) {
  try { const r = read(stateDir); return r.status === 'none' ? NONE : r.status === 'bad' ? BAD : clean(r.doc, names); } catch (e) { return BAD; }
}

// ---- formatting
const UNITS = ['B', 'KB', 'MB', 'GB', 'TB'], NB = String.fromCharCode(160);                        // a non-breaking space between number and unit
function size(n) {                                                       // 1024-based, one decimal below 10, whole from 10, ".0" dropped, a rounded 1024 moves to the next unit
  if (!int(n)) return '0' + NB + 'B';
  if (n < 1024) return n + NB + 'B';
  let v = n, i = 0; while (v >= 1024 && i < 4) { v /= 1024; i++; }
  const rnd = x => (x < 10 ? Math.floor(x * 10 + 0.5) / 10 : Math.floor(x + 0.5));
  let r = rnd(v);
  if (r >= 1024 && i < 4) { r = 1; i++; }
  return String(r) + NB + UNITS[i];
}
const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'], p2 = n => (n < 10 ? '0' : '') + n;
const dayNo = d => Math.floor(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()) / 864e5);
function daysSince(tsSec, nowMs) { const d = dayNo(new Date(nowMs)) - dayNo(new Date(tsSec * 1000)); return d > 0 ? d : 0; }   // local calendar days; a date in the future reads as today
function absolute(tsSec) { const d = new Date(tsSec * 1000); return `${d.getDate()} ${MON[d.getMonth()]} ${d.getFullYear()}, ${p2(d.getHours())}:${p2(d.getMinutes())}`; }

// ---- the card
const esc = s => String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
const fill = (k, o = {}) => esc(STR[k]).replace(/\{(\w+)\}/g, (m, n) => (o[n] != null ? o[n] : ''));   // the template is escaped, the slots are already safe html
const bdi = s => `<bdi dir="ltr">${esc(s)}</bdi>`;
const summaryKey = m => {
  if (!m.scanned) return 'noProjects';
  if (!m.free && !m.decide) return m.partialTotal ? 'emptyP' : 'empty';
  const p = m.partialTotal ? 'P' : '';
  return (m.free && m.decide ? 'sumBoth' : m.free ? 'sumFree' : 'sumDecide') + p;
};
// model: the output of clean()/load() (re-checked here: anything that is not a known shape reads as 'could not be read'). o: {now (ms), tool (false = the extension cannot type a command)}.
function card(model, o = {}) {
  if (model === undefined) return '';                                    // older data without the field: no card
  const nowMs = Number.isFinite(o.now) ? o.now : Date.now();
  let m = model; if (!isObj(m) || !['none', 'bad', 'ok'].includes(m.state)) m = BAD;
  if (m.state === 'ok' && !(Number.isFinite(m.ts) && int(m.free) && int(m.decide) && int(m.scanned) && Array.isArray(m.rows) && int(m.over) && int(m.needed) && int(m.threshold) && typeof m.met === 'boolean')) m = BAD;
  const toolOk = o.tool !== false;
  let body = '';
  if (m.state === 'none') body = `<p class="tds">${fill('none')}</p>`;
  else if (m.state === 'bad') body = `<p class="tds">${fill('unreadable')}</p>`;
  else {
    const key = summaryKey(m), days = daysSince(m.ts, nowMs), rows = m.rows.filter(r => isObj(r) && int(r.free) && int(r.decide) && (r.free || r.decide) && typeof r.name === 'string');
    const shown = rows.slice(0, MAX_ROWS), anyP = m.partialTotal || shown.some(r => r.partial === true);
    const found = m.scanned > 0 && (m.free > 0 || m.decide > 0);
    body = `<p class="tds">${fill(key, { free: bdi(size(m.free)), decide: bdi(size(m.decide)) })}</p>`;
    if (days > OLD_DAYS) body += `<p class="tdn">${fill('old', { n: days })}</p>`;
    if (anyP && (found || key === 'emptyP')) body += `<p class="tdn">${fill('partial')}</p>`;
    if (found) {
      if (shown.length) body += '<ul class="tdl">' + shown.map(r => {
        const P = m.partialTotal || r.partial === true;
        return `<li><span class="tdname" dir="auto" title="${esc(r.full || r.name)}">${esc(r.name)}</span>`
          + (r.free ? `<span class="tdz">${fill(P ? 'rowFreeP' : 'rowFree', { size: bdi(size(r.free)) })}</span>` : '')
          + (r.decide ? `<span class="tdz tdm">${fill(P ? 'rowDecideP' : 'rowDecide', { size: bdi(size(r.decide)) })}</span>` : '') + '</li>';
      }).join('') + '</ul>';
      const more = rows.length - shown.length;
      if (more > 0) body += `<p class="tdn tdmore">${more === 1 ? fill('more1') : fill('moreN', { n: more })}</p>`;
    }
    if (m.met) body += `<p class="tdw">${fill('met', { size: bdi(size(m.threshold)), n: m.needed })}</p>`;       // the history is independent of the newest numbers: shown in every state that has a report
    else if (m.over >= 1 && m.over < m.needed) body += `<p class="tdw">${fill('weeks', { size: bdi(size(m.threshold)), k: m.over, n: m.needed })}</p>`;
    const when = days === 0 ? STR.today : days === 1 ? STR.yesterday : STR.daysAgo.replace('{n}', days);
    body += `<p class="tdn tdmeta">${fill('checked', { when: `<time datetime="${esc(new Date(m.ts * 1000).toISOString())}" title="${esc(absolute(m.ts))}">${esc(when)}</time>` })}</p>`;
  }
  const btn = `<button type="button" class="btn tdbtn" data-tidyopen title="${esc(STR.openTip)}"${toolOk ? '' : ' aria-disabled="true"'}>${esc(STR.open)}</button>`;
  return `<section class="hsec tdy" aria-labelledby="tidy-h"><h3 class="hsech" id="tidy-h">${esc(STR.heading)}</h3>${body}${btn}`
    + (toolOk ? `<p class="tdn tdnotice" data-tidynote hidden>${esc(STR.typed)}</p>` : `<p class="tdn tdnotice">${esc(STR.noTool)}</p>`)
    + `<p class="tdn tdfoot">${esc(STR.foot)}</p></section>`;
}

const css = `.tdy{--tdink:var(--fg)}body.vscode-light .tdy{--tdink:color-mix(in srgb,var(--fg) 50%,#000)}body.vscode-high-contrast .tdy{--tdink:var(--fg)}   /* ink: the theme foreground; Light+ foreground is a mid grey, so ink is darkened there to stay above the grey text-2 */
.tdy h3{margin:0 0 4px;font-size:12px;line-height:17px;font-weight:600;color:var(--tdink)}.tdy p,.tdy li{margin:0;font-size:12px;line-height:17px;color:var(--tdink);overflow-wrap:anywhere}
.tdy .tdn{margin-top:4px;font-size:11px;line-height:16px;color:var(--mutt)}.tdy .tdl{list-style:none;margin:8px 0 0;padding:0}.tdy .tdl li+li{margin-top:8px}
.tdy .tdname{display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2;overflow:hidden;font-weight:600;text-align:start;overflow-wrap:anywhere}
.tdy .tdz{display:block;text-align:start}.tdy .tdz+.tdz{margin-top:4px}.tdy .tdm{color:var(--mutt)}.tdy .tdmore{margin-top:8px}.tdy .tdw,.tdy .tdmeta{margin-top:8px}
.tdy .tdbtn{color:var(--tdink);display:block;width:100%;min-width:0;height:auto;min-height:24px;margin-top:8px;padding:2px 4px;white-space:normal;text-overflow:clip}.tdy .tdnotice,.tdy .tdfoot{margin-top:8px}.tdy .tdbtn[aria-disabled="true"]{color:var(--mutt);cursor:not-allowed;border-style:dashed}
.tdy *{transition:none!important;animation:none!important}body.vscode-high-contrast .tdy .tdn,body.vscode-high-contrast .tdy .tdm,body.vscode-high-contrast .tdy .tdbtn[aria-disabled="true"]{color:var(--fg)}body.vscode-high-contrast .tdy{border:1px solid var(--vscode-contrastBorder,currentColor)}
body.vscode-high-contrast .tdy .tdbtn:focus-visible{outline:2px solid var(--vscode-focusBorder,var(--acc))}`;
// The page side: one click handler. It sends {type:'tidy-open'} and NOTHING else (the extension types the fixed command), then shows the notice until the next redraw. A disabled button does nothing.
const clientJs = `document.addEventListener('click', e => { const b = e.target.closest('[data-tidyopen]'); if (!b) return; e.stopImmediatePropagation(); if (b.getAttribute('aria-disabled') === 'true') return;
  vscode.postMessage({ type: 'tidy-open' }); const n = document.querySelector('[data-tidynote]'); if (n) n.hidden = false; });`;

module.exports = { read, clean, load, card, size, daysSince, absolute, deriveWeeks, css, clientJs, MAX_FILE, MAX_ROWS, OLD_DAYS, WRITER };
