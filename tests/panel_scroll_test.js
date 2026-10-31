// The token card and the tabs stay on screen while everything under them scrolls, in a short sidebar (real headless Chrome; skips without Chrome).
const fs = require('fs'), path = require('path'), { spawn } = require('child_process');
const H = require('./chrome_helper'), CHROME = H.CHROME;
if (!fs.existsSync(CHROME)) { console.log('SKIP no Chrome'); process.exit(0); }
const { html } = require(path.join(__dirname, '../vscode-ext/shipmiracle-panel/panel.js'));
const base = { dir: '/x', stack: 'web', state: 'calm', message: '', agents: [], model: '', next: 'Fix the login screen', dirty: 2, ahead: 1, pushFailed: false, lastCommit: 1, tokens: { claudeDay: 12000, claudeWeek: 1 }, live: null, held: false, active: false, chatOpen: false, ideas: { open: [], evaluated: [], done: 0, dropped: 0 } };
const I = (id, text) => ({ id, text, date: '2026-10-19', tags: [], verdict: '' });
const ps = Array.from({ length: 9 }, (_, i) => ({ ...base, name: 'project-' + (i + 1), active: i === 0, ideas: i === 0 ? { open: Array.from({ length: 9 }, (_, k) => I('F' + (k + 1), 'Idea number ' + (k + 1))), evaluated: [], done: 0, dropped: 0 } : base.ideas }));
fs.writeFileSync(H.work + '/shipmiracle-scroll.html', html({ plan: { meters: [{ id: 'five', label: '5-hour', pct: 18, lvl: 0 }] }, guard: { on: true, running: true }, projects: ps, ask: { projects: [{ name: 'project-1', count: 9 }], expires: 9e9 } }, {}));
const port = 9950 + Math.floor(Math.random() * 40);
const { chrome, kill: killChrome } = H.launch({ port });
let fails = 0; const check = (n, c, info = '') => { console.log((c ? 'PASS ' : 'FAIL ') + n + (c ? '' : ' ' + info)); if (!c) fails++; };
const sleep = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  let tabs; for (let i = 0; i < 60; i++) { try { tabs = await (await fetch(`http://127.0.0.1:${port}/json`)).json(); if (tabs.some(t => t.type === 'page')) break; } catch (e) { /* wait */ } await sleep(250); }
  const ws = new WebSocket(tabs.find(t => t.type === 'page').webSocketDebuggerUrl); await new Promise(r => ws.addEventListener('open', r));
  let id = 0; const pend = {}; ws.addEventListener('message', m => { const d = JSON.parse(m.data); if (d.id && pend[d.id]) { pend[d.id](d); delete pend[d.id]; } });
  const cdp = (method, params = {}) => new Promise(r => { const i = ++id; pend[i] = r; ws.send(JSON.stringify({ id: i, method, params })); });
  const ev = async e => { const r = await cdp('Runtime.evaluate', { expression: e, returnByValue: true }); if (r.result.exceptionDetails) throw new Error(JSON.stringify(r.result.exceptionDetails)); return r.result.result.value; };
  await cdp('Page.enable'); await cdp('Emulation.setDeviceMetricsOverride', { width: 330, height: 520, deviceScaleFactor: 1, mobile: false });
  await cdp('Page.addScriptToEvaluateOnNewDocument', { source: `window.acquireVsCodeApi = () => ({ postMessage() {}, getState: () => JSON.parse(sessionStorage.getItem('st') || 'null'), setState: s => sessionStorage.setItem('st', JSON.stringify(s)) });` });
  const load = async q => { await cdp('Page.navigate', { url: 'file://' + H.work + '/shipmiracle-scroll.html' + q }); await sleep(500); };
  const top = sel => ev(`Math.round(document.querySelector(${JSON.stringify(sel)}).getBoundingClientRect().top)`);
  for (const [name, q, firstSel] of [['Projects tab', '?tab=projects', '.card'], ['Ideas tab', '?tab=ideas&proj=project-1', '.ilist:not([hidden]) .idea']]) {
    await load(q); await ev('sessionStorage.clear()'); await load(q);
    const m = await ev(`({ sh: document.getElementById('scroll').scrollHeight, ch: document.getElementById('scroll').clientHeight, page: document.documentElement.scrollHeight, vh: innerHeight })`);
    check(`${name}: the content is taller than the space under the header, so it scrolls`, m.sh > m.ch + 50, JSON.stringify(m));
    check(`${name}: the page itself does not scroll (only the area under the header)`, m.page <= m.vh + 1, JSON.stringify(m));
    const t0 = { plan: await top('.plan'), tabs: await top('.tabs'), first: await top(firstSel) };
    await ev(`document.getElementById('scroll').scrollTop = 400`); await sleep(150);
    const t1 = { plan: await top('.plan'), tabs: await top('.tabs'), first: await top(firstSel) };
    check(`${name}: the token card and the tabs did not move while scrolling`, t1.plan === t0.plan && t1.tabs === t0.tabs, JSON.stringify([t0, t1]));
    check(`${name}: the list under them did move`, t1.first < t0.first - 100, JSON.stringify([t0, t1]));
    const geo = await ev(`(() => { const p = document.querySelector('.plan').getBoundingClientRect(), t = document.querySelector('.tabs').getBoundingClientRect(); return { planBottom: Math.round(p.bottom), tabsTop: Math.round(t.top), planW: Math.round(p.width), tabsW: Math.round(t.width), vw: innerWidth }; })()`);
    check(`${name}: the token card sits above the tabs, both full width (not side by side)`, geo.tabsTop >= geo.planBottom && geo.planW > geo.vw - 40 && geo.tabsW > geo.vw - 40, JSON.stringify(geo));
    check(`${name}: the token card and the tabs are fully on screen`, t1.plan >= 0 && t1.tabs > t1.plan && t1.tabs + 30 < 520, JSON.stringify(t1));
    await sleep(250); await load(q);
    const back = await ev(`document.getElementById('scroll').scrollTop`);
    check(`${name}: after the panel redraws, the scroll position comes back`, Math.abs(back - 400) <= 3, 'scrollTop=' + back);
  }
  await load('?tab=projects'); await ev(`document.getElementById('scroll').scrollTop = 300`); await sleep(250);
  await ev(`document.querySelector('[data-tab="ideas"]').click()`); await sleep(100);
  check('switching tab starts at the top', await ev(`document.getElementById('scroll').scrollTop`) === 0);
  const sh = await cdp('Page.captureScreenshot', { format: 'png' }); fs.writeFileSync(H.work + '/shipmiracle-scroll.png', Buffer.from(sh.result.data, 'base64'));
  console.log(fails ? '\nFAILED: ' + fails : '\nALL PASS'); ws.close(); killChrome(); process.exit(fails ? 1 : 0);
})().catch(e => { console.error('test crashed:', e.message); killChrome(); process.exit(2); });
