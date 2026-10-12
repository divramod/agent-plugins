"""hal2's one records checker, `hal2-cli-records check --json`, called by the skills (hal2 plan 0214 step 6).

The skills call hal2, hal2 calls no skill: every rule of a record's form lives once, in hal2's Rust specs. Without
the binary the check is advisory: one line, `records unchecked: hal2-cli-records is not installed`, and no failure
(a machine without hal2 keeps working; hal2's landing gate is where the check is enforced). The binary is
`$HAL2_CLI_RECORDS` (a hal2 worktree ahead of the installed binary, and the tests, set it), else
`hal2-cli-records` on PATH.

A copy of the plan skill's scripts/checker.py (each skill is installed on its own): change both together.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

ENV = "HAL2_CLI_RECORDS"
NAME = "hal2-cli-records"
NOT_INSTALLED = f"records unchecked: {NAME} is not installed"


class CheckerError(Exception):
    """The checker could not check (exit 2: usage or an unreadable repository; 3: older than the repository asks)."""

    def __init__(self, message: str, code: int):
        super().__init__(message)
        self.code = code


def binary() -> str | None:
    """The checker to run: `$HAL2_CLI_RECORDS` when it names a file, else the one on PATH; None when neither."""
    named = os.environ.get(ENV, "").strip()
    if named:
        return named if Path(named).expanduser().is_file() else None
    return shutil.which(NAME)


def check(*, repo: Path | None = None, folder: Path | None = None) -> dict | None:
    """The checker's JSON (`records`, `valid`, `legacy`, `shaped`, `problems`) for a repository or a folder laid
    out like one; None when the binary is missing."""
    cli = binary()
    if cli is None:
        return None
    args = [str(Path(cli).expanduser()), "check", "--json"]
    args += ["--folder", str(folder)] if folder else ["--repo", str(repo or Path.cwd())]
    out = subprocess.run(args, capture_output=True, text=True)
    if out.returncode not in (0, 1):
        raise CheckerError(f"{NAME}: {(out.stderr or out.stdout).strip()}", out.returncode)
    try:
        return json.loads(out.stdout)
    except json.JSONDecodeError as error:
        raise CheckerError(f"{NAME} printed no JSON ({error}): {(out.stderr or out.stdout).strip()}", 2) from error


def line(problem: dict, prefix: str = "") -> str:
    """One problem as the skills print it: `<path>[:<line>]: <message> (<rule>)`."""
    at = f":{problem['line']}" if problem.get("line") else ""
    return f"{prefix}{problem['path']}{at}: {problem['message']} ({problem['rule']})"
