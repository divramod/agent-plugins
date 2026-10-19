#!/usr/bin/env bash
# Check the tools of important-interrupt's scripts (it also uses stop-all-agent-work's quiet.py).
missing=0
for t in python3 ps lsof launchctl; do
  if command -v "$t" >/dev/null; then echo "ok $t"; else echo "MISSING $t -> part of macOS / brew install python"; missing=1; fi
done
for t in tart hal2-cli-agents docker; do
  if command -v "$t" >/dev/null; then echo "ok $t (optional)"; else echo "MISSING $t (optional) -> brew install cirruslabs/cli/tart / cargo install --path apps/hal2-cli-agents / brew install --cask docker"; fi
done
exit $missing
