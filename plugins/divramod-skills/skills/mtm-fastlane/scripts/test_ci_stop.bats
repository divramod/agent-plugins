#!/usr/bin/env bats
# ci-stop.sh with fake gh, glab and hal2-cli-git: runs and pipelines are files in $fake.

setup() {
  here="$BATS_TEST_DIRNAME"
  tmp="$(cd "$(mktemp -d)" && pwd -P)"
  fake="$tmp/fake"
  mkdir -p "$fake/bin"
  export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t
  export FASTLANE_PLAIN=1 FAKE="$fake" PATH="$fake/bin:$PATH"
  git init -q -b main "$tmp/main"
  git -C "$tmp/main" commit -q --allow-empty -m init
  git -C "$tmp/main" worktree add -q -b 07 "$tmp/wt/07"
  cd "$tmp/wt/07"
  mkdir -p .hal
  printf 'PROVIDER=github\nLAND_WORKFLOWS=land.yml\nSHIP_GRACE=0m\n' > .hal/mtm-fastlane.conf
  : > "$fake/runs"
  # A run is a line `<id> <ref> <status> [<workflow file>]` of $FAKE/runs (no file: land.yml) and is listed only
  # under its own workflow file. A file named in $FAKE/unknown gets GitHub's 404 (gh 2.92's words), one named in
  # $FAKE/broken another failure. GitHub before the rename: it does not know merge-to-main.yml.
  echo merge-to-main.yml > "$fake/unknown"
  cat > "$fake/bin/gh" <<'EOF'
#!/usr/bin/env bash
echo "$*" >> "$FAKE/gh-calls"
case "$1 $2" in
  "run list")
    workflow="" prev=""
    for arg in "$@"; do
      if [ "$prev" = --workflow ]; then workflow=$arg; fi
      prev=$arg
    done
    if grep -qx "$workflow" "$FAKE/unknown" 2>/dev/null; then
      echo "HTTP 404: workflow $workflow not found on the default branch (https://api.github.com/repos/o/r/actions/workflows/$workflow)" >&2
      exit 1
    fi
    if grep -qx "$workflow" "$FAKE/broken" 2>/dev/null; then
      echo "HTTP 502: Bad Gateway (https://api.github.com/repos/o/r/actions/workflows/$workflow)" >&2
      exit 1
    fi
    awk -v w="$workflow" '$3 != "completed" && ($4 == "" ? "land.yml" : $4) == w {print $1, $2}' "$FAKE/runs" ;;
  "run view") cat "$FAKE/jobs-$3" ;;
  "run cancel") echo "$3" >> "$FAKE/cancelled"
    awk -v id="$3" '$1 == id {$3 = "completed"} {print}' "$FAKE/runs" > "$FAKE/runs.new" && mv "$FAKE/runs.new" "$FAKE/runs" ;;
esac
EOF
  chmod +x "$fake/bin/gh"
}

teardown() { rm -rf "$tmp"; }

run_on() { echo "$1 $2 in_progress" >> "$fake/runs"; printf '%s\n' "${@:3}" > "$fake/jobs-$1"; }

# run_under <workflow file> <id> <ref> <job>...: an unfinished run of that workflow file.
run_under() { echo "$2 $3 in_progress $1" >> "$fake/runs"; printf '%s\n' "${@:4}" > "$fake/jobs-$2"; }

# The lists gh was asked for, a workflow file per line.
asked() { sed -n 's/^run list --workflow \([^ ]*\) .*/\1/p' "$fake/gh-calls" 2>/dev/null | sort -u | paste -sd ' ' -; }

# github_workflows of ci-providers.sh in this worktree, with the conf as it is.
workflows() {
  (
    FASTLANE_HERE="$here" dir=.
    . "$here/fastlane-lib.sh"
    . "$here/ci-providers.sh"
    repo_paths
    github_workflows
  )
}

# A workflow file committed in the worktree.
commit_workflow() {
  mkdir -p .github/workflows
  echo "on: {push: {branches: ['land/**']}}" > ".github/workflows/$1"
  git add .github && git commit -q -m "$1"
}

# A PATH directory with every tool of /usr/bin and /bin except gh: a Linux runner has gh in /usr/bin itself.
path_without_gh() {
  local dir=$1 d f
  mkdir -p "$dir"
  for d in /usr/bin /bin; do
    for f in "$d"/*; do
      [ "${f##*/}" = gh ] || [ -e "$dir/${f##*/}" ] || ln -s "$f" "$dir/${f##*/}"
    done
  done
}

@test "github: a run that has not merged is cancelled" {
  run_on 11 land/03 "completed failure gate" "queued none merge"
  run bash "$here/ci-stop.sh" --interval 1
  [ "$status" -eq 0 ]
  [ "$(cat "$fake/cancelled")" = 11 ]
  [ "$(echo "$output" | tail -1 | jq -c .cancelled)" = "[11]" ]
}

@test "github: a merged run's queued jobs are cancelled after the grace, not before" {
  run_on 12 land/04 "completed success linux / merge" "queued none mac-host-ship / deliver"
  printf 'PROVIDER=github\nLAND_WORKFLOWS=land.yml\nSHIP_GRACE=15m\n' > .hal/mtm-fastlane.conf
  run bash "$here/ci-stop.sh" --max-wait 0m --interval 1
  [ "$status" -eq 7 ]
  [ ! -e "$fake/cancelled" ]
  printf 'PROVIDER=github\nLAND_WORKFLOWS=land.yml\nSHIP_GRACE=0m\n' > .hal/mtm-fastlane.conf
  run bash "$here/ci-stop.sh" --interval 1
  [ "$status" -eq 0 ]
  [ "$(cat "$fake/cancelled")" = 12 ]
  [ "$(echo "$output" | tail -1 | jq -c .waited)" = "[12]" ]
}

@test "github: the merge job named by its stage and runner code (plan 0260) is the merge, its ship jobs wait for the grace" {
  run_on 15 land/06 "completed success 05-xxx1hx/merge" "queued none 06-lmm1ha/deliver"
  printf 'PROVIDER=github\nLAND_WORKFLOWS=land.yml\nSHIP_GRACE=15m\n' > .hal/mtm-fastlane.conf
  run bash "$here/ci-stop.sh" --max-wait 0m --interval 1
  [ "$status" -eq 7 ]
  [ ! -e "$fake/cancelled" ]
}

@test "github: a run whose merge job named by stage and runner code has not run is cancelled" {
  run_on 16 land/07 "completed failure 04-xxx1hx/gate" "queued none 05-xxx1hx/merge"
  run bash "$here/ci-stop.sh" --interval 1
  [ "$status" -eq 0 ]
  [ "$(cat "$fake/cancelled")" = 16 ]
}

@test "github: a merged run with a started job is waited for, never cancelled" {
  run_on 13 land/05 "completed success merge" "in_progress none ship"
  run bash "$here/ci-stop.sh" --max-wait 0m --interval 1
  [ "$status" -eq 7 ]
  [[ "$output" == *"waiting for run 13"* ]]
  [ ! -e "$fake/cancelled" ]
}

@test "dry-run cancels nothing and stops no landing" {
  run_on 14 land/03 "queued none merge"
  cat > "$fake/bin/hal2-cli-git" <<'EOF'
#!/usr/bin/env bash
[ "$1" = --help ] && { echo '--local'; exit 0; }
[ "$*" = "worktree queue --json" ] && { cat "$FAKE/queue.json"; exit 0; }
echo "$*" >> "$FAKE/hal2-args"
EOF
  chmod +x "$fake/bin/hal2-cli-git"
  echo "{\"queue\":[{\"holding\":true,\"slot\":\"02\",\"worktree\":\"$tmp/wt/02\"}],\"priority\":null}" > "$fake/queue.json"
  run env FASTLANE_PLAIN=0 bash "$here/ci-stop.sh" --dry-run
  [ "$status" -eq 0 ]
  [[ "$output" == *"would cancel run 14"* ]]
  [[ "$output" == *"would stop the landing of 02"* ]]
  [ ! -e "$fake/cancelled" ]
  [ ! -e "$fake/hal2-args" ]
}

@test "hal2: this slot goes first, the holder's landing is stopped" {
  cat > "$fake/bin/hal2-cli-git" <<'EOF'
#!/usr/bin/env bash
[ "$1" = --help ] && { echo '--local'; exit 0; }
[ "$*" = "worktree queue --json" ] && { cat "$FAKE/queue.json"; exit 0; }
echo "$*" >> "$FAKE/hal2-args"
EOF
  chmod +x "$fake/bin/hal2-cli-git"
  echo "{\"queue\":[{\"holding\":true,\"slot\":\"02\",\"worktree\":\"$tmp/wt/02\"}],\"priority\":{\"slots\":[\"12\",\"07\"]}}" > "$fake/queue.json"
  run env FASTLANE_PLAIN=0 bash "$here/ci-stop.sh" --interval 1
  [ "$status" -eq 0 ]
  [ "$(sed -n 1p "$fake/hal2-args")" = "worktree queue order 07 12 --json" ]
  [ "$(sed -n 2p "$fake/hal2-args")" = "worktree stop 02 --json" ]
  [ "$(echo "$output" | tail -1 | jq -c .stopped_slots)" = '["02"]' ]
}

@test "gitlab: land pipelines only; unmerged cancelled, a merged one's pending jobs after the grace" {
  printf 'PROVIDER=gitlab\nSHIP_GRACE=0m\n' > .hal/mtm-fastlane.conf
  cat > "$fake/pipelines.json" <<'EOF'
[{"id":21,"ref":"land/03","status":"running"},{"id":22,"ref":"land/04","status":"running"},
 {"id":23,"ref":"feature","status":"running"}]
EOF
  echo '[{"id":1,"status":"pending","name":"merge"}]' > "$fake/jobs-21.json"
  echo '[{"id":2,"status":"success","name":"merge"},{"id":3,"status":"pending","name":"deliver"}]' > "$fake/jobs-22.json"
  cat > "$fake/bin/glab" <<'EOF'
#!/usr/bin/env bash
if [ "$2" = -X ]; then
  echo "$4" >> "$FAKE/glab-cancelled"
  case "$4" in
    */pipelines/*/cancel) id=${4#*pipelines/}; id=${id%/cancel} ;;
    */jobs/3/cancel) id=22 ;;
  esac
  jq --argjson id "$id" 'map(if .id == $id then .status = "canceled" else . end)' "$FAKE/pipelines.json" > "$FAKE/p.new"
  mv "$FAKE/p.new" "$FAKE/pipelines.json"
  exit 0
fi
case "$2" in
  *pipelines/21/jobs*) cat "$FAKE/jobs-21.json" ;;
  *pipelines/22/jobs*) cat "$FAKE/jobs-22.json" ;;
  *pipelines\?*) cat "$FAKE/pipelines.json" ;;
esac
EOF
  chmod +x "$fake/bin/glab"
  run bash "$here/ci-stop.sh" --interval 1
  [ "$status" -eq 0 ]
  [ "$(cat "$fake/glab-cancelled")" = "$(printf 'projects/:id/pipelines/21/cancel\nprojects/:id/jobs/3/cancel')" ]
  [ "$(echo "$output" | tail -1 | jq -c .cancelled)" = "[21,22]" ]
}

@test "no provider: nothing to stop; a missing gh is exit 2" {
  printf 'SHIP_GRACE=0m\n' > .hal/mtm-fastlane.conf
  run bash "$here/ci-stop.sh"
  [ "$status" -eq 0 ]
  [ "$(echo "$output" | tail -1 | jq -r .provider)" = none ]
  printf 'PROVIDER=github\nLAND_WORKFLOWS=land.yml\n' > .hal/mtm-fastlane.conf
  path_without_gh "$tmp/bare"
  ln -sf "$(command -v git)" "$(command -v jq)" "$tmp/bare/"
  run env PATH="$tmp/bare" bash "$here/ci-stop.sh"
  [ "$status" -eq 2 ]
  [[ "$output" == *"gh is missing"* ]]
}

@test "github: a conf written before the rename (LAND_WORKFLOWS=land.yml) also stops merge-to-main.yml's runs" {
  echo land.yml > "$fake/unknown" # after the rename GitHub does not know land.yml
  run_under merge-to-main.yml 31 land/03 "completed failure 04-xxx1hx/gate" "queued none 05-xxx1hx/merge"
  run bash "$here/ci-stop.sh" --interval 1
  [ "$status" -eq 0 ]
  [ "$(cat "$fake/cancelled")" = 31 ]
  [ "$(asked)" = "land.yml merge-to-main.yml" ]
}

@test "github: unfinished runs of both workflow files are stopped, a merged one of either is waited for" {
  : > "$fake/unknown"
  run_on 32 land/04 "in_progress none 02-vhl1hx/rust-test" "queued none 05-xxx1hx/merge"
  run_under merge-to-main.yml 33 land/05 "queued none 05-xxx1hx/merge"
  run_under merge-to-main.yml 34 land/06 "completed success 05-xxx1hx/merge" "in_progress none 06-lmm1ha/deliver"
  run bash "$here/ci-stop.sh" --max-wait 0m --interval 1
  [ "$status" -eq 7 ]
  [ "$(sort "$fake/cancelled" | paste -sd ' ' -)" = "32 33" ]
  [[ "$output" == *"waiting for run 34 (land/06)"* ]]
}

@test "github: before the rename only land.yml has runs, merge-to-main.yml is asked and unknown" {
  run_on 35 land/03 "queued none merge"
  run bash "$here/ci-stop.sh" --dry-run
  [ "$status" -eq 0 ]
  [[ "$output" == *"would cancel run 35"* ]]
  [ "$(asked)" = "land.yml merge-to-main.yml" ]
  [ ! -e "$fake/cancelled" ]
}

@test "github: GitHub knows neither land workflow: nothing is known, exit 1" {
  printf '%s\n' merge-to-main.yml land.yml > "$fake/unknown"
  run bash "$here/ci-stop.sh" --interval 1
  [ "$status" -eq 1 ]
  [[ "$output" == *"GitHub knows none of the land workflows (land.yml merge-to-main.yml)"* ]]
  [[ "$output" == *"listing the github land runs failed"* ]]
}

@test "github: a list failing for another reason than an unknown file is exit 1, whichever file it is" {
  : > "$fake/unknown"
  echo merge-to-main.yml > "$fake/broken"
  run_on 36 land/03 "queued none merge"
  run bash "$here/ci-stop.sh" --interval 1
  [ "$status" -eq 1 ]
  [[ "$output" == *"HTTP 502"* ]]
  [ ! -e "$fake/cancelled" ]
  echo land.yml > "$fake/broken"
  run bash "$here/ci-stop.sh" --interval 1
  [ "$status" -eq 1 ]
  [ ! -e "$fake/cancelled" ]
}

@test "github: without LAND_WORKFLOWS, neither workflow file: no land runs to stop, GitHub is not asked" {
  printf 'PROVIDER=github\n' > .hal/mtm-fastlane.conf
  [ -z "$(workflows)" ]
  run bash "$here/ci-stop.sh" --interval 1
  [ "$status" -eq 0 ]
  [[ "$output" == *"no land workflow (LAND_WORKFLOWS, .github/workflows/merge-to-main.yml or land.yml)"* ]]
  [ ! -e "$fake/gh-calls" ]
}

@test "github: without LAND_WORKFLOWS, only land.yml in the worktree: both names are asked, a merge-to-main.yml run is stopped" {
  printf 'PROVIDER=github\n' > .hal/mtm-fastlane.conf
  commit_workflow land.yml
  [ "$(workflows)" = "land.yml merge-to-main.yml" ]
  : > "$fake/unknown" # main was renamed meanwhile: GitHub knows both, the running landing is under the new name
  run_under merge-to-main.yml 37 land/03 "queued none 05-xxx1hx/merge"
  run bash "$here/ci-stop.sh" --interval 1
  [ "$status" -eq 0 ]
  [ "$(cat "$fake/cancelled")" = 37 ]
}

@test "github: without LAND_WORKFLOWS, only merge-to-main.yml in the worktree: both names are asked, a land.yml run is stopped" {
  printf 'PROVIDER=github\n' > .hal/mtm-fastlane.conf
  commit_workflow merge-to-main.yml
  [ "$(workflows)" = "merge-to-main.yml land.yml" ]
  : > "$fake/unknown" # the worktree renames it: main's running landing is still under the old name
  run_on 38 land/04 "queued none merge"
  run bash "$here/ci-stop.sh" --interval 1
  [ "$status" -eq 0 ]
  [ "$(cat "$fake/cancelled")" = 38 ]
}

@test "github: the land workflows are the conf's, else the two names found; one of the two brings the other" {
  printf 'PROVIDER=github\n' > .hal/mtm-fastlane.conf
  commit_workflow merge-to-main.yml
  commit_workflow land.yml
  [ "$(workflows)" = "merge-to-main.yml land.yml" ]
  printf 'PROVIDER=github\nLAND_WORKFLOWS=land.yml\n' > .hal/mtm-fastlane.conf
  [ "$(workflows)" = "land.yml merge-to-main.yml" ]
  printf 'PROVIDER=github\nLAND_WORKFLOWS="merge-to-main.yml hotfix.yml"\n' > .hal/mtm-fastlane.conf
  [ "$(workflows)" = "merge-to-main.yml hotfix.yml land.yml" ]
  printf 'PROVIDER=github\nLAND_WORKFLOWS=.github/workflows/land.yml\n' > .hal/mtm-fastlane.conf
  [ "$(workflows)" = ".github/workflows/land.yml merge-to-main.yml" ]
  printf 'PROVIDER=github\nLAND_WORKFLOWS="deploy.yml release.yml"\n' > .hal/mtm-fastlane.conf
  [ "$(workflows)" = "deploy.yml release.yml" ]
}

@test "github: without LAND_WORKFLOWS a workflow file only on origin's default branch counts" {
  printf 'PROVIDER=github\n' > .hal/mtm-fastlane.conf
  git init -q --bare -b main "$tmp/origin.git"
  git remote add origin "$tmp/origin.git"
  commit_workflow merge-to-main.yml
  git push -q origin HEAD:main
  git fetch -q origin
  git remote set-head origin main
  git reset -q --hard HEAD~1
  [ ! -e .github/workflows/merge-to-main.yml ]
  [ "$(workflows)" = "merge-to-main.yml land.yml" ]
}
