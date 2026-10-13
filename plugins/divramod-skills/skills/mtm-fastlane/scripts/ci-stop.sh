#!/usr/bin/env bash
# shellcheck source-path=SCRIPTDIR
# Stop the land attempts before the fastlane reserves (SKILL.md, land step 3), in
# the worktree <dir> (default .):
#   ci-stop.sh [--dry-run] [--max-wait 60m] [--interval <s>] [<dir>]
# 1. hal2-cli-git: this slot goes to the front of the queue's priority list, and
#    another slot's landing or reservation that holds the queue is stopped.
# 2. Every unfinished land run (GitHub: the conf's LAND_WORKFLOWS, default the repository's
#    merge-to-main.yml or land.yml, and always both of these names where one is a land
#    workflow: a run started before the rename is under the old one; GitLab: pipelines
#    on LAND_REFS, default land/*) whose MERGE_JOB has not
#    succeeded is cancelled; one that merged is waited for, and once SHIP_GRACE
#    (default 15m) has passed its jobs that never started are cancelled.
#    A run is asked to cancel once (once more when it was started again: a new
#    attempt), however many rounds its end takes and however often this is called,
#    and never when its own fail-fast is ending it already (`ending` below): a
#    second request to a run that is cancelling seems to end its `always()` jobs,
#    the parks, unrun, and a machine stays on (hal2 plan 0263).
# Exits once no land run is unfinished, printing JSON: provider, stopped_slots,
# cancelled (asked by this call), ending (not asked: ending by itself, or asked by
# an earlier call), waited. --dry-run says what it would do and changes nothing.
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
stopped="" cancelled="" waited="" ending="" spared=""

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
    [ -n "$(github_workflows)" ] || say "no land workflow (LAND_WORKFLOWS, .github/workflows/merge-to-main.yml or land.yml): no land runs to stop" ;;
  gitlab) need glab ;;
  *) say "origin is on neither GitHub nor GitLab: no land runs to stop" ;;
esac
marks="$state/ci-stop"
mkdir -p "$marks"
# The runs asked to cancel, a file `<id>.<attempt>.asked` each (a run started again keeps its id and is a new
# attempt): ci-providers.sh calls `asking` before a request goes out, so a request that failed counts too (it may
# have arrived), and a later call of this script knows them as well.
asked() { [ -e "$marks/$1.$2.asked" ]; }
asking() { : > "$marks/$1.$2.asked"; }

# spared <id> <ref> <attempt>: this run gets no request, said once: it was asked before, or it is ending by itself.
spared() {
  case " $spared " in *" $1.$3 "*) return 0 ;; esac
  if asked "$1" "$3"; then
    say "waiting for run $1 ($2) to end: it was asked to cancel, and no run is asked twice"
    case " $cancelled " in *" $1 "*) ;; *) ending="$ending $1" ;; esac
  elif "${provider}_ending" "$1"; then
    say "run $1 ($2) ends by itself (its own fail fast stopped it): not asked, waiting for its end"
    ending="$ending $1"
  else
    return 1
  fi
  spared="$spared $1.$3"
}
waited_s=0
while [ "$provider" = github ] || [ "$provider" = gitlab ]; do
  runs=$("${provider}_runs") || die 1 "listing the $provider land runs failed (logged in?)"
  [ -n "$runs" ] || break
  while read -r id ref merged queued_only attempt; do
    if [ "$merged" = 0 ]; then
      spared "$id" "$ref" "$attempt" && continue
      if [ "$dry_run" = 1 ]; then say "would cancel run $id ($ref), not merged"; continue; fi
      "${provider}_cancel" "$id" "$attempt" || die 1 "cancelling run $id failed; it is not asked again \
(if nothing cancels it: rm $marks/$id.$attempt.asked, rerun)"
      say "cancelled run $id ($ref), not merged"
      cancelled="$cancelled $id"
      continue
    fi
    [ -f "$marks/$id" ] || date +%s > "$marks/$id"
    case " $waited " in *" $id "*) ;; *) waited="$waited $id" ;; esac
    if [ "$dry_run" = 1 ]; then say "would wait for run $id ($ref): merged, shipping"; continue; fi
    if [ $(( $(date +%s) - $(cat "$marks/$id") )) -ge $(( grace * 60 )) ] && [ "$queued_only" = 1 ]; then
      spared "$id" "$ref" "$attempt" && continue
      if "${provider}_cancel_queued" "$id" "$attempt"; then
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
  --argjson cancelled "$(ids $cancelled)" --argjson ending "$(ids $ending)" --argjson waited "$(ids $waited)" \
  '{provider: $provider, dry_run: ($dry == 1), stopped_slots: $stopped, cancelled: $cancelled, ending: $ending,
    waited: $waited}'
