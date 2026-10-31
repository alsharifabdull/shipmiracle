// Cross-platform onboarding, Setup tab (plan 2026-10-21-cross-platform-onboarding.md 4.6, acceptance O12) in real headless Chrome. Calm view: every required row ready -> one "Setup complete" line, a sub-line,
// "Check again" and a closed Details button (no Fix button, no Quick setup card, no warning on screen). Fix view: "Setup · N to fix" and only the not-ready required rows on top with their Fix button, the Quick setup
// card there only while it has never been run. Details (a button with aria-expanded, state kept in vscode.setState) holds the OS line, the card (when not on top) and every other row. Also: the Quick setup card
// (five choices, the recommended answer selected, the exact prefilled command, one message), unsupported rows, optional rows never red, ASCII marks, hostile text, an older CLI (no onboarding fields) keeping the old
// list, keyboard, contrast and targets at 280 / 315 / 360 in Dark+, Light+, High Contrast.
// Screenshots only with SHIPMIRACLE_SHOTS=1 (tests/fixtures/panel-v3-setup, or the folder in SHIPMIRACLE_SHOTS_DIR). Run: node tests/panel_v3_setup_test.js    (skips without Chrome)
require('./shipmiracle_isolation').apply();
const fs = require('fs'), path = require('path');
const D = require('./panel_cdp');
if (!D.H.available()) { console.log('SKIP no Chrome'); process.exit(0); }
const F3 = require('./panel_v3_tab_fixtures');
const C = D.checker(), check = C.check;
const SHOTS = process.env.SHIPMIRACLE_SHOTS_DIR || path.join(__dirname, 'fixtures', 'panel-v3-setup'), WRITE = process.env.SHIPMIRACLE_SHOTS === '1';
if (WRITE) fs.mkdirSync(SHOTS, { recursive: true });
// rows as the CLI sends them (the plan's section 4.3 fields). Built from the fixture rows; the optional-not-ready ones are RED in the CLI's data on purpose: the panel must show them grey.
const stageOf = r => (r.id === 'prefs' ? 'prefs' : ['advanced'].includes(r.cls) ? 'advanced' : r.need === 'required' || r.need === 'recommended' ? 'connect' : 'advanced');
const rowsCli = (over = {}, extra = []) => [...F3.ROWS(), ...extra]
  .map(r => ({ ...r, stage: stageOf({ ...r, cls: r.need }), class: r.need === 'advisory' ? 'advisory' : r.need, os_supported: true, docs: r.id === 'git-id' ? 'https://git-scm.com/downloads' : '', ...(over[r.id] || {}) }));
const OS = k => ({ macos: { kind: 'macos', line: 'This computer: macOS 27.0 (arm64). Supported: CLI, hooks, panel, autopilot, awake guard. Not here: nothing. Confirmations: not checked.' },
  linux: { kind: 'linux', line: 'This computer: Ubuntu 24.04 (x86_64). Supported: CLI, hooks, panel, autopilot. Not here: awake guard, iOS tools. Confirmations: password (basic).' } })[k];
const SETUP = (os = 'macos', rows = rowsCli(), quick = true) => ({ rows: rows.map(r => ({ ...r })), ready: false, error: false, at: 'now', os: quick ? OS(os) : null, quick });
const DATA = (o = {}) => ({ projects: [], plan: { meters: [] }, remote: { state: 'off' }, setup: SETUP(), ...o });

(async () => {
  const S = await D.session({ size: '345,900' }); const load0 = S.load; S.load = async (...a) => { try { await S.sleep(260); await S.ev(`sessionStorage.clear()`); } catch (e) { /* first load */ } return load0(...a); };
  const msgs = () => S.ev('JSON.stringify(window.__msgs)').then(JSON.parse).then(a => a.filter(x => x.type !== 'editing'));
  const clr = () => S.ev('window.__msgs.length = 0');
  const load = async (data, theme = 'dark', w = 315, vars) => { await S.load(S.file('su-' + theme + w, D.page(theme, data, vars)), w, '?tab=setup', 9000); };
  const pane = '#pane-setup';

  await load(DATA());
  const redReq = rowsCli().filter(r => r.need === 'required' && r.state !== 'green').map(r => r.id);
  const g = await S.ev(`(() => { const p = document.querySelector('${pane}'); const ids = s => [...p.querySelectorAll(s)].map(l => l.dataset.row), vis = n => !!n && n.getClientRects().length > 0, det = p.querySelector('[data-sdetbody]'), qs = p.querySelector('.qs');
    return { view: p.querySelector('.shead').dataset.view, head: p.querySelector('.shead b').textContent, ready: p.querySelector('[data-ready]').textContent, needs: ids('.qn li'), more: ids('[data-sdetbody] li'), detOpen: p.querySelector('[data-sdet]').getAttribute('aria-expanded'), detHidden: det.hidden, detLabel: p.querySelector('[data-sdet]').childNodes[0].textContent.trim(),
      osInDet: det.contains(p.querySelector('.osl')), prefsRow: !!p.querySelector('[data-row="prefs"]'), cardVisible: vis(qs), cardInDet: det.contains(qs), cardAfterNeeds: !!(p.querySelector('.qn').compareDocumentPosition(qs) & 4), check: p.querySelector('[data-setup="recheck"]').textContent,
      topBtns: [...p.querySelectorAll('.qn [data-setup]')].map(b => b.dataset.setup + ':' + b.dataset.id), visBtns: [...p.querySelectorAll('button')].filter(vis).map(b => b.textContent.trim()).slice(0, 4) }; })()`);
  check(`S1 one required row red -> header "Setup · ${redReq.length} to fix" (never a hard-coded number), view "fix", "Finish the required rows first."`, g.view === 'fix' && g.head === `Setup · ${redReq.length} to fix` && g.ready === 'Finish the required rows first.', JSON.stringify(g));
  check('S1 the top lists exactly the not-ready required rows (git-id), each with its Fix button and no Skip (a required row cannot be skipped); "Check again" stays', JSON.stringify(g.needs) === JSON.stringify(redReq) && JSON.stringify(g.topBtns) === JSON.stringify(redReq.map(i => 'fix:' + i)) && g.check === 'Check again', JSON.stringify(g));
  check('S1 Quick setup was never run (prefs row not green): the card stays in view right after the not-ready rows, outside Details', g.cardVisible && !g.cardInDet && g.cardAfterNeeds, JSON.stringify(g));
  check('S1 Details is a button, closed by default (aria-expanded false, body hidden); it holds the OS line and every other row (none of the top rows, not the prefs row)', g.detLabel === 'Details' && g.detOpen === 'false' && g.detHidden && g.osInDet && !g.prefsRow && !g.more.some(i => g.needs.includes(i)) && g.more.length === rowsCli().length - g.needs.length - 1, JSON.stringify([g.detLabel, g.detOpen, g.more.length, g.visBtns]));
  // "Check again" follows the panel's button standard: a real .btn (the same class as the Fix button and the Health / Reports header buttons), not a link
  const std = await S.ev(`(() => { const p = document.querySelector('${pane}'); const cs = n => { const c = getComputedStyle(n); return [c.height, c.borderTopLeftRadius, c.borderTopWidth, c.fontSize, c.paddingLeft, c.borderTopColor].join('|'); };
    const b = p.querySelector('.shead [data-setup="recheck"]'), fx = p.querySelector('.qn [data-setup="fix"]'), sh = p.querySelector('.shead'), bb = b.getBoundingClientRect(), hb = sh.querySelector('b').getBoundingClientRect(), pr = sh.getBoundingClientRect();
    return { tag: b.tagName, type: b.type, cls: b.className, busy: b.dataset.busy, aria: b.getAttribute('aria-label'), css: cs(b), fixCss: cs(fx), fixCls: fx.className, td: getComputedStyle(b).textDecorationLine, bg: getComputedStyle(b).backgroundColor, right: Math.abs(pr.right - bb.right) < 2, sameRow: Math.abs((bb.top + bb.height / 2) - (hb.top + hb.height / 2)) < 3, h: Math.round(bb.height), lnk: b.classList.contains('lnk') || b.classList.contains('scheck') }; })()`);
  check('S4 "Check again" is a real <button type=button class="btn"> (not a link): no underline, a filled border and background, same height / radius / border / font as the Fix button, at the right end of the header row', std.tag === 'BUTTON' && std.type === 'button' && std.cls === 'btn' && !std.lnk && std.td === 'none' && [0, 1, 2, 3, 5].every(i => std.css.split('|')[i] === std.fixCss.split('|')[i]) && std.right && std.sameRow && std.h >= 26, JSON.stringify(std));
  check('S4 "Check again" keeps its busy label for the shared click handler (data-busy "Checking…") and is secondary (not primary) next to the Fix buttons', std.busy === 'Checking…' && !std.cls.includes('primary') && !std.fixCls.includes('primary'), JSON.stringify(std));
  // Details follows the History toggle standard (button.lnk, text + trailing chevron span aria-hidden, aria-expanded + aria-controls, same height / colour / underline)
  const ds = await S.ev(`(() => { const p = document.querySelector('${pane}'); const b = p.querySelector('[data-sdet]'); const c = getComputedStyle(b), ch = b.querySelector('[aria-hidden="true"]'); const r = b.getBoundingClientRect(); return { cls: b.className, td: c.textDecorationLine, h: Math.round(r.height), fs: c.fontSize, col: c.color, chev: !!ch && ch.textContent.trim(), ctl: b.getAttribute('aria-controls'), regionHidden: document.getElementById(b.getAttribute('aria-controls')).hidden, role: document.getElementById(b.getAttribute('aria-controls')).getAttribute('role') }; })()`);
  check('S4 Details uses the same disclosure standard as the timeline History toggle: <button class="lnk ...">, link look (underline, 11.5px, >= 24 px high), trailing chevron span (aria-hidden), aria-expanded + aria-controls', /\blnk\b/.test(ds.cls) && ds.td === 'underline' && ds.fs === '11.5px' && ds.h >= 24 && ds.chev === '▸' && ds.ctl === 'sdet-body' && ds.regionHidden, JSON.stringify(ds));
  const dt = await S.ev(`(() => { const b = document.querySelector('${pane} [data-sdet]'), body = document.getElementById(b.getAttribute('aria-controls')); const o = { tag: b.tagName, type: b.type, ctl: !!body }; b.click(); o.open = { exp: b.getAttribute('aria-expanded'), hidden: body.hidden, shown: body.getClientRects().length > 0, st: JSON.parse(sessionStorage.getItem('st') || '{}').sdet }; return o; })()`);
  check('S2 Details toggle: a real <button type=button> controlling its body; a click opens it (aria-expanded true, body visible) and writes the choice into vscode.setState', dt.tag === 'BUTTON' && dt.type === 'button' && dt.ctl && dt.open.exp === 'true' && !dt.open.hidden && dt.open.shown && dt.open.st === 1, JSON.stringify(dt));
  await S.cdp('Page.reload'); await S.sleep(500);
  check('S2 the open Details survives a redraw (read back from vscode.setState)', await S.ev(`document.querySelector('${pane} [data-sdet]').getAttribute('aria-expanded') === 'true' && !document.querySelector('${pane} [data-sdetbody]').hidden`));
  await S.ev(`document.querySelector('${pane} [data-sdet]').click()`);
  const dc = await S.ev(`({ exp: document.querySelector('${pane} [data-sdet]').getAttribute('aria-expanded'), hidden: document.querySelector('${pane} [data-sdetbody]').hidden, st: JSON.parse(sessionStorage.getItem('st') || '{}').sdet })`);
  check('S2 a second click closes it again and clears the saved choice', dc.exp === 'false' && dc.hidden && dc.st === undefined, JSON.stringify(dc));
  await load(DATA({ setup: SETUP('macos', rowsCli({ [redReq[0]]: { state: 'red' }, base: { state: 'red' } })) }));
  const two = await S.ev(`({ head: document.querySelector('${pane} .shead b').textContent, ids: [...document.querySelectorAll('${pane} .qn li')].map(l => l.dataset.row) })`);
  check('S1 two required rows red -> "Setup · 2 to fix" and both are on top', two.head === 'Setup · 2 to fix' && two.ids.length === 2 && two.ids.includes('base') && two.ids.includes(redReq[0]), JSON.stringify(two));
  await load(DATA({ setup: SETUP('macos', rowsCli({ prefs: { state: 'green' } })) }));
  const pg = await S.ev(`(() => { const p = document.querySelector('${pane}'); const qs = p.querySelector('.qs'); return { inDet: p.querySelector('[data-sdetbody]').contains(qs), vis: qs.getClientRects().length > 0, n: p.querySelectorAll('.qs').length }; })()`);
  check('S1 Quick setup already run (prefs row green): the card moves into Details (once), the top shows only the not-ready rows', pg.inDet && !pg.vis && pg.n === 1, JSON.stringify(pg));
  const calmRows = rowsCli().map(r => (r.need === 'required' ? { ...r, state: 'green' } : r));
  await load(DATA({ setup: SETUP('macos', calmRows) }));
  const c = await S.ev(`(() => { const p = document.querySelector('${pane}'); const vis = n => !!n && n.getClientRects().length > 0, sh = p.querySelector('.shead'), det = p.querySelector('[data-sdetbody]');
    return { view: sh.dataset.view, head: sh.querySelector('b').textContent.trim(), icon: !!sh.querySelector('b svg[aria-hidden="true"]'), sub: p.querySelector('[data-ready]').textContent, visBtns: [...p.querySelectorAll('button')].filter(vis).map(b => b.childNodes[0].textContent.trim()), fixVisible: [...p.querySelectorAll('[data-setup="fix"],[data-setup="skip"],[data-setup="undo"]')].filter(vis).length,
      fixTotal: p.querySelectorAll('[data-setup="fix"]').length, cardVisible: vis(p.querySelector('.qs')), cardInDet: det.contains(p.querySelector('.qs')), top: !!p.querySelector('.qn'), redVisible: [...p.querySelectorAll('.chk.red')].filter(vis).length, rowsVisible: [...p.querySelectorAll('li.chk')].filter(vis).length, rowsAll: p.querySelectorAll('li.chk').length,
      osVisible: vis(p.querySelector('.osl')), exp: p.querySelector('[data-sdet]').getAttribute('aria-expanded'), noX: !/required ready|to fix|Needs you|Re-check/.test(p.textContent) }; })()`);
  check('S3 all required ready: one calm line "Setup complete" with a green check (decorative svg), the sub-line "Everything Shipmiracle needs is in place.", view "calm"', c.view === 'calm' && c.head === 'Setup complete' && c.icon && c.sub === 'Everything Shipmiracle needs is in place.', JSON.stringify(c));
  check('S3 the calm view shows only "Check again" and "Details": no Fix / Skip / Undo button, no Quick setup card, no row, no OS line, no red mark, no top list, no "N of M"', JSON.stringify(c.visBtns) === JSON.stringify(['Check again', 'Details']) && c.fixVisible === 0 && !c.cardVisible && c.cardInDet && !c.top && c.redVisible === 0 && c.rowsVisible === 0 && !c.osVisible && c.noX, JSON.stringify(c));
  check('S3 Details is closed by default; behind it sit the Quick setup card, the OS line and every row (optional rows that are not set included, grey), with their buttons', c.exp === 'false' && c.rowsAll === rowsCli().length - 1 && c.fixTotal > 0, JSON.stringify([c.exp, c.rowsAll, c.fixTotal]));
  await S.ev(`document.querySelector('${pane} [data-sdet]').click()`);
  const co = await S.ev(`(() => { const p = document.querySelector('${pane}'); const vis = n => !!n && n.getClientRects().length > 0; return { card: vis(p.querySelector('.qs')), os: vis(p.querySelector('.osl')), rows: [...p.querySelectorAll('li.chk')].filter(vis).length, opt: p.querySelector('[data-row="gitleaks"]').className, optBtn: !!p.querySelector('[data-row="gitleaks"] [data-setup="fix"]') }; })()`);
  check('S3 opening Details shows the card, the OS line and all rows; an optional row that is not set stays grey (never red)', co.card && co.os && co.rows === rowsCli().length - 1 && co.opt.includes('skip') && !co.opt.includes('red'), JSON.stringify(co));
  await clr(); await S.ev(`document.querySelector('${pane} [data-setup="recheck"]').click()`); await S.sleep(80);
  const rc = await msgs(), rb = await S.ev(`(() => { const b = document.querySelector('${pane} [data-setup="recheck"]'); return [b.disabled, b.textContent]; })()`);
  check('S3 "Check again" is the old Re-check all: one message {type:"setup", op:"recheck"} and the button shows the busy label while it checks', rc.length === 1 && rc[0].type === 'setup' && rc[0].op === 'recheck' && rb[0] === true && rb[1] === 'Checking…', JSON.stringify([rc, rb]));
  const dis = await S.ev(`(() => { const b = document.querySelector('${pane} [data-setup="recheck"]'); const c = getComputedStyle(b); return { dis: b.disabled, op: c.opacity, cur: c.cursor }; })()`);
  check('S4 the busy "Check again" button looks disabled like every other .btn (opacity .45, not-allowed cursor)', dis.dis && dis.op === '0.45' && dis.cur === 'not-allowed', JSON.stringify(dis));
  await load(DATA()); await clr(); await S.ev(`document.querySelector('${pane} .shead [data-setup="recheck"]').click()`); await S.sleep(80);
  const rf = await msgs(), rfb = await S.ev(`(() => { const b = document.querySelector('${pane} .shead [data-setup="recheck"]'); return [b.disabled, b.textContent]; })()`);
  check('S4 the fix view "Check again" sends the same single {type:"setup", op:"recheck"} message and shows "Checking…" (disabled)', rf.length === 1 && rf[0].type === 'setup' && rf[0].op === 'recheck' && rfb[0] === true && rfb[1] === 'Checking…', JSON.stringify([rf, rfb]));
  await load(DATA());
  const r0 = await S.ev(`(() => { const out = {}; document.querySelectorAll('${pane} li.chk').forEach(l => { out[l.dataset.row] = { cls: l.className, mark: l.querySelector('.cmark').textContent, txt: l.querySelector('.cmark').getAttribute('aria-label') }; }); return out; })()`);
  check('O12 optional rows are never red: the gitleaks row (red in the CLI data) is grey (skip) with a "-" mark; only a required row can be red', Object.keys(r0).length === rowsCli().length - 1 && r0.gitleaks.cls.includes('skip') && !r0.gitleaks.cls.includes('red') && r0.docker.cls.includes('skip') && r0['git-id'].cls.includes('red'), JSON.stringify([r0.gitleaks, r0.docker, r0['git-id']]));
  check('O12 symbols in the new layout are ASCII (+ ! - i) and always have a word label', Object.values(r0).every(x => /^[\x20-\x7e]+$/.test(x.mark) && x.txt), JSON.stringify(Object.values(r0).filter(x => !/^[\x20-\x7e]+$/.test(x.mark))));
  const q = await S.ev(`(() => { const p = document.querySelector('${pane} .qs'); return { legends: [...p.querySelectorAll('legend')].map(l => l.textContent), checked: [...p.querySelectorAll('input[type=radio]:checked')].map(i => i.dataset.qs + '=' + i.value), recs: [...p.querySelectorAll('.qsr')].map(x => x.closest('.qso').querySelector('input').value), folder: p.querySelector('input[type=text]').value, cmd: p.querySelector('[data-qscmd]').textContent, btn: p.querySelector('[data-setup="prefs"]').textContent, h: Math.round(p.querySelector('[data-setup="prefs"]').getBoundingClientRect().height) }; })()`);
  check('O12 the five choices (macOS): language, projects folder, autonomy, keep awake, notifications; the recommended answer is selected and marked (recommended)', q.legends.join('|') === 'Language for reports|Projects folder|How much should the team do by itself?|Keep the computer awake while Claude works?|Notifications' && q.checked.join() === 'lang=en,autonomy=normal,awake=yes,notify=vscode' && q.folder === '~/Developer' && q.recs.length === 4, JSON.stringify(q));
  check('O12 the command text is exactly `shipm init --prefs --lang en --folder ~/Developer --autonomy normal --awake yes --notify vscode`', q.cmd === 'shipm init --prefs --lang en --folder ~/Developer --autonomy normal --awake yes --notify vscode' && q.btn === 'Run in terminal' && q.h >= 26, q.cmd);
  await S.ev(`document.querySelector('input[data-qs=lang][value=ar]').click(); document.querySelector('input[data-qs=autonomy][value=step]').click(); document.querySelector('input[data-qs=awake][value=no]').click(); document.querySelector('input[data-qs=notify][value=none]').click();`);
  const f = await S.ev(`(() => { const i = document.querySelector('input[data-qs=folder]'); i.value = '~/Work/projects'; i.dispatchEvent(new Event('input', { bubbles: true })); return document.querySelector('[data-qscmd]').textContent; })()`);
  check('O12 changing a choice rewrites the command live', f === 'shipm init --prefs --lang ar --folder ~/Work/projects --autonomy step --awake no --notify none', f);
  await clr(); await S.ev(`document.querySelector('[data-setup="prefs"]').click()`); await S.sleep(100);
  const m = await msgs();
  check('O12 Run in terminal posts ONE message {type:"setup", op:"prefs", prefs:{lang, folder, autonomy, awake, notify}} and nothing else (no write call from the page)', m.length === 1 && m[0].type === 'setup' && m[0].op === 'prefs' && JSON.stringify(m[0].prefs) === JSON.stringify({ lang: 'ar', folder: '~/Work/projects', autonomy: 'step', awake: 'no', notify: 'none' }) && Object.keys(m[0]).sort().join() === 'id,op,prefs,type', JSON.stringify(m));
  await S.cdp('Page.reload'); await S.sleep(500);
  check('O12 the choices survive a redraw (vscode.setState)', await S.ev(`document.querySelector('[data-qscmd]').textContent`) === 'shipm init --prefs --lang ar --folder ~/Work/projects --autonomy step --awake no --notify none');
  await S.ev(`document.querySelector('${pane} [data-sdet]').click()`);
  check('O12 Details opens with a click and lists the optional / advanced rows', await S.ev(`!document.querySelector('${pane} [data-sdetbody]').hidden && document.querySelectorAll('${pane} [data-sdetbody] li').length > 5`));

  // Linux: no keep-awake choice, system pop-ups offered; unsupported rows
  const lin = rowsCli({ ios: { os_supported: false, state: 'skipped' }, guard: { os_supported: false, state: 'skipped', docs: 'https://example.org/awake' } });
  await load(DATA({ setup: SETUP('linux', lin) }));
  const l = await S.ev(`(() => { const p = document.querySelector('${pane}'); const ios = p.querySelector('[data-row="ios"]'), gd = p.querySelector('[data-row="guard"]'); return { legends: [...p.querySelectorAll('.qs legend')].map(x => x.textContent).join('|'), cmd: p.querySelector('[data-qscmd]').textContent, notify: [...p.querySelectorAll('input[data-qs=notify]')].map(i => i.value).join(), ios: ios.textContent.replace(/\\s+/g, ' ').trim(), iosBtn: ios.querySelectorAll('button').length, iosMark: ios.querySelector('.cmark').textContent, iosCls: ios.className, gd: gd.textContent.replace(/\\s+/g, ' ').trim(), os: p.querySelector('.osl').textContent }; })()`);
  check('O12 Linux: no keep-awake choice (only macOS has it), the command has no --awake, system pop-ups are offered', !/awake/i.test(l.legends) && l.cmd === 'shipm init --prefs --lang en --folder ~/Developer --autonomy normal --notify vscode' && l.notify === 'vscode,system,none', JSON.stringify([l.legends, l.cmd, l.notify]));
  check('O12 a row with os_supported:false says "Not supported on this OS", has no button, a "x" mark, is grey (not red) and is not counted as required', /Not supported on this OS/.test(l.ios) && l.iosBtn === 0 && l.iosMark === 'x' && !l.iosCls.includes('red') && /More: https:\/\/example\.org\/awake/.test(l.gd) && /Ubuntu 24\.04/.test(l.os), JSON.stringify(l));
  await load(DATA({ setup: SETUP('linux', rowsCli({ 'git-id': { os_supported: false, state: 'red' } })) }));
  const un = await S.ev(`({ head: document.querySelector('${pane} .shead b').textContent, view: document.querySelector('${pane} .shead').dataset.view, top: !!document.querySelector('${pane} .qn') })`);
  check('O12 an unsupported required row never counts: with it as the only red required row the tab is still the calm "Setup complete" (no top list)', un.head === 'Setup complete' && un.view === 'calm' && !un.top, JSON.stringify(un));

  // hostile text, old CLI, empty needs
  const host = rowsCli({ 'git-id': { title: '<img src=x onerror=alert(1)> Git', detail: '"><script>alert(1)</script> ' + 'w'.repeat(500), connect: { kind: 'hint', text: '<b>run</b> `rm -rf ~`' } } });
  const hs = SETUP('macos', host); hs.os = { kind: 'macos', line: '<script>alert(2)</script> This computer' };
  await load(DATA({ setup: hs }));
  check('hostile row title / detail / OS line stay text: no element, no handler, no horizontal scroll', await S.ev(`(() => { const p = document.querySelector('${pane}'); return !p.querySelector('img, script, [onerror], .qn b b') && p.querySelector('.osl').textContent.includes('<script>') && document.documentElement.scrollWidth <= document.documentElement.clientWidth && document.getElementById('scroll').scrollWidth <= document.getElementById('scroll').clientWidth; })()`));
  await load(DATA({ setup: SETUP('macos', F3.ROWS(), false) }));
  check('O12 an older CLI (no stage/class/os fields): no Quick setup card, no OS line, no Details button, the old full list is shown unchanged', await S.ev(`!document.querySelector('${pane} .qs, ${pane} .osl, ${pane} [data-sdet]') && document.querySelectorAll('${pane} li.chk').length === ${F3.ROWS().length}`));

  // keyboard + contrast + targets + no scroll at the three widths in the three themes
  const walk = async () => { const order = []; await S.ev(`document.activeElement && document.activeElement.blur(); document.querySelector('${pane} .qs').scrollIntoView()`); await S.ev(`document.querySelector('input[data-qs=lang]').focus()`);
    for (let i = 0; i < 9; i++) { order.push(await S.ev(`(() => { const a = document.activeElement; return a.tagName + ':' + (a.dataset.qs || a.dataset.setup || a.tagName); })()`)); await S.cdp('Input.dispatchKeyEvent', { type: 'rawKeyDown', key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9 }); await S.cdp('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9 }); } return order; };
  await load(DATA());
  const ord = await walk();
  check('keyboard: Tab goes language, folder, autonomy, awake, notifications, then Run in terminal (a radio group is one stop)', ord.slice(0, 6).join() === 'INPUT:lang,INPUT:folder,INPUT:autonomy,INPUT:awake,INPUT:notify,BUTTON:prefs', ord.join());
  await S.ev(`document.querySelector('input[data-qs=autonomy]:checked').focus()`); await S.key('ArrowRight', 'ArrowRight', 39); await S.sleep(80);
  check('keyboard: the arrow keys move inside a choice and update the command', (await S.ev(`document.querySelector('[data-qscmd]').textContent`)).includes('--autonomy step'));
  await S.ev(`document.querySelector('${pane} [data-sdet]').focus()`); await S.key('Enter', 'Enter', 13, '\r'); await S.sleep(80);
  const openedByEnter = await S.ev(`document.querySelector('${pane} [data-sdet]').getAttribute('aria-expanded') === 'true'`);
  await S.key(' ', 'Space', 32, ' '); await S.sleep(80);
  check('keyboard: Enter on Details opens it, Space closes it again', openedByEnter && await S.ev(`document.querySelector('${pane} [data-sdet]').getAttribute('aria-expanded') === 'false'`));
  const ring = await S.ev(`(() => { const b = document.querySelector('${pane} [data-sdet]'); b.focus(); const cs = getComputedStyle(b); return { out: cs.outlineStyle, w: cs.outlineWidth, fv: b.matches(':focus-visible') }; })()`);
  check('keyboard: Details shows a visible focus ring', ring.out !== 'none' && parseFloat(ring.w) >= 2, JSON.stringify(ring));
  for (const [label, theme] of [['Dark+', 'dark'], ['Light+', 'light'], ['High Contrast', 'hc']]) for (const w of [280, 315, 360]) {
    await load(DATA({ setup: SETUP('linux', lin) }), theme, w, D.THEMES[theme]); await S.ev(`document.querySelector('${pane} [data-sdet]').click()`); await S.sleep(120);
    const tx = await S.ev(D.TEXT_IN(`${pane} *`)), bad = tx.filter(x => x.ratio < 4.5);
    const tg = await S.ev(`[...document.querySelectorAll('${pane} button, ${pane} summary, ${pane} .qso')].filter(b => b.getClientRects().length).map(b => Math.round(b.getBoundingClientRect().height)).filter(h => h < 22)`);
    const hs2 = await S.ev(`document.documentElement.scrollWidth <= document.documentElement.clientWidth && document.getElementById('scroll').scrollWidth <= document.getElementById('scroll').clientWidth`);
    check(`[${label} ${w}] Setup text >= 4.5:1 (${tx.length} elements), targets >= 22 px, no horizontal scroll`, tx.length > 20 && bad.length === 0 && tg.length === 0 && hs2, JSON.stringify({ bad: bad.slice(0, 5), tg, hs2 }));
    await load(DATA({ setup: SETUP('macos', calmRows) }), theme, w, D.THEMES[theme]); await S.sleep(120);
    const tx2 = await S.ev(D.TEXT_IN(`${pane} *`)), bad2 = tx2.filter(x => x.ratio < 4.5);
    const tg2 = await S.ev(`[...document.querySelectorAll('${pane} button')].filter(b => b.getClientRects().length).map(b => Math.round(b.getBoundingClientRect().height)).filter(h => h < 22)`);
    const hs3 = await S.ev(`document.documentElement.scrollWidth <= document.documentElement.clientWidth`);
    check(`[${label} ${w}] calm view: text >= 4.5:1 (${tx2.length} elements; the green title and the link buttons included), buttons >= 22 px, no horizontal scroll`, tx2.length >= 3 && bad2.length === 0 && tg2.length === 0 && hs3, JSON.stringify({ bad: bad2.slice(0, 5), tg2, hs3 }));
  }
  if (WRITE) for (const theme of ['dark', 'light']) for (const [name, data, open] of [['calm', DATA({ setup: SETUP('macos', calmRows) }), false], ['calm-details', DATA({ setup: SETUP('macos', calmRows) }), true], ['fix', DATA(), false]]) {
    await load(data, theme, 315, D.THEMES[theme]); if (open) await S.ev(`document.querySelector('${pane} [data-sdet]').click()`); await S.sleep(150);
    await S.ev(`document.getElementById('scroll').scrollTop = 0`);
    const h = await S.ev(`Math.min(1800, document.getElementById('scroll').scrollHeight + 60)`);
    fs.writeFileSync(path.join(SHOTS, `setup-${name}-${theme}-315.png`), await S.shot({ x: 0, y: 0, width: 315, height: Math.max(h, 200) }, 2));
  }
  S.close();
  console.log(C.fails ? `\nFAILED: ${C.fails} of ${C.n}` : `\nALL PASS (${C.n})`); process.exit(C.fails ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
