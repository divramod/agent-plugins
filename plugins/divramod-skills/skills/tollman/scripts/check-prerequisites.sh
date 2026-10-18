#!/usr/bin/env bash
# Check the tools the tollman's scripts need: they run on the farmer skill's round frame (farmer_frame.py), so
# the tools are that skill's (python3, git, gh, hal2-cli-git, hal2-cli-agents). Exit 1 when a required tool is missing.
here="$(cd "$(dirname "$0")" && pwd -P)"
u="$here"; until [ -d "$u/.claude-plugin" ] || [ "$u" = / ]; do u="$(dirname "$u")"; done
if [ -f "$u/scripts/skillpath.sh" ]; then
  . "$u/scripts/skillpath.sh"  # skill_dir <name> <dir>: a sibling skill, flat or in a category (plan 0360 D20)
else
  skill_dir() { printf '%s/../../%s\n' "$2" "$1"; }  # outside a skills unit (a copied script): the flat layout
fi
frame="$(skill_dir farmer "$here")/scripts"
if [ ! -f "$frame/tick.py" ]; then
  echo "MISSING the farmer skill's scripts ($frame) -> install the skill farmer beside tollman"
  exit 1
fi
exec "$frame/check-prerequisites.sh"
