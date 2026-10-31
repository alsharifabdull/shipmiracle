#!/usr/bin/env bash
# PostToolUse(Edit|Write): format the edited file with whatever formatter the project has.
input=$(cat)
file=$(printf '%s' "$input" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_input",{}).get("file_path",""))' 2>/dev/null)
[[ -f "$file" ]] || exit 0
cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0
case "$file" in
  *.swift)       command -v swiftformat >/dev/null && swiftformat --quiet "$file" ;;
  *.ts|*.tsx|*.js|*.jsx|*.json|*.css|*.md)
                 [[ -f node_modules/.bin/prettier ]] && node_modules/.bin/prettier --log-level silent --write "$file" ;;
  *.py)          command -v ruff >/dev/null && ruff format --quiet "$file" ;;
esac
exit 0
