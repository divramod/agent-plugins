#!/usr/bin/env bash
# Check the tools this skill's script uses: python3 and hal2-cli-ring (both required).
missing=0
if command -v python3 >/dev/null 2>&1; then
  echo "ok python3"
else
  echo "MISSING python3 -> brew install python (or: sudo apt-get install -y python3)"
  missing=1
fi
if command -v hal2-cli-ring >/dev/null 2>&1; then
  echo "ok hal2-cli-ring"
else
  echo "MISSING hal2-cli-ring -> cargo install --git https://github.com/divramod/hal2 hal2-cli-ring"
  missing=1
fi
exit "$missing"
