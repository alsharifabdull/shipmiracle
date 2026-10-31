// G2 step 4: the read-only Tidy up card (UX addendum section 11, QA checklist T1-T15). Unit part (always runs): tidyx.clean() / card() / load() for every state and every row of the priority matrix, hostile files,
// the file reader (missing, oversized, symlink, FIFO), size and time wording, the strings block, the source rules. Browser part (skips without Chrome): placement, button, hostile page, accessibility, contrast
// (Dark+, Light+, High Contrast), 280 / 315 / 360 px. Screenshots are written with SHIPMIRACLE_SHOTS=1 to tests/fixtures/panel-v3-tidy/tidy-<state>-<theme>-<width>.png. Parity P-1540...
// Run: node tests/panel_v3_tidy_test.js
require('./shipmiracle_isolation').apply();
const fs = require('fs'), os = require('os'), path = require('path'), cp = require('child_process');
const EXT = path.join(__dirname, '..', 'vscode-ext', 'shipmiracle-panel');
const TX = require(path.join(EXT, 'tidyx.js')), STR = require(path.join(EXT, 'strings.js')).tidy;
const D = require('./panel_cdp');
const C = D.checker(), check = C.check;
const U = h => String.fromCharCode(parseInt(h, 16)), NB = U('a0'), BIDI = U('202e') + U('2066') + U('200f') + U('061c') + U('200b') + U('feff');
const GB = 2 ** 30, MB = 2 ** 20, THR = 2 * GB;
const NAMES = ['shipmiracle', 'home-hub', 'notes-app', 'zeta', 'alpha', 'beta'];

// ---- fixtures (the shape in the G2 plan, "Step 1"; built here, not by the engine)
const fx = NOW => {
  const tsAgo = (days, hh = 16, mm = 5) => { const d = new Date(NOW); d.setDate(d.getDate() - days); d.setHours(hh, mm, 0, 0); return d.getTime() / 1000; };
  const bytes = (free, decide) => { const a = Math.floor(free / 2), b = Math.floor(decide / 2); return { disposable: a, regenerable_idle: free - a, regenerable_in_use: b, review: decide - b }; };
  const scan = (wk, days, free, decide = 0, o = {}) => ({ ts: tsAgo(days), iso_week: '2026-W' + wk, complete: true, projects_scanned: 6, projects_skipped: 0, duration_s: 12.5, bytes: bytes(free, decide), freeable: free, ...o });
  const pbytes = (free, decide) => { const a = Math.floor(free / 2); return { disposable: a, regenerable: free - a, review: decide, never: 7 }; };      // the ENGINE's project row shape: {disposable, regenerable, review, never} + freeable
  const proj = (name, free, decide, o = {}) => ({ name, partial: false, git: true, idle_days: 30, counts: { disposable: 1, regenerable: 1, review: 1, never: 0 }, bytes: pbytes(free, decide), freeable: free, ...o });
  const refOver = scans => { const seen = new Set(); let k = 0; for (const s of scans.slice().sort((a, b) => b.ts - a.ts)) { if (!s.complete || seen.has(s.iso_week)) continue; seen.add(s.iso_week); if (s.bytes.disposable + s.bytes.regenerable_idle > THR) k++; else break; } return k; };
  const doc = (scans, projects, cond = {}) => { const k = refOver(scans); return { v: 1, ts: Math.floor(NOW / 1000), writer: 'shipmiracle-tidy', data: { schema: 1, scans, projects, condition: { threshold_bytes: THR, weeks_needed: 4, weeks_over: k, met: k >= 4, met_since: null, ...cond } } }; };
  const R = Math.round;
  const mkP3 = () => [proj('shipmiracle', R(2.1 * GB), 600 * MB), proj('home-hub', 900 * MB, 400 * MB), proj('notes-app', 400 * MB, 0), proj('zeta', 100 * MB, 0), proj('alpha', 0, 0)];
  const found = (o = {}) => doc([scan(43, 3, R(3.4 * GB), R(1.1 * GB), o.s0), scan(42, 10, R(2.5 * GB), 0), scan(41, 17, GB, 0)], o.projects || mkP3());   // 2 weeks over
  const met = () => doc([scan(43, 3, 3 * GB, GB), scan(42, 10, 3 * GB, 0), scan(41, 17, R(2.5 * GB), 0), scan(40, 24, R(2.2 * GB), 0)], mkP3());
  const one = (free, decide, o = {}, projects = []) => doc([scan(43, o.days == null ? 1 : o.days, free, decide, { projects_scanned: o.scanned == null ? 6 : o.scanned, complete: o.complete !== false })], projects);
  return { tsAgo, bytes, scan, proj, doc, found, met, one, get P3() { return mkP3(); }, refOver };
};
const FX = fx(new Date(2026, 9, 22, 12, 0, 0).getTime()), NOW = new Date(2026, 9, 22, 12, 0, 0).getTime();
const mdl = (doc, names = NAMES) => TX.clean(doc, names);
const html = (m, o = {}) => TX.card(m, { now: NOW, tool: true, ...o });
const vis = h => h.replace(/<[^>]*>/g, '').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, '&');
const parse = h => [...h.matchAll(/<(h3|p|li|button)((?:\s[^>]*)?)>([\s\S]*?)<\/\1>/g)].map(m => ({ tag: m[1], attrs: m[2], cls: (m[2].match(/class="([^"]*)"/) || [])[1] || '', text: vis(m[3]), hidden: /\shidden(\s|>|$)/.test(m[2] + '>') }));
const kindsOf = h => { const out = []; for (const x of parse(h)) {
  if (x.hidden) continue;
  if (x.tag === 'h3') out.push('h'); else if (x.tag === 'li') { if (out[out.length - 1] !== 'rows') out.push('rows'); } else if (x.tag === 'button') out.push('btn');
  else if (x.cls.includes('tds')) out.push('sum'); else if (x.cls.includes('tdmore')) out.push('more'); else if (x.cls.includes('tdw')) out.push(/ for \d+ weeks/.test(x.text) ? 'met' : 'weeks');
  else if (x.cls.includes('tdmeta')) out.push('meta'); else if (x.cls.includes('tdfoot')) out.push('foot'); else if (/days old/.test(x.text)) out.push('old'); else if (/too large/.test(x.text)) out.push('partial'); else out.push('?' + x.text.slice(0, 20));
} return out; };
const sumOf = h => (parse(h).find(x => x.cls.includes('tds')) || {}).text;
const E = (k, o = {}) => STR[k].replace(/\{(\w+)\}/g, (m, n) => o[n]);
const S3 = n => n + NB;

// ---- T4 sizes
{
  const T = [[0, '0' + NB + 'B'], [1, '1' + NB + 'B'], [1023, '1023' + NB + 'B'], [1024, '1' + NB + 'KB'], [1536, '1.5' + NB + 'KB'], [10239, '10' + NB + 'KB'], [1048575, '1' + NB + 'MB'], [1073741824, '1' + NB + 'GB'], [2147483648, '2' + NB + 'GB'],
    [2147483649, '2' + NB + 'GB'], [Math.floor(1023.6 * MB), '1' + NB + 'GB'], [2048 * GB, '2' + NB + 'TB'], [2 ** 53, '8192' + NB + 'TB'], [512, '512' + NB + 'B'], [340 * 1024, '340' + NB + 'KB'], [12 * MB, '12' + NB + 'MB'], [Math.round(2.1 * GB), '2.1' + NB + 'GB'], [Math.round(1.5 * GB), '1.5' + NB + 'GB'], [GB - 1, '1' + NB + 'GB']];
  const bad = T.filter(([n, s]) => TX.size(n) !== s).map(([n, s]) => [n, s, TX.size(n)]);
  check('P-1540 T4 size formatting table (0..2^53: units, one decimal below 10, whole from 10, ".0" dropped, 1023.6 MB -> 1 GB, NBSP between number and unit)', bad.length === 0, JSON.stringify(bad));
  check('P-1540 T4 sizes use no KiB / lower case / thousands separator, only Western digits', !T.some(([n]) => /KiB|[a-z]B$|,|[\u0660-\u0669]/.test(TX.size(n))));
}
// ---- T15 strings equal the spec block
{
  const spec = path.join(__dirname, '..', 'docs', 'plans', '2026-10-21-panel-v3-ux-addendum.md');
  if (fs.existsSync(spec)) {
    const txt = fs.readFileSync(spec, 'utf8'), a = txt.indexOf('tidy: { heading'), b = txt.indexOf("foot:'Read-only: this card never moves or deletes anything.' }", a);
    let want = null; try { want = require('vm').runInNewContext('({' + txt.slice(a, b + 62) + '})', Object.create(null)).tidy; } catch (e) { want = null; }
    check('P-1541 T15 strings.js tidy group equals the spec block 11k key for key (' + (want ? Object.keys(want).length : 0) + ' keys)', !!want && JSON.stringify(want) === JSON.stringify(STR), want ? '' : 'spec block not parsed');
  } else check('P-1541 T15 strings.js tidy group has the 31 spec keys (spec file absent in this tree)', Object.keys(STR).length === 31);
  const src = fs.readFileSync(path.join(EXT, 'panel.js'), 'utf8');
  check('P-1541 T15 panel.js stays under 200 KB and holds only the call and the require (no card markup, no card CSS)', fs.statSync(path.join(EXT, 'panel.js')).size < 200000 && !/data-tidyopen|tdname|Show the full report/.test(src) && /TX\.card\(/.test(src) && /TX\.css/.test(src), fs.statSync(path.join(EXT, 'panel.js')).size);
  const all = fs.readFileSync(path.join(EXT, 'strings.js'), 'utf8');
  check('P-1541 T15 the tidy group appears once in strings.js', (all.match(/\n  tidy: \{/g) || []).length === 1);
}

// ---- T2 states and the priority matrix 11f
const WK = (k, n) => E('weeks', { size: S3('2') + 'GB'.replace(/^/, ''), k, n });
const THR_S = '2' + NB + 'GB';
{
  const o = (m, x = {}) => html(m, x);
  const none = TX.load(fs.mkdtempSync(path.join(os.tmpdir(), 'tidy-none-')), NAMES);
  let h = o(none);
  check('P-1542 T2 no report: summary + button + footer only, string tidy.none', JSON.stringify(kindsOf(h)) === '["h","sum","btn","foot"]' && sumOf(h) === STR.none, JSON.stringify(kindsOf(h)));
  h = o({ state: 'bad' });
  check('P-1542 T2 unreadable: summary + button + footer only, string tidy.unreadable', JSON.stringify(kindsOf(h)) === '["h","sum","btn","foot"]' && sumOf(h) === STR.unreadable);
  const row = (name, m, kinds, sum) => { const hh = o(m); check('P-1542 T2 matrix row: ' + name, JSON.stringify(kindsOf(hh)) === JSON.stringify(['h', ...kinds, 'btn', 'foot']) && (!sum || sumOf(hh) === sum), JSON.stringify(kindsOf(hh)) + ' ' + sumOf(hh)); return hh; };
  row('zero projects, not partial, not old', mdl(FX.one(0, 0, { scanned: 0, days: 1 })), ['sum', 'meta'], STR.noProjects);
  row('zero projects, old', mdl(FX.one(0, 0, { scanned: 0, days: 12 })), ['sum', 'old', 'meta'], STR.noProjects);
  row('empty, not partial, not old', mdl(FX.one(0, 0)), ['sum', 'meta'], STR.empty);
  row('empty, old', mdl(FX.one(0, 0, { days: 12 })), ['sum', 'old', 'meta'], STR.empty);
  row('empty, partial', mdl(FX.one(0, 0, { complete: false })), ['sum', 'partial', 'meta'], STR.emptyP);
  row('empty, partial, old', mdl(FX.one(0, 0, { complete: false, days: 12 })), ['sum', 'old', 'partial', 'meta'], STR.emptyP);
  const P2 = [FX.proj('shipmiracle', 600 * MB, 100 * MB)];
  row('found, not partial, not old (no counter at 0 weeks)', mdl(FX.one(600 * MB, 100 * MB, {}, P2)), ['sum', 'rows', 'meta'], E('sumBoth', { free: '600' + NB + 'MB', decide: '100' + NB + 'MB' }));
  row('found, not partial, old', mdl(FX.one(600 * MB, 100 * MB, { days: 12 }, P2)), ['sum', 'old', 'rows', 'meta']);
  row('found, partial, not old', mdl(FX.one(600 * MB, 100 * MB, { complete: false }, P2)), ['sum', 'partial', 'rows', 'meta'], E('sumBothP', { free: '600' + NB + 'MB', decide: '100' + NB + 'MB' }));
  row('found, partial, old', mdl(FX.one(600 * MB, 100 * MB, { complete: false, days: 12 }, P2)), ['sum', 'old', 'partial', 'rows', 'meta']);
  row('found with the weeks counter (2 of 4)', mdl(FX.found()), ['sum', 'rows', 'more', 'weeks', 'meta'], E('sumBoth', { free: '3.4' + NB + 'GB', decide: '1.1' + NB + 'GB' }));
  row('found with the condition met (sentence replaces the counter)', mdl(FX.met()), ['sum', 'rows', 'more', 'met', 'meta']);
  h = o(mdl(FX.found()));
  check('P-1542 T2 summary variants: free only, decide only', sumOf(o(mdl(FX.one(600 * MB, 0, {}, [FX.proj('alpha', 600 * MB, 0)])))) === E('sumFree', { free: '600' + NB + 'MB' }) && sumOf(o(mdl(FX.one(0, 5 * MB, {}, [FX.proj('alpha', 0, 5 * MB)])))) === E('sumDecide', { decide: '5' + NB + 'MB' })
    && sumOf(o(mdl(FX.one(600 * MB, 0, { complete: false }, [FX.proj('alpha', 600 * MB, 0)])))) === E('sumFreeP', { free: '600' + NB + 'MB' }) && sumOf(o(mdl(FX.one(0, 5 * MB, { complete: false }, [FX.proj('alpha', 0, 5 * MB)])))) === E('sumDecideP', { decide: '5' + NB + 'MB' }));
  const rows = parse(h).filter(x => x.tag === 'li').map(x => x.text);
  check('P-1542 T2 the three rows read like the mockup (name, "Could free", "You decide"; a zero line is left out)', rows.length === 3 && rows[0] === 'shipmiracle' + E('rowFree', { size: '2.1' + NB + 'GB' }) + E('rowDecide', { size: '600' + NB + 'MB' }) && rows[2] === 'notes-app' + E('rowFree', { size: '400' + NB + 'MB' }), JSON.stringify(rows));
  check('P-1542 T2 weeks counter reads "Over 2 GB: 2 of 4 weeks in a row"; "and 1 more project."; meta "Checked 3 days ago"', parse(h).some(x => x.text === 'Over ' + THR_S + ': 2 of 4 weeks in a row') && parse(h).some(x => x.text === STR.more1) && parse(h).some(x => x.text === 'Checked 3 days ago'), JSON.stringify(parse(h).map(x => x.text)));
  const hm = o(mdl(FX.met()));
  check('P-1542 T2 met sentence is the spec sentence and the counter is not shown with it', parse(hm).some(x => x.text === E('met', { size: THR_S, n: 4 })) && !parse(hm).some(x => /of 4 weeks/.test(x.text)));
  // partial listed project only: plain summary, P row, partial note
  const pp = mdl(FX.one(600 * MB, 100 * MB, {}, [FX.proj('shipmiracle', 600 * MB, 100 * MB, { partial: true })])), hp = o(pp);
  check('P-1542 T2 a listed project that is itself partial: plain summary, "at least" row strings, one partial note', sumOf(hp) === E('sumBoth', { free: '600' + NB + 'MB', decide: '100' + NB + 'MB' }) && parse(hp).filter(x => /too large/.test(x.text)).length === 1 && parse(hp).some(x => x.tag === 'li' && /at least/.test(x.text)), JSON.stringify(parse(hp).map(x => x.text)));
  // internal words never on screen (visible text only; the tooltip is an attribute)
  const states = [none, { state: 'bad' }, mdl(FX.found()), mdl(FX.met()), mdl(FX.one(0, 0)), mdl(FX.one(0, 0, { complete: false })), mdl(FX.one(0, 0, { scanned: 0 })), mdl(FX.one(600 * MB, 100 * MB, { complete: false, days: 12 }, P2))];
  const words = /\bscan|tidy\.json|ISO week|quarantine|condition|\bpartial\b|path_rel|freed safely|<|>/i;
  check('P-1542 T2 no internal word (scan, tidy.json, ISO week, quarantine, condition, partial) in any visible text, in every state', states.every(m => !words.test(vis(html(m)).replace(/Types shipm tidy/, ''))), states.map(m => vis(html(m)).match(words)));
}
// ---- T3 rows
{
  const mk = n => FX.doc([FX.scan(43, 1, 10 * GB, 0)], Array.from({ length: n }, (_, i) => FX.proj('p' + i, (i + 1) * MB, 0)));
  const names = Array.from({ length: 120 }, (_, i) => 'p' + i);
  for (const n of [0, 1, 2, 3, 4, 100]) {
    const m = TX.clean(mk(n), names), h = html(m), li = parse(h).filter(x => x.tag === 'li'), more = parse(h).find(x => x.cls.includes('tdmore'));
    check(`P-1543 T3 ${n} projects: ${Math.min(n, 3)} rows, ${n > 3 ? 'text "and ' + (n - 3) + ' more"' : 'no "more" line'}`, li.length === Math.min(n, 3) && (n > 3 ? more && more.text === (n - 3 === 1 ? STR.more1 : E('moreN', { n: n - 3 })) : !more), JSON.stringify({ rows: li.length, more: more && more.text }));
    if (n >= 3) check(`P-1543 T3 (${n}) rows ordered by "could free" largest first`, li[0].text.startsWith('p' + (n - 1)) && li[1].text.startsWith('p' + (n - 2)), li.map(x => x.text.slice(0, 5)).join());
  }
  const ties = TX.clean(FX.doc([FX.scan(43, 1, 10 * GB, 0)], [FX.proj('zeta', MB, 0), FX.proj('alpha', MB, 0), FX.proj('beta', MB, 0), FX.proj('home-hub', MB, 0)]), NAMES);
  check('P-1543 T3 ties are ordered by name', parse(html(ties)).filter(x => x.tag === 'li').map(x => x.text.split('Could')[0]).join() === 'alpha,beta,home-hub');
  const mix = TX.clean(FX.doc([FX.scan(43, 1, GB, GB)], [FX.proj('alpha', 0, 0), FX.proj('beta', 0, MB), FX.proj('zeta', MB, 0)]), NAMES), li = parse(html(mix)).filter(x => x.tag === 'li').map(x => x.text);
  check('P-1543 T3 a project with both sizes zero is never listed; a project with only "decide" shows one line', li.length === 2 && li[1] === 'beta' + E('rowDecide', { size: '1' + NB + 'MB' }), JSON.stringify(li));
}
// ---- T5 time wording
{
  const when = days => { const h = html(mdl(FX.one(MB, 0, { days }, [FX.proj('alpha', MB, 0)]))); return parse(h).find(x => x.cls.includes('tdmeta')).text; };
  check('P-1544 T5 the same day "today", the day before "yesterday", 2..30 days "N days ago" (never "1 days")', when(0) === 'Checked today' && when(1) === 'Checked yesterday' && when(2) === 'Checked 2 days ago' && when(30) === 'Checked 30 days ago' && ![...Array(31).keys()].some(d => /\b1 days/.test(when(d))), [when(0), when(1), when(2)].join('|'));
  const fut = mdl(FX.doc([{ ...FX.scan(43, 0, MB, 0), ts: NOW / 1000 + 5 * 86400 }], [FX.proj('alpha', MB, 0)]));
  check('P-1544 T5 a report dated in the future reads "today"', parse(html(fut)).find(x => x.cls.includes('tdmeta')).text === 'Checked today');
  const old = d => parse(html(mdl(FX.one(MB, 0, { days: d }, [FX.proj('alpha', MB, 0)])))).some(x => /days old/.test(x.text));
  check('P-1544 T5 the old note shows from 10 days, not at 9 days; "This report is 12 days old."', !old(9) && old(10) && parse(html(mdl(FX.one(MB, 0, { days: 12 }, [FX.proj('alpha', MB, 0)])))).some(x => x.text === 'This report is 12 days old. Sizes may have changed.'));
  const h = html(mdl(FX.one(MB, 0, { days: 3 }, [FX.proj('alpha', MB, 0)]))), tm = h.match(/<time datetime="([^"]*)" title="([^"]*)">/);
  check('P-1544 T5 <time> carries an ISO datetime and a 24 h absolute title like "19 Oct 2026, 16:05" with Western digits', tm && /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$/.test(tm[1]) && tm[2] === '19 Oct 2026, 16:05', tm && tm.slice(1).join(' | '));
  const walk = m => parse(html(m)).some(x => /days old/.test(x.text)), cm = mdl(FX.met());
  const oldMet = mdl(FX.doc([FX.scan(43, 12, 3 * GB, 0), FX.scan(42, 19, 3 * GB, 0), FX.scan(41, 26, 3 * GB, 0), FX.scan(40, 33, 3 * GB, 0)], FX.P3));
  check('P-1544 T5 an old report still shows its data and the met sentence, together with the old note', walk(oldMet) && parse(html(oldMet)).some(x => /for 4 weeks in a row/.test(x.text)) && parse(html(oldMet)).some(x => x.tag === 'li'));
}
// ---- T6 the weeks counter and the re-derived condition
{
  const weeksFor = (ks) => { const free = i => (ks[i] || 0) * GB; const sc = ks.map((g, i) => FX.scan(43 - i, 3 + 7 * i, g * GB, 0)); return mdl(FX.doc(sc, [FX.proj('alpha', ks[0] * GB, 0)])); };
  const shown = m => parse(html(m)).filter(x => x.cls.includes('tdw')).map(x => x.text);
  check('P-1545 T6 counter hidden at 0 (lower newest week), shown for 1, 2, 3; sentence at 4; never both', shown(weeksFor([1])).length === 0 && shown(weeksFor([3, 1]))[0] === 'Over ' + THR_S + ': 1 of 4 weeks in a row' && shown(weeksFor([3, 3, 1]))[0].includes('2 of 4')
    && shown(weeksFor([3, 3, 3, 1]))[0].includes('3 of 4') && shown(weeksFor([3, 3, 3, 3]))[0].includes('for 4 weeks in a row') && shown(weeksFor([3, 3, 3, 3])).length === 1, JSON.stringify([1, 2, 3, 4].map(n => shown(weeksFor(Array(n).fill(3).concat([1]))))));
  const ex = mdl(FX.doc([FX.scan(43, 3, THR, 0), FX.scan(42, 10, 3 * GB, 0)], [FX.proj('alpha', THR, 0)]));
  check('P-1545 T6 exactly 2 GB is not "more than": the run is 0', ex.over === 0 && shown(ex).length === 0, ex.over);
  const miss = mdl(FX.doc([FX.scan(43, 3, 3 * GB, 0), FX.scan(41, 17, 3 * GB, 0), FX.scan(40, 24, 3 * GB, 0), FX.scan(38, 38, 3 * GB, 0)], FX.P3));
  check('P-1545 T6 a missing week neither counts nor resets (weeks 43, 41, 40, 38 are four weeks in a row)', miss.over === 4 && miss.met === true, miss.over);
  const part = mdl(FX.doc([FX.scan(43, 3, 3 * GB, 0), FX.scan(42, 10, 0, 0, { complete: false }), FX.scan(41, 17, 3 * GB, 0)], FX.P3));
  check('P-1545 T6 a partial week neither counts nor resets', part.over === 2, part.over);
  const dup = mdl(FX.doc([FX.scan(43, 3, 3 * GB, 0), FX.scan(43, 4, 3 * GB, 0), FX.scan(42, 10, 3 * GB, 0)], FX.P3));
  check('P-1545 T6 two complete scans in one week make one entry', dup.over === 2, dup.over);
  // forged conditions
  const forged = (o) => { const d = FX.found(); Object.assign(d.data.condition, o); return TX.clean(d, NAMES); };
  check('P-1545 T6 a forged "met:true" with fewer than 4 qualifying weeks -> unreadable', forged({ met: true }).state === 'bad' && forged({ met: true, weeks_over: 4 }).state === 'bad');
  const m4 = FX.met(); m4.data.condition.met = false;
  check('P-1545 T6 a forged "met:false" with 4 qualifying weeks -> unreadable, and only the unreadable text is drawn', TX.clean(m4, NAMES).state === 'bad' && kindsOf(html(TX.clean(m4, NAMES))).join() === 'h,sum,btn,foot' && sumOf(html(TX.clean(m4, NAMES))) === STR.unreadable);
  check('P-1545 T6 a stored weeks_over that differs from the history -> unreadable', forged({ weeks_over: 3 }).state === 'bad' && forged({ weeks_over: 0 }).state === 'bad' && forged({ weeks_over: -1 }).state === 'bad' && forged({ weeks_over: '2' }).state === 'bad');
  check('P-1545 T6 a bad threshold or needed count -> unreadable', forged({ threshold_bytes: 0 }).state === 'bad' && forged({ threshold_bytes: 'x' }).state === 'bad' && forged({ weeks_needed: 1 }).state === 'bad' && forged({ weeks_needed: 99 }).state === 'bad' && forged({ met: 'false' }).state === 'bad');
  const noCond = FX.found(); delete noCond.data.condition;
  check('P-1545 T6 a missing condition -> unreadable', TX.clean(noCond, NAMES).state === 'bad');
}
// ---- T8 hostile data
{
  const J = JSON.stringify, good = () => FX.found();
  const bad = (name, mut) => { const d = good(); mut(d); const r = TX.clean(d, NAMES); check('P-1546 T8 hostile: ' + name + ' -> unreadable, nothing else drawn', r.state === 'bad' && kindsOf(html(r)).join() === 'h,sum,btn,foot', J(r).slice(0, 80)); };
  const BADN = [-1, NaN, Infinity, -Infinity, 2 ** 53 + 2, 2 ** 60, 1e300, 1.5, '5', '1e3', null, true, [], {}, undefined];
  for (const v of BADN) {
    for (const k of ['disposable', 'regenerable_idle', 'regenerable_in_use', 'review']) { const d1 = good(); d1.data.scans[0].bytes[k] = v; if (TX.clean(d1, NAMES).state !== 'bad') check('P-1546 T8 bad number ' + String(v) + ' in scan bytes.' + k + ' is refused', false); }
    for (const k of ['disposable', 'regenerable', 'review', 'never']) { const d2 = good(); d2.data.projects[0].bytes[k] = v; if (TX.clean(d2, NAMES).state !== 'bad') check('P-1546 T8 bad number ' + String(v) + ' in project bytes.' + k + ' is refused', false); }
    const d3 = good(); d3.data.projects[0].freeable = v; if (TX.clean(d3, NAMES).state !== 'bad') check('P-1546 T8 bad number ' + String(v) + ' in a project freeable is refused', false);
  }
  { const d = good(); d.data.projects[0].freeable = d.data.projects[0].bytes.disposable + d.data.projects[0].bytes.regenerable + 1; check('P-1546 T8 a project freeable above disposable + regenerable is refused', TX.clean(d, NAMES).state === 'bad'); }
  { const d = good(); d.data.projects[0].bytes = { disposable: 1, regenerable_idle: 1, regenerable_in_use: 0, review: 1 }; check('P-1546 T8 a project row in the scan-level byte shape (not the engine project shape) is refused', TX.clean(d, NAMES).state === 'bad'); }
  { const d = good(); d.data.projects[0].bytes.review = 5; d.data.projects[0].freeable = 3; d.data.projects[0].bytes.disposable = 3; d.data.projects[0].bytes.regenerable = 0; const r = TX.clean(d, NAMES).rows.find(x => x.name === 'shipmiracle'); check('P-1546 T8 a project shows the engine freeable as "could free" and bytes.review as "you decide" (idleness is not guessed)', r && r.free === 3 && r.decide === 5, JSON.stringify(r)); }
  check('P-1546 T8 negative / NaN / Infinity / 2^53+2 / 2^60 / float / string / null / object values in scan bytes (4 keys), project bytes (4 keys) and freeable (15 values) are all refused', true);
  bad('sum of the four sizes over 2^53', d => { d.data.scans[0].bytes = { disposable: 2 ** 53, regenerable_idle: 2 ** 53, regenerable_in_use: 0, review: 0 }; });
  bad('a missing size key', d => { delete d.data.scans[0].bytes.review; });
  bad('wrong version', d => { d.v = 2; }); bad('wrong writer', d => { d.writer = 'shipmiracle-guard'; }); bad('wrong schema', d => { d.data.schema = 2; });
  bad('scans not an array', d => { d.data.scans = {}; }); bad('9 scans', d => { d.data.scans = Array(9).fill(d.data.scans[0]); }); bad('101 projects', d => { d.data.projects = Array(101).fill(d.data.projects[0]); });
  bad('a scan that is not an object', d => { d.data.scans[1] = 5; }); bad('iso_week with markup', d => { d.data.scans[0].iso_week = '<img src=x>'; }); bad('complete as a string', d => { d.data.scans[0].complete = 'yes'; });
  bad('ts as a string / 0 / NaN / year 3000', d => { d.data.scans[0].ts = '1'; }); bad('ts NaN', d => { d.data.scans[0].ts = NaN; }); bad('ts in the year 3000', d => { d.data.scans[0].ts = 32503680000; });
  bad('projects_scanned negative', d => { d.data.scans[0].projects_scanned = -3; }); bad('partial as a string on a project', d => { d.data.projects[0].partial = 'false'; });
  for (const x of [null, undefined, 5, 'x', [], true]) check('P-1546 T8 a top level that is not an object (' + J(x) + ') -> unreadable', TX.clean(x, NAMES).state === 'bad');
  // injected fields and markup are ignored / escaped
  const d = good(); d.evil = '<script>alert(9)</script>'; d.data.evil = { path_rel: '/etc/passwd' }; d.data.scans[0].path_rel = '/Users/x/.ssh/id_rsa'; d.data.scans[0].command = 'rm -rf ~';
  for (const p of d.data.projects) Object.assign(p, { path_rel: '/Users/x/secret.txt', command: 'rm -rf ~', why: '<img src=x onerror=alert(1)>', files: ['/etc/passwd'] }); d.data.condition.command = 'rm -rf /';
  const clean0 = TX.clean(good(), NAMES), clean1 = TX.clean(d, NAMES), h1 = html(clean1);
  check('P-1546 T8 unknown fields (path_rel, command, why, files, evil) are ignored: the model equals the one without them, the page shows none of them', J(clean0) === J(clean1) && !/passwd|ssh|rm -rf|onerror|alert|secret|<script/.test(h1 + J(clean1)));
  const reg = ['<b>x</b>&"\'' + BIDI + 'y', 'a'.repeat(200), 'ok-name', ...NAMES];
  const hd = good(); hd.data.projects = [FX.proj(reg[0], 3 * GB, 0), FX.proj(reg[1], 2 * GB, MB), FX.proj('ok-name', GB, 0)]; const hm = TX.clean(hd, reg), hh = html(hm);
  check('P-1546 T8 a registry name with markup, quotes and bidi controls is escaped (no element, no bidi char on the page), a 200 character name is kept whole (the CSS clamps it to 2 lines with an ellipsis) and carries the same title', !/<b>|<img/.test(hh) && hh.includes('&lt;b&gt;x&lt;/b&gt;') && !new RegExp('[' + BIDI + ']').test(hh) && parse(hh).filter(x => x.tag === 'li')[1].text.startsWith('a'.repeat(200) + 'Could') && !hh.includes('a'.repeat(201)), hh.slice(0, 300));
  check('P-1546 T8 every name carries dir="auto"', (hh.match(/class="tdname" dir="auto"/g) || []).length === 3);
  // names not in the registry are dropped (the totals still come from the report)
  const dn = good(); dn.data.projects.push(FX.proj('ghost-project', 9 * GB, 0), FX.proj('../etc', 9 * GB, 0), FX.proj('', 9 * GB, 0)); const mn = TX.clean(dn, NAMES);
  check('P-1546 T8 projects whose name is not in the registry (ghost, "../etc", "") are dropped; the same name twice shows once', mn.rows.length === 4 && !J(mn).includes('ghost') && !J(mn).includes('..') && TX.clean({ ...good(), data: { ...good().data, projects: [FX.proj('alpha', MB, 0), FX.proj('alpha', 9 * GB, 0)] } }, NAMES).rows.length === 1);
  check('P-1546 T8 with an empty or missing registry nothing is listed and nothing breaks', TX.clean(good(), []).rows.length === 0 && TX.clean(good(), undefined).rows.length === 0 && TX.clean(good(), new Set(NAMES)).rows.length === 4);
  // 10^6 projects (in memory) and as a file
  // load-tolerant (26 Oct 2026): build + clean <= max(500 ms, K x baseline); baseline = building the same 10^6 rows alone (about 110-140 ms on a quiet Mac, so K = 4), measured right before and after
  const TM = require('./shipmiracle_timing'), build = () => Array.from({ length: 1e6 }, (_, i) => FX.proj('p' + i, 1, 0));
  let bigState = null;
  const whole = () => TM.timed(() => { const big = good(); big.data.projects = build(); bigState = TX.clean(big, NAMES).state; });
  const t8 = TM.robustAround(whole, () => TM.timed(build), 500, 4, 5);
  console.log('INFO T8 10^6 projects: ' + t8.report);
  check('P-1546 T8 10^6 projects in memory -> unreadable at once (<= max(500 ms, 4 x baseline)): ' + t8.report, bigState === 'bad' && t8.ok, t8.report);
  check('P-1546 T8 mutant: the same work slowed by a busy wait (4 x the allowed time) is still noticed by the relative check', TM.mutantNoticed(whole, () => TM.timed(build), 500, 4));
  // the card re-checks a model it is handed
  for (const m of [null, 5, 'ok', { state: 'ok' }, { state: 'ok', ts: NaN, free: 1, decide: 1, scanned: 1, rows: [], over: 0, needed: 4, threshold: 1, met: false }, { state: 'ok', ts: 1, free: -1, decide: 1, scanned: 1, rows: [], over: 0, needed: 4, threshold: 1, met: false }, { state: 'zzz' }, []]) {
    check('P-1546 T8 card() given a model of an unknown shape (' + J(m) + ') draws "could not read" and nothing else', kindsOf(html(m)).join() === 'h,sum,btn,foot' && sumOf(html(m)) === STR.unreadable);
  }
  check('P-1546 T8 card() of older data (undefined) draws nothing', TX.card(undefined, {}) === '');
  const rowsBad = { ...mdl(FX.found()), rows: [{ name: '<img src=x onerror=alert(1)>', full: 'x', free: 5, decide: 0, partial: false }, { name: 5, free: 1, decide: 1 }, null, { name: 'ok', free: NaN, decide: 1 }] };
  check('P-1546 T8 card() escapes a row name even if a model with raw markup is handed in, and drops rows of a bad shape', !/<img/.test(html(rowsBad)) && parse(html(rowsBad)).filter(x => x.tag === 'li').length === 1);
}
// ---- T9 the reader
{
  const mkState = () => { const s = fs.mkdtempSync(path.join(os.tmpdir(), 'tidy-st-')); fs.mkdirSync(path.join(s, 'v1'), { recursive: true }); return s; };
  const f = s => path.join(s, 'v1', 'tidy.json'), ok = () => JSON.stringify(FX.found());
  let s = mkState();
  check('P-1547 T9 a missing file is "no report yet", not an error', TX.load(s, NAMES).state === 'none' && TX.read(s).status === 'none');
  fs.writeFileSync(f(s), ok()); check('P-1547 T9 a good file reads', TX.load(s, NAMES).state === 'ok');
  fs.writeFileSync(f(s), ok() + ' '.repeat(65 * 1024)); check('P-1547 T9 a file over 64 KB is "could not be read"', TX.load(s, NAMES).state === 'bad');
  fs.writeFileSync(f(s), ok().slice(0, 50)); check('P-1547 T9 broken JSON is "could not be read"', TX.load(s, NAMES).state === 'bad');
  fs.writeFileSync(f(s), ''); check('P-1547 T9 an empty file is "could not be read"', TX.load(s, NAMES).state === 'bad');
  fs.unlinkSync(f(s)); const other = path.join(s, 'real.json'); fs.writeFileSync(other, ok()); fs.symlinkSync(other, f(s));
  check('P-1547 T9 a symlink (even to a valid file) is refused: "could not be read"', TX.load(s, NAMES).state === 'bad');
  fs.unlinkSync(f(s)); fs.symlinkSync(path.join(s, 'nowhere'), f(s)); check('P-1547 T9 a dangling symlink is refused', TX.load(s, NAMES).state === 'bad');
  fs.unlinkSync(f(s)); fs.mkdirSync(f(s)); check('P-1547 T9 a directory named tidy.json is refused', TX.load(s, NAMES).state === 'bad'); fs.rmdirSync(f(s));
  let fifo = true; try { cp.execFileSync('mkfifo', [f(s)]); } catch (e) { fifo = false; }
  if (fifo) { const t0 = Date.now(); const r = TX.load(s, NAMES); check('P-1547 T9 a FIFO is refused at once without blocking (' + (Date.now() - t0) + ' ms)', r.state === 'bad' && Date.now() - t0 < 1500); fs.unlinkSync(f(s)); } else check('P-1547 T9 a FIFO is refused (mkfifo missing: NOT TESTED)', true);
  const huge = FX.found(); huge.data.projects = Array.from({ length: 1e6 }, (_, i) => FX.proj('p' + i, 1, 0)); fs.writeFileSync(f(s), JSON.stringify(huge).slice(0, 70 * 1024) + '"]}}');
  check('P-1547 T9 a file with 10^6 projects (oversized) is refused before parsing', TX.load(s, NAMES).state === 'bad');
  fs.rmSync(s, { recursive: true, force: true });
  const src = fs.readFileSync(path.join(EXT, 'tidyx.js'), 'utf8');
  check('P-1547 T9 the reader uses the capped, no-follow, non-blocking reader of reports.js', /readCapped\(f, MAX_FILE, false\)/.test(src) && MAX_OK());
  function MAX_OK() { return TX.MAX_FILE === 64 * 1024; }
  const data = fs.readFileSync(path.join(EXT, 'data.js'), 'utf8');
  check('P-1547 T9 data.js reads the report with the registry names, in the one collect() result', /tidy: TIDYX\.load\(STATE, names\)/.test(data));
}

// ---- integration with the REAL engine writer: tests/tidy_engine_fixture.py runs shipmiracle.tidyweekly.run over fake scans and prints the tidy.json it wrote and its own condition.
// For every history the card state must equal the engine's weeks_over / met exactly. (To regenerate by hand: echo '{...}' | python3 tests/tidy_engine_fixture.py)
{
  const dayStr = (y, m, d) => y + '-' + String(m).padStart(2, '0') + '-' + String(d).padStart(2, '0');
  const mon = i => { const d = new Date(Date.UTC(2026, 7, 31 + 7 * i, 12)); return dayStr(d.getUTCFullYear(), d.getUTCMonth() + 1, d.getUTCDate()); };       // 2026-W36 is i = 0
  const full = g => ({ projects: [{ name: 'alpha', disposable: g, review: 5 }] }), skip = () => ({ projects: [{ name: 'alpha', disposable: 0 }], skip: true });
  const part = () => ({ projects: [{ name: 'alpha', disposable: 0, partial: true }] });
  const weekly = list => list.map((g, i) => ({ date: mon(i), ...(g === 'P' ? part() : g === 'S' ? skip() : full(g)) }));
  const G3 = 3 * GB, G1 = GB;
  const SC = {
    w1: weekly([G3]), w3: weekly([G3, G3, G3]), w4: weekly([G3, G3, G3, G3]), w5: weekly(Array(5).fill(G3)), w8: weekly(Array(8).fill(G3)), w9: weekly(Array(9).fill(G3)),
    lowerWeek: weekly([G3, G3, G1, G3, G3]), partialMid: weekly([G3, G3, 'P', G3, G3]), partialNewest: weekly([G3, G3, G3, G3, 'P']), partialOnly: weekly(['P', 'P']), skippedNewest: weekly([G3, G3, G3, G3, 'S']),
    twoInOneWeek: [{ date: mon(0), ...full(G3) }, { date: dayStr(2026, 9, 2), ...full(G3) }, { date: mon(1), ...full(G3) }, { date: mon(2), ...full(G3) }],
    weekGap: [{ date: mon(7), ...full(G3) }, { date: mon(5), ...full(G3) }, { date: mon(4), ...full(G3) }, { date: mon(2), ...full(G3) }].sort((a, b) => (a.date < b.date ? -1 : 1)),
    yearBoundary: [{ date: '2025-12-15', ...full(G3) }, { date: '2025-12-22', ...full(G3) }, { date: '2025-12-29', ...full(G3) }, { date: '2026-01-05', ...full(G3) }],
    idleProject: [{ date: mon(0), projects: [{ name: 'alpha', disposable: GB, regenerable: 2 * GB, review: 5, idle: 3 }, { name: 'zeta', disposable: GB, regenerable: 2 * GB, review: 0, idle: 40 }] }],
    metThenLower: weekly([G3, G3, G3, G3, G1]), exact2GiB: weekly(Array(4).fill(2 * GB)), plus1: weekly(Array(4).fill(2 * GB + 1)), emptyScan: [{ date: mon(0), projects: [] }], emptyAfterMet: weekly([G3, G3, G3, G3]).concat([{ date: mon(4), projects: [] }])
  };
  let eng = null;
  try { eng = JSON.parse(cp.execFileSync('python3', [path.join(__dirname, 'tidy_engine_fixture.py')], { input: JSON.stringify(SC), env: process.env, maxBuffer: 1 << 26, timeout: 120000 }).toString()); } catch (e) { check('P-1553 integration: the real engine writer ran (tests/tidy_engine_fixture.py)', false, String(e.stderr || e)); }
  if (eng) {
    const hasSchema = Object.values(eng).every(x => x.has_schema);
    check('P-1553 integration: the real engine writes `schema: 1` in the data block (the plan: data = {schema:1, scans, projects, condition})', hasSchema, hasSchema ? '' : 'NOT written by this engine build: the harness adds schema:1 so the rest can still be compared');
    for (const [name, r] of Object.entries(eng)) {
      const doc = JSON.parse(JSON.stringify(r.doc)); if (doc.data.schema === undefined) doc.data.schema = 1;
      const m = TX.clean(doc, ['alpha']), c = r.condition, h = html(m), t = parse(h).map(x => x.text);
      const scans = doc.data.scans.length;
      const okState = m.state === 'ok' && m.over === c.weeks_over && m.met === c.met && doc.data.condition.weeks_over === c.weeks_over;
      const counter = c.met ? t.some(x => /for 4 weeks in a row/.test(x)) && !t.some(x => /of 4 weeks/.test(x)) : (c.weeks_over >= 1 && c.weeks_over < 4 ? t.includes('Over ' + THR_S + ': ' + c.weeks_over + ' of 4 weeks in a row') : !t.some(x => /weeks in a row/.test(x)));
      check(`P-1553 integration [${name}]: engine weeks_over=${c.weeks_over} met=${c.met} (${scans} scans stored) == the card (${m.state} over=${m.over} met=${m.met}); the right counter or sentence, not "could not read"`, okState && counter && !t.includes(STR.unreadable), JSON.stringify({ st: m.state, over: m.over, met: m.met, t: t.slice(0, 4) }));
    }
    check('P-1553 integration: the engine keeps 8 scans (9 weeks written) and the card still reads it', eng.w9.doc.data.scans.length === 8 && TX.clean({ ...eng.w9.doc, data: { schema: 1, ...eng.w9.doc.data } }, ['alpha']).over === 8);
    const row = TX.clean({ ...eng.w4.doc, data: { schema: 1, ...eng.w4.doc.data } }, ['alpha']).rows[0], er = eng.w4.doc.data.projects[0];
    check('P-1553 integration: a real engine project row (bytes {disposable, regenerable, review, never} + freeable) shows its own freeable as "could free" and bytes.review as "you decide"', row && row.free === er.freeable && row.decide === er.bytes.review && er.bytes.never === 7, JSON.stringify({ row, er }));
    { const m = TX.clean({ ...eng.idleProject.doc, data: { schema: 1, ...eng.idleProject.doc.data } }, ['alpha', 'zeta']), al = m.rows.find(x => x.name === 'alpha'), ze = m.rows.find(x => x.name === 'zeta');
      check('P-1553 integration: a project that is NOT idle (idle_days 3) shows only disposable as "could free" (the engine freeable), an idle one (40) adds its rebuildable part; the panel does not guess idleness', al && ze && al.free === GB && ze.free === 3 * GB && al.decide === 5, JSON.stringify({ al, ze })); }
    const dropped = TX.clean({ ...eng.w4.doc, data: { schema: 1, ...eng.w4.doc.data } }, ['other']);
    check('P-1553 integration: a project missing from the registry is dropped from a real file, the totals stay', dropped.state === 'ok' && dropped.rows.length === 0 && dropped.free > 0);
    // m4: newest scan partial with zero sizes while the older history is met
    const pn = TX.clean({ ...eng.partialNewest.doc, data: { schema: 1, ...eng.partialNewest.doc.data } }, ['alpha']), pt = parse(html(pn)).map(x => x.text);
    check('P-1554 m4 newest scan partial with zero sizes, older history met: "Nothing found in what could be measured." + the partial note + the met sentence + meta (the history is not hidden)', pt[1] === STR.emptyP && pt.includes(STR.partial) && pt.some(x => /for 4 weeks in a row/.test(x)) && pt.some(x => /^Checked /.test(x)) && !pt.some(x => x === STR.unreadable), JSON.stringify(pt));
    const sk = TX.clean({ ...eng.skippedNewest.doc, data: { schema: 1, ...eng.skippedNewest.doc.data } }, ['alpha']), st2 = parse(html(sk)).map(x => x.text);
    check('P-1554 m4 newest scan with every project skipped (zero scanned), older history met: "No projects were checked." and the met sentence', sk.state === 'ok' && st2[1] === STR.noProjects && st2.some(x => /for 4 weeks in a row/.test(x)), JSON.stringify(st2));
    const ea = TX.clean({ ...eng.emptyAfterMet.doc, data: { schema: 1, ...eng.emptyAfterMet.doc.data } }, ['alpha']);
    check('P-1554 m4 a complete empty scan after a met run resets the run: no sentence, "No projects were checked."', ea.over === 0 && !ea.met && parse(html(ea))[1].text === STR.noProjects);
  }
}

// ---- the 5 states the QA screenshot list names, as data for the browser part
if (!D.H.available()) { console.log(C.fails ? `\nFAILED: ${C.fails} of ${C.n}` : `\nALL PASS (${C.n}) (browser part skipped: no Chrome)`); process.exit(C.fails ? 1 : 0); }

const F = require('./panel_v3_fixtures'), F3 = require('./panel_v3_tab_fixtures');
const SHOTS = path.join(__dirname, 'fixtures', 'panel-v3-tidy'), WRITE = process.env.SHIPMIRACLE_SHOTS === '1';
if (WRITE) fs.mkdirSync(SHOTS, { recursive: true });
const FB = fx(Date.now());                                         // browser part: dates relative to the real clock, the page uses Date.now()
const HOST = ['<b>x</b>&"\'', 'منزل-ذكي-home', 'a-very-long-project-name-that-keeps-going-and-going-and-going', 'u'.repeat(60), 'ok'];
const hostile = () => TX.clean(FB.doc([FB.scan(43, 3, 3400 * MB, 1100 * MB), FB.scan(42, 10, 2500 * MB, 0), FB.scan(41, 17, GB, 0)], [
  FB.proj(HOST[0], 2100 * MB, 600 * MB), FB.proj(HOST[1], 900 * MB, 400 * MB), FB.proj(HOST[2], 300 * MB, 100 * MB, { partial: true }), FB.proj(HOST[3], 50 * MB, 0), FB.proj(HOST[4], 10 * MB, 0)]), HOST);
const MODELS = {
  found: () => TX.clean(FB.found(), NAMES), met: () => TX.clean(FB.met(), NAMES), hostile,
  none: () => ({ state: 'none' }), unreadable: () => ({ state: 'bad' }), empty: () => TX.clean(FB.one(0, 0), NAMES),
  partial: () => TX.clean(FB.one(600 * MB, 100 * MB, { complete: false }, [FB.proj('shipmiracle', 600 * MB, 100 * MB)]), NAMES),
  old: () => TX.clean(FB.one(600 * MB, 100 * MB, { days: 12 }, [FB.proj('shipmiracle', 600 * MB, 100 * MB)]), NAMES),
  weeks2: () => TX.clean(FB.found(), NAMES), disabled: () => TX.clean(FB.found(), NAMES), notice: () => TX.clean(FB.found(), NAMES)
};
const proj = () => [F.mk('alpha-app', 'software'), F.mk('beta-app', 'software', { state: 'working' })];
const DATA = (o = {}) => ({ projects: proj(), health: F3.HEALTH(), plan: { meters: [] }, tidy: MODELS.found(), tidyTool: true, ...o });
const WATCHDOG = setTimeout(() => { console.log('FAIL watchdog: the browser part did not finish in 300 s'); process.exit(1); }, 300000); WATCHDOG.unref();

(async () => {
  const S = await D.session({ size: '345,900' }); await S.cdp('Page.addScriptToEvaluateOnNewDocument', { source: 'window.__alerts = 0; window.alert = () => { window.__alerts++; };' });
  const load = async (data, theme = 'dark', w = 315) => { await S.load(S.file('td-' + theme + w, D.page(theme, data, D.THEMES[theme])), w, '?tab=health', 3000); await S.sleep(120); };
  const msgs = () => S.ev('JSON.stringify(window.__msgs)').then(JSON.parse).then(a => a.filter(x => x.type !== 'editing'));
  const Q = `document.querySelector('#pane-health .tdy')`;

  // T1 placement
  await load(DATA());
  check('P-1548 T1 the card is the LAST child of the Health pane, after "Automatic cleanup", and exists once in the whole page', await S.ev(`(() => { const p = document.getElementById('pane-health'); const last = p.lastElementChild; return last === ${Q} && document.querySelectorAll('.tdy').length === 1 && !!p.querySelector('.hclean') && p.querySelector('.hclean').compareDocumentPosition(last) & Node.DOCUMENT_POSITION_FOLLOWING; })()`));
  await load(DATA({ health: null }));
  check('P-1548 T1 also drawn when there is no host scan ("No scan yet."), still the last child', await S.ev(`(() => { const p = document.getElementById('pane-health'); return /No scan yet/.test(p.textContent) && p.lastElementChild === ${Q}; })()`));
  {
    const a = D.page('dark', DATA()), b = D.page('dark', DATA({ tidy: undefined }));
    const strip = a.replace(/<section class="hsec tdy"[\s\S]*?<\/section>/, '');
    check('P-1548 T1 no chip, badge, dot or count anywhere else: the page with a report equals the page without one except for the card itself (tabs, project cards, Health count byte-identical)', strip === b, '');
    const sec = a.match(/<section class="hsec tdy"[\s\S]*?<\/section>/)[0];
    check('P-1548 T1 no live region, no status class, no data-* beyond the one button, no aria-live / role=status in the card', !/aria-live|role="status"|okt|dangert|warnt|hamb|hred|class="[^"]*(?:ok|warn|danger)\b/.test(sec) && (sec.match(/data-[a-z]+/g) || []).sort().join() === 'data-tidynote,data-tidyopen');
  }
  // button
  await load(DATA());
  check('P-1549 T7 exactly one button in the card, one tab stop', await S.ev(`${Q}.querySelectorAll('button').length === 1 && ${Q}.querySelectorAll('a, input, select, textarea, [tabindex], summary').length === 0`));
  check('P-1549 T7 the notice is hidden before the click', await S.ev(`${Q}.querySelector('[data-tidynote]').hidden === true && ${Q}.querySelector('[data-tidynote]').getClientRects().length === 0`));
  await S.ev('window.__msgs.length = 0'); await S.ev(`${Q}.querySelector('button').click()`); await S.sleep(80);
  let m = await msgs();
  check('P-1549 T7 click posts exactly {type:"tidy-open"} and nothing else', m.length === 1 && JSON.stringify(m[0]) === '{"type":"tidy-open"}', JSON.stringify(m));
  check('P-1549 T7 after the click the notice "Typed the command in a terminal..." is visible, plain text (no live region)', await S.ev(`(() => { const n = ${Q}.querySelector('[data-tidynote]'); return !n.hidden && n.textContent.trim() === ${JSON.stringify(STR.typed)} && !n.closest('[aria-live]') && !n.getAttribute('role'); })()`));
  await S.ev('window.__msgs.length = 0'); await S.ev(`${Q}.querySelector('button').click()`); await S.sleep(60);
  check('P-1549 T7 a second click types it again (one more message)', (await msgs()).length === 1);
  await S.ev('window.__msgs.length = 0'); await S.ev(`${Q}.querySelectorAll('.tds, .tdname, .tdz, time, h3, .tdfoot').forEach(n => n.click())`); await S.sleep(60);
  check('P-1549 T7 clicking any text of the card posts nothing', (await msgs()).every(x => x.type !== 'tidy-open' && x.type !== 'cmd'), JSON.stringify(await msgs()));
  await load(DATA({ tidyTool: false }));
  check('P-1549 T7 shipm not installed: the button stays visible and focusable with aria-disabled and the reason as visible text', await S.ev(`(() => { const b = ${Q}.querySelector('button'); return b.getAttribute('aria-disabled') === 'true' && !b.disabled && b.tabIndex === 0 && ${Q}.textContent.includes(${JSON.stringify(STR.noTool)}) && ${Q}.querySelector('[data-tidynote]') === null; })()`));
  await S.ev('window.__msgs.length = 0'); await S.ev(`${Q}.querySelector('button').click()`); await S.sleep(60);
  check('P-1549 T7 ...and a click on the disabled button posts nothing', (await msgs()).length === 0);
  check('P-1549 m3 the disabled button has a non-colour cue too: a dashed border (also in High Contrast)', await S.ev(`getComputedStyle(${Q}.querySelector('button')).borderStyle === 'dashed'`));
  await load(DATA({ tidyTool: false }), 'hc'); check('P-1549 m3 ...in High Contrast as well', await S.ev(`getComputedStyle(${Q}.querySelector('button')).borderStyle === 'dashed'`));
  await load(DATA()); check('P-1549 m3 the enabled button is solid', await S.ev(`getComputedStyle(${Q}.querySelector('button')).borderStyle === 'solid'`));
  check('P-1549 m2 the button label uses the card ink (--tdink), the same colour as the summary', await S.ev(`getComputedStyle(${Q}.querySelector('button')).color === getComputedStyle(${Q}.querySelector('.tds')).color`));
  // keyboard
  await load(DATA());
  await S.ev(`(() => { const f = [...document.querySelectorAll('#pane-health button, #pane-health [tabindex], #pane-health summary')].filter(n => !${Q}.contains(n)); f[f.length - 1].focus(); })()`);
  await S.key('Tab', 'Tab', 9);
  let ring = await S.ev(`(() => { const b = document.activeElement, cs = getComputedStyle(b); return { onBtn: b === ${Q}.querySelector('button'), style: cs.outlineStyle, w: parseFloat(cs.outlineWidth), col: cs.outlineColor, fv: b.matches(':focus-visible') }; })()`);
  check('P-1550 T10 Tab from the control before it lands on the card button (the card has one tab stop) and shows a 2 px focus ring', ring.onBtn && ring.fv && ring.style === 'solid' && ring.w >= 2, JSON.stringify(ring));
  await S.key('Tab', 'Tab', 9);
  check('P-1550 T10 the next Tab leaves the card (no trap, no second stop)', await S.ev(`!${Q}.contains(document.activeElement)`));
  await S.ev(`${Q}.querySelector('button').focus()`); await S.ev('window.__msgs.length = 0'); await S.key('Enter', 'Enter', 13, '\r'); await S.sleep(60);
  const mEnter = (await msgs()).length; await S.ev('window.__msgs.length = 0'); await S.key(' ', 'Space', 32, ' '); await S.sleep(60);
  check('P-1550 T10 Enter and Space both activate the button (one message each)', mEnter === 1 && (await msgs()).length === 1, mEnter);

  // T10 structure + hostile page
  await load(DATA({ tidy: MODELS.hostile() }));
  const st = await S.ev(`(() => { const q = ${Q}; const h = q.querySelector('h3'); return { tag: q.tagName, labelled: q.getAttribute('aria-labelledby') === h.id && !!h.id, ul: q.querySelectorAll('ul > li').length, ulOnly: q.querySelectorAll('ul').length, time: !!q.querySelector('time[datetime][title]'), dirAuto: [...q.querySelectorAll('.tdname')].every(n => n.getAttribute('dir') === 'auto'), titles: [...q.querySelectorAll('.tdname')].every(n => n.title),
    live: q.querySelectorAll('[aria-live], [role=status], [role=alert]').length, bdi: [...q.querySelectorAll('bdi')].every(b => b.getAttribute('dir') === 'ltr'), imgs: q.querySelectorAll('img, svg, script, a, canvas').length, alerts: window.__alerts, order: [...q.children].map(n => n.tagName).join() }; })()`);
  check('P-1550 T10 section named by its h3, a real ul/li (3 rows), <time datetime title>, dir=auto + title on every name, sizes in <bdi dir=ltr>, no live region, no image / icon / link', st.tag === 'SECTION' && st.labelled && st.ul === 3 && st.ulOnly === 1 && st.time && st.dirAuto && st.titles && st.live === 0 && st.bdi && st.imgs === 0, JSON.stringify(st));
  await load(DATA({ tidy: TX.clean(FB.doc([FB.scan(43, 3, 3 * GB, 0)], [FB.proj('u'.repeat(200), 3 * GB, 0)]), ['u'.repeat(200)]) }));
  check('P-1550 m1 a name longer than two lines is clamped to two lines (the CSS shows the ellipsis) and keeps its full text in the title', await S.ev(`(() => { const n = [...${Q}.querySelectorAll('.tdname')].find(x => x.textContent.startsWith('uuuu')); const cs = getComputedStyle(n); return !!n && n.scrollHeight > n.clientHeight && n.clientHeight <= 2 * 17 + 1 && cs.webkitLineClamp === '2' && n.title === n.textContent && n.textContent.length === 200; })()`));
  await load(DATA({ tidy: MODELS.hostile() }));
  check('P-1546 T8 hostile card: markup in a registry name stayed text, no script ran, the name is visible as text', await S.ev(`window.__alerts === 0 && !${Q}.querySelector('b, img') && ${Q}.textContent.includes('<b>x</b>&"')`));
  check('P-1550 T10 reading order = visual order: h3, summary, partial note, list, more, weeks line, meta, button, notice, footer', st.order === 'H3,P,P,UL,P,P,P,BUTTON,P,P', st.order);
  const anim = await S.ev(`(() => { const out = []; ${Q}.querySelectorAll('*').forEach(n => { const cs = getComputedStyle(n); if (parseFloat(cs.transitionDuration) > 0 || parseFloat(cs.animationDuration) > 0) out.push(n.className); }); return out.concat(document.getAnimations().map(a => 'anim')); })()`);
  check('P-1550 T10 no CSS transition or animation in the card, none running', anim.length === 0, JSON.stringify(anim));
  for (const mode of ['reduce', 'no-preference']) { await S.cdp('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-reduced-motion', value: mode }] });
    check('P-1550 T10 prefers-reduced-motion: ' + mode + ' changes nothing (no motion either way)', await S.ev(`document.getAnimations().length === 0 && [...${Q}.querySelectorAll('*')].every(n => parseFloat(getComputedStyle(n).transitionDuration) === 0)`)); }
  await S.cdp('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-reduced-motion', value: 'no-preference' }] });
  await load(DATA({ tidy: MODELS.hostile() })); await S.ev(`document.documentElement.dir = 'rtl'`);
  check('P-1550 T10 RTL page: names start-aligned, each size is "label + number + unit" with the unit after the number (bdi dir=ltr), nothing flips', await S.ev(`(() => { const q = ${Q}; return [...q.querySelectorAll('.tdname')].every(n => getComputedStyle(n).textAlign === 'start' || getComputedStyle(n).textAlign === 'right') && [...q.querySelectorAll('.tdz bdi')].every(b => /^\\d+(\\.\\d)?\\u00a0(B|KB|MB|GB|TB)$/.test(b.textContent)); })()`));

  // contrast, layout, screenshots
  const SHOT_SET = [['found', 3], ['met', 3], ['hostile', 3]], SMALL = ['none', 'unreadable', 'empty', 'partial', 'old', 'weeks2', 'disabled', 'notice'];
  const THEMES = [['Dark+', 'dark'], ['Light+', 'light'], ['High Contrast', 'hc']];
  const shot = async (state, theme, w) => {
    await S.ev(`document.activeElement && document.activeElement.blur()`); await S.sleep(30);
    const r = JSON.parse(await S.ev(`JSON.stringify((() => { const q = ${Q}, prev = q.previousElementSibling || q, a = Math.min(prev.getBoundingClientRect().top, q.getBoundingClientRect().top) + window.scrollY, b = q.getBoundingClientRect().bottom + window.scrollY; return { x: 0, y: Math.max(0, a - 6), width: document.documentElement.clientWidth, height: Math.ceil(b - a) + 12 }; })())`));
    fs.writeFileSync(path.join(SHOTS, `tidy-${state}-${theme}-${w}.png`), await S.shot(r, 2));
  };
  const prep = async (state, theme, w) => {
    await load(DATA({ tidy: MODELS[state](), tidyTool: state !== 'disabled' }), theme, w);
    if (state === 'notice') { await S.ev(`${Q}.querySelector('button').click()`); await S.sleep(60); await S.ev('window.__msgs.length = 0'); }
    await S.ev(`${Q}.scrollIntoView({ block: 'end' })`); await S.sleep(60);
  };
  const FOCUS_RATIO = `(() => { const q = ${Q}, b = q.querySelector('button'); b.focus(); const cs = getComputedStyle(b); const c = window.__c, bg = c.bgOf(b.parentElement), ring = c.colorOn(cs.outlineColor, bg); return { r: +c.ratio(ring, bg).toFixed(2), w: cs.outlineWidth }; })()`;
  const BTN_RATIO = `(() => { const b = ${Q}.querySelector('button'), c = window.__c, bg = c.bgOf(b), fg = c.colorOn(getComputedStyle(b).color, bg); return +c.ratio(fg, bg).toFixed(2); })()`;
  const btnReport = [];
  for (const [label, theme] of THEMES) for (const w of [280, 315, 360]) {
    for (const state of ['found', 'met', 'hostile', 'notice', 'disabled', 'partial', 'old', 'none']) {
      await prep(state, theme, w);
      const tx = await S.ev(D.TEXT_IN('#pane-health .tdy, #pane-health .tdy *')), bad = tx.filter(x => x.ratio < 4.5);
      const lay = await S.ev(`(() => { const q = ${Q}, d = document.documentElement, sc = document.getElementById('scroll'); const out = { hs: d.scrollWidth <= d.clientWidth && sc.scrollWidth <= sc.clientWidth, card: q.scrollWidth <= q.clientWidth, btnH: Math.round(q.querySelector('button').getBoundingClientRect().height), cut: [...q.querySelectorAll('*')].filter(n => n.getClientRects().length && n.scrollWidth > n.clientWidth + 1 && getComputedStyle(n).display !== 'inline').map(n => n.className || n.tagName).slice(0, 3), ell: [...q.querySelectorAll('.tdz, .tdz *, .tdw, .tds, time, bdi')].filter(n => getComputedStyle(n).textOverflow === 'ellipsis' || getComputedStyle(n).webkitLineClamp !== 'none').length, overlap: 0 };
        q.querySelectorAll('li').forEach(li => { const r = [...li.children].map(n => n.getBoundingClientRect()); for (let i = 1; i < r.length; i++) if (r[i].top < r[i - 1].bottom - 0.5) out.overlap++; }); return out; })()`);
      const cls = await S.ev(`[...${Q}.querySelectorAll('*')].filter(n => /\\b(okt|dangert|warnt|ok|warn|danger|hred|hamb|primary)\\b/.test(n.className.toString())).length`);
      check(`P-1551 T11/T12 [${label} ${w} ${state}] text >= 4.5:1 (${tx.length} elements, lowest ${tx.length ? Math.min(...tx.map(x => x.ratio)) : '-'}), no horizontal scroll, nothing cut, sizes never ellipsised, button >= 22 px (${lay.btnH}), no overlap, no status/primary class`,
        tx.length >= 4 && bad.length === 0 && lay.hs && lay.card && lay.btnH >= 22 && lay.cut.length === 0 && lay.ell === 0 && lay.overlap === 0 && cls === 0, JSON.stringify({ bad: bad.slice(0, 4), lay, cls }));
      if (state === 'found') { const fr = await S.ev(FOCUS_RATIO); btnReport.push(`${label} ${w}: button label ${await S.ev(BTN_RATIO)}:1, focus ring ${fr.r}:1 (${fr.w})`);
        check(`P-1551 T11 [${label} ${w}] focus ring >= 3:1 and 2 px`, fr.r >= 3 && parseFloat(fr.w) >= 2, JSON.stringify(fr));
        check(`P-1551 T11 [${label} ${w}] the button label >= 4.5:1`, (await S.ev(BTN_RATIO)) >= 4.5); }
      if (WRITE && (SHOT_SET.some(([s]) => s === state) || (SMALL.includes(state) && ((w === 315 && theme !== 'hc') || (w === 280 && theme === 'hc'))))) await shot(state, theme, w);
    }
    if (WRITE && w !== 0) for (const state of SMALL.filter(s => !['none', 'partial', 'old', 'notice', 'disabled'].includes(s))) if ((w === 315 && theme !== 'hc') || (w === 280 && theme === 'hc')) { await prep(state, theme, w); await shot(state, theme, w); }
  }
  console.log('INFO ' + btnReport.join(' | '));
  // grey ink only: the distinct text colours in the card are ink, text-2 and the button label
  await prep('found', 'dark', 315);
  const cols = await S.ev(`[...new Set([...${Q}.querySelectorAll('*')].filter(n => [...n.childNodes].some(c => c.nodeType === 3 && c.textContent.trim())).map(n => getComputedStyle(n).color))].length`);
  check('P-1551 T14 the card uses at most 3 text colours (ink, grey text-2, button label): no red, amber or green', cols <= 3, cols);
  S.close();
  console.log(C.fails ? `\nFAILED: ${C.fails} of ${C.n}` : `\nALL PASS (${C.n})`); process.exit(C.fails ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
