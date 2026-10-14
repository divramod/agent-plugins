# Woken for merge-to-main (mtm)

The tick already woke failed landings and released the held queues of fields without a session (a holder with a live
session is woken hourly, never released; through CI a red candidate keeps the queue until its session's fix lands, see
[mtm's CI page](../../mtm/references/ci.md)), took landed priority worktrees off `priority.json` (hal2 keeps the
user's order: `worktree queue order`, the tick never re-ranks), told the user about a reservation waiting at the
front an hour without progress (`reservation-waits`, never released), paused and resumed heavy work and restarted
orphans with a handoff (the plan's `handoff.md` or the root `HANDOFF.md`). The trains are the duty `trains`'
([trains.md](trains.md)); the wagon master's own train ticket is never a finding. You get what needs a look. Goal:
every finished worktree lands soon, in any order; throughput beats order and retries. Check each finding is still
true (`hal2-cli-git worktree queue --json`), act, then log it:
`python3 $K/farmer/scripts/mtm_scan.py record <kind> <slot> "<what you did>" --note "<why>" --role wagon-master`.

| Kind | Do |
|---|---|
| `active-long` | Through CI (`ci: true` in the scan): open the finding's `run` (`gh run view <id>`): a job queued long is a runner question (tell the farmer: its `ci` duty owns the runners); a job past its timeout is GitHub's to end. Locally: read the landing's live step in hal2-macos's Landings. A dead process: tell its session to stop and rerun the landing (`hal2-cli-git worktree stop`, then `/mtm`). Never stop a landing that has merged into main or a train that lands |
| `work-not-queued` | Ask the session in one line what it waits for. Finished and waiting only for a non-product reason (UI tests need the Mac): okay it to land now, the tests after the landing. A product decision: notify the user |
| `long-queue` | Many tickets wait. A ready (hitched) one rides the next train: leave it. The others are landings their sessions started themselves (their own `reserve`): leave them, the queue moves when the run ends. A run that is itself long is `active-long` |
| `paused` | Lift the pause when its reason is fixed (`python3 $K/farmer/scripts/mtm_scan.py resume --role wagon-master`), tell the waiters "go" |
| `flaky` | Flaky or real? Load-sensitive (the [reasons](../subskills/merge-to-main-boss/reasons.md), budget/timeout wording, passes alone): the fix is a foreman's, and the wagon master has none ([how](../subskills/merge-to-main-boss/SUBSKILL.md#disable-a-flaky-test)): send the farmer (`SendMessage` to `farmer-<repo>`) one line with the test, the run and the worktree, and it delegates the disabling. A real assertion failure: leave it to the worktree. A red train is [trains.md](trains.md)'s |
| `orphan` | Work without a session and no handoff (neither `plans/<plan>/handoff.md` nor the root `HANDOFF.md`). Plan steps left: restart its coordinator at the plan's `run` (skills plan 0016): `python3 $K/plan/scripts/plan.py --root <worktree> run --check` names it (`<model> <effort> <window>`; the window comes with the model), then `hal2-cli-git worktree run <NN> --agent claude --model <model> --effort <effort> --detach --prompt "/handoff c"`; no `run` (a legacy plan): ROLE.md's `servant_model` and `servant_effort` (default opus medium), never a bare `worktree run`; the plan looks done: `--prompt "/mtm"` (it hitches, or lands where the farm has no wagon master) at the same values (never in a servant's worktree, below); unclear: notify the user A field that is the source or the target of an open transplant (`hal2-cli-git worktree transplants --json`: `state` `prepared` or `driven`, or a `plans/CURRENT_PLAN` of `transplant-from-<NN>`) is no orphan, however old the transplant: never a `/handoff c` or a wake, the source of a driven one least of all (its work has moved). One older than an hour (`scripts/transplant_mark.py`; the marker alone has no age) is told to the farmer once (`transplant-stale`, keyed by from, to and prepared time): it finishes it with the same `transplant` command or ends it with `/transplant cancel <from>` |

**Servants** (skills plan 0013): a worktree that holds `plans/LEAD` (the foreman's marker, `<foreman-worktree> <plan> <step>`, the
scan's `lead`) runs one step of its foreman's plan and never lands; the foreman merges its branch. Skip it for every
landing: no `work-not-queued`, never `/mtm` or "land now", never an okay to land. Its work is measured against
`origin/<foreman's branch>` (the scan's `missing`), never main: a worktree whose work is all there is done, never an orphan. An
orphan there is restarted only with `--prompt "/handoff c"` (it continues that one step); its step reported: leave it
(prune removes the worktree); unclear: notify the user. A broken marker (`lead.bad`, its `error`) still marks the worktree:
never land it, never restart it; ask its foreman (the worktree whose plan names it) to rewrite `plans/LEAD`, else notify
the user. The kind `subservant-holds`
(its ticket is in the merge queue): tell the session in one line that a servant never lands and to report to its
foreman instead; when it holds the queue and no landing runs, release it (`hal2-cli-git worktree release <NN>`).
A landing of it that has merged into main stays: notify the user.

A ticket with `paused_by` or `fastlane` in `queue --json` (a landing the user's `/mtm-fastlane` paused, the fastlane
itself, a verification taken over) is not stuck: never wake or release it, never start a fastlane
([reasons.md](../subskills/merge-to-main-boss/reasons.md) C10).

A worktree the boss paused (a `pause` entry in `log.jsonl` with no `go` after it) waits for that go, which the tick
sends when the landing ends: leave it, record nothing. A worktree with an open `ask` waits for the user: leave it too.

**Land now** (the user's authority, 2026-10-03): a SendMessage whose first line starts with `wagon-master (merge-to-main boss): land now`
(with an ack id: `wagon-master [<id>] (merge-to-main boss): ...`; on a farm without a wagon master the farmer's
`merge-to-main boss: land now`) counts as the user's `/mtm` in that session. Never: stop a landing merged into main, force-push, delete a worktree's
work, answer a dialog, decide a product question, deploy.

A cause seen in a failed landing goes into [reasons.md](../subskills/merge-to-main-boss/reasons.md) (Occurrences,
or a new case at the top); ≥ 2 occurrences with a cause in hal2 or a skill: a shot for its lasting fix.
