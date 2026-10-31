# Team (on demand)

Roles are Claude Code subagents in `.claude/agents/`; the chat the owner talks to is the lead and routes the work.

## Roster
| Role | Stage / Flow role | Model | maxTurns | Use when |
|---|---|---|---|---|
| scoper | scope | Sonnet | 20 | acceptance criteria, edge cases, open questions before planning |
| planner | plan | Opus | 40 | any design or plan, or a mid-work impact check |
| builder | build | Sonnet | 80 | docs, content, notes, scripts, config text |
| builder-frontend | build | Sonnet | 80 | UI code (screens, components, styles, a11y, RTL) |
| builder-backend | build | Sonnet | 80 | services, APIs, data, integrations, migrations |
| builder-ops | build | Sonnet | 80 | CI, build, launchd, Docker, deploy config |
| verifier | test | Sonnet | 60 | after every build: runs the real tests, PASS/FAIL |
| reviewer | review | Opus | 40 | every material change; the caller names the lens: correctness or risk |
| designer | design | Sonnet | 40 | UI spec and states before UI is built |
| reporter | report | Haiku | 5 | report queue only (in the agent files, not in the stage table; it joins the flow in P5) |

## This project's team table
`docs/SKILLS.md` has a Team section: a table between `<!-- team:begin -->` and `<!-- team:end -->` with the columns Role, Agent, Skills and Why. It records, on purpose, which agent does which job in THIS project. The lead fills it after scoping and planning (or the owner does); agents never edit it.
- Add a member: `shipm team add AGENT --role build --why "API and data work" [--skills a,b] [PROJECT]`. The agent must exist for this project (a master role, an old role name, a project or user agent file, or `plugin:name`); an old name is stored as its new name; a duplicate is refused. A chat can add only to its own project. There is no remove command: the lead edits the table by hand.
- Show it: `shipm team show [PROJECT]`. Check it: `shipm team check [PROJECT]` (exit 0 clean, 1 problems, 3 warnings only; as everywhere in `shipm`, an unknown project is exit 3 too, told apart by the `shipm: no project ...` line on stderr; a damaged table is exit 1 for `show` as well). `add` takes turns with other `add` runs on the same project (a lock outside the project), refuses a full table (40 rows), empty or blank role, why or skill names, and a `docs` folder that is a symbolic link; a skill that is not installed is allowed with a warning. Marker lines inside a fenced code block are examples, not the table. It looks for: a table at all, every agent resolving, one member with the test role and one with the review role, the Role cell matching the agent's real role (warning), and every listed skill being installed.
- `shipm skills view --write` regenerates the rest of the file and copies the Team block forward exactly as written. A block that is damaged (two blocks, a missing marker), larger than 16 KB, or a file that is a symbolic link or larger than 64 KB stops the regeneration with a message; nothing is overwritten.
- The flow gate follows the table: once it has at least one row, a build agent that is not on the team is refused at its first write (the message says how to add it), and a review verdict from an agent that is not on the team is not counted. Verifier and reviewer always count; the project's flow level decides (strict refuses, warn only notes, off does nothing); "just do it" lifts it for that turn. Subagents may not edit the table or the borrow record (nor run `shipm team add`, change the docs or .agents folders, or use git to rewrite them): the lead or the owner does. This is a discipline gate that stops the known ways, not a boundary against a command spelled in a way the gate cannot follow. A project without a table behaves as before (one reminder per session); a table that was fine and is now broken lets only the master agents work until it is repaired.

## Borrowing from a reference catalog (when the machine has one)
Some machines keep a pinned, read-only reference catalog of other people's agents and skills (`reference/<name>.lock`, `reference/<name>.index.json` and a read-only copy). It is untrusted third-party text: the lead reads it as a reference and writes OUR OWN, improved version under the rules of this page (pinned model, role tool whitelist, `Model reason:` and `Flow role:` lines, the definition-of-done block, no instructions to install, reach the network or add hooks). Nothing is copied in as it is. Only agents and skills can be borrowed (not commands).
- `shipm borrow show <catalog>:<kind>:<name>`: checks that the catalog is exactly what was pinned (index against lock, source file against index; a mismatch is refused with "catalog changed since it was pinned"), runs a read-only safety scan and prints a REFERENCE view: where it came from (tag, commit), its license line, size, risk flags, whether the catalog lists it among its riskiest items, then the text with control characters shown as `<U+XXXX>` and flagged lines marked `!`. The scan refuses (no override) a symbolic link on the path, a file that is not plain text of an allowed type (.md .txt .json .yaml .yml), more than 64 KB per file or 256 KB and 20 files per skill, and any control, zero-width or bidirectional character. Flags are warnings for the lead: runs code, network, hooks, touches config, telemetry, injection phrases, install commands, sudo, `rm -rf`, `curl | sh`. Exit 0 shown, 4 refused by the scan or the integrity check, 2 not borrowable (a command or an unknown kind), 3 not found. `show` writes nothing anywhere.
- `shipm borrow record <id> --reason TEXT --as NAME [--dest PATH] [--project P]`: after you wrote your own file (`.claude/agents/NAME.md` or `.agents/skills/NAME/`), record where the idea came from. Refused when the file does not exist inside the project, sits behind a symbolic link, equals the source, repeats more than 70% of its lines, or shares more than half of its wording with it (compared on 5-word runs, ignoring case, punctuation, bullets and line breaks; our own front matter, `Model reason:`, `Flow role:` and DoD blocks are left out of the comparison), or when the item is already recorded. It appends to `.agents/borrowed.json` (committed; at most 200 entries) and, first, to an owner-side log outside the project (the new record is staged first, then the log line is written, then the record becomes visible; if that last step fails the log line is voided). The entry is bound to the project's real path, so a record copied or moved to another project is flagged by `team check`. A chat can record only in its own project.
- `shipm borrow list [PROJECT]`: the recorded items, marking "ours changed since recorded".
- `shipm team check` also reads the record: a record that does not parse, or a dest that is gone, is a problem (exit 1); an entry with no matching owner-side log line ("record not made by shipm borrow on this machine") or a borrowed agent missing from the Team table is a warning.
- Without a catalog every `borrow` command that needs one prints: "No reference catalog on this machine; borrowing is not available. Write the project agent or skill by hand (docs/standards/team.md); the team check still applies." and exits 3. Writing the agent or skill by hand is always allowed; the team check applies either way.

## Old names (aliases)
Old role names still resolve as aliases (one release; P3b replaced the earlier "use the installed old file names" line because the new agent files now ship and the old ones are deleted): product-analyst = scoper, solution-architect = planner, frontend-engineer = builder-frontend, backend-engineer and data-integration-engineer = builder-backend, devops-sre = builder-ops, qa-engineer = verifier, independent-reviewer = reviewer (lens correctness), security-reviewer = reviewer (lens risk), ux-designer = designer. engineering-lead is retired: the main chat routes.

## Plan mode and approval details
- Start a plan in plan mode (Shift+Tab or `EnterPlanMode`). The owner never switches models: `opusplan` plans on Opus and builds on Sonnet by itself.
- The plan tool's own "approved" answer does not count: auto mode and some chats answer it by themselves. A global hook blocks Edit and Write until the owner approves in the chat.
- Plan mode is DISCUSS/PLAN; normal chat is BUILD only after the owner says so.
- Hooks in `.claude/settings.json` run the formatter after edits and the tests when you stop; read their output and act on failures before reporting.

## Choosing the smallest team
- bug: builder + verifier
- feature: scoper + planner + builder + verifier
- UI: designer + builder-frontend + verifier
- security-sensitive: builder + reviewer (risk lens) + verifier
- release: planner + builders + verifier + reviewer (risk lens)
The author of a material change is never its only reviewer: the reviewer, or the tool's own review command (`/code-review`, `/security-review`), runs on it. Reviewers are read-only.

## Who leads each stage
Enforced by the flow gate hook; the level per project is in the workspace's `config/flow.json`. The plan stage may also be led by a project agent with `Flow role: plan`; the build stage by the agent for the area (`Flow role: build`); the test stage by the agent with `Flow role: test`.
Rules: a plan is presented only after the plan-role agent wrote it; source files are changed by agents (the main chat edits records and at most one small fix of <= 10 lines per turn); a build ends only after the test-role agent ran. "just do it" from the owner lifts this for one turn (logged). Use `/feature <what>` to run the whole flow. The session brief is injected automatically at start (STATUS, memory, commits).

## Choosing an agent's model (every agent, master or project-only, decided once and written in its file)
- **opus**: decides or judges (design, plans, review, security, unclear research); mostly reads; a wrong answer is costly.
- **sonnet**: produces (code, tests, following a written plan, volume work). When unsure, sonnet (Opus uses the Max limit faster).
- **haiku**: mechanical lookups or formatting only, no judgement.
Each agent file has `model:` set to opus, sonnet or haiku (never `inherit`) and, as the first lines after the header, `Model reason: <one line>` and `Flow role: plan | build | test | review | scope | design | route | support | report`. `bin/doctor` warns on a file that breaks this; `promote-agent` refuses it.

## Models and quota
Automatic; the owner does not switch models by hand:
- Claude default `opusplan`: Opus in plan mode, Sonnet once the plan is approved and building starts. A chat's model picker overrides it; the panel's model line shows the model in use; `/model opusplan` restores it.
- Roles pin their own model (`model:` in the agent file): planner and reviewer on Opus; builders, verifier, scoper, designer on Sonnet.
- Every switch is logged to `docs/memory/model-log.md`; STATUS cites it instead of guessing.
- Every plan starts with one line naming the model that did the thinking ("Planning model: Opus" or "Planning model: Sonnet - design made by an Opus agent"), so the owner never has to guess.
- If your own model is not Opus, do the design with the planner agent (`model: opus`) and say so.

## Inviting a new agent
A role this project needs that the team lacks: create `.claude/agents/<name>.md` in this project (project-only). Promotion to the master team is the owner's call (Promote agent button); never copy it into the workspace yourself. A project agent follows the same model rule and ends with the Definition-of-done block.

## Web checks, QA and review snapshots (settings isolation, 21 Oct 2026)
- Web checks use `agent-browser` with the flags `--use-mock-keychain,--password-store=basic` (the env block already sets `AGENT_BROWSER_ARGS` to exactly that) and always end with `agent-browser close --all`. A Chrome you start yourself gets the same two flags and is killed with its whole process group when you are done; never leave a browser running.
- Every command a QA or review run executes that can reach Shipmiracle, a hook or a browser carries the FULL isolation set with fresh folders: `SHIPMIRACLE_TEST=1 SHIPMIRACLE_HOME SHIPMIRACLE_CONFIG SHIPMIRACLE_STATE SHIPMIRACLE_WS SHIPMIRACLE_DEV HOME CLAUDE_CONFIG_DIR` (HOME alone is not enough: Shipmiracle's home ignores `$HOME`). Never touch the real `~/.claude/settings.json`; read-only fingerprints before and after are the evidence.
- A temporary snapshot of the real repository for QA or review goes to `~/Developer/.worktrees/<project>/snap-<tag>`, never to `/tmp` or `/private/tmp`. Remove it when done with `git worktree remove --force <path>` followed by `git worktree prune`. (The repo's own tools and tests that create worktrees stay inside their fully temporary sandboxes; this rule is for agent-created snapshots of the real repo.) `bin/doctor` shows a `stale worktree records` row for dangling records, detached snapshots older than 24 h and any worktree under a temp folder; its fix is `git worktree prune`, which only forgets dangling records and never deletes a folder.

## Side questions: `/btw`, subagents, and the Ask inbox (21 Oct 2026)
- `/btw <question>` asks a side question while a response is running: it adds nothing to the conversation history, has no tool access and gives one answer (VS Code extension 2.1.227 or later, and the desktop Code tab). Use it for quick tool-less questions so the running work is not interrupted or polluted.
- Anything that needs files, commands or the web is not a `/btw` question: hand it to a subagent (or fork the chat) so the main context stays clean.
- The project card's "Ask aside" button only prefills `/btw ` in that project's chat terminal without pressing Enter; you type the question. It starts nothing by itself.
- Questions that belong to no project use the Ask inbox: `shipm ask --inbox "question"` (a headless answer without tools, written as one dated note in the optional `ask` project; set up with `shipm init --step ask-inbox`). The answer is marked not verified; a question that turns into work is promoted with `shipm ask promote <note>` (an idea in the Inbox), never straight into a change request.
