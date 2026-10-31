#!/usr/bin/env python3
"""Wagon trains as code: what the duty `trains` plans each round (hal2 plan 0294 step 6; hal2's
.adr/merge-queue-policy.md rule 3). Each train rides in its own worktree `tollman-train-<plan>-...` (train_wt.py); a
foreman's whole part is the hitch, `hal2-cli-git worktree queue ready` (D9). This module only reads (the queue, git,
the train state, the landing's log) and returns the frame's actions, each with a `key`; `engine.py` does them.

Between trains (`draft`, steps 1 to 4; `tollman.py train --dry-run` prints it):
1. the tickets marked `ready`, in queue order; none: nothing to do. Only adjacent production wagons ride: an entry
   whose effective mode is smuggle passes alone, one between them cuts the train (kinds.py, plan 0375 D8)
2. what cannot ride is unhitched: a head that is in the barn already (no message), a servant's field (`plans/LEAD`);
   while a place the user reserved for a field that is not ready stands in the queue, the others wait: a landing
   waits behind such a place (.adr/merge-queue-policy.md rule 2), and that field is to land first
3. the alone rule (D11, D12 of plan 0333; gate_car.py): a car rides alone, the only car of its train, only when it
   adds, removes or renames the landing workflow or changes what starts its run (`on:`, `name:`, `run-name:`); a
   crop touching other gate files (jobs, job lists, lanes, runners) rides with the others, the train's own run
   tests it. Such a car behind the first waits for the next train, its why naming the change
4. the trial merge in queue order (trial.py): a wagon that conflicts is unhitched and its foreman told why (a
   template), unless every file of the conflict is generated (generated.py: the train writes them again); the
   rest rides, every clean car (no car limit, plan 0463 D1)
5. `engine.py form`: the yard's work as the first car (yard.py, step 8), merge, mark, start the landing detached;
   what the yard keeps is told to the farmer (yard_report.py)

Before the draft (plan 0383 step 3, D3, D14; leavers.py): a placed ticket gone from the queue with its head not in the
barn is put back on its place, its foreman told, and a ticket held by `worktree stop` told likewise; the field is
`left` for `draft`: every car waits behind it until it is back in motion. A train that stands goes on.

While a train stands (`standing`, step 6) it is frozen (plan 0360 D3, frozen.py): nothing leaves it, a later
hitch joins only while its landing waits for the run before (open_train.py, plan 0490 step 20), else waits for the
next train, no wait limit ends it (D7). Its landing still runs: the watch reads its land run;
at its first red job the one car the triage names gets its fix order by code, an unclear culprit wakes once (watch.py,
plan 0360 step 5; early_order.py, plan 0383 step 5). Landed: every car's foreman is told "in the barn"
(D12), and the same round goes on to the next train (`chain`, plan 0333 step 6). Red (also a red pretest before the
push, `pretest_red`: pretest_train.py): triage (triage.py, train_red.py): a runner fault lands the same cars again on
a fresh run by code; the barn's or a car's red is one wake, then nothing until the session's `retry`; the train
waits for its fix. Interrupted (the process gone without a result): the same
landing again, it adopts the run; after MAX_STARTS the train is red and the session woken instead. Formed and never
started (its form died): the same train started (`restart` merges the cars it lacks first). The queue's mark naming
other cars: the next `restart` marks the train's own again. Only a car the user's own command unhitched (`by:
user`) splits it: broken up, and the rest forms again in the same call. A mark without a train of ours (a dead
tollman's, step 7) is cleared.
"""

import json
import sys
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import board
import chain
import early_order
import frozen
import gate_car
import generated
import hold
import kinds
import leavers
import modes
import mtm_scan
import orders
import own_fix
import pause
import proof
import stack_red
import train_state
import train_wt
import smuggled
import train_red
import trial as trial_merge
import watch
import watch_events
import yard_report
from tick import act, default_ref
from trains_sort import HELD, HELD_LEFT, base_of, current_plan, held_ahead, held_for, servant, sort_out  # noqa: F401  (re-exported)

QUEUE = mtm_scan.QUEUE  # the queue read; defined with mtm_scan.run_json so a minute pass needs no trains
ROLE = "tollman"
TRAIN = ROLE + " (wagon train)"
ENGINE = Path(__file__).with_name("engine.py")
PROVE = proof.verdict  # (main, field, head, barn) -> {state: green | red | wait, lines}; a test fakes it
MAX_STARTS = 5  # an interrupted landing is started again this often, then the train is red (it stands, D7)
HOUR = 3600
LANDED = ("landed", "nothing")  # the landing's results that mean: every car's crop is in the barn
AGAIN = (None, "interrupted", "waiting", "testing", "paused", "held")  # no result, or one whose rerun goes on (held: L88)
HITCH = "report it ready again (`hal2-cli-git worktree queue ready`)"
TEXT = {
    "conflict": TRAIN + ": field {field} is unhitched: its crop conflicts with {what} in {files}. {then}, resolve "
                        "it, push and " + HITCH + ".",
    "proof": TRAIN + ": field {field} is unhitched before it rode: its light gate checks are red on {head}:\n{lines}\n"
                     "Fix it, push and " + HITCH + ".",
    "servant": TRAIN + ": field {field} is unhitched: a servant's field (plans/LEAD) never rides a train, its foreman "
                       "merges its branch.",
    "split": TRAIN + ": field {field} is unhitched from the red train by the user: {why}. Fix it, push and " + HITCH
             + ".",
    "barn": TRAIN + ": your crop is in the barn (the train of {cars}{run}): /merge-from-main, finish the plan, once finished "
                    "/cleanup, then clear (the tollman clears a field 00-09 and removes a field above 09 once its work "
                    "is safe).",  # plan 0360 step 7 (D8): the foreman ends its turn, barn.py clears or removes
    "stuck": "the train engine's `{verb}` failed ({what}): run `{cmd}` to see why, then `tollman.py train "
             "--dry-run`.",
    **train_red.TEXT,  # failed, main_red, car_red, runner_broken (plan 0360 step 5)
    **pause.TEXT, **smuggled.TEXT,  # paused, resumed, resume_conflict, smuggled_red (plan 0360 step 18)
    **modes.TEXT,  # in_barn (plan 0360 step 25)
}


def draft(main: str, tickets: list[dict], own: str, base: str, default: str, mode: dict | None = None,
          left: str | None = None) -> dict:
    """Steps 1 to 4: the train the queue allows now. `cars` ([{field, branch, head, plan}] in order), `unhitched`
    ([{field, head, why, tell, ...}]), `waiting` ([{field, why}]: ready, but not in this train), `alone` (the one car
    rides alone: gate_car.py). `left`: the field of a ticket that left the queue
    unmerged or was stopped (leavers.py): every car waits behind it."""
    rides, later = kinds.split(tickets, own, mode)  # only adjacent production wagons ride (plan 0375 D8)
    wagons, unhitched = sort_out(main, default, rides, own)
    out = {"base": base, "cars": [], "unhitched": unhitched, "waiting": later, "alone": False}
    acc = base
    for t in wagons:
        field, head = t["slot"], t["ready"]["head"]
        if held := left or held_ahead(tickets, own, t):  # only a place ahead of it (L95)
            out["waiting"].append({"field": field, "why": (HELD_LEFT if left else HELD).format(field=held)})
            continue
        if out["alone"]:
            first = out["cars"][0]["field"]
            out["waiting"].append({"field": field, "why": f"rides in the next train, after {first}, which rides alone"})
            continue
        if (alone := gate_car.alone_why(main, default, head)) and out["cars"]:
            out["waiting"].append({"field": field, "why": f"rides alone in the next train: {alone}"})
            continue
        commit, files = trial_merge.merge(main, acc, head)
        if commit is None:
            out["waiting"].append({"field": field, "why": f"the trial merge of {head[:12]} could not run"})
        elif files and not generated.only(main, base, files, commit):  # generated only: the train writes them again
            barn = acc == base or bool(trial_merge.merge(main, base, head)[1])
            ahead = [] if barn else [c["field"] for c in out["cars"]]
            unhitched.append({"field": field, "head": head, "at": t["ready"].get("at", ""), "tell": "conflict",
                              "files": files, "ahead": ahead,
                              "why": f"conflicts with {'the cars ahead' if ahead else 'the barn'} in "
                                     + ", ".join(files[:5])})
        elif (proven := PROVE(main, t["worktree"], head, default))["state"] == "wait":
            out["waiting"].append({"field": field, "why": proven["lines"][0]})
        elif proven["state"] == "red":
            unhitched.append({"field": field, "head": head, "at": t["ready"].get("at", ""), "tell": "proof",
                              "lines": proven["lines"], "why": "its light gate checks are red: " + proven["lines"][0]})
        else:
            out["cars"].append({"field": field, "branch": t.get("branch") or field, "head": head,
                                "plan": current_plan(t["worktree"])})
            acc, out["alone"] = commit, bool(alone)
    return out


def run(kind: str, slot: str, key: str, verb: str, top: str, *args: str, window: int = 7 * 24 * HOUR, **fields):
    """A `run` action of an engine verb; a failed one wakes the session (the run's key keeps it from looping)."""
    argv = [sys.executable, str(ENGINE), verb, *args, "--repo", top]
    stuck = act("trains", "train-stuck", "wake", key=f"stuck:{key}",
                text=TEXT["stuck"].format(verb=verb, what=fields.get("text", ""), cmd=" ".join(argv[1:])))
    return act("trains", kind, "run", slot, key=key, window=window, argv=argv, on_fail=[stuck], **fields)


def tell(kind: str, field: str, key: str, text: str, panes: dict, after: str | None = None) -> dict:
    return act("trains", kind, "send", field, pane=panes.get(field), key=key, text=text,
               **({"after": after} if after else {}))


def train_actions(top: str, d: dict, panes: dict, after: str | None = None) -> list[dict]:
    """Steps 2, 4 and 5 as actions: the unhitched (each told why by a template), then the train."""
    out, chain = [], {"after": after} if after else {}
    for u in d["unhitched"]:
        key = f"unhitch:{u['field']}:{u['at'] or u['head'][:12]}"
        out.append(run("unhitch", u["field"], key, "unhitch", top, u["field"], "--why", u["why"],
                       text=f"{u['field']} unhitched: {u['why']}", **chain))
        if u["tell"]:
            out.append(tell("unhitched", u["field"], f"told:{key}", unhitched_text(u), panes, key))
    if d["cars"]:
        fields = [c["field"] for c in d["cars"]]
        # The same cars are not formed again within the hour, unless this round broke their train up before.
        key = "form:" + "+".join(f"{c['field']}@{c['head'][:12]}" for c in d["cars"]) + (f":{after}" if after else "")
        out.append(run("form", "-", key, "form", top, "--cars", json.dumps(d["cars"]), window=HOUR,
                       text=f"wagon train: {', '.join(fields)}" + (" (alone)" if d["alone"] else ""), **chain))
    return out


def unhitched_text(u: dict) -> str:
    """What a foreman is told whose field the draft unhitched (`tell`: `servant`, `proof` or `conflict`)."""
    if u["tell"] == "servant":
        return TEXT["servant"].format(field=u["field"])
    if u["tell"] == "proof":
        return TEXT["proof"].format(field=u["field"], head=u["head"][:12], lines="\n".join(u["lines"]))
    ahead = ", ".join(u["ahead"])
    return TEXT["conflict"].format(
        field=u["field"], files=", ".join(u["files"][:5]), what=f"the cars ahead ({ahead})" if ahead else "the barn",
        then=f"Restock (/merge-from-main) once the train of {ahead} is in the barn" if ahead else "Restock (/merge-from-main)")


def settle(top: str, train: dict, result: dict | None, panes: dict, tickets=()) -> list[dict]:
    """Step 6 for a train whose landing's process is gone: landed, started again, or red."""
    name, status = train["train"], (result or {}).get("status")
    cars = ", ".join(c["field"] for c in train["cars"])
    if status in LANDED or (status == "shipping" and result.get("commit")):
        key, link = f"landed:{name}", result.get("run")
        commit = ["--commit", result["commit"]] if result.get("commit") else []
        done = run("landed", "-", key, "landed", top, *(["--run", link] if link else []), *commit,
                   text=f"train {name} is in the barn")
        text = TEXT["barn"].format(cars=cars, run=f", {link}" if link else "")
        return [done] + [tell("in-the-barn", c["field"], f"barn:{name}:{c['field']}", text, panes, key)
                         for c in train["cars"]] + stack_red.actions(top, train, result, panes, key) + [
                            chain.action(top, key)]  # the next train in this round
    if status in AGAIN and train["starts"] < MAX_STARTS:
        return [run("restart", "-", f"restart:{name}:{train['starts']}", "restart", top,
                    text=f"train {name}: its landing ended {status or 'without a result'}, started again")]
    if status in AGAIN:
        status, why = "interrupted", f"its landing ended without a result {train['starts']} times"
    else:
        red, suspects = ", ".join(j.get("name", "") for j in result.get("red") or []), result.get("suspects")
        why = ((f"{red}, suspects: {', '.join(suspects)}" if red and suspects else red) or result.get("message")
               or status)[:300]
    return train_red.actions(top, train, result, status, why, run, tickets)  # triage first (plan 0360 step 5)


def plan(top: str, main: str, tickets: list[dict], rows: list[dict], panes: dict, alive=None,
         result=None, mode: dict | None = None, sleep_flag: dict | None = None, left: str | None = None,
         held: dict | None = None) -> list[dict]:
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
    if train and train["state"] == "landing" and landing(train["pid"]):
        return pre + watch.actions(top, main, train, rows, tickets)  # its land run read, a red job wakes once
    if train and train["state"] == "landing":  # frozen (D3): a mark that names other cars is marked again
        return pre + hold.keep(settle(top, train, result(main), panes, tickets), held)  # held: no restart (L107)
    if held:  # plan 0383 step 7 (D7): the hold; a landing that runs or settles went on above, nothing forms or starts
        return pre + [hold.line(held)]
    if train and train["state"] in ("retry", "formed"):  # formed, never started: the same train, never a re-draft
        key = f"retry:{train['train']}:{train['starts']}" if train["state"] == "retry" else f"resume:{train['train']}"
        return [run("restart", "-", key, "restart", top, text=f"train {train['train']} lands again")]
    if train and not (train["state"] == "split" and frozen.by_user(train)):
        return []  # red, or split without the user's word: frozen, it waits for its fix (D7: no wait limit)
    if not train and (fix := own_fix.waiting(rows)) and not fix["sha"]:
        return []  # the barn's fix is open: the next train waits for its first car (plan 0360 step 8)
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
    d = draft(main, queue, own, base_of(main, default, own_head), default, mode, left)
    return out + train_actions(top, d, panes, after) + yard_report.left_actions(main, d, default, rows, panes)


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
                          default_ref(main), bool(ctx.get("dry")))  # a leaver is put back, the trains behind it hold
    out = turn + leave["actions"] + early_order.once(ctx, plan(top, main, tickets, rows, panes, mode=mode,
                                                               sleep_flag=flag, left=leave["held"],
                                                               held=hold.of(main)))  # one early order a round
    watched = watch_events.state(main)  # the 1-minute watch's run: its post-merge red is post_merge.py's
    return out + yard_report.settled_actions(main, rows, panes) + stack_red.watch(
        top, main, rows, panes, log, watched=None if watched.get("closed") else str(watched.get("run") or "")) \
        + orders.answers(top, rows, log)  # `fixed <sha>` (step 6)
