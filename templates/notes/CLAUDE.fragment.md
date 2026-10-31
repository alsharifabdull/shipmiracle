## Stack rules — Notes / ideas (no code lives here)
- This repository holds ideas, discussions and plans only. Modes allowed: DISCUSS, RESEARCH, PLAN.
  Never create source code here; if the owner asks to build, say the idea must become a project first.
- One file per idea: `ideas/<slug>.md` with sections: Problem · Who has it · Options considered ·
  Recommendation · Requirements (numbered, testable) · Open questions · Status (idea / planned / became project <name> / dropped).
- Keep each idea file current as the discussion evolves; do not create a second file for the same idea.
- When the owner says **"turn <idea> into a project"**:
  1. Confirm the project name (lowercase slug) and type (ios / web / python / home).
  2. Run `new-project <name> --type <type> --no-open` (in the `bin/` folder of the Shipmiracle engine).
  3. Copy the idea's Problem, Requirements and Recommendation into the new project's `docs/STATUS.md`
     ("Next" = first implementation tasks with acceptance criteria) and the Recommendation + rejected
     options into its `docs/DECISIONS.md`; fill the Project section of its `CLAUDE.md`.
  4. Commit and push the new project; set the idea's Status to "became project <name>" and commit here.
  5. Tell the owner to open the new project from the Projects sidebar; nothing else is needed.
