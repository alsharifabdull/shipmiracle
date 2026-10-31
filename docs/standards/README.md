# docs/standards

The engineering standard of every project, split by how often it is needed.

| File | Loaded | Content |
|---|---|---|
| `base.md` | always (copied into each project's `CLAUDE.md` between the `SHIPMIRACLE-STANDARD` markers by `shipm standard sync`) | the rules that gate behaviour; at most 4,096 bytes (a test enforces it) |
| `team.md` | on demand | roster, old-name aliases, team combinations, stage rules, model rule, models and quota, inviting an agent |
| `records.md` | on demand | writing the records, repo-is-memory details, STATUS rules |
| `skills.md` | on demand | skills policy; `npx skills find <topic>` |
| `ideas.md` | on demand | feature ideas |
| `long-jobs.md` | on demand | jobs over about 10 minutes |

Edit the files here, never the copies in a project (they carry a "managed" header and are overwritten by the sync).
This README is not copied to projects.

## Dropped on purpose

`tests/standard_test.py` proves that every rule sentence of the old `AGENTS.md` (kept as `tests/private/fixtures/standards/AGENTS.v1.md`)
appears in `base.md` or an on-demand file, or is listed here with the reason. The old text must match the first column.

In the table, `{Eng}` / `{eng}` stand for the removed second engine's name (written out in the old text; kept as a placeholder so this public file does not carry it).

| Old text | Reason |
|---|---|
| These rules apply to every project created from this workspace. | replaced by the `SHIPMIRACLE-STANDARD` marker line, which says the block is managed |
| A project's own `AGENTS.md` starts with these | projects no longer have an `AGENTS.md`; project rules follow the managed block in `CLAUDE.md` |
| Claude Code reads this file through `CLAUDE.md` (`@AGENTS.md`); {Eng} reads it directly. | second-engine-only; `CLAUDE.md` is now the file itself |
| {Eng} and anyone else: run | second-engine-only (no session brief outside Claude Code) |
| Claude Code and {Eng} work on the same folder. | second-engine-only (one engine) |
| They do not see each other's chats. | second-engine-only (two-engine handoff) |
| {Eng} working through the MCP server cannot write `.git`; Claude commits for it. | second-engine-only |
| Claude commits for it | second-engine-only |
| Machine-local state (`~/.claude`, `~/.{eng}`) | the `~/.{eng}` half is second-engine-only; `~/.claude` is kept in base.md |
| {Eng}: `/plan` | second-engine-only |
| `/plan` in {Eng} | second-engine-only |
| {Eng} `/review` | second-engine-only |
| `.{eng}/agents/` | second-engine-only (the {Eng} team is removed) |
| write the plan, and wait for the owner's approval before building | kept in base.md in shorter words |
| and in which tool | only one tool exists now |
| \| routing \| engineering-lead \| Opus \| | the engineering-lead role is retired: the main chat routes (see team.md) |
| The session the owner is talking to is the Engineering Lead. | the main chat is the lead and routes; there is no lead agent (team.md) |
| {Eng}: long mechanical implementation, bulk refactors, test writing, and cloud tasks from the phone. | second-engine-only |
| `find-skills` | replaced by `npx skills find <topic>` (skills.md) |
