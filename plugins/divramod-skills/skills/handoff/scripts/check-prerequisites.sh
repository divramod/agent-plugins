#!/usr/bin/env bash
# Check the tools the handoff scripts need. Exit 1 when a required tool is missing.
missing=0
if command -v git >/dev/null 2>&1; then
  echo "ok git"
else
  echo "MISSING git -> brew install git (or: sudo apt-get install -y git)"
  missing=1
fi
exit "$missing"
