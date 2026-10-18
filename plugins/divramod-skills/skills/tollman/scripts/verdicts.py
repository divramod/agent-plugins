#!/usr/bin/env python3
"""Before and after per learning (hal2 plan 0313 step 7, decisions D9 and D10): the duty `learn` measures whether a
role's rules helped. Generic: the role folder is the argument. Deterministic, no model call, stdlib only.

Each entry of `learnings.md` names when its rule took effect (`**Start:**`) and the number it should move
(`**Metric:**`, one of METRICS). Once its 7 days after the start are over (before the run's day), the 7 days before
are compared with the 7 after by `metrics.measure`: at least 5 trains on each side, else "not enough data yet"; a
move of 20% or more the metric's good way is "helped", the other way "worse", else "no change". The first verdict
is written into the entry: `**Status:** kept` (helped), `dropped` (worse: the rule is no longer applied) or `revise`
(no change: the next skill-change brief takes it with its numbers), with `**Verdict:**` holding the numbers. Every
run rewrites `stats.md` in the role folder: the day's summary metrics and one section per learning.

    verdicts.py --dir <role folder> [--today <UTC date>] [--offline] [--json]   the review, as the learn run does it
"""

import argparse
import datetime as dt
import json
import math
import sys
from pathlib import Path

import learnings
import metrics

STATS = "stats.md"
DAYS, MIN_TRAINS, MOVE = 7, 5, 0.20  # D10: the window, the trains each side needs, the move that counts
VERDICT_STATUS = {"helped": "kept", "worse": "dropped", "no change": "revise"}


def _red(cause):
    return lambda t: (t.get("red_causes") or {}).get(cause)


def _part(key, sub):
    return lambda t: (t.get(key) or {}).get(sub)


# name -> (good direction: +1 higher is better, -1 lower is better; its value in metrics.measure's `total`)
METRICS = {
    "landings": (1, lambda t: t.get("landings")),
    "first_try_green_rate": (1, lambda t: t.get("first_try_green_rate")),
    "trains_per_landing": (-1, lambda t: t.get("trains_per_landing")),
    "hitch_to_barn_median": (-1, _part("hitch_to_barn_min", "median")),
    "hitch_to_barn_p90": (-1, _part("hitch_to_barn_min", "p90")),
    "queue_wait_min": (-1, _part("queue_wait_min", "total")),
    "queue_wait_behind_checks": (-1, _part("queue_wait_min", "behind_checks")),
    "runner_minutes_per_landing": (-1, lambda t: t.get("runner_minutes_per_landing")),
    **{f"red_{c}": (-1, _red(c)) for c in metrics.CAUSES},
    **{k: (-1, lambda t, k=k: t.get(k)) for k in ("restarts", "breakups", "hand_fixes")},
}


def judge(before: dict, after: dict, metric: str) -> dict:
    """The verdict of one metric between two windows' totals: helped, worse, no change or not enough data yet."""
    good, value = METRICS[metric]
    b, a = value(before), value(after)
    out = {"metric": metric, "good": "higher" if good > 0 else "lower", "before": b, "after": a,
           "trains_before": before.get("trains", 0), "trains_after": after.get("trains", 0), "change": None}
    if out["trains_before"] < MIN_TRAINS or out["trains_after"] < MIN_TRAINS or a is None or b is None:
        return {**out, "verdict": "not enough data yet"}
    change = (a - b) / abs(b) if b else (0.0 if a == b else math.copysign(math.inf, a - b))
    out["change"] = change if math.isinf(change) else round(change, 4)
    way = good * out["change"]
    return {**out, "verdict": "helped" if way >= MOVE else "worse" if way <= -MOVE else "no change"}


def start_of(entry) -> dt.datetime | None:
    try:
        return metrics.parse_time(entry.fields.get("start", "").strip())
    except ValueError:
        return None


def once(ci):
    """The ci-analyzer asked at most once per review, its runs (or its fault) shared by every measure."""
    memo = {}

    def runs():
        if "runs" not in memo:
            try:
                memo["runs"] = ci()
            except Exception as error:  # noqa: BLE001  (measure says unknown for any fault)
                memo["error"], memo["runs"] = error, None
        if memo.get("error"):
            raise metrics.CiUnknown(str(memo["error"]))
        return memo["runs"]
    return runs


def assess(role_dir: Path, entry, cutoff: dt.datetime, measure, runs) -> dict:
    """One entry's state: unmeasured, unknown metric, measuring (window still open) or judged with its numbers."""
    base = {"n": entry.n, "slug": entry.slug, "rule": entry.rule or entry.case, "status": entry.status,
            "handed": entry.fields.get("handed", "")}
    metric, start = entry.fields.get("metric", "").strip(), start_of(entry)
    if not metric or start is None:
        return {**base, "verdict": "unmeasured", "why": "no Metric" if not metric else "no Start"}
    if metric not in METRICS:
        return {**base, "verdict": "unknown metric", "metric": metric}
    span = dt.timedelta(days=DAYS)
    base.update(metric=metric, start=_stamp(start), until=_stamp(start + span))
    if start + span > cutoff:
        return {**base, "verdict": "measuring"}
    before = measure(role_dir, start - span, start, ci=runs)["total"]
    after = measure(role_dir, start, start + span, ci=runs)["total"]
    return {**base, **judge(before, after, metric)}


def review(role_dir: Path, today: str, ci=None, measure=metrics.measure) -> list[dict]:
    """The day's review (learn.run's seam): every entry assessed, a first verdict written into its entry, stats.md
    rewritten. `ci` returns the ci-analyzer's runs (None: its CLI, once); returns the assessments."""
    role_dir = Path(role_dir)
    runs = once(ci or (lambda: metrics.fetch_ci(role_dir)))
    cutoff = metrics.parse_time(today)  # the run's day starts: the windows before it are whole
    found = [assess(role_dir, e, cutoff, measure, runs) for e in learnings.read(role_dir)]
    updates = {}
    for a in found:
        status = VERDICT_STATUS.get(a["verdict"])
        if status and not a["status"]:
            updates[a["n"]] = {"Status": f"{status} {today}", "Verdict": verdict_line(a)}
            a["status"], a["new"] = status, True
    if updates:
        learnings.set_fields(role_dir, updates)
    summary = measure(role_dir, cutoff - dt.timedelta(days=DAYS), cutoff, ci=runs)
    write_stats(role_dir, today, summary, found)
    return found


def _stamp(t: dt.datetime) -> str:
    return t.strftime("%Y-%m-%d %H:%MZ")


def _pct(change) -> str:
    if change is None:
        return "-"
    if math.isinf(change):
        return ("+" if change > 0 else "-") + "inf (from 0)"
    return f"{change * 100:+.0f}%"


def verdict_line(a: dict) -> str:
    """The numbers of a judged entry in one line."""
    return (f"{a['verdict']}: {a['metric']} ({a['good']} is better) {a['before']} -> {a['after']} "
            f"({_pct(a['change'])}), trains {a['trains_before']} before, {a['trains_after']} after, "
            f"{a['start']} ± {DAYS} days")


def section(a: dict) -> str:
    head = f"## L{a['n']} · {a['slug']} · {a['verdict']}"
    rows = [f"- Rule: {a['rule']}"]
    if a["verdict"] in ("unmeasured", "unknown metric"):
        rows.append(f"- Not measured: {a.get('why') or 'unknown metric ' + repr(a.get('metric'))}"
                    + f" (the metrics: {', '.join(METRICS)})" * (a["verdict"] == "unknown metric"))
    elif a["verdict"] == "measuring":
        rows.append(f"- Metric {a['metric']}, start {a['start']}: measured after {a['until']}")
    else:
        rows.append(f"- {verdict_line(a)}")
    if a["status"]:
        rows.append(f"- Status: {a['status']}" + (f", handed {a['handed']}" if a["handed"] else ""))
    return head + "\n\n" + "\n".join(rows)


def write_stats(role_dir: Path, today: str, summary: dict, found: list[dict]) -> None:
    role = role_dir.name
    days = "\n".join(f"- {metrics.line(day, m)}" for day, m in summary["days"].items() if m["trains"] or m["landings"])
    ci = summary["ci"]
    text = (f"---\ntype: Ledger\nschema: 1\nrole: {role}\ntitle: {role} stats\ndescription: The daily learn run's "
            f"before/after verdict per learning and the day's summary metrics (scripts/verdicts.py).\n"
            f"status: current\n---\n\n# {role} stats\n\nWritten by the learn run of {today}. "
            f"Window {DAYS} days before and after a rule's start, at least {MIN_TRAINS} trains each side, a move of "
            f"{MOVE * 100:.0f}% counts. The ci-analyzer: {ci.get('status')}"
            + (f" ({ci['why']})" if ci.get("why") else "") + ".\n\n"
            f"## Summary: the last {DAYS} days\n\n- {metrics.line('total', summary['total'])}\n"
            + (days + "\n" if days else "") + "\n"
            + "\n\n".join(section(a) for a in found) + ("\n" if found else ""))
    role_dir.mkdir(parents=True, exist_ok=True)
    tmp = role_dir / f".{STATS}.tmp"
    tmp.write_text(text)
    tmp.replace(role_dir / STATS)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dir", required=True, help="the role folder")
    p.add_argument("--today", help="the UTC date, default today")
    p.add_argument("--offline", action="store_true", help="the ci-analyzer's cache only")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    role = Path(args.dir)
    today = args.today or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    found = review(role, today, ci=lambda: metrics.fetch_ci(role, offline=args.offline))
    print(json.dumps(found, indent=1, default=str) if args.json else
          "\n".join(f"L{a['n']} {a['slug']}: {a['verdict']}" for a in found) or "no learnings")
    return 0


if __name__ == "__main__":
    sys.exit(main())
