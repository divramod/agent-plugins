"""The tollman's duty handlers by item, each module imported when its handler is asked for (hal2 plan 0480 D3).

A minute pass runs no handler, so it loads none; a round asks for the due duties' only. `HANDLERS` is a dict whose
values are `module.function` until first asked for.
"""

import importlib


class Handlers(dict):
    """`dict` keys are the item names; the value is `module.function` until `[]` or `get` imports it."""

    def __getitem__(self, item):
        value = super().__getitem__(item)
        if isinstance(value, str):
            module, name = value.split(".")
            value = getattr(importlib.import_module(module), name)
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
