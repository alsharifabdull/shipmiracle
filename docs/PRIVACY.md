# Privacy

Shipmiracle runs on your machine. It has no server, no account, no analytics and no telemetry. The code contains no HTTP client of its
own. It starts tools you already use (`git`, `gh`, `claude`, `code`), and those make their own network calls under their own terms.
Nothing from Shipmiracle itself leaves your computer.

This page lists what is written, where, and for how long. Folder names are the defaults; `~` is your home folder.

## What is written

| Where | What | Kept |
|---|---|---|
| `~/.config/shipmiracle/` | your settings (`config.json`) and your project list (`registry.json`) | until you uninstall with `--purge` |
| `~/.local/state/shipmiracle/v1/events.jsonl` | one line per event: event name, source, a project id (12 hex characters), step names, change-request ids, counts. Keys named token, secret, password and similar are refused. | rotated at 5 MiB, 3 old files kept, old files deleted after `logs.retention_days` (default 30) |
| `~/.local/state/shipmiracle/flow-events.jsonl` | gate events: time, project folder name, session id, event name, tool and agent names, file base names (no folders), names of environment variables that were set, line counts, and for a tester verdict the first 120 characters of the evidence text the tester wrote | not rotated or deleted by Shipmiracle today; the chosen policy is 30 days, then delete (not built yet) |
| `~/.local/state/shipmiracle/away-decisions.jsonl` | when a chat stops with a question while you are away: time, project name, the last 300 characters of that question, the rule applied | not rotated or deleted by Shipmiracle today; the chosen policy is 30 days, then delete (not built yet) |
| `~/.local/state/shipmiracle/ledger.jsonl` and `ledger.summary.json` | token counts per Claude call (model, project, session, counts); no message text | rows older than 8 days are not needed by the summary; rotated at 20 MB. The chosen policy is 8 days, which matches what the summary uses; old rows are ignored, not deleted, before rotation |
| `/private/tmp/claude-<uid>/` (Claude Code's own task output files) | not written by Shipmiracle. If you turned on the optional awake guard, its watcher (about every minute; `auto` in `config/watch.json`) deletes files there older than 7 days and ends processes it can prove are orphans of a dead chat; set `"auto": false` to stop that | n/a |
| `<project>/docs/memory/` | `bin/apply-template` copies Claude's own auto-memory notes for that project (from `~/.claude/projects/<project path>/memory`) into the project's `docs/memory/`, once, so they become part of the project's repository: read them before you share or publish that repository | yours; it is part of the project |
| `~/.local/state/shipmiracle/v1/reports/` | stage reports of change requests (PASS, FAIL, BLOCKED and notes written by the agents) and an index | 30 days |
| `<project>/docs/reports/` | the final report of a change request, in your project's repository | yours; it is part of the project |
| `~/.local/state/shipmiracle/v1/autopilot-ledger.jsonl` and run state | autopilot run bookkeeping; a hard stop keeps a short excerpt (200 characters at most, secrets masked) of what stopped it | until purge |
| `~/.local/state/shipmiracle/stop-tests.log`, `flow-errors.log` | the tail of your test command's output when a chat stops; errors of the hook scripts | not rotated or deleted by Shipmiracle today; the chosen policy is 30 days, then delete (not built yet) |
| `~/.local/state/shipmiracle/v1/hooks-record.jsonl` | hook inputs recorded for replay. Off by default (`hooks.record`), masked, 7 days, 10 MB then rotated | only if you turn it on |
| `~/.local/state/shipmiracle/v1/install-manifest.json` and `install-backups/` | what setup wrote, and backups of changed files | until purge |
| `~/.local/state/shipmiracle-diag/` | the panel's `panel-trace.log` (short technical lines, emptied at 100 KB) and `panel-render.json` (counts only) | until you delete it |

## Chat text

- The panel can show the last message of a project's chat inside a card's Details. The public build ships with this **off**
  (VS Code setting `shipmiracle.cardChatExcerpt`). When it is on, the panel reads the end of the newest Claude session file of that
  project, shows at most the first 280 characters of the last assistant message, and caches it in memory for 15 seconds. It does not write
  that text to a file.
- Text that looks like a key, token or password is masked as `[hidden]`. This is best effort, not a guarantee: a bare password inside
  a sentence can still show. Chat text can appear on screen shares.
- Away decisions (table above) keep up to 300 characters of the last question in a local file. Today it is stored as the chat wrote it, without masking, so do not put secrets in a question; masking secret-shaped text before it is written is planned and not built yet.
- Claude Code itself stores your sessions under `~/.claude/`; that is Claude Code's behaviour, not Shipmiracle's. The ledger only
  reads those files for token counts and never writes there.

## Masking and secrets

- Shipmiracle never asks for, reads or stores a password, token or API key. Sign-ins happen in the tool's own login.
- Masking of secret-shaped text is best effort. About 89% of secret shapes in a fresh test corpus were masked; the rest are listed as a known limit.
- Most state files and folders are created readable by you only (mode 600 or 700). Some log files (for example the gate's `flow-events.jsonl` and `flow-errors.log`) are created with your system's default file mode, so check `ls -l` on `~/.local/state/shipmiracle` if other accounts share the machine.

## What leaves your machine

Nothing from Shipmiracle itself. The tools it starts can: `claude` talks to Anthropic, `gh` and `git` talk to GitHub or your remote, `code`
may talk to Microsoft's extension service. Their terms apply. Badges shown on the README page are loaded by your browser from third-party
hosts, not by the tool.

## Delete everything

```
bin/shipm uninstall --apply --purge
rm -rf ~/.local/state/shipmiracle-diag
```

Then remove the clone. Reports inside your projects stay with your projects.
