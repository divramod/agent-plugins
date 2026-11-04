"""The hal2 CLIs `/continue` asks, and git (plan 0593 step 8). Read-only: a missing CLI, an older one, a failure or
an answer that is no JSON object gives None, and the caller says what it could not check.

`HAL2_CLI_AGENTS`, `HAL2_CLI_PLANS`, `HAL2_CLI_GIT` name other binaries (a test's fakes, a debug build).
"""

import json
import os
import subprocess
from pathlib import Path

TIMEOUT = 60
BINARIES = {"agents": ("HAL2_CLI_AGENTS", "hal2-cli-agents"), "plans": ("HAL2_CLI_PLANS", "hal2-cli-plans"),
            "git": ("HAL2_CLI_GIT", "hal2-cli-git")}


def binary(name: str) -> str:
    env, default = BINARIES[name]
    return os.environ.get(env) or default


def run_json(name: str, args: list[str], cwd: str | Path | None = None) -> dict | None:
    """`hal2-cli-<name> <args>`'s JSON object; None without one."""
    try:
        done = subprocess.run([binary(name), *args], capture_output=True, text=True, timeout=TIMEOUT, check=False,
                              cwd=str(cwd) if cwd else None)
        found = json.loads(done.stdout) if done.returncode == 0 and done.stdout.strip() else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return found if isinstance(found, dict) else None


def git(root: str | Path, *args: str) -> str | None:
    """git's stdout in `root`, stripped; None when git fails."""
    try:
        done = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=TIMEOUT,
                              check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() if done.returncode == 0 else None
