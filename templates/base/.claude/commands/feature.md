---
description: Open a change request (CR) and run it through this project's playbook: scope, plan (Opus), your OK, build, test, review, deliver
argument-hint: <what to change>   (no text = resume the active CR)
---
Request: $ARGUMENTS

1. Run `shipm cr open -` with the request on stdin in a QUOTED heredoc: `<<'SHIPMIRACLE_REQ'`, then the request in one line, then `SHIPMIRACLE_REQ` on its own line (never put the request text on the command line or inside double quotes: quotes, `$(...)` and backticks in it would be run by the shell). No request text: run `shipm cr show` instead. It prints the CR id, its lane and the next step. If another CR is active, the new one is queued and an impact-check step is printed: do it.
2. Loop: run `shipm cr show --next` and do exactly the step it names with the agent it names (Agent tool, that subagent_type; brief = CR title, acceptance criteria, the printed checks, pointers to docs/STATUS.md and docs/DECISIONS.md). Hooks record every stage. Never edit .shipmiracle/ files and never mark a stage yourself.
3. Plan: present the planner's plan with EnterPlanMode/ExitPlanMode (deferred tools: ToolSearch `select:EnterPlanMode,ExitPlanMode`). First line: `Planning model: Opus (planner agent). This chat runs <your model>.` Print it in plain language, then STOP until the owner writes approval in the chat.
4. Stop and ask the owner whenever `--next` says "waiting on owner" (plan approval, tests failed twice, manual autopilot). Otherwise keep going until the CR is delivered.
5. Exception: one small fix (one file, at most 10 lines) in the main chat, as before.
6. Finish: commit "CR-NNN: what + why", update docs/STATUS.md (dated today), and report the CR result as `shipm cr show` prints it.
