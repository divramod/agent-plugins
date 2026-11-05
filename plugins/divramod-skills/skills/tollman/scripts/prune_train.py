#!/usr/bin/env python3
"""The prune duty's trims under a building train (hal2 plan 0623 D2, L147; tollman learning of 2026-10-31).

While a train builds, the prune duty defers every trim, muck out and response (prune.py `building`). Prune run
20261030T185542 freed 0 B at 28 and then 16 GB free for that reason. Now, with under `train_trim_gb` (30 GB, /prune's
own number in its plan) free, the phase-2 trims (a build folder of a session-less field, never a muck out, a removal or
a response) go on for the fields the building train does not carry: its cars' fields and its carrier stay deferred.
A train whose cars are not known (a hold with no standing train of the tollman's) defers every field.

  outside_trims(main, data) -> the phase-2 trim actions of /prune's plan `data` for the fields outside the train
"""

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import train_state

DEFAULT_GB = 30


def train_fields(main: str) -> set[str] | None:
    """The fields the standing train carries (its cars and its carrier), None when no train of the tollman's stands."""
    try:
        train = train_state.standing(train_state.lines(main))
    except OSError:
        return None
    if not train:
        return None
    return {c["field"] for c in train.get("cars", []) if isinstance(c, dict) and c.get("field")} | {str(train["carrier"])}


def outside_trims(main: str, data: dict) -> list[dict]:
    """/prune's phase-2 trims (planned or held by the hold) for the fields the building train does not carry, only while
    the free disk is under /prune's `train_trim_gb`; [] when the train's fields are unknown."""
    plan, free = data["plan"], data["facts"]["disk"]["free_gb"]
    if free >= plan.get("train_trim_gb", DEFAULT_GB) or (carried := train_fields(main)) is None:
        return []
    job = plan["jobs"].get("phase-2", {})
    return [a for a in job.get("actions", []) + job.get("held", []) if a["action"] == "trim" and a["field"] not in carried]
