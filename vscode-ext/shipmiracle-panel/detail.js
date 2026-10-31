// Details of one project card (F9, UX addendum section 5): the last thing the chat said, the newest report, the STATUS line. Pure Node, no vscode import, read-only.
// Called ONLY while a card is expanded (the page asks with {type:'detail', project}); the answer is cached 15 s per project. Everything it returns is plain text: control and bidi
// characters are removed (the zero-width joiners U+200C / U+200D stay: Persian and emoji need them), every field is capped, nothing is markup. Nothing here writes a file.
//   chat   : the last assistant text (first 280 characters, cut at a word) + the name of the latest tool call, read from the LAST 128 KB of the newest session file only
//   report : the newest report of the project from the reports index (the existing guards in reports.js decide whether its file may be read)
//   status : the `Updated:` line of docs/STATUS.md (cut at 120) and the file's change time
const fs = require('fs');
const path = require('path');
const REPORTS = require('./reports');

const MAX_TAIL = 128 * 1024;                 // bytes read from the end of a session file
const MAX_FILE = 512 * 1024 * 1024;          // a session file larger than this is refused (it is not a conversation)
const CHAT_CHARS = 280, NOTE_CHARS = 120, TITLE_CHARS = 160, SUMMARY_CHARS = 300;
const TTL_MS = 15000;

// ---- text hygiene ------------------------------------------------------------------------------------------------------------------------------
// Control characters (Cc), format characters (Cf: bidi marks and overrides, zero-width joiners, BOM), line/paragraph separators and unassigned/private-use are removed;
// every run of white space becomes one space. A hostile chat can write anything, so nothing else about the text is trusted either (the panel escapes it again).
const ANSI = /\x1b\[[0-?]{0,64}[ -\/]{0,16}[@-~]|\x9b[0-?]{0,64}[ -\/]{0,16}[@-~]|\x1b\][^\x07\x1b]{0,2000}(?:\x07|\x1b\\)|\x1b[ -\/]{0,4}[0-~]/g;      // CSI, OSC (to BEL or ST) and two-character escapes, every part bounded: a terminal colour code must not leave its parameters behind
const clean = s => String(s == null ? '' : s).replace(ANSI, '').replace(/[\p{Cc}\p{Cf}\p{Co}\p{Cn}\u2028\u2029]/gu, m => (m === '\n' || m === '\t' || m === '\r' ? ' ' : m === '\u200c' || m === '\u200d' ? m : '')).replace(/\s+/g, ' ').trim();
const { redact } = require('./redact');                  // best-effort masking of secret-shaped text (linear passes, see redact.js)
const cps = s => Array.from(s);
// The first `n` code points; when the text is longer, cut at the last space inside the limit (a word boundary) and add an ellipsis. No space at all: hard cut.
function cutWord(text, n) {
  const a = cps(String(text)); if (a.length <= n) return a.join('');
  let cut = a.slice(0, n);
  if (a[n] !== ' ') { const sp = cut.lastIndexOf(' '); if (sp > 0) cut = cut.slice(0, sp); }
  return cut.join('').replace(/\s+$/, '') + '…';
}
// The text is cut to a bound BEFORE the heavy passes (display limit x 4 + 2000, then back to the last space so a secret cut in half is not left behind), then masked, then cut to the display limit.
// A text that was cut shows an ellipsis even when masking made it shorter than the limit.
function sanitize(s, n) {
  let t = clean(String(s == null ? '' : s).slice(0, n * 8 + 4000)), cutIn = false;
  const lim = n * 4 + 2000;
  if (t.length > lim) { t = t.slice(0, lim); const sp = t.lastIndexOf(' '); if (sp > lim - 400) t = t.slice(0, sp); cutIn = true; }
  const r = cutWord(redact(t), n);
  return cutIn && !r.endsWith('…') ? r + '…' : r;
}
const toolName = s => (typeof s === 'string' && /^[A-Za-z0-9_:.-]{1,60}$/.test(s) ? s : '');

// ---- finding and reading the transcript ----------------------------------------------------------------------------------------------------------
// The folders Claude Code keeps a project's sessions in: the project's own folder name (path with every non-alphanumeric turned into '-') plus any older path it lived at.
function claudeDirs(root, dir, name) {
  const own = dir.replace(/[^A-Za-z0-9]/g, '-'), tail = '-' + name.replace(/[^A-Za-z0-9]/g, '-');
  let all = []; try { all = fs.readdirSync(root); } catch (e) { /* none */ }
  return [...new Set([own, ...all.filter(k => k.endsWith(tail) && !k.includes('-tmp-'))])].map(k => path.join(root, k));
}
// The newest session file (regular file, not a link) of the project, or null.
function newestSession(root, dir, name) {
  let best = null;
  for (const d of claudeDirs(root, dir, name)) {
    let files = []; try { files = fs.readdirSync(d).filter(f => f.endsWith('.jsonl')); } catch (e) { continue; }
    for (const f of files) { try { const full = path.join(d, f), st = fs.lstatSync(full); if (st.isFile() && !st.isSymbolicLink() && (!best || st.mtimeMs > best.mtimeMs)) best = { file: full, mtimeMs: st.mtimeMs }; } catch (e) { /* gone */ } }
  }
  return best;
}
// The last <= 128 KB of a regular file. Refuses a symlink, a FIFO or device, and a file over MAX_FILE. -> { ok, buf, partial, mtimeMs } | { ok: false, why }
function tail(file, max = MAX_TAIL) {
  let fd = -1;
  try {
    fd = fs.openSync(file, fs.constants.O_RDONLY | fs.constants.O_NONBLOCK | (fs.constants.O_NOFOLLOW || 0));
    const st = fs.fstatSync(fd);
    if (!st.isFile()) return { ok: false, why: 'not a regular file' };
    if (st.size > MAX_FILE) return { ok: false, why: 'too large' };
    const len = Math.min(st.size, max), buf = Buffer.alloc(len);
    const n = len ? fs.readSync(fd, buf, 0, len, st.size - len) : 0;
    return { ok: true, buf: buf.subarray(0, n), partial: st.size > len, mtimeMs: st.mtimeMs };
  } catch (e) { return { ok: false, why: 'unreadable' }; } finally { if (fd >= 0) try { fs.closeSync(fd); } catch (e) { /* closed */ } }
}
// The newest assistant text and the newest tool name in the tail. Lines of sub-agents (isSidechain) and the user's lines are never used.
// Transcript line shape (Claude Code): {"type":"assistant","timestamp":ISO,"message":{"role":"assistant","content":[{"type":"text","text":...},{"type":"tool_use","name":"Bash","input":{...}}]}}
// A tool's input is never read. -> { text, ts, tool }
function lastFromTail(buf, partial, fallbackMs) {
  let lines = buf.toString('utf8').split('\n'); if (partial) lines.shift();         // the first line of a tail may be cut in the middle
  let text = '', ts = 0, tool = '';
  for (let i = lines.length - 1; i >= 0 && !(text && tool); i--) {
    const l = lines[i]; if (!l || l.indexOf('"assistant"') < 0) continue;
    let j; try { j = JSON.parse(l); } catch (e) { continue; }
    if (!j || typeof j !== 'object' || j.type !== 'assistant' || j.isSidechain === true) continue;
    const m = j.message, c = m && Array.isArray(m.content) ? m.content : null; if (!c) continue;
    for (let k = c.length - 1; k >= 0; k--) {
      const b = c[k]; if (!b || typeof b !== 'object') continue;
      if (!tool && b.type === 'tool_use') tool = toolName(b.name);
      if (!text && b.type === 'text' && typeof b.text === 'string' && clean(b.text)) {
        text = sanitize(b.text, CHAT_CHARS); const t = Date.parse(j.timestamp); ts = Number.isFinite(t) ? t : fallbackMs;
      }
    }
  }
  return { text, ts: Math.floor(ts / 1000), tool };
}
// -> { state: 'ok', text, ts, tool } | { state: 'none' } (no session or no assistant message yet: the block is omitted) | { state: 'error' }
function chatExcerpt(root, dir, name) {
  const s = newestSession(root, dir, name); if (!s) return { state: 'none' };
  const t = tail(s.file); if (!t.ok) return { state: 'error' };
  const r = lastFromTail(t.buf, t.partial, s.mtimeMs);
  return r.text ? { state: 'ok', text: r.text, ts: r.ts, tool: r.tool } : { state: 'none' };
}

// ---- report and STATUS -------------------------------------------------------------------------------------------------------------------------------
// The first lines of a report as plain text: front matter, headings, rules and empty lines are skipped; markdown marks and link targets are dropped.
function summaryOf(text) {
  const out = []; let fm = false, first = true;
  for (const raw of String(text).split('\n')) {
    const l = raw.trim();
    if (first && l === '---') { fm = true; first = false; continue; } first = false;
    if (fm) { if (l === '---') fm = false; continue; }
    if (!l || /^(#{1,6}\s|[-*_]{3,}$|```|\|)/.test(l)) continue;
    const t = clean(l.slice(0, 4000).replace(/^([-*+]|\d+[.)])\s+/, '').replace(/!?\[([^\]]*)\]\([^)]*\)/g, '$1').replace(/[*_`~>]/g, ''));
    if (t) out.push(t);
    if (out.length >= 3) break;
  }
  return sanitize(out.join(' '), SUMMARY_CHARS);
}
// The newest report of the project in the index. projectDirOf(name) -> the project's folder from the panel's own data. -> { id, verdict, title, summary, ts } | null
function newestReport(stateDir, name, projectDirOf) {
  let idx; try { idx = REPORTS.readIndex(stateDir); } catch (e) { return null; }
  const items = idx.items.filter(x => x.project === name && x.ts > 0).sort((a, b) => b.ts - a.ts);
  for (const it of items.slice(0, 3)) {                                              // the newest that can be read; a report that cannot be read is never shown half read
    const r = REPORTS.load(stateDir, projectDirOf, it.id); if (!r.ok) continue;
    return { id: it.id, verdict: it.verdict, title: sanitize(it.title || it.id, TITLE_CHARS), summary: summaryOf(r.text), ts: it.ts };
  }
  return null;
}
// docs/STATUS.md: the `Updated:` line (without its prefix) and when the file last changed. -> { note, ts } | null
function statusUpdated(dir) {
  for (const f of ['docs/STATUS.md', 'Docs/STATUS.md']) {
    const file = path.join(dir, f); let st; try { st = fs.lstatSync(file); } catch (e) { continue; }
    if (!st.isFile() || st.isSymbolicLink()) continue;
    const t = REPORTS.readText(file); if (!t) continue;
    const m = t.match(/^Updated:[ \t]*(.*)$/m);
    return { note: m ? sanitize(m[1], NOTE_CHARS) : '', ts: Math.floor(st.mtimeMs / 1000) };
  }
  return null;
}

// ---- the whole answer for one project, cached ----------------------------------------------------------------------------------------------------
// opts: { stateDir, claudeRoot, projectDirOf, ttl, now }. read(p, excerpt) -> { at, chat, report, status }; chat.state is 'hidden' (and no transcript is read) when excerpt is false.
function create(opts) {
  const ttl = opts.ttl != null ? opts.ttl : TTL_MS, now = opts.now || Date.now, cache = new Map();
  const part = (fn, dflt) => { try { return fn(); } catch (e) { return dflt; } };
  return {
    read(p, excerpt) {
      const key = p.dir + '|' + (excerpt ? '1' : '0'), hit = cache.get(key), t = now();
      if (hit && t - hit.at < ttl) return hit.out;
      const out = {
        at: t,
        chat: excerpt ? part(() => chatExcerpt(opts.claudeRoot, p.dir, p.name), { state: 'error' }) : { state: 'hidden' },
        report: part(() => newestReport(opts.stateDir, p.name, opts.projectDirOf), null),
        status: part(() => statusUpdated(p.dir), null)
      };
      cache.set(key, { at: t, out }); if (cache.size > 200) cache.delete(cache.keys().next().value);
      return out;
    },
    fresh(p, excerpt) { const hit = cache.get(p.dir + '|' + (excerpt ? '1' : '0')); return !!hit && now() - hit.at < ttl; },
    drop() { cache.clear(); }
  };
}

module.exports = { redact, MAX_TAIL, MAX_FILE, CHAT_CHARS, NOTE_CHARS, TTL_MS, clean, cutWord, sanitize, claudeDirs, newestSession, tail, lastFromTail, chatExcerpt, summaryOf, newestReport, statusUpdated, create };
