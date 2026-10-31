"""The open train (hal2 plan 0490 step 20; D20, D21, D23; the plan's open-train-brief.md, point 1): a formed train
takes newly hitched wagons until its push starts.

The next train forms on the green merge job of the train before (minute.next_train, trains.settle on a `shipping`
result with its commit: plan 0383 step 6, D21's "after the main merge in the mtm was successful"); its landing's
process pretests it, then waits in next_train.wait while the run before still runs. All that wait the train is open:
each poll `take` drafts the wagons hitched since onto the carrier's head as the round's draft does (trains.draft:
queue order, a place the user holds ahead, adjacent production wagons only, the trial merge, the proof, the alone
rule) and `join`s the clean, proven ones, one car at a time, in queue order. Its cars freeze once the run before has
concluded as a whole (D23: status `completed`, every job done, success or failure): the wait ends, nothing joins
after it, the push starts; a wagon hitched later waits for the next train. Nothing ever leaves the train
(frozen.py, plan 0360 D3): a join only adds.

`join` is the one place a car is added after forming, run only by the landing's own process (the carrier's worktree
is its own while it lives, so there is no CLI verb): the car merged into the carrier (frozen.merge_car; generated
files written again as `form` does), the pretest of only the jobs the car's own range selects (`check`: `gate plan`
over the barn's merge base .. the car's head, then pretest.pretest with `only`; the rest is the train's pretest,
whose green markers cache it), the queue's mark refreshed with every car (`--train/--attempt` of the start that runs;
hal2-cli-git takes it while the carrier's landing waits or runs until its push begins, cars only growing, and refuses
it after: plan 0490 row 24, D24), then the process's `--pid` again (a standing train's re-mark replaces its pid; one
whose landing owns the ticket keeps it, the stamp is refused then and changes nothing), the CURRENT_PLAN pointer
rewritten (the land run's title) and a `joined` line (train_state: its cars count from then on). Its own undo, as
`form`'s (frozen.py): a car that does not merge, a red pretest, a mark the queue refuses put the carrier back on the
head it had before the call and write a `declined` line; that head of that field never joins this train again and
rides the next one's draft (whose pretest tells its foreman). A join never makes the train red.

Speed first (D9): a join starts only while the run before still runs, so a train whose run before has concluded
pushes at once; a join's pretest is bounded by the pretest's budget and runs only the new car's jobs. Nothing joins
in smuggle mode or while the sleep flag stands, under a hold, to a train without a number, or to a train whose car
rides alone (gate_car.py); a wagon that would ride alone waits, and so do the wagons behind it (the order rule).

`take` is one round of joining; the wait for the post-merge reds' fix cars (fix_wait.py, plan 0490 step 21, D22) calls
it on after the run before has concluded, each round while a red job still lacks its fix car or a named reason.
"""

import os
import subprocess
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import frozen
import gate_car
import generated
import hold
import modes
import mtm_scan
import pretest
import pretest_train
import train_branch
import train_state
from carrier import git
from tick import default_ref

PLAN_SECONDS = 60  # `gate plan` over one car's range (pretest_train.BLAME_SECONDS likewise)


def take(top: str, main: str) -> list[str]:
    """One round of the open train in its carrier `top`: the wagons that join now, one at a time; the lines printed.
    A declined car ends the round (the next poll drafts again on the carrier's head)."""
    lines, train = [], train_state.standing(train_state.lines(main))
    if not train or train["carrier"] != Path(top).name or not train_branch.numbered(train):
        return []
    doc = mtm_scan.run_json(mtm_scan.QUEUE, main) or {}
    if modes.asleep(modes.of(doc), doc.get("queue", []), modes.flag(main)) or hold.of(main):
        return []
    for car in joiners(main, top, train, doc):
        code, text = join(top, main, train, car)
        lines.append(text)
        print(text, flush=True)
        if code:
            break
        train = train_state.standing(train_state.lines(main))
    return lines


def joiners(main: str, top: str, train: dict, doc: dict) -> list[dict]:
    """The cars the round's draft would take now on the carrier's head, the train's own cars and declined heads left
    out; none when the train or the first of them rides alone."""
    import trains  # the round's draft: loaded only when the wait looks for wagons
    default, carrier = default_ref(main), Path(top).name
    if any(gate_car.alone_why(main, default, c["head"]) for c in train["cars"]):
        return []
    riding = {c["field"] for c in train["cars"]}
    declined = {(d.get("field"), d.get("head")) for d in train.get("declined", [])}
    tickets = [t for t in doc.get("queue", []) if t.get("slot") not in riding
               and (t.get("slot"), (t.get("ready") or {}).get("head")) not in declined]
    head = git(top, "rev-parse", "HEAD")[1]
    d = trains.draft(main, tickets, carrier, head, default, modes.of(doc))
    return [] if d["alone"] else d["cars"]


def join(top: str, main: str, train: dict, car: dict) -> tuple[int, str]:
    """The car added to the standing train in its carrier `top` (the module doc): 0 and its line, else 1 and why it
    was declined (the carrier back on its head before)."""
    import engine  # its `cli` (hal2-cli-git); engine imports next_train, which imports this module
    carrier, name = Path(top).name, train["train"]
    branch, pre = git(top, "branch", "--show-current")[1] or carrier, git(top, "rev-parse", "HEAD")[1]
    code, out, taken = frozen.merge_car(top, branch, car)
    if code:
        git(top, "merge", "--abort")
        return decline(top, main, train, car, pre, f"it did not merge: {out[-200:]}")
    fields = [c["field"] for c in train["cars"]] + [car["field"]]
    if taken and (made := generated.regenerate(top, sorted(set(taken)), fields))[0]:
        return decline(top, main, train, car, pre, made[1][-200:])
    r = check(top, train_state.folder(main), default_ref(top), car)
    if r["result"] == "red":
        job = next((j["job"] for j in r["jobs"] if j["result"] == "red"), "?")
        return decline(top, main, train, car, pre, f"its pretest is red: {job} ({r['log']})")
    mark = ["--train", str(train["number"]), "--attempt", str(max(1, train["starts"]))]  # the start that runs
    code, out = engine.cli(["worktree", "queue", "train", carrier, *fields, *mark, "--json"], top)
    if code:  # also once the landing began its push: the cars are frozen (row 24)
        return decline(top, main, train, car, pre, f"the queue refused the mark: {out[-200:]}")
    engine.cli(["worktree", "queue", "train", carrier, "--pid", str(os.getpid()), "--json"], top)  # see the doc
    frozen.write_current(top, train["cars"] + [car], bool(train.get("yard")))
    commit = git(top, "rev-parse", "HEAD")[1]
    train_state.append(main, "joined", carrier, train=name, cars=[car], base=pre, commit=commit, result=r["result"],
                       seconds=r["seconds"], jobs=r["jobs"], why=r["why"] or None)
    return 0, (f"open train {name}: field {car['field']} ({car.get('plan') or car['branch']}) joined, "
               f"pretest {r['result']}" + (f" ({r['why']})" if r["why"] else ""))


def decline(top: str, main: str, train: dict, car: dict, pre: str, why: str) -> tuple[int, str]:
    """The join undone: the carrier back on `pre`, a `declined` line (that head never joins this train again)."""
    git(top, "reset", "-q", "--keep", pre)
    train_state.append(main, "declined", Path(top).name, train=train["train"], field=car["field"], head=car["head"],
                       why=why)
    return 1, f"open train {train['train']}: field {car['field']} waits for the next train: {why}"


def check(top: str, state: Path, base_ref: str, car: dict, config: Path | None = None,
          gate: Path | None = None) -> dict:
    """The pretest of the carrier's head for only the jobs the car's own range selects (the barn's merge base .. its
    head): pretest.pretest's result; `none` without a config or a job, `skipped` when the gate cannot say."""
    cfg_path, gate = config or Path(top) / pretest.CONFIG, gate or Path(top) / pretest.GATE
    empty = {"result": "none", "seconds": 0, "jobs": [], "why": "", "log": str(state / pretest_train.LOG)}
    if not pretest.read_config(cfg_path)[0]:
        return empty
    try:
        start = pretest.git(top, "merge-base", base_ref, car["head"]) or base_ref
        only = set(pretest.plan(top, gate, start, car["head"], PLAN_SECONDS))
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as e:  # NoBuild is a RuntimeError
        return {**empty, "result": "skipped", "why": f"the car's jobs are not known: {e}"[:300]}
    if not only:
        return {**empty, "why": "the car's range selects no job"}
    return pretest.pretest(top, state, base_ref, state / pretest_train.LOG, cfg_path, gate, only=only)
