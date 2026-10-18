#!/usr/bin/env python3
"""Wagon trains as code: what the duty `trains` plans each round (hal2 plan 0294 step 6; hal2's
.adr/merge-queue-policy.md rule 3). The tollman's own field `tollman-<repo>` carries every train (D8); a
foreman's whole part is the hitch, `hal2-cli-git worktree queue ready` (D9). This module only reads (the queue, git,
the train state, the landing's log) and returns the frame's actions, each with a `key`; `engine.py` does them.

Between trains (`draft`, steps 1 to 4; `tollman.py train --dry-run` prints it):
1. the tickets marked `ready`, in queue order; none: nothing to do
2. what cannot ride is unhitched: a head that is in the barn already (no message), a servant's field (30-99);
   while a place the user reserved for a field that is not ready stands in the queue, the others wait: a landing
   waits behind such a place (.adr/merge-queue-policy.md rule 2), and that field is to land first
3. the alone rule (D11, D12 of plan 0333; gate_car.py): a car rides alone, the only car of its train, only when it
   adds, removes or renames the landing workflow or changes what starts its run (`on:`, `name:`, `run-name:`); a
   crop touching other gate files (jobs, job lists, lanes, runners) rides with the others, the train's own run
   tests it. Such a car behind the first waits for the next train, its why naming the change
4. the trial merge in queue order (trial.py): a wagon that conflicts is unhitched and its foreman told why (a
   template), unless every file of the conflict is generated (generated.py: the train writes them again); the
   rest rides, at most MAX_CARS (the user: "4-6 fields brought in at once"): a clean car past them waits
5. `engine.py form`: the yard's work as the first car (yard.py, step 8), merge, mark, start the landing detached;
   what the yard keeps is told to the farmer (yard_report.py)

While a train stands (`standing`, step 6) it is frozen (plan 0360 D3, frozen.py): nothing leaves it, a later
hitch waits for the next train, no wait limit ends it (D7). Its landing still runs: the watch reads its land run
and wakes once at its first red job (watch.py, plan 0360 step 5). Landed: every car's foreman is told "in the barn"
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
import frozen
import gate_car
import generated
import modes
import mtm_scan
import orders
import own_fix
import pause
import proof
import stack_red
import train_state
import smuggled
import train_red
import trial as trial_merge
import watch
import yard_report
from tick import act, default_ref

QUEUE = ["hal2-cli-git", "worktree", "queue", "--json"]
ROLE = "tollman"
TRAIN = ROLE + " (wagon train)"
ENGINE = Path(__file__).with_name("engine.py")
MAX_CARS = 6  # a train aims at 4-6 cars (plan 0333 D12); fewer only when fewer are ready and clean
PROVE = proof.verdict  # (main, field, head, barn) -> {state: green | red | wait, lines}; a test fakes it
MAX_STARTS = 5  # an interrupted landing is started again this often, then the train is red (it stands, D7)
HOUR = 3600
LANDED = ("landed", "nothing")  # the landing's results that mean: every car's crop is in the barn
AGAIN = (None, "interrupted", "waiting", "testing", "paused")  # no result, or one whose rerun goes on
HELD = ("the place reserved for field {field} stands in the queue and {field} is not ready: a train's landing waits "
        "behind it (the user's order; `hal2-cli-git worktree queue order`)")
HITCH = "report it ready again (`hal2-cli-git worktree queue ready`)"
TEXT = {
    "conflict": TRAIN + ": field {field} is unhitched: its crop conflicts with {what} in {files}. {then}, resolve "
                        "it, push and " + HITCH + ".",
    "proof": TRAIN + ": field {field} is unhitched before it rode: its light gate checks are red on {head}:\n{lines}\n"
                     "Fix it, push and " + HITCH + ".",
    "servant": TRAIN + ": field {field} is unhitched: a servant's field (30-99) never rides a train, its foreman "
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


def current_plan(worktree: str) -> str:
    """The first line of the worktree's plans/CURRENT_PLAN, or ''."""
    current = Path(worktree) / "plans/CURRENT_PLAN"
    text = current.read_text() if current.exists() else ""
    return next((line.strip() for line in text.splitlines() if line.strip()), "")


def servant(field: str) -> bool:
    return len(field) == 2 and field.isdigit() and 30 <= int(field) <= 99


def base_of(main: str, default: str, own: str | None) -> str:
    """What the cars are merged onto: the barn's head, with what the tollman's field holds beyond it (`own`)."""
    if not own or trial_merge.git(main, "merge-base", "--is-ancestor", own, default)[0] == 0:
        return default
    return trial_merge.merge(main, default, own)[0] or default


def sort_out(main: str, default: str, tickets: list[dict], own: str) -> tuple[list[dict], list[dict]]:
    """Steps 1 and 2: the ready tickets that may ride, in queue order, and those unhitched at once."""
    wagons, unhitched = [], []
    for t in sorted(tickets, key=lambda t: t.get("position", 0)):
        mark, field = t.get("ready"), t.get("slot")
        if not mark or field == own or t.get("rides_with") not in (None, own) or t.get("state", "waiting") != "waiting":
            continue  # also a ticket at the head, a leaving one included (`waits_for`): its own landing's, no car
        gone = {"field": field, "head": mark["head"], "at": mark.get("at", ""), "tell": None}
        if servant(field):
            unhitched.append({**gone, "why": "a servant's field (30-99) never rides", "tell": "servant"})
        elif not Path(t.get("worktree") or "-").is_dir():
            unhitched.append({**gone, "why": "its worktree is gone"})
        elif trial_merge.git(main, "merge-base", "--is-ancestor", mark["head"], default)[0] == 0:
            unhitched.append({**gone, "why": "its head is in the barn already"})
        else:
            wagons.append(t)
    return wagons, unhitched


def held_for(tickets: list[dict], own: str) -> str | None:
    """The field whose reserved place holds every train back: a waiting ticket the user's order put there, with no
    process of its own and no ready mark (plan 0294 step 12: the carrier's landing waited behind it). A leaving
    ticket in front (held, `waits_for`) holds no train back: only a waiter's look frees it, and the hitched have
    no process, so the carrier's landing has to wait behind it."""
    return next((t["slot"] for t in tickets if t.get("reserved") and not t.get("ready") and not t.get("pid")
                 and t.get("state") == "waiting" and t.get("slot") != own), None)


def draft(main: str, tickets: list[dict], own: str, base: str, default: str) -> dict:
    """Steps 1 to 4: the train the queue allows now. `cars` ([{field, branch, head, plan}] in order), `unhitched`
    ([{field, head, why, tell, ...}]), `waiting` ([{field, why}]: ready, but not in this train), `alone` (the one car
    rides alone: gate_car.py)."""
    wagons, unhitched = sort_out(main, default, tickets, own)
    out = {"base": base, "cars": [], "unhitched": unhitched, "waiting": [], "alone": False}
    acc, held = base, held_for(tickets, own)
    for t in wagons:
        field, head = t["slot"], t["ready"]["head"]
        if held:
            out["waiting"].append({"field": field, "why": HELD.format(field=held)})
            continue
        if out["alone"] or len(out["cars"]) >= MAX_CARS:
            first = out["cars"][0]["field"]
            why = f"after {first}, which rides alone" if out["alone"] else f"this one is full ({MAX_CARS} cars)"
            out["waiting"].append({"field": field, "why": "rides in the next train, " + why})
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
         result=None, mode: dict | None = None, sleep_flag: dict | None = None) -> list[dict]:
    """The round's actions for the tollman's field `top` (see the module doc). `alive(pid)` and `result(main)`
    are train_state's (the train's detached process, its last word) unless a test says otherwise; a ticket's pid is
    a landing's own process (mtm_scan.pid_alive). `mode`: the queue's (modes.py); the tollman sleeps in smuggle mode
    while no hitched entry is production, and while the sleep flag `sleep_flag` stands (plan 0365 D3, D9); a hitched
    entry whose effective mode is smuggle is no car."""
    if modes.asleep(mode, tickets, sleep_flag):  # plan 0360 step 25 (D75 2): a landing train goes on, nothing new starts
        return modes.sleep(mode, train_state.standing(rows),
                           lambda: plan(top, main, tickets, rows, panes, alive, result), sleep_flag)
    tickets = modes.trainable(tickets, mode, Path(top).name)
    landing, waiter, result = alive or train_state.alive, alive or mtm_scan.pid_alive, result or train_state.result
    own, default = Path(top).name, default_ref(main)
    mine = next((t for t in tickets if t.get("slot") == own), {})
    marked = [c.get("field") for c in (mine.get("train") or {}).get("cars", [])]
    out, after, head = [], None, "HEAD"
    pre, train, stop = pause.step(top, main, train_state.standing(rows), mine, landing, result)  # a smuggle's pause
    if stop:
        return pre  # paused: frozen, one line per pause (plan 0360 step 18, D58)
    if train and train["state"] == "landing" and landing(train["pid"]):
        return pre + watch.actions(top, main, train, rows, tickets)  # its land run read, a red job wakes once
    if train and train["state"] == "landing":  # frozen (D3): a mark that names other cars is marked again
        return pre + settle(top, train, result(main), panes, tickets)
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
        out.append(run("breakup", "-", after, "breakup", top, "--why", why, *["--by-user"] * bool(train),
                       text=f"train broken up: {why}"))
        out += [tell("unhitched", u["field"], f"split:{train['train']}:{u['field']}",
                     TEXT["split"].format(field=u["field"], why=u["why"]), panes)
                for u in (train or {}).get("unhitched", []) if u["field"] != train_state.YARD]
        head = (train or {}).get("base") or head
    own_head = trial_merge.git(top, "rev-parse", head)[1] if Path(top).is_dir() else None
    d = draft(main, tickets, own, base_of(main, default, own_head), default)
    return out + train_actions(top, d, panes, after) + yard_report.left_actions(main, d, default, rows, panes)


def handler(item: dict, ctx: dict) -> list[dict]:
    """duty:trains: the queue (its mode: modes.py, plan 0360 step 25) and the train state, then the round's actions."""
    main, top, panes, doc = ctx["main"], ctx["top"], ctx.get("panes", {}), mtm_scan.run_json(QUEUE, ctx["main"]) or {}
    tickets, mode, rows, log = doc.get("queue", []), modes.of(doc), train_state.lines(main), ctx.get("log", [])
    if not ctx.get("dry"):
        board.safely(main, "ready tickets", board.on_ready, tickets)  # a ready ticket seen first (step 7)
    flag = modes.flag(main)  # the tollman's sleep flag (plan 0365 D3)
    turn, stop = modes.turn(top, main, mode, tickets, rows, panes, flag)  # the mode noted; awake again: the barn first
    if stop:
        return turn
    return turn + plan(top, main, tickets, rows, panes, mode=mode, sleep_flag=flag) + yard_report.settled_actions(main, rows, panes) \
        + stack_red.watch(top, main, rows, panes, log) + orders.answers(top, rows, log)  # `fixed <sha>` (step 6)
