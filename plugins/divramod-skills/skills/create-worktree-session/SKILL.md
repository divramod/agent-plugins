---
name: create-worktree-session
description: Start a new agent session (Claude by default) in the current repository's first free and clean worktree slot — the first slot from 01 with no agent session running in it and no work in its worktree (no plan in plans/CURRENT_PLAN, no uncommitted changes, no commits not merged into main, no landing queued; behind main is fine), creating the worktree when it is missing — detached in the background (a hal2 terminal host, or a tmux window with --tmux), with a fresh session whose first prompt runs /mfm and then an optional task prompt (e.g. `/shoot 13`). The farmer's servants start with `--from 30` and an explicit `--model` and `--effort` (a new worktree needs free disk). Reports the slot, the attach command (in the clipboard) and the slots it skipped for their work. Use when the user says /create-worktree-session, "new worktree session", "start an agent in a free worktree" or wants a task started in a fresh worktree. `/create-worktree-session h` shows help. The opposite is delete-worktree-session.
---

# create-worktree-session

`create.py` picks the slot (hal2's agents, terminal hosts, worktrees and merge queue) and starts the agent with
`hal2-cli-git worktree run <NN> --detach`; this skill runs it and reports. `S=<skill-dir>/scripts`.

| Call | Does |
|---|---|
| `/create-worktree-session` | start Claude in the first free, clean slot of the current repository; its first prompt is `/mfm` |
| `/create-worktree-session <prompt>` | the same, the first prompt runs `/mfm` and then `<prompt>` (e.g. `/shoot 13`) |
| `... --repo <dir>` | another repository (any of its checkouts) |
| `... --agent codex\|opencode`, `--model <id>`, `--effort <level>`, `--tmux` | another agent, its model and effort (per process, saved nowhere; the JSON echoes them), a window of tmux session `hal-<repo>` instead of a terminal host |
| `... --exact` | the first prompt exactly as given, without `/mfm` first |
| `... --from <NN>` | start the slot search at `<NN>` instead of 01 (servants: `--from 30`) |
| `... --min-free-gb <n>` | free disk a new worktree needs (default 50: a slot's build cache takes 10-30 GB) |
| `/create-worktree-session h` | print this table and stop |

## Run

1. `python3 $S/create.py [--repo <dir>] [--agent ..] [--model ..] [--effort ..] [--tmux] [--prompt "<prompt>"] [--exact]
   [--from <NN>]`. Pass the user's prompt verbatim as one argument. Exit 2 names a missing hal2 CLI: run `bash $S/install-prerequisites.sh`
   once and retry. Exit 1 prints why (not a repository, no free and clean slot from 01 to 99, the start failed):
   report it, stop (too little disk: say so; the farmer prunes a slot).
2. The JSON has `slot`, `pane`, `worktree`, `attach`, `model`, `effort` and `skipped` (the slots without a session that hold work,
   each with why). Copy `attach` into both clipboards
   (`pbcopy`, and `tmux set-buffer` when a tmux server runs).

## Report

Short: `Started <agent> in <repo> wt <slot> (<worktree>), pane <pane>; first prompt: /mfm[, then <prompt>].`, then
`Attach: <attach> (in the clipboard).` When slots were skipped, one line: `Skipped <slot> (<why>), ...`: earlier
tasks' work waiting there to be landed or reset (`hal2-cli-git worktree reset-to-main <slot>`); the user decides.
