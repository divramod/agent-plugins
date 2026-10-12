#!/usr/bin/env bash
# Check the tools the merge-to-main-boss scripts need. Exit 1 when a required tool is missing.
missing=0
for tool in python3 git gh hal2-cli-git hal2-cli-agents; do
  if command -v "$tool" >/dev/null 2>&1; then
    echo "ok $tool"
  else
    case "$tool" in
      hal2-cli-*) echo "MISSING $tool -> cargo install --path code/rust/apps/$tool (in ~/a/hal2)" ;;
      gh) echo "MISSING gh -> brew install gh, then gh auth login (landings and CI live on GitHub)" ;;
      git) echo "MISSING git -> brew install git (or: sudo apt-get install -y git)" ;;
      *) echo "MISSING $tool -> brew install python (or: sudo apt-get install -y python3)" ;;
    esac
    missing=1
  fi
done
exit "$missing"
