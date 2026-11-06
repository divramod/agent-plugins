"""The next train's landing before it pushes (hal2 plan 0383 step 6, D6, L33, L34): `engine.py land` calls
`before_push` after the train's pretest, in the carrier's field, as the landing's own process. The next train forms
on the green merge job of the train before (minute.py) and is pretested at once; its land run waits here.

1. One land run at a time (L34; the role's Train flow: "workflow finished: only now does the next run start"):
   while a run of the landing workflow on another train's `land/` branch has not completed (the train before, its jobs
   after the merge still running; a run of this train's own earlier start never, plan 0560 D4), the landing waits, polling every POLL seconds, at most MAX_WAIT, one line when
   the runs it waits for change. hal2-git itself waits only while a run's merge job runs (ci/ship.rs). gh failing:
   no run known, no wait. The landing's train has started, so its cars are fixed (plan 0687 D1, superseding plan
   0610 D17 for started trains): no wagon joins in the wait; each poll and once more right before the push the
   landing's round (open_train.take) only owes a wagon hitched meanwhile that rides alone the very next train (plan
   0610 D15); every other later hitch rides the next train. A join recorded before the first start that waits for
   its resolve holds the push (open_train.stops, plan 0687 D4).
2. The post-merge fixes: each open post-merge order the train carries (train_state's `post`: a red after the merge
   of the train before, post_merge.py) whose foreman answered `done fixed <sha>` (orders.answered, the role's log)
   is checked, proven green (orders.proven, never waited for here: the round runs the proof) and merged into the
   carrier with its `fixed` line (orders.take), so it rides this train's run; a refused, unproven or unanswered one
   stays open and goes on to the next train. No wagon leaves the train and none joins: only fixes are merged.
3. The fix wait (fix_wait.py, plan 0490 step 21, D22): between 1. and 2., when the run before concluded red, the push
   waits until each of its red jobs has its fix car in the train or a named reason; each round merges the answered
   fixes (2.) and, while a red holds, runs the landing's round (open_train.take); a timeout wakes the tollman,
   never pushes.
"""

import functools
import time

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import fix_wait
import mtm_ci
import mtm_scan
import open_train
import orders
import train_branch
import train_state
from logstate import read_log

POLL = 30
MAX_WAIT = 6 * 3600  # the ship jobs' own limits are shorter; past it the landing goes on (hal2-git's own wait stands)


def others(main: str, own: str | dict) -> list[dict]:
    """The landing workflow's runs not completed on a `land/` branch that is not this train's: `own` the train (each
    of its starts' branches is its own, train_branch.ours, plan 0560 D4) or one branch."""
    mine = functools.partial(train_branch.ours, own) if isinstance(own, dict) else own.__eq__
    return [r for r in mtm_ci.runs_of(mtm_scan.run_json, main) if r.get("status") != "completed"
            and str(r.get("headBranch") or "").startswith("land/") and not mine(str(r.get("headBranch")))]


def wait(main: str, own: str | dict, sleep=time.sleep, clock=time.monotonic, join=None) -> list[str]:
    """1.: wait while another land run runs; the lines it printed. `join()`: the landing's round each poll while it
    runs (its lines; open_train.take), never after it ended."""
    deadline, told, lines = clock() + MAX_WAIT, "", []
    while runs := others(main, own):
        ids = ", ".join(str(r.get("databaseId")) for r in runs)
        if ids != told:
            told = ids
            lines.append(f"next train: its land run waits for run {ids} to finish (one land run at a time)")
            print(lines[-1], flush=True)
        if clock() >= deadline:
            lines.append(f"next train: run {ids} still runs after {MAX_WAIT // 3600} h: the landing goes on")
            print(lines[-1], flush=True)
            break
        if (joined := join() if join else []) and not lands(main):  # no longer landing: the push waits (0610 E5)
            return lines + joined
        lines += joined
        sleep(POLL)
    return lines


def merge_posts(top: str, main: str, train: dict) -> list[str]:
    """2.: the answered post-merge fixes merged into the carrier; a line each."""
    log, lines = read_log(main, train_state.ROLE), []
    for o in train.get("post") or []:
        if not (answer := orders.answered(o, log)):
            continue
        sha, note = answer
        code, text = orders.proven(top, main, o, sha, note, foreground=False)  # proven by the round (plan 0522 D5)
        code, text = (code, text) if code else orders.take(top, main, train, o, sha)
        lines.append(f"fix order {o['id']}: {o['field']}'s fix {sha[:12]} " +
                     (f"stays open: {text[:400]}" if code else f"merged into train {train['train']} ({text[:12]})"))
        print(lines[-1], flush=True)
    return lines


def before_push(top: str, sleep=time.sleep, clock=time.monotonic) -> list[str]:
    """1., 3. and 2. for the train that stands in the carrier `top`; the lines printed."""
    main = mtm_scan.main_checkout(top)
    train = train_state.standing(train_state.lines(main))
    if not train:
        return []
    joins = functools.partial(open_train.take, top, main)  # owes alone cars only: no join (plan 0687 D1)
    lines = wait(main, train, sleep, join=joins)  # never its own earlier start's run (plan 0560 D4, L200)
    if lands(main):
        lines += fix_wait.fixes(main, train["train"], lambda: merge_posts(top, main, current(main) or train), joins,
                                sleep, clock)
    lines += joins() if lands(main) else []  # alone cars hitched until now, also with no run before (plan 0610 E4)
    return lines + (merge_posts(top, main, current(main) or train) if lands(main) else [])


def current(main: str) -> dict | None:
    """The train that stands now (a fix merged since changes its `post`)."""
    return train_state.standing(train_state.lines(main))


def lands(main: str) -> bool:
    """Whether the standing train still lands: a car that joined with its resolve order makes it `resolving`."""
    return (current(main) or {}).get("state") == "landing"
