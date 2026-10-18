#!/usr/bin/env bash
# Check the tools /mfm and /mtm need. Exit 1 when a required tool is missing.
missing=0
if command -v git >/dev/null 2>&1; then
  echo "ok git"
else
  echo "MISSING git -> brew install git (or: sudo apt-get install -y git)"
  missing=1
fi
if command -v hal2-cli-git >/dev/null 2>&1 && hal2-cli-git --help | grep -q 'merge-to-main .*--json'; then
  echo "ok hal2-cli-git"
else
  echo "MISSING hal2-cli-git (with --json merges) -> cargo install --git https://github.com/divramod/hal2 hal2-cli-git"
  missing=1
fi
exit "$missing"
