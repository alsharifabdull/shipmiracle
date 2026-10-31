// Host notices in the panel (task E10; parity P-1000..P-1003) in real headless Chrome: the Windows message (Setup tab and Projects empty state), the Remote-WSL "experimental" note (only when the CLI says
// so), the Health tab's "chat health: unknown" line, and a macOS page with none of them. 280 / 315 / 360 wide, Dark+ / Light+ / High Contrast: text >= 4.5:1 against the panel's own tokens, targets >= 22 px,
// no horizontal scroll, hostile text stays text, every state-changing control still only posts a message. Screenshots only with SHIPMIRACLE_SHOTS=1 (tests/fixtures/panel-v3-host).
// Run: node tests/panel_v3_host_test.js    (skips without Chrome)
require('./shipmiracle_isolation').apply();
const fs = require('fs'), path = require('path');
const D = require('./panel_cdp');
if (!D.H.available()) { console.log('SKIP no Chrome'); process.exit(0); }
const F3 = require('./panel_v3_tab_fixtures');
const HX = require('../vscode-ext/shipmiracle-panel/hostx.js');
const C = D.checker(), check = C.check;
const SHOTS = path.join(__dirname, 'fixtures', 'panel-v3-host'), WRITE = process.env.SHIPMIRACLE_SHOTS === '1';
if (WRITE) fs.mkdirSync(SHOTS, { recursive: true });
const CLI_WIN = 'This computer: Windows 11 (native). Shipmiracle runs inside WSL2 here: run "wsl --install", open Ubuntu, then install Shipmiracle there. Nothing was changed.';
const rows = () => F3.ROWS().map(r => ({ ...r, stage: r.need === 'required' || r.need === 'recommended' ? 'connect' : 'advanced', class: r.need, os_supported: true, docs: '' }));
const SETUP = (os, quick = true) => ({ rows: rows(), ready: false, error: false, at: 'now', os, quick });
const HOSTS = {
  win: HX.hostOf({ platform: 'win32' }), wsl: HX.hostOf({ platform: 'linux', remoteName: 'wsl' }), linux: HX.hostOf({ platform: 'linux' }), mac: HX.hostOf({ platform: 'darwin' })
};
const OSL = { wsl: { kind: 'wsl', line: 'This computer: Ubuntu 24.04 on Windows (WSL 2) (x86_64). Supported: CLI, hooks, panel, autopilot. Not here: awake guard, iOS tools.', level: 'experimental' },
  wslplain: { kind: 'wsl', line: 'This computer: Ubuntu 24.04 on Windows (WSL 2) (x86_64). Supported: CLI, hooks, panel, autopilot.', level: '' },
  mac: { kind: 'macos', line: 'This computer: macOS 27.0 (arm64). Supported: everything.', level: 'experimental' } };
const DATA = (o = {}) => ({ projects: [], plan: { meters: [] }, remote: { state: 'off' }, ...o });
const SCEN = {
  'win-setup': { tab: 'setup', data: DATA({ host: HOSTS.win, setup: { rows: [], ready: false, error: true, at: 'now', os: null, quick: false } }) },
  'win-setup-cli': { tab: 'setup', data: DATA({ host: HOSTS.win, setup: SETUP({ kind: 'windows', line: CLI_WIN }, false) }) },
  'win-projects': { tab: 'projects', data: DATA({ host: HOSTS.win }) },
  'wsl-setup': { tab: 'setup', data: DATA({ host: HOSTS.wsl, setup: SETUP(OSL.wsl) }) },
  'unknown-health': { tab: 'health', data: DATA({ host: HOSTS.linux }) }
};

(async () => {
  const S = await D.session({ size: '345,900' }); const load0 = S.load; S.load = async (...a) => { try { await S.sleep(260); await S.ev(`sessionStorage.clear()`); } catch (e) { /* first load */ } return load0(...a); };
  const msgs = () => S.ev('JSON.stringify(window.__msgs)').then(JSON.parse).then(a => a.filter(x => x.type !== 'editing'));
  const load = async (data, tab, theme = 'dark', w = 315) => { await S.load(S.file('hx-' + theme + w, D.page(theme, data, D.THEMES[theme])), w, '?tab=' + tab, 9000); };
  const q = sel => S.ev(`(() => { const n = document.querySelector(${JSON.stringify(sel)}); return n ? n.textContent.replace(/\\s+/g, ' ').trim() : null; })()`);

  // ---- Windows
  await load(SCEN['win-setup'].data, 'setup');
  let t = await q('#pane-setup [data-host=windows]');
  check('Windows, CLI silent (the check failed): the Setup tab shows "not supported yet", "WSL 2" and the fallback install hint', t && /Windows is not supported yet/.test(t) && /WSL 2/.test(t) && t.includes(HX.FALLBACK_HINT), t);
  check('Windows: no red error row, no "Could not read setup state", no Quick setup card (nothing to set up here); NO Re-check button (it cannot work on native Windows)', await S.ev(`(() => { const p = document.querySelector('#pane-setup'); return !p.querySelector('.chk.red, .qs, .qn') && !p.querySelector('[data-setup=recheck]') && !/Could not read/.test(p.textContent); })()`));
  await load(SCEN['win-setup-cli'].data, 'setup');
  t = await q('#pane-setup [data-host=windows]');
  check('Windows with an answering CLI: the hint is the CLI\'s own os.line, not the fallback', t && t.includes('runs inside WSL2 here') && !t.includes(HX.FALLBACK_HINT), t);
  await load(SCEN['win-projects'].data, 'projects');
  t = await q('#pane-projects [data-host=windows]');
  check('Windows: the Projects empty state shows the same message instead of "No projects yet. Use + to create one."', t && /not supported yet/.test(t) && !/No projects yet/.test(await q('#pane-projects')));
  // ---- WSL
  await load(SCEN['wsl-setup'].data, 'setup');
  t = await q('#pane-setup [data-host=experimental]');
  check('Remote-WSL, CLI says level "experimental": the Setup tab shows "Linux and WSL 2 support is experimental", above the OS line', t && /experimental/.test(t) && await S.ev(`!!(document.querySelector('[data-host=experimental]').compareDocumentPosition(document.querySelector('.osl')) & 4)`), t);
  await load(DATA({ host: HOSTS.wsl, setup: SETUP(OSL.wslplain) }), 'setup');
  check('Remote-WSL, CLI sends no level: NO experimental note (the panel decides nothing itself)', (await q('[data-host=experimental]')) === null && /Ubuntu 24.04/.test(await q('.osl')));
  await load(DATA({ host: HOSTS.mac, setup: SETUP(OSL.mac) }), 'setup');
  check('macOS: no host notice anywhere on the Setup tab', (await q('[data-host]')) === null);
  // ---- Health unknown
  await load(SCEN['unknown-health'].data, 'health');
  t = await q('#pane-health [data-host=chat-unknown]');
  check('Linux: the Health tab says "Chat health: unknown on this computer" and that nothing is closed by itself', t && /unknown/.test(t) && /never closes or relaunches/.test(t), t);
  await load(DATA({ host: HOSTS.mac }), 'health');
  check('macOS: no chat-health line', (await q('[data-host]')) === null);
  // ---- off-macOS wording (QA minors): the Awake guard row, '+ New project' / 'Check & update' on native Windows, neutral tooltips
  const DG = { on: true, running: false, hold: false, lpm: false };
  const has = sel => S.ev(`!!document.querySelector(${JSON.stringify(sel)})`);
  await load(DATA({ host: HOSTS.linux, guard: DG, health: null }), 'projects');
  check('Linux: no "Awake guard" header row in the plan block', !(await has('.grow [data-guard]')) && !/Awake guard/.test(await q('.plan')));
  await load(DATA({ host: HOSTS.linux, guard: DG }), 'health');
  check('Linux: the Health empty state says "No scan yet." and does NOT claim the Awake guard runs the check', /No scan yet\./.test(await q('#pane-health .iempty')) && !/Awake guard/.test(await q('#pane-health')));
  await load(DATA({ host: HOSTS.wsl, guard: DG }), 'projects');
  check('WSL: no Awake guard row either', !(await has('[data-guard]')));
  await load(DATA({ host: HOSTS.mac, guard: DG }), 'projects');
  check('macOS: the Awake guard row (with its switch) is still there', await has('.grow [data-guard]') && /Awake guard/.test(await q('.plan')));
  await load(DATA({ host: HOSTS.mac }), 'health');
  check('macOS: the Health empty state still names the Awake guard', /Awake guard runs the health check every minute/.test(await q('#pane-health .iempty')));
  await load(DATA({ host: HOSTS.win, guard: DG }), 'projects');
  check('native Windows: no "+ New project", no "Check & update", no new-project box', !(await has('[data-toggle=newbox], [data-cmd=check], [data-newbox]')));
  await load(DATA({ host: HOSTS.linux }), 'projects');
  check('Linux: "+ New project" and "Check & update" are still there (they work on Linux)', await has('[data-toggle=newbox]') && await has('[data-cmd=check]'));
  await load(DATA({ host: HOSTS.mac }), 'projects');
  check('macOS: "+ New project" and "Check & update" are there', await has('[data-toggle=newbox]') && await has('[data-cmd=check]'));
  await load(DATA({ host: HOSTS.linux, guard: DG, health: F3.HEALTH() }), 'health');
  check('Linux: with a scan, the Automatic cleanup note and the load-line tooltip do not name the Awake guard or "this Mac"', await S.ev(`(() => { const t = document.querySelector('#pane-health .hclean .hwhy').textContent + ' ' + (document.querySelector('.grow.mac') || {}).title + ' ' + document.querySelector('.grow.mac').textContent; return !/Awake guard|this Mac|Mac ·/.test(t) && /This computer/.test(t) && /Only proven leftovers/.test(t); })()`));
  await load(DATA({ host: HOSTS.mac, guard: DG, health: F3.HEALTH() }), 'health');
  check('macOS: with a scan, the cleanup note, "Mac ·" and the tooltip keep the Mac wording', await S.ev(`(() => { const t = document.querySelector('#pane-health .hclean .hwhy').textContent + ' ' + document.querySelector('.grow.mac').title + ' ' + document.querySelector('.grow.mac').textContent; return /Runs with the Awake guard every minute/.test(t) && /this Mac/.test(t) && /Mac ·/.test(t); })()`));
  await load(DATA({ host: HOSTS.linux, guard: DG, health: Object.assign(F3.HEALTH(), { ageS: 900 }) }), 'health');
  check('Linux: a stale scan says "Last scan ... ago" and does NOT name the Awake guard', await S.ev(`(() => { const t = document.querySelector('#pane-health .inote').textContent; return /Last scan .* ago\\.$/.test(t) && !/Awake guard/.test(t); })()`));
  await load(DATA({ host: HOSTS.mac, guard: DG, health: Object.assign(F3.HEALTH(), { ageS: 900 }) }), 'health');
  check('macOS: a stale scan still says the Awake guard may be off', await S.ev(`/Last scan .* ago: the Awake guard may be off\\./.test(document.querySelector('#pane-health .inote').textContent)`));
  // text hygiene (unit): bidi / zero-width characters never reach the hint or the setup rows
  const U = h => String.fromCharCode(parseInt(h, 16)), BIDI = U('202e') + U('2066') + U('200f') + U('061c') + U('200b') + U('feff');
  check('hintOf: bidi and zero-width characters removed from the CLI line', HX.hintOf({ kind: 'windows', line: 'Run ' + BIDI + 'wsl --install' + U('2028') + ' now' }) === 'Run wsl --install now', HX.hintOf({ kind: 'windows', line: 'Run ' + BIDI + 'wsl' }));
  const SU = require('../vscode-ext/shipmiracle-panel/setup.js');
  const pr = SU.parseCheck(JSON.stringify({ v: 1, rows: [{ n: 1, id: 'git', title: 'G' + BIDI + 'it', need: 'required', state: 'red', detail: 'Install ' + BIDI + 'git', connect: { kind: 'hint', text: 'brew' + BIDI + ' install git' } }] }));
  check('setup rows: bidi and zero-width characters removed from title, detail and connect text', pr.ok && pr.rows[0].title === 'Git' && pr.rows[0].detail === 'Install git' && pr.rows[0].connect.text === 'brew install git', JSON.stringify(pr.rows && pr.rows[0]));
  check('experimental note: not shown when the host platform is macOS, even if the CLI says wsl + experimental', HX.notice({ ...HOSTS.mac, kind: 'wsl' }, { kind: 'wsl', level: 'experimental' }, { t: k => k, esc: x => x }, 'setup') === '' && /experimental/.test(HX.notice(HOSTS.wsl, { kind: 'wsl', level: 'experimental' }, { t: k => k, esc: x => x }, 'setup')));
  // ---- hostile text and safety
  const hostile = '<img src=x onerror=alert(1)> ' + CLI_WIN + ' <script>alert(2)</script>';
  await load(DATA({ host: HOSTS.win, setup: SETUP({ kind: 'windows', line: hostile }, false) }), 'setup');
  check('hostile CLI text in the Windows notice stays text: no element, no handler', await S.ev(`(() => { const n = document.querySelector('[data-host=windows]'); return !n.querySelector('img, script, [onerror]') && n.textContent.includes('<img'); })()`));
  await S.ev('window.__msgs.length = 0');
  await S.ev(`document.querySelectorAll('#pane-setup [data-host] *').forEach(n => n.click())`); await S.sleep(80);
  check('the notice has no button or link: clicking it posts nothing, and the page has no action control besides Re-check', (await msgs()).length === 0 && await S.ev(`document.querySelectorAll('[data-host] button, [data-host] a, [data-host] input').length === 0`));

  // ---- contrast, targets, scroll, screenshots at the three widths in the three themes
  for (const [label, theme] of [['Dark+', 'dark'], ['Light+', 'light'], ['High Contrast', 'hc']]) for (const w of [280, 315, 360]) for (const [name, sc] of Object.entries(SCEN)) {
    await load(sc.data, sc.tab, theme, w); await S.sleep(100);
    const sel = '#pane-' + sc.tab;
    const tx = await S.ev(D.TEXT_IN(`${sel} *`)), bad = tx.filter(x => x.ratio < 4.5);
    const tg = await S.ev(`[...document.querySelectorAll('${sel} button')].filter(b => b.getClientRects().length).map(b => Math.round(b.getBoundingClientRect().height)).filter(h => h < 22)`);
    const fit = await S.ev(`document.documentElement.scrollWidth <= document.documentElement.clientWidth && document.getElementById('scroll').scrollWidth <= document.getElementById('scroll').clientWidth`);
    const vis = await S.ev(`(() => { const n = document.querySelector('${sel} [data-host]'); return !!n && n.getClientRects().length > 0 && n.getBoundingClientRect().width > 100; })()`);
    check(`[${label} ${w}] ${name}: notice visible, text >= 4.5:1 (${tx.length} elements), targets >= 22 px, no horizontal scroll`, vis && tx.length >= 2 && bad.length === 0 && tg.length === 0 && fit, JSON.stringify({ vis, bad: bad.slice(0, 5), tg, fit }));
    if (WRITE) { await S.ev(`document.getElementById('scroll').scrollTop = 0`); const h = await S.ev(`Math.min(900, document.getElementById('scroll').scrollHeight + 120)`); fs.writeFileSync(path.join(SHOTS, `${name}-${theme}-${w}.png`), await S.shot({ x: 0, y: 0, width: w, height: h }, 2)); }
  }
  S.close();
  console.log(C.fails ? `\nFAILED: ${C.fails} of ${C.n}` : `\nALL PASS (${C.n})`); process.exit(C.fails ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
