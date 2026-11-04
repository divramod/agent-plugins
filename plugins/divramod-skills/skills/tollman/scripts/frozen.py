"""A train is frozen at forming (hal2 plan 0360 D3, D7): before forming a wagon waits only under a user-named
exception (trains_draft.EXCEPTIONS: a servant's field, a head in the barn, a smuggle entry, the sleep flag, a reserved
place, the user's hold); a conflict and red light checks ride; from its `formed` line on nothing leaves the train, and
no wait limit ends it: a red train waits until it is fixed. A later hitch joins the standing train until its push
starts, in every state before it (formed, resolving, red, fixing, retry, its landing before the push), with its
resolve or fix order when it has a conflict or red light checks (open_train.py, train_join.py; plan 0490 step 20,
plan 0610 D17); from the push on it rides the next train. Only the user's own command (`--by-user`, typed by the user
or relayed by the farmer as "the user decided") breaks a formed train up or takes a car out of it; the session never
passes it on its own judgment. Nothing undoes a forming or a join (plan 0610 E6, E25): a car that does not merge
waits `resolving` with its resolve order (resolve_train.py), a failed regenerate or a refused mark leaves the train
standing for its next start, which marks it and merges the cars the carrier lacks (engine.restart).

`merge_car` is the merge of one car into the carrier (`form`'s by resolve_train.merge_rest, open_train.join's);
`lacking` names the cars the carrier lacks (engine.restart, open_train.stops).
"""

from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import generated
import origin
import lead_marker
from carrier import git

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


def lacking(top: str, train: dict) -> list[str]:
    """The cars of the standing train the carrier `top` lacks (a form that died, a join recorded outside a landing:
    engine.restart merges them first, plan 0610 D17)."""
    return [c["field"] for c in train["cars"] if git(top, "merge-base", "--is-ancestor", c["head"], "HEAD")[0]]


def write_current(top: str, cars: list[dict], yard: bool) -> None:
    """The CURRENT_PLAN pointer: `yard` and the cars' plan names joined by ` + ` (the land run's title)."""
    POINTERS.write(top, CURRENT, " + ".join(["yard"] * yard + [c.get("plan") or c["field"] for c in cars]))
