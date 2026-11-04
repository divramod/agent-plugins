"""The forming of a train (`engine.py form`, `tollman.py resolve-form`; split out of engine.py by hal2 plan 0610 step 2,
small-files). Forming never drops a wagon (plan 0610 E25; the user, 2026-11-04: "take all finished ones into the
train"): the train's own worktree on the tollman's field's head (train_wt.py: the kept `tollman-train` on the branch
`train-<n>-1`, `<n>` the train's number, plan 0610 D18), the barn merged in, its `formed` line,
the yard's car (engine_yard.py), then the cars by `resolve_train.merge_rest`:

- a car that does not merge waits `resolving` with its resolve order on the train's branch (resolve.py), the cars
  behind it merged after its resolve; never a cleared train
- a failed regenerate of the generated files, or a mark the queue refuses, leaves the train standing `formed`: the
  next round's `restart` lands the same train (frozen.py), the tick wakes the session once
- a barn that does not merge into the tollman's field: the train forms on the barn's head, the field's own commits
  ride a later train (the session told by the form's text)
- an owed role car (left out of the train before, role_cars.py, plan 0610 D24) is merged first, right after the barn;
  left out a second time in a row, the train stands `stopped` (no yard, no car merged until its retry)
- `alone_next`: the alone cars that wait for their own train right after this one (gate_car.py, plan 0610 D9, D15),
  on the `formed` line: the next draft takes the first of them alone, before every later hitch (trains.plan)
"""

import datetime as dt
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import generated
import role_cars
import train_state
import train_wt
from carrier import Done, git, push_base
from engine_yard import load_yard


def form(top: str, cars: list[dict], now: dt.datetime | None = None, alone_next=()) -> Done:
    """The train of `cars` formed from the tollman's field `top` (see the module doc)."""
    import engine  # its `here`, `fetch`; engine imports this module's caller
    import resolve_train  # merge_rest: the cars, a conflict's resolve order, the restart
    main, _, train, _ = engine.here(top)
    if train:
        return 0, f"train {train['train']} stands ({train['state']}): no second one"
    if not cars:
        return 1, "a train needs a car"
    default = engine.fetch(top)
    number = train_state.peek_number(main)  # its carrier `train-<n>-1` in the kept `tollman-train` (plan 0610 D18)
    code, at, taken, apart = start(top, cars, default, number)
    if code:
        return 1, at
    if (taken_number := train_state.next_number(main)) != number:  # never: one tollman forms; then the branch follows
        train_wt.to_run(at, taken_number, 1)
    field, base = Path(at).name, git(at, "rev-parse", "HEAD")[1]
    name = "+".join(c["field"] for c in cars) + "@" + train_state.utc(now)
    pushed = push_base(at, field, base)  # a dead train an earlier end left on the remote (plan 0313 step 14)
    train_state.append(main, "formed", field, now, train=name, number=taken_number, cars=cars,
                       base=base, worktree=at, alone_next=list(alone_next) or None,
                       **({"pushed": pushed} if pushed else {}))
    stop, owed = role_cars.first(at, now)  # an owed role car first, before the yard and every wagon (plan 0610 D24)
    if stop:  # left out a second time in a row: the train stands `stopped`, its cars merged after the role car's retry
        return 0, "; ".join([*owed, *(t for t in (apart, pushed) if t)])
    note = load_yard(at, main, default, name, cars, now)[1]
    code, text = resolve_train.merge_rest(at, now, taken)
    return code, "; ".join(t for t in (*owed, text, apart, pushed, note) if t)


def start(top: str, cars: list[dict], default: str, number: int | None = None) -> tuple[int, str, list[str], str]:
    """The train's worktree with the barn in it: (0, its path, the generated files taken, why the field's own head
    stays out) or (1, why, [], ""). The field's head first; when the barn does not merge into it, the barn's head (the
    train's branch moved there; the field keeps its commits). With the train's `number`: the kept `tollman-train` on
    `train-<number>-1` (train_wt.add, plan 0610 D18)."""
    code, at = train_wt.add(top, cars, number)  # the train's own worktree on the field's head (plan 0375 D5)
    if code:
        return 1, at, [], ""
    behind, taken = git(at, "merge-base", "--is-ancestor", default, "HEAD")[0], []
    if not behind or not git(at, "merge", "-q", "--no-edit", default)[0] or (taken := generated.take(at, "--theirs")):
        return 0, at, taken, ""
    git(at, "merge", "--abort")
    why = f"{default} does not merge into {Path(top).name}: the train forms on the barn's head, its own commits ride later"
    # the branch was made by this call on the field's head: the field's own branch keeps every commit of it
    code, out = git(at, "reset", "-q", "--hard", default)
    return (1, f"{why}; not reset: {out[-200:]}", [], "") if code else (0, at, [], why)
