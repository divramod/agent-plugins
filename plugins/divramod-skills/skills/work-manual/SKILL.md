---
name: work-manual
description: Walk the user through every farm's manual work — the hands-on items (an install, a click in a console, a cable) that plans keep in their `manual/` folder, written only by `hal2-cli-plans manual`; a script lists, shows and marks them done; the model walks one by one. Use when the user says /work-manual, "manual work", "what do I have to do by hand", "my manual items" or "list the hands-on things".
---

# work-manual

`S=<skill-dir>/scripts`. A manual item is what only the user's hands can do, one file `plans/<plan>/manual/<NN>-<slug>.md`
(Why, Steps, Done when), id `<farm>/<NNNN>/<NN>`. The items are written and read only by `hal2-cli-plans manual`
(`$HAL2_CLI_PLANS` or the one on PATH); `wm.py` is a thin layer over it for every farm on the machine (the repositories
with a `plans/` folder under git.toml's `root`, default `~/a`). Never read, edit or write an item file by hand.

| Call | Does |
|---|---|
| `/work-manual` | list every farm's open items, then walk them (below) |
| `/work-manual <id>` | show that one item and walk it |
| `/work-manual list [--json]` | only the list: `python3 $S/wm.py list` |
| `/work-manual done <id>` | mark the item done: `python3 $S/wm.py done <id>`, only after the user said it is done |
| `/work-manual h` | print this table and stop |

## Walk

1. `python3 $S/wm.py list`. Print it as it comes. A `problem:` line is a farm whose CLI call failed: say so once, go on.
   No items: say so and stop.
2. One item at a time, the user's pick or the first: `python3 $S/wm.py show <id>`. Give the guide in plain text, the
   steps as stored (they are in the step-by-step form of `~/AGENTS.md`: system, link, where, do, then you see), the
   done-when check, and what waits for it. Never the question tool; the user answers in words.
3. The user does it by hand. Their word "done" (or the check's result) is the only reason to run
   `python3 $S/wm.py done <id>`; never mark an item done yourself, from a guess or because a command looked fine. If
   they say it failed or is blocked, leave the item open and say what you saw.
4. After `done`, name the item that was waiting for it if the item had `waits`, then offer the next one.

An item with `from: Q<n>` comes from that question of its plan (`hal2-cli-plans questions list`); the question stays
the decision, the item holds only the guide. A step that is wrong or missing is a finding for the plan's owner, not
something to edit here.
