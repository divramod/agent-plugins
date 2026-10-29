"""A paused field is never started, continued or woken by a tick (hal2 plan 0458, D2, D3, D7).

hal2 keeps the pause (`hal2-cli-git worktree pause|resume|paused`); this module only asks it, through the CLI and never
the file (D2): `load(main)` is `{field: {"by", "why", "since"}}` from `worktree paused --json` (schema 1, `fields` a
list of `{field, by, why, since}`). An old CLI without the command, or an answer that cannot be read, is "nothing paused"
(said once on stderr): the CLIs' own guards (`worktree run`, `hal2-cli-agents send`) stay the choke point (D3).

The frame uses it twice: `skip` when it plans a round (the due duties' acts) and `tick.execute` when it carries one out
(acts that never went through the planner: minute.py's, chain.py's, orders_cli.py's). What a pause drops is any act that
starts, continues or wakes the field's session: `send`, `relay`, `wake`, and a `run` whose argv starts a session
(`starts_session`). The tollman's landing and train runs, a `notify` for the user and the records stay (D7): a paused
field in the merge queue still lands. A dropped act becomes a keyed `record` (one log line a day per field, duty and kind),
so the journal says why a field with a plan and a handoff sits, and the acts that follow it (`after`) go with it.
"""

import sys

import mtm_scan

CMD = ["hal2-cli-git", "worktree", "paused", "--json"]
DAY = 24 * 3600
TALKS = ("send", "relay", "wake")  # an act that types into, messages or wakes a field's session
SESSION_RUNS = (("worktree", "run"), ("hal2-cli-agents", "send"), ("hal2-cli-agents", "restart"))
_said = False


def load(main: str) -> dict[str, dict]:
    """The paused fields of `main`'s repository: {field: {by, why, since}}; {} when hal2 cannot say."""
    global _said
    doc = mtm_scan.run_json(CMD, main)
    rows = doc.get("fields") if isinstance(doc, dict) else None
    if not isinstance(rows, list):
        if not _said:
            _said = True
            print("field_pause: `hal2-cli-git worktree paused --json` gave no answer (an older CLI?): "
                  "no field counts as paused", file=sys.stderr)
        return {}
    return {str(r["field"]): {k: r.get(k, "") for k in ("by", "why", "since")}
            for r in rows if isinstance(r, dict) and r.get("field")}


def of(holder: dict, main: str) -> dict[str, dict]:
    """`load`, asked once per round: kept in the round's dict (`out["paused_fields"]`)."""
    if "paused_fields" not in holder:
        holder["paused_fields"] = load(main)
    return holder["paused_fields"]


def _has(argv: list[str], pair: tuple[str, ...]) -> bool:
    return any(tuple(argv[i:i + len(pair)]) == pair for i in range(len(argv)))


def starts_session(a: dict) -> bool:
    """Does the act start, continue or wake a session (what a pause drops)? A `run` does when its argv is a start, a
    typed message or a clear-and-continue; the landing's and the trains' runs, records and notices never do."""
    if a["do"] in TALKS:
        return True
    if a["do"] != "run":
        return False
    argv = [str(x) for x in a.get("argv", [])]
    return (any(x.endswith("orphan_start.py") for x in argv) or "clear-and-continue" in argv
            or any(_has(argv, pair) for pair in SESSION_RUNS))


def reason(slot: str, pause: dict) -> str:
    return f"field {slot} paused by {pause.get('by') or '?'}: {pause.get('why') or 'no reason given'}"


def dropped(a: dict, pause: dict) -> dict:
    """The record that stands for a dropped act: one line a day per field, duty and kind (its key and window)."""
    slot = a["slot"]
    return {"duty": a["duty"], "kind": "paused-skip", "slot": slot, "do": "record",
            "key": f"paused-skip:{slot}:{a['duty']}:{a['kind']}", "window": DAY,
            "text": f"skipped {a['do']} {a['kind']}: {reason(slot, pause)}"}


def skip(actions: list[dict], paused: dict[str, dict]) -> list[dict]:
    """The planned acts with every starter act of a paused field turned into its record, and the acts `after` it gone."""
    if not paused:
        return actions
    out, gone = [], set()
    for a in actions:
        if a.get("after") and a["after"] in gone:
            continue
        pause = paused.get(a["slot"])
        if pause is not None and starts_session(a):
            if a.get("key"):
                gone.add(a["key"])
            out.append(dropped(a, pause))
        else:
            out.append(a)
    return out


def guard(a: dict, out: dict, main: str) -> bool:
    """`tick.execute`'s guard: turn a starter act of a paused field into its record (in place) and say whether it was
    one. The pause is asked only for an act that could start something, once per round."""
    if a["do"] == "record" or a["slot"] in ("", "-") or not (a["do"] in TALKS or a["do"] == "run"):
        return False
    gone = out.setdefault("paused_keys", set())
    if a.get("after") and a["after"] in gone:
        a.update(do="record", kind="paused-skip", text=f"skipped with the act it follows ({a['after']})")
        return True
    if not starts_session(a):
        return False
    pause = of(out, main).get(a["slot"])
    if pause is None:
        return False
    if a.get("key"):
        gone.add(a["key"])
    a.update(dropped(a, pause))
    return True
