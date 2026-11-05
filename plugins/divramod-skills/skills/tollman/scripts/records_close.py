"""The closers of the tollman's records (hal2 plan 0611 step 4, design.md §2, D4, D8): one function per kind, each
`(record, facts) -> evidence | None`, reading code facts only. A record closes when its closer returns evidence
(role_records.sweep writes the close); never by a file's age, a handoff's mtime or the model's word. The only other
close is a relayed `--by user` (D4).

  fix_order   a `fixed` line with the order's id and, after it, a `landed` line of the train it rode (the `fixed`
              line's train; the tollman's own fix has none: the next train that lands); `redundant`: the `fixed` alone
  user_order  unhitch: the queue holds no `ready` head of the field and, for a car, an `unhitched` line by the user;
              breakup: a `cleared` line of that train
  hand_merge  `tollman.py cars --json` (train_cars.of): the field's car of that train `in_branch`, or a `landed`
              line of that train whose cars hold the field
  restart     `of: session`: a live session in the field (live_sessions), seen since the record; `of: train`: a
              `started` line of that train after its `retry`
  question    the ask's ack `done` or `refused` (acks.instructions); its recorded `ack-void` closes it `how: void`

`facts` is filled lazily, once per sweep: `train` (train.jsonl), `queue` (the tickets, None when unreadable),
`cars`, `agents` (None when unreadable), `log` (the tollman's log). A source that cannot be read leaves the record
open. `run` is the sweep and the prune of `tollman.py tick`'s round.
"""

import datetime as dt

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import mtm_scan
import role_records
import roletime
import train_state

ROLE = train_state.ROLE
SINCE_SLACK = dt.timedelta(seconds=60)  # a session's `since` this much before the record still counts (clocks)


def fact(facts: dict, key: str, read):
    """`facts[key]`, read by `read(main)` the first time a closer asks for it."""
    if key not in facts:
        facts[key] = read(facts["main"])
    return facts[key]


def _queue(main: str):
    doc = mtm_scan.run_json(mtm_scan.QUEUE, main)
    return doc.get("queue", []) if isinstance(doc, dict) else None


def _cars(main: str) -> dict:
    import train_cars
    return train_cars.of(main)


def _agents(main: str):
    import live_sessions
    return live_sessions.read()


def _log(main: str) -> list[dict]:
    return mtm_scan.entries(mtm_scan.state_dir(main, ROLE) / "log.jsonl")


def rows(facts: dict) -> list[dict]:
    return fact(facts, "train", train_state.lines)


def first(lines: list[dict], start: int, test) -> tuple[int, dict | None]:
    """The first line from index `start` on that passes `test`, with its index; (-1, None) when none does."""
    return next(((i, e) for i, e in enumerate(lines) if i >= start and test(e)), (-1, None))


def fix_order(rec: dict, facts: dict) -> str | None:
    lines, oid = rows(facts), rec.get("order")
    opened = max([i for i, e in enumerate(lines) if e["kind"] == "order" and e.get("id") == oid
                  and not e.get("also")] or [0])
    i, done = first(lines, opened, lambda e: e["kind"] == "fixed" and e.get("id") == oid)
    if done is None:
        return None
    sha = str(done.get("sha") or "")[:12]
    if done.get("redundant"):
        return f"fixed line of {oid} at {done.get('at')}: redundant, its fix in the train already ({sha})"
    name = done.get("train")
    _, landed = first(lines, i + 1, lambda e: e["kind"] == "landed" and (name is None or e.get("train") == name))
    if landed is None:
        return None
    return f"fixed {oid} ({sha}) at {done.get('at')}; train {landed.get('train')} landed at {landed.get('at')} " \
           f"(run {landed.get('run') or '?'})"


def user_order(rec: dict, facts: dict) -> str | None:
    name, field = rec.get("train"), rec["slot"]
    if rec.get("order") == "breakup":
        _, gone = first(rows(facts), 0, lambda e: e["kind"] == "cleared" and e.get("train") == name and name)
        return f"train {name} cleared at {gone.get('at')}" if gone else None
    tickets = fact(facts, "queue", _queue)
    if tickets is None or any(t.get("slot") == field and (t.get("ready") or {}).get("head") for t in tickets):
        return None
    said = f"the queue holds no ready mark of {field}"
    if not name:
        return said
    _, out = first(rows(facts), 0, lambda e: e["kind"] == "unhitched" and e.get("slot") == field
                   and e.get("train") == name and e.get("by") == "user")
    return f"{said}; unhitched from train {name} by the user at {out.get('at')}" if out else None


def hand_merge(rec: dict, facts: dict) -> str | None:
    name, field = rec.get("train"), rec["slot"]
    _, landed = first(rows(facts), 0, lambda e: e["kind"] == "landed" and e.get("train") == name
                      and field in (e.get("cars") or []))
    if landed:
        return f"train {name} landed at {landed.get('at')} with {field}"
    cars = fact(facts, "cars", _cars)
    if ((cars or {}).get("train") or {}).get("train") != name:
        return None
    car = next((c for c in cars.get("cars", []) if c.get("field") == field and c.get("in_branch")), None)
    return f"{field} ({str(car['head'])[:12]}) is in the branch of train {name}" if car else None


def restart(rec: dict, facts: dict) -> str | None:
    return _train_restart(rec, facts) if rec.get("of") == "train" else _session_restart(rec, facts)


def _train_restart(rec: dict, facts: dict) -> str | None:
    lines, name, at = rows(facts), rec.get("train"), roletime.parse(rec.get("at"))
    retries = [i for i, e in enumerate(lines) if e["kind"] == "retry" and e.get("train") == name
               and at and (roletime.parse(e.get("at")) or at) <= at]
    if retries:
        _, began = first(lines, retries[-1] + 1, lambda e: e["kind"] == "started" and e.get("train") == name)
    else:  # its retry line is gone (an archived log): a start at or after the record
        _, began = first(lines, 0, lambda e: e["kind"] == "started" and e.get("train") == name and at
                         and (roletime.parse(e.get("at")) or at) >= at)
    return f"train {name} started again at {began.get('at')} (pid {began.get('pid')})" if began else None


def _session_restart(rec: dict, facts: dict) -> str | None:
    import foreman_wake
    import live_sessions
    agents = fact(facts, "agents", _agents)
    if agents is None:
        return None
    a = live_sessions.live_session(agents, str(foreman_wake.field_path(facts["main"], rec["slot"])))
    at = roletime.parse(rec.get("at"))
    if not a or a.get("state") == live_sessions.UNKNOWN:
        return None
    since = a.get("since")
    if since and at and dt.datetime.fromtimestamp(since / 1000, dt.timezone.utc) < at - SINCE_SLACK:
        return None  # a session older than the restart: not the one it started
    who = a.get("pane_id") or a.get("session_id") or "?"
    return f"a live session ({who}, {a.get('state')}) in field {rec['slot']}"


def question(rec: dict, facts: dict):
    import acks
    ask = acks.instructions(fact(facts, "log", _log)).get(rec.get("ack"))
    if not ask:
        return None
    answer = next((a for a in ask["acks"] if a["status"] in ("done", "refused")), None)
    if answer:
        return f"ack {rec['ack']} {answer['status']} at {roletime.stamp(answer['at'])}"
    if ask["void"]:
        return "void", f"ack {rec['ack']} closed void at {roletime.stamp(ask['void'])} (no ack in 24 h)"
    return None


def run(main: str, now: dt.datetime | None = None, facts: dict | None = None) -> list[str]:
    """The round's sweep (`tollman.py tick`): every open record whose closer sees it done closed, then the prune of
    the records closed over 30 days ago. One line per close (or failed closer)."""
    out = role_records.sweep(main, ROLE, now, facts)
    role_records.prune(main, ROLE, now)
    return out
