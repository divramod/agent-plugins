#!/usr/bin/env python3
"""The merge queue's two modes in the tollman's round (hal2 plan 0360 step 25, D74 to D76). hal2-git keeps the
mode (`queue --json`'s `mode: {mode, by, at, why}`, production when missing; the farmer's queue_mode.of reads it);
only the user switches it.

1. Asleep (D75 2): in smuggle mode `trains.plan` returns `sleep`'s actions: one `asleep` record per round ("asleep:
   smuggle mode since <t> (by <who>)", no key, so one tick.log line each round) and nothing new: no train formed or
   started again, no retry, no breakup, no wake. A train already landing is never cut: its pause and run are watched
   and a landing that lands settles as ever (KEEP); a landing that ends red or interrupted is left as it is, the
   train stays `landing` with its process gone, and the first round in production settles it (triage, wake, fix
   order) and its cars stay hitched. `busy` holds every ci-check back (the duty `checks`).
2. Awake again (D75 5, D76): the round notes the mode it saw (`seen-mode`, `mode.json` in the state folder). The first
   round in production after smuggle mode, before any train, finds the cars already in the barn (`git merge-base
   --is-ancestor <head> <default>`): a waiting hitch is cleared, a car of a formed train (not landing: formed, red,
   fixing, retry, split) leaves it (D76 amends D3 for this case only), a car of a running train (landing, paused) is
   only recorded; each a `barn` line of train.jsonl (`tollman.py barn`) and its foreman told once (`in-barn`); then
   the chain goes on in the same round. A formed train whose every car left is cleared.

  tollman.py seen-mode production|smuggle [--repo <dir>]                     the mode this round saw
  tollman.py barn <field> --head <sha> --how hitch|formed|running [--train <name>] [--repo <dir>]
"""

import json
import sys
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import chain
import engine
import mtm_scan
import queue_mode
import train_state
import trial
from tick import act, default_ref

CLI = Path(__file__).with_name("tollman.py")
FILE = "mode.json"
VERBS = ("seen-mode", "barn")
QUEUE = queue_mode.QUEUE
RUNNING = ("landing", "paused")  # a car of such a train is only recorded; of every other standing train it leaves
KEEP = ("train-paused", "train-resumed", "train-run", "train-stuck", "landed", "in-the-barn", "stack-red",
        "stack-red-fix", "chain")  # what a landing train still does while asleep: watched, paused, landed
TEXT = {"in_barn": "tollman (wagon train): field {field}'s crop ({head}) is already in the barn (smuggled in smuggle "
                   "mode): {what}. Nothing of it is carried again: /merge-from-main and finish the plan as after \"in the barn\"."}
WHAT = {"hitch": "its hitch is cleared", "formed": "it left the formed train {train}",
        "running": "the running train {train} carries nothing new of it"}


def of(doc: dict | None) -> dict:
    return queue_mode.of(doc)


def asleep(mode: dict | None) -> bool:
    return queue_mode.smuggle(mode or {})


def busy(mode: dict | None) -> dict | None:
    """The duty `checks`' reason to hold every check back in smuggle mode, or None."""
    return {"reason": f"smuggle mode since {mode.get('at')} (by {mode.get('by')}): the tollman sleeps", "slot": ""} \
        if asleep(mode) else None


def sleep(mode: dict, train: dict | None, inner) -> list[dict]:
    """trains.plan in smuggle mode: the asleep line, and of a landing train what KEEP lets through (`inner()` is the
    production plan)."""
    line = act("trains", "asleep", "record", text=f"asleep: smuggle mode since {mode.get('at')} (by {mode.get('by')})")
    going = [a for a in inner() if a["kind"] in KEEP] if train and train["state"] in RUNNING else []
    return [line] + going


def seen(main: str) -> str:
    """The mode the last round saw (production when never noted)."""
    f = mtm_scan.state_dir(main, train_state.ROLE) / FILE
    try:
        return json.loads(f.read_text()).get("mode") or queue_mode.PRODUCTION
    except (OSError, ValueError, AttributeError):
        return queue_mode.PRODUCTION


def cli(top: str, kind: str, key: str, text: str, *args: str, **kw) -> dict:
    argv = [sys.executable, str(CLI), *args, "--repo", top]
    stuck = act("trains", "train-stuck", "wake", key=f"stuck:{key}", text=f"{text}: failed, run `{' '.join(argv[1:])}`")
    return act("trains", kind, "run", kw.pop("slot", "-"), key=key, argv=argv, text=text, on_fail=[stuck], **kw)


def in_barn(main: str, default: str, tickets: list[dict], train: dict | None, own: str) -> list[dict]:
    """The cars and hitches whose head is in `default` already: [{field, head, how, train}]."""
    def landed(head: str) -> bool:
        return bool(head) and trial.git(main, "merge-base", "--is-ancestor", head, default)[0] == 0
    how = "running" if train and train["state"] in RUNNING else "formed"
    found = [{"field": c["field"], "head": c["head"], "how": how, "train": train["train"]}
             for c in (train or {}).get("cars", []) if c["field"] not in train.get("in_barn", []) and landed(c["head"])]
    riding = {c["field"] for c in (train or {}).get("cars", [])} | {own}
    return found + [{"field": t["slot"], "head": t["ready"]["head"], "how": "hitch", "train": None} for t in tickets
                    if t.get("ready") and t.get("slot") not in riding and not t.get("rides_with")
                    and t.get("state", "waiting") == "waiting" and landed(t["ready"].get("head"))]


def turn(top: str, main: str, mode: dict, tickets: list[dict], rows: list[dict], panes: dict) -> tuple[list, bool]:
    """(the actions, whether the round ends with them): the mode noted when it changed; the first production round
    after smuggle mode drops the cars in the barn first and goes on through the chain."""
    now, last = mode.get("mode") or queue_mode.PRODUCTION, seen(main)
    note = [cli(top, "seen-mode", f"seen-mode:{now}:{mode.get('at')}", f"the queue's mode is {now}", "seen-mode",
                now)] if now != last else []
    if last != queue_mode.SMUGGLE or asleep(mode):
        return note, False
    found = in_barn(main, default_ref(main), tickets, train_state.standing(rows), Path(top).name)
    if not found:
        return note, False
    out = []
    for c in found:
        key, what = f"barn:{c['field']}:{c['head'][:12]}", WHAT[c["how"]].format(train=c["train"])
        out.append(cli(top, "barn", key, f"{c['field']} is in the barn already: {what}", "barn", c["field"], "--head",
                       c["head"], "--how", c["how"], *(["--train", c["train"]] if c["train"] else []), slot=c["field"]))
        out.append(act("trains", "in-barn", "send", c["field"], pane=panes.get(c["field"]), key=f"told:{key}",
                       after=key, text=TEXT["in_barn"].format(field=c["field"], head=c["head"][:12], what=what)))
    return out + note + [chain.action(top, out[-2]["key"])], True


def barn(repo: str, field: str, head: str, how: str, name: str | None) -> tuple[int, str]:
    """The verb: the `barn` line; a hitch or a formed train's car loses its ready mark; a formed train left without
    a car is cleared."""
    main = mtm_scan.main_checkout(repo)
    train_state.append(main, "barn", field, train=name, head=head, how=how)
    said = f"{field} is in the barn already ({how})"
    if how in ("hitch", "formed"):
        code, text = engine.cli(["worktree", "queue", "ready", field, "--clear", "--json"], main)
        said += "; hitch cleared" if not code else f"; its mark stays: {text[-200:]}"
    train = train_state.standing(train_state.lines(main))
    if how == "formed" and train and not train["cars"] and not train.get("yard"):
        code, text = engine.clear(repo, "every car is in the barn already (smuggled)")
        return code, f"{said}; {text}"
    return 0, said


def add_parser(sub) -> None:
    sub.add_parser("seen-mode").add_argument("mode", choices=(queue_mode.PRODUCTION, queue_mode.SMUGGLE))
    b = sub.add_parser("barn")
    b.add_argument("field")
    b.add_argument("--head", required=True)
    b.add_argument("--how", required=True, choices=tuple(WHAT))
    b.add_argument("--train")


def main(args) -> int:
    if args.cmd == "seen-mode":
        main_dir = mtm_scan.main_checkout(args.repo)
        f = mtm_scan.state_dir(main_dir, train_state.ROLE) / FILE
        f.write_text(json.dumps({"mode": args.mode, "at": train_state.utc()}) + "\n")
        print(f"the queue's mode seen: {args.mode}")
        return 0
    code, text = barn(args.repo, args.field, args.head, args.how, args.train)
    print(text, file=sys.stderr if code else sys.stdout)
    return code
