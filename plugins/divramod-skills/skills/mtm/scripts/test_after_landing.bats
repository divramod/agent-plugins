#!/usr/bin/env bats
# after-landing.sh: the cleanup after a full landing with a finished plan; the farmer line from 10-99.

setup() {
  here="$BATS_TEST_DIRNAME"
  tmp="$(mktemp -d)"
  git init -q --bare -b main "$tmp/origin.git"
  git clone -q "$tmp/origin.git" "$tmp/main" 2>/dev/null
  cd "$tmp/main"
  printf 'plans/CURRENT_PLAN\n' > .gitignore
  git add .gitignore && git -c user.name=t -c user.email=t@t commit -q -m init
  git push -q origin HEAD:main
  git remote set-head origin main
  git worktree add -q -b 12 "$tmp/12"
  git worktree add -q -b 03 "$tmp/03"
  # a fake cleanup skill: busy when $tmp/busy exists, delete logs where it ran
  cat > "$tmp/cleanup.py" <<PY
import os, sys
if sys.argv[1] == "busy":
    sys.exit(1 if os.path.exists("$tmp/busy") else 0)
open("$tmp/deleted", "a").write(os.getcwd() + "\n")
print("deleted 1 path, freed 1.0 GB")
PY
  export HAL_MTM_CLEANUP="$tmp/cleanup.py"
}

teardown() { rm -rf "$tmp"; }

@test "a landed 10-99 slot is cleaned and the farmer is told" {
  run bash "$here/after-landing.sh" "$tmp/12"
  [ "$status" -eq 0 ]
  [[ "$output" == *"status: cleaned"* ]]
  [[ "$output" == *"farmer: slot 12 done"* ]]
  grep -q "/12$" "$tmp/deleted"
}

@test "a landed 00-09 slot is cleaned without the farmer line" {
  run bash "$here/after-landing.sh" "$tmp/03"
  [[ "$output" == *"status: cleaned"* ]]
  [[ "$output" != *"farmer:"* ]]
}

@test "an unfinished plan, a commit or a change skips it" {
  mkdir -p "$tmp/12/plans" && echo 0001-x > "$tmp/12/plans/CURRENT_PLAN"
  run bash "$here/after-landing.sh" "$tmp/12"
  [[ "$output" == *"status: skipped"*"0001-x"* ]]
  rm "$tmp/12/plans/CURRENT_PLAN"
  echo x > "$tmp/12/x.txt"
  run bash "$here/after-landing.sh" "$tmp/12"
  [[ "$output" == *"uncommitted"* ]]
  git -C "$tmp/12" add x.txt && git -C "$tmp/12" -c user.name=t -c user.email=t@t commit -q -m x
  run bash "$here/after-landing.sh" "$tmp/12"
  [[ "$output" == *"1 commit(s) not on origin/main"* ]]
  [ ! -e "$tmp/deleted" ]
}

@test "a busy worktree and a named slot are not cleaned" {
  touch "$tmp/busy"
  run bash "$here/after-landing.sh" "$tmp/12"
  [[ "$output" == *"status: busy"* ]]
  run bash "$here/after-landing.sh" "$tmp/main"
  [[ "$output" == *"not a numbered slot"* ]]
  [ ! -e "$tmp/deleted" ]
}
