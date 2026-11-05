"""Wake the foreman (hal2 plan 0522 D21; the user, 2026-10-31: "When he forms a train and there are sessions he needs
work from from the foreman, then he needs to start the sessions, right?"): an order the train sends a car's foreman
(a fix order, orders.py; a resolve order, resolve.py) never goes into a field without a session.

- `gate(actions, ctx)`: every `send` of kind `fix-order` or `resolve-order`, before tick.fresh, on both paths
  (`orders_cli.deliver`: `tollman.py order`, the early orders; `trains.handler`: the round's resolve orders):
  - a field with a live session (live_sessions.live_session on the round's agents list; an unreadable list counts as
    one, fail closed: never a start) gets the order as before;
  - a paused field (field_pause, record paused-fields-never-woken) is never started: one note for the farmer on the
    board (a `record` of kind NOTE, board.NOTES), who relays the user's go; a resolve order is resolved in the train
    by the tollman's own hand meanwhile (one wake, D21's only fallback); a fix order waits held;
  - no session: one start per field and order (key `foreman-start:<the order's key>`, never a second), the start
    guard of orphan_start.py around `hal2-cli-git worktree run <NN> --agent claude --detach` (the field's last
    conversation resumed), run as `foreman_wake.py start`, which writes the train's `woke` line; the order waits
    until the session is listed resting, at most START_WAIT (or a failed start), then goes as before (no pane: a
    relay to the tollman's session).
- A fix order's message is planned once (orders.order), so one that waits is kept: a `record` of kind HELD with its
  text, keyed `order-held:<its key>`; `held(ctx, rows)` (trains.handler) plans it again while its order is open and
  its key was never sent or relayed. A resolve order is planned every round anyway (resolve.actions).
"""

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import live_sessions
import mtm_scan
import run_names
import train_state
from deliver import READY
from tick import act

ORDERS = ("fix-order", "resolve-order")
HELD, NOTE, SELF, START = "order-held", "foreman-paused", "resolve-self", "foreman-start"
START_WAIT = dt.timedelta(minutes=15)  # a resumed session is listed resting within a minute on a quiet Mac
DAY = dt.timedelta(days=1)
ID = re.compile(r"\b(?:fix|resolve) order (\S+) for field")
TEXT = {
    "start": "field {field} has no session: started it (`hal2-cli-git worktree run {field} --agent claude --detach`, "
             "its conversation resumed) for {id}; the order follows once it rests",
    "farmer": "tollman: field {field} is paused ({why}), and train {train} needs its foreman for {id}. Resume it on the "
              "user's go; the tollman then sends the order.{own}",
    "own": " Meanwhile the tollman resolves the conflict in the train itself (plan 0522 D21).",
    "self": "resolve order {id}: field {field} is paused ({why}), so its foreman is never started (plan 0522 D21): "
            "resolve it in the train yourself, a hand of yours on `{branch}` as the order says (below), push, then "
            "`tollman.py resolved {field} <sha>`. The farmer is told.\n{order}",
}


def order_id(text: str) -> str:
    m = ID.search(text or "")
    return m.group(1) if m else "an order"


def at(e: dict) -> dt.datetime:
    return dt.datetime.fromisoformat(e["at"])


def last(log: list[dict], key: str) -> dict | None:
    return next((e for e in reversed(log) if e.get("key") == key), None)


def field_path(main: str, field: str) -> Path:
    """The field's folder: a sibling of the role's own (roles.slot_dir), `~/.hal/git/worktree/<repo>/<NN>`."""
    return mtm_scan.roles.slot_dir(main).parent / field


def start_act(a: dict, main: str) -> dict:
    field, oid = a["slot"], order_id(a["text"])
    argv = [sys.executable, str(Path(__file__).resolve()), "start", "--path", str(field_path(main, field)),
            "--slot", field, "--main", main, "--order", oid, "--need", a["kind"], "--",
            "hal2-cli-git", "worktree", "run", field, "--agent", "claude", "--detach"]
    return act("trains", START, "run", field, key=f"{START}:{a['key']}", argv=argv,
               text=TEXT["start"].format(field=field, id=oid))


def hold(a: dict) -> list[dict]:
    """A fix order that waits, kept for `held`; a resolve order needs none."""
    return [act("trains", HELD, "record", a["slot"], key=f"{HELD}:{a['key']}", text=a["text"])] \
        if a["kind"] == "fix-order" else []


def paused(a: dict, ctx: dict, pause: dict) -> list[dict]:
    """The paused field's order: never a start; the farmer's note, and the train's own resolve or the held fix."""
    field, key, oid = a["slot"], a["key"], order_id(a["text"])
    why = f"by {pause.get('by') or '?'}: {pause.get('why') or 'no reason given'}"
    train = (train_state.standing(train_state.lines(ctx["main"])) or {}).get("train") or "?"
    resolve = a["kind"] == "resolve-order"
    note = act("trains", NOTE, "record", mtm_scan.roles.slot_name(ctx["main"]), key=f"{NOTE}:{key}",
               text=TEXT["farmer"].format(field=field, why=why, train=train, id=oid, own=TEXT["own"] * resolve))
    if not resolve:
        return [note] + hold(a)
    standing = train_state.standing(train_state.lines(ctx["main"])) or {}
    branch = ((standing.get("resolve") or {}).get("branch") if standing.get("state") == "resolving" else None) or \
        run_names.fix_branch(standing, field, "resolve")  # the order's own systematic name (plan 0610 D18)
    return [note, act("trains", SELF, "wake", key=f"{SELF}:{key}", evidence={"order": a["text"]},
                      text=TEXT["self"].format(id=oid, field=field, why=why, branch=branch, order=a["text"]))]


def one(a: dict, ctx: dict, begun: set[str]) -> list[dict]:
    """What goes instead of the order `a` (see the module doc)."""
    field, log = a["slot"], ctx.get("log", [])
    if (pause := (ctx.get("paused_fields") or {}).get(field)) is not None:
        return paused(a, ctx, pause)
    session = live_sessions.live_session(ctx.get("agents"), str(field_path(ctx["main"], field)))
    started = last(log, f"{START}:{a['key']}")
    if started:
        failed = "(exit " in (started.get("note") or "")
        resting = bool(session) and session.get("state") in READY
        return [a] if failed or resting or ctx["now"] - at(started) >= START_WAIT else hold(a)
    if session:
        return [a]
    if field in begun:  # a second order this round: the first one's start serves it
        return hold(a)
    begun.add(field)
    return [start_act(a, ctx["main"])] + hold(a)


def gate(actions: list[dict], ctx: dict) -> list[dict]:
    """The actions with every order to a car's foreman checked for its session (see the module doc)."""
    out, begun = [], set()
    for a in actions:
        orders = a.get("do") == "send" and a.get("kind") in ORDERS and a.get("slot") not in ("", "-", "main")
        out += one(a, ctx, begun) if orders and a.get("key") else [a]
    return out


def held(ctx: dict, rows: list[dict]) -> list[dict]:
    """The held fix orders' messages planned again: their order open, their key never sent or relayed, within a day."""
    log, now = ctx.get("log", []), ctx["now"]
    done = {e.get("key") for e in log if e.get("do") in ("send", "relay")}
    train = train_state.standing(rows) or {}
    open_ = {o.get("id") for o in train.get("orders", []) + train.get("post", [])}
    out, seen = [], set()
    for e in log:
        key = e.get("key") or ""
        if e.get("kind") != HELD or not key.startswith(HELD + ":") or now - at(e) > DAY:
            continue
        okey = key[len(HELD) + 1:]
        if okey in done or okey in seen or order_id(e.get("what", "")) not in open_:
            continue
        seen.add(okey)
        out.append(act("trains", "fix-order", "send", e["slot"], pane=ctx.get("panes", {}).get(e["slot"]), key=okey,
                       text=e["what"]))
    return out


def start(argv: list[str] | None = None, guard=None) -> int:
    """`foreman_wake.py start ... -- <the start's argv>`: orphan_start.py's guard and start, then the `woke` line."""
    p = argparse.ArgumentParser(prog="foreman_wake.py start")
    for name in ("--path", "--slot", "--main", "--order", "--need"):
        p.add_argument(name, required=True)
    p.add_argument("run", nargs=argparse.REMAINDER)
    args = p.parse_args(argv)
    if guard is None:
        import orphan_start
        guard = orphan_start.main
    run = args.run[1:] if args.run[:1] == ["--"] else args.run
    code = guard(["--path", args.path, "--slot", args.slot, "--main", args.main, "--role", train_state.ROLE, "--",
                  *run])
    if code == 0:
        train = train_state.standing(train_state.lines(args.main)) or {}
        train_state.append(args.main, "woke", args.slot, train=train.get("train"), field=args.slot, id=args.order,
                           why=f"{args.need}: no session in {args.slot}, started")
    return code


def restart(repo: str, field: str, why: str, guard=None, now=None) -> tuple[int, str]:
    """`tollman.py restart <field> --why <text>` (hal2 plan 0611): the field's session started as an order's start is
    (the orphan guard around `hal2-cli-git worktree run <NN> --agent claude --detach`), a `woke` line and a `restart`
    record, open until a live session is seen there; a paused field is never started (paused-fields-never-woken)."""
    import field_pause
    import records_kinds
    main = mtm_scan.main_checkout(repo)
    if pause := field_pause.load(main).get(field):
        why = pause.get("why") or "no reason given"
        return 1, f"field {field} is paused ({why}): never started; the farmer resumes it"
    if guard is None:
        import orphan_start
        guard = orphan_start.main
    code = guard(["--path", str(field_path(main, field)), "--slot", field, "--main", main, "--role", train_state.ROLE,
                  "--", "hal2-cli-git", "worktree", "run", field, "--agent", "claude", "--detach"])
    if code:
        return code, f"field {field} not started (exit {code}): the guard's line says why"
    train = (train_state.standing(train_state.lines(main)) or {}).get("train")
    train_state.append(main, "woke", field, now, train=train, field=field, id=f"restart-{field}", why=f"restart: {why}")
    r = records_kinds.add(main, "restart", field, f"field {field} restarted: {why}", now=now, of="session",
                          event=records_kinds.train_event("woke", field=field, id=f"restart-{field}"), train=train)
    return 0, f"field {field} started ({r['id']}): {why}"


def add_parser(sub) -> None:
    r = sub.add_parser("restart")
    r.add_argument("field")
    r.add_argument("--why", required=True)


if __name__ == "__main__":
    if sys.argv[1:2] != ["start"]:
        sys.exit("usage: foreman_wake.py start --path <dir> --slot <NN> --main <yard> --order <id> --need <kind> "
                 "-- <argv>")
    sys.exit(start(sys.argv[2:]))
