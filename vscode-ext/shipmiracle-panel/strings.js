// Every piece of panel v3 copy (UX spec docs/plans/2026-10-20-panel-v3-ux.md section 10) lives here, keyed, English only, Western digits.
// panel.js reads it through t('group.key', {name: value}); a strings.ar.js with the same keys can replace this file later. {name} marks a slot.
// Legacy card/Health/Ideas copy that predates v3 is still written inline in panel.js and moves here as those screens are rebuilt.
module.exports = {
  // Every text the panel puts into a CHAT (a first message, a handoff request) starts with this marker, so the gate's plan-approval hook can tell it from the owner's own words.
  // The exact '/btw ' prefill is the one exception (it starts with '/', which the hook ignores). One constant; tests/ext_chatmark_test.js asserts every chat-bound text.
  panelMarker: '[panel] ',
  lang: 'en',
  dir: 'ltr',
  tabs: { projects: 'Projects', reports: 'Reports', ideas: 'Ideas', health: 'Health', setup: 'Setup', aria: 'Panel sections' },
  // Jargon tooltips (one line each).
  jargon: {
    cr: 'Change request: one piece of work, from idea to delivered.',
    gate: 'The rule check that refuses skipped steps.',
    lens: 'A kind of review: correctness, or risk.',
    charter: 'Your written permission: what it may change, how much it may spend, for how long.',
    hardstop: 'A rule-based pause that only you can lift.',
    playbook: 'The steps this project follows, set by its type.',
    autopilot: 'How much it does before asking you.'
  },
  autopilot: {
    manual: { name: 'Manual', tip: 'I say next after every step.' },
    guided: { name: 'Guided', tip: 'It chains steps and asks at approvals and stops.' },
    full: { name: 'Full', tip: 'It also approves inside your charter.' },
    fullItem: 'Full…',
    chipAria: 'Autopilot {level} for {project}. Press to change it.',
    chipFixed: 'Autopilot {level}. {why}',
    menuAria: 'Autopilot level',
    fullLeft: 'Full · {left}',
    notNow: 'Not now: {project} is working or waiting for you.',
    heldWhy: 'Held: its session is still running.',
    laterNote: 'Changing the autopilot level from the panel comes in the next panel update. Until then, type in a terminal inside {project}: shipm playbook set autopilot {to}',
    back: 'Back to guided',
    backSure: 'Sure?',
    // The panel never changes the level itself: the owner's command runs in a VS Code terminal and is confirmed there.
    // The command is typed but NOT run (owner decision 21 Oct): the owner reads it and presses Enter.
    pressEnter: 'Press Enter in the terminal to run it',
    termLevel: 'Typed the command in a terminal for {project}. Press Enter in the terminal to run it, then type {to} to confirm. Nothing changes until you do.',
    termBack: 'Typed the command in a terminal for {project}: the run stops and the charter is cleared. Press Enter in the terminal to run it, then type guided to confirm.',
    termFull: 'Typed the commands in a terminal for {project}: they set the charter, then ask you to type yes. Press Enter in the terminal to run them. Nothing starts until you do.',
    termDecide: 'Put the command in a terminal for {project}. Press Enter in the terminal to run it.',
    termInit: 'Typed `{cmd}` in a terminal. Press Enter in the terminal to run it.',
    ended: 'Autopilot finished: {why}. Back to Normal.',
    endedWhy: { done: 'its requests are done', time: 'time ran out', budget: 'your weekly limit was reached', owner: 'you stopped it', lapsed: 'it lapsed' },
    waitTitle: 'Waiting for you in the terminal',
    waitFull: 'Press Enter there to run it, check the charter and type yes to start.',
    waitLevel: 'Press Enter there to run it, then type {to} to confirm.',
    waitBack: 'Press Enter there to run it, then type guided to confirm.',
    waitOpen: 'Show terminal',
    waitTip: 'The panel does not change autopilot itself. It waits for the owner command to finish and refreshes by itself.',
    termFail: 'No terminal opened: {why}'
  },
  // Charter editor (spec section 4): opens from the autopilot chip, Full…. Field rules and messages come from charter.js (a copy of shipmiracle/autopilot/charter.py's).
  charter: {
    heading: 'Full autopilot for {project}',
    intro: 'Your written permission for this run. Nothing starts from this form: the commands open in a terminal and you confirm there.',
    goal: 'Goal', goalPh: 'One line: what it should finish', goalHint: '1-200 characters.',
    scope: 'May change', scopePh: 'src/**, tests/**', scopeHint: 'Folders or files, comma separated (1-20). Never offered: .shipmiracle, the rule files.',
    excluded: 'Always excluded ({n})', excludedHint: 'Whatever you list, these are never touched:',
    budget: 'Budget (% of the week)', budgetHint: '1-25. The cap is 25%.', budgetNow: 'now {now}% of the week, stops at {stop}%', budgetNoReading: 'No fresh weekly reading yet. It is measured when the run starts.',
    time: 'Time (hours)', timeHint: '0.25-8 h, in 0.25 steps.',
    deps: 'New packages', depsNone: 'None', depsListed: 'Listed names', depsPh: 'left-pad, @scope/name', depsHint: 'Package names, comma separated (1-10).',
    ends: 'Ends at', endsHint: 'Pick the change requests it may finish (1-5). It stops after the last one.',
    endsNone: 'No open or queued change request in this project. Open one first, then come back.',
    stops: 'Always stops for', stopList: ['deleting data or history', 'pushing or publishing publicly', 'paid services or new accounts', 'deploying to production', 'changing settings, hooks or secrets', 'touching files outside "May change"', 'tests failing twice', 'reaching budget or time'],
    tick: 'I understand it will work without asking until the charter ends or a hard stop',
    start: 'Start full autopilot', cancel: 'Cancel',
    whyOff: 'Start is off: {why}',
    whyLevel: 'Full autopilot needs gate level strict. Switch the level first.',
    whyHeld: 'Held: its session is still running.',
    whyBusy: 'Not now: {project} is working or waiting for you.',
    whySwitch: 'The full-autopilot switch is off. In a terminal: shipm switch autopilot.full.enabled on',
    whyType: 'Full autopilot is for software projects only.',
    whyFill: 'Fix the highlighted fields.',
    whyTick: 'Tick the box to confirm.',
    whyFillIn: 'Fill in: {fields}.',
    whyEnds: 'There is no open or queued change request to end at.',
    tip: 'Your written permission: what it may change, how much it may spend, for how long.'
  },
  // Hard stop: shown in words, never sent to a chat.
  decide: {
    heading: 'Stopped: {text}',
    why: 'Autopilot paused itself. Only you can lift a hard stop.',
    allowLead: 'To allow this one thing, run this in a terminal:',
    allowBtn: 'Allow this once',
    allowTip: 'Opens a terminal in the project with the command typed but not run. You press Enter.',
    noId: 'The stop has no id the panel can use. Open the chat to see it.',
    offLead: 'To end the run: Back to guided below, or put charter: off as the first line of a message in the chat.',
    allowChat: 'In the chat the same thing is: allow: {id} (first line, typed by you).',
    chat: 'Open chat', close: 'Close'
  },
  // New project box (spec section 5). Hints use the rule of bin/new-project (kebab-case, at most 40).
  newp: {
    nameHint: 'Will be created as ~/Developer/{name}',
    nameEmpty: 'Will be created as ~/Developer/…',
    nameRule: 'Use lowercase letters, numbers and dashes.',
    nameTaken: 'That name is already a project.',
    typePh: 'Choose a type…', typeNeed: 'Pick a type to continue.', typeBusy: 'Another project is still being created.',
    private: 'GitHub: private repo (default). Making a repo public is done later and always asks you.',
    createTitleType: 'Choose a type first.'
  },
  plan: { hint: 'Type "approved" in the chat to approve' },
  // Buttons: exactly one primary per card.
  btn: {
    open: 'Open chat', plan: 'Review plan', decide: 'Decide', fix: 'Fix', start: 'Start {cr}', setup: 'Set up playbook',
    wait: 'Wait · back {time}', waitUnknown: 'Wait for the limit',
    more: 'More actions for {project}', moreShort: '⋯',
    handoff: 'Handoff + fresh chat', handoffSure: 'Sure? Note saved, then fresh chat'
  },
  btnTip: {
    open: 'Open this project\'s Claude chat here.',
    plan: 'Opens the plan. Read it, then type "approved" in the chat. The panel never sends your approval.',
    decide: 'This needs your decision. Opens the chat.',
    fix: 'Opens the Health row for this project.',
    wait: 'Not now: the usage limit has not reset yet.',
    setup: 'This project has no playbook yet. The gate rules still apply.',
    start: 'Asks the chat to start this change request.',
    report: 'Open the last report'
  },
  menu: {
    open: 'Open chat', report: 'Report', setup: 'Set up playbook', autopilot: 'Autopilot…', safe: 'Safe mode…', handoff: 'Handoff + fresh chat', handoffDot: 'Chat is long: a handoff saves tokens',
    newWindow: 'Open in new window', relaunch: 'Relaunch chat', health: 'Open Health', moreCrs: 'More change requests',
    askAside: 'Ask aside'
    // Extension point for F5 (not built; needs an owner-approved UX addendum): a 'Toolbox' item goes here, after askAside and before newWindow.
  },
  // Ask aside (F3, /btw) and the Ask inbox card (F4). /btw has no tools and its answer is not saved; `shipm ask` spends quota, so the panel only types the command, the owner presses Enter.
  ask: {
    aside: 'Ask aside',
    asideTip: 'Types /btw into this chat. /btw uses the same model as this chat. We found no way to change it, so there is no model choice here. For a different model, use Ask a question. Needs the Claude extension 2.1.227 or later.',
    asideAria: 'Ask aside in the {project} chat',
    asideNoChat: 'Open the {project} chat first. Ask aside types /btw into that chat.',
    asideNoChatNotice: 'Not sent: no {project} chat is open in this VS Code window.',
    asideUnsure: 'Not sent: could not confirm which chat that is. Nothing typed.',
    asideSent: 'Typed /btw in the {project} chat. Type your question after it and press Enter.',
    title: 'Ask', sub: 'Questions that are not a project',
    label: 'Ask anything…', placeholder: 'Ask anything…', counter: '{n} of {max}',
    send: 'Ask', sendTip: 'Types `shipm ask --inbox` with your question into a terminal. You press Enter there: asking uses your quota.',
    sendAria: 'Ask this question', empty: 'Type a question first.', tooLong: 'Not sent: the question is longer than {max} characters.', newline: 'Not sent: a question is one line.', dash: 'Not sent: start the question with a letter or a number.', control: 'Not sent: the question has a control character.',
    today: 'Questions today {n} of {max}', fullTip: 'Not now: today\'s {limit} questions are used.', todayFull: 'Today\'s limit is reached. Try again tomorrow.',
    noNotes: 'No answers yet. Ask a question above; the answer is saved here as a note.', last: 'Last answer', open: 'Open', openAria: 'Open the last answer: {title}', promote: 'Promote to idea', promoteTip: 'Types `shipm ask promote` for this note into a terminal. It adds the question to your Inbox ideas. You press Enter there.',
    notOpened: 'Not opened: {why}', typed: 'Typed `{cmd}` in a terminal. Press Enter in the terminal to run it.', noInbox: 'The Ask inbox is not set up. Use Setup, row Ask inbox.', badNote: 'Not typed: that is not an Ask note.',
    model: 'Model', modelHint: 'Opus is most careful. Sonnet is balanced. Haiku is fastest and uses the least of your week.', modelOpus: 'Opus (default)', modelSonnet: 'Sonnet', modelHaiku: 'Haiku',
    preview: 'This will be typed in the terminal:', cancel: 'Cancel',
    termTitle: 'Shipmiracle · ask'
  },
  // Status lines (final strings from the spec). {x} slots.
  status: {
    held: 'Held: its session is still running.',
    integrity: 'Blocked: a gate file changed',
    frozen: 'No activity for {min} min. Open Health',
    frozenUnknown: 'No activity for a while. Open Health',
    limit: 'Waiting for the usage limit to reset (back {time})',
    hardstop: 'Paused: {text}. It will not go on without you.',
    hardstopDefault: 'it hit a rule that needs you',
    verifyTwice: 'Stopped: tests failed twice. Your decision',
    blocked: 'Stopped: {cr} is blocked. Your decision',
    approval: 'Waiting for your OK: the plan is ready',
    auto: 'Auto: {what}',
    idle: 'Idle · last commit {ago}',
    idleNoCommit: 'Idle',
    delivered: 'Delivered · {cr}',
    deliveredAgo: 'Delivered · {cr} · last commit {ago}',
    noPlaybook: 'No playbook yet. Gate rules still apply',
    typeNotSet: 'Type: not set',
    scope: 'Scoping: {agent} is clarifying the task',
    plan: 'Planning: {agent} is writing the plan',
    planWith: 'Planning with {model}: {agent}',
    build: 'Building{with}: {agent}',
    buildMany: 'Building{with}: {n} agents',
    verifyTest: 'Testing: {agent} is running the tests',
    verify: '{label}: {agent} is checking',
    verifyFail: 'Fixing: {label} failed (1 of 2 tries)',
    review: 'Review: {agent} is reading the change',
    deliver: '{label}: finishing up',
    atStage: '{cr} is at {label}. Open the chat to continue',
    withModel: ' with {model}',
    autoDoing: { scope: 'scoping {cr}', plan: 'planning {cr}', approve: 'waiting at the OK for {cr}', do: 'building {cr}', verify: 'testing {cr}', review: 'reviewing {cr}', deliver: 'delivering {cr}', learn: 'finishing {cr}' },
    roles: { scope: 'scoper', plan: 'planner', do: 'builder', verify: 'verifier', review: 'reviewer' },
    builder: 'Builder'
  },
  strip: {
    aria: 'Stages: {names}',
    of: '{label} · {n} of 7',
    allDone: 'Done · 7 of 7',
    none: 'No change request open',
    marks: { done: 'done', cur: 'now', fail: 'failed', fail1: 'failed, attempt 1 of 2', fail2: 'failed twice', blk: 'blocked', wait: 'waiting for you', skip: 'skipped: small change', next: 'not yet' },
    skipTip: 'Skipped: small change',
    glyph: { done: '✓', cur: '', fail: '✕', blk: '!', wait: '!', skip: '', next: '' }
  },
  // Step words by project type (panel v3 revision v2): one everyday word per step, the same word everywhere. Step ids stay fixed.
  stageNames: {
    software: ['Brief', 'Plan', 'OK', 'Build', 'Test', 'Review', 'Ship'],
    app: ['Brief', 'Plan', 'OK', 'Build', 'Test', 'Review', 'Ship'],
    content: ['Brief', 'Plan', 'OK', 'Write', 'Check', 'Review', 'Post'],
    research: ['Brief', 'Plan', 'OK', 'Draft', 'Check', 'Review', 'Send'],
    ops: ['Brief', 'Plan', 'OK', 'Change', 'Trial', 'Review', 'Apply'],
    notes: ['Brief', 'Plan', 'OK', 'Write', 'Check', 'Review', 'File']
  },
  cr: {
    active: '{id} {title}', queued: '{id} queued', blocked: '{id} blocked: needs you', more: '+{n}',
    moreTip: '{n} more change requests: {list}', needsYou: 'Needs you',
    queuedTip: 'Queued: starts when the active change request is done.', blockedTip: 'Blocked: this change request needs your decision.'
  },
  verdict: {
    line: 'Last: {stage}', counts: ' · {counts}', report: 'report ›', reportAria: 'Open the {stage} report',
    words: { PASS: 'PASS', FAIL: 'FAIL', BLOCKED: 'BLOCKED', 'NOT TESTED': 'NOT TESTED' }
  },
  chips: {
    gateFile: 'Gate file changed', autoDecisions: 'Auto: {n} decisions', autoDecision1: 'Auto: 1 decision',
    budget: '{used}% of {cap}%', budgetTime: '{used}% of {cap}% · {left}', typeNotSet: 'Type: not set',
    hardstopTip: 'Hard stop: a rule-based pause that only you can lift.'
  },
  // Context size (section 9).
  ctx: {
    plain: 'context {k}',
    soft: 'Chat is long · {k}', strong: 'Chat is very long · {k}',
    softTip: 'Chat is long. Handing over to a fresh chat saves tokens and keeps quality up. Your choice.',
    strongTip: 'Chat is very long. Handing over to a fresh chat saves tokens and keeps quality up. Your choice.',
    tokens: '{n} tokens in this chat'
  },
  // Now / Next / Waiting on you (section 3)
  now: {
    aria: 'Now, next and waiting on you',
    waiting: 'WAITING ON YOU', nowH: 'NOW', next: 'NEXT',
    empty: 'Nothing waiting on you.',
    more: '+{n} more', less: 'Show fewer',
    open: 'Open', openAria: '{what} for {project}',
    approve: 'Approve plan for {cr}', approveNoCr: 'Approve the plan',
    twice: 'Tests failed twice ({cr})', blocked: '{cr} is blocked', crFallback: 'CR',
    decide: 'Decide: {text}', fix: 'Fix: {text}', answer: 'Needs you',
    working: '{text}', minutes: '{n} min', queued: '{cr} queued'
  },
  // Reports tab (section 6)
  reports: {
    title: 'Reports', empty: 'No reports yet. They appear when a stage finishes.', error: 'Could not read reports. Try again.', retry: 'Retry',
    filterProject: 'Project', allProjects: 'All projects', allKinds: 'All', allVerdicts: 'All',
    kinds: { stage: 'Stage', cr: 'Delivered', digest: 'Daily' }, kindsAria: 'Kind of report', verdictsAria: 'Verdict',
    none: 'No report matches these filters.', open: 'Open', openAria: 'Open the report {title}',
    back: '‹ Reports', backAria: 'Back to the list of reports',
    verdictAria: 'Verdict: {word}', verdictGloss: { PASS: 'PASS', FAIL: 'FAIL', BLOCKED: 'BLOCKED', 'NOT TESTED': 'NOT TESTED' },
    notVerified: 'Not verified', notVerifiedNone: 'None listed', notVerifiedMissing: 'This report does not say.',
    openFile: 'Open file', copyPath: 'Copy path', copied: 'Path copied.', notOpened: 'Report not opened: {why}',
    badgeAria: '{n} failed or blocked this week', loading: 'Loading report…', unreadable: 'Could not read that report.',
    gone: 'That report is not in the list any more.',
    private: 'Private report (kept 30 days)'
  },
  // Setup tab (section 7). Row names, reasons and hints come from `shipm init --check --json`; only the frame is written here.
  setup: {
    title: 'Setup', header: 'Setup · {n} of {m} ready', recheck: 'Re-check all', rechecking: 'Checking…', fix: 'Fix', skip: 'Skip', turnOn: 'Turn on',
    ready: 'Everything required is ready.', notReady: 'Finish the required rows first.',
    badgeAria: '{n} required rows need fixing', badgeAria1: '1 required row needs fixing', checking: 'Checking your setup…', error: 'Could not read setup state', errorSub: 'The check did not answer in time or gave an unreadable answer. Nothing was changed.',
    marks: { ok: 'Ready', red: 'Needs fixing', skip: 'Skipped', info: 'Information' },
    need: { required: 'Required', recommended: 'Recommended', optional: 'Optional', advisory: 'Set in Claude', never: 'On purpose' },
    never: 'Not set up here on purpose: publishing always asks you.',
    fixTip: 'Runs `shipm init --step {id}` in the terminal. Most steps change things at once; a few ask you a question first, there.', skipTip: 'I don\'t want this. It stays grey, nothing nags, and I can turn it on later. Runs `shipm init --skip {id}` in the terminal; it applies at once, no prompt.',
    fixAria: 'Fix {name}', skipAria: 'Skip {name}', turnOnAria: 'Turn on {name}',
    noSkipWhy: 'Required: it cannot be skipped.',
    sentPrompt: 'Running: answer its prompt in the terminal; the row updates by itself.', sentNow: 'Running: this change is applied at once (undo: {undo}).', stillRunning: 'A command is still running in the setup terminal: finish it first.',
    done: 'Done: the Setup list was re-checked.', notDone: 'Not done: see the terminal.',
    sentWait: 'Answer the prompt in the terminal.', unknownRow: 'Setup row not found. Check the Setup list again.',
    finish: 'Finish setup first', finishSub: '{n} required rows need fixing.', finishSub1: '1 required row needs fixing.', finishBtn: 'Open Setup',
    secretNote: 'Sign-in opens your browser. This panel never asks for or shows a password or token.',
    remoteNote: 'Lets you reach your own Claude Code sessions from your phone. Needs a claude.ai paid plan.',
    remoteOff: 'Off by default', remoteOn: 'On', remoteUnknown: 'State not readable',
    undo: 'Undo', undoTip: 'Runs `shipm init --undo remote-control` in the terminal; it applies at once, no prompt. The panel never edits your Claude settings.', undoAria: 'Undo {name}',
    remoteTurnOnTip: 'Runs `shipm init --step remote-control` in the terminal. It explains the setting and asks you to type yes there.'
    // Extension point for F6 (not built; needs an owner-approved UX addendum): a Setup step 'Describe your work' goes after the last row of the CLI list.
  },
  tokens: {
    long: 'Long chats this week: {n}% of tokens (goal under 45%)',
    longTip: 'Share of this week\'s tokens spent in chats past 200k context. Long chats cost more per message. A handoff and a fresh chat keeps this number down. Claude only.'
  },
  // Health tab additions (section 8)
  health: {
    waitHead: 'Waiting on you', badgeAria: '{n} need a look', openChat: 'Open chat', openChatTip: 'Opens this project\'s chat.', back: 'Back to guided', backSure: 'Sure?',
    backTip: 'Stops the run and goes back to guided. Types the command in a terminal; you press Enter there.',
    reasonNeeds: 'Needs you', unknownKind: 'Needs a look'
  },
  // ---- panel v3 revision v2 ----
  // Autopilot line and the Change sheet
  ap: {
    prefix: 'Autopilot ·', lineTip: 'Change how much it asks you', lineAria: 'Autopilot {level} for {project}. Press to change it.',
    levels: { manual: 'Step by step', guided: 'Normal', full: 'On its own' },
    promise: { manual: 'It stops after every step and waits for you.', guided: 'It keeps going, and asks you at approvals and when something risky comes up.', full: 'It works through a request without asking, inside limits you set. Risky things still stop it.' },
    sheetTitle: 'How much should it ask you?', current: 'Current', close: 'Close',
    notNow: 'Not now: it is working. Change it when it is waiting.', held: 'Held: its session is still running.',
    needSafe: 'On its own needs Safe mode on. Turn Safe mode on first.', turnSafe: 'Turn Safe mode on', softwareOnly: 'On its own is for software projects only.',
    switchOff: 'The on-its-own switch is off. In a terminal: shipm switch autopilot.full.enabled on',
    typedLevel: 'Typed the command in a terminal for {project}. Press Enter in the terminal to run it, then type {to} to confirm. Nothing changes until you do.'
  },
  safe: {
    on: 'Safe mode ✓', warn: 'Safe mode: warnings only', off: 'Safe mode off', tip: 'Change Safe mode', aria: 'Safe mode for {project}: {state}. Press to change it.',
    sheetTitle: 'Safe mode', opts: { strict: 'On', warn: 'Warnings only', off: 'Off' },
    desc: { strict: 'It checks every step before moving on. Needed for On its own.', warn: 'It tells you about problems but does not stop.', off: 'No checks between steps.' },
    offBy: 'Off is set by hand in config/flow.json.', busy: 'Not now: it is working. Change it when it is waiting.',
    typed: 'Typed the command in a terminal for {project}. Press Enter in the terminal to run it, then confirm there.'
  },
  // The step timeline: dots only (owner's change 21 Oct: no coloured boxes round the steps)
  steps: {
    aria: 'Steps: {names}', ariaOne: '{name}: {word}',
    meanings: { scope: 'Work out exactly what is being asked.', plan: 'Write down how it will be done.', approve: 'You read the plan and say OK. Nothing starts before this.',
      do: { software: 'Write the code.', app: 'Write the code.', content: 'Write the piece.', research: 'Write the first draft.', ops: 'Prepare the change in the system.', notes: 'Write the note.' },
      verify: { software: 'Run the tests.', app: 'Run the tests.', content: 'Check facts, links and wording.', research: 'Check sources and claims.', ops: 'Try the change without applying it.', notes: 'Check that the note reads right.' },
      review: 'A second reader goes through it for mistakes and risks.',
      deliver: { software: 'Save and hand over the finished change.', app: 'Save and hand over the finished change.', content: 'Put it out. It always asks you.', research: 'Pass the result to you.', ops: 'Make the change real.', notes: 'Put the note in its place.' } },
    detailDone: '{name} · {word}{counts} · {date}', detailNone: 'Done. No report saved for this step.', report: 'report ›', reportAria: 'Open the {name} report', close: 'Close',
    skipTip: 'Skipped: small change', link: 'What do these steps mean?', title: 'The steps', legend: '✓ done · ● now · ○ next · – skipped · ! needs you · ✕ failed',
    nextLine: 'Next: {name}', now: 'Now', next: 'Next', nextAgain: 'Next: {name} again', nextYou: 'Next: your decision', none: 'No request open', allDone: 'Delivered'
  },
  // "On its own" sheet: Keep going until, presets, summary, tick
  own: {
    heading: 'On its own for {project}', intro: 'Your permission for this run. Nothing starts from this form: the commands open in a terminal and you confirm there.',
    untilLabel: 'Keep going until',
    until: {
      a: { label: 'This request is done', hint: '{cr} · {title}' },
      b: { label: 'I stop it (8 hours at most)', hint: 'Works through your open requests in order (up to 5). It stops by itself after 8 hours.', more: 'Only the first 5 are included.' },
      c: { label: 'Until I disable it', hint: 'Keeps working on this project\'s requests until you press Stop. You OK it once a day.' }
    },
    chatOpened: '(opened in a chat)', listAria: 'Requests it will work through',
    noCr: 'No open requests. Open one first, then come back.',
    timeQ: 'How long may it work?', timeStop8: 'It stops after 8 hours, even if you forget.', timeDay: 'It pauses every 24 hours until you say yes.',
    crsQ: 'Requests a day', budgetQ: 'How much of your weekly Claude use may it spend?', dayQ: 'A day', crsQ: 'Requests a day',
    left: 'About {left}% left this week', leftNone: 'We will read your weekly use when it starts.', over: 'That is more than what is left. It stops when your week runs out.',
    more: 'More options', moreStep: 'Want it to stop at each step? Use Normal.',
    goal: 'Goal', goalPh: 'One line: what it should finish', folders: 'Folders it may change', foldersPh: 'src/**, tests/**', foldersNone: 'Say which folders it may change',
    deps: 'New packages', depsNone: 'None', depsListed: 'Listed names', depsPh: 'left-pad, @scope/name',
    hours: 'Exact hours (0.25-8)', share: 'Exact share of the week (1-25)',
    never: 'Never touched: rule files, secrets, git and hook settings', stops: 'Always stops for',
    summaryA: 'It will work on {cr} for up to {time} hours or {budget}% of your week. It may change files in {folders}. It will not add packages. It stops when finished or if something risky comes up, and waits for you.',
    summaryAdeps: 'It will work on {cr} for up to {time} hours or {budget}% of your week. It may change files in {folders}. It may add: {deps}. It stops when finished or if something risky comes up, and waits for you.',
    summaryB: 'It will work through {crs}, one after another, until you stop it, for at most {time} hours or {budget}% of your week. It may change files in {folders}. It will not add packages. Risky things still stop it and wait for you.',
    summaryC: 'It will work through {crs}, then wait for requests you OK, until you disable it. At most {day}% of your week a day and {budget}% a week, up to {crsDay} requests a day. It pauses every 24 hours for your yes. It may change files in {folders}. It will not add packages. Risky things still stop it and wait for you.',
    tickA: 'I understand it will work on its own until it finishes or something risky comes up.',
    tickB: 'I understand it keeps going on its own until I stop it, 8 hours pass, or it finishes these requests.',
    tickC: 'I understand it keeps going and merges into main on its own until I disable it, and I will check it once a day.',
    start: 'Start autopilot', cancel: 'Cancel', startOff: 'Start is off: {why}', tickWhy: 'Tick the box to confirm.',
    notReady: 'engine not ready', notReadyTip: 'Start is off: engine not ready. This option needs a newer Shipmiracle.',
    noCrWhy: 'No open requests. Open one first, then come back.', foldersWhy: 'Say which folders it may change.', dayWhy: 'A day cannot be more than the week.',
    termFull: 'Typed the commands in a terminal for {project}: they set the permission, then ask you to type yes. Press Enter in the terminal to run them. Nothing starts until you do.'
  },
  // Option C note (exact text from autopilot-scope-design.md 8.4)
  cnote: {
    heading: 'Read this before you choose it',
    lines: ['It keeps working without you, also at night, until you press Stop autopilot.', 'Once a day it pauses and waits until you type yes in a terminal.', 'It merges finished work into your main branch by itself after its tests and review pass.',
      'It uses your Claude week: at most {day}% a day and {week}% a week. Your own chats share that limit, so they can run out sooner.', 'New requests are never picked up by themselves. You OK each one in a terminal. Requests a chat opens wait for you.', 'A risky step, a failed test or a rejected review pauses it until you look.'],
    one: 'Only one project can run like this at a time.'
  },
  run: {
    line: '{level} · about {left} left · {used}% of your week used (limit {cap}%)', lineNoTime: '{level} · {used}% of your week used (limit {cap}%)',
    untilStop: '{level} · until you stop it · about {left} left · {used}% of your week used (limit {cap}%)',
    stop: 'Stop autopilot', stopSure: 'Sure?', stopTip: 'Types the stop command in a terminal. You press Enter there.',
    termStop: 'Typed the stop command in a terminal for {project}. Press Enter in the terminal to run it.'
  },
  ended: { time: 'Autopilot finished: {why}. Back to Normal.', timeB: 'Autopilot finished: 8 hours passed. Back to Normal. Start it again if you want more.', lapsed: 'Autopilot stopped: no daily yes for 7 days. Back to Normal.' },
  // Option C: banner on every tab, the band on the card, paused states, waiting requests
  cban: {
    run: 'On its own until you disable it · next check-in in {h} h · today {day}% of {dayCap}% · week {week}% of {weekCap}%', waiting: ' · {n} request waiting for your OK', waitingMany: ' · {n} requests waiting for your OK',
    paused: 'Paused: {reason}', stop: 'Stop', aria: 'Autopilot that runs until you disable it'
  },
  cband: { running: 'Autopilot running until you stop it', waitingReqs: 'Waiting for requests you OK.' },
  cpause: {
    checkpoint: { band: 'Paused: daily check-in. Keep going another day?', slot: 'Keep going', cmd: 'checkpoint', tone: 'warn', short: 'daily check-in' },
    day_limit: { band: 'Paused: today\'s limit reached. Next check-in in {h} h.', slot: 'Keep going', off: 'Keep going is available in {h} h.', cmd: 'checkpoint', tone: 'warn', short: 'today\'s limit reached' },
    week_limit: { band: 'Paused: your week limit for autopilot is reached.', slot: 'Keep going', off: 'Keep going is available when your week resets.', cmd: 'checkpoint', tone: 'warn', short: 'week limit reached' },
    qa_fail: { band: 'Paused: tests failed on {cr}. It will not go on without you.', slot: 'Resume', cmd: 'resume', tone: 'red', drop: true, short: 'tests failed on {cr}' },
    review_reject: { band: 'Paused: the review did not accept {cr}. It will not go on without you.', slot: 'Resume', cmd: 'resume', tone: 'red', drop: true, short: 'review did not accept {cr}' },
    unknown_request: { band: 'Paused: {cr} asked to open a new request. It will not go on without you.', slot: 'Resume', cmd: 'resume', tone: 'red', drop: false, short: '{cr} asked to open a new request' },
    budget_unknown: { band: 'Paused: your weekly use cannot be read right now. It will not go on without you.', slot: 'Resume', cmd: 'resume', tone: 'warn', drop: false, short: 'weekly use unknown' }
  },
  cwait: { head: 'Waiting for your OK', row: '{id} · {title} (opened in a chat)', rowTerm: '{id} · {title}', btn: 'Let autopilot do it', openAuto: 'Open the auto chat', drop: 'Drop {cr}',
    verbTip: 'Types the command in a terminal. You press Enter there.', typed: 'Typed `{cmd}` in a terminal for {project}. Press Enter in the terminal to run it.', notReady: 'Not typed: the engine does not support this yet.' },
  // ---- UX addendum 2026-10-21 (F5 Toolbox, F6 Describe your work, F7 Set aside, F8 Unread marker, F9 Details). English only, Western digits, {name} = slot.
  toolbox: { menuItem: 'Toolbox', menuItemN: 'Toolbox · {n}', heading: 'Toolbox for {project}', intro: 'Scripts, templates and docs signed off for reuse.', back: '‹ Back',
    empty: 'No assets yet. Add scripts, templates or docs you want reused.', add: 'Add an asset…', addNote: 'Typed in a terminal. Fill in the path, stage and purpose, then press Enter. You confirm there.',
    removeCmd: 'Copy remove command', resignCmd: 'Re-sign command', ok: 'Unchanged', changed: 'Changed since sign-off', changedHint: 'Check it, then run the add command again to sign it off.',
    rowAria: '{path}, used in {stage}, {status}. {purpose}', more: '+{n} more', error: 'Could not read the toolbox. Try again.', retry: 'Retry', held: 'Not now: its session is still running.',
    typed: 'Typed the command in a terminal. Press Enter there to run it.', notReady: 'The toolbox is not available yet.', missing: 'File missing', stageNone: 'any stage' },
  proposed: { heading: 'Proposed assets ({n})', kindNew: 'new', kindChanged: 'changed', addCmd: 'Copy add command', note: 'Nothing is added until you run the command yourself in a terminal and confirm there. Claude cannot do it for you.', cmdLabel: 'Command to run in a terminal', copied: 'Copied the add command. Paste it into a terminal and press Enter there.', noCmd: 'No command offered: the file name is unusual. Add it yourself with shipm playbook asset add.',
    rowAria: '{path}. {why}', copyAria: 'Copy the add command for {path}',
    changedAtDeliver: 'Asset changed: {path}', error: 'Could not read the proposed assets.', gone: 'This report is for a project you no longer have.' },
  describe: { setupName: 'Describe your work', setupOptional: 'Optional. Answer a few questions and get a draft playbook.', setupDraft: 'A draft playbook is ready to read.', setupDone: 'Playbook set from your answers.',
    start: 'Start', menuItem: 'Describe your work…', heading: 'Describe your work: {project}', suggested: 'Suggested',
    shortName: 'Short', shortMeta: 'about 3 questions, 1-2 minutes', shortWhy: 'Enough to start. You can run Long later.',
    longName: 'Long', longMeta: 'about 10 questions in up to 3 rounds, 5-8 minutes',
    longWhy: 'Gives the agent more detail to build your playbook and definition of done from, which should mean fewer rework rounds. (Not proven yet; we will measure it.)',
    longContinues: 'Continues from your Short answers. It never asks them again.', startTerm: 'Start in terminal', typed: 'Typed the command in a terminal. Press Enter there to start.', cancel: 'Cancel',
    progress: 'Question {n} of about {total}', recommended: 'Recommended', termHint: 'In the terminal:', accept: 'Accept', edit: 'Edit', skipRest: 'Skip rest', keys: 'Enter = Accept · type = Edit · s = Skip rest', showTerm: 'Show terminal',
    assumed: 'Assumed so far ({n})', assumedMark: 'Assumed', prototype: 'A throwaway prototype will answer this.',
    draftHeading: 'Draft playbook: read it, then run the command', openDraft: 'Open draft', copySet: 'Copy set command', draftNote: 'Nothing is trusted yet. The draft only counts after you run the command and confirm.',
    paused: 'Interview paused at question {n} of about {total}', resume: 'Resume', startOver: 'Start over', sure: 'Sure?',
    errInterview: 'The interview did not finish. Start again.', errDraft: 'The draft could not be read. Open it or start over.', busy: 'Not now: {project} is working.', noShipmiracle: 'Shipmiracle is not installed. Fix this in Setup.',
    mirrorHead: 'Describe your work · {project}', modeShort: 'Short', modeLong: 'Long', rowAssumed: 'Assumed', typedResume: 'Typed the command in a terminal. Press Enter there to continue.', typedSet: 'Typed the command in a terminal. Read the draft first, then press Enter and confirm there.', notDraft: 'There is no draft to apply.',
    rowWork: 'Work', rowInputs: 'Inputs', rowOutputs: 'Outputs', rowTools: 'Tools', rowRisks: 'Risks', rowApproves: 'Who approves', rowDone: 'Definition of done', rowNever: 'Never allowed' },
  aside: { setAside: 'Set aside', bringBack: 'Bring back', heading: 'Set aside ({n})', since: 'since {date}', rowAria: '{project}, set aside since {date}',
    notNowAuto: 'Not now: autopilot is running.', notNowWait: 'Not now: {project} is waiting for you.', typed: 'Typed the command in a terminal. Press Enter there to run it.',
    healthHeading: 'Set aside: {n} silenced', healthRow: '{project}: {title} (not shown elsewhere)', returnedWork: 'Brought back: {project} started work.', returnedStop: 'Brought back: {project} hit a hard stop.',
    backOnList: 'Back on the list: {why}', error: 'Could not read the set-aside list. Try again.', dismiss: 'Dismiss', openOne: 'Show {project}',
    whyHardStop: 'it hit a hard stop', whyIntegrity: 'a gate file changed', whyLimit: 'the usage limit is near', whyScan: 'the safety scan blocked it' },
  details: { toggle: 'Details', toggleAria: 'Details for {project}', toggleTip: 'Show details', toggleTipOpen: 'Hide details', region: 'Details for {project}', loading: 'Loading details…', empty: 'Nothing to show yet.',
    now: 'Now', rowQuiet: 'Quiet', rowStage: 'Stage', rowAgent: 'Agent', rowCommit: 'Commit', agentVal: '{agent}, wrote {when}', agentNone: 'None running', commitVal: '{when} · {n} uncommitted', commitOnly: '{n} uncommitted', moreAgents: '+{n} more',
    chat: 'Last from the chat', rowTool: 'Tool', chatHidden: 'Hidden. Turn on {setting} in Settings to see it here.', chatError: 'Could not read the chat.', showMore: 'Show more', showLess: 'Show less',
    report: 'Latest report', rowVerdict: 'Verdict', rowTitle: 'Title', rowSummary: 'Summary', reportLink: 'Open report ›', reportLinkAria: 'Open the latest report of {project}',
    status: 'STATUS', rowNote: 'Note', rowNext: 'Next',
    justNow: 'just now', minAgo: '{n} min ago', hAgo: '{n} h ago', yesterday: 'yesterday',
    quiet: 'No new step for {n} min.', quietTests: 'Tests running {n} min.', error: 'Could not read the details. Try again.', retry: 'Try again',
    settingName: 'shipmiracle.cardChatExcerpt', settingDesc: 'Show the chat\'s last message inside a project card\'s Details. Chat text can show on screen shares. Text that looks like a key, token or password is masked as [hidden] (best-effort masking, about 89% of the secret shapes in a fresh corpus we had not tuned for, not a guarantee: a bare password in a sentence or a secret with no key name around it can still show, and code-like text can be masked too).',
    months: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'] },
  unread: { word: 'New', turn: 'New: its chat finished a turn.', wait: 'New: its chat is waiting for you.', cardAria: '{project}, new: {why}', whyTurn: 'the chat finished a turn', whyWait: 'the chat needs you',
    settingDesc: 'Show a small New marker on a project when its chat finished a turn or needs you.' },
  // ---- cross-platform onboarding (plan 2026-10-21-cross-platform-onboarding.md 4.6): the Setup tab's calm view, the not-ready rows, the Quick setup card and Details
  quick: { title: 'Quick setup', intro: 'Five short choices. The recommended answer is selected. Run in terminal saves them at once (undo: shipm init --undo prefs).', recommended: 'recommended',
    lang: 'Language for reports', langEn: 'English', langAr: 'Arabic', folder: 'Projects folder', folderHelp: 'A folder in your home folder, like ~/Developer.', autonomy: 'How much should the team do by itself?', autNormal: 'Normal', autStep: 'Step by step', autOwn: 'On its own',
    awake: 'Keep the computer awake while Claude works?', yes: 'Yes', no: 'No', notify: 'Notifications', notVscode: 'In VS Code only', notSystem: 'Also system pop-ups', notNone: 'None',
    cmdLabel: 'Command to run', run: 'Run in terminal', badFolder: 'Not run: the folder must start with ~/ or /.',
    needs: 'Needs you', details: 'Details', checkAgain: 'Check again', calmTitle: 'Setup complete', calmSub: 'Everything Shipmiracle needs is in place.', unsupported: 'Not supported on this OS', docs: 'More: {url}', osAria: 'This computer',
    markOk: 'ready', markNeeds: 'needs you', markOpt: 'optional', markNo: 'not supported on this system', headerFix: 'Setup · {n} to fix' },
  a11y: { projectCard: 'Open the {project} chat' },
  help: {
    cardTip: 'Click: open this project\'s Claude chat here · ⌘-click: open the project in a new window',
    cardTipOther: 'Click: open this project\'s Claude chat here · Ctrl-click: open the project in a new window'
  },
  // Where the panel runs (hostx.js). The WSL 2 install sentence itself comes from the CLI (`shipm init --check --json`, os.line), never from here.
  host: {
    winTitle: 'Windows is not supported yet', winBody: 'Shipmiracle runs inside WSL 2 (Linux on Windows). Set it up there and open VS Code in WSL.', hintLabel: 'How to install WSL 2',
    experimental: 'Linux and WSL 2 support is experimental. Some things may not work yet.',
    chatUnknown: 'Chat health: unknown on this computer. The panel cannot tell a stale chat from a live one here, so it never closes or relaunches a chat by itself.'
  },
  // Tidy up card (G2, UX addendum section 11k): read-only, rendered by tidyx.js. No internal word (scan, partial, condition, tidy.json) is shown to the owner.
  tidy: { heading: 'Tidy up',
    none: 'No report yet. The daily check makes the first one within a week.',
    unreadable: 'Could not read the tidy report. The next daily check will try again.',
    empty: 'Nothing to tidy.', emptyP: 'Nothing found in what could be measured.', noProjects: 'No projects were checked.',
    sumBoth: '{free} could be freed. {decide} is up to you.', sumFree: '{free} could be freed.', sumDecide: 'Nothing to free without you. {decide} is up to you.',
    sumBothP: 'At least {free} could be freed. At least {decide} is up to you.', sumFreeP: 'At least {free} could be freed.', sumDecideP: 'Nothing to free without you. At least {decide} is up to you.',
    rowFree: 'Could free {size}', rowDecide: 'You decide {size}', rowFreeP: 'Could free at least {size}', rowDecideP: 'You decide at least {size}',
    more1: 'and 1 more project.', moreN: 'and {n} more projects.',
    partial: 'Some folders were too large to measure fully. Real sizes may be larger.',
    old: 'This report is {n} days old. Sizes may have changed.',
    weeks: 'Over {size}: {k} of {n} weeks in a row',
    met: 'Over {size} for {n} weeks in a row. You can ask for a clean-up plan. Nothing is moved or removed until you approve it.',
    checked: 'Checked {when}', today: 'today', yesterday: 'yesterday', daysAgo: '{n} days ago',
    open: 'Show the full report', openTip: 'Types shipm tidy --all in a terminal. You press Enter to run it. It only reads.',
    typed: 'Typed the command in a terminal. Press Enter there to see the report.',
    noTool: 'Not available: shipm is not installed. Fix this in Setup.',
    foot: 'Read-only: this card never moves or deletes anything.' },
  // Two-level project timeline (owner approved 30 Oct 2026): the release line, the idle block that stands where the rail would be, the unplanned-work wording, the History list. Shown only when the engine says caps.release.
  tl: {
    released: 'Released v{v}', working: 'working on v{v}', doneOne: '{n} change done', doneN: '{n} changes done', sinceDoneOne: '{n} change done since', sinceDoneN: '{n} changes done since', nothingNew: 'nothing new since',
    ready: 'v{v} ready', readyOne: '{n} change done since v{v}', readyN: '{n} changes done since v{v}',
    mark: 'Mark v{v} released', markTip: 'Types the command in a terminal. You press Enter there to record v{v} as released.', markAria: 'Mark v{v} released for {project}',
    noRelease: 'No release yet', building: 'building v{v} ({src})', buildingNoSrc: 'building v{v}', lastDone: 'Last done: {cr}', relAria: 'Release: {text}',
    lastChange: 'Last change:', doneOn: 'done {date}', noChangeYet: 'No change finished yet', nextStart: 'Next: start a change ({first})',
    start: 'Start a change', startAria: 'Start a change in {project}', startTip: 'Types the command in a terminal. Write the title between the quotes, then press Enter there.',
    track: 'Track as a change', trackAria: 'Track the unplanned work in {project} as a change', idleAria: 'No change in progress in {project}',
    unplanned: 'Unplanned work · not on the timeline', chatOnly: 'Chat open · no change yet', done: 'Done',
    hist: 'History ({n})', histAria: 'History of {project}: {n} changes', histRegion: 'Changes of {project} by release', hRel: 'Released in v{v}', hNone: 'Not released yet',
    typedMark: 'Typed in the {project} terminal: shipm release mark {v}. Press Enter there to record it.', typedOpen: 'Typed in the {project} terminal: shipm cr open --project {project} \'\'. Write the title between the quotes and press Enter.',
    notMark: 'Not typed: {why}', whyNoCap: 'this engine cannot record releases yet.', whyOpen: 'a change is still open.', whyVersion: 'v{v} is not the version being built.', whyNothing: 'no finished change since the last release.'
  },
  nowTabBadge: '{n} waiting on you'
};
