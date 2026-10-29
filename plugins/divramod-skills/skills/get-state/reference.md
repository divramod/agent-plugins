# The state call

`/s` writes the role's page (below) and prints its path; `--text` prints the table, which the rest of this file
documents from "The table (`--text`)" on.

## Roles

`role.py` detects the role from the checkout of `--repo` (default the current folder), `--role <role>` overrides it
(plan 0366 D2, D11). `farmer-<repo>` farmer, `tollman-<repo>` tollman, a field named `00`-`99` servant when it holds `plans/LEAD` (the foreman's marker), else foreman (plan 0383 D16),
a main checkout steward. `PLACES` maps the upper roles to their place's main checkout: mayor `~/a/village`
(`HAL_VILLAGE`), lord `~/a/city` (`HAL_CITY`), pope `~/a/planet` (`HAL_PLANET`); the main checkout of a place is that
role, so lord and pope are detected there and otherwise only by `--role`. Anything else is `unknown`: today's table as
the page.

## Views

`views.py` maps each role to `view_<role>.py`: `view(data, ctx) -> (title, sections)`, pure, no model. The title is
`<repo> · <role> [<field>]`; the line under the table (head, queue, runs) is the page's meta line.

| Role | Sections and empty states |
|---|---|
| farmer | five grids (`grid` kind): **queue** (Place, mode line `Merge queue mode: production\|smuggle since <at> by <who>` above it, queue order), **fields** (filters All / done / one step left / nearly done / the rest, free ones apart; sorted by done % descending), **free**, **questions** (filters Open (default) / Answered / All; Q, Question, Options, Answer, State) and **decisions** (In force (default, in-force and promoted) / All; D, Date, Who, State, Decision, hidden Words and Why; sorted by date descending). Shared columns: Field, Plan (`0042 name`), Steps, Done % (hidden), What it brings in, State, then the statusline numbers ↓ behind, ↑ ahead, s stash, ? untracked, + added, ~ modified, - deleted; no numbered fields: each grid shows its own empty text |
| foreman, servant | the plan's title and description, Progress (`bar` and `3 of 8 steps done`), the Steps table (own plan row marked), Next step with its done-when, Open questions, and for a farm with a plan store a Plan store section (its home; sync on or off and why, a locked gpg agent, conflicts); the plan comes from `hal2-cli-plans show/questions list/home/state status --json` (either home, plan 0409 step 6), the files only without the CLI; a servant shows its foreman's plan (`plans/LEAD`), "servant of <field>, working step <n>"; no plan: "No plan in this field." |
| steward | Daybook (today's day file, else the newest earlier: open chores of Today and Later), Unfinished plans (steps done < total), Open UAT checks (failures first, 15 plans at most); each source missing says so |
| tollman | Mode, Merge queue: Holder, Trains, Ready wagons, Waiting in order, Open land runs; nothing queued and no run: "The toll gate is empty."; unknown tools say so |
| mayor, lord, pope | the role's goals file under its place's `office/goals/` (`1-year.md`, `3-5-years.md`, `life.md`): the file's `- ` lines (nesting kept) and a Source section (path, mtime); no file: "No goals written yet. They would live in <path>"; nothing creates the file |

## The page

`page.py` renders one self-contained HTML file: inline CSS (system fonts, light and dark by `prefers-color-scheme`),
no network; every value goes through `html.escape`. A section is a dict with a `heading` and a body: a table
(`columns`, `rows`, `marked` row indexes shown bold), `text`, `items` or `empty` (the line shown for an empty table or
list, default "Nothing here."); `bar: [done, total]` adds a progress bar above the body (CSS width, clamped, a bad total
ignored). The file is runtime state, never in a checkout: `${XDG_STATE_HOME:-~/.local/state}/hal2/get-state/
<repo>-<checkout>-<role>.html` (Windows `%LOCALAPPDATA%\hal2\get-state\`); `--no-open` only writes it. `--json` rows
also carry `description`, the plan.md front matter's (null without).

The `grid` kind (`grid.py`): `{"kind": "grid", "id", "heading", "note"?, "columns": [{"key","label","type":"text|num",
"hidden"?}], "rows", "filters"?: [{"key","label","match"}], "filter"?, "sort"?, "empty"?, "static"?}`. The static table
is always in the page (it works without script) and a JSON island carries the same data. Script (`table.js`, `table.css`)
is inlined only on a page with a grid; it sorts by a header click (cycle asc, desc, off), filters, reorders and hides
columns (column menu), resizes by the header grip and has "Fit widths" and "Reset all". An island over 32 KB
(`PACK_OVER`) is gzipped and base64 coded (`application/gzip+base64`, read by the browser's `DecompressionStream`);
a section with `"static": false` (the decisions) shows a "shown by the page's script" line instead of its rows.
Settings per table id (order, hidden, sort, filter, widths) live in the browser's localStorage and, on a served page, in
the server's `settings.json`.

The server (`serve.py`, launched by `serve_launch.py`): `/s` reuses the one on `127.0.0.1:47369` (`HAL2_STATE_PORT`
overrides) or starts it detached (log `serve.log` in the state dir), prints and opens `http://127.0.0.1:47369/?repo=...`
(`role` only with `--role`), else falls back to the file. It exits after 30 minutes idle and is restarted when an update
changes the scripts (`/health` carries a digest). Routes: `GET /` the page, rendered fresh; `GET /table/<id>?repo=&role=`
one grid's JSON (the refresh button; ids queue, fields, free, questions, decisions; 404 for another role);
`GET /health`; `GET|PUT /settings` (`{<id>: settings|null}` merged). Loopback only: Host, Origin and `Sec-Fetch-Site`
are checked. `--no-open`, `--text` and `--json` start no server.

Facts are collected by need: `collect(..., table_facts=, ledgers=)`. The table facts (`last_commit_age`, `uncommitted`,
`ahead`, three git calls per field) are read only for the five-cell fallback table (`needs_table_facts`), else null. The
farmer's page also reads the ledgers (`page_facts`): questions through `hal2-cli-plans questions list --all --json`
(the stored-format parser as fallback), decisions through the parser, one read per plan (the field running it, else the
lowest numbered servant's copy), put in a top-level `questions` key for the view; `--json` and `--text` do not read them.

`--json` also has, per row, `git` (`behind`, `ahead`, `stash`, `untracked`, `added`, `modified`, `deleted`, against the
default branch; null if unknown) and `done_pct` (0-100, null without steps); top-level `queue` (tickets in queue order,
holder first, `wt` joins with `rows[].wt`) and `mode` (`mode`, `by`, `at`, `since` = `at`, `why`; null if unknown).

## Modules

`state.py` (collect, CLI), `role.py`, `page.py` with `grid.py`, `table.js`, `table.css`, `serve.py` with `serve_launch.py`, `views.py` (registry, fallback table, titles), `view_farmer.py` with `ledger_sources.py` (questions, decisions),
`view_foreman.py` with `plan_cli.py` (the plan through `hal2-cli-plans --json`), `view_goals.py`, `view_steward.py` with `steward_sources.py` (daybook, UATs), `view_tollman.py` with
`tollman_sources.py` (raw queue), `state_sources.py`, `state_table.py`, `farmer_link.py`; tests `test_*.py` beside them.

## The table (`--text`)

The table: `scripts/state.py` collects, `state_sources.py` (every outside read), `state_table.py` (cells, table, line)
and `farmer_link.py` (the farmer skill's helpers, imported by path from `../../farmer/scripts`, each optional); decisions
in hal2's plan 0268. One row per worktree: numbered worktrees by number, named worktrees (`farmer-<repo>`) by name, the main
checkout last as `main`; dot checkouts and prunable worktrees are no rows. Cells are fixed phrases joined by `; `, an
unknown fact left out, a `|` escaped.

| Column | Content |
|---|---|
| WT | the worktree's folder name; **bold** for the checkout the script runs in (`**01**`); `↳ 31` for a servant, directly under its foreman's row |
| Plan | `<NNNN> <slug with spaces>` (also when the file holds a path `plans/<it>`, with or without `/` or `/plan.md`), a shot or task name as the `CURRENT_PLAN` pointer has it, `free` when empty |
| Steps | `<done> of <total>` from the plan skill's `plan.py`, empty without a plan |
| State | in order: `paused (<by>: <why>)` for a paused field (`hal2-cli-git worktree paused --json`, hal2 plan 0458; an older CLI shows none); `busy`/`idle`/`no session`; `holds the merge queue` or `waits in the queue at <n>`; `check run queued`/`check run running`/`land run running`; `<n> uncommitted`; `<n> not on <default>` (main: `not pushed`); `last commit <5m\|3h\|2d>` |
| Waits for | in order: `the queue`, `the run`, `the farmer's answer` (an open ask), `ack <id>` (an instruction unacked for under 12 h), `Q<n>` per open question of the plan (three or more in a row collapse to a range, `Q5-Q15`; two stay `Q19; Q20`) |

The marks: the own row is the checkout of the folder the script is started in; with `--repo <path>` of another
repository no row is marked. A worktree whose `plans/LEAD` names a worktree of the table is a servant of that foreman (a foreman
runs a plan, a servant works in a worktree a foreman created): its row stands under the foreman's row, the servants of
one foreman by number; all other rows keep their order. The farmer's worktree marks its own row like any other. `--json` rows
carry `own` (bool) and `foreman` (the foreman's worktree or null).

The line under the table: `<default>: <sha> <age> ago <subject cut at 60>; queue: <holder> holds; waiting: <worktrees>|empty; open CI
runs: <n> (<worktrees>)|none`; in the queue's smuggle mode `mode: smuggle since <at> (by <who>)` stands before `queue:` (plan
0360 D75; `mode` in --json, production shows nothing). Degrading, never an error: without `hal2-cli-agents` the agent phrase is missing, without
`hal2-cli-git` the queue, without `gh` the run phrases and the CI part of the line, without the plan skill beside this
one the Steps cell, without the farmer skill beside this one the ask and ack waits (and the farmer's log), without a farmer
log the same. Tools time out after 10 s. A run takes 2-8 s (`gh` is the slow part).
