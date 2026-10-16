---
name: adapt-merge-queue
description: Change the merge queue's priorities as the user says — `/adapt-merge-queue 12 18 15` makes worktrees 12, 18 and 15 land first in that order, before every other waiting landing (also one that queues later; the landing holding the queue is never preempted), and reserves each listed worktree's place: a worktree not yet queued gets a reserved ticket there, and at the front the queue waits for it until its own merge-to-main takes it over. hal2 owns the order (`hal2-cli-git worktree queue order`); the skill runs it, prints the queue before and after, and tells every affected session by SendMessage: each listed worktree its place (finished work not queued: land now; still working: keep working, the place waits), each worktree moved back, each worktree whose reservation went. In the farmer session every message carries an ack id (acks.py instruct). `/adapt-merge-queue clear` drops the order and every reservation. Use when the user says /adapt-merge-queue, "change the merge queue's order", "12 first, then 18", "reserve a place in the queue for 18" or "these land first". `/adapt-merge-queue h` shows help.
---

# adapt-merge-queue

`S=<skill-dir>/scripts`. The user's order; nothing here lands, releases or stops anything.

| Call | Does |
|---|---|
| `/adapt-merge-queue <worktree>... [-- <why>]` | these worktrees land first, in this order; each place reserved |
| `/adapt-merge-queue clear` | drop the order and every reservation |
| `... --repo <dir>` | another repository (default: the current one) |
| `/adapt-merge-queue h` | print this table and stop |

A worktree is `12`, a role's short name (`farmer`) or its full worktree name (`farmer-hal2`); never `main`. A new order
replaces the old one: a worktree no longer listed loses its reservation (a waiting landing keeps waiting, unreserved). A
listed worktree leaves the order when its landing's turn ends, or by `hal2-cli-git worktree release <worktree>`.

## Run

```bash
python3 $S/adapt.py <worktree>... [--note "<why>"] [--by user] [--repo <dir>] [--instruct] --json
```

The order is stamped with who set it (`hal2-cli-git worktree queue order ... --by <who>`, which `worktree queue` shows as
"by ..."): by default this session's own field (`hal2/17`, `hal2/farmer-hal2`). Add `--by user` when you relay the user's
own words (their `/adapt-merge-queue` or "12 first, then 18"): hal2 then shows `the user (via hal2/17)`. Never `--by user`
for an order the session decided itself.

Pass `--instruct` in the farmer session (the farmer's worktree `farmer-<repo>`): each message then carries the farmer's ack id
and is logged as an instruction (the tick follows up on missing acks). Exit 2 names a missing hal2 CLI (`bash
$S/install-prerequisites.sh`, then retry); exit 1 is hal2's refusal (an unknown worktree, main, a merge queue on the
hub): report it and stop.

## Tell

For each entry of `messages` (`slot`, `kind`, `worktree`, `text`): find the session working in `worktree`
(ListAgents: the row whose path is that folder) and send `text` verbatim by SendMessage. No session there: say so in
the report; the reservation still holds. Never edit a message: a `land` message's first line (`merge-to-main boss:
land now`) is the user's go to land, as the boss sends it. In a repository with a working wagon master (the mtm
skill's `scripts/wagon-master.sh` prints `yes`) the script writes that line in the wagon master's boss's name
(`wagon-master (merge-to-main boss): land now`): the worktree's `/mtm` then reports its work ready at the reserved
place and the wagon master's train lands it.

## Report

The queue before and after (the script's text without `--json`), the order now, who was told what and which worktrees
had no session. Nothing else.
