# Landings first: the ci-check runs (checks)

Landings and trains have the runners first ([merge-queue-policy](../../../../../../../.adr/merge-queue-policy.md),
amendment 2026-10-14; [docs/ci.md](../../../../../../../docs/ci.md#landings-first)). The tick does the duty as code
(`checks.py`, the CLI `checks_cli.py`); you are woken only for what it cannot settle. Opt in with
`checks: "*/2 * * * *"` in `roles/wagon-master/ROLE.md`: without the duty `ci-check` never defers (a deferral would wait
for nobody).

**Each round**, in this order:

1. **Busy?** `busy` is true while a ticket is active, a train stands (formed, landing, retry), a hold is reserved, a
   `push` run of merge-to-main.yml on `land/**` is unfinished or a ticket waits; not while a red landing holds the
   queue (`held`: nothing moves, the checks may run).
2. **Busy: cancel what costs nothing.** A `workflow_dispatch` run `[<slot>] ci-check ...` that is queued or in progress
   and has started no job but `route` and `changes` is cancelled (`gh run cancel`) and recorded as deferred again.
   A check that runs lane jobs is **never** cancelled; a run not recorded in the store (`checks dispatched` was not
   called for it) is **never** cancelled, it is left alone and said so in the log.
3. **Not busy: dispatch.** The oldest pending worktree's **newest** deferral is dispatched, **one per round**; the worktree's
   older deferrals are superseded.
4. **Tell the session**, once per entry: "your check <title> waits behind landing <slot>" when it is deferred, "your check
   <title> runs: <url>" when it is dispatched (`SendMessage` to the worktree's session, as the act says).

**The store** is `roles/wagon-master/checks.jsonl` (events `deferred`, `dispatched`, `cancelled`, `superseded`; declared
in the manifest). The CLI, from any checkout (`--repo <dir>`, default `.`):

| Call | Does |
|---|---|
| `python3 $S/wagon_master.py checks busy [--json]` | `{busy, reason, slot, live, live_why}`, exit 0; `live`: the tick ran in the last 30 min and the duty is opted in |
| `checks defer --slot <s> --pane <p> --title <t> -- <argv...>` | records a check for later and prints its id (ci-check calls it only when busy and live) |
| `checks dispatched --slot <s> --pane <p> --title <t> [--run <id>] -- <argv...>` | records ci-check's own dispatch so the duty may cancel it later |
| `checks list [--json]` | the store; `checks cancel --run <id>` and `checks dispatch --id <id>` are what the round runs |

`ci-check --now` skips the deferral. Without a live wagon master ci-check dispatches as before.

**The bounds** (constants of `checks.py` and `checks_tell.py`):

| Bound | Value | Meaning |
|---|---|---|
| RETRY | 10 min | a failed cancel or dispatch is planned again after this; a slot whose newest deferral failed within it is skipped |
| TRIES | 3 | failed dispatches of one deferral before it is given up and the session told |
| STALE | 24 h | a deferral older than this is superseded, never dispatched |
| WAITING | 2 h | a `waiting` ticket without a live session holds the runners this long (from `ready.at`) |
| MATCH | 2 h | a dispatch recorded without its run is matched by title, or counts as running, this long |
| SEND_WINDOW | 30 min | a message not typed (relayed) is planned again after this |
| SEND_TRIES | 3 | how often one message is planned at most |
| TELL | 1 day | a dispatched or given-up check older than this is not told any more |

A `gh` failure reads as busy: `unknown: gh failed`, and that round cancels and dispatches nothing.

| Kind | Do |
|---|---|
| a `checks` item | The act names the entry. Check with `checks list` and `checks busy --json`. A cancel or dispatch that failed is tried again at the next round (10-minute window); a deferral that never leaves (busy for hours) is a stuck landing: handle it as `mtm` says, and tell the session to run `ci-check --now` only when the user wants it |

Never: cancel a landing's or train's run, or a check with a started lane job; dispatch two checks in one round.
