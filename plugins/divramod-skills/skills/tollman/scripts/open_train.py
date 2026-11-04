"""The open train (hal2 plan 0490 step 20; D20, D21, D23; plan 0610 D17, audit E3-E6, E8, E10): a standing train
takes every newly hitched wagon until its push starts, in every state before it (formed, resolving, red, fixing,
retry, and its landing before the push); after the push a wagon rides the next train. Nothing ever leaves the train
(frozen.py, plan 0360 D3) and nothing is declined (E6): a join only adds.

`joiners` drafts the hitched wagons on the carrier's head as the round's draft does (trains.draft: queue order, a
place the user holds ahead, adjacent production wagons only, the trial merge, the proof, the alone rule, no minimum):
every car of it joins, with what it needs (`conflict`, `proof_red`, `proof_unknown`, `untried`, `carried`: a hand
merge the carrier holds already is recorded so, E8). A riding field whose ticket holds a newer head joins again: its
newer head takes its car's place (E10). The train's own cars at their heads stay out.

- Outside a landing (`OPEN`): the round (trains.plan) runs `tollman.py join <field> --car <json>` per joiner
  (train_join.record): a `joined` line (`merged` false) and the queue's mark; the next start merges it
  (engine.restart: resolve_train.merge_rest, a conflict waits `resolving` with its resolve order), and a car with red
  light checks makes that start red with its fix order first (proof_orders.py). In `resolving` the carrier stays as
  it is until the resolve; `merge_rest` merges the joiners behind it.
- In its landing, before the push (`take`, the landing's own process: next_train.before_push each poll of its wait,
  of the fix wait, and once more right before the push, also when no run before runs, E4): `join` merges the car
  into the carrier (frozen.merge_car; generated files written again as `form` does), pretests only the jobs its own
  range selects (`check`), refreshes the queue's mark (`--train/--attempt` of the start that runs; then its `--pid`
  again) and the CURRENT_PLAN pointer, and writes its `joined` line. A conflict joins with its resolve order (the
  train waits `resolving`, resolve_train.wait); a red pretest joins with `proof_red` and `pretest_red` (its fix order,
  E6); a refused mark is noted, never a decline (the next start marks it). `stops` (engine.land, right before the
  push): the push waits while a joined car waits for its resolve, a car is unmerged (the landing ends `interrupted`,
  the restart merges it) or a car's light checks are red with no fix order yet (the train goes red `proof_red`).

Nothing joins in smuggle mode or while the sleep flag stands, under the user's hold, to a train without a number, or
to a train whose car rides alone (gate_car.py); a wagon that would ride alone waits for its own train (D9): hitched
while the train stands, it goes on that train's `alone_next` (`owe`, an `alone` line; the round's `tollman.py join
<field> --alone`), so it rides alone in the very next train (D15).
"""

import json
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
import proof_orders
import train_branch
import train_state
from carrier import git
from tick import default_ref

PLAN_SECONDS = 60  # `gate plan` over one car's range (pretest_train.BLAME_SECONDS likewise)
OPEN = ("formed", "resolving", "red", "fixing", "retry")  # a join is recorded (train_join.record), merged at the start


def pushed(train: dict) -> bool:
    """Whether the standing train's current start pushed (its `push` line): no join after it."""
    return train.get("state") == "landing" and bool(train.get("head"))


def take(top: str, main: str) -> list[str]:
    """One round of the open train in its landing (the carrier `top`, the landing's own process, before the push):
    the joiners merged one at a time; the lines printed. A join that stops the push ends the round."""
    lines, train = [], train_state.standing(train_state.lines(main))
    if not train or train["carrier"] != Path(top).name or train["state"] != "landing" or pushed(train) \
            or not train_branch.numbered(train):
        return []
    doc = mtm_scan.run_json(mtm_scan.QUEUE, main) or {}
    if modes.asleep(modes.of(doc), doc.get("queue", []), modes.flag(main)) or hold.of(main):
        return []
    cars, alone = round_of(main, top, train, doc.get("queue", []), modes.of(doc))
    for text in owe(main, train, alone):
        lines.append(text)
        print(text, flush=True)
    for car in cars:
        code, text = join(top, main, train, car)
        lines.append(text)
        print(text, flush=True)
        if code:
            break
        train = train_state.standing(train_state.lines(main))
    return lines


def candidates(main: str, train: dict, tickets: list[dict]) -> list[dict]:
    """The hitched tickets that may join: a field no car of the train, or a riding field whose ready head is newer than
    its car's (E10); a car at its own head, or an older head of it, never."""
    heads, out = {c["field"]: c["head"] for c in train["cars"]}, []
    for t in tickets:
        head = (t.get("ready") or {}).get("head")
        old = heads.get(t.get("slot"))
        if not head or head == old or old and git(main, "merge-base", "--is-ancestor", head, old)[0] == 0:
            continue
        out.append(t)
    return out


def draft(main: str, top: str, train: dict, tickets: list[dict], mode: dict | None) -> dict | None:
    """The round's draft on the carrier's head for the candidates, or None (no candidate, or the train has a car that
    rides alone)."""
    import trains  # the round's draft: loaded only when a wagon may join
    if not (them := candidates(main, train, tickets)):
        return None
    default, carrier = default_ref(main), Path(top).name
    if any(gate_car.alone_why(main, default, c["head"]) for c in train["cars"]):
        return None
    head = git(top, "rev-parse", "HEAD")[1]
    return trains.draft(main, them, carrier, head, default, mode)


def joiners(main: str, top: str, train: dict, tickets: list[dict], mode: dict | None) -> list[dict]:
    """Every car the draft takes now (`draft`), a conflict and red light checks too (E5); none when the first of them
    rides alone (it waits for its own train)."""
    return round_of(main, top, train, tickets, mode)[0]


def round_of(main: str, top: str, train: dict, tickets: list[dict], mode: dict | None) -> tuple[list[dict], list[dict]]:
    """One draft's joiners and its alone cars ({field, head, why}: a wagon that would ride alone, hitched while the
    train stands, rides alone in the very next train, plan 0610 D15), the train's own owed ones left out."""
    if not (d := draft(main, top, train, tickets, mode)):
        return [], []
    heads = {t.get("slot"): (t.get("ready") or {}).get("head") for t in tickets}
    whys = {w["field"]: w["why"] for w in d["waiting"] if w.get("reason") == "alone"}
    fields = [c["field"] for c in d["cars"]] if d["alone"] else d["alone_next"]
    owed = set(owed_now(train_state.lines(main)))
    alone = [{"field": f, "head": heads.get(f), "why": whys.get(f) or "it rides alone (gate_car.py)"}
             for f in fields if heads.get(f) and f not in owed]
    return ([] if d["alone"] else d["cars"]), alone


def actions(top: str, main: str, train: dict | None, tickets: list[dict], mode: dict | None) -> list[dict]:
    """The open train's join round outside its landing (trains.join_actions; plan 0610 D17, E3, E4: every round while
    it stands unpushed, also before its first start): a `tollman.py join <field> --car <json>` per joiner, each a car
    from then on, merged by the train's next start (train_join.record), and a `tollman.py join <field> --alone <json>`
    per alone car (`owe`, D15). Its landing joins in its own process (`take`)."""
    import trains  # its `run` actions; trains loads this module only while a train stands
    import train_wt
    at = train_wt.folder(train, top) if train else ""
    if not train or train["state"] not in OPEN or train_wt.astray(at, train) or not Path(at).is_dir():
        return []
    cars, alone = round_of(main, at, train, tickets, mode)
    name, state = train["train"], train["state"]
    owe_runs = [trains.run("join", "-", f"alone:{name}:{c['field']}@{c['head'][:12]}", "join", top, c["field"],
                           "--alone", json.dumps(c), window=0, script=trains.TOLLMAN,
                           text=f"open train {name} ({state}): field {c['field']} rides alone in the very next train, "
                                "its own (plan 0610 D15)") for c in alone]
    flags = lambda c: "".join(f", {k}" for k in trains.JOIN_FLAGS if c.get(k))  # noqa: E731
    return owe_runs + [trains.run("join", "-", f"join:{name}:{c['field']}@{c['head'][:12]}", "join", top, c["field"],
                                  "--car", json.dumps(c), window=0, script=trains.TOLLMAN,
                                  text=f"open train {name} ({state}): field {c['field']} joins{flags(c)}")
                       for c in cars]


def owed_now(rows: list[dict]) -> list[str]:
    """The alone cars owed their own train next: the last `formed` line's `alone_next`, then every `alone` line after
    it (plan 0610 D15; trains.owed)."""
    out: list[str] = []
    for e in rows:
        if e.get("kind") == "formed":
            out = list(e.get("alone_next") or [])
        elif e.get("kind") == "alone" and e.get("field") and e["field"] not in out:
            out.append(e["field"])
    return out


def owe(main: str, train: dict, cars: list[dict], now=None) -> list[str]:
    """Each alone car not owed yet put on the standing train's `alone_next` (an `alone` line): its lines."""
    lines, owed = [], set(owed_now(train_state.lines(main)))
    for c in cars:
        if c["field"] in owed:
            continue
        train_state.append(main, "alone", train["carrier"], now, train=train["train"], field=c["field"],
                           head=c["head"], why=c["why"])
        owed.add(c["field"])
        lines.append(f"open train {train['train']}: field {c['field']} rides alone in the very next train, its own "
                     f"({c['why']})")
    return lines


def join(top: str, main: str, train: dict, car: dict, now=None) -> tuple[int, str]:
    """The car added to the landing train in its carrier `top` (the module doc): 0 and its line, or 1 and its line
    when the push must wait (a conflict's resolve, or a car left unmerged for the next start)."""
    import engine  # its `cli` (hal2-cli-git); engine imports next_train, which imports this module
    carrier, name, what = Path(top).name, train["train"], f"field {car['field']} ({car.get('plan') or car['branch']})"
    branch, pre = git(top, "branch", "--show-current")[1] or carrier, git(top, "rev-parse", "HEAD")[1]
    code, out, taken = frozen.merge_car(top, branch, car)
    if code:  # E6: it joins with its resolve order; the train waits `resolving`, the push for the resolve
        import resolve_train
        train_state.append(main, "joined", carrier, now, train=name, cars=[car], base=pre, commit=pre, merged=False,
                           result="conflict")
        text = resolve_train.wait(top, main, train_state.standing(train_state.lines(main)), car, [], now)[1]
        return 1, f"open train {name}: {what} joined with a conflict, the push waits for its resolve: {text}"
    cars = train_state.add_cars(train["cars"], [car])
    if taken and (made := generated.regenerate(top, sorted(set(taken)), [c["field"] for c in cars]))[0]:
        git(top, "reset", "-q", "--keep", pre)
        train_state.append(main, "joined", carrier, now, train=name, cars=[car], base=pre, commit=pre, merged=False,
                           result="none", why=f"its generated files were not written again: {made[1][-200:]}")
        return 1, f"open train {name}: {what} joined unmerged ({made[1][-120:]}): the next start merges it"
    r = check(top, train_state.folder(main), default_ref(top), car)
    if r["result"] == "red":  # E6: rides with its fix order (proof_orders.py), the push waits for it (`stops`)
        jobs = [j["job"] for j in r["jobs"] if j["result"] == "red"] or ["?"]
        car = {**car, "pretest_red": jobs, "proof_red": [*(car.get("proof_red") or []),
                                                         *(f"{j}: its join pretest is red ({r['log']})" for j in jobs)]}
        cars = train_state.add_cars(train["cars"], [car])
    mark = ["--train", str(train["number"]), "--attempt", str(max(1, train["starts"]))]  # the start that runs
    code, out = engine.cli(["worktree", "queue", "train", carrier, *(c["field"] for c in cars), *mark, "--json"], top)
    if not code:  # the stamp: a re-mark replaces the mark's pid
        engine.cli(["worktree", "queue", "train", carrier, "--pid", str(os.getpid()), "--json"], top)
    frozen.write_current(top, cars, bool(train.get("yard")))
    train_state.append(main, "joined", carrier, now, train=name, cars=[car], base=pre,
                       commit=git(top, "rev-parse", "HEAD")[1], result=r["result"], seconds=r["seconds"],
                       jobs=r["jobs"], why=r["why"] or None, mark=out[-200:] if code else None)
    return 0, (f"open train {name}: {what} joined, pretest {r['result']}" + (f" ({r['why']})" if r["why"] else "")
               + (f"; the queue refused the mark ({out[-120:]}): the next start marks it" if code else ""))


def stops(top: str) -> int:
    """engine.land's look right before the push (the module doc): 1 when the push waits, with its line printed."""
    main = mtm_scan.main_checkout(top)
    train = train_state.standing(train_state.lines(main))
    if not train:
        return 0
    if train["state"] == "resolving":
        print(f"tollman: train {train['train']} is resolving: a car that joined waits for its resolve, no push",
              flush=True)
        return 1
    if lacking := frozen.lacking(top, train):
        print(json.dumps({"status": "interrupted", "message": f"car {', '.join(lacking)} joined unmerged: the next "
                          "start merges it"}), flush=True)
        return 1
    if red := proof_orders.red_line(main, Path(top).name, train):
        print(json.dumps({"status": proof_orders.STATUS, "message": red[:300]}), flush=True)
        return 1
    return 0


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
