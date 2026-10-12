#!/usr/bin/env bats
# check.sh on the templates filled in a scratch repository.

setup() {
  here="$BATS_TEST_DIRNAME"
  tmp="$(cd "$(mktemp -d)" && pwd -P)"
  export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t
  git init -q -b main "$tmp/repo"
  cd "$tmp/repo"
  mkdir -p .hal .github/workflows code/rust
  echo 'on: push' > .github/workflows/land.yml
  git add . && git commit -q -m init
  fill "$here/templates/mtm-fastlane-worktree.sh" .hal/mtm-fastlane-worktree.sh \
    "if touches '^code/rust/'; then step rust-test cargo test; fi
skip linux-e2e \"needs Linux and Docker\""
  fill "$here/templates/mtm-fastlane-main.sh" .hal/mtm-fastlane-main.sh "step deliver true"
  fill "$here/templates/mtm-fastlane.conf" .hal/mtm-fastlane.conf ""
  chmod +x .hal/*.sh
  sed -i.bak "s|^FINGERPRINT=.*|FINGERPRINT=$(bash "$here/fastlane.sh" fingerprint)|" .hal/mtm-fastlane.conf
  rm .hal/*.bak
  git checkout -q -b feature
  echo 'fn main() {}' > code/rust/main.rs && git add . && git commit -q -m rust
}

teardown() { rm -rf "$tmp"; }

fill() { # fill <template> <out> <body>: the placeholders as configure fills them
  BODY="$3" awk '/^@CHECKS@$|^@STEPS@$/ {print ENVIRON["BODY"]; next} {print}' "$1" \
    | sed -e 's/@REPO@/repo/; s/@DATE@/2026-10-09/; s/@REPLACES@/land.yml rust-test/; s/@SKIPPED_NEEDS@/Linux/' \
      -e 's/@SKIPPED@/linux-e2e/; s/@CI_COMMAND@/gh workflow run land.yml/; s/@LAND_WORKFLOWS@/land.yml/' \
      -e 's|@FINGERPRINT_INPUTS@|.github/workflows/*|; s/@FINGERPRINT@/none/' > "$2"
}

@test "check: filled scripts pass and the dry-run lists what runs and what is skipped" {
  run bash "$here/check.sh"
  [ "$status" -eq 0 ]
  [[ "$output" == *"FASTLANE_BASE=HEAD"* ]] || [[ "$output" == *"FASTLANE_BASE=origin/main"* ]]
  [[ "$output" == *"skipped: linux-e2e (needs Linux and Docker)"* ]]
  [[ "$output" == *"would run: deliver"* ]]
  [ "$(echo "$output" | tail -1)" = ok ]
}

@test "check: the dry-run sees only what the branch changed" {
  git update-ref refs/remotes/origin/main main
  run bash "$here/check.sh"
  [ "$status" -eq 0 ]
  [[ "$output" == *"would run: rust-test"* ]]
  git update-ref refs/remotes/origin/main feature
  run bash "$here/check.sh"
  [[ "$output" != *"would run: rust-test"* ]]
}

@test "check: not executable, a syntax error, a placeholder and a stale fingerprint are problems" {
  chmod -x .hal/mtm-fastlane-main.sh
  echo 'if then' >> .hal/mtm-fastlane-worktree.sh
  echo '# @CHECKS@' >> .hal/mtm-fastlane-worktree.sh
  echo 'on: pull_request' > .github/workflows/land.yml && git commit -q -am ci
  run bash "$here/check.sh"
  [ "$status" -eq 1 ]
  [[ "$output" == *"mtm-fastlane-main.sh is not executable"* ]]
  [[ "$output" == *"mtm-fastlane-worktree.sh has a syntax error"* ]]
  [[ "$output" == *"template placeholders"* ]]
  [[ "$output" == *"FINGERPRINT is stale"* ]]
}

@test "check: missing scripts send to configure" {
  rm .hal/mtm-fastlane-main.sh
  run bash "$here/check.sh"
  [ "$status" -eq 1 ]
  [[ "$output" == *"run /mtm-fastlane configure"* ]]
}
