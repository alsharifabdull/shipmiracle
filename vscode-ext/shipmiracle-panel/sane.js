// The shape guard in front of the panel page (panel.js html()). data.js already cleans what it reads from disk; this module makes sure the page builder can never throw on, or
// print as markup, a value of the wrong type (null, a number where text belongs, an object where a list belongs, a missing block). Valid data passes through unchanged (same values).
// Rule: a field that is not what the page expects is replaced by its empty default; nothing is guessed. Pure functions, no I/O.
const TLM = require('./timeline');                                    // the two cleaners of the timeline fields (release, history), the same ones data.js uses
const DETAIL = require('./detail');                                 // text hygiene for everything F9 shows (control and bidi characters out, length capped)
const isObj = v => v !== null && typeof v === 'object' && !Array.isArray(v);
const str = (v, d = '') => (typeof v === 'string' ? v : typeof v === 'number' && Number.isFinite(v) ? String(v) : d);
const num = (v, d = 0) => (typeof v === 'number' && Number.isFinite(v) ? v : d);
const numOrNull = v => (typeof v === 'number' && Number.isFinite(v) ? v : null);
const list = v => (Array.isArray(v) ? v : []);
const objs = v => list(v).filter(isObj);
const strs = v => list(v).filter(x => typeof x === 'string');
const keepStr = (o, ks) => { for (const k of ks) if (k in o) o[k] = str(o[k]); return o; };
const keepNum = (o, ks) => { for (const k of ks) if (k in o) o[k] = num(o[k]); return o; };
const optObj = v => (isObj(v) ? { ...v } : null);

function idea(i) { const q = keepStr({ ...i }, ['id', 'text', 'date', 'verdict', 'why']); q.tags = strs(i.tags); return q; }
function project(p) {
  if (!isObj(p)) return null;
  const q = keepStr({ ...p }, ['dir', 'stack', 'state', 'message', 'model', 'next', 'level', 'nextAction']);
  q.name = str(p.name); q.dir = str(p.dir);
  keepNum(q, ['dirty', 'ahead', 'lastCommit']); if ('limitUntil' in q) q.limitUntil = typeof q.limitUntil === 'string' ? q.limitUntil : num(q.limitUntil);      // epoch seconds or an ISO text
  if ('age' in q) q.age = numOrNull(q.age);
  const tk = isObj(p.tokens) ? p.tokens : {};
  q.tokens = { ...tk, claudeDay: num(tk.claudeDay), claudeWeek: num(tk.claudeWeek) };
  for (const k of ['ledgerDay', 'ledgerWeek']) if (k in tk) q.tokens[k] = num(tk[k]);
  const id = isObj(p.ideas) ? p.ideas : {};
  q.ideas = { ...id, open: objs(id.open).map(idea), evaluated: objs(id.evaluated).map(idea), done: num(id.done), dropped: num(id.dropped) };
  q.agents = objs(p.agents).map(a => { const x = keepStr({ ...a }, ['id', 'type', 'model', 'itemId']); x.mins = num(a.mins); x.quiet = numOrNull(a.quiet); return x; });
  q.health = objs(p.health).map(h => keepStr({ ...h }, ['id', 'kind', 'severity', 'title', 'why', 'mode', 'project']));
  if (isObj(p.team)) q.team = { ...p.team, count: num(p.team.count), bad: strs(p.team.bad), dod: strs(p.team.dod), untrusted: strs(p.team.untrusted), untrustedInfo: objs(p.team.untrustedInfo).map(u => keepStr({ ...u }, ['name', 'role'])) }; else delete q.team;
  q.live = optObj(p.live); if (q.live) { keepStr(q.live, ['model', 'phase']); if ('idle' in q.live) q.live.idle = numOrNull(q.live.idle); if ('modelAge' in q.live) q.live.modelAge = numOrNull(q.live.modelAge); }
  q.ci = optObj(p.ci); if (q.ci) keepStr(q.ci, ['state', 'url', 'conclusion', 'status', 'title']);
  q.context = optObj(p.context); if (q.context) { q.context.tokens = num(q.context.tokens); q.context.level = str(q.context.level); } else delete q.context;
  q.levelSwitch = optObj(p.levelSwitch); if (q.levelSwitch) { q.levelSwitch.ok = q.levelSwitch.ok === true; q.levelSwitch.why = str(q.levelSwitch.why); } else delete q.levelSwitch;
  const pb = optObj(p.playbook); q.playbook = pb ? keepStr(pb, ['type', 'level', 'autopilot']) : null;
  if (p.cr === null || p.cr === undefined) q.cr = null; else q.cr = objs(p.cr).map(c => ({ ...keepStr({ ...c }, ['id', 'title', 'status', 'stage', 'lane', 'label', 'verdict', 'waiting_on']), in_chat: c.in_chat === true }));
  if ('release' in p) q.release = TLM.cleanRelease(p.release); if ('history' in p) q.history = TLM.cleanHistory(p.history);                         // two-level timeline: the keys exist only when the engine sent them
  const sl = optObj(p.stageLabels); q.stageLabels = sl ? Object.fromEntries(Object.entries(sl).map(([k, v]) => [k, str(v)])) : null;
  const lv = optObj(p.lastVerdict); q.lastVerdict = lv ? keepStr(lv, ['stage', 'word', 'report']) : null; if (lv && 'counts' in lv && !(isObj(lv.counts) || typeof lv.counts === 'string')) q.lastVerdict.counts = null;
  const ap = optObj(p.autopilot);
  if (ap) { keepStr(ap, ['state', 'level', 'cr', 'branch', 'ended_reason']); ap.decisions = num(ap.decisions); ap.stop = optObj(ap.stop); if (ap.stop) keepStr(ap.stop, ['id', 'rule', 'text']); ap.budget = optObj(ap.budget); if (ap.budget) { ap.budget.used_pct = numOrNull(ap.budget.used_pct); ap.budget.cap_pct = numOrNull(ap.budget.cap_pct); }
    ap.time = optObj(ap.time); if (ap.time) { ap.time.left_s = numOrNull(ap.time.left_s); ap.time.cap_s = numOrNull(ap.time.cap_s); } ap.charter = optObj(ap.charter); if (ap.charter) { keepStr(ap.charter, ['id', 'goal', 'set_by', 'sha8']); ap.charter.scope = strs(ap.charter.scope); ap.charter.ends = strs(ap.charter.ends); } }
  if (ap) { ap.until = ap.until === 'disabled' ? 'disabled' : ''; keepStr(ap, ['reason']); ap.seg_left_s = numOrNull(ap.seg_left_s);
    ap.day = optObj(ap.day); if (ap.day) { ap.day.used_pct = numOrNull(ap.day.used_pct); ap.day.cap_pct = numOrNull(ap.day.cap_pct); }
    ap.waiting = objs(ap.waiting).slice(0, 5).map(w => ({ id: str(w.id), title: str(w.title), in_chat: w.in_chat === true })); }
  q.autopilot = ap;
  q.folders = strs(p.folders);
  const fl = optObj(p.flow); if (fl) { fl.steps = isObj(fl.steps) ? fl.steps : {}; fl.running = objs(fl.running).map(r => keepStr({ ...r }, ['type', 'model', 'label'])); fl.actors = objs(fl.actors); fl.outside = strs(fl.outside); keepStr(fl, ['stage', 'plannedBy', 'builtBy', 'qaBy', 'qaState', 'plannedByLabel']); fl.integrity = typeof fl.integrity === 'string' || typeof fl.integrity === 'boolean' ? fl.integrity : ''; if ('mismatch' in fl && typeof fl.mismatch !== 'string') fl.mismatch = fl.mismatch === true ? true : false; fl.refusalsToday = num(fl.refusalsToday); q.flow = fl; } else delete q.flow;
  const ak = optObj(p.ask); if (ak) { ak.questions_today = num(ak.questions_today); ak.notes = num(ak.notes); if ('limit' in ak) ak.limit = num(ak.limit, 20); const l = optObj(ak.last); if (l) { keepStr(l, ['title', 'path']); l.ts = num(l.ts); } ak.last = l; ak.model_supported = ak.model_supported === true; q.ask = ak; } else delete q.ask;
  { const qt = optObj(p.quiet); q.quiet = qt && Number.isFinite(qt.min) && qt.min >= 0 ? { min: Math.floor(qt.min), tests: numOrNull(qt.tests) } : null;         // F9: the quiet fact
    const pg = optObj(p.progress); q.progress = pg && num(pg.ts) > 0 ? { ts: num(pg.ts), src: str(pg.src) } : null;
    const as = optObj(p.aside); q.aside = as ? { on: as.on === true, since: num(as.since), note: DETAIL.sanitize(as.note, 120), canAside: as.canAside === true, reason: DETAIL.sanitize(as.reason, 120), backOnList: DETAIL.sanitize(as.backOnList, 120) } : null;                    // F7
    q.unread = p.unread === 'turn' || p.unread === 'wait' ? p.unread : ''; }                                                                                  // F8
    { const tb = optObj(p.toolbox); q.toolbox = tb ? { count: num(tb.count), changed: num(tb.changed), assets: objs(tb.assets).slice(0, 100).map(a => ({ path: DETAIL.sanitize(a.path, 200), stage: DETAIL.sanitize(a.stage, 20), stageLabel: DETAIL.sanitize(a.stageLabel, 30), purpose: DETAIL.sanitize(a.purpose, 120), status: ['ok', 'changed', 'missing'].includes(a.status) ? a.status : 'ok' })) } : null;     // F5
      q.proposed = require('./proposed').clean(p.proposed, q.name);                                                                               // F5 Learn: rebuilt from path/why/stage, never trusted
      const iv = optObj(p.interview); q.interview = iv && ['asking', 'paused', 'draft', 'done', 'error'].includes(iv.status) ? { status: iv.status, mode: iv.mode === 'long' ? 'long' : 'short', n: num(iv.n), total: num(iv.total), draft: iv.draft === true } : null;                  // F6
      const mi = optObj(p.mirror); q.mirror = mi && ['asking', 'paused', 'draft', 'error'].includes(mi.status) ? { status: mi.status, mode: mi.mode === 'long' ? 'long' : 'short', n: num(mi.n), total: num(mi.total), updated: num(mi.updated),
        question: isObj(mi.question) ? { text: DETAIL.sanitize(mi.question.text, 200), recommended: DETAIL.sanitize(mi.question.recommended, 200) } : null, assumed: strs(mi.assumed).slice(0, 12).map(x => DETAIL.sanitize(x, 80)), prototype: strs(mi.prototype).slice(0, 12).map(x => DETAIL.sanitize(x, 80)),
        draftOk: mi.draftOk === true, rows: objs(mi.rows).slice(0, 9).map(r => ({ label: DETAIL.sanitize(r.label, 40), text: DETAIL.sanitize(r.text, 200) })) } : null; }
  for (const k of ['held', 'active', 'chatOpen', 'approval', 'pushFailed', 'hub']) if (k in q) q[k] = q[k] === true;
  if ('special' in q) q.special = q.special === 'ideas' ? 'ideas' : '';
  return q;
}

// F9 details of the open cards, by project name: only the shapes the page draws, every text cleaned and capped. A name-keyed map without a prototype.
function detailMap(v) {
  const out = Object.create(null); if (!isObj(v)) return out;
  const T = (x, n) => DETAIL.sanitize(x, n), chatStates = ['ok', 'hidden', 'error', 'none'];
  for (const name of Object.keys(v)) {
    const x = v[name]; if (!isObj(x)) continue;
    if (x.error === true) { out[name] = { error: true }; continue; }
    const c = isObj(x.chat) ? x.chat : { state: 'none' }, r = isObj(x.report) ? x.report : null, st = isObj(x.status) ? x.status : null;
    out[name] = {
      error: false, at: num(x.at),
      chat: { state: chatStates.includes(c.state) ? c.state : 'none', text: T(c.text, 300), ts: num(c.ts), tool: /^[A-Za-z0-9_:.-]{1,60}$/.test(str(c.tool)) ? str(c.tool) : '' },
      report: r && /^[A-Za-z0-9._-]{1,120}$/.test(str(r.id)) ? { id: str(r.id), verdict: ['PASS', 'FAIL', 'BLOCKED', 'NOT TESTED'].includes(str(r.verdict)) ? str(r.verdict) : 'NOT TESTED', title: T(r.title, 160), summary: T(r.summary, 300), ts: num(r.ts) } : null,
      status: st ? { note: T(st.note, 130), ts: num(st.ts) } : null
    };
  }
  return out;
}
function sane(data) {
  const d = isObj(data) ? { ...data } : {};
  d.projects = list(d.projects).map(project).filter(Boolean);
  const pl = isObj(d.plan) ? { ...d.plan } : {}; pl.meters = objs(pl.meters).map(m => { const x = keepStr({ ...m }, ['id', 'label']); x.pct = numOrNull(m.pct); x.lvl = num(m.lvl); if ('resets' in m && typeof m.resets !== 'number') x.resets = typeof m.resets === 'string' ? m.resets : null; return x; }); d.plan = pl;
  const g = isObj(d.guard) ? d.guard : {}; d.guard = { ...g, on: g.on !== false, running: g.running === true, hold: g.hold === true, reason: str(g.reason), battery: numOrNull(g.battery), lpm: g.lpm === true, away: num(g.away) };
  if (d.health !== null && d.health !== undefined) { if (!isObj(d.health)) d.health = null; else { const h = { ...d.health }; h.items = objs(h.items).map(i => keepStr({ ...i }, ['id', 'kind', 'severity', 'project', 'title', 'why', 'mode', 'info', 'next', 'fix_label', 'proof', 'recommended'])); h.counts = isObj(h.counts) ? { red: num(h.counts.red), amber: num(h.counts.amber), info: num(h.counts.info) } : {}; h.ageS = num(h.ageS); h.notice = str(h.notice); h.noticeInfo = isObj(h.noticeInfo) ? h.noticeInfo : { busy: false, id: '', steps: [] }; h.chats = isObj(h.chats) ? h.chats : {}; h.aside_items = objs(h.aside_items).slice(0, 100).map(i => ({ project: str(i.project), kind: str(i.kind), title: DETAIL.sanitize(i.title, 120), id: str(i.id) })); d.health = h; } }
  if (d.reports !== null && d.reports !== undefined) d.reports = isObj(d.reports) ? { ...d.reports, items: objs(d.reports.items), status: str(d.reports.status, 'ok') } : null;
  if (d.setup !== null && d.setup !== undefined) d.setup = isObj(d.setup) ? { ...d.setup, rows: objs(d.setup.rows).map(r => { const x = keepStr({ ...r }, ['id', 'title', 'need', 'state', 'detail']); x.n = num(r.n); x.connect = isObj(r.connect) ? keepStr({ ...r.connect }, ['kind', 'text']) : { kind: 'hint', text: '' }; if (['connect', 'prefs', 'advanced'].includes(r.stage)) { x.stage = r.stage; x.cls = str(r.cls, x.need); x.os_supported = r.os_supported !== false; x.docs = str(r.docs); } return x; }), error: d.setup.error === true, os: isObj(d.setup.os) ? { kind: str(d.setup.os.kind, 'other'), line: str(d.setup.os.line), level: str(d.setup.os.level) } : null, quick: d.setup.quick === true } : null;
  d.host = require('./hostx').cleanHost(d.host);
  d.remote = isObj(d.remote) ? { state: ['on', 'off'].includes(d.remote.state) ? d.remote.state : 'unknown' } : { state: 'unknown' };
  d.levelSwitch = isObj(d.levelSwitch) ? { ok: d.levelSwitch.ok === true, why: str(d.levelSwitch.why) } : { ok: false, why: '' };      // no answer = no switch (same as before)
  d.creating = isObj(d.creating) ? keepStr({ ...d.creating }, ['name']) : null;
  d.pnotice = str(d.pnotice);
  d.modelReset = isObj(d.modelReset) ? d.modelReset : null;
  d.ledger = isObj(d.ledger) ? d.ledger : {};
  d.ask = isObj(d.ask) ? d.ask : null;
  d.autopilot = { until_disabled_supported: isObj(d.autopilot) && d.autopilot.until_disabled_supported === true };
  { const st = isObj(d.settings) ? d.settings : {}; d.settings = { cardChatExcerpt: st.cardChatExcerpt !== false, unreadMarker: st.unreadMarker !== false };       // F9 / F8 settings (default on)
    const cp = isObj(d.capabilities) ? d.capabilities : {}; d.capabilities = { aside: cp.aside === true, toolbox: cp.toolbox === true, interview: cp.interview === true, release: cp.release === true };   // what the CLI can do (F5 F6 F7, release timeline)
    d.detail = detailMap(d.detail);
    d.asideNotice = objs(d.asideNotice).slice(0, 5).map(n => ({ project: DETAIL.sanitize(n.project, 100), why: n.why === 'hard_stop' ? 'hard_stop' : 'work', ts: num(n.ts) })); }
  if (d.rview !== null && d.rview !== undefined && !isObj(d.rview)) d.rview = null;
  return d;
}
module.exports = { sane, project };
