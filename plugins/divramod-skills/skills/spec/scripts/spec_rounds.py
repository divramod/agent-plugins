"""spec_rounds.py: the rounds of a spec (hal2 plan 0502, D6 and D8): `iterate`, `update`, `abandon`, `reviewed`.

Each takes spec.py's module as `S` (its resolve, describe and SpecError; spec.py imports this module, so it cannot
import spec back) and returns spec.py's JSON answer.

  iterate(S, root, ref)           one round of a draft spec done: iteration + 1, the plan's Brief re-seeded, the
                                  answer carries the checkpoint: plan now, bring in for later or another round, the
                                  recommended one first ("plan now" only when nothing is left open, D8 idea 1)
  update(S, root, ref, what)      a new round on any spec, also an approved one or one whose plan has steps (D6):
                                  status back to draft, iteration + 1; a plan with steps gets `spec_review: <iteration>`
                                  in its front matter (its Brief and steps are never rewritten), until `reviewed`
  abandon(S, root, ref)           the spec and its still unplanned plan abandoned; a planned one is refused
  reviewed(S, root, ref)          the plan's review flag cleared
  grilled(S, root, ref, how)      `grilled: <date> (<how>)` stamped on spec.md and its plan.md (/grill-plan, step 5)
"""
import datetime as dt
import re
from pathlib import Path

import envelope  # noqa: E402  (the plan skill's, on the path through spec.py)
import spec_plan  # noqa: E402

SPEC, PLAN, QUESTIONS = "spec.md", "plan.md", "questions.md"
REVIEW = "spec_review"
BULLET = re.compile(r"^\s*[-*]\s+(.*)$")
OPEN_Q = re.compile(r"^Q\d+\b.*·\s*open\s*$")
OPTIONS = (("plan_now", "plan now"), ("bring_in", "bring in for later"), ("another_round", "another round"))


def items(text: str) -> list[str]:
    """The bullets of a section that say something (`- none` and an empty line do not)."""
    found = [m.group(1).strip() for m in map(BULLET.match, text.splitlines()) if m]
    return [i for i in found if i and i.rstrip(".").lower() != "none"]


def open_plan_questions(folder: Path) -> int:
    path = folder / QUESTIONS
    if not path.is_file():
        return 0
    return sum(1 for head, _ in envelope.entries(envelope.split(path.read_text())[1]) if OPEN_Q.match(head))


def checkpoint(info: dict, folder: Path) -> dict:
    """The three options after a round, the recommended first; `open` says what keeps "plan now" from being it."""
    sections = info["sections"]
    left = {"placeholders": len(info["placeholders"]), "not_yet_specified": items(sections.get("Not yet specified", "")),
            "open_questions": items(sections.get("Open questions", "")), "plan_questions": open_plan_questions(folder)}
    ready = not (left["placeholders"] or left["not_yet_specified"] or left["open_questions"] or left["plan_questions"])
    best = "plan_now" if ready else "another_round"
    options = [{"id": i, "label": label, "recommended": i == best} for i, label in OPTIONS]
    options.sort(key=lambda o: not o["recommended"])
    return {"iteration": info["iteration"], "recommended": best, "options": options, "open": left}


def bump(S, root: Path, folder: Path, status: str) -> None:
    """spec.md: iteration + 1 and the status."""
    path = folder / SPEC
    text = path.read_text()
    meta = envelope.parse(envelope.split(text)[0] or "")
    text = envelope.set_key(text, "iteration", str(int(meta.get("iteration") or 0) + 1))
    path.write_text(envelope.set_key(text, "status", status))


def iterate(S, root: Path, ref: str | None) -> dict:
    folder = S.resolve(root, ref)
    status = S.describe(root, folder)["status"]
    if status != "draft":
        raise S.SpecError(f"{folder.name}: the spec is {status}, not a draft: a new round on it is "
                          f"`spec.py update {folder.name[:4]}`")
    bump(S, root, folder, "draft")
    info = S.describe(root, folder)
    spec_plan.reseed(folder, info)
    return {**info, "checkpoint": checkpoint(info, folder)}


def update(S, root: Path, ref: str | None, what: str = "") -> dict:
    folder = S.resolve(root, ref)
    if S.describe(root, folder)["status"] == "abandoned":
        raise S.SpecError(f"{folder.name}: the spec is abandoned: nothing to update")
    bump(S, root, folder, "draft")
    info = S.describe(root, folder)
    flagged = spec_plan.has_steps(folder)
    if flagged:  # D6: the plan's Brief and steps are flagged for review, never rewritten
        envelope_set(folder / PLAN, REVIEW, str(info["iteration"]))
    else:
        spec_plan.reseed(folder, info)
    return {**S.describe(root, folder), "what": what, "flagged": flagged, "checkpoint": checkpoint(info, folder)}


def abandon(S, root: Path, ref: str | None) -> dict:
    folder = S.resolve(root, ref)
    if S.describe(root, folder)["status"] == "abandoned":
        raise S.SpecError(f"{folder.name}: the spec is already abandoned")
    if spec_plan.has_steps(folder):
        raise S.SpecError(f"{folder.name}: the plan has steps (it was planned): abandon the plan, not the spec")
    path = folder / SPEC
    path.write_text(envelope.set_key(path.read_text(), "status", "abandoned"))
    if spec_plan.state(folder) == "spec":
        spec_plan.set_status(folder, "abandoned")
    return S.describe(root, folder)


def reviewed(S, root: Path, ref: str | None) -> dict:
    folder = S.resolve(root, ref)
    if (folder / PLAN).is_file():
        envelope_set(folder / PLAN, REVIEW, None)
    return S.describe(root, folder)


def grilled(S, root: Path, ref: str | None, how: str = "") -> dict:
    folder = S.resolve(root, ref)
    value = envelope.quote(f"{dt.date.today().isoformat()} ({' '.join(how.split())})" if how.strip()
                           else dt.date.today().isoformat())
    for name in (SPEC, PLAN):
        if (folder / name).is_file():
            envelope_set(folder / name, "grilled", value)
    return S.describe(root, folder)


def envelope_set(path: Path, key: str, raw: str | None) -> None:
    text = path.read_text()
    if (new := envelope.set_key(text, key, raw)) != text:
        path.write_text(new)
