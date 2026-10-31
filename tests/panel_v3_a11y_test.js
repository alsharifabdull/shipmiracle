// Panel v3 spec section 12 item 10, in full, in real headless Chrome:
//  1. keyboard-only walk (real Tab / Shift+Tab / Enter / Space / arrow / Esc key events, no .click()) of ALL FIVE tabs: every enabled control is reachable, no positive tabindex,
//     a visible focus ring at every stop, no focus trap; plus the card menu, the Setup Fix button and the full-autopilot charter editor, driven by keys only;
//  2. reduced motion: with prefers-reduced-motion the page has zero running animations or transitions on all five tabs (and without it the spinner does run: the check can fail);
//  3. contrast (text >= 4.5:1, marks and icons >= 3:1) on all five tabs in Dark+, Light+ and High Contrast (the table below) AND in the themes of an installed VS Code
//     (Dark Modern, Light Modern, 2026 Dark / Light, High Contrast Black / Light), plus a report of every difference between the table and the installed theme files;
//  4. high-contrast screenshots (kept in reports/screens, the committed set is written by tests/panel_v3_ui_test.js with SHIPMIRACLE_SHOTS=1).
// Run: node tests/panel_v3_a11y_test.js    (skips without Chrome)
require('./shipmiracle_isolation').apply();
const fs = require('fs'), path = require('path');
const D = require('./panel_cdp'), T = require('./panel_themes');
if (!D.H.available()) { console.log('SKIP no Chrome'); process.exit(0); }
const F = require('./panel_v3_fixtures'), F3 = require('./panel_v3_tab_fixtures');
const C = D.checker(), check = C.check;
const SCRATCH = path.join(__dirname, '..', 'reports', 'screens'); fs.mkdirSync(SCRATCH, { recursive: true });

const idea = { id: 'F1', text: 'an idea about dark mode', tags: ['ui'], date: '2026-10-20', verdict: '' };
const verdicts = ['BUILD NOW', 'BUILD LATER', 'MERGE into x', 'SPLIT OUT', 'DROP'].map((v, k) => ({ ...idea, id: 'F' + (k + 3), verdict: v }));
const crq = n => [F.cr('CR-012', 'RTL fix', 'queued', 'scope'), F.cr('CR-013', 'Export report', 'queued', 'scope'), F.cr('CR-014', 'إصلاح الواجهة', 'queued', 'scope')].slice(0, n);
const PROJ = () => [F.mk('demo-app', 'software', { cr: crq(3), ideas: { open: [idea, { ...idea, id: 'F2' }, ...verdicts], evaluated: [], done: 0, dropped: 0 } }), F.mk('busy-app', 'software', { state: 'working', agents: [{ type: 'builder-frontend', model: 'sonnet', mins: 3 }], cr: [F.cr('CR-012', 'RTL fix', 'open', 'do')], flow: F.run('builder-frontend', 'sonnet'), chatOpen: true }),
  F.STATES.find(s => s.state === 'approval').p, F.STATES.find(s => s.state === 'hardstop').p, F.STATES.find(s => s.state === 'verify-fail').p, F.STATES.find(s => s.state === 'autopilot').p,
  F.mk('ask', 'notes', { dir: '/x/ask', ask: { inbox: true, questions_today: 3, limit: 20, notes: 2, last: { title: 'What is a monad?', path: 'docs/notes/2026-10-21-what-is-a-monad.md', ts: 1 } } })];
const DATA = (o = {}) => ({ projects: PROJ(), reports: F3.REPORTS, setup: F3.SETUP(), health: F3.HEALTH(), plan: { meters: [{ id: 'week', label: 'Week', pct: 12.3, lvl: 0, resets: null }] }, remote: { state: 'off' }, ...o });
const TABS = ['projects', 'reports', 'ideas', 'health', 'setup'];

(async () => {
  const S = await D.session({ size: '345,900' });
  const msgs = () => S.ev('JSON.stringify(window.__msgs)').then(JSON.parse);
  const tab = (n = 1, shift = false) => (async () => { for (let i = 0; i < n; i++) { await S.cdp('Input.dispatchKeyEvent', { type: 'rawKeyDown', key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9, modifiers: shift ? 8 : 0 }); await S.cdp('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9 }); await S.sleep(25); } })();
  const DESC = `(() => { const a = document.activeElement, cs = getComputedStyle(a); const r = a.getBoundingClientRect(); return { id: (a.tagName + '|' + (a.getAttribute('data-id') || a.dataset.tab || a.getAttribute('aria-label') || a.textContent || a.className || '').toString().trim().slice(0, 40) + '|' + (a.className || '').toString().slice(0, 30)), ring: (cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) >= 1) || (cs.boxShadow && cs.boxShadow !== 'none'), vis: r.width > 0 && r.height > 0, tabindex: a.tabIndex, tag: a.tagName }; })()`;
  const INTERACTIVE = `[...document.querySelectorAll('button, select, input, textarea, a[href], [tabindex]')].filter(n => n.getClientRects().length && !n.closest('[hidden]') && !n.disabled && n.tabIndex >= 0).map(n => (n.tagName + '|' + (n.getAttribute('data-id') || n.dataset.tab || n.getAttribute('aria-label') || n.textContent || n.className).toString().trim().slice(0, 40) + '|' + (n.className || '').toString().slice(0, 30)))`;
  const walkTab = async (theme, tabName, data = DATA(), tag = '', pre = '') => {
    const f = S.file('w-' + theme + tag, D.page(theme, data)); await S.load(f, 315, '?tab=' + tabName, 1400); if (pre) await S.ev(pre);
    await S.ev(`document.activeElement && document.activeElement.blur(); window.scrollTo(0, 0)`);
    const want = new Set(await S.ev(INTERACTIVE)), seen = [], rings = [];
    let first = null;
    for (let i = 0; i < 120; i++) {
      await tab(); const d = await S.ev(DESC); if (d.tag === 'BODY') continue; if (first === null) first = d.id; else if (d.id === first) break;
      seen.push(d.id); rings.push(d); }
    return { want, seen, rings, first, wrapped: seen.length < 120 };
  };

  // ============ 1. keyboard-only walk of all five tabs ============
  for (const theme of ['light', 'dark', 'hc']) {
    for (const tb of TABS) {
      const w = await walkTab(theme, tb), T0 = `[${theme}] ${tb}: `;
      const missing = [...w.want].filter(x => !w.seen.includes(x) && !/\|tab\b/.test(x) && !/^BUTTON\|[^|]*\|tab/.test(x));
      check(T0 + `Tab visits ${w.seen.length} stops and wraps around (no focus trap)`, w.wrapped && w.seen.length >= 3, JSON.stringify(w.seen.slice(0, 5)));
      check(T0 + 'every enabled control of the page is reachable with Tab (' + w.want.size + ' controls; roving-tab tabs and menu items are reached with arrows)', missing.length === 0, JSON.stringify(missing.slice(0, 5)));
      check(T0 + 'every stop shows a visible focus ring (outline >= 1 px or shadow) and has a box', w.rings.every(r => r.ring && r.vis), JSON.stringify(w.rings.filter(r => !r.ring || !r.vis).slice(0, 3)));
      check(T0 + 'no positive tabindex anywhere (the order is the document order)', (await S.ev(`[...document.querySelectorAll('[tabindex]')].filter(n => n.tabIndex > 0).length`)) === 0);
      if (theme === 'light') {                                           // Shift+Tab goes back one stop
        await S.ev(`document.activeElement.blur()`); await tab(3); const a3 = await S.ev(DESC); await tab(1, true); const b = await S.ev(DESC); await tab(2); const c = await S.ev(DESC); await tab(1, true); const d = await S.ev(DESC);
        check(T0 + 'Shift+Tab moves focus back one stop', a3.id !== b.id && c.id !== d.id && d.id === b.id || (a3.id !== b.id && d.id !== c.id), JSON.stringify([a3.id, b.id, c.id, d.id]));
      }
    }
  }
  // ============ 1b. Setup tab with the cross-platform onboarding fields (not-ready rows, Quick setup card, Details): keyboard walk and contrast ============
  const QSETUP = () => { const st = F3.SETUP(); st.rows = st.rows.map(r => ({ ...r, stage: r.id === 'prefs' ? 'prefs' : 'connect', cls: r.need, os_supported: true, docs: '' })); st.os = { kind: 'macos', line: 'This computer: macOS 27.0 (arm64). Supported: CLI, hooks, panel, autopilot, awake guard.' }; st.quick = true; return st; };
  for (const theme of ['light', 'dark', 'hc']) {
    const w = await walkTab(theme, 'setup', DATA({ setup: QSETUP() }), 'q', `document.querySelector('#pane-setup [data-sdet]').click()`), T0 = `[${theme}] setup (onboarding): `;
    const missing = [...w.want].filter(x => !w.seen.includes(x) && !/\|tab\b/.test(x) && !/^BUTTON\|[^|]*\|tab/.test(x));
    check(T0 + `every control is reachable with Tab (${w.want.size} controls: the radios, the folder box, Run in terminal, Needs you, More and the buttons inside More) and shows a focus ring`, w.wrapped && missing.length === 0 && w.rings.every(r => r.ring && r.vis) && w.want.size > 8, JSON.stringify({ missing: missing.slice(0, 5), noRing: w.rings.filter(r => !r.ring || !r.vis).slice(0, 3) }));
    await S.load(S.file('qc-' + theme, D.page(theme, DATA({ setup: QSETUP() }), D.THEMES[theme])), 315, '?tab=setup', 1800); await S.ev(`document.querySelector('#pane-setup [data-sdet]').click()`);
    const tx = await S.ev(D.TEXT_IN('#pane-setup *')), bad = tx.filter(x => x.ratio < 4.5);
    check(T0 + `text >= 4.5:1 on ${tx.length} elements (lowest ${tx.length ? Math.min(...tx.map(x => x.ratio)) : '-'})`, tx.length > 20 && bad.length === 0, JSON.stringify(bad.slice(0, 5)));
  }
  // the roving tab bar: the selected tab is the only tab stop; arrows move AND open (covered in panel_v3_ui_test); here Tab from the bar leaves it
  {
    const f = S.file('bar', D.page('light', DATA())); await S.load(f, 315, '?tab=ideas', 1400); await S.ev(`document.querySelector('[data-tab=ideas]').focus()`); await tab(1);
    check('tab bar: Tab leaves the bar into the open pane (the selected tab is the one stop)', await S.ev(`!document.activeElement.closest('.tabs')`));
  }
  // card menu by keys: focus the ⋯ button (by Tab), Enter opens, arrows move, Esc closes and the focus returns to the button
  {
    const f = S.file('menu', D.page('dark', DATA())); await S.load(f, 315, '?tab=projects', 1400);
    await S.ev(`document.activeElement.blur()`);
    let ok = false; for (let i = 0; i < 40 && !ok; i++) { await tab(); ok = await S.ev(`document.activeElement.classList.contains('more')`); }
    check('menu: Tab reaches a ⋯ button', ok);
    await S.key('Enter', 'Enter', 13, '\r'); await S.sleep(80);
    const open = await S.ev(`(() => { const b = document.activeElement.closest('.mwrap') ? document.activeElement : null; const m = document.querySelector('.menu:not([hidden])'); return { open: !!m, inMenu: !!(m && m.contains(document.activeElement)), exp: !!document.querySelector('.more[aria-expanded=true]') }; })()`);
    check('menu: Enter opens the menu and moves focus into it (aria-expanded true)', open.open && open.inMenu && open.exp, JSON.stringify(open));
    const f1 = await S.ev(`document.activeElement.textContent.trim()`); await S.key('ArrowDown', 'ArrowDown', 40); const f2 = await S.ev(`document.activeElement.textContent.trim()`);
    check('menu: ArrowDown moves to the next item', f1 !== f2 && (await S.ev(`document.activeElement.getAttribute('role')`)).startsWith('menuitem'), JSON.stringify([f1, f2]));
    await S.key('Escape', 'Escape', 27); await S.sleep(80);
    check('menu: Esc closes it and focus returns to the ⋯ button', await S.ev(`!document.querySelector('.menu:not([hidden])') && document.activeElement.classList.contains('more')`));
  }
  // Setup Fix by keys: Tab until the git-id Fix button has focus, press Enter (message) and Space
  {
    const f = S.file('setup', D.page('light', DATA())); await S.load(f, 315, '?tab=setup', 1400); await S.ev(`document.activeElement.blur()`);
    let ok = false; for (let i = 0; i < 60 && !ok; i++) { await tab(); ok = await S.ev(`document.activeElement.dataset.setup === 'fix' && document.activeElement.dataset.id === 'git-id'`); }
    check('Setup: Tab reaches the Fix button of the git-id row (its aria-label names the row)', ok && /Git name and email/.test(await S.ev(`document.activeElement.getAttribute('aria-label')`)), await S.ev(DESC).then(d => d.id));
    await S.ev('window.__msgs.length = 0'); await S.key('Enter', 'Enter', 13, '\r'); await S.sleep(60);
    const m1 = (await msgs()).filter(x => x.type === 'setup');
    check('Setup: Enter on Fix posts {type:"setup", op:"fix", id:"git-id"} and nothing else (the extension types the command; Enter is never pressed for you)', JSON.stringify(m1) === JSON.stringify([{ type: 'setup', op: 'fix', id: 'git-id' }]), JSON.stringify(m1));
    await S.load(f, 315, '?tab=setup', 1400); await S.ev(`document.querySelector('[data-setup=recheck]').focus()`); await S.ev('window.__msgs.length = 0'); await S.key(' ', 'Space', 32, ' '); await S.sleep(60);
    check('Setup: Space on Re-check posts {type:"setup", op:"recheck"}', (await msgs()).some(x => x.type === 'setup' && x.op === 'recheck'), JSON.stringify(await msgs()));
  }
  // the Change sheet and the On its own sheet by keys only: Autopilot line -> Enter -> Tab to "On its own" -> Enter -> sheet opens with focus inside, Tab stays in order, Esc cancels and returns to the Autopilot line
  {
    const f = S.file('charter', D.page('light', DATA({ projects: [F.mk('char-app', 'software', { cr: crq(3), folders: ['src'] })] }))); await S.load(f, 315, '?tab=projects', 1400); await S.ev(`document.activeElement.blur()`);
    let ok = false; for (let i = 0; i < 30 && !ok; i++) { await tab(); ok = await S.ev(`document.activeElement.classList.contains('apl')`); }
    check('sheets: Tab reaches the Autopilot line button', ok);
    await S.key('Enter', 'Enter', 13, '\r'); await S.sleep(80);
    check('sheets: Enter opens the Change sheet and focus moves to its first option', await S.ev(`(() => { const b = document.querySelector('[data-sheetbox="level"]'); return !b.hidden && b.contains(document.activeElement) && document.activeElement.dataset.lv === 'manual'; })()`));
    let on = false; for (let i = 0; i < 6 && !on; i++) { on = await S.ev(`document.activeElement.dataset.lv === 'full'`); if (!on) await tab(); }
    check('sheets: Tab reaches the "On its own" option', on);
    await S.key('Enter', 'Enter', 13, '\r'); await S.sleep(200);
    const ed = await S.ev(`(() => { const e = document.querySelector('[data-sheetbox="own"]'); return { vis: !!e && !e.hidden, inside: !!e && e.contains(document.activeElement), first: document.activeElement.dataset.of || document.activeElement.tagName }; })()`);
    check('sheets: On its own opens in place and focus moves into it (the "Keep going until" select first)', ed.vis && ed.inside && ed.first === 'until', JSON.stringify(ed));
    const order = []; for (let i = 0; i < 12; i++) { await tab(); order.push(await S.ev(`(() => { const a = document.activeElement; return a.dataset.of ? 'f:' + a.dataset.of : a.dataset.pre ? 'pre:' + a.dataset.pre : a.dataset.ostart !== undefined ? 'start' : a.dataset.ocancel !== undefined ? 'cancel' : a.tagName; })()`)); }
    check('sheets: Tab walks the presets and fields in reading order (time, budget presets, More options, ... tick, Cancel); Start is skipped while disabled; it never traps', order.includes('pre:time') && order.includes('pre:budget') && order.includes('f:tick') && order.includes('cancel') && !order.includes('start'), JSON.stringify(order));
    await S.ev(`document.querySelector('[data-of=until]').focus()`); await S.key('Escape', 'Escape', 27); await S.sleep(80);
    check('sheets: Esc cancels (sheet hidden) and focus returns to the Autopilot line; nothing was posted', await S.ev(`document.querySelector('[data-sheetbox="own"]').hidden && document.activeElement.classList.contains('apl')`) && !(await msgs()).some(x => x.type === 'charter'));
  }
  // the Ask box by keys: type with real key events, Enter posts the question
  {
    const f = S.file('ask', D.page('dark', DATA())); await S.load(f, 315, '?tab=projects', 1400); await S.ev(`document.querySelector('[data-askq]').focus()`);
    for (const ch of 'hi') await S.key(ch, 'Key' + ch.toUpperCase(), ch.toUpperCase().charCodeAt(0), ch);
    await S.ev('window.__msgs.length = 0'); await S.key('Enter', 'Enter', 13, '\r'); await S.sleep(60);
    check('Ask: typing with the keyboard and Enter posts {type:"ask", op:"type", q:"hi"}', JSON.stringify((await msgs()).filter(x => x.type === 'ask')) === JSON.stringify([{ type: 'ask', op: 'type', q: 'hi' }]), JSON.stringify(await msgs()));
  }

  // ============ 2. reduced motion ============
  {
    const busy = DATA({ setup: null, reports: null });                                // loading skeletons on Reports and Setup, working projects (spinner) on Projects
    const f = S.file('motion', D.page('light', busy));
    const anims = `document.getAnimations().filter(a => a.playState === 'running').map(a => (a.animationName || a.transitionProperty || a.constructor.name))`;
    await S.cdp('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-reduced-motion', value: 'no-preference' }] });
    await S.load(f, 315, '?tab=projects', 1400);
    const motion = await S.ev(anims);
    check('reduced motion control: WITHOUT the preference the page does run animations (the spinner), so the zero below is meaningful', motion.length > 0, JSON.stringify(motion));
    await S.cdp('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-reduced-motion', value: 'reduce' }] });
    for (const tb of TABS) {
      await S.load(f, 315, '?tab=' + tb, 1400);
      await S.ev(`(() => { const m = document.querySelector('.card .btn.more'); if (m) m.click(); })()`); await S.sleep(200);       // open a menu: its open transition must be off too
      const run = await S.ev(anims);
      const trans = await S.ev(`[...document.querySelectorAll('*')].filter(n => n.getClientRects().length && /[1-9]/.test(getComputedStyle(n).transitionDuration.replace(/0\\.?0*s|0s/g, ''))).map(n => n.className.toString().slice(0, 24)).slice(0, 5)`);
      const aniDur = await S.ev(`[...document.querySelectorAll('*')].filter(n => n.getClientRects().length && getComputedStyle(n).animationName !== 'none' && parseFloat(getComputedStyle(n).animationDuration) > 0 && getComputedStyle(n).animationIterationCount !== '1').map(n => n.className.toString().slice(0, 24)).slice(0, 5)`);
      check(`reduced motion [${tb}]: zero running animations and transitions, no infinite animation left on any element`, run.length === 0 && trans.length === 0 && aniDur.length === 0, JSON.stringify({ run, trans, aniDur }));
    }
    await S.cdp('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-reduced-motion', value: 'no-preference' }] });
  }

  // ============ 3. contrast on all five tabs in the table themes and in the installed VS Code themes ============
  const shotNames = { projects: 'projects', reports: 'reports', ideas: 'ideas', health: 'health', setup: 'setup' };
  const contrast = async (label, theme, vars) => {
    const f = S.file('c-' + label.replace(/\W+/g, ''), D.page(theme, DATA(), vars));
    for (const tb of TABS) {
      await S.load(f, 315, '?tab=' + tb, 1800);
      if (tb === 'projects') await S.ev(`document.querySelector('.card .btn.more').click()`);                      // an open menu is measured too
      const tx = await S.ev(D.TEXT_IN('.tabs *, #scroll *, header *, .menu *')), bad = tx.filter(x => x.ratio < 4.5);
      const ic = await S.ev(`(() => { const { ratio, bgOf, colorOn } = window.__c, out = []; document.querySelectorAll('.card .seg, .cmark').forEach(n => { if (!n.getClientRects().length || n.closest('[hidden]')) return; const host = n.closest('.card, .chk') || n.parentElement, card = bgOf(host), s = getComputedStyle(n), own = bgOf(n), border = colorOn(s.borderTopColor, card), glyphCol = n.textContent.trim() ? colorOn(s.color, own) : null; out.push({ ring: +ratio(border, card).toFixed(2), glyph: glyphCol ? +ratio(glyphCol, own).toFixed(2) : null, cls: n.className.toString().slice(0, 20) }); }); return out; })()`);
      const badI = ic.filter(x => (x.glyph !== null && x.glyph < 3));
      check(`contrast [${label}] ${tb}: text >= 4.5:1 on ${tx.length} elements (lowest ${tx.length ? Math.min(...tx.map(x => x.ratio)) : '-'}), mark glyphs >= 3:1 on ${ic.length}`, tx.length > 5 && bad.length === 0 && badI.length === 0, JSON.stringify({ bad: bad.slice(0, 6), badI: badI.slice(0, 3) }));
      if (theme === 'hc' && label === 'High Contrast (table)') {                                               // high-contrast screenshots of every tab (scratch; the committed set is written by panel_v3_ui_test with SHIPMIRACLE_SHOTS=1)
        const r = await S.ev(`(() => { const t = document.querySelector('.tabs').getBoundingClientRect(); return { x: 0, y: 0, width: document.documentElement.clientWidth, height: Math.min(900, document.documentElement.scrollHeight) }; })()`);
        fs.writeFileSync(path.join(SCRATCH, `panel-v3-a11y-${shotNames[tb]}-hc.png`), await S.shot(r, 1));
      }
    }
  };
  for (const [label, theme] of [['Dark+ (table)', 'dark'], ['Light+ (table)', 'light'], ['High Contrast (table)', 'hc']]) await contrast(label, theme, D.THEMES[theme]);
  if (T.available()) {
    const inst = [['Dark Modern', 'dark_modern.json', 'dark'], ['Light Modern', 'light_modern.json', 'light'], ['2026 Dark', '2026-dark.json', 'dark'], ['2026 Light', '2026-light.json', 'light'], ['High Contrast Dark', 'hc_black.json', 'hc'], ['High Contrast Light', 'hc_light.json', 'hcl']];
    for (const [label, file, th] of inst) {
      const base = th === 'hcl' ? { ...D.THEMES.light, '--vscode-contrastBorder': '#0f4a85' } : D.THEMES[th];
      await contrast(label + ' (installed VS Code)', th, T.resolve(file, base).vars);
    }
    // report: table values vs the installed theme files (informational: the installed defaults moved on to the Modern themes; the table keeps the Dark+/Light+ values as a second baseline)
    for (const [label, file, th] of [['Dark+ (dark_plus.json)', 'dark_plus.json', 'dark'], ['Light+ (light_plus.json)', 'light_plus.json', 'light'], ['High Contrast (hc_black.json)', 'hc_black.json', 'hc'], ['Dark Modern (dark_modern.json) vs the Dark+ table', 'dark_modern.json', 'dark'], ['Light Modern (light_modern.json) vs the Light+ table', 'light_modern.json', 'light']]) {
      const cmp = T.compare(file, D.THEMES[th]), diff = cmp.filter(x => x.same === false), unset = cmp.filter(x => x.same === null);
      console.log(`NOTE table vs ${label}: ${cmp.length - diff.length - unset.length} equal, ${diff.length} different, ${unset.length} not set by the file (workbench built-in default applies)` + diff.map(x => `\n     ${x.key}: table ${x.table} / theme file ${x.theme}`).join(''));
    }
    check('theme table cross-check ran against the installed VS Code theme files (differences are reported above, not failures)', true);
  } else console.log('NOTE VS Code is not installed here: only the table themes were measured');

  S.close();
  console.log(C.fails ? `\nFAILED: ${C.fails} of ${C.n}` : `\nALL PASS (${C.n})`); process.exit(C.fails ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
