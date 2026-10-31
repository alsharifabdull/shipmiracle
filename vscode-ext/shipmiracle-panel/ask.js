// Ask aside (F3) and Ask inbox (F4): the pure parts. Pure Node, no vscode: the extension and tests/ext_ask_test.js share it.
// The panel never runs `shipm ask` (it spends quota; the CLI is owner-only): it TYPES the command into the owner's terminal WITHOUT Enter. Everything the page sends is checked again here.
// Constants mirror shipmiracle/ask.py (MAX_Q, DAILY_CAP, NOTE_RE); tests/ext_ask_test.js fails when they drift.
const fs = require('fs');
const path = require('path');

const MAX_Q = 2000, DAILY_CAP = 20;   // DAILY_CAP is only the DEFAULT of the config key ask.daily_limit; the panel shows the limit the CLI reports (ask.limit)
const NOTE_RE = /^[0-9]{4}-[0-9]{2}-[0-9]{2}-[a-z0-9-]{1,60}\.md$/;
const ASIDE_TEXT = '/btw ';                                   // the only text Ask aside ever sends to a chat; Enter is never pressed

// -> { ok: true, value } | { ok: false, why: <key in strings.ask> }. One line; a leading '-' would be read as an option by the CLI.
// Format characters (bidi marks, zero-width joiners) are removed like the CLI does; a real control character or a line break is refused, never silently changed.
function checkQuestion(q, strip = true) {
  if (typeof q !== 'string') return { ok: false, why: 'empty' };
  if (/[\r\n\u2028\u2029]/.test(q)) return { ok: false, why: 'newline' };
  if (/\p{Cc}/u.test(q)) return { ok: false, why: 'control' };
  const v = (strip ? q.replace(/\p{Cf}/gu, '') : q).trim();
  if (!v) return { ok: false, why: 'empty' };
  if (Array.from(v).length > MAX_Q) return { ok: false, why: 'tooLong' };
  if (v.startsWith('-')) return { ok: false, why: 'dash' };
  return { ok: true, value: v };
}
const MODELS = ['opus', 'sonnet', 'haiku'];
// model: only added when the CLI supports --model (the panel's data says ask.model_supported); otherwise the CLI's own config key ask.model decides.
const inboxArgv = (shipm, q, model) => { const c = checkQuestion(q); if (!c.ok) throw new Error(c.why); if (model === undefined || model === null || model === '') return [shipm, 'ask', '--inbox', c.value]; if (!MODELS.includes(model)) throw new Error('badModel'); return [shipm, 'ask', '--inbox', '--model', model, c.value]; };
const promoteArgv = (shipm, note) => { const n = path.basename(String(note || '')); if (!NOTE_RE.test(n) || n !== String(note)) throw new Error('badNote'); return [shipm, 'ask', 'promote', n]; };
const remoteFixArgv = shipm => [shipm, 'init', '--step', 'remote-control'];
const remoteUndoArgv = shipm => [shipm, 'init', '--undo', 'remote-control'];

const real = p => { try { return fs.realpathSync(p); } catch (e) { return ''; } };
const isLink = p => { try { return fs.lstatSync(p).isSymbolicLink(); } catch (e) { return true; } };
// The "Open" guard for the last note: exactly <askDir>/docs/notes/<YYYY-MM-DD-slug>.md. Neither folder on the way, nor the file, may be a symlink; the real path must stay inside the real notes folder.
// `rel` comes from the panel's own data (shipm report panel), never from the page. -> { ok, file } | { ok: false, why }
function guardNote(askDir, rel) {
  if (typeof askDir !== 'string' || !askDir || typeof rel !== 'string' || !rel || rel.includes('\0')) return { ok: false, why: 'not a note path' };
  const parts = rel.split('/');
  if (parts.length !== 3 || parts[0] !== 'docs' || parts[1] !== 'notes' || !NOTE_RE.test(parts[2])) return { ok: false, why: 'not a note path' };
  const root = real(askDir); if (!root) return { ok: false, why: 'no ask folder' };
  const docs = path.join(askDir, 'docs'), notes = path.join(docs, 'notes'), file = path.join(notes, parts[2]);
  if (isLink(docs) || isLink(notes)) return { ok: false, why: 'a folder on the way is a symlink' };
  let st; try { st = fs.lstatSync(file); } catch (e) { return { ok: false, why: 'not found' }; }
  if (st.isSymbolicLink() || !st.isFile()) return { ok: false, why: 'not a regular file' };
  const full = real(file), rn = real(notes);
  if (!full || !rn || !(full === path.join(rn, parts[2]))) return { ok: false, why: 'outside the notes folder' };
  return { ok: true, file: full };
}
// The folder of the ask project from the panel's data: only a project whose data says inbox:true, and only a plain absolute path.
const inboxProject = projects => (projects || []).find(p => p && p.ask && p.ask.inbox === true && typeof p.dir === 'string' && path.isAbsolute(p.dir)) || null;

module.exports = { MODELS, MAX_Q, DAILY_CAP, NOTE_RE, ASIDE_TEXT, checkQuestion, inboxArgv, promoteArgv, remoteFixArgv, remoteUndoArgv, guardNote, inboxProject };
