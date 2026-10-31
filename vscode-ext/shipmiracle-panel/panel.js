// HTML for the Shipmiracle panel. Pure function of the collected data; uses VS Code theme variables so it
// follows light/dark. Also used by preview.js to render the panel outside VS Code for checking.
const S = require('./strings');
const SANE = require('./sane');
const CHARTER = require('./charter');                              // the charter rules of shipmiracle/autopilot/charter.py; the editor in the page runs the same validate() function                                     // all v3 copy, keyed (strings.js); t('group.key', { slot: value })
const t = (k, o) => { const v = k.split('.').reduce((a, x) => (a == null ? a : a[x]), S); return typeof v === 'string' ? v.replace(/\{(\w+)\}/g, (m, n) => (o && o[n] != null ? o[n] : '')) : k; };
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const fmt = n => n >= 1e6 ? (n / 1e6).toFixed(n >= 1e7 ? 0 : 1) + 'M' : n >= 1e3 ? Math.round(n / 1e3) + 'k' : String(n || 0);
const ago = s => !s ? '' : s < 90 ? 'just now' : s < 5400 ? Math.round(s / 60) + ' min ago' : s < 129600 ? Math.round(s / 3600) + ' h ago' : Math.round(s / 86400) + ' d ago';
const when = iso => { if (!iso) return ''; const d = new Date(iso); const days = (d - Date.now()) / 86400000;
  const hm = d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
  return days > 1.5 ? d.toLocaleDateString('en-GB', { weekday: 'short' }) + ' ' + hm : hm; };

const ICON = {
  bell: '<path d="M10 5a2 2 0 1 1 4 0a7 7 0 0 1 4 6v3a4 4 0 0 0 2 3h-16a4 4 0 0 0 2-3v-3a7 7 0 0 1 4-6"/><path d="M9 17v1a3 3 0 0 0 6 0v-1"/>',
  spin: '<path d="M12 3a9 9 0 1 0 9 9"/>',
  check: '<circle cx="12" cy="12" r="9"/><path d="M9 12l2 2l4-4"/>',
  idle: '<circle cx="12" cy="12" r="9"/>',
  plus: '<path d="M12 5v14M5 12h14"/>', bulb: '<path d="M9 16a5 5 0 1 1 6 0a3.5 3.5 0 0 0-1 3a2 2 0 0 1-4 0a3.5 3.5 0 0 0-1-3"/><path d="M9.7 17h4.6"/>',
  gear: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3a1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5a1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8a1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1a1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5a1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>'
};
const svg = (n, cls = '') => `<svg class="ic ${cls}" viewBox="0 0 24 24" aria-hidden="true">${ICON[n]}</svg>`;
const STATE = { 'needs-input': ['bell', 'warn'], working: ['spin', 'accent'], calm: ['check', 'ok'], idle: ['idle', 'muted'] };      // icon + tone only: the words live in the card's subtitle

// Meter level words and colours: low (green, under 50 %) · mid (amber, 50-79) · high (orange, 80-94) · almost out (red, 95+).
const WORD = ['', 'mid', 'high', 'almost out'];
function meter(m) {
  if (m.pct == null) return `<div class="mrow"><span>${esc(m.label)}</span><span class="muted">${m.stale ? 'waiting for a new reading' : 'no reading yet'}</span></div><div class="bar"><i class="lv0 w0"></i></div>`;
  const word = WORD[m.lvl];
  return `<div class="mrow"><span>${esc(m.label)}</span><span class="t${m.lvl}">${m.pct}%${word ? ' · ' + word : ''}${m.resets ? ' · resets ' + esc(when(m.resets)) : ''}</span></div>
    <div class="bar"><i class="lv${m.lvl} w${Math.max(0, Math.min(100, Math.round(m.pct)))}"></i></div>`;
}

// ---- Project card v2: title row (state, name, stack, gate-level pill), one subtitle line, the Team-flow strip, then chips ----
const cap = s => s ? s[0].toUpperCase() + s.slice(1) : '';
const mdl = m => cap(String(m || '').trim().split(/\s+/)[0]);                           // "sonnet" -> "Sonnet", "Opus 5.5" -> "Opus"
const STEPS = [['scope', 'Scope'], ['plan', 'Plan'], ['ok', 'OK'], ['build', 'Build'], ['qa', 'QA'], ['review', 'Review']];
const LEVEL = {
  strict: ['strict', 'Gate level strict: the gate refuses skipped steps (plan by the architect, tests before done).', 'warn'],
  warn: ['warn', 'Gate level warn: the gate only tells the chat about skipped steps; it refuses nothing.', 'strict'],
  off: ['gate off', 'Gate off: no team-flow check for this project.', '']
};
const gateBlocks = p => !!(p.flow && p.flow.integrity) && p.level !== 'warn' && p.level !== 'off';   // a changed gate file blocks only at strict
function levelPill(p, ls) {
  const L = LEVEL[p.level]; if (!L) return '';
  const [text, tip, to] = L, cls = `chip lvl lvs-${p.level}`;
  if (!to) return `<span class="${cls}" title="${esc(tip + (ls && ls.why ? ' ' + ls.why : ''))}">${text}</span>`;
  if (ls && ls.ok && !p.held) return `<button class="${cls}" data-level="${esc(p.name)}" data-to="${to}" data-sure="Sure? Switch to ${to}" aria-label="Gate level ${text} for ${esc(p.name)}. Press to switch to ${to}" title="${esc(tip + ' Click to switch to ' + to + '.')}">${text}</button>`;
  return `<span class="${cls}" title="${esc(tip + (ls && ls.why ? ' ' + ls.why : ''))}">${text}</span>`;
}
function frozenMin(p) {                                    // minutes without activity when the chat looks frozen, '' when frozen but unknown, null when not frozen
  if (p.live && p.live.phase === 'stalled') return Math.max(1, Math.round((p.live.idle || 0) / 60));
  const h = (p.health || []).find(i => /^(frozen_|job_frozen)/.test(i.kind || ''));
  if (!h) return null;
  return h.since > 1e9 ? Math.max(1, Math.round((Date.now() / 1000 - h.since) / 60)) : '';
}
function subtitle(p) {                                     // [text, tone]; priority: held > integrity > frozen > limit > needs-you / plan approval > stage > done > idle > none
  const f = p.flow, working = p.state === 'working', needs = p.state === 'needs-input', now = Date.now() / 1000;
  if (p.held) return ['Held: its session is still running.', ''];
  if (gateBlocks(p)) return ['Blocked: a gate file changed', 'red'];
  const fz = frozenMin(p); if (fz !== null) return [fz === '' ? 'No activity for a while. Open Health' : `No activity for ${fz} min. Open Health`, 'red'];
  if (p.limitUntil) { const t = typeof p.limitUntil === 'number' ? new Date(p.limitUntil < 1e12 ? p.limitUntil * 1000 : p.limitUntil).toISOString() : p.limitUntil; return [`Waiting for the usage limit to reset (back at ${when(t)})`, 'warn']; }
  if (p.approval || (f && f.stage === 'ok' && (working || needs))) return ['Plan is ready. Waiting for your OK in the chat', 'warn'];
  if (needs) return ['Needs you' + (p.message ? ': ' + p.message : ''), 'warn'];
  const A = (f && f.running) || [], a0 = A[0] || {}, m = mdl(a0.model);           // an actor is named only while it is really running
  if (working && f && A.length && f.stage) {
    const T = {
      scope: `Scoping: ${a0.label || a0.type || 'scoper'} is clarifying the task`,
      plan: m && a0.type ? `Planning with ${m}: ${a0.label || a0.type}` : `Planning: ${a0.type || 'an agent'} is writing the plan`,
      build: A.length > 1 ? `Building with ${m || 'Sonnet'}: ${A.length} agents` : `Building with ${m || 'Sonnet'}${a0.type ? ': ' + (a0.label || a0.type) : ''}`,
      qa: `Testing: ${a0.label || a0.type || 'verifier'} is checking the build`,
      review: `Review: ${a0.label || a0.type || 'reviewer'} is reading the change`
    };
    if (T[f.stage]) return [T[f.stage], ''];
  }
  if (working && f && f.steps) {                              // nobody is running: say only what the records show
    const st = f.steps, last = STEPS.filter(([k]) => st[k] === 'done').pop();
    if (st.qa === 'done' && st.review !== 'done') return ['Working · QA ran, review next', ''];
    if (st.plan !== 'done') return ['Working · no plan yet', ''];
    return [last ? `Working · ${last[1]} done` : 'Working · no plan yet', ''];
  }
  if (working) return ['Working', ''];
  if (f && f.steps && f.steps.build === 'done' && f.steps.qa === 'done' && f.steps.review !== 'current') return ['Done · QA ran', ''];
  if (f) return [p.lastCommit ? 'Idle · last commit ' + ago(now - p.lastCommit) : 'Idle', ''];
  return ['No flow data for this project yet', ''];
}
function flowStrip(f) {
  if (!f || !f.steps) return '';
  const act = (f.running || [])[0];
  const li = STEPS.map(([k, w]) => {
    const s = f.steps[k] || 'next', cur = s === 'current', model = cur && act && act.model && k !== 'ok' ? ' · ' + esc(mdl(act.model)) : '';
    return `<li class="ts ${s === 'done' ? 'done' : cur ? 'cur' : 'next'}" aria-label="${w}: ${s === 'done' ? 'done' : cur ? 'in progress' + (model ? ' with ' + esc(mdl(act.model)) : '') : 'not yet'}"${cur ? ' aria-current="step"' : ''}><i class="td"></i>${w}${model}</li>`;
  }).join('');
  return `<ol class="tflow" aria-label="Team flow: scope, plan, your OK, build, QA, review">${li}</ol>`;
}
function flowMeta(f) {                                     // who is working (grey), what QA did, whether the plan came from the architect
  if (!f) return '';
  const A = f.running || [], ms = [...new Set(A.map(a => mdl(a.model)).filter(Boolean))].join('/');
  const who = !A.length ? '' : A.length === 1 ? [ms, A[0].label || A[0].type].filter(Boolean).join(' · ') : `${ms ? ms + ' · ' : ''}${A.length} agents: ${A.map(a => a.label || a.type).join(', ')}`;
  const cn = f.qaCounts ? ` (${f.qaCounts})` : '', vb = f.qaVerdict && f.qaVerdict !== 'FAIL' ? f.qaVerdict : 'FAILED';
  const qa = { ran: ['QA ran', ''], passed: [`QA passed${cn}`, ''], failed: [`QA ${vb === 'FAILED' ? 'FAILED' : vb}${cn}`, 'warnt'], none: ['QA not run yet', 'warnt'], cutoff: ['QA cut off: it never reported', 'warnt'], noverdict: ['QA: no verdict', 'warnt'], stale: ['QA stale: code changed after the test', 'warnt'] }[f.qaState];
  const bits = [qa ? `<span${qa[1] ? ` class="${qa[1]}"` : ''}>${esc(qa[0])}</span>` : '', f.plannedByLabel ? `<span>Plan: ${esc(f.plannedByLabel)}</span>` : '', f.planNotByArchitect ? '<span class="warnt">Plan not by the architect</span>' : ''].filter(Boolean);
  const tip = `Team flow (AGENTS.md section 4): plan by the planner (Opus), build by the builders (Sonnet), then the verifier. Plan: ${f.plannedBy || 'none'} · Build: ${f.builtBy || 'none'} · QA: ${f.qaBy || 'none'}`;
  return (who ? `<div class="tmeta" title="${esc(tip)}">${esc(who)}</div>` : '') + (bits.length ? `<div class="tmeta" title="${esc(tip)}">${bits.join(' · ')}</div>` : '');
}
function flowChips(p) {
  const f = p.flow || {}, out = [], wn = (t, tip) => `<span class="chip wn" title="${esc(tip || t)}">${esc(t)}</span>`;
  if (f.mismatch) out.push(wn(`Planning on ${mdl(typeof f.mismatch === 'string' ? f.mismatch : p.live && p.live.model) || 'Sonnet'}. Type /model opusplan`, 'A model picked in the chat overrides opusplan'));
  if (f.integrity && p.level !== 'off') {
    const t = p.level === 'warn' ? 'Gate file changed (note only)' : '⚠ Gate file changed: your next message clears it';
    out.push(`<button class="chip wn" data-hopen="-" title="${esc(t + '. A gate file (hook or flow config) was edited. Click to open the Health tab.')}">${esc(t)}</button>`);
  }
  if (f.refusalsToday > 0) out.push(`<span class="chip" title="The gate refused ${f.refusalsToday} skipped step(s) today (plan without the architect, edit outside the team, done without QA, gate tampering).">${f.refusalsToday} refused today</span>`);
  const outside = Array.isArray(f.outside) ? f.outside : [], nOut = Array.isArray(f.outside) ? f.outside.length : Number(f.outside) || 0;
  if (nOut > 0) out.push(wn(`${nOut} ${nOut === 1 ? 'file' : 'files'} outside the team`, outside.length ? outside.join('\n') : 'Changed outside the team agents'));
  if (f.bypass) out.push(wn('bypass on for this turn', 'The owner switched the gate off for this turn only.'));
  const tm = p.team;
  if (tm && tm.count === 0) out.push(wn('No team agents', 'This project has no .claude/agents team yet. Run Check & update to install it.'));
  if (tm && tm.untrusted && tm.untrusted.length) out.push(`<button class="chip wn" data-activate="${esc(p.name)}" title="${esc('A privileged role (plan, test, review, report) is claimed by a file that is not a master copy: ' + tm.untrusted.join(', ') + '. Until you activate it, it counts as a support agent. Click to choose one, or run: shipm agents activate ' + p.name + ' <name>')}">${tm.untrusted.length} ${tm.untrusted.length === 1 ? 'agent' : 'agents'} untrusted</button>`);
  if (tm && tm.dod && tm.dod.length) out.push(wn(`${tm.dod.length} agent ${tm.dod.length === 1 ? 'file needs' : 'files need'} the DoD block`, 'Needs the DoD block (Verdict line) or maxTurns; QA verdicts of these agents count as unknown:\n' + tm.dod.join('\n')));
  if (tm && tm.bad && tm.bad.length) out.push(wn(`${tm.bad.length} agent ${tm.bad.length === 1 ? 'file breaks' : 'files break'} the model rule`, tm.bad.join('\n')));
  return out;
}
// ---- tokens: the ledger (bin/shipm-ledger, cache reads included) when it is fresh; otherwise the old transcript estimate, labelled as such
function tokenRows(led, allDay) {
  if (led && led.fresh && led.today) {
    const td = led.today, w = led.week || {}, share = td.calls ? td.overCallsPct : w.overCallsPct;
    const tip = 'Cache reads are included: they are most of what is sent on every message.' + (w.tokens ? ' Last 7 days: ' + fmt(w.tokens) + ' tokens' + (w.overCallsPct != null ? ', ' + Math.round(w.overCallsPct) + '% of calls over 200k context' : '') + '.' : '');
    return `<div class="mrow" title="${esc(tip)}"><span>Today: ${fmt(td.tokens)} tokens (incl. cache reads)</span></div>`
      + (w.overTokensPct != null && w.tokens ? `<div class="mrow" title="${esc(t('tokens.longTip'))}"><span>${esc(t('tokens.long', { n: Math.round(w.overTokensPct) }))}</span></div>` : '')
      + (share != null ? `<div class="mrow" title="Chats past 200k tokens cost more per message. A fresh chat with a handoff keeps this number down."><span>${Math.round(share)}% of calls are over 200k context</span></div>` : '');
  }
  return `<div class="mrow" title="The token ledger is not available (${esc(led && led.why === 'old' ? 'its last update is older than 15 minutes' : 'no ledger yet; the guard builds it every 10 minutes')}). This is an older estimate that leaves out cache reads, so the real figure is much higher."><span>Today (estimate, cache reads not counted)</span><span>Claude ${fmt(allDay)}</span></div>`;
}
// ---- context size of the project's chat (the context-nudge hook): a chip from 200k, a quiet handoff button; never automatic, never primary
const kfmt = n => Math.floor(n / 1000) + 'k';       // same rounding as the nudge hook: 199999 is 199k, never 200k
const CTX_TIP = { soft: 'Chat is long. Handing over to a fresh chat saves tokens and keeps quality up. Your choice.', strong: 'Chat is very long. Handing over to a fresh chat saves tokens and keeps quality up. Your choice.' };
function ctxChip(p) {
  const c = p.context; if (!c || (c.level !== 'soft' && c.level !== 'strong')) return '';
  return `<span class="chip wn ctx${c.level === 'strong' ? ' strong' : ''}" title="${esc(CTX_TIP[c.level] + ' (' + c.tokens.toLocaleString('en-US') + ' tokens in this chat)')}">${esc(t(c.level === 'strong' ? 'ctx.strong' : 'ctx.soft', { k: kfmt(c.tokens) }))}</span>`;
}
function handoffRow(p) {
  const c = p.context, h = p.handoff, long = c && c.level === 'strong';        // soft (200-299k): the chip and a dot on the menu item only; strong: a quiet button too
  if (!long && !h) return '';
  const busy = p.state === 'working' || p.state === 'needs-input' || (p.agents || []).length > 0;
  const nm = `data-project="${esc(p.name)}"`;
  if (!h) return `<div class="btns"><button class="btn quiet" data-handoff="ask" ${nm} data-sure="Sure? Note saved, then fresh chat"${busy ? ' disabled' : ''} title="${esc(busy ? 'Wait: an agent is working.' : 'Asks this chat to write its handoff into docs/STATUS.md and commit. Then you can open a fresh chat. The old chat stays open.')}">Handoff + fresh chat</button></div>`;
  return `<div class="nhint" title="The chat was asked to update docs/STATUS.md and reply HANDOFF DONE.">Handoff asked. Waiting for docs/STATUS.md to be updated.</div><div class="btns"><button class="btn" data-handoff="open" ${nm}${h.ready && !busy ? '' : ' disabled'} title="${esc(!h.ready ? 'Not yet: docs/STATUS.md has not changed since you asked. Wait until the chat replies HANDOFF DONE.' : busy ? 'Wait: an agent is working.' : 'Opens a fresh chat. The old chat is not closed.')}">Open fresh chat</button></div>`;
}
// ---- Panel v3 card (UX spec 2026-10-20): state -> one status line, the 7-mark stage strip, change-request chips, last verdict, ONE primary button and the ⋯ menu.
// A project with no playbook (p.playbook null or missing: no .shipmiracle folder) renders the legacy card content (subtitle, 6-step Team-flow strip) with the same primary/⋯ row.
const STAGE_IDS = ['scope', 'plan', 'approve', 'do', 'verify', 'review', 'deliver'];
const ACTIVE_CR = ['open', 'blocked'], FINISHED_CR = ['delivered', 'merged', 'abandoned'];
function crInfo(p) {
  const l = Array.isArray(p.cr) ? p.cr : [];
  return { active: l.find(c => ACTIVE_CR.includes(c.status)) || null, queued: l.filter(c => c.status === 'queued'), fin: l.find(c => FINISHED_CR.includes(c.status)) || null,
    open: l.filter(c => c.status === 'open' || c.status === 'queued' || c.status === 'blocked') };
}
function stageNames(p) {                                   // one everyday word per step, the same everywhere (revision v2); the playbook's terse labels stay for reports only
  const n = S.stageNames[p.playbook && p.playbook.type] || S.stageNames.software;
  return TL.on(p) ? TL.stageLabelsFor(p, n) : n;                // timeline: the last step reads "Done" (display only)
}
const leftLong = s => { const h = Math.floor(s / 3600), m = Math.round((s % 3600) / 60); return s < 3600 ? `${Math.max(1, Math.round(s / 60))} min` : m ? `${h} h ${m} min` : `${h} h`; };
const cOf = p => { const a = p.autopilot; return !!(a && a.until === 'disabled' && ['running', 'paused', 'set'].includes(a.state)); };   // an "Until I disable it" run exists
const leftText = s => { if (s < 3600) return `${Math.max(1, Math.round(s / 60))} min left`; const h = Math.floor(s / 3600), m = Math.round((s % 3600) / 60); return m ? `${h} h ${m} left` : `${h} h left`; };   // "1 h 12 left", "45 min left"
const limitTime = p => { const v = p.limitUntil; if (!v) return ''; return when(typeof v === 'number' ? new Date(v < 1e12 ? v * 1000 : v).toISOString() : v); };
const stopWords = st => String((st && st.text) || '').replace(/[.\s]+$/, '');
function stateOf(p) {                                      // -> { id, text, tone }; priority: held > integrity > frozen > limit > hard stop > blocked > plan approval > needs you > autopilot > stage > delivered > idle
  const R = (id, text, tone = '') => ({ id, text, tone }), fz = frozenMin(p);
  if (p.held) return R('held', t('status.held'));
  if (gateBlocks(p)) return R('integrity', t('status.integrity'), 'red');
  if (fz !== null) return R('frozen', fz === '' ? t('status.frozenUnknown') : t('status.frozen', { min: fz }), 'red');
  if (p.limitUntil) return R('limit', t('status.limit', { time: limitTime(p) }), 'warn');
  const ap = p.autopilot, ci = crInfo(p), a = ci.active, names = stageNames(p), F = p.flow || {}, A = F.running || [], a0 = A[0] || {}, mo = mdl(a0.model);
  if (ap && ap.state === 'paused' && ap.stop) return R('hardstop', t('status.hardstop', { text: stopWords(ap.stop) || t('status.hardstopDefault') }), 'red');
  if (ap && ap.state === 'paused' && ap.until === 'disabled' && S.cpause[ap.reason]) { const cp = S.cpause[ap.reason]; return R('cpause', t('cpause.' + ap.reason + '.band', { cr: ap.cr || t('now.crFallback'), h: Math.max(1, Math.ceil((ap.seg_left_s || 0) / 3600)) }), cp.tone); }
  if (ap && ap.state === 'ended' && ap.until === 'disabled' && ap.ended_reason === 'lapsed') return R('ap-ended', t('ended.lapsed'), 'warn');
  if (ap && ap.state === 'ended' && p.playbook && p.playbook.autopilot === 'full') return R('ap-ended', ap.ended_reason === 'time' && p.untilB ? t('ended.timeB') : t('autopilot.ended', { why: t('autopilot.endedWhy.' + ap.ended_reason) === 'autopilot.endedWhy.' + ap.ended_reason ? t('autopilot.endedWhy.owner') : t('autopilot.endedWhy.' + ap.ended_reason) }), 'warn');   // (the ended text of revision v2 is "Back to Normal")
  if (a && a.status === 'blocked') return a.stage === 'verify' ? R('verify-twice', t('status.verifyTwice'), 'red') : R('blocked', t('status.blocked', { cr: a.id }), 'red');
  if (a ? a.stage === 'approve' : !!(p.approval || (F.stage === 'ok' && (p.state === 'working' || p.state === 'needs-input')))) return R('approval', t('status.approval'), 'warn');
  if (!p.playbook) {                                       // legacy: today's wording while something happens; the spec's line when nothing does
    if (p.state === 'needs-input' || p.state === 'working') { const [tx, tn] = subtitle(p); return R(p.state === 'needs-input' ? 'needs' : 'working', tx, tn); }
    return R('noplaybook', t('status.noPlaybook'));
  }
  if (p.state === 'needs-input') { const [tx, tn] = subtitle(p); return R('needs', tx, tn); }
  if (ap && ap.state === 'running' && ap.until === 'disabled' && !a) return R('cwaiting', t('cband.waitingReqs'));
  if (ap && ap.state === 'running') return R('autopilot', t('status.auto', { what: t('status.autoDoing.' + (a ? a.stage : 'do'), { cr: a ? a.id : (ap.cr || '') }) }));
  const nm = id => names[STAGE_IDS.indexOf(id)] || id, live = p.state === 'working' || A.length > 0;
  if (a) {
    const st = a.stage, who = t('status.roles.' + st) === 'status.roles.' + st ? '' : t('status.roles.' + st), agent = a0.label || a0.type || who;
    if (st === 'do' && a.verdict === 'FAIL') return R('verify-fail', t('status.verifyFail', { label: nm('verify'), builder: t('status.builder') }));
    const id = { scope: 'scoping', plan: 'planning', do: 'building', verify: 'verifying', review: 'reviewing', deliver: 'delivering' }[st] || 'working';
    if (!live) return R(id, t('status.atStage', { cr: a.id, label: nm(st) }));
    const text = st === 'scope' ? t('status.scope', { agent }) : st === 'plan' ? (mo && a0.type ? t('status.planWith', { model: mo, agent }) : t('status.plan', { agent }))
      : st === 'do' ? (A.length > 1 ? t('status.buildMany', { with: t('status.withModel', { model: mo || 'Sonnet' }), n: A.length }) : t('status.build', { with: t('status.withModel', { model: mo || 'Sonnet' }), agent }))
      : st === 'verify' ? (nm('verify') === 'Test' ? t('status.verifyTest', { agent }) : t('status.verify', { label: nm('verify'), agent }))
      : st === 'review' ? t('status.review', { agent }) : t('status.deliver', { label: nm('deliver') });
    return R(id, text);
  }
  { const cs = TL.chatState(p); if (cs) return R(cs.id, cs.text, cs.tone); }       // timeline: a chat with no change is "Unplanned work" (edits) or "Chat open · no change yet"
  if (live) { const [tx, tn] = subtitle(p); return R('working', tx, tn); }
  if (ci.fin && ci.fin.status !== 'abandoned' && !TL.on(p)) return R('delivered', p.lastCommit ? t('status.deliveredAgo', { cr: ci.fin.id, ago: ago(Date.now() / 1000 - p.lastCommit) }) : t('status.delivered', { cr: ci.fin.id }));
  return R('idle', p.lastCommit ? t('status.idle', { ago: ago(Date.now() / 1000 - p.lastCommit) }) : t('status.idleNoCommit'));
}
function primaryOf(p, st, cap) {                           // exactly one; first match wins: waiting on you > fix > limit > start queued CR > open chat (Set up playbook lives in the ⋯ menu)
  const ci = crInfo(p), q = ci.queued[0], P = (key, label, attrs = '', disabled = false, tip = '') => ({ key, label, attrs, disabled, tip: tip || t('btnTip.' + key) });
  if (st.id === 'approval') return P('plan', t('btn.plan'), 'data-act="plan"');
  if (st.id === 'cpause') {                                // option C pause: the one primary is the owner's verb (Keep going / Resume); the command is only typed
    const ap = p.autopilot, cp = S.cpause[ap.reason], h = Math.max(1, Math.ceil((ap.seg_left_s || 0) / 3600));
    const off = !cap ? t('own.notReadyTip') : cp.off ? t('cpause.' + ap.reason + '.off', { h }) : '';
    return P('c' + cp.cmd, cp.slot, `data-act="cverb" data-verb="${cp.cmd}" data-project="${esc(p.name)}"`, !!off, off || t('cwait.verbTip'));
  }
  if (st.id === 'hardstop') return P('decide', t('btn.decide'), `data-act="decide" data-project-for="${esc(p.name)}"`);   // opens the in-card hard-stop box (in words, with the exact commands); nothing is sent to a chat
  if (['verify-twice', 'blocked', 'needs'].includes(st.id)) return P('decide', t('btn.decide'), 'data-act="open"');
  if (st.id === 'integrity' || st.id === 'frozen') { const h = (p.health || []).find(i => /^(frozen_|job_frozen)/.test(i.kind || '')); return P('fix', t('btn.fix'), `data-hopen="${esc(st.id === 'frozen' && h ? h.id : '-')}"`); }
  if (st.id === 'limit') { const tm = limitTime(p); return P('wait', tm ? t('btn.wait', { time: tm }) : t('btn.waitUnknown'), '', true); }
  if (q && !ci.active) return P('start', t('btn.start', { cr: q.id }), `data-act="start" data-cr="${esc(q.id)}"`);
  return P('open', t('btn.open'), 'data-act="open"');
}
// Seven marks. s = done | cur | wait | fail | blk | skip | next. ms.cur = index of the step the request is at (-1 when none). Dots only: no box, no tint round a step (owner, 21 Oct).
function marksOf(p, st) {
  const names = stageNames(p), a = crInfo(p).active, fin = crInfo(p).fin;
  let s = STAGE_IDS.map(() => 'next'), idx = -1;
  if (a) {
    idx = Math.max(0, STAGE_IDS.indexOf(a.stage)); const fast = a.lane === 'fast';
    s = STAGE_IDS.map((id, i) => i < idx ? 'done' : i === idx ? 'cur' : 'next');
    if (fast) STAGE_IDS.forEach((id, i) => { if (['scope', 'plan', 'approve', 'review'].includes(id) && i !== idx) s[i] = 'skip'; });
    if (a.stage === 'do' && a.verdict === 'FAIL') s[STAGE_IDS.indexOf('verify')] = 'fail';
    if (st.id === 'verify-twice') s[idx] = 'fail';
    else if (st.id === 'cpause' && st.tone === 'red') s[idx] = 'fail';
    else if (st.id === 'approval' || st.id === 'cpause') s[idx] = 'wait';
    else if (['blocked', 'hardstop', 'frozen'].includes(st.id)) s[idx] = 'blk';
  } else if (fin && fin.status === 'delivered' && !TL.on(p)) s = s.map(() => 'done');       // (with the timeline an idle project draws no rail at all, never an all-done one)
  const ms = STAGE_IDS.map((id, i) => ({ id, name: names[i], s: s[i], first: s[i] === 'fail' && a && a.stage === 'do', twice: st.id === 'verify-twice' && s[i] === 'fail' }));
  ms.cur = idx; return ms;
}
const stepMeaning = (p, id) => { const m = S.steps.meanings[id], ty = (p.playbook && p.playbook.type) || 'software'; return typeof m === 'string' ? m : (m[ty] || m.software); };
function vDate(v) { const d = v && v.date ? new Date(v.date) : null; return d && !isNaN(d) ? d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' }) : ''; }
// The step timeline (option A of revision v2): a dot on a line with the word under it; every step is a button (tap for detail). Not colour alone: the dot's shape and glyph, the line and the bold word say it too.
function rail(p, st, ms) {
  const v = p.lastVerdict, names = ms.map(m => m.name);
  const li = ms.map((m, i) => {
    const w = S.strip.marks[m.s === 'fail' ? (m.twice ? 'fail2' : m.first ? 'fail1' : 'fail') : m.s];
    const hasV = v && v.word && v.stage === m.id, cn = hasV ? countsText(v.counts) : '';
    const detail = m.s === 'done' ? (hasV ? [m.name, String(v.word).toUpperCase(), cn, vDate(v)].filter(Boolean).join(' · ') : t('steps.detailNone')) : m.name + ' · ' + stepMeaning(p, m.id);
    const rep = m.s === 'done' && hasV && v.report ? v.report : '';
    return `<li class="rsi ${m.s === 'done' ? 'ld' : ''}"><button type="button" class="rs s-${m.s}" data-step="${m.id}" data-detail="${esc(detail)}" data-report="${esc(rep)}" data-name="${esc(m.name)}" data-project="${esc(p.name)}" aria-expanded="false" aria-label="${esc(t('steps.ariaOne', { name: m.name, word: w }))}"${i === ms.cur ? ' aria-current="step"' : ''}${m.s === 'skip' ? ` title="${esc(t('steps.skipTip'))}"` : ''}><i class="dt" aria-hidden="true">${S.strip.glyph[m.s]}</i><span class="rw">${esc(m.name)}</span></button></li>`;
  }).join('');
  return `<div class="railw"><ol class="rail" aria-label="${esc(t('steps.aria', { names: names.join(', ') }))}">${li}</ol></div><div class="rdetail" data-rdetail role="region" aria-label="${esc(t('steps.title'))}" hidden></div>`;
}
function nextLine(p, st, ms) {
  if (['held', 'integrity', 'frozen', 'limit', 'noplaybook', 'idle', 'delivered', 'ap-ended'].includes(st.id) || ms.cur < 0) return '';
  if (['hardstop', 'verify-twice', 'blocked', 'cpause'].includes(st.id)) return t('steps.nextYou');
  if (st.id === 'verify-fail') return t('steps.nextAgain', { name: ms.find(m => m.id === 'verify').name });
  const nx = ms.slice(ms.cur + 1).find(m => m.s !== 'skip'); return nx ? t('steps.nextLine', { name: nx.name }) : '';
}
const countsText = c => { if (c == null) return ''; if (typeof c === 'string') return c; const total = c.total; if (!Number.isInteger(total)) return ''; return (c.failed > 0 ? c.failed : Number.isInteger(c.passed) ? c.passed : total) + ' of ' + total; };
function lastLine(p) {
  const v = p.lastVerdict; if (!v || !v.word) return '';
  const w = String(v.word).toUpperCase(), names = stageNames(p), sn = names[STAGE_IDS.indexOf(v.stage)] || cap(v.stage || ''), cls = w === 'PASS' ? 'vd-pass' : w === 'FAIL' ? 'vd-fail' : w === 'BLOCKED' ? 'vd-blk' : '', cn = countsText(v.counts);
  return `<div class="last ${cls}"><span>${esc(t('verdict.line', { stage: sn }))} <b>${esc(w)}</b>${cn ? esc(t('verdict.counts', { counts: cn })) : ''}</span>${v.report ? ` <button class="lnk" data-act="openreport" data-report="${esc(v.report)}" data-project="${esc(p.name)}" aria-label="${esc(t('verdict.reportAria', { stage: sn }))}">${esc(t('verdict.report'))}</button>` : ''}</div>`;
}
function crRow(p, id) {
  const open = crInfo(p).open; if (!open.length) return '';
  const chip = c => c.status === 'queued' ? `<span class="chip q" title="${esc(t('cr.queuedTip'))}">${esc(t('cr.queued', { id: c.id }))}</span>`
    : c.status === 'blocked' ? `<span class="chip bl" title="${esc(t('cr.blockedTip'))}"><span aria-hidden="true">!</span> ${esc(t('cr.blocked', { id: c.id }))}</span>`
    : `<span class="chip cr" title="${esc(c.id + ' ' + c.title)}">${esc(c.id)} <bdi dir="auto">${esc(c.title || '')}</bdi></span>`;
  const rest = open.slice(2);
  return `<div class="crow" data-crs>${open.slice(0, 2).map(chip).join('')}${rest.length ? `<button class="chip crmore" data-menufor="${id}" aria-label="${esc(t('cr.moreTip', { n: rest.length, list: rest.map(c => c.id).join(', ') }))}" title="${esc(t('cr.moreTip', { n: rest.length, list: rest.map(c => c.id).join(', ') }))}">${esc(t('cr.more', { n: rest.length }))}</button>` : ''}</div>`;
}
// ---- Autopilot line (revision v2): level + Safe mode on one line; the Change sheet, the Safe mode sheet and the "On its own" sheet open inside the card. The panel never changes a level or a charter itself:
// every choice posts a message and the extension types the owner's command into a terminal WITHOUT Enter.
const safeKey = p => p.level === 'warn' ? 'warn' : p.level === 'off' ? 'off' : 'strict';
function apLine(p) {
  if (!p.playbook) return '';
  const lv = p.playbook.autopilot, sk = safeKey(p), nm = esc(p.name), lname = t('ap.levels.' + lv) === 'ap.levels.' + lv ? lv : t('ap.levels.' + lv), stxt = t('safe.' + (sk === 'strict' ? 'on' : sk));
  return `<div class="apline"><button type="button" class="apl" data-sheet="level" data-project="${nm}" aria-haspopup="dialog" aria-expanded="false" title="${esc(t('ap.lineTip'))}" aria-label="${esc(t('ap.lineAria', { level: lname, project: p.name }))}"><span class="apm">${esc(t('ap.prefix'))}</span> <b>${esc(lname)}</b> <span aria-hidden="true">▾</span></button>`
    + `<button type="button" class="sfl sf-${sk}" data-sheet="safe" data-project="${nm}" aria-haspopup="dialog" aria-expanded="false" title="${esc(t('safe.tip'))}" aria-label="${esc(t('safe.aria', { project: p.name, state: stxt }))}">${sk === 'strict' ? 'Safe mode <span class="tk" aria-hidden="true">✓</span>' : esc(stxt)}</button></div>`;
}
function runLine(p) {
  const ap = p.autopilot; if (!(ap && ap.state === 'running' && p.playbook && p.playbook.autopilot === 'full') || ap.until === 'disabled') return '';
  const b = ap.budget || {}; if (b.used_pct == null || !b.cap_pct) return '';
  const left = ap.time && ap.time.left_s != null ? leftLong(ap.time.left_s) : '', o = { level: t('ap.levels.full'), left, used: Math.round(b.used_pct * 10) / 10, cap: b.cap_pct };
  return `<div class="runl">${esc(t(p.untilB && left ? 'run.untilStop' : left ? 'run.line' : 'run.lineNoTime', o))}</div>`;
}
function sheetFoot(label) { return `<div class="brow"><button type="button" class="btn quiet" data-sheetclose>${esc(label || t('ap.close'))}</button></div>`; }
function levelSheet(p, ls) {
  const lv = p.playbook.autopilot, nm = esc(p.name), busy = p.state === 'working' || p.state === 'needs-input' || (p.agents || []).length > 0, can = !!(ls && ls.ok);
  const why = to => {
    if (to === lv) return '';
    if (p.held) return t('ap.held');
    if (to === 'full') { if (p.playbook.type !== 'software') return t('ap.softwareOnly'); if (p.level !== 'strict') return 'safe'; if (p.autopilot && p.autopilot.enabled === false) return t('ap.switchOff'); }
    if (to === 'guided' && lv === 'full') return '';                      // leaving On its own is always allowed, even while it works
    return busy || !can ? t('ap.notNow') : '';
  };
  const rows = ['manual', 'guided', 'full'].map(to => {
    const w = why(to), cur = to === lv;
    return `<div class="orow"><button type="button" class="opt${cur ? ' cur' : ''}" role="radio" aria-checked="${cur ? 'true' : 'false'}" data-lv="${to}" data-project="${nm}"${w ? ' disabled' : ''}><span class="ork" aria-hidden="true">${cur ? '●' : '○'}</span><span class="ort"><b>${esc(t('ap.levels.' + to))}</b>${cur ? ` <span class="orc">${esc(t('ap.current'))}</span>` : ''}<span class="ord">${esc(t('ap.promise.' + to))}</span></span></button>`
      + (w === 'safe' ? `<div class="nhint">${esc(t('ap.needSafe'))}</div><button type="button" class="btn" data-safeto="strict" data-project="${nm}"${can && !busy ? '' : ' disabled'}>${esc(t('ap.turnSafe'))}</button>` : w ? `<div class="nhint">${esc(w)}</div>` : '') + '</div>';
  }).join('');
  return `<div class="sheet" data-sheetbox="level" data-project="${nm}" role="group" aria-label="${esc(t('ap.sheetTitle'))}" hidden><div class="chh"><b>${esc(t('ap.sheetTitle'))}</b></div><div role="radiogroup" aria-label="${esc(t('ap.sheetTitle'))}">${rows}</div>${sheetFoot()}</div>`;
}
function safeSheet(p, ls) {
  const cur = safeKey(p), nm = esc(p.name), busy = p.state === 'working' || p.state === 'needs-input' || (p.agents || []).length > 0, can = !!(ls && ls.ok) && !p.held && !busy;
  const rows = ['strict', 'warn', 'off'].map(to => {
    const isCur = to === cur, off = !isCur && (to === 'off' || !can), w = !isCur && to === 'off' ? t('safe.offBy') : !isCur && !can ? (p.held ? t('ap.held') : t('safe.busy')) : '';
    return `<div class="orow"><button type="button" class="opt${isCur ? ' cur' : ''}" role="radio" aria-checked="${isCur ? 'true' : 'false'}" data-safeto="${to}" data-project="${nm}"${off ? ' disabled' : ''}><span class="ork" aria-hidden="true">${isCur ? '●' : '○'}</span><span class="ort"><b>${esc(t('safe.opts.' + to))}</b>${isCur ? ` <span class="orc">${esc(t('ap.current'))}</span>` : ''}<span class="ord">${esc(t('safe.desc.' + to))}</span></span></button>${w ? `<div class="nhint">${esc(w)}</div>` : ''}</div>`;
  }).join('');
  return `<div class="sheet" data-sheetbox="safe" data-project="${nm}" role="group" aria-label="${esc(t('safe.sheetTitle'))}" hidden><div class="chh"><b>${esc(t('safe.sheetTitle'))}</b></div><div role="radiogroup" aria-label="${esc(t('safe.sheetTitle'))}">${rows}</div>${sheetFoot()}</div>`;
}
// "On its own": Keep going until (A this request / B I stop it, 8 hours at most / C until I disable it), three questions with presets, a live summary and a required tick. Start types the commands; nothing starts here.
function charterPre(p, ls) {                               // the one blocking reason that does not depend on the fields, '' when none
  const ap = p.autopilot, busy = p.state === 'working' || p.state === 'needs-input' || (p.agents || []).length > 0;
  if (p.held) return t('charter.whyHeld');
  if (p.level !== 'strict') return t('ap.needSafe');
  if (p.playbook.type !== 'software') return t('ap.softwareOnly');
  if (busy || !(ls && ls.ok)) return t('charter.whyBusy', { project: p.name });
  if (ap && ap.enabled === false) return t('charter.whySwitch');
  return '';
}
function ownSheet(p, ls, i, wk, cap) {
  if (!p.playbook || p.held) return '';
  const R = CHARTER.RULES, U = CHARTER.UNTIL, H = `ow${i}`, nm = esc(p.name), O = S.own;
  const crs = crInfo(p).open.filter(c => c.status === 'open' || c.status === 'queued').map(c => ({ id: c.id, title: c.title || '', active: c.status === 'open', chat: c.in_chat === true }));
  const msg = { untilA: O.until.a.hint, untilB: O.until.b.hint, untilC: O.until.c.hint, bmore: O.until.b.more, chat: O.chatOpened, timeB: O.timeStop8, timeC: O.timeDay, left: O.left, leftNone: O.leftNone, over: O.over, sumA: O.summaryA, sumAdeps: O.summaryAdeps, sumB: O.summaryB, sumC: O.summaryC,
    tickA: O.tickA, tickB: O.tickB, tickC: O.tickC, whyOff: O.startOff, noCr: O.noCrWhy, notReady: O.notReady, foldersWhy: O.foldersWhy, tickWhy: O.tickWhy, dayWhy: O.dayWhy, and: 'and' };
  const pre = (kind, vals, unit, def) => `<div class="pres" role="group" data-pres="${kind}" aria-label="${esc(kind)}">${vals.map(v => `<button type="button" class="pre" data-pre="${kind}" data-v="${v}" aria-pressed="${v === def ? 'true' : 'false'}">${v}${unit}</button>`).join('')}</div>`;
  const cn = S.cnote;
  return `<div class="sheet own" role="group" aria-labelledby="${H}" data-sheetbox="own" data-own="${nm}" data-crs="${esc(JSON.stringify(crs))}" data-folders="${esc(JSON.stringify(p.folders || []))}" data-week="${wk == null ? '' : esc(String(wk))}" data-blocked="${esc(charterPre(p, ls))}" data-cok="${cap ? '1' : ''}" data-msg="${esc(JSON.stringify(msg))}" hidden>
    <div class="chh" id="${H}"><b>${esc(t('own.heading', { project: p.name }))}</b></div>
    <div class="nhint">${esc(t('own.intro'))}</div>
    <label class="flabel">${esc(t('own.untilLabel'))}<select class="fsel" data-of="until"><option value="a">${esc(O.until.a.label)}</option><option value="b">${esc(O.until.b.label)}</option><option value="c">${esc(O.until.c.label)}</option></select></label>
    <div class="nhint" data-ohint dir="auto"></div>
    <ul class="olist" data-olist aria-label="${esc(O.listAria)}" hidden></ul>
    <div class="cnote" data-cnote role="alert" hidden><b class="cnh">${esc(cn.heading)}</b><ul>${cn.lines.map((l, k) => `<li${k === 3 ? ' data-cline4' : ''} data-tpl="${esc(l)}">${esc(l)}</li>`).join('')}</ul><div class="cnone">${esc(cn.one)}</div></div>
    <div class="oq" data-oqtime><div class="ql">${esc(O.timeQ)}</div>${pre('time', [1, 3, 8], ' h', 3)}<div class="nhint" data-otimetxt hidden></div></div>
    <div class="oq"><div class="ql">${esc(O.budgetQ)}</div>${pre('budget', [5, 10, 25], '%', 10)}<div class="nhint" data-oleft aria-live="polite"></div></div>
    <div class="oq" data-oqday hidden><div class="ql">${esc(O.dayQ)}</div>${pre('day', [2, 4, 8], '%', 4)}</div>
    <details class="chex" data-omore><summary>${esc(O.more)}</summary>
      <label class="flabel">${esc(O.goal)}<input class="fin" type="text" data-of="goal" autocomplete="off" spellcheck="false" placeholder="${esc(O.goalPh)}" dir="auto"></label><div class="nhint bad" data-oerr="goal" hidden></div>
      <label class="flabel">${esc(O.folders)}<input class="fin" type="text" data-of="folders" autocomplete="off" spellcheck="false" placeholder="${esc(O.foldersPh)}" dir="ltr"></label><div class="nhint bad" data-oerr="scope" hidden></div>
      <fieldset class="chfs"><legend>${esc(O.deps)}</legend>
        <label class="copt"><input type="radio" name="od${i}" value="none" data-of="depsMode" checked>${esc(O.depsNone)}</label>
        <label class="copt"><input type="radio" name="od${i}" value="listed" data-of="depsMode">${esc(O.depsListed)}</label>
        <input class="fin" type="text" data-of="deps" autocomplete="off" spellcheck="false" placeholder="${esc(O.depsPh)}" aria-label="${esc(O.deps)}" dir="ltr" hidden></fieldset><div class="nhint bad" data-oerr="deps" hidden></div>
      <label class="flabel">${esc(O.hours)}<input class="fin" type="text" inputmode="decimal" data-of="hours" autocomplete="off"></label><div class="nhint bad" data-oerr="time" hidden></div>
      <label class="flabel">${esc(O.share)}<input class="fin" type="text" inputmode="numeric" data-of="share" autocomplete="off"></label><div class="nhint bad" data-oerr="budget" hidden></div>
      <div data-oqcrs hidden><div class="ql">${esc(O.crsQ)}</div>${pre('crs', [1, 2, 3, 5], '', U.crsDefault)}</div>
      <details class="chex"><summary>${esc(O.never)}</summary><div class="chlist" dir="ltr">${R.alwaysExcluded.map(x => `<code>${esc(x)}</code>`).join(' ')}</div></details>
      <details class="chex"><summary>${esc(O.stops)}</summary><ul class="chstops">${S.charter.stopList.map(x => `<li>${esc(x)}</li>`).join('')}</ul></details>
      <div class="nhint">${esc(O.moreStep)}</div></details>
    <div class="nhint bad" data-oerr="ends" hidden></div>
    <div class="osum" data-osum aria-live="polite"></div>
    <label class="copt tick"><input type="checkbox" data-of="tick"><span data-otick></span></label>
    <div class="nhint bad" data-owhy role="status" aria-live="polite"></div>
    <div class="brow"><button type="button" class="btn go" data-ostart disabled>${esc(O.start)}</button><button type="button" class="btn quiet" data-ocancel>${esc(O.cancel)}</button></div></div>`;
}
// Option C pieces: the band on the card, the waiting rows, the banner on every tab.
function cBand(p, st) {
  const ap = p.autopilot; if (!cOf(p)) return '';
  if (st.id === 'cpause') return `<div class="cband ${st.tone === 'red' ? 'red' : 'amber'}" role="status"><span class="cbm" aria-hidden="true">${st.tone === 'red' ? '✕' : '!'}</span><span class="cbt" dir="auto">${esc(st.text)}</span></div>`;
  if (ap.state === 'running' && st.id !== 'cwaiting') return `<div class="cband amber" role="status"><span class="cbm" aria-hidden="true">!</span><span class="cbt">${esc(t('cband.running'))}</span></div>`;
  return '';
}
function cWaiting(p, cap) {
  const w = (p.autopilot && p.autopilot.waiting) || []; if (!cOf(p) || !w.length) return '';
  return `<div class="cwait" role="group" aria-label="${esc(t('cwait.head'))}"><div class="nh">${esc(t('cwait.head'))}</div>${w.map(x => `<div class="cwrow"><div class="cwt" dir="auto">${esc(t(x.in_chat ? 'cwait.row' : 'cwait.rowTerm', { id: x.id, title: x.title }))}</div><div class="brow"><button type="button" class="btn" data-act="cverb" data-verb="admit" data-cr="${esc(x.id)}" data-project="${esc(p.name)}"${cap ? '' : ' disabled'} title="${esc(cap ? t('cwait.verbTip') : t('own.notReadyTip'))}">${esc(t('cwait.btn'))}</button></div></div>`).join('')}</div>`;
}
function cBanner(ps) {
  const p = ps.find(cOf); if (!p) return '';
  const ap = p.autopilot, b = ap.budget || {}, d = ap.day || {}, w = (ap.waiting || []).length, r1 = v => Math.round((v || 0) * 10) / 10, paused = ap.state === 'paused';
  let text;
  if (paused) { const cp = S.cpause[ap.reason], reason = ap.stop ? (stopWords(ap.stop) || t('status.hardstopDefault')) : cp ? t('cpause.' + ap.reason + '.short', { cr: ap.cr || t('now.crFallback') }) : String(ap.reason || ''); text = t('cban.paused', { reason }); }
  else text = t('cban.run', { h: Math.max(1, Math.ceil((ap.seg_left_s || 0) / 3600)), day: r1(d.used_pct), dayCap: d.cap_pct == null ? '?' : d.cap_pct, week: r1(b.used_pct), weekCap: b.cap_pct == null ? '?' : b.cap_pct }) + (w ? t(w === 1 ? 'cban.waiting' : 'cban.waitingMany', { n: w }) : '');
  return `<div class="cban${paused ? ' red' : ''}" role="status" aria-label="${esc(t('cban.aria'))}" data-cban><span class="cbt" dir="auto">${esc(text)}</span>${paused ? `<button type="button" class="btn quiet" data-act="apstop" data-project="${esc(p.name)}" data-sure="${esc(t('run.stopSure'))}" title="${esc(t('run.stopTip'))}">${esc(t('cban.stop'))}</button>` : ''}</div>`;
}
const STOP_ID = /^H-[0-9a-f]{6}$/;
function decideBox(p, st) {
  if (st.id !== 'hardstop') return '';
  const stop = (p.autopilot && p.autopilot.stop) || {}, id = String(stop.id || ''), ok = STOP_ID.test(id), nm = esc(p.name);
  return `<div class="addbox decide" role="group" aria-label="${esc(t('decide.heading', { text: stopWords(stop) || t('status.hardstopDefault') }))}" data-decide="${nm}" hidden>
    <div class="chh"><b>${esc(t('decide.heading', { text: stopWords(stop) || t('status.hardstopDefault') }))}</b></div>
    <div class="nhint">${esc(t('decide.why'))}</div>
    ${ok ? `<div class="nhint">${esc(t('decide.allowLead'))}</div><code class="chcmd" data-dcmd dir="ltr">shipm autopilot allow ${esc(id)} --project ${nm}</code>` : `<div class="nhint">${esc(t('decide.noId'))}</div>`}
    <div class="brow">${ok ? `<button class="btn go" data-act="allowterm" data-project="${nm}" title="${esc(t('decide.allowTip'))}">${esc(t('decide.allowBtn'))}</button>` : '<span></span>'}<button class="btn stopq" data-act="ap" data-to="guided" data-project="${nm}" data-sure="${esc(t('run.stopSure'))}" title="${esc(t('run.stopTip'))}">${esc(t('run.stop'))}</button></div>
    <div class="frow"><button class="btn" data-act="open" title="${esc(t('decide.allowChat', { id }))}">${esc(t('decide.chat'))}</button><button class="btn quiet" data-act="dclose">${esc(t('decide.close'))}</button></div></div>`;
}
function apWaitRow(p) {
  const w = p.apWait; if (!w) return '';
  const detail = w.kind === 'full' ? t('autopilot.waitFull') : w.kind === 'back' ? t('autopilot.waitBack') : t('autopilot.waitLevel', { to: w.to });
  return `<div class="apwait" role="status" title="${esc(t('autopilot.waitTip'))}">${svg('spin', 'spinning accent')}<span><b>${esc(t('autopilot.waitTitle'))}</b> ${esc(detail)}</span><button class="btn" data-act="showterm" data-project="${esc(p.name)}">${esc(t('autopilot.waitOpen'))}</button></div>`;
}
// ---- Ask aside (F3): types `/btw ` into the project's chat WITHOUT Enter. Quiet button on the card (hidden below 300 px) and a ⋯ item (shown there). Disabled with the reason when no chat is open.
function asideOff(p) { return !p.chatOpen ? t('ask.asideNoChat', { project: p.name }) : ''; }
function asideTitle(p) { const off = asideOff(p); return off ? off + ' ' + t('ask.asideTip') : t('ask.asideTip'); }
function asideBtn(p) {
  const off = asideOff(p);
  return `<button class="btn quiet aside" data-ask="aside" data-project="${esc(p.name)}" aria-label="${esc(off ? t('ask.aside') + ': ' + off : t('ask.asideAria', { project: p.name }))}" title="${esc(asideTitle(p))}"${off ? ' disabled' : ''}>${esc(t('ask.aside'))}</button>`;
}
function menuHtml(p, st, i) {
  const hasCtx = p.context && (p.context.level === 'soft' || p.context.level === 'strong'), busy = p.state === 'working' || p.state === 'needs-input' || (p.agents || []).length > 0, h = p.handoff;
  const it = (label, attrs, o = {}) => `<button class="mi" role="menuitem" tabindex="-1" ${attrs}${o.disabled ? ' disabled' : ''}${o.title ? ` title="${esc(o.title)}"` : ''}>${esc(label)}${o.dot ? '<span class="mdot" aria-hidden="true"></span>' : ''}</button>`;
  const rest = crInfo(p).open.slice(2), nm = esc(p.name);
  const items = [it(t('menu.open'), 'data-act="open"')];
  if (st.id === 'cpause') {
    const cp = S.cpause[p.autopilot.reason];
    if (cp && cp.drop && p.autopilot.cr) items.push(it(t('cwait.drop', { cr: p.autopilot.cr }), `data-act="cverb" data-verb="drop" data-cr="${esc(p.autopilot.cr)}" data-project="${nm}" data-sure="${esc(t('run.stopSure'))}"`));
  }
  if (p.lastVerdict && p.lastVerdict.report) items.push(it(t('menu.report'), `data-act="openreport" data-report="${esc(p.lastVerdict.report)}" data-project="${nm}"`));
  if (p.playbook) items.push(it(t('menu.autopilot'), `data-sheet="level" data-project="${nm}"`), it(t('menu.safe'), `data-sheet="safe" data-project="${nm}"`));
  if (!p.playbook && !p.held) items.push(it(t('menu.setup'), `data-act="setup" data-project="${nm}"`, { title: t('btnTip.setup') }));
  items.push(h ? it('Open fresh chat', `data-handoff="open" data-project="${nm}"`, { disabled: !h.ready || busy, title: busy ? 'Wait: an agent is working.' : '' })
    : it(t('menu.handoff'), `data-handoff="ask" data-project="${nm}" data-sure="${esc(t('btn.handoffSure'))}"`, { disabled: busy, dot: hasCtx, title: busy ? 'Wait: an agent is working.' : hasCtx ? t('menu.handoffDot') : '' }));
  items.push(it(t('menu.askAside'), `data-ask="aside" data-project="${nm}"`, { disabled: !!asideOff(p), title: asideTitle(p) }).replace('class="mi"', 'class="mi askmi"'));
  if (tbOn(p)) items.push(it(p.toolbox.count > 0 ? t('toolbox.menuItemN', { n: p.toolbox.count }) : t('toolbox.menuItem'), `data-sheet="toolbox" data-project="${nm}"`));
  if (ivOn() && !p.playbook && !p.held) items.push(it(t('describe.menuItem'), `data-sheet="describe" data-project="${nm}"`));
  if (asideOn() && p.aside) items.push(p.aside.on ? it(t('aside.bringBack'), `data-aside="unaside" data-project="${nm}"`) : it(t('aside.setAside'), `data-aside="aside" data-project="${nm}"`, { disabled: !p.aside.canAside, title: p.aside.canAside ? '' : (p.aside.reason || '') }));
  // F5 extension point: the 'Toolbox' item goes here (added with the Toolbox view)
  items.push(it(t('menu.newWindow'), 'data-act="newwin"'), it(t('menu.relaunch'), `data-act="relaunch" data-project="${nm}"`), it(t('menu.health'), 'data-hopen="-"'));
  return `<div class="menu" id="m${i}" role="menu" aria-label="${esc(t('btn.more', { project: p.name }))}" hidden>${items.join('')}${rest.length ? `<div class="mh" role="presentation">${esc(t('menu.moreCrs'))}</div>${rest.map(c => `<div class="mn" role="presentation" dir="auto">${esc(c.id + ' ' + (c.title || '') + ' · ' + c.status)}</div>`).join('')}` : ''}</div>`;
}
const X = require('./cardx')({ t, esc, S, cap, crInfo, stageNames, STAGE_IDS, STEPS });             // F5-F9 card extras (Details, Set aside, Toolbox, Describe your work): see cardx.js
const TLX = require('./timeline'), TL = TLX({ t, esc, S, crInfo, caps: () => X.getCtx().capabilities || {}, stageNames: p => stageNames(p) });   // two-level timeline (release line, idle block, History): see timeline.js
const { detailRegion, detailToggle, quietText, toolboxSheet, describeSheet, interviewBlock, asideRows, asideNotice, asideHealth, isAsideRow, asideOn, tbOn, ivOn } = X;
function card(p, ls, i = 0, wk = null, cap = false) {
  const [ic, tone] = STATE[p.state] || STATE.idle, t0 = p.tokens, now = Date.now() / 1000, v3 = !!p.playbook, ci = crInfo(p), a = ci.active;
  const st = stateOf(p), pr = primaryOf(p, st, cap), ms = v3 ? marksOf(p, st) : null, ap = p.autopilot, cx = cOf(p);
  const chips = [];
  if (p.chatOpen) chips.push(`<span class="chip open">chat open</span>`);
  const linked = new Set();
  p.agents.filter(a1 => a1.stalled).forEach(a1 => {                    // a stalled agent links to its frozen_agent item in the Health tab when there is one
    const full = `${a1.type} quiet ${Math.round(a1.quiet / 60)} min`, fa = (p.health || []).filter(x => x.kind === 'frozen_agent'), it = fa.find(x => x.agent && x.agent === (a1.id || a1.agent)) || fa.find(x => !x.agent && !linked.has(x.id)) || fa.find(x => !linked.has(x.id));
    if (it) { linked.add(it.id); chips.push(`<button class="chip stall" data-hopen="${esc(it.id)}" title="${esc(full + '. Click to open it in the Health tab.')}">${esc(full)}</button>`); }
    else chips.push(`<span class="chip stall" title="${esc(full)}">${esc(full)}</span>`); });
  chips.push(...flowChips(p));
  const hc = healthChips(p, linked); if (hc) chips.push(hc);
  { const cc = ctxChip(p); if (cc) chips.push(cc); }
  if (p.chatStale) chips.unshift(`<button class="chip relaunch" data-relaunch="${esc(p.dir)}" data-project="${esc(p.name)}" title="${esc(p.chatOld ? 'This chat was started by the old launcher: a full VS Code restart would open a blank conversation. Click to reopen it once (the conversation continues)' : 'This chat lost its link to VS Code after a restart (the yellow marker on its tab). Click to reopen it: same conversation, fresh link.')}">↻ relaunch chat</button>`);
  if (p.ci && p.ci.conclusion === 'failure') chips.unshift(`<button class="chip ci fail" data-ci="${esc(p.ci.url)}" title="The latest GitHub Actions run on main failed: ${esc(p.ci.title)}. Click to open it.">CI failing</button>`);
  else if (p.ci && p.ci.status && p.ci.status !== 'completed' && p.ci.status !== 'none') chips.unshift(`<button class="chip ci" data-ci="${esc(p.ci.url)}" title="A GitHub Actions run on main is in progress. Click to open it.">CI running</button>`);
  const facts = [];
  if (p.pushFailed) facts.push('<span class="danger">push failed</span>');
  if (p.dirty) facts.push(`${p.dirty} uncommitted`);
  if (p.ahead) facts.push(`${p.ahead} not pushed`);
  if (p.context && p.context.level === 'none') facts.push(t('ctx.plain', { k: kfmt(p.context.tokens) }));
  if (!facts.length && p.lastCommit) facts.push('clean · ' + ago(now - p.lastCommit));
  if (!v3) facts.unshift(`<span title="${esc(t('status.noPlaybook'))}">${esc(t('status.typeNotSet'))}</span>`);
  const tokens = t0.ledgerDay != null ? `Today: ${fmt(t0.ledgerDay)} tokens (incl. cache reads)` : t0.claudeDay
    ? `Today: Claude ${fmt(t0.claudeDay)}`
    : t0.claudeWeek ? `This week: Claude ${fmt(t0.claudeWeek)}` : 'No tokens this week';
  const ctx = esc(JSON.stringify({ webviewSection: 'project', dir: p.dir, name: p.name, preventDefaultContextMenuItems: true }));
  const data = `data-state="${esc(st.id)}" data-stage="${esc(a ? a.stage : '')}" data-cr="${esc(a ? a.id : '')}" data-verdict="${esc(p.lastVerdict ? p.lastVerdict.word : '')}" data-autopilot="${esc(p.playbook ? p.playbook.autopilot : '')}" data-primary="${esc(pr.key)}" data-chips="${esc(ci.open.map(c => c.id + ':' + c.status).join(','))}"`;
  const mid = `m${i}`, nm = esc(p.name);
  const running = !!(ap && ap.state === 'running' && p.playbook && p.playbook.autopilot === 'full');
  const stopBtn = cx ? `<button type="button" class="btn stopc" data-act="apstop" data-project="${nm}" data-sure="${esc(t('run.stopSure'))}" title="${esc(t('run.stopTip'))}">${esc(t('run.stop'))}</button>`
    : running ? `<button type="button" class="btn stopq" data-act="ap" data-to="guided" data-project="${nm}" data-sure="${esc(t('run.stopSure'))}" title="${esc(t('run.stopTip'))}">${esc(t('run.stop'))}</button>` : '';
  const nl = v3 ? nextLine(p, st, ms) : '', tlOn = v3 && TL.on(p);
  const band = v3 ? cBand(p, st) : '', dreg = detailRegion(p), un = X.getCtx().settings.unreadMarker && (p.unread === 'turn' || p.unread === 'wait') ? p.unread : '';
  return `<div class="card st-${tone}${p.active ? ' active' : ''}${st.tone ? ' tn-' + st.tone : ''}${dreg.ready ? ' dok' : ''}" ${p.active ? 'aria-current="true" ' : ''}${data} data-dir="${esc(p.dir)}" data-vscode-context='${ctx}' tabindex="0" role="button" aria-label="${esc((un ? t('unread.cardAria', { project: p.name, why: t(un === 'turn' ? 'unread.whyTurn' : 'unread.whyWait') }) + '. ' : '') + t('a11y.projectCard', { project: p.name }))}" title="${esc(t(MACH ? 'help.cardTip' : 'help.cardTipOther'))}">
    <div class="top">${svg(ic, ic === 'spin' ? 'spinning ' + tone : tone)}<span class="name" title="${esc(p.name)}">${esc(p.name)}</span><span class="tag">${esc(v3 ? p.playbook.type : p.stack)}</span>${un ? `<span class="newm" title="${esc(t('unread.' + un))}"><i class="udot" aria-hidden="true"></i>${esc(t('unread.word'))}</span>` : ''}${detailToggle(p)}</div>
    ${tlOn ? TL.releaseLine(p) : ''}${band}
    ${asideOn() && p.aside && p.aside.on && p.aside.backOnList ? `<div class="nhint backl">${esc(t('aside.backOnList', { why: p.aside.backOnList }))}</div>` : ''}
    ${st.id === 'cpause' ? '' : `<div class="sub${st.tone ? ' ' + st.tone : ''}" title="${esc(st.text)}">${esc(st.text)}</div>`}
    ${tlOn && !ci.open.length ? TL.idleBlock(p, st) : v3 ? rail(p, st, ms) : flowStrip(p.flow)}
    ${nl ? `<div class="nextl">${esc(nl)}</div>` : ''}
    ${p.quiet ? `<div class="nextl quietl" data-quiet>${esc(quietText(p.quiet))}</div>` : ''}
    ${dreg.html}
    ${v3 ? apLine(p) : ''}
    ${v3 ? runLine(p) : ''}
    ${v3 ? cWaiting(p, cap) : ''}
    ${v3 ? '' : flowMeta(p.flow)}
    ${v3 ? crRow(p, mid) : ''}
    ${v3 ? lastLine(p) : ''}${tlOn ? TL.historyBlock(p) : ''}
    ${chips.length ? `<div class="chips">${chips.join('')}</div>` : ''}
    ${interviewBlock(p)}
    ${X.proposedBlock(p)}
    ${apWaitRow(p)}
    ${handoffRow(p)}
    ${decideBox(p, st)}
    ${st.id === 'approval' ? `<div class="nhint planhint" data-planhint="${esc(p.name)}" role="status" hidden>${esc(t('plan.hint'))}</div>` : ''}
    <div class="brow"><button class="btn primary" data-primary="${pr.key}" ${pr.attrs} data-project="${nm}" title="${esc(pr.tip)}"${pr.disabled ? ' disabled' : ''}>${un && pr.key === 'open' ? '<i class="udot udotb" aria-hidden="true"></i>' : ''}${esc(pr.label)}</button>${stopBtn || asideBtn(p)}<div class="mwrap"><button class="btn more" aria-haspopup="menu" aria-expanded="false" aria-controls="${mid}" aria-label="${esc(t('btn.more', { project: p.name }))}" title="${esc(t('btn.more', { project: p.name }))}">${t('btn.moreShort')}</button>${menuHtml(p, st, i)}</div></div>
    <div class="foot"><span>${tokens}</span><span>${facts.join(' · ')}</span></div>
    ${v3 ? levelSheet(p, ls) + safeSheet(p, ls) + ownSheet(p, ls, i, wk, cap) : ''}
    ${toolboxSheet(p)}${describeSheet(p, i)}
  </div>`;
}
// ---- Ask inbox card (F4). Shown when the project's data says ask.inbox. `shipm ask` spends quota and is owner-only: Ask TYPES the command into the owner terminal without Enter. The card is not a project:
// no stage strip, no chat opening, not counted in the Waiting block (it is filtered out of the project list before nowBlock).
function askCard(p) {
  const a = p.ask, n = a.questions_today, cap = Number.isInteger(a.limit) && a.limit >= 1 && a.limit <= 200 ? a.limit : 20, full = n >= cap, nm = esc(p.name);
  const last = a.last
    ? `<div class="alast"><span class="alt">${esc(t('ask.last'))}: <b dir="auto" title="${esc(a.last.title)}">${esc(a.last.title || a.last.path)}</b></span><div class="frow"><button class="btn" data-ask="open" aria-label="${esc(t('ask.openAria', { title: a.last.title || a.last.path }))}">${esc(t('ask.open'))}</button><button class="btn quiet" data-ask="promote" title="${esc(t('ask.promoteTip'))}">${esc(t('ask.promote'))}</button></div></div>`
    : `<div class="nhint aempty">${esc(t('ask.noNotes'))}</div>`;
  return `<div class="card askcard" data-askcard="${nm}" role="group" aria-label="${esc(t('ask.title'))}">
    <div class="top"><span class="name">${esc(t('ask.title'))}</span></div>
    <div class="sub">${esc(t('ask.sub'))}</div>
    <label class="flabel askl"><span>${esc(t('ask.label'))}</span><input class="fin" type="text" data-askq maxlength="2000" dir="auto" autocomplete="off" spellcheck="false" placeholder="${esc(t('ask.placeholder'))}" aria-describedby="askc"></label>
    <div class="arow"><span class="nhint" id="askc" data-askcount data-max="2000" data-fmt="${esc(t('ask.counter', { n: '{n}', max: 2000 }))}" data-dash="${esc(t('ask.dash'))}">${esc(t('ask.counter', { n: 0, max: 2000 }))}</span></div>
    ${a.model_supported === true ? `<label class="flabel askl"><span>${esc(t('ask.model'))}</span><select class="fsel" data-askmodel><option value="opus">${esc(t('ask.modelOpus'))}</option><option value="sonnet">${esc(t('ask.modelSonnet'))}</option><option value="haiku">${esc(t('ask.modelHaiku'))}</option></select></label><div class="nhint">${esc(t('ask.modelHint'))}</div>
    <div class="nhint">${esc(t('ask.preview'))}</div><code class="chcmd askprev" data-askprev dir="ltr"></code>` : ''}
    <div class="brow askbtns"><button class="btn primary" data-ask="type" data-askgo disabled${full ? ' data-full="1"' : ''} aria-label="${esc(t('ask.sendAria'))}" title="${esc(full ? t('ask.fullTip', { limit: cap }) : t('ask.sendTip'))}">${esc(t('ask.send'))}</button><button class="btn quiet" data-ask="clear">${esc(t('ask.cancel'))}</button></div>
    <div class="nhint atoday${full ? ' bad' : ''}" data-asktoday>${esc(t('ask.today', { n, max: cap }))}${full ? ' ' + esc(t('ask.todayFull')) : ''}</div>
    ${last}
  </div>`;
}
// ---- Now / Next / Waiting on you (spec section 3): above the cards; aria-live is used here and nowhere else on the cards
function nowModel(ps) {
  const w = [], n = [], x = [];
  ps.forEach(p => {
    const st = stateOf(p), pr = primaryOf(p, st), ci = crInfo(p), a = ci.active;
    if (pr.key === 'plan' || pr.key === 'decide') {
      const txt = pr.key === 'plan' ? (a ? t('now.approve', { cr: a.id }) : t('now.approveNoCr'))
        : st.id === 'verify-twice' ? t('now.twice', { cr: a ? a.id : t('now.crFallback') }) : st.id === 'hardstop' ? stopWords(p.autopilot && p.autopilot.stop) || t('status.hardstopDefault') : st.id === 'blocked' ? t('now.blocked', { cr: a ? a.id : t('now.crFallback') }) : (p.message || t('now.answer'));
      w.push({ p, txt, pr, what: pr.label }); return;
    }
    if (p.state === 'working' && !p.held) { const m0 = (p.agents || [])[0], mins = m0 && m0.mins ? ` · ${t('now.minutes', { n: m0.mins })}` : ''; n.push({ p, txt: st.text + mins }); }
    if (ci.queued.length && !p.held) x.push({ p, txt: t('now.queued', { cr: ci.queued[0].id }) });
  });
  return { w, n, x };
}
function nowBlock(ps) {
  const m = nowModel(ps), rows = (list, kind) => {
    const li = (r, k) => `<li class="nrow${k >= 3 ? ' xtra' : ''}"${k >= 3 ? ' hidden' : ''}><span class="nproj" title="${esc(r.p.name)}">${esc(r.p.name)}</span><span class="ntxt" title="${esc(r.txt)}" dir="auto">${esc(r.txt)}</span>${kind === 'w' ? `<button class="btn" data-primary="${r.pr.key}" ${r.pr.attrs} data-project="${esc(r.p.name)}" data-pdir="${esc(r.p.dir)}" aria-label="${esc(t('now.openAria', { what: r.what, project: r.p.name }))}">${esc(t('now.open'))}</button>` : ''}</li>`;
    return `<ul class="nlist">${list.map(li).join('')}</ul>${list.length > 3 ? `<button class="lnk nmore" data-nmore aria-expanded="false" data-more="${esc(t('now.more', { n: list.length - 3 }))}" data-less="${esc(t('now.less'))}">${esc(t('now.more', { n: list.length - 3 }))}</button>` : ''}`;
  };
  const sec = (cls, head, list, kind) => list.length ? `<div class="nsec ${cls}"><div class="nh">${esc(head)}</div>${rows(list, kind)}</div>` : '';
  if (!m.w.length && !m.n.length && !m.x.length) return `<section class="nowblk empty" aria-live="polite" aria-label="${esc(t('now.aria'))}"><span class="nempty">${esc(t('now.empty'))}</span></section>`;
  return `<section class="nowblk" aria-live="polite" aria-label="${esc(t('now.aria'))}">${m.w.length ? '' : `<div class="nempty">${esc(t('now.empty'))}</div>`}${sec('nwait', `${t('now.waiting')} (${m.w.length})`, m.w, 'w')}${sec('nnow', t('now.nowH'), m.n, 'n')}${sec('nnext', t('now.next'), m.x, 'x')}</section>`;
}

// ---- Ideas tab: a clean checklist per project. Buttons are real buttons (class .btn); no inline styles (CSP).
const VCLS = v => /^BUILD NOW/i.test(v) ? 'green' : /^BUILD LATER/i.test(v) ? 'amber' : /^(MERGE|MOVE)/i.test(v) ? 'blue' : /^SPLIT OUT/i.test(v) ? 'purple' : 'grey';
const label = p => p.special === 'ideas' ? 'Inbox' : p.name;
function ideaItem(p, i, names) {
  const dis = p.held ? ' disabled' : '';
  const short = i.verdict ? i.verdict.split(' · ').slice(0, 2).join(' · ') : '';
  const mv = (i.verdict.match(/^MOVE to ([^ ·]+)/i) || [])[1];                  // the review recommended another existing project
  const target = mv && names.find(n => n.toLowerCase() === mv.toLowerCase() || (n === 'ideas' && /^inbox$/i.test(mv)));
  const primary = !i.verdict ? ['worth', 'Worth it?', ''] : /^BUILD NOW/i.test(i.verdict) ? ['plan', 'Plan this', ''] : /^SPLIT OUT/i.test(i.verdict) ? ['newproject', 'Create project…', '']
    : target && target !== p.name ? ['moveto', 'Move to ' + esc(target === 'ideas' ? 'Inbox' : target), target] : null;
  const pk = (op, text) => `<button class="btn" data-pick="${op}" data-project="${esc(p.name)}" data-id="${esc(i.id)}"${dis}>${text}</button>`;
  const b = (op, text, cls = '', to = '') => `<button class="btn ${cls}" data-idea data-op="${op}" data-project="${esc(p.name)}" data-id="${esc(i.id)}"${to ? ` data-to="${esc(to)}"` : ''}${dis}>${text}</button>`;
  return `<li class="idea">
    <button class="cb" data-idea data-op="done" data-project="${esc(p.name)}" data-id="${esc(i.id)}" aria-label="Mark ${esc(i.id)} as done" title="Mark as done"${dis}></button>
    <div class="ibody"><div class="itext">${esc(i.text)}</div>
      <div class="imeta"><span>${esc(i.id)}${i.date ? ' · ' + esc(i.date) : ''}</span>${i.tags.map(t => `<span class="itag">${esc(t)}</span>`).join('')}${short ? `<span class="pill ${VCLS(i.verdict)}" title="${esc(i.verdict)}">${esc(short)}</span>` : ''}</div>
      <div class="iacts">${primary ? b(primary[0], primary[1], 'primary', primary[2]) : ''}${pk('move', 'Move…')}${pk('copy', 'Copy…')}${b('drop', 'Drop', 'quiet')}</div></div></li>`;
}
function addBox(p, all) {                      // the add form lives in the tab itself (no VS Code input bar); the project is a dropdown
  const opts = all.filter(x => !x.held).map(x => `<option value="${esc(x.name)}"${x.name === p.name ? ' selected' : ''}>${esc(label(x))}${x.special === 'ideas' ? ' (not sure yet)' : ''}</option>`).join('');
  return `<div class="addbox" data-addbox hidden>
    <label class="flabel">Project<select class="fsel" data-f="project">${opts}</select></label>
    <label class="flabel">Idea<textarea class="ftext" data-f="text" rows="3" maxlength="500" placeholder="One or two lines. Add #tags if you like (#export #report)."></textarea></label>
    <div class="frow"><button class="btn primary" data-form="add">Add</button><button class="btn quiet" data-form="cancel">Cancel</button><button class="btn wide" data-form="addreview" title="Add it, then open a chat to check if it is worth building">Add and check if it is worth it</button></div></div>`;
}
function ideaList(p, names, all0) {
  const all = [...p.ideas.open, ...p.ideas.evaluated];
  const addBtn = `<button class="btn primary" data-toggle="addbox"${p.held ? ' disabled' : ''}>+ Add idea</button>`;
  return `<div class="ilist" data-proj="${esc(p.name)}" hidden>
    <div class="ititle"><div class="itl"><span class="iname">${esc(label(p))}</span><span class="isub">${p.ideas.open.length} open${p.ideas.evaluated.length ? ' · ' + p.ideas.evaluated.length + ' reviewed' : ''}</span></div>${addBtn}</div>
    ${p.held ? '<div class="inote">This project\'s session is still running. Ideas can be added when it finishes.</div>' : addBox(p, all0)}
    ${all.length ? `<ul class="ideas">${all.map(i => ideaItem(p, i, names)).join('')}</ul>` : '<div class="iempty">No ideas yet.<br>Press <b>+ Add idea</b>, or tell any chat: <i>add idea: …</i></div>'}
    ${(p.ideas.done || p.ideas.dropped) ? `<details class="idone"><summary>Done ${p.ideas.done} · Dropped ${p.ideas.dropped}</summary><div class="isub">Kept in docs/FEATURE-IDEAS.md</div></details>` : ''}
    <div class="ifoot"><button class="btn quiet" data-idea data-op="never" data-project="${esc(p.name)}" title="Stop asking me about ${esc(label(p))}'s ideas">Mute reminders</button></div>
  </div>`;
}
function ideaAll(ps, all0, def) {                       // the "All projects" view: every idea of every project, grouped by project
  const names = ps.map(x => x.name), open = ps.reduce((a, q) => a + q.ideas.open.length, 0), rev = ps.reduce((a, q) => a + q.ideas.evaluated.length, 0);
  const groups = ps.filter(q => q.ideas.open.length + q.ideas.evaluated.length).map(q => `<section class="igroup"><div class="igname"><span>${esc(label(q))}</span><span class="isub">${q.ideas.open.length} open${q.ideas.evaluated.length ? ' · ' + q.ideas.evaluated.length + ' reviewed' : ''}</span></div>
    <ul class="ideas">${[...q.ideas.open, ...q.ideas.evaluated].map(i => ideaItem(q, i, names)).join('')}</ul></section>`).join('');
  return `<div class="ilist" data-proj="__all__" hidden>
    <div class="ititle"><div class="itl"><span class="iname">All projects</span><span class="isub">${open} open${rev ? ' · ' + rev + ' reviewed' : ''}</span></div><button class="btn primary" data-toggle="addbox">+ Add idea</button></div>
    ${addBox(def, all0)}
    ${groups || '<div class="iempty">No ideas yet.<br>Press <b>+ Add idea</b>, or tell any chat: <i>add idea: …</i></div>'}
  </div>`;
}
// ---- Health tab: frozen or stuck work, leftovers and Mac pressure (bin/shipm-watch writes health.json) ----
const HACT = { interrupt: 'Interrupt', relaunch: 'Relaunch chat', fresh: 'Fresh chat', 'end-job': 'End job', 'end-proc': 'End it', 'quit-session': 'Quit session',
  'close-duplicate': 'Close duplicate', 'stop-colima': 'Stop Docker VM', 'pause-agents': 'Pause new agents', 'end-browser': 'End browser', 'end-testrun': 'Stop test run' };
const HSURE = new Set(['end-job', 'end-proc', 'quit-session', 'close-duplicate', 'stop-colima', 'relaunch', 'fresh', 'pause-agents', 'end-browser', 'end-testrun']);       // these ask "Sure?" in place
const hAgo = s => s < 90 ? 'just now' : s < 5400 ? Math.round(s / 60) + ' min' : s < 129600 ? Math.round(s / 3600) + ' h' : Math.round(s / 86400) + ' d';
function healthCount(h) { return healthBadge(h).n; }
function hTitle(t) {                                       // "Mac busy (mostly other apps)" -> main title + grey subtitle
  let m = /^(.*?)\s*\((.*)\)\s*$/.exec(t); if (m) return [m[1], m[2]];
  m = /^([^,]+),\s*(.*)$/.exec(t); return m ? [m[1], m[2]] : [t, ''];
}
const DESTRUCTIVE = new Set(['relaunch', 'fresh', 'end-job', 'end-proc', 'quit-session', 'close-duplicate', 'stop-colima', 'end-browser', 'end-testrun']);
function hMode(i) { return i.mode || (i.severity === 'info' ? 'wait' : 'fix'); }
const hFixable = i => ['fix', 'auto'].includes(hMode(i));
function hWaitActs(i, pm) {                                 // wait kinds: a link to the chat and, when the run is not guided, Back to guided (a terminal command the owner runs)
  const p = pm && pm[i.project]; if (!p || !H_WAIT.has(i.kind)) return '';
  const b = [];
  if (H_CHAT.has(i.kind)) b.push(`<button class="btn" data-act="open" data-pdir="${esc(p.dir)}" data-project="${esc(i.project)}" title="${esc(t('health.openChatTip'))}">${esc(t('health.openChat'))}</button>`);
  if (H_BACK.has(i.kind) && p.ap && p.ap !== 'guided') b.push(`<button class="btn" data-act="ap" data-to="guided" data-project="${esc(i.project)}" data-sure="${esc(t('health.backSure'))}" title="${esc(t('health.backTip'))}">${esc(t('health.back'))}</button>`);
  return b.length ? `<div class="hacts">${b.join('')}</div>` : '';
}
function healthRow(i, now, h, pm) {
  try { return healthRow0(i, now, h, pm); } catch (err) { return `<li class="hrow info hinfo" data-item="${esc(i && i.id)}"><span class="hdot"></span><div class="hmain"><div class="hline1"><b>${esc((i && (i.title || i.kind)) || t('health.unknownKind'))}</b></div><div class="hwhy">${esc((i && (i.why || i.info || i.next)) || t('health.reasonNeeds'))}</div></div></li>`; }
}
function healthRow0(i, now, h, pm) {
  const mode = hMode(i), chain = i.chain || (i.recommended ? [i.recommended] : []), imp = i.impact || {}, safe = i.safe || {};
  const [main, sub0] = hTitle(String(i.title || i.kind || '')), sub = [sub0, hAgo(Math.max(0, (now || Date.now() / 1000) - (Number(i.since) || 0)))].filter(Boolean).join(' · ');
  const top = (i.top || []).length ? ' ' + i.top.map(t => `${t.who}: ${(t.mb / 1024).toFixed(1)} GB`).join(' · ') : '';
  const ni = (h && h.noticeInfo) || {}, busy = !!(ni.busy && ni.id === i.id);
  const head = `<li class="hrow ${esc(i.severity)}${hFixable(i) ? '' : ' hinfo'}${H_RED.has(i.kind) ? ' hk-red' : H_AMBER.has(i.kind) ? ' hk-amber' : ''}" data-item="${esc(i.id)}"><span class="hdot"></span><div class="hmain"><div class="hline1"><b>${esc(main)}</b>${i.project ? `<span class="htag">${esc(i.project)}</span>` : ''}</div><div class="hsub">${esc(sub)}</div>`;
  if (!hFixable(i)) {                                      // info and wait rows: grey, the cause and the proof, no buttons
    const cause = ((i.why || '') + top).trim() || i.info || '';          // the item's own cause first (who uses the Mac, which containers); the static contract sentence only as a smaller line under it
    return `${head}<div class="hwhy clamp" title="Click to show all">${esc(cause)}</div>${i.info && i.info !== cause && i.info !== i.why ? `<div class="hproof">${esc(i.info)}</div>` : ''}${i.proof ? `<div class="hproof">${esc(i.proof)}</div>` : ''}${i.next ? `<div class="hproof hnext">${esc(i.next)}</div>` : ''}${hWaitActs(i, pm)}</div></li>`;
  }
  const canNow = chain.length && i.fixable_now !== false, destructive = typeof i.destructive_chain === 'boolean' ? i.destructive_chain : chain.some(o => DESTRUCTIVE.has(o));
  const steps = chain.map((o, n) => `${n + 1}. ${HACT[o] || o}${imp[o] ? ': ' + imp[o] : ''}`).join(' ');
  const safeTxt = safe[chain.find(o => DESTRUCTIVE.has(o))] || safe[chain[0]] || '';
  const impact = chain.length > 1 ? `Runs in order and stops at the first step that fixes it. ${steps}` : steps.replace(/^1\. /, '');
  const label = busy ? 'Fixing…' : 'Fix';
  const fix = chain.length ? `<button class="btn primary" data-health data-op="fix" data-id="${esc(i.id)}"${destructive ? ' data-confirm="1"' : ''} data-impact="${esc(impact)}" data-safe="${esc(safeTxt)}"${!canNow || busy ? ' disabled' : ''}${!canNow && i.why_not ? ` title="${esc(i.why_not)}"` : i.verify_text ? ` title="${esc(i.verify_text)}"` : ''}>${label}</button>` : '';
  const second = (i.actions || []).filter(a => a !== chain[0] && !chain.includes(a)).map(a => { const c = (i.can || {})[a], off = c && c[0] === false;
    return `<button class="btn" data-health data-op="${esc(a)}" data-id="${esc(i.id)}" data-project="${esc(i.project)}"${HSURE.has(a) ? ' data-confirm="1"' : ''} data-impact="${esc(imp[a] || '')}" data-safe="${esc(safe[a] || '')}"${off ? ` disabled title="${esc(c[1] || '')}"` : ''}>${esc(HACT[a] || a)}</button>`; }).join('');
  const plan = i.fix_label ? `<div class="hreco"><b>Fix:</b> ${esc(i.fix_label)}${/^Nothing is lost|^No container|^Nothing is deleted/.test(safeTxt) ? ' <span class="hsafe">Safe</span>' : ''}</div>` : '';
  const why = !canNow && i.why_not ? `<div class="hreco hnot">${esc(i.why_not)}</div>` : '';
  const prog = busy && h.notice ? `<div class="hbusy" role="status">${esc(h.notice)}</div>` : '';
  return `${head}<div class="hwhy clamp" title="Click to show all">${esc((i.why || '') + top)}</div>${plan}${why}${prog}${fix || second ? `<div class="hacts">${fix}${second}</div><div class="himpact" hidden></div>` : ''}</div></li>`;
}
function healthPane(h, pm) {
  if (!h) return '<div class="iempty">No scan yet.' + (MACH ? '<br>The Awake guard runs the health check every minute.' : '') + '</div>';
  const now = h.ts, needs = h.items.filter(hFixable), attn = h.items.filter(i => !hFixable(i) && H_WAIT.has(i.kind)), infos = h.items.filter(i => !hFixable(i) && !H_WAIT.has(i.kind) && hMode(i) === 'info'), waits = h.items.filter(i => !hFixable(i) && !H_WAIT.has(i.kind) && hMode(i) !== 'info');
  const bw = mb => 'bw' + Math.min(10, Math.max(1, Math.round(mb / 25)));        // bar width class, 25 MB per step
  const rows = Object.entries(h.chats || {}).filter(([, c]) => c.chats > 0 || c.size_mb > 0).sort((x, y) => (y[1].size_mb || 0) - (x[1].size_mb || 0)).map(([n, c]) => `<div class="srow"><div class="sl"><b>${esc(n)}</b><span class="isub">${c.size_mb ? Math.round(c.size_mb) + ' MB' : ''}</span></div>
    <div class="sbar"><i class="${bw(c.size_mb || 0)}${c.size_mb > 80 ? ' big' : ''}"></i></div><div class="isub">${c.chats ? c.chats + (c.chats > 1 ? ' chats open' : ' chat open') : 'no chat open'}${c.quiet_s != null ? ' · quiet ' + esc(hAgo(c.quiet_s)) : ''}</div></div>`).join('');
  const cl = h.cleaned || [], hk = h.hk_last ? new Date(h.hk_last * 1000).toTimeString().slice(0, 5) : '';
  const sw = `<button class="sw${h.auto ? ' on' : ''}" role="switch" aria-checked="${h.auto ? 'true' : 'false'}" aria-label="Automatic cleanup" data-health data-op="${h.auto ? 'auto-clean-off' : 'auto-clean-on'}" data-id="-"><i></i></button>`;
  const cleaned = `<div class="hsec hclean"><div class="hclh"><div><b>Automatic cleanup</b><div class="isub">${h.auto ? 'On' + (hk ? ' · last run ' + hk : '') + ' · ' + cl.length + ' cleaned today' : 'Off: nothing is cleaned until you turn it on'}</div></div>${sw}</div>
    <div class="hwhy">${MACH ? 'Runs with the Awake guard every minute. ' : ''}Only proven leftovers, old records and old outputs; never a live chat, agent or job.</div>
    ${cl.length ? `<details><summary>What was cleaned</summary>${cl.slice(-8).reverse().map(c => `<div class="crow"><b>${esc(c.what)}</b><span class="isub">${esc((c.cmd || '').slice(0, 44))}</span></div>`).join('')}</details>` : ''}</div>`;
  return `${h.notice ? `<div class="hnote"><span>${esc(h.notice)}</span>${h.noticeInfo && h.noticeInfo.busy ? '' : '<button class="btn" data-health data-op="dismiss-notice" data-id="-">OK</button>'}</div>` : ''}${h.ageS > 300 ? `<div class="inote">Last scan ${esc(hAgo(h.ageS))} ago${MACH ? ': the Awake guard may be off' : ''}.</div>` : ''}
    <div class="hsec"><div class="hsech">${needs.length ? 'Needs you' : 'All good'}</div>${needs.length ? `<ul class="hlist">${needs.map(i => healthRow(i, now, h, pm)).join('')}</ul>` : '<div class="isub">No frozen or stuck work, no leftovers.</div>'}</div>
    ${attn.length ? `<div class="hsec hattn"><div class="hsech">${esc(t('health.waitHead'))}</div><ul class="hlist">${attn.map(i => healthRow(i, now, h, pm)).join('')}</ul></div>` : ''}
    ${infos.length ? `<div class="hsec"><div class="hsech">For your information</div><ul class="hlist">${infos.map(i => healthRow(i, now, h, pm)).join('')}</ul></div>` : ''}
    ${waits.length ? `<div class="hsec"><div class="hsech">Waiting (normal)</div><ul class="hlist">${waits.map(i => healthRow(i, now, h, pm)).join('')}</ul></div>` : ''}
    ${cleaned}`;
}
const HCHIP = { frozen_chat: 'red', frozen_agent: 'red', job_frozen: 'red' };
function healthChips(p, skip) {                                // small chips on a project card; a click opens the Health tab
  return (p.health || []).filter(i => !['host_busy', 'hog', 'vm_idle'].includes(i.kind) && !(skip && skip.has(i.id)) && (!i.mode || ['fix', 'auto'].includes(i.mode))).map(i => `<button class="chip hc ${i.severity === 'red' ? 'hred' : i.severity === 'amber' ? 'hamb' : ''}" data-hopen="${esc(i.id)}" title="${esc(i.why)}">${esc(i.title)}</button>`).join('');
}
function ideasPane(data) {
  const ps = data.projects;
  const opts = `<option value="__all__">All projects (${ps.reduce((a, q) => a + q.ideas.open.length, 0)})</option>` + ps.map(p => `<option value="${esc(p.name)}">${esc(label(p))} (${p.ideas.open.length})</option>`).join('');
  const def = ps.find(q => q.active && !q.held) || ps.find(q => !q.held) || ps[0] || { name: '' };       // the add form of the All view starts on the project you are in
  return `<label class="pselbar">Project<select class="psel" data-psel aria-label="Project">${opts}</select></label>${ideaAll(ps, ps, def)}${ps.map(q => ideaList(q, ps.map(x => x.name), ps)).join('')}`;
}
const KINDS = ['web', 'ios', 'python', 'api', 'home', 'notes', 'other'];
function projectNotice(data) {                             // the result of the last New project / level switch, and the "Creating…" row
  const n = data.pnotice && (data.pnotice.text || data.pnotice), c = data.creating;
  return (c && c.name ? `<div class="pcreate" role="status">${svg('spin', 'spinning accent')}<span>Creating ${esc(c.name)}… (GitHub repo too, up to a minute)</span></div>` : '')
    + (n && typeof n === 'string' ? `<div class="hnote"><span>${esc(n)}</span><button class="btn" data-health data-op="dismiss-project-notice" data-id="-">OK</button></div>` : '');
}
function newBox(data) {                                    // in-place "New project" form (same structure as the Ideas add box); fields use data-nf so the idea draft is not disturbed
  const names = data.projects.map(x => x.name);
  return `<div class="addbox" data-newbox data-names="${esc(JSON.stringify(names))}"${data.creating ? ' data-busy="1"' : ''} data-msg="${esc(JSON.stringify({ hint: t('newp.nameHint', { name: '{name}' }), empty: t('newp.nameEmpty'), rule: t('newp.nameRule'), taken: t('newp.nameTaken'), typeNeed: t('newp.typeNeed'), typeBusy: t('newp.typeBusy') }))}" hidden>
    <label class="flabel">Name<input class="fin" type="text" data-nf="name" maxlength="60" autocomplete="off" spellcheck="false" placeholder="my-new-app"></label>
    <div class="nhint" data-nhint aria-live="polite">${esc(t('newp.nameEmpty'))}</div>
    <div class="nhint bad" data-nrule hidden></div>
    <label class="flabel">Type<select class="fsel" data-nf="kind"><option value="">${esc(t('newp.typePh'))}</option>${KINDS.map(k => `<option value="${k}">${k}</option>`).join('')}</select></label>
    <div class="nhint bad" data-nkind hidden>${esc(t('newp.typeNeed'))}</div>
    <label class="flabel">What is it for? (optional)<textarea class="ftext" data-nf="about" rows="2" maxlength="140" placeholder="One line, up to 140 characters."></textarea></label>
    <div class="nhint" data-nprivate>${esc(t('newp.private'))}</div>
    <div class="frow"><button class="btn primary" data-nform="create" disabled>Create</button><button class="btn quiet" data-nform="cancel">Cancel</button></div></div>`;
}
function banner(data) {
  const a = data.ask; if (!a || !a.projects || !a.projects.length) return '';
  const names = a.projects.map(x => `${esc(x.name === 'ideas' ? 'Inbox' : x.name)} (${x.count})`).join(', ');
  return `<div class="banner" role="status"><div><b>Ideas are waiting</b><div class="isub">${names}: no activity for a while. Look at them now?</div></div>
    <div class="bgrid"><button class="btn primary" data-idea data-op="review" data-project="${esc(a.projects[0].name)}">Review now</button><button class="btn" data-idea data-op="later">Later</button></div></div>`;
}

function guardRow(g) {
  if (!g) return '';
  const st = !g.on ? 'off' : !g.running ? 'not running' : g.hold ? 'keeping awake' + (g.lpm ? ' · low power' : '') : 'idle';
  const live = g.on && g.running && g.hold;
  return `<div class="grow" title="Keeps the Mac working (display may sleep, lid may be closed) while VS Code has work. Click the switch to turn the guard on or off."><span><i class="dot${live ? ' act' : ''}"></i>Awake guard · ${st}</span><button class="sw${g.on ? ' on' : ''}" role="switch" aria-checked="${g.on ? 'true' : 'false'}" aria-label="Awake guard" data-guard="1"><i></i></button></div>`;
}
function macRow(h) {                                       // one universal line under the token meters: how hard the Mac is working
  if (!h || !h.host) return '';
  const m = h.host, busy = !!m.busy;
  const tip = 'How hard ' + (MACH ? 'this Mac' : 'this computer') + ' is working right now (swap = memory pushed to disk, free = memory left, load = busy processes). When it is busy everything slows down and chats can look frozen, so heavy jobs should wait. Details: Health tab.';
  return `<div class="grow mac" title="${esc(tip)}"><span><i class="dot${busy || h.ageS > 300 ? ' warn' : ' act'}"></i>${MACH ? 'Mac' : 'This computer'} · ${h.ageS > 300 ? 'no scan ' + hAgo(h.ageS) : busy ? 'busy' : 'ok'}</span><span class="mvals"><span>Swap ${Math.round(m.swap_pct || 0)} %</span><span>Free ${Math.round(m.free_pct || 0)} %</span><span>Load ${(m.load || 0).toFixed(1)}</span></span></div>`
    + (h.auto === false ? `<div class="grow" title="Nothing is cleaned automatically while this is off: leftovers, stale records and old outputs pile up."><span><i class="dot warn"></i>Auto cleanup off</span><button class="btn" data-health data-op="auto-clean-on" data-id="-">Turn on</button></div>` : '')
    + (h.paused ? `<div class="grow"><span>New agents paused</span><button class="btn primary" data-health data-op="resume-agents" data-id="-">Resume</button></div>` : '');
}
function awayRow(g) {
  if (!g || !g.away) return '';
  return `<div class="grow"><button class="btn quiet" data-away="1" title="Choices Claude made on its own while you were away: open the list, then mark it as read.">Decisions while away: ${g.away}</button></div>`;
}
// ---- Reports tab (UX spec section 6). Data: data.reports = { items, status } from reports.js (the index, read-only); data.rview = the report open in the viewer. Everything is escaped; no link is ever clickable.
const SETUPJS = require('./setup');
const VCLS2 = { PASS: 'v-pass', FAIL: 'v-fail', BLOCKED: 'v-blk', 'NOT TESTED': 'v-nt' };
const rDate = ts => ts ? new Date(ts * 1000).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' }) : '';
const vchip = w => `<span class="vchip ${VCLS2[w] || 'v-nt'}" role="img" aria-label="${esc(t('reports.verdictAria', { word: w }))}">${esc((S.reports.verdictGloss || {})[w] || w)}</span>`;
const isAttn = it => it.verdict === 'FAIL' || it.verdict === 'BLOCKED';
// The tiny safe renderer: every character is escaped first, then only these shapes are added: headings, lists, code, bold, "Label: value" rows. A link is shown as its text and address, never as a link.
const inl = s => esc(s).replace(/`([^`]+)`/g, '<code>$1</code>').replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>').replace(/\[([^\]]*)\]\(([^)]*)\)/g, (m, a, b) => a + ' (' + b + ')');
function mdSafe(src) {                                      // -> { html, nv, meta }  nv = the "Not verified" text (null when the report has none), meta = the grey line of the first heading
  const lines = String(src == null ? '' : src).replace(/\r\n?/g, '\n').split('\n').slice(0, 600).map(l => l.length > 800 ? l.slice(0, 800) : l);
  const out = []; let list = null, code = null, nv = null, nvOpen = false, meta = '', first = true, last = '';
  const flush = () => { if (list) { out.push(`<${list.t}>${list.items.map(x => `<li dir="auto">${x}</li>`).join('')}</${list.t}>`); list = null; } };
  for (const raw of lines) {
    if (code !== null) { if (/^\s*```/.test(raw)) { out.push(`<pre dir="ltr"><code>${code.join('\n')}</code></pre>`); code = null; } else code.push(esc(raw)); continue; }
    if (/^\s*```/.test(raw)) { flush(); code = []; nvOpen = false; continue; }
    let m;
    if ((m = /^(#{1,6})\s+(.*)$/.exec(raw))) {
      flush(); nvOpen = false;
      const parts = m[2].split(/ {3,}/), head = parts[0].trim(), tail = parts.slice(1).join(' · ').trim();
      if (first && m[1].length === 1) { first = false; meta = tail; last = head; continue; }       // the report's own title line: the viewer shows it as its heading
      first = false; const lv = Math.min(5, Math.max(3, m[1].length + 1));
      if (/^not verified$/i.test(head)) { nv = ''; nvOpen = true; continue; }
      out.push(`<h${lv} class="rhd" dir="auto">${inl(head)}</h${lv}>`); continue;
    }
    first = false;
    if ((m = /^\s*([-*]|\d+[.)])\s+(.*)$/.exec(raw))) { nvOpen = false; const tag = /\d/.test(m[1]) ? 'ol' : 'ul'; if (!list || list.t !== tag) { flush(); list = { t: tag, items: [] }; } list.items.push(inl(m[2])); continue; }
    if ((m = /^([A-Z][A-Za-z ]{1,22}):\s*(.*)$/.exec(raw))) {
      flush();
      if (/^not verified$/i.test(m[1])) { nv = m[2]; nvOpen = true; continue; }
      nvOpen = false; out.push(`<div class="rkv"><b>${esc(m[1])}</b><span dir="auto">${inl(m[2])}</span></div>`); continue;
    }
    if (!raw.trim()) { flush(); nvOpen = false; continue; }
    if (nvOpen && /^\s+\S/.test(raw)) { nv = (nv ? nv + ' ' : '') + raw.trim(); continue; }
    if (/^\s{2,}\S/.test(raw) && out.length && !list) { out.push(`<div class="rcont" dir="auto">${inl(raw.trim())}</div>`); continue; }
    flush(); nvOpen = false; out.push(`<p dir="auto">${inl(raw.trim())}</p>`);
  }
  flush(); if (code !== null) out.push(`<pre dir="ltr"><code>${code.join('\n')}</code></pre>`);
  return { html: out.join(''), nv: nv === null ? null : nv.trim(), meta, head: last };
}
function notVerifiedBlock(nv) {
  const txt = nv === null ? t('reports.notVerifiedMissing') : (!nv || /^(none|n\/a|-|nothing)\.?$/i.test(nv)) ? t('reports.notVerifiedNone') : nv;
  return `<div class="rnv" role="note"><b>${esc(t('reports.notVerified'))}</b><span dir="auto">${esc(txt)}</span></div>`;
}
function reportViewer(v) {
  const back = `<button class="btn quiet rback" data-rv="back" aria-label="${esc(t('reports.backAria'))}">${esc(t('reports.back'))}</button>`;
  if (v.error) return `<div class="rview" data-rview="${esc(v.id)}">${back}<div class="rerr" role="alert">${esc(v.error)}</div></div>`;
  const md = mdSafe(v.text);
  const meta = [rDate(v.ts), v.project, md.meta].filter(Boolean).join(' · ');
  return `<div class="rview" data-rview="${esc(v.id)}">${back}
    <h2 class="rh">${crTitle(v.title || md.head || v.id)}</h2>
    <div class="rmeta">${vchip(v.verdict)}<span dir="auto">${esc(meta)}</span></div>
    <div class="rbody">${md.html}${notVerifiedBlock(md.nv)}</div>
    ${v.private ? `<div class="nhint">${esc(t('reports.private'))}</div>` : ''}
    <div class="frow"><button class="btn" data-rv="open" data-id="${esc(v.id)}">${esc(t('reports.openFile'))}</button><button class="btn" data-rv="copy" data-id="${esc(v.id)}">${esc(t('reports.copyPath'))}</button></div></div>`;
}
const noticeOnly = data => { const n = data.pnotice && (data.pnotice.text || data.pnotice); return n && typeof n === 'string' ? `<div class="hnote" role="status"><span>${esc(n)}</span><button class="btn" data-health data-op="dismiss-project-notice" data-id="-">OK</button></div>` : ''; };
function reportsPane(data) {
  if (data.rview) return noticeOnly(data) + reportViewer(data.rview);
  const R = data.reports;
  if (!R) return `<div class="rlist" aria-busy="true" aria-label="${esc(t('reports.loading'))}">${'<div class="rskel"></div>'.repeat(3)}</div>`;
  if (R.status === 'bad') return `${noticeOnly(data)}<div class="rerr" role="alert">${esc(t('reports.error'))} <button class="btn" data-rv="retry">${esc(t('reports.retry'))}</button></div>`;
  if (!R.items.length) return `${noticeOnly(data)}<div class="iempty">${esc(t('reports.empty'))}</div>`;
  const byP = new Map();
  R.items.forEach(it => { const k = it.project || ''; if (!byP.has(k)) byP.set(k, []); byP.get(k).push(it); });
  const groups = [...byP.entries()].map(([k, l]) => ({ k, l: l.slice().sort((a, b) => (isAttn(b) - isAttn(a)) || (b.ts - a.ts)) }))
    .sort((a, b) => (a.l.some(isAttn) ? 0 : 1) - (b.l.some(isAttn) ? 0 : 1) || (b.l[0].ts || 0) - (a.l[0].ts || 0));
  const projects = groups.filter(g => g.k).map(g => g.k).sort();
  const kinds = [...new Set(R.items.map(i => i.kind))].filter(k => S.reports.kinds[k]);
  const row = it => `<button class="rrow" data-rid="${esc(it.id)}" data-kind="${esc(it.kind)}" data-verdict="${esc(it.verdict)}" data-proj="${esc(it.project)}" aria-label="${esc(t('reports.openAria', { title: it.title || it.id }) + ', ' + it.verdict + ', ' + rDate(it.ts))}">`
    + `${vchip(it.verdict)}<span class="rt">${crTitle(it.title || it.id)}</span><span class="rd">${esc(rDate(it.ts))}</span>`
    + `<span class="rsub" dir="auto">${esc(it.sub)}</span><span class="ropen" aria-hidden="true">${esc(t('reports.open'))} ›</span></button>`;
  const chips = (key, label, vals, aria) => `<div class="pchips" role="group" aria-label="${esc(aria)}"><button class="pchip on" data-rf="${key}" data-val="" aria-pressed="true">${esc(label)}</button>${vals.map(([v, l]) => `<button class="pchip" data-rf="${key}" data-val="${esc(v)}" aria-pressed="false">${esc(l)}</button>`).join('')}</div>`;
  return `${noticeOnly(data)}<div class="rfilters"><label class="pselbar">${esc(t('reports.filterProject'))}<select class="psel" data-rproj aria-label="${esc(t('reports.filterProject'))}"><option value="">${esc(t('reports.allProjects'))}</option>${projects.map(p => `<option value="${esc(p)}">${esc(p)}</option>`).join('')}</select></label>
    ${chips('verdict', t('reports.allVerdicts'), [['FAIL', 'FAIL'], ['BLOCKED', 'BLOCKED'], ['PASS', 'PASS']], t('reports.verdictsAria'))}
    ${chips('kind', t('reports.allKinds'), kinds.map(k => [k, S.reports.kinds[k]]), t('reports.kindsAria'))}</div>
    <div class="rlist" data-rlist>${groups.map(g => `<section class="rgroup" data-group="${esc(g.k)}"><div class="igname"><span dir="auto">${esc(g.k || S.reports.kinds.digest)}</span><span class="isub">${g.l.length}</span></div>${g.l.map(row).join('')}</section>`).join('')}</div>
    <div class="iempty" data-rnone hidden>${esc(t('reports.none'))}</div>`;
}
const crTitle = ti => { const m = /^(CR-\d+)\s+([\s\S]*)$/.exec(String(ti || '')); return m ? `<span class="rid">${esc(m[1])}</span> <bdi dir="auto">${esc(m[2])}</bdi>` : `<bdi dir="auto">${esc(ti || '')}</bdi>`; };   // the id stays Latin, the title takes its own direction (an Arabic title reads right to left)
const attnReports = data => { const R = data.reports; if (!R || !R.items) return 0; const cut = Date.now() / 1000 - 7 * 86400; return R.items.filter(it => isAttn(it) && it.ts >= cut).length; };

// ---- Setup tab (UX spec section 7). Data: data.setup = { rows, ready, error } from setup.js (`shipm init --check --json`). The page types nothing and runs nothing: Fix / Skip post a message and the extension
// puts `shipm init --step <id>` / `--skip <id>` into a terminal, WITHOUT Enter. Nothing here is an input: no secret is ever asked for.
const MARK = { green: ['ok', '✓', 'ok'], red: ['red', '✕', 'red'], skipped: ['skip', '–', 'skip'], advisory: ['skip', 'i', 'info'], never: ['skip', 'i', 'info'] };
const redRequired = data => (data.setup && data.setup.rows ? data.setup.rows.filter(r => r.state === 'red' && r.need === 'required').length : 0);
// Remote Control (addendum 3 section C): the row's colour comes from `remote.state` of the panel data (a read-only look at the user-level setting), not from the init check alone.
//   on -> green; off -> grey 'Off by default' (the Skipped look); unknown -> the CLI's own row, unchanged. The panel never writes the settings file: Turn on / Undo only type a command.
function effRow(r, remote) {
  if (r.id !== 'remote-control' || !remote) return r;
  if (remote.state === 'on') return { ...r, state: 'green', detail: t('setup.remoteOn') };
  if (remote.state === 'off') return { ...r, state: 'skipped', detail: t('setup.remoteOff') };
  return r;
}
const MARK_A = { green: ['ok', '+', 'ok'], red: ['red', '!', 'red'], skipped: ['skip', '-', 'skip'], advisory: ['skip', 'i', 'info'], never: ['skip', 'i', 'info'] };   // ASCII marks of the cross-platform Setup layout (words carry the meaning too)
function setupRow(r, ascii) {
  const [cls, glyph, word] = (ascii ? MARK_A : MARK)[r.state] || MARK.advisory, A = r.id === 'describe-work' ? { fix: false, skip: false } : SETUPJS.rowActions(r), nm = SETUPJS.clean(r.title, 80);
  const reason = r.state === 'never' ? t('setup.never') : r.state === 'skipped' ? (SETUPJS.clean(r.detail, 300) || t('setup.marks.skip')) : SETUPJS.clean(r.detail, 300);
  const hint = r.connect ? SETUPJS.clean(r.connect.text, 300) : '', showHint = (r.state === 'red' || r.state === 'advisory') && hint;
  const btn = (op, label, aria, tip, extra = '') => `<button class="btn${extra}" data-setup="${op}" data-id="${esc(r.id)}" aria-label="${esc(t(aria, { name: nm }))}" title="${esc(tip)}">${esc(label)}</button>`;
  return `<li class="chk ${cls}" data-row="${esc(r.id)}" data-need="${esc(r.need)}" data-state="${esc(r.state)}">
    <span class="cmark" role="img" aria-label="${esc(t('setup.marks.' + word))}">${glyph}</span>
    <div class="cbody"><div class="cname"><b>${esc(nm)}</b><span class="cneed">${esc(t('setup.need.' + r.need))}</span></div>
      ${reason ? `<div class="creason" dir="auto">${esc(reason)}</div>` : ''}${showHint ? `<div class="chint" dir="auto">${esc(hint)}</div>` : ''}${r.id === 'remote-control' ? `<div class="cnote" dir="auto">${esc(t('setup.remoteNote'))}</div>` : ''}</div>
    ${r.id === 'remote-control' && r.state === 'green' ? `<div class="cacts">${btn('undo', t('setup.undo'), 'setup.undoAria', t('setup.undoTip'), ' quiet')}</div>` : ''}
    ${A.fix || A.skip ? `<div class="cacts">${A.fix ? btn('fix', A.again ? t('setup.turnOn') : t('setup.fix'), A.again ? 'setup.turnOnAria' : 'setup.fixAria', r.id === 'remote-control' ? t('setup.remoteTurnOnTip') : t('setup.fixTip', { id: r.id })) : ''}${A.skip ? btn('skip', t('setup.skip'), 'setup.skipAria', t('setup.skipTip', { id: r.id }), ' quiet') : ''}</div>` : ''}</li>`;
}
const TX = require('./tidyx');                                  // G2: the read-only Tidy up card at the bottom of the Health tab (tidyx.js)
const SX = require('./setupx')({ t, esc, setupRow, effRow });                // the cross-platform Setup layout (OS line, Quick setup, Needs you, More): shown only when the CLI sends the onboarding fields
const HX = require('./hostx'), HXD = { t, esc };                         // Windows / WSL notice (E10): the install hint is the CLI's own os.line, the fallback sentence lives in hostx.js only
function setupPane(data) {
  const s = data.setup, nt = noticeOnly(data), hn = HX.notice(data.host, s && s.os, HXD, 'setup');
  if (data.host && data.host.kind === 'windows') return `${nt}${hn}<div class="shead"><b>${esc(t('setup.title'))}</b></div>`;      // native Windows: nothing to re-check here (the notice says why)
  const recheck = (primary, label) => `<button class="btn${primary ? ' primary' : ''}" data-setup="recheck" data-busy="${esc(t('setup.rechecking'))}">${esc(label || t('setup.recheck'))}</button>`;
  if (!s) return `${nt}${hn}<div class="shead"><b>${esc(t('setup.title'))}</b>${recheck(false)}</div><div class="rlist" aria-busy="true" aria-label="${esc(t('setup.checking'))}">${'<div class="rskel"></div>'.repeat(3)}</div>`;
  if (s.error || !s.rows || !s.rows.length) return `${nt}${hn}<div class="shead"><b>${esc(t('setup.title'))}</b>${recheck(true)}</div><ul class="chks"><li class="chk red" data-row="-" data-state="error"><span class="cmark" role="img" aria-label="${esc(t('setup.marks.red'))}">✕</span><div class="cbody"><div class="cname"><b>${esc(t('setup.error'))}</b></div><div class="creason">${esc(t('setup.errorSub'))}</div></div></li></ul>`;
  const qx = SX.pane(s, data);
  if (qx) return `${nt}${hn}<div class="shead" data-at="${esc(s.at || '')}" data-view="${qx.ok ? 'calm' : 'fix'}"><b${qx.ok ? ' class="scalm"' : ''}>${qx.icon}${esc(qx.header)}</b><button type="button" class="btn" data-setup="recheck" data-busy="${esc(t('setup.rechecking'))}">${esc(t('quick.checkAgain'))}</button></div>\n    <div class="nhint" data-ready>${esc(qx.sub)}</div>\n    ${qx.body}`;
  const rows = s.rows.map(r => effRow(r, data.remote));
  const counted = rows.filter(r => r.id !== 'describe-work'), n = counted.filter(r => r.state === 'green').length, red = redRequired(data),   // F6's optional row is never counted in "N of M ready" and never red
    browser = s.rows.some(r => r.state === 'red' && r.connect && r.connect.kind === 'browser');
  return `${nt}${hn}<div class="shead" data-at="${esc(s.at || '')}"><b>${esc(t('setup.header', { n, m: counted.length }))}</b>${recheck(red > 0)}</div>
    <div class="nhint" data-ready>${esc(red ? t('setup.notReady') : t('setup.ready'))}${browser ? ' ' + esc(t('setup.secretNote')) : ''}</div>
    <ul class="chks">${rows.map(r => setupRow(r)).join('')}</ul>`;
}

// ---- Health: the change-request and autopilot kinds (section 8). The watcher produces them (bin/shipm-watch KINDS); the panel only renders them. An unknown kind falls back to the generic row.
const H_RED = new Set(['verify_failed_twice', 'autopilot_paused', 'autopilot_stopped']);                     // badge red: the run is stopped and needs your choice
const H_AMBER = new Set(['budget_reached', 'autopilot_ended_time', 'merge_waiting', 'cr_orphan']);          // badge amber: it ended or waits, nothing is broken
const H_WAIT = new Set([...H_RED, ...H_AMBER]);
const H_CHAT = new Set(['verify_failed_twice', 'autopilot_stopped', 'autopilot_paused', 'cr_orphan', 'merge_waiting']);       // an "Open chat" link
const H_BACK = new Set(['autopilot_paused', 'autopilot_stopped', 'budget_reached', 'autopilot_ended_time']);                // a "Back to guided" button
function healthBadge(h) {                                      // { n, red } for the Health tab: the watcher's red+amber counts plus the wait kinds above
  if (!h) return { n: 0, red: false };
  const items = Array.isArray(h.items) ? h.items : [], extra = items.filter(i => i && H_WAIT.has(i.kind) && i.severity !== 'red' && i.severity !== 'amber');
  const c = h.counts || {};
  return { n: (c.red || 0) + (c.amber || 0) + extra.length, red: !!(c.red || 0) || extra.some(i => H_RED.has(i.kind)) };
}
let MACH = true;                                          // false on Linux / WSL / Windows (the CLI-independent host says so): macOS-only wording and the Awake guard row are left out there
function render(data, { nonce = '', csp = '' } = {}) {
  X.setCtx(data); MACH = !(data.host && data.host.platform && data.host.platform !== 'darwin');
  const inbox = p => !!(p.ask && p.ask.inbox === true), askP = data.projects.find(inbox) || null;
  const ps0 = data.projects.filter(p => !p.special && !inbox(p)), sp = data.projects.filter(p => p.special);
  const asidePs = ps0.filter(isAsideRow), ps = ps0.filter(p => !isAsideRow(p));
  const pl = data.plan || {}; const ms = pl.meters || [];
  const openTotal = data.projects.reduce((a, q) => a + ((q.ideas && q.ideas.open.length) || 0), 0);
  const firstWithIdeas = (data.projects.find(q => q.ideas && q.ideas.open.length) || data.projects.find(q => q.active) || data.projects[0] || {}).name || '';
  const allDay = data.projects.reduce((a, p) => a + p.tokens.claudeDay, 0);
  const waitN = nowModel(ps).w.length, wm = (pl.meters || []).find(m => m.id === 'week'), weekPct = wm && wm.pct != null ? wm.pct : null;
  const pm = Object.fromEntries(data.projects.map(p => [p.name, { dir: p.dir, ap: p.playbook ? p.playbook.autopilot : '' }]));
  const hb = healthBadge(data.health), rn = attnReports(data), sr = redRequired(data);
  const TABS = [['projects', t('tabs.projects'), waitN, 'hamb', t('nowTabBadge', { n: waitN })], ['reports', t('tabs.reports'), rn, 'hamb', t('reports.badgeAria', { n: rn })], ['ideas', t('tabs.ideas'), openTotal, '', ''],
    ['health', t('tabs.health'), hb.n, hb.red ? 'hred' : 'hamb', t('health.badgeAria', { n: hb.n })], ['setup', t('tabs.setup'), sr, 'hred', (sr === 1 ? t('setup.badgeAria1') : t('setup.badgeAria', { n: sr }))]];
  const tabBar = `<div class="tabs" role="tablist" aria-label="${esc(t('tabs.aria'))}">${TABS.map(([id, name, n, cls, aria], k) => `<button class="tab" id="tab-${id}" data-tab="${id}" role="tab" aria-controls="pane-${id}" aria-selected="${k === 0 ? 'true' : 'false'}" tabindex="${k === 0 ? 0 : -1}"${n && aria ? ` aria-label="${esc(name + ', ' + aria)}"` : ''}>${esc(name)}${n ? ` <i${cls ? ` class="hbadge ${cls}"` : ''}>${esc(n)}</i>` : ''}</button>`).join('')}</div>`;
  return `<!doctype html><html><head><meta charset="utf-8">${csp}
<style${nonce ? ` nonce="${nonce}"` : ''}>
:root{--fg:var(--vscode-foreground,#1f1f1f);--mut:var(--vscode-descriptionForeground,#6b6b6b);--bd:var(--vscode-panel-border,rgba(0,0,0,.12));
--card:var(--vscode-editorWidget-background,#fff);--acc:var(--vscode-textLink-foreground,#185FA5);--warn:var(--vscode-editorWarning-foreground,#B97A00);
--lv0:var(--vscode-charts-green,#2E7D32);--lv1:var(--vscode-editorWarning-foreground,#B97A00);--lv2:var(--vscode-charts-orange,#D2691E);--lv3:var(--vscode-errorForeground,#C62828);
--warnbg:color-mix(in srgb,var(--warn) 12%,transparent);--ok:var(--vscode-testing-iconPassed,#3B6D11);--danger:var(--vscode-errorForeground,#A32D2D);
--accbg:color-mix(in srgb,var(--acc) 12%,transparent);--warnt:color-mix(in srgb,var(--warn) 40%,var(--fg));--okt:color-mix(in srgb,var(--ok) 45%,var(--fg));--acct:color-mix(in srgb,var(--acc) 65%,var(--fg));--mutt:color-mix(in srgb,var(--mut) 50%,var(--fg))}
*{box-sizing:border-box}body{margin:0;padding:8px 10px 16px;overflow-x:hidden;color:var(--fg);font:13px/1.4 var(--vscode-font-family,-apple-system,sans-serif);background:transparent}
.ic{width:16px;height:16px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round;flex:none}
.spinning{animation:sp 1.1s linear infinite}@keyframes sp{to{transform:rotate(360deg)}}@media (prefers-reduced-motion:reduce){.spinning{animation:none}}
.plan,.card{background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:10px 12px;margin-bottom:10px}
.rs{font-size:11px;color:var(--mut);margin:0 0 8px}.gap{height:8px}.mrow span:first-child{white-space:nowrap}.plan{padding:6px 10px 3px}.plan .mrow{font-size:11.5px;line-height:1.25}.mrow{display:flex;justify-content:space-between;gap:8px;font-size:12px;color:var(--mut)}.mrow span:last-child{text-align:right}.bar{height:4px;border-radius:2px;background:var(--bd);margin:3px 0 7px;overflow:hidden}
.bar i{display:block;height:4px;width:0;background:var(--acc)}.bar i.lv0{background:var(--lv0)}.bar i.lv1{background:var(--lv1)}.bar i.lv2{background:var(--lv2)}.bar i.lv3{background:var(--lv3)}.t0{color:var(--mut)}.t1{color:var(--lv1)}.t2{color:var(--lv2)}.t3{color:var(--lv3);font-weight:600}${Array.from({ length: 101 }, (_, i) => `.bar i.w${i}{width:${i}%}`).join('')}.bar i.warn{background:var(--warn)}.bar i.danger{background:var(--danger)}
.warn{color:var(--warn)}.danger{color:var(--danger)}.ok{color:var(--ok)}.accent{color:var(--acc)}.muted{color:var(--mut)}
.note{font-size:11px;color:var(--mut);margin-top:-2px}
.card{cursor:pointer}.card:hover,.card:focus{border-color:var(--acc);outline:none}
.card.active{border-color:var(--acc);box-shadow:inset 3px 0 0 var(--acc)}.card.active:not(.st-warn){background:var(--accbg)}.small.active{color:var(--acc);font-weight:600}.card.st-warn{background:var(--warnbg);border-color:color-mix(in srgb,var(--warn) 45%,transparent)}
.top{display:flex;align-items:center;gap:8px;min-width:0}.name{font-weight:600;font-size:13.5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tag{margin-left:auto;font-size:11px;color:var(--mut)}.line{font-size:12px;color:var(--mut);margin-top:3px;overflow:hidden;text-overflow:ellipsis;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}
.foot{display:flex;justify-content:space-between;flex-wrap:wrap;gap:2px 8px;font-size:11px;color:var(--mut);margin-top:7px}
.card.st-warn .sub,.card.st-warn .name{color:var(--warnt)}
.chips{display:flex;flex-wrap:wrap;gap:5px;margin-top:7px}.chip{max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;display:inline-flex;align-items:center;gap:4px;font-size:11px;padding:1px 7px;border-radius:6px;border:1px solid var(--bd);color:var(--mut)}
button.chip{background:transparent;font:inherit;font-size:11px;cursor:pointer}.chip.ci{border-color:var(--mut)}.chip.ci.fail{border-color:#d1242f;color:#d1242f;background:color-mix(in srgb,#d1242f 14%,transparent)}
.chip.ci:hover{border-color:var(--acc)}.chip.ci:focus-visible{outline:2px solid var(--acc);outline-offset:1px}
.chip .ic{width:11px;height:11px}.chip.open{border-color:var(--acc);color:var(--acc)}
.btns{display:flex;gap:6px;margin-top:8px}button{font:inherit;font-size:12px;height:24px;padding:0 10px;border-radius:5px;border:1px solid var(--bd);background:transparent;color:var(--fg);cursor:pointer}
button:hover{border-color:var(--acc)}
.small{display:flex;align-items:center;gap:7px;font-size:12px;color:var(--mut);padding:5px 2px;cursor:pointer}.small:hover{color:var(--fg)}
.chip.stall{border-color:#d1242f;color:#d1242f}.grow{display:flex;justify-content:space-between;align-items:center;border-top:1px solid var(--bd);margin-top:4px;padding:5px 0 4px;font-size:11.5px;color:var(--mut)}.dot{display:inline-block;width:6px;height:6px;border-radius:50%;background:var(--mut);margin-right:7px;vertical-align:1px}.dot.act{background:#3fb950}button.sw{position:relative;width:26px;height:14px;padding:0;border:0;border-radius:7px;background:var(--bd)}.sw i{position:absolute;top:2px;left:2px;width:10px;height:10px;border-radius:50%;background:var(--bg,#fff);transition:left .15s}.sw.on{background:var(--acc)}.sw.on i{left:14px}.empty{color:var(--mut);font-size:12px;padding:8px 2px}

[hidden]{display:none!important}
.btn{font:inherit;font-size:11.5px;height:24px;padding:0 10px;border-radius:6px;border:1px solid var(--bd);background:color-mix(in srgb,var(--fg) 7%,transparent);color:var(--fg);cursor:pointer;white-space:nowrap}
.btn:hover:not(:disabled){border-color:var(--acc);background:var(--accbg)}.btn:focus-visible,.cb:focus-visible,.tab:focus-visible,.pchip:focus-visible{outline:2px solid var(--acc);outline-offset:1px}
.btn.primary{background:var(--acc);border-color:var(--acc);color:var(--vscode-button-foreground,#fff);font-weight:600}.btn.primary:hover:not(:disabled){filter:brightness(1.1);background:var(--acc)}
.btn.quiet{background:transparent;color:var(--mut)}.btn:disabled,.cb:disabled{opacity:.45;cursor:not-allowed}
.tabs{display:flex;gap:3px;padding:3px;margin:0 0 10px;border-radius:9px;background:color-mix(in srgb,var(--fg) 8%,transparent)}
.tab{flex:1;height:26px;border:0;border-radius:6px;background:transparent;color:var(--mut);font-weight:500}.tab:hover{color:var(--fg);border:0}.tab.on{background:var(--card);color:var(--fg);box-shadow:0 1px 2px rgba(0,0,0,.18)}
.tab i,.pchip i{font-style:normal;font-size:10.5px;margin-left:5px;padding:0 6px;border-radius:999px;background:color-mix(in srgb,var(--fg) 12%,transparent)}
.pchips{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 10px}.pchip{height:26px;padding:0 10px;border-radius:999px;color:var(--mut);background:var(--card);border:1px solid var(--bd)}
.pchip.on{color:var(--acc);border-color:var(--acc);background:var(--accbg);font-weight:600}.pchip:hover{border-color:var(--acc)}
.ilist{background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:10px 12px}
.ititle{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:6px}.iname{font-weight:600;font-size:13.5px}.isub{font-size:11px;color:var(--mut)}
.ideas{list-style:none;margin:0;padding:0}.idea{display:flex;gap:10px;padding:10px 0;border-top:1px solid var(--bd)}.idea:first-child{border-top:0}
.cb{width:18px;height:18px;padding:0;margin-top:1px;border-radius:50%;border:1.6px solid var(--mut);background:transparent;flex:none}.cb:hover:not(:disabled){border-color:var(--ok);background:color-mix(in srgb,var(--ok) 18%,transparent)}
.ibody{flex:1;min-width:0}.itext{line-height:1.35;overflow-wrap:anywhere}.imeta{display:flex;flex-wrap:wrap;align-items:center;gap:5px 7px;font-size:11px;color:var(--mut);margin-top:3px}
.itag{padding:0 6px;border-radius:4px;background:color-mix(in srgb,var(--fg) 9%,transparent)}.iacts{display:flex;flex-wrap:wrap;gap:5px;margin-top:7px}.iacts .btn{padding:0 8px}.iacts .btn.quiet{margin-left:auto}
.pill{padding:1px 8px;border-radius:999px;font-size:10.5px;font-weight:600}.pill.green{background:color-mix(in srgb,#2e9d4f 20%,transparent);color:var(--ok)}.pill.amber{background:color-mix(in srgb,var(--warn) 20%,transparent);color:var(--warn)}
.pill.blue{background:var(--accbg);color:var(--acc)}.pill.purple{background:color-mix(in srgb,#8957e5 20%,transparent);color:#8957e5}.pill.grey{background:color-mix(in srgb,var(--fg) 10%,transparent);color:var(--mut)}
.iempty{padding:16px 6px;text-align:center;color:var(--mutt);font-size:12px;line-height:1.7}.inote{font-size:11.5px;color:var(--warn);margin:2px 0 6px}
.idone{margin-top:8px;padding-top:8px;border-top:1px solid var(--bd);font-size:12px;color:var(--mut)}.idone summary{cursor:pointer}.ifoot{margin-top:10px;display:flex;justify-content:flex-end}
.banner{display:flex;flex-direction:column;gap:8px;margin:0 0 10px;padding:10px 12px;border-radius:10px;background:var(--warnbg);border:1px solid color-mix(in srgb,var(--warn) 45%,transparent)}.banner .bgrid{display:flex;gap:6px}

.ptools{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 10px}.pselbar{display:flex;flex-direction:column;gap:4px;margin:0 0 10px;font-size:11px;color:var(--mut)}
.psel,.fsel,.fin,.ftext,.pickrow select{width:100%;font:inherit;font-size:12.5px;color:var(--fg);background:var(--vscode-input-background,var(--card));border:1px solid var(--vscode-input-border,var(--bd));border-radius:6px;padding:0 8px}
.psel,.fsel,.fin,.pickrow select{height:28px}.ftext{padding:6px 8px;resize:vertical;min-height:60px;line-height:1.35}
.psel:focus,.fsel:focus,.fin:focus,.ftext:focus,.pickrow select:focus{outline:2px solid var(--acc);outline-offset:0;border-color:var(--acc)}
.addbox{display:flex;flex-direction:column;gap:8px;margin:2px 0 10px;padding:10px;border-radius:8px;border:1px solid var(--bd);background:color-mix(in srgb,var(--fg) 4%,transparent)}
.flabel{display:flex;flex-direction:column;gap:4px;font-size:11px;color:var(--mut)}.frow{display:flex;flex-wrap:wrap;gap:6px}
.pickrow{display:flex;flex-wrap:wrap;align-items:center;gap:6px;margin-top:7px;padding:7px;border-radius:7px;background:color-mix(in srgb,var(--fg) 5%,transparent)}.pickrow select{flex:1;min-width:120px;width:auto}
.btn.danger{background:var(--danger);border-color:var(--danger);color:#fff}.ifoot .btn{max-width:100%;overflow:hidden;text-overflow:ellipsis}

/* ---- layout system: buttons sit in grids with equal columns, every button is 26 px, every chip 22 px ---- */
.btn{height:26px;display:inline-flex;align-items:center;justify-content:center;text-align:center;overflow:hidden;text-overflow:ellipsis}
.ptools,.bgrid,.frow,.iacts,.btns{display:grid;gap:6px;margin-left:0}.ptools,.bgrid{grid-template-columns:1fr 1fr}.iacts{grid-template-columns:repeat(3,minmax(0,1fr))}.frow{grid-template-columns:1fr 1fr}.frow .wide{grid-column:1/-1}.btns{grid-template-columns:1fr}
.ptools .btn,.bgrid .btn,.frow .btn,.iacts .btn,.btns .btn{width:100%;min-width:0;padding:0 6px}.iacts .btn.primary{grid-column:1/-1}.iacts .btn.quiet{margin-left:0}
.chips{display:flex;flex-wrap:wrap;gap:5px;align-items:center}.chip{height:22px;display:inline-block;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;vertical-align:top;padding:0 8px;border-radius:11px;font-size:11px;line-height:22px}.chip .ic{vertical-align:-2px;margin-right:4px}
button.chip{font:inherit;font-size:11px;height:22px;padding:0 8px;border-radius:11px}
.pickrow{display:grid;grid-template-columns:1fr 1fr;gap:6px}.pickrow select{grid-column:1/-1;width:100%;min-width:0}.pickrow .btn{width:100%}
.itl{display:flex;flex-direction:column;gap:1px;min-width:0}.ititle{align-items:flex-start}.ititle .btn{flex:none;padding:0 10px}
.ifoot{justify-content:flex-end}
.igroup{margin:0 0 6px}.igname{display:flex;justify-content:space-between;align-items:baseline;gap:8px;margin:8px 0 2px;padding:5px 8px;border-radius:6px;background:color-mix(in srgb,var(--fg) 7%,transparent);font-weight:600;font-size:12px}.igname .isub{font-weight:400}
.chip{border:0;background:color-mix(in srgb,var(--fg) 9%,transparent);color:var(--mutt)}.chip.open{background:var(--accbg);color:var(--acct)}.chip.stall{background:color-mix(in srgb,var(--danger) 14%,transparent);color:var(--danger)}
button.chip.ci{border:1px solid var(--bd);background:transparent;color:var(--mutt);cursor:pointer}button.chip.relaunch{border:0;font:inherit;font-size:11px;cursor:pointer}button.chip.relaunch:hover{background:color-mix(in srgb,var(--fg) 16%,transparent);color:var(--fg)}button.chip.ci.fail{border-color:var(--danger);color:var(--danger);background:color-mix(in srgb,var(--danger) 10%,transparent)}  /* a border = you can click it */

/* ---- frozen header: the token card and the tabs stay; everything under them scrolls ---- */
html,body{height:100%}body{display:flex;flex-direction:column;overflow:hidden;padding:8px 0 0}
.frozen{flex:none;padding:0 10px;background:var(--vscode-sideBar-background,var(--vscode-editor-background,transparent))}.frozen .plan{margin-bottom:8px}.frozen .tabs{margin-bottom:6px}
.scroll{flex:1;min-height:0;overflow-y:auto;overflow-x:hidden;padding:4px 10px 16px;scrollbar-gutter:stable}

/* ---- Health tab ---- */
.hsec{background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:8px 12px;margin:0 0 10px}.hsech{font-weight:600;font-size:12px;margin:0 0 6px}
.hlist{list-style:none;margin:0;padding:0}.hrow{padding:8px 0;border-top:1px solid var(--bd)}.hrow:first-child{border-top:0}.hhead{display:flex;align-items:center;gap:7px;flex-wrap:wrap}.hdot{width:8px;height:8px;border-radius:50%;background:var(--mut);flex:none}
.hrow.red .hdot{background:var(--danger)}.hrow.amber .hdot{background:var(--warn)}.hrow.info .hdot{background:var(--mut)}.htag{margin-left:auto;font-size:11px;color:var(--mut);max-width:50%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.hwhy{font-size:11.5px;color:var(--mut);margin:3px 0 0 15px}.hacts{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin:7px 0 0}.hacts .btn{width:100%;min-width:0;padding:0 6px}
.himpact{font-size:11.5px;margin:6px 0 0 15px;padding:6px 8px;border-radius:7px;background:color-mix(in srgb,var(--warn) 14%,transparent)}.himpact[hidden]{display:none}.hmac{display:flex;flex-wrap:wrap;gap:4px 12px;align-items:center;font-size:11.5px;color:var(--mut);margin:0 0 6px}.hline{display:flex;justify-content:space-between;gap:8px;font-size:12px;padding:2px 0}.hline.muted{color:var(--mut);font-size:11.5px}
.hbadge{color:#fff!important}.hbadge.hred{background:var(--danger)!important}.hbadge.hamb{background:var(--warn)!important}
button.chip.hc{border:0;font:inherit;font-size:11px;cursor:pointer}button.chip.hc.hred{background:color-mix(in srgb,var(--danger) 16%,transparent);color:var(--danger)}button.chip.hc.hamb{background:color-mix(in srgb,var(--warn) 18%,transparent);color:var(--warnt)}button.chip.hc:hover{filter:brightness(.92)}

.hsec{padding:7px 10px;margin:0 0 8px}.hsech{margin:0 0 4px}.hrow{display:flex;gap:8px;padding:7px 0}.hmain{min-width:0;flex:1}.hdot{margin-top:5px}
.hline1{display:flex;align-items:baseline;gap:6px}.hline1 b{font-size:12.5px}.hline1 .htag{margin-left:auto;font-size:10.5px;padding:0 6px;border-radius:4px;background:color-mix(in srgb,var(--fg) 9%,transparent)}
.hsub{font-size:11px;color:var(--mut);margin:1px 0 0}.hwhy{margin:3px 0 0;font-size:11px;color:var(--mut)}.hwhy.clamp{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;cursor:pointer}.hwhy.clamp.open{display:block}
.hacts{display:flex;gap:5px;margin:6px 0 0}.hacts .btn{flex:1 1 0;min-width:0;height:22px;padding:0 6px;font-size:11px;overflow:hidden;text-overflow:ellipsis}.hacts .btn:only-child{flex:0 0 calc(50% - 3px)}
.himpact{margin:5px 0 0}
.hnote{display:flex;align-items:center;gap:8px;justify-content:space-between;margin:0 0 8px;padding:7px 10px;border-radius:8px;background:color-mix(in srgb,var(--ok,#2e7d32) 14%,transparent);font-size:11.5px}.hnote .btn{height:22px;flex:none}
.hproof{font-size:11px;color:var(--mut);margin:2px 0 0;overflow-wrap:anywhere}.hinfo .hwhy{overflow-wrap:anywhere}.hinfo .hwhy.clamp{-webkit-line-clamp:3}.hinfo .hline1 b{color:var(--mutt);font-weight:600}.hnot{color:var(--warnt)}.hbusy{font-size:11px;margin:5px 0 0;padding:4px 8px;border-radius:6px;background:var(--accbg)}button.chip.stall{border:0;font:inherit;font-size:11px;cursor:pointer}
.hreco{font-size:11px;margin:5px 0 0}.hreco b{font-weight:600}.hacts .btn.primary{flex-grow:1.4}
.srow{padding:4px 0}.sl{display:flex;justify-content:space-between;font-size:12px}.sbar{height:4px;border-radius:2px;background:color-mix(in srgb,var(--fg) 9%,transparent);margin:3px 0 2px;overflow:hidden}.sbar i{display:block;height:100%;background:var(--mut);border-radius:2px}.sbar i.big{background:var(--warn)}
.bw1{width:10%}.bw2{width:20%}.bw3{width:30%}.bw4{width:40%}.bw5{width:50%}.bw6{width:60%}.bw7{width:70%}.bw8{width:80%}.bw9{width:90%}.bw10{width:100%}
.hclean summary{cursor:pointer;font-weight:600;font-size:12px;list-style:none}.hclean summary i{font-style:normal;font-weight:400;font-size:11px;padding:0 6px;border-radius:8px;background:color-mix(in srgb,var(--fg) 10%,transparent);margin-left:4px}.hclean .crow{display:flex;justify-content:space-between;gap:8px;font-size:11.5px;padding:3px 0}
.hclean0{display:flex;justify-content:space-between;font-size:12px;font-weight:600}.hclean0 .isub{font-weight:400}
.grow.mac .mvals{display:flex;gap:9px;font-size:11px;color:var(--mut);white-space:nowrap}.grow .dot.warn{background:var(--warn)}.grow .btn.primary{height:22px;padding:0 10px}
.hsafe{font-weight:600;font-size:10.5px;padding:0 6px;border-radius:4px;background:color-mix(in srgb,#2e7d32 20%,transparent);color:#2e7d32}.himpact b{font-weight:700}
.hclh{display:flex;align-items:center;justify-content:space-between;gap:8px}.hclean details summary{cursor:pointer;font-size:11.5px;margin:6px 0 2px;color:var(--mut)}
/* ---- card v2: subtitle, Team-flow strip, gate chips, level pill, New project box ---- */
.sub{font-size:12px;color:var(--mut);margin-top:3px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.sub.red{color:var(--danger)}.sub.warn{color:var(--warnt)}
.tflow{list-style:none;margin:6px 0 0;padding:0;display:flex;flex-wrap:wrap;gap:2px 5px;font-size:10.5px;line-height:16px;color:var(--mut)}.ts{display:inline-flex;align-items:center;gap:3px;white-space:nowrap}
.td{width:6px;height:6px;border-radius:50%;box-sizing:border-box;border:1.5px solid var(--mut);flex:none}.ts.done .td{background:var(--ok);border-color:var(--ok)}.ts.cur{color:var(--fg);font-weight:600}.ts.cur .td{background:var(--acc);border-color:var(--acc)}
.tmeta{font-size:11px;color:var(--mut);margin-top:3px;overflow-wrap:anywhere}.warnt{color:var(--warnt)}
.chip.wn{background:color-mix(in srgb,var(--warn) 16%,transparent);color:var(--warnt)}button.chip.wn{border:0;font:inherit;font-size:11px;cursor:pointer}button.chip.wn:hover{background:color-mix(in srgb,var(--warn) 26%,transparent)}
.chip.ctx.strong{font-weight:600;box-shadow:inset 0 0 0 1px var(--warn)}
.chip.lvl{flex:none;font-weight:600;font-size:10.5px}button.chip.lvl{border:0;font:inherit;font-size:10.5px;font-weight:600;cursor:pointer}button.chip.lvl:hover:not(.danger){filter:brightness(.94)}
.chip.lvs-strict{background:color-mix(in srgb,var(--ok) 16%,transparent);color:var(--okt)}.chip.lvs-warn{background:color-mix(in srgb,var(--warn) 16%,transparent);color:var(--warnt)}
.chip.lvs-off{background:transparent;color:var(--mutt);box-shadow:inset 0 0 0 1px var(--mut)}.chip.lvl.danger{background:var(--danger);color:#fff}
button:focus-visible{outline:2px solid var(--acc);outline-offset:1px}
.nhint{font-size:11px;color:var(--mut)}.nhint.bad{color:var(--warnt)}.pcreate{display:flex;align-items:center;gap:8px;margin:0 0 8px;padding:6px 10px;border-radius:8px;background:var(--accbg);font-size:11.5px}
/* ---- panel v3: card hero (status line, stage strip, CR chips, verdict line, primary + ⋯ menu), Now / Next / Waiting block ---- */
:root{--dangert:color-mix(in srgb,var(--danger) 45%,var(--fg))}
/* VS Code puts vscode-light / vscode-dark / vscode-high-contrast on <body>: the text tokens get the direction that reaches 4.5:1 on the card in each family (checked by tests/panel_v3_ui_test.js on the real default theme values) */
body.vscode-light{--purplet:color-mix(in srgb,#8957e5 70%,#000);--warnt:color-mix(in srgb,var(--warn) 55%,#000);--okt:color-mix(in srgb,var(--ok) 45%,#000);--dangert:color-mix(in srgb,var(--danger) 65%,#000);--acct:color-mix(in srgb,var(--acc) 85%,#000);--mutt:color-mix(in srgb,var(--mut) 70%,#000)}
body.vscode-dark,body.vscode-high-contrast:not(.vscode-high-contrast-light){--purplet:color-mix(in srgb,#8957e5 55%,#fff);--acct:color-mix(in srgb,var(--acc) 45%,#fff);--warnt:color-mix(in srgb,var(--warn) 50%,#fff);--okt:color-mix(in srgb,var(--ok) 60%,#fff);--dangert:color-mix(in srgb,var(--danger) 55%,#fff)}
.mrow{flex-wrap:wrap}.btn.primary{color:var(--card)}.btn.quiet{color:var(--mutt)}.tflow{color:var(--mutt)}.card .ic.ok{color:var(--okt)}.card .ic.warn{color:var(--warnt)}.card .ic.muted{color:var(--mutt)}.card .ic.accent{color:var(--acct)}.btn.primary:disabled{color:var(--mutt)}
.hbadge{color:var(--card)!important}.hbadge.hred{background:var(--dangert)!important}.hbadge.hamb{background:var(--warnt)!important}
.card:focus-visible{outline:2px solid var(--acc);outline-offset:1px;border-color:var(--acc)}
.top{flex-wrap:wrap;row-gap:4px}.top .name{flex:0 1 auto;min-width:0}.top .tag{flex:none;color:var(--mutt)}.card .sub,.card .foot,.tmeta{color:var(--mutt)}
.card .sub.red{color:var(--dangert)}.card .sub.warn,.card.st-warn .sub{color:var(--warnt)}
.stripline{display:flex;align-items:center;gap:10px;margin-top:7px;min-width:0}.strip{list-style:none;margin:0;padding:0;display:flex;align-items:center;flex:none}
.seg{position:relative;box-sizing:border-box;width:15px;height:15px;border-radius:50%;border:1.5px solid var(--mutt);color:var(--mutt);background:transparent;display:inline-flex;align-items:center;justify-content:center;font-size:9px;line-height:1;font-weight:700;flex:none;transition:background-color .15s}
.seg i{font-style:normal}.seg+.seg{margin-left:8px}.seg+.seg::before{content:"";position:absolute;left:-9px;top:50%;width:8px;border-top:1.5px solid var(--mutt);opacity:.55}
.seg.done{background:var(--okt);border-color:var(--okt);color:var(--card)}.seg.cur{border-color:var(--acct);color:var(--acct);background:var(--accbg);font-size:8px}
.seg.fail{background:var(--dangert);border-color:var(--dangert);color:var(--card)}.seg.blk{border-color:var(--warnt);color:var(--warnt);background:var(--warnbg)}.seg.skip{border-style:dashed}
.stg{font-size:11px;color:var(--mutt);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0}.stg.warn{color:var(--warnt)}.stg.red{color:var(--dangert)}
.card .crow{display:flex;flex-wrap:wrap;gap:5px;margin-top:7px}.chip.cr{background:var(--accbg);color:var(--acct)}.chip.q{background:color-mix(in srgb,var(--fg) 9%,transparent);color:var(--mutt)}.chip.bl{background:color-mix(in srgb,var(--warn) 16%,transparent);color:var(--warnt);font-weight:600}
button.chip.crmore{border:0;font:inherit;font-size:11px;cursor:pointer}button.chip.crmore:hover{background:color-mix(in srgb,var(--fg) 16%,transparent)}
.chip.hard{background:color-mix(in srgb,var(--danger) 14%,transparent);color:var(--dangert);font-weight:600}.chip.bud-r{background:color-mix(in srgb,var(--danger) 14%,transparent);color:var(--dangert);font-weight:600}
.last{display:flex;align-items:center;flex-wrap:wrap;gap:0 4px;font-size:11.5px;color:var(--mutt);margin-top:6px;min-height:22px}.last b{font-weight:700}.last.vd-pass b{color:var(--okt)}.last.vd-fail b{color:var(--dangert)}.last.vd-blk b{color:var(--warnt)}
button.lnk{height:22px;min-width:22px;padding:0 5px;border:0;border-radius:5px;background:transparent;color:var(--acct);font:inherit;font-size:11.5px;cursor:pointer;text-decoration:underline}button.lnk:hover{background:var(--accbg)}
.btns.pr{grid-template-columns:minmax(0,1fr) 26px;align-items:start}.btns.pr .btn.primary{width:100%;min-width:0}.btn.more{width:26px;min-width:26px;padding:0;font-size:15px;line-height:1}.mwrap,.apwrap{position:relative}.apwrap{display:inline-flex;min-width:0}
.btn.primary:disabled{background:color-mix(in srgb,var(--fg) 12%,transparent);border-color:var(--bd);color:var(--mutt);opacity:1}
button.chip.apchip{border:0;font:inherit;font-size:11px;font-weight:600;cursor:pointer}.chip.apchip{background:color-mix(in srgb,var(--fg) 9%,transparent);color:var(--mutt);font-weight:600}button.chip.apchip:hover{background:color-mix(in srgb,var(--fg) 16%,transparent);color:var(--fg)}
.menu{position:absolute;z-index:20;right:0;bottom:calc(100% + 4px);min-width:200px;max-width:250px;padding:4px;border:1px solid var(--bd);border-radius:8px;background:var(--card);box-shadow:0 4px 14px rgba(0,0,0,.28);animation:mopen .12s ease-out}
.menu.left{right:auto;left:0;max-width:260px}.menu.down{bottom:auto;top:calc(100% + 4px)}.menu[hidden]{display:none}
@keyframes mopen{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}
.mi{display:flex;align-items:center;flex-wrap:wrap;gap:0 6px;width:100%;min-height:26px;height:auto;padding:4px 8px;border:0;border-radius:5px;background:transparent;color:var(--fg);font:inherit;font-size:12px;text-align:left;cursor:pointer;white-space:normal;justify-content:flex-start}
.mi:hover:not(:disabled),.mi:focus-visible{background:var(--accbg);outline:2px solid var(--acc);outline-offset:-2px}.mi:disabled{opacity:.55;cursor:not-allowed}.mchk{display:inline-block;width:12px;color:var(--acct)}.mdesc{flex-basis:100%;margin-left:18px;font-size:10.5px;color:var(--mutt)}
.mdot{width:7px;height:7px;border-radius:50%;background:var(--warn);margin-left:auto;flex:none}.mh{padding:6px 8px 2px;font-size:10.5px;color:var(--mutt);border-top:1px solid var(--bd);margin-top:4px}.mn{padding:2px 8px;font-size:11.5px;color:var(--mutt);overflow-wrap:anywhere}
.nowblk{margin:0 0 10px;padding:8px 10px;border:1px solid var(--bd);border-radius:10px;background:var(--card)}.nowblk.empty{padding:6px 10px}.nempty{font-size:12px;color:var(--mutt)}
.nsec+.nsec,.nempty+.nsec{margin-top:8px}.nh{font-size:10.5px;font-weight:600;letter-spacing:.04em;color:var(--mutt);margin:0 0 3px}.nlist{list-style:none;margin:0;padding:0}
.nrow{display:flex;align-items:center;gap:8px;min-height:26px;font-size:12px}.nrow::before{content:"▸";color:var(--mutt);flex:none}.nproj{font-weight:600;flex:none;max-width:42%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ntxt{flex:1 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--mutt)}.nrow .btn{flex:none;min-width:52px}.nsec.nwait .ntxt{color:var(--warnt)}
body.vscode-high-contrast .chip,body.vscode-high-contrast .seg,body.vscode-high-contrast .nrow,body.vscode-high-contrast .menu,body.vscode-high-contrast .nowblk{border:1px solid var(--vscode-contrastBorder,currentColor)}
body.vscode-high-contrast .seg{border-width:1.5px}body.vscode-high-contrast .chip{border-radius:11px}
.card.chopen>:not(.top):not(.sheet){display:none}.sheet[hidden],.decide[hidden],.planhint[hidden],.sheet [hidden]{display:none}
.btn.go{background:var(--acc);border-color:var(--acc);color:var(--card);font-weight:600}.btn.go:disabled{background:color-mix(in srgb,var(--fg) 12%,transparent);border-color:var(--bd);color:var(--mutt);opacity:1}
.sheet,.decide{margin:8px 0 0;cursor:default}.chh{font-size:12.5px}.sheet .nhint.bad,.decide .nhint.bad{color:var(--dangert)}.sheet .nhint,.sheet .flabel,.decide .nhint{color:var(--mutt)}
.copt{display:flex;align-items:flex-start;gap:6px;font-size:12px;min-height:22px;line-height:1.35;color:var(--fg)}.copt input{margin:2px 0 0;flex:none;width:14px;height:14px}.copt.tick{padding:4px 0}
.chfs{border:0;margin:0;padding:0;display:flex;flex-direction:column;gap:2px;min-width:0}.chfs legend{padding:0;font-size:11px;color:var(--mutt)}
.chex summary{cursor:pointer;font-size:11.5px;color:var(--acct);min-height:22px;display:flex;align-items:center}.chlist{display:flex;flex-wrap:wrap;gap:4px;margin-top:3px}
.chlist code,.chcmd{overflow-wrap:anywhere;font:11px/1.35 var(--vscode-editor-font-family,monospace);padding:1px 5px;border-radius:4px;background:color-mix(in srgb,var(--fg) 8%,transparent)}.chcmd{display:block;padding:6px 8px;border-radius:6px;user-select:all}
.chstops{margin:4px 0 0;padding-left:18px;font-size:11.5px;color:var(--mutt)}input:focus-visible,summary:focus-visible{outline:2px solid var(--acc);outline-offset:1px}
.apwait{display:flex;align-items:center;gap:8px;margin-top:7px;padding:6px 8px;border-radius:8px;background:var(--accbg);font-size:11.5px}.apwait span{flex:1;min-width:0}.apwait .btn{flex:none;padding:0 8px}
/* ---- panel v3 task 3: five tabs, Reports, Setup, wait kinds in Health ---- */
.tabs{gap:1px;padding:3px 2px}.tab{flex:1 1 auto;min-width:0;padding:0;font-size:11.5px;white-space:nowrap}
.tab i{display:inline-block;margin-left:2px;padding:0 3px;min-width:13px;height:14px;line-height:14px;font-size:9.5px;text-align:center;vertical-align:1px}.tab i:not(.hbadge){background:color-mix(in srgb,var(--fg) 8%,transparent);color:var(--mutt)}.tab i.hbadge{color:var(--card)!important}
.tab[aria-selected="true"]{background:var(--card);color:var(--fg);box-shadow:0 1px 2px rgba(0,0,0,.18)}.tab:focus-visible{outline:2px solid var(--acc);outline-offset:-2px}
.nhint{color:var(--mutt)}.pchip{color:var(--mutt)}.pchip.on{color:var(--acct)}.pselbar,.imeta{color:var(--mutt)}.tab{color:var(--mutt)}.tab:hover,.tab.on{color:var(--fg)}.pill.green{color:var(--okt)}.pill.amber{color:var(--warnt)}.pill.blue{color:var(--acct)}.pill.grey{color:var(--mutt)}.pill.purple{color:var(--purplet)}
.hsub,.hwhy,.hproof,.hreco,.hline1 .htag,.isub{color:var(--mutt)}.hnot,.hnext{color:var(--warnt)}.chk.ok,.chk.red,.chk.skip{color:var(--fg)}
button.sw{box-sizing:border-box;width:34px;height:22px;border:4px solid transparent;background-clip:padding-box}button.sw.on{background-clip:padding-box}
.vh{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
.vchip{display:inline-flex;align-items:center;justify-content:center;height:22px;padding:0 8px;border-radius:11px;font-size:10.5px;font-weight:700;letter-spacing:.02em;white-space:nowrap}
.vchip.v-pass{background:color-mix(in srgb,var(--ok) 16%,transparent);color:var(--okt)}.vchip.v-fail{background:color-mix(in srgb,var(--danger) 14%,transparent);color:var(--dangert)}
.vchip.v-blk{background:color-mix(in srgb,var(--warn) 16%,transparent);color:var(--warnt)}.vchip.v-nt{background:color-mix(in srgb,var(--fg) 9%,transparent);color:var(--mutt)}
.rfilters{margin:0 0 6px}.rfilters .pchips{gap:5px;margin:0 0 6px}.rfilters .pchip{height:24px;padding:0 9px;font-size:11px}.rfilters .pselbar{margin:0 0 6px}
.rgroup{margin:0 0 8px}.rgroup .igname{margin:6px 0 3px}
.rrow{display:grid;grid-template-columns:auto minmax(0,1fr) auto;gap:3px 8px;align-items:center;width:100%;height:auto;min-height:46px;padding:6px 8px;margin:0 0 4px;text-align:start;border-radius:8px;background:var(--card);border:1px solid var(--bd);color:var(--fg);font-size:12px}
.rrow:hover{border-color:var(--acc)}.rrow:focus-visible{outline:2px solid var(--acc);outline-offset:1px}
.rt{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:600}.rd{font-size:11px;color:var(--mutt);white-space:nowrap}
.rsub{grid-column:1/3;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:11px;color:var(--mutt)}.ropen{grid-column:3;justify-self:end;font-size:11px;color:var(--acct)}
.rview{background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:10px 12px}.rback{margin:0 0 6px}.rh{font-size:14px;margin:4px 0;overflow-wrap:anywhere}
.rmeta{display:flex;flex-wrap:wrap;align-items:center;gap:4px 8px;font-size:11px;color:var(--mutt);margin:0 0 8px}
.rbody{font-size:12px;line-height:1.45;overflow-wrap:anywhere}.rbody p{margin:4px 0}.rbody ul,.rbody ol{margin:4px 0;padding-inline-start:18px}.rhd{margin:8px 0 3px;font-size:12px}
.rkv{display:grid;grid-template-columns:72px minmax(0,1fr);gap:6px;padding:3px 0;border-top:1px solid var(--bd)}.rkv:first-child{border-top:0}.rkv b{font-size:11px;font-weight:600;color:var(--mutt)}.rcont{padding-inline-start:78px;font-size:11.5px;color:var(--mutt)}
.rbody pre{white-space:pre-wrap;overflow-wrap:anywhere;margin:4px 0;padding:6px 8px;border-radius:6px;background:color-mix(in srgb,var(--fg) 8%,transparent);font:11px/1.35 var(--vscode-editor-font-family,monospace)}.rbody code{font:11px var(--vscode-editor-font-family,monospace);padding:0 3px;border-radius:3px;background:color-mix(in srgb,var(--fg) 8%,transparent)}
.rnv{display:grid;grid-template-columns:72px minmax(0,1fr);gap:6px;margin:8px 0;padding:6px 8px;border-radius:6px;background:var(--warnbg);border-inline-start:3px solid var(--warn);font-size:12px}.rnv b{font-size:11px;color:var(--warnt)}
.rview .frow{margin-top:8px}.rerr{margin:6px 0;padding:8px 10px;border-radius:8px;background:color-mix(in srgb,var(--danger) 12%,transparent);color:var(--dangert);font-size:12px}.rerr .btn{margin-inline-start:6px}
.rskel{height:46px;margin:0 0 6px;border-radius:8px;background:color-mix(in srgb,var(--fg) 8%,transparent)}@media (prefers-reduced-motion:no-preference){.rskel{animation:rsk 1.4s ease-in-out infinite}}@keyframes rsk{50%{opacity:.5}}
.shead{display:flex;justify-content:space-between;align-items:center;gap:8px;margin:0 0 4px}.shead b{font-size:13px}.shead .btn{flex:none}
.tbhead{display:flex;justify-content:space-between;align-items:center;gap:8px;margin:0 0 4px}.tbhead b{font-size:13px}.tbhead .btn{flex:none}
.chks{list-style:none;margin:8px 0 0;padding:0}.chk{display:flex;align-items:flex-start;gap:8px;margin:0 0 6px;padding:8px 10px;border:1px solid var(--bd);border-radius:8px;background:var(--card);font-size:12px}
.chk.red{border-color:color-mix(in srgb,var(--danger) 45%,transparent)}
.cmark{flex:none;width:18px;height:18px;margin-top:1px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;border:1.5px solid var(--mutt);color:var(--mutt);font-size:11px;font-weight:700;line-height:1}
.chk.ok .cmark{background:var(--okt);border-color:var(--okt);color:var(--card)}.chk.red .cmark{background:var(--dangert);border-color:var(--dangert);color:var(--card)}
.cbody{flex:1;min-width:0}.cname{display:flex;flex-wrap:wrap;align-items:baseline;gap:1px 6px}.cname b{font-size:12.5px}.cneed{font-size:10.5px;color:var(--mutt)}
.creason{margin-top:1px;font-size:11.5px;color:var(--mutt);overflow-wrap:anywhere}.chint{margin-top:3px;font-size:11px;color:var(--mutt);overflow-wrap:anywhere}
.cacts{display:flex;flex-direction:column;gap:5px;flex:none;width:64px}.cacts .btn{width:100%;padding:0 6px}
.plan .mrow{color:var(--mutt)}.cnote{margin-top:3px;font-size:11px;color:var(--mutt);overflow-wrap:anywhere}
.btns.pr.aa{grid-template-columns:minmax(0,1fr) auto 26px}.btn.aside{width:auto;padding:0 8px;white-space:nowrap}.mi.askmi{display:none}
@media (max-width:299px){.btns.pr.aa{grid-template-columns:minmax(0,1fr) 26px}.btn.aside{display:none}.mi.askmi{display:flex}}
.askcard{cursor:default}.askcard:hover,.askcard:focus-within{border-color:var(--bd)}.askcard .sub{font-size:11.5px;color:var(--mutt);margin:2px 0 6px}.askl{margin-top:2px}.askl>span{font-size:11.5px;color:var(--mutt)}
.arow{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-top:6px}.arow .btn{width:auto;min-width:64px;padding:0 12px}.atoday{margin-top:6px}.alast{margin-top:8px;padding-top:8px;border-top:1px solid var(--bd)}.alt{display:block;font-size:12px;margin-bottom:6px;overflow-wrap:anywhere}.alast .frow{display:flex}.alast .frow .btn{width:auto;padding:0 10px}
.aempty{margin-top:8px}
.setupbanner{margin:0 0 10px}.hrow.hk-red .hdot{background:var(--danger)}.hrow.hk-amber .hdot{background:var(--warn)}.hnext{color:var(--warnt)}
body.vscode-high-contrast .rrow,body.vscode-high-contrast .chk,body.vscode-high-contrast .vchip,body.vscode-high-contrast .rview{border:1px solid var(--vscode-contrastBorder,currentColor)}
@media (prefers-reduced-motion:reduce){*,*::before,*::after{transition:none!important;animation:none!important}}

/* ---- panel v3 revision v2 (21 Oct): tokens, the dot rail, one button grid, the autopilot line, sheets, option C ---- */
:root{--warn-soft:color-mix(in srgb,var(--warn) 14%,var(--card));--danger-soft:color-mix(in srgb,var(--danger) 14%,var(--card));--ok-soft:color-mix(in srgb,var(--ok) 14%,var(--card));--acc-soft:color-mix(in srgb,var(--acc) 14%,var(--card))}
.card,.plan,.nowblk,.ilist,.hsec,.rview,.banner,.addbox,.sheet{border-radius:8px}
.btn,.chip,button.chip,.vchip,.pre,.apl,.sfl{border-radius:6px}.pchip,.tab i,.pill{border-radius:6px}
.card.st-warn{background:var(--card);border-color:var(--bd)}
.railw{container:rail/inline-size;margin:8px -4px 0}
.rail{list-style:none;margin:0;padding:0;display:grid;grid-template-columns:repeat(7,minmax(0,1fr))}
.rsi{position:relative;min-width:0}
.rsi::after{content:"";position:absolute;top:11px;left:50%;width:100%;border-top:1.5px solid var(--mutt);opacity:.55}.rsi:last-child::after{display:none}.rsi.ld::after{border-top-color:var(--okt);opacity:1}
.rs{position:relative;display:flex;flex-direction:column;align-items:center;gap:4px;width:100%;height:40px;padding:4px 0 0;border:0;border-radius:6px;background:transparent;color:var(--mutt);font:inherit;font-size:11px;line-height:14px;cursor:pointer}
.rs:hover{background:color-mix(in srgb,var(--fg) 7%,transparent);border:0}.rs:focus-visible{outline:2px solid var(--acc);outline-offset:-2px}.rs[aria-expanded="true"]{box-shadow:inset 0 -2px 0 var(--acc)}
.dt{position:relative;z-index:1;box-sizing:border-box;width:14px;height:14px;border-radius:50%;border:1.5px solid var(--mutt);background:var(--card);display:inline-flex;align-items:center;justify-content:center;font-style:normal;font-size:9px;font-weight:700;line-height:1;color:var(--card);flex:none}
.rw{max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.s-done .dt{background:var(--okt);border-color:var(--okt)}
.s-cur .dt{background:var(--acct);border-color:var(--acct);box-shadow:0 0 0 2px var(--card),0 0 0 3.5px var(--acct)}.s-cur .rw{color:var(--fg);font-weight:700}
.s-wait .dt,.s-blk .dt{background:var(--warnt);border-color:var(--warnt)}.s-wait .rw,.s-blk .rw{color:var(--warnt);font-weight:600}
.s-fail .dt{background:var(--dangert);border-color:var(--dangert)}.s-fail .rw{color:var(--dangert);font-weight:600}
.s-skip .dt{border-style:dashed}
@container rail (max-width:249px){.rail{grid-template-columns:repeat(4,minmax(0,1fr));gap:2px 0}.rsi::after{display:none}.rs{flex-direction:row;justify-content:flex-start;height:28px;padding:0 2px;gap:4px}}
.rdetail{display:flex;flex-wrap:wrap;align-items:center;gap:2px 8px;margin-top:4px;padding:5px 8px;border-radius:6px;background:color-mix(in srgb,var(--fg) 6%,var(--card));font-size:11.5px;color:var(--fg);cursor:default}.rdetail[hidden]{display:none}
.nextl{font-size:11.5px;color:var(--mutt);margin-top:2px}
.apline{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:2px 8px;margin-top:6px;min-height:22px;font-size:11.5px}
.apl,.sfl{height:22px;padding:0 6px;border:0;background:transparent;color:var(--fg);font:inherit;font-size:11.5px;white-space:nowrap;cursor:pointer;max-width:100%}
.apl{margin-inline-start:-6px}.apl .apm{color:var(--mutt)}.apl:hover,.sfl:hover{background:color-mix(in srgb,var(--fg) 8%,transparent);border:0}
.sfl .tk{color:var(--okt);font-weight:700}.sfl.sf-warn,.sfl.sf-off{background:var(--warn-soft);color:var(--warnt);font-weight:600}.sfl.sf-warn:hover,.sfl.sf-off:hover{background:color-mix(in srgb,var(--warn) 24%,var(--card))}
.apl:focus-visible,.sfl:focus-visible,.opt:focus-visible,.pre:focus-visible{outline:2px solid var(--acc);outline-offset:1px}
.runl{font-size:11.5px;color:var(--mutt);margin-top:2px}
.brow{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr) 28px;gap:8px;margin-top:8px;align-items:center}
.brow .btn{height:28px;padding:0 8px;font-size:12.5px;width:100%;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;display:inline-flex;align-items:center;justify-content:center}
.sheet .chex summary{min-height:24px}.brow .mwrap{grid-column:3}@media (max-width:299px){.brow .btn.aside{display:none}}.brow .btn.more{width:28px;min-width:28px;padding:0}.brow .btn.aside{width:100%}
.btn.stopq{background:transparent;color:var(--fg)}.btn.stopc{background:var(--danger-soft);border-color:var(--dangert);color:var(--dangert);font-weight:700}.btn.stopc:hover:not(:disabled){background:color-mix(in srgb,var(--danger) 24%,var(--card));border-color:var(--dangert)}
.btn.danger{color:#fff}
.sheet{display:flex;flex-direction:column;gap:8px;padding:10px;border:1px solid var(--bd);background:color-mix(in srgb,var(--fg) 4%,var(--card))}
.sheet .brow{margin-top:0}.orow{display:flex;flex-direction:column;align-items:flex-start;gap:4px;margin-bottom:4px}
.opt{display:flex;align-items:flex-start;gap:8px;width:100%;height:auto;padding:6px 8px;text-align:start;border:1px solid var(--bd);border-radius:6px;background:transparent;color:var(--fg);font:inherit;font-size:12px;cursor:pointer}
.opt.cur{border-color:var(--acc);background:var(--acc-soft)}.opt:disabled{opacity:.6;cursor:not-allowed}.ork{flex:none;color:var(--acct)}.ort{display:flex;flex-direction:column;min-width:0}.orc{font-size:10.5px;color:var(--acct);font-weight:600}.ord{font-size:11px;color:var(--mutt)}
.pres{display:flex;flex-wrap:wrap;gap:6px}.pre{height:24px;min-width:40px;padding:0 10px;border:1px solid var(--bd);background:transparent;color:var(--fg);font:inherit;font-size:12px;cursor:pointer}.pre[aria-pressed="true"]{background:var(--acc-soft);border-color:var(--acc);color:var(--acct);font-weight:600}
.oq{display:flex;flex-direction:column;gap:4px}.ql{font-size:11.5px;color:var(--mutt)}.olist{list-style:none;margin:0;padding:0;font-size:11.5px;color:var(--fg)}.olist li{padding:1px 0;overflow-wrap:anywhere}
.osum{font-size:12px;line-height:1.4;color:var(--fg)}
.cnote{padding:8px 10px;border-radius:6px;background:var(--warn-soft);border-inline-start:3px solid var(--dangert);font-size:11.5px;color:var(--fg)}.cnh{display:block;margin-bottom:4px;color:var(--dangert);font-weight:700}.cnote ul{margin:0 0 6px;padding-inline-start:16px}.cnone{font-weight:600}
.cband{display:flex;align-items:flex-start;gap:8px;margin-top:6px;padding:6px 8px;border-radius:6px;font-size:12px;font-weight:600;line-height:1.35}.cband.amber{background:var(--warn-soft);color:var(--warnt)}.cband.red{background:var(--danger-soft);color:var(--dangert)}.cbm{flex:none;width:14px;text-align:center;font-weight:700}
.cwait{margin-top:8px}.cwrow{margin:4px 0}.cwt{font-size:12px;overflow-wrap:anywhere}.cwait .nh{margin:0 0 2px}
.cban{display:flex;align-items:center;justify-content:space-between;gap:8px;margin:0 0 6px;padding:5px 8px;border-radius:6px;background:var(--warn-soft);color:var(--warnt);font-size:11.5px;line-height:1.35}.cban.red{background:var(--danger-soft);color:var(--dangert)}.cban .btn{flex:none;height:24px;color:var(--fg)}
.askprev{margin:0}.askbtns{margin-top:8px}
body.vscode-high-contrast .cband,body.vscode-high-contrast .cban,body.vscode-high-contrast .cnote,body.vscode-high-contrast .sheet,body.vscode-high-contrast .sfl.sf-warn,body.vscode-high-contrast .sfl.sf-off,body.vscode-high-contrast .rdetail,body.vscode-high-contrast .opt,body.vscode-high-contrast .pre{border:1px solid var(--vscode-contrastBorder,currentColor)}
body.vscode-high-contrast .cnote{border-inline-start:3px solid var(--dangert)}

${X.css}
${SX.css}
${HX.css}
${TX.css}${X.getCtx().capabilities.release === true ? '\n' + TLX.css : ''}
</style></head><body data-first="${esc(firstWithIdeas)}" data-dloading="${esc(t('details.loading'))}">
<div class="frozen">
<div class="plan" title="Bar colour: green under 50 %, amber 50-79 % (mid), orange 80-94 % (high), red 95 % and above (almost out)">
  ${ms.length ? ms.map(meter).join('') : ''}
  ${tokenRows(data.ledger, allDay)}
  ${MACH ? guardRow(data.guard) : ''}
  ${macRow(data.health)}
  ${data.modelReset ? `<div class="grow" title="A /model choice had changed your saved default. New chats start on opusplan again (Opus plans, Sonnet builds); the chat where you switched keeps your choice."><span><i class="dot warn"></i>Default model reset to opusplan (was ${esc(String(data.modelReset.was))})</span><button class="btn" data-health data-op="dismiss-model-reset" data-id="-">OK</button></div>` : ''}
  ${awayRow(data.guard)}
</div>
${tabBar}
${cBanner(ps)}
</div>
<main class="scroll" id="scroll">
${banner(data)}
<section data-pane="projects" id="pane-projects" role="tabpanel" aria-labelledby="tab-projects">
${projectNotice(data)}
${asideNotice(data)}
${data.setup && !data.setup.error && sr ? `<div class="banner setupbanner" role="status"><div><b>${esc(t('setup.finish'))}</b><div class="isub">${esc(sr === 1 ? t('setup.finishSub1') : t('setup.finishSub', { n: sr }))}</div></div><div class="bgrid"><button class="btn primary" data-tab="setup">${esc(t('setup.finishBtn'))}</button></div></div>` : ''}
${data.host && data.host.kind === 'windows' ? '' : '<div class="ptools"><button class="btn primary" data-toggle="newbox" aria-expanded="false">+ New project</button><button class="btn" data-cmd="check" title="Update tools, skills and extensions; check every project">Check &amp; update</button></div>'}
${data.host && data.host.kind === 'windows' ? '' : newBox(data)}
${ps.length ? nowBlock(ps) : ''}
${ps.length ? ps.map((p, i) => card(p, p.levelSwitch || data.levelSwitch, i, weekPct, !!(data.autopilot && data.autopilot.until_disabled_supported))).join('') : (askP || asidePs.length ? '' : HX.notice(data.host, data.setup && data.setup.os, HXD, 'projects') + (data.host && data.host.kind === 'windows' ? '' : '<div class="empty">No projects yet. Use + to create one.</div>'))}
${asideRows(asidePs, (p, k) => card(p, p.levelSwitch || data.levelSwitch, k, weekPct, !!(data.autopilot && data.autopilot.until_disabled_supported)))}
${askP ? askCard(askP) : ''}
${sp.map(p => `<div class="small${p.active ? ' active' : ''}" data-dir="${esc(p.dir)}" data-vscode-context='${esc(JSON.stringify({ webviewSection: 'project', dir: p.dir, name: p.name, preventDefaultContextMenuItems: true }))}'>${svg('bulb')}${esc(p.name)} · discuss before it becomes a project</div>`).join('')}
</section>
<section data-pane="reports" id="pane-reports" role="tabpanel" aria-labelledby="tab-reports" hidden>${reportsPane(data)}</section>
<section data-pane="ideas" data-projects="${esc(JSON.stringify(data.projects.map(x => ({ name: x.name, label: label(x), held: !!x.held }))))}" id="pane-ideas" role="tabpanel" aria-labelledby="tab-ideas" hidden>${ideasPane(data)}</section>
<section data-pane="health" id="pane-health" role="tabpanel" aria-labelledby="tab-health" hidden>${HX.healthNote(data.host, HXD)}${healthPane(data.health, pm)}${asideHealth(data.health)}${TX.card(data.tidy, { tool: data.tidyTool !== false })}</section>
<section data-pane="setup" id="pane-setup" role="tabpanel" aria-labelledby="tab-setup" hidden>${setupPane(data)}</section>
</main>
<script${nonce ? ` nonce="${nonce}"` : ''}>
const vscode = typeof acquireVsCodeApi === 'function' ? acquireVsCodeApi() : { postMessage: () => {}, getState: () => null, setState: () => {} };
const S = vscode.getState() || {}; const Q = new URLSearchParams(location.search); if (Q.get('tab')) S.tab = Q.get('tab'); if (Q.get('proj')) S.proj = Q.get('proj'); if (Q.get('add')) S.addOpen = Q.get('add');   // the query is only used by preview checks
const PR = (() => { try { return JSON.parse((document.querySelector('[data-pane="ideas"]') || { dataset: {} }).dataset.projects || '[]'); } catch (e) { return []; } })();
const $ = (r, s) => r.querySelector(s);
const RF = () => S.rf || (S.rf = { project: '', kind: '', verdict: '' });
function rfApply() {                                       // Reports filters: project, verdict and kind narrow the same list; groups with no visible row hide
  const list = $(document, '[data-rlist]'); if (!list) return; const f = RF(); let shown = 0;
  document.querySelectorAll('.rrow').forEach(r => { const ok = (!f.project || r.dataset.proj === f.project) && (!f.kind || r.dataset.kind === f.kind) && (!f.verdict || r.dataset.verdict === f.verdict); r.hidden = !ok; if (ok) shown++; });
  document.querySelectorAll('.rgroup').forEach(g => { g.hidden = !g.querySelector('.rrow:not([hidden])'); });
  document.querySelectorAll('[data-rf]').forEach(b => { const on = (f[b.dataset.rf] || '') === b.dataset.val; b.classList.toggle('on', on); b.setAttribute('aria-pressed', on ? 'true' : 'false'); });
  const ps = $(document, '[data-rproj]'); if (ps) ps.value = f.project; const none = $(document, '[data-rnone]'); if (none) none.hidden = shown > 0;
}
function show() {
  const tab = S.tab || 'projects', first = document.body.dataset.first, sel = $(document, '[data-psel]');
  let proj = S.proj; if (!proj || !document.querySelector('.ilist[data-proj="' + CSS.escape(proj) + '"]')) proj = first || (sel && sel.options.length ? sel.options[0].value : '');
  document.querySelectorAll('[role="tab"]').forEach(b => { const on = b.dataset.tab === tab; b.classList.toggle('on', on); b.setAttribute('aria-selected', on ? 'true' : 'false'); b.tabIndex = on ? 0 : -1; });
  document.querySelectorAll('[data-pane]').forEach(s => { s.hidden = s.dataset.pane !== tab; });
  if (sel) sel.value = proj;
  rfApply();
  { const am = $(document, '[data-askmodel]'); if (am && S.askModel) am.value = S.askModel; }
  { const aq = $(document, '[data-askq]'); if (aq) { if (S.askDraft && !aq.value) aq.value = S.askDraft; askSync(aq.closest('[data-askcard]')); } }
  document.querySelectorAll('.ilist').forEach(l => { l.hidden = l.dataset.proj !== proj; });
  const d = S.draft;                                   // the panel redraws on every change: bring back a half-typed idea
  if (S.addOpen) document.querySelectorAll('.ilist').forEach(l => { const box = $(l, '[data-addbox]'); if (box && l.dataset.proj === S.addOpen && box.hidden) { box.hidden = false; } });
  if (d && d.text) document.querySelectorAll('.ilist').forEach(l => { const box = $(l, '[data-addbox]'); if (box && l.dataset.proj === d.list) { $(box, '[data-f="text"]').value = d.text; if (d.project) $(box, '[data-f="project"]').value = d.project; box.hidden = false; } });
  if (S.addOpen && S.focused) { const box = document.querySelector('.ilist[data-proj="' + CSS.escape(S.addOpen) + '"] [data-addbox]'), ta = box && $(box, '[data-f="text"]');   // you were typing: the cursor goes back where it was
    if (ta && !box.hidden) { ta.focus(); const c = S.caret || [ta.value.length, ta.value.length]; try { ta.setSelectionRange(Math.min(c[0], ta.value.length), Math.min(c[1], ta.value.length)); } catch (err) { /* not a text box */ } } }
  const nb = $(document, '[data-newbox]');                // New project box: reopen it with the half-typed draft after a redraw
  if (nb) { if (S.newOpen) { nb.hidden = false; const nd = S.newDraft || {}; ['name', 'kind', 'about'].forEach(k => { const f = $(nb, '[data-nf="' + k + '"]'); if (f && nd[k] != null && nd[k] !== '') f.value = nd[k]; }); }
    const tg = $(document, '[data-toggle="newbox"]'); if (tg) tg.setAttribute('aria-expanded', S.newOpen ? 'true' : 'false'); newCheck(nb);
    if (S.newOpen && S.newFocus && (S.tab || 'projects') === 'projects') { const f = $(nb, '[data-nf="' + (S.newField || 'name') + '"]'); if (f) { f.focus(); const c = S.newCaret || [f.value.length, f.value.length]; try { f.setSelectionRange(Math.min(c[0], f.value.length), Math.min(c[1], f.value.length)); } catch (err) { /* a select has no caret */ } } } }
}
// ---- sheets inside a card (Change, Safe mode, On its own). The page never changes anything itself: a choice posts one message and the extension types the owner's command into a terminal (no Enter).
const sheetBox = (name, kind) => [...document.querySelectorAll('[data-sheetbox="' + kind + '"]')].find(b => (b.dataset.project || b.dataset.own) === name) || null;
let chBeat = 0;
function sheetOpen(name, kind, restore) {
  const box = sheetBox(name, kind); if (!box) return false; const card = box.closest('.card');
  document.querySelectorAll('[data-sheetbox]').forEach(b => { if (b !== box) { b.hidden = true; b.closest('.card').classList.remove('chopen'); } });
  if (kind === 'own') ownOpen(box, restore);
  box.hidden = false; card.classList.add('chopen');
  S.sheet = { project: name, kind }; vscode.setState(S);
  vscode.postMessage({ type: 'editing', on: true }); clearInterval(chBeat); chBeat = setInterval(() => vscode.postMessage({ type: 'editing', on: true }), 60000);
  if (!restore) { const f = box.querySelector('select, .opt:not(:disabled), button:not(:disabled)'); if (f) f.focus(); }
  return true;
}
function sheetClose(box, refocus) {
  const card = box.closest('.card'), kind = box.dataset.sheetbox; box.hidden = true; card.classList.remove('chopen'); clearInterval(chBeat); delete S.sheet; if (kind === 'own') delete S.own; vscode.setState(S); vscode.postMessage({ type: 'editing', on: false });
  if (refocus) { const tr = kind === 'toolbox' || kind === 'describe' ? card.querySelector('.btn.more') : (card.querySelector('[data-sheet="' + kind + '"]') || card.querySelector('.apl')); if (tr) tr.focus(); }
}
function sheetClick(e, box) {
  e.stopPropagation();
  if (e.target.closest('[data-sheetclose], [data-ocancel]')) { sheetClose(box, true); return; }
  const lv = e.target.closest('[data-lv]'); if (lv) { if (lv.disabled) return; const to = lv.dataset.lv, name = lv.dataset.project;
    if (lv.getAttribute('aria-checked') === 'true') { sheetClose(box, true); return; }
    if (to === 'full') { sheetClose(box, false); sheetOpen(name, 'own'); return; }
    sheetClose(box, false); vscode.postMessage({ type: 'act', act: 'ap', project: name, to, dir: '', cr: '', report: '', verb: '' }); return; }
  const sf = e.target.closest('[data-safeto]'); if (sf) { if (sf.disabled) return; if (sf.getAttribute('aria-checked') === 'true') { sheetClose(box, true); return; } sheetClose(box, false); vscode.postMessage({ type: 'safe', project: sf.dataset.project, to: sf.dataset.safeto }); return; }
  if (box.dataset.sheetbox === 'own') ownClick(e, box);
}
// ---- "On its own": Keep going until + three questions + live summary. Same validate() as the extension (charter.js).
const OWD = { time: 3, budget: 10, day: 4, crs: 3 };
const ownMsg = box => { try { return JSON.parse(box.dataset.msg || '{}'); } catch (err) { return {}; } };
const ownData = (box, k) => { try { return JSON.parse(box.dataset[k] || '[]'); } catch (err) { return []; } };
const og = (box, k) => box.querySelector('[data-of="' + k + '"]');
function ownRead(box) {
  const P = box._p || (box._p = Object.assign({}, OWD)), mode = box.querySelector('[data-of="depsMode"]:checked');
  return { until: og(box, 'until').value, time: P.time, budget: P.budget, day: P.day, crs: P.crs, goal: og(box, 'goal').value, folders: og(box, 'folders').value, depsMode: mode ? mode.value : 'none', deps: og(box, 'deps').value, hours: og(box, 'hours').value.trim(), share: og(box, 'share').value.trim(), tick: og(box, 'tick').checked };
}
function ownWrite(box, f) {
  box._p = { time: f.time, budget: f.budget, day: f.day, crs: f.crs };
  og(box, 'until').value = f.until; ['goal', 'folders', 'deps', 'hours', 'share'].forEach(k => { og(box, k).value = f[k] || ''; });
  box.querySelectorAll('[data-of="depsMode"]').forEach(r => { r.checked = r.value === (f.depsMode || 'none'); }); og(box, 'tick').checked = !!f.tick;
}
const joinAnd = (l, w) => l.length < 2 ? l.join('') : l.slice(0, -1).join(', ') + ' ' + w + ' ' + l[l.length - 1];
function ownCalc(box, f) {
  const M = ownMsg(box), crs = ownData(box, 'crs'), folders = ownData(box, 'folders'), wk = parseFloat(box.dataset.week), pre = box.dataset.blocked || '';
  const act = crs.find(c => c.active) || crs[0], list = f.until === 'a' ? (act ? [act] : []) : crs.slice(0, 5), ends = list.map(c => c.id);
  const scopeText = f.folders.trim() ? f.folders : folders.map(x => x + '/**').join(',');
  let goal = f.goal.trim() ? f.goal : (list.length ? 'Finish ' + (f.until === 'a' ? list[0].id + ' ' + list[0].title : ends.join(', ')) : ''); goal = Array.from(goal).slice(0, 200).join('');
  const timeVal = f.hours || (f.until === 'b' ? '8' : String(f.time)), budgetVal = f.share || String(f.budget);
  const r = CHV({ goal, scope: scopeText, budget: budgetVal, time: f.until === 'c' ? '3' : timeVal, depsMode: f.depsMode, deps: f.deps, ends }, Object.assign({}, CHX, { openCrs: crs.map(c => c.id) }));
  const day = f.until === 'c' ? CHUC(f.day, f.crs, r.value.budget) : '';
  const dirty = (S.own && S.own.dirty) || {};
  let why = pre;
  if (!why && !list.length) why = M.noCr;
  if (!why && f.until === 'c' && box.dataset.cok !== '1') why = M.notReady;
  if (!why && !scopeText.trim()) why = M.foldersWhy;
  if (!why) { const bad = Object.keys(r.errors).filter(k => k !== 'ends' && !(f.until === 'c' && k === 'time')); if (bad.length) { const k = bad.find(x => dirty[x]) || bad[0]; why = r.errors[k]; } }
  if (!why && day) why = day;
  if (!why && !f.tick) why = M.tickWhy;
  const fs = (r.value.scope || []).map(x => (x.endsWith('/**') ? x.slice(0, -2) : x)), ftxt = joinAnd(fs, M.and || 'and');
  const ctx = { cr: list[0] ? list[0].id : '', crs: joinAnd(ends, M.and || 'and'), time: String(r.value.time == null ? timeVal : r.value.time), budget: String(r.value.budget == null ? budgetVal : r.value.budget), folders: ftxt, day: String(f.day), crsDay: String(f.crs), deps: (r.value.deps && r.value.deps.names || []).join(', ') };
  const tpl = f.until === 'c' ? M.sumC : f.until === 'b' ? M.sumB : (f.depsMode === 'listed' ? M.sumAdeps : M.sumA);
  const summary = list.length && fs.length ? Object.keys(ctx).reduce((acc, k) => acc.split('{' + k + '}').join(ctx[k]), tpl) : '';
  return { f, M, list, crs, r, why, summary, ctx, wk, budgetVal, dirty };
}
function ownCheck(box) {
  const f = ownRead(box), c = ownCalc(box, f), M = c.M, u = f.until;
  const hint = og(box, 'until').closest('label').nextElementSibling;                       // [data-ohint]
  const act = c.crs.find(x => x.active) || c.crs[0];
  hint.textContent = !c.crs.length ? M.noCr : u === 'a' ? M.untilA.replace('{cr}', act.id).replace('{title}', Array.from(act.title).slice(0, 60).join('')) : u === 'b' ? M.untilB : M.untilC;
  const ul = box.querySelector('[data-olist]'); ul.textContent = '';
  if (u !== 'a' && c.crs.length) { c.crs.slice(0, 5).forEach(x => { const li = document.createElement('li'); li.setAttribute('dir', 'auto'); li.textContent = x.id + ' · ' + x.title + (x.chat ? ' ' + M.chat : ''); ul.appendChild(li); });
    if (c.crs.length > 5) { const li = document.createElement('li'); li.textContent = M.bmore; ul.appendChild(li); } ul.hidden = false; } else ul.hidden = true;
  box.querySelector('[data-cnote]').hidden = u !== 'c';
  box.querySelectorAll('[data-tpl]').forEach(li => { li.textContent = li.dataset.tpl.replace('{day}', String(f.day)).replace('{week}', String(c.budgetVal)); });
  const tp = box.querySelector('[data-pres="time"]'), tt = box.querySelector('[data-otimetxt]'); tp.hidden = u !== 'a'; tt.hidden = u === 'a'; tt.textContent = u === 'b' ? M.timeB : u === 'c' ? M.timeC : '';
  box.querySelector('[data-oqday]').hidden = u !== 'c'; box.querySelector('[data-oqcrs]').hidden = u !== 'c';
  box.querySelectorAll('[data-pre]').forEach(b => { b.setAttribute('aria-pressed', String(box._p[b.dataset.pre]) === b.dataset.v ? 'true' : 'false'); });
  const L = box.querySelector('[data-oleft]'), bv = Number(c.budgetVal);
  if (Number.isFinite(c.wk)) { const left = Math.max(0, Math.round((100 - c.wk) * 10) / 10); L.textContent = M.left.replace('{left}', String(left)) + (bv > left ? ' ' + M.over : ''); } else L.textContent = M.leftNone;
  const dirty = c.dirty; Object.keys({ goal: 1, scope: 1, budget: 1, time: 1, deps: 1, ends: 1 }).forEach(k => { const e = box.querySelector('[data-oerr="' + k + '"]'); if (!e) return; const msg = dirty[k] && !(f.until === 'c' && k === 'time') ? (c.r.errors[k] || '') : ''; e.textContent = msg; e.hidden = !msg; });
  og(box, 'deps').hidden = f.depsMode !== 'listed';
  box.querySelector('[data-osum]').textContent = c.summary; box.querySelector('[data-otick]').textContent = u === 'c' ? M.tickC : u === 'b' ? M.tickB : M.tickA;
  const w = box.querySelector('[data-owhy]'), go = box.querySelector('[data-ostart]'); w.textContent = c.why ? M.whyOff.replace('{why}', c.why.replace(/[.]+$/, '') + '.') : ''; go.disabled = !!c.why; go.title = c.why;
  if (c.why === M.foldersWhy) box.querySelector('[data-omore]').open = true;
  return c;
}
function ownSave(box, field) { S.own = Object.assign({ project: box.dataset.own, dirty: {} }, S.own, { project: box.dataset.own, f: ownRead(box) }); if (field) { S.own.field = field.dataset.of || ''; S.own.caret = [field.selectionStart == null ? 0 : field.selectionStart, field.selectionEnd == null ? 0 : field.selectionEnd]; } vscode.setState(S); }
function ownOpen(box, restore) {
  if (!restore) { S.own = { project: box.dataset.own, dirty: {}, f: null }; ownWrite(box, Object.assign({ until: 'a', goal: '', folders: '', deps: '', hours: '', share: '', tick: false, depsMode: 'none' }, OWD)); }
  else if (S.own && S.own.f) ownWrite(box, S.own.f);
  ownCheck(box);
}
function ownClick(e, box) {
  const pr = e.target.closest('[data-pre]'); if (pr) { const k = pr.dataset.pre; box._p = box._p || Object.assign({}, OWD); box._p[k] = Number(pr.dataset.v); if (k === 'budget') og(box, 'share').value = ''; if (k === 'time') og(box, 'hours').value = ''; ownSave(box); ownCheck(box); return; }
  const go = e.target.closest('[data-ostart]');
  if (go) { if (go.disabled) return; const c = ownCheck(box); if (c.why) return; const f = c.f;
    vscode.postMessage({ type: 'charter', op: 'start', project: box.dataset.own, goal: c.r.value.goal, scope: c.r.value.scope.join(','), budget: String(c.r.value.budget), time: f.until === 'c' ? '' : String(c.r.value.time), depsMode: f.depsMode, deps: f.deps, ends: c.r.value.ends, until: f.until, day: f.until === 'c' ? f.day : 0, crsDay: f.until === 'c' ? f.crs : 0 });
    sheetClose(box, false); }
}
document.addEventListener('input', e => { const cf = e.target.closest('[data-of]'); if (!cf) return; const box = cf.closest('.own'); if (!box) return;
  const k = ({ hours: 'time', share: 'budget', folders: 'scope', depsMode: 'deps' })[cf.dataset.of] || cf.dataset.of; S.own = Object.assign({ project: box.dataset.own, dirty: {} }, S.own); if (k !== 'tick' && k !== 'until') S.own.dirty[k] = 1; ownSave(box, cf); ownCheck(box); });
document.addEventListener('change', e => { const cf = e.target.closest('[data-of]'); if (!cf) return; const box = cf.closest('.own'); if (box) { ownSave(box, cf); ownCheck(box); } });
function stepClose(card, refocus) { const det = card && card.querySelector('[data-rdetail]'); if (!det) return; const open = card.querySelector('.rs[aria-expanded="true"]'); card.querySelectorAll('.rs').forEach(b => b.setAttribute('aria-expanded', 'false')); det.hidden = true; det.textContent = ''; delete S.step; vscode.setState(S); if (refocus && open) open.focus(); }
function stepOpen(rs) {
  const card = rs.closest('.card'), det = card.querySelector('[data-rdetail]'); if (rs.getAttribute('aria-expanded') === 'true') { stepClose(card, false); return; }
  document.querySelectorAll('.rs[aria-expanded="true"]').forEach(b => { b.setAttribute('aria-expanded', 'false'); const d = b.closest('.card').querySelector('[data-rdetail]'); d.hidden = true; d.textContent = ''; });
  rs.setAttribute('aria-expanded', 'true'); det.textContent = ''; const sp = document.createElement('span'); sp.textContent = rs.dataset.detail; det.appendChild(sp);
  if (rs.dataset.report) { const b = document.createElement('button'); b.type = 'button'; b.className = 'lnk'; b.textContent = det.dataset.rl || 'report ›'; b.dataset.act = 'openreport'; b.dataset.report = rs.dataset.report; b.dataset.project = rs.dataset.project; b.setAttribute('aria-label', 'Open the ' + rs.dataset.name + ' report'); det.appendChild(b); }
  det.hidden = false; S.step = { project: rs.dataset.project, id: rs.dataset.step }; vscode.setState(S);
}
function dOpen(name, restore) { const b = [...document.querySelectorAll('[data-decide]')].find(x => x.dataset.decide === name); if (!b) return false; b.hidden = false; S.decide = name; vscode.setState(S); return true; }
function planHint(name) { const h = [...document.querySelectorAll('[data-planhint]')].find(x => x.dataset.planhint === name); if (h) { h.hidden = false; S.planHint = Object.assign({}, S.planHint, { [name]: 1 }); vscode.setState(S); } }
function tidy(n) { const t = String(n).toLowerCase().replace(/[^a-z0-9._-]+/g, '-').replace(/^[-.]+/, '').slice(0, 40).replace(/[-.]+$/, ''); return /[a-z0-9]/.test(t) ? t : ''; }   // same rule as bin/new-project and the extension's tidyName
function newCheck(nb) {                                    // live hint under the name; Create is on only for a free tidy name AND a picked type, when nothing is being created
  const raw = $(nb, '[data-nf="name"]').value, t = tidy(raw), hint = $(nb, '[data-nhint]'), rule = $(nb, '[data-nrule]'), btn = $(nb, '[data-nform="create"]'), kind = $(nb, '[data-nf="kind"]').value, kh = $(nb, '[data-nkind]');
  let names = [], M = {}; try { names = JSON.parse(nb.dataset.names || '[]'); M = JSON.parse(nb.dataset.msg || '{}'); } catch (err) { /* none */ }
  const exists = !!t && names.some(x => x.toLowerCase() === t), busy = nb.dataset.busy === '1', has = !!raw.trim();
  hint.textContent = !has ? M.empty : !t ? M.rule : exists ? M.taken : M.hint.replace('{name}', t);
  hint.classList.toggle('bad', has && (!t || exists));
  rule.textContent = M.rule; rule.hidden = !(has && !!t && raw.trim() !== t);          // the name will be tidied: say the rule, do not block
  kh.hidden = !(has && !!t && !exists && !kind);
  btn.disabled = !t || exists || busy || !kind; btn.title = busy ? M.typeBusy : !kind ? 'Choose a type first.' : '';
}

${CHARTER.clientSource()}
show();
{ const v = $(document, '.rview'); if (v && (S.tab || 'projects') === 'reports' && S.rvFocus !== v.dataset.rview) { const b = $(v, '[data-rv="back"]'); if (b) { b.focus(); S.rvFocus = v.dataset.rview; vscode.setState(S); } } else if (!v && S.rvFocus) { delete S.rvFocus; vscode.setState(S); } }   // the viewer opens with focus on its back button
if (S.sheet && S.sheet.project) { if (sheetOpen(S.sheet.project, S.sheet.kind, true)) { const fl = S.own && S.own.field && S.sheet.kind === 'own' && sheetBox(S.sheet.project, 'own').querySelector('[data-of="' + S.own.field + '"]'); if (fl && S.own.focus) { fl.focus(); try { fl.setSelectionRange(S.own.caret[0], S.own.caret[1]); } catch (err) { /* checkbox */ } } } else { delete S.sheet; vscode.setState(S); } }
if (S.step) { const rs0 = [...document.querySelectorAll('.rs')].find(b => b.dataset.project === S.step.project && b.dataset.step === S.step.id); if (rs0) stepOpen(rs0); else { delete S.step; vscode.setState(S); } }
if (S.decide) { if (!dOpen(S.decide)) { delete S.decide; vscode.setState(S); } }
if (S.planHint) Object.keys(S.planHint).forEach(n => planHint(n));
const sc = document.getElementById('scroll'), skey = () => (S.tab || 'projects') + '|' + (S.proj || '');
if (sc) { if (S.scrollKey === skey() && S.scroll) sc.scrollTop = S.scroll;                      // the panel redraws on every change: come back to where you were
  let st; sc.addEventListener('scroll', () => { clearTimeout(st); st = setTimeout(() => { S.scroll = sc.scrollTop; S.scrollKey = skey(); vscode.setState(S); }, 120); }); }
${X.clientJs}
${SX.clientJs}
${TX.clientJs}${X.getCtx().capabilities.release === true ? '\n' + TLX.clientJs : ''}
const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text) n.textContent = text; return n; };
let restoring = false;
function openPick(btn) {                               // Move… / Copy…: a dropdown right under the idea, no VS Code input bar
  const row = btn.closest('.ibody'); const old = $(row, '.pickrow'); if (old) { old.remove(); return; }
  document.querySelectorAll('.pickrow').forEach(n => n.remove());
  const op = btn.dataset.pick, box = el('div', 'pickrow'), s = document.createElement('select'); s.setAttribute('aria-label', op === 'move' ? 'Move to project' : 'Copy to project');
  PR.filter(x => !x.held && x.name !== btn.dataset.project).forEach(x => { const o = document.createElement('option'); o.value = x.name; o.textContent = x.label; s.appendChild(o); });
  const go = el('button', 'btn primary', op === 'move' ? 'Move here' : 'Copy here'), no = el('button', 'btn quiet', 'Cancel');
  go.type = no.type = 'button';
  go.addEventListener('click', ev => { ev.stopPropagation(); if (s.value) vscode.postMessage({ type: 'idea', op, project: btn.dataset.project, id: btn.dataset.id, to: s.value }); box.remove(); });
  no.addEventListener('click', ev => { ev.stopPropagation(); box.remove(); });
  s.addEventListener('change', () => { S.pick = { op, project: btn.dataset.project, id: btn.dataset.id, to: s.value }; vscode.setState(S); });
  const done = () => { delete S.pick; vscode.setState(S); };
  go.addEventListener('click', done); no.addEventListener('click', done);
  if (S.pick && S.pick.op === op && S.pick.id === btn.dataset.id && S.pick.project === btn.dataset.project && S.pick.to) s.value = S.pick.to;
  box.append(s, go, no); row.appendChild(box); if (!restoring) { s.focus(); S.pick = { op, project: btn.dataset.project, id: btn.dataset.id, to: s.value }; vscode.setState(S); }
}
document.addEventListener('change', e => { const rp = e.target.closest('[data-rproj]'); if (rp) { RF().project = rp.value; vscode.setState(S); rfApply(); } });
document.addEventListener('keydown', e => {                 // tabs: roving tabindex, arrows / Home / End move and open the tab (role=tablist); Esc leaves the report viewer
  if (e.key === 'Escape' && e.target.closest && e.target.closest('.rview') && !openMenu) { const b = $(document, '[data-rv="back"]'); if (b) { e.preventDefault(); b.click(); } return; }
  const tb = e.target.closest && e.target.closest('[role="tab"]'); if (!tb || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) return;
  const tabs = [...document.querySelectorAll('[role="tab"]')], i = tabs.indexOf(tb);
  const to = e.key === 'Home' ? 0 : e.key === 'End' ? tabs.length - 1 : e.key === 'ArrowRight' ? (i + 1) % tabs.length : (i - 1 + tabs.length) % tabs.length;
  e.preventDefault(); disarm(); S.tab = tabs[to].dataset.tab; vscode.setState(S); show(); tabs[to].focus(); if (sc) sc.scrollTop = 0;
});
document.addEventListener('change', e => { const sel = e.target.closest('[data-psel]'); if (sel) { S.proj = sel.value; vscode.setState(S); show(); if (sc) sc.scrollTop = 0; } });
const saveDraft = f => { const l = f.closest('.ilist'), box = f.closest('[data-addbox]'), ta = $(box, '[data-f="text"]');
  S.draft = { list: l.dataset.proj, project: $(box, '[data-f="project"]').value, text: ta.value }; S.caret = [ta.selectionStart, ta.selectionEnd]; vscode.setState(S); };
const saveNew = f => { const nb = f.closest('[data-newbox]'); S.newDraft = { name: $(nb, '[data-nf="name"]').value, kind: $(nb, '[data-nf="kind"]').value, about: $(nb, '[data-nf="about"]').value };
  S.newField = f.dataset.nf; S.newCaret = [f.selectionStart == null ? 0 : f.selectionStart, f.selectionEnd == null ? 0 : f.selectionEnd]; newCheck(nb); vscode.setState(S); };
function askSync(card) {                                    // counter in code points and the Ask button: on for 1-2000 characters not starting with '-' (the CLI would read it as an option)
  if (!card) return; const inp = $(card, '[data-askq]'), c = $(card, '[data-askcount]'), go = $(card, '[data-askgo]'); if (!inp || !c || !go) return;
  const v = inp.value, n = Array.from(v).length, dash = v.trim().startsWith('-');
  c.textContent = dash ? c.dataset.dash : c.dataset.fmt.replace('{n}', String(n)); c.classList.toggle('bad', dash); go.disabled = !v.trim() || dash || n > +c.dataset.max || go.dataset.full === '1';
  const pv = $(card, '[data-askprev]'), ms = $(card, '[data-askmodel]'); if (pv && ms) pv.textContent = 'shipm ask --inbox --model ' + ms.value + ' "' + Array.from(v.trim()).slice(0, 60).join('') + (n > 60 ? '…' : '') + '"';
}
document.addEventListener('input', e => { const aq = e.target.closest('[data-askq]'); if (aq) { S.askDraft = aq.value; vscode.setState(S); askSync(aq.closest('[data-askcard]')); }
  const f = e.target.closest('[data-f]'); if (f) saveDraft(f); const n = e.target.closest('[data-nf]'); if (n) saveNew(n); });
document.addEventListener('change', e => { const n = e.target.closest('[data-nf]'); if (n) saveNew(n); const am = e.target.closest('[data-askmodel]'); if (am) { S.askModel = am.value; vscode.setState(S); askSync(am.closest('[data-askcard]')); } });
document.addEventListener('keyup', e => { const n = e.target.closest('[data-nf]'); if (n && e.key !== 'Enter' && e.key !== 'Tab') saveNew(n); });
document.addEventListener('keyup', e => { const f = e.target.closest('[data-f="text"]'); if (f) saveDraft(f); });
document.addEventListener('click', e => { const f = e.target.closest('[data-f="text"]'); if (f) saveDraft(f); });
function closeNew(nb) { ['name', 'about'].forEach(k => { $(nb, '[data-nf="' + k + '"]').value = ''; }); $(nb, '[data-nf="kind"]').selectedIndex = 0; delete S.newOpen; delete S.newDraft; delete S.newFocus; delete S.newField; delete S.newCaret; newCheck(nb); }
let armedBtn = null, armedTimer = 0; const dropArmed = new WeakSet();   // the 'Sure?' state lives only in these variables: a data-armed attribute in the markup is display, never read as consent
function disarm(keepText) {
  if (!armedBtn) return; clearInterval(armedTimer);
  const b = armedBtn; armedBtn = null; b.dataset.armed = '';
  if (!keepText) { b.textContent = b.dataset.label; b.classList.remove('danger'); const im = b.closest('li, .hsec'); const box = im && im.querySelector('.himpact'); if (box) box.hidden = true; vscode.postMessage({ type: 'editing', on: false }); }
}
function armHealth(b) {                                      // first click: ask "Sure?" and say what it does; the panel does not redraw meanwhile
  armedBtn = b; b.dataset.armed = '1'; b.dataset.label = b.textContent; b.textContent = b.dataset.sure || 'Sure?'; b.classList.add('danger');
  const row = b.closest('li, .hsec'), box = row && row.querySelector('.himpact'); if (box && b.dataset.impact) { box.textContent = 'If you press Sure?: ' + b.dataset.impact; if (b.dataset.safe) { const k = document.createElement('b'); k.textContent = ' Safe: '; box.appendChild(k); box.appendChild(document.createTextNode(b.dataset.safe)); } box.hidden = false; }
  vscode.postMessage({ type: 'editing', on: true });
  armedTimer = setInterval(() => vscode.postMessage({ type: 'editing', on: true }), 60000);   // stays open until you click elsewhere, change tab or type; keeps the redraw pause alive
}
let openMenu = null;                                         // the one open popover { btn, menu }: the card's ⋯ menu or the autopilot chip menu
function closeMenu(refocus) {
  if (!openMenu) return; const o = openMenu; openMenu = null; o.menu.hidden = true; o.btn.setAttribute('aria-expanded', 'false');
  if (armedBtn && o.menu.contains(armedBtn)) disarm(); vscode.postMessage({ type: 'editing', on: false }); if (refocus) o.btn.focus();
}
function openMenuFor(btn) {
  if (openMenu && openMenu.btn === btn) { closeMenu(true); return; }
  closeMenu(false); const menu = document.getElementById(btn.getAttribute('aria-controls')); if (!menu) return;
  menu.hidden = false; menu.classList.remove('down'); btn.setAttribute('aria-expanded', 'true');
  const r = menu.getBoundingClientRect(), top = sc ? sc.getBoundingClientRect().top : 0; if (r.top < top + 2) menu.classList.add('down');   // no room above: open downwards
  openMenu = { btn, menu }; vscode.postMessage({ type: 'editing', on: true });
  const first = menu.querySelector('.mi:not(:disabled)'); if (first) first.focus();
}
document.addEventListener('keydown', e => {                 // Enter/Space on a trigger opens (native click); arrows move; Esc closes and returns focus; Tab leaves
  if (e.key === 'Escape' && !openMenu && e.target.closest && e.target.closest('.asc')) { const r = e.target.closest('[data-asiderow]'); if (r) { e.preventDefault(); asideCard(r.dataset.asiderow, false, true); return; } }
  if (e.key === 'Escape' && !openMenu && e.target.closest && (e.target.closest('.dtl') || e.target.closest('.dtog[aria-expanded="true"]'))) { if (dCloseFrom(e.target)) { e.preventDefault(); return; } }
  if (e.key === 'Escape' && e.target.closest && e.target.closest('.sheet') && !openMenu) { e.preventDefault(); sheetClose(e.target.closest('.sheet'), true); return; }
  if (e.key === 'Escape' && e.target.closest && (e.target.closest('.rail') || e.target.closest('[data-rdetail]')) && !openMenu) { const cd = e.target.closest('.card'); if (cd && cd.querySelector('.rs[aria-expanded="true"]')) { e.preventDefault(); stepClose(cd, true); return; } }
  if (e.key === 'ArrowDown' && e.target.closest && e.target.closest('[aria-haspopup="menu"]') && !openMenu) { e.preventDefault(); openMenuFor(e.target.closest('[aria-haspopup="menu"]')); return; }
  if (!openMenu) return;
  if (e.key === 'Escape') { e.preventDefault(); closeMenu(true); return; }
  if (e.key === 'Tab') { closeMenu(false); return; }
  if (!openMenu.menu.contains(document.activeElement)) return;
  const items = [...openMenu.menu.querySelectorAll('.mi:not(:disabled)')], i = items.indexOf(document.activeElement);
  const to = e.key === 'ArrowDown' ? (i + 1) % items.length : e.key === 'ArrowUp' ? (i - 1 + items.length) % items.length : e.key === 'Home' ? 0 : e.key === 'End' ? items.length - 1 : -1;
  if (to >= 0 && items.length) { e.preventDefault(); items[to].focus(); }
});
document.addEventListener('focusin', e => { if (e.target.closest('[data-askq]')) { disarm(); vscode.postMessage({ type: 'editing', on: true }); }
   if (e.target.closest('[data-nf]')) { disarm(); S.newFocus = true; S.newField = e.target.dataset.nf; vscode.setState(S); vscode.postMessage({ type: 'editing', on: true }); }
  if (e.target.closest('[data-f]')) { disarm(); S.focused = true; vscode.setState(S); vscode.postMessage({ type: 'editing', on: true }); }
  if (e.target.closest('.own') && S.own) { S.own.focus = true; vscode.setState(S); } });   // the panel does not redraw while you type
document.addEventListener('focusout', e => { if (e.target.closest('[data-askq]')) vscode.postMessage({ type: 'editing', on: false });
   if (e.target.closest('[data-nf]')) { S.newFocus = false; vscode.setState(S); vscode.postMessage({ type: 'editing', on: false }); }
  if (e.target.closest('[data-f]')) { S.focused = false; vscode.setState(S); vscode.postMessage({ type: 'editing', on: false }); }
  if (e.target.closest('.own') && S.own) { S.own.focus = false; vscode.setState(S); } });
document.addEventListener('click', e => {
  if (openMenu && !e.target.closest('.menu') && !e.target.closest('[aria-haspopup="menu"]')) closeMenu(false);
  const tbb = e.target.closest('[data-tb]'); if (tbb) { e.stopPropagation(); if (tbb.disabled) return; closeMenu(false); vscode.postMessage({ type: 'toolbox', op: tbb.dataset.tb, project: tbb.dataset.project || '', path: tbb.dataset.path || '' }); return; }
  const dsb = e.target.closest('[data-describe]'); if (dsb) { e.stopPropagation(); if (dsb.disabled) return; const op = dsb.dataset.describe;
    if (dsb.dataset.sure && armedBtn !== dsb) { disarm(); armHealth(dsb); return; }
    disarm(true); const sh0 = dsb.closest('.sheet'); const rd = sh0 && sh0.querySelector('input[type="radio"]:checked');
    vscode.postMessage(Object.assign({ type: 'describe', op, project: dsb.dataset.project || '' }, op === 'start' ? { mode: rd ? rd.value : 'short' } : {})); if (op === 'start' && sh0) sheetClose(sh0, true); return; }
  const asd = e.target.closest('[data-aside]'); if (asd) { e.stopPropagation(); if (asd.disabled) return; closeMenu(false); vscode.postMessage({ type: 'aside', op: asd.dataset.aside, project: asd.dataset.project || '' }); return; }
  const ast = e.target.closest('[data-asidetoggle]'); if (ast) { e.stopPropagation(); asideList(ast.getAttribute('aria-expanded') !== 'true'); return; }
  const aso = e.target.closest('[data-asideopen]'); if (aso) { e.stopPropagation(); asideCard(aso.dataset.asideopen, aso.getAttribute('aria-expanded') !== 'true'); return; }
  const asx = e.target.closest('[data-asidedismiss]'); if (asx) { e.stopPropagation(); vscode.postMessage({ type: 'aside', op: 'dismiss', project: asx.dataset.asidedismiss, ts: Number(asx.dataset.ts) || 0 }); const bn = asx.closest('.asnote'); if (bn) bn.remove(); return; }
  const dtg = e.target.closest('.dtog'); if (dtg) { e.stopPropagation(); dSet(dtg, dtg.getAttribute('aria-expanded') !== 'true'); return; }
  const dmo = e.target.closest('[data-dmore]'); if (dmo) { e.stopPropagation(); const on = dmo.getAttribute('aria-expanded') !== 'true', q = dmo.parentElement.querySelector('.dq'); if (q) q.classList.toggle('open', on); dmo.setAttribute('aria-expanded', on ? 'true' : 'false'); dmo.textContent = on ? dmo.dataset.less : dmo.dataset.more; return; }
  const dre = e.target.closest('[data-dretry]'); if (dre) { e.stopPropagation(); const box = dre.closest('.dload'); if (box) { box.textContent = ''; const lp = document.createElement('p'); lp.className = 'dnote'; lp.textContent = document.body.dataset.dloading || ''; box.appendChild(lp); } dAsk(dre.dataset.dretry); return; }
  const sh = e.target.closest('.sheet'); if (sh) { sheetClick(e, sh); return; }
  const sht = e.target.closest('[data-sheet]'); if (sht) { e.stopPropagation(); if (sht.disabled) return; closeMenu(false); sheetOpen(sht.dataset.project, sht.dataset.sheet, false); return; }
  const rsb = e.target.closest('.rs'); if (rsb) { e.stopPropagation(); stepOpen(rsb); return; }
  const t = e.target.closest('[data-tab]'); if (t) { disarm(); S.tab = t.dataset.tab; vscode.setState(S); show(); if (sc) sc.scrollTop = 0; return; }
  const rr = e.target.closest('.rrow'); if (rr) { S.scroll = 0; S.scrollKey = skey(); vscode.setState(S); vscode.postMessage({ type: 'rview', op: 'view', id: rr.dataset.rid }); return; }
  const rv = e.target.closest('[data-rv]'); if (rv) { if (rv.dataset.rv === 'back') { delete S.rvFocus; S.scroll = 0; vscode.setState(S); } vscode.postMessage({ type: 'rview', op: rv.dataset.rv, id: rv.dataset.id || '' }); return; }
  const rf = e.target.closest('[data-rf]'); if (rf) { RF()[rf.dataset.rf] = rf.dataset.val; vscode.setState(S); rfApply(); return; }
  const su = e.target.closest('[data-setup]'); if (su) { if (su.disabled) return; const op = su.dataset.setup; vscode.postMessage(Object.assign({ type: 'setup', op, id: su.dataset.id || '' }, op === 'prefs' ? { prefs: qsRead() } : {})); if (op === 'recheck') { su.disabled = true; su.textContent = su.dataset.busy || '…'; } return; }
  const nt = e.target.closest('[data-toggle="newbox"]'); if (nt) { disarm(); const nb = $(document, '[data-newbox]'); nb.hidden = !nb.hidden; nt.setAttribute('aria-expanded', nb.hidden ? 'false' : 'true');
    if (!nb.hidden) { S.newOpen = true; $(nb, '[data-nf="name"]').focus(); } else { closeNew(nb); } vscode.setState(S); return; }
  const nf = e.target.closest('[data-nform]'); if (nf) { const nb = nf.closest('[data-newbox]');
    if (nf.dataset.nform === 'create') { if (nf.disabled) return; const t = tidy($(nb, '[data-nf="name"]').value); if (!t) return;
      vscode.postMessage({ type: 'newproject', name: t, kind: $(nb, '[data-nf="kind"]').value, about: $(nb, '[data-nf="about"]').value.trim().slice(0, 140) }); }
    nb.hidden = true; closeNew(nb); $(document, '[data-toggle="newbox"]').setAttribute('aria-expanded', 'false'); vscode.setState(S); vscode.postMessage({ type: 'editing', on: false }); return; }
  const tg = e.target.closest('[data-toggle]'); if (tg) { const lst = tg.closest('.ilist'), box = $(lst, '[data-addbox]'); if (box) { box.hidden = !box.hidden; if (!box.hidden) { $(box, '[data-f="text"]').focus(); S.addOpen = lst.dataset.proj; } else { delete S.addOpen; delete S.focused; } vscode.setState(S); } return; }
  const fm = e.target.closest('[data-form]'); if (fm) {
    const box = fm.closest('[data-addbox]'), ta = $(box, '[data-f="text"]'), pr = $(box, '[data-f="project"]');
    if (fm.dataset.form !== 'cancel' && ta.value.trim()) vscode.postMessage({ type: 'idea', op: 'add', project: pr.value, text: ta.value.trim(), review: fm.dataset.form === 'addreview' });
    else if (fm.dataset.form !== 'cancel') { ta.focus(); return; }
    ta.value = ''; box.hidden = true; delete S.draft; delete S.addOpen; delete S.focused; delete S.caret; vscode.setState(S); vscode.postMessage({ type: 'editing', on: false }); return; }
  const pk = e.target.closest('[data-pick]'); if (pk) { if (!pk.disabled) openPick(pk); return; }
  const cl = e.target.closest('.hwhy.clamp'); if (cl) { cl.classList.toggle('open'); return; }
  const ho = e.target.closest('[data-hopen]'); if (ho) { e.stopPropagation(); closeMenu(false); S.tab = 'health'; S.focusItem = ho.dataset.hopen; vscode.setState(S); show(); const row = document.querySelector('[data-item="' + CSS.escape(ho.dataset.hopen) + '"]'); if (sc) sc.scrollTop = row ? Math.max(0, row.offsetTop - 8) : 0; return; }
  const lv = e.target.closest('[data-level]'); if (lv) {                       // gate-level pill: first click asks "Sure? Switch to …" in place, the second sends; the card does not open the chat
    if (armedBtn !== lv) { disarm(); armHealth(lv); return; }
    disarm(true); vscode.postMessage({ type: 'editing', on: false }); vscode.postMessage({ type: 'level', project: lv.dataset.level, to: lv.dataset.to }); return; }
  const mt = e.target.closest('[aria-haspopup="menu"]'); if (mt) { e.stopPropagation(); if (!mt.disabled) openMenuFor(mt); return; }
  const mf = e.target.closest('[data-menufor]'); if (mf) { e.stopPropagation(); const mb = mf.closest('.card') && mf.closest('.card').querySelector('.btn.more'); if (mb) openMenuFor(mb); return; }
  const nm = e.target.closest('[data-nmore]'); if (nm) { e.stopPropagation(); const box = nm.closest('.nsec'), on = nm.getAttribute('aria-expanded') !== 'true'; box.querySelectorAll('.xtra').forEach(r => { r.hidden = !on; }); nm.setAttribute('aria-expanded', on ? 'true' : 'false'); nm.textContent = on ? nm.dataset.less : nm.dataset.more; return; }
  const ak = e.target.closest('[data-ask]'); if (ak) {                       // Ask aside / Ask inbox: the page sends only the question text or an op; the extension types the commands and never presses Enter
    e.stopPropagation(); if (ak.disabled) return; closeMenu(false);
    const op = ak.dataset.ask, ac = ak.closest('[data-askcard]');
    if (op === 'clear' && ac) { const inp = $(ac, '[data-askq]'); inp.value = ''; delete S.askDraft; vscode.setState(S); askSync(ac); inp.focus(); }
    else if (op === 'type' && ac) { const inp = $(ac, '[data-askq]'); if (!inp.value.trim()) return; const ms = $(ac, '[data-askmodel]'); vscode.postMessage(ms ? { type: 'ask', op: 'type', q: inp.value, model: ms.value } : { type: 'ask', op: 'type', q: inp.value }); inp.value = ''; delete S.askDraft; vscode.setState(S); askSync(ac); }
    else vscode.postMessage({ type: 'ask', op, project: ak.dataset.project || '' });
    return; }
  const da = e.target.closest('[data-act]'); if (da) {                       // primary button, menu items, verdict link, autopilot items; the card does not open the chat
    e.stopPropagation(); if (da.disabled) return;

    if (da.dataset.act === 'decide') { closeMenu(false); dOpen(da.dataset.project); return; }
    if (da.dataset.act === 'dclose') { const b = da.closest('[data-decide]'); if (b) b.hidden = true; delete S.decide; vscode.setState(S); return; }
    if (da.dataset.sure && armedBtn !== da) { disarm(); armHealth(da); return; }
    disarm(true); closeMenu(false); vscode.postMessage({ type: 'editing', on: false });
    const act = da.dataset.act, card = da.closest('[data-dir]'), dir = da.dataset.pdir || (card ? card.dataset.dir : '');
    if (act === 'relaunch') vscode.postMessage({ type: 'relaunch', dir, project: da.dataset.project || '' });
    else if (act === 'open' || act === 'newwin') vscode.postMessage({ type: 'open', dir, newWindow: act === 'newwin' || e.metaKey || e.ctrlKey });
    else { vscode.postMessage({ type: 'act', act, project: da.dataset.project || '', dir, cr: da.dataset.cr || '', to: da.dataset.to || '', report: da.dataset.report || '', verb: da.dataset.verb || '' }); if (act === 'plan') planHint(da.dataset.project || ''); }
    return; }
  const ac = e.target.closest('[data-activate]'); if (ac) { e.stopPropagation(); vscode.postMessage({ type: 'activateAgent', project: ac.dataset.activate }); return; }
  const hf = e.target.closest('[data-handoff]'); if (hf) {                      // Handoff + fresh chat: first click asks "Sure?" in place, the second sends; the card does not open the chat
    e.stopPropagation(); if (hf.disabled) return;
    if (hf.dataset.handoff === 'ask' && armedBtn !== hf) { disarm(); armHealth(hf); return; }
    disarm(true); closeMenu(false); vscode.postMessage({ type: 'editing', on: false }); vscode.postMessage({ type: 'handoff', step: hf.dataset.handoff, project: hf.dataset.project || '' }); return; }
  const hb = e.target.closest('[data-health]'); if (hb && !hb.disabled) {
    if (hb.dataset.confirm === '1' && armedBtn !== hb) { disarm(); armHealth(hb); return; }
    disarm(true); vscode.postMessage({ type: 'editing', on: false }); vscode.postMessage({ type: 'health', op: hb.dataset.op, id: hb.dataset.id || '', project: hb.dataset.project || '' }); return; }
  if (armedBtn) disarm();                                    // a click anywhere else cancels the question
  const dr = e.target.closest('[data-op="drop"]');
  if (dr && !dr.disabled && !dropArmed.has(dr)) {   // drop asks again, in place, instead of a pop-up
    dropArmed.add(dr); dr.dataset.armed = '1'; dr.dataset.label = dr.textContent; dr.textContent = 'Sure? Drop it'; dr.classList.add('danger');
    setTimeout(() => { if (dropArmed.has(dr)) { dropArmed.delete(dr); dr.dataset.armed = ''; dr.textContent = dr.dataset.label; dr.classList.remove('danger'); } }, 4000); return; }
  const ib = e.target.closest('[data-idea]'); if (ib) { if (!ib.disabled) vscode.postMessage({ type: 'idea', op: ib.dataset.op, project: ib.dataset.project || '', id: ib.dataset.id || '', to: ib.dataset.to || '' }); return; }
  const cm = e.target.closest('[data-cmd]'); if (cm) { vscode.postMessage({ type: 'cmd', name: cm.dataset.cmd }); return; }
  const rl = e.target.closest('[data-relaunch]'); if (rl) { e.stopPropagation(); closeMenu(false); vscode.postMessage({ type: 'relaunch', dir: rl.dataset.relaunch, project: rl.dataset.project || '' }); return; }
  const ci = e.target.closest('[data-ci]'); if (ci) { e.stopPropagation(); vscode.postMessage({ type: 'ci', url: ci.dataset.ci }); return; }
  if (e.target.closest('[data-away]')) { vscode.postMessage({ type: 'away' }); return; }
  if (e.target.closest('[data-guard]')) { vscode.postMessage({ type: 'guard' }); return; }
  if (e.target.closest('.decide, .apwait, .planhint, .rdetail, .cband, .cwait, .cban, .dtl')) return;
  const card = e.target.closest('[data-dir]'); if (card) vscode.postMessage({ type: 'open', dir: card.dataset.dir, newWindow: e.metaKey || e.ctrlKey });
});
if (S.pick && S.tab === 'ideas') { const b = [...document.querySelectorAll('.ilist:not([hidden]) [data-pick]')].find(x => x.dataset.pick === S.pick.op && x.dataset.id === S.pick.id && x.dataset.project === S.pick.project); if (b) { restoring = true; openPick(b); restoring = false; } }
document.addEventListener('keydown', e => { if (e.key === 'Enter' && e.target.closest('[data-askq]')) { const go = $(e.target.closest('[data-askcard]'), '[data-askgo]'); if (go && !go.disabled) go.click(); return; }
  if (e.key === 'Enter' && e.target.closest('[data-nf="name"]')) { const go = $(document, '[data-nform="create"]'); if (go && !go.disabled) go.click(); return; }
  if (e.key === 'Enter' && !e.target.closest('button, input, select, textarea, a, summary, .sheet, .decide')) { const el2 = e.target.closest('[data-dir]'); if (el2) vscode.postMessage({ type: 'open', dir: el2.dataset.dir }); } });
</script></body></html>`;
}

// The public entry: the data is shape-checked first (sane.js), and if drawing still fails the page is drawn from empty data, never an exception into the webview provider.
function html(data, opts) {
  try { return render(SANE.sane(data), opts); } catch (e) { return render(SANE.sane({}), opts); }
}
module.exports = { html, fmt };
