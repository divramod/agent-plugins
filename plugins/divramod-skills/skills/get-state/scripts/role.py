"""The session's role from its checkout (hal2 plan 0366, D2, D11). Pure: only paths and three environment variables.

    farmer-<repo>   farmer        tollman-<repo>  tollman
    00-29           foreman       30-99           servant
    the main checkout             steward; a place's main checkout (PLACES) that place's role:
                                  mayor ~/a/village, lord ~/a/city, pope ~/a/planet

Each place is overridden by its environment variable (`HAL_VILLAGE`, `HAL_CITY`, `HAL_PLANET`). Anything else is
`unknown` (the page then shows today's table). `--role` overrides the detected role.
"""

import os
from pathlib import Path

ROLES = ("farmer", "foreman", "servant", "steward", "tollman", "mayor", "lord", "pope")
UNKNOWN = "unknown"
PLACES = {"mayor": ("HAL_VILLAGE", "~/a/village"), "lord": ("HAL_CITY", "~/a/city"), "pope": ("HAL_PLANET", "~/a/planet")}


def place(role: str) -> str:
    """The main checkout of an upper role's place (`mayor`, `lord`, `pope`): its environment variable, else its
    default under `~/a`, as a real path."""
    env, default = PLACES[role]
    return os.path.realpath(os.environ.get(env) or os.path.expanduser(default))


def village() -> str:
    """The village's main checkout (the town hall)."""
    return place("mayor")


def field_role(name: str) -> str | None:
    """`foreman` for a field 00-29, `servant` for 30-99, None for any other name (`1`, `100`, `feature`)."""
    if len(name) != 2 or not name.isdigit():
        return None
    return "foreman" if int(name) < 30 else "servant"


def detect(top: str | None, main: str | None) -> str:
    """The role of the checkout `top` of the repository whose main checkout is `main`."""
    if not top:
        return UNKNOWN
    here = os.path.realpath(top)
    if main and here == os.path.realpath(main):
        return next((r for r in PLACES if here == place(r)), "steward")
    name = Path(here).name
    for prefix in ("farmer", "tollman"):
        if name.startswith(prefix + "-") and len(name) > len(prefix) + 1:
            return prefix
    return field_role(name) or UNKNOWN


def resolve(override: str | None, top: str | None, main: str | None) -> str:
    """`--role` wins; else the role detected from the checkout."""
    return override or detect(top, main)
