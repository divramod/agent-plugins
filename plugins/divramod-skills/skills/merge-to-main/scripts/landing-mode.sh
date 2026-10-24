#!/usr/bin/env bash
# How the worktree at <dir> (default .) lands: prints `ci` when
# .github/workflows/merge-to-main-local.yml, merge-to-main-cloud.yml (plan 0423 D4) or one of their older names
# dev-merge-to-main.yml, merge-to-main.yml is in its HEAD or in
# origin's default branch (references/ci.md), else
# `local` (SKILL.md steps 1, 3, 4).
set -euo pipefail
dir="${1:-.}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
u="$here"; until [ -d "$u/.claude-plugin" ] || [ "$u" = / ]; do u="$(dirname "$u")"; done
if [ -f "$u/scripts/landing-workflow.sh" ]; then
  . "$u/scripts/landing-workflow.sh"  # LANDING_WORKFLOWS, landing_workflow_order <dir> (plan 0423 D4)
else  # outside a skills unit (a copied script): the names, no setting
  LANDING_WORKFLOWS="merge-to-main-local.yml merge-to-main-cloud.yml dev-merge-to-main.yml merge-to-main.yml"
  landing_workflow_order() { printf '%s\n' $LANDING_WORKFLOWS; }
fi
default=$(git -C "$dir" symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null || echo origin/main)
for ref in HEAD "$default"; do
  for file in $LANDING_WORKFLOWS; do
    if git -C "$dir" cat-file -e "$ref:.github/workflows/$file" 2>/dev/null; then
      echo ci
      exit 0
    fi
  done
done
echo local
