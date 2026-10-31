// Full-autopilot charter: the rules of shipmiracle/autopilot/charter.py (caps and error messages) as one pure module, shared by the panel's editor (the page gets validate()'s own source,
// see clientSource()) and the extension (which re-checks everything the page sent). tests/ext_charter_test.js parses charter.py and fails when a cap or a message drifts.
// This module also builds the owner's terminal commands. The panel never writes a charter or starts a run: `shipm autopilot charter set` and `start` need the owner at a
// terminal, so the extension types the exact commands into a VS Code integrated terminal and the owner confirms there.

// Constants copied from charter.py (GOAL_MAX, SCOPE_*, BUDGET_*, TIME_*, DEPS_MAX, ENDS_MAX, ALWAYS_EXCLUDED).
const RULES = {
  goalMax: 200, scopeMaxGlobs: 20, scopeMaxLen: 200, budgetMin: 1, budgetMax: 25, budgetDefault: 10, timeMin: 0.25, timeMax: 8, timeDefault: 3, depsMax: 10, endsMax: 5,
  alwaysExcluded: ['.shipmiracle/**', '.claude/**', '.githooks/**', '.git/**', '.github/workflows/**', '**/.env*', '.mcp.json', '.co' + 'dex/**', '.vscode/tasks.json', '.vscode/settings.json', '.envrc', '.husky/**', 'CLAUDE.md', 'AGENTS.md']
};
// Python format strings exactly as written in charter.py (%d %g %r %s, %% = one percent sign). The drift test compares each one with the source text.
const MSG = {
  goalLen: 'goal: 1-%d characters after removing control characters (got %d)',
  scopeCount: 'scope: 1-%d globs, comma separated',
  scopeLen: 'scope: each glob is 1-%d characters',
  scopeCtrl: 'scope: no control characters or backslashes in %r',
  scopeAbs: "scope: %r must be relative (no leading '/' or '~')",
  scopeDots: "scope: %r must not contain '..'",
  budgetForm: 'budget: expected a whole number of percent, like 10%%, got %r',
  budgetRange: 'budget: %d%% is outside %d-%d%% of the week (the cap is %d%%)',
  timeForm: 'time: expected hours like 3h or 1.5h, or minutes like 90m, got %r',
  timeStep: 'time: %g h is not a multiple of 15 minutes',
  timeRange: 'time: %g h is outside %g-%g h',
  depsCount: 'deps: listed needs 1-%d package names',
  depsName: 'deps: %r is not a package name ([a-z0-9@/._-], 1-100 characters)',
  endsCount: 'ends: 1-%d change request ids',
  endsId: 'ends: %r is not a change request id like CR-012'
};
// Panel-only rules (not in charter.py): the owner-facing form is stricter than the CLI about paths that control the rules, and about "everything".
const PANEL_MSG = {
  scopeOff: 'scope: %r is off limits: it controls the rules (the list below is always excluded)',
  scopeAll: 'scope: %r is everything. Name the folders or files it may change'
};

const gfmt = x => String(+Number(x).toPrecision(6));                       // Python %g for the values used here (0.25, 1.5, 8, 9)
function pyRepr(s) {                                                        // Python repr() of a short string: single quotes unless the text has a ' and no "
  s = String(s); const q = s.includes("'") && !s.includes('"') ? '"' : "'";
  return q + s.replace(/\\/g, '\\\\').replace(/\n/g, '\\n').replace(/\r/g, '\\r').replace(/\t/g, '\\t').replace(new RegExp(q, 'g'), '\\' + q) + q;
}
function fmt(f, ...a) {
  let i = 0;
  return f.replace(/%([%dgrs])/g, (m, c) => c === '%' ? '%' : c === 'd' ? String(parseInt(a[i++], 10)) : c === 'g' ? gfmt(a[i++]) : c === 'r' ? pyRepr(a[i++]) : String(a[i++]));
}
const cps = s => Array.from(String(s));                                     // code points, like Python len()

// validate(f, ctx) -> { ok, errors: { goal, scope, budget, time, deps, ends }, value }. Self-contained: clientSource() sends exactly this function text to the page.
//   f = { goal, scope (comma separated text or array), budget (text or number), time (text or number), depsMode 'none'|'listed', deps (comma separated text), ends (array of CR ids) }
//   ctx = { rules, msg, panelMsg, openCrs: ['CR-012', ...] }
function validate(f, ctx) {
  const R = ctx.rules, M = ctx.msg, P = ctx.panelMsg, errors = {}, value = {};
  const pyRepr = s => { s = String(s); const q = s.includes("'") && !s.includes('"') ? '"' : "'"; return q + s.replace(/\\/g, '\\\\').replace(/\n/g, '\\n').replace(/\r/g, '\\r').replace(/\t/g, '\\t').replace(new RegExp(q, 'g'), '\\' + q) + q; };
  const gfmt = x => String(+Number(x).toPrecision(6));
  const fmt = (m, ...a) => { let i = 0; return m.replace(/%([%dgrs])/g, (x, c) => c === '%' ? '%' : c === 'd' ? String(parseInt(a[i++], 10)) : c === 'g' ? gfmt(a[i++]) : c === 'r' ? pyRepr(a[i++]) : String(a[i++])); };
  const ctrl = s => /\p{C}/u.test(s);
  // goal
  { const g = String(f.goal == null ? '' : f.goal).replace(/\p{C}/gu, '').trim(), n = Array.from(g).length;
    if (n < 1 || n > R.goalMax) errors.goal = fmt(M.goalLen, R.goalMax, n); else value.goal = g; }
  // scope
  { let list = f.scope; if (typeof list === 'string') list = list.split(',').map(x => x.trim()).filter(Boolean);
    const out = [];
    if (!Array.isArray(list) || list.length < 1 || list.length > R.scopeMaxGlobs) errors.scope = fmt(M.scopeCount, R.scopeMaxGlobs);
    else for (const g of list) {
      const n = Array.from(g).length;
      if (n < 1 || n > R.scopeMaxLen) { errors.scope = fmt(M.scopeLen, R.scopeMaxLen); break; }
      if (ctrl(g) || g.includes('\\')) { errors.scope = fmt(M.scopeCtrl, Array.from(g).slice(0, 40).join('')); break; }
      if (g.startsWith('/') || g.startsWith('~')) { errors.scope = fmt(M.scopeAbs, Array.from(g).slice(0, 40).join('')); break; }
      if (g.split('/').includes('..')) { errors.scope = fmt(M.scopeDots, Array.from(g).slice(0, 40).join('')); break; }
      if (g === '*' || g === '**' || g === '**/*' || g === '.' || g === './') { errors.scope = fmt(P.scopeAll, g); break; }
      if (new RegExp('^(\\.\\/)?(\\.shipmiracle|\\.claude|\\.githooks|\\.git|\\.co' + 'dex|\\.husky|\\.envrc|\\.mcp\\.json|CLAUDE\\.md|AGENTS\\.md)(\\/|$|\\*)').test(g) || /(^|\/)\.env/.test(g) || /^(\.\/)?\.github\/workflows(\/|$)/.test(g)) { errors.scope = fmt(P.scopeOff, g); break; }
      if (!out.includes(g)) out.push(g);
    }
    if (!errors.scope) value.scope = out; }
  // budget
  { let v = f.budget == null || f.budget === '' ? R.budgetDefault : f.budget;
    if (typeof v === 'string') { const m = /^(\d{1,3})\s*%?$/.exec(v.trim()); if (!m) errors.budget = fmt(M.budgetForm, Array.from(v).slice(0, 20).join('')); else v = parseInt(m[1], 10); }
    if (!errors.budget) {
      if (typeof v !== 'number' || !Number.isInteger(v)) errors.budget = fmt(M.budgetForm, String(v).slice(0, 20));
      else if (v < R.budgetMin || v > R.budgetMax) errors.budget = fmt(M.budgetRange, v, R.budgetMin, R.budgetMax, R.budgetMax); else value.budget = v; } }
  // time (hours, 15-minute steps)
  { let v = f.time == null || f.time === '' ? R.timeDefault : f.time;
    if (typeof v === 'string') {
      const s = v.trim().toLowerCase(), m = /^(\d{1,3}(?:\.\d{1,3})?)\s*h?$/.exec(s), m2 = /^(\d{1,3})\s*m$/.exec(s);
      if (m2) v = parseInt(m2[1], 10) / 60; else if (m) v = parseFloat(m[1]); else errors.time = fmt(M.timeForm, Array.from(v).slice(0, 20).join('')); }
    if (!errors.time) {
      const q = Math.round(v * 4);
      if (Math.abs(v * 4 - q) > 1e-6) errors.time = fmt(M.timeStep, v);
      else if (q / 4 < R.timeMin || q / 4 > R.timeMax) errors.time = fmt(M.timeRange, q / 4, R.timeMin, R.timeMax); else value.time = q / 4; } }
  // deps
  { if (f.depsMode === 'listed') {
      const names = String(f.deps == null ? '' : f.deps).split(',').map(x => x.trim()).filter(Boolean), out = [];
      if (names.length < 1 || names.length > R.depsMax) errors.deps = fmt(M.depsCount, R.depsMax);
      else for (const n of names) { if (!/^[a-z0-9@/._-]{1,100}$/.test(n)) { errors.deps = fmt(M.depsName, Array.from(n).slice(0, 40).join('')); break; } if (!out.includes(n)) out.push(n); }
      if (!errors.deps) value.deps = { mode: 'listed', names: out };
    } else value.deps = { mode: 'none' }; }
  // ends
  { const l = Array.isArray(f.ends) ? f.ends : [], out = [];
    if (l.length < 1 || l.length > R.endsMax) errors.ends = fmt(M.endsCount, R.endsMax);
    else for (const c of l) { if (typeof c !== 'string' || !/^CR-\d{3,6}$/.test(c) || !(ctx.openCrs || []).includes(c)) { errors.ends = fmt(M.endsId, typeof c === 'string' ? c.slice(0, 20) : String(c)); break; } if (!out.includes(c)) out.push(c); }
    if (!errors.ends) value.ends = out; }
  return { ok: Object.keys(errors).length === 0, errors, value };
}
const CTX = { rules: RULES, msg: MSG, panelMsg: PANEL_MSG };
const check = (f, openCrs) => validate(f, { ...CTX, openCrs });
const clientSource = () => `const CHV = ${validate.toString()};\nconst CHX = ${JSON.stringify(CTX)};\nconst UNTIL = ${JSON.stringify(UNTIL)};\nconst CHUC = ${untilCheck.toString()};`;     // the page's copy of the rules: the very same function

// ---- the owner's terminal commands: argv arrays, quoted for the owner's shell. A value can never become shell syntax: every argument is single-quoted, a single quote is closed,
// escaped and reopened, and every control character (newline, tab, escape ...) is refused or removed first, because the terminal would type it as a key press.
const SAFE_NAME = /^[A-Za-z0-9._-]{1,100}$/;
const OPEN_CHAT = '--allow-open-chat';                                    // owner decision 21 Oct: the owner is at the terminal and confirms there; the project's chat is usually open
const stripCtrl = s => String(s).replace(/\p{C}/gu, '');
function quote(arg) {
  const s = String(arg);
  if (/\p{C}/u.test(s)) throw new Error('control character in a terminal argument');
  return "'" + s.replace(/'/g, "'\\''") + "'";
}
const line = argv => argv.map(quote).join(' ');
// Each element is one command (argv). The terminal runs them with && so a failed step stops the rest.
function charterArgv(shipm, project, v, setAutopilotFull) {
  if (!SAFE_NAME.test(project) || project.startsWith('-')) throw new Error('unsafe project name');
  const cmds = [];
  if (setAutopilotFull) cmds.push([shipm, 'playbook', 'set', 'autopilot', 'full', '--project', project, OPEN_CHAT]);
  const set = [shipm, 'autopilot', 'charter', 'set', '--project', project, '--goal=' + stripCtrl(v.goal), '--scope=' + v.scope.join(','), '--budget=' + v.budget + '%'];
  if (v.until === 'disabled') set.push('--until=disabled', '--day=' + v.day + '%', '--crs-day=' + v.crsDay);   // option C (standing charter): no time cap, a day slice and a requests-a-day cap
  else set.push('--time=' + v.time + 'h');
  set.push('--deps=' + (v.deps.mode === 'none' ? 'none' : v.deps.names.join(',')), '--ends=' + v.ends.join(','));
  cmds.push(set);
  cmds.push([shipm, 'autopilot', 'start', '--project', project]);
  return cmds;
}
function apLevelArgv(shipm, project, to) {
  if (!SAFE_NAME.test(project) || project.startsWith('-') || !['manual', 'guided'].includes(to)) throw new Error('bad autopilot request');
  return [[shipm, 'playbook', 'set', 'autopilot', to, '--project', project, OPEN_CHAT]];
}
function backToGuidedArgv(shipm, project) {                                    // `autopilot stop` ends the run AND clears the charter (charter.clear), then the level goes back to guided
  if (!SAFE_NAME.test(project) || project.startsWith('-')) throw new Error('unsafe project name');
  return [[shipm, 'autopilot', 'stop', '--project', project], [shipm, 'playbook', 'set', 'autopilot', 'guided', '--project', project, OPEN_CHAT]];
}
function allowArgv(shipm, project, id) {
  if (!SAFE_NAME.test(project) || project.startsWith('-') || !/^H-[0-9a-f]{6}$/.test(String(id))) throw new Error('bad stop id');
  return [[shipm, 'autopilot', 'allow', id, '--project', project]];
}
// Option C numbers (autopilot-scope-design 8.2): the day slice is 1-10% and never above the week value; requests a day 1-5.
const UNTIL = { dayMin: 1, dayMax: 10, dayDefault: 4, crsMin: 1, crsMax: 5, crsDefault: 3, weekMax: 25 };
function untilCheck(day, crsDay, week) {
  const d = Number(day), c = Number(crsDay), w = Number(week);
  if (!Number.isInteger(d) || d < UNTIL.dayMin || d > UNTIL.dayMax) return 'A day: 1-10% of the week.';
  if (Number.isInteger(w) && d > w) return 'A day cannot be more than the week.';
  if (!Number.isInteger(c) || c < UNTIL.crsMin || c > UNTIL.crsMax) return 'Requests a day: 1-5.';
  return '';
}
// Safe mode = the gate level; `shipm playbook set level` needs the owner at a terminal, so the command is only typed. Off is never set from here (the CLI refuses it).
function safeArgv(shipm, project, to) {
  if (!SAFE_NAME.test(project) || project.startsWith('-') || !['strict', 'warn'].includes(to)) throw new Error('bad safe mode request');
  return [[shipm, 'playbook', 'set', 'level', to, '--project', project, OPEN_CHAT]];
}
function stopArgv(shipm, project) {
  if (!SAFE_NAME.test(project) || project.startsWith('-')) throw new Error('unsafe project name');
  return [[shipm, 'autopilot', 'stop', '--project', project]];
}
// Option C verbs the owner types: checkpoint / resume / admit CR-x / drop CR-x. The engine side is built later; the panel only types them.
function cVerbArgv(shipm, project, verb, cr) {
  if (!SAFE_NAME.test(project) || project.startsWith('-') || !['checkpoint', 'resume', 'admit', 'drop'].includes(verb)) throw new Error('bad autopilot request');
  const a = [shipm, 'autopilot', verb];
  if (verb === 'admit' || verb === 'drop') { if (!/^CR-\d{1,6}$/.test(String(cr))) throw new Error('bad request id'); a.push(String(cr)); }
  a.push('--project', project);
  return [a];
}
// F7: park / bring back a project. `shipm project aside|unaside NAME` needs the owner at a terminal, so it is only typed (the optional note is typed there).
function asideArgv(shipm, project, op) {
  if (!SAFE_NAME.test(project) || project.startsWith('-') || !['aside', 'unaside'].includes(op)) throw new Error('bad aside request');
  return [[shipm, 'project', op, project]];
}
// F6 / F5: the owner's terminal lines for the interview and the toolbox. Every value is validated again here; a control character in any argument is refused by quote().
function interviewArgv(shipm, project, op, mode) {
  if (!SAFE_NAME.test(project) || project.startsWith('-') || !['start', 'resume', 'restart'].includes(op) || (op === 'start' && !['short', 'long'].includes(mode))) throw new Error('bad interview request');
  const a = [shipm, 'playbook', 'interview'];
  a.push(op === 'start' ? '--' + mode : '--' + op); a.push('--project', project);
  return [a];
}
function fromDraftArgv(shipm, project) {
  if (!SAFE_NAME.test(project) || project.startsWith('-')) throw new Error('unsafe project name');
  return [[shipm, 'playbook', 'set', '--from-draft', '--project', project, OPEN_CHAT]];
}
const STAGES = ['scope', 'plan', 'approve', 'do', 'verify', 'review', 'deliver'];
function assetArgv(shipm, project, op, a) {
  if (!SAFE_NAME.test(project) || project.startsWith('-') || !['remove', 'add'].includes(op)) throw new Error('bad toolbox request');
  const path = String(a && a.path || ''); if (!path || path.startsWith('-') || path.length > 300) throw new Error('bad asset path');
  if (op === 'remove') return [[shipm, 'playbook', 'asset', 'remove', path, '--project', project]];
  if (!STAGES.includes(a.stage)) throw new Error('bad stage');
  return [[shipm, 'playbook', 'asset', 'add', path, '--stage', a.stage, '--purpose', String(a.purpose || ''), '--project', project]];
}
const joinCmds = cmds => cmds.map(line).join(' && ');

module.exports = { RULES, MSG, PANEL_MSG, validate, check, clientSource, fmt, pyRepr, quote, line, joinCmds, charterArgv, apLevelArgv, backToGuidedArgv, allowArgv, safeArgv, stopArgv, cVerbArgv, asideArgv, interviewArgv, fromDraftArgv, assetArgv, STAGES, untilCheck, UNTIL, SAFE_NAME };
