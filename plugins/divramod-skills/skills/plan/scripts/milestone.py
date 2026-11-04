"""Milestone rows (hal2 plan 0592 D6-D8, plan 0593 step 3): any plan declares a milestone as a step row `Milestone <n>:
<what lands>`; a step that needs earlier code in main starts its done-when with `after milestone <n>:`. The hitch
kind (complete, milestone n/m, partial) is hal2-plans' (`hal2-cli-plans show --json`: hitch.py reads it); this
module reads the row forms and writes the one thing a script adds: `plan.py milestone --after <id> [--title ...]`
inserts a row with the next free id at that position (ids are never renumbered).

- `number(step)`: n of a Step cell that starts `Milestone <n>` (any case, after any marks), else None.
- `after(done_when)`: n of a done-when that starts `after milestone <n>`, else None.
- `insert(lines, after, title)`: the plan's lines with the new row below row `after`, and the row's id.
"""
import re

import table

ROW = re.compile(r"^\W*milestone\s+(\d+)", re.I)
AFTER = re.compile(r"^\W*after\s+milestone\s+(\d+)", re.I)
# an open row is sized (plan-steps-sized); a milestone is the foreman's landing, so the smallest valid values
SIZED = {"model": "haiku", "effort": "low", "window": "200k", "size": "5k"}


class MilestoneError(Exception):
    pass


def number(step: str) -> int | None:
    found = ROW.match(step)
    return int(found.group(1)) if found else None


def after(done_when: str) -> int | None:
    found = AFTER.match(done_when)
    return int(found.group(1)) if found else None


def insert(lines: list[str], after_id: str, title: str = "") -> tuple[list[str], str, int]:
    """(lines with the row, its id, its milestone number): `Milestone <n>: <title>` below row `after_id`, its id the
    highest integer id + 1, n one above the milestones at or above the position. A milestone below the position
    whose number would not rise is refused: milestone numbers rise down the table (0592 D7)."""
    header, cols = table.header(lines) or (None, None)
    if header is None:
        raise MilestoneError("no step table with columns '#', 'Step' and 'Status'")
    rows = table.rows(lines, header)
    ids = [cells[cols["#"]] for _, cells in rows]
    if after_id not in ids:
        raise MilestoneError(f"no step '{after_id}' in the plan: --after names the row the milestone follows")
    at = ids.index(after_id)
    numbers = [number(cells[cols["step"]]) for _, cells in rows]
    above = max((n for n in numbers[:at + 1] if n), default=0)
    below = [n for n in numbers[at + 1:] if n]
    if below and min(below) <= above + 1:
        raise MilestoneError(f"Milestone {above + 1} would not stay below Milestone {above} and above Milestone "
                             f"{min(below)}: milestone numbers rise down the table and are never renumbered; "
                             "give the later milestone a higher number first")
    n = above + 1
    new_id = str(max([int(i) for i in ids if i.isdigit()], default=0) + 1)
    values = {"#": new_id, "step": f"Milestone {n}: {title.strip() or 'what lands'}", "needs": "", "touches": "@land",
              "who": "lead", "done when": "the rows above are done and landed (`/mtm milestone`)", "status": ""}
    values.update(SIZED)
    width = max(cols.values()) + 1
    cells = [values.get(name, "") for name, _ in sorted(cols.items(), key=lambda kv: kv[1])]
    cells += [""] * (width - len(cells))
    row = table.join_row(cells) + table.eol(lines[rows[at][0]])
    out = list(lines)
    out.insert(rows[at][0] + 1, row)
    return out, new_id, n
