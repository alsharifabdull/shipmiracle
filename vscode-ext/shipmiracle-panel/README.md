# Shipmiracle panel (VS Code extension `shipmiracle-panel`)

A side panel that shows every project of your Shipmiracle at a glance and helps you act on what needs you. It reads local files only (your projects folder, the shipm state folder, the output of `shipm report panel` and `shipm init --check --json`). It makes no network call and loads nothing from outside.

## The five tabs

| Tab | What it shows |
|---|---|
| **Projects** | A "Now / Next / Waiting on you" block, then one card per project: status line, the seven-stage strip (names follow the project type), change-request chips, the last test verdict, the autopilot level, one primary button (Review plan, Decide, Start CR-n, Open chat), an `Ask aside` button and a `...` menu. Also the New project box and, when the Ask inbox exists, one Ask card. |
| **Reports** | Stage reports, change-request reports and daily digests from the reports index. FAIL and BLOCKED first, filters by verdict, kind and project, a viewer that always shows "Not verified". |
| **Ideas** | The ideas of each project (`docs/FEATURE-IDEAS.md`), worth-it checks and promotions. |
| **Health** | Things that need attention (frozen chats, stuck steps, stopped autopilot runs, leftover processes) with a Fix, Open chat or Back to guided button where one exists, or the next step in words. |
| **Setup** | The rows of `shipm init --check`: red, green or skipped, Fix and Skip, Re-check. Required rows have no Skip. No secret is ever asked for or shown. |

## The owner-terminal trust rule

The panel is a window onto your workspace, not a second owner.

- It **never writes a trusted file** (gate config, playbook, charter, settings, registry). Those are written only by `shipm` commands that you run.
- It **never sends approval text** to a chat. Approving a plan, allowing a hard stop and starting full autopilot are words or commands that only you type.
- A state-changing action is **prefilled, not run**: the panel types the exact command into an "Shipmiracle" terminal and stops. You read it and press Enter. Each prefill starts with a line clear, so two clicks never run together. The one exception is the Setup tab: Fix, Skip, Undo and Quick setup "Run in terminal" run their `shipm init ...` command in the visible "Shipmiracle · setup" terminal for you (one click, no Enter from you). Some steps (remote-control, github, projects, vscode, guard, ask-inbox, and the prefs row) ask you a question in that terminal and the panel says "answer its prompt"; Skip, Undo, Quick setup and the other steps apply at once with no question, and the panel says "applied at once" with the command that undoes it. A new click is refused while a command is still running in that terminal. When it ends the row turns green by itself; if it fails or the terminal is closed the panel says "Not done: see the terminal" and the row stays red.
- Text the panel puts into a chat (a first message, a handoff request) starts with the marker `[panel] ` so it cannot be mistaken for your own words. The one exception is `Ask aside`, which only types `/btw ` and never presses Enter.
- Every file it reads from a project is size-capped and never followed through a symlink; a device or FIFO is skipped.

## Settings

The extension adds no VS Code settings and no keybindings. It reads these `shipm` settings (change them with `shipm config set`, not in the panel):

| Key | Used for |
|---|---|
| `paths.projects_dir` | where your projects live (default `~/Developer`) |
| `engine.dir` | the Shipmiracle checkout whose `bin/shipm` the panel runs |
| `ask.daily_limit` | the daily number of Ask inbox questions (1-200, default 20) |
| `autopilot.full.enabled` | whether full autopilot can be chosen |

## Keyboard

Everything is reachable with the keyboard and shows a focus ring.

| Keys | Action |
|---|---|
| Tab / Shift+Tab | next / previous control |
| Left / Right, Home, End | move between the five tabs (the tab opens as you move) |
| Enter or Space | press the focused button; open a menu |
| Up / Down, Home, End | move inside an open menu |
| Esc | close a menu, cancel the charter editor, leave the report viewer; focus returns to where you were |

With `prefers-reduced-motion` the panel runs no animation or transition.

## Themes and accessibility

Text is at least 4.5:1 and icons or marks at least 3:1 in Dark+, Light+, High Contrast, Dark Modern, Light Modern, 2026 Dark and 2026 Light (measured by `tests/panel_v3_a11y_test.js`). High Contrast adds a 1 px contrast border. Colour is never the only signal: every state also has a word or a shape.

## Safety of the page

The page is built by `panel.js` from data that `sane.js` has shape-checked. Every value is escaped; the Content-Security-Policy is `default-src 'none'` with a per-render nonce for the one style and the one script; there are no inline handlers, no external URLs and no local resource roots.

## Screenshots (kept in the private development repo, not in the public export)

`tests/fixtures/panel-v3/` holds, for light and dark: `idle`, `building`, `approval`, `verify-fail`, `hardstop`, `delivered`, `charter-editor`, `reports`, `setup`, `health`, `ask-inbox`, `setup-remote`; and in high contrast: `approval`, `hardstop`, `setup`, `health`. `docs/summary/panel-shots-manifest.json` lists them with sizes and captions. Regenerate with `SHIPMIRACLE_SHOTS=1 node tests/panel_v3_ui_test.js`. Both folders are on the release hard-never list.

## Tests

`tests/panel_v3_ui_test.js`, `panel_v3_golden_test.js` (live data), `panel_v3_a11y_test.js`, `panel_v3_perf_test.js`, `panel_v3_safety_test.js`, `ext_*_test.js`, `data_flow_test.js`. Each runs on its own: `node tests/<name>.js` (they skip the browser part when Chrome is not installed).
