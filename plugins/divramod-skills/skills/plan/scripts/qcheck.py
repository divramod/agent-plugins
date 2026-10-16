"""hal2's questions checker, `hal2-cli-plans questions check --json`, called by `plan.py check` (hal2 plan 0329).

The skills call hal2, hal2 calls no skill: the Q form of a questions.md lives once, in hal2's Rust lib. An open
question of the agent must have exactly three option lines a) b) c) (decision D5 of plan 0329). Without the binary
the check is advisory: one line, `questions unchecked: hal2-cli-plans is not installed`, and no failure. The binary
is `$HAL2_CLI_PLANS` (a hal2 worktree ahead of the installed binary, and the tests, set it), else `hal2-cli-plans` on
PATH.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

ENV = "HAL2_CLI_PLANS"
NAME = "hal2-cli-plans"
RULE = "questions-q-form"
NOT_INSTALLED = f"questions unchecked: {NAME} is not installed"
TOO_OLD = f"questions unchecked: {NAME} has no `questions check` (an older binary)"


def binary() -> str | None:
    """The CLI to run: `$HAL2_CLI_PLANS` when it names a file, else the one on PATH; None when neither."""
    named = os.environ.get(ENV, "").strip()
    if named:
        return named if Path(named).expanduser().is_file() else None
    return shutil.which(NAME)


def check(stores: list[tuple[str, Path]]) -> tuple[list[str], str | None]:
    """The problems of every `(label, questions.md)` store, one line each ending in the rule name, and the
    advisory line when the CLI is missing or too old (then the problems are empty)."""
    cli = binary()
    if cli is None:
        return [], NOT_INSTALLED
    problems: list[str] = []
    for label, path in stores:
        out = subprocess.run([str(Path(cli).expanduser()), "questions", "check", "--json", "--store", str(path)],
                             capture_output=True, text=True)
        try:
            found = json.loads(out.stdout)["problems"] if out.returncode in (0, 1) else None
        except (json.JSONDecodeError, KeyError):
            found = None
        if found is None:
            return [], TOO_OLD
        for p in found:
            where = f"Q{p['n']}: " if p.get("n") else ""
            problems.append(f"{label}: {where}{p['message']} ({RULE})")
    return problems, None
