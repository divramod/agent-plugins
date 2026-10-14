#!/usr/bin/env bash
# Check the tools the daybook needs. Exit 1 when a required tool (python3, git) is missing; without git the farm is
# the folder itself and no worktree plans show.
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
exit "$missing"
