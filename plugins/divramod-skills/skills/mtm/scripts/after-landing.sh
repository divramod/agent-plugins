#!/usr/bin/env bash
# The end of a landing (SKILL.md step 7), as code: when the worktree at <dir> (default .) is fully landed (nothing
# on HEAD that the default branch lacks, no change) and its plan is finished (plans/CURRENT_PLAN gone or empty:
# step 6's `plan.py leave` deletes it then), it runs the cleanup skill's `busy` then `delete` in every worktree 00-99.
# A file that names something skips the cleanup; when it names a masterplan (the field waits between two of its
# plans and keeps its builds, hal2 plan 0275 D14) the reason says so: learned from the plan skill's `plan.py
# current` (`masterplan`), never from the slug. A worktree 10-99 also prints the line for the farmer (`farmer: ...`):
# the session cannot delete the worktree it runs in, the farmer's prune duty does (hal2 plan 0143, the user,
# 2026-10-06). Prints `status: cleaned|skipped|busy` and what it did; exit 0 unless git or the cleanup script is
# missing (2). HAL_MTM_CLEANUP overrides the cleanup script's path, HAL_MTM_PLAN the plan skill's plan.py.
set -euo pipefail
dir="${1:-.}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cleanup="${HAL_MTM_CLEANUP:-$here/../../cleanup/scripts/cleanup.py}"
planpy="${HAL_MTM_PLAN:-$here/../../plan/scripts/plan.py}"
command -v git >/dev/null || { echo "missing git" >&2; exit 2; }
[ -f "$cleanup" ] || { echo "missing the cleanup skill's script: $cleanup" >&2; exit 2; }
top="$(git -C "$dir" rev-parse --show-toplevel)"
slot="$(basename "$top")"
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
plan="$top/plans/CURRENT_PLAN"
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
