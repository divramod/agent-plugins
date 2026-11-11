# The plan's end: `plan.py end`

The plan skill's [Land the plan](../SKILL.md#land-the-plan) in detail (hal2 plan 0514 step 2, D3, D5, D6; the code:
`scripts/plan_end.py`).

```bash
python3 $S/plan.py end --json      # run_in_background with a long timeout: the pre-push hook can take 10-50 min
python3 $S/plan.py end --dry-run   # what it would do; changes nothing
```

It refuses (exit 1, `action: refused`, no run state written) an open step before the landing, a plan that is not
`landing: auto`, a servant's field, a detached HEAD or the default branch, and uncommitted tracked changes (it names
them and commits nothing: commit them as the step's commit, then again; untracked files are only named, left for the
report). Then it writes the run state `pushing` (its why: the field's workqueue wait, or a hold of another field
that slows the hook) and pushes the branch (not when origin's branch is HEAD already). Its `action`:

- `hitched` (state `hitched`): mtm's `scripts/tollman.sh` printed `yes` and the queue is in production: the work
  is hitched (`hal2-cli-git worktree queue ready`). Report `hitched: field <NN> rides the next train` and end the
  turn; the plan's end (mtm's [after "in the barn"](../../merge-to-main/SKILL.md#after-in-the-barn): the run state
  `landed`, `plan.py leave`, cleanup, the report) waits for the tollman's "in the barn". A hitched plan takes no new
  step: what is found now is a follow-up plan.
- `mtm` or `smuggle` (state `done`, `next: /mtm`): no awake tollman, or the queue is in smuggle mode: run the
  [mtm](../../merge-to-main/SKILL.md) skill from its step 1 as the plan's landing (it smuggles in smuggle mode, hal2
  plan 0360 D75, D76; 0365 D5). Above the context threshold hal2's guard stops a `/mtm` that would start a landing:
  hand off with Next `/mtm` (SKILL.md's "Finish a step" point 6); the continued session lands.
- `blocked` (state `blocked`, its `why`): the push failed (the pre-push hook's words) or the hitch was refused. Fix
  what it names, commit, run `plan.py end` again; a cause you cannot fix: push a notification naming the plan and
  the why (`PushNotification`) and stop with the report.

**Built in the wrong field** (e.g. a masterplan's own field): `hal2-cli-plans carry <plan> [--hitch|--land] [--dry-run]`
moves it out by hand (hal2 plan 0689 D35, D36): a fresh field from 10 at the pushed head, hitched there (`--land`:
left to its `/mtm`), the source field back on the masterplan, the row `done (hitched, field NN)` (a milestone:
`running`). The plan's status must already pass `hal2-cli-records check` (D34). It is a tool, not a rule: the reeve
builds no row itself and makes a fresh field per plan (0630 D69), so no field carries on its own; `--no-start` starts
no foreman.

Why it is code: fields 09, 23 and 29 (2026-10-30) had every step committed but sat 10-50 min in the pre-push hook
behind workqueue holds, read as idle and nudged; 09 had handed off before its push. The push is a state now, and
the end needs no hand-off: `plan.py` and git pass hal2's guard above the threshold.
