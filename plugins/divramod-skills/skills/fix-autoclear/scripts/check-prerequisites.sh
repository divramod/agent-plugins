#!/usr/bin/env bash
# Check the tools the fix-autoclear scripts need. Exit 1 when a required tool is missing.
missing=0
for tool in python3 hal2-cli-agents; do
  if command -v "$tool" >/dev/null 2>&1; then
    echo "ok $tool"
  else
    case "$tool" in
      hal2-cli-agents) echo "MISSING hal2-cli-agents -> cargo install --path code/rust/apps/hal2-cli-agents (in ~/a/hal2)" ;;
      *) echo "MISSING $tool -> brew install python (or: sudo apt-get install -y python3)" ;;
    esac
    missing=1
  fi
done
exit "$missing"
