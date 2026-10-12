#!/usr/bin/env bash
# Install the tools the handoff scripts need that are missing, then re-check.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v git >/dev/null 2>&1; then
  if command -v brew >/dev/null 2>&1; then
    brew install git
  elif command -v apt-get >/dev/null 2>&1; then
    sudo apt-get install -y git
  else
    echo "install git manually: neither brew nor apt-get is available" >&2
  fi
fi

bash "$here/check-prerequisites.sh"
