#!/usr/bin/env bats
# ci-stop.sh with fake gh, glab and hal2-cli-git: runs and pipelines are files in $fake.

setup() {
  here="$BATS_TEST_DIRNAME"
  tmp="$(cd "$(mktemp -d)" && pwd -P)"
  fake="$tmp/fake"
  mkdir -p "$fake/bin"
  export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t
  export FASTLANE_PLAIN=1 FAKE="$fake" PATH="$fake/bin:$PATH"
  # The fake on PATH answers, never the caller's own program: a gate run with HAL2_CLI_GIT set (a local round) would
  # hand ci-stop.sh the installed hal2-cli-git, which then orders and stops in the scratch repository for real.
  unset HAL2_CLI_GIT
  git init -q -b main "$tmp/main"
  git -C "$tmp/main" commit -q --allow-empty -m init
  git -C "$tmp/main" worktree add -q -b 07 "$tmp/wt/07"
  cd "$tmp/wt/07"
  mkdir -p .hal
  printf 'PROVIDER=github\nLAND_WORKFLOWS=land.yml\nSHIP_GRACE=0m\n' > .hal/mtm-fastlane.conf
  : > "$fake/runs"
  # A run is a line `<id> <ref> <status> [<workflow file>]` of $FAKE/runs (no file: land.yml) and is listed only
  # under its own workflow file. A file named in $FAKE/unknown gets GitHub's 404 (gh 2.92's words), one named in
  # $FAKE/broken another failure. GitHub before the renames: it knows neither merge-to-main.yml nor
  # dev-merge-to-main.yml.
  # A run's jobs are gh's JSON in $FAKE/jobs-<id>, read with the script's own --jq; its attempt is 1, or what
  # $FAKE/attempt-<id> says. A cancel ends its run at once;
  # with $FAKE/linger (a number) a run only notes the request and every run ends after that many rounds (lists of
  # a known workflow file). $FAKE/refuses: the cancel fails.
  printf '%s\n' merge-to-main.yml dev-merge-to-main.yml > "$fake/unknown"
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
    echo "$workflow" >> "$FAKE/rounds"
    if [ -e "$FAKE/linger" ] && [ "$(grep -cx "$workflow" "$FAKE/rounds")" -gt "$(cat "$FAKE/linger")" ]; then
      awk '{$3 = "completed"} {print}' "$FAKE/runs" > "$FAKE/runs.new" && mv "$FAKE/runs.new" "$FAKE/runs"
    fi
    awk -v w="$workflow" '$3 != "completed" && ($4 == "" ? "land.yml" : $4) == w {print $1, $2}' "$FAKE/runs" \
      | while read -r id ref; do echo "$id $ref $(cat "$FAKE/attempt-$id" 2>/dev/null || echo 1)"; done ;;
  "run view")
    filter="" prev=""
    for arg in "$@"; do
      if [ "$prev" = --jq ]; then filter=$arg; fi
      prev=$arg
    done
    jq -r "$filter" "$FAKE/jobs-$3" ;;
  "run cancel") echo "$3" >> "$FAKE/cancelled"
    [ ! -e "$FAKE/refuses" ] || { echo "HTTP 500: Server Error" >&2; exit 1; }
    [ ! -e "$FAKE/linger" ] || exit 0
    awk -v id="$3" '$1 == id {$3 = "completed"} {print}' "$FAKE/runs" > "$FAKE/runs.new" && mv "$FAKE/runs.new" "$FAKE/runs" ;;
esac
EOF
  chmod +x "$fake/bin/gh"
}

teardown() { rm -rf "$tmp"; }

# jobs <job>...: gh's `run view --json jobs` of jobs given as `<status> <conclusion or none> <name>`.
jobs() {
  printf '%s\n' "$@" | jq -R 'capture("^(?<status>\\S+) (?<conclusion>\\S+) (?<name>.+)$")
    | .conclusion |= (if . == "none" then "" else . end) | .steps = []' | jq -s '{jobs: .}'
}

# run_on <id> <ref> <job>...: an unfinished run of land.yml.
run_on() { echo "$1 $2 in_progress" >> "$fake/runs"; jobs "${@:3}" > "$fake/jobs-$1"; }

# run_under <workflow file> <id> <ref> <job>...: an unfinished run of that workflow file.
run_under() { echo "$2 $3 in_progress $1" >> "$fake/runs"; jobs "${@:4}" > "$fake/jobs-$2"; }

# step_of <id> <job name> <conclusion> [<step>] [<status>]: one more step of that job, by default the gate jobs' stop
# step; its status as gh gives it (`completed`, or `pending` and `in_progress` with the conclusion "").
step_of() {
  jq --arg job "$2" --arg c "$3" --arg step "${4:-[19] fail fast: stop the run}" --arg s "${5:-completed}" \
    '(.jobs[] | select(.name == $job) | .steps) += [{name: $step, conclusion: $c, status: $s}]' "$fake/jobs-$1" \
    > "$fake/new"
  mv "$fake/new" "$fake/jobs-$1"
}

# The runs gh was asked to cancel, sorted, a request each.
requests() { sort "$fake/cancelled" 2>/dev/null | paste -sd ' ' -; }

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

@test "github: a run unfinished over three rounds gets one request, two runs one each" {
  echo 3 > "$fake/linger"
  run_on 41 land/03 "in_progress none 02-hz01-host-b/rust-test" "queued none 05-x-host-x/merge"
  run_on 42 land/04 "queued none 05-x-host-x/merge"
  run bash "$here/ci-stop.sh" --interval 1
  [ "$status" -eq 0 ]
  [ "$(grep -cx land.yml "$fake/rounds")" -eq 4 ] # three rounds unfinished, the fourth finds them ended
  [ "$(requests)" = "41 42" ]
  [ "$(grep -c "waiting for run 41 (land/03) to end: it was asked to cancel" <<<"$output")" -eq 1 ]
  [ "$(echo "$output" | tail -1 | jq -c '[.cancelled, .ending]')" = "[[41,42],[]]" ]
}

@test "github: a run asked by an earlier call, also one whose request failed, is not asked again" {
  echo 2 > "$fake/linger"
  run_on 43 land/03 "in_progress none 02-hz01-host-b/rust-test"
  run bash "$here/ci-stop.sh" --max-wait 0m --interval 1
  [ "$status" -eq 7 ]
  run bash "$here/ci-stop.sh" --interval 1
  [ "$status" -eq 0 ]
  [ "$(requests)" = 43 ]
  [ "$(echo "$output" | tail -1 | jq -c '[.cancelled, .ending]')" = "[[],[43]]" ]
  rm "$fake/rounds"
  : > "$fake/refuses"
  run_on 44 land/04 "in_progress none 02-hz01-host-b/rust-test"
  run bash "$here/ci-stop.sh" --interval 1
  [ "$status" -eq 1 ]
  [[ "$output" == *"cancelling run 44 failed; it is not asked again"*"/mtm-fastlane/ci-stop/44.1.asked"* ]]
  run bash "$here/ci-stop.sh" --interval 1
  [ "$status" -eq 0 ]
  [ "$(requests)" = "43 44" ]
}

@test "github: a run started again, a new attempt under its old id, is asked once more" {
  run_on 43 land/03 "in_progress none 02-hz01-host-b/rust-test"
  run bash "$here/ci-stop.sh" --interval 1
  [ "$status" -eq 0 ]
  echo "43 land/03 in_progress" > "$fake/runs"
  echo 2 > "$fake/attempt-43"
  echo 2 > "$fake/linger"
  rm "$fake/rounds"
  run bash "$here/ci-stop.sh" --interval 1
  [ "$status" -eq 0 ]
  [ "$(requests)" = "43 43" ]
  [ "$(echo "$output" | tail -1 | jq -c '[.cancelled, .ending]')" = "[[43],[]]" ]
}

@test "github: a run its own fail fast is ending gets no request, the loop waits for its end" {
  echo 2 > "$fake/linger"
  # The stop step of a job ended success: that job asked GitHub. And a job that carries the step concluded cancelled.
  run_on 45 land/03 "in_progress none 02-hz01-host-a/python-test" "in_progress none 02-hz01-host-b/rust-test"
  step_of 45 02-hz01-host-a/python-test failure "[07] gate python-test"
  step_of 45 02-hz01-host-a/python-test success
  run_on 46 land/04 "completed cancelled 02-mac-host-a/bash-test" "in_progress none 03-mac-host-a/mac-vm-park"
  step_of 46 02-mac-host-a/bash-test skipped " [08]  fail fast: stop the run "
  run bash "$here/ci-stop.sh" --interval 1
  [ "$status" -eq 0 ]
  [ ! -e "$fake/cancelled" ]
  [ "$(grep -cx land.yml "$fake/rounds")" -eq 3 ]
  [ "$(grep -c "run 45 (land/03) ends by itself" <<<"$output")" -eq 1 ]
  [ "$(echo "$output" | tail -1 | jq -c '[.cancelled, .ending]')" = "[[],[45,46]]" ]
  [ "$(grep -c "^run view 45 " "$fake/gh-calls")" -eq 3 ] # a look per round for the list, one for the ending
}

@test "github: only its own fail fast spares a run: any other cancelled job, a refused stop step, no step: asked" {
  echo 2 > "$fake/linger"
  run_on 47 land/03 "completed cancelled 02-az01-host-a/rust-test-windows" "in_progress none 02-hz01-host-b/rust-test"
  step_of 47 02-hz01-host-b/rust-test "" # cancelled at its own limit, without the step; a gate job still at work
  run_on 48 land/04 "completed failure 02-hz01-host-a/python-test" "in_progress none 02-hz01-host-b/rust-test"
  step_of 48 02-hz01-host-a/python-test failure # it ran, GitHub refused: nothing is cancelling the run
  step_of 48 02-hz01-host-b/rust-test skipped
  run_on 49 land/05 "completed cancelled 02-hz01-host-a/python-test" "in_progress none 02-hz01-host-b/rust-test"
  step_of 49 02-hz01-host-a/python-test cancelled "[19] fail fast: stop the run later" # another step's name
  run bash "$here/ci-stop.sh" --interval 1
  [ "$status" -eq 0 ]
  [ "$(requests)" = "47 48 49" ]
}

@test "github: a run whose stop step still runs is ending and gets no request, one whose stop step is still to come is asked" {
  echo 2 > "$fake/linger"
  # The review of the fix round, 1: the step runs only in a job that failed or hit its limit, and its request is on
  # its way in these seconds. A look that asked now would send the run's second request.
  run_on 55 land/03 "in_progress none 02-hz01-host-a/python-test" "in_progress none 02-hz01-host-b/rust-test"
  step_of 55 02-hz01-host-a/python-test failure "[07] gate python-test"
  step_of 55 02-hz01-host-a/python-test "" "[20] fail fast: stop the run" in_progress
  step_of 55 02-hz01-host-b/rust-test "" "[20] fail fast: stop the run" pending
  # A failed step, the stop step not started: the job may yet find another job's stop and ask nothing. Not ending.
  run_on 56 land/04 "in_progress none 02-hz01-host-a/python-test"
  step_of 56 02-hz01-host-a/python-test failure "[07] gate python-test"
  step_of 56 02-hz01-host-a/python-test "" "[19] fail fast: why this job ended" in_progress
  step_of 56 02-hz01-host-a/python-test "" "[20] fail fast: stop the run" pending
  # Another step in progress is no stop step.
  run_on 57 land/05 "in_progress none 02-hz01-host-b/rust-test"
  step_of 57 02-hz01-host-b/rust-test "" "[07] gate rust-test" in_progress
  step_of 57 02-hz01-host-b/rust-test "" "[20] fail fast: stop the run" pending
  run bash "$here/ci-stop.sh" --interval 1
  [ "$status" -eq 0 ]
  [ "$(requests)" = "56 57" ]
  [ "$(grep -c "run 55 (land/03) ends by itself" <<<"$output")" -eq 1 ]
  [ "$(echo "$output" | tail -1 | jq -c '[.cancelled, .ending]')" = "[[56,57],[55]]" ]
}

@test "github: a failed job's hand-off and its stop job's cancel step make a run ending, a refused cancel step does not" {
  echo 2 > "$fake/linger"
  # Plan 0319, shaped like the proof's run: `bash-lint` ended failure, its stop step `success` is the hand-off (no
  # request); its lane's stop job `fail-fast-a` sends the one request in its own step.
  fail_and_hand_off() { # <run id>
    step_of "$1" 03-hz01-host-a/bash-lint failure "[07] gate bash-lint"
    step_of "$1" 03-hz01-host-a/bash-lint success "[21] fail fast: stop the run"
  }
  # 60: the hand-off alone, the stop job not started yet: ending, nobody asks a second request.
  run_on 60 land/03 "completed failure 03-hz01-host-a/bash-lint" "in_progress none 03-hz01-host-a/bash-test"
  fail_and_hand_off 60
  step_of 60 03-hz01-host-a/bash-test "" "[21] fail fast: stop the run" pending
  # 61: the stop job's cancel step runs; 62: it ended success and the run's jobs end cancelled: both ending.
  run_on 61 land/04 "completed failure 03-hz01-host-a/bash-lint" "in_progress none 03-hz01-host-a/fail-fast-a"
  fail_and_hand_off 61
  step_of 61 03-hz01-host-a/fail-fast-a "" "[02] fail fast: cancel the run" in_progress
  run_on 62 land/05 "completed failure 03-hz01-host-a/bash-lint" "completed cancelled 03-hz01-host-a/fail-fast-a" \
    "completed cancelled 03-hz01-host-a/bash-test"
  fail_and_hand_off 62
  step_of 62 03-hz01-host-a/fail-fast-a success "[02] fail fast: cancel the run"
  step_of 62 03-hz01-host-a/bash-test skipped "[21] fail fast: stop the run"
  # 63: the cancel step ended failure and no request is out: the hand-off alone is no ending, the run is asked.
  run_on 63 land/06 "completed failure 03-hz01-host-a/bash-lint" "completed failure 03-hz01-host-a/fail-fast-a" \
    "in_progress none 03-hz01-host-a/bash-test"
  fail_and_hand_off 63
  step_of 63 03-hz01-host-a/fail-fast-a failure "[02] fail fast: cancel the run"
  step_of 63 03-hz01-host-a/bash-test "" "[21] fail fast: stop the run" pending
  # 64: the same refusal, but a time-limit job asked from inside (its stop step success, a step cancelled): out.
  run_on 64 land/07 "completed failure 03-hz01-host-a/fail-fast-a" "completed cancelled 03-hz01-host-a/bash-test" \
    "in_progress none 03-hz01-host-b/rust-test"
  step_of 64 03-hz01-host-a/fail-fast-a failure "[02] fail fast: cancel the run"
  step_of 64 03-hz01-host-a/bash-test cancelled "[07] gate bash-test"
  step_of 64 03-hz01-host-a/bash-test success "[21] fail fast: stop the run"
  run bash "$here/ci-stop.sh" --interval 1
  [ "$status" -eq 0 ]
  [ "$(requests)" = 63 ]
  [ "$(echo "$output" | tail -1 | jq -c '[.cancelled, .ending]')" = "[[63],[60,61,62,64]]" ]
}

@test "github: dry-run names an ending run and one asked before, and asks neither" {
  run_on 50 land/03 "completed cancelled 02-mac-host-a/bash-test"
  step_of 50 02-mac-host-a/bash-test success
  run_on 51 land/04 "queued none merge"
  run_on 52 land/05 "queued none merge"
  mkdir -p "$(git rev-parse --git-common-dir)/mtm-fastlane/ci-stop"
  : > "$(git rev-parse --git-common-dir)/mtm-fastlane/ci-stop/52.1.asked"
  run bash "$here/ci-stop.sh" --dry-run
  [ "$status" -eq 0 ]
  [[ "$output" == *"run 50 (land/03) ends by itself"* ]]
  [[ "$output" == *"would cancel run 51"* ]]
  [[ "$output" == *"waiting for run 52 (land/05) to end: it was asked to cancel"* ]]
  [ ! -e "$fake/cancelled" ]
  [ ! -e "$(git rev-parse --git-common-dir)/mtm-fastlane/ci-stop/51.1.asked" ]
}

@test "github: a merged run gets no request while a job of it runs, and one after the grace however long it ends" {
  echo 3 > "$fake/linger"
  run_on 53 land/05 "completed success 05-x-host-x/merge" "in_progress none 06-mac-host-a/deliver"
  run bash "$here/ci-stop.sh" --interval 1
  [ "$status" -eq 0 ]
  [ ! -e "$fake/cancelled" ]
  [ "$(echo "$output" | tail -1 | jq -c '[.cancelled, .ending, .waited]')" = "[[],[],[53]]" ]
  rm "$fake/rounds"
  run_on 54 land/06 "completed success 05-x-host-x/merge" "queued none 06-mac-host-a/deliver"
  run bash "$here/ci-stop.sh" --interval 1
  [ "$status" -eq 0 ]
  [ "$(grep -cx land.yml "$fake/rounds")" -eq 4 ]
  [ "$(requests)" = 54 ]
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
  run_on 15 land/06 "completed success 05-x-host-x/merge" "queued none 06-mac-host-a/deliver"
  printf 'PROVIDER=github\nLAND_WORKFLOWS=land.yml\nSHIP_GRACE=15m\n' > .hal/mtm-fastlane.conf
  run bash "$here/ci-stop.sh" --max-wait 0m --interval 1
  [ "$status" -eq 7 ]
  [ ! -e "$fake/cancelled" ]
}

@test "github: the merge job named with its position in its lane (plan 0349 D40) is the merge too" {
  run_on 17 land/06 "completed success 03-hz01-host-b/01-merge" "queued none 04-mac-host-a/01-git-pull-main"
  printf 'PROVIDER=github\nLAND_WORKFLOWS=land.yml\nSHIP_GRACE=15m\n' > .hal/mtm-fastlane.conf
  run bash "$here/ci-stop.sh" --max-wait 0m --interval 1
  [ "$status" -eq 7 ]
  [ ! -e "$fake/cancelled" ]
}

@test "github: a run whose positioned merge job has not run is cancelled" {
  run_on 18 land/07 "completed failure 03-hz01-host-a/01-stack-test" "queued none 03-hz01-host-b/01-merge"
  run bash "$here/ci-stop.sh" --interval 1
  [ "$status" -eq 0 ]
  [ "$(cat "$fake/cancelled")" = 18 ]
}

@test "github: a run whose merge job named by stage and runner code has not run is cancelled" {
  run_on 16 land/07 "completed failure 04-x-host-x/gate" "queued none 05-x-host-x/merge"
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
  printf '%s\n' land.yml dev-merge-to-main.yml > "$fake/unknown" # after the rename GitHub does not know land.yml
  run_under merge-to-main.yml 31 land/03 "completed failure 04-x-host-x/gate" "queued none 05-x-host-x/merge"
  run bash "$here/ci-stop.sh" --interval 1
  [ "$status" -eq 0 ]
  [ "$(cat "$fake/cancelled")" = 31 ]
  [ "$(asked)" = "dev-merge-to-main.yml land.yml merge-to-main.yml" ]
}

@test "github: unfinished runs of both workflow files are stopped, a merged one of either is waited for" {
  : > "$fake/unknown"
  run_on 32 land/04 "in_progress none 02-hz01-host-x/rust-test" "queued none 05-x-host-x/merge"
  run_under merge-to-main.yml 33 land/05 "queued none 05-x-host-x/merge"
  run_under merge-to-main.yml 34 land/06 "completed success 05-x-host-x/merge" "in_progress none 06-mac-host-a/deliver"
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
  [ "$(asked)" = "dev-merge-to-main.yml land.yml merge-to-main.yml" ]
  [ ! -e "$fake/cancelled" ]
}

@test "github: GitHub knows neither land workflow: nothing is known, exit 1" {
  printf '%s\n' dev-merge-to-main.yml merge-to-main.yml land.yml > "$fake/unknown"
  run bash "$here/ci-stop.sh" --interval 1
  [ "$status" -eq 1 ]
  [[ "$output" == *"GitHub knows none of the land workflows (land.yml dev-merge-to-main.yml merge-to-main.yml)"* ]]
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
  [[ "$output" == *"no land workflow (LAND_WORKFLOWS, .github/workflows/dev-merge-to-main.yml, merge-to-main.yml or land.yml)"* ]]
  [ ! -e "$fake/gh-calls" ]
}

@test "github: without LAND_WORKFLOWS, only land.yml in the worktree: both names are asked, a merge-to-main.yml run is stopped" {
  printf 'PROVIDER=github\n' > .hal/mtm-fastlane.conf
  commit_workflow land.yml
  [ "$(workflows)" = "land.yml dev-merge-to-main.yml merge-to-main.yml" ]
  : > "$fake/unknown" # main was renamed meanwhile: GitHub knows both, the running landing is under the new name
  run_under merge-to-main.yml 37 land/03 "queued none 05-x-host-x/merge"
  run bash "$here/ci-stop.sh" --interval 1
  [ "$status" -eq 0 ]
  [ "$(cat "$fake/cancelled")" = 37 ]
}

@test "github: without LAND_WORKFLOWS, only merge-to-main.yml in the worktree: both names are asked, a land.yml run is stopped" {
  printf 'PROVIDER=github\n' > .hal/mtm-fastlane.conf
  commit_workflow merge-to-main.yml
  [ "$(workflows)" = "merge-to-main.yml dev-merge-to-main.yml land.yml" ]
  : > "$fake/unknown" # the worktree renames it: main's running landing is still under the old name
  run_on 38 land/04 "queued none merge"
  run bash "$here/ci-stop.sh" --interval 1
  [ "$status" -eq 0 ]
  [ "$(cat "$fake/cancelled")" = 38 ]
}

@test "github: without LAND_WORKFLOWS, only dev-merge-to-main.yml in the worktree: every name is asked, its run is stopped" {
  printf 'PROVIDER=github\n' > .hal/mtm-fastlane.conf
  commit_workflow dev-merge-to-main.yml
  [ "$(workflows)" = "dev-merge-to-main.yml merge-to-main.yml land.yml" ]
  echo land.yml > "$fake/unknown" # after both renames: GitHub knows the two newer names
  run_under dev-merge-to-main.yml 39 land/05 "queued none 05-x-host-x/merge"
  run_under merge-to-main.yml 40 land/06 "queued none 05-x-host-x/merge"
  run bash "$here/ci-stop.sh" --interval 1
  [ "$status" -eq 0 ]
  [ "$(sort "$fake/cancelled" | paste -sd ' ' -)" = "39 40" ]
}

@test "github: the land workflows are the conf's, else the names found; one of them brings the others" {
  printf 'PROVIDER=github\n' > .hal/mtm-fastlane.conf
  commit_workflow merge-to-main.yml
  commit_workflow land.yml
  [ "$(workflows)" = "merge-to-main.yml land.yml dev-merge-to-main.yml" ]
  printf 'PROVIDER=github\nLAND_WORKFLOWS=land.yml\n' > .hal/mtm-fastlane.conf
  [ "$(workflows)" = "land.yml dev-merge-to-main.yml merge-to-main.yml" ]
  printf 'PROVIDER=github\nLAND_WORKFLOWS="merge-to-main.yml local-macos-26-macbook-18.4.yml"\n' > .hal/mtm-fastlane.conf
  [ "$(workflows)" = "merge-to-main.yml local-macos-26-macbook-18.4.yml dev-merge-to-main.yml land.yml" ]
  printf 'PROVIDER=github\nLAND_WORKFLOWS=.github/workflows/land.yml\n' > .hal/mtm-fastlane.conf
  [ "$(workflows)" = ".github/workflows/land.yml dev-merge-to-main.yml merge-to-main.yml" ]
  printf 'PROVIDER=github\nLAND_WORKFLOWS=dev-merge-to-main.yml\n' > .hal/mtm-fastlane.conf
  [ "$(workflows)" = "dev-merge-to-main.yml merge-to-main.yml land.yml" ]
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
  [ "$(workflows)" = "merge-to-main.yml dev-merge-to-main.yml land.yml" ]
}
