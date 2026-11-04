"""Plan dependencies for the farmer's readers (hal2 plan 0595 step 9): the columns "depends on" and "dependents" and the
reason "waits for <NNNN> (<state>)", all from `hal2-cli-plans depends list --all --json` (schema 1: the graph is
computed there, deterministically; nothing of it is copied here). Read-only, no model call.

- `read(repo)`: the CLI's `plans` as `{plan number: node}`, called once per view; None when the CLI is missing, older
  (no `depends`), fails or answers garbage (the readers then show empty columns, never an error).
- `cell(links)`: `0514 (38, pushed), 0571 (open)`: the plan, then its field and the state of the edge in brackets.
- `wait_of(node, next_step)`: `waits for 0514 (open)` for the first dependency not yet reached whose `steps` is empty
  (the whole plan waits) or names the plan's next step; "" when nothing blocks.
- `ADVISORY`: the one line a view prints when `read` gave None.

`HAL2_CLI_PLANS` names another binary (a test's stub or debug build). The get-state skill loads this module through
`farmer_link.load("depends_view")`.
"""

import json
import os
import subprocess

TIMEOUT = 15
ADVISORY = "plan dependencies unknown: hal2-cli-plans depends list did not answer (CLI missing or older)"


def cli() -> str:
    return os.environ.get("HAL2_CLI_PLANS") or "hal2-cli-plans"


def read(repo: str) -> dict[int, dict] | None:
    """The farm's plans on a dependency edge by number (`{plan, slug, field, depends_on, dependents}`); None when unknown."""
    try:
        done = subprocess.run([cli(), "depends", "list", "--all", "--json", "--repo", str(repo)], capture_output=True,
                              text=True, timeout=TIMEOUT, check=False)
        found = json.loads(done.stdout) if done.returncode == 0 and done.stdout.strip() else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    plans = found.get("plans") if isinstance(found, dict) else None
    if not isinstance(plans, list):
        return None
    return {n["plan"]: n for n in plans if isinstance(n, dict) and isinstance(n.get("plan"), int)}


def number_of(text: object) -> int | None:
    """The plan number of a row's `plan_number` (`"0543"`) or of a CURRENT_PLAN text (`0543-slug`); None for neither."""
    head = str(text or "").strip().removeprefix("plans/")[:4]
    return int(head) if head.isdigit() else None


def node_of(graph: dict[int, dict] | None, plan: object) -> dict:
    """The graph's node of a plan (a number or text), else an empty one: no dependency either way."""
    return (graph or {}).get(number_of(plan)) or {"depends_on": [], "dependents": []}


def cell(links: list[dict]) -> str:
    """`0514 (38, pushed), 0581 (open)`; a link with no known field shows its state alone."""
    out = []
    for link in links or []:
        inside = ", ".join(x for x in (link.get("field"), link.get("state")) if x)
        out.append(f"{int(link['plan']):04d}" + (f" ({inside})" if inside else ""))
    return ", ".join(out)


def names(refs: list[str], step: str) -> bool:
    """Whether the step refs as written (`36`, `22-27`, schema 2's `01.03`) name `step`."""
    for ref in refs:
        lo, _, hi = str(ref).partition("-")
        if ref == step or (hi and lo.isdigit() and hi.isdigit() and step.isdigit() and int(lo) <= int(step) <= int(hi)):
            return True
    return False


def blocking(node: dict, next_step: object) -> list[dict]:
    """The dependencies not yet reached that hold the plan's next step: all of the plan's when a link names no step."""
    nxt = str(next_step) if next_step not in (None, "") else None
    return [l for l in node.get("depends_on") or []
            if not l.get("reached") and (not l.get("steps") or nxt is None or names(l["steps"], nxt))]


def wait_of(node: dict, next_step: object) -> str:
    """`waits for 0514 (open)` (several: `waits for 0514 (open), 0571 (pushed)`), "" when the next step is free."""
    held = blocking(node, next_step)
    return "waits for " + ", ".join(f"{int(l['plan']):04d} ({l.get('state') or 'open'})" for l in held) if held else ""
