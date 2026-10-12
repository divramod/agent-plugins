#!/usr/bin/env bash
# The guard before a landing through CI (references/ci.md): a repository whose landing workflow is
# .github/workflows/merge-to-main.yml needs a hal2-cli-git that knows that name. One that knows only land.yml (the
# name before hal2 plan 0263) finds no workflow, takes the repository for one without CI and lands the worktree
# as a plain merge, untested, or waits for a land.yml run that never comes.
#   check-landing-cli.sh [<dir>]     <dir>: the worktree that lands (default .)
# It looks where hal2-cli-git looks when it starts: the worktree's HEAD and origin's default branch. What the CLI
# knows is read from its help: `hal2-cli-git --help` of one that reads both names says merge-to-main.yml, an older
# one's does not. No version number is compared: both report the same one until a landing bumps it.
# Exit 0: go on (no merge-to-main.yml here, or the CLI knows it).
# Exit 8: the installed CLI does not know it: nothing may land, stop and tell the user. 8 because the guard runs
#   in front of the landing (`check-landing-cli.sh && hal2-cli-git worktree merge-to-main ...`), whose exits are
#   0 to 6 (land-runs.sh: 7).
# Exit 2: git or hal2-cli-git is missing, or <dir> is no git checkout.
set -euo pipefail
dir="${1:-.}"
file=.github/workflows/merge-to-main.yml
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if ! command -v git >/dev/null 2>&1; then
  echo "check-landing-cli.sh: git is missing -> bash $here/install-prerequisites.sh" >&2
  exit 2
fi
if ! git -C "$dir" rev-parse --git-dir >/dev/null 2>&1; then
  echo "check-landing-cli.sh: $dir is no git checkout: pass the directory of the worktree that lands" >&2
  exit 2
fi
default=$(git -C "$dir" symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null || echo origin/main)
found=""
for ref in HEAD "$default"; do
  if git -C "$dir" cat-file -e "$ref:$file" 2>/dev/null; then
    found="${found:+$found and }$ref"
  fi
done
[ -n "$found" ] || exit 0
if ! command -v hal2-cli-git >/dev/null 2>&1; then
  echo "check-landing-cli.sh: hal2-cli-git is missing -> bash $here/install-prerequisites.sh" >&2
  exit 2
fi
# Read whole, never piped into `grep -q`: grep ends at the first match, the CLI's next write fails and pipefail
# would report a CLI that knows the name as one that does not.
help=$(hal2-cli-git --help 2>&1) || true
case "$help" in
  *merge-to-main.yml*) exit 0 ;;
esac
version=$(hal2-cli-git --version 2>/dev/null | head -n 1) || true
cat >&2 <<MSG
check-landing-cli.sh: nothing was landed. The installed hal2-cli-git does not know the landing workflow
$file (in $found): $(command -v hal2-cli-git) (${version:-version unknown}).
It knows only land.yml and would land this worktree as a plain merge, untested, or wait for a run that never comes.
Install the current hal2-cli-git, then run /mtm again:
  cargo install --locked --path <hal2 checkout>/code/rust/apps/hal2-cli-git    (a hal2 checkout that has merge-to-main.yml)
  cargo install --locked --git https://github.com/divramod/hal2 hal2-cli-git   (without one)
MSG
exit 8
