// F7 Set aside (UX addendum section 3, acceptance 18) in real headless Chrome: the collapsed "Set aside (n)" list, counts, menu items and their disabled reasons, "Back on the list",
// the Health "Set aside" section, the auto un-aside notice, hostile note text; shown only when the CLI says caps.aside. The panel posts messages only (the extension types the commands).
// 280 / 315 / 360 px, Dark+ / Light+ / High Contrast. Run: node tests/panel_v3_f7_test.js    (skips without Chrome)
require('./shipmiracle_isolation').apply();
const D = require('./panel_cdp');
if (!D.H.available()) { console.log('SKIP no Chrome'); process.exit(0); }
const F = require('./panel_v3_fixtures'), F3 = require('./panel_v3_tab_fixtures');
const C = D.checker(), check = C.check;
const now = Math.floor(Date.now() / 1000), MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const dayOf = ts => { const d = new Date(ts * 1000); return d.getDate() + ' ' + MON[d.getMonth()]; };
const SINCE = now - 9 * 86400;
const aside = (o = {}) => ({ on: false, since: null, note: null, canAside: true, reason: null, backOnList: null, ...o });
const appr = { ...F.STATES.find(s => s.state === 'approval').p };           // waits for the owner: counts in Waiting until it is set aside
const proj = () => [
  F.mk('live-app', 'software', { state: 'working', cr: [F.cr('CR-012', 'RTL fix', 'open', 'do')], aside: aside() }),
  F.mk('busy-ap', 'software', { state: 'working', aside: aside({ canAside: false, reason: 'Not now: autopilot is running.' }) }),
  { ...appr, name: 'wait-app', aside: aside({ canAside: false, reason: 'Not now: wait-app is waiting for you.' }) },
  F.mk('park-one', 'software', { state: 'working', cr: [F.cr('CR-012', 'RTL fix', 'open', 'do')], aside: aside({ on: true, since: SINCE, note: 'waiting for the client' }) }),
  { ...appr, name: 'park-wait', aside: aside({ on: true, since: now - 86400 * 2, note: '<img src=x onerror=alert(1)> "quoted" ' + 'n'.repeat(120) }) },
  F.mk('back-app', 'software', { state: 'working', aside: aside({ on: true, since: SINCE, backOnList: 'back-app started work.' }) }),
  F.mk('nodata-app', 'software', {})
];
const DATA = (o = {}) => ({ projects: proj(), capabilities: { aside: true, toolbox: false, interview: false }, plan: { meters: [] }, ...o });
const card = nm => `[...document.querySelectorAll('.card')].find(c => c.querySelector('.name').textContent === ${JSON.stringify(nm)})`;

(async () => {
  const S = await D.session({ size: '345,900' }); const load0 = S.load; S.load = async (...a) => { try { await S.sleep(260); await S.ev(`sessionStorage.clear()`); } catch (e) { /* first load */ } return load0(...a); };
  const msgs = () => S.ev('JSON.stringify(window.__msgs)').then(JSON.parse).then(a => a.filter(x => x.type !== 'editing'));
  const clr = () => S.ev('window.__msgs.length = 0');
  const load = async (data, theme = 'dark', w = 315, vars) => { await S.load(S.file('f7-' + theme + w, D.page(theme, data, vars)), w, '?tab=projects', 6000); };
  const names = `[...document.querySelectorAll('#pane-projects > .card')].map(c => c.querySelector('.name').textContent)`;

  for (const w of [280, 315, 360]) {
    await load(DATA(), 'dark', w); const T = `[${w}] `;
    check(T + '18 aside projects are not cards in the main list; back-on-list and the others are', JSON.stringify(await S.ev(names)) === JSON.stringify(['live-app', 'busy-ap', 'wait-app', 'back-app', 'nodata-app']), JSON.stringify(await S.ev(names)));
    check(T + '18 the list is ONE collapsed heading "Set aside (2)" with aria-expanded=false and a hidden list', await S.ev(`(() => { const b = document.querySelector('[data-asidetoggle]'); return b.textContent === 'Set aside (2)' && b.getAttribute('aria-expanded') === 'false' && b.getAttribute('aria-controls') === 'aside-list' && document.getElementById('aside-list').hidden; })()`));
    check(T + '18 excluded from Now / Next / Waiting and the tab badge: the approval project that is set aside is not waiting', await S.ev(`(() => { const w = document.querySelector('.nowblk'); const txt = w ? w.textContent : ''; const badge = document.querySelector('#tab-projects i'); return !/park-wait/.test(txt) && /wait-app/.test(txt) && (badge ? badge.textContent.trim() : '0') === '2'; })()`) || await S.ev(`(() => { const b = document.querySelector('#tab-projects i'); return b ? b.textContent : 'none'; })()`));
    check(T + '18 back-on-list shows as a normal card with "Back on the list: back-app started work."', await S.ev(`${card('back-app')}.querySelector('.backl').textContent`) === 'Back on the list: back-app started work.');
    await S.ev(`document.querySelector('[data-asidetoggle]').click()`);
    const rows = await S.ev(`[...document.querySelectorAll('[data-asiderow]')].map(r => ({ n: r.dataset.asiderow, t: r.querySelector('.asrb').textContent.replace(/\\s+/g, ' ').trim(), title: r.querySelector('.asrb').title, aria: r.querySelector('.asrb').getAttribute('aria-label'), bb: r.querySelector('.asbb').textContent, h: r.querySelector('.asrh').getBoundingClientRect().height, hasPrimary: !!r.querySelector('.asrh .primary') }))`);
    check(T + '18 each row: "⏸ name · since 5 Oct", the note as title text, a Bring back button, 26 px high, no primary/strip/chips in the row', rows.length === 2 && rows[0].t === `⏸ park-one · since ${dayOf(SINCE)}` && rows[0].title === 'waiting for the client' && rows[0].bb === 'Bring back' && rows.every(r => r.h >= 26 && !r.hasPrimary) && /set aside since/.test(rows[0].aria), JSON.stringify(rows[0]));
    check(T + '18 hostile note stays text: no element, escaped in the title', await S.ev(`document.querySelectorAll('.asrh img, [data-asiderow] img[src]').length === 0 && !document.querySelector('[onerror]')`));
    check(T + '18 no horizontal scroll', await S.ev(`document.documentElement.scrollWidth <= document.documentElement.clientWidth && document.getElementById('scroll').scrollWidth <= document.getElementById('scroll').clientWidth`));
  }
  await load(DATA());
  await clr(); await S.ev(`document.querySelector('[data-asidetoggle]').click(); document.querySelector('[data-asiderow="park-one"] .asbb').click()`); await wait(100);
  let m = await msgs();
  check('18 Bring back posts {type:"aside", op:"unaside", project} and nothing else', m.length === 1 && JSON.stringify(m[0]) === '{"type":"aside","op":"unaside","project":"park-one"}', JSON.stringify(m));
  await S.ev(`document.querySelector('[data-asiderow="park-one"] .asrb').click()`);
  check('18 clicking the row shows the card for one look (no chat opened)', await S.ev(`!document.querySelector('[data-asiderow="park-one"] .asc').hidden && document.querySelector('[data-asiderow="park-one"] .asrb').getAttribute('aria-expanded') === 'true'`) && (await msgs()).every(x => x.type !== 'open'));
  await S.ev(`document.querySelector('[data-asiderow="park-one"] .asc .card').focus()`); await S.key('Escape', 'Escape', 27); await S.sleep(100);
  check('18 Esc collapses it and focus returns to the row', await S.ev(`document.querySelector('[data-asiderow="park-one"] .asc').hidden && document.activeElement === document.querySelector('[data-asiderow="park-one"] .asrb')`));
  await S.cdp('Page.reload'); await S.sleep(500);
  check('18 the open list survives a redraw (vscode.setState)', await S.ev(`document.querySelector('[data-asidetoggle]').getAttribute('aria-expanded') === 'true' && !document.getElementById('aside-list').hidden`));

  // menu items
  const menu = async nm => S.ev(`[...${card(nm)}.querySelectorAll('.menu .mi')].filter(b => /Set aside|Bring back/.test(b.textContent)).map(b => ({ t: b.textContent.trim(), d: b.disabled, title: b.title, op: b.dataset.aside }))`);
  const a1 = await menu('live-app'), a2 = await menu('busy-ap'), a3 = await menu('wait-app'), a4 = await menu('back-app'), a5 = await menu('nodata-app');
  check('18 card menu: "Set aside" enabled when the CLI says canAside', a1.length === 1 && a1[0].t === 'Set aside' && !a1[0].d && a1[0].op === 'aside', JSON.stringify(a1));
  check('18 disabled with the CLI\'s own reasons: "Not now: autopilot is running." and "Not now: wait-app is waiting for you."', a2[0].d && a2[0].title === 'Not now: autopilot is running.' && a3[0].d && a3[0].title === 'Not now: wait-app is waiting for you.', JSON.stringify([a2, a3]));
  check('18 an aside project that is back on the list offers "Bring back" in its menu; a project without aside data offers nothing', a4.length === 1 && a4[0].t === 'Bring back' && a5.length === 0, JSON.stringify([a4, a5]));
  await clr(); await S.ev(`${card('live-app')}.querySelector('.btn.more').click(); ${card('live-app')}.querySelector('[data-aside="aside"]').click()`); await S.sleep(100);
  m = await msgs(); check('18 Set aside posts {type:"aside", op:"aside", project} and does not open the chat', m.length === 1 && JSON.stringify(m[0]) === '{"type":"aside","op":"aside","project":"live-app"}', JSON.stringify(m));
  await clr(); await S.ev(`${card('busy-ap')}.querySelector('.btn.more').click(); ${card('busy-ap')}.querySelector('[data-aside="aside"]').click()`); await S.sleep(100);
  check('18 a disabled Set aside posts nothing', (await msgs()).length === 0);

  // capability gate
  await load(DATA({ capabilities: { aside: false } }));
  check('18 caps.aside false: no menu item, no list, every project is a normal card (nothing is hidden)', await S.ev(`!document.querySelector('[data-asidetoggle], [data-aside]') && document.querySelectorAll('#pane-projects > .card').length === 7`));

  // Health section + notice
  const h = F3.HEALTH(); h.aside_items = [{ project: 'park-one', kind: 'stage_stuck', title: 'CR step stuck 40 min', id: 'x1' }, { project: 'park-wait', kind: 'cr_orphan', title: '<b>CR</b> open', id: 'x2' }];
  await load(DATA({ health: h, asideNotice: [{ project: 'back-app', why: 'work', ts: now - 60 }, { project: 'x-app', why: 'hard_stop', ts: now - 30 }] }));
  const hs = await S.ev(`(() => { const s = [...document.querySelectorAll('#pane-health .hsec')].find(x => x.querySelector('.hsech') && /Set aside/.test(x.querySelector('.hsech').textContent)); return s ? { head: s.querySelector('.hsech').textContent, rows: [...s.querySelectorAll('.hrow')].map(r => r.querySelector('b').textContent), bb: s.querySelectorAll('[data-aside="unaside"]').length, b: !!s.querySelector('b b') } : null; })()`);
  check('18 Health: "Set aside: 2 silenced" lists each silenced item as "{project}: {title} (not shown elsewhere)" with Bring back; markup stays text', hs && hs.head === 'Set aside: 2 silenced' && hs.rows[0] === 'park-one: CR step stuck 40 min (not shown elsewhere)' && hs.rows[1] === 'park-wait: <b>CR</b> open (not shown elsewhere)' && hs.bb === 2 && !hs.b, JSON.stringify(hs));
  const nt = await S.ev(`[...document.querySelectorAll('.asnote')].map(n => ({ t: n.querySelector('span').textContent, role: n.getAttribute('role'), live: n.getAttribute('aria-live'), b: n.querySelector('button').textContent }))`);
  check('18 auto un-aside notices: "Brought back: back-app started work." / "... hit a hard stop.", role=status, aria-live=polite, dismissible', nt.length === 2 && nt[0].t === 'Brought back: back-app started work.' && nt[1].t === 'Brought back: x-app hit a hard stop.' && nt.every(n => n.role === 'status' && n.live === 'polite' && n.b === 'Dismiss'), JSON.stringify(nt));
  await clr(); await S.ev(`document.querySelector('[data-asidedismiss]').click()`); await S.sleep(80);
  m = await msgs(); check('18 Dismiss posts {type:"aside", op:"dismiss", project, ts} and removes the notice', m.length === 1 && m[0].op === 'dismiss' && m[0].project === 'back-app' && await S.ev(`document.querySelectorAll('.asnote').length`) === 1, JSON.stringify(m));

  // contrast + targets of the new elements in the three themes
  for (const [label, theme] of [['Dark+', 'dark'], ['Light+', 'light'], ['High Contrast', 'hc']]) {
    await load(DATA({ asideNotice: [{ project: 'back-app', why: 'work', ts: now }] }), theme, 315, D.THEMES[theme]); await S.ev(`document.querySelector('[data-asidetoggle]').click()`); await S.sleep(150);
    const tx = await S.ev(D.TEXT_IN('.asideset *, .asnote *, .backl')), bad = tx.filter(x => x.ratio < 4.5);
    const tg = await S.ev(`[...document.querySelectorAll('.asideset button, .asnote button')].filter(b => b.getClientRects().length).map(b => Math.round(b.getBoundingClientRect().height)).filter(h => h < 22)`);
    check(`[${label}] aside list, notice and back-on-list text >= 4.5:1 (${tx.length} elements), targets >= 22 px`, tx.length >= 4 && bad.length === 0 && tg.length === 0, JSON.stringify({ bad: bad.slice(0, 4), tg }));
  }
  S.close();
  console.log(C.fails ? `\nFAILED: ${C.fails} of ${C.n}` : `\nALL PASS (${C.n})`); process.exit(C.fails ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
function wait(ms) { return new Promise(r => setTimeout(r, ms)); }
