#!/usr/bin/env bash
# Install the fix-loc scripts' missing tools, then check them.
set -u
here="$(cd "$(dirname "$0")" && pwd)"
for tool in python3 git scc; do
  command -v "$tool" >/dev/null 2>&1 && continue
  formula="$tool"; [ "$tool" = python3 ] && formula=python
  if command -v brew >/dev/null 2>&1; then
    brew install "$formula"
  elif [ "$tool" = scc ]; then
    echo "scc: install it from https://github.com/boyter/scc/releases" >&2
  else
    sudo apt-get install -y "$tool"
  fi
done
for tool in hal2-cli-agents hal2-cli-git; do
  if ! command -v "$tool" >/dev/null 2>&1 && [ -d "$HOME/a/hal2/code/rust" ]; then
    (cd "$HOME/a/hal2/code/rust" && cargo install --path "apps/$tool")
  fi
done
exec "$here/check-prerequisites.sh"
