#!/usr/bin/env bash
# Install python3, osv-scanner and trivy when they are missing, then re-check. Run it yourself: the scan never installs.
# docker, tart and ssh are optional and not installed here.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
need() { ! command -v "$1" >/dev/null 2>&1; }
if command -v brew >/dev/null 2>&1; then
  need python3 && brew install python
  need osv-scanner && brew install osv-scanner
  need trivy && brew install trivy
elif command -v apt-get >/dev/null 2>&1; then
  need python3 && sudo apt-get install -y python3
  need osv-scanner && echo "osv-scanner: install a release from https://github.com/google/osv-scanner/releases (or: go install github.com/google/osv-scanner/v2/cmd/osv-scanner@latest)" >&2
  need trivy && echo "trivy: see https://trivy.dev/latest/getting-started/installation/ (apt repository or the install script)" >&2
elif command -v winget >/dev/null 2>&1; then
  need python3 && winget install Python.Python.3
  need trivy && winget install AquaSecurity.Trivy
  need osv-scanner && echo "osv-scanner: scoop install osv-scanner (or a release from https://github.com/google/osv-scanner/releases)" >&2
elif command -v scoop >/dev/null 2>&1; then
  need python3 && scoop install python
  need osv-scanner && scoop install osv-scanner
  need trivy && scoop install trivy
else
  echo "install python3, osv-scanner and trivy manually: no brew, apt-get, winget or scoop found" >&2
fi
bash "$here/check-prerequisites.sh"
