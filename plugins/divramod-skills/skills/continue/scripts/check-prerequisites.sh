#!/usr/bin/env bash
# Check the tools the continue scripts need. Exit 1 when a required tool is missing.
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
for cli in hal2-cli-agents hal2-cli-plans hal2-cli-git; do
  command -v "$cli" >/dev/null 2>&1 && echo "ok $cli" || echo "MISSING $cli (optional: the folder rule and the by-hand check stand in)"
done
exit "$missing"
