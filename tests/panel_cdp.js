// Shared driver for the panel v3 browser tests (golden, a11y, performance, safety): the theme table, the page builder, a CDP session over tests/chrome_helper.js
// (the only way Chrome is started), the in-page contrast helpers and the common layout probes. Not a test.
require('./shipmiracle_isolation');
const fs = require('fs'), os = require('os'), path = require('path');
const H = require('./chrome_helper');
const { html } = require(path.join(__dirname, '../vscode-ext/shipmiracle-panel/panel.js'));

// The variables the panel reads, as the shipped default themes set them (Default Dark+, Default Light+, Default High Contrast). The table is the test's own source of truth;
// tests/panel_v3_a11y_test.js cross-checks it against the theme JSON of an installed VS Code and reports every difference.
const THEMES = {
  dark: { '--vscode-foreground': '#cccccc', '--vscode-descriptionForeground': '#ccccccb3', '--vscode-panel-border': '#80808059', '--vscode-editorWidget-background': '#252526', '--vscode-editorWarning-foreground': '#cca700', '--vscode-textLink-foreground': '#3794ff', '--vscode-testing-iconPassed': '#73c991', '--vscode-errorForeground': '#f48771', '--vscode-sideBar-background': '#252526', '--vscode-button-foreground': '#ffffff', '--vscode-input-background': '#3c3c3c', 'color-scheme': 'dark' },
  light: { '--vscode-foreground': '#616161', '--vscode-descriptionForeground': '#717171', '--vscode-panel-border': '#80808059', '--vscode-editorWidget-background': '#f3f3f3', '--vscode-editorWarning-foreground': '#bf8803', '--vscode-textLink-foreground': '#006ab1', '--vscode-testing-iconPassed': '#73c991', '--vscode-errorForeground': '#a1260d', '--vscode-sideBar-background': '#f3f3f3', '--vscode-button-foreground': '#ffffff', '--vscode-input-background': '#ffffff', 'color-scheme': 'light' },
  hc: { '--vscode-foreground': '#ffffff', '--vscode-descriptionForeground': '#ffffffb3', '--vscode-panel-border': '#6fc3df', '--vscode-editorWidget-background': '#0c141f', '--vscode-editorWarning-foreground': '#ffcc00', '--vscode-textLink-foreground': '#21a6a2', '--vscode-testing-iconPassed': '#73c991', '--vscode-errorForeground': '#f48771', '--vscode-sideBar-background': '#000000', '--vscode-contrastBorder': '#6fc3df', '--vscode-button-foreground': '#ffffff', '--vscode-input-background': '#000000', 'color-scheme': 'dark' }
};
const bodyClass = theme => theme === 'light' || theme === 'hcl' ? 'vscode-light' + (theme === 'hcl' ? ' vscode-high-contrast vscode-high-contrast-light' : '') : theme === 'hc' ? 'vscode-dark vscode-high-contrast' : 'vscode-dark';
// The panel page for a theme (the theme variables are injected the way VS Code injects them into a webview).
function page(theme, data, vars = THEMES[theme], opts = {}) {
  const v = vars || THEMES[theme];
  return html({ plan: { meters: [] }, guard: { on: true }, projects: [], ask: null, levelSwitch: { ok: true, why: '' }, ...data }, opts)
    .replace('</head>', `<style>:root{${Object.entries(v).map(([k, x]) => k + ':' + x).join(';')}}html,body{background:${v['--vscode-sideBar-background']}}</style></head>`)
    .replace('<body ', `<body class="${bodyClass(theme)}" `);
}
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
})();`;
// every visible text element of the open pane and the tab bar: its contrast against the composited background (ratio < 4.5 is a failure; disabled text is exempt)
const TEXT_IN = sel => `(() => { const { ratio, bgOf, colorOn } = window.__c, out = [];
  document.querySelectorAll(${JSON.stringify(sel)}).forEach(n => {
    if (!n.getClientRects().length || n.closest('svg') || n.closest('[hidden]')) return;
    const own = [...n.childNodes].some(c => c.nodeType === 3 && c.textContent.trim()); if (!own) return;
    if (n.disabled || n.closest(':disabled') || n.classList.contains('seg')) return;
    const bg = bgOf(n), fg = colorOn(getComputedStyle(n).color, bg), r = ratio(fg, bg);
    out.push({ txt: n.textContent.trim().slice(0, 30), cls: n.className.toString().slice(0, 24), ratio: +r.toFixed(2) });
  }); return out; })()`;
const TARGETS = `[...document.querySelectorAll('.tabs button, #scroll button, #scroll select')].filter(n => n.getClientRects().length && !n.closest('[hidden]')).map(n => { const r = n.getBoundingClientRect(); return { t: (n.textContent.trim() || n.getAttribute('aria-label') || n.className).slice(0, 24), w: Math.round(r.width), h: Math.round(r.height) }; }).filter(x => x.w < 22 || x.h < 22)`;
const NO_HSCROLL = `(() => { const d = document.documentElement, sc = document.getElementById('scroll'); return d.scrollWidth <= d.clientWidth && sc.scrollWidth <= sc.clientWidth; })()`;

// A browser session. -> { cdp, ev, load, key, shot, sleep, close, file(name, html) }
async function session({ size = '345,900', port } = {}) {
  const work = fs.mkdtempSync(path.join(os.tmpdir(), 'shipmiracle-panel-cdp-'));
  const p = port || 9500 + Math.floor(Math.random() * 300);
  const { kill } = H.launch({ port: p, size });
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  let tabs; for (let i = 0; i < 60; i++) { try { tabs = await (await fetch(`http://127.0.0.1:${p}/json`)).json(); if (tabs.some(t => t.type === 'page')) break; } catch (e) { /* not up yet */ } await sleep(250); }
  const ws = new WebSocket(tabs.find(t => t.type === 'page').webSocketDebuggerUrl); await new Promise(r => ws.addEventListener('open', r));
  let id = 0; const pend = {}; const events = [];
  ws.addEventListener('message', m => { const d = JSON.parse(m.data); if (d.id && pend[d.id]) { pend[d.id](d); delete pend[d.id]; } else if (d.method) events.push(d); });
  const cdp = (method, params = {}) => new Promise(r => { const i = ++id; pend[i] = r; ws.send(JSON.stringify({ id: i, method, params })); });
  const ev = async expr => { const r = await cdp('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true }); if (r.result.exceptionDetails) throw new Error(JSON.stringify(r.result.exceptionDetails.exception || r.result.exceptionDetails)); return r.result.result.value; };
  await cdp('Page.enable'); await cdp('Runtime.enable'); await cdp('Emulation.setFocusEmulationEnabled', { enabled: true });
  await cdp('Page.addScriptToEvaluateOnNewDocument', { source: `window.__msgs = []; window.acquireVsCodeApi = () => ({ postMessage: m => window.__msgs.push(m), getState: () => JSON.parse(sessionStorage.getItem('st') || 'null'), setState: s => sessionStorage.setItem('st', JSON.stringify(s)) });` });
  const file = (name, text) => { const f = path.join(work, name + '.html'); fs.writeFileSync(f, text); return f; };
  const load = async (f, w = 315, q = '?tab=projects', h = 7000) => { await cdp('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: 1, mobile: false }); await cdp('Page.navigate', { url: 'file://' + f + q }); await sleep(450); await ev(`sessionStorage.clear()`); await ev(LIB); };
  const key = async (k, code, vk, text) => { await cdp('Input.dispatchKeyEvent', { type: text ? 'keyDown' : 'rawKeyDown', key: k, code, windowsVirtualKeyCode: vk, ...(text ? { text } : {}) }); await cdp('Input.dispatchKeyEvent', { type: 'keyUp', key: k, code, windowsVirtualKeyCode: vk }); };
  const shot = async (clip, scale = 1.5) => Buffer.from((await cdp('Page.captureScreenshot', { format: 'png', clip: { ...clip, scale } })).result.data, 'base64');
  return { cdp, ev, load, key, shot, sleep, file, events, work, close() { try { ws.close(); } catch (e) { /* closed */ } kill(); try { fs.rmSync(work, { recursive: true, force: true }); } catch (e) { /* ok */ } } };
}
// the counter every test uses
function checker() { const c = { fails: 0, n: 0, check(name, ok, info = '') { c.n++; console.log((ok ? 'PASS ' : 'FAIL ') + name + (ok ? '' : ' ' + info)); if (!ok) c.fails++; } }; return c; }

module.exports = { H, THEMES, page, LIB, TEXT_IN, TARGETS, NO_HSCROLL, session, checker, bodyClass };
