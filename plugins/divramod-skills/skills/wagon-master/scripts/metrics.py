#!/usr/bin/env python3
"""The wagon master's metrics as code (hal2 plan 0313 step 6, D9, D10): no model, read-only, for any role folder.

    python3 metrics.py --role <dir> [--since <day|time>] [--until <day|time>] [--json] [--offline] [--runs N]

Per UTC day and for the whole window (`since` inclusive, `until` exclusive, UTC; a bare day is its midnight):

  landings                  `landed` lines of `train.jsonl`
  trains                    trains whose landing was tried (a `started`, `red` or `landed` line)
  trains_per_landing        trains / landings
  first_try_green_rate      trains that landed without ever being red / trains with a verdict (landed, or red and
                            never landed); a train red once and landed after a retry is not first-try
  red_causes                {car, barn, engine, runner, unknown}: per red line, from `cause: <x>` in its text, else
                            the status `error` (engine), else the keywords of CAUSE_RULES over the red's why and the
                            reasons of the cars unhitched from that train (a car blamed: car)
  hitch_to_barn_min         {n, median, p90}: per landed car, its first ready mark (`board.jsonl`, else the first
                            train it rode) to the train's landing, minutes; a car unhitched starts again
  restarts, breakups, hand_fixes   `log.jsonl` counts (the legacy lines carry local time; hand_fixes are the
                            `train-failed` notes that are neither the red report nor an unhitch)
  runner_minutes_per_landing, queue_wait_min   from the ci-analyzer's runs (`main.py fetch --json`): the runner
                            minutes of the landing runs (`land/*` branches) per landing; the wait of their jobs for a
                            runner, and the part of it while a check run (any other branch) held a job on the same
                            kind of runner. None ("unknown") when the ci-analyzer is missing or fails.

`measure(role, since, until, ci=...)` is what the learn duty calls; `ci` is a callable `() -> list of trimmed runs`
(tests pass a fake). Stdlib only; imports no other module of the skill.
"""

import argparse
import datetime as dt
import json
import math
import os
import statistics
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CAUSES = ("car", "barn", "engine", "runner", "unknown")
# Ordered: the first rule whose word is in the lower-cased text wins (data, so a learning can tune it).
CAUSE_RULES = (
    ("engine", ("not your code", "gate's own bug", "gate bug", "engine", "wagon master", "non-fast-forward",
                "plan.sh", "force-push", "train state")),
    ("barn", ("barn is red", "main is red", "red on main", "red in the barn", "broken in main", "also red on main")),
    ("runner", ("runner", "cancelled", "timed out", "timeout", "no space left", "disk full", "lost communication",
                "offline", "out of memory")),
)


# ---- reading ----

def parse_time(text: str, local: bool = False) -> dt.datetime:
    """A time as aware UTC; a text without a zone is UTC, or this machine's local time when `local`."""
    t = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    if t.tzinfo is None:
        t = t.astimezone() if local else t.replace(tzinfo=dt.timezone.utc)
    return t.astimezone(dt.timezone.utc)


def read(path: Path, local: bool = False) -> list[dict]:
    """The lines of a JSONL file with `at` as aware UTC; a line that does not parse, or has no time, is skipped."""
    out = []
    for text in path.read_text().splitlines() if path.is_file() else []:
        try:
            row = json.loads(text)
            row["at"] = parse_time(row["at"], local)
        except (ValueError, KeyError, TypeError):
            continue
        if isinstance(row, dict):
            out.append(row)
    return sorted(out, key=lambda r: r["at"])


def day_of(t: dt.datetime) -> str:
    return t.strftime("%Y-%m-%d")


def in_window(t: dt.datetime, since, until) -> bool:
    return (since is None or t >= since) and (until is None or t < until)


# ---- the trains ----

def cause_of(status: str | None, texts: list[str]) -> str:
    """The cause class of a red train (see the module doc)."""
    low = " ".join(texts).lower()
    for cause in CAUSES[:4]:
        if f"cause: {cause}" in low:
            return cause
    if status == "error":
        return "engine"
    for cause, words in CAUSE_RULES:
        if any(w in low for w in words):
            return cause
    return "car" if any(t.strip() for t in texts[1:]) else "unknown"


def fold_trains(rows: list[dict], board: list[dict]) -> dict:
    """The train lines folded into events: landings, reds (with cause), train verdicts, hitch-to-barn minutes."""
    reds, landed, tried, ever_red = [], [], {}, set()
    texts: dict = {}  # a train's latest red -> [why, the reasons of its unhitched cars]
    ready: dict = {}  # field -> when it first rode or was ready since it last left
    hitch = []
    for e in sorted(rows + [dict(b, board=True) for b in board if b.get("kind") == "ready"], key=lambda r: r["at"]):
        kind, train, field = e["kind"], e.get("train"), e.get("slot")
        if e.get("board"):
            ready.setdefault(field, e["at"])
        elif kind == "formed":
            for car in e.get("cars", []):
                ready.setdefault(car["field"] if isinstance(car, dict) else car, e["at"])
        elif kind == "started":
            tried.setdefault(train, e["at"])
        elif kind == "red":
            tried.setdefault(train, e["at"])
            ever_red.add(train)
            reds.append({"at": e["at"], "train": train, "status": e.get("status")})
            texts[train] = [e.get("why", "")]
            reds[-1]["texts"] = texts[train]
        elif kind == "unhitched":
            ready.pop(field, None)
            if train in texts:
                texts[train].append(e.get("why", ""))
        elif kind == "landed":
            tried.setdefault(train, e["at"])
            landed.append({"at": e["at"], "train": train, "first_try": train not in ever_red})
            for car in e.get("cars", []):
                if car in ready:
                    hitch.append((e["at"], (e["at"] - ready.pop(car)).total_seconds() / 60))
    for r in reds:
        r["cause"] = cause_of(r["status"], r["texts"])
    return {"landed": landed, "reds": reds, "tried": tried, "hitch": hitch, "ever_red": ever_red}


def spread(values: list[float]) -> dict:
    """{n, median, p90} of minutes; the p90 is the nearest rank."""
    if not values:
        return {"n": 0, "median": None, "p90": None}
    v = sorted(values)
    return {"n": len(v), "median": round(statistics.median(v), 1), "p90": round(v[math.ceil(0.9 * len(v)) - 1], 1)}


def train_metrics(f: dict, log: list[dict], keep) -> dict:
    """The metrics of the lines `keep(at)` accepts."""
    landed = [x for x in f["landed"] if keep(x["at"])]
    landed_trains = {x["train"] for x in f["landed"]}
    tried = {t for t, at in f["tried"].items() if keep(at)}
    reds = [r for r in f["reds"] if keep(r["at"])]
    # The trains with a verdict here: landed, or red here and never landed.
    verdict = {x["train"] for x in landed} | {r["train"] for r in reds if r["train"] not in landed_trains}
    first = {x["train"] for x in landed if x["first_try"]}
    mine = [r for r in log if keep(r["at"])]
    kinds = [r.get("kind") for r in mine]
    notes = [r for r in mine if r.get("kind") == "train-failed"
             and not str(r.get("what", "")).startswith(("unhitched", "train "))]
    return {
        "landings": len(landed), "trains": len(tried),
        "trains_per_landing": round(len(tried) / len(landed), 2) if landed else None,
        "first_try_green_rate": round(len(first) / len(verdict), 2) if verdict else None,
        "red_causes": {c: sum(1 for r in reds if r["cause"] == c) for c in CAUSES},
        "hitch_to_barn_min": spread([m for at, m in f["hitch"] if keep(at)]),
        "restarts": kinds.count("restart"), "breakups": kinds.count("breakup"), "hand_fixes": len(notes),
    }


# ---- the ci-analyzer ----

class CiUnknown(Exception):
    """The ci-analyzer is missing or failed: its metrics are unknown."""


def analyzer_for(role: Path) -> Path | None:
    """main.py of the ci-analyzer: $HAL_CI_ANALYZER, the role folder's repository, else this skill's."""
    rel = Path("code/python/scripts/ci-analyzer/main.py")
    found = [Path(os.environ["HAL_CI_ANALYZER"])] if os.environ.get("HAL_CI_ANALYZER") else []
    found += [role.resolve().parents[1] / rel] if len(role.resolve().parents) > 1 else []
    found += [HERE.parents[6] / rel] if len(HERE.parents) > 6 else []
    return next((p for p in found if p.is_file()), None)


def fetch_ci(role: Path, offline: bool = False, runs: int = 100) -> list[dict]:
    """The ci-analyzer's trimmed runs (`main.py fetch --json`, read-only, its own cache); CiUnknown on any fault."""
    main = analyzer_for(role)
    if not main:
        raise CiUnknown("no ci-analyzer found (code/python/scripts/ci-analyzer/main.py)")
    cmd = [sys.executable, str(main), "fetch", "--json", "--runs", str(runs)] + (["--offline"] if offline else [])
    try:
        done = subprocess.run(cmd, cwd=main.parent, capture_output=True, text=True, timeout=180)
        if done.returncode:
            raise CiUnknown(f"ci-analyzer failed: {(done.stderr or done.stdout).strip()[-200:]}")
        return json.loads(done.stdout)["runs"]
    except (OSError, subprocess.SubprocessError, ValueError, KeyError) as error:
        raise CiUnknown(f"ci-analyzer failed: {error}") from error


def ci_metrics(runs: list[dict], landings: int, keep) -> dict:
    """Runner minutes and queue waits of the landing runs (`land/*`) among the runs `keep(started)` accepts."""
    def at(text):
        return parse_time(text) if text else None
    land = [r for r in runs if str(r.get("head_branch", "")).startswith("land/")]
    checks = [r for r in runs if r not in land]
    busy = [(at(j.get("started_at")), at(j.get("completed_at")), frozenset(j.get("labels") or []))
            for r in checks for j in r.get("jobs", []) if j.get("runner_name") and j.get("started_at")]
    runner = wait = behind = 0.0
    for r in land:
        if not keep(at(r.get("started_at") or r.get("created_at"))):
            continue
        for j in r.get("jobs", []):
            if not (j.get("runner_name") and j.get("started_at") and j.get("completed_at")):
                continue
            begin, end = at(j["started_at"]), at(j["completed_at"])
            runner += (end - begin).total_seconds() / 60
            made = at(j.get("created_at")) or begin
            waited = max((begin - made).total_seconds() / 60, 0.0)
            wait += waited
            labels = frozenset(j.get("labels") or [])
            if waited and labels and any(b[2] == labels and b[0] < begin and (b[1] is None or b[1] > made)
                                         for b in busy):
                behind += waited
    return {"runner_minutes": round(runner, 1), "queue_wait_min": {"total": round(wait, 1),
            "behind_checks": round(behind, 1)},
            "runner_minutes_per_landing": round(runner / landings, 1) if landings else None}


UNKNOWN_CI = {"runner_minutes": None, "queue_wait_min": None, "runner_minutes_per_landing": None}


# ---- the whole ----

def measure(role, since=None, until=None, ci=None) -> dict:
    """{window, ci, total, days}: the metrics of the role folder per UTC day and over the whole window.
    `ci` is a callable returning the ci-analyzer's runs; None: the ci-analyzer is run as a CLI."""
    role = Path(role)
    rows, log, board = read(role / "train.jsonl"), read(role / "log.jsonl", local=True), read(role / "board.jsonl")
    f = fold_trains(rows, board)
    status = {"status": "ok"}
    try:
        runs = (ci or (lambda: fetch_ci(role)))()
    except CiUnknown as error:
        runs, status = None, {"status": "unknown", "why": str(error)}
    except Exception as error:  # a fake or a caller's function may fail any way: the rest still computes
        runs, status = None, {"status": "unknown", "why": f"ci-analyzer failed: {error}"}
    if runs is not None:
        first = [parse_time(r["created_at"]) for r in runs if r.get("created_at")]
        status.update(runs=len(runs), first_run=min(first).isoformat().replace("+00:00", "Z") if first else None)
        status["partial"] = bool(since and first and min(first) > since)
    times = [r["at"] for r in rows + log] + [parse_time(r["created_at"]) for r in runs or [] if r.get("created_at")]
    lo, hi = since or (min(times) if times else None), until
    if hi is None and times:
        hi = max(times) + dt.timedelta(seconds=1)

    def bucket(keep):
        m = train_metrics(f, log, keep)
        m.update(ci_metrics(runs, m["landings"], keep) if runs is not None else UNKNOWN_CI)
        return m
    days: dict = {}
    d = lo.replace(hour=0, minute=0, second=0, microsecond=0) if lo else None
    while d and hi and d < hi:
        end = d + dt.timedelta(days=1)
        lo_d, hi_d = max(d, since or d), min(end, hi)
        days[day_of(d)] = bucket(lambda t, a=lo_d, b=hi_d: t is not None and a <= t < b)
        d = end

    def stamp(t):
        return t.isoformat().replace("+00:00", "Z") if t else None
    return {"window": {"since": stamp(lo), "until": stamp(hi)}, "ci": status,
            "total": bucket(lambda t: t is not None and in_window(t, lo, hi)), "days": days}


def line(name: str, m: dict) -> str:
    def v(x):
        return "unknown" if x is None else x
    h, w = m["hitch_to_barn_min"], m["queue_wait_min"]
    return (f"{name}: landings {m['landings']}, trains {m['trains']} ({v(m['trains_per_landing'])}/landing), "
            f"first-try green {v(m['first_try_green_rate'])}, red {m['red_causes']}, hitch-to-barn median "
            f"{v(h['median'])} p90 {v(h['p90'])} min (n {h['n']}), runner min/landing "
            f"{v(m['runner_minutes_per_landing'])}, queue wait {v(w and w['total'])} min "
            f"(behind checks {v(w and w['behind_checks'])})")


def main(argv=None, ci=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--role", required=True, help="the role folder (roles/wagon-master)")
    p.add_argument("--since", help="UTC day or time, inclusive")
    p.add_argument("--until", help="UTC day or time, exclusive")
    p.add_argument("--json", action="store_true")
    p.add_argument("--offline", action="store_true", help="the ci-analyzer reads its cache only")
    p.add_argument("--runs", type=int, default=100, help="the ci-analyzer's newest N runs")
    a = p.parse_args(argv)
    role = Path(a.role)
    if not role.is_dir():
        sys.exit(f"metrics: no role folder {role}")
    out = measure(role, parse_time(a.since) if a.since else None, parse_time(a.until) if a.until else None,
                  ci or (lambda: fetch_ci(role, a.offline, a.runs)))
    if a.json:
        print(json.dumps(out, indent=1, sort_keys=True))
        return 0
    print(f"window {out['window']['since']} .. {out['window']['until']}; ci-analyzer {out['ci']}")
    print("\n".join([line("total", out["total"])] + [line(d, m) for d, m in out["days"].items()]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
