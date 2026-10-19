#!/usr/bin/env bash
# Does the repository of the worktree at <dir> (default .) have a working tollman (hal2 plan 0294, D13)?
# Prints `yes`: /mtm hitches (references/tollman.md): it reports the worktree ready and the tollman's
# train lands it. Prints `no`, with the reason on stderr: /mtm lands itself, as ever (SKILL.md's steps).
#   tollman.sh [<dir>]
# Working is all of:
#   - the tollman's worktree `tollman-<repo>` exists;
#   - its timer is loaded and its mode is `timer`;
#   - its last round is at most 30 minutes old: a tollman that is down never holds the work;
#   - <dir> is not the tollman's own worktree: that one lands itself;
#   - the tollman is awake (hal2 plan 0365 D3, 0375): its sleep flag `roles/tollman/sleep.json` of its worktree
#     (`hal2-cli-roles sleep tollman on|off`) is off; while it stands no train carries a hitched wagon: /mtm lands
#     itself, alone, in its place in the queue;
#   - the installed hal2-cli-git knows `worktree queue ready` (its help names it), or the hitch would fail.
# The first four are read from `tollman.py status --json` of the tollman skill beside this one (its
# state files and one `launchctl print` or `systemctl is-active`; no model, no network). Every doubt is `no`: a
# missing tool or skill, an answer that cannot be read. Exit 0 either way: the answer is the line on stdout.
set -uo pipefail
dir="${1:-.}"
max_age=1800
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
u="$here"; until [ -d "$u/.claude-plugin" ] || [ "$u" = / ]; do u="$(dirname "$u")"; done
if [ -f "$u/scripts/skillpath.sh" ]; then
  . "$u/scripts/skillpath.sh"  # skill_dir <name> <dir>: a sibling skill, flat or in a category (plan 0360 D20)
else
  skill_dir() { printf '%s/../../%s\n' "$2" "$1"; }  # outside a skills unit (a copied script): the flat layout
fi
cli="$(skill_dir tollman "$here")/scripts/tollman.py"

no() { # <reason>: the answer `no`, why on stderr
  echo "tollman.sh: $*" >&2
  echo no
  exit 0
}

for tool in git python3; do
  command -v "$tool" >/dev/null 2>&1 || no "$tool is missing"
done
top=$(git -C "$dir" rev-parse --show-toplevel 2>/dev/null) || no "$dir is no git checkout"
[ -f "$cli" ] || no "the tollman skill is not installed beside mtm ($cli)"
status=$(python3 "$cli" status --json --repo "$top" 2>/dev/null) || no "tollman.py status failed"

# One line: `yes`, or `no <reason>`.
answer=$(printf '%s' "$status" | python3 -c '
import json, os, sys

top, max_age = sys.argv[1], int(sys.argv[2])
try:
    s = json.load(sys.stdin)
    field, timer, mode, age = s["field"], s["timer"], s["mode"], s["last_tick_age_s"]
    label = timer.get("label", "")
    if not s["field_exists"]:
        why = f"no tollman here: no worktree {field}"
    elif os.path.realpath(top) == os.path.realpath(field):
        why = "this is the own worktree of the tollman: it lands itself"
    elif timer.get("loaded") is not True:
        why = f"the timer {label} of the tollman is not loaded"
    elif mode != "timer":
        why = f"the mode of the tollman is {mode}, not timer"
    elif age is None:
        why = "the tollman has not run a round yet"
    elif type(age) is not int or not 0 <= age <= max_age:
        why = f"the last round of the tollman is {age} s old (limit {max_age} s)"
    elif os.path.lexists(os.path.join(field, "roles", "tollman", "sleep.json")):
        why = "the tollman is asleep (its sleep flag stands): no train carries this worktree, it lands itself alone in its turn"
    else:
        why = ""
except Exception as e:
    why = f"the status of the tollman cannot be read ({type(e).__name__})"
print(f"no {why}" if why else "yes")
' "$top" "$max_age" 2>/dev/null) || no "the status of the tollman cannot be read"
case "$answer" in
  yes) ;;
  "no "*) no "${answer#no }" ;;
  *) no "the status of the tollman cannot be read" ;;
esac

command -v hal2-cli-git >/dev/null 2>&1 || no "hal2-cli-git is missing"
# Read whole, never piped into `grep -q` (check-landing-cli.sh says why).
help=$(hal2-cli-git --help 2>&1) || true
case "$help" in
  *"worktree queue ready"*) ;;
  *) no "the installed hal2-cli-git ($(command -v hal2-cli-git)) does not know \`worktree queue ready\`: install the current one" ;;
esac
echo yes
