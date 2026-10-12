# Landing through CI

A repository whose default branch (or this worktree's `HEAD`) has `.github/workflows/land.yml` lands through
GitHub Actions (hal2's plan 0131 and its decision record
[landings-on-github-actions](https://github.com/divramod/hal2/blob/main/.adr/landings-on-github-actions.md)). Nothing is tested on this machine:
`hal2-cli-git worktree merge-to-main` takes the worktree's turn in the merge queue, merges the default branch in,
builds the `--no-ff` candidate, pushes the branch and `land/<slot>`, opens or updates the landing's pull request
(`land/<slot>` → the default branch) and waits until `land.yml` has tested the candidate: green, its `merge` job
fast-forwards the default branch to the candidate (the PR shows merged); red, the queue stays held for this worktree
until its fix lands (the user, 2026-10-06: "run landing until everything is fixed and merged and then release"). There
is no attempts counter, and `reserve` only holds the queue while `land-runs.sh` waits (below): SKILL.md's steps 2 and 5 to 8 apply as they are, this page replaces steps
1, 3 and 4.

## Land

Run in the worktree (SKILL.md step 2 first: everything committed and pushed):

**Reserve, then wait until no land run is unfinished**, before the first `merge-to-main` below and before a rerun
after exit 3 or 4 (a new candidate), never before an exit-6 rerun (that one waits for its own run or for the queue
ahead; a wait over 10 minutes loses its parked ticket, so it reruns at once):

1. `hal2-cli-git worktree reserve --max-wait 100m --json [<slot>]`, in the background like the landing (exit 6:
   rerun at once; after exit 3 or 4 the queue is still held for this worktree: skip this). The hold keeps any other
   landing from starting while you wait; `merge-to-main` takes it over.
2. `bash $S/land-runs.sh`, in the background too. It runs `gh run list --workflow land.yml --limit 10 --json
   databaseId,headBranch,status --jq '.[] | select(.status != "completed")'` every minute and exits 0 once that
   prints nothing; while it lists a run, an earlier landing still runs or ships (`queued` counts too: a run whose
   ship job waits for a runner is queued), so never push meanwhile. Exit 7: a run stayed unfinished for an hour
   (`--max-wait`; a parked runner, a pending approval): tell the farmer and wait for it, the hold stays. Exit 1: gh
   failed, nothing is known: check again. hal2-cli-git's own check misses queued runs (the user, 2026-10-06: "the
   mtm skill should have a mention of the command on how to check in the gh workflow list, if he can start now or
   needs to wait").

Then land:

`hal2-cli-git worktree merge-to-main --max-wait 100m --keep-reserved --json [<slot>]`, in the background with the
shell tool's maximum timeout (Claude Code: `run_in_background`, `timeout` 7200000; a lower limit gets a
`--max-wait` 20 minutes below it). It needs `gh` logged in to GitHub (`gh auth status`). Wait for it by its task
notification or its own PID, never by a `pgrep` pattern (SKILL.md step 4 says why).

**`--keep-reserved` only when something follows**: the plan has steps to finish after the landing (`after_landing`
of `plan.py current`). Without such steps, and for the finish landing of SKILL.md step 5, run the command **without
it**: the tool releases the queue the moment the landing ends (after its run has shipped). The finish landing
starts within the kept reservation's lease (10 minutes, git.toml `[queue] keep_lease_minutes`), takes the hold back
at once and needs no `reserve` or `land-runs.sh` before it; a kept reservation nobody follows up ends with its
lease and the next waiter lands (hal2 plan 0169).

**`/mtm milestone`** (SKILL.md's [milestone mode](../SKILL.md#milestone-mode)): run the same command **without
`--keep-reserved`**, and on exit 0 do not go to step 5 (it is skipped): if the JSON still says `reserved: true`, run
`hal2-cli-git worktree release --json [<slot>]` at once, so the queue is free for the next landing; then go on with
SKILL.md step 6 as milestone mode says.

| Exit | JSON `status` | Do |
|---|---|---|
| 0 | `landed` | the default branch is the candidate (`commit`), the PR (`pull_request`) merged; `retests` counts how often the default branch moved under it. `reserved: true` (kept, a lease): go to SKILL.md [step 5](../SKILL.md#5-finish-the-plan-and-land-it) at once; `reserved: false`: the queue is released, step 5 only checks that nothing is left. Report `warnings` (e.g. the main checkout could not be pulled) |
| 0 | `nothing` | the branch has nothing the default branch lacks; the queue is released, with or without `--keep-reserved` (`reserved: false`), and a worktree that held no ticket never entered the queue: step 5 |
| 6 | `waiting`, `testing`, `shipping` | the slice passed: in the queue (`ahead`), while the candidate is tested (`candidate`, `run`) or while a run ships (`runs`; with `commit`: this landing has landed and waits for its run's `ship / ...` jobs before it releases the queue: strictly one land run at a time). The place and the candidate are kept: **rerun the same command at once**, as often as it takes, without reserve or `land-runs.sh` before it |
| 4 | `gate_failed` | the candidate is red; the queue stays held for this worktree (`released: false`): [fix it](#red) and run again at once, the rerun adopts the hold at the head of the queue. Never release it yourself while you can fix: it is released when the branch lands. An older hal2-cli-git answers `released: true`: rerun at once all the same (it queues again) |
| 3 | `conflict` | merging the default branch in conflicts (`files`): resolve as the [mfm](../../mfm/SKILL.md) skill's **Conflicts** says, commit, rerun (the queue stays held for this worktree meanwhile: go straight on) |
| 5 | `stopped`, `cancelled` | the user ended it: report and stop, never rerun on your own (your own shell's time limit is no user stop: rerun) |
| 5 | `interrupted` | its process went away, not the user: rerun at once; it adopts the same landing and its run (never cancel the run) |
| 1 | `error` | uncommitted changes: SKILL.md step 2. Anything else: report the `message`; the queue may be held for this worktree, so ask the user (fix, or `hal2-cli-git worktree release`) |

**Watch the run every 5 minutes while it is tested** (the user, 2026-10-06). Once the candidate's run is known (exit
6 names `run`; else `hal2-cli-git worktree landings --json`), look at its jobs every 5 minutes
(`gh run view <run> --json jobs`) for as long as the landing waits. A job that concluded `failure` or `timed_out`
while others still run: start on [Red](#red) at once (read its log, reproduce, fix, commit, push) instead of waiting
for the landing to end; the landing keeps its place meanwhile, and when it ends with `gate_failed` the fix is ready
for the next [Land](#land) at once. Never cancel the run: the whole workflow finishes, so every red job of it is
known and fixed in that one next landing (the user, 2026-10-06: "that way we save time"). A red outside the code (runner offline, full disk, network): tell the farmer
right away.

## Red

`gate_failed` lists the `red` jobs, each with its `url` (the job's log) and `reproduce`, the command that runs the
same job in this checkout for only what this branch changed (`code/bash/scripts/gate/main.sh <job> --branch
origin/main`; hal2 plan 0157). Never drop the `--branch`: without a range the job tests the whole workspace, which is
the runner's work, not the Mac's:

1. Read why: `gh run view <run id> --log-failed` (the run is the JSON's `run`), or the job's `url`.
2. Reproduce locally with `reproduce` (it runs the same script as CI; a macOS-only job needs this Mac's Xcode, a
   stack job Docker).
3. Fix the cause in this worktree (the code, a test; the gate script or the workflow only when they are wrong, and
   say so) and run `reproduce` again until the job is green locally. **Nothing goes up before that** (the user,
   2026-10-08: "the failing jobs should be fixed and tested locally, before reuploading them"; hal2's ADR
   `red-ci-fixed-locally-first`). Then commit with a real message, push, and run [Land](#land) again. Only the red jobs and what the fix
   changed run again: jobs and packages whose content key was green before are skipped (green markers).

A job red for a reason outside the code (the runner offline, a network failure, a full disk, the runner's image) is
no code fix and cannot be seen green locally: fix the environment (a runner image is built first:
`code/bash/scripts/ci-runner-linux/main.sh image-build`), then check **that one job alone** on CI (`gh workflow run
land.yml --ref <branch> -f ref=<sha> -f jobs=<job>`) and land only after it is green. Never rerun a whole landing on
hope; when the job alone stays red, report it and ask the user (the farmer's ci duty may already be on it). Keep going until the PR is merged: every fix is a new candidate, and the queue stays held for this worktree
meanwhile, so every other landing waits on you: fix and run again at once.

## After the landing

land.yml's `merge` pushes the version tags; the same run's `ship / ...` jobs (ship.yml, called after `merge`) promote
the staged Linux bundle, install the landed apps on the Mac host (cargo installs, hal2-api/hal2-daemon, the apps'
install) and pull the main checkout; the landing pulls it too when ship has not yet. hal2-cli-git decides the landing
once `merge` completed: a `ship / ...` job never delays or reddens it. In the report, name the PR and the land run
(its `ship / publish` and `ship / deliver` state), not hook tasks or durations of local steps.
