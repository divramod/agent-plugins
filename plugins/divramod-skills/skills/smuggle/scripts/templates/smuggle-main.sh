#!/usr/bin/env bash
# The smuggle's after-landing work of @REPO@ on the default branch (/smuggle configure, @DATE@).
# Replaces, while CI does not work: @REPLACES@
# Runs in the main checkout (or <worktrees>/.smuggle) at $SMUGGLE_HEAD, the landed commit;
# $SMUGGLE_BASE is the default branch before the landing. --dry-run lists what it would run.
set -euo pipefail
base="${SMUGGLE_BASE:?smuggle.sh main sets SMUGGLE_BASE}"
head="${SMUGGLE_HEAD:?smuggle.sh main sets SMUGGLE_HEAD}"
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
