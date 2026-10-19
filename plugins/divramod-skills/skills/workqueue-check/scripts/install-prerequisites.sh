#!/usr/bin/env bash
# Install python3 when it is missing, then re-check. hal2-cli-workqueue comes with hal2's own install.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if ! command -v python3 >/dev/null 2>&1; then
  if command -v brew >/dev/null 2>&1; then brew install python
  elif command -v apt-get >/dev/null 2>&1; then sudo apt-get install -y python3
  else echo "install python3 manually: neither brew nor apt-get is available" >&2; fi
fi
bash "$here/check-prerequisites.sh"
