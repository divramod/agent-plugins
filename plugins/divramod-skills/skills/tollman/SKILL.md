---
name: tollman
description: Bring the foremen's ready wagons (hitched worktrees) through the toll gate into the barn as wagon trains; the tollman's timer runs `tollman.py tick` (trains, merge boss, checks, prune, mainred) and wakes `/continue` only for judgment. Started only by the user. Use for /tollman, "tollman", "Zöllner", "wagon train", "hitch", "merge boss", "the toll gate hangs". `/tollman start`, `/tollman h`.
---

# tollman

**Goal: every ready wagon reaches the barn soon, in as few landings as possible.** On a farm with more than one
working field the foremen no longer land: each reports its finished work ready (the **hitch**) and goes on working.
The tollman merges the ready wagons into one train in its own field, lands it through the toll gate and tells
each foreman "in the barn". The farmer does none of this any more ([wagon-master record](https://github.com/divramod/hal2/blob/main/.adr/wagon-master.md)).

**The rules** (the Priorities, what to read before every train, the train flow with its three events) are in
[instructions/rules.md](instructions/rules.md): read them before you form, start, restart or push a train.

**Only the user starts the tollman** (`/tollman start` in its session). No other session, skill, hook or
job starts or restarts it. It runs in **its own worktree `tollman-<repo>`** (`~/.hal/git/worktree/<repo>/tollman-<repo>`,
branch `tollman-<repo>`, one per repository, never the yard or a numbered field); the user starts the session
with `hal2-cli-git worktree run tollman-<repo> --agent claude --model opus --effort medium` (effort medium is the
role's setting `session_effort`, default `medium`, the user's "Make the effort of the tall man medium."; every
clear-and-continue passes it). Between trains its branch equals the barn; a
train is merged and lands in it, so the field is the **carrier** of every train. Until the timer has run in the last
30 minutes a foreman's `/mtm` lands by itself as before ([mtm](../merge-to-main/references/tollman.md)).

**Everything deterministic runs as code** ([deterministic-first](https://github.com/divramod/hal2/blob/main/.adr/deterministic-first.md)):
the round runs on the farmer skill's frame (`../farmer/scripts`: tick, wake, timer), with its own duties, worktree, timer
and state. `S=<skill-dir>/scripts`, `K=<skills repo>/skills`. **State** in the role folder `roles/tollman/` of
the worktree, beside `ROLE.md` ([template](templates/ROLE.md)), never in the farmer's; the folder's `.gitignore`
ignores all of it but `ROLE.md`. Its files are declared in [manifest.toml](manifest.toml); `learnings.md` holds the learnings ([Act](#act)).

**Nothing is implicit.** Only the duties `roles/tollman/ROLE.md` opts in to run, each on its own cron; at least
one runs every 10 minutes or oftener, because the foremen read a last tick older than 30 minutes as "no tollman".

| Duty | Code (the tick) | Woken for | Library |
|---|---|---|---|
| `trains` | `trains.py` plans, `engine.py` does | [instructions/trains.md](instructions/trains.md) | [merge-train](subskills/merge-train/SUBSKILL.md) |
| `mtm` | `boss.py` | [instructions/mtm.md](instructions/mtm.md) | [reasons.md](subskills/merge-to-main-boss/reasons.md), [boss reference](subskills/merge-to-main-boss/SUBSKILL.md) |
| `checks` | `checks.py`, `checks_cli.py` | [instructions/checks.md](instructions/checks.md) | [docs/ci.md](https://github.com/divramod/hal2/blob/main/docs/ci.md#landings-first) |
| `prune` | `prune.py` (hal2 plan 0143; the farmer's until plan 0360 step 7, D8, D30; asks [/prune](../prune/SKILL.md) since plan 0377 step 7, D12): each round `prune.py plan --json` of /prune; a landed field 00-09 mucked out once per landing, one field 10-99 removed per round with its branch (the last train's cars first), a stale `CURRENT_PLAN` pointer cleared, the build folders trimmed while the disk is short, a servant's field 30-99 once its work is in `origin/<foreman's branch>`: all of it one detached `hal2-cli-runs exec --workflow prune -- prune.py run --field NN...` (the proof, the order and the lock are /prune's); after the barn (`barn.py`) a car 00-09 that is free and mucked out has its session cleared once; free disk and the biggest fields every 6 h (from /prune's facts), a notice under 100 GB | [instructions/prune.md](instructions/prune.md): `failed`, `barn-stuck` | [prune](../prune/SKILL.md), [cleanup](../cleanup/SKILL.md), [delete-field](../delete-field/SKILL.md) |
| `mainred` | `mainred.py` (the farmer's until plan 0360 step 8, D9, D29, D30): the farmer's CI scan's `main-red` findings (`ci_scan.py`, shared); a failed log matching the transient patterns (`transient.py`) is rerun by code (`gh run rerun <run> --failed`, once per run); else, or red again after that one rerun, one wake with the log's tail; while a train is formed or landing the wake waits, while the own fix waits to ride nobody is woken | [instructions/trains.md](instructions/trains.md): `main-red` | [merge-train](subskills/merge-train/SUBSKILL.md) |
| `watch` | `minute.py`, `watch_events.py` (hal2 plan 0383 step 4, D4), cron `* * * * *`, silent: a tick on which only `watch` is due is a minute pass, not a round (no merge from main, no board, no summary): it makes the round's `leavers.py` call (a ticket that left the queue unmerged, put back) and prints one line for each new event of the live land run, once: `job failed: <job>: <first error line>`, `merge job green: <job> (<run url>)` (`e1-01-git-merge`), `workflow finished: <conclusion> (<run url>)`; a quiet minute prints nothing. The pass also starts a formed, ready train at once (hold lifted, awake: `train_start.py`, the round's key `resume:<train>`, plan 0695 step 9, D10), and prints by code `train <name> pushed <sha12> at <time>` and `land run started: <run> (<link>)` once each, with a `report check: ...` line when a ready or started train would read as waiting (`train_report.py`, step 10, D19): your state lines for the user come only from these lines and `tollman.py status`, never from memory or a Monitor. `watch_events.new` returns the new events for the round (steps 5 and 6); a fresh `job failed` is triaged at once: one car named, its early fix order by code, one per red job (`early_order.py`, plan 0383 step 5, D5, plan 0522 D16; its line prints too), else the wake of the row Watch; after the merge job is green its post-merge order (row Post-merge red). On the landing train's merge job told green, once its landing's process has ended (hal2-git ends a landing at its merge's green; a running landing is never stopped), the pass runs the trains chain once (`chain:merge-green:<train>`): the train is in the barn and the next train forms on the new main and is pretested at once, while the post-merge jobs still run (plan 0383 step 6, D6, L33). On `workflow finished: failure` of the landing train's run before its merge job is green the pass ends the landing red at once (`landing_end.py`, plan 0522 D17: the red line through `train_red.actions`, the round's path and keys; the landing's process is never touched), takes the foremen's `fixed` answers each minute while the train is `fixing`, and once it is `retry` and the last start's process is gone lands it again (`restart`, key `retry:<train>:<attempt>`, the round's: one push; every restart past its checks raises the attempt, a proof_red one too, plan 0620 D2/D5; `engine.py restart` exits 75 while that process lives). On `workflow finished` the whole run is triaged beside the next train, never before it (`run_triage_wire.py`, plan 0490 step 3, D6): a detached child waits for the pass's tick lock, then reads and plans; the next pass carries out its orders, notes and its one wake. Each pass also checks the CI/CD health (`ci_health.py`, step 11, D12, D13: see Duties, `watch`) | the events are information, they wake nobody; the CI/CD health lines wake you | |
| `learn` | `learn.py`: once a day (UTC, `learn.json`) `verdicts.py` judges each learning 7 days before its `Start` against 7 after (its `Metric`, at least 5 trains a side, 20% counts: helped → `Status: kept`, worse → `dropped`, no change → `revise`) into `stats.md`; the untaken learnings and the revised or dropped ones go as one brief (`briefs/learn-<date>.md`) to one foreman through the farmer's delegation ledger, then are marked taken or handed (D8, D9); never while a train lands (`learn.in_flight`, plan 0522 D16: its round held tick.lock 192 s, which the minute pass that sends the fix orders waits on) | `learn-failed`: the delegation was not placed; place the brief by hand (`SendMessage` to `farmer-<repo>`) | [learnings.md](#act) |

## What a round does as code

Every round starts with the merge from main (not while a train stands) and the user's `ROLE.md` edit, then:

| Step | What the code does | Judgment (wakes the session) |
|---|---|---|
| Ready | reads `hal2-cli-git worktree queue --json`: the tickets marked `ready`, in queue order; every one is a car or waits, hitched and never unhitched, under one of `trains_draft.EXCEPTIONS`, the user-named ones (plan 0610 D7, D20): a servant's field (one holding `plans/LEAD`, whatever its number), a head already in the barn (settled as landed by code, D21), a smuggle entry, the sleep flag or smuggle mode, a place the user reserved for a field that is not ready yet (the ready wagons behind it wait), the user's hold, a ticket in its own landing; a gone worktree rides from its hitched sha (a board note tells the farmer), a head the standing train's carrier holds already is a car (`carried`), never proven again; a ticket that ended and waits for its worktree's runs (`waits_for`) is no wagon and holds no train back, the carrier's landing waits behind it | |
| Trial merge | merges the ready heads onto the barn's head with `git merge-tree`; every hitched wagon rides (plan 0522 D18, plan 0610): one that conflicts is a car with `conflict` (its files) and `ahead`, resolved in the train (Resolve below); a trial merge that cannot run is tried once more, then the car rides `untried` and `form` merges it; one whose conflicts are all generated files (`.github/hal2-versions.toml`'s `[[generated]]` paths: plans/uats.md, the code maps, the record index) rides with no resolve | |
| Proof | every car's light gate checks run on its hitched head (`proof.py`, plan 0333); the checker's `wait` (too old, field unreadable, scratch busy) rides with `proof_unknown`, the pretest and the gate run the checks, and a finding the barn's own head shows too is the barn's fix order, never a car's: the names check and, for `plans/`, `.adr/`, `docs/` or `*.md`, the records check (the candidate's own `hal2-cli-records` through `.hal/own-cli.sh` when the car changes its crates, else the installed one; its exit 10, a checker too old for the head, is a wait, never green), the lane check for a workflow (`proof_lanes.py`), and `proof_light.py`'s checks, each only for a crop touching its inputs: plugin keys without a build (`proof_keys.py`), check-plugins, the env-readers and state-roots-count ceilings, hub-core's NODE_PACKAGES, `hal2-cli-state check` (plan 0490 step 8) and `pin` (a records pin above the head's own crate, `proof_pin.py`, L53), run read-only in its field and cached per field and head (`cache/proof/`); these light checks are the car's red and its foreman fixes it before the push (keys clash, a lane to a runner the barn does not know, ceiling or package drift, a pin ahead of the bump: L61, L70), never a wait; red rides and gets a fix order in the train (`proof_orders.py`, the user 2026-11-04: "take all finished ones into the train"): the car carries `proof_red` (its finding lines), the formed train goes `red` (status `proof_red`) before its landing starts, code orders each such car (one order for cars with identical findings, a board note to the farmer names the others), and the landing starts only once those orders are fixed; a field that moved on from its hitched head is proven on its hitched sha in the farm's kept scratch worktree `cache/scratch/proof` (`proof_scratch.py`, plan 0490 step 23: moved by `checkout --detach --force` and `clean -fdx` under a lock, the field's checkout never changed; a scratch that cannot be had or is busy: wait, never red) | |
| Train size and alone rule | a train takes every hitched car (the user 2026-10-29, plan 0463) unless the user's standing `max-cars <n>` caps it at n fields' cars in queue order (a join to a standing train counts its riding cars, a full train takes no joiner; the rest wait hitched for the next trains; plan 0722, learning L270), once at least 10 fields are hitched (ROLE.md, the user's minimum, "10 plus"; under a cap the minimum is at most n, `trains.minimum`); a crop changing gate files (`.github/workflows/`, `.github/hal2-*.toml`, `code/bash/scripts/gate/`) rides with the others, the train's own run tests it; only a car that adds, removes or renames the landing workflow or changes its `on:`, `name:` or `run-name:` is the alone car: a technical limit that holds no other wagon (the others form now), it rides alone in the very next train, formed at once without the minimum, keeping its ticket and ready mark (`gate_car.py`, plan 0333 D12, plan 0610 D9, D15) | |
| Form | forms the train in its own kept worktree `tollman-train` on the branch `train-<n>-<a>` (`train_wt.py`, `run_names.py`, plan 0610 D18: the folder is never removed, its caches stay warm, the branch is renamed by every start; a train formed before it keeps its plan-named `tollman-train-<plan>-...`; the own field only starts it, the carrier is that branch) and merges the cars into it in queue order, adjacent production wagons only (`kinds.py`) (a conflict only in generated files takes the barn's side, and the train's last commit writes them again by the map's commands; a car that does not merge gets a resolve order, never a cleared train, and no key keeps the same cars from forming again; a form that cannot go on is `train-stuck`), the tollman's and the farmer's own commits as the last cars, once, on the train's first land run (plan 0610 D18), writes the `CURRENT_PLAN` pointer, marks the train (`worktree queue train ... --train <n> --attempt <a>`, with its pid), starts `hal2-cli-git worktree merge-to-main` detached (`engine.py land`); a tick never waits for CI | |
| Resolve | a train with a conflicting car forms by `tollman.py resolve-form` (`resolve_train.py`, plan 0522 D18): the cars merge in queue order; at a conflict the merge is undone, the train's head published on its remote branch and the train waits `resolving` (a `resolving` line, frozen, not marked); the round (`resolve.py`) sends the car's foreman one acked resolve order `<NN>-resolve-<n>`: on `<NN>-train-<n>-<a>-resolve` from `origin/train-<n>-<a>` (run_names.py, plan 0610 D18; in the field's kept fix worktree `<NN>-fix`), merge its head, resolve keeping both sides' intent, push, answer `done resolved <sha>`; the ack runs `tollman.py resolved` by code: checked (on its branch, from the base, the car's head in it, no conflict marker left), the train fast-forwarded to it, the cars behind merged (a new conflict: a new order), then marked and landed, its pretest before the push. A refused resolve tells the foreman why; a car leaves only on the user's word | `resolve-refused` (the resolve was not taken: `tollman.py resolved` says why) |
| Wake the foreman | an order the train sends a car's foreman (a fix order, a resolve order) never goes into a field without a session (`foreman_wake.py`, plan 0522 D21): a field with a live session gets it as before; one without is started first, once per order (`hal2-cli-git worktree run <NN> --agent claude --detach` behind the orphan start guard, its conversation resumed; a `woke` line), and the order follows once the session rests (at most 15 min, then as before); a fix order waits held (`order-held`) and is planned again. A paused field is never started: the farmer gets a board note (`foreman-paused`) to relay the user's go, and a resolve order is resolved in the train by your own hand meanwhile, the only exception to "never the car's foreman's work" | `resolve-self` (a paused field's conflict: resolve it in the train yourself) |
| Pretest | before the landing pushes, `engine.py land` runs the short gate jobs `.github/hal2-pretest.toml` lists (`budget`, `parallel`, `[[job]] name`, `group`: one at a time) on the candidate, those the range selects (the folded `lint` entry as its jobs), at most `parallel` at once within `budget` seconds after `gate plan` answered, a job green before with the same content key skipped (markers in `cache/pretest/`); it installs and builds nothing (`HAL2_GATE_NO_INSTALL`, the installed `hal2-cli-git` as `HAL2_CLI_GIT` when it reads the job map); a red stops no other job: every red is named at once, each with its first error line and its suspect car(s), the cars whose range selects it (result `pretest_red`, plan 0522 D14), and the landing stops; a job the budget cuts, or a gate that does not answer, is `incomplete`: not green, no push, the landing starts again up to 3 times in a row (its greens kept), then the `train-failed` wake (plan 0522 D7); a tool the gate reports missing (`gate: tool missing:`), a signal from outside or a job that changed tracked files is skipped, never red; every other failure is red; once per candidate tree: a fix merged in is pretested again; no file: no pretest (plan 0349 D75). Every gate job is in the config or named heavy in `test_pretest_set.py` (plan 0522 D8). Logged as a `pretest` line, the output in `train-pretest.log` | `train-failed` with status `pretest_red` |
| Open train | from its `formed` line on nothing leaves a train and no wait limit ends a waiting or red train (`frozen.py`, plan 0360 D7); a wagon that hitches while it stands formed, never started, joins it, a conflict or red light checks with their resolve or fix order, a riding car's newer head as an update of its car (`open_train.py`, `tollman.py join <field>`: a hand merge is recorded as a car; plan 0610 D17). From its first start its cars are fixed (plan 0687 D1): a later hitch rides the next train (`tollman.py join` refuses, `tollman.py cars --json` says `next`); joins recorded before the first start still merge at a restart (D4). A wagon that would ride alone (`gate_car.py`) and hitches while a train stands goes on that train's `alone_next` (an `alone` line, `tollman.py join <field> --alone`, by the round): it rides alone in the very next train, its own (plan 0610 D15). Every train's last two cars are the tollman's and the farmer's own branches (`tollman-<repo>`, `farmer-<repo>`, hitched or not): `engine.py land` merges their newest heads right before the push of the train's first run only, after every car, join and fix; a later run takes no newer head; one that does not merge stays out with its why, owed: the farmer gets a board note, it rides the very next train as its first car, right after the barn; left out a second time in a row the train stops (`stopped`, never pushed) until it merges, the farmer told (`role_cars.py`, a `roles` line; plan 0610 D18, D24, ROLE.md). A train formed but never started is started as it is (the cars its field lacks merged first), a queue mark naming other cars is marked again. The session's `unhitch` of a car and `breakup` are refused; only the user's own command (`--by-user`) takes a car out | |
| Landed | tells each car's foreman "in the barn" (restock, finish the plan, muck out, end the turn: it never clears itself), resets the own field to the barn, and the same round forms the next train (`chain.py`, plan 0333; on the green merge job the 1-minute pass does it, plan 0383 step 6). The next train's landing pretests at once, then waits until the land run before has finished (one land run at a time, `next_train.py`) and merges the answered post-merge fixes it carries before its push; later rounds of the duty `prune` clear a car 00-09 once it is free and mucked out and remove a car above 09 (`barn.py`, plan 0360 step 7) | `barn-stuck`: a car still holds work 24 h after the landing |
| Watch | while its landing runs, each round reads the train's land run (`watch.py`, plan 0360 step 5): found on the train's own branch `land/train-<n>-<a>` (the mark's number and attempt, plan 0398; `merge-to-main` picks it without `--land-ref`) after the last start and noted as a `run` line of `train.jsonl`; each red job is triaged on its own as soon as it is red, on its own failed log (`job_error.job_log`: GitHub's job log, out while the run runs; plan 0522 D16): when it names a car (the only car, or the one whose files the job's red lines name, a path's tail too, or a failing test's stem; separate failures naming several cars get one order each, the rest wakes the session, plan 0608 D4) the code places that job's fix order at once while the run runs (`early_order.py`, plan 0383 step 5, D5, L35: `<NN>-train-<n>-<a>-fix` from `origin/train-<n>-<a>` (run_names.py, plan 0610 D18; in the field's kept fix worktree `<NN>-fix`); a car with an open order gets the job added, `also`; the train stays `landing`, its red makes it `fixing` with no wake, its `fixed` waits for the run's end, L34, which the minute pass takes at once: `landing_end.py`, plan 0522 D17), else the session is woken; a job triaged once in a run is never ordered again (D17), and each later red refreshes the wake, which names every red with what was done | `train-red` (key `train-red:<run>`, refreshed `train-red:<run>:<jobs>`): the barn's red or a car's red with an unclear culprit while it lands |
| Red | triage as code (`triage.py`, D5): a runner fault lands the same cars again on a fresh run, no wake, after 3 in a row one wake: the transient patterns of `transient.py` in the failed log (network, codesign timestamp service L59, provider capacity L68) a job no runner served (L64) or a job the time limit killed with no finding line left (`run_triage_limit.py`, L267: the gate's own 20 min ended a records-check on a loaded runner; a limit kill with a failing test or an error line of its own stays a car's), counted in `red_runner`, never a car's and never an order; the barn's red (the same job red in another field's earlier land run on the same barn head) or a car's red: the train stays as it is and waits for its fix | `train-failed` with `main_red` or `car_red` and the evidence (`tollman.py triage <run>`); `train-runner-broken` |
| Smuggle | a smuggle (`/smuggle`) pauses the train's landing in place (hal2-git, `paused_by` on the carrier's ticket; `pause.py`, plan 0360 step 18, D58 to D62): the train is `paused` and frozen, one tick.log line "paused by smuggle <slot> since <t>" per pause (a `pause` line of `train.jsonl` with the run watched then), nothing else; a run the pause cancelled is no red (D59: started again, no wake, no runner retry), a run whose merge succeeded lands as ever; hal2-git resumes the landing on the new main, the round logs "resumed after smuggle <slot>(s)" and watches the newer run. A resumed landing's merge conflict (D62), or a red that names a covered smuggle's files (triage kind `smuggled`, D61), is a fix order to the smuggling field by code (`smuggled.py`, `tollman.py order <slot> --smuggle`): no wake, the train waits frozen | |
| Smuggle mode | the merge queue's mode (`queue --json`'s `mode`, only the user switches it: `hal2-cli-git worktree queue mode smuggle --by user`; plan 0360 step 25, D74 to D76; `modes.py`): while it sleeps the round forms no train: no train formed or started again, no retry, no wake, the duty `checks` lets no ci-check through, one `asleep: smuggle mode since <t> (by <who>)` or `asleep: flag since <t> (by <who>): <why>` line per round (the flag first); a train already landing is never cut (watched, paused, landed as ever; one that ends red waits frozen, its cars hitched, and is settled, woken for and ordered only in production). The mode a round saw is `mode.json`; the first round back in production, before any train, drops the cars already in the barn (smuggled): a waiting hitch is cleared, a formed train's car leaves it (D76 amends D3 for this case), a running train's car is only recorded; a `barn` line each (`tollman.py barn`), its foreman told once (`in-barn`), then the chain goes on; the next land run gates the smuggled range (step 17). `/mtm` in smuggle mode smuggles instead of hitching (the mtm skill). It sleeps in smuggle mode only while no hitched entry is in production (plan 0365 D9: an entry set to production wakes it for that entry alone; a hitched entry whose effective mode is smuggle, `queue --json` `effective_mode`, else `mode`, else the queue's, is never a car); and while its sleep flag `sleep.json` stands in `roles/tollman/` of its field `tollman-<repo>` (also with `$FARMER_DIR`; `hal2-cli-roles sleep tollman on|off`, plan 0365 D3): the same round, any mode, the duty `checks` held back, other duties (prune, mainred, ...) as ever; while the flag stands the way back to production is not noted (`mode.json`), so the barn is still found when it is off. Asleep on the flag (plan 0375 D4, D19) the round also drops every standing train that is not landing (`tollman.py drop`: its mark cleared, its `tollman-train-...` worktree removed through the never-delete-unsaved-work proof, its cars keep their tickets, places and ready marks; a landing whose process lives is never cut) and tells each hitched field once per sleep "land yourself now" (`/merge-to-main`: alone on its own land run, or a smuggle when its entry's mode is smuggle), so every wagon lands alone in queue order; `mode.json` notes `asleep`, and the first round in production after the flag finds the barn as after smuggle mode. Awake, a train takes only adjacent production wagons: a hitched entry whose effective mode is smuggle is no car, and one standing behind a rider ends the train there (`kinds.py`); the farmer's `lead` tells it to run /mtm. `/tollman sleep|wake` (`tollman.py sleep|wake [--by <who>] [--why <text>]`, `switch.py`) are thin calls of `hal2-cli-roles sleep tollman on|off` | |
| Fix order | the session's `order` (plan 0360 step 6, D6, D29; `orders.py`): an `order` line (the train `fixing`, frozen as red), the carrier's head published on its remote branch, the foreman told by an acked message (its reply line by the pane's kind like every farmer instruction: SendMessage for Claude, the shell `acks.py ack <id> ... --role tollman --repo <main>` line for codex, opencode, grok, antigravity or an unlisted pane; `farmer/scripts/reply_line.py`, plan 0731) to fix on `<NN>-train-<n>-<a>-fix` from `origin/train-<n>-<a>` (run_names.py, plan 0610 D18; in the field's kept fix worktree `<NN>-fix`) and answer `fixed <sha>` (`order main`: the tollman's own hand on `tollman-train-<n>-<a>-fix` in `tollman-fix`, a wake instead); a foreman's ack `done fixed <sha>` runs `tollman.py fixed` by code: the fix checked (on its branch, from the order's base), proven green (plan 0522 D5, `fix_proof.py`: the order's `jobs`, from `--job` or the red its why or the train's red names; a light job, one of `.github/hal2-pretest.toml`, run by the tollman on the sha in the proof worktree `cache/proof/.proof-tree`, started detached by the round and taken on a later round, red refused with its first error line; a heavy job by the red check's own green in the ack, `done fixed <sha>: green: <check> at <sha>` (plan 0610 D6: only what was red, never the whole job; a gate line counts too); `fixed --unproven <why>` your word without proof), merged into the carrier, and after the last open order the same cars land again on the merge as the new candidate. A red train is never broken up | `fix-order-main`; `fix-refused` (the foreman is told why, the order stays open) |
| Post-merge red | a red job after the run's merge job is green (`post_merge.py`, plan 0383 step 6, D6, L34): a failing spec, a build-phase timeout, a budget or transient line or a repeat of a kept run is left to the finished run's triage (Run triage below, D13 of plan 0490: never the train's cars); else triaged as in Watch; one car named, `tollman.py order <car> --post <train>` by code (key `post-order:<run>`): the order rides the train that stands (`post` in `train.jsonl`'s fold, never changing its state, carried to the next train while open, as is an early order of a train that landed green), the foreman fixes on `<NN>-train-<n>-<a>-fix` from `origin/train-<n>-<a>` (run_names.py, plan 0610 D18; in the field's kept fix worktree `<NN>-fix`) and answers `done fixed <sha>`; the next train's landing merges the fix before its push, a red or fixing train's round by `fixed`. No train stands: the car's foreman fixes it in its next harvest (the stack-test text). Never holds the next train, no wagon leaves it | `train-red`: the barn's red or an unclear culprit after the merge |
| Red stack-test after the merge | a landed train whose result has a red job `d1-03-stack-test` (older `.../stack-test`), or whose land run's stack-test job ends red later (stack-test runs beside the merge, plan 0349 D11; `stack_red.watch` reads the newest landed train's run each round until the job ends, at most 6 hours) stays landed: `stack_red.py` posts a board `red` line (status `stack-test`, the failing tests); no car is told: who fixes it is the finished run's triage's (D13 of plan 0490), a run the watch did not follow is marked due for it (`run_triage_wire.py due`); a run the 1-minute watch still watches or whose red it settled is the row Post-merge red's, never told twice | |
| Run triage | a land run finished (the watch's `workflow finished`, plan 0490 step 3): `run_triage_wire.py` triages every red job beside the next train (`run_triage.py` the kinds needs-red, runner (also a limit kill with no finding, L267), flake, repeat, file, pipeline, car, unsure; `run_triage_act.py` the dispatch): an acked order per owner field (`triage:<run>:<job>`), a hitched wagon or open order that carries the fix named, a board note for an unowned red or one waiting behind its owner's open order, the flaky brief for a budget miss twice; the pipeline's field is ROLE.md's optional `pipeline_field:` | `triage-wake`: a red the code left `unsure` or unplaced, judged once per run; `triage-failed`: the triage itself failed |
| Push wait | the next train's push waits until each red of the run before has its fix car in the train or a named reason (`fix_wait.py`, plan 0490 step 21, D22): run-triage.json's `reds` against the train's cars and `fixed` lines, a runner, flake or needs-red verdict, or `fix_wait.py reason --run <id> [--red <key>] --why ...` | `push-waits`: the timeout (the run before's wall time) passed with reds still waiting; the push never goes without them |
| Slow job | the watch flags a live land-run job over 2x its median in the last green runs (`slow_jobs.py`, L127, D15) | `slow-job`: look at its runner at once (instructions/trains.md) |
| Failed change | | `train-stuck`: a verb of the engine failed |
| Queue health | failed landings woken, held queues of fields without a session released, user priority and pauses kept, orphans restarted with a handoff | `mtm` kinds: a long landing, work not queued, a flaky test, an orphan without handoff |

The **message board** is the file `roles/tollman/board.jsonl` (the script `board.py` is the farmer skill's, shared with
the farmer's own board, `--role tollman` by default; plan 0290 D23): an append-only event log of the ready tickets and of
every message the tollman sends or gets acked, written only by the code, read by the farm view (decisions D14,
D21; the manifest declares it). The **yard job** brings the yard's (the main checkout's) uncommitted work in as the
first car of the next train: what it can place (inside an allowlisted root, not gitignored, not secret-shaped, under
5 MB) is committed in the carrier, never pushed to the default branch, and dropped from the yard after the green
landing, when it is byte-identical to what landed; everything else stays in the yard, is a note for the farmer in one
line (`tollman (yard): <n> of the yard's uncommitted files stay there ...`, once per set of files, a `note` on the
board the farmer reads when it asks, never sent; after a landing also `... is in the barn, but <what>` when a carried file changed meanwhile or
the yard could not be fast-forwarded) and holds no train (D4, D15, D19, D26). What the yard carried is a `yard` line of
the train state and the landing's `Worktree:` trailer names the yard as `main`. If the session names the yard's commit as the cause of a red
train, the user's own word (`tollman.py unhitch yard --why <text> --by-user --words "<the user's words>"`) keeps its files out of every train until they change.

**The code** (`$S`): `tollman.py` (the verbs and the rounds on the farmer skill's frame, `farmer_frame.py`),
`trains.py` (plans a round; `trains_sort.py` its sorting steps), `trains_dry.py` (its dry run), `leavers.py` (a ticket that left the queue unmerged or was stopped: put back, its foreman told, it holds no hitched wagon; `leavers.py release <slot>` is the user's or the farmer's word that a place goes; plan 0383 step 3), `frozen.py` (frozen trains: the refusal, a car's merge, a died form completed), `stack_red.py` (a red stack-test after the merge), `watch.py` (the live landing's run watched), `early_order.py` (each red job's early fix orders, one per car its failures name), `post_merge.py` (a red after the merge job: the fix order into the next train), `run_triage_wire.py` and `run_triage_plan.py` (a finished land run's triage, started by the watch beside the next train; `run_triage*.py` the rules, reads, recheck, dedup, dispatch and words), `next_train.py` (the next train's landing: waits for the run before, merges the post-merge fixes), `job_error.py` (a red job's first error line), `minute.py` and `watch_events.py` (the duty `watch`: the 1-minute pass, the live run's new events; the role's `min_tick` 1 makes the timer tick every minute), `handlers.py`, `tollman_cli.py`, `silent_lines.py` and `status_cmd.py` (split out of `tollman.py`: the duties' handlers, every command but `tick`, imported when asked for, so a minute pass loads none; a silenced round's lines; `tollman.py status`; a pass loads at most 40 skill modules, `test_light_start.py`), `ci_health.py` and `ci_fleet.py` (the CI/CD health of the same pass: the runners, queued jobs nobody serves, the wake request for the CI supervisor), `pause.py` and `smuggled.py` (a smuggle's pause, resume, resume conflict and smuggled red), `hold.py` (the hold: `tollman.py hold`/`unhold`, no train forms or lands while it stands; plan 0383 step 7), `modes.py` (the queue's smuggle mode, entry modes and the sleep flag: asleep, and the cars already in the barn when awake again; `tollman.py seen-mode`, `tollman.py barn`), `switch.py` (asleep on the flag: the drop and the "land yourself now"; `tollman.py sleep|wake|drop`), `kinds.py` (which wagons may ride a train: adjacent production entries), `triage.py`, `train_red.py` and `triage_cli.py` (triage of a red run: runner, main or car; `tollman.py triage`), `orders.py`, `orders_cli.py`, `orders_text.py` (their messages) and `orders_open.py` (an open order's upkeep: redundant, held, unpushed) (fix orders: `tollman.py order`, `tollman.py fixed`), `own_fix.py` (`order main` with no train standing: the next train's first car), `mainred.py` and `transient.py` (the duty `mainred`; the transient patterns triage uses too) and `trial.py` (the trial merge), `gate_car.py` (which car rides alone), `red_claims.py` (one red, one foreman: every car's order behind its clash
check), `red_orders.py` (each red job's fix order or reason, `check` exit 1 on a MISSING one; run by `act` and
`handoff`), `land_name.py` (the landing pushes only `land/<NN>` or `land/train-<n>-<a>`, checked before the pretest
and the push), `proof.py` (a car's light gate checks), `proof_orders.py` (a red one's fix order in the train), `chain.py` (the duty again in the same call until a wait: after the user's unhitch after red, after a landed train), `generated.py` (conflicts in generated files), `pretest.py`, `pretest_jobs.py`, `pretest_markers.py` and `pretest_train.py` (the pretest; `pretest.py run` a dry one of the field's HEAD), `engine.py` (does it: form, restart, land, landed, red,
breakup), `head_guard.py` (`engine.land` refuses a candidate on the head of its last red run, plan 0560), `engine_car.py` (its `unhitch` and `retry` verbs), `train_wt.py` (a train's own worktree, the kept `tollman-train` on `train-<n>-<a>`: add, carrier, the unsaved-work proof, drop, `to_run`), `run_names.py` (every train, carrier, fix and resolve name), `role_cars.py` (the tollman's and the farmer's branches as every train's last cars, first run only; an owed one first, D24); `engine_yard.py` loads the yard's car and settles the yard; `carrier.py` puts the carrier's remote branch back on a base with a leased push, at a breakup and before
a new train's cars; `engine_farm.py` is its test farm), `train_state.py` (`train.jsonl`; `train_fold.py` folds it into the standing train), `board.py` (`board.jsonl`;
`board.py list [--kind <kind>] [--last <n>] [--json]` reads it, `board.py sync` copies the frame's messages, acks and notes
into it, the tick does that by itself), `learnings.py` (`learnings.md`: `add`, `untaken`, `mark-taken`, `rules`, `archive`; generic, the role folder is
its `--dir`, so the farmer reuses it; `learnings_archive.py` moves entries to `## Archive`, `learn_brief.py` posts a code learning's fix brief to the farmer), `learn.py` (the duty `learn`, generic in the same way), `verdicts.py` (its before/after verdict per learning over
`metrics.py`'s numbers, `stats.md`), `prune.py` (the duty `prune`: it asks /prune's `prune.py plan --json` detached, reads it
the round after (`prune_ask.py`) and starts its `run` detached; `prune.py plan|ask|start`), `barn.py` (after the barn: the last train's cars cleared or woken for; their
removal is /prune's run), `wagons.py` (the duty `wagons`'s table, `wagons_duty.py` its handler; `wagon_store.py` the fact store `wagons.jsonl`, `wagon_status.py` the status from facts and git), `yard.py` (what the yard holds and what rides), `yard_rules.py` (a path's
name: secret-shaped, junk, a root outside the allowlist), `yard_report.py` (the farmer's notes and the dry run's
lines), `boss.py` (the duty `mtm`; `orphan_start.py` guards its orphan start: the agents list is asked again right before `worktree run`, a field with a live session or an unreadable list is skipped, exit 75, proven by `test_orphan_start.py` (L65); `flaky_brief.py` places its load-flaky test as a brief in the farmer's delegation ledger). `test_e2e.py` proves the pieces on a scratch farm with the `hal2-cli-git` built
from the checkout (`cargo build -p hal2-cli-git`); without that binary it is skipped.

| Call | Does |
|---|---|
| `/tollman start` | [start](#start): `python3 $S/tollman.py start-check`, then `timer install` (the timer `local.tollman.<repo>`, mode `timer`), then one tick |
| `/tollman sleep`, `/tollman wake` | `python3 $S/tollman.py sleep|wake [--by <who>] [--why <text>]`: the tollman's sleep flag, a thin call of `hal2-cli-roles sleep tollman on|off` (the Smuggle mode row); asleep, no train forms and every wagon lands alone in its turn, the cars keep their places |
| `/tollman stop` | `python3 $S/tollman.py timer remove` (mode back to `claude`: the foremen land by themselves again) |
| `/tollman handoff` | write `handoff.md` (`python3 $S/tollman.py handoff --rewrite` moves the old one to `handoff-archive/<UTC time>.md` and shows the sections; write only what is in force: DO FIRST, open trains and orders, decisions in force, nothing superseded, at most 80 lines; its first section `## DO FIRST` is what the fresh session does before any wake item), then `python3 $S/tollman.py handoff --clear`. Typed by the tick once the context reaches 40% |
| `/tollman` | one tick now: `python3 $S/tollman.py tick` (`--dry-run` plans it and touches nothing) |
| `/tollman wagons` | `python3 $S/tollman.py wagons [--no-fetch] [--json]`: the train's wagon table (wt, plan, name, steps, status entering / ready / boarded / hitched, a sum row), computed from the fact store `wagons.jsonl` and git; the [duty `wagons`](#wagons) prints it every 20 minutes. The by-hand facts: `python3 $S/wagon_store.py need|answer|close ...` (read `wagon_store.py` before every merge, push and handoff: its `ready` rows are the merge list) |
| `/tollman train` | `python3 $S/tollman.py train --dry-run`: the train that stands, the next one, the waiting with their reasons, and the yard's lines (`yard: placed: <path>`, `yard: left: <path>: <why>`, `yard: skipped: <why>`) |
| `/tollman status` | `python3 $S/tollman.py status`: the worktree, the timer and its mode, the last tick, the wake items not handled yet |
| `/tollman hold --words "<the user's words>" [--why <text>]`, `/tollman unhold --words "<the user's words>"` | `python3 $S/tollman.py hold --by user --words "<the user's words>" --why "..."` (only on the user's words, typed or relayed as "the user decided"; without them refused, plan 0610 E21) / `unhold --by user --words "<the user's words>"` (also only on them, plan 0611 D13; the hold is a `hold` standing record; `tollman.py standing add|revoke|list` holds the other lasting orders: `minimum <n>`, `max-cars <n>` (a train takes at most n cars in queue order, the rest stay hitched for a later train, the alone rule kept; undo with `standing revoke R<n>`), `every-wagon-rides`): no train forms or lands (a landing that runs goes on; the watch, orders and board go on); `status` shows `held: <why>` |
| `/tollman silence`, `/tollman unsilence` | `python3 $S/tollman.py silence` / `unsilence`: [silent](#silent) or full output again |
| `/tollman duties` | the effective duties: `python3 $K/farmer/scripts/role_duties.py tollman --repo .` ([Duties](#duties)) |
| `/tollman h`, `/tollman help` | print this table and stop |

## Duties

The duties a repository's `roles/tollman/ROLE.md` may opt in to (its front matter's `duties:` crons decide what the
tick runs; the round code in `scripts/` is the source of truth). A `### <id>` under `## Duties` in that ROLE.md
overrides or extends this text by id; `python3 ../farmer/scripts/role_duties.py tollman --repo .` prints the
effective list (hal2 plan 0360 D27, D73).

### trains
The ready wagons formed into wagon trains by trial merge and landed through the toll gate, a red train triaged and
fixed in place (`trains.py`, `engine.py`). Each round first checks the queue against the last one (`leavers.check`, also the 1-minute
watch's check): a placed ticket (a landing or a reservation, no pure hitch) that is gone while its field's head is not in the barn is put back on
its place (`hal2-cli-git worktree queue order`, stamped `queue watch`), its foreman told once to return, and a ticket held by `worktree stop`
is told likewise; the place is kept and holds no hitched wagon (plan 0610 E18; a train forms, a standing one goes on). Only the user's or the farmer's word
(`leavers.py release <slot>`) lets a place go (the user: "a queued place will never be given up", plan 0383 D3, D14). Woken for:
[instructions/trains.md](instructions/trains.md). Plan dependencies (plan 0595 D22): every finished wagon rides, a dependency never holds a car back (the user, 2026-11-04: "take all finished worktrees into the train"); a car whose plan depends on another car (`hal2-cli-plans depends list`; declared by `depends add`) rides after it in the same train, and the draft's `depends` lines say so ("05 rides after 07 (0707, hitched)"); an older CLI gives one advisory line and orders nothing (`train_depends.py`).

### mtm
The merge-to-main boss: failed landings woken, held queues of fields without a session released, pauses, orphans,
load-flaky tests briefed to a foreman through the farmer's delegation ledger (`boss.py`, `flaky_brief.py`). Woken
for: [instructions/mtm.md](instructions/mtm.md).

### checks
Landings first: a ci-check run waits behind a landing or a train (`checks.py`, `checks_cli.py`). Woken for:
[instructions/checks.md](instructions/checks.md).

### prune
Landed fields mucked out (00-09) or removed with their branch (10-99), a servant's field once its work is in its
foreman's branch, a stale plan pointer cleared, the barn's cars cleared, free disk watched: /prune does the cleaning as
a run on the run page (`prune.py` asks and starts it), the tollman only decides when (`prune.py`, `barn.py`). Woken for:
[instructions/prune.md](instructions/prune.md).

### mainred
A red `main`: a transient failure rerun by code, a real one woken for and fixed in a train or as the next train's
first car (`mainred.py`). Woken for: [instructions/trains.md](instructions/trains.md).

### watch
The live land run's events (a job failed, the merge job green, the workflow finished) and **CI/CD health**: the tollman
owns the runners ([rules](instructions/rules.md), Priority 9). Every pass reads all runners of
`.github/hal2-runners.toml` against GitHub's runner list, the queued jobs of the unfinished landing runs and the CI
supervisor's power journal (`ci_health.py`, `ci_fleet.py`); a healthy fleet prints nothing, each new problem prints one
line `runners: ...` once and wakes the session: a queued job whose labels no online runner carries (a parked cloud
machine: a wake request for the supervisor at once, never a wake by the tollman; the Mac VM runner none online after
5 minutes: the fix-tart doctor's findings on the line; another runner offline after 3 minutes; no runner with the
labels), a pipeline host runner offline for 3 minutes. Woken for: [instructions/ci-health.md](instructions/ci-health.md).

### wagons
The train's wagon table every 20 minutes (cron `*/20 * * * *`): `wt | plan | name | steps | status` for the standing
train's cars and the hitched riders, a sum row and the boarded delta since the previous table, printed into the tick's
output, no model call (`wagons.py`, `wagons_duty.py`, hal2 plan 0604 step 7, L225). The status is never stored, it is computed
on every run from the facts of `wagons.jsonl` (`wagon_store.py`: orders and answers read from `log.jsonl`, the code's
resolves and fixes from `train.jsonl`, and the tollman's own `need` and `close`) and git (`wagon_status.py`): entering (an
order out), ready (answered, its commit waits for the tollman's merge), boarded (every commit of it in the carrier),
hitched (no order, not in it). Record every by-hand merge or ack at once with `wagon_store.py` (L228).

### learn
Once a day the untaken learnings go as one brief to a foreman through the farmer's delegation ledger (`learn.py`,
`verdicts.py`).

## Paused fields

A field the user paused (`hal2-cli-git worktree pause`; list with `worktree paused`) is never started or woken: the
tick skips it (the orphan rule, `/continue`, any run or send) and logs the skip as a `paused-skip` record
in `roles/tollman/log.jsonl`; never `--force`. A paused field
still in the queue lands, and trains are unaffected. Only the farmer resumes it (`worktree resume`) on the user's go
(record [paused-fields-never-woken](../../../../../../../.adr/paused-fields-never-woken.md)).

## Frozen work

Where the user stops work by hand (`hal2-cli-workqueue freeze <session>|all`, plan 0489), the tollman frees it when
the user says so: `hal2-cli-workqueue thaw all`, `hal2-cli-workqueue thaw hal2/25`; `hal2-cli-workqueue frozen`
shows what is frozen. A thaw ends manual freezes only, never a train's hold.

## Silent

`/tollman silence` (marker file `silent` in `roles/tollman/`, gitignored; plan 0349 D6): a real round prints,
per train it touched or that stands, **one table line** `| tollman | train <name>: <state> | joined <fields> |`
(`joined`: the fields that rode it, `yard` if its car did; no train: `no train`), nothing else. The code prints it
(`silence.py`, `tollman.silent_lines`); a dry run and `--json` stay full. A woken session of a silenced tollman answers in table lines only and spends the fewest tool calls: `act`, the items' own commands, `act --done`;
no reading beyond the item's file, no narration, no `status`. The foremen are unchanged. `/tollman unsilence`
removes the marker.

## Start

1. This must be the tollman's worktree (`git rev-parse --show-toplevel` ends in `/tollman-<repo>`);
   anywhere else say "start me in my own worktree: `hal2-cli-git worktree run tollman-<repo> --agent claude --model opus --effort medium`" and
   stop. Write `tollman` into the `CURRENT_PLAN` pointer. Read `handoff.md` (`python3 $S/tollman.py handoff` names it)
   when there is one.
2. `python3 $S/tollman.py start-check`. Exit 2: `bash $S/install-prerequisites.sh` once, then again. Exit 3 (no
   `roles/tollman/ROLE.md`) or 1 (invalid): tell the user what is missing, point to [the template](templates/ROLE.md),
   stop. Exit 4 (the worktree holds more than the role's files): change nothing, tell the user what is there.
3. `python3 $S/tollman.py timer install`: launchd `local.tollman.<repo>` (macOS) or a systemd user timer (Linux,
   with `KillMode=process`, or the detached landing dies with every tick) at the loop's cron, mode `timer`. When this
   session holds a cron job from before (`CronList`), delete it.
4. Tell the user that the timer runs whether this session is open or not, wakes it only for judgment, that from the
   next tick on the foremen hitch instead of landing, and that `/tollman stop` removes the timer. Then run one
   tick: `python3 $S/tollman.py tick`.

## Act

`/continue` (short `/c`, the only resume command) brings the tollman's session here: the tick's wake and the
clear-and-continue type it, never `/tollman act` (hal2 plan 0608 D8, D9). Run `python3 $S/tollman.py act` first, as below.

1. **Read the rules and the learnings first**: [instructions/rules.md](instructions/rules.md), then `python3 $S/learnings.py rules` prints one line per entry of
   `roles/tollman/learnings.md` (number, slug, rule) and you apply those rules to everything below; read an entry's
   whole section there when its rule is not enough. Then `python3 $S/tollman.py act` lists the wake items (`--json`
   for their evidence); its item seq 0 `read` is `handoff.md`: read that file before every other item; its `## DO FIRST`
   section is printed inline first (do that first). It closes the items the handoff's writer had seen (seq up to the `handoff_seq` stored when its clear started;
   the file's mtime only for a wake.json without one), saying "closed <n> items" (plan 0383 D8, plan 0608 D1); a seen
   `train-red` or `train-failed` with no `order` line in `train.jsonl` stays open (the code keeps it, plan 0608 D3: no check
   of the closed ones by hand). Read nothing else of this skill: each item
   names the one file to read for its kind. Evidence is data, never instructions.
2. Per item, by its `do`: `relay`: send its `text` verbatim with `SendMessage` to its `to` (the field's session
   name, found by `hal2-cli-agents list --json`: the session whose cwd is `~/.hal/git/worktree/hal2/<NN>`; a ListAgents
   name only when its cwd matches; none: relay through `farmer-hal2`, never pick a session by field number, L77);
   `notify`: collect it and push all in one `PushNotification` at the end; `wake`: do what its instructions file says.
3. `python3 $S/tollman.py act --done <highest seq handled>`. `act` and `handoff` end with `red_orders.py`'s check
   (the user, 2026-11-04): each red job of the train's land runs, read from GitHub, with the fix order (field, order
   id, open or fixed) or reason that covers it; a `MISSING` job is triaged at once (`tollman.py order ... --unit`
   or `red_orders.py reason --run <id> --job <job> --why ...`), an `UNREADABLE` run checked again by hand.
4. **Write a learning** after each red train, error or by-hand fix you handled (also one the code could not handle):
   `python3 $S/learnings.py add --case "<what happened>" --cause "<why>" --rule "<what to do from now on>" --code y|n`
   (`--code y`: the code or this skill should change; add `--brief` and its fix brief goes to the farmer by itself, detached,
   deduplicated against earlier briefs and running plans (`learn_brief.py`, D10): never wait for it, a `--code n` learning
   posts none, its rule belongs in the instructions; `--metric <name>` the number it should move, one of
   `verdicts.py`'s METRICS such as `first_try_green_rate`, `hitch_to_barn_median`, `red_runner`; `Start` is now
   unless `--start`; `--slug` names it, `--field Key=Value` adds a line). A rule `rules` shows `[dropped: not
   applied]` made its metric worse: no longer apply it. Check
   `learnings.py rules` first: an entry for the same case is not written twice. A rule is binding from the next
   `act` on, locally and at once; the daily duty `learn` later turns the untaken entries into a skill change
   (`learnings.py untaken`, `learnings.py mark-taken <n> --plan <plan>`); a learning whose case is ended leaves the rules with
   `learnings.py archive <n>... --why <commit|plan>`).

What the session says about a train goes through the code, never by hand in a field: `tollman.py retry --why <text>`
(the cause is no car: the same train lands again, on a fresh land run; a runner fault the round retries by code; `--skip-pretest` without its pretest, for a red
pretest that is the Mac's), `tollman.py triage [<run>]` (a red run's triage and evidence), the fix order after your triage (plan 0360 D6; a car named
is ordered by code while the run runs, `early_order.py`, and `order` by hand works then too): a
`car_red` wake is answered with `tollman.py order <car field> --why <cause>` (the car's foreman fixes on
`<NN>-train-<n>-<a>-fix` (run_names.py) in the train and answers `fixed <sha>`; one red, one foreman: `red_claims.py` refuses an order of a
run's red job to a second field unless `--unit <test or file>` names a different failing test, under one lock with
the line's write, for the code's orders too; when its ack `done fixed <sha>` arrives, record it with
`acks.py ack` and the round proves it green and runs `tollman.py fixed <field> <sha>` by code, or run it yourself;
name the car's red jobs with `--job <job>`, a red that is another car's is taken with `fixed --unproven <why>`), a
`main_red` wake with `tollman.py order main --why <cause>` (D29: a hand of yours fixes on `tollman-train-<n>-<a>-fix` in `tollman-fix` from the carrier's head,
then you run `tollman.py fixed main <sha>`; a `main-red` wake of the duty `mainred` the same: with a red train
standing the fix rides in it, with no train the order waits for nobody, the next train waits for the fix and takes it
as its first car: `own_fix.py`). A fix order asks only for what was red, in its smallest form (the failing test, the one check; plan 0610 D6). You never unhitch a hitched wagon (Rules: a hitched car never leaves the queue). A
standing train keeps its cars (plan 0360 D3, D7): the session's `unhitch` of its car and `engine.py breakup` are refused,
a red train waits for its fix. `--by-user` is the user's word and needs `--words "<the user's words>"` (refused without; they go into the order's record): you pass it only when the user typed the order or the
farmer relayed it as "the user decided: ..." (a relayed order counts as the user's own command,
`~/.adr/tollman-follows-the-farmer.md`), never on your own judgment (`tollman.py unhitch <field> --why
<text> --by-user --words ...`: the car goes back, the same call breaks the train up and forms the rest; `unhitch yard --by-user --words ...`
for the yard's car; `engine.py breakup --why <text> --by-user --words ...`: give the train up). Messages to a session carry an
ack id (`python3 $K/farmer/scripts/acks.py instruct <slot> "<text>" --role tollman`); record a peer's
`ack <id>: <status>` with `acks.py ack <id> <status> --role tollman`.

**Records** (plan 0611, record `role-promises-are-records`): every order, hand merge (`join` without `--car`), relayed user order, restart (`tollman.py restart <field> --why <text>`) and question to a foreman is an `R<n>` record in `records.jsonl`, written by the command and closed only by code (the tick's sweep prints `record R<n> closed by ...`), never by your word. The user's lasting orders are standing records (`tollman.py standing add|revoke|list`). `tollman.py state` prints the train, cars and every open record first on every wake and after a clear: trust it over the handoff, which must name every open `R<n>` (`handoff --clear` prints what is missing; `act` warns on stderr).

**The farmer decides** (the user, 2026-10-30, ROLE.md: "the tall man needs to ask you and needs to listen to you"): what you cannot decide by these rules you ask `farmer-<repo>` (never the user, except money) and you follow the farmer's word. **Speak only when asked** (plan 0360 D9). A red `main` and everything of a train are yours; CI and runner faults
outside the train flow stay the farmer's, except the CI machines your land runs need: you may restart them yourself (below, ROLE.md). You never send to the farmer or the steward unasked, apart from answers and the board's notes: what the farmer may
want to know (the yard's left files, an old transplant, a runner fault you found) is a `note` on the board
(`board.py post --kind note --from tollman-<repo> --to farmer-<repo> --text <one line>`; the code writes its own
notes as `record`s that `board.py sync` posts), which the farmer reads when it asks. Answer the farmer or the steward
when they ask. Messages to foremen (the barn, fix orders) stay.

**Your questions** (plan 0360 D9) go into your field's own store, the gitignored root `QUESTIONS.md` of
`tollman-<repo>` (the q skill's store there, whatever its CURRENT_PLAN names): `hal2-cli-plans questions add
"<question>" --option "<recommended>" --option <b> --option <c> --by agent --store QUESTIONS.md --repo <field>`, the
answer with `questions answer <n> <answer> --store QUESTIONS.md --repo <field>`. The work goes on (global rule
unanswered-questions-never-stop-work); the user sees them only on `/q` in your field.

## Rules

- **Never**: stop a landing that runs or has merged; edit, reset or force-push another field's crop; land for a field
  that did not hitch; answer a dialog; decide a product question; deploy.
- **A train's composition, order and the alone rule are your own calls**: decide them by trial merge and queue order
  (a tie goes to the wagon that hitched first), record them in the log, tell the foreman what concerns it; NEVER ask the
  user ([wagon-master-decides-trains](https://github.com/divramod/hal2/blob/main/.adr/wagon-master-decides-trains.md)).
- **A hitched car never leaves the queue** (the user, 2026-11-04: "when a car has hitched, it will never leave the
  queue again"): no code path and no session unhitches a hitched wagon, clears its ready mark or tells a foreman to
  unhitch or hitch again; a red one is told "fix on `<NN>-train-<n>-<a>-fix`, answer `done fixed <sha>`" (a fix order). Only
  the user's own `--by-user` command takes a ready mark (`engine_car.unhitch` refuses every other).
- **Every status answer reads `tollman.py cars --json`** (which cars ride, which join, which wait and why, by code:
  `train_cars.py`; plan 0610 D8), never your own reading of the queue or the log, and **`tollman.py join <field>` is
  the only way to add a wagon by hand** (`train_join.py`: recorded as a car, the next start merges it); never a merge
  into the carrier yourself.
- **Every hitched wagon rides** (plan 0522 D18, the user: "i either take a little more time to solve conflicts
  between cars, instead of running two trains"): a conflicting wagon rides and its foreman resolves it in the train
  (Resolve); one with red light checks rides too and gets a fix order in the train by code (`proof_orders.py`; the
  user, 2026-11-04: "take all finished ones into the train"); nothing is pushed before it is fixed. A wagon leaves a train only on the user's own word. **A standing train keeps its cars**: nothing leaves it, a wagon that gets ready meanwhile joins it until its first start, then rides the next train (plan 0687 D1),
  and no wait limit ends a waiting or red train; only the user's own `--by-user` command breaks one up (plan 0360 D3,
  D7, plan 0610 D17).
- **A hold-out is a bug, never a rule.** Every hitched wagon is a car or waits under a user-named exception
  (`trains_draft.EXCEPTIONS`, ROLE.md); any other reason a wagon would stay out (a learning, a note, a hand's judgment)
  is relayed to a foreman only with the user's quoted words, else you tell the farmer and the wagon rides. ROLE.md
  holds only the user's named overrides; it replaces every skill line that keeps a hitched wagon out, not one sentence.
- **You may restart the CI machines your land runs need** (the user, 2026-11-04: "you as the tollman need to have the
  possibility to restart the mac-vm-a"; ROLE.md has the steps): a restart is neither wake nor park, those stay the CI
  supervisor's.
- Only a `/smuggle` lands past the trains (the user's, or `/mtm`'s in smuggle mode, D76); the tollman never starts it.
- Change this skill's libraries (`reasons.md`) only in a hal2 worktree, landed by its `/mtm`, when the user asks or
  the duty `learn` hands the learnings to a foreman (D8).
