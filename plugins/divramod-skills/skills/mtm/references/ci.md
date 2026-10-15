# Landing through CI

A repository whose default branch (or this worktree's `HEAD`) has `.github/workflows/dev-merge-to-main.yml` (or
`merge-to-main.yml`, its name before hal2 plan 0349, or `land.yml`, before plan 0263) lands through
GitHub Actions (hal2's plan 0131 and its decision record
[landings-on-github-actions](https://github.com/divramod/hal2/blob/main/.adr/landings-on-github-actions.md)). Nothing is tested on this machine:
`hal2-cli-git worktree merge-to-main` takes the worktree's turn in the merge queue, merges the default branch in,
builds the `--no-ff` candidate, pushes the branch and `land/<slot>`, opens or updates the landing's pull request
(`land/<slot>` → the default branch) and waits until that workflow has tested the candidate: green, its `merge` job
fast-forwards the default branch to the candidate (the PR shows merged); red, the queue stays held for this worktree
until its fix lands (the user, 2026-10-06: "run landing until everything is fixed and merged and then release"). There
is no attempts counter, and `reserve` only holds the queue while `land-runs.sh` waits (below): SKILL.md's steps 2 and 5 to 8 apply as they are, this page replaces steps
1, 3 and 4.

## Land

Run in the worktree (SKILL.md step 2 first: everything committed and pushed):

**Reserve, then wait until no land run is unfinished**, before the first `merge-to-main` below and before a rerun
after exit 3 or 4 (a new candidate), never before an exit-6 rerun (that one waits for its own run or for the queue
ahead; a wait over 10 minutes loses its parked ticket, so it reruns at once):

0. `bash $S/check-landing-cli.sh` first, before anything is reserved. Exit 8: the repository's workflow is
   `dev-merge-to-main.yml` or `merge-to-main.yml` and the installed hal2-cli-git does not know that name (its
   `--help` does not name it): it would find no workflow it knows and land this worktree **as a plain merge,
   untested**. Nothing lands: stop and tell the
   user what the script printed (the binary, the install command); a plan's landing pushes a notification first.
   Exit 2: a missing tool, `bash $S/install-prerequisites.sh`. Exit 0 prints nothing: go on. It checks the
   worktree it runs in; for another one pass its directory (`bash $S/check-landing-cli.sh <dir>`), here and below.
1. `hal2-cli-git worktree reserve --max-wait 100m --json [<slot>]`, in the background like the landing (exit 6:
   rerun at once; after exit 3 or 4 the queue is still held for this worktree: skip this). The hold keeps any other
   landing from starting while you wait; `merge-to-main` takes it over.
2. `bash $S/land-runs.sh`, in the background too. It runs `gh run list --workflow <file> --limit 10 --json
   databaseId,headBranch,status --jq '.[] | select(.status != "completed")'` for `dev-merge-to-main.yml`,
   `merge-to-main.yml` and `land.yml` every minute (a run started before a rename finishes under the old name; a
   file GitHub does not know has no runs) and exits 0 once none
   prints anything; while it lists a run, an earlier landing still runs or ships (`queued` counts too: a run whose
   ship job waits for a runner is queued), so never push meanwhile. Exit 7: a run stayed unfinished for an hour
   (`--max-wait`; a parked runner, a pending approval): tell the farmer and wait for it, the hold stays. Exit 1: gh
   failed, nothing is known: check again. hal2-cli-git's own check misses queued runs (the user, 2026-10-06: "the
   mtm skill should have a mention of the command on how to check in the gh workflow list, if he can start now or
   needs to wait").

Then land:

`bash $S/check-landing-cli.sh && hal2-cli-git worktree merge-to-main --max-wait 100m --keep-reserved --json [<slot>]`,
in the background with the
shell tool's maximum timeout (Claude Code: `run_in_background`, `timeout` 7200000; a lower limit gets a
`--max-wait` 20 minutes below it). It needs `gh` logged in to GitHub (`gh auth status`). Wait for it by its task
notification or its own PID, never by a `pgrep` pattern (SKILL.md step 4 says why).

**The guard is part of the command**, on every run of it, an exit-6 rerun too: hal2-cli-git decides anew at each
start, from this worktree's `HEAD` and origin's default branch, whether the repository lands through CI, and both
may have got the renamed workflow since step 0 (the default branch merged in, the rename landed meanwhile). The
guard takes no time and prints nothing when it passes.

**`--keep-reserved` only when something follows**: the plan has steps to finish after the landing (`after_landing`
of `plan.py current`). Without such steps, and for the finish landing of SKILL.md step 5, run the command **without
it**: the tool releases the queue the moment the landing ends (after its run has shipped). The finish landing
starts within the kept reservation's lease (10 minutes, longer while the session that started the landing lives, at most 60: git.toml
`[queue] keep_lease_minutes`, `keep_lease_max_minutes`), takes the hold back
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
| 6 | `paused` | a fastlane of another worktree (`paused_by`: its slot, the user's `/mtm-fastlane`) paused this landing in place; it waits by itself and resumes when the fastlane releases: **rerun the same command at once**, as for `waiting`, and say in one line that it was paused. A run the pause cancelled is no red and needs no fix |
| 4 | `gate_failed` | the candidate is red; the queue stays held for this worktree (`released: false`): [fix it](#red) and run again at once, the rerun adopts the hold at the head of the queue. Never release it yourself while you can fix: it is released when the branch lands. An older hal2-cli-git answers `released: true`: rerun at once all the same (it queues again) |
| 3 | `conflict` | merging the default branch in conflicts (`files`): resolve as the [mfm](../../mfm/SKILL.md) skill's **Conflicts** says, commit, rerun (the queue stays held for this worktree meanwhile: go straight on) |
| 5 | `stopped`, `cancelled` | the user ended it: report and stop, never rerun on your own (your own shell's time limit is no user stop: rerun) |
| 5 | `interrupted` | its process went away, not the user: rerun at once; it adopts the same landing and its run (never cancel the run) |
| 1 | `error` | uncommitted changes: SKILL.md step 2. Anything else: report the `message`; the queue may be held for this worktree, so ask the user (fix, or `hal2-cli-git worktree release`) |
| 8 | none (`check-landing-cli.sh: nothing was landed ...`) | the guard stopped the command before hal2-cli-git ran: the installed one does not know `dev-merge-to-main.yml` or `merge-to-main.yml` (step 0 above). Never run `merge-to-main` without the guard to get past it. This landing cannot go on until the CLI is installed: `hal2-cli-git worktree release --json [<slot>]` when the queue is held or reserved for this worktree (`hal2-cli-git worktree queue --json`), then stop and tell the user what the script printed |

**Watch the run every 5 minutes while it is tested** (the user, 2026-10-06). Once the candidate's run is known (exit
6 names `run`; else `hal2-cli-git worktree landings --json`), look at its jobs every 5 minutes
(`gh run view <run> --json jobs`) for as long as the landing waits. A red outside the code (runner offline, full
disk, network): tell the farmer right away.

**A workflow with fail-fast** (the lanes' jobs have the step `[NN] fail fast: stop the run`; hal2 plan 0263, the user,
2026-10-12: "when one job fails. the whole pipeline fails instantly"): the first job the `gate` job needs that fails
or hits its time limit stops the run itself (a job that failed ends `failure`, red in the graph, and its lane's stop
job `fail-fast-<lane>` cancels the run seconds after it; plan 0319, the user, 2026-10-14: "i want to visually see in
red, which job failed"; a job at its time limit asks from inside and stays `cancelled`), and the landing returns `gate_failed` **at once** with that job in
`red`, without waiting for the run's other jobs. Nothing to start early, and **never cancel the run yourself** (`gh
run cancel`): a second cancel request seems to end the run's last jobs, which park the machines, unrun. Go to
[Red](#red) when it returns. One landing names one cause; a second red job shows in the next landing. A red monitor,
cleanup or Windows job has no such step and stops nothing.

**A workflow without it**: a job that concluded `failure` or `timed_out` while others still run: start on
[Red](#red) at once (read its log, reproduce, fix, commit, push) instead of waiting for the landing to end; the landing
keeps its place meanwhile, and when it ends with `gate_failed` the fix is ready for the next [Land](#land) at once.
Never cancel the run: the whole workflow finishes, so every red job of it is known and fixed in that one next landing
(the user, 2026-10-06: "that way we save time").

**Work while it is tested** (the user, 2026-10-12: "you should always trigger work, which can be done while you are
waiting for a pipeline run to finish"). A land run takes an hour and more: right after the landing started, do what
the plan skill's "A wait is never idle" says (prepare the steps that wait for the landing, move idle foremen, merge
nothing into the landing's branch), and only wait when nothing is left, saying why.

## Red

`gate_failed` lists the `red` jobs, each with its `url` (the job's log) and `reproduce`, the command that runs the
same job in this checkout for only what this branch changed (`code/bash/scripts/gate/main.sh <job> --branch
origin/main`; hal2 plan 0157). Never drop the `--branch`: without a range the job tests the whole workspace, which is
the runner's work, not the Mac's. `stopped` names the jobs that only stopped because of them (cancelled after the
failure, or still running when a fail-fast workflow's first failed job decided the landing): no cause, nothing to
reproduce or fix, they run again in the next landing. A red job with `conclusion: timed_out` hit its time limit: its
log shows what hung. On GitHub the run of a fail-fast red landing reads `cancelled`; the job that failed reads `failure` (red), the jobs
cut with the run read `cancelled` (grey), and so does a job that hit its time limit (`gate`'s summary names it red):
trust `red`, and do not rerun the run, fix the job:

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
dev-merge-to-main.yml --ref <branch> -f ref=<sha> -f jobs=<job>`; `merge-to-main.yml` or `land.yml` where the
repository still has an older name) and land only after it is green. Never rerun a whole landing on
hope; when the job alone stays red, report it and ask the user (the farmer's ci duty may already be on it). Keep going until the PR is merged: every fix is a new candidate, and the queue stays held for this worktree
meanwhile, so every other landing waits on you: fix and run again at once.

## After the landing

The workflow's `merge` pushes the version tags; the same run's delivery and publish jobs (after `merge`) promote
the staged Linux bundle, install the landed apps on the Mac host (cargo installs, hal2-api/hal2-daemon, the apps'
install) and pull the main checkout; the landing pulls it too when ship has not yet. hal2-cli-git decides the landing
once `merge` completed: a `ship / ...` job never delays or reddens it. In the report, name the PR and the land run
(its `ship / publish` and `ship / deliver` state), not hook tasks or durations of local steps.
