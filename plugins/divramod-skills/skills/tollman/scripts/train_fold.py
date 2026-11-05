"""The train state's folding (split out of train_state.py by hal2 plan 0610 step 9, small-files): the lines of
`train.jsonl` (train_state.py's module doc names every kind) folded into the train that stands. `train_state`
re-exports every name, so callers keep `train_state.standing`.

`standing` folds the lines into the train that stands, or None between trains: its `state` is `formed` (merged or
merging, no landing started), `resolving` (a car's conflict waits for its foreman's resolve, `resolve`: frozen), `landing` (its pretest's result in `pretest`), `red` (frozen, waits for its fix or the
session's retry), `fixing` (red with fix orders open, `orders`: frozen as red; the post-merge orders, `post`, never
count), `retry` (also once the last order is
`fixed`: `fixed` true, the merge is the new candidate), `paused` (a smuggle paused its landing, `pauses`: frozen,
pause.py), `stopped` (a role car left out twice in a row, plan 0610 D24, `stop`: frozen, never pushed, role_cars.py),
or `split` (the user unhitched a car after red: the rest forms again). `push` is the train's last push, kept across its starts: `head`, `run` (its land run), `red` (a `red`
line named its head; head_guard.py). `attempt` counts the restarts that got past their checks (hal2 plan 0620 D5): each
`started` line raises it with `starts`, each `attempt` line (a restart that started nothing: proof_red, a refused mark)
alone; `attempt(train)` numbers the round's `retry:` key. The landing's own output is the text log `train-landing.log`, rewritten by every
start; `result` is its last JSON line.
"""

ORDER_KEYS = ("id", "field", "branch", "base", "why", "run", "at", "jobs")  # an open order's, as its line has them
RUNNER = "runner"  # a retry's `why` that starts so is the code's after a runner fault (triage.py)
YARD = "yard"  # the yard as a car: no field, never in the queue's mark


def standing(rows: list[dict]) -> dict | None:
    """The train that stands as the lines say (see the module doc), or None."""
    train, carry = None, []  # carry: the post-merge orders a train left open, for the next one (plan 0383 D6)
    for e in rows:
        kind = e["kind"]
        if kind == "formed":
            train = {"train": e.get("train"), "at": e.get("at"), "carrier": e.get("slot"), "cars": e.get("cars", []),
                     "worktree": e.get("worktree"),
                     "base": e.get("base"), "number": e.get("number"), "state": "formed", "starts": 0, "attempt": 0, "pid": None, "unhitched": [], "yard": [],
                     "runner_retries": 0, "land_run": None, "orders": [], "fixed": False, "pauses": [],
                     "in_barn": [], "post": carry, "declined": []}
        elif not train or e.get("train") != train["train"]:
            continue
        elif kind == "yard":
            train["yard"] = e.get("files", [])
        elif kind == "regenerated":
            train["regenerated"] = e.get("commit")
        elif kind == "joined":  # the open train (plan 0490 step 20, plan 0610 D17): a car added, or a car's newer head
            train["cars"] = add_cars(train["cars"], e.get("cars", []))
        elif kind == "declined":
            train["declined"].append({"field": e.get("field"), "head": e.get("head")})
        elif kind in ("resolving", "resolved"):  # every wagon rides (plan 0522 D18): a conflict waits for its resolve
            train.update(state=kind.replace("resolved", "formed"), resolve=e if kind == "resolving" else None)
        elif kind == "pretest":  # incomplete ones in a row: pretest_train.WAITS (plan 0522 D7)
            waits = (train.get("pretest_waits", 0) + 1) * (e.get("result") == "incomplete")
            train.update(pretest=e.get("result"), pretest_tree=e.get("tree"), pretest_waits=waits)
        elif kind == "attempt":  # a restart past its checks that started nothing (plan 0620 D5): its own key
            train["attempt"] = attempt(train) + 1
        elif kind == "started":
            train.update(state="landing", pid=e.get("pid"), starts=train["starts"] + 1, started=e.get("at"),
                         attempt=attempt(train) + 1,
                         land_run=None, fixed=False, since=None, land_ref=e.get("land_ref"), head=None)
        elif kind == "push":  # plan 0560 step 3: the head this start lands, kept as the train's last push
            train.update(head=e.get("head"), push={"head": e.get("head"), "run": None, "red": False})
        elif kind == "run":
            train["land_run"] = e.get("run")
            if train.get("push"):
                train["push"]["run"] = e.get("run")
        elif kind == "red":  # an early order answers the red: the train is `fixing` at once (plan 0383 D5)
            if e.get("head") and e["head"] == (train.get("push") or {}).get("head"):  # its run is red (head_guard)
                train["push"].update(red=True, run=e.get("run") or train["push"]["run"])
            train.update(state="fixing" if any(o.get("early") for o in train["orders"]) else "red",
                         status=e.get("status"), run=e.get("run"), why=e.get("why", ""))
        elif kind in ("order", "fixed"):
            fix(train, e)
        elif kind == "pause":
            train["pauses"].append({k: e.get(k) for k in ("field", "seq", "since", "run")})
            if train["state"] != "paused":
                train.update(paused_from=train["state"], state="paused")
        elif kind == "resumed":
            if train["state"] == "paused":
                resume(train)
        elif kind == "retry":
            runner = str(e.get("why", "")).startswith(RUNNER)
            train.update(state="retry", retried=e.get("why", ""), runner_retries=(train["runner_retries"] + 1) * runner)
        elif kind == "barn":  # a car already in the barn (smuggled, modes.py): a formed train's leaves it (D76)
            train["in_barn"].append(e.get("slot"))
            train["cars"] = [c for c in train["cars"] if e.get("how") != "formed" or c["field"] != e.get("slot")]
        elif kind == "roles":  # the role cars (plan 0610 D18); one left out twice in a row stops the train (D24)
            if e.get("stop"):
                train.update(stopped_from=train["state"], state="stopped", stop=e["stop"])
            elif train["state"] == "stopped" and train["stop"]["field"] in {m.get("field") for m in e.get("merged") or []}:
                train.update(state=train.pop("stopped_from", None) or "formed", stop=None)
        elif kind in ("woke", "alone"):  # only recorded: a foreman started (plan 0522 D21), an alone car owed the next
            pass  # train (plan 0610 D15)
        elif kind == "unhitched":
            train["unhitched"].append({"field": e.get("slot"), "why": e.get("why", ""), "by": e.get("by")})
            train["state"] = "split"
        else:  # landed, cleared: its open post-merge orders ride the next train, a landed one's early ones too
            train, carry = None, train["post"] + carried(train) * (kind == "landed")
    return train


def attempt(train: dict) -> int:
    """The number of the train's restart key `retry:<train>:<n>` (plan 0620 D2, D5): its starts and its restarts
    that started nothing; a state without `attempt` reads `starts` (an old train keeps its key)."""
    return train["attempt"] if train.get("attempt") is not None else train.get("starts") or 0


def restart_key(train: dict) -> str:
    """The round's key of a restart (trains.plan, landing_end.push): `retry:<train>:<attempt>` for a train in
    `retry`, new after every restart past its checks (plan 0620 D5); `resume:<train>` for one formed, never started."""
    return f"retry:{train['train']}:{attempt(train)}" if train["state"] == "retry" else f"resume:{train['train']}"


def add_cars(cars: list[dict], new: list[dict]) -> list[dict]:
    """`cars` with each of `new` last, or in its field's place when that field rides (its newer head, plan 0610 E10)."""
    out = list(cars)
    for c in new:
        out = [c if x.get("field") == c.get("field") else x for x in out] if c.get("field") in {
            x.get("field") for x in out} else out + [c]
    return out


def carried(train: dict) -> list[dict]:
    """The early orders of a train that landed green: their red did not hold the merge, so they are post-merge
    orders now, for the next train (plan 0383 step 6)."""
    return [{**{k: o.get(k) for k in ORDER_KEYS}, "post": train["train"]}
            for o in train["orders"] if o.get("early")]


def fix(train: dict, e: dict) -> None:
    """An `order` opens a fix order (the train `fixing`), a `fixed` closes one; the last closed: `retry`. A
    post-merge order (`post`) only opens and closes: the train's state stays as it is."""
    post = [o for o in train["post"] if o["id"] != e.get("id")]
    if e["kind"] == "order" and e.get("post"):
        train["post"] = post + [{k: e.get(k) for k in (*ORDER_KEYS, "post")}]
        return
    if e["kind"] == "fixed" and len(post) < len(train["post"]):
        train["post"] = post
        return
    if e["kind"] == "order" and e.get("also"):  # another red job for an open order (plan 0522 D16): it grows
        for o in (o for o in train["orders"] if o["id"] == e["also"]):
            o.update(jobs=list(dict.fromkeys((o.get("jobs") or []) + (e.get("jobs") or []))),
                     why=f"{o.get('why')}; {e.get('why')}")
        return
    if e["kind"] == "order":
        early = train["state"] == "landing"  # placed while the run runs (plan 0383 D5): the landing goes on
        train["orders"].append({**{k: e.get(k) for k in ORDER_KEYS},
                                "early": early})
        train["state"] = train["state"] if early else "fixing"
        return
    train["orders"] = [o for o in train["orders"] if o["id"] != e.get("id")]
    if not train["orders"]:
        train.update(state="retry", retried=f"fixed: {e.get('id')}", fixed=True, runner_retries=0)


def resume(train: dict) -> dict:
    """A paused train resumed: its state before the pause, its land run forgotten; watch.py looks for runs created
    since the pause (`since`), so the cancelled one is never taken for the resumed landing's."""
    train.update(state=train.pop("paused_from", None) or "landing", land_run=None, resumed=len(train["pauses"]),
                 since=train["pauses"][-1].get("since"))
    return train


def land_run(rows: list[dict]) -> str | None:
    """The standing train's land run of its current start (a `run` line after its last `started`), or None."""
    return (standing(rows) or {}).get("land_run")


def yard_past(rows: list[dict]) -> dict:
    """What yard.sort needs of the past: `carried` ({path: [hash]}: what the yard brought into a train, so a barn
    file that is the yard's own may be changed by it again) and `refused` ({path: hash}: the files of a yard car a
    session unhitched from a red train)."""
    past: dict = {"carried": {}, "refused": {}}
    for e in rows:
        for f in e.get("files", []) if e["kind"] == "yard" else []:
            past["carried"].setdefault(f["path"], []).append(f.get("hash"))
        for f in e.get("files", []) if e["kind"] == "unhitched" and e.get("slot") == YARD else []:
            past["refused"][f["path"]] = f.get("hash")
    return past
