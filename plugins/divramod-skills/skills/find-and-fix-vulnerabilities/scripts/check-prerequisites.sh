#!/usr/bin/env bash
# Check the tools the vulnerability scan needs. Exit 1 when python3 is missing; the scanners and the rest are
# optional: a scan part whose tool is missing says "not installed" and the others still run.
missing=0
if command -v python3 >/dev/null 2>&1; then echo "ok python3"; else echo "MISSING python3 -> brew install python (or: sudo apt-get install -y python3; winget install Python.Python.3)"; missing=1; fi
for t in osv-scanner trivy; do
  if command -v "$t" >/dev/null 2>&1; then echo "ok $t"; else echo "optional $t missing: not installed yet (farms need osv-scanner, images and servers trivy) -> scripts/install-prerequisites.sh"; fi
done
for t in docker tart ssh; do
  if command -v "$t" >/dev/null 2>&1; then echo "ok $t"; else echo "optional $t missing: its part of the scan is skipped"; fi
done
exit "$missing"
