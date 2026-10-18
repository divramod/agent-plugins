"""The tick (plan 0311 design.md, Timer "Tick"; D7, D10, D15, D16): what the 5-minute timer runs.

Under `tick.lock` (a second tick exits 0 "busy"; stale after 10 minutes): write `heartbeat`, rotate `tick.log`, then
per farm file and per record with a `check`: if the watch is active and `watchfile.due` says so, `runner.run_watch`
(check, dedupe, judge each new event); for every watch, due or not, retry the events pending at the judge and push
the finds that wait for the find path through `find.process` (record, apply, daybook item, notification). The
returned `alert` becomes a daybook item and a notification; an exit 11 ends the watch. Only the run keys go back into
the farm's file, under the store lock (D10). A quiet tick starts no model run: the judge is reached only from a new
event of a watch with `judge`, and a watch without pending state costs one small file read.

The runner keeps a judged find pending at step `find` in a shape of its own (`event` the whole event); `deliver_finds`
turns it into the arguments of `find.process`, which writes the finds.jsonl line. Stdlib only.
"""

import dataclasses
import functools
from typing import Any, Callable

import lookout_frame  # noqa: F401  (the farmer's and the daybook's scripts on the import path)
import find
import judge as judge_mod
import notify
import paths
import runner
import store
import timer
import watchfile
import watchstate

STALE_TICK = 600.0  # seconds: a tick lock older than this belongs to a dead tick


@dataclasses.dataclass
class Ctx:
    """What one tick needs; every part can be faked in a test."""
    now: Any
    judge_fn: Callable = None
    notifier: Callable = notify.send
    daybook: Any = None
    settings: dict = None
    log: Any = None
    env: dict = None

    def __post_init__(self):
        self.judge_fn = self.judge_fn or functools.partial(judge_mod.judge, log=self.log, env=self.env)


def deliver_finds(ctx, farm, record, state):
    """Push every find waiting for the find path through `find.process`; returns its results."""
    results = []
    for entry in [p for p in state["pending"] if p["step"] != "judge" and p.get("find")]:
        waiting = entry["find"]
        if entry["step"] == "find":  # the runner's shape: drop it, process builds the finds.jsonl line afresh
            state["pending"] = [p for p in state["pending"] if p is not entry]
            verdict, judged = waiting, bool(waiting.get("judged"))
        else:  # an earlier process() call kept the finished line at its step: it is used as it is
            verdict, judged = {}, True
        results.append(find.process(record, farm, entry["event"], verdict, state, judged=judged, now=ctx.now,
                                    settings=ctx.settings, daybook=ctx.daybook, notifier=ctx.notifier, log=ctx.log))
    return results


def raise_alert(ctx, farm, record, alert):
    """The alert of a watch that cannot be checked: one daybook item and one notification, both logged."""
    watch = str(record.get("id"))
    ok, error = find.jot(str(record.get("farm") or farm), f"{alert['message']} [lookout:{watch}]", ctx.daybook)
    settings = paths.load_settings() if ctx.settings is None else ctx.settings
    try:
        sent = ctx.notifier(f"Watch {record.get('title') or watch}", alert["message"], farm, watch,
                            notify.backends_for(record, settings))
    except Exception as exc:  # a notifier that raises is still only a log line
        sent = [{"backend": "?", "ok": False, "error": str(exc)}]
    paths.append_log({"kind": "alert", "at": ctx.now.isoformat(), "farm": farm, "watch": watch,
                      "cause": alert["cause"], "message": alert["message"], "daybook_ok": ok,
                      "daybook_error": error, "notify": sent}, ctx.log)


def _run_keys(keys, results):
    """The run keys after the find path: `found` (its title) or `pending` when a step is still to retry."""
    if results:
        keys = dict(keys, last_result=results[-1]["last_result"],
                    state="pending" if any(r["status"] == "pending" for r in results) else "found")
    return keys


def handle(ctx, farm, record, run_check):
    """One watch: the check when `run_check`, the retries and the find path always. Returns a report or None
    when there was nothing to do."""
    watch_dir = paths.watch_dir(farm, str(record["id"]))
    keys, end, alert, new = {}, False, None, 0
    if run_check:
        out = runner.run_watch(record, farm, watch_dir, now=ctx.now, env=ctx.env, judge_fn=ctx.judge_fn, log=ctx.log)
        keys, end, alert, new = out["record"], out["end"], out["alert"], out["new"]
    state = watchstate.load(watch_dir)
    if not run_check:
        if not state["pending"]:
            return None
        runner.retry_judges(record, farm, watch_dir, state, ctx.now, ctx.judge_fn)
        watchstate.save(watch_dir, state)
    results = deliver_finds(ctx, farm, record, state)
    if results or run_check:
        watchstate.save(watch_dir, state)
    if alert:
        raise_alert(ctx, farm, record, alert)
    keys = _run_keys(keys, results)
    if keys or end:
        store.update_run_keys(farm, str(record["id"]), keys, "check settled (exit 11)" if end else None, ctx.now)
    return {"farm": farm, "watch": record["id"], "checked": run_check, "state": keys.get("state"),
            "new": new, "delivered": sum(r["status"] == "done" for r in results),
            "pending": sum(r["status"] == "pending" for r in results), "alert": bool(alert), "ended": end}


def watches(now):
    """[(farm, record, due)] of every record with a check in every farm file; due is True/False/None (bad cron)."""
    out = []
    for name, _path in store.farm_files():
        try:
            records = store.load(name)[1]
        except watchfile.YamlError as exc:
            out.append((name, {"id": "?", "unreadable": str(exc)}, False))
            continue
        for record in records:
            if record.get("check") and record.get("id"):
                try:
                    due = watchfile.due(record, now) if record.get("active", True) is not False else False
                except Exception:  # a record with odd values (cron not text, ...) is a bad cron, not a dead tick
                    due = None
                out.append((name, record, due))
    return out


def summary_line(at, reports, skipped):
    checked = sum(1 for r in reports if r["checked"])
    found = [f"{r['farm']}/{r['watch']}" for r in reports if r["new"] or r["delivered"]]
    extra = [f"alert {r['farm']}/{r['watch']}" for r in reports if r["alert"]]
    extra += [f"pending {r['farm']}/{r['watch']}" for r in reports if r["pending"]]
    extra += [f"ended {r['farm']}/{r['watch']}" for r in reports if r["ended"]] + skipped
    if not found and not extra:
        return f"{at} quiet ({checked} checked)"
    return f"{at} found {len(found)} ({checked} checked)" + "".join(f"; {x}" for x in found + extra)


def run_tick(ctx, keepalive=lambda: None):
    """One round over every farm; returns the printed line. The caller holds `tick.lock`; `keepalive` is called
    between watches so a long round does not look stale."""
    reports, skipped = [], []
    inner = ctx.judge_fn

    def judge_alive(*args, **kwargs):  # a watch with many events to judge runs minutes: keep the lock fresh
        keepalive()
        return inner(*args, **kwargs)

    ctx = dataclasses.replace(ctx, judge_fn=judge_alive)
    for farm, record, due in watches(ctx.now):
        keepalive()
        if record.get("unreadable"):
            skipped.append(f"unreadable {farm}.yaml: {record['unreadable']}")
            continue
        if due is None:
            skipped.append(f"bad cron {farm}/{record['id']}")
        try:
            report = handle(ctx, farm, record, due is True)
        except Exception as exc:  # one bad watch (any error in it) never stops the others
            skipped.append(f"error {farm}/{record.get('id')}: {type(exc).__name__}: {exc}")
            continue
        if report:
            reports.append(report)
    return summary_line(ctx.now.isoformat(), reports, skipped)


def plan_line(now):
    """`tick --dry-run`: the watches a tick would run now, and those with finds still pending."""
    lines = []
    for farm, record, due in watches(now):
        if record.get("unreadable"):
            lines.append(f"unreadable {farm}.yaml")
        elif due:
            lines.append(f"would run {farm}/{record['id']}")
        elif watchstate.load(paths.watch_dir(farm, str(record["id"])))["pending"]:
            lines.append(f"would retry pending {farm}/{record['id']}")
    return "\n".join(lines) or "nothing due"


def tick(ctx=None, dry_run=False):
    """The tick: returns the line to print (and exits 0 even when a watch failed: its state says so)."""
    ctx = ctx or Ctx(now=paths.now())
    if dry_run:
        return plan_line(ctx.now)
    state = paths.state_root()
    state.mkdir(parents=True, exist_ok=True)
    lock = store.Lock(state / "tick.lock", wait=0, stale=STALE_TICK)
    if not lock.acquire():
        return f"{ctx.now.isoformat()} busy: another tick is running"
    try:
        (state / "heartbeat").write_text(ctx.now.isoformat() + "\n", encoding="utf-8")
        timer.rotate(state)
        return run_tick(ctx, lock.touch)
    finally:
        lock.release()


def cmd_tick(args):
    print(tick(dry_run=args.dry_run))
    return 0
