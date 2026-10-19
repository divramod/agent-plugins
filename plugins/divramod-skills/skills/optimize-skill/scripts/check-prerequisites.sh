#!/usr/bin/env bash
# Check the tools optimize-skill needs. Exit 1 when a required tool is missing.
# Optional: git (best.diff is relative to the skill's git root and applied with git apply).
missing=0
if command -v python3 >/dev/null 2>&1; then
  echo "ok python3"
else
  echo "MISSING python3 -> brew install python (or: sudo apt-get install -y python3)"
  missing=1
fi
if [ -n "${OPTIMIZE_SKILL_CLAUDE:-}" ] || command -v claude >/dev/null 2>&1; then
  echo "ok claude"
else
  echo "MISSING claude -> npm install -g @anthropic-ai/claude-code"
  missing=1
fi
if command -v git >/dev/null 2>&1; then
  echo "ok git"
else
  echo "MISSING git (optional: applying best.diff) -> brew install git (or: sudo apt-get install -y git)"
fi
exit "$missing"
