#!/usr/bin/env bash
# Check the tools /mtm-fastlane needs. Exit 1 when a required tool is missing.
missing=0
for tool in git bash jq; do
  if command -v "$tool" >/dev/null 2>&1; then
    echo "ok $tool"
  else
    echo "MISSING $tool -> brew install $tool (or: sudo apt-get install -y $tool)"
    missing=1
  fi
done
if command -v hal2-cli-git >/dev/null 2>&1 && hal2-cli-git --help 2>&1 | grep -q -- '--local'; then
  echo "ok hal2-cli-git"
else
  echo "optional hal2-cli-git (with merge-to-main --local; without it the fastlane lands with plain git) -> cargo install --git https://github.com/divramod/hal2 hal2-cli-git"
fi
for tool in gh glab shellcheck; do
  if command -v "$tool" >/dev/null 2>&1; then
    echo "ok $tool"
  else
    case "$tool" in
      gh) why="stopping land runs on GitHub" ;;
      glab) why="stopping land pipelines on GitLab" ;;
      shellcheck) why="configure's check of the two scripts" ;;
    esac
    echo "optional $tool ($why) -> brew install $tool"
  fi
done
exit "$missing"
