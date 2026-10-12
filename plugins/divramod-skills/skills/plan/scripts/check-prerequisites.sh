#!/usr/bin/env bash
# Check the tools the plan scripts need. Exit 1 when a required tool is missing.
missing=0
if command -v git >/dev/null 2>&1; then
  echo "ok git"
else
  echo "MISSING git -> brew install git (or: sudo apt-get install -y git)"
  missing=1
fi
# Optional: session.py and context.py read the claude process's --model and --effort with ps.
if command -v ps >/dev/null 2>&1; then
  echo "ok ps"
else
  echo "MISSING ps (optional) -> sudo apt-get install -y procps"
fi
exit "$missing"
