#!/usr/bin/env bash
# Install what check-prerequisites.sh reports missing (ps, lsof, launchctl ship with macOS).
dir="$(cd "$(dirname "$0")" && pwd)"
if ! command -v python3 >/dev/null; then
  if command -v brew >/dev/null; then brew install python; elif command -v apt-get >/dev/null; then sudo apt-get install -y python3; fi
fi
exec bash "$dir/check-prerequisites.sh"
