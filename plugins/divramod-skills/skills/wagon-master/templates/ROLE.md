---
# The wagon-master skill's settings for this repository: the user's word, and only the user changes it.
# Nothing is implicit. Only what is listed here runs, each on its own cron
# (5-field cron: minute hour day-of-month month day-of-week, local time).
# The foremen's check reads a last tick older than 30 minutes as "no wagon master" and lands as before, so at least
# one duty runs every 10 minutes or oftener.
duties:
  trains: "*/5 * * * *"       # the wagon train: ready wagons, trial merge, the landing; a red train wakes the session
  mtm: "*/10 * * * *"         # the merge-to-main boss: failed landings, held queues, pauses, orphans
notify: every-round
---

# <repo>'s wagon master

The wagon master brings the ready wagons of the foremen through the toll gate into the barn, as many per run as
possible (a wagon train), from its own field `wagon-master-<repo>`. The code does the rounds; the session judges only
what the code cannot.

## Priorities

1. A ready wagon rides the next train: nothing waits for a train that could have formed.
2. A red train is read at once: the wagon that broke it goes back to its foreman, the rest rides again.
3. The yard (the main checkout) holds nothing the barn lacks that could ride a train.

## Rules

- Never stop a landing that runs.
- Never edit another field's crop: a wagon that conflicts or breaks a train goes back to its foreman with the reason.
- Never land for a field that did not hitch (`hal2-cli-git worktree queue ready`); the user's `/mtm-fastlane` is
  not the wagon master's to run.
- A crop that changes the landing workflow, a gate job list or the runner setup rides alone.
- Secrets any session creates go into hal2-secrets and the main checkout's `.env` (AGENTS.md).
