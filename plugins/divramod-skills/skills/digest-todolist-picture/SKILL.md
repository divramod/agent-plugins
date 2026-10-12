---
name: digest-todolist-picture
description: Turn a photo of a handwritten to-do list into shots — reads every item of the picture (sent from the Claude iOS or Android app, or a path), routes each to the right repository and shotfile (the current repo's `shotfiles/*.md`, another of the user's repos, or the global shotfiles; it never assumes an item belongs to the repo it was started in), then walks the user through the list top to bottom in the order it is written on paper, one item per message in plain text (no question dialogs, so every answer can be dictated with the app's microphone): the handwritten text, any unclear reading or repository, the exact shot it would write (`## shot <n> <title>` and body), its shotfile and number; the user answers by voice with 1 add, 2 add and implement (sent at once to a new worktree via hal2, or to an existing agent session the user names), 3 skip or 4 more input (a dictated change); it writes only the confirmed ones with `hal2-cli-shooter shots create` (or the same format by hand where hal2 is missing). Ticked or crossed-out items are skipped; items that match an open shot are flagged. Use when the user sends a picture of a to-do list, a notebook page or a whiteboard and wants the items as shots. `/digest-todolist-picture --dry-run` shows the shots without writing, `/digest-todolist-picture h` shows help.
---

# digest-todolist-picture

A handwritten list becomes shots, and nothing goes into a shotfile that the user has not seen and confirmed in its
final form. `S=<skill-dir>/scripts`. A shot is `## shot <n> <title>` with its body below it, in a shotfile
(`shotfiles/<name>.md`); `shots.py` writes it exactly as hal2-nvim's shooter does, so never edit shotfiles by hand. The skill captures
work, it does not start it: it never writes `plans/CURRENT_PLAN`, `.gitignore` or anything but the confirmed shots.

| Call | Does |
|---|---|
| `/digest-todolist-picture` + a picture | read the list, walk through it item by item, write the confirmed shots |
| `/digest-todolist-picture <path> [<path> ...]` | the same for picture files (several pages: one list) |
| `/digest-todolist-picture --dry-run ...` | read and route the list, print the shots it would write with their numbers, write nothing and ask nothing |
| `/digest-todolist-picture h` | print this table and stop |

## Where it runs

Mostly from the Claude iOS or Android app, in a Claude Code session: either Remote Control into a session on the
user's Mac (this repo, the global shotfiles and `hal2-cli-shooter` are there) or a cloud session (only the repo
and its `shotfiles/`; `shots.py` writes the format itself and `global` is `null`). Without a git repository (a plain
claude.ai chat) there is nowhere to write: say so and stop. No picture attached and no path given: ask for it.

**Plain text only, never the question tool.** The user answers with the phone's microphone (speech to text), and
the app's question dialog only takes typed answers. So every question is a short plain-text message the user can
answer by speaking, and answers are read leniently: dictation garbles words, mixes German and English
(`ja`, `passt`, `nein`, `weiter`) and adds filler.

## 1. Read the picture

Read every item, top to bottom, page after page. For each note:

- the text as written (keep the user's words; expand only obvious abbreviations, e.g. `impl.` → implement);
- `done` when it is ticked, checked or crossed out; those are skipped and only listed in the report;
- the words you cannot read for sure, marked `[?word?]` with your best guess;
- an arrow, indent or sub-bullet makes a note part of the item above it (one shot), not an item of its own;
- a heading over a group of items (a repo, a project, "hal2:", "skills") is routing for the items below it.

## 2. Find the repositories and shotfiles

```bash
python3 $S/shots.py repos              # the user's git repositories (~/a; --root <dir>), which has shotfiles, which is current
python3 $S/shots.py targets            # the current repo's and the global shotfiles; --repo <dir> for another repository
```

`targets` JSON: `repo` (its shotfiles, each with `name`, `next` number and `open` shots `{number, title}`), `global`
(the global shotfiles, `null` when there are none here) and `cli` (whether `hal2-cli-shooter` is installed). Exit 2
names a missing tool: run `bash $S/install-prerequisites.sh` once and retry. Run `targets --repo <dir>` for every
other repository an item may belong to (step 3), so its shotfiles and open shots are known too.

## 3. Draft each shot

For every open item:

- **Repository first.** Starting the skill in a repository does not make every item that repository's: a
  handwritten list mixes projects. An item belongs to the current repo only when it clearly does (it names the
  repo, one of its skills, apps or shotfiles, or its heading does). An item that names another repo (`hal2: ...`,
  a heading `hal2`) goes to that one from `repos`. A personal task with no project (`call the dentist`) goes to a
  global shotfile. Everything else, and every item that could belong to two repos, is **unclear**: its message in step 4
  asks for the repository, never a guess.
- **Shotfile**: the one whose name and open shots match the item's topic (the feature it belongs to); a skill's
  name, a repo or an app named in the item decides. Personal tasks with no repo go to a global shotfile. Nothing
  fits: propose a new shotfile with a short kebab-case name (`shots.py` creates it).
- **Title**: short and lower case like the shotfile's other shots (`new skill daily-digest`, `tell: add reddit as a
  source`).
- **Body**: the item in clear words, as a prompt someone else could act on. Only what the note says or its
  heading implies: no requirements, steps or details made up. A one-line item can have an empty body.
- **Duplicate**: when an open shot of the target shotfile already asks for the same thing, mark it "similar to
  `<shotfile>` shot `<n>`".

Then number the drafts in the order they are written on paper (items for one shotfile get consecutive numbers):

```bash
echo '<items JSON>' | python3 $S/shots.py preview
```

Items: `[{"shotfile": "main", "title": "...", "body": "...", "global": false, "repo": "<dir, other repos only>"}]`.
It returns each with `number`, `header` (`## shot <n> <title>`) and `new_file`, and writes nothing.

`--dry-run` stops here: print every draft in paper order as it would be written (shotfile, `new shotfile` when new,
the header and the body, quoted as in step 4, never in a code block), the done items where they stand, the unclear points (for an unclear repository: the
candidate repos), and end.

## 4. Walk through the list, top to bottom

One item per message, strictly in the order the items stand on the paper (top to bottom, page after page), so the
user can follow along on the handwritten list. Never reorder, group by shotfile or batch items. A done (crossed
out, ticked) item is not asked: name it in one line at the top of the next message where it stands
(`Item 3 "buy coffee filters" is crossed out: skipped.`), so the count still matches the paper:
`<i> of <n>` counts every item on the paper, done ones included, top to bottom.

Before each item, `preview` it alone (earlier items are already written, so its number is exact). The message:

```
**Item <i> of <n>**: "<the text as written on paper>"

<only when something is unclear: what, and the choices as letters, the recommended one first and in the proposal>
A. <recommended reading, repository or shotfile> (recommended)
B. <the other likely one>

**Proposal**: <repo>:<shotfile> (new shotfile), shot <n>

> <the shotfile's full path from preview's `path`, home as ~: ~/a/hal2/shotfiles/app-macos-components.md>
>
> **## shot <n> <title>**
> <the body, line by line as it will be written, every line quoted with `> `>

<only for a likely duplicate: "Similar to <shotfile> shot <n> <title>: I'd skip it.">
**1** add · **2** add and implement · **3** skip · **4** more input
```

Plain Markdown, and the shot always as a quote (`> `), never in a code block: the Claude app does not wrap code
blocks, so a long line is cut off and the user has to expand the block on every item. The quote wraps like the
text around it. Its first line is the full path of the shotfile the shot is written to (`path` from
`preview`, the home folder as `~`), as plain text, not inline code (plain text wraps on the phone; escape `_` as
`\_`), then a bare `>` line, then the header in bold, written out literally (`**## shot 6 tabs: sort
alphabetically button**`; inside bold it is not turned into a heading); every body line follows as its own `> `
line, a blank body line as a bare `>`. The options line always shows all four numbers in this order; when option 2
cannot work here (a global shotfile, or no `hal2-cli-agents`: a cloud session) it reads `**2** add and implement
(not here: <why>)`. Keep the message short enough to read on a phone without scrolling. The
`<repo>:` part is left out for the current repo and is `global:` for a global shotfile.

Read the answer (spoken, so leniently; numbers come as `one`, `eins`, `the first`, `option 2`):

- **1, add** (`one`, `yes`, `yeah`, `ok`, `add`, `write it`, `ja`, `passt`): write this item now (see 5), then the
  next item. For an item with an unclear point, it takes the recommended choice, which the proposal already shows.
- **2, add and implement** (`two`, `implement`, `add and implement`, `do it now`): write it (see 5), then send it to
  an agent at once (see 6): a new worktree, or the existing session the answer names (`two, to 03`, `implement it
  in the n8n session`, `send it to main`). Then the next item.
- **3, skip** (`three`, `skip`, `no`, `next`, `nein`, `weiter`, `drop it`): nothing is written, next item. For a
  likely duplicate, skip is the expectation; 1 still writes it.
- **4, more input** (`four`, `more`, `wait`, or straight away the input itself): the user dictates more for the shot
  (new wording, "shorter title", "add that it must work on Linux"). After a bare `four`, ask `Go ahead.` and take
  the next answer as the input. Apply exactly that, nothing more, and show the item again.
- **a letter** (`A`, `B`, `the second one`): take that choice of the unclear point, redraft, and show the item again.
- **another place** (`put it in hal2`, `tell shotfile`, `global ideas`): redraft for that repository or shotfile and
  show the item again with its new number.
- **stop** (`stop`, `enough`, `that's it`): end the walk; the report names the items not yet walked through.

Anything else is more input (4). An answer you cannot make sense of: say what you understood in one line and ask
again.

## 5. Write each confirmed shot

Write a confirmed item at once, before showing the next one, so the number shown is the number written and nothing
is lost when the session ends early:

```bash
echo '[<the confirmed item, with its previewed "number">]' | python3 $S/shots.py write
```

It writes it (`hal2-cli-shooter shots create`, else the same format itself) and returns it with its `path`,
`number`, `line` and `via`; `previewed` is set when the real number differs from the one shown (the shotfile changed
meanwhile). The next message always starts with the result, so the user hears what happened:
`Written: <shotfile> shot <n>.` (`..., not <m> as shown.` when `previewed` is set), plus the send's result after
option 2 (see 6), or `Skipped item <i>.`

Commits: on the user's Mac never (shotfiles are working notes, hal2-nvim does not commit them either). In a cloud
session (`CLAUDE_CODE_REMOTE` is set) the shots are lost with the session unless they are pushed: after the walk,
commit only the written shotfiles (`shotfiles: <n> shots from a to-do list picture`) and push the session's branch.

## 6. Implement: send the shot to an agent (option 2)

Right after the write, the shot goes to an agent the way hal2-nvim sends a shot: its shot template (`# shot <n>
<title> (<shotfile>)`, the body, the `# context` lines telling the agent to run `/mfm`, not to touch the shotfile and
to make the shot a plan titled `<shotfile> <n> <title>` and run it as the plan's coordinator, every step in a sized
subagent), saved as a bullet file; then the shot is marked sent
(`## x shot ... [<slot>]`). Only on the user's Mac: it needs hal2 (`hal2-cli-agents`, `hal2-cli-shooter`; exit 2
names the missing one, `bash $S/install-prerequisites.sh` installs them) and a repository shotfile (a global shot
has no repository to start a worktree in).

- **No session named: a new worktree.**
  ```bash
  python3 $S/implement.py send --repo <repo dir> --shotfile <name> --number <n>
  ```
  create-worktree-session's `create.py` starts Claude in the repository's first slot without a session and without
  work (created when missing, its setup run) with the shot as its first prompt, at the user's defaults `opus` and
  `medium` effort (`--model <m> --effort <e>` when the user names others for the shot). The JSON names the `slot`, `pane` and `remote_control` (the
  Remote Control name `<repo>-<slot>`, so the user finds the new session in the Claude app). Say:
  `Sent to a new worktree: slot <NN>, in the app as <remote_control>.`
- **A session named: that session.** List the repository's live sessions:
  ```bash
  python3 $S/implement.py sessions --repo <repo dir>
  ```
  Each has `pane_id`, `slot` (`main`, `01`, ...), `state`, `title`, `plan` and `context_percent`. Match the answer by
  slot (`03`, `three`, `main`) or by words of its plan or title. One match:
  `python3 $S/implement.py send --repo <repo dir> --shotfile <name> --number <n> --pane <pane_id>` types
  `@<bullet>` into it; a Claude session whose model or effort differ from the shot's (or cannot be read) is
  restarted at them first with the shot as its first prompt (`switched` in the JSON): say so. No or several matches: list them in plain text, one line each (`A. slot 03, plan 0094 ...,
  done`), offer `new worktree` too, and take the next answer. A session in state `blocked` (waiting for a
  permission or an answer) is never typed into: the text would answer its dialog; say so and offer a new worktree.
  `working` is fine (the agent queues the input), but say so: `Sent to slot 03; it is still working, it reads the
  shot when done.`
- The shot stays written even when the send fails; say what failed and go on with the next item.
- A repository outside a folder Claude Code trusts (not below `~/a`) starts its new session on Claude Code's
  "trust this folder" dialog: then say `Open <remote_control> in the app and confirm the folder once.`

## 7. Report

One table in paper order, one row per item, so the user can cross the items off the paper:

| # | Item | Result | Shotfile | Shot |
|---|---|---|---|---|
| 1 | Tabs: sort alphabetically btn | written, sent to slot 05 | app-macos-components | 6 |
| 2 | buy coffee filters | done on paper | – | – |
| 3 | Inter agent message board | written | hal2:plugin-agents | 29 |

- **#**: the item's number on the paper (the `Item <i>` of the walk); **Item**: the note as written, shortened.
- **Result**: `written`, `written, sent to slot <NN>` / `... sent to <slot>'s session`, `skipped`, `done on paper`,
  `merged into <shotfile> shot <n>`, or `not walked through` (after a stop).
- **Shotfile** and **Shot**: where the shot now is, the shotfile's name (`<repo>:` before it when not the current
  repo, `global:` for a global one) and its number. An item that became two shots gets both, in the same order in
  both cells (`plugin-ai-evals, plugin-software-evals` / `1, 1`); no shot: `–` in both.

Keep the Item and Result cells short: the table has to fit a phone screen.
