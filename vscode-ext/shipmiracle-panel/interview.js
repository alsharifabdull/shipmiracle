// F6 mirror of `shipm playbook interview` (UX addendum 2d-2f): reads the two files the CLI writes inside the project, read-only, size-capped, never followed through a symlink:
//   .shipmiracle/playbook.interview.json   progress (untrusted data, only the fields below are used, every text cleaned and cut)
//   .shipmiracle/playbook.draft.md         the draft (text only, never executed; nine labelled sections + Assumed)
// Pure Node, no vscode. A status "asking" whose process (pid in the file) is gone is shown as paused: the terminal was closed.
const fs = require('fs');
const path = require('path');
const REPORTS = require('./reports');
const DETAIL = require('./detail');

const PROGRESS = 'playbook.interview.json', DRAFT = 'playbook.draft.md';
const MAX_PROGRESS = 256 * 1024, MAX_DRAFT = 40 * 1024;
const LABELS = ['Work', 'Inputs', 'Outputs', 'Tools', 'Risks', 'Who approves', 'Definition of done', 'Never allowed', 'Assumed'];
const T = (v, n) => DETAIL.sanitize(typeof v === 'string' ? v : '', n);
const int = (v, max) => Number.isInteger(v) && v >= 0 ? Math.min(v, max) : 0;
const alive = pid => { if (!Number.isInteger(pid) || pid <= 0) return false; try { process.kill(pid, 0); return true; } catch (e) { return !!e && e.code === 'EPERM'; } };

// -> null (no interview) | { status, mode, n, total, question: {text, recommended}|null, assumed: [text], prototype: [text], updated }
function readProgress(dir) {
  const r = REPORTS.readCapped(path.join(dir, '.shipmiracle', PROGRESS), MAX_PROGRESS); if (!r.ok) return null;
  let j; try { j = JSON.parse(r.text); } catch (e) { return null; }
  if (!j || typeof j !== 'object' || j.v !== 1 || !['asking', 'paused', 'draft', 'done', 'error'].includes(j.status) || !['short', 'long'].includes(j.mode)) return null;
  const q = j.question && typeof j.question === 'object' ? { text: T(j.question.text, 200), recommended: T(j.question.recommended, 200) } : null;
  const list = (a, k) => (Array.isArray(a) ? a : []).slice(0, 12).map(x => T(x && typeof x === 'object' ? x[k] : '', 80)).filter(Boolean);
  let status = j.status;
  if (status === 'asking' && !alive(j.pid)) status = 'paused';                       // the terminal closed: the file stopped updating and nobody is asking
  return { status, mode: j.mode, n: int(j.n, 99), total: int(j.total, 99), question: q && q.text ? q : null, assumed: list(j.assumed, 'text'), prototype: list(j.prototype, 'text'), updated: int(j.updated, 4e10) };
}
// -> { ok: true, rows: [{label, text}] } | { ok: false }. All nine labelled sections must be present; a link or HTML in the text stays text (escaped by the page).
function readDraft(dir) {
  const r = REPORTS.readCapped(path.join(dir, '.shipmiracle', DRAFT), MAX_DRAFT); if (!r.ok) return { ok: false };
  const secs = {}; let cur = null;
  for (const raw of r.text.split('\n')) {
    const m = /^##\s+(.+?)\s*$/.exec(raw); if (m) { cur = m[1]; secs[cur] = secs[cur] || []; continue; }
    if (cur && /^\s*[-*]\s+/.test(raw)) secs[cur].push(raw.replace(/^\s*[-*]\s+/, ''));
  }
  if (!LABELS.every(l => Object.prototype.hasOwnProperty.call(secs, l))) return { ok: false };
  return { ok: true, rows: LABELS.map(l => ({ label: l, text: T(secs[l].join(' · '), 200) })) };
}
const draftFile = dir => { const f = path.join(dir, '.shipmiracle', DRAFT); try { const st = fs.lstatSync(f); return st.isFile() && !st.isSymbolicLink() ? f : ''; } catch (e) { return ''; } };
// everything the page needs for one project, or null
function mirrorOf(dir, cliStatus) {
  if (!cliStatus || cliStatus === 'done') return null;
  const p = readProgress(dir); if (!p) return cliStatus === 'error' ? { status: 'error' } : null;
  if (p.status === 'draft') { const d = readDraft(dir); return { ...p, draftOk: d.ok, rows: d.ok ? d.rows : [] }; }
  return p;
}
module.exports = { LABELS, readProgress, readDraft, draftFile, mirrorOf, alive };
