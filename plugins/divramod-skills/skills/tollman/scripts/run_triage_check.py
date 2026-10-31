"""The independent recheck of a triage verdict (hal2 plan 0490 step 1, D11, D12): `recheck` recomputes kind and owner
from the verdict's evidence alone, never from the first verdict: the transient fault and the build-phase timeout
are read again from the evidence's lines, a spec must stand in them, a car owner must be a car of the train and a
repeat never a car's. `settle` keeps a verdict both agree on and turns any other into `unsure` (no field, what
disagrees named): the code never sends a guess (the record security-findings' recheck by recompute)."""

import run_triage_read as read
import transient

QUIET = ("needs-red", "runner", "flake")


def unsure(v: dict, missing: str | None) -> dict:
    """The verdict turned `unsure`: no field, what is missing named."""
    missing = missing or f"the owner of this {v.get('cause') or v['kind']} red"
    return {**v, "kind": "unsure", "placed": v["kind"], "owner": None, "live": False, "missing": missing}


def pipeline(e: dict) -> str | None:
    p = e.get("pipeline") or {}
    cars, movers = p.get("cars") or [], [m for m in p.get("movers") or [] if m in (p.get("cars") or [])]
    if len(cars) > 1 and len(movers) == 1:
        return movers[0]  # of several pipeline cars, the one that moved the red job's lane (L83, L87)
    return cars[0] if len(cars) == 1 else (p.get("configured") if not cars else None)


def owned(e: dict) -> str | None:
    """The failing file's owner as its evidence shows it: a car owner must be a car of the train."""
    o = e.get("owner") or {}
    field, by = o.get("field"), (o.get("from") or {}).get("by")
    if by == "car" and field not in (e.get("cars") or []):
        return "?"
    if by == "worktree" and field != ((o.get("from") or {}).get("worktree") or "").strip():
        return "?"
    return field


def recheck(e: dict) -> tuple[str, str | None]:
    """(kind, owner) from the evidence alone; `unsure` where the evidence does not carry the placement."""
    text = "\n".join(e.get("lines") or [])
    if e.get("needs_red"):
        return "needs-red", None
    if transient.TRANSIENT.search(text) or e.get("unserved"):
        return "runner", None
    if e.get("green_on") or (not read.TIMEOUT.search(text) and read.budget_only(e.get("lines") or [])):
        return "flake", None
    if e.get("spec"):
        if e["spec"] not in text:
            return "unsure", None
        why, owner = "file", owned(e)
    elif read.TIMEOUT.search(text) or (e.get("pipeline") or {}).get("cars"):
        why, owner = "pipeline", pipeline(e)
    elif e.get("culprit") and not e.get("repeat_of") and e["culprit"] in (e.get("cars") or []):
        why, owner = "car", e["culprit"]
    else:
        why, owner = "unplaced", None
    if why == "pipeline" and not owner:
        return "unsure", None
    if e.get("repeat_of"):
        return ("repeat", owner) if owner or why == "file" else ("unsure", None)
    return why, owner


def settle(v: dict) -> dict:
    """The verdict when the recheck agrees, else `unsure`; an `unsure` verdict stays one."""
    if v["kind"] == "unsure":
        return {**v, "recheck": "unsure"}
    kind, owner = recheck(v["evidence"])
    if (kind, owner) != (v["kind"], v.get("owner")):
        return {**unsure(v, f"recheck: {kind} {owner or '-'} against {v['kind']} {v.get('owner') or '-'}"),
                "recheck": "disagrees"}
    return {**v, "recheck": "agrees"}
