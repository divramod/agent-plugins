#!/usr/bin/env python3
"""A train whose landing ended red, settled after triage (hal2 plan 0360 step 5, D4, D5, D7, D31): what
`trains.settle` returns for it. Every red is an `engine.py red` first; then by triage.py's kind:

- `runner`: `engine.py retry --why "runner: <match>"` and `restart` by code, the same cars on a fresh run (engine.fresh),
  no wake. The train counts them (`runner_retries`, train_state.py); at MAX_RUNNER in a row the code retries no more
  and wakes once (`train-runner:<train>:<n>`, TEXT runner_broken): the train stays red, frozen and standing (D7)
- `main`, `car`: one wake (kind `train-failed`, key `train-red:<run id>`, TEXT main_red or car_red, the evidence),
  the same key the watch's wake has (watch.py), so a run the watch already woke for wakes nobody again
- `none`: a run a pause cancelled is no red (D59, step 18): no red line, no wake, no runner retry counted; the same
  landing is started again (`restart`), as a landing that ended without a result
- `smuggled`: the red touches a covered smuggle's files (D61, step 18): the red line and a fix order to the smuggling
  field by code (smuggled.py), no wake; a `conflict` while smuggles stand is the resumed landing's (D62): the same
- an early fix order stands (early_order.py, plan 0383 step 5, D5): the red line only; the train is `fixing` at once
  and waits for that order's `fixed` (a `runner`, `main` or `car` verdict changes nothing)
- no run to read (a red pretest, a conflict, a landing that ended without a result too often): one wake
  (`train-red:<train>:<starts>`, TEXT failed)
"""

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import smuggled
import train_state
import triage
from tick import act

MAX_RUNNER = 3  # runner faults retried by code in a row before the session is woken
HEAD = ("train {train} {state}: {why}. Run: {run}. Cars: {cars}. The train is frozen (plan 0360 D3): no car leaves "
        "it and no wait limit ends it (D7). ")
TEXT = {
    "failed": HEAD + "Name the cause; the train waits for its fix: `tollman.py order <car field> --why <why>` orders "
                     "a car's foreman to fix it in the train, `tollman.py order main --why <why>` the barn's red to "
                     "your own hand (plan 0360 D6, D29); `tollman.py retry --why <why>` lands it again as it is.",
    "main_red": HEAD + "Triage: the barn is red, not a car: {jobs} is red the same way in field {slot}'s land run "
                       "{other} on the same barn head {main}, so the train waits and the barn is fixed in this same "
                       "train (plan 0360 D29): `tollman.py order main --why <why>`, a hand of yours fixes it on "
                       "tollman-train-fix. `tollman.py triage {rid}` shows the evidence.",
    "car_red": HEAD + "Triage: a car's red: {jobs}; failing tests: {tests}. The cars' files against the train's base:"
                      "\n{files}\nJudge which car broke it and give its foreman the fix order: `tollman.py order <car "
                      "field> --why <why>` (plan 0360 D6); the train waits for its fix. `tollman.py triage "
                      "{rid}` shows the evidence and the log's tail.",
    "runner_broken": "train {train}: the runner looks broken: {n} runner faults in a row ({match}), each landed again "
                     "on a fresh run by code. Run: {run}. The train is red, frozen and still standing (D7): look at "
                     "the runners (docs/ci.md), then `tollman.py retry --why runner` lands it again.",
}


def cars_of(train: dict) -> str:
    """The cars with their plans, and the yard's car."""
    plans = ", ".join(f"{c['field']} ({c.get('plan') or c['branch']})" for c in train["cars"])
    return plans + (f", yard ({len(train['yard'])} files of the yard)" if train.get("yard") else "")


def text(verdict: dict, train: dict, state: str, why: str, run: str | None) -> str:
    """The wake's text for a `main` or `car` verdict."""
    return TEXT["main_red" if verdict["kind"] == "main" else "car_red"].format(
        train=train["train"], state=state, why=why, run=run or "none", cars=cars_of(train), **triage.words(verdict))


def actions(top: str, train: dict, result: dict | None, status: str, why: str, run, tickets=()) -> list[dict]:
    """The red train's actions; `run` is trains.run (an engine verb as a `run` action); `tickets` the queue's."""
    name, starts, link = train["train"], train["starts"], (result or {}).get("run")
    key = f"red:{name}:{starts}"
    red = run("red", "-", key, "red", top, "--status", status, *(["--run", link] if link else []), "--why", why,
              text=f"train {name} is red ({status}): {why}")
    if status == "conflict" and (fix := smuggled.conflict(top, triage.mtm_scan.main_checkout(top), train, result,
                                                          tickets, key)):
        return [red, *fix]
    names = [j.get("name", "") for j in (result or {}).get("red") or []]
    verdict = triage.of(top, train, link, names, list(tickets)) if status != "interrupted" else None
    if not verdict:
        return [red, act("trains", "train-failed", "wake", key=f"train-red:{name}:{starts}", after=key,
                         text=TEXT["failed"].format(train=name, state=f"did not land ({status})", why=why,
                                                    run=link or "none", cars=cars_of(train)),
                         evidence={"train": train, "result": result})]
    kind, match = verdict["kind"], verdict["evidence"].get("match")
    if kind == "none":
        return [run("restart", "-", f"restart:{name}:paused:{starts}", "restart", top,
                    text=f"train {name}: its run {link} was cancelled by smuggle "
                         f"{verdict['evidence'].get('paused_by')}'s pause, started again")]
    if kind == "smuggled":
        return [red, *smuggled.red(top, verdict, key, link)]
    if any(o.get("early") for o in train.get("orders") or []):
        return [red]  # its early fix order answers it (plan 0383 D5): `fixing` at once, no wake, no runner retry
    if kind == "runner" and (n := train.get("runner_retries", 0)) >= MAX_RUNNER:
        return [red, act("trains", "train-runner-broken", "wake", key=f"train-runner:{name}:{n}", after=key,
                         text=TEXT["runner_broken"].format(train=name, n=n, match=match, run=link),
                         evidence={**verdict, "train": train, "result": result})]
    if kind == "runner":
        again = f"runner-retry:{name}:{starts}"
        return [red, run("retry", "-", again, "retry", top, "--why", f"{train_state.RUNNER}: {match}", after=key,
                         text=f"train {name}: a runner fault ({match}), landed again on a fresh run"),
                run("restart", "-", f"restart:{name}:runner:{starts}", "restart", top, after=again,
                    text=f"train {name} lands again after a runner fault")]
    return [red, act("trains", "train-failed", "wake", key=f"train-red:{verdict['evidence']['id']}", after=key,
                     text=text(verdict, train, f"did not land ({status})", why, link),
                     evidence={**verdict, "train": train, "result": result})]
