# Woken for wagon trains (trains)

The tick forms, starts and settles the trains itself (the ready wagons in queue order, the trial merge, the own
field as carrier, the detached landing, "in the barn" to every car, a conflicting wagon unhitched with its reason:
[merge-train](../subskills/merge-train/SUBSKILL.md)); a field 30-99 never rides. You get what needs judgment. Check it
is still true (`python3 $S/wagon_master.py train --dry-run`, `hal2-cli-git worktree queue --json`), act, then log it:
`python3 $K/farmer/scripts/mtm_scan.py record <kind> <slot> "<what you did>" --note "<why>" --role wagon-master`.

Before you act: read the learnings (`python3 $S/learnings.py rules`, the file `roles/wagon-master/learnings.md`) and
apply their rules. After you handled a red train, an error or a by-hand fix, write one entry
(`python3 $S/learnings.py add --case ... --cause ... --rule ... --code y|n`, [SKILL.md](../SKILL.md#act)).

| Kind | Do |
|---|---|
| `train-failed` | The train's landing did not land (the item names the train, the status, the run and the cars). Read the red job (`gh run view <run> --log-failed`) and reproduce it with `code/bash/scripts/gate/main.sh <job> --branch origin/main` where the repository has it. **One car broke it** (the failing task's files against each car's diff, `git diff --name-only origin/<default>...<branch>`): `python3 $S/wagon_master.py unhitch <field> --why "<job and cause>"`; its foreman is told, the rest forms again at the next round. **The cause is not a car** (a runner that died, a network error, a test that fails alone on the barn too): `python3 $S/wagon_master.py retry --why "<why>"` sends the same train again whole. **The barn itself is red** (the same job fails on `origin/<default>`): `python3 $S/engine.py breakup --why "<why>"`, tell the farmer in one line, the wagons ride again after the fix. Unclear after one look: unhitch nothing, retry once, and look again at the next failure |
| `train-failed`, the yard as the cause | The train's title starts with `yard + ` and the failing task's files are the yard's commit (`train.jsonl`'s `yard` line names them; the dry run's `yard: placed:` lines show what rides next): `python3 $S/wagon_master.py unhitch yard --why "<job and cause>"`. The files stay in the yard, out of every train until they change; the farmer is told, and the cars ride again. Never edit the yard's files |
| `train-stuck` | An engine verb failed (the item names the verb and the command). Run the command to see why, then `python3 $S/wagon_master.py train --dry-run`. A leftover mark or a field in a state the engine does not expect: `python3 $S/engine.py breakup --why "<why>"` clears the mark and releases the queue; then the next round forms the train again. Not fixable here (a git or `hal2-cli-git` fault): notify the user |

Never: stop a landing that runs or has merged into the default branch, force-push, edit, reset or merge another
field's branch yourself (the foreman restocks and fixes its own crop), unhitch a car of a train that lands (the
command refuses it). A wagon you unhitch is told why by the code; add nothing unless the cause needs the foreman's
judgment. Messages to a foreman that carry a question go through `acks.py instruct <slot> "<text>" --role
wagon-master`.
