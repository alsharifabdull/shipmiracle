// The Ideas tab in a real browser engine (headless Chrome driven over the DevTools protocol): dropdown, in-tab add form, draft survives a redraw,
// inline Move/Copy dropdown, in-place Drop confirm, no overflow with a long project name. Needs Google Chrome; skips if it is missing.
const fs = require('fs'), path = require('path'), { spawn } = require('child_process');
const H = require('./chrome_helper'), CHROME = H.CHROME;
if (!fs.existsSync(CHROME)) { console.log('SKIP no Chrome'); process.exit(0); }
const { html } = require(path.join(__dirname, '../vscode-ext/shipmiracle-panel/panel.js'));
const base = { dir: '/x', stack: 'web', state: 'calm', message: '', agents: [], model: '', next: 'n', dirty: 0, ahead: 0, pushFailed: false, lastCommit: 1, tokens: { claudeDay: 0, claudeWeek: 0 }, live: null, held: false };
const I = (id, text, tags = [], verdict = '') => ({ id, text, date: '2026-10-19', tags, verdict });
const LONG = 'home-lab-With-A-Very-Long-Name-2026';
const ps = [
  { ...base, name: 'sample-app', active: true, ideas: { open: [I('F1', 'Export the yearly report as PDF', ['#export']), I('F2', 'Second idea')], evaluated: [], done: 0, dropped: 0 } },
  { ...base, name: LONG, ideas: { open: [I('F1', 'Long-named project idea')], evaluated: [], done: 0, dropped: 0 } },
  { ...base, name: 'gate', held: true, ideas: { open: [], evaluated: [], done: 0, dropped: 0 } },
  { ...base, name: 'ideas', special: 'ideas', ideas: { open: [], evaluated: [], done: 0, dropped: 0 } },
];
const page = H.work + '/shipmiracle-ui-test.html';
fs.writeFileSync(page, html({ plan: { meters: [] }, guard: { on: true }, projects: ps, ask: null }, {}).replace('<body', '<body style="width:315px"'));
const port = 9400 + Math.floor(Math.random() * 400);
const { chrome, kill: killChrome } = H.launch({ port, size: '345,900' });
let fails = 0; const check = (n, c, info = '') => { console.log((c ? 'PASS ' : 'FAIL ') + n + (c ? '' : ' ' + info)); if (!c) fails++; };
const sleep = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  let tabs; for (let i = 0; i < 60; i++) { try { tabs = await (await fetch(`http://127.0.0.1:${port}/json`)).json(); if (tabs.some(t => t.type === 'page')) break; } catch (e) { /* not up yet */ } await sleep(250); }
  const ws = new WebSocket(tabs.find(t => t.type === 'page').webSocketDebuggerUrl); await new Promise(r => ws.addEventListener('open', r));
  let id = 0; const pend = {}; ws.addEventListener('message', m => { const d = JSON.parse(m.data); if (d.id && pend[d.id]) { pend[d.id](d); delete pend[d.id]; } });
  const cdp = (method, params = {}) => new Promise(r => { const i = ++id; pend[i] = r; ws.send(JSON.stringify({ id: i, method, params })); });
  const ev = async expr => { const r = await cdp('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true }); if (r.result.exceptionDetails) throw new Error(JSON.stringify(r.result.exceptionDetails.exception || r.result.exceptionDetails)); return r.result.result.value; };
  await cdp('Page.enable');
  await cdp('Page.addScriptToEvaluateOnNewDocument', { source: `window.__msgs = []; window.acquireVsCodeApi = () => ({ postMessage: m => window.__msgs.push(m), getState: () => JSON.parse(sessionStorage.getItem('st') || 'null'), setState: s => sessionStorage.setItem('st', JSON.stringify(s)) });` });
  const load = async q => { await cdp('Page.navigate', { url: 'file://' + page + q }); await sleep(500); };
  const click = sel => ev(`document.querySelector(${JSON.stringify(sel)}).click()`);
  const msgs = () => ev('JSON.stringify(window.__msgs)').then(JSON.parse);
  const vis = sel => ev(`(() => { const n = document.querySelector(${JSON.stringify(sel)}); return !!n && !n.hidden && n.getClientRects().length > 0; })()`);

  await load('?tab=projects');
  check('Projects tab: the New project and Check & update buttons are visible at the top, above the first card', await vis('[data-toggle="newbox"]') && await vis('[data-cmd="check"]') && await ev(`document.querySelector('[data-toggle="newbox"]').getBoundingClientRect().top < document.querySelector('.card').getBoundingClientRect().top`));
  check('the New project box is closed at first', !(await vis('[data-newbox]')));
  await cdp('Emulation.setFocusEmulationEnabled', { enabled: true }); await click('[data-toggle="newbox"]');
  check('+ New project opens the box in place (focus in the name field, aria-expanded) and tells the extension not to redraw', await vis('[data-newbox]') && await ev(`document.activeElement.dataset.nf`) === 'name' && await ev(`document.querySelector('[data-toggle="newbox"]').getAttribute('aria-expanded')`) === 'true' && (await msgs()).some(x => x.type === 'editing' && x.on === true));
  await click('[data-nform="cancel"]'); await click('[data-cmd="check"]'); await cdp('Emulation.setFocusEmulationEnabled', { enabled: false });
  const mc = await msgs(); check('Cancel closes the box; Check & update sends a cmd message; no newProject cmd any more', !(await vis('[data-newbox]')) && mc.some(x => x.type === 'cmd' && x.name === 'check') && !mc.some(x => x.name === 'newProject' || x.type === 'newproject'), JSON.stringify(mc));
  await ev('window.__msgs.length = 0');
  await load('?tab=ideas&proj=sample-app');
  check('Ideas tab shows the dropdown, set to the current project, and only that project\'s list', await vis('[data-psel]') && await ev('document.querySelector("[data-psel]").value') === 'sample-app' && await vis('.ilist[data-proj="sample-app"]') && !(await vis('.ilist[data-proj="ideas"]')));
  check('the dropdown lists all four projects (long name included) plus All projects', await ev('document.querySelector("[data-psel]").options.length') === 5);
  check('the dropdown starts with "All projects" and lists every project after it', await ev(`[...document.querySelector('[data-psel]').options].map(o => o.value)[0]`) === '__all__' && await ev('document.querySelector("[data-psel]").options.length') === 5);
  await ev(`(() => { const s = document.querySelector('[data-psel]'); s.value = '__all__'; s.dispatchEvent(new Event('change', { bubbles: true })); })()`);
  check('All projects shows every idea of every project, grouped by project, and nothing else', await vis('.ilist[data-proj="__all__"]') && !(await vis('.ilist[data-proj="sample-app"]')) && await ev(`[...document.querySelectorAll('.ilist[data-proj="__all__"] .igname span:first-child')].map(n => n.textContent).join(',')`) === 'sample-app,' + LONG);
  check('in All projects each idea acts on its own project (buttons carry the real project)', await ev(`[...document.querySelectorAll('.ilist[data-proj="__all__"] .igroup')].every(g => { const n = g.querySelector('.igname span').textContent; return [...g.querySelectorAll('[data-project]')].every(b => b.dataset.project === n); })`));
  await click('.ilist[data-proj="__all__"] [data-toggle="addbox"]');
  check('the add form of All projects offers every project and starts on the one you are in', await vis('.ilist[data-proj="__all__"] [data-addbox]') && await ev(`document.querySelector('.ilist[data-proj="__all__"] [data-f="project"]').value`) === 'sample-app');
  await click('.ilist[data-proj="__all__"] [data-form="cancel"]');
  await ev(`(() => { const s = document.querySelector('[data-psel]'); s.value = 'ideas'; s.dispatchEvent(new Event('change', { bubbles: true })); })()`);
  check('choosing another project in the dropdown switches the list (Inbox)', await vis('.ilist[data-proj="ideas"]') && !(await vis('.ilist[data-proj="sample-app"]')));
  await ev(`(() => { const s = document.querySelector('[data-psel]'); s.value = 'sample-app'; s.dispatchEvent(new Event('change', { bubbles: true })); })()`);
  check('the add box is closed until you press + Add idea', !(await vis('.ilist[data-proj="sample-app"] [data-addbox]')));
  await click('.ilist[data-proj="sample-app"] [data-toggle="addbox"]');
  await load('?tab=ideas&proj=sample-app');
  check('the add form stays open when the panel redraws (it used to open and vanish)', await vis('.ilist[data-proj="sample-app"] [data-addbox]'));
  await click('.ilist[data-proj="sample-app"] [data-toggle="addbox"]'); await load('?tab=ideas&proj=sample-app');
  check('closing the form with + Add idea again keeps it closed after a redraw', !(await vis('.ilist[data-proj="sample-app"] [data-addbox]')));
  await click('.ilist[data-proj="sample-app"] [data-toggle="addbox"]');
  // typing, then the panel is redrawn under you: the cursor must be back in the box, at the same place, so you can just carry on
  await ev(`(() => { const t = document.querySelector('.ilist[data-proj="sample-app"] [data-f="text"]'); t.value = 'abc def ghi'; t.setSelectionRange(7, 7); t.dispatchEvent(new FocusEvent('focusin', { bubbles: true })); t.dispatchEvent(new Event('input', { bubbles: true })); t.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true })); })()`);
  const ms0 = await msgs();
  await load('?tab=ideas&proj=sample-app');
  const back = await ev(`(() => { const t = document.querySelector('.ilist[data-proj="sample-app"] [data-f="text"]'); return { focused: document.activeElement === t, value: t.value, caret: [t.selectionStart, t.selectionEnd] }; })()`);
  check('while typing, a redraw puts the cursor back in the box at the same place (no clicking needed to carry on)', back.focused && back.value === 'abc def ghi' && back.caret[0] === 7 && back.caret[1] === 7, JSON.stringify(back));
  check('the panel tells the extension when you start editing (so it can hold the redraw)', ms0.some(m => m.type === 'editing' && m.on === true), JSON.stringify(ms0));
  await ev(`(() => { const t = document.querySelector('.ilist[data-proj="sample-app"] [data-f="text"]'); t.dispatchEvent(new FocusEvent('focusout', { bubbles: true })); t.value = ''; t.dispatchEvent(new Event('input', { bubbles: true })); })()`);
  await ev('window.__msgs.length = 0');
  await load('?tab=ideas&proj=sample-app');
  check('after you leave the box, a redraw does not pull the cursor back into it', await ev(`document.activeElement !== document.querySelector('.ilist[data-proj="sample-app"] [data-f="text"]')`));
  check('+ Add idea opens the form inside the tab (no VS Code bar)', await vis('.ilist[data-proj="sample-app"] [data-addbox]') && await vis('.ilist[data-proj="sample-app"] [data-f="text"]'));
  check('the form dropdown preselects the project and has no held project', await ev(`document.querySelector('.ilist[data-proj="sample-app"] [data-f="project"]').value`) === 'sample-app' && await ev(`![...document.querySelectorAll('.ilist[data-proj="sample-app"] [data-f="project"] option')].some(o => o.value === 'gate')`));
  await ev(`(() => { const t = document.querySelector('.ilist[data-proj="sample-app"] [data-f="text"]'); t.value = 'Half typed idea #x'; t.dispatchEvent(new Event('input', { bubbles: true })); })()`);
  await load('?tab=ideas&proj=sample-app');
  check('a half-typed idea survives a redraw of the panel', await vis('.ilist[data-proj="sample-app"] [data-addbox]') && await ev(`document.querySelector('.ilist[data-proj="sample-app"] [data-f="text"]').value`) === 'Half typed idea #x');
  await ev(`(() => { const t = document.querySelector('.ilist[data-proj="sample-app"] [data-f="text"]'); t.value = ''; })()`);
  await click('.ilist[data-proj="sample-app"] [data-form="add"]');
  check('Add with an empty box sends nothing and keeps the form open', (await msgs()).length === 0 && await vis('.ilist[data-proj="sample-app"] [data-addbox]'));
  await ev(`(() => { const b = document.querySelector('.ilist[data-proj="sample-app"] [data-addbox]'); b.querySelector('[data-f="text"]').value = 'Brand new idea #y'; b.querySelector('[data-f="project"]').value = 'ideas'; })()`);
  await click('.ilist[data-proj="sample-app"] [data-form="addreview"]');
  const m1 = (await msgs()).filter(x => x.type === 'idea');
  check('"Add and check if it is worth it" sends project, text and review=true, then closes and clears the draft', m1.length === 1 && m1[0].op === 'add' && m1[0].project === 'ideas' && m1[0].text === 'Brand new idea #y' && m1[0].review === true && !(await vis('.ilist[data-proj="sample-app"] [data-addbox]')) && await ev(`(JSON.parse(sessionStorage.getItem('st')||'{}').draft) === undefined`), JSON.stringify(m1));
  await ev('window.__msgs.length = 0');
  await click('.ilist[data-proj="sample-app"] [data-pick="move"]'); await ev(`(() => { const s = document.querySelector('.ilist[data-proj="sample-app"] .pickrow select'); s.value = 'ideas'; s.dispatchEvent(new Event('change', { bubbles: true })); })()`);
  await load('?tab=ideas&proj=sample-app');
  check('the Move dropdown and its chosen project survive a redraw', await vis('.ilist[data-proj="sample-app"] .pickrow select') && await ev(`document.querySelector('.ilist[data-proj="sample-app"] .pickrow select').value`) === 'ideas');
  await click('.ilist[data-proj="sample-app"] .pickrow .btn.quiet'); await click('.ilist[data-proj="sample-app"] [data-pick="move"]');
  check('Move… opens a dropdown right under the idea, without the current or a held project', await vis('.ilist[data-proj="sample-app"] .pickrow select') && await ev(`[...document.querySelectorAll('.ilist[data-proj="sample-app"] .pickrow select option')].map(o => o.value).sort().join(',')`) === ['ideas', LONG].sort().join(','));
  await ev(`(() => { const s = document.querySelector('.ilist[data-proj="sample-app"] .pickrow select'); s.value = 'ideas'; })()`);
  await click('.ilist[data-proj="sample-app"] .pickrow .btn.primary');
  const m2 = await msgs();
  check('"Move here" sends move with the chosen project and closes the dropdown', m2.length === 1 && m2[0].op === 'move' && m2[0].project === 'sample-app' && m2[0].id === 'F1' && m2[0].to === 'ideas' && !(await vis('.pickrow')), JSON.stringify(m2));
  await ev('window.__msgs.length = 0');
  await click('.ilist[data-proj="sample-app"] [data-pick="copy"]'); await click('.ilist[data-proj="sample-app"] .pickrow .btn.quiet');
  check('Cancel closes the dropdown and sends nothing', (await msgs()).length === 0 && !(await vis('.pickrow')));
  await click('.ilist[data-proj="sample-app"] [data-op="drop"]');
  check('Drop asks again in place ("Sure?") and sends nothing yet', (await msgs()).length === 0 && (await ev(`document.querySelector('.ilist[data-proj="sample-app"] [data-op="drop"]').textContent`)).startsWith('Sure'));
  await click('.ilist[data-proj="sample-app"] [data-op="drop"]');
  const m3 = await msgs(); check('the second click drops', m3.length === 1 && m3[0].op === 'drop' && m3[0].id === 'F1', JSON.stringify(m3));
  await ev('window.__msgs.length = 0');
  await click('.ilist[data-proj="sample-app"] [data-op="never"]');
  check('Mute reminders sends never for that project', (await msgs())[0].op === 'never' && (await msgs())[0].project === 'sample-app');
  // layout: nothing leaves its box, also with a very long project name
  await load('?tab=ideas&proj=' + encodeURIComponent(LONG));
  const over = await ev(`(() => { const box = document.querySelector('.ilist:not([hidden])').getBoundingClientRect(); return [...document.querySelectorAll('.ilist:not([hidden]) .btn, .ilist:not([hidden]) select, .ilist:not([hidden]) .iname, [data-psel]')].filter(n => n.getClientRects().length && n.getBoundingClientRect().right > box.right + 1).map(n => n.className + ':' + n.textContent.slice(0, 20)); })()`);
  check('with a very long project name no button, label or dropdown leaves the box', over.length === 0, JSON.stringify(over));
  await click('.ilist:not([hidden]) [data-toggle="addbox"]');
  const over2 = await ev(`(() => { const box = document.querySelector('.ilist:not([hidden])').getBoundingClientRect(); return [...document.querySelectorAll('.ilist:not([hidden]) [data-addbox] *')].filter(n => n.getClientRects().length && n.getBoundingClientRect().right > box.right + 1).map(n => n.tagName); })()`);
  check('the open add form also stays inside the box', over2.length === 0, JSON.stringify(over2));
  const shot = await cdp('Page.captureScreenshot', { format: 'png' }); fs.writeFileSync(H.work + '/shipmiracle-ui-test.png', Buffer.from(shot.result.data, 'base64'));
  console.log(fails ? '\nFAILED: ' + fails : '\nALL PASS'); ws.close(); killChrome(); process.exit(fails ? 1 : 0);
})().catch(e => { console.error('test crashed:', e.message); killChrome(); process.exit(2); });
