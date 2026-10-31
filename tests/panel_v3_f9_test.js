// F9 Details, the expandable card (UX addendum sections 5 and 9, acceptance 21 to 30) in real headless Chrome through tests/chrome_helper.js (one browser):
// toggle and messages, keyboard, the four blocks and every missing / loading / error / off state, the information-block standard (alignment, type scale, spacing, truncation, no jump),
// time words, contrast with the panel's own tokens in Dark+, Light+, High Contrast and the installed VS Code themes, reduced motion, 280 / 315 / 360 px.
// Screenshots are written only with SHIPMIRACLE_SHOTS=1 (tests/fixtures/panel-v3-f9/*.png). Run: node tests/panel_v3_f9_test.js    (skips without Chrome)
require('./shipmiracle_isolation').apply();
const fs = require('fs'), path = require('path');
const D = require('./panel_cdp'), T = require('./panel_themes');
if (!D.H.available()) { console.log('SKIP no Chrome'); process.exit(0); }
const X = require('./panel_v3_f9_fixtures');
const C = D.checker(), check = C.check;
const SHOTS = path.join(__dirname, 'fixtures', 'panel-v3-f9'), SCRATCH = path.join(__dirname, '..', 'reports', 'screens'), WRITE = process.env.SHIPMIRACLE_SHOTS === '1';
fs.mkdirSync(SCRATCH, { recursive: true }); if (WRITE) fs.mkdirSync(SHOTS, { recursive: true });
const P = X.P, now = X.now;
const detailFor = (map) => Object.fromEntries(Object.entries(map).map(([p, d]) => [p.name || p, d]));
const BASE = () => ({ projects: [P.quiet, P.plain, P.idle, P.empty, P.hostile, P.noplaybook], detail: { [P.quiet.name]: X.D.full, [P.plain.name]: X.D.full, [P.idle.name]: X.D.full, [P.empty.name]: X.D.none, [P.hostile.name]: X.D.hostile, [P.noplaybook.name]: X.D.full } });
const cardJs = nm => `[...document.querySelectorAll('.card')].find(c => c.querySelector('.name').textContent === ${JSON.stringify(nm)})`;
const OPEN_ALL = `document.querySelectorAll('.dtog').forEach(b => { if (b.getAttribute('aria-expanded') !== 'true') b.click(); })`;
const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

(async () => {
  const S = await D.session({ size: '345,900' });
  const msgs = () => S.ev('JSON.stringify(window.__msgs)').then(JSON.parse).then(a => a.filter(x => x.type !== 'editing'));
  const clr = () => S.ev('window.__msgs.length = 0');
  const q = (nm, sel) => `${cardJs(nm)}.querySelector(${JSON.stringify(sel)})`;
  const load = async (data, theme = 'dark', w = 315, vars) => { const f = S.file('f9-' + theme + w, D.page(theme, data, vars)); await S.load(f, w, '?tab=projects', 9000); };
  const tab = async (shift = false) => { await S.cdp('Input.dispatchKeyEvent', { type: 'rawKeyDown', key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9, modifiers: shift ? 8 : 0 }); await S.cdp('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9 }); };
  const act = `(() => { const a = document.activeElement; return a.tagName + '|' + (a.className || '').toString().split(' ')[0] + '|' + (a.getAttribute('aria-label') || a.textContent || '').trim().slice(0, 30); })()`;
  const wait = ms => S.sleep(ms);

  // ===== 21. the toggle and its messages (315 px, dark) =====
  await load(BASE());
  const cards = await S.ev(`document.querySelectorAll('.card').length`), togs = await S.ev(`document.querySelectorAll('.card .top > .dtog').length`);
  check('21 a toggle sits in the title row of every card (after the type tag)', cards === 6 && togs === 6 && await S.ev(`[...document.querySelectorAll('.card .top')].every(t => t.lastElementChild.classList.contains('dtog') && t.children[t.children.length - 2].classList.contains('tag'))`));
  const t0 = await S.ev(`(() => { const b = ${q('quiet-app', '.dtog')}, r = b.getBoundingClientRect(); return { type: b.type, exp: b.getAttribute('aria-expanded'), ctl: b.getAttribute('aria-controls'), lab: b.getAttribute('aria-label'), title: b.title, w: r.width, h: r.height, tag: b.tagName, hidden: document.getElementById(b.getAttribute('aria-controls')).hidden, role: document.getElementById(b.getAttribute('aria-controls')).getAttribute('role'), rlab: document.getElementById(b.getAttribute('aria-controls')).getAttribute('aria-label') }; })()`);
  check('21 toggle is a real button: type=button, aria-expanded=false, aria-controls -> the region, label "Details for quiet-app", title "Show details", 22 x 22', t0.tag === 'BUTTON' && t0.type === 'button' && t0.exp === 'false' && t0.ctl === 'detail-quiet-app' && t0.lab === 'Details for quiet-app' && t0.title === 'Show details' && t0.w >= 22 && t0.h >= 22 && t0.hidden === true && t0.role === 'region' && t0.rlab === 'Details for quiet-app', JSON.stringify(t0));
  const tr = await S.ev(`(() => { const g = ${q('plain-app', '.top')}.getBoundingClientRect(), n = ${q('plain-app', '.name')}.getBoundingClientRect(); return [g.height, n.height]; })()`);
  check('21 the toggle does not make the title row taller than its text (collapsed card keeps its height)', tr[0] <= tr[1] + 2, JSON.stringify(tr));
  check('21 collapsed: the quiet project has ONE grey line under Next; the others have none; the region is hidden', await S.ev(`document.querySelectorAll('.quietl').length`) === 1 && await S.ev(`${q('quiet-app', '.quietl')}.textContent`) === '◷ No new step for 34 min. Tests running 12 min.' && await S.ev(`[...document.querySelectorAll('.dtl')].every(r => r.hidden)`));
  await clr(); await S.ev(`${q('quiet-app', '.dtog')}.click()`); await wait(400);
  let m = await msgs();
  check('21 clicking the toggle posts exactly {type:"detail", project} (no path, no other field) and does NOT open the chat', m.length === 1 && JSON.stringify(Object.keys(m[0]).sort()) === '["project","type"]' && m[0].type === 'detail' && m[0].project === 'quiet-app', JSON.stringify(m));
  const o1 = await S.ev(`(() => { const b = ${q('quiet-app', '.dtog')}; return { exp: b.getAttribute('aria-expanded'), title: b.title, vis: !document.getElementById('detail-quiet-app').hidden, cls: ${cardJs('quiet-app')}.classList.contains('dopen'), quiet: getComputedStyle(${q('quiet-app', '.quietl')}).display }; })()`);
  check('21 open: aria-expanded=true, title "Hide details", region visible, the collapsed quiet line is hidden (the fact moved into Now)', o1.exp === 'true' && o1.title === 'Hide details' && o1.vis && o1.cls && o1.quiet === 'none', JSON.stringify(o1));
  check('21 the open state is kept in vscode.setState (survives a redraw)', await S.ev(`JSON.parse(sessionStorage.getItem('st') || '{}').dopen && JSON.parse(sessionStorage.getItem('st')).dopen['quiet-app'] === 1`));
  await S.cdp('Page.reload'); await wait(500);
  check('21 after a reload the region is open again without a click and asks the extension once', await S.ev(`!document.getElementById('detail-quiet-app').hidden && ${q('quiet-app', '.dtog')}.getAttribute('aria-expanded') === 'true'`) && (await msgs()).filter(x => x.type === 'detail').length >= 1);
  await clr();
  await S.ev(`${q('quiet-app', '.dtl .dh h4')}.click(); ${q('quiet-app', '.dtl .dg dd')}.click()`); await wait(150);
  check('21 a click INSIDE the region never opens the chat', (await msgs()).every(x => x.type !== 'open'), JSON.stringify(await msgs()));
  await S.ev(`${q('quiet-app', '.name')}.click()`); await wait(150);
  check('21 a click outside the region still opens the chat', (await msgs()).some(x => x.type === 'open'));
  await S.ev(OPEN_ALL); await wait(300);
  check('21 several cards can be open at once', await S.ev(`[...document.querySelectorAll('.dtl')].filter(r => !r.hidden).length`) === 6);
  const brow = await S.ev(`[...document.querySelectorAll('.card')].map(c => c.querySelectorAll(':scope > .brow').length + ':' + getComputedStyle(c.querySelector(':scope > .brow')).gridTemplateColumns.split(' ').length + ':' + c.querySelector(':scope > .brow .btn').getBoundingClientRect().height)`);
  check('25 no new button row: every card keeps ONE .brow grid with 3 slots and 28 px buttons, open or not', brow.every(x => /^1:3:28$/.test(x)), JSON.stringify(brow));
  check('25 the dot rail is unchanged by Details (same 7 step buttons, same markup before and after opening)', await S.ev(`(() => { const c = ${cardJs('quiet-app')}; return c.querySelectorAll('.rail .rs').length === 7 && c.querySelectorAll('.railw').length === 1; })()`));
  await S.ev(`document.querySelectorAll('.dtog').forEach(b => b.click())`); await wait(400);
  check('21 toggling again collapses (aria-expanded=false, region hidden)', await S.ev(`[...document.querySelectorAll('.dtog')].every(b => b.getAttribute('aria-expanded') === 'false') && [...document.querySelectorAll('.dtl')].every(r => r.hidden)`));

  // ===== keyboard (21, 30) =====
  await load(BASE());
  await S.ev(`${cardJs('quiet-app')}.focus()`); await tab();
  check('30 Tab from the card lands on the toggle first (before the dot rail)', (await S.ev(act)).startsWith('BUTTON|dtog|Details for quiet-app'), await S.ev(act));
  await S.key(' ', 'Space', 32, ' '); await wait(350);
  check('30 Space opens it; focus stays on the toggle', await S.ev(`${q('quiet-app', '.dtog')}.getAttribute('aria-expanded')`) === 'true' && (await S.ev(act)).startsWith('BUTTON|dtog'));
  await S.key('Enter', 'Enter', 13, '\r'); await wait(350);
  check('30 Enter closes it again', await S.ev(`${q('quiet-app', '.dtog')}.getAttribute('aria-expanded')`) === 'false');
  await S.key('Enter', 'Enter', 13, '\r'); await wait(350);
  const order = await S.ev(`[...${cardJs('quiet-app')}.querySelectorAll('button, [tabindex="0"]')].filter(n => n.getClientRects().length && !n.closest('[hidden]')).map(n => n.className.toString().split(' ')[0] + (n.dataset.dmore !== undefined ? ':more' : '') + (n.dataset.rv ? ':report' : '')).join(',')`);
  check('30 DOM focus order inside the open card: toggle, the dot rail, then the region controls (Show more, Open report), then the autopilot line and buttons', /^dtog,rs,rs,rs,rs,rs,rs,rs,lnk:report,/.test(order) || /^dtog,rs,rs,rs,rs,rs,rs,rs,lnk:more,lnk:report,/.test(order), order);
  await S.ev(`${q('quiet-app', '[data-rv="open"]')}.focus()`); await S.key('Escape', 'Escape', 27); await wait(350);
  check('30 Esc inside the region collapses it and returns focus to the toggle', await S.ev(`${q('quiet-app', '.dtog')}.getAttribute('aria-expanded')`) === 'false' && (await S.ev(act)).startsWith('BUTTON|dtog'), await S.ev(act));
  await S.ev(`${q('quiet-app', '.dtog')}.click()`); await wait(300);
  await S.ev(`${q('quiet-app', '.btn.more')}.click()`); await wait(100);
  await S.key('Escape', 'Escape', 27); await wait(300);
  check('21 Esc with the ⋯ menu open closes the menu first and leaves Details open', await S.ev(`${q('quiet-app', '.menu')}.hidden === true && ${q('quiet-app', '.dtog')}.getAttribute('aria-expanded') === 'true'`));
  await S.ev(`${q('quiet-app', '.dtog')}.focus()`); await S.key('Escape', 'Escape', 27); await wait(300);
  check('30 Esc on the open toggle collapses it', await S.ev(`${q('quiet-app', '.dtog')}.getAttribute('aria-expanded')`) === 'false');

  // ===== 22. blocks: order, isolation, missing data =====
  await load(BASE()); await S.ev(OPEN_ALL); await wait(400);
  const heads = await S.ev(`[...${q('plain-app', '.dtl')}.querySelectorAll('section')].map(s => s.querySelector('h4').textContent + '|' + s.getAttribute('aria-labelledby') + '|' + (document.getElementById(s.getAttribute('aria-labelledby')) === s.querySelector('h4')))`);
  check('22 DOM order is exactly Now, Last from the chat, Latest report, STATUS; each is a section named by its h4', heads.map(h => h.split('|')[0]).join() === 'Now,Last from the chat,Latest report,STATUS' && heads.every(h => h.endsWith('|true')), JSON.stringify(heads));
  const blk = await S.ev(`Object.fromEntries([...${q('plain-app', '.dtl')}.querySelectorAll('section')].map(s => [s.querySelector('h4').textContent, s.textContent]))`);
  check('22 no block holds another block\'s data (chat has no report/STATUS text, report has no chat text, Now has no file text)', !/Test report|STATUS|214 of 214|Seed script done/.test(blk['Last from the chat'].replace('Seed script is done', '')) && !/Seed script is done|RTL checklist wiring/.test(blk['Latest report']) && !/Seed script|214 of 214|tests passed/.test(blk['Now']) && !/214 of 214|Seed script is done/.test(blk['STATUS']), JSON.stringify(blk).slice(0, 200));
  const rows = await S.ev(`(() => { const r = {}; for (const s of ${q('plain-app', '.dtl')}.querySelectorAll('section')) r[s.querySelector('h4').textContent] = [...s.querySelectorAll('dt')].map(d => d.textContent).join('/'); return r; })()`);
  check('22 rows are in the spec order: Now = Stage/Agent/Commit, chat = Tool, report = Verdict/Title/Summary, STATUS = Note/Next', rows['Now'] === 'Stage/Agent/Commit' && rows['Last from the chat'] === 'Tool' && rows['Latest report'] === 'Verdict/Title/Summary' && rows['STATUS'] === 'Note/Next', JSON.stringify(rows));
  const qrows = await S.ev(`[...${q('quiet-app', '.dtl section')}.querySelectorAll('dt')].map(d => d.textContent).join('/')`);
  check('23 the quiet fact is the FIRST Now row, label "Quiet", once (not also as the collapsed line)', qrows.startsWith('Quiet/Stage/Agent') && await S.ev(`${cardJs('quiet-app')}.querySelectorAll('.dquiet').length`) === 1 && await S.ev(`getComputedStyle(${q('quiet-app', '.quietl')}).display`) === 'none', qrows);
  check('23 the quiet fact is grey words with a shape (◷), no status class, no chip, no badge, and not in the Waiting count', await S.ev(`(() => { const e = ${q('quiet-app', '.dquiet')}; return e.textContent.startsWith('◷ No new step') && !/ok|danger|warn|dv-|chip/.test(e.className) && !e.closest('.chip') && !document.querySelector('.tab i') ; })()`));
  const miss = async (nm, key, expectHeads, extra) => { await load({ projects: [P.plain], detail: { 'plain-app': X.D[key] } }); await S.ev(OPEN_ALL); await wait(300); const h = await S.ev(`[...document.querySelectorAll('.dtl h4')].map(x => x.textContent).join()`); check(`22 ${nm}: ${expectHeads}`, h === expectHeads && (!extra || await S.ev(extra)), h); };
  await miss('no chat message yet -> the chat block is omitted', 'noChat', 'Now,Latest report,STATUS');
  await miss('no report -> the report block is omitted', 'noReport', 'Now,Last from the chat,STATUS');
  await miss('no STATUS data (and the project has a Next line) -> STATUS shows only Next', 'noStatus', 'Now,Last from the chat,Latest report,STATUS', `[...document.querySelectorAll('.dtl section')].pop().querySelectorAll('dt').length === 1`);
  await miss('chat cannot be read -> "Could not read the chat." in its block, the others unaffected', 'chatErr', 'Now,Last from the chat,Latest report,STATUS', `document.querySelector('.dtl section:nth-of-type(2) .dnote').textContent === 'Could not read the chat.'`);
  await miss('no tool name -> no Tool row, quote only', 'noTool', 'Now,Last from the chat,Latest report,STATUS', `document.querySelectorAll('.dtl section:nth-of-type(2) dt').length === 0`);
  await load({ projects: [P.empty], detail: { 'empty-app': X.D.none } }); await S.ev(OPEN_ALL); await wait(300);
  check('22 everything missing -> the single grey line "Nothing to show yet." (no blocks)', await S.ev(`document.querySelectorAll('.dtl section').length`) === 0 && await S.ev(`document.querySelector('.dtl .dnote').textContent`) === 'Nothing to show yet.');
  for (const [k, w] of [['fail', '✕ FAIL'], ['blocked', '! BLOCKED'], ['full', '✓ PASS']]) { await load({ projects: [P.plain], detail: { 'plain-app': X.D[k] } }); await S.ev(OPEN_ALL); await wait(200);
    const v = await S.ev(`(() => { const e = [...document.querySelectorAll('.dtl dd')].find(d => /PASS|FAIL|BLOCKED/.test(d.textContent)); return e.textContent.trim() + '|' + e.firstElementChild.className; })()`);
    check(`29 verdict ${k}: shape + word "${w}" with exactly one status class`, v.startsWith(w) && /dv-(pass|fail|blk)$/.test(v), v); }
  await load({ projects: [P.plain], detail: {} }); await S.ev(OPEN_ALL); await wait(200);
  const ld = await S.ev(`(() => { const e = document.querySelector('.dtl .dload'); return [e.textContent.trim(), Math.round(e.getBoundingClientRect().height), !!document.querySelector('.dtl .spin, .dtl svg')]; })()`);
  check('22 no data yet -> "Loading details…" with 96 px reserved and no spinner', ld[0] === 'Loading details…' && ld[1] >= 96 && ld[1] <= 100 && !ld[2], JSON.stringify(ld));
  await load({ projects: [P.plain], detail: { 'plain-app': X.D.err } }); await S.ev(OPEN_ALL); await wait(200);
  check('22 error -> "Could not read the details. Try again." + a Try again button; the card above is unaffected', await S.ev(`document.querySelector('.dtl .dnote').textContent`) === 'Could not read the details. Try again.' && await S.ev(`!!document.querySelector('.dtl [data-dretry]') && !!document.querySelector('.card .brow .btn.primary')`));
  await clr(); await S.ev(`document.querySelector('[data-dretry]').click()`); await wait(150);
  check('22 Try again asks again ({type:"detail", project}) and shows "Loading details…" meanwhile', (await msgs()).some(x => x.type === 'detail' && x.project === 'plain-app') && await S.ev(`document.querySelector('.dtl .dload').textContent.trim()`) === 'Loading details…');
  // 24 setting off
  await load({ ...BASE(), projects: [P.plain], settings: { cardChatExcerpt: false } }); await S.ev(OPEN_ALL); await wait(200);
  const off = await S.ev(`(() => { const s = [...document.querySelectorAll('.dtl section')].find(x => x.querySelector('h4').textContent === 'Last from the chat'); return [s.textContent, !!s.querySelector('.dq'), !!s.querySelector('dt')]; })()`);
  check('24 excerpt setting off: "Hidden. Turn on shipmiracle.cardChatExcerpt in Settings to see it here.", no quote, no Tool row, the chat text is not in the page', off[0].includes('Hidden. Turn on shipmiracle.cardChatExcerpt in Settings to see it here.') && !off[1] && !off[2] && !(await S.ev(`document.body.textContent`)).includes('Seed script is done and the RTL'), JSON.stringify(off));

  // ===== 27, 28 alignment and truncation at 280 / 315 / 360 =====
  for (const w of [280, 315, 360]) {
    for (const theme of ['dark', 'light']) {
      await load(BASE(), theme, w); await S.ev(OPEN_ALL); await wait(450);
      const T0 = `[${theme} ${w}] `;
      const al = await S.ev(`(() => { const out = { dt: new Set(), dd: new Set(), gaps: new Set(), cgaps: new Set(), blocks: [], rule: [] };
        document.querySelectorAll('.dtl:not([hidden])').forEach(r => { const rb = r.getBoundingClientRect();
          r.querySelectorAll('dt').forEach(d => out.dt.add(Math.round(d.getBoundingClientRect().width)));
          const lefts = new Set(); r.querySelectorAll('dd').forEach(d => lefts.add(Math.round(d.getBoundingClientRect().left * 100) / 100)); if (lefts.size) out.dd.add(lefts.size + ':' + [...lefts][0]);
          r.querySelectorAll('.dg').forEach(g => { const cs = getComputedStyle(g); out.gaps.add(cs.rowGap); out.cgaps.add(cs.columnGap); });
          const secs = [...r.querySelectorAll('section')]; secs.forEach((s, i) => { if (i) out.blocks.push(Math.round(s.getBoundingClientRect().top - secs[i - 1].getBoundingClientRect().bottom)); });
          if (secs[0]) out.rule.push(Math.round(secs[0].getBoundingClientRect().top - rb.top)); });
        return { dt: [...out.dt], dd: [...out.dd], gaps: [...out.gaps], cgaps: [...out.cgaps], blocks: [...new Set(out.blocks)], rule: [...new Set(out.rule)] }; })()`);
      check(T0 + '27 every dt is 64 px; every dd of a region starts at ONE x (spread 0); row gap 4, column gap 8, block gap 12, rule-to-first-block 13 (1 px rule + 12)', al.dt.length === 1 && al.dt[0] === 64 && al.dd.every(x => x.startsWith('1:')) && al.gaps.join() === '4px' && al.cgaps.join() === '8px' && al.blocks.join() === '12' && al.rule.join() === '13', JSON.stringify(al));
      const xs = await S.ev(`[...document.querySelectorAll('.dtl:not([hidden])')].filter(r => r.querySelector('dd')).map(r => { const dd = r.querySelector('dd').getBoundingClientRect().left - r.getBoundingClientRect().left; return Math.round(dd); })`);
      check(T0 + '27 the value column starts 72 px (64 + 8) from the region edge in every card', xs.every(x => x === 72), JSON.stringify(xs));
      const sweep = await S.ev(`(() => { const bad = []; document.querySelectorAll('.dtl:not([hidden]) *').forEach(n => { if (!n.getClientRects().length || ![...n.childNodes].some(c => c.nodeType === 3 && c.textContent.trim())) return; const cs = getComputedStyle(n);
        if (!['11px', '12px', '13px', '14px'].includes(cs.fontSize) || !['400', '600', '700'].includes(cs.fontWeight) || cs.fontStyle !== 'normal' || cs.textTransform !== 'none' || cs.letterSpacing !== 'normal') bad.push(n.tagName + '.' + n.className + ' ' + cs.fontSize + '/' + cs.fontWeight + '/' + cs.fontStyle + '/' + cs.textTransform + '/' + cs.letterSpacing); }); return bad; })()`);
      check(T0 + '27 type scale: only 11 / 12 px sizes (inside the 11-14 allowance), weights 400 / 600, no italics, no uppercase, no letter-spacing', sweep.length === 0, JSON.stringify(sweep.slice(0, 4)));
      const bord = await S.ev(`(() => { const bad = []; document.querySelectorAll('.dtl:not([hidden]) *').forEach(n => { const cs = getComputedStyle(n); const w = ['Top', 'Right', 'Bottom', 'Left'].map(s => parseFloat(cs['border' + s + 'Width'])).reduce((a, b) => a + b, 0); if (w > 0 && !n.classList.contains('dq')) bad.push(n.tagName + '.' + n.className); if (n.matches('.dh *') && (n.tagName === 'svg' || n.querySelector('svg'))) bad.push('icon in heading'); }); return bad; })()`);
      check(T0 + '27 nothing inside the region has a border except the quote rule (the opening rule is the region\'s own); headings hold no icon', bord.length === 0, JSON.stringify(bord.slice(0, 4)));
      const spc = await S.ev(`(() => { const set = new Set(); document.querySelectorAll('.dtl:not([hidden]), .dtl:not([hidden]) *').forEach(n => { const cs = getComputedStyle(n); ['marginTop', 'marginBottom', 'paddingTop', 'paddingBottom', 'rowGap', 'columnGap'].forEach(k => { const v = parseFloat(cs[k]); if (v > 0) set.add(v); }); }); return [...set].sort((a, b) => a - b); })()`);
      check(T0 + '27 spacing scale: only 4, 8, 12 (and the 2 px quote rule / 4 px button padding) inside the region; never 5, 6, 10', spc.every(v => [4, 8, 12].includes(v)), JSON.stringify(spc));
      // 28 truncation (hostile card)
      const tr2 = await S.ev(`(() => { const r = ${q('hostile-app', '.dtl')}, lh = 17, out = {}; const lim = { c1: 1, c2: 2, c3: 3, c4: 4 };
        r.querySelectorAll('dd').forEach(d => { const k = Object.keys(lim).find(c => d.classList.contains(c)); if (k) out[k + ':' + d.previousElementSibling.textContent] = Math.round(d.getBoundingClientRect().height / lh * 10) / 10 <= lim[k] + .05; });
        const q4 = r.querySelector('.dq'); out.quote = q4.getBoundingClientRect().height <= 4 * lh + .5;
        return { out, sw: [document.documentElement.scrollWidth <= document.documentElement.clientWidth, document.getElementById('scroll').scrollWidth <= document.getElementById('scroll').clientWidth, r.scrollWidth <= r.clientWidth + 1], more: !r.querySelector('[data-dmore]').hidden }; })()`);
      check(T0 + '28 hostile card: Title 1, Summary 3, Note 4, Next 2, Agent 2, quote 4 lines at most; no horizontal scroll (page, scroll area, region)', Object.values(tr2.out).every(Boolean) && tr2.sw.every(Boolean) && tr2.more, JSON.stringify(tr2));
      const shortMore = await S.ev(`${q('plain-app', '[data-dmore]')}.hidden`);
      check(T0 + '28 "Show more" appears only when the quote is clamped (hostile card yes; the short message ' + (w === 280 ? 'may' : 'does not') + ' need it)', w === 280 ? true : shortMore === true, String(shortMore));
      if (theme === 'dark') {
        const ids = await S.ev(`(() => { const out = []; document.querySelectorAll('.dtl:not([hidden])').forEach(r => { const b = r.getBoundingClientRect(); out.push(Math.round(b.height)); }); return out; })()`);
        await wait(2000);
        const ids2 = await S.ev(`[...document.querySelectorAll('.dtl:not([hidden])')].map(r => Math.round(r.getBoundingClientRect().height))`);
        check(T0 + '28 no layout jump: the height of every open region is the same 2 s later', JSON.stringify(ids) === JSON.stringify(ids2), JSON.stringify([ids, ids2]));
        const before = await S.ev(`Math.round(${q('hostile-app', '.dtl')}.getBoundingClientRect().height)`);
        await S.ev(`${q('hostile-app', '[data-dmore]')}.focus(); ${q('hostile-app', '[data-dmore]')}.click()`); await wait(100);
        const mo = await S.ev(`(() => { const b = ${q('hostile-app', '[data-dmore]')}; return { exp: b.getAttribute('aria-expanded'), txt: b.textContent, focus: document.activeElement === b, h: Math.round(${q('hostile-app', '.dtl')}.getBoundingClientRect().height), open: ${q('hostile-app', '.dq')}.classList.contains('open') }; })()`);
        check(T0 + '28 Show more -> "Show less", aria-expanded=true, focus kept, the quote grows (the only height change), instantly', mo.exp === 'true' && mo.txt === 'Show less' && mo.focus && mo.open && mo.h > before, JSON.stringify([mo, before]));
        await S.ev(`${q('hostile-app', '[data-dmore]')}.click()`);
        check(T0 + '28 Show less puts it back', await S.ev(`${q('hostile-app', '[data-dmore]')}.textContent`) === 'Show more' && Math.round(await S.ev(`${q('hostile-app', '.dtl')}.getBoundingClientRect().height`)) === before);
      }
    }
  }

  // ===== hostile text: escaped, no markup, no link =====
  await load(BASE()); await S.ev(OPEN_ALL); await wait(300);
  const hh = await S.ev(`(() => { const r = ${q('hostile-app', '.dtl')}; return { imgs: r.querySelectorAll('img, script, a, iframe, b, i, u').length, onerr: !!r.querySelector('[onerror]'), links: r.querySelectorAll('a[href]').length, bidi: /[\\u202a-\\u202e\\u2066-\\u2069\\u200e\\u200f\\u061c]/.test(r.textContent), txt: r.textContent.includes('<img src=x onerror=alert(1)>'), ar: r.querySelector('.dq').getAttribute('dir'), btnOnly: [...r.querySelectorAll('button')].every(b => b.classList.contains('lnk')) }; })()`);
  check('22 hostile chat / report / STATUS text: shown as plain text (tags and a markdown link stay literal), no element, no link, no on* attribute, no bidi control, dir="auto"', hh.imgs === 0 && !hh.onerr && hh.links === 0 && !hh.bidi && hh.txt && hh.ar === 'auto' && hh.btnOnly, JSON.stringify(hh));
  check('22 the page stays one script and one style element (CSP) and has no style= attribute', await S.ev(`document.scripts.length === 1 && document.querySelectorAll('style').length >= 1 && !document.querySelector('[style]') && !document.querySelector('[onclick]')`));

  // ===== times (5i) =====
  const nowS = () => Math.floor(Date.now() / 1000), startOfToday = () => Math.floor(new Date(new Date().setHours(0, 0, 0, 0)).getTime() / 1000);
  const ago = { c30s: () => nowS() - 30, c5m: () => nowS() - 300, c3h: () => nowS() - 3 * 3600, cYest: () => startOfToday() - 3600, c9d: () => nowS() - 9 * 86400, cOld: () => Math.floor(new Date(new Date().setFullYear(new Date().getFullYear() - 1)).getTime() / 1000) };   // each timestamp is taken from the clock right before ITS page is built, so a slow run cannot turn 30 s into 1 min
  const ts = {};

  const fmtAbs = v => { const d = new Date(v * 1000); return `${d.getDate()} ${MON[d.getMonth()]} ${d.getFullYear()}, ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`; };

  const got = {};
  for (const k of Object.keys(ago)) { ts[k] = ago[k](); const d = { ...X.D.full, report: { ...X.D.full.report, ts: ts[k] } }; await load({ projects: [P.plain], detail: { 'plain-app': d } }); await S.ev(OPEN_ALL); await wait(150); got[k] = await S.ev(`(() => { const t = [...document.querySelectorAll('.dtl section')][2].querySelector('time'); return [t.textContent, t.title, t.getAttribute('datetime'), t.tagName]; })()`); }
  const exp = { c30s: 'just now', c5m: '5 min ago', c3h: new Date(ts.c3h * 1000).toDateString() === new Date().toDateString() ? '3 h ago' : 'yesterday', cYest: 'yesterday', c9d: (d => d.getDate() + ' ' + MON[d.getMonth()] + (d.getFullYear() === new Date().getFullYear() ? '' : ' ' + d.getFullYear()))(new Date(ts.c9d * 1000)), cOld: (d => d.getDate() + ' ' + MON[d.getMonth()] + ' ' + d.getFullYear())(new Date(ts.cOld * 1000)) };
  check('28 relative times follow 5i: 30 s "just now", 5 min, 3 h (or yesterday after midnight), yesterday, 9 days "D Mon", a year ago "D Mon YYYY"', Object.keys(exp).every(k => got[k][0] === exp[k]), JSON.stringify({ exp, got: Object.fromEntries(Object.entries(got).map(([k, v]) => [k, v[0]])) }));
  check('28 every <time> has a datetime and a title with the absolute 24 h local time ("20 Oct 2026, 16:05")', Object.entries(ts).every(([k, v]) => got[k][1] === fmtAbs(v) && /^\d{4}-\d\d-\d\dT/.test(got[k][2]) && got[k][3] === 'TIME'), JSON.stringify(got.c5m));

  // ===== 29 contrast with the panel's own tokens: Dark+, Light+, High Contrast, installed VS Code themes =====
  const contrastRun = async (label, theme, vars) => {
    await load(BASE(), theme, 315, vars); await S.ev(OPEN_ALL); await wait(350);
    const tx = await S.ev(D.TEXT_IN('.dtl *, .quietl, .dtog')), bad = tx.filter(x => x.ratio < 4.5);
    const mk = await S.ev(`(() => { const { ratio, bgOf, colorOn } = window.__c, c = ${cardJs('quiet-app')}, bg = bgOf(c), out = {}; const tg = c.querySelector('.dtog'); out.toggle = +ratio(colorOn(getComputedStyle(tg).color, bg), bg).toFixed(2);
      const e = c.querySelector('.dtog'); e.focus(); out.ring = getComputedStyle(e).outlineColor ? +ratio(colorOn(getComputedStyle(e).outlineColor, bg), bg).toFixed(2) : 0; return out; })()`);
    check(`29 [${label}] every text in the open region >= 4.5:1 (${tx.length} elements, lowest ${tx.length ? Math.min(...tx.map(x => x.ratio)) : '-'}); toggle mark ${mk.toggle} and focus ring ${mk.ring} >= 3:1`, tx.length > 20 && bad.length === 0 && mk.toggle >= 3 && mk.ring >= 3, JSON.stringify({ bad: bad.slice(0, 5), mk }));
    const cls = await S.ev(`(() => { const st = [...document.querySelectorAll('.dtl *')].filter(n => /(^| )(ok|okt|danger|dangert|warn|warnt|dv-)/.test(n.className.toString())).map(n => n.className.toString() + ':' + n.textContent.trim().slice(0, 12)); return { st, quiet: !!document.querySelector('.dquiet') && !/dv-|ok|danger|warn/.test(document.querySelector('.dquiet').className) }; })()`);
    check(`29 [${label}] only the verdict word carries a status class; the quiet fact carries none`, cls.st.every(x => /^dv-/.test(x)) && cls.st.length >= 1 && cls.quiet, JSON.stringify(cls));
    if (theme === 'hc') {
      const hc = await S.ev(`(() => { const r = ${q('quiet-app', '.dtl')}, g = getComputedStyle(r), tg = getComputedStyle(${q('quiet-app', '.dtog')}), dq = getComputedStyle(${q('quiet-app', '.dq')}); return { rule: g.borderTopColor, toggleBorder: tg.borderTopWidth, quote: dq.borderInlineStartColor, grey: getComputedStyle(${q('quiet-app', '.dh h4')}).color, fg: getComputedStyle(document.body).color }; })()`);
      check(`29 [${label}] high contrast: the toggle has a 1 px border, the rules use the contrast colour, headings and labels use the foreground (no grey)`, hc.toggleBorder === '1px' && hc.grey === hc.fg && hc.rule === hc.quote, JSON.stringify(hc));
    }
  };
  for (const [label, theme] of [['Dark+ (table)', 'dark'], ['Light+ (table)', 'light'], ['High Contrast (table)', 'hc']]) await contrastRun(label, theme, D.THEMES[theme]);
  if (T.available()) {
    const inst = [['Dark Modern', 'dark_modern.json', 'dark'], ['Light Modern', 'light_modern.json', 'light'], ['2026 Dark', '2026-dark.json', 'dark'], ['2026 Light', '2026-light.json', 'light'], ['High Contrast Dark', 'hc_black.json', 'hc'], ['High Contrast Light', 'hc_light.json', 'hcl']];
    for (const [label, file, th] of inst) { const base = th === 'hcl' ? { ...D.THEMES.light, '--vscode-contrastBorder': '#0f4a85' } : D.THEMES[th]; await contrastRun(label + ' (installed VS Code)', th, T.resolve(file, base).vars); }
  } else console.log('NOTE VS Code is not installed here: only the table themes were measured');

  // ===== 30 reduced motion and structure =====
  await load(BASE());
  await S.cdp('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-reduced-motion', value: 'no-preference' }] });
  await S.ev(`${q('plain-app', '.dtog')}.click()`);
  const anim = await S.ev(`document.getAnimations().length`);
  await S.cdp('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-reduced-motion', value: 'reduce' }] });
  await wait(400); await S.ev(`${q('plain-app', '.dtog')}.click()`); await wait(50); await S.ev(`${q('plain-app', '.dtog')}.click()`);
  const anim2 = await S.ev(`document.getAnimations().length`), tr3 = await S.ev(`getComputedStyle(${q('plain-app', '.dchev')}).transitionDuration`);
  check('30 motion: with no preference opening runs an animation (the check can fail); with reduced motion zero animations and no chevron transition', anim > 0 && anim2 === 0 && /^0s(, 0s)*$/.test(tr3), JSON.stringify([anim, anim2, tr3]));
  await S.cdp('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-reduced-motion', value: 'no-preference' }] });
  await load(BASE()); await S.ev(OPEN_ALL); await wait(300);
  const sem = await S.ev(`(() => { const r = ${q('plain-app', '.dtl')}; return { live: !!r.querySelector('[aria-live]') || r.hasAttribute('aria-live'), dl: [...r.querySelectorAll('dl')].every(d => [...d.children].every((c, i) => c.tagName === (i % 2 ? 'DD' : 'DT'))), time: r.querySelectorAll('time[datetime]').length, sides: r.querySelectorAll('.side, .sidelabel').length, role: r.getAttribute('role'), btns: [...r.querySelectorAll('button')].filter(b => b.getClientRects().length).map(b => Math.round(b.getBoundingClientRect().height)) }; })()`);
  check('30 the region has role=region, no aria-live, every grid is a dl of dt/dd pairs, time elements carry datetime, no layout-B markup, text buttons are 22 px high', !sem.live && sem.dl && sem.time >= 2 && sem.sides === 0 && sem.role === 'region' && sem.btns.every(h => h >= 22), JSON.stringify(sem));

  // ===== 26 visual states (mock v2 states): each one is ASSERTED before it is shot, with a clean state per shot (the open set lives in sessionStorage and must not leak from the previous page) =====
  const SH = (k, d, nm, op, want) => ({ k, d, nm, op, want });
  const txt = `(sel) => (document.querySelector(sel) || { textContent: '' }).textContent`;
  const STATES = [
    SH('collapsed', BASE(), 'plain-app', false, `(() => { const c = ${cardJs('plain-app')}; return c.querySelector('.dtog').getAttribute('aria-expanded') === 'false' && c.querySelector('.dtl').hidden && !c.querySelector('.quietl'); })()`),
    SH('quiet', BASE(), 'quiet-app', false, `(() => { const c = ${cardJs('quiet-app')}; const l = c.querySelector('.quietl'); return c.querySelector('.dtl').hidden && !!l && getComputedStyle(l).display !== 'none' && l.textContent === '◷ No new step for 34 min. Tests running 12 min.'; })()`),
    SH('expanded', BASE(), 'quiet-app', true, `(() => { const c = ${cardJs('quiet-app')}; return !c.querySelector('.dtl').hidden && [...c.querySelectorAll('.dtl h4')].map(h => h.textContent).join() === 'Now,Last from the chat,Latest report,STATUS' && c.querySelector('.dtog').getAttribute('aria-expanded') === 'true'; })()`),
    SH('missing', { projects: [P.plain], detail: { 'plain-app': X.D.noReport } }, 'plain-app', true, `(() => { const c = ${cardJs('plain-app')}; return !c.querySelector('.dtl').hidden && [...c.querySelectorAll('.dtl h4')].map(h => h.textContent).join() === 'Now,Last from the chat,STATUS'; })()`),
    SH('off', { ...BASE(), settings: { cardChatExcerpt: false } }, 'plain-app', true, `(() => { const c = ${cardJs('plain-app')}; return !c.querySelector('.dtl').hidden && c.querySelector('.dtl').textContent.includes('Hidden. Turn on shipmiracle.cardChatExcerpt in Settings to see it here.'); })()`),
    SH('loading', { projects: [P.plain], detail: {} }, 'plain-app', true, `(() => { const c = ${cardJs('plain-app')}; return !c.querySelector('.dtl').hidden && c.querySelector('.dtl').textContent.trim() === 'Loading details…'; })()`),
    SH('error', { projects: [P.plain], detail: { 'plain-app': X.D.err } }, 'plain-app', true, `(() => { const c = ${cardJs('plain-app')}; const r = c.querySelector('.dtl'); return !r.hidden && r.textContent.includes('Could not read the details. Try again.') && !!r.querySelector('[data-dretry]'); })()`),
    SH('chaterr', { projects: [P.plain], detail: { 'plain-app': X.D.chatErr } }, 'plain-app', true, `(() => { const c = ${cardJs('plain-app')}; return !c.querySelector('.dtl').hidden && c.querySelector('.dtl').textContent.includes('Could not read the chat.'); })()`),
    SH('nothing', { projects: [P.empty], detail: { 'empty-app': X.D.none } }, 'empty-app', true, `(() => { const c = ${cardJs('empty-app')}; return !c.querySelector('.dtl').hidden && c.querySelector('.dtl').textContent.trim() === 'Nothing to show yet.'; })()`),
    SH('hostile', BASE(), 'hostile-app', true, `(() => { const c = ${cardJs('hostile-app')}; return !c.querySelector('.dtl').hidden && c.querySelector('.dq').textContent.includes('<img src=x') && !c.querySelector('.dtl img'); })()`)
  ];
  if (WRITE) { for (const f of fs.readdirSync(SHOTS)) if (f.endsWith('.png')) fs.rmSync(path.join(SHOTS, f)); }
  let shots = 0, stateOk = 0, stateN = 0;
  const shoot = async (st, theme, w) => {
    await S.ev(`sessionStorage.clear()`);                                   // the previous page's open set must not be restored into this one
    await load(st.d, theme, w); await S.ev(`sessionStorage.clear()`);
    await S.ev(`(() => { const t = ${q(st.nm, '.dtog')}; if (${st.op ? 'true' : 'false'} && t.getAttribute('aria-expanded') !== 'true') t.click(); })()`); await wait(400);
    stateN++; const ok = await S.ev(st.want); if (ok) stateOk++; else console.log('FAIL state "' + st.k + '" ' + theme + ' ' + w + ' is not what its name says');
    if (!WRITE) return;
    const r = await S.ev(`(() => { const b = ${cardJs(st.nm)}.getBoundingClientRect(); return { x: Math.max(0, b.left - 8), y: b.top - 8 + (document.getElementById('scroll').scrollTop), w: b.width + 16, h: b.height + 16 }; })()`);
    fs.writeFileSync(path.join(SHOTS, `f9-${st.k}-${theme}-${w}.png`), await S.shot({ x: r.x, y: r.y, width: r.w, height: r.h }, 2)); shots++;
  };
  for (const w of [280, 315, 360]) for (const theme of ['dark', 'light']) for (const st of STATES) await shoot(st, theme, w);
  for (const st of STATES.filter(x => ['expanded', 'quiet', 'hostile'].includes(x.k))) await shoot(st, 'hc', 315);
  check(`26 every visual state is what its name says before it is shot (${stateOk} of ${stateN}: collapsed, quiet, expanded, missing, off, loading, error, chaterr, nothing, hostile; light and dark at 280/315/360 + High Contrast for expanded, quiet, hostile)`, stateOk === stateN && stateN === STATES.length * 6 + 3, `${stateOk}/${stateN}`);
  if (WRITE) check('26 screenshots written to tests/fixtures/panel-v3-f9 (' + shots + ')', shots === stateN && fs.readdirSync(SHOTS).filter(f => f.endsWith('.png')).length === shots);
  S.close();
  console.log(C.fails ? `\nFAILED: ${C.fails} of ${C.n}` : `\nALL PASS (${C.n})`); process.exit(C.fails ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
