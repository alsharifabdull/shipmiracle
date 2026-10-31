#!/usr/bin/env bash
# PostToolUse(ExitPlanMode): keep the approved plan in the repo, so cloud sessions and the
# owner can read it later. Copies the newest plan file from ~/.claude/plans into docs/plans/.
cd "${CLAUDE_PROJECT_DIR:-.}" 2>/dev/null || exit 0
src=$(ls -t "$HOME"/.claude/plans/*.md 2>/dev/null | head -1); [[ -f "$src" ]] || exit 0
# only plans touched in the last 2 hours belong to this session
# mtime in seconds since the epoch, same on macOS (BSD) and Linux (GNU): `date -r FILE +%s` (BSD `stat -f %m` means something else on GNU)
mtime() { date -r "$1" +%s 2>/dev/null; }
[[ $(( $(date +%s) - $(mtime "$src") )) -lt 7200 ]] || exit 0
mkdir -p docs/plans
slug=$(basename "$src" .md | sed -E 's/-[a-z]+-[a-z]+$//'); slug=${slug:0:50}   # characters, not bytes (GNU cut -c counts bytes and would cut an Arabic title in the middle of a letter)
dst="docs/plans/$(date +%Y-%m-%d)-$slug.md"
cmp -s "$src" "$dst" 2>/dev/null || { cp "$src" "$dst"; echo "Plan saved to $dst (commit it with the work)."; }
exit 0
