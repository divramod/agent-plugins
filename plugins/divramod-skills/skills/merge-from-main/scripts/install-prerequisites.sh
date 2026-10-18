#!/usr/bin/env bash
# Install the tools /mfm and /mtm need that are missing, then re-check.
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

if ! command -v hal2-cli-git >/dev/null 2>&1 || ! hal2-cli-git --help | grep -q 'merge-to-main .*--json'; then
  if ! command -v cargo >/dev/null 2>&1; then
    echo "install Rust first (https://rustup.rs), then rerun this script" >&2
  elif [ -d "$HOME/a/hal2/code/rust/apps/hal2-cli-git" ]; then
    cargo install --path "$HOME/a/hal2/code/rust/apps/hal2-cli-git"
  else
    cargo install --git https://github.com/divramod/hal2 hal2-cli-git
  fi
fi

bash "$here/check-prerequisites.sh"
