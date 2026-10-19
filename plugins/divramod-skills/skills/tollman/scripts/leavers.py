#!/usr/bin/env python3
"""A ticket never leaves the merge queue unmerged (hal2 plan 0383 step 3, D3, D14, D17; the user, 2026-10-18: "a
queued place will never be given up, except i or the farmer tell you so"; the tollman's learning L36: field 02 ran
`worktree stop` and `gh run cancel`, its ticket ended and train 20 took the gate).

`check` is deterministic and reads only the queue and git, so the 1-minute watch (plan 0383 step 4) and the round of
the duty `trains` call it each pass. It diffs the queue with the last pass (`queue-seen.json` in the tollman's state
folder: the placed tickets, the priority list) and finds

- `gone`: a placed ticket that is absent now, whose field's head is not in the barn. It comes back as a reservation
  on its place by one `hal2-cli-git worktree queue order` (the field's own `worktree reserve` or merge-to-main takes
  it over), its foreman is told once to return, and every train behind it holds until it is back;
- `stopped`: a ticket held by `worktree stop` (hold step `stopped`, plan 0383 step 2): still in its place, so nothing
  to restore, but it is not in motion: its foreman is told once to return and the trains behind it hold.

A pure hitch (a `ready` mark, no process, no reservation) is no place: the tollman unhitches those itself. A ticket
whose head is in the barn (landed), whose worktree is gone (removed through the proof), a servant's field and the
tollman's own field are no leavers. An explicit release, the user's or the farmer's word, is told to the check:
`leavers.py release <slot>`; the next pass lets that slot go. Every action carries a key, so a pass repeats nothing.

  leavers.py release <worktree> [--repo <dir>]   its place is given up on purpose (once)
  leavers.py show [--repo <dir>]             the last pass's snapshot
"""

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import mtm_scan
import trial as trial_merge
from tick import act, default_ref
from trains_sort import servant

ROLE = "tollman"
SEEN, RELEASED = "queue-seen.json", "queue-released.json"
SCHEMA = 1
STOPPED = "stopped"  # the hold step hal2-git gives a landing the user stopped (queue/stopped.rs)
NOTE = "queue-leaver"  # the board note's kind (board.NOTES)
HOUR = 3600
QUEUE_WATCH = "queue watch"
BY = "{own} (" + QUEUE_WATCH + ": {slots} returned)"
TEXT = {
    "gone": "your place in the merge queue ended without your crop in the barn ({how}): the tollman put it back, "
            "reserved, and the trains behind it hold. Run /merge-to-main now and fix your code until its workflow "
            "passes; only the user or the farmer gives a queued place up.",
    "stopped": "your landing was stopped; its place in the merge queue is kept and the trains behind it hold. Run "
               "/merge-to-main again and fix your code until its workflow passes; only the user or the farmer gives "
               "the place up (`hal2-cli-git worktree release`).",
    "note": "queue: {slot} {what}; trains behind it hold until it is back in motion",
    "stuck": "the tollman could not put the ticket of {slots} back (`{cmd}`): {what}",
}


def utc(now: dt.datetime | None = None) -> str:
    return (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def folder(main: str) -> Path:
    return mtm_scan.state_dir(main, ROLE)


def read(main: str, name: str, empty):
    file = folder(main) / name
    try:
        return json.loads(file.read_text()) if file.exists() else empty
    except (OSError, json.JSONDecodeError):
        return empty  # a torn file reads as nothing seen: the next pass writes it again


def write(main: str, name: str, doc) -> None:
    """Atomic (temp file, rename); without the tollman's folder nothing is kept (a test's, a dry look's)."""
    if not folder(main).is_dir():
        return
    file = folder(main) / name
    tmp = file.with_name(file.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(doc, indent=1) + "\n")
    os.replace(tmp, file)


def placed(t: dict) -> bool:
    """A place in the queue: not a pure hitch (a `ready` mark that waits without a process, never reserved)."""
    pure = t.get("ready") and not t.get("pid") and not t.get("reserved") and not t.get("holding") \
        and t.get("state", "waiting") == "waiting"
    return not pure


def stopped(t: dict) -> bool:
    return t.get("state") == "held" and (t.get("hold") or {}).get("step") == STOPPED


def restored(t: dict) -> bool:
    """A place this check put back (its reservation is stamped by the queue watch) that its field has not taken
    over yet: no process, no ready mark."""
    return QUEUE_WATCH in ((t.get("reserved") or {}).get("by") or "") and not t.get("pid") and not t.get("ready")


def unmerged(main: str, default: str, worktree: str | None) -> bool | None:
    """Whether the field's head is outside the barn; None when git cannot say (the worktree is gone)."""
    if not worktree or not Path(worktree).is_dir():
        return None
    code, head = trial_merge.git(worktree, "rev-parse", "HEAD")
    if code or not head:
        return None
    return trial_merge.git(main, "merge-base", "--is-ancestor", head, default)[0] != 0


def new_order(was: list[str], now: list[str], back: list[dict]) -> list[str]:
    """The priority list with the returning slots on their places: where the old list had them (after the slots
    before them that are still listed), a head of the queue in front, any other at the end of the list."""
    order = list(now)
    for b in sorted(back, key=lambda b: b["position"]):
        if b["slot"] in order:
            continue
        before = [s for s in was[:was.index(b["slot"])] if s in order] if b["slot"] in was else None
        order.insert(len(before) if before is not None else (0 if b["position"] == 0 else len(order)), b["slot"])
    return order


def entry(t: dict) -> dict:
    return {"worktree": t.get("worktree"), "position": t.get("position", 0), "seq": t.get("seq")}


def tell(kind: str, slot: str, seq, text: str, panes: dict) -> dict:
    return act("trains", kind, "send", slot, pane=panes.get(slot), key=f"told:{kind}:{slot}:{seq}", text=text)


def restore(own: str, back: list[dict], order: list[str]) -> dict:
    """The one `queue order` that puts every gone ticket back (a failed call wakes the session, a keyed retry)."""
    slots = [b["slot"] for b in back]
    argv = ["hal2-cli-git", "worktree", "queue", "order", *order, "--by", BY.format(own=own, slots=", ".join(slots))]
    key = "return:" + "+".join(f"{b['slot']}@{b['seq']}" for b in back)
    stuck = act("trains", "returned-stuck", "wake", key=f"stuck:{key}",
                text=TEXT["stuck"].format(slots=", ".join(slots), cmd=" ".join(argv), what="it failed"))
    return act("trains", "returned", "run", slots[0], key=key, window=300, argv=argv, on_fail=[stuck],
               text=f"queue: put {', '.join(slots)} back on its place")


def check(main: str, top: str, tickets: list[dict], priority: list[str], panes: dict, default: str | None = None,
          dry: bool = False) -> dict:
    """One pass: {"actions", "held": the field the trains hold for | None, "gone", "stopped", "back"} (lists of
    {slot, worktree, position, seq})."""
    own, default = Path(top).name, default or default_ref(main)
    snap, here = read(main, SEEN, {}), {t["slot"]: t for t in tickets if t.get("slot")}
    freed, seen = set(read(main, RELEASED, {}).get("slots", [])), {}
    gone, stop, back = [], [], []
    for slot, old in sorted((snap.get("seen") or {}).items(), key=lambda kv: kv[1].get("position", 0)):
        if slot in here or slot in freed or slot == own or unmerged(main, default, old.get("worktree")) is not True:
            continue
        seen[slot] = old
        gone.append({"slot": slot, **old})
    for slot, t in here.items():
        if slot == own or servant(t.get("worktree")):
            continue
        if placed(t):
            seen[slot] = entry(t)
        if stopped(t):
            stop.append({"slot": slot, **entry(t)})
        elif restored(t):
            back.append({"slot": slot, **entry(t)})
    out = _actions(own, panes, gone, stop, snap.get("order") or [], priority)
    if not dry:
        write(main, SEEN, {"schema": SCHEMA, "at": utc(), "order": list(priority), "seen": seen})
        if freed:  # a word is used up once its ticket is out of the queue
            write(main, RELEASED, {"schema": SCHEMA, "slots": sorted(freed & set(here))})
    ahead = sorted(gone + stop + back, key=lambda b: b["position"])
    return {"actions": out, "held": ahead[0]["slot"] if ahead else None, "gone": gone, "stopped": stop, "back": back}


def _actions(own: str, panes: dict, gone: list[dict], held: list[dict], was: list[str], now: list[str]) -> list[dict]:
    out = []
    if gone:
        out.append(restore(own, gone, new_order(was, now, gone)))
    for b in gone:
        out.append(tell("returned", b["slot"], b["seq"], TEXT["gone"].format(how="the ticket ended unmerged"), panes))
        out.append(act("trains", NOTE, "record", own, key=f"note:gone:{b['slot']}:{b['seq']}", window=HOUR * 24,
                       text=TEXT["note"].format(slot=b["slot"], what="left the queue unmerged and is put back")))
    for b in held:
        out.append(tell("stopped", b["slot"], b["seq"], TEXT["stopped"], panes))
        out.append(act("trains", NOTE, "record", own, key=f"note:stopped:{b['slot']}:{b['seq']}", window=HOUR * 24,
                       text=TEXT["note"].format(slot=b["slot"], what="was stopped and keeps its place")))
    return out


def release(main: str, slot: str) -> None:
    """The user's or the farmer's word: this worktree's place is given up on purpose; the next pass lets it go."""
    write(main, RELEASED, {"schema": SCHEMA, "slots": sorted({*read(main, RELEASED, {}).get("slots", []), slot})})


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    rel, show = sub.add_parser("release"), sub.add_parser("show")
    rel.add_argument("slot")
    for x in (rel, show):
        x.add_argument("--repo", default=os.getcwd())
    a = p.parse_args(argv)
    main_dir = mtm_scan.main_checkout(a.repo)
    if a.cmd == "release":
        release(main_dir, a.slot)
        print(f"{a.slot}: its place is given up on purpose; the next pass lets it go")
    else:
        print(json.dumps(read(main_dir, SEEN, {}), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
