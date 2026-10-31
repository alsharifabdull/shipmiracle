#!/usr/bin/env bash
# shipm-state <working|needs-input|done>: tell the VS Code status bar what this project's Claude session is doing.
# Writes ~/.local/state/shipmiracle/<project>.json; the shipmiracle-panel extension reads it. Never blocks, never fails a session.
state="${1:-working}"
dir="${CLAUDE_PROJECT_DIR:-$PWD}"; name=$(basename "$dir")
# only real projects (a folder directly under ~/Developer) get a state file; build clones and temp folders do not
[[ "$(cd "$(dirname "$dir")" 2>/dev/null && pwd -P)" == "$(cd "$HOME/Developer" 2>/dev/null && pwd -P)" ]] || exit 0
input=$(cat 2>/dev/null)
msg=$(printf '%s' "$input" | python3 -c 'import json,sys
try: print(str(json.load(sys.stdin).get("message",""))[:140])
except Exception: pass' 2>/dev/null)
# Claude Code also sends a Notification about a minute after it finished a reply ("Claude is waiting for your input").
# That is not a question: keep the state (done) instead of flagging "Needs you".
if [[ "$state" == "needs-input" ]]; then
  ntype=$(printf '%s' "$input" | python3 -c 'import json,sys
try: print(json.load(sys.stdin).get("notification_type",""))
except Exception: pass' 2>/dev/null)
  if [[ "$ntype" == "idle_prompt" || "$ntype" == "auth_success" || "$msg" == *"waiting for your input"* ]]; then exit 0; fi
fi
out="$HOME/.local/state/shipmiracle"; mkdir -p "$out" 2>/dev/null || exit 0
python3 - "$out/$name.json" "$name" "$state" "$msg" "$dir" <<'P' 2>/dev/null
import json,sys,time
f,name,state,msg,path=sys.argv[1:6]
json.dump({"project":name,"path":path,"state":state,"message":msg,"ts":int(time.time())},open(f,"w"))
P
exit 0
