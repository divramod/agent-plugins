---
name: delete-field
description: Stop the agent session of a worktree (`03`) or pane by signal, never /exit; worktree, branch and work stay. Refuses its own session, a busy agent, a draft, background tasks or a queued landing unless confirmed. Use when the user says /delete-field, "stop the session in wt 03", "end that agent" or "free a worktree".
---

# delete-field

`S=<skill-dir>/scripts`. It stops sessions, never deletes a worktree (that is `hal2-cli-git worktree remove`).
Ask questions by the global question rule (background first; ~/.claude/CLAUDE.md), recommended option first.

| Call | Does |
|---|---|
| `/delete-field` | list the repository's running sessions, ask which to stop |
| `/delete-field <worktree\|pane> [...]` | stop those sessions (`03`, `3`, `%54`, `t:<id>`; several: one after the other) |
| `... --repo <dir>` | another repository |
| `/delete-field h` | print this table and stop |

## Run

1. No target: `python3 $S/stop.py list [--repo <dir>]`, show a table (worktree, pane, state, plan, title; mark `self`),
   ask which to stop (plain-text question: worktree or pane, `none` to stop) and go on with the answer.
2. `python3 $S/stop.py stop <target> [--repo <dir>]` per target. Exit 2 names a missing hal2 CLI: run
   `bash $S/install-prerequisites.sh` once and retry.
   - Exit 3, `refused`: its own session (never stop it; say so), its plan has open dependents (plans waiting for
     it, `hal2-cli-plans depends list`; `--force` only on the user's word), or the agent is busy, holds a draft, runs
     background tasks or its landing runs (an older hal2 without `hal2-cli-agents stop` refuses every unforced
     stop: it cannot see a draft): show why and ask by the question rule (a) leave it running (recommended), b)
     stop it anyway: it loses its current turn, its draft and its background tasks, a landing ends with exit 13 (5 before hal2 plan 0318) and
     must be rerun, c) something else the user names). On b) rerun with `--force`.
   - Exit 4, `ambiguous`: several sessions in that worktree; show them and ask for the pane.
   - Exit 1: report the message.
3. The JSON names `stopped`, `slot` (the worktree) and `how`: `terminal-kill` (its terminal host killed) or `signal` (its tmux
   pane's process signalled); it waits up to 15 s (`--wait`) until the session is gone.

## Report

One line per target: `Stopped <repo> worktree <slot> (<pane>): <how>.` (`terminal-kill` or `signal`), or why it
was left running. Add that the worktree keeps its work: free for `/create-worktree-session`, and
`hal2-cli-git worktree list` shows what it still holds.
