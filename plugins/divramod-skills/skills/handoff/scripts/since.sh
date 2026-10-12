#!/usr/bin/env bash
# What changed since a handoff was written: commits after its `written at` sha (a plan's handoff.md: its front
# matter's `at`), ignoring the commit that wrote the handoff, and uncommitted changes.
# Usage: since.sh [handoff file]   (default: this checkout's, as where.py names it: the current plan's
#                                   plans/<plan>/handoff.md, else the root HANDOFF.md)
# Exit 0: report printed. Exit 1: no handoff or no stamp. Exit 2: git missing.
set -euo pipefail

if ! command -v git >/dev/null 2>&1; then
  echo "since.sh: git is missing; run install-prerequisites.sh" >&2
  exit 2
fi

file="${1:-}"
if [[ -z "$file" ]]; then
  top="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
  file="$top/$(python3 "$(dirname "$0")/where.py" --root "$top" 2>/dev/null || echo HANDOFF.md)"
fi
if [[ ! -f "$file" ]]; then
  echo "since.sh: $file does not exist" >&2
  exit 1
fi
sha="$(sed -n 's/.*[Ww]ritten at `\([0-9a-f]\{7,40\}\)`.*/\1/p' "$file" | head -1)"
if [[ -z "$sha" && "$(head -1 "$file")" == "---" ]]; then
  sha="$(sed -n '2,/^---$/s/^at:[[:space:]]*["'"'"']\{0,1\}\([0-9a-f]\{7,40\}\)["'"'"']\{0,1\}[[:space:]]*$/\1/p' "$file" | head -1)"
fi
if [[ -z "$sha" ]]; then
  echo "since.sh: $file has no 'Written at \`<sha>\`' stamp (a plan's handoff.md: no \`at: <sha>\`)" >&2
  exit 1
fi
if ! git cat-file -e "$sha^{commit}" 2>/dev/null; then
  echo "written at $sha, which is not in this repository (rewritten history?)"
  exit 0
fi

# The commit that wrote the handoff (maybe together with other docs) is part of the handoff, not drift.
own="$(git log -1 --format=%h -- "$file")"
commits="$(git log --oneline "$sha..HEAD" | grep -v "^$own " || true)"
changes="$(git status --short)"
echo "written at $sha"
if [[ -z "$commits" ]]; then
  echo "commits since: none"
else
  echo "commits since:"
  echo "$commits" | sed 's/^/  /'
fi
if [[ -z "$changes" ]]; then
  echo "uncommitted: none"
else
  echo "uncommitted:"
  echo "$changes" | sed 's/^/  /'
fi
