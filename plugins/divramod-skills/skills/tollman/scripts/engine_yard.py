"""The yard's car in the train engine (hal2 plan 0294 step 8, D4, D15; split out of engine.py by plan 0360 step 4):
`engine.form` loads the yard's uncommitted work as the train's first car, `engine.landed` settles the yard after a
green landing (yard.py does both)."""

import datetime as dt
import subprocess
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import train_state
import yard
from carrier import git


def load_yard(top: str, main: str, default: str, name: str, cars: list[dict], now=None) -> tuple[int, str]:
    """The yard's uncommitted work as the train's first car (yard.py; D4, D15): what it can place is one commit on
    the field's head, its files a `yard` line of the train state. It never fails a train: the number of files that
    ride and, when the yard had work that does not, why."""
    try:
        past = train_state.yard_past(train_state.lines(main))
        seen = yard.look(main, git(top, "rev-parse", "HEAD")[1], default, cars, past)
        commit, files, why = yard.carry(main, top, seen["placed"], cars)
    except (OSError, subprocess.SubprocessError) as e:
        return 0, f"the yard does not ride: {e}"
    if files:  # without a commit: files the barn holds as they are, for yard.settle after the landing
        train_state.append(main, "yard", Path(top).name, now, train=name, commit=commit, files=files)
    return len(files) * bool(commit), (f"the yard does not ride: {why}" if why else
                                       f"the yard rides with {len(files)} files" if commit else "")


def settle_yard(main: str, train: dict, default: str) -> dict | None:
    """After a green landing: the files the yard's car carried leave the yard where they are still the same, and
    the yard is fast-forwarded (yard.settle). None: the yard did not ride."""
    if not train.get("yard"):
        return None
    try:
        return yard.settle(main, train["yard"], default)
    except (OSError, subprocess.SubprocessError) as e:
        return {"dropped": [], "kept": [], "pulled": False, "why": str(e)}
