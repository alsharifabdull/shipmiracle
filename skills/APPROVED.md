# Approved skills

Skills are pinned by commit: `skills/skills.lock.json` holds `{skill: {pkg, commit, tree_sha256}}` and the line below repeats the commit.
Nothing updates by itself: `bin/skills-sync` installs the pinned ref (git clone + checkout + copy) and never updates. Entries marked
`unpinned` have no commit recorded yet: `bin/skills-sync --pin --online` resolves them.
Project-only skills go in that project's `.agents/skills/`.

Line format (the only lines the tools read): `- pkg@<commit> | skill | why | packs`
Packs: `global` = installed for the user (every project); `web`, `ios`, `content`... = installed per project from source, never `-g`.
Add a line only after you have read the skill's SKILL.md and decided you want it.

## Approved

### Planning pack (global)
- mattpocock/skills@unpinned | grill-me | pressure-test a plan one question at a time until every branch is decided | global,planning
- mattpocock/skills@unpinned | grill-with-docs | the same, checked against the live code, writes ADRs and glossary as it goes | global,planning
- mattpocock/skills@unpinned | prototype | try business logic or state transitions before committing to a build | global,planning
- mattpocock/skills@unpinned | domain-modeling | project glossary and architecture decision records | global,planning
- mattpocock/skills@unpinned | handoff | compress a long session into a handoff the next agent can pick up | global,planning

### Engineering pack (global)
- mattpocock/skills@unpinned | tdd | strict red-green-refactor for features and bug fixes | global,engineering
- mattpocock/skills@unpinned | diagnosing-bugs | root-cause loop for hard bugs and slow code | global,engineering
- mattpocock/skills@unpinned | improve-codebase-architecture | deepen shallow modules into testable units safely | global,engineering
- mattpocock/skills@unpinned | codebase-design | shared vocabulary for module interfaces and seams | global,engineering
- mattpocock/skills@unpinned | triage | move issues and PRs through verify, brief, ready | global,engineering

### Web pack (per project, not global): web projects only
- vercel-labs/agent-browser@unpinned | agent-browser | agents drive a real browser to test and QA web apps | web
- vercel-labs/agent-skills@unpinned | vercel-react-best-practices | React and Next.js performance rules while writing and reviewing | web
- vercel-labs/agent-skills@unpinned | vercel-composition-patterns | React component architecture that scales | web
- pbakaus/impeccable@unpinned | impeccable | design, critique, polish, animate and audit frontend UI | web,design
