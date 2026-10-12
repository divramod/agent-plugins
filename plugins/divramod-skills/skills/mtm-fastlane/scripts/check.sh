#!/usr/bin/env bash
# shellcheck source-path=SCRIPTDIR
# Validate what /mtm-fastlane configure wrote in the repository of <dir> (default .):
#   check.sh [<dir>]
# Both scripts present, executable, `bash -n` clean, shellcheck clean (when it is
# installed), with their header and no template placeholder left; the conf without
# placeholders and its FINGERPRINT current; then both scripts' --dry-run, whose
# output it prints (what the worktree script runs and skips for this branch).
# Exit 0 ok, 1 problems (each printed as `problem: ...`), 2 a missing tool.
set -euo pipefail
FASTLANE_HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=fastlane-lib.sh
. "$FASTLANE_HERE/fastlane-lib.sh"
dir="${1:-.}"
need git
repo_paths
problems=0
problem() { echo "problem: $*"; problems=$((problems + 1)); }

for script in "$worktree_script" "$top/$main_script"; do
  name=${script#"$top"/}
  if [ ! -f "$script" ]; then problem "$name is missing: run /mtm-fastlane configure"; continue; fi
  [ -x "$script" ] || problem "$name is not executable (chmod +x)"
  bash -n "$script" 2>/dev/null || problem "$name has a syntax error: bash -n $name"
  if command -v shellcheck >/dev/null 2>&1 && ! shellcheck -S warning "$script" >/dev/null; then
    problem "$name: shellcheck -S warning $name"
  fi
  grep -q '^# Replaces' "$script" || problem "$name has no '# Replaces' header line"
  ! grep -q -E '@[A-Z_]+@' "$script" || problem "$name still has template placeholders (@...@)"
done
if [ ! -f "$conf" ]; then
  problem ".hal/mtm-fastlane.conf is missing"
else
  ! grep -q -E '@[A-Z_]+@' "$conf" || problem ".hal/mtm-fastlane.conf still has template placeholders (@...@)"
  [ "$(conf_get FINGERPRINT "")" = "$(fingerprint)" ] \
    || problem "FINGERPRINT is stale: FINGERPRINT=$(fingerprint) (after committing the inputs)"
fi

if [ "$problems" = 0 ]; then
  base="origin/$default"
  git -C "$top" rev-parse -q --verify "$base" >/dev/null || base=HEAD
  echo "== $(basename "$worktree_script") --dry-run (FASTLANE_BASE=$base)"
  (cd "$top" && FASTLANE_BASE="$base" "$worktree_script" --dry-run) || problem "the worktree script's --dry-run failed"
  echo "== $main_script --dry-run"
  (cd "$top" && FASTLANE_BASE=HEAD FASTLANE_HEAD=HEAD "./$main_script" --dry-run) \
    || problem "the main script's --dry-run failed"
fi
[ "$problems" = 0 ] || exit 1
echo ok
