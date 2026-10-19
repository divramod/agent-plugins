---
name: workqueue-check
description: Check hal2's work queue for drift — runs `scripts/check.py`, which reads `hal2-cli-workqueue stats --json` and `report --json` for a window (default 24 h) against the window before and `workqueue-bench compare --json` against the stored baseline, and prints ranked findings (a class or command head whose mean wall or CPU per run rose, new hung, orphan or Docker-stuck runs, benchmarks slower than baseline); the skill only judges: names the likely cause and proposes the fix as a shot or one farmer brief. Read-only: it never changes code and never runs a benchmark (benchmarks need a quiet Mac and the user's go). Use when the user says /workqueue-check, "is the work queue slower", "workqueue drift", "what got slower" or "check the shims' cost". `/workqueue-check h` shows help.
---

# workqueue-check

Thin by the record deterministic-first: the script gathers and ranks as code; you judge. `C=scripts/check.py` of this
skill.

| Call | Does |
|---|---|
| `/workqueue-check [<window>]` | `python3 $C --json [--since <window>]` (window `30m`, `24h`, `7d`; default 24h), then judge |
| `/workqueue-check --no-bench` | the same without the benchmarks against their baseline |
| `/workqueue-check h` | print this table and stop |

Exit 0 no finding, 1 findings, 2 bad window, 3 `hal2-cli-workqueue` missing or failing: say that it is not installed
yet (or the message) and stop; an empty journal or a missing baseline is a note, not an error. The window before is
derived (the CLI has no `--until`): `--since 2W` minus `--since W`; peak memory is compared only when the earlier
window held the maximum, else the note says it is skipped.

## Judge

Read the findings; do not recompute them. For each of the top ones: a class (`build`, `test`, ...) or head
(`class:cargo nextest`) whose mean wall or CPU rose names the field of the cost: `hal2-cli-workqueue report --since
<window> --sort wall|cpu|peak --top 5` lists its costliest runs with their children. Say the likely cause (a heavier
step, a new head, a hung or orphaned tree, a slot too few, the shim itself when a benchmark `shim-overhead` or
`run-overhead` is slower) and propose one fix.

- Write the fix as a shot (`/create-shot`) or one farmer brief; never edit code here.
- Never run `workqueue-bench run` or `baseline` yourself: benchmarks need a quiet Mac and the user's go. A slower
  benchmark is reported with the command for the user (`python3 code/python/scripts/workqueue-bench/main.py run`).
- No baseline yet: say so once; taking it is the user's step.
