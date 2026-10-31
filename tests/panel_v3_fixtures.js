// Fixtures for the panel v3 UI test and preview.js --v3: one project per card state of the UX spec (section 2), in the shape data.js produces
// (p.playbook / p.cr / p.stageLabels / p.nextAction / p.lastVerdict / p.autopilot are the committed `shipm report panel` data contract).
const NAMES = {
  software: ['Brief', 'Plan', 'OK', 'Build', 'Test', 'Review', 'Ship'], app: ['Brief', 'Plan', 'OK', 'Build', 'Test', 'Review', 'Ship'],
  content: ['Brief', 'Plan', 'OK', 'Write', 'Check', 'Review', 'Post'], research: ['Brief', 'Plan', 'OK', 'Draft', 'Check', 'Review', 'Send'],
  ops: ['Brief', 'Plan', 'OK', 'Change', 'Trial', 'Review', 'Apply'], notes: ['Brief', 'Plan', 'OK', 'Write', 'Check', 'Review', 'File']
};
const IDS = ['scope', 'plan', 'approve', 'do', 'verify', 'review', 'deliver'];
const now = Date.now() / 1000;
const labels = type => Object.fromEntries(IDS.map((id, i) => [id, NAMES[type][i]]));
const base = { dir: '/x', stack: 'web', state: 'idle', message: '', agents: [], model: '', next: '', dirty: 0, ahead: 0, pushFailed: false, lastCommit: now - 7200, tokens: { claudeDay: 41000, claudeWeek: 1 }, live: null, held: false, active: false, chatOpen: false, ideas: { open: [], evaluated: [], done: 0, dropped: 0 }, level: 'strict', approval: false, limitUntil: 0, team: { count: 11, bad: [] } };
const steps = () => ({ scope: 'next', plan: 'next', ok: 'next', build: 'next', qa: 'next', review: 'next' });
const flow = (o = {}) => ({ stage: '', steps: steps(), running: [], plannedBy: '', builtBy: '', qaBy: '', qaState: '', planNotByArchitect: false, outside: [], integrity: false, bypass: false, refusalsToday: 0, mismatch: false, ...o });
const pb = (type, autopilot = 'guided') => ({ type, level: 'strict', autopilot, trusted: true, valid: true });
const cr = (id, title, status, stage, o = {}) => ({ id, title, status, stage, lane: 'full', label: NAMES.software[IDS.indexOf(stage)] || stage, verdict: null, waiting_on: null, ...o });
const mk = (name, type, o = {}) => ({ ...base, name, dir: '/x/' + name, stack: type, playbook: pb(type), stageLabels: labels(type), cr: [], nextAction: null, lastVerdict: null, autopilot: null, flow: flow(), ...o });
const run = (type, model) => flow({ running: [{ type, model, label: type }] });
const apState = (o = {}) => ({ state: 'running', level: 'full', enabled: true, charter: { id: 'ch-1', goal: 'ship', scope: ['src/'], ends: ['CR-012'], set_by: 'owner', sha8: 'abcd1234' }, decisions: 3, budget: { used_pct: 4.1, cap_pct: 10, source: 'plan' }, time: { left_s: 4320, cap_s: 10800 }, stop: null, cr: 'CR-012', branch: 'auto/cr-012', worktree: null, ended_reason: null, ...o });

// The 16 card states of the spec. `primary` is the label and key the card must show; `state` is data-state.
const STATES = [
  { state: 'idle', primary: ['open', 'Open chat'], p: mk('idle-app', 'software') },
  { state: 'scoping', primary: ['open', 'Open chat'], p: mk('scope-app', 'software', { state: 'working', cr: [cr('CR-012', 'RTL fix', 'open', 'scope')], flow: run('product-analyst', 'sonnet') }) },
  { state: 'planning', primary: ['open', 'Open chat'], p: mk('plan-app', 'app', { state: 'working', cr: [cr('CR-012', 'RTL fix', 'open', 'plan')], flow: run('planner', 'opus') }) },
  { state: 'approval', primary: ['plan', 'Review plan'], p: mk('approve-app', 'software', { state: 'needs-input', cr: [cr('CR-013', 'Export report', 'open', 'approve', { waiting_on: 'owner' }), cr('CR-014', 'Dark mode', 'queued', 'scope')], nextAction: 'CR-013: Waiting on owner: approve the plan.' }) },
  { state: 'building', primary: ['open', 'Open chat'], p: mk('build-app', 'software', { state: 'working', agents: [{ type: 'builder-frontend', model: 'sonnet', mins: 12 }], cr: [cr('CR-012', 'RTL fix', 'open', 'do'), cr('CR-013', 'Export', 'queued', 'scope'), cr('CR-014', 'Dark mode', 'queued', 'scope'), cr('CR-015', 'Login', 'queued', 'scope')], flow: run('builder-frontend', 'sonnet') }) },
  { state: 'verifying', primary: ['open', 'Open chat'], p: mk('test-app', 'software', { state: 'working', cr: [cr('CR-012', 'RTL fix', 'open', 'verify')], flow: run('verifier', 'sonnet') }) },
  { state: 'verify-fail', primary: ['open', 'Open chat'], p: mk('fail-app', 'software', { state: 'working', cr: [cr('CR-012', 'RTL fix', 'open', 'do', { verdict: 'FAIL' })], lastVerdict: { stage: 'verify', word: 'FAIL', counts: { passed: 212, failed: 2, total: 214 }, report: 'docs/reports/cr-012-verify.md' }, flow: run('builder-frontend', 'sonnet') }) },
  { state: 'verify-twice', primary: ['decide', 'Decide'], p: mk('twice-app', 'software', { state: 'needs-input', cr: [cr('CR-020', 'Search', 'blocked', 'verify', { verdict: 'BLOCKED', waiting_on: 'owner' })], lastVerdict: { stage: 'verify', word: 'BLOCKED', counts: null, report: null } }) },
  { state: 'reviewing', primary: ['open', 'Open chat'], p: mk('review-app', 'software', { state: 'working', cr: [cr('CR-012', 'RTL fix', 'open', 'review')], lastVerdict: { stage: 'verify', word: 'PASS', counts: { passed: 214, failed: 0, total: 214 }, report: 'docs/reports/cr-012-verify.md', date: '2026-10-20T10:00:00Z' }, flow: run('reviewer', 'opus') }) },
  { state: 'delivered', primary: ['open', 'Open chat'], p: mk('done-app', 'software', { cr: [{ ...cr('CR-012', 'RTL fix', 'delivered', 'learn'), verdict: 'PASS' }], lastVerdict: { stage: 'verify', word: 'PASS', counts: { passed: 214, failed: 0, total: 214 }, report: 'docs/reports/cr-012-verify.md' } }) },
  { state: 'frozen', primary: ['fix', 'Fix'], p: mk('frozen-app', 'software', { state: 'working', live: { phase: 'stalled', idle: 1080 }, health: [{ id: 'frozen_chat:frozen-app', kind: 'frozen_chat', severity: 'red', title: 'Chat frozen', why: 'No output', mode: 'fix' }], cr: [cr('CR-012', 'RTL fix', 'open', 'do')] }) },
  { state: 'limit', primary: ['wait', 'Wait · back'], p: mk('limit-app', 'software', { limitUntil: Math.floor(now + 3600), cr: [cr('CR-012', 'RTL fix', 'open', 'do')] }) },
  { state: 'integrity', primary: ['fix', 'Fix'], p: mk('gate-app', 'software', { state: 'working', flow: flow({ integrity: 'blocked' }), cr: [cr('CR-012', 'RTL fix', 'open', 'do')] }) },
  { state: 'autopilot', primary: ['open', 'Open chat'], p: mk('auto-app', 'software', { state: 'working', playbook: pb('software', 'full'), autopilot: apState(), cr: [cr('CR-012', 'RTL fix', 'open', 'do')], flow: run('builder-backend', 'sonnet') }) },
  { state: 'hardstop', primary: ['decide', 'Decide'], p: mk('stop-app', 'software', { state: 'needs-input', playbook: pb('software', 'full'), autopilot: apState({ state: 'paused', stop: { id: 'H-1a2b3c', rule: 'push_public', text: 'autopilot wants to push publicly', ts: 1 } }), cr: [cr('CR-012', 'RTL fix', 'open', 'deliver')] }) },
  { state: 'noplaybook', primary: ['open', 'Open chat'], p: { ...base, name: 'legacy-app', dir: '/x/legacy-app', stack: 'python', playbook: null, cr: null, stageLabels: null, nextAction: null, lastVerdict: null, autopilot: null, flow: flow() } }
];
// Extra projects: every type with a CR in the 4th stage (strip names), a queued CR only (Start CR-n), a fast lane, an Arabic title, a held project.
const TYPES = ['software', 'app', 'content', 'research', 'ops', 'notes'].map(t => ({ type: t, p: mk('type-' + t, t, { state: 'working', cr: [cr('CR-001', 'Task', 'open', 'verify')], flow: run('verifier', 'sonnet') }) }));
const EXTRA = {
  queued: mk('queued-app', 'software', { cr: [cr('CR-013', 'Export report', 'queued', 'scope')] }),
  fast: mk('fast-app', 'software', { state: 'working', cr: [cr('CR-030', 'Typo', 'open', 'do', { lane: 'fast' })], flow: run('builder-frontend', 'sonnet') }),
  arabic: mk('arabic-app', 'content', { cr: [cr('CR-001', 'إصلاح RTL fix on login', 'open', 'do')], state: 'working', flow: run('writer', 'sonnet') }),
  held: mk('held-app', 'software', { held: true })
};
// Option C (until I disable it): data fields of autopilot-scope-design section 8 (autopilot.until / reason / seg_left_s / day / waiting[]); the engine commands do not exist yet.
const cState = (o = {}) => apState({ until: 'disabled', state: 'running', time: null, charter: { id: 'ch-2', goal: 'standing', scope: ['src/'], ends: ['CR-012', 'CR-013'], set_by: 'owner', sha8: 'c0ffee00' }, seg_left_s: 13 * 3600 - 600, day: { used_pct: 2, cap_pct: 4 }, budget: { used_pct: 6, cap_pct: 10, source: 'plan' }, waiting: [{ id: 'CR-015', title: 'Login page', in_chat: true }], reason: '', ...o });
const cProj = (name, o = {}, crs = [cr('CR-012', 'RTL fix', 'open', 'do')]) => mk(name, 'software', { state: 'working', playbook: pb('software', 'full'), cr: crs, flow: run('builder-backend', 'sonnet'), ...o });
const C_STATES = [
  { key: 'running', p: cProj('c-run', { autopilot: cState() }) },
  { key: 'checkpoint', slot: 'Keep going', cmd: 'checkpoint', p: cProj('c-check', { state: 'needs-input', autopilot: cState({ state: 'paused', reason: 'checkpoint', seg_left_s: 0 }) }) },
  { key: 'day_limit', slot: 'Keep going', cmd: 'checkpoint', off: true, p: cProj('c-day', { autopilot: cState({ state: 'paused', reason: 'day_limit', seg_left_s: 6 * 3600 }) }) },
  { key: 'week_limit', slot: 'Keep going', cmd: 'checkpoint', off: true, p: cProj('c-week', { autopilot: cState({ state: 'paused', reason: 'week_limit' }) }) },
  { key: 'qa_fail', slot: 'Resume', cmd: 'resume', p: cProj('c-qa', { state: 'needs-input', autopilot: cState({ state: 'paused', reason: 'qa_fail', cr: 'CR-013' }) }, [cr('CR-013', 'Export', 'open', 'verify')]) },
  { key: 'review_reject', slot: 'Resume', cmd: 'resume', p: cProj('c-rev', { state: 'needs-input', autopilot: cState({ state: 'paused', reason: 'review_reject', cr: 'CR-013' }) }, [cr('CR-013', 'Export', 'open', 'review')]) },
  { key: 'unknown_request', slot: 'Resume', cmd: 'resume', p: cProj('c-unk', { state: 'needs-input', autopilot: cState({ state: 'paused', reason: 'unknown_request', cr: 'CR-013' }) }, [cr('CR-013', 'Export', 'open', 'do')]) },
  { key: 'waiting', p: cProj('c-wait', { state: 'idle', flow: flow(), autopilot: cState({ cr: null, reason: 'waiting' }) }, []) },
  { key: 'lapsed', p: cProj('c-lapsed', { state: 'idle', flow: flow(), autopilot: cState({ state: 'ended', ended_reason: 'lapsed', waiting: [] }) }, []) }
];
module.exports = { C_STATES, cState, cProj, STATES, TYPES, EXTRA, NAMES, IDS, base, mk, cr, pb, flow, run, apState };
