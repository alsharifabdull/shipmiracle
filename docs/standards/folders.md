# Project folder standard

One place for each kind of file, so things can be found and swept. On demand: read it when you create a folder, save a screenshot, mockup or export, or when `shipm tidy` makes a suggestion.
`shipm tidy [PROJECT|PATH] [--json] [--standard]` compares a project with this page and only reports. It never moves, deletes or writes. Moving things is a normal build turn or the owner's own hand.

## Where things go
| Path | For | Git |
|---|---|---|
| `AGENTS.md`, `CLAUDE.md`, `README.md` | rules, entry | tracked |
| `docs/STATUS.md`, `DECISIONS.md`, `FEATURE-IDEAS.md`, `SKILLS.md`, `docs/memory/`, `docs/plans/<date>-<slug>.md` | the records | tracked, never swept |
| `docs/reports/<date>-CR-n.md` | change-request reports | tracked |
| `docs/summary/<date>-<slug>/` (`index.md` + its images) | owner-facing summaries and the mockups shown to the owner | tracked (private: never in the public export) |
| `design/` | kept design sources and APPROVED mockups and prototypes | tracked |
| `src/`, `apps/`, `packages/`, stack folders | code | tracked |
| `tests/`, `tests/fixtures/` | tests and their inputs, golden screenshots included | tracked |
| **`.scratch/<date>-<slug>/`** | **the one scratch place** for anything worth more than a session: QA screenshots, run evidence, throw-away prototypes, downloads, exports. Session-only junk stays in the Claude scratchpad | ignored; disposable 14 days after its newest file, only with the owner's yes |
| `archive/` | the owner's own old versions and zips kept on purpose | ignored; never swept |
| `backups/` | the owner's backups (may be the only copy on this Mac) | ignored; never swept |
| build and dependency folders: `node_modules`, `dist`, `build`, `.next`, `.turbo`, `.venv`, `__pycache__`, `.pytest_cache`, `coverage`, `test-results`, `playwright-report`, `.playwright-mcp`, `DerivedData`, `.build`, `.gradle`, `Pods` | regenerable | ignored |
| `.shipmiracle/`, `.claude/`, `.githooks/`, `.github/`, `.vscode/` | tool config | tracked; `.claude/_backup/` is ignored: keep the newest 3, dispose after 30 days |
| outside the project: `~/Developer/.worktrees/<project>/snap-<tag>` and `auto-CR-n` | snapshots and autopilot worktrees | disposable: snap after 24 h, auto-CR-n after delivery + 7 days |

## Names
- `YYYY-MM-DD-<slug>` for every dated folder or file (plans already do this).
- Screenshots are `<width>-<theme>.png` inside a dated folder.
- No spaces in names (use dashes). Counter-example: `Claude outputs/`.

## What `shipm tidy` calls things (first match wins)
1. **Protected (never)**: anything tracked or holding a tracked file, `.git`, secret-looking names (`.env`, `.env.*`, `*.pem`, `*.key`, `*.p12`, `*.pfx`, `secrets.*`, `id_rsa*`, `id_ed25519*`) and any folder that contains one, the records, `design/`, `archive/`, `backups/`, tool folders, symbolic links, pipes/sockets, and anything a tracked markdown page links to (inline, reference-style or HTML `src`/`href`; a link to a file inside a folder, or to a folder above it, protects it too).
   `backups/` and `archive/` are listed as "may be the only copy on this Mac" and never offered.
2. **Rebuildable**: ignored AND its tool marker (a regular file) is next to it (`node_modules` with `package.json`, `.venv` with `pyvenv.cfg`, `Pods` with `Podfile.lock`, `dist`/`build`/... in a project with a stack file). Marked "in use" when the project had activity in the last 14 days. If it holds a secret-looking file it is demoted to "needs a decision".
3. **Throw-away by the standard**: `.scratch/*` untouched for 14 days; `.claude/_backup/*` beyond the newest 3 and older than 30 days. Only when git ignores them.
4. **Needs a decision**: any other ignored or untracked item over 50 MB or older than 90 days; an unignored `.scratch` item of 30 days or more and an unignored `.claude/_backup` item older than 30 days (beyond the newest 3), whatever their size or age; and any item the scan could not look at completely (scan limit, unreadable or very deep folder, another disk): nothing is claimed about it, and it is never called throw-away or rebuildable. In `--json` such an item has `measured: false` and `null` for `bytes` and `age_days` (no real-looking numbers).
Untracked, not ignored, younger than 30 days is work in progress and is not offered. Sizes are allocated bytes; a hard-linked file counts once; age is the newest file inside.
Limits: the scan reads at most 20,000 top-level names, 2 million entries and 20 seconds, then says "partial". A single folder deeper than 64 levels is marked "not fully measured" on its own. For links it reads at most 2,000 tracked markdown files, 1 MB per file and 32 MB in all; if any page is skipped, unreadable (a pipe, a link, too big) or over those caps, nothing at all is offered for clean-up and a note says so.
Output: the text report shows 15 items per class and "... and N more"; `--json` carries the largest 50 per class, at most 50 suggestions and skipped names, and an `omitted` count for the rest.
`shipm tidy NAME`: a path that exists in the current folder is read as a path before a project name is tried; use `./NAME` or `/full/path` to be explicit.

## Adoption
- New projects: add `.scratch/`, `archive/`, `test-results/`, `playwright-report/`, `.playwright-mcp/`, `.next/`, `.turbo/` to `.gitignore` (the template change is a later task).
- Existing projects: run `shipm tidy PROJECT --standard` and move things by hand, for example a project's 38 `v1xx` folders and 4 zips into one ignored `archive/`.
- Weekly scan (built): the daily run does `shipm tidy --all --write --weekly` when the Mac is not busy. It looks at every project once a week (at most 300 seconds in all, at low priority), changes nothing in any project, and keeps only sizes and counts in `<state>/v1/tidy.json`: 8 weeks, no file names. "Can be freed" there means throw-away items plus rebuildable items in projects idle for 14 days or more. When four complete weekly scans in a row show more than 2 GiB to free, the engine records that once (event `tidy.condition_met`); nothing is moved or removed because of it. `shipm tidy --all` shows the same one-line summary without saving. Shape of `tidy.json` data: `{schema: 1, scans, projects, condition}`; a file with a missing or different `schema` counts as no history and is replaced on the next `--write`. `scans[]` = `{ts, iso_week, complete, projects_scanned, projects_skipped, duration_s, bytes: {disposable, regenerable_idle, regenerable_in_use, review}}`. `projects[]` (latest scan, 100 largest) = `{name, partial, git, idle_days, counts: {regenerable, disposable, review, never}, bytes: {disposable, regenerable, review, never}, freeable}` where freeable = disposable + regenerable (regenerable only when the project is idle 14 days or more). `condition` = `{threshold_bytes, weeks_needed, weeks_over, met, met_since}`. The 300 seconds is a target: every git question is also bounded by the project's remaining budget (at least 1 second), so a run can overshoot by a few seconds, and `bin/daily` kills the whole step after 420 seconds. Scans dated more than a day ahead, scans whose week does not match their time, and a `tidy.json` that is not ours are ignored, and a forged one is replaced on the next write (a folder with content in its place is kept and reported).
- Not built yet (phase 2 and later): the "Tidy up" panel card, worktree rows, and any move/quarantine/restore/purge. Those need the owner's separate go; the quarantine only if four weekly reports show more than 2 GB to free.
