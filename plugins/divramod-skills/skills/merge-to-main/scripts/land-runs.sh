#!/usr/bin/env bash
# Wait until no run of the landing workflow is unfinished in the repository of <dir> (default .),
# so a landing through CI (which reserves the queue first) never pushes a
# candidate while another landing still runs or ships (references/ci.md). The workflow is
# merge-to-main-local.yml or merge-to-main-cloud.yml (plan 0423 D4), before them dev-merge-to-main.yml and
# merge-to-main.yml: all are asked, a run started before a rename finishes under the old name. A run counts until its
# status is `completed`: `queued` too (a ship job waiting for a runner is queued).
#   land-runs.sh [--once] [--interval <s>] [--max-wait <minutes>] [<dir>]
# Exit 0: none unfinished. --once: exit 6 and list them instead of waiting.
# Exit 7: still unfinished after --max-wait (default 60): a run stuck queued or
# waiting (a parked runner, a pending approval); tell the farmer, do not push.
# A file GitHub does not know (HTTP 404: the workflow is not renamed yet, or has been) has no runs,
# as long as GitHub knows another one; when it knows none, nothing is known.
# Exit 2: gh is missing, or --max-wait/--interval is no whole number. Exit 1: gh failed, nothing is known: do not push.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
u="$here"; until [ -d "$u/.claude-plugin" ] || [ "$u" = / ]; do u="$(dirname "$u")"; done
if [ -f "$u/scripts/landing-workflow.sh" ]; then
  . "$u/scripts/landing-workflow.sh"  # LANDING_WORKFLOWS, landing_workflow_order <dir> (plan 0423 D4)
else  # outside a skills unit (a copied script): the names, no setting
  LANDING_WORKFLOWS="merge-to-main-local.yml merge-to-main-cloud.yml dev-merge-to-main.yml merge-to-main.yml"
  landing_workflow_order() { printf '%s\n' $LANDING_WORKFLOWS; }
fi
once=0
interval=60
max_wait=60
dir=.
while [ $# -gt 0 ]; do
  case "$1" in
    --once) once=1 ;;
    --interval) shift; interval="$1" ;;
    --max-wait) shift; max_wait="$1" ;;
    *) dir="$1" ;;
  esac
  shift
done
for n in "$max_wait" "$interval"; do
  case "$n" in
    ''|*[!0-9]*) echo "land-runs.sh: --max-wait (minutes) and --interval (seconds) take whole numbers, not '$n'" >&2; exit 2 ;;
  esac
done
if ! command -v gh >/dev/null 2>&1; then
  echo "land-runs.sh: gh is missing -> brew install gh (or: bash $(dirname "$0")/install-prerequisites.sh)" >&2
  exit 2
fi
cd "$dir"
# The unfinished runs of one workflow file, a line each. Exit 3: GitHub does not know the file; 1: gh failed
# otherwise (its message on stderr).
unfinished_of() {
  local err rc=0
  # gh's stdout stays this function's (fd 3); its stderr is read, a 404 says GitHub does not know the file.
  { err=$(gh run list --workflow "$1" --limit 10 --json databaseId,headBranch,status \
    --jq '.[] | select(.status != "completed") | "\(.databaseId) \(.headBranch) \(.status)"' 2>&1 >&3); } 3>&1 || rc=$?
  if [ "$rc" -eq 0 ]; then
    return 0
  fi
  case "$err" in
    *"HTTP 404"*|*"could not find any workflows named"*) return 3 ;;
  esac
  [ -z "$err" ] || echo "$err" >&2
  return 1
}
# The unfinished runs of every name of the workflow file.
unfinished() {
  local file runs rc known=0 all=""
  for file in $LANDING_WORKFLOWS; do
    rc=0
    runs=$(unfinished_of "$file") || rc=$?
    case "$rc" in
      0) known=1 ;;
      3) continue ;;
      *) return 1 ;;
    esac
    [ -z "$runs" ] || all="${all:+$all
}$runs"
  done
  if [ "$known" -eq 0 ]; then
    echo "land-runs.sh: GitHub knows none of $LANDING_WORKFLOWS in this repository" >&2
    return 1
  fi
  [ -z "$all" ] || echo "$all"
}
while :; do
  if ! runs=$(unfinished); then
    echo "land-runs.sh: gh run list failed (gh auth status?); cannot tell, do not push" >&2
    exit 1
  fi
  if [ -z "$runs" ]; then
    exit 0
  fi
  echo "land runs unfinished: $(echo "$runs" | paste -sd ',' - | sed 's/,/, /g')"
  if [ "$once" -eq 1 ]; then
    exit 6
  fi
  if [ "$SECONDS" -ge $((max_wait * 60)) ]; then
    echo "land-runs.sh: still unfinished after ${max_wait} min: tell the farmer (a parked runner or a pending approval?); do not push" >&2
    exit 7
  fi
  sleep "$interval"
done
