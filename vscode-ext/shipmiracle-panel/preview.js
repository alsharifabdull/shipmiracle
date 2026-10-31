// Render the panel outside VS Code to check it: node preview.js [--demo] > /tmp/shipmiracle-panel.html
// --demo adds one "needs you" project and two running agents so every state is visible, plus four project-card flow
// states (idle, building with Sonnet, waiting for approval, blocked by integrity) for the card v2 tests and screenshots.
const { collect } = require('./data');
const { html } = require('./panel');
const wrap = (inner, dark) => inner.replace('<html>', `<html style="${dark ? 'color-scheme:dark;--vscode-foreground:#cccccc;--vscode-descriptionForeground:#9d9d9d;--vscode-panel-border:rgba(255,255,255,.13);--vscode-editorWidget-background:#252526;--vscode-textLink-foreground:#4daafc;--vscode-editorWarning-foreground:#cca700;--vscode-testing-iconPassed:#73c991;--vscode-errorForeground:#f48771' : ''}">`).replace('<body>', `<body style="background:${dark ? '#181818' : '#f8f8f8'}">`);
collect().then(d => {
  if (process.argv.includes('--demo')) {
    const demoPool = d.projects.filter(p => !p.special && !p.hub);   // any two projects of this machine: the demo needs no particular names
    const g = demoPool[0]; if (g) { g.state = 'needs-input'; g.message = 'approve 3 skills for the review'; }
    const s = demoPool[1]; if (s) { s.state = 'working'; s.agents = [{ type: 'frontend-engineer', model: 'sonnet', mins: 6 }, { type: 'qa-reviewer', model: 'sonnet', mins: 2 }]; }
    // Card v2 fixtures: four states (idle, building with Sonnet, waiting for approval, blocked by integrity). Same shape as data.js p.flow.
    const mk = (stage, over = {}) => {
      const order = ['scope', 'plan', 'ok', 'build', 'qa', 'review']; const at = order.indexOf(stage);
      const steps = {}; order.forEach((k, i) => { steps[k] = i < at ? 'done' : i === at ? 'current' : 'next'; });
      const f = { stage, steps, actors: [], running: [], actorRunning: false, plannedByLabel: '', plannedBy: '', builtBy: '', qaBy: '', qaState: '', planNotByArchitect: false, outside: [], integrity: '', bypass: false, refusalsToday: 0, mismatch: false, planned: '', built: '', qa: false, ...over };
      f.plannedByLabel = f.plannedByLabel || f.plannedBy; if (over.actors && !over.running && stage !== 'done' && stage !== 'ok') { f.running = over.actors; f.actorRunning = true; }
      return f;
    };
    const quiet = d.projects.filter(p => !p.special && !p.hub && p !== g && p !== s);
    const idle = quiet[0], blocked = quiet[1];
    if (idle) { idle.state = 'calm'; idle.level = 'strict'; idle.approval = false; idle.limitUntil = 0; idle.team = { count: 11, bad: [] };
      idle.flow = mk('done', { steps: { scope: 'done', plan: 'done', ok: 'done', build: 'done', qa: 'done', review: 'next' }, plannedBy: 'solution-architect', builtBy: 'frontend-engineer', qaBy: 'qa-engineer', qaState: 'ran', actors: [{ type: 'qa-engineer', model: 'sonnet' }] }); }
    if (s) { s.level = 'strict'; s.approval = false; s.limitUntil = 0; s.team = { count: 11, bad: [] };
      s.flow = mk('build', { plannedBy: 'solution-architect', builtBy: 'frontend-engineer', qaState: 'none', refusalsToday: 2, actors: [{ type: 'frontend-engineer', model: 'sonnet' }, { type: 'qa-reviewer', model: 'sonnet' }] }); }
    if (g) { g.state = 'needs-input'; g.message = ''; g.level = 'warn'; g.approval = true; g.limitUntil = 0; g.team = { count: 11, bad: [] };
      g.flow = mk('ok', { plannedBy: 'solution-architect', actors: [{ type: 'solution-architect', model: 'opus' }] }); }
    if (blocked) { blocked.state = 'working'; blocked.level = 'strict'; blocked.approval = false; blocked.limitUntil = 0; blocked.team = { count: 11, bad: ['.claude/agents/x.md: model is inherit (use opus, sonnet or haiku)'] };
      blocked.flow = mk('build', { plannedBy: 'solution-architect', builtBy: 'backend-engineer', qaState: 'stale', integrity: 'blocked', outside: ['src/app.js', 'tools/build'], bypass: true, refusalsToday: 3, actors: [{ type: 'backend-engineer', model: 'sonnet' }] }); }
    d.levelSwitch = { ok: false, why: 'Not now: ' + (s ? s.name : 'a project') + ' is working or waiting for you. Every chat of this project reads the gate level, so switch it when this project is idle.' };
    const RANK = { 'needs-input': 0, working: 1, calm: 2, idle: 3 };
    d.projects.sort((a, b) => (a.special ? 1 : 0) - (b.special ? 1 : 0) || RANK[a.state] - RANK[b.state]);
  }
  if (process.argv.includes('--v3')) {                       // panel v3: one project per card state of the UX spec (fixtures shared with tests/panel_v3_ui_test.js; dev only)
    try { const F = require('../../tests/panel_v3_fixtures'); d.projects = [...F.STATES.map(x => x.p), ...F.TYPES.map(x => x.p), F.EXTRA.queued, F.EXTRA.fast, F.EXTRA.arabic, F.EXTRA.held, F.mk('ask', 'notes', { dir: '/x/ask', ask: { inbox: true, questions_today: 3, notes: 1, last: { title: 'What is a monad?', path: 'docs/notes/2026-10-21-what-is-a-monad.md', ts: 1 } } })]; d.remote = { state: 'on' }; d.levelSwitch = { ok: true, why: '' };
      const T = require('../../tests/panel_v3_tab_fixtures'); d.reports = T.REPORTS; d.setup = T.SETUP(); d.health = T.HEALTH(); }
    catch (e) { console.error('--v3 needs tests/panel_v3_fixtures.js'); process.exit(1); }
  }
  if (process.argv.includes('--levels')) {   // show every colour level: low, mid, high, almost out
    const set = (id, pct) => { const m = d.plan.meters.find(x => x.id === id); if (m) { m.pct = pct; m.lvl = pct >= 95 ? 3 : pct >= 80 ? 2 : pct >= 50 ? 1 : 0; } };
    set('five', 97); set('week', 86); set('model-fable', 62); set('model-opus', 18); set('model-sonnet', 18);
  }
  const nonce = 'preview123';   // same security rules as VS Code's webview: no inline styles, nonce'd style and script only
  const csp = `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'nonce-${nonce}'; script-src 'nonce-${nonce}';">`;
  const page = html(d, { nonce, csp });
  console.log(`<!doctype html><html><head><meta charset="utf-8"></head><body style="margin:0;display:flex;gap:24px;padding:16px;background:#ddd">
<iframe style="border:0;width:300px;height:1000px" srcdoc="${wrap(page, false).replace(/&/g, '&amp;').replace(/"/g, '&quot;')}"></iframe>
<iframe style="border:0;width:300px;height:1000px" srcdoc="${wrap(page, true).replace(/&/g, '&amp;').replace(/"/g, '&quot;')}"></iframe></body></html>`);
});
