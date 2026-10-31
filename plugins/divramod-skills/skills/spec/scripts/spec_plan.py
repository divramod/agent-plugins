"""spec_plan.py: the plan a spec lives in (hal2 plan 0502, D7): `plan.md` in state `spec` beside spec.md, with the
ledgers and the handoff the plan skill's folder module writes; no step table until `/plan` fills it. The Brief is
the spec's text (the plan skill's spec_link.brief_values) while the plan has no steps; once it has any, the Brief and
the steps are the plan's own and a spec update only flags them for review (D6, spec_rounds.py).

  write(root, folder, number, title, description, seed_line)   plan.md and the ledgers into `folder`
  state(folder)       -> the plan.md's status (`spec`, `open`, ...), "" without a plan.md
  has_steps(folder)   -> True when the plan has step rows or sub-plans (it was planned)
  reseed(folder, info)  rewrite the Brief of a spec-state plan from the spec's sections (`info` is spec.describe's)
  set_status(folder, status)   plan.md's status; an abandoned plan closes its ledgers and handoff with it
"""
import re
from pathlib import Path

import envelope  # noqa: E402  (the plan skill's, on the path through spec.py)
import folder as plan_folder  # noqa: E402
import spec_link  # noqa: E402

PLAN = "plan.md"
TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / PLAN
ROW = re.compile(r"^\|\s*\d+\s*\|", re.M)
BRIEF = re.compile(r"(## Brief\n\n)(.*?)(?=\n## )", re.S)
POINT = {"In": "Scope", "Out": "Scope", "Must": "Requirements", "Proof": "Acceptance criteria"}


def write(root: Path, folder: Path, number: int, title: str, description: str, seed_line: str = "") -> None:
    """plan.md in state spec (over the one a store claim made) and the ledgers and the handoff beside it."""
    values = plan_folder.fields(root, number, title, description, "auto")
    values["description"] = envelope.quote(description)
    path = folder / PLAN
    path.write_text(TEMPLATE.read_text().format(seed_line=f"{seed_line}\n" if seed_line else "", **values))
    plan_folder.scaffold(path, values)


def state(folder: Path) -> str:
    path = folder / PLAN
    return str(envelope.get(path.read_text(), "status") or "") if path.is_file() else ""


def has_steps(folder: Path) -> bool:
    path = folder / PLAN
    if not path.is_file():
        return False
    _, body = envelope.split(path.read_text())
    return bool(ROW.search(envelope.section(body, "Steps"))) or (folder / "subplans").is_dir()


def reseed(folder: Path, info: dict) -> None:
    """The Brief of a plan still in state spec, from the spec's current text; a label the spec says nothing for
    keeps a pointer line. A plan with steps keeps its own Brief."""
    path = folder / PLAN
    if state(folder) != "spec" or has_steps(folder):
        return
    values = spec_link.brief_values(info, [])
    lines = [f"- {label}: " + ("\n  ".join(found) if found else f"not written yet ({POINT[label]} of [spec.md](spec.md))")
             for label, found in values.items()]
    path.write_text(BRIEF.sub(lambda m: m.group(1) + "\n".join(lines) + "\n", path.read_text(), count=1))


def set_status(folder: Path, status: str) -> None:
    path = folder / PLAN
    plan_folder.write_key(path, "status", status)
    if status == "abandoned":
        for name in plan_folder.SIBLINGS:
            other = folder / name
            if other.is_file() and plan_folder.is_record(other.read_text()):
                plan_folder.write_key(other, "status", "closed")
