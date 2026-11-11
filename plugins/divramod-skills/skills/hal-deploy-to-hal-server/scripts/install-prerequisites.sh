#!/usr/bin/env bash
# Install hal-deploy-to-hal-server's missing tools (python3), then check them.
set -u
here="$(cd "$(dirname "$0")" && pwd)"
if ! command -v python3 >/dev/null 2>&1; then
  if command -v brew >/dev/null 2>&1; then brew install python; else sudo apt-get install -y python3; fi
fi
exec "$here/check-prerequisites.sh"
