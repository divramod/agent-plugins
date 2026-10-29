---
name: continue-all-agent-work
description: The counterpart of stop-all-agent-work — after a system-wide stop (benchmarks done), undo the machine quieting (thaw frozen processes, load the unloaded LaunchAgents such as the Ollama keepalive, start Ollama again, unpause Docker containers) from the stop record, then tell every stopped Claude session through Claude Code's cross-session socket (SendMessage) to resume with /continue, a session whose landing was paused in place runs /mtm again, which adopts it. Use when the user says /continue-all-agent-work, "all agents may continue", "benchmarks are done" or "let them work again". `/continue-all-agent-work h` shows help.
---

# continue-all-agent-work

The scripts live with `stop-all-agent-work`: `S=<stop-all-agent-work-skill-dir>/scripts`,
`R="python3 $S/stopall.py"`, `Q="python3 $S/quiet.py"`.

| Call | Does |
|---|---|
| `/continue-all-agent-work` | undo the machine quieting, tell every stopped session to continue |
| `/continue-all-agent-work <name>...` | only those sessions (the stop stays active for the rest) |
| `/continue-all-agent-work h` | print this table and stop |

## 1. Read the stop

`$R status`; exit 1: no stop is active, say so and stop. The record names the stopped sessions, the kept ones and
the machine actions.

## 2. Undo the machine first

`$Q restore` (preview with `--dry-run`) undoes the recorded actions in reverse: SIGCONT for frozen processes,
`launchctl bootstrap` for unloaded LaunchAgents, `open -a Ollama`, `docker unpause`, and `launchctl kickstart -k` of every CI runner service the stop froze or stopped (a runner
thawed by SIGCONT alone stays online but deaf); report each restarted service by name. Orphans and simulators had no
undo. Report a step that failed (a process that is gone is fine).

## 3. Tell the sessions (SendMessage, all in one reply, in parallel)

`ListAgents` first: send only to recorded names still listed (a session that ended: say so). **Skip a paused field**
(`hal2-cli-git worktree paused --json`, hal2 plan 0458): a stop does not unpause it, so the session of a field that
was paused before or during the stop is not told to continue, nor is any session started there; list it in the report
as paused (by, why). Only the farmer resumes a field (`worktree resume <NN>`, on the user's go). To each:

> All agents may continue: the system-wide stop is over. Run /continue now. If your pause record says a merge to
> main (/mtm landing) was running, it was paused in place, not aborted: run /mtm again, it adopts the landing.

## 4. Close the stop

With every stopped session told: `$R finish` (moves the record to `history/`). With only some named: keep the
record and `$R save` nothing; tell the user which are still stopped.

## 5. Report

The sessions told (and any no longer listed or holding the message for approval), what `restore` undid, and the
load a minute later (`top -l 2 -n 0 | grep "CPU usage"`). If a script exits 2 with a missing-tool error, run
`bash $S/install-prerequisites.sh`.
