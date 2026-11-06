#!/usr/bin/env python3
"""Standing orders (hal2 plan 0611 step 5, design.md §3, D13): the user's lasting orders to the tollman as records.

A standing order is an open `standing` record of the tollman's records store (role_records): a `rule` from the closed
table RULES, a `value`, the user's `words` (required: only the user, or the farmer relaying "the user decided", sets
one; ~/.adr/tollman-follows-the-farmer.md) and `by: user`. The train code reads the open ones: `hold.of` the `hold`,
`trains.minimum` / `train_cars.of` the `minimum`, `trains.draft` the `max-cars`; `every-wagon-rides` has no train logic (trains_draft.close already
enforces it), the handoff check and `state` read it. One open record per rule: a second `add` of a rule revokes the
older in the same call. Only a relayed revoke (`how: user`, with the user's words) closes one; no code closer.

  tollman.py standing add <rule> [--value <v>] --by user --words "<the user's words>" [--repo <dir>]
  tollman.py standing revoke R<n> --by user --words "<the user's words>" [--repo <dir>]
  tollman.py standing list [--json] [--repo <dir>]
"""

import argparse
import datetime as dt
import json

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import mtm_scan
import records_kinds
import role_records

ROLE = records_kinds.ROLE
TYPE = "standing"
RULES = {
    "hold": "no train forms, restarts or lands; the value is the reason (hold.py)",
    "minimum": "the hitched fields a train needs; the value is the number (trains.MIN_HITCHED is the default)",
    "max-cars": "the most cars a train takes, in queue order; the rest wait hitched for the next train (trains.draft)",
    "every-wagon-rides": "every hitched wagon rides the next train; none is held back (trains_draft.close)",
}
NUMBERED = ("minimum", "max-cars")
USER = "user"
NOT_USER = "a standing order is the user's: `--by user --words \"<the user's words>\"`, typed by the user or relayed by " \
           "the farmer as \"the user decided\" (a session's own is refused)"


def refusal(by: str, words: str) -> str:
    """Why `by`/`words` may not set or end a standing order, or ""."""
    return "" if by == USER and words.strip() else NOT_USER


def _check(rule: str, value) -> str:
    """The value as stored (text), ValueError for an unknown rule or a value the rule cannot take."""
    if rule not in RULES:
        raise ValueError(f"no standing rule {rule!r}; the rules: {', '.join(RULES)}")
    text = "" if value is None else str(value).strip()
    if rule in NUMBERED and not (text.isdigit() and int(text) >= 1):
        raise ValueError(f"the rule {rule} needs a whole number from 1 as its --value")
    return text


def opened(main: str) -> list[dict]:
    """The open standing orders, oldest first; none when the store is not there (nothing is created)."""
    if not (mtm_scan.state_dir(main, ROLE) / role_records.FILE).exists():
        return []
    return [r for r in role_records.open_(main, ROLE) if r["type"] == TYPE]


def of(main: str, rule: str) -> dict | None:
    """The open order of `rule` (the newest), or None."""
    found = [r for r in opened(main) if r.get("rule") == rule]
    return found[-1] if found else None


def value(main: str, rule: str, default=None):
    """The open order's value (an int for `minimum`, the text otherwise), else `default`."""
    rec = of(main, rule)
    if rec is None:
        return default
    return int(rec["value"]) if rule in NUMBERED else rec.get("value", "")


def add(main: str, rule: str, val, words: str, now: dt.datetime | None = None) -> dict:
    """Open the standing order `rule` for the user's `words`; an older open one of the rule is revoked by it.
    ValueError for an unknown rule, a bad value or empty words."""
    text = _check(rule, val)
    if not words.strip():
        raise ValueError(NOT_USER)
    older = [r["id"] for r in opened(main) if r.get("rule") == rule]
    what = f"standing: {rule}" + (f" {text}" if text else "") + f' ("{words.strip()[:120]}")'
    rec = records_kinds.add(main, TYPE, "-", what, by=USER, now=now, rule=rule, value=text or None, words=words.strip())
    for rid in older:
        role_records.close(main, ROLE, rid, "user", f"replaced by {rec['id']}", USER, now)
    return rec


def revoke(main: str, rid: str, words: str, now: dt.datetime | None = None) -> bool:
    """End the open standing order `rid` on the user's `words`; False when it is not an open standing order."""
    if not words.strip():
        raise ValueError(NOT_USER)
    if rid not in {r["id"] for r in opened(main)}:
        return False
    return role_records.close(main, ROLE, rid, "user", f"revoked: {words.strip()[:200]}", USER, now)


def revoke_rule(main: str, rule: str, words: str, now: dt.datetime | None = None) -> bool:
    """End the open order of `rule` (`unhold`); False when none is open."""
    rec = of(main, rule)
    return bool(rec) and revoke(main, rec["id"], words, now)


def show(rec: dict) -> str:
    return f"{rec['id']} {rec['rule']}{' ' + rec['value'] if rec.get('value') else ''}: the user's words \"{rec.get('words', '')}\""


def add_parser(sub) -> None:
    st = sub.add_parser("standing")
    verbs = st.add_subparsers(dest="verb", required=True)
    for name in ("add", "revoke", "list"):
        v = verbs.add_parser(name)
        v.add_argument("--repo", default=argparse.SUPPRESS)
        if name != "list":
            v.add_argument("--by", default="", help="who: only `user` (the user's own or relayed words)")
            v.add_argument("--words", default="", help="the user's own words")
    verbs.choices["add"].add_argument("rule", choices=tuple(RULES))
    verbs.choices["add"].add_argument("--value", default=None)
    verbs.choices["revoke"].add_argument("id")
    verbs.choices["list"].add_argument("--json", action="store_true")


def main(args) -> int:
    top = mtm_scan.main_checkout(args.repo)
    if args.verb == "list":
        rows = opened(top)
        print(json.dumps(rows, indent=1) if args.json else "\n".join(show(r) for r in rows) or "no standing order is open")
        return 0
    if why := refusal(args.by, args.words):
        print(why)
        return 1
    try:
        if args.verb == "add":
            print("standing order " + show(add(top, args.rule, args.value, args.words)))
            return 0
        done = revoke(top, args.id, args.words)
    except ValueError as e:
        print(str(e))
        return 1
    print(f"{args.id} revoked" if done else f"{args.id} is not an open standing order")
    return 0 if done else 1
