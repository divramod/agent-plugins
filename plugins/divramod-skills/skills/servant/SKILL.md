---
name: servant
description: The servant (German Knecht), a session in a field 30-99 that a foreman created — it does one part of the foreman's plan, reports back to the foreman and never lands. `/servant` prints the servant's effective duties (the skill's, overridden and extended by the repository's `roles/servant/ROLE.md`) and works by them. Use when the user says /servant, "servant", "Knecht", "what does a servant do", or a session in a field holding `plans/LEAD` needs its role. `/servant h` shows help.
---

# servant

A servant is a session in a field 30-99 that a foreman created: it does a part of the foreman's plan, reports back to
it and never lands (`~/.claude/GLOSSARY.md`, entry **servant**). Its field holds the foreman's marker `plans/LEAD`
(`<foreman's field> <plan> <step>`; a whole sub-plan of a schema 2 plan: `<field> <plan> <NN-slug>`), which says it is a servant's, not the number; how it works is the [plan](../plan/SKILL.md) skill's "Work as a servant".

| Call | Does |
|---|---|
| `/servant` | print the effective duties (`python3 ../farmer/scripts/role_duties.py servant --repo .`), then work by them |
| `/servant duties` | only print them (`--json` for every field) |
| `/servant h` | print this table and stop |

The effective duties are this skill's list below, overridden by id and extended by a `### <id>` under `## Duties` in
the repository's `roles/servant/ROLE.md` ([role_duties.py](../farmer/scripts/role_duties.py), hal2 plan 0360 D27).

## Duties

### one-step
Do the steps `plans/LEAD` names (`hal2-cli-plans servant show --json`), each in a hand (`plan.py prompt <n> --plan
<its plan>`), only in this field (hal2 record
[subservants-in-slots-30-99](https://github.com/divramod/hal2/blob/main/.adr/subservants-in-slots-30-99.md)); never
write the marker (the foreman's `servant assign` does), never edit `plan.md`. Mark a step with `hal2-cli-plans servant
status <n> "in progress"` when you start it and `done` once its done-when passed; no other state, no other step. When LEAD
names a sub-plan (`NN-slug`), the whole sub-plan is yours: each of its steps in a hand (`plan.py prompt <NN>.<step>`),
marked by `plan.py status <NN>.<step> next|running|blocked|done`; nothing else of the plan is yours to write.

### depends
A servant declares no dependency: a wait it finds goes to the foreman in the report, who runs `hal2-cli-plans depends add`.

### report
Commit the step, write its `## Notes` in `steps/<n>.md` (your memory; the foreman's `servant finish` refuses a step
without it) and report to the foreman (`SendMessage` to its field's session): what is done, the commits, what could not
be verified. A sub-plan's servant reports once, after its last step, pushed:
`sub-plan <NN-slug> done: field <NN> at <sha>; done-when: <last output line>`. Then wait: the foreman merges, checks,
marks it and finishes this field (`servant finish`).

### never-land
A servant never lands, hitches or smuggles: `plan.py`, merge-to-main's guard and hal2's merge queue refuse it. Its
work reaches the barn in the foreman's harvest.
