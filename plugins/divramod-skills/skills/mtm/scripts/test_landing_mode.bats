#!/usr/bin/env bats
# landing-mode.sh: ci when dev-merge-to-main.yml, merge-to-main.yml or land.yml is in HEAD or origin's default branch.

setup() {
  here="$BATS_TEST_DIRNAME"
  tmp="$(mktemp -d)"
  git init -q --bare -b main "$tmp/origin.git"
  git clone -q "$tmp/origin.git" "$tmp/wt" 2>/dev/null
  cd "$tmp/wt"
  git -c user.name=t -c user.email=t@t commit -q --allow-empty -m init
  git push -q origin HEAD:main
  git remote set-head origin main
}

teardown() { rm -rf "$tmp"; }

add_land() { # [<workflow file>...], default land.yml: one commit with them
  local file
  mkdir -p .github/workflows
  for file in "${@:-land.yml}"; do echo 'on: push' > ".github/workflows/$file"; done
  git add .github && git -c user.name=t -c user.email=t@t commit -q -m land
}

@test "neither workflow file lands locally" {
  run bash "$here/landing-mode.sh" "$tmp/wt"
  [ "$output" = local ]
}

@test "another workflow file alone lands locally" {
  add_land ci.yml
  run bash "$here/landing-mode.sh" "$tmp/wt"
  [ "$output" = local ]
}

@test "land.yml in HEAD lands through CI" {
  add_land
  run bash "$here/landing-mode.sh" "$tmp/wt"
  [ "$output" = ci ]
}

@test "land.yml only on origin's default branch lands through CI" {
  add_land
  git push -q origin HEAD:main
  git reset -q --hard HEAD~1
  run bash "$here/landing-mode.sh" "$tmp/wt"
  [ "$output" = ci ]
}

@test "dev-merge-to-main.yml in HEAD lands through CI" {
  add_land dev-merge-to-main.yml
  run bash "$here/landing-mode.sh" "$tmp/wt"
  [ "$output" = ci ]
}

@test "dev-merge-to-main.yml only on origin's default branch lands through CI" {
  add_land dev-merge-to-main.yml
  git push -q origin HEAD:main
  git reset -q --hard HEAD~1
  run bash "$here/landing-mode.sh" "$tmp/wt"
  [ "$output" = ci ]
}

@test "merge-to-main.yml in HEAD lands through CI" {
  add_land merge-to-main.yml
  run bash "$here/landing-mode.sh" "$tmp/wt"
  [ "$output" = ci ]
}

@test "merge-to-main.yml only on origin's default branch lands through CI" {
  add_land merge-to-main.yml
  git push -q origin HEAD:main
  git reset -q --hard HEAD~1
  run bash "$here/landing-mode.sh" "$tmp/wt"
  [ "$output" = ci ]
}

@test "both workflow files in HEAD land through CI" {
  add_land merge-to-main.yml land.yml
  run bash "$here/landing-mode.sh" "$tmp/wt"
  [ "$output" = ci ]
}

@test "the rename on origin's default branch, land.yml still in HEAD: through CI" {
  add_land
  git push -q origin HEAD:main
  git mv .github/workflows/land.yml .github/workflows/merge-to-main.yml
  git -c user.name=t -c user.email=t@t commit -q -m rename
  git push -q origin HEAD:main
  git reset -q --hard HEAD~1
  [ -f .github/workflows/land.yml ]
  run bash "$here/landing-mode.sh" "$tmp/wt"
  [ "$output" = ci ]
}

@test "run in the worktree without an argument" {
  add_land merge-to-main.yml
  run bash "$here/landing-mode.sh"
  [ "$output" = ci ]
}
