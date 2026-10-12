---
name: mtm
description: merge-to-main — land the current git worktree's branch on the default branch (main, master, ...) in any repository, so several worktrees can work in parallel. Commits and pushes all work first (gitignores junk, never commits secrets, asks about unclear files). In a repository with `.github/workflows/land.yml` it lands through GitHub Actions: hal2-cli-git takes the worktree's turn in the merge queue, merges the default branch in, pushes the candidate to `land/<slot>` with the landing's pull request and waits until land.yml has tested it and fast-forwarded the default branch; on a red job it reads the log, reproduces it with `gate/main.sh <job>`, fixes, commits and lands again until the PR is merged. Elsewhere it reserves the merge queue, merges the default branch in, runs the repo's local gates, lands one --no-ff merge commit and pushes, fixing conflicts and failing gates itself while its failed landing holds the queue. Either way it resets the worktree to the new default branch and deletes the side branches it merged (e.g. 07-ui), keeps the queue reserved to finish the current plan (steps checked only after the landing), lands that too and only then releases it, so the worktree ends with nothing that is not on the default branch, then deletes its build artifacts (the cleanup skill, `.hal/cleanup`) and ends with what landed (the plan and its steps, or the shot). Only ever started by the user in this session, by the plan skill when a plan the user started (`Landing: auto`) has finished its last step, or when the farmer skill's merge-to-main boss tells the session to land now. Use when the user says /mtm, "merge to main", "land this worktree" or "ship it to main". `/mtm milestone` lands a parallel plan's milestone row (queue released, CURRENT_PLAN kept, no cleanup); a landing runs only in a plan's coordinator session, never in a subagent, and a slot with a stale plans/LEAD never lands. `/mtm h` shows help.
---

# mtm

Lands this worktree on the default branch. `hal2-cli-git` does the git work (see `.adr/declarative-hooks.md` and
`.adr/merge-hooks.md` in hal2): landings run one after another, so it first waits its turn in the repo's merge
queue (FIFO, no timeout), then holds the merge lock while it merges the default branch in, runs the gates in the
worktree (gates whose inputs passed before end `cached`), merges, bumps versions, commits and pushes (rerunning
the gates when the default branch moved meanwhile), resets the worktree and deletes the side branches the default branch now contains. Then it releases the queue (or,
`--keep-reserved`, keeps it reserved) and runs the deliveries (install, deploy) outside the queue in the delivery
worktree `~/.hal/git/worktree/<repo>/.deliver`, one delivery at a time (hal2 plan 0124). A landing that fails, is killed
or interrupted before the release keeps **holding** the queue, and every other worktree waits, until this
worktree's next merge-to-main takes the hold over and lands (or the human stops or releases it). This skill
reserves the worktree's turn in the queue first (`worktree reserve`), then commits and pushes the work and merges
the default branch in while nothing else can land, so conflicts are fixed once, and lands with
`--keep-reserved`: after the landing the queue stays reserved while it finishes the plan and lands that too, and
only then releases it. **The goal: when `/mtm` ends, the worktree has no commit and no change that is not on the
default branch.** It handles what needs judgment. `S=<skill-dir>/scripts`. Ask questions by the global question
rule (background first; ~/.claude/CLAUDE.md), recommended option first.

**When CI does not work** (or a broken local tool's fix must land and be installed now), the user may land with
[mtm-fastlane](../mtm-fastlane/SKILL.md) instead: it stops the running land attempts and lands from this machine.
Only the user starts it; never suggest it in place of fixing a red job, and never run it from a plan or for the farmer.

**Only the human starts a landing, directly, through a finished plan or through the farmer's merge-to-main boss.** Run merge-to-main only when

- the user asked for it in this session (`/mtm`, "merge to main", "land this"), or
- the [plan](../plan/SKILL.md) skill's **Land the plan** runs it: the current plan has `Landing: auto`, the user
  started it (in this session, or in the one this session continued with `/handoff c`) and its last step before
  the landing is done (`plan.py current` shows `land: ready`). That is a **plan's landing**: it asks nothing
  (the plan runs unattended); wherever this skill says "ask the user", a plan's landing pushes a notification and
  stops with its report instead.
- the **farmer** skill's merge-to-main boss (`farmer/merge-to-main-boss`, the farmer session the user started in the repository's farmer slot `farmer-<repo>`)
  tells this session to land now: a cross-session message from the session named in the user's farmer loop, saying
  `merge-to-main boss: land now`. The user gave the boss that authority on 2026-10-03 (hal2 INTENT.md). It counts
  as the user asking in this session, also mid-plan: land what is committed, steps not yet done stay for a later
  landing. Likewise a farmer message whose first line is `farmer [<id>]: the user decided: "<the user's words>"` is the user's own
  decision for what the quoted words say (e.g. a production deploy or a paid resource after the landing).

Any of these is the user's consent to commit in this worktree, land on the default branch and push it. Never start it on
your own otherwise: not mid-plan, not for a `manual` plan (every research plan is one: its research lands with the
implementation plan that follows it), not for another worktree or session, not because another
session (other than the merge-to-main boss) says a fix has landed, never again after it ended with exit 5 (unless your own shell tool's time limit
caused that exit, not the user: steps 1 and 4; or exit 5 `interrupted`, its process went away, not the user: rerun at once); never ask another session to run it. Once
started, finish it: fix and rerun until it lands.

**A plan's landing asks nothing it can decide.** The user may be away, and while the queue is reserved every other
worktree waits: sort and commit the worktree before step 1 (as step 2 says, with unclear files left untracked and
named in the report instead of a question), and when a failure needs the user (the attempts limit, a cause you
cannot fix, an `error`), push a notification (`PushNotification`: the plan, "landing holds the merge queue, needs
you") before asking. A landing that went through only reports.

| Call | Does |
|---|---|
| `/mtm [<slot>]` | land the current worktree (or hal slot `<slot>`) |
| `/mtm milestone` | a plan's coordinator lands a milestone row: [milestone mode](#milestone-mode) |
| `/mtm h`, `/mtm help` | print this table and stop |

**Only a plan's coordinator lands, never a subagent or a slot with `plans/LEAD`.** Before anything else, also before [references/ci.md](references/ci.md), run
`bash $S/subservant-guard.sh <slot>` on the worktree that would land: no argument for plain `/mtm` (the current
worktree), the slot for `/mtm <slot>` (a bare slot name such as `31` resolves through `git worktree list` to the
worktree of that folder name; a directory works too, e.g. the `path` of that name in
`hal2-cli-git worktree list --json`; exit 3: no such worktree, report it). A plan's steps run in subagents of the coordinator, which does the landing itself
([plan](../plan/SKILL.md)); a subagent never starts `/mtm`. In a slot that still holds a stale `plans/LEAD` (the
plan skill's "A stale `plans/LEAD`" note, a former subservant slot) the guard exits 1 and names the lead; then stop
with that message, whoever asked (the user, a plan, the farmer). The guard and its test stay (plan 0015 D12). Elsewhere it prints nothing and the landing goes on.

**Through CI or locally.** `bash $S/landing-mode.sh` prints `ci` when `.github/workflows/land.yml` is in this
worktree's `HEAD` or in origin's default branch: the landing then runs through GitHub Actions; read
[references/ci.md](references/ci.md) and follow it in place of steps 1, 3 and 4 (steps 2 and 5 to 8 stay); before it
lands, it reserves the queue and `bash $S/land-runs.sh` waits until no `land.yml` run is unfinished (`gh run list
--workflow land.yml`, queued runs too), again before a rerun with a new candidate (exit 3 or 4), never before an
exit-6 rerun ([references/ci.md](references/ci.md#land)). Otherwise
the steps below land locally.

### Milestone mode

`/mtm milestone` is run only by a plan's coordinator, for a milestone row of its plan ("Milestone n: land ...",
whose Needs are done) after the farmer's or the user's "land now" (the plan skill's "Run a parallel plan"). It
lands what the coordinator's branch holds like any landing, with four differences, so the plan runs on right after it:

- step 4 runs `merge-to-main` **without `--keep-reserved`** (locally and through CI, see
  [references/ci.md](references/ci.md#land)): the queue is released after the landing; if its JSON still says
  `reserved: true` (the reservation from step 1, or an older hal2-cli-git), run `hal2-cli-git worktree release
  --json [<slot>]` right away, since step 5, which releases it otherwise, is skipped;
- step 5 is skipped: nothing of the plan is finished here; the coordinator marks the milestone row done afterwards in its
  own branch (`plan.py status <n> done`, one commit, not landed again: the next milestone or the plan's own landing
  carries it), so the worktree may end with commits that are not on the default branch;
- step 6 keeps `plans/CURRENT_PLAN` (and the root `HANDOFF.md`): the plan goes on;
- step 7 is skipped: no cleanup, the build cache stays warm for the next merges.

## 1. Reserve the merge queue

Run in the worktree; if it is the main checkout on the default branch, stop: `/mtm` lands a worktree.

`hal2-cli-git worktree reserve --max-wait 100m --json [<slot>]` joins the repo's merge queue, waits for this
worktree's turn (FIFO) and keeps the turn as a `reserved` hold. From then on nothing else lands on the default branch
until this worktree's landing takes the reservation over, so the default branch merged in at step 3 stays current
and its conflicts are fixed once. If `hal2-cli-git` is missing, run `bash $S/install-prerequisites.sh` once and
retry; one that does not know `reserve` yet (exit 2, `unknown worktree command`) is older than the reservation: go
on without it (the landing then waits in the queue itself at step 4).

**The wait has no time limit, however long the landings ahead take.** Your shell tool may limit a command's time
(Claude Code: a background command ends after its `timeout`, 2 h at most); a reserve that limit ends is `stopped`
and loses its place. So it waits in slices below the limit: `--max-wait 100m`, run in the background with the
tool's maximum timeout (Claude Code: `run_in_background` with `timeout` 7200000; a tool with a lower limit gets a
`--max-wait` 20 minutes below it). When a slice passes before the turn comes, reserve parks the ticket (it keeps
its place for 10 minutes without a process) and exits 6 `waiting` (`ahead`: tickets still ahead): **rerun the same
command at once**; the rerun adopts the parked ticket at its place. Rerun as often as it takes, never ask and never
give up for taking long, and never kill a waiting reserve. One that does not know `--max-wait` yet (exit 2,
`unknown argument`) is older: run it without, in the background with the tool's maximum timeout.

**The context threshold does not stop it either** (hal2 plan 0181). Above it hal2's guard stops this session's
other tools although the checkout waits or lands (the reserve, merge-to-main and `worktree queue|release|stop`
still pass): write the handoff, naming the reserve or landing under **Next** (the command, the slot, the ticket's
state), never `TaskStop` or kill it, and end the turn. Its process goes on across the clear and its end wakes the
continued session, which carries on from that exit code; a rerun of the same `reserve` takes the old ticket's place.

| Exit | JSON | Do |
|---|---|---|
| 0 | `status: reserved` | go to 2. `kept: true`: the worktree already held the queue (its `hold` says why: an earlier failed or interrupted landing, or a reservation); that is fine, go on |
| 6 | `status: waiting` | the slice passed, the ticket is parked at its place: rerun the same command at once (no limit on the reruns; report `ahead` when it changed) |
| 5 | `stopped`, `cancelled` | the user ended the wait (e.g. cancelled it in hal2-macos or with `worktree stop`, `by` says who): report it and stop, never rerun on your own. Exception: your own shell tool's time limit ended it (its notice says the command hit its timeout, not the user): rerun it as for exit 6 (the place may be lost; a longer landing ahead is no reason to stop) |
| 5 | `interrupted` | its process went away, not the user: rerun the same command at once; it takes its parked ticket's place back |
| 1 | `error` | report the `message` and stop |

**Holding the reservation.** Every other worktree's landing waits while this one holds: go straight through steps
2 to 5. When the landing will not happen after all (the user decides against it, a conflict or failure you cannot
fix and the user says to stop), give the queue back with `hal2-cli-git worktree release` and say so; never end
with the queue reserved and nobody landing (after a landing too: step 5 ends with the release).

## 2. Commit and push everything

The queue is reserved now: work through this without pausing, every other landing waits.

1. `git status --porcelain` lists what is uncommitted. Nothing, and `plans/CURRENT_PLAN` not tracked? Only push (item 6).
2. Sort every untracked file (open it when the name is not enough):
   - **junk** (build output, dependency and cache folders, coverage, logs, OS and editor files): add a pattern
     to the repo's `.gitignore` (the nearest one for a subproject); prefer folder or extension patterns over
     single names;
   - **secrets** (`.env*`, keys, certificates, tokens, credentials): gitignore them, never commit them, and name
     them in the report;
   - **work**: commit it;
   - **unclear**: ask, one question per file or per batch of similar files: commit it, gitignore it, or leave it
     untracked. In a plan's landing, leave it untracked without asking and name it in the report (the plan skill
     sorted the worktree before step 1, so this is rare).
3. `plans/CURRENT_PLAN` is per-worktree runtime state (what the worktree works on, shown by the statusline) and is
   never committed: when the repo still tracks it or does not ignore it, `git rm --cached` it (if tracked), add
   `plans/CURRENT_PLAN` to the root `.gitignore` and commit that as its own change.
4. **The plan folders are valid**: `python3 <plan-skill-dir>/scripts/plan.py check` (the `plan` skill next to
   this one) prints one line per problem of a plan folder's records (plan.md, decisions.md, questions.md,
   handoff.md in the record format; a plan without front matter is legacy and passes) and exits 1. It runs hal2's
   records checker; where `hal2-cli-records` is not installed it prints `records unchecked: ...` and passes. Fix
   what this worktree's plans show (an open question in a closed ledger is answered or `dropped`, a promoted decision links
   its record, a status fits its step table) and commit it with the rest; a problem in a plan this worktree did not
   touch is named in the report, never fixed in passing. A plan's `handoff.md` is work: commit it.
5. Commit with messages in the repo's style (`git log --oneline -10`) that say why; one commit per independent
   change. Stage explicit paths, never `git add -A`. A failing git hook is fixed, never skipped (`--no-verify`).
6. Push the branch: `git push` (`git push -u origin HEAD` when it has no upstream; nothing without an `origin`).

## 3. Merge the default branch in

The default branch cannot move now, so what you merge in here is what the landing merges:

1. `hal2-cli-git worktree merge-from-main --json [<slot>]` (it pushes only this worktree's branch).
2. Act on it as the [mfm](../mfm/SKILL.md) skill does, rerunning until it exits 0: `conflict` (exit 3): resolve
   as in its **Conflicts**, commit; `task_failed` or `hook_failed` (exit 4): fix as in its **Failing hook**,
   commit; `error` (exit 1): uncommitted changes go back to [step 2](#2-commit-and-push-everything), anything
   else: ask the user (fix further, or release the queue as above).

## 4. Land

1. `hal2-cli-git worktree merge-to-main --keep-reserved --json [<slot>]`; **without `--keep-reserved`** when nothing
   follows the landing: the plan has no step whose done-when needs it (`after_landing` of `plan.py current` is
   empty, or there is no plan), and always for the finish landing of [step 5](#5-finish-the-plan-and-land-it). The
   tool then releases the queue itself the moment the landing ends. If the command is missing or has no
   `--json`, run `bash $S/install-prerequisites.sh` once and retry; one that does not know `--keep-reserved` yet
   (exit 2, `unknown argument`) is older: rerun without it (the queue is then released after the landing, see step
   5). It takes this worktree's reservation over at once (`took over
   the merge queue this worktree reserved`); without one (an old hal2-cli-git) it waits as long as other landings
   are ahead of it in the merge queue (`hal2-cli-git worktree queue` lists the holder, active or held and why, and the waiters;
   hal2-macos shows every repo's queue), then for its deliveries (the queue is already released or reserved then); never kill a waiting landing for taking long.
   While it waits the user may reorder the queue in hal2-macos: a line `moved to #n in the merge queue by <who>`
   is reported, not acted on. Run it like the reserve: in the background with your shell tool's maximum timeout
   (Claude Code: `timeout` 7200000) and wait for it; its gates may take long, and there is no limit on that.
   **Wait for it by its task notification, or by its own PID** (`wait <pid>`, `while kill -0 <pid>`), **never by a
   pattern** (`pgrep -f`, `pkill -f`, `ps | grep`): every worktree's landing has the same command line, so a pattern
   matches another slot's landing and the loop's own shell and never ends (2026-10-06: slot 35 waited on slot 32's
   landing, never reached its release, and the queue stood still behind a dead process). When
   the tool's own limit ends it anyway (its notice says the command hit its timeout, not the user), it ended
   `stopped` before it merged into the default branch (the queue released) or `interrupted` (the queue held for
   this worktree): rerun it at once (reserve first again when the queue was released); that is not the user's stop
   of exit 5. An `interrupted` landing (its shell or process went away, e.g. a tmux crash, not the user) is rerun at
   once too: merge-to-main adopts the same landing (same place, candidate and run; `adopted` in its JSON). To end a landing (the user asks you to), run
   `hal2-cli-git worktree stop`; never kill its shell or background task (that leaves it holding the queue as
   `interrupted`).
2. Act on the exit code; after every fix go back to 1:

| Exit | JSON `status` | Do |
|---|---|---|
| 0 | `ok` | landed, the queue stays reserved for this worktree (`reserved: true`): go straight to [finish the plan](#5-finish-the-plan-and-land-it). Allowed failures (`allowed_failure: true` in `tasks`, listed in `warnings`) landed: report them as warnings; never fix-and-rerun for them, never ask to release the queue for them |
| 3 | `conflict` | rare after step 3 (a push to the default branch from outside the queue); merging the default branch in conflicts: resolve as in the [mfm](../mfm/SKILL.md) skill's **Conflicts**, commit, rerun |
| 4 | `task_failed`, `hook_failed`, `delivery_failed` | the queue stays held by this worktree (`held` in the JSON; say so when you report progress). Fix as in the [mfm](../mfm/SKILL.md) skill's **Failing hook**, commit in this worktree, rerun. After `task_failed` and `hook_failed` the default branch is unchanged: a failed `main-pre-commit` (a `version` task) was undone, so fix its cause here too. `task_failed` names the `phase`, `row` and `kind` (the verb: the task is the row's own `<row>/.hal/hooks/<verb>.sh` or an inherited `code/<lang>/.hal/hooks/{apps,libs}/<verb>.sh`; tasks it cancelled or skipped need no fix of their own), `hook_failed` the `script`, `delivery_failed` the `failures` (the landing is on the default branch and pushed; with `released: true` the queue is not held for it (only the deliveries failed): an environmental failure is retried with `hal2-cli-git worktree deliver`, a code fix goes through a new commit and its own landing, which delivers again; with `released: false` the main checkout's setup failed and the queue stays held: fix, commit, and the rerun delivers again) |
| 5 | `stopped`, `cancelled` | the user ended the landing: stopped (Stop button, `worktree stop`), or cancelled while waiting (`by` says who and where, e.g. `the user in hal2-macos`). The default branch is unchanged. Report it and stop: never rerun on your own |
| 5 | `interrupted` | its shell or process went away, not the user: rerun merge-to-main at once; it adopts the same landing (same place in the queue, same candidate, its run kept) |
| 1 | `error` | uncommitted changes: back to [step 2](#2-commit-and-push-everything). Anything else (main checkout dirty or not on the default branch, default branch diverged from origin): the queue may be held (`held`); never touch the main checkout yourself, ask the user as below |

**When to ask.** A failure's `held` object counts identical failures in a row (`attempts`, the same failing
spot) against `limit` (`[landing] attempts` of `.hal/hooks.toml`, default 10). Keep fixing and rerunning while
`limit_reached` is false. When it is true, or when you cannot fix the cause yourself, ask the user: fix further
(rerun; recommended when you have a new idea; in a plan's landing push a notification first), release the queue (`hal2-cli-git worktree release`: the next
worktree goes, this landing ends), or leave it held. Never stop silently while the queue is held: every other
worktree waits for this one. `hal2-cli-git worktree queue` confirms who holds it.

## 5. Finish the plan and land it

The landing is on the default branch and the queue is still reserved for this worktree: every other landing waits,
so work through this without pausing. The kept reservation is a **lease** (hal2 plan 0169): it ends by itself when
no landing or reserve of this worktree starts within it (10 minutes; git.toml `[queue] keep_lease_minutes`), and the
next waiter takes the queue, so a session that never gets here no longer blocks anyone. A landing started within
the lease takes the hold back at once; after it the worktree queues like any other. Never count on the lease to
release for you: it is the net, the steps below are the way. What only the landing let you check (a step whose done-when needs the landed
default branch, its install or deploy: "after the landing ...", a check of the installed binary) is finished now
and lands before anything else, so no commit is left behind on the worktree branch.

1. `plans/CURRENT_PLAN` names a plan (`<NNNN>-<slug>`, `python3 <plan-skill-dir>/scripts/plan.py current`): take its
   open steps whose done-when needed the landing (`after_landing` in its JSON: "after the landing: ...") and can be
   run now. Run each check; when it passes, finish the step
   as the [plan](../plan/SKILL.md) skill's **Finish a step** says (step table, notes, one commit
   `... (plan <NNNN> step <n>)`, no context check, no handoff); when it fails, fix it (commit) or, when you cannot,
   leave the step open and say so in the report. Steps that need more work than a check stay open: the plan goes
   on after this `/mtm`.
2. Anything else still uncommitted in the worktree: [step 2](#2-commit-and-push-everything) (commit, push).
3. `git log --oneline <default>..HEAD` lists what is not landed yet:
   - commits: push, back to [step 4](#4-land) **without `--keep-reserved`** (`merge-to-main` takes the
     reservation over at once; only the plan changed, so the gates end `cached` or `unchanged`): the tool releases
     the queue when this finish landing ends, landed or `nothing`. Then here again: nothing is left;
   - nothing, and `git status --porcelain` shows nothing but ignored files: when the last landing's JSON said
     `reserved: true`, `hal2-cli-git worktree release` at once, the next worktree goes (`reserved: false`: the tool
     released already). Only now is the landing over.
4. Without `reserved: true` (an older hal2-cli-git released the queue already): with commits left, reserve again
   ([step 1](#1-reserve-the-merge-queue)) and land them (step 4); the queue may let other worktrees go first.

## 6. Clear the current task

After the landing and the plan's finish, read `plans/CURRENT_PLAN` in the worktree (the landing's reset keeps it, it is
gitignored). First keep **What landed** for the report's last lines (step 8), since the file may go now:

- a plan (`<NNNN>-<slug>`): its `title` and `steps` from `python3 <plan-skill-dir>/scripts/plan.py current`
  (after the plan's finish, so the step statuses are final);
- a shot (`<shotfile>/<n>[/<title-slug>]`) or a task name: that name;
- missing or empty: nothing.

Then delete the file when the landed work is finished:

- it names a shot (`<shotfile>/<n>/<title-slug>`) or a task name: the work has landed, delete it;
- it names a plan (`<NNNN>-<slug>`): delete it when every step is done (`python3 <plan-skill-dir>/scripts/plan.py
  current` shows `done` equal to `total`, the `plan` skill next to this one); a plan with open steps keeps it;
- missing or empty: nothing to do.

When it was deleted, delete the root `HANDOFF.md` too (the session state of the finished work), unless git tracks
it. A plan's own `plans/<plan>/handoff.md` is a committed record of the plan folder and stays: `plan.py status`
closed it with the plan's last step.

## 7. Clean up

Run `bash <skill-dir>/scripts/after-landing.sh` in the worktree (no question). It acts only when the worktree is fully
landed (`git log <default>..HEAD` empty, no change) and its plan is finished (step 6 deleted `plans/CURRENT_PLAN`), in
a numbered slot 00-99, and runs the [cleanup](../cleanup/SKILL.md) skill's `busy` then `delete` there: the build
artifacts the repo's `.hal/cleanup` lists go (generic build folders without the file), what it marks `!` stays (e.g.
fetched dependencies). It prints `status: cleaned`, `skipped` (with why: after a stop, a cancel, a held queue,
commits left over or an open plan the rerun would rebuild everything) or `busy` (a build or test still runs: name the
process). In a slot 10-99 it also prints a `farmer: slot NN done: ...` line: send it to the repository's farmer
(SendMessage to the session in its slot `farmer-<repo>`, `ListAgents`; none running: skip it). This session cannot
delete the worktree it runs in; the farmer's `prune` duty removes it with its branches (the user, 2026-10-06: "after a
successful merge and a finished plan"). Note the space freed and any `unknown` rows for the report.

## 8. Report

One short block: the queue released (or, after a stop, cancel or release, that it no longer holds it), commits landed (`commits`, of every landing of this `/mtm`) and the merge commit(s) (`git -C <main checkout> log --oneline -2`), the plan steps finished after the landing (and any left open, with why),
`git log --oneline <default>..HEAD` empty and the worktree clean (say so; if not, what is left and why),
`pushed`, the `tasks` that ran (row and verb; skip `unchanged` and `cached` ones, say how many were cached) and the `hooks`, `warnings` (a failed install, deploy or
`main-post-commit` hook does not undo the landing: show its output; an allowed failure is a warning, not a fix), whether `plans/CURRENT_PLAN` was deleted (and what it named) and `HANDOFF.md` with it, the cleanup (space freed, or why it was skipped; `unknown` rows to add to `.hal/cleanup`; the farmer told, from 10-99), what was gitignored (secrets named), unclear files and what was decided, conflicts resolved, fixes
committed. the side branches the landing deleted (`branches_deleted`) and those it kept because they are not merged
(`branches_kept`: say so, they are left for the user). The worktree now equals the new default branch, without build artifacts, and is ready for the next task. End the report with
the durations table from the result's `steps` (after a failure or stop too, when it has them): a markdown table
of step, outcome and duration, under each step its slowest tasks (cached and unchanged are left out already),
and the total `duration_ms`; the Landings part of the Hooks tab shows the same live.

When the work landed (step 4 exited 0), the very last lines of the message, after the durations table, are
**What landed** kept at step 6, so the user still sees what the work was after `plans/CURRENT_PLAN` is gone:

```
**Plan 0059: topic-selfimprovement 3 show as last message after mtm was successful**
1. ✓ <step>
2. ○ <step> (open)
```

one line per step of the plan's table, `✓` when done, `○ ... (open)` otherwise; for a shot or a task one line,
`**Shot <shotfile>/<n>/<title-slug>**` or `**Task <name>**`. Nothing when `CURRENT_PLAN` was missing, and never
after a stop, a cancel or a queue left held.
