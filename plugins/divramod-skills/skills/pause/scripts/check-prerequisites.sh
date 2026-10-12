#!/usr/bin/env bash
# Check the tools the pause scripts need. Exit 1 when a required tool is missing.
missing=0
for tool in python3 ps; do
  if command -v "$tool" >/dev/null 2>&1; then
    echo "ok $tool"
  else
    case "$tool" in
      ps) echo "MISSING ps -> sudo apt-get install -y procps" ;;
      *) echo "MISSING $tool -> brew install python (or: sudo apt-get install -y python3)" ;;
    esac
    missing=1
  fi
done
if command -v git >/dev/null 2>&1; then
  echo "ok git"
else
  echo "MISSING git (optional: the record is keyed by the current directory without it) -> brew install git"
fi
exit "$missing"
