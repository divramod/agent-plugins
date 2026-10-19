---
name: servant
description: The servant (German Knecht), a session in a field 30-99 that a foreman created — it does one part of the foreman's plan, reports back to the foreman and never lands. `/servant` prints the servant's effective duties (the skill's, overridden and extended by the repository's `roles/servant/ROLE.md`) and works by them. Use when the user says /servant, "servant", "Knecht", "what does a servant do", or a session in a field holding `plans/LEAD` needs its role. `/servant h` shows help.
---

# servant

A servant is a session in a field 30-99 that a foreman created: it does a part of the foreman's plan, reports back to
it and never lands (`~/.claude/GLOSSARY.md`, entry **servant**). Its field holds the foreman's marker `plans/LEAD`
(`<foreman's field> <plan> <step>`), which says it is a servant's, not the number; how it works is the [plan](../plan/SKILL.md) skill's "Work as a servant".

| Call | Does |
|---|---|
| `/servant` | print the effective duties (`python3 ../farmer/scripts/role_duties.py servant --repo .`), then work by them |
| `/servant duties` | only print them (`--json` for every field) |
| `/servant h` | print this table and stop |

The effective duties are this skill's list below, overridden by id and extended by a `### <id>` under `## Duties` in
the repository's `roles/servant/ROLE.md` ([role_duties.py](../farmer/scripts/role_duties.py), hal2 plan 0360 D27).

## Duties

### one-step
Do the step `plans/LEAD` names, in a hand (`plan.py prompt <n> --plan <its plan>`), only in this field (hal2 record
[subservants-in-slots-30-99](https://github.com/divramod/hal2/blob/main/.adr/subservants-in-slots-30-99.md)); never
delete the marker, never edit `plan.md` or mark a step.

### report
Commit the step, write its `## Notes` and report to the foreman (`SendMessage` to its field's session): what is done,
the commits, what could not be verified. The foreman merges, checks, marks it and removes this field.

### never-land
A servant never lands, hitches or smuggles: `plan.py`, merge-to-main's guard and hal2's merge queue refuse it. Its
work reaches the barn in the foreman's harvest.
