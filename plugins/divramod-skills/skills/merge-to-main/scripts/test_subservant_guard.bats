#!/usr/bin/env bats
# subservant-guard.sh: a servant's field (plans/LEAD) never lands, and is told who does.

load test_helper

# The template (test_helper.bash): a repository wt with a folder sub, and a hal2-cli-git on PATH that fails: a
# name resolves through git's worktree list, never through the installed CLI and the user's own worktrees. A test
# about the CLI writes its own.
build() {
  git init -q "$tmp/wt"
  mkdir -p "$tmp/wt/sub" "$tmp/bin"
  printf '#!/usr/bin/env bash\nexit 1\n' > "$tmp/bin/hal2-cli-git"
  chmod +x "$tmp/bin/hal2-cli-git"
}

setup_file() {
  tmp=$(fixture_dir)
  fixture_build build
}

setup() {
  here="$BATS_TEST_DIRNAME"
  tmp=$(fixture_dir)
  fixture_copy
  export PATH="$tmp/bin:$PATH"
}

teardown() { fixture_drop; }

@test "a worktree without the marker passes silently" {
  run bash "$here/subservant-guard.sh" "$tmp/wt"
  [ "$status" -eq 0 ]
  [ -z "$output" ]
}

@test "a servant's field is refused, naming the foreman and what the servant does instead" {
  mkdir -p "$tmp/wt/plans" && echo "02 0005-big-plan 3" > "$tmp/wt/plans/LEAD"
  run bash "$here/subservant-guard.sh" "$tmp/wt/sub"
  [ "$status" -eq 1 ]
  [[ "$output" == *"a servant of the foreman in field 02 (plans/LEAD: plan 0005-big-plan, step or row 3): it never lands"* ]]
  [[ "$output" == *"report to the foreman in field 02, who merges it, marks the steps and brings the work in"* ]]
  # a live marker is never called a leftover, and the servant is never told to remove it (hal2 plan 0275 D26)
  [[ "$output" != *"stale"* ]]
  [[ "$output" != *"delete"* ]]
  [[ "$output" != *"plan.py report"* ]]
  [ -f "$tmp/wt/plans/LEAD" ]
}

@test "a marker in the git dir's hal/ refuses the landing as plans/LEAD does (plan 0409 step 12)" {
  mkdir -p "$tmp/wt/.git/hal" && echo "02 0005-big-plan 3" > "$tmp/wt/.git/hal/LEAD"
  run bash "$here/subservant-guard.sh" "$tmp/wt/sub"
  [ "$status" -eq 1 ]
  [[ "$output" == *"a servant of the foreman in field 02"* ]]
}

@test "a masterplan's servant is refused the same way: its marker names the masterplan and its row" {
  mkdir -p "$tmp/wt/plans" && echo "09 0274-masterplan-halverse-plugin 12" > "$tmp/wt/plans/LEAD"
  echo "0274-masterplan-halverse-plugin" > "$tmp/wt/plans/CURRENT_PLAN"
  run bash "$here/subservant-guard.sh" "$tmp/wt"
  [ "$status" -eq 1 ]
  [[ "$output" == *"the foreman in field 09 (plans/LEAD: plan 0274-masterplan-halverse-plugin, step or row 12)"* ]]
}

@test "the current directory is the default" {
  mkdir -p "$tmp/wt/plans" && echo "07 0001-x 9" > "$tmp/wt/plans/LEAD"
  cd "$tmp/wt/sub"
  run bash "$here/subservant-guard.sh"
  [ "$status" -eq 1 ]
  [[ "$output" == *"field 07"* ]]
}

@test "a bare worktree name resolves to the worktree of that folder name" {
  git -C "$tmp/wt" -c user.email=t@t -c user.name=t commit -q --allow-empty -m init
  git -C "$tmp/wt" worktree add -q -b 31 "$tmp/slots/31"
  mkdir -p "$tmp/slots/31/plans" && echo "30 0013-parallel 4" > "$tmp/slots/31/plans/LEAD"
  cd "$tmp/wt" || return
  run bash "$here/subservant-guard.sh" 31
  [ "$status" -eq 1 ]
  [[ "$output" == *"the foreman in field 30 (plans/LEAD: plan 0013-parallel, step or row 4)"* ]]
}

@test "a bare worktree name without the marker passes, whatever the current worktree holds" {
  git -C "$tmp/wt" -c user.email=t@t -c user.name=t commit -q --allow-empty -m init
  git -C "$tmp/wt" worktree add -q -b 32 "$tmp/slots/32"
  mkdir -p "$tmp/wt/plans" && echo "07 0001-x 9" > "$tmp/wt/plans/LEAD"
  cd "$tmp/wt" || return
  run bash "$here/subservant-guard.sh" 32
  [ "$status" -eq 0 ]
  [ -z "$output" ]
}

@test "an unknown worktree name exits 3" {
  cd "$tmp/wt" || return
  run bash "$here/subservant-guard.sh" 99
  [ "$status" -eq 3 ]
  [[ "$output" == *"named '99'"* ]]
}

@test "a named worktree resolves through hal2-cli-git's worktree list" {
  mkdir -p "$tmp/bin" "$tmp/slots/farmer-hal2/plans"
  git init -q "$tmp/slots/farmer-hal2"
  echo "30 0013-parallel 2" > "$tmp/slots/farmer-hal2/plans/LEAD"
  printf '#!/usr/bin/env bash\necho %s\n' "'{\"worktrees\":[{\"name\":\"farmer-hal2\",\"path\":\"$tmp/slots/farmer-hal2\"}]}'" > "$tmp/bin/hal2-cli-git"
  chmod +x "$tmp/bin/hal2-cli-git"
  cd "$tmp/wt" || return
  PATH="$tmp/bin:$PATH" run bash "$here/subservant-guard.sh" farmer-hal2
  [ "$status" -eq 1 ]
  [[ "$output" == *"field 30"* ]]
}

@test "main is the main checkout without hal2-cli-git" {
  git -C "$tmp/wt" -c user.email=t@t -c user.name=t commit -q --allow-empty -m init
  git -C "$tmp/wt" worktree add -q -b 33 "$tmp/slots/33"
  mkdir -p "$tmp/bin" && printf '#!/usr/bin/env bash\nexit 1\n' > "$tmp/bin/hal2-cli-git" && chmod +x "$tmp/bin/hal2-cli-git"
  mkdir -p "$tmp/wt/plans" && echo "07 0001-x 9" > "$tmp/wt/plans/LEAD"
  cd "$tmp/slots/33"
  PATH="$tmp/bin:$PATH" run bash "$here/subservant-guard.sh" main
  [ "$status" -eq 1 ]
  [[ "$output" == *"field 07"* ]]
}

@test "a worktree name is compared as text: 2 is not 02" {
  git -C "$tmp/wt" -c user.email=t@t -c user.name=t commit -q --allow-empty -m init
  git -C "$tmp/wt" worktree add -q -b 02 "$tmp/slots/02"
  mkdir -p "$tmp/bin" && printf '#!/usr/bin/env bash\nexit 1\n' > "$tmp/bin/hal2-cli-git" && chmod +x "$tmp/bin/hal2-cli-git"
  cd "$tmp/wt" || return
  PATH="$tmp/bin:$PATH" run bash "$here/subservant-guard.sh" 2
  [ "$status" -eq 3 ]
}
