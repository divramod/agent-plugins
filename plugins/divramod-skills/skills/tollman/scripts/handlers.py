"""The tollman's duty handlers by item, each module imported when its handler is asked for (hal2 plan 0480 D3).

A minute pass runs no handler, so it loads none; a round asks for the due duties' only. `HANDLERS` is a dict whose
values are `module.function` until first asked for.

A module that fails to import (L135: `module 'mtm_scan' has no attribute 'QUEUE'` at trains.py's import, the yard's
files half updated while a round ran) is tried once more (`load`): after PAUSE, the module the error names reloaded
from its file; a second failure raises.
"""

import importlib
import sys
import time
import types

PAUSE = 2.0  # seconds before the one retry: the yard's update goes on meanwhile


def stale(e: Exception) -> str | None:
    """The loaded module the import error names (its file may be newer), or None."""
    if isinstance(e, AttributeError) and isinstance(getattr(e, "obj", None), types.ModuleType):
        return e.obj.__name__
    return e.name if isinstance(e, ImportError) and e.name in sys.modules else None


def load(module: str):
    """`module` imported; an AttributeError or ImportError retried once after PAUSE, the module it names reloaded."""
    try:
        return importlib.import_module(module)
    except (AttributeError, ImportError) as e:
        print(f"tollman: importing {module} failed ({e}): once more in {PAUSE:g} s", file=sys.stderr, flush=True)
        time.sleep(PAUSE)
        importlib.invalidate_caches()
        if (name := stale(e)) and name in sys.modules:
            importlib.reload(sys.modules[name])
        return importlib.import_module(module)


class Handlers(dict):
    """`dict` keys are the item names; the value is `module.function` until `[]` or `get` imports it."""

    def __getitem__(self, item):
        value = super().__getitem__(item)
        if isinstance(value, str):
            module, name = value.split(".")
            value = getattr(load(module), name)
            self[item] = value
        return value

    def get(self, item, default=None):
        return self[item] if item in self else default


# "duty:<name>" → (item, ctx) → actions
HANDLERS: dict = Handlers({
    "duty:mtm": "boss.handler", "duty:trains": "trains.handler", "duty:checks": "checks.handler",
    "duty:learn": "learn.handler", "duty:prune": "prune.handler",  # prune: plan 0360 step 7 (D30)
    "duty:mainred": "mainred.handler",  # a red main: plan 0360 step 8 (D9, D29, D30)
    "duty:watch": "minute.handler"})  # the 1-minute watch of the land run: plan 0383 step 4 (D4)
