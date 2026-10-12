# Woken for prune (prune)

The tick does the duty itself (`prune.py`, hal2 plan 0143): every round it checks each numbered slot 00-99 and
prunes the free ones; nothing of it needs you unless it failed. A slot is free when nothing in it is unsaved: no
commit (its branch or a side branch `NN-*`) that origin's default branch lacks, no change, no `plans/CURRENT_PLAN`,
no merge queue ticket or boss pause, no busy agent, no session active in the last 30 minutes (10-99), no build
running in it and no open question to the user. Main, the role slots (`farmer-<repo>`, ...) and other names are
never touched.

- **00-09**: `prune.py clean NN` deletes the build artifacts (the cleanup skill), once per landing (keyed on HEAD).
- **10-99**, one per round: `prune.py remove NN` stops the idle session by signal (delete-worktree-session's
  `stop.py` through `hal2-cli-agents stop`, never a typed `/exit`: hal2 plan 0212; a draft or running background
  tasks refuse it), then runs
  `hal2-cli-git worktree remove NN --remote` (the local branch, and `origin/NN` once merged). The user allowed
  stopping any idle session there holding no work, also their own (2026-10-06, answer 2a).
- **Subservants' slots** (`plans/LEAD`, skills plan 0013): never measured against main. A marked slot 30-99 is
  free once HEAD, `origin/NN` and every side branch `NN-*` are in `origin/<lead>`, nothing is uncommitted, no ticket
  or busy agent, no session active and no `plans/LEAD` written in the last hour, no build runs; `prune.py remove NN`
  fetches and checks again, runs `hal2-cli-git worktree remove NN --force` (its branch is not on main by design),
  then `git push origin --delete NN` once `origin/NN` is in `origin/<lead>`. A marked slot below 30 is never pruned,
  nor one whose marker is broken (still marked, its lead unknown).
- **Disk**: every 6 hours a log line with the free disk and the 5 biggest worktrees (in the round summary), a notice
  for the user under 100 GB free. `du` over every worktree takes minutes, so the round starts it detached
  (`prune.py sizes`, one at a time, into `disk.json`) and the next round reports it.

`python3 $S/prune.py scan` lists every slot and why it is not free. A `run` of the duty that failed (its exit in the
log) needs a look: read its output, run `prune.py scan`, and leave a slot that holds anything alone. Log what you
did: `python3 $S/mtm_scan.py record prune <slot> "<what you did>" --note "<why>"`. Never remove a slot by hand that
`prune.py` refuses, never `--force` a removal yourself (only `prune.py remove` does, for a free subservant slot).
