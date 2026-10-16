#!/usr/bin/env bash
# Check the tools the fix-tart scripts need. Exit 1 when a required tool is missing.
# Required: python3, hal2-daemon (`vms list --json`). Optional: tart, gh, pmset (their sections say when missing).
missing=0
for tool in python3 hal2-daemon; do
  if command -v "$tool" >/dev/null 2>&1; then
    echo "ok $tool"
  else
    case "$tool" in
      hal2-daemon) echo "MISSING hal2-daemon -> cargo install --path code/rust/apps/hal2-daemon (in ~/a/hal2)" ;;
      *) echo "MISSING $tool -> brew install python (or: sudo apt-get install -y python3)" ;;
    esac
    missing=1
  fi
done
for tool in tart gh pmset; do
  if command -v "$tool" >/dev/null 2>&1; then echo "ok $tool"; else echo "optional $tool missing (its section is skipped)"; fi
done
exit "$missing"
