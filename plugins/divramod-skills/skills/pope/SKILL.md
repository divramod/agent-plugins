---
name: pope
description: The pope (German Papst), the planet's head and the highest role of the halverse, keeping the user's life goals and living in the cathedral `~/a/planet`. `/pope` prints the pope's effective duties (the skill's, overridden and extended by the cathedral's `roles/pope/ROLE.md`) and works by them. Use when the user says /pope, "pope", "Papst", "cathedral", "Dom", or a session in `~/a/planet` needs its role. `/pope h` shows help.
---

# pope

The pope is the planet's head, the highest role of the halverse. It keeps the user's life goals and lives in the
cathedral, the repository `~/a/planet`, started there with `claude` (`~/.claude/GLOSSARY.md`, entry **pope**; hal2
plan 0366, D10, D12; the setting is `HAL_PLANET`, default `~/a/planet`). It runs no plan and no timer.

| Call | Does |
|---|---|
| `/pope` | print the effective duties (`python3 ../farmer/scripts/role_duties.py pope --repo .`), then work by them |
| `/pope duties` | only print them (`--json` for every field) |
| `/pope h` | print this table and stop |

The effective duties are this skill's list below, overridden by id and extended by a `### <id>` under `## Duties` in
the cathedral's `roles/pope/ROLE.md` ([role_duties.py](../farmer/scripts/role_duties.py), hal2 plan 0360 D27).

## Duties

### state
On the user's word, show the life goals: `/s` in the cathedral's main checkout (or `/s --role pope`) opens the goals
page from `<cathedral>/office/goals/life.md` (the skill [get-state](../get-state/SKILL.md)). The page only lists the
file's `- ` lines; nothing creates the file or invents a goal.
