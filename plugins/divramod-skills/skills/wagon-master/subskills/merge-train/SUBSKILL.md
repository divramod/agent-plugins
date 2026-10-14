# wagon-master › merge-train

The duty `trains` of the [wagon master](../../SKILL.md), opted in by roles/wagon-master/ROLE.md. At every round every
ready wagon becomes one train, so the gates run once (the user, 2026-10-06: "in the best case, as now, it combines all
waiting worktrees into one train."; since 2026-10-13 the wagon master's, not the farmer's: hal2's
[wagon-master](https://github.com/divramod/hal2/blob/main/.adr/wagon-master.md) and
[merge-queue-policy](https://github.com/divramod/hal2/blob/main/.adr/merge-queue-policy.md) rule 3). It runs as code:
`trains.py` plans (`python3 $S/wagon_master.py train --dry-run` shows what it would do now, changing nothing),
`engine.py` does, `trial.py` is the trial merge. What needs judgment wakes the session with
[instructions/trains.md](../../instructions/trains.md).

## What the code does each round

1. **Ready wagons**: the tickets marked `ready` in `hal2-cli-git worktree queue --json`, in queue order, each with the
   head the foreman pushed. A foreman marks it with `hal2-cli-git worktree queue ready` (the hitch) and does not wait.
   Unhitched without a word: a head already in the barn. Unhitched and told why: a servant's field (30-99).
   While a place the user reserved for a field that is not ready stands in the queue (`worktree queue order`,
   `/adapt-merge-queue`), no train forms: a landing waits behind such a place, and that field is to land first. It
   rides as soon as it hitches; the boss's `reservation-waits` tells the user when nothing moves.
2. **Alone rule**: a crop that changes `.github/workflows/`, `.github/hal2-*.toml` or `code/bash/scripts/gate/` rides
   as a train of one; when it is first in the queue it rides alone, otherwise it waits for the next train.
3. **Trial merge** (`git merge-tree --write-tree`: nothing checked out, no ref moves): each head merged onto the
   barn's head in queue order. A wagon that conflicts, in any file (generated files and lockfiles too), is unhitched
   (`queue ready <field> --clear`) and its foreman told the files and the cause by a template. The rest rides. No
   maximum.
4. **Form**: in the own field `wagon-master-<repo>`, on the barn's head: the yard's first car (the yard job), then a
   merge commit per car, `plans/CURRENT_PLAN` filled (the cars' plan names joined by ` + `: the land run's title), the
   train marked (`worktree queue train <own field> <car>...`, a car's ticket then names its carrier as `rides_with`),
   and `hal2-cli-git worktree merge-to-main --json` started detached (`engine.py land` stays its parent; its output
   in `train-landing.log`). The tick never waits for CI.
5. **State**: every change of the train is a line of `train.jsonl` (`formed`, `started`, `red`, `retry`, `unhitched`,
   `landed`, `cleared`) and of the message board. A train that stands is no waiter for the boss and its field holds
   the cars' commits; between trains the field equals the barn.
6. **Landed** (green): each car's foreman gets "in the barn" (the cars' tickets go with the landing), the field is
   reset to the barn. The foreman restocks, finishes its plan and mucks out; the wagon master resets no other field.
7. **Red**: one wake (`train-failed`, with the run, the cars and the failing job) and nothing else, until the session
   answers: `unhitch <field> --why` (that car goes back, the rest forms again) or `retry --why` (the same train lands
   again). An interrupted landing (its process gone) is started again at once and adopts its run, at most 5 times.
8. **Leftovers**: a mark without a train line, or a train a dead wagon master left behind, is cleared and the round
   starts again at 1. A wagon that gets ready during a run rides the next train.

By hand the same is: `queue --json`, `git merge --no-ff` each pushed head in the own field, `queue train`, `merge-to-main`;
use the code instead, it writes the state the foremen and the farm view read.
