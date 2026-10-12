#!/usr/bin/env bash
# Check the tools the cleanup scripts need. Exit 1 when a required tool is missing.
missing=0
for tool in python3 git ps; do
  if command -v "$tool" >/dev/null 2>&1; then
    echo "ok $tool"
  else
    case "$tool" in
      ps) echo "MISSING ps -> sudo apt-get install -y procps" ;;
      git) echo "MISSING git -> brew install git (or: sudo apt-get install -y git)" ;;
      *) echo "MISSING $tool -> brew install python (or: sudo apt-get install -y python3)" ;;
    esac
    missing=1
  fi
done
exit "$missing"
