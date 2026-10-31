// F9 detail reader (vscode-ext/shipmiracle-panel/detail.js, acceptance 22, 24, 25): last chat text + tool from the LAST 128 KB of the newest session file only; newest report through the
// existing report guards; STATUS `Updated:` line; 15 s cache; no transcript read at all when the excerpt setting is off. Synthetic transcripts only.
// Run: node tests/ext_detail_test.js
require('./shipmiracle_isolation').apply();
const fs = require('fs'), os = require('os'), path = require('path'), cp = require('child_process');
const D = require(path.join(__dirname, '../vscode-ext/shipmiracle-panel/detail.js'));
let fails = 0; const check = (name, c, info = '') => { console.log((c ? 'PASS ' : 'FAIL ') + name + (c ? '' : ' ' + info)); if (!c) fails++; };
const ROOT = fs.mkdtempSync(path.join(os.tmpdir(), 'shipmiracle-detail-'));
const CL = path.join(ROOT, 'claude-projects'), STATE = path.join(ROOT, 'state'), PROJ = path.join(ROOT, 'Dev', 'demo');
const SESS = path.join(CL, PROJ.replace(/[^A-Za-z0-9]/g, '-'));
for (const d of [SESS, STATE, path.join(PROJ, 'docs', 'reports'), path.join(PROJ, '.git')]) fs.mkdirSync(d, { recursive: true });
const U = h => String.fromCharCode(parseInt(h, 16));                       // unicode escapes written as code, never as text
const BIDI = U('202e') + U('2066') + U('200f') + U('061c') + U('feff') + U('200b');
const asst = (content, o = {}) => JSON.stringify({ type: 'assistant', timestamp: o.ts || '2026-10-21T10:00:00.000Z', ...(o.side ? { isSidechain: true } : {}), message: { role: 'assistant', content } });
const user = t => JSON.stringify({ type: 'user', timestamp: '2026-10-21T10:00:01.000Z', message: { role: 'user', content: t } });
const text = t => ({ type: 'text', text: t }), tool = (name, input) => ({ type: 'tool_use', name, input: input || { command: 'secret-argument' } });
const write = (name, lines, mtimeAgo = 0) => { const f = path.join(SESS, name); fs.writeFileSync(f, lines.join('\n') + '\n'); const t = (Date.now() - mtimeAgo * 1000) / 1000; fs.utimesSync(f, t, t); return f; };
const reset = () => { for (const f of fs.readdirSync(SESS)) fs.rmSync(path.join(SESS, f), { force: true }); };

(async () => {
  // ---- hygiene helpers
  check('clean() removes control and bidi characters, keeps Arabic and joiners, collapses white space',
    D.clean('a' + BIDI + 'b\u0007\n\tc   d') === 'ab c d' && D.clean('مرحبا بالعالم') === 'مرحبا بالعالم' && D.clean('a' + U('200c') + 'b') === 'a' + U('200c') + 'b');
  const long = ('word '.repeat(80)).trim();                                    // 399 characters
  const cut = D.cutWord(long, 280);
  check('cutWord(): at most 280 characters + an ellipsis, cut at a word boundary (never inside a word)', cut.endsWith('…') && cut.length <= 281 && long.startsWith(cut.slice(0, -1)) && /word$/.test(cut.slice(0, -1)), cut.slice(-20));
  check('cutWord(): an unbroken string is hard cut at 280', D.cutWord('x'.repeat(300), 280) === 'x'.repeat(280) + '…');
  check('cutWord(): a text of exactly 280 is unchanged', D.cutWord('y'.repeat(280), 280) === 'y'.repeat(280));

  // ---- the transcript: last assistant text, latest tool name; user lines, sub-agents and tool arguments are never used
  write('s1.jsonl', [user('please do the thing SECRET-USER'), asst([text('first answer'), tool('Read')]), asst([tool('Grep')]), asst([text('Second answer: tests are running.'), tool('Bash')]), asst([tool('Edit')]), user('thanks SECRET-USER-2')]);
  let r = D.chatExcerpt(CL, PROJ, 'demo');
  check('last assistant TEXT is the second answer, tool = newest tool_use (Edit)', r.state === 'ok' && r.text === 'Second answer: tests are running.' && r.tool === 'Edit', JSON.stringify(r));
  check('the answer holds no user text and no tool argument', !/SECRET/.test(JSON.stringify(r)), JSON.stringify(r));
  check('chat time = the line timestamp', r.ts === Math.floor(Date.parse('2026-10-21T10:00:00.000Z') / 1000), String(r.ts));
  write('s1.jsonl', [asst([text('main answer')]), asst([text('SUBAGENT answer')], { side: true })]);
  check('a sidechain (sub-agent) line is ignored', D.chatExcerpt(CL, PROJ, 'demo').text === 'main answer');
  write('s1.jsonl', [asst([tool('Bash')])]);
  check('a chat with a tool call but no text yet: block omitted ("none")', D.chatExcerpt(CL, PROJ, 'demo').state === 'none');
  reset(); check('no session file: "none"', D.chatExcerpt(CL, PROJ, 'demo').state === 'none');
  write('old.jsonl', [asst([text('OLD chat')])], 3600); write('new.jsonl', [asst([text('NEW chat')])], 5);
  check('the NEWEST session file is read', D.chatExcerpt(CL, PROJ, 'demo').text === 'NEW chat');
  write('new.jsonl', [asst([text('x'.repeat(100) + ' ' + 'y'.repeat(300))])]);
  const ex = D.chatExcerpt(CL, PROJ, 'demo');
  check('a 400-character message is cut to <= 280 at a word with an ellipsis', ex.text.length <= 281 && ex.text.endsWith('…') && ex.text.startsWith('x'.repeat(100)), ex.text.length + '');
  // hostile
  const hostile = '<img src=x onerror=alert(1)> <script>alert(1)</script> [click](javascript:alert(1)) ' + BIDI + 'مرحبا ' + 'Z'.repeat(5000) + ' deep/nested/' + 'p'.repeat(200);
  write('new.jsonl', [asst([text(hostile), tool('Bash<script>')])]);
  const h = D.chatExcerpt(CL, PROJ, 'demo');
  check('hostile text: capped at 281, bidi/control gone, markup kept as plain text (escaped later), a bad tool name is dropped', h.state === 'ok' && h.text.length <= 281 && !new RegExp('[' + BIDI + ']').test(h.text) && h.text.includes('<img') && h.tool === '', JSON.stringify([h.text.length, h.tool]));
  write('new.jsonl', [asst([text('ok'), tool('mcp__server__do-it')])]); check('an MCP-style tool name is kept', D.chatExcerpt(CL, PROJ, 'demo').tool === 'mcp__server__do-it');
  write('new.jsonl', ['{not json', asst([text('after junk')]), '{"type":"assistant","message":']);
  check('junk and a cut last line are skipped', D.chatExcerpt(CL, PROJ, 'demo').text === 'after junk');

  // ---- only the last 128 KB is read; a 50 MB transcript is fast
  reset();
  const big = path.join(SESS, 'big.jsonl'), filler = asst([text('filler line '.repeat(40)), tool('Read')]) + '\n';
  const fd = fs.openSync(big, 'w'); const chunk = Buffer.from(filler.repeat(2000)); let size = 0; while (size < 50 * 1024 * 1024) { fs.writeSync(fd, chunk); size += chunk.length; }
  fs.writeSync(fd, asst([text('the very last words'), tool('Bash')]) + '\n'); fs.closeSync(fd);
  D.chatExcerpt(CL, PROJ, 'demo');                                          // warm the file cache and the JIT once
  const t0 = process.hrtime.bigint(); const big1 = D.chatExcerpt(CL, PROJ, 'demo'); const ms = Number(process.hrtime.bigint() - t0) / 1e6;
  check(`a ${Math.round(size / 1048576)} MB transcript: last text found in ${ms.toFixed(1)} ms (< 20 ms)`, big1.text === 'the very last words' && ms < 20, JSON.stringify([big1.text, ms]));
  const spy = []; const realRead = fs.readSync; fs.readSync = function (fdn, buf, off, len, pos) { spy.push(len); return realRead.apply(this, arguments); };
  D.chatExcerpt(CL, PROJ, 'demo'); fs.readSync = realRead;
  check('it reads at most 128 KB in total', spy.reduce((a, b) => a + b, 0) <= D.MAX_TAIL && spy.length >= 1, JSON.stringify(spy));
  fs.rmSync(big);

  // ---- refusals: symlink, FIFO, oversize
  const secret = path.join(ROOT, 'secret.jsonl'); fs.writeFileSync(secret, asst([text('LEAK')]) + '\n');
  fs.symlinkSync(secret, path.join(SESS, 'link.jsonl'));
  check('a symlinked session file is never read (not picked as newest)', D.chatExcerpt(CL, PROJ, 'demo').state === 'none');
  check('tail() refuses a symlink even when called on it directly', D.tail(path.join(SESS, 'link.jsonl')).ok === false);
  const fifo = path.join(ROOT, 'fifo.jsonl'); cp.execFileSync('mkfifo', [fifo]);
  const tf = Date.now(); const rf = D.tail(fifo);
  check('tail() refuses a FIFO without waiting for a writer', rf.ok === false && Date.now() - tf < 500, JSON.stringify(rf));
  fs.symlinkSync(fifo, path.join(SESS, 'fifo2.jsonl'));
  check('a FIFO / symlink as the newest session file does not hang chatExcerpt', D.chatExcerpt(CL, PROJ, 'demo').state === 'none');
  const huge = path.join(ROOT, 'huge.jsonl'); fs.closeSync(fs.openSync(huge, 'w')); fs.truncateSync(huge, D.MAX_FILE + 1);
  const th = D.tail(huge); check('tail() refuses a file over the size limit', th.ok === false && th.why === 'too large', JSON.stringify(th));
  fs.copyFileSync(huge, path.join(SESS, 'huge.jsonl')); fs.rmSync(huge);
  check('an oversize session file gives the "error" state (the card says: Could not read the chat)', D.chatExcerpt(CL, PROJ, 'demo').state === 'error');
  fs.rmSync(path.join(SESS, 'huge.jsonl')); fs.rmSync(path.join(SESS, 'link.jsonl')); fs.rmSync(path.join(SESS, 'fifo2.jsonl'));
  const dev = D.tail('/dev/zero'); check('tail() refuses a device (/dev/zero)', dev.ok === false);


  // ---- terminal escapes and token-shaped strings (D2, D3). Samples are built from pieces so no secret-looking literal sits in the repo.
  const ESC = String.fromCharCode(27), BEL = String.fromCharCode(7), j = (...a) => a.join('');
  check('ANSI colour codes are stripped completely (RED stays, no "[31m" left)', D.sanitize(j(ESC, '[31mRED', ESC, '[0m done'), 100) === 'RED done' && D.sanitize(j(ESC, '[1;38;5;196mX', ESC, '[K'), 50) === 'X');
  check('OSC sequences (title, hyperlink) are stripped to BEL or ST; two-character escapes too', D.sanitize(j(ESC, ']0;evil title', BEL, 'shown'), 50) === 'shown' && D.sanitize(j(ESC, ']8;;http://x', ESC, '\\', 'link', ESC, ']8;;', ESC, '\\'), 50) === 'link' && D.sanitize(j(ESC, 'cX'), 20) === 'X');
  const samples = { 'Anthropic key': j('sk-', 'ant-', 'api03-', 'AbCdEf', '123456'), 'OpenAI-style key': j('sk-', 'abcdefghijklmnopqrstuvwx'), 'GitHub ghp': j('gh', 'p_', 'abcdefghijklmnopqrstuvwxyz0123'), 'GitHub gho': j('gh', 'o_', 'abcdefghijklmnopqrstuvwxyz0123'), 'GitHub ghs': j('gh', 's_', 'abcdefghijklmnopqrstuvwxyz0123'),
    'GitHub fine-grained': j('github', '_pat_', '11ABCDEFG0abcdefghijkl_mnop'), 'AWS access key': j('AK', 'IA', 'ABCDEFGHIJKLMNOP'), 'Slack': j('xo', 'xb-', '1234567890-abcdefghij'), 'hex run': '0123456789abcdef0123456789abcdef01', 'base64-like run': j('QWxhZGRpbjpvcGVuIHNlc2FtZQ', '12345678901234567890==') };
  for (const [k, v] of Object.entries(samples)) { const out = D.sanitize('before ' + v + ' after', 200); check('redacted: ' + k + ' -> [hidden], the words around it stay', out === 'before [hidden] after', out); }
  const kv = D.sanitize(j('pass', 'word=hunter2 and tok', 'en: abcdef12 and api', '_key="x y" done'), 200);
  check('password= / token: / api_key= values -> [hidden] (the key name stays)', kv === 'password=[hidden] and token: [hidden] and api_key=[hidden] done', kv);
  check('Bearer values -> [hidden]', D.sanitize('curl -H Bearer ' + j('abc', '.def-ghi', '123456') + ' x', 100).includes('Bearer [hidden]') && !/abc\.def/.test(D.sanitize('Bearer ' + j('abc', '.def-ghi', '123456'), 100)));
  check('a token inside a longer text is hidden BEFORE the 280 cut (no half token survives the cut)', (() => { const out = D.sanitize('x'.repeat(260) + ' ' + j('sk-', 'ant-', 'api03-', 'AbCdEf', '1234567890'), 280); return !/sk-|ant-|api03/.test(out); })());
  check('ordinary text is untouched: paths, words, long letter-only runs and a short hash', D.sanitize('see src/app/page.tsx and abc1234 and ' + 'W'.repeat(60), 200) === 'see src/app/page.tsx and abc1234 and ' + 'W'.repeat(60));
  const chat = j('The key is ', 'sk-', 'ant-', 'api03-', 'ZzYyXx9988776655', ' ok'); write('esc.jsonl', [asst([text(chat)])]);
  check('the chat excerpt itself is redacted end to end (chatExcerpt)', D.chatExcerpt(CL, PROJ, 'demo').text === 'The key is [hidden] ok');
  fs.rmSync(path.join(SESS, 'esc.jsonl'));


  // ---- QA round: leaks of key names that merely CONTAIN a secret word, headers, URL userinfo, JWT, PEM, prefix tokens inside identifiers; and the near misses that must stay visible.
  // Every secret-looking string is built at run time from pieces (no secret literal in the repo).
  const R = x => D.sanitize(x, 400), H = '[hidden]', J = (...a) => a.join('');
  const leaks = {
    'GITHUB_TOKEN=value': [J('GITHUB', '_TOKEN=abc', '123'), J('GITHUB_TO', 'KEN=') + H], 'DB_PASSWORD=value': [J('DB_PASS', 'WORD=hunt', 'er2'), J('DB_PASS', 'WORD=') + H],
    'JSON password': [J('{"pass', 'word": "hunt', 'er2"}'), J('{"pass', 'word": ') + H + '}'], 'JSON api_key': [J('{"api', '_key":"abc', 'def123"}'), J('{"api', '_key":') + H + '}'],
    'passcode=1234': [J('pass', 'code=12', '34'), J('pass', 'code=') + H], 'apikey: quoted': [J('apik', 'ey: "ab', ' cd"'), J('api', 'key: ') + H], 'x-api-key = value': [J('x-api', '-key = ab', 'cd1234'), J('x-api', '-key = ') + H],
    'secret => value': [J('my_sec', 'ret => zz', '99'), J('my_sec', 'ret => ') + H], 'credentials=': [J('credent', 'ials=us', 'er:pw'), J('crede', 'ntials=') + H], 'private_key=': [J('private', '_key=ab', 'cdef12'), J('priva', 'te_key=') + H], 'access-key:': [J('AWS_ACCESS', '_KEY_ID=AK', 'xyz12'), J('AWS_ACCES', 'S_KEY_ID=') + H],
    'prefix inside identifier': [J('x_gh', 'p_', 'abcdefghijklmnopqrstuvwxyz0123'), 'x_' + H], 'Authorization Basic': [J('Authori', 'zation: Basic dXNlcjpwYXNz', 'd29yZA=='), J('Au', 'thorization: ') + H], 'Authorization Bearer': [J('Authori', 'zation: Bear', 'er abc.def-ghi123'), J('Au', 'thorization: ') + H],
    'Proxy-Authorization Digest': [J('Proxy-Authori', 'zation: Dig', 'est user="a", nonce="b"'), J('Proxy-Au', 'thorization: ') + H], 'Authorization Token scheme': [J('Authori', 'zation: Tok', 'en abc12345'), J('Au', 'thorization: ') + H],
    'URL userinfo': [J('https://user:hunt', 'er2@host.example/path'), 'https://' + H + '@host.example/path'], 'JWT short segments': [J('ey', 'J.ab.cd'), H], 'JWT normal': [J('ey', 'JhbGciOiJIUzI1NiJ9.', 'eyJzdWIiOiIxMjM0In0.', 'abc_DEF-123'), H],
    'PEM block': [J('-----BEGIN RSA PRIV', 'ATE KEY-----\nMIIabc\ndef\n-----END RSA PRIV', 'ATE KEY-----'), H], 'PEM no END': [J('see -----BEGIN PRIV', 'ATE KEY----- MIIabc def'), 'see ' + H]
  };
  for (const [k, [src, want]] of Object.entries(leaks)) { const out = R(src); check('leak hidden: ' + k, out === want, JSON.stringify([out, want])); }
  check('Authorization header is hidden ONCE (no "Authorization: [hidden] [hidden]")', R(J('Authori', 'zation: Bear', 'er abcdefgh1234')) === 'Authorization: [hidden]');
  check('hiding is idempotent (the page cleans the text a second time)', ['password=x1y2z3w4', 'Authorization: Bearer abcdefgh1234', 'https://u:p@h/x', 'plain words'].every(x => R(R(x)) === R(x)));
  const keep = {
    'UUID': '9b2f6c1e-4d3a-4f6b-8a7c-1d2e3f4a5b6c', 'long file name': 'report-2026-10-21-final-summary-of-the-whole-sprint-review.md', 'png file name': 'Screenshot_2026-10-21_at_14.31.07_final_version_of_it.png',
    'path with digits': 'src/components/settings/panel_v3_card_expanded_state_2026/index.tsx', 'dash-joined words': 'deeply-nested-folder-name-for-the-new-feature-123', 'CamelCase identifier': 'ThisIsAVeryLongCamelCaseIdentifier12',
    'UPPER_SNAKE identifier': 'MAX_NUMBER_OF_RETRIES_BEFORE_GIVING_UP_9', 'prose with token word': 'the token: budget is low', 'prose with password word': 'the password: reset page is ready', 'prose auth': 'auth: ok and done',
    'git sha after commit': 'commit ' + '0123456789abcdef'.repeat(3).slice(0, 40), 'git sha after sha256': 'sha256 ' + 'fedcba9876543210'.repeat(4), 'git sha after @': 'v1@' + '0123456789abcdef'.repeat(3).slice(0, 40), 'git sha in backticks': 'at `' + 'abcdef0123456789'.repeat(3).slice(0, 40) + '`', 'ordinary short hash': 'abc1234 and 3f2a9c1'
  };
  for (const [k, v] of Object.entries(keep)) { const out = R('see ' + v + ' ok'); check('NOT redacted: ' + k, out === 'see ' + v + ' ok', out); }
  check('a bare `token: value` that looks like a secret IS hidden (8+ chars with a digit)', R(J('tok', 'en: abcd', 'ef12345')) === J('to', 'ken: ') + H && R(J('pass', 'word: "two words"')) === J('pass', 'word: ') + H);
  check('a standalone 64-char hex without a git word before it IS hidden; so is a standalone 40-char hex', R('x ' + 'abcdef0123456789'.repeat(4) + ' y') === 'x [hidden] y' && R('x ' + 'abcdef0123456789'.repeat(3).slice(0, 40) + ' y') === 'x [hidden] y');
  check('a standalone base64-like blob (letters and digits, 44 chars) IS hidden even with a slash inside', R('k ' + J('QWxhZGRpbjpvcGVuIHNlc2FtZQ', '/12345678901234567890') + ' z') === 'k [hidden] z');

  // ---- STATUS
  const sf = path.join(PROJ, 'docs', 'STATUS.md');
  fs.writeFileSync(sf, '# STATUS\n\nUpdated: 2026-10-21 by Claude. ' + 'long '.repeat(60) + '\n\n## Next\n- one\n');
  const st = D.statusUpdated(PROJ);
  check('STATUS Updated line: prefix dropped, cut at 120 (+ ellipsis), time = file mtime', st && st.note.startsWith('2026-10-21 by Claude.') && st.note.length <= 121 && st.note.endsWith('…') && Math.abs(st.ts - Date.now() / 1000) < 60, JSON.stringify(st));
  fs.writeFileSync(sf, '# STATUS\n\nno updated line\n'); check('STATUS without an Updated line: empty note, still has a time', D.statusUpdated(PROJ).note === '');
  fs.rmSync(sf); check('no STATUS.md: null', D.statusUpdated(PROJ) === null);
  fs.symlinkSync(secret, sf); check('STATUS.md as a symlink: null (never followed)', D.statusUpdated(PROJ) === null); fs.rmSync(sf);
  fs.writeFileSync(sf, 'Updated: ' + BIDI + 'clean ' + '<b>x</b>\n'); check('STATUS note: bidi removed, markup left as text', D.statusUpdated(PROJ).note === 'clean <b>x</b>');

  // ---- the newest report through the guards
  const rep = path.join(PROJ, 'docs', 'reports', 'CR-1-test.md'); fs.writeFileSync(rep, '---\nx: 1\n---\n# Test report\n\n**214 of 214** tests passed. See [the log](http://evil.example/x).\nNo failures.\n- 2 skipped by design\nfourth line\n');
  const idx = items => { fs.mkdirSync(path.join(STATE, 'v1', 'reports'), { recursive: true }); fs.writeFileSync(path.join(STATE, 'v1', 'reports', 'index.json'), JSON.stringify({ v: 1, items })); };
  const now = Math.floor(Date.now() / 1000), pd = n => (n === 'demo' ? PROJ : '');
  idx([{ id: 'old', kind: 'cr', project: 'demo', verdict: 'FAIL', ts: now - 9000, title: 'Old', path: 'docs/reports/CR-1-test.md' }, { id: 'new', kind: 'cr', project: 'demo', verdict: 'pass', ts: now - 60, title: 'Test report', path: 'docs/reports/CR-1-test.md' }, { id: 'other', kind: 'cr', project: 'other', verdict: 'FAIL', ts: now, title: 'Not mine', path: 'x.md' }]);
  let nr = D.newestReport(STATE, 'demo', pd);
  check('newest report of THIS project: id, verdict, title, time', nr && nr.id === 'new' && nr.verdict === 'PASS' && nr.title === 'Test report' && nr.ts === now - 60, JSON.stringify(nr));
  check('summary = first three body lines as plain text (no heading, front matter, markdown marks or link target)', nr.summary === '214 of 214 tests passed. See the log. No failures. 2 skipped by design', nr.summary);
  idx([{ id: 'esc', kind: 'cr', project: 'demo', verdict: 'PASS', ts: now, title: 'Escape', path: '../../secret.jsonl' }]);
  check('a report path that leaves the project is not shown', D.newestReport(STATE, 'demo', pd) === null);
  fs.symlinkSync(secret, path.join(PROJ, 'docs', 'reports', 'link.md'));
  idx([{ id: 'ln', kind: 'cr', project: 'demo', verdict: 'PASS', ts: now, title: 'Link', path: 'docs/reports/link.md' }]);
  check('a report that is a symlink out of the project is not shown', D.newestReport(STATE, 'demo', pd) === null);
  idx([{ id: 'ln', kind: 'cr', project: 'demo', verdict: 'PASS', ts: now, title: 'Link', path: 'docs/reports/link.md' }, { id: 'ok', kind: 'cr', project: 'demo', verdict: 'FAIL', ts: now - 5, title: 'Fine', path: 'docs/reports/CR-1-test.md' }]);
  check('the newest report that CAN be read wins (a bad one is skipped, never half read)', (D.newestReport(STATE, 'demo', pd) || {}).id === 'ok');
  fs.writeFileSync(path.join(STATE, 'v1', 'reports', 'index.json'), '{broken'); check('a broken index: null', D.newestReport(STATE, 'demo', pd) === null);
  fs.rmSync(path.join(STATE, 'v1'), { recursive: true }); check('no index: null', D.newestReport(STATE, 'demo', pd) === null);

  // ---- the whole answer, cache and the setting
  write('s2.jsonl', [asst([text('cached text')])]);
  let clock = 1000000; const det = D.create({ stateDir: STATE, claudeRoot: CL, projectDirOf: pd, now: () => clock });
  const p = { name: 'demo', dir: PROJ };
  const a1 = det.read(p, true); write('s2.jsonl', [asst([text('changed text')])]);
  clock += 14000; check('within 15 s the cached answer is returned (no new read)', det.read(p, true) === a1 && a1.chat.text === 'cached text');
  clock += 2000; check('after 15 s the files are read again', det.read(p, true).chat.text === 'changed text');
  const opened = []; const realOpen = fs.openSync; fs.openSync = function (f) { opened.push(String(f)); return realOpen.apply(this, arguments); };
  const off = D.create({ stateDir: STATE, claudeRoot: CL, projectDirOf: pd }).read(p, false); fs.openSync = realOpen;
  check('excerpt OFF: chat state is "hidden" and NO file under the Claude projects folder is opened (no transcript read)', off.chat.state === 'hidden' && !opened.some(f => f.startsWith(CL)) && !JSON.stringify(off).includes('changed text'), JSON.stringify(opened.slice(0, 3)));
  check('excerpt OFF still returns the other blocks (status)', off.status && off.status.note.includes('clean'));
  check('a broken part never throws: every block degrades on its own', (() => { try { const d2 = D.create({ stateDir: '/nonexistent', claudeRoot: '/nonexistent', projectDirOf: () => { throw new Error('x'); } }).read({ name: 'zz', dir: '/nonexistent/zz' }, true); return d2.chat.state === 'none' && d2.report === null && d2.status === null; } catch (e) { return false; } })());

  console.log(fails ? `\nFAILED: ${fails}` : '\nALL PASS'); fs.rmSync(ROOT, { recursive: true, force: true }); process.exit(fails ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
