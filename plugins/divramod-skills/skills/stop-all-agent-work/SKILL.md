---
name: stop-all-agent-work
description: Stop the work of every Claude Code session on the machine at once, for a quiet system (performance benchmarks, a hot or slow Mac) — except the sessions the user names (`/stop-all-agent-work keep hal2/07`) — through Claude Code's own cross-session socket (ListAgents + SendMessage, not hal2): each session runs the `pause` skill (background shells frozen, subagents, workflows, monitors, cron jobs and /loop stopped, a pause record written), a session in a merge to main (/mtm) aborts the landing and starts a new one later; then a script quiets the rest of the machine (freezes processes still running below paused sessions, ends test leftovers, shuts down simulators, quits Ollama, unloads timer LaunchAgents such as an Ollama keepalive) and records each undo. Before stopping important work (data copied to a volume, a push, deploy, migration, install, upload, a landing, the CI runner) it asks the user one safety question. continue-all-agent-work undoes all of it. Use when the user says /stop-all-agent-work, "stop all agents", "tell all sessions to stop", "I need a quiet machine" or "benchmark time". `/stop-all-agent-work h` shows help.
---

# stop-all-agent-work

`S=<skill-dir>/scripts`, `R="python3 $S/stopall.py"` (the stop record), `Q="python3 $S/quiet.py"` (the machine).
The counterpart is `continue-all-agent-work`. Work fast: the user wants the machine quiet now. Messages go through
Claude Code's cross-session socket (`ListAgents`, `SendMessage`); do not type into panes or use hal2 for it.

| Call | Does |
|---|---|
| `/stop-all-agent-work` | stop every other session, quiet the machine |
| `/stop-all-agent-work keep <who>...` | the same, but the named sessions go on (`hal2/07`, `wt07 of hal2`, a session name like `07-53`) |
| `/stop-all-agent-work scan` | only show what still costs CPU (`$Q scan`) and stop |
| `/stop-all-agent-work status` | show the active stop (`$R status`) and stop |
| `/stop-all-agent-work h` | print this table and stop |

## 1. Who stops

`ListAgents` lists the peer sessions (this session is not among them and keeps running: it coordinates).
Resolve each kept session to its row: a name like `07-53` is a slot, not a repository, so check its checkout —
`lsof -a -p <pid> -d cwd` of the `claude` processes (`pgrep -x claude`), or the row's tmux pane
(`tmux display -p -t <%pane> '#{pane_current_path}'`). Keep the checkout path(s) for step 4 (`--keep-cwd`).
Ask only when a kept name matches several sessions. Everyone else is stopped.

## 2. Tell them (SendMessage, all in one reply, in parallel)

To every session to stop:

> STOP NOW: the user needs a quiet machine (<reason>). Stop your work right away, mid-step is fine: run the pause
> skill (/pause stopped for system-wide quiet) so every background shell is frozen, every subagent, workflow and
> monitor stopped, every cron job and /loop removed, and a pause record written. Exception: when stopping one
> piece right now would break or half-finish something important (copying or moving data, a git push, a deploy, a
> database migration, an install, an upload, a paid or outward-facing action), pause everything else, leave that
> piece running and reply to <this session's name> at once: what it is, what breaks when it is frozen or killed,
> and how long until a safe point. Then wait for the answer. If you were running a merge to
> main (/mtm landing), stop the landing's running hooks/workflows too (TaskStop or kill their process tree), note
> in the record that the landing was aborted, and on /continue start a NEW /mtm landing instead of resuming the
> old one. Do not start builds, tests or anything else. Then stay idle until a message from <this session's
> name> says all agents may continue; then run /continue.

Then record it: `$R save --stopped <name>... --keep <name>... --note "<reason>"` (a stop that is active
already gets the names added). A `[Cross-session delivery notice]` that a session holds or refuses the message:
tell the user which one needs their approval in its own terminal.

## 3. Wait for the replies

Sessions answer as they pause (`... is paused`). Give them a minute; meanwhile run step 4. Note what they report
that still runs (a detached download, an LSP indexing), for step 4 and the summary. A reply that names important
work it left running goes into the safety question (step 5).

## 4. Quiet the machine (script)

`$Q apply --keep-cwd <kept checkout>...` (preview with `--dry-run`). It freezes (SIGSTOP) busy processes still
running below paused sessions (a build a session forgot, sourcekit-lsp indexing), terminates test leftovers
under /tmp whose session is gone, shuts down booted simulators, quits Ollama (SIGTERM: its quit dialog blocks a
polite quit; never call the `ollama` CLI, which starts Ollama.app again), unloads LaunchAgents that run on a
timer (e.g. `local.ollama-keepalive`, every 60 s), pauses Docker containers, and writes every action with its
undo into the stop record. Processes of the kept sessions, macOS daemons and the user's apps are only listed.
Rows marked `CONFIRM` are important work (data copied or moved to a volume, a git push, merge or landing, a deploy,
a database migration or dump, an install, an upload, a disk or backup operation, the CI runner): `apply` leaves
them running and exits 3; they go into the safety question (step 5).

A self-hosted GitHub Actions runner is listed, not stopped: ask the user, then `--runner` unloads it (CI jobs
wait meanwhile). The user's apps (Chrome, VoiceInk, a `tart pull`, ...): name them and let the user decide;
quit one only on their yes.

Run `$Q scan --keep-cwd ...` again after a minute: anything new below a paused session (a session started work
after its pause) gets `apply` again and a reminder message to that session. The load average lags: judge by
`top -l 2 -n 0 | grep "CPU usage"`, not `uptime`.

## 5. Safety question (only when something important is at stake)

Ask the user before stopping anything important; when nothing is, ask nothing and go on. Important is: a `CONFIRM`
row of `apply`, a session's reply about work it left running, a session holding the merge queue or waiting on a
permission dialog, anything outward-facing or paid (a deploy, a push, a cloud resource), and the user's apps. One
question for all of it, after the background (the global question rule: plain text, not the question tool): a
table of the items (session, what, what breaks when stopped now, time to a safe point), then

1. **Wait for the safe point, then stop (Recommended)**: the session finishes that piece and pauses; `apply` again.
2. **Stop it now**: freeze it (`$Q apply --yes <pid|label>...`, thawed on continue) or tell the session to pause it;
   says what may be left half done.
3. **Leave it running**: it keeps running through the benchmarks; the report names it as load.

Per item when they differ. Act on the answer: `--yes` for what the user confirmed, a message to the session
("pause it now" / "pause after the safe point" / "leave it running") for session work.

## 6. Report

A short table: session, paused (yes / waiting / held for approval), what it reported. Then what `apply` did
and what it left alone (system daemons such as syspolicyd or Spotlight's mds settling after builds, the kept
sessions' own load, the user's apps), the CPU idle now, and that `/continue-all-agent-work` brings it all back.
Exit 3 of `apply` is not an error: it means the
safety question is open. If a script exits 2 with a missing-tool error, run `bash $S/install-prerequisites.sh`.
