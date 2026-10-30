#!/usr/bin/env python3
"""The merge queue's two modes and the tollman's sleep flag in the tollman's round (hal2 plan 0360 step 25, D74 to
D76; plan 0365 D3, D5, D9; plan 0375 D4, D19). hal2-git keeps the mode (`queue --json`'s `mode: {mode, by, at, why}`, production when
missing; the farmer's queue_mode.of reads it); only the user switches it. Each hitched entry has an effective mode of
its own (`effective_mode`, else its own `mode`, else the queue's; an older hal2-cli-git without them reads as the
queue's): the tollman's trains take only entries whose effective mode is production, and in smuggle mode it sleeps
only while no hitched entry is production (it wakes for such an entry alone). The sleep flag `sleep.json`
(`hal2-cli-roles sleep tollman on`, `{by, at, why}` in `roles/tollman/` of the field `tollman-<repo>`, where
hal2-roles writes it, also when `$FARMER_DIR` moves the state folder) puts it to sleep in any mode.

1. Asleep (D75 2; 0365 D3, D9): while the flag stands, or in smuggle mode with no hitched entry in production,
   `trains.plan` returns `sleep`'s actions: one `asleep` record per round ("asleep: smuggle mode since <t> (by
   <who>)", or "asleep: flag since <t> (by <who>): <why>", the flag first; no key, so one tick.log line each round) and nothing new: no train formed or
   started again, no retry, no breakup, no wake. A train already landing is never cut: its pause and run are watched
   and a landing that lands settles as ever (KEEP); a landing that ends red or interrupted is left as it is, the
   train stays `landing` with its process gone, and the first round in production settles it (triage, wake, fix
   order) and its cars stay hitched. `busy` holds every ci-check back (the duty `checks`).
   Asleep on the flag (plan 0375, switch.py) the round also drops every standing train that is not landing (its
   cars keep their tickets, places and ready marks; a landing process that lives is never cut) and tells every
   hitched field once per sleep to land alone in its turn (`/merge-to-main`, which smuggles when its entry's mode is
   smuggle).
2. Awake again (D75 5, D76): the round notes the mode it saw (`seen-mode`, `mode.json` in the state folder;
   `asleep` while the flag stands). The first round in production after smuggle mode or the flag, before any train, finds the cars already in the barn (`git merge-base
   --is-ancestor <head> <default>`): a waiting hitch is cleared, a car of a formed train (not landing: formed, red,
   fixing, retry, split) leaves it (D76 amends D3 for this case only), a car of a running train (landing, paused) is
   only recorded; each a `barn` line of train.jsonl (`tollman.py barn`) and its foreman told once (`in-barn`); then
   the chain goes on in the same round. A formed train whose every car left is cleared.

  tollman.py seen-mode production|smuggle|asleep [--repo <dir>]              the mode this round saw
  tollman.py barn <field> --head <sha> --how hitch|formed|running [--train <name>] [--repo <dir>]
"""

import json
import sys
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import mtm_scan
import queue_mode
import roles
import train_state
import trial
from tick import act, default_ref

CLI = Path(__file__).with_name("tollman.py")
FILE = "mode.json"
SLEEP = "sleep.json"
ASLEEP = "asleep"  # what `seen` notes while the flag stands (plan 0375): the way back finds the barn too
VERBS = ("seen-mode", "barn", "sleep", "wake", "drop")  # + switch.VERBS (test_light_start pins it); switch imports engine, so a minute pass does not
QUEUE = queue_mode.QUEUE
RUNNING = ("landing", "paused")  # a car of such a train is only recorded; of every other standing train it leaves
KEEP = ("train-paused", "train-resumed", "train-run", "train-stuck", "landed", "in-the-barn", "stack-red",
        "stack-red-fix", "chain")  # what a landing train still does while asleep: watched, paused, landed
TEXT = {"in_barn": "tollman (wagon train): field {field}'s crop ({head}) is already in the barn (smuggled, or "
                   "landed alone while the tollman slept): {what}. Nothing of it is carried again: /merge-from-main and finish the plan as after \"in the barn\"."}
WHAT = {"hitch": "its hitch is cleared", "formed": "it left the formed train {train}",
        "running": "the running train {train} carries nothing new of it"}


def of(doc: dict | None) -> dict:
    return queue_mode.of(doc)


def flag_file(main: str) -> Path:
    """Where hal2-roles writes the flag: `roles/tollman/sleep.json` of the tollman's field `tollman-<repo>`
    (hal2_roles::role_field), never `$FARMER_DIR`'s state folder (plan 0365 review finding 8)."""
    return roles.slot_dir(main, train_state.ROLE) / "roles" / train_state.ROLE / SLEEP


def flag(main: str) -> dict | None:
    """The tollman's sleep flag (`sleep.json` of its field's role folder, plan 0365 D3): `{by, at, why}`, None while
    it is off. A flag file that cannot be read still puts the tollman to sleep (the flag stands, its fields unknown)."""
    f = flag_file(main)
    try:
        doc = json.loads(f.read_text())
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def production_waits(mode: dict | None, tickets) -> bool:
    """Whether a hitched entry waits whose effective mode is production (D9): the tollman wakes for it alone."""
    return any(queue_mode.hitched(t) and queue_mode.effective(t, mode or {}) == queue_mode.PRODUCTION
               for t in tickets or ())


def reason(mode: dict | None, tickets=(), sleep_flag: dict | None = None) -> str | None:
    """Why the round sleeps: `flag` (the sleep flag), `smuggle` (smuggle mode and no hitched entry in production),
    or None. The flag wins."""
    if sleep_flag is not None:
        return "flag"
    return "smuggle" if queue_mode.smuggle(mode or {}) and not production_waits(mode, tickets) else None


def asleep(mode: dict | None, tickets=(), sleep_flag: dict | None = None) -> bool:
    return reason(mode, tickets, sleep_flag) is not None


def since(mode: dict | None, sleep_flag: dict | None) -> str:
    """The asleep line's text: the flag's, else smuggle mode's."""
    if sleep_flag is not None:
        why = f": {sleep_flag['why']}" if sleep_flag.get("why") else ""
        return f"flag since {sleep_flag.get('at')} (by {sleep_flag.get('by')}){why}"
    return f"smuggle mode since {(mode or {}).get('at')} (by {(mode or {}).get('by')})"


def trainable(tickets: list[dict], mode: dict | None, own: str) -> list[dict]:
    """The queue the trains are drafted from: a hitched entry whose effective mode is smuggle is left out (it
    smuggles itself, D9); the tollman's own ticket stays whatever its mode."""
    return [t for t in tickets if t.get("slot") == own or not queue_mode.hitched(t)
            or queue_mode.effective(t, mode or {}) != queue_mode.SMUGGLE]


def busy(mode: dict | None, tickets=(), sleep_flag: dict | None = None) -> dict | None:
    """The duty `checks`' reason to hold every check back while the tollman sleeps, or None."""
    why = reason(mode, tickets, sleep_flag)
    return {"reason": f"{since(mode, sleep_flag)}: the tollman sleeps", "slot": ""} if why else None


def sleep(top: str, mode: dict, tickets: list[dict], train: dict | None, panes: dict, inner, alive,
          sleep_flag: dict | None = None) -> list[dict]:
    """trains.plan while asleep: the asleep line, and of a landing train what KEEP lets through (`inner()` is the
    production plan); on the flag every other standing train dropped and the hitched told to land alone (switch.py)."""
    line = act("trains", "asleep", "record", text=f"asleep: {since(mode, sleep_flag)}")
    if sleep_flag is not None:
        import switch as switch_
        return switch_.plan(top, line, sleep_flag, mode, tickets, train, panes, inner, KEEP, alive)
    going = [a for a in inner() if a["kind"] in KEEP] if train and train["state"] in RUNNING else []
    return [line] + going


def seen(main: str) -> str:
    """The mode the last round saw (production when never noted)."""
    f = mtm_scan.state_dir(main, train_state.ROLE) / FILE
    try:
        return json.loads(f.read_text()).get("mode") or queue_mode.PRODUCTION
    except (OSError, ValueError, AttributeError):
        return queue_mode.PRODUCTION


def cli(top: str, kind: str, key: str, text: str, *args: str, **kw) -> dict:
    argv = [sys.executable, str(CLI), *args, "--repo", top]
    stuck = act("trains", "train-stuck", "wake", key=f"stuck:{key}", text=f"{text}: failed, run `{' '.join(argv[1:])}`")
    return act("trains", kind, "run", kw.pop("slot", "-"), key=key, argv=argv, text=text, on_fail=[stuck], **kw)


def in_barn(main: str, default: str, tickets: list[dict], train: dict | None, own: str) -> list[dict]:
    """The cars and hitches whose head is in `default` already: [{field, head, how, train}]."""
    def landed(head: str) -> bool:
        return bool(head) and trial.git(main, "merge-base", "--is-ancestor", head, default)[0] == 0
    how = "running" if train and train["state"] in RUNNING else "formed"
    found = [{"field": c["field"], "head": c["head"], "how": how, "train": train["train"]}
             for c in (train or {}).get("cars", []) if c["field"] not in train.get("in_barn", []) and landed(c["head"])]
    riding = {c["field"] for c in (train or {}).get("cars", [])} | {own}
    return found + [{"field": t["slot"], "head": t["ready"]["head"], "how": "hitch", "train": None} for t in tickets
                    if t.get("ready") and t.get("slot") not in riding and not t.get("rides_with")
                    and t.get("state", "waiting") == "waiting" and landed(t["ready"].get("head"))]


def turn(top: str, main: str, mode: dict, tickets: list[dict], rows: list[dict], panes: dict,
         sleep_flag: dict | None = None) -> tuple[list, bool]:
    """(the actions, whether the round ends with them): the mode noted when it changed (`asleep` while the flag
    stands); the first production round after smuggle mode or the flag drops the cars in the barn first and goes on
    through the chain. After smuggle mode the flag notes nothing: the first awake round still finds the barn."""
    now, last = ASLEEP if sleep_flag is not None else mode.get("mode") or queue_mode.PRODUCTION, seen(main)
    if sleep_flag is not None and last == queue_mode.SMUGGLE:
        return [], False
    at = (sleep_flag or {}).get("at") if now == ASLEEP else mode.get("at")
    note = [cli(top, "seen-mode", f"seen-mode:{now}:{at}", f"the queue's mode is {now}" if now != ASLEEP else
                "the tollman is asleep (its flag)", "seen-mode", now)] if now != last else []
    if last == queue_mode.PRODUCTION or now != queue_mode.PRODUCTION:
        return note, False
    found = in_barn(main, default_ref(main), tickets, train_state.standing(rows), Path(top).name)
    if not found:
        return note, False
    out = []
    for c in found:
        key, what = f"barn:{c['field']}:{c['head'][:12]}", WHAT[c["how"]].format(train=c["train"])
        out.append(cli(top, "barn", key, f"{c['field']} is in the barn already: {what}", "barn", c["field"], "--head",
                       c["head"], "--how", c["how"], *(["--train", c["train"]] if c["train"] else []), slot=c["field"]))
        out.append(act("trains", "in-barn", "send", c["field"], pane=panes.get(c["field"]), key=f"told:{key}",
                       after=key, text=TEXT["in_barn"].format(field=c["field"], head=c["head"][:12], what=what)))
    import chain
    return out + note + [chain.action(top, out[-2]["key"])], True


def barn(repo: str, field: str, head: str, how: str, name: str | None) -> tuple[int, str]:
    """The verb: the `barn` line; a hitch or a formed train's car loses its ready mark; a formed train left without
    a car is cleared."""
    import engine
    main = mtm_scan.main_checkout(repo)
    train_state.append(main, "barn", field, train=name, head=head, how=how)
    said = f"{field} is in the barn already ({how})"
    if how in ("hitch", "formed"):
        code, text = engine.cli(["worktree", "queue", "ready", field, "--clear", "--json"], main)
        said += "; hitch cleared" if not code else f"; its mark stays: {text[-200:]}"
    train = train_state.standing(train_state.lines(main))
    if how == "formed" and train and not train["cars"] and not train.get("yard"):
        code, text = engine.clear(repo, "every car is in the barn already (smuggled or landed alone)")
        return code, f"{said}; {text}"
    return 0, said


def add_parser(sub) -> None:
    import switch as switch_
    sub.add_parser("seen-mode").add_argument("mode", choices=(queue_mode.PRODUCTION, queue_mode.SMUGGLE, ASLEEP))
    switch_.add_parser(sub)
    b = sub.add_parser("barn")
    b.add_argument("field")
    b.add_argument("--head", required=True)
    b.add_argument("--how", required=True, choices=tuple(WHAT))
    b.add_argument("--train")


def main(args) -> int:
    import switch as switch_
    if args.cmd in switch_.VERBS:
        return switch_.main(args)
    if args.cmd == "seen-mode":
        main_dir = mtm_scan.main_checkout(args.repo)
        f = mtm_scan.state_dir(main_dir, train_state.ROLE) / FILE
        f.write_text(json.dumps({"mode": args.mode, "at": train_state.utc()}) + "\n")
        print(f"the queue's mode seen: {args.mode}")
        return 0
    code, text = barn(args.repo, args.field, args.head, args.how, args.train)
    print(text, file=sys.stderr if code else sys.stdout)
    return code
