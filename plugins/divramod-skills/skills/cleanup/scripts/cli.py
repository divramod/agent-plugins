"""The hal2 CLI behind the cleanup skill: `hal2-cli-git worktree cleanup`, used where the installed one knows it.

The skill is published and runs anywhere, so the Python of cleanup.py stays the fallback: a missing, older or
unstartable CLI means the Python runs (plan 0284, D6, D22, D32).
"""
import os
import shutil
import subprocess

PROGRAM = "hal2-cli-git"
# The old hand-parsed help's first line, and the group help's once hal2-cli-git runs on hal2_core::cli (plan 0318).
FIRST_LINES = ("usage: hal2-cli-git worktree cleanup", "hal2-cli-git worktree cleanup - ")
HELP_TIMEOUT = 10


def find():
    """The CLI that knows `worktree cleanup`, or None.

    HAL_CLEANUP_CLI names it (empty: none, the Python runs), else hal2-cli-git on PATH. It counts only when
    `<cli> worktree cleanup --help` exits 0 AND its first line starts with one of FIRST_LINES: older CLIs exit 0 on any `--help`
    and print their general usage.
    """
    cli = os.environ["HAL_CLEANUP_CLI"] if "HAL_CLEANUP_CLI" in os.environ else shutil.which(PROGRAM)
    if not cli:
        return None
    try:
        help_ = subprocess.run([cli, "worktree", "cleanup", "--help"], capture_output=True, text=True,
                               timeout=HELP_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return None
    lines = help_.stdout.splitlines()
    return cli if help_.returncode == 0 and lines and lines[0].startswith(FIRST_LINES) else None


def run(argv):
    """Hand argv to the CLI as it is; its output is printed as it is. Its exit code, or None if the Python runs."""
    cli = find()
    if not cli:
        return None
    try:
        return subprocess.run([cli, "worktree", "cleanup", *argv]).returncode  # inherits stdout and stderr
    except OSError:
        return None
