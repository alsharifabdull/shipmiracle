// Card v2 data checks (data.js): flow stage, QA state, refusals, level, team, level switch, notices. Fixture folders in a temp dir.
// Run: node tests/data_flow_test.js
require('./shipmiracle_isolation').apply();   // test isolation: fresh HOME/SHIPMIRACLE_HOME/CONFIG/STATE unless already temp
const fs = require('fs'); const os = require('os'); const path = require('path');
const ROOT = fs.mkdtempSync(path.join(os.tmpdir(), 'shipmiracle-dataflow-'));
const STATE = path.join(ROOT, 'state'), DEV = path.join(ROOT, 'dev'), WS = path.join(DEV, 'AI-Workspace');
delete process.env.CLAUDECODE;   // the owner check only runs in a fully temp sandbox or outside a chat (H1)
process.env.SHIPMIRACLE_TEST = '1'; process.env.SHIPMIRACLE_EXT_STATE = STATE; process.env.SHIPMIRACLE_EXT_DEV = DEV; process.env.SHIPMIRACLE_EXT_WS = WS;
const HOMEDIR = path.join(ROOT, 'home'); process.env.SHIPMIRACLE_HOME = HOMEDIR; process.env.SHIPMIRACLE_STATE = STATE;   // user-level agents and the manifest of the python resolver live in the temp dir too
const { collect, resolveAgent, ALIASES } = require(path.join(__dirname, '../vscode-ext/shipmiracle-panel/data.js'));
let fails = 0, n = 0; const check = (name, c, info = '') => { n++; console.log((c ? 'PASS ' : 'FAIL ') + name + (c ? '' : ' ' + info)); if (!c) fails++; };
const now = () => Date.now() / 1000;
const put = (f, o) => { fs.mkdirSync(path.dirname(f), { recursive: true }); fs.writeFileSync(f, typeof o === 'string' ? o : JSON.stringify(o)); };
const NAME = 'zzf-card';
const agentMd = (model, role, reason = true, name = 'x') => `---\nname: ${name}\nmodel: ${model}\nmaxTurns: 20\n---\n${reason ? 'Model reason: test\n' : ''}Flow role: ${role}\n## DoD\nVerdict: PASS\n`;
const FILES = { 'solution-architect': ['opus', 'plan'], 'frontend-engineer': ['sonnet', 'build'], 'qa-engineer': ['sonnet', 'test'], 'independent-reviewer': ['opus', 'review'], 'product-analyst': ['sonnet', 'scope'] };

function reset(level) {
  fs.rmSync(STATE, { recursive: true, force: true }); fs.rmSync(DEV, { recursive: true, force: true });
  fs.mkdirSync(path.join(WS, 'bin'), { recursive: true }); fs.mkdirSync(path.join(WS, 'config'), { recursive: true }); fs.mkdirSync(path.join(DEV, NAME, '.git'), { recursive: true }); fs.mkdirSync(STATE, { recursive: true });
  fs.copyFileSync(path.join(__dirname, '../bin/shipm'), path.join(WS, 'bin/shipm')); fs.chmodSync(path.join(WS, 'bin/shipm'), 0o755);   // the panel runs `bin/shipm agents check --project`
  fs.copyFileSync(path.join(__dirname, '../bin/agent-check'), path.join(WS, 'bin/agent-check')); fs.chmodSync(path.join(WS, 'bin/agent-check'), 0o755);
  fs.cpSync(path.join(__dirname, '../shipmiracle'), path.join(WS, 'shipmiracle'), { recursive: true });   // agent-check is a shim over shipmiracle/agents.py
  for (const [t, [m, r]] of Object.entries(FILES)) put(path.join(DEV, NAME, '.claude/agents', t + '.md'), agentMd(m, r, true, t));   // frontmatter name = file name (Shipmiracle lists agents by it)
  if (level !== null) put(path.join(WS, 'config/flow.json'), level || { default: 'strict', projects: {} });
}
// o: state (internal state in <p>.json), flow (flow.sid.json fields), agents [{type,model,startedAgo}], mode, model, health state, pending
async function run(o = {}) {
  reset(o.cfg === undefined ? undefined : o.cfg);
  const t = now();
  put(path.join(STATE, NAME + '.json'), { state: o.state || 'idle', ts: t, message: o.message || '' });
  if (o.flow) put(path.join(STATE, 'flow.sid1.json'), { project: NAME, ts: t, ...o.flow });
  if (o.agents) put(path.join(STATE, NAME + '.agents.json'), Object.fromEntries(o.agents.map((a, i) => ['ag' + i, { type: a.type, model: a.model || '', started: t - (a.ago || 60) }])));
  if (o.mode) put(path.join(STATE, NAME + '.mode.json'), { mode: o.mode, ts: t });
  if (o.model) put(path.join(STATE, NAME + '.model.json'), { model: o.model, ts: t });
  if (o.health) put(path.join(STATE, 'health.json'), { ts: t, chats: { [NAME]: { state: o.health } }, items: [] });
  if (o.pending) { put(path.join(STATE, 'plan-pending.sid1'), 'x'); }
  if (o.limit) put(path.join(STATE, NAME + '.limit.json'), { until: t + 3600, ts: t });
  if (o.events) put(path.join(STATE, 'flow-events.jsonl'), o.events.map(e => JSON.stringify({ project: NAME, ...e })).join('\n') + '\n');
  if (o.extra) o.extra(t);
  const d = await collect(); return { d, p: d.projects.find(p => p.name === NAME) };
}
const T = now();
const steps = f => STEPS.map(s => f.steps[s][0]).join('');   // d/c/n per step
const STEPS = ['scope', 'plan', 'ok', 'build', 'qa', 'review'];

(async () => {
  // ---- stage precedence table ----
  const table = [
    ['running scope agent', { state: 'working', agents: [{ type: 'product-analyst', model: 'sonnet' }] }, 'scope'],
    ['running plan-role agent', { state: 'working', agents: [{ type: 'solution-architect', model: 'opus' }] }, 'plan'],
    ['running build agent', { state: 'working', agents: [{ type: 'frontend-engineer', model: 'sonnet' }] }, 'build'],
    ['running test agent', { state: 'working', agents: [{ type: 'qa-engineer', model: 'sonnet' }] }, 'qa'],
    ['running review agent', { state: 'working', agents: [{ type: 'independent-reviewer', model: 'opus' }] }, 'review'],
    ['agent beats plan approval', { state: 'working', health: 'plan_approval', agents: [{ type: 'frontend-engineer' }] }, 'build'],
    ['agent beats plan mode', { state: 'working', mode: 'plan', agents: [{ type: 'frontend-engineer' }] }, 'build'],
    ['newest running agent wins', { state: 'working', agents: [{ type: 'frontend-engineer', ago: 600 }, { type: 'qa-engineer', ago: 30 }] }, 'qa'],
    ['an agent started over 3 h ago is ignored', { state: 'working', flow: { arch_ts: T - 100 }, agents: [{ type: 'qa-engineer', ago: 4 * 3600 }], mode: 'plan' }, 'plan'],
    ['unknown built-in general-purpose = build', { state: 'working', agents: [{ type: 'general-purpose' }] }, 'build'],
    ['plan approval via health', { state: 'idle', health: 'plan_approval', flow: { arch_ts: T - 10 } }, 'ok'],
    ['plan approval via plan-pending', { state: 'idle', pending: true, flow: { arch_ts: T - 10 } }, 'ok'],
    ['working in plan mode', { state: 'working', mode: 'plan' }, 'plan'],
    ['working, nothing yet = scope', { state: 'working' }, 'scope'],
    ['working, build after qa = build', { state: 'working', flow: { arch_ts: T - 50, build_ts: T - 10, qa_ts: T - 30 } }, 'build'],
    ['working, only build = build', { state: 'working', flow: { arch_ts: T - 50, build_ts: T - 10 } }, 'build'],
    ['working, qa after build, no agent = qa (not review)', { state: 'working', flow: { arch_ts: T - 50, build_ts: T - 30, qa_ts: T - 10 } }, 'qa'],
    ['working, review_ts >= qa = review', { state: 'working', flow: { arch_ts: T - 50, build_ts: T - 30, qa_ts: T - 10, review_ts: T - 5 } }, 'review'],
    ['working, plan approved, build not started = build (next)', { state: 'working', flow: { arch_ts: T - 50, plan_ts: T - 40 } }, 'build'],
    ['working, plan approved but still in plan mode = plan', { state: 'working', mode: 'plan', flow: { arch_ts: T - 50, plan_ts: T - 40 } }, 'plan'],
    ['idle, nothing = none', { state: 'idle' }, ''],
    ['idle, plan only = plan', { state: 'idle', flow: { arch_ts: T - 10, planned_by: 'solution-architect' } }, 'plan'],
    ['idle, built not tested = build', { state: 'idle', flow: { arch_ts: T - 50, build_ts: T - 10 } }, 'build'],
    ['idle, tested = done', { state: 'idle', flow: { arch_ts: T - 50, build_ts: T - 30, qa_ts: T - 10 } }, 'done'],
  ];
  for (const [name, o, want] of table) { const { p } = await run(o); check('stage: ' + name, p.flow.stage === want, `got "${p.flow.stage}" want "${want}"`); }

  // ---- steps and done markers ----
  let r = await run({ state: 'working', flow: { arch_ts: T - 50, build_ts: T - 30, qa_ts: T - 10, review_ts: T - 5 } });
  check('working with review_ts >= qa: review is the current step', steps(r.p.flow) === 'dddddc', steps(r.p.flow));
  r = await run({ state: 'working', flow: { arch_ts: T - 50, build_ts: T - 30, qa_ts: T - 10 } });
  check('working, QA done, no agent: QA done, Review next, nothing current', steps(r.p.flow) === 'ddddd' + 'n' && r.p.flow.running.length === 0 && r.p.flow.actorRunning === false, steps(r.p.flow));
  r = await run({ state: 'working', agents: [{ type: 'independent-reviewer', model: 'opus' }], flow: { arch_ts: T - 50, build_ts: T - 30, qa_ts: T - 10 } });
  check('review agent running: review current, running lists it', steps(r.p.flow) === 'dddddc' && r.p.flow.running.length === 1 && r.p.flow.running[0].type === 'independent-reviewer' && r.p.flow.actorRunning === true, steps(r.p.flow));
  r = await run({ state: 'working' });
  check('scope fallback with no agent names no running actor', r.p.flow.stage === 'scope' && r.p.flow.running.length === 0 && r.p.flow.actorRunning === false);
  r = await run({ state: 'working', flow: { arch_ts: T - 50, plan_ts: T - 40 }, mode: 'default', model: 'Sonnet 5.5' });
  check('M3: plan approved, build not started: scope/plan/ok done, build next, no mismatch', steps(r.p.flow) === 'dddnnn' && r.p.flow.stage === 'build' && r.p.flow.mismatch === false, steps(r.p.flow));
  r = await run({ state: 'idle', flow: { arch_ts: T - 50, build_ts: T - 30, qa_ts: T - 10, review_ts: T - 5 } });
  check('idle fully done: every step done', steps(r.p.flow) === 'dddddd', steps(r.p.flow));
  r = await run({ state: 'idle', flow: { arch_ts: T - 50, build_ts: T - 30, qa_ts: T - 10 } });
  check('idle tested, no review: review is next', steps(r.p.flow) === 'ddddd' + 'n', steps(r.p.flow));
  r = await run({ state: 'working', agents: [{ type: 'frontend-engineer', model: 'sonnet' }], flow: { arch_ts: T - 50, build_ts: T - 10 } });
  check('building: scope/plan/ok done, build current, qa/review next', steps(r.p.flow) === 'dddcnn', steps(r.p.flow));
  r = await run({ state: 'idle', health: 'plan_approval', flow: { arch_ts: T - 10 } });
  check('waiting for approval: scope/plan done, ok current', steps(r.p.flow) === 'ddcnnn' && r.p.approval === true, steps(r.p.flow));
  r = await run({ state: 'working' });
  check('scoping: scope current, rest next', steps(r.p.flow) === 'cnnnnn', steps(r.p.flow));
  r = await run({ state: 'idle' });
  check('no flow data: all next, no actors', steps(r.p.flow) === 'nnnnnn' && r.p.flow.actors.length === 0 && r.p.approval === false);

  // ---- actors and models ----
  r = await run({ state: 'working', agents: [{ type: 'frontend-engineer', model: 'claude-sonnet-5-5' }, { type: 'qa-engineer', model: '' }] });
  check('actors: model from agents.json, else the agent file', r.p.flow.actors.length === 2 && r.p.flow.actors[0].model === 'sonnet' && r.p.flow.actors[1].model === 'sonnet' && r.p.flow.actors[1].type === 'qa-engineer', JSON.stringify(r.p.flow.actors));
  r = await run({ state: 'working', agents: [{ type: 'solution-architect', model: '' }] });
  check('actors: architect model from its file (opus)', r.p.flow.actors[0].model === 'opus', JSON.stringify(r.p.flow.actors));
  r = await run({ state: 'working', agents: [{ type: 'Plan', model: '' }], model: 'Opus 5.5' });
  check('actors: built-in Plan agent shows the main chat model', r.p.flow.stage === 'plan' && r.p.flow.actors[0].model === 'opus', JSON.stringify(r.p.flow.actors));
  r = await run({ state: 'idle', flow: { arch_ts: T - 10, planned_by: 'solution-architect', built_by: 'frontend-engineer', qa_by: 'qa-engineer', build_ts: T - 5 } });
  check('idle: plannedBy / builtBy / qaBy copied', r.p.flow.plannedBy === 'solution-architect' && r.p.flow.builtBy === 'frontend-engineer' && r.p.flow.qaBy === 'qa-engineer');
  check('idle actor is the agent that did the last step', r.p.flow.actors.length === 1 && r.p.flow.actors[0].type === 'frontend-engineer' && r.p.flow.actors[0].model === 'sonnet', JSON.stringify(r.p.flow.actors));

  // ---- qaState ----
  r = await run({ flow: { build_ts: T - 20, qa_ts: T - 5 } }); check('qaState ran (qa_ts >= build_ts)', r.p.flow.qaState === 'ran');
  r = await run({ flow: { build_ts: T - 5, qa_ts: T - 20 } }); check('qaState stale (qa before the last build)', r.p.flow.qaState === 'stale');
  r = await run({ flow: { build_ts: T - 5 } }); check('qaState none (built, never tested)', r.p.flow.qaState === 'none');
  r = await run({ flow: { arch_ts: T - 5 } }); check("qaState '' when nothing was built", r.p.flow.qaState === '');
  r = await run({}); check("qaState '' without flow data", r.p.flow.qaState === '');
  // ---- QA verdict (gate v2): passed / failed / ran (no verdict) / stale ----
  const R = (ts, verdict, o = {}) => ({ ts: T - ts, start: T - ts - 3, verdict, evidence: '', by: 'qa-engineer', ...o });
  r = await run({ flow: { build_ts: T - 20, qa_ts: T - 5, qa_by: 'qa-engineer', qa_runs: [R(5, 'PASS', { evidence: '12 passed, 0 failed' })] } });
  check('qaState passed (PASS verdict newer than the build) with the counts line', r.p.flow.qaState === 'passed' && r.p.flow.qaCounts === '12 passed, 0 failed' && r.p.flow.qa === true, JSON.stringify(r.p.flow));
  r = await run({ flow: { build_ts: T - 20, qa_ts: T - 5, qa_by: 'qa-engineer', qa_runs: [R(5, 'FAIL', { evidence: '3 failed, 9 passed' })] } });
  check('qaState failed (FAIL verdict) with the failing counts; QA step not done; stage build', r.p.flow.qaState === 'failed' && r.p.flow.qaVerdict === 'FAIL' && r.p.flow.qaCounts === '3 failed, 9 passed' && r.p.flow.steps.qa !== 'done' && r.p.flow.qa === false, JSON.stringify(r.p.flow));
  r = await run({ flow: { build_ts: T - 20, qa_ts: T - 5, qa_runs: [R(5, 'BLOCKED', { evidence: 'no node' })] } }); check('qaState failed for BLOCKED (verdict kept, no counts without digits)', r.p.flow.qaState === 'failed' && r.p.flow.qaVerdict === 'BLOCKED' && r.p.flow.qaCounts === '');
  r = await run({ flow: { build_ts: T - 20, qa_ts: T - 5, qa_runs: [R(5, '')] } }); check('qaState ran when the run had no verdict (legacy)', r.p.flow.qaState === 'ran');
  r = await run({ flow: { build_ts: T - 5, qa_ts: T - 20, qa_runs: [R(20, 'PASS')] } }); check('qaState stale when the PASS is older than the last build', r.p.flow.qaState === 'stale');
  r = await run({ flow: { build_ts: T - 30, qa_ts: T - 5, qa_runs: [R(12, 'FAIL', { evidence: '1 failed', start: T - 20 }), R(5, 'PASS', { start: T - 8 })] } }); check('FAIL then a later PASS (not overlapping): passed', r.p.flow.qaState === 'passed');
  r = await run({ flow: { build_ts: T - 30, qa_ts: T - 5, qa_runs: [R(12, 'FAIL', { evidence: '1 failed', start: T - 20 }), R(5, 'PASS', { start: T - 14 })] } }); check('PASS that started before the FAIL stopped (parallel): failed', r.p.flow.qaState === 'failed');
  r = await run({ flow: { build_ts: T - 30, qa_ts: T - 5, qa_runs: [R(12, 'FAIL', { evidence: '1 failed' }), R(5, '')] } }); check('a verdict-less run does not supersede an earlier FAIL', r.p.flow.qaState === 'failed');
  r = await run({ flow: { build_ts: T - 20, qa_ts: T - 5, qa_runs: [R(5, '')] } }); check('legacy mode (default): no verdict stays "ran"', r.p.flow.qaState === 'ran');
  r = await run({ flow: { build_ts: T - 20, qa_ts: T - 5, qa_runs: [R(5, '')] }, cfg: { default: 'strict', projects: {}, gate: { verdict: 'strict' } } }); check('strict + no verdict: noverdict, QA step not done', r.p.flow.qaState === 'noverdict' && r.p.flow.steps.qa !== 'done', JSON.stringify(r.p.flow));
  r = await run({ flow: { build_ts: T - 20, qa_ts: T - 5, qa_runs: [R(5, 'PASS')] }, cfg: { default: 'strict', projects: {}, gate: { verdict: 'strict' } } }); check('strict + PASS stays passed', r.p.flow.qaState === 'passed');
  r = await run({ flow: { build_ts: T - 20, qa_pending: { a1: T - 10 } } }); check('QA started, nothing running, never reported: cutoff', r.p.flow.qaState === 'cutoff', r.p.flow.qaState);
  r = await run({ flow: { build_ts: T - 20, qa_ts: T - 5, qa_runs: 'junk' } }); check('garbage qa_runs falls back to ran', r.p.flow.qaState === 'ran');

  // ---- plan not by the architect, mismatch ----
  r = await run({ flow: { plan_ts: T - 5 } }); check('planNotByArchitect: plan shown with no architect', r.p.flow.planNotByArchitect === true);
  r = await run({ flow: { plan_ts: T - 5, arch_ts: T - 20 }, events: [{ ts: T - 9, session: 'sid1', event: 'plan_without_architect_warned' }] }); check('planNotByArchitect: newest plan event of the session was warned', r.p.flow.planNotByArchitect === true);
  r = await run({ flow: { plan_ts: T - 5, arch_ts: T - 20, warnings: ['plan_without_architect'] }, events: [{ ts: T - 9, session: 'sid1', event: 'plan_without_architect_warned' }, { ts: T - 3, session: 'sid1', event: 'plan_ok' }] }); check('planNotByArchitect resets after a later plan_ok (old warnings list is ignored)', r.p.flow.planNotByArchitect === false);
  r = await run({ flow: { plan_ts: T - 5, arch_ts: T - 20 }, events: [{ ts: T - 3, session: 'other', event: 'plan_without_architect' }, { ts: T - 9, session: 'sid1', event: 'plan_ok' }] }); check('planNotByArchitect: other sessions do not count', r.p.flow.planNotByArchitect === false);
  r = await run({ flow: { plan_ts: T - 5, arch_ts: T - 20, planned_by: 'Plan' } }); check('built-in Plan agent is a plan role: no warning, label set', r.p.flow.planNotByArchitect === false && r.p.flow.plannedByLabel === 'Plan agent (built-in)');
  r = await run({ flow: { planned_by: 'solution-architect' } }); check('plannedByLabel is the agent name otherwise', r.p.flow.plannedByLabel === 'solution-architect');
  r = await run({ flow: { plan_ts: T - 5, arch_ts: T - 20 } }); check('planNotByArchitect false for a normal plan', r.p.flow.planNotByArchitect === false);
  r = await run({ state: 'working', mode: 'plan', model: 'Sonnet 5.5' }); check('mismatch: plan mode in the chat on Sonnet', r.p.flow.mismatch === true && r.p.live.model === 'Sonnet 5.5');
  r = await run({ state: 'working', mode: 'default', model: 'Sonnet 5.5' }); check('no mismatch outside plan mode', r.p.flow.mismatch === false);
  r = await run({ state: 'working', mode: 'plan', model: 'Opus 5.5' }); check('no mismatch on Opus', r.p.flow.mismatch === false);
  r = await run({ state: 'working', mode: 'plan', model: 'Sonnet 5.5', agents: [{ type: 'solution-architect' }] }); check('no mismatch when the architect agent plans', r.p.flow.mismatch === false);

  // ---- refusals today ----
  const mid = new Date(); mid.setHours(0, 0, 0, 0); const m0 = mid.getTime() / 1000;
  r = await run({ events: [
    { ts: T, event: 'plan_without_architect' }, { ts: T, event: 'edit_outside_team' }, { ts: T, event: 'bash_write_outside_team' }, { ts: T, event: 'done_without_qa' },
    { ts: T, event: 'outside_team' }, { ts: T, event: 'gate_tamper' }, { ts: T, event: 'agent_rule_refused' },
    { ts: T, event: 'edit_outside_team_warned' }, { ts: T, event: 'done_without_qa_capped' }, { ts: T, event: 'bypass' }, { ts: T, event: 'plan_ok' }, { ts: T, event: 'gate_tamper_detected' },
    { ts: m0 - 60, event: 'edit_outside_team' }, { ts: T, event: 'edit_outside_team', project: 'other' },
  ] });
  check('refusalsToday counts only today, only the exact kinds, only this project', r.p.flow.refusalsToday === 7, 'got ' + r.p.flow.refusalsToday);
  check('refusalsToday survives junk lines', (await run({ extra: () => fs.appendFileSync(path.join(STATE, 'flow-events.jsonl'), 'not json\n{"ts":1}\n\n'), events: [{ ts: T, event: 'gate_tamper' }] })).p.flow.refusalsToday === 1);
  check('refusalsToday 0 without the file', (await run({})).p.flow.refusalsToday === 0);

  // ---- level ----
  r = await run({ cfg: { default: 'warn', projects: { [NAME]: 'strict' } } }); check('level: project entry wins', r.p.level === 'strict');
  r = await run({ cfg: { default: 'warn', projects: {} } }); check('level: default used', r.p.level === 'warn');
  r = await run({ cfg: { projects: {} } }); check('level: no default = strict', r.p.level === 'strict');
  r = await run({ cfg: { default: 'strict', projects: { [NAME]: 'off' } } }); check('level: off is reported', r.p.level === 'off');
  r = await run({ cfg: null }); check('level: missing flow.json = strict', r.p.level === 'strict');
  r = await run({ cfg: '{ not json' }); check('level: malformed flow.json = strict, no throw', r.p.level === 'strict');
  r = await run({ cfg: { default: 'loud', projects: { [NAME]: 7 } } }); check('level: unknown values = strict', r.p.level === 'strict');
  r = await run({ cfg: '[]' }); check('level: flow.json is a list = strict', r.p.level === 'strict');

  // ---- integrity, outside, bypass ----
  r = await run({ flow: { integrity_logged: '.claude/agents' } }); check('integrity at strict = blocked', r.p.flow.integrity === 'blocked');
  r = await run({ cfg: { default: 'warn', projects: {} }, flow: { integrity_logged: '.claude/agents' } }); check('integrity at warn = note', r.p.flow.integrity === 'note');
  r = await run({ flow: {} }); check('integrity empty when nothing logged', r.p.flow.integrity === '');
  r = await run({ state: 'idle', flow: { integrity_logged: 'x' }, extra: t => put(path.join(STATE, 'flow.sid1.json'), { project: NAME, ts: t - 3600, integrity_logged: 'x' }), health: 'plan_approval' });
  check('m3: integrity and approval of a quiet session over 30 min old are hidden', r.p.flow.integrity === '' && r.p.approval === false, JSON.stringify([r.p.flow.integrity, r.p.approval]));
  r = await run({ state: 'working', agents: [{ type: 'frontend-engineer' }], extra: t => put(path.join(STATE, 'flow.sid1.json'), { project: NAME, ts: t - 3600, integrity_logged: 'x' }) });
  check('m3: integrity of an old session still shows while the project is working', r.p.flow.integrity === 'blocked');
  r = await run({ flow: { outside: ['src/a.js', 'b.py'] } }); check('outside names listed', JSON.stringify(r.p.flow.outside) === '["src/a.js","b.py"]');
  r = await run({ flow: { outside: 'oops' } }); check('outside junk = empty list', Array.isArray(r.p.flow.outside) && r.p.flow.outside.length === 0);
  r = await run({ flow: { bypass: true } }); check('bypass true', r.p.flow.bypass === true);
  r = await run({ flow: { bypass: false } }); check('bypass false', r.p.flow.bypass === false);
  r = await run({ extra: t => put(path.join(STATE, 'flow.old.json'), { project: NAME, ts: t - 13 * 3600, bypass: true, built_by: 'x', build_ts: 1 }) }); check('a flow file older than 12 h is ignored', r.p.flow.bypass === false && r.p.flow.builtBy === '');
  r = await run({ extra: t => { put(path.join(STATE, 'flow.a.json'), { project: NAME, ts: t - 100, built_by: 'old-one' }); put(path.join(STATE, 'flow.b.json'), { project: NAME, ts: t - 5, built_by: 'new-one' }); } }); check('newest flow file of the project wins', r.p.flow.builtBy === 'new-one');

  // ---- team ----
  r = await run({}); check('team: all good = 5 agent files, none bad', r.p.team.count === 5 && r.p.team.bad.length === 0, JSON.stringify(r.p.team));
  r = await run({ extra: () => put(path.join(DEV, NAME, '.claude/agents/bad-one.md'), '---\nmodel: inherit\n---\nbody\n') });
  check('team: one bad agent file is reported once, with the file name', r.p.team.count === 6 && r.p.team.bad.length === 1 && /bad-one\.md/.test(r.p.team.bad[0]) && /inherit/.test(r.p.team.bad[0]), JSON.stringify(r.p.team));
  r = await run({ extra: () => put(path.join(DEV, NAME, '.claude/agents/qa-reviewer.md'), '---\nmodel: sonnet\n---\nModel reason: t\nFlow role: test\n') });
  check('team: a file with only the DoD/maxTurns missing is NOT a model-rule problem; it is listed under dod', r.p.team.bad.length === 0 && r.p.team.dod.length === 1 && /qa-reviewer\.md/.test(r.p.team.dod[0]) && !/\[dod\]/.test(r.p.team.dod[0]), JSON.stringify(r.p.team));
  r = await run({ events: [{ ts: T, event: 'qa_failed' }, { ts: T, event: 'qa_no_verdict' }, { ts: T, event: 'qa_failed_capped' }, { ts: T, event: 'bypass_qa_failed' }] });
  check('refusalsToday counts qa_failed and qa_no_verdict (the exact refusals) but not the capped / bypass lines', r.p.flow.refusalsToday === 2, r.p.flow.refusalsToday);
  r = await run({ extra: () => fs.rmSync(path.join(DEV, NAME, '.claude/agents'), { recursive: true }) }); check('team: no agents dir = count 0', r.p.team.count === 0 && r.p.team.bad.length === 0);
  { // cached by mtimes: second collect without a change must not run agent-check again (replace the script with a failing one)
    await run({ extra: () => put(path.join(DEV, NAME, '.claude/agents/bad-one.md'), '---\nmodel: inherit\n---\nx\n') });
    const ac = path.join(WS, 'bin/agent-check'); fs.writeFileSync(ac, '#!/bin/sh\necho SHOULD-NOT-RUN\nexit 1\n');
    const d2 = await collect(); const p2 = d2.projects.find(p => p.name === NAME);
    check('team: result cached while the agent files are unchanged', p2.team.bad.length === 1 && !/SHOULD-NOT-RUN/.test(p2.team.bad[0]), JSON.stringify(p2.team));
  }

  // ---- team via `shipm agents check --project --json` (T6) ----
  r = await run({ extra: () => put(path.join(DEV, NAME, '.claude/agents/odd-file.md'), agentMd('sonnet', 'review', true, 'other-name')) });
  check('team (shipm): untrusted = project agents claiming a privileged role that is no master copy (old names, no manifest here)', JSON.stringify(r.p.team.untrusted) === JSON.stringify(['independent-reviewer', 'odd-file', 'qa-engineer', 'solution-architect']), JSON.stringify(r.p.team));
  check('team (shipm): untrustedInfo carries name, claimed role, shadow and mismatch flags for the confirmation ; a file whose frontmatter name differs is flagged mismatch and listed by FILE name', (() => { const r0 = r.p.team.untrustedInfo.find(x => x.name === 'qa-engineer'), r1 = r.p.team.untrustedInfo.find(x => x.name === 'odd-file'); return r.p.team.untrustedInfo.length === 4 && r0 && r0.role === 'test' && r0.mismatch === false && r0.shadow === true && r1 && r1.mismatch === true; })(), JSON.stringify(r.p.team.untrustedInfo));
  r = await run({ extra: () => {
    for (const f of ['solution-architect', 'qa-engineer', 'independent-reviewer']) { const fp = path.join(DEV, NAME, '.claude/agents', f + '.md'); fs.writeFileSync(fp, fs.readFileSync(fp, 'utf8').replace('name: x', 'name: ' + f)); }   // a name that differs from the file name is never trusted
    const sha = f => require('crypto').createHash('sha256').update(fs.readFileSync(path.join(DEV, NAME, '.claude/agents', f))).digest('hex');
    put(path.join(STATE, 'v1', 'agents.json'), { v: 1, ts: 1, writer: 'shipmiracle-agents', data: { v: 1, installed: 1, ws: WS, ws_sha: 'x', agents: {}, legacy: { 'solution-architect': [sha('solution-architect.md')], 'qa-engineer': [sha('qa-engineer.md')], 'independent-reviewer': [sha('independent-reviewer.md')] }, legacy_expires: 'P5' } });
  } });
  check('team (shipm): a sha in the manifest legacy set is trusted, so no untrusted chip data', r.p.team.untrusted.length === 0 && r.p.team.count === 5, JSON.stringify(r.p.team));
  r = await run({ extra: () => put(path.join(DEV, NAME, '.claude/agents/odd-helper.md'), '---\nname: odd-helper\nmodel: sonnet\nmaxTurns: 9\n---\nModel reason: t\nFlow role: build\n## DoD\nVerdict: PASS\n') });
  check('team (shipm): a non-privileged project-only agent is never "untrusted"', !r.p.team.untrusted.includes('odd-helper') && r.p.team.count === 6, JSON.stringify(r.p.team));
  r = await run({ extra: () => { fs.rmSync(path.join(DEV, NAME, '.claude/agents'), { recursive: true }); put(path.join(HOMEDIR, '.claude/agents/verifier.md'), agentMd('sonnet', 'test', true, 'verifier')); } });
  check('team (shipm): a user-level agent counts, so a project with no agents folder is NOT "no team" (count 1)', r.p.team.count === 1, JSON.stringify(r.p.team));
  fs.rmSync(HOMEDIR, { recursive: true, force: true });
  r = await run({ extra: () => fs.rmSync(path.join(WS, 'bin/shipm')) });
  check('team (fallback): bin/shipm missing falls back to agent-check: count and model-rule result as before, untrusted empty', r.p.team.count === 5 && r.p.team.bad.length === 0 && r.p.team.untrusted.length === 0, JSON.stringify(r.p.team));
  r = await run({ extra: () => { fs.writeFileSync(path.join(WS, 'bin/shipm'), '#!/bin/sh\necho not json\nexit 0\n'); put(path.join(DEV, NAME, '.claude/agents/bad-one.md'), '---\nmodel: inherit\n---\nbody\n'); } });
  check('team (fallback): bin/shipm printing junk falls back to agent-check (bad-one reported)', r.p.team.count === 6 && r.p.team.bad.length === 1 && /bad-one\.md/.test(r.p.team.bad[0]), JSON.stringify(r.p.team));
  { const t0 = Date.now(); r = await run({ extra: () => fs.writeFileSync(path.join(WS, 'bin/shipm'), '#!/bin/sh\nsleep 5\n') });
    check('team (fallback): a hanging bin/shipm is cut at 3 s and the check still answers', Date.now() - t0 < 6500 && r.p.team.count === 5, String(Date.now() - t0) + ' ' + JSON.stringify(r.p.team)); }
  r = await run({ extra: () => put(path.join(DEV, NAME, '.claude/agents/bad-one.md'), '---\nmodel: inherit\n---\nbody\n') });
  check('team (shipm): bad model is listed under bad with the file name (kind model only)', r.p.team.bad.length === 1 && /bad-one\.md/.test(r.p.team.bad[0]) && r.p.team.bad.every(l => !/unmarked shadow|\[dod\]/.test(l)), JSON.stringify(r.p.team));
  { // the cache key includes the manifest mtime: a changed manifest runs the check again
    const fx = path.join(WS, 'bin/shipm');
    await run({}); fs.writeFileSync(fx, '#!/bin/sh\necho SHOULD-NOT-RUN\nexit 0\n'); fs.chmodSync(fx, 0o755);
    let p2 = (await collect()).projects.find(p => p.name === NAME);
    check('team (shipm): cached while agent files and manifest are unchanged', p2.team.count === 5, JSON.stringify(p2.team));
    put(path.join(STATE, 'v1', 'agents.json'), { v: 1, ts: 2, writer: 'shipmiracle-agents', data: { agents: {} } });
    p2 = (await collect()).projects.find(p => p.name === NAME);
    check('team (shipm): a new manifest mtime invalidates the cache (the junk script now runs, so the fallback answers)', p2.team.count === 5, JSON.stringify(p2.team));
  }

  // ---- resolveAgent: same semantics as shipmiracle/agents.py resolve (T6) ----
  {
    const PRJ = path.join(ROOT, 'rprj'), UD = path.join(HOMEDIR, '.claude/agents');
    const wipe = () => { fs.rmSync(PRJ, { recursive: true, force: true }); fs.rmSync(HOMEDIR, { recursive: true, force: true }); };
    wipe();
    let a = resolveAgent(PRJ, 'qa-engineer');
    check('resolve: a missing file for an old name resolves by alias to the new role (verifier / test)', a && a.layer === 'alias' && a.alias_of === 'verifier' && a.role === 'test', JSON.stringify(a));
    put(path.join(UD, 'planner.md'), agentMd('opus', 'plan', true, 'planner'));
    a = resolveAgent(PRJ, 'planner'); check('resolve: user layer', a && a.layer === 'user' && a.role === 'plan' && a.model === 'opus', JSON.stringify(a));
    put(path.join(PRJ, '.claude/agents/planner.md'), agentMd('sonnet', 'build', true, 'planner'));
    a = resolveAgent(PRJ, 'planner'); check('resolve: project beats user, never merged (role and model from the project file)', a && a.layer === 'project' && a.role === 'build' && a.model === 'sonnet', JSON.stringify(a));
    put(path.join(HOMEDIR, '.claude/plugins/cache/mk/feature-dev/1.0/agents/code-explorer.md'), agentMd('sonnet', 'support'));
    put(path.join(HOMEDIR, '.claude/plugins/cache/mk/feature-dev/1.0/agents/code-reviewer.md'), agentMd('sonnet', 'review'));
    a = resolveAgent(PRJ, 'feature-dev:code-explorer'); check('resolve: plugin name a:b resolves to the plugin layer, role support', a && a.layer === 'plugin' && a.role === 'support', JSON.stringify(a));
    check('resolve: a bare plugin agent name is ambiguous (null); a plugin that has no such agent is null', resolveAgent(PRJ, 'code-explorer') === null && resolveAgent(PRJ, 'other:code-explorer') === null);
    check('resolve: unknown, empty, path traversal, non-string -> null', [resolveAgent(PRJ, 'no-such-agent'), resolveAgent(PRJ, ''), resolveAgent(PRJ, '../planner'), resolveAgent(PRJ, 'a/b'), resolveAgent(PRJ, null), resolveAgent(PRJ, 7)].every(x => x === null));
    check('resolve: the lens of the two old reviewers', resolveAgent(PRJ, 'security-reviewer').lens === 'risk' && resolveAgent(PRJ, 'independent-reviewer').lens === 'correctness' && resolveAgent(PRJ, 'ux-designer').lens === null);
    check('resolve: Object.prototype names do not hit the alias/default tables', ['constructor', '__proto__', 'toString', 'hasOwnProperty'].every(k => resolveAgent(PRJ, k) === null));
    put(path.join(PRJ, '.claude/agents/odd-helper.md'), '---\nmodel: sonnet\n---\nFlow role: wizard\n');
    check('resolve: an unknown role word is support', resolveAgent(PRJ, 'odd-helper').role === 'support');
    wipe();
  }
  {
    const parsed = {}; const src = fs.readFileSync(path.join(__dirname, '../shipmiracle/agents.py'), 'utf8'); const blk = src.match(/^ALIASES = \{([\s\S]*?)\n\}/m)[1];
    for (const m of blk.matchAll(/"([a-z-]+)":\s*"([a-z-]+)"/g)) parsed[m[1]] = m[2];
    check('ALIASES in data.js equal ALIASES in shipmiracle/agents.py (10 entries)', Object.keys(parsed).length === 10 && JSON.stringify(Object.entries(parsed).sort()) === JSON.stringify(Object.entries(ALIASES).sort()), JSON.stringify(parsed));
    const CASES = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures/agents/resolve_cases.json'), 'utf8')).cases; let bad = [];
    for (const c of CASES) {
      const PRJ = path.join(ROOT, 'case'), UD = path.join(HOMEDIR, '.claude/agents');
      fs.rmSync(PRJ, { recursive: true, force: true }); fs.rmSync(HOMEDIR, { recursive: true, force: true }); fs.mkdirSync(PRJ, { recursive: true });
      for (const [fn, role] of Object.entries(c.project)) put(path.join(PRJ, '.claude/agents', fn + '.md'), role ? agentMd('sonnet', role, true, (c.project_names || {})[fn] || fn) : '---\nname: ' + fn + '\nmodel: sonnet\n---\nModel reason: x\n');
      for (const [fn, role] of Object.entries(c.user)) put(path.join(UD, fn + '.md'), agentMd('sonnet', role, true, fn));
      for (const pe of c.plugins) { const [pl, ag] = pe.split(':'); put(path.join(HOMEDIR, '.claude/plugins/cache/mk', pl, 'v1/agents', ag + '.md'), agentMd('sonnet', 'support')); }
      const x = resolveAgent(PRJ, c.name);
      const ok = c.layer === null ? x === null : !!x && x.name === c.name && x.layer === c.layer && x.role === c.claimed && x.alias_of === (c.alias_of || null) && x.lens === (c.lens || null);
      if (!ok) bad.push(c.id + ' ' + JSON.stringify(x));
    }
    fs.rmSync(path.join(ROOT, 'case'), { recursive: true, force: true }); fs.rmSync(HOMEDIR, { recursive: true, force: true });
    check(`every shared resolve case (${CASES.length}) gives the same name/layer/role/alias/lens in JS as in Python`, CASES.length >= 25 && bad.length === 0, bad.join('; '));
  }
  r = await run({ state: 'working', agents: [{ type: 'qa-engineer', model: '' }], extra: () => fs.rmSync(path.join(DEV, NAME, '.claude/agents'), { recursive: true }) });
  check('flow strip: an old name with no file shows its new role (label "qa-engineer (verifier)", stage qa), type stays the raw name', r.p.flow.running[0].label === 'qa-engineer (verifier)' && r.p.flow.running[0].type === 'qa-engineer' && r.p.flow.stage === 'qa', JSON.stringify(r.p.flow.running));
  r = await run({ state: 'working', agents: [{ type: 'verifier', model: '' }], extra: () => fs.rmSync(path.join(DEV, NAME, '.claude/agents'), { recursive: true }) });
  check('flow strip: a new role name resolves by default (verifier -> qa) and has no alias suffix', r.p.flow.stage === 'qa' && r.p.flow.running[0].label === 'verifier', JSON.stringify(r.p.flow));
  r = await run({ state: 'working', agents: [{ type: 'qa-engineer', model: '' }] });
  check('flow strip: an old name WITH its own project file is that agent: no alias suffix', r.p.flow.running[0].label === 'qa-engineer', JSON.stringify(r.p.flow.running));

  // ---- limit, level switch ----
  r = await run({ limit: true }); check('limitUntil from limit.json', Math.abs(r.p.limitUntil - (T + 3600)) < 120, String(r.p.limitUntil));
  r = await run({}); check('limitUntil 0 without a limit', r.p.limitUntil === 0);
  r = await run({ extra: t => put(path.join(STATE, NAME + '.limit.json'), { until: t - 10 }) }); check('limitUntil 0 when the limit passed', r.p.limitUntil === 0);
  r = await run({ state: 'idle' }); check('levelSwitch ok when nothing is working', r.d.levelSwitch.ok === true && r.p.levelSwitch.ok === true);
  r = await run({ state: 'working', agents: [{ type: 'frontend-engineer' }] }); check('levelSwitch refused while a project is working, with a reason', r.d.levelSwitch.ok === false && /working/.test(r.d.levelSwitch.why) && r.d.levelSwitch.why.includes(NAME) && r.p.levelSwitch.ok === false);
  r = await run({ state: 'needs-input', message: 'q' }); check('levelSwitch refused while a project needs input', r.d.levelSwitch.ok === false && r.d.levelSwitch.why.length > 10);
  r = await run({ extra: () => { put(path.join(WS, 'config/ci-hold.txt'), NAME + '\n'); } }); check('levelSwitch refused for a held project, other projects stay ok', r.d.levelSwitch.ok === true && r.p.levelSwitch.ok === false && /held/.test(r.p.levelSwitch.why));
  r = await run({ extra: t => { put(path.join(STATE, NAME + '.json'), { state: 'working', ts: t - 7200 }); } }); check('M4: a raw "working" state blocks the switch even after the 30-min demotion', r.p.state === 'idle' && r.d.levelSwitch.ok === false && /is working/.test(r.d.levelSwitch.why));
  r = await run({ limit: true }); check('M4: a future usage limit blocks the switch', r.d.levelSwitch.ok === false && /usage limit/.test(r.d.levelSwitch.why) && r.d.levelSwitch.why.includes(NAME));
  r = await run({ agents: [{ type: 'frontend-engineer', ago: 3600 }] }); check('M4: an agents.json entry under 3 h old blocks the switch', r.d.levelSwitch.ok === false && /agent running/.test(r.d.levelSwitch.why));
  r = await run({ agents: [{ type: 'frontend-engineer', ago: 4 * 3600 }] }); check('M4: an agents.json entry over 3 h old does not', r.d.levelSwitch.ok === true);
  r = await run({ flow: { build_ts: T - 5 } }); check('M4: a flow file under 3 min old blocks the switch', r.d.levelSwitch.ok === false && /chat activity/.test(r.d.levelSwitch.why));
  r = await run({ extra: t => put(path.join(STATE, 'flow.sid1.json'), { project: NAME, ts: t - 60 }) }); check('P1: activity 1 min ago blocks, says idle in 2 min', r.p.levelSwitch.ok === false && /had chat activity 1 min ago; idle in 2 min\./.test(r.p.levelSwitch.why + '.'), r.p.levelSwitch.why);
  r = await run({ extra: t => put(path.join(STATE, 'flow.sid1.json'), { project: NAME, ts: t - 170 }) }); check('P1: activity 170 s ago says idle in 1 min', r.p.levelSwitch.ok === false && /idle in 1 min/.test(r.p.levelSwitch.why), r.p.levelSwitch.why);
  r = await run({ extra: t => put(path.join(STATE, 'flow.sid1.json'), { project: NAME, ts: t - 240 }) }); check('P1: activity 4 min ago does not block', r.p.levelSwitch.ok === true && r.d.levelSwitch.ok === true, r.p.levelSwitch.why);
  r = await run({ state: 'idle', extra: t => { fs.mkdirSync(path.join(DEV, 'zzf-other', '.git'), { recursive: true }); put(path.join(STATE, 'zzf-other.json'), { state: 'working', ts: t, message: '' }); } });
  { const o = r.d.projects.find(p => p.name === 'zzf-other'); check('P1: project X idle while Y working -> X ok, Y blocked with its own name', !!o && r.p.levelSwitch.ok === true && o.levelSwitch.ok === false && o.levelSwitch.why.includes('zzf-other') && /working/.test(o.levelSwitch.why), JSON.stringify([r.p.levelSwitch, o && o.levelSwitch])); }
  r = await run({ state: 'working', extra: t => { fs.mkdirSync(path.join(DEV, 'zzf-other', '.git'), { recursive: true }); put(path.join(STATE, 'zzf-other.json'), { state: 'idle', ts: t, message: '' }); } });
  { const o = r.d.projects.find(p => p.name === 'zzf-other'); check('P1: X working -> X blocked with reason, idle Y ok', r.p.levelSwitch.ok === false && /working/.test(r.p.levelSwitch.why) && !!o && o.levelSwitch.ok === true, JSON.stringify([r.p.levelSwitch, o && o.levelSwitch])); }
  r = await run({ extra: t => { fs.mkdirSync(path.join(DEV, 'zzf-other', '.git'), { recursive: true }); put(path.join(STATE, 'flow.o1.json'), { project: 'zzf-other', ts: t - 30 }); } });
  { const o = r.d.projects.find(p => p.name === 'zzf-other'); check('P1: recent chat in Y does not block X', r.p.levelSwitch.ok === true && !!o && o.levelSwitch.ok === false && /activity/.test(o.levelSwitch.why)); }
  r = await run({ extra: t => put(path.join(STATE, 'flow.old1.json'), { project: NAME, ts: t - 3 * 3600, integrity_logged: 'x' }) }); check('M4: integrity_logged in any flow file blocks the switch', r.d.levelSwitch.ok === false && /gate file/.test(r.d.levelSwitch.why));
  r = await run({ extra: t => put(path.join(STATE, 'flow.old1.json'), { project: NAME, ts: t - 3 * 3600, built_by: 'x' }) }); check('M4: an old quiet flow file does not block', r.d.levelSwitch.ok === true);
  for (const hs of ['limit', 'working', 'plan_approval', 'waiting_you']) { r = await run({ health: hs }); check('M4: health chat state ' + hs + ' blocks the switch', r.d.levelSwitch.ok === false && r.d.levelSwitch.why.includes(NAME), r.d.levelSwitch.why); }
  r = await run({ health: 'ok' }); check('M4: a calm health state does not block', r.d.levelSwitch.ok === true);
  r = await run({ state: 'working', agents: [{ type: 'frontend-engineer' }] }); check('D2: busy project: p.levelSwitch carries the same reason', r.p.levelSwitch.ok === false && r.p.levelSwitch.why === r.d.levelSwitch.why);
  r = await run({ extra: () => put(path.join(WS, 'config/ci-hold.txt'), NAME + '\n'), state: 'working' }); check('D2: held says held even when busy', /held/.test(r.p.levelSwitch.why));
  r = await run({ cfg: { default: 'strict', projects: { [NAME]: 'off' } } }); check('D2: off says off: change it by hand', /^The gate is off: change it by hand/.test(r.p.levelSwitch.why));
  r = await run({ cfg: { default: 'strict', projects: { [NAME]: 'off' } } }); check('a project at off is not switchable', r.p.levelSwitch.ok === false && r.p.levelSwitch.why.length > 5);

  // ---- creating / pnotice ----
  r = await run({ extra: t => put(path.join(STATE, 'project-creating.json'), { name: 'newthing', ts: t - 30 }) }); check('creating shown', r.d.creating && r.d.creating.name === 'newthing');
  r = await run({ extra: t => put(path.join(STATE, 'project-creating.json'), { name: 'newthing', ts: t - 400 }) }); check('creating ignored when older than 5 min', r.d.creating === null);
  r = await run({ extra: t => put(path.join(STATE, 'project-creating.json'), { name: 'newthing', ts: (t - 30) * 1000 }) }); check('creating accepts a millisecond ts', r.d.creating && r.d.creating.name === 'newthing');
  r = await run({}); check('no creating file = null', r.d.creating === null);
  r = await run({ extra: t => put(path.join(STATE, 'project-notice.json'), { ts: t - 60, text: 'Created x' }) }); check('pnotice shown', r.d.pnotice === 'Created x');
  r = await run({ extra: t => put(path.join(STATE, 'project-notice.json'), { ts: t - 25 * 3600, text: 'Old' }) }); check('pnotice ignored when older than 24 h', r.d.pnotice === '');
  r = await run({}); check('no pnotice = empty text', r.d.pnotice === '');

  // ---- m1: name-keyed tables survive project names like __proto__ and constructor ----
  r = await run({ state: 'idle', flow: { built_by: 'frontend-engineer', build_ts: T - 5 }, events: [{ ts: T, event: 'gate_tamper' }],
    extra: t => {
      fs.mkdirSync(path.join(DEV, 'constructor', '.git'), { recursive: true });
      put(path.join(STATE, 'flow.p1.json'), { project: '__proto__', ts: t - 20, built_by: 'x' }); put(path.join(STATE, 'flow.p2.json'), { project: 'constructor', ts: t - 10, built_by: 'ctor-builder', bypass: true });
      put(path.join(STATE, 'flow.p3.json'), { project: 'toString', ts: t - 10 }); put(path.join(STATE, 'flow.p4.json'), { project: 7, ts: t });
      put(path.join(STATE, 'ci.json'), {}); put(path.join(STATE, 'flow-events.jsonl'), [{ project: NAME, event: 'gate_tamper' }, { project: 'constructor', event: 'gate_tamper' }, { project: '__proto__', event: 'gate_tamper' }].map(e => JSON.stringify({ ts: t, ...e })).join('\n') + '\n');
    } });
  const ctor = r.d.projects.find(p => p.name === 'constructor');
  check('m1: a project folder named constructor is listed with its own flow data', !!ctor && ctor.flow.builtBy === 'ctor-builder' && ctor.flow.bypass === true && ctor.ci === null, ctor && JSON.stringify(ctor.flow.builtBy));
  check('m1: refusalsToday is a number for constructor and for the others', ctor && ctor.flow.refusalsToday === 1 && r.p.flow.refusalsToday === 1 && typeof r.p.flow.refusalsToday === 'number');
  check('m1: other projects keep their flow data and the activity signal', r.p.flow.builtBy === 'frontend-engineer' && r.p.levelSwitch.ok === false && /chat activity/.test(r.p.levelSwitch.why), r.p.levelSwitch.why);
  check('m1: a project without a folder of that name does not leak Object.prototype', r.p.team.count === 5 && typeof r.p.level === 'string' && r.p.approval === false);

  // ---- m6: agent files are read capped and only when regular ----
  const agentsDir = () => path.join(DEV, NAME, '.claude/agents');
  r = await run({ state: 'working', agents: [{ type: 'weird-engineer' }], extra: () => {
    const fifo = path.join(ROOT, 'fifo'); require('child_process').execFileSync('mkfifo', [fifo]); fs.symlinkSync(fifo, path.join(agentsDir(), 'weird-engineer.md'));
  } });
  check('m6: an agent file that is a symlink to a FIFO does not hang; role falls back to the name (engineer = build)', r.p.flow.stage === 'build', r.p.flow.stage);
  fs.rmSync(path.join(ROOT, 'fifo'), { force: true });
  r = await run({ state: 'working', agents: [{ type: 'big-agent' }], extra: () => {
    const big = Buffer.alloc(10 * 1024 * 1024, 'x'); big.write('Flow role: review\n', 70 * 1024);   // the role line sits past the 64 KB cap
    fs.writeFileSync(path.join(agentsDir(), 'big-agent.md'), big);
  } });
  check('m6: only the first 64 KB of an agent file is read (a role line at 70 KB is not seen)', r.p.flow.stage !== 'review', r.p.flow.stage);
  r = await run({ state: 'working', agents: [{ type: 'small-agent' }], extra: () => fs.writeFileSync(path.join(agentsDir(), 'small-agent.md'), 'model: sonnet\nmaxTurns: 20\nModel reason: x\nFlow role: test\n## DoD\nVerdict: PASS\n') });
  check('m6: a normal agent file is still read', r.p.flow.stage === 'qa', r.p.flow.stage);

  // ---- bad JSON never throws; old fields stay ----
  r = await run({ extra: () => {
    for (const f of [NAME + '.json', NAME + '.agents.json', NAME + '.mode.json', NAME + '.model.json', NAME + '.limit.json', 'health.json', 'project-creating.json', 'project-notice.json', 'flow.sid1.json', 'ci.json'])
      put(path.join(STATE, f), '{ broken');
    put(path.join(STATE, 'flow-events.jsonl'), '{ broken\n'); put(path.join(STATE, 'plan-pending.sid1'), '');
  } });
  check('malformed JSON everywhere: collect still works with safe defaults', !!r.p && r.p.flow.stage === '' && r.p.limitUntil === 0 && r.d.creating === null && r.d.pnotice === '' && r.p.level === 'strict');
  r = await run({ state: 'working', agents: [{ type: 'frontend-engineer', model: 'sonnet' }], model: 'Sonnet 5.5' });
  check('existing fields kept: state, live, agents, held, ideas, tokens', r.p.state === 'working' && r.p.live && r.p.live.model === 'Sonnet 5.5' && r.p.agents.length === 1 && r.p.agents[0].type === 'frontend-engineer' && r.p.held === false && !!r.p.ideas && !!r.p.tokens);
  check('internal "calm" state kept for a finished project', (await run({ state: 'done' })).p.state === 'calm');
  check('scratch fields are not leaked', r.p.mdl === undefined && r.p.mod === undefined);

  // ---- token ledger (ledger.summary.json) and the chat context files (context.<session>.json) ----
  const LED = (o = {}) => ({ version: 1, generated_at: now() - 60, day: '2026-10-20', today: { calls: 10, tokens: 263200000, share_calls_over_200k_pct: 20.0, share_tokens_over_200k_pct: 60 }, week: { calls: 100, tokens: 3181000000, share_calls_over_200k_pct: 37.1, share_tokens_over_200k_pct: 71 },
    by_project: { [NAME]: { today: 41000000, week: 90000000 } }, context_resets: { today: 1, week: 3 }, ...o });
  r = await run({});
  check('token_ledger_cache_reads: no summary file -> not fresh, labelled fallback source', r.d.ledger && r.d.ledger.fresh === false && r.d.ledger.source === 'transcripts' && r.d.ledger.why === 'missing' && r.p.tokens.ledgerDay === undefined, JSON.stringify(r.d.ledger));
  r = await run({ extra: () => put(path.join(STATE, 'ledger.summary.json'), LED()) });
  check('token_ledger_cache_reads: a summary under 15 min old is used (tokens incl. cache reads, share over 200k)', r.d.ledger.fresh === true && r.d.ledger.source === 'ledger' && r.d.ledger.today.tokens === 263200000 && r.d.ledger.today.overCallsPct === 20 && r.d.ledger.week.overTokensPct === 71, JSON.stringify(r.d.ledger));
  check('token_ledger_cache_reads: the project card gets its own ledger tokens', r.p.tokens.ledgerDay === 41000000 && r.p.tokens.ledgerWeek === 90000000 && typeof r.p.tokens.claudeDay === 'number');
  r = await run({ extra: () => put(path.join(STATE, 'ledger.summary.json'), LED({ generated_at: now() - 901 })) });
  check('a summary older than 15 min is not used', r.d.ledger.fresh === false && r.d.ledger.why === 'old' && r.p.tokens.ledgerDay === undefined);
  r = await run({ extra: () => put(path.join(STATE, 'ledger.summary.json'), LED({ generated_at: now() - 899 })) });
  check('just under 15 min is still used', r.d.ledger.fresh === true);
  for (const [nm, body] of [['corrupt', '{ broken'], ['no numbers', { today: {}, week: {} }], ['text instead of numbers', LED({ generated_at: 'now' })], ['null', 'null'], ['array', '[1]']]) {
    r = await run({ extra: () => put(path.join(STATE, 'ledger.summary.json'), body) });
    check('ledger summary ' + nm + ': fallback, no crash', r.d.ledger.fresh === false && !!r.p);
  }
  r = await run({ extra: () => put(path.join(STATE, 'ledger.summary.json'), LED({ today: { calls: 'x', tokens: -5, share_calls_over_200k_pct: 'a' }, by_project: { [NAME]: { today: 'x' } } })) });
  check('bad values inside the summary become 0 / null, never NaN', r.d.ledger.fresh === true && r.d.ledger.today.tokens === 0 && r.d.ledger.today.overCallsPct === null && r.p.tokens.ledgerDay === undefined, JSON.stringify(r.d.ledger));
  const CX = (o = {}) => ({ project: NAME, session: 's1', tokens: 312000, level: 'strong', ts: now() - 60, nudged: { soft: true, strong: true }, ...o });
  r = await run({ extra: () => put(path.join(STATE, 'context.s1.json'), CX()) });
  check('context file under 30 min old: p.context = {tokens, level}', r.p.context && r.p.context.tokens === 312000 && r.p.context.level === 'strong' && Object.keys(r.p.context).sort().join() === 'level,tokens', JSON.stringify(r.p.context));
  r = await run({ extra: () => put(path.join(STATE, 'context.s1.json'), CX({ ts: now() - 1801 })) });
  check('context file older than 30 min is ignored', r.p.context === undefined);
  r = await run({ extra: () => { put(path.join(STATE, 'context.old.json'), CX({ tokens: 250000, level: 'soft', ts: now() - 900 })); put(path.join(STATE, 'context.new.json'), CX({ tokens: 120000, level: 'none', ts: now() - 30 })); } });
  check('two chats of one project: the newest wins', r.p.context.tokens === 120000 && r.p.context.level === 'none', JSON.stringify(r.p.context));
  r = await run({ extra: () => { put(path.join(STATE, 'context.x1.json'), CX({ project: 'someone-else' })); put(path.join(STATE, 'context.x2.json'), '{ broken'); put(path.join(STATE, 'context.x3.json'), CX({ tokens: 'lots' })); put(path.join(STATE, 'context.x4.json'), CX({ ts: now() + 99999 })); put(path.join(STATE, 'context.x5.json'), CX({ level: 'evil<script>' })); put(path.join(STATE, 'context.a b.json'), CX()); put(path.join(STATE, 'context.x6.json'), CX({ project: 5 })); } });
  check('other project, corrupt, non-number tokens, future ts, odd file name, odd project: none attach (odd level -> none)', r.p.context && r.p.context.level === 'none' && r.p.context.tokens === 312000, JSON.stringify(r.p.context));
  r = await run({}); check('no context file: no p.context', r.p.context === undefined);

  // stack: CLAUDE.md first (managed block / Stack rules line), AGENTS.md for one release
  const MK = '<!-- SHIPMIRACLE-STANDARD BEGIN v2 (x) -->\nx\n<!-- SHIPMIRACLE-STANDARD END -->\n';
  const PD = path.join(DEV, NAME);
  r = await run({ extra: () => put(path.join(PD, 'CLAUDE.md'), '# p\n' + MK + '\n## Stack rules — iOS (Swift / SwiftUI)\n') });
  check('stack: a migrated CLAUDE.md with a Stack rules line wins', r.p.stack === 'ios', r.p.stack);
  r = await run({ extra: () => { put(path.join(PD, 'CLAUDE.md'), '# p\n' + MK); put(path.join(PD, 'AGENTS.md'), 'Stack rules — Python\n'); } });
  check('stack: CLAUDE.md without a Stack rules line falls back to AGENTS.md', r.p.stack === 'python', r.p.stack);
  r = await run({ extra: () => { put(path.join(PD, 'CLAUDE.md'), '# p\n' + MK + '\n## Stack rules — Web\n'); put(path.join(PD, 'AGENTS.md'), 'Stack rules — Python\n'); } });
  check('stack: CLAUDE.md is read before AGENTS.md', r.p.stack === 'web', r.p.stack);
  r = await run({ extra: () => put(path.join(PD, 'AGENTS.md'), 'Stack rules — Notes\n') });
  check('stack: old AGENTS.md alone still works', r.p.stack === 'notes', r.p.stack);

  // ---- P5c: playbook / change requests / autopilot / stage.refused in the panel data (data contract only; the UI is P7) ----
  const cp = require('child_process'); const crypto = require('crypto');
  Object.assign(process.env, { SHIPMIRACLE_CONFIG: path.join(ROOT, 'config'), SHIPMIRACLE_DEV: DEV, SHIPMIRACLE_WS: WS, GIT_AUTHOR_NAME: 't', GIT_AUTHOR_EMAIL: 't@e.x', GIT_COMMITTER_NAME: 't', GIT_COMMITTER_EMAIL: 't@e.x' });
  const PB = 'zzp-pb', PBD = path.join(DEV, PB);
  const sh = (cmd, args, cwd) => cp.execFileSync(cmd, args, { cwd, env: process.env, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] });
  const shipmiracleRun = (...a) => sh('python3', [path.join(WS, 'bin', 'shipm'), ...a], ROOT);
  const pidOfDir = d => crypto.createHash('sha256').update('shipmiracle-project:' + fs.realpathSync(d)).digest('hex').slice(0, 12);
  const mkPb = t => {
    fs.mkdirSync(PBD, { recursive: true }); sh('git', ['init', '-q'], PBD); put(path.join(PBD, 'a.txt'), '1\n'); sh('git', ['add', '-A'], PBD); sh('git', ['commit', '-q', '-m', 'init'], PBD);
    put(path.join(STATE, 'health.json'), { ts: t, chats: { [PB]: { chats: 0 } } });
    shipmiracleRun('playbook', 'set', 'type', 'software', '--project', PB); shipmiracleRun('cr', 'open', 'RTL fix on login', '--lane', 'full', '--project', PB);
  };
  r = await run({});
  check('P5c: a project with no .shipmiracle folder and no autopilot state: playbook, cr, stageLabels, nextAction, lastVerdict, autopilot are all null', ['playbook', 'cr', 'stageLabels', 'nextAction', 'lastVerdict', 'autopilot'].every(k => r.p[k] === null), JSON.stringify(r.p));
  const todayTs = now(), yesterday = now() - 86400 * 2;
  r = await run({ extra: t => {
    mkPb(t); const pid = pidOfDir(PBD);
    sh('python3', ['-c', 'import sys,time; sys.path.insert(0, sys.argv[1]); from shipmiracle.autopilot import state as ap; ap.update(sys.argv[2], lambda cur: ap.blank("a" * 64, int(time.time()) - 60), base=sys.argv[3])', path.join(WS), pid, STATE], ROOT);
    const ev = (ts, kind, proj) => JSON.stringify({ v: 1, ts, kind, project: proj, src: 'hooks', data: {} });
    put(path.join(STATE, 'v1', 'events.jsonl'), [ev(todayTs, 'stage.refused', pid), ev(todayTs, 'stage.refused', pid), ev(yesterday, 'stage.refused', pid), ev(todayTs, 'stage.refused', 'f'.repeat(12)), ev(todayTs, 'other.kind', pid), '{ broken stage.refused'].join('\n') + '\n');
  } });
  const q = r.d.projects.find(x => x.name === PB);
  check('P5c playbook: {type, level, autopilot, trusted, valid} from the trusted playbook', q && JSON.stringify(q.playbook) === JSON.stringify({ type: 'software', level: 'strict', autopilot: 'guided', trusted: true, valid: true }), JSON.stringify(q && q.playbook));
  check('P5c cr: the active CR first with id, title, status, stage, lane, label, verdict, waiting_on', q.cr.length === 1 && q.cr[0].id === 'CR-001' && q.cr[0].title === 'RTL fix on login' && q.cr[0].status === 'open' && q.cr[0].lane === 'full'
    && Object.keys(q.cr[0]).sort().join() === 'id,in_chat,label,lane,stage,status,title,verdict,waiting_on', JSON.stringify(q.cr));   // in_chat: added by the option C engine (shipm report panel cr[].in_chat), the test was stale
  check('P5c stageLabels: seven stages, approve is "OK"', q.stageLabels && Object.keys(q.stageLabels).join() === 'scope,plan,approve,do,verify,review,deliver' && q.stageLabels.approve === 'OK', JSON.stringify(q.stageLabels));
  check('P5c nextAction is the engine text; lastVerdict null before any verdict', typeof q.nextAction === 'string' && q.nextAction.startsWith('CR-001:') && q.lastVerdict === null, JSON.stringify([q.nextAction, q.lastVerdict]));
  check('P5c autopilot: the state snapshot (state "set", no charter, keys of the P6 contract)', q.autopilot && q.autopilot.state === 'set' && q.autopilot.charter === null && ['level', 'enabled', 'decisions', 'budget', 'time', 'stop', 'cr', 'branch', 'worktree', 'ended_reason'].every(k => k in q.autopilot), JSON.stringify(q.autopilot));
  check('P5c refusalsToday counts today\'s stage.refused events of this project only (2: not yesterday, not another project, not another kind, not a broken line)', q.flow.refusalsToday === 2, q.flow.refusalsToday);
  const other = r.d.projects.find(x => x.name === NAME);
  check('P5c: the other project stays null on every playbook field and has no refusals', other.playbook === null && other.autopilot === null && other.flow.refusalsToday === 0, JSON.stringify([other.playbook, other.flow.refusalsToday]));
  // an older workspace without `shipm report`, a failing command and junk output: all give null fields and never break the panel
  const stub = body => { fs.writeFileSync(path.join(WS, 'bin', 'shipm'), '#!/bin/sh\n' + body + '\n'); fs.chmodSync(path.join(WS, 'bin', 'shipm'), 0o755); };
  const keepStub = (t, body) => { mkPb(t); stub(body); };
  r = await run({ extra: t => { mkPb(t); fs.rmSync(path.join(WS, 'shipmiracle', 'report'), { recursive: true, force: true }); } });
  let q2 = r.d.projects.find(x => x.name === PB);
  check('P5c: a workspace without shipmiracle/report (old checkout) -> null fields, no crash', q2 && q2.playbook === null && q2.cr === null && !!r.d.projects.length, JSON.stringify(q2 && q2.playbook));
  r = await run({ extra: t => { mkPb(t); stub('echo "not json"'); } });
  q2 = r.d.projects.find(x => x.name === PB);
  check('P5c: junk output -> null fields', q2.playbook === null && q2.cr === null && q2.autopilot === null);
  r = await run({ extra: t => { mkPb(t); stub('exit 7'); } });
  q2 = r.d.projects.find(x => x.name === PB);
  check('P5c: exit code 7 -> null fields', q2.playbook === null);
  const COUNT = path.join(ROOT, 'count.txt');
  r = await run({ extra: t => { mkPb(t); stub('echo "$1" >> "' + COUNT + '"\necho \'{"v":1,"playbook":{"type":"app","level":"warn","autopilot":"manual","trusted":false,"valid":true},"cr":[{"id":"CR-007"}],"stageLabels":null,"nextAction":"hi","lastVerdict":null,"autopilot":null}\''); } });
  await collect(); await collect();
  q2 = r.d.projects.find(x => x.name === PB);
  const calls = fs.readFileSync(COUNT, 'utf8').trim().split('\n').filter(x => x === 'report').length;
  check('P5c: a valid answer is used as it is and cached (3 collects, one `report` process)', q2.playbook.type === 'app' && q2.cr[0].id === 'CR-007' && q2.nextAction === 'hi' && calls === 1, [calls, JSON.stringify(q2.playbook)]);
  const big = JSON.stringify({ v: 1, playbook: { type: 'app', level: 'warn', autopilot: 'manual', trusted: true, valid: true }, cr: Array.from({ length: 9 }, (_, i) => ({ id: 'CR-00' + i })), stageLabels: null, nextAction: 5, lastVerdict: null, autopilot: 'x' });
  r = await run({ extra: t => { mkPb(t); stub("echo '" + big + "'"); } });
  q2 = r.d.projects.find(x => x.name === PB);
  check('P5c: cr is cut to 5, a non-text nextAction and a non-object autopilot become null', q2.cr.length === 5 && q2.nextAction === null && q2.autopilot === null, JSON.stringify([q2.cr.length, q2.nextAction, q2.autopilot]));

  fs.rmSync(ROOT, { recursive: true, force: true });
  console.log(`\n${n - fails}/${n} passed`); process.exit(fails ? 1 : 0);
})().catch(e => { console.log('FAIL crashed ' + e.stack); process.exit(1); });
