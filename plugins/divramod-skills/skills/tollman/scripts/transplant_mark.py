"""The open transplant of a field (hal2 plan 0286, read by plan 0294 step 15, D29).

A transplant moves a foreman with its branch, plan and handoff from a source field to a target field and drives
the target itself. hal2-git keeps one JSON record per transplant (`hal2-cli-git worktree transplants --json`:
`{"transplants": [{"id", "from", "to", "state", "prepared", "driven", ...}]}`, newest first); it is open while its
`state` is `prepared` or `driven`. A prepared target also holds the marker `transplant-from-<source>` in its
`plans/CURRENT_PLAN`. The orphan rule (boss.py) leaves the source and the target of an open transplant alone, or
it would start a second `/handoff c` in a field the transplant is driving.

Read tolerantly: an installed CLI without the command, a failure or output that is not the contract answers no
record; only `from`, `to`, `state` and the times are used, so a newer writer's keys change nothing. The marker file
is the fallback for a target whose record cannot be read: it protects the field and has no age, so nothing is
reported. A mark older than STALE still protects both fields, however old (the transplant's command finishes it); the
tollman leaves the farmer a board note once instead (Mark.report, plan 0360 step 8; plan 0286 names no timeout, so
60 minutes).
"""

import dataclasses
import datetime as dt
from pathlib import Path

import farmer_frame  # noqa: F401  (puts the farmer skill's scripts on the path)
import mtm_scan

STALE = dt.timedelta(minutes=60)
OPEN = ("prepared", "driven")
ROLE = "tollman (transplants)"
MARKER = "transplant-from-"  # the prefix of a prepared target's plans/CURRENT_PLAN


@dataclasses.dataclass(frozen=True)
class Mark:
    """The open transplant a field is in: its record, or just the marker (no record: no id, no age)."""
    id: str
    src: str
    dst: str
    state: str
    prepared: str  # the record's own `prepared` text: the report's key stays the same every round
    age: dt.timedelta | None  # since the last state change; None for the marker alone

    @property
    def stale(self) -> bool:
        return self.age is not None and self.age > STALE

    @property
    def key(self) -> str:
        return f"transplant-stale:{self.src}:{self.dst}:{self.prepared}"

    def report(self) -> str:
        """The note the farmer reads once about an old open transplant."""
        n = int(self.age.total_seconds() // 60) if self.age else 0
        return (f"{ROLE}: transplant {self.src} to {self.dst} is {self.state} for {n} minutes, over "
                f"{int(STALE.total_seconds() // 60)}. Its fields are left alone. Finish it with `hal2-cli-git worktree "
                f"transplant {self.src} {self.dst}` again, or end it with `/transplant cancel {self.src}`.")


def history(main: str, call=None) -> list[dict]:
    """The repository's transplant records; [] when the command is missing or answers badly."""
    out = (call or mtm_scan.run_json)(["hal2-cli-git", "worktree", "transplants", "--json"], main)
    found = out.get("transplants") if isinstance(out, dict) else None
    return [t for t in found if isinstance(t, dict)] if isinstance(found, list) else []


def when(text) -> dt.datetime | None:
    """An RFC 3339 time as an aware datetime; None when missing or unreadable."""
    try:
        return dt.datetime.fromisoformat(str(text).replace("Z", "+00:00")).astimezone()
    except ValueError:
        return None


def aware(now: dt.datetime) -> dt.datetime:
    return now.astimezone()  # a naive time is the local one


def from_record(records: list[dict], slot: str, now: dt.datetime) -> Mark | None:
    """The newest open record that names `slot` as its source or target."""
    for t in records:
        if t.get("state") not in OPEN or slot not in (t.get("from"), t.get("to")):
            continue
        times = [x for x in (when(t.get("prepared")), when(t.get("driven"))) if x]
        # a record without a readable time cannot be aged: it is as old as it gets
        since = max(times) if times else aware(now) - STALE - dt.timedelta(seconds=1)
        return Mark(str(t.get("id") or "?"), str(t.get("from")), str(t.get("to")), str(t["state"]),
                    str(t.get("prepared") or ""), max(aware(now) - since, dt.timedelta(0)))
    return None


def from_marker(path: str) -> Mark | None:
    """A prepared target's `plans/CURRENT_PLAN` marker: it protects the field and has no age to report."""
    try:
        text = (Path(path) / "plans" / "CURRENT_PLAN").read_text().strip() if path else ""
    except OSError:
        return None
    if not text.startswith(MARKER):
        return None
    return Mark(text, text.removeprefix(MARKER), Path(path).name, "prepared", "", None)


def of(slot: str, path: str, records: list[dict], now: dt.datetime) -> Mark | None:
    """The open transplant of field `slot` (its folder `path`): the record's, else the marker's, else None."""
    return from_record(records, slot, now) or from_marker(path)
