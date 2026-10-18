#!/usr/bin/env bats
# smuggle.sh and plain-land.sh against a scratch repository: a bare origin, its
# main checkout and a worktree 07; hal2-cli-git faked where it lands.

setup() {
  here="$BATS_TEST_DIRNAME"
  tmp="$(cd "$(mktemp -d)" && pwd -P)"
  export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t
  export SMUGGLE_PLAIN=1 SMUGGLE_POLL=1
  git init -q --bare -b main "$tmp/origin.git"
  git clone -q "$tmp/origin.git" "$tmp/main" 2>/dev/null
  cd "$tmp/main"
  mkdir -p .hal .github/workflows
  echo 'on: push' > .github/workflows/merge-to-main.yml
  cat > .hal/smuggle-worktree.sh <<EOF
#!/usr/bin/env bash
echo "base=\$SMUGGLE_BASE args=\$*" > "$tmp/worktree-ran"
[ ! -e "$tmp/red" ]
EOF
  cat > .hal/smuggle-main.sh <<EOF
#!/usr/bin/env bash
echo "pwd=\$(pwd -P) base=\$SMUGGLE_BASE head=\$SMUGGLE_HEAD" > "$tmp/main-ran"
[ ! -e "$tmp/red" ]
EOF
  chmod +x .hal/*.sh
  echo 'FINGERPRINT_INPUTS=".github/workflows/*.yml"' > .hal/smuggle.conf
  git add . && git commit -q -m init
  echo "FINGERPRINT=$(bash "$here/smuggle.sh" fingerprint)" >> .hal/smuggle.conf
  git commit -q -am fingerprint
  git push -q origin HEAD:main
  git remote set-head origin main
  mkdir -p "$tmp/wt"
  git worktree add -q -b 07 "$tmp/wt/07"
  git worktree add -q -b 08 "$tmp/wt/08"
  cd "$tmp/wt/07"
}

teardown() { rm -rf "$tmp"; }

work() { echo "$1" > "$1.txt" && git add "$1.txt" && git commit -q -m "$1"; }

@test "preflight: a worktree with both scripts and a current fingerprint" {
  run bash "$here/smuggle.sh" preflight
  [ "$status" -eq 0 ]
  [[ "$output" == *"branch: 07"* ]]
  [[ "$output" == *"main checkout: $tmp/main"* ]]
  [[ "$output" == *"lands: plain git"* ]]
  [[ "$output" == *"smuggle: no hal2-cli-git --smuggle here"* ]]
  [[ "$output" == *"fingerprint: current"* ]]
}

@test "preflight: a changed CI input makes the fingerprint stale, a warning only" {
  echo 'on: pull_request' > .github/workflows/merge-to-main.yml && git commit -q -am ci
  run bash "$here/smuggle.sh" preflight
  [ "$status" -eq 0 ]
  [[ "$output" == *"fingerprint: stale"* ]]
}

@test "preflight: the main checkout and a missing script are not runnable" {
  run bash "$here/smuggle.sh" preflight "$tmp/main"
  [ "$status" -eq 1 ]
  [[ "$output" == *"the main checkout"* ]]
  git rm -q .hal/smuggle-main.sh && git commit -q -m gone
  run bash "$here/smuggle.sh" preflight
  [ "$status" -eq 1 ]
  [[ "$output" == *"run /smuggle configure"* ]]
}

@test "reserve: the lock is the worktree's, another waits until --max-wait (exit 7)" {
  run bash "$here/smuggle.sh" reserve
  [ "$status" -eq 0 ]
  run bash "$here/smuggle.sh" reserve
  [[ "$output" == *"(kept)"* ]]
  run bash "$here/smuggle.sh" reserve --max-wait 0m "$tmp/wt/08"
  [ "$status" -eq 7 ]
  run bash "$here/smuggle.sh" release "$tmp/wt/08"
  [ "$status" -eq 1 ]
  run bash "$here/smuggle.sh" release
  [ "$status" -eq 0 ]
  run bash "$here/smuggle.sh" reserve --max-wait 0m "$tmp/wt/08"
  [ "$status" -eq 0 ]
}

@test "land: plain git pushes the merge candidate, resets the worktree, pulls main, deletes side branches" {
  git branch 07-ui
  work a
  bash "$here/smuggle.sh" reserve
  before=$(git rev-parse origin/main)
  run bash "$here/smuggle.sh" land
  [ "$status" -eq 0 ]
  landed=$(git --git-dir "$tmp/origin.git" rev-parse main)
  [ "$(git rev-parse "$landed^1")" = "$before" ]
  [ "$(git rev-parse "$landed^{tree}")" = "$(git rev-parse "$landed^2^{tree}")" ]
  [ "$(git rev-parse HEAD)" = "$landed" ]
  [ "$(git -C "$tmp/main" rev-parse HEAD)" = "$landed" ]
  slot=$(basename "$PWD")  # the origin trailers (plan 0355): where it came from, and that CI was skipped
  [ "$(git log -1 --format='%(trailers:key=Worktree,valueonly)' "$landed" | head -n1)" = "$slot" ]
  [ "$(git log -1 --format='%(trailers:key=Smuggle,valueonly)' "$landed" | head -n1)" = "$slot" ]
  run git rev-parse -q --verify refs/heads/07-ui
  [ "$status" -ne 0 ]
  [ "$(cat "$(git rev-parse --git-common-dir)/smuggle/last")" = "$(printf 'base=%s\nhead=%s' "$before" "$landed")" ]
}

@test "land: without the lock it refuses, after main moved it is a conflict (exit 3)" {
  work a
  run bash "$here/smuggle.sh" land
  [ "$status" -eq 1 ]
  [[ "$output" == *"reserve first"* ]]
  (cd "$tmp/wt/08" && work b && git push -q origin HEAD:main)
  bash "$here/smuggle.sh" reserve
  run bash "$here/smuggle.sh" land
  [ "$status" -eq 3 ]
  git merge -q --no-edit origin/main
  run bash "$here/smuggle.sh" land
  [ "$status" -eq 0 ]
}

@test "checks: the worktree script gets the base and --dry-run; red is exit 1" {
  run bash "$here/smuggle.sh" checks --dry-run
  [ "$status" -eq 0 ]
  [ "$(cat "$tmp/worktree-ran")" = "base=origin/main args=--dry-run" ]
  touch "$tmp/red"
  run bash "$here/smuggle.sh" checks
  [ "$status" -eq 1 ]
}

@test "main: in the clean main checkout at the landed commit, else in .smuggle" {
  work a
  bash "$here/smuggle.sh" reserve
  bash "$here/smuggle.sh" land
  head=$(git rev-parse HEAD)
  run bash "$here/smuggle.sh" main
  [ "$status" -eq 0 ]
  [[ "$(cat "$tmp/main-ran")" == "pwd=$tmp/main base="*" head=$head" ]]
  touch "$tmp/main/dirty"
  run bash "$here/smuggle.sh" main
  [ "$status" -eq 0 ]
  [ "$(cat "$tmp/main-ran" | cut -d' ' -f1)" = "pwd=$tmp/wt/.smuggle" ]
  [ "$(git -C "$tmp/wt/.smuggle" rev-parse HEAD)" = "$head" ]
  touch "$tmp/red"
  run bash "$here/smuggle.sh" main
  [ "$status" -eq 1 ]
  [[ "$output" == *"the landing stays"* ]]
}

@test "preflight names the one call when hal2-cli-git has --smuggle" {
  mkdir -p "$tmp/bin"
  printf '#!/usr/bin/env bash\necho "merge-to-main [--local] [--smuggle]"\n' > "$tmp/bin/hal2-cli-git"
  chmod +x "$tmp/bin/hal2-cli-git"
  export SMUGGLE_PLAIN=0 HAL2_CLI_GIT="$tmp/bin/hal2-cli-git"
  run bash "$here/smuggle.sh" preflight
  [ "$status" -eq 0 ]
  [[ "$output" == *"smuggle: $tmp/bin/hal2-cli-git worktree merge-to-main --smuggle"* ]]
  SMUGGLE_PLAIN=1 run bash "$here/smuggle.sh" preflight
  [[ "$output" == *"smuggle: no hal2-cli-git --smuggle here"* ]]
}

@test "hal2-cli-git lands with --local --keep-reserved; its exits map to the smuggle's" {
  mkdir -p "$tmp/bin"
  cat > "$tmp/bin/hal2-cli-git" <<EOF
#!/usr/bin/env bash
[ "\$1" = --help ] && { echo 'merge-to-main [--keep-reserved] [--local]'; exit 0; }
echo "\$*" >> "$tmp/hal2-args"
exit \$(cat "$tmp/hal2-exit" 2>/dev/null || echo 0)
EOF
  chmod +x "$tmp/bin/hal2-cli-git"
  export SMUGGLE_PLAIN=0 HAL2_CLI_GIT="$tmp/bin/hal2-cli-git"
  run bash "$here/smuggle.sh" preflight
  [[ "$output" == *"lands: hal2-cli-git"* ]]
  run bash "$here/smuggle.sh" land --max-wait 2h
  [ "$status" -eq 0 ]
  grep -qx 'worktree merge-to-main --local --keep-reserved --max-wait 120m --json' "$tmp/hal2-args"
  echo 4 > "$tmp/hal2-exit"
  run bash "$here/smuggle.sh" land
  [ "$status" -eq 1 ]
  echo 6 > "$tmp/hal2-exit"
  run bash "$here/smuggle.sh" reserve
  [ "$status" -eq 7 ]
  grep -qx 'worktree reserve --max-wait 60m --json' "$tmp/hal2-args"
}

@test "usage errors exit 64" {
  run bash "$here/smuggle.sh" nonsense
  [ "$status" -eq 64 ]
  run bash "$here/smuggle.sh" reserve --max-wait soon
  [ "$status" -eq 64 ]
}

# hal2 plan 0360 step 19: the units of .hal/smuggle.toml (D49, D63) and who starts a smuggle (D53, D76).
units_list() {
  printf '[[unit]]\nname = "skills"\npaths = ["skills"]\nchecks = ["true"]\n' > "$tmp/main/.hal/smuggle.toml"
  git -C "$tmp/main" add .hal/smuggle.toml && git -C "$tmp/main" commit -q -m units
  git -C "$tmp/main" push -q origin HEAD:main
  git fetch -q origin && git merge -q origin/main
}

fake_cli() { # fake_cli <mode>: a hal2-cli-git for `queue mode --json` and `changes`
  mkdir -p "$tmp/bin"
  cat > "$tmp/bin/hal2-cli-git" <<EOF
#!/usr/bin/env bash
case "\$*" in
  "worktree queue mode --json") echo '{"mode":"$1","by":"user","at":null,"why":null}' ;;
  changes*) echo '{"jobs":[{"name":"rust-test","run":true},{"name":"bash-lint","run":false}]}' ;;
  *) exit 2 ;;
esac
EOF
  chmod +x "$tmp/bin/hal2-cli-git"
  export HAL2_CLI_GIT="$tmp/bin/hal2-cli-git"
}

@test "preflight: a change inside the units is no warning" {
  units_list
  mkdir -p skills && work skills/a
  run bash "$here/smuggle.sh" preflight
  [ "$status" -eq 0 ]
  [[ "$output" == *"units: skills"* ]]
  [[ "$output" != *"outside"* ]]
}

@test "preflight: a change outside the units warns with the CI jobs, exit 4; --yes-outside goes on" {
  units_list
  fake_cli production
  work core
  run bash "$here/smuggle.sh" preflight
  [ "$status" -eq 4 ]
  [[ "$output" == *"outside every unit of .hal/smuggle.toml"* ]]
  [[ "$output" == *"core.txt"* ]]
  [[ "$output" == *"CI would have run: rust-test"* ]]
  [[ "$output" == *"fingerprint: current"* ]]
  run bash "$here/smuggle.sh" preflight --yes-outside
  [ "$status" -eq 0 ]
  [[ "$output" == *"the user said yes"* ]]
}

@test "preflight --from-mtm: refused in production mode (exit 6), on in smuggle mode" {
  fake_cli production
  run bash "$here/smuggle.sh" preflight --from-mtm
  [ "$status" -eq 6 ]
  [[ "$output" == *"production mode"* ]]
  fake_cli smuggle
  run bash "$here/smuggle.sh" preflight --from-mtm
  [ "$status" -eq 0 ]
  [[ "$output" == *"started by: /mtm in smuggle mode"* ]]
  rm "$tmp/bin/hal2-cli-git"
  run bash "$here/smuggle.sh" preflight --from-mtm
  [ "$status" -eq 6 ]
}
