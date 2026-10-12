#!/usr/bin/env bash
# Install the tools the pause scripts need that are missing, then re-check.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

install() { # <brew formula> <apt package>
  if command -v brew >/dev/null 2>&1; then
    brew install "$1"
  elif command -v apt-get >/dev/null 2>&1; then
    sudo apt-get install -y "$2"
  else
    echo "install $2 manually: neither brew nor apt-get is available" >&2
  fi
}

command -v python3 >/dev/null 2>&1 || install python python3
command -v ps >/dev/null 2>&1 || install procps procps
command -v git >/dev/null 2>&1 || install git git

bash "$here/check-prerequisites.sh"
