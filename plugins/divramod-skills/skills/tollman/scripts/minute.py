#!/usr/bin/env python3
"""The duty `watch`, the tollman's 1-minute pass (hal2 plan 0383 step 4, D4): code only, a quiet minute prints nothing.

The existing timer ticks every minute (the role's `watch: "* * * * *"` makes the loop cron every minute,
Wiring.min_tick); the other duties keep their own crons. A tick on which only `watch` is due is a *minute pass* (`light`,
`run`), not a round: no merge from main, no role file edit, no message board, no summary. It

1. looks for a ticket that left the merge queue unmerged or was stopped (leavers.check, the same call as the round's,
   once per pass; a minute pass is no round, so no round's call runs beside it, and the actions carry keys, so none
   acts twice) and does what it plans: puts the ticket back, tells its foreman, notes it for the board;
2. reads the new events of the live land run (watch_events.new) and prints each as one line: a job failed (name and
   its first error line), the merge job (`d2-01-git-merge`) green, the workflow finished (conclusion).

3. on a fresh `job failed` of the watched run: triage, and before its merge job is green the early fix order to
   the one car it names, or the wake for an unclear culprit (early_order.py, plan 0383 step 5, D5); after it the
   post-merge order into the next train (post_merge.py, step 6, D6); the order's line prints too.
4. on the landing train's merge job told green (watch_events.merged), once its landing's process has ended (hal2-git
   ends a landing at its merge's green; a running landing is never stopped, the next minute looks again): the
   trains chain (`tollman.py chain --in-tick`, chain.py) settles it in the barn and forms the next train on the new
   main, whose landing's process pretests it at once and starts its land run only after this run has finished
   (next_train.py); keyed `chain:merge-green:<train>`, so it runs once (plan 0383 step 6, D6, L33). In smuggle mode
   none.

5. CI/CD health (ci_health.py, step 11, D12, D13): every runner of hal2-runners.toml checked each pass, a line only
   for a new problem (a queued job nobody serves, a pipeline host runner offline); a parked cloud machine with a
   queued job gets the supervisor's wake request at once.

A quiet pass imports only what it uses (plan 0480 D3): the orders, the chain, the wake and the trains module load when
a pass has something to do for them (test_light_start bounds it).

A tick on which other duties are due too is a round: `handler` plans the events as `record` actions and 3. and 4. as
the pass does (the round's trains duty has the leavers' call already, and its own early order: one key, one
action, early_order.once) and the round carries them out (silent_lines shows them).
"""

import datetime as dt
import fcntl

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import ci_health
import gh_runs
import leavers
import modes
import mtm_scan
import pass_timing
import role_cli
import tick
import train_state
import watch_events
from logstate import read_log
from tick import act, default_ref

ITEM = "duty:watch"
KIND = "watch"  # the duty name in the actions
PRINTED = ("early-order", "post-order", "chain", "runner")  # the trains' actions of a pass that print their line


def events(top: str, main: str, dry: bool, doc: dict | None = None, panes: dict | None = None) -> list[dict]:
    """The new events of the watched land run as `record` actions, one line each (the line is the action's text),
    after a `job failed` the early or post-merge order or the wake, and the next train on a green merge job (3., 4.).
    `doc`: the queue's (read when needed); `panes`: the sessions' (a post-merge red with no train standing is told)."""
    fresh = watch_events.new(main, train_state.lines(main), dry)
    return [act(KIND, e["kind"], "record", "-", key=e["key"], text=e["text"]) for e in fresh] + early(
        top, main, fresh, doc, panes) + next_train(top, main, doc) + ci_health.check(top, main, None, dry)


def awake(main: str, doc: dict | None) -> dict | None:
    """The queue's doc (read when None), or None in smuggle mode: the tollman orders and forms nothing then."""
    doc = (mtm_scan.run_json(mtm_scan.QUEUE, main) or {}) if doc is None else doc
    return None if modes.asleep(modes.of(doc)) else doc


def early(top: str, main: str, fresh: list[dict], doc: dict | None = None, panes: dict | None = None) -> list[dict]:
    """On the first fresh `job failed` event of the watched run: post_merge.red's action for its train (the standing
    one, or the one that landed with it: post_merge.past); before the merge job is green only the landing train's."""
    if not any(e["kind"] == "job-failed" for e in fresh):
        return []
    import mtm_ci
    import post_merge
    s, rows = watch_events.state(main), train_state.lines(main)
    rid, url, standing = str(s.get("run") or ""), s.get("url"), train_state.standing(rows)
    hit = next((e for e in fresh if e["kind"] == "job-failed" and e["key"].startswith(f"job:{rid}:")), None)
    own = bool(standing) and (standing["train"], standing.get("started")) == (s.get("train"), s.get("started"))
    train = standing if own else post_merge.past(rows, s.get("train"))
    if not hit or not train or (doc := awake(main, doc)) is None:
        return []
    jobs = gh_runs.jobs([rid], set(), gh_runs.view_jobs(mtm_scan.run_json, main)).get(rid) or []
    if not (own and standing["state"] == "landing") and not mtm_ci.merged(jobs):
        return []  # an early order only for the landing train's run
    return post_merge.red(top, main, train, url, rid, jobs, doc.get("queue", []),
                          hit["text"].removeprefix("job failed: "), panes)


def next_train(top: str, main: str, doc: dict | None = None) -> list[dict]:
    """4.: the chain, once the landing train's merge job is told green and its landing's process has ended."""
    train = train_state.standing(train_state.lines(main))
    if not train or train["state"] != "landing" or not watch_events.merged(main, train):
        return []
    import chain
    import hold
    if train_state.alive(train["pid"]) or awake(main, doc) is None or hold.of(main):
        return []  # a running landing is never stopped: the next minute looks again
    return [{**chain.action(top, f"merge-green:{train['train']}"),
             "text": f"train {train['train']}: merge job green: the next train forms on the new main"}]


def handler(item: dict, ctx: dict) -> list[dict]:
    """duty:watch in a full round (an early order the round's trains duty planned is not planned twice)."""
    import early_order
    return early_order.once(ctx, events(ctx.get("top") or ctx["main"], ctx["main"], bool(ctx.get("dry")), None,
                                        ctx.get("panes")))


class Panes(dict):
    """The sessions' panes by field, asked for (`hal2-cli-agents list`) only when a message is typed: a quiet minute
    never asks."""

    def __init__(self, load):
        super().__init__()
        self.load, self.loaded = load, False

    def get(self, key, default=None):
        if not self.loaded:
            self.update(self.load())
            self.loaded = True
        return super().get(key, default)


def leaver_actions(top: str, main: str, doc: dict, now: dt.datetime, wiring, panes: dict | None = None) -> list[dict]:
    """leavers.check's actions for this pass (the same call as the round's); `doc` the queue's."""
    panes = Panes(lambda: tick.context(top, main, {}, now, False, wiring)["panes"]) if panes is None else panes
    return leavers.check(main, top, doc.get("queue", []), (doc.get("priority") or {}).get("slots") or [], panes,
                         default_ref(main), False)["actions"]


def light(repo: str, wiring, now: dt.datetime | None = None) -> bool:
    """Whether this tick is a minute pass: the tools are there, the timer runs the rounds and `watch` is the only duty
    due. Anything else is a round (it reports its own problems). The worktree's cleanliness (`tick.slot_problem`:
    three git calls) is the round's to check, every 5 minutes at the latest, not a pass's (plan 0480 D3)."""
    if role_cli.missing() or role_cli.mode(repo, wiring) != "timer":
        return False
    top = tick.git(repo, "rev-parse", "--show-toplevel")
    rows, _, problems = tick.due_items(top, now, False, wiring)
    return not problems and [r["name"] for r in rows] == [ITEM]


def run(repo: str, wiring, now: dt.datetime | None = None) -> int:
    """One minute pass; the events print, one line each. A round that holds the tick lock does the watch itself.
    The pass is timed from `pass_timing.begin()` (tollman.tick, before `light`): wall, process starts and `gh` calls go
    to `pass-timing.jsonl` of the tollman's state folder (plan 0480 D1), never to stdout."""
    now = now or dt.datetime.now()
    top = tick.git(repo, "rev-parse", "--show-toplevel")
    main = mtm_scan.main_checkout(top)
    out = {"now": now, "wake": [], "notify": [], "relay": [], "done": []}
    with (role_cli.state(repo, wiring) / "tick.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            pass_timing.abandon()
            return 0
        with gh_runs.round(gh_runs.cache_dir(mtm_scan.state_dir(main, wiring.role))):
            doc = mtm_scan.run_json(mtm_scan.QUEUE, main) or {}
            asleep = modes.asleep(modes.of(doc))  # smuggle mode: the tollman sleeps, no train, no queue work
            panes = Panes(lambda: tick.context(top, main, {}, now, False, wiring)["panes"])
            planned = ([] if asleep else leaver_actions(top, main, doc, now, wiring, panes)) + events(
                top, main, False, doc, panes)
        for a in tick.fresh(planned, read_log(main, wiring.role), now, wiring.role):
            tick.execute(a, top, main, out, wiring)
            if a["duty"] == KIND or a["kind"] in PRINTED:
                print(a["text"])
        if any(out[k] for k in ("wake", "relay", "notify")):  # wake.KINDS: wake loads only when it has work
            import wake
            wake.hand_over(top, main, out, now, wiring)
    pass_timing.finish(role_cli.state(repo, wiring))  # the pass's cost (D1): a line in pass-timing.jsonl, none on stdout
    return 0
