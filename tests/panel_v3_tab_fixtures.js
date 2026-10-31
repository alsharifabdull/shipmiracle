// Fixtures for the Reports, Setup and Health tabs of panel v3 (UX spec sections 6, 7, 8). Shapes are the real ones:
//  - reports: <state>/v1/reports/index.json items (shipmiracle/report/write.py); the Markdown is the real template shape (shipmiracle/report/templates.py "Label: value" lines)
//  - setup rows: `shipm init --check --json` (shipmiracle/setup/rows.py): 18 rows, n 0..17; tests/ext_reports_test.js compares the ids with the live CLI output
//  - health items: bin/shipm-watch item shape for the new kinds (mode, severity, next, info)
const now = Math.floor(Date.now() / 1000), day = 86400;
const it = (id, project, kind, verdict, ago, title, sub, extra = {}) => ({ id, project, kind, cr: kind === 'digest' ? '' : (extra.cr || 'CR-012'), stage: kind === 'stage' ? (extra.stage || 'verify') : '', verdict, ts: now - ago, title, sub, path: extra.path || '', private: kind !== 'cr' });
const ITEMS = [
  it('2026-10-20-CR-012-verify', 'demo-app', 'stage', 'FAIL', 3600, 'CR-012 Test', '2 of 214 tests failed', { path: '/s/v1/reports/aaaaaaaaaaaa/2026-10-20-CR-012-verify.md' }),
  it('2026-10-20-CR-020-verify', 'search-app', 'stage', 'BLOCKED', 7200, 'CR-020 Test', 'Blocked: owner decides', { cr: 'CR-020' }),
  it('2026-10-19-CR-011', 'demo-app', 'cr', 'PASS', 2 * day, 'CR-011 Export report', 'Delivered', { cr: 'CR-011', path: '/x/demo-app/docs/reports/2026-10-19-CR-011.md' }),
  it('2026-10-18-CR-010', 'demo-app', 'cr', 'NOT TESTED', 3 * day, 'CR-010 Dark mode', 'Abandoned', { cr: 'CR-010' }),
  it('2026-10-20-CR-001-verify', 'arabic-app', 'stage', 'PASS', 5400, 'CR-001 إصلاح RTL', 'إصلاح الواجهة العربية', { cr: 'CR-001' }),
  it('2026-10-21-CR-031-review', 'zeta-app', 'stage', 'PASS', 600, 'CR-031 Review', 'Review ACCEPT', { cr: 'CR-031', stage: 'review' }),
  it('digest-2026-10-20', '', 'digest', 'NOT TESTED', 4 * 3600, 'Digest 2026-10-20', '3 projects')
];
const REPORTS = { items: ITEMS, status: 'ok' };
const STAGE_MD = `# CR-012 · Test · FAIL                                  2026-10-20 14:02 · demo-app (software)
Verdict: FAIL (attempt 1 of 2)
Evidence: \`node tests/run.js\` -> 212 passed, 2 failed
Failed: export_pdf_test, export_csv_test
By: verifier (sonnet) · 6 min · 41k tokens
Next: Builder (builder-frontend) fixes the failures
Not verified: live PDF printing on a real printer
`;
const HOSTILE_MD = `# CR-099 **bold** title      2026-10-20 <script>window.__xss=1</script>
Verdict: PASS (ok) <img src=x onerror=window.__xss=2>
Evidence: [click me](javascript:window.__xss=3) and [docs](https://example.com/a?b=1&c=2) and \`code <b>x</b>\`
## Details <b>x</b> <img src=x onerror=window.__xss=5>
- item **one** <i>x</i>
- item two
1. first
\`\`\`
<script>window.__xss=4</script>
raw & text
\`\`\`
إصلاح الواجهة العربية بالكامل
Not verified: nothing was run
  against a real device
`;
const NO_NV_MD = `# CR-050 Something · DELIVERED · PASS
Summary: pending
Stages: Scope done · Plan done
`;
const ARABIC_MD = `# CR-001 إصلاح RTL · DELIVERED · PASS
Summary: إصلاح الواجهة العربية بالكامل
Not verified: None
`;
// the rows of `shipm init --check --json` (ids, titles, needs and connect kinds as the CLI prints them); the state of each row is set per test
const R = (n, id, title, need, kind, text, state, detail) => ({ n, id, title, need, state, detail, connect: { kind, text } });
const ROWS = (st = {}) => [
  R(0, 'engine', 'Engine', 'required', 'write', 'Register this checkout: config, hooks, agent team, Shipmiracle command.', st.engine || 'green', 'engine ~/Developer/AI-Workspace registered'),
  R(1, 'base', 'Base tools', 'required', 'hint', 'Run: xcode-select --install   (a macOS window opens; python3 3.9+ comes with it)', st.base || 'green', 'command line tools, git and python3 3.9 found'),
  R(2, 'node', 'Node', 'required', 'hint', 'Install Node 18 or newer (for example: brew install node). Shipmiracle never runs brew.', st.node || 'green', 'node v22.1.0'),
  R(3, 'claude', 'Claude Code login', 'required', 'browser', 'Run `claude` in a terminal and sign in with your Claude account (opens your browser).', st.claude || 'green', 'Claude Code 2.1, logged in'),
  R(4, 'vscode', 'VS Code + panel', 'required', 'write', 'Installs the Shipmiracle panel and the Claude Code extension with `code --install-extension`.', st.vscode || 'green', 'VS Code with the panel and Claude Code extension'),
  R(5, 'git-id', 'Git name and email', 'required', 'prompt', 'git config --global user.name "Your Name"   and   git config --global user.email "you@example.com"', st['git-id'] || 'red', 'git user.name and user.email not set'),
  R(6, 'github', 'GitHub login', 'recommended', 'browser', 'gh auth login --web -s repo   (opens your browser; Shipmiracle never sees the token)', st.github || 'red', 'not logged in to GitHub'),
  R(7, 'projects', 'Projects folder', 'required', 'prompt', 'Confirm the folder for your projects (default ~/Developer).', st.projects || 'green', '~/Developer exists'),
  R(8, 'registry', 'Project registry', 'required', 'write', 'Adds your existing projects to the registry from their git remotes.', st.registry || 'green', '9 project(s) registered'),
  R(9, 'guard', 'Awake guard', 'optional', 'write', 'Installs two launchd jobs for your account: the awake guard and the daily report.', st.guard || 'green', 'awake guard installed and loaded'),
  R(10, 'notify', 'Notifications and CI', 'optional', 'hint', 'The CI chip needs the GitHub login; notifications use macOS and need nothing.', st.notify || 'skipped', 'skipped'),
  R(11, 'docker', 'Docker', 'optional', 'hint', 'Only for container projects: install Colima and Docker (brew install colima docker).', st.docker || 'red', 'Docker (Colima) is not running or not installed'),
  R(12, 'web-verify', 'Web checks', 'optional', 'hint', 'Only for web projects: install agent-browser (see the stack pack).', st['web-verify'] || 'green', 'agent-browser found'),
  R(13, 'connectors', 'Claude connectors and MCP servers', 'advisory', 'hint', "Gmail, Drive, Calendar and other connectors are added in Claude's own settings, never by Shipmiracle.", st.connectors || 'advisory', "set in Claude's own settings; Shipmiracle only reports"),
  R(14, 'remote-control', 'Remote Control', 'optional', 'hint', 'Optional: reach your own Claude Code sessions from your phone. Off by default; opt in with `shipm init --step remote-control`.', st['remote-control'] || 'skipped', 'off (default); opt in with: shipm init --step remote-control'),
  R(15, 'backup', 'Backups', 'advisory', 'hint', 'Turn on Time Machine or another backup; GitHub is the only offsite copy.', st.backup || 'advisory', 'Time Machine: last backup 2 h ago'),
  R(16, 'ios', 'iOS tools', 'optional', 'hint', 'Only for iOS projects: install Xcode from the App Store.', st.ios || 'green', 'Xcode found'),
  R(17, 'publishing', 'Publishing', 'never', 'hint', 'Publishing tools are never preconfigured: publishing always asks you.', st.publishing || 'never', 'not set up here on purpose: publishing always asks you'),
  R(18, 'ask-inbox', 'Ask inbox', 'optional', 'write', 'Optional: a notes project `ask` for random questions; `shipm ask --inbox "question"` writes the answers there.', st['ask-inbox'] || 'skipped', 'not set up (optional): a notes project for random questions; shipm init --step ask-inbox'),
  R(19, 'describe-work', 'Describe your work', 'optional', 'hint', 'Optional: answer a few questions and get a draft playbook. In a terminal: `shipm playbook interview --short --project NAME` (or --long).', st['describe-work'] || 'skipped', 'optional: answer a few questions and get a draft playbook; shipm playbook interview --short --project NAME'),
  R(20, 'prefs', 'Quick setup choices', 'optional', 'prompt', 'Five short choices: language, projects folder, how much the team does by itself, keep awake, notifications. Enter keeps the recommended answer.', st.prefs || 'skipped', 'not answered yet: defaults are used (shipm init --prefs asks 5 short questions)'),
  R(21, 'gitleaks', 'gitleaks', 'optional', 'hint', 'Recommended for release export and autopilot deliver: install gitleaks (brew install gitleaks).', st.gitleaks || 'red', 'gitleaks not found (brew install gitleaks); the release check then skips its secret scan')
];
const SETUP = (st) => { const rows = ROWS(st); return { error: false, rows, ready: rows.filter(r => [0, 1, 2, 3, 4, 5, 7].includes(r.n)).every(r => r.state === 'green'), at: 1 }; };
// Health items of the new kinds, in bin/shipm-watch's shape (info_only kinds carry severity "info"; the fix kinds carry their chain)
const hi = (kind, project, o = {}) => ({ id: kind + ':' + project, kind, severity: 'info', project, title: o.title || kind, why: o.why || '', since: now - 1800, mode: 'wait', actions: [], chain: [], info_only: true, fixable_now: false, impact: {}, safe: {}, can: {}, fix_label: '', proof: '', info: o.info || '', next: o.next || '', ...o });
const HEALTH_NEW = [
  hi('stage_stuck', 'demo-app', { severity: 'amber', mode: 'fix', info_only: false, title: 'CR step stuck 31 min', why: 'CR-012 has had no stage change for 31 min while the chat is working.', actions: ['interrupt'], chain: ['interrupt'], fixable_now: true, recommended: 'interrupt', fix_label: 'Stop the step the chat is on', can: { interrupt: [true, ''] }, impact: { interrupt: 'Sends Esc to the chat.' } }),
  hi('verify_failed_twice', 'search-app', { title: 'CR-020: test failed twice', why: 'The test failed twice; the CR waits for your choice.', info: 'The test failed twice on the active change request; it is blocked until you choose.', next: 'Open the chat and choose: change the plan, fix it again, or stop the CR (shipm cr abandon in a terminal).' }),
  hi('autopilot_paused', 'auto-app', { title: "CR-021: waiting for 'next'", why: 'The manual autopilot stopped after a stage and waits for your word.', info: 'The manual autopilot finished a stage and waits for your word.', next: 'Open the chat and type next to let the manual autopilot run the following stage.' }),
  hi('autopilot_stopped', 'auto-app', { title: 'autopilot stopped (H-1a2b3c)', why: 'autopilot wants to push publicly', info: 'The autopilot run stopped on a hard rule and waits for your word.', next: 'Open the auto chat: type allow: H-1a2b3c to allow that one action, or charter: off.' }),
  hi('budget_reached', 'auto-app', { title: 'autopilot budget reached', why: 'The autopilot run ended because the weekly budget in its charter was used up.', next: 'Raise the charter budget or go back to guided.' }),
  hi('autopilot_ended_time', 'auto-app', { title: 'autopilot ended: time limit reached', why: 'The autopilot run ended because the time limit in its charter was reached.', next: 'Look at the auto branch result, then start a new run with a longer time limit or go back to guided.' }),
  hi('merge_waiting', 'auto-app', { title: 'CR-022: merge waiting', why: 'Merge waiting: the main checkout is in use.', next: 'Close the chat that uses the main checkout and commit or stash your changes there.' }),
  hi('cr_orphan', 'demo-app', { mode: 'info', title: 'CR-012 open, no chat for 26 h', why: 'A change request is open but no chat has worked on it for a day.', info: 'A change request is open but no chat has worked on it for a day.', next: "Open the project's chat from its card and type /feature with no text to resume the CR." }),
  hi('stray_browser', '', { severity: 'amber', mode: 'fix', info_only: false, title: 'leftover automation browser (pid 4242)', why: 'An automation Chrome is older than 30 minutes.', actions: ['end-browser'], chain: ['end-browser'], fixable_now: true, recommended: 'end-browser', fix_label: 'End the leftover automation browser', can: { 'end-browser': [true, ''] }, impact: { 'end-browser': 'Closes that browser.' }, destructive_chain: true, destructive: { 'end-browser': true } }),
  hi('stray_testrun', '', { severity: 'amber', mode: 'fix', info_only: false, title: 'orphaned test run (pid 4343)', why: 'bin/test-all has run for 20+ minutes and its parent is gone.', actions: ['end-testrun'], chain: ['end-testrun'], fixable_now: true, recommended: 'end-testrun', fix_label: 'Stop the orphaned test run', can: { 'end-testrun': [true, ''] }, impact: { 'end-testrun': 'Stops it.' }, destructive_chain: true, destructive: { 'end-testrun': true } })
];
const HEALTH = (items = HEALTH_NEW, red = 0, amber = 3) => ({ ts: now, ageS: 10, items, counts: { red, amber, info: items.length }, chats: {}, host: { busy: false, swap_pct: 1, free_pct: 50, load: 1 }, auto: true, cleaned: [], notice: '', noticeInfo: {} });
module.exports = { ITEMS, REPORTS, STAGE_MD, HOSTILE_MD, NO_NV_MD, ARABIC_MD, ROWS, SETUP, HEALTH_NEW, HEALTH, hi, now };
