#!/usr/bin/env bash
# shellcheck source-path=SCRIPTDIR
# The fastlane's landing without hal2 (fastlane.sh land): the worktree <dir>'s
# HEAD, which must contain origin/<default>, lands as one merge commit of HEAD's
# tree on origin/<default> + HEAD, pushed fast-forward to the default branch;
# then the worktree is reset to it, the main checkout pulled when it is clean on
# the default branch, and the side branches <branch>-* it contains deleted.
# Needs the lock (fastlane.sh reserve). Exit 0 landed or nothing to land,
# 1 not runnable, 3 origin/<default> moved (merge it in and rerun).
set -euo pipefail
FASTLANE_HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=fastlane-lib.sh
. "$FASTLANE_HERE/fastlane-lib.sh"
dir="${1:-.}"
repo_paths

[ "$(cat "$(lock_dir)/worktree" 2>/dev/null)" = "$top" ] || die 1 "this worktree holds no lock: fastlane.sh reserve first"
[ -n "$branch" ] || die 1 "$top is not on a branch"
[ -z "$(git -C "$top" status --porcelain)" ] || die 1 "uncommitted changes in $top: commit them first"
git -C "$top" fetch -q origin "$default" || die 1 "git fetch origin $default failed"
target="origin/$default"

if git -C "$top" merge-base --is-ancestor HEAD "$target"; then
  echo "nothing to land: $target contains $branch"
  exit 0
fi
git -C "$top" merge-base --is-ancestor "$target" HEAD \
  || die 3 "$target is not merged into $branch: merge it in (fastlane step 4) and rerun"

sha=$(git -C "$top" commit-tree "HEAD^{tree}" -p "$target" -p HEAD \
  -m "Merge branch '$branch' (fastlane: CI skipped)")
git -C "$top" push -q origin "$sha:refs/heads/$default" \
  || die 3 "the push to $default was refused ($default moved): merge $target in again and rerun"
git -C "$top" fetch -q origin "$default"
git -C "$top" reset -q --hard "$target"
echo "pushed: ${sha:0:9} to $default"

if [ "$(git -C "$main_checkout" symbolic-ref --quiet --short HEAD 2>/dev/null)" = "$default" ] \
  && [ -z "$(git -C "$main_checkout" status --porcelain)" ]; then
  git -C "$main_checkout" merge -q --ff-only "$target" && echo "main checkout: pulled"
else
  echo "main checkout: not pulled (not clean on $default)"
fi

for side in $(git -C "$top" branch --merged "$target" --format '%(refname:short)'); do
  case "$side" in
    "$branch"-*) git -C "$top" branch -q -d "$side" && echo "branch deleted: $side" ;;
  esac
done
