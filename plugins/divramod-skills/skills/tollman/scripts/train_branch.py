"""A train's own landing branch (hal2 plan 0383 step 1, D2; learning L34; plan 0398 D1, D4): every train lands on
its own `land/train-<n>-<a>` instead of the carrier's `land/<carrier>`, so each train has its own branch, pull
request and runs and none adopts or cancels another's. `<n>` is the train's number (`train_state.next_number`, on
its `formed` line) and `<a>` the start (`starts + 1`): `engine.restart` marks the train with `--train <n> --attempt
<a>` (`mark`), `hal2-cli-git worktree merge-to-main` then lands on `land/train-<n>-<a>` without a `--land-ref`
(the workflow runs only for `land/**`), `ref` is the name it writes into the `started` line (`land_ref`) and
`watch.find` looks for the run there (`land`).

A train formed before plan 0398 has no number: it keeps the plan-named branch (`name`, passed as `--land-ref`).
Its part per car in train order: its plan's number (`0383` of `0383-train-rules`), else its field (lowercase letters
and digits only); a part twice is named once. hal2-cli-git refuses a branch over 200 characters and one holding
`probe` (the workflow's replays): a train too long keeps the parts that fit and `plus<n>` for the rest, and a part
never holds `probe`.
"""

import re

TRAIN = "train-"
LAND = "land/"
MAX = 200 - len(LAND)  # hal2-cli-git's limit is the whole branch's
PLAN = re.compile(r"(\d+)-")


def part(car: dict) -> str:
    """A car's part of the name: its plan's number, else its field, lowercase letters and digits only."""
    plan = PLAN.match(str(car.get("plan") or ""))
    raw = plan.group(1) if plan else re.sub(r"[^a-z0-9]", "", str(car.get("field") or "").lower())
    return raw.replace("probe", "prb")


def name(cars: list[dict]) -> str:
    """`train-<part>-<part>-...` of the cars (see the module doc): the value of `--land-ref`."""
    parts = []
    for car in cars:
        if (p := part(car)) and p not in parts:
            parts.append(p)
    parts = parts or ["car"]
    for keep in range(len(parts), 0, -1):
        rest = len(parts) - keep
        text = TRAIN + "-".join(parts[:keep] + [f"plus{rest}"] * bool(rest))
        if len(text) <= MAX:
            return text
    return (TRAIN + parts[0])[:MAX]


def numbered(train: dict) -> bool:
    """The train has a number (formed since plan 0398): the mark names its branch."""
    return bool(train.get("number"))


def mark(train: dict) -> list[str]:
    """`--train <n> --attempt <a>` of the next start (a = starts + 1), none for a train without a number."""
    return ["--train", str(train["number"]), "--attempt", str(train["starts"] + 1)] if numbered(train) else []


def ref(train: dict) -> str:
    """The `started` line's `land_ref` of the next start: `train-<n>-<a>`, else the plan-named `name`."""
    return f"{TRAIN}{train['number']}-{train['starts'] + 1}" if numbered(train) else name(train["cars"])


def land(train: dict) -> str:
    """The branch the standing train's current start lands on: `land/<land_ref>` of its `started` line, else (a
    train started before plan 0383) the carrier's `land/<carrier>`."""
    ref = train.get("land_ref")
    return f"{LAND}{ref}" if ref else f"{LAND}{train.get('carrier')}"
