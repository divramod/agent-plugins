---
name: get-state
description: The state on demand, by script, no model call: `/s` detects the session's role from its checkout (farmer, foreman, servant, steward, tollman, mayor, lord, pope) and opens that role's page as HTML in the browser, printing one line with the page's path. Farmer = five sortable, filterable tables (merge queue, fields, free, open questions, decisions in force), foreman and servant = their plan's steps, steward = next actions (daybook chores, unfinished plans, open UATs), tollman = the toll gate (the merge queue), mayor, lord, pope = their goals or a clear empty state. `--text` prints the old table instead: `WT | Plan | Steps | State | Waits for`, one row per worktree and a line under it with the default branch's head, the merge queue and the open CI runs. Read-only, for every session in every repository. Use when the user says /s, "state", "what is every worktree doing", "show the worktrees" or "show my goals". `/s h` shows help.
---

# get-state (alias s)

`S=<skill-dir>/scripts`. Read-only, no model work: a script reads git, the agents, the merge queue, the open CI runs, the
plans and the daybook, writes the role's page and opens it. Views, roles and the page: [reference](reference.md).

| Call | Does |
|---|---|
| `/get-state` | the role's page, opened in the browser from the local server (`http://127.0.0.1:47369/?repo=...`; the file when no server starts); one line, its URL or path: `python3 $S/state.py` |
| `/get-state --role <role>` | another role's page (the only way to lord and pope from a repository checkout) |
| `/get-state --no-open` | write the page as a file, open nothing, start no server (a headless box, a test) |
| `/get-state --text` | the table: `WT | Plan | Steps | State | Waits for` and the line under it |
| `/get-state --json` | the raw rows with their five `cells`, `description`, `own` and `foreman` |
| `... --repo <path>` | another repository (its role from that checkout, no row marked) |
| `/get-state h` | print this table and stop |

## Run

`python3 $S/state.py [--role <role>] [--no-open | --text | --json] [--repo <path>]`. Print its output as it is, the page's
path or the table; add nothing. With `--text` add at most one sentence per worktree, only for what code cannot know.

The views by role: farmer = the tables queue (with the mode line), fields (filters by progress, sorted by done %), free, questions (open by default) and decisions (in force by default), each with git numbers, column menu and refresh button; foreman, servant = the plan's
step table, progress, next step, open questions; steward = open chores, unfinished plans, open UATs; tollman = mode,
holder, trains, ready wagons, waiters, open land runs; mayor, lord, pope = the goals files or where they would live. An
unknown role gets today's table as its page. A fact that cannot be known is left out, never an error: no
`hal2-cli-agents`, `hal2-cli-git`, `gh`, plan, daybook or farmer skill only takes its facts away.

The server: one per user on port 47369 (`HAL2_STATE_PORT` overrides), reused or started detached by `/s`, exits after 30
minutes idle. It renders a page fresh per request, serves a table's refresh and keeps the tables' settings across
browsers; loopback only. Details: [reference](reference.md).
