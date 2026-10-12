#!/usr/bin/env bash
# shellcheck disable=SC2154 # conf_get, top and die come from fastlane-lib.sh
# The land runs of GitHub (gh) and GitLab (glab) as ci-stop.sh sees them. Each
# provider has `<p>_runs`, printing one unfinished land run per line as
# `<id> <ref> <merged 0|1> <queued_only 0|1>` (merged: its MERGE_JOB succeeded,
# the default branch moved; queued_only: none of its unfinished jobs started),
# `<p>_cancel <id>` (the whole run) and `<p>_cancel_queued <id>` (only the jobs
# that never started; 1 when the provider cannot do that while others run).

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

github_workflows() {
  local w
  w=$(conf_get LAND_WORKFLOWS "")
  if [ -z "$w" ] && [ -f "$top/.github/workflows/land.yml" ]; then w=land.yml; fi
  echo "$w"
}

github_runs() {
  local w id ref
  for w in $(github_workflows); do
    gh run list --workflow "$w" --limit 20 --json databaseId,headBranch,status \
      --jq '.[] | select(.status != "completed") | "\(.databaseId) \(.headBranch)"' \
      | while read -r id ref; do
          echo "$id $ref $(gh run view "$id" --json jobs \
            --jq '.jobs[] | "\(.status) \(if (.conclusion // "") == "" then "none" else .conclusion end) \(.name)"' | judge_jobs)"
        done
  done
}

github_cancel() { gh run cancel "$1" >/dev/null; }

# GitHub cancels runs, not single jobs: once nothing of the run runs any more,
# cancelling it cancels only jobs that never started.
github_cancel_queued() {
  local verdict
  verdict=$(gh run view "$1" --json jobs --jq '.jobs[] | "\(.status) \(if (.conclusion // "") == "" then "none" else .conclusion end) \(.name)"' | judge_jobs)
  [ "${verdict#* }" = 1 ] || return 1
  gh run cancel "$1" >/dev/null
}

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
          | jq -r '.[] | "\(.status) \(if .status == "success" then "success" else "none" end) \(.name)"' | judge_jobs)"
      done
}

gitlab_cancel() { glab api -X POST "projects/:id/pipelines/$1/cancel" >/dev/null; }

gitlab_cancel_queued() {
  local job
  for job in $(glab api "projects/:id/pipelines/$1/jobs?per_page=100" \
    | jq -r '.[] | select(.status | IN("created","pending","waiting_for_resource","preparing","scheduled")) | .id'); do
    glab api -X POST "projects/:id/jobs/$job/cancel" >/dev/null
  done
}
