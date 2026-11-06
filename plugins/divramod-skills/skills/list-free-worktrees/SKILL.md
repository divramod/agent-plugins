---
name: list-free-worktrees
description: List the repository's free worktrees (an agent session runs there but has no plan, no uncommitted or unmerged work, no queued landing) as a table, so a new task can go to one; `--all` says why the others are not free. Use when the user says /list-free-worktrees, "which worktrees are free", "which sessions are idle" or wants a session for a new task.
---

# list-free-worktrees

`S=<skill-dir>/scripts`. Read-only: it lists, it never starts, stops or sends anything.

| Call | Does |
|---|---|
| `/list-free-worktrees` | the free worktrees of the current repository |
| `/list-free-worktrees --all` | every worktree, free or why not |
| `... --repo <dir>` | another repository |
| `/list-free-worktrees h` | print this table and stop |

## Run

`python3 $S/free.py [--repo <dir>] [--all]`. Exit 2 names a missing hal2 CLI: run `bash $S/install-prerequisites.sh`
once and retry. Exit 1: report the message.

## Show

A Markdown table, one row per worktree: Worktree, Pane, State, Behind main, Context % (with `--all` also Free and Why). Below it one line, `<n> free worktrees in <repo>` (none: say so and that `/create-worktree-session`
starts a session in a worktree without one). Point to the next steps: send a
task to a free worktree's session (e.g. `/shoot` there), `/delete-field <worktree>` to stop it.
