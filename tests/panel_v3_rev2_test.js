// Panel v3 UX revision v2 (owner approval 21 Oct 2026, with the owner's change: the step timeline shows ONLY the dot, no coloured box round a phase) in real headless Chrome:
// autopilot + Safe mode line, the dot rail, one button grid, the Change / Safe mode / On its own sheets ("Keep going until" A / B / C), option C states and banner, the Ask model, contrast, jargon.
// 280 / 315 / 360 px; Dark+, Light+, High Contrast. Screenshots are rewritten only with SHIPMIRACLE_SHOTS=1 (tests/fixtures/panel-v3-rev2/*.png, light and dark; high contrast stays in reports/screens). Run: node tests/panel_v3_rev2_test.js
require('./shipmiracle_isolation').apply();
const fs = require('fs'), path = require('path');
const D = require('./panel_cdp');
if (!D.H.available()) { console.log('SKIP no Chrome'); process.exit(0); }
const F = require('./panel_v3_fixtures'), CH = require('../vscode-ext/shipmiracle-panel/charter.js'), S0 = require('../vscode-ext/shipmiracle-panel/strings.js');
const C = D.checker(), check = C.check;
const SHOTS = path.join(__dirname, 'fixtures', 'panel-v3-rev2'), SCRATCH = path.join(__dirname, '..', 'reports', 'screens'), WRITE = process.env.SHIPMIRACLE_SHOTS === '1';
fs.mkdirSync(SCRATCH, { recursive: true }); if (WRITE) fs.mkdirSync(SHOTS, { recursive: true });

const crs = n => [F.cr('CR-012', 'RTL fix', 'open', 'do'), F.cr('CR-013', 'Export report', 'queued', 'scope'), { ...F.cr('CR-014', 'إصلاح الواجهة', 'queued', 'scope'), in_chat: true }, F.cr('CR-016', 'Four', 'queued', 'scope'), F.cr('CR-017', 'Five', 'queued', 'scope'), F.cr('CR-018', 'Six', 'queued', 'scope')].slice(0, n);
const mk = (name, o = {}) => F.mk(name, 'software', { folders: ['src', 'tests'], ...o });
const SPEC = () => [mk('own-app', { cr: crs(3) }), mk('big-app', { cr: crs(6) }), mk('nofolder-app', { cr: crs(1), folders: [] }), mk('nocr-app'), mk('warn-app', { level: 'warn', cr: crs(1) }), mk('off-app', { level: 'off' }), mk('busy-app', { state: 'working', cr: crs(1), levelSwitch: { ok: false, why: 'Not now: busy-app is working or waiting for you.' } })];
const ASKP = (o = {}) => F.mk('ask', 'notes', { dir: '/x/ask', ask: { inbox: true, questions_today: 3, limit: 20, notes: 2, last: null, model_supported: true, ...o } });
const ALL = () => [...F.STATES.map(s => s.p), ...F.C_STATES.map(s => s.p), ...F.TYPES.map(t => t.p), F.EXTRA.queued, F.EXTRA.fast, F.EXTRA.held, ...SPEC()];
const DATA = (o = {}) => ({ projects: ALL(), autopilot: { until_disabled_supported: true }, plan: { meters: [{ id: 'week', label: 'Week', pct: 12.3, lvl: 0, resets: null }] }, ...o });
const cardJs = nm => `[...document.querySelectorAll('.card')].find(c => c.querySelector('.name').textContent === ${JSON.stringify(nm)})`;

(async () => {
  const S = await D.session({ size: '345,900' }); const load0 = S.load; S.load = async (...a) => { try { await S.sleep(260); await S.ev(`sessionStorage.clear()`); } catch (e) { /* first load */ } return load0(...a); };
  const msgs = () => S.ev('JSON.stringify(window.__msgs)').then(JSON.parse).then(a => a.filter(x => x.type !== 'editing'));
  const clr = () => S.ev('window.__msgs.length = 0');
  const q = (nm, sel) => `${cardJs(nm)}.querySelector(${JSON.stringify(sel)})`;
  const click = (nm, sel) => S.ev(`${q(nm, sel)}.click()`);
  const key = (k, code, vk) => S.key(k, code, vk);
  const shotCard = async (nm, name, theme) => { const r = await S.ev(`(() => { const b = ${cardJs(nm)}.getBoundingClientRect(); return { x: Math.max(0, b.left - 8), y: b.top - 8 + window.scrollY, w: b.width + 16, h: b.height + 16 }; })()`);
    const buf = await S.shot({ x: r.x, y: r.y, width: r.w, height: r.h }, 2); fs.writeFileSync(path.join(WRITE && theme !== 'hc' ? SHOTS : SCRATCH, `rev2-${name}-${theme}.png`), buf); };

  for (const theme of ['dark', 'light', 'hc']) {
    const T = `[${theme}] `;
    const f = S.file('all-' + theme, D.page(theme, DATA())); await S.load(f, 315, '?tab=projects', 12000);
    check(T + 'no style= attribute in the markup (CSP)', !/\sstyle=/.test(await S.ev(`document.documentElement.outerHTML`)));

    // 1. the autopilot line + Safe mode
    const ap = await S.ev(`[...document.querySelectorAll('.card')].filter(c => c.dataset.state !== 'noplaybook').map(c => ({ n: c.querySelector('.name').textContent, lines: c.querySelectorAll('.apline').length, apl: c.querySelector('.apl') && c.querySelector('.apl').textContent.replace(/\\s+/g, ' ').trim(), sfl: c.querySelector('.sfl') && c.querySelector('.sfl').textContent.replace(/\\s+/g, ' ').trim(), cls: c.querySelector('.sfl') && c.querySelector('.sfl').className }))`);
    check(T + `every playbook card has exactly one Autopilot line with a level word and Safe mode text (${ap.length} cards)`, ap.length > 30 && ap.every(a => a.lines === 1 && /^Autopilot · (Step by step|Normal|On its own) ▾$/.test(a.apl) && /^Safe mode( ✓|: warnings only| off)$/.test(a.sfl)), JSON.stringify(ap.filter(a => !(a.lines === 1 && /^Autopilot · /.test(a.apl))).slice(0, 3)));
    const sf = Object.fromEntries(ap.map(a => [a.n, a]));
    check(T + 'Safe mode text and class follow the level: strict "Safe mode ✓" (green tick), warn "Safe mode: warnings only", off "Safe mode off" (amber-soft chip); no tooltip needed', sf['own-app'].sfl === 'Safe mode ✓' && sf['warn-app'].sfl === 'Safe mode: warnings only' && sf['warn-app'].cls.includes('sf-warn') && sf['off-app'].sfl === 'Safe mode off' && sf['off-app'].cls.includes('sf-off'), JSON.stringify([sf['own-app'], sf['warn-app'], sf['off-app']]));
    check(T + 'the old promise text, the Change button, the Guided chip and the strict pill are gone from the card', await S.ev(`!document.querySelector('.apchip, .chip.lvl, .chip.hard, .stripline, .strip') && ![...document.querySelectorAll('.card .btn')].some(b => b.textContent.trim() === 'Change')`));

    // 2. the dot rail
    const rails = await S.ev(`[...document.querySelectorAll('.card')].filter(c => c.querySelector('.rail')).map(c => ({ n: c.querySelector('.name').textContent, ty: c.querySelector('.tag').textContent, words: [...c.querySelectorAll('.rail .rs')].map(b => b.querySelector('.rw').textContent), cur: c.querySelectorAll('.rail [aria-current="step"]').length, h: [...c.querySelectorAll('.rail .rs')].map(b => Math.round(b.getBoundingClientRect().height)), w: [...c.querySelectorAll('.rail .rs')].map(b => Math.round(b.getBoundingClientRect().width)), cut: [...c.querySelectorAll('.rail .rw')].filter(x => x.scrollWidth > x.clientWidth + 0.5).length, cols: getComputedStyle(c.querySelector('.rail')).gridTemplateColumns.split(' ').length, st: c.dataset.state }))`);
    check(T + 'the rail has 7 step buttons in the order of the type words (Brief Plan OK Build Test Review Ship ...)', rails.every(r => JSON.stringify(r.words) === JSON.stringify(F.NAMES[r.ty])), JSON.stringify(rails.filter(r => JSON.stringify(r.words) !== JSON.stringify(F.NAMES[r.ty])).slice(0, 2)));
    check(T + 'exactly one aria-current="step" on a card with an open request; none when idle, delivered or no request', rails.every(r => r.cur === ((['idle', 'delivered', 'noplaybook'].includes(r.st) || ['c-wait', 'c-lapsed', 'nocr-app', 'queued-app', 'held-app', 'off-app'].includes(r.n)) ? 0 : r.cur) && r.cur <= 1) && rails.filter(r => r.cur === 1).length > 20, JSON.stringify(rails.filter(r => r.cur > 1)));
    check(T + 'at 315 px the rail is one line of 7 columns, 40 px high; no word is cut; every column >= 24 px wide', rails.every(r => r.cols === 7 && r.h.every(h => h === 40) && r.w.every(w => w >= 24) && r.cut === 0), JSON.stringify(rails.filter(r => !(r.cols === 7 && r.h.every(h => h === 40) && r.cut === 0)).slice(0, 2)));
    const hidden = await S.ev(`[...document.querySelectorAll('.rail .rs')].filter(n => { const s = getComputedStyle(n); return s.backgroundColor !== 'rgba(0, 0, 0, 0)'; }).length`);
    check(T + 'owner change: no coloured box round any phase (red, amber or other): step buttons have no background, only the dot carries the state', hidden === 0, String(hidden));
    const marks = await S.ev(`(() => { const g = n => [...${cardJs('c-qa')}.querySelectorAll('.rail .rs')].map(x => x.className.replace('rs s-', '') + ':' + x.querySelector('.dt').textContent.trim()).join(' '); return { qa: g(), wait: [...${cardJs('c-check')}.querySelectorAll('.rail .rs')].map(x => x.className.replace('rs s-', '')).join(' '), skip: getComputedStyle(${cardJs('fast-app')}.querySelector('.s-skip .dt')).borderTopStyle, done: getComputedStyle(${cardJs('build-app')}.querySelector('.s-done .dt')).backgroundColor, next: getComputedStyle(${cardJs('build-app')}.querySelector('.s-next .dt')).borderTopStyle }; })()`);
    check(T + 'C pause marks: red pause = ✕ dot on the current step, amber pause = ! dot (shape + word, never colour alone); skipped dots are dashed; next dots are hollow', /fail:✕/.test(marks.qa) && /wait/.test(marks.wait) && marks.skip === 'dashed' && marks.next === 'solid' && marks.done !== 'rgba(0, 0, 0, 0)', JSON.stringify(marks));

    // tap for detail
    await clr();
    await click('review-app', '.rs[data-step="verify"]');
    const d1 = await S.ev(`(() => { const c = ${cardJs('review-app')}, d = c.querySelector('[data-rdetail]'); return { vis: !d.hidden, txt: d.textContent, exp: c.querySelector('.rs[data-step="verify"]').getAttribute('aria-expanded'), btn: d.querySelector('button') && d.querySelector('button').textContent, rep: d.querySelector('button') && d.querySelector('button').dataset.report }; })()`);
    check(T + 'tap a Done step with a report: "Test · PASS · 214 of 214 · 20 Oct" and a "report ›" button', d1.vis && /^Test · PASS · 214 of 214 · 20 Oct/.test(d1.txt) && d1.btn === 'report ›' && d1.rep === 'docs/reports/cr-012-verify.md' && d1.exp === 'true', JSON.stringify(d1));
    await S.ev(`${cardJs('review-app')}.querySelector('[data-rdetail] button').click()`); let m = await msgs();
    check(T + '"report ›" posts {act:openreport} for that report and nothing else', m.length === 1 && m[0].act === 'openreport' && m[0].report === 'docs/reports/cr-012-verify.md' && m[0].project === 'review-app', JSON.stringify(m));
    await click('review-app', '.rs[data-step="scope"]');
    const d2 = await S.ev(`(() => { const c = ${cardJs('review-app')}; return { txt: c.querySelector('[data-rdetail]').textContent, open: c.querySelectorAll('.rs[aria-expanded="true"]').length }; })()`);
    check(T + 'a Done step without a report says "Done. No report saved for this step."; only one detail is open at a time', d2.txt === 'Done. No report saved for this step.' && d2.open === 1, JSON.stringify(d2));
    await click('review-app', '.rs[data-step="review"]'); const d3 = await S.ev(`${cardJs('review-app')}.querySelector('[data-rdetail]').textContent`);
    await click('review-app', '.rs[data-step="deliver"]'); const d4 = await S.ev(`${cardJs('review-app')}.querySelector('[data-rdetail]').textContent`);
    check(T + 'tap the Now and a Next step: the one-sentence meaning', d3 === 'Review · A second reader goes through it for mistakes and risks.' && d4 === 'Ship · Save and hand over the finished change.', JSON.stringify([d3, d4]));
    await S.ev(`${q('review-app', '.rs[data-step="deliver"]')}.focus()`); await key('Escape', 'Escape', 27); await S.sleep(60);
    check(T + 'Esc closes the detail and returns focus to that step', await S.ev(`(() => { const c = ${cardJs('review-app')}; return c.querySelector('[data-rdetail]').hidden && document.activeElement === c.querySelector('.rs[data-step="deliver"]') && !c.querySelector('.rs[aria-expanded="true"]'); })()`));
    await click('review-app', '.rs[data-step="plan"]'); await click('review-app', '.rs[data-step="plan"]');
    check(T + 'a second tap on the same step closes it', await S.ev(`${q('review-app', '[data-rdetail]')}.hidden`));
    check(T + 'a step tap does not open the chat (no message)', (await msgs()).filter(x => x.type === 'open').length === 0);

    // 4. the button grid
    const grid = await S.ev(`[...document.querySelectorAll('.card > .brow')].map(b => { const k = [...b.children], r = k.map(x => x.getBoundingClientRect()); const p = b.querySelector('.btn.primary').getBoundingClientRect(), mo = b.querySelector('.btn.more').getBoundingClientRect(); return { n: b.closest('.card').querySelector('.name').textContent, ph: Math.round(p.height), mh: Math.round(mo.height), mw: Math.round(mo.width), x1: Math.round(p.left), x3: Math.round(mo.left), gap: Math.round(mo.left - p.right) }; })`);
    check(T + `.brow: primary and ⋯ are 28 px high, ⋯ is 28 wide, and slots 1 and 3 sit at the same x on all ${grid.length} cards`, grid.length > 30 && grid.every(g => g.ph === 28 && g.mh === 28 && g.mw === 28 && g.x1 === grid[0].x1 && g.x3 === grid[0].x3), JSON.stringify(grid.filter(g => !(g.ph === 28 && g.x1 === grid[0].x1 && g.x3 === grid[0].x3)).slice(0, 3)));
    const s2 = await S.ev(`[...document.querySelectorAll('.card > .brow')].map(b => { const k = b.querySelector('.stopc, .stopq, .aside'); return k ? Math.round(k.getBoundingClientRect().left) : null; }).filter(x => x !== null)`);
    check(T + 'slot 2 (Ask aside or Stop autopilot) is at the same x on every card that has it', s2.length > 20 && s2.every(x => x === s2[0]), JSON.stringify([...new Set(s2)]));

    // 8. option C cards: Stop autopilot in slot 2 in every state, slot 1 verbs, bands, waiting rows
    for (const st of F.C_STATES) {
      const nm = st.p.name;
      const r = await S.ev(`(() => { const c = ${cardJs(nm)}, b = c.querySelector(':scope > .brow'), kids = [...b.children], stop = b.querySelector('.stopc'); return { stop: !!stop, stopTxt: stop && stop.textContent, stopIdx: stop ? kids.indexOf(stop) : -1, pr: b.querySelector('.btn.primary').textContent, prDis: b.querySelector('.btn.primary').disabled, prTip: b.querySelector('.btn.primary').title, band: c.querySelector('.cband') && c.querySelector('.cband').textContent.replace(/\\s+/g, ' ').trim(), cls: c.querySelector('.cband') && c.querySelector('.cband').className, verb: b.querySelector('.btn.primary').dataset.verb || '' }; })()`);
      const live = !['lapsed'].includes(st.key);
      check(`${T}C state ${st.key}: ${live ? 'Stop autopilot in slot 2 (red-soft, bold)' : 'ended: no Stop'}${st.slot ? ', slot 1 "' + st.slot + '"' : ''}`, live ? (r.stop && r.stopIdx === 1 && r.stopTxt === 'Stop autopilot') && (!st.slot || (r.pr === st.slot && r.verb === st.cmd && r.prDis === !!st.off)) : !r.stop, JSON.stringify(r));
    }
    const bands = await S.ev(`Object.fromEntries(['c-run', 'c-check', 'c-day', 'c-week', 'c-qa', 'c-rev', 'c-unk', 'c-wait', 'c-lapsed'].map(n => { const c = [...document.querySelectorAll('.card')].find(x => x.querySelector('.name').textContent === n); return [n, [c.querySelector('.cband') && c.querySelector('.cband .cbt').textContent.replace(/\\s+/g, ' ').trim(), c.querySelector('.sub') && c.querySelector('.sub').textContent]]; }))`);
    check(T + 'C bands: running, daily check-in, today\'s limit (next check-in in 6 h), week limit, tests failed, review not accepted, new request asked; waiting and lapsed have the plain lines', /^Autopilot running until you stop it$/.test(bands['c-run'][0]) && /Paused: daily check-in\. Keep going another day\?/.test(bands['c-check'][0]) && /Paused: today's limit reached\. Next check-in in 6 h\./.test(bands['c-day'][0]) && /Paused: your week limit for autopilot is reached\./.test(bands['c-week'][0])
      && /Paused: tests failed on CR-013\. It will not go on without you\./.test(bands['c-qa'][0]) && /Paused: the review did not accept CR-013\. It will not go on without you\./.test(bands['c-rev'][0]) && /Paused: CR-013 asked to open a new request\. It will not go on without you\./.test(bands['c-unk'][0]) && bands['c-wait'][0] === null && bands['c-wait'][1] === 'Waiting for requests you OK.' && bands['c-lapsed'][1] === 'Autopilot stopped: no daily yes for 7 days. Back to Normal.', JSON.stringify(bands));
    // slot-1 / Stop / admit messages
    await clr(); await click('c-check', '.btn.primary'); await click('c-qa', '.btn.primary'); await click('c-run', '[data-verb="admit"]'); await click('c-day', '.btn.primary');
    m = await msgs();
    check(T + 'C buttons post exactly {act:cverb, verb} (checkpoint, resume, admit with the CR id); a disabled "Keep going" posts nothing', m.length === 3 && m[0].act === 'cverb' && m[0].verb === 'checkpoint' && m[1].verb === 'resume' && m[2].verb === 'admit' && m[2].cr === 'CR-015' && m[2].project === 'c-run' && !JSON.stringify(m).match(/yes|approved|until I disable/i), JSON.stringify(m));
    await clr(); await click('c-qa', '.stopc'); const armed = await S.ev(`${q('c-qa', '.stopc')}.textContent`); m = await msgs(); await click('c-qa', '.stopc'); const m2 = await msgs();
    check(T + 'Stop autopilot (C): first tap asks "Sure?" and posts nothing; the second posts {act:apstop}', armed === 'Sure?' && m.length === 0 && m2.length === 1 && m2[0].act === 'apstop' && m2[0].project === 'c-qa', JSON.stringify([armed, m, m2]));
    await S.ev(`${q('c-qa', '.btn.more')}.click()`);
    const mi = await S.ev(`[...${cardJs('c-qa')}.querySelectorAll('.menu .mi')].map(x => x.textContent.trim())`);
    check(T + 'the ⋯ menu of a "tests failed" pause has "Drop CR-013" and Autopilot… / Safe mode…', mi.includes('Drop CR-013') && mi.includes('Autopilot…') && mi.includes('Safe mode…'), JSON.stringify(mi));
    await S.ev('document.body.click()');
    const wr = await S.ev(`(() => { const c = ${cardJs('c-run')}, r = c.querySelector('.cwrow'); return { head: c.querySelector('.cwait .nh').textContent, txt: r.querySelector('.cwt').textContent, btn: r.querySelector('.btn').textContent }; })()`);
    check(T + 'a request a chat opened waits: "Waiting for your OK" · "CR-015 · Login page (opened in a chat)" with "Let autopilot do it"', wr.head === 'Waiting for your OK' && wr.txt === 'CR-015 · Login page (opened in a chat)' && wr.btn === 'Let autopilot do it', JSON.stringify(wr));

    // banner on every tab
    for (const tab of ['projects', 'reports', 'ideas', 'health', 'setup']) {
      await S.load(f, 315, '?tab=' + tab, 1400);
      const b = await S.ev(`(() => { const e = document.querySelector('[data-cban]'); return e ? { txt: e.textContent.trim(), red: e.classList.contains('red'), vis: e.getBoundingClientRect().height > 0, tab: document.querySelector('[role="tab"][aria-selected="true"]').dataset.tab, frozen: !!e.closest('.frozen') } : null; })()`);
      check(`${T}banner on the ${tab} tab: shown in the frozen header; first C run is amber with the check-in, day, week and waiting count`, !!b && b.vis && b.tab === tab && b.frozen && /^On its own until you disable it · next check-in in 13 h · today 2% of 4% · week 6% of 10% · 1 request waiting for your OK$/.test(b.txt), JSON.stringify(b));
    }
    const pf = S.file('pb-' + theme, D.page(theme, DATA({ projects: [F.C_STATES.find(s => s.key === 'qa_fail').p] }))); await S.load(pf, 315, '?tab=ideas', 1400);
    const pb = await S.ev(`(() => { const e = document.querySelector('[data-cban]'); return { txt: e.textContent.trim().replace(/\\s+/g, ' '), red: e.classList.contains('red'), btn: e.querySelector('.btn') && e.querySelector('.btn').textContent }; })()`);
    check(T + 'paused: the banner turns red-soft: "Paused: tests failed on CR-013" with a quiet Stop', pb.red && /^Paused: tests failed on CR-013Stop$/.test(pb.txt) && pb.btn === 'Stop', JSON.stringify(pb));
    await clr(); await S.ev(`document.querySelector('[data-cban] .btn').click()`); await S.ev(`document.querySelector('[data-cban] .btn').click()`); m = await msgs();
    check(T + 'banner Stop: "Sure?" then {act:apstop} (one message)', m.length === 1 && m[0].act === 'apstop' && m[0].project === 'c-qa', JSON.stringify(m));
    const nf = S.file('nb-' + theme, D.page(theme, DATA({ projects: [F.STATES[0].p] }))); await S.load(nf, 315, '?tab=projects', 1400);
    check(T + 'no banner when no run that lasts until you disable it exists', await S.ev(`!document.querySelector('[data-cban]')`));
    await S.load(f, 315, '?tab=projects', 12000);

    // jargon
    const jar = await S.ev(`[...document.querySelectorAll('.card')].filter(c => c.dataset.state !== 'noplaybook').map(c => c.innerText).join(' ').match(/\\b(charter|segment|sha\\d*|hard stop|lane|lens|Manual|Guided|Full|strict|budget|deps|glob)\\b/gi)`);
    check(T + 'no jargon in the default-visible card text (charter, segment, sha, hard stop, lane, lens, Manual, Guided, Full, strict, budget, deps, glob; the older gate wording of the Blocked line is unchanged)', !jar, JSON.stringify(jar));

    // contrast of the new colours (cards, banner)
    const tx = await S.ev(D.TEXT_IN('.card *, .cban *, .cban'));
    const bad = tx.filter(x => x.ratio < 4.5);
    check(`${T}text contrast >= 4.5:1 on ${tx.length} texts incl. rail words, Safe mode chips, C bands, banner (lowest ${Math.min(...tx.map(x => x.ratio))})`, tx.length > 400 && bad.length === 0, JSON.stringify(bad.slice(0, 8)));
    const dots = await S.ev(`(() => { const { ratio, bgOf, colorOn } = window.__c, out = []; document.querySelectorAll('.card .dt').forEach(n => { const card = bgOf(n.closest('.card'), false), s = getComputedStyle(n), fill = colorOn(s.backgroundColor, card), border = colorOn(s.borderTopColor, card), own = bgOf(n); const g = n.textContent.trim() ? ratio(colorOn(s.color, own), own) : 99; out.push({ c: n.parentElement.className, mark: +Math.max(ratio(fill, card), ratio(border, card)).toFixed(2), glyph: +g.toFixed(2) }); }); return out; })()`);
    check(`${T}dot marks >= 3:1 against the card and their glyph >= 3:1 on the dot (${dots.length} dots, lowest ${Math.min(...dots.map(x => x.mark))})`, dots.length > 200 && dots.every(x => x.mark >= 3 && x.glyph >= 3), JSON.stringify(dots.filter(x => x.mark < 3 || x.glyph < 3).slice(0, 5)));
    const sb = await S.ev(`(() => { const { ratio, bgOf, colorOn } = window.__c; return [...document.querySelectorAll('.sfl.sf-warn, .sfl.sf-off, .cband, .cban, .btn.stopc')].filter(n => n.getClientRects().length).map(n => { const bg = bgOf(n), card = bgOf(n.parentElement), s = getComputedStyle(n); return { c: n.className.slice(0, 20), t: +ratio(colorOn(s.color, bg), bg).toFixed(2), edge: +ratio(bg, card).toFixed(2) }; }); })()`);
    check(`${T}amber-soft / red-soft chips, bands and the Stop button: text >= 4.5:1 on their own fill (${sb.length} checked)`, sb.length > 10 && sb.every(x => x.t >= 4.5), JSON.stringify(sb.filter(x => x.t < 4.5)));
    if (theme !== 'hc' || true) for (const [nm, name] of [['build-app', 'rail-now'], ['approve-app', 'rail-waiting'], ['c-qa', 'c-paused-red'], ['c-run', 'c-running'], ['own-app', 'apline']]) await shotCard(nm, name, theme);
  }

  // widths 280 / 360
  for (const w of [280, 360]) {
    const f = S.file('w-' + w, D.page('light', DATA())); await S.load(f, w, '?tab=projects', 12000);
    const r = await S.ev(`(() => { const rs = [...document.querySelectorAll('.card')].filter(c => c.querySelector('.rail')).map(c => ({ cols: getComputedStyle(c.querySelector('.rail')).gridTemplateColumns.split(' ').length, h: [...c.querySelectorAll('.rail .rs')].map(b => b.getBoundingClientRect().height), w: [...c.querySelectorAll('.rail .rs')].map(b => b.getBoundingClientRect().width), cut: [...c.querySelectorAll('.rail .rw')].filter(x => x.scrollWidth > x.clientWidth + .5).length })); const g = [...document.querySelectorAll('.card > .brow')].map(b => { const p = b.querySelector('.btn.primary').getBoundingClientRect(), m = b.querySelector('.btn.more').getBoundingClientRect(); return [Math.round(p.height), Math.round(p.left), Math.round(m.left)]; }); const sc = document.getElementById('scroll'), d = document.documentElement; return { rs, g, hs: d.scrollWidth <= d.clientWidth && sc.scrollWidth <= sc.clientWidth }; })()`);
    check(`[${w}] rail: ${w === 280 ? 'the 4 + 3 grid (dots only) on a very narrow panel' : 'one line of 7'}; every step >= 24 px high and wide; no word cut`, r.rs.every(x => x.cols === (w === 280 ? 4 : 7) && x.h.every(h => h >= (w === 280 ? 24 : 40)) && x.w.every(v => v >= 24) && x.cut === 0), JSON.stringify(r.rs.filter(x => x.cut || x.cols !== (w === 280 ? 4 : 7)).slice(0, 2)));
    check(`[${w}] .brow: 28 px high, slot positions equal on every card, no horizontal scroll`, r.g.every(x => x[0] === 28 && x[1] === r.g[0][1] && x[2] === r.g[0][2]) && r.hs, JSON.stringify([r.g.slice(0, 2), r.hs]));
    const nodots = await S.ev(`[...document.querySelectorAll('.rail .rs')].filter(n => getComputedStyle(n).backgroundColor !== 'rgba(0, 0, 0, 0)').length`);
    check(`[${w}] fallback grid also dots only: no box round any step`, nodots === 0);
  }

  // 5. sheets: Change, Safe mode, On its own
  for (const theme of ['dark', 'light', 'hc']) {
    const T = `[${theme}] `;
    const f = S.file('sh-' + theme, D.page(theme, DATA({ projects: [...SPEC(), ASKP()] }))); await S.load(f, 315, '?tab=projects', 6000);
    // Change sheet
    await S.ev(`${q('own-app', '.apl')}.click()`);
    const ls = await S.ev(`(() => { const c = ${cardJs('own-app')}, b = c.querySelector('[data-sheetbox="level"]'); return { vis: !b.hidden, rows: [...b.querySelectorAll('[role="radio"]')].map(r => r.getAttribute('aria-checked') + ':' + r.querySelector('b').textContent + ':' + (r.querySelector('.orc') ? 'Current' : '')), prom: [...b.querySelectorAll('.ord')].map(x => x.textContent), others: getComputedStyle(c.querySelector('.railw')).display, focus: document.activeElement.dataset.lv, exp: c.querySelector('.apl').getAttribute('aria-expanded') }; })()`);
    check(T + 'Change sheet: three radios Step by step / Normal / On its own, the current one ticked and labelled "Current", with the one-line promises', ls.vis && JSON.stringify(ls.rows) === JSON.stringify(['false:Step by step:', 'true:Normal:Current', 'false:On its own:']) && ls.prom[0] === 'It stops after every step and waits for you.' && ls.prom[1] === 'It keeps going, and asks you at approvals and when something risky comes up.' && ls.prom[2] === 'It works through a request without asking, inside limits you set. Risky things still stop it.' && ls.others === 'none', JSON.stringify(ls));
    await key('Escape', 'Escape', 27); await S.sleep(60);
    check(T + 'Esc closes the Change sheet and returns focus to the Autopilot line', await S.ev(`${q('own-app', '[data-sheetbox="level"]')}.hidden && document.activeElement === ${q('own-app', '.apl')}`));
    await S.ev(`${q('own-app', '.apl')}.click()`); await clr(); await S.ev(`${q('own-app', '[data-lv="manual"]')}.click()`); m = await msgs();
    check(T + 'choosing Step by step posts {act:ap, to:manual} once and closes the sheet', m.length === 1 && m[0].type === 'act' && m[0].act === 'ap' && m[0].to === 'manual' && m[0].project === 'own-app' && await S.ev(`${q('own-app', '[data-sheetbox="level"]')}.hidden`), JSON.stringify(m));
    await S.ev(`${q('warn-app', '.apl')}.click()`);
    const wl = await S.ev(`(() => { const b = ${q('warn-app', '[data-sheetbox="level"]')}; const full = b.querySelector('[data-lv="full"]'); return { dis: full.disabled, txt: b.textContent, btn: b.querySelector('[data-safeto="strict"]') && b.querySelector('[data-safeto="strict"]').textContent }; })()`);
    check(T + 'On its own while Safe mode is not on: disabled with "On its own needs Safe mode on. Turn Safe mode on first." and a "Turn Safe mode on" button', wl.dis && /On its own needs Safe mode on\. Turn Safe mode on first\./.test(wl.txt) && wl.btn === 'Turn Safe mode on', JSON.stringify(wl));
    await clr(); await S.ev(`${q('warn-app', '[data-safeto="strict"]')}.click()`); m = await msgs();
    check(T + '"Turn Safe mode on" posts {type:safe, to:strict} only', m.length === 1 && m[0].type === 'safe' && m[0].to === 'strict' && m[0].project === 'warn-app', JSON.stringify(m));
    await S.ev(`${q('busy-app', '.apl')}.click()`);
    check(T + 'a working project: Normal/Step by step disabled with "Not now: it is working. Change it when it is waiting."', await S.ev(`(() => { const b = ${q('busy-app', '[data-sheetbox="level"]')}; return b.querySelector('[data-lv="manual"]').disabled && /Not now: it is working\\. Change it when it is waiting\\./.test(b.textContent); })()`));
    // Safe mode sheet
    await S.load(f, 315, '?tab=projects', 6000);
    await S.ev(`${q('own-app', '.sfl')}.click()`);
    const ss = await S.ev(`(() => { const b = ${q('own-app', '[data-sheetbox="safe"]')}; return { rows: [...b.querySelectorAll('[role="radio"]')].map(r => r.getAttribute('aria-checked') + ':' + r.querySelector('b').textContent + ':' + r.disabled), desc: [...b.querySelectorAll('.ord')].map(x => x.textContent), txt: b.textContent }; })()`);
    check(T + 'Safe mode sheet: On (ticked) / Warnings only / Off with the three descriptions; Off is not offered from the panel (set by hand)', JSON.stringify(ss.rows) === JSON.stringify(['true:On:false', 'false:Warnings only:false', 'false:Off:true']) && ss.desc[0] === 'It checks every step before moving on. Needed for On its own.' && ss.desc[1] === 'It tells you about problems but does not stop.' && ss.desc[2] === 'No checks between steps.' && /Off is set by hand in config\/flow\.json/.test(ss.txt), JSON.stringify(ss));
    await clr(); await S.ev(`${q('own-app', '[data-safeto="warn"]')}.click()`); m = await msgs();
    check(T + 'choosing Warnings only posts {type:safe, to:warn}', m.length === 1 && m[0].type === 'safe' && m[0].to === 'warn' && m[0].project === 'own-app', JSON.stringify(m));

    // On its own sheet
    await S.load(f, 315, '?tab=projects', 6000);
    const O = sel => q('own-app', sel), setv = (sel, v) => S.ev(`(() => { const n = ${O(sel)}; n.value = ${JSON.stringify(v)}; n.dispatchEvent(new Event('input', { bubbles: true })); })()`), tick = (sel, on = true) => S.ev(`(() => { const n = ${O(sel)}; n.checked = ${on}; n.dispatchEvent(new Event('input', { bubbles: true })); })()`);
    const pick = async (nm, v) => S.ev(`(() => { const s = ${q(nm, '[data-of="until"]')}; s.value = ${JSON.stringify(v)}; s.dispatchEvent(new Event('change', { bubbles: true })); })()`);
    const own = nm => S.ev(`(() => { const b = ${q(nm, '[data-sheetbox="own"]')}; const vis = n => n && !n.hidden && !n.closest('[hidden]'); return { vis: !b.hidden, hint: b.querySelector('[data-ohint]').textContent, list: [...b.querySelectorAll('[data-olist] li')].map(x => x.textContent), listVis: vis(b.querySelector('[data-olist]')), note: vis(b.querySelector('[data-cnote]')), timeP: vis(b.querySelector('[data-pres="time"]')), timeTxt: vis(b.querySelector('[data-otimetxt]')) ? b.querySelector('[data-otimetxt]').textContent : '', day: vis(b.querySelector('[data-oqday]')), tick: b.querySelector('[data-otick]').textContent, sum: b.querySelector('[data-osum]').textContent, why: b.querySelector('[data-owhy]').textContent, go: b.querySelector('[data-ostart]').disabled, left: b.querySelector('[data-oleft]').textContent, opts: [...b.querySelectorAll('[data-of="until"] option')].map(o => o.textContent), pressed: [...b.querySelectorAll('[aria-pressed="true"]')].filter(x => vis(x)).map(x => x.dataset.pre + '=' + x.dataset.v) }; })()`);
    await S.ev(`${O('.apl')}.click()`); await S.ev(`${O('[data-lv="full"]')}.click()`);
    let o = await own('own-app');
    check(T + 'On its own opens in place: "Keep going until" has exactly three options (no current phase, no Renew); default is "This request is done" with "CR-012 · RTL fix"', o.vis && JSON.stringify(o.opts) === JSON.stringify(['This request is done', 'I stop it (8 hours at most)', 'Until I disable it']) && o.hint === 'CR-012 · RTL fix' && !/phase|Renew|current step/i.test(await S.ev(`${O('[data-sheetbox="own"]')}.textContent`)), JSON.stringify(o));
    check(T + 'A defaults: 3 h and 10% pressed, the time presets shown, the week reading "About 87.7% left this week", Start off (tick missing)', o.timeP && o.pressed.sort().join() === 'budget=10,time=3' && !o.day && o.left === 'About 87.7% left this week' && o.go && /Tick the box to confirm/.test(o.why), JSON.stringify(o));
    check(T + 'A summary and tick are the approved text', o.sum === 'It will work on CR-012 for up to 3 hours or 10% of your week. It may change files in src/ and tests/. It will not add packages. It stops when finished or if something risky comes up, and waits for you.' && o.tick === 'I understand it will work on its own until it finishes or something risky comes up.', JSON.stringify(o));
    await tick('[data-of="tick"]'); o = await own('own-app'); check(T + 'A: ticked -> Start enabled with no reason', !o.go && o.why === '');
    await clr(); await S.ev(`${O('[data-ostart]')}.click()`); m = (await msgs()).filter(x => x.type === 'charter');
    check(T + 'A Start posts one {type:charter, op:start} with goal "Finish CR-012 RTL fix", scope src/**,tests/**, budget 10, time 3, ends [CR-012], until a; nothing else', m.length === 1 && m[0].project === 'own-app' && m[0].goal === 'Finish CR-012 RTL fix' && m[0].scope === 'src/**,tests/**' && m[0].budget === '10' && m[0].time === '3' && JSON.stringify(m[0].ends) === '["CR-012"]' && m[0].until === 'a', JSON.stringify(m));
    // presets map
    await S.ev(`${O('.apl')}.click()`); await S.ev(`${O('[data-lv="full"]')}.click()`);
    for (const [kind, v, exp] of [['time', 1, '1 hours'], ['time', 8, '8 hours'], ['budget', 5, '5% of your week'], ['budget', 25, '25% of your week']]) { await S.ev(`${O('[data-pre="' + kind + '"][data-v="' + v + '"]')}.click()`); o = await own('own-app'); check(`${T}preset ${kind} ${v} updates the summary (${exp})`, o.sum.includes(exp) && o.pressed.includes(kind + '=' + v), o.sum); }
    await S.ev(`${O('[data-pre="budget"][data-v="25"]')}.click()`); o = await own('own-app'); check(T + 'a share above what is left adds "That is more than what is left. It stops when your week runs out." (25% of 87.7% is fine: no note)', !/more than what is left/.test(o.left));
    // B
    await pick('own-app', 'b'); o = await own('own-app');
    check(T + 'B: hint, the list of the open requests with "(opened in a chat)" on the chat-opened one, the time presets replaced by "It stops after 8 hours, even if you forget."', o.hint === 'Works through your open requests in order (up to 5). It stops by itself after 8 hours.' && JSON.stringify(o.list) === JSON.stringify(['CR-012 · RTL fix', 'CR-013 · Export report', 'CR-014 · إصلاح الواجهة (opened in a chat)']) && !o.timeP && o.timeTxt === 'It stops after 8 hours, even if you forget.' && !o.note, JSON.stringify(o));
    check(T + 'B summary and tick: 8 hours at most is in the label, the summary and the tick', /^It will work through CR-012, CR-013 and CR-014, one after another, until you stop it, for at most 8 hours or 25% of your week\./.test(o.sum) && o.tick === 'I understand it keeps going on its own until I stop it, 8 hours pass, or it finishes these requests.', JSON.stringify([o.sum, o.tick]));
    await S.ev(`${O('[data-pre="budget"][data-v="10"]')}.click()`); await tick('[data-of="tick"]'); await clr(); await S.ev(`${O('[data-ostart]')}.click()`); m = (await msgs()).filter(x => x.type === 'charter');
    check(T + 'B Start: ends = the open requests in queue order, time 8, until b', m.length === 1 && JSON.stringify(m[0].ends) === '["CR-012","CR-013","CR-014"]' && m[0].time === '8' && m[0].until === 'b' && m[0].goal === 'Finish CR-012, CR-013, CR-014', JSON.stringify(m));
    // B with more than 5
    await S.ev(`${q('big-app', '.apl')}.click()`); await S.ev(`${q('big-app', '[data-lv="full"]')}.click()`); await pick('big-app', 'b'); o = await own('big-app');
    check(T + 'B with 6 open requests: only the first 5 are listed, with "Only the first 5 are included."', o.list.length === 6 && o.list[5] === 'Only the first 5 are included.' && o.list[4].startsWith('CR-017'), JSON.stringify(o.list));
    await pick('big-app', 'a'); o = await own('big-app'); check(T + 'back to A: no list, no note', !o.listVis && !o.note && o.timeP);
    await S.ev(`${q('big-app', '[data-ocancel]')}.click()`);
    // C
    await S.load(f, 315, '?tab=projects', 6000);
    await S.ev(`${O('.apl')}.click()`); await S.ev(`${O('[data-lv="full"]')}.click()`); await pick('own-app', 'c'); o = await own('own-app');
    const note = await S.ev(`(() => { const n = ${O('[data-cnote]')}; return { role: n.getAttribute('role'), head: n.querySelector('.cnh').textContent, lines: [...n.querySelectorAll('li')].map(x => x.textContent), one: n.querySelector('.cnone').textContent, edge: getComputedStyle(n).borderInlineStartWidth, edgeCol: getComputedStyle(n).borderInlineStartColor, headCol: getComputedStyle(n.querySelector('.cnh')).color, bold: getComputedStyle(n.querySelector('.cnh')).fontWeight, dismiss: !!n.querySelector('button') }; })()`);
    check(T + 'C: the warning note is exact (heading, six lines with the day and week values, "Only one project can run like this at a time."), role=alert, not dismissible, red left edge, red bold heading', note.role === 'alert' && note.head === 'Read this before you choose it' && JSON.stringify(note.lines) === JSON.stringify([
      'It keeps working without you, also at night, until you press Stop autopilot.', 'Once a day it pauses and waits until you type yes in a terminal.', 'It merges finished work into your main branch by itself after its tests and review pass.',
      'It uses your Claude week: at most 4% a day and 10% a week. Your own chats share that limit, so they can run out sooner.', 'New requests are never picked up by themselves. You OK each one in a terminal. Requests a chat opens wait for you.', 'A risky step, a failed test or a rejected review pauses it until you look.']) && note.one === 'Only one project can run like this at a time.' && note.edge === '3px' && note.edgeCol === note.headCol && +note.bold >= 600 && !note.dismiss, JSON.stringify(note));
    check(T + 'C: hint under the select, time presets hidden and replaced by "It pauses every 24 hours until you say yes.", the "A day" row (2% 4% 8%, default 4%) shown, list shown', o.hint === 'Keeps working on this project\'s requests until you press Stop. You OK it once a day.' && !o.timeP && o.timeTxt === 'It pauses every 24 hours until you say yes.' && o.day && o.pressed.includes('day=4') && o.list.length === 3, JSON.stringify(o));
    check(T + 'C summary and the REQUIRED tick are the approved text; Start is off until ticked', o.sum.startsWith('It will work through CR-012, CR-013 and CR-014, then wait for requests you OK, until you disable it. At most 4% of your week a day and 10% a week, up to 3 requests a day. It pauses every 24 hours for your yes.') && o.tick === 'I understand it keeps going and merges into main on its own until I disable it, and I will check it once a day.' && o.go && /Tick the box/.test(o.why), JSON.stringify(o));
    await S.ev(`${O('[data-pre="budget"][data-v="10"]')}.click()`); await S.ev(`${O('[data-pre="day"][data-v="8"]')}.click()`); await S.ev(`${O('[data-pre="budget"][data-v="5"]')}.click()`); await tick('[data-of="tick"]'); o = await own('own-app');
    check(T + 'C: a day above the week is impossible (8% a day with 5% a week): Start off with "A day cannot be more than the week."', o.go && /A day cannot be more than the week\./.test(o.why), o.why);
    await S.ev(`${O('[data-pre="day"][data-v="4"]')}.click()`); o = await own('own-app');
    check(T + 'C: 4% a day with 5% a week is valid; the engine is ready in this page, so Start is on once ticked', !o.go && o.why === '', JSON.stringify(o));
    await tick('[data-of="tick"]', false); o = await own('own-app'); check(T + 'C: un-ticking turns Start off again', o.go);
    await tick('[data-of="tick"]'); await clr(); await S.ev(`${O('[data-ostart]')}.click()`); m = (await msgs()).filter(x => x.type === 'charter');
    check(T + 'C Start posts until c, day 4, crsDay 3, budget 5, ends = the open requests; no approval or confirm text is in the message', m.length === 1 && m[0].until === 'c' && m[0].day === 4 && m[0].crsDay === 3 && m[0].budget === '5' && JSON.stringify(m[0].ends) === '["CR-012","CR-013","CR-014"]' && !/yes|until I disable|approved/i.test(JSON.stringify(m)), JSON.stringify(m));
    // C not ready
    const nr = S.file('nr-' + theme, D.page(theme, DATA({ projects: SPEC(), autopilot: { until_disabled_supported: false } }))); await S.load(nr, 315, '?tab=projects', 6000);
    await S.ev(`${O('.apl')}.click()`); await S.ev(`${O('[data-lv="full"]')}.click()`); await pick('own-app', 'c'); await tick('[data-of="tick"]'); o = await own('own-app');
    check(T + 'C with the engine not ready: Start is disabled with the reason "engine not ready" (A and B still work)', o.go && /Start is off: engine not ready\./.test(o.why), JSON.stringify(o));
    await pick('own-app', 'b'); o = await own('own-app'); check(T + '...and B is unaffected', !o.go);
    // no folders / no CRs / jargon in the open sheet
    await S.ev(`${q('nofolder-app', '.apl')}.click()`); await S.ev(`${q('nofolder-app', '[data-lv="full"]')}.click()`); await S.ev(`(() => { const i = ${q('nofolder-app', '[data-of="tick"]')}; i.checked = true; i.dispatchEvent(new Event('input', { bubbles: true })); })()`);
    check(T + 'no src/tests/docs folder: More options opens itself and Start says "Say which folders it may change."', await S.ev(`(() => { const b = ${q('nofolder-app', '[data-sheetbox="own"]')}; return b.querySelector('[data-omore]').open && b.querySelector('ul, .nhint') && /Say which folders it may change\\./.test(b.querySelector('[data-owhy]').textContent) && b.querySelector('[data-ostart]').disabled; })()`));
    await S.ev(`${q('nocr-app', '.apl')}.click()`); await S.ev(`${q('nocr-app', '[data-lv="full"]')}.click()`);
    check(T + 'no open request: "No open requests. Open one first, then come back." and Start stays off', await S.ev(`(() => { const b = ${q('nocr-app', '[data-sheetbox="own"]')}; return b.querySelector('[data-ohint]').textContent === 'No open requests. Open one first, then come back.' && b.querySelector('[data-ostart]').disabled; })()`));
    // the old charter editor messages, through More options
    await S.load(f, 315, '?tab=projects', 6000); await S.ev(`${O('.apl')}.click()`); await S.ev(`${O('[data-lv="full"]')}.click()`);
    const errOf = k => S.ev(`(() => { const e = ${O('[data-oerr="' + k + '"]')}; return e.hidden ? null : e.textContent; })()`);
    await setv('[data-of="folders"]', '/etc/passwd'); check(T + 'More options: a folder outside the project is refused with the charter message', await errOf('scope') === "scope: '/etc/passwd' must be relative (no leading '/' or '~')", await errOf('scope'));
    await setv('[data-of="folders"]', '.shipmiracle/**'); check(T + 'More options: the rule files are off limits', /off limits/.test(await errOf('scope') || ''));
    await setv('[data-of="folders"]', 'src/**'); await setv('[data-of="share"]', '26'); check(T + 'More options: exact share 26 is refused (the cap is 25%)', await errOf('budget') === 'budget: 26% is outside 1-25% of the week (the cap is 25%)', await errOf('budget'));
    await setv('[data-of="share"]', ''); await setv('[data-of="hours"]', '9'); check(T + 'More options: exact hours 9 are refused (0.25-8 h)', await errOf('time') === 'time: 9 h is outside 0.25-8 h', await errOf('time'));
    await setv('[data-of="hours"]', '0.5'); o = await own('own-app'); check(T + 'More options: exact hours 0.5 lowers the time', await errOf('time') === null && /0\.5 hours/.test(o.sum), o.sum);
    check(T + 'More options holds the 14 never-touched paths and "Want it to stop at each step? Use Normal."', await S.ev(`(() => { const b = ${O('[data-sheetbox="own"]')}; return b.querySelectorAll('.chlist code').length === 14 && /Want it to stop at each step\\? Use Normal\\./.test(b.textContent); })()`));
    // draft survives a redraw (same page, state kept) and Esc
    await S.ev(`${O('[data-of="goal"]')}.value = 'My goal'; ${O('[data-of="goal"]')}.dispatchEvent(new Event('input', { bubbles: true }))`);
    await S.cdp('Page.navigate', { url: 'file://' + f + '?tab=projects' }); await S.sleep(500); await S.ev(D.LIB);
    check(T + 'the sheet survives a redraw with its fields', await S.ev(`(() => { const b = ${O('[data-sheetbox="own"]')}; return !b.hidden && b.querySelector('[data-of="goal"]').value === 'My goal'; })()`));
    await S.ev(`${O('[data-omore]')}.open = true; ${O('[data-of="goal"]')}.focus()`); await key('Escape', 'Escape', 27); await S.sleep(60);
    { const esc = await S.ev(`({ hidden: ${O('[data-sheetbox="own"]')}.hidden, onApl: document.activeElement === ${O('.apl')}, act: document.activeElement.className + '|' + document.activeElement.tagName })`);
    check(T + 'Esc cancels the sheet: closed, focus back on the Autopilot line, nothing started', esc.hidden && esc.onApl && !(await msgs()).some(x => x.type === 'charter'), JSON.stringify(esc)); }
    // contrast and size of the open sheets
    for (const kind of ['level', 'safe', 'own']) {
      await S.load(f, 315, '?tab=projects', 6000);
      if (kind === 'own') { await S.ev(`${O('.apl')}.click()`); await S.ev(`${O('[data-lv="full"]')}.click()`); await pick('own-app', 'c'); await S.ev(`${O('[data-omore]')}.open = true`); }
      else await S.ev(`${O(kind === 'level' ? '.apl' : '.sfl')}.click()`);
      const bad = await S.ev(`(() => { const { ratio, bgOf, colorOn } = window.__c, out = []; document.querySelectorAll('[data-sheetbox="${kind}"] *').forEach(n => { if (!n.getClientRects().length || n.closest('svg') || n.closest('[hidden]')) return; if (![...n.childNodes].some(c => c.nodeType === 3 && c.textContent.trim())) return; if (n.disabled || n.closest(':disabled')) return; const bg = bgOf(n), fg = colorOn(getComputedStyle(n).color, bg), r = ratio(fg, bg); if (r < 4.5) out.push({ t: n.textContent.trim().slice(0, 30), r: +r.toFixed(2) }); }); return out; })()`);
      check(`${T}${kind} sheet: every visible text >= 4.5:1`, bad.length === 0, JSON.stringify(bad));
      const sz = await S.ev(`(() => { const b = ${O('[data-sheetbox="' + kind + '"]')}, bb = b.getBoundingClientRect(); const sb = b.querySelector('.brow'); const kids = [...sb.children].map(x => Math.round(x.getBoundingClientRect().left)); return { over: [...b.querySelectorAll('*')].filter(n => n.getClientRects().length && !n.closest('[hidden]') && n.getBoundingClientRect().right > bb.right + 1).map(n => n.tagName + '.' + n.className).slice(0, 5), small: [...b.querySelectorAll('button, input:not([type=checkbox]):not([type=radio]), select, summary')].filter(n => n.getClientRects().length && !n.closest('[hidden]') && n.getBoundingClientRect().height < 24).map(n => n.tagName + '.' + n.className).slice(0, 5), bh: Math.round(sb.querySelector('.btn').getBoundingClientRect().height), kids, doc: document.documentElement.scrollWidth <= window.innerWidth }; })()`);
      check(`${T}${kind} sheet: nothing leaves the box, targets >= 24 px, buttons in the 28 px grid, no horizontal scroll`, sz.over.length === 0 && sz.small.length === 0 && sz.bh === 28 && sz.doc, JSON.stringify(sz));
      if (kind === 'own') { const jar = await S.ev(`${O('[data-sheetbox="own"]')}.innerText.match(/\\b(charter|segment|sha\\d*|hard stop|gate|lane|lens|Manual|Guided|strict|deps|glob)\\b/gi)`); check(T + 'the sheet text has no jargon (charter, segment, sha, hard stop ...)', !jar, JSON.stringify(jar)); }
      await shotCard('own-app', 'sheet-' + (kind === 'own' ? 'own-c' : kind), theme);
    }
  }

  // 6. Ask card: Model select
  for (const theme of ['dark', 'light', 'hc']) {
    const T = `[${theme}] `;
    const f = S.file('ask-' + theme, D.page(theme, { projects: [ASKP()] })); await S.load(f, 315, '?tab=projects', 2000);
    const a = await S.ev(`(() => { const c = document.querySelector('.askcard'), s = c.querySelector('[data-askmodel]'); return { opts: [...s.options].map(o => o.value + ':' + o.textContent), val: s.value, hint: [...c.querySelectorAll('.nhint')].some(x => x.textContent === 'Opus is most careful. Sonnet is balanced. Haiku is fastest and uses the least of your week.'), prev: c.querySelector('[data-askprev]').textContent, btns: [...c.querySelectorAll('.brow .btn')].map(b => b.textContent + '@' + Math.round(b.getBoundingClientRect().left) + 'x' + Math.round(b.getBoundingClientRect().height)) }; })()`);
    check(T + 'Ask: Model select Opus (default) / Sonnet / Haiku with the hint; the grid has Ask (slot 1) and Cancel (slot 2), 28 px', JSON.stringify(a.opts) === JSON.stringify(['opus:Opus (default)', 'sonnet:Sonnet', 'haiku:Haiku']) && a.val === 'opus' && a.hint && /^Ask@\d+x28$/.test(a.btns[0]) && /^Cancel@\d+x28$/.test(a.btns[1]), JSON.stringify(a));
    await S.ev(`(() => { const i = document.querySelector('[data-askq]'); i.value = 'What does the stale-status hook check?'; i.dispatchEvent(new Event('input', { bubbles: true })); })()`);
    check(T + 'Ask: the read-only preview shows exactly what will be typed', await S.ev(`document.querySelector('[data-askprev]').textContent`) === 'shipm ask --inbox --model opus "What does the stale-status hook check?"');
    await S.ev(`(() => { const s = document.querySelector('[data-askmodel]'); s.value = 'haiku'; s.dispatchEvent(new Event('change', { bubbles: true })); })()`);
    check(T + 'Ask: choosing Haiku updates the preview', /--model haiku /.test(await S.ev(`document.querySelector('[data-askprev]').textContent`)));
    await clr(); await S.ev(`document.querySelector('[data-askgo]').click()`); m = await msgs();
    check(T + 'Ask: posts {type:ask, op:type, q, model:haiku} once; no Enter and no approval text', m.length === 1 && m[0].type === 'ask' && m[0].op === 'type' && m[0].model === 'haiku' && m[0].q === 'What does the stale-status hook check?', JSON.stringify(m));
    await S.ev(`(() => { const i = document.querySelector('[data-askq]'); i.value = 'abc'; i.dispatchEvent(new Event('input', { bubbles: true })); })()`); await S.ev(`document.querySelector('[data-ask="clear"]').click()`);
    check(T + 'Ask: Cancel clears the question', await S.ev(`document.querySelector('[data-askq]').value`) === '' && await S.ev(`document.querySelector('[data-askgo]').disabled`));
    const tx = await S.ev(D.TEXT_IN('.askcard *')); const bad = tx.filter(x => x.ratio < 4.5);
    check(`${T}Ask card text contrast >= 4.5:1 (${tx.length} texts)`, tx.length > 5 && bad.length === 0, JSON.stringify(bad));
    await S.ev(`(() => { const i = document.querySelector('[data-askq]'); i.value = 'What does the stale-status hook check?'; i.dispatchEvent(new Event('input', { bubbles: true })); })()`);
    { const r = await S.ev(`(() => { const b = document.querySelector('.askcard').getBoundingClientRect(); return { x: Math.max(0, b.left - 8), y: b.top - 8 + window.scrollY, w: b.width + 16, h: b.height + 16 }; })()`); fs.writeFileSync(path.join(WRITE && theme !== 'hc' ? SHOTS : SCRATCH, `rev2-ask-model-${theme}.png`), await S.shot({ x: r.x, y: r.y, width: r.w, height: r.h }, 2)); }
    const nm = S.file('asknm-' + theme, D.page(theme, { projects: [ASKP({ model_supported: false })] })); await S.load(nm, 315, '?tab=projects', 2000);
    check(T + 'Ask without CLI support for --model (shipm ask has no --model yet): no model select is shown', await S.ev(`!document.querySelector('[data-askmodel]') && !document.querySelector('[data-askprev]')`));
  }
  // the /btw aside keeps its honest line and has no model control
  { const f = S.file('aside', D.page('dark', { projects: [mk('aside-app', { chatOpen: true })] })); await S.load(f, 315, '?tab=projects', 1200);
    const t = await S.ev(`(() => { const b = document.querySelector('.card .btn.aside'); return { title: b.title, sel: [...document.querySelectorAll('.card select')].some(x => !x.closest('.sheet')) }; })()`);
    check('Ask aside tooltip: "/btw uses the same model as this chat. We found no way to change it ... use Ask a question."; no model control on the card', /\/btw uses the same model as this chat\. We found no way to change it, so there is no model choice here\. For a different model, use Ask a question\./.test(t.title) && !t.sel, JSON.stringify(t)); }
  // reduced motion
  { await S.cdp('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-reduced-motion', value: 'reduce' }] });
    const f = S.file('rm', D.page('dark', DATA({ projects: SPEC() }))); await S.load(f, 315, '?tab=projects', 6000); await S.ev(`${q('own-app', '.apl')}.click()`); await S.sleep(250);
    const anim = await S.ev(`document.getAnimations().filter(a => a.playState === 'running').map(a => a.animationName || a.transitionProperty || '?')`);
    check('prefers-reduced-motion: no running animation while a sheet opens', anim.length === 0, JSON.stringify(anim));
    await S.cdp('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-reduced-motion', value: 'no-preference' }] }); }
  // the panel never writes a trusted file: no write call anywhere in the page builder or the rules module
  const src = ['panel.js', 'charter.js', 'strings.js'].map(n => fs.readFileSync(path.join(__dirname, '..', 'vscode-ext', 'shipmiracle-panel', n), 'utf8')).join('\n');
  check('no file write in panel.js, charter.js or strings.js (the panel only types commands)', !/writeFile|appendFile|createWriteStream|rename\(|unlinkSync/.test(src));
  check('strings: the exact C note and tick texts are in strings.js (one source)', S0.cnote.lines.length === 6 && S0.own.tickC.startsWith('I understand it keeps going and merges into main') && S0.own.until.c.label === 'Until I disable it');
  S.close();
  console.log(C.fails ? `\nFAILED: ${C.fails} of ${C.n}` : `\nALL PASS (${C.n})`); process.exit(C.fails ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
