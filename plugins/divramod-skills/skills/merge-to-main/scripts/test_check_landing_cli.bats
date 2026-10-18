#!/usr/bin/env bats
# check-landing-cli.sh: a repository with dev-merge-to-main.yml or merge-to-main.yml needs a hal2-cli-git whose help
# names that file; an older one would land it as a plain merge, untested.

load test_helper

# The template (test_helper.bash): origin and its clone wt, one commit on main.
build() {
  git init -q --bare -b main "$tmp/origin.git"
  git clone -q "$tmp/origin.git" "$tmp/wt" 2>/dev/null
  git -C "$tmp/wt" -c user.name=t -c user.email=t@t commit -q --allow-empty -m init
  git -C "$tmp/wt" push -q origin HEAD:main
  git -C "$tmp/wt" remote set-head origin main
  mkdir -p "$tmp/bin"
}

setup_file() {
  tmp=$(fixture_dir)
  fixture_build build
}

setup() {
  here="$BATS_TEST_DIRNAME"
  tmp=$(fixture_dir)
  fixture_copy
  cd "$tmp/wt" || return
  export PATH="$tmp/bin:$PATH" CALLS="$tmp/calls"
}

teardown() { fixture_drop; }

# A fake hal2-cli-git: `--help` prints the lines of $tmp/help, `--version` a version, anything else is recorded
# in $tmp/calls (a landing that started).
fake_cli() { # <a line of its help>...
  printf '%s\n' "$@" > "$tmp/help"
  cat > "$tmp/bin/hal2-cli-git" <<EOF
#!/usr/bin/env bash
case "\$1" in
  --help) cat "$tmp/help" ;;
  --version) echo "hal2-cli-git 0.13.0" ;;
  *) echo "\$*" >> "\$CALLS" ;;
esac
EOF
  chmod +x "$tmp/bin/hal2-cli-git"
}

# The help of a CLI that reads merge-to-main.yml (its merge-to-main entry).
new_cli() {
  fake_cli "usage: hal2-cli-git worktree merge-to-main [<slot>] [--keep-reserved] [--local] [--json]" \
    "  the candidate merge commit and, when the repository has .github/workflows/merge-to-main.yml," \
    "  push it to land/<slot>"
}

# The help of the CLI that reads dev-merge-to-main.yml too (hal2 plan 0349 D52).
dev_cli() {
  fake_cli "usage: hal2-cli-git worktree merge-to-main [<slot>] [--keep-reserved] [--local] [--json]" \
    "  the candidate merge commit and, when the repository has .github/workflows/dev-merge-to-main.yml (or" \
    "  merge-to-main.yml, its name before plan 0349), push it to land/<slot>"
}

add_workflow() { # <workflow file>...: one commit with them
  local file
  mkdir -p .github/workflows
  for file in "$@"; do echo 'on: push' > ".github/workflows/$file"; done
  git add .github && git -c user.name=t -c user.email=t@t commit -q -m wf
}

# A PATH directory with every tool of /usr/bin and /bin except hal2-cli-git.
path_without_cli() {
  link_tools_except "$1" hal2-cli-git
  ln -sf "$(command -v git)" "$1/git"
}

@test "neither workflow file: nothing to check, whatever the CLI" {
  new_cli
  run bash "$here/check-landing-cli.sh" "$tmp/wt"
  [ "$status" -eq 0 ]
  [ -z "$output" ]
  rm "$tmp/bin/hal2-cli-git"
  path_without_cli "$tmp/bare"
  PATH="$tmp/bare" run bash "$here/check-landing-cli.sh" "$tmp/wt"
  [ "$status" -eq 0 ]
}

@test "only merge-to-main.yml, a CLI whose help names it: passes, in HEAD and on origin's default branch" {
  add_workflow merge-to-main.yml
  new_cli
  run bash "$here/check-landing-cli.sh" "$tmp/wt"
  [ "$status" -eq 0 ]
  [ -z "$output" ]
  git push -q origin HEAD:main
  git reset -q --hard HEAD~1
  run bash "$here/check-landing-cli.sh"
  [ "$status" -eq 0 ]
}

@test "dev-merge-to-main.yml in HEAD or on origin's default branch: a CLI that knows only merge-to-main.yml is stopped" {
  add_workflow dev-merge-to-main.yml
  new_cli
  run bash "$here/check-landing-cli.sh" "$tmp/wt"
  [ "$status" -eq 8 ]
  [[ "$output" == *".github/workflows/dev-merge-to-main.yml (in HEAD): "* ]]
  [[ "$output" == *"(a hal2 checkout that has dev-merge-to-main.yml)"* ]]
  git push -q origin HEAD:main
  git reset -q --hard HEAD~1
  run bash "$here/check-landing-cli.sh" "$tmp/wt"
  [ "$status" -eq 8 ]
  [[ "$output" == *"dev-merge-to-main.yml (in origin/main): "* ]]
  dev_cli
  run bash "$here/check-landing-cli.sh" "$tmp/wt"
  [ "$status" -eq 0 ]
  [ -z "$output" ]
}

@test "the rename to dev-merge-to-main.yml beside merge-to-main.yml: the newer name must be known" {
  add_workflow merge-to-main.yml dev-merge-to-main.yml
  new_cli
  run bash "$here/check-landing-cli.sh" "$tmp/wt"
  [ "$status" -eq 8 ]
  dev_cli
  run bash "$here/check-landing-cli.sh" "$tmp/wt"
  [ "$status" -eq 0 ]
}

@test "a help longer than a pipe's buffer, the name in its first line: still passes" {
  add_workflow merge-to-main.yml
  new_cli
  { echo "lands through .github/workflows/merge-to-main.yml"; yes "filler line of the help text" | head -n 20000; } > "$tmp/help"
  run bash "$here/check-landing-cli.sh" "$tmp/wt"
  [ "$status" -eq 0 ]
}

@test "a CLI that prints its help on stderr and exits 1 is read all the same" {
  add_workflow merge-to-main.yml
  cat > "$tmp/bin/hal2-cli-git" <<'EOF'
#!/usr/bin/env bash
echo "usage: ... .github/workflows/merge-to-main.yml" >&2
exit 1
EOF
  chmod +x "$tmp/bin/hal2-cli-git"
  run bash "$here/check-landing-cli.sh" "$tmp/wt"
  [ "$status" -eq 0 ]
}

@test "in front of the landing a CLI that does not know the file never starts it, one that does starts it" {
  add_workflow dev-merge-to-main.yml
  new_cli
  run bash -c "bash '$here/check-landing-cli.sh' && hal2-cli-git worktree merge-to-main --max-wait 100m --json"
  [ "$status" -eq 8 ]
  [ ! -e "$tmp/calls" ]
  dev_cli
  run bash -c "bash '$here/check-landing-cli.sh' && hal2-cli-git worktree merge-to-main --max-wait 100m --json"
  [ "$status" -eq 0 ]
  [ "$(cat "$tmp/calls")" = "worktree merge-to-main --max-wait 100m --json" ]
}

@test "merge-to-main.yml and no hal2-cli-git: exit 2 naming the install" {
  add_workflow merge-to-main.yml
  path_without_cli "$tmp/bare"
  PATH="$tmp/bare" run bash "$here/check-landing-cli.sh" "$tmp/wt"
  [ "$status" -eq 2 ]
  [[ "$output" == *"hal2-cli-git is missing"* ]]
  [[ "$output" == *"install-prerequisites.sh"* ]]
}

@test "a directory that is no git checkout exits 2, it is never taken for a repository without the workflow" {
  new_cli
  mkdir "$tmp/plain"
  run bash "$here/check-landing-cli.sh" "$tmp/plain"
  [ "$status" -eq 2 ]
  [[ "$output" == *"is no git checkout"* ]]
  run bash "$here/check-landing-cli.sh" 31
  [ "$status" -eq 2 ]
}

@test "the docs run the guard: before the reserve and in front of every merge-to-main through CI" {
  ci="$here/../references/ci.md"
  skill="$here/../SKILL.md"
  grep -q 'bash \$S/check-landing-cli.sh && hal2-cli-git worktree merge-to-main --max-wait 100m --keep-reserved --json' "$ci"
  grep -q '^| 8 |' "$ci"
  grep -q '^0\. `bash \$S/check-landing-cli.sh`' "$ci"
  grep -q 'check-landing-cli.sh' "$skill"
  # no merge-to-main command of the CI page is left without the guard in front
  ! grep -n 'hal2-cli-git worktree merge-to-main --max-wait' "$ci" | grep -v 'check-landing-cli.sh && hal2-cli-git worktree merge-to-main'
}
