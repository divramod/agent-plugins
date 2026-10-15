#!/usr/bin/env python3
"""Wagon trains as code: what the duty `trains` plans each round (hal2 plan 0294 step 6; hal2's
.adr/merge-queue-policy.md rule 3). The wagon master's own field `wagon-master-<repo>` carries every train (D8); a
foreman's whole part is the hitch, `hal2-cli-git worktree queue ready` (D9). This module only reads (the queue, git,
the train state, the landing's log) and returns the frame's actions, each with a `key`; `engine.py` does them.

Between trains (`draft`, steps 1 to 4; `wagon_master.py train --dry-run` prints it):
1. the tickets marked `ready`, in queue order; none: nothing to do
2. what cannot ride is unhitched: a head that is in the barn already (no message), a servant's field (30-99);
   while a place the user reserved for a field that is not ready stands in the queue, the others wait: a landing
   waits behind such a place (.adr/merge-queue-policy.md rule 2), and that field is to land first
3. the alone rule (D11): a crop touching the landing workflow, a gate job list or the runner setup (ALONE) is a
   train of one; first in the queue it rides alone, otherwise it waits for the next train
4. the trial merge in queue order (trial.py): a wagon that conflicts is unhitched and its foreman told why (a
   template), unless every file of the conflict is generated (generated.py: the train writes them again); the
   rest rides, no maximum
5. `engine.py form`: the yard's work as the first car (yard.py, step 8), merge, mark, start the landing detached;
   what the yard keeps is told to the farmer (yard_report.py)

While a train stands (`standing`, step 6): its landing still runs: nothing. Landed: every car's foreman is told
"in the barn" (D12). Red: one wake (`train-failed`), then nothing until the session's `wagon_master.py unhitch` or
`retry`. Interrupted (the process gone without a result): the same landing again, it adopts the run; after
MAX_STARTS the session is woken instead. A car unhitched after red, or a train never started: broken up, and the
rest forms again in the same round. A mark without a train of ours (a dead wagon master's, step 7) is cleared.
"""

import json
import re
import sys
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import board
import generated
import mtm_scan
import stack_red
import train_state
import trial as trial_merge
import yard_report
from tick import act, default_ref

QUEUE = ["hal2-cli-git", "worktree", "queue", "--json"]
ROLE = "wagon-master"
TRAIN = ROLE + " (wagon train)"
ENGINE = Path(__file__).with_name("engine.py")
ALONE = re.compile(r"^(\.github/workflows/|\.github/hal2-[^/]*\.toml$|code/bash/scripts/gate/)")
MAX_STARTS = 5  # an interrupted landing is started again this often, then the session looks
HOUR = 3600
LANDED = ("landed", "nothing")  # the landing's results that mean: every car's crop is in the barn
AGAIN = (None, "interrupted", "waiting", "testing", "paused")  # no result, or one whose rerun goes on
HELD = ("the place reserved for field {field} stands in the queue and {field} is not ready: a train's landing waits "
        "behind it (the user's order; `hal2-cli-git worktree queue order`)")
HITCH = "report it ready again (`hal2-cli-git worktree queue ready`)"
TEXT = {
    "conflict": TRAIN + ": field {field} is unhitched: its crop conflicts with {what} in {files}. {then}, resolve "
                        "it, push and " + HITCH + ".",
    "servant": TRAIN + ": field {field} is unhitched: a servant's field (30-99) never rides a train, its foreman "
                       "merges its branch.",
    "split": TRAIN + ": field {field} is unhitched from the red train: {why}. Fix it, push and " + HITCH + ".",
    "barn": TRAIN + ": your crop is in the barn (the train of {cars}{run}). Restock (/mfm), finish your plan (the "
                    "steps checked after the landing; a commit they need rides the next train) and muck out.",
    "failed": "train {train} did not land ({status}): {why}. Run: {run}. Cars: {cars}. Name the car that broke it "
              "(`wagon_master.py unhitch <field> --why <why>`: the rest forms again; the yard's car is `yard`) or "
              "land it again as it is (`wagon_master.py retry --why <why>`: a flaky gate).",
    "stuck": "the train engine's `{verb}` failed ({what}): run `{cmd}` to see why, then `wagon_master.py train "
             "--dry-run`.",
}


def current_plan(worktree: str) -> str:
    """The first line of the worktree's plans/CURRENT_PLAN, or ''."""
    current = Path(worktree) / "plans/CURRENT_PLAN"
    text = current.read_text() if current.exists() else ""
    return next((line.strip() for line in text.splitlines() if line.strip()), "")


def servant(field: str) -> bool:
    return len(field) == 2 and field.isdigit() and 30 <= int(field) <= 99


def alone_files(main: str, default: str, head: str) -> list[str]:
    """The crop's files that make it ride alone (D11): what `head` changed since it left the barn."""
    return [f for f in trial_merge.git(main, "diff", "--name-only", f"{default}...{head}")[1].splitlines()
            if ALONE.match(f)]


def base_of(main: str, default: str, own: str | None) -> str:
    """What the cars are merged onto: the barn's head, with what the wagon master's field holds beyond it (`own`)."""
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
    ([{field, head, why, tell, ...}]), `waiting` ([{field, why}]: ready, but not in this train), `alone`."""
    wagons, unhitched = sort_out(main, default, tickets, own)
    out = {"base": base, "cars": [], "unhitched": unhitched, "waiting": [], "alone": False}
    acc, held = base, held_for(tickets, own)
    for t in wagons:
        field, head = t["slot"], t["ready"]["head"]
        if held or out["alone"]:
            why = HELD.format(field=held) if held else f"{out['cars'][0]['field']} rides alone"
            out["waiting"].append({"field": field, "why": why})
            continue
        touched = alone_files(main, default, head)
        if touched and out["cars"]:
            out["waiting"].append({"field": field, "why": f"rides alone in the next train ({touched[0]})"})
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
        else:
            out["cars"].append({"field": field, "branch": t.get("branch") or field, "head": head,
                                "plan": current_plan(t["worktree"])})
            acc, out["alone"] = commit, bool(touched)
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
    """What a foreman is told whose field the draft unhitched (`tell`: `servant` or `conflict`)."""
    if u["tell"] == "servant":
        return TEXT["servant"].format(field=u["field"])
    ahead = ", ".join(u["ahead"])
    return TEXT["conflict"].format(
        field=u["field"], files=", ".join(u["files"][:5]), what=f"the cars ahead ({ahead})" if ahead else "the barn",
        then=f"Restock (/mfm) once the train of {ahead} is in the barn" if ahead else "Restock (/mfm)")


def settle(top: str, train: dict, result: dict | None, panes: dict) -> list[dict]:
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
                         for c in train["cars"]] + stack_red.actions(top, train, result, panes, key)
    if status in AGAIN and train["starts"] < MAX_STARTS:
        return [run("restart", "-", f"restart:{name}:{train['starts']}", "restart", top,
                    text=f"train {name}: its landing ended {status or 'without a result'}, started again")]
    if status in AGAIN:
        status, why = "interrupted", f"its landing ended without a result {train['starts']} times"
    else:
        red = ", ".join(j.get("name", "") for j in result.get("red") or [])
        why = (red or result.get("message") or status)[:300]
    link, key = (result or {}).get("run"), f"red:{name}:{train['starts']}"
    plans = ", ".join(f"{c['field']} ({c.get('plan') or c['branch']})" for c in train["cars"])
    plans += f", yard ({len(train['yard'])} files of the yard)" if train.get("yard") else ""
    return [run("red", "-", key, "red", top, "--status", status, *(["--run", link] if link else []), "--why", why,
                text=f"train {name} is red ({status}): {why}"),
            act("trains", "train-failed", "wake", key=f"train-failed:{name}:{train['starts']}", after=key,
                text=TEXT["failed"].format(train=name, status=status, why=why, run=link or "none", cars=plans),
                evidence={"train": train, "result": result})]


def plan(top: str, main: str, tickets: list[dict], rows: list[dict], panes: dict, alive=None,
         result=None) -> list[dict]:
    """The round's actions for the wagon master's field `top` (see the module doc). `alive(pid)` and `result(main)`
    are train_state's (the train's detached process, its last word) unless a test says otherwise; a ticket's pid is
    a landing's own process (mtm_scan.pid_alive)."""
    landing, waiter, result = alive or train_state.alive, alive or mtm_scan.pid_alive, result or train_state.result
    own, default = Path(top).name, default_ref(main)
    mine = next((t for t in tickets if t.get("slot") == own), {})
    marked = [c.get("field") for c in (mine.get("train") or {}).get("cars", [])]
    train, out, after, head = train_state.standing(rows), [], None, "HEAD"
    if train and train["state"] == "landing" and landing(train["pid"]):
        return []
    stale = bool(train and marked and marked != [c["field"] for c in train["cars"]])
    if train and not stale and train["state"] == "landing":
        return settle(top, train, result(main), panes)
    if train and not stale and train["state"] == "retry":
        return [run("restart", "-", f"retry:{train['train']}:{train['starts']}", "restart", top,
                    text=f"train {train['train']} lands again")]
    if train and not stale and train["state"] == "red":
        return []
    if not train and waiter(mine.get("pid")) and not mine.get("waits_for"):
        return []  # a landing of the field runs that is no train of ours: never touched (a leaving ticket's ended)
    if train or marked:
        why = ("the queue's mark names other cars" if stale else "its landing never started" if train and
               train["state"] == "formed" else "split after red" if train else "a mark without a train of ours")
        after = f"breakup:{train['train']}" if train else f"leftover:{mine['train'].get('at', '')}"
        out.append(run("breakup", "-", after, "breakup", top, "--why", why, text=f"train broken up: {why}"))
        out += [tell("unhitched", u["field"], f"split:{train['train']}:{u['field']}",
                     TEXT["split"].format(field=u["field"], why=u["why"]), panes)
                for u in (train or {}).get("unhitched", []) if u["field"] != train_state.YARD]
        head = (train or {}).get("base") or head
    own_head = trial_merge.git(top, "rev-parse", head)[1] if Path(top).is_dir() else None
    d = draft(main, tickets, own, base_of(main, default, own_head), default)
    return out + train_actions(top, d, panes, after) + yard_report.left_actions(main, d, default, rows, panes)


def handler(item: dict, ctx: dict) -> list[dict]:
    """duty:trains: the queue and the train state, then the round's actions."""
    tickets = (mtm_scan.run_json(QUEUE, ctx["main"]) or {}).get("queue", [])
    if not ctx.get("dry"):
        board.safely(ctx["main"], "ready tickets", board.on_ready, tickets)  # a ready ticket seen first (step 7)
    rows, panes = train_state.lines(ctx["main"]), ctx.get("panes", {})
    return (plan(ctx["top"], ctx["main"], tickets, rows, panes) + yard_report.settled_actions(ctx["main"], rows, panes)
            + stack_red.watch(ctx["top"], ctx["main"], rows, panes, ctx.get("log", [])))


def dry_run(repo: str) -> dict:
    """`wagon_master.py train --dry-run`: the train that stands and steps 1 to 4 for the next one (without the cars
    that ride the standing one), and what the yard would give it (`yard`: placed and left); nothing is written,
    merged or sent. From any checkout of the farm: the field is the wagon master's when it exists."""
    main = mtm_scan.main_checkout(repo)
    top = mtm_scan.roles.slot_dir(main, ROLE)
    rows, default = train_state.lines(main), default_ref(main)
    train = train_state.standing(rows)
    rides = {c["field"] for c in train["cars"]} if train and train["state"] not in ("formed", "split") else set()
    tickets = [t for t in (mtm_scan.run_json(QUEUE, main) or {}).get("queue", []) if t.get("slot") not in rides]
    head = (train or {}).get("base") or (trial_merge.git(str(top), "rev-parse", "HEAD")[1] if top.is_dir() else None)
    d = draft(main, tickets, top.name, base_of(main, default, head), default)
    return {"field": top.name, "standing": train, **d,
            "yard": yard_report.seen(main, d["base"], default, d["cars"], rows)}


def print_dry_run(d: dict) -> None:
    t = d["standing"]
    print(f"standing: train {t['train']} ({t['state']})" if t else "standing: no train")
    print("next train" + (" (alone)" if d["alone"] else "") + ": "
          + (", ".join(f"{c['field']} ({c['plan'] or c['branch']}, {c['head'][:12]})" for c in d["cars"]) or "none"))
    for name in ("unhitched", "waiting"):
        for x in d[name]:
            print(f"{name}: {x['field']}: {x['why']}")
    print("\n".join(yard_report.lines(d["yard"])) or "yard: nothing uncommitted that may ride")
