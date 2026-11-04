"""A plan's hitch kind and rule problems, from hal2-plans (hal2 plan 0592 D8/D10, plan 0593): `hal2-cli-plans show
<slug> --repo <root> --json` carries `progress.hitch` (`{kind: complete|milestone|partial|none, n, of, open_before,
after_landing_open}`) and `problems`. This module only asks and relays; it never computes a kind itself (one source).
The binary is `$HAL2_CLI_PLANS` (a hal2 worktree ahead of the installed one, and the tests), else `hal2-cli-plans`
on PATH. Without it, or with one that does not know `progress.hitch`, the answer is (None, [], the one line that
says so), the way `check` goes on without hal2's records checker."""
import json
import os
import shutil
import subprocess
from pathlib import Path

ENV = "HAL2_CLI_PLANS"
NAME = "hal2-cli-plans"
TIMEOUT = 30


def binary() -> str | None:
    named = os.environ.get(ENV, "").strip()
    if named:
        return named if Path(named).expanduser().is_file() else None
    return shutil.which(NAME)


def label(hitch: dict | None) -> str:
    """`complete`, `milestone 1/2`, `partial` or `none`, as the tables show it."""
    if not hitch:
        return "-"
    if hitch.get("kind") == "milestone" and hitch.get("n"):
        return f"milestone {hitch['n']}/{hitch.get('of')}"
    return str(hitch.get("kind", "-"))


def of(root: Path, slug: str) -> tuple[dict | None, list[str], str]:
    """(hitch, rule problems, note): the note says why there is no hitch, "" otherwise."""
    cli = binary()
    if cli is None:
        return None, [], f"the hitch kind needs {NAME}: it is not installed"
    try:
        out = subprocess.run([str(Path(cli).expanduser()), "show", slug, "--repo", str(root), "--json"],
                             capture_output=True, text=True, encoding="utf-8", timeout=TIMEOUT)
        data = json.loads(out.stdout) if out.returncode == 0 else None
    except (OSError, UnicodeDecodeError, subprocess.TimeoutExpired, json.JSONDecodeError):
        data = None
    hitch = ((data or {}).get("progress") or {}).get("hitch")
    if not isinstance(hitch, dict):
        return None, [], f"the hitch kind needs a newer {NAME}: the installed one does not give `progress.hitch`"
    problems = [str(p) for p in (data.get("problems") or [])]
    return hitch, problems, ""
