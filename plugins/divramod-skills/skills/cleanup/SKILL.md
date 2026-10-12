---
name: cleanup
description: Delete the build artifacts of the current git worktree, or another worktree of the repository named by its folder name, branch or path (`/cleanup 03`, so it runs from another session), to free disk space — every git-ignored, untracked build output and generated file (Rust target/, Xcode and SwiftPM build folders, .build/, generated .xcodeproj and xcframeworks, dist/, caches), without asking. What goes is the repo's `.hal/cleanup` (globs to delete, `!` globs to keep, e.g. fetched dependencies), else generic build folders; it deletes only git-ignored paths that hold no tracked file — never secrets, .env, .hal/, plans/ or shotfiles/ — and reports sizes and how each comes back. /mtm runs it after a fully landed worktree. Refuses while a build or test still runs in the worktree. Use when the user says /cleanup, "clean the worktree", "delete build artifacts", "free disk space" or a disk is full. `/cleanup h` shows help.
---

# cleanup

Frees the disk space a worktree's builds use, without asking. `S=<skill-dir>/scripts`, `C="python3 $S/cleanup.py"`.
The script decides what counts as an artifact and refuses unsafe paths; this skill runs it and reports.

| Call | Does |
|---|---|
| `/cleanup` | delete every artifact of this worktree, then report |
| `/cleanup <path>...` | delete just these (worktree-relative), after the same safety checks |
| `/cleanup list` | only the table, delete nothing |
| `/cleanup <worktree> [list\|<path>...]` | the same for another checkout of this repository: its folder name or branch as `git worktree list` shows it (`03`, `main`) or its path; add `--worktree <it>` to every `$C` call |
| `/cleanup h`, `/cleanup help` | print this table and stop |

A first argument that `git worktree list` names (a folder name or branch) or that is a checkout's path is the
worktree; anything else is a path inside the current one.

## What counts

`$C list` takes git's ignored, untracked paths (`git ls-files --others --ignored --exclude-standard --directory`),
drops the protected ones and gives each a kind: `artifact` (deleted), `kept` or `unknown` (never deleted in bulk;
name it explicitly when the user wants it gone).

- **`.hal/cleanup`** (the repo's list, tracked): one glob per line relative to the worktree root, `*` within a
  folder, `**` across folders, naming the git-ignored folder or file itself; `!glob` keeps what it matches; a
  trailing `# ...` says how it comes back (shown as the rebuild column); the last matching line wins. It is meant
  to name every ignored path of the repo, so an `unknown` row is a new artifact location: add it to the list
  (delete or `!` keep) instead of deleting it by hand. hal2's list is the example: build output and generated
  files go, fetched dependencies (`node_modules`, VLCKit), the root `HANDOFF.md` and `.claude/` stay (a plan's
  `plans/<plan>/handoff.md` is tracked, so cleanup never sees it).
- **Without the file**: generic build folders are artifacts (`target/`, `build/`, `.build/`, `dist/`,
  `DerivedData`, `*.xcresult`, `__pycache__/`, `.gradle/`, `.next/`, ...), fetched dependencies are kept
  (`node_modules/`, `.venv/`, `Pods/`), the rest is unknown. Suggest writing a `.hal/cleanup` for the repo.

Protected, never listed or deleted: `.git`, `.hal/` (worktree runtime state), `.secrets/`, `.env*`, `plans/`
(`CURRENT_PLAN`), `shotfiles/`, `*.machine.toml`. `delete` also refuses a path that is not git-ignored, holds a
tracked file, lies outside the worktree or does not exist.

Outside the worktree and **not** touched: an installed app (`~/Applications/hal2-macos-<worktree>.app`), the
checkout's test simulator (`hal2-<worktree>`), published builds (`~/.local/state/hal2/builds/`), Xcode's
compilation cache and `~/Library/Developer/Xcode/DerivedData`, and other worktrees (the delivery worktree
`.deliver` keeps its builds so installs after a landing stay fast). Mention them when the user wants more space
back; delete them only when asked.

## Steps

1. `$C busy` lists the processes whose command line names this worktree (a `cargo`, `xcodebuild`, a hook's
   `test-unit.sh`). When it exits 1, deleting their output breaks them: say which run and stop (from /mtm: skip
   the cleanup and say so). Your own background tasks in this worktree count too. For another worktree, also check
   `hal2-cli-agents list --json` (when installed) for an agent in it whose `state` is `working`: it may start a
   build any moment, so say so and ask before deleting (plain text: 1. wait until it is idle (recommended), 2.
   clean now).
2. `$C delete`, or `$C delete <path>...`: no question first. It prints `deleted <size> <path>` per path, `skip
   <path>: <why>` for a refused one (exit 1) and the space freed. A large `target/` takes a while: run it in the
   background when the harness allows and say so.
3. `$C list` shows what is left: `kept` rows and any `unknown` ones (name those, and propose the line for
   `.hal/cleanup`).
4. Report the space freed, what was skipped and why, and what the next build has to rebuild (the rebuild column;
   in hal2 e.g. `build-core` before the Swift apps).

Never commit, and never delete tracked files: when a path is tracked but looks like an artifact, report it as a
gitignore candidate instead. If a script exits 2 with a missing-tool error, run `bash $S/install-prerequisites.sh`.
