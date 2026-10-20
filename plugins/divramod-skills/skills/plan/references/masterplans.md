# Masterplans

The plan skill's section on masterplans ([SKILL.md](../SKILL.md#masterplans) points here).

A **masterplan** is a plan whose rows are plans (`plans/<NNNN>-masterplan-<slug>/plan.md`): the parallel form without
Model, Effort, Window and Size, `landing: manual` (it never lands itself) and its symbol, the key `crop`. A plan names
its masterplan by the key `parent` and is then never a masterplan itself; the JSON says `masterplan`, `crop`, `parent`
and `row`. **Three levels, masterplan > plan > step**: the masterplan's files are its foreman's alone (the foreman of
the field it was created in) and are never brought in on their own; a plan has its own folder, ledger, UATs and
foreman, who brings it in alone (a servant may do its steps: [Work as a servant](#work-as-a-servant)); a step
runs in a hand, one subagent, and the foreman commits it. No level below: **a hand's helpers** (read-only fan-out:
a search, a review) have no row or file, report to the hand, carry its name (`Plan <NNNN> row <step>: <title>`),
never edit, commit or start a servant, and count in the five subagents at once. **A row's status** is `draft` (from `new --parent`: not
yet grilled again against the default branch), `next`, `running`, `blocked <why>`, `done` (`done (<note>)`) or blank,
nothing else; `done` exactly when its plan is. **Code ticks it**: the `plan.py status` that finishes a plan's last
step sets its row `done` (`tick` in the JSON, `tick_skipped`: why not; also with `--plan`), a reopened step takes it
back (`running`); commit both `plan.md` files. Between two plans `CURRENT_PLAN` names the masterplan (`/handoff c`).

- `plan.py new "<title>" --masterplan`: its crop is the first of twelve no unfinished masterplan of any checkout uses;
  the marker is none of the name's four words. After `new --parent <n>` fill the row's Needs and Touches.
- `plan.py masterplan [--plan <ref>] [--json]`: the roll-up of `hal2-cli-plans masterplan` (`$HAL2_CLI_PLANS`, else on
  PATH; `+` while a row is `draft`), without it the own rows and one line, exit 0: never add up step tables yourself.
  Its `after_landing`: the plans whose open steps are all checked after the landing (`/mtm` finishes them).
- **Schema 2** (the one plan shape, SKILL.md): a masterplan stays a plan of plans, schema 1, rows under `## Steps`, no
  `subplans/`, never converted (`new --masterplan` always writes the old table; `convert` skips it). Its plans may be
  schema 2 (`convert`), keeping `parent`; a row of such a plan turns `done` when the
  plan's derived status is `uat` or `done`, and goes back when it is `open` again. A servant of a masterplan row
  still holds `<field> <the masterplan> <its row>`.
- On the masterplan `ready --json`, `assign` and `status <row> <status>` work as on a parallel plan. Its rows are no
  steps: not sized, no step file on `next`; `prompt <row>` and `uat` refuse and name the row's plan.
