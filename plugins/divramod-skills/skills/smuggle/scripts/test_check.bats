#!/usr/bin/env bats
# check.sh on the templates filled in a scratch repository.

load test_helper

# The template (test_helper.bash): a repository with the filled scripts and conf, on the branch feature.
build() {
  here="$BATS_TEST_DIRNAME"
  git init -q -b main "$tmp/repo"
  cd "$tmp/repo" || return
  mkdir -p .hal .github/workflows code/rust
  echo 'on: push' > .github/workflows/merge-to-main.yml
  git add . && git commit -q -m init
  fill "$here/templates/smuggle-worktree.sh" .hal/smuggle-worktree.sh \
    "if touches '^code/rust/'; then step rust-test cargo test; fi
skip linux-e2e \"needs Linux and Docker\""
  fill "$here/templates/smuggle-main.sh" .hal/smuggle-main.sh "step deliver true"
  fill "$here/templates/smuggle.conf" .hal/smuggle.conf ""
  chmod +x .hal/*.sh
  sed -i.bak "s|^FINGERPRINT=.*|FINGERPRINT=$(bash "$here/smuggle.sh" fingerprint)|" .hal/smuggle.conf
  rm .hal/*.bak
  git checkout -q -b feature
  echo 'fn main() {}' > code/rust/main.rs && git add . && git commit -q -m rust
}

setup_file() {
  export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t
  tmp=$(fixture_dir)
  fixture_build build
}

setup() {
  here="$BATS_TEST_DIRNAME"
  tmp=$(fixture_dir)
  fixture_copy
  export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t
  cd "$tmp/repo" || return
}

teardown() { fixture_drop; }

fill() { # fill <template> <out> <body>: the placeholders as configure fills them
  BODY="$3" awk '/^@CHECKS@$|^@STEPS@$/ {print ENVIRON["BODY"]; next} {print}' "$1" \
    | sed -e 's/@REPO@/repo/; s/@DATE@/2026-10-09/; s/@REPLACES@/merge-to-main.yml rust-test/; s/@SKIPPED_NEEDS@/Linux/' \
      -e 's/@SKIPPED@/linux-e2e/; s/@CI_COMMAND@/gh workflow run merge-to-main.yml/; s/@LAND_WORKFLOWS@/merge-to-main.yml/' \
      -e 's|@FINGERPRINT_INPUTS@|.github/workflows/*|; s/@FINGERPRINT@/none/' > "$2"
}

@test "check: filled scripts pass and the dry-run lists what runs and what is skipped" {
  run bash "$here/check.sh"
  [ "$status" -eq 0 ]
  [[ "$output" == *"SMUGGLE_BASE=HEAD"* ]] || [[ "$output" == *"SMUGGLE_BASE=origin/main"* ]]
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
  chmod -x .hal/smuggle-main.sh
  echo 'if then' >> .hal/smuggle-worktree.sh
  echo '# @CHECKS@' >> .hal/smuggle-worktree.sh
  echo 'on: pull_request' > .github/workflows/merge-to-main.yml && git commit -q -am ci
  run bash "$here/check.sh"
  [ "$status" -eq 1 ]
  [[ "$output" == *"smuggle-main.sh is not executable"* ]]
  [[ "$output" == *"smuggle-worktree.sh has a syntax error"* ]]
  [[ "$output" == *"template placeholders"* ]]
  [[ "$output" == *"FINGERPRINT is stale"* ]]
}

@test "check: missing scripts send to configure" {
  rm .hal/smuggle-main.sh
  run bash "$here/check.sh"
  [ "$status" -eq 1 ]
  [[ "$output" == *"run /smuggle configure"* ]]
}

@test "check: the unit list, when there, must be filled and readable at HEAD" {
  run bash "$here/check.sh"
  [[ "$output" == *"note: no .hal/smuggle.toml"* ]]
  sed -e 's/@REPO@/repo/; s/@DATE@/2026-10-17/; s/@FREE@/"plans"/' \
    -e 's/^@UNITS@$/[[unit]]\nname = "rust"\npaths = ["code\/rust"]\nchecks = ["true"]/' \
    "$here/templates/smuggle.toml" > .hal/smuggle.toml
  git add .hal/smuggle.toml && git commit -q -m units
  run bash "$here/check.sh"
  [ "$status" -eq 0 ]
  [[ "$output" != *"note: no .hal/smuggle.toml"* ]]
  echo 'name = = broken' >> .hal/smuggle.toml && git commit -q -am broken
  run bash "$here/check.sh"
  [ "$status" -eq 1 ]
  [[ "$output" == *"cannot be read at HEAD"* ]]
}
