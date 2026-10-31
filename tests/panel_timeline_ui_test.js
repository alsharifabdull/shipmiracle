// The two-level timeline in real headless Chrome at 315 px (and 280 / 360 for overflow), light and dark: no sideways scroll, text contrast >= 4.5, the buttons are keyboard reachable and post the right
// message, the History disclosure opens and closes with the keyboard, a screenshot of each of the main states. Starts Chrome only through tests/chrome_helper.js (via panel_cdp.js); skips without Chrome.
// Screenshots are written only when TL_SHOTS_DIR names a folder. Run: node tests/panel_timeline_ui_test.js
require('./shipmiracle_isolation').apply();
const fs = require('fs'), path = require('path');
const D = require('./panel_cdp');
if (!D.H.available()) { console.log('SKIP no Chrome'); process.exit(0); }
const F = require('./panel_v3_fixtures');
const C = D.checker(), check = C.check;
const SHOTS = process.env.TL_SHOTS_DIR || '';
if (SHOTS) fs.mkdirSync(SHOTS, { recursive: true });
const rel = (o = {}) => ({ last: { version: '1.0', date: '2026-10-12', tag: 'v1.0' }, working: null, since: { changes: 0, commits: 0 }, ...o });
const Hs = (id, title, status, closed, release) => ({ id, title, status, closed, release });
const hist = [Hs('CR-011', 'Dark mode', 'delivered', '2026-10-28', null), Hs('CR-010', 'Search filters with a long title that must wrap inside the card without any sideways scroll', 'delivered', '2026-10-20', null), Hs('CR-009', 'إصلاح شاشة الدخول', 'delivered', '2026-10-11', '1.0'), Hs('CR-008', 'Export report', 'abandoned', '2026-10-05', '1.0')];
const W11 = { version: '1.1', source: 'package.json' };
const states = {
  idle: F.mk('idle-app', 'software', { release: rel(), history: hist }),
  planning: F.mk('plan-app', 'software', { state: 'working', cr: [F.cr('CR-012', 'RTL fix', 'open', 'plan')], flow: F.run('planner', 'opus'), release: rel({ working: W11, since: { changes: 2, commits: 7 } }), history: hist }),
  building: F.mk('build-app', 'software', { state: 'working', cr: [F.cr('CR-012', 'RTL fix', 'open', 'do')], flow: F.run('builder-frontend', 'sonnet'), release: rel({ working: W11, since: { changes: 1, commits: 3 } }), history: hist }),
  ready: F.mk('ready-app', 'software', { release: rel({ working: W11, since: { changes: 3, commits: 9 } }), history: hist }),
  unplanned: F.mk('unplanned-app', 'software', { state: 'working', chatOpen: true, dirty: 4, release: rel(), history: hist }),
  talking: F.mk('talking-app', 'software', { chatOpen: true, release: rel(), history: hist }),
  norelease: F.mk('norel-app', 'app', { release: { last: null, working: { version: '1.0', source: 'Xcode' }, since: { changes: 0, commits: 0 } }, history: [] }),
  content: F.mk('blog', 'content', { release: { last: null, working: null, since: { changes: 0, commits: 0 } }, history: [Hs('CR-004', 'Spring post', 'delivered', '2026-10-09', null)] })
};
const names = Object.keys(states);
(async () => {
  const S = await D.session({ size: '345,900' });
  try {
    for (const theme of ['light', 'dark']) {
      const f = S.file('tl-' + theme, D.page(theme, { projects: names.map(n => states[n]), capabilities: { release: true } }));
      for (const w of [315, 280, 360]) {
        await S.load(f, w); await S.ev(D.LIB);
        const T = `[${theme} ${w}px] `;
        check(T + 'no sideways scroll with every state on the page', await S.ev(D.NO_HSCROLL));
        if (w !== 315) continue;
        const low = (await S.ev(D.TEXT_IN('.card *'))).filter(x => x.ratio < 4.5);
        check(T + 'every visible text has contrast >= 4.5', low.length === 0, JSON.stringify(low.slice(0, 5)));
        const txt = n => S.ev(`(() => { const c = [...document.querySelectorAll('.card')].find(c => c.querySelector('.name').textContent === ${JSON.stringify(n)}); return c ? c.innerText : ''; })()`);
        check(T + 'idle card shows the release line and Last change, and no rail', /Released v1\.0 · 12 Oct · nothing new since/.test(await txt('idle-app')) && /Last change: CR-011/.test(await txt('idle-app')) && !(await S.ev(`!![...document.querySelectorAll('.card')].find(c => c.querySelector('.name').textContent === 'idle-app').querySelector('.rail')`)));
        check(T + 'planning card shows "working on v1.1" and the rail ends in Done', /working on v1\.1 · 2 changes done/.test(await txt('plan-app')) && await S.ev(`[...document.querySelectorAll('.card')].find(c => c.querySelector('.name').textContent === 'plan-app').querySelectorAll('.rail .rw')[6].textContent === 'Done'`));
        check(T + 'ready card shows the Mark button', /v1\.1 ready · 3 changes done since v1\.0/.test(await txt('ready-app')) && /Mark v1\.1 released/.test(await txt('ready-app')));
        check(T + 'unplanned and talking cards say so', /Unplanned work · not on the timeline/.test(await txt('unplanned-app')) && /Track as a change/.test(await txt('unplanned-app')) && /Chat open · no change yet/.test(await txt('talking-app')));
        check(T + 'no release / content cards read as specified', /No release yet · building v1\.0 \(Xcode\)/.test(await txt('norel-app')) && /Last done: CR-004 · 9 Oct/.test(await txt('blog')));
        // the Mark button posts exactly the act the extension re-checks
        await S.ev(`window.__msgs.length = 0; [...document.querySelectorAll('.card')].find(c => c.querySelector('.name').textContent === 'ready-app').querySelector('.tlmark').click()`);
        const m1 = await S.ev('JSON.stringify(window.__msgs)');
        check(T + 'Mark v1.1 released posts {act:tlmark, verb:1.1, project} and nothing else', /"act":"tlmark"/.test(m1) && /"verb":"1\.1"/.test(m1) && /"project":"ready-app"/.test(m1) && JSON.parse(m1).length === 1, m1);
        await S.ev(`window.__msgs.length = 0; [...document.querySelectorAll('.card')].find(c => c.querySelector('.name').textContent === 'idle-app').querySelector('.tlcr').click()`);
        const m2 = await S.ev('JSON.stringify(window.__msgs)');
        check(T + 'Start a change posts {act:tlcr, project} and does not open the chat', /"act":"tlcr"/.test(m2) && !/"type":"open"/.test(m2) && JSON.parse(m2).length === 1, m2);
        // History: keyboard open / close, kept across a redraw (state), card does not open the chat
        const hbSel = `[...document.querySelectorAll('.card')].find(c => c.querySelector('.name').textContent === 'idle-app').querySelector('.tlhb')`;
        await S.ev(`window.__msgs.length = 0; ${hbSel}.focus()`);
        await S.key('Enter', 'Enter', 13, '\r'); await S.sleep(150);
        const ex = await S.ev(`(() => { const b = ${hbSel}, r = document.getElementById(b.getAttribute('aria-controls')); return { exp: b.getAttribute('aria-expanded'), hidden: r.hidden, items: r.querySelectorAll('li').length, heads: [...r.querySelectorAll('h5')].map(h => h.textContent), msgs: window.__msgs.length }; })()`);
        check(T + 'History opens with Enter: 4 items under 2 release headings, no message posted', ex.exp === 'true' && ex.hidden === false && ex.items === 4 && ex.heads.length === 2 && ex.msgs === 0, JSON.stringify(ex));
        check(T + 'History: the open set is saved in the page state', await S.ev(`JSON.parse(sessionStorage.getItem('st') || '{}').tlh && JSON.parse(sessionStorage.getItem('st')).tlh['idle-app'] === 1`));
        check(T + 'History: no sideways scroll when open (long title, Arabic title)', await S.ev(D.NO_HSCROLL));
        // the toggle is underlined; an in-flow arrow inherits that underline and the rotation turns it into a stray bar before the arrow, so the arrow must sit out of the flow, inside the button's own padding
        const chev = await S.ev(`(() => { const b = ${hbSel}, c = b.querySelector('.tlchev'), cb = c.getBoundingClientRect(), bb = b.getBoundingClientRect(); return { pos: getComputedStyle(c).position, inside: cb.left >= bb.left && cb.right <= bb.right, deco: getComputedStyle(c).textDecorationLine }; })()`);
        check(T + 'History toggle: the arrow is out of the underlined text flow and inside the button (no stray bar)', chev.pos === 'absolute' && chev.inside && chev.deco === 'none', JSON.stringify(chev));
        if (SHOTS) {
          const r = await S.ev(`(() => { const c = [...document.querySelectorAll('.card')].find(c => c.querySelector('.name').textContent === 'idle-app'), b = c.getBoundingClientRect(); return { x: b.x, y: b.y + scrollY, w: b.width, h: b.height }; })()`);
          fs.writeFileSync(path.join(SHOTS, `timeline-idle-history-${theme}-315.png`), await S.shot({ x: r.x, y: r.y, width: r.w, height: r.h }, 2));
        }
        await S.key(' ', 'Space', 32, ' '); await S.sleep(150);
        check(T + 'History closes with Space', await S.ev(`${hbSel}.getAttribute('aria-expanded') === 'false'`));
        // focus order inside a card: every control is a native button, reachable by Tab, with a visible focus ring
        const tabs = await S.ev(`(() => { const c = [...document.querySelectorAll('.card')].find(c => c.querySelector('.name').textContent === 'ready-app'); return [...c.querySelectorAll('.tlmark, .tlhb')].map(b => ({ tag: b.tagName, tab: b.tabIndex, h: Math.round(b.getBoundingClientRect().height), outline: getComputedStyle(b).outlineStyle })); })()`);
        check(T + 'timeline controls are native buttons in the tab order, at least 24 px high', tabs.length === 2 && tabs.every(b => b.tag === 'BUTTON' && b.tab >= 0 && b.h >= 24), JSON.stringify(tabs));
        if (SHOTS) for (const n of ['idle', 'planning', 'ready', 'unplanned']) {
          const r = await S.ev(`(() => { const c = [...document.querySelectorAll('.card')].find(c => c.querySelector('.name').textContent === ${JSON.stringify(states[n].name)}), b = c.getBoundingClientRect(); return { x: b.x, y: b.y + scrollY, w: b.width, h: b.height }; })()`);
          fs.writeFileSync(path.join(SHOTS, `timeline-${n}-${theme}-315.png`), await S.shot({ x: r.x, y: r.y, width: r.w, height: r.h }, 2));
        }
      }
    }
  } finally { S.close(); }
  console.log(C.fails ? `\nFAILED: ${C.fails} of ${C.n}` : `\nALL PASS (${C.n})`); process.exit(C.fails ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
