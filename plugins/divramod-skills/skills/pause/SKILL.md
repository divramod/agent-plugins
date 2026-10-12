---
name: pause
description: Pause all current work of the agent session at once — the main task, every background shell (frozen with SIGSTOP, so a build or download stops where it is), every subagent and workflow (stopped, their transcripts kept for resuming), monitors, cron jobs and /loop wakeups — and write a pause record (~/skills/pause/<checkout>.md) of what was running and where each piece stood, so the `continue` skill picks it all up again, in this session or a fresh one. Nothing is committed, killed without a record, or lost. Use when the user says /pause, "pause", "stop everything for now", "hold on" or needs the machine's CPU back without losing the work. `/pause h` shows help.
---

# pause

Stops the session's work without losing any of it, and writes down how to resume every piece. The `continue`
skill reads that record and resumes. `S=<skill-dir>/scripts`, `P="python3 $S/pause.py"`.

| Call | Does |
|---|---|
| `/pause` | pause everything, write the record, stop |
| `/pause <note>` | the same, with the note in the record (why, or what to do first on continue) |
| `/pause status` | print whether this checkout has a paused session (`$P status`) and stop |
| `/pause h`, `/pause help` | print this table and stop |

Work fast: the user wants the work stopped now. Stop the moving parts first (steps 1–3), write the record
after (step 4). Do not finish a step of the task, run tests or commit before pausing.

## 1. Take stock

- `$P status`: when a record exists already, this checkout is paused already. Pause what runs now anyway and
  **add** to that record (a new `## Paused again <time>` section) instead of overwriting it.
- List what runs, from the conversation and the harness's own listings (Claude Code: the background tasks you
  started with `run_in_background`, `Monitor`, `Agent`, `Workflow`; `CronList`; an active `/loop`). For each,
  note its id or name, what it is for and how far it got (the last output you saw, a subagent's last report).
- `$P procs` prints the agent session's process tree (pid, ppid, state, start time, command). Match each
  background shell to its pids by command. The tree also holds the harness's own processes (MCP servers,
  `caffeinate`, the agent itself): leave those alone.

## 2. Freeze background shells

A background shell that is doing real work (build, test run, download, transcription, server) is frozen, not
killed: `$P freeze <pid> ...` with the top pid of each (the shell the task started) SIGSTOPs it with its whole
tree and remembers pid and start time in `<root>/<slug>.procs.json`. `continue` thaws them where they stopped,
as long as this agent session lives; when it has ended, `continue` reruns the command from the record.

Stop (the harness's `TaskStop`) instead of freezing, and record the command to rerun, when freezing would
break something: a process that holds a lock or a port other work waits on, one with a network connection that
will time out anyway, or a pure poller whose next run is as good as this one. Say which you did per task.

## 3. Stop agents, monitors and schedules

- **Subagents** and **teammates**: `TaskStop` each by id or name. Record its name/id, agent type, isolation
  (a worktree's path), the task it was given (its prompt, short) and its last known progress. Its transcript
  stays: in this session `continue` resumes it with `SendMessage` to the same name; in a new session it is
  relaunched from the recorded task and progress. Files it changed stay on disk.
- **Workflows**: `TaskStop` the run and record its run id (`wf_...`) and script path; `continue` resumes it with
  `resumeFromRunId` (same session only; otherwise rerun).
- **Monitors**: `TaskStop`; record the command or ws URL, description and timeout to re-arm.
- **Cron jobs** (`CronList`): record each cron expression, prompt and recurring flag, then `CronDelete` it.
- **A `/loop`**: `ScheduleWakeup` with `stop: true`; record the loop's prompt and interval.
- Other harnesses: use their equivalents; when something cannot be stopped, say so and record it anyway.

## 4. Write the record

`$P path` names the file (`~/skills/pause/<checkout slug>.md`; `$PAUSE_ROOT` overrides the root). Gather facts,
don't recall them: `git rev-parse --show-toplevel`, `git branch --show-current`, `git rev-parse --short HEAD`,
`git status --short`, and the content of `plans/CURRENT_PLAN` when there is one. Write:

```markdown
# Paused <YYYY-MM-DD HH:MM>

Checkout `<path>`, branch `<branch>`, HEAD `<short sha>`, agent session `<session id or link, when known>`.
<the user's /pause note, if any>

## Task
<what the session was doing: the user's request, the plan and step (link), the CURRENT_PLAN name>

## Where it stopped
<the main thread's state: what was done, what was half done (which file, which edit), what was verified>

## Next
1. <the exact next action on continue, then the ones after it>

## Uncommitted changes
<git status --short, and what each change is for; "none">

## Background shells
| task id | command | pids | paused as | on continue |
|---|---|---|---|---|
| b1 | `cargo nextest run` | 4711 | frozen | thaw; rerun when gone |

## Agents and workflows
| name / id | type | task | progress | on continue |
|---|---|---|---|---|

## Monitors and schedules
| kind | what (command, cron + prompt, loop prompt) | on continue |
|---|---|---|

## Watch out
<anything that must not happen on resume: a half-written file, a running migration, a lock>
```

Drop a section that has nothing in it. No secrets (tokens, passwords) in the record.

## 5. Report and hold

Tell the user in a few lines what was paused (counts per kind, what was frozen and what was stopped), the
record's path, and that `/continue` resumes it. Then stop: start no further work of the paused task until the
user continues. A later message from the user that is not `/continue` is answered on its own, the paused work
stays paused. If a script exits 2 with a missing-tool error, run `bash $S/install-prerequisites.sh`.
