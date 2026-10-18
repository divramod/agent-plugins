#!/usr/bin/env bash
# Check the tools the design call needs. Exit 1 when python3 is missing; `open` (macOS) or `xdg-open` (Linux) is only
# needed for `design.py serve --open` and reported as optional.
missing=0
if command -v python3 >/dev/null 2>&1; then
  echo "ok python3"
else
  echo "MISSING python3 -> brew install python (or: sudo apt-get install -y python3)"
  missing=1
fi
if command -v open >/dev/null 2>&1 || command -v xdg-open >/dev/null 2>&1; then
  echo "ok open (serve --open)"
else
  echo "optional open/xdg-open missing: serve --open cannot open a browser; open the printed URL by hand"
fi
exit "$missing"
