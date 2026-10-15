#!/usr/bin/env bash
# Check the tools this skill's scripts use: git, python3, hal2-cli-agents and hal2-cli-git (all required), and that
# the installed hal2-cli-git knows `worktree transplant` (it comes with hal2 plan 0286's bring in).
missing=0
for tool in git python3; do
  if command -v "$tool" >/dev/null 2>&1; then
    echo "ok $tool"
  else
    echo "MISSING $tool -> brew install $tool (or apt-get install $tool)"
    missing=1
  fi
done
for tool in hal2-cli-agents hal2-cli-git; do
  if command -v "$tool" >/dev/null 2>&1; then
    echo "ok $tool"
  else
    echo "MISSING $tool -> cargo install --git https://github.com/divramod/hal2 $tool"
    missing=1
  fi
done
if command -v hal2-cli-git >/dev/null 2>&1; then
  if hal2-cli-git --help 2>&1 | grep -q "worktree transplant"; then
    echo "ok hal2-cli-git worktree transplant"
  else
    echo "MISSING hal2-cli-git worktree transplant -> the installed hal2-cli-git is older than hal2 plan 0286; the land run's delivery installs the new one after the bring in"
    missing=1
  fi
fi
exit "$missing"
