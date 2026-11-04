"""A dependent wagon rides after its dependency (hal2 plan 0595 step 12, D22, which replaced D17's wait: the user,
2026-11-04, "take all finished worktrees into the train"): `trains.draft` orders the cars by the farm's plan
dependencies and never leaves one out for them.

- the dependencies: one `hal2-cli-plans depends list --json --repo <main>` per draft that has a wagon (schema 1,
  plan 0595 step 8: every plan on an edge, its `depends_on` links with the dependency's field and `state`: open,
  pushed, hitched or main; a plan absent depends on nothing). The binary is `$HAL2_CLI_PLANS` when it names a file,
  else `hal2-cli-plans` on PATH, as the plan skill's qcheck. Missing, too old (no `depends`), failing or not
  parsing: no rule, every wagon rides as before, and one advisory line says why
- the order (`order`): queue order, except that a wagon whose dependency not in main is another wagon's field moves
  behind that wagon (the first wagon in queue order whose dependencies are placed goes next; a cycle, which
  `depends add` refuses, keeps queue order)
- no wait: a dependent whose dependency is not hitched rides all the same (D22); `lines` names each car that rides
  behind its dependency, the reason the dry run and the train page show
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import bounded
from trains_sort import current_plan

ENV, NAME = "HAL2_CLI_PLANS", "hal2-cli-plans"
SCHEMA = 1
LIMIT = 60  # seconds: the farm's read takes 0.4 s (step 8's Notes); bounded.run tries twice
MISSING = f"dependencies unchecked: {NAME} is not installed"
OLD = f"dependencies unchecked: {NAME} has no `depends list` (an older binary)"
BROKEN = f"dependencies unchecked: `{NAME} depends list` failed"
NONE = {"plans": [], "line": None}  # no wagon: nothing read


def binary() -> str | None:
    """The CLI to run: `$HAL2_CLI_PLANS` when it names a file, else the one on PATH; None when neither."""
    env = os.environ.get(ENV, "")
    return env if env and Path(env).expanduser().is_file() else shutil.which(NAME)


def read(main: str) -> dict:
    """The farm's dependencies: {plans: [node], line: str | None}; no plans and a line when they cannot be read."""
    cli = binary()
    if cli is None:
        return {"plans": [], "line": MISSING}
    try:
        p = bounded.run([str(Path(cli).expanduser()), "depends", "list", "--json", "--repo", main], cwd=main,
                        other=LIMIT)
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"plans": [], "line": f"{BROKEN}: {e}"[:200]}
    try:
        doc = json.loads(p.stdout) if p.returncode == 0 else None
    except json.JSONDecodeError:
        doc = None
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA or not isinstance(doc.get("plans"), list):
        old = p.returncode == 2 or "unrecognized subcommand" in (p.stderr or "")
        return {"plans": [], "line": OLD if old else f"{BROKEN} (exit {p.returncode})"}
    return {"plans": [n for n in doc["plans"] if isinstance(n, dict)], "line": None}


def number(plan: str | None) -> int | None:
    """`0595-plan-gaps-manual-work` -> 595; None for no plan number."""
    digits = (plan or "").split("-", 1)[0]
    return int(digits) if digits.isdigit() else None


def pending(deps: dict, field: str, plan: str | None = None) -> list[dict]:
    """The dependencies not in main of the wagon of `field` (its node by field, else by its CURRENT_PLAN `plan`)."""
    nodes = deps.get("plans") or []
    node = next((n for n in nodes if n.get("field") == field), None) \
        or next((n for n in nodes if number(plan) is not None and n.get("plan") == number(plan)), None)
    return [link for link in (node or {}).get("depends_on") or [] if link.get("state") != "main"
            and link.get("field") != field]


def plan_of(ticket: dict) -> str:
    """The CURRENT_PLAN of the ticket's field ('' without a worktree)."""
    return current_plan(ticket["worktree"]) if ticket.get("worktree") else ""


def order(wagons: list[dict], deps: dict) -> list[dict]:
    """`wagons` (tickets in queue order) with each dependent behind the wagons its pending dependencies ride in."""
    fields = {t["slot"] for t in wagons}
    needs = {t["slot"]: {link["field"] for link in pending(deps, t["slot"], plan_of(t))} & fields for t in wagons}
    out, rest = [], list(wagons)
    while rest:
        placed = {t["slot"] for t in out}
        nxt = next((t for t in rest if needs[t["slot"]] <= placed), rest[0])  # a cycle: queue order
        out.append(nxt)
        rest.remove(nxt)
    return out


def lines(deps: dict, cars: list[dict]) -> list[str]:
    """The draft's `depends`: a line per car that rides behind a dependency in the same train (the dry run's and the
    train page's why), then the advisory line when the dependencies could not be read."""
    out, seen = [], set()
    for c in cars:
        ahead = [f"{link['field']} ({int(link.get('plan') or 0):04d}, {link.get('state')})"
                 for link in pending(deps, c["field"], c.get("plan")) if link.get("field") in seen]
        if ahead:
            out.append(f"{c['field']} rides after {', '.join(ahead)}: its plan depends on it")
        seen.add(c["field"])
    return out + ([deps["line"]] if deps.get("line") else [])
