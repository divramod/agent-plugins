#!/usr/bin/env bash
# Install the tools this skill's scripts need that are missing, then re-check.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

for tool in git python3; do
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

for tool in hal2-cli-agents hal2-cli-git; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    if ! command -v cargo >/dev/null 2>&1; then
      echo "install Rust first (https://rustup.rs), then rerun this script" >&2
    elif [ -d "$HOME/a/hal2/code/rust/apps/$tool" ]; then
      cargo install --path "$HOME/a/hal2/code/rust/apps/$tool"
    else
      cargo install --git https://github.com/divramod/hal2 "$tool"
    fi
  fi
done

bash "$here/check-prerequisites.sh"
