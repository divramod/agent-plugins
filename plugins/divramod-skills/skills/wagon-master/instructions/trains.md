# Woken for wagon trains (trains)

The tick forms, starts and settles the trains itself (the ready wagons in queue order, the trial merge, the own
field as carrier, the detached landing, "in the barn" to every car, a conflicting wagon unhitched with its reason:
[merge-train](../subskills/merge-train/SUBSKILL.md)); a field 30-99 never rides. No car rides without its light gate
checks (names, records) green on its hitched head (`proof.py`): a red one is unhitched and told the finding lines, a
field not at its hitched head waits ("no proof yet"), never a wake. You get what needs judgment. Check it
is still true (`python3 $S/wagon_master.py train --dry-run`, `hal2-cli-git worktree queue --json`), act, then log it:
`python3 $K/farmer/scripts/mtm_scan.py record <kind> <slot> "<what you did>" --note "<why>" --role wagon-master`.

Before you act: read the learnings (`python3 $S/learnings.py rules`, the file `roles/wagon-master/learnings.md`) and
apply their rules. After you handled a red train, an error or a by-hand fix, write one entry
(`python3 $S/learnings.py add --case ... --cause ... --rule ... --code y|n`, [SKILL.md](../SKILL.md#act)).

| Kind | Do |
|---|---|
| `train-failed` | The train's landing did not land (the item names the train, the status, the run and the cars). Read the red job (`gh run view <run> --log-failed`) and reproduce it with `code/bash/scripts/gate/main.sh <job> --branch origin/main` where the repository has it. **One car broke it** (the failing task's files against each car's diff, `git diff --name-only origin/<default>...<branch>`): `python3 $S/wagon_master.py unhitch <field> --why "<job and cause>"`; its foreman is told, and the same call breaks the train up and forms the rest (its output ends `chain stops: <why>`). **The cause is not a car** (a runner that died, a network error, a test that fails alone on the barn too): `python3 $S/wagon_master.py retry --why "<why>"` sends the same train again whole. **The barn itself is red** (the same job fails on `origin/<default>`): `python3 $S/engine.py breakup --why "<why>"`, tell the farmer in one line, the wagons ride again after the fix. Unclear after one look: unhitch nothing, retry once, and look again at the next failure |
| `train-failed`, status `pretest_red` | The local pretest before the push was red: nothing was pushed, no run. The item names the job and the suspect car(s), whose own range selects the job. Read the job's output in `roles/wagon-master/train-pretest.log` and reproduce it in the own field with `code/bash/scripts/gate/main.sh <job> --branch origin/main`. Then as above: unhitch the named car, `breakup` when the barn is red, `retry` when it is not a car and may pass now (a flaky job: a retry pretests again). The red is the Mac's, not a car's (it fails on this Mac only, e.g. a tool or path of this machine, while CI's job passes): `python3 $S/wagon_master.py retry --skip-pretest --why "<why>"`, the train lands without its pretest |
| `train-failed`, the yard as the cause | The train's title starts with `yard + ` and the failing task's files are the yard's commit (`train.jsonl`'s `yard` line names them; the dry run's `yard: placed:` lines show what rides next): `python3 $S/wagon_master.py unhitch yard --why "<job and cause>"`. The files stay in the yard, out of every train until they change; the farmer is told, and the cars ride again. Never edit the yard's files |
| `train-stuck` | An engine verb failed (the item names the verb and the command). Run the command to see why, then `python3 $S/wagon_master.py train --dry-run`. A leftover mark or a field in a state the engine does not expect: `python3 $S/engine.py breakup --why "<why>"` clears the mark and releases the queue; then the next round forms the train again. Not fixable here (a git or `hal2-cli-git` fault): notify the user |

**Composition, order and the alone rule are yours** ([wagon-master-decides-trains](https://github.com/divramod/hal2/blob/main/.adr/wagon-master-decides-trains.md)): which wagons ride together, in what order,
what rides alone. Decide by the trial merge and the queue order (a tie goes to the wagon that hitched first), record it
(`mtm_scan.py record` as above, with the reason in `--note`), report it to the foreman it concerns, and never ask the
user; a question only the user can answer goes to `farmer-<repo>`.

Never: stop a landing that runs or has merged into the default branch, force-push, edit, reset or merge another
field's branch yourself (the foreman restocks and fixes its own crop), unhitch a car of a train that lands (the
command refuses it). A wagon you unhitch is told why by the code; add nothing unless the cause needs the foreman's
judgment. Messages to a foreman that carry a question go through `acks.py instruct <slot> "<text>" --role
wagon-master`.
