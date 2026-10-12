#!/usr/bin/env bats
# fastlane.sh and plain-land.sh against a scratch repository: a bare origin, its
# main checkout and a worktree slot 07; hal2-cli-git faked where it lands.

setup() {
  here="$BATS_TEST_DIRNAME"
  tmp="$(cd "$(mktemp -d)" && pwd -P)"
  export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t
  export FASTLANE_PLAIN=1 FASTLANE_POLL=1
  git init -q --bare -b main "$tmp/origin.git"
  git clone -q "$tmp/origin.git" "$tmp/main" 2>/dev/null
  cd "$tmp/main"
  mkdir -p .hal .github/workflows
  echo 'on: push' > .github/workflows/land.yml
  cat > .hal/mtm-fastlane-worktree.sh <<EOF
#!/usr/bin/env bash
echo "base=\$FASTLANE_BASE args=\$*" > "$tmp/worktree-ran"
[ ! -e "$tmp/red" ]
EOF
  cat > .hal/mtm-fastlane-main.sh <<EOF
#!/usr/bin/env bash
echo "pwd=\$(pwd -P) base=\$FASTLANE_BASE head=\$FASTLANE_HEAD" > "$tmp/main-ran"
[ ! -e "$tmp/red" ]
EOF
  chmod +x .hal/*.sh
  echo 'FINGERPRINT_INPUTS=".github/workflows/*.yml"' > .hal/mtm-fastlane.conf
  git add . && git commit -q -m init
  echo "FINGERPRINT=$(bash "$here/fastlane.sh" fingerprint)" >> .hal/mtm-fastlane.conf
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
  run bash "$here/fastlane.sh" preflight
  [ "$status" -eq 0 ]
  [[ "$output" == *"branch: 07"* ]]
  [[ "$output" == *"main checkout: $tmp/main"* ]]
  [[ "$output" == *"lands: plain git"* ]]
  [[ "$output" == *"fingerprint: current"* ]]
}

@test "preflight: a changed CI input makes the fingerprint stale, a warning only" {
  echo 'on: pull_request' > .github/workflows/land.yml && git commit -q -am ci
  run bash "$here/fastlane.sh" preflight
  [ "$status" -eq 0 ]
  [[ "$output" == *"fingerprint: stale"* ]]
}

@test "preflight: the main checkout and a missing script are not runnable" {
  run bash "$here/fastlane.sh" preflight "$tmp/main"
  [ "$status" -eq 1 ]
  [[ "$output" == *"the main checkout"* ]]
  git rm -q .hal/mtm-fastlane-main.sh && git commit -q -m gone
  run bash "$here/fastlane.sh" preflight
  [ "$status" -eq 1 ]
  [[ "$output" == *"run /mtm-fastlane configure"* ]]
}

@test "reserve: the lock is the worktree's, another waits until --max-wait (exit 7)" {
  run bash "$here/fastlane.sh" reserve
  [ "$status" -eq 0 ]
  run bash "$here/fastlane.sh" reserve
  [[ "$output" == *"(kept)"* ]]
  run bash "$here/fastlane.sh" reserve --max-wait 0m "$tmp/wt/08"
  [ "$status" -eq 7 ]
  run bash "$here/fastlane.sh" release "$tmp/wt/08"
  [ "$status" -eq 1 ]
  run bash "$here/fastlane.sh" release
  [ "$status" -eq 0 ]
  run bash "$here/fastlane.sh" reserve --max-wait 0m "$tmp/wt/08"
  [ "$status" -eq 0 ]
}

@test "land: plain git pushes the merge candidate, resets the worktree, pulls main, deletes side branches" {
  git branch 07-ui
  work a
  bash "$here/fastlane.sh" reserve
  before=$(git rev-parse origin/main)
  run bash "$here/fastlane.sh" land
  [ "$status" -eq 0 ]
  landed=$(git --git-dir "$tmp/origin.git" rev-parse main)
  [ "$(git rev-parse "$landed^1")" = "$before" ]
  [ "$(git rev-parse "$landed^{tree}")" = "$(git rev-parse "$landed^2^{tree}")" ]
  [ "$(git rev-parse HEAD)" = "$landed" ]
  [ "$(git -C "$tmp/main" rev-parse HEAD)" = "$landed" ]
  run git rev-parse -q --verify refs/heads/07-ui
  [ "$status" -ne 0 ]
  [ "$(cat "$(git rev-parse --git-common-dir)/mtm-fastlane/last")" = "$(printf 'base=%s\nhead=%s' "$before" "$landed")" ]
}

@test "land: without the lock it refuses, after main moved it is a conflict (exit 3)" {
  work a
  run bash "$here/fastlane.sh" land
  [ "$status" -eq 1 ]
  [[ "$output" == *"reserve first"* ]]
  (cd "$tmp/wt/08" && work b && git push -q origin HEAD:main)
  bash "$here/fastlane.sh" reserve
  run bash "$here/fastlane.sh" land
  [ "$status" -eq 3 ]
  git merge -q --no-edit origin/main
  run bash "$here/fastlane.sh" land
  [ "$status" -eq 0 ]
}

@test "checks: the worktree script gets the base and --dry-run; red is exit 1" {
  run bash "$here/fastlane.sh" checks --dry-run
  [ "$status" -eq 0 ]
  [ "$(cat "$tmp/worktree-ran")" = "base=origin/main args=--dry-run" ]
  touch "$tmp/red"
  run bash "$here/fastlane.sh" checks
  [ "$status" -eq 1 ]
}

@test "main: in the clean main checkout at the landed commit, else in .fastlane" {
  work a
  bash "$here/fastlane.sh" reserve
  bash "$here/fastlane.sh" land
  head=$(git rev-parse HEAD)
  run bash "$here/fastlane.sh" main
  [ "$status" -eq 0 ]
  [[ "$(cat "$tmp/main-ran")" == "pwd=$tmp/main base="*" head=$head" ]]
  touch "$tmp/main/dirty"
  run bash "$here/fastlane.sh" main
  [ "$status" -eq 0 ]
  [ "$(cat "$tmp/main-ran" | cut -d' ' -f1)" = "pwd=$tmp/wt/.fastlane" ]
  [ "$(git -C "$tmp/wt/.fastlane" rev-parse HEAD)" = "$head" ]
  touch "$tmp/red"
  run bash "$here/fastlane.sh" main
  [ "$status" -eq 1 ]
  [[ "$output" == *"the landing stays"* ]]
}

@test "hal2-cli-git lands with --local --keep-reserved; its exits map to the fastlane's" {
  mkdir -p "$tmp/bin"
  cat > "$tmp/bin/hal2-cli-git" <<EOF
#!/usr/bin/env bash
[ "\$1" = --help ] && { echo 'merge-to-main [--keep-reserved] [--local]'; exit 0; }
echo "\$*" >> "$tmp/hal2-args"
exit \$(cat "$tmp/hal2-exit" 2>/dev/null || echo 0)
EOF
  chmod +x "$tmp/bin/hal2-cli-git"
  export FASTLANE_PLAIN=0 HAL2_CLI_GIT="$tmp/bin/hal2-cli-git"
  run bash "$here/fastlane.sh" preflight
  [[ "$output" == *"lands: hal2-cli-git"* ]]
  run bash "$here/fastlane.sh" land --max-wait 2h
  [ "$status" -eq 0 ]
  grep -qx 'worktree merge-to-main --local --keep-reserved --max-wait 120m --json' "$tmp/hal2-args"
  echo 4 > "$tmp/hal2-exit"
  run bash "$here/fastlane.sh" land
  [ "$status" -eq 1 ]
  echo 6 > "$tmp/hal2-exit"
  run bash "$here/fastlane.sh" reserve
  [ "$status" -eq 7 ]
  grep -qx 'worktree reserve --max-wait 60m --json' "$tmp/hal2-args"
}

@test "usage errors exit 64" {
  run bash "$here/fastlane.sh" nonsense
  [ "$status" -eq 64 ]
  run bash "$here/fastlane.sh" reserve --max-wait soon
  [ "$status" -eq 64 ]
}
