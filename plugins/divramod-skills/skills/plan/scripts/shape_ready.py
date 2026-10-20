"""`plan.py ready [--json]` on the one plan shape (hal2 plan 0376, design §2 A5, D19): what can start now, on both
levels, each by its own `schedule` (`serial` default, `waves`).

- Sub-plans (plan.md's `schedule`): serial, the first unfinished work sub-plan by number; waves, every unfinished,
  unassigned work sub-plan of the lowest unfinished wave whose `touches` no running sub-plan holds. A sub-plan runs
  when its steps derive `running` or `blocked`, or when it has a `who`. 99-uat is never ready before the landing.
- Steps of a sub-plan (its `schedule`): serial, the first unfinished step; waves, every open step of the lowest
  unfinished wave whose `touches` no running step holds.
- Each resource has room for one item, the machine resources `@vm` for two, `@ci` and `@land` for one.
- Who (D19): exactly one ready work sub-plan while the foreman runs none is `foreman`; otherwise each is a `servant`
  with its `create.py --from 30 --lead` command. Steps of a sub-plan the foreman runs are parallel `hand`s.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

import envelope
import parallel
import shape
import shape_names as names
import shape_new
from shape_names import StepRef

MACHINE = {"@vm": 2, "@ci": 1, "@land": 1}


class Room:
    """The resources the running items hold, and what one more item may take."""

    def __init__(self, held: list[list[str]]):
        self.used = Counter(r for touches in held for r in clean(touches))

    def blocker(self, touches: list[str]) -> str | None:
        return next((r for r in clean(touches) if self.used[r] >= MACHINE.get(r, 1)), None)

    def take(self, touches: list[str]) -> None:
        self.used.update(clean(touches))


def clean(touches: list[str]) -> list[str]:
    return [parallel.resource(t) for t in touches if parallel.resource(t)]


def wave(item) -> int:
    return item.doc.wave or 1


def pick(items: list, running: list, schedule: str, label, limit: int | None) -> tuple[list, list]:
    """(ready, waiting) of one level's unfinished, not running `items`; `label` names an item."""
    if not items and not running:
        return [], []
    unfinished = sorted(items + running, key=label)
    if schedule != "waves":
        first = unfinished[0]
        ready = [first] if any(first is i for i in items) else []
        return ready, [(i, f"serial: waits for {label(first)}") for i in items if i is not first]
    lowest = min(wave(i) for i in unfinished)
    room, ready, waiting = Room([i.doc.touches for i in running]), [], []
    for item in items:
        blocker = room.blocker(item.doc.touches)
        if wave(item) > lowest:
            waiting.append((item, f"wave {wave(item)} waits for wave {lowest}"))
        elif blocker:
            waiting.append((item, f"`{blocker}` is held by a running item"))
        elif limit is not None and len(ready) >= limit:
            waiting.append((item, "over --limit"))
        else:
            room.take(item.doc.touches)
            ready.append(item)
    return ready, waiting


def step_level(sub: shape.ShapeSubplan, limit: int | None) -> dict:
    ref = lambda s: str(StepRef(sub.id.number, s.number))  # noqa: E731
    left = [s for s in sub.steps if not names.finished(s.doc.status)]
    running = [s for s in left if s.doc.status in ("running", "blocked")]
    items = [s for s in left if s not in running]
    ready, waiting = pick(items, running, sub.doc.schedule or "serial", ref, limit)
    item = lambda s: {"ref": ref(s), "title": s.doc.title, "wave": s.doc.wave, "touches": s.doc.touches}  # noqa
    return {"schedule": sub.doc.schedule or "serial", "ready": [{**item(s), "who": "hand"} for s in ready],
            "running": [{**item(s), "status": s.doc.status} for s in running],
            "waiting": [{"ref": ref(s), "why": why} for s, why in waiting]}


def servant_command(root: Path, folder: Path, sub) -> str:
    model, effort, _ = shape_new.run_words(folder)
    lead = f"{root.resolve().name} {folder.name} {sub.id}"
    extra = (f" --model {model}" if model else "") + (f" --effort {effort}" if effort else "")
    return f'create.py --from 30 --lead "{lead}"{extra}'


def foremans(sub) -> bool:
    return sub.doc.who in (None, "foreman")


def subplan_level(root: Path, folder: Path, found: shape.Shape, schedule: str, limit: int | None) -> dict:
    left = [s for s in found.work() if s.derived() != "done"]
    running = [s for s in left if s.derived() in ("running", "blocked") or s.doc.who]
    ready, waiting = pick([s for s in left if s not in running], running, schedule, lambda s: str(s.id), limit)
    alone = len(ready) == 1 and not any(foremans(s) for s in running)
    out = []
    for sub in ready:
        entry = {"id": str(sub.id), "wave": sub.doc.wave, "touches": sub.doc.touches,
                 "who": "foreman" if alone else "servant"}
        if not alone:
            entry["command"] = servant_command(root, folder, sub)
        out.append(entry)
    waits = [{"id": str(s.id), "why": why} for s, why in waiting]
    uat = found.uat()
    if uat and uat.derived() != "done":
        waits.append({"id": str(uat.id), "why": "the user's checks: never ready before the landing"})
    return {"running": [{"id": str(s.id), "status": s.derived(), "who": s.doc.who} for s in running],
            "waiting": waits, "ready": out}


def ready(root: Path, folder: Path, limit: int | None = None, lead=None) -> dict:
    """The JSON of `ready --json` (design §2); in a sub-plan servant's field (`lead`) only its sub-plan's steps."""
    found = shape.load(folder)
    schedule = envelope.get((folder / "plan.md").read_text(), "schedule") or "serial"
    subplans = subplan_level(root, folder, found, schedule, limit)
    left = [s for s in found.work() if s.derived() != "done"]
    if lead is not None:
        runs = [s for s in left if s.id.number == lead.number]
    else:
        ids = {e["id"] for e in subplans["ready"] if e["who"] == "foreman"}
        runs = [s for s in left if str(s.id) in ids or (foremans(s) and s.derived() in ("running", "blocked"))]
    return {"plan": folder.name, "schedule": schedule, "wave": min((wave(s) for s in left), default=None),
            "steps": {str(s.id): step_level(s, limit) for s in runs}, "subplans": subplans}


def lines(result: dict) -> list[str]:
    """`ready` without --json: a line per ready sub-plan and step."""
    out = [f"subplan\t{e['id']}\t{e['who']}" + (f"\t{e['command']}" if e.get("command") else "")
           for e in result["subplans"]["ready"]]
    out += [f"step\t{s['ref']}\t{s['title']}" for level in result["steps"].values() for s in level["ready"]]
    return out or ["nothing ready"]
