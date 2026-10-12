#!/usr/bin/env python3
"""Merge trains as code (the duty `trains`, subskills/merge-train; hal2 plan 0128 step 7).

At every round everything waiting behind the current run becomes one train (the user, 2026-10-06: "its a duty of the
farmer to always create the merge train for all the queued worktrees behind the current run"; hal2's
.adr/merge-queue-policy.md rule 3, hal2 plan 0169): the gates run once. `group` takes the queue's tickets in queue
order. The **carrier** is the holder while its candidate is not pushed (a plain reservation, a priority slot
included), else the first waiter; a running landing is never touched. Every other waiter with commits rides when
the trial merge (trial.py: `git merge-tree`, in queue order) is clean or conflicts only in append-only files; one
that conflicts elsewhere is left out and named. No maximum. The carrier is told (a template) to merge the others
into its branch and land as usual. The **passengers** keep their tickets (their follow-up landing is quick) and
are told to /mfm after it lands. A carrier whose landing fails while its train is under way wakes the farmer: the
train splits (judgment: which passenger broke it). Conflicts the carrier hits it resets and names itself.

  trains.py plan [--repo <dir>] [--json]
      the trains the queue allows now and the messages they would send (a dry run: nothing is sent or logged)
"""

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import lead_marker
import mtm_ci
import mtm_scan
import trial as trial_merge
from tick import act, default_ref, git

QUEUE = ["hal2-cli-git", "worktree", "queue", "--json"]
WINDOW = dt.timedelta(hours=12)  # a train under way: its slots are not grouped again, its failure is watched
TRAIN = "farmer (merge train)"
TEXT = {
    "carrier": TRAIN + ": you carry a merge train. Merge {branches} into your branch now (`git merge --no-ff "
                       "--no-edit <branch>`, one at a time, in this order; a trial merge was clean but for "
                       "append-only docs and generated files: keep both sides there, regenerate lock files), run "
                       "your quick checks and land as usual (/mtm). A merge that conflicts elsewhere, or a "
                       "passenger's change that fails the landing before it lands: `git reset --hard ORIG_HEAD` for "
                       "it, land without it and name it in one line.{left}{subject}",
    "passenger": TRAIN + ": your branch {branch} rides in slot {carrier}'s landing; keep your ticket and wait. "
                         "After it lands run /mfm; your /mtm then lands what is left (plan steps checked after the "
                         "landing), probably nothing.",
    "failed": "train {key}: the carrier {carrier}'s landing failed ({why}). Split it: find the passenger that broke "
              "it, tell the carrier to reset that merge (`git reset --hard ORIG_HEAD`) and land without it, and that "
              "passenger to land alone after /mfm.",
}


# The candidate's subject (the land run's title) is the carrier's CURRENT_PLAN (hal2 plan 0131, the user 2026-10-06:
# "or better, only <CURRENT_PLAN>"): a train names every car's.
SUBJECT = (" Before your landing, write `{line}` as the first line of your plans/CURRENT_PLAN (your landing's commit "
           "and run are named after it; drop a reset passenger's name).")


def current_plan(worktree: str) -> str:
    """The first line of the worktree's plans/CURRENT_PLAN, or ''."""
    current = Path(worktree) / "plans/CURRENT_PLAN"
    text = current.read_text() if current.exists() else ""
    return next((line.strip() for line in text.splitlines() if line.strip()), "")


def slot_info(main: str, tickets: list[dict]) -> dict[str, dict]:
    """Per ticket's slot: `ahead` (its branch's commits the default branch lacks) and its CURRENT_PLAN's first line.
    A subservant's slot (plans/LEAD, even a broken one) never lands, so it never rides: `marked`, nothing ahead."""
    base, out = default_ref(main), {}
    for t in tickets:
        if not t.get("worktree") or not t.get("branch"):
            continue
        if lead_marker.marker(t["worktree"]) is not None:
            out[t["slot"]] = {"ahead": 0, "current": "", "marked": True}
            continue
        count = git(main, "rev-list", "--count", "--no-merges", f"{base}..{t['branch']}").strip()
        out[t["slot"]] = {"ahead": int(count) if count.isdigit() else 0, "current": current_plan(t["worktree"])}
    return out


def under_way(log: list[dict], now: dt.datetime) -> dict[str, dict]:
    """The trains recorded within WINDOW, by key: carrier, passengers, when."""
    out = {}
    for e in log:
        kind, _, cars = e.get("key", "").partition(":")
        if kind == "train" and e.get("kind") == "train" and now - dt.datetime.fromisoformat(e["at"]) < WINDOW:
            carrier, *passengers = cars.split("+")
            out[e["key"]] = {"carrier": carrier, "passengers": passengers, "at": e["at"]}
    return out


def carries(t: dict) -> bool:
    """The holder may carry: a plain reservation, so no candidate of it is pushed and no landing of it runs. A
    running landing (`active`), a red candidate's hold and a kept lease (landed already) are never touched."""
    return (t.get("state") == "held" and (t.get("hold") or {}).get("reason") == "reserved"
            and not t.get("kept_until") and not t.get("landing"))


def group(tickets: list[dict], info: dict[str, dict], riding: dict[str, str], trial) -> tuple[list[str], dict]:
    """The one train the queue allows now (carrier first, [] for none) and the waiters the trial merge left out
    (slot: files). `riding`: the slots of trains under way, `carrier` or `passenger`: a passenger is not taken
    again, a carrier that has not landed yet takes on the waiters that came since. `trial(carrier, waiters)` is
    trial.ride over slots."""
    order = sorted(tickets, key=lambda t: t.get("position", 0))
    lands = lambda s: info.get(s, {}).get("ahead") and not info[s].get("marked")  # noqa: E731
    waiters = [t["slot"] for t in order if t.get("state") == "waiting" and lands(t["slot"])
               and t["slot"] not in riding]
    head = next((t for t in order if t.get("state") != "waiting"), None)
    if head and carries(head) and lands(head["slot"]) and riding.get(head["slot"]) != "passenger":
        carrier = head["slot"]
    else:
        first = next((t["slot"] for t in order if t.get("state") == "waiting" and lands(t["slot"])
                      and riding.get(t["slot"]) != "passenger"), None)
        carrier, waiters = first, [s for s in waiters if s != first]
    if not carrier or not waiters:
        return [], {}
    riders, left = trial(carrier, waiters)
    return ([carrier, *riders] if riders else []), left


def train_actions(cars: list[str], branches: dict[str, str], panes: dict, plans: dict[str, str] = None,
                  left: dict = None) -> list[dict]:
    """The carrier's message first (with the train's CURRENT_PLAN line: every car's, joined by ` + `); the passengers'
    and the record follow it (dropped with it by tick.fresh)."""
    carrier, passengers = cars[0], cars[1:]
    line = " + ".join(n for n in ((plans or {}).get(c, "") for c in cars) if n)
    subject = SUBJECT.format(line=line) if line else ""
    out_of = "; ".join(f"{s} ({', '.join(f[:5])})" for s, f in (left or {}).items())
    named = f" Left out, it conflicts: {out_of}." if out_of else ""
    key, window = "train:" + "+".join(cars), WINDOW.total_seconds()
    first = f"{key}:{carrier}"
    out = [act("trains", "carrier", "send", carrier, pane=panes.get(carrier), key=first, window=window,
               text=TEXT["carrier"].format(branches=", ".join(branches[p] for p in passengers), left=named,
                                            subject=subject))]
    out += [act("trains", "passenger", "send", p, pane=panes.get(p), key=f"{key}:{p}", window=window, after=first,
                text=TEXT["passenger"].format(branch=branches[p], carrier=carrier)) for p in passengers]
    return out + [act("trains", "train", "record", carrier, key=key, window=window, after=first,
                      text=f"merge train: {carrier} carries {', '.join(passengers)}"
                           + (f"; left out: {out_of}" if out_of else ""))]


def failures(trains: dict[str, dict], tickets: list[dict], red: list[dict] = ()) -> list[dict]:
    """A train whose carrier's landing failed: its ticket held by a failed local landing, or (CI, mtm_ci) a red
    land.yml run of the carrier started after the train (a red CI landing keeps its reservation hold, which says
    nothing about the run): wake the farmer to split it."""
    held = {t["slot"]: t for t in tickets if (t.get("hold") or {}).get("reason") == "failed"}
    out = []
    for key, tr in trains.items():
        t = held.get(tr["carrier"])
        if t:
            why = (t["hold"].get("message") or t["hold"].get("step") or "failed")[:300]
            out.append(act("trains", "train-failed", "wake", tr["carrier"], key=f"{key}:failed:{t.get('seq')}",
                           text=TEXT["failed"].format(key=key, carrier=tr["carrier"], why=why), train=tr))
            continue
        since = dt.datetime.fromisoformat(tr["at"]).timestamp()
        r = next((r for r in red if r["slot"] == tr["carrier"] and r["started"] >= since), None)
        if r:
            why = f"red: {r['task'] or 'the gate'} {r.get('url') or ''}".strip()
            out.append(act("trains", "train-failed", "wake", tr["carrier"], key=f"{key}:failed:run{r['id']}",
                           text=TEXT["failed"].format(key=key, carrier=tr["carrier"], why=why), train=tr))
    return out


def ci_red(main: str, now: dt.datetime) -> list[dict]:
    """The failed land.yml runs within WINDOW, where the repository lands through CI."""
    default = default_ref(main).removeprefix("origin/")
    if not mtm_ci.ci_mode(mtm_scan.run, main, default):
        return []
    rows = mtm_ci.landings(mtm_scan.run_json, main, (now - WINDOW).timestamp())
    return [r for r in rows if r["outcome"] == "failed"]


def real_trial(main: str, tickets: list[dict]):
    """trial.ride over slots: the tickets give each slot's branch."""
    branch = {t["slot"]: t.get("branch") or t["slot"] for t in tickets}
    return lambda carrier, waiters: trial_merge.ride(main, default_ref(main), branch[carrier],
                                                     [(s, branch[s]) for s in waiters])


def plan(tickets: list[dict], info: dict[str, dict], log: list[dict], panes: dict, now: dt.datetime,
         red: list[dict] = (), trial=lambda carrier, waiters: (waiters, {})) -> list[dict]:
    trains = under_way(log, now)
    riding = {s: "passenger" for tr in trains.values() for s in tr["passengers"]}
    riding.update({tr["carrier"]: "carrier" for tr in trains.values() if tr["carrier"] not in riding})
    branches = {t["slot"]: t.get("branch") or t["slot"] for t in tickets}
    out = failures(trains, tickets, red)
    cars, left = group(tickets, info, riding, trial)
    if cars:
        out += train_actions(cars, branches, panes, {s: i.get("current", "") for s, i in info.items()}, left)
    return out


def handler(item: dict, ctx: dict) -> list[dict]:
    """duty:trains: the queue, each waiting slot's state, then the trains and failed ones."""
    tickets = (mtm_scan.run_json(QUEUE, ctx["main"]) or {}).get("queue", [])
    log = ctx.get("log", [])
    red = ci_red(ctx["main"], ctx["now"]) if under_way(log, ctx["now"]) else []
    return plan(tickets, slot_info(ctx["main"], tickets), log, ctx.get("panes", {}), ctx["now"], red,
                real_trial(ctx["main"], tickets))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["plan"])
    ap.add_argument("--repo", default=".")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    main_dir = mtm_scan.main_checkout(args.repo)
    tickets = (mtm_scan.run_json(QUEUE, main_dir) or {}).get("queue", [])
    info = slot_info(main_dir, tickets)
    log = mtm_scan.entries(mtm_scan.state_dir(main_dir) / "log.jsonl")
    actions = plan(tickets, info, log, {}, dt.datetime.now(), trial=real_trial(main_dir, tickets))
    if args.json:
        print(json.dumps({"slots": {s: {"ahead": i["ahead"], "marked": bool(i.get("marked"))} for s, i in info.items()},
                          "actions": actions}, indent=1))
        return 0
    for s, i in info.items():
        print(f"{s}: {i['ahead']} commits ahead{', a subservant' if i.get('marked') else ''}")
    for a in actions:
        print(f"{a['kind']} {a['slot']}: {a['text']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
