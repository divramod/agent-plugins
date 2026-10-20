# Run a parallel plan

The plan skill's section on parallel plans ([SKILL.md](../SKILL.md#run-a-parallel-plan) points here).

A big plan runs its independent steps at once, as parallel subagents of its coordinator, never in other sessions.
Its table (`plan.py new --parallel`) adds three columns after Step: **Needs** (the steps that must be done first,
ids and ranges `1, 3-7`; blank or `-` is none; ids are integers, never renumbered), **Touches** (what the step
changes: `rust:<crate>`, `ts:<package>`, `proto:<package>`, `docs`, and resources a machine has once such as `@vm`,
`@ci`, `@land`; two steps sharing one never run at once, a `Capacity: @vm=3` line under the title changes that) and
**Who** (`subagent`; `lead` (the value stays) for the foreman's own bookkeeping, such as a milestone; `user` for a batched
physical action). Status is blank, `running`, `blocked <why>` or `done`; `problems` names bad ids, Needs and cycles:
fix them before dispatching.

1. `python3 $S/plan.py ready --json`: the open steps whose Needs are done and whose Touches are free, and why the others wait.
2. Write each ready step's Task, `plan.py assign <n> subagent`, then one `plan.py prompt <n>` each and all their
   Agent calls in one message. Their Touches are disjoint; builds and test runs that share a machine resource run
   one at a time. Worktree isolation only when the repo's tracked `.claude/settings.json` sets
   `"worktree": {"baseRef": "head"}` (otherwise the isolated tree branches from the default branch).
3. As each reports: its done-when, the diff, its commit, `status <n> done`, then `ready` again. Shared files
   (`plan.md`, `INTENT.md`, `AGENTS.md`, lockfiles, generated files, CI config) are the coordinator's alone.

## Milestones

**Milestones** land a plan too big to land once in parts: a row "Milestone n: land ...", whose Needs name what it
carries and which touches `@land`; before it, every gate job the candidate touches runs green locally, then the
farmer's (or the user's) "land now" and `/mtm milestone` (the queue is not kept, `CURRENT_PLAN` stays). Only the
plan's last landing is the plan's own ([Land the plan](#land-the-plan)).
