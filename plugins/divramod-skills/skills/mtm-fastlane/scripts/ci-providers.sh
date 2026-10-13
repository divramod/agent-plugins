#!/usr/bin/env bash
# shellcheck disable=SC2154 # conf_get, top and die come from fastlane-lib.sh
# The land runs of GitHub (gh) and GitLab (glab) as ci-stop.sh sees them. Each
# provider has `<p>_runs`, printing one unfinished land run per line as
# `<id> <ref> <merged 0|1> <queued_only 0|1> <attempt>` (merged: its MERGE_JOB
# succeeded, the default branch moved; queued_only: none of its unfinished jobs
# started; attempt: which start of the run this is, a run started again keeps
# its id), `<p>_cancel <id> <attempt>` (the whole run), `<p>_cancel_queued <id>
# <attempt>` (only the jobs that never started; 1 when the provider cannot do
# that while others run) and `<p>_ending <id>` (0: the run ends by itself,
# nobody asks it to cancel). A request to cancel a whole run calls `asking <id>
# <attempt>` first: ci-stop.sh notes it there and sends an attempt of a run one
# such request, never a second.

provider_of() { # github, gitlab or none, by the conf's PROVIDER or origin's URL
  local p
  p=$(conf_get PROVIDER "")
  [ -n "$p" ] && { echo "$p"; return; }
  case "$(git -C "$top" remote get-url origin 2>/dev/null)" in
    *github.com*) echo github ;;
    *gitlab*) echo gitlab ;;
    *) echo none ;;
  esac
}

# The jobs (`<status> <conclusion> <name>` lines) of a run → `<merged> <queued_only>`.
judge_jobs() {
  local merge_job merged=0 queued_only=1 status conclusion name
  merge_job=$(conf_get MERGE_JOB merge)
  while read -r status conclusion name; do
    [ -n "$status" ] || continue
    case "$name" in
      "$merge_job"|*" / $merge_job"|*"/$merge_job")
        [ "$conclusion" = success ] && merged=1 ;;
    esac
    case "$status" in
      completed|success|failed|canceled|cancelled|skipped|manual) ;;
      queued|waiting|pending|requested|created|waiting_for_resource|preparing|scheduled) ;;
      *) queued_only=0 ;;
    esac
  done
  echo "$merged $queued_only"
}

# The landing workflow's two names: merge-to-main.yml, before hal2 plan 0263 land.yml. A run is under the name its
# commit had, so around the rename the unfinished runs are under either: where one is a land workflow, both are.
LAND_TWINS="merge-to-main.yml land.yml"

# The land workflows, words: the conf's LAND_WORKFLOWS, else those of the two names the worktree or origin's
# default branch has; then the other name of the two where one is among them (a conf written before the rename).
github_workflows() {
  local w f
  w=$(conf_get LAND_WORKFLOWS "")
  if [ -z "$w" ]; then
    for f in $LAND_TWINS; do
      if [ -f "$top/.github/workflows/$f" ] \
        || git -C "$top" cat-file -e "origin/${default:-main}:.github/workflows/$f" 2>/dev/null; then
        w="$w${w:+ }$f"
      fi
    done
  fi
  for f in $LAND_TWINS; do
    case " $w " in
      *" $f "*|*"/$f "*) ;;
      *" merge-to-main.yml "*|*"/merge-to-main.yml "*|*" land.yml "*|*"/land.yml "*) w="$w $f" ;;
    esac
  done
  echo "$w"
}

# The unfinished runs (`<id> <ref> <attempt>` lines) of one workflow file. Exit 3: GitHub does not know the file (not
# renamed yet, or renamed away: no runs); 1: gh failed otherwise (its message on stderr).
github_unfinished() {
  local err rc=0
  # gh's stdout stays this function's (fd 3); its stderr is read, a 404 says GitHub does not know the file.
  { err=$(gh run list --workflow "$1" --limit 20 --json databaseId,headBranch,status,attempt \
    --jq '.[] | select(.status != "completed") | "\(.databaseId) \(.headBranch) \(.attempt // 1)"' 2>&1 >&3); } 3>&1 || rc=$?
  if [ "$rc" -eq 0 ]; then
    return 0
  fi
  case "$err" in
    *"HTTP 404"*|*"could not find any workflows named"*) return 3 ;;
  esac
  [ -z "$err" ] || echo "$err" >&2
  return 1
}

# A workflow file GitHub does not know has no runs, as long as it knows another of them: when it knows none,
# nothing is known (exit 1).
github_runs() {
  local w runs rc id ref attempt known=0 asked=0
  for w in $(github_workflows); do
    asked=1 rc=0
    runs=$(github_unfinished "$w") || rc=$?
    case "$rc" in
      0) known=1 ;;
      3) continue ;;
      *) return 1 ;;
    esac
    while read -r id ref attempt; do
      [ -n "$id" ] || continue
      echo "$id $ref $(gh run view "$id" --json jobs \
        --jq '.jobs[] | "\(.status) \(if (.conclusion // "") == "" then "none" else .conclusion end) \(.name)"' | judge_jobs) ${attempt:-1}"
    done <<RUNS
$runs
RUNS
  done
  if [ "$asked" = 1 ] && [ "$known" = 0 ]; then
    echo "GitHub knows none of the land workflows ($(github_workflows))" >&2
    return 1
  fi
}

# The one place that asks GitHub to cancel a run.
github_cancel() {
  asking "$1" "$2"
  gh run cancel "$1" >/dev/null
}

# GitHub cancels runs, not single jobs: once nothing of the run runs any more,
# cancelling it cancels only jobs that never started.
github_cancel_queued() {
  local verdict
  verdict=$(gh run view "$1" --json jobs --jq '.jobs[] | "\(.status) \(if (.conclusion // "") == "" then "none" else .conclusion end) \(.name)"' | judge_jobs)
  [ "${verdict#* }" = 1 ] || return 1
  github_cancel "$1" "$2"
}

# A run that its own fail-fast is ending (hal2 plan 0263 rows 19 and 73, the rule hal2-git's ci/fail_fast.rs
# follows): every job the landing workflow's `gate` job needs carries the step `[NN] fail fast: stop the run`, which
# asks GitHub to cancel the run once its job failed or hit its time limit. The run is ending when that step ended
# `success` in one of its jobs (the request went out) or still runs there (`in_progress`: it runs only in such a job,
# and its request is going out in these seconds; the workflow's own look, gate/lib/stop-run.sh, reads it so too), or
# when a job that carries the step concluded `cancelled` (a cancel reached the gate's jobs). Such a run can no longer
# merge. Nothing else counts: a cancelled job without the step (at its own time limit, a cleanup replaced in its
# group), a stop step still before its job (`pending`), one that ended `failure` (the request did not go out, or
# GitHub refused it) and a run of a workflow file without the step leave the run to be asked.
# shellcheck disable=SC2016 # $stop is jq's
GITHUB_ENDING='any(.jobs[];
  [.steps[]? | select((.name // "") | test("^\\s*(\\[[0-9]+\\]\\s*)?fail fast: stop the run\\s*$"))
    | .status == "in_progress" or .conclusion == "success"] as $stop
  | ($stop | length) > 0 and (.conclusion == "cancelled" or ($stop | any)))'

# 0: the run ends by itself. A look that fails says 1: the run then gets its one request, as before the look.
github_ending() { [ "$(gh run view "$1" --json jobs --jq "$GITHUB_ENDING")" = true ]; }

gitlab_ref_matches() { # the conf's LAND_REFS globs, default land/*
  local glob
  for glob in $(conf_get LAND_REFS 'land/*'); do
    # shellcheck disable=SC2254 # the glob is meant
    case "$1" in $glob) return 0 ;; esac
  done
  return 1
}

gitlab_runs() {
  local id ref
  glab api "projects/:id/pipelines?per_page=50" \
    | jq -r '.[] | select(.status | IN("created","waiting_for_resource","preparing","pending","running","scheduled"))
             | "\(.id) \(.ref)"' \
    | while read -r id ref; do
        gitlab_ref_matches "$ref" || continue
        echo "$id $ref $(glab api "projects/:id/pipelines/$id/jobs?per_page=100" \
          | jq -r '.[] | "\(.status) \(if .status == "success" then "success" else "none" end) \(.name)"' | judge_jobs) 1"
      done
}

gitlab_cancel() {
  asking "$1" "$2"
  glab api -X POST "projects/:id/pipelines/$1/cancel" >/dev/null
}

# GitLab lists a pipeline that is cancelling as finished (gitlab_runs): none is ever seen ending.
gitlab_ending() { return 1; }

gitlab_cancel_queued() {
  local job
  for job in $(glab api "projects/:id/pipelines/$1/jobs?per_page=100" \
    | jq -r '.[] | select(.status | IN("created","pending","waiting_for_resource","preparing","scheduled")) | .id'); do
    glab api -X POST "projects/:id/jobs/$job/cancel" >/dev/null
  done
}
