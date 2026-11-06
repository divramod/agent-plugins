"""A resolved car is proved on the carrier's head (hal2 plan 0695 row 22, learning L258, D25): a car whose resolve
(or whose later merge) is on the carrier already carries the carrier's lines, not the ones of its old hitched head, so
proof.py's red on the hitched head can name lines the resolve renamed (train 56: car 19, two fix orders that needed no
commit). `live` returns the train with such a car's `proof_red` read again on the carrier's head: green or unknown
drops it (the pretest and the gate run the checks), red keeps the lines the carrier's head shows. The hitched head
stays what it is (hitch-is-forever); only the proof moves. proof_orders.py calls it before every red line and order.
"""

from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import proof
import train_wt
from carrier import git


def resolved(rows: list[dict], name: str) -> set[str]:
    """The fields whose resolve train `name` has taken (a `resolved` line)."""
    return {e.get("field") for e in rows if e.get("kind") == "resolved" and e.get("train") == name}


def live(top: str, main: str, train: dict, rows: list[dict], prove=None) -> dict:
    """`train` with the `proof_red` of each resolved red car proved again on the carrier head (see the module doc)."""
    prove = prove or proof.verdict
    mine = resolved(rows, train["train"])
    reds = [c for c in train.get("cars") or [] if c.get("proof_red") and c["field"] in mine]
    carrier = train_wt.folder(train, top)
    code, head = git(carrier, "rev-parse", "HEAD") if reds and Path(carrier).is_dir() else (1, "")
    if code or not reds:
        return train
    cars = []
    for c in train["cars"]:
        if c in reds:
            v = prove(main, carrier, head, train["base"])
            c = {k: val for k, val in c.items() if k != "proof_red"}
            c |= {"proof_red": v["lines"]} if v["state"] == "red" else {}
        cars.append(c)
    return {**train, "cars": cars}
