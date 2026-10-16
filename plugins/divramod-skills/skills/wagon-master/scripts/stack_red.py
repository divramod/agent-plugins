#!/usr/bin/env python3
"""A red stack-test after the merge (hal2 plan 0349 step 10, decisions D6, D11): stack-test runs beside the merge, so
a train can land (its merge is green, status landed/nothing/shipping) while a job `.../stack-test` of the landing's
result is red. The rule part, as code: the board gets a `red` line (status `stack-test`, the train's cars), and each
car's foreman is told the failing tests as a fix for its next harvest. The train itself stays landed: nothing is
unhitched, retried or broken up. `trains.settle` calls `actions` when it settles a landed train.

The failing tests are what the red job carries: `tests` or `failed_tests` (a list or one string); a job without them
is named with the run, so the foreman reads the job's log.

Since merge no longer waits for stack-test (plan 0349 step 4), the landing's result rarely holds it: it is mostly
still running when the train settles. So `watch` reads the stack-test job of the newest landed train's land run
itself (`gh run view <id> --json jobs`, the round's shared fetch, gh_runs), each round until it has ended, at most
WATCH_HOURS after the landing: red (failure, cancelled, timed out), the same actions; anything else, one `record`
line whose key ends the watch.
"""

import datetime as dt
import re
import sys
from pathlib import Path

import gh_runs
import mtm_scan
from tick import act

STACK = "stack-test"
SHOWN = 10
TEXT = ("wagon-master (wagon train): train {train} is in the barn, but {job} is red{run}. Fix {what} in your next "
        "harvest (it is in the barn already, so the fix rides the next train): {tests}.")


def bare(name: object) -> str:
    """A job's own part of its display name: `d1-01-stack-test` (the matrix alias and the job's position, plan 0349
    D101), the older `03-hz01-host-a/01-stack-test` (the position in its lane since D40), `03-hz01-host-a/stack-test`
    and a bare `stack-test` give `stack-test`; the matrix values GitHub appended to a matrix job of a fixed name in
    older runs (`stack-test (stack-test)`) go."""
    name = re.sub(r"\s*\([^)]*\)$", "", str(name or ""))
    staged = re.match(r"^(?:[a-z][1-9]-\d\d-|\d\d-[^/]*/(?:\d\d-)?)(.+)$", name)
    return (staged[1] if staged else name.rsplit("/", 1)[-1]).strip()


def red_jobs(result: dict | None) -> list[dict]:
    """The landing result's red jobs whose job is `stack-test` (`d1-01-stack-test`; older `03-hz01-host-a/01-stack-test`,
    or without the position `03-hz01-host-a/stack-test`), also with the matrix values older runs have
    (`03-hz01-host-a/stack-test (stack-test)`)."""
    return [j for j in (result or {}).get("red") or [] if bare(j.get("name", "")) == STACK]


def tests_of(jobs: list[dict]) -> list[str]:
    """The failing tests the red jobs name, in order, once each."""
    found: list[str] = []
    for j in jobs:
        for key in ("tests", "failed_tests"):
            value = j.get(key) or []
            found += [value] if isinstance(value, str) else [str(t) for t in value]
    return list(dict.fromkeys(found))


def words(jobs: list[dict]) -> tuple[str, str]:
    """(the failing tests as one phrase, what the foreman fixes)."""
    tests = tests_of(jobs)
    if not tests:
        return "the job's failing tests (read its log)", "its failing tests"
    more = f" and {len(tests) - SHOWN} more" if len(tests) > SHOWN else ""
    return ", ".join(tests[:SHOWN]) + more, "these tests"


def actions(top: str, train: dict, result: dict | None, panes: dict, after: str | None = None) -> list[dict]:
    """[] unless the landed train's stack-test is red; else the board line and one `send` per car."""
    jobs = red_jobs(result)
    if not jobs:
        return []
    name, cars, run = train["train"], [c["field"] for c in train["cars"]], (result or {}).get("run")
    tests, what = words(jobs)
    job = ", ".join(j["name"] for j in jobs)
    own, chain = Path(top).name, {"after": after} if after else {}
    board = [sys.executable, str(Path(__file__).with_name("board.py")), "post", "--kind", "red", "--from", own,
             "--to", "-", "--train", name, "--cars", ",".join(cars), "--status", STACK, "--repo", top,
             "--text", f"train {name} is in the barn, but {job} is red: {tests}"] + (["--run", run] if run else [])
    key = f"stack-red:{name}"
    out = [act("trains", "stack-red", "run", "-", key=key, argv=board, text=f"train {name}: {job} is red after the merge",
               **chain)]
    text = TEXT.format(train=name, job=job, run=f" ({run})" if run else "", what=what, tests=tests)
    return out + [act("trains", "stack-red-fix", "send", c, pane=panes.get(c), key=f"{key}:{c}", text=text, after=key)
                  for c in cars]


WATCH_HOURS = 6  # stack-test's own limit is 270 minutes; its run is read until it ends, at most this long
RED = ("failure", "cancelled", "timed_out")


def run_id(run: str | None) -> str | None:
    """The land run's id from its address (`.../actions/runs/<id>`) or a bare id."""
    match = re.search(r"/runs/(\d+)", run or "") or re.fullmatch(r"(\d+)", run or "")
    return match[1] if match else None


def stack_job(jobs: list[dict]) -> dict | None:
    """The run's stack-test job (`d1-01-stack-test`, or older `03-hz01-host-a/01-stack-test` and
    `03-hz01-host-a/stack-test`, with or without GitHub's matrix suffix)."""
    return next((j for j in jobs if red_jobs({"red": [j]})), None)


def watch(top: str, main: str, rows: list[dict], panes: dict, log: list[dict], fetch=None,
          now: dt.datetime | None = None) -> list[dict]:
    """The newest landed train's stack-test, read from its land run (see the module doc): [] while it runs, has no
    run or was settled before (its key in the log); `fetch(run id)` gives the run's jobs (gh by default)."""
    landed = [r for r in rows if r.get("kind") == "landed"]
    row = landed[-1] if landed else {}
    name, rid = row.get("train"), run_id(row.get("run"))
    if not name or not rid:
        return []
    done = {e.get("key") for e in log}
    if f"stack-red:{name}" in done or f"stack-done:{name}" in done:
        return []
    try:
        at = dt.datetime.fromisoformat(str(row.get("at")).replace("Z", "+00:00"))
    except ValueError:
        return []
    if (now or dt.datetime.now(dt.timezone.utc)) - at > dt.timedelta(hours=WATCH_HOURS):
        return []
    fetch = fetch or gh_runs.view_jobs(mtm_scan.run_json, main)
    job = stack_job(gh_runs.jobs([rid], set(), fetch).get(rid) or [])
    if not job or job.get("status") != "completed":
        return []
    train = {"train": name, "cars": [{"field": c} for c in row.get("cars") or []]}
    if job.get("conclusion") in RED:
        return actions(top, train, {"red": [job], "run": row.get("run")}, panes)
    return [act("trains", "stack-done", "record", "-", key=f"stack-done:{name}",
                text=f"train {name}: {job.get('name')} ended {job.get('conclusion') or 'without a conclusion'}")]
