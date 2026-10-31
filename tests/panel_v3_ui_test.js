// Panel v3 card (UX spec docs/plans/2026-10-20-panel-v3-ux.md section 12, items 1, 2, 3, 9, 10) in real headless Chrome at 315 px (and 280/360 for overflow):
// light (Light+), dark (Dark+) and high contrast, with the real VS Code default theme variables. Starts Chrome only through tests/chrome_helper.js; skips without Chrome.
// Saves screenshots of 6 core states to tests/fixtures/panel-v3/ (light + dark) and writes docs/summary/panel-shots-manifest.json. Run: node tests/panel_v3_ui_test.js
require('./shipmiracle_isolation').apply();
const fs = require('fs'), path = require('path'), os = require('os');
const H = require('./chrome_helper');
if (!H.available()) { console.log('SKIP no Chrome'); process.exit(0); }
const { html } = require(path.join(__dirname, '../vscode-ext/shipmiracle-panel/panel.js'));
const F = require('./panel_v3_fixtures');
const ROOT = path.join(__dirname, '..');
const SHOTS = path.join(__dirname, 'fixtures', 'panel-v3'), SCRATCH = path.join(ROOT, 'reports', 'screens');
const WRITE_SHOTS = process.env.SHIPMIRACLE_SHOTS === '1';          // committed screenshots + manifest are rewritten only on request (PNG bytes differ run to run): SHIPMIRACLE_SHOTS=1 node tests/panel_v3_ui_test.js
fs.mkdirSync(SCRATCH, { recursive: true }); if (WRITE_SHOTS) fs.mkdirSync(SHOTS, { recursive: true });
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'shipmiracle-panel-v3-'));
const HC_KEEP = ['approval', 'hardstop', 'setup', 'health'];      // the 4 states that also get a committed high-contrast shot (SHIPMIRACLE_SHOTS=1); the other high-contrast shots stay in reports/screens
const keepShot = (name, theme) => theme !== 'hc' || (WRITE_SHOTS && HC_KEEP.includes(name));         // listed in the manifest (a normal run lists light and dark only)
const CORE = ['idle', 'building', 'approval', 'verify-fail', 'hardstop', 'delivered'];           // the 6 core states that get committed screenshots (light + dark)
// The shipped default theme values of VS Code (Default Dark+, Default Light+, Default High Contrast): the variables the panel reads.
const THEMES = {
  dark: { '--vscode-foreground': '#cccccc', '--vscode-descriptionForeground': '#ccccccb3', '--vscode-panel-border': '#80808059', '--vscode-editorWidget-background': '#252526', '--vscode-editorWarning-foreground': '#cca700', '--vscode-textLink-foreground': '#3794ff', '--vscode-testing-iconPassed': '#73c991', '--vscode-errorForeground': '#f48771', '--vscode-sideBar-background': '#252526', '--vscode-button-foreground': '#ffffff', '--vscode-input-background': '#3c3c3c', 'color-scheme': 'dark' },
  light: { '--vscode-foreground': '#616161', '--vscode-descriptionForeground': '#717171', '--vscode-panel-border': '#80808059', '--vscode-editorWidget-background': '#f3f3f3', '--vscode-editorWarning-foreground': '#bf8803', '--vscode-textLink-foreground': '#006ab1', '--vscode-testing-iconPassed': '#73c991', '--vscode-errorForeground': '#a1260d', '--vscode-sideBar-background': '#f3f3f3', '--vscode-button-foreground': '#ffffff', '--vscode-input-background': '#ffffff', 'color-scheme': 'light' },
  hc: { '--vscode-foreground': '#ffffff', '--vscode-descriptionForeground': '#ffffffb3', '--vscode-panel-border': '#6fc3df', '--vscode-editorWidget-background': '#0c141f', '--vscode-editorWarning-foreground': '#ffcc00', '--vscode-textLink-foreground': '#21a6a2', '--vscode-testing-iconPassed': '#73c991', '--vscode-errorForeground': '#f48771', '--vscode-sideBar-background': '#000000', '--vscode-contrastBorder': '#6fc3df', '--vscode-button-foreground': '#ffffff', '--vscode-input-background': '#000000', 'color-scheme': 'dark' }
};
const ALL = [...F.STATES.map(s => s.p), ...F.TYPES.map(t => t.p), F.EXTRA.queued, F.EXTRA.fast, F.EXTRA.arabic, F.EXTRA.held];
const mkPage = (theme, projects, extra = {}) => html({ plan: { meters: [] }, guard: { on: true }, projects, ask: null, levelSwitch: { ok: true, why: '' }, ...extra }, {})
  .replace('</head>', `<style>:root{${Object.entries(THEMES[theme]).map(([k, v]) => k + ':' + v).join(';')}}html,body{background:${THEMES[theme]['--vscode-sideBar-background']}}</style></head>`)
  .replace('<body ', `<body class="${theme === 'light' ? 'vscode-light' : theme === 'hc' ? 'vscode-dark vscode-high-contrast' : 'vscode-dark'}" `);
const file = n => path.join(tmp, n + '.html');
for (const th of Object.keys(THEMES)) fs.writeFileSync(file('all-' + th), mkPage(th, ALL));
const ctxCard = (tokens, level, o = {}) => ({ ...F.mk('ctx-app', 'software', { state: 'idle' }), context: { tokens, level }, ...o });
fs.writeFileSync(file('ctx'), mkPage('light', [ctxCard(199999, 'none'), ctxCard(200000, 'soft'), ctxCard(299999, 'soft'), ctxCard(300000, 'strong'), ctxCard(312000, 'strong', { state: 'working', name: 'ctx-busy', dir: '/x/ctx-busy' })].map((p, i) => ({ ...p, name: p.name === 'ctx-busy' ? p.name : 'ctx-' + i, dir: '/x/ctx-' + i }))));
const crq = n => [F.cr('CR-012', 'RTL fix', 'queued', 'scope'), F.cr('CR-013', 'Export report', 'queued', 'scope'), F.cr('CR-014', 'إصلاح الواجهة', 'queued', 'scope')].slice(0, n);
fs.writeFileSync(file('charter'), mkPage('light', [F.mk('char-app', 'software', { cr: crq(3) }), F.mk('warn-app', 'software', { level: 'warn', cr: crq(2) }), F.mk('busy-app', 'software', { state: 'working', cr: crq(1), levelSwitch: { ok: false, why: 'Not now: busy-app is working or waiting for you.' } }), F.STATES.find(x => x.state === 'autopilot').p, F.STATES.find(x => x.state === 'hardstop').p, F.STATES.find(x => x.state === 'approval').p],
  { plan: { meters: [{ id: 'week', label: 'Week', pct: 12.3, lvl: 0, resets: null }] } }));
fs.writeFileSync(file('charter-dark'), mkPage('dark', [F.mk('char-app', 'software', { cr: crq(3) })], { plan: { meters: [{ id: 'week', label: 'Week', pct: 12.3, lvl: 0, resets: null }] } }));
fs.writeFileSync(file('empty'), mkPage('light', [F.mk('quiet-app', 'software')]));
fs.writeFileSync(file('legacy'), mkPage('light', [F.STATES.find(s => s.state === 'noplaybook').p]));

const port = 9500 + Math.floor(Math.random() * 300);
const { kill: killChrome } = H.launch({ port, size: '345,900' });
let fails = 0; const check = (n, c, info = '') => { console.log((c ? 'PASS ' : 'FAIL ') + n + (c ? '' : ' ' + info)); if (!c) fails++; };
const sleep = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  let tabs; for (let i = 0; i < 60; i++) { try { tabs = await (await fetch(`http://127.0.0.1:${port}/json`)).json(); if (tabs.some(t => t.type === 'page')) break; } catch (e) { /* not up yet */ } await sleep(250); }
  const ws = new WebSocket(tabs.find(t => t.type === 'page').webSocketDebuggerUrl); await new Promise(r => ws.addEventListener('open', r));
  let id = 0; const pend = {}; ws.addEventListener('message', m => { const d = JSON.parse(m.data); if (d.id && pend[d.id]) { pend[d.id](d); delete pend[d.id]; } });
  const cdp = (method, params = {}) => new Promise(r => { const i = ++id; pend[i] = r; ws.send(JSON.stringify({ id: i, method, params })); });
  const ev = async expr => { const r = await cdp('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true }); if (r.result.exceptionDetails) throw new Error(JSON.stringify(r.result.exceptionDetails.exception || r.result.exceptionDetails)); return r.result.result.value; };
  await cdp('Page.enable'); await cdp('Emulation.setFocusEmulationEnabled', { enabled: true });
  await cdp('Page.addScriptToEvaluateOnNewDocument', { source: `window.__msgs = []; window.acquireVsCodeApi = () => ({ postMessage: m => window.__msgs.push(m), getState: () => JSON.parse(sessionStorage.getItem('st') || 'null'), setState: s => sessionStorage.setItem('st', JSON.stringify(s)) });` });
  const size = (w, h = 7000) => cdp('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: 1, mobile: false });
  const load = async (n, w = 315, q = '?tab=projects') => { await size(w); await cdp('Page.navigate', { url: 'file://' + file(n) + q }); await sleep(450); await ev(`sessionStorage.clear()`); await ev(LIB); };
  const msgs = () => ev('JSON.stringify(window.__msgs)').then(JSON.parse);
  const key = async (k, code, vk, text) => { await cdp('Input.dispatchKeyEvent', { type: text ? 'keyDown' : 'rawKeyDown', key: k, code, windowsVirtualKeyCode: vk, ...(text ? { text } : {}) }); await cdp('Input.dispatchKeyEvent', { type: 'keyUp', key: k, code, windowsVirtualKeyCode: vk }); };
  const cardJs = name => `[...document.querySelectorAll('.card')].find(c => c.querySelector('.name').textContent === ${JSON.stringify(name)})`;
  // in-page contrast helpers: composite every ancestor background on a canvas (wcag ratio)
  const LIB = `window.__c = (() => {
    const cv = document.createElement('canvas'); cv.width = cv.height = 1; const cx = cv.getContext('2d', { willReadFrequently: true });
    const px = () => { const d = cx.getImageData(0, 0, 1, 1).data; return [d[0], d[1], d[2]]; };
    const lum = c => { const f = v => { v /= 255; return v <= .03928 ? v / 12.92 : Math.pow((v + .055) / 1.055, 2.4); }; return .2126 * f(c[0]) + .7152 * f(c[1]) + .0722 * f(c[2]); };
    const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + .05) / (Math.min(x, y) + .05); };
    const bgOf = (n, own = true) => { cx.clearRect(0, 0, 1, 1); cx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue('--vscode-sideBar-background').trim(); cx.fillRect(0, 0, 1, 1);
      const chain = []; for (let e = n; e; e = e.parentElement) chain.unshift(e);
      chain.forEach(e => { if (e === n && !own) return; const b = getComputedStyle(e).backgroundColor; if (b && b !== 'rgba(0, 0, 0, 0)' && b !== 'transparent') { cx.fillStyle = b; cx.fillRect(0, 0, 1, 1); } }); return px(); };
    const colorOn = (col, bg) => { cx.fillStyle = 'rgb(' + bg.join(',') + ')'; cx.fillRect(0, 0, 1, 1); cx.fillStyle = col; cx.fillRect(0, 0, 1, 1); return px(); };
    return { ratio, bgOf, colorOn };
  })(); window.__card = n => [...document.querySelectorAll('.card')].find(c => c.querySelector('.name').textContent === n);`;
  const TEXT_CHECK = `(() => { const { ratio, bgOf, colorOn } = window.__c, out = [];
    document.querySelectorAll('.card *, .nowblk *, .menu *, .tab i').forEach(n => {
      if (!n.getClientRects().length || n.closest('svg') || n.closest('[hidden]')) return;
      const own = [...n.childNodes].some(c => c.nodeType === 3 && c.textContent.trim()); if (!own) return;
      if (n.disabled || n.closest(':disabled') || n.classList.contains('seg') || n.classList.contains('dt')) return;
      const bg = bgOf(n), fg = colorOn(getComputedStyle(n).color, bg), r = ratio(fg, bg);
      out.push({ txt: n.textContent.trim().slice(0, 30), cls: n.className.toString().slice(0, 24), ratio: +r.toFixed(2) });
    }); return out; })()`;
  const ICON_CHECK = `(() => { const { ratio, bgOf, colorOn } = window.__c, out = [];
    document.querySelectorAll('.card .dt').forEach(n => {
      const card = bgOf(n.closest('.card'), false), s = getComputedStyle(n), fill = colorOn(s.backgroundColor, card), border = colorOn(s.borderTopColor, card), own = bgOf(n), glyph = n.textContent.trim() ? colorOn(s.color, own) : null;
      out.push({ s: n.parentElement.className, ring: +Math.max(ratio(fill, card), ratio(border, card)).toFixed(2), glyph: glyph ? +ratio(glyph, own).toFixed(2) : null });
    });
    document.querySelectorAll('.card .ic').forEach(n => { if (!n.getClientRects().length) return; const card = bgOf(n.closest('.card')), c = colorOn(getComputedStyle(n).color, card); out.push({ s: 'ic', ring: +ratio(c, card).toFixed(2), glyph: null }); });
    return out; })()`;

  // ============ item 1: the 16 card states x light / dark / high contrast ============
  const manifest = [];
  for (const theme of ['light', 'dark', 'hc']) {
    await load('all-' + theme);
    const T = `[${theme}] `;
    check(T + 'no style= attribute in the markup (CSP)', !/\sstyle=/.test(await ev(`document.querySelector('main').outerHTML`)));
    for (const s of F.STATES) {
      const nm = s.p.name, k = JSON.stringify(nm);
      const r = await ev(`(() => { const c = ${cardJs(nm)}; const prim = [...c.querySelectorAll('.btn.primary')]; return { n: prim.length, label: prim[0] && prim[0].textContent.trim(), key: c.dataset.primary, state: c.dataset.state, dis: prim[0] && prim[0].disabled,
        marks: [...c.querySelectorAll('.rail .rs')].map(x => x.getAttribute('aria-label')), hasStrip: !!c.querySelector('.rail'), sub: c.querySelector('.sub').textContent }; })()`);
      check(`${T}${s.state}: one primary "${s.primary[1]}" (data-primary ${s.primary[0]}), data-state ${s.state}`, r.n === 1 && r.key === s.primary[0] && r.label.startsWith(s.primary[1]) && r.state === s.state && (s.primary[0] !== 'wait' || r.dis === true), JSON.stringify(r));
      if (s.state !== 'noplaybook') check(`${T}${s.state}: rail has 7 step buttons, each with an aria-label "Name: word"`, r.marks.length === 7 && r.marks.every(m => /^[^:]+: .+/.test(m)), JSON.stringify(r.marks));
      else check(`${T}noplaybook: legacy card (no step rail, quiet "Type: not set", status line from the spec)`, !r.hasStrip && /No playbook yet/.test(r.sub), JSON.stringify(r));
    }
    // per-type stage names (all six types) in the strip's aria-labels and its list label
    for (const ty of F.TYPES) {
      const names = await ev(`(() => { const c = ${cardJs('type-' + ty.type)}; return { m: [...c.querySelectorAll('.rail .rs')].map(x => x.getAttribute('aria-label').split(':')[0]), l: c.querySelector('.rail').getAttribute('aria-label') }; })()`);
      check(`${T}${ty.type}: stage names ${F.NAMES[ty.type].join(' / ')}`, JSON.stringify(names.m) === JSON.stringify(F.NAMES[ty.type]) && names.l === 'Steps: ' + F.NAMES[ty.type].join(', '), JSON.stringify(names));
    }
    // a card on the data's own labels when stageLabels is missing falls back to the type table
    check(`${T}exactly one .btn.primary per card on the whole page (26 cards)`, await ev(`document.querySelectorAll('.card').length`) === ALL.length && await ev(`[...document.querySelectorAll('.card')].every(c => c.querySelectorAll('.btn.primary').length === 1)`));
    // mark shapes are not colour only
    const shapes = await ev(`(() => { const g = n => [...window.__card(n).querySelectorAll('.rail .rs')].map(x => x.className.replace('rs s-', '') + ':' + x.querySelector('.dt').textContent.trim()).join(' '); return { fail: g('fail-app'), twice: g('twice-app'), fast: g('fast-app'), frozen: g('frozen-app'), done: g('done-app'), idle: g('idle-app'), appr: g('approve-app') }; })()`);
    check(T + 'dots use shapes: done ✓, now filled (no glyph), failed ✕ on the test step, next hollow', /^done:✓ done:✓ done:✓ cur: fail:✕ next: next:$/.test(shapes.fail), JSON.stringify(shapes));
    check(T + 'failed twice shows ✕; frozen and waiting show !; fast lane shows dashed skipped dots; delivered is all ✓; idle all hollow',
      /fail:✕/.test(shapes.twice) && /blk:!/.test(shapes.frozen) && /wait:!/.test(shapes.appr) && (shapes.fast.match(/skip:/g) || []).length === 4 && (shapes.done.match(/done:✓/g) || []).length === 7 && (shapes.idle.match(/next:/g) || []).length === 7, JSON.stringify(shapes));
    // owner's change (21 Oct): no coloured box round a step, only the dot
    const boxes = await ev(`[...document.querySelectorAll('.rail .rs, .rail .rsi')].filter(n => { const s = getComputedStyle(n); return (s.backgroundColor !== 'rgba(0, 0, 0, 0)' && !n.matches(':hover')) || s.boxShadow !== 'none' && !n.matches('[aria-expanded="true"]'); }).length`);
    check(T + 'no highlighted box round any step (no red or amber square): the step buttons have no background', boxes === 0, String(boxes));
    // layout: no horizontal scroll, nothing leaves its card, every target >= 22 px
    const lay = await ev(`(() => { const d = document.documentElement, bad = []; document.querySelectorAll('.card').forEach(c => { const cr = c.getBoundingClientRect(); c.querySelectorAll('*').forEach(n => { if (n.closest('[hidden]') || !n.getClientRects().length) return; const r = n.getBoundingClientRect(); if (r.width && (r.right > cr.right + 1 || r.left < cr.left - 1)) bad.push(c.querySelector('.name').textContent + ':' + n.className.toString().slice(0, 20)); }); });
      const sc = document.getElementById('scroll'); return { sw: d.scrollWidth <= d.clientWidth && sc.scrollWidth <= sc.clientWidth, bad: bad.slice(0, 5) }; })()`);
    check(T + 'no horizontal scroll at 315 px and nothing leaves its card', lay.sw && lay.bad.length === 0, JSON.stringify(lay));
    const small = await ev(`[...document.querySelectorAll('.card button, .card .chip, .nowblk button')].filter(n => n.getClientRects().length && !n.closest('[hidden]')).map(n => { const r = n.getBoundingClientRect(); return { t: (n.textContent.trim() || n.getAttribute('aria-label') || '').slice(0, 24), w: Math.round(r.width), h: Math.round(r.height) }; }).filter(x => x.h < 22 || x.w < 22)`);
    check(T + 'every button and chip is at least 22 x 22 px', small.length === 0, JSON.stringify(small.slice(0, 6)));
    const shapeSizes = await ev(`(() => { const c = ${cardJs('idle-app')}; const b = c.querySelector('.btn.primary').getBoundingClientRect(), m = c.querySelector('.btn.more').getBoundingClientRect(); return { pw: Math.round(b.height), mh: Math.round(m.height), mw: Math.round(m.width) }; })()`);
    check(T + 'primary is 28 px high (.brow grid); the ⋯ button is 28 x 28', shapeSizes.pw === 28 && shapeSizes.mh === 28 && shapeSizes.mw === 28, JSON.stringify(shapeSizes));
    const live = await ev(`[...document.querySelectorAll('[aria-live]')].map(n => n.className || n.tagName)`);
    check(T + 'aria-live is used only for the Now block (and form hints)', live.every(c => /nowblk|nhint|osum/.test(c)) && live.filter(c => /nowblk/.test(c)).length === 1, JSON.stringify(live));
    // contrast
    const tx = await ev(TEXT_CHECK), ic = await ev(ICON_CHECK);
    const badT = tx.filter(x => x.ratio < 4.5), badI = ic.filter(x => x.ring < 3 || (x.glyph !== null && x.glyph < 3));
    check(`${T}text contrast >= 4.5:1 on ${tx.length} text elements (lowest ${Math.min(...tx.map(x => x.ratio))})`, tx.length > 100 && badT.length === 0, JSON.stringify(badT.slice(0, 8)));
    check(`${T}icon / mark contrast >= 3:1 on ${ic.length} marks and icons (lowest ${Math.min(...ic.map(x => x.ring))})`, ic.length > 100 && badI.length === 0, JSON.stringify(badI.slice(0, 8)));
    // menus (closed ones are hidden): open the card menu and the autopilot menu and re-measure
    await ev(`${cardJs('idle-app')}.querySelector('.btn.more').click()`);
    const mtx = await ev(TEXT_CHECK); const badM = mtx.filter(x => x.ratio < 4.5);
    check(`${T}open ⋯ menu: items readable (>= 4.5:1)`, mtx.some(x => x.cls.includes('mi')) && badM.length === 0, JSON.stringify(badM.slice(0, 5)));
    await ev(`document.body.click()`);
    await ev(`${cardJs('idle-app')}.querySelector('.apl').click()`);
    const atx = await ev(TEXT_CHECK); const badA = atx.filter(x => x.ratio < 4.5);
    check(`${T}open Change sheet: items readable (>= 4.5:1)`, atx.some(x => x.cls.includes('ord')) && badA.length === 0, JSON.stringify(badA.slice(0, 5)));
    await ev(`${cardJs('idle-app')}.querySelector('[data-sheetclose]').click()`);
    // screenshots (light and dark committed for the 6 core states; high contrast stays in reports/screens)
    for (const st of CORE) {
      const nm = F.STATES.find(s => s.state === st).p.name;
      const r = await ev(`(() => { const b = ${cardJs(nm)}.getBoundingClientRect(); return { x: b.left - 8, y: b.top - 8 + window.scrollY, w: b.width + 16, h: b.height + 16 }; })()`);
      const shot = await cdp('Page.captureScreenshot', { format: 'png', clip: { x: r.x, y: r.y, width: r.w, height: r.h, scale: 2 } });
      const buf = Buffer.from(shot.result.data, 'base64'), dest = !(WRITE_SHOTS && keepShot(st, theme)) ? path.join(SCRATCH, `panel-v3-${st}-${theme}.png`) : path.join(SHOTS, `${st}-${theme}.png`);
      fs.writeFileSync(dest, buf);
      if (keepShot(st, theme)) manifest.push({ state: st, theme, file: `tests/fixtures/panel-v3/${st}-${theme}.png`, width: Math.round(r.w * 2), height: Math.round(r.h * 2), bytes: buf.length });
    }
    const full = await cdp('Page.captureScreenshot', { format: 'png' }); fs.writeFileSync(path.join(SCRATCH, `panel-v3-all-${theme}.png`), Buffer.from(full.result.data, 'base64'));
  }

  // widths 280 and 360: no horizontal scroll and no clipped card
  for (const w of [280, 360]) {
    await load('all-light', w);
    const lay = await ev(`(() => { const d = document.documentElement, sc = document.getElementById('scroll'), bad = []; document.querySelectorAll('.card').forEach(c => { const cr = c.getBoundingClientRect(); c.querySelectorAll('*').forEach(n => { if (n.closest('[hidden]') || !n.getClientRects().length) return; const r = n.getBoundingClientRect(); if (r.width && (r.right > cr.right + 1 || r.left < cr.left - 1)) bad.push(c.querySelector('.name').textContent + ':' + n.className.toString().slice(0, 20)); }); }); const wide = [...document.querySelectorAll('body *')].filter(n => n.getClientRects().length && n.getBoundingClientRect().right > d.clientWidth + 1).slice(0, 4).map(n => n.tagName + '.' + n.className.toString().slice(0, 30) + ':' + Math.round(n.getBoundingClientRect().right) + ':' + n.outerHTML.slice(0, 60)); return { sw: d.scrollWidth <= d.clientWidth && sc.scrollWidth <= sc.clientWidth, bad: bad.slice(0, 6), wide, sc: [d.scrollWidth, d.clientWidth, sc.scrollWidth, sc.clientWidth] }; })()`);
    check(`[${w}] no horizontal scroll, nothing leaves its card`, lay.sw && lay.bad.length === 0, JSON.stringify(lay));
  }

  // ============ item 2: golden snapshot: the DOM data-* fields equal the data contract fields of each fixture ============
  await load('all-light');
  const dom = await ev(`JSON.stringify([...document.querySelectorAll('.card')].map(c => ({ name: c.querySelector('.name').textContent, stage: c.dataset.stage, cr: c.dataset.cr, verdict: c.dataset.verdict, autopilot: c.dataset.autopilot, chips: c.dataset.chips })))`).then(JSON.parse);
  const expect = ALL.map(p => { const a = (p.cr || []).find(c => c.status === 'open' || c.status === 'blocked'); return { name: p.name, stage: a ? a.stage : '', cr: a ? a.id : '', verdict: p.lastVerdict ? p.lastVerdict.word : '', autopilot: p.playbook ? p.playbook.autopilot : '', chips: (p.cr || []).filter(c => ['open', 'queued', 'blocked'].includes(c.status)).map(c => c.id + ':' + c.status).join(',') }; });
  check('golden: data-stage, data-cr, data-verdict, data-autopilot, data-chips of all ' + ALL.length + ' cards deep-equal the contract fields of the fixtures', JSON.stringify(dom) === JSON.stringify(expect), JSON.stringify(dom.filter((d, i) => JSON.stringify(d) !== JSON.stringify(expect[i])).slice(0, 2)));
  check('golden: data-primary and data-state of the 16 states match the spec table', await ev(`${JSON.stringify(F.STATES.map(s => [s.p.name, s.primary[0], s.state]))}.every(([n, p, st]) => { const c = window.__card(n); return c.dataset.primary === p && c.dataset.state === st; })`));

  // CR chips, verdict line, autopilot chips, strip label
  const row = await ev(`(() => { const c = window.__card;
    const txt = (n, s) => [...c(n).querySelectorAll(s)].map(x => x.textContent.trim());
    return { build: txt('build-app', '.crow > *'), approve: txt('approve-app', '.crow > *'), twice: txt('twice-app', '.crow > *'), arabic: c('arabic-app').querySelector('.crow bdi').getAttribute('dir'), more: c('build-app').querySelector('.crmore').getAttribute('aria-label'),
      failLast: c('fail-app').querySelector('.last').textContent.replace(/\\s+/g, ' ').trim(), passLast: c('review-app').querySelector('.last').textContent.replace(/\\s+/g, ' ').trim(), twiceLast: c('twice-app').querySelector('.last').textContent.replace(/\\s+/g, ' ').trim(), failCls: c('fail-app').querySelector('.last').className,
      auto: txt('auto-app', '.chips .chip'), run: c('auto-app').querySelector('.runl').textContent, apl: c('auto-app').querySelector('.apl').textContent.replace(/\\s+/g, ' ').trim(), sfl: c('build-app').querySelector('.sfl').textContent.replace(/\\s+/g, ' ').trim(), stopSub: c('stop-app').querySelector('.sub').textContent, nextl: c('approve-app').querySelector('.nextl').textContent, bl: c('twice-app').querySelector('.chip.bl') ? 1 : 0, q: c('approve-app').querySelector('.chip.q').textContent }; })()`);
  check('CR chips: active "CR-012 RTL fix", queued "CR-014 queued", blocked "! CR-020 blocked: needs you"; max 2 shown + "+2" more', row.build.join('|') === 'CR-012 RTL fix|CR-013 queued|+2' && row.q === 'CR-014 queued' && /CR-020 blocked: needs you/.test(row.twice.join('')) && row.bl === 1, JSON.stringify(row));
  check('CR title carries dir="auto" (Arabic renders right-to-left)', row.arabic === 'auto');
  check('verdict line: always the word, counts and "report ›"', /^Last: Test FAIL · 2 of 214 report ›$/.test(row.failLast) && /^Last: Test PASS · 214 of 214 report ›$/.test(row.passLast) && /^Last: Test BLOCKED$/.test(row.twiceLast) && /vd-fail/.test(row.failCls), JSON.stringify([row.failLast, row.passLast, row.twiceLast]));
  check('autopilot running: no budget or decision chips; the line reads "On its own · about 1 h 12 min left · 4.1% of your week used (limit 10%)"; the autopilot line reads "Autopilot · On its own ▾"', row.auto.length === 0 && row.run === 'On its own · about 1 h 12 min left · 4.1% of your week used (limit 10%)' && row.apl === 'Autopilot · On its own ▾' && row.sfl === 'Safe mode ✓', JSON.stringify([row.auto, row.run, row.apl, row.sfl]));
  check('hard stop says "Paused: ... It will not go on without you." (no red duplicate chip); the next line of a waiting plan is "Next: Build"', /^Paused: autopilot wants to push publicly\. It will not go on without you\.$/.test(row.stopSub) && row.nextl === 'Next: Build', JSON.stringify([row.stopSub, row.nextl]));

  // ============ item 3: Now / Next / Waiting on you ============
  const now = await ev(`(() => { const b = document.querySelector('.nowblk'); const rows = s => [...b.querySelectorAll(s + ' .nrow')].map(r => ({ p: r.querySelector('.nproj').textContent, t: r.querySelector('.ntxt').textContent, hidden: r.hidden, btn: r.querySelector('.btn') && r.querySelector('.btn').getAttribute('aria-label') }));
    return { head: [...b.querySelectorAll('.nh')].map(x => x.textContent), wait: rows('.nwait'), now: rows('.nnow'), next: rows('.nnext'), live: b.getAttribute('aria-live'), badge: document.querySelector('[data-tab="projects"] i') && document.querySelector('[data-tab="projects"] i').textContent, before: b.compareDocumentPosition(document.querySelector('.card')) & 4 }; })()`);
  check('Now block: WAITING ON YOU (3) with the three owners in card order, each row a real "Open" button with a descriptive label', now.head[0] === 'WAITING ON YOU (3)' && now.wait.map(r => r.p).join() === 'approve-app,twice-app,stop-app' && now.wait.every(r => /^(Review plan|Decide) for /.test(r.btn)) && now.live === 'polite' && now.before === 4, JSON.stringify(now));
  check('Waiting rows say what is needed (plan for CR-013 / tests failed twice / the stop)', /Approve plan for CR-013/.test(now.wait[0].t) && /Tests failed twice \(CR-020\)/.test(now.wait[1].t) && /push publicly/.test(now.wait[2].t), JSON.stringify(now.wait));
  check('NOW lists the working projects; only 3 rows show, the rest are behind "+N more"; the Projects tab badge mirrors the waiting count', now.now.filter(r => !r.hidden).length === 3 && now.now.some(r => r.hidden) && now.badge === '3' && now.next.length >= 1, JSON.stringify([now.now.length, now.badge]));
  await ev(`document.querySelector('[data-nmore]').click()`);
  check('"+N more" expands the hidden rows and turns into "Show fewer"', await ev(`[...document.querySelectorAll('.nnow .nrow')].every(r => !r.hidden)`) && await ev(`document.querySelector('[data-nmore]').textContent`) === 'Show fewer');
  await ev(`window.__msgs.length = 0; document.querySelector('.nwait .nrow .btn').click()`);
  let m = (await msgs()).filter(x => x.type !== 'editing');
  check('Open in the Now block = the card\'s primary: "Review plan" posts {type:act, act:plan} and does not open the chat', m.length === 1 && m[0].type === 'act' && m[0].act === 'plan' && m[0].project === 'approve-app' && m[0].dir === '/x/approve-app', JSON.stringify(m));
  await ev(`window.__msgs.length = 0; document.querySelectorAll('.nwait .nrow .btn')[1].click()`); m = (await msgs()).filter(x => x.type !== 'editing');
  check('"Decide" opens that project\'s chat', m.length === 1 && m[0].type === 'open' && m[0].dir === '/x/twice-app', JSON.stringify(m));
  await load('empty');
  const em = await ev(`(() => { const b = document.querySelector('.nowblk'); return { cls: b.className, text: b.textContent.trim(), kids: b.children.length, badge: !!document.querySelector('[data-tab="projects"] i') }; })()`);
  check('Now block empty = one calm line "Nothing waiting on you." and no badge', em.cls.includes('empty') && em.text === 'Nothing waiting on you.' && em.kids === 1 && !em.badge, JSON.stringify(em));

  // primary click behaviours on the cards
  await load('all-light'); await ev('window.__msgs.length = 0');
  const clickIn = (nm, sel) => ev(`${cardJs(nm)}.querySelector(${JSON.stringify(sel)}).click()`);
  await clickIn('approve-app', '.btn.primary'); await clickIn('idle-app', '.btn.primary'); await clickIn('queued-app', '.btn.primary'); await clickIn('legacy-app', '.btn.primary'); await clickIn('done-app', '[data-act="openreport"]'); await clickIn('limit-app', '.btn.primary');
  m = (await msgs()).filter(x => x.type !== 'editing');
  check('primary buttons post exactly one message each and never open the chat through the card click: plan, open, start CR-013, legacy = open chat, report; Wait is disabled', JSON.stringify(m.map(x => x.type + ':' + (x.act || ''))) === JSON.stringify(['act:plan', 'open:', 'act:start', 'open:', 'act:openreport']) && m[2].cr === 'CR-013' && m[4].report === 'docs/reports/cr-012-verify.md', JSON.stringify(m));
  check('"Start CR-013" is the primary of an idle project with a queued CR, "Wait · back" is disabled with a reason', await ev(`${cardJs('queued-app')}.querySelector('.btn.primary').textContent`) === 'Start CR-013' && await ev(`${cardJs('limit-app')}.querySelector('.btn.primary').disabled`) && /usage limit/.test(await ev(`${cardJs('limit-app')}.querySelector('.btn.primary').title`)));
  check('held project: subtitle "Held: its session is still running.", primary Open chat, the Change sheet says why it cannot change', await ev(`${cardJs('held-app')}.querySelector('.sub').textContent`) === 'Held: its session is still running.' && await ev(`${cardJs('held-app')}.querySelector('.btn.primary').textContent`) === 'Open chat' && /Held: its session is still running\./.test(await ev(`${cardJs('held-app')}.querySelector('[data-sheetbox="level"]').textContent`)) && await ev(`[...${cardJs('held-app')}.querySelectorAll('[data-lv]')].filter(b => !b.disabled && b.getAttribute('aria-checked') !== 'true').length`) === 0);

  // ============ item 9: context chip at 199k / 200k / 299k / 300k ============
  await load('ctx'); await ev('window.__msgs.length = 0');
  const cx = await ev(`[...document.querySelectorAll('.card')].map(c => ({ chip: c.querySelector('.chip.ctx') && c.querySelector('.chip.ctx').textContent, strong: !!c.querySelector('.chip.ctx.strong'), foot: c.querySelector('.foot').textContent, quiet: c.querySelector('.btns > [data-handoff].btn') && c.querySelector('.btns > [data-handoff].btn').className, dot: !!c.querySelector('.menu [data-handoff] .mdot'), dis: c.querySelector('.btns > [data-handoff]') && c.querySelector('.btns > [data-handoff]').disabled, title: c.querySelector('.btns > [data-handoff]') && c.querySelector('.btns > [data-handoff]').title, prim: c.querySelectorAll('.btn.primary').length, primKey: c.dataset.primary }))`);
  check('199k: plain grey text "context 199k" in the foot, no chip, no button', cx[0].chip === null && /context 199k/.test(cx[0].foot) && cx[0].quiet === null && !cx[0].dot, JSON.stringify(cx[0]));
  check('200k and 299k (soft): amber chip "Chat is long · 200k"/"299k", amber dot on the ⋯ item, no extra button', cx[1].chip === 'Chat is long · 200k' && cx[2].chip === 'Chat is long · 299k' && !cx[1].strong && cx[1].dot && cx[2].dot && cx[1].quiet === null && cx[2].quiet === null, JSON.stringify([cx[1], cx[2]]));
  check('300k (strong): chip "Chat is very long · 300k" plus a quiet (never primary) Handoff button', cx[3].chip === 'Chat is very long · 300k' && cx[3].strong && /quiet/.test(cx[3].quiet) && !/primary/.test(cx[3].quiet) && cx[3].prim === 1 && cx[3].primKey === 'open', JSON.stringify(cx[3]));
  check('while an agent works the Handoff button is disabled with "Wait: an agent is working."', cx[4].dis === true && cx[4].title === 'Wait: an agent is working.', JSON.stringify(cx[4]));
    await ev(`document.querySelectorAll('.card')[3].querySelector('.btns > [data-handoff]').click()`);
  const armed = await ev(`document.querySelectorAll('.card')[3].querySelector('.btns > [data-handoff]').textContent`);
  await ev(`document.querySelectorAll('.card')[3].querySelector('.btns > [data-handoff]').click()`);
  m = (await msgs()).filter(x => x.type === 'handoff');
  check('Handoff asks "Sure?" in place first, then sends {type:handoff, step:ask}', armed === 'Sure? Note saved, then fresh chat' && m.length === 1 && m[0].step === 'ask' && m[0].project === 'ctx-3', JSON.stringify([armed, m]));

  // ============ item 10: keyboard walk, focus ring, reduced motion, menu behaviour ============
  await load('all-dark'); await ev('window.__msgs.length = 0');
  const active = () => ev(`(() => { const a = document.activeElement; return a ? { tag: a.tagName, cls: a.className.toString(), txt: (a.textContent || '').trim().slice(0, 24), aria: a.getAttribute('aria-label') || '', card: a.closest('.card') && a.closest('.card').querySelector('.name').textContent } : null; })()`);
  await ev(`${cardJs('build-app')}.focus()`);
  const order = [await active()];
  for (let i = 0; i < 12; i++) { await key('Tab', 'Tab', 9); order.push(await active()); }
  const seq = order.map(o => o && (['card', 'dtog', 'rs', 'apl', 'sfl', 'primary', 'more', 'crmore'].find(c => o.cls.split(' ').includes(c)) || o.tag)).join('>');
  check('Tab order inside a card: card > Details toggle > 7 steps > autopilot line > Safe mode > chips (if any) > primary  (got ' + seq + ')', /^card>dtog(>rs){7}>apl>sfl(>[a-z]+)*>primary/.test(seq), seq);
  const ringTarget = await ev(`(() => { const c = ${cardJs('build-app')}; c.querySelector('.btn.primary').focus(); const s = getComputedStyle(c.querySelector('.btn.primary')); return { w: s.outlineWidth, st: s.outlineStyle, off: s.outlineOffset }; })()`);
  check('focus ring: 2px solid on the focused primary, offset 1px', ringTarget.w === '2px' && ringTarget.st === 'solid' && ringTarget.off === '1px', JSON.stringify(ringTarget));
  { const r = await ev(`(() => { const b = ${cardJs('build-app')}.getBoundingClientRect(); return { x: b.left - 8, y: b.top - 8 + window.scrollY, w: b.width + 16, h: b.height + 16 }; })()`);
    const shot = await cdp('Page.captureScreenshot', { format: 'png', clip: { x: r.x, y: r.y, width: r.w, height: r.h, scale: 2 } }); fs.writeFileSync(path.join(SCRATCH, 'panel-v3-focus-ring-dark.png'), Buffer.from(shot.result.data, 'base64')); }
  await key('Tab', 'Tab', 9);
  check('Tab reaches the ⋯ button, aria-label "More actions for build-app"', (await active()).aria === 'More actions for build-app');
  await key('Enter', 'Enter', 13, '\r'); await sleep(100);
  let mo = await ev(`(() => { const a = document.activeElement; return { open: !document.getElementById('m4').hidden, exp: document.querySelector('[aria-controls="m4"]').getAttribute('aria-expanded'), item: a.className, txt: a.textContent.trim() }; })()`);
  check('Enter opens the menu, focus moves to its first item "Open chat"', mo.open && mo.exp === 'true' && /\bmi\b/.test(mo.item) && mo.txt === 'Open chat', JSON.stringify(mo));
  await key('ArrowDown', 'ArrowDown', 40); await key('ArrowDown', 'ArrowDown', 40);
  const t2 = (await active()).txt; await key('ArrowUp', 'ArrowUp', 38); const t1 = (await active()).txt; await key('End', 'End', 35); const tl = (await active()).txt; await key('Home', 'Home', 36); const th = (await active()).txt;
  check('arrow keys move through the items (down, up, End, Home)', t2 !== 'Open chat' && t1 !== t2 && tl === 'Open Health' && th === 'Open chat', JSON.stringify([t2, t1, tl, th]));
  await key('Escape', 'Escape', 27); await sleep(80);
  mo = await ev(`({ hidden: document.getElementById('m4').hidden, onMore: document.activeElement === document.querySelector('[aria-controls="m4"]') })`);
  check('Esc closes the menu and returns focus to the ⋯ button', mo.hidden && mo.onMore, JSON.stringify(mo));
  await key(' ', 'Space', 32, ' '); await sleep(80);
  check('Space opens it too', await ev(`!document.getElementById('m4').hidden`));
  await key('Escape', 'Escape', 27);
  await ev('window.__msgs.length = 0'); await ev(`${cardJs('build-app')}.querySelector('.btn.primary').focus()`); await key('Enter', 'Enter', 13, '\r'); m = (await msgs()).filter(x => x.type !== 'editing');
  check('Enter on the focused primary posts one message (open the chat); the card itself does not fire a second', m.length === 1 && m[0].type === 'open' && m[0].dir === '/x/build-app', JSON.stringify(m));
  // reduced motion: no running animation
  await cdp('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-reduced-motion', value: 'reduce' }] });
  await load('all-dark');
  await ev(`${cardJs('build-app')}.querySelector('.btn.more').click()`); await sleep(250);
  const anim = await ev(`document.getAnimations().filter(a => a.playState === 'running').map(a => (a.animationName || a.transitionProperty || '?'))`);
  check('prefers-reduced-motion: zero running animations (spinner static, menu opens without the fade)', anim.length === 0, JSON.stringify(anim));
  await cdp('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-reduced-motion', value: 'no-preference' }] });
  await load('all-dark');
  const anim2 = await ev(`document.getAnimations().filter(a => a.playState === 'running').length`);
  check('(control) without the preference the working cards do spin', anim2 > 0, String(anim2));
  // legacy card keeps today's look
  await load('legacy');
  const lg = await ev(`(() => { const c = document.querySelector('.card'); return { strip: c.querySelectorAll('.tflow .ts').length, sub: c.querySelector('.sub').textContent, prim: c.querySelector('.btn.primary').textContent, foot: c.querySelector('.foot').textContent, ap: !!c.querySelector('.apchip'), crow: !!c.querySelector('.crow'), last: !!c.querySelector('.last'), menu: [...c.querySelectorAll('.menu .mi')].map(x => x.textContent.trim()), primSetup: !!c.querySelector('.btn.primary[data-act="setup"]') }; })()`);
  check('legacy card (no playbook): the 6-step Team-flow strip, no autopilot chip, no CR row, "Type: not set", primary stays "Open chat" and "Set up playbook" is a quiet item in the ⋯ menu (owner decision)', lg.strip === 6 && lg.prim === 'Open chat' && !lg.primSetup && lg.menu.includes('Set up playbook') && /Type: not set/.test(lg.foot) && !lg.ap && !lg.crow && !lg.last, JSON.stringify(lg));


  // (the old charter editor tests moved to tests/panel_v3_rev2_test.js: the 'On its own' sheet)
  await load('charter'); const m0 = 0;
  // hard stop: Decide shows the stop in words and the exact commands; nothing goes to a chat
  await ev('window.__msgs.length = 0'); const SQ = sel => `${cardJs('stop-app')}.querySelector(${JSON.stringify(sel)})`;
  await ev(`${SQ('.btn.primary')}.click()`); m = (await msgs()).filter(x => x.type !== 'editing');
  const dd = await ev(`(() => { const b = ${SQ('[data-decide]')}; return { vis: !b.hidden, head: b.querySelector('.chh').textContent, cmd: b.querySelector('[data-dcmd]').textContent, text: b.textContent }; })()`);
  check('hard stop: Decide opens the in-card box with the stop in words, the exact `shipm autopilot allow H-1a2b3c` command and Stop autopilot; no message at all', m.length === 0 && dd.vis && dd.head === 'Stopped: autopilot wants to push publicly' && dd.cmd === 'shipm autopilot allow H-1a2b3c --project stop-app' && /Stop autopilot/.test(dd.text) && !/charter: off/.test(dd.text), JSON.stringify([m, dd]));
  await ev(`${SQ('[data-act="allowterm"]')}.click()`); m = (await msgs()).filter(x => x.type !== 'editing');
  check('hard stop: "Allow this once" posts {act:"allowterm"} and nothing else; no message carries allow:/charter:/approved text', m.length === 1 && m[0].act === 'allowterm' && m[0].project === 'stop-app' && !JSON.stringify(await msgs()).match(/"(text|prompt|send)"|allow: |charter: |approved/i), JSON.stringify(m));
  await ev(`${SQ('[data-act="dclose"]')}.click()`); check('hard stop: Close hides the box', await ev(`${SQ('[data-decide]')}.hidden`));
  // plan review: Review plan shows the in-card hint, posts only {act:"plan"}
  await ev('window.__msgs.length = 0'); const PQ = sel => `${cardJs('approve-app')}.querySelector(${JSON.stringify(sel)})`;
  check('plan: the hint is hidden until Review plan is pressed', await ev(`${PQ('[data-planhint]')}.hidden`));
  await ev(`${PQ('.btn.primary')}.click()`); m = (await msgs()).filter(x => x.type !== 'editing');
  check('plan: Review plan posts only {act:"plan"} and shows "Type "approved" in the chat to approve" in the card; no approval text is posted', m.length === 1 && m[0].act === 'plan' && !(await ev(`${PQ('[data-planhint]')}.hidden`)) && await ev(`${PQ('[data-planhint]')}.textContent`) === 'Type "approved" in the chat to approve' && !/approved/i.test(JSON.stringify(m)), JSON.stringify(m));
  // ============ item 5: New project box (spec section 5) ============
  await load('empty');
  const NB = sel => `document.querySelector('[data-newbox] ${sel}')`;
  const typeName = v => ev(`(() => { const n = ${NB('[data-nf="name"]')}; n.value = ${JSON.stringify(v)}; n.dispatchEvent(new Event('input', { bubbles: true })); })()`);
  const hintOf = () => ev(`document.querySelector('[data-nhint]').textContent`), ruleOf = () => ev(`(() => { const r = document.querySelector('[data-nrule]'); return r.hidden ? null : r.textContent; })()`);
  const createDis = () => ev(`document.querySelector('[data-nform="create"]').disabled`);
  await ev(`document.querySelector('[data-toggle="newbox"]').click()`);
  check('new project: empty name hint "Will be created as ~/Developer/…"; Create disabled', await hintOf() === 'Will be created as ~/Developer/…' && await createDis());
  await typeName('Garden Notes!'); check('new project: a name that is not kebab-case is shown tidied with the rule "Use lowercase letters, numbers and dashes."', await hintOf() === 'Will be created as ~/Developer/garden-notes' && await ruleOf() === 'Use lowercase letters, numbers and dashes.', await hintOf());
  await typeName('garden-notes'); check('new project: a kebab-case name shows no rule message', await hintOf() === 'Will be created as ~/Developer/garden-notes' && await ruleOf() === null);
  await typeName('!!!'); check('new project: no letter or digit = the rule message, Create disabled', await hintOf() === 'Use lowercase letters, numbers and dashes.' && await createDis());
  await typeName('Quiet-App'); check('new project: an existing name = "That name is already a project."', await hintOf() === 'That name is already a project.' && await createDis());
  await typeName('garden-notes');
  check('new project: with a good name Create stays disabled until a type is picked; "Pick a type to continue." shows', await createDis() && await ev(`!document.querySelector('[data-nkind]').hidden && document.querySelector('[data-nkind]').textContent`) === 'Pick a type to continue.');
  const ko = await ev(`[...${NB('[data-nf="kind"]')}.options].map(o => o.value + ':' + o.textContent)`);
  check('new project: type dropdown = placeholder + web/ios/python/api/home/notes/other, placeholder selected', JSON.stringify(ko) === JSON.stringify([':Choose a type…', ...['web', 'ios', 'python', 'api', 'home', 'notes', 'other'].map(k => k + ':' + k)]) && await ev(`${NB('[data-nf="kind"]')}.value`) === '', JSON.stringify(ko));
  await ev(`(() => { const k = ${NB('[data-nf="kind"]')}; k.value = 'web'; k.dispatchEvent(new Event('change', { bubbles: true })); })()`);
  check('new project: picking a type enables Create', !(await createDis()) && await ev(`document.querySelector('[data-nkind]').hidden`));
  const priv = await ev(`(() => { const b = document.querySelector('[data-newbox]'); return { note: b.querySelector('[data-nprivate]').textContent, radios: b.querySelectorAll('input[type=radio], input[type=checkbox]').length, pubOpt: [...b.querySelectorAll('option')].some(o => /public/i.test(o.textContent + o.value)), pubCtl: [...b.querySelectorAll('input, select, button, textarea')].some(n => /public/i.test(n.outerHTML)) }; })()`);
  check('new project: private by default, NO public option or control (only the note "Making a repo public is done later and always asks you")', /^GitHub: private repo \(default\)\. Making a repo public is done later and always asks you\.$/.test(priv.note) && priv.radios === 0 && !priv.pubOpt && !priv.pubCtl, JSON.stringify(priv));
  await typeName('half-typed'); await cdp('Page.navigate', { url: 'file://' + file('empty') + '?tab=projects' }); await sleep(500);
  const nd = await ev(`({ open: !document.querySelector('[data-newbox]').hidden, name: ${NB('[data-nf="name"]')}.value, kind: ${NB('[data-nf="kind"]')}.value, dis: document.querySelector('[data-nform="create"]').disabled })`);
  check('new project: the draft (name and type) survives a redraw', nd.open && nd.name === 'half-typed' && nd.kind === 'web' && !nd.dis, JSON.stringify(nd));
  await ev('window.__msgs.length = 0'); await ev(`document.querySelector('[data-nform="create"]').click()`); m = (await msgs()).filter(x => x.type !== 'editing');
  check('new project: Create posts {type:"newproject", name, kind, about} only (no visibility field)', m.length === 1 && m[0].type === 'newproject' && m[0].name === 'half-typed' && m[0].kind === 'web' && JSON.stringify(Object.keys(m[0]).sort()) === '["about","kind","name","type"]', JSON.stringify(m));


  // ============ task 3: five tabs, Reports (item 6), Setup (item 7), Health new kinds (item 8) ============
  const F3 = require('./panel_v3_tab_fixtures');
  const idea = { id: 'F1', text: 'an idea', tags: [], date: '', verdict: '' };
  const T3PROJ = () => [F.mk('demo-app', 'software', { ideas: { open: [idea, { ...idea, id: 'F2' }], evaluated: [], done: 0, dropped: 0 } }), F.mk('search-app', 'software'), F.mk('arabic-app', 'content'), F.mk('zeta-app', 'software'),
    F.mk('auto-app', 'software', { playbook: F.pb('software', 'full') }), F.STATES.find(s => s.state === 'approval').p];
  const T3DATA = (o = {}) => ({ reports: F3.REPORTS, setup: F3.SETUP(), health: F3.HEALTH(), ...o });
  for (const th of Object.keys(THEMES)) fs.writeFileSync(file('t3-' + th), mkPage(th, T3PROJ(), T3DATA()));
  const TXT_IN = sel => `(() => { const { ratio, bgOf, colorOn } = window.__c, out = [];
    document.querySelectorAll(${JSON.stringify(sel)}).forEach(n => {
      if (!n.getClientRects().length || n.closest('svg') || n.closest('[hidden]')) return;
      const own = [...n.childNodes].some(c => c.nodeType === 3 && c.textContent.trim()); if (!own) return;
      if (n.disabled || n.closest(':disabled')) return;
      const bg = bgOf(n), fg = colorOn(getComputedStyle(n).color, bg), r = ratio(fg, bg);
      out.push({ txt: n.textContent.trim().slice(0, 30), cls: n.className.toString().slice(0, 24), ratio: +r.toFixed(2) });
    }); return out; })()`;
  const TARGETS = `[...document.querySelectorAll('.tabs button, #scroll button, #scroll select')].filter(n => n.getClientRects().length && !n.closest('[hidden]')).map(n => { const r = n.getBoundingClientRect(); return { t: (n.textContent.trim() || n.getAttribute('aria-label') || n.className).slice(0, 24), w: Math.round(r.width), h: Math.round(r.height) }; }).filter(x => x.w < 22 || x.h < 22)`;
  const noHScroll = `(() => { const d = document.documentElement, sc = document.getElementById('scroll'); return d.scrollWidth <= d.clientWidth && sc.scrollWidth <= sc.clientWidth; })()`;
  const rowIds = `[...document.querySelectorAll('.rrow:not([hidden])')].map(r => r.dataset.rid)`;
  const shot3 = async (name, theme, paneSel) => {                                   // a screenshot of the tab bar + the open pane
    const r = await ev(`(() => { const t = document.querySelector('.tabs').getBoundingClientRect(), p = document.querySelector(${JSON.stringify(paneSel)}).getBoundingClientRect(); return { x: 0, y: Math.max(0, t.top - 8 + window.scrollY), w: document.documentElement.clientWidth, h: Math.min(780, p.bottom - t.top + 16) }; })()`);
    const s = await cdp('Page.captureScreenshot', { format: 'png', clip: { x: r.x, y: r.y, width: r.w, height: r.h, scale: 1.5 } }), buf = Buffer.from(s.result.data, 'base64');
    const dest = !(WRITE_SHOTS && keepShot(name, theme)) ? path.join(SCRATCH, `panel-v3-${name}-${theme}.png`) : path.join(SHOTS, `${name}-${theme}.png`);
    fs.writeFileSync(dest, buf); if (keepShot(name, theme)) manifest.push({ state: name, theme, file: `tests/fixtures/panel-v3/${name}-${theme}.png`, width: Math.round(r.w * 1.5), height: Math.round(r.h * 1.5), bytes: buf.length });
  };
  const sizeAll = async () => { await size(315, 1400); await sleep(120); };

  // ---- the tab bar (spec section 1): five tabs, 11.5 px, roving tabindex, arrow keys
  for (const theme of ['light', 'dark', 'hc']) {
    const T = `[${theme}] `;
    await load('t3-' + theme, 315, '?tab=projects');
    const tb = await ev(`(() => { const bar = document.querySelector('.tabs'), tabs = [...bar.querySelectorAll('[role=tab]')]; return { role: bar.getAttribute('role'), names: tabs.map(t => t.dataset.tab), roles: tabs.every(t => t.getAttribute('role') === 'tab'),
      tabindex: tabs.map(t => t.tabIndex), sel: tabs.map(t => t.getAttribute('aria-selected')), ctl: tabs.every(t => document.getElementById(t.getAttribute('aria-controls')) && document.getElementById(t.getAttribute('aria-controls')).getAttribute('role') === 'tabpanel'),
      fs: tabs.map(t => getComputedStyle(t).fontSize), over: tabs.filter(t => t.scrollWidth > t.clientWidth + 1).map(t => t.dataset.tab), barOver: bar.scrollWidth > bar.clientWidth + 1, h: tabs.map(t => Math.round(t.getBoundingClientRect().height)), badges: tabs.map(t => { const i = t.querySelector('i'); return i ? i.textContent + ':' + i.className : ''; }), label: bar.getAttribute('aria-label') }; })()`);
    check(T + 'tab bar: role=tablist, five tabs in order Projects, Reports, Ideas, Health, Setup, each role=tab with aria-controls -> a tabpanel', tb.role === 'tablist' && JSON.stringify(tb.names) === '["projects","reports","ideas","health","setup"]' && tb.roles && tb.ctl && !!tb.label, JSON.stringify(tb));
    check(T + 'tab bar: roving tabindex (only the selected tab is in the tab order), 11.5 px text, 26 px high, no tab text overflows at 315 px even with all five badges', JSON.stringify(tb.tabindex) === '[0,-1,-1,-1,-1]' && JSON.stringify(tb.sel) === '["true","false","false","false","false"]' && tb.fs.every(f => f === '11.5px') && tb.h.every(h => h >= 26) && tb.over.length === 0 && !tb.barOver, JSON.stringify(tb));
    check(T + 'badges: Projects (waiting on you) amber, Reports (failed or blocked this week) amber, Ideas plain, Health red (a stopped run needs you), Setup red (required rows to fix)',
      /^1:.*hamb/.test(tb.badges[0]) && /^2:.*hamb/.test(tb.badges[1]) && /^2:/.test(tb.badges[2]) && !/hbadge/.test(tb.badges[2]) && /hred/.test(tb.badges[3]) && /^\d+:/.test(tb.badges[3]) && /^1:.*hred/.test(tb.badges[4]), JSON.stringify(tb.badges));
    // arrow keys
    await ev(`document.querySelector('[data-tab=projects]').focus()`);
    const walk = []; const step = async (k, code, vk) => { await key(k, code, vk); await sleep(60); walk.push(await ev(`(() => { const a = document.activeElement, sel = [...document.querySelectorAll('[role=tab]')].filter(t => t.getAttribute('aria-selected') === 'true').map(t => t.dataset.tab); return a.dataset.tab + '|' + sel.join() + '|' + [...document.querySelectorAll('[role=tab]')].map(t => t.tabIndex === 0 ? '1' : '0').join('') + '|' + [...document.querySelectorAll('[data-pane]')].filter(s => !s.hidden).map(s => s.dataset.pane).join(); })()`)); };
    await step('ArrowRight', 'ArrowRight', 39); await step('ArrowRight', 'ArrowRight', 39); await step('End', 'End', 35); await step('ArrowRight', 'ArrowRight', 39); await step('ArrowLeft', 'ArrowLeft', 37); await step('Home', 'Home', 36);
    check(T + 'tab bar keyboard: ArrowRight/ArrowLeft/Home/End move focus AND open the tab, wrap around, the tabindex follows', JSON.stringify(walk) === JSON.stringify(['reports|reports|01000|reports', 'ideas|ideas|00100|ideas', 'setup|setup|00001|setup', 'projects|projects|10000|projects', 'setup|setup|00001|setup', 'projects|projects|10000|projects']), JSON.stringify(walk));
    for (const tab of ['projects', 'reports', 'ideas', 'health', 'setup']) {
      await load('t3-' + theme, 315, '?tab=' + tab);
      const ok = await ev(`(() => { const p = [...document.querySelectorAll('[data-pane]')].filter(s => !s.hidden).map(s => s.dataset.pane); const t = document.querySelector('[role=tab][aria-selected=true]'); return p.join() === ${JSON.stringify(tab)} && t.dataset.tab === ${JSON.stringify(tab)}; })()`);
      check(`${T}?tab=${tab}: only that pane shows and its tab is selected`, ok);
    }
  }

  // ---- Reports tab (item 6)
  for (const theme of ['light', 'dark', 'hc']) {
    const T = `[${theme}] reports: `;
    await load('t3-' + theme, 315, '?tab=reports');
    const order = await ev(rowIds);
    check(T + 'FAIL and BLOCKED projects first (newest first), then the rest by newest; inside a project FAIL/BLOCKED first, then newest', JSON.stringify(order) === JSON.stringify(['2026-10-20-CR-012-verify', '2026-10-19-CR-011', '2026-10-18-CR-010', '2026-10-20-CR-020-verify', '2026-10-21-CR-031-review', '2026-10-20-CR-001-verify', 'digest-2026-10-20']), JSON.stringify(order));
    const rw = await ev(`(() => { const r = document.querySelector('.rrow[data-rid="2026-10-20-CR-012-verify"]'); return { tag: r.tagName, chip: r.querySelector('.vchip').textContent, chipRole: r.querySelector('.vchip').getAttribute('role'), title: r.querySelector('.rt').textContent, date: r.querySelector('.rd').textContent, sub: r.querySelector('.rsub').textContent, open: r.querySelector('.ropen').textContent, label: r.getAttribute('aria-label'),
      groups: [...document.querySelectorAll('.rgroup .igname span:first-child')].map(x => x.textContent) }; })()`);
    check(T + 'a row is one button: verdict chip with the word, title, date, grey sub, "Open ›"', rw.tag === 'BUTTON' && rw.chip === 'FAIL' && rw.chipRole === 'img' && rw.title === 'CR-012 Test' && /^\d{1,2} [A-Z][a-z]{2,3}$/.test(rw.date) && rw.sub === '2 of 214 tests failed' && /^Open/.test(rw.open) && /FAIL/.test(rw.label) && /CR-012 Test/.test(rw.label), JSON.stringify(rw));
    check(T + 'grouped by project (digest group is named "Daily")', JSON.stringify(rw.groups) === JSON.stringify(['demo-app', 'search-app', 'zeta-app', 'arabic-app', 'Daily']), JSON.stringify(rw.groups));
    const ar = await ev(`(() => { const r = document.querySelector('.rrow[data-rid="2026-10-20-CR-001-verify"]'); return { t: getComputedStyle(r.querySelector('.rt bdi')).direction, s: getComputedStyle(r.querySelector('.rsub')).direction, en: getComputedStyle(document.querySelector('.rrow[data-rid="2026-10-20-CR-012-verify"] .rt bdi')).direction, dirAttr: r.querySelector('.rt bdi').getAttribute('dir') }; })()`);
    check(T + 'an Arabic CR title and sub render right-to-left (dir=auto); an English one stays left-to-right', ar.t === 'rtl' && ar.s === 'rtl' && ar.en === 'ltr' && ar.dirAttr === 'auto', JSON.stringify(ar));
    // filters
    const fl = [];
    const chip = (k, v) => ev(`document.querySelector('[data-rf="${k}"][data-val="${v}"]').click()`);
    await chip('verdict', 'FAIL'); fl.push(await ev(rowIds)); await chip('verdict', 'BLOCKED'); fl.push(await ev(rowIds)); await chip('verdict', 'PASS'); fl.push((await ev(rowIds)).length);
    await chip('verdict', ''); await chip('kind', 'stage'); fl.push((await ev(rowIds)).length); await chip('kind', 'cr'); fl.push(await ev(rowIds)); await chip('kind', 'digest'); fl.push(await ev(rowIds));
    await chip('kind', ''); await ev(`(() => { const s = document.querySelector('[data-rproj]'); s.value = 'demo-app'; s.dispatchEvent(new Event('change', { bubbles: true })); })()`); fl.push((await ev(rowIds)).length);
    await chip('verdict', 'BLOCKED'); const none = await ev(`({ ids: ${rowIds}.length, msg: !document.querySelector('[data-rnone]').hidden, groups: [...document.querySelectorAll('.rgroup')].filter(g => !g.hidden).length })`);
    const pr = await ev(`[...document.querySelectorAll('[data-rf]')].filter(b => b.getAttribute('aria-pressed') === 'true').map(b => b.dataset.rf + '=' + b.dataset.val)`);
    await chip('verdict', ''); await ev(`(() => { const s = document.querySelector('[data-rproj]'); s.value = ''; s.dispatchEvent(new Event('change', { bubbles: true })); })()`);
    check(T + 'filters: FAIL = 1 row, BLOCKED = 1, PASS = 3, kind Stage = 4, Delivered = 2, Daily = 1, project demo-app = 3; a combination with no match shows "No report matches these filters." and hides the groups; All resets',
      JSON.stringify(fl) === JSON.stringify([['2026-10-20-CR-012-verify'], ['2026-10-20-CR-020-verify'], 3, 4, ['2026-10-19-CR-011', '2026-10-18-CR-010'], ['digest-2026-10-20'], 3]) && none.ids === 0 && none.msg && none.groups === 0 && (await ev(rowIds)).length === 7, JSON.stringify([fl, none]));
    check(T + 'filter chips show their state (aria-pressed) and are at least 22 px', pr.includes('verdict=BLOCKED') && pr.includes('kind=') && !pr.includes('verdict='), JSON.stringify(pr));
    check(T + 'no horizontal scroll; every button, chip and select is at least 22 x 22 px', await ev(noHScroll) && (await ev(TARGETS)).length === 0, JSON.stringify(await ev(TARGETS)));
    const tx = await ev(TXT_IN('#pane-reports *, .tabs i')), bad = tx.filter(x => x.ratio < 4.5);
    check(T + 'text contrast >= 4.5:1 (' + tx.length + ' texts)', tx.length > 20 && bad.length === 0, JSON.stringify(bad.slice(0, 5)));
    await ev('window.__msgs.length = 0'); await ev(`document.querySelector('.rrow[data-rid="2026-10-20-CR-012-verify"]').click()`);
    const rm = (await msgs()).filter(x => x.type !== 'editing');
    check(T + 'a row posts one message {type:"rview", op:"view", id}; the page never sends a path', rm.length === 1 && JSON.stringify(rm[0]) === JSON.stringify({ type: 'rview', op: 'view', id: '2026-10-20-CR-012-verify' }), JSON.stringify(rm));
    if (theme !== 'hc') { await load('t3-' + theme, 315, '?tab=reports'); await sizeAll(); await ev(`document.querySelector('#scroll').scrollTop = 0`); await shot3('reports', theme, '#pane-reports'); }
  }
  // viewer
  const view = (o = {}) => ({ id: '2026-10-20-CR-012-verify', title: 'CR-012 Test', verdict: 'FAIL', ts: F3.now - 3600, project: 'demo-app', kind: 'stage', private: true, text: F3.STAGE_MD, ...o });
  for (const theme of ['light', 'dark', 'hc']) {
    const T = `[${theme}] report viewer: `;
    fs.writeFileSync(file('rv-' + theme), mkPage(theme, T3PROJ(), T3DATA({ rview: view() })));
    await load('rv-' + theme, 315, '?tab=reports');
    const v = await ev(`(() => { const a = document.activeElement, rv = document.querySelector('.rview'); return { focus: a && a.dataset.rv, back: rv.querySelector('[data-rv=back]').textContent, h: rv.querySelector('.rh').textContent, list: !!document.querySelector('.rrow'), kv: [...rv.querySelectorAll('.rkv')].map(x => x.querySelector('b').textContent + '=' + x.querySelector('span').textContent),
      nv: rv.querySelector('.rnv').textContent, chip: rv.querySelector('.vchip').textContent, btns: [...rv.querySelectorAll('.frow .btn')].map(b => b.textContent + ':' + b.dataset.rv), meta: rv.querySelector('.rmeta').textContent }; })()`);
    check(T + 'opens with focus on the back button "‹ Reports"; replaces the list; heading and verdict chip', v.focus === 'back' && /Reports/.test(v.back) && v.h === 'CR-012 Test' && !v.list && v.chip === 'FAIL' && /demo-app/.test(v.meta), JSON.stringify(v));
    check(T + 'the template renders as labelled rows (Verdict, Evidence, Failed, By, Next) and "Not verified" is always shown, last, with the report\'s own text', ['Verdict=FAIL (attempt 1 of 2)', 'Failed=export_pdf_test, export_csv_test'].every(x => v.kv.includes(x)) && v.kv.length === 5 && /^Not verified\s*live PDF printing on a real printer$/.test(v.nv), JSON.stringify(v));
    check(T + 'footer buttons: Open file and Copy path', JSON.stringify(v.btns) === '["Open file:open","Copy path:copy"]');
    await ev('window.__msgs.length = 0'); await ev(`document.querySelector('[data-rv=open]').click(); document.querySelector('[data-rv=copy]').click(); document.querySelector('[data-rv=back]').click()`);
    const vm = (await msgs()).filter(x => x.type !== 'editing');
    check(T + 'Open file / Copy path / back post {type:"rview", op, id} only', JSON.stringify(vm.map(x => x.op + ':' + (x.id || '')).sort()) === JSON.stringify(['back:', 'copy:2026-10-20-CR-012-verify', 'open:2026-10-20-CR-012-verify']) && vm.every(x => x.type === 'rview' && Object.keys(x).length === 3), JSON.stringify(vm));
    await load('rv-' + theme, 315, '?tab=reports'); await ev('window.__msgs.length = 0'); await key('Escape', 'Escape', 27); await sleep(80);
    check(T + 'Esc leaves the viewer (posts back)', (await msgs()).some(x => x.type === 'rview' && x.op === 'back'));
    check(T + 'no horizontal scroll; targets >= 22 px; contrast >= 4.5:1', await ev(noHScroll) && (await ev(TARGETS)).length === 0 && (await ev(TXT_IN('.rview *'))).every(x => x.ratio >= 4.5), JSON.stringify([await ev(TARGETS), (await ev(TXT_IN('.rview *'))).filter(x => x.ratio < 4.5)]));
  }
  // hostile Markdown, a report without "Not verified", an Arabic one, errors, empty and loading states (light)
  fs.writeFileSync(file('rv-hostile'), mkPage('light', T3PROJ(), T3DATA({ rview: view({ id: 'x-1', title: '<b>CR-099</b>', text: F3.HOSTILE_MD }) })));
  await load('rv-hostile', 315, '?tab=reports');
  const hs = await ev(`(() => { const rv = document.querySelector('.rview'); return { xss: window.__xss === undefined, scripts: rv.querySelectorAll('script').length, imgs: rv.querySelectorAll('img').length, anchors: document.querySelectorAll('a').length, handlers: [...document.querySelectorAll('.rview *')].some(n => [...n.attributes].some(a => /^on/i.test(a.name))),
    text: rv.querySelector('.rbody').textContent, h: rv.querySelector('.rh').textContent, hb: rv.querySelectorAll('.rh b').length, lis: rv.querySelectorAll('li').length, libold: rv.querySelectorAll('li b').length, code: rv.querySelectorAll('.rbody pre code').length, ol: rv.querySelectorAll('ol li').length, nv: rv.querySelector('.rnv').textContent, boldInKv: [...rv.querySelectorAll('.rkv b')].length }; })()`);
  check('hostile Markdown is only text: no script, img, link or on* handler, nothing ran; a javascript: link shows as text, an https link as "text (address)"; <b> inside code stays literal', hs.xss && hs.scripts === 0 && hs.imgs === 0 && hs.anchors === 0 && !hs.handlers && /click me \(javascript:window\.__xss=3\)/.test(hs.text) && /docs \(https:\/\/example\.com\/a\?b=1&c=2\)/.test(hs.text) && /code <b>x<\/b>/.test(hs.text) && hs.h === '<b>CR-099</b>' && hs.hb === 0, JSON.stringify(hs));
  check('Markdown subset: lists (ul and ol), **bold**, fenced code (shown literally), headings, Arabic text kept; "Not verified" continues on indented lines', hs.lis === 3 && hs.ol === 1 && hs.libold === 1 && hs.code === 1 && /<script>window\.__xss=4<\/script>/.test(hs.text) && /إصلاح الواجهة العربية بالكامل/.test(hs.text) && /nothing was run against a real device/.test(hs.nv), JSON.stringify(hs));
  fs.writeFileSync(file('rv-nonv'), mkPage('light', T3PROJ(), T3DATA({ rview: view({ id: 'x-2', title: 'CR-050', text: F3.NO_NV_MD, verdict: 'PASS' }) }))); await load('rv-nonv', 315, '?tab=reports');
  check('a report with no "Not verified" line still shows the Not verified block: "This report does not say."', await ev(`document.querySelector('.rnv').textContent`) === 'Not verified' + 'This report does not say.');
  fs.writeFileSync(file('rv-ar'), mkPage('light', T3PROJ(), T3DATA({ rview: view({ id: 'x-3', title: 'CR-001 إصلاح RTL', text: F3.ARABIC_MD, verdict: 'PASS' }) }))); await load('rv-ar', 315, '?tab=reports');
  const va = await ev(`({ dir: getComputedStyle(document.querySelector('.rh bdi')).direction, nv: document.querySelector('.rnv').textContent, kv: getComputedStyle(document.querySelector('.rkv span')).direction })`);
  check('Arabic viewer: heading and Summary render right-to-left; "Not verified: None" shows "None listed"', va.dir === 'rtl' && va.kv === 'rtl' && va.nv === 'Not verified' + 'None listed', JSON.stringify(va));
  fs.writeFileSync(file('rv-err'), mkPage('light', T3PROJ(), T3DATA({ rview: { id: 'x-4', error: 'Report not opened: outside the reports folder.' } }))); await load('rv-err', 315, '?tab=reports');
  check('a report that cannot be shown says why, with the back button focused', await ev(`document.querySelector('.rerr').textContent`) === 'Report not opened: outside the reports folder.' && await ev(`document.activeElement.dataset.rv`) === 'back');
  fs.writeFileSync(file('rp-bad'), mkPage('light', T3PROJ(), T3DATA({ reports: { items: [], status: 'bad' } }))); await load('rp-bad', 315, '?tab=reports');
  await ev('window.__msgs.length = 0'); await ev(`document.querySelector('[data-rv=retry]').click()`);
  check('unreadable index: "Could not read reports. Try again." with a Retry button that posts rview retry', /Could not read reports\. Try again\./.test(await ev(`document.querySelector('.rerr').textContent`)) && (await msgs()).some(x => x.type === 'rview' && x.op === 'retry'));
  fs.writeFileSync(file('rp-empty'), mkPage('light', T3PROJ(), T3DATA({ reports: { items: [], status: 'missing' } }))); await load('rp-empty', 315, '?tab=reports');
  check('no reports yet: "No reports yet. They appear when a stage finishes."', await ev(`document.querySelector('#pane-reports .iempty').textContent`) === 'No reports yet. They appear when a stage finishes.');
  fs.writeFileSync(file('rp-load'), mkPage('light', T3PROJ(), { setup: null, health: null })); await load('rp-load', 315, '?tab=reports');
  check('loading: three skeleton rows, aria-busy', await ev(`document.querySelectorAll('#pane-reports .rskel').length`) === 3 && await ev(`document.querySelector('#pane-reports [aria-busy]').getAttribute('aria-busy')`) === 'true');
  check('reduced motion: skeleton rows have no running animation', await (async () => { await cdp('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-reduced-motion', value: 'reduce' }] }); await load('rp-load', 315, '?tab=reports'); const n = await ev(`document.getAnimations().length`); await cdp('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-reduced-motion', value: 'no-preference' }] }); return n === 0; })());

  // ---- Setup tab (item 7)
  for (const theme of ['light', 'dark', 'hc']) {
    const T = `[${theme}] setup: `;
    await load('t3-' + theme, 315, '?tab=setup');
    const st = await ev(`(() => { const rows = [...document.querySelectorAll('.chk')]; return { n: rows.length, head: document.querySelector('.shead b').textContent, ids: rows.map(r => r.dataset.row).join(), cls: rows.map(r => r.className.replace('chk ', '')).join(), recheck: document.querySelector('[data-setup=recheck]').className,
      btns: Object.fromEntries(rows.map(r => [r.dataset.row, [...r.querySelectorAll('.cacts .btn')].map(b => b.textContent).join('+')])), need: Object.fromEntries(rows.map(r => [r.dataset.row, r.dataset.need])), ready: document.querySelector('[data-ready]').textContent }; })()`);
    check(T + `${F3.SETUP().rows.length} rows in the CLI order, red / green / grey classes, header "Setup · N of M ready" (the optional Describe-your-work row is not counted)`, st.n === F3.ROWS().length && st.ids === F3.ROWS().map(r => r.id).join() && st.head === 'Setup · ' + F3.SETUP().rows.filter(r => r.state === 'green').length + ' of ' + (F3.ROWS().length - 1) + ' ready'
      && st.cls === 'ok ok ok ok ok red red ok ok ok skip red ok skip skip skip ok skip skip skip skip red'.split(' ').join(),
      JSON.stringify(st));
    const noSkip = Object.entries(st.need).filter(([, nd]) => nd === 'required').every(([id]) => !/Skip/.test(st.btns[id]));
    check(T + 'required rows (the CLI\'s need field) have no Skip, even when red', noSkip && st.btns['git-id'] === 'Fix' && st.need['git-id'] === 'required', JSON.stringify(st.btns));
    check(T + 'a red recommended or optional row has Fix + Skip; a skipped one has "Turn on" and no Skip; advisory and publishing rows have no button; Remote Control and Ask inbox are off by default and say "Turn on"', st.btns.github === 'Fix+Skip' && st.btns.docker === 'Fix+Skip' && st.btns.notify === 'Turn on' && st.btns.connectors === '' && st.btns.backup === '' && st.btns.publishing === '' && st.btns['describe-work'] === '' && st.btns['remote-control'] === 'Turn on' && st.btns['ask-inbox'] === 'Turn on' && st.btns.ios === '', JSON.stringify(st.btns));
    check(T + 'Re-check all is the primary button while a required row is red; the publishing row says it is not set up on purpose', /primary/.test(st.recheck) && await ev(`document.querySelector('[data-row=publishing] .creason').textContent`) === 'Not set up here on purpose: publishing always asks you.' && /Finish the required rows first/.test(st.ready), JSON.stringify(st.recheck));
    const row = await ev(`(() => { const r = document.querySelector('[data-row=git-id]'); return { mark: r.querySelector('.cmark').getAttribute('aria-label'), glyph: r.querySelector('.cmark').textContent, reason: r.querySelector('.creason').textContent, hint: r.querySelector('.chint').textContent, need: r.querySelector('.cneed').textContent, fixAria: r.querySelector('[data-setup=fix]').getAttribute('aria-label'),
      ok: document.querySelector('[data-row=node] .cmark').textContent + document.querySelector('[data-row=node] .cmark').getAttribute('aria-label'), grey: document.querySelector('[data-row=notify] .cmark').textContent + document.querySelector('[data-row=notify] .cmark').getAttribute('aria-label'), inputs: document.querySelectorAll('#pane-setup input, #pane-setup textarea, #pane-setup select').length }; })()`);
    check(T + 'row anatomy: mark with a word (✕ Needs fixing / ✓ Ready / – Skipped), name, Required, grey reason, plain-text hint; Fix has an aria-label with the name; the pane has no input of any kind', row.glyph === '✕' && row.mark === 'Needs fixing' && row.need === 'Required' && /not set/.test(row.reason) && /git config --global user\.name/.test(row.hint) && row.fixAria === 'Fix Git name and email' && row.ok === '✓Ready' && row.grey === '–Skipped' && row.inputs === 0, JSON.stringify(row));
    await ev('window.__msgs.length = 0'); await ev(`document.querySelector('[data-row=git-id] [data-setup=fix]').click(); document.querySelector('[data-row=github] [data-setup=skip]').click(); document.querySelector('[data-setup=recheck]').click()`);
    const sm = (await msgs()).filter(x => x.type !== 'editing');
    check(T + 'Fix / Skip / Re-check post {type:"setup", op, id}; the page sends no command text (Re-check turns into "Checking…" until the answer redraws the page)', JSON.stringify(sm) === JSON.stringify([{ type: 'setup', op: 'fix', id: 'git-id' }, { type: 'setup', op: 'skip', id: 'github' }, { type: 'setup', op: 'recheck', id: '' }]) && await ev(`document.querySelector('[data-setup=recheck]').textContent`) === 'Checking…', JSON.stringify(sm));
    check(T + 'no horizontal scroll; targets >= 22 px; contrast >= 4.5:1', await ev(noHScroll) && (await ev(TARGETS)).length === 0 && (await ev(TXT_IN('#pane-setup *, .tabs i'))).every(x => x.ratio >= 4.5), JSON.stringify([await ev(TARGETS), (await ev(TXT_IN('#pane-setup *'))).filter(x => x.ratio < 4.5).slice(0, 5)]));
    const icr = await ev(`(() => { const { ratio, bgOf, colorOn } = window.__c; return [...document.querySelectorAll('.cmark')].map(m => { const s = getComputedStyle(m), card = bgOf(m.closest('.chk')), own = bgOf(m); return { ring: +ratio(colorOn(s.borderTopColor, card), card).toFixed(2), glyph: +ratio(colorOn(s.color, own), own).toFixed(2) }; }); })()`);
    check(T + 'marks: ring >= 3:1 against the row, glyph >= 3:1 against the mark', icr.length === F3.ROWS().length && icr.every(x => x.ring >= 3 && x.glyph >= 3), JSON.stringify(icr.filter(x => x.ring < 3 || x.glyph < 3)));
    { await load('t3-' + theme, 315, '?tab=setup'); await sizeAll(); await ev(`document.querySelector('#scroll').scrollTop = 0`); await shot3('setup', theme, '#pane-setup'); }
  }
  // Fix then Re-check flips a row (the page is a pure function of the data: the extension re-renders after `shipm init --check --json`)
  fs.writeFileSync(file('setup-after'), mkPage('light', T3PROJ(), T3DATA({ setup: F3.SETUP({ 'git-id': 'green' }) })));
  await load('t3-light', 315, '?tab=setup');
  const before = await ev(`({ head: document.querySelector('.shead b').textContent, cls: document.querySelector('[data-row=git-id]').className, badge: document.querySelector('[data-tab=setup] i').textContent })`);
  await load('setup-after', 315, '?tab=setup');
  const after = await ev(`({ head: document.querySelector('.shead b').textContent, cls: document.querySelector('[data-row=git-id]').className, btns: document.querySelectorAll('[data-row=git-id] .btn').length, badge: document.querySelector('[data-tab=setup] i') && document.querySelector('[data-tab=setup] i').textContent })`);
  check('Fix then Re-check: the git-id row flips red -> green (no buttons), the header count goes up by one and the Setup badge drops by one (1 -> none)', /red/.test(before.cls) && /ok/.test(after.cls) && after.btns === 0 && before.head === 'Setup · 10 of ' + (F3.ROWS().length - 1) + ' ready' && after.head === 'Setup · 11 of ' + (F3.ROWS().length - 1) + ' ready' && before.badge === '1' && after.badge === null, JSON.stringify([before, after]));
  // required rows all green: Re-check is no longer primary, no banner, no badge
  fs.writeFileSync(file('setup-green'), mkPage('light', T3PROJ(), T3DATA({ setup: F3.SETUP({ 'git-id': 'green', github: 'green', docker: 'green' }) }))); await load('setup-green', 315, '?tab=setup');
  check('all required rows green: Re-check all is not primary, "Everything required is ready."', !/primary/.test(await ev(`document.querySelector('[data-setup=recheck]').className`)) && /Everything required is ready/.test(await ev(`document.querySelector('[data-ready]').textContent`)));
  fs.writeFileSync(file('setup-err'), mkPage('light', T3PROJ(), T3DATA({ setup: { error: true, rows: [], ready: false, at: 1 } }))); await load('setup-err', 315, '?tab=setup');
  check('a check that cannot be read: one red row "Could not read setup state" and a primary Re-check all', await ev(`document.querySelector('#pane-setup .chk b').textContent`) === 'Could not read setup state' && /primary/.test(await ev(`document.querySelector('[data-setup=recheck]').className`)) && await ev(`document.querySelectorAll('#pane-setup .chk').length`) === 1);
  fs.writeFileSync(file('setup-load'), mkPage('light', T3PROJ(), { reports: F3.REPORTS, setup: null, health: F3.HEALTH() })); await load('setup-load', 315, '?tab=setup');
  check('check not answered yet: "Setup" with three skeleton rows and no counts', await ev(`document.querySelectorAll('#pane-setup .rskel').length`) === 3 && await ev(`document.querySelector('.shead b').textContent`) === 'Setup' && await ev(`document.querySelector('[data-tab=setup] i')`) === null);
  // a secret in a CLI text never reaches the page
  const poison = F3.SETUP(); poison.rows[6].detail = 'login failed token=' + 'ghp' + '_abcdefghijklmnopqrstuvwxyz0123456789' + ' password=hunter2 ' + 'sk-ant' + '-api03-abcdefghijklmnopqrstuvwxyz' + ''; poison.rows[6].connect.text = 'use ' + 'ghp' + '_abcdefghijklmnopqrstuvwxyz0123456789' + ' here';
  fs.writeFileSync(file('setup-secret'), mkPage('light', T3PROJ(), T3DATA({ setup: poison }))); await load('setup-secret', 315, '?tab=setup');
  const secTxt = await ev(`document.querySelector('#pane-setup').textContent + document.querySelector('#pane-setup').innerHTML`);
  check('no secret is ever rendered: token-shaped text and password=... in a CLI reason or hint is hidden', !/ghp_|hunter2|sk-ant/.test(secTxt) && /\[hidden\]/.test(secTxt));
  // the Projects tab: a banner (not a lock) when required rows are red
  await load('t3-light', 315, '?tab=projects');
  const bn = await ev(`({ txt: document.querySelector('.setupbanner') && document.querySelector('.setupbanner').textContent, cards: document.querySelectorAll('.card').length })`);
  check('Projects shows "Finish setup first" with a button that opens Setup while required rows are red, and the cards stay usable', /Finish setup first/.test(bn.txt) && /1 required row needs fixing/.test(bn.txt) && bn.cards === T3PROJ().length);
  await ev(`document.querySelector('.setupbanner [data-tab=setup]').click()`); await sleep(60);
  check('the banner button opens the Setup tab', await ev(`[...document.querySelectorAll('[data-pane]')].filter(s => !s.hidden).map(s => s.dataset.pane).join()`) === 'setup' && await ev(`document.querySelectorAll('[role=tab][aria-selected=true]').length`) === 1);

  // ---- Health tab (item 8): the new kinds
  const HNEW = F3.HEALTH_NEW;
  for (const theme of ['light', 'dark', 'hc']) {
    const T = `[${theme}] health: `;
    await load('t3-' + theme, 315, '?tab=health');
    const hr = await ev(`(() => { const o = {}; document.querySelectorAll('#pane-health [data-item]').forEach(r => { o[r.dataset.item] = { btns: [...r.querySelectorAll('.btn')].map(b => b.textContent.trim()), reason: [...r.querySelectorAll('.hwhy,.hproof,.hreco')].map(x => x.textContent.trim()).join(' | '), cls: r.className, title: r.querySelector('b').textContent }; }); return o; })()`);
    check(T + 'all 10 new kinds render (stage_stuck, verify_failed_twice, autopilot_paused, autopilot_stopped, budget_reached, autopilot_ended_time, merge_waiting, cr_orphan, stray_browser, stray_testrun)', HNEW.every(i => hr[i.id]) && Object.keys(hr).length === HNEW.length, JSON.stringify(Object.keys(hr)));
    check(T + 'every row has a Fix-type button or a specific reason: fix kinds have a primary Fix; wait kinds show the next step as text', HNEW.every(i => { const r = hr[i.id]; return i.mode === 'fix' ? r.btns.includes('Fix') : (r.reason.length > 20 && r.reason.includes(i.next)); }), JSON.stringify(hr));
    const act = Object.fromEntries(HNEW.map(i => [i.kind, hr[i.id].btns.join('+')]));
    check(T + 'Open chat on the stopped-run rows, Back to guided on the ended/stopped autopilot rows of a full project, nothing invented on the others', act.verify_failed_twice === 'Open chat' && act.autopilot_stopped === 'Open chat+Back to guided' && act.autopilot_paused === 'Open chat+Back to guided' && act.budget_reached === 'Back to guided' && act.autopilot_ended_time === 'Back to guided' && act.merge_waiting === 'Open chat' && act.cr_orphan === 'Open chat'
      && act.stage_stuck === 'Fix' && act.stray_browser === 'Fix' && act.stray_testrun === 'Fix', JSON.stringify(act));
    check(T + 'severity dots: red for verify_failed_twice / autopilot_paused / autopilot_stopped, amber for budget, time, merge, orphan', ['verify_failed_twice', 'autopilot_paused', 'autopilot_stopped'].every(k => /hk-red/.test(hr[HNEW.find(i => i.kind === k).id].cls)) && ['budget_reached', 'autopilot_ended_time', 'merge_waiting', 'cr_orphan'].every(k => /hk-amber/.test(hr[HNEW.find(i => i.kind === k).id].cls)));
    const secs = await ev(`[...document.querySelectorAll('#pane-health .hsech')].map(h => h.textContent)`);
    check(T + 'sections: "Needs you" (fix kinds) then "Waiting on you" (the wait kinds)', secs[0] === 'Needs you' && secs[1] === 'Waiting on you', JSON.stringify(secs));
    check(T + 'no horizontal scroll; targets >= 22 px; contrast >= 4.5:1', await ev(noHScroll) && (await ev(TARGETS)).length === 0 && (await ev(TXT_IN('#pane-health *, .tabs i'))).every(x => x.ratio >= 4.5), JSON.stringify([await ev(TARGETS), (await ev(TXT_IN('#pane-health *'))).filter(x => x.ratio < 4.5).slice(0, 6)]));
    if (theme === 'light') {
      await ev('window.__msgs.length = 0'); await ev(`document.querySelector('[data-item="${HNEW.find(i => i.kind === 'verify_failed_twice').id}"] [data-act=open]').click()`);
      let mm = (await msgs()).filter(x => x.type !== 'editing');
      check(T + 'Open chat posts {type:"open", dir} for that project only', mm.length === 1 && mm[0].type === 'open' && mm[0].dir === '/x/search-app', JSON.stringify(mm));
      await ev('window.__msgs.length = 0'); const bsel = `document.querySelector('[data-item="${HNEW.find(i => i.kind === 'budget_reached').id}"] [data-act=ap]')`;
      await ev(`${bsel}.click()`); const armed = await ev(`${bsel}.textContent`); mm = (await msgs()).filter(x => x.type !== 'editing');
      await ev(`${bsel}.click()`); const mm2 = (await msgs()).filter(x => x.type !== 'editing');
      check(T + 'Back to guided asks "Sure?" in place, then posts {type:"act", act:"ap", to:"guided", project} once', armed === 'Sure?' && mm.length === 0 && mm2.length === 1 && mm2[0].type === 'act' && mm2[0].act === 'ap' && mm2[0].to === 'guided' && mm2[0].project === 'auto-app', JSON.stringify([armed, mm, mm2]));
    }
    { await load('t3-' + theme, 315, '?tab=health'); await sizeAll(); await ev(`document.querySelector('#scroll').scrollTop = 0`); await shot3('health', theme, '#pane-health'); }
  }
  // unknown and malformed kinds never crash the tab
  const odd = [F3.hi('wibble', 'demo-app', { title: 'Something new (a kind this panel does not know)', why: 'A future watcher raised this.', mode: 'info' }), { id: 'broken1', kind: 'verify_failed_twice', project: 'demo-app', severity: 'info' }, { id: 'broken2' }, ...F3.HEALTH_NEW.slice(2, 3)];
  fs.writeFileSync(file('h-odd'), mkPage('light', T3PROJ(), T3DATA({ health: F3.HEALTH(odd, 0, 0) }))); await load('h-odd', 315, '?tab=health');
  const ho = await ev(`({ rows: document.querySelectorAll('#pane-health [data-item]').length, titles: [...document.querySelectorAll('#pane-health [data-item] b')].map(b => b.textContent), err: window.__err || 0 })`);
  check('an unknown kind, an item without title/since and an item with only an id render as rows (no crash); the generic row shows the item\'s own words', ho.rows === 4 && ho.titles.includes('Something new') && ho.titles.length === 4, JSON.stringify(ho));
  // badge colour rules
  let bc = 0; const badge = async (items, red, amber) => { const bf = 'h-b' + (++bc); fs.writeFileSync(file(bf), mkPage('light', T3PROJ(), T3DATA({ health: F3.HEALTH(items, red, amber) }))); await load(bf, 315, '?tab=projects'); return ev(`(() => { const i = document.querySelector('[data-tab=health] i'); return i ? i.textContent + ':' + i.className : ''; })()`); };
  const only = k => F3.HEALTH_NEW.filter(i => i.kind === k);
  const b1 = await badge(only('budget_reached'), 0, 0), b2 = await badge(only('verify_failed_twice'), 0, 0), b3 = await badge(only('stage_stuck'), 0, 1), b4 = await badge([], 0, 0), b5 = await badge(only('stage_stuck'), 1, 0);
  check('Health tab badge (spec section 8): amber for budget reached, red for a test failed twice, amber for a stuck stage, none when empty, red when the watcher counts a red item', /^1:.*hamb/.test(b1) && /^1:.*hred/.test(b2) && /^1:.*hamb/.test(b3) && b4 === '' && /^1:.*hred/.test(b5), JSON.stringify([b1, b2, b3, b4, b5]));

  // ---- Panel v3 task 4b: Ask aside (F3), Ask inbox card (F4), Remote Control row, token card long-chats row
  const NOTE4 = '2026-10-21-what-is-a-monad.md';
  const askProj = (o = {}) => F.mk('ask', 'notes', { dir: '/x/ask', state: 'needs-input', ask: { inbox: true, questions_today: 3, notes: 1, last: { title: 'What is a monad?', path: 'docs/notes/' + NOTE4, ts: 1 }, ...o } });
  const P4 = (askO) => [F.mk('chat-app', 'software', { chatOpen: true }), F.mk('nochat-app', 'software', { chatOpen: false }), askProj(askO)];
  const TIP = 'Types /btw into this chat. /btw uses the same model as this chat. We found no way to change it, so there is no model choice here. For a different model, use Ask a question. Needs the Claude extension 2.1.227 or later.';
  const post = async fn => { await ev('window.__msgs.length = 0'); await ev(fn); return (await msgs()).filter(x => x.type !== 'editing'); };
  for (const theme of ['light', 'dark', 'hc']) {
    const T = `[${theme}] ask: `;
    fs.writeFileSync(file('ask-' + theme), mkPage(theme, P4(), T3DATA({ remote: { state: 'off' } })));
    await load('ask-' + theme, 360, '?tab=projects');
    const as = await ev(`(() => { const q = n => document.querySelector('.card[data-dir="/x/' + n + '"] .btn.aside'); const a = q('chat-app'), b = q('nochat-app'); return { aOn: !a.disabled, aTitle: a.title, aText: a.textContent, aVis: a.getClientRects().length > 0, bOff: b.disabled, bTitle: b.title, bAria: b.getAttribute('aria-label'), bVis: b.getClientRects().length > 0, aAria: a.getAttribute('aria-label') }; })()`);
    check(T + 'Ask aside: a quiet button on every card; enabled with the exact tooltip when the chat is open', as.aOn && as.aVis && as.aText === 'Ask aside' && as.aTitle === TIP && /Ask aside in the chat-app chat/.test(as.aAria), JSON.stringify(as));
    check(T + 'Ask aside: disabled with a specific reason (open the project chat first) when no chat is open; the reason is also in the accessible name', as.bOff && as.bVis && /^Open the nochat-app chat first\./.test(as.bTitle) && as.bTitle.endsWith(TIP) && /unavailable|first/.test(as.bAria) && /Open the nochat-app chat first/.test(as.bAria), JSON.stringify(as));
    const m1 = await post(`document.querySelector('.card[data-dir="/x/chat-app"] .btn.aside').click()`);
    check(T + 'Ask aside click posts only {type:"ask", op:"aside", project} (no text: the extension owns "/btw ")', JSON.stringify(m1) === JSON.stringify([{ type: 'ask', op: 'aside', project: 'chat-app' }]), JSON.stringify(m1));
    const m2 = await post(`document.querySelector('.card[data-dir="/x/nochat-app"] .btn.aside').click()`);
    check(T + 'Ask aside click on the disabled button posts nothing', m2.length === 0, JSON.stringify(m2));
    // narrow cards: the button hides, the same action sits in the ⋯ menu
    const vis = async () => ev(`(() => { const c = document.querySelector('.card[data-dir="/x/chat-app"]'); return { btn: c.querySelector('.btn.aside').getClientRects().length > 0, item: c.querySelector('.mi.askmi').getClientRects().length > 0 }; })()`);
    const w360 = await vis(); await size(315); await sleep(80); const w315 = await vis(); await size(280); await sleep(120); const w280 = await vis();
    check(T + 'width rule: >= 300 px the card shows the quiet button (menu item hidden), narrower the button is hidden and the menu has "Ask aside"', w360.btn && !w360.item && w315.btn && !w315.item && !w280.btn, JSON.stringify([w360, w315, w280]));
    await ev(`document.querySelector('.card[data-dir="/x/chat-app"] .btn.more').click()`); await sleep(60);
    const mi = await ev(`(() => { const i = document.querySelector('.card[data-dir="/x/chat-app"] .mi.askmi'), j = document.querySelector('.card[data-dir="/x/nochat-app"] .mi.askmi'); return { vis: i.getClientRects().length > 0, txt: i.textContent, title: i.title, role: i.getAttribute('role'), offOther: j.disabled, otherTitle: j.title }; })()`);
    check(T + 'narrow: the ⋯ menu item "Ask aside" is visible with the tooltip; on a project without a chat it is disabled with the reason', mi.vis && mi.txt === 'Ask aside' && mi.title === TIP && mi.role === 'menuitem' && mi.offOther && /^Open the nochat-app chat first/.test(mi.otherTitle), JSON.stringify(mi));
    const m3 = await post(`document.querySelector('.card[data-dir="/x/chat-app"] .mi.askmi').click()`);
    check(T + 'narrow: the menu item posts the same {type:"ask", op:"aside", project} and closes the menu', JSON.stringify(m3) === JSON.stringify([{ type: 'ask', op: 'aside', project: 'chat-app' }]) && await ev(`document.querySelector('.menu:not([hidden])') === null`), JSON.stringify(m3));
    check(T + 'narrow 280 px: no horizontal scroll, targets >= 22 px, contrast >= 4.5:1 (enabled controls)', await ev(noHScroll) && (await ev(TARGETS)).length === 0 && (await ev(TXT_IN('.card .btns *, .askcard *, .menu *'))).every(x => x.ratio >= 4.5), JSON.stringify([await ev(TARGETS), (await ev(TXT_IN('.card .btns *, .askcard *'))).filter(x => x.ratio < 4.5)]));
    await size(315); await sleep(80);

    // ---- the Ask inbox card
    const ic = await ev(`(() => { const c = document.querySelector('.askcard'); const inp = c.querySelector('[data-askq]'), lab = c.querySelector('label'); return { n: document.querySelectorAll('.askcard').length, title: c.querySelector('.name').textContent, sub: c.querySelector('.sub').textContent, label: lab.textContent.trim(), lblFor: lab.contains(inp), ph: inp.placeholder, max: inp.maxLength, type: inp.type, count: c.querySelector('[data-askcount]').textContent, goOff: c.querySelector('[data-askgo]').disabled, go: c.querySelector('[data-askgo]').textContent, today: c.querySelector('[data-asktoday]').textContent, last: c.querySelector('.alast .alt').textContent, btns: [...c.querySelectorAll('.alast .btn')].map(b => b.textContent), dataDir: c.hasAttribute('data-dir'), cards: [...document.querySelectorAll('.card[data-dir]')].map(x => x.dataset.dir).join(), now: document.querySelector('.nowblk').textContent, dir: inp.getAttribute('dir') }; })()`);
    check(T + 'Ask card: one compact card "Ask" / "Questions that are not a project", a labelled one-line box "Ask anything…" (max 2000, dir=auto), counter "0 of 2000" and a disabled Ask button', ic.n === 1 && ic.title === 'Ask' && ic.sub === 'Questions that are not a project' && ic.label === 'Ask anything…' && ic.lblFor && ic.ph === 'Ask anything…' && ic.max === 2000 && ic.type === 'text' && ic.dir === 'auto' && ic.count === '0 of 2000' && ic.goOff && ic.go === 'Ask', JSON.stringify(ic));
    check(T + 'Ask card: "Questions today 3 of 20", the last note title with Open and "Promote to idea"', ic.today === 'Questions today 3 of 20' && /Last answer: What is a monad\?/.test(ic.last) && ic.btns.join() === 'Open,Promote to idea', JSON.stringify(ic));
    check(T + 'Ask card: it is not a project card (no data-dir, so a click never opens a chat) and it is not in the Waiting block, although its data says needs-input', !ic.dataDir && ic.cards === '/x/chat-app,/x/nochat-app' && !/\bask\b/i.test(ic.now) && await ev(`document.querySelector('[data-tab=projects] i') === null`), JSON.stringify([ic.cards, ic.now]));
    const typeIn = v => ev(`(() => { const i = document.querySelector('[data-askq]'); i.value = ${JSON.stringify(v)}; i.dispatchEvent(new Event('input', { bubbles: true })); const c = document.querySelector('[data-askcount]'); return { count: c.textContent, off: document.querySelector('[data-askgo]').disabled, bad: c.classList.contains('bad') }; })()`);
    const t1 = await typeIn('hello'), t2 = await typeIn('   '), t3 = await typeIn('-rf x'), t4 = await typeIn('a'.repeat(2001)), t5 = await typeIn('a'.repeat(2000)), t6 = await typeIn('😀'.repeat(3)), t7 = await typeIn('ما هو؟');
    check(T + 'Ask input: counter in characters; Ask is on for 1-2000 characters, off for empty, spaces only, a leading "-" (with its own message) and 2001', t1.count === '5 of 2000' && !t1.off && t2.off && t3.off && t3.bad && /start the question/i.test(t3.count) && t4.off && !t5.off && t5.count === '2000 of 2000' && t6.count === '3 of 2000' && t7.count === '6 of 2000' && !t7.off, JSON.stringify([t1, t2, t3, t4, t5, t6, t7]));
    const hos = ["it's a \"test\" $(touch x) `y` ; rm -rf ~ && echo", 'ما هو الفرق بين git و GitHub؟', '<b>x</b> \\n %s'];
    for (const q of hos) { await typeIn(q); const mm = await post(`document.querySelector('[data-askgo]').click()`);
      check(T + 'Ask posts the question text unchanged and nothing else: ' + JSON.stringify(q).slice(0, 36), JSON.stringify(mm) === JSON.stringify([{ type: 'ask', op: 'type', q }]) && !/shipm/.test(JSON.stringify(mm)), JSON.stringify(mm)); }
    check(T + 'after Ask the box is empty and Ask is off again (the command now waits in the terminal, nothing was run)', await ev(`document.querySelector('[data-askq]').value === '' && document.querySelector('[data-askgo]').disabled && document.querySelector('[data-askcount]').textContent === '0 of 2000'`));
    await typeIn('via enter'); const me = await post(`document.querySelector('[data-askq]').dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))`);
    check(T + 'Enter in the box does the same as the Ask button; with an empty box Enter posts nothing', JSON.stringify(me) === JSON.stringify([{ type: 'ask', op: 'type', q: 'via enter' }]) && (await post(`document.querySelector('[data-askq]').dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))`)).length === 0, JSON.stringify(me));
    const mo = await post(`document.querySelector('.alast [data-ask=open]').click()`), mp = await post(`document.querySelector('.alast [data-ask=promote]').click()`), mc = await post(`document.querySelector('.askcard .name').click()`);
    check(T + 'Open and Promote post only the op (the note comes from the data, never from the page); a click on the card posts nothing', JSON.stringify(mo) === JSON.stringify([{ type: 'ask', op: 'open', project: '' }]) && JSON.stringify(mp) === JSON.stringify([{ type: 'ask', op: 'promote', project: '' }]) && mc.length === 0, JSON.stringify([mo, mp, mc]));
    check(T + 'Ask card: no horizontal scroll, targets >= 22 px, contrast >= 4.5:1, the Ask button and both note buttons are real buttons with names', await ev(noHScroll) && (await ev(TARGETS)).length === 0 && (await ev(TXT_IN('.askcard *'))).every(x => x.ratio >= 4.5) && await ev(`[...document.querySelectorAll('.askcard button')].every(b => (b.getAttribute('aria-label') || b.textContent).trim().length > 1)`), JSON.stringify([await ev(TARGETS), (await ev(TXT_IN('.askcard *'))).filter(x => x.ratio < 4.5)]));
    await ev(`document.querySelector('[data-askq]').focus()`); await sleep(40);
    const foc = await ev(`(() => { const i = document.querySelector('[data-askq]'), cs = getComputedStyle(i); return { ow: cs.outlineWidth, os: cs.outlineStyle, active: document.activeElement === i }; })()`);
    check(T + 'Ask input shows a focus outline', foc.active && foc.os !== 'none' && parseFloat(foc.ow) >= 1, JSON.stringify(foc));
    if (theme !== 'hc' && WRITE_SHOTS) {
      await load('ask-' + theme, 315, '?tab=projects'); await sizeAll(); await typeIn('What is the difference between RAM and storage?');
      const r = await ev(`(() => { const b = document.querySelector('.askcard').getBoundingClientRect(); return { x: b.left - 8, y: b.top - 8 + window.scrollY, w: b.width + 16, h: b.height + 16 }; })()`);
      const s = await cdp('Page.captureScreenshot', { format: 'png', clip: { x: r.x, y: r.y, width: r.w, height: r.h, scale: 2 } }), buf = Buffer.from(s.result.data, 'base64');
      fs.writeFileSync(path.join(SHOTS, `ask-inbox-${theme}.png`), buf); manifest.push({ state: 'ask-inbox', theme, file: `tests/fixtures/panel-v3/ask-inbox-${theme}.png`, width: Math.round(r.w * 2), height: Math.round(r.h * 2), bytes: buf.length });
    }
    await ev(`sessionStorage.clear()`);                      // the half-typed question is kept across redraws: do not let it leak into the next theme
  }
  // Ask card states: nothing yet, limit reached, hostile and long titles, no Ask project at all, and the page text of the quiet button in the card
  fs.writeFileSync(file('ask-empty'), mkPage('light', P4({ last: null, notes: 0, questions_today: 0 }), T3DATA())); await load('ask-empty', 315, '?tab=projects');
  check('Ask card, no answers yet: the empty-state text, no Open / Promote buttons, "Questions today 0 of 20"', /No answers yet/.test(await ev(`document.querySelector('.askcard').textContent`)) && await ev(`document.querySelectorAll('.askcard [data-ask=open], .askcard [data-ask=promote]').length`) === 0 && await ev(`document.querySelector('[data-asktoday]').textContent`) === 'Questions today 0 of 20');
  fs.writeFileSync(file('ask-full'), mkPage('light', P4({ questions_today: 20, last: { title: '<img src=x onerror=alert(1)> ' + 'long '.repeat(40), path: 'docs/notes/' + NOTE4, ts: 1 } }), T3DATA())); await load('ask-full', 315, '?tab=projects');
  const af = await ev(`({ today: document.querySelector('[data-asktoday]').textContent, bad: document.querySelector('[data-asktoday]').classList.contains('bad'), imgs: document.querySelectorAll('.askcard img').length, html: document.querySelector('.askcard').innerHTML.includes('<img'), sc: document.documentElement.scrollWidth <= document.documentElement.clientWidth })`);
  check('Ask card at the daily limit says so; a hostile or very long note title is shown as text only (no element, no overflow)', /Questions today 20 of 20/.test(af.today) && /limit is reached/.test(af.today) && af.bad && af.imgs === 0 && !af.html && af.sc, JSON.stringify(af));
  // the daily limit is the CLI's (config ask.daily_limit): "3 of 5", a missing / out-of-range value falls back to 20, at the limit Ask stays off with the reason
  const limToday = async (lim, n) => { fs.writeFileSync(file('ask-lim'), mkPage('light', P4({ questions_today: n, ...(lim === undefined ? {} : { limit: lim }) }), T3DATA())); await load('ask-lim', 315, '?tab=projects'); return ev(`document.querySelector('[data-asktoday]').textContent`); };
  check('Ask limit: limit 5 shows "Questions today 3 of 5"; a missing limit shows "of 20"; 0, 500, 2.5 and "7" fall back to 20', await limToday(5, 3) === 'Questions today 3 of 5' && await limToday(undefined, 3) === 'Questions today 3 of 20' && await limToday(0, 3) === 'Questions today 3 of 20' && await limToday(500, 3) === 'Questions today 3 of 20' && await limToday(2.5, 3) === 'Questions today 3 of 20' && await limToday('7', 3) === 'Questions today 3 of 20');
  await limToday(5, 5); await ev(`(() => { const i = document.querySelector('[data-askq]'); i.value = 'a real question'; i.dispatchEvent(new Event('input', { bubbles: true })); })()`);
  const lf = await ev(`({ dis: document.querySelector('[data-askgo]').disabled, title: document.querySelector('[data-askgo]').title, bad: document.querySelector('[data-asktoday]').classList.contains('bad') })`);
  check('Ask limit: at 5 of 5 the Ask button stays disabled even with a typed question, title "Not now: today\'s 5 questions are used."', lf.dis && lf.title === "Not now: today's 5 questions are used." && lf.bad, JSON.stringify(lf));
  await limToday(5, 4); await ev(`(() => { const i = document.querySelector('[data-askq]'); i.value = 'a real question'; i.dispatchEvent(new Event('input', { bubbles: true })); })()`);
  check('Ask limit: at 4 of 5 the Ask button is on', await ev(`!document.querySelector('[data-askgo]').disabled`));
  check('Ask limit: the hard-coded 20 is gone from ask.js usage and strings.js (the page reads ask.limit)', !/\b20\b/.test(fs.readFileSync(path.join(ROOT, 'vscode-ext/shipmiracle-panel/strings.js'), 'utf8').split('\n').filter(l => /today|fullTip/.test(l)).join('\n')));
  fs.writeFileSync(file('ask-none'), mkPage('light', [F.mk('chat-app', 'software', { chatOpen: true }), F.mk('ask', 'notes', { dir: '/x/ask' })], T3DATA())); await load('ask-none', 315, '?tab=projects');
  check('without ask data (inbox not set up) there is no Ask card; a project that is merely called "ask" is an ordinary card', await ev(`document.querySelectorAll('.askcard').length`) === 0 && await ev(`document.querySelectorAll('.card[data-dir]').length`) === 2);
  fs.writeFileSync(file('ask-bogus'), mkPage('light', [F.mk('ask', 'notes', { dir: '/x/ask', ask: { inbox: 'yes' } })], T3DATA())); await load('ask-bogus', 315, '?tab=projects');
  check('ask.inbox must be exactly true for the card', await ev(`document.querySelectorAll('.askcard').length`) === 0);

  // ---- Remote Control row (Setup)
  for (const theme of ['light', 'dark', 'hc']) {
    const T = `[${theme}] remote: `;
    for (const [rs, cliState] of [['on', 'skipped'], ['off', 'green'], ['unknown', 'skipped'], ['unknown', 'green'], [undefined, 'skipped']]) {
      fs.writeFileSync(file('rc-' + theme + rs + cliState), mkPage(theme, T3PROJ(), T3DATA({ remote: rs ? { state: rs } : undefined, setup: F3.SETUP({ 'remote-control': cliState }) })));
    }
    await load('rc-' + theme + 'onskipped', 315, '?tab=setup');
    const row = () => ev(`(() => { const r = document.querySelector('[data-row=remote-control]'); return { cls: r.className, state: r.dataset.state, mark: r.querySelector('.cmark').textContent + '/' + r.querySelector('.cmark').getAttribute('aria-label'), reason: (r.querySelector('.creason') || {}).textContent || '', note: (r.querySelector('.cnote') || {}).textContent || '', btns: [...r.querySelectorAll('.cacts .btn')].map(b => b.textContent).join('+'), tips: [...r.querySelectorAll('.cacts .btn')].map(b => b.title), arias: [...r.querySelectorAll('.cacts .btn')].map(b => b.getAttribute('aria-label')), head: document.querySelector('.shead b').textContent }; })()`);
    const NOTE = 'Lets you reach your own Claude Code sessions from your phone. Needs a claude.ai paid plan.';
    const on = await row();
    check(T + 'state on: green row, "On", the risk note, one button "Undo" (quiet) and no Turn on / Skip', on.cls.includes('ok') && on.mark === '✓/Ready' && on.reason === 'On' && on.note === NOTE && on.btns === 'Undo' && /shipm init --undo remote-control/.test(on.tips[0]) && on.arias[0] === 'Undo Remote Control', JSON.stringify(on));
    const mu = await post(`document.querySelector('[data-row=remote-control] [data-setup=undo]').click()`);
    check(T + 'Undo posts only {type:"setup", op:"undo", id:"remote-control"} (the page types nothing, never writes the settings file)', JSON.stringify(mu) === JSON.stringify([{ type: 'setup', op: 'undo', id: 'remote-control' }]), JSON.stringify(mu));
    await load('rc-' + theme + 'offgreen', 315, '?tab=setup'); const off = await row();
    check(T + 'state off wins over a green CLI row: grey "Skipped" look, "Off by default", the same risk note, button "Turn on" (types `shipm init --step remote-control`), no Undo', off.cls.includes('skip') && off.mark === '–/Skipped' && off.reason === 'Off by default' && off.note === NOTE && off.btns === 'Turn on' && /shipm init --step remote-control/.test(off.tips[0]), JSON.stringify(off));
    const mf = await post(`document.querySelector('[data-row=remote-control] [data-setup=fix]').click()`);
    check(T + 'Turn on posts {type:"setup", op:"fix", id:"remote-control"} only', JSON.stringify(mf) === JSON.stringify([{ type: 'setup', op: 'fix', id: 'remote-control' }]), JSON.stringify(mf));
    await load('rc-' + theme + 'unknownskipped', 315, '?tab=setup'); const un = await row();
    await load('rc-' + theme + 'unknowngreen', 315, '?tab=setup'); const ug = await row();
    await load('rc-' + theme + 'undefinedskipped', 315, '?tab=setup'); const ud = await row();
    check(T + 'state unknown or missing: the CLI row is shown unchanged (skipped = grey with its own text, green = Ready + Undo), the note is still there', un.cls.includes('skip') && /opt in with/.test(un.reason) && un.note === NOTE && un.btns === 'Turn on' && ug.cls.includes('ok') && ug.btns === 'Undo' && ud.cls.includes('skip') && ud.btns === 'Turn on', JSON.stringify([un, ug, ud]));
    await load('rc-' + theme + 'onskipped', 315, '?tab=setup');
    const hc = await ev(`document.querySelector('.shead b').textContent`);
    check(T + 'header counts remote on as ready: "Setup · 11 of M ready" (10 green in the fixture + Remote Control; M = the fixture rows without the optional Describe-your-work row)', hc === 'Setup · 11 of ' + (F3.ROWS().length - 1) + ' ready' && off.head === 'Setup · 10 of ' + (F3.ROWS().length - 1) + ' ready', JSON.stringify([hc, off.head]));
    check(T + 'Remote row: no horizontal scroll, targets >= 22 px, contrast >= 4.5:1 (note included)', await ev(noHScroll) && (await ev(TARGETS)).length === 0 && (await ev(TXT_IN('[data-row=remote-control] *'))).every(x => x.ratio >= 4.5), JSON.stringify([await ev(TARGETS), (await ev(TXT_IN('[data-row=remote-control] *'))).filter(x => x.ratio < 4.5)]));
    if (theme !== 'hc' && WRITE_SHOTS) {
      await load('rc-' + theme + 'onskipped', 315, '?tab=setup'); await sizeAll();
      const r = await ev(`(() => { const a = document.querySelector('[data-row=remote-control]').getBoundingClientRect(); return { x: a.left - 8, y: a.top - 8 + window.scrollY, w: a.width + 16, h: a.height + 16 }; })()`);
      const s = await cdp('Page.captureScreenshot', { format: 'png', clip: { x: r.x, y: r.y, width: r.w, height: r.h, scale: 2 } }), buf = Buffer.from(s.result.data, 'base64');
      fs.writeFileSync(path.join(SHOTS, `setup-remote-${theme}.png`), buf); manifest.push({ state: 'setup-remote', theme, file: `tests/fixtures/panel-v3/setup-remote-${theme}.png`, width: Math.round(r.w * 2), height: Math.round(r.h * 2), bytes: buf.length });
    }
  }
  // ---- token card: the long-chats row (only with ledger data, Claude only, never invented)
  {
    const led = (wk, fresh = true) => ({ fresh, source: 'ledger', today: { calls: 4, tokens: 120000, overCallsPct: 10, overTokensPct: 20 }, week: wk, byProject: {}, resets: null });
    const pg = l => mkPage('light', [F.mk('chat-app', 'software')], T3DATA({ ledger: l }));
    const withRow = pg(led({ calls: 50, tokens: 900000, overCallsPct: 22.5, overTokensPct: 38.4 })), tipOk = /title="[^"]*Claude only/.test(withRow);
    check('token card: "Long chats this week: 38% of tokens (goal under 45%)" with its tooltip when the ledger has the number', withRow.includes('Long chats this week: 38% of tokens (goal under 45%)') && tipOk);
    check('token card: no row when the ledger has no share, no week tokens, or is stale; a share of 0 shows as 0%', !pg(led({ calls: 5, tokens: 1000, overCallsPct: null, overTokensPct: null })).includes('Long chats this week') && !pg(led({ calls: 0, tokens: 0, overCallsPct: null, overTokensPct: 12 })).includes('Long chats this week') && !pg(led({ calls: 50, tokens: 900000, overTokensPct: 38 }, false)).includes('Long chats this week') && !pg(null).includes('Long chats this week') && pg(led({ calls: 5, tokens: 1000, overCallsPct: 0, overTokensPct: 0 })).includes('Long chats this week: 0% of tokens'));
    fs.writeFileSync(file('tok'), withRow); await load('tok', 315, '?tab=projects');
    check('token card: the row sits with the other token lines, readable, no overflow', await ev(`[...document.querySelectorAll('.mrow')].some(r => /Long chats this week/.test(r.textContent))`) && await ev(noHScroll) && (await ev(TXT_IN('.mrow *'))).every(x => x.ratio >= 4.5), JSON.stringify([await ev(noHScroll), await ev(TXT_IN('.mrow *'))]));
  }
  // hard-coded counts: the panel copy and code never name 17 or 18 rows
  { const srcs = ['panel.js', 'strings.js', 'extension.js', 'data.js', 'setup.js'].map(f => fs.readFileSync(path.join(ROOT, 'vscode-ext', 'shipmiracle-panel', f), 'utf8')).join('\n');
    check('no hard-coded Setup row count (17 / 18 rows) in the panel code or copy', !/\b1[78] rows\b|of 1[78] ready/.test(srcs)); }

  // manifest of the committed screenshots
  fs.mkdirSync(path.join(ROOT, 'docs', 'summary'), { recursive: true });
  if (WRITE_SHOTS) for (const x of manifest) { const b = fs.readFileSync(path.join(ROOT, x.file)); x.width = b.readUInt32BE(16); x.height = b.readUInt32BE(20); x.bytes = b.length; }      // the real size from the PNG header, not the clip rounding
  const total = manifest.reduce((a, x) => a + x.bytes, 0);
  if (WRITE_SHOTS) fs.writeFileSync(path.join(ROOT, 'docs', 'summary', 'panel-shots-manifest.json'), JSON.stringify({ v: 1, generated_by: 'tests/panel_v3_ui_test.js', width_px: 315, themes: ['light (Light+)', 'dark (Dark+)', 'hc (Default High Contrast, 4 states)'], total_bytes: total, shots: manifest.map(x => ({ ...x, caption: (x.theme === 'hc' ? 'High contrast. ' : '') + { idle: 'Idle: nothing running, last commit 2 h ago', building: 'Building with Sonnet: builder-frontend, 4th stage current', approval: 'Plan is ready: the primary button is "Review plan"', 'verify-fail': 'Test failed once: the 4th stage current again, verdict FAIL', hardstop: 'Autopilot hard stop: "Decide"', delivered: 'Delivered: all seven stages done, verdict PASS', 'charter-editor': 'Full autopilot charter editor in place: fields, always-excluded list, tick box, Start', reports: 'Reports tab: filters, grouped by project, FAIL and BLOCKED first, Arabic title right to left', setup: 'Setup tab: 19 rows from shipmiracle init --check, red / green / grey, Fix and Skip, required rows without Skip', health: 'Health tab: the new change-request and autopilot kinds with Fix, Open chat or Back to guided', 'ask-inbox': 'Ask inbox card: one-line box with counter, Ask types the command in the terminal, questions today, last answer with Open and Promote to idea', 'setup-remote': 'Setup: the Remote Control row when on (green, Undo, plain-text risk note)' }[x.state] })) }, null, 2) + '\n');
  const shotFiles = fs.existsSync(SHOTS) ? fs.readdirSync(SHOTS).filter(f => f.endsWith('.png')) : [], committed = shotFiles.reduce((a, f) => a + fs.statSync(path.join(SHOTS, f)).size, 0);
  const NEED = [...['idle', 'building', 'approval', 'verify-fail', 'hardstop', 'delivered', 'reports', 'setup', 'health', 'ask-inbox', 'setup-remote'].flatMap(n => ['light', 'dark'].map(t => `${n}-${t}`)), ...HC_KEEP.map(n => `${n}-hc`)].sort();
  const SHOTS_ABSENT = !WRITE_SHOTS && shotFiles.length === 0 && !fs.existsSync(path.join(ROOT, 'docs', 'summary', 'panel-shots-manifest.json'));
  const want = 18 + (WRITE_SHOTS ? 8 : 0);
  check('screenshots: ' + want + ' PNGs taken in this run' + (WRITE_SHOTS ? ' (6 core states + reports + setup + health + ask-inbox + setup-remote, light and dark, + high contrast for ' + HC_KEEP.join(', ') + ')' : ' (6 states + Reports, Setup, Health, light and dark; SHIPMIRACLE_SHOTS=1 also writes ask-inbox, setup-remote and the high-contrast four)'), manifest.length === want, String(manifest.length));
  if (SHOTS_ABSENT) console.log('SKIP committed screenshot set and manifest: the exported tree ships neither tests/fixtures/panel-v3 PNGs nor docs/summary (private records)');
  else check('committed screenshot set: exactly the ' + NEED.length + ' expected files (' + shotFiles.length + ' files, ' + committed + ' bytes), under 2 MB; a normal run leaves the repo untouched (SHIPMIRACLE_SHOTS=1 rewrites them)', JSON.stringify(shotFiles.map(f => f.replace(/\.png$/, '')).sort()) === JSON.stringify(NEED) && committed < 2 * 1024 * 1024, JSON.stringify(shotFiles.length) + ' ' + committed);
  if (!SHOTS_ABSENT) {                                                                                   // the committed manifest describes exactly the committed files
    const mf = path.join(ROOT, 'docs', 'summary', 'panel-shots-manifest.json'); let mj = null; try { mj = JSON.parse(fs.readFileSync(mf, 'utf8')); } catch (e) { /* reported */ }
    const png = f => { const b = fs.readFileSync(f); return { w: b.readUInt32BE(16), h: b.readUInt32BE(20), n: b.length, ok: b.slice(0, 8).toString('hex') === '89504e470d0a1a0a' }; };
    const rows = mj ? mj.shots.map(x => { const f = path.join(ROOT, x.file); const ex = fs.existsSync(f), g = ex ? png(f) : null; return { x, ok: ex && g.ok && g.n === x.bytes && g.w === x.width && g.h === x.height && typeof x.caption === 'string' && x.caption.length > 8 && !/^\/|Users/.test(x.file) }; }) : [];
    check('manifest: docs/summary/panel-shots-manifest.json is valid JSON (v 1), lists every committed PNG once with its real size, width and height, a caption, a relative path; total_bytes is the sum and under 2 MB',
      !!mj && mj.v === 1 && rows.length === NEED.length && rows.every(r => r.ok) && JSON.stringify(mj.shots.map(x => path.basename(x.file, '.png')).sort()) === JSON.stringify(NEED) && mj.total_bytes === mj.shots.reduce((a, x) => a + x.bytes, 0) && mj.total_bytes === committed && mj.total_bytes < 2 * 1024 * 1024 && !/Users|\/home\//.test(JSON.stringify(mj)), JSON.stringify(rows.filter(r => !r.ok).slice(0, 2)));
  }
  killChrome(); ws.close();
  console.log(fails ? `\nFAILED: ${fails}` : '\nALL PASS'); process.exit(fails ? 1 : 0);
})().catch(e => { console.error(e); killChrome(); process.exit(2); });
