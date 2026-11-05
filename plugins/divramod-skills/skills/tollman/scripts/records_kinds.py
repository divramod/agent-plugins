"""The tollman's record kinds (hal2 plan 0611 step 3, design.md §2): registered with the farmer frame's role_records,
and the one call every writer makes right after its train line.

A record is written by the command that does the action, in the same call as its `train.jsonl` (or log) line, which
it names (`event`, D10); there is no record verb (D4). The kinds and their writers:

- `fix-order`: orders.order, own_fix.order (an `also` adds jobs to the same order: no second record)
- `user-order`: engine_car.unhitch and engine.breakup with `--by-user --words`
- `hand-merge`: train_join.join by hand (no `--car`)
- `restart`: `tollman.py restart <field>` (foreman_wake.restart: a session) and engine_car.retry (a train)
- `standing`: standing.add (`tollman.py standing add`, `hold`): no code closer, only the user's relayed revoke
- `question`: `acks.py instruct ... --role tollman` (the farmer frame loads this module by skillpath)

Each kind names its closer, a function of records_close.py (step 4) reading code facts only, swept by `tollman.py
tick`. This module imports only role_records, and records_close only inside a check: acks.py loads it from the
farmer's folder, where no tollman module is on the path (a tollman script has imported farmer_frame before it).
"""

import datetime as dt
import re

import role_records
from role_records import Kind

ROLE = "tollman"


def closer(name: str):
    """The kind's `check`: records_close's function `name`, imported when a sweep first calls it."""
    def check(record: dict, facts: dict):
        import records_close
        return getattr(records_close, name)(record, facts)
    return check


KINDS = {
    "fix-order": Kind("fix_order", ("orders.order", "own_fix.order"), closer("fix_order")),
    "user-order": Kind("user_order", ("engine_car.unhitch", "engine.breakup"), closer("user_order")),
    "hand-merge": Kind("hand_merge", ("train_join.join",), closer("hand_merge")),
    "restart": Kind("restart", ("foreman_wake.restart", "engine_car.retry"), closer("restart")),
    "question": Kind("question", ("acks.instruct",), closer("question"), hows=("void",)),
    "standing": Kind("user", ("standing.add",)),  # the user's lasting orders (step 5): closed only by a relayed revoke
}
role_records.register(ROLE, KINDS)

# What a handoff sentence may not say while the standing order is open (step 7, design.md §5, D9): rule -> (the words
# against it, the words that make the sentence an exception). A negated match ("no train forms") is no contradiction.
CONTRA = {
    "every-wagon-rides": (re.compile(r"\bfields?\s*\d+\b[^.\n]*?\b(?:waits?|waiting|held back|deferred|left out|(?:moves?|goes|pushed|slips?) to the next train)\b", re.I),
                          re.compile(r"\b(?:unless|except|until|because|only when|only if)\b|\bthe user\b", re.I)),
    "hold": (re.compile(r"\btrains?\s+(?:form|forms|formed|run|runs|land|lands)\b|\bno hold\b"
                        r"|\bhold (?:is )?(?:over|off|lifted|released)\b", re.I),
             re.compile(r"\b(?:unless|except|until|once|after|when)\b", re.I)),
}


def _negated(sentence: str, at: int) -> bool:
    before = re.split(r"[;.:]", sentence[max(0, at - 40):at])[-1]
    return bool(re.search(r"\b(?:never|no|not|nobody|nor|without|don'?t|do not|must not|cannot)\b", before, re.I))


def against_standing(record: dict, sentence: str) -> bool:
    """True when `sentence` goes against the open standing order `record` (its rule's CONTRA words, unnegated)."""
    pair = CONTRA.get(record.get("rule"))
    if pair is None or pair[1].search(sentence):
        return False
    return any(not _negated(sentence, m.start()) for m in pair[0].finditer(sentence))


role_records.register_contra(ROLE, {"standing": against_standing})


def train_event(kind: str, **keys) -> dict:
    """The `event` naming a `train.jsonl` line: its kind and the keys that find it (id, train, field)."""
    return {"file": "train.jsonl", "kind": kind, **{k: v for k, v in keys.items() if v is not None}}


def add(main: str, type: str, slot: str, what: str, by: str = ROLE, event: dict | None = None,
        now: dt.datetime | None = None, **keys) -> dict:
    """Open the tollman's record (role_records.add): its line, `id` = `R<n>`; `what` made one line."""
    return role_records.add(main, ROLE, type, slot, " ".join(what.split())[:240], by, event=event, now=now, **keys)
