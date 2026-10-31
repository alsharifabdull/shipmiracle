// F5 Toolbox sheet and F6 Describe your work (UX addendum sections 1 and 2; acceptance 13, 15-17) in real headless Chrome: shown only when the CLI says caps.toolbox / caps.interview;
// every button posts a message (the extension types the command, never Enter); status words and shapes; the 20-row cap; the Short / Long choice; the read-only mirror, paused, draft and error states;
// hostile text; contrast and targets in Dark+, Light+, High Contrast at 280 / 315 / 360. Run: node tests/panel_v3_f56_test.js    (skips without Chrome)
require('./shipmiracle_isolation').apply();
const D = require('./panel_cdp');
if (!D.H.available()) { console.log('SKIP no Chrome'); process.exit(0); }
const F = require('./panel_v3_fixtures');
const C = D.checker(), check = C.check;
const now = Math.floor(Date.now() / 1000);
const asset = (path, st, status = 'ok', purpose = 'Seeds the demo data') => ({ path, stage: st, stageLabel: { do: 'Build', verify: 'Test', plan: 'Plan' }[st] || st, purpose, status });
const ASSETS = [asset('docs/rtl-checklist.md', 'verify', 'changed', 'Checklist for RTL checks'), asset('scripts/gone.py', 'do', 'missing', 'Was a helper'), asset('scripts/seed_menu.py', 'do'), asset('scripts/<b>x</b> "q" \'s\'.py', 'plan', 'ok', '<img src=x onerror=alert(1)> ' + 'long '.repeat(40))];
const many = Array.from({ length: 25 }, (_, k) => asset('scripts/tool' + String(k).padStart(2, '0') + '.py', 'do'));
const tb = (assets, count) => ({ count: count == null ? assets.length : count, changed: assets.filter(a => a.status !== 'ok').length, assets });
const noPb = (name, o = {}) => ({ ...F.mk(name, 'software', o), playbook: null, cr: null, stageLabels: null });
const mir = (o = {}) => ({ status: 'asking', mode: 'short', n: 3, total: 8, updated: now, question: { text: 'Who approves a finished recipe page?', recommended: 'You, before anything goes live.' }, assumed: ['Output is a web page', 'Tests run with npm test'], prototype: [], draftOk: false, rows: [], ...o });
const NINE = ['Work', 'Inputs', 'Outputs', 'Tools', 'Risks', 'Who approves', 'Definition of done', 'Never allowed', 'Assumed'].map(l => ({ label: l, text: l + ' text <b>x</b> ' + (l === 'Work' ? 'w'.repeat(250) : '') }));
const proj = () => [
  F.mk('tb-app', 'software', { toolbox: tb(ASSETS) }), F.mk('tb-many', 'software', { toolbox: tb(many.slice(0, 100), 25) }), F.mk('tb-empty', 'software', { toolbox: tb([]) }), F.mk('tb-busy', 'software', { state: 'working', toolbox: tb(ASSETS.slice(2, 3)) }),
  noPb('old-app', { lastCommit: now - 5000 }), noPb('new-app', { lastCommit: 0 }), noPb('busy-new', { state: 'working', lastCommit: 0 }),
  noPb('mir-ask', { mirror: mir(), interview: { status: 'asking', mode: 'short', n: 3, total: 8, draft: false } }), noPb('mir-pause', { mirror: mir({ status: 'paused', n: 4 }) }), noPb('mir-draft', { mirror: mir({ status: 'draft', draftOk: true, rows: NINE }) }),
  noPb('mir-bad', { mirror: mir({ status: 'draft', draftOk: false }) }), noPb('mir-err', { mirror: mir({ status: 'error' }) }),
  noPb('mir-host', { mirror: mir({ question: { text: '<img src=x onerror=alert(1)> ' + 'q'.repeat(300), recommended: '<b>r</b>' }, assumed: ['<script>alert(1)</script>'] }) })
];
const DATA = (o = {}) => ({ projects: proj(), capabilities: { toolbox: true, interview: true, aside: false }, plan: { meters: [] }, ...o });
const card = nm => `[...document.querySelectorAll('.card')].find(c => c.querySelector('.name').textContent === ${JSON.stringify(nm)})`;

(async () => {
  const S = await D.session({ size: '345,900' }); const load0 = S.load; S.load = async (...a) => { try { await S.sleep(260); await S.ev(`sessionStorage.clear()`); } catch (e) { /* first load */ } return load0(...a); };
  const msgs = () => S.ev('JSON.stringify(window.__msgs)').then(JSON.parse).then(a => a.filter(x => x.type !== 'editing'));
  const clr = () => S.ev('window.__msgs.length = 0');
  const load = async (data, theme = 'dark', w = 315, vars) => { await S.load(S.file('f56-' + theme + w, D.page(theme, data, vars)), w, '?tab=projects', 12000); };
  const menuOpen = nm => S.ev(`${card(nm)}.querySelector('.btn.more').click()`);
  const sheet = (nm, kind) => `${card(nm)}.querySelector('[data-sheetbox="${kind}"]')`;
  const wait = ms => S.sleep(ms);

  await load(DATA({ capabilities: { toolbox: false, interview: false } }));
  check('13 caps off: no Toolbox / Describe menu item, no sheet, no mirror', await S.ev(`!document.querySelector('[data-sheetbox="toolbox"], [data-sheetbox="describe"], .mirror, [data-sheet="toolbox"], [data-sheet="describe"]')`));
  await load(DATA());
  const items = {}; for (const n of ['tb-app', 'tb-empty', 'old-app', 'tb-many']) items[n] = await S.ev(`[...${card(n)}.querySelectorAll('.menu .mi')].map(b => b.textContent.trim()).filter(t => /Toolbox|Describe/.test(t))`);
  check('13 menu: "Toolbox · 4" with a count, "Toolbox" when empty; "Describe your work…" only on a card without a playbook', JSON.stringify(items) === JSON.stringify({ 'tb-app': ['Toolbox · 4'], 'tb-empty': ['Toolbox'], 'old-app': ['Describe your work…'], 'tb-many': ['Toolbox · 25'] }), JSON.stringify(items));
  await menuOpen('tb-app'); await S.ev(`${card('tb-app')}.querySelector('[data-sheet="toolbox"]').click()`); await wait(150);
  const t1 = await S.ev(`(() => { const b = ${sheet('tb-app', 'toolbox')}; return { vis: !b.hidden, head: b.querySelector('.tbhead b').textContent, back: b.querySelector('[data-sheetclose]').textContent, rows: [...b.querySelectorAll('.tbr')].map(r => ({ p: r.querySelector('.tbp').textContent, st: r.querySelector('.tbst').textContent.replace(/\\s+/g, ' ').trim(), btns: [...r.querySelectorAll('button')].map(x => x.textContent), hint: !!r.querySelector('.nhint'), aria: r.getAttribute('aria-label') })), add: [...b.querySelectorAll('button')].pop().textContent, note: b.lastElementChild.textContent }; })()`);
  check('13 Toolbox sheet: heading "Toolbox for tb-app", ‹ Back, one row per asset in the CLI order (changed and missing first)', t1.vis && t1.head === 'Toolbox for tb-app' && t1.back === '‹ Back' && t1.rows.length === 4 && t1.rows[0].p === 'docs/rtl-checklist.md', JSON.stringify(t1.rows.map(r => r.p)));
  check('13 each row says its status in words with a shape: "✓ Unchanged", "! Changed since sign-off", "! File missing"; a changed row adds the hint and Re-sign', t1.rows[0].st === '! Changed since sign-off' && t1.rows[1].st === '! File missing' && t1.rows[2].st === '✓ Unchanged' && t1.rows[0].hint && !t1.rows[2].hint && t1.rows[0].btns.join() === 'Re-sign command,Copy remove command' && t1.rows[2].btns.join() === 'Copy remove command', JSON.stringify(t1.rows.slice(0, 3)));
  check('13 row aria-label "{path}, used in {stage}, {status}. {purpose}"; "Add an asset…" and its note', /^docs\/rtl-checklist\.md, used in Test, Changed since sign-off\. Checklist for RTL checks$/.test(t1.rows[0].aria) && t1.add === 'Add an asset…' && /Typed in a terminal\. Fill in the path, stage and purpose, then press Enter\. You confirm there\./.test(t1.note), JSON.stringify([t1.rows[0].aria, t1.add, t1.note]));
  check('13 hostile path and purpose stay text (no element, escaped title)', await S.ev(`(() => { const b = ${sheet('tb-app', 'toolbox')}; return !b.querySelector('img, b b, [onerror]') && [...b.querySelectorAll('.tbp')].some(x => x.textContent.includes('<b>x</b>') && x.title.includes('<b>x</b>')); })()`));
  await clr(); await S.ev(`${sheet('tb-app', 'toolbox')}.querySelectorAll('.tbr')[2].querySelector('[data-tb]').click()`); await wait(80);
  let m = await msgs(); check('13 "Copy remove command" posts {type:"toolbox", op:"remove", project, path} only', m.length === 1 && JSON.stringify(m[0]) === '{"type":"toolbox","op":"remove","project":"tb-app","path":"scripts/seed_menu.py"}', JSON.stringify(m));
  await clr(); await S.ev(`${sheet('tb-app', 'toolbox')}.querySelectorAll('.tbr')[0].querySelector('[data-tb="resign"]').click()`); await wait(80);
  m = await msgs(); check('13 "Re-sign command" posts op resign', m.length === 1 && m[0].op === 'resign' && m[0].path === 'docs/rtl-checklist.md', JSON.stringify(m));
  await clr(); await S.ev(`${sheet('tb-app', 'toolbox')}.querySelector('[data-tb="add"]').click()`); await wait(80);
  m = await msgs(); check('13 "Add an asset…" posts op add with no path', m.length === 1 && JSON.stringify(m[0]) === '{"type":"toolbox","op":"add","project":"tb-app","path":""}', JSON.stringify(m));
  await S.ev(`${sheet('tb-app', 'toolbox')}.querySelector('[data-sheetclose]').click()`); await wait(100);
  check('13 ‹ Back closes the sheet and focus returns to ⋯', await S.ev(`${sheet('tb-app', 'toolbox')}.hidden && document.activeElement === ${card('tb-app')}.querySelector('.btn.more')`));
  await S.ev(`document.querySelectorAll('[data-sheetbox]').forEach(b => b.hidden = true)`);
  await menuOpen('tb-many'); await S.ev(`${card('tb-many')}.querySelector('[data-sheet="toolbox"]').click()`); await wait(100);
  check('13 20 rows are shown and "+5 more"', await S.ev(`${sheet('tb-many', 'toolbox')}.querySelectorAll('.tbr').length`) === 20 && /\+5 more/.test(await S.ev(`${sheet('tb-many', 'toolbox')}.textContent`)));
  await S.ev(`${sheet('tb-many', 'toolbox')}.querySelector('[data-sheetclose]').click()`);
  await menuOpen('tb-empty'); await S.ev(`${card('tb-empty')}.querySelector('[data-sheet="toolbox"]').click()`); await wait(100);
  check('13 empty: "No assets yet. Add scripts, templates or docs you want reused." and Add', /No assets yet\. Add scripts, templates or docs you want reused\./.test(await S.ev(`${sheet('tb-empty', 'toolbox')}.textContent`)) && await S.ev(`!!${sheet('tb-empty', 'toolbox')}.querySelector('[data-tb="add"]')`));
  await S.ev(`${sheet('tb-empty', 'toolbox')}.querySelector('[data-sheetclose]').click()`);
  await menuOpen('tb-busy'); await S.ev(`${card('tb-busy')}.querySelector('[data-sheet="toolbox"]').click()`); await wait(100);
  check('13 while the session is running the command buttons are disabled with "Not now: its session is still running."', await S.ev(`[...${sheet('tb-busy', 'toolbox')}.querySelectorAll('[data-tb]')].every(b => b.disabled && b.title === 'Not now: its session is still running.')`));

  // ---- F6
  await load(DATA());
  for (const [nm, want] of [['old-app', 'short'], ['new-app', 'long']]) {
    await menuOpen(nm); await S.ev(`${card(nm)}.querySelector('[data-sheet="describe"]').click()`); await wait(120);
    const d = await S.ev(`(() => { const b = ${sheet(nm, 'describe')}; return { leg: b.querySelector('legend').textContent, checked: b.querySelector('input:checked').value, opts: [...b.querySelectorAll('.dsopt')].map(o => ({ h: Math.round(o.getBoundingClientRect().height), t: o.textContent.replace(/\\s+/g, ' ').trim() })), tag: b.querySelector('fieldset') ? 'fieldset' : '' }; })()`);
    check(`15 ${nm}: fieldset + legend "Describe your work: ${nm}", "${want}" preselected and marked Suggested, both rows >= 44 px`, d.tag === 'fieldset' && d.leg === `Describe your work: ${nm}` && d.checked === want && d.opts.every(o => o.h >= 44) && d.opts.find(o => /Suggested/.test(o.t)).t.startsWith(want === 'short' ? 'Short' : 'Long') && /about 3 questions, 1-2 minutes/.test(d.opts[0].t) && /about 10 questions in up to 3 rounds, 5-8 minutes/.test(d.opts[1].t) && /Not proven yet; we will measure it\./.test(d.opts[1].t), JSON.stringify(d));
    await clr(); await S.ev(`${sheet(nm, 'describe')}.querySelector('[data-describe="start"]').click()`); await wait(100);
    const mm = await msgs(); check(`15 ${nm}: Start in terminal posts {type:"describe", op:"start", project, mode:"${want}"} and closes the sheet`, mm.length === 1 && JSON.stringify(mm[0]) === JSON.stringify({ type: 'describe', op: 'start', project: nm, mode: want }) && await S.ev(`${sheet(nm, 'describe')}.hidden`), JSON.stringify(mm));
  }
  await menuOpen('new-app'); await S.ev(`${card('new-app')}.querySelector('[data-sheet="describe"]').click()`); await S.ev(`${sheet('new-app', 'describe')}.querySelector('input[value="short"]').click()`); await clr(); await S.ev(`${sheet('new-app', 'describe')}.querySelector('[data-describe="start"]').click()`); await wait(80);
  check('15 the owner can pick the other mode (Short on a new project)', (await msgs())[0].mode === 'short');
  await menuOpen('busy-new'); await S.ev(`${card('busy-new')}.querySelector('[data-sheet="describe"]').click()`); await wait(100);
  check('15 a working project: Start is disabled with "Not now: busy-new is working."', await S.ev(`(() => { const b = ${sheet('busy-new', 'describe')}.querySelector('[data-describe="start"]'); return b.disabled && b.title === 'Not now: busy-new is working.'; })()`));
  const mi = await S.ev(`(() => { const c = ${card('mir-ask')}.querySelector('[data-mirror="asking"]'); const pb = c.querySelector('[role="progressbar"]'); return { head: c.querySelector('.mh1').textContent.replace(/\\s+/g, ' ').trim(), prog: c.querySelector('.mq').textContent, now: pb.getAttribute('aria-valuenow'), max: pb.getAttribute('aria-valuemax'), q: c.querySelector('.mqt').textContent, live: !!c.querySelector('[aria-live="polite"] .mqt'), btns: [...c.querySelectorAll('button')].map(b => b.textContent), keys: c.textContent.includes('Enter = Accept · type = Edit · s = Skip rest'), as: [...c.querySelectorAll('.mas li')].map(l => l.textContent.trim()) }; })()`);
  check('15 mirror: "Question 3 of about 8" with a progressbar (text first), the question, Recommended text, the key hints as text, the only button is Show terminal, Assumed so far (2)', mi.head.startsWith('Describe your work · mir-ask') && mi.head.endsWith('Short') && mi.prog === 'Question 3 of about 8' && mi.now === '3' && mi.max === '8' && mi.q === 'Who approves a finished recipe page?' && mi.live && mi.btns.join() === 'Show terminal' && mi.keys && mi.as.join('|') === '~ Output is a web page|~ Tests run with npm test', JSON.stringify(mi));
  await clr(); await S.ev(`${card('mir-ask')}.querySelector('[data-describe="show"]').click()`); await wait(80);
  check('15 Show terminal posts {type:"describe", op:"show", project}', JSON.stringify((await msgs())[0]) === '{"type":"describe","op":"show","project":"mir-ask"}');
  check('15 the mirror never offers Accept / Edit / Skip as buttons', await S.ev(`![...${card('mir-ask')}.querySelectorAll('.mirror button')].some(b => /Accept|Edit|Skip/.test(b.textContent))`));
  const pa = await S.ev(`(() => { const c = ${card('mir-pause')}.querySelector('[data-mirror="paused"]'); return [c.querySelector('.mq').textContent, [...c.querySelectorAll('button')].map(b => b.textContent)]; })()`);
  check('17 paused: "Interview paused at question 4 of about 8" with Resume and Start over', pa[0] === 'Interview paused at question 4 of about 8' && pa[1].join() === 'Resume,Start over', JSON.stringify(pa));
  await clr(); await S.ev(`${card('mir-pause')}.querySelector('[data-describe="resume"]').click()`); await wait(80);
  check('17 Resume posts op resume', JSON.stringify((await msgs())[0]) === '{"type":"describe","op":"resume","project":"mir-pause"}');
  await clr(); await S.ev(`${card('mir-pause')}.querySelector('[data-describe="restart"]').click()`); await wait(80);
  check('17 Start over asks "Sure?" in place first and posts nothing', (await msgs()).length === 0 && await S.ev(`${card('mir-pause')}.querySelector('[data-describe="restart"]').textContent`) === 'Sure?');
  await S.ev(`${card('mir-pause')}.querySelector('[data-describe="restart"]').click()`); await wait(80);
  check('17 the second press posts op restart', JSON.stringify((await msgs())[0]) === '{"type":"describe","op":"restart","project":"mir-pause"}');
  const dr = await S.ev(`(() => { const c = ${card('mir-draft')}.querySelector('[data-mirror="draft"]'); return { h: c.querySelector('.mq').textContent, rows: [...c.querySelectorAll('dt')].map(d => d.textContent), btns: [...c.querySelectorAll('button')].map(b => b.textContent), note: c.querySelector('.nhint').textContent, b: !!c.querySelector('dd b, img'), w: c.querySelector('dd').textContent.length }; })()`);
  check('16 draft view: "Draft playbook: read it, then run the command", nine labelled rows, Open draft + Copy set command, the "Nothing is trusted yet" note, markup stays text', dr.h === 'Draft playbook: read it, then run the command' && dr.rows.join('|') === 'Work|Inputs|Outputs|Tools|Risks|Who approves|Definition of done|Never allowed|Assumed' && dr.btns.join() === 'Open draft,Copy set command' && dr.note === 'Nothing is trusted yet. The draft only counts after you run the command and confirm.' && !dr.b, JSON.stringify(dr));
  await clr(); await S.ev(`${card('mir-draft')}.querySelector('[data-describe="open"]').click(); ${card('mir-draft')}.querySelector('[data-describe="set"]').click()`); await wait(80);
  check('16 Open draft and Copy set command post ops open and set (the extension types the command, no Enter)', (await msgs()).map(x => x.op).join() === 'open,set');
  check('16 a draft that cannot be read: "The draft could not be read. Open it or start over."; an interview that failed: "The interview did not finish. Start again."', await S.ev(`${card('mir-bad')}.querySelector('.mirror').textContent`).then(t => t.includes('The draft could not be read. Open it or start over.')) && await S.ev(`${card('mir-err')}.querySelector('.mirror').textContent`).then(t => t.includes('The interview did not finish. Start again.')));
  check('15 hostile question / assumed text stays text', await S.ev(`(() => { const c = ${card('mir-host')}; return !c.querySelector('.mirror img, .mirror script, .mqt b, .mirror p b, .mirror li b, [onerror]') && c.querySelector('.mqt').textContent.startsWith('<img src=x'); })()`));

  // widths, scroll, contrast, targets
  for (const [label, theme] of [['Dark+', 'dark'], ['Light+', 'light'], ['High Contrast', 'hc']]) for (const w of [280, 315, 360]) {
    await load(DATA(), theme, w, D.THEMES[theme]);
    await S.ev(`document.querySelectorAll('.card').forEach(c => { const b = c.querySelector('.btn.more'); })`);
    await menuOpen('tb-app'); await S.ev(`${card('tb-app')}.querySelector('[data-sheet="toolbox"]').click()`); await wait(120);
    const tx = await S.ev(D.TEXT_IN('.mirror *, [data-sheetbox="toolbox"]:not([hidden]) *')), bad = tx.filter(x => x.ratio < 4.5);
    const tg = await S.ev(`[...document.querySelectorAll('.mirror button, [data-sheetbox]:not([hidden]) button')].filter(b => b.getClientRects().length).map(b => Math.round(b.getBoundingClientRect().height)).filter(h => h < 22)`);
    const hs = await S.ev(`document.documentElement.scrollWidth <= document.documentElement.clientWidth && document.getElementById('scroll').scrollWidth <= document.getElementById('scroll').clientWidth`);
    check(`[${label} ${w}] mirror and Toolbox text >= 4.5:1 (${tx.length} elements), targets >= 22 px, no horizontal scroll`, tx.length > 10 && bad.length === 0 && tg.length === 0 && hs, JSON.stringify({ bad: bad.slice(0, 4), tg, hs }));
  }
  S.close();
  console.log(C.fails ? `\nFAILED: ${C.fails} of ${C.n}` : `\nALL PASS (${C.n})`); process.exit(C.fails ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
