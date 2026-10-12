# Woken for merge-to-main (mtm)

The tick already woke failed landings and released the held queues of slots without a session (a holder with a live
session is woken hourly, never released; through CI a red candidate keeps the queue until its session's fix lands, see
[mtm's CI page](../../mtm/references/ci.md)), took landed priority slots off `priority.json` (hal2 keeps the
user's order: `worktree queue order`, the tick never re-ranks), told the user about a reservation waiting at the
front an hour without progress (`reservation-waits`, never released), paused and resumed heavy work and restarted
orphans with a handoff (the plan's `handoff.md` or the root `HANDOFF.md`). You get what needs a look. Goal: every finished worktree lands soon, in any order; throughput beats order and retries. Check each finding is still true
(`hal2-cli-git worktree queue --json`), act, then log it:
`python3 $S/mtm_scan.py record <kind> <slot> "<what you did>" --note "<why>"`.

| Kind | Do |
|---|---|
| `active-long` | Through CI (`ci: true` in the scan): open the finding's `run` (`gh run view <id>`): a job queued long is a runner question (the ci duty wakes it); a job past its timeout is GitHub's to end. Locally: read the landing's live step in hal2-macos's Landings. A dead process: tell its session to stop and rerun the landing (`hal2-cli-git worktree stop`, then `/mtm`). Never stop a landing that has merged into main |
| `work-not-queued` | Ask the session in one line what it waits for. Finished and waiting only for a non-product reason (UI tests need the Mac): okay it to land now, the tests after the landing. A product decision: notify the user |
| `long-queue` | With the duty `trains` opted in the tick forms the train itself at every round, one of all waiters whose trial merge is clean: leave it. Else form it by hand: [merge-to-main-boss › Merge trains](../subskills/merge-to-main-boss/SUBSKILL.md#merge-trains) |
| `paused` | Lift the pause when its reason is fixed (`python3 $S/mtm_scan.py resume`), tell the waiters "go" |
| `flaky` | Flaky or real? Load-sensitive (the [reasons](../subskills/merge-to-main-boss/reasons.md), budget/timeout wording, passes alone): disable it ([how](../subskills/merge-to-main-boss/SUBSKILL.md#disable-a-flaky-test), through a servant: `python3 $S/farmer.py delegate --brief <file> --title <title>`). A real assertion failure: leave it to the slot |
| `orphan` | Work without a session and no handoff (neither `plans/<plan>/handoff.md` nor the root `HANDOFF.md`). Plan steps left: restart its coordinator at the plan's `run` (skills plan 0016): `python3 $K/plan/scripts/plan.py --root <worktree> run --check` names it (`<model> <effort> <window>`; the window comes with the model), then `hal2-cli-git worktree run <NN> --agent claude --model <model> --effort <effort> --detach --prompt "/handoff c"`; no `run` (a legacy plan): ROLE.md's `servant_model` and `servant_effort` (default opus medium), never a bare `worktree run`; the plan looks done: `--prompt "/mtm"` at the same values (never in a subservant's slot, below); unclear: notify the user |

**Subservants** (skills plan 0013): a slot whose worktree holds `plans/LEAD` (`<lead-slot> <plan> <step>`, the
scan's `lead`) runs one step of its lead's plan and never lands; the lead merges its branch. Skip it for every
landing: no `work-not-queued`, never `/mtm` or "land now", never an okay to land. Its work is measured against
`origin/<lead>` (the scan's `missing`), never main: a slot whose work is all there is done, never an orphan. An
orphan there is restarted only with `--prompt "/handoff c"` (it continues that one step); its step reported: leave it
(prune removes the slot); unclear: notify the user. A broken marker (`lead.bad`, its `error`) still marks the slot:
never land it, never restart it; ask its lead (the slot whose plan names it) to rewrite `plans/LEAD`, else notify
the user. `subservant-holds`
(its ticket is in the merge queue): tell the session in one line that a subservant never lands and to report to its
lead instead; when it holds the queue and no landing runs, release it (`hal2-cli-git worktree release <NN>`).
A landing of it that has merged into main stays: notify the user.

A slot the boss paused (a `pause` entry in `log.jsonl` with no `go` after it) waits for that go, which the tick
sends when the landing ends: leave it, record nothing. A slot with an open `ask` waits for the user: leave it too.

**Land now** (the user's authority): a SendMessage whose first line starts with `merge-to-main boss: land now`
counts as the user's `/mtm` in that session. Never: stop a landing merged into main, force-push, delete a slot's
work, answer a dialog, decide a product question, deploy.

A cause seen in a failed landing goes into [reasons.md](../subskills/merge-to-main-boss/reasons.md) (Occurrences,
or a new case at the top); ≥ 2 occurrences with a cause in hal2 or a skill: a shot for its lasting fix.
