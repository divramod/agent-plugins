#!/usr/bin/env python3
"""The farmer's duty `autopilot` (hal2 plan 0543 step 24; plan 0695 step 8, D4, D13, D21, D27).

The daemon ticks the foreman limit by itself (`hal2-agents-node`'s loop, every `interval_s`, single flight per farm) and
journals every act in `<state>/agents/autopilot-journal.jsonl`; it writes a heartbeat `autopilot-heartbeat.json` after
every round. This duty, every 15 minutes:

  - copies the journal's new records of this farm into the farmer's `log.jsonl` (`copy`, once per record: its key
    `journal:<at>:<field>:<action>`);
  - runs the limit itself (a `run` of `hal2-cli-agents autopilot tick`, its starts) only when the heartbeat is older
    than 3 intervals (or missing): the daemon does not tick. With a fresh heartbeat only the dry tick's tollman tell
    (the hitch threshold's train order) is relayed; a busy tick (exit 1 "another autopilot tick of <repo> runs")
    means the daemon ticks and is no failure (`tick`);
  - wakes the farmer and pushes a notice (`alarm.py`) once for a freeze open over 90 min while no Mac job runs.

  autopilot_duty.py copy --repo-dir <main>        copy the new journal records into the farmer's log
  autopilot_duty.py tick --repo-dir <main> ...    `hal2-cli-agents autopilot tick --json ...`, busy is exit 0
"""

import datetime as dt
import json
import os
import sys
from pathlib import Path

import roletime
from tick import act, read_log

HERE = Path(__file__).resolve().parent
AUTOPILOT = ["hal2-cli-agents", "autopilot", "tick", "--json"]
ORDER_KINDS = {"unhitched", "fix-order", "stack-red-fix", "early-order", "triage-order", "post-order"}
ORDER_AGE = dt.timedelta(hours=6)  # a tollman order this young overrides the limit (field 44, 2026-10-31)
START_WINDOW = 15 * 60
FREEZE_LONG = dt.timedelta(minutes=90)  # a freeze open this long without a Mac job is stuck
COPY_AGE = dt.timedelta(days=3)  # older journal records are not copied (a first round copies no history)
COPY_MAX = 200
INTERVAL = 60  # the store's default `interval_s`
BUSY = "another autopilot tick of"
JOURNAL, HEARTBEAT = "autopilot-journal.jsonl", "autopilot-heartbeat.json"
_UNSET = object()


def tollman_orders(log: list[dict], now: dt.datetime) -> list[str]:
    """The fields with a tollman order (unhitched, a fix order) in the tollman's log within ORDER_AGE of `now`."""
    cut, out = roletime.aware(now) - ORDER_AGE, set()
    for e in log:
        at, slot = roletime.parse(e.get("at")), str(e.get("slot", ""))
        if e.get("kind") in ORDER_KINDS and at and at >= cut and slot.isdigit():
            out.add(slot)
    return sorted(out)


def autopilot_argv(main: str, orders: list[str], dry: bool) -> list[str]:
    spare = [w for f in orders for w in ("--spare", f)]
    return AUTOPILOT + ["--repo-dir", main] + spare + (["--dry-run"] if dry else [])


def records_dir() -> Path:
    """`<state>/agents`, as hal2_core::paths::state_root finds it (HAL2_STATE_DIR, XDG_STATE_HOME, the home)."""
    if os.environ.get("HAL2_STATE_DIR"):
        root = Path(os.environ["HAL2_STATE_DIR"])
    elif os.environ.get("XDG_STATE_HOME"):
        root = Path(os.environ["XDG_STATE_HOME"]) / "hal2"
    else:
        root = Path(os.environ.get("HAL2_HOME") or Path.home()) / ".local" / "state" / "hal2"
    return root / "agents"


def beats(folder: Path) -> dict | None:
    try:
        b = json.loads((folder / HEARTBEAT).read_text())
    except (OSError, ValueError):
        return None
    return b if isinstance(b, dict) and b.get("schema") == 1 else None


def journal(folder: Path, repo: str) -> list[dict]:
    """The journal's records of `repo`, oldest first; a line of another schema or unreadable is skipped."""
    out = []
    try:
        lines = (folder / JOURNAL).read_text().splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if isinstance(r, dict) and r.get("schema") == 1 and r.get("repo") == repo:
            out.append(r)
    return out


def view_of(main: str, now: dt.datetime, interval_s: int = INTERVAL, folder: Path | None = None) -> dict:
    """What the daemon left: `age` of its heartbeat in seconds (None: no heartbeat), the farm's last `mode`, the
    farm's journal `records`."""
    folder, repo, now = folder or records_dir(), Path(main).name, roletime.aware(now)
    b = beats(folder)
    at = roletime.parse(b["at"]) if b else None
    mode = ((b or {}).get("farms", {}).get(repo) or {}).get("mode", "")
    return {"age": (now - at).total_seconds() if at else None, "interval_s": interval_s, "mode": mode,
            "records": journal(folder, repo)}


def alive(view: dict) -> bool:
    """The daemon ticks: its heartbeat is at most 3 intervals old."""
    return view["age"] is not None and view["age"] <= 3 * max(view["interval_s"], 30)


def key_of(r: dict) -> str:
    return f"journal:{r['at']}:{r.get('field', '')}:{r['action']}"


def new_records(view: dict, log: list[dict], now: dt.datetime) -> list[dict]:
    """The journal's records of the last COPY_AGE not yet in the farmer's log (by key), at most COPY_MAX."""
    seen, cut = {e.get("key") for e in log if e.get("key")}, roletime.aware(now) - COPY_AGE
    fresh = [r for r in view["records"] if (roletime.parse(r.get("at")) or cut) >= cut and key_of(r) not in seen]
    return fresh[-COPY_MAX:]


def log_entry(r: dict) -> dict:
    note = f"{r.get('outcome', '')} by {r.get('by', '')}, trigger {r.get('trigger') or '-'}"
    return {"kind": "journal-" + r["action"], "slot": r.get("field") or "-", "what": r.get("why", ""),
            "note": note + (f": {r['error']}" if r.get("error") else ""), "by": "autopilot", "duty": "autopilot",
            "do": "journal", "key": key_of(r)}


def stuck_freezes(view: dict, now: dt.datetime) -> list[dict]:
    """Freeze records still open (no later thaw of the field) older than FREEZE_LONG while no Mac job runs."""
    if view["mode"] == "ci":
        return []
    last: dict[str, dict] = {}
    for r in view["records"]:
        if r["action"] in ("freeze", "thaw") and r.get("outcome") != "failed":
            last[r.get("field", "")] = r
    now = roletime.aware(now)
    return [r for r in last.values() if r["action"] == "freeze"
            and (at := roletime.parse(r.get("at"))) and now - at > FREEZE_LONG]


def journal_acts(main: str, view: dict, log: list[dict], now: dt.datetime) -> list[dict]:
    out = []
    if new_records(view, log, now):
        out.append(act("autopilot", "journal", "run", "-", cwd=main, text="copy the daemon's journal into the log",
                       argv=[sys.executable, str(HERE / "autopilot_duty.py"), "copy", "--repo-dir", main]))
    for r in stuck_freezes(view, now):
        f, key = r.get("field") or "-", f"autopilot:freeze-stuck:{r.get('field', '')}:{r['at']}"
        why = (f"field {f} is frozen since {r['at']} (over 90 min) and no Mac job runs: the thaw did not come "
               f"(trigger {r.get('trigger') or '-'}, daemon heartbeat {'alive' if alive(view) else 'DEAD'})")
        out.append(act("autopilot", "freeze-stuck", "wake", f, key=key + ":wake", text=why))
        out.append(act("autopilot", "freeze-alarm", "run", f, key=key + ":alarm", text="notice: " + why,
                       argv=[sys.executable, str(HERE / "alarm.py"), "autopilot-freeze", why, "--repo", main,
                             "--slot", f]))
    return out


def interval_of(main: str) -> int:
    """The farm's `interval_s` from `hal2-cli-agents autopilot show --json`; the default when unreadable."""
    import bounded
    import subprocess
    try:
        p = bounded.run(["hal2-cli-agents", "autopilot", "show", "--json"], cwd=main, other=60)
        n = json.loads(p.stdout).get("farm", {}).get("interval_s") if p.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, ValueError, AttributeError):
        n = None
    return n if isinstance(n, int) and n > 0 else INTERVAL


def dry_tick(main: str, orders: list[str]):
    """The dry tick's report; None when unreadable or busy (the daemon holds the farm: it ticks)."""
    import bounded
    import subprocess
    try:
        p = bounded.run(autopilot_argv(main, orders, True), cwd=main, other=120)
        return json.loads(p.stdout) if p.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def tick_acts(main: str, ctx: dict, report: dict, orders: list[str], limit: bool) -> list[dict]:
    """The report as acts: with `limit` (the daemon does not tick) the real tick and a `run` per start; always the
    train order, sent to the tollman (relayed when it is busy)."""
    changes, out = report.get("changes", []), []
    moves = [c for c in changes if c.get("action") in ("freeze", "thaw")]
    if limit and moves:
        what = ", ".join(f"{c['action']} {c['field']}" for c in moves)
        out.append(act("autopilot", "limit", "run", "-", text=f"foreman limit ({report.get('mode')}): {what}",
                       argv=[sys.executable, str(HERE / "autopilot_duty.py"), "tick"]
                       + autopilot_argv(main, orders, False)[len(AUTOPILOT):]))
    for c in (c for c in changes if limit and c.get("action") == "start" and c.get("argv")):
        out.append(act("autopilot", "start", "run", c["field"], argv=c["argv"], key=f"autopilot:start:{c['field']}",
                       window=START_WINDOW, text=f"start foreman {c['field']}: {c.get('why', '')}"))
    tell = report.get("tell_tollman")
    if isinstance(tell, dict) and tell.get("key"):
        toll = f"tollman-{report.get('repo') or Path(main).name}"
        out.append(act("autopilot", "train", "send", toll, pane=ctx.get("panes", {}).get(toll), to=toll,
                       key=tell["key"], text=tell.get("text", "")))
    return out


def plan_autopilot(item: dict, ctx: dict, report=_UNSET, orders: list[str] | None = None, view=_UNSET) -> list[dict]:
    """Journal copy and stuck-freeze alarm every round; the limit's own tick only while the daemon's heartbeat is
    stale. An unreadable tick plans no tick act (duty_health sees no failed run; the next round asks again)."""
    main = ctx["main"]
    view = view_of(main, ctx["now"], interval_of(main)) if view is _UNSET else view
    out = journal_acts(main, view, ctx.get("log", []), ctx["now"])
    orders = orders if orders is not None else tollman_orders(read_log(main, "tollman"), ctx["now"])
    report = dry_tick(main, orders) if report is _UNSET else report
    if not isinstance(report, dict) or report.get("schema") != 1:
        return out
    return out + tick_acts(main, ctx, report, orders, not alive(view))


def copy(main: str, log=None, now: dt.datetime | None = None, folder: Path | None = None) -> int:
    """Copy the new journal records into the farmer's log; the number copied. Idempotent by key."""
    import mtm_scan
    now = now or roletime.utcnow()
    view = view_of(main, now, folder=folder)
    rows = new_records(view, read_log(main), now)
    for r in rows:
        (log or mtm_scan.log)(main, log_entry(r))
    return len(rows)


def tick(argv: list[str]) -> int:
    """The tick; another tick holding the farm (the daemon's) is the daemon ticking, no failure."""
    import bounded
    p = bounded.run(AUTOPILOT + argv, other=120)
    if p.returncode == 1 and BUSY in (p.stderr or "") + (p.stdout or ""):
        print("autopilot: the daemon ticks this farm (its tick holds the lock)")
        return 0
    sys.stdout.write(p.stdout or "")
    sys.stderr.write(p.stderr or "")
    return p.returncode


def main(argv: list[str]) -> int:
    if argv[:1] == ["tick"]:
        return tick(argv[1:])
    if len(argv) == 3 and argv[:2] == ["copy", "--repo-dir"]:
        print(f"copied {copy(argv[2])} journal records")
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
