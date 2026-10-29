"""A train is frozen at forming (hal2 plan 0360 D3, D7): before forming wagons still drop out (trains.draft: a
servant's field, a gone worktree, a head in the barn, a conflict, red light checks, the alone rule); from its
`formed` line on nothing leaves the train, a later hitch waits for the next one, and no wait limit ends it: a red
train waits until it is fixed. Only the user's own command (`--by-user`) breaks a formed train up or takes a car out
of it; the session never passes it. The one undo left is `engine.form`'s own: a car that does not merge there, or a
mark the queue refuses, undoes that same call's forming, before the train ever was in the queue.

`merge_car` is the merge of one car into the carrier (`form`'s, and `complete`'s for a train whose form died between
its lines); `complete` merges the cars the carrier lacks, so `restart` lands the same train, never a new draft.
"""

from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import generated
import origin
import lead_marker
from carrier import Done, git

CURRENT = "CURRENT_PLAN"  # the pointer's name: the git dir's, else plans/ (hal2 plan 0409 step 12)
POINTERS = lead_marker.pointers
USER = "user"  # an `unhitched` line's `by`: the user's own command (`--by-user`)


def refused(train: dict, what: str) -> str:
    """Why the session may not do `what` to the standing train."""
    return (f"train {train['train']} ({train['state']}) is frozen (plan 0360 D3): {what} is refused; nothing leaves a "
            "formed train and no wait limit ends it (D7), a red one waits for its fix. Only the user's own command "
            "(`--by-user`, never the session's) breaks it up or takes a car out")


def by_user(train: dict) -> bool:
    """A split train whose every unhitch was the user's own command."""
    return bool(train["unhitched"]) and all(u.get("by") == USER for u in train["unhitched"])


def merge_car(top: str, branch: str, car: dict) -> tuple[int, str, list[str]]:
    """One car merged into the carrier (a merge commit); a conflict only in generated files takes the barn's side
    (generated.py): its exit, output and the generated files taken."""
    what = f"wagon train: field {car['field']} ({car.get('plan') or car['branch']}), head {car['head']}"
    # neutral commits (plan 0409 D15): the subject stays git's own, which hal2-git's title reads the cars from; no body
    # naming the field and plan, no trailers
    body = [] if origin.neutral(top) else ["-m", what]
    code, out = git(top, "merge", "-q", "--no-ff", "-m", f"Merge branch '{car['branch']}' into {branch}", *body,
                    *origin.paragraph(top, [car["field"]], [car.get("plan") or ""]), car["head"])
    got = generated.take(top, "--ours") if code else []
    return (0 if got else code), out, got


def write_current(top: str, cars: list[dict], yard: bool) -> None:
    """The CURRENT_PLAN pointer: `yard` and the cars' plan names joined by ` + ` (the land run's title)."""
    POINTERS.write(top, CURRENT, " + ".join(["yard"] * yard + [c.get("plan") or c["field"] for c in cars]))


def complete(top: str, train: dict) -> Done:
    """The cars of a formed train its carrier lacks, merged in order (a form that died between its lines): the train
    stays the same, a car that does not merge leaves it standing and the restart fails (the tick wakes the session)."""
    branch = git(top, "branch", "--show-current")[1] or Path(top).name
    merged = []
    for car in train["cars"]:
        if git(top, "merge-base", "--is-ancestor", car["head"], "HEAD")[0] == 0:
            continue
        code, out, taken = merge_car(top, branch, car)
        if code:
            git(top, "merge", "--abort")
            return 1, f"car {car['field']} of train {train['train']} did not merge: {out[-300:]}; the train stands (D3)"
        if taken:
            code, text, _, _ = generated.regenerate(top, sorted(set(taken)), [c["field"] for c in train["cars"]])
            if code:
                return 1, f"{text}; the train stands (D3)"
        merged.append(car["field"])
    if merged or not POINTERS.exists(top, CURRENT):
        write_current(top, train["cars"], bool(train.get("yard")))
    return 0, f"merged the missing cars {', '.join(merged)}" if merged else ""
