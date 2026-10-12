---
name: delete-worktree-session
description: Stop a running agent session of the current repository's worktree slots — the opposite of create-worktree-session — by its slot (`03`) or pane (`%54`, `t:<id>`): stops it by signal through `hal2-cli-agents stop` (its terminal host killed, or SIGHUP, SIGTERM, SIGKILL to its tmux pane), never by typing `/exit`, which sessions did not take; the worktree, its branch and its work stay. Refuses its own session, a busy agent (working, starting, blocked), a draft in its prompt, running background tasks and a slot whose landing runs or waits in the merge queue unless the user confirms. Without an argument it lists the running sessions and asks which. Use when the user says /delete-worktree-session, "stop the session in wt 03", "end that agent" or "free a worktree slot". `/delete-worktree-session h` shows help.
---

# delete-worktree-session

`S=<skill-dir>/scripts`. It stops sessions, never deletes a worktree (that is `hal2-cli-git worktree remove`).
Ask questions by the global question rule (background first; ~/.claude/CLAUDE.md), recommended option first.

| Call | Does |
|---|---|
| `/delete-worktree-session` | list the repository's running sessions, ask which to stop |
| `/delete-worktree-session <slot\|pane> [...]` | stop those sessions (`03`, `3`, `%54`, `t:<id>`; several: one after the other) |
| `... --repo <dir>` | another repository |
| `/delete-worktree-session h` | print this table and stop |

## Run

1. No target: `python3 $S/stop.py list [--repo <dir>]`, show a table (slot, pane, state, plan, title; mark `self`),
   ask which to stop (plain-text question: slot or pane, `none` to stop) and go on with the answer.
2. `python3 $S/stop.py stop <target> [--repo <dir>]` per target. Exit 2 names a missing hal2 CLI: run
   `bash $S/install-prerequisites.sh` once and retry.
   - Exit 3, `refused`: its own session (never stop it; say so), or the agent is busy, holds a draft, runs
     background tasks or its landing runs (an older hal2 without `hal2-cli-agents stop` refuses every unforced
     stop: it cannot see a draft): show why and ask by the question rule (a) leave it running (recommended), b)
     stop it anyway: it loses its current turn, its draft and its background tasks, a landing ends with exit 5 and
     must be rerun, c) something else the user names). On b) rerun with `--force`.
   - Exit 4, `ambiguous`: several sessions in that slot; show them and ask for the pane.
   - Exit 1: report the message.
3. The JSON names `stopped`, `slot` and `how`: `terminal-kill` (its terminal host killed) or `signal` (its tmux
   pane's process signalled); it waits up to 15 s (`--wait`) until the session is gone.

## Report

One line per target: `Stopped <repo> wt <slot> (<pane>): <how>.` (`terminal-kill` or `signal`), or why it
was left running. Add that the worktree keeps its work: free for `/create-worktree-session`, and
`hal2-cli-git worktree list` shows what it still holds.
