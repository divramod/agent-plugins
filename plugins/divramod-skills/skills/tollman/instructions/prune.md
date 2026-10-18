# Woken for prune (prune)

The tick does the duty itself (`prune.py`, hal2 plan 0143; the farmer's until plan 0360 step 7, D8, D30): every round
it checks each numbered field 00-99 and prunes the free ones; nothing of it needs you unless it failed or a car of a
landed train is stuck. A field is free when nothing in it is unsaved (`prune_proof.py`, the global record
never-delete-unsaved-work): no commit (its branch or a side branch `NN-*`) that origin's default branch lacks, no
change, no `plans/CURRENT_PLAN`, no merge queue ticket or boss pause, no busy agent, no session active in the last 30
minutes (10-99), no build running in it and no open question to the user (your log and the farmer's). Main, the role
fields (`farmer-<repo>`, `tollman-<repo>`, ...) and other names are never touched.

- **00-09**: `prune.py clean NN` deletes the build artifacts (the cleanup skill), once per landing (keyed on HEAD).
- **10-99**, one per round, the cars of the last landed train first: `prune.py remove NN` stops the idle session by
  signal (delete-field's `stop.py` through `hal2-cli-agents stop`, never a typed `/exit`: hal2 plan 0212;
  a draft or running background tasks refuse it), then runs `hal2-cli-git worktree remove NN --remote` (the local
  branch, and `origin/NN` once merged). The user allowed stopping any idle session there holding no work, also their
  own (2026-10-06, answer 2a).
- **After the barn** (`barn.py`, plan 0360 step 7): a car 00-09 of the last landed train that is free and mucked out
  (the `clean` of its HEAD ran) has its resting session cleared once (`hal2-cli-agents clear-and-continue --pane
  <pane> --without-plan --prompt /mfm --detach`, key `barn-clear:<NN>:<HEAD>`): its foreman ends its turn after the
  report and never clears itself.
- **Servants' fields** (`plans/LEAD`, the foreman's marker, skills plan 0013): never measured against main. A marked
  field 30-99 is free once HEAD, `origin/NN` and every side branch `NN-*` are in `origin/<foreman's branch>`, nothing
  is uncommitted, no ticket or busy agent, no session active and no `plans/LEAD` written in the last hour, no build
  runs; `prune.py remove NN` fetches and checks again, runs `hal2-cli-git worktree remove NN --force` (its branch is not
  on main by design), then `git push origin --delete NN` once `origin/NN` is in `origin/<foreman's branch>`. A marked
  field below 30 is never pruned, nor one whose marker is broken (still marked, its foreman unknown).
- **Disk**: every 6 hours a log line with the free disk and the 5 biggest fields (in the round summary), a notice
  for the user under 100 GB free. `du` over every field takes minutes, so the round starts it detached
  (`prune.py sizes`, one at a time, into `disk.json` of your state folder) and the next round reports it.

| Wake | What you do |
|---|---|
| `failed` | A `run` of the duty failed (its exit in the log): read its output, run `python3 $S/prune.py scan`, and leave a field that holds anything alone. |
| `barn-stuck` | A car of the last landed train still holds work 24 hours after the landing (key `barn-stuck:<NN>:<HEAD>`, once). New work of its foreman is fine: nothing to do. Work left behind (an unpushed commit, a forgotten change, a `CURRENT_PLAN` of a finished plan): tell its foreman in one line; a field with no session: leave the farmer a board note (`board.py post --kind note --from tollman-<repo> --to farmer-<repo> --text ...`; it reads it when it asks). Never remove it. |

Log what you did: `python3 $K/farmer/scripts/mtm_scan.py record prune <slot> "<what you did>" --note "<why>" --role
tollman`. Never remove a field by hand that `prune.py` refuses, never `--force` a removal yourself (only `prune.py
remove` does, for a free servant's field).
