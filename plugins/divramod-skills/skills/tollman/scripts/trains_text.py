#!/usr/bin/env python3
"""The tollman's messages and board texts (split out of trains.py by plan 0695 step 51, small-files): `TEXT` by kind,
trains.py re-exports it."""

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import modes
import pause
import smuggled
import train_red

TRAIN = "tollman (wagon train)"

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


def barn_text(cars: str, link: str | None, car: dict) -> str:
    """The foreman's "in the barn" text; a milestone car's adds that its plan stays open and it runs `/continue`."""
    text = TEXT["barn"].format(cars=cars, run=f", {link}" if link else "")
    if car.get("milestone"):
        text = text.split(": /merge-from-main")[0] + TEXT["milestone"].format(label=car["milestone"])
    return text


def reds(result: dict) -> str:
    """The red jobs of a landing's result: each with its own suspects when it names them (a pretest's, plan 0522
    D14: `a (car 07), b (cars 07, 09)`), else the names and the result's suspects."""
    red, suspects = result.get("red") or [], result.get("suspects")
    if red and all(j.get("suspects") for j in red):
        return ", ".join(f"{j.get('name', '')} (car{'s' * (len(j['suspects']) > 1)} {', '.join(j['suspects'])})"
                         for j in red)
    names = ", ".join(j.get("name", "") for j in red)
    return f"{names}, suspects: {', '.join(suspects)}" if names and suspects else names
