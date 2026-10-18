#!/usr/bin/env bash
# Kept for the documented command `scripts/link-skills.sh [--unlink]`: the one installer is install-skills.py, which
# also finds skills in category folders and prunes links that went dangling (plan 0360, D20).
exec python3 "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/install-skills.py" "$@"
