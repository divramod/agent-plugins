# Woken for queue

The tick's merge-queue watch (`queue_watch.py`, duty `queue`, hal2 plan 0570 step 5) found the front of the merge queue
blocked. It reads the queue only; you act. The item's `evidence` holds the finding (`kind`, `repo`, `slot`, `line`,
`fix`, `first_seen`); `python3 $S/queue_watch.py --repo-dir .` shows the queue's findings now (none: it moved, nothing
to do). One that lasts over 30 min reaches the user by itself (`alarm.py`: STALLED-GATE rings and pushes as `runner-down`, the
others only push); never ring again for it. The landings and the trains stay the tollman's: never land, unhitch or reorder
a train yourself.

| Kind | Do |
|---|---|
| `idle-reservation` | A reserved place at the front, no landing running, others waiting. Clear the order (`hal2-cli-git worktree queue order --clear --by <your field>`), re-order the ready ones, and tell the field it gets first place once it is ready |
| `dead-holder` | The holder's process is gone and no landing runs: tell the field to run `/mtm` again (its rerun adopts the landing); no session there: start one with the task |
| `stalled-gate` | The landing sits in one step over 45 min: open its `run_url`; a runner offline or a job without output is a runner fault ([ci.md](ci.md): `queued-long`, `running-long`), fix or delegate it |
| `not-moving` | The same landing over 60 min with others waiting: find out why (one of the above, or a red gate the tollman fixes in place) and tell the tollman by its board when it is not on it |

After acting: `python3 $S/mtm_scan.py record queue <slot> "<what>" --note "<why>"`.
