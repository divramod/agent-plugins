#!/usr/bin/env bash
# Install the wagon master's scripts' missing tools (the farmer skill's: its round frame runs them), then check them.
here="$(cd "$(dirname "$0")" && pwd)"
if [ -x "$here/../../farmer/scripts/install-prerequisites.sh" ]; then
  "$here/../../farmer/scripts/install-prerequisites.sh" >/dev/null
fi
exec "$here/check-prerequisites.sh"
