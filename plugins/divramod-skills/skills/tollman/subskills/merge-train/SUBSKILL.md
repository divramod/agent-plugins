# tollman › merge-train

The duty `trains` of the [tollman](../../SKILL.md), opted in by roles/tollman/ROLE.md. At every round every
hitched wagon becomes a car of one train, so the gates run once (the user, 2026-10-06: "in the best case, as now, it combines all
waiting worktrees into one train."; since 2026-10-13 the tollman's, not the farmer's: hal2's
[wagon-master](https://github.com/divramod/hal2/blob/main/.adr/wagon-master.md) and
[merge-queue-policy](https://github.com/divramod/hal2/blob/main/.adr/merge-queue-policy.md) rule 3). It runs as code:
`trains.py` plans (`python3 $S/tollman.py train --dry-run` shows what it would do now, changing nothing),
`engine.py` does, `trial.py` is the trial merge, `proof.py` a car's light gate checks. What needs judgment wakes the session with
[instructions/trains.md](../../instructions/trains.md).

## What the code does each round

1. **Ready wagons**: the tickets marked `ready` in `hal2-cli-git worktree queue --json`, in queue order, each with the
   head the foreman pushed. A foreman marks it with `hal2-cli-git worktree queue ready` (the hitch) and does not wait.
   Nothing is unhitched (the user, 2026-11-04: "when a car has hitched, it will never leave the queue again"); only
   the user-named exceptions wait, hitched (`trains_draft.EXCEPTIONS`): a head already in the barn (settled as landed
   by code), a servant's field (it holds `plans/LEAD`, whatever its number), a smuggle entry, the sleep flag, the
   user's hold. A worktree that is gone rides from its hitched sha; a head the standing train's carrier holds already
   is a car (`carried`). While a place the user reserved for a field that is not ready stands in the queue (`worktree
   queue order`, `/adapt-merge-queue`), the wagons behind it wait: that field is to land first. It rides as soon as
   it hitches; the boss's `reservation-waits` tells the user when nothing moves. A placed ticket that left the queue
   (`leavers.py`) keeps its place and holds no hitched wagon. A train forms once at least 10 fields are hitched and
   takes every one (ROLE.md).
2. **Alone rule** (`gate_car.py`, plan 0610 D9, D15): only a crop that adds, removes or renames the landing
   workflow or changes its `on:`, `name:` or `run-name:` is the alone car (the train's own run cannot test what
   starts and finds that run); a crop touching other gate files (`.github/hal2-*.toml`, `code/bash/scripts/gate/`,
   jobs, lanes) rides with the others. The alone car holds no other wagon: the others form their train now, the
   alone car rides alone in the very next train, formed at once (no 10-field minimum), keeping its ticket and ready
   mark, ahead of every later hitch.
3. **Trial merge** (`git merge-tree --write-tree`: nothing checked out, no ref moves): each head merged onto the
   barn's head in queue order. Every hitched wagon rides (plan 0522 D18): one that conflicts, in any file (lockfiles
   too), is a car with `conflict` (its files) and `ahead` (the cars it conflicts with, none: the barn), and the
   trial goes on without its head; the train forms by `tollman.py resolve-form` and resolves it in the train (step
   4). No wagon is unhitched for a conflict; a wagon leaves only on the user's own word. Unless every file of
   the conflict is generated (`.github/hal2-versions.toml`'s `[[generated]]` paths: `plans/uats.md`, the code maps,
   the record index, INTENT.md's log, the Rules in RULES.md or AGENTS.md): that wagon rides with no resolve, the merge in the field takes the barn's
   side and the train's last commit writes those files again by the map's commands (plan 0313 step 8). The rest
   rides. No maximum. A trial merge that cannot run is tried once more, then the car rides `untried` and `form`
   merges it. Every car is proven (`proof.py`, plan 0333 step 4): the light gate checks (names; records for
   `plans/`, `.adr/`, `docs/`, `*.md`) on its hitched head, in its own field or, when the field moved on or is gone,
   in the kept scratch worktree; red rides with `proof_red` (its finding lines) and a fix order in the train
   (`proof_orders.py`); a check that cannot be decided rides with `proof_unknown`, the pretest and the gate run it.
   A finding the barn's own head shows too is the barn's fix order (`order main`), never a car's.
4. **Form**: in the own field `tollman-<repo>`, on the barn's head: the yard's first car (the yard job), then a
   merge commit per car, the `CURRENT_PLAN` pointer filled (the cars' plan names joined by ` + `: hal2-git reads the landing's descriptive subject and its `Plan:` trailers from it; the `Worktree:` trailer lists the cars' fields, `02, 03`, the yard as `main`), the
   train marked (`worktree queue train <own field> <car>... --train <n> --attempt <a>`, a car's ticket then names its carrier as `rides_with`),
   and `hal2-cli-git worktree merge-to-main --json` started detached (`engine.py land` stays its parent; its output
   in `train-landing.log`). The tick never waits for CI. With a conflicting car (`resolve_train.py`): the cars merge
   in queue order; at the conflict the merge is undone, the carrier's head pushed to its remote branch and the train
   waits `resolving` (frozen, not marked, nothing starts). The round sends the car's foreman one acked resolve order
   `<NN>-resolve-<n>` (never a second for the same conflict): resolve on `<NN>-train-resolve` from `origin/<carrier>`,
   both sides' intent kept, answer `done resolved <sha>`; the ack runs `tollman.py resolved` by code (checked: on the
   branch, from the base, the car's head in it, no conflict marker left; refused: the foreman told why, the order
   open), the carrier fast-forwarded to it, the cars behind merged (a new conflict: a new order), then marked and
   landed; the landing's pretest (the light checks) runs before the push.
5. **Open train** (plan 0360 D3, D7, plan 0610 D17; `frozen.py`, `open_train.py`): from its `formed` line on nothing
   leaves the train. A wagon that hitches while it stands, in any state before its push (formed, resolving, red,
   fixing, retry), joins it until the push starts, with a resolve or fix order when it has a conflict or red light
   checks, and a riding car's newer head joins as an update of its car; the join round runs every tick, also before
   the first start. A hand merge of a hitched head is recorded as a car (`tollman.py join <field>`), never left
   untracked; `tollman.py cars --json` reads the cars and the waiting wagons by code. After the push a hitch rides the
   next train. A train formed but never started is started as it is (the cars the field
   lacks merged first); a queue mark naming other cars is marked again at the next start; no wait limit ends a
   waiting or red train. The session's `unhitch` of a car and `engine.py breakup` are refused; only the user's own
   command (`--by-user --words ...`, a `user-order` record) takes a car out or gives the train up.
6. **State**: every change of the train is a line of `train.jsonl` (`formed`, `resolving`, `resolved`, `started`, `run`, `red`, `order`, `fixed`, `pause`, `resumed`, `retry`, `unhitched`,
   `landed`, `cleared`) and of the message board. A train that stands is no waiter for the boss and its field holds
   the cars' commits; between trains the field equals the barn.
7. **Landed** (green): each car's foreman gets "in the barn" (the cars' tickets go with the landing), the field is
   reset to the barn, and the same round forms the next train (`chain.py`: the duty again until a wait, at most 3
   links). The foreman restocks, finishes its plan and mucks out; the tollman resets no other field.
8. **Watch and red**: while the landing runs, each round reads its land run (`watch.py`: the run on the train's own branch
   `land/train-<n>-<a>`, plan 0398, after the last start, noted as a `run` line); its first red job is triaged (`triage.py`) and wakes once,
   `train-red:<run>`. A red landing is triaged as code: a runner fault (the transient patterns, `transient.py`, in the
   failed log) lands the same cars again on a fresh run with no wake, after 3 in a row one `runner_broken` wake; the
   barn's red (the same job red in another slot's earlier land run on the same barn head) and a car's red are one
   wake (`train-failed`, `main_red` or `car_red`, with the evidence: red jobs, failing tests, each car's files, the
   log's tail; `tollman.py triage <run>` prints it) and nothing else; the train stays as
   it is and waits for its fix (the session's fix order, below), or the session's `retry --why` (the same train lands again, on a fresh land run: an
   empty retry commit gives it a new candidate, plan 0313 step 13). Only the user's word (`unhitch <field> --why --by-user --words ...`)
   takes a car out (the same call breaks the train up and forms the rest). An interrupted landing (its process gone)
   is started again at once and adopts its run, at most 5 times; then the train is red and waits as above.
   **The fix order** (plan 0360 D6, D29; `orders.py`) replaces unhitch-after-red and breakup: `tollman.py order
   <car field> --why <cause>` tells the car's foreman (acked) to fix on `<NN>-train-fix` from `origin/<carrier>` (the
   carrier's head, published first) and answer `fixed <sha>`; `order main` is the barn's red, fixed by the tollman's
   own hand on `tollman-train-fix`. The train is `fixing` (frozen as red) while an order is open; `tollman.py fixed
   <field> <sha>` (the round runs it from the foreman's ack) checks the sha is on the branch and descends from the
   order's base, proves it green (`fix_proof.py`, plan 0522 D5: a light job run by the tollman on the sha, a heavy
   one by the red check's own `green: <check> at <sha>` line in the ack, plan 0610 D6: only what was red), merges it into the carrier and, after the last
   order, the same cars land again on that merge.
   **A smuggle** (plan 0360 step 18, D58 to D62; `pause.py`, `smuggled.py`): hal2-git pauses the carrier's landing
   (`paused_by` on its ticket); the train is `paused` and frozen, one tick.log line per pause, no wake. A run the
   pause cancelled is no red (started again), a run whose merge succeeded lands. Resumed by hal2-git on the new main,
   the round logs it and watches the newer run. A merge conflict of the resumed landing goes as a fix order to the
   newest smuggle whose files conflict (else the newest smuggle); a red whose failing files or tests name a covered
   smuggle's files (triage `smuggled`) to that smuggle's field: `tollman.py order <slot> --smuggle`, by code.
9. **Leftovers**: a mark without a train line (a dead tollman's, no train of ours) is cleared and the round
   starts again at 1. A wagon that gets ready during a run joins the open train (5) until its push, else rides the next.

By hand the same is: `queue --json`, `git merge --no-ff` each pushed head in the own field, `queue train`, `merge-to-main`;
use the code instead, it writes the state the foremen and the farm view read.
