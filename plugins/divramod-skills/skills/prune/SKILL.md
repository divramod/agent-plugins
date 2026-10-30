---
name: prune
description: Clean a farm's fields (worktrees) by script, shown as a run: idle fields removed or mucked out, stale CURRENT_PLAN pointers cleared, build folders trimmed only while the disk is short; never a field with unsaved work. Use for /prune, "prune the fields", "clean up the worktrees", "free disk space on the farm", "delete unused worktrees". `/prune h` shows help.
---

# prune

`S=<skill-dir>/scripts`, `P="python3 $S/prune.py"`. The script decides and acts; this skill runs it, relays its asks
and reports. The model never deletes a field, never decides for a foreman (D6), never edits `.hal/prune.toml` unasked.

| Call | Does |
|---|---|
| `/prune` | `hal2-cli-runs exec --workflow prune -- $P run`: the real run, a run on the run page |
| `/prune dry` | the same with `run --dry-run`: says "would ...", changes nothing, takes no lock |
| `/prune plan` | `$P plan`: the planned actions per job and the facts, no run, no change (`--json` for data) |
| `... --field NN` | only field NN (repeatable), for any call |
| `/prune h`, `/prune help` | print this table and stop |

`hal2-cli-runs` missing (`command -v` fails): run `$P run` alone and say there is no run page then. `$P` exits 2 when a
tool it needs is missing (`bash $S/check-prerequisites.sh` names it): report which, never use another way.

## Order and rules

Fixed in code, not judgment (the record [.adr/prune-order.md](../../../../../../../.adr/prune-order.md), guide
[docs/prune.md](../../../../../../../docs/prune.md)):

1. `facts` (disk, config, per field kind, session, proof, size) and `stale-pointers` (a `CURRENT_PLAN` naming a
   finished or missing plan on a field with nothing unsaved and no session is cleared) run on every run. A plan
   reads the farm's facts in batches, each on first use: one `ps -A` (cleanup's `busy`), one `git for-each-ref` with
   `%(ahead-behind:origin/<default>)` and one `hal2-cli-plans list --json` serve all fields; a case a batch cannot
   answer (a HEAD that is no branch tip, a plan only the field knows) is asked per field as before, and every
   action's proof re-reads its one field.
2. `phase-1`: fields the proof calls free: 10-99 removed (an idle session stopped by signal first), 00-09 only mucked
   out, the last train's cars first, then the biggest.
3. `phase-2` (session-less fields not free, free 00-09 included) and `phase-3` (idle live fields) trim the `trim`
   paths, only while the disk is under the threshold (default under 150 GB free or over 90% used) and then until the
   goal (250 GB free, at most 85% used).
   `responses` follows (plan 0472): while the disk is still above the goal, `tart prune --entries caches
   --older-than=<days>` (Tart's OCI and IPSW caches, never a VM; `[caches] tart_older_than_days`, default 7) and the
   contents of the folders `[caches] paths` lists (none by default; never a pattern, a field or a parent of one). Each
   is planned with its measured size, asked again for a train (`busy`) and the goal before it runs; no tart is said and
   skipped. `run --responses` does only these (the tollman's start). None of trims, muck outs, responses and size
   walks run while a train builds or a workqueue hold stands.
4. A servant 30-99 goes only once its commits are in its foreman's `origin` branch; else the report asks.
5. Every action through the proof again just before; a removal has no timeout; a half-removed field is resumed only
   when prune's own journal shows it began the removal.

## Run

1. Run the call. It prints `run <id>` first on stderr: tell the user the id and that `hal2-cli-runs show <id>` or the
   CI Runs page shows its jobs (`facts`, `stale-pointers`, `phase-1`, `phase-2`, `phase-3`, `report`) and a step
   `field <NN>` per action. A real run may take minutes (size walks, removals): run it in the background when the
   harness allows and say so.
2. Read the `report` job's last lines: the table field, action, bytes, why; free space before and after; the last line
   `prune: <n> actions, <bytes> freed, <n> asks`.
3. For each line `ask the foreman of field FF about field NN`, `SendMessage` to that foreman (`ListAgents` finds the
   session of repo + field FF): "field NN is a servant field of yours with commits that may not be in your branch;
   push or merge what you need and tell me, or say it can go; prune only removes it once they are in `origin/<FF>`".
   If no session of FF runs, say so. Prune is run again after the answer (`/prune --field NN`).
4. Exit codes: 0 done (also `already running: <run id>`, another prune holds the farm lock: no failure, say whose),
   1 an action failed (name it from the report; the next run retries it), 2 a tool missing.
5. Reply in few words: the run id, what was freed, the asks sent, what is left (`left` rows with their reasons).
   `/prune plan` and `/prune dry` print the script's lines as they are.

The farm's thresholds, goal and `trim` paths are `.hal/prune.toml` (keys in the run contract of plan 0377); a missing
file means the defaults. The tollman runs `/prune`'s script itself when a landed field or the disk calls for it.
