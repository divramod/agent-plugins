#!/usr/bin/env bats
# after-landing.sh: the cleanup after a full landing with a finished plan; the farmer line from 10-99; a field
# whose CURRENT_PLAN names a masterplan is not cleaned and is told so.

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

@test "a landed 10-99 worktree is cleaned and the farmer is told" {
  run bash "$here/after-landing.sh" "$tmp/12"
  [ "$status" -eq 0 ]
  [[ "$output" == *"status: cleaned"* ]]
  [[ "$output" == *"farmer: worktree 12 done"* ]]
  grep -q "/12$" "$tmp/deleted"
}

@test "a landed 00-09 worktree is cleaned without the farmer line" {
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

# A plan folder in the record format, committed and on the default branch, so the worktree stays fully landed.
plan_in_12() { # <slug> <extra front matter line>
  mkdir -p "$tmp/12/plans/$1"
  printf -- '---\ntype: Plan\nschema: 1\nid: %d\ntitle: "%s"\ndescription: "x"\nstatus: open\nlanding: manual\n%s---\n\n# Plan %s\n\n## Steps\n\n| # | Step | Needs | Touches | Who | Done when | Status |\n|---|---|---|---|---|---|---|\n| 1 | one | | | lead | a check | |\n' \
    "$((10#${1%%-*}))" "$1" "$2" "${1%%-*}" > "$tmp/12/plans/$1/plan.md"
  git -C "$tmp/12" add plans && git -C "$tmp/12" -c user.name=t -c user.email=t@t commit -q -m "$1"
  git -C "$tmp/12" push -q origin HEAD:main
}

@test "a field that names a masterplan keeps its builds and says so; the slug alone decides nothing" {
  plan_in_12 0001-masterplan-farm ""
  plan_in_12 0002-masterplan-tools $'parent: 1\n'
  echo 0001-masterplan-farm > "$tmp/12/plans/CURRENT_PLAN"
  run bash "$here/after-landing.sh" "$tmp/12"
  [ "$status" -eq 0 ]
  [[ "$output" == *"status: skipped"* ]]
  [[ "$output" == *"why: plans/CURRENT_PLAN names the masterplan 0001-masterplan-farm: the field goes on with its next plan"* ]]
  # a plan of a masterplan whose slug carries the word is a plan like any other (hal2 plan 0275 D34)
  echo 0002-masterplan-tools > "$tmp/12/plans/CURRENT_PLAN"
  run bash "$here/after-landing.sh" "$tmp/12"
  [[ "$output" == *"why: plans/CURRENT_PLAN still names 0002-masterplan-tools: the plan is not finished"* ]]
  # without the plan skill beside it the file still skips the cleanup
  echo 0001-masterplan-farm > "$tmp/12/plans/CURRENT_PLAN"
  HAL_MTM_PLAN="$tmp/no-plan.py" run bash "$here/after-landing.sh" "$tmp/12"
  [[ "$output" == *"still names 0001-masterplan-farm"* ]]
  [ ! -e "$tmp/deleted" ]
}

@test "a plan.py that fails decides nothing: the file still names the plan and nothing is deleted" {
  plan_in_12 0001-masterplan-farm ""
  echo 0001-masterplan-farm > "$tmp/12/plans/CURRENT_PLAN"
  # it exits non-zero, with nothing and with an answer it gave before it failed: neither is taken
  for body in 'import sys; sys.exit(1)' 'import sys; print("{\"masterplan\": true}"); sys.exit(3)'; do
    printf '%s\n' "$body" > "$tmp/plan.py"
    HAL_MTM_PLAN="$tmp/plan.py" run bash "$here/after-landing.sh" "$tmp/12"
    [ "$status" -eq 0 ]
    [[ "$output" == *"status: skipped"* ]]
    [[ "$output" == *"why: plans/CURRENT_PLAN still names 0001-masterplan-farm: the plan is not finished"* ]]
    [[ "$output" != *"names the masterplan"* ]]
  done
  [ ! -e "$tmp/deleted" ]
  [ "$(cat "$tmp/12/plans/CURRENT_PLAN")" = 0001-masterplan-farm ]
}

@test "a busy worktree and a named worktree are not cleaned" {
  touch "$tmp/busy"
  run bash "$here/after-landing.sh" "$tmp/12"
  [[ "$output" == *"status: busy"* ]]
  run bash "$here/after-landing.sh" "$tmp/main"
  [[ "$output" == *"not a numbered worktree"* ]]
  [ ! -e "$tmp/deleted" ]
}
