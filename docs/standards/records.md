# Writing the records (on demand)

- STATUS and DECISIONS are short, dated, factual. No transcripts.
- Distinguish: verified / implemented, not verified / planned / proposed / rejected / unknown.
- Preserve existing project rules when migrating a project; reconcile, do not overwrite.
- Everything a future session needs is a file in this repo: `docs/STATUS.md`, `docs/DECISIONS.md`, `docs/memory/` (Claude's project memory, committed), `docs/plans/` (approved plans, auto-saved). Machine-local state (`~/.claude`) is a cache, never the record.
- Every commit is pushed automatically (`.githooks/post-commit`). A commit is a backup; commit small and often.
- STATUS first lines: `Updated:` with today's date, model and mode. The Stop hook and the pre-commit hook refuse source changes with a stale STATUS.
- Inspect the code before trusting STATUS or DECISIONS: code and test output are the truth; the two files are the record of it.
- Never say "the next session will know"; write it in STATUS.
- Commit before handing a checkout to another chat; one chat edits a checkout at a time, parallel work uses separate worktrees (`claude --worktree <name>` or `git worktree`).
- The handoff is `docs/STATUS.md` plus a Git commit, nothing else.
