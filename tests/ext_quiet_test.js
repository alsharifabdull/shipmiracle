// F9 quiet fact in data.js (UX addendum 5c, acceptance 23): p.progress {ts, src} is the newest of stage change, flow step, report, commit, STATUS and agent start/finish;
// p.quiet {min, tests} is set only for a working, healthy chat without a stall item, not set aside, whose progress is at least quiet_progress_min old (10-240, default 30).
// A transcript write alone is not progress. Fixture folders in a temp dir; no Shipmiracle process is started (the fixture project has no .shipmiracle folder).
// Run: node tests/ext_quiet_test.js
require('./shipmiracle_isolation').apply();
const fs = require('fs'), os = require('os'), path = require('path'), crypto = require('crypto');
const ROOT = fs.mkdtempSync(path.join(os.tmpdir(), 'shipmiracle-quiet-'));
const STATE = path.join(ROOT, 'state'), DEV = path.join(ROOT, 'dev'), WS = path.join(DEV, 'AI-Workspace');
delete process.env.CLAUDECODE;
Object.assign(process.env, { SHIPMIRACLE_TEST: '1', SHIPMIRACLE_EXT_STATE: STATE, SHIPMIRACLE_EXT_DEV: DEV, SHIPMIRACLE_EXT_WS: WS, SHIPMIRACLE_STATE: STATE });
const DATA = require(path.join(__dirname, '../vscode-ext/shipmiracle-panel/data.js'));
let fails = 0; const check = (name, c, info = '') => { console.log((c ? 'PASS ' : 'FAIL ') + name + (c ? '' : ' ' + info)); if (!c) fails++; };
const NAME = 'zzq-card', DIR = path.join(DEV, NAME), now = () => Date.now() / 1000;
const put = (f, o) => { fs.mkdirSync(path.dirname(f), { recursive: true }); fs.writeFileSync(f, typeof o === 'string' ? o : JSON.stringify(o)); };
const old = (f, minAgo) => { const t = now() - minAgo * 60; fs.utimesSync(f, t, t); };
let pid = '';
const QUIET_MIN = 40;                                           // every progress source is made this old unless a case says otherwise

// World: working chat, healthy (watcher says ok + working), every progress source 40 min old. o.* adds one change.
async function world(o = {}) {
  fs.rmSync(STATE, { recursive: true, force: true }); fs.rmSync(DEV, { recursive: true, force: true });
  fs.mkdirSync(path.join(WS, 'config'), { recursive: true }); fs.mkdirSync(path.join(DIR, '.git', 'logs'), { recursive: true }); fs.mkdirSync(path.join(DIR, 'docs'), { recursive: true }); fs.mkdirSync(STATE, { recursive: true });
  pid = crypto.createHash('sha256').update('shipmiracle-project:' + fs.realpathSync(DIR)).digest('hex').slice(0, 12);
  const t = now();
  put(path.join(STATE, NAME + '.json'), { state: o.state || 'working', ts: t, message: '' });
  put(path.join(STATE, 'health.json'), { ts: t, chats: { [NAME]: { state: o.chat || 'ok', working: o.chatWorking !== false } }, items: (o.items || []).map(k => ({ id: k + ':' + NAME, kind: k, project: NAME, severity: 'amber', title: k })) });
  put(path.join(DIR, '.git', 'logs', 'HEAD'), 'x'); old(path.join(DIR, '.git', 'logs', 'HEAD'), o.commitAge || QUIET_MIN);
  put(path.join(DIR, 'docs', 'STATUS.md'), '# s\n\nUpdated: today\n'); old(path.join(DIR, 'docs', 'STATUS.md'), o.statusAge || QUIET_MIN);
  put(path.join(STATE, NAME + '.agents.json'), o.agents ? Object.fromEntries(o.agents.map((a, i) => ['ag' + i, { type: a.type, model: 'sonnet', started: t - (a.startedAgo || QUIET_MIN * 60) }])) : {}); old(path.join(STATE, NAME + '.agents.json'), o.agentsAge || QUIET_MIN);
  put(path.join(STATE, 'v1', 'cr', pid + '.jsonl'), '{}\n'); old(path.join(STATE, 'v1', 'cr', pid + '.jsonl'), o.stageAge || QUIET_MIN);
  put(path.join(STATE, 'flow.sid1.json'), { project: NAME, ts: t, arch_ts: t - (o.flowAge || QUIET_MIN) * 60, build_ts: t - (o.flowAge || QUIET_MIN) * 60 });
  if (o.report) put(path.join(STATE, 'v1', 'reports', 'index.json'), { v: 1, items: [{ id: 'r1', kind: 'stage', project: NAME, verdict: 'PASS', ts: Math.floor(t - o.report * 60), title: 'Test report', path: '/x' }] });
  if (o.limit) put(path.join(STATE, NAME + '.limit.json'), { until: t + 3600, ts: t });
  if (o.pending) put(path.join(STATE, 'plan-pending.sid1'), 'x');
  if (o.cfg) put(path.join(WS, 'config', 'watch.json'), o.cfg);
  if (o.transcript) { const d = path.join(os.homedir(), '.claude', 'projects', DIR.replace(/[^A-Za-z0-9]/g, '-')); put(path.join(d, 's.jsonl'), '{"type":"assistant"}\n'); }
  if (o.after) o.after();
  const d = await DATA.collect(); return d.projects.find(p => p.name === NAME);
}

(async () => {
  let p = await world();
  check('baseline: all sources 40 min old -> quiet min 40, progress has a source', p.quiet && p.quiet.min >= 39 && p.quiet.min <= 41 && p.progress && p.progress.ts > 0 && ['stage', 'flow', 'report', 'commit', 'status', 'agent'].includes(p.progress.src), JSON.stringify([p.quiet, p.progress]));
  check('quiet carries no tests number when no test agent runs', p.quiet && p.quiet.tests === null);

  // ---- threshold: shown at 30, hidden at 29 (default); quiet_progress_min honoured, clamped to 10-240
  const atAge = async (min, cfg) => world({ commitAge: min, statusAge: min, agentsAge: min, stageAge: min, flowAge: min, cfg });
  p = await atAge(30.2); check('30 min of no progress -> shown (default threshold 30)', !!p.quiet && p.quiet.min === 30, JSON.stringify(p.quiet));
  p = await atAge(29); check('29 min -> hidden', p.quiet === null, JSON.stringify(p.quiet));
  p = await atAge(12, { quiet_progress_min: 10 }); check('quiet_progress_min 10 -> shown at 12 min', !!p.quiet);
  p = await atAge(9, { quiet_progress_min: 10 }); check('quiet_progress_min 10 -> hidden at 9 min', p.quiet === null);
  p = await atAge(100, { quiet_progress_min: 240 }); check('quiet_progress_min 240 -> hidden at 100 min', p.quiet === null);
  p = await atAge(241, { quiet_progress_min: 240 }); check('quiet_progress_min 240 -> shown at 241 min', !!p.quiet);
  p = await atAge(15, { quiet_progress_min: 1 }); check('quiet_progress_min below 10 is raised to 10 (shown at 15, hidden at 9)', !!p.quiet && (await atAge(9, { quiet_progress_min: 1 })).quiet === null);
  p = await atAge(100, { quiet_progress_min: 100000 }); check('quiet_progress_min above 240 is lowered to 240 (hidden at 100)', p.quiet === null);
  p = await atAge(50, { quiet_progress_min: 'soon' }); check('a non-number setting falls back to 30', !!p.quiet && p.quiet.min >= 49);
  check('quietThreshold(): 10..240, default 30', [DATA.quietThreshold({ quiet_progress_min: 10 }), DATA.quietThreshold({ quiet_progress_min: 240 }), DATA.quietThreshold({}), DATA.quietThreshold(null), DATA.quietThreshold({ quiet_progress_min: 5 }), DATA.quietThreshold({ quiet_progress_min: 999 })].join() === '10,240,30,30,10,240');

  // ---- each progress source resets the fact
  const src = {
    'stage change (CR log)': [{ stageAge: 1 }, 'stage'],
    'flow step': [{ flowAge: 2 }, 'flow'],
    'report written': [{ report: 3 }, 'report'],
    'commit (.git/logs/HEAD)': [{ commitAge: 4 }, 'commit'],
    'STATUS.md change': [{ statusAge: 5 }, 'status'],
    'agent finish (agents.json rewritten)': [{ agentsAge: 6 }, 'agent'],
    'agent start': [{ agents: [{ type: 'qa-engineer', startedAgo: 7 * 60 }] }, 'agent']
  };
  for (const [label, [o, want]] of Object.entries(src)) {
    p = await world(o);
    check(`progress source "${label}" resets the quiet fact and is named ${want}`, p.quiet === null && p.progress && p.progress.src === want && now() - p.progress.ts < 10 * 60, JSON.stringify([p.quiet, p.progress]));
  }
  p = await world({ transcript: true }); check('a transcript write alone does NOT reset it', !!p.quiet && p.progress.ts < now() - 35 * 60);

  // ---- suppression: every other state wins
  const none = async (label, o) => { const q = await world(o); check('suppressed: ' + label, q.quiet === null, JSON.stringify(q.quiet)); };
  await none('usage limit', { limit: true, chat: 'limit' });
  await none('plan approval pending', { pending: true, chat: 'plan_approval' });
  await none('needs you', { state: 'needs-input', chat: 'waiting_you' });
  await none('API trouble', { chat: 'api' });
  await none('context full', { chat: 'context' });
  await none('waiting on a background job', { chat: 'job' });
  await none('the watcher says not working (Esc pressed)', { chatWorking: false });
  await none('chat idle (hooks say idle)', { state: 'idle' });
  for (const k of ['frozen_chat', 'frozen_agent', 'stage_stuck', 'job_frozen']) await none('stall item ' + k, { items: [k] });
  p = await world({ items: ['merge_waiting'] }); check('an unrelated Health item does not suppress it', !!p.quiet);
  p = await world({ agents: [{ type: 'qa-engineer', startedAgo: 40 * 60 }], agentsAge: 40 }); check('a running test agent adds the minutes (Tests running N min), grey info', !!p.quiet && p.quiet.tests === 40, JSON.stringify(p.quiet));

  // ---- it needs a health.json chat entry: nothing known = nothing shown
  p = await world({ after: () => fs.rmSync(path.join(STATE, 'health.json')) }); check('no health.json -> no quiet fact (the watcher must vouch for the chat)', p.quiet === null);
  p = await world({ after: () => put(path.join(STATE, 'health.json'), { ts: now(), chats: {}, items: [] }) }); check('health.json without this chat -> no quiet fact', p.quiet === null);
  p = await world({ after: () => fs.rmSync(path.join(DIR, 'docs', 'STATUS.md')) }); check('missing sources are skipped, the others still decide', !!p.quiet);
  p = await world({ after: () => { for (const f of [path.join(DIR, 'docs', 'STATUS.md'), path.join(DIR, '.git', 'logs', 'HEAD'), path.join(STATE, NAME + '.agents.json'), path.join(STATE, 'v1', 'cr', pid + '.jsonl'), path.join(STATE, 'flow.sid1.json')]) fs.rmSync(f); } });
  check('no progress information at all -> no quiet fact, progress null', p.quiet === null && p.progress === null, JSON.stringify([p.quiet, p.progress]));

  // set aside (F7): quietOf is a pure rule, so the aside flag from `shipm report panel` is checked directly
  { const base = { state: 'working', approval: false, limitUntil: 0, health: [], agents: [], dir: DIR, live: null }, ok = { state: 'ok', working: true }, prog = { ts: now() - 3600, src: 'commit' };
    check('quietOf: shown for a plain quiet working project', !!DATA.quietOf(base, prog, ok, 30, now()));
    check('quietOf: suppressed when the project is set aside (aside.on)', DATA.quietOf({ ...base, aside: { on: true } }, prog, ok, 30, now()) === null);
    check('quietOf: not suppressed by an aside record that is off', !!DATA.quietOf({ ...base, aside: { on: false } }, prog, ok, 30, now())); }
  console.log(fails ? `\nFAILED: ${fails}` : '\nALL PASS'); fs.rmSync(ROOT, { recursive: true, force: true }); process.exit(fails ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
