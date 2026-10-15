#!/usr/bin/env bash
# Install the tools /hv needs that are missing (python3, hal2-cli-voiceink, hal2-cli-halverse), then re-check.
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

if ! command -v hal2-cli-voiceink >/dev/null 2>&1; then
  if ! command -v cargo >/dev/null 2>&1; then
    echo "install Rust first (https://rustup.rs), then rerun this script" >&2
  elif [ -d "$HOME/a/hal2/code/rust/apps/hal2-cli-voiceink" ]; then
    (cd "$HOME/a/hal2/code/rust" && cargo install --path apps/hal2-cli-voiceink)
  else
    cargo install --git https://github.com/divramod/hal2 hal2-cli-voiceink
  fi
fi

if ! command -v hal2-cli-halverse >/dev/null 2>&1; then
  if ! command -v cargo >/dev/null 2>&1; then
    echo "install Rust first (https://rustup.rs), then rerun this script" >&2
  elif [ -d "$HOME/a/hal2/code/rust/apps/hal2-cli-halverse" ]; then
    (cd "$HOME/a/hal2/code/rust" && cargo install --path apps/hal2-cli-halverse)
  else
    cargo install --git https://github.com/divramod/hal2 hal2-cli-halverse
  fi
fi

bash "$here/check-prerequisites.sh"
