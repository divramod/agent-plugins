"""The duty `wagons` (hal2 plan 0604 step 7, D11; L225): every 20 minutes the train's wagon table is printed into the
tick's output, by code, no model call (wagons.py does the work).

In the tick `handler` plans one `record` action whose text is the table: the round prints it and logs it. A dry run
plans a line and touches nothing (no fetch, no store write). A table that cannot be made is a record line saying why,
never a wake: it is information, the duty must not fail a round.
"""

import wagons

WINDOW = 600  # the key window: one table per tick, however often a retry asks


def table_text(top: str, dry: bool) -> str:
    if dry:
        return "wagon table (not made in a dry run)"
    try:
        return wagons.run(top)
    except Exception as exc:  # noqa: BLE001  (information only, a failing table never fails the round)
        return f"wagon table failed: {type(exc).__name__}: {exc}"


def handler(item: dict, ctx: dict) -> list[dict]:
    """duty:wagons: one record action with the table."""
    top = ctx.get("top") or ctx["main"]
    text = table_text(top, bool(ctx.get("dry")))
    now = ctx["now"].strftime("%Y-%m-%dT%H:%M")
    return [{"duty": "wagons", "kind": "wagons", "slot": "-", "do": "record", "key": f"wagons:{now}",
             "window": WINDOW, "text": text}]
