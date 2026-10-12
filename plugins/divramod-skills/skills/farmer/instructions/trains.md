# Woken for merge trains (trains)

The tick puts every waiter behind the current run whose trial merge is clean into one train (the holder carries
while its candidate is not pushed, else the first waiter) and tells carrier and passengers itself
([merge-train](../subskills/merge-train/SUBSKILL.md)); a parallel plan's subservant (a slot with `plans/LEAD`)
never lands, so it never rides, as carrier or passenger. You get what needs a look. Check it is still true
(`hal2-cli-git worktree queue --json`), act, then log it:
`python3 $S/mtm_scan.py record <kind> <slot> "<what you did>" --note "<why>"`.

| Kind | Do |
|---|---|
| `train-failed` | The carrier's landing failed while it carried a train (the item names the train and the failure). Find the change that broke it (the failing task's files against each passenger's diff: `git diff --name-only origin/<default>...<branch>`). A passenger's: tell the carrier to reset that merge (`git reset --hard ORIG_HEAD`, or a revert of that merge commit when more followed) and land without it, and tell that passenger to `/mfm` and land alone. The carrier's own change or unclear: tell the carrier to reset every passenger merge and land alone; the passengers land alone after `/mfm`. Never reset a slot's work yourself |

A passenger keeps its ticket throughout; once the carrier has landed its follow-up landing is quick. Never: stop a
landing that has merged into main, force-push, touch a slot's branch yourself.
