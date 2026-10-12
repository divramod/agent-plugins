#!/usr/bin/env bash
# Check the tools of stop-all-agent-work's scripts (also used by continue-all-agent-work).
missing=0
for t in python3 ps lsof launchctl; do
  if command -v "$t" >/dev/null; then echo "ok $t"; else echo "MISSING $t -> part of macOS / brew install python"; missing=1; fi
done
for t in xcrun docker; do
  if command -v "$t" >/dev/null; then echo "ok $t (optional)"; else echo "MISSING $t (optional) -> xcode-select --install / brew install --cask docker"; fi
done
exit $missing
