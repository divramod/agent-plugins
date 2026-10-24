---
name: smuggle
description: smuggle — land the current git worktree from this machine past CI, merge-to-main's twin for when the normal landing cannot or should not wait: CI does not work (runners down, GitHub Actions or GitLab CI broken, a land run stuck), a broken local CLI, daemon, hook or install needs its fix landed and installed now, or the merge queue is in smuggle mode. It pauses the running landing or train in place (it resumes by itself), merges the default branch in, runs only the checks of what the branch changed on this machine (the touched units of `.hal/smuggle.toml`), lands the candidate straight onto the default branch with its version bumps and CHANGELOG.md as a landing writes them, starts no CI run (the next land run gates the smuggled range), installs what it changed so it works at once (`.hal/smuggle-main.sh`) and leaves the merge queue once landed; a red smuggle keeps holding the queue, its session fixes and reruns until it lands. A change outside the units of `.hal/smuggle.toml` warns with the CI jobs it would have run and lands only on the user's yes. Where hal2 has it, one call: `hal2-cli-git worktree merge-to-main --smuggle`; else this skill's steps with `--local` or plain git. `/smuggle configure` writes the scripts and the unit list for any repository. Started by the user, or in the merge queue's smuggle mode by /mtm (`/smuggle --from-mtm`; a plan's `Landing: auto` and the farmer's "smuggle mode: run /mtm now" included); never otherwise by a plan, the farmer or another session. Use when the user says /smuggle, "smuggle", "land without CI", "CI is down, land it anyway" or "land this fix now". `/smuggle --dry-run` changes nothing, `/smuggle h` shows help.
---

# smuggle

Lands this worktree like [mtm](../merge-to-main/SKILL.md) does, without waiting for CI: the checks that matter run here, on
this machine, and the candidate goes straight onto the default branch. `S=<skill-dir>/scripts`. Ask questions by
the global question rule (background first; ~/.claude/CLAUDE.md), recommended option first.

## When to use

Three uses:

1. **CI does not work**: the runners are down or parked for good, GitHub Actions or GitLab CI fails for reasons
   that have nothing to do with the change, a land run hangs; work must land anyway.
2. **The local machine is broken and the fix must land now**: a broken CLI, daemon, hook or install stops the agent
   sessions (or the landing itself); the fix lands through the smuggle and the main script's delivery installs it,
   which gets everything running again.
3. **The worktree's mode is smuggle**: the user switched the whole merge queue (`hal2-cli-git worktree queue mode smuggle`)
   or set this worktree's entry (`queue entry-mode <slot> smuggle`, hal2 plan 0365 D5); the tollman leaves it out of its
   trains and its `/mtm` smuggles (below).

## A queued place is never given up
Once queued (hitched or landing) a worktree never leaves the merge queue on its own: no `hal2-cli-git worktree stop`, never `--release`, no `gh run cancel` of its own land run; on a red run it fixes its code until the CI/CD workflow passes. Only the user or the farmer takes it out (`worktree stop --release`). `ci-stop.sh` (the user's smuggle) only pauses another landing: its place stays held (hal2 plan 0383 D3). Record `~/.adr/queued-place-never-given-up.md`.

## Who starts it

**The user** (the skill's command in this session), **or `/mtm` in smuggle mode** (hal2 plan 0360 D53, D75,
D76; 0365 D5): when `hal2-cli-git worktree queue mode --slot <this worktree>` prints `smuggle` (its entry's own mode,
else the queue's; an older hal2-cli-git without `--slot`: the queue's), the user switched the queue or this entry to
smuggle mode, the tollman brings no train of it, and [mtm](../merge-to-main/SKILL.md) (its **Smuggle mode**) runs this skill's [land](#land) in place
of a hitch, whoever started that `/mtm`: the user, a plan's `Landing: auto`, or the farmer's message
`farmer (development foreman): smuggle mode: run /mtm now`. `/mtm` passes `--from-mtm` to the preflight, whose
guard refuses (exit 6) while the worktree's mode is production: then never a plan's landing, never the farmer's
merge-to-main boss, never another session's message; they land with `/mtm`. Without `--from-mtm` the preflight takes
the start as the user's: run the skill without the flag only on the user's own `/smuggle` (or their words above). It
pauses other worktrees' landings, which resume by themselves (hal2: merge-queue-policy, amendment of 2026-10-10;
hal2's smuggle guide in docs/).

## What it changes, and what may be smuggled

- **No CI run** (D68, D72): no `land/<slot>` candidate is pushed, the default branch's push starts nothing; the
  smuggle's ticket stays in the queue only as an unverified range, which the next land run (the resumed train's,
  else the next landing's) gates with `Hal2-Gate-Base` and clears when it lands. Nothing else of it stays queued: its
  hitch and ticket go when it has landed; a red smuggle (conflict, checks, build, push) keeps the ticket held `failed`, blocks every new landing and smuggle, and its own rerun takes it over (plan 0370).
- **Versions and CHANGELOG.md** (D68, D69): hal2-git's smuggle bumps the versions of the apps, libs and scripts it
  touches (the `Versions:` block of its merge commit, dependents included) and writes CHANGELOG.md from the plans'
  `changelog.md` fragments it brings in, as a landing does. The skill runs no bump of its own.
- **The units** (D49, D63): `.hal/smuggle.toml` lists the units a smuggle may land (hal2: the skills, the mod
  subagent-context, hal2-nvim, the tmux plugin with hal2-cli-tmux), each with its `paths`, `checks`, `build` and
  `install`, plus `free` paths (plans, generated files). The preflight reads it from the branch's HEAD (`units.py
  warn`), so a change to the list is itself outside it. Inside the units the worktree script runs only the touched
  units' checks and the main script only their installs; a path outside every unit prints the warning (the paths and
  the CI jobs `hal2-cli-git changes` names), exit 4. In a repository with `.github/hal2-changes.toml`, `units.py run
  checks` runs the job map's selection instead of the units' `checks` (`jobmap.py`: one `changes --keys --json`, jobs with
  their packages, a job green before skipped and listed in the report, a green one on a clean tree marked); the
  units' `checks` are the fallback without a map or when the call fails, and run besides the map's jobs when a run job
  is unknown to the gate or none is runnable (a repository whose map names jobs the gate lacks still gets its unit checks). With `SMUGGLE_RUN_LOGS` set (hal2-git's
  smuggle) every job or unit command is a step of the smuggle's run (`runsteps.py`: `<lane>.jobs` lines with the exit,
  cpu, load, sccache delta and key; its output in `<lane>.log`, printed only when red).

## Usage

| Call | Does |
|---|---|
| `/smuggle` | [land](#land) this worktree |
| `/smuggle --from-mtm` | [land](#land), started by `/mtm` in smuggle mode: the guard refuses it while the worktree's mode is production |
| `/smuggle --dry-run` | `merge-to-main --smuggle --dry-run` (the holder it pauses, the runs it cancels, the phases, the scripts' dry runs; nothing changed); without hal2's `--smuggle`: preflight, `ci-stop.sh --dry-run`, `checks --dry-run` |
| `/smuggle configure` | [write the two scripts](#configure) for this repository |
| `/smuggle h` | print this table and stop |

`hal2-cli-git worktree merge-to-main --smuggle` exits 0 landed or nothing to merge, 1 an error, 2 a usage error
(`--local` and `--keep-reserved` are refused with it), 11 a conflict, 12 `checks_failed`, `gate_failed` or
`delivery_failed`, 13 `stopped`, `cancelled` or `interrupted`, 10 `queued` (3, 4, 5 and 6 before plan 0318); the
[land](#land) section says what to do for each. The skill's own scripts exit 0 ok, 1 red or not runnable (fix and rerun), 2 a missing tool (run
`bash $S/install-prerequisites.sh`, then rerun), 3 a conflict, 4 a change outside the units (ask the user), 5 stopped
by the user, 6 refused (`--from-mtm` in production mode), 7 a wait over `--max-wait`
(default 60m: tell the user; a held reservation stays held), 64 a usage error. Long waits (`reserve`, `ci-stop.sh`,
`land`) run in the background with the shell tool's maximum timeout, as mtm's reserve does.

## Land

1. **Preflight**: `bash $S/smuggle.sh preflight` (`--from-mtm` when `/mtm` started it). Exit 6: refused, `/mtm`
   started it in production mode: stop and go back to `/mtm`'s own way. It needs a worktree on a branch of its own and both scripts
   (`.hal/smuggle-worktree.sh`, `.hal/smuggle-main.sh`) executable; missing ones: offer
   `/smuggle configure` first. `fingerprint: stale` (the CI inputs changed since configure) is a warning only:
   say so and go on (CI is down, the user needs to land); configure again after the landing. It names how it lands
   (`hal2-cli-git` or `plain git`) and whether hal2-cli-git has `--smuggle`. Its last lines are the units: exit 4
   means a path outside every unit: show the user the paths and the CI jobs it printed and ask **once** in the Q
   form (a) stop and land with `/mtm` (Recommended), b) smuggle anyway, c) move the outside change to another
   branch). Only on the user's yes in this session rerun `bash $S/smuggle.sh preflight --yes-outside` and go on; a
   plan's or the farmer's start never answers it: stop and report.
2. **Commit and push** everything, by mtm's step 2 rules (gitignore junk, never a secret, ask about unclear files).

Then **pick the way**: the preflight prints `smuggle: hal2-cli-git ... --smuggle` where the installed hal2-cli-git
has the flag: take [one call](#with-hal2-one-call). Else (no hal2, an older one): [the steps 3-8](#without---smuggle-the-steps-3-8).

### With hal2: one call

Run `hal2-cli-git worktree merge-to-main --smuggle --json` **in the background** (`run_in_background`, the maximum
timeout; a shell timeout's SIGTERM counts as the user's stop). It pauses the queue holder (never stops it), cancels
this slot's unmerged land runs, merges the default branch in, runs the worktree script and the build in parallel,
lands with the version bumps and CHANGELOG.md, installs, and leaves the queue once landed (a red end keeps it; its range stays unverified for the
next land run; no land run of its own). It does what the steps below do
by hand (`ci-stop.sh`, `smuggle.sh reserve|checks|land|main|release`): run none of them beside it. Read the
result by exit code and `status`:

| Exit | `status` | Do |
|---|---|---|
| 0 | `landed`, `nothing` | done. Report `phases`, `report` (its `ci` line lists the jobs left to the next land run), `warnings`, `gate_base` |
| 1 | `failed` | the smuggle still holds the queue: report the error, fix and rerun at once |
| 11 (or 3) | `conflict` | the smuggle still holds the queue: resolve as the mfm skill does, commit, rerun at once |
| 12 (or 4) | `checks_failed`, `gate_failed`, `delivery_failed` | the smuggle still holds the queue (held `failed`, new landings wait): read `part` and `tail`, fix the reasons, commit, rerun at once, on your own, until it lands (failed run > fix > next run); never release the place yourself, only the user's or the farmer's word does (`hal2-cli-git worktree stop|release --by <who>`). A `delivery_failed` with `landed: true` is already on the default branch: fix it in a new smuggle |
| 13 (or 5) | `stopped`, `cancelled` | the user's stop is final: report and stop |
| 13 (or 5) | `interrupted` | its process went away: rerun the same command, it adopts the landing |
| 10 (or 6) | `queued` | the wait's slice passed: rerun the same command at once, the ticket keeps its place |

Then **finish** as mtm steps 5-8 (plan steps checked after the landing, then land those too; CURRENT_PLAN;
cleanup); the command released the queue itself, so no `smuggle.sh release`. The report adds:

- `paused` (the slots it paused: they resume by themselves, no message to the farmer);
- the CI jobs the smuggle skipped (`report`'s `ci` line) and the command that runs them once CI works again (hal2:
  `gh workflow run dev-merge-to-main.yml -f ref=<default> -f jobs=<jobs>`, or `merge-to-main.yml` where
  the repository still has the older name).

### Without `--smuggle`: the steps 3-8

3. **Stop the land attempts, then reserve**, in this order (else the reserve waits behind the very landing it wants
   to stop): `bash $S/ci-stop.sh` moves this worktree to the front of the merge queue, stops another worktree's landing
   that holds it, asks every land run whose merge job has not succeeded to cancel and waits for those that have
   (only their still queued jobs are cancelled after `SHIP_GRACE`), then waits until every one has ended; it prints
   the stopped worktrees. **A run gets one cancel request**, however many rounds its end takes and however often the
   script is rerun (it notes the runs it asked in the git common dir; a run started again, a new attempt, is asked
   once more), and none when its own fail-fast is ending it already (the step `fail fast: stop the run` of one of
   its jobs ended `success` or still runs, or a job with that step concluded `cancelled`, or the step `fail fast:
   cancel the run` of a lane's stop job `fail-fast-<lane>` ended `success` or still runs; a failed job's stop step is
   only a hand-off to that stop job and stops counting once the stop job's cancel step ended `failure` with no request
   out, plan 0319; such a run can no longer merge and is printed as `ending`, like one an earlier call asked). Never send a `gh run cancel` of your own
   beside it: a second request to a run that is cancelling seems to end its last jobs, which park the machines,
   unrun (hal2 plan 0263). Exit 1 with "cancelling run <id> failed": the run is not asked again; look at it (`gh run view
   <id>`) and only when nothing is cancelling it remove the file the message names and rerun. Then
   `bash $S/smuggle.sh reserve` (hal2-cli-git's queue, else a lock in the git common dir).
4. **Merge the default branch in**: `hal2-cli-git worktree merge-from-main --json` where hal2 runs, else
   `git fetch origin && git merge origin/<default>`. Fix conflicts as the mfm skill does, commit.
5. **The worktree checks**: `bash $S/smuggle.sh checks` runs `.hal/smuggle-worktree.sh` with
   `SMUGGLE_BASE=origin/<default>`. Red (exit 1): read the output, fix, commit, rerun until green. Nothing goes up
   red, as in mtm.
6. **Land**: `bash $S/smuggle.sh land`. Through hal2-cli-git: `worktree merge-to-main --local --keep-reserved`, the
   same candidate as a CI landing (version bumps, generated code maps) pushed fast-forward, the worktree reset, the
   main checkout pulled, the merged side branches deleted, the queue kept reserved. Plain git: one merge commit of
   HEAD's tree on `origin/<default>` + HEAD, pushed fast-forward, the same reset, pull and sweep. Exit 3 (the default
   branch moved): back to step 4.
7. **The main checks**: `bash $S/smuggle.sh main` runs `.hal/smuggle-main.sh` with `SMUGGLE_BASE` and
   `SMUGGLE_HEAD` (recorded by `land`) in the main checkout when it is clean on the default branch at the landed
   commit, else in the detached worktree `<worktrees>/.smuggle`. Red does not undo the landing: report it and fix
   it in a new landing (for use 2 that is the next smuggle).
8. **Finish** as mtm steps 5-8: plan steps checked after the landing, then land those too; `bash $S/smuggle.sh
   release` once nothing is left; CURRENT_PLAN; cleanup; the report. The report adds:
   - the CI jobs the smuggle skipped (Linux, Docker stacks, Windows, VMs; the worktree script lists them) and the
     command that runs them once CI works again (hal2: `gh workflow run dev-merge-to-main.yml -f ref=<default> -f
     jobs=<jobs>`, or `merge-to-main.yml` where the repository still has the older name);
   - the worktrees whose landings `ci-stop.sh` stopped: send them to the repository's farmer in one line (SendMessage to
     the session in its worktree `farmer-<repo>`, `ListAgents`) so they land again later; no farmer: name them to the
     user. (This list stays only here: the one call above pauses, it stops nothing.)

## Configure

`/smuggle configure` writes the two scripts, `.hal/smuggle.conf` and `.hal/smuggle.toml` for this repository:

In hal2 itself the two scripts are thin delegates to `code/bash/scripts/smuggle/` (the worktree script exits
0/1/2 and writes a JSON line per lane or unit to `SMUGGLE_REPORT`; the main script takes `build|install|tags` and
exits 75 while the deliver lock is held; both call `$S/units.py` for the units of `.hal/smuggle.toml`). The steps below write them for any other repository.

1. `bash $S/scan.sh` prints the facts as JSON: the CI workflows' jobs (`runs-on`, `run` lines), the change map
   (`.github/hal2-changes.toml` or similar), the units under `code/` with their manifests and test commands,
   `utils/`, `code/*/scripts/`, the package managers, the land workflows and branches, the delivery scripts.
2. Judge from them what runs natively on this machine (lint, unit tests, the macOS jobs, a script's bats tests on
   the stock bash) and what is skipped (Linux-only, Docker stacks, VMs, Windows), and what the default branch needs
   after a landing (version tags, deliveries, installs). Only what the branch changed runs: use the repository's
   change detection (`hal2-cli-git changes --branch "$SMUGGLE_BASE"`) where it has one, else `git diff
   --name-only "$SMUGGLE_BASE"...HEAD`.
3. Write `.hal/smuggle-worktree.sh`, `.hal/smuggle-main.sh`, `.hal/smuggle.conf` and `.hal/smuggle.toml` from
   `$S/templates/` (same names), filling every `@PLACEHOLDER@` (the toml: `@FREE@` the plans and generated paths,
   `@UNITS@` one `[[unit]]` per unit the user may smuggle, with the fast checks of its README): the header says what they replace and what is
   skipped with the CI command for it; `@CHECKS@` and `@STEPS@` become `step <name> <command>` lines, each guarded
   with `if touches '<ERE>'; then ...; fi` (never `touches ... && step ...`: a false last line fails the script),
   and `skip <job> <why>` for every CI job that cannot run here. The conf: `LAND_WORKFLOWS` (the file names of
   scan's `land_workflows`; of `dev-merge-to-main.yml` and `merge-to-main.yml`, one workflow before and
   after its renames, `ci-stop.sh` asks all where one is listed, so a conf written before a rename still stops every
   land run),
   `LAND_REFS`,
   `MERGE_JOB`, `SHIP_GRACE`, `FINGERPRINT_INPUTS` (scan's `fingerprint_inputs`); commit the inputs, then set
   `FINGERPRINT=$(bash $S/smuggle.sh fingerprint)` last.
4. `bash $S/check.sh` validates them (`bash -n`, executable, shellcheck when present, the fingerprint, the toml read
   at HEAD) and runs the worktree script's `--dry-run`, which lists what it would run and what it skips. Commit the
   four files.
