#!/usr/bin/env bash
# Check the tools this skill's scripts use: git, python3 and gh (all required).
missing=0
for tool in git python3 gh; do
  if command -v "$tool" >/dev/null 2>&1; then
    echo "ok $tool"
  else
    echo "MISSING $tool -> brew install $tool (or apt-get install $tool)"
    missing=1
  fi
done
exit "$missing"
