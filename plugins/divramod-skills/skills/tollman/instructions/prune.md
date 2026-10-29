# Woken for prune (prune)

The tick does the duty itself (`prune.py`, hal2 plan 0143; the farmer's until plan 0360 step 7, D8, D30; since plan 0377
step 7, D12 it asks [/prune](../../prune/SKILL.md), which owns the proof, the order and the deleting): every round it
runs `prune.py plan --json` of /prune (its facts and the planned actions per job) and starts, detached, one
`hal2-cli-runs exec --workflow prune --slot tollman-<repo> -- prune.py run --field NN...` when anything is due (without
`hal2-cli-runs`: `prune.py run` alone; one run at a time, its pid in `prune-run.json`, its output in `prune-run.log` of
your state folder; the run shows on the run page as a run of the workflow `prune`). Nothing of it needs you unless it
failed or a car of a landed train is stuck. A field is free when nothing in it is unsaved (/prune's proof, the
global record never-delete-unsaved-work): no commit (its branch or a side branch `NN-*`) that origin's default branch
lacks, no change, no live `CURRENT_PLAN` pointer, no merge queue ticket or boss pause, no busy agent, no session active in
the last 30 minutes (10-99), no build running in it and no open question to the user. Main, the role fields
(`farmer-<repo>`, `tollman-<repo>`, ...) and other names are never touched.

- **00-09**: mucked out once per landing (keyed on HEAD), never removed.
- **10-99**, one per round, the cars of the last landed train first (/prune's order): the idle session stopped by signal,
  then `hal2-cli-git worktree remove NN --remote`, a removal never under a timeout, a half-removed field resumed.
- **A stale pointer** (the `CURRENT_PLAN` pointer naming a finished or missing plan on a field with nothing unsaved and no
  session) is cleared, then the proof runs again.
- **While the disk is short** (/prune's threshold, `.hal/prune.toml`) the build folders (`trim` paths) of session-less
  fields and then of idle live ones are deleted until the goal.
- **After the barn** (`barn.py`, plan 0360 step 7): a car 00-09 of the last landed train that is free and mucked out
  (the muck out of its HEAD was started) has its resting session cleared once (`hal2-cli-agents clear-and-continue
  --pane <pane> --without-plan --prompt /mfm --detach`, key `barn-clear:<NN>:<HEAD>`): its foreman ends its turn after
  the report and never clears itself.
- **Servants' fields** (`plans/LEAD`, the foreman's marker): removed once their commits are in `origin/<foreman>`; else
  /prune's report says "ask the foreman of field FF about field NN" (the duty does not ask; `/prune` does, run by the
  user or you).
- **Disk**: every 6 hours a log line with the free disk and the 5 biggest fields (from /prune's facts, in the round
  summary), a notice for the user under 100 GB free.

| Wake | What you do |
|---|---|
| `failed` | The duty could not ask /prune ("/prune could not be asked") or its run could not start (a `run` with an exit in the log): read `prune-run.log` and `python3 $S/prune.py plan`, and fix or tell the user; the next try is the round after the key's window. A leftover half-removed field is /prune's to resume; leave a field that holds anything alone. |
| `barn-stuck` | A car of the last landed train still holds work 24 hours after the landing (key `barn-stuck:<NN>:<HEAD>`, once). New work of its foreman is fine: nothing to do. Work left behind (an unpushed commit, a forgotten change, a `CURRENT_PLAN` of a finished plan): tell its foreman in one line; a field with no session: leave the farmer a board note (`board.py post --kind note --from tollman-<repo> --to farmer-<repo> --text ...`; it reads it when it asks). Never remove it. |

Log what you did: `python3 $K/farmer/scripts/mtm_scan.py record prune <slot> "<what you did>" --note "<why>" --role
tollman`. Never remove a field by hand that /prune refuses, never `--force` a removal yourself (only /prune's run does, for a
free servant's field).
