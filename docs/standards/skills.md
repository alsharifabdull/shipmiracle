# Skills (on demand)

- Global skills (every project) are listed in `skills/APPROVED.md` in the Shipmiracle engine folder; they are installed and updated daily.
- Each project keeps `docs/SKILLS.md`: its review date and the extra skills each agent uses. On the first session of a project (the session brief says so) the lead runs the skills review, proposes skills per agent, and installs only what the owner approves, in the project (`npx skills add <package> --skill <name> -y`, never `-g`). Repeat when the stack or scope changes.
- To look for a skill on a topic run `npx skills find <topic>` (this replaces the old find-skills skill); read the skill's SKILL.md before proposing it.
- Every agent: before starting, check `docs/SKILLS.md` for the skills listed for your role and use them.
- Borrowing from a reference catalog (when the machine has one) means the lead reads an item and writes our own improved version under our rules; nothing is copied in as it is, and the master team and global skills never change automatically.
- The Team table in `docs/SKILLS.md` (between `<!-- team:begin -->` and `<!-- team:end -->`) lists the agents chosen for this project, with the skills each one uses and why. The lead fills it after scoping and planning with `shipm team add`, and `shipm team check` verifies it; `shipm skills view --write` keeps it exactly as written. Details: `docs/standards/team.md`.
