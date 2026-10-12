#!/usr/bin/env bash
# Check the tools /shoot needs. Exit 1 when a required tool is missing.
missing=0
if command -v git >/dev/null 2>&1; then
  echo "ok git"
else
  echo "MISSING git -> brew install git (or: sudo apt-get install -y git)"
  missing=1
fi
if command -v hal2-cli-shooter >/dev/null 2>&1 && hal2-cli-shooter --help | grep -q -- '--global'; then
  echo "ok hal2-cli-shooter"
else
  echo "MISSING hal2-cli-shooter (with --global shotfiles) -> cargo install --git https://github.com/divramod/hal2 hal2-cli-shooter"
  missing=1
fi
exit "$missing"
