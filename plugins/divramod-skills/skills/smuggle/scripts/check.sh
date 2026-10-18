#!/usr/bin/env bash
# shellcheck source-path=SCRIPTDIR
# Validate what /smuggle configure wrote in the repository of <dir> (default .):
#   check.sh [<dir>]
# Both scripts present, executable, `bash -n` clean, shellcheck clean (when it is
# installed), with their header and no template placeholder left; the conf without
# placeholders and its FINGERPRINT current; .hal/smuggle.toml, when there, readable at HEAD and without
# placeholders (units.py); then both scripts' --dry-run, whose
# output it prints (what the worktree script runs and skips for this branch).
# Exit 0 ok, 1 problems (each printed as `problem: ...`), 2 a missing tool.
set -euo pipefail
SMUGGLE_HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=smuggle-lib.sh
. "$SMUGGLE_HERE/smuggle-lib.sh"
dir="${1:-.}"
need git
repo_paths
problems=0
problem() { echo "problem: $*"; problems=$((problems + 1)); }

for script in "$worktree_script" "$top/$main_script"; do
  name=${script#"$top"/}
  if [ ! -f "$script" ]; then problem "$name is missing: run /smuggle configure"; continue; fi
  [ -x "$script" ] || problem "$name is not executable (chmod +x)"
  bash -n "$script" 2>/dev/null || problem "$name has a syntax error: bash -n $name"
  if command -v shellcheck >/dev/null 2>&1 && ! shellcheck -S warning "$script" >/dev/null; then
    problem "$name: shellcheck -S warning $name"
  fi
  grep -q '^# Replaces' "$script" || problem "$name has no '# Replaces' header line"
  ! grep -q -E '@[A-Z_]+@' "$script" || problem "$name still has template placeholders (@...@)"
done
if [ ! -f "$conf" ]; then
  problem ".hal/smuggle.conf is missing"
else
  ! grep -q -E '@[A-Z_]+@' "$conf" || problem ".hal/smuggle.conf still has template placeholders (@...@)"
  [ "$(conf_get FINGERPRINT "")" = "$(fingerprint)" ] \
    || problem "FINGERPRINT is stale: FINGERPRINT=$(fingerprint) (after committing the inputs)"
fi

units="$top/.hal/smuggle.toml"
if [ ! -f "$units" ]; then
  echo "note: no .hal/smuggle.toml: no unit list, so a smuggle never warns about what it changes"
elif grep -q -E '@[A-Z_]+@' "$units"; then
  problem ".hal/smuggle.toml still has template placeholders (@...@)"
elif ! python3 "$SMUGGLE_HERE/units.py" touched --repo "$top" --base HEAD >/dev/null; then
  problem ".hal/smuggle.toml cannot be read at HEAD (committed? TOML?): python3 units.py touched"
fi

if [ "$problems" = 0 ]; then
  base="origin/$default"
  git -C "$top" rev-parse -q --verify "$base" >/dev/null || base=HEAD
  echo "== $(basename "$worktree_script") --dry-run (SMUGGLE_BASE=$base)"
  (cd "$top" && SMUGGLE_BASE="$base" "$worktree_script" --dry-run) || problem "the worktree script's --dry-run failed"
  echo "== $main_script --dry-run"
  (cd "$top" && SMUGGLE_BASE=HEAD SMUGGLE_HEAD=HEAD "./$main_script" --dry-run) \
    || problem "the main script's --dry-run failed"
fi
[ "$problems" = 0 ] || exit 1
echo ok
