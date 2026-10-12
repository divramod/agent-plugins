---
name: continue
description: Continue where the `pause` skill paused the session — read the pause record (~/skills/pause/<checkout>.md), check what changed since, thaw the frozen background shells (SIGCONT) or rerun them when they are gone, resume the stopped subagents (SendMessage to the same name in this session, relaunched from the recorded task and progress in a new one) and workflows, re-arm monitors, cron jobs and the /loop, then carry on with the main task's next action. Works in the paused session and in a fresh one. Use when the user says /continue, "continue", "resume", "unpause" or "go on" after a pause. `/continue h` shows help.
---

# continue

The counterpart of the `pause` skill: it resumes every piece of work its record names. The scripts live with
`pause`: `S=<pause-skill-dir>/scripts` (the `pause` skill next to this one), `P="python3 $S/pause.py"`.

| Call | Does |
|---|---|
| `/continue` | resume everything this checkout's pause record names |
| `/continue <text>` | the same, with the user's text overriding the record's **Next** where they conflict |
| `/continue h`, `/continue help` | print this table and stop |

## 1. Read the record

`$P status` prints the record's path and age, exit 1 when nothing is paused for this checkout: then say so. When
the user says "continue" without a pause, look for a handoff (the current plan's `plans/<plan>/handoff.md`, else
the root `HANDOFF.md`; the handoff skill's `where.py` names it) and offer the `handoff` skill's continue
instead; otherwise ask what to work on. Read the whole record (every `## Paused again` section too) and
the files its **Task** links (the plan, the step).

## 2. Check for drift

Compare with the record: `git branch --show-current`, `git rev-parse --short HEAD`, `git status --short`. New
commits or changes the record doesn't list mean someone worked meanwhile: read them and say how they change the
**Next** list before resuming anything. A different branch: stop, say what differs, and ask.

## 3. Resume the moving parts

Same session or new one? The session is the same when the record's agents, task ids and frozen pids belong to
this conversation (you started them, `$P thaw` finds the pids alive).

- **Background shells**: `$P thaw` SIGCONTs every frozen process that still runs (same pid and start time) and
  prints `thawed` or `gone` per process. The task is back where it stopped; read its output as usual. A `gone`
  task, and every task paused as *stopped*, is started again from its recorded command (`run_in_background`),
  unless the record or drift says its result is no longer needed.
- **Subagents**: in the same session `SendMessage` to its recorded name or id: "You were paused. Continue your
  task where you stopped." — it resumes from its transcript. In a new session launch it again with the same
  agent type and isolation, its recorded task, and its recorded progress ("already done: ...; continue with:
  ...").
- **Workflows**: same session: `Workflow` with `resumeFromRunId` (completed agents return cached). New session:
  run the recorded script again, or leave it to the user when it is expensive (ask).
- **Monitors**: re-arm with the recorded command, description and timeout.
- **Cron jobs** and **/loop**: recreate them from the recorded cron, prompt and recurring flag; a `/loop`
  continues with `ScheduleWakeup` and its recorded prompt.
- Respect **Watch out**. When something cannot be resumed, say so and what it means for the task.

## 4. Close the record and carry on

1. `$P finish` moves the record (and its procs file) to `~/skills/pause/<slug>/history/`, so the next `/pause`
   starts fresh and `/continue` does not resume twice.
2. When `plans/CURRENT_PLAN` is missing or names something else, write the record's task name into it.
3. Tell the user in two or three lines what was resumed (thawed, rerun, resumed agents, re-armed) and what you
   start with, then do the first **Next** action. When the task is a started plan, keep running it as the `plan`
   skill's "Run the plan" says instead of stopping after one step.

If a script exits 2 with a missing-tool error, run `bash $S/install-prerequisites.sh`.
