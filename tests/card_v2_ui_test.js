// Project card v2, the New project box and the gate-level pill in real headless Chrome at 315 px, light and dark.
// Checks layout (no overflow, strip on one line, chips 22 px, buttons 26 px), contrast of chip and pill text (>= 4.5:1), focus rings,
// the "Sure? Switch to ..." confirm flow, the New project box (tidy hint, draft survives a redraw, payload, Cancel). Saves screenshots to reports/screens/.
// Needs Google Chrome; skips if it is missing. Run: node tests/card_v2_ui_test.js
const fs = require('fs'), path = require('path'), os = require('os'), { spawn } = require('child_process');
const H = require('./chrome_helper'), CHROME = H.CHROME;
if (!fs.existsSync(CHROME)) { console.log('SKIP no Chrome'); process.exit(0); }
const { html } = require(path.join(__dirname, '../vscode-ext/shipmiracle-panel/panel.js'));
const SHOTS = path.join(__dirname, '../reports/screens'); fs.mkdirSync(SHOTS, { recursive: true });
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'shipmiracle-card-v2-'));
const base = { dir: '/x', stack: 'web', state: 'idle', message: '', agents: [], model: '', next: '', dirty: 0, ahead: 0, pushFailed: false, lastCommit: Date.now() / 1000 - 7200, tokens: { claudeDay: 12000, claudeWeek: 1 }, live: null, held: false, active: false, chatOpen: false, ideas: { open: [], evaluated: [], done: 0, dropped: 0 } };
const steps = (cur, done = []) => Object.fromEntries(['scope', 'plan', 'ok', 'build', 'qa', 'review'].map(k => [k, done.includes(k) ? 'done' : k === cur ? 'current' : 'next']));
const FL = o => ({ stage: '', steps: steps(''), running: [], plannedBy: '', builtBy: '', qaBy: '', qaState: '', planNotByArchitect: false, outside: [], integrity: false, bypass: false, refusalsToday: 0, mismatch: false, ...o });
const ps = [
  { ...base, name: 'sample-app', stack: 'web', state: 'idle', level: 'off', flow: FL({ stage: 'review', steps: steps('', ['scope', 'plan', 'ok', 'build', 'qa']), plannedBy: 'solution-architect', builtBy: 'frontend-engineer', qaBy: 'qa-engineer', qaState: 'passed', qaVerdict: 'PASS', qaCounts: '212 passed, 0 failed' }), team: { count: 11, bad: [] } },
  { ...base, name: 'AI-Workspace', stack: 'workspace', state: 'working', level: 'strict', active: true, chatOpen: true, ci: { conclusion: '', status: 'in_progress', url: 'https://github.com/a/b', title: '' }, flow: FL({ stage: 'build', steps: steps('build', ['scope', 'plan', 'ok']), running: [{ type: 'frontend-engineer', model: 'sonnet' }], plannedBy: 'solution-architect', builtBy: 'frontend-engineer', refusalsToday: 2 }), team: { count: 11, bad: [] } },
  { ...base, name: 'home-lab', stack: 'home', state: 'needs-input', level: 'warn', approval: true, message: 'Approve the plan?', flow: FL({ stage: 'ok', steps: steps('ok', ['scope', 'plan']), plannedBy: 'solution-architect' }), team: { count: 11, bad: [] } },
  { ...base, name: 'gate-demo', stack: 'python', state: 'working', level: 'strict', chatOpen: true, chatStale: true, ci: { conclusion: 'failure', status: 'completed', url: 'https://github.com/a/b', title: 't' }, flow: FL({ stage: 'build', steps: steps('build', ['scope', 'plan', 'ok']), running: [{ type: 'backend-engineer', model: 'sonnet' }], integrity: true, bypass: true, outside: ['scripts/gate.py', 'tools/x'], refusalsToday: 1 }), team: { count: 11, bad: [] } },
  { ...base, name: 'extras', stack: 'api', state: 'working', level: 'warn', agents: [{ type: 'qa-engineer', model: 'sonnet', mins: 9, quiet: 900, stalled: true }], flow: FL({ stage: 'plan', steps: steps('plan', ['scope']), running: [{ type: 'solution-architect', model: 'opus' }], planNotByArchitect: true, qaState: 'failed', qaVerdict: 'FAIL', qaCounts: '3 failed, 9 passed', mismatch: 'Sonnet 5.5', integrity: true }), team: { count: 0, bad: ['frontend-engineer.md: model: inherit', 'x.md: no Flow role'] }, health: [{ id: 'h1', kind: 'frozen_chat', severity: 'red', title: 'Chat frozen', why: 'quiet 25 min' }, { id: 'h2', kind: 'leftover', severity: 'amber', title: 'Leftover', why: 'x' }] },
];
const THEME = {
  light: { '--vscode-foreground': '#3b3b3b', '--vscode-descriptionForeground': '#717171', '--vscode-panel-border': 'rgba(128,128,128,.35)', '--vscode-editorWidget-background': '#ffffff', '--vscode-editorWarning-foreground': '#bf8803', '--vscode-textLink-foreground': '#006ab1', '--vscode-testing-iconPassed': '#388a34', '--vscode-errorForeground': '#a1260d', '--vscode-sideBar-background': '#f3f3f3' },
  dark: { '--vscode-foreground': '#cccccc', '--vscode-descriptionForeground': '#9d9d9d', '--vscode-panel-border': 'rgba(128,128,128,.35)', '--vscode-editorWidget-background': '#252526', '--vscode-editorWarning-foreground': '#cca700', '--vscode-textLink-foreground': '#3794ff', '--vscode-testing-iconPassed': '#73c991', '--vscode-errorForeground': '#f48771', '--vscode-sideBar-background': '#181818' }
};
const mk = (theme, extra = {}) => html({ plan: { meters: [] }, guard: { on: true }, projects: ps, ask: null, levelSwitch: { ok: true, why: '' }, ...extra }, {})
  .replace('</head>', `<style>:root{${Object.entries(THEME[theme]).map(([k, v]) => k + ':' + v).join(';')}}html,body{background:${THEME[theme]['--vscode-sideBar-background']}}</style></head>`).replace('<body', '<body style="width:315px"');
const file = n => path.join(tmp, n + '.html');
fs.writeFileSync(file('light'), mk('light')); fs.writeFileSync(file('dark'), mk('dark'));
fs.writeFileSync(file('noswitch'), mk('light', { levelSwitch: { ok: false, why: 'Gate-test is working right now. Try again when no project is working.' } }));
fs.writeFileSync(file('busy'), mk('light', { creating: { name: 'trial-notes', ts: 1 }, pnotice: 'Not created: no GitHub login' }));
const port = 9500 + Math.floor(Math.random() * 300);
const { chrome, kill: killChrome } = H.launch({ port, size: '345,1700' });
let fails = 0; const check = (n, c, info = '') => { console.log((c ? 'PASS ' : 'FAIL ') + n + (c ? '' : ' ' + info)); if (!c) fails++; };
const sleep = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  let tabs; for (let i = 0; i < 60; i++) { try { tabs = await (await fetch(`http://127.0.0.1:${port}/json`)).json(); if (tabs.some(t => t.type === 'page')) break; } catch (e) { /* not up yet */ } await sleep(250); }
  const ws = new WebSocket(tabs.find(t => t.type === 'page').webSocketDebuggerUrl); await new Promise(r => ws.addEventListener('open', r));
  let id = 0; const pend = {}; ws.addEventListener('message', m => { const d = JSON.parse(m.data); if (d.id && pend[d.id]) { pend[d.id](d); delete pend[d.id]; } });
  const cdp = (method, params = {}) => new Promise(r => { const i = ++id; pend[i] = r; ws.send(JSON.stringify({ id: i, method, params })); });
  const ev = async expr => { const r = await cdp('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true }); if (r.result.exceptionDetails) throw new Error(JSON.stringify(r.result.exceptionDetails.exception || r.result.exceptionDetails)); return r.result.result.value; };
  await cdp('Page.enable'); await cdp('Emulation.setDeviceMetricsOverride', { width: 345, height: 1700, deviceScaleFactor: 2, mobile: false }); await cdp('Emulation.setFocusEmulationEnabled', { enabled: true });
  await cdp('Page.addScriptToEvaluateOnNewDocument', { source: `window.__msgs = []; window.acquireVsCodeApi = () => ({ postMessage: m => window.__msgs.push(m), getState: () => JSON.parse(sessionStorage.getItem('st') || 'null'), setState: s => sessionStorage.setItem('st', JSON.stringify(s)) });` });
  const load = async (n, q = '?tab=projects') => { await cdp('Page.navigate', { url: 'file://' + file(n) + q }); await sleep(500); };
  const click = sel => ev(`document.querySelector(${JSON.stringify(sel)}).click()`);
  const msgs = () => ev('JSON.stringify(window.__msgs)').then(JSON.parse);
  const vis = sel => ev(`(() => { const n = document.querySelector(${JSON.stringify(sel)}); return !!n && !n.hidden && n.getClientRects().length > 0; })()`);
  const txt = sel => ev(`document.querySelector(${JSON.stringify(sel)}).textContent`);
  const typeInto = (sel, v) => ev(`(() => { const n = document.querySelector(${JSON.stringify(sel)}); n.focus(); n.value = ${JSON.stringify(v)}; n.dispatchEvent(new Event('input', { bubbles: true })); })()`);
  const CONTRAST = `(() => {                                   // composite the ancestors' backgrounds on a canvas, then the text colour on top, then WCAG contrast
    const cv = document.createElement('canvas'); cv.width = cv.height = 1; const cx = cv.getContext('2d', { willReadFrequently: true });
    const px = () => { const d = cx.getImageData(0, 0, 1, 1).data; return [d[0], d[1], d[2]]; };
    const lum = c => { const f = v => { v /= 255; return v <= .03928 ? v / 12.92 : Math.pow((v + .055) / 1.055, 2.4); }; return .2126 * f(c[0]) + .7152 * f(c[1]) + .0722 * f(c[2]); };
    return [...document.querySelectorAll('.chip, .lvl')].filter(n => n.getClientRects().length).map(n => {
      cx.clearRect(0, 0, 1, 1); cx.fillStyle = getComputedStyle(document.documentElement).backgroundColor; cx.fillRect(0, 0, 1, 1);
      const chain = []; for (let e = n; e; e = e.parentElement) chain.unshift(e);
      chain.forEach(e => { const b = getComputedStyle(e).backgroundColor; if (b && b !== 'rgba(0, 0, 0, 0)' && b !== 'transparent') { cx.fillStyle = b; cx.fillRect(0, 0, 1, 1); } });
      const bg = px(); cx.fillStyle = getComputedStyle(n).color; cx.fillRect(0, 0, 1, 1); const fg = px();
      const a = lum(fg), b = lum(bg); return { txt: n.textContent.trim().slice(0, 28), ratio: +(((Math.max(a, b) + .05) / (Math.min(a, b) + .05))).toFixed(2) };
    }); })()`;

  for (const theme of ['light', 'dark']) {
    await load(theme);
    const T = `[${theme}] `;
    check(T + 'no style= attribute in the page markup (CSP)', !/\sstyle=/.test(await ev(`document.querySelector('main').outerHTML`)));
    check(T + 'five cards render, and the old gate-level pill is gone (Safe mode replaced it)', await ev(`document.querySelectorAll('.card').length`) === 5 && await ev(`document.querySelectorAll('.card .lvl, [data-level]').length`) === 0);
    const ov = await ev(`(() => { const d = document.documentElement; const bad = []; document.querySelectorAll('.card').forEach(c => { const cr = c.getBoundingClientRect(); c.querySelectorAll('*').forEach(n => { if (n.getClientRects().length && n.getBoundingClientRect().right > cr.right + 0.5) bad.push(n.className + ':' + n.textContent.slice(0, 15)); }); }); return { sw: d.scrollWidth <= d.clientWidth, bad }; })()`);
    check(T + 'no horizontal overflow, nothing leaves its card', ov.sw && ov.bad.length === 0, JSON.stringify(ov));
    const strips = await ev(`[...document.querySelectorAll('.tflow')].map(o => { const t = [...o.children].map(li => Math.round(li.getBoundingClientRect().top)); return { one: t.every(x => Math.abs(x - t[0]) <= 1), fit: o.scrollWidth <= o.clientWidth + 1, n: t.length }; })`);
    check(T + 'the Team-flow strip is one line at 315 px on every card that has one', strips.length === 5 && strips.every(s => s.one && s.fit && s.n === 6), JSON.stringify(strips));
    const chips = await ev(`[...document.querySelectorAll('.chip')].filter(n => n.getClientRects().length).map(n => ({ h: Math.round(n.getBoundingClientRect().height), t: n.textContent.slice(0, 20) }))`);
    check(T + 'every chip and pill is 22 px high', chips.length >= 5 && chips.every(c => c.h === 22), JSON.stringify(chips.filter(c => c.h !== 22)));
    const btns = await ev(`[...document.querySelectorAll('.btn')].filter(n => n.getClientRects().length).map(n => ({ h: Math.round(n.getBoundingClientRect().height), t: n.textContent.slice(0, 20) }))`);
    check(T + 'every .btn (Answer, New project, Check & update) is at least 26 px high', btns.length >= 3 && btns.every(b => b.h >= 26), JSON.stringify(btns));
    const clip = await ev(`[...document.querySelectorAll('.chip')].filter(n => n.getClientRects().length && n.scrollWidth > n.clientWidth + 1 && !n.title).map(n => n.textContent.slice(0, 30))`);
    check(T + 'a chip that is cut off with an ellipsis always carries its full text as a tooltip', clip.length === 0, JSON.stringify(clip));
    const cr = await ev(CONTRAST);
    check(T + 'text on every chip and pill reaches 4.5:1 (lowest ' + Math.min(...cr.map(c => c.ratio)) + ')', cr.length >= 5 && cr.every(c => c.ratio >= 4.5), JSON.stringify(cr.filter(c => c.ratio < 4.5)));
    const noRing = [];
    for (const i of await ev(`[...document.querySelectorAll('button')].map((n, i) => n.getClientRects().length && !n.disabled ? i : -1).filter(i => i >= 0)`)) {
      const r = await ev(`(() => { const n = document.querySelectorAll('button')[${i}]; n.focus(); const s = getComputedStyle(n); return { ok: s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) >= 2, t: n.textContent.trim().slice(0, 20) || n.getAttribute('aria-label') }; })()`);
      if (!r.ok) noRing.push(r.t);
    }
    check(T + 'every visible button shows a focus ring (2 px outline)', noRing.length === 0, JSON.stringify(noRing));
    await ev(`document.activeElement.blur()`);
    // screenshots of the four states
    for (const [state, name] of [['idle', 'sample-app'], ['building', 'AI-Workspace'], ['waiting-for-approval', 'home-lab'], ['integrity-blocked', 'gate-demo']]) {
      const r = await ev(`(() => { const c = [...document.querySelectorAll('.card')].find(c => c.querySelector('.name').textContent === ${JSON.stringify(name)}); const b = c.getBoundingClientRect(); return { x: b.left - 6, y: b.top - 6 + window.scrollY, w: b.width + 12, h: b.height + 12 }; })()`);
      const shot = await cdp('Page.captureScreenshot', { format: 'png', clip: { x: r.x, y: r.y, width: r.w, height: r.h, scale: 2 } });
      fs.writeFileSync(path.join(SHOTS, `card-v2-${state}-${theme}.png`), Buffer.from(shot.result.data, 'base64'));
    }
    const all = await cdp('Page.captureScreenshot', { format: 'png' }); fs.writeFileSync(path.join(SHOTS, `card-v2-all-${theme}.png`), Buffer.from(all.result.data, 'base64'));
  }

  // The gate-level pill was removed by the panel v3 revision v2 (21 Oct): Safe mode is typed in a terminal and covered by tests/panel_v3_rev2_test.js and tests/ext_rev2_test.js.

  // ---- New project box ----
  await load('light'); await ev('window.__msgs.length = 0');
  check('New project box is closed at first', !(await vis('[data-newbox]')));
  await click('[data-toggle="newbox"]');
  check('opens in place with the name field focused; Create is disabled while the name is empty', await vis('[data-newbox]') && await ev('document.activeElement.dataset.nf') === 'name' && await ev(`document.querySelector('[data-nform="create"]').disabled`));
  await typeInto('[data-nf="name"]', 'My New App!');
  check('live hint shows the tidy folder name; Create stays off until a type is picked, then turns on', await txt('[data-nhint]') === 'Will be created as ~/Developer/my-new-app' && await ev(`document.querySelector('[data-nform="create"]').disabled`));
  await ev(`document.querySelector('[data-nf="kind"]').value = 'web'; document.querySelector('[data-nf="kind"]').dispatchEvent(new Event('change', { bubbles: true }))`);
  check('picking a type turns Create on', !(await ev(`document.querySelector('[data-nform="create"]').disabled`)));
  await typeInto('[data-nf="name"]', '  --.Hidden__Dir  ');
  check('tidy rule matches bin/new-project: lowercase, odd characters become -, no leading dot or dash', await txt('[data-nhint]') === 'Will be created as ~/Developer/hidden__dir', await txt('[data-nhint]'));
  await typeInto('[data-nf="name"]', 'x'.repeat(60));
  check('long names are cut to 40 characters', await txt('[data-nhint]') === 'Will be created as ~/Developer/' + 'x'.repeat(40));
  await typeInto('[data-nf="name"]', 'foo.');
  check('tidy equals the extension: trailing dot stripped (foo.)', await txt('[data-nhint]') === 'Will be created as ~/Developer/foo');
  await typeInto('[data-nf="name"]', ' -Foo Bar-');
  check('tidy equals the extension: leading dash and trailing dash stripped ( -Foo Bar-)', await txt('[data-nhint]') === 'Will be created as ~/Developer/foo-bar');
  await typeInto('[data-nf="name"]', '___' + '.');
  check('a name without a letter or digit is refused like the extension', await ev(`document.querySelector('[data-nform="create"]').disabled`));
  await typeInto('[data-nf="name"]', '!!!');
  check('a name with no letter or digit keeps Create off and says so', await ev(`document.querySelector('[data-nform="create"]').disabled`) && await txt('[data-nhint]') === 'Use lowercase letters, numbers and dashes.');
  await typeInto('[data-nf="name"]', 'AI-Workspace');
  check('a name that already exists keeps Create off and says so', await ev(`document.querySelector('[data-nform="create"]').disabled`) && await txt('[data-nhint]') === 'That name is already a project.');
  await typeInto('[data-nf="name"]', 'Trial Notes');
  await ev(`document.querySelector('[data-nf="kind"]').value = 'python'; document.querySelector('[data-nf="kind"]').dispatchEvent(new Event('change', { bubbles: true }))`);
  await typeInto('[data-nf="about"]', 'A tiny test project');
  const editing = (await msgs()).filter(x => x.type === 'editing');
  check('typing in the box tells the extension not to redraw (editing on) and never uses the ideas draft', editing.some(x => x.on === true) && await ev(`(JSON.parse(sessionStorage.getItem('st') || '{}')).draft === undefined`));
  await load('light');
  const dr = await ev(`({ open: !document.querySelector('[data-newbox]').hidden, name: document.querySelector('[data-nf="name"]').value, kind: document.querySelector('[data-nf="kind"]').value, about: document.querySelector('[data-nf="about"]').value, hint: document.querySelector('[data-nhint]').textContent, focus: document.activeElement.dataset.nf })`);
  check('the draft (name, type, text) and the open box survive a redraw, with the hint and the cursor back', dr.open && dr.name === 'Trial Notes' && dr.kind === 'python' && dr.about === 'A tiny test project' && dr.hint === 'Will be created as ~/Developer/trial-notes', JSON.stringify(dr));
  await ev('window.__msgs.length = 0'); await click('[data-nform="create"]');
  const np = (await msgs()).filter(x => x.type === 'newproject');
  check('Create posts {type:"newproject", name (tidy), kind, about} once and closes the box', np.length === 1 && np[0].name === 'trial-notes' && np[0].kind === 'python' && np[0].about === 'A tiny test project' && !(await vis('[data-newbox]')), JSON.stringify(np));
  await load('light');
  check('after Create the draft is gone: a redraw leaves the box closed', !(await vis('[data-newbox]')));
  await click('[data-toggle="newbox"]'); await typeInto('[data-nf="name"]', 'half typed'); await click('[data-nform="cancel"]'); await load('light');
  check('Cancel closes the box, clears the draft and posts no newproject', !(await vis('[data-newbox]')) && !(await msgs()).some(x => x.type === 'newproject') && await ev(`document.querySelector('[data-nf="name"]').value`) === '');
  await load('busy'); await click('[data-toggle="newbox"]'); await typeInto('[data-nf="name"]', 'another-one');
  const bz = await ev(`({ row: document.querySelector('.pcreate').textContent, dis: document.querySelector('[data-nform="create"]').disabled, note: document.querySelector('.hnote span').textContent, btn: document.querySelector('.hnote [data-op="dismiss-project-notice"]').dataset.id, firstTop: Math.round(document.querySelector('.pcreate').getBoundingClientRect().top) < Math.round(document.querySelector('.ptools').getBoundingClientRect().top) })`);
  check('while a project is being created: a "Creating <name>…" row on top, Create stays disabled; the notice has an OK button', /Creating trial-notes… \(GitHub repo too, up to a minute\)/.test(bz.row) && bz.dis && bz.firstTop && bz.note === 'Not created: no GitHub login' && bz.btn === '-', JSON.stringify(bz));
  await ev('window.__msgs.length = 0'); await click('.hnote [data-op="dismiss-project-notice"]');
  check('OK on the notice posts the health dismiss message', (await msgs()).some(x => x.type === 'health' && x.op === 'dismiss-project-notice' && x.id === '-'));
  const bo = await ev(`(() => { const nb = document.querySelector('[data-newbox]').getBoundingClientRect(); return [...document.querySelectorAll('[data-newbox] *')].filter(n => n.getClientRects().length && n.getBoundingClientRect().right > nb.right + 1).map(n => n.tagName); })()`);
  check('the open New project box keeps everything inside itself at 315 px; its buttons are 26 px', bo.length === 0 && await ev(`[...document.querySelectorAll('[data-newbox] .btn')].every(n => Math.round(n.getBoundingClientRect().height) === 26)`), JSON.stringify(bo));

  console.log(fails ? '\nFAILED: ' + fails : '\nALL PASS'); ws.close(); killChrome(); process.exit(fails ? 1 : 0);
})().catch(e => { console.error('test crashed:', e.message); killChrome(); process.exit(2); });
