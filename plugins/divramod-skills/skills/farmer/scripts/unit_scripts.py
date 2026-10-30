"""The skills unit's `scripts/` on the import path (`git_seed`, `skillpath`): a test of this folder that grows its
git tree through the shared seed imports this first (hal2 plan 0480 step 05.01). No test here."""

import sys
from pathlib import Path

UNIT_SCRIPTS = next(str(_p / "scripts") for _p in Path(__file__).resolve().parents if (_p / ".claude-plugin").is_dir())
if UNIT_SCRIPTS not in sys.path:
    sys.path.insert(0, UNIT_SCRIPTS)
