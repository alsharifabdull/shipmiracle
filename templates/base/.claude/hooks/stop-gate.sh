#!/usr/bin/env bash
# Stop gate: Claude may not call the turn done while source changed and the record is stale.
# 1) tests (from .claude/test-command) must pass; 2) docs/STATUS.md must carry today's date in its
# "Updated:" line and be newer than the newest changed source file. Exit 2 = blocked with a message.
cd "${CLAUDE_PROJECT_DIR:-.}" 2>/dev/null || exit 0
input=$(cat)
printf '%s' "$input" | grep -q '"stop_hook_active": *true' && exit 0      # we already asked once this turn
[[ -d .git ]] || exit 0

# changed files since HEAD, excluding the record itself and memory/plans
changed=$( { git diff --name-only HEAD; git ls-files --others --exclude-standard; } 2>/dev/null | grep -viE '^docs/(STATUS\.md|DECISIONS\.md|FEATURE-IDEAS\.md|memory/|plans/)' | grep -vE '^(\.claude/|\.agents/|\.vscode/|\.github/|\.githooks/|\.editorconfig$|\.gitignore$)' )
[[ -n "$changed" ]] || exit 0

# 1) tests
if [[ -f .claude/test-command ]]; then
  cmd=$(cat .claude/test-command)
  out=$(bash -lc "$cmd" 2>&1 | tail -30); status=${PIPESTATUS[0]}
  if [[ $status -ne 0 ]]; then
    printf 'Stop blocked: tests failed (`%s`). Fix them, then update docs/STATUS.md.\n%s\n' "$cmd" "$out" >&2; exit 2
  fi
fi

# 2) STATUS freshness
today=$(date +%Y-%m-%d)
if [[ ! -f docs/STATUS.md ]]; then echo "Stop blocked: docs/STATUS.md is missing. Create it (what changed, how verified, next, handoff)." >&2; exit 2; fi
if ! grep -qE "^Updated: *$today" docs/STATUS.md; then
  echo "Stop blocked: source files changed but docs/STATUS.md is not updated for today. Set its first 'Updated:' line to '$today · by: <engine/model> · mode: <mode>', record what changed, the exact verification, what is next and the handoff. Then stop again." >&2; exit 2
fi
# mtime in seconds since the epoch, same on macOS (BSD) and Linux (GNU): `date -r FILE +%s` (BSD `stat -f %m` means something else on GNU)
mtime() { date -r "$1" +%s 2>/dev/null; }
newest=$(printf '%s\n' "$changed" | while read -r f; do [[ -f "$f" ]] && mtime "$f"; done | sort -n | tail -1)
st=$(mtime docs/STATUS.md)
if [[ -n "$newest" && "$st" -lt "$newest" ]]; then
  echo "Stop blocked: docs/STATUS.md is older than the latest source change. Re-read it, update what changed/verified/next/handoff, save it, then stop again." >&2; exit 2
fi

# 3) record which Claude session did the work (handoff line), silently
sid=$(printf '%s' "$input" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("session_id",""))' 2>/dev/null)
if [[ -n "$sid" ]]; then
  line="- Last Claude session: $sid ($today). Resume: /resume in VS Code, or claude --resume $sid"
  if grep -q '^- Last Claude session:' docs/STATUS.md; then
    python3 - "$line" <<'PY'
import re,sys,pathlib
p=pathlib.Path("docs/STATUS.md"); t=p.read_text()
t=re.sub(r"^- Last Claude session:.*$", sys.argv[1], t, count=1, flags=re.M); p.write_text(t)
PY
  elif grep -q '^## Handoff' docs/STATUS.md; then
    python3 - "$line" <<'PY'
import sys,pathlib
p=pathlib.Path("docs/STATUS.md"); t=p.read_text()
t=t.replace("## Handoff\n", "## Handoff\n"+sys.argv[1]+"\n", 1); p.write_text(t)
PY
  fi
fi
exit 0
