#!/usr/bin/env bash
# Install the required tool of the design call when it is missing (python3), then re-check. `open`/`xdg-open` is
# optional (serve --open) and only reported.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v python3 >/dev/null 2>&1; then
  if command -v brew >/dev/null 2>&1; then
    brew install python
  elif command -v apt-get >/dev/null 2>&1; then
    sudo apt-get install -y python3
  else
    echo "install python3 manually: neither brew nor apt-get is available" >&2
  fi
fi

bash "$here/check-prerequisites.sh"
