"""The session's role from its checkout (hal2 plan 0366, D2, D11). Pure: only paths and three environment variables.

    farmer-<repo>   farmer        tollman-<repo>  tollman
    a field 00-99   servant when it holds plans/LEAD (a foreman's marker), else foreman (hal2 plan 0383, D16)
    the main checkout             steward; a place's main checkout (PLACES) that place's role:
                                  mayor ~/a/village, lord ~/a/city, pope ~/a/planet

Each place is overridden by its environment variable (`HAL_VILLAGE`, `HAL_CITY`, `HAL_PLANET`). Anything else is
`unknown` (the page then shows today's table). `--role` overrides the detected role.

The one rule lives in hal2 (plan 0592's D12): `resolve` and `of_checkout` read `hal2-cli-agents role --path <dir>
--json` (schema 1; its `role` null, a train's field, is `unknown` here) and fall back to `detect` only when the CLI is
missing, older (no `role` command) or answers no schema 1 object. `HAL2_CLI_AGENTS` names another binary (a test's).
"""

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, next(str(_p / "scripts") for _p in Path(__file__).resolve().parents if (_p / ".claude-plugin").is_dir()))
from skillpath import pointers as _pointers  # noqa: E402  (the skills unit's scripts/, plan 0360 D20)

pointers = _pointers(__file__)  # LEAD in the git dir, else plans/ (hal2 plan 0409 step 12)

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


def field_role(name: str, path: str | None = None) -> str | None:
    """`servant` for a field 00-99 holding `plans/LEAD`, else `foreman`; None for any other name (`1`, `100`,
    `feature`). The role comes from the marker, never from the number: a foreman may work in any field (D16)."""
    if len(name) != 2 or not name.isdigit():
        return None
    return "servant" if path and pointers.exists(path, "LEAD") else "foreman"


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
    return field_role(name, here) or UNKNOWN


CLI_TIMEOUT = 15


def cli() -> str:
    return os.environ.get("HAL2_CLI_AGENTS") or "hal2-cli-agents"


def from_cli(path: str) -> dict | None:
    """`hal2-cli-agents role --path <path> --json` (schema 1: `path, checkout, repo, field, role, why, lead, plan`); None
    when the CLI is missing, older, fails or answers something else."""
    try:
        done = subprocess.run([cli(), "role", "--path", str(path), "--json"], capture_output=True, text=True,
                              timeout=CLI_TIMEOUT, check=False)
        found = json.loads(done.stdout) if done.returncode == 0 and done.stdout.strip() else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    if not isinstance(found, dict) or found.get("schema") != 1 or "role" not in found:
        return None
    return found


def of_checkout(top: str | None, main: str | None) -> str:
    """The role of the checkout `top`: hal2's one rule (`from_cli`), else `detect`."""
    if not top:
        return UNKNOWN
    found = from_cli(top)
    if found is None:
        return detect(top, main)
    return found["role"] if found["role"] in ROLES else UNKNOWN


def resolve(override: str | None, top: str | None, main: str | None) -> str:
    """`--role` wins; else the role of the checkout (`of_checkout`)."""
    return override or of_checkout(top, main)
