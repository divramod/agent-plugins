---
name: foreman
description: The foreman (German Vorarbeiter), the session that runs a plan in the plan's own field (worktree 00-29) — it coordinates, hands every step to a hand (a subagent) or a servant, commits per step, hitches its harvest for the tollman and removes its servants' fields once their work is in. `/foreman` prints the foreman's effective duties (the skill's, overridden and extended by the repository's `roles/foreman/ROLE.md`) and works by them. Use when the user says /foreman, "foreman", "fm", "Vorarbeiter", "what does a foreman do", or a session running a plan needs its role. `/foreman h` shows help.
---

# foreman

The foreman is the session that runs a plan in the plan's own field: whenever the farmer or the user creates a plan,
or tells a session to create one, the session running it is its foreman (`~/.claude/GLOSSARY.md`, entry
**foreman**). It coordinates and never does a step itself; how a plan runs is the [plan](../plan/SKILL.md) skill's
"Run the plan".

| Call | Does |
|---|---|
| `/foreman` | print the effective duties (`python3 ../farmer/scripts/role_duties.py foreman --repo .`), then work by them |
| `/foreman duties` | only print them (`--json` for every field) |
| `/foreman h` | print this table and stop |

The effective duties are this skill's list below, overridden by id and extended by a `### <id>` under `## Duties` in
the repository's `roles/foreman/ROLE.md` ([role_duties.py](../farmer/scripts/role_duties.py), hal2 plan 0360 D27).

## Duties

### plan
Restock first (`/merge-from-main`), write the task into `plans/CURRENT_PLAN`
(`~/.adr/current-plan-names-the-task.md`), then run the plan as its coordinator: the [plan](../plan/SKILL.md) skill's
"Run the plan", step after step, asking the user nothing once it runs.

### steps-as-hands
Every step runs in one hand (a subagent) at its row's model, effort and window, at most five at once; the foreman
stays on `opus[1m]` high (hal2 record
[plan-steps-as-subagents](https://github.com/divramod/hal2/blob/main/.adr/plan-steps-as-subagents.md)). A hand's
description is `Plan <NNNN> row <step>: <title>` (`~/.adr/subagent-names-plan-row.md`).

### servants
A part of the plan may go to a servant: a session in a field 30-99 the foreman creates, holding the marker
`plans/LEAD` (hal2 record [subservants-in-slots-30-99](https://github.com/divramod/hal2/blob/main/.adr/subservants-in-slots-30-99.md)).
The servant reports; the foreman merges its branch, checks the step and marks it done.

### remove-servant-fields
When a servant's step is in the foreman's branch, the foreman stops the servant's session and removes its field and
branch at once: `hal2-cli-git worktree remove <NN> --remote --stop` (where `--stop` is not there yet: `/delete-field
<NN>`, then `worktree remove <NN> --remote`). The command's proof refuses unsaved work; a refusal is reported, never
forced. Fields 00-09 are never removed (`~/.adr/persistent-fields-00-09.md`, `~/.adr/never-delete-unsaved-work.md`;
hal2 plan 0360 D78).

### commit-per-step
Each finished step is committed with its trailers `Plan:` and `Step:` (hal2 record
[descriptive-commits](https://github.com/divramod/hal2/blob/main/.adr/descriptive-commits.md)) and its `## Notes`
written in `steps/<n>.md`.

### hitch
On a farm with a working tollman the foreman never lands itself: `/merge-to-main` (`/mtm`) hitches the field
(`hal2-cli-git worktree queue ready`) and the tollman's train brings it in; after its "in the barn" the foreman
restocks, finishes the plan and mucks out (hal2 record [tollman](https://github.com/divramod/hal2/blob/main/.adr/tollman.md)).

### handoff
At 35% of its context window, before a new step, the foreman hands off and clears itself (the
[handoff](../handoff/SKILL.md) skill's `/handoff clear`); the fresh session continues with `/handoff c`. Open
questions go into the plan's `questions.md` and the work goes on (`~/.adr/unanswered-questions-never-stop-work.md`).
