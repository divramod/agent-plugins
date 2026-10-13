---
name: s
description: Print the state of every worktree slot of the repository as one table on demand, by script — `WT | Plan | Steps | State | Waits for`, one row per slot (numbered slots by number, named slots, `main` last) and a line under it with the default branch's head, the merge queue and the open CI runs. The row of the checkout the session runs in is marked bold (`**01**`), a foreman's servants stand under its row (`↳ 31`). No model call, read-only, for every session in every repository (farmer, foreman, servant). Use when the user says /s, "state", "what is every worktree doing" or "show the worktrees". `/s h` shows help.
---

# s

`S=<skill-dir>/scripts`. Read-only, no model work: a script reads git, the agents, the merge queue, the open CI runs and the
plans, and prints the table.

| Call | Does |
|---|---|
| `/s` | the table: `python3 $S/state.py` |
| `/s --json` | the raw rows with their five `cells`, `own` and `foreman` |
| `... --repo <path>` | another repository (its table, no row marked) |
| `/s h` | print this table and stop |

## Run

`python3 $S/state.py [--json] [--repo <path>]`. Print its output as it is; add at most one sentence per slot only for what
code cannot know, and nothing else.

The columns are the slot (WT), its plan (Plan), the plan's steps done of all (Steps), what the slot is doing (State) and
what it waits for (Waits for). The own row (the checkout you run in) has its WT in bold; a slot whose `plans/LEAD` names a
foreman stands under that foreman's row as `↳ <slot>` (a foreman runs a plan, a servant works in a worktree a foreman
created). A fact that cannot be known is left out, never an error: no `hal2-cli-agents`, `hal2-cli-git`, `gh`, plan skill or
farmer skill beside this one only takes its facts away. Cell phrases and degrading: [reference](reference.md).
