"""The farmer skill's frame (and the daybook's scripts) on the import path (hal2 plan 0311, D1, D4).

lookout's timer is the farmer's `timer.py` with a `roles.Wiring`, exactly as the wagon master's is
(`tollman/scripts/farmer_frame.py`): every script and test of this folder that needs `timer`, `roles`, `due` or
(from the daybook skill, when it is installed beside this one) `watchfile` imports this module first, then those by
name. The farmer's scripts go in front (no module name exists in both folders), the daybook's go behind, so a
module of lookout's own always wins.
"""

import sys
from pathlib import Path

sys.path.insert(0, next(str(_p / "scripts") for _p in Path(__file__).resolve().parents if (_p / ".claude-plugin").is_dir()))
from skillpath import sibling  # noqa: E402  (the skills unit's scripts/, plan 0360 D20)
FARMER = sibling("farmer") / "scripts"
try:
    DAYBOOK = sibling("daybook") / "scripts"
except FileNotFoundError:
    DAYBOOK = None
if str(FARMER) not in sys.path:
    sys.path.insert(0, str(FARMER))
if DAYBOOK and DAYBOOK.is_dir() and str(DAYBOOK) not in sys.path:
    sys.path.append(str(DAYBOOK))
