---
name: create-shot
description: create-shot — write a new open shot (`## shot <n> <title>` with its body) into a shotfile, as hal2-nvim's shooter does with `<space>ss` (above the first shot, numbered one above the highest), from the agent CLI instead of Neovim — the counterpart of shoot, which sends shots. Takes the user's words (`/create-shot tell: add reddit as a source`) or, without text, what the conversation just settled (`/create-shot` after a discussion), picks the shotfile (the current repo's `shotfiles/*.md`, another repo's with `hal2:<shotfile>`, a global one with `global:<name>`, a new one when nothing fits), drafts a short lower-case title and keeps the user's words as the body, writes it with `hal2-cli-shooter shots create` (or the same format by hand where hal2 is missing) and reports the shotfile, number and the id to `/shoot` it with, then offers to implement it right away: in the next idle worktree session (running, no plan, nothing unmerged), or, when there is none, in a new worktree session. Asks only when the repository or shotfile is unclear; flags an open shot asking the same. `/create-shot --dry-run ...` shows the shot without writing, `/create-shot --implement ...` sends it without asking, `/create-shot --no-implement ...` only writes it. Use when the user says /create-shot, "make a shot of this", "add a shot", "write that down as a shot" or "put this in the shotfile". `/create-shot h` shows help.
---

# create-shot

The user's words become a shot in a shotfile, exactly as hal2-nvim writes one, so the shot shows up in `/shoot`,
`<space>fp` and every worktree. `S=<skill-dir>/../digest-todolist-picture/scripts` (its `shots.py` finds the
shotfiles, numbers and writes shots; never edit a shotfile by hand). The skill captures work, it does not start it:
it writes nothing but the shot (no `plans/CURRENT_PLAN`, no commit; shotfiles are working notes, hal2-nvim does not
commit them either); implementing it happens in another session, after the [offer](#6-offer-to-implement). Ask any question by the global question
rule, recommended option first.

| Call | Does |
|---|---|
| `/create-shot <text>` | one shot from `<text>` in the shotfile that fits, written at once |
| `/create-shot <shotfile>: <text>` | the same into `<shotfile>` (`main`, `tell.md`; `hal2:<shotfile>` another repo's, `global:<name>` a global one); created when missing |
| `/create-shot` | a shot of what the conversation just settled (the task, idea or bug discussed last) |
| `/create-shot --dry-run ...` | show the shot it would write, its shotfile and number, write nothing |
| `/create-shot --implement ...` | write it and send it at once to the next idle worktree session, else a new one, without asking |
| `/create-shot --no-implement ...` | write it, no offer |
| `/create-shot h`, `/create-shot help` | print this table and stop |

Several clearly separate tasks in one call (a list, "and also ...") become one shot each, written in the order given.

## 1. Find the shotfiles

```bash
python3 $S/shots.py targets [--repo <dir>]   # the repo's and the global shotfiles: name, next number, open shots
python3 $S/shots.py repos                    # the user's repositories (~/a), for `<repo>:<shotfile>`
```

`targets` JSON: `repo` (its `shotfiles` folder and `files`, each with `name`, `next` and `open` shots
`{number, title}`; `null` outside a git repository), `global` (`null` where there is no hal2) and `cli` (whether
`hal2-cli-shooter` is installed). It reads the main checkout's `shotfiles/`, also from a worktree, like
`hal2-cli-shooter`. A `<repo>:` prefix names a repository from `repos` by its folder name: run `targets --repo <dir>`
for it. Outside a repository only `global:` targets work; without one either, say so and stop.

## 2. Draft the shot

- **Shotfile**: the one named in the call; else the one whose name and open shots match the topic (a skill's,
  app's or feature's name in the text decides; `main` is the catch-all of a repo that has it). A personal task with
  no project goes to a global shotfile. Nothing fits: propose a new shotfile with a short kebab-case name.
- **Repository**: the current one, unless the text names another repo (`hal2: ...`, one of its apps). When the
  shot could belong to two repos or two shotfiles equally, ask (step 3) instead of guessing.
- **Title**: short and lower case like the shotfile's other shots (`new skill create-shot`, `tell: add reddit as a
  source`). The user may give it (`title: ...`, the first line of a multi-line text).
- **Body**: the user's words, as a prompt someone else could act on later, in a fresh session without this
  conversation: keep their wording, fix only dictation slips, and add only what they said or what the conversation
  settled (for `/create-shot` without text: the decided goal, constraints and file paths, briefly). No made-up
  requirements or steps. A one-line shot may have an empty body.
- **Duplicate**: an open shot of the target shotfile that asks the same thing: say so (`similar to <shotfile> shot
  <n> <title>`) and ask whether to write it anyway, extend nothing on your own.

Number it without writing:

```bash
python3 $S/shots.py preview <<'JSON'
[{"shotfile": "<name>", "title": "...", "body": "...", "global": false, "repo": "<dir, other repos only>"}]
JSON
```

Pass the JSON through a quoted heredoc, never `echo`: zsh's `echo` turns the body's `\n` into raw newlines,
which breaks the JSON.

It returns each item with `path`, `number`, `header` and `new_file`.

## 3. Ask only when unclear

Clear shotfile, no duplicate: write at once (step 4); the user asked for the shot, and the report shows it. Unclear
repository or shotfile, a new shotfile, or a duplicate: show the draft (as in the report below, with the
proposed shotfile) and end with one plain-text question, the choices as numbers, the recommended first:

```
Where should it go?
1. <repo>:<shotfile>, shot <n> (recommended): <why it fits>
2. <other shotfile>, shot <m>
3. new shotfile <name>
```

Read the answer leniently (a number, a shotfile's name, "write it", "skip"); a correction of title or body is
applied exactly and the draft shown again. `--dry-run` never asks: it shows the draft and its open points and stops.

## 4. Write

```bash
python3 $S/shots.py write <<'JSON'
[<the item, with its previewed "number">]
JSON
```

It writes through `hal2-cli-shooter shots create` (else the same format itself; `via` says which) and returns
`path`, `number`, `line` and, when the shotfile changed since the preview, `previewed` (the number shown before).
Exit 2 names a missing tool: run `bash $S/install-prerequisites.sh` once and retry. An open Neovim buffer of the
shotfile reloads it (or asks, when it has unsaved changes).

Then find the shot's id for `/shoot`: `hal2-cli-shooter shots list-open <shotfile> --json` (`--global` for a global
shotfile, `--repo <dir>` for another repo) and take the `id` of the entry with that `number` (a global shot's id
gets a `g` prefix). Without the CLI, leave the id out.

## 5. Report

The shot as a quote, its first line the shotfile's path (home as `~`), then the header in bold:

```
Written: <repo>:<shotfile> shot <n> (id <id>, `/shoot <id>` sends it)

> ~/a/skills/shotfiles/main.md
>
> **## shot 26 new skill create-shot**
> <the body, every line quoted with `> `, a blank line as a bare `>`>
```

`<repo>:` only for another repository, `global:` for a global shotfile; add `new shotfile` when it was created and
`, not <m> as shown` when `previewed` is set. Several shots: one block each.

## 6. Offer to implement

After the report (not for `--dry-run` or `--no-implement`), offer to start the shot now in another session, the way
`/shoot` does from main, so this session stays free. `I=<skill-dir>/../digest-todolist-picture/scripts/implement.py`.

1. Find idle sessions of the shot's repository (for a global shot: the current repository, where it will be
   carried out; outside a repository there is nowhere to run it, so skip the offer and point to `/shoot g`):
   `python3 <skill-dir>/../list-free-worktrees/scripts/free.py --repo <repo>`. Its `worktrees` (`slot`, `panes`) are the free
   slots, lowest first: a running agent session, none of its agents busy, no plan in `plans/CURRENT_PLAN`, no
   uncommitted changes, nothing unmerged into main, no landing queued. Exit 2 (no hal2: a cloud session) or no
   `hal2-cli-agents`: skip the offer and say `/shoot <id>` runs it later.
2. End the message (the report is the background, so a plain-text question, never the question tool):

   ```
   Implement it now?
   1. Idle session wt <slot> (recommended): typed into the running idle session (<pane>)
   2. New worktree session: a fresh session in the first slot without a session and without work
   3. Not now: it stays open for /shoot <id>
   ```

   With no free slot, drop option 1, and the new worktree session is the recommended one. Several shots: one
   question for all; each shot gets its own session, the free slots first (lowest first), then new ones; say
   when there are more shots than free slots. Read the answer leniently (`1`, `idle`, `yes`, `new`, `2`, `no`,
   `later`, another free slot's number).
3. Send, per shot in the order written:
   `python3 $I send --repo <repo> --shotfile <file> --number <n> [--global] [--pane <the slot's first pane>]`
   (`--pane` for an idle session; without it a new session starts through create-worktree-session, which skips
   slots holding work). It sends hal2-nvim's shot template (run `/mfm`, make the shot a plan, carry it out), then
   marks the shot sent (`## x shot ... [<slot>]`). Exit 2 names a missing hal2 CLI: run
   `bash <skill-dir>/../digest-todolist-picture/scripts/install-prerequisites.sh` once and retry; exit 1: report
   that shot (it stays written and open) and go on.
4. Report one line per shot, `<file> shot <n> → wt <slot> (<pane>, idle | new session)`, and copy
   `hal2-cli-agents attach <repo>/<slot>` of the first into both clipboards (`pbcopy`, `tmux set-buffer` when a
   tmux server runs). Nothing is carried out in this session.

`--implement` skips the question and takes the recommended option (the first idle session, else a new one).
