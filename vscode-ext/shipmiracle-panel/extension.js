// Shipmiracle: a sidebar panel with every project (state, active agents, token use, plan meters) and one
// status bar item. No dependencies. Data: data.js; HTML: panel.js. Claude hooks write ~/.local/state/shipmiracle.
const vscode = require('vscode');
const fs = require('fs');
const os = require('os');
const path = require('path');
const crypto = require('crypto');
const { execFile } = require('child_process');
const { collect } = require('./data');
const { DEV, WS, isProtected } = require('./locations');
const { html } = require('./panel');
const CHARTER = require('./charter');
const PROPOSED = require('./proposed');
const REPORTS = require('./reports');
const SETUP = require('./setup');
const ASK = require('./ask');
const STR = require('./strings');
const INTERVIEW = require('./interview');
const DETAIL = require('./detail');      // F9 card Details: read-only, only for an open card

// SHIPMIRACLE_EXT_* and the other SHIPMIRACLE_* knobs below exist for the tests only: they are read only when SHIPMIRACLE_TEST=1 (and not SHIPMIRACLE_WS / SHIPMIRACLE_STATE: the gate hooks read those).
const testEnv = k => process.env.SHIPMIRACLE_TEST === '1' ? process.env[k] : undefined;
// Safe by construction: an SHIPMIRACLE_EXT_* variable without SHIPMIRACLE_TEST=1 is a half-configured test. The override is ignored (real paths), so EVERY write to the workspace or the state folder is refused.
const LEAKED = process.env.SHIPMIRACLE_TEST !== '1' && Object.keys(process.env).some(k => k.startsWith('SHIPMIRACLE_EXT_'));
let leakTold = false;
const leakBlock = () => { if (!LEAKED) return false; if (!leakTold) { leakTold = true; trace('SHIPMIRACLE_EXT_* set without SHIPMIRACLE_TEST=1: refusing to write'); } return true; };
const STATE = testEnv('SHIPMIRACLE_EXT_STATE') || path.join(os.homedir(), '.local', 'state', 'shipmiracle');
const CLAUDE_ROOT = path.join(os.homedir(), '.claude', 'projects');          // where Claude Code keeps the session files (data.js reads the same folder)
const DIAG = testEnv('SHIPMIRACLE_DIAG_DIR') || path.join(os.homedir(), '.local', 'state', 'shipmiracle-diag');
const runTask = async label => {
  const t = (await vscode.tasks.fetchTasks()).find(x => x.name === label);
  if (t) return vscode.tasks.executeTask(t);
  vscode.window.showWarningMessage(`Task "${label}" not found: add it to your VS Code tasks.json (template: dotfiles/vscode-tasks.json).`);
};
// Run a workspace script with an argument list (no shell, so names can't inject commands); output shows in a terminal.
const SAFE = /^[A-Za-z0-9._-]+$/;
const shownPath = p => { const h = os.homedir(); return p === h || p.startsWith(h + path.sep) ? '~' + p.slice(h.length) : p; };   // for messages: ~/... under the home folder
const runScript = (title, script, args) => vscode.tasks.executeTask(new vscode.Task(
  { type: 'shipmiracle', script: title }, vscode.TaskScope.Global, title, 'Shipmiracle',
  new vscode.ProcessExecution(path.join(WS, 'bin', script), args)));
const openDir = (dir, newWindow) => vscode.commands.executeCommand('vscode.openFolder', vscode.Uri.file(dir), { forceNewWindow: !!newWindow });

// One Claude chat per project, as a tab in the editor area, started in that project's own folder (so its rules,
// hooks and history apply). The window never changes folder, so nothing reloads. Clicking a card again just
// brings its tab forward; a chat keeps running while another tab is in front.
const CLAUDE = path.join(os.homedir(), '.local', 'bin', 'claude');
const chatName = name => `${name} · Claude`;
let onChatOpened = () => {};          // activate() points this at the unread-marker clearing (F8)
const closing = new WeakSet();       // terminals this panel is closing right now (VS Code removes them a moment later)
// The ops the extension itself performs (they need a chat terminal). Every executor:'ext' op in bin/shipm-watch's contract must be listed here (tests/ext_health_fix_test.js).
const EXT_OPS = ['interrupt', 'relaunch', 'fresh'];
const DEFAULT_OPS = { interrupt: { executor: 'ext', wait_s: 8, checks: 1 }, relaunch: { executor: 'ext', wait_s: 20, checks: 3 }, fresh: { executor: 'ext', wait_s: 20, checks: 3 },
  'end-job': { executor: 'watch', wait_s: 2, checks: 1 }, 'end-proc': { executor: 'watch', wait_s: 2, checks: 1 }, 'quit-session': { executor: 'watch', wait_s: 2, checks: 1 }, 'close-duplicate': { executor: 'watch', wait_s: 2, checks: 1 },
  'stop-colima': { executor: 'watch', wait_s: 5, checks: 2 }, 'pause-agents': { executor: 'watch', wait_s: 1, checks: 1 }, 'drop-record': { executor: 'watch', wait_s: 0, checks: 1 },
  'end-browser': { executor: 'watch', wait_s: 3, checks: 2 }, 'end-testrun': { executor: 'watch', wait_s: 20, checks: 2 } };
const OP_LABEL = { interrupt: 'Interrupt', relaunch: 'Relaunch', fresh: 'Fresh chat', 'end-job': 'End job', 'end-proc': 'End process', 'quit-session': 'Quit session', 'close-duplicate': 'Close duplicate', 'stop-colima': 'Stop Docker VM', 'pause-agents': 'Pause agents', 'drop-record': 'Drop record', 'end-browser': 'End browser', 'end-testrun': 'Stop test run' };
const oldLauncher = t => { const co = t.creationOptions; return !!(co && co.shellPath && !(co.shellArgs || []).some(a => /(^|\/)shipm-chat$/.test(String(a)))); };   // started by the panel before 0.4.38 (shellPath = claude); unknown when VS Code gives no creationOptions
const chatOf = new Map();           // terminal -> { project, port, pid }: which chat a terminal really is (revived terminals have another name)
// A project name that contains a word the legacy plan-approval hook reads as consent (go, yes, ok, start, implement, approve ...) is never typed into a chat by the panel.
const APPROVAL_WORD = /(^|[^a-z0-9])(go|yes|ok|okay|start|implement|approve|approved|proceed|continue|run|do|sure)([^a-z0-9]|$)/i;
const chatTab = name => vscode.window.terminals.find(t => t.exitStatus === undefined && !closing.has(t) && (t.name === chatName(name) || (chatOf.get(t) || {}).project === name));
// Which project is the owner "in"? The focused tab decides: a Claude chat tab (by name, or by the working folder of its
// process, which also covers tabs VS Code restored after a restart) or a file open under <projects folder>/<project>.
const projectOfPath = p => { const rel = p && path.relative(DEV, p); return rel && !rel.startsWith('..') && !path.isAbsolute(rel) ? rel.split(path.sep)[0] : ''; };
// The folder a chat process works in and which chat a terminal is: procx.js (macOS: lsof and ps eww; Linux and WSL: /proc/<pid>/cwd and portable ps flags, the environment is never read; anything else: unknown).
const PROCX = require('./procx'), HOSTX = require('./hostx');
const within = (promise, ms) => Promise.race([Promise.resolve(promise), new Promise(r => setTimeout(() => r(undefined), ms))]);
const proc = PROCX.make({ projectOfPath, within });
const cwdOfPid = pid => proc.cwdOfPid(pid);
const trace = msg => { try { fs.mkdirSync(DIAG, { recursive: true }); const f = path.join(DIAG, 'panel-trace.log'); try { if (fs.statSync(f).size > 100000) fs.writeFileSync(f, ''); } catch (e0) { /* no file yet */ } fs.appendFileSync(f, new Date().toISOString().slice(11, 23) + ' ' + msg + '\n'); } catch (err) { /* diagnostics only */ } };
async function activeProject() { try { return await within(activeProjectRaw(), 2500) || ''; } catch (e) { return ''; } }
// ---- Chat health -------------------------------------------------------------------------------------------------------------
// VS Code revives the chat terminals after a restart with the PREVIOUS run's environment: the Claude-IDE port in it is dead, VS Code marks the
// terminal with a yellow "relaunch" triangle, the chat's IDE link fails, and the panel (which looked for "<project> · Claude") opened a second chat
// on the same conversation. So: find chats by their process, compare each chat's port with the live IDE lock files, close stale duplicates and
// relaunch a lone stale chat (claude --continue = same conversation) when its project is idle; a busy or focused one only gets a "relaunch" chip.
const IDE_DIR = testEnv('SHIPMIRACLE_IDE_DIR') || path.join(os.homedir(), '.claude', 'ide');
function livePorts() {
  const live = new Set();
  try { for (const f of fs.readdirSync(IDE_DIR)) { const m = /^(\d+)\.lock$/.exec(f); if (!m) continue; try { process.kill(REPORTS.readJson(path.join(IDE_DIR, f), 65536).pid, 0); live.add(m[1]); } catch (err) { /* owner gone */ } } } catch (err) { /* no folder */ }
  return live;
}
// Tools by absolute path where macOS and Linux differ: python3 is /usr/bin/python3 on macOS and most Linux, elsewhere (/usr/local/bin, Homebrew, Nix ...) the first one that exists, else the bare name from PATH.
const firstFile = (list, bare) => list.find(f => { try { return fs.statSync(f).isFile(); } catch (e) { return false; } }) || bare;
const PY3 = firstFile(['/usr/bin/python3', '/usr/local/bin/python3', '/opt/homebrew/bin/python3'], 'python3'), GIT = firstFile(['/usr/bin/git', '/usr/local/bin/git', '/opt/homebrew/bin/git'], 'git');
const inspectChat = t => proc.inspect(t);                                         // { project, port, pid, portKnown } or null; portKnown false = the stale-chat check cannot tell here (nothing is closed because of it)
async function activeProjectRaw() {
  const tab = vscode.window.tabGroups.activeTabGroup && vscode.window.tabGroups.activeTabGroup.activeTab;
  const input = tab && tab.input;
  if (input && input.uri && input.uri.scheme === 'file' && !(vscode.TabInputTerminal && input instanceof vscode.TabInputTerminal)) {
    const n = projectOfPath(input.uri.fsPath); if (n) return n;
  }
  const term = vscode.window.activeTerminal;
  if (term) {
    const m = /^(.+) · Claude$/.exec(term.name); if (m) return m[1];
    try { const pid = await within(term.processId, 1200); if (pid) { const n = projectOfPath(await cwdOfPid(pid)); if (n) return n; } } catch (e) { /* no process */ }
  }
  const wf = vscode.workspace.workspaceFolders; return wf && wf[0] ? projectOfPath(wf[0].uri.fsPath) : '';
}

// ---- Feature ideas (bin/idea): every action goes through the tool (no shell strings); names and ids are validated.
const IDEA = path.join(WS, 'bin', 'idea');
const runIdea = args => new Promise(res => execFile(PY3, [IDEA, ...args], { timeout: 60000 }, (err, out, errout) => {
  if (err) vscode.window.showErrorMessage('Ideas: ' + String(errout || err.message).trim().split('\n').pop());
  res(err ? null : String(out).trim());
}));

// One-shot instructions for bin/shipm-chat, written before the terminal is created; the wrapper deletes them when it starts claude.
const MAX_ONESHOT = 4000;
function oneShot(file, text) {   // true when the file now exists; exclusive create (never follows or replaces a planted file), private
  try {
    if (leakBlock()) return false;
    if (typeof text !== 'string' || !text.length) throw new Error('empty');
    if (text.length > MAX_ONESHOT) throw new Error('longer than ' + MAX_ONESHOT + ' characters');
    if (text.includes('\0')) throw new Error('contains a NUL character');
    fs.mkdirSync(STATE, { recursive: true }); fs.writeFileSync(path.join(STATE, file), text, { mode: 0o600, flag: 'wx' }); return true;
  } catch (err) { trace('could not write ' + file + ': ' + (err && err.message)); const msg = 'Chat not opened: the launch instruction could not be saved (' + String(err && err.message).slice(0, 80) + ')'; chatNotify(msg); if (err && err.code) vscode.window.showErrorMessage(msg); return false; }
}
const CHAT_NAME_OK = n => /^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(n) && !n.includes('..');
let chatNotify = text => vscode.window.showInformationMessage(text);   // activate() points this at the panel's notice line
// How a chat terminal is launched: /bin/bash -p bin/shipm-chat <name> <nonce> [prompt-hash] (-p: BASH_ENV, SHELLOPTS and exported functions are ignored).
// The nonce names the one-shot files, so a replay of these saved args after a VS Code restart finds them consumed and just continues the conversation;
// the hash binds a prompt file to what the panel wrote (a file swapped afterwards is ignored).
const launchOf = (name, nonce, hash) => ({ shellPath: '/bin/bash', shellArgs: ['-p', path.join(WS, 'bin', 'shipm-chat'), name, nonce, ...(hash ? [hash] : [])] });
const bornAt = new WeakMap();   // when this panel opened a chat terminal: a brand-new chat is never closed as "stale" in its first 3 minutes
const named = new WeakSet();    // chat terminals already titled with their folder name
// Open (or reuse) a project's chat and put a first message into it. A new terminal gets it through a one-shot file that bin/shipm-chat reads and deletes at launch; an open one only
// while that chat is waiting at its prompt (never typed into a chat that is busy).
function openChatWith(dir, name, prompt0, busy) {
  const prompt = String(prompt0).startsWith(STR.panelMarker) ? String(prompt0) : STR.panelMarker + prompt0;      // marked as the panel's text, never mistaken for the owner's approval
  const open = chatTab(name);
  if (open) {
    open.show(false);
    if (busy) { vscode.window.showInformationMessage(name + ' is busy right now. Try again when it has finished its step.'); return false; }
    open.sendText('\u0015', false); open.sendText(prompt, false); vscode.window.showInformationMessage('The message is in the ' + name + ' chat. Check it and press Enter.');
    return false;
  }
  if (!chatNameOk(name)) return false;
  const nonce = crypto.randomBytes(8).toString('hex');
  if (!oneShot(`chat-prompt.${name}.${nonce}`, prompt)) return false;
  const hash = crypto.createHash('sha256').update(prompt, 'utf8').digest('hex').slice(0, 32);
  const t = vscode.window.createTerminal({
    name: chatName(name), cwd: dir, ...launchOf(name, nonce, hash),
    location: { viewColumn: vscode.ViewColumn.Active, preserveFocus: false }, isTransient: false, iconPath: new vscode.ThemeIcon('sparkle')
  });
  named.add(t); bornAt.set(t, Date.now()); t.show(false);
  return true;
}
// bin/shipm-chat starts every chat with --model opusplan (a resumed chat would otherwise keep the model saved in its conversation) and --continue when the project has history
function openChat(dir, name, quiet, fresh) {
  const open = chatTab(name);
  if (!quiet) onChatOpened(name);
  if (open) { if (!quiet) open.show(false); return false; }
  if (!chatNameOk(name)) return false;
  const nonce = crypto.randomBytes(8).toString('hex');
  if (fresh && !oneShot(`chat-fresh.${name}.${nonce}`, '1')) return false;      // a failed marker must not silently continue the old conversation
  const t = vscode.window.createTerminal({
    name: chatName(name), cwd: dir, ...launchOf(name, nonce),   // bin/shipm-chat decides --continue / fresh / first message at EVERY launch (VS Code replays these saved args after a restart); chat title and phone session = folder name
    location: { viewColumn: vscode.ViewColumn.Active, preserveFocus: !!quiet }, isTransient: false,
    iconPath: new vscode.ThemeIcon('sparkle')
  });
  named.add(t); bornAt.set(t, Date.now());
  t.show(!!quiet);
  return true;
}
// Handoff: a fresh chat NEXT TO the old one. Same launch as openChat(..., fresh=true) (bin/shipm-chat starts a new conversation when the marker exists), but the old terminal is left alone:
// the owner closes it when ready. Only the panel decides; nothing is closed here.
function openFreshBeside(dir, name) {
  if (!chatNameOk(name)) return false;
  const nonce = crypto.randomBytes(8).toString('hex');
  if (!oneShot(`chat-fresh.${name}.${nonce}`, '1')) return false;
  const t = vscode.window.createTerminal({
    name: chatName(name) + ' (fresh)', cwd: dir, ...launchOf(name, nonce),
    location: { viewColumn: vscode.ViewColumn.Active, preserveFocus: false }, isTransient: false, iconPath: new vscode.ThemeIcon('sparkle')
  });
  named.add(t); bornAt.set(t, Date.now()); t.show(false);
  return true;
}
function chatNameOk(name) {
  if (CHAT_NAME_OK(name)) return true;
  chatNotify(`Chat not opened: the folder name ${String(name).slice(0, 60)} has characters the chat launcher does not accept; rename the folder`);
  return false;
}

// Claude Code's saved usage list (Fable and the weekly meters) goes stale between uses. `claude -p "/usage"` is Claude
// Code's own command: it makes no model request (no tokens), takes about 3 seconds and refreshes that list. Run at most
// every 10 minutes, only while a VS Code window is in front, from an empty folder, with this workspace's hooks silenced.
const PROBE = path.join(os.homedir(), '.local', 'state', 'shipmiracle', 'probe');
let probeBusy = false, lastProbe = 0;
function refreshUsage(cachedAt) {
  if (leakBlock()) return Promise.resolve(false);
  const now = Date.now();
  if (probeBusy || now - lastProbe < 10 * 60e3 || now - (cachedAt || 0) < 10 * 60e3 || !vscode.window.state.focused) return Promise.resolve(false);
  probeBusy = true; lastProbe = now;
  try { fs.mkdirSync(PROBE, { recursive: true }); } catch (e) { /* ignore */ }
  return new Promise(res => {
    const c = execFile(CLAUDE, ['-p', '/usage'], { cwd: PROBE, timeout: 60000, env: { ...process.env, SHIPMIRACLE_QUIET: '1' } }, () => { probeBusy = false; res(true); });
    if (c.stdin) c.stdin.end();
  });
}

function activate(ctx) {
  trace('activate start');
  const known = n => data.projects.find(p => p.name === n);
  const label = p => p.special === 'ideas' ? 'Inbox (not sure yet)' : p.name;
  async function ideaAction(m) {
    if (leakBlock()) return;
    const op = String(m.op || ''), id = /^F\d+$/.test(m.id || '') ? m.id : '', proj = known(m.project || '') ? m.project : '';
    if (op === 'add') {
      const dp = proj && !known(proj).held ? known(proj) : null; const text = String(m.text || '').replace(/\s+/g, ' ').trim().slice(0, 500);
      if (!dp || !text) return;                                                  // the project and the text come from the tab itself (no VS Code input bar)
      const r = await runIdea(['-p', dp.name, 'add', text]);
      if (r === null) return;
      refresh();
      const nid = (r.match(/added (F\d+)/) || [])[1];
      if (!nid) return;
      const busy = dp.state === 'working' || dp.state === 'needs-input';
      const startReview = async () => { const prompt = await runIdea(['-p', dp.name, 'eval-prompt', nid]); if (prompt) openChatWith(dp.dir, dp.name, prompt, busy); };
      if (m.review) await startReview();                                         // "Add and check if it is worth it"
      else if (await vscode.window.showInformationMessage(`Added ${nid} to ${label(dp)}.`, 'Is it worth it? Review now') === 'Is it worth it? Review now') await startReview();
    } else if (op === 'done' && proj && id) { if (await runIdea(['-p', proj, 'done', id]) !== null) refresh();
    } else if (op === 'drop' && proj && id) {                                  // the tab already asked "Sure?" in place
      if (await runIdea(['-p', proj, 'drop', id]) !== null) refresh();
    } else if (op === 'copy' && proj && id && known(m.to || '') && !known(m.to).held && m.to !== proj) {
      const r = await runIdea(['-p', proj, 'copy', id, '--to', m.to]);
      if (r !== null) { vscode.window.showInformationMessage('Copied ' + id + ' to ' + label(known(m.to)) + '.'); refresh(); }
    } else if ((op === 'moveto' || op === 'move') && proj && id && known(m.to || '') && !known(m.to).held && m.to !== proj) {
      if (await runIdea(['-p', proj, 'move', id, '--to', m.to]) !== null) refresh();
    } else if ((op === 'worth' || op === 'plan' || op === 'newproject' || op === 'review') && proj) {
      const p = known(proj); const busy = p.state === 'working' || p.state === 'needs-input';
      let prompt = '';
      if (op === 'worth' && id) prompt = await runIdea(['-p', proj, 'eval-prompt', id]);
      else if (op === 'review') { const ids = p.ideas.open.slice(0, 5).map(i => i.id); prompt = await runIdea(['-p', proj, 'eval-prompt', ...ids]); runIdea(['dismiss']).then(refresh); }
      else if (op === 'plan' && id) prompt = `Plan idea ${id} of ${proj} (its verdict is BUILD NOW). Work in plan mode, write the steps and acceptance criteria, print the plan here and wait for my approval before building.`;
      else if (op === 'newproject' && id) { openChatWith(path.join(DEV, 'ideas'), 'ideas', `Idea ${id} of ${proj} was judged to be a new project. Propose a project name and type and seed it as an idea here. Create nothing until I tell you the name and type to use.`, false); return; }
      if (prompt) openChatWith(p.dir, p.name, prompt, busy);
    } else if (op === 'later') { await runIdea(['dismiss']); refresh();
    } else if (op === 'never' && proj) { await runIdea(['never', proj]); vscode.window.showInformationMessage('Will not remind you about ' + proj + ' ideas.'); refresh(); }
  }
  let data = { projects: [], plan: {} }, view = null, busy = false, activeName = '', lastPage = '';
  // ---- Settings (package.json contributes shipmiracle.cardChatExcerpt and shipmiracle.unreadMarker; both default to on, the public export's package.json turns the first off).
  const settingOn = key => { try { return vscode.workspace.getConfiguration('shipmiracle').get(key) !== false; } catch (e) { return true; } };
  // ---- F9 Details. The page asks with {type:'detail', project} only while a card is open. The project and its folder come from THIS side's data, never from the page. The answer is cached 15 s
  // (detail.js) and goes into the next render as data.detail[project]; an identical page is not set again. With shipmiracle.cardChatExcerpt off no transcript file is opened at all.
  const detailReader = DETAIL.create({ stateDir: STATE, claudeRoot: testEnv('SHIPMIRACLE_EXT_CLAUDE') || CLAUDE_ROOT, projectDirOf: n => { const q = known(typeof n === 'string' ? n : ''); return q && q.dir ? q.dir : ''; } });
  const detailSeen = new Map();                    // project -> { out | error, at }
  const detailForPage = () => {
    const ex = settingOn('cardChatExcerpt'), out = Object.create(null), nowMs = Date.now();
    for (const [name, v] of detailSeen) {
      if (nowMs - v.at > 90000) { detailSeen.delete(name); continue; }                  // the open page asks again every 30 s; a card nobody asked for any more stops carrying text
      out[name] = v.error ? { error: true } : { ...v.out, chat: ex ? v.out.chat : { state: 'hidden' } };
    }
    return out;
  };
  function detailAction(m) {
    if (!m || typeof m !== 'object' || typeof m.project !== 'string' || m.project.length > 200) return;
    const p = known(m.project); if (!p || !p.dir) return;                               // anything else in the message (a path, a file name) is ignored
    const ex = settingOn('cardChatExcerpt');
    try { detailSeen.set(p.name, { out: detailReader.read(p, ex), at: Date.now() }); } catch (err) { trace('detail failed: ' + (err && err.message)); detailSeen.set(p.name, { error: true, at: Date.now() }); }
    if (view) render();
  }
  // ---- F8 Unread marker. The CLI decides what is new (`shipm report panel` unread {new, why} = the chat's state file says finished-a-turn / needs-you later than the owner last looked) and keeps the
  // "looked" time in <state>/v1/seen.json, written ONLY by `shipm project seen NAME`. This side calls that command (execFile argv, no shell) when the owner opens the chat, focuses its terminal, or the
  // chat is the focused tab while it is marked. Nothing here counts the marker in a badge; shipmiracle.unreadMarker off shows nothing and calls nothing.
  const lastSeenCall = new Map();
  const chatFocused = name => { try { const t = chatTab(name); return !!t && t === vscode.window.activeTerminal && vscode.window.state.focused !== false; } catch (e) { return false; } };
  function markSeen(name) {
    if (leakBlock() || !settingOn('unreadMarker') || typeof name !== 'string' || !CHAT_NAME_OK(name)) return;
    const p = known(name); if (!p || !p.unread) return;                                   // only a project that is marked, and only a name from this side's own data
    const t = Date.now(); if (t - (lastSeenCall.get(name) || 0) < 400) return; lastSeenCall.set(name, t);
    p.unread = '';
    try { execFile(path.join(WS, 'bin', 'shipm'), ['project', 'seen', name], { timeout: 8000, env: process.env }, err => { if (err) trace('seen failed: ' + String(err.message).slice(0, 120)); setTimeout(refresh, 300); }); } catch (e) { trace('seen crashed'); }
    if (view) render();
  }
  onChatOpened = name => markSeen(name);
  function updateUnread(ps) {
    const on = settingOn('unreadMarker');
    for (const p of ps) { if (!on) p.unread = ''; else if (p.unread && chatFocused(p.name)) markSeen(p.name); }
  }
  let healing = false, lastHeal = 0, staleFlags = {};
  async function heal(force) {
    if (healing || (!force && Date.now() - lastHeal < (testEnv('SHIPMIRACLE_HEAL_MS') !== undefined ? +testEnv('SHIPMIRACLE_HEAL_MS') : 20000))) return false; healing = true; lastHeal = Date.now();
    const before = JSON.stringify(staleFlags);
    try {
      const live = livePorts(), groups = {};
      await Promise.all(vscode.window.terminals.filter(t => t.exitStatus === undefined && !closing.has(t)).map(async t => {
        const i = await inspectChat(t); if (!i) { chatOf.delete(t); return; }
        chatOf.set(t, i); (groups[i.project] = groups[i.project] || []).push({ t, ...i, old: oldLauncher(t), stale: !!i.port && !live.has(i.port) && Date.now() - (bornAt.get(t) || 0) > 180000 });
      }));
      const flags = {};
      for (const [proj, list] of Object.entries(groups)) {
        const p = data.projects.find(x => x.name === proj); if (!p) continue;
        const calm = p.state === 'calm' || p.state === 'idle', free = x => x.t !== vscode.window.activeTerminal;
        const healthy = list.filter(x => !x.stale), stale = list.filter(x => x.stale);
        const close = x => { trace(`chat health: closing the stale ${proj} chat (pid ${x.pid}, dead port ${x.port})`); closing.add(x.t); chatOf.delete(x.t); x.t.dispose(); };
        if (healthy.length && stale.length) { for (const x of stale) { if (calm && free(x)) close(x); else flags[proj] = true; } }
        else if (!healthy.length && stale.length) {
          if (calm && stale.every(free)) { stale.forEach(close); openChat(p.dir, p.name, true); trace(`chat health: relaunched the ${proj} chat`); }
          else flags[proj] = true;
        }
        // chats started by the old launcher would open a blank conversation at the next full VS Code restart: only mark the card, never close
        if (list.some(x => x.old && x.t.exitStatus === undefined && !closing.has(x.t))) flags[proj] = 'old';
      }
      staleFlags = flags;
    } catch (err) { trace('chat health failed: ' + (err && err.message || err)); } finally { healing = false; }
    for (const p of data.projects) { p.chatStale = !!staleFlags[p.name]; p.chatOld = staleFlags[p.name] === 'old'; }
    return before !== JSON.stringify(staleFlags);
  }
  const WATCH = path.join(WS, 'bin', 'shipm-watch');
  const runWatch = args => new Promise(res => execFile(PY3, [WATCH, ...args], { timeout: 120000 }, (err, out) => res({ ok: !err, out: String(out || '').trim() })));
  const NOTICE = path.join(STATE, 'health-notice.json');
  // The notice stays in the Health tab until dismissed (a pop-up vanishes while you read). A running fix writes busy:true with its steps so far.
  const writeNotice = (text, extra) => { if (leakBlock()) return; try { fs.mkdirSync(STATE, { recursive: true }); fs.writeFileSync(NOTICE, JSON.stringify({ ts: Date.now(), text, ...(extra || {}) })); } catch (err) { /* ignore */ } refresh(); };
  const notice = text => writeNotice(text);
  // ---- Health closed loop: bin/shipm-watch owns the contract (can / act / verify / contract, JSON); only this file can reach the chat terminals, so it runs the chain.
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const waitScale = () => testEnv('SHIPMIRACLE_FIX_WAIT_SCALE') !== undefined ? Math.max(0, +testEnv('SHIPMIRACLE_FIX_WAIT_SCALE') || 0) : 1;
  const clean = (x, n) => String(x == null ? '' : x).replace(/[\x00-\x1f\x7f-\x9f\s]+/g, ' ').trim().slice(0, n || 200);   // text that came from a process or a file: one short plain line
  const waitS = s => sleep(s * 1000 * waitScale());
  const watchJson = async args => { const r = await runWatch(args); let obj = null; try { obj = JSON.parse(r.out); } catch (err) { /* plain text */ } return { ok: r.ok, out: r.out, obj: obj && typeof obj === 'object' ? obj : null }; };
  let contractCache = null;
  async function opSpecs() {                                // the registry as the watcher declares it; the built-in table is only the fallback when the watcher cannot be asked
    if (contractCache && Date.now() - contractCache.at < 60000) return contractCache.ops;
    const r = await watchJson(['contract']);
    const ops = r.obj && r.obj.ops && typeof r.obj.ops === 'object' ? r.obj.ops : DEFAULT_OPS;
    contractCache = { at: Date.now(), ops }; return ops;
  }
  const readHealth = () => REPORTS.readJson(path.join(STATE, 'health.json'));
  const titles = new Map();
  let fixing = null;
  async function verifyOnce(id, since) {
    const r = await watchJson(['verify', id, ...(since ? ['--since', String(since)] : [])]);
    return r.obj ? r.obj : { gone: false, checked: false, detail: 'could not check: the watcher gave no answer' };
  }
  async function runFix(id, only) {
    if (leakBlock()) return;
    if (fixing) { vscode.window.showInformationMessage('A fix is already running for ' + fixing.title + '. Wait until it finishes.'); return; }
    const h0 = readHealth(); const item = h0 && (h0.items || []).find(i => i.id === id);
    const title = clean((item && (item.title || item.kind)) || titles.get(id) || 'that item', 120);
    if (!item) { notice('Already fixed: ' + title + ' is gone.'); return; }
    titles.set(id, title);
    const chain = only ? [only] : (Array.isArray(item.chain) ? item.chain.filter(x => typeof x === 'string') : []);
    if (only && !(item.actions || []).includes(only)) { vscode.window.showInformationMessage('That action is not available for this item any more; nothing done.'); refresh(); return; }
    if (!chain.length) { notice(title + ' is information only: nothing to fix.'); return; }
    fixing = { id, title }; const steps = []; let detail = '', done = false, unchecked = false, changed = false;
    const busy = text => writeNotice(text, { id, busy: true, steps: steps.slice() });
    const idleNow = v => v && (v.working === false || v.gone === true);
    try {
      const specs = await opSpecs();
      for (const op of chain) {
        const spec = specs[op];
        if (!spec || (spec.executor !== 'ext' && spec.executor !== 'watch') || (spec.executor === 'ext' && !EXT_OPS.includes(op))) { steps.push(op + ': skipped - not a known action'); continue; }
        const label = OP_LABEL[op] || op;
        busy(label + '…');
        const can = await watchJson(['can', op, id]);
        const c = can.obj;
        // who and what the fix is about comes from the watcher's FRESH scan, never from health.json alone: a planted or stale item must not steer a terminal
        if (c && (typeof c.project === 'string' || typeof c.kind === 'string') && (c.project !== item.project || c.kind !== item.kind)) { changed = true; break; }
        if (!c || c.ok !== true) {
          if (op === 'interrupt' && c && c.working === false) { steps.push(label + ': The chat was already idle'); continue; }
          steps.push(`${label}: skipped - ${clean(c && c.why) || 'the watcher could not confirm it applies now'}`); continue;
        }
        if (spec.executor === 'ext' && (typeof c.project !== 'string' || c.project !== item.project || !c.project)) { changed = true; break; }
        const project = c.project || item.project || '';
        let since = 0, performed = false, interruptedOnly = false;
        if (spec.executor === 'ext') {
          const p = known(project), t = p && chatTab(project), ins = t && await inspectChat(t);
          if (!p || !t || !ins || ins.project !== project) { steps.push(`${label}: skipped - no ${clean(project, 60) || 'project'} chat in this VS Code window`); continue; }
          chatOf.set(t, ins);
          if (op === 'interrupt') {
            if (c.working !== true) { steps.push(label + ': The chat was already idle'); continue; }      // `working` is the watcher's own answer (a frozen chat is working = true); the chat state word is not
            since = Math.floor(Date.now() / 1000); t.sendText('\u001b', false); performed = true; interruptedOnly = true;
          } else {
            busy('Saving your work first…');
            const cp = await watchJson(['act', 'checkpoint', project]);
            const text = clean((cp.obj && (cp.obj.did || cp.obj.why)) || cp.out || '');
            const saved = (cp.obj ? cp.obj.ok !== false : cp.ok) && (/nothing to save/i.test(text) || /(^|\s)wip\/\S+/.test(text));
            trace(`health fix: ${op} ${project}, checkpoint: ${text}`);
            if (!saved) { steps.push(label + ': stopped - could not save your work first; nothing closed'); detail = 'could not save your work first'; break; }
            closing.add(t); chatOf.delete(t); t.dispose();                                    // only the chat that was proved to be this project's, not every terminal
            const opened = openChat(p.dir, project, false, op === 'fresh');
            if (!opened) { steps.push(`${label}: the new chat did not open (${chatTab(project) ? 'another chat tab of this project is open' : 'the launch was refused'})`); continue; }
            steps.push(`${label}: done` + (/nothing to save/i.test(text) ? '' : ' (work saved to ' + clean((text.match(/wip\/\S+/) || [text])[0], 80) + ')'));
            performed = true;
          }
        } else {
          const r = await watchJson(['act', op, id]);
          const ok = r.obj ? r.obj.ok === true : r.ok;
          const said = clean(r.obj ? (r.obj.did || r.obj.why || '') : r.out);
          if (!ok) { steps.push(`${label}: failed - ${said || 'no reason given'}`); continue; }
          steps.push(`${label}: ${said || 'done'}`); performed = true;
        }
        if (!performed) continue;
        busy('Checking that it worked…');
        await waitS(spec.wait_s != null ? +spec.wait_s : 5);
        let v = null; const checks = Math.max(1, Math.min(5, +spec.checks || 1));
        for (let k = 0; k < checks; k++) {
          v = await verifyOnce(id, since || undefined);
          if (v.checked === false) unchecked = true; else unchecked = false;
          if (v.gone) break;
          if (interruptedOnly && (idleNow(v) || v.interrupted_at >= since)) break;
          if (k < checks - 1) await waitS(10);
        }
        detail = clean(v && v.detail) || detail;
        if (v && v.gone) { if (interruptedOnly) steps.push(label + ': Interrupted: the chat is idle now'); done = true; break; }
        if (interruptedOnly) { steps.push(label + ': ' + (v.checked === false ? 'could not check yet' : (idleNow(v) || v.interrupted_at >= since) ? 'Interrupted: the chat is idle now' : 'Esc had no visible effect (a tool call may be hung)')); continue; }
        steps[steps.length - 1] += ' (not gone yet)';
      }
      if (changed) { writeNotice('Not done: the item changed; refresh.', { id, busy: false, steps }); return; }
      if (!done && steps.length) {                                      // the chain is used up (or every step was skipped): one last look, so a skipped step on an item that went away is not called a failure
        const v = await verifyOnce(id);
        if (v.gone) done = true; else if (v.checked === false) unchecked = true; else { unchecked = false; detail = clean(v.detail) || detail; }
      }
      const ran = steps.length ? steps.join('; ') : 'nothing ran';
      if (done) writeNotice(`Fixed: ${title}. Ran: ${ran}.`, { id, busy: false, steps });
      else if (unchecked) writeNotice(`Could not check yet (a scan is running); the fix may still have worked: refresh in a minute. ${title}. Ran: ${ran}.`, { id, busy: false, steps });
      else writeNotice(`Not fixed: ${title}. Ran: ${ran}.${detail ? ' Now: ' + detail.replace(/[.\s]+$/, '') + '.' : ''}${item.next ? ' Next: ' + clean(item.next, 200).replace(/[.\s]+$/, '') + '.' : ''}`, { id, busy: false, steps });
    } catch (err) {
      trace('fix failed: ' + (err && err.stack || err));
      writeNotice(`Not fixed: ${title}. The fix stopped on an error (${clean(err && err.message || err, 120)}). Ran: ${steps.join('; ') || 'nothing'}.`, { id, busy: false, steps });
    } finally { fixing = null; setTimeout(refresh, 300); }
  }
  async function healthAction(m) {                          // Health tab buttons: whitelist, the item is re-read from health.json, nothing comes from the page except op + id
    if (leakBlock()) return;
    const op = String(m.op || ''), id = String(m.id || '');
    if (op === 'dismiss-model-reset') { try { fs.unlinkSync(path.join(STATE, 'model-reset.json')); } catch (err) { /* none */ } refresh(); return; }
    if (op === 'dismiss-project-notice') { try { fs.unlinkSync(PNOTICE); } catch (err) { /* none */ } refresh(); return; }
    if (op === 'dismiss-notice') { try { fs.unlinkSync(NOTICE); } catch (err) { /* none */ } refresh(); return; }
    if (op === 'auto-clean-on' || op === 'auto-clean-off' || op === 'resume-agents') { await runWatch(['act', op, '-']); if (op !== 'resume-agents') runWatch(['scan']).then(refresh); else refresh(); return; }
    if (!/^[A-Za-z0-9_.:-]{1,80}$/.test(id)) { trace('health: rejected id'); return; }
    if (op === 'fix') { await runFix(id); return; }
    const spec = (await opSpecs())[op];
    if (!spec || (spec.executor !== 'ext' && spec.executor !== 'watch') || (spec.executor === 'ext' && !EXT_OPS.includes(op))) { trace('health: rejected op ' + op.slice(0, 40)); return; }
    await runFix(id, op);                                   // a secondary button is a one-step chain: same checks, same verification
  }
  // ---- New project and team-flow level, from the panel. Every value is validated here; nothing comes from the page unchecked, no shell string.
  const PNOTICE = path.join(STATE, 'project-notice.json'), CREATING = path.join(STATE, 'project-creating.json');
  const pnotice = text => { if (leakBlock()) return; try { fs.mkdirSync(STATE, { recursive: true }); fs.writeFileSync(PNOTICE, JSON.stringify({ ts: Date.now(), text })); } catch (err) { /* ignore */ } refresh(); };
  chatNotify = pnotice;
  const lastLine = (s, fallback) => (String(s || '').split('\n').map(x => x.trim()).filter(Boolean).pop() || fallback).slice(0, 200);
  const KINDS = ['web', 'ios', 'python', 'api', 'home', 'notes', 'other'];
  const tidyName = raw => (typeof raw === 'string' ? raw : '').toLowerCase().replace(/[^a-z0-9._-]+/g, '-').replace(/^[-.]+/, '').slice(0, 40).replace(/[-.]+$/, '');   // like bin/new-project, plus: no leading dot, at most 40
  let creatingNow = false;
  async function newProjectAction(m) {
    if (leakBlock()) return;
    if (creatingNow) { trace('newproject: ignored, one is already running'); return; }          // one run at a time
    const name = tidyName(m.name), kind = typeof m.kind === 'string' ? m.kind : '', about = (typeof m.about === 'string' ? m.about : '').replace(/[\u0000-\u001f\u007f-\u009f\u2028\u2029]+/g, ' ').replace(/ +/g, ' ').trim().slice(0, 140);
    if (!/[a-z0-9]/.test(name)) { pnotice('Not created: give the project a name with at least one letter or digit.'); return; }
    if (['__proto__', 'constructor', 'prototype'].includes(name)) { pnotice('Not created: ' + name + ' is a reserved name; please pick another.'); return; }
    if (!KINDS.includes(kind)) { pnotice('Not created: unknown type.'); return; }
    const dir = path.join(DEV, name);
    if (fs.existsSync(dir)) { pnotice('Not created: ' + name + ' already exists.'); return; }
    creatingNow = true;
    try { fs.mkdirSync(STATE, { recursive: true }); fs.writeFileSync(CREATING, JSON.stringify({ name, ts: Date.now() })); } catch (err) { /* the row is a courtesy */ }
    refresh();
    const env = { ...process.env, PATH: [process.env.PATH, '/opt/homebrew/bin', '/usr/local/bin', path.join(os.homedir(), '.local', 'bin')].filter(Boolean).join(':') };
    const argv = [path.join(WS, 'bin', 'new-project'), name, '--type', kind, ...(about ? ['--about', about] : []), '--no-open'];
    const r = await new Promise(res => { try { execFile('/bin/bash', argv, { timeout: 180000, maxBuffer: 1 << 20, env }, (err, out, errout) => res({ err, errout })); } catch (err) { res({ err, errout: String(err && err.message) }); } });
    creatingNow = false;
    try { fs.unlinkSync(CREATING); } catch (err) { /* none */ }
    if (r.err && r.err.killed) { trace('newproject: stopped after the timeout'); pnotice(`Stopped after 3 minutes; ${shownPath(path.join(DEV, name))} may be half-created: finish with bin/new-project ${name} in a terminal.`); setTimeout(refresh, 800); return; }
    if (r.err && r.err.code !== 3) { trace('newproject failed: ' + lastLine(r.errout, r.err.message)); pnotice('Not created: ' + lastLine(r.errout, r.err.message || 'failed')); return; }
    const card = ' Its card is below: click it to open the chat.';      // nothing opens by itself: no terminal, no pop-up, no focus change
    pnotice(r.err ? `Created ${name} (GitHub not set up: ${lastLine(r.errout, 'see bin/new-project in a terminal')}).${card}` : `Created ${name}.${card}`);      // exit 3 = the project is complete, only GitHub is missing
    setTimeout(refresh, 800);
  }
  // Activate agent...: drafts in <project>/.claude/agents-drafts/*.md and untrusted project agents; the owner picks one, `shipm agents activate` does the work.
  const AGENT_NAME = /^[a-z][a-z0-9-]{0,63}$/, PRIVILEGED_ROLES = 'plan test review report'.split(' ');   // same set as shipmiracle/agents.py PRIVILEGED
  async function activateAgentAction(m) {
    if (leakBlock()) return;
    const p = known(typeof m.project === 'string' ? m.project : '');
    if (!p || p.held || p.name.startsWith('-') || !/^[A-Za-z0-9._-]+$/.test(p.name)) { pnotice('Agent not activated: unknown project.'); return; }
    const items = [];
    const fileOf = i => i.draft ? path.join(p.dir, '.claude', 'agents-drafts', i.label + '.md') : path.join(p.dir, '.claude', 'agents', i.label + '.md');
    try { for (const f of fs.readdirSync(path.join(p.dir, '.claude', 'agents-drafts'))) if (f.endsWith('.md') && AGENT_NAME.test(f.slice(0, -3))) items.push({ label: f.slice(0, -3), draft: true }); } catch (err) { /* no drafts */ }
    for (const n of ((p.team && p.team.untrusted) || [])) if (typeof n === 'string' && AGENT_NAME.test(n) && !items.some(i => i.label === n)) items.push({ label: n, draft: false });
    // what the owner is about to trust, read from the file itself: claimed role, path, sha256 prefix, flags
    const infoOf = i => {
      const file = fileOf(i); const rc = REPORTS.readCapped(file, 262144), text = rc.ok ? rc.text : '';      // capped, no symlink: unreadable is shown as unknown
      const role = ((text.match(/^Flow role:[ \t]*(\w+)/m) || [])[1] || 'unknown').toLowerCase();
      const nm = (text.match(/^name:[ \t]*(\S+)/m) || [])[1];
      const ui = ((p.team && p.team.untrustedInfo) || []).find(x => x && x.name === i.label) || {};
      const flags = [nm && nm !== i.label ? 'name mismatch' : '', ui.mismatch ? 'name mismatch' : '', ui.shadow ? 'unmarked shadow' : ''].filter((x, k, arr) => x && arr.indexOf(x) === k);
      return { file, role, sha: text ? crypto.createHash('sha256').update(rc.buf).digest('hex').slice(0, 12) : 'unreadable', flags };
    };
    const entries = items.map(i => ({ ...i, info: infoOf(i) }));
    const label = e => `${e.label}: role ${e.info.role}, ${e.draft ? 'draft' : 'untrusted'}, ${path.relative(p.dir, e.info.file)}, sha ${e.info.sha}${e.info.flags.length ? ', ' + e.info.flags.join(', ') : ''}`;
    if (!entries.length) { pnotice(`${p.name}: no drafts in .claude/agents-drafts and no untrusted agents. Nothing to activate.`); return; }
    const pick = await vscode.window.showQuickPick(entries.map(e => ({ label: e.label, description: `role ${e.info.role} · ${e.draft ? 'draft' : 'untrusted'}`, detail: `${path.relative(p.dir, e.info.file)} · sha256 ${e.info.sha}${e.info.flags.length ? ' · ' + e.info.flags.join(' · ') : ''}` })), { placeHolder: `Activate which ${p.name} agent? The owner decides; this trusts the file as it is now.` });
    const name = pick && typeof pick.label === 'string' ? pick.label : '';
    if (!name) return;
    const e = entries.find(x => x.label === name);
    if (!AGENT_NAME.test(name) || !e) { pnotice('Agent not activated: not an agent name.'); return; }
    try { await vscode.window.showTextDocument(await vscode.workspace.openTextDocument(vscode.Uri.file(e.info.file)), { preview: true }); } catch (err) { /* the confirmation below still shows everything */ }   // read it before you trust it
    const role = e.info.role;
    if (!/^[a-z]+$/.test(role) || role === 'unknown') { pnotice('Agent not activated: the file has no valid Flow role line.'); return; }
    const c1 = await vscode.window.showWarningMessage(`Activate ${name} in ${p.name}?\n${label(e)}\nThis trusts the file exactly as it is now.`, { modal: true }, 'Activate');
    if (c1 !== 'Activate') return;
    if (PRIVILEGED_ROLES.includes(role)) {
      const c2 = await vscode.window.showWarningMessage(`${name} claims the privileged role "${role}".\nA ${role} agent can approve plans or verdicts and unlock the gate. Only continue if you have read the file and wrote or reviewed it yourself.`, { modal: true }, `Activate as ${role}`);
      if (c2 !== `Activate as ${role}`) return;
    }
    const env = { ...process.env, PATH: [process.env.PATH, '/opt/homebrew/bin', '/usr/local/bin', path.join(os.homedir(), '.local', 'bin')].filter(Boolean).join(':') };
    const r = await new Promise(res => { try { execFile(path.join(WS, 'bin', 'shipm'), ['agents', 'activate', p.name, name, '--confirm-role', role], { timeout: 30000, maxBuffer: 1 << 20, env }, (err, out, errout) => res({ err, out, errout })); } catch (err) { res({ err, out: '', errout: String(err && err.message) }); } });
    if (r.err) { trace('activate agent failed: ' + lastLine(r.errout, r.err.message)); pnotice('Agent not activated: ' + lastLine(r.errout || r.out, r.err.message || 'failed')); return; }
    pnotice(lastLine(r.out, `Activated ${name} in ${p.name}.`));
    setTimeout(refresh, 800);
  }
  const ser = v => v && typeof v === 'object' && !Array.isArray(v) ? '{' + Object.entries(v).map(([k, x]) => JSON.stringify(k) + ': ' + ser(x)).join(', ') + '}' : JSON.stringify(v);   // keeps flow.json in its one-line-per-key style
  // Level pill (review of P4-P6, M6). Decision: the pill still writes config/flow.json itself (the one file the gate reads for the level) and does NOT call
  // `shipm playbook set level`: that command needs the owner to type the value at /dev/tty (confirm_owner, P5 security M5) and the panel has no terminal. A token file
  // written by the panel would be writable by a chat as well (same user), so it would weaken M5. Nor is .shipmiracle/playbook.json edited from here: its sha is the registry
  // trust anchor, so a hand edit would make the playbook untrusted. Consequence: playbook.json keeps a stale `level` mirror until the next `shipm playbook set level`
  // (flow.json is authoritative; `shipm playbook show` prints the flow.json level; the next `set` sees the difference and reconciles both files).
  let levelBusy = false;
  async function levelAction(m) {
    if (leakBlock()) return;
    if (levelBusy) return; levelBusy = true;
    try {
      const name = String(m.project || ''), to = String(m.level || m.to || '');
      if (to !== 'strict' && to !== 'warn') { trace('level: refused target ' + to); return; }            // never off
      let fresh; try { fresh = await collect(); } catch (err) { pnotice('Level not changed: could not read the projects.'); return; }
      const p = (fresh.projects || []).find(x => x.name === name);
      if (!p || name === '__proto__') { trace('level: unknown project'); return; }
      const sw = p.levelSwitch && p.levelSwitch.ok === false ? p.levelSwitch : null;   // data.js decides, per project (only this project's own state blocks) (raw states, limits, recent agents and flow state, chat health)
      if (sw) { pnotice('Level not changed: ' + (sw.why || 'not now.') + ' A change while a chat is mid-turn blocks that chat once; try again when everything is idle.'); return; }
      if (p.state === 'working' || p.state === 'needs-input') { pnotice('Level not changed: ' + name + ' is working. Every chat of this project watches this file; try again when it is idle.'); return; }
      if (p.held) { pnotice('Level not changed: ' + name + ' is held.'); return; }
      const file = path.join(WS, 'config', 'flow.json'); let cfg;
      cfg = REPORTS.readJson(file);
      const LV = ['strict', 'warn', 'off'];
      if (!cfg || typeof cfg !== 'object' || Array.isArray(cfg) || !LV.includes(cfg.default) || (cfg.projects !== undefined && (!cfg.projects || typeof cfg.projects !== 'object' || Array.isArray(cfg.projects)))) { pnotice('Level not changed: config/flow.json is missing or malformed. Fix it by hand.'); return; }
      const projects = { ...(cfg.projects || {}) }, from = LV.includes(projects[name]) ? projects[name] : cfg.default;
      if (from === 'off') { pnotice('Level not changed: ' + name + ' has the gate off; set it by hand.'); return; }
      if (from === to) return;
      if (to === cfg.default) delete projects[name]; else projects[name] = to;
      const out = { ...cfg, projects }, tmp = file + '.' + process.pid + '.tmp';
      try {
        const body = '{\n' + Object.entries(out).map(([k, v]) => '  ' + JSON.stringify(k) + ': ' + ser(v)).join(',\n') + '\n}\n';
        fs.writeFileSync(tmp, body); try { fs.chmodSync(tmp, fs.statSync(file).mode & 0o777); } catch (err) { /* keep default mode */ }
        fs.renameSync(tmp, file);
      } catch (err) { try { fs.unlinkSync(tmp); } catch (e2) { /* none */ } pnotice('Level not changed: could not write config/flow.json.'); return; }
      try { fs.mkdirSync(STATE, { recursive: true }); fs.appendFileSync(path.join(STATE, 'flow-events.jsonl'), JSON.stringify({ ts: Math.floor(Date.now() / 1000), project: name, event: 'level_changed', by: 'owner-panel', from, to }) + '\n'); } catch (err) { /* the file change stands */ }
      const msg = `Team flow: ${name} ${from} -> ${to} (owner, panel)`;
      const g = await new Promise(res => { try { execFile(GIT, ['-C', WS, 'commit', '-m', msg, '--', 'config/flow.json'], { timeout: 60000 }, (err, out2, errout) => res({ err, errout: String(errout || out2 || '') })); } catch (err) { res({ err, errout: String(err && err.message) }); } });
      pnotice(g.err ? 'Saved, not committed: ' + lastLine(g.errout, g.err.message || 'git failed') : name + ' team flow: ' + from + ' -> ' + to);
    } catch (err) { trace('level failed: ' + (err && err.stack || err)); } finally { levelBusy = false; }
  }
  // ---- Panel v3 card buttons (primary + ⋯ menu + autopilot chip). The panel never writes the playbook, a charter or an approval: `shipm playbook set` needs the owner at /dev/tty
  // and a plan counts as approved only by the owner's words in the chat. So: plan -> open the plan and say so; setup / autopilot -> tell the owner the exact command (the in-panel
  // pickers come in later panel tasks); start CR -> a message into the chat (never typed into a busy chat); report -> open a file that is inside the project folder.
  async function cardAction(m) {
    if (leakBlock()) return;
    const p = (data.projects || []).find(x => x.name === String(m.project || '')); if (!p || !p.dir) return;
    const act = String(m.act || ''), busy = p.state === 'working' || p.state === 'needs-input' || (p.agents || []).length > 0;
    if (act === 'plan') {
      let file = '';
      try { const dir = path.join(p.dir, 'docs', 'plans'); file = fs.readdirSync(dir).filter(f => /\.md$/.test(f)).map(f => path.join(dir, f)).map(f => ({ f, t: fs.statSync(f).mtimeMs })).sort((x, y) => y.t - x.t)[0]; file = file ? file.f : ''; } catch (err) { file = ''; }
      if (file) { try { await vscode.window.showTextDocument(await vscode.workspace.openTextDocument(vscode.Uri.file(file)), { preview: true }); } catch (err) { /* the message below still tells what to do */ } }
      else openChat(p.dir, p.name);
      vscode.window.showInformationMessage(`Read the plan for ${p.name}, then type "approved" in the chat. The panel never sends your approval.`);
      return;
    }
    if (act === 'openreport') {                                              // inside the project, or exactly the two state report folders (stage reports, digests); a symlink out is refused
      const rel = String(m.report || ''); if (!rel || rel.includes('\0')) return;
      const g = REPORTS.guardAny(STATE, p.dir, rel); if (!g.ok) { pnotice(STR.reports.notOpened.replace('{why}', g.why + '.')); return; }
      try { await vscode.window.showTextDocument(await vscode.workspace.openTextDocument(vscode.Uri.file(g.file)), { preview: true }); }
      catch (err) { pnotice('Report not found: ' + rel.slice(0, 120)); }
      return;
    }
    if (act === 'start') {
      const cr = String(m.cr || '');
      if (!/^CR-\d{1,6}$/.test(cr) || !(p.cr || []).some(c => c.id === cr && c.status === 'queued')) { pnotice('Start not sent: ' + cr + ' is not queued.'); return; }
      openChatWith(p.dir, p.name, `Pick up ${cr}: run shipm cr start ${cr}, then continue with its first stage.`, busy); setTimeout(refresh, 800); return;
    }
    if (act === 'setup') { pnotice(`${p.name} has no playbook yet. In a terminal inside the project, type: shipm playbook set type <software|app|content|research|ops|notes>. The in-panel type picker comes in a later update.`); return; }
    if (act === 'ap') {
      const to = String(m.to || ''); if (!['manual', 'guided', 'full'].includes(to) || !p.playbook) return;
      if (to === 'full') { pnotice(`Full autopilot for ${p.name} is set up in the charter editor: open the autopilot chip and choose Full.`); return; }
      const back = to === 'guided' && p.playbook.autopilot === 'full';       // Back to guided is always allowed, even while the run works
      if (!back && (p.held || busy)) { pnotice(STR.autopilot.notNow.replace('{project}', p.name)); return; }
      if (!back && p.playbook.autopilot === to) { pnotice(`${p.name} is already on ${STR.autopilot[to].name}.`); return; }
      const cmds = back ? CHARTER.backToGuidedArgv(shipmiracleBin(), p.name) : CHARTER.apLevelArgv(shipmiracleBin(), p.name, to);
      if (ownerTerminal(p, cmds, { kind: back ? 'back' : 'level', to, run: false })) pnotice((back ? STR.autopilot.termBack : STR.autopilot.termLevel).replace('{project}', p.name).replace('{to}', to));
      return;
    }
    if (act === 'allowterm') {                                              // hard stop: the command is typed into a terminal but NOT run; the owner presses Enter. Nothing goes to a chat.
      const stop = p.autopilot && p.autopilot.stop; if (!stop) return;
      let cmds; try { cmds = CHARTER.allowArgv(shipmiracleBin(), p.name, stop.id); } catch (err) { pnotice('No command opened: ' + err.message); return; }
      if (ownerTerminal(p, cmds, { kind: 'allow', run: false })) pnotice(STR.autopilot.termDecide.replace('{project}', p.name));
      return;
    }
    if (act === 'apstop') {                                                 // option C Stop: `shipm autopilot stop`, typed not run
      if (!(p.autopilot && (p.autopilot.until === 'disabled' || p.autopilot.state === 'running'))) { pnotice('Not typed: no autopilot run to stop.'); return; }
      let cmds; try { cmds = CHARTER.stopArgv(shipmiracleBin(), p.name); } catch (err) { pnotice('No command opened: ' + err.message); return; }
      if (ownerTerminal(p, cmds, { kind: 'stop', run: false })) pnotice(STR.run.termStop.replace('{project}', p.name));
      return;
    }
    if (act === 'tlmark' || act === 'tlcr') {                               // two-level timeline buttons: re-check everything, then only TYPE the command (never Enter); gated on caps.release
      const TLM = require('./timeline'), tn = k => STR.tl[k];
      if (!(data.capabilities && data.capabilities.release === true) || !p.playbook || !p.release || p.held) { pnotice(STR.tl.notMark.replace('{why}', tn('whyNoCap'))); return; }
      if (act === 'tlcr') {
        let line; try { line = TLM.openLine(shipmiracleBin(), p.name); } catch (err) { pnotice('No command opened: ' + err.message); return; }
        if (ownerTerminal(p, null, { kind: 'cropen', run: false, line, back: 1 })) pnotice(STR.tl.typedOpen.split('{project}').join(p.name));
        return;
      }
      const v = TLM.ver(String(m.verb || '')), r = p.release, why = k => pnotice(STR.tl.notMark.replace('{why}', tn(k).replace('{v}', v)));
      if ((p.cr || []).some(c => ['open', 'queued', 'blocked'].includes(c.status))) { why('whyOpen'); return; }
      if (!TLM.verOk(v) || !r.working || TLM.ver(r.working.version) !== v || !r.last || TLM.cmpVer(v, TLM.ver(r.last.version)) <= 0) { why('whyVersion'); return; }
      if (!(r.since && r.since.changes > 0)) { why('whyNothing'); return; }
      let cmds; try { cmds = TLM.markArgv(shipmiracleBin(), p.name, v); } catch (err) { pnotice('No command opened: ' + err.message); return; }
      if (ownerTerminal(p, cmds, { kind: 'release', run: false })) pnotice(STR.tl.typedMark.replace('{project}', p.name).replace('{v}', v));
      return;
    }
    if (act === 'cverb') {                                                  // option C verbs: checkpoint | resume | admit CR-x | drop CR-x. Typed, never run; the engine side is built later, so they are refused until the data says it exists.
      const verb = String(m.verb || ''), cr = String(m.cr || ''), ap = p.autopilot;
      if (!(data.autopilot && data.autopilot.until_disabled_supported === true)) { pnotice(STR.cwait.notReady); return; }
      if (!ap || ap.until !== 'disabled') { pnotice('Not typed: no run that lasts until you disable it.'); return; }
      if (verb === 'admit' && !(ap.waiting || []).some(w => w.id === cr)) { pnotice('Not typed: ' + cr + ' is not waiting for your OK.'); return; }
      if (verb === 'drop' && (cr !== ap.cr || ap.state !== 'paused')) { pnotice('Not typed: ' + cr + ' is not the paused request.'); return; }
      if ((verb === 'checkpoint' || verb === 'resume') && ap.state !== 'paused') { pnotice('Not typed: the run is not paused.'); return; }
      let cmds; try { cmds = CHARTER.cVerbArgv(shipmiracleBin(), p.name, verb, cr); } catch (err) { pnotice('No command opened: ' + err.message); return; }
      if (ownerTerminal(p, cmds, { kind: 'cverb', run: false })) pnotice(STR.cwait.typed.replace('{cmd}', 'shipm autopilot ' + verb + (cr ? ' ' + cr : '')).replace('{project}', p.name));
      return;
    }
    if (act === 'showterm') { const w = apWaits.get(p.name); if (w && w.term && !w.term.exitStatus) w.term.show(); return; }
  }
  // ---- Owner terminal route (autopilot level, charter, back to guided, allow). The commands are argv arrays quoted by charter.js; the extension never runs the charter CLI itself (execFile),
  // because `shipm playbook set` / `autopilot charter set|start|stop` need the owner at a terminal. The terminal is visible and the owner confirms there.
  const shipmiracleBin = () => path.join(WS, 'bin', 'shipm');
  const apWaits = new Map();                                                // project -> { kind, to, at, term }
  function ownerTerminal(p, cmds, o) {
    let line; try { line = o.line || CHARTER.joinCmds(cmds); } catch (err) { pnotice(STR.autopilot.termFail.replace('{why}', String(err && err.message))); return false; }
    const title = o.title || `Shipmiracle · ${p.name}`;
    let term = (vscode.window.terminals || []).find(x => x && x.name === title && !x.exitStatus);
    if (term && o.kind === 'init' && o.run === true && ((setupWait && setupWait.term === term) || shellRunning.has(term))) { pnotice(STR.setup.stillRunning); return false; }      // never type into a terminal that still runs a command (the line would go to that command's input)
    if (!term) term = vscode.window.createTerminal({ name: title, cwd: p.dir });
    term.show();
    const runIt = o.run === true && o.kind === 'init';
    term.sendText(runIt ? '\u0005\u0015' : '\u0015', false);                // Ctrl-U clears what an earlier click left on the prompt line, so two prefills never run together; a run line also goes to the END first (Ctrl-E), so the whole line is cleared, not only the part before the cursor
    term.sendText(line, runIt);                                           // prefilled, not run: the owner reads the line and presses Enter. ONLY the Setup operations (kind 'init') run with Enter (see setupRun)
    if (o.back > 0) term.sendText('\u001b[D'.repeat(Math.min(o.back, 400)), false);   // put the cursor back where the owner types the missing value (never an Enter)
    if (['full', 'back', 'level'].includes(o.kind)) { apWaits.set(p.name, { kind: o.kind, to: o.to || '', at: Date.now(), term }); waitPoll(); }
    if (o.kind === 'init' && o.run === true) setupWatch(term);
    return true;
  }
  let interviewPoll = null, waitTimer = null;
  function waitPoll() { if (waitTimer) return; waitTimer = setInterval(() => { if (!apWaits.size) { clearInterval(waitTimer); waitTimer = null; return; } refresh(); }, 3000); }
  function apWaitView(p) {                                                   // the "Waiting for you in the terminal" row: until the command's effect shows in the data, the terminal closes, or 10 minutes
    const w = apWaits.get(p.name); if (!w) return null;
    const ap = p.autopilot, lvl = p.playbook && p.playbook.autopilot;
    const done = w.kind === 'full' ? !!(ap && ap.state === 'running') : w.kind === 'back' ? lvl === 'guided' : lvl === w.to;
    if (done || Date.now() - w.at > 600000 || (w.term && w.term.exitStatus)) { apWaits.delete(p.name); return null; }
    return { kind: w.kind, to: w.to, at: w.at };
  }
  // Safe mode = the gate level. Typed as `shipm playbook set level strict|warn` (needs the owner at a terminal); Off is never set from the panel.
  async function safeAction(m) {
    if (leakBlock() || !m || typeof m !== 'object') return;
    const p = known(typeof m.project === 'string' ? m.project : ''), to = m.to;
    if (!p || !p.playbook || !CHARTER.SAFE_NAME.test(p.name) || p.name.startsWith('-') || !['strict', 'warn'].includes(to)) { pnotice('Not typed: unknown project or level.'); return; }
    const busy = p.state === 'working' || p.state === 'needs-input' || (p.agents || []).length > 0;
    if (p.held) { pnotice(STR.ap.held); return; }
    if (busy || (p.levelSwitch && p.levelSwitch.ok === false)) { pnotice(STR.safe.busy); return; }
    if (p.level === to) return;
    let cmds; try { cmds = CHARTER.safeArgv(shipmiracleBin(), p.name, to); } catch (err) { pnotice('No command opened: ' + err.message); return; }
    if (ownerTerminal(p, cmds, { kind: 'safe', run: false })) pnotice(STR.safe.typed.replace('{project}', p.name));
  }
  const untilB = new Map();                                                 // project -> ends of the last "I stop it" start: display memory only, Shipmiracle never reads it
  async function charterAction(m) {
    if (leakBlock() || !m || typeof m !== 'object' || m.op !== 'start') return;
    const p = known(typeof m.project === 'string' ? m.project : '');
    if (!p || !p.playbook || p.held || !CHARTER.SAFE_NAME.test(p.name) || p.name.startsWith('-')) { pnotice('Not started: unknown project.'); return; }
    if (p.state === 'working' || p.state === 'needs-input' || (p.agents || []).length > 0) { pnotice('Not started: ' + STR.charter.whyBusy.replace('{project}', p.name)); return; }
    if (p.level !== 'strict') { pnotice('Not started: ' + STR.charter.whyLevel); return; }
    if (p.playbook.type !== 'software') { pnotice('Not started: ' + STR.charter.whyType); return; }
    if (p.autopilot && p.autopilot.enabled === false) { pnotice('Not started: ' + STR.charter.whySwitch); return; }
    const open = (p.cr || []).filter(c => c.status === 'open' || c.status === 'queued').map(c => c.id);
    const str = v => typeof v === 'string' ? v : '';
    const untilC = m.until === 'c' || m.until === 'disabled';
    if (untilC && !(data.autopilot && data.autopilot.until_disabled_supported === true)) { pnotice('Not started: engine not ready.'); return; }
    if (untilC) { const bad = CHARTER.untilCheck(m.day, m.crsDay, m.budget); if (bad) { pnotice('Not started: ' + bad); return; } }
    const r = CHARTER.check({ goal: str(m.goal), scope: str(m.scope), budget: str(m.budget), time: untilC ? '3' : str(m.time), depsMode: m.depsMode === 'listed' ? 'listed' : 'none', deps: str(m.deps), ends: Array.isArray(m.ends) ? m.ends.filter(x => typeof x === 'string') : [] }, open);
    if (!r.ok) { pnotice('Not started: ' + Object.values(r.errors)[0]); return; }
    if (untilC) Object.assign(r.value, { until: 'disabled', day: Number(m.day), crsDay: Number(m.crsDay) });
    if (m.until === 'b') untilB.set(p.name, r.value.ends.join(',')); else untilB.delete(p.name);
    let cmds; try { cmds = CHARTER.charterArgv(shipmiracleBin(), p.name, r.value, p.playbook.autopilot !== 'full'); } catch (err) { pnotice(STR.autopilot.termFail.replace('{why}', String(err && err.message))); return; }
    if (ownerTerminal(p, cmds, { kind: 'full', run: false })) pnotice(STR.autopilot.termFull.replace('{project}', p.name));
  }
  // ---- F7 Set aside. The page sends {type:'aside', op:'aside'|'unaside', project} or {op:'dismiss', project, ts}. The extension checks the project and the CLI's own answer (p.aside.canAside / on,
  // caps.aside) and only TYPES `shipm project aside|unaside NAME` into the owner's terminal, never pressing Enter. A dismissed "Brought back" notice is remembered in memory for this window.
  const asideDismissed = new Set();
  const asideNoticeForPage = () => (Array.isArray(data.asideReturned) ? data.asideReturned : []).filter(n => !asideDismissed.has(n.project + '|' + n.ts));
  function asideAction(m) {
    if (leakBlock() || !m || typeof m !== 'object' || typeof m.op !== 'string') return;
    const name = typeof m.project === 'string' && m.project.length <= 100 ? m.project : '';
    if (m.op === 'dismiss') { if (name && Number.isFinite(Number(m.ts))) asideDismissed.add(name + '|' + Number(m.ts)); if (view) render(); return; }
    if (m.op !== 'aside' && m.op !== 'unaside') return;
    const p = name && known(name); if (!p || !(data.capabilities && data.capabilities.aside === true) || !p.aside) return;
    if (m.op === 'aside' && !p.aside.canAside) { pnotice(p.aside.on ? STR.aside.typed : (p.aside.reason || STR.aside.error)); return; }
    if (m.op === 'unaside' && !p.aside.on) return;
    let cmds; try { cmds = CHARTER.asideArgv(shipmiracleBin(), p.name, m.op); } catch (err) { pnotice('No command opened: ' + err.message); return; }
    if (ownerTerminal(p, cmds, { kind: 'aside', run: false })) pnotice(STR.aside.typed);
  }
  // ---- G2 Tidy up card. The page sends {type:'tidy-open'} and NOTHING else is read from the message. The extension builds the whole argument list itself and only TYPES it (no Enter); `shipm tidy --all` only reads.
  function tidyOpen() {
    if (leakBlock()) return;
    const shipm = shipmiracleBin();
    if (!fs.existsSync(shipm)) { pnotice(STR.tidy.noTool); return; }
    ownerTerminal({ name: 'tidy', dir: WS }, [[shipm, 'tidy', '--all']], { kind: 'tidy', run: false, title: 'Shipmiracle · tidy' });
  }
  // ---- F5 Toolbox and F6 Describe your work. Both only TYPE commands into the owner's terminal (no Enter) after checking the CLI's capability flag and the project's own data; the page names a project and,
  // for the toolbox, an asset path that must equal one of the assets the CLI listed (a path of its own making is refused).
  const needCap = key => !!(data.capabilities && data.capabilities[key] === true);
  const busyProj = p => p.state === 'working' || p.state === 'needs-input' || (p.agents || []).length > 0;
  // F5 Learn: Copy for a proposed asset's add command. The page names a project and a row number; the text copied is the command this side built (proposed.js) and re-checks against its strict shape.
  // Nothing is run or typed: the owner pastes it into a terminal. The engine refuses `asset add` from a chat.
  async function proposedAction(m) {
    if (leakBlock() || !m || typeof m !== 'object' || m.op !== 'copy') return;
    const p = known(typeof m.project === 'string' && m.project.length <= 100 ? m.project : ''); if (!p || !needCap('toolbox') || !p.playbook || !Array.isArray(p.proposed)) return;
    const a = Number.isInteger(m.i) ? p.proposed[m.i] : null; if (!a || !PROPOSED.CMD.test(a.command || '')) return;
    try { await vscode.env.clipboard.writeText(a.command); pnotice(STR.proposed.copied); } catch (err) { pnotice(STR.proposed.error); }
  }
  function toolboxAction(m) {
    if (leakBlock() || !m || typeof m !== 'object') return;
    const p = known(typeof m.project === 'string' && m.project.length <= 100 ? m.project : ''); if (!p || !needCap('toolbox') || !p.toolbox || !p.playbook) return;
    if (!['remove', 'resign', 'add'].includes(m.op)) return;
    if (busyProj(p)) { pnotice(STR.toolbox.held); return; }
    let cmds, opts = { kind: 'toolbox', run: false };
    try {
      if (m.op === 'add') {
        if (!CHARTER.SAFE_NAME.test(p.name) || p.name.startsWith('-')) throw new Error('unsafe project name');
        const head = CHARTER.quote(shipmiracleBin()) + ' playbook asset add ', tail = ' --stage  --purpose "" --project ' + CHARTER.quote(p.name);
        opts = { ...opts, line: head + tail, back: tail.length }; cmds = [];
      } else {
        const a = typeof m.path === 'string' ? p.toolbox.assets.find(x => x.path === m.path) : null; if (!a) return;
        cmds = m.op === 'remove' ? CHARTER.assetArgv(shipmiracleBin(), p.name, 'remove', a) : CHARTER.assetArgv(shipmiracleBin(), p.name, 'add', a);
      }
    } catch (err) { pnotice('No command opened: ' + err.message); return; }
    if (ownerTerminal(p, cmds, opts)) pnotice(STR.toolbox.typed);
  }
  async function describeAction(m) {
    if (leakBlock() || !m || typeof m !== 'object') return;
    const p = known(typeof m.project === 'string' && m.project.length <= 100 ? m.project : ''); if (!p || !needCap('interview')) return;
    const op = m.op;
    if (op === 'show') { const term = (vscode.window.terminals || []).find(x => x && x.name === `Shipmiracle · ${p.name}` && !x.exitStatus); if (term) term.show(); return; }
    if (op === 'open') { const f = INTERVIEW.draftFile(p.dir); if (!f) { pnotice(STR.describe.notDraft); return; } try { await vscode.window.showTextDocument(await vscode.workspace.openTextDocument(vscode.Uri.file(f)), { preview: true }); } catch (err) { pnotice(STR.describe.errDraft); } return; }
    let cmds;
    try {
      if (op === 'start') {
        if (p.playbook || p.held) return; if (busyProj(p)) { pnotice(STR.describe.busy.replace('{project}', p.name)); return; }
        if (m.mode !== 'short' && m.mode !== 'long') return; cmds = CHARTER.interviewArgv(shipmiracleBin(), p.name, 'start', m.mode);
      } else if (op === 'resume' || op === 'restart') {
        if (!p.mirror || !['paused', 'error', 'draft', 'asking'].includes(p.mirror.status)) return; if (busyProj(p)) { pnotice(STR.describe.busy.replace('{project}', p.name)); return; }
        cmds = CHARTER.interviewArgv(shipmiracleBin(), p.name, op);
      } else if (op === 'set') {
        if (!p.mirror || p.mirror.status !== 'draft' || !p.mirror.draftOk) { pnotice(STR.describe.notDraft); return; }
        cmds = CHARTER.fromDraftArgv(shipmiracleBin(), p.name);
      } else return;
    } catch (err) { pnotice('No command opened: ' + err.message); return; }
    if (ownerTerminal(p, cmds, { kind: 'describe', run: false })) pnotice(op === 'start' ? STR.describe.typed : op === 'set' ? STR.describe.typedSet : STR.describe.typedResume);
  }
  // ---- Reports tab (read-only) and Setup tab. The page sends only ids; the extension looks them up again (the index and the init check), guards every path, and never runs `shipm init` itself:
  // Fix / Skip / Undo / Quick setup run `shipm init --step|--skip|--undo|--prefs ...` in the owner's visible terminal. Only `--step` of some rows asks a question there (SETUP_PROMPT_ROWS below); `--skip`, `--undo`, `--prefs` and the other steps apply AT ONCE. All need an owner at a terminal (paths.require_owner).
  let rviewState = null, setupState = null;
  const autoSetup = process.env.SHIPMIRACLE_TEST !== '1' || testEnv('SHIPMIRACLE_EXT_SETUP') === '1';           // tests start the check only when they ask for it
  const dirOf = name => { const q = known(typeof name === 'string' ? name : ''); return q && q.dir ? q.dir : ''; };
  const setupChecker = SETUP.makeChecker({ shipm: path.join(WS, 'bin', 'shipm'), stateDir: STATE, runner: execFile, env: { ...process.env, PATH: [process.env.PATH, '/opt/homebrew/bin', '/usr/local/bin', path.join(os.homedir(), '.local', 'bin')].filter(Boolean).join(':') } });
  const setupRefresh = force => setupChecker.get(!!force).then(v => { if (v !== setupState) { setupState = v; if (view) render(); } }).catch(err => trace('setup check failed: ' + (err && err.message)));
  async function reportAction(m) {
    const op = String(m.op || ''), id = typeof m.id === 'string' && m.id.length <= 120 ? m.id : '';
    if (op === 'back') { rviewState = null; if (view) render(); return; }
    if (op === 'retry') { refresh(); return; }
    if (!/^[A-Za-z0-9._-]{1,120}$/.test(id)) return;
    if (op === 'view') {
      const r = REPORTS.load(STATE, dirOf, id);
      rviewState = r.ok ? { id, title: r.item.title || r.item.id, verdict: r.item.verdict, ts: r.item.ts, project: r.item.project, kind: r.item.kind, private: r.item.private, text: r.text } : { id, error: STR.reports.notOpened.replace('{why}', r.why) };
      if (view) render(); return;
    }
    if (op !== 'open' && op !== 'copy') return;
    const idx = REPORTS.readIndex(STATE), item = idx.items.find(x => x.id === id), g = REPORTS.guardItem(STATE, dirOf, item);
    if (!g.ok) { pnotice(STR.reports.notOpened.replace('{why}', g.why + '.')); return; }
    if (op === 'open') { try { await vscode.window.showTextDocument(await vscode.workspace.openTextDocument(vscode.Uri.file(g.file)), { preview: true }); } catch (err) { pnotice(STR.reports.unreadable); } return; }
    try { await vscode.env.clipboard.writeText(g.file); pnotice(STR.reports.copied); } catch (err) { pnotice(STR.reports.unreadable); }
  }
  // The ONE place a command is run with Enter (owner decision 31 Oct 2026, option A, DECISIONS.md): the exact argv built by this side goes into the visible "Shipmiracle · setup" terminal and runs there.
  // HONEST WORDING: the CLI asks a question in the terminal only for `--step` of the rows in SETUP_PROMPT_ROWS (pinned by tests/setup_prompts_test.py); `--skip`, `--undo`, `--prefs` and the other
  // steps (engine, registry, notify ...) apply AT ONCE, with no prompt, so their notice says so. The panel never runs them with execFile. setupWatch then re-checks by itself when the command ends.
  const SETUP_PROMPT_ROWS = ['vscode', 'github', 'projects', 'guard', 'remote-control', 'ask-inbox', 'prefs'];
  const setupNote = (op, id) => (op === 'step' && SETUP_PROMPT_ROWS.includes(id) ? STR.setup.sentPrompt : STR.setup.sentNow.replace('{undo}', op === 'prefs' ? 'shipm init --undo prefs' : op === 'step' ? 'shipm init --undo ' + id : 'shipm init --step ' + id));
  const setupRun = (argv, text) => { if (ownerTerminal({ name: 'setup', dir: WS }, [argv], { kind: 'init', run: true, title: 'Shipmiracle · setup' })) pnotice(text); };
  function setupAction(m) {
    const op = String(m.op || '');
    if (op === 'recheck') { setupRefresh(true); return; }
    if (op === 'undo') {                                                  // Remote Control only, and only while the row is on: runs `shipm init --undo remote-control`. The settings file is never written here.
      const row = setupState && !setupState.error && (setupState.rows || []).find(r => r.id === 'remote-control');
      const on = row && ((data.remote && data.remote.state === 'on') || row.state === 'green');
      if (!on) { pnotice(STR.setup.unknownRow); return; }
      const argv = ASK.remoteUndoArgv(path.join(WS, 'bin', 'shipm'));
      setupRun(argv, setupNote('undo', 'remote-control'));
      return;
    }
    if (op === 'prefs') {                                                // Quick setup: `shipm init --prefs ...` runs in the terminal and saves AT ONCE (no prompt when all choices are given); every value is checked again here
      const v = m.prefs && typeof m.prefs === 'object' ? m.prefs : null;
      if (!setupState || setupState.error || !setupState.quick || !v) { pnotice(STR.setup.unknownRow); return; }
      const one = (k, allowed) => (typeof v[k] === 'string' && allowed.includes(v[k]) ? v[k] : null);
      const folder = typeof v.folder === 'string' && v.folder.length <= 200 && /^(~\/|\/)[^\u0000-\u001f\u007f]*$/.test(v.folder) && !v.folder.includes('..') ? v.folder : null;
      const lang = one('lang', ['en', 'ar']), aut = one('autonomy', ['normal', 'step', 'own']), notify = one('notify', ['vscode', 'system', 'none']), awake = v.awake === undefined ? undefined : one('awake', ['yes', 'no']);
      if (!folder) { pnotice(STR.quick.badFolder); return; }
      if (!lang || !aut || !notify || awake === null) { pnotice(STR.setup.unknownRow); return; }
      const argv = [path.join(WS, 'bin', 'shipm'), 'init', '--prefs', '--lang', lang, '--folder', folder, '--autonomy', aut, ...(awake ? ['--awake', awake] : []), '--notify', notify];
      setupRun(argv, setupNote('prefs', 'prefs'));
      return;
    }
    if (op !== 'fix' && op !== 'skip') return;
    const id = typeof m.id === 'string' ? m.id : '', row = setupState && !setupState.error && (setupState.rows || []).find(r => r.id === id);
    if (!row || !SETUP.ID.test(id)) { pnotice(STR.setup.unknownRow); return; }
    const A = SETUP.rowActions(row);
    if (op === 'fix' ? !A.fix : !A.skip) { pnotice(op === 'skip' ? STR.setup.noSkipWhy : STR.setup.unknownRow); return; }        // a required row has no Skip, whatever the page says
    const argv = [path.join(WS, 'bin', 'shipm'), 'init', op === 'fix' ? '--step' : '--skip', id];
    setupRun(argv, setupNote(op === 'fix' ? 'step' : 'skip', id));
  }
  // After a Setup command was sent, wait for it to end: the shell-integration event (with the exit code) when VS Code gives it, else a poll (a cheap cached check; a forced one every 5th tick), at most 10 minutes.
  // Exit 0 -> a forced re-check so the row turns green by itself. Non-zero exit, the terminal closed, or the time up -> "Not done: see the terminal" and nothing is re-checked (the row stays as it was).
  const SETUP_POLL_MS = Number(testEnv('SHIPMIRACLE_SETUP_POLL_MS')) || 3000, SETUP_LIMIT_MS = Number(testEnv('SHIPMIRACLE_SETUP_LIMIT_MS')) || 600000;
  let setupWait = null, setupTimer = null;
  const setupSig = () => (setupState && !setupState.error ? (setupState.rows || []).map(r => r.id + ':' + r.state).join('|') : '');
  function setupStop() { setupWait = null; if (setupTimer) { clearInterval(setupTimer); setupTimer = null; } }
  const shellRunning = new Map();                                         // terminal -> the execution VS Code's shell integration says is running in it (start event); empty without shell integration
  function setupWatch(term) { setupWait = { term, at: Date.now(), sig: setupSig(), ticks: 0, busy: false, exec: null }; if (!term.shellIntegration && !setupTimer) setupTimer = setInterval(() => { setupTick().catch(err => trace('setup poll failed: ' + (err && err.message))); }, SETUP_POLL_MS); }
  function setupNotDone() { setupStop(); pnotice(STR.setup.notDone); }
  async function setupTick() {
    const w = setupWait; if (!w) { setupStop(); return; }
    if (w.term.shellIntegration) { if (setupTimer) { clearInterval(setupTimer); setupTimer = null; } return; }      // the end event will tell: no poll
    if (w.term.exitStatus || Date.now() - w.at > SETUP_LIMIT_MS) { setupNotDone(); return; }
    if (w.busy) return;
    w.busy = true;
    try { await setupRefresh(++w.ticks % 5 === 0); } finally { w.busy = false; }
    if (setupWait === w && setupSig() !== w.sig) { setupStop(); pnotice(STR.setup.done); }
  }
  function setupStarted(e) {                                              // vscode.window.onDidStartTerminalShellExecution: the first execution after our line was sent is OURS; any later end of another one is not
    if (!e || !e.terminal) return;
    shellRunning.set(e.terminal, e.execution);
    const w = setupWait; if (w && e.terminal === w.term && !w.exec) w.exec = e.execution;
  }
  function setupEnded(e) {                                                // vscode.window.onDidEndTerminalShellExecution
    if (e && e.terminal && shellRunning.get(e.terminal) === e.execution) shellRunning.delete(e.terminal);
    const w = setupWait; if (!w || !e || e.terminal !== w.term || !w.exec || e.execution !== w.exec) return;      // an old command's end is not this command's end
    if (e.exitCode === 0) { setupStop(); setupRefresh(true).then(() => pnotice(STR.setup.done)); } else setupNotDone();
  }
  // ---- Ask aside (F3) and Ask inbox (F4). Aside: the fixed text '/btw ' (Enter never pressed) into the project's own chat, only when that chat is proved to be this project's. Inbox: the exact
  // `shipm ask --inbox '<question>'` line is typed into the owner terminal WITHOUT Enter (`shipm ask` spends quota and is owner-only; the panel never runs it). The page sends the question text only.
  async function askAction(m) {
    if (leakBlock() || !m || typeof m !== 'object' || typeof m.op !== 'string') return;
    const op = m.op;
    if (op === 'aside') {
      const name = typeof m.project === 'string' && m.project.length <= 100 ? m.project : '', p = name && known(name);
      if (!p) return;
      const t = chatTab(name);
      if (!t) { pnotice(STR.ask.asideNoChatNotice.replace('{project}', name)); return; }
      const ins = await inspectChat(t);                       // looked at again on every action, never the cached answer
      if (!ins || ins.project !== name) { pnotice(STR.ask.asideUnsure); return; }
      chatOf.set(t, ins); t.show(false); t.sendText(ASK.ASIDE_TEXT, false);
      pnotice(STR.ask.asideSent.replace('{project}', name));
      return;
    }
    const ap = ASK.inboxProject(data.projects);
    if (!ap) { pnotice(STR.ask.noInbox); return; }
    const shipm = shipmiracleBin();
    if (op === 'type') {
      const c = ASK.checkQuestion(m.q);
      if (!c.ok) { pnotice(STR.ask[c.why].replace('{max}', String(ASK.MAX_Q))); return; }
      const model = ap.ask && ap.ask.model_supported === true && typeof m.model === 'string' && ASK.MODELS.includes(m.model) ? m.model : undefined;   // --model only when the CLI supports it
      let argv; try { argv = ASK.inboxArgv(shipm, c.value, model); } catch (err) { pnotice(STR.ask.control); return; }
      if (ownerTerminal(ap, [argv], { kind: 'ask', run: false, title: STR.ask.termTitle })) pnotice(STR.ask.typed.replace('{cmd}', 'shipm ask --inbox …'));
      return;
    }
    const last = ap.ask && ap.ask.last; if (!last) return;                  // both ops below work on the last note from the panel's own data, never on a path the page sent
    if (op === 'open') {
      const g = ASK.guardNote(ap.dir, last.path); if (!g.ok) { pnotice(STR.ask.notOpened.replace('{why}', g.why + '.')); return; }
      try { await vscode.window.showTextDocument(await vscode.workspace.openTextDocument(vscode.Uri.file(g.file)), { preview: true }); } catch (err) { pnotice(STR.ask.notOpened.replace('{why}', 'could not read it.')); }
      return;
    }
    if (op === 'promote') {
      const g = ASK.guardNote(ap.dir, last.path); if (!g.ok) { pnotice(STR.ask.notOpened.replace('{why}', g.why + '.')); return; }
      let argv; try { argv = ASK.promoteArgv(shipm, path.basename(g.file)); } catch (err) { pnotice(STR.ask.badNote); return; }
      if (ownerTerminal(ap, [argv], { kind: 'ask', run: false, title: STR.ask.termTitle })) pnotice(STR.ask.typed.replace('{cmd}', 'shipm ask promote ' + path.basename(g.file)));
    }
  }
  // ---- Handoff + fresh chat (chat context is long). Three steps, all started by the owner's click; nothing is automatic and the old chat is never closed here.
  //  ask:  the fixed text below goes into the project's chat terminal, only if that chat is idle and proved to be this project's.
  //  open: only after the project's docs/STATUS.md is NEWER than the ask: save work (same checkpoint as the Health 'fresh' fix), then open a fresh chat beside the old one.
  const HANDOFF_TEXT = STR.panelMarker + 'Write your handoff now: update docs/STATUS.md (what changed, verified, next, handoff) and commit, then reply HANDOFF DONE.';
  const handoffs = new Map();                                   // project -> { at: ms of the ask }
  const handoffBusy = new Set();
  const statusMtime = p => { try { const st = fs.lstatSync(path.join(p.dir, 'docs', 'STATUS.md')); return st.isFile() ? st.mtimeMs : 0; } catch (err) { return 0; } };
  const idleProject = p => (p.state === 'calm' || p.state === 'idle') && !(p.agents || []).length;
  function handoffView(p) {
    const h = handoffs.get(p.name); if (!h) return null;
    if (Date.now() - h.at > 3600000) { handoffs.delete(p.name); return null; }
    return { asked: true, at: h.at, ready: statusMtime(p) > h.at };
  }
  async function handoffAction(m) {
    if (leakBlock() || !m || typeof m !== 'object') return;
    const step = m.step; if (step !== 'ask' && step !== 'open') return;
    const name = typeof m.project === 'string' && m.project.length <= 100 ? m.project : '';
    let p = name && known(name); if (!p) return;                // unknown project: nothing happens
    if (handoffBusy.has(name)) return;
    handoffBusy.add(name);
    try {
      if (!idleProject(p)) { pnotice('Wait: an agent is working.'); return; }
      if (step === 'ask') {
        const h0 = handoffs.get(name); if (h0 && Date.now() - h0.at < 120000) { pnotice('The handoff was already asked a moment ago.'); return; }
        const t = chatTab(name);
        if (!t) { pnotice(`Handoff not asked: no ${name} chat is open in this VS Code window.`); return; }
        const ins = await inspectChat(t);                       // looked at again on every action, never the cached answer
        if (!ins || ins.project !== name) { pnotice('Handoff not asked: could not confirm which chat that is. Nothing sent.'); return; }
        p = known(name); if (!p || !idleProject(p)) { pnotice('Wait: an agent is working.'); return; }      // re-read after the check: it may have started
        chatOf.set(t, ins); t.sendText(HANDOFF_TEXT, true);
        handoffs.set(name, { at: Date.now() }); p.handoff = handoffView(p);
        trace(`handoff: asked the ${name} chat to write its handoff`);
        pnotice(`Handoff asked in the ${name} chat. When docs/STATUS.md is updated, press Open fresh chat.`);
        return;
      }
      const h = handoffs.get(name);
      if (!h) { pnotice('Ask for the handoff first.'); return; }
      if (!(statusMtime(p) > h.at)) { pnotice('Not yet: docs/STATUS.md has not changed since you asked. Wait until the chat replies HANDOFF DONE.'); return; }
      const cp = await watchJson(['act', 'checkpoint', name]);
      const text = clean((cp.obj && (cp.obj.did || cp.obj.why)) || cp.out || '');
      const saved = (cp.obj ? cp.obj.ok !== false : cp.ok) && (/nothing to save/i.test(text) || /(^|\s)wip\/\S+/.test(text));
      trace(`handoff: open ${name}, checkpoint: ${text}`);
      if (!saved) { pnotice('Handoff not saved: could not save your work first. Nothing changed.'); return; }
      if (!openFreshBeside(p.dir, name)) { pnotice('Fresh chat not opened: the launch was refused. Nothing changed; the old chat is still open.'); return; }
      handoffs.delete(name); p.handoff = null;
      pnotice(`Handoff saved. Fresh chat opened for ${name}. The old chat is still open: close it when you are ready.`);
    } catch (err) { trace('handoff failed: ' + (err && err.message)); pnotice('Handoff not saved, nothing changed.'); }
    finally { handoffBusy.delete(name); if (view) render(); }
  }
  async function relaunch(m) {                            // the owner pressed "relaunch chat" on a card: close only the stale chat(s); open a fresh one only if no healthy chat is left
    const p = known(m.project || '') || data.projects.find(x => x.dir === m.dir); if (!p) return;
    const live = livePorts(); let healthy = 0; const calm = p.state === 'calm' || p.state === 'idle';
    for (const [t, i] of [...chatOf]) {
      if (i.project !== p.name || t.exitStatus !== undefined || closing.has(t)) continue;
      if (i.port && !live.has(i.port)) { closing.add(t); chatOf.delete(t); t.dispose(); }
      else if (oldLauncher(t) && calm) { closing.add(t); chatOf.delete(t); t.dispose(); }     // old launcher: reopened through bin/shipm-chat (the conversation continues)
      else healthy++;
    }
    if (healthy && [...chatOf].some(([t, i]) => i.project === p.name && t.exitStatus === undefined && !closing.has(t) && oldLauncher(t))) { notice(`Not done: ${p.name} is working; the chip stays until it is idle.`); if (view) render(); return; }   // not calm: the chip stays
    staleFlags[p.name] = false; p.chatStale = false; p.chatOld = false;
    if (!healthy) openChat(p.dir, p.name, false); else { const h = chatTab(p.name); if (h) h.show(false); }
    if (view) render();
    verifyRelaunch(p.name);                                 // not awaited: the card redraws now, the result notice follows
  }
  async function verifyRelaunch(name) {                     // the chip says "stale": prove it is gone before saying so
    await waitS(8);
    try { await heal(true); } catch (err) { /* reported below as still stale */ }
    const flag = staleFlags[name];
    if (!flag) { notice(`Relaunched ${name}: linked to VS Code again.`); if (view) render(); return; }
    const p = known(name), t = chatTab(name);
    const why = flag === 'old' ? 'old launcher' : (p && p.state !== 'calm' && p.state !== 'idle') ? 'busy' : (t && t === vscode.window.activeTerminal) ? 'focused' : 'the chat is still not linked';
    notice(`Not fixed: ${name} is still marked stale (${why}). Next: ${why === 'busy' ? 'wait until it is idle, then press the chip again.' : why === 'focused' ? 'switch to another tab, then press the chip again.' : 'close that chat tab and press the chip again.'}`);
    if (view) render();
  }
  const item = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 1000);
  item.command = 'shipmiracle.focus';

  let guardMiss = 0, lastRevive = 0;
  function guardWatchdog() {
    if (leakBlock()) return;                              // the guard is switched on but nothing is running: load it again (once per 5 minutes), so the cleanup and the awake hold never silently stop
    const g = data.guard || {};
    if (!g.on || g.running) { guardMiss = 0; return; }
    if (++guardMiss < 2 || Date.now() - lastRevive < 300000) return;
    lastRevive = Date.now(); trace('watchdog: awake guard not running, loading it again');
    execFile(PY3, [path.join(WS, 'bin', 'shipm-guard'), 'install'], () => setTimeout(refresh, 3000));
  }
  async function refresh() {
    if (busy) return; busy = true;
    trace('refresh: collecting');
    try { data = await collect(); trace('refresh: collected ' + data.projects.length + ' projects'); } catch (e) { console.error('Shipmiracle collect', e); trace('collect failed: ' + (e && e.stack || e)); } finally { busy = false; }
    guardWatchdog();
    if (autoSetup) setupRefresh(false);
    refreshUsage(((data.plan || {}).claude || {}).cachedAt).then(ran => { if (ran) setTimeout(refresh, 1000); });
    const ps = data.projects;
    for (const p of ps) p.handoff = handoffView(p);
    updateUnread(ps);
    if (ps.some(p => p.mirror && p.mirror.status === 'asking') && !interviewPoll) interviewPoll = setTimeout(() => { interviewPoll = null; refresh(); }, 3000);     // the mirror follows the terminal: look again in 3 s while a question is open
    for (const p of ps) p.apWait = apWaitView(p);
    for (const p of ps) p.untilB = !!(untilB.get(p.name) && p.autopilot && p.autopilot.charter && (p.autopilot.charter.ends || []).join(',') === untilB.get(p.name));
    for (const p of ps) { p.chatOpen = !!chatTab(p.name); p.chatStale = !!staleFlags[p.name]; p.chatOld = staleFlags[p.name] === 'old'; }
    heal(false).then(changed => { if (changed && view) render(); });
    // Chats that VS Code restored (or that were open before) get their folder name once, via Claude's own /rename, only while
    // that chat is waiting at its prompt and is not the tab being typed in.
    for (const p of ps) {
      const t = chatTab(p.name);
      if (t && !named.has(t) && (p.state === 'calm' || p.state === 'idle') && t !== vscode.window.activeTerminal) { named.add(t); if (!APPROVAL_WORD.test(p.name)) t.sendText('/rename ' + p.name); }
    }
    for (const p of ps) p.active = p.name === activeName;      // last known highlight; refreshed below, never blocks the render
    const need = ps.filter(p => p.state === 'needs-input').length;
    const agents = ps.reduce((a, p) => a + p.agents.filter(x => !x.stalled).length, 0);
    const work = ps.filter(p => p.state === 'working').length;
    const ms = ((data.plan || {}).meters || []);
    const byId = id => ms.find(m => m.id === id);
    const LV = ['', '', '$(warning) ', '$(error) '];                       // icon only when high or almost out
    const parts = [];
    if (need) parts.push(`$(bell) ${need} need${need > 1 ? '' : 's'} you`);
    if (agents) parts.push(`$(sync~spin) ${agents} agent${agents > 1 ? 's' : ''} working`);
    else if (work) parts.push(`$(sync~spin) ${work} working`);
    for (const [id, short] of [['five', '5h'], ['model-fable', 'Fable']]) {
      const m = byId(id); if (m && m.pct != null) parts.push(`${LV[m.lvl] || ''}${short} ${m.pct}%`);
    }
    if (data.ask) parts.push('$(lightbulb) ideas to review');
    item.text = parts.length ? parts.join('   ') : '$(layout) All projects calm';
    item.tooltip = 'Shipmiracle: show projects\n' + ms.filter(m => m.pct != null).map(m => `${m.label}: ${m.pct}%`).join('\n');
    const worst = Math.max(-1, ...ms.filter(m => m.pct != null).map(m => m.lvl));
    item.backgroundColor = worst >= 3 ? new vscode.ThemeColor('statusBarItem.errorBackground')
      : (need || worst >= 2) ? new vscode.ThemeColor('statusBarItem.warningBackground') : undefined;
    item.show();
    if (view) render();
    activeProject().then(n => { if (n !== activeName) { activeName = n; for (const p of data.projects) p.active = p.name === n; if (view) render(); } });
  }
  let editing = false, editingAt = 0, pendingRender = false;
  const isEditing = () => editing && Date.now() - editingAt < 120000;           // a webview that never says "stopped" cannot freeze the panel for more than 2 minutes
  function render() {
    if (isEditing()) { pendingRender = true; return; }                          // do not redraw under your fingers: draw once when you leave the box
    pendingRender = false;
    const nonce = crypto.randomBytes(12).toString('base64');
    const csp = `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'nonce-${nonce}'; script-src 'nonce-${nonce}';">`;
    try {
      const page = html({ ...data, host: HOSTX.hostOf({ platform: process.platform, remoteName: vscode.env && vscode.env.remoteName }), setup: setupState, rview: rviewState, detail: detailForPage(), asideNotice: asideNoticeForPage(), settings: { cardChatExcerpt: settingOn('cardChatExcerpt'), unreadMarker: settingOn('unreadMarker') }, tidyTool: fs.existsSync(path.join(WS, 'bin', 'shipm')) }, { nonce, csp }), key = page.split(nonce).join('');
      if (key !== lastPage || !view.webview.html) { view.webview.html = page; lastPage = key; }     // an identical page is not set again: a redraw would close what you just opened
      fs.mkdirSync(DIAG, { recursive: true }); fs.writeFileSync(path.join(DIAG, 'panel-render.json'), JSON.stringify({ at: Date.now(), projects: data.projects.length, active: activeName, bytes: view.webview.html.length }));
    } catch (err) {
      trace('render failed: ' + (err && err.stack || err));
      try { view.webview.html = `<!doctype html><html><body style="font:12px sans-serif;padding:10px"><b>Shipmiracle could not draw the panel.</b><pre style="white-space:pre-wrap">${String(err && err.message || err).replace(/[<&]/g, ' ')}</pre></body></html>`; } catch (e2) { /* view gone */ }
    }
  }

  ctx.subscriptions.push(item, vscode.window.registerWebviewViewProvider('shipmiracle.projects', {
    resolveWebviewView(v) {
      trace('resolveWebviewView');
      view = v; lastPage = ''; v.webview.options = { enableScripts: true, localResourceRoots: [] };       // the page loads no local file (CSP default-src 'none'): no folder is readable from it
      v.webview.onDidReceiveMessage(m => {
        if (!m || typeof m !== 'object') return;
        if ((m.type === 'guard' || m.type === 'away') && leakBlock()) return;
        if (m.type === 'guard') {                                   // awake guard on/off button
          const ws = path.join(WS, 'bin', 'shipm-guard');
          execFile(PY3, [ws, (data.guard || {}).on === false ? 'on' : 'off'], () => setTimeout(refresh, 400));
          return;
        }
        if (m.type === 'editing') { editing = !!m.on; editingAt = Date.now(); if (!editing && pendingRender && view) render(); return; }
        if (m.type === 'proposed') { Promise.resolve().then(() => proposedAction(m)).catch(err => trace('proposed crashed: ' + (err && err.message))); return; }
        if (m.type === 'tidy-open') { try { tidyOpen(); } catch (err) { trace('tidy-open crashed: ' + (err && err.message)); } return; }
        if (m.type === 'toolbox') { try { toolboxAction(m); } catch (err) { trace('toolbox crashed: ' + (err && err.message)); } return; }
        if (m.type === 'describe') { describeAction(m).catch(err => trace('describe crashed: ' + (err && err.message))); return; }
        if (m.type === 'aside') { try { asideAction(m); } catch (err) { trace('aside crashed: ' + (err && err.message)); } return; }
        if (m.type === 'detail') { try { detailAction(m); } catch (err) { trace('detail crashed: ' + (err && err.message)); } return; }
        if (m.type === 'rview') { reportAction(m).catch(err => trace('report action crashed: ' + (err && err.message))); return; }
        if (m.type === 'ask') { askAction(m).catch(err => trace('ask action crashed: ' + (err && err.message))); return; }
        if (m.type === 'setup') { try { setupAction(m); } catch (err) { trace('setup action crashed: ' + (err && err.message)); } return; }
        if (m.type === 'idea') { ideaAction(m); return; }
        if (m.type === 'relaunch') { relaunch(m); return; }
        if (m.type === 'handoff') { handoffAction(m).catch(err => trace('handoff crashed: ' + (err && err.message))); return; }
        if (m.type === 'health') { healthAction(m); return; }
        if (m.type === 'newproject') { newProjectAction(m).catch(err => trace('newproject crashed: ' + (err && err.message))); return; }
        if (m.type === 'activateAgent') { activateAgentAction(m).catch(err => trace('activateAgent crashed: ' + (err && err.message))); return; }
        if (m.type === 'safe') { safeAction(m).catch(err => trace('safe crashed: ' + (err && err.message))); return; }
        if (m.type === 'level') { levelAction(m).catch(err => trace('level crashed: ' + (err && err.message))); return; }
        if (m.type === 'charter') { charterAction(m).catch(err => trace('charter crashed: ' + (err && err.message))); return; }
        if (m.type === 'act') { cardAction(m).catch(err => trace('card action crashed: ' + (err && err.message))); return; }
        if (m.type === 'cmd') { const c = { newProject: 'shipmiracle.newProject', check: 'shipmiracle.check' }[m.name]; if (c) vscode.commands.executeCommand(c); return; }   // the buttons that used to sit in the sidebar header
        if (m.type === 'ci') {                                      // red-CI chip: open the run on GitHub, nothing else
          if (typeof m.url === 'string' && m.url.startsWith('https://github.com/')) vscode.env.openExternal(vscode.Uri.parse(m.url));
          return;
        }
        if (m.type === 'away') {                                    // "Decisions while away": render, open, then mark as reviewed
          const tool = path.join(WS, 'bin', 'away-decisions');
          execFile(PY3, [tool, 'render'], (err, out) => {
            const file = String(out || '').trim();
            if (err || !file) { vscode.window.showErrorMessage('Could not write the list of decisions taken while away.'); return; }
            vscode.workspace.openTextDocument(vscode.Uri.file(file)).then(doc => vscode.window.showTextDocument(doc, { preview: true }))
              .then(() => execFile(PY3, [tool, 'review'], () => setTimeout(refresh, 400)), () => {});
          });
          return;
        }
        if (m.type !== 'open' || !m.dir) return;
        const p = data.projects.find(x => x.dir === m.dir); if (!p) return;
        if (m.newWindow) openDir(p.dir, true);                    // ⌘-click: the whole project in its own window
        else { openChat(p.dir, p.name); setTimeout(refresh, 800); }
      });
      v.onDidChangeVisibility(() => v.visible && refresh());
      v.onDidDispose(() => { view = null; });
      render(); refresh();
    }
  }));

  const cmd = (id, fn) => ctx.subscriptions.push(vscode.commands.registerCommand(id, fn));
  cmd('shipmiracle.focus', () => vscode.commands.executeCommand('workbench.view.extension.shipmiracle'));
  cmd('shipmiracle.projects', () => vscode.commands.executeCommand('workbench.view.extension.shipmiracle'));   // old command name
  cmd('shipmiracle.refresh', refresh);
  // No tasks.json needed: both run the workspace script directly. New project asks for a name and a type, then uses the same code path as the panel's box.
  cmd('shipmiracle.newProject', async () => {
    const raw = await vscode.window.showInputBox({ prompt: 'Name of the new project', placeHolder: 'my-project' });
    if (!raw || !/[A-Za-z0-9]/.test(raw)) return;
    const kind = await vscode.window.showQuickPick(KINDS, { placeHolder: 'What kind of project?' });
    if (!kind) return;
    newProjectAction({ name: raw, kind }).catch(err => trace('newProject command crashed: ' + (err && err.message)));
  });
  cmd('shipmiracle.check', () => runScript('Check & update', 'daily', ['--show']));
  cmd('shipmiracle.openNewWindow', c => c && openDir(c.dir, true));
  cmd('shipmiracle.activateAgent', async c => {                       // palette: choose the project first (or from a card menu)
    const ps = data.projects.filter(p => !p.held);
    const proj = c && c.name ? c.name : ((await vscode.window.showQuickPick(ps.map(p => ({ label: p.name })), { placeHolder: 'Activate an agent in which project?' })) || {}).label;
    if (proj) activateAgentAction({ project: proj }).catch(err => trace('activateAgent crashed: ' + (err && err.message)));
  });
  cmd('shipmiracle.reveal', c => c && vscode.commands.executeCommand('revealFileInOS', vscode.Uri.file(c.dir)));
  cmd('shipmiracle.promote', async c => {
    if (!c) return;
    const dir = path.join(c.dir, '.claude', 'agents'); let own = [];
    try { const masters = new Set(fs.readdirSync(path.join(WS, 'agents', 'claude'))); own = fs.readdirSync(dir).filter(f => f.endsWith('.md') && !masters.has(f)).map(f => f.slice(0, -3)).filter(n => SAFE.test(n)); } catch (e) { /* none */ }
    if (!own.length) return vscode.window.showInformationMessage(`${c.name} has no project-only agents to promote.`);
    const pick = await vscode.window.showQuickPick(own, { placeHolder: `Make which ${c.name} agent part of the master team?` });
    if (!pick) return;
    runScript('Promote agent', 'promote-agent', [c.dir, pick]);
  });
  // The delete tool is owner-only (the delete-project tool is not part of the public export): the menu entry shows only when the file exists (context key shipmiracle.deleteAvailable).
  const deleteToolThere = () => { try { return fs.statSync(path.join(WS, 'bin', 'delete-project')).isFile(); } catch (e) { return false; } };
  vscode.commands.executeCommand('setContext', 'shipmiracle.deleteAvailable', deleteToolThere());
  cmd('shipmiracle.delete', async c => {
    if (!c) return;
    if (!deleteToolThere()) return vscode.window.showInformationMessage('Delete project is not available in this installation.');
    if (!SAFE.test(c.name)) return vscode.window.showWarningMessage(`Can't delete "${c.name}": unexpected characters in the name.`);
    if (isProtected(c.name, c.dir)) return vscode.window.showWarningMessage(`${c.name} is protected and can't be deleted from here.`);
    const where = await vscode.window.showQuickPick([{ label: 'Mac and GitHub', v: 'both' }, { label: 'Mac only (keep GitHub copy)', v: 'mac' }, { label: 'GitHub only (keep Mac copy)', v: 'github' }], { placeHolder: `Delete ${c.name} from where?` });
    if (!where) return;
    const ok = await vscode.window.showWarningMessage(`Delete ${c.name} from ${where.label}? This can't be undone.`, { modal: true }, 'Delete');
    if (ok !== 'Delete') return;
    runScript('Delete project', 'delete-project', [c.name, '--where', where.v, '--confirm', 'yes']);
  });

  ctx.subscriptions.push(vscode.window.onDidOpenTerminal(() => setTimeout(refresh, 300)), vscode.window.onDidCloseTerminal(t => { shellRunning.delete(t); if (setupWait && setupWait.term === t) setupNotDone(); setTimeout(refresh, 300); }));
  if (typeof vscode.window.onDidStartTerminalShellExecution === 'function') ctx.subscriptions.push(vscode.window.onDidStartTerminalShellExecution(setupStarted));
  if (typeof vscode.window.onDidEndTerminalShellExecution === 'function') ctx.subscriptions.push(vscode.window.onDidEndTerminalShellExecution(setupEnded));      // VS Code 1.93+; older versions use the poll
  // moving between tabs only moves the highlight: no data reload, no flicker
  let hl = null;
  const moveHighlight = () => { clearTimeout(hl); hl = setTimeout(async () => {
    const n = await activeProject(); if (n === activeName) return; activeName = n;
    for (const p of data.projects) p.active = p.name === n; if (view) render(); }, 120); };
  ctx.subscriptions.push(vscode.window.onDidChangeActiveTerminal(t => { const nm = t && ((chatOf.get(t) || {}).project || (/^(.+) · Claude(?: \(fresh\))?$/.exec(t.name) || [])[1]); if (nm) markSeen(nm); }));
  try { ctx.subscriptions.push(vscode.workspace.onDidChangeConfiguration(e => { try { if (e.affectsConfiguration('shipmiracle')) { if (view) render(); } } catch (err) { /* ignore */ } })); } catch (err) { /* a host without the event: the next refresh reads the settings anyway */ }
  ctx.subscriptions.push(vscode.window.onDidChangeActiveTerminal(moveHighlight), vscode.window.onDidChangeActiveTextEditor(moveHighlight),
    vscode.window.tabGroups.onDidChangeTabs(moveHighlight), vscode.window.tabGroups.onDidChangeTabGroups(moveHighlight));
  cmd('shipmiracle.openFolderHere', c => c && openDir(c.dir, false));
  // the Shipmiracle panel is the default view whenever a window opens
  setTimeout(() => vscode.commands.executeCommand('workbench.view.extension.shipmiracle'), 1200);
  const healSoon = ms => setTimeout(() => heal(true).then(changed => { if (changed && view) render(); }), ms);
  healSoon(5000); healSoon(15000);                                              // revived chat terminals show up a few seconds after start
  ctx.subscriptions.push(vscode.window.onDidOpenTerminal(() => healSoon(3000)));
  refresh();
  const timer = setInterval(refresh, 20000);
  ctx.subscriptions.push({ dispose: () => clearInterval(timer) });
  let pending = null;       // one refresh per 1.5 s however many state files change (model/mode files update every reply)
  try { fs.mkdirSync(STATE, { recursive: true }); const w = fs.watch(STATE, (ev, name) => { if (name && /^(probe|panel-|guard|away|user-active|handoff)/.test(name)) return; if (pending) return; pending = setTimeout(() => { pending = null; refresh(); }, 1500); }); ctx.subscriptions.push({ dispose: () => w.close() }); } catch (e) { /* timer covers it */ }
}
exports.activate = activate;
exports.deactivate = () => {};
exports.EXT_OPS = EXT_OPS;
exports.cwdOfPid = cwdOfPid;                                                  // for the platform tests
