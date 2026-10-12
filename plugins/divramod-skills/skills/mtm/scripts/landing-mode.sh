#!/usr/bin/env bash
# How the worktree at <dir> (default .) lands: prints `ci` when
# .github/workflows/merge-to-main.yml or land.yml (its name before hal2 plan
# 0263) is in its HEAD or in origin's default branch (references/ci.md), else
# `local` (SKILL.md steps 1, 3, 4).
set -euo pipefail
dir="${1:-.}"
default=$(git -C "$dir" symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null || echo origin/main)
for ref in HEAD "$default"; do
  for file in merge-to-main.yml land.yml; do
    if git -C "$dir" cat-file -e "$ref:.github/workflows/$file" 2>/dev/null; then
      echo ci
      exit 0
    fi
  done
done
echo local
