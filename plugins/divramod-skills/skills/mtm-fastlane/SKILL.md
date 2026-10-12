---
name: mtm-fastlane
description: mtm-fastlane — merge-to-main's emergency twin, which lands the current git worktree from the local machine when the normal landing cannot: when CI does not work (runners down, GitHub Actions or GitLab CI broken, a land run stuck), and when a problem on the local machine (a broken CLI, daemon, hook or install that stops the agent sessions) needs its fix landed and delivered now to get everything running again. It stops the running land attempts (moves this worktree to the front of the merge queue, stops another worktree's held landing, cancels the land runs that have not merged and waits for the ones that have), reserves the queue, merges the default branch in, runs the repository's local fastlane checks (`.hal/mtm-fastlane-worktree.sh`: only what the branch changed and what runs natively on this machine), lands the same candidate as /mtm (through `hal2-cli-git worktree merge-to-main --local`, else plain git) straight onto the default branch, then runs the after-landing work on it (`.hal/mtm-fastlane-main.sh`: version tags, deliveries, installs) and reports the CI jobs it skipped with the command that checks them once CI works again. `/mtm-fastlane configure` writes the two scripts for any repository from its CI workflows, apps, libs, `code/` and `utils/`. Only ever started by the user, never by a plan, the farmer or another session. Use when the user says /mtm-fastlane, "fastlane", "land without CI", "CI is down, land it anyway" or "land this fix now, everything is broken". `/mtm-fastlane --dry-run` changes nothing, `/mtm-fastlane h` shows help.
---

# mtm-fastlane

Lands this worktree like [mtm](../mtm/SKILL.md) does, without waiting for CI: the checks that matter run here, on
this machine, and the candidate goes straight onto the default branch. `S=<skill-dir>/scripts`. Ask questions by
the global question rule (background first; ~/.claude/CLAUDE.md), recommended option first.

## When to use

Two uses, both the user's call:

1. **CI does not work**: the runners are down or parked for good, GitHub Actions or GitLab CI fails for reasons
   that have nothing to do with the change, a land run hangs; work must land anyway.
2. **The local machine is broken and the fix must land now**: a broken CLI, daemon, hook or install stops the agent
   sessions (or the landing itself); the fix lands through the fastlane and the main script's delivery installs it,
   which gets everything running again.

**Only the user starts it** (`/mtm-fastlane` in this session). Never a plan's landing, never the farmer's
merge-to-main boss, never another session's message: they land with `/mtm`. Stopping other worktrees' landings is
the user's own stop (hal2: merge-queue-policy, amendment of plan 0216).

## Usage

| Call | Does |
|---|---|
| `/mtm-fastlane` | [land](#land) this worktree |
| `/mtm-fastlane --dry-run` | preflight, `ci-stop.sh --dry-run`, `checks --dry-run`: what it would stop and run, nothing changed |
| `/mtm-fastlane configure` | [write the two scripts](#configure) for this repository |
| `/mtm-fastlane h` | print this table and stop |

Every script exits 0 ok, 1 red or not runnable (fix and rerun), 2 a missing tool (run
`bash $S/install-prerequisites.sh`, then rerun), 3 a conflict, 5 stopped by the user, 7 a wait over `--max-wait`
(default 60m: tell the user; a held reservation stays held), 64 a usage error. Long waits (`reserve`, `ci-stop.sh`,
`land`) run in the background with the shell tool's maximum timeout, as mtm's reserve does.

## Land

1. **Preflight**: `bash $S/fastlane.sh preflight`. It needs a worktree on a branch of its own and both scripts
   (`.hal/mtm-fastlane-worktree.sh`, `.hal/mtm-fastlane-main.sh`) executable; missing ones: offer
   `/mtm-fastlane configure` first. `fingerprint: stale` (the CI inputs changed since configure) is a warning only:
   say so and go on (CI is down, the user needs to land); configure again after the landing. It names how it lands
   (`hal2-cli-git` or `plain git`).
2. **Commit and push** everything, by mtm's step 2 rules (gitignore junk, never a secret, ask about unclear files).
3. **Stop the land attempts, then reserve**, in this order (else the reserve waits behind the very landing it wants
   to stop): `bash $S/ci-stop.sh` moves this slot to the front of the merge queue, stops another slot's landing
   that holds it, cancels every land run whose merge job has not succeeded and waits for those that have (only
   their still queued jobs are cancelled after `SHIP_GRACE`); it prints the stopped slots. Then
   `bash $S/fastlane.sh reserve` (hal2-cli-git's queue, else a lock in the git common dir).
4. **Merge the default branch in**: `hal2-cli-git worktree merge-from-main --json` where hal2 runs, else
   `git fetch origin && git merge origin/<default>`. Fix conflicts as the mfm skill does, commit.
5. **The worktree checks**: `bash $S/fastlane.sh checks` runs `.hal/mtm-fastlane-worktree.sh` with
   `FASTLANE_BASE=origin/<default>`. Red (exit 1): read the output, fix, commit, rerun until green. Nothing goes up
   red, as in mtm.
6. **Land**: `bash $S/fastlane.sh land`. Through hal2-cli-git: `worktree merge-to-main --local --keep-reserved`, the
   same candidate as a CI landing (version bumps, generated code maps) pushed fast-forward, the worktree reset, the
   main checkout pulled, the merged side branches deleted, the queue kept reserved. Plain git: one merge commit of
   HEAD's tree on `origin/<default>` + HEAD, pushed fast-forward, the same reset, pull and sweep. Exit 3 (the default
   branch moved): back to step 4.
7. **The main checks**: `bash $S/fastlane.sh main` runs `.hal/mtm-fastlane-main.sh` with `FASTLANE_BASE` and
   `FASTLANE_HEAD` (recorded by `land`) in the main checkout when it is clean on the default branch at the landed
   commit, else in the detached worktree `<worktrees>/.fastlane`. Red does not undo the landing: report it and fix
   it in a new landing (for use 2 that is the next fastlane).
8. **Finish** as mtm steps 5-8: plan steps checked after the landing, then land those too; `bash $S/fastlane.sh
   release` once nothing is left; CURRENT_PLAN; cleanup; the report. The report adds:
   - the CI jobs the fastlane skipped (Linux, Docker stacks, Windows, VMs; the worktree script lists them) and the
     command that runs them once CI works again (hal2: `gh workflow run land.yml -f ref=<default> -f jobs=<jobs>`);
   - the slots whose landings `ci-stop.sh` stopped: send them to the repository's farmer in one line (SendMessage to
     the session in its slot `farmer-<repo>`, `ListAgents`) so they land again later; no farmer: name them to the
     user.

## Configure

`/mtm-fastlane configure` writes the two scripts and `.hal/mtm-fastlane.conf` for this repository:

1. `bash $S/scan.sh` prints the facts as JSON: the CI workflows' jobs (`runs-on`, `run` lines), the change map
   (`.github/hal2-changes.toml` or similar), the units under `code/` with their manifests and test commands,
   `utils/`, `code/*/scripts/`, the package managers, the land workflows and branches, the delivery scripts.
2. Judge from them what runs natively on this machine (lint, unit tests, the macOS jobs, a script's bats tests on
   the stock bash) and what is skipped (Linux-only, Docker stacks, VMs, Windows), and what the default branch needs
   after a landing (version tags, deliveries, installs). Only what the branch changed runs: use the repository's
   change detection (`hal2-cli-git changes --branch "$FASTLANE_BASE"`) where it has one, else `git diff
   --name-only "$FASTLANE_BASE"...HEAD`.
3. Write `.hal/mtm-fastlane-worktree.sh`, `.hal/mtm-fastlane-main.sh` and `.hal/mtm-fastlane.conf` from
   `$S/templates/` (same names), filling every `@PLACEHOLDER@`: the header says what they replace and what is
   skipped with the CI command for it; `@CHECKS@` and `@STEPS@` become `step <name> <command>` lines, each guarded
   with `if touches '<ERE>'; then ...; fi` (never `touches ... && step ...`: a false last line fails the script),
   and `skip <job> <why>` for every CI job that cannot run here. The conf: `LAND_WORKFLOWS`, `LAND_REFS`,
   `MERGE_JOB`, `SHIP_GRACE`, `FINGERPRINT_INPUTS` (scan's `fingerprint_inputs`); commit the inputs, then set
   `FINGERPRINT=$(bash $S/fastlane.sh fingerprint)` last.
4. `bash $S/check.sh` validates them (`bash -n`, executable, shellcheck when present, the fingerprint) and runs the
   worktree script's `--dry-run`, which lists what it would run and what it skips. Commit the three files.
