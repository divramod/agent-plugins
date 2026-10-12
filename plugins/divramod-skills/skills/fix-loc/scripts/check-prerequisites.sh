#!/usr/bin/env bash
# Check the tools the fix-loc scripts need. Exit 1 when a required tool is missing.
missing=0
for tool in python3 git scc hal2-cli-agents hal2-cli-git; do
  if command -v "$tool" >/dev/null 2>&1; then
    echo "ok $tool"
  else
    case "$tool" in
      hal2-cli-*) echo "MISSING $tool -> cargo install --path code/rust/apps/$tool (in ~/a/hal2)" ;;
      python3) echo "MISSING python3 -> brew install python (or: sudo apt-get install -y python3)" ;;
      *) echo "MISSING $tool -> brew install $tool" ;;
    esac
    missing=1
  fi
done
exit "$missing"
