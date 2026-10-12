---
name: shoot
description: shoot — list the open shots of the repo's shotfiles (`shotfiles/*.md` of the main checkout, also from a worktree; the prompts written with hal2-nvim's shooter) as a table of id, shotfile, shot number and title, then shoot the ones the user picks by id (`3`, `1,2,4`, `1-4`), as `<space>00` does from Neovim — the shots are marked sent (`## x shot ...`) in their shotfiles and carried out; in the repository's main checkout it first asks where: a new worktree session per shot (recommended), a free worktree session (running, idle, no plan, nothing unmerged) or here in main; in a worktree slot it carries them out in this session. `/shoot` shows the 10 most important open shots, `/shoot g` the global shotfiles' shots (ids `g1`, `g2`, ...), `/shoot -a` all of both, `/shoot <shotfile>` the open shots of one shotfile, `/shoot <ids>` shoots shots directly. Use when the user says /shoot, asks which shots are open, or wants to pick the next shot to work on. `/shoot h` shows help.
---

# shoot

`hal2-cli-shooter` reads and marks the shotfiles; this skill ranks the shots, shows the table, lets the user pick
shots by id and then does them, here or (from main) in worktree sessions. `S=<skill-dir>/scripts`. The pick and
the [where](#where-main-checkout-only) question are asked as plain text, not with the question tool: the dialog
would hide the table and most ids. Ask any other question by the global question rule, recommended option first.

| Call | Does |
|---|---|
| `/shoot` | table of the 10 most important open shots, then ask which to shoot |
| `/shoot g`, `/shoot global` | table of every open shot of the global shotfiles (ids `g1`, `g2`, ...), then ask |
| `/shoot -a`, `/shoot --all` | table of every open shot, the repo's and the global ones, then ask |
| `/shoot <shotfile>` | table of the open shots of `<shotfile>` (`skills` or `skills.md`; `global:<name>` for a global one), then ask |
| `/shoot <ids>` | shoot the shots with these ids (from a table: `3`, `1,2,4`, `1-4`, `1-3,7`, `g2`, `g1-g3`) without asking which (in main still asking where) |
| `/shoot h`, `/shoot help` | print this table and stop |

## List

1. `hal2-cli-shooter shots list-open [<shotfile>] --json` from the current directory. It always reads the main
   checkout's `shotfiles/` (the default branch), also from a worktree, so every worktree sees the same shots and
   ids; a worktree's own `shotfiles/` counts only when the main checkout has none. If the command is missing or
   has no `shots list-open`, run `bash $S/install-prerequisites.sh` once and retry. Exit 1 prints why on stderr
   (no `shotfiles/` folder, not a git repository): report it and stop.
2. The JSON is `{"shotfiles": <dir>, "shots": [{id, file, number, title, line, path, modified, body}]}`. Only open
   shots with a title are listed. `id` is the shot's position in the repo's full list, so it stays the same with
   or without a filter until a shotfile changes.
3. No shots: say so (`no open shots in <shotfiles>`) and stop.

Global shots live in the global shotfiles folder (`hal2-cli-shooter settings --json` prints it as `root`; flat
`*.md`, shared by every repository): `hal2-cli-shooter shots list-open [<name>] --global --json`, same JSON, works
outside a repository too. Their ids get a `g` prefix (`g1`, `g2`, ...) and their shotfile shows as
`global:<name>`, so they never collide with the repo's. `/shoot g` lists only them; `/shoot -a` lists the repo's
shots, then the global ones, in one table (outside a repository, only the global ones); plain `/shoot` and
`/shoot <shotfile>` stay repo-only (`/shoot global:<name>` lists one global shotfile). A missing global folder
lists nothing (it is created only when a shot is written).

## Rank (plain `/shoot` only)

With more than 10 shots, pick the 10 most important and list them most important first. Judge from each shot's
title and body, and look up facts instead of guessing: `plans/CURRENT_PLAN` and the handoff (the plan's `plans/<plan>/handoff.md`, else the root `HANDOFF.md`) for the
current work,
the branch name, `modified` for recently touched shotfiles. Rank higher what:

- fixes something broken or blocks other shots (a foundation others build on);
- continues the current plan, the handoff's next tasks or this branch's feature;
- sits in a recently modified shotfile (active work) or is concrete and small enough to finish in one session.

Rank lower vague ideas (titles ending in `?`, "think about ..."), far-future items and duplicates of other shots.
`-a` and `<shotfile>` keep the CLI's order (shotfiles by name, shots top to bottom) and show every shot.

## Show

A Markdown table with exactly these columns, one row per shot:

| ID | Shotfile | Shot | Title |
|---|---|---|---|
| 15 | skills | 5 | adapt plan |
| g2 | global:ideas | 3 | try the new tokenizer |

Below it one line: `<shown> of <total> open shots in <shotfiles>` (with global shots also `and <global folder>`) and, for a ranked table, the one-line reason
for the top pick. Then end the message with the plain-text question, never the question tool:

`Which shots? ids from the table (e.g. 16 or 16,14 or 1-4 or g2), none to stop. Recommended: <id>`

and wait for the answer. The answer is a list of ids and ranges (`1,2,4`, `1-4`, `1-3,7`, spaces allowed); any
id of the repo's or the global full list counts (`g` ids and ranges `g1-g3`), also one not shown in the table. `none` (or an empty answer): stop. An id
that is not an open shot: say which and ask again.

## Where (main checkout only)

In a worktree slot (`git rev-parse --show-toplevel` is not the first path of `git worktree list`) the shots run in
this session: go on with [Shoot](#shoot). In the repository's main checkout ask first, also for `/shoot <ids>`,
after naming the picked shots (one line each: id, shotfile, shot, title), as one plain-text question:

```
Where should <this shot | these <n> shots> run?
1. New worktree session (recommended): each shot in its own new session, in the first slot without a session and without work
2. Free session <slot>[, <slot>...]: typed into a running idle session whose worktree holds no work
3. Here, in main
```

A shot only ever goes to a worktree without work: no plan in `plans/CURRENT_PLAN`, no uncommitted changes, no
commits not merged into main, no landing queued (behind main is fine: the shot's first step is `/mfm`). Offer 2
only when `python3 <skill-dir>/../list-free-worktrees/scripts/free.py --repo <main>` lists free slots (it applies
that rule);
with more shots than free slots, say that the rest get new sessions. Read the answer leniently (`1`, `new`, `free`,
`here`, a slot number for 2).

For 1 and 2, with `I=<skill-dir>/../digest-todolist-picture/scripts/implement.py`, per shot in the order picked:
`python3 $I send --repo <main> --shotfile <file> --number <number> [--global] [--pane <pane>] [--model <m>]
[--effort <e>]` (`--pane` with the next free slot's pane for 2; without it a new session starts through
create-worktree-session's `create.py`, which skips slots holding work). It sends hal2-nvim's shot template (run
`/mfm`, make the shot a plan, then run it as its coordinator, with the plan skill's coordinator sentence), starts or
types into the session and only then marks the shot sent with that slot, so skip step 1 below. The session runs at
an explicit model and effort: the user's defaults `opus` and `medium` (skills plan 0015's D15), or the ones the user
names for the shot (`--model`, `--effort`). A free session whose model or effort differ (or cannot be read from its
transcript) is restarted at them first, with the shot as its first prompt (`hal2-cli-agents switch`; the JSON says
`switched`), instead of being typed into. Exit 2 names a missing hal2 CLI: run that skill's `install-prerequisites.sh` once and
retry; exit 1: report that shot and go on with the next. Report one line per shot, `<file> shot <n> → <repo> wt
<slot> (<pane>, new | existing session)`, copy `hal2-cli-agents attach <repo>/<slot>` of the first into both
clipboards (`pbcopy`, `tmux set-buffer`), and stop: nothing is carried out here. For 3 go on with Shoot.

## Shoot

Resolve every picked id to its `file` and `number` from the list first (for `/shoot <ids>` list first; an
unknown id: say so and stop), before marking any: ids refer to that list.

1. Mark every picked shot, in the order picked, before working on any:
   `hal2-cli-shooter shots mark-sent <file> <number> --json` (a global shot: `--global`). It turns the header
   into `## x shot <n> <title> (<timestamp>) [<worktree>]`, as hal2-nvim's `<space><NN>` does (a global shot:
   `[<repo>/<worktree>]`, e.g. `[hal2/00]`, since the shotfile names no repository), and prints the shot:
   `{file, path, number, title, line, sent, worktree, body}`. Exit 1 (`already sent`, `no shot`): report that shot and
   leave it out; the shotfile changed since the list.
2. Print each marked shot in a code block, as `<space>00` shows what was sent:

   ```
   # shot <number> <title> (<file>, or global:<file>)
   <body>
   ```

3. Carry them out one after another, in the order picked, each as the current task with the same rules as a
   shot sent from Neovim:
   - It is shot `<number>` of the feature `<file>` in this repository; a global shot is shot `<number>` of the
     global shotfile `<file>` (at `path`), carried out in this repository. Read the shotfile (`path`) only when
     you need more context on what was prompted before.
   - In a git worktree, run `/mfm` (merge-from-main) once before starting the first shot.
   - Make every shot a plan before starting it: `/plan new "<file> <number> <title>"` (`shooter 3 i want all
     shots to become a plan`; `<file> <number>` for a shot without a title; a global shot:
     `"global <file> <number> <title>"`; a shot that asks for research rather than implementation becomes a
     research plan, `/plan new --research ...`, slug `<NNNN>-research-...`), then run the plan as its
     coordinator: **You are the plan's coordinator: you never do a step yourself; each step runs in one subagent
     at its row's Model and Effort, sized under 35% of its Window; you check its done-when, commit it and keep
     `run` current.** `/plan` writes the plan's `<NNNN>-<slug>` into `plans/CURRENT_PLAN`, so the statusline shows it; the file is
     gitignored runtime state, never committed, and `/mtm` deletes it once the plan has landed. A shot worked
     on without a plan names itself there as `<file>/<number>/<title-slug>`, a global one as
     `global:<file>/<number>/<title-slug>`.
   - Do not implement shots that were not picked, and do not change the shotfiles beyond the marks from step 1.

The mark is written straight into the shotfile, without renumbering: hal2-nvim renumbers on its next send. An open
Neovim buffer of the shotfile reloads it (or asks, when it has unsaved changes).
