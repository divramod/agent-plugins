"""A red after the merge (hal2 plan 0383 step 6, D6, L33, L34): a job of a land run fails after its merge job
(`d2-01-git-merge`) is green, so the train is in the barn (or about to be) and its post-merge jobs still run. Nothing
holds the next train for it: the code orders the car's foreman by the orders path, and the fix rides the train that
stands (the next train, formed on the merge's green, minute.py), merged before that train's run starts
(next_train.py).

- the hooks: `red`, for every red job of a watched run (watch.py in the round, minute.py's `job failed` event in
  the pass and the round's `duty:watch`): before the merge job is green early_order.py's early order, after it
  this module's `actions`
- the train: the standing one when the run is its own, else the train as it stood before it landed (`past`)
- D13 (plan 0490 step 3): a red the finished run's triage places (run_triage_wire.py, on `workflow finished`) is
  never ordered here: a failing spec (its owner's), a build-phase timeout (the pipeline's), a budget or transient
  line (flake, runner) or a repeat of a kept earlier run (L131) is one `record` (`post-order:<run>`), the triage
  decides it at the run's end; one place per red, never the train's cars for them
- the triage and the culprit: early_order's (triage.classify, early_order.culprit); `runner`, `none` and
  `smuggled` order nobody (a `record` line); `main` or an unclear culprit wake the session once (`train-red:<run>`)
- one car named: `tollman.py order <car> --post <train> --why "<job>: <first error line>" --run <url>`, keyed
  `post-order:<run id>` (orders.py: the order rides the standing train's `post`, its state never changes); no
  train stands: the car's foreman is told to fix it in its next harvest (stack_red's text), the same key
"""

import sys

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import early_order
import mtm_ci
import stack_red
import train_red
import train_state
import triage
from tick import act

KIND = "post-order"


def past(rows: list[dict], name: str | None) -> dict | None:
    """The train `name` as it stood before its `landed` or `cleared` line (or as it stands), or None."""
    end = next((i for i, e in enumerate(rows) if e["kind"] in ("landed", "cleared") and e.get("train") == name),
               len(rows))
    train = train_state.standing(rows[:end])
    return train if name and train and train["train"] == name else None


def red(top: str, main: str, train: dict, url: str, rid: str, jobs: list[dict], tickets=(), why: str | None = None,
        panes: dict | None = None) -> list[dict]:
    """The actions for the red jobs of `train`'s run `rid`: early_order's before its merge job is green, else ours."""
    if not mtm_ci.merged(jobs):
        return early_order.actions(top, main, train, url, rid, jobs, tickets, why)
    return actions(top, main, train, url, rid, jobs, tickets, why, panes)


def the_triages(main: str, rid: str, jobs: list[dict], log: str) -> str | None:
    """Why the finished run's triage places this run's red, not an order now (see D13 in the module doc), or None:
    a car's red, ordered here as before. The earlier runs' signatures are the triage's kept ones (no gh call)."""
    import run_triage
    import run_triage_gather
    import run_triage_read as read
    import run_triage_wire
    kept = [r for r in run_triage_wire.state(main)["runs"] if r.get("run") != rid and not r.get("error")]
    previous = [{"id": r["run"], "units": r.get("units") or {}} for r in reversed(kept)][:run_triage_gather.PREVIOUS]
    for u in read.units(jobs, log or ""):
        f = read.facts(u["lines"])
        why = ("a failing spec, its owner's" if f["specs"] else "a build-phase timeout, the pipeline's" if f["timeout"]
               else "a budget or transient line" if f["budget"] or f["transient"] or u["unserved"] else None)
        if why or (why := (f"a repeat of run {r}" if (r := run_triage.repeat_of(u["unit"], None, f, previous))
                           else None)):
            return f"{u['unit']}: {why}"
    return None


def actions(top: str, main: str, train: dict, url: str, rid: str, jobs: list[dict], tickets=(),
            why: str | None = None, panes: dict | None = None) -> list[dict]:
    """The post-merge red's action (see the module doc), or [] while no counted job is red."""
    names = mtm_ci.red_jobs(jobs)
    reds = [j for j in jobs if j.get("name") in names]
    standing = train_state.standing(train_state.lines(main))
    if not reds or any(o.get("run") == url for o in (standing or {}).get("post", [])):
        return []  # nothing red, or its order stands already
    data = triage.gather(main, train, url, names, jobs, list(tickets))
    key, jobs_text = f"{KIND}:{rid}", ", ".join(names)
    if placed := the_triages(main, rid, jobs, data[2] if data else ""):
        return [act("trains", KIND, "record", "-", key=key,
                    text=f"train {train['train']}: {jobs_text} red after its merge ({placed}): the run's triage "
                         "orders its owner when the run has finished (D13)")]
    verdict = triage.classify(*data)
    if verdict["kind"] in early_order.QUIET:
        return [act("trains", KIND, "record", "-", key=key,
                    text=f"train {train['train']}: {jobs_text} red after its merge ({verdict['kind']}): "
                         "nobody ordered")]
    wake = act("trains", "train-red", "wake", key=f"train-red:{rid}", evidence={**verdict, "train": train},
               text=train_red.text(verdict, train, "is in the barn, but red after its merge", jobs_text, url))
    field = early_order.culprit(train, verdict)
    if not field:
        return [wake]
    why = (why or early_order.why_of(main, rid, reds, verdict["evidence"].get("tail")))[:300]
    if not standing:
        tests, what = stack_red.words(reds)
        text = stack_red.TEXT.format(train=train["train"], job=jobs_text, run=f" ({url})", what=what, tests=tests)
        pane = None if panes is None else panes.get(field)  # minute.Panes: an empty dict until asked
        return [act("trains", KIND, "send", field, pane=pane, key=key, text=text)]
    argv = [sys.executable, str(early_order.CLI), "order", field, "--post", train["train"], "--why", why, "--run", url,
            "--repo", top]
    return [act("trains", KIND, "run", field, key=key, argv=argv, on_fail=[wake],
                text=f"train {train['train']}: fix order to {field} for its red after the merge ({why[:120]}); "
                     f"the fix rides train {standing['train']}")]
