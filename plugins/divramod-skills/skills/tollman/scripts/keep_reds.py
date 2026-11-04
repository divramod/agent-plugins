"""The train-reds `act` keeps open (hal2 plan 0608 D3, learning L240, rule L230): a `train-red` or `train-failed` wake
item that has no `order` line in train.jsonl for its train and run lost its fix order if `act` closed it (train 51's
reds were closed unseen), so the farmer frame's `close_older` (roles.Wiring.keep) leaves it open. The train is the
item's `evidence.train.train`; its run ids are the key's (`train-red:<run id>[:...]`), the verdict's
(`evidence.evidence.id`) and the result's (`evidence.result.run`, a URL), each as a bare id; an order line's `run` is
a URL or a bare id (plan 0608 D5). An item that names no run is kept until its train has any order line. train.jsonl
is read once per `act`, and only when an item is a candidate."""

import re

import train_state

KINDS = ("train-red", "train-failed")
RUN = re.compile(r"(?:runs/)?(\d{6,})(?:[/?#].*)?$")  # a GitHub run id: a train's number is short


def run_id(value) -> str | None:
    """The bare run id of a URL or id (six digits or more), else None."""
    m = RUN.search(str(value or ""))
    return m.group(1) if m else None


def runs_of(item: dict) -> set[str]:
    """The run ids an item names (see the module doc)."""
    ev = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
    inner = ev.get("evidence") if isinstance(ev.get("evidence"), dict) else {}
    result = ev.get("result") if isinstance(ev.get("result"), dict) else {}
    parts = (item.get("key") or "").split(":")
    found = {run_id(v) for v in (parts[1] if len(parts) > 1 and parts[0] == "train-red" else None,
                                 inner.get("id"), result.get("run"))}
    return {r for r in found if r}


def train_of(item: dict) -> object:
    ev = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
    train = ev.get("train")
    return train.get("train") if isinstance(train, dict) else None


def unordered(main: str, items: list[dict]) -> list[dict]:
    """Of `items`, the train-reds and train-faileds no `order` line of train.jsonl answers."""
    cand = [i for i in items if i.get("kind") in KINDS]
    if not cand:
        return []
    orders = [e for e in train_state.lines(main) if e["kind"] == "order"]
    kept = []
    for item in cand:
        train, runs = train_of(item), runs_of(item)
        mine = [e for e in orders if train is not None and e.get("train") == train]
        if train is None:
            mine = orders if runs else []  # no train named: any order of the run answers it
        if runs:
            mine = [e for e in mine if run_id(e.get("run")) in runs]
        if not mine:
            kept.append(item)
    return kept
