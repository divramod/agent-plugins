#!/usr/bin/env bash
# Refuse a landing in a former subservant slot (skills plan 0013; subservant
# sessions are gone since plan 0016, the guard stays while a slot holds one, plan
# 0015 D12): the worktree holds plans/LEAD (`<lead-slot> <plan> <step>`).
# Usage: subservant-guard.sh [<dir>|<slot>]   (default: the current directory)
#   <dir>  any directory inside the worktree to check;
#   <slot> a worktree's name when no such directory exists here (31, main, a named
#          slot such as farmer-hal2): resolved through `hal2-cli-git worktree list
#          --json` of the current repo, else by folder name through `git worktree
#          list --porcelain` (`main`: the main checkout).
# Exit 1 naming the lead there, 0 silently elsewhere; 2 when git is missing;
# 3 when <slot> names no worktree of the current repo.
set -euo pipefail
command -v git >/dev/null 2>&1 || { echo "subservant-guard.sh: git is missing: run install-prerequisites.sh" >&2; exit 2; }
arg="${1:-.}"
if [ -d "$arg" ]; then
  dir="$arg"
else
  dir=""
  if command -v hal2-cli-git >/dev/null 2>&1 && command -v python3 >/dev/null 2>&1; then
    dir=$(hal2-cli-git worktree list --json 2>/dev/null | python3 -c '
import json, sys
name = sys.argv[1]
for w in json.load(sys.stdin).get("worktrees", []):
    if w.get("name") == name:
        print(w.get("path", ""))
        break
' "$arg" 2>/dev/null || true)
  fi
  if [ -z "$dir" ]; then
    dir=$(git worktree list --porcelain 2>/dev/null \
      | awk -v name="$arg" 'sub(/^worktree /, "") { first++; n = split($0, p, "/")
          if (p[n] "" == name "" || (first == 1 && name == "main")) { print; exit } }')
  fi
  [ -n "$dir" ] || { echo "subservant-guard.sh: no directory and no worktree of this repo named '$arg'" >&2; exit 3; }
fi
root=$(git -C "$dir" rev-parse --show-toplevel 2>/dev/null || echo "$dir")
marker="$root/plans/LEAD"
[ -f "$marker" ] || exit 0
read -r lead plan step _ < "$marker" || true
echo "mtm: this slot is a subservant of slot ${lead:-?} (plan ${plan:-?} step ${step:-?}, plans/LEAD): it never lands." >&2
echo "It holds a stale plans/LEAD of the lead in slot ${lead:-?}: the lead takes the work over, or delete plans/LEAD." >&2
exit 1
