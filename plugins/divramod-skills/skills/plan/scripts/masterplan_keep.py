"""masterplan_keep.py: a masterplan over a clear and a bring in (hal2 plan 0275 step 5; its decisions D8, D14, D26,
D33 and D36).

- `tick`: when a plan with `parent` turns done, every row of its masterplan that links it is set `done` in the same
  checkout, and the tick is taken back (`running`: the plan is in work again) when a step reopens. plan.py's
  `stamp_finished` calls it for every changed cell and stamps the masterplan after it, so a row is `done` exactly
  when its plan's `status` is (hal2's rule `masterplan-rows`). It works with `--plan` too: a foreman marks a
  servant's plan from its own field. A tick that could not do so says why (`tick_skipped` of `plan.py status`).
- `leave`: what `plans/CURRENT_PLAN` holds after a bring in (`plan.py leave`, the mtm skill's step 6): the slug of
  the finished plan's unfinished masterplan, else nothing (the file is deleted); a plan with open steps keeps it.
  `--release`: the field does not carry on with the masterplan, the file is deleted.
- `finishable`: the plans of a masterplan whose open steps are all checked after the landing (`after_landing` of
  `plan.py masterplan --json`): the mtm skill finishes them after a bring in, each with `status --plan`.

Like masterplan.py it imports no plan.py (that runs as `__main__`): plan.py passes it its reader of a plan's steps.
"""
import re
from pathlib import Path

import masterplan
import occupied
import shape
import table

MAIN = masterplan.MAIN
DONE = "done"
REOPENED = "running"
POINTER = "plans/CURRENT_PLAN"
ROW_DONE = re.compile(r"done(?: \(.*\))?")  # a finished row's two forms: `done`, `done (<note>)`


def is_done(status: str) -> bool:
    return status.lower().startswith(DONE)


def tick(path: Path) -> dict | None:
    """Hold every row of the masterplan that links the plan at `path` to the plan's `status`: `done` when the plan
    is, whatever the row read (a `done (<note>)` keeps its note); `running` when the plan is open and the row reads
    `done` or `done (<note>)`. A row at `blocked <why>`, `draft`, `next` or blank stays as it is while its plan is
    open. The result: {masterplan, row, status} for a written tick (`row`: every row written, `, ` between two),
    and `skipped`, why the tick did not hold a row: the parent's folder is not in this checkout, no row links the
    plan, or a row's cells are not the header's (table.misfit: such a row is never written). None when there is
    nothing to do or say: a plan of no masterplan, an abandoned one, rows that agree already."""
    if path.name != MAIN:
        return None
    text, slug = masterplan.read(path), masterplan.slug_of(path)
    parent, status = masterplan.parent_of(text), masterplan.key(text, "status")
    if parent is None or status not in ("open", DONE):
        return None
    master = masterplan.find(path.parent.parent, parent)
    if master is None:
        return {"skipped": f"plan {parent:04d}, the `parent` of {slug}, has no folder in this checkout: a row it has "
                           f"for {slug} is not ticked here (restock, or mark the step from the field that holds it)"}
    if not masterplan.of(master):
        return None
    home, lines = masterplan.slug_of(master), masterplan.raw(master).split("\n")
    found = table.header(lines)
    if found is None:
        return {"skipped": f"masterplan {home} has no step table: no row links {slug}"}
    at, cols = found
    width, written, skipped, linked = table.width(lines, at), [], [], False
    for i, cells in table.rows(lines, at):
        misfit = table.misfit(cells, width)
        link = masterplan.LINK.search(" ".join(cells) if misfit else cells[cols["step"]])
        if link is None or link.group(1) != slug:
            continue
        linked = True
        if misfit:
            number = cells[cols["#"]] if cols["#"] < len(cells) else "?"
            skipped.append(f"row {number} of masterplan {home} is not written: it {misfit}")
        elif (status == DONE) != bool(ROW_DONE.fullmatch(cells[cols["status"]])):
            cells[cols["status"]] = DONE if status == DONE else REOPENED
            lines[i] = table.join_row(cells) + table.eol(lines[i])
            written.append(cells[cols["#"]])
    if written:
        masterplan.write(master, "\n".join(lines))
    if not linked:
        skipped.append(f"no row of masterplan {home} links {slug}")
    out = {"masterplan": home, "row": ", ".join(written), "status": DONE if status == DONE else REOPENED}
    return {**(out if written else {}), **({"skipped": "; ".join(skipped)} if skipped else {})} or None


def report(ticked: dict | None) -> dict:
    """What `plan.py status` adds to its JSON for a tick: `tick` (the written one) and `tick_skipped` (why not)."""
    out = dict(ticked or {})
    why = out.pop("skipped", None)
    return {**({"tick": out} if out else {}), **({"tick_skipped": why} if why else {})}


def named(plans: Path, ref: str) -> Path | None:
    """The plan file a `CURRENT_PLAN` holding `ref` names: plans/<slug>/plan.md, or a flat plans/<slug>.md."""
    return next((p for p in (plans / ref / MAIN, plans / f"{ref}.md") if p.is_file()), None)


def unfinished_master(path: Path, steps_of) -> Path | None:
    """The masterplan of the plan at `path` when it still has an open row; None for a plan of none, a masterplan
    this checkout does not hold and one that is done or abandoned."""
    parent = masterplan.parent_of(masterplan.read(path))
    master = masterplan.find(path.parent.parent, parent) if parent is not None and path.name == MAIN else None
    if master is None or not masterplan.of(master):
        return None
    if masterplan.key(masterplan.read(master), "status") in masterplan.FINISHED:
        return None
    return master if any(not is_done(s["status"]) for s in steps_of(master)) else None


def leave(pointer: Path, steps_of, release: bool = False) -> dict:
    """`plan.py leave`, after a bring in: what the checkout's `pointer` (plans/CURRENT_PLAN) holds from now on.
    `steps_of(plan.md)` gives a plan's step rows. Prints nothing; the result is {was, current, action, line}:

    - `none`: the file is missing or names nothing (an empty one, also of whitespace only, is deleted);
    - `kept`: it names a plan with open steps (also a masterplan with open rows), a plan without steps that is not
      `done` or a plan this checkout does not hold: left alone;
    - `masterplan`: the plan is finished and its masterplan is not: the file names the masterplan now, the field
      goes on with its next plan;
    - `deleted`: the plan is finished and belongs to no unfinished masterplan (a masterplan's last plan too), or the
      file named a shot or a task: the work is in, the file is gone. With `release` (`leave --release`: the field
      does not carry on with the masterplan) also where the file would name the masterplan or names it already.
    - `restored`: the work is in and plans/PREVIOUS_PLAN (a `--here` switch, D4) keeps a plan still unfinished: the
      file names it again and PREVIOUS_PLAN goes (D5); `release` drops PREVIOUS_PLAN without restoring it.
    A plan of schema 2 is finished when its derived status is `uat` or `done` (D15), kept while it is `open`."""
    was = pointer.read_text(encoding="utf-8").strip() if pointer.is_file() else ""

    def result(action: str, line: str, current: str = "") -> dict:
        return {"was": was, "current": current, "action": action, "line": line}

    def restored(why: str) -> dict | None:
        root = pointer.parent.parent
        if release:
            (root / occupied.PREVIOUS).unlink(missing_ok=True)
            return None
        back = occupied.restore_previous(root)
        return result("restored", f"{POINTER} names {back} again, kept by a --here switch: {why}", back) if back else None

    def deleted(why: str) -> dict:
        if (back := restored(why)) is not None:
            return back
        pointer.unlink()
        return result("deleted", f"{POINTER} deleted: {why}")

    if not was and pointer.is_file():
        pointer.unlink()
        return result("none", f"{POINTER} named nothing: the empty file is deleted")
    if not was:
        return result("none", f"{POINTER} names nothing")
    path = named(pointer.parent, was) if masterplan.SLUG.match(was) else None
    if path is None and masterplan.SLUG.match(was):
        return result("kept", f"{POINTER} keeps naming {was}: this checkout holds no such plan", was)
    if path is None:
        return deleted(f"it named {was}, which is in")
    if release and masterplan.of(path):
        return deleted(f"the field is released from the masterplan {was} and is free again")
    steps = steps_of(path)
    shaped = path.name == MAIN and shape.is_shape(path.parent)
    still = ["open"] if shaped and occupied.status_of(path) == "open" else \
        [] if shaped else [s["number"] for s in steps if not is_done(s["status"])]
    part = "row" if masterplan.of(path) else "step"
    bare = not shaped and not steps and masterplan.key(masterplan.read(path), "status") != DONE
    if still or bare:
        why = f"{part}(s) {', '.join(still)} open" if still else f"it has no {part}"
        return result("kept", f"{POINTER} keeps naming {was}: {why}", was)
    master = unfinished_master(path, steps_of)
    if master is None:
        return deleted(f"{was} is finished")
    if (back := restored(f"{was} is finished")) is not None:
        return back
    home = masterplan.slug_of(master)
    row = masterplan.row_of(path, int(home[:4]))
    its = f"{was}, its row {row}," if row else was
    if release:
        return deleted(f"{its} is finished and the field is released from the masterplan {home}: it is free again")
    pointer.write_text(home + "\n", encoding="utf-8")
    return result("masterplan", f"{POINTER} names the masterplan {home} now: {its} is finished and the field goes "
                                "on with the masterplan's next plan", home)


def finishable(master: Path, steps_of) -> list[dict]:
    """The plans of the masterplan at `master` whose open steps are all checked after the landing, as this checkout
    holds them: each row's number, its plan and those steps' numbers. A row without a plan here is left out."""
    out = []
    for row in masterplan.rows(masterplan.read(master)):
        path = master.parent.parent / row["plan"] / MAIN if row["plan"] else None
        if path is None or not path.is_file():
            continue
        still = [s for s in steps_of(path) if not is_done(s["status"])]
        if still and all(s.get("after_landing") for s in still):
            out.append({"row": row["number"], "plan": row["plan"], "steps": [s["number"] for s in still]})
    return out
