"""No silent duty (hal2 plan 0514 step 6, D17): a farmer or tollman duty that fails, times out or is deferred past its
next run is reported, and each duty's last good run is counted. Deterministic code, no model: a quiet round costs
nothing, a report is a board line (and, for a disk or production duty, a desktop notification), never a wake.

The round frame (tick.py) calls this for the farmer and the tollman alike, after the round's actions ran:

  failed    the duty's handler raised, or one of its `run` actions exited non-zero (not OFFLINE: that one did not run)
  timeout   the same with `subprocess.TimeoutExpired` (bounded.py), or a run whose output says it timed out
  deferred  the duty's next run (its cron's first fire after its last run) is MIN_LATE past and it has not run: the
            round that should have run it never came (a tick that finds the lock held, a hung round), or a handler marked its
            action `health="deferred"` (it put its work off on purpose)

A report goes to the role's message board as a `note` line (board.py) and, for the duties in NOTIFY (disk:
`prune`; production: `trains`, `mainred`, `watch`), through lookout's notifier (`notify.send`: desktop, Telegram).
The same duty with the same status is reported again only after REPEAT, or when its status changes; a good run
clears it.

State: `duty-health.json` in the role's state folder (a gitignored snapshot of the manifest's `*.json`):
`{"schema": 1, "duties": {"duty:<name>": {"good", "last_good", "status", "why", "bad", "last_bad", "seen",
"reported": {"status", "at"}}}, "busy_checked": <UTC>}`, times RFC 3339 UTC with `Z`, written atomically (temp file,
then rename) under `duty-health.lock`. Retention: a duty that is no longer opted in leaves after RETAIN; the file
holds one entry per opted-in duty.
"""

import contextlib
import datetime as dt
import fcntl
import importlib.util
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import board
import due
import mtm_scan
import roles
import tick
from tick import OFFLINE, act

sys.path.insert(0, next(str(_p / "scripts") for _p in Path(__file__).resolve().parents if (_p / ".claude-plugin").is_dir()))
from skillpath import sibling  # noqa: E402  (the skills unit's scripts/, plan 0360 D20)

SCHEMA = 1
FILE, LOCK = "duty-health.json", "duty-health.lock"
BAD = ("failed", "timeout", "deferred")
REPEAT = dt.timedelta(hours=6)  # the same bad status of the same duty is said again after this
RETAIN = dt.timedelta(days=30)  # an entry of a duty that is no longer opted in
MIN_LATE = dt.timedelta(minutes=30)  # a duty is deferred when this long after the fire that was its next run it has not run
BUSY_EVERY = dt.timedelta(minutes=5)  # a tick that finds the lock held looks for deferred duties at most this often
# The duties whose silence costs the user a resource: told on the desktop too, (role, duty).
NOTIFY = {("tollman", "prune"), ("tollman", "trains"), ("tollman", "mainred"), ("tollman", "watch")}
TIMED_OUT = re.compile(r"timed out|timeout", re.I)


def path(main: str, role: str) -> Path:
    return mtm_scan.state_dir(main, role) / FILE


def parse(text: str | None) -> dt.datetime | None:
    try:
        return dt.datetime.strptime(text or "", "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None


def local(t: dt.datetime) -> dt.datetime:
    """A naive local time (the cron's clock) from a naive or an aware one."""
    return t.astimezone().replace(tzinfo=None) if t.tzinfo else t


def aware(now: dt.datetime) -> dt.datetime:
    return now.astimezone()  # a naive time is this machine's local time


@contextlib.contextmanager
def locked(main: str, role: str):
    folder = path(main, role).parent
    with (folder / LOCK).open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def load(main: str, role: str) -> dict:
    try:
        data = json.loads(path(main, role).read_text())
    except (OSError, ValueError):
        data = None
    if not isinstance(data, dict) or not isinstance(data.get("duties"), dict):
        return {"schema": SCHEMA, "duties": {}}
    return data


def save(main: str, role: str, data: dict) -> None:
    f = path(main, role)
    tmp = f.with_name(f.name + ".tmp")
    tmp.write_text(json.dumps({**data, "schema": SCHEMA}, indent=1, sort_keys=True) + "\n")
    os.replace(tmp, f)


def crashed(name: str, error: Exception) -> list[dict]:
    """The actions of a duty whose handler raised (tick.item_actions): the round goes on, the failure is the
    duty's status."""
    status = "timeout" if isinstance(error, subprocess.TimeoutExpired) else "failed"
    why = f"{type(error).__name__}: {error}"[:200]
    return [act(name, "duty-crashed", "record", text=f"duty {name} {status}: {why}", health=status, why=why)]


def status_of(actions: list[dict]) -> tuple[str, str]:
    """(status, why) of one due duty from its executed actions: ok, failed, timeout or deferred."""
    for a in actions:
        if a.get("health") in BAD:
            return a["health"], a.get("why") or a.get("text", "")
    for a in actions:
        if a["do"] == "run" and a.get("exit") and a["exit"] != OFFLINE:
            lines = (a.get("output") or "").strip().splitlines()
            last = lines[-1][:120] if lines else ""
            return ("timeout" if TIMED_OUT.search(a.get("output") or "") else "failed",
                    f"{a['kind']}: exit {a['exit']} {last}".strip())
    return "ok", ""


def expected_run(cron: str, last: dt.datetime, now: dt.datetime) -> dt.datetime | None:
    """The first fire time after the duty's last run, at or before `now` (within due.LOOKBACK): when it should have run."""
    parsed, t = due.parse_cron(cron), max(last, now - due.LOOKBACK).replace(second=0, microsecond=0)
    t += dt.timedelta(minutes=1)
    while t <= now:
        if due.fires_at(parsed, t):
            return t
        t += dt.timedelta(minutes=1)
    return None


def overdue(schedule: dict[str, str], last: dict[str, dt.datetime], now: dt.datetime) -> list[tuple[str, str]]:
    """The opted-in duties and tasks that ran before and have not run MIN_LATE after the fire that was their next
    run. A duty with no run yet is not late: the first round runs it."""
    out = []
    now = local(now)
    for name, cron in schedule.items():
        fire = expected_run(cron, local(last[name]), now) if name in last else None
        if fire is not None and now - fire >= MIN_LATE:
            out.append((name, f"due since {fire:%Y-%m-%d %H:%M}, not run for {int((now - fire).total_seconds() // 60)} min"))
    return out


def again(reported: dict | None, status: str, now: dt.datetime) -> bool:
    """Say it: a new status, or the same one after REPEAT."""
    at = parse((reported or {}).get("at"))
    return not reported or reported.get("status") != status or at is None or aware(now) - at >= REPEAT


def settle(main: str, role: str, results: dict[str, tuple[str, str]], schedule: dict, now: dt.datetime) -> list[dict]:
    """Count the round's results into duty-health.json; the duties to report (a bad status not said lately)."""
    stamp, reports = board.utc(now), []
    with locked(main, role):
        data = load(main, role)
        for name, (status, why) in results.items():
            e = data["duties"].setdefault(name, {"good": 0, "bad": 0})
            e["seen"], e["status"] = stamp, status
            if status == "ok":
                e.update(good=e.get("good", 0) + 1, last_good=stamp, bad=0, why="")
                e.pop("reported", None)
                continue
            e.update(why=why[:200], last_bad=stamp, bad=e.get("bad", 0) + 1)
            if again(e.get("reported"), status, now):
                e["reported"] = {"status": status, "at": stamp}
                reports.append({"duty": name, "status": status, "why": why, "good": e.get("good", 0),
                                "last_good": e.get("last_good")})
        gone = aware(now) - RETAIN
        data["duties"] = {n: e for n, e in data["duties"].items()
                          if n in schedule or (parse(e.get("seen")) or aware(now)) >= gone}
        save(main, role, data)
    return reports


def line(role: str, r: dict) -> str:
    good = f"last good run {r['last_good']}, {r['good']} good" if r["last_good"] else "no good run yet"
    return f"{role} duty {r['duty']} {r['status']}: {r['why'] or 'no reason given'} ({good})"[:board.TEXT_MAX]


def lookout_notifier(title: str, body: str, farm: str, watch: str) -> list[dict]:
    """The existing notify path: lookout's `notify.send` over the user's backends (desktop, Telegram). Loaded under a
    private name, its sibling `paths` taken from lookout's folder only while it imports."""
    folder = sibling("lookout") / "scripts"
    saved = sys.modules.pop("paths", None)
    sys.path.insert(0, str(folder))
    try:
        spec = importlib.util.spec_from_file_location("lookout_notify", folder / "notify.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.path.remove(str(folder))
        sys.modules.pop("paths", None)
        if saved is not None:
            sys.modules["paths"] = saved
    return mod.send(title, body, farm, watch, mod.backends_for(None, mod.paths.load_settings()))


def deliver(main: str, role: str, reports: list[dict], notifier=None) -> None:
    """Each report as a `note` on the role's board and, for a disk or production duty, a notification. Nothing here
    raises: a board that cannot be written or a notifier that fails is the report's loss, never a round's."""
    mine, to = board.own(main, role), (board.own(main, "farmer") if role == "tollman" else "-")
    for r in reports:
        text = line(role, r)
        board.safely(main, "duty report", board.post, "note", mine, to, role=role, text=text)
        short = r["duty"].removeprefix("duty:")
        if (role, short) not in NOTIFY:
            continue
        if notifier is None and os.environ.get(roles.UNDER_TEST):
            continue  # a test never opens a real notification
        with contextlib.suppress(Exception):
            (notifier or lookout_notifier)(f"{role}: {short} {r['status']}", text, Path(main).name, r["duty"])


def after_round(top: str, main: str, rnd: dict, now: dt.datetime, wiring: roles.Wiring, notifier=None) -> list[dict]:
    """Count and report one executed round (tick.rest): every due duty's status, and the duties that were due and
    did not run. Never raises."""
    try:
        by = defaultdict(list)
        for a in rnd["actions"]:
            by[a.get("item")].append(a)
        results = {i["name"]: status_of(by[i["name"]]) for i in rnd["due"]}
        schedule = due.schedule((Path(top) / wiring.role_file).read_text(), wiring.duties)[0]
        for name, why in overdue(schedule, due.last_runs(top, wiring.role), now):
            results.setdefault(name, ("deferred", why))
        reports = settle(main, wiring.role, results, schedule, now)
        deliver(main, wiring.role, reports, notifier)
        return reports
    except Exception:  # noqa: BLE001  (a report must never stop a round)
        return []


def busy(repo: str, wiring: roles.Wiring, now: dt.datetime | None = None, notifier=None) -> list[dict]:
    """A tick that found another one running (role_cli.run_tick, the tollman's minute pass): look for duties that
    are overdue because that round does not end, at most every BUSY_EVERY. Never raises."""
    now = now or dt.datetime.now()
    try:
        top = tick.toplevel(repo) or repo
        main = mtm_scan.main_checkout(top)
        role_file = Path(top) / wiring.role_file
        if not role_file.exists():
            return []
        with locked(main, wiring.role):
            data = load(main, wiring.role)
            checked = parse(data.get("busy_checked"))
            if checked and aware(now) - checked < BUSY_EVERY:
                return []
            save(main, wiring.role, {**data, "busy_checked": board.utc(now)})
        schedule = due.schedule(role_file.read_text(), wiring.duties)[0]
        results = {n: ("deferred", why) for n, why in overdue(schedule, due.last_runs(top, wiring.role), now)}
        reports = settle(main, wiring.role, results, schedule, now) if results else []
        deliver(main, wiring.role, reports, notifier)
        return reports
    except Exception:  # noqa: BLE001
        return []
