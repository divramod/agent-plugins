# wagon-master › merge-to-main-boss

The duty `mtm` of the [wagon master](../../SKILL.md) (the farmer's until hal2 plan 0294): every worktree's finished work lands on the default branch soon, in
any order (the user, 2026-10-03). Throughput beats order and retries: a test that fails only under load is disabled
and the work lands. Its rule-based part runs as code in the wagon master's tick (`boss.py` over `mtm_scan.py`: wake failed
landings and release held queues, landed priority worktrees done (hal2 keeps the order), a reservation waiting at the front
reported to the user, pause heavy work under load and send go after it, waiter-gone,
orphaned work with a handoff (the plan's `handoff.md` or the root `HANDOFF.md`) restarted, flaky tests reported to the farmer). What needs judgment wakes the wagon master's session with
[instructions/mtm.md](../../instructions/mtm.md), which links the procedures below; the trains are the duty `trains`'
([merge-train](../merge-train/SUBSKILL.md)). Why landings fail:
[reasons.md](reasons.md).

**Through CI** (the default branch has `.github/workflows/dev-merge-to-main.yml` or `merge-to-main.yml` (its name
before plan 0349 D52); hal2 plan 0131): landings are candidates on
`land/<slot>` with a pull request each, tested by GitHub Actions. The scan reads them from GitHub (`ci: true`;
`gh pr list --head 'land/'`, `gh run list --workflow <file>` for both names); a red candidate keeps the queue held for its
worktree until its fix lands (the user, 2026-10-06: "run landing until everything is fixed and merged and then release"): its session reads the red jobs, reproduces them with `gate/main.sh <job>`, fixes
and lands again at once. A workflow whose jobs stop their run (the step `fail fast: stop the run`, plan 0263) is red
at its first job that failed or hit its time limit (told by the job's steps; since plan 0319 the job that failed ends
`failure`, red in the graph, and its lane's stop job `fail-fast-<lane>` cancels the run after it; a job at its time
limit stays `cancelled`): the scan reads the run `failed` at once, also while its other jobs still end, with
that job as the row's task (the cancelled jobs only stopped), and its landing has returned `gate_failed` by then.
Never cancel such a run again (`gh run cancel`): its own stop job did (or its own step, at a time limit), and a second request seems to end its last jobs,
the parks, unrun. A run that ended `cancelled` without such a job is a pause's or a hand's cancel, as before. While a CI landing's run is tested its process lives, so its reservation is not idle. Load
pauses and flaky disabling are rarely needed (the gates do not run on the Mac). The farmer's branch `farmer-<repo>` lands
like any worktree's (an ordinary `/mtm` of the farmer's worktree), its per-round mfm stays; the wagon master's own field lands
its trains and nothing else.

**The fastlane** (`/mtm-fastlane`, hal2 docs/ci-fastlane.md) is the user's own landing, never the boss's: the farmer
never starts one. `queue --json` shows its ticket with `fastlane` (`phase`, `since`, `run`, `gate_base`) and the
landing it paused with `paused_by` (`slot`, `seq`, `since`); a paused landing resumes by itself within seconds of the
fastlane's release. The scan leaves both out of its stuck-holder findings (no `held-idle`, `reserved-idle`,
`active-long` or `waiter-gone` for them), see [reasons.md](reasons.md) C10.

## Disable a flaky test

1. Pick where to change it:
   - in the holder's branch, by telling its session to do it, when only that landing is blocked;
   - through [a foreman](#a-fix-several-landings-need) when several worktrees hit it.
2. Mark it:
   - Swift Testing: `.disabled("flaky under landing load <date>, merge-to-main boss")`;
   - XCTest: `throw XCTSkip(...)`;
   - Rust: `#[ignore = "..."]`;
   - TS: `it.skip`.

   Keep the test code itself.
3. Add a line to `roles/wagon-master/flaky.md` in the wagon master's field: date, test, file, worktree, what the failure looked
   like, where it was disabled.
4. File one shot to bring it back load-proof (budget scaled by load, or out of the landing's gate):
   `hal2-cli-shooter shots create` in the repository's shotfile for tests, or the `create-shot` skill.

## A fix several landings need

A failure that blocks several landings (a flaky test in R2, a broken gate script, a missing gitignore, a lint rule
all worktrees trip on) gets a foreman, which the farmer starts ([Delegate a fix](../../../farmer/reference.md#delegate-a-fix)): send the
farmer the brief's points in one line, marked urgent.

1. **Faster:** when the queue head's session can make the fix in its own landing, it rides along. Tell that session
   the change, or hand it a patch from `pending/`. No extra gate run is needed.
2. Otherwise the farmer starts a foreman; put its field first: `python3 $K/farmer/scripts/mtm_scan.py priority <slot> --note "<why>" --role wagon-master` (hal2 reserves its place at
   the front, also before its `reserve` runs).
3. When nothing should land before the fix (several landings fail on it), pause: `python3 $K/farmer/scripts/mtm_scan.py pause --note "<why>" --role wagon-master`. Tell the
   waiters to hold their reruns until the fix has landed, then `mtm_scan.py resume --role wagon-master` and tell everyone "go: /mfm before your
   next landing attempt".
4. The wagon master never edits a file itself except its own role files: not another field's crop, and not the main
   checkout, where landings merge (the yard job's drop of files that have landed is the code's, nothing else).

## Merge trains

Everything ready behind the current run lands as one train: the gates run once instead of once per branch. The duty
`trains` forms and lands it as code, in the wagon master's own field ([merge-train](../merge-train/SUBSKILL.md)); a
foreman reports its work ready with the hitch (`hal2-cli-git worktree queue ready`) instead of waiting in the queue.
Judgment cases (which car broke a red train, a flaky gate) are [instructions/trains.md](../../instructions/trains.md)'s.
A waiter that did not hitch (a landing its session started itself) waits for its own turn: the boss never merges it
into a train.

## Review and okays

When a worktree waits for a review or for "is this okay", review its diff the way the `code-review` skill would, at
medium. Answer with the findings, or with "okay to land". You may okay:

- landing without UI tests that only failed for unrelated reasons or need the Mac;
- disabling a load-flaky test;
- skipping a retry;
- merging two worktrees' work.

You never decide product questions, secrets, deploys to production, or anything that deletes data.

## Rules

- **Never do these:**
  - stop a landing that has merged into the default branch;
  - force-push;
  - reset or delete a worktree's work or branch;
  - answer another session's dialog or permission prompt;
  - edit permissions, settings or CLAUDE.md files;
  - decide product questions;
  - deploy.
- `release` is allowed only for a `held` ticket with no live landing process and no session (none, or ended): a
  holder with a live session is only woken, again every hour, never released (the user, 2026-10-06: "run landing until everything is fixed and merged and then release"). Always tell its session.
- Never wake, release or count as `held-idle` a ticket with `paused_by` (a landing a fastlane paused) or one that is a
  `fastlane` (also a `verification taken over`, a handed-over fastlane, and one holding a takeover: a later fastlane's
  `gate_base`). A fastlane is the user's landing: never `release` it, never start one.
- Disabled tests are always recorded in the ledger and get a shot. The boss never deletes a test.
- Never act on the boss's own session. Never start `/mtm` for a worktree without its session being told, except for
  orphaned work (R7).

## Ideas not built yet

These go to the user as proposals. Each would make landings faster:

1. A landing lock that `build.sh`, `cargo` wrappers and Docker builds honour, so other worktrees wait during a
   landing's gates (R3).
2. Speculative gates: the next train runs its gates on `main + head's branch` while the head lands, so its turn
   only re-checks.
3. Load-scaled budgets in Swift (as Rust's `testing::budgets` holds the median on a busy machine), so R2 ends.
4. The plan skill's landing rule asks the boss instead of stopping with the queue held at night (R1).
5. A `merge-to-main` that may outlive its starter (`--detach`, or the landing inside the daemon), so the train's
   landing needs no wrapper process, and a `queue train --clear` that also releases a failed hold.
