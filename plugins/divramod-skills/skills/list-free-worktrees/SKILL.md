---
name: list-free-worktrees
description: List the current repository's free worktrees — slots where an agent session (Claude, Codex, OpenCode) is running but does no work and holds none: no agent busy (working, starting, blocked), `plans/CURRENT_PLAN` names nothing, no uncommitted changes, no commits not merged into main, no landing in the merge queue (behind main is fine) — as a table with the slot, pane, state and how far behind main, so a new task can go to one of them instead of a new session. `--all` lists every slot with why it is not free. Built on hal2 (`hal2-cli-agents`, `hal2-cli-git`). Use when the user says /list-free-worktrees, "which worktrees are free", "which sessions are idle" or wants a session for a new task. `/list-free-worktrees h` shows help.
---

# list-free-worktrees

`S=<skill-dir>/scripts`. Read-only: it lists, it never starts, stops or sends anything.

| Call | Does |
|---|---|
| `/list-free-worktrees` | the free worktrees of the current repository |
| `/list-free-worktrees --all` | every worktree slot, free or why not |
| `... --repo <dir>` | another repository |
| `/list-free-worktrees h` | print this table and stop |

## Run

`python3 $S/free.py [--repo <dir>] [--all]`. Exit 2 names a missing hal2 CLI: run `bash $S/install-prerequisites.sh`
once and retry. Exit 1: report the message.

## Show

A Markdown table, one row per worktree: Slot, Pane, State, Behind main, Context % (with `--all` also Free and Why). Below it one line, `<n> free worktrees in <repo>` (none: say so and that `/create-worktree-session`
starts a session in a slot without one). Point to the next steps: send a
task to a free slot's session (e.g. `/shoot` there), `/delete-worktree-session <slot>` to stop it.
