#!/usr/bin/env python3
"""The hal2 CLI a tollman call runs on a candidate (hal2 plan 0431 step 4, D4, D6): when the repository has the hook
`.hal/own-cli.sh`, the CLI is the candidate's own build if the candidate changes that CLI's crates (or the installed
one is older than the checkout), else the installed one; a repository without the hook keeps PATH's.

  resolve(field, app, barn, head, run)  the command to run: the hook's path, else `app` (PATH); None when the hook
                                        cannot answer (exit 1: the build does not build; a timeout; not startable),
                                        so the check that needs the CLI cannot run and is skipped, never a red car

Only calls that read the candidate come here (the train's proof). Queue operations and the landing call stay the
installed `hal2-cli-git`: the queue is main's state and the landing re-runs itself as the branch's build (D5, D6).
"""

import os
from pathlib import Path

HOOK = ".hal/own-cli.sh"
BUILD = 1800  # the hook may build a CLI; a light check's limit would skip every cold build


def hook_of(field: str) -> str | None:
    """The field's hook when it is an executable file."""
    hook = Path(field) / HOOK
    return str(hook) if hook.is_file() and os.access(hook, os.X_OK) else None


def printed(text: str, app: str) -> str | None:
    """The path on the hook's `<app>\\t<path>\\t<reason>` line for `app`: "" when it keeps the installed one, None
    when no line names the app."""
    for line in text.splitlines():
        cols = line.split("\t")
        if cols[0] == app:
            return cols[1].strip() if len(cols) > 1 else ""
    return None


def resolve(field: str, app: str, barn: str, head: str, run) -> str | None:
    """The command for `app` on the candidate `head` (the range `barn`..`head`); see the module text."""
    hook = hook_of(field)
    if hook is None:
        return app
    code, text = run(["env", f"HAL_GATE_BASE={barn}", f"HAL_GATE_HEAD={head}", hook, app], field)
    if code != 0:
        return None
    path = printed(text, app)
    if path is None:
        return None
    return path or app
