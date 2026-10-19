"""The farmer skill's round frame on the import path (hal2 plan 0377, D10).

/prune's scripts use the farmer skill's modules as the tollman does (`tick`, `logstate`, `mtm_scan`, `lead_marker`,
`roles`): every script and test of this folder imports this module first, then those by name. The skills unit's
`skillpath.sibling` finds the farmer skill in the source layout and in the published one. No module name exists in
both folders.
"""

import sys
from pathlib import Path

sys.path.insert(0, next(str(_p / "scripts") for _p in Path(__file__).resolve().parents if (_p / ".claude-plugin").is_dir()))
from skillpath import sibling  # noqa: E402  (the skills unit's scripts/, plan 0360 D20)
SCRIPTS = sibling("farmer") / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
