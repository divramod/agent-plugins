#!/usr/bin/env bash
# Install the tools this skill's scripts need that are missing, then re-check.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

for tool in git python3 gh; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    if command -v brew >/dev/null 2>&1; then
      brew install "$tool"
    elif command -v apt-get >/dev/null 2>&1; then
      sudo apt-get install -y "$tool"
    else
      echo "install $tool manually: neither brew nor apt-get is available" >&2
    fi
  fi
done

bash "$here/check-prerequisites.sh"
