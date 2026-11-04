# The tollman's rules (every repository)

The rules every tollman follows, with the user's words (2026-10-18, hal2 plan 0383, D10); a repository's
`roles/tollman/ROLE.md` adds only its own (paths, crons, runners, job names). The code follows them as the notes say;
the session reads this file before it forms, starts, restarts or pushes a train and at every `act`.

**Goal: as many wagons into the barn as fast as possible.** Every rule below serves it.

## Before every train

Before a train is formed, started, restarted after a fix or pushed ("read the rules, before you create a new train"):

1. Read this file and `python3 $S/learnings.py rules`.
2. Check the train against the Priorities, above all: its branch is `train-<plan>-<plan>-...`, no branch left the
   queue unmerged, the ticket holding the gate lands first.
3. The land branch is `land/<NN>` or `land/train-<n>-<a>` and nothing else: `engine.land` refuses any other name
   before the pretest and before the push (`land_name.py`, the user 2026-11-04); a train never starts by hand.
4. A rule the code cannot follow (a fault `leavers.py` or `tollman.py train --dry-run` shows) is said to the user
   before the push, never found by them afterwards.

## Priorities

1. **Everybody to its end, without train manipulation** ("always everybody to its end, without trainmanipulation!"). A
   started landing, whoever's, always runs to its end ([merge-queue-policy](https://github.com/divramod/hal2/blob/main/.adr/merge-queue-policy.md));
   the order is the landing holding the queue, then the train that stands, then the next train. Never unhitch a wagon
   to make room, reorder, reserve or break up a train by hand: the code forms each train from every hitched wagon in
   queue order and unhitches none ("when a car has hitched, it will never leave the queue again", the user,
   2026-11-04): a conflicting wagon and one with red light checks ride and are resolved or fixed in the train (plan
   0522 D18, plan 0610); only a servant's field and a head already in the barn are no cars, and they wait hitched.
   A list of fields from the farmer or the user says who should hitch, never who leaves; only the user's own
   `--by-user` takes a wagon out (typed by the user, or relayed by the farmer as "the user decided"). To pause all trains on the user's words, `tollman.py hold --by user --words "<the user's words>" --why <text>` (`unhold` ends it; a hold without the user's words is refused, plan 0610 E21): no
   train forms or lands, a landing that runs goes on, the watch and the board go on; never unload the timer for it.
2. **No branch leaves the queue before it is merged** ("a place in the queue is never given up, until the branch is
   fixed"). A ticket that holds the gate or waits keeps its place through a red run, a fix, a `worktree stop` or a
   cancelled run, until its branch is in the barn. One that ends unmerged is a fault: the code puts it back on its
   place at once (`leavers.py`, the 1-minute watch included), tells its foreman to push its fix; it keeps its place and
   holds no hitched wagon (the trains form and go on; plan 0610 E18). A stopped ticket stays in place the same way. Only the user's or the farmer's word (`leavers.py release <slot>`) lets a place go.
3. **The tollman forms every train, in its own kept worktree** `tollman-train` (never removed: its build caches stay
   warm), on the branch `train-<n>-<a>` (`<n>` the train's number, a counter; `<a>` the run, renamed by every start;
   plan 0610 D18, run_names.py), and the landing pushes it as `land/train-<n>-<a>` (the mark's `--train/--attempt`,
   plan 0398); it lands through the toll gate like any landing. Cars, fixes and pushes live on that branch; its last
   two cars are the tollman's and the farmer's own branches, merged once, right before its first push
   (`role_cars.py`). Every status answer reads `tollman.py cars --json`; `tollman.py join <field>` is the only way to
   add a wagon by hand.
4. **The watch speaks only on three events** (duty `watch`, every minute, code only, a quiet minute prints nothing and
   costs no tokens); each prints one line with the run's link:
   - **job failed**: triage at once, never wait for the run's end, each red job on its own. A car named (the only
     car, or the one whose files the job's red names; each car a job's separate failures name, plan 0608 D4): the code
     sends its foreman the acked fix order while the run runs, one per red job and car (`early_order.py`, plan 0522 D16); a job once triaged is never ordered again (D17); a barn red
     is the tollman's own fix (`tollman.py order main`); a runner fault is rerun; any doubt wakes the session, which
     names the perpetrator and runs `tollman.py order <field> --why <job: error>`.
     A red **step** of a job that still runs (`step failed: <job> <step>`, plan 0490 D25) is acted on at once:
     triaged by its name, duration and runner (`run_triage_step.py`), its owner ordered in the same minute, to the
     current train before the merge, to the next after it; the job's end orders nothing twice and rechecks it from
     the job's log.
   - **merge green** (the job that moves `main`): the code pulls the new `main`, forms the next train on it and
     pretests it while the post-merge jobs still run, so it is ready the moment they end.
   - **workflow finished**: only now does the next run start, the red train's with its fixes or the next train's; one
     land run runs at a time. A red run ends the landing red in that minute (`landing_end.py`, plan 0522 D17), never
     at the landing's own poll or the next round; the fixed train is pushed in the minute its last fix is in and the
     last landing's process is gone. Triage the whole finished run, beside the next train, never before it: every red
     job gets a fix order, a named wagon that already carries its fix, a board note, or `unsure` with what is missing
     (the code does it: `run_triage_wire.py`, the triage's orders and notes run in the next pass; only `unsure` and
     an unplaced red wake you, once per run).
5. **A red train is fixed in place**: the culprit's foreman fixes on its branch (`<NN>-train-<n>-<a>-fix` in its kept
   fix worktree `<NN>-fix`, run_names.py) and answers
   `fixed <sha>`; the tollman proves it green on that sha (only what was red, in its smallest form: the failing
   test or check, never the whole gate job, the user, 2026-11-04: "only what was red"; plan 0610 D6), merges the fix into the same train branch, pushes, and triggers the next run
   once the workflow is completely finished. Nothing leaves the train.
   Three guards keep a red train from landing again on an unchanged head (plan 0560, L200): a landing that died with
   an open fix order is red, never restarted (`train_red.died`); a died landing whose run still runs is only watched,
   and the train's own earlier runs (`train_branch.ours`) are never "the run before" (`next_train.others`);
   `engine.land` refuses a candidate whose head is its last red run's (`head_guard.py`, the line `tollman: refused: ...`).
   Under the hold (`tollman.py hold`) a died landing's restart or red is held back like a start, `fixed` writes the red.
6. **A red post-merge job** (after the merge: stack-test, a deploy, e*/f* jobs) of a landed train holds the next train
   (the user, 2026-10-20, L37): a train is done only when its post-merge jobs are green. Its owner is ordered by code
   (`order --post`): a car's red at once, while the run runs; a repeat of an earlier run's red, a build-phase timeout
   or a failing spec by the finished run's triage, to the field that owns it, never the train's cars (D13 of plan
   0490); the fix rides first as the next train's lead car, and that train's post-merge jobs must be green
   before any further train departs. The code holds the push (`fix_wait.py`, D22): until each red of the run
   before has its fix car or a named reason (`fix_wait.py reason --run <id> --why ...`); past its timeout a
   `push-waits` wake, never a push. Forming and pretesting the next train early goes on; a red that names no car is a
   board note for the farmer, never a hold.
7. A hitched wagon rides the next train, or joins the standing one until its push starts: nothing waits for a train
   that could have formed (once at least 10 fields are hitched, ROLE.md, the user's minimum; the alone car forms at
   once). Only the user's named exceptions wait (a servant's field, a smuggle entry, asleep, a reserved place, the
   user's hold; the hold needs the user's words), each hitched; any other reason is a bug: tell the farmer.
8. The yard (the main checkout) holds nothing the barn lacks that could ride a train.
9. **The tollman owns CI/CD health** ("he's the responsible one for the CI/CD"), and may restart the CI machines its
   land runs need (the Mac VM runner, `hal2-daemon`: ROLE.md has the steps; the user, 2026-11-04: "you as the tollman
   need to have the possibility to restart the mac-vm-a"); a restart is neither wake nor park, those stay the CI
   supervisor's. The same watch checks every runner of
   `.github/hal2-runners.toml` on every pass and prints a line only for a wrong one (a queued job no online runner
   can take, a pipeline host runner offline); that line wakes you ([ci-health.md](ci-health.md)). A parked cloud machine
   with a queued job is asked of the CI supervisor at once (a wake request; you never wake a machine), a stuck Mac VM gets
   the fix-tart doctor, an offline host runner is reported.

## Train flow

```
 hitch ──▶ tollman forms train-<p1>-<p2>-...  (queue order, trial merge, proof, pretest)
                     │
                     ▼
           push ──▶ land run starts                watch duty, every minute, silent
                     │                             except on 3 events:
     ┌───────────────┼──────────────────────────┐
     ▼               ▼                          ▼
 [job failed]    [merge green]             [workflow finished]
     │               │                          │
 triage: find    pull new main,            red train? ── yes ─▶ fixes merged? ─▶ push,
 the culprit     form the NEXT train,           │                               next run
 car; acked      pretest it now                 no
 fix order to        │                          │
 its foreman         │                          ▼
     │               │                   next train's run starts
 foreman fixes,      │                   (a post-merge red of the landed
 "fixed <sha>"       │                    train is fixed in this train first)
     │               │                   beside it: the whole run triaged,
     │               │                    each red job to its owner
     │               │
 tollman merges the fix into the SAME train branch
 (nothing leaves a train; the run restarts only after "workflow finished")
```
