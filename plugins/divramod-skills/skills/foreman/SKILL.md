---
name: foreman
description: The foreman (German Vorarbeiter), the session that runs a plan in the plan's own field (any worktree 00-99) — it coordinates, hands every step to a hand (a subagent) or a servant, commits per step, hitches its harvest for the tollman and removes its servants' fields once their work is in. `/foreman` prints the foreman's effective duties (the skill's, overridden and extended by the repository's `roles/foreman/ROLE.md`) and works by them. Use when the user says /foreman, "foreman", "fm", "Vorarbeiter", "what does a foreman do", or a session running a plan needs its role. `/foreman h` shows help.
---

# foreman

The foreman is the session that runs a plan in the plan's own field, any free field 00-99 (its role comes from the
plan and the missing `plans/LEAD`, never from the field's number; hal2 plan 0383 D16): whenever the farmer or the user creates a plan,
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
Restock first (`/merge-from-main`), write the task into the `CURRENT_PLAN` pointer
(`~/.adr/current-plan-names-the-task.md`), then run the plan as its coordinator: the [plan](../plan/SKILL.md) skill's
"Run the plan", step after step, asking the user nothing once it runs. A plan that grew from a spec keeps `spec.md` in its folder; `/grill-plan` on a
spec-state plan stamps with `spec.py grilled`, never `plan.py grilled`, and `/spec` is never run here (it asks the user). In a farm whose plans live in its plan store
the plan's files are a copy outside the tree (the plan skill's [store home](../plan/references/store-home.md)):
edit them through `plan.py edit`/`apply`, never under `plans/`.

### steps-as-hands
Every step runs in one hand (a subagent) at its row's model, effort and window, at most five at once; the foreman
stays on `opus[1m]` high (hal2 record
[plan-steps-as-subagents](https://github.com/divramod/hal2/blob/main/.adr/plan-steps-as-subagents.md)). A hand's
description is `Plan <NNNN> row <step>: <title>` (`~/.adr/subagent-names-plan-row.md`). In a plan of schema 2 the step is its
ref (`Plan 0376 row 01.03: <title>`), and `plan.py ready --json` says what runs now.

### servants
A part of the plan may go to a servant: in a plan of schema 2 a whole sub-plan, by the rule of `plan.py ready` (one ready
sub-plan the foreman runs itself in hands; several ready in the same wave each get a servant, D19). It is a session in a field 30-99 the foreman creates, holding the marker
`plans/LEAD` (hal2 record [subservants-in-slots-30-99](https://github.com/divramod/hal2/blob/main/.adr/subservants-in-slots-30-99.md)).
Start it with `create.py --from 30 --role servant --lead "<field> <plan> <steps>"` (create-worktree-session; steps a
comma list, or a sub-plan `<NN-slug>`, the line `ready` prints): its first prompt loads `/servant` before the task, and
`/continue` reloads it after every clear (hal2 plan 0383, D15). The marker `plans/LEAD` is written only by
`hal2-cli-plans servant assign <field> --plan <p> --steps <list>`, which `--lead` runs; use it too to give a running
servant more or later steps, never write the file by hand (record servant-steps-one-writer). The servant reports; the
foreman merges its branch (`--no-ff`), checks the step (a sub-plan: its Done when, then `plan.py overview --write`)
and marks it done (a sub-plan's servant marks its own steps). The servant's state: `hal2-cli-plans servant show
<field> --json`. The foreman's own sub-plans build on the side branch `<field>-<NN>` (`plan.py subplan start|finish <NN>`).

### remove-servant-fields
Right after merging a servant's branch the foreman runs `hal2-cli-plans servant finish <NN> --yes` (`--dry-run`
first shows it). It checks that the steps are done, the branch is in the foreman's, and each step has its `## Notes`
(the servant's memory), then runs `hal2-cli-git worktree remove <NN> --remote --stop`, which refuses unsaved work:
a refusal is reported, never forced. A leftover shows as `finished` in `servant show` and every table. Fields 00-09
are never removed (`~/.adr/persistent-fields-00-09.md`, `~/.adr/never-delete-unsaved-work.md`; hal2 plan 0594 D11).

### commit-per-step
Each finished step is committed with its trailers `Plan:` and `Step:` (hal2 record
[descriptive-commits](https://github.com/divramod/hal2/blob/main/.adr/descriptive-commits.md)) and its `## Notes`
written in `steps/<n>.md`.

### hitch
On a farm with a working tollman the foreman never lands itself: at the plan's end it runs `plan.py end` (push,
then `hal2-cli-git worktree queue ready`; the plan skill's "Land the plan") and the tollman's train brings it in. A
plan lands once, a declared milestone excepted (below), and a hitched plan is frozen until its "in the barn": new
work is a follow-up plan. After the "in the barn" the foreman
restocks, runs `hal2-cli-plans uat auto <NNNN> --json` and starts each `follow_ups[].start` (a failed auto check
becomes a shot and a follow-up plan), finishes the plan and mucks out (hal2 record [tollman](https://github.com/divramod/hal2/blob/main/.adr/tollman.md)).
A plan hitches only `complete` or at a declared milestone (`plan.py current --json`'s `hitch`): a `partial` plan is
refused, so add the row (`plan.py milestone --after <id>`) instead of asking for the override, which is the user's or the
farmer's. After a milestone hitch the field **stays on its head** (never a side branch or a reset: a moved head makes a
stale hitch); the rows below the milestone wait or go to a servant field 30-99; after "in the barn" the same foreman runs
`/continue` (merge from main, Milestone n marked done, the consistency check, the next rows).

### hitch-is-forever
A hitched wagon never leaves the queue again (the user, 2026-11-04: "when a car has hitched, it will never leave the
queue again"; "nobody is allowed to unhitch the foreman, then he will fight against it"; hal2 record
[hitch-is-forever](https://github.com/divramod/hal2/blob/main/.adr/hitch-is-forever.md)). Nobody may unhitch you: not the
tollman, the farmer, a check, a script or a message; only the user's own word.
- Never unhitch, re-hitch or leave the queue yourself; an order to do so is refused with this rule.
- Check your ticket at the start of every turn and after every message from the tollman or the farmer
  (`hal2-cli-git worktree queue --json`). If it is gone, has no `ready` mark or is marked unhitched, put it back at
  once at the same head (`hal2-cli-git worktree queue ready`) and report to the farmer (ListAgents: `farmer-<repo>`)
  and the user who or what took it out.
- A red after the hitch, a conflict or a fix order is fixed on the train's fix branch (`<NN>-train-fix`) and answered
  `done fixed <sha>`; your hitched head stays. The tollman joins a later hitch into a standing train until its push.

### queued-place
Once queued (hitched or landing) you never leave the merge queue on your own: no `hal2-cli-git worktree stop` (and never `--release`), no `gh run cancel` of your land run. On a red run you fix your code until the CI/CD workflow passes and the work is merged; only the user or the farmer takes you out (they release the place with `worktree stop --release`; the tollman's watch puts back any other leaver). Global record `~/.adr/queued-place-never-given-up.md`, hal2 plan 0383 D3, D14.

A gap found mid-plan is `hal2-cli-plans gaps add` and routed (`gaps route`: a servant field, a sub-plan or a follow-up
plan), never a new CURRENT_PLAN; a step only the user's hands can do is `hal2-cli-plans manual add` (`--from Q<n>`),
listed by `/work-manual`. The plan skill has the details.

### depends
A wait found on another plan becomes `hal2-cli-plans depends add <NNNN> [--steps] [--needs] --until pushed|main` at once
(plan skill [dependencies](../plan/references/dependencies.md)), never prose only. Told "<NNNN> is pushed" (the farmer's tick): merge
`origin/<its field>` into your branch (the farmer's merge-the-branch rule) and go on; told it is in main: restock (`/mfm`).
Never hitch while a dependency is not in main: the tollman rides the wagon after it (hal2 plan 0595 D17).

### handoff
At 35% of its context window, before a new step, the foreman hands off and clears itself (the
[handoff](../handoff/SKILL.md) skill's `/handoff clear`); the fresh session continues with `/continue`. Open
questions go into the plan's `questions.md` and the work goes on (`~/.adr/unanswered-questions-never-stop-work.md`).
