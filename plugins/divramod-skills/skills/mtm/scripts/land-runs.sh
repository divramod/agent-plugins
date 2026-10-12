#!/usr/bin/env bash
# Wait until no land.yml run is unfinished in the repository of <dir> (default .),
# so a landing through CI (which reserves the queue first) never pushes a
# candidate while another landing still runs or ships (references/ci.md). A run counts until its
# status is `completed`: `queued` too (a ship job waiting for a runner is queued).
#   land-runs.sh [--once] [--interval <s>] [--max-wait <minutes>] [<dir>]
# Exit 0: none unfinished. --once: exit 6 and list them instead of waiting.
# Exit 7: still unfinished after --max-wait (default 60): a run stuck queued or
# waiting (a parked runner, a pending approval); tell the farmer, do not push.
# Exit 2: gh is missing, or --max-wait/--interval is no whole number. Exit 1: gh failed, nothing is known: do not push.
set -euo pipefail
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
unfinished() {
  gh run list --workflow land.yml --limit 10 --json databaseId,headBranch,status \
    --jq '.[] | select(.status != "completed") | "\(.databaseId) \(.headBranch) \(.status)"'
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
