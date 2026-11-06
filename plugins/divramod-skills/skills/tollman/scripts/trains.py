#!/usr/bin/env python3
"""Wagon trains as code: what the duty `trains` plans each round (hal2 plan 0294 step 6; hal2's
.adr/merge-queue-policy.md rule 3). Each train rides in its own worktree `tollman-train-<plan>-...` (train_wt.py); a
foreman's whole part is the hitch, `hal2-cli-git worktree queue ready` (D9). This module only reads (the queue, git,
the train state, the landing's log) and returns the frame's actions, each with a `key`; `engine.py` does them.

Between trains (`draft`, trains_draft.py's steps 1 to 6; `tollman.py train --dry-run` prints it): every hitched wagon
rides (the user, 2026-11-04: "take all finished ones into the train"), a car with what it needs (`conflict`,
`proof_red`, `proof_unknown`, `untried`, `carried`, `gone`), or waits under one of trains_draft.EXCEPTIONS, the
user-named ones; nothing is unhitched. A train forms once MIN_HITCHED fields are hitched (the user's minimum, plan
0610 D11); an alone car the last train left (`owed`) or one below the minimum rides alone at once (D15). Then
`engine.py form` (engine_form.py; nothing undoes a forming, E25): the yard's work as the first car (yard.py, step 8),
merge, mark, start the landing detached; a train with a conflicting car forms by `tollman.py resolve-form` and waits
`resolving` for its foreman's resolve on the train's branch (resolve.py); what the yard keeps is told to the farmer
(yard_report.py). A red the barn's own head shows too (`barn_red`) is the barn's own fix order first (own_fix.py,
`tollman.py order main`), never a car's; a car whose worktree is gone is a board note to the farmer.

Before the draft (plan 0383 step 3, D3, D14; leavers.py): a placed ticket gone from the queue with its head not in the
barn is put back on its place, its foreman told, and a ticket held by `worktree stop` told likewise; it keeps its
place and holds no hitched wagon (plan 0610 E18). A train that stands goes on.

While a train stands (`standing`, step 6) it is frozen (plan 0360 D3, frozen.py): nothing leaves it, no wait limit
ends it (D7), and every later hitch joins it until its first start (open_train.py, plan 0610 D17): the round's
`join_actions`, a car with red light checks gets its fix order there. From the first start its cars are fixed: a
later hitch rides the next train (plan 0687 D1). Its landing still runs: the watch reads
its land run; at its first red job the one car the triage names gets its fix order by code, an unclear culprit wakes once (watch.py,
plan 0360 step 5; early_order.py, plan 0383 step 5). Landed: every car's foreman is told "in the barn"
(D12), and the same round goes on to the next train (`chain`, plan 0333 step 6). Red (also a red pretest before the
push, `pretest_red`: pretest_train.py): triage (triage.py, train_red.py): a runner fault lands the same cars again on
a fresh run by code; the barn's or a car's red is one wake, then nothing until the session's `retry`; the train
waits for its fix (a `retry` round places a proof_red car's fix order first; its restart key is
`retry:<train>:<attempt>`, train_fold.restart_key, plan 0620 D2, D5, D6). An incomplete pretest (`pretest_incomplete`: the budget cut a job or the gate did not answer, plan
0522 D7): the same landing again, up to PRETEST_WAITS in a row, then red as above.
Interrupted (the process gone without a result): the same
landing again, it adopts the run, but while its land run still runs it is only watched, settled at the run's end
(plan 0560 step 2, watch.running); after MAX_STARTS the train is red and the session woken instead. With a fix order
open it is never started again (plan 0560 D2): its red is recorded from the last run, the order answers it. Formed and never
started (its form died): the same train started (`restart` merges the cars it lacks first). The queue's mark naming
other cars: the next `restart` marks the train's own again. Only a car the user's own command unhitched (`by:
user`) splits it: broken up, and the rest forms again in the same call. A mark without a train of ours (a dead
tollman's, step 7) is cleared.
"""

import hashlib
import json
import sys
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import board
import chain
import early_order
import foreman_wake
import frozen
import hold
import leavers
import modes
import mtm_scan
import orders
import own_fix
import pause
import proof
import proof_orders
import resolve
import roletime
import stack_red
import train_depends  # noqa: F401  (trains_draft reads it; tests fake trains.train_depends.read)
import train_state
import train_wt
import smuggled
import train_red
import trains_draft
import trial as trial_merge
import watch
import watch_events
import yard_report
from tick import act, default_ref
from trains_draft import EXCEPTIONS, open_plan  # noqa: F401  (re-exported)
from trains_sort import HELD, base_of, current_plan, held_ahead, held_for, servant, sort_out  # noqa: F401  (re-exported)

QUEUE = mtm_scan.QUEUE  # the queue read; defined with mtm_scan.run_json so a minute pass needs no trains
ROLE = "tollman"
TRAIN = ROLE + " (wagon train)"
ENGINE, TOLLMAN, ROLE_CARS = (Path(__file__).with_name(f"{n}.py") for n in ("engine", "tollman", "role_cars"))  # 0610 D24
GONE = "worktree-gone"  # the board note's kind (board.NOTES)
PROVE = proof.verdict  # (main, field, head, barn) -> {state: green | red | wait, lines}; a test fakes it
MAX_STARTS = 5  # an interrupted landing is started again this often, then the train is red (it stands, D7)
HOUR = 3600
MIN_HITCHED = 10  # a train forms once this many fields are hitched, and takes every one (plan 0610 D11; ROLE.md's words);
# the barn's own fix (`order main`, own_fix.py) is not bound by it (D22)
RESUME_WINDOW = 30 * 60  # a failed restart of a formed, never started train is tried again after this (not a week)
BARN_FIX_WAIT = 30 * 60  # an open fix order of the barn's own holds forming this long (plan 0610 D12, E22)
JOIN_FLAGS = ("conflict", "proof_red", "carried", "untried", "proof_unknown")  # what a joiner rides with (its line)
LANDED = ("landed", "nothing")  # the landing's results that mean: every car's crop is in the barn
AGAIN = (None, "interrupted", "waiting", "testing", "paused", "held")  # no result, or one whose rerun goes on (held: L88)
PRETEST_WAIT, PRETEST_WAITS = "pretest_incomplete", 3  # pretest_train.INCOMPLETE and WAITS (not imported: light start)
TEXT = {
    # plan 0610 D21: after the user's split no fix order exists, so the answer goes to the farmer, who relays it
    "split": TRAIN + ": field {field} is out of the red train by the user's own command: {why}. Fix it on your "
                     "branch `{field}` (/merge-from-main first), push, then tell the farmer by SendMessage "
                     "(`farmer-<repo>` in ListAgents) `{field} fixed <sha>`: the farmer relays it to the user, whose "
                     "word alone puts it back in the queue; the tollman never touches its hitch.",
    "barn": TRAIN + ": your crop is in the barn (the train of {cars}{run}): /merge-from-main, finish the plan, once finished "
                    "/cleanup, then clear (the tollman clears a field 00-09 and removes a field above 09 once its work "
                    "is safe).",  # plan 0360 step 7 (D8): the foreman ends its turn, barn.py clears or removes
    "milestone": ": your crop rode as {label} and is in the barn, its plan stays open: /merge-from-main, then run "
                 "`/continue` and carry on with the plan's next rows (do not finish the plan or clean up).",
    "gone": "field {field}'s worktree is gone; its hitched head {head} rides from its sha (plan 0610 E13)",
    "stuck": "the train engine's `{verb}` failed ({what}; `{cmd}`): its output follows. Look with `tollman.py status` "
             "and `tollman.py train --dry-run`; never run a start again by hand while a landing may run (a live one is "
             "adopted by `restart`, never `engine.py land`).",
    **train_red.TEXT,  # failed, main_red, car_red, runner_broken (plan 0360 step 5)
    **pause.TEXT, **smuggled.TEXT,  # paused, resumed, resume_conflict, smuggled_red (plan 0360 step 18)
    **modes.TEXT,  # in_barn (plan 0360 step 25)
}


def minimum(main: str) -> int:
    """The hitched fields a train needs: the user's open `minimum` standing order (standing.py), else MIN_HITCHED."""
    import standing
    return standing.value(main, "minimum", MIN_HITCHED)


def draft(main: str, tickets: list[dict], own: str, base: str, default: str, mode: dict | None = None,
          carried=(), first=(), minimum: int = 0) -> dict:
    """The train the queue allows now (trains_draft.draft, proven by PROVE); `carried`: commits whose ancestors ride
    already (the standing train's carrier head, the dry run's); `first`: the alone cars owed their own train
    (`owed`); `minimum`: the hitched fields a train needs (the round's MIN_HITCHED, none for a join)."""
    return trains_draft.draft(main, tickets, own, base, default, mode, PROVE, carried, first, minimum)


def owed(rows: list[dict]) -> list[str]:
    """The alone cars owed their own train next: the last formed train's `alone_next` and the alone cars that hitched
    while it stood (open_train.owed_now, plan 0610 D15)."""
    import open_train
    return open_train.owed_now(rows)


def run(kind: str, slot: str, key: str, verb: str, top: str, *args: str, window: int = 7 * 24 * HOUR,
        script: Path = ENGINE, **fields):
    """A `run` action of an engine verb (`script`'s); a failed one wakes the session (its key keeps it from looping)."""
    argv = [sys.executable, str(script), verb, *args, "--repo", top]
    stuck = act("trains", "train-stuck", "wake", key=f"stuck:{key}",
                text=TEXT["stuck"].format(verb=verb, what=fields.get("text", ""), cmd=" ".join(argv[1:])))
    return act("trains", kind, "run", slot, key=key, window=window, argv=argv, on_fail=[stuck], **fields)


def tell(kind: str, field: str, key: str, text: str, panes: dict, after: str | None = None) -> dict:
    return act("trains", kind, "send", field, pane=panes.get(field), key=key, text=text,
               **({"after": after} if after else {}))


def train_actions(top: str, d: dict, panes: dict, after: str | None = None, barn_fix: bool = False,
                  log=()) -> list[dict]:
    """The draft as actions: a board note per car whose worktree is gone (E13), the barn's own fix order for a
    `barn_red` while none waits (`barn_fix`), then the train. The train waits for the order only in the round that
    makes it: once its key ran (`log`, the frame's: done or failed) the train forms beside it, so a failed or
    ineffective order never holds a train (plan 0610 D12; an open order holds forming only while young: `plan`).
    Never an unhitch: a hitched car never leaves the queue (the user, 2026-11-04)."""
    out, chain = [], {"after": after} if after else {}
    for c in (c for c in d["cars"] if c.get("gone")):
        out.append(act("trains", GONE, "record", Path(top).name, key=f"note:gone:{c['field']}:{c['head'][:12]}",
                       window=24 * HOUR, text=TEXT["gone"].format(field=c["field"], head=c["head"][:12])))
    if d.get("barn_red") and not barn_fix:
        lines = sorted({ln for r in d["barn_red"] for ln in r["lines"]})
        key = "barn-red:" + hashlib.sha256("\n".join(lines).encode()).hexdigest()[:12]
        why = (f"light checks red on the barn's own head, not the cars' "
               f"({', '.join(r['field'] for r in d['barn_red'])}): {'; '.join(lines)}")[:300]
        out.append(run("barn-red", "-", key, "order", top, "main", "--why", why, script=TOLLMAN, **chain,
                       text=f"the barn's own fix order first: {why}"))
        if not any(e.get("key") == key for e in log):
            return out  # the order's first round: its fix becomes the first car of the next train (own_fix.py)
    if d["cars"]:
        fields = [c["field"] for c in d["cars"]]
        # No wait on the key (plan 0610 E25): a form that failed before its `formed` line is tried again next round.
        key = "form:" + "+".join(f"{c['field']}@{c['head'][:12]}" for c in d["cars"]) + (f":{after}" if after else "")
        tangled = [c["field"] for c in d["cars"] if c.get("conflict")]  # every wagon rides (resolve.py, D18)
        red = [c["field"] for c in d["cars"] if c.get("proof_red")]  # fixed in the train (proof_orders.py)
        nxt = ["--alone-next", *d["alone_next"]] if d.get("alone_next") else []
        out.append(run("form", "-", key, "resolve-form" if tangled else "form", top, "--cars", json.dumps(d["cars"]),
                       *nxt, window=0, script=resolve.CLI if tangled else ENGINE, **chain, text=f"wagon train: "
                       f"{', '.join(fields)}" + (" (alone)" if d["alone"] else "")
                       + (f", {', '.join(tangled)} to resolve" if tangled else "")
                       + (f", {', '.join(red)} with red light checks to fix" if red else "")))
    return out




def barn_text(cars: str, link: str | None, car: dict) -> str:
    """The foreman's "in the barn" text; a milestone car's adds that its plan stays open and it runs `/continue`."""
    text = TEXT["barn"].format(cars=cars, run=f", {link}" if link else "")
    if car.get("milestone"):
        text = text.split(": /merge-from-main")[0] + TEXT["milestone"].format(label=car["milestone"])
    return text


def settle(top: str, train: dict, result: dict | None, panes: dict, tickets=()) -> list[dict]:
    """Step 6 for a train whose landing's process is gone: landed, started again, or red."""
    name, status = train["train"], (result or {}).get("status")
    cars = ", ".join(c["field"] for c in train["cars"])
    if status in LANDED or (status == "shipping" and result.get("commit")):
        key, link = f"landed:{name}", result.get("run")
        commit = ["--commit", result["commit"]] if result.get("commit") else []
        done = run("landed", "-", key, "landed", top, *(["--run", link] if link else []), *commit,
                   text=f"train {name} is in the barn")
        return [done] + [tell("in-the-barn", c["field"], f"barn:{name}:{c['field']}", barn_text(cars, link, c), panes, key)
                         for c in train["cars"]] + stack_red.actions(top, train, result, panes, key) + [
                            chain.action(top, key)]  # the next train in this round
    if status == PRETEST_WAIT and train.get("pretest_waits", 0) <= PRETEST_WAITS:  # not green: the push waits (D7)
        return [run("restart", "-", f"pretest-wait:{name}:{train['starts']}", "restart", top,
                    text=f"train {name}: {result.get('message') or 'its pretest is incomplete'}, started again")]
    if status in AGAIN and train.get("orders"):  # plan 0560 D2, D3: an open fix order, the candidate is unchanged
        return train_red.died(top, train, result, run, tickets)  # recorded red from the last run, never pushed again
    if status in AGAIN and train["starts"] < MAX_STARTS:
        return [run("restart", "-", f"restart:{name}:{train['starts']}", "restart", top,
                    text=f"train {name}: its landing ended {status or 'without a result'}, started again")]
    if status in AGAIN:
        status, why = "interrupted", f"its landing ended without a result {train['starts']} times"
    else:
        why = (reds(result) or result.get("message") or status)[:300]
    return train_red.actions(top, train, result, status, why, run, tickets)  # triage first (plan 0360 step 5)


def reds(result: dict) -> str:
    """The red jobs of a landing's result: each with its own suspects when it names them (a pretest's, plan 0522
    D14: `a (car 07), b (cars 07, 09)`), else the names and the result's suspects."""
    red, suspects = result.get("red") or [], result.get("suspects")
    if red and all(j.get("suspects") for j in red):
        return ", ".join(f"{j.get('name', '')} (car{'s' * (len(j['suspects']) > 1)} {', '.join(j['suspects'])})"
                         for j in red)
    names = ", ".join(j.get("name", "") for j in red)
    return f"{names}, suspects: {', '.join(suspects)}" if names and suspects else names


def plan(top: str, main: str, tickets: list[dict], rows: list[dict], panes: dict, alive=None,
         result=None, mode: dict | None = None, sleep_flag: dict | None = None, held: dict | None = None, log=(),
         now=None, minimum: int = 0) -> list[dict]:
    """The round's actions for the tollman's field `top` (see the module doc). `alive(pid)` and `result(main)`
    are train_state's (the train's detached process, its last word) unless a test says otherwise; a ticket's pid is
    a landing's own process (mtm_scan.pid_alive). `mode`: the queue's (modes.py); the tollman sleeps in smuggle mode
    while no hitched entry is production, and while the sleep flag `sleep_flag` stands (plan 0365 D3, D9; on the flag
    every train not landing is dropped and the hitched land alone, plan 0375); a hitched entry whose effective mode is
    smuggle is no car, and only adjacent production wagons ride (kinds.py)."""
    if modes.asleep(mode, tickets, sleep_flag):  # plan 0360 step 25 (D75 2): a landing train goes on, nothing new starts
        return modes.sleep(top, mode, tickets, train_state.standing(rows), panes, lambda: plan(
            top, main, tickets, rows, panes, alive, result, held=held), alive or train_state.alive, sleep_flag)
    queue, tickets = tickets, modes.trainable(tickets, mode, Path(top).name)
    landing, waiter, result = alive or train_state.alive, alive or mtm_scan.pid_alive, result or train_state.result
    own, default, standing = Path(top).name, default_ref(main), train_state.standing(rows)
    mine = train_wt.ticket(tickets, own, standing)  # the carrier's: the standing train's, or one left with a mark
    marked = [c.get("field") for c in (mine.get("train") or {}).get("cars", [])]
    out, after, head = [], None, "HEAD"
    pre, train, stop = pause.step(top, main, standing, mine, landing, result)  # a smuggle's pause
    if stop:
        return pre  # paused: frozen, one line per pause (plan 0360 step 18, D58)
    if train and train["state"] == "landing" and (landing(train["pid"]) or (result(main) or {}).get("status") in AGAIN
                                                  and watch.running(main, train, rows)):  # died, its run runs: plan 0560
        return pre + watch.actions(top, main, train, rows, tickets)  # its land run read, a red job wakes once
    if train and train["state"] == "landing":  # frozen (D3): a mark that names other cars is marked again
        return pre + hold.keep(settle(top, train, result(main), panes, tickets), held)  # held: no restart (L107)
    if held:  # plan 0383 step 7 (D7): the hold; a landing that runs or settles went on above, nothing forms or starts
        return pre + [hold.line(held)]
    joins = join_actions(top, main, train, queue, mode)  # until its push (plan 0610 D17): before every start
    if train and train["state"] in ("retry", "formed"):  # formed, never started: the same train, never a re-draft
        key = train_state.restart_key(train)  # retry: new after every restart past its checks (plan 0620 D5)
        first = proof_orders.pending(top, main, train, rows) if train["state"] == "retry" else []  # a joiner's (D6)
        return joins + (first or [run("restart", "-", key, "restart", top, text=f"train {train['train']} lands again",
                                      **({"window": RESUME_WINDOW} if train["state"] == "formed" else {}))])
    if train and train["state"] in ("red", "fixing", "resolving"):  # a car with red light checks: its fix order
        return joins + proof_orders.actions(top, main, train, rows) * (train["state"] != "resolving")
    if train and train["state"] == "stopped":  # a role car left out twice in a row (plan 0610 D24): tried again
        return joins + [run("roles", "-", f"roles:{train['train']}", "retry", top, script=ROLE_CARS, window=5 * 60,
                            text=f"train {train['train']} is stopped: role car {train['stop']['field']} again")]
    if train and not (train["state"] == "split" and frozen.by_user(train)):
        return []  # paused, or split without the user's word: frozen, it waits (D7: no wait limit)
    if not train and (fix := own_fix.waiting(rows)) and not fix["sha"] and young(fix.get("at"), now):
        return []  # the barn's fix is open and young: the next train waits for its first car (plan 0360 step 8)
    if not train and waiter(mine.get("pid")) and not mine.get("waits_for"):
        return []  # a landing of the field runs that is no train of ours: never touched (a leaving ticket's ended)
    if train or marked:
        why = "split after red by the user" if train else "a mark without a train of ours"
        after = f"breakup:{train['train']}" if train else f"leftover:{mine['train'].get('at', '')}"
        out.append(run("breakup", "-", after, "breakup", train_wt.left(mine, train, top), "--why", why, *["--by-user"] * bool(train),
                       text=f"train broken up: {why}"))
        out += [tell("unhitched", u["field"], f"split:{train['train']}:{u['field']}",
                     TEXT["split"].format(field=u["field"], why=u["why"]), panes)
                for u in (train or {}).get("unhitched", []) if u["field"] != train_state.YARD]
        head = (train or {}).get("base") or head
    own_head = trial_merge.git(top, "rev-parse", head)[1] if Path(top).is_dir() else None
    fix = 0 if own_fix.waiting(rows) else minimum  # the barn's own fix forms at once (D22), as the alone car does
    d = draft(main, queue, own, base_of(main, default, own_head), default, mode, first=owed(rows), minimum=fix)
    return out + train_actions(top, d, panes, after, own_fix.waiting(rows) is not None, log) \
        + yard_report.left_actions(main, d, default, rows, panes)


def join_actions(top: str, main: str, train: dict | None, tickets: list[dict], mode: dict | None) -> list[dict]:
    """The open train's join round outside its landing (open_train.actions; plan 0610 D15, D17)."""
    import open_train  # the join round: loaded only while a train stands
    return open_train.actions(top, main, train, tickets, mode)


def young(at, now=None) -> bool:
    """Whether the barn's own fix order made at `at` is younger than BARN_FIX_WAIT (plan 0610 D12: an older one, or one
    whose time does not parse, holds no train: the train forms beside it)."""
    age = roletime.age(at, now or roletime.utcnow())
    return age is not None and age.total_seconds() < BARN_FIX_WAIT


def handler(item: dict, ctx: dict) -> list[dict]:
    """duty:trains: the queue (its mode, the tollman's sleep flag: modes.py) and the train state, then the round's actions."""
    main, top, panes, doc = ctx["main"], ctx["top"], ctx.get("panes", {}), mtm_scan.run_json(QUEUE, ctx["main"]) or {}
    tickets, mode, rows, log = doc.get("queue", []), modes.of(doc), train_state.lines(main), ctx.get("log", [])
    if not ctx.get("dry"):
        board.safely(main, "ready tickets", board.on_ready, tickets)  # a ready ticket seen first (step 7)
    flag = modes.flag(main)  # the tollman's sleep flag (plan 0365 D3)
    turn, stop = modes.turn(top, main, mode, tickets, rows, panes, flag)  # the mode noted; awake again: the barn first
    if stop:
        return turn
    leave = leavers.check(main, top, tickets, (doc.get("priority") or {}).get("slots") or [], panes,
                          default_ref(main), bool(ctx.get("dry")))  # a leaver is put back; it holds no wagon (E18)
    out = turn + leave["actions"] + early_order.once(ctx, plan(top, main, tickets, rows, panes, mode=mode,
                                                               sleep_flag=flag, held=hold.of(main), log=log,
                                                               minimum=minimum(main)))
    watched = watch_events.state(main)  # the 1-minute watch's run: its post-merge red is post_merge.py's
    return foreman_wake.gate(out + yard_report.settled_actions(main, rows, panes) + stack_red.watch(
        top, main, rows, panes, log, watched=None if watched.get("closed") else str(watched.get("run") or "")) \
        + orders.answers(top, rows, log) + resolve.actions(top, rows, panes, log)  # `fixed`, `resolved` (D18)
        + foreman_wake.held(ctx, rows), ctx)  # an order's foreman started first (plan 0522 D21)
