"""The tollman's metrics, the reading and the fold (split from metrics.py, hal2 plan 0467 step 10): the lines of
train.jsonl, board.jsonl and log.jsonl as aware UTC, and `fold_trains`: landings, reds with their cause, train
verdicts, hitch-to-barn and local-phase minutes, the local-phase load. Stdlib only; metrics.py re-exports every name."""

import datetime as dt
import json
import math
import statistics
from pathlib import Path

CAUSES = ("car", "barn", "engine", "runner", "unknown")
# Ordered: the first rule whose word is in the lower-cased text wins (data, so a learning can tune it).
CAUSE_RULES = (
    ("engine", ("not your code", "gate's own bug", "gate bug", "engine", "tollman", "non-fast-forward",
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
    reds, landed, tried, ever_red, phase, local = [], [], {}, set(), [], []
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
        elif kind == "pretest" and isinstance(e.get("local"), dict):
            local.append({"at": e["at"], "load": e["local"].get("load_peak"), "ops": e["local"].get("disk_ops_s")})
        elif kind == "run":
            if isinstance(e.get("local_phase_seconds"), (int, float)):
                phase.append((e["at"], e["local_phase_seconds"] / 60))
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
    return {"landed": landed, "reds": reds, "tried": tried, "hitch": hitch, "ever_red": ever_red, "phase": phase,
            "local": local}


def spread(values: list[float]) -> dict:
    """{n, median, p90} of minutes; the p90 is the nearest rank."""
    if not values:
        return {"n": 0, "median": None, "p90": None}
    v = sorted(values)
    return {"n": len(v), "median": round(statistics.median(v), 1), "p90": round(v[math.ceil(0.9 * len(v)) - 1], 1)}
