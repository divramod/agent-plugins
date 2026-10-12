#!/usr/bin/env bats
# scan.sh on a scratch repository with a land workflow, units and a utils script.

setup() {
  here="$BATS_TEST_DIRNAME"
  tmp="$(cd "$(mktemp -d)" && pwd -P)"
  export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t
  git init -q -b main "$tmp/repo"
  cd "$tmp/repo"
  git remote add origin https://github.com/someone/repo.git
  mkdir -p .github/workflows code/rust/apps/foo code/bash/scripts/bar code/typescript/libs/ui utils/cloudinit
  cat > .github/workflows/land.yml <<'YML'
on:
  push:
    branches: ['land/**']
jobs:
  rust-test:
    runs-on: [self-hosted, linux]
    steps:
      - uses: actions/checkout@v4
      - run: cargo nextest run
  merge:
    runs-on: ubuntu-latest
    steps:
      - run: git push origin HEAD:main
YML
  printf 'on: pull_request\njobs:\n  lint:\n    runs-on: macos-latest\n    steps:\n      - run: make lint\n' \
    > .github/workflows/pr.yml
  echo '[package]' > code/rust/apps/foo/Cargo.toml
  echo 'echo hi' > code/bash/scripts/bar/main.sh
  echo '@test "x" { true; }' > code/bash/scripts/bar/test_main.bats
  echo '{"scripts":{"test":"vitest","lint":"biome check"}}' > code/typescript/libs/ui/package.json
  echo 'x' > utils/cloudinit/user-data
  mkdir -p code/bash/scripts/deliver && echo 'true' > code/bash/scripts/deliver/main.sh
  git add . && git commit -q -m init
}

teardown() { rm -rf "$tmp"; }

@test "scan: workflows with their jobs, the land workflow, units, utils, deliveries, inputs" {
  run bash -c "bash '$here/scan.sh' 2>&1"
  [ "$status" -eq 0 ]
  json="$output"
  [ "$(echo "$json" | jq -r .provider)" = github ]
  [ "$(echo "$json" | jq -c .land_workflows)" = '[".github/workflows/land.yml"]' ]
  [ "$(echo "$json" | jq -c '[.workflows[] | select(.file == ".github/workflows/land.yml") | .jobs[].name]')" = '["rust-test","merge"]' ]
  [ "$(echo "$json" | jq -r '.workflows[] | select(.file | endswith("pr.yml")) | .jobs[0].runs_on')" = macos-latest ]
  [ "$(echo "$json" | jq -c '[.units[] | .name] | sort')" = '["bar","deliver","foo","ui"]' ]
  [ "$(echo "$json" | jq -c '.units[] | select(.name == "foo") | .manifests')" = '["Cargo.toml"]' ]
  [ "$(echo "$json" | jq -c '.units[] | select(.name == "bar") | .tests')" = '["test_main.bats"]' ]
  [ "$(echo "$json" | jq -r '.units[] | select(.name == "ui") | .package_scripts.test')" = vitest ]
  [ "$(echo "$json" | jq -c .utils)" = '["utils/cloudinit"]' ]
  [ "$(echo "$json" | jq -c .deliveries)" = '["code/bash/scripts/deliver/main.sh"]' ]
  [ "$(echo "$json" | jq -c .fingerprint_inputs)" = '[".github/workflows/*"]' ]
}

@test "scan without yq: the jobs' names and runs-on" {
  run env FASTLANE_NO_YQ=1 bash "$here/scan.sh"
  [ "$status" -eq 0 ]
  [ "$(echo "$output" | jq -c '.workflows[] | select(.file | endswith("land.yml")) | .jobs')" \
    = '[{"name":"rust-test","runs_on":"[self-hosted, linux]"},{"name":"merge","runs_on":"ubuntu-latest"}]' ]
}
