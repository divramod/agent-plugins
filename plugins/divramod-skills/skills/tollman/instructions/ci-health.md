# Woken for CI/CD health (ci-health)

The tollman owns CI/CD health ("the script should check all runners and if something is wrong with a runner then the
tollman needs to know and then he needs to act on it", the user, 2026-10-18; plan 0383 step 11, D12, D13). Every pass
of the 1-minute `watch` (`ci_health.py`, `ci_fleet.py`) reads all runners of `.github/hal2-runners.toml`, GitHub's
runner list, the queued jobs of the unfinished landing runs and the CI supervisor's journal
(`<state root>/ci-supervisor/power.log`, state root `$HAL2_STATE_DIR` else `~/.local/state/hal2`). A healthy fleet
prints nothing; each new problem prints one line `runners: ...` once and wakes you with it (kind `runner`). GitHub
lists a parked server online for minutes, so a cloud machine counts by the journal's word.

You never wake or park a machine yourself, never call `hal2-cli-hetzner` or `az` for it: only the CI supervisor wakes
and parks ([park-the-linux-runner-asap](https://github.com/divramod/hal2/blob/main/.adr/park-the-linux-runner-asap.md)).

| The line says | The code already did | You do |
|---|---|---|
| `... waits for [...]: hz01 is parked; asked the CI supervisor to wake it (<file>)` | wrote the wake request `<state root>/ci-supervisor/wake-requests/<machine>.json` (`machine`, `requested`, `run`, `job`, `labels`) at once, in the first pass | Look at the journal in a minute (`tail ci-supervisor/power.log`): `<machine>: wake (...): ok` and then `says up` mean it is on its way, and the request file is gone. No wake after 5 minutes (the supervisor does not read requests yet, or is down): a board note for the farmer (`board.py post --kind note ...`) and, if the supervisor is down, tell the user; never wake it yourself |
| `... waits N min for the Mac VM runner, none online; fix-tart doctor: <case (n), ...>` | ran the fix-tart skill's doctor (`evidence.py doctor --hours 2`) for the last two hours | Read the case in `fix-tart/cases.md` and run `/fix-tart` when the doctor names one; "no case": look at the queued job's run, a board note for the farmer |
| `... waits N min for [...]: <code> offline` or `host runner <code> is offline for N min` | nothing (the supervisor restarts a runner at its grace, three tries) | After the supervisor's tries (its events in hal2-daemon's log) report it: a board note for the farmer naming the runner and the machine; the user fixes a machine |
| `... no runner of hal2-runners.toml has these labels` | nothing | The workflow's `runs-on` or `.github/hal2-runners.toml` is wrong: a board note for the farmer with the job and its labels |

Then `python3 $S/tollman.py act --done <seq>` as for any item. A problem prints once while it lasts; when it clears
and returns it is new.
