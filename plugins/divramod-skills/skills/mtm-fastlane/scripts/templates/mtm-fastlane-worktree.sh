#!/usr/bin/env bash
# The fastlane's worktree checks of @REPO@ (/mtm-fastlane configure, @DATE@).
# Replaces, while CI does not work: @REPLACES@
# Skipped (they need @SKIPPED_NEEDS@): @SKIPPED@
# CI checks them once it works again: @CI_COMMAND@
# Runs only what the branch changed since $FASTLANE_BASE (fastlane.sh checks sets it),
# natively on this machine; --dry-run lists what it would run and what it skips.
set -euo pipefail
base="${FASTLANE_BASE:-origin/main}"
dry_run=0
[ "${1:-}" = --dry-run ] && dry_run=1
changed=$(git diff --name-only "$base"...HEAD)

touches() { echo "$changed" | grep -q -E "$1"; } # touches <ERE over the changed paths>
step() { # step <name> <command...>
  if [ "$dry_run" = 1 ]; then echo "would run: $1"; return 0; fi
  echo "== $1"
  shift
  "$@"
}
skip() { echo "skipped: $1 ($2)"; } # skip <job> <why>

# The checks (configure writes them), e.g.:
#   if touches '^code/rust/'; then step rust-test cargo nextest run -p <crate>; fi
#   skip linux-e2e "needs Linux and Docker"
@CHECKS@
