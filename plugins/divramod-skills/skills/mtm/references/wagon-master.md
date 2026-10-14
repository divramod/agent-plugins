# A repository with a wagon master

`bash $S/wagon-master.sh [<dir>]` printed `yes`: the repository has a wagon master (hal2 plan 0294), the role whose
session in the worktree `wagon-master-<repo>` lands the work of every worktree as trains
([wagon-master](../../wagon-master/SKILL.md)). A foreman's `/mtm` then only reports its work ready, the **hitch**,
and finishes later. This page stands in place of SKILL.md's steps 1, 3 and 4 and says how steps 5 to 8 run
afterwards. `S=<skill-dir>/scripts`.

## The check

`wagon-master.sh` reads `python3 <wagon-master skill>/scripts/wagon_master.py status --json` (state files and one
timer probe; no model, no network) and the installed hal2-cli-git's help. It always exits 0; the answer is its one
line on stdout, the reason for a `no` one line on stderr.

| Answer | When |
|---|---|
| `yes` | the worktree `wagon-master-<repo>` exists, its timer is loaded and its mode is `timer`, its last round is at most 30 minutes old, the worktree asked for is not the wagon master's own, and `hal2-cli-git --help` names `worktree queue ready` |
| `no` | anything else, and every doubt: a missing tool or wagon-master skill, a status that cannot be read, a last round in the future |

`no` is never a failure: `/mtm` lands as SKILL.md says. A wagon master that goes down after a hitch does not
strand the work either: the next `/mtm` of the worktree gets `no`, and its own `reserve` or `merge-to-main` takes
the ready ticket over at its place.

## Hitch

In the main checkout on the default branch there is nothing to hitch: stop, as step 1 says.

1. SKILL.md [step 2](../SKILL.md#2-commit-and-push-everything), unchanged: sort, commit, push. A plan's landing
   leaves unclear files untracked and names them in the report, as there.
2. `hal2-cli-git worktree queue ready --json [<slot>]`. It fetches and pushes nothing and returns at once: exit 0,
   `{"status": "ready", "field": "<repo>/<NN>", "seq": <n>, "branch": ..., "ready": {"at", "head", "by"}}`. The
   ticket waits without a process, in nobody's way; the train takes the head the mark names.
3. `hal2-cli-git worktree queue --json`: the place is the position of this worktree's ticket in `queue`, counted
   from 1 (the trains' order); `rides_with` names the wagon master's worktree once a train carries it.
4. Report, and nothing more: `hitched: field <NN> rides the next train`, the place, the head, and what step 2
   gitignored or left untracked. No `reserve`, no `land-runs.sh`, no `merge-from-main`, no `merge-to-main`, no
   waiting and no watching of a run.

Exit 1 is a refusal, its one line on stderr. Report it as it is and stop; only the first two rows have a fix
that is part of step 2, done once before the command is run again:

| The refusal says | Then |
|---|---|
| `has <n> commit(s) that are not pushed`, `is not pushed (no origin/<branch>)` | push (step 2, item 6), run the command again |
| `has uncommitted changes in <n> tracked file(s)` | commit and push them (step 2), run the command again |
| `holds nothing <default> lacks: nothing to bring in` | nothing to land: say so; steps 6 to 8 as after a landing that landed nothing |
| `origin/<branch> is ahead of the worktree` | report it: someone else pushed to this branch |
| `its ticket #<n> is at the head of the merge queue (...)`, `its own landing waits in the merge queue`, `its fastlane keeps a place` | this worktree's own landing is on its way: report the message, it names the way out (its `merge-to-main` lands it, `worktree release` or `stop` gives it up); never hitch around it |
| exit 2, `unknown ...` | the installed hal2-cli-git is older than the hitch: land as SKILL.md says |

**Afterwards the session goes on working**, or ends its turn; a finished `Landing: auto` plan ends its turn here
and its end waits for "in the barn". `plans/CURRENT_PLAN` and the plan's handoff stay.

- Work committed after the hitch rides only when it is pushed and the same command has run again (it moves the
  mark to the new head, the place stays).
- `hal2-cli-git worktree queue ready --clear [<slot>]` takes the hitch back (the user decides against it).
- The context threshold: a hitched worktree has no landing under way, so hal2's guard stops its session like any
  other. The handoff names the hitch under **Next** (hitched, the head, "after in the barn: `/mfm`, then steps 5
  to 8"); there is no process to keep alive.
- Never poll for the train. Looking once, when the session works anyway, is fine: `git fetch origin <default>`,
  then `git merge-base --is-ancestor <ready head> origin/<default>` (exit 0: it is in the barn).

## After "in the barn"

The wagon master's code tells each wagon of a green train that its work is in the barn. The message's first line is

```
wagon-master [<id>] (wagon train): your crop is in the barn (the train of <fields>, <run address>). Restock (/mfm), ...
```

(`<id>` is the ack id: answer `ack <id>: started|done|refused <why>` by `SendMessage` to the wagon master's session,
the line below the message names it). That message, or the check above seen by the session itself, is this
worktree's landing: the second half of `/mtm` runs now, in this
session, without a question (the wagon master changes no other worktree).

1. `/mfm` ([mfm](../../mfm/SKILL.md)): the default branch, which holds the work now, into the worktree. Then
   `git log --oneline origin/<default>..HEAD` lists only what was committed after the hitched head (and its merge).
2. SKILL.md [step 5](../SKILL.md#5-finish-the-plan-and-land-it): run the plan's steps whose done-when needed the
   landing, finish each as the plan skill says. Nothing is reserved here, so nothing is released and no lease
   runs; where step 5 says "back to step 4", hitch again instead: push, `hal2-cli-git worktree queue ready --json`,
   report `hitched` and wait for that hitch's own "in the barn". Only then is nothing left.
3. [Step 6](../SKILL.md#6-clear-the-current-task) as it is. Delete the side branches the default branch now
   contains (`git branch -d <NN>-<topic>`: it refuses an unmerged one, which stays and is named), as a landing of
   this worktree would have.
4. [Step 7](../SKILL.md#7-clean-up) as it is: `after-landing.sh` acts only on a fully landed worktree with a
   finished plan.
5. [Step 8](../SKILL.md#8-report): the train that carried the work (the run the message names), the commits that
   landed, the plan steps finished afterwards, the worktree clean and equal to the default branch, the cleanup, and
   **What landed** as the last lines. No queue release and no durations table: the landing was the wagon master's.

`/mtm milestone`: only item 1, then the milestone row is marked done; steps 5 and 7 are skipped and
`plans/CURRENT_PLAN` stays, as milestone mode says.

## Unhitched

The wagon master takes a wagon off, clearing its ready mark, and tells its session why. The message's first line is
one of

```
wagon-master [<id>] (wagon train): field <NN> is unhitched: its crop conflicts with <the barn | the cars ahead (<fields>)> in <files>. Restock (/mfm), resolve it, push and report it ready again (...)
wagon-master [<id>] (wagon train): field <NN> is unhitched from the red train: <why>. Fix it, push and report it ready again (...)
wagon-master [<id>] (wagon train): field <NN> is unhitched: a servant's field (30-99) never rides a train, its foreman merges its branch.
```

for these causes (acked like "in the barn"):

- **a conflict** in the trial merge, with the default branch or with a wagon ahead of it in the queue, in any file
  (generated files and lockfiles too: restock and resolve them yourself);
- **named as the cause of a red train**, with the failing job in the reason;
- **a servant's field**: a worktree 30-99 never hitches; its foreman merges its branch.

The work is back with this session, and the rest of the train rides without it. Fix this worktree's own work only:

1. `/mfm`; resolve what conflicts as its **Conflicts** says. A clean `/mfm` after a conflict means the other side
   is a wagon that is not in the default branch yet: do it again once the default branch has moved.
2. A red job: read its log (`gh run view <run> --log-failed`), reproduce it with
   `code/bash/scripts/gate/main.sh <job> --branch origin/main` where the repository has it, fix it and see it green.
3. Commit, push, hitch again (the command above) and report `hitched` with the new head.

Never land the work yourself instead, never ask the wagon master to resolve it (it never edits another worktree's
work), and never leave it unhitched without a word: a cause this session cannot fix is asked of the user, in a
plan's landing after a notification (`PushNotification`), as SKILL.md's "When to ask" says.
