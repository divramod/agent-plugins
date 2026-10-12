#!/usr/bin/env bash
# Install the tools /digest-todolist-picture needs that are missing, then re-check.
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

for app in hal2-cli-shooter hal2-cli-agents; do
  if ! command -v "$app" >/dev/null 2>&1; then
    if ! command -v cargo >/dev/null 2>&1; then
      echo "optional $app needs Rust (https://rustup.rs); shots.py works without it" >&2
    elif [ -d "$HOME/a/hal2/code/rust/apps/$app" ]; then
      cargo install --path "$HOME/a/hal2/code/rust/apps/$app"
    else
      cargo install --git https://github.com/divramod/hal2 "$app"
    fi
  fi
done

bash "$here/check-prerequisites.sh"
