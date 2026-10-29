#!/usr/bin/env bash
# The end of a landing (SKILL.md step 7), as code: when the worktree at <dir> (default .) is fully landed (nothing
# on HEAD that the default branch lacks, no change) and its plan is finished (CURRENT_PLAN gone or empty, in the git dir and plans/:
# step 6's `plan.py leave` deletes it then), it runs the cleanup skill's `busy` then `delete` in every worktree 00-99.
# A file that names something skips the cleanup; when it names a masterplan (the field waits between two of its
# plans and keeps its builds, hal2 plan 0275 D14) the reason says so: learned from the plan skill's `plan.py
# current` (`masterplan`), never from the slug. A worktree 10-99 also prints the line for the farmer (`farmer: ...`):
# the session cannot delete the worktree it runs in, the tollman's prune duty does (hal2 plan 0143, the user,
# 2026-10-06). Prints `status: cleaned|skipped|busy` and what it did; exit 0 unless git or the cleanup script is
# missing (2). HAL_MTM_CLEANUP overrides the cleanup script's path, HAL_MTM_PLAN the plan skill's plan.py. A fully
# landed worktree of a farm whose plans live in its store first calls the store's sync trigger (`sync --if-due
# landing`, the plan skill's planread.py, hal2 plan 0409 step 9; a line `plan store sync ...`, nothing in the files home;
# HAL_MTM_PLANREAD names another planread.py). First of all, a public farm's snapshot mirror is published on the
# machine that landed (`hal2-cli-git publish`, hal2 plan 0409 step 15; `public` off: nothing, no line); a refusal or a
# failure is printed as `publish: ...` and never stops the rest. HAL_MTM_GIT names another hal2-cli-git.
set -euo pipefail
dir="${1:-.}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
u="$here"; until [ -d "$u/.claude-plugin" ] || [ "$u" = / ]; do u="$(dirname "$u")"; done
if [ -f "$u/scripts/skillpath.sh" ]; then
  . "$u/scripts/skillpath.sh"  # skill_dir <name> <dir>: a sibling skill, flat or in a category (plan 0360 D20)
else
  skill_dir() { printf '%s/../../%s\n' "$2" "$1"; }  # outside a skills unit (a copied script): the flat layout
fi
cleanup="${HAL_MTM_CLEANUP:-$(skill_dir cleanup "$here")/scripts/cleanup.py}"
planpy="${HAL_MTM_PLAN:-$(skill_dir plan "$here")/scripts/plan.py}"
planread="${HAL_MTM_PLANREAD:-$(skill_dir plan "$here")/scripts/planread.py}"
command -v git >/dev/null || { echo "missing git" >&2; exit 2; }
[ -f "$cleanup" ] || { echo "missing the cleanup skill's script: $cleanup" >&2; exit 2; }
top="$(git -C "$dir" rev-parse --show-toplevel)"
slot="$(basename "$top")"
gitcli="${HAL_MTM_GIT:-hal2-cli-git}"
if command -v "$gitcli" >/dev/null && "$gitcli" publish --help >/dev/null 2>&1; then
  if published="$("$gitcli" publish --repo "$top" 2>&1)"; then
    case "$published" in "publish: skipped"*) ;; *) printf '%s\n' "$published" | sed -n '1p;/^note: /p' ;; esac
  else
    printf 'publish: refused or failed, the mirror is not updated:\n%s\n' "$published"
  fi
fi
# A checkout's plan pointer (hal2 plan 0409 step 12): the git dir's hal/<name>, else the files home's plans/<name>.
pointer() {
  local f
  f="$(git -C "$1" rev-parse --path-format=absolute --git-path "hal/$2" 2>/dev/null || true)"
  if [ -n "$f" ] && [ -f "$f" ]; then printf '%s\n' "$f"; else printf '%s\n' "$1/plans/$2"; fi
}
skip() { echo "status: skipped"; echo "why: $1"; exit 0; }
case "$slot" in
  [0-9][0-9]) ;;
  *) skip "$slot is not a numbered worktree 00-99" ;;
esac
default="$(git -C "$top" symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null || echo origin/main)"
git -C "$top" rev-parse --verify --quiet "$default" >/dev/null || default="main"
ahead="$(git -C "$top" log --oneline "$default..HEAD" | wc -l | tr -d ' ')"
[ "$ahead" = 0 ] || skip "$ahead commit(s) not on $default"
[ -z "$(git -C "$top" status --porcelain)" ] || skip "uncommitted changes"
[ ! -f "$planread" ] || python3 "$planread" sync landing --root "$top" || true
plan="$(pointer "$top" CURRENT_PLAN)"
if [ -s "$plan" ]; then
  named="$(tr -d '\n' < "$plan")"
  if [ -f "$planpy" ] && python3 "$planpy" --root "$top" current 2>/dev/null \
      | python3 -c 'import json, sys; sys.exit(0 if json.load(sys.stdin).get("masterplan") is True else 1)' 2>/dev/null; then
    skip "plans/CURRENT_PLAN names the masterplan $named: the field goes on with its next plan and keeps its builds"
  fi
  skip "plans/CURRENT_PLAN still names $named: the plan is not finished"
fi
if ! busy="$(cd "$top" && python3 "$cleanup" busy 2>&1)"; then
  echo "status: busy"
  echo "why: a build or test still runs in $top"
  printf '%s\n' "$busy"
  exit 0
fi
(cd "$top" && python3 "$cleanup" delete)
echo "status: cleaned"
if [ "${slot#0}" = "$slot" ]; then
  echo "farmer: worktree $slot done: landed, plan finished, cleaned; the prune duty may remove it"
fi
