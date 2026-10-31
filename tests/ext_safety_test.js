// Extension-host safety (security review of the panel, M1 M2 M3 L1 L2), no Chrome:
//  M2  a cloned project cannot freeze or bloat the extension host: docs/STATUS.md, CLAUDE.md, AGENTS.md, FEATURE-IDEAS.md (and the state files) as a symlink to /dev/zero or as a FIFO are
//      skipped quickly, with a small memory cost; every file read in data.js / extension.js / locations.js goes through the capped reader (reports.js readCapped / readText / readJson).
//  M1  health.json with hostile counts becomes numbers in collect().
//  M3  every text the panel types into a CHAT starts with the marker from strings.js (except the exact '/btw ' prefill); /rename is not sent for approval-word project names.
//  L2  askAction and handoffAction look at the chat again on every action (no cached answer).
// Run: node tests/ext_safety_test.js
require('./shipmiracle_isolation').apply();
const fs = require('fs'), path = require('path'), { spawnSync } = require('child_process');
const W = require('./panel_live_world'); const D = require('./panel_cdp');
const world = W.make(null); W.enter(world);
const C = D.checker(), check = C.check;
const EXT = path.join(__dirname, '..', 'vscode-ext', 'shipmiracle-panel');
const SRC = n => fs.readFileSync(path.join(EXT, n), 'utf8');
const DATA = require('../vscode-ext/shipmiracle-panel/data.js'), REPORTS = require('../vscode-ext/shipmiracle-panel/reports.js'), STR = require('../vscode-ext/shipmiracle-panel/strings.js');

(async () => {
  // ---------- M2 ----------
  const mk = (name, f) => { const d = path.join(world.dev, name); fs.mkdirSync(path.join(d, 'docs'), { recursive: true }); spawnSync('git', ['init', '-q', '-b', 'main', d], { env: world.env }); f(d); return d; };
  const fifoOk = spawnSync('mkfifo', [path.join(world.root, 'probe.fifo')]).status === 0;
  const dz = '/dev/zero';
  mk('zero-app', d => { for (const f of ['docs/STATUS.md', 'CLAUDE.md', 'AGENTS.md', 'docs/FEATURE-IDEAS.md']) fs.symlinkSync(dz, path.join(d, f)); });
  if (fifoOk) mk('fifo-app', d => { for (const f of ['docs/STATUS.md', 'CLAUDE.md', 'AGENTS.md', 'docs/FEATURE-IDEAS.md']) spawnSync('mkfifo', [path.join(d, f)]); });
  mk('big-app', d => { fs.writeFileSync(path.join(d, 'docs', 'STATUS.md'), '## Next\n\n1. ' + 'x'.repeat(5 << 20)); fs.writeFileSync(path.join(d, 'CLAUDE.md'), 'Stack: web\n' + 'y'.repeat(3 << 20)); });
  mk('good-app', d => { fs.writeFileSync(path.join(d, 'docs', 'STATUS.md'), '## Next\n\n1. Ship the login screen\n'); fs.writeFileSync(path.join(d, 'docs', 'FEATURE-IDEAS.md'), '# Ideas\n\n- [ ] F1 an idea\n'); });
  // state-side files: health.json, away-decisions.jsonl as /dev/zero symlinks or FIFOs; hostile counts
  fs.mkdirSync(world.state, { recursive: true });
  fs.symlinkSync(dz, path.join(world.state, 'away-decisions.jsonl'));
  const rss0 = process.memoryUsage().rss, t0 = Date.now();
  const d1 = await DATA.collect();
  const dt = Date.now() - t0, grow = (process.memoryUsage().rss - rss0) / 1048576;
  const by = Object.fromEntries(d1.projects.map(p => [p.name, p]));
  check('collect() with /dev/zero symlinks (STATUS.md, CLAUDE.md, AGENTS.md, FEATURE-IDEAS.md, away-decisions.jsonl) and a 5 MB STATUS.md returns in under 5 s (' + dt + ' ms) and grows memory by under 100 MB (' + Math.round(grow) + ' MB)', dt < 5000 && grow < 100, dt + ' ms ' + grow + ' MB');
  check('...the hostile projects are listed with empty next / stack / ideas and the good project still reads its Next line and ideas', !!by['zero-app'] && by['zero-app'].next === '' && by['zero-app'].ideas.open.length === 0 && by['big-app'].next === '' && by['good-app'].next === 'Ship the login screen', JSON.stringify([by['zero-app'] && by['zero-app'].next, by['good-app'] && by['good-app'].next]));
  check('...the away-decisions.jsonl symlink to /dev/zero counts as 0', d1.guard.away === 0, String(d1.guard.away));
  if (fifoOk) {
    const t1 = Date.now(); const d2 = await DATA.collect(); const dt2 = Date.now() - t1;
    check('a FIFO as docs/STATUS.md, CLAUDE.md, AGENTS.md and FEATURE-IDEAS.md does not block (collect() ' + dt2 + ' ms), the project is listed', dt2 < 5000 && d2.projects.some(p => p.name === 'fifo-app' && p.next === ''), String(dt2));
    fs.rmSync(path.join(world.state, 'away-decisions.jsonl')); spawnSync('mkfifo', [path.join(world.state, 'away-decisions.jsonl')]); spawnSync('mkfifo', [path.join(world.state, 'health.json')]);
    const t3 = Date.now(); const d3 = await DATA.collect(); const dt3 = Date.now() - t3;
    check('a FIFO as health.json and away-decisions.jsonl does not block either (' + dt3 + ' ms): no Health block, away 0', dt3 < 5000 && d3.health === null && d3.guard.away === 0, String(dt3));
    fs.rmSync(path.join(world.state, 'health.json'));
  }
  fs.writeFileSync(path.join(world.state, 'health.json'), JSON.stringify({ ts: Date.now() / 1000, items: [], counts: { red: '<button class="btn primary" data-level="x" data-to="warn" data-armed="1">', amber: { a: 1 }, info: null } }));
  const d4 = await DATA.collect();
  check('M1: hostile health.json counts (strings with markup, objects, null) become numbers in collect()', d4.health && d4.health.counts.red === 0 && d4.health.counts.amber === 0 && d4.health.counts.info === 0, JSON.stringify(d4.health && d4.health.counts));
  fs.writeFileSync(path.join(world.state, 'health.json'), JSON.stringify({ ts: Date.now() / 1000, items: [], counts: { red: '2', amber: 1 } }));
  check('...and real numbers (also numeric strings) are kept', (await DATA.collect()).health.counts.red === 2);
  // the reader itself
  const rd = REPORTS.readText(path.join(world.dev, 'zero-app', 'CLAUDE.md')), big = REPORTS.readCapped(path.join(world.dev, 'big-app', 'CLAUDE.md'), 1 << 20);
  check('reports.readText: /dev/zero symlink -> "" ; readCapped: a 3 MB file over the cap -> not ok, big', rd === '' && big.ok === false && big.big === true);
  check('reports.readJson follows a symlinked dotfile (the owner\'s config) but refuses a device', (() => { const real = path.join(world.root, 'real.json'); fs.writeFileSync(real, '{"a":1}'); fs.symlinkSync(real, path.join(world.root, 'link.json')); return REPORTS.readJson(path.join(world.root, 'link.json')).a === 1 && REPORTS.readJson(dz) === null; })());
  const raw = ['data.js', 'extension.js', 'locations.js', 'panel.js', 'setup.js', 'ask.js'].map(f => [f, SRC(f)]).filter(([f, t]) => /fs\.readFileSync|fs\.readFile\(|createReadStream/.test(t.replace(/^\s*\/\/.*$/gm, '')));
  check('M2 source: no unbounded fs.readFileSync / readFile left in data.js, extension.js, locations.js, panel.js, setup.js, ask.js (reports.js readCapped is the one reader; scanFile in data.js streams transcripts with offsets)', raw.length === 0 || (raw.length === 1 && raw[0][0] === 'data.js' && (raw[0][1].match(/fs\.readFileSync/g) || []).length === 0), raw.map(r => r[0]).join());

  // ---------- M3 / L1 / L2: source level (the behaviour is exercised by ext_ideas_test, ext_handoff_test, ext_ask_test, ext_charter_test, ext_reports_test) ----------
  const ex = SRC('extension.js').replace(/^\s*\/\/.*$/gm, '');
  const sends = [...ex.matchAll(/\.sendText\(([^;]*?)\)\s*[;}]/g)].map(m => m[1].replace(/\s+/g, ' ').trim());
  const okSend = s => /^(prompt, false|ASK\.ASIDE_TEXT, false|HANDOFF_TEXT, true|line, runIt|runIt \? '\\u0005\\u0015' : '\\u0015', false|'\\u0015', false|'\\u001b', false|'\\u001b\[D'\.repeat\(Math\.min\(o\.back, 400\)\), false|'\/rename ' \+ p\.name)$/.test(s);
  check('M3: every sendText in extension.js is one of the known routes (chat prompt, /btw prefill, handoff, owner-terminal line, Ctrl-U, Esc, guarded /rename): ' + sends.length + ' calls', sends.length >= 6 && sends.every(okSend), JSON.stringify(sends.filter(s => !okSend(s))));
  check('M3: openChatWith puts the marker "' + STR.panelMarker.trim() + '" in front of every chat prompt, HANDOFF_TEXT starts with it, and the marker is one constant in strings.js', STR.panelMarker === '[panel] ' && /STR\.panelMarker \+ prompt0/.test(ex) && /HANDOFF_TEXT = STR\.panelMarker \+ /.test(ex) && (SRC('strings.js').match(/panelMarker/g) || []).length === 1);
  check("M3: the exact '/btw ' prefill is unchanged (starts with '/', no marker)", require('../vscode-ext/shipmiracle-panel/ask.js').ASIDE_TEXT === '/btw ');
  const re = new RegExp((/const APPROVAL_WORD = \/(.*)\/i;/.exec(SRC('extension.js')) || [, '$^'])[1], 'i');
  check('M3: /rename is skipped for names with an approval word (go, ok, start, implement, approve, yes, proceed ...) and still sent for ordinary names', ['go-app', 'ok', 'start-here', 'my-implement', 'approve_it', 'yes', 'proceed', 'x-go-y'].every(n => re.test(n)) && ['ideas', 'gopher', 'website', 'oklahoma', 'startup', 'notes', 'ask', 'shipm'].every(n => !re.test(n)), [...['gopher', 'startup', 'oklahoma'].filter(n => re.test(n))].join());
  check('M3: no chat-bound text names an approval word outside the marker where it can be avoided (the new-project and start-CR prompts were reworded)', !/only after I approve/.test(ex) && !/`Start \$\{cr\} now/.test(ex));
  check('re-review h: openChatWith sends Ctrl-U (a line clear) before the prefilled chat prompt', /open\.sendText\('\\u0015', false\); open\.sendText\(prompt, false\)/.test(ex));
  check('L1: ownerTerminal sends Ctrl-U (a line clear) before every prefilled line, and presses Enter ONLY for the Setup operations (kind "init"; owner decision 31 Oct 2026)', /const runIt = o\.run === true && o\.kind === 'init';\s*\n\s*term\.sendText\(runIt \? '\\u0005\\u0015' : '\\u0015', false\);[^\n]*\n\s*term\.sendText\(line, runIt\)/.test(ex));
  check('31 Oct: exactly one route asks for run:true (the Setup helper, kind "init"); every other ownerTerminal call says run:false', (ex.match(/\brun: true\b/g) || []).length === 1 && /kind: 'init', run: true/.test(ex));
  check('L2: askAction and handoffAction inspect the chat again on every action (no chatOf.get(t) || inspectChat)', !/chatOf\.get\(t\) \|\| await inspectChat/.test(ex) && (ex.match(/const ins = await inspectChat\(t\)/g) || []).length >= 2);
  world.cleanup();
  console.log(C.fails ? `\nFAILED: ${C.fails} of ${C.n}` : `\nALL PASS (${C.n})`); process.exit(C.fails ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
