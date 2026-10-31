// Button and chip alignment, measured in real headless Chrome at a normal and a narrow sidebar width, in both tabs.
// Rules: every .btn is 26 px, every chip 22 px; groups of buttons are equal-width columns on one row; the same column positions in every idea; nothing leaves its box.
const fs = require('fs'), path = require('path'), { spawn } = require('child_process');
const H = require('./chrome_helper'), CHROME = H.CHROME;
if (!fs.existsSync(CHROME)) { console.log('SKIP no Chrome'); process.exit(0); }
const { html } = require(path.join(__dirname, '../vscode-ext/shipmiracle-panel/panel.js'));
const base = { dir: '/x', stack: 'web', state: 'calm', message: '', agents: [], model: '', next: 'Fix the login screen', dirty: 2, ahead: 1, pushFailed: false, lastCommit: 1, tokens: { claudeDay: 12000, claudeWeek: 1 }, live: null, held: false, active: false, chatOpen: false, ideas: { open: [], evaluated: [], done: 0, dropped: 0 } };
const I = (id, text, tags = [], verdict = '') => ({ id, text, date: '2026-10-19', tags, verdict });
const ps = [
  { ...base, name: 'AI-Workspace', stack: 'workspace', active: true, chatOpen: true, ci: { conclusion: 'failure', status: 'completed', url: 'https://github.com/a/b', title: 't' }, ideas: { open: [I('F1', 'Export the yearly report as PDF', ['#export', '#report']), I('F2', 'Short')], evaluated: [I('F3', 'Dark mode', [], 'BUILD LATER · score 2.4'), I('F4', 'Weekly digest', [], 'MOVE to ideas · fits notes'), I('F5', 'Family sync across devices', [], 'SPLIT OUT · new project'), I('F6', 'Quick win', [], 'BUILD NOW · score 3.1')], done: 1, dropped: 0 } },
  { ...base, name: 'gate', state: 'working', chatOpen: true, chatStale: true, agents: [{ type: 'backend-engineer', model: 'sonnet', mins: 12, quiet: 20, stalled: false }, { type: 'frontend-engineer', model: 'sonnet', mins: 12, quiet: 900, stalled: true }], live: { model: 'Sonnet 5.5', phase: 'implementing', modelAge: 5, idle: 5 } },
  { ...base, name: 'home-lab', stack: 'home', state: 'needs-input', message: 'Approve?', live: { model: 'Opus 5.5', phase: 'waiting', modelAge: 5, idle: 5 }, ci: { conclusion: '', status: 'in_progress', url: 'https://github.com/a/b', title: '' } },
  { ...base, name: 'ideas', stack: 'notes', special: 'ideas' },
];
const mk = w => html({ plan: { meters: [] }, guard: { on: true, running: true, hold: true }, projects: ps, ask: { projects: [{ name: 'sample-app', count: 2 }], expires: 9e9 } }, {}).replace('<body', '<body style="width:' + w + 'px"');
const port = 9800 + Math.floor(Math.random() * 150);
const { chrome, kill: killChrome } = H.launch({ port, size: '400,1400' });
let fails = 0; const check = (n, c, info = '') => { console.log((c ? 'PASS ' : 'FAIL ') + n + (c ? '' : ' ' + info)); if (!c) fails++; };
const sleep = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  let tabs; for (let i = 0; i < 60; i++) { try { tabs = await (await fetch(`http://127.0.0.1:${port}/json`)).json(); if (tabs.some(t => t.type === 'page')) break; } catch (e) { /* wait */ } await sleep(250); }
  const ws = new WebSocket(tabs.find(t => t.type === 'page').webSocketDebuggerUrl); await new Promise(r => ws.addEventListener('open', r));
  let id = 0; const pend = {}; ws.addEventListener('message', m => { const d = JSON.parse(m.data); if (d.id && pend[d.id]) { pend[d.id](d); delete pend[d.id]; } });
  const cdp = (method, params = {}) => new Promise(r => { const i = ++id; pend[i] = r; ws.send(JSON.stringify({ id: i, method, params })); });
  const ev = async e => { const r = await cdp('Runtime.evaluate', { expression: e, returnByValue: true }); if (r.result.exceptionDetails) throw new Error(JSON.stringify(r.result.exceptionDetails)); return r.result.result.value; };
  await cdp('Page.enable');
  await cdp('Page.addScriptToEvaluateOnNewDocument', { source: `window.acquireVsCodeApi = () => ({ postMessage() {}, getState: () => null, setState() {} });` });
  for (const w of [315, 255]) {
    fs.writeFileSync(H.work + '/shipmiracle-align.html', mk(w));
    const load = async q => { await cdp('Page.navigate', { url: 'file://' + H.work + '/shipmiracle-align.html' + q }); await sleep(400); };
    const R = `(sel, root) => [...(root || document).querySelectorAll(sel)].filter(n => n.getClientRects().length).map(n => { const r = n.getBoundingClientRect(); return { l: Math.round(r.left), r: Math.round(r.right), t: Math.round(r.top), h: Math.round(r.height), w: Math.round(r.width), txt: n.textContent.trim().slice(0, 14) }; })`;
    const m = async (sel, root) => ev(`(${R})(${JSON.stringify(sel)}, ${root ? `document.querySelector(${JSON.stringify(root)})` : 'null'})`);
    const same = (a, k, tol = 1) => a.length > 0 && a.every(x => Math.abs(x[k] - a[0][k]) <= tol);
    await load('?tab=projects');
    let b = await m('.btn'); check(`[${w}] Projects tab: every button is 26 px high (28 px in the card button grid)`, b.length >= 4 && b.every(x => x.h === 26 || x.h === 28), JSON.stringify(b.filter(x => x.h !== 26 && x.h !== 28)));
    const rl = await ev(`(() => { const n = document.querySelector('.chip[data-relaunch]'); const s = getComputedStyle(n); return { border: s.borderTopWidth, h: Math.round(n.getBoundingClientRect().height), cursor: s.cursor, txt: n.textContent }; })()`);
    check(`[${w}] the relaunch chip is a plain flat chip: no border, 22 px high, pointer cursor`, rl.border === '0px' && rl.h === 22 && rl.cursor === 'pointer', JSON.stringify(rl));
    let c = await m('.chip'); check(`[${w}] Projects tab: every chip is 22 px high`, c.length >= 4 && c.every(x => x.h === 22), JSON.stringify(c.filter(x => x.h !== 22)));
    let t = await m('.ptools .btn'); check(`[${w}] the New project and Check & update buttons are equal halves on one row`, t.length === 2 && same(t, 'w') && same(t, 't'), JSON.stringify(t));
    let br = await m('.bgrid .btn'); check(`[${w}] the banner buttons are equal halves on one row`, br.length === 2 && same(br, 'w') && same(br, 't'), JSON.stringify(br));
    let ans = await m('.card.st-warn .btn.primary'), mo = await m('.card.st-warn .btn.more'); check(`[${w}] the primary button (Decide) takes slot 1 of the grid: half of the width left of the 28 px ⋯ button, 8 px gaps (slot 2 stays empty when Ask aside is hidden)`, ans.length === 1 && mo.length === 1 && mo[0].w === 28 && Math.abs(ans[0].w - (mo[0].l - 16 - ans[0].l) / 2) <= 2, JSON.stringify([ans, mo]));
    const clipP = await ev(`[...document.querySelectorAll('.btn, .chip, .tab')].filter(n => n.getClientRects().length && n.scrollWidth > n.clientWidth + 1 && !(getComputedStyle(n).textOverflow === 'ellipsis' && n.title)).map(n => n.textContent.trim().slice(0, 30))`);
    check(`[${w}] Projects tab: no button, chip or tab clips its text`, clipP.length === 0, JSON.stringify(clipP));
    let ov = await ev(`[...document.querySelectorAll('.btn, .chip, select')].filter(n => n.getClientRects().length && n.getBoundingClientRect().right > document.documentElement.clientWidth - 4).map(n => n.textContent.slice(0, 15))`);
    check(`[${w}] Projects tab: nothing runs past the right edge`, ov.length === 0 && await ev('document.documentElement.scrollWidth <= document.documentElement.clientWidth'), JSON.stringify(ov));
    await load('?tab=ideas&proj=AI-Workspace');
    b = await m('.ilist:not([hidden]) .btn'); check(`[${w}] Ideas tab: every button is 26 px high`, b.length >= 20 && b.every(x => x.h === 26), JSON.stringify(b.filter(x => x.h !== 26)));
    const rows = await ev(`[...document.querySelectorAll('.ilist:not([hidden]) .iacts')].map(a => [...a.querySelectorAll('.btn:not(.primary)')].map(n => { const r = n.getBoundingClientRect(); return { l: Math.round(r.left), t: Math.round(r.top), w: Math.round(r.width) }; }))`);
    check(`[${w}] each idea has Move…, Copy…, Drop as three equal columns on one row`, rows.length === 6 && rows.every(r => r.length === 3 && same(r, 't') && same(r, 'w')), JSON.stringify(rows));
    check(`[${w}] the three columns sit at the same x in every idea`, rows.every(r => r.every((x, i) => x.l === rows[0][i].l && x.w === rows[0][i].w)), JSON.stringify(rows.map(r => r.map(x => x.l))));
    const prim = await ev(`[...document.querySelectorAll('.ilist:not([hidden]) .iacts .btn.primary')].map(n => { const r = n.getBoundingClientRect(), p = n.parentElement.getBoundingClientRect(); return Math.round(r.width) - Math.round(p.width); })`);
    check(`[${w}] a primary action (Worth it?, Plan this, …) spans the full row`, prim.length === 5 && prim.every(d => Math.abs(d) <= 1), JSON.stringify(prim));
    await ev(`document.querySelector('.ilist:not([hidden]) [data-toggle="addbox"]').click(); document.querySelector('.ilist:not([hidden]) [data-pick="move"]').click()`);
    const fr = await m('.frow .btn'); check(`[${w}] the add form: Add and Cancel are equal halves on one row, the long action spans the full width below`, fr.length === 3 && Math.abs(fr[0].w - fr[1].w) <= 1 && fr[0].t === fr[1].t && fr[2].t > fr[0].t && fr[2].w >= fr[0].w + fr[1].w, JSON.stringify(fr));
    const pr = await m('.pickrow .btn'); check(`[${w}] the Move dropdown's two buttons are equal halves on one row`, pr.length === 2 && same(pr, 'w') && same(pr, 't'), JSON.stringify(pr));
    const clipped = await ev(`[...document.querySelectorAll('.btn, .chip, .tab, .pchip')].filter(n => n.getClientRects().length && n.scrollWidth > n.clientWidth + 1 && !(getComputedStyle(n).textOverflow === 'ellipsis' && n.title)).map(n => n.textContent.trim().slice(0, 30) + ' (' + n.scrollWidth + '>' + n.clientWidth + ')')`);
    check(`[${w}] no button, chip or tab clips its text without an ellipsis and a tooltip (open add form and Move dropdown included)`, clipped.length === 0, JSON.stringify(clipped));
    ov = await ev(`(() => { const box = document.querySelector('.ilist:not([hidden])').getBoundingClientRect(); return [...document.querySelectorAll('.ilist:not([hidden]) .btn, .ilist:not([hidden]) select, .ilist:not([hidden]) textarea, [data-psel]')].filter(n => n.getClientRects().length && n.getBoundingClientRect().right > box.right + 1).map(n => n.tagName + ':' + n.textContent.slice(0, 12)); })()`);
    check(`[${w}] Ideas tab: nothing leaves its box`, ov.length === 0, JSON.stringify(ov));
    if (w === 255) { const s = await cdp('Page.captureScreenshot', { format: 'png' }); fs.writeFileSync(H.work + '/shipmiracle-align.png', Buffer.from(s.result.data, 'base64')); }
  }
  console.log(fails ? '\nFAILED: ' + fails : '\nALL PASS'); ws.close(); killChrome(); process.exit(fails ? 1 : 0);
})().catch(e => { console.error('test crashed:', e.message); killChrome(); process.exit(2); });
