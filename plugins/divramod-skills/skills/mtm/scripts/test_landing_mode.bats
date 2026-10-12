#!/usr/bin/env bats
# landing-mode.sh: ci when land.yml is in HEAD or origin's default branch.

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

add_land() {
  mkdir -p .github/workflows && echo 'on: push' > .github/workflows/land.yml
  git add .github && git -c user.name=t -c user.email=t@t commit -q -m land
}

@test "no land.yml lands locally" {
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
