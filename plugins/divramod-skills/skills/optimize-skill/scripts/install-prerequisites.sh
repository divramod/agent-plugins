#!/usr/bin/env bash
# Install optimize-skill's missing tools, then check them.
set -u
here="$(cd "$(dirname "$0")" && pwd)"
if ! command -v python3 >/dev/null 2>&1; then
  if command -v brew >/dev/null 2>&1; then brew install python; else sudo apt-get install -y python3; fi
fi
if ! command -v claude >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; then
  npm install -g @anthropic-ai/claude-code
fi
exec "$here/check-prerequisites.sh"
