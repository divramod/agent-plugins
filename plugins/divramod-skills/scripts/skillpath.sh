#!/usr/bin/env bash
# Find a sibling skill from a script of another skill, flat or in a category (plan 0360, D20). bash 3.2.
#
#   here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
#   u="$here"; until [ -d "$u/.claude-plugin" ] || [ "$u" = / ]; do u="$(dirname "$u")"; done
#   . "$u/scripts/skillpath.sh"
#   planpy="$(skill_dir plan "$here")/scripts/plan.py"
#
# skill_dir <name> [start]: the calling skill's parent folder first, then <skills root>/*/<name>, then
# <skills root>/<name>; a folder counts when it holds SKILL.md. Prints the path; exit 1 naming the skill if none.

skill_unit_root() {
  local d
  d="$(cd "$1" 2>/dev/null && pwd -P)" || return 1
  while [ "$d" != "/" ]; do
    [ -d "$d/.claude-plugin" ] && { printf '%s\n' "$d"; return 0; }
    d="$(dirname "$d")"
  done
  return 1
}

skill_dir() {
  local name="$1" start="${2:-$(cd "$(dirname "${BASH_SOURCE[1]:-$0}")" && pwd -P)}" d own root c
  d="$start"
  own=""
  while [ "$d" != "/" ]; do
    [ -f "$d/SKILL.md" ] && { own="$d"; break; }
    d="$(dirname "$d")"
  done
  if [ -n "$own" ] && [ -f "$(dirname "$own")/$name/SKILL.md" ]; then
    printf '%s\n' "$(dirname "$own")/$name"; return 0
  fi
  if root="$(skill_unit_root "$start")"; then
    root="$root/skills"
    for c in "$root"/*/"$name" "$root/$name"; do
      [ -f "$c/SKILL.md" ] && { printf '%s\n' "$c"; return 0; }
    done
  fi
  echo "skill '$name' not found beside or under the skills root of $start" >&2
  return 1
}
