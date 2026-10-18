#!/usr/bin/env bash
# Check the tools the state call needs. Exit 1 when a required tool (python3, git) is missing; gh, hal2-cli-git and
# hal2-cli-agents are optional: without them the table only leaves their facts out.
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
for tool in gh hal2-cli-git hal2-cli-agents; do
  if command -v "$tool" >/dev/null 2>&1; then echo "ok $tool"; else echo "optional $tool missing: its facts are left out"; fi
done
exit "$missing"
