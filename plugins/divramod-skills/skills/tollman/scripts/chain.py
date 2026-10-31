"""One call goes on to the next train (hal2 plan 0333 step 6, cause C of its analysis.md): the duty `trains` again,
right now, link after link, instead of a round per change of a train. Before it, an unhitch after red waited for
the next round's breakup (12:53:36 unhitched, 12:57:10 broken up) and a landed train's next one for the round after
(14:07:11 landed, 14:12:34 formed).

A link is one plan of the duty (`trains.handler` on the frame's context, read fresh), what `tick.fresh` lets
through, done by the frame's `tick.execute` (each action in the role's log, as a tick's), and one `chain` record of
the link in the log. The chain goes on only while a link ran `landed` or `breakup` and started no landing; it stops
at a wait: nothing to do (nothing ready, a held place, a train that stands), a landing started (`form`,
`restart`), a run that failed (its `on_fail` woke the session); and after MAX_LINKS links, where the next round goes
on. Its wakes, relays and notices go to wake.json as a round's do (`wake.hand_over`).
Only after its links, the next train formed, the worktrees of the trains before are dropped, detached (train_wt.later,
L135: a landed train's `git worktree remove` inside the round held the next train back 6+ min).

Who calls it: the user's `tollman.py unhitch --by-user` of a red train's car (plan 0360 D3; breakup, the split
tells and the next form in the same call) and the round that finds a train landed (`trains.settle`'s `chain` action after `landed`:
`tollman.py chain --in-tick`).
"""

import datetime as dt
import fcntl
import sys
from contextlib import contextmanager
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import mtm_scan
import role_cli
import tick
import train_wt
import wake

MAX_LINKS = 3
GOES_ON = ("landed", "breakup")  # a link that changed the train state this way: the next plan may form a train
STARTS = ("form", "restart")  # a landing started: the chain waits for it
CLI = Path(__file__).with_name("tollman.py")
ITEM = {"name": "duty:trains"}


def action(top: str, after: str) -> dict:
    """The round's `chain` run after a change the next train waits for (`after`: its key); a failed one wakes."""
    argv = [sys.executable, str(CLI), "chain", "--in-tick", "--repo", top]
    stuck = tick.act("trains", "train-stuck", "wake", key=f"stuck:chain:{after}",
                     text=f"the trains chain after `{after}` failed: run `{' '.join(argv[1:4])}` to see why, then "
                          "`tollman.py train --dry-run`.")
    return tick.act("trains", "chain", "run", key=f"chain:{after}", after=after, argv=argv, on_fail=[stuck],
                    text="the next train in the same round")


def failed(a: dict) -> bool:
    return a["do"] == "run" and bool(a.get("exit")) and a["exit"] != tick.OFFLINE


def link(top: str, main: str, wiring, handler, out: dict, now: dt.datetime | None) -> list[dict]:
    """One plan of the duty, done: the actions it ran (none: nothing to do)."""
    ctx = tick.context(top, main, {ITEM["name"]: None}, now or dt.datetime.now(), False, wiring)
    actions = tick.fresh(handler(ITEM, ctx), ctx["log"], ctx["now"], wiring.role)
    for a in actions:
        tick.execute(a, top, main, out, wiring)
    return actions


def stop(done: list[dict]) -> str | None:
    """Why the chain stops after a link that did `done`, or None: it goes on."""
    if not done:
        return "nothing to do"
    if bad := [a["kind"] for a in done if failed(a)]:
        return "failed: " + ", ".join(bad)
    ran = {a["kind"] for a in done if a["do"] == "run"}
    if ran & set(STARTS):
        return "a landing started"
    return None if ran & set(GOES_ON) else "a wait"


def go(top: str, wiring, handler, links: int = MAX_LINKS, now: dt.datetime | None = None) -> dict:
    """The chain from the tollman's field `top`: {links: [[(kind, do, slot, exit)]], why, items}."""
    main, out, steps, why = mtm_scan.main_checkout(top), {}, [], f"{links} links: the next round goes on"
    for n in range(1, links + 1):
        done = link(top, main, wiring, handler, out, now)
        steps.append([(a["kind"], a["do"], a["slot"], a.get("exit")) for a in done])
        reason = stop(done)
        what = ", ".join(f"{a['kind']} {a['slot']}" + (f" (exit {a['exit']})" if a.get("exit") else "")
                         for a in done) or "nothing"
        tick.execute(tick.act("trains", "chain", "record", text=f"chain link {n}: {what}"
                              + (f"; stops: {reason}" if reason else "")), top, main, out, wiring)
        if reason:
            why = reason
            break
    items = sum(len(out.get(k, [])) for k in wake.KINDS)
    if items:
        wake.hand_over(top, main, out, now or dt.datetime.now(), wiring)
    return {"links": steps, "why": why, "items": items, "dropping": train_wt.later(top)}  # after the form (L135)


@contextmanager
def locked(repo: str, wiring):
    """The role's tick lock, without waiting: yields False when a tick runs (that tick or the next goes on)."""
    with (role_cli.state(repo, wiring) / "tick.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        yield True


def run(repo: str, wiring, handler, in_tick: bool = False) -> tuple[int, str]:
    """`tollman.py chain`: the chain from `repo`'s tollman field, as lines; only in timer mode (the tick's
    own rule) and behind the tick lock unless the tick that holds it calls (`in_tick`)."""
    top = str(mtm_scan.roles.slot_dir(mtm_scan.main_checkout(repo), wiring.role))
    if role_cli.mode(top, wiring) != "timer":
        return 0, "the trains chain runs only in timer mode: the next round goes on"
    if in_tick:
        return report(go(top, wiring, handler))
    with locked(top, wiring) as mine:
        return report(go(top, wiring, handler)) if mine else (0, "a tick runs: it or the next round goes on")


def report(r: dict) -> tuple[int, str]:
    """Exit 0 also after a failed link: its own run's `on_fail` woke the session already."""
    lines = [f"chain link {n}: " + (", ".join(f"{k} {s}" + (f" (exit {e})" if e else "") for k, _, s, e in steps)
                                    or "nothing") for n, steps in enumerate(r["links"], 1)]
    lines.append(f"chain stops: {r['why']}" + (f"; {r['items']} items for the session (act)" if r["items"] else ""))
    lines += [f"train worktrees {r['dropping']}"] if r.get("dropping") else []
    return 0, "\n".join(lines)
