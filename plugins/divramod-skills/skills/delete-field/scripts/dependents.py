"""Open plan dependents of a field (hal2 plan 0595 step 13): the guard prune, delete-field and transplant share.

A field whose plan other plans wait for (`depends_on` in their plan.md, hal2-cli-plans `depends`) is not removed or
stopped while a dependent still waits: the dependent's Link in the graph has a `state` that is not `main`. The graph
is read live, once per view: `hal2-cli-plans depends list --all --json --repo <farm>` (`$HAL2_CLI_PLANS` names
another program, for tests); no copy of its logic here. A missing or older CLI, a failed call or an unreadable answer
gives no plans and one advisory line, never a crash and never a refusal. Stdlib only.
"""
import json
import os
import shutil
import subprocess

ADVISORY = "plan dependents not checked: {why}"


def program() -> str:
    return os.environ.get("HAL2_CLI_PLANS") or "hal2-cli-plans"


def graph(repo) -> tuple[list[dict] | None, str | None]:
    """(the graph's plans, None) or (None, the advisory line). One call."""
    prog = program()
    if not shutil.which(prog):
        return None, ADVISORY.format(why=f"{prog} is not installed")
    try:
        r = subprocess.run([prog, "depends", "list", "--all", "--json", "--repo", str(repo)], capture_output=True,
                           text=True, timeout=120)
        plans = json.loads(r.stdout)["plans"] if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
        plans = None
    if not isinstance(plans, list):
        return None, ADVISORY.format(why=f"{prog} has no usable `depends list` (older CLI?)")
    return [p for p in plans if isinstance(p, dict)], None


def waiting(plan: dict) -> list[str]:
    """The dependents of `plan` that still wait: one text each, naming the plan and its wait."""
    out = []
    for link in plan.get("dependents") or []:
        if isinstance(link, dict) and link.get("state") != "main":
            until = link.get("until") or "main"
            out.append(f"plan {link.get('plan')} waits for plan {plan.get('plan')} until {until} "
                       f"(now {link.get('state')})")
    return out


def by_field(plans: list[dict] | None) -> dict[str, list[str]]:
    """{field: what waits for the plans running in it}, only fields with a waiting dependent."""
    out: dict[str, list[str]] = {}
    for p in plans or []:
        if p.get("field") and (found := waiting(p)):
            out.setdefault(str(p["field"]), []).extend(found)
    return out


def reason(texts: list[str]) -> str | None:
    return "its plan has open dependents: " + "; ".join(texts) if texts else None


def refusal(repo, field: str) -> tuple[str | None, str | None]:
    """(why the field's plan has open dependents, else None; the advisory line, else None)."""
    plans, advice = graph(repo)
    return reason(by_field(plans).get(field, [])), advice
