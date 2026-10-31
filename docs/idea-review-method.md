# Idea review method — is this idea worth building, and as what?

Used when the owner asks "is F3 worth it?" or presses Review / Worth it? in the Shipmiracle panel. Run it in **plan mode** (Opus plans), as the product-analyst
and then the solution-architect would: read the repo before scoring, cite what you found, never guess silently. One page per idea. **Do not write to FEATURE-IDEAS.md,
DECISIONS.md or any source until the owner approves the result.** Nothing is built from a idea list item without an approved plan.

## 1. The page, per idea
1. **Problem** — who has it, how often, what they do today (the workaround). One or two sentences.
2. **Value 1-5** — 1 = nice to have, 3 = saves real time or avoids a recurring annoyance, 5 = removes a blocker or a real risk.
   Cite evidence from the repo (docs/STATUS.md, docs/DECISIONS.md, CI history, TODOs, past chat decisions). **Confidence**: 0.5 guessed, 0.8 partly backed by evidence, 1.0 proven.
3. **Effort** — S = 1 (hours, a few files), M = 2 (a day or two, one area), L = 4 (several days or several areas). Name the files or modules it touches.
4. **Risk 0-2** — add 1 each for: security or privacy impact, possible data loss or an irreversible action. 0 = none.
5. **Score = Value × Confidence ÷ Effort − 0.5 × Risk.** Show the numbers.
6. **Fit test** — answer yes/no: (a) same users as the project today? (b) same stack and data? (c) same release cycle and deploy? (d) effort M or smaller?
   **3 or more yes = FEATURE of this project. 1 or fewer = NEW PROJECT.** Two yes = FEATURE, but say what makes it awkward.
7. **Alternatives** — do nothing; an existing tool, skill or plugin that already covers most of it; a smaller first version (what is the one-day slice?).
8. **Overlap** — run `shipm idea index` and read the "Likely overlaps". For each pair involving this idea, decide: same problem and same user → confirm,
   otherwise reject with a reason.

## 2. The recommendation (the last part of every page)
End the page with one short **Recommendation** that answers three things, in this order:
1. **Where does it belong?** This project, another existing project (which, and why), a new project (name and type), or merged with other ideas (which).
2. **Is it worth building?** Yes now / yes later / no, with the score and the one reason that matters most.
3. **Next step.** Exactly what the owner can do next (build it here with a plan, move it, create the project, merge, drop).

## 3. The verdict (pick exactly one)
| Verdict | When |
|---|---|
| **BUILD NOW** | score ≥ 2 and nothing blocks it. Ends with a normal plan: steps, files, acceptance criteria, verification. |
| **BUILD LATER** | score between 0.75 and 2, or blocked by something named ("after F5", "needs the gate project finished"). |
| **MERGE with <ids>** | a confirmed overlap: the ideas are one bigger idea. Say what the combined idea is and re-score it as one. |
| **MOVE to <project>** | the idea fits another existing project better (same users, same stack or data). Name the project; the panel then offers "Move to <project>". |
| **SPLIT OUT** | fit test says NEW PROJECT. Propose a project name and type (`bin/new-project`), seed it in the `ideas` project first. |
| **DROP** | score under 0.75, or an alternative already covers it. Say which. |

## 4. Making an idea bigger (merging across projects)
- Copying an idea to another project is allowed at any time (the original stays); use it when the same idea helps two projects.
- Confirmed overlaps are written to `<projects folder>/ideas/ideas/theme-<slug>.md` (config `paths.projects_dir`, default `~/Developer`) (keep the existing idea-file layout of that folder): the combined problem, the items it absorbs
  (project/id each), and the combined score.
- **Offer a NEW PROJECT** when a theme has **3 or more items from 2 or more projects** (or a combined score of 6 or more) **and** it fails the fit test for every existing project.
  Then the `ideas` project's "turn an idea into a project" step runs `bin/new-project`. The owner approves every time.

## 5. After the owner approves
- `shipm idea verdict F3 "BUILD LATER · score 2.4 · reason"` (moves it to Evaluated). Merged items: give each the verdict "MERGED into <theme>".
- Add a dated entry to `docs/DECISIONS.md`: the verdict, the score and the one-line reason.
- BUILD NOW: the plan is the next deliverable, in plan mode; building starts only after the owner approves it.
- Say plainly what you could not verify (value is often an estimate). Never present a guess as evidence.
