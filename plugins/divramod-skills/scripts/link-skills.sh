#!/usr/bin/env bash
set -euo pipefail

# Dev install for maintainers: symlink every skill in skills/ into the local
# skill directories that the agent harnesses read:
#   - ~/.claude/skills: Claude Code (OpenCode and Grok read it too)
#   - ~/.agents/skills: Codex, OpenCode, Grok and other Agent Skills harnesses
# Each entry is a symlink into this repo, so edits and `git pull` are live.
# Do not combine this with the plugin install: you would get every skill twice.
#
# Usage: scripts/link-skills.sh [--unlink]

REPO="$(cd "$(dirname "$0")/.." && pwd)"
DESTS=("$HOME/.claude/skills" "$HOME/.agents/skills")
MODE="${1:-link}"

for skill_md in "$REPO"/skills/*/SKILL.md; do
  src="$(dirname "$skill_md")"
  name="$(basename "$src")"
  for dest in "${DESTS[@]}"; do
    target="$dest/$name"
    if [ "$MODE" = "--unlink" ]; then
      if [ -L "$target" ]; then rm "$target" && echo "unlinked $target"; fi
      continue
    fi
    mkdir -p "$dest"
    if [ -e "$target" ] && [ ! -L "$target" ]; then
      echo "skip $target: exists and is not a symlink" >&2
      continue
    fi
    ln -sfn "$src" "$target"
    echo "linked $target -> $src"
  done
done
