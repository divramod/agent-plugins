#!/usr/bin/env bash
# Check the tools this skill's scripts use: git, python3 and hal2-cli-git (all required).
missing=0
for tool in git python3; do
  if command -v "$tool" >/dev/null 2>&1; then
    echo "ok $tool"
  else
    echo "MISSING $tool -> brew install $tool (or apt-get install $tool)"
    missing=1
  fi
done
for tool in hal2-cli-git; do
  if command -v "$tool" >/dev/null 2>&1; then
    echo "ok $tool"
  else
    echo "MISSING $tool -> cargo install --git https://github.com/divramod/hal2 $tool"
    missing=1
  fi
done
exit "$missing"
