---
name: mayor
description: The mayor (German Bürgermeister), the village's head one level above the farms (the village is the laptop, every farm on it), living in the town hall `~/a/village` — it stops all work in every farm and sends everyone back to work. `/mayor` prints the mayor's effective duties (the skill's, overridden and extended by the town hall's `roles/mayor/ROLE.md`) and works by them. Use when the user says /mayor, "mayor", "Bürgermeister", "stop every farm", "everyone back to work", or a session in `~/a/village` needs its role. `/mayor h` shows help.
---

# mayor

The mayor is the village's head, one level above the farms: the village is the laptop with every farm on it, the
mayor lives in the town hall, the repository `~/a/village`, started there with `claude` (`~/.claude/GLOSSARY.md`,
entries **mayor** and **town hall**). It runs no plan and no timer.

| Call | Does |
|---|---|
| `/mayor` | print the effective duties (`python3 ../farmer/scripts/role_duties.py mayor --repo .`), then work by them |
| `/mayor duties` | only print them (`--json` for every field) |
| `/mayor h` | print this table and stop |

The effective duties are this skill's list below, overridden by id and extended by a `### <id>` under `## Duties` in
the town hall's `roles/mayor/ROLE.md` ([role_duties.py](../farmer/scripts/role_duties.py), hal2 plan 0360 D27).

## Duties

### stop-all
On the user's word, stop the work of every agent session on the machine, in every farm, except those the user
names: the skill [stop-all-agent-work](../stop-all-agent-work/SKILL.md) (`/stop-all-agent-work [keep <who>...]`); for the user's own call or need of full compute, one script call without a
question: [important-interrupt](../important-interrupt/SKILL.md) (`/important-interrupt`, `done` undoes it).

### continue-all
On the user's word, send everyone back to work and undo the machine's quieting: the skill
[continue-all-agent-work](../continue-all-agent-work/SKILL.md) (`/continue-all-agent-work`).


### state
On the user's word, show the goals of the next year: `/s` in the town hall's main checkout (or `/s --role mayor`)
opens the goals page from `<town hall>/office/goals/1-year.md` (the skill [get-state](../get-state/SKILL.md)). The
page only lists the file's `- ` lines; nothing creates the file or invents a goal.
