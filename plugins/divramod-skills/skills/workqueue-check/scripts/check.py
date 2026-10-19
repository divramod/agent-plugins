#!/usr/bin/env python3
"""workqueue-check: the work queue's numbers of a window against the window before, and the benchmarks against
their baseline; prints ranked findings. Read-only: it never runs a benchmark and never changes anything."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import findings as fx  # noqa: E402
import gather  # noqa: E402


def seconds(text: str) -> int:
    unit = {"m": 60, "h": 3600, "d": 86400}.get(text[-1:])
    if not unit or not text[:-1].isdigit() or int(text[:-1]) == 0:
        raise ValueError(f"--since {text}: an age like 30m, 24h or 7d")
    return int(text[:-1]) * unit


def doubled(text: str) -> str:
    return f"{seconds(text) * 2 // 60}m"


def collect(since: str, bench: bool, tolerance: float) -> dict:
    out = {"since": since, "findings": [], "notes": [], "missing": []}
    now_stats, why = gather.workqueue("stats", since, ("--by", "class"))
    if now_stats is None:
        out["missing"].append(why)
    else:
        wide_stats, why = gather.workqueue("stats", doubled(since), ("--by", "class"))
        now_report, _ = gather.workqueue("report", since, ("--top", "20"))
        wide_report, _ = gather.workqueue("report", doubled(since), ("--top", "20"))
        out["runs"] = now_stats.get("total", {}).get("runs", 0)
        if not out["runs"]:
            out["notes"].append("the journal has no runs in this window (nothing is measured yet, or the shims are not installed)")
        if wide_stats is not None:
            f, n = fx.compare_groups("class", now_stats.get("groups", []), wide_stats.get("groups", []), tolerance)
            out["findings"] += f
            out["notes"] += n
        if now_report and wide_report:
            heads = lambda r: [{**h, "key": f"{h.get('class')}:{h.get('key')}"} for h in r.get("heads", [])]  # noqa: E731
            f, n = fx.compare_groups("head", heads(now_report), heads(wide_report), tolerance)
            out["findings"] += f
            out["notes"] += n
            out["findings"] += fx.marks_findings(now_report.get("marks", {}), wide_report.get("marks", {}))
    if bench:
        result, why, code = gather.bench_compare()
        if result is None:
            out["notes"].append(f"benchmarks: {why}" if why else "benchmarks: no result")
        elif code == 1:
            out["findings"] += fx.bench_findings(result)
        elif code != 0:
            out["notes"].append(f"benchmarks: compare exited {code}")
    out["findings"] = fx.rank(out["findings"])
    return out


def human(res: dict) -> str:
    lines = [f"workqueue-check, window {res['since']} against the window before"]
    lines += [f"  missing: {m}" for m in res["missing"]]
    for i, f in enumerate(res["findings"], 1):
        if f["kind"] == "rose":
            lines.append(f"  {i}. {f['what']} rose {f['pct']}%: {f['was']} -> {f['is']} {f['unit']} ({f['runs']} runs)")
        elif f["kind"] == "marks":
            lines.append(f"  {i}. {f['what']}: {f['was']} -> {f['is']}")
        else:
            lines.append(f"  {i}. {f['what']} is slower than its baseline")
    if not res["findings"] and not res["missing"]:
        lines.append("  no finding: nothing rose past the tolerance")
    lines += [f"  note: {n}" for n in res["notes"]]
    return "\n".join(lines)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="workqueue-check", description=__doc__)
    p.add_argument("--since", default="24h", help="the window: 30m, 24h, 7d (default 24h)")
    p.add_argument("--tolerance", type=float, default=fx.TOLERANCE, help="a rise past this fraction is a finding")
    p.add_argument("--no-bench", action="store_true", help="skip the benchmarks against their baseline")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    try:
        seconds(args.since)
    except ValueError as err:
        print(err, file=sys.stderr)
        return 2
    res = collect(args.since, not args.no_bench, args.tolerance)
    print(json.dumps(res, indent=2) if args.json else human(res))
    if res["missing"]:
        return 3
    return 1 if res["findings"] else 0


if __name__ == "__main__":
    sys.exit(main())
