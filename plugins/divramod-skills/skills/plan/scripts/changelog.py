"""`plan.py changelog`: scaffold a plan's changelog fragment, `plans/<NNNN>-<slug>/changelog.md` (hal2 plan 0339).

hal2's `hal2-cli-changelog new <plan> --json` writes it (`$HAL2_CLI_CHANGELOG`, else the binary on PATH); a machine
without it gets the same template from here (the text of `hal2-changelog`'s `fragment::template`). Never overwrites.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

ENV = "HAL2_CLI_CHANGELOG"
NAME = "hal2-cli-changelog"
FILE = "changelog.md"

NEXT = ("next: replace the empty `## Added` with the user-facing changes of this plan (one `- ` line each, "
        "`` `<unit>`: `` first), or write `No user-facing change.` and no category; then `hal2-cli-changelog check`")


class ChangelogError(Exception):
    """The fragment cannot be written."""


def binary() -> str | None:
    """`$HAL2_CLI_CHANGELOG` when it names a file, else the CLI on PATH; None when neither."""
    named = os.environ.get(ENV, "").strip()
    if named:
        return named if Path(named).expanduser().is_file() else None
    return shutil.which(NAME)


def template(number: int) -> str:
    """The lib's fragment template for plan `number`."""
    return (f"---\ntype: Changelog\nschema: 1\nplan: {number}\ntitle: Changelog of plan {number:04d}\n"
            f"description: What plan {number:04d} changes for the people using hal2.\nstatus: active\n"
            f"---\n\n# Changelog of plan {number:04d}\n\n## Added\n\n")


def write(root: Path, plan_dir: Path, research: bool) -> tuple[Path, str]:
    """Scaffold the fragment of the plan folder `plan_dir`; returns (its path, the guidance line)."""
    if research:
        raise ChangelogError("a research plan writes no changelog fragment")
    if not (plan_dir / "plan.md").is_file() or not plan_dir.name[:4].isdigit():
        raise ChangelogError("a flat plan file has no folder for its changelog.md: move it into plans/<NNNN>-<slug>/")
    target = plan_dir / FILE
    if target.exists():
        return target, "exists: edit it, then `hal2-cli-changelog check`"
    cli = binary()
    if cli:
        out = subprocess.run([str(Path(cli).expanduser()), "new", plan_dir.name, "--json"], cwd=root,
                             capture_output=True, text=True)
        if out.returncode == 0 and target.exists():
            return target, NEXT
        try:
            message = json.loads(out.stdout)["error"]["message"]
        except (ValueError, KeyError, TypeError):
            message = (out.stderr or out.stdout).strip()
        raise ChangelogError(f"{NAME} new: {message}")
    target.write_text(template(int(plan_dir.name[:4])))
    return target, f"{NEXT} ({NAME} is not installed: the template was written by the skill)"
