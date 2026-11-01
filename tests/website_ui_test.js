// Public website in real headless Chrome: the page is LIGHT by default even when the system prefers dark, the toggle switches to dark and back,
// a saved choice wins on reload, and the Projects tab leaves no tall empty gap at 375 px. The site is served from website/ by a throw-away
// static server on 127.0.0.1 (random port, closed at the end). Needs Google Chrome; skips if it is missing. Run: node tests/website_ui_test.js
const fs = require('fs'), path = require('path'), http = require('http');
const H = require('./chrome_helper');
if (!H.available()) { console.log('SKIP no Chrome'); process.exit(0); }
const SITE = path.join(__dirname, '..', 'website');
const MIME = { '.html': 'text/html', '.css': 'text/css', '.js': 'text/javascript', '.svg': 'image/svg+xml', '.png': 'image/png', '.woff2': 'font/woff2', '.ico': 'image/x-icon' };
const server = http.createServer((q, r) => {
  let u = decodeURIComponent(q.url.split('?')[0]); if (u === '/') u = '/index.html';
  const f = path.join(SITE, path.normalize(u));
  if (!f.startsWith(SITE + path.sep) || !fs.existsSync(f) || fs.statSync(f).isDirectory()) { r.writeHead(404); r.end('not found'); return; }
  r.writeHead(200, { 'content-type': MIME[path.extname(f)] || 'application/octet-stream' }); r.end(fs.readFileSync(f));
});
const sleep = ms => new Promise(r => setTimeout(r, ms));
let fails = 0; const check = (n, c, info = '') => { console.log((c ? 'PASS ' : 'FAIL ') + n + (c ? '' : ' ' + info)); if (!c) fails++; };
const LIGHT = 'rgb(244, 239, 230)', DARK = 'rgb(23, 25, 28)';
let killChrome = () => {};
const done = code => { try { killChrome(); } catch (e) { /* already gone */ } server.close(); process.exit(code); };
server.listen(0, '127.0.0.1', async () => {
  try {
    const base = 'http://127.0.0.1:' + server.address().port;
    const L = H.launch({ size: '1280,900' }); killChrome = L.kill; const port = L.port;
    let tabs; for (let i = 0; i < 60; i++) { try { tabs = await (await fetch(`http://127.0.0.1:${port}/json`)).json(); if (tabs.some(t => t.type === 'page')) break; } catch (e) { /* not up yet */ } await sleep(250); }
    const ws = new WebSocket(tabs.find(t => t.type === 'page').webSocketDebuggerUrl); await new Promise(r => ws.addEventListener('open', r));
    let id = 0; const pend = {}; ws.addEventListener('message', m => { const d = JSON.parse(m.data); if (d.id && pend[d.id]) { pend[d.id](d); delete pend[d.id]; } });
    const cdp = (method, params = {}) => new Promise(r => { const i = ++id; pend[i] = r; ws.send(JSON.stringify({ id: i, method, params })); });
    const ev = async expr => { const r = await cdp('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true }); if (r.result.exceptionDetails) throw new Error(JSON.stringify(r.result.exceptionDetails)); return r.result.result.value; };
    const bg = () => ev('getComputedStyle(document.body).backgroundColor');
    const load = async (w = 1280) => {
      await cdp('Emulation.setDeviceMetricsOverride', { width: w, height: 900, deviceScaleFactor: 1, mobile: false });
      await cdp('Page.navigate', { url: base + '/' }); await sleep(900);
    };
    await cdp('Page.enable');
    // the system says dark: the site must still be light
    await cdp('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-color-scheme', value: 'dark' }, { name: 'prefers-reduced-motion', value: 'reduce' }] });
    await ev('localStorage.clear()').catch(() => {});
    await load();
    await ev('localStorage.clear()'); await load();
    check('system dark + nothing saved: the body background is the LIGHT value', await bg() === LIGHT, await bg());
    check('system dark + nothing saved: no data-theme, light colour-scheme, light theme-color', await ev(`(() => !document.documentElement.hasAttribute('data-theme') && document.querySelector('meta[name="color-scheme"]').content === 'light' && document.querySelector('meta[name="theme-color"]').content === '#F4EFE6')()`));
    check('the toggle offers dark and shows the sun', await ev(`document.querySelector('.theme').getAttribute('aria-label')`) === 'Switch to dark theme' && await ev(`getComputedStyle(document.querySelector('.t-sun')).display`) === 'block' && await ev(`getComputedStyle(document.querySelector('.t-moon')).display`) === 'none');
    check('the toggle is at least 44 x 44 px', await ev(`(() => { const r = document.querySelector('.theme').getBoundingClientRect(); return r.width >= 44 && r.height >= 44; })()`));
    await ev(`document.querySelector('.theme').click()`); await sleep(200);
    check('after the toggle: the body background is the DARK value', await bg() === DARK, await bg());
    check('after the toggle: data-theme dark, dark colour-scheme and theme-color, the label offers light, the moon shows', await ev(`(() => document.documentElement.getAttribute('data-theme') === 'dark' && document.querySelector('meta[name="color-scheme"]').content === 'dark' && document.querySelector('meta[name="theme-color"]').content === '#17191C' && document.querySelector('.theme').getAttribute('aria-label') === 'Switch to light theme' && getComputedStyle(document.querySelector('.t-moon')).display === 'block')()`));
    await load();
    check('a saved dark choice wins on reload (still dark)', await bg() === DARK, await bg());
    await ev(`document.querySelector('.theme').click()`); await sleep(200);
    check('toggling back gives light again', await bg() === LIGHT, await bg());
    await cdp('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-color-scheme', value: 'light' }, { name: 'prefers-reduced-motion', value: 'reduce' }] });
    await ev('localStorage.clear()'); await load();
    check('system light + nothing saved: light', await bg() === LIGHT, await bg());
    // the hero headline and the tab panel gap at 375 px
    check('the h1 says "All your AI projects, organized."', await ev(`document.querySelector('h1').textContent.trim()`) === 'All your AI projects, organized.');
    await load(375);
    const gap = await ev(`(() => { const box = document.querySelector('.tab-panels').getBoundingClientRect(), on = document.querySelector('.tp.on').getBoundingClientRect(); return { box: Math.round(box.height), on: Math.round(on.height) }; })()`);
    check('at 375 px the Projects panel keeps no empty band under it (container height equals the active panel)', Math.abs(gap.box - gap.on) <= 1, JSON.stringify(gap));
    check('at 375 px nothing scrolls sideways', await ev('document.documentElement.scrollWidth <= document.documentElement.clientWidth'));
    await ev(`document.querySelector('#t-reports').click()`); await sleep(700);
    const g2 = await ev(`(() => { const box = document.querySelector('.tab-panels').getBoundingClientRect(), on = document.querySelector('.tp.on').getBoundingClientRect(); return { box: Math.round(box.height), on: Math.round(on.height), vis: document.querySelector('#p-reports').getBoundingClientRect().height > 0 }; })()`);
    check('switching to Reports shows it and the container follows it', g2.vis && Math.abs(g2.box - g2.on) <= 1, JSON.stringify(g2));
    ws.close(); console.log(fails ? '\nFAILED: ' + fails : '\nALL PASS'); done(fails ? 1 : 0);
  } catch (e) { console.error('test crashed:', e.message); done(2); }
});
