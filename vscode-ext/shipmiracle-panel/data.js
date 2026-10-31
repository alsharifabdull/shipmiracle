// Data for the Shipmiracle panel. Pure Node, no dependencies; runnable on its own:  node data.js  → JSON.
// Sources (all local): <projects folder>/* git repos, ~/.local/state/shipmiracle (Claude hooks), Claude transcripts in
// ~/.claude/projects, plan usage cached by Claude Code in ~/.claude.json.
const fs = require('fs');
const os = require('os');
const path = require('path');
const crypto = require('crypto');
const { execFile } = require('child_process');

const HOME = os.homedir();
// Test-only overrides (tests/data_flow_test.js). Not SHIPMIRACLE_WS / SHIPMIRACLE_STATE: the Claude hooks read those.
const testEnv = k => process.env.SHIPMIRACLE_TEST === '1' ? process.env[k] : undefined;     // test-only overrides (SHIPMIRACLE_EXT_*) are read only when SHIPMIRACLE_TEST=1
const { DEV, WS, isHub, isProtected } = require('./locations');
const REPORTS = require('./reports');                        // Reports tab: the index <state>/v1/reports/index.json, read-only and size-capped
const DETAIL = require('./detail');
const TIDYX = require('./tidyx');                          // G2: the weekly tidy report (<state>/v1/tidy.json), cleaned and re-checked here; the card is drawn by tidyx.js
const PROPOSED = require('./proposed');                    // F5 Learn: proposed assets (plain text + the copy-only add command)
const INTERVIEW = require('./interview');                  // F6 mirror of the interview files inside a project                          // F9 card Details: the session-folder rule is shared (the transcript itself is read only by detail.js, only for an open card)
const STATE = testEnv('SHIPMIRACLE_EXT_STATE') || path.join(HOME, '.local', 'state', 'shipmiracle');
const CLAUDE_PROJECTS = path.join(HOME, '.claude', 'projects');

const git = (cwd, args) => new Promise(res => execFile('git', args, { cwd, timeout: 8000 }, (e, out) => res(e ? '' : String(out).trim())));
const readJSON = f => REPORTS.readJson(f);                  // capped, no symlink, no FIFO (reports.js)
const dayKey = t => { const d = new Date(t); return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0'); };
const today = () => dayKey(Date.now());
const weekKeys = () => { const k = new Set(); for (let i = 0; i < 7; i++) k.add(dayKey(Date.now() - i * 86400000)); return k; };

// ---- incremental token counting: each file is read once, then only its new bytes ----------------------
const cache = new Map();   // file -> { size, offset, rest, days: {day: tokens}, model, cwd }
function scanFile(file, parseLine) {
  let st; try { st = fs.statSync(file); } catch (e) { return null; }
  let c = cache.get(file);
  if (!c || st.size < c.size) { c = { size: 0, offset: 0, rest: '', days: {}, model: '', cwd: '' }; cache.set(file, c); }
  if (st.size > c.offset) {
    const fd = fs.openSync(file, 'r'); const len = st.size - c.offset; const buf = Buffer.alloc(len);
    fs.readSync(fd, buf, 0, len, c.offset); fs.closeSync(fd);
    const text = c.rest + buf.toString('utf8'); const lines = text.split('\n'); c.rest = lines.pop();
    for (const line of lines) { if (line) { try { parseLine(JSON.parse(line), c); } catch (e) { /* partial line */ } } }
    c.offset = st.size;
  }
  c.size = st.size;
  return c;
}
function claudeLine(r, c) {
  const m = r.message;
  if (r.type !== 'assistant' || !m || !m.usage) return;
  const u = m.usage;
  // FALLBACK ONLY (used when ledger.summary.json is missing or old): this count leaves cache reads out, and cache reads are ~97 % of the input
  // side, so it is far too low. The real figure is bin/shipm-ledger (see ledgerInfo); the panel labels this one 'estimate'.
  const n = (u.input_tokens || 0) + (u.output_tokens || 0) + (u.cache_creation_input_tokens || 0);   // cache reads excluded
  const d = dayKey(r.timestamp || Date.now());
  c.days[d] = (c.days[d] || 0) + n;
  if (m.model && !r.isSidechain) { c.model = m.model; c.modelAt = Date.parse(r.timestamp || 0) || 0; }
}
function walk(dir, out = [], depth = 0) {
  let es = []; try { es = fs.readdirSync(dir, { withFileTypes: true }); } catch (e) { return out; }
  for (const e of es) {
    const p = path.join(dir, e.name);
    if (e.isDirectory() && depth < 4) walk(p, out, depth + 1);
    else if (e.isFile() && e.name.endsWith('.jsonl')) out.push(p);
  }
  return out;
}
// ---- token ledger (bin/shipm-ledger, refreshed by the guard every 10 min): the summary counts cache reads; used while it is under 15 min old
function ledgerInfo() {
  const j = readJSON(path.join(STATE, 'ledger.summary.json'));
  const num = v => typeof v === 'number' && isFinite(v) && v >= 0 ? v : null;
  if (!j || typeof j !== 'object' || !j.today || !j.week || num(j.generated_at) == null) return { fresh: false, source: 'transcripts', why: 'missing' };
  const age = Math.round(Date.now() / 1000 - j.generated_at);
  if (age > 900) return { fresh: false, source: 'transcripts', why: 'old', ageS: age };
  const blk = b => ({ calls: num(b.calls) || 0, tokens: num(b.tokens) || 0, overCallsPct: num(b.share_calls_over_200k_pct), overTokensPct: num(b.share_tokens_over_200k_pct) });
  const by = {}; for (const [k, v] of Object.entries(j.by_project && typeof j.by_project === 'object' ? j.by_project : {})) if (v && num(v.today) != null) by[k] = { today: v.today, week: num(v.week) || 0 };
  return { fresh: true, source: 'ledger', ageS: age, today: blk(j.today), week: blk(j.week), byProject: by, resets: j.context_resets || null };
}
// ---- context size per chat (the context-nudge hook writes context.<session>.json on every owner message); only fresh ones (under 30 min)
function contextFiles() {
  const out = {};
  let fs_ = []; try { fs_ = fs.readdirSync(STATE).filter(f => /^context\.[A-Za-z0-9_-]{1,64}\.json$/.test(f)); } catch (e) { return out; }
  for (const f of fs_) {
    const j = readJSON(path.join(STATE, f)); if (!j || typeof j !== 'object') continue;
    const ts = typeof j.ts === 'number' ? j.ts : 0, tokens = j.tokens;
    if (typeof j.project !== 'string' || !j.project || typeof tokens !== 'number' || !isFinite(tokens) || tokens < 0) continue;
    if (Date.now() / 1000 - ts > 1800 || ts - Date.now() / 1000 > 300) continue;
    const level = j.level === 'strong' || j.level === 'soft' ? j.level : 'none';
    if (!out[j.project] || ts > out[j.project].ts) out[j.project] = { tokens: Math.round(tokens), level, ts };
  }
  return out;
}
const sum = (days, keys) => Object.entries(days).reduce((a, [d, n]) => a + (keys.has(d) ? n : 0), 0);

const claudeDirs = (dir, name) => DETAIL.claudeDirs(CLAUDE_PROJECTS, dir, name);   // the project's own folder plus any older path it lived at (e.g. a folder in the home folder)
// Real activity: seconds since the newest write in the project's latest Claude session (and its sub-agents), and per agent.
// The hooks only say "started"/"working"; a dead or starved agent never says "stopped", so the card trusts file writes too.
function claudeActivity(dir, name) {
  let best = null;
  for (const d of claudeDirs(dir, name)) {
    let files = []; try { files = fs.readdirSync(d).filter(f => f.endsWith('.jsonl')); } catch (e) { continue; }
    for (const f of files) { try { const m = fs.statSync(path.join(d, f)).mtimeMs; if (!best || m > best.m) best = { m, d, base: f.replace(/\.jsonl$/, '') }; } catch (e) { /* gone */ } }
  }
  if (!best) return { idle: null, agent: {} };
  let newest = best.m; const agent = {}; const sub = path.join(best.d, best.base, 'subagents');
  try {
    for (const g of fs.readdirSync(sub)) {
      const mt = g.match(/^agent-(.+)\.jsonl$/); if (!mt) continue;
      const t = fs.statSync(path.join(sub, g)).mtimeMs; agent[mt[1]] = t; if (t > newest) newest = t;
    }
  } catch (e) { /* no sub-agents */ }
  return { idle: Math.round((Date.now() - newest) / 1000), agent };
}
function claudeTokens(dir, name) {
  const t = today(), wk = weekKeys(); let day = 0, week = 0, model = '', modelAt = 0;
  for (const f of claudeDirs(dir, name).flatMap(d => walk(d))) {
    const c = scanFile(f, claudeLine); if (!c) continue;
    day += c.days[t] || 0; week += sum(c.days, wk);
    if (c.modelAt > modelAt) { model = c.model; modelAt = c.modelAt; }
  }
  return { day, week, model };
}
const safeReal = p => { try { return fs.realpathSync(p); } catch (e) { return p; } };

// Usage level of a meter: 0 low (<50 %), 1 mid (50-79), 2 high (80-94), 3 end (95+). null = no current reading.
const level = pct => pct == null ? null : pct >= 95 ? 3 : pct >= 80 ? 2 : pct >= 50 ? 1 : 0;

function plan() {
  // Claude 5-hour and week: the live numbers Claude Code hands its status line (the plan-capture hook), unless the
  // saved copy in ~/.claude.json is newer. Fable (and any other per-model weekly limit): only in that saved copy, which
  // the panel refreshes with Claude Code's own `/usage` command.
  const live = readJSON(path.join(STATE, 'plan.json'));
  const g = readJSON(path.join(HOME, '.claude.json')) || {};
  const u = g.cachedUsageUtilization || {}; const util = u.utilization || {};
  const cachedAt = u.fetchedAtMs || 0, liveAt = live && live.rate_limits ? live.at * 1000 : 0;
  const limits = Array.isArray(util.limits) ? util.limits : [];
  const iso = r => r.resets_at ? new Date(r.resets_at > 1e12 ? r.resets_at : r.resets_at * 1000).toISOString() : null;
  const meter = (id, label, pct, resets, at, source) => {
    const passed = !!resets && Date.parse(resets) < Date.now();   // its window already reset: the old number no longer applies
    const v = passed || pct == null ? null : Math.round(pct);
    return { id, label, pct: v, resets, at, source, lvl: level(v), stale: passed };
  };
  const unscoped = kind => limits.find(l => l.kind === kind && !(l.scope && (l.scope.model || l.scope.surface)));
  const useLive = liveAt && liveAt >= cachedAt;
  const lv = k => (useLive && live.rate_limits[k]) ? live.rate_limits[k] : null;
  const cache = (kind, legacy) => { const l = unscoped(kind); if (l) return { pct: l.percent, resets: l.resets_at };
    return util[legacy] ? { pct: util[legacy].utilization, resets: util[legacy].resets_at } : null; };
  const out = [];
  const five = lv('five_hour') ? meter('five', 'Claude · 5-hour', lv('five_hour').used_percentage, iso(lv('five_hour')), liveAt, 'live')
    : cache('session', 'five_hour') && (c => meter('five', 'Claude · 5-hour', c.pct, c.resets, cachedAt, 'saved'))(cache('session', 'five_hour'));
  const week = lv('seven_day') ? meter('week', 'Claude · week', lv('seven_day').used_percentage, iso(lv('seven_day')), liveAt, 'live')
    : cache('weekly_all', 'seven_day') && (c => meter('week', 'Claude · week', c.pct, c.resets, cachedAt, 'saved'))(cache('weekly_all', 'seven_day'));
  if (five) out.push(five); if (week) out.push(week);
  const seen = new Set();
  for (const l of limits) {   // per-model weekly limits, e.g. Fable
    const name = l.kind === 'weekly_scoped' && l.scope && l.scope.model && l.scope.model.display_name;
    if (name && !seen.has(name)) { seen.add(name); out.push(meter('model-' + name.toLowerCase(), name + ' · week', l.percent, l.resets_at, cachedAt, 'saved')); }
  }
  for (const [k, name] of [['seven_day_opus', 'Opus'], ['seven_day_sonnet', 'Sonnet']]) {
    const r = lv(k); if (r && !seen.has(name)) { seen.add(name); out.push(meter('model-' + name.toLowerCase(), name + ' · week', r.used_percentage, iso(r), liveAt, 'live')); }
  }
  const claudeAt = Math.max(useLive ? liveAt : 0, cachedAt);
  return { meters: out, claude: { at: claudeAt || null, cachedAt, liveAt } };
}

function nextLine(dir) {
  for (const f of ['docs/STATUS.md', 'Docs/STATUS.md']) {
    const t = REPORTS.readText(path.join(dir, f)); if (!t) continue;
    const m = t.match(/##\s*Next\s*\n+([\s\S]*?)(\n##|$)/);
    if (m) { const first = m[1].split('\n').map(s => s.trim()).find(s => /^(\d+\.|-|\*)\s+[^(\s]/.test(s)); if (first) return first.replace(/^(\d+\.|-|\*)\s+/, '').replace(/\*\*/g, '').replace(/`/g, '').slice(0, 110); }
  }
  return '';
}
function stackOf(dir) {
  const rd = f => REPORTS.readText(path.join(dir, f));
  // CLAUDE.md first (migrated projects: managed standard block or a Stack rules line), AGENTS.md for one release
  const c = rd('CLAUDE.md'), ag = rd('AGENTS.md');
  const t = (/SHIPMIRACLE-STANDARD BEGIN|Stack rules — /.test(c) ? c : '') + '\n' + ag + (c && !/SHIPMIRACLE-STANDARD BEGIN|Stack rules — /.test(c) ? '\n' + c : '');
  const m = t.match(/Stack rules — (\w+)/);
  if (m) return { Web: 'web', iOS: 'ios', Python: 'python', API: 'api', Home: 'home', Notes: 'notes', Other: 'other' }[m[1]] || m[1].toLowerCase();
  const has = f => fs.existsSync(path.join(dir, f));
  if (/Home Assistant/i.test(t)) return 'home';
  if (fs.readdirSync(dir).some(f => f.endsWith('.xcodeproj')) || has('Package.swift')) return 'ios';
  if (has('package.json')) return 'web';
  if (has('pyproject.toml') || has('requirements.txt')) return 'python';
  return '';
}
const shortModel = m => !m ? '' : /opus/i.test(m) ? 'opus' : /sonnet/i.test(m) ? 'sonnet' : /haiku/i.test(m) ? 'haiku' : /fable/i.test(m) ? 'fable' : m;

// Feature ideas of one project: docs/FEATURE-IDEAS.md (written by bin/idea). Done/dropped are only counted.
function readIdeas(dir) {
  const out = { open: [], evaluated: [], done: 0, dropped: 0 };
  const t = REPORTS.readText(path.join(dir, 'docs', 'FEATURE-IDEAS.md')); if (!t) return out;
  let sec = 'Open', last = null;
  for (const line of t.split('\n')) {
    const h = line.match(/^## (.*)$/); if (h) { sec = h[1].trim(); last = null; continue; }
    const m = line.match(/^- \[( |x|-)\] (?:(F\d+) · )?(?:(\d{4}-\d{2}-\d{2}) · )?(.*)$/);
    if (m) {
      const text = m[4].trim();
      last = { id: m[2] || '', date: m[3] || '', text: text.replace(/\s*#\w+/g, '').trim(), tags: text.match(/#\w+/g) || [], verdict: '' };
      if (sec === 'Open') out.open.push(last); else if (sec === 'Evaluated') out.evaluated.push(last); else if (m[1] === 'x') out.done++; else out.dropped++;
      continue;
    }
    if (last && /^\s+↳ verdict:/.test(line)) last.verdict = line.replace(/^\s+↳ verdict:\s*/, '').trim();
  }
  return out;
}
const heldNames = () => { try { return REPORTS.readText(path.join(WS, 'config', 'ci-hold.txt')).split('\n').map(s => s.trim()).filter(s => s && !s.startsWith('#')); } catch (e) { return []; } };

// Choices Claude took while the owner was away (the keep-going hook -> away-decisions.jsonl) that were not reviewed yet.
function awayCount() {
  let seen = 0; try { seen = parseFloat(REPORTS.readText(path.join(STATE, 'away-reviewed'), 64)) || 0; } catch (e) { /* never reviewed */ }
  const t = REPORTS.readText(path.join(STATE, 'away-decisions.jsonl'), 4 << 20); if (!t) return 0;
  return t.split('\n').filter(l => { try { return JSON.parse(l).ts > seen; } catch (e) { return false; } }).length;
}

// ---- team flow (card v2): everything below is derived from files the gate already writes ----------------------
const LEVELS = ['strict', 'warn', 'off'];
const REFUSAL_KINDS = ['plan_without_architect', 'edit_outside_team', 'bash_write_outside_team', 'done_without_qa', 'qa_failed', 'qa_no_verdict', 'outside_team', 'gate_tamper', 'agent_rule_refused'];
// Same tables as shipmiracle/agents.py (a test keeps ALIASES equal; the resolve cases in tests/fixtures/agents/resolve_cases.json run through both).
const ALIASES = {
  'product-analyst': 'scoper', 'solution-architect': 'planner', 'frontend-engineer': 'builder-frontend', 'backend-engineer': 'builder-backend',
  'data-integration-engineer': 'builder-backend', 'devops-sre': 'builder-ops', 'qa-engineer': 'verifier', 'independent-reviewer': 'reviewer',
  'security-reviewer': 'reviewer', 'ux-designer': 'designer'
};
const ALIAS_LENS = { 'independent-reviewer': 'correctness', 'security-reviewer': 'risk' };
const DEFAULT_ROLE = {
  scoper: 'scope', planner: 'plan', builder: 'build', 'builder-frontend': 'build', 'builder-backend': 'build', 'builder-ops': 'build', verifier: 'test',
  reviewer: 'review', designer: 'design', reporter: 'report', 'general-purpose': 'build', Plan: 'plan', Explore: 'scope', 'claude-code-guide': 'support',
  'statusline-setup': 'support', 'engineering-lead': 'route'
};
const BUILTINS = new Set(['general-purpose', 'Plan', 'Explore', 'claude-code-guide', 'statusline-setup', 'engineering-lead']);
const ROLES = new Set(['plan', 'build', 'test', 'review', 'scope', 'design', 'route', 'support', 'report']);
const STEPS = ['scope', 'plan', 'ok', 'build', 'qa', 'review'];
const ROLE_STAGE = { scope: 'scope', design: 'plan', plan: 'plan', build: 'build', test: 'qa', review: 'review' };
const own = (o, k) => o && typeof o === 'object' && Object.prototype.hasOwnProperty.call(o, k) ? o[k] : undefined;   // name-keyed lookups: a project called constructor or __proto__ must not hit Object.prototype
const secs = t => { const n = Number(t) || 0; return n > 1e12 ? n / 1000 : n; };          // a ts in seconds or milliseconds
const safeName = t => typeof t === 'string' && t && !t.includes('/') && !t.includes('..');

function levelOf(cfg, name) {
  const projs = cfg && typeof cfg.projects === 'object' && cfg.projects ? cfg.projects : {};
  const v = Object.prototype.hasOwnProperty.call(projs, name) ? projs[name] : (cfg && cfg.default);
  return LEVELS.includes(v) ? v : 'strict';                                                // the gate also falls back to strict
}
function readSmall(file) {                                       // regular files only, at most 64 KB: a FIFO, /dev/zero or a huge file must not hang the panel
  let fd = -1;
  try {
    fd = fs.openSync(file, fs.constants.O_RDONLY | fs.constants.O_NONBLOCK);   // O_NONBLOCK: opening a FIFO must not wait for a writer
    if (!fs.fstatSync(fd).isFile()) return '';
    const buf = Buffer.alloc(64 * 1024); const n = fs.readSync(fd, buf, 0, buf.length, 0);
    return buf.toString('utf8', 0, n);
  } catch (e) { return ''; } finally { if (fd >= 0) try { fs.closeSync(fd); } catch (e) { /* closed */ } }
}
// Where an agent type comes from; same order and result as shipmiracle/agents.py resolve(): project file > user file (~/.claude/agents) > plugin (`plugin:name`
// only) > builtin / alias. The same name is never merged. null when nothing matches. Role = the file's "Flow role:" line (valid word) else the default.
const NAME_RE = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/, PLUGIN_RE = /^([A-Za-z0-9][A-Za-z0-9._-]{0,63}):([A-Za-z0-9][A-Za-z0-9._-]{0,127})$/;
const userHome = () => testEnv('SHIPMIRACLE_HOME') || HOME;
function pluginHas(plugin, agent) {
  const root = path.join(userHome(), '.claude', 'plugins', 'cache');
  try {
    for (const mk of fs.readdirSync(root)) for (const ver of fs.readdirSync(path.join(root, mk, plugin))) {
      if (fs.existsSync(path.join(root, mk, plugin, ver, 'agents', agent + '.md'))) return true;
    }
  } catch (e) { /* no such plugin */ }
  return false;
}
function resolveAgent(dir, type) {
  if (typeof type !== 'string' || type.length > 192 || type.includes('\0')) return null;
  const NAME_LINE = /^name: (['"]?)([a-z][a-z0-9]*(?:-[a-z0-9]+)*)\1$/m, NAMEY = /^[ \t]*['"]?name['"]?[ \t]*:/mg;
  const findFile = dir_ => {                                                    // P3 R6: Claude Code keys an agent on its frontmatter name, not on the file name
    let names; try { names = fs.readdirSync(dir_).filter(f => f.endsWith('.md') && !f.startsWith('.')).sort(); } catch (e) { return null; }
    const hit = []; for (const f of names) {
      const t = readSmall(path.join(dir_, f)); if (!t) continue;
      const loose = (t.match(NAMEY) || []).length, m = t.match(NAME_LINE), stem = f.slice(0, -3);
      const keys = loose === 0 ? [stem] : (loose === 1 && m && !/\r|^\ufeff/.test(t) ? [m[2]] : [stem, ...[...t.matchAll(/^[ \t]*['"]?name['"]?[ \t]*:[ \t]*['"]?([A-Za-z0-9._-]+)/mg)].map(x => x[1])]);
      if (keys.includes(type)) hit.push({ f, ok: loose === 0 || (loose === 1 && !!m && keys[0] === type) });
    }
    hit.sort((a, b) => (b.f === type + '.md') - (a.f === type + '.md'));
    return hit.length ? path.join(dir_, hit[0].f) : null;
  };
  const fromFile = (layer, file) => {
    if (!file) return null;
    const t = readSmall(file); if (!t) return null;
    const r = t.match(/^Flow role:[ \t]*(\w+)/m), m = t.match(/^model:[ \t]*(\S+)/m), rl = r ? r[1].toLowerCase() : '';
    return { name: type, layer, path: file, role: ROLES.has(rl) ? rl : (own(DEFAULT_ROLE, type) || 'support'), model: m ? shortModel(m[1]) : '', alias_of: null, lens: null };
  };
  if (NAME_RE.test(type)) {
    let r = dir ? fromFile('project', findFile(path.join(dir, '.claude', 'agents'))) : null;
    if (!r) r = fromFile('user', findFile(path.join(userHome(), '.claude', 'agents')));
    if (r) return r;
  }
  const pm = PLUGIN_RE.exec(type);
  if (pm) return pluginHas(pm[1], pm[2]) ? { name: type, layer: 'plugin', path: null, role: 'support', model: '', alias_of: null, lens: null } : null;
  if (own(ALIASES, type)) { const to = ALIASES[type]; return { name: type, layer: 'alias', path: null, role: DEFAULT_ROLE[to], model: '', alias_of: to, lens: own(ALIAS_LENS, type) || null }; }
  if (BUILTINS.has(type) || own(DEFAULT_ROLE, type)) return { name: type, layer: 'builtin', path: null, role: own(DEFAULT_ROLE, type) || 'support', model: '', alias_of: null, lens: null };
  return null;
}
function agentFile(dir, type) {                                                            // {role, model, label} for the flow strip; unknown names keep the old engineer heuristic
  const r = safeName(type) ? resolveAgent(dir, type) : null;
  const role = r ? r.role : (/engineer|sre|developer|implement/.test(type || '') ? 'build' : '');
  return { role, model: r ? r.model : '', label: r && r.layer === 'alias' ? `${type} (${r.alias_of})` : (type || '') };
}
// flow-events.jsonl: the last 512 KB, parsed once per change (shared by the refusal count and the plan-by-architect check)
let evCache = { key: '', list: [] };
function readEvents() {
  const f = path.join(STATE, 'flow-events.jsonl'); let st; try { st = fs.statSync(f); } catch (e) { return []; }
  const key = st.size + ':' + st.mtimeMs; if (evCache.key === key) return evCache.list;
  const list = [];
  try {
    const fd = fs.openSync(f, 'r'); const len = Math.min(st.size, 512 * 1024); const buf = Buffer.alloc(len);
    fs.readSync(fd, buf, 0, len, st.size - len); fs.closeSync(fd);
    const lines = buf.toString('utf8').split('\n'); if (st.size > len) lines.shift();           // the first line of a tail may be cut
    for (const line of lines) { if (!line) continue; try { const e = JSON.parse(line); if (e && typeof e === 'object') list.push(e); } catch (x) { /* junk line */ } }
  } catch (e) { /* unreadable */ }
  evCache = { key, list }; return list;
}
// project id (shipmiracle/projects.py project_id): first 12 hex of sha256("shipmiracle-project:" + realpath)
const pidOf = real => crypto.createHash('sha256').update('shipmiracle-project:' + real).digest('hex').slice(0, 12);
// v1/events.jsonl (shipmiracle.events): the last 512 KB, parsed once per change. Only `stage.refused` is read here (P5c: the playbook gate's refusals).
let ev1Cache = { key: '', list: [] };
function readV1Events() {
  const f = path.join(STATE, 'v1', 'events.jsonl'); let st; try { st = fs.statSync(f); } catch (e) { return []; }
  const key = st.size + ':' + st.mtimeMs; if (ev1Cache.key === key) return ev1Cache.list;
  const list = [];
  try {
    const fd = fs.openSync(f, 'r'); const len = Math.min(st.size, 512 * 1024); const buf = Buffer.alloc(len);
    fs.readSync(fd, buf, 0, len, st.size - len); fs.closeSync(fd);
    const lines = buf.toString('utf8').split('\n'); if (st.size > len) lines.shift();
    for (const line of lines) { if (!line || line.indexOf('stage.refused') < 0) continue; try { const e = JSON.parse(line); if (e && e.kind === 'stage.refused' && typeof e.project === 'string') list.push(e); } catch (x) { /* junk line */ } }
  } catch (e) { /* unreadable */ }
  ev1Cache = { key, list }; return list;
}
function refusalsToday(names) {                                     // since local midnight, exact kinds only (not the _warned / _capped variants); `stage.refused` (P5c) counts too
  const mid = new Date(); mid.setHours(0, 0, 0, 0); const since = mid.getTime() / 1000; const byProj = Object.create(null);
  for (const e of readEvents()) if (secs(e.ts) >= since && REFUSAL_KINDS.includes(e.event) && typeof e.project === 'string') byProj[e.project] = (byProj[e.project] || 0) + 1;
  if (names && names.length) {
    const byPid = Object.create(null); for (const n of names) byPid[pidOf(safeReal(path.join(DEV, n)))] = n;
    for (const e of readV1Events()) { const n = byPid[e.project]; if (n && secs(e.ts) >= since) byProj[n] = (byProj[n] || 0) + 1; }
  }
  return byProj;
}
// Was the newest plan of this session presented without the architect? Newest plan_ok / plan_without_architect[_warned|_capped] event decides; null = no such event.
function planEvent(sid) {
  let last = null;
  for (const e of readEvents()) if (e.session === sid && (e.event === 'plan_ok' || /^plan_without_architect(_warned|_capped)?$/.test(e.event || ''))) last = e;
  return last ? last.event !== 'plan_ok' : null;
}
// `bin/shipm agents check --project <dir> --json` once per change, cached by the project's agent files (names + mtimes) and the manifest mtime.
// Any error (no python, timeout, bad JSON) falls back to bin/agent-check on the project files (the old check); the render never waits more than 3 s.
const teamCache = new Map();   // dir -> { key, out }
const MANIFEST = () => path.join(STATE, 'v1', 'agents.json');
const PRIV = new Set(['plan', 'test', 'review', 'report']);
function teamFromJson(j) {                                       // {count, bad, dod, untrusted} from the check output; null when it is not the expected shape
  if (!j || typeof j !== 'object' || !Array.isArray(j.problems) || !Array.isArray(j.agents)) return null;
  const line = p => `${p.file}: ${p.text}`;
  const fname = a => typeof a.path === 'string' && a.path ? path.basename(a.path, '.md') : String(a.name);
  const untr = j.agents.filter(a => a && a.layer === 'project' && PRIV.has(a.claimed) && a.trusted === false);
  const probs = j.problems.filter(p => p && typeof p === 'object' && typeof p.text === 'string');
  return { count: j.agents.length,
    bad: probs.filter(p => p.kind === 'model').map(line).slice(0, 20),                                   // model-rule problems only (exit 1)
    dod: probs.filter(p => p.kind === 'dod').map(line).slice(0, 20),                                     // missing DoD block / maxTurns (warn level)
    untrusted: untr.map(fname).slice(0, 20),                                                              // by FILE name (shipm agents activate takes the file name), not by the frontmatter name
    untrustedInfo: untr.slice(0, 20).map(a => ({ name: fname(a), role: String(a.claimed), shadow: !!a.shadow, mismatch: !!a.mismatch || String(a.name) !== fname(a) })) };
}
function teamFallback(dir, files) {
  return new Promise(res => execFile(path.join(WS, 'bin', 'agent-check'), files.map(f => path.join('.claude', 'agents', f)), { cwd: dir, timeout: 8000 }, (e, out) => {
    const text = String(out || (e && e.stdout) || '');
    const lines = e && (e.code === 1 || e.code === 3) ? text.split('\n').map(s => s.trim()).filter(Boolean) : [];   // other errors (no python, timeout): stay quiet
    res({ count: files.length, bad: lines.filter(l => !l.includes(': [dod] ')).slice(0, 20), dod: lines.filter(l => l.includes(': [dod] ')).map(l => l.replace(': [dod] ', ': ')).slice(0, 20), untrusted: [] });
  }));
}
function teamOf(dir) {
  const ad = path.join(dir, '.claude', 'agents'); let files = [];
  try { files = fs.readdirSync(ad).filter(f => f.endsWith('.md')).sort(); } catch (e) { /* no agents folder: user-level agents may still count */ }
  let key = ''; for (const f of files) { try { key += f + ':' + fs.statSync(path.join(ad, f)).mtimeMs + ';'; } catch (e) { key += f + ';'; } }
  try { key += 'M' + fs.statSync(MANIFEST()).mtimeMs; } catch (e) { key += 'M-'; }
  const hit = teamCache.get(dir); if (hit && hit.key === key && Date.now() < hit.until) return Promise.resolve(hit.out);
  const done = (out, ttl) => { teamCache.set(dir, { key, out, until: Date.now() + (ttl || 1e12) }); return out; };   // a fallback result is kept 5 min, then Shipmiracle is tried again
  return new Promise(res => {
    const fall = () => (files.length ? teamFallback(dir, files) : Promise.resolve({ count: 0, bad: [], dod: [], untrusted: [] })).then(o => res(done(o, 300000)));
    try {
      execFile(path.join(WS, 'bin', 'shipm'), ['agents', 'check', '--project', dir, '--json'], { timeout: 3000, maxBuffer: 1 << 20, env: process.env }, (e, out) => {
        let t = null;
        if (!e || e.code === 1 || e.code === 3) { try { t = teamFromJson(JSON.parse(String(out || (e && e.stdout) || ''))); } catch (x) { t = null; } }   // exit 1/3 = problems found, JSON still printed
        if (t) res(done(t)); else fall();
      });
    } catch (e) { fall(); }
  });
}
// ---- playbook / change requests / autopilot (P5c data contract; the UI is P7): `bin/shipm report panel --project <dir>` once per change -------------------
// p.playbook {type, level, autopilot, trusted, valid} | p.cr [{id, title, status, stage, lane, label, verdict, waiting_on}] (<= 5) | p.stageLabels | p.nextAction |
// p.lastVerdict {stage, word, counts, report} | p.autopilot (shipmiracle.autopilot.state.snapshot). A project with no .shipmiracle folder and no autopilot state file gets null everywhere
// and no process is started. Any error (older workspace without the command, no python, timeout, bad JSON) also gives null.
const NO_PB = Object.freeze({ playbook: null, cr: null, stageLabels: null, nextAction: null, lastVerdict: null, autopilot: null, aside: null, toolbox: null, proposed: [], interview: null, unread: '', release: null, history: null });
// Panel v3 task 4b: `shipm report panel` also carries remote={state:'on'|'off'|'unknown'} (top level, read-only) and ask={inbox:true,questions_today,limit,notes,last:{title,path,ts}|null} (only for the registered ask
// project). Both are cleaned here; anything unexpected is dropped (remote -> 'unknown', ask -> absent). The last remote answer is kept for the Setup tab.
let remoteSeen = 'unknown';
const cleanAsk = a => {
  if (!a || typeof a !== 'object' || a.inbox !== true) return null;
  const n = (v, max) => Number.isInteger(v) && v >= 0 ? Math.min(v, max) : 0, one = (v, k) => (typeof v === 'string' ? v : '').replace(/[\u0000-\u001f\u007f-\u009f\u2028\u2029]+/g, ' ').trim().slice(0, k);
  const l = a.last && typeof a.last === 'object' ? { title: one(a.last.title, 80), path: one(a.last.path, 120), ts: Number.isFinite(Number(a.last.ts)) ? Math.floor(Number(a.last.ts)) : 0 } : null;
  const lim = Number.isInteger(a.limit) && a.limit >= 1 && a.limit <= 200 ? a.limit : 20;       // the config key ask.daily_limit (1-200); 20 = the default when the CLI gives nothing usable
  return { inbox: true, model_supported: a.model_supported === true, questions_today: n(a.questions_today, 1000), limit: lim, notes: n(a.notes, 100000), last: l && l.path ? l : null };
};

// F5-F8 fields of `shipm report panel` (shipmiracle/report/panel.py): aside {on,since,note,canAside,reason,backOnList}, unread {new,why}, toolbox {count,changed,assets[]}, interview {status,mode,n,total,draft}, caps {toolbox,interview,aside,unread}.
// Everything is cleaned here (types, lengths, enums); anything unexpected is dropped. `caps` says what this CLI can do: a UI part is shown only when its flag is true (never guessed).
const txt1 = (v, n) => DETAIL.sanitize(v, n);
const int0 = (v, max) => Number.isInteger(v) && v >= 0 ? Math.min(v, max) : 0;
const cleanAside = a => !a || typeof a !== 'object' ? null : { on: a.on === true, since: int0(a.since, 4e10), note: txt1(a.note, 120), canAside: a.canAside === true, reason: txt1(a.reason, 120), backOnList: txt1(a.backOnList, 120) };
const cleanToolbox = t => {
  if (!t || typeof t !== 'object') return null;
  const assets = (Array.isArray(t.assets) ? t.assets : []).slice(0, 100).filter(x => x && typeof x === 'object' && typeof x.path === 'string' && x.path)
    .map(x => ({ path: txt1(x.path, 200), stage: txt1(x.stage, 20), stageLabel: txt1(x.stageLabel, 30), purpose: txt1(x.purpose, 120), status: ['ok', 'changed', 'missing'].includes(x.status) ? x.status : 'ok' }));
  return { count: int0(t.count, 100000), changed: int0(t.changed, 100000), assets };
};
const cleanInterview = i => {
  if (!i || typeof i !== 'object' || !['asking', 'paused', 'draft', 'done', 'error'].includes(i.status)) return null;
  return { status: i.status, mode: i.mode === 'long' ? 'long' : 'short', n: int0(i.n, 99), total: int0(i.total, 99), draft: i.draft === true, question: txt1(i.question, 200), recommended: txt1(i.recommended, 200),
    answered: int0(i.answered, 99), assumed: (Array.isArray(i.assumed) ? i.assumed : []).slice(0, 10).map(x => txt1(typeof x === 'string' ? x : '', 80)).filter(Boolean), prototype: i.prototype === true };
};
const cleanCaps = c => ({ toolbox: !!c && c.toolbox === true, interview: !!c && c.interview === true, aside: !!c && c.aside === true, unread: !!c && c.unread === true, release: !!c && c.release === true });
let capsSeen = { toolbox: false, interview: false, aside: false, unread: false, release: false };
// Two-level timeline (caps.release): release {last, working, since} and history[] are cleaned by timeline.js. The answer depends on git tags, packed refs, the version file and the commit count since the last tag,
// so those files are part of the cache key below (a stat each, nothing is read).
const TLM = require('./timeline');
const versionFiles = dir => { const l = ['package.json', 'VERSION', 'release/VERSION', 'pyproject.toml'].map(f => path.join(dir, f)); try { for (const n of fs.readdirSync(dir)) if (/\.xcodeproj$/.test(n)) l.push(path.join(dir, n, 'project.pbxproj')); } catch (e) { /* unreadable folder: no Xcode file */ } return l; };
const tlFiles = dir => [path.join(dir, '.git', 'packed-refs'), path.join(dir, '.git', 'refs', 'tags'), path.join(dir, '.git', 'logs', 'HEAD'), ...versionFiles(dir)];
const pbCache = new Map();   // dir -> { key, out, until }
const stamp = f => { try { const st = fs.statSync(f); return st.mtimeMs + ':' + st.size; } catch (e) { return '-'; } };
// The capability flags describe the CLI, not a project: read them once (any registered project dir will do), so cards without a playbook still get 'Describe your work'. A failed read is retried after 60 s.
let capsProbe = null, capsProbeAt = 0;
function probeCaps(dir) {
  if (capsProbe && (capsProbeAt === 0 || Date.now() < capsProbeAt)) return capsProbe;
  capsProbeAt = Date.now() + 60000;
  return capsProbe = new Promise(res => {
    try {
      execFile(path.join(WS, 'bin', 'shipm'), ['report', 'panel', '--project', dir], { timeout: 3000, maxBuffer: 1 << 20, env: process.env }, (e, out) => {
        let j = null; if (!e) { try { j = JSON.parse(String(out)); } catch (x) { j = null; } }
        if (j && typeof j === 'object' && j.v === 1 && j.caps) { const c = cleanCaps(j.caps); for (const k of Object.keys(c)) if (c[k]) capsSeen[k] = true; capsProbeAt = 0; }
        res();
      });
    } catch (e) { res(); }
  });
}
function playbookOf(dir) {
  const real = safeReal(dir); const pid = pidOf(real);
  const apFile = path.join(STATE, 'v1', 'autopilot', pid + '.json');
  const hasAp = fs.existsSync(apFile);
  if (!hasAp && !fs.existsSync(path.join(dir, '.shipmiracle'))) return probeCaps(dir).then(() => ({ ...NO_PB }));
  const key = [path.join(dir, '.shipmiracle', 'playbook.json'), path.join(dir, '.shipmiracle', 'work.json'), path.join(STATE, 'v1', 'cr', pid + '.jsonl'), apFile, path.join(WS, 'config', 'flow.json'), path.join(STATE, 'plan.json'), path.join(process.env.CLAUDE_CONFIG_DIR || path.join(HOME, '.claude'), 'settings.json'), path.join(DEV, 'ask', 'docs', 'notes'), path.join(STATE, 'v1', 'aside.json'), path.join(STATE, 'v1', 'seen.json'), path.join(STATE, path.basename(dir) + '.json'), path.join(dir, '.shipmiracle', 'playbook.interview.json'), path.join(dir, '.shipmiracle', 'playbook.draft.md'), ...tlFiles(dir)].map(stamp).join('|');   // aside / seen / the chat's state file: F7 and F8 follow them at once
  const hit = pbCache.get(dir); if (hit && hit.key === key && Date.now() < hit.until) return Promise.resolve(hit.out);
  const done = (out, ttl) => { pbCache.set(dir, { key, out, until: Date.now() + ttl }); return out; };
  return new Promise(res => {
    try {
      execFile(path.join(WS, 'bin', 'shipm'), ['report', 'panel', '--project', dir], { timeout: 3000, maxBuffer: 1 << 20, env: process.env }, (e, out) => {
        let j = null;
        if (!e) { try { j = JSON.parse(String(out)); } catch (x) { j = null; } }
        if (j && typeof j === 'object' && j.v === 1 && j.caps) { const c = cleanCaps(j.caps); for (const k of Object.keys(c)) if (c[k]) capsSeen[k] = true; }
        if (j && typeof j === 'object' && j.v === 1) { remoteSeen = j.remote && ['on', 'off'].includes(j.remote.state) ? j.remote.state : 'unknown'; }
        if (j && typeof j === 'object' && j.v === 1) res(done({ ...(cleanAsk(j.ask) ? { ask: cleanAsk(j.ask) } : {}), playbook: j.playbook || null, cr: Array.isArray(j.cr) && j.playbook ? j.cr.slice(0, 5) : null, stageLabels: j.stageLabels || null, nextAction: typeof j.nextAction === 'string' ? j.nextAction : null,
          lastVerdict: j.lastVerdict || null, autopilot: j.autopilot && typeof j.autopilot === 'object' ? j.autopilot : null,
          aside: cleanAside(j.aside), toolbox: cleanToolbox(j.toolbox), proposed: Array.isArray(j.proposed_assets) ? j.proposed_assets.slice(0, 100) : [], interview: cleanInterview(j.interview), unread: j.unread && j.unread.new === true && (j.unread.why === 'turn' || j.unread.why === 'wait') ? j.unread.why : '', release: TLM.cleanRelease(j.release), history: TLM.cleanHistory(j.history), caps: cleanCaps(j.caps) }, hasAp ? 15000 : 600000));
        else res(done({ ...NO_PB }, 60000));
      });
    } catch (e) { res({ ...NO_PB }); }
  });
}
const emptyFlow = () => ({ qaVerdict: '', qaCounts: '', qaAt: 0, stage: '', steps: { scope: 'next', plan: 'next', ok: 'next', build: 'next', qa: 'next', review: 'next' }, actors: [], plannedBy: '', builtBy: '', qaBy: '', qaState: '',
  plannedByLabel: '', running: [], actorRunning: false, planNotByArchitect: false, outside: [], integrity: '', bypass: false, refusalsToday: 0, mismatch: false, planned: '', built: '', qa: false });

// QA verdict from the gate's session state. qa_runs (newest cohort since the last build: the newest run plus runs that overlapped it) mirrors the flow gate's qa_cohort.
function qaVerdictOf(j, build) {
  const runs = (Array.isArray(j.qa_runs) ? j.qa_runs : []).filter(r => r && typeof r === 'object' && Number(r.ts) > 0).sort((a, b) => a.ts - b.ts);
  if (!runs.length || !(build > 0)) return { state: '' };                              // old state file: the caller keeps ran/stale/none
  const live0 = runs.filter(r => r.ts >= build), known = live0.filter(r => r.verdict), live = known.length ? known : live0;   // a verdict-less run never supersedes a known verdict
  if (!live.length) return { state: 'stale', verdict: '', counts: '', at: 0 };
  const cohort = [live[live.length - 1]]; let lo = Number(cohort[0].start) || cohort[0].ts;
  for (const r of live.slice(0, -1).reverse()) if (r.ts >= lo) { cohort.unshift(r); lo = Math.min(lo, Number(r.start) || r.ts); }
  const bad = cohort.filter(r => ['FAIL', 'BLOCKED', 'NOT TESTED'].includes(r.verdict)).pop();
  const pick = bad || cohort[cohort.length - 1], ev = typeof pick.evidence === 'string' ? pick.evidence : '';
  const counts = /\d/.test(ev) ? ev.slice(0, 120) : '';
  if (bad) return { state: 'failed', verdict: bad.verdict, counts, at: bad.ts };
  if (cohort.every(r => r.verdict === 'PASS')) return { state: 'passed', verdict: 'PASS', counts, at: pick.ts };
  return { state: 'ran', verdict: '', counts: '', at: pick.ts };
}

// One project's flow. j = newest flow.<sid>.json (or {}), all inputs already read.
function flowOf(i) {
  const { j, level, agents, dir, mdl, mod, working, approval, refusals, notByArchitect } = i;
  const f = emptyFlow(); const num = k => Number(j[k]) || 0;
  const arch = num('arch_ts'), plan = num('plan_ts'), build = num('build_ts'), qa = num('qa_ts'), review = num('review_ts');
  f.plannedBy = j.planned_by || ''; f.builtBy = j.built_by || ''; f.qaBy = j.qa_by || '';
  f.plannedByLabel = f.plannedBy === 'Plan' ? 'Plan agent (built-in)' : f.plannedBy;
  f.qaState = build > 0 ? (qa >= build ? 'ran' : qa > 0 ? 'stale' : 'none') : '';
  const qv = qaVerdictOf(j, build);                                                    // verdict-aware (gate v2): passed | failed | ran (no verdict = legacy) | stale | none
  if (build > 0 && qv.state) { f.qaState = qv.state; f.qaVerdict = qv.verdict; f.qaCounts = qv.counts; f.qaAt = qv.at; }
  const run = agents.filter(a => !a.stalled).map(a => ({ a, ...agentFile(dir, a.type) })).sort((x, y) => (y.a.started || 0) - (x.a.started || 0));
  const pend = j.qa_pending && typeof j.qa_pending === 'object' ? Object.values(j.qa_pending).filter(t => Number(t) >= build - 1) : [];
  if (build > 0 && pend.length && (f.qaState === 'none' || f.qaState === 'stale') && !run.some(x => x.role === 'test')) f.qaState = 'cutoff';   // started, never reported (turn limit)
  if (build > 0 && i.vmode === 'strict' && f.qaState === 'ran') f.qaState = 'noverdict';                                                 // strict: the gate refuses a QA without a Verdict line
  const qaOk = qa >= build && f.qaState !== 'failed' && f.qaState !== 'noverdict';   // a FAILED / verdict-less (strict) QA is not a finished QA step
  f.planNotByArchitect = notByArchitect != null ? notByArchitect : (plan > 0 && arch <= 0);
  f.outside = (Array.isArray(j.outside) ? j.outside : []).filter(x => typeof x === 'string').slice(0, 30);
  f.integrity = j.integrity_logged && i.fresh ? (level === 'strict' ? 'blocked' : 'note') : '';
  f.bypass = !!j.bypass; f.refusalsToday = refusals || 0;
  f.planned = f.plannedBy; f.built = f.builtBy; f.qa = (f.qaState === 'ran' || f.qaState === 'passed') && !!f.qaBy;   // old fields the panel read before v2
  const approvedNoBuild = arch > 0 && plan >= arch && build <= 0 && !approval;          // plan presented and approved, building not started
  const marks = { plan: arch > 0, build: build > 0, ok: build > 0 || approvedNoBuild, qa: build > 0 && qaOk, review: build > 0 && review >= Math.max(build, qa) };
  marks.scope = marks.plan || marks.build;
  // 1) a running, not stalled agent decides by its Flow role (newest start wins)
  const main = shortModel(mdl.model);
  const withRole = run.find(x => ROLE_STAGE[x.role]);
  let stage = '', current = true;
  if (withRole) stage = ROLE_STAGE[withRole.role];
  else if (approval) stage = 'ok';                                                                // 2) plan approval pending
  else if (working) {                                                                            // 3) working, no agent: from the timestamps (the panel names no actor: f.running is empty)
    if (mod.mode === 'plan') stage = 'plan';
    else if (!arch && !build) stage = 'scope';
    else if (approvedNoBuild) { stage = 'build'; current = false; }                               // approved, building not started: plan + OK done, build = next (no current dot)
    else if (build > qa || f.qaState === 'failed') stage = 'build';
    else if (build > 0 && review >= Math.max(build, qa)) stage = 'review';
    else if (build > 0 && qaOk) { stage = 'qa'; current = false; }                         // QA done, Review next
    else stage = 'plan';
  } else {                                                                                       // 4) idle: the last step reached
    current = false;
    const last = [...STEPS].reverse().find(s => marks[s]);
    stage = marks.qa ? 'done' : (last || '');
  }
  const at = STEPS.indexOf(stage);
  for (const s of STEPS) f.steps[s] = s === stage && current ? 'current' : (current && at >= 0 && STEPS.indexOf(s) > at) ? 'next' : (marks[s] || (stage === 'done' && s !== 'review')) ? 'done' : 'next';
  f.stage = stage;
  f.running = run.map(x => ({ type: x.a.type, label: x.label, model: x.a.type === 'Plan' ? main : (shortModel(x.a.model) || x.model) }));   // only these may be named as "doing it now"
  f.actorRunning = f.running.length > 0;
  if (run.length) f.actors = f.running;
  else if (working && stage === 'plan') f.actors = [{ type: 'main chat', model: main }];
  else if (stage) { const t = stage === 'plan' ? f.plannedBy : stage === 'build' ? f.builtBy : (stage === 'done' || stage === 'qa') ? f.qaBy : ''; if (t) { const af = agentFile(dir, t); f.actors = [{ type: t, label: af.label, model: af.model }]; } }
  f.mismatch = !withRole && working && mod.mode === 'plan' && !!main && main !== 'opus';        // planning in the main chat on a non-Opus model
  return f;
}

function verdictMode(cfg) {                                       // gate.verdict in config/flow.json, default legacy (the gate's env override SHIPMIRACLE_FLOW_VERDICT is not visible to the panel)
  const g = cfg && cfg.gate && cfg.gate.verdict; return g === 'strict' ? 'strict' : 'legacy';
}
function listProjectNames(dev) {                                  // the project rule: direct child of dev, not dot-named, with .git (same as shipmiracle/projects.py)
  try { return fs.readdirSync(dev).filter(n => !n.startsWith('.') && fs.existsSync(path.join(dev, n, '.git'))); } catch (e) { return []; /* no folder */ }
}

// ---- F9 quiet fact (UX addendum 5c): "no new step for N min" while the chat is working. PROGRESS = the newest of a stage change, a flow step, a report written, a commit, a STATUS change,
// an agent start or finish. A transcript write alone is NOT progress (it only proves the chat is alive; the stall signals already cover a silent one). Everything here is a stat of a file that
// is read today anyway: no file contents, no process.
const mtimeS = f => { try { const st = fs.lstatSync(f); return st.isFile() ? Math.floor(st.mtimeMs / 1000) : 0; } catch (e) { return 0; } };
const QUIET_DEFAULT = 30;
function quietThreshold(w) { const v = w && typeof w === 'object' ? Number(w.quiet_progress_min) : NaN; return Number.isFinite(v) ? Math.min(240, Math.max(10, Math.round(v))) : QUIET_DEFAULT; }
function progressOf(p, flow, reportTs, pid) {
  const c = [];
  c.push(['stage', mtimeS(path.join(STATE, 'v1', 'cr', pid + '.jsonl'))]);
  if (flow) c.push(['flow', Math.max(0, ...['arch_ts', 'plan_ts', 'build_ts', 'qa_ts', 'review_ts'].map(k => secs(flow[k])))]);
  c.push(['report', reportTs || 0]);
  c.push(['commit', Math.max(p.lastCommit || 0, mtimeS(path.join(p.dir, '.git', 'logs', 'HEAD')))]);
  c.push(['status', Math.max(mtimeS(path.join(p.dir, 'docs', 'STATUS.md')), mtimeS(path.join(p.dir, 'Docs', 'STATUS.md')))]);
  c.push(['agent', Math.max(mtimeS(path.join(STATE, p.name + '.agents.json')), ...p.agents.map(a => secs(a.started)))]);
  const best = c.reduce((a, x) => (x[1] > a[1] ? x : a), ['', 0]);
  return best[1] > 0 ? { ts: best[1], src: best[0] } : null;
}
const STALL_KINDS = new Set(['frozen_chat', 'frozen_agent', 'stage_stuck', 'job_frozen']);
// -> { min, tests } | null. Shown only for a working, healthy chat without a stall item, not set aside, whose progress is at least `thr` minutes old.
function quietOf(p, prog, chat, thr, nowS) {
  if (!prog || (p.aside && p.aside.on) || p.state !== 'working' || p.approval || p.limitUntil) return null;
  if (!chat || chat.state !== 'ok' || chat.working !== true) return null;                       // limit, plan approval, needs-you, API trouble, context full, job wait, frozen: the watcher's other states
  if ((p.health || []).some(i => STALL_KINDS.has(i.kind)) || (p.live && p.live.phase === 'stalled') || p.agents.some(a => a.stalled)) return null;
  const age = nowS - prog.ts; if (!(age >= thr * 60)) return null;
  const tests = p.agents.filter(a => !a.stalled && agentFile(p.dir, a.type).role === 'test').map(a => a.mins);
  return { min: Math.floor(age / 60), tests: tests.length ? Math.max(...tests) : null };
}
// F7: the auto un-aside notices (aside.json `returned`, written by the watcher): [{project, why: 'work'|'hard_stop', ts}] of the last 24 hours, read-only, size-capped.
function asideReturned() {
  const j = REPORTS.readJson(path.join(STATE, 'v1', 'aside.json')), l = j && j.data && Array.isArray(j.data.returned) ? j.data.returned : [], nowS = Date.now() / 1000;
  return l.filter(r => r && typeof r === 'object' && typeof r.project === 'string' && (r.why === 'work' || r.why === 'hard_stop') && Number.isInteger(r.ts) && nowS - r.ts < 86400).slice(-5).map(r => ({ project: DETAIL.sanitize(r.project, 100), why: r.why, ts: r.ts }));
}
async function collect() {
  const names = listProjectNames(DEV);
  const held = heldNames();
  const cfg = readJSON(path.join(WS, 'config', 'flow.json')) || {};
  const refusals = refusalsToday(names);
  const ci = readJSON(path.join(STATE, 'ci.json')) || {};
  const projects = await Promise.all(names.map(async name => {
    const dir = path.join(DEV, name); const real = safeReal(dir);
    const s = readJSON(path.join(STATE, name + '.json')) || {};
    const agentsRaw = readJSON(path.join(STATE, name + '.agents.json')) || {};
    const now = Date.now() / 1000;
    const act = claudeActivity(real, name);
    const agents = Object.entries(agentsRaw).filter(([, a]) => now - a.started < 3 * 3600).map(([id, a]) => {
      const t = act.agent[id]; const quiet = t ? Math.round((Date.now() - t) / 1000) : null;     // seconds since this agent last wrote
      return { id: /^[A-Za-z0-9_-]{1,64}$/.test(id) ? id : '', type: a.type, model: shortModel(a.model), started: a.started, mins: Math.max(0, Math.round((now - a.started) / 60)), quiet, stalled: quiet != null && quiet > 600 };
    });
    const dirty = (await git(dir, ['status', '--porcelain'])).split('\n').filter(Boolean).length;
    const ahead = parseInt(await git(dir, ['rev-list', '--count', '@{u}..HEAD']), 10) || 0;
    const lastCommit = parseInt(await git(dir, ['log', '-1', '--format=%ct']), 10) || 0;
    const pushFailed = fs.existsSync(path.join(dir, '.git', 'PUSH-FAILED'));
    const age = s.ts ? Math.round(now - s.ts) : null;
    let state = s.state || 'idle';
    if (state === 'working' && age !== null && age > 1800 && !agents.length) state = 'idle';
    if (state === 'done') state = 'calm';
    const ct = claudeTokens(real, name);
    // What the lead session is running right now: model from Claude's status line (after each reply), mode from the hooks.
    // opusplan: plan mode = Opus, after approval = Sonnet. Phase: planning / implementing / reviewing / waiting for you.
    const mdl = readJSON(path.join(STATE, name + '.model.json')) || {}; const mod = readJSON(path.join(STATE, name + '.mode.json')) || {};
    const active = state === 'working' || state === 'needs-input';
    let phase = '';
    const moving = agents.some(a => !a.stalled) || (act.idle != null && act.idle <= 600);
    const stalled = state === 'working' && !moving && act.idle != null;     // hooks say working, nothing has been written for 10 min
    if (stalled) phase = 'stalled';
    else if (state === 'needs-input') phase = 'waiting';
    else if (state === 'working') phase = mod.mode === 'plan' ? 'planning' : agents.some(a => /review|qa|security|audit/i.test(a.type)) ? 'reviewing' : 'implementing';
    const live = active && mdl.model ? { model: mdl.model, phase, modelAge: mdl.ts ? Math.round(now - mdl.ts) : null, idle: act.idle } : (active ? { model: '', phase, modelAge: null, idle: act.idle } : null);
    const team = await teamOf(dir);
    const pb = await playbookOf(dir);
    return {
      mdl, mod, team, ...pb, proposed: PROPOSED.clean(pb.proposed, name), folders: ['src', 'app', 'lib', 'tests', 'test', 'docs'].filter(f => { try { return fs.statSync(path.join(dir, f)).isDirectory(); } catch (e) { return false; } }), rawState: s.state || 'idle', name, dir, stack: isHub(dir) ? 'workspace' : stackOf(dir), state, message: s.message || '', age, agents,
      model: shortModel(ct.model), live, next: nextLine(dir), dirty, ahead, pushFailed, lastCommit,
      tokens: { claudeDay: ct.day, claudeWeek: ct.week },
      ideas: readIdeas(dir), held: held.includes(name), ci: own(ci, name) || null,
      special: name === 'ideas' ? 'ideas' : '', hub: isHub(dir)
    };
  }));
  const RANK = { 'needs-input': 0, working: 1, calm: 2, idle: 3 };
  projects.sort((a, b) => (b.hub ? 1 : 0) - (a.hub ? 1 : 0) || (a.special ? 1 : 0) - (b.special ? 1 : 0) || (RANK[a.state] ?? 4) - (RANK[b.state] ?? 4) || b.lastCommit - a.lastCommit);
  const g = readJSON(path.join(STATE, 'guard.json')) || {};
  const off = fs.existsSync(path.join(STATE, 'guard.off'));
  const guard = { on: !off, running: Date.now() / 1000 - (g.ts || 0) < 120, hold: !!g.hold, reason: g.reason || '', battery: g.battery, lpm: !!g.lpm, away: awayCount() };
  let ask = readJSON(path.join(STATE, 'idea-ask.json')) || null;                 // the guard's "idle projects have ideas" question
  if (ask && !(ask.expires > Date.now() / 1000)) ask = null;
  let health = readJSON(path.join(STATE, 'health.json')) || null;                // bin/shipm-watch (the guard runs it every minute)
  if (health) { const c0 = health.counts && typeof health.counts === 'object' ? health.counts : {}, nn = x => (Number.isFinite(+x) ? +x : 0); health.counts = { ...c0, red: nn(c0.red), amber: nn(c0.amber), info: nn(c0.info) }; }   // numbers only: the Health badge is built from them
  if (health) { health.ageS = Math.round(Date.now() / 1000 - (health.ts || 0)); health.paused = fs.existsSync(path.join(STATE, 'agents.paused')); }
  if (health) { const n = readJSON(path.join(STATE, 'health-notice.json')); const ok = n && typeof n.text === 'string' && Date.now() - n.ts < 864e5; health.notice = ok ? n.text : '';
    health.noticeInfo = ok ? { busy: n.busy === true && Date.now() - n.ts < 600e3, id: typeof n.id === 'string' ? n.id : '', steps: Array.isArray(n.steps) ? n.steps.filter(x => typeof x === 'string').slice(0, 12) : [] } : { busy: false, id: '', steps: [] }; }   // notice stays a string for the old panel; a busy notice older than 10 min is a crashed fix, not progress
  const nowS0 = Date.now() / 1000;
  const flows = Object.create(null), sids = Object.create(null), flowSid = Object.create(null), signs = Object.create(null);                                                  // flow gate: who planned / built / tested in each project's latest session
  try { for (const f of fs.readdirSync(STATE)) { if (!/^flow\..+\.json$/.test(f)) continue; const j = readJSON(path.join(STATE, f)); if (j && typeof j === 'object' && typeof j.project === 'string' && j.project && Date.now() / 1000 - secs(j.ts) < 12 * 3600) { (sids[j.project] = sids[j.project] || []).push(f.slice(5, -5)); if (!flows[j.project] || j.ts > flows[j.project].ts) { flows[j.project] = j; flowSid[j.project] = f.slice(5, -5); } const sg = signs[j.project] = signs[j.project] || { recent: false, integrity: false, newest: 0 }; if (nowS0 - secs(j.ts) < 180) sg.recent = true; if (secs(j.ts) > sg.newest) sg.newest = secs(j.ts); if (j.integrity_logged) sg.integrity = true; } } } catch (e) { /* none */ }
  let pending = []; try { pending = fs.readdirSync(STATE).filter(f => f.startsWith('plan-pending.')).map(f => ({ sid: f.slice(13), at: fs.statSync(path.join(STATE, f)).mtimeMs / 1000 })); } catch (e) { /* none */ }
  const nowS = Date.now() / 1000;
  for (const p of projects) {
    const j = flows[p.name] || {}; const chat = health && own(health.chats, p.name);
    p.level = levelOf(cfg, p.name);
    const live = p.state === 'working' || p.state === 'needs-input';
    const fresh = live || (!!flows[p.name] && nowS - secs(j.ts) < 1800);                      // integrity / approval of a quiet old session are not shown
    p.approval = fresh && (!!(chat && chat.state === 'plan_approval') || pending.some(x => nowS - x.at < 6 * 3600 && (sids[p.name] || []).includes(x.sid)));
    p.flow = flowOf({ j, level: p.level, vmode: verdictMode(cfg), agents: p.agents, dir: p.dir, mdl: p.mdl, mod: p.mod, working: p.state === 'working', approval: p.approval, fresh,
      refusals: refusals[p.name], notByArchitect: flowSid[p.name] ? planEvent(flowSid[p.name]) : null });
    const lim = readJSON(path.join(STATE, p.name + '.limit.json')); p.limitUntil = lim && secs(lim.until) > nowS ? secs(lim.until) : 0;
    // Why a level switch would be unsafe now (every open chat reads config/flow.json): the first reason found, '' when none.
    const sg = signs[p.name] || {}; const cs = chat && chat.state;
    p.busyWhy = p.rawState === 'working' ? 'is working' : p.rawState === 'needs-input' ? 'is waiting for you' : p.limitUntil ? 'is waiting for the usage limit to reset'
      : p.agents.length ? 'has an agent running' : sg.recent ? (() => { const ago = Math.max(1, Math.round((nowS - sg.newest) / 60)), left = Math.max(1, Math.ceil((180 - (nowS - sg.newest)) / 60)); return `had chat activity ${ago} min ago; idle in ${left} min`; })() : sg.integrity ? 'has a changed gate file that your next message clears'
      : ['limit', 'working', 'plan_approval', 'waiting_you'].includes(cs) ? `chat is ${{ limit: 'waiting for the usage limit', working: 'working', plan_approval: 'waiting for your plan approval', waiting_you: 'waiting for you' }[cs]}` : '';
    delete p.mdl; delete p.mod; delete p.rawState;
  }
  // Per-project rule: a switch of X is blocked only by X's own busyWhy. data.levelSwitch (old shape) is ok when any project could switch.
  for (const p of projects) {
    p.levelSwitch = p.held ? { ok: false, why: 'Not now: this project is held (its session is still running).' } : p.level === 'off' ? { ok: false, why: 'The gate is off: change it by hand in config/flow.json.' }
      : p.busyWhy ? { ok: false, why: `Not now: ${p.name} ${p.busyWhy.replace(/\.$/, '')}. Every chat of this project reads the gate level, so switch it when this project is idle.` } : { ok: true, why: '' };
  }
  const bp = projects.find(p => p.busyWhy);
  const levelSwitch = projects.some(p => !p.busyWhy) || !bp ? { ok: true, why: '' } : { ok: false, why: `Not now: ${bp.name} ${bp.busyWhy}. Every chat of this project reads the gate level, so switch it when this project is idle.` };
  for (const p of projects) delete p.busyWhy;
  let creating = readJSON(path.join(STATE, 'project-creating.json'));
  creating = creating && typeof creating.name === 'string' && creating.name && Date.now() / 1000 - secs(creating.ts) < 300 ? { name: creating.name, ts: creating.ts } : null;
  const pn = readJSON(path.join(STATE, 'project-notice.json'));
  const pnotice = pn && typeof pn.text === 'string' && Date.now() / 1000 - secs(pn.ts) < 864e2 ? pn.text : '';
  const mr = readJSON(path.join(STATE, 'model-reset.json'));
  const modelReset = mr && Date.now() / 1000 - mr.ts < 864e2 ? mr : null;
  const led = ledgerInfo(), ctxs = contextFiles();
  for (const p of projects) {
    if (led.fresh && led.byProject[p.name]) { p.tokens.ledgerDay = led.byProject[p.name].today; p.tokens.ledgerWeek = led.byProject[p.name].week; }
    const c = ctxs[p.name]; if (c) p.context = { tokens: c.tokens, level: c.level };
  }
  for (const p of projects) p.health = health ? (health.items || []).filter(i => i.project === p.name) : [];
  for (const p of projects) {                                                    // a stalled agent's chip links to its frozen_agent Health item (matched by agent id when the item carries it, else the only one)
    const fa = p.health.filter(i => i.kind === 'frozen_agent'); if (!fa.length) continue;
    for (const a of p.agents) { if (!a.stalled) continue; const it = fa.find(i => a.id && JSON.stringify(i).includes(a.id)) || (fa.length === 1 ? fa[0] : null); if (it && typeof it.id === 'string') a.itemId = it.id; }
  }
  let reports; try { reports = REPORTS.readIndex(STATE); } catch (e) { reports = { items: [], status: 'bad' }; }
  { // F9: p.progress {ts, src} and p.quiet {min, tests}; the threshold is the watch config key quiet_progress_min (10-240, default 30)
    const thr = quietThreshold(readJSON(path.join(WS, 'config', 'watch.json'))), repTs = Object.create(null);
    for (const it of reports.items) if (it.project && it.ts > (repTs[it.project] || 0)) repTs[it.project] = it.ts;
    for (const p of projects) {
      p.progress = progressOf(p, flows[p.name], repTs[p.name], pidOf(safeReal(p.dir)));
      p.mirror = INTERVIEW.mirrorOf(p.dir, p.interview && p.interview.status);
      p.quiet = quietOf(p, p.progress, health && own(health.chats, p.name), thr, nowS);
    }
  }
  return { at: Date.now(), plan: plan(), ledger: led, projects, guard, ask, remote: { state: remoteSeen }, autopilot: { until_disabled_supported: false }, capabilities: { ...capsSeen }, asideReturned: asideReturned(),   // flips to true when the engine reports the standing-charter commands (autopilot-scope-design section 8)
   health, modelReset, levelSwitch, creating, pnotice, reports, tidy: TIDYX.load(STATE, names) };
}

module.exports = { collect, listProjectNames, resolveAgent, ALIASES, quietThreshold, quietOf };
if (require.main === module) collect().then(d => console.log(JSON.stringify(d, null, 2)));
