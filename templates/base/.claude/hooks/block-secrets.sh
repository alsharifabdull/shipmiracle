#!/usr/bin/env bash
# PreToolUse(Bash): refuse a git commit/push that stages a secret-looking value.
# Exit 2 blocks the tool call and shows the message to Claude.
input=$(cat)
cmd=$(printf '%s' "$input" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_input",{}).get("command",""))' 2>/dev/null)
case "$cmd" in
  *"git commit"*|*"git push"*) ;;
  *) exit 0 ;;
esac
cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0
staged=$(git diff --cached -U0 2>/dev/null | grep '^+' | grep -v '^+++')
pattern='(sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{36}|xox[baprs]-[A-Za-z0-9-]{10,}|-----BEGIN [A-Z ]*PRIVATE KEY-----|(api[_-]?key|secret|token|password)\s*[:=]\s*["'"'"'][^"'"'"']{8,})'
if printf '%s' "$staged" | grep -Eiq "$pattern"; then
  echo "Blocked: staged changes contain something that looks like a secret. Move it to .env and retry." >&2
  exit 2
fi
if git diff --cached --name-only 2>/dev/null | grep -Eq '(^|/)\.env($|\.)' ; then
  if ! git diff --cached --name-only | grep -Eq '\.env\.example$'; then
    echo "Blocked: a .env file is staged. Unstage it (git restore --staged .env)." >&2
    exit 2
  fi
fi
exit 0
