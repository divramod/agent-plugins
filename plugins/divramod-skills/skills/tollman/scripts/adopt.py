"""A landing the train state does not know is adopted, never doubled (the user, 2026-11-04: "make these scripts
bullet proof now").

What happened: train 51 was landed by a direct `engine.py land`. That call wrote no `started` line and set no
`--train/--attempt` mark, so the next round saw no live landing, tried `restart`, failed on the queue (its ticket
was held by the running landing) and woke the session with "run `engine.py restart` to see why": a rerun that
could have pushed a second landing. And the watch, finding no `started` line, never followed the run.

Two guards:
- `restart` asks the queue before it starts anything (`live`): a carrier ticket with a live landing pid is
  adopted (`adopt`: a `started` line with that pid, the branch hal2-git pushes and the time the landing began,
  the earlier start's landing log moved aside), exit 0, so the watch follows its run and no second landing starts.
  That pid is hal2-git's `merge-to-main`, which `train_state.alive` counts as a live landing too.
- `engine.py land` on the command line runs only as `spawn`'s child (`SPAWNED` in its environment, `direct`):
  `restart` alone marks the train and writes its `started` line, so a hand-typed `land` is refused with that word.
"""
import datetime as dt
import json
import os
import subprocess

import land_name
import train_state

SPAWNED = "HAL2_TOLLMAN_SPAWNED"
REFUSED = ("tollman: refused: `engine.py land` starts only as `engine.py restart`'s child (it marks the train with "
           "its number and attempt and writes the `started` line the watch follows); run `engine.py restart --repo "
           "<field>` instead, which adopts a landing that already runs")


def direct(env: dict | None = None) -> bool:
    """`engine.py land` was typed by hand or by another tool, not spawned by `restart`."""
    return not (env if env is not None else os.environ).get(SPAWNED)


def entry_of(queue: dict, field: str) -> dict | None:
    """The queue entry of the carrier `field` (`hal2-cli-git worktree queue --json`'s `queue`)."""
    return next((e for e in queue.get("queue") or [] if e.get("slot") == field), None)


def live(top: str, field: str, run=subprocess.run) -> dict | None:
    """The carrier's queue entry while a landing of it runs: a landing id and a live pid; None when the queue
    cannot be read (the start goes on as before and the queue refuses a second one)."""
    try:
        out = run(["hal2-cli-git", "worktree", "queue", "--json"], cwd=top, capture_output=True, text=True,
                  timeout=60)
        entry = entry_of(json.loads(out.stdout or "{}"), field) if out.returncode == 0 else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    return entry if entry and entry.get("landing") and train_state.alive(entry.get("pid")) else None


def started_at(entry: dict) -> dt.datetime | None:
    """When the adopted landing began (the entry's `enqueued`), so the watch takes its run (made after it)."""
    try:
        return dt.datetime.fromisoformat(str(entry.get("enqueued")).replace("Z", "+00:00"))
    except ValueError:
        return None


def stale(main: str) -> None:
    """The landing log of an earlier start moved aside (`<log>.before-adopt`): an adopted landing writes no line
    into it, and its last `status` (another train's refusal) was taken as this train's red (train 51, 2026-11-04)."""
    log = train_state.folder(main) / train_state.LOG
    if log.exists():
        log.replace(log.with_name(log.name + ".before-adopt"))


def adopt(main: str, field: str, train: dict, entry: dict, now: dt.datetime | None = None) -> tuple[int, str]:
    """The `started` line of a landing that runs without one: its pid, the branch hal2-git lands it on (the
    entry's `land_ref`, else hal2-git's `current` for the carrier; none recorded when neither names one, never the
    carrier's own name: plan 0607 D4) and its start time."""
    ref = (entry.get("land_ref") or land_name.current(main, field) or "").removeprefix("land/") or None
    stale(main)
    train_state.append(main, "started", field, started_at(entry) or now, train=train["train"], pid=entry["pid"],
                       land_ref=ref, why="adopted: a landing ran without a started line")
    return 0, (f"train {train['train']}: adopted the landing that runs (pid {entry['pid']}, {f'land/{ref}' if ref else 'its branch unknown'}); "
               "no second one started")
