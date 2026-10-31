// Panel render checks (no VS Code needed): the Ideas tab, the banner, buttons, CSP-safety, escaping. Run: node tests/panel_test.js
const path = require('path'); const { html } = require(path.join(__dirname, '../vscode-ext/shipmiracle-panel/panel.js'));
let fails = 0; const check = (n, c, info = '') => { console.log((c ? 'PASS ' : 'FAIL ') + n + (c ? '' : ' ' + info)); if (!c) fails++; };
const base = { dir: '/x', stack: 'web', state: 'calm', message: '', agents: [], model: '', next: 'n', dirty: 0, ahead: 0, pushFailed: false, lastCommit: 1, tokens: { claudeDay: 0, claudeWeek: 0 }, live: null, held: false };
const I = (id, text, tags = [], verdict = '') => ({ id, text, date: '2026-10-19', tags, verdict });
const ps = [
  { ...base, name: 'sample-app', active: true, ideas: { open: [I('F1', 'Export <b>PDF</b> & "more"', ['#a']), I('F2', 'Second')], evaluated: [I('F8', 'Elsewhere', [], 'MOVE to gate · fits there'), I('F9', 'Nowhere', [], 'MOVE to ghost-project · x'), I('F10', 'Inbox move', [], 'MOVE to Inbox · unsure'), I('F3', 'Dark', [], 'BUILD LATER · score 2.4 · x'), I('F4', 'Big', [], 'SPLIT OUT · new project'), I('F5', 'Now', [], 'BUILD NOW · score 3.1'), I('F6', 'Join', [], 'MERGE with F1'), I('F7', 'No', [], 'DROP · alt')], done: 2, dropped: 1 } },
  { ...base, name: 'gate', held: true, ideas: { open: [I('F1', 'Held idea')], evaluated: [], done: 0, dropped: 0 } },
  { ...base, name: 'empty', ideas: { open: [], evaluated: [], done: 0, dropped: 0 } },
  { ...base, name: 'ideas', special: 'ideas', ideas: { open: [I('F1', 'Inbox thing')], evaluated: [], done: 0, dropped: 0 } },
];
const page = (ask, nonce = 'n0nce') => html({ plan: { meters: [] }, guard: { on: true }, projects: ps, ask }, { nonce, csp: '' });
const h = page(null);
const body = h => h.slice(h.indexOf('<body'));       // the stylesheet names the classes; only the markup counts
check('no inline style attributes (CSP)', !/\sstyle=/.test(h));
check('tabs Projects | Ideas with the open total', /data-tab="projects"/.test(h) && /data-tab="ideas"[^>]*>Ideas <i>4<\/i>/.test(h), h.match(/data-tab="ideas".{0,60}/));
const psel = h.slice(h.indexOf('data-psel'), h.indexOf('</select>', h.indexOf('data-psel')));
check('one dropdown lists every project with its count; the Inbox is named Inbox', (psel.match(/<option/g) || []).length === 5 && /<option value="__all__">All projects \(4\)</.test(psel) && />Inbox \(1\)</.test(psel) && />sample-app \(2\)</.test(psel) && !/class="pchip"/.test(h), psel);
check('one list per project plus the All projects list', (h.match(/class="ilist"/g) || []).length === 5 && /data-proj="__all__"/.test(h));
const allv = h.slice(h.indexOf('data-proj="__all__"'), h.indexOf('data-proj="sample-app"'));
check('All projects groups the ideas by project and skips projects without ideas', /class="igname"><span>sample-app/.test(allv) && /class="igname"><span>gate/.test(allv) && /class="igname"><span>Inbox/.test(allv) && !/class="igname"><span>empty/.test(allv), allv.slice(0, 200));
check('idea text and tags are HTML-escaped', h.includes('Export &lt;b&gt;PDF&lt;/b&gt; &amp; &quot;more&quot;') && !/<b>PDF<\/b>/.test(h));
check('every action is a real button', !/<(a|div|span)[^>]*data-(idea|pick|toggle|form)/.test(h) && (h.match(/<button class="btn[^>]*data-(idea|pick|toggle|form)/g) || []).length >= 30);
check('verdict pills have the right colours', /pill amber[^>]*>BUILD LATER · score 2.4/.test(h) && /pill purple[^>]*>SPLIT OUT/.test(h) && /pill green[^>]*>BUILD NOW/.test(h) && /pill blue[^>]*>MERGE/.test(h) && /pill grey[^>]*>DROP/.test(h));
check('primary action per verdict: Worth it? / Plan this / Create project…', /Worth it\?/.test(h) && /Plan this/.test(h) && /Create project…/.test(h));
const s0 = h.slice(h.indexOf('data-proj="sample-app" hidden'), h.indexOf('data-proj="gate" hidden'));
const nItems = (s0.match(/<li class="idea">/g) || []).length;
check('every idea has Move… and Copy… buttons that open an inline dropdown', (s0.match(/<button[^>]*data-pick="copy"/g) || []).length === nItems && (s0.match(/<button[^>]*data-pick="move"/g) || []).length === nItems);
const gateList = h.slice(h.indexOf('data-proj="gate" hidden'), h.indexOf('data-proj="empty" hidden'));
check('the add form is inside the tab: project dropdown, text box, three buttons', /data-addbox/.test(s0) && /<select class="fsel" data-f="project">/.test(s0) && /<textarea class="ftext" data-f="text"/.test(s0) && /data-form="add"/.test(s0) && /data-form="addreview"[^>]*>Add and check if it is worth it/.test(s0) && /data-form="cancel"/.test(s0));
check('the add dropdown offers every project except a held one, Inbox marked', !/value="gate"/.test(s0.slice(s0.indexOf('data-addbox'), s0.indexOf('</select>', s0.indexOf('data-addbox')))) && /value="ideas">Inbox \(not sure yet\)</.test(s0));
check('a held project has no add form', !/data-addbox/.test(gateList));
check('the mute button is short and cannot overflow (project name only in the tooltip)', />Mute reminders</.test(s0) && /title="Stop asking me about sample-app/.test(s0) && !/Don't remind me about/.test(h));
check('the project list for the inline dropdowns is valid JSON in a data attribute', (() => { const m = h.match(/data-pane="ideas" data-projects="([^"]*)"/); if (!m) return false; const j = JSON.parse(m[1].replace(/&quot;/g, '"').replace(/&amp;/g, '&')); return j.length === 4 && j.find(x => x.name === 'gate').held === true && j.find(x => x.name === 'ideas').label === 'Inbox'; })());
check('a MOVE verdict naming an existing project gets a "Move to <project>" button', /data-op="moveto"[^>]*data-id="F8"[^>]*data-to="gate"[^>]*>Move to gate</.test(s0) && /pill blue[^>]*>MOVE to gate/.test(s0));
check('a MOVE verdict naming a project that does not exist gets no such button', !/data-id="F9"[^>]*data-op="moveto"|data-op="moveto"[^>]*data-id="F9"/.test(s0));
check('MOVE to Inbox points at the ideas project', /data-op="moveto"[^>]*data-id="F10"[^>]*data-to="ideas"[^>]*>Move to Inbox</.test(s0));
check('Done/Dropped are only a count', /Done 2 · Dropped 1/.test(h));
const gate = h.slice(h.indexOf('data-proj="gate" hidden'), h.indexOf('data-proj="empty" hidden'));
check('a held project is read-only with a note', /session is still running/.test(gate) && !/<button[^>]*data-op="done"(?![^>]*disabled)/.test(gate) && /disabled/.test(gate));
check('an empty project invites the first idea', /No ideas yet/.test(h));
check('no banner without an ask; banner with one', !/class="banner"/.test(h) && /class="banner"[\s\S]*Review now[\s\S]*Later/.test(page({ projects: [{ name: 'ideas', count: 2 }, { name: 'sample-app', count: 1 }] })));
check('banner names the Inbox, not "ideas"', /Inbox \(2\)/.test(page({ projects: [{ name: 'ideas', count: 2 }] })));
const evil = html({ plan: { meters: [] }, guard: {}, projects: [{ ...ps[0], name: 'x" onerror="alert(1)' }], ask: null }, {});
check('a hostile project name cannot add an attribute', !/\sonerror=["']/.test(evil) && evil.includes('x&quot; onerror=&quot;alert(1)'));
const FL = (o = {}) => ({ stage: 'plan', steps: { scope: 'done', plan: 'current', ok: 'next', build: 'next', qa: 'next', review: 'next' }, running: [{ type: 'solution-architect', model: 'opus' }], plannedBy: '', builtBy: '', qaBy: '', qaState: '', planNotByArchitect: false, outside: [], integrity: false, bypass: false, refusalsToday: 0, mismatch: false, ...o });
const plan = html({ plan: { meters: [] }, guard: {}, projects: [{ ...ps[0], state: 'working', level: 'strict', flow: FL({ mismatch: 'Sonnet 5.5' }) }], ask: null }, {});
check('planning on a non-Opus model shows the mismatch chip with the /model opusplan hint', /<span class="chip wn" title="A model picked in the chat overrides opusplan">Planning on Sonnet\. Type \/model opusplan<\/span>/.test(plan), plan.match(/.{0,60}Planning on.{0,60}/));
check('planning on Opus shows no mismatch chip', !/Planning on Sonnet|Type \/model opusplan/.test(body(html({ plan: { meters: [] }, guard: {}, projects: [{ ...ps[0], state: 'working', level: 'strict', flow: FL() }], ask: null }, {}))));
const run = (ci, away) => html({ plan: { meters: [] }, guard: { on: true, away }, projects: [{ ...ps[0], ci }], ask: null }, {});
const U = 'https://github.com/me/x/actions/runs/9';
const bad = body(run({ conclusion: 'failure', status: 'completed', title: 'Broke <it>', url: U }, 0));
check('red CI: a "CI failing" chip that is a real button carrying the run URL', /<button class="chip ci fail" data-ci="https:\/\/github.com\/me\/x\/actions\/runs\/9"[^>]*>CI failing<\/button>/.test(bad), bad.match(/.{0,80}CI failing.{0,20}/));
check('CI title is escaped, no inline style', !/Broke <it>/.test(bad) && !/\sstyle=/.test(bad));
check('green CI: no chip', !/CI failing|CI running|data-ci=/.test(body(run({ conclusion: 'success', status: 'completed', title: 't', url: U }, 0))));
const going = body(run({ conclusion: '', status: 'in_progress', title: 't', url: U }, 0));
check('running CI: grey "CI running" chip, not the red one', /class="chip ci" data-ci[^>]*>CI running</.test(going) && !/>CI failing</.test(going));
check('no ci data: no chip', !/data-ci=/.test(body(run(null, 0))));
check('"Decisions while away: N" row only when there are unreviewed entries', /data-away="1"[^>]*>Decisions while away: 3</.test(body(run(null, 3))) && !/data-away=/.test(body(run(null, 0))));
check('away row sits under the Awake guard row, as a real button', /data-guard="1"><i><\/i><\/button><\/div>\s*<div class="grow"><button class="btn quiet" data-away/.test(run(null, 2)));
const stale = html({ plan: { meters: [] }, guard: {}, projects: [{ ...ps[0], chatStale: true, chatOpen: true }], ask: null }, {});
check('a stale chat shows a clickable "relaunch chat" chip (a bordered button) with the project folder', /<button class="chip relaunch" data-relaunch="\/x" data-project="sample-app"[^>]*>↻ relaunch chat<\/button>/.test(stale), stale.match(/data-relaunch.{0,80}/));
check('no relaunch chip when the chat is healthy', !/<button class="chip relaunch"/.test(html({ plan: { meters: [] }, guard: {}, projects: [{ ...ps[0], chatOpen: true }], ask: null }, {})));
const oldl = html({ plan: { meters: [] }, guard: {}, projects: [{ ...ps[0], chatStale: true, chatOld: true, chatOpen: true }], ask: null }, {});
check('an old-launcher chat shows the relaunch chip with the blank-conversation tooltip', /data-relaunch="\/x"[^>]*title="This chat was started by the old launcher: a full VS Code restart would open a blank conversation\. Click to reopen it once \(the conversation continues\)"/.test(oldl) && !/lost its link/.test(oldl), oldl.match(/data-relaunch.{0,160}/));
check('a plain stale chat keeps the lost-link tooltip', /lost its link/.test(stale) && !/old launcher/.test(stale));
const pkg = require(path.join(__dirname, '../vscode-ext/shipmiracle-panel/package.json'));
check('the sidebar shows one title: the view is named like its container (no "SHIPMIRACLE: PROJECTS")', pkg.contributes.views.shipmiracle[0].name === pkg.contributes.viewsContainers.activitybar[0].title);
check('no header buttons in the sidebar title bar (+, lamp, sync moved into the tab)', !(pkg.contributes.menus || {})['view/title'] && !pkg.contributes.commands.some(c => c.command === 'shipmiracle.ideas'));
const ptools = h.slice(h.indexOf('class="ptools"'), h.indexOf('</div>', h.indexOf('class="ptools"')));
check('the Projects tab starts with + New project and Check & update buttons', /<button class="btn primary" data-toggle="newbox"[^>]*>\+ New project/.test(ptools) && !/data-cmd="newProject"/.test(body(h)) && /data-cmd="check"[^>]*>Check &amp; update/.test(ptools) && h.indexOf('class="ptools"') > h.indexOf('data-pane="projects"') && h.indexOf('class="ptools"') < h.indexOf('class="card'));

// ---- card v2 ----
const card1 = (o, data = {}) => { const b = body(html({ plan: { meters: [] }, guard: {}, projects: [{ ...ps[0], ...o }], ask: null, ...data }, {})); const i = b.indexOf('<div class="card '); return i < 0 ? b : b.slice(i, b.indexOf('</section>', i)); };   // the card only (the Now block above it has its own tests in panel_v3_ui_test)
const noMenu = h => h.replace(/<div class="mwrap">[\s\S]*?(?=<div class="foot">)/, '');                 // the card's ⋯ menu always holds a Handoff item: the tests below look at the card body
const subOf = h => { const m = h.match(/<div class="sub[^"]*" title="([^"]*)">/); return m ? m[1].replace(/&#39;/g, "'") : ''; };
const ST = (stage, o = {}) => FL({ stage, steps: { scope: 'done', plan: 'done', ok: 'done', build: 'next', qa: 'next', review: 'next', [stage]: 'current' }, ...o });
const SUB = [
  ['idle', { state: 'idle', flow: FL({ stage: '', steps: { scope: 'next', plan: 'next', ok: 'next', build: 'next', qa: 'next', review: 'next' }, running: [] }), lastCommit: Date.now() / 1000 - 7200 }, /^No playbook yet\. Gate rules still apply$/],
  ['scope', { state: 'working', flow: ST('scope', { running: [{ type: 'product-analyst', model: 'sonnet' }] }) }, /^Scoping: product-analyst is clarifying the task$/],
  ['plan', { state: 'working', flow: ST('plan') }, /^Planning with Opus: solution-architect$/],
  ['approval', { state: 'needs-input', approval: true, message: 'ok?', flow: ST('ok', { running: [] }) }, /^Waiting for your OK: the plan is ready$/],
  ['build', { state: 'working', flow: ST('build', { running: [{ type: 'frontend-engineer', model: 'sonnet' }] }) }, /^Building with Sonnet: frontend-engineer$/],
  ['qa', { state: 'working', flow: ST('qa', { running: [{ type: 'qa-engineer', model: 'sonnet' }] }) }, /^Testing: qa-engineer is checking the build$/],
  ['review', { state: 'working', flow: ST('review', { running: [{ type: 'independent-reviewer', model: 'opus' }] }) }, /^Review: independent-reviewer is reading the change$/],
  ['done', { state: 'idle', flow: FL({ stage: 'review', steps: { scope: 'done', plan: 'done', ok: 'done', build: 'done', qa: 'done', review: 'next' }, running: [], qaState: 'ran' }) }, /^No playbook yet\. Gate rules still apply$/],
  ['question', { state: 'needs-input', message: 'Which colour?', flow: ST('build', { running: [] }) }, /^Needs you: Which colour\?$/],
  ['held', { state: 'working', held: true, flow: ST('build') }, /^Held: its session is still running\.$/],
  ['limit', { state: 'idle', limitUntil: '2026-10-19T17:30:00', flow: FL() }, /^Waiting for the usage limit to reset \(back \d\d:\d\d\)$/],
  ['frozen', { state: 'working', live: { model: 'Sonnet', phase: 'stalled', modelAge: 5, idle: 1500 }, flow: ST('build') }, /^No activity for 25 min\. Open Health$/],
  ['integrity', { state: 'working', level: 'strict', flow: ST('build', { integrity: true }) }, /^Blocked: a gate file changed$/],
  ['none', { state: 'idle', flow: undefined }, /^No playbook yet\. Gate rules still apply$/],
];
SUB.forEach(([n, o, re]) => { const x = subOf(card1(o)); check('subtitle for the ' + n + ' state: ' + x, re.test(x)); });
check('priority: held beats integrity beats frozen beats limit beats approval', /^Held/.test(subOf(card1({ held: true, level: 'strict', state: 'needs-input', approval: true, limitUntil: 1e9, flow: FL({ integrity: true }) }))) && /^Blocked/.test(subOf(card1({ level: 'strict', limitUntil: 1e9, approval: true, live: { phase: 'stalled', idle: 600 }, flow: FL({ integrity: true }) }))) && /^No activity/.test(subOf(card1({ limitUntil: 1e9, approval: true, live: { phase: 'stalled', idle: 600 }, flow: FL() }))) && /^Waiting for the usage limit/.test(subOf(card1({ limitUntil: 1e9, approval: true, state: 'needs-input', flow: FL() }))));
const strip = card1({ state: 'working', level: 'strict', flow: ST('build', { running: [{ type: 'frontend-engineer', model: 'sonnet' }] }) });
check('the strip shows six steps for the 4 main stages, aria-label on every step', ['plan', 'build', 'qa', 'review'].every(st => { const x = card1({ state: 'working', flow: ST(st) }); return (x.match(/<li class="ts /g) || []).length === 6 && (x.match(/<li class="ts [^"]*" aria-label="[^"]+"/g) || []).length === 6 && x.includes('aria-current="step"'); }));
check('strip: done filled, current with the word and model, next hollow', /<li class="ts done" aria-label="Scope: done"><i class="td"><\/i>Scope<\/li>/.test(strip) && /<li class="ts cur" aria-label="Build: in progress with Sonnet" aria-current="step"><i class="td"><\/i>Build · Sonnet<\/li>/.test(strip) && /<li class="ts next" aria-label="QA: not yet">/.test(strip));
const qaTxt = q => card1({ state: 'idle', flow: FL({ qaState: q, builtBy: 'x' }) });
check('QA wording: ran / not run yet / stale, and "passed" only for a real PASS', />QA ran</.test(qaTxt('ran')) && />QA not run yet</.test(qaTxt('none')) && />QA stale: code changed after the test</.test(qaTxt('stale')) && !/passed/i.test(['ran', 'none', 'stale', ''].map(qaTxt).join('')));
const qaV = (q, o) => card1({ state: 'idle', flow: FL({ qaState: q, builtBy: 'x', ...o }) });
check('QA wording: a PASS verdict says "QA passed" with counts', />QA passed \(12 passed\)</.test(qaV('passed', { qaVerdict: 'PASS', qaCounts: '12 passed' })) && />QA passed</.test(qaV('passed', { qaVerdict: 'PASS' })));
check('QA wording: FAIL says "QA FAILED" with the counts, amber contrast class kept', /<span class="warnt">QA FAILED \(3 failed, 9 passed\)<\/span>/.test(qaV('failed', { qaVerdict: 'FAIL', qaCounts: '3 failed, 9 passed' })) && /<span class="warnt">QA BLOCKED<\/span>/.test(qaV('failed', { qaVerdict: 'BLOCKED' })));
const esc1 = qaV('failed', { qaVerdict: 'FAIL', qaCounts: '<img src=x>1 failed' });
check('QA wording: cut off / no verdict (strict) are warnings', /<span class="warnt">QA cut off: it never reported<\/span>/.test(qaV('cutoff')) && /<span class="warnt">QA: no verdict<\/span>/.test(qaV('noverdict')));
const tmchip = card1({ state: 'idle', flow: FL({}), team: { count: 3, bad: [], dod: ['a.md: no DoD', 'b.md: maxTurns is missing'] } });
check('team chip: DoD problems get their own chip, not the model-rule chip', /2 agent files need the DoD block/.test(tmchip) && !/break the model rule/.test(tmchip), tmchip.slice(0, 300));
check('QA wording: counts are escaped', !/<img src=x>/.test(esc1) && /&lt;img src=x&gt;1 failed/.test(esc1));
check('actors line: one agent and several agents', />Opus · solution-architect<\/div>/.test(card1({ flow: FL() })) && />Sonnet · 2 agents: frontend-engineer, qa-engineer<\/div>/.test(card1({ flow: FL({ running: [{ type: 'frontend-engineer', model: 'sonnet' }, { type: 'qa-engineer', model: 'sonnet' }] }) })));
check('"Plan not by the architect" in warn colour', /<span class="warnt">Plan not by the architect<\/span>/.test(card1({ flow: FL({ planNotByArchitect: true }) })) && !/Plan not by the architect/.test(card1({ flow: FL() })));
const gch = card1({ level: 'strict', flow: FL({ integrity: true, refusalsToday: 3, outside: ['a.js', 'b.js'], bypass: true, mismatch: true }), team: { count: 0, bad: ['x.md: model: inherit'] } });
check('gate chips: integrity button to Health, refused, outside with names, bypass', /<button class="chip wn" data-hopen="-"[^>]*>⚠ Gate file changed: your next message clears it<\/button>/.test(gch) && />3 refused today</.test(gch) && /title="a\.js\nb\.js">2 files outside the team</.test(gch) && />bypass on for this turn</.test(gch));
check('at warn level the integrity chip is only a note', />Gate file changed \(note only\)</.test(card1({ level: 'warn', flow: FL({ integrity: true }) })) && !/Blocked/.test(subOf(card1({ level: 'warn', flow: FL({ integrity: true }) }))));
check('team chips: none installed, and the model rule with the lines in the tooltip; quiet when OK', />No team agents</.test(gch) && /title="x\.md: model: inherit">1 agent file breaks the model rule</.test(gch) && !/No team agents|break/.test(card1({ team: { count: 5, bad: [] }, flow: FL() }).replace(/Team flow:[^"]*/g, '')));
const gone = card1({ state: 'working', model: 'Sonnet 5.5', next: 'ship it', agents: [{ type: 'backend-engineer', model: 'sonnet', mins: 12, quiet: 20, stalled: false }, { type: 'frontend-engineer', model: 'sonnet', mins: 12, quiet: 900, stalled: true }], live: { model: 'Sonnet 5.5', phase: 'implementing', modelAge: 5, idle: 5 }, flow: ST('build') });
check('removed: lead chip, per-agent minute chips, live row, flow line, Working head, calm/check words', !/lead ·|class="live|class="flowl|Working ·|Next:|implementing|>calm<|>check</.test(gone) && !/backend-engineer · sonnet|12 min/.test(gone));
check('only a stalled agent keeps a chip: "<type> quiet N min"', /<span class="chip stall"[^>]*>frontend-engineer quiet 15 min<\/span>/.test(gone));
check('the gate-level pill is gone from the card (revision v2: Safe mode is a line on the Autopilot line of playbook cards, tested in tests/panel_v3_rev2_test.js)', !/chip lvl/.test(card1({ level: 'strict', flow: FL() })) && !/chip lvl/.test(card1({ level: 'warn', flow: FL() })) && !/data-level=/.test(card1({ level: 'strict', flow: FL() }, { levelSwitch: { ok: true, why: '' } })));
check('the project card has a state icon, name and stack in the title row', /<div class="top"><svg[^>]*>.*?<\/svg><span class="name" title="sample-app">sample-app<\/span><span class="tag">web<\/span>/.test(strip));
const nb = h.slice(h.indexOf('data-newbox'), h.indexOf('data-newbox') + 2500);
check('New project box: name, type (7 kinds), about (140), Create disabled, Cancel; fields use data-nf only', /data-nf="name"/.test(nb) && /<option value="notes">/.test(nb) && (nb.match(/<option value=/g) || []).length >= 7 && /maxlength="140"/.test(nb) && /data-nform="create" disabled/.test(nb) && /data-nform="cancel"/.test(nb) && !/data-f=/.test(nb.slice(0, nb.indexOf('data-nform="cancel"'))));
const busy = body(html({ plan: { meters: [] }, guard: {}, projects: [ps[0]], ask: null, creating: { name: 'trial-notes', ts: 1 }, pnotice: 'Created <x>' }, {}));
check('creating row and project notice at the top of the Projects pane, OK button dismisses via health', /Creating trial-notes… \(GitHub repo too, up to a minute\)/.test(busy) && /data-busy="1"/.test(busy) && /class="hnote"><span>Created &lt;x&gt;<\/span><button class="btn" data-health data-op="dismiss-project-notice" data-id="-">OK<\/button>/.test(busy) && busy.indexOf('Creating trial-notes') < busy.indexOf('class="ptools"') && busy.indexOf('class="hnote"') < busy.indexOf('class="ptools"'));
check('no creating row or notice when idle', !/class="pcreate"|class="hnote"/.test(body(h)));
check('no inline style attributes anywhere in a full card page', !/\sstyle=/.test(gch) && !/\sstyle=/.test(busy));


// ---- round 2: never name an agent that is not running; per-project level switch; neutral working texts ----
const NR = (o, steps) => ({ state: 'working', flow: FL({ stage: 'build', running: [], steps: { scope: 'next', plan: 'next', ok: 'next', build: 'next', qa: 'next', review: 'next', ...steps }, ...o }) });
check('working with nobody running: QA done, review next -> "Working · QA ran, review next"', subOf(card1(NR({}, { scope: 'done', plan: 'done', ok: 'done', build: 'done', qa: 'done' }))) === 'Working · QA ran, review next');
check('working with nobody running and no plan -> "Working · no plan yet"', subOf(card1(NR({}, {}))) === 'Working · no plan yet');
check('working between steps -> "Working · <last step> done"', subOf(card1(NR({}, { scope: 'done', plan: 'done', ok: 'done', build: 'done' }))) === 'Working · Build done');
const ghost = card1(NR({ plannedBy: 'solution-architect', builtBy: 'frontend-engineer', actors: [{ type: 'frontend-engineer', model: 'sonnet' }] }, { scope: 'done', plan: 'done', ok: 'done', build: 'current' }));
check('an actor not in flow.running is never named (subtitle, strip, actors line)', !/frontend-engineer|solution-architect/.test(ghost.replace(/title="Team flow[^"]*"/g, '')) && !/Sonnet/.test(ghost.replace(/title="[^"]*"/g, '')), ghost.match(/<div class="sub.{0,120}/));
check('with a running agent the subtitle and actors line name it', subOf(card1({ state: 'working', flow: ST('build', { running: [{ type: 'backend-engineer', model: 'sonnet' }] }) })) === 'Building with Sonnet: backend-engineer');
check('plannedByLabel is printed as given: an agent name has no "built-in", the Plan agent label does', />Plan: solution-architect</.test(card1({ flow: FL({ plannedByLabel: 'solution-architect' }) })) && !/built-in/.test(card1({ flow: FL({ plannedByLabel: 'solution-architect' }) }).slice(100)) && />Plan: Plan agent \(built-in\)</.test(card1({ flow: FL({ plannedByLabel: 'Plan agent (built-in)' }) })) && !/>Plan: /.test(card1({ flow: FL() })) && !/<x>/.test(card1({ flow: FL({ plannedByLabel: '<x>' }) })));
const own = (o, ls) => card1({ level: 'strict', flow: FL(), levelSwitch: ls, ...o });

// ---- token card (ledger incl. cache reads, or the labelled estimate) and the context chip + Handoff button
const pg = data => body(html({ plan: { meters: [] }, guard: {}, projects: [{ ...ps[0] }], ask: null, ...data }, {}));
const LEDF = { fresh: true, source: 'ledger', today: { calls: 1911, tokens: 263200000, overCallsPct: 20.04, overTokensPct: 60 }, week: { calls: 14720, tokens: 3181200000, overCallsPct: 37.1, overTokensPct: 71 } };
const tk = pg({ ledger: LEDF });
check('token card (ledger): "Today: X tokens (incl. cache reads)" in plain words', /Today: 263M tokens \(incl\. cache reads\)/.test(tk), tk.match(/Today[^<]{0,80}/));
check('token card (ledger): "N% of calls are over 200k context" with its tooltip', /20% of calls are over 200k context/.test(tk) && /Chats past 200k tokens cost more per message/.test(tk));
check('token card (ledger): the old "Claude .." estimate line and its label are gone', !/estimate, cache reads not counted/.test(tk) && !/Claude 0/.test(tk));
const old1 = pg({ ledger: { fresh: false, source: 'transcripts', why: 'missing' } });
check('token card fallback (no ledger): old figures kept and labelled as an estimate without cache reads', /Today \(estimate, cache reads not counted\)/.test(old1) && /Claude 0/.test(old1) && /no ledger yet/.test(old1), old1.match(/Today[^<]{0,60}/));
check('token card fallback (old ledger) says why', /older than 15 minutes/.test(pg({ ledger: { fresh: false, source: 'transcripts', why: 'old' } })));
check('token card: no ledger field at all (old callers) still renders the labelled estimate', /Today \(estimate/.test(pg({})));
check('token card (ledger): no calls today falls back to the 7-day share, no share at all hides the row', /37% of calls are over 200k/.test(pg({ ledger: { ...LEDF, today: { calls: 0, tokens: 0, overCallsPct: null } } })) && !/of calls are over 200k/.test(pg({ ledger: { ...LEDF, today: { calls: 0, tokens: 5, overCallsPct: null }, week: {} } })));
check('card foot uses the ledger figure when the project has one, else the old line', /Today: 41M tokens \(incl\. cache reads\)/.test(card1({ tokens: { claudeDay: 5, claudeWeek: 5, ledgerDay: 41000000 } })) && /Today: Claude 5/.test(card1({ tokens: { claudeDay: 5, claudeWeek: 5 } })));
const cx = (tokens, level, o = {}) => card1({ context: { tokens, level }, ...o });
for (const [tok, lv, chip] of [[199999, 'none', false], [200000, 'soft', true], [299999, 'soft', true], [300000, 'strong', true]]) {
  const c = cx(tok, lv);
  check(`context ${tok}: ${chip ? (lv === 'strong' ? 'chip + quiet Handoff button' : 'chip + amber dot on the menu item, no button') : 'plain text, no chip, no button'}`, chip ? new RegExp(`<span class="chip wn ctx${lv === 'strong' ? ' strong' : ''}"[^>]*>Chat is ${lv === 'strong' ? 'very ' : ''}long · ${Math.floor(tok / 1000)}k</span>`).test(c) && (lv === 'strong' ? /data-handoff="ask"/.test(noMenu(c)) : !/data-handoff/.test(noMenu(c)) && /data-handoff="ask"[^>]*>Handoff \+ fresh chat<span class="mdot"/.test(c)) : !/class="chip[^"]*ctx/.test(c) && !/<button[^>]*data-handoff/.test(noMenu(c)) && /context 199k/.test(c), c.match(/context[^<]{0,20}/));
}
check('context chip tooltip carries the UX wording and the exact size', /Chat is long\. Handing over to a fresh chat saves tokens and keeps quality up\. Your choice\. \(214,000 tokens in this chat\)/.test(cx(214000, 'soft')) && /Chat is very long\./.test(cx(312000, 'strong')));
check('strong chip has the stronger class', /ctx strong/.test(cx(312000, 'strong')) && !/ctx strong/.test(cx(214000, 'soft')));
const hb = cx(312000, 'strong').match(/<button[^>]*data-handoff="ask"[^>]*>[^<]*<\/button>/)[0];
check('Handoff + fresh chat is a secondary button (never primary), asks "Sure?" in place, names the project', />Handoff \+ fresh chat</.test(hb) && !/primary/.test(hb) && /data-sure="Sure\? Note saved, then fresh chat"/.test(hb) && /data-project="sample-app"/.test(hb) && !/disabled/.test(hb), hb);
check('Handoff button is disabled with "Wait: an agent is working." while the project works, waits, or has an agent', ['working', 'needs-input'].every(st => { const b = cx(312000, 'strong', { state: st }).match(/<button[^>]*data-handoff="ask"[^>]*>/)[0]; return /disabled/.test(b) && /Wait: an agent is working\./.test(b); }) && /disabled/.test(cx(312000, 'strong', { agents: [{ id: 'a', type: 'qa-engineer', started: 1, mins: 1, quiet: 1, stalled: false }] }).match(/<button[^>]*data-handoff="ask"[^>]*>/)[0]));
check('no context -> no chip, no handoff row', !/class="chip wn ctx/.test(card1({})) && !/<button[^>]*data-handoff/.test(noMenu(card1({}))));
const asked = cx(312000, 'strong', { handoff: { asked: true, at: 1, ready: false } });
check('after the ask: no Ask button, "Open fresh chat" is disabled and says what is missing', !/data-handoff="ask"/.test(asked) && /data-handoff="open"[^>]*disabled/.test(asked) && /docs\/STATUS\.md has not changed since you asked/.test(asked) && /Handoff asked/.test(asked), asked.match(/data-handoff="open"[^>]*>/));
const ready = cx(312000, 'strong', { handoff: { asked: true, at: 1, ready: true } });
check('STATUS newer than the ask: "Open fresh chat" is enabled, tooltip says the old chat stays open, still not primary', /<button class="btn" data-handoff="open"[^>]*>/.test(ready) && !/data-handoff="open"[^>]*disabled/.test(ready) && /The old chat is not closed/.test(ready));
check('handoff row stays after the context chip drops below 200k (the owner finishes what was started)', /data-handoff="open"/.test(card1({ context: { tokens: 20000, level: 'none' }, handoff: { asked: true, at: 1, ready: true } })));
check('the ask can not be pressed while the project works even when STATUS is ready', /data-handoff="open"[^>]*disabled/.test(cx(312000, 'strong', { state: 'working', handoff: { asked: true, at: 1, ready: true } })));
check('project name is escaped in the handoff button', /data-project="a&quot;b&lt;"/.test(cx(312000, 'strong', { name: 'a"b<' })));
check('the panel script posts {type:handoff, step, project} and arms "Sure?" before the ask', /type: 'handoff', step: hf\.dataset\.handoff, project: hf\.dataset\.project/.test(h) && /hf\.dataset\.handoff === 'ask' && armedBtn !== hf/.test(h));
check('no inline styles introduced (CSP)', !/\sstyle=/.test(cx(312000, 'strong')) && !/\sstyle=/.test(tk));

// ---- team chips (T6): none / model / dod / untrusted / no team ----
{
  const T = o => card1({ state: 'idle', flow: FL({}), team: { count: 4, bad: [], dod: [], untrusted: [], ...o } });
  const none = T({});
  check('team chips: a clean team shows none of the five team chips', !/No team agents|break the model rule|breaks the model rule|DoD block|untrusted/.test(none), none.match(/class="chip[^"]*"[^>]*>[^<]*/g));
  check('team chips: "No team agents" appears only at count 0 (count 1 with user-level agent: none)', !/No team agents/.test(T({ count: 1 })) && />No team agents</.test(T({ count: 0 })));
  const md = T({ bad: ['.claude/agents/x.md: model is inherit (use opus, sonnet or haiku)', 'y.md: no Model reason'] });
  check('team chips: model rule chip counts model problems only: "2 agent files break the model rule"', />2 agent files break the model rule</.test(md) && !/DoD block/.test(md) && !/untrusted/.test(md));
  check('team chips: one model problem reads "1 agent file breaks the model rule"', />1 agent file breaks the model rule</.test(T({ bad: ['x.md: bad'] })));
  const dd = T({ dod: ['a.md: no DoD', 'b.md: maxTurns is missing'], bad: ['x.md: bad'] });
  check('team chips: "2 agent files need the DoD block" stays next to the model chip', />2 agent files need the DoD block</.test(dd) && />1 agent file breaks the model rule</.test(dd));
  check('team chips: one dod problem reads "1 agent file needs the DoD block"', />1 agent file needs the DoD block</.test(T({ dod: ['a.md: x'] })));
  const un = T({ untrusted: ['qa-reviewer', 'a<b'] });
  check('team chips: "2 agents untrusted" is a button carrying the project name for the Activate QuickPick', /<button class="chip wn" data-activate="sample-app"[^>]*>2 agents untrusted<\/button>/.test(un), un.match(/data-activate[^>]*>[^<]*/g));
  check('team chips: untrusted tooltip says privileged role claimed by a file that is not a master copy, names the files (escaped) and `shipm agents activate`', /title="[^"]*privileged role[^"]*not a master copy[^"]*qa-reviewer, a&lt;b[^"]*shipm agents activate sample-app/.test(un), un.match(/data-activate[^>]*/g));
  check('team chips: "1 agent untrusted" (singular)', />1 agent untrusted</.test(T({ untrusted: ['x-y'] })));
  check('team chips: no untrusted field (old data) gives no chip and no crash', !/untrusted/.test(card1({ state: 'idle', flow: FL({}), team: { count: 2, bad: [], dod: [] } })));
  const names = card1({ state: 'working', flow: FL({ stage: 'qa', running: [{ type: 'qa-engineer', label: 'qa-engineer (verifier)', model: 'sonnet' }] }) });
  check('flow strip: an old actor name shows with its new role: "qa-engineer (verifier)"', /qa-engineer \(verifier\)/.test(names), names.match(/Testing[^<]*/g));
  const nl = card1({ state: 'working', flow: FL({ stage: 'qa', running: [{ type: 'qa-engineer', model: 'sonnet' }] }) });
  check('flow strip: data without a label (older data.js) still shows the type', /Testing: qa-engineer is checking the build/.test(nl), nl.match(/Testing[^<]*/g));
  check('the panel script posts {type:activateAgent, project} on the untrusted chip and keeps the card from opening', /data-activate\]'\); if \(ac\) \{ e\.stopPropagation\(\); vscode\.postMessage\(\{ type: 'activateAgent', project: ac\.dataset\.activate \}\)/.test(html({ plan: { meters: [] }, guard: { on: true }, projects: ps, ask: null }, { nonce: 'n', csp: '' })));
}

console.log(fails ? '\nFAILED: ' + fails : '\nALL PASS'); process.exit(fails ? 1 : 0);
