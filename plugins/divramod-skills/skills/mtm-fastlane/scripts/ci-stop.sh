#!/usr/bin/env bash
# shellcheck source-path=SCRIPTDIR
# Stop the land attempts before the fastlane reserves (SKILL.md, land step 3), in
# the worktree <dir> (default .):
#   ci-stop.sh [--dry-run] [--max-wait 60m] [--interval <s>] [<dir>]
# 1. hal2-cli-git: this slot goes to the front of the queue's priority list, and
#    another slot's landing or reservation that holds the queue is stopped.
# 2. Every unfinished land run (GitHub: the conf's LAND_WORKFLOWS, default land.yml;
#    GitLab: pipelines on LAND_REFS, default land/*) whose MERGE_JOB has not
#    succeeded is cancelled; one that merged is waited for, and once SHIP_GRACE
#    (default 15m) has passed its jobs that never started are cancelled.
# Exits once no land run is unfinished, printing JSON: provider, stopped_slots,
# cancelled, waited. --dry-run says what it would do and changes nothing.
# Exit 0 done, 1 a CLI failed, 2 a missing tool, 7 runs still unfinished after --max-wait, 64 usage.
set -euo pipefail
FASTLANE_HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=fastlane-lib.sh
. "$FASTLANE_HERE/fastlane-lib.sh"
# shellcheck source=ci-providers.sh
. "$FASTLANE_HERE/ci-providers.sh"

dir=. max_wait=60m interval=15 dry_run=0
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) dry_run=1 ;;
    --max-wait) max_wait="${2:-}"; shift ;;
    --interval) interval="${2:-}"; shift ;;
    -*) die 64 "unknown option $1" ;;
    *) dir="$1" ;;
  esac
  shift
done
case "$interval" in ''|*[!0-9]*) die 64 "--interval takes seconds, not '$interval'" ;; esac
need git
need jq
repo_paths
mins=$(minutes "$max_wait")
grace=$(minutes "$(conf_get SHIP_GRACE 15m)")
say() { echo "ci-stop: $*" >&2; }
stopped="" cancelled="" waited=""

# 1. The merge queue.
if bin=$(hal2_bin); then
  slot=$(basename "$top")
  queue=$(cd "$top" && "$bin" worktree queue --json) || die 1 "hal2-cli-git worktree queue failed"
  holder=$(echo "$queue" | jq -r --arg wt "$top" '.queue[] | select(.holding and .worktree != $wt) | .slot')
  others=$(echo "$queue" | jq -r --arg s "$slot" '(.priority.slots // [])[] | select(. != $s)')
  if [ "$dry_run" = 1 ]; then
    say "would move $slot to the front of the queue"
    [ -z "$holder" ] || say "would stop the landing of $holder, which holds the queue"
  else
    # shellcheck disable=SC2086 # the slots are words
    (cd "$top" && "$bin" worktree queue order "$slot" $others --json >/dev/null) || die 1 "queue order failed"
    say "$slot is first in the queue"
    if [ -n "$holder" ]; then
      (cd "$top" && "$bin" worktree stop "$holder" --json >/dev/null) || die 1 "worktree stop $holder failed"
      say "stopped the landing of $holder"
    fi
  fi
  stopped="$holder"
fi

# 2. The land runs.
provider=$(provider_of)
case "$provider" in
  github) need gh
    [ -n "$(github_workflows)" ] || say "no land workflow (LAND_WORKFLOWS, .github/workflows/land.yml): no land runs to stop" ;;
  gitlab) need glab ;;
  *) say "origin is on neither GitHub nor GitLab: no land runs to stop" ;;
esac
marks="$state/ci-stop"
mkdir -p "$marks"
waited_s=0
while [ "$provider" = github ] || [ "$provider" = gitlab ]; do
  runs=$("${provider}_runs") || die 1 "listing the $provider land runs failed (logged in?)"
  [ -n "$runs" ] || break
  while read -r id ref merged queued_only; do
    if [ "$merged" = 0 ]; then
      if [ "$dry_run" = 1 ]; then say "would cancel run $id ($ref), not merged"; continue; fi
      "${provider}_cancel" "$id" || die 1 "cancelling run $id failed"
      say "cancelled run $id ($ref), not merged"
      cancelled="$cancelled $id"
      continue
    fi
    [ -f "$marks/$id" ] || date +%s > "$marks/$id"
    case " $waited " in *" $id "*) ;; *) waited="$waited $id" ;; esac
    if [ "$dry_run" = 1 ]; then say "would wait for run $id ($ref): merged, shipping"; continue; fi
    if [ $(( $(date +%s) - $(cat "$marks/$id") )) -ge $(( grace * 60 )) ] && [ "$queued_only" = 1 ]; then
      if "${provider}_cancel_queued" "$id"; then
        say "cancelled the jobs of run $id ($ref) that never started, after the ${grace}m grace"
        cancelled="$cancelled $id"
      fi
    else
      say "waiting for run $id ($ref): merged, its started jobs finish"
    fi
  done <<EOF
$runs
EOF
  [ "$dry_run" = 0 ] || break
  [ "$waited_s" -lt $(( mins * 60 )) ] || die 7 "land runs still unfinished after ${mins}m: tell the user"
  sleep "$interval"
  waited_s=$(( waited_s + interval ))
done

words() { for w in "$@"; do echo "$w"; done | jq -R . | jq -sc 'map(select(. != "")) | unique'; }
ids() { words "$@" | jq -c 'map(tonumber? // .)'; }
# shellcheck disable=SC2086 # the lists are words
jq -nc --arg provider "$provider" --argjson dry "$dry_run" --argjson stopped "$(words $stopped)" \
  --argjson cancelled "$(ids $cancelled)" --argjson waited "$(ids $waited)" \
  '{provider: $provider, dry_run: ($dry == 1), stopped_slots: $stopped, cancelled: $cancelled, waited: $waited}'
