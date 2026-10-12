#!/usr/bin/env bash
# Install the merge-to-main-boss scripts' missing tools, then check them.
set -u
here="$(cd "$(dirname "$0")" && pwd)"
for tool in python3 git; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    pkg=$([ "$tool" = python3 ] && echo python || echo git)
    if command -v brew >/dev/null 2>&1; then brew install "$pkg"; else sudo apt-get install -y "$tool"; fi
  fi
done
for app in hal2-cli-git hal2-cli-agents; do
  if ! command -v "$app" >/dev/null 2>&1 && [ -d "$HOME/a/hal2/code/rust" ]; then
    (cd "$HOME/a/hal2/code/rust" && cargo install --path "apps/$app")
  fi
done
if ! command -v gh >/dev/null 2>&1 && command -v brew >/dev/null 2>&1; then brew install gh; fi
exec "$here/check-prerequisites.sh"
