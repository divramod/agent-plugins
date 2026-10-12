#!/usr/bin/env bash
# Install the tools /mtm-fastlane needs that are missing, then re-check.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

for tool in git bash jq; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    if command -v brew >/dev/null 2>&1; then
      brew install "$tool"
    elif command -v apt-get >/dev/null 2>&1; then
      sudo apt-get install -y "$tool"
    else
      echo "install $tool manually: neither brew nor apt-get is available" >&2
    fi
  fi
done
# gh or glab only for the provider origin is on.
origin=$(git remote get-url origin 2>/dev/null || true)
case "$origin" in
  *github.com*) tool=gh ;;
  *gitlab*) tool=glab ;;
  *) tool="" ;;
esac
if [ -n "$tool" ] && ! command -v "$tool" >/dev/null 2>&1 && command -v brew >/dev/null 2>&1; then
  brew install "$tool"
fi

bash "$here/check-prerequisites.sh"
