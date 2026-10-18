#!/usr/bin/env bash
# Check the tools the uat call needs. Exit 1 when a required tool (python3, git, hal2-cli-plans) is missing.
missing=0
for tool in python3 git; do
  if command -v "$tool" >/dev/null 2>&1; then
    echo "ok $tool"
  else
    case "$tool" in
      git) echo "MISSING git -> brew install git (or: sudo apt-get install -y git)" ;;
      *) echo "MISSING $tool -> brew install python (or: sudo apt-get install -y python3)" ;;
    esac
    missing=1
  fi
done
if command -v hal2-cli-plans >/dev/null 2>&1; then
  echo "ok hal2-cli-plans"
else
  echo "MISSING hal2-cli-plans -> cargo install --path code/rust/apps/hal2-cli-plans (from the hal2 repository)"
  missing=1
fi
exit "$missing"
