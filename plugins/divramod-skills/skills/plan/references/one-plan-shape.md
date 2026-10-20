# The one plan shape (schema 2)

The plan skill's section on plans of schema 2 ([SKILL.md](../SKILL.md#the-one-plan-shape-schema-2) points here).

hal2 plan 0376. A plan of schema 2 has no step table: `plan.md` holds the goal, brief, context, the **generated**
`## Overview` (between `<!-- generated: overview -->` and `<!-- /generated -->`; never edit it by hand) and
Pre-authorized; the work is in `subplans/`. The ledgers, `handoff.md`, `changelog.md` and `designs/` stay at the
plan's root and are the foreman's. Both shapes are read; `new` writes schema 1 until plan 0409 moves the farm's readers
(farmer, tollman, `/s`, hal2-cli-plans), so `new --schema 2` is the opt-in and `convert` the way for an old plan.

```
plans/<NNNN>-<slug>/plan.md  decisions.md  questions.md  handoff.md
  subplans/01-<slug>/subplan.md  steps/step-01.md ...   a work sub-plan: a deliverable and its steps
  subplans/99-uat/subplan.md     steps/step-01.md ...   the UAT checks, always last
```

- **Sub-plan** `NN-<slug>` (01-98, at most four words, numbered on, never renumbered); `99-uat` is always the last.
  A **step** is `steps/step-NN.md`, its **ref** `<sub-plan>.<step>` (`01.03`); a bare number resolves only when the plan
  has one work sub-plan or `plans/LEAD` names one. A step's status lives only in its file (`open`, `next`, `running`,
  `blocked`, `done`, `dropped`; `--why <t>` sets the reason); the sub-plan's and the plan's (`open`, `uat` = every work
  sub-plan done, `done`) are derived, and every write regenerates the overview.
- **Write**: `new "<t>" --schema 2` (plan.md, `01-<slug>`, an empty `99-uat`), `subplan new "<t>" [--wave n]`,
  `step add <NN> "<t>" [--done-when d] [--wave n] [--model m] [--effort e] [--window w] [--size s]` (sized by the same
  rubric; `check` enforces `plan-steps-sized` per step file), `uat add "<t>" [--steps ..] [--expected ..] [--open ..]
  [--run ..] [--priority p1-p3] [--tags ..]` (a check `U<n>` of 99-uat, replacing `uat.md`; the verdicts stay the
  landing's), `overview [--write|--check]` to repair or test the generated block.
- **Run**: `status <ref> <status>`, `prompt <ref>` (the hand's Agent call `Plan <NNNN> row 01.03: <title>`) and
  `trailers [<ref>]` (`Step: <ordinal>/<work steps>`) work as on a step table. `ready --json` answers on two levels
  (plan.md `schedule` for sub-plans, a sub-plan's `schedule` for its steps; `serial` default, `waves` runs the lowest
  unfinished wave in parallel; `touches` and the machine resources `@vm` 2, `@ci`, `@land` 1 limit it). **Who runs a
  sub-plan (D19, by rule)**: one ready work sub-plan is the foreman's own (steps in hands); several ready in the
  same wave each get a servant, `create.py --from 30 --lead "<field> <plan> <NN-slug>"`, the line `ready` prints.
  `assign <NN> <who>` sets a sub-plan's `who` (`foreman`, `field NN`, `-`). 99-uat is never ready before the landing.
- **Side branches**: `subplan start <NN>` switches to `<field>-<NN>` (made from `<field>` when missing), `subplan
  finish <NN>` merges it `--no-ff` into `<field>` once its steps are done or dropped, so `<field>` holds only finished
  sub-plans.
- **Stays current**: while CURRENT_PLAN names a plan that is not finished, `new` adds a sub-plan to it (JSON `{"added":
  "subplan", ...}`; a schema 1 plan or masterplan refuses), `new --no-current` writes a separate plan and leaves
  CURRENT_PLAN, and `use` is refused; `--here` is the user's switch only (the old value goes to `PREVIOUS_PLAN`).
  `leave` after a bring in treats `uat` and `done` as finished.
- **Convert**: `convert <plan>... | --all [--dry-run] [--json]`, idempotent: one sub-plan `01-<slug>` holds the old
  rows, `uat.md` and `uat-results.jsonl` become 99-uat, other legacy sections go to `legacy.md`. It skips masterplans,
  plans in schema 2, plans an unmerged field branch changes and plans a field holds; a plan that fails the records
  check is put back. Masterplans stay plans of plans.
- `check` on schema 2 adds `plan-shape`, `overview-current`, `status-derived` and `waves-disjoint`; with a
  `hal2-cli-records` older than 0.7.0 the records findings on schema 2 plans are dropped (`records_skipped`).

## A servant of a sub-plan

A servant takes the whole sub-plan (D19) and, unlike the step servant, marks its own steps:
`plan.py status <NN>.<step> next|running|blocked|done` writes only that sub-plan's step files (a step is `done` once
its done-when passed) and never regenerates the overview; every other write (plan.md, a subplan.md, the ledgers,
99-uat, `new`, `step add`, `assign`, `leave`, `convert`) is refused. It sends the foreman one line when the sub-plan
is done (`sub-plan 02-cli done: field 31 at <sha>; done-when: <last output line>`); the foreman merges its branch
`--no-ff`, runs the sub-plan's Done when, regenerates the overview (`overview --write`) and removes the field.
