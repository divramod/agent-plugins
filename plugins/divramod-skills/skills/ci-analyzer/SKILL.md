---
name: ci-analyzer
description: Analyse hal2's CI for waste and bottlenecks — runs hal2's `ci-analyzer` unit (`code/python/scripts/ci-analyzer/main.py`) over the last N workflow runs (default 40), whose sixteen deterministic checks (empty runs, ugly job names, queue wait, critical path, cancelled runs, repeated checks, cache misses, flaky jobs, idle runners, Mac host load, slow steps, disk, token cost, green markers that missed, setup overhead, unequal lanes of one stage) rank findings by wall time, runner minutes and money; the skill only judges: merges duplicates, ranks the top bottlenecks with run and job ids and minutes, and turns the fixes into shots or one farmer brief. Read-only against GitHub, it never changes a workflow and never reruns, cancels or dispatches. Use when the user says /ci-analyzer, "analyse CI", "CI bottlenecks", "why is CI slow", "CI cost" or "where does CI waste minutes". `/ci-analyzer h` shows help.
---

# ci-analyzer

Thin by the record deterministic-first: the unit fetches, checks and ranks as code; you judge. `M=<hal2 checkout>/code/python/scripts/ci-analyzer/main.py`:
the current repository when it is hal2, else `~/a/hal2`. Read-only, so any worktree's copy will do.

| Call | Does |
|---|---|
| `/ci-analyzer [<N>]` | `python3 $M report --runs <N> --json` (N default 40), then judge (below) |
| `/ci-analyzer checks <ids>` | `python3 $M checks --only <ids> --json` (ids comma separated, e.g. `1,2`), then judge those findings |
| `/ci-analyzer fetch` | `python3 $M fetch` (add `--runs N`, `--run <id>` for one run): fill the cache, report the count |
| `/ci-analyzer h` | print this table and stop (`python3 $M h` shows the unit's own help) |

Subcommands of `main.py`: `fetch`, `checks`, `report`, `h`/`help`. Options (all subcommands): `--runs N`, `--json`,
`--offline` (cache only, no `gh` call), `--state <dir>`, `--repo <owner/name>`, `--workflow <file.yml>` (repeatable);
`fetch --run <id>` (repeatable); `checks --only <ids>`. Use `--offline` for a second look at the same runs. A missing
`gh` or a failed call: report the message and stop.

## The checks

For the numbers of one finished run (which lane, how long, which job) run `main.py lanes <run id>` (`--json` for data):
each lane's stage, OS, runner, span and busy minutes with its jobs, and per stage and OS the gap and the job to move.
Use it to check a c16 finding or before proposing a move; quote its numbers, do not recompute them.

c01 empty-runs (runs that did nothing), c02 job-names (names breaking the runner-names rule), c03 queue-wait (time a job
waited for a runner), c04 critical-path (the jobs that set the wall time), c05 cancelled (cancelled or superseded runs),
c06 repeats (identical checks run again), c07 cache-misses, c08 flaky (jobs red then green), c09 idle-runners (idle or
unparked runners), c10 mac-host-load, c11 slow-steps (against `budgets.toml`), c12 disk (disk and cleanup), c13
token-cost (a proxy for the agents' token cost), c14 green-markers (a job that ran although its marker should
have hit; `--keys` names the input that moved the key), c15 setup-overhead ("Set up job" over 20 s; `--logs` names the
action downloads), c16 stage-balance (the lanes of one stage and OS busy far unequal, e.g. e2-mac-host-b 22 min beside an idle
e4-mac-host-c; names the job whose move evens them; `--lane-gap`, `--lane-solo`). Match them with `checks/c<NN>_<slug>.py` in the unit.

## Judge

Read the findings; do not recompute them. Merge duplicates (one cause, several checks), then rank the top bottlenecks
by the unit's order: wall time, runner minutes, money. For each give the evidence (run and job ids, minutes), the
cause in one line and one proposed fix. Mark what the unit could not see.

Fixes are only proposed: one shot each (`/create-shot`, the CI shotfile, else a new one named `ci`) or, for several
related ones, one brief to the farmer (SendMessage to `farmer-<repo>`, the newest from ListAgents). Never edit a
workflow, never rerun, cancel or dispatch a run. End with the table of bottlenecks and the shots or brief made.
