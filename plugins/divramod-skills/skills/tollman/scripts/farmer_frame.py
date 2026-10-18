"""The farmer skill's round frame on the import path (hal2 plan 0294, D7).

The tollman's rounds run on the frame the farmer skill keeps (`tick`, `wake`, `timer`, `due`, `acks`,
`deliver`, `roles`, `role_cli`, `mtm_scan`, `mtm_ci`, `lead_marker`): every script and test of this folder imports
this module first, then those by name. No module name exists in both folders.
"""

import sys
from pathlib import Path

sys.path.insert(0, next(str(_p / "scripts") for _p in Path(__file__).resolve().parents if (_p / ".claude-plugin").is_dir()))
from skillpath import sibling  # noqa: E402  (the skills unit's scripts/, plan 0360 D20)
SCRIPTS = sibling("farmer") / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
