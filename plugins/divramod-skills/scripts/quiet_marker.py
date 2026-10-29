#!/usr/bin/env python3
"""The quiet marker of hal2 (plan 0442 D11): `<state root>/quiet.json`, written by hal2-machine (`hal2-cli-machine
quiet now`, the Machine view's Quiet now) in hal2-core's shape (`code/rust/libs/hal2-core/src/quiet.rs`, schema 1):
`{"schema": 1, "active": <bool>, "since", "by", "holds": {...}}`. While `active` every starter refuses, and the
skills' ticks (farmer, tollman, sanity-watch) skip their round: they would start, resume or message the sessions
Quiet now stopped. A missing, unreadable or foreign file is no quiet, as hal2-core reads it.

  from quiet_marker import refusal
  why = refusal()   # None, or the words why the round is skipped

The state root as hal2-core's paths: `$HAL2_STATE_DIR`, else `$XDG_STATE_HOME/hal2`, else the XDG state folder
(`.local`, `state`, `hal2`) below `$HAL2_HOME` or `$HOME`. A published plugin cannot import the repository's shared
helper (code/python/scripts/shared/hal_roots.py), so the folder is built from its parts here.
"""
import json
import os
from pathlib import Path

SCHEMA = 1
FILE = "quiet.json"
DEFAULT_STATE = (".local", "state", "hal2")  # below the home, as hal2_core::paths


def state_root(env=None) -> Path:
    env = os.environ if env is None else env
    if env.get("HAL2_STATE_DIR"):
        return Path(env["HAL2_STATE_DIR"])
    if env.get("XDG_STATE_HOME"):
        return Path(env["XDG_STATE_HOME"]) / "hal2"
    return Path(env.get("HAL2_HOME") or env.get("HOME") or Path.home(), *DEFAULT_STATE)


def marker(env=None) -> Path:
    return state_root(env) / FILE


def active(path: Path) -> dict | None:
    """The marker at `path` when Quiet now is on; None otherwise (also missing, broken, another schema)."""
    try:
        quiet = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    ok = isinstance(quiet, dict) and quiet.get("schema") == SCHEMA and quiet.get("active") is True
    return quiet if ok else None


def refusal(env=None) -> str | None:
    """Why a tick is skipped now: Quiet now is on (since when, by whom); None: it runs."""
    path = marker(env)
    quiet = active(path)
    if quiet is None:
        return None
    since = f" since {quiet['since']}" if quiet.get("since") else ""
    by = f" by {quiet['by']}" if quiet.get("by") else ""
    return f"the machine is quiet{since}{by} ({path}): no round until Back to work (hal2-cli-machine quiet back)"
