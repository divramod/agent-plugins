<!-- hal2 slot 04's HANDOFF.md of 2026-10-06 10:48, trimmed (skills plan 0012) -->
# Handoff

Updated 2026-10-06, branch `04`, written at `b4662a1d`.
Farmer: farmer-hal2-71 (hal2)

## Goal

Land worktree 04's cleanup train (04 + 06, 08, 11, 16, 20, 22) on main, so every worktree > 09 can go
(INTENT.md, 2026-10-06 "How are the finished worktrees cleaned up?").

## Plan

[Plan 0094: plugin-n8n 2 implement n8n plugin](plans/0094-plugin-n8n-2-implement-n8n-plugin/plan.md): 9/9
(step 7 "done (dropped: Swift abandoned)"); only its notes ride the train. Passengers' plans: 0104 (06), 0098 (08),
0085 (11, steps 7-8 "later"), 0142 (16), 0125 (20), 0130 (22, step 6 after the landing: that session's).

## Read first

- [CLAUDE.md](CLAUDE.md): layout, commands, rules
- [INTENT.md](INTENT.md): 2026-10-06 rows (Swift abandoned, the cleanup train, a red landing keeps the queue)
- [docs/ci.md](docs/ci.md) "Landings", `~/.claude/skills/mtm/references/ci.md` (watch the run every 5 min)

## Done

- `04-train` built and merged into `04` (ff), main `cb702200` merged (`ec143c36`); every passenger tip is an ancestor.
- Conflicts resolved: WebHostTests.swift (22), AGENTS.md + compilation-cache.sh + process.rs (11), live.rs +
  testing/budgets.rs (main; also the train's swapped p50/budget print args).
- Reds fixed: hal2-agents feed threads (`dd1a3fad`, plans read one after another; starts_per_tick mark gone
  `26b4e997`), bench-all bash 3.2 (`56e98861`), hal2-tell jobs feed threads on Linux (`928d4cad`, one spawn_blocking).

## Next

1. The landing `hal2-cli-git worktree merge-to-main --max-wait 100m --keep-reserved --json` was running in the old
   session's background and holds the queue (04 `held`). If it is gone: rerun it at once (it adopts the hold), in the
   background with timeout 7200000; exit 6 `waiting` → rerun; exit 4 `gate_failed` → fix the red jobs, push, rerun.
2. Watch the run's jobs every 5 min (`hal2-cli-git worktree landings --json` → run id; `gh run view <run> --json
   jobs`); a red job: log (the job log), reproduce with
   `code/bash/scripts/gate/main.sh <job>`, fix, commit, push to 04.
3. Before every reland: if 09 (plan 0147) reported origin/09 done and pushed, merge origin/09 into 04 first and fix
   its reds like any passenger's; never cancel a run going green to take 09 in (INTENT.md, cleanup train row).
4. Report each step to the farmer (SendMessage `farmer-hal2-71`, or the newest farmer in ListAgents).
5. After the landing: `/mtm` step 5 to 8 (release the queue, delete `plans/CURRENT_PLAN` and this file, cleanup).

Done when: `git log origin/main..HEAD` is empty and the queue no longer lists 04.

## Watch out

- One land run at a time; never push to `land/04` or main by hand; never `worktree release` while red (INTENT.md).
- Swift gate jobs still run on this train; Swift is abandoned only after it lands.
- Feed budget tests (plan 0098) count threads: concurrent `tokio::fs` reads grow the blocking pool, on Linux more.
- Do not delete worktrees > 09 or end their sessions: the farmer's job.

## Open

- Nothing unpushed: INTENT.md's rows are in `b4662a1d` (pushed to 04, they land with the train).

## Start the next session with

> /handoff c
