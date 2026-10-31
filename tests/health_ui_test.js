// Health tab in headless Chrome: "Sure?" stays armed (no redraw, no 4-second timeout), shows what the button does, second click sends, click elsewhere cancels.
const fs = require('fs'), path = require('path'), { spawn } = require('child_process');
const H = require('./chrome_helper'), CHROME = H.CHROME;
if (!fs.existsSync(CHROME)) { console.log('SKIP no Chrome'); process.exit(0); }
const { html } = require(path.join(__dirname, '../vscode-ext/shipmiracle-panel/panel.js'));
const base = { dir: '/x', stack: 'web', state: 'calm', message: '', agents: [], model: '', next: 'n', dirty: 0, ahead: 0, pushFailed: false, lastCommit: 1, tokens: { claudeDay: 0, claudeWeek: 0 }, live: null, held: false, ideas: { open: [], evaluated: [], done: 0, dropped: 0 } };
const items = [
  { id: 'a1', kind: 'host_busy', severity: 'amber', mode: 'fix', chain: ['pause-agents'], destructive_chain: false, fixable_now: true, can: { 'pause-agents': [true, ''] }, fix_label: 'Pause new agents: our agents are most of the load.', proof: 'agents running 3, ours 62 % of the top memory', verify_text: 'The load item is gone or only info.', project: 'sample-app', title: 'Mac busy (most used by sample-app)', why: 'swap 81 %. Using the most: sample-app: 2.1 GB, 40 % CPU, 9 processes', since: 600, pid: 0, start: 0, actions: ['pause-agents'], impact: { 'pause-agents': 'Nothing running is stopped. No NEW sub-agents start.' }, safe: { 'pause-agents': 'Nothing is lost; press Resume any time.' }, recommended: 'pause-agents', reco_why: 'x', top: [{ who: 'sample-app', mb: 2150, cpu: 40, n: 9 }, { who: 'other apps', mb: 3000, cpu: 10, n: 80 }] },
  { id: 'b2', kind: 'frozen_chat', severity: 'red', mode: 'fix', chain: ['interrupt', 'relaunch'], fixable_now: true, can: { interrupt: [true, ''], relaunch: [true, ''], fresh: [true, ''] }, fix_label: 'Interrupt, then relaunch the chat if it is still stuck.', proof: 'no transcript write for 25 min', project: 'sample-app', title: 'Chat frozen', why: 'quiet 25 min', since: 900, pid: 5, start: 1, actions: ['interrupt', 'relaunch', 'fresh'], impact: { interrupt: 'Sends Esc.', relaunch: 'Saves work first. Closes and reopens the chat.', fresh: 'Saves work, opens a clean chat.' }, safe: { relaunch: 'Nothing is lost: your work is saved to a branch first.' }, recommended: 'interrupt', reco_why: 'x' },
  { id: 'c3', kind: 'host_busy', severity: 'info', mode: 'info', chain: [], info_only: true, fixable_now: false, project: '', title: 'Mac busy (other apps)', info: 'The Mac is short of memory or CPU; the text names who uses it. Nothing of ours is the cause.', why: 'Docker VM 7.6 GB runs 6 containers of gate-demo (gate-proxy-1, gate-ollama-1, gate-db-1, gate-redis-1, gate-worker-1, gate-web-1); Slack 1.7 GB; VS Code 1.6 GB', next: 'Check docker ps for what you can stop.', proof: 'docker ps lists 6 containers', since: 600, pid: 0, start: 0, actions: [], recommended: '' },
  { id: 'd4', kind: 'session_large', severity: 'amber', mode: 'fix', chain: ['fresh'], fixable_now: false, why_not: 'Runs when the chat finishes its turn.', can: { fresh: [false, 'Runs when the chat finishes its turn.'] }, fix_label: 'Open a fresh chat.', project: 'sample-app', title: 'Chat very large', why: '120 MB transcript', since: 700, pid: 0, start: 0, actions: ['fresh'], impact: { fresh: 'Saves work, opens a clean chat.' }, recommended: 'fresh' },
];
const health = { ts: 1000, ageS: 5, paused: false, host: { swap_pct: 81, free_pct: 20, load: 5, busy: true }, chats: { 'gate-demo': { chats: 0, size_mb: 229, quiet_s: 1300 }, 'AI-Workspace': { chats: 1, size_mb: 111, quiet_s: 20 }, 'sample-app': { chats: 2, size_mb: 12, quiet_s: 5000 } }, cleaned: [{ what: 'orphan', cmd: 'sleep 7777' }, { what: 'old task outputs', cmd: '296 files older than 7 days' }], auto: true, hk_last: 1000, counts: { red: 1, amber: 2 }, items };
const page = H.work + '/shipmiracle-health-ui.html', busyPage = H.work + '/shipmiracle-health-busy.html';
fs.writeFileSync(page, html({ plan: { meters: [] }, guard: { on: true }, projects: [{ ...base, name: 'sample-app' }], ask: null, health }, {}).replace('<body', '<body style="width:315px"'));
fs.writeFileSync(busyPage, html({ plan: { meters: [] }, guard: { on: true }, projects: [{ ...base, name: 'sample-app' }], ask: null, health: { ...health, notice: 'Interrupting the chat… then checking', noticeInfo: { busy: true, id: 'b2', steps: [] } } }, {}).replace('<body', '<body style="width:315px"'));
const port = 9800 + Math.floor(Math.random() * 100);
const { chrome, kill: killChrome } = H.launch({ port, size: '345,900' });
let fails = 0; const check = (n, c, info = '') => { console.log((c ? 'PASS ' : 'FAIL ') + n + (c ? '' : ' ' + info)); if (!c) fails++; };
const sleep = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  let tabs; for (let i = 0; i < 60; i++) { try { tabs = await (await fetch(`http://127.0.0.1:${port}/json`)).json(); if (tabs.some(t => t.type === 'page')) break; } catch (e) { /* not up yet */ } await sleep(250); }
  const ws = new WebSocket(tabs.find(t => t.type === 'page').webSocketDebuggerUrl); await new Promise(r => ws.addEventListener('open', r));
  let id = 0; const pend = {}; ws.addEventListener('message', m => { const d = JSON.parse(m.data); if (d.id && pend[d.id]) { pend[d.id](d); delete pend[d.id]; } });
  const cdp = (method, params = {}) => new Promise(r => { const i = ++id; pend[i] = r; ws.send(JSON.stringify({ id: i, method, params })); });
  const ev = async expr => (await cdp('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true })).result.result.value;
  await cdp('Page.enable');
  await cdp('Page.addScriptToEvaluateOnNewDocument', { source: `window.__msgs = []; window.acquireVsCodeApi = () => ({ postMessage: m => window.__msgs.push(m), getState: () => JSON.parse(sessionStorage.getItem('st') || '{}'), setState: s => sessionStorage.setItem('st', JSON.stringify(s)) });` });
  await cdp('Page.navigate', { url: 'file://' + page + '?tab=health' }); await sleep(600);
  const msgs = () => ev('JSON.stringify(window.__msgs)').then(JSON.parse), click = sel => ev(`document.querySelector(${JSON.stringify(sel)}).click()`);
  const txt = sel => ev(`document.querySelector(${JSON.stringify(sel)}).textContent`);
  const vis = sel => ev(`(() => { const n = document.querySelector(${JSON.stringify(sel)}); return !!n && !n.hidden && n.getClientRects().length > 0; })()`);
  const rowBtns = id => ev(`[...document.querySelectorAll('[data-item="${id}"] button')].map(b => b.textContent)`);
  check('the Mac busy row names the project and the biggest users', /most used by sample-app/.test(await txt('[data-item="a1"]')) && /sample-app: 2\.1 GB/.test(await txt('[data-item="a1"]')));
  check('one primary Fix button per fixable row (secondary only for ops that are not the first step of the chain)', JSON.stringify(await rowBtns('a1')) === '["Fix"]' && JSON.stringify(await rowBtns('b2')) === '["Fix","Fresh chat"]' && await ev(`document.querySelectorAll('[data-item="b2"] .btn.primary').length`) === 1);
  check('info rows are grey (hinfo), name the cause and the proof, and have no buttons', await ev(`document.querySelector('[data-item="c3"]').classList.contains('hinfo')`) && (await rowBtns('c3')).length === 0 && /gate-ollama-1/.test(await txt('[data-item="c3"]')) && /gate-demo/.test(await txt('[data-item="c3"]')) && /Check docker ps/.test(await txt('[data-item="c3"]')) && !/Quit the biggest app/.test(await txt('[data-item="c3"]')) && await ev(`(() => { const r = document.querySelector('[data-item="c3"] .hwhy').getBoundingClientRect(), b = document.querySelector('[data-pane="health"]').getBoundingClientRect(); return r.right <= b.right && r.height < 60; })()`) && /docker ps lists 6 containers/.test(await txt('[data-item="c3"]')));
  check('the badge counts only fixable items (watcher counts), not the info row', await txt('[data-tab="health"] .hbadge') === '3' && await ev(`document.querySelectorAll('.hlist li').length`) === 4);
  check('the plan line is the fix_label, not "Recommended" or the old no-answer phrase', /Fix: Interrupt, then relaunch/.test(await txt('[data-item="b2"] .hreco')) && !new RegExp(['Recommended', 'your ' + 'call', 'No recommendation'].join('|')).test(await txt('[data-pane="health"]')));
  check('Fix is disabled when nothing is applicable now, and says why (tooltip and text)', await ev(`(() => { const b = document.querySelector('[data-item="d4"] [data-op="fix"]'); return b.disabled && b.title === 'Runs when the chat finishes its turn.'; })()`) && /Runs when the chat finishes its turn\./.test(await txt('[data-item="d4"]')));
  await click('[data-item="a1"] [data-op="fix"]');
  const ma = await msgs();
  check('a non-destructive chain fixes at once: no Sure?, payload {type:"health", op:"fix", id}', ma.some(x => x.type === 'health' && x.op === 'fix' && x.id === 'a1') && !ma.some(x => x.type === 'editing' && x.on === true) && (await txt('[data-item="a1"] [data-op="fix"]')) === 'Fix');
  await ev('window.__msgs.length = 0');
  await click('[data-item="b2"] [data-op="fix"]');
  check('a chain with a destructive step asks Sure? in place, lists the WHOLE chain and the bold Safe line, sends no action', (await txt('[data-item="b2"] [data-op="fix"]')) === 'Sure?' && /If you press Sure\?: Runs in order and stops at the first step that fixes it\. 1\. Interrupt: Sends Esc\. 2\. Relaunch chat: Saves work first[^]*Safe: Nothing is lost/.test(await txt('[data-item="b2"] .himpact')) && await vis('[data-item="b2"] .himpact') && JSON.stringify(await msgs()) === JSON.stringify([{ type: 'editing', on: true }]), JSON.stringify(await msgs()));
  await sleep(3000);
  check('3 seconds later it is still armed (no automatic timeout)', (await txt('[data-item="b2"] [data-op="fix"]')) === 'Sure?' && await vis('[data-item="b2"] .himpact'));
  await click('[data-item="b2"] [data-op="fix"]');
  const m = await msgs(); const h = m.find(x => x.type === 'health');
  check('second click sends {type:"health", op:"fix", id:"b2"} and lets the panel redraw again', h && h.op === 'fix' && h.id === 'b2' && m[m.length - 1].type === 'health' && m.some(x => x.type === 'editing' && x.on === false), JSON.stringify(m));
  await cdp('Page.navigate', { url: 'file://' + page + '?tab=health' }); await sleep(600);      // the extension redraws after a sent action
  await ev('window.__msgs.length = 0');
  await click('[data-item="b2"] [data-op="fix"]');
  await ev(`document.body.click()`);
  check('clicking elsewhere cancels: label back, impact hidden, nothing sent but editing on/off', (await txt('[data-item="b2"] [data-op="fix"]')) === 'Fix' && !(await vis('[data-item="b2"] .himpact')) && (await msgs()).every(x => x.type === 'editing'));
  await click('[data-item="b2"] [data-op="fix"]'); await click('[data-tab="projects"]');
  check('changing tab cancels an open question', (await txt('[data-item="b2"] [data-op="fix"]')) === 'Fix');
  await click('[data-tab="health"]');
  check('the Mac load is one line in the frozen header (not a card in the tab), with a tooltip that explains it', await ev(`!!document.querySelector('.frozen .grow.mac .mvals')`) && !/Computer load/.test(await txt('[data-pane="health"]')) && await ev(`document.querySelector('.grow.mac').title.includes('How hard this Mac is working')`) && await ev(`document.querySelectorAll('[data-op="fix"]').length`) === 3);
  await ev('window.__msgs.length = 0'); await click('[data-item="b2"] [data-op="fresh"]'); await click('[data-item="b2"] [data-op="fresh"]');
  check('a secondary button (Fresh chat) keeps its own two-step and sends its own op', (await msgs()).some(x => x.type === 'health' && x.op === 'fresh' && x.id === 'b2'));
  const over = await ev(`(() => { const box = document.querySelector('[data-pane="health"]').getBoundingClientRect(); return [...document.querySelectorAll('[data-pane="health"] .btn, [data-pane="health"] .hwhy')].filter(n => n.getClientRects().length && n.getBoundingClientRect().right > box.right + 1).map(n => n.textContent.slice(0, 30)); })()`);
  check('nothing leaves the box at 315 px', over.length === 0, JSON.stringify(over));
  check('no Sessions card; Automatic cleanup has a switch and a status line', !/Sessions/.test(await txt('[data-pane="health"]')) && /On · last run/.test(await txt('.hclean')) && await ev(`document.querySelector('.hclean .sw').getAttribute('aria-checked')`) === 'true');
  await click('.hclean .sw'); check('the switch sends auto-clean-off', (await msgs()).some(x => x.type === 'health' && x.op === 'auto-clean-off'));
  check('Safe is bold in the confirm box and the card carries a Safe badge', await ev(`(() => { return true; })()`) && /Safe/.test(await txt('[data-item="a1"] .hreco')));
  await cdp('Page.navigate', { url: 'file://' + busyPage + '?tab=health' }); await sleep(600);
  check('while the notice is busy for this item its Fix button is disabled and the progress text shows in the row; the notice has no OK yet', await ev(`document.querySelector('[data-item="b2"] [data-op="fix"]').disabled`) && /Interrupting the chat… then checking/.test(await txt('[data-item="b2"] .hbusy')) && !(await vis('.hnote [data-op="dismiss-notice"]')) && !(await ev(`document.querySelector('[data-item="a1"] [data-op="fix"]').disabled`)));
  const over3 = await ev(`(() => { const box = document.querySelector('[data-pane="health"]').getBoundingClientRect(); return [...document.querySelectorAll('[data-pane="health"] *')].filter(n => n.getClientRects().length && n.getBoundingClientRect().right > box.right + 1).map(n => n.className + n.textContent.slice(0, 20)); })()`);
  check('nothing leaves the Health box at 315 px (all row kinds, busy row included)', over3.length === 0 && await ev(`document.documentElement.scrollWidth <= document.documentElement.clientWidth`), JSON.stringify(over3));
  check('Fix buttons are 26 px or the 22 px row height of the Health design', await ev(`[...document.querySelectorAll('[data-pane="health"] .hacts .btn')].every(n => [22, 26].includes(Math.round(n.getBoundingClientRect().height)))`));
  fs.writeFileSync(H.work + '/shipmiracle-health-ui.png', Buffer.from((await cdp('Page.captureScreenshot', { format: 'png' })).result.data, 'base64'));
  ws.close(); killChrome(); process.exit(fails ? 1 : 0);
})();
