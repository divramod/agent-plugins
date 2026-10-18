#!/usr/bin/env bash
# Install the required tools of the uat call that are missing (python3, git), then re-check. hal2-cli-plans comes from
# the hal2 repository (cargo install --path code/rust/apps/hal2-cli-plans): this script only reports it.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

for pair in python3:python git:git; do
  tool="${pair%%:*}"; pkg="${pair##*:}"
  if ! command -v "$tool" >/dev/null 2>&1; then
    if command -v brew >/dev/null 2>&1; then
      brew install "$pkg"
    elif command -v apt-get >/dev/null 2>&1; then
      sudo apt-get install -y "$([ "$tool" = python3 ] && echo python3 || echo "$pkg")"
    else
      echo "install $tool manually: neither brew nor apt-get is available" >&2
    fi
  fi
done

bash "$here/check-prerequisites.sh"
