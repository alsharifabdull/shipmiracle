// Reports tab data and the two path guards (UX spec docs/plans/2026-10-20-panel-v3-ux.md section 6). Pure Node, no dependencies, no vscode: the extension and the tests share it.
// Read-only: it never writes. The index is <state>/v1/reports/index.json (shipmiracle/report/write.py): {"v":1,"items":[...]} newest first. Anything unexpected is an empty list, never a crash.
//   kind "stage"  -> <state>/v1/reports/<12 hex>/<name>.md      (private, 30 days)
//   kind "digest" -> <state>/v1/digest/YYYY-MM-DD.md            (private, 30 days)
//   kind "cr"     -> <project>/docs/reports/<name>.md           (in the repo)
// The page only ever sends an item id. The extension finds the item in the index again and guards its path again, because the index lives in a folder a chat can write to.
const fs = require('fs');
const path = require('path');

const MAX_INDEX = 1 << 20;            // 1 MB (500 items are about 150 KB)
const MAX_ITEMS = 500;
const MAX_TEXT = 256 * 1024;          // one report
const VERDICTS = ['PASS', 'FAIL', 'BLOCKED', 'NOT TESTED'];
const KINDS = ['stage', 'cr', 'digest'];

const CTRL = /[\u0000-\u001f\u007f-\u009f\u2028\u2029]+/g;
const one = (v, n) => (typeof v === 'string' ? v : '').replace(CTRL, ' ').trim().slice(0, n);

// Regular files only, at most `max` bytes (a FIFO, /dev/zero or a huge file must not hang the panel). -> { ok, text, big }
function readCapped(file, max, follow = false) {   // follow: owner-controlled locations (state, config) may be symlinked dotfiles; project files never are followed
  let fd = -1;
  try {
    fd = fs.openSync(file, fs.constants.O_RDONLY | fs.constants.O_NONBLOCK | (follow ? 0 : fs.constants.O_NOFOLLOW || 0));
    const st = fs.fstatSync(fd);
    if (!st.isFile()) return { ok: false, text: '', big: false };
    if (st.size > max) return { ok: false, text: '', big: true };
    const buf = Buffer.alloc(Math.min(st.size, max)); const n = fs.readSync(fd, buf, 0, buf.length, 0);
    return { ok: true, text: buf.toString('utf8', 0, n), buf: buf.subarray(0, n), big: false };
  } catch (e) { return { ok: false, text: '', big: false }; } finally { if (fd >= 0) try { fs.closeSync(fd); } catch (e) { /* closed */ } }
}

// One index entry -> the fields the panel uses, or null. Nothing is trusted: strings are cut and cleaned, enums are checked.
function cleanItem(x) {
  if (!x || typeof x !== 'object' || Array.isArray(x)) return null;
  const id = one(x.id, 120), kind = typeof x.kind === 'string' ? x.kind : '';
  if (!/^[A-Za-z0-9._-]{1,120}$/.test(id) || !KINDS.includes(kind)) return null;
  const ts = Number(x.ts); const v = typeof x.verdict === 'string' ? x.verdict.toUpperCase() : '';
  return { id, kind, project: one(x.project, 100), cr: one(x.cr, 20), stage: one(x.stage, 20), verdict: VERDICTS.includes(v) ? v : 'NOT TESTED', ts: Number.isFinite(ts) && ts > 0 ? Math.floor(ts) : 0,
    title: one(x.title, 160), sub: one(x.sub, 200), path: typeof x.path === 'string' && x.path.length <= 1000 && !x.path.includes('\0') ? x.path : '', private: x.private === true };
}
// -> { items, status: 'ok' | 'missing' | 'bad' }. 'bad' = unreadable, too big or malformed: the page says so and offers Retry; the list is empty.
function readIndex(stateDir) {
  const f = path.join(stateDir, 'v1', 'reports', 'index.json');
  if (!fs.existsSync(f)) return { items: [], status: 'missing' };
  const r = readCapped(f, MAX_INDEX); if (!r.ok) return { items: [], status: 'bad' };
  let j; try { j = JSON.parse(r.text); } catch (e) { return { items: [], status: 'bad' }; }
  if (!j || typeof j !== 'object' || !Array.isArray(j.items)) return { items: [], status: 'bad' };
  const items = []; const seen = new Set();
  for (const x of j.items.slice(0, MAX_ITEMS)) { const c = cleanItem(x); if (c && !seen.has(c.id)) { seen.add(c.id); items.push(c); } }
  return { items, status: 'ok' };
}

// ---- guards. All return { ok: true, file } (the real path of a regular file) or { ok: false, why }.
const real = p => { try { return fs.realpathSync(p); } catch (e) { return ''; } };
const inside = (child, root) => !!root && !!child && (child === root || child.startsWith(root.endsWith(path.sep) ? root : root + path.sep));
function regular(file) { try { const st = fs.lstatSync(file); return st.isFile() && !st.isSymbolicLink(); } catch (e) { return false; } }

// A report inside the state folder: exactly <state>/v1/reports/<12 hex>/<name>.md (stage) or <state>/v1/digest/<YYYY-MM-DD>.md (digest). Nothing else in the state folder can be opened.
function guardState(stateDir, kind, file) {
  if (typeof file !== 'string' || !file || file.includes('\0') || !path.isAbsolute(file)) return { ok: false, why: 'not a report path' };
  const stage = kind === 'stage', digest = kind === 'digest';
  if (!stage && !digest) return { ok: false, why: 'not a state report' };
  const root = real(path.join(stateDir, 'v1', stage ? 'reports' : 'digest')); if (!root) return { ok: false, why: 'no reports folder' };
  if (!regular(file)) return { ok: false, why: 'not a regular file' };               // a symlink as the file itself is refused, even one that points inside
  const full = real(file); if (!inside(full, root) || full === root) return { ok: false, why: 'outside the reports folder' };
  const rel = path.relative(root, full).split(path.sep);
  if (stage ? !(rel.length === 2 && /^[0-9a-f]{12}$/.test(rel[0]) && /^[A-Za-z0-9._-]+\.md$/.test(rel[1])) : !(rel.length === 1 && /^\d{4}-\d\d-\d\d\.md$/.test(rel[0]))) return { ok: false, why: 'not a report file' };
  return { ok: true, file: full };
}
// A report inside a project folder (the existing openreport rule, tightened to .md): the real path must stay inside the project's real folder.
function guardProject(projectDir, file) {
  if (typeof file !== 'string' || !file || file.includes('\0') || typeof projectDir !== 'string' || !projectDir) return { ok: false, why: 'not a report path' };
  const root = real(projectDir); if (!root) return { ok: false, why: 'no project folder' };
  const cand = path.resolve(projectDir, file); if (!/\.md$/i.test(cand)) return { ok: false, why: 'not a Markdown report' };
  const full = real(cand); if (!full) return { ok: false, why: 'not found' };
  if (!inside(full, root) || full === root) return { ok: false, why: 'outside the project folder' };
  try { if (!fs.statSync(full).isFile()) return { ok: false, why: 'not a regular file' }; } catch (e) { return { ok: false, why: 'not found' }; }
  return { ok: true, file: full };
}
// Any path the card's "report ›" link may carry: a relative path inside the project, or an absolute path under the two state report folders.
function guardAny(stateDir, projectDir, file) {
  if (typeof file === 'string' && path.isAbsolute(file)) {
    const s = guardState(stateDir, 'stage', file); if (s.ok) return s;
    const d = guardState(stateDir, 'digest', file); if (d.ok) return d;
    return guardProject(projectDir, file);               // an absolute path is allowed only when it is inside the project
  }
  return guardProject(projectDir, file);
}
// The guard that matches the item's kind. projectDirOf(name) -> the project's folder from the panel's own data (never from the index).
function guardItem(stateDir, projectDirOf, item) {
  if (!item) return { ok: false, why: 'not in the index' };
  if (item.kind === 'cr') { const dir = projectDirOf(item.project); return dir ? guardProject(dir, item.path) : { ok: false, why: 'unknown project' }; }
  return guardState(stateDir, item.kind, item.path);
}
// Find the item again in the index and read its text. -> { ok, item, file, text } | { ok: false, why, item? }
function load(stateDir, projectDirOf, id) {
  const idx = readIndex(stateDir); if (idx.status === 'bad') return { ok: false, why: 'The report list could not be read.' };
  const item = idx.items.find(x => x.id === id); if (!item) return { ok: false, why: 'That report is not in the list any more.' };
  const g = guardItem(stateDir, projectDirOf, item); if (!g.ok) return { ok: false, why: 'Not opened: ' + g.why + '.', item };
  const r = readCapped(g.file, MAX_TEXT);
  if (!r.ok) return { ok: false, why: r.big ? 'That report is too large to show here. Use Open file.' : 'Could not read that report.', item, file: g.file };
  return { ok: true, item, file: g.file, text: r.text };
}

// Every read of a file the panel did not write itself (a project's STATUS.md, CLAUDE.md, FEATURE-IDEAS.md, state files, config) goes through here: never follows a symlink, never blocks on a FIFO,
// never reads more than `max` bytes (a clone can hold docs/STATUS.md -> /dev/zero). -> the text, or '' when it is not a small regular file.
const readText = (file, max = 262144) => { const r = readCapped(file, max); return r.ok ? r.text : ''; };
// JSON files are the owner's (state folder, config): a symlinked dotfile is fine, a device or FIFO is not.
const readJson = (file, max = 1 << 20) => { const r = readCapped(file, max, true); if (!r.ok) return null; try { return JSON.parse(r.text); } catch (e) { return null; } };
module.exports = { readText, readJson, MAX_INDEX, MAX_TEXT, VERDICTS, readCapped, cleanItem, readIndex, guardState, guardProject, guardAny, guardItem, load };
