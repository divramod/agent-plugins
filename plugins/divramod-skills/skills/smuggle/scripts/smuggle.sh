#!/usr/bin/env bash
# shellcheck source-path=SCRIPTDIR
# The smuggle's deterministic steps (SKILL.md), run in the worktree <dir> (default .):
#   smuggle.sh preflight [--from-mtm] [--yes-outside] [<dir>]   a worktree on its own branch, the two scripts, the
#                                                 fingerprint, who started it and the units (units.py warn)
#   smuggle.sh fingerprint [<dir>]                the fingerprint of the conf's FINGERPRINT_INPUTS now
#   smuggle.sh reserve [--max-wait 60m] [<dir>]   the merge queue's turn (hal2-cli-git) or the lock
#   smuggle.sh release [--force] [<dir>]          give it back
#   smuggle.sh checks [--dry-run] [<dir>]         .hal/smuggle-worktree.sh, SMUGGLE_BASE=origin/<default>
#   smuggle.sh land [--max-wait 60m] [<dir>]      the candidate pushed straight to the default branch
#   smuggle.sh main [--base <rev>] [--head <rev>] [<dir>]   .hal/smuggle-main.sh on the landed commit
# hal2-cli-git lands when it has --local (HAL2_CLI_GIT names the binary); SMUGGLE_PLAIN=1 lands with plain git.
# Exit 0 ok, 1 red or not runnable (fix and rerun), 2 a missing tool (install-prerequisites.sh),
# 3 a conflict (merge origin/<default> in and rerun), 4 a change outside the units of .hal/smuggle.toml (ask the user;
# on yes rerun with --yes-outside), 5 stopped by the user, 6 refused: --from-mtm (started by /mtm) while the merge
# queue is in production mode, 7 a wait over --max-wait, 64 usage.
set -euo pipefail
SMUGGLE_HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=smuggle-lib.sh
. "$SMUGGLE_HERE/smuggle-lib.sh"

cmd="${1:-}"
[ $# -gt 0 ] && shift
dir=. max_wait=60m dry_run=0 force="" base="" head="" from_mtm=0 yes_outside=""
while [ $# -gt 0 ]; do
  case "$1" in
    --max-wait) max_wait="${2:-}"; shift ;;
    --dry-run) dry_run=1 ;;
    --force) force=--force ;;
    --from-mtm) from_mtm=1 ;;
    --yes-outside) yes_outside=--yes-outside ;;
    --base) base="${2:-}"; shift ;;
    --head) head="${2:-}"; shift ;;
    -*) die 64 "unknown option $1" ;;
    *) dir="$1" ;;
  esac
  shift
done
need git
repo_paths

# Who started it (hal2 plan 0360 D53, D76): the user, or /mtm (--from-mtm) only in the queue's smuggle mode.
started_by() {
  if [ "$from_mtm" = 0 ]; then
    echo "started by: the user"
    return
  fi
  local mode
  mode=$(queue_mode)
  [ "$mode" = smuggle ] || die 6 "refused: /mtm started this smuggle, but the merge queue is in $mode mode: \
only the user starts a smuggle there; /mtm hitches or lands"
  echo "started by: /mtm in smuggle mode"
}

preflight() {
  started_by
  [ "$top" != "$main_checkout" ] || die 1 "$top is the main checkout: the smuggle lands a worktree"
  [ -n "$branch" ] && [ "$branch" != "$default" ] || die 1 "$top is not on a branch of its own"
  local script
  for script in "$worktree_script" "$top/$main_script"; do
    [ -x "$script" ] || die 1 "${script#"$top"/} is missing or not executable: run /smuggle configure"
  done
  echo "worktree: $top"
  echo "branch: $branch"
  echo "default: $default"
  echo "main checkout: $main_checkout"
  if bin=$(hal2_bin); then echo "lands: hal2-cli-git ($bin)"; else echo "lands: plain git"; fi
  if bin=$(hal2_smuggle_bin); then
    echo "smuggle: $bin worktree merge-to-main --smuggle (one call, SKILL.md)"
  else
    echo "smuggle: no hal2-cli-git --smuggle here: the steps (SKILL.md)"
  fi
  local want now
  want=$(conf_get FINGERPRINT "")
  now=$(fingerprint)
  if [ -n "$want" ] && [ "$want" = "$now" ]; then
    echo "fingerprint: current"
  else
    echo "fingerprint: stale: the CI inputs changed since configure; run /smuggle configure after the landing"
  fi
  need python3
  # shellcheck disable=SC2086 # nothing or one option
  python3 "$SMUGGLE_HERE/units.py" warn --repo "$top" --base "origin/$default" $yes_outside || exit $?
}

reserve() {
  local mins rc=0
  mins=$(minutes "$max_wait")
  if bin=$(hal2_bin); then
    (cd "$top" && "$bin" worktree reserve --max-wait "${mins}m" --json) || rc=$?
    case "$rc" in 0) ;; 6) exit 7 ;; 2) exit 1 ;; *) exit "$rc" ;; esac
  else
    lock_take "$mins"
  fi
}

release() {
  if bin=$(hal2_bin); then
    (cd "$top" && "$bin" worktree release --json)
  else
    lock_drop "$force"
  fi
}

checks() {
  git -C "$top" fetch -q origin "$default" || die 1 "git fetch origin $default failed"
  local args=""
  [ "$dry_run" = 1 ] && args=--dry-run
  # shellcheck disable=SC2086 # no argument or --dry-run
  (cd "$top" && SMUGGLE_BASE="origin/$default" "$worktree_script" $args) \
    || die 1 "the worktree checks are red: fix, commit and rerun"
}

land() {
  local mins rc=0
  mins=$(minutes "$max_wait")
  git -C "$top" fetch -q origin "$default" || die 1 "git fetch origin $default failed"
  local before
  before=$(git -C "$top" rev-parse "origin/$default")
  if bin=$(hal2_bin); then
    (cd "$top" && "$bin" worktree merge-to-main --local --keep-reserved --max-wait "${mins}m" --json) || rc=$?
    case "$rc" in 0) ;; 2|4) exit 1 ;; 6) exit 7 ;; *) exit "$rc" ;; esac
  else
    "$SMUGGLE_HERE/plain-land.sh" "$top"
  fi
  git -C "$top" fetch -q origin "$default"
  mkdir -p "$state"
  printf 'base=%s\nhead=%s\n' "$before" "$(git -C "$top" rev-parse "origin/$default")" > "$state/last"
  echo "landed: $(sed -n 's/^base=//p' "$state/last" | cut -c1-9)..$(sed -n 's/^head=//p' "$state/last" | cut -c1-9)"
}

# Where the main script runs: the main checkout when it is clean on the default
# branch at the landed commit (its build caches are warm), else <worktrees>/.smuggle.
main_where() {
  if [ "$(git -C "$main_checkout" symbolic-ref --quiet --short HEAD 2>/dev/null)" = "$default" ] \
    && [ -z "$(git -C "$main_checkout" status --porcelain)" ] \
    && [ "$(git -C "$main_checkout" rev-parse HEAD)" = "$head" ]; then
    echo "$main_checkout"
    return
  fi
  local spare
  spare="$(dirname "$top")/.smuggle"
  if [ -e "$spare/.git" ]; then
    git -C "$spare" checkout -q --detach "$head" >&2
  else
    git -C "$top" worktree add -q --detach "$spare" "$head" >&2
  fi
  echo "$spare"
}

main_checks() {
  if [ -z "$base" ] || [ -z "$head" ]; then
    [ -f "$state/last" ] || die 64 "no landing recorded: pass --base and --head"
    [ -n "$base" ] || base=$(sed -n 's/^base=//p' "$state/last")
    [ -n "$head" ] || head=$(sed -n 's/^head=//p' "$state/last")
  fi
  head=$(git -C "$top" rev-parse "$head^{commit}") || die 1 "no commit $head"
  local where
  where=$(main_where)
  echo "main checks in: $where"
  [ -x "$where/$main_script" ] || die 1 "$main_script is missing at ${head:0:9}"
  (cd "$where" && SMUGGLE_BASE="$base" SMUGGLE_HEAD="$head" "./$main_script") \
    || die 1 "the main checks are red; the landing stays: fix it in a new landing"
}

case "$cmd" in
  preflight) preflight ;;
  fingerprint) fingerprint ;;
  reserve) reserve ;;
  release) release ;;
  checks) checks ;;
  land) land ;;
  main) main_checks ;;
  -h|--help|help|h|"") sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//' ; [ -n "$cmd" ] || exit 64 ;;
  *) die 64 "unknown command $cmd (preflight, fingerprint, reserve, release, checks, land, main)" ;;
esac
