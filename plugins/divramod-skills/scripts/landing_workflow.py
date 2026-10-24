"""Which landing workflow file a checkout has (hal2 plan 0423, decision D4). The Python twin of landing-workflow.sh.

The names, in the order they are tried: the setting's file (`.hal/landing.toml` `workflow = "local"|"cloud"`;
$HAL2_LAND_WORKFLOW=local|cloud beats it), the other new file, then the old names, which stay found during the
migration. No setting: local first. Stdlib only; a skill puts the unit's scripts/ on sys.path (see skillpath).

    NAMES                          every name, the order with no setting
    setting(root, env=None)        "local", "cloud" or ""
    order(setting="")              the names in the order to try
    pick(root, env=None)           the first name the checkout has, else None
    pick_where(has, setting="")    the first name `has(name)` accepts (a ref's files), else None
"""
import os
import re
from pathlib import Path

NEW = ("merge-to-main-local.yml", "merge-to-main-cloud.yml")
OLD = ("dev-merge-to-main.yml", "merge-to-main.yml")
NAMES = NEW + OLD
_KEY = re.compile(r'^\s*workflow\s*=\s*"(local|cloud)"', re.MULTILINE)


def parse(text: str) -> str:
    """The `workflow` key of a landing.toml's text: local, cloud or ``."""
    m = _KEY.search(text or "")
    return m.group(1) if m else ""


def setting(root, env=None, text=None) -> str:
    """The choice: the env var, else `.hal/landing.toml` (its `text` when given, else read under root)."""
    value = (os.environ if env is None else env).get("HAL2_LAND_WORKFLOW", "")
    if value in ("local", "cloud"):
        return value
    if text is None:
        try:
            text = Path(root, ".hal", "landing.toml").read_text()
        except OSError:
            text = ""
    return parse(text)


def order(choice: str = "") -> tuple:
    return (NEW[1], NEW[0]) + OLD if choice == "cloud" else NAMES


def pick_where(has, choice: str = ""):
    return next((name for name in order(choice) if has(name)), None)


def pick(root, env=None):
    return pick_where(lambda name: Path(root, ".github", "workflows", name).is_file(), setting(root, env))
