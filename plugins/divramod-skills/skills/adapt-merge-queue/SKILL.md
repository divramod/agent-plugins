---
name: adapt-merge-queue
description: Change the merge queue's priorities as the user says — `/adapt-merge-queue 12 18 15` makes slots 12, 18 and 15 land first in that order, before every other waiting landing (also one that queues later; the landing holding the queue is never preempted), and reserves each listed slot's place: a slot not yet queued gets a reserved ticket there, and at the front the queue waits for it until its own merge-to-main takes it over. hal2 owns the order (`hal2-cli-git worktree queue order`); the skill runs it, prints the queue before and after, and tells every affected session by SendMessage: each listed slot its place (finished work not queued: land now; still working: keep working, the place waits), each slot moved back, each slot whose reservation went. In the farmer session every message carries an ack id (acks.py instruct). `/adapt-merge-queue clear` drops the order and every reservation. Use when the user says /adapt-merge-queue, "change the merge queue's order", "12 first, then 18", "reserve a place in the queue for 18" or "these land first". `/adapt-merge-queue h` shows help.
---

# adapt-merge-queue

`S=<skill-dir>/scripts`. The user's order; nothing here lands, releases or stops anything.

| Call | Does |
|---|---|
| `/adapt-merge-queue <slot>... [-- <why>]` | these slots land first, in this order; each place reserved |
| `/adapt-merge-queue clear` | drop the order and every reservation |
| `... --repo <dir>` | another repository (default: the current one) |
| `/adapt-merge-queue h` | print this table and stop |

A slot is `12`, a role's short name (`farmer`) or its full slot name (`farmer-hal2`); never `main`. A new order
replaces the old one: a slot no longer listed loses its reservation (a waiting landing keeps waiting, unreserved). A
listed slot leaves the order when its landing's turn ends, or by `hal2-cli-git worktree release <slot>`.

## Run

```bash
python3 $S/adapt.py <slot>... [--note "<why>"] [--repo <dir>] [--instruct] --json
```

Pass `--instruct` in the farmer session (the slot `farmer-<repo>`): each message then carries the farmer's ack id
and is logged as an instruction (the tick follows up on missing acks). Exit 2 names a missing hal2 CLI (`bash
$S/install-prerequisites.sh`, then retry); exit 1 is hal2's refusal (an unknown slot, main, a merge queue on the
hub): report it and stop.

## Tell

For each entry of `messages` (`slot`, `kind`, `worktree`, `text`): find the session working in `worktree`
(ListAgents: the row whose path is that folder) and send `text` verbatim by SendMessage. No session there: say so in
the report; the reservation still holds. Never edit a message: a `land` message's first line (`merge-to-main boss:
land now`) is the user's go to land, as the farmer's boss sends it.

## Report

The queue before and after (the script's text without `--json`), the order now, who was told what and which slots
had no session. Nothing else.
