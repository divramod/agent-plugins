---
name: restart-claude-code-sessions
description: Restart every running Claude Code session on the machine in place (the same tmux pane or terminal host, the same conversation, model, effort and Remote Control name), e.g. after the user logged in to another account — one script calls `hal2-cli-agents restart --all`, which asks busy sessions to hand off first, never cuts a running landing or smuggle (skipped and reported), restarts the others one by one and this session last. Use when the user says /restart-claude-code-sessions, "restart all claude sessions", "restart every session", "I logged in to another account" or "restart the agents". `/restart-claude-code-sessions h` shows help.
---

# restart-claude-code-sessions

`S=<skill-dir>/scripts`. The script does everything; this skill only runs it (hal2 plan 0371).

| Call | Does |
|---|---|
| `/restart-claude-code-sessions` | restart every running Claude session, this one last |
| `... --dry-run` | list every session and what would happen, restart nothing |
| `... --except <pane>` | leave that session out (repeatable) |
| `... --wait <secs>` | how long a busy session may take for its handoff (the CLI's default 600) |
| `/restart-claude-code-sessions h` | print this table and stop |

## Run

1. `python3 $S/restart.py [--dry-run] [--except <pane>]... [--wait <secs>]`. Exit 2 names a missing hal2 CLI: run
   `bash $S/install-prerequisites.sh` once and retry. Exit 1: a session failed or timed out; report which.
2. Report its table in a few lines (project/slot, pane, action, result) and the skipped ones with their reason.
3. Without `--dry-run` this session is restarted last by a detached job, in about a minute: end the turn at once
   after the report and start nothing else.
