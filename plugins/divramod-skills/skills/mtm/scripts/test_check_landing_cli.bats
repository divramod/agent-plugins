#!/usr/bin/env bats
# check-landing-cli.sh: a repository with merge-to-main.yml needs a hal2-cli-git whose help names that file; an
# older one would land it as a plain merge, untested.

setup() {
  here="$BATS_TEST_DIRNAME"
  tmp="$(mktemp -d)"
  git init -q --bare -b main "$tmp/origin.git"
  git clone -q "$tmp/origin.git" "$tmp/wt" 2>/dev/null
  cd "$tmp/wt"
  git -c user.name=t -c user.email=t@t commit -q --allow-empty -m init
  git push -q origin HEAD:main
  git remote set-head origin main
  mkdir -p "$tmp/bin"
  export PATH="$tmp/bin:$PATH" CALLS="$tmp/calls"
}

teardown() { rm -rf "$tmp"; }

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

# The help of the CLI before the rename and of the one that reads both names (their merge-to-main entries).
old_cli() {
  fake_cli "usage: hal2-cli-git worktree merge-to-main [<slot>] [--keep-reserved] [--local] [--json]" \
    "  the candidate merge commit and, when the repository has .github/workflows/land.yml, push it to land/<slot>" \
    "  without land.yml the candidate is pushed straight to the default branch, untested (warning)"
}
new_cli() {
  fake_cli "usage: hal2-cli-git worktree merge-to-main [<slot>] [--keep-reserved] [--local] [--json]" \
    "  the candidate merge commit and, when the repository has .github/workflows/merge-to-main.yml (or land.yml," \
    "  its name before plan 0263), push it to land/<slot>"
}

add_workflow() { # <workflow file>...: one commit with them
  local file
  mkdir -p .github/workflows
  for file in "$@"; do echo 'on: push' > ".github/workflows/$file"; done
  git add .github && git -c user.name=t -c user.email=t@t commit -q -m wf
}

# A PATH directory with every tool of /usr/bin and /bin except hal2-cli-git.
path_without_cli() {
  local dir=$1 d f
  mkdir -p "$dir"
  for d in /usr/bin /bin; do
    for f in "$d"/*; do
      [ "${f##*/}" = hal2-cli-git ] || [ -e "$dir/${f##*/}" ] || ln -s "$f" "$dir/${f##*/}"
    done
  done
  ln -sf "$(command -v git)" "$dir/git"
}

@test "neither workflow file: nothing to check, whatever the CLI" {
  old_cli
  run bash "$here/check-landing-cli.sh" "$tmp/wt"
  [ "$status" -eq 0 ]
  [ -z "$output" ]
  rm "$tmp/bin/hal2-cli-git"
  path_without_cli "$tmp/bare"
  PATH="$tmp/bare" run bash "$here/check-landing-cli.sh" "$tmp/wt"
  [ "$status" -eq 0 ]
}

@test "only land.yml: an old CLI lands it through CI, nothing to check" {
  add_workflow land.yml
  git push -q origin HEAD:main
  old_cli
  run bash "$here/check-landing-cli.sh" "$tmp/wt"
  [ "$status" -eq 0 ]
  [ -z "$output" ]
}

@test "only merge-to-main.yml in HEAD, an old CLI: stopped, the message says what and how to go on" {
  add_workflow merge-to-main.yml
  old_cli
  run bash "$here/check-landing-cli.sh" "$tmp/wt"
  [ "$status" -eq 8 ]
  [[ "$output" == *"nothing was landed"* ]]
  [[ "$output" == *".github/workflows/merge-to-main.yml (in HEAD): "* ]]
  [[ "$output" == *"$tmp/bin/hal2-cli-git (hal2-cli-git 0.13.0)"* ]]
  [[ "$output" == *"as a plain merge, untested"* ]]
  [[ "$output" == *"cargo install --locked --path <hal2 checkout>/code/rust/apps/hal2-cli-git"* ]]
  [[ "$output" == *"then run /mtm again"* ]]
}

@test "merge-to-main.yml only on origin's default branch, an old CLI: stopped" {
  add_workflow merge-to-main.yml
  git push -q origin HEAD:main
  git reset -q --hard HEAD~1
  old_cli
  run bash "$here/check-landing-cli.sh" "$tmp/wt"
  [ "$status" -eq 8 ]
  [[ "$output" == *"merge-to-main.yml (in origin/main): "* ]]
}

@test "the rename on origin's default branch, land.yml still in HEAD, an old CLI: stopped" {
  add_workflow land.yml
  git push -q origin HEAD:main
  git mv .github/workflows/land.yml .github/workflows/merge-to-main.yml
  git -c user.name=t -c user.email=t@t commit -q -m rename
  git push -q origin HEAD:main
  git reset -q --hard HEAD~1
  old_cli
  run bash "$here/check-landing-cli.sh" "$tmp/wt"
  [ "$status" -eq 8 ]
}

@test "both workflow files, an old CLI: stopped; a new one passes" {
  add_workflow merge-to-main.yml land.yml
  git push -q origin HEAD:main
  old_cli
  run bash "$here/check-landing-cli.sh" "$tmp/wt"
  [ "$status" -eq 8 ]
  [[ "$output" == *"merge-to-main.yml (in HEAD and origin/main): "* ]]
  new_cli
  run bash "$here/check-landing-cli.sh" "$tmp/wt"
  [ "$status" -eq 0 ]
  [ -z "$output" ]
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

@test "a help longer than a pipe's buffer, the name in its first line: still passes" {
  add_workflow merge-to-main.yml
  new_cli
  { echo "lands through .github/workflows/merge-to-main.yml or land.yml"; yes "filler line of the help text" | head -n 20000; } > "$tmp/help"
  run bash "$here/check-landing-cli.sh" "$tmp/wt"
  [ "$status" -eq 0 ]
}

@test "a CLI that prints its help on stderr and exits 1 is read all the same" {
  add_workflow merge-to-main.yml
  cat > "$tmp/bin/hal2-cli-git" <<'EOF'
#!/usr/bin/env bash
echo "usage: ... .github/workflows/merge-to-main.yml (or land.yml)" >&2
exit 1
EOF
  chmod +x "$tmp/bin/hal2-cli-git"
  run bash "$here/check-landing-cli.sh" "$tmp/wt"
  [ "$status" -eq 0 ]
}

@test "in front of the landing an old CLI never starts it, a new one does" {
  add_workflow merge-to-main.yml
  old_cli
  run bash -c "bash '$here/check-landing-cli.sh' && hal2-cli-git worktree merge-to-main --max-wait 100m --json"
  [ "$status" -eq 8 ]
  [ ! -e "$tmp/calls" ]
  new_cli
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
  old_cli
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
