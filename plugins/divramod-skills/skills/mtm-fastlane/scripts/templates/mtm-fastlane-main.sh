#!/usr/bin/env bash
# The fastlane's after-landing work of @REPO@ on the default branch (/mtm-fastlane configure, @DATE@).
# Replaces, while CI does not work: @REPLACES@
# Runs in the main checkout (or <worktrees>/.fastlane) at $FASTLANE_HEAD, the landed commit;
# $FASTLANE_BASE is the default branch before the landing. --dry-run lists what it would run.
set -euo pipefail
base="${FASTLANE_BASE:?fastlane.sh main sets FASTLANE_BASE}"
head="${FASTLANE_HEAD:?fastlane.sh main sets FASTLANE_HEAD}"
dry_run=0
[ "${1:-}" = --dry-run ] && dry_run=1
changed=$(git diff --name-only "$base" "$head")

touches() { echo "$changed" | grep -q -E "$1"; } # touches <ERE over the landed paths>
step() { # step <name> <command...>
  if [ "$dry_run" = 1 ]; then echo "would run: $1"; return 0; fi
  echo "== $1"
  shift
  "$@"
}

# The after-landing work (configure writes it), e.g.:
#   step version-tags git push origin <tags of the bumped versions>
#   if touches '^code/rust/apps/'; then step deliver ./scripts/deliver.sh; fi
@STEPS@
