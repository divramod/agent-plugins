"""A fake hal2-cli-plans for the plan skill's tests: `questions check --json --store <file>` prints a fixed JSON.

Tests pin `$HAL2_CLI_PLANS` to it, so `plan.py check` does not depend on the machine's installed binary.
"""
import json
import os
import tempfile
from pathlib import Path

import qcheck


def write(folder: Path, problems: list[dict] | None = None, code: int = 0, out: str | None = None) -> str:
    """Write the stub into `folder`; it records its arguments in `args` beside it and prints the problems as the
    CLI does (or `out` verbatim); returns its path."""
    path = folder / "hal2-cli-plans"
    body = out if out is not None else json.dumps({"store": "x", "problems": problems or []})
    path.write_text(f"#!/bin/sh\necho \"$@\" >> '{folder}/args'\ncat <<'EOF'\n{body}\nEOF\nexit {code}\n")
    path.chmod(0o755)
    return str(path)


def pin_module() -> tempfile.TemporaryDirectory:
    """For `setUpModule`: pin the CLI to a stub without problems; keep the returned directory alive."""
    tmp = tempfile.TemporaryDirectory()
    os.environ[qcheck.ENV] = write(Path(tmp.name))
    return tmp
