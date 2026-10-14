# The state call

`/s` runs `scripts/state.py` (collects), `state_sources.py` (every outside read), `state_table.py` (cells, table, line)
and `farmer_link.py` (the farmer skill's helpers, imported by path from `../../farmer/scripts`, each optional); decisions
in hal2's plan 0268. One row per worktree: numbered worktrees by number, named worktrees (`farmer-<repo>`) by name, the main
checkout last as `main`; dot checkouts and prunable worktrees are no rows. Cells are fixed phrases joined by `; `, an
unknown fact left out, a `|` escaped.

| Column | Content |
|---|---|
| WT | the worktree's folder name; **bold** for the checkout the script runs in (`**01**`); `↳ 31` for a servant, directly under its foreman's row |
| Plan | `<NNNN> <slug with spaces>` (also when the file holds a path `plans/<it>`, with or without `/` or `/plan.md`), a shot or task name as `plans/CURRENT_PLAN` has it, `free` when empty |
| Steps | `<done> of <total>` from the plan skill's `plan.py`, empty without a plan |
| State | in order: `busy`/`idle`/`no session`; `holds the merge queue` or `waits in the queue at <n>`; `check run queued`/`check run running`/`land run running`; `<n> uncommitted`; `<n> not on <default>` (main: `not pushed`); `last commit <5m\|3h\|2d>` |
| Waits for | in order: `the queue`, `the run`, `the farmer's answer` (an open ask), `ack <id>` (an instruction unacked for under 12 h), `Q<n>` per open question of the plan (three or more in a row collapse to a range, `Q5-Q15`; two stay `Q19; Q20`) |

The marks: the own row is the checkout of the folder the script is started in; with `--repo <path>` of another
repository no row is marked. A worktree whose `plans/LEAD` names a worktree of the table is a servant of that foreman (a foreman
runs a plan, a servant works in a worktree a foreman created): its row stands under the foreman's row, the servants of
one foreman by number; all other rows keep their order. The farmer's worktree marks its own row like any other. `--json` rows
carry `own` (bool) and `foreman` (the foreman's worktree or null).

The line under the table: `<default>: <sha> <age> ago <subject cut at 60>; queue: <holder> holds; waiting: <worktrees>|empty; open CI
runs: <n> (<worktrees>)|none`. Degrading, never an error: without `hal2-cli-agents` the agent phrase is missing, without
`hal2-cli-git` the queue, without `gh` the run phrases and the CI part of the line, without the plan skill beside this
one the Steps cell, without the farmer skill beside this one the ask and ack waits (and the farmer's log), without a farmer
log the same. Tools time out after 10 s. A run takes 2-8 s (`gh` is the slow part).
