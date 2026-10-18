---
name: daybook
description: The farm's daybook, a daily list of what the user does not want to forget there — one file per day (`<farm>/daybook/<YYYY-MM-DD>.md`, jobsearch's `daily/`), open chores carried into the next day, with the farm's unfinished plans and its watches (lookouts). `/daybook` shows today's, `/daybook jot <text>` adds a chore, `/daybook tick <n|text>` ticks one off, `/daybook watch add|rm|list` manages the watches, `/daybook plans` shows only the plans. A stdlib script (`scripts/daybook.py`) does all of it; the model only judges which chore is meant and runs due watches. Works in every farm, also from a worktree (it writes the main checkout's daybook). Alias `/daily`. Use when the user says /daybook, /daily, "daybook", "daily", "jot", "tick off", "watch", "lookout", "Tagebuch", "what is on today" or "don't let me forget". `/daybook h` shows help.
---

# daybook

`S=<skill-dir>/scripts`, `D="python3 $S/daybook.py"`. The script does every file edit; the format is in [README.md](README.md).

| Call | Does |
|---|---|
| `/daybook` | `$D show`: make today's file (carry-over), print the open chores numbered, the plans, the watches |
| `/daybook jot <text>` | `$D jot "<text>"` (`--later` puts it under Later) |
| `/daybook tick <n\|text>` | `$D tick <n\|"text">`: the number of `show`, or text matching exactly one open item |
| `/daybook move <n\|text> today\|later` | `$D move ...` |
| `/daybook watch list` | `$D watch list`: the watches with `due` |
| `/daybook watch add <id> ...` | `$D watch add <id> --title T --cron C --prompt P [--every E] [--until U]`, then step 2 below |
| `/daybook watch rm <id>` | `$D watch rm <id>`, then `CronDelete` its job |
| `/daybook plans` | `$D plans`: only the plan lines |
| `... --farm <dir>` | another farm; `--date YYYY-MM-DD` another day, `--json` data |
| `/daybook h` | print this table and stop |

A watch a script can check runs in lookout (`/lookout`, the lookout skill: 0 tokens while quiet, plan 0311); the
daybook's own CronCreate watches are for prompt-only checks.

## Run

1. Run the call. Print its output as it is; a ref matching several items (exit 2) lists the candidates: ask the user
   which (Q form), never guess. Exit 3: not a farm or folder not writable; 4: a broken file, name it; 5: the lock was
   busy, run again.
2. After `show` and `watch add|rm`: compare `$D watch list` with `CronList` (a job belongs to a watch when its prompt
   starts `Watch <id>`) and `CronCreate` each active watch without a job, recurring, with its `cron` and `prompt`.
3. For each watch with `due: true` run its prompt (read-only), put the result in one line and call
   `$D watch ran <id> --result "<line>"`; when the watch is settled, `$D tick` its item (that ends it).
4. Jot what the conversation settled as a chore only when the user asks; otherwise `jot` exactly the words given.

Never edit the day file by hand, never commit it: the script keeps `daybook/` out of git. Reply with the script's
output and one line of what you did.
