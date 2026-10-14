#!/usr/bin/env bash
# Check the tools the wagon master's scripts need: they run on the farmer skill's round frame (farmer_frame.py), so
# the tools are that skill's (python3, git, gh, hal2-cli-git, hal2-cli-agents). Exit 1 when a required tool is missing.
here="$(cd "$(dirname "$0")" && pwd)"
frame="$here/../../farmer/scripts"
if [ ! -f "$frame/tick.py" ]; then
  echo "MISSING the farmer skill's scripts ($frame) -> install the skill farmer beside wagon-master"
  exit 1
fi
exec "$frame/check-prerequisites.sh"
