#!/usr/bin/env python3
"""`tollman.py state [--json]` (hal2 plan 0611 step 6, design.md §4, D6): what is true now, read by code, never from
a handoff or from memory: the train and its cars (train_cars.py, plan 0610), the hitched wagons with where each
stands, the open fix orders, the open records with what closes each, the standing orders. Nothing is written.

  {schema: 1, at, train, cars, hitched, held: {why, at, by, words, record} | null,
   orders: [{id, field, branch, jobs, post, early, record}], records: [{id, type, slot, what, at, by, waits_for}],  # names-ok: the record key
   standing: [{id, rule, value, words, at}]}                                 (schemas/state.schema.json)

`act` prints `text` before the handoff's DO FIRST on every wake and after a clear (Wiring.state, role_cli.run_wake).
`records` are the open ones but the standing orders, which `standing` lists. `orders` are the standing train's open
fix orders and the post-merge ones it carries (`post`); `record` names the `fix-order` record that waits for each.
"""

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import hold
import mtm_scan
import records_kinds
import role_records
import roletime
import standing
import train_cars
import train_fold
import train_state

SCHEMA = 1
ROLE = records_kinds.ROLE


def _orders(main: str, records: list[dict]) -> list[dict]:
    train = train_fold.standing(train_state.lines(main))
    if not train:
        return []
    by_order = {r.get("order"): r["id"] for r in records if r["type"] == "fix-order"}
    return [{"id": o["id"], "field": o.get("field") or "", "branch": o.get("branch") or "", "jobs": o.get("jobs") or [],
             "post": "post" in o, "early": bool(o.get("early")), "record": by_order.get(o["id"])}
            for o in (*train["orders"], *train["post"])]


def of(repo: str) -> dict:
    """The state as data (the module doc)."""
    main = mtm_scan.main_checkout(repo)
    cars = train_cars.of(repo)
    store = mtm_scan.state_dir(main, ROLE) / role_records.FILE
    open_ = role_records.open_(main, ROLE) if store.exists() else []
    kinds = role_records.KINDS[ROLE]
    held = hold.of(main)
    return {"schema": SCHEMA, "at": roletime.now(), "train": cars["train"], "cars": cars["cars"],
            "hitched": cars["hitched"],
            "held": {k: held.get(k) for k in ("why", "at", "by", "words", "record")} if held else None,
            "orders": _orders(main, open_),
            "records": [{"id": r["id"], "type": r["type"], "slot": r["slot"], "what": r["what"], "at": r["at"],
                         "by": r["by"], "waits_for": kinds[r["type"]].closer if r["type"] in kinds else "?"}
                        for r in open_ if r["type"] != standing.TYPE],
            "standing": [{"id": r["id"], "rule": r.get("rule") or "", "value": r.get("value") or "",
                          "words": r.get("words") or "", "at": r["at"]} for r in standing.opened(main)]}


def show(d: dict) -> str:
    """The state as text, a line per fact."""
    t = d["train"]
    out = [f"train {t['train']} ({t['state']}{', pushed' if t['pushed'] else ', open' if t['open'] else ''}), carrier "
           f"{t['carrier']} at {(t['head'] or '?')[:12]}" if t else "no train stands"]
    if d["held"]:
        out.append(f"HELD {d['held']['record'] or ''}: {d['held']['why'] or d['held']['words'] or 'no reason given'}")
    if d["cars"]:
        out.append("cars: " + ", ".join(c["field"] + ("" if c["in_branch"] else "*") for c in d["cars"])
                   + " (* not in the train's branch yet)")
    out += [f"hitched {h['field']} ({h['head'][:12]}): {h['where']}: {h['why']}" for h in d["hitched"]]
    out += [f"fix order {o['id']} ({o['field']}{', post-merge' if o['post'] else ''}): {','.join(o['jobs']) or '-'}"
            + (f" [{o['record']}]" if o["record"] else "") for o in d["orders"]]
    out += [f"{r['id']} {r['type']} {r['slot']}: {r['what']} (waits for {r['waits_for']})" for r in d["records"]]
    out += [f"standing {s['id']} {s['rule']}{' ' + s['value'] if s['value'] else ''}: \"{s['words']}\""
            for s in d["standing"]]
    if not (d["records"] or d["standing"] or d["orders"]):
        out.append("no open records, no standing orders")
    return "tollman state:\n" + "\n".join(f"  {line}" for line in out)


def text(repo: str) -> str:
    return show(of(repo))
