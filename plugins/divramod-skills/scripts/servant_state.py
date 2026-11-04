"""The one reader of a servant's state for the skills (hal2 plan 0594, step 6; decisions D5, D6): it runs
`hal2-cli-plans servant show [--repo <checkout>] --json` and returns the `servant` object, so no skill splits the
`plans/LEAD` line itself (the CLI is the one parser, `hal2_plans::servant::of`).

  from servant_state import of, foreman_of, steps_line
  s = of(root)            # None, or {"schema": 1, "foreman": "09", "plan": "0594-...", "finished": False,
                          #           "steps": [{"n": "3", "title": "...", "status": "done"}, ...]}
  foreman_of(root)        # "09" or None
  steps_line(s)           # "steps 3 (done), 4 (open)"

None means "not a servant, or the state cannot be read": the CLI missing, failing or answering garbage or another
`schema` (D6: no fallback parse of the file, that would be the copy again). A caller that must tell a servant's field
from a broken marker asks the pointers' `exists(root, "LEAD")` first (existence only, no parse). `HAL2_CLI_PLANS`
names another binary (a test's fake, a debug build), as get-state's `plan_cli` does. Tests stub the CLI with
`servant_testkit.install`.
"""
import json
import os
import subprocess
from pathlib import Path

SCHEMA = 1
TIMEOUT = 15


def cli() -> str:
    return os.environ.get("HAL2_CLI_PLANS") or "hal2-cli-plans"


def of(root: str | Path) -> dict | None:
    """The `servant` object of the checkout `root`, None when it is no servant's or cannot be read."""
    try:
        done = subprocess.run([cli(), "servant", "show", "--repo", str(root), "--json"], capture_output=True,
                              text=True, timeout=TIMEOUT, check=False)
        found = json.loads(done.stdout) if done.returncode == 0 and done.stdout.strip() else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    ok = isinstance(found, dict) and found.get("schema") == SCHEMA and isinstance(found.get("steps"), list)
    return found if ok and found.get("foreman") and found.get("plan") else None


def foreman_of(root: str | Path) -> str | None:
    """The foreman's field (`09`) of the servant in `root`, None otherwise."""
    found = of(root)
    return str(found["foreman"]) if found else None


def step_names(servant: dict) -> list[str]:
    return [str(s.get("n", "")) for s in servant.get("steps", [])]


def steps_line(servant: dict) -> str:
    """`step 3 (done)` or `steps 3 (done), 4 (open)`: every step with its status (an empty status is `open`)."""
    steps = servant.get("steps", [])
    each = ", ".join(f"{s.get('n', '')} ({s.get('status') or 'open'})" for s in steps)
    return f"step{'s' if len(steps) != 1 else ''} {each}" if steps else "no steps"
