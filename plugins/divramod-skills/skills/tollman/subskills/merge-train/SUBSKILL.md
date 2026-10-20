# tollman › merge-train

The duty `trains` of the [tollman](../../SKILL.md), opted in by roles/tollman/ROLE.md. At every round every
ready wagon becomes one train, so the gates run once (the user, 2026-10-06: "in the best case, as now, it combines all
waiting worktrees into one train."; since 2026-10-13 the tollman's, not the farmer's: hal2's
[wagon-master](https://github.com/divramod/hal2/blob/main/.adr/wagon-master.md) and
[merge-queue-policy](https://github.com/divramod/hal2/blob/main/.adr/merge-queue-policy.md) rule 3). It runs as code:
`trains.py` plans (`python3 $S/tollman.py train --dry-run` shows what it would do now, changing nothing),
`engine.py` does, `trial.py` is the trial merge, `proof.py` a car's light gate checks. What needs judgment wakes the session with
[instructions/trains.md](../../instructions/trains.md).

## What the code does each round

1. **Ready wagons**: the tickets marked `ready` in `hal2-cli-git worktree queue --json`, in queue order, each with the
   head the foreman pushed. A foreman marks it with `hal2-cli-git worktree queue ready` (the hitch) and does not wait.
   Unhitched without a word: a head already in the barn. Unhitched and told why: a servant's field (it holds `plans/LEAD`, whatever its number).
   While a place the user reserved for a field that is not ready stands in the queue (`worktree queue order`,
   `/adapt-merge-queue`), no train forms: a landing waits behind such a place, and that field is to land first. It
   rides as soon as it hitches; the boss's `reservation-waits` tells the user when nothing moves.
2. **Alone rule**: a crop that changes `.github/workflows/`, `.github/hal2-*.toml` or `code/bash/scripts/gate/` never
   rides with other crops: the ALONE crops ride together as one gate train. The first car that rides sets the
   kind: ALONE first, a gate train of every further ALONE car (the others wait for the next train); otherwise a
   normal train, and the ALONE cars wait for the next, a gate train.
3. **Trial merge** (`git merge-tree --write-tree`: nothing checked out, no ref moves): each head merged onto the
   barn's head in queue order. A wagon that conflicts, in any file (lockfiles too), is unhitched
   (`queue ready <field> --clear`) and its foreman told the files and the cause by a template, unless every file of
   the conflict is generated (`.github/hal2-versions.toml`'s `[[generated]]` paths: `plans/uats.md`, the code maps,
   the record index, INTENT.md's log, AGENTS.md's Rules): that wagon rides, the merge in the field takes the barn's
   side and the train's last commit writes those files again by the map's commands (plan 0313 step 8). The rest
   rides. No maximum. A clean wagon rides only with its proof (`proof.py`, plan 0333 step 4): the light gate checks
   (names; records for `plans/`, `.adr/`, `docs/`, `*.md`) green on its hitched head in its own field; red is
   unhitched with the finding lines, a field not at its hitched head waits ("no proof yet").
4. **Form**: in the own field `tollman-<repo>`, on the barn's head: the yard's first car (the yard job), then a
   merge commit per car, `plans/CURRENT_PLAN` filled (the cars' plan names joined by ` + `: hal2-git reads the landing's descriptive subject and its `Plan:` trailers from it; the `Worktree:` trailer lists the cars' fields, `02, 03`, the yard as `main`), the
   train marked (`worktree queue train <own field> <car>... --train <n> --attempt <a>`, a car's ticket then names its carrier as `rides_with`),
   and `hal2-cli-git worktree merge-to-main --json` started detached (`engine.py land` stays its parent; its output
   in `train-landing.log`). The tick never waits for CI.
5. **Frozen** (plan 0360 D3, D7; `frozen.py`): from its `formed` line on nothing leaves the train. A wagon that
   hitches meanwhile rides the next one; a train formed but never started is started as it is (the cars the field
   lacks merged first); a queue mark naming other cars is marked again at the next start; no wait limit ends a
   waiting or red train. The session's `unhitch` of a car and `engine.py breakup` are refused; only the user's own
   command (`--by-user`) takes a car out or gives the train up.
6. **State**: every change of the train is a line of `train.jsonl` (`formed`, `started`, `run`, `red`, `order`, `fixed`, `pause`, `resumed`, `retry`, `unhitched`,
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
   empty retry commit gives it a new candidate, plan 0313 step 13). Only the user's `unhitch <field> --why --by-user`
   takes a car out (the same call breaks the train up and forms the rest). An interrupted landing (its process gone)
   is started again at once and adopts its run, at most 5 times; then the train is red and waits as above.
   **The fix order** (plan 0360 D6, D29; `orders.py`) replaces unhitch-after-red and breakup: `tollman.py order
   <car field> --why <cause>` tells the car's foreman (acked) to fix on `<NN>-train-fix` from `origin/<carrier>` (the
   carrier's head, published first) and answer `fixed <sha>`; `order main` is the barn's red, fixed by the tollman's
   own hand on `tollman-train-fix`. The train is `fixing` (frozen as red) while an order is open; `tollman.py fixed
   <field> <sha>` (the round runs it from the foreman's ack) checks the sha is on the branch and descends from the
   order's base, merges it into the carrier and, after the last order, the same cars land again on that merge.
   **A smuggle** (plan 0360 step 18, D58 to D62; `pause.py`, `smuggled.py`): hal2-git pauses the carrier's landing
   (`paused_by` on its ticket); the train is `paused` and frozen, one tick.log line per pause, no wake. A run the
   pause cancelled is no red (started again), a run whose merge succeeded lands. Resumed by hal2-git on the new main,
   the round logs it and watches the newer run. A merge conflict of the resumed landing goes as a fix order to the
   newest smuggle whose files conflict (else the newest smuggle); a red whose failing files or tests name a covered
   smuggle's files (triage `smuggled`) to that smuggle's field: `tollman.py order <slot> --smuggle`, by code.
9. **Leftovers**: a mark without a train line (a dead tollman's, no train of ours) is cleared and the round
   starts again at 1. A wagon that gets ready during a run rides the next train.

By hand the same is: `queue --json`, `git merge --no-ff` each pushed head in the own field, `queue train`, `merge-to-main`;
use the code instead, it writes the state the foremen and the farm view read.
