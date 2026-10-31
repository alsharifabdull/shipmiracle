#!/usr/bin/env bash
# PreModelSwitch: log every model change into docs/memory/model-log.md so STATUS can say which
# model did what without anyone typing it. Never blocks.
cd "${CLAUDE_PROJECT_DIR:-.}" 2>/dev/null || exit 0
input=$(cat)
line=$(printf '%s' "$input" | python3 -c '
import json,sys
try: d=json.load(sys.stdin)
except Exception: sys.exit(0)
keys=[k for k in d if "model" in k.lower()]
parts=[f"{k}={d[k]}" for k in keys] or ["(no model fields)"]
print(" ".join(parts), "session="+str(d.get("session_id",""))[:8])' 2>/dev/null)
[[ -n "$line" ]] || exit 0
mkdir -p docs/memory
[[ -f docs/memory/model-log.md ]] || printf '# Model log (auto)\n\nEvery model switch in this project, newest last.\n\n' > docs/memory/model-log.md
printf -- '- %s %s\n' "$(date '+%Y-%m-%d %H:%M')" "$line" >> docs/memory/model-log.md
exit 0
