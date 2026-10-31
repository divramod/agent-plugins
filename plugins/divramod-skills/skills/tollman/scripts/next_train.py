"""The next train's landing before it pushes (hal2 plan 0383 step 6, D6, L33, L34): `engine.py land` calls
`before_push` after the train's pretest, in the carrier's field, as the landing's own process. The next train forms
on the green merge job of the train before (minute.py) and is pretested at once; its land run waits here.

1. One land run at a time (L34; the role's Train flow: "workflow finished: only now does the next run start"):
   while a run of the landing workflow on another `land/` branch has not completed (the train before, its jobs
   after the merge still running), the landing waits, polling every POLL seconds, at most MAX_WAIT, one line when
   the runs it waits for change. hal2-git itself waits only while a run's merge job runs (ci/ship.rs). gh failing:
   no run known, no wait. All that wait the train is open (open_train.py, plan 0490 step 20, D21, D23): each poll a
   newly hitched clean, proven wagon joins it; once the run before has concluded as a whole its cars freeze and the
   push starts, no join after it (D9: a join never delays the push of a train whose run before has ended).
2. The post-merge fixes: each open post-merge order the train carries (train_state's `post`: a red after the merge
   of the train before, post_merge.py) whose foreman answered `done fixed <sha>` (orders.answered, the role's log)
   is checked and merged into the carrier with its `fixed` line (orders.take), so it rides this train's run; a
   refused or unanswered one stays open and goes on to the next train. No wagon leaves the train: only fixes and
   newly hitched wagons join.
3. The fix wait (fix_wait.py, plan 0490 step 21, D22): between 1. and 2., when the run before concluded red, the push
   waits until each of its red jobs has its fix car in the train or a named reason; each round merges the answered
   fixes (2.) and, while a red holds, runs the open train's join round; a timeout wakes the tollman, never pushes.
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


def others(main: str, own: str) -> list[dict]:
    """The landing workflow's runs not completed on a `land/` branch other than `own` (this train's)."""
    return [r for r in mtm_ci.runs_of(mtm_scan.run_json, main) if r.get("status") != "completed"
            and str(r.get("headBranch") or "").startswith("land/") and r.get("headBranch") != own]


def wait(main: str, own: str, sleep=time.sleep, clock=time.monotonic, join=None) -> list[str]:
    """1.: wait while another land run runs; the lines it printed. `join()`: the open train's round each poll while
    it runs (its lines), never after it ended."""
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
        lines += join() if join else []
        sleep(POLL)
    return lines


def merge_posts(top: str, main: str, train: dict) -> list[str]:
    """2.: the answered post-merge fixes merged into the carrier; a line each."""
    log, lines = read_log(main, train_state.ROLE), []
    for o in train.get("post") or []:
        if not (sha := orders.answered(o, log)):
            continue
        code, text = orders.take(top, main, train, o, sha)
        lines.append(f"fix order {o['id']}: {o['field']}'s fix {sha[:12]} " +
                     (f"stays open: {text[-200:]}" if code else f"merged into train {train['train']} ({text[:12]})"))
        print(lines[-1], flush=True)
    return lines


def before_push(top: str, sleep=time.sleep, clock=time.monotonic) -> list[str]:
    """1., 3. and 2. for the train that stands in the carrier `top`; the lines printed."""
    main = mtm_scan.main_checkout(top)
    train = train_state.standing(train_state.lines(main))
    if not train:
        return []
    joins = functools.partial(open_train.take, top, main)  # the open train (plan 0490 step 20)
    lines = wait(main, train_branch.land(train), sleep, join=joins)
    lines += fix_wait.fixes(main, train["train"], lambda: merge_posts(top, main, current(main) or train), joins, sleep,
                            clock)
    return lines + merge_posts(top, main, current(main) or train)


def current(main: str) -> dict | None:
    """The train that stands now (a fix merged since changes its `post`)."""
    return train_state.standing(train_state.lines(main))
