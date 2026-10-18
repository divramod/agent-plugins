#!/usr/bin/env bash
# Install lookout's missing tools and its bundled checks' (checks/), then check them.
set -u
here="$(cd "$(dirname "$0")" && pwd)"
if ! command -v python3 >/dev/null 2>&1; then
  if command -v brew >/dev/null 2>&1; then brew install python; else sudo apt-get install -y python3; fi
fi
if [ "$(uname -s)" = Darwin ] && ! command -v terminal-notifier >/dev/null 2>&1 && command -v brew >/dev/null 2>&1; then
  brew install terminal-notifier
fi
if ! command -v hal2-cli-secrets >/dev/null 2>&1 && [ -d "$HOME/a/hal2/code/rust" ]; then
  (cd "$HOME/a/hal2/code/rust" && cargo install --path apps/hal2-cli-secrets)
fi
"$here/checks/install-prerequisites.sh" >/dev/null || true
exec "$here/check-prerequisites.sh"
