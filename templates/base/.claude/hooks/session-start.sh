#!/usr/bin/env bash
# SessionStart: put the project's current state in front of Claude before the first prompt.
# Everything printed to stdout becomes context. Keep it short: STATUS head, memory, recent commits, dirt.
cd "${CLAUDE_PROJECT_DIR:-.}" 2>/dev/null || exit 0
echo "=== PROJECT BRIEF (auto, $(date +%Y-%m-%d)) — read before anything else ==="
if [[ -f docs/STATUS.md ]]; then echo "--- docs/STATUS.md (brief; full file: docs/STATUS.md)"; { python3 "@SHIPMIRACLE_ENGINE@/bin/status-extract" "$PWD" 2>/dev/null || sed -n 1,120p docs/STATUS.md; }; else echo "docs/STATUS.md missing: create it from the template before working."; fi
if [[ -f docs/FEATURE-IDEAS.md ]]; then
  open=$(awk '/^## Open/{f=1;next} /^## /{f=0} f && /^- \[ \]/' docs/FEATURE-IDEAS.md); n=$(printf '%s' "$open" | grep -c . )
  if [[ "$n" -gt 0 ]]; then echo; echo "--- feature ideas: $n open idea(s) in docs/FEATURE-IDEAS.md (top 3; add: shipm idea add \"idea\"; review method: docs/idea-review-method.md in the Shipmiracle engine folder)"; printf '%s\n' "$open" | head -3; fi
fi
[[ -f docs/memory/MEMORY.md ]] && { echo; echo "--- docs/memory/MEMORY.md (project memory index)"; sed -n 1,60p docs/memory/MEMORY.md; }
if [[ -d .git ]]; then
  echo; echo "--- last 10 commits"; git log --oneline -10 2>/dev/null
  echo; echo "--- uncommitted changes"; git status --short 2>/dev/null | head -30
  [[ -f .git/PUSH-FAILED ]] && echo "WARNING: last auto-push failed ($(cat .git/PUSH-FAILED)); run: git push"
  b=$(git branch --show-current 2>/dev/null); ahead=$(git rev-list --count '@{u}..HEAD' 2>/dev/null || echo 0)
  echo "branch: $b, commits not on GitHub: $ahead"
fi
# skills check: first session of a project (or after the owner resets it) reviews the skills each agent needs
sk=docs/SKILLS.md
if [[ ! -f "$sk" ]] || grep -qiE '^Skills review: *not done' "$sk"; then
  echo; echo ">>> FIRST TASK THIS SESSION: the project skills review has not been done. Before other work, follow"
  echo "    docs/SKILLS.md 'How the review works' (create it from templates/base/docs/SKILLS.md in the Shipmiracle engine folder if missing):"
  echo "    the lead runs `npx skills find <topic>` and proposes the skills each role needs, asks the owner once, installs only what is approved."
elif [[ -n "$(find "$sk" -mtime +90 2>/dev/null)" ]]; then
  echo; echo "Note: docs/SKILLS.md was last reviewed over 90 days ago; offer the owner a skills re-check."
else
  echo; echo "--- project skills (docs/SKILLS.md)"; grep -E '^\|' "$sk" | sed -n 3,20p
fi
echo; echo "Rules in force: update docs/STATUS.md (Updated: line with today's date) before stopping when source changed; one engine edits at a time; commit = push (auto)."
echo "To continue an earlier conversation: /resume (VS Code) or claude --continue (terminal)."
exit 0
