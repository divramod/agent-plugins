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
  cat > "$fake/bin/gh" <<'EOF'
#!/usr/bin/env bash
case "$1 $2" in
  "run list") awk '$3 != "completed" {print $1, $2}' "$FAKE/runs" ;;
  "run view") cat "$FAKE/jobs-$3" ;;
  "run cancel") echo "$3" >> "$FAKE/cancelled"
    awk -v id="$3" '$1 == id {$3 = "completed"} {print}' "$FAKE/runs" > "$FAKE/runs.new" && mv "$FAKE/runs.new" "$FAKE/runs" ;;
esac
EOF
  chmod +x "$fake/bin/gh"
}

teardown() { rm -rf "$tmp"; }

run_on() { echo "$1 $2 in_progress" >> "$fake/runs"; printf '%s\n' "${@:3}" > "$fake/jobs-$1"; }

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
