"""Finds hal2's tree (the skill is in it, or linked from it) and the pieces of it the skill runs."""

from __future__ import annotations

import os
import sys
from pathlib import Path

MARKER = Path("code/python/scripts/hal9k/sites.py")
HAL9K = Path("code/python/scripts/hal9k")
SITE_CHECK = Path("code/python/scripts/hal9k-site-check/main.py")
SITES_DIR = Path("utils/deploy/hal9k/sites")


class NoHal2(Exception):
    pass


def find_root(start: Path | None = None) -> Path:
    """`HAL2_ROOT`, else the tree above this file (a link is resolved); NoHal2 says what to do when there is none."""
    env = os.environ.get("HAL2_ROOT")
    candidates = [Path(env)] if env else list((start or Path(__file__).resolve()).parents)
    for folder in candidates:
        if (folder / MARKER).is_file():
            return folder
    raise NoHal2("hal2's tree was not found (set HAL2_ROOT to a hal2 checkout, or run the skill from hal2's field): "
                 "outside hal2 only inspect, declare --stdout, ci-step, status and `learn --brief` work")


def load_modules(root: Path):
    """hal2's own `sites`, `site_container` and `shell`, the code the real deploy runs."""
    folder = str(root / HAL9K)
    if folder not in sys.path:
        sys.path.insert(0, folder)
    import shell
    import site_container
    import sites
    return sites, site_container, shell
