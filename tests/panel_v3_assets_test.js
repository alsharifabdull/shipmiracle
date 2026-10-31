// Proposed assets (F5, Learn stage) in the project card: path and why as PLAIN text, the exact `shipm playbook asset add ...` command as copy-only text with a Copy button, NO control that runs it,
// hidden when there are none or the CLI has no toolbox. Unit part (proposed.js: strict command shape, hostile rows) always runs; the browser part (0 / 1 / 3 rows, 280 / 315 / 360, Dark+ / Light+ /
// High Contrast, text >= 4.5:1) skips without Chrome. Screenshots only with SHIPMIRACLE_SHOTS=1 (tests/fixtures/panel-v3-assets). Parity P-1300..P-1306.
// Run: node tests/panel_v3_assets_test.js
require('./shipmiracle_isolation').apply();
const fs = require('fs'), path = require('path');
const PR = require('../vscode-ext/shipmiracle-panel/proposed.js');
const D = require('./panel_cdp');
const C = D.checker(), check = C.check;
const U = h => String.fromCharCode(parseInt(h, 16)), BIDI = U('202e') + U('2066') + U('200f') + U('061c') + U('200b') + U('feff');
const row = (p, why, stage = 'do') => ({ path: p, why, stage, cr: 'CR-001' });
const GOOD = [row('scripts/seed_menu.py', 'new script, 3 KB, in scripts'), row('docs/rtl-checklist.md', 'changed document, 2 KB, in docs', 'verify'), row('templates/page.html', 'new template, 1 KB, in templates', 'plan')];
const HOSTILE_WHY = '<img src=x onerror=alert(1)> `rm -rf ~` $(whoami) \'quote\' "dq" ' + BIDI + 'end ' + 'w'.repeat(10000);

// ---- unit: proposed.js
{
  const c = PR.clean(GOOD, 'my-app');
  check('P-1300 three rows -> three rows with the exact add command (engine shape, quoted purpose, --project)', c.length === 3 && c[0].command === "shipm playbook asset add scripts/seed_menu.py --stage do --purpose 'new script, 3 KB, in scripts' --project my-app", JSON.stringify(c[0]));
  check('P-1300 every command matches the strict shape', c.every(r => PR.CMD.test(r.command)));
  check('P-1300 at most 3 rows, 0 / 1 rows kept as they are, non-arrays give []', PR.clean(GOOD.concat(GOOD), 'a').length === 3 && PR.clean([GOOD[0]], 'a').length === 1 && PR.clean([], 'a').length === 0 && PR.clean(null, 'a').length === 0 && PR.clean('x', 'a').length === 0);
  const h = PR.clean([row('scripts/a.py', HOSTILE_WHY)], 'my-app')[0];
  check('P-1301 hostile why: text only, bidi / zero-width gone, capped (10k in -> <= 161 out)', h.why.length <= 161 && !/[‮⁦‏؜​﻿]/.test(h.why), h.why.length);
  check('P-1301 hostile why: the command has no backtick, angle bracket, $, quote or backslash inside the purpose, one line', PR.CMD.test(h.command) && !/[`<>$"\\\n]/.test(h.command.replace(/^shipm playbook asset add \S+ --stage \w+ --purpose '|'( --project \S+)?$/g, '')), h.command);
  check('P-1301 a forged `command` in the data is ignored (rebuilt, never taken)', PR.clean([{ ...GOOD[0], command: 'rm -rf / ; shipm playbook asset add x' }], 'a')[0].command.startsWith('shipm playbook asset add scripts/seed_menu.py '));
  for (const [label, p] of [['html', '<img src=x onerror=1>.py'], ['spaces', 'my dir/a b.py'], ['semicolon', 'a;rm -rf x.py'], ['dotdot', 'scripts/../../etc/x.py'], ['leading dash', '-rf/x.py'], ['bidi', 'scripts/' + BIDI + 'a.py'], ['backtick', 'scripts/`id`.py'], ['10k path', 'scripts/' + 'a'.repeat(10000) + '.py'], ['absolute', '/etc/passwd']]) {
    const r = PR.clean([row(p, 'why')], 'a'); check(`P-1301 hostile path (${label}): shown as text at most, never a command`, r.length <= 1 && (!r.length || (r[0].command === '' && r[0].path.length <= 201)), JSON.stringify(r));
  }
  check('P-1301 a path that cleaning changed (bidi) gets no command, also after a second pass (data.js then sane.js)', PR.clean(PR.clean([row('scripts/' + BIDI + 'b.py', 'w')], 'a'), 'a')[0].command === '');
  check('P-1303 valid rows behind junk rows are kept (clean first, then at most 3): 3 junk + 2 good -> 2 rows', PR.clean([null, 5, { path: '' }, GOOD[0], GOOD[1]], 'a').length === 2);
  check('P-1303 data.js does not cut the CLI rows to 3 before cleaning', !/proposed_assets\.slice\(0, 3\)/.test(fs.readFileSync(path.join(__dirname, '..', 'vscode-ext', 'shipmiracle-panel', 'data.js'), 'utf8')));
  check('P-1301 unknown stage / bad project name: no command', PR.clean([row('a/b.py', 'w', 'bogus')], 'a')[0].command === '' && !PR.clean([row('a/b.py', 'w')], '--x')[0].command.includes('--project'));
}
// ---- source: nothing runs the command; the panel stays small
{
  const dir = path.join(__dirname, '..', 'vscode-ext', 'shipmiracle-panel'), size = fs.statSync(path.join(dir, 'panel.js')).size;
  check('P-1306 panel.js stays under 200 KB (' + size + ' bytes)', size < 200000);
  const ext = fs.readFileSync(path.join(dir, 'extension.js'), 'utf8'), fn = ext.slice(ext.indexOf('async function proposedAction'), ext.indexOf('function toolboxAction'));
  check('P-1302 the extension side of the proposed assets only copies to the clipboard: no terminal, no exec, no sendText', fn.includes('clipboard.writeText') && !/sendText|createTerminal|execFile|spawn|ownerTerminal|runScript/.test(fn), fn.length);
}
if (!D.H.available()) { console.log(C.fails ? `\nFAILED: ${C.fails} of ${C.n}` : `\nALL PASS (${C.n}) (browser part skipped: no Chrome)`); process.exit(C.fails ? 1 : 0); }

const F = require('./panel_v3_fixtures');
const SHOTS = path.join(__dirname, 'fixtures', 'panel-v3-assets'), WRITE = process.env.SHIPMIRACLE_SHOTS === '1';
if (WRITE) fs.mkdirSync(SHOTS, { recursive: true });
const mkp = (name, rows, o = {}) => F.mk(name, 'software', { proposed: PR.clean(rows, name), ...o });
const proj = () => [
  mkp('pa-three', GOOD), mkp('pa-one', [GOOD[0]]), mkp('pa-none', []),
  mkp('pa-hostile', [row('scripts/<img src=x onerror=alert(1)>.py', HOSTILE_WHY), row('scripts/' + BIDI + 'b.py', '<script>alert(2)</script> `x`', 'verify'), row('scripts/ok.py', 'plain')]),
  { ...F.mk('pa-nopb', 'software', {}), playbook: null, cr: null, stageLabels: null, proposed: PR.clean(GOOD, 'pa-nopb') }
];
const DATA = (o = {}) => ({ projects: proj(), capabilities: { toolbox: true, interview: false, aside: false }, plan: { meters: [] }, ...o });
const card = nm => `[...document.querySelectorAll('.card')].find(c => c.querySelector('.name').textContent === ${JSON.stringify(nm)})`;

// Fail fast instead of hanging: a hostile payload that escaped (an alert() dialog) would block the page for ever, so alert is recorded, not shown, and a watchdog ends the run.
const WATCHDOG = setTimeout(() => { console.log('FAIL watchdog: the browser part did not finish in 240 s (a blocked page?)'); process.exit(1); }, 240000); WATCHDOG.unref();
(async () => {
  const S = await D.session({ size: '345,900' }); await S.cdp('Page.addScriptToEvaluateOnNewDocument', { source: 'window.__alerts = 0; window.alert = () => { window.__alerts++; };' }); const load0 = S.load; S.load = async (...a) => { try { await S.sleep(260); await S.ev(`sessionStorage.clear()`); } catch (e) { /* first load */ } return load0(...a); };
  const msgs = () => S.ev('JSON.stringify(window.__msgs)').then(JSON.parse).then(a => a.filter(x => x.type !== 'editing'));
  const load = async (data, theme = 'dark', w = 315) => { await S.load(S.file('pa-' + theme + w, D.page(theme, data, D.THEMES[theme])), w, '?tab=projects', 12000); };
  const txt = (nm, sel) => S.ev(`(() => { const n = ${card(nm)}.querySelector(${JSON.stringify(sel)}); return n ? n.textContent.replace(/\\s+/g, ' ').trim() : null; })()`);

  await load(DATA());
  check('P-1303 0 rows: no section at all', await S.ev(`!${card('pa-none')}.querySelector('.prop')`));
  check('P-1303 no playbook on the card: no section', await S.ev(`!${card('pa-nopb')}.querySelector('.prop')`));
  let t = await txt('pa-one', '.prop');
  check('P-1303 1 row: heading "Proposed assets (1)", the path, the why, the command text, one Copy button', /Proposed assets \(1\)/.test(t) && t.includes('scripts/seed_menu.py') && t.includes('new script, 3 KB, in scripts') && t.includes("shipm playbook asset add scripts/seed_menu.py --stage do --purpose 'new script, 3 KB, in scripts' --project pa-one")
    && await S.ev(`${card('pa-one')}.querySelectorAll('.prop button').length === 1`), t);
  check('P-1303 3 rows: three items, three Copy buttons, plain-word note that the owner runs it', await S.ev(`${card('pa-three')}.querySelectorAll('.prop .prr').length === 3 && ${card('pa-three')}.querySelectorAll('.prop button').length === 3`) && /yourself in a terminal/.test(await txt('pa-three', '.prop .nhint')));
  check('P-1302 the section has NO control that runs anything: only "Copy add command" buttons, no link, no input, no data-tb / data-act', await S.ev(`(() => { const p = ${card('pa-three')}.querySelector('.prop'); return [...p.querySelectorAll('button')].every(b => b.hasAttribute('data-pacopy') && b.textContent.trim() === 'Copy add command') && !p.querySelector('a, input, select, textarea, [data-tb], [data-act], [data-primary], [data-cmd]'); })()`));
  await S.ev('window.__msgs.length = 0'); await S.ev(`${card('pa-three')}.querySelectorAll('.prop [data-pacopy]')[1].click()`); await S.sleep(80);
  let m = await msgs(); check('P-1302 Copy posts exactly {type:"proposed", op:"copy", project, i}', m.length === 1 && JSON.stringify(m[0]) === '{"type":"proposed","op":"copy","project":"pa-three","i":1}', JSON.stringify(m));
  await S.ev('window.__msgs.length = 0'); await S.ev(`${card('pa-three')}.querySelectorAll('.prop .pcmd, .prop .pap, .prop .prw').forEach(n => n.click())`); await S.sleep(80);
  check('P-1302 clicking the command or the texts posts nothing besides the usual card open (no run)', (await msgs()).every(x => x.type !== 'proposed' && x.type !== 'toolbox' && x.type !== 'run'));
  check('P-1301 hostile card: no element made from the text, handlers or scripts; the angle brackets are visible text', await S.ev(`(() => { const p = ${card('pa-hostile')}.querySelector('.prop'); return window.__alerts === 0 && !p.querySelector('img, script, [onerror]') && p.textContent.includes('<img') && p.textContent.includes('<script>'); })()`));
  const hc = await S.ev(`(() => { const r = [...${card('pa-hostile')}.querySelectorAll('.prop .prr')]; return JSON.stringify([r.length, r.filter(x => x.querySelector('.pcmd')).length, r.filter(x => x.querySelector('button')).length]); })()`);
  check('P-1301 hostile card: shows at most 3 rows; the unsafe-path rows have no command and no Copy, the safe one has both', hc === '[3,1,1]', hc);
  check('P-1301 hostile card: a 10,000-character why is cut (the section text stays short)', (await txt('pa-hostile', '.prop')).length < 900);
  await load(DATA({ capabilities: { toolbox: false } }));
  check('P-1303 the CLI has no toolbox: no section', await S.ev(`!document.querySelector('.prop')`));
  await load(DATA({ projects: proj().map(p => ({ ...p, proposed: undefined })) }));
  check('P-1303 an older CLI (no proposed field): no section, no error', await S.ev(`!document.querySelector('.prop') && document.querySelectorAll('.card').length === 5`));
  await load(DATA()); await S.ev(`document.documentElement.dir = 'rtl'`);
  check('P-1305 RTL page: the command stays left-to-right, the path follows the text (dir=auto)', await S.ev(`(() => { const p = ${card('pa-one')}.querySelector('.prop'); return p.querySelector('.pcmd').getAttribute('dir') === 'ltr' && p.querySelector('.pap').getAttribute('dir') === 'auto'; })()`));

  // ---- contrast, targets, scroll, screenshots at the three widths in the three themes
  for (const [label, theme] of [['Dark+', 'dark'], ['Light+', 'light'], ['High Contrast', 'hc']]) for (const w of [280, 315, 360]) {
    await load(DATA(), theme, w); await S.sleep(100);
    const tx = await S.ev(D.TEXT_IN('.prop *')), bad = tx.filter(x => x.ratio < 4.5);
    const tg = await S.ev(`[...document.querySelectorAll('.prop button')].filter(b => b.getClientRects().length).map(b => Math.round(b.getBoundingClientRect().height)).filter(h => h < 22)`);
    const fit = await S.ev(`document.documentElement.scrollWidth <= document.documentElement.clientWidth && document.getElementById('scroll').scrollWidth <= document.getElementById('scroll').clientWidth && [...document.querySelectorAll('.prop *')].every(n => n.getBoundingClientRect().right <= document.documentElement.clientWidth + 1)`);
    check(`P-1304 [${label} ${w}] proposed assets: text >= 4.5:1 (${tx.length} elements), targets >= 22 px, nothing cut off the right edge, no horizontal scroll`, tx.length > 15 && bad.length === 0 && tg.length === 0 && fit, JSON.stringify({ bad: bad.slice(0, 5), tg, fit }));
    if (WRITE) for (const nm of ['pa-three', 'pa-hostile']) {
      await S.ev(`${card(nm)}.scrollIntoView({ block: 'start' })`); await S.sleep(60);
      const r = JSON.parse(await S.ev(`JSON.stringify((() => { const b = ${card(nm)}.getBoundingClientRect(); return { x: 0, y: Math.max(0, b.top + window.scrollY), width: document.documentElement.clientWidth, height: Math.ceil(b.height) + 8 }; })())`));
      fs.writeFileSync(path.join(SHOTS, `${nm.replace('pa-', '')}-${theme}-${w}.png`), await S.shot(r, 2));
    }
  }
  S.close();
  console.log(C.fails ? `\nFAILED: ${C.fails} of ${C.n}` : `\nALL PASS (${C.n})`); process.exit(C.fails ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
