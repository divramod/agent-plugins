---
name: lord
description: The lord (German Burgherr), the city's head one level above the mayor (the city is the network of the user's machines, every village in it), keeping the user's goals for the next 3-5 years and living in the castle `~/a/city`. `/lord` prints the lord's effective duties (the skill's, overridden and extended by the castle's `roles/lord/ROLE.md`) and works by them. Use when the user says /lord, "lord", "Burgherr", "castle", "Burg", or a session in `~/a/city` needs its role. `/lord h` shows help.
---

# lord

The lord is the city's head, one level above the mayor: the city is the network of the user's machines with every
village in it. It keeps the user's goals for the next 3-5 years and lives in the castle, the repository `~/a/city`,
started there with `claude` (`~/.claude/GLOSSARY.md`, entry **lord**; hal2 plan 0366, D10, D12; the setting is
`HAL_CITY`, default `~/a/city`). It runs no plan and no timer.

| Call | Does |
|---|---|
| `/lord` | print the effective duties (`python3 ../farmer/scripts/role_duties.py lord --repo .`), then work by them |
| `/lord duties` | only print them (`--json` for every field) |
| `/lord h` | print this table and stop |

The effective duties are this skill's list below, overridden by id and extended by a `### <id>` under `## Duties` in
the castle's `roles/lord/ROLE.md` ([role_duties.py](../farmer/scripts/role_duties.py), hal2 plan 0360 D27).

## Duties

### state
On the user's word, show the goals of the next 3 to 5 years: `/s` in the castle's main checkout (or `/s --role lord`)
opens the goals page from `<castle>/office/goals/3-5-years.md` (the skill [get-state](../get-state/SKILL.md)). The
page only lists the file's `- ` lines; nothing creates the file or invents a goal.
