#!/usr/bin/env bash
# Check the tools /q's scripts use: git and python3 (required), hal2-cli-plans (optional: without it q.py reads
# the store itself and prints the same Q form).
missing=0
for tool in git python3; do
  if command -v "$tool" >/dev/null 2>&1; then
    echo "ok $tool"
  else
    echo "MISSING $tool -> brew install $tool (or apt-get install $tool)"
    missing=1
  fi
done
if command -v hal2-cli-plans >/dev/null 2>&1; then
  echo "ok hal2-cli-plans"
else
  echo "MISSING hal2-cli-plans (optional) -> cargo install --path apps/hal2-cli-plans (from code/rust/ of hal2)"
fi
exit "$missing"
