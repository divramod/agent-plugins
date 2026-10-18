#!/usr/bin/env bash
# Install the tollman's scripts' missing tools (the farmer skill's: its round frame runs them), then check them.
here="$(cd "$(dirname "$0")" && pwd -P)"
u="$here"; until [ -d "$u/.claude-plugin" ] || [ "$u" = / ]; do u="$(dirname "$u")"; done
if [ -f "$u/scripts/skillpath.sh" ]; then
  . "$u/scripts/skillpath.sh"  # skill_dir <name> <dir>: a sibling skill, flat or in a category (plan 0360 D20)
else
  skill_dir() { printf '%s/../../%s\n' "$2" "$1"; }  # outside a skills unit (a copied script): the flat layout
fi
farmer_scripts="$(skill_dir farmer "$here")/scripts"
if [ -x "$farmer_scripts/install-prerequisites.sh" ]; then
  "$farmer_scripts/install-prerequisites.sh" >/dev/null
fi
exec "$here/check-prerequisites.sh"
