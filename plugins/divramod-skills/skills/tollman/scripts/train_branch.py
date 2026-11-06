"""A train's own landing branch (hal2 plan 0383 step 1, D2; learning L34; plan 0398 D1, D4; plan 0607 step 6): every
train lands on its own `land/train-<n>-<a>`, so each train has its own branch, pull request and runs and none adopts
or cancels another's. `<n>` is the train's number (`train_state.next_number`, on its `formed` line) and `<a>` the start
(`starts + 1`): `engine.restart` marks the train with `--train <n> --attempt <a>` (`mark`), `hal2-cli-git worktree
merge-to-main` then lands on the branch hal2-git names for that mark, and the tollman never builds the name: it asks
`hal2-cli-git worktree land-ref` (land_name.py, plan 0607 D6). `restart` writes what the CLI named into the `started`
line (`land_ref`), and `watch.find` looks for the run on the branch the CLI calls `current` (`land`), else on the
`started` line's.

A train formed before plan 0398 has no number and no mark: hal2-git refuses its landing (plan 0607 D4, D10: no
fallback name), land_name.refuses stops it before the pretest.

`ours` names every branch of the train itself (plan 0560 D4, L200): each start lands on a new `land/train-<n>-<a>`,
so an earlier attempt's run is the train's own, never "the run before" (next_train.others).
"""

import land_name

LAND = "land/"


def numbered(train: dict) -> bool:
    """The train has a number (formed since plan 0398): the mark names its branch."""
    return bool(train.get("number"))


def mark(train: dict) -> list[str]:
    """`--train <n> --attempt <a>` of the next start (a = starts + 1), none for a train without a number."""
    return ["--train", str(train["number"]), "--attempt", str(train["starts"] + 1)] if numbered(train) else []


def land(train: dict, main: str | None = None, run=None) -> str | None:
    """The branch the standing train's current start has its run on: hal2-git's `current` for the carrier (asked from
    `main`), else the `land/<land_ref>` its `started` line recorded; None when neither names one (never a built name)."""
    if main and (held := land_name.current(main, train.get("carrier"), run)):
        return held
    ref = train.get("land_ref")
    return f"{LAND}{ref}" if ref else None


def ours(train: dict, branch: str) -> bool:
    """`branch` is one of the train's own land branches: any start's `land/train-<n>-*` of a numbered train, else the
    one its `started` line recorded (plan 0560 D4)."""
    if numbered(train):
        return branch.startswith(f"{LAND}train-{train['number']}-")
    return bool(train.get("land_ref")) and branch == LAND + train["land_ref"]
