#!/usr/bin/env bash
# Install the tools /work-manual needs that are missing, then re-check.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v python3 >/dev/null 2>&1; then
  if command -v brew >/dev/null 2>&1; then
    brew install python3
  elif command -v apt-get >/dev/null 2>&1; then
    sudo apt-get install -y python3
  else
    echo "install python3 manually: neither brew nor apt-get is available" >&2
  fi
fi

app=hal2-cli-plans
if ! command -v "$app" >/dev/null 2>&1; then
  if ! command -v cargo >/dev/null 2>&1; then
    echo "$app needs Rust (https://rustup.rs)" >&2
  elif [ -d "$HOME/a/hal2/code/rust/apps/$app" ]; then
    (cd "$HOME/a/hal2/code/rust" && cargo install --path "apps/$app")
  else
    cargo install --git https://github.com/divramod/hal2 "$app"
  fi
fi

bash "$here/check-prerequisites.sh"
