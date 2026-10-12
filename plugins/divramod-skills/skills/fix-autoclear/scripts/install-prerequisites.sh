#!/usr/bin/env bash
# Install the fix-autoclear scripts' missing tools, then check them.
set -u
here="$(cd "$(dirname "$0")" && pwd)"
if ! command -v python3 >/dev/null 2>&1; then
  if command -v brew >/dev/null 2>&1; then brew install python; else sudo apt-get install -y python3; fi
fi
if ! command -v hal2-cli-agents >/dev/null 2>&1 && [ -d "$HOME/a/hal2/code/rust" ]; then
  (cd "$HOME/a/hal2/code/rust" && cargo install --path apps/hal2-cli-agents)
fi
exec "$here/check-prerequisites.sh"
