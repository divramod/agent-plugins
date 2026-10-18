#!/usr/bin/env bash
# Install the bundled checks' missing tools (python3, hal2-cli-email from a hal2 checkout), then check them.
set -u
here="$(cd "$(dirname "$0")" && pwd)"
if ! command -v python3 >/dev/null 2>&1; then
  if command -v brew >/dev/null 2>&1; then brew install python; else sudo apt-get install -y python3; fi
fi
if ! command -v hal2-cli-email >/dev/null 2>&1 && [ -d "$HOME/a/hal2/code/rust/apps/hal2-cli-email" ]; then
  (cd "$HOME/a/hal2/code/rust" && cargo install --path apps/hal2-cli-email)
fi
exec "$here/check-prerequisites.sh"
