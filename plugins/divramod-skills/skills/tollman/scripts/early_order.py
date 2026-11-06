"""The early fix orders (hal2 plan 0383 step 5, D5, L32, L35; plan 0522 D16, D17): each red job of a train's live land
run is triaged on its own as soon as it is red, and each car its log names is ordered while the run still runs, one
order per red job and car (plan 0608 D4); a red, or a failure of it, no single car is named for goes to the session.

- the hooks: the round (watch.actions, each round while the train lands) and the watch duty (minute.py: the minute
  pass and the round's `duty:watch`, on a fresh `job failed` event of watch_events.py); the same keys, so a tick
  and the next never act twice (tick.fresh), and `once` keeps two handlers of one round from it
- once per red job and run (D17): a job an earlier round triaged (its `early-red:<run>:<job>` record, an
  `early-order:<run>:<job>[:<car>]` key, an order line of the run (its `run` the URL or the bare run id, plan 0608
  D5) naming its gate job) is never triaged or ordered again, also when its log names a car later (train 32:
  bash-test went to the session at 04:23Z, which fixed it on the carrier itself, and the run's end ordered car 27
  for it at 05:01Z, a duplicate)
- the triage per job: triage.gather once, triage.classify with the job alone and its own failed log
  (job_error.job_log: out while the run runs); `runner`, `none` and `smuggled` need nobody here (trains.settle and
  train_red act at the run's end); `main` and a `car` red whose culprit is unclear go to the session
- the culprit (`culprit`): the only car of a train without the yard's car, else the one car (the yard counts as one)
  whose files the job's red names (`names`: a path in its log, a path in its log that ends a car's file, as a test
  runner names `gate/test-abort.bats` for `code/bash/scripts/gate/test-abort.bats`, or a file's stem in a failing
  test) or a failing test named by its name only, whose test file or unit a car's files hold (red_tests.py, plan
  0714, L262: bats `not ok <n> <name>`, unittest `FAIL: <test> (<id>)`); none or two or more: unclear, unless exactly
  one car's open early order of the train already names the failing test, its test file or its unit in its why
  (`linked`, plan 0714 D5: a second red job of a cause already ordered joins that order as an `also`, orders.py).
  The early order splits the red (`split`, plan 0608 D4; train 51's run 2 had
  four cars' failures in one job and ordered nobody): each runner's red line with up to 3 after it, cut at the next,
  is one failure, the ones naming a failing test (`crate::bin test` of nextest) grouped per test; each failure naming
  exactly one car is that car's, the rest the session's; a line naming no car, test or path (`error: test run
  failed`) is a summary, no failure. A red after the run's merge job is green is no early order: the train is in
  the barn then, post_merge.py orders it into the next train (plan 0383 step 6)
- the order: `tollman.py order <car> --why "<job>: <first error line>" --run <url>` (orders.py: the train stays
  `landing`, the foreman fixes on `<NN>-train-<n>-<a>-fix` from `origin/train-<n>-<a>` (run_names.py) and answers
  `done fixed <sha>`; a car with an open order gets this job added to it, `also`), keyed
  `early-order:<run id>:<job>:<car>`; when the job's red is split its why and its `--unit`s are the car's failing
  tests, else its failures' first lines (red_claims.py: one red, one foreman); a failed order goes to the session.
  Its `fixed` waits for the run's end (L34)
- the session's wake (`train-red`): every red of the run named, each with what the code did (ordered to a car, or
  the session's to judge); the first of a run keyed `train-red:<run id>` (train_red's wake at the run's end is the
  same key: no second), each later red refreshes it (`train-red:<run id>:<its jobs>`), once any red of the run went to
  the session; reds that all went to their cars wake nobody
"""

import re
import sys
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import job_error
import mtm_ci
import red_tests
import smuggled
import stack_red
import train_red
import train_state
import triage
from logstate import read_log
from tick import act

CLI = Path(__file__).with_name("tollman.py")
KINDS = ("early-order", "early-red", "train-red", "post-order")  # the actions `once` keeps to one per round
QUIET = ("runner", "none", "smuggled")  # reds the run's end settles (train_red.py)
ROLE = "tollman"
PATH = re.compile(r"[\w.@+-]+(?:/[\w.@+-]+)+")  # a path in a log: two parts or more, the last a file's name
NEXTEST = re.compile(r"FAIL \[\s*[\d.]+s\] (?:\(\s*\d+/\d+\) )?(\S+ [\w:]+)")  # its counter is padded: `(  935/14017)`


def names(files: list[str], tail: str | None, tests: list[str]) -> bool:
    """Whether a red's log `tail` or its failing `tests` name one of `files` (see the module doc)."""
    if smuggled.touched([{"files": files}], tail, tests):
        return True
    tails = {"/" + t for t in PATH.findall(tail or "") if "." in t.rsplit("/", 1)[-1]}
    return any(f.endswith(t) for f in files for t in tails)


def cars_named(rows: list[dict], text: str, tests: list[str], repo: red_tests.Repo | None = None) -> list[str]:
    """The slots of `rows` the red `text` names: by a file of theirs in the log (`names`) or by the test file or
    unit of a failing test named by its name only (red_tests.py, plan 0714 D3: bats `not ok` and unittest `FAIL`)."""
    slots = {r["slot"] for r in rows if names(r["files"], text, tests)} | red_tests.owners(rows, text, repo)
    return [r["slot"] for r in rows if r["slot"] in slots]


def linked(train: dict, rows: list[dict], text: str, repo: red_tests.Repo | None = None) -> str | None:
    """The one car whose open early order of `train` already names the cause of the failure `text` (plan 0714 D5,
    L262): its test's name or id, test file or unit, as the order's why holds them; None for none or several. The
    red is then that car's: `order` to it is an `also` on the open order (orders.py)."""
    slots = {r["slot"] for r in rows} - {train_state.YARD}
    clues = red_tests.clues(text, rows, repo)
    hits = {o["field"] for o in train.get("orders") or [] if o.get("field") in slots and not o.get("post")
            and clues and red_tests.mentions(o.get("why") or "", clues)}
    return hits.pop() if len(hits) == 1 else None


def red_lines(tail: str | None) -> str:
    """The lines of `tail` that say the red (a test runner's own red line, else an error word) with the 3 after each
    (bats names the test's file there), or the whole tail when none does: the paths of passing tests (bash-test lists
    every unit it ran) name no culprit."""
    lines = [job_error.STAMP.sub("", job_error.ANSI.sub("", x.split("\t", 2)[-1]).strip()) for x in
             (tail or "").splitlines()]
    for pattern in (job_error.OWN, job_error.ERROR):
        if hits := [i for i, x in enumerate(lines) if pattern.search(x)]:
            return "\n".join(lines[i] for i in sorted({k for h in hits for k in range(h, min(h + 4, len(lines)))}))
    return tail or ""


def culprit(train: dict, verdict: dict, tail: str | None = None, main: str | None = None) -> str | None:
    """The one car the `car` verdict names, or None (see the module doc); `tail`: the red job's own failed log, else
    the verdict's; `main`: the checkout the test names are looked up in (red_tests.py)."""
    if verdict["kind"] != "car":
        return None
    e = verdict["evidence"]
    text = red_lines(tail if tail is not None else e.get("tail"))
    rows = [{"slot": c["field"], "files": c.get("files") or []} for c in e.get("cars") or []]
    if train.get("yard"):
        rows.append({"slot": train_state.YARD, "files": [f["path"] for f in train["yard"]]})
    repo = red_tests.repo(main, train)
    slots = [r["slot"] for r in rows] if len(rows) == 1 else cars_named(rows, text, e.get("tests") or [], repo)
    if len(slots) != 1 and len(rows) > 1 and (car := linked(train, rows, text, repo)) and car in (slots or [car]):
        slots = [car]
    return slots[0] if len(slots) == 1 and slots[0] != train_state.YARD else None


def failures(tail: str | None, tests: list[str]) -> list[tuple[str, list[str]]]:
    """The red's failures (plan 0608 D4): [(their lines, their failing tests)]; each runner's red line (else error
    line) with up to 3 after it, cut at the next, the lines naming a failing test grouped per test (see the module
    doc); no such line: the whole tail as one."""
    lines = [job_error.STAMP.sub("", job_error.ANSI.sub("", x.split("\t", 2)[-1]).strip()) for x in
             (tail or "").splitlines()]
    hits = next((h for pattern in (job_error.OWN, job_error.ERROR)
                 if (h := [i for i, x in enumerate(lines) if pattern.search(x)])), [])
    if not hits:
        return [(tail or "", list(tests))]
    blocks = ["\n".join(lines[h:min(h + 4, end)]) for h, end in zip(hits, hits[1:] + [len(lines)])]
    tests = tests_of(tail or "", tests)
    per = {t: [b for b in blocks if t.rsplit(" ", 1)[-1] in b] for t in tests}
    loose = [b for b in blocks if not any(b in v for v in per.values())]
    return [("\n".join(v), [t]) for t, v in per.items()] + [(b, []) for b in loose]


def tests_of(tail: str, tests: list[str]) -> list[str]:
    """`tests` with nextest's names of `tail` (mtm_scan's pattern reads `( 3179` from a padded counter), a bare name
    left out where a `crate::bin name` has it."""
    found = list(dict.fromkeys([t for t in tests if not t.startswith("(")] + NEXTEST.findall(tail)))
    return [n for n in found if not any(o != n and o.endswith((" " + n, "::" + n)) for o in found)]


def rows_of(train: dict, evidence: dict) -> list[dict]:
    """The train's cars with their files, the yard's as one more."""
    rows = [{"slot": c["field"], "files": c.get("files") or []} for c in evidence.get("cars") or []]
    if train.get("yard"):
        rows.append({"slot": train_state.YARD, "files": [f["path"] for f in train["yard"]]})
    return rows


def split(train: dict, verdict: dict, tail: str | None = None,
          main: str | None = None) -> tuple[dict[str, list[str]], bool]:
    """({car: what of the red is its}, whether a failure goes to the session) for a red job (D4, see the module doc):
    a failure naming exactly one car is that car's; none, several or the yard's are the session's."""
    if verdict["kind"] != "car":
        return {}, True
    e = verdict["evidence"]
    tail, rows = tail if tail is not None else e.get("tail"), rows_of(train, e)
    if len(rows) == 1:
        return ({}, True) if rows[0]["slot"] == train_state.YARD else ({rows[0]["slot"]: []}, False)
    repo = red_tests.repo(main, train)
    red_tests.prefetch(tail, rows, repo)  # the red's bats names in one git process, not one per failure (D7)
    placed = [(cars_named(rows, text, tests, repo), text, tests)
              for text, tests in failures(tail, e.get("tests") or [])]
    placed = [p for p in placed if p[0] or p[2] or PATH.search(p[1]) or red_tests.failing(p[1])] or [  # not a summary
        (cars_named(rows, red_lines(tail), e.get("tests") or [], repo), "", [])]
    cars, rest = {}, False
    for named, text, tests in placed:
        car = named[0] if len(named) == 1 else linked(train, rows, text, repo)
        car = car if car in (named or [car]) else None  # a link picks among the cars named, else it is the only one
        if car and car != train_state.YARD:
            cars.setdefault(car, []).extend(tests or [text.split("\n", 1)[0]])
        else:
            rest = True
    return cars, rest


def why_of(main: str, rid: str, red: list[dict], tail: str | None) -> str:
    """`<job>: <its first error line>` for the run's first red job; `tail`: the triage's failed log."""
    return f"{red[0].get('name')}: {job_error.first_error(main, rid, red[0], tail)}" if red else "a red job"


def handled(main: str, train: dict, url: str, rid: str, log: list[dict]) -> set[str]:
    """The red jobs of run `rid` triaged before (D17): their records or order keys, or an order line of the run (the
    session's own too, or a red step's, plan 0490 D25) naming the job's gate job or starting with the job's name."""
    keys = [e.get("key") or "" for e in log]
    done = {k.split(":")[2] for k in keys if k.startswith((f"early-red:{rid}:", f"early-order:{rid}:"))}  # per job
    orders = [e for e in train_state.lines(main) if e["kind"] == "order" and e.get("train") == train["train"]
              and str(e.get("run")) in (url, rid)]  # by hand a bare run id (D5)
    jobs = {j for e in orders for j in e.get("jobs") or []}
    named = {str(e.get("why") or "").split(":", 1)[0] for e in orders}  # a step's order (run_triage_step): `<job>: ...`
    return done | named | {"*" + j for j in jobs}


def actions(top: str, main: str, train: dict, url: str, rid: str, jobs: list[dict], tickets=(),
            why: str | None = None) -> list[dict]:
    """The round's or the pass's actions for the live run `rid` whose jobs are `jobs`: per new red job its order or
    its record, and the session's wake (see the module doc)."""
    names_ = mtm_ci.red_jobs(jobs)
    red = [j for j in jobs if j.get("name") in names_]
    log = read_log(main, ROLE) if red else []
    done = handled(main, train, url, rid, log)
    new = [j for j in red if j["name"] not in done and "*" + stack_red.bare(j["name"]) not in done]
    data = triage.gather(main, train, url, names_, jobs, list(tickets)) if new else None
    if not data:
        return []
    run, _, logs, history = data
    out, told, unclear = [], {}, None
    for j in new:
        tail = job_error.job_log(main, j) or logs
        verdict = triage.classify(run, [j], tail, history)
        quiet = verdict["kind"] in QUIET
        cars, rest = ({}, not quiet) if quiet or mtm_ci.merged(jobs) else split(train, verdict, tail, main)
        unclear = unclear or (verdict if rest else None)
        said = [f"ordered to {', '.join(cars)}"] if cars else []
        told[j["name"]] = verdict["kind"] if quiet else "; ".join(said + (["yours"] if rest or not cars else []))
        out.append(act("trains", "early-red", "record", "-", key=f"early-red:{rid}:{j['name']}",
                       text=f"train {train['train']}: {j['name']} red while it lands: {told[j['name']]}"))
        for field, what in cars.items():
            split_ = bool(what) and (rest or len(cars) > 1)  # its units: one red, one foreman (red_claims.py)
            mine = f"{j['name']}: {', '.join(what)}" if split_ else \
                why if why and why.startswith(j["name"] + ":") else \
                f"{j['name']}: {job_error.first_error(main, rid, j, tail)}"
            out.append(order(top, train, url, rid, j["name"], field, mine[:300], verdict, what if split_ else []))
    woken = any((e.get("key") or "").startswith(f"train-red:{rid}") for e in log)
    if not (unclear or (woken and told)):
        return out
    verdict = unclear or triage.classify(run, new, logs, history)
    key = f"train-red:{rid}" + (f":{','.join(sorted(told))}" if woken else "")
    said = "; ".join(f"{n}: {told.get(n, 'told before')}" for n in names_)
    return out + [act("trains", "train-red", "wake", key=key, evidence={**verdict, "train": train},
                      text=train_red.text(verdict, train, "is red while it lands", ", ".join(names_), url)
                      + f" Each red so far (plan 0522 D16): {said}.")]


def order(top: str, train: dict, url: str, rid: str, job: str, field: str, why: str, verdict: dict,
          units: list[str] = ()) -> dict:
    """The early order of the red `job` to `field` (its `units`: the failures of a split red); a failed one goes to
    the session."""
    argv = [sys.executable, str(CLI), "order", field, "--why", why, "--run", url, "--repo", top,
            *[x for u in units for x in ("--unit", u[:200])]]
    stuck = act("trains", "train-red", "wake", key=f"train-red:{rid}:{job}:{field}:order",
                evidence={**verdict, "train": train},
                text=train_red.text(verdict, train, "is red while it lands", job, url)
                + f" The fix order to {field} failed: `{' '.join(argv[1:4])} ...` says why.")
    return act("trains", "early-order", "run", field, key=f"early-order:{rid}:{job}:{field}", argv=argv,
               on_fail=[stuck],
               text=f"train {train['train']}: fix order to {field} while its run runs ({why[:120]})")


def once(ctx: dict, planned: list[dict]) -> list[dict]:
    """`planned` without the early orders and red wakes another handler of this round planned already."""
    seen = ctx.setdefault("early_keys", set())
    out = [a for a in planned if a["kind"] not in KINDS or a.get("key") not in seen]
    seen.update(a.get("key") for a in out if a["kind"] in KINDS)
    return out
