// Panel v3 spec section 12 item 2, the real one: GOLDEN SNAPSHOT AGAINST LIVE DATA.
// A project set is built with the real engine APIs (tests/panel_live_fixture.py: open CRs in scope / plan / approve / build / test-FAIL / test-BLOCKED / review / deliver,
// a delivered CR, queued-only, a running and a paused full-autopilot project, no playbook, stage reports + a CR report in the reports index, the registered ask inbox project)
// inside a throw-away world (fresh HOME / config / state / workspace / projects folders). Then:
//   1. the real `shipm report panel --project <dir>` runs for every project (the CLI is the contract);
//   2. data.js collect() (which runs the same CLI) must hand the panel exactly those fields;
//   3. the panel page is rendered from collect()'s data in headless Chrome and a DOM-to-JSON dump of every card is deep-compared with values derived from the CLI JSON by an
//      INDEPENDENT rule table (state, primary, stage, CR, verdict, autopilot level, chips);
//   4. Reports rows = the real index file; the Ask card = the CLI ask block; Setup rows = the real `shipm init --check --json` (read-only).
// Run: node tests/panel_v3_golden_test.js     (skips without Chrome)
require('./shipmiracle_isolation').apply();
const fs = require('fs'), path = require('path');
const W = require('./panel_live_world');
const D = require('./panel_cdp');
if (!D.H.available()) { console.log('SKIP no Chrome'); process.exit(0); }
const C = D.checker(); const check = C.check;
const world = W.make('golden'); W.enter(world);
const STRINGS = require('../vscode-ext/shipmiracle-panel/strings.js'), DATA = require('../vscode-ext/shipmiracle-panel/data.js'), SETUP = require('../vscode-ext/shipmiracle-panel/setup.js');

(async () => {
  const data = await DATA.collect();
  const cliOf = {}; for (const d of world.dirs) { const r = world.shipm('report', 'panel', '--project', d); check('CLI: `shipm report panel` exits 0 with JSON for ' + path.basename(d), r.status === 0 && /^\{/.test(r.stdout), r.stderr.slice(0, 200)); cliOf[path.basename(d)] = JSON.parse(r.stdout); }
  const names = Object.keys(cliOf).sort();
  check('live fixture: ' + names.length + ' projects (15) with open CRs, autopilot states, ask inbox', names.length === 15 && names.includes('ask') && names.includes('mu-auto-run'), names.join());
  const byName = Object.fromEntries(data.projects.map(p => [p.name, p]));
  check('collect() lists exactly the fixture projects', JSON.stringify(Object.keys(byName).sort()) === JSON.stringify(names), Object.keys(byName).join());

  // ---- 2. data.js hands the CLI fields through unchanged
  let bad = [];
  for (const n of names) {
    const j = cliOf[n], p = byName[n]; if (!p) { bad.push(n + ': missing'); continue; }
    const want = { playbook: j.playbook, cr: j.playbook ? j.cr.slice(0, 5) : null, stageLabels: j.stageLabels, nextAction: typeof j.nextAction === 'string' ? j.nextAction : null, lastVerdict: j.lastVerdict, autopilot: j.autopilot };
    const ln = o => (o && o.time && typeof o.time.left_s === 'number' ? o.time.left_s : null), dl = Math.abs((ln(p.autopilot) || 0) - (ln(want.autopilot) || 0));       // left_s counts down between the two calls
    if (dl > 30) bad.push(n + '.autopilot.time.left_s'); const nl = o => o && o.time ? { ...o, time: { ...o.time, left_s: null } } : o;
    for (const k of Object.keys(want)) { const a = k === 'autopilot' ? nl(p[k]) : p[k], b = k === 'autopilot' ? nl(want[k]) : want[k]; if (JSON.stringify(a === undefined ? null : a) !== JSON.stringify(b === undefined ? null : b)) bad.push(n + '.' + k); }
  }
  check('data.js: playbook, cr, stageLabels, nextAction, lastVerdict and autopilot of all 15 projects deep-equal the live `shipm report panel` JSON', bad.length === 0, bad.slice(0, 6).join(' | '));
  const aj = cliOf.ask.ask;
  check('data.js: the ask project carries ask {inbox:true, questions_today, notes, last} = the CLI block; no other project has it', byName.ask.ask && byName.ask.ask.inbox === true && byName.ask.ask.notes === aj.notes && byName.ask.ask.limit === aj.limit && Number.isInteger(aj.limit) && byName.ask.ask.questions_today === aj.questions_today && JSON.stringify(byName.ask.ask.last) === JSON.stringify(aj.last) && names.filter(n => n !== 'ask').every(n => !byName[n].ask), JSON.stringify([byName.ask.ask, aj]));
  check('live contract: a CR whose test failed once is at the build stage with verdict FAIL (eps-fail), failed twice is blocked at verify (zeta-twice), waiting_on owner at approve (gamma-approve)',
    cliOf['eps-fail'].cr[0].stage === 'do' && cliOf['eps-fail'].cr[0].verdict === 'FAIL' && cliOf['zeta-twice'].cr[0].status === 'blocked' && cliOf['zeta-twice'].cr[0].stage === 'verify' && cliOf['gamma-approve'].cr[0].waiting_on === 'owner', JSON.stringify([cliOf['eps-fail'].cr, cliOf['zeta-twice'].cr]));

  // ---- the independent rule table: card state, primary and data-* fields from the CLI JSON only
  // Two-level timeline (owner approved 30 Oct 2026): when the engine reports caps.release and the project has release facts, an idle project that has a finished change is drawn as the
  // timeline's "Last change / Next: start a change" block (state idle, no all-done rail) instead of the old "delivered" card, and the last step of every rail reads "Done" (D1).
  const tlOn = j => !!(j.caps && j.caps.release === true && j.release && typeof j.release === 'object' && j.playbook);
  const expectCard = (n, j) => {
    const cr = Array.isArray(j.cr) ? j.cr : [], act = cr.find(c => c.status === 'open' || c.status === 'blocked') || null, q = cr.filter(c => c.status === 'queued'), fin = cr.find(c => ['delivered', 'merged'].includes(c.status));
    const ap = j.autopilot; let state;
    if (ap && ap.state === 'paused' && ap.stop) state = 'hardstop';
    else if (act && act.status === 'blocked') state = act.stage === 'verify' ? 'verify-twice' : 'blocked';
    else if (act && act.stage === 'approve') state = 'approval';
    else if (!j.playbook) state = 'noplaybook';
    else if (ap && ap.state === 'running') state = 'autopilot';
    else if (act) state = act.stage === 'do' && act.verdict === 'FAIL' ? 'verify-fail' : { scope: 'scoping', plan: 'planning', do: 'building', verify: 'verifying', review: 'reviewing', deliver: 'delivering' }[act.stage];
    else state = fin && !tlOn(j) ? 'delivered' : 'idle';
    const primary = ['hardstop', 'verify-twice', 'blocked'].includes(state) ? 'decide' : state === 'approval' ? 'plan' : q.length && !act ? 'start' : 'open';
    return { name: n, state, primary, stage: act ? act.stage : '', cr: act ? act.id : '', verdict: j.lastVerdict ? j.lastVerdict.word : '', autopilot: j.playbook ? j.playbook.autopilot : '',
      chips: cr.filter(c => ['open', 'queued', 'blocked'].includes(c.status)).map(c => c.id + ':' + c.status).join(',') };
  };

  // ---- 3. render in Chrome from collect()'s data and dump the DOM of every card
  const S = await D.session({ size: '345,900' });
  const full = { ...data, setup: { error: false, rows: [], ready: false, at: 1 } };
  const live = world.shipm('init', '--check', '--json'); const parsed = SETUP.parseCheck(live.stdout);
  check('live: `shipm init --check --json` (read-only, isolation env) parses as the panel expects', live.status === 0 && parsed.ok && parsed.rows.length >= 19, (live.stderr || '').slice(0, 200));
  full.setup = { error: false, rows: parsed.rows, ready: parsed.ready, at: 1 };
  const themes = ['light', 'dark', 'hc'];
  for (const th of themes) {
    const f = S.file('live-' + th, D.page(th, full)); await S.load(f, 315, '?tab=projects');
    const T = `[${th}] `;
    const dom = JSON.parse(await S.ev(`JSON.stringify([...document.querySelectorAll('.card:not(.askcard)')].map(c => ({ name: c.querySelector('.name').textContent, state: c.dataset.state, primary: c.dataset.primary, stage: c.dataset.stage, cr: c.dataset.cr, verdict: c.dataset.verdict, autopilot: c.dataset.autopilot, chips: c.dataset.chips })))`));
    const cards = data.projects.filter(p => p.name !== 'ask').map(p => expectCard(p.name, cliOf[p.name]));
    check(T + 'golden: the DOM dump of all ' + dom.length + ' cards (state, primary, stage, cr, verdict, autopilot level, chips) deep-equals the values derived from the live CLI JSON', JSON.stringify(dom) === JSON.stringify(cards), JSON.stringify(dom.map((d, i) => JSON.stringify(d) === JSON.stringify(cards[i]) ? null : [d, cards[i]]).filter(Boolean).slice(0, 2)));
    check(T + 'the ask inbox project is not a project card; it is the Ask card', !dom.some(d => d.name === 'ask') && await S.ev(`document.querySelectorAll('.askcard').length`) === 1);
    const tlCards = data.projects.filter(p => p.name !== 'ask' && tlOn(cliOf[p.name]));
    const wantStates = ['scoping', 'planning', 'approval', 'building', 'verify-fail', 'verify-twice', 'reviewing', 'delivering', 'autopilot', 'hardstop', 'noplaybook', 'idle'].concat(tlCards.length ? [] : ['delivered']);   // 'delivered' is the pre-timeline card; with the timeline it is the idle card
    check(T + 'all 15 - 1 states covered: scoping, planning, approval, building, verify-fail, verify-twice, reviewing, delivering, autopilot, hardstop, noplaybook, idle (and delivered when the engine has no timeline)', wantStates.every(s => dom.some(d => d.state === s)), JSON.stringify([...new Set(dom.map(d => d.state))]));
    if (tlCards.length) {                                  // the timeline's own states: a finished change with no open one shows the idle block (last change + next step), never an all-done rail
      const idleTl = JSON.parse(await S.ev(`JSON.stringify([...document.querySelectorAll('.card:not(.askcard)')].map(c => [c.querySelector('.name').textContent, c.dataset.state, !!c.querySelector('[data-tlidle]'), !!c.querySelector('.rail')]))`));
      const finishedIdle = tlCards.filter(p => { const cr = cliOf[p.name].cr || []; return !cr.some(c => ['open', 'blocked', 'queued'].includes(c.status)) && cr.some(c => ['delivered', 'merged'].includes(c.status)) && !(cliOf[p.name].autopilot && cliOf[p.name].autopilot.state); });
      check(T + 'timeline: a project with a finished change and nothing open shows the idle block (state idle, "Last change" block, no rail)', finishedIdle.length >= 1 && finishedIdle.every(p => idleTl.some(r => r[0] === p.name && r[1] === 'idle' && r[2] === true && r[3] === false)), JSON.stringify(idleTl.filter(r => finishedIdle.some(p => p.name === r[0]))));
    }
    const marks = JSON.parse(await S.ev(`JSON.stringify([...document.querySelectorAll('.card:not(.askcard)')].map(c => [c.querySelector('.name').textContent, c.querySelectorAll('.rail .rs').length, c.querySelector('.rail') ? c.querySelector('.rail').getAttribute('aria-label') : '']))`));
    const stepWords = j => { const w = STRINGS.stageNames[j.playbook.type].slice(); if (tlOn(j)) w[w.length - 1] = 'Done'; return w; };   // D1: with the timeline the last step reads "Done" (Ship/Post/Send/Apply/File are the old words)
    const labelOk = marks.every(([n, k, l]) => { const j = cliOf[n]; return j.playbook ? (k === 7 || (k === 0 && tlOn(j) && !j.cr.some(c => ['open', 'blocked'].includes(c.status)))) && (k === 0 || l === 'Steps: ' + stepWords(j).join(', ')) : k === 6 || k === 0; });
    check(T + 'the rail of every card names the steps with the everyday words of its type (all 6 types; the terse labels of the playbook stay in reports)', labelOk, JSON.stringify(marks.filter(([n, k, l]) => cliOf[n].playbook).slice(0, 2)));
    const pri = JSON.parse(await S.ev(`JSON.stringify([...document.querySelectorAll('.card:not(.askcard)')].map(c => [c.querySelector('.name').textContent, c.querySelectorAll('.btn.primary').length, c.querySelector('.btn.primary').textContent.trim()]))`));
    check(T + 'exactly one primary per card; labels: "Review plan" (approval), "Decide" (hard stop, failed twice), "Start CR-n" (queued only), "Open chat" otherwise', pri.every(([n, k]) => k === 1) && pri.find(x => x[0] === 'gamma-approve')[2] === 'Review plan' && pri.find(x => x[0] === 'nu-auto-stop')[2] === 'Decide' && pri.find(x => x[0] === 'zeta-twice')[2] === 'Decide' && pri.find(x => x[0] === 'eps-fail')[2] === 'Open chat', JSON.stringify(pri));
    // the autopilot card shows the live numbers
    const ap = await S.ev(`(() => { const c = [...document.querySelectorAll('.card:not(.askcard)')].find(c => c.querySelector('.name').textContent === 'mu-auto-run'); return { chips: [...c.querySelectorAll('.chips .chip')].map(x => x.textContent.trim()), ap: c.querySelector('.apl').textContent.replace(/\\s+/g, ' ').trim(), run: (c.querySelector('.runl') || { textContent: '' }).textContent }; })()`);
    check(T + 'running autopilot (live state file): the line reads "Autopilot · On its own" and the usage line "On its own · ... of your week used (limit ...%)"', /^Autopilot · On its own/.test(ap.ap) && /^On its own · .*of your week used \(limit \d+%\)$/.test(ap.run), JSON.stringify(ap));
    // Now block from live data
    const now = await S.ev(`(() => { const b = document.querySelector('.nowblk'); return { head: [...b.querySelectorAll('.nh')].map(x => x.textContent), wait: [...b.querySelectorAll('.nwait .nproj')].map(x => x.textContent) }; })()`);
    const wantWait = data.projects.filter(p => p.name !== 'ask').map(p => expectCard(p.name, cliOf[p.name])).filter(c => ['approval', 'hardstop', 'verify-twice', 'blocked'].includes(c.state)).map(c => c.name);
    check(T + 'Now block: "Waiting on you" lists exactly the projects the rule table says need the owner (' + wantWait.join(', ') + ')', JSON.stringify(now.wait) === JSON.stringify(wantWait) && now.head[0] === 'WAITING ON YOU (' + wantWait.length + ')', JSON.stringify(now));
    // Reports
    await S.load(f, 315, '?tab=reports');
    const idx = JSON.parse(fs.readFileSync(path.join(world.state, 'v1', 'reports', 'index.json'), 'utf8')).items;
    const rows = JSON.parse(await S.ev(`JSON.stringify([...document.querySelectorAll('.rrow')].map(r => ({ id: r.dataset.rid, proj: r.dataset.proj, verdict: r.dataset.verdict, kind: r.dataset.kind })))`));
    check(T + 'Reports: one row per item of the real index file (' + idx.length + '), same project, kind and verdict word', rows.length === idx.length && idx.length >= 4 && idx.every(i => rows.some(r => r.id === i.id && r.proj === i.project && r.kind === i.kind && r.verdict === (i.verdict || 'NOT TESTED'))), JSON.stringify([rows, idx.map(i => i.id)]).slice(0, 300));
    check(T + 'Reports: a failed or blocked report is first; the Reports badge counts them', rows[0].verdict === 'FAIL' || rows[0].verdict === 'BLOCKED', JSON.stringify(rows[0]));
    // Ask card
    await S.load(f, 315, '?tab=projects');
    const ask = await S.ev(`(() => { const c = document.querySelector('.askcard'); return { text: c.textContent.replace(/\\s+/g, ' '), dirs: c.dataset.dir || null }; })()`);
    check(T + 'Ask card from the live ask block: "Questions today ' + aj.questions_today + ' of ' + aj.limit + '" and the last note title "' + aj.last.title + '"', ask.text.includes('Questions today ' + aj.questions_today + ' of ' + aj.limit) && ask.text.includes(aj.last.title) && !ask.dirs, JSON.stringify(ask));
    // Setup
    await S.load(f, 315, '?tab=setup');
    const su = JSON.parse(await S.ev(`JSON.stringify({ head: document.querySelector('.shead b').textContent, rows: [...document.querySelectorAll('.chk')].map(r => [r.dataset.row, r.dataset.state, r.dataset.need]) })`));
    check(T + 'Setup: the rows are the rows of the real `shipm init --check --json`, in its order, with its own state and need', JSON.stringify(su.rows.map(r => r[0])) === JSON.stringify(parsed.rows.map(r => r.id)) && su.rows.every((r, i) => r[2] === parsed.rows[i].need && (r[0] === 'remote-control' || r[1] === parsed.rows[i].state)), JSON.stringify(su.rows).slice(0, 300));
    check(T + 'Setup header counts the CLI rows (' + parsed.rows.length + ')', new RegExp('^Setup · \\d+ of ' + parsed.rows.filter(r => r.id !== 'describe-work').length + ' ready$').test(su.head), su.head);
    // Setup with the CLI's onboarding fields (stage / class / os_supported and the top-level os line): the new layout derived from the REAL rows
    if (parsed.quick) {
      const fq = S.file('liveq-' + th, D.page(th, { ...full, setup: { error: false, rows: parsed.rows, ready: parsed.ready, at: 1, os: parsed.os, quick: true } })); await S.load(fq, 315, '?tab=setup');
      const q = JSON.parse(await S.ev(`JSON.stringify({ os: document.querySelector('.osl').textContent, card: !!document.querySelector('.qs [data-setup="prefs"]'), head: document.querySelector('.shead b').textContent, needs: [...document.querySelectorAll('.qn li')].map(l => l.dataset.row), more: [...document.querySelectorAll('[data-sdetbody] li')].map(l => l.dataset.row), detOpen: document.querySelector('[data-sdet]').getAttribute('aria-expanded'), red: [...document.querySelectorAll('.chk.red')].map(l => l.dataset.need) })`));
      const rest = parsed.rows.filter(r => r.stage !== 'prefs'), isReq = r => (r.cls || r.need) === 'required', needIds = rest.filter(r => isReq(r) && r.state !== 'green' && r.os_supported !== false).map(r => r.id), reqRows = rest.filter(r => isReq(r) && r.os_supported !== false);
      check(T + 'Setup (onboarding fields): the OS line is the CLI\'s own, the Quick setup card is there, the not-ready required rows are on top, Details (closed) = every other row but the prefs row', q.os === parsed.os.line && q.card && JSON.stringify(q.needs) === JSON.stringify(needIds) && q.more.length === rest.length - needIds.length && !q.more.includes('prefs') && q.detOpen === 'false', JSON.stringify(q));
      const nFix = reqRows.filter(r => r.state !== 'green').length, wantHead = nFix ? 'Setup · ' + nFix + ' to fix' : 'Setup complete';
      check(T + 'Setup (onboarding fields): the header is "' + wantHead + '" from the real required rows only, and a red mark only ever sits on a required row', q.head === wantHead && q.red.every(n => n === 'required'), JSON.stringify([q.head, q.red]));
    }
  }
  S.close();
  world.cleanup();
  console.log(C.fails ? `\nFAILED: ${C.fails} of ${C.n}` : `\nALL PASS (${C.n})`); process.exit(C.fails ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
