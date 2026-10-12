# farmer › merge-train

The duty `trains` of the [farmer](../../SKILL.md), opted in by roles/farmer/ROLE.md (`trains: "*/15 * * * *"`). At
every round everything waiting behind the current run becomes one train, so the gates run once (the user,
2026-10-06: "its a duty of the farmer to always create the merge train for all the queued worktrees behind the
current run. in the best case, as now, it combines all waiting worktrees into one train."; hal2's
[merge-queue-policy](https://github.com/divramod/hal2/blob/main/.adr/merge-queue-policy.md) rule 3). Its rule-based part runs as code in the tick: `trains.py`
(`python3 $S/trains.py plan --repo <main>` shows what it would do now, sending nothing), the test is `trial.py`'s
trial merge. What needs judgment wakes the farmer session with [instructions/trains.md](../../instructions/trains.md).
The by-hand practice it mirrors: [merge-to-main-boss › Merge trains](../merge-to-main-boss/SUBSKILL.md#merge-trains).

## What the code does each round

1. **Carrier**: the queue's holder while its candidate is not pushed (`hal2-cli-git worktree queue --json`: its
   ticket is `held` with the reason `reserved`, no lease (`kept_until`) and no landing; a slot with the user's
   priority included), else the first waiter. A running landing, a red candidate's hold and a kept lease are never
   touched: then the first waiter carries, and its train lands after the current run.
2. **Passengers**: every other waiting ticket, in queue order, whose branch has commits the default branch lacks
   and whose slot is no subservant's (`plans/LEAD`). No maximum, and no look at the plan: a ticket in the queue
   says the branch is to land.
3. **Trial merge** (`trial.py`, `git merge-tree --write-tree`: nothing is checked out, no ref moves): the carrier's
   branch merged into the default branch, then each passenger in order. Clean, or conflicts only in append-only
   docs and generated files (INTENT.md, AGENTS.md, CLAUDE.md, Cargo.lock, the workspace-hack): it rides. A conflict
   anywhere else: left out, named to the carrier and in the log, and it lands alone after the train. The carrier is
   told to merge the passengers' branches (`git merge --no-ff --no-edit`, one at a time, in that order), run its
   quick checks and land as usual (/mtm); a merge that conflicts after all, or a passenger change that fails before
   the landing merged: `git reset --hard ORIG_HEAD` for it, land without it, name it.
4. **Passengers** keep their tickets (their follow-up landing is quick; hal2 cannot cancel another slot's ticket
   without killing its `reserve`): told to wait, then `/mfm` after the carrier lands and `/mtm` what is left.
5. **Record**: `train:<carrier>+<passenger>...` in the log. For 12 hours its passengers are not taken again and its
   carrier is watched; a carrier that has not landed yet takes on the waiters that came since (a new train record); a busy session gets the message as a relay. A carrier waiting for the user holds the train.
6. **Failure**: the carrier's ticket held by a failed landing while its train is under way wakes the farmer
   (`train-failed`): the train splits.
