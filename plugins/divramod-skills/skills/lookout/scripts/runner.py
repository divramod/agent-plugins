"""The check runner (plan 0311 design.md, Check contract; D11): run one watch's check, dedupe, judge new events.

`run_check` runs the record's `check` by the contract: argv from `shlex` (`{python}` the running interpreter,
`{checks}` the skill's `checks/`, `~` expanded; never a shell), cwd the record's `farm`, stdin the record as JSON,
env the tick's plus `LOOKOUT_FARM`, `LOOKOUT_WATCH`, `LOOKOUT_STATE`, `LOOKOUT_SINCE` (UTC, D17; empty the first
time) and `LOOKOUT_DRY_RUN=1` on a dry run; `timeout` seconds (default 60, at most 300) kill the process group.
Exit 0 quiet, 10 found, 11 found and settled, 75 not checkable now, any other or a timeout broken; stdout over
64 kB or a found line without `id`/`summary` is broken.

`run_watch` adds the watch's state: the alert counters, the dedupe on `delivered` and `pending`, and the judge
(only for a new event of a watch with `judge`; a quiet run never reaches it, so it spends 0 tokens). It returns the
run keys for the record (D10), the finds for the find path (step 4), the alert and one `kind: check` log line.
No store file IO here: the caller reads the record and writes the run keys. Stdlib only.
"""

import functools
import json
import os
import shlex
import sys
from pathlib import Path

import judge as judge_mod
import paths
import proc
import watchstate

CHECKS = Path(__file__).resolve().parent / "checks"
DEFAULT_TIMEOUT = 60
MAX_TIMEOUT = 300
STDOUT_LIMIT = 64 * 1024
RESULT_LIMIT = 200
EXIT_KINDS = {0: "quiet", 10: "found", 11: "settled", 75: "unreachable"}
STATE_WORD = {"quiet": "quiet", "found": "found", "settled": "found", "unreachable": "unreachable",
              "broken": "broken"}


def argv(check, python=None, checks=None):
    """The check's command line as argv (POSIX shlex rules on every system)."""
    python = python or sys.executable
    checks = str(checks or CHECKS)
    words = shlex.split(str(check))
    return [os.path.expanduser(w.replace("{python}", python).replace("{checks}", checks)) for w in words]


def timeout(record):
    try:
        value = int(record.get("timeout") or DEFAULT_TIMEOUT)
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT
    return max(1, min(value, MAX_TIMEOUT))


def check_env(base, farm, record, check_dir, since, dry_run):
    env = dict(base)
    env.update(LOOKOUT_FARM=farm, LOOKOUT_WATCH=str(record.get("id", "")), LOOKOUT_STATE=str(check_dir),
               LOOKOUT_SINCE=since or "")
    env.pop("LOOKOUT_DRY_RUN", None)
    if dry_run:
        env["LOOKOUT_DRY_RUN"] = "1"
    return env


def parse_found(text):
    """The events of a found run, one JSON object per non-empty line: (events, None) or (None, reason)."""
    events = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except ValueError:
            return None, "found line is not JSON"
        if not isinstance(event, dict) or not isinstance(event.get("id"), str) or not event["id"] \
                or not isinstance(event.get("summary"), str):
            return None, "found line without id or summary"
        events.append(event)
    if not events:
        return None, "found without an event"
    return events, None


def parse_unreachable(text):
    """(cause, detail) of an exit 75: one JSON line {cause, detail}, or plain text (cause `unknown`)."""
    text = text.strip()
    try:
        data = json.loads(text.splitlines()[0]) if text else {}
    except ValueError:
        data = None
    if isinstance(data, dict) and data.get("cause"):
        return str(data["cause"]), str(data.get("detail") or "")
    return "unknown", text[:RESULT_LIMIT]


def _first_line(text):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[0][:RESULT_LIMIT] if lines else ""


def classify(run):
    """The outcome of one finished check run: {kind, code, ms, events, status, cause, detail, stderr}."""
    outcome = {"kind": "broken", "code": run["code"], "ms": run["ms"], "events": [], "status": "",
               "cause": None, "detail": "", "stderr": proc.tail(run["err"])}
    kind = EXIT_KINDS.get(run["code"])
    if run["error"] or run["timed_out"] or kind is None:
        outcome["detail"] = run["error"] or ("timeout" if run["timed_out"] else f"exit {run['code']}")
        return outcome
    if len(run["out"]) > STDOUT_LIMIT:
        outcome["detail"] = "stdout over 64 kB"
        return outcome
    text = run["out"].decode("utf-8", errors="replace")
    if kind in ("found", "settled"):
        events, reason = parse_found(text)
        if events is None:
            outcome["detail"] = reason
            return outcome
        outcome["events"] = events
    elif kind == "unreachable":
        outcome["cause"], outcome["detail"] = parse_unreachable(text)
    else:
        outcome["status"] = _first_line(text)
    outcome["kind"] = kind
    return outcome


def run_check(record, farm, watch_dir, *, since="", dry_run=False, env=None):
    """Run the record's check once by the contract; returns `classify`'s outcome."""
    check_dir = Path(watch_dir) / "check"
    check_dir.mkdir(parents=True, exist_ok=True)
    try:
        command, error = argv(record.get("check") or ""), "no check"
    except ValueError as exc:
        command, error = [], f"check: {exc}"
    if not command:
        return classify({"code": None, "timed_out": False, "out": b"", "err": b"", "ms": 0, "error": error})
    stdin = json.dumps(record, ensure_ascii=False, default=str).encode("utf-8")
    run = proc.run(command, cwd=record.get("farm") or None, stdin=stdin, timeout=timeout(record),
                   env=check_env(dict(os.environ) if env is None else env, farm, record, check_dir, since, dry_run))
    return classify(run)


def _find(event, verdict, judged):
    return {"event": event, "judged": judged, "verdict": verdict["verdict"], "title": verdict["title"],
            "notify": verdict["notify"], "data": verdict["data"]}


def _judge_one(record, farm, event, watch_dir, state, attempts, now, judge_fn):
    """Judge one event into the state: a find (pending at `find`), an ignore (delivered) or a retry (`judge`)."""
    if not record.get("judge"):
        watchstate.set_pending(state, event, "find", 0, _find(event, judge_mod.unjudged(event), False))
        return
    verdict = judge_fn(record, farm, event, watch_dir, now=now)
    if verdict.get("ok") and verdict["verdict"] == "ignore":
        watchstate.deliver(state, event["id"], now)
    elif verdict.get("ok"):
        watchstate.set_pending(state, event, "find", 0, _find(event, verdict, True))
    elif verdict.get("skipped") or attempts + 1 >= judge_mod.MAX_ATTEMPTS:
        watchstate.set_pending(state, event, "find", 0, _find(event, judge_mod.unjudged(event), False))
    else:
        watchstate.set_pending(state, event, "judge", attempts + 1)


def retry_judges(record, farm, watch_dir, state, now, judge_fn=None):
    """Judge again every event pending at `judge` (the tick's retry of pending, design.md Tick)."""
    for entry in [p for p in state["pending"] if p["step"] == "judge"]:
        _judge_one(record, farm, entry["event"], watch_dir, state, entry["attempts"], now,
                   judge_fn or judge_mod.judge)


def finds(state):
    """The finds waiting for the find path (step 4): pending entries at `find`."""
    return [p["find"] for p in state["pending"] if p["step"] == "find" and "find" in p]


def _record_keys(outcome, started, fresh):
    if outcome["kind"] in ("found", "settled"):
        result = f"{len(fresh)} new of {len(outcome['events'])}"
    elif outcome["kind"] == "quiet":
        result = outcome["status"]
    elif outcome["kind"] == "unreachable":
        result = f"{outcome['cause']}: {outcome['detail']}"[:RESULT_LIMIT]
    else:
        result = outcome["detail"][:RESULT_LIMIT]
    return {"last_run": started.isoformat(), "last_result": result, "state": STATE_WORD[outcome["kind"]]}


def _log_line(farm, record, outcome, fresh, started):
    line = {"kind": "check", "at": started.isoformat(), "farm": farm, "watch": record.get("id"),
            "outcome": outcome["kind"], "code": outcome["code"], "ms": outcome["ms"],
            "events": len(outcome["events"]), "new": len(fresh), "cause": outcome["cause"]}
    if outcome["kind"] == "broken":
        line.update(detail=outcome["detail"], stderr=outcome["stderr"])
    return line


def run_watch(record, farm, watch_dir=None, *, now=None, dry_run=False, env=None, judge_fn=None, log=None):
    """Run one due watch: check, count, dedupe, judge each new event, save state.json, log one line.

    Returns {outcome, record (the run keys), finds, alert, end (exit 11: the watch ends), new}. A dry run calls
    no judge and saves no state. `env` is the tick's env for the check and the judge (default os.environ);
`judge_fn` defaults to `judge.judge` (tests pass a fake).
    """
    watch_dir = Path(watch_dir) if watch_dir else paths.watch_dir(farm, str(record.get("id")))
    started = now or paths.now()
    state = watchstate.load(watch_dir)
    watchstate.prune(state, started)
    outcome = run_check(record, farm, watch_dir, since=state["since"], dry_run=dry_run, env=env)
    alert = watchstate.account(state, outcome["kind"], outcome["cause"], started,
                               record.get("title") or record.get("id"), started)
    fresh = watchstate.new_events(state, outcome["events"])
    judge_fn = judge_fn or functools.partial(judge_mod.judge, log=log, env=env)
    if dry_run:
        found = [_find(e, judge_mod.unjudged(e), False) for e in fresh]
    else:
        retry_judges(record, farm, watch_dir, state, started, judge_fn)
        for event in fresh:
            _judge_one(record, farm, event, watch_dir, state, 0, started, judge_fn)
        watchstate.save(watch_dir, state)
        found = finds(state)
        paths.append_log(_log_line(farm, record, outcome, fresh, started), log)
    return {"outcome": outcome["kind"], "record": _record_keys(outcome, started, fresh), "finds": found,
            "alert": alert, "end": outcome["kind"] == "settled", "new": len(fresh)}
