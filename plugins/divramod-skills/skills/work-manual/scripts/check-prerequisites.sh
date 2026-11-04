#!/usr/bin/env bash
# Check the tools /work-manual's script uses: python3 and hal2-cli-plans (both required: the CLI is the only reader
# and writer of the manual items).
missing=0
for tool in python3 hal2-cli-plans; do
  if command -v "$tool" >/dev/null 2>&1; then
    echo "ok $tool"
  else
    case "$tool" in
      python3) echo "MISSING python3 -> brew install python3 (or apt-get install python3)" ;;
      *) echo "MISSING $tool -> cargo install --path apps/hal2-cli-plans (from code/rust/ of hal2)" ;;
    esac
    missing=1
  fi
done
exit "$missing"
