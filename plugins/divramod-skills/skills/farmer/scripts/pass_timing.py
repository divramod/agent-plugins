#!/usr/bin/env python3
"""What one minute pass costs (hal2 plan 0480 step 01.03, D1): wall time, process starts and `gh` calls, one JSON line
per pass in `pass-timing.jsonl` of the role's state folder (roles/<role>/, gitignored with the other runtime files).

The tollman's minute pass (tollman minute.py) is no round: a quiet one prints nothing, so its cost goes to this file,
not to stdout (a round's `timing:` line is tick.timing_line). `begin()` starts the clock and counts every
`subprocess.Popen` construction (subprocess.run and check_output make one each, in any thread); the readers of GitHub
(mtm_scan.run, ci_scan.run) call `count_gh(args)` for each `gh` command they start; `finish(state)` stops both and
appends the record, keeping the last KEEP lines (count retention, about a day of 1-minute passes); `abandon()` stops
without a record (the tick turned out to be a round). Nothing is counted outside begin..finish.

  pass_timing.py summary [--file <path>] [--json]   median and p95 of wall_ms, procs and gh over the file's passes
"""

import argparse
import datetime as dt
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

FILE = "pass-timing.jsonl"
SCHEMA = 1
KEEP = 1440  # passes kept: a day of 1-minute passes
CHECK_BYTES = 100_000  # the file is read for trimming only past this size
FIELDS = ("wall_ms", "procs", "gh")

_lock = threading.Lock()
_pass: dict | None = None  # {"t0": float, "procs": int, "gh": int} while a pass is counted
_init = subprocess.Popen.__init__


def _counted(self, *args, **kwargs):
    with _lock:
        if _pass is not None:
            _pass["procs"] += 1
    _init(self, *args, **kwargs)


def begin() -> None:
    """Start timing and counting this pass (a second call starts it again)."""
    global _pass
    with _lock:
        _pass = {"t0": time.perf_counter(), "procs": 0, "gh": 0}
    subprocess.Popen.__init__ = _counted


def abandon() -> None:
    """Stop counting without a record."""
    global _pass
    subprocess.Popen.__init__ = _init
    with _lock:
        _pass = None


def count_gh(args) -> None:
    """One more `gh` command started, when `args` is one and a pass is counted."""
    if _pass is not None and list(args[:1]) == ["gh"]:
        with _lock:
            _pass["gh"] += 1


def record(now: dt.datetime | None = None) -> dict | None:
    """The counted pass as a record, None when none is counted."""
    if _pass is None:
        return None
    now = now or dt.datetime.now(dt.timezone.utc)
    return {"schema": SCHEMA, "at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "wall_ms": round((time.perf_counter() - _pass["t0"]) * 1000), "procs": _pass["procs"], "gh": _pass["gh"]}


def finish(state: Path, now: dt.datetime | None = None) -> dict | None:
    """Stop and append the record to `state/pass-timing.jsonl` (kept to the last KEEP lines); never raises."""
    rec = record(now)
    abandon()
    if rec is None:
        return None
    path = Path(state) / FILE
    try:
        with path.open("a") as f:
            f.write(json.dumps(rec) + "\n")
        if path.stat().st_size > CHECK_BYTES:
            trim(path)
    except OSError:
        pass
    return rec


def trim(path: Path, keep: int = KEEP) -> None:
    """Rewrite `path` with its last `keep` lines when it has more than a tenth over (atomic: tmp, then replace)."""
    lines = path.read_text().splitlines()
    if len(lines) > keep + keep // 10:
        tmp = path.with_name(f".{path.name}.tmp")
        tmp.write_text("\n".join(lines[-keep:]) + "\n")
        tmp.replace(path)


def read(path: Path) -> list[dict]:
    """The file's records; a line that does not parse is skipped."""
    out = []
    for text in path.read_text().splitlines() if path.exists() else []:
        try:
            row = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and all(isinstance(row.get(k), (int, float)) for k in FIELDS):
            out.append(row)
    return out


def summary(rows: list[dict]) -> dict:
    """{field: {median, p95}} and `passes`; p95 is the nearest rank."""
    import statistics  # the summary command only: a pass does not load it
    out: dict = {"passes": len(rows)}
    for k in FIELDS:
        vals = sorted(r[k] for r in rows)
        if vals:
            out[k] = {"median": statistics.median(vals), "p95": vals[min(len(vals) - 1, -(-95 * len(vals) // 100) - 1)]}
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("command", choices=["summary"])
    p.add_argument("--file", required=True, help="a pass-timing.jsonl")
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    s = summary(read(Path(a.file)))
    if a.json:
        print(json.dumps(s))
    else:
        print(f"{s['passes']} passes" + "".join(f"; {k} median {s[k]['median']:g} p95 {s[k]['p95']:g}"
                                                 for k in FIELDS if k in s))
    return 0


if __name__ == "__main__":
    sys.exit(main())
