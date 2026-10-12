---
id: SI-0005
skill: hal-lc-finalize
status: proposed
category: wrong-default
severity: medium
mechanical: true
occurrences: 1
first_seen: 2026-09-25
last_seen: 2026-09-25
---

Finalize step 4 commits the detach diff, and the `hal git commit` chokepoint (required by /gcp) mints and
binds a fresh micro-plan when no plan is active, which is exactly the state detach just produced (here:
0004-choreplan-detach-0001-0002-0003, left active with a CURRENT_PLAN breadcrumb). Finalize then ends with an
active plan again, and committing that plan's own detach through the chokepoint would mint the next one.
Finalize also assumes a hal worktree slot; on the main checkout `/mfm`, the slot lookup and `/mdtm` don't apply.

**Recommendation:** give `hal git commit` a `--plan <slug>` (bind the detached plan explicitly) or a
`--no-mint` flag, and have finalize use it; document a main-checkout path (skip mfm/mdtm, push instead).
